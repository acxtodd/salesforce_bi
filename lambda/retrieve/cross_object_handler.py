"""
Cross-Object Query Handler for Zero-Config Production.

Handles queries where filter criteria apply to related objects rather than
the target object. For example, "availabilities in Plano" where City is a
Property field, not an Availability field.

**Feature: zero-config-production**
**Requirements: 9.1, 9.2, 9.5**
"""
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set, Tuple

import boto3
from boto3.dynamodb.conditions import Key, Attr

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# DynamoDB table names
GRAPH_NODES_TABLE = os.environ.get('GRAPH_NODES_TABLE', 'salesforce-ai-search-graph-nodes')
GRAPH_EDGES_TABLE = os.environ.get('GRAPH_EDGES_TABLE', 'salesforce-ai-search-graph-edges')

# Configuration
MAX_NODES_PER_HOP = int(os.environ.get('MAX_NODES_PER_HOP', '100'))
MAX_TRAVERSAL_DEPTH = int(os.environ.get('MAX_TRAVERSAL_DEPTH', '3'))
# Separate limit for cross-object filter queries (should be higher than traversal limit)
# This controls how many nodes we scan when finding filter matches
CROSS_OBJECT_QUERY_LIMIT = int(os.environ.get('CROSS_OBJECT_QUERY_LIMIT', '5000'))


@dataclass
class CrossObjectQuery:
    """
    Represents a query that spans multiple objects.
    
    **Requirements: 9.1, 9.2**
    
    Attributes:
        target_entity: The entity the user wants (e.g., 'ascendix__Availability__c')
        filter_entity: Where filters apply (e.g., 'ascendix__Property__c')
        filters: Filters for the filter_entity
        numeric_filters: Numeric filters for the filter_entity
        traversal_path: Path from filter_entity to target_entity
        confidence: Confidence score (0.0 to 1.0)
    """
    target_entity: str
    filter_entity: str
    filters: Dict[str, Any] = field(default_factory=dict)
    numeric_filters: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    traversal_path: List[str] = field(default_factory=list)
    confidence: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "target_entity": self.target_entity,
            "filter_entity": self.filter_entity,
            "filters": self.filters,
            "numeric_filters": self.numeric_filters,
            "traversal_path": self.traversal_path,
            "confidence": self.confidence,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CrossObjectQuery":
        """Create CrossObjectQuery from dictionary."""
        return cls(
            target_entity=data.get("target_entity", ""),
            filter_entity=data.get("filter_entity", ""),
            filters=data.get("filters", {}),
            numeric_filters=data.get("numeric_filters", {}),
            traversal_path=data.get("traversal_path", []),
            confidence=data.get("confidence", 1.0),
        )



