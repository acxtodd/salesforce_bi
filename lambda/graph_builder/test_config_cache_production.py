"""
Property-Based Tests for Configuration Cache (Zero-Config Production).

Tests the ConfigurationCache class with property-based testing using Hypothesis
to verify configuration fetch, fallback chain, and caching behavior.

**Feature: zero-config-production**
**Requirements: 1.1, 1.2, 1.3, 1.4, 1.5**
"""
import pytest
import time
import sys
import os
from unittest.mock import patch, MagicMock, Mock
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

# Add lambda directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hypothesis import given, strategies as st, settings, assume

from graph_builder.config_cache import (
    ConfigurationCache, CachedConfig, DEFAULT_CONFIG,
    CONFIG_CACHE_TTL_SECONDS
)


# ============================================================================
# Test Data Generators (Strategies)
# ============================================================================

# Strategy for valid Salesforce object API names
sobject_name_strategy = st.from_regex(
    r'^[A-Za-z][A-Za-z0-9_]*(__c)?$',
    fullmatch=True
).filter(lambda x: len(x) >= 3 and len(x) <= 80)

# Strategy for comma-separated field lists
field_list_strategy = st.lists(
    st.from_regex(r'^[A-Za-z][A-Za-z0-9_]*(__c)?$', fullmatch=True)
    .filter(lambda x: len(x) >= 2 and len(x) <= 40),
    min_size=0,
    max_size=10
).map(lambda fields: ','.join(fields) if fields else None)

# Strategy for IndexConfiguration__mdt records
@st.composite
def salesforce_config_strategy(draw):
    """Generate valid IndexConfiguration__mdt records."""
    return {
        'Object_API_Name__c': draw(sobject_name_strategy),
        'Enabled__c': draw(st.booleans()),
        'Text_Fields__c': draw(field_list_strategy),
        'Long_Text_Fields__c': draw(field_list_strategy),
        'Relationship_Fields__c': draw(field_list_strategy),
        'Graph_Enabled__c': draw(st.booleans()),
        'Graph_Node_Attributes__c': draw(field_list_strategy),
        'Display_Name_Field__c': draw(st.sampled_from(['Name', 'Title', 'Subject', None])),
        'Chunking_Strategy__c': draw(st.sampled_from(['semantic', 'fixed', 'none', None])),
        'Max_Chunk_Tokens__c': draw(st.integers(min_value=128, max_value=2048) | st.none()),
        'Semantic_Hints__c': draw(field_list_strategy),
        'Object_Description__c': draw(st.text(min_size=0, max_size=200) | st.none()),
    }


# Strategy for ObjectSchema (from schema cache)
@st.composite
def schema_strategy(draw):
    """Generate valid ObjectSchema-like objects for testing."""
    
    @dataclass
    class MockFieldSchema:
        name: str
        label: str
        type: str
        values: Optional[List[str]] = None
        reference_to: Optional[str] = None
    
    @dataclass
    class MockObjectSchema:
        api_name: str
        label: str
        text: List[MockFieldSchema]
        relationships: List[MockFieldSchema]
        filterable: List[MockFieldSchema]
        numeric: List[MockFieldSchema]
        date: List[MockFieldSchema]
    
    api_name = draw(sobject_name_strategy)
    
    # Generate text fields
    text_count = draw(st.integers(min_value=0, max_value=5))
    text_fields = [
        MockFieldSchema(
            name=f"TextField{i}__c",
            label=f"Text Field {i}",
            type="text"
        )
        for i in range(text_count)
    ]
    
    # Generate relationship fields
    rel_count = draw(st.integers(min_value=0, max_value=3))
    rel_fields = [
        MockFieldSchema(
            name=f"RelField{i}__c",
            label=f"Relationship {i}",
            type="relationship",
            reference_to=f"RelatedObject{i}__c"
        )
        for i in range(rel_count)
    ]
    
    # Generate filterable fields
    filter_count = draw(st.integers(min_value=0, max_value=3))
    filter_fields = [
        MockFieldSchema(
            name=f"FilterField{i}__c",
            label=f"Filter {i}",
            type="filterable",
            values=["Value1", "Value2"]
        )
        for i in range(filter_count)
    ]
    
    # Generate numeric fields
    num_count = draw(st.integers(min_value=0, max_value=2))
    num_fields = [
        MockFieldSchema(
            name=f"NumField{i}__c",
            label=f"Numeric {i}",
            type="numeric"
        )
        for i in range(num_count)
    ]
    
    # Generate date fields
    date_count = draw(st.integers(min_value=0, max_value=2))
    date_fields = [
        MockFieldSchema(
            name=f"DateField{i}__c",
            label=f"Date {i}",
            type="date"
        )
        for i in range(date_count)
    ]
    
    return MockObjectSchema(
        api_name=api_name,
        label=api_name.replace('__c', '').replace('_', ' '),
        text=text_fields,
        relationships=rel_fields,
        filterable=filter_fields,
        numeric=num_fields,
        date=date_fields
    )


