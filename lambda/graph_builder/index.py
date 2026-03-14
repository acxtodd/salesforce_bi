"""
Graph Builder Lambda Function for Phase 3 Graph Enhancement.

Builds relationship graphs from Salesforce records during ingestion.
Creates nodes and edges in DynamoDB for multi-hop relationship queries.

**Feature: phase3-graph-enhancement**
**Requirements: 2.1, 2.2, 2.3, 2.4, 5.1, 5.2, 5.3, 5.5, 10.1-10.4, 6.1, 6.3**
"""
import json
import os
import re
import time
import boto3
from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict

# Initialize clients
dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')

# Import metrics module (Task 9.1)
try:
    from graph_metrics import get_build_metrics, GraphBuildMetrics
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    GraphBuildMetrics = None

# Environment variables
GRAPH_NODES_TABLE = os.environ.get('GRAPH_NODES_TABLE', 'salesforce-ai-search-graph-nodes')
GRAPH_EDGES_TABLE = os.environ.get('GRAPH_EDGES_TABLE', 'salesforce-ai-search-graph-edges')

# Module-level table references for use in GraphBuilder class
_nodes_table = dynamodb.Table(GRAPH_NODES_TABLE)

# Default configuration when IndexConfiguration__mdt is not available
DEFAULT_CONFIG = {
    'Graph_Enabled__c': True,
    'Relationship_Depth__c': 2,
    'Relationship_Fields__c': None,  # None means all relationship fields
    'Graph_Node_Attributes__c': None,  # None means use defaults
}

# Import configuration cache (Task 8.5)
try:
    from graph_builder.config_cache import (
        get_config_cache, get_object_config, invalidate_config_cache
    )
    CONFIG_CACHE_AVAILABLE = True
except ImportError:
    CONFIG_CACHE_AVAILABLE = False
    # Fallback functions when cache module not available
    def get_object_config(sobject: str) -> Dict[str, Any]:
        return DEFAULT_CONFIG.copy()
    def invalidate_config_cache(sobject: Optional[str] = None) -> None:
        pass

# Import schema loader for zero-config schema discovery (Task 3.1)
SCHEMA_LOADER_AVAILABLE = False
try:
    from schema_loader import (
        load_schema, clear_memory_cache, is_schema_available
    )
    SCHEMA_LOADER_AVAILABLE = True
except ImportError:
    # Fallback for local development/tests
    try:
        from graph_builder.schema_loader import (
            load_schema, clear_memory_cache, is_schema_available
        )
        SCHEMA_LOADER_AVAILABLE = True
    except ImportError:
        pass

# Fallback stubs if schema loader not available
if not SCHEMA_LOADER_AVAILABLE:
    def load_schema(sobject: str, use_memory_cache: bool = True):
        return None
    def clear_memory_cache(sobject=None):
        pass
    def is_schema_available(sobject: str) -> bool:
        return False

# Display name priority rules for extracting node display names
DISPLAY_NAME_PRIORITY = ['Name', 'Subject', 'Title', 'Id']

# NOTE: POC_OBJECT_FIELDS has been removed as part of zero-config-production
# All object configuration is now fetched dynamically from:
# 1. IndexConfiguration__mdt (Salesforce Custom Metadata)
# 2. Schema Cache (auto-discovered via Describe API)
# 3. Default configuration
# See config_cache.py for implementation details.


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class GraphNode:
    """
    Represents a node in the graph database.

    Corresponds to items in salesforce-ai-search-graph-nodes DynamoDB table.
    """
    nodeId: str
    type: str
    displayName: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    sharingBuckets: List[str] = field(default_factory=list)
    ownerId: Optional[str] = None
    depth: int = 0
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updatedAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ttl: Optional[int] = None

    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format."""
        item = {
            'nodeId': self.nodeId,
            'type': self.type,
            'displayName': self.displayName,
            'attributes': self.attributes,
            'sharingBuckets': self.sharingBuckets,
            'depth': self.depth,
            'createdAt': self.createdAt,
            'updatedAt': self.updatedAt,
        }
        if self.ownerId:
            item['ownerId'] = self.ownerId
        if self.ttl is not None:
            item['ttl'] = self.ttl
        return item

    def validate(self) -> bool:
        """Validate node structure completeness (Property 2)."""
        return (
            bool(self.nodeId) and
            bool(self.type) and
            self.displayName is not None and
            self.attributes is not None and
            isinstance(self.attributes, dict)
        )


@dataclass
class GraphEdge:
    """
    Represents an edge (relationship) in the graph database.

    Corresponds to items in salesforce-ai-search-graph-edges DynamoDB table.
    """
    fromId: str
    toId: str
    type: str
    fieldName: str
    direction: str  # 'parent' or 'child'
    createdAt: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def toIdType(self) -> str:
        """Composite sort key for DynamoDB."""
        return f"{self.toId}#{self.type}"

    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format."""
        return {
            'fromId': self.fromId,
            'toIdType': self.toIdType,
            'toId': self.toId,
            'type': self.type,
            'fieldName': self.fieldName,
            'direction': self.direction,
            'createdAt': self.createdAt,
        }

    def validate(self) -> bool:
        """Validate edge structure completeness (Property 3)."""
        return (
            bool(self.fromId) and
            bool(self.toId) and
            bool(self.type) and
            bool(self.fieldName) and
            self.direction in ('parent', 'child')
        )


