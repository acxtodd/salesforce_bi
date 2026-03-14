"""
Property-based tests for Graph Builder Zero-Config Production.

This module contains property tests that verify:
- Relationship fields are fetched from configuration
- Attributes are extracted from schema + configuration
- Display name uses configuration
- Graph_Enabled__c check works correctly

**Feature: zero-config-production**
**Property 5: Graph Builder Configuration**
**Property 6: Graph Disabled Handling**
**Validates: Requirements 4.1, 4.2, 4.3, 4.5**
"""
import pytest
import sys
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from hypothesis import given, strategies as st, settings, assume

# Add lambda directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use the phase3 profile with minimum 100 examples
try:
    settings.load_profile("phase3")
except Exception:
    # Fallback if profile not available
    pass

# Import GraphBuilder and models from index.py
from graph_builder.index import (
    GraphBuilder, GraphNode, GraphEdge, Graph, DEFAULT_CONFIG
)


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
    "Account", "Opportunity", "Case", "Contact", "Lead",
    "ascendix__Property__c", "ascendix__Lease__c", "ascendix__Deal__c",
    "ascendix__Availability__c", "ascendix__Sale__c", "Custom__c"
])

# Strategy for field names
field_name_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
    min_size=1,
    max_size=50
)

# Strategy for relationship field lists
relationship_fields_strategy = st.lists(
    st.sampled_from([
        'OwnerId', 'AccountId', 'ParentId', 'ContactId',
        'ascendix__Property__c', 'ascendix__Tenant__c', 'ascendix__Client__c',
        'CustomLookup__c', 'RelatedRecord__c'
    ]),
    min_size=1,
    max_size=5,
    unique=True
)

# Strategy for attribute field lists
attribute_fields_strategy = st.lists(
    st.sampled_from([
        'Name', 'Status', 'Type', 'City', 'State', 'Industry',
        'ascendix__City__c', 'ascendix__State__c', 'ascendix__PropertyClass__c',
        'CustomField__c', 'Amount', 'CloseDate'
    ]),
    min_size=1,
    max_size=8,
    unique=True
)

# Strategy for display name fields
display_name_field_strategy = st.sampled_from([
    'Name', 'Subject', 'Title', 'DisplayName__c', 'Label__c'
])


# =============================================================================
# Property Tests for Graph Builder Configuration
# =============================================================================

