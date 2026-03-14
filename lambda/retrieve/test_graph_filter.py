"""
Tests for Graph Attribute Filter.

Includes property-based tests using Hypothesis and unit tests.

**Feature: zero-config-schema-discovery**
**Requirements: 4.1, 4.2, 4.3, 4.4, 4.5**
"""
import os
import sys
import pytest
from unittest.mock import Mock, MagicMock, patch
from hypothesis import given, strategies as st, settings, assume

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from graph_filter import (
    GraphAttributeFilter,
    apply_graph_filter,
    MAX_FILTER_RESULTS,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def sample_nodes():
    """Create sample graph nodes for testing."""
    return [
        {
            "nodeId": "node1",
            "type": "ascendix__Property__c",
            "displayName": "Property 1",
            "attributes": {
                "ascendix__PropertyClass__c": "A",
                "ascendix__PropertySubType__c": "Office",
                "ascendix__City__c": "Dallas",
                "ascendix__TotalBuildingArea__c": 150000,
                "ascendix__YearBuilt__c": 2010,
            },
        },
        {
            "nodeId": "node2",
            "type": "ascendix__Property__c",
            "displayName": "Property 2",
            "attributes": {
                "ascendix__PropertyClass__c": "B",
                "ascendix__PropertySubType__c": "Retail",
                "ascendix__City__c": "Houston",
                "ascendix__TotalBuildingArea__c": 75000,
                "ascendix__YearBuilt__c": 2005,
            },
        },
        {
            "nodeId": "node3",
            "type": "ascendix__Property__c",
            "displayName": "Property 3",
            "attributes": {
                "ascendix__PropertyClass__c": "A",
                "ascendix__PropertySubType__c": "Industrial",
                "ascendix__City__c": "Dallas",
                "ascendix__TotalBuildingArea__c": 250000,
                "ascendix__YearBuilt__c": 2015,
            },
        },
        {
            "nodeId": "node4",
            "type": "ascendix__Property__c",
            "displayName": "Property 4",
            "attributes": {
                "ascendix__PropertyClass__c": "C",
                "ascendix__PropertySubType__c": "Office",
                "ascendix__City__c": "Austin",
                "ascendix__TotalBuildingArea__c": 50000,
                "ascendix__YearBuilt__c": 1998,
            },
        },
    ]


@pytest.fixture
def graph_filter():
    """Create a GraphAttributeFilter instance with mocked table."""
    mock_table = Mock()
    return GraphAttributeFilter(nodes_table=mock_table)


# =============================================================================
# Property-Based Tests
# =============================================================================

# Strategy for generating picklist values
picklist_values_strategy = st.sampled_from(["A", "B", "C", "Office", "Retail", "Industrial"])

# Strategy for generating city values
city_values_strategy = st.sampled_from(["Dallas", "Houston", "Austin", "San Antonio"])

# Strategy for generating numeric values
numeric_values_strategy = st.integers(min_value=10000, max_value=500000)

# Strategy for generating node attributes
node_attributes_strategy = st.fixed_dictionaries({
    "ascendix__PropertyClass__c": picklist_values_strategy,
    "ascendix__PropertySubType__c": st.sampled_from(["Office", "Retail", "Industrial"]),
    "ascendix__City__c": city_values_strategy,
    "ascendix__TotalBuildingArea__c": numeric_values_strategy,
    "ascendix__YearBuilt__c": st.integers(min_value=1950, max_value=2025),
})

# Strategy for generating a list of nodes
nodes_strategy = st.lists(
    st.fixed_dictionaries({
        "nodeId": st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=5, max_size=18),
        "type": st.just("ascendix__Property__c"),
        "displayName": st.text(min_size=1, max_size=50),
        "attributes": node_attributes_strategy,
    }),
    min_size=1,
    max_size=20,
    unique_by=lambda x: x["nodeId"]
)