@dataclass
class Graph:
    """Container for nodes and edges built from a record."""
    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    edges: List[GraphEdge] = field(default_factory=list)

    def add_node(self, node: GraphNode) -> None:
        """Add node to graph (skip if already exists)."""
        if node.nodeId not in self.nodes:
            self.nodes[node.nodeId] = node

    def add_edge(self, edge: GraphEdge) -> None:
        """Add edge to graph."""
        self.edges.append(edge)


# =============================================================================
# Graph Builder
# =============================================================================

class GraphBuilder:
    """
    Builds relationship graphs from Salesforce records.

    **Requirements: 2.1, 2.2, 2.3, 2.4**
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize GraphBuilder with configuration.

        Args:
            config: Optional configuration from IndexConfiguration__mdt
        """
        self.config = config or DEFAULT_CONFIG
        self._visited: Set[str] = set()  # Track visited nodes to handle circular refs

    def build_relationship_graph(
        self,
        record: Dict[str, Any],
        sobject: str,
        max_depth: Optional[int] = None
    ) -> Graph:
        """
        Build graph representation of record and its relationships.

        **Requirements: 2.1, 2.4**
        **Feature: zero-config-production**
        **Requirements: 4.5**

        Args:
            record: Salesforce record data
            sobject: Object type (e.g., 'Account', 'ascendix__Property__c')
            max_depth: Override for relationship depth (1-3)

        Returns:
            Graph containing nodes and edges (empty if Graph_Enabled__c = false)
        """
        graph = Graph()
        self._visited.clear()

        # Check if graph building is enabled for this object (Requirement 4.5)
        if not self.config.get('Graph_Enabled__c', True):
            print(f"Graph building disabled for {sobject} via Graph_Enabled__c")
            return graph  # Return empty graph

        # Determine max depth from config or parameter
        depth = max_depth or self.config.get('Relationship_Depth__c', 2)
        depth = max(1, min(3, depth))  # Clamp to 1-3

        # Create root node
        root_node = self.create_node(record, sobject, depth=0)
        if root_node and root_node.validate():
            graph.add_node(root_node)
            self._visited.add(root_node.nodeId)

            # Traverse relationships
            self.traverse_relationships(record, sobject, graph, depth, current_depth=0)

        return graph

    def traverse_relationships(
        self,
        record: Dict[str, Any],
        sobject: str,
        graph: Graph,
        max_depth: int,
        current_depth: int
    ) -> None:
        """
        Recursively traverse relationships to build graph.

        **Requirements: 2.4, 5.2**

        Args:
            record: Current record data
            sobject: Object type
            graph: Graph to populate
            max_depth: Maximum traversal depth (1-3)
            current_depth: Current depth in traversal
        """
        # Stop at configured depth
        if current_depth >= max_depth:
            return

        record_id = record.get('Id')
        if not record_id:
            return

        # Get relationship fields for this object
        relationship_fields = self._get_relationship_fields(sobject)

        for field_name in relationship_fields:
            related_id = record.get(field_name)
            if not related_id or related_id in self._visited:
                continue

            # Determine related object type from field name
            related_type = self._infer_object_type(field_name, sobject)

            # Create edge from current record to related record
            # NOTE: edge.type must be the type of fromId (source node) so traversal
            # can find edges by matching type == target_type
            edge = self.create_edge(
                from_id=record_id,
                to_id=related_id,
                relationship_type=sobject,  # Type of source (fromId) node
                field_name=field_name,
                direction='parent'  # Current record points to parent
            )
            if edge and edge.validate():
                graph.add_edge(edge)

            # Create node for related record (with limited attributes)
            related_node = GraphNode(
                nodeId=related_id,
                type=related_type,
                displayName=related_id,  # We don't have the full record
                attributes={},
                depth=current_depth + 1
            )
            if related_node.validate():
                graph.add_node(related_node)
                self._visited.add(related_id)

            # Also create reverse edge for bidirectional traversal
            # NOTE: edge.type must be the type of fromId (source node)
            reverse_edge = self.create_edge(
                from_id=related_id,
                to_id=record_id,
                relationship_type=related_type,  # Type of source (fromId) node
                field_name=field_name,
                direction='child'  # Related record points to child
            )
            if reverse_edge and reverse_edge.validate():
                graph.add_edge(reverse_edge)

            # Check for nested relationship data (__r fields)
            rel_field_name = field_name.replace('__c', '__r').replace('Id', '')
            nested_data = record.get(rel_field_name)
            if nested_data and isinstance(nested_data, dict):
                # Update node with actual data from nested record
                updated_node = self.create_node(nested_data, related_type, current_depth + 1)
                if updated_node and updated_node.validate():
                    graph.nodes[related_id] = updated_node

                # Recursively traverse nested record's relationships
                # Only if nested data contains relationship fields
                if current_depth + 1 < max_depth:
                    self.traverse_relationships(
                        nested_data, related_type, graph, max_depth, current_depth + 1
                    )

    def create_node(
        self,
        record: Dict[str, Any],
        sobject: str,
        depth: int = 0
    ) -> Optional[GraphNode]:
        """
        Create node with ID, type, display name, and key attributes.

        **Requirements: 2.2, 5.3**
        **Zero-Config Enhancement**: Inherits filterable attributes from parent nodes

        Args:
            record: Salesforce record data
            sobject: Object type
            depth: Depth from root node

        Returns:
            GraphNode instance or None if invalid
        """
        record_id = record.get('Id')
        if not record_id:
            return None

        # Extract display name using priority rules
        display_name = self._extract_display_name(record, sobject)

        # Extract key attributes based on configuration
        attributes = self._extract_attributes(record, sobject)

        # Zero-Config: Inherit filterable attributes from parent nodes
        # This enables filtering child objects by parent attributes
        # (e.g., find Availabilities in Class A Properties)
        inherited = self._inherit_parent_attributes(record, sobject)
        for key, value in inherited.items():
            if key not in attributes:  # Don't override existing attributes
                attributes[key] = value

        # Extract sharing buckets for authorization
        sharing_buckets = record.get('sharingBuckets', [])
        if isinstance(sharing_buckets, str):
            sharing_buckets = [sharing_buckets]

        # Get owner ID
        owner_id = record.get('OwnerId')

        return GraphNode(
            nodeId=record_id,
            type=sobject,
            displayName=display_name,
            attributes=attributes,
            sharingBuckets=sharing_buckets,
            ownerId=owner_id,
            depth=depth
        )

    def _inherit_parent_attributes(
        self,
        record: Dict[str, Any],
        sobject: str
    ) -> Dict[str, Any]:
        """
        Zero-Config: Inherit filterable attributes from parent nodes.

        Looks up relationship fields in the record, fetches the parent node
        from the graph-nodes table, and returns its filterable attributes.

        This enables queries like "Availabilities in Class A Properties" by
        copying Property's ascendix__PropertyClass__c to the Availability node.

        Args:
            record: Child record with relationship field IDs
            sobject: Child object type

        Returns:
            Dictionary of inherited attributes from parent nodes
        """
        inherited = {}

        # Get relationship fields for this object
        relationship_fields = self._get_relationship_fields(sobject)
        print(f"[INHERIT] {sobject} relationship_fields: {relationship_fields}")
        print(f"[INHERIT] record keys: {list(record.keys())}")

        # Skip owner and generic relationships - focus on business objects
        skip_fields = {'OwnerId', 'ParentId', 'AccountId', 'ContactId'}

        for field_name in relationship_fields:
            if field_name in skip_fields:
                continue

            parent_id = record.get(field_name)
            print(f"[INHERIT] Checking {field_name} -> {parent_id}")
            if not parent_id:
                continue

            # Try to fetch parent node from graph-nodes table
            try:
                parent_attrs = self._fetch_parent_node_attributes(parent_id)
                print(f"[INHERIT] Parent {parent_id} attrs: {parent_attrs}")
                if parent_attrs:
                    # Copy all filterable attributes from parent
                    for attr_name, attr_value in parent_attrs.items():
                        if attr_name not in inherited:
                            inherited[attr_name] = attr_value
            except Exception as e:
                print(f"[INHERIT] Error fetching parent {parent_id}: {e}")

        print(f"[INHERIT] Final inherited attrs: {inherited}")
        return inherited

    def _fetch_parent_node_attributes(self, parent_id: str) -> Dict[str, Any]:
        """
        Fetch a parent node's attributes from the graph-nodes table.

        Args:
            parent_id: The parent node ID (Salesforce record ID)

        Returns:
            Dictionary of parent node attributes, or empty dict if not found
        """
        try:
            response = _nodes_table.get_item(Key={'nodeId': parent_id})
            item = response.get('Item')
            if item and 'attributes' in item:
                print(f"[INHERIT] Fetched parent {parent_id} attributes: {item['attributes']}")
                return item['attributes']
            else:
                print(f"[INHERIT] Parent {parent_id} not found or has no attributes")
        except Exception as e:
            print(f"[INHERIT] Error fetching parent {parent_id}: {e}")
        return {}

    def create_edge(
        self,
        from_id: str,
        to_id: str,
        relationship_type: str,
        field_name: str,
        direction: str
    ) -> Optional[GraphEdge]:
        """
        Create edge with relationship metadata.

        **Requirements: 2.3**

        Args:
            from_id: Source node ID
            to_id: Target node ID
            relationship_type: Type of related object
            field_name: Relationship field name
            direction: 'parent' or 'child'

        Returns:
            GraphEdge instance or None if invalid
        """
        if not from_id or not to_id or from_id == to_id:
            return None

        return GraphEdge(
            fromId=from_id,
            toId=to_id,
            type=relationship_type,
            fieldName=field_name,
            direction=direction
        )

    def handle_incremental_update(
        self,
        operation: str,
        record: Dict[str, Any],
        sobject: str
    ) -> Dict[str, Any]:
        """
        Handle CREATE, UPDATE, DELETE operations on graph.

        **Requirements: 10.1, 10.2, 10.3, 10.4**

        Args:
            operation: 'CREATE', 'UPDATE', or 'DELETE'
            record: Salesforce record data
            sobject: Object type

        Returns:
            Result with operation status
        """
        record_id = record.get('Id')
        if not record_id:
            return {'success': False, 'error': 'No record ID'}

        if operation == 'CREATE':
            return self._handle_create(record, sobject)
        elif operation == 'UPDATE':
            return self._handle_update(record, sobject)
        elif operation == 'DELETE':
            return self._handle_delete(record_id)
        else:
            return {'success': False, 'error': f'Unknown operation: {operation}'}

    def _handle_create(self, record: Dict[str, Any], sobject: str) -> Dict[str, Any]:
        """Handle CREATE operation - add new node and edges."""
        graph = self.build_relationship_graph(record, sobject)
        return {
            'success': True,
            'operation': 'CREATE',
            'nodeCount': len(graph.nodes),
            'edgeCount': len(graph.edges),
            'graph': graph
        }

    def _handle_update(self, record: Dict[str, Any], sobject: str) -> Dict[str, Any]:
        """Handle UPDATE operation - update node and re-evaluate edges."""
        # For updates, we rebuild the graph which will update attributes
        graph = self.build_relationship_graph(record, sobject)
        return {
            'success': True,
            'operation': 'UPDATE',
            'nodeCount': len(graph.nodes),
            'edgeCount': len(graph.edges),
            'graph': graph
        }

    def _handle_delete(self, record_id: str) -> Dict[str, Any]:
        """Handle DELETE operation - return IDs to delete."""
        return {
            'success': True,
            'operation': 'DELETE',
            'nodeIdToDelete': record_id,
            # Edges will be cleaned up in store_graph
        }

    def _get_relationship_fields(self, sobject: str) -> List[str]:
        """
        Get relationship fields for object type using configuration and schema.
        
        **Feature: zero-config-production**
        **Requirements: 4.1**
        
        Priority order:
        1. Configuration (Relationship_Fields__c from IndexConfiguration__mdt)
        2. Schema Cache (auto-discovered relationship fields)
        3. Default fallback fields (OwnerId, AccountId, ParentId)
        
        Args:
            sobject: Salesforce object API name
            
        Returns:
            List of relationship field names
        """
        # Step 1: Check if configuration specifies specific fields
        configured_fields = self.config.get('Relationship_Fields__c')
        if configured_fields:
            return [f.strip() for f in configured_fields.split(',') if f.strip()]

        # Step 2: Fall back to Schema Cache (auto-discovered relationships)
        if SCHEMA_LOADER_AVAILABLE:
            schema = load_schema(sobject)
            if schema is not None:
                relationship_fields = schema.get_all_relationship_field_names()
                if relationship_fields:
                    return relationship_fields

        # Step 3: Fallback to common relationship fields
        return ['OwnerId', 'AccountId', 'ParentId']

    def _extract_display_name(self, record: Dict[str, Any], sobject: str) -> str:
        """
        Extract display name using configuration.
        
        **Feature: zero-config-production**
        **Requirements: 4.3**
        
        Priority order:
        1. Display_Name_Field__c from configuration
        2. Default priority rules (Name, Subject, Title, Id)
        3. Fallback to record ID
        
        Args:
            record: Salesforce record data
            sobject: Object type
            
        Returns:
            Display name string
        """
        # Step 1: Check configuration for Display_Name_Field__c
        display_field = self.config.get('Display_Name_Field__c')
        if display_field and display_field in record and record[display_field]:
            return str(record[display_field])

        # Step 2: Use default priority rules
        for field in DISPLAY_NAME_PRIORITY:
            if field in record and record[field]:
                return str(record[field])

        # Step 3: Fallback to ID
        return record.get('Id', 'Unknown')

    def _extract_attributes(self, record: Dict[str, Any], sobject: str) -> Dict[str, Any]:
        """
        Extract key attributes based on schema or configuration.
        
        **Feature: zero-config-schema-discovery**
        **Requirements: 2.2, 2.3, 2.4, 2.5**
        
        Priority order:
        1. Schema from cache (if available) - extracts ALL filterable fields
        2. Configuration (Graph_Node_Attributes__c from IndexConfiguration__mdt)
        3. Zero-config fallback (extract all non-system fields from record)
        4. Fallback to ['Name']
        
        Type handling:
        - Filterable fields (picklists): stored as strings
        - Numeric fields: stored as numbers (int/float)
        - Date fields: stored in ISO 8601 format
        """
        attributes = {}

        # Try to load schema from cache first (zero-config approach)
        schema = None
        if SCHEMA_LOADER_AVAILABLE:
            schema = load_schema(sobject)

        if schema is not None:
            # Schema-driven attribute extraction
            attributes = self._extract_attributes_from_schema(record, schema)
        else:
            # Fallback to configuration or zero-config defaults
            attributes = self._extract_attributes_from_config(record, sobject)
        
        return attributes
    
    def _extract_attributes_from_schema(
        self, 
        record: Dict[str, Any], 
        schema: Any
    ) -> Dict[str, Any]:
        """
        Extract attributes using discovered schema.
        
        **Requirements: 2.2, 2.3, 2.4**
        
        Populates ALL filterable field values as node attributes with correct types:
        - Filterable (picklist) fields: stored as strings
        - Numeric fields: stored as number types (int/float)
        - Date fields: stored in ISO 8601 format
        
        Args:
            record: Salesforce record data
            schema: ObjectSchema from schema discovery
            
        Returns:
            Dictionary of attributes with correct types
        """
        attributes = {}

        # Extract filterable fields (picklists) as strings
        for field_schema in schema.filterable:
            field_name = field_schema.name
            if field_name in record and record[field_name] is not None:
                attributes[field_name] = str(record[field_name])
        
        # Extract numeric fields as numbers (Requirements 2.3)
        for field_schema in schema.numeric:
            field_name = field_schema.name
            if field_name in record and record[field_name] is not None:
                value = record[field_name]
                # Preserve numeric type
                if isinstance(value, (int, float)):
                    attributes[field_name] = value
                else:
                    # Try to convert string to number
                    try:
                        if '.' in str(value):
                            attributes[field_name] = float(value)
                        else:
                            attributes[field_name] = int(value)
                    except (ValueError, TypeError):
                        # If conversion fails, store as string
                        attributes[field_name] = str(value)
        
        # Extract date fields in ISO 8601 format (Requirements 2.4)
        for field_schema in schema.date:
            field_name = field_schema.name
            if field_name in record and record[field_name] is not None:
                value = record[field_name]
                # Ensure ISO 8601 format
                if isinstance(value, str):
                    # Already a string, assume ISO format or convert
                    if 'T' not in value and len(value) == 10:
                        # Date only format (YYYY-MM-DD), add time component
                        attributes[field_name] = f"{value}T00:00:00Z"
                    else:
                        attributes[field_name] = value
                else:
                    # Convert to ISO string
                    attributes[field_name] = str(value)
        
        # Extract text fields (Requirements: text filtering)
        # This ensures fields like City, State, Zip are included
        for field_schema in schema.text:
            field_name = field_schema.name
            if field_name in record and record[field_name] is not None:
                attributes[field_name] = str(record[field_name])

        # Also include Name field if present (for display purposes)
        if 'Name' in record and record['Name'] is not None:
            attributes['Name'] = str(record['Name'])
        
        return attributes
    
    def _extract_attributes_from_config(
        self,
        record: Dict[str, Any],
        sobject: str
    ) -> Dict[str, Any]:
        """
        Extract attributes using IndexConfiguration__mdt configuration.

        **Feature: zero-config-production**
        **Requirements: 4.2**

        When schema discovery is not available, this function extracts fields
        from Graph_Node_Attributes__c configuration. Falls back to extracting
        all non-system fields from the record.

        Args:
            record: Salesforce record data
            sobject: Object type

        Returns:
            Dictionary of attributes
        """
        attributes = {}

        # Debug: Log config and record keys
        print(f"[ATTR_DEBUG] sobject={sobject}, config keys: {list(self.config.keys())}")
        print(f"[ATTR_DEBUG] Graph_Node_Attributes__c = {self.config.get('Graph_Node_Attributes__c')}")
        print(f"[ATTR_DEBUG] record keys: {list(record.keys())}")

        # Step 1: Check if configuration specifies specific attributes
        configured_attrs = self.config.get('Graph_Node_Attributes__c')
        if configured_attrs:
            attr_fields = [f.strip() for f in configured_attrs.split(',') if f.strip()]
            for field in attr_fields:
                if field in record and record[field] is not None:
                    value = record[field]
                    if isinstance(value, (str, int, float, bool)):
                        attributes[field] = value
                    else:
                        attributes[field] = str(value)
            return attributes

        # Step 2: Zero-config fallback - extract all non-system fields from record
        # This enables filtering - chunking Lambda adds filterable fields
        # to metadata, which get passed to record_data. We extract all of them.
        system_fields = {
            'Id', 'OwnerId', 'Name', 'attributes', 'sobject', 'recordId',
            'parentIds', 'lastModified', 'language', 'chunkIndex', 'totalChunks'
        }
        print(f"[ATTR_DEBUG] Zero-config fallback, extracting from {len(record)} record fields")
        for field, value in record.items():
            if field not in attributes and field not in system_fields and value is not None:
                if isinstance(value, (str, int, float, bool)):
                    attributes[field] = value
                    print(f"[ATTR_DEBUG] Extracted: {field} = {value[:50] if isinstance(value, str) and len(str(value)) > 50 else value}")
                else:
                    attributes[field] = str(value)
                    print(f"[ATTR_DEBUG] Extracted (converted): {field} = {str(value)[:50]}")

        # Always include Name field if present (for display purposes)
        if 'Name' in record and record['Name'] is not None:
            attributes['Name'] = str(record['Name'])

        return attributes

    def _infer_object_type(self, field_name: str, source_sobject: str) -> str:
        """Infer related object type from field name."""
        # Handle standard fields
        if field_name == 'OwnerId':
            return 'User'
        if field_name == 'AccountId':
            return 'Account'
        if field_name == 'ContactId':
            return 'Contact'
        if field_name == 'ParentId':
            # ParentId usually refers to same object type or Account
            return source_sobject if '__c' in source_sobject else 'Account'

        # Handle custom fields: field__c -> Object__c
        if field_name.endswith('__c'):
            # Remove __c suffix and add it back as object name
            base_name = field_name[:-3]
            return f"{base_name}__c"

        # Handle standard lookup fields: ObjectId -> Object
        if field_name.endswith('Id'):
            return field_name[:-2]

        return 'Unknown'