class TestGraphBuilderConfiguration:
    """
    Property tests for Graph Builder configuration.
    
    **Feature: zero-config-production, Property 5: Graph Builder Configuration**
    **Validates: Requirements 4.1, 4.2, 4.3**
    """

    @pytest.mark.property
    @given(
        relationship_fields=relationship_fields_strategy,
        sobject=object_type_strategy
    )
    def test_property_5a_relationship_fields_from_config(
        self, relationship_fields: List[str], sobject: str
    ):
        """
        **Feature: zero-config-production, Property 5: Graph Builder Configuration**
        **Validates: Requirements 4.1**
        
        *For any* configuration with Relationship_Fields__c, the GraphBuilder
        SHALL use those fields for relationship extraction.
        """
        # Create config with specific relationship fields
        config = DEFAULT_CONFIG.copy()
        config['Relationship_Fields__c'] = ','.join(relationship_fields)
        
        builder = GraphBuilder(config)
        
        # Get relationship fields
        result_fields = builder._get_relationship_fields(sobject)
        
        # Should return exactly the configured fields
        assert result_fields == relationship_fields, (
            f"Expected {relationship_fields}, got {result_fields}"
        )

    @pytest.mark.property
    @given(
        attribute_fields=attribute_fields_strategy,
        record_id=salesforce_id_strategy,
        sobject=object_type_strategy
    )
    def test_property_5b_attributes_from_config(
        self, attribute_fields: List[str], record_id: str, sobject: str
    ):
        """
        **Feature: zero-config-production, Property 5: Graph Builder Configuration**
        **Validates: Requirements 4.2**
        
        *For any* configuration with Graph_Node_Attributes__c, the GraphBuilder
        SHALL extract only those attributes from records.
        """
        assume(len(record_id) >= 15)
        
        # Create config with specific attribute fields
        config = DEFAULT_CONFIG.copy()
        config['Graph_Node_Attributes__c'] = ','.join(attribute_fields)
        
        builder = GraphBuilder(config)
        
        # Create a record with all possible fields
        record = {'Id': record_id}
        for field in attribute_fields:
            record[field] = f"value_{field}"
        # Add some extra fields that should NOT be extracted
        record['ExtraField1'] = 'should_not_appear'
        record['ExtraField2'] = 'should_not_appear'
        
        # Extract attributes using config
        attributes = builder._extract_attributes_from_config(record, sobject)
        
        # Should contain only configured fields (that exist in record)
        for field in attribute_fields:
            assert field in attributes, f"Expected {field} in attributes"
            assert attributes[field] == f"value_{field}"
        
        # Should NOT contain extra fields
        assert 'ExtraField1' not in attributes
        assert 'ExtraField2' not in attributes

    @pytest.mark.property
    @given(
        display_field=st.sampled_from(['Subject', 'Title', 'DisplayName__c', 'Label__c']),
        record_id=salesforce_id_strategy,
        sobject=object_type_strategy
    )
    def test_property_5c_display_name_from_config(
        self, display_field: str, record_id: str, sobject: str
    ):
        """
        **Feature: zero-config-production, Property 5: Graph Builder Configuration**
        **Validates: Requirements 4.3**
        
        *For any* configuration with Display_Name_Field__c, the GraphBuilder
        SHALL use that field for display name extraction.
        
        Note: We exclude 'Name' from the test since it's the default fallback
        and would conflict with the test setup.
        """
        assume(len(record_id) >= 15)
        
        # Create config with specific display name field (not 'Name')
        config = DEFAULT_CONFIG.copy()
        config['Display_Name_Field__c'] = display_field
        
        builder = GraphBuilder(config)
        
        # Create a record with the display field
        expected_name = f"Test Display Name for {display_field}"
        record = {
            'Id': record_id,
            display_field: expected_name,
            'Name': 'Default Name',  # Should NOT be used when display_field is configured
        }
        
        # Extract display name
        result = builder._extract_display_name(record, sobject)
        
        # Should use the configured display field
        assert result == expected_name, (
            f"Expected '{expected_name}', got '{result}'"
        )

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        sobject=object_type_strategy
    )
    def test_property_5d_fallback_to_defaults(
        self, record_id: str, sobject: str
    ):
        """
        **Feature: zero-config-production, Property 5: Graph Builder Configuration**
        **Validates: Requirements 4.1, 4.2, 4.3**
        
        *For any* configuration without specific fields, the GraphBuilder
        SHALL fall back to default behavior.
        """
        assume(len(record_id) >= 15)
        
        # Create config without specific fields (all None)
        config = DEFAULT_CONFIG.copy()
        config['Relationship_Fields__c'] = None
        config['Graph_Node_Attributes__c'] = None
        config['Display_Name_Field__c'] = None
        
        builder = GraphBuilder(config)
        
        # Test relationship fields fallback
        rel_fields = builder._get_relationship_fields(sobject)
        # Should return default fields (from schema cache or fallback)
        assert isinstance(rel_fields, list)
        assert len(rel_fields) > 0  # Should have at least some default fields
        
        # Test display name fallback
        record = {'Id': record_id, 'Name': 'Test Name'}
        display_name = builder._extract_display_name(record, sobject)
        # Should use Name field as default
        assert display_name == 'Test Name'


