"""
Property-based tests for Cross-Object Query Handler.

Uses Hypothesis to verify correctness properties for cross-object query
detection and execution.

**Feature: zero-config-production, Property 13: Cross-Object Query Detection**
**Feature: zero-config-production, Property 14: Cross-Object Query Execution**
"""
import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List, Set, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from hypothesis import given, strategies as st, settings, assume

from cross_object_handler import (
    CrossObjectQueryHandler,
    CrossObjectQuery,
    get_cross_object_handler,
    detect_cross_object_query,
    execute_cross_object_query,
)


# =============================================================================
# Hypothesis Strategies for Cross-Object Query Data
# =============================================================================

def salesforce_object_type() -> st.SearchStrategy[str]:
    """Generate valid Salesforce object API names."""
    return st.sampled_from([
        'ascendix__Availability__c',
        'ascendix__Property__c',
        'ascendix__Lease__c',
        'ascendix__Deal__c',
        'ascendix__Listing__c',
        'ascendix__Sale__c',
        'Account',
        'Contact',
        'Opportunity',
    ])


def child_object_type() -> st.SearchStrategy[str]:
    """Generate child object types that have parent relationships."""
    return st.sampled_from([
        'ascendix__Availability__c',
        'ascendix__Lease__c',
        'ascendix__Deal__c',
        'ascendix__Listing__c',
        'ascendix__Sale__c',
        'Contact',
        'Opportunity',
    ])


def parent_field_name() -> st.SearchStrategy[str]:
    """Generate field names that typically exist on parent objects."""
    return st.sampled_from([
        'City',
        'ascendix__City__c',
        'State',
        'ascendix__State__c',
        'Country',
        'ascendix__Country__c',
        'ascendix__Class__c',
        'ascendix__Property_Type__c',
        'ascendix__SubMarket__c',
        'BillingCity',
        'BillingState',
        'Industry',
    ])


def child_field_name() -> st.SearchStrategy[str]:
    """Generate field names that typically exist on child objects."""
    return st.sampled_from([
        'Name',
        'ascendix__SQFT__c',
        'ascendix__Asking_Rate__c',
        'ascendix__Status__c',
        'OwnerId',
        'CreatedDate',
    ])


def filter_value() -> st.SearchStrategy[str]:
    """Generate filter values."""
    return st.sampled_from([
        'Plano',
        'Dallas',
        'Austin',
        'Houston',
        'Texas',
        'California',
        'A',
        'B',
        'C',
        'Office',
        'Retail',
        'Industrial',
    ])


def salesforce_record_id() -> st.SearchStrategy[str]:
    """Generate valid Salesforce record IDs."""
    return st.from_regex(r'a[0-9A-Za-z]{2}[0-9A-Za-z]{12}([0-9A-Za-z]{3})?', fullmatch=True)


@st.composite
def parent_field_filters(draw) -> Dict[str, Any]:
    """Generate filters using parent object fields."""
    num_filters = draw(st.integers(min_value=1, max_value=3))
    filters = {}
    for _ in range(num_filters):
        field = draw(parent_field_name())
        value = draw(filter_value())
        filters[field] = value
    return filters


@st.composite
def child_field_filters(draw) -> Dict[str, Any]:
    """Generate filters using child object fields."""
    num_filters = draw(st.integers(min_value=1, max_value=3))
    filters = {}
    for _ in range(num_filters):
        field = draw(child_field_name())
        value = draw(filter_value())
        filters[field] = value
    return filters


@st.composite
def numeric_filters(draw) -> Dict[str, Dict[str, Any]]:
    """Generate numeric comparison filters."""
    num_filters = draw(st.integers(min_value=0, max_value=2))
    filters = {}
    numeric_fields = ['ascendix__SQFT__c', 'ascendix__Asking_Rate__c', 'Amount']
    operators = ['$gt', '$gte', '$lt', '$lte']
    
    for _ in range(num_filters):
        field = draw(st.sampled_from(numeric_fields))
        op = draw(st.sampled_from(operators))
        value = draw(st.integers(min_value=100, max_value=100000))
        filters[field] = {op: value}
    
    return filters



# =============================================================================
# Property 13: Cross-Object Query Detection
# **Validates: Requirements 9.1, 9.2, 9.4**
# =============================================================================

