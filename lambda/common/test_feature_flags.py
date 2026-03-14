"""
Tests for Feature Flags Module.

Tests the feature flag infrastructure for Phase 3 Graph Enhancement.
"""
import os
import sys
import time
import pytest
from unittest.mock import patch

# Add common directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from feature_flags import (
    FeatureFlagName,
    FeatureFlagProvider,
    get_feature_flags,
    is_feature_enabled,
    get_all_feature_flags,
    FEATURE_FLAG_CONFIGS,
)


class TestFeatureFlagProvider:
    """Tests for FeatureFlagProvider class."""
    
    def setup_method(self):
        """Reset environment and provider before each test."""
        # Clear any existing environment variables
        for config in FEATURE_FLAG_CONFIGS.values():
            if config.env_var in os.environ:
                del os.environ[config.env_var]
        
        # Create fresh provider instance
        self.provider = FeatureFlagProvider()
    
    def test_default_values_when_no_env_vars(self):
        """Test that default values are used when no env vars are set."""
        # Graph building should be disabled by default
        assert self.provider.is_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED) is False
        
        # Graph retrieval should be disabled by default
        assert self.provider.is_enabled(FeatureFlagName.GRAPH_RETRIEVAL_ENABLED) is False
        
        # Intent routing should be disabled by default
        assert self.provider.is_enabled(FeatureFlagName.INTENT_ROUTING_ENABLED) is False
        
        # Graph cache should be enabled by default
        assert self.provider.is_enabled(FeatureFlagName.GRAPH_CACHE_ENABLED) is True
    
    def test_env_var_true_values(self):
        """Test that various 'true' env var values are parsed correctly."""
        true_values = ["true", "True", "TRUE", "1", "yes", "Yes", "on", "enabled"]
        
        for true_val in true_values:
            os.environ["FEATURE_GRAPH_BUILDING_ENABLED"] = true_val
            provider = FeatureFlagProvider()
            assert provider.is_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED) is True, \
                f"Failed for value: {true_val}"
    
    def test_env_var_false_values(self):
        """Test that various 'false' env var values are parsed correctly."""
        false_values = ["false", "False", "FALSE", "0", "no", "No", "off", "disabled"]
        
        for false_val in false_values:
            os.environ["FEATURE_GRAPH_CACHE_ENABLED"] = false_val
            provider = FeatureFlagProvider()
            assert provider.is_enabled(FeatureFlagName.GRAPH_CACHE_ENABLED) is False, \
                f"Failed for value: {false_val}"
    
    def test_invalid_env_var_uses_default(self):
        """Test that invalid env var values fall back to default."""
        os.environ["FEATURE_GRAPH_BUILDING_ENABLED"] = "invalid"
        provider = FeatureFlagProvider()
        
        # Should use default (False) for invalid value
        assert provider.is_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED) is False
    
    def test_get_all_flags(self):
        """Test getting all feature flags at once."""
        os.environ["FEATURE_GRAPH_BUILDING_ENABLED"] = "true"
        os.environ["FEATURE_INTENT_ROUTING_ENABLED"] = "true"
        
        provider = FeatureFlagProvider()
        all_flags = provider.get_all_flags()
        
        assert all_flags["graph_building_enabled"] is True
        assert all_flags["intent_routing_enabled"] is True
        assert all_flags["graph_retrieval_enabled"] is False  # default
        assert all_flags["graph_cache_enabled"] is True  # default
    
    def test_cache_is_used(self):
        """Test that cache is used for subsequent calls."""
        provider = FeatureFlagProvider()
        
        # First call loads from env
        provider.is_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED)
        
        # Change env var
        os.environ["FEATURE_GRAPH_BUILDING_ENABLED"] = "true"
        
        # Should still return cached value (False)
        assert provider.is_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED) is False
    
    def test_cache_clear(self):
        """Test that clearing cache forces refresh."""
        provider = FeatureFlagProvider()
        
        # First call loads from env
        assert provider.is_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED) is False
        
        # Change env var
        os.environ["FEATURE_GRAPH_BUILDING_ENABLED"] = "true"
        
        # Clear cache
        provider.clear_cache()
        
        # Should now return new value
        assert provider.is_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED) is True
    
    def test_cache_ttl_expiry(self):
        """Test that cache expires after TTL."""
        provider = FeatureFlagProvider()
        provider.CACHE_TTL_SECONDS = 0.1  # 100ms for testing
        
        # First call loads from env
        assert provider.is_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED) is False
        
        # Change env var
        os.environ["FEATURE_GRAPH_BUILDING_ENABLED"] = "true"
        
        # Wait for cache to expire
        time.sleep(0.15)
        
        # Should now return new value
        assert provider.is_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED) is True


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def setup_method(self):
        """Reset environment before each test."""
        for config in FEATURE_FLAG_CONFIGS.values():
            if config.env_var in os.environ:
                del os.environ[config.env_var]
    
    def test_is_feature_enabled(self):
        """Test is_feature_enabled convenience function."""
        os.environ["FEATURE_GRAPH_RETRIEVAL_ENABLED"] = "true"
        
        # Need to clear the global singleton cache
        provider = get_feature_flags()
        provider.clear_cache()
        
        assert is_feature_enabled(FeatureFlagName.GRAPH_RETRIEVAL_ENABLED) is True
        assert is_feature_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED) is False
    
    def test_get_all_feature_flags(self):
        """Test get_all_feature_flags convenience function."""
        os.environ["FEATURE_GRAPH_BUILDING_ENABLED"] = "true"
        
        # Clear cache
        provider = get_feature_flags()
        provider.clear_cache()
        
        all_flags = get_all_feature_flags()
        
        assert isinstance(all_flags, dict)
        assert "graph_building_enabled" in all_flags
        assert all_flags["graph_building_enabled"] is True


class TestFeatureFlagConfigs:
    """Tests for feature flag configuration definitions."""
    
    def test_all_flags_have_configs(self):
        """Test that all FeatureFlagName values have configurations."""
        for flag_name in FeatureFlagName:
            assert flag_name in FEATURE_FLAG_CONFIGS, \
                f"Missing config for {flag_name}"
    
    def test_all_configs_have_required_fields(self):
        """Test that all configs have required fields."""
        for flag_name, config in FEATURE_FLAG_CONFIGS.items():
            assert config.name == flag_name
            assert isinstance(config.default_value, bool)
            assert config.description
            assert config.env_var
            assert config.env_var.startswith("FEATURE_")
    
    def test_env_var_naming_convention(self):
        """Test that env vars follow naming convention."""
        for config in FEATURE_FLAG_CONFIGS.values():
            # Should be uppercase with underscores
            assert config.env_var == config.env_var.upper()
            assert config.env_var.startswith("FEATURE_")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