# =============================================================================
# DynamoDB Operations
# =============================================================================

def store_graph(graph: Graph, operation: str = 'CREATE') -> Dict[str, Any]:
    """
    Store graph nodes and edges in DynamoDB.

    Args:
        graph: Graph to store
        operation: Operation type for logging

    Returns:
        Result with counts
    """
    nodes_table = dynamodb.Table(GRAPH_NODES_TABLE)
    edges_table = dynamodb.Table(GRAPH_EDGES_TABLE)

    nodes_written = 0
    edges_written = 0
    errors = []

    # Write nodes - use conditional write to avoid overwriting richer data with stubs
    for node_id, node in graph.nodes.items():
        try:
            item = node.to_dynamodb_item()
            new_attrs = item.get('attributes', {})

            # Check if node already exists with more attributes
            try:
                existing = nodes_table.get_item(Key={'nodeId': node_id})
                existing_item = existing.get('Item')
                if existing_item:
                    existing_attrs = existing_item.get('attributes', {})
                    # If existing node has more attributes, merge instead of overwrite
                    if len(existing_attrs) > len(new_attrs):
                        # Keep existing attributes but update metadata
                        merged_attrs = dict(existing_attrs)
                        for k, v in new_attrs.items():
                            if k not in merged_attrs or merged_attrs[k] in [None, '', {}]:
                                merged_attrs[k] = v
                        item['attributes'] = merged_attrs
            except Exception:
                pass  # If lookup fails, proceed with normal put

            nodes_table.put_item(Item=item)
            nodes_written += 1
        except Exception as e:
            errors.append(f"Node {node_id}: {str(e)}")

    # Write edges
    for edge in graph.edges:
        try:
            item = edge.to_dynamodb_item()
            edges_table.put_item(Item=item)
            edges_written += 1
        except Exception as e:
            errors.append(f"Edge {edge.fromId}->{edge.toId}: {str(e)}")

    return {
        'success': len(errors) == 0,
        'nodesWritten': nodes_written,
        'edgesWritten': edges_written,
        'errors': errors
    }