# ============================================================================
# Property Tests
# ============================================================================

class TestConfigurationFetchAndFallback:
    """
    **Property 1: Configuration Fetch and Fallback**
    **Validates: Requirements 1.1, 1.2, 1.3**
    
    For any Salesforce object API name, the ConfigurationCache SHALL return
    a valid configuration by following the fallback chain:
    IndexConfiguration__mdt → Schema Cache → Default configuration.
    """

    @given(sobject=sobject_name_strategy, sf_config=salesforce_config_strategy())
    @settings(max_examples=100, deadline=None)
    def test_salesforce_config_returned_when_available(self, sobject, sf_config):
        """
        **Feature: zero-config-production, Property 1: Configuration Fetch and Fallback**
        **Validates: Requirements 1.1, 1.2**
        
        When IndexConfiguration__mdt exists and is enabled, that configuration
        SHALL be returned.
        """
        # Ensure the config is for our test object and is enabled
        sf_config['Object_API_Name__c'] = sobject
        sf_config['Enabled__c'] = True
        
        # Create mock Salesforce client
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {
            'records': [sf_config]
        }
        
        # Create cache with mock client
        cache = ConfigurationCache(salesforce_client=mock_sf_client)
        
        # Get config
        config = cache.get_config(sobject)
        
        # Verify Salesforce config was used
        assert config['Object_API_Name__c'] == sobject
        assert cache.get_config_source(sobject) == "salesforce"
        
        # Verify fields from Salesforce config are present
        if sf_config.get('Text_Fields__c'):
            assert config['Text_Fields__c'] == sf_config['Text_Fields__c']
        if sf_config.get('Graph_Enabled__c') is not None:
            assert config['Graph_Enabled__c'] == sf_config['Graph_Enabled__c']

    @given(sobject=sobject_name_strategy, schema=schema_strategy())
    @settings(max_examples=100, deadline=None)
    def test_schema_cache_fallback_when_no_salesforce_config(self, sobject, schema):
        """
        **Feature: zero-config-production, Property 1: Configuration Fetch and Fallback**
        **Validates: Requirements 1.3**
        
        When no IndexConfiguration__mdt record exists, the system SHALL fall
        back to auto-discovered schema from the Schema Cache.
        """
        # Update schema to match our test object
        schema.api_name = sobject
        
        # Create mock Salesforce client that returns no records
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        
        # Create mock schema cache
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = schema
        
        # Create cache with mocks
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        
        # Get config
        config = cache.get_config(sobject)
        
        # Verify schema cache was used
        assert config['Object_API_Name__c'] == sobject
        assert cache.get_config_source(sobject) == "schema_cache"
        
        # Verify text fields from schema are in config
        if schema.text:
            expected_text_fields = ','.join([f.name for f in schema.text])
            assert config['Text_Fields__c'] == expected_text_fields
        
        # Verify relationship fields from schema are in config
        if schema.relationships:
            expected_rel_fields = ','.join([f.name for f in schema.relationships])
            assert config['Relationship_Fields__c'] == expected_rel_fields

    @given(sobject=sobject_name_strategy)
    @settings(max_examples=100, deadline=None)
    def test_default_config_fallback_when_nothing_available(self, sobject):
        """
        **Feature: zero-config-production, Property 1: Configuration Fetch and Fallback**
        **Validates: Requirements 1.1, 1.2, 1.3**
        
        When neither IndexConfiguration__mdt nor Schema Cache has data,
        the system SHALL return default configuration.
        """
        # Create mock Salesforce client that returns no records
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        
        # Create mock schema cache that returns None
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        # Create cache with mocks
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        
        # Get config
        config = cache.get_config(sobject)
        
        # Verify default config was used
        assert config['Object_API_Name__c'] == sobject
        assert cache.get_config_source(sobject) == "default"
        
        # Verify default values are present
        assert config['Graph_Enabled__c'] == DEFAULT_CONFIG['Graph_Enabled__c']
        assert config['Display_Name_Field__c'] == DEFAULT_CONFIG['Display_Name_Field__c']

    @given(sobject=sobject_name_strategy)
    @settings(max_examples=100, deadline=None)
    def test_fallback_on_salesforce_error(self, sobject):
        """
        **Feature: zero-config-production, Property 1: Configuration Fetch and Fallback**
        **Validates: Requirements 1.1, 1.2, 1.3**
        
        When Salesforce API fails, the system SHALL fall back to Schema Cache
        or default configuration.
        """
        # Create mock Salesforce client that raises an error
        mock_sf_client = MagicMock()
        mock_sf_client.query.side_effect = Exception("Salesforce API error")
        
        # Create mock schema cache that returns None
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        # Create cache with mocks
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        
        # Get config - should not raise, should fall back
        config = cache.get_config(sobject)
        
        # Verify we got a valid config (default)
        assert config['Object_API_Name__c'] == sobject
        assert 'Graph_Enabled__c' in config


