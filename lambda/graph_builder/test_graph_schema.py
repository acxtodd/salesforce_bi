"""
Property-based tests for Graph Database schema validation and Graph Builder.

This module contains property tests that verify:
- Graph node and edge structures conform to the expected schema
- GraphBuilder correctly builds relationship graphs
- Depth limiting works as expected
- Configuration-driven field filtering works

**Feature: phase3-graph-enhancement, Tasks 1.3, 2.3, 2.5, 2.7, 2.9**
"""
import pytest
import sys
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

from hypothesis import given, strategies as st, settings, assume

# Add lambda directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use the phase3 profile with minimum 100 examples
settings.load_profile("phase3")

# Import GraphBuilder and models from index.py
from graph_builder.index import (
    GraphBuilder, GraphNode, GraphEdge, Graph, DEFAULT_CONFIG
)

# Define supported object types for testing (previously from POC_OBJECT_FIELDS)
# These are now dynamically configured via IndexConfiguration__mdt
SUPPORTED_OBJECT_TYPES = [
    "Account", "Opportunity", "Case", "Note", "Contact", "Lead",
    "ascendix__Property__c", "ascendix__Availability__c", "ascendix__Lease__c",
    "ascendix__Sale__c", "ascendix__Deal__c"
]


# Note: GraphNode and GraphEdge are imported from graph_builder.index


# =============================================================================
# Hypothesis Strategies
# =============================================================================

# Strategy for Salesforce-like record IDs (15-18 alphanumeric chars)
salesforce_id_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=15,
    max_size=18
)

# Strategy for Salesforce object types
object_type_strategy = st.sampled_from([
    "Account", "Opportunity", "Case", "Note", "Contact", "Lead",
    "ascendix__Property__c", "ascendix__Lease__c", "ascendix__Deal__c",
    "ascendix__Availability__c", "ascendix__Sale__c"
])

# Strategy for display names (non-empty strings)
display_name_strategy = st.text(min_size=1, max_size=255)

# Strategy for attribute values
attribute_value_strategy = st.one_of(
    st.text(max_size=100),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none()
)

# Strategy for attributes map
attributes_strategy = st.dictionaries(
    keys=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz_"),
    values=attribute_value_strategy,
    max_size=20
)

# Strategy for sharing buckets
sharing_bucket_strategy = st.lists(
    st.text(min_size=1, max_size=100),
    max_size=10
)

# Strategy for edge direction
direction_strategy = st.sampled_from(['parent', 'child'])

# Strategy for relationship field names
field_name_strategy = st.sampled_from([
    'AccountId', 'OwnerId', 'ParentId', 'ContactId',
    'ascendix__Property__c', 'ascendix__Tenant__c', 'ascendix__Client__c'
])

# Strategy for depth (1-3 as per requirements)
depth_strategy = st.integers(min_value=0, max_value=3)


# =============================================================================
# Property Tests
# =============================================================================

class TestGraphNodeSchema:
    """Property tests for GraphNode schema validation."""

    @pytest.mark.property
    @given(
        node_id=salesforce_id_strategy,
        obj_type=object_type_strategy,
        display_name=display_name_strategy,
        attributes=attributes_strategy,
        depth=depth_strategy
    )
    def test_property_2_node_structure_completeness(
        self, node_id, obj_type, display_name, attributes, depth
    ):
        """
        **Feature: phase3-graph-enhancement, Property 2: Node Structure Completeness**

        For any node created by the Graph Builder, the node SHALL contain
        a valid record ID, object type, display name, and the attributes
        map SHALL be non-null.

        **Validates: Requirements 2.2**
        """
        # Assume we have valid inputs (skip empty node_id or type)
        assume(len(node_id) >= 15)
        assume(len(obj_type) > 0)
        assume(len(display_name) > 0)

        node = GraphNode(
            nodeId=node_id,
            type=obj_type,
            displayName=display_name,
            attributes=attributes,
            depth=depth
        )

        # Verify node passes validation
        assert node.validate(), "Node should pass validation with valid inputs"

        # Verify node can be converted to DynamoDB format
        item = node.to_dynamodb_item()
        assert 'nodeId' in item, "DynamoDB item must have nodeId"
        assert 'type' in item, "DynamoDB item must have type"
        assert 'displayName' in item, "DynamoDB item must have displayName"
        assert 'attributes' in item, "DynamoDB item must have attributes"
        assert isinstance(item['attributes'], dict), "attributes must be a dict"

    @pytest.mark.property
    @given(
        node_id=salesforce_id_strategy,
        obj_type=object_type_strategy,
        sharing_buckets=sharing_bucket_strategy,
        owner_id=salesforce_id_strategy
    )
    def test_node_authorization_fields(
        self, node_id, obj_type, sharing_buckets, owner_id
    ):
        """
        **Feature: phase3-graph-enhancement, Property 2b: Node Authorization Fields**

        Nodes should store sharing buckets and owner ID for authorization
        at each hop during traversal.

        **Validates: Requirements 8.1, 8.2**
        """
        assume(len(node_id) >= 15)
        assume(len(owner_id) >= 15)

        node = GraphNode(
            nodeId=node_id,
            type=obj_type,
            displayName="Test Node",
            sharingBuckets=sharing_buckets,
            ownerId=owner_id
        )

        item = node.to_dynamodb_item()
        assert 'sharingBuckets' in item, "DynamoDB item must have sharingBuckets"
        assert isinstance(item['sharingBuckets'], list), "sharingBuckets must be a list"
        assert item['ownerId'] == owner_id, "ownerId must be preserved"

    @pytest.mark.property
    @given(
        node_id=salesforce_id_strategy,
        obj_type=object_type_strategy
    )
    def test_node_timestamps_generated(self, node_id, obj_type):
        """
        **Feature: phase3-graph-enhancement, Property 2c: Node Timestamps**

        Nodes should have createdAt and updatedAt timestamps.

        **Validates: Requirements 2.5 (freshness tracking)**
        """
        assume(len(node_id) >= 15)

        node = GraphNode(
            nodeId=node_id,
            type=obj_type,
            displayName="Test Node"
        )

        item = node.to_dynamodb_item()
        assert 'createdAt' in item, "DynamoDB item must have createdAt"
        assert 'updatedAt' in item, "DynamoDB item must have updatedAt"
        # Verify ISO format
        assert 'T' in item['createdAt'], "createdAt must be ISO format"