def delete_node_and_edges(node_id: str) -> Dict[str, Any]:
    """
    Delete node and all connected edges from graph.

    **Requirements: 10.3**

    Args:
        node_id: Node ID to delete

    Returns:
        Result with counts
    """
    nodes_table = dynamodb.Table(GRAPH_NODES_TABLE)
    edges_table = dynamodb.Table(GRAPH_EDGES_TABLE)

    edges_deleted = 0
    errors = []

    try:
        # Delete node
        nodes_table.delete_item(Key={'nodeId': node_id})

        # Delete edges where node is source (fromId) - paginate to handle >1MB
        last_key = None
        while True:
            query_args = {
                'KeyConditionExpression': boto3.dynamodb.conditions.Key('fromId').eq(node_id)
            }
            if last_key:
                query_args['ExclusiveStartKey'] = last_key
            response = edges_table.query(**query_args)
            for item in response.get('Items', []):
                edges_table.delete_item(
                    Key={'fromId': item['fromId'], 'toIdType': item['toIdType']}
                )
                edges_deleted += 1
            last_key = response.get('LastEvaluatedKey')
            if not last_key:
                break

        # Delete edges where node is target (using GSI) - paginate
        last_key = None
        while True:
            query_args = {
                'IndexName': 'toId-index',
                'KeyConditionExpression': boto3.dynamodb.conditions.Key('toId').eq(node_id)
            }
            if last_key:
                query_args['ExclusiveStartKey'] = last_key
            response = edges_table.query(**query_args)
            for item in response.get('Items', []):
                edges_table.delete_item(
                    Key={'fromId': item['fromId'], 'toIdType': item['toIdType']}
                )
                edges_deleted += 1
            last_key = response.get('LastEvaluatedKey')
            if not last_key:
                break

    except Exception as e:
        errors.append(str(e))

    return {
        'success': len(errors) == 0,
        'nodeDeleted': True,
        'edgesDeleted': edges_deleted,
        'errors': errors
    }