@given(
    nodes=nodes_strategy,
    filter_field=st.sampled_from(["ascendix__PropertyClass__c", "ascendix__City__c"]),
)
@settings(max_examples=100)
def test_property_filter_application_correctness_exact_match(nodes, filter_field):
    """
    **Property 5: Filter Application Correctness (exact match)**
    **Validates: Requirements 4.1, 4.2**
    
    *For any* set of filters applied to graph nodes, the Graph Attribute Filter
    SHALL return only nodes where all filter conditions are satisfied
    (exact match for picklists).
    """
    assume(len(nodes) > 0)
    
    # Pick a filter value from one of the nodes
    filter_value = nodes[0]["attributes"][filter_field]
    
    # Create filter
    filters = {filter_field: filter_value}
    
    # Apply filter
    graph_filter = GraphAttributeFilter()
    result = graph_filter.filter_nodes(nodes, filters=filters)
    
    # Verify all returned nodes match the filter
    for node in result:
        actual_value = node["attributes"].get(filter_field)
        # Case-insensitive comparison for strings
        if isinstance(actual_value, str) and isinstance(filter_value, str):
            assert actual_value.lower() == filter_value.lower(), (
                f"Node {node['nodeId']} has {filter_field}='{actual_value}' "
                f"but filter expected '{filter_value}'"
            )
        else:
            assert actual_value == filter_value
    
    # Verify no matching nodes were excluded
    expected_count = sum(
        1 for n in nodes 
        if (isinstance(n["attributes"].get(filter_field), str) and 
            isinstance(filter_value, str) and
            n["attributes"].get(filter_field, "").lower() == filter_value.lower())
        or n["attributes"].get(filter_field) == filter_value
    )
    assert len(result) == expected_count