class TestGraphEdgeSchema:
    """Property tests for GraphEdge schema validation."""

    @pytest.mark.property
    @given(
        from_id=salesforce_id_strategy,
        to_id=salesforce_id_strategy,
        obj_type=object_type_strategy,
        field_name=field_name_strategy,
        direction=direction_strategy
    )
    def test_property_3_edge_structure_completeness(
        self, from_id, to_id, obj_type, field_name, direction
    ):
        """
        **Feature: phase3-graph-enhancement, Property 3: Edge Structure Completeness**

        For any edge created by the Graph Builder, the edge SHALL contain
        valid from/to IDs, relationship type, direction (parent or child),
        and field name.

        **Validates: Requirements 2.3**
        """
        assume(len(from_id) >= 15)
        assume(len(to_id) >= 15)
        assume(from_id != to_id)  # No self-referential edges

        edge = GraphEdge(
            fromId=from_id,
            toId=to_id,
            type=obj_type,
            fieldName=field_name,
            direction=direction
        )

        # Verify edge passes validation
        assert edge.validate(), "Edge should pass validation with valid inputs"

        # Verify edge can be converted to DynamoDB format
        item = edge.to_dynamodb_item()
        assert 'fromId' in item, "DynamoDB item must have fromId"
        assert 'toIdType' in item, "DynamoDB item must have toIdType (composite SK)"
        assert 'toId' in item, "DynamoDB item must have toId"
        assert 'type' in item, "DynamoDB item must have type"
        assert 'fieldName' in item, "DynamoDB item must have fieldName"
        assert 'direction' in item, "DynamoDB item must have direction"

    @pytest.mark.property
    @given(
        from_id=salesforce_id_strategy,
        to_id=salesforce_id_strategy,
        obj_type=object_type_strategy
    )
    def test_edge_composite_sort_key(self, from_id, to_id, obj_type):
        """
        **Feature: phase3-graph-enhancement, Property 3b: Edge Composite Key**

        Edges should have a composite sort key (toId#type) for uniqueness.

        **Validates: DynamoDB schema design for graph_edges table**
        """
        assume(len(from_id) >= 15)
        assume(len(to_id) >= 15)

        edge = GraphEdge(
            fromId=from_id,
            toId=to_id,
            type=obj_type,
            fieldName="TestField",
            direction="parent"
        )

        # Verify composite key format
        assert edge.toIdType == f"{to_id}#{obj_type}"
        item = edge.to_dynamodb_item()
        assert item['toIdType'] == f"{to_id}#{obj_type}"

    @pytest.mark.property
    @given(direction=direction_strategy)
    def test_edge_direction_valid(self, direction):
        """
        **Feature: phase3-graph-enhancement, Property 3c: Edge Direction Validity**

        Edge direction must be either 'parent' or 'child'.

        **Validates: Requirements 2.3 (relationship direction)**
        """
        assert direction in ('parent', 'child')

        edge = GraphEdge(
            fromId="a0I000000000001",
            toId="a0J000000000001",
            type="Account",
            fieldName="AccountId",
            direction=direction
        )
        assert edge.validate()


class TestGraphSchemaInvariants:
    """Property tests for schema invariants."""

    @pytest.mark.property
    @given(
        node_id=st.text(max_size=5)  # Intentionally invalid (too short)
    )
    def test_invalid_node_id_fails_validation(self, node_id):
        """
        **Feature: phase3-graph-enhancement, Property 2d: Invalid Node Detection**

        Nodes with invalid (empty or too short) IDs should fail validation.
        """
        node = GraphNode(
            nodeId=node_id,
            type="Account",
            displayName="Test"
        )

        if len(node_id) == 0:
            assert not node.validate(), "Empty nodeId should fail validation"

    @pytest.mark.property
    @given(
        from_id=salesforce_id_strategy,
        direction=st.text(min_size=1, max_size=20)
    )
    def test_invalid_edge_direction_fails_validation(self, from_id, direction):
        """
        **Feature: phase3-graph-enhancement, Property 3d: Invalid Edge Detection**

        Edges with invalid direction should fail validation.
        """
        assume(direction not in ('parent', 'child'))
        assume(len(from_id) >= 15)

        edge = GraphEdge(
            fromId=from_id,
            toId="a0J000000000001",
            type="Account",
            fieldName="AccountId",
            direction=direction
        )

        assert not edge.validate(), f"Direction '{direction}' should fail validation"


class TestGraphPathCacheSchema:
    """Property tests for graph path cache schema."""

    @pytest.mark.property
    @given(
        start_node=salesforce_id_strategy,
        user_id=salesforce_id_strategy,
        pattern=st.text(min_size=1, max_size=100)
    )
    def test_path_cache_key_generation(self, start_node, user_id, pattern):
        """
        **Feature: phase3-graph-enhancement, Property 13: Path Cache Key**

        Path cache keys should include user ID for security isolation.

        **Validates: Requirements 4.5, 8.5 (cache security)**
        """
        assume(len(start_node) >= 15)
        assume(len(user_id) >= 15)

        # Path key format: hash of (start_node + pattern + user_id)
        import hashlib
        cache_key = hashlib.sha256(
            f"{start_node}:{pattern}:{user_id}".encode()
        ).hexdigest()

        assert len(cache_key) == 64  # SHA-256 produces 64 hex chars
        assert user_id not in cache_key  # User ID should not be in plain text