class TestCrossObjectQueryDetectionProperty:
    """
    Property 13: Cross-Object Query Detection
    
    *For any* query where filter criteria (e.g., city name) match fields on a
    related object but not the target object, the Schema-Aware Decomposer SHALL
    detect this and construct a traversal path from the filter object to the
    target object.
    
    **Feature: zero-config-production, Property 13: Cross-Object Query Detection**
    **Validates: Requirements 9.1, 9.2, 9.4**
    """
    
    @given(
        target_entity=child_object_type(),
        filters=parent_field_filters(),
    )
    @settings(max_examples=100, deadline=None)
    def test_parent_field_filters_detected_as_cross_object(
        self,
        target_entity: str,
        filters: Dict[str, Any],
    ):
        """
        Property: Filters on parent fields MUST be detected as cross-object
        when there's a valid relationship between target and filter entity.
        
        **Feature: zero-config-production, Property 13: Cross-Object Query Detection**
        **Validates: Requirements 9.1, 9.2, 9.4**
        """
        # Create handler with mocked schema cache
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Determine which parent the filters point to
        filter_parents = set()
        for field_name in filters.keys():
            parent = handler.PARENT_FIELD_HINTS.get(field_name)
            if parent:
                filter_parents.add(parent)
        
        # Check if target has relationship to any of the filter parents
        has_valid_relationship = False
        expected_parent = None
        for (child, parent), _ in handler.KNOWN_RELATIONSHIPS.items():
            if child == target_entity and parent in filter_parents:
                has_valid_relationship = True
                expected_parent = parent
                break
        
        # Skip test if no valid relationship exists
        assume(has_valid_relationship)
        
        # Mock _field_exists_on_object to return False for target, True for parent
        def mock_field_exists(field_name: str, object_type: str) -> bool:
            parent_fields = handler.PARENT_FIELD_HINTS.keys()
            if field_name in parent_fields:
                return object_type == handler.PARENT_FIELD_HINTS.get(field_name)
            return object_type == target_entity
        
        with patch.object(handler, '_field_exists_on_object', side_effect=mock_field_exists):
            # Act
            result = handler.detect_cross_object_query(
                target_entity=target_entity,
                filters=filters,
                numeric_filters={},
            )
            
            # Assert: Cross-object query should be detected
            assert result is not None, \
                f"Cross-object query should be detected for {target_entity} with parent filters {filters}"
            assert result.target_entity == target_entity, \
                "Target entity should match"
            assert result.filter_entity is not None, \
                "Filter entity should be identified"
    
    @given(
        target_entity=child_object_type(),
        filters=child_field_filters(),
    )
    @settings(max_examples=100, deadline=None)
    def test_child_field_filters_not_detected_as_cross_object(
        self,
        target_entity: str,
        filters: Dict[str, Any],
    ):
        """
        Property: Filters on child fields MUST NOT be detected as cross-object.
        
        **Feature: zero-config-production, Property 13: Cross-Object Query Detection**
        **Validates: Requirements 9.1, 9.2, 9.4**
        """
        # Create handler with mocked schema cache
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Mock _field_exists_on_object to return True for target
        def mock_field_exists(field_name: str, object_type: str) -> bool:
            # Child fields exist on child objects
            child_fields = ['Name', 'ascendix__SQFT__c', 'ascendix__Asking_Rate__c', 
                           'ascendix__Status__c', 'OwnerId', 'CreatedDate']
            if field_name in child_fields:
                return object_type == target_entity
            return False
        
        with patch.object(handler, '_field_exists_on_object', side_effect=mock_field_exists):
            # Act
            result = handler.detect_cross_object_query(
                target_entity=target_entity,
                filters=filters,
                numeric_filters={},
            )
            
            # Assert: Cross-object query should NOT be detected
            assert result is None, \
                f"Cross-object query should NOT be detected for {target_entity} with child filters {filters}"
    
    @given(
        target_entity=child_object_type(),
    )
    @settings(max_examples=100, deadline=None)
    def test_empty_filters_not_detected_as_cross_object(
        self,
        target_entity: str,
    ):
        """
        Property: Empty filters MUST NOT be detected as cross-object.
        
        **Feature: zero-config-production, Property 13: Cross-Object Query Detection**
        **Validates: Requirements 9.1, 9.2, 9.4**
        """
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Act
        result = handler.detect_cross_object_query(
            target_entity=target_entity,
            filters={},
            numeric_filters={},
        )
        
        # Assert: No cross-object query for empty filters
        assert result is None, \
            "Cross-object query should NOT be detected for empty filters"
    
    @given(
        target_entity=child_object_type(),
        filters=parent_field_filters(),
    )
    @settings(max_examples=100, deadline=None)
    def test_traversal_path_includes_both_entities(
        self,
        target_entity: str,
        filters: Dict[str, Any],
    ):
        """
        Property: Traversal path MUST include both target and filter entities.
        
        **Feature: zero-config-production, Property 13: Cross-Object Query Detection**
        **Validates: Requirements 9.1, 9.2, 9.4**
        """
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Mock _field_exists_on_object
        def mock_field_exists(field_name: str, object_type: str) -> bool:
            parent_fields = handler.PARENT_FIELD_HINTS.keys()
            if field_name in parent_fields:
                return object_type == handler.PARENT_FIELD_HINTS.get(field_name)
            return object_type == target_entity
        
        with patch.object(handler, '_field_exists_on_object', side_effect=mock_field_exists):
            # Act
            result = handler.detect_cross_object_query(
                target_entity=target_entity,
                filters=filters,
                numeric_filters={},
            )
            
            # Assert: If detected, path must include both entities
            if result is not None:
                assert target_entity in result.traversal_path, \
                    "Traversal path must include target entity"
                assert result.filter_entity in result.traversal_path, \
                    "Traversal path must include filter entity"
                assert len(result.traversal_path) >= 2, \
                    "Traversal path must have at least 2 entities"