class TestGraphDisabledHandling:
    """
    Property tests for Graph_Enabled__c handling.
    
    **Feature: zero-config-production, Property 6: Graph Disabled Handling**
    **Validates: Requirements 4.5**
    """

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        sobject=object_type_strategy
    )
    def test_property_6a_graph_disabled_returns_empty(
        self, record_id: str, sobject: str
    ):
        """
        **Feature: zero-config-production, Property 6: Graph Disabled Handling**
        **Validates: Requirements 4.5**
        
        *For any* configuration where Graph_Enabled__c = false, the GraphBuilder
        SHALL NOT create graph nodes for records of that object type.
        """
        assume(len(record_id) >= 15)
        
        # Create config with graph disabled
        config = DEFAULT_CONFIG.copy()
        config['Graph_Enabled__c'] = False
        
        builder = GraphBuilder(config)
        
        # Create a valid record
        record = {
            'Id': record_id,
            'Name': 'Test Record',
            'OwnerId': 'owner123456789012',
        }
        
        # Build graph
        graph = builder.build_relationship_graph(record, sobject)
        
        # Should return empty graph
        assert len(graph.nodes) == 0, (
            f"Expected 0 nodes when graph disabled, got {len(graph.nodes)}"
        )
        assert len(graph.edges) == 0, (
            f"Expected 0 edges when graph disabled, got {len(graph.edges)}"
        )

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        sobject=object_type_strategy
    )
    def test_property_6b_graph_enabled_creates_nodes(
        self, record_id: str, sobject: str
    ):
        """
        **Feature: zero-config-production, Property 6: Graph Disabled Handling**
        **Validates: Requirements 4.5**
        
        *For any* configuration where Graph_Enabled__c = true (or not set),
        the GraphBuilder SHALL create graph nodes for records.
        """
        assume(len(record_id) >= 15)
        
        # Create config with graph enabled (default)
        config = DEFAULT_CONFIG.copy()
        config['Graph_Enabled__c'] = True
        
        builder = GraphBuilder(config)
        
        # Create a valid record
        record = {
            'Id': record_id,
            'Name': 'Test Record',
            'OwnerId': 'owner123456789012',
        }
        
        # Build graph
        graph = builder.build_relationship_graph(record, sobject)
        
        # Should create at least the root node
        assert len(graph.nodes) >= 1, (
            f"Expected at least 1 node when graph enabled, got {len(graph.nodes)}"
        )
        # Root node should have the record ID
        assert record_id in graph.nodes, (
            f"Expected root node {record_id} in graph"
        )

    @pytest.mark.property
    @given(
        record_id=salesforce_id_strategy,
        sobject=object_type_strategy
    )
    def test_property_6c_graph_enabled_default_true(
        self, record_id: str, sobject: str
    ):
        """
        **Feature: zero-config-production, Property 6: Graph Disabled Handling**
        **Validates: Requirements 4.5**
        
        *For any* configuration without Graph_Enabled__c set, the GraphBuilder
        SHALL default to enabled (create nodes).
        """
        assume(len(record_id) >= 15)
        
        # Create config without Graph_Enabled__c
        config = DEFAULT_CONFIG.copy()
        del config['Graph_Enabled__c']
        
        builder = GraphBuilder(config)
        
        # Create a valid record
        record = {
            'Id': record_id,
            'Name': 'Test Record',
        }
        
        # Build graph
        graph = builder.build_relationship_graph(record, sobject)
        
        # Should create nodes (default enabled)
        assert len(graph.nodes) >= 1, (
            f"Expected at least 1 node when Graph_Enabled__c not set, got {len(graph.nodes)}"
        )


# =============================================================================
# Unit Tests for Edge Cases
# =============================================================================

class TestGraphBuilderConfigurationUnit:
    """Unit tests for Graph Builder configuration edge cases."""

    def test_empty_relationship_fields_config(self):
        """Test handling of empty Relationship_Fields__c."""
        config = DEFAULT_CONFIG.copy()
        config['Relationship_Fields__c'] = ''
        
        builder = GraphBuilder(config)
        fields = builder._get_relationship_fields('Account')
        
        # Empty string should fall back to defaults
        assert isinstance(fields, list)

    def test_whitespace_in_relationship_fields(self):
        """Test handling of whitespace in Relationship_Fields__c."""
        config = DEFAULT_CONFIG.copy()
        config['Relationship_Fields__c'] = ' OwnerId , AccountId , ParentId '
        
        builder = GraphBuilder(config)
        fields = builder._get_relationship_fields('Account')
        
        # Should strip whitespace
        assert fields == ['OwnerId', 'AccountId', 'ParentId']

    def test_empty_attribute_fields_config(self):
        """Test handling of empty Graph_Node_Attributes__c."""
        config = DEFAULT_CONFIG.copy()
        config['Graph_Node_Attributes__c'] = ''
        
        builder = GraphBuilder(config)
        record = {'Id': 'test123456789012', 'Name': 'Test', 'Extra': 'Value'}
        
        attributes = builder._extract_attributes_from_config(record, 'Account')
        
        # Empty string should fall back to extracting all non-system fields
        assert 'Name' in attributes
        assert 'Extra' in attributes

    def test_display_name_fallback_chain(self):
        """Test display name fallback when configured field is missing."""
        config = DEFAULT_CONFIG.copy()
        config['Display_Name_Field__c'] = 'MissingField__c'
        
        builder = GraphBuilder(config)
        record = {
            'Id': 'test123456789012',
            'Name': 'Fallback Name',
            'Subject': 'Subject Value',
        }
        
        display_name = builder._extract_display_name(record, 'Account')
        
        # Should fall back to Name since MissingField__c doesn't exist
        assert display_name == 'Fallback Name'

    def test_display_name_id_fallback(self):
        """Test display name falls back to ID when no name fields exist."""
        config = DEFAULT_CONFIG.copy()
        config['Display_Name_Field__c'] = None
        
        builder = GraphBuilder(config)
        record = {'Id': 'test123456789012'}
        
        display_name = builder._extract_display_name(record, 'Account')
        
        # Should fall back to ID
        assert display_name == 'test123456789012'