@given(
    nodes=nodes_strategy,
    operator=st.sampled_from(["$gt", "$lt", "$gte", "$lte"]),
)
@settings(max_examples=100)
def test_property_filter_application_correctness_numeric(nodes, operator):
    """
    **Property 5: Filter Application Correctness (numeric comparison)**
    **Validates: Requirements 4.1, 4.3**
    
    *For any* set of numeric filters applied to graph nodes, the Graph Attribute
    Filter SHALL return only nodes where all comparison conditions are satisfied.
    """
    assume(len(nodes) > 0)
    
    # Use TotalBuildingArea for numeric filtering
    field_name = "ascendix__TotalBuildingArea__c"
    
    # Pick a threshold value from the middle of the range
    all_values = [n["attributes"][field_name] for n in nodes]
    threshold = sorted(all_values)[len(all_values) // 2]
    
    # Create numeric filter
    numeric_filters = {field_name: {operator: threshold}}
    
    # Apply filter
    graph_filter = GraphAttributeFilter()
    result = graph_filter.filter_nodes(nodes, numeric_filters=numeric_filters)
    
    # Verify all returned nodes satisfy the comparison
    for node in result:
        actual_value = float(node["attributes"][field_name])
        
        if operator == "$gt":
            assert actual_value > threshold, (
                f"Node {node['nodeId']} has {field_name}={actual_value} "
                f"which is not > {threshold}"
            )
        elif operator == "$lt":
            assert actual_value < threshold
        elif operator == "$gte":
            assert actual_value >= threshold
        elif operator == "$lte":
            assert actual_value <= threshold


@given(
    nodes=nodes_strategy,
    class_value=picklist_values_strategy,
    city_value=city_values_strategy,
)
@settings(max_examples=100)
def test_property_multiple_filters_and_logic(nodes, class_value, city_value):
    """
    **Property 5: Filter Application Correctness (AND logic)**
    **Validates: Requirements 4.1, 4.2**
    
    *For any* multiple filters, the Graph Attribute Filter SHALL return only
    nodes where ALL filter conditions are satisfied (AND logic).
    """
    assume(len(nodes) > 0)
    
    # Create multiple filters
    filters = {
        "ascendix__PropertyClass__c": class_value,
        "ascendix__City__c": city_value,
    }
    
    # Apply filter
    graph_filter = GraphAttributeFilter()
    result = graph_filter.filter_nodes(nodes, filters=filters)
    
    # Verify all returned nodes match ALL filters
    for node in result:
        attrs = node["attributes"]
        assert attrs.get("ascendix__PropertyClass__c", "").lower() == class_value.lower()
        assert attrs.get("ascendix__City__c", "").lower() == city_value.lower()


@given(
    nodes=nodes_strategy,
    class_value=picklist_values_strategy,
    area_threshold=numeric_values_strategy,
)
@settings(max_examples=100)
def test_property_combined_exact_and_numeric_filters(nodes, class_value, area_threshold):
    """
    **Property 5: Filter Application Correctness (combined filters)**
    **Validates: Requirements 4.1, 4.2, 4.3**
    
    *For any* combination of exact-match and numeric filters, the Graph Attribute
    Filter SHALL return only nodes satisfying all conditions.
    """
    assume(len(nodes) > 0)
    
    # Create combined filters
    filters = {"ascendix__PropertyClass__c": class_value}
    numeric_filters = {"ascendix__TotalBuildingArea__c": {"$gte": area_threshold}}
    
    # Apply filter
    graph_filter = GraphAttributeFilter()
    result = graph_filter.filter_nodes(
        nodes, 
        filters=filters, 
        numeric_filters=numeric_filters
    )
    
    # Verify all returned nodes match both filter types
    for node in result:
        attrs = node["attributes"]
        # Check exact match
        assert attrs.get("ascendix__PropertyClass__c", "").lower() == class_value.lower()
        # Check numeric comparison
        assert float(attrs.get("ascendix__TotalBuildingArea__c", 0)) >= area_threshold


# =============================================================================
# Unit Tests
# =============================================================================

class TestGraphAttributeFilter:
    """Unit tests for GraphAttributeFilter class."""
    
    def test_filter_nodes_exact_match(self, sample_nodes):
        """Test exact-match filtering returns correct nodes."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            sample_nodes,
            filters={"ascendix__PropertyClass__c": "A"}
        )
        
        assert len(result) == 2
        assert all(n["attributes"]["ascendix__PropertyClass__c"] == "A" for n in result)
    
    def test_filter_nodes_case_insensitive(self, sample_nodes):
        """Test exact-match filtering is case-insensitive."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            sample_nodes,
            filters={"ascendix__PropertyClass__c": "a"}  # lowercase
        )
        
        assert len(result) == 2
        assert all(n["attributes"]["ascendix__PropertyClass__c"] == "A" for n in result)
    
    def test_filter_nodes_numeric_gt(self, sample_nodes):
        """Test numeric greater-than filtering."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            sample_nodes,
            numeric_filters={"ascendix__TotalBuildingArea__c": {"$gt": 100000}}
        )
        
        assert len(result) == 2
        assert all(n["attributes"]["ascendix__TotalBuildingArea__c"] > 100000 for n in result)
    
    def test_filter_nodes_numeric_lt(self, sample_nodes):
        """Test numeric less-than filtering."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            sample_nodes,
            numeric_filters={"ascendix__TotalBuildingArea__c": {"$lt": 100000}}
        )
        
        assert len(result) == 2
        assert all(n["attributes"]["ascendix__TotalBuildingArea__c"] < 100000 for n in result)
    
    def test_filter_nodes_numeric_gte(self, sample_nodes):
        """Test numeric greater-than-or-equal filtering."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            sample_nodes,
            numeric_filters={"ascendix__TotalBuildingArea__c": {"$gte": 150000}}
        )
        
        assert len(result) == 2
        assert all(n["attributes"]["ascendix__TotalBuildingArea__c"] >= 150000 for n in result)
    
    def test_filter_nodes_numeric_lte(self, sample_nodes):
        """Test numeric less-than-or-equal filtering."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            sample_nodes,
            numeric_filters={"ascendix__TotalBuildingArea__c": {"$lte": 75000}}
        )
        
        assert len(result) == 2
        assert all(n["attributes"]["ascendix__TotalBuildingArea__c"] <= 75000 for n in result)
    
    def test_filter_nodes_multiple_exact_filters(self, sample_nodes):
        """Test multiple exact-match filters with AND logic."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            sample_nodes,
            filters={
                "ascendix__PropertyClass__c": "A",
                "ascendix__City__c": "Dallas",
            }
        )
        
        assert len(result) == 2
        for node in result:
            assert node["attributes"]["ascendix__PropertyClass__c"] == "A"
            assert node["attributes"]["ascendix__City__c"] == "Dallas"
    
    def test_filter_nodes_combined_filters(self, sample_nodes):
        """Test combined exact-match and numeric filters."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            sample_nodes,
            filters={"ascendix__PropertyClass__c": "A"},
            numeric_filters={"ascendix__TotalBuildingArea__c": {"$gt": 200000}}
        )
        
        assert len(result) == 1
        assert result[0]["nodeId"] == "node3"
    
    def test_filter_nodes_no_filters_returns_all(self, sample_nodes):
        """Test that no filters returns all nodes."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(sample_nodes)
        
        assert len(result) == len(sample_nodes)
    
    def test_filter_nodes_no_matches_returns_empty(self, sample_nodes):
        """Test that non-matching filters return empty list."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            sample_nodes,
            filters={"ascendix__PropertyClass__c": "X"}  # Non-existent value
        )
        
        assert len(result) == 0
    
    def test_filter_nodes_missing_attribute(self, sample_nodes):
        """Test filtering on missing attribute excludes node."""
        # Add a node without the filter attribute
        nodes_with_missing = sample_nodes + [{
            "nodeId": "node5",
            "type": "ascendix__Property__c",
            "displayName": "Property 5",
            "attributes": {
                "ascendix__City__c": "Dallas",
                # Missing ascendix__PropertyClass__c
            },
        }]
        
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            nodes_with_missing,
            filters={"ascendix__PropertyClass__c": "A"}
        )
        
        # node5 should not be included
        assert "node5" not in [n["nodeId"] for n in result]