# =============================================================================
# Property 14: Cross-Object Query Execution
# **Validates: Requirements 9.5**
# =============================================================================

class TestCrossObjectQueryExecutionProperty:
    """
    Property 14: Cross-Object Query Execution
    
    *For any* cross-object query, the Retrieve Lambda SHALL first filter the
    parent/related object, then traverse the graph to find related target
    records, returning only records that satisfy the relationship.
    
    **Feature: zero-config-production, Property 14: Cross-Object Query Execution**
    **Validates: Requirements 9.5**
    """
    
    @given(
        target_entity=child_object_type(),
        filter_entity=st.just('ascendix__Property__c'),
        filters=parent_field_filters(),
        matching_parent_ids=st.lists(salesforce_record_id(), min_size=1, max_size=5),
        connected_child_ids=st.lists(salesforce_record_id(), min_size=1, max_size=10),
    )
    @settings(max_examples=100, deadline=None)
    def test_execution_returns_target_entity_records(
        self,
        target_entity: str,
        filter_entity: str,
        filters: Dict[str, Any],
        matching_parent_ids: List[str],
        connected_child_ids: List[str],
    ):
        """
        Property: Execution MUST return records of target entity type.
        
        **Feature: zero-config-production, Property 14: Cross-Object Query Execution**
        **Validates: Requirements 9.5**
        """
        # Skip if target is same as filter entity
        assume(target_entity != filter_entity)
        
        # Create cross-object query
        cross_query = CrossObjectQuery(
            target_entity=target_entity,
            filter_entity=filter_entity,
            filters=filters,
            traversal_path=[target_entity, filter_entity],
            confidence=0.8,
        )
        
        # Create handler with mocked tables
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Mock _query_nodes_by_attributes to return parent IDs
        with patch.object(handler, '_query_nodes_by_attributes') as mock_query, \
             patch.object(handler, '_traverse_to_target') as mock_traverse:
            
            mock_query.return_value = matching_parent_ids
            mock_traverse.return_value = set(connected_child_ids)
            
            # Act
            result = handler.execute_cross_object_query(
                cross_query=cross_query,
                user_sharing_buckets=set(),
            )
            
            # Assert: Result should be list of target entity IDs
            assert isinstance(result, list), \
                "Result should be a list"
            assert set(result) == set(connected_child_ids), \
                "Result should contain connected child IDs"
    
    @given(
        target_entity=child_object_type(),
        filter_entity=st.just('ascendix__Property__c'),
        filters=parent_field_filters(),
    )
    @settings(max_examples=100, deadline=None)
    def test_execution_returns_empty_when_no_parent_matches(
        self,
        target_entity: str,
        filter_entity: str,
        filters: Dict[str, Any],
    ):
        """
        Property: Execution MUST return empty when no parent records match.
        
        **Feature: zero-config-production, Property 14: Cross-Object Query Execution**
        **Validates: Requirements 9.5**
        """
        assume(target_entity != filter_entity)
        
        cross_query = CrossObjectQuery(
            target_entity=target_entity,
            filter_entity=filter_entity,
            filters=filters,
            traversal_path=[target_entity, filter_entity],
            confidence=0.8,
        )
        
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Mock _query_nodes_by_attributes to return empty list
        with patch.object(handler, '_query_nodes_by_attributes') as mock_query:
            mock_query.return_value = []
            
            # Act
            result = handler.execute_cross_object_query(
                cross_query=cross_query,
                user_sharing_buckets=set(),
            )
            
            # Assert: Result should be empty
            assert result == [], \
                "Result should be empty when no parent records match"
    
    @given(
        target_entity=child_object_type(),
        filter_entity=st.just('ascendix__Property__c'),
        filters=parent_field_filters(),
        matching_parent_ids=st.lists(salesforce_record_id(), min_size=1, max_size=5),
    )
    @settings(max_examples=100, deadline=None)
    def test_execution_returns_empty_when_no_connected_children(
        self,
        target_entity: str,
        filter_entity: str,
        filters: Dict[str, Any],
        matching_parent_ids: List[str],
    ):
        """
        Property: Execution MUST return empty when no connected children exist.
        
        **Feature: zero-config-production, Property 14: Cross-Object Query Execution**
        **Validates: Requirements 9.5**
        """
        assume(target_entity != filter_entity)
        
        cross_query = CrossObjectQuery(
            target_entity=target_entity,
            filter_entity=filter_entity,
            filters=filters,
            traversal_path=[target_entity, filter_entity],
            confidence=0.8,
        )
        
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Mock to return parents but no connected children
        with patch.object(handler, '_query_nodes_by_attributes') as mock_query, \
             patch.object(handler, '_traverse_to_target') as mock_traverse:
            
            mock_query.return_value = matching_parent_ids
            mock_traverse.return_value = set()  # No connected children
            
            # Act
            result = handler.execute_cross_object_query(
                cross_query=cross_query,
                user_sharing_buckets=set(),
            )
            
            # Assert: Result should be empty
            assert result == [], \
                "Result should be empty when no connected children exist"
    
    @given(
        target_entity=child_object_type(),
        filter_entity=st.just('ascendix__Property__c'),
        filters=parent_field_filters(),
        matching_parent_ids=st.lists(salesforce_record_id(), min_size=1, max_size=3),
        connected_child_ids=st.lists(salesforce_record_id(), min_size=1, max_size=5),
        user_buckets=st.sets(st.text(min_size=5, max_size=20), min_size=1, max_size=3),
    )
    @settings(max_examples=100, deadline=None)
    def test_execution_passes_sharing_buckets_to_traversal(
        self,
        target_entity: str,
        filter_entity: str,
        filters: Dict[str, Any],
        matching_parent_ids: List[str],
        connected_child_ids: List[str],
        user_buckets: Set[str],
    ):
        """
        Property: Execution MUST pass user sharing buckets to traversal.
        
        **Feature: zero-config-production, Property 14: Cross-Object Query Execution**
        **Validates: Requirements 9.5**
        """
        assume(target_entity != filter_entity)
        
        cross_query = CrossObjectQuery(
            target_entity=target_entity,
            filter_entity=filter_entity,
            filters=filters,
            traversal_path=[target_entity, filter_entity],
            confidence=0.8,
        )
        
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        with patch.object(handler, '_query_nodes_by_attributes') as mock_query, \
             patch.object(handler, '_traverse_to_target') as mock_traverse:
            
            mock_query.return_value = matching_parent_ids
            mock_traverse.return_value = set(connected_child_ids)
            
            # Act
            handler.execute_cross_object_query(
                cross_query=cross_query,
                user_sharing_buckets=user_buckets,
            )
            
            # Assert: Sharing buckets passed to both methods
            mock_query.assert_called_once()
            call_kwargs = mock_query.call_args[1]
            assert call_kwargs['user_sharing_buckets'] == user_buckets, \
                "User sharing buckets should be passed to query"
            
            mock_traverse.assert_called_once()
            traverse_kwargs = mock_traverse.call_args[1]
            assert traverse_kwargs['user_sharing_buckets'] == user_buckets, \
                "User sharing buckets should be passed to traversal"