class CrossObjectQueryHandler:
    """
    Handle queries where filters apply to related objects.
    
    Detects cross-object queries and executes them using graph traversal.
    For example, "availabilities in Plano" requires:
    1. Finding Properties in Plano
    2. Traversing to related Availabilities
    
    **Requirements: 9.1, 9.2, 9.5**
    """
    
    # Known relationships between objects
    # Maps (child_object, parent_object) -> relationship_field
    KNOWN_RELATIONSHIPS = {
        ("ascendix__Availability__c", "ascendix__Property__c"): "ascendix__Property__c",
        ("ascendix__Lease__c", "ascendix__Property__c"): "ascendix__Property__c",
        ("ascendix__Deal__c", "ascendix__Property__c"): "ascendix__Property__c",
        ("ascendix__Listing__c", "ascendix__Property__c"): "ascendix__Property__c",
        ("ascendix__Sale__c", "ascendix__Property__c"): "ascendix__Property__c",
        ("Contact", "Account"): "AccountId",
        ("Opportunity", "Account"): "AccountId",
        ("Case", "Account"): "AccountId",
    }
    
    # Fields that typically exist on parent objects but not children
    # Maps field_name -> likely_parent_object
    PARENT_FIELD_HINTS = {
        "City": "ascendix__Property__c",
        "ascendix__City__c": "ascendix__Property__c",
        "State": "ascendix__Property__c",
        "ascendix__State__c": "ascendix__Property__c",
        "Country": "ascendix__Property__c",
        "ascendix__Country__c": "ascendix__Property__c",
        "ascendix__Class__c": "ascendix__Property__c",
        "ascendix__Property_Type__c": "ascendix__Property__c",
        "ascendix__SubMarket__c": "ascendix__Property__c",
        "BillingCity": "Account",
        "BillingState": "Account",
        "Industry": "Account",
    }
    
    def __init__(
        self,
        schema_cache=None,
        graph_nodes_table=None,
        graph_edges_table=None
    ):
        """
        Initialize with schema cache and graph tables.
        
        Args:
            schema_cache: SchemaCache instance for field lookups
            graph_nodes_table: DynamoDB table for graph nodes
            graph_edges_table: DynamoDB table for graph edges
        """
        self._schema_cache = schema_cache
        self._nodes_table = graph_nodes_table
        self._edges_table = graph_edges_table
        self._dynamodb = None
    
    def _get_dynamodb(self):
        """Get or create DynamoDB resource."""
        if self._dynamodb is None:
            self._dynamodb = boto3.resource('dynamodb')
        return self._dynamodb
    
    @property
    def nodes_table(self):
        """Lazy initialization of nodes table."""
        if self._nodes_table is None:
            self._nodes_table = self._get_dynamodb().Table(GRAPH_NODES_TABLE)
        return self._nodes_table
    
    @property
    def edges_table(self):
        """Lazy initialization of edges table."""
        if self._edges_table is None:
            self._edges_table = self._get_dynamodb().Table(GRAPH_EDGES_TABLE)
        return self._edges_table
    
    def _get_schema_cache(self):
        """Get or create Schema Cache instance."""
        if self._schema_cache is not None:
            return self._schema_cache
        
        try:
            # **Feature: zero-config-production, Task 27.1**
            # Schema discovery is now provided via Lambda Layer
            import sys
            try:
                from schema_discovery.cache import SchemaCache
            except ImportError:
                # Fallback for local development
                # Note: Use single dirname to stay in lambda/retrieve/ directory
                local_schema_path = os.path.join(
                    os.path.dirname(__file__), 'schema_discovery'
                )
                if local_schema_path not in sys.path:
                    sys.path.insert(0, local_schema_path)
                from cache import SchemaCache
            
            self._schema_cache = SchemaCache()
            return self._schema_cache
        except Exception as e:
            LOGGER.warning(f"Failed to create Schema Cache: {e}")
            return None

    def _field_exists_on_object(self, field_name: str, object_type: str) -> bool:
        """
        Check if a field exists on an object using schema cache.
        
        Args:
            field_name: Field API name
            object_type: Object API name
            
        Returns:
            True if field exists on object
        """
        schema_cache = self._get_schema_cache()
        if not schema_cache:
            return False
        
        try:
            schema = schema_cache.get(object_type)
            if not schema:
                return False
            
            # Check all field types
            all_fields = (
                schema.filterable + 
                schema.numeric + 
                schema.date + 
                schema.relationships
            )
            
            for f in all_fields:
                if f.name == field_name or f.name.lower() == field_name.lower():
                    return True
            
            return False
        except Exception as e:
            LOGGER.debug(f"Error checking field {field_name} on {object_type}: {e}")
            return False

    def _find_relationship_path(
        self,
        from_object: str,
        to_object: str
    ) -> Optional[List[str]]:
        """
        Find relationship path between two objects.
        
        Args:
            from_object: Source object type
            to_object: Target object type
            
        Returns:
            List of object types in path, or None if no path found
        """
        # Check direct relationship
        if (from_object, to_object) in self.KNOWN_RELATIONSHIPS:
            return [from_object, to_object]
        
        # Check reverse relationship
        if (to_object, from_object) in self.KNOWN_RELATIONSHIPS:
            return [from_object, to_object]
        
        # Try to find path through schema relationships
        schema_cache = self._get_schema_cache()
        if schema_cache:
            try:
                from_schema = schema_cache.get(from_object)
                if from_schema:
                    for rel in from_schema.relationships:
                        if rel.reference_to == to_object:
                            return [from_object, to_object]
            except Exception as e:
                LOGGER.debug(f"Error finding relationship path: {e}")
        
        return None


    def detect_cross_object_query(
        self,
        target_entity: str,
        filters: Dict[str, Any],
        numeric_filters: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Optional[CrossObjectQuery]:
        """
        Detect if filters apply to a related object rather than target.
        
        **Property 13: Cross-Object Query Detection**
        **Validates: Requirements 9.1, 9.2, 9.4**
        
        Example:
        - Query: "availabilities in Plano"
        - Target: Availability (no City field)
        - Filters: City = "Plano" (exists on Property)
        - Result: CrossObjectQuery(target=Availability, filter_entity=Property, ...)
        
        Args:
            target_entity: The entity the user wants
            filters: Exact-match filters from decomposition
            numeric_filters: Numeric comparison filters
            
        Returns:
            CrossObjectQuery if cross-object detected, None otherwise
        """
        if not filters and not numeric_filters:
            return None
        
        numeric_filters = numeric_filters or {}
        
        # Check each filter field
        cross_object_filters: Dict[str, Any] = {}
        cross_object_numeric: Dict[str, Dict[str, Any]] = {}
        target_filters: Dict[str, Any] = {}
        target_numeric: Dict[str, Dict[str, Any]] = {}
        filter_entity: Optional[str] = None
        
        # Process exact-match filters
        for field_name, value in filters.items():
            # Check if field exists on target
            if self._field_exists_on_object(field_name, target_entity):
                target_filters[field_name] = value
                continue
            
            # Check if field hints to a parent object
            hinted_parent = self.PARENT_FIELD_HINTS.get(field_name)
            if hinted_parent:
                # Verify relationship exists
                path = self._find_relationship_path(target_entity, hinted_parent)
                if path:
                    cross_object_filters[field_name] = value
                    filter_entity = hinted_parent
                    continue
            
            # Try to find the field on related objects
            for (child, parent), _ in self.KNOWN_RELATIONSHIPS.items():
                if child == target_entity:
                    if self._field_exists_on_object(field_name, parent):
                        cross_object_filters[field_name] = value
                        filter_entity = parent
                        break
            else:
                # Field not found anywhere, keep on target
                target_filters[field_name] = value
        
        # Process numeric filters
        for field_name, comparison in numeric_filters.items():
            if self._field_exists_on_object(field_name, target_entity):
                target_numeric[field_name] = comparison
                continue
            
            # Check parent objects
            hinted_parent = self.PARENT_FIELD_HINTS.get(field_name)
            if hinted_parent:
                path = self._find_relationship_path(target_entity, hinted_parent)
                if path:
                    cross_object_numeric[field_name] = comparison
                    filter_entity = filter_entity or hinted_parent
                    continue
            
            # Try related objects
            for (child, parent), _ in self.KNOWN_RELATIONSHIPS.items():
                if child == target_entity:
                    if self._field_exists_on_object(field_name, parent):
                        cross_object_numeric[field_name] = comparison
                        filter_entity = filter_entity or parent
                        break
            else:
                target_numeric[field_name] = comparison
        
        # If no cross-object filters found, return None
        if not cross_object_filters and not cross_object_numeric:
            return None
        
        if not filter_entity:
            return None
        
        # Build traversal path
        traversal_path = self._find_relationship_path(target_entity, filter_entity)
        if not traversal_path:
            LOGGER.warning(
                f"No relationship path from {target_entity} to {filter_entity}"
            )
            return None
        
        # Calculate confidence based on how many filters are cross-object
        total_filters = len(filters) + len(numeric_filters)
        cross_filters = len(cross_object_filters) + len(cross_object_numeric)
        confidence = 0.8 if cross_filters == total_filters else 0.6
        
        LOGGER.info(
            f"Detected cross-object query: target={target_entity}, "
            f"filter_entity={filter_entity}, "
            f"cross_filters={cross_object_filters}, "
            f"path={traversal_path}"
        )
        
        return CrossObjectQuery(
            target_entity=target_entity,
            filter_entity=filter_entity,
            filters=cross_object_filters,
            numeric_filters=cross_object_numeric,
            traversal_path=traversal_path,
            confidence=confidence,
        )


    def execute_cross_object_query(
        self,
        cross_query: CrossObjectQuery,
        user_sharing_buckets: Optional[Set[str]] = None
    ) -> List[str]:
        """
        Execute cross-object query using graph traversal.
        
        **Property 14: Cross-Object Query Execution**
        **Validates: Requirements 9.5**
        
        1. Find filter_entity records matching filters
        2. Traverse graph to find related target_entity records
        3. Return target record IDs
        
        Args:
            cross_query: CrossObjectQuery with filters and traversal path
            user_sharing_buckets: User's sharing buckets for authorization
            
        Returns:
            List of target entity record IDs
        """
        user_sharing_buckets = user_sharing_buckets or set()
        
        # Step 1: Find filter_entity records matching filters
        filter_node_ids = self._query_nodes_by_attributes(
            object_type=cross_query.filter_entity,
            filters=cross_query.filters,
            numeric_filters=cross_query.numeric_filters,
            user_sharing_buckets=user_sharing_buckets,
        )
        
        if not filter_node_ids:
            LOGGER.info(
                f"No {cross_query.filter_entity} records match filters: "
                f"{cross_query.filters}"
            )
            return []
        
        LOGGER.info(
            f"Found {len(filter_node_ids)} {cross_query.filter_entity} records "
            f"matching filters"
        )
        
        # Step 2: Traverse graph to find related target_entity records
        target_node_ids = self._traverse_to_target(
            source_node_ids=filter_node_ids,
            target_type=cross_query.target_entity,
            user_sharing_buckets=user_sharing_buckets,
        )
        
        LOGGER.info(
            f"Found {len(target_node_ids)} {cross_query.target_entity} records "
            f"via graph traversal"
        )
        
        return list(target_node_ids)

    def _query_nodes_by_attributes(
        self,
        object_type: str,
        filters: Dict[str, Any],
        numeric_filters: Dict[str, Dict[str, Any]],
        user_sharing_buckets: Set[str],
    ) -> List[str]:
        """
        Query graph nodes by attributes.
        
        Args:
            object_type: Object type to query
            filters: Exact-match filters
            numeric_filters: Numeric comparison filters
            user_sharing_buckets: User's sharing buckets
            
        Returns:
            List of matching node IDs
        """
        matching_ids: List[str] = []

        # Log the filters being applied for debugging
        LOGGER.info(
            f"Cross-object filter query: type={object_type}, "
            f"filters={filters}, numeric_filters={numeric_filters}, "
            f"limit={CROSS_OBJECT_QUERY_LIMIT}"
        )

        try:
            # Query nodes by type (newest first for relevance)
            # Use CROSS_OBJECT_QUERY_LIMIT to ensure we scan enough nodes to find filter matches
            response = self.nodes_table.query(
                IndexName='type-createdAt-index',
                KeyConditionExpression=Key('type').eq(object_type),
                Limit=CROSS_OBJECT_QUERY_LIMIT,  # Scan more nodes to find filter matches
                ScanIndexForward=False,  # Newest first - recently updated records are more relevant
            )

            scanned_count = len(response.get('Items', []))
            for item in response.get('Items', []):
                # Check authorization
                node_buckets = set(item.get('sharingBuckets', []))
                if node_buckets and user_sharing_buckets:
                    if not (node_buckets & user_sharing_buckets):
                        continue
                
                # Check exact-match filters
                attributes = item.get('attributes', {})
                matches_filters = True
                
                for field_name, expected_value in filters.items():
                    actual_value = attributes.get(field_name)
                    if actual_value is None:
                        matches_filters = False
                        break
                    
                    # Case-insensitive string comparison
                    if isinstance(expected_value, str) and isinstance(actual_value, str):
                        if expected_value.lower() != actual_value.lower():
                            matches_filters = False
                            break
                    elif actual_value != expected_value:
                        matches_filters = False
                        break
                
                if not matches_filters:
                    continue
                
                # Check numeric filters
                for field_name, comparison in numeric_filters.items():
                    actual_value = attributes.get(field_name)
                    if actual_value is None:
                        matches_filters = False
                        break
                    
                    try:
                        actual_num = float(actual_value)
                        for op, threshold in comparison.items():
                            threshold_num = float(threshold)
                            if op == "$gt" and not (actual_num > threshold_num):
                                matches_filters = False
                            elif op == "$gte" and not (actual_num >= threshold_num):
                                matches_filters = False
                            elif op == "$lt" and not (actual_num < threshold_num):
                                matches_filters = False
                            elif op == "$lte" and not (actual_num <= threshold_num):
                                matches_filters = False
                    except (ValueError, TypeError):
                        matches_filters = False
                        break
                
                if matches_filters:
                    matching_ids.append(item['nodeId'])

                    if len(matching_ids) >= MAX_NODES_PER_HOP:
                        break

            # Log scan results for debugging
            LOGGER.info(
                f"Cross-object filter results: scanned={scanned_count}, "
                f"matched={len(matching_ids)}, type={object_type}"
            )

        except Exception as e:
            LOGGER.error(f"Error querying nodes by attributes: {e}")

        return matching_ids

    def _traverse_to_target(
        self,
        source_node_ids: List[str],
        target_type: str,
        user_sharing_buckets: Set[str],
    ) -> Set[str]:
        """
        Traverse graph from source nodes to find target type nodes.

        OPTIMIZED: Uses edge type field directly instead of fetching nodes.
        For Property→Lease traversal, queries inbound edges to Properties
        where the source node type matches target_type.

        Args:
            source_node_ids: Starting node IDs
            target_type: Target object type to find
            user_sharing_buckets: User's sharing buckets

        Returns:
            Set of target node IDs
        """
        target_ids: Set[str] = set()

        # OPTIMIZATION: Query all edges for all source nodes in batches
        # Instead of fetching full nodes, use edge 'type' field directly
        import time
        start_time = time.perf_counter()

        # For Property→Lease, Leases have edges pointing TO Properties
        # So we query edges WHERE toId IN source_node_ids AND type = target_type
        # Using the toId-index GSI for efficient lookup

        for source_id in source_node_ids:
            if len(target_ids) >= MAX_NODES_PER_HOP:
                break

            try:
                # Query inbound edges (edges pointing to this source node)
                # The source of these edges might be our target type
                # Use FilterExpression to filter by type server-side
                # Paginate to ensure we find all matching edges (not just first N)
                exclusive_start_key = None
                while True:
                    query_params = {
                        'IndexName': 'toId-index',
                        'KeyConditionExpression': Key('toId').eq(source_id),
                        'FilterExpression': Attr('type').eq(target_type),
                        'ProjectionExpression': 'fromId',
                    }
                    if exclusive_start_key:
                        query_params['ExclusiveStartKey'] = exclusive_start_key

                    inbound_response = self.edges_table.query(**query_params)

                    for edge in inbound_response.get('Items', []):
                        from_id = edge.get('fromId')
                        if from_id:
                            target_ids.add(from_id)
                            if len(target_ids) >= MAX_NODES_PER_HOP:
                                break

                    # Check if we've hit the limit or no more pages
                    if len(target_ids) >= MAX_NODES_PER_HOP:
                        break
                    exclusive_start_key = inbound_response.get('LastEvaluatedKey')
                    if not exclusive_start_key:
                        break

            except Exception as e:
                LOGGER.warning(f"Error querying edges for {source_id}: {e}")

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        LOGGER.info(
            f"Edge traversal completed: {len(source_node_ids)} sources → "
            f"{len(target_ids)} targets in {elapsed_ms:.0f}ms"
        )

        return target_ids

    def _get_connected_nodes(self, node_id: str) -> List[Dict[str, Any]]:
        """
        Get nodes connected to the given node.
        
        Args:
            node_id: Source node ID
            
        Returns:
            List of connected node dictionaries
        """
        connected: List[Dict[str, Any]] = []
        
        try:
            # Query outbound edges
            outbound_response = self.edges_table.query(
                KeyConditionExpression=Key('fromId').eq(node_id),
                Limit=MAX_NODES_PER_HOP,
            )
            
            for edge in outbound_response.get('Items', []):
                to_id = edge.get('toId')
                if to_id:
                    node_response = self.nodes_table.get_item(Key={'nodeId': to_id})
                    if 'Item' in node_response:
                        connected.append(node_response['Item'])
            
            # Query inbound edges using GSI
            inbound_response = self.edges_table.query(
                IndexName='toId-index',
                KeyConditionExpression=Key('toId').eq(node_id),
                Limit=MAX_NODES_PER_HOP,
            )
            
            for edge in inbound_response.get('Items', []):
                from_id = edge.get('fromId')
                if from_id:
                    node_response = self.nodes_table.get_item(Key={'nodeId': from_id})
                    if 'Item' in node_response:
                        connected.append(node_response['Item'])
        
        except Exception as e:
            LOGGER.warning(f"Error getting connected nodes for {node_id}: {e}")
        
        return connected


# Module-level convenience functions
_cross_object_handler: Optional[CrossObjectQueryHandler] = None


def get_cross_object_handler(
    schema_cache=None
) -> CrossObjectQueryHandler:
    """
    Get or create the default CrossObjectQueryHandler instance.
    
    Args:
        schema_cache: Optional SchemaCache instance
        
    Returns:
        CrossObjectQueryHandler instance
    """
    global _cross_object_handler
    if _cross_object_handler is None:
        _cross_object_handler = CrossObjectQueryHandler(schema_cache=schema_cache)
    return _cross_object_handler


def detect_cross_object_query(
    target_entity: str,
    filters: Dict[str, Any],
    numeric_filters: Optional[Dict[str, Dict[str, Any]]] = None
) -> Optional[CrossObjectQuery]:
    """
    Convenience function to detect cross-object queries.
    
    Args:
        target_entity: Target entity type
        filters: Exact-match filters
        numeric_filters: Numeric comparison filters
        
    Returns:
        CrossObjectQuery if detected, None otherwise
    """
    return get_cross_object_handler().detect_cross_object_query(
        target_entity=target_entity,
        filters=filters,
        numeric_filters=numeric_filters,
    )


def execute_cross_object_query(
    cross_query: CrossObjectQuery,
    user_sharing_buckets: Optional[Set[str]] = None
) -> List[str]:
    """
    Convenience function to execute cross-object queries.
    
    Args:
        cross_query: CrossObjectQuery to execute
        user_sharing_buckets: User's sharing buckets
        
    Returns:
        List of target record IDs
    """
    return get_cross_object_handler().execute_cross_object_query(
        cross_query=cross_query,
        user_sharing_buckets=user_sharing_buckets,
    )