# =============================================================================
# S3 Operations
# =============================================================================

def read_chunks_from_s3(bucket: str, key: str) -> List[Dict[str, Any]]:
    """
    Read chunks from S3 JSON file.
    
    Args:
        bucket: S3 bucket name
        key: S3 object key
        
    Returns:
        List of chunk dictionaries
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        chunks = json.loads(content)
        print(f"Read {len(chunks)} chunks from s3://{bucket}/{key}")
        return chunks
    except Exception as e:
        print(f"Error reading chunks from S3: {str(e)}")
        raise


def extract_records_from_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract unique records from chunks for graph building.
    
    Chunks contain metadata with sobject and recordId. We need to reconstruct
    record-like structures for the graph builder.
    
    Args:
        chunks: List of chunk dictionaries from chunking Lambda
        
    Returns:
        List of record dictionaries suitable for graph building
    """
    records_by_id = {}
    
    for chunk in chunks:
        metadata = chunk.get('metadata', {})
        record_id = metadata.get('recordId')
        sobject = metadata.get('sobject')
        
        if not record_id or not sobject:
            continue
            
        # Only process first chunk of each record (avoid duplicates)
        if record_id in records_by_id:
            continue
            
        # Build a minimal record structure for graph building
        record_data = {
            'Id': record_id,
            'OwnerId': metadata.get('ownerId'),
        }

        # Phase 3: Add record name from metadata for proper display names
        if 'name' in metadata:
            record_data['Name'] = metadata['name']
        
        # Add parent IDs as relationship fields
        # Zero-config: parent IDs are now passed through metadata with field names
        parent_ids = metadata.get('parentIds', [])
        parent_fields = metadata.get('parentFields', [])  # Field names from chunking Lambda
        
        # Map parent IDs to their corresponding relationship fields
        if parent_fields and parent_ids:
            for i, parent_id in enumerate(parent_ids):
                if i < len(parent_fields) and parent_id:
                    record_data[parent_fields[i]] = parent_id
        elif parent_ids:
            # Fallback: use generic field names if parentFields not provided
            for i, parent_id in enumerate(parent_ids):
                if parent_id:
                    record_data[f'ParentId_{i}'] = parent_id
        
        # Zero-Config Schema Discovery: Pass through ALL metadata fields to record_data
        # This allows any filterable field added by chunking Lambda to automatically
        # flow through to graph builder's schema-driven attribute extraction.
        # System/internal fields are excluded to avoid confusion.
        system_fields = {
            'sobject', 'recordId', 'ownerId', 'lastModified', 'language',
            'name', 'parentIds', 'chunkIndex', 'totalChunks', 'tokenCount'
        }
        for key, value in metadata.items():
            if key not in system_fields and key not in record_data and value is not None:
                record_data[key] = value

        records_by_id[record_id] = {
            'sobject': sobject,
            'data': record_data
        }

    records = list(records_by_id.values())
    print(f"Extracted {len(records)} unique records from {len(chunks)} chunks")
    return records