# =============================================================================
# Unit Tests for CrossObjectQuery Data Class
# =============================================================================

class TestCrossObjectQueryDataClass:
    """Unit tests for CrossObjectQuery data class."""
    
    def test_to_dict_includes_all_fields(self):
        """Test that to_dict includes all fields."""
        query = CrossObjectQuery(
            target_entity='ascendix__Availability__c',
            filter_entity='ascendix__Property__c',
            filters={'City': 'Plano'},
            numeric_filters={'ascendix__SQFT__c': {'$gt': 1000}},
            traversal_path=['ascendix__Availability__c', 'ascendix__Property__c'],
            confidence=0.8,
        )
        
        result = query.to_dict()
        
        assert result['target_entity'] == 'ascendix__Availability__c'
        assert result['filter_entity'] == 'ascendix__Property__c'
        assert result['filters'] == {'City': 'Plano'}
        assert result['numeric_filters'] == {'ascendix__SQFT__c': {'$gt': 1000}}
        assert result['traversal_path'] == ['ascendix__Availability__c', 'ascendix__Property__c']
        assert result['confidence'] == 0.8
    
    def test_from_dict_creates_correct_instance(self):
        """Test that from_dict creates correct instance."""
        data = {
            'target_entity': 'ascendix__Availability__c',
            'filter_entity': 'ascendix__Property__c',
            'filters': {'City': 'Plano'},
            'numeric_filters': {'ascendix__SQFT__c': {'$gt': 1000}},
            'traversal_path': ['ascendix__Availability__c', 'ascendix__Property__c'],
            'confidence': 0.8,
        }
        
        query = CrossObjectQuery.from_dict(data)
        
        assert query.target_entity == 'ascendix__Availability__c'
        assert query.filter_entity == 'ascendix__Property__c'
        assert query.filters == {'City': 'Plano'}
        assert query.numeric_filters == {'ascendix__SQFT__c': {'$gt': 1000}}
        assert query.traversal_path == ['ascendix__Availability__c', 'ascendix__Property__c']
        assert query.confidence == 0.8