class TestConfigurationCaching:
    """
    **Property 2: Configuration Caching**
    **Validates: Requirements 1.4, 1.5**
    
    For any configuration that is successfully fetched, subsequent requests
    within the 5-minute TTL SHALL return the cached configuration without
    making additional Salesforce API calls.
    """

    @given(sobject=sobject_name_strategy, sf_config=salesforce_config_strategy())
    @settings(max_examples=100, deadline=None)
    def test_cached_config_returned_within_ttl(self, sobject, sf_config):
        """
        **Feature: zero-config-production, Property 2: Configuration Caching**
        **Validates: Requirements 1.4, 1.5**
        
        Cached config SHALL be returned within TTL without additional API calls.
        """
        sf_config['Object_API_Name__c'] = sobject
        sf_config['Enabled__c'] = True
        
        # Create mock Salesforce client
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': [sf_config]}
        
        # Create cache with mock client
        cache = ConfigurationCache(salesforce_client=mock_sf_client)
        
        # First call - should query Salesforce
        config1 = cache.get_config(sobject)
        assert mock_sf_client.query.call_count == 1
        
        # Second call - should use cache
        config2 = cache.get_config(sobject)
        assert mock_sf_client.query.call_count == 1  # No additional call
        
        # Configs should be identical
        assert config1 == config2

    @given(sobject=sobject_name_strategy, sf_config=salesforce_config_strategy())
    @settings(max_examples=50, deadline=None)
    def test_cache_used_when_api_unavailable(self, sobject, sf_config):
        """
        **Feature: zero-config-production, Property 2: Configuration Caching**
        **Validates: Requirements 1.4, 1.5**
        
        When Salesforce API is unavailable, cached configuration SHALL be
        returned if available within TTL.
        """
        sf_config['Object_API_Name__c'] = sobject
        sf_config['Enabled__c'] = True
        
        # Create mock Salesforce client
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': [sf_config]}
        
        # Create cache with mock client
        cache = ConfigurationCache(salesforce_client=mock_sf_client)
        
        # First call - populate cache
        config1 = cache.get_config(sobject)
        
        # Now make Salesforce unavailable
        mock_sf_client.query.side_effect = Exception("API unavailable")
        
        # Second call - should still return cached config
        config2 = cache.get_config(sobject)
        
        # Should get same config from cache
        assert config1 == config2

    @given(sobject=sobject_name_strategy)
    @settings(max_examples=50, deadline=None)
    def test_cache_expires_after_ttl(self, sobject):
        """
        **Feature: zero-config-production, Property 2: Configuration Caching**
        **Validates: Requirements 1.4, 1.5**
        
        Cache entries SHALL expire after TTL and trigger a refresh.
        """
        # Create mock Salesforce client
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        
        # Create mock schema cache
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        # Create cache with very short TTL for testing
        cache = ConfigurationCache(
            ttl_seconds=1,
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        
        # First call
        cache.get_config(sobject)
        initial_call_count = mock_sf_client.query.call_count
        
        # Wait for cache to expire
        time.sleep(1.1)
        
        # Reset cooldown to allow refresh
        cache._last_refresh_attempt.clear()
        
        # Second call - should refresh
        cache.get_config(sobject)
        
        # Should have made additional API call
        assert mock_sf_client.query.call_count > initial_call_count


class TestConfigurationValidation:
    """Additional property tests for configuration validation."""

    @given(sobject=sobject_name_strategy)
    @settings(max_examples=100, deadline=None)
    def test_config_always_has_required_fields(self, sobject):
        """
        For any object, returned configuration SHALL always have required fields.
        """
        # Create mock that returns empty results
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        
        config = cache.get_config(sobject)
        
        # Required fields should always be present
        assert 'Object_API_Name__c' in config
        assert 'Graph_Enabled__c' in config
        assert 'Display_Name_Field__c' in config
        assert 'Enabled__c' in config

    @given(sobject=sobject_name_strategy, sf_config=salesforce_config_strategy())
    @settings(max_examples=100, deadline=None)
    def test_salesforce_config_overrides_defaults(self, sobject, sf_config):
        """
        Salesforce configuration values SHALL override default values.
        """
        sf_config['Object_API_Name__c'] = sobject
        sf_config['Enabled__c'] = True
        sf_config['Graph_Enabled__c'] = False  # Override default True
        
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': [sf_config]}
        
        cache = ConfigurationCache(salesforce_client=mock_sf_client)
        config = cache.get_config(sobject)
        
        # Salesforce value should override default
        assert config['Graph_Enabled__c'] == False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