class TestBuildFilterExpression:
    """Tests for filter expression building."""
    
    def test_build_filter_expression_exact_match(self, graph_filter):
        """Test building filter expression for exact match."""
        expr = graph_filter._build_filter_expression(
            filters={"ascendix__PropertyClass__c": "A"}
        )
        
        assert expr is not None
    
    def test_build_filter_expression_numeric(self, graph_filter):
        """Test building filter expression for numeric comparison."""
        expr = graph_filter._build_filter_expression(
            numeric_filters={"ascendix__TotalBuildingArea__c": {"$gt": 100000}}
        )
        
        assert expr is not None
    
    def test_build_filter_expression_combined(self, graph_filter):
        """Test building combined filter expression."""
        expr = graph_filter._build_filter_expression(
            filters={"ascendix__PropertyClass__c": "A"},
            numeric_filters={"ascendix__TotalBuildingArea__c": {"$gt": 100000}}
        )
        
        assert expr is not None
    
    def test_build_filter_expression_empty(self, graph_filter):
        """Test building filter expression with no filters."""
        expr = graph_filter._build_filter_expression()
        
        assert expr is None


class TestNumericConditions:
    """Tests for numeric condition building."""
    
    def test_build_numeric_condition_gt(self, graph_filter):
        """Test building greater-than condition."""
        from boto3.dynamodb.conditions import Attr
        
        attr_path = Attr("attributes.field")
        condition = graph_filter._build_numeric_condition(attr_path, "$gt", 100)
        
        assert condition is not None
    
    def test_build_numeric_condition_lt(self, graph_filter):
        """Test building less-than condition."""
        from boto3.dynamodb.conditions import Attr
        
        attr_path = Attr("attributes.field")
        condition = graph_filter._build_numeric_condition(attr_path, "$lt", 100)
        
        assert condition is not None
    
    def test_build_numeric_condition_unknown_operator(self, graph_filter):
        """Test unknown operator returns None."""
        from boto3.dynamodb.conditions import Attr
        
        attr_path = Attr("attributes.field")
        condition = graph_filter._build_numeric_condition(attr_path, "$unknown", 100)
        
        assert condition is None


class TestQueryByAttributes:
    """Tests for DynamoDB query functionality."""
    
    def test_query_by_attributes_calls_dynamodb(self):
        """Test that query_by_attributes calls DynamoDB correctly."""
        mock_table = Mock()
        mock_table.query.return_value = {
            "Items": [
                {"nodeId": "node1", "type": "ascendix__Property__c"},
                {"nodeId": "node2", "type": "ascendix__Property__c"},
            ]
        }
        
        graph_filter = GraphAttributeFilter(nodes_table=mock_table)
        
        result = graph_filter.query_by_attributes(
            object_type="ascendix__Property__c",
            filters={"ascendix__PropertyClass__c": "A"}
        )
        
        assert len(result) == 2
        assert "node1" in result
        assert "node2" in result
        mock_table.query.assert_called_once()
    
    def test_query_by_attributes_empty_result(self):
        """Test query_by_attributes with no matches."""
        mock_table = Mock()
        mock_table.query.return_value = {"Items": []}
        
        graph_filter = GraphAttributeFilter(nodes_table=mock_table)
        
        result = graph_filter.query_by_attributes(
            object_type="ascendix__Property__c",
            filters={"ascendix__PropertyClass__c": "X"}
        )
        
        assert len(result) == 0