# =============================================================================
# Unit Tests for Specific Scenarios
# =============================================================================

class TestCrossObjectQueryScenarios:
    """Unit tests for specific cross-object query scenarios."""
    
    def test_availabilities_in_plano_scenario(self):
        """
        Test the "availabilities in Plano" scenario.
        
        This is the canonical example from the requirements:
        - User asks for "availabilities in Plano"
        - Availability has no City field
        - Property has City field
        - System should detect cross-object query and traverse Property→Availability
        """
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Mock _field_exists_on_object
        def mock_field_exists(field_name: str, object_type: str) -> bool:
            if field_name == 'City' or field_name == 'ascendix__City__c':
                return object_type == 'ascendix__Property__c'
            return object_type == 'ascendix__Availability__c'
        
        with patch.object(handler, '_field_exists_on_object', side_effect=mock_field_exists):
            result = handler.detect_cross_object_query(
                target_entity='ascendix__Availability__c',
                filters={'City': 'Plano'},
                numeric_filters={},
            )
            
            assert result is not None, "Should detect cross-object query"
            assert result.target_entity == 'ascendix__Availability__c'
            assert result.filter_entity == 'ascendix__Property__c'
            assert result.filters == {'City': 'Plano'}
    
    def test_leases_in_dallas_scenario(self):
        """Test the "leases in Dallas" scenario."""
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        def mock_field_exists(field_name: str, object_type: str) -> bool:
            if field_name == 'City' or field_name == 'ascendix__City__c':
                return object_type == 'ascendix__Property__c'
            return object_type == 'ascendix__Lease__c'
        
        with patch.object(handler, '_field_exists_on_object', side_effect=mock_field_exists):
            result = handler.detect_cross_object_query(
                target_entity='ascendix__Lease__c',
                filters={'City': 'Dallas'},
                numeric_filters={},
            )
            
            assert result is not None, "Should detect cross-object query"
            assert result.target_entity == 'ascendix__Lease__c'
            assert result.filter_entity == 'ascendix__Property__c'
    
    def test_class_a_availabilities_scenario(self):
        """Test filtering by property class for availabilities."""
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        def mock_field_exists(field_name: str, object_type: str) -> bool:
            if field_name == 'ascendix__Class__c':
                return object_type == 'ascendix__Property__c'
            return object_type == 'ascendix__Availability__c'
        
        with patch.object(handler, '_field_exists_on_object', side_effect=mock_field_exists):
            result = handler.detect_cross_object_query(
                target_entity='ascendix__Availability__c',
                filters={'ascendix__Class__c': 'A'},
                numeric_filters={},
            )
            
            assert result is not None, "Should detect cross-object query"
            assert result.filter_entity == 'ascendix__Property__c'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])



# =============================================================================
# Unit Tests for Multi-Hop Traversals and Error Handling
# =============================================================================

