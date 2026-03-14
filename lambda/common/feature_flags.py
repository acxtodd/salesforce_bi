"""
Feature Flags Module for Phase 3 Graph Enhancement.

Provides centralized feature flag management for controlling graph-related
functionality. Flags can be configured via environment variables or
DynamoDB for dynamic updates.

Design Reference: .kiro/specs/phase3-graph-enhancement/design.md
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))


class FeatureFlagName(str, Enum):
    """Enumeration of all feature flags for Phase 3 Graph Enhancement."""
    
    # Graph building during ingestion
    GRAPH_BUILDING_ENABLED = "graph_building_enabled"
    
    # Graph-aware retrieval for relationship queries
    GRAPH_RETRIEVAL_ENABLED = "graph_retrieval_enabled"
    
    # Intent classification and routing
    INTENT_ROUTING_ENABLED = "intent_routing_enabled"
    
    # Path caching for graph traversal
    GRAPH_CACHE_ENABLED = "graph_cache_enabled"


@dataclass
class FeatureFlagConfig:
    """Configuration for a single feature flag."""
    
    name: FeatureFlagName
    default_value: bool
    description: str
    env_var: str


# Feature flag definitions with defaults
FEATURE_FLAG_CONFIGS: Dict[FeatureFlagName, FeatureFlagConfig] = {
    FeatureFlagName.GRAPH_BUILDING_ENABLED: FeatureFlagConfig(
        name=FeatureFlagName.GRAPH_BUILDING_ENABLED,
        default_value=False,
        description="Enable graph construction during data ingestion",
        env_var="FEATURE_GRAPH_BUILDING_ENABLED",
    ),
    FeatureFlagName.GRAPH_RETRIEVAL_ENABLED: FeatureFlagConfig(
        name=FeatureFlagName.GRAPH_RETRIEVAL_ENABLED,
        default_value=False,
        description="Enable graph-aware retrieval for relationship queries",
        env_var="FEATURE_GRAPH_RETRIEVAL_ENABLED",
    ),
    FeatureFlagName.INTENT_ROUTING_ENABLED: FeatureFlagConfig(
        name=FeatureFlagName.INTENT_ROUTING_ENABLED,
        default_value=False,
        description="Enable intent classification and query routing",
        env_var="FEATURE_INTENT_ROUTING_ENABLED",
    ),
    FeatureFlagName.GRAPH_CACHE_ENABLED: FeatureFlagConfig(
        name=FeatureFlagName.GRAPH_CACHE_ENABLED,
        default_value=True,
        description="Enable path caching for graph traversal optimization",
        env_var="FEATURE_GRAPH_CACHE_ENABLED",
    ),
}


class FeatureFlagProvider:
    """
    Feature flag provider with environment variable support and caching.
    
    Supports multiple configuration sources:
    1. Environment variables (primary, for Lambda configuration)
    2. In-memory cache with TTL for performance
    3. Default values as fallback
    
    Usage:
        from lambda.common.feature_flags import get_feature_flags
        
        flags = get_feature_flags()
        if flags.is_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED):
            # Build graph
            pass
    """
    
    # Cache TTL in seconds (5 minutes)
    CACHE_TTL_SECONDS = 300
    
    def __init__(self) -> None:
        """Initialize the feature flag provider."""
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamp: float = 0.0
    
    def _is_cache_valid(self) -> bool:
        """Check if the cache is still valid based on TTL."""
        return (time.time() - self._cache_timestamp) < self.CACHE_TTL_SECONDS
    
    def _parse_bool_env(self, value: Optional[str], default: bool) -> bool:
        """Parse boolean value from environment variable string."""
        if value is None:
            return default
        
        value_lower = value.lower().strip()
        if value_lower in ("true", "1", "yes", "on", "enabled"):
            return True
        elif value_lower in ("false", "0", "no", "off", "disabled"):
            return False
        else:
            LOGGER.warning(
                f"Invalid boolean value '{value}', using default: {default}"
            )
            return default
    
    def _load_flags_from_env(self) -> Dict[str, bool]:
        """Load all feature flags from environment variables."""
        flags: Dict[str, bool] = {}
        
        for flag_name, config in FEATURE_FLAG_CONFIGS.items():
            env_value = os.environ.get(config.env_var)
            flags[flag_name.value] = self._parse_bool_env(
                env_value, config.default_value
            )
        
        return flags
    
    def _refresh_cache(self) -> None:
        """Refresh the feature flag cache from all sources."""
        try:
            flags = self._load_flags_from_env()
            self._cache = {"flags": flags}
            self._cache_timestamp = time.time()
            
            LOGGER.debug(f"Feature flags refreshed: {flags}")
        except Exception as e:
            LOGGER.error(f"Error refreshing feature flags: {e}")
            # Keep existing cache on error
            if not self._cache:
                # Initialize with defaults if no cache exists
                self._cache = {
                    "flags": {
                        name.value: config.default_value
                        for name, config in FEATURE_FLAG_CONFIGS.items()
                    }
                }
    
    def is_enabled(
        self,
        flag_name: FeatureFlagName,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Check if a feature flag is enabled.
        
        Args:
            flag_name: The feature flag to check
            context: Optional context for conditional evaluation (future use)
        
        Returns:
            True if the feature is enabled, False otherwise
        """
        if not self._is_cache_valid():
            self._refresh_cache()
        
        flags = self._cache.get("flags", {})
        is_enabled = flags.get(
            flag_name.value,
            FEATURE_FLAG_CONFIGS[flag_name].default_value,
        )
        
        LOGGER.debug(f"Feature flag {flag_name.value}: {is_enabled}")
        return is_enabled
    
    def get_all_flags(self) -> Dict[str, bool]:
        """
        Get all feature flags and their current values.
        
        Returns:
            Dictionary mapping flag names to their boolean values
        """
        if not self._is_cache_valid():
            self._refresh_cache()
        
        return self._cache.get("flags", {}).copy()
    
    def clear_cache(self) -> None:
        """Clear the feature flag cache, forcing a refresh on next access."""
        self._cache = {}
        self._cache_timestamp = 0.0
        LOGGER.info("Feature flag cache cleared")


# Global singleton instance
_feature_flag_provider: Optional[FeatureFlagProvider] = None


def get_feature_flags() -> FeatureFlagProvider:
    """
    Get the global feature flag provider instance.
    
    Returns:
        The singleton FeatureFlagProvider instance
    """
    global _feature_flag_provider
    if _feature_flag_provider is None:
        _feature_flag_provider = FeatureFlagProvider()
    return _feature_flag_provider


def is_feature_enabled(
    flag_name: FeatureFlagName,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Convenience function to check if a feature flag is enabled.
    
    Args:
        flag_name: The feature flag to check
        context: Optional context for conditional evaluation
    
    Returns:
        True if the feature is enabled, False otherwise
    
    Example:
        from lambda.common.feature_flags import is_feature_enabled, FeatureFlagName
        
        if is_feature_enabled(FeatureFlagName.GRAPH_BUILDING_ENABLED):
            build_graph(record)
    """
    return get_feature_flags().is_enabled(flag_name, context)


def get_all_feature_flags() -> Dict[str, bool]:
    """
    Get all feature flags and their current values.
    
    Returns:
        Dictionary mapping flag names to their boolean values
    """
    return get_feature_flags().get_all_flags()


# Export commonly used items
__all__ = [
    "FeatureFlagName",
    "FeatureFlagProvider",
    "get_feature_flags",
    "is_feature_enabled",
    "get_all_feature_flags",
    "FEATURE_FLAG_CONFIGS",
]