# =============================================================================
# Lambda Handler
# =============================================================================

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for building relationship graphs.

    Supports:
    - Building graph from record(s)
    - Incremental updates (CREATE, UPDATE, DELETE)
    - Configuration caching with 5-minute TTL (Task 8.5)
    - CloudWatch metrics emission (Task 9.1)

    Args:
        event: Lambda event with records and operation
        context: Lambda context

    Returns:
        Result with graph statistics
    """
    handler_start_time = time.time()
    
    # Initialize metrics (Task 9.1)
    metrics = None
    if METRICS_AVAILABLE:
        metrics = get_build_metrics(enabled=True)
    
    try:
        print(f"Received event keys: {list(event.keys())}")

        # Get operation type (default to CREATE for new records)
        operation = event.get('operation', 'CREATE').upper()

        # Get configuration - priority: event config > cached config > defaults
        # Task 8.5: Use configuration cache with 5-minute TTL
        config = event.get('config')
        if not config:
            # Try to get from cache (falls back to defaults if unavailable)
            # The sobject-specific config will be fetched per record below
            config = DEFAULT_CONFIG.copy()

        # Check if graph building is enabled at global level
        if not config.get('Graph_Enabled__c', True):
            return {
                'success': True,
                'message': 'Graph building disabled',
                'nodesWritten': 0,
                'edgesWritten': 0
            }

        # Initialize builder with base config
        builder = GraphBuilder(config)

        # Get records to process
        records = event.get('records', [])
        
        # Check if input is S3 reference from chunking Lambda
        chunks_bucket = event.get('chunksS3Bucket')
        chunks_key = event.get('chunksS3Key')
        
        if chunks_bucket and chunks_key:
            # Read chunks from S3 and extract records
            print(f"Reading chunks from S3: s3://{chunks_bucket}/{chunks_key}")
            chunks = read_chunks_from_s3(chunks_bucket, chunks_key)
            records = extract_records_from_chunks(chunks)
        elif not records:
            # Try alternate event structures
            if 'record' in event:
                records = [event['record']]
            elif 'Payload' in event:
                payload = event['Payload']
                records = payload.get('records', [])
                if not records and 'record' in payload:
                    records = [payload['record']]
                # Also check for S3 reference in Payload
                if not records:
                    chunks_bucket = payload.get('chunksS3Bucket')
                    chunks_key = payload.get('chunksS3Key')
                    if chunks_bucket and chunks_key:
                        print(f"Reading chunks from S3 (Payload): s3://{chunks_bucket}/{chunks_key}")
                        chunks = read_chunks_from_s3(chunks_bucket, chunks_key)
                        records = extract_records_from_chunks(chunks)

        if not records:
            raise ValueError('No records provided')

        total_nodes = 0
        total_edges = 0
        results = []

        for record_wrapper in records:
            record_start_time = time.time()
            
            # Handle different event formats
            if isinstance(record_wrapper, dict):
                sobject = record_wrapper.get('sobject')
                record_data = record_wrapper.get('data', record_wrapper)
            else:
                continue

            if not sobject:
                sobject = record_data.get('attributes', {}).get('type')

            if not sobject:
                print(f"Skipping record without sobject type")
                continue

            # Zero-config: All object types are now supported via configuration
            # No longer checking against POC_OBJECT_FIELDS whitelist
            # Configuration determines if graph building is enabled per object

            # Task 8.5: Get object-specific configuration from cache
            # This allows per-object Graph_Enabled__c, Relationship_Depth__c, etc.
            if CONFIG_CACHE_AVAILABLE:
                object_config = get_object_config(sobject)
                # Check if graph is enabled for this specific object
                if not object_config.get('Graph_Enabled__c', True):
                    print(f"Graph building disabled for {sobject}")
                    continue
                # Update builder config for this object
                builder.config = object_config
            else:
                object_config = config

            try:
                if operation == 'DELETE':
                    result = delete_node_and_edges(record_data.get('Id'))
                    results.append(result)
                    # Emit delete operation metric
                    if metrics:
                        metrics.emit_build_operation('DELETE', sobject)
                else:
                    # Build graph for record using object-specific config
                    graph = builder.build_relationship_graph(record_data, sobject)

                    # Store in DynamoDB
                    store_result = store_graph(graph, operation)
                    total_nodes += store_result['nodesWritten']
                    total_edges += store_result['edgesWritten']
                    results.append(store_result)

                    # Emit metrics (Task 9.1)
                    record_latency_ms = (time.time() - record_start_time) * 1000
                    if metrics:
                        metrics.emit_build_latency(record_latency_ms, sobject)
                        metrics.emit_nodes_created(store_result['nodesWritten'], sobject)
                        metrics.emit_edges_created(store_result['edgesWritten'], sobject)
                        metrics.emit_build_operation(operation, sobject)

                    print(f"Built graph for {sobject} {record_data.get('Id')}: "
                          f"{len(graph.nodes)} nodes, {len(graph.edges)} edges")

            except Exception as e:
                print(f"Error processing record {record_data.get('Id')}: {str(e)}")
                results.append({'success': False, 'error': str(e)})
                # Emit error metric
                if metrics:
                    metrics.emit_build_error(type(e).__name__, sobject)

        # Emit total records processed metric
        if metrics:
            metrics.emit_records_processed(len(records))

        # Build response - pass through S3 references for downstream steps
        response = {
            'success': True,
            'operation': operation,
            'recordsProcessed': len(records),
            'nodesWritten': total_nodes,
            'edgesWritten': total_edges,
        }
        
        # Pass through S3 references for Enrich/Embed/Sync steps
        if chunks_bucket and chunks_key:
            response['chunksS3Bucket'] = chunks_bucket
            response['chunksS3Key'] = chunks_key
            response['chunkCount'] = event.get('chunkCount', len(records))
        
        return response

    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        # Emit error metric
        if metrics:
            metrics.emit_build_error(type(e).__name__, 'unknown')
        # Raise so Step Functions catches the error and routes to DLQ
        raise