class TestMultiHopTraversals:
    """Unit tests for multi-hop traversal scenarios."""
    
    def test_single_hop_traversal(self):
        """Test single-hop traversal from Property to Availability."""
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Mock the graph tables
        mock_nodes_table = MagicMock()
        mock_edges_table = MagicMock()
        handler._nodes_table = mock_nodes_table
        handler._edges_table = mock_edges_table
        
        # Set up mock responses
        property_node = {
            'nodeId': 'a0Pxx000001PROP1',
            'type': 'ascendix__Property__c',
            'attributes': {'City': 'Plano'},
            'sharingBuckets': [],
        }
        
        availability_node = {
            'nodeId': 'a0Axx000001AVAIL',
            'type': 'ascendix__Availability__c',
            'sharingBuckets': [],
        }
        
        # Mock query for property nodes
        mock_nodes_table.query.return_value = {'Items': [property_node]}
        
        # Mock get_item for connected nodes
        mock_nodes_table.get_item.return_value = {'Item': availability_node}
        
        # Mock edges query - inbound edge TO Property FROM Availability
        # Edge type is the source node type (Availability)
        mock_edges_table.query.return_value = {
            'Items': [{
                'fromId': 'a0Axx000001AVAIL',  # Availability (source)
                'toId': 'a0Pxx000001PROP1',    # Property (target)
                'type': 'ascendix__Availability__c',  # Type of source node
            }]
        }

        # Execute - traverse from Property to find Availability
        result = handler._traverse_to_target(
            source_node_ids=['a0Pxx000001PROP1'],
            target_type='ascendix__Availability__c',
            user_sharing_buckets=set(),
        )

        # Assert - should find the Availability via inbound edge
        assert 'a0Axx000001AVAIL' in result
    
    def test_traversal_single_hop(self):
        """Test single-hop traversal from Property to Availability."""
        handler = CrossObjectQueryHandler(schema_cache=None)

        # Mock the graph tables
        mock_nodes_table = MagicMock()
        mock_edges_table = MagicMock()
        handler._nodes_table = mock_nodes_table
        handler._edges_table = mock_edges_table

        # Mock inbound edges TO Property FROM Availability
        # Edge type = source node type (Availability)
        mock_edges_table.query.return_value = {
            'Items': [{
                'fromId': 'avail1',
                'toId': 'prop1',
                'type': 'ascendix__Availability__c',
            }]
        }

        # Execute - looking for Availability (1 hop from Property)
        result = handler._traverse_to_target(
            source_node_ids=['prop1'],
            target_type='ascendix__Availability__c',
            user_sharing_buckets=set(),
        )

        # Should find the availability
        assert 'avail1' in result


class TestErrorHandling:
    """Unit tests for error handling scenarios."""
    
    def test_detect_handles_missing_schema_cache(self):
        """Test that detection handles missing schema cache gracefully."""
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # This should not raise an exception
        result = handler.detect_cross_object_query(
            target_entity='ascendix__Availability__c',
            filters={'UnknownField': 'value'},
            numeric_filters={},
        )
        
        # Should return None for unknown fields
        assert result is None
    
    def test_execute_handles_dynamodb_error(self):
        """Test that execution handles DynamoDB errors gracefully."""
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Mock the nodes table to raise an exception
        mock_nodes_table = MagicMock()
        mock_nodes_table.query.side_effect = Exception("DynamoDB error")
        handler._nodes_table = mock_nodes_table
        
        cross_query = CrossObjectQuery(
            target_entity='ascendix__Availability__c',
            filter_entity='ascendix__Property__c',
            filters={'City': 'Plano'},
            traversal_path=['ascendix__Availability__c', 'ascendix__Property__c'],
            confidence=0.8,
        )
        
        # Should return empty list, not raise exception
        result = handler.execute_cross_object_query(
            cross_query=cross_query,
            user_sharing_buckets=set(),
        )
        
        assert result == []
    
    def test_detect_handles_no_relationship(self):
        """Test detection when no relationship exists between objects."""
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Try to detect cross-object for objects with no relationship
        # Case object doesn't have a relationship to Property in our KNOWN_RELATIONSHIPS
        result = handler.detect_cross_object_query(
            target_entity='Case',  # Not in KNOWN_RELATIONSHIPS as child of Property
            filters={'City': 'Plano'},  # City is a Property field
            numeric_filters={},
        )
        
        # Should return None since Case doesn't relate to Property
        assert result is None
    
    def test_execute_with_empty_sharing_buckets(self):
        """Test execution with empty sharing buckets (public access)."""
        handler = CrossObjectQueryHandler(schema_cache=None)
        
        # Mock tables
        mock_nodes_table = MagicMock()
        mock_edges_table = MagicMock()
        handler._nodes_table = mock_nodes_table
        handler._edges_table = mock_edges_table
        
        # Node with no sharing buckets (public)
        public_node = {
            'nodeId': 'public1',
            'type': 'ascendix__Property__c',
            'attributes': {'City': 'Plano'},
            'sharingBuckets': [],  # Empty = public
        }
        
        mock_nodes_table.query.return_value = {'Items': [public_node]}
        
        cross_query = CrossObjectQuery(
            target_entity='ascendix__Availability__c',
            filter_entity='ascendix__Property__c',
            filters={'City': 'Plano'},
            traversal_path=['ascendix__Availability__c', 'ascendix__Property__c'],
            confidence=0.8,
        )
        
        # Mock traverse to return empty (no connected availabilities)
        with patch.object(handler, '_traverse_to_target', return_value=set()):
            result = handler.execute_cross_object_query(
                cross_query=cross_query,
                user_sharing_buckets=set(),  # Empty user buckets
            )
        
        # Should complete without error
        assert result == []