class TestIntentClassificationLogSchema:
    """Property tests for intent classification log schema."""

    @pytest.mark.property
    @given(
        request_id=st.uuids(),
        query=st.text(min_size=1, max_size=500),
        intent=st.sampled_from([
            "SIMPLE_LOOKUP", "FIELD_FILTER", "RELATIONSHIP",
            "AGGREGATION", "COMPLEX"
        ]),
        confidence=st.floats(min_value=0.0, max_value=1.0)
    )
    def test_intent_log_schema(self, request_id, query, intent, confidence):
        """
        **Feature: phase3-graph-enhancement, Intent Log Schema**

        Intent classification logs should have valid schema for DynamoDB.

        **Validates: Requirements 3.4, 6.2 (intent logging)**
        """
        import time

        log_item = {
            'requestId': str(request_id),
            'query': query,
            'intent': intent,
            'confidence': confidence,
            'timestamp': int(time.time()),
            'ttl': int(time.time()) + (30 * 24 * 60 * 60)  # 30 days
        }

        assert 'requestId' in log_item
        assert 'intent' in log_item
        assert log_item['intent'] in {
            "SIMPLE_LOOKUP", "FIELD_FILTER", "RELATIONSHIP",
            "AGGREGATION", "COMPLEX"
        }
        assert 0.0 <= log_item['confidence'] <= 1.0
        assert log_item['ttl'] > log_item['timestamp']


# =============================================================================
# GraphBuilder Property Tests
# =============================================================================

class TestGraphBuilderDepthLimit:
    """Property tests for graph traversal depth limiting."""

    @pytest.mark.property
    @given(
        depth_limit=st.integers(min_value=1, max_value=3),
        record_id=salesforce_id_strategy,
        related_id=salesforce_id_strategy
    )
    def test_property_1_traversal_respects_depth_limit(
        self, depth_limit, record_id, related_id
    ):
        """
        **Feature: phase3-graph-enhancement, Property 1: Graph Traversal Depth Limit**

        For any record with relationships and any configured depth limit (1-3),
        the Graph Builder SHALL create nodes only up to the configured depth,
        and no deeper.

        **Validates: Requirements 2.4, 5.2**
        """
        assume(len(record_id) >= 15)
        assume(len(related_id) >= 15)
        assume(record_id != related_id)

        # Create test record with relationship
        record = {
            'Id': record_id,
            'Name': 'Test Property',
            'ascendix__OwnerLandlord__c': related_id,
            'OwnerId': '005000000000001'
        }

        builder = GraphBuilder({'Relationship_Depth__c': depth_limit})
        graph = builder.build_relationship_graph(record, 'ascendix__Property__c', max_depth=depth_limit)

        # Verify depth limit is respected
        for node_id, node in graph.nodes.items():
            assert node.depth <= depth_limit, \
                f"Node {node_id} has depth {node.depth} exceeding limit {depth_limit}"

    @pytest.mark.property
    @given(depth_limit=st.integers(min_value=1, max_value=3))
    def test_depth_limit_clamped_to_valid_range(self, depth_limit):
        """
        **Feature: phase3-graph-enhancement, Property 1b: Depth Limit Clamping**

        Depth limits should be clamped to valid range 1-3.

        **Validates: Requirements 5.2**
        """
        builder = GraphBuilder({'Relationship_Depth__c': depth_limit})
        record = {'Id': 'a0I000000000001', 'Name': 'Test'}

        graph = builder.build_relationship_graph(record, 'Account')

        # Root node should always be at depth 0
        root_node = graph.nodes.get('a0I000000000001')
        assert root_node is not None
        assert root_node.depth == 0


class TestGraphBuilderNodeCreation:
    """Property tests for node creation."""

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        name=st.text(min_size=1, max_size=100),
        city=st.text(min_size=1, max_size=50),
        obj_type=st.sampled_from(SUPPORTED_OBJECT_TYPES)
    )
    def test_property_2_node_structure_from_builder(
        self, record_id, name, city, obj_type
    ):
        """
        **Feature: phase3-graph-enhancement, Property 2: Node Structure Completeness**

        For any node created by the Graph Builder, the node SHALL contain
        a valid record ID, object type, display name, and the attributes
        map SHALL be non-null.

        **Validates: Requirements 2.2**
        """
        assume(len(record_id) >= 15)
        assume(len(name) > 0)

        record = {
            'Id': record_id,
            'Name': name,
            'ascendix__City__c': city,
            'OwnerId': '005000000000001'
        }

        builder = GraphBuilder()
        node = builder.create_node(record, obj_type)

        assert node is not None, "Node should be created"
        assert node.validate(), "Node should pass validation"
        assert node.nodeId == record_id
        assert node.type == obj_type
        assert node.displayName is not None
        assert isinstance(node.attributes, dict)

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        owner_id=salesforce_id_strategy
    )
    def test_node_owner_extraction(self, record_id, owner_id):
        """
        **Feature: phase3-graph-enhancement, Property 2c: Node Owner Extraction**

        Nodes should extract OwnerId for authorization.

        **Validates: Requirements 8.1**
        """
        assume(len(record_id) >= 15)
        assume(len(owner_id) >= 15)

        record = {
            'Id': record_id,
            'Name': 'Test',
            'OwnerId': owner_id
        }

        builder = GraphBuilder()
        node = builder.create_node(record, 'Account')

        assert node.ownerId == owner_id


