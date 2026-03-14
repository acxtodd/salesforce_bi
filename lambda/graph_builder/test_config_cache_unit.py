"""
Unit Tests for Configuration Caching (Zero-Config Production).

Tests the ConfigurationCache class that caches IndexConfiguration__mdt
settings with 5-minute TTL and fallback to Schema Cache.

**Feature: zero-config-production**
**Requirements: 1.1, 1.2, 1.3, 1.4, 1.5**
"""
import pytest
import time
import sys
import os
from unittest.mock import MagicMock
from dataclasses import dataclass
from typing import Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph_builder.config_cache import (
    ConfigurationCache, CachedConfig,
    CONFIG_CACHE_TTL_SECONDS, DEFAULT_CONFIG
)


class TestCachedConfig:
    """Tests for CachedConfig dataclass."""

    def test_cached_config_not_expired_immediately(self):
        cached = CachedConfig(config={'Graph_Enabled__c': True}, cached_at=time.time())
        assert not cached.is_expired()

    def test_cached_config_expired_after_ttl(self):
        cached = CachedConfig(
            config={'Graph_Enabled__c': True},
            cached_at=time.time() - CONFIG_CACHE_TTL_SECONDS - 1
        )
        assert cached.is_expired()

    def test_time_remaining_positive(self):
        cached = CachedConfig(config={'Graph_Enabled__c': True}, cached_at=time.time())
        assert cached.time_remaining() > 0

    def test_time_remaining_zero_when_expired(self):
        cached = CachedConfig(
            config={'Graph_Enabled__c': True},
            cached_at=time.time() - CONFIG_CACHE_TTL_SECONDS - 100
        )
        assert cached.time_remaining() == 0

    def test_cached_config_tracks_source(self):
        cached = CachedConfig(
            config={'Graph_Enabled__c': True},
            cached_at=time.time(),
            source="salesforce"
        )
        assert cached.source == "salesforce"