class TestConvenienceFunctions:
    """Unit tests for module-level convenience functions."""
    
    def test_get_cross_object_handler_returns_singleton(self):
        """Test that get_cross_object_handler returns same instance."""
        # Reset the global handler
        import cross_object_handler
        cross_object_handler._cross_object_handler = None
        
        handler1 = get_cross_object_handler()
        handler2 = get_cross_object_handler()
        
        assert handler1 is handler2
    
    def test_detect_cross_object_query_convenience(self):
        """Test the convenience function for detection."""
        # Reset the global handler
        import cross_object_handler
        cross_object_handler._cross_object_handler = None

        # This should work without raising exceptions
        result = detect_cross_object_query(
            target_entity='ascendix__Availability__c',
            filters={},
            numeric_filters={},
        )

        assert result is None  # Empty filters = no cross-object query


# =============================================================================
# Regression Tests for Optimized _traverse_to_target
# Added: 2025-12-15 - Verifies projection-only edge queries
# =============================================================================

class TestTraverseToTargetOptimization:
    """
    Regression tests for the optimized _traverse_to_target method.

    These tests verify that:
    1. Edge queries use ProjectionExpression (no full node fetches)
    2. MAX_NODES_PER_HOP limit is respected
    3. Edge `type` field is used directly for filtering

    **Added after performance fix on 2025-12-15**
    """

    def test_uses_projection_expression_on_edge_queries(self):
        """
        Verify edge queries use ProjectionExpression to minimize data transfer.

        The optimized traversal should only request fromId/toId and type fields,
        not full edge records.
        """
        handler = CrossObjectQueryHandler(schema_cache=None)

        # Mock the edges table
        mock_edges_table = MagicMock()
        handler._edges_table = mock_edges_table

        # Set up mock response with edges containing type info
        mock_edges_table.query.return_value = {
            'Items': [
                {'fromId': 'lease1', 'type': 'ascendix__Lease__c'},
                {'fromId': 'lease2', 'type': 'ascendix__Lease__c'},
            ]
        }

        # Execute traversal
        result = handler._traverse_to_target(
            source_node_ids=['prop1'],
            target_type='ascendix__Lease__c',
            user_sharing_buckets=set(),
        )

        # Verify ProjectionExpression was used in queries
        for call in mock_edges_table.query.call_args_list:
            kwargs = call[1]
            assert 'ProjectionExpression' in kwargs, \
                "Edge query must use ProjectionExpression for optimization"
            # Should only request minimal fields
            assert 'fromId' in kwargs['ProjectionExpression'] or 'toId' in kwargs['ProjectionExpression']

    def test_does_not_fetch_nodes_for_type_check(self):
        """
        Verify that _traverse_to_target does NOT call get_item on nodes table.

        The optimized version uses edge `type` field directly, eliminating
        the N+1 query problem where each edge required a node fetch.
        """
        handler = CrossObjectQueryHandler(schema_cache=None)

        # Mock both tables
        mock_nodes_table = MagicMock()
        mock_edges_table = MagicMock()
        handler._nodes_table = mock_nodes_table
        handler._edges_table = mock_edges_table

        # Set up edge responses with type info
        mock_edges_table.query.return_value = {
            'Items': [
                {'fromId': 'lease1', 'type': 'ascendix__Lease__c'},
            ]
        }

        # Execute traversal
        result = handler._traverse_to_target(
            source_node_ids=['prop1', 'prop2'],
            target_type='ascendix__Lease__c',
            user_sharing_buckets=set(),
        )

        # Verify NO get_item calls were made to nodes table
        assert mock_nodes_table.get_item.call_count == 0, \
            "Optimized traversal should NOT call get_item on nodes table"

    def test_respects_max_nodes_per_hop_limit(self):
        """
        Verify traversal stops when MAX_NODES_PER_HOP targets are found.
        """
        handler = CrossObjectQueryHandler(schema_cache=None)

        # Mock the edges table
        mock_edges_table = MagicMock()
        handler._edges_table = mock_edges_table

        # Generate more edges than MAX_NODES_PER_HOP
        from cross_object_handler import MAX_NODES_PER_HOP
        many_edges = [
            {'fromId': f'lease{i}', 'type': 'ascendix__Lease__c'}
            for i in range(MAX_NODES_PER_HOP + 50)
        ]

        mock_edges_table.query.return_value = {'Items': many_edges}

        # Execute traversal
        result = handler._traverse_to_target(
            source_node_ids=['prop1'],
            target_type='ascendix__Lease__c',
            user_sharing_buckets=set(),
        )

        # Verify result is capped at MAX_NODES_PER_HOP
        assert len(result) <= MAX_NODES_PER_HOP, \
            f"Result should be capped at MAX_NODES_PER_HOP ({MAX_NODES_PER_HOP})"

    def test_filters_by_target_type_using_edge_type_field(self):
        """
        Verify traversal uses FilterExpression to filter by edge type.

        With the edge type semantics, type = source node type. The query
        uses FilterExpression to filter server-side, so the mock should
        return only matching edges (simulating server-side filtering).
        """
        handler = CrossObjectQueryHandler(schema_cache=None)

        # Mock the edges table
        mock_edges_table = MagicMock()
        handler._edges_table = mock_edges_table

        # Mock returns only Lease edges (simulating FilterExpression filtering)
        # In production, DynamoDB's FilterExpression handles this server-side
        mock_edges_table.query.return_value = {
            'Items': [
                {'fromId': 'lease1', 'type': 'ascendix__Lease__c'},
                {'fromId': 'lease2', 'type': 'ascendix__Lease__c'},
            ]
        }

        # Execute traversal looking for Leases only
        result = handler._traverse_to_target(
            source_node_ids=['prop1'],
            target_type='ascendix__Lease__c',
            user_sharing_buckets=set(),
        )

        # Verify only Lease IDs are returned
        assert result == {'lease1', 'lease2'}, \
            "Should only return IDs where edge type matches target_type"

        # Verify query was called with FilterExpression
        call_kwargs = mock_edges_table.query.call_args.kwargs
        assert 'FilterExpression' in call_kwargs, \
            "Should use FilterExpression to filter by type"

    def test_queries_inbound_edges_only(self):
        """
        Verify traversal queries only inbound edges (via toId-index).

        With edge type = source node type:
        - Inbound edges TO Property FROM Lease have type=ascendix__Lease__c
        - Outbound edges FROM Property don't have target type in edge.type
        - Therefore only inbound queries can find targets by type
        """
        handler = CrossObjectQueryHandler(schema_cache=None)

        # Mock the edges table
        mock_edges_table = MagicMock()
        handler._edges_table = mock_edges_table

        # Inbound query returns lease edges
        mock_edges_table.query.return_value = {
            'Items': [
                {'fromId': 'lease1', 'type': 'ascendix__Lease__c'},
                {'fromId': 'lease2', 'type': 'ascendix__Lease__c'},
            ]
        }

        # Execute traversal
        result = handler._traverse_to_target(
            source_node_ids=['prop1'],
            target_type='ascendix__Lease__c',
            user_sharing_buckets=set(),
        )

        # Verify query used toId-index for inbound edges
        call_kwargs = mock_edges_table.query.call_args.kwargs
        assert call_kwargs.get('IndexName') == 'toId-index', \
            "Should query inbound edges using toId-index"

        # Verify results
        assert 'lease1' in result, "Should include inbound edge source"
        assert 'lease2' in result, "Should include inbound edge source"

    def test_handles_empty_edge_results_gracefully(self):
        """
        Verify traversal handles sources with no edges.
        """
        handler = CrossObjectQueryHandler(schema_cache=None)

        # Mock the edges table to return empty results
        mock_edges_table = MagicMock()
        mock_edges_table.query.return_value = {'Items': []}
        handler._edges_table = mock_edges_table

        # Execute traversal
        result = handler._traverse_to_target(
            source_node_ids=['prop1', 'prop2', 'prop3'],
            target_type='ascendix__Lease__c',
            user_sharing_buckets=set(),
        )

        # Should return empty set without error
        assert result == set()

    def test_deduplicates_target_ids_across_sources(self):
        """
        Verify that target IDs are deduplicated when multiple sources
        connect to the same target.
        """
        handler = CrossObjectQueryHandler(schema_cache=None)

        # Mock the edges table
        mock_edges_table = MagicMock()
        handler._edges_table = mock_edges_table

        # Both sources connect to the same lease
        def mock_query(**kwargs):
            return {'Items': [{'fromId': 'shared_lease', 'type': 'ascendix__Lease__c'}]}

        mock_edges_table.query.side_effect = mock_query

        # Execute traversal with multiple sources
        result = handler._traverse_to_target(
            source_node_ids=['prop1', 'prop2'],
            target_type='ascendix__Lease__c',
            user_sharing_buckets=set(),
        )

        # Should only have one entry for shared_lease
        assert 'shared_lease' in result
        assert len([x for x in result if x == 'shared_lease']) == 1