class TestApplyGraphFilter:
    """Tests for convenience function."""
    
    def test_apply_graph_filter_function(self):
        """Test the apply_graph_filter convenience function."""
        mock_table = Mock()
        mock_table.query.return_value = {
            "Items": [{"nodeId": "node1"}]
        }
        
        result = apply_graph_filter(
            object_type="ascendix__Property__c",
            filters={"ascendix__PropertyClass__c": "A"},
            nodes_table=mock_table
        )
        
        assert len(result) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# =============================================================================
# Property Test for Empty Filter Short-Circuit (Property 6)
# =============================================================================

@given(
    object_type=st.sampled_from([
        "ascendix__Property__c",
        "ascendix__Deal__c",
        "ascendix__Availability__c",
    ]),
    filter_value=st.text(
        alphabet="XYZ123",  # Values unlikely to match any real data
        min_size=5,
        max_size=10
    ),
)
@settings(max_examples=100)
def test_property_empty_filter_short_circuit(object_type, filter_value):
    """
    **Property 6: Empty Filter Short-Circuit**
    **Validates: Requirements 4.5**
    
    *For any* query where graph filtering returns zero matching nodes,
    the Retrieve Lambda SHALL return an empty result set without
    executing vector search.
    
    This test verifies that when filters produce no matches,
    the filter_nodes method returns an empty list.
    """
    # Create nodes that won't match the filter
    nodes = [
        {
            "nodeId": f"node_{i}",
            "type": object_type,
            "displayName": f"Test Node {i}",
            "attributes": {
                "ascendix__PropertyClass__c": "A",
                "ascendix__City__c": "Dallas",
            },
        }
        for i in range(5)
    ]
    
    # Apply a filter that won't match any nodes
    graph_filter = GraphAttributeFilter()
    result = graph_filter.filter_nodes(
        nodes,
        filters={"ascendix__PropertyClass__c": filter_value}  # Won't match "A"
    )
    
    # Result should be empty
    assert len(result) == 0, (
        f"Expected empty result for non-matching filter '{filter_value}', "
        f"but got {len(result)} results"
    )


class TestEmptyFilterShortCircuit:
    """Unit tests for empty filter short-circuit behavior."""
    
    def test_empty_result_when_no_matches(self, sample_nodes):
        """Test that non-matching filters return empty list."""
        graph_filter = GraphAttributeFilter()
        
        result = graph_filter.filter_nodes(
            sample_nodes,
            filters={"ascendix__PropertyClass__c": "NonExistent"}
        )
        
        assert len(result) == 0
    
    def test_empty_result_with_numeric_filter_no_match(self, sample_nodes):
        """Test empty result when numeric filter has no matches."""
        graph_filter = GraphAttributeFilter()
        
        # All sample nodes have area < 1,000,000
        result = graph_filter.filter_nodes(
            sample_nodes,
            numeric_filters={"ascendix__TotalBuildingArea__c": {"$gt": 1000000}}
        )
        
        assert len(result) == 0
    
    def test_empty_result_with_combined_filters_no_match(self, sample_nodes):
        """Test empty result when combined filters have no matches."""
        graph_filter = GraphAttributeFilter()
        
        # Class A exists, but not in "NonExistentCity"
        result = graph_filter.filter_nodes(
            sample_nodes,
            filters={
                "ascendix__PropertyClass__c": "A",
                "ascendix__City__c": "NonExistentCity",
            }
        )
        
        assert len(result) == 0
    
    def test_query_by_attributes_returns_empty_list(self):
        """Test that query_by_attributes returns empty list when no matches."""
        mock_table = Mock()
        mock_table.query.return_value = {"Items": []}
        
        graph_filter = GraphAttributeFilter(nodes_table=mock_table)
        
        result = graph_filter.query_by_attributes(
            object_type="ascendix__Property__c",
            filters={"ascendix__PropertyClass__c": "NonExistent"}
        )
        
        assert result == []
        assert len(result) == 0