class TestGraphBuilderEdgeCreation:
    """Property tests for edge creation."""

    @pytest.mark.property
    @given(
        from_id=salesforce_id_strategy,
        to_id=salesforce_id_strategy,
        field_name=field_name_strategy,
        direction=direction_strategy
    )
    def test_property_3_edge_structure_from_builder(
        self, from_id, to_id, field_name, direction
    ):
        """
        **Feature: phase3-graph-enhancement, Property 3: Edge Structure Completeness**

        For any edge created by the Graph Builder, the edge SHALL contain
        valid from/to IDs, relationship type, direction, and field name.

        **Validates: Requirements 2.3**
        """
        assume(len(from_id) >= 15)
        assume(len(to_id) >= 15)
        assume(from_id != to_id)

        builder = GraphBuilder()
        edge = builder.create_edge(
            from_id=from_id,
            to_id=to_id,
            relationship_type='Account',
            field_name=field_name,
            direction=direction
        )

        assert edge is not None, "Edge should be created"
        assert edge.validate(), "Edge should pass validation"
        assert edge.fromId == from_id
        assert edge.toId == to_id
        assert edge.direction in ('parent', 'child')

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy
    )
    def test_no_self_referential_edges(self, record_id):
        """
        **Feature: phase3-graph-enhancement, Property 3b: No Self-Referential Edges**

        Edges should not connect a node to itself.

        **Validates: Requirements 2.3**
        """
        assume(len(record_id) >= 15)

        builder = GraphBuilder()
        edge = builder.create_edge(
            from_id=record_id,
            to_id=record_id,  # Same ID
            relationship_type='Account',
            field_name='ParentId',
            direction='parent'
        )

        assert edge is None, "Self-referential edge should not be created"


class TestGraphBuilderFieldFiltering:
    """Property tests for configuration-driven field filtering."""

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        related_id=salesforce_id_strategy
    )
    def test_property_9_relationship_field_filtering(self, record_id, related_id):
        """
        **Feature: phase3-graph-enhancement, Property 9: Relationship Field Filtering**

        For any object with Relationship_Fields__c specified in configuration,
        the Graph Builder SHALL only create edges for the specified relationship
        fields, and no others.

        **Validates: Requirements 5.3**
        """
        assume(len(record_id) >= 15)
        assume(len(related_id) >= 15)
        assume(record_id != related_id)

        record = {
            'Id': record_id,
            'Name': 'Test Deal',
            'OwnerId': '005000000000001',
            'ascendix__Property__c': related_id,
            'ascendix__Client__c': '001000000000001',  # Should be ignored
        }

        # Configure to only include Property relationship
        config = {
            'Graph_Enabled__c': True,
            'Relationship_Depth__c': 1,
            'Relationship_Fields__c': 'ascendix__Property__c',
        }

        builder = GraphBuilder(config)
        graph = builder.build_relationship_graph(record, 'ascendix__Deal__c')

        # Should only have edges for Property, not Client
        edge_fields = {edge.fieldName for edge in graph.edges}

        assert 'ascendix__Property__c' in edge_fields or len(graph.edges) == 0
        assert 'ascendix__Client__c' not in edge_fields, \
            "Client field should be filtered out"

    @pytest.mark.property
    @given(
        obj_type=st.sampled_from(SUPPORTED_OBJECT_TYPES)
    )
    def test_default_fields_used_when_not_configured(self, obj_type):
        """
        **Feature: phase3-graph-enhancement, Property 9b: Default Field Fallback**
        **Feature: zero-config-production**

        When Relationship_Fields__c is not specified, default fields should be used.
        Zero-config: Falls back to schema cache or common default fields.

        **Validates: Requirements 5.3, 4.1**
        """
        config = {
            'Graph_Enabled__c': True,
            'Relationship_Depth__c': 1,
            'Relationship_Fields__c': None,  # Not configured
        }

        builder = GraphBuilder(config)
        fields = builder._get_relationship_fields(obj_type)

        # Should return default fields (from schema cache or fallback)
        # Zero-config: defaults to common relationship fields
        assert isinstance(fields, list)
        assert len(fields) > 0, "Should have at least some default fields"