class TestConfigurationCache:
    """Tests for ConfigurationCache class."""

    def test_get_config_returns_defaults_for_unknown_object(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        config = cache.get_config('Unknown__c')

        assert config['Graph_Enabled__c'] == DEFAULT_CONFIG['Graph_Enabled__c']
        assert config['Object_API_Name__c'] == 'Unknown__c'

    def test_get_config_caches_result(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )

        config1 = cache.get_config('Account')
        config2 = cache.get_config('Account')

        assert config1 == config2
        assert 'Account' in cache._cache
        assert mock_sf_client.query.call_count == 1

    def test_cache_respects_ttl(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            ttl_seconds=1,
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )

        cache.get_config('Account')
        assert not cache._cache['Account'].is_expired()
        time.sleep(1.1)
        assert cache._cache['Account'].is_expired()

    def test_invalidate_specific_object(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )

        cache.get_config('Account')
        cache.get_config('Opportunity')
        cache.invalidate('Account')

        assert 'Account' not in cache._cache
        assert 'Opportunity' in cache._cache

    def test_invalidate_all(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )

        cache.get_config('Account')
        cache.get_config('Opportunity')
        cache.invalidate()

        assert len(cache._cache) == 0

    def test_set_config_manually(self):
        cache = ConfigurationCache()
        custom_config = {'Graph_Enabled__c': False, 'Relationship_Depth__c': 3}
        cache.set_config('CustomObject__c', custom_config)

        result = cache.get_config('CustomObject__c')
        assert result['Graph_Enabled__c'] == False
        assert result['Relationship_Depth__c'] == 3

    def test_get_cache_stats(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )

        cache.get_config('Account')
        cache.get_config('Opportunity')
        stats = cache.get_cache_stats()

        assert stats['total_entries'] == 2
        assert 'Account' in stats['entries']
        assert 'source' in stats['entries']['Account']

    def test_get_config_source(self):
        cache = ConfigurationCache()
        cache.set_config('TestObject__c', {'Graph_Enabled__c': True}, source="salesforce")
        
        assert cache.get_config_source('TestObject__c') == "salesforce"
        assert cache.get_config_source('NonExistent__c') is None


class TestSalesforceQueryIntegration:
    """Tests for Salesforce query integration. Requirements: 1.1, 1.2"""

    def test_query_salesforce_config_success(self):
        sf_config = {
            'Object_API_Name__c': 'TestObject__c',
            'Enabled__c': True,
            'Text_Fields__c': 'Name,Description',
            'Relationship_Fields__c': 'OwnerId,ParentId',
            'Graph_Enabled__c': True,
            'Display_Name_Field__c': 'Name',
        }
        
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': [sf_config]}
        
        cache = ConfigurationCache(salesforce_client=mock_sf_client)
        config = cache.get_config('TestObject__c')
        
        assert config['Object_API_Name__c'] == 'TestObject__c'
        assert config['Text_Fields__c'] == 'Name,Description'
        assert config['Relationship_Fields__c'] == 'OwnerId,ParentId'
        assert cache.get_config_source('TestObject__c') == "salesforce"

    def test_query_salesforce_config_not_found(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        config = cache.get_config('NonExistent__c')
        
        assert config['Object_API_Name__c'] == 'NonExistent__c'
        assert cache.get_config_source('NonExistent__c') == "default"

    def test_query_salesforce_config_error_handling(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.side_effect = Exception("API Error")
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        
        config = cache.get_config('TestObject__c')
        
        assert config['Object_API_Name__c'] == 'TestObject__c'
        assert cache.get_config_source('TestObject__c') == "default"


class TestSchemaFallbackBehavior:
    """Tests for Schema Cache fallback behavior. Requirements: 1.3"""

    def test_fallback_to_schema_cache(self):
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
        
        mock_schema = MockObjectSchema(
            api_name='TestObject__c',
            label='Test Object',
            text=[MockFieldSchema(name='Name', label='Name', type='text')],
            relationships=[MockFieldSchema(name='OwnerId', label='Owner', type='relationship')],
            filterable=[MockFieldSchema(name='Status__c', label='Status', type='filterable')],
            numeric=[MockFieldSchema(name='Amount__c', label='Amount', type='numeric')],
            date=[MockFieldSchema(name='CreatedDate', label='Created Date', type='date')]
        )
        
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = mock_schema
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        
        config = cache.get_config('TestObject__c')
        
        assert config['Object_API_Name__c'] == 'TestObject__c'
        assert config['Text_Fields__c'] == 'Name'
        assert config['Relationship_Fields__c'] == 'OwnerId'
        assert cache.get_config_source('TestObject__c') == "schema_cache"

    def test_fallback_to_default_when_schema_not_found(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        
        config = cache.get_config('TestObject__c')
        
        assert config['Object_API_Name__c'] == 'TestObject__c'
        assert cache.get_config_source('TestObject__c') == "default"


class TestCacheTTLBehavior:
    """Tests for cache TTL behavior. Requirements: 1.4, 1.5"""

    def test_cache_ttl_default_5_minutes(self):
        assert CONFIG_CACHE_TTL_SECONDS == 300

    def test_config_refresh_on_expiration(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.return_value = {'records': []}
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            ttl_seconds=1,
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )

        cache.get_config('Account')
        cached_at1 = cache._cache['Account'].cached_at

        time.sleep(1.1)
        cache._last_refresh_attempt.clear()

        cache.get_config('Account')
        cached_at2 = cache._cache['Account'].cached_at

        assert cached_at2 > cached_at1

    def test_cooldown_prevents_hammering(self):
        mock_sf_client = MagicMock()
        mock_sf_client.query.side_effect = Exception("API Error")
        mock_schema_cache = MagicMock()
        mock_schema_cache.get.return_value = None
        
        cache = ConfigurationCache(
            salesforce_client=mock_sf_client,
            schema_cache=mock_schema_cache
        )
        cache._refresh_cooldown_seconds = 60  # Long cooldown
        
        # First call - should attempt API
        cache.get_config('TestObject__c')
        first_call_count = mock_sf_client.query.call_count
        
        # Second call immediately - should use cached result (cooldown active)
        # Note: invalidate() clears cooldown, so we don't call it here
        cache._cache.pop('TestObject__c', None)  # Clear cache but not cooldown
        cache.get_config('TestObject__c')
        
        # Should not have made additional API call due to cooldown
        assert mock_sf_client.query.call_count == first_call_count


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