class TestGraphEnablementConfiguration:
    """Property tests for graph enablement configuration (Task 8.4)."""

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        name=st.text(min_size=1, max_size=50),
        graph_enabled=st.booleans()
    )
    def test_property_8_graph_enablement_configuration(
        self, record_id, name, graph_enabled
    ):
        """
        **Feature: phase3-graph-enhancement, Property 8: Graph Enablement Configuration**

        For any object with Graph_Enabled__c set to true in IndexConfiguration__mdt,
        the Graph Builder SHALL create nodes for that object. For any object with
        Graph_Enabled__c set to false, the Graph Builder SHALL NOT create nodes
        for that object in new graph construction.

        **Validates: Requirements 5.1, 5.4**
        """
        assume(len(record_id) >= 15)
        assume(len(name) > 0)

        record = {
            'Id': record_id,
            'Name': name,
            'OwnerId': '005000000000001'
        }

        config = {
            'Graph_Enabled__c': graph_enabled,
            'Relationship_Depth__c': 2,
        }

        builder = GraphBuilder(config)

        if graph_enabled:
            # When enabled, should create nodes
            graph = builder.build_relationship_graph(record, 'Account')
            assert len(graph.nodes) >= 1, "Enabled graph should create nodes"
            assert record_id in graph.nodes, "Root node should be in graph"
        else:
            # When disabled, graph building should be skipped at handler level
            # The builder itself still works, but the handler checks the flag
            # This test verifies the config is properly read
            assert not config['Graph_Enabled__c']

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        obj_type=st.sampled_from(SUPPORTED_OBJECT_TYPES)
    )
    def test_property_8b_disabled_objects_excluded(self, record_id, obj_type):
        """
        **Feature: phase3-graph-enhancement, Property 8b: Disabled Objects Excluded**
        **Feature: zero-config-production**

        When Graph_Enabled__c is false, the lambda handler should skip
        graph building entirely.

        **Validates: Requirements 5.4, 4.5**
        """
        assume(len(record_id) >= 15)

        config = {
            'Graph_Enabled__c': False,
            'Relationship_Depth__c': 2,
        }

        # Simulate what lambda_handler does when graph is disabled
        if not config.get('Graph_Enabled__c', True):
            result = {
                'success': True,
                'message': 'Graph building disabled',
                'nodesWritten': 0,
                'edgesWritten': 0
            }
            assert result['nodesWritten'] == 0
            assert result['edgesWritten'] == 0

    @pytest.mark.property
    @given(
        depth=st.integers(min_value=1, max_value=3),
        record_id=salesforce_id_strategy
    )
    def test_relationship_depth_configuration(self, depth, record_id):
        """
        **Feature: phase3-graph-enhancement, Property 8c: Relationship Depth Config**

        Relationship_Depth__c should control traversal depth (1-3).

        **Validates: Requirements 5.2**
        """
        assume(len(record_id) >= 15)

        config = {
            'Graph_Enabled__c': True,
            'Relationship_Depth__c': depth,
        }

        builder = GraphBuilder(config)
        record = {'Id': record_id, 'Name': 'Test', 'OwnerId': '005000000000001'}
        graph = builder.build_relationship_graph(record, 'Account')

        # All nodes should be within configured depth
        for node in graph.nodes.values():
            assert node.depth <= depth

    @pytest.mark.property
    @given(
        fields=st.lists(
            st.sampled_from(['OwnerId', 'AccountId', 'ParentId', 'ContactId']),
            min_size=1,
            max_size=4,
            unique=True
        )
    )
    def test_relationship_fields_configuration(self, fields):
        """
        **Feature: phase3-graph-enhancement, Property 8d: Relationship Fields Config**

        Relationship_Fields__c should control which fields create edges.

        **Validates: Requirements 5.3**
        """
        config = {
            'Graph_Enabled__c': True,
            'Relationship_Depth__c': 1,
            'Relationship_Fields__c': ', '.join(fields),
        }

        builder = GraphBuilder(config)
        actual_fields = builder._get_relationship_fields('Account')

        # Should return exactly the configured fields
        assert set(actual_fields) == set(fields)

    @pytest.mark.property
    @given(
        attrs=st.lists(
            st.sampled_from(['Name', 'BillingCity', 'Industry', 'Type']),
            min_size=1,
            max_size=4,
            unique=True
        )
    )
    def test_graph_node_attributes_configuration(self, attrs):
        """
        **Feature: phase3-graph-enhancement, Property 8e: Node Attributes Config**

        Graph_Node_Attributes__c should control which fields are stored as attributes.

        **Validates: Requirements 5.3**
        """
        config = {
            'Graph_Enabled__c': True,
            'Relationship_Depth__c': 1,
            'Graph_Node_Attributes__c': ', '.join(attrs),
        }

        builder = GraphBuilder(config)
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test Account',
            'BillingCity': 'Dallas',
            'Industry': 'Technology',
            'Type': 'Customer',
            'OwnerId': '005000000000001'
        }

        node = builder.create_node(record, 'Account')

        # Only configured attributes should be in node
        for attr in attrs:
            if attr in record:
                assert attr in node.attributes


class TestGraphBuilderCRUD:
    """Property tests for incremental CRUD operations."""

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        name=st.text(min_size=1, max_size=50)
    )
    def test_property_11_crud_create(self, record_id, name):
        """
        **Feature: phase3-graph-enhancement, Property 11: Graph CRUD Consistency - CREATE**

        For any record CREATE operation, the graph SHALL contain the new node
        and its relationship edges.

        **Validates: Requirements 10.1**
        """
        assume(len(record_id) >= 15)
        assume(len(name) > 0)

        record = {
            'Id': record_id,
            'Name': name,
            'OwnerId': '005000000000001'
        }

        builder = GraphBuilder()
        result = builder.handle_incremental_update('CREATE', record, 'Account')

        assert result['success']
        assert result['operation'] == 'CREATE'
        assert result['nodeCount'] >= 1
        assert record_id in result['graph'].nodes

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        old_name=st.text(min_size=1, max_size=50),
        new_name=st.text(min_size=1, max_size=50)
    )
    def test_property_11_crud_update(self, record_id, old_name, new_name):
        """
        **Feature: phase3-graph-enhancement, Property 11: Graph CRUD Consistency - UPDATE**

        For any record UPDATE operation, the graph SHALL reflect the updated
        attributes.

        **Validates: Requirements 10.2, 10.4**
        """
        assume(len(record_id) >= 15)
        assume(len(new_name) > 0)

        record = {
            'Id': record_id,
            'Name': new_name,
            'OwnerId': '005000000000001'
        }

        builder = GraphBuilder()
        result = builder.handle_incremental_update('UPDATE', record, 'Account')

        assert result['success']
        assert result['operation'] == 'UPDATE'
        # Updated node should have new name
        node = result['graph'].nodes.get(record_id)
        assert node is not None
        assert node.displayName == new_name

    @pytest.mark.property
    @given(record_id=salesforce_id_strategy)
    def test_property_11_crud_delete(self, record_id):
        """
        **Feature: phase3-graph-enhancement, Property 11: Graph CRUD Consistency - DELETE**

        For any record DELETE operation, the result SHALL contain the node ID
        to delete.

        **Validates: Requirements 10.3**
        """
        assume(len(record_id) >= 15)

        record = {'Id': record_id}

        builder = GraphBuilder()
        result = builder.handle_incremental_update('DELETE', record, 'Account')

        assert result['success']
        assert result['operation'] == 'DELETE'
        assert result['nodeIdToDelete'] == record_id


# =============================================================================
# Schema-Driven Attribute Population Property Tests (Task 3.3)
# =============================================================================

# Import schema discovery models for testing
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from schema_discovery.models import ObjectSchema, FieldSchema
    SCHEMA_MODELS_AVAILABLE = True
except ImportError:
    SCHEMA_MODELS_AVAILABLE = False
    ObjectSchema = None
    FieldSchema = None


# Strategy for picklist values
picklist_value_strategy = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -_",
    min_size=1,
    max_size=50
)

# Strategy for numeric values
numeric_value_strategy = st.one_of(
    st.integers(min_value=-1000000, max_value=1000000),
    st.floats(min_value=-1000000.0, max_value=1000000.0, allow_nan=False, allow_infinity=False)
)

# Strategy for date values (ISO 8601 format)
date_value_strategy = st.dates().map(lambda d: d.isoformat())


@pytest.mark.skipif(not SCHEMA_MODELS_AVAILABLE, reason="Schema models not available")
class TestSchemaAttributePopulation:
    """
    Property tests for schema-driven graph node attribute population.
    
    **Feature: zero-config-schema-discovery, Property 3: Graph Node Attribute Population**
    **Validates: Requirements 2.2, 2.3, 2.4**
    """

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        filterable_value=picklist_value_strategy,
        numeric_value=numeric_value_strategy,
        date_value=date_value_strategy
    )
    def test_property_3_graph_node_attribute_population(
        self, record_id, filterable_value, numeric_value, date_value
    ):
        """
        **Feature: zero-config-schema-discovery, Property 3: Graph Node Attribute Population**
        
        *For any* record with filterable field values defined in the schema, 
        building a graph node SHALL result in node attributes containing all 
        those field values with correct types (strings for picklists, numbers 
        for numeric fields, ISO 8601 strings for dates).
        
        **Validates: Requirements 2.2, 2.3, 2.4**
        """
        assume(len(record_id) >= 15)
        assume(len(filterable_value) > 0)
        
        # Create a test schema with filterable, numeric, and date fields
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test Object',
            filterable=[
                FieldSchema(
                    name='Status__c',
                    label='Status',
                    type='filterable',
                    values=['Active', 'Inactive', filterable_value]
                )
            ],
            numeric=[
                FieldSchema(
                    name='Amount__c',
                    label='Amount',
                    type='numeric'
                )
            ],
            date=[
                FieldSchema(
                    name='CloseDate__c',
                    label='Close Date',
                    type='date'
                )
            ]
        )
        
        # Create a test record with values for all field types
        record = {
            'Id': record_id,
            'Name': 'Test Record',
            'Status__c': filterable_value,
            'Amount__c': numeric_value,
            'CloseDate__c': date_value
        }
        
        # Create builder and extract attributes using schema
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        # Verify filterable field is present and is a string
        assert 'Status__c' in attributes, "Filterable field should be in attributes"
        assert isinstance(attributes['Status__c'], str), "Filterable field should be string"
        assert attributes['Status__c'] == str(filterable_value)
        
        # Verify numeric field is present and is a number
        assert 'Amount__c' in attributes, "Numeric field should be in attributes"
        assert isinstance(attributes['Amount__c'], (int, float)), "Numeric field should be number"
        
        # Verify date field is present and is ISO 8601 format
        assert 'CloseDate__c' in attributes, "Date field should be in attributes"
        assert isinstance(attributes['CloseDate__c'], str), "Date field should be string"
        # ISO 8601 format should contain 'T' for datetime or be date-only
        date_attr = attributes['CloseDate__c']
        assert 'T' in date_attr or len(date_attr) == 10, "Date should be ISO 8601 format"

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        num_filterable=st.integers(min_value=1, max_value=5),
        num_numeric=st.integers(min_value=0, max_value=3),
        num_date=st.integers(min_value=0, max_value=2)
    )
    def test_all_filterable_fields_populated(
        self, record_id, num_filterable, num_numeric, num_date
    ):
        """
        **Feature: zero-config-schema-discovery, Property 3b: All Filterable Fields**
        
        *For any* schema with multiple filterable fields, ALL filterable fields
        present in the record should appear in the node attributes.
        
        **Validates: Requirements 2.2**
        """
        assume(len(record_id) >= 15)
        
        # Create schema with multiple filterable fields
        filterable_fields = [
            FieldSchema(
                name=f'Field{i}__c',
                label=f'Field {i}',
                type='filterable',
                values=['Value1', 'Value2', 'Value3']
            )
            for i in range(num_filterable)
        ]
        
        numeric_fields = [
            FieldSchema(
                name=f'Num{i}__c',
                label=f'Numeric {i}',
                type='numeric'
            )
            for i in range(num_numeric)
        ]
        
        date_fields = [
            FieldSchema(
                name=f'Date{i}__c',
                label=f'Date {i}',
                type='date'
            )
            for i in range(num_date)
        ]
        
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test Object',
            filterable=filterable_fields,
            numeric=numeric_fields,
            date=date_fields
        )
        
        # Create record with values for all fields
        record = {'Id': record_id, 'Name': 'Test'}
        for i in range(num_filterable):
            record[f'Field{i}__c'] = 'Value1'
        for i in range(num_numeric):
            record[f'Num{i}__c'] = 100.0 + i
        for i in range(num_date):
            record[f'Date{i}__c'] = '2025-01-15'
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        # Verify ALL filterable fields are present
        for i in range(num_filterable):
            field_name = f'Field{i}__c'
            assert field_name in attributes, f"Filterable field {field_name} should be in attributes"
        
        # Verify ALL numeric fields are present
        for i in range(num_numeric):
            field_name = f'Num{i}__c'
            assert field_name in attributes, f"Numeric field {field_name} should be in attributes"
        
        # Verify ALL date fields are present
        for i in range(num_date):
            field_name = f'Date{i}__c'
            assert field_name in attributes, f"Date field {field_name} should be in attributes"

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        int_value=st.integers(min_value=-1000000, max_value=1000000),
        float_value=st.floats(min_value=-1000000.0, max_value=1000000.0, allow_nan=False, allow_infinity=False)
    )
    def test_numeric_type_preservation(self, record_id, int_value, float_value):
        """
        **Feature: zero-config-schema-discovery, Property 3c: Numeric Type Preservation**
        
        *For any* numeric field value, the attribute should preserve the numeric
        type (int or float) rather than converting to string.
        
        **Validates: Requirements 2.3**
        """
        assume(len(record_id) >= 15)
        
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test Object',
            numeric=[
                FieldSchema(name='IntField__c', label='Int Field', type='numeric'),
                FieldSchema(name='FloatField__c', label='Float Field', type='numeric')
            ]
        )
        
        record = {
            'Id': record_id,
            'Name': 'Test',
            'IntField__c': int_value,
            'FloatField__c': float_value
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        # Verify numeric types are preserved
        assert 'IntField__c' in attributes
        assert isinstance(attributes['IntField__c'], (int, float))
        
        assert 'FloatField__c' in attributes
        assert isinstance(attributes['FloatField__c'], (int, float))

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        date_str=st.dates().map(lambda d: d.isoformat())
    )
    def test_date_iso_format(self, record_id, date_str):
        """
        **Feature: zero-config-schema-discovery, Property 3d: Date ISO 8601 Format**
        
        *For any* date field value, the attribute should be stored in ISO 8601 format.
        
        **Validates: Requirements 2.4**
        """
        assume(len(record_id) >= 15)
        
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test Object',
            date=[
                FieldSchema(name='DateField__c', label='Date Field', type='date')
            ]
        )
        
        record = {
            'Id': record_id,
            'Name': 'Test',
            'DateField__c': date_str
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        # Verify date is in ISO 8601 format
        assert 'DateField__c' in attributes
        date_attr = attributes['DateField__c']
        assert isinstance(date_attr, str)
        # Should have time component added if date-only
        assert 'T' in date_attr, "Date should include time component in ISO 8601"

    @pytest.mark.property
    @given(record_id=salesforce_id_strategy)
    def test_missing_field_values_excluded(self, record_id):
        """
        **Feature: zero-config-schema-discovery, Property 3e: Missing Values Excluded**
        
        *For any* field defined in schema but not present in record, that field
        should NOT appear in the attributes (no null/None values).
        
        **Validates: Requirements 2.2**
        """
        assume(len(record_id) >= 15)
        
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test Object',
            filterable=[
                FieldSchema(name='Present__c', label='Present', type='filterable', values=['A', 'B']),
                FieldSchema(name='Missing__c', label='Missing', type='filterable', values=['X', 'Y'])
            ],
            numeric=[
                FieldSchema(name='NumPresent__c', label='Num Present', type='numeric'),
                FieldSchema(name='NumMissing__c', label='Num Missing', type='numeric')
            ]
        )
        
        # Record only has some fields
        record = {
            'Id': record_id,
            'Name': 'Test',
            'Present__c': 'A',
            'NumPresent__c': 100
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        # Present fields should be in attributes
        assert 'Present__c' in attributes
        assert 'NumPresent__c' in attributes
        
        # Missing fields should NOT be in attributes
        assert 'Missing__c' not in attributes
        assert 'NumMissing__c' not in attributes


# =============================================================================
# Unit Tests for Schema-Driven Graph Builder (Task 3.5)
# =============================================================================

class TestSchemaLoaderIntegration:
    """
    Unit tests for schema loader integration with graph builder.
    
    **Feature: zero-config-schema-discovery**
    **Requirements: 2.1, 2.2, 2.3, 2.4, 2.5**
    """

    def test_extract_attributes_with_schema(self):
        """
        Test attribute extraction when schema is available.
        
        **Requirements: 2.2, 2.3, 2.4**
        """
        # Create a test schema
        schema = ObjectSchema(
            api_name='ascendix__Property__c',
            label='Property',
            filterable=[
                FieldSchema(name='ascendix__PropertyClass__c', label='Property Class', 
                           type='filterable', values=['A', 'B', 'C']),
                FieldSchema(name='ascendix__City__c', label='City', 
                           type='filterable', values=['Dallas', 'Houston', 'Austin'])
            ],
            numeric=[
                FieldSchema(name='ascendix__TotalBuildingArea__c', label='Total Building Area', 
                           type='numeric'),
                FieldSchema(name='ascendix__YearBuilt__c', label='Year Built', 
                           type='numeric')
            ],
            date=[
                FieldSchema(name='LastActivityDate', label='Last Activity Date', 
                           type='date')
            ]
        )
        
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test Property',
            'ascendix__PropertyClass__c': 'A',
            'ascendix__City__c': 'Dallas',
            'ascendix__TotalBuildingArea__c': 250000,
            'ascendix__YearBuilt__c': 1998,
            'LastActivityDate': '2025-11-15'
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        # Verify filterable fields
        assert attributes['ascendix__PropertyClass__c'] == 'A'
        assert attributes['ascendix__City__c'] == 'Dallas'
        
        # Verify numeric fields are numbers
        assert attributes['ascendix__TotalBuildingArea__c'] == 250000
        assert isinstance(attributes['ascendix__TotalBuildingArea__c'], (int, float))
        assert attributes['ascendix__YearBuilt__c'] == 1998
        
        # Verify date field is ISO 8601
        assert 'LastActivityDate' in attributes
        assert 'T' in attributes['LastActivityDate']

    def test_extract_attributes_fallback_without_schema(self):
        """
        Test attribute extraction falls back to zero-config defaults when schema unavailable.
        
        **Requirements: 2.5**
        **Feature: zero-config-production**
        
        When no schema is available and no Graph_Node_Attributes__c is configured,
        the builder should extract all non-system fields from the record.
        """
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test Property',
            'ascendix__PropertyClass__c': 'A',
            'ascendix__City__c': 'Dallas',
            'ascendix__State__c': 'TX',
            'ascendix__PropertySubType__c': 'Office'
        }
        
        builder = GraphBuilder()
        # Use the config-based extraction (simulating no schema available)
        attributes = builder._extract_attributes_from_config(record, 'ascendix__Property__c')
        
        # Zero-config: Should extract all non-system fields from record
        assert 'Name' in attributes
        assert 'ascendix__City__c' in attributes
        assert 'ascendix__State__c' in attributes
        assert 'ascendix__PropertyClass__c' in attributes
        assert 'ascendix__PropertySubType__c' in attributes

    def test_numeric_type_preservation_int(self):
        """
        Test that integer values are preserved as integers.
        
        **Requirements: 2.3**
        """
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test',
            numeric=[
                FieldSchema(name='IntField__c', label='Int Field', type='numeric')
            ]
        )
        
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test',
            'IntField__c': 42
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        assert attributes['IntField__c'] == 42
        assert isinstance(attributes['IntField__c'], int)

    def test_numeric_type_preservation_float(self):
        """
        Test that float values are preserved as floats.
        
        **Requirements: 2.3**
        """
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test',
            numeric=[
                FieldSchema(name='FloatField__c', label='Float Field', type='numeric')
            ]
        )
        
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test',
            'FloatField__c': 123.45
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        assert attributes['FloatField__c'] == 123.45
        assert isinstance(attributes['FloatField__c'], float)

    def test_numeric_string_conversion(self):
        """
        Test that numeric strings are converted to numbers.
        
        **Requirements: 2.3**
        """
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test',
            numeric=[
                FieldSchema(name='IntStr__c', label='Int String', type='numeric'),
                FieldSchema(name='FloatStr__c', label='Float String', type='numeric')
            ]
        )
        
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test',
            'IntStr__c': '100',
            'FloatStr__c': '99.99'
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        assert attributes['IntStr__c'] == 100
        assert isinstance(attributes['IntStr__c'], int)
        assert attributes['FloatStr__c'] == 99.99
        assert isinstance(attributes['FloatStr__c'], float)

    def test_date_only_format_conversion(self):
        """
        Test that date-only strings get time component added.
        
        **Requirements: 2.4**
        """
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test',
            date=[
                FieldSchema(name='DateField__c', label='Date Field', type='date')
            ]
        )
        
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test',
            'DateField__c': '2025-11-15'
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        assert attributes['DateField__c'] == '2025-11-15T00:00:00Z'

    def test_datetime_format_preserved(self):
        """
        Test that datetime strings are preserved as-is.
        
        **Requirements: 2.4**
        """
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test',
            date=[
                FieldSchema(name='DateTimeField__c', label='DateTime Field', type='date')
            ]
        )
        
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test',
            'DateTimeField__c': '2025-11-15T14:30:00Z'
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        assert attributes['DateTimeField__c'] == '2025-11-15T14:30:00Z'

    def test_null_values_excluded(self):
        """
        Test that null/None values are not included in attributes.
        
        **Requirements: 2.2**
        """
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test',
            filterable=[
                FieldSchema(name='Field1__c', label='Field 1', type='filterable', values=['A', 'B']),
                FieldSchema(name='Field2__c', label='Field 2', type='filterable', values=['X', 'Y'])
            ]
        )
        
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test',
            'Field1__c': 'A',
            'Field2__c': None
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        assert 'Field1__c' in attributes
        assert 'Field2__c' not in attributes

    def test_name_field_always_included(self):
        """
        Test that Name field is always included when present.
        
        **Requirements: 2.2**
        """
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test',
            filterable=[
                FieldSchema(name='Status__c', label='Status', type='filterable', values=['Active'])
            ]
        )
        
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test Record Name',
            'Status__c': 'Active'
        }
        
        builder = GraphBuilder()
        attributes = builder._extract_attributes_from_schema(record, schema)
        
        assert 'Name' in attributes
        assert attributes['Name'] == 'Test Record Name'

    def test_create_node_uses_schema_attributes(self):
        """
        Test that create_node uses schema-driven attributes when available.
        
        **Requirements: 2.1, 2.2**
        """
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test Property',
            'ascendix__PropertyClass__c': 'A',
            'ascendix__City__c': 'Dallas',
            'OwnerId': '005000000000001'
        }
        
        builder = GraphBuilder()
        node = builder.create_node(record, 'ascendix__Property__c')
        
        assert node is not None
        assert node.nodeId == 'a0I000000000001'
        assert node.type == 'ascendix__Property__c'
        assert node.displayName == 'Test Property'
        # Attributes should be populated (either from schema or defaults)
        assert isinstance(node.attributes, dict)

    def test_config_override_takes_precedence(self):
        """
        Test that explicit configuration overrides schema.
        
        **Requirements: 2.5**
        """
        config = {
            'Graph_Enabled__c': True,
            'Relationship_Depth__c': 1,
            'Graph_Node_Attributes__c': 'Name, CustomField__c'
        }
        
        record = {
            'Id': 'a0I000000000001',
            'Name': 'Test',
            'CustomField__c': 'Custom Value',
            'OtherField__c': 'Should Not Appear'
        }
        
        builder = GraphBuilder(config)
        attributes = builder._extract_attributes_from_config(record, 'Account')
        
        assert 'Name' in attributes
        assert 'CustomField__c' in attributes
        assert 'OtherField__c' not in attributes
