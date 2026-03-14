"""
Configuration Caching for Graph Builder.

Implements caching of IndexConfiguration__mdt settings with 5-minute TTL.
Falls back to Schema Cache if configuration is unavailable.

**Feature: zero-config-production**
**Requirements: 1.1, 1.2, 1.3, 1.4, 1.5**
"""
import os
import sys
import time
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timezone

# Set up logging
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Cache TTL in seconds (5 minutes as per requirements)
CONFIG_CACHE_TTL_SECONDS = 300

# Default configuration when IndexConfiguration__mdt is not available
DEFAULT_CONFIG = {
    'Graph_Enabled__c': True,
    'Relationship_Depth__c': 2,
    'Relationship_Fields__c': None,
    'Graph_Node_Attributes__c': None,
    'Object_API_Name__c': None,
    'Enabled__c': True,
    'Text_Fields__c': None,
    'Long_Text_Fields__c': None,
    'Rich_Text_Fields__c': None,
    'Display_Name_Field__c': 'Name',
    'Preview_Fields__c': None,
    'Chunking_Strategy__c': 'semantic',
    'Max_Chunk_Tokens__c': 512,
    'Semantic_Hints__c': None,
    'Object_Description__c': None,
}


@dataclass
class CachedConfig:
    """Cached configuration entry with TTL tracking."""
    config: Dict[str, Any]
    cached_at: float
    ttl_seconds: int = CONFIG_CACHE_TTL_SECONDS
    source: str = "default"  # "salesforce", "schema_cache", or "default"

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return time.time() - self.cached_at > self.ttl_seconds

    def time_remaining(self) -> float:
        """Get seconds remaining until expiration."""
        remaining = self.ttl_seconds - (time.time() - self.cached_at)
        return max(0, remaining)


class ConfigurationCache:
    """
    In-memory cache for IndexConfiguration__mdt settings.

    Caches configuration per object type with 5-minute TTL.
    Falls back to Schema Cache, then defaults if configuration is unavailable.

    **Requirements: 1.1, 1.2, 1.3, 1.4, 1.5**
    """

    def __init__(
        self,
        ttl_seconds: int = CONFIG_CACHE_TTL_SECONDS,
        salesforce_client=None,
        schema_cache=None
    ):
        """
        Initialize configuration cache.

        Args:
            ttl_seconds: Cache TTL in seconds (default 5 minutes)
            salesforce_client: Optional SalesforceClient instance for testing
            schema_cache: Optional SchemaCache instance for testing
        """
        self._cache: Dict[str, CachedConfig] = {}
        self._ttl_seconds = ttl_seconds
        self._salesforce_client = salesforce_client
        self._schema_cache = schema_cache
        self._last_refresh_attempt: Dict[str, float] = {}
        self._refresh_cooldown_seconds = 30  # Avoid hammering Salesforce on errors

    def get_config(self, sobject: str) -> Dict[str, Any]:
        """
        Get configuration for an object type.

        Returns cached config if valid, otherwise fetches from Salesforce
        or falls back to Schema Cache, then defaults.

        **Property 1: Configuration Fetch and Fallback**
        **Validates: Requirements 1.1, 1.2, 1.3**

        Args:
            sobject: Salesforce object API name

        Returns:
            Configuration dictionary
        """
        # Check cache first
        if sobject in self._cache:
            cached = self._cache[sobject]
            if not cached.is_expired():
                LOGGER.debug(f"Cache hit for {sobject} (source: {cached.source})")
                return cached.config

        # Try to refresh from Salesforce
        config, source = self._fetch_config(sobject)

        # Cache the result
        self._cache[sobject] = CachedConfig(
            config=config,
            cached_at=time.time(),
            ttl_seconds=self._ttl_seconds,
            source=source
        )

        return config

    def _fetch_config(self, sobject: str) -> tuple[Dict[str, Any], str]:
        """
        Fetch configuration with fallback chain.

        Fallback chain:
        1. Salesforce IndexConfiguration__mdt
        2. Schema Cache (auto-discovered schema)
        3. Default configuration

        **Property 2: Configuration Caching**
        **Validates: Requirements 1.4, 1.5**

        Args:
            sobject: Salesforce object API name

        Returns:
            Tuple of (configuration dictionary, source string)
        """
        # Check cooldown to avoid hammering Salesforce on errors
        last_attempt = self._last_refresh_attempt.get(sobject, 0)
        if time.time() - last_attempt < self._refresh_cooldown_seconds:
            # Return cached or default during cooldown
            if sobject in self._cache:
                cached = self._cache[sobject]
                return cached.config, cached.source
            return self._get_default_config(sobject), "default"

        self._last_refresh_attempt[sobject] = time.time()

        # Step 1: Try to fetch from Salesforce IndexConfiguration__mdt
        try:
            config = self._query_salesforce_config(sobject)
            if config:
                LOGGER.info(f"Loaded config for {sobject} from Salesforce IndexConfiguration__mdt")
                return config, "salesforce"
        except Exception as e:
            LOGGER.warning(f"Error fetching config from Salesforce for {sobject}: {str(e)}")

        # Step 2: Fall back to Schema Cache
        try:
            config = self._build_config_from_schema_cache(sobject)
            if config:
                LOGGER.info(f"Built config for {sobject} from Schema Cache")
                return config, "schema_cache"
        except Exception as e:
            LOGGER.warning(f"Error building config from Schema Cache for {sobject}: {str(e)}")

        # Step 3: Fall back to defaults
        LOGGER.info(f"Using default config for {sobject}")
        return self._get_default_config(sobject), "default"

    def _get_salesforce_client(self):
        """
        Get or create Salesforce REST API client.

        Returns:
            SalesforceClient instance
        """
        if self._salesforce_client is not None:
            return self._salesforce_client

        # Import here to avoid circular imports and allow testing without boto3
        try:
            # Add common directory to path if needed
            common_path = os.path.join(os.path.dirname(__file__), '..', 'common')
            if common_path not in sys.path:
                sys.path.insert(0, common_path)

            from salesforce_client import get_salesforce_client
            self._salesforce_client = get_salesforce_client()
            return self._salesforce_client
        except Exception as e:
            LOGGER.error(f"Failed to create Salesforce client: {e}")
            raise

    def _query_salesforce_config(self, sobject: str) -> Optional[Dict[str, Any]]:
        """
        Query IndexConfiguration__mdt from Salesforce.

        **Requirements: 1.1, 1.2**

        Args:
            sobject: Salesforce object API name

        Returns:
            Configuration dictionary or None if not found
        """
        try:
            client = self._get_salesforce_client()

            # Query IndexConfiguration__mdt for this object
            soql = f"""
                SELECT
                    DeveloperName,
                    Object_API_Name__c,
                    Enabled__c,
                    Text_Fields__c,
                    Long_Text_Fields__c,
                    Relationship_Fields__c,
                    Graph_Enabled__c,
                    Graph_Node_Attributes__c,
                    Display_Name_Field__c,
                    Chunking_Strategy__c,
                    Max_Chunk_Tokens__c,
                    Semantic_Hints__c,
                    Object_Description__c
                FROM IndexConfiguration__mdt
                WHERE Object_API_Name__c = '{sobject}'
                AND Enabled__c = true
                LIMIT 1
            """

            result = client.query(soql)
            records = result.get('records', [])

            if not records:
                LOGGER.debug(f"No IndexConfiguration__mdt found for {sobject}")
                return None

            record = records[0]

            # Parse configuration fields into dictionary
            config = self._parse_salesforce_config(record)
            return config

        except Exception as e:
            LOGGER.error(f"Error querying IndexConfiguration__mdt for {sobject}: {e}")
            raise

    def _parse_salesforce_config(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse Salesforce IndexConfiguration__mdt record into configuration dictionary.

        Args:
            record: Salesforce record from query

        Returns:
            Configuration dictionary
        """
        # Start with defaults and override with Salesforce values
        config = DEFAULT_CONFIG.copy()

        # Map Salesforce fields to config keys
        field_mapping = {
            'Object_API_Name__c': 'Object_API_Name__c',
            'Enabled__c': 'Enabled__c',
            'Text_Fields__c': 'Text_Fields__c',
            'Long_Text_Fields__c': 'Long_Text_Fields__c',
            'Relationship_Fields__c': 'Relationship_Fields__c',
            'Graph_Enabled__c': 'Graph_Enabled__c',
            'Graph_Node_Attributes__c': 'Graph_Node_Attributes__c',
            'Display_Name_Field__c': 'Display_Name_Field__c',
            'Chunking_Strategy__c': 'Chunking_Strategy__c',
            'Max_Chunk_Tokens__c': 'Max_Chunk_Tokens__c',
            'Semantic_Hints__c': 'Semantic_Hints__c',
            'Object_Description__c': 'Object_Description__c',
        }

        for sf_field, config_key in field_mapping.items():
            value = record.get(sf_field)
            if value is not None:
                config[config_key] = value

        return config

    def _get_schema_cache(self):
        """
        Get or create Schema Cache instance.

        Returns:
            SchemaCache instance
        """
        if self._schema_cache is not None:
            return self._schema_cache

        try:
            # Try local import first (if bundled in same package)
            # This fixes the issue in ChunkingLambda where schema_discovery is local
            try:
                from schema_discovery.cache import SchemaCache
                self._schema_cache = SchemaCache()
                return self._schema_cache
            except ImportError:
                pass

            # Fallback: Import schema cache from retrieve lambda (legacy path)
            schema_discovery_path = os.path.join(
                os.path.dirname(__file__), '..', 'retrieve', 'schema_discovery'
            )
            if schema_discovery_path not in sys.path:
                sys.path.insert(0, schema_discovery_path)

            from cache import SchemaCache
            self._schema_cache = SchemaCache()
            return self._schema_cache
        except Exception as e:
            LOGGER.error(f"Failed to create Schema Cache: {e}")
            raise

    def _build_config_from_schema_cache(self, sobject: str) -> Optional[Dict[str, Any]]:
        """
        Build configuration from auto-discovered schema in Schema Cache.

        **Requirements: 1.3**

        Args:
            sobject: Salesforce object API name

        Returns:
            Configuration dictionary or None if not found in cache
        """
        try:
            schema_cache = self._get_schema_cache()
            schema = schema_cache.get(sobject)

            if schema is None:
                LOGGER.debug(f"No schema found in Schema Cache for {sobject}")
                return None

            # Build configuration from schema
            config = DEFAULT_CONFIG.copy()
            config['Object_API_Name__c'] = sobject
            config['Enabled__c'] = True

            # Extract text fields from schema
            text_fields = [f.name for f in schema.text]
            if text_fields:
                config['Text_Fields__c'] = ','.join(text_fields)

            # Extract relationship fields from schema
            relationship_fields = [f.name for f in schema.relationships]
            if relationship_fields:
                config['Relationship_Fields__c'] = ','.join(relationship_fields)

            # Extract filterable fields as potential graph node attributes
            filterable_fields = [f.name for f in schema.filterable]
            numeric_fields = [f.name for f in schema.numeric]
            date_fields = [f.name for f in schema.date]
            # Also include text fields (City, State, etc.) for graph filtering
            text_fields_attr = [f.name for f in schema.text]

            # Combine filterable, numeric, date, and text fields for graph attributes
            graph_attributes = filterable_fields + numeric_fields + date_fields + text_fields_attr
            if graph_attributes:
                config['Graph_Node_Attributes__c'] = ','.join(graph_attributes)

            # Use schema label for display name field if available
            config['Display_Name_Field__c'] = 'Name'

            return config

        except Exception as e:
            LOGGER.error(f"Error building config from Schema Cache for {sobject}: {e}")
            raise

    def _get_default_config(self, sobject: str) -> Dict[str, Any]:
        """
        Get default configuration for an object type.

        Args:
            sobject: Salesforce object API name

        Returns:
            Default configuration dictionary
        """
        config = DEFAULT_CONFIG.copy()
        config['Object_API_Name__c'] = sobject
        return config

    def invalidate(self, sobject: Optional[str] = None) -> None:
        """
        Invalidate cached configuration.

        Args:
            sobject: Object type to invalidate, or None to invalidate all
        """
        if sobject:
            self._cache.pop(sobject, None)
            self._last_refresh_attempt.pop(sobject, None)
        else:
            self._cache.clear()
            self._last_refresh_attempt.clear()

    def set_config(self, sobject: str, config: Dict[str, Any], source: str = "manual") -> None:
        """
        Manually set configuration (useful for testing and Step Functions).

        Args:
            sobject: Salesforce object API name
            config: Configuration dictionary
            source: Source of the configuration
        """
        self._cache[sobject] = CachedConfig(
            config=config,
            cached_at=time.time(),
            ttl_seconds=self._ttl_seconds,
            source=source
        )

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics for monitoring.

        Returns:
            Dictionary with cache stats
        """
        stats = {
            'total_entries': len(self._cache),
            'entries': {}
        }

        for sobject, cached in self._cache.items():
            stats['entries'][sobject] = {
                'is_expired': cached.is_expired(),
                'time_remaining_seconds': cached.time_remaining(),
                'source': cached.source,
                'cached_at': datetime.fromtimestamp(
                    cached.cached_at, tz=timezone.utc
                ).isoformat()
            }

        return stats

    def get_config_source(self, sobject: str) -> Optional[str]:
        """
        Get the source of cached configuration for an object.

        Args:
            sobject: Salesforce object API name

        Returns:
            Source string ("salesforce", "schema_cache", "default") or None if not cached
        """
        if sobject in self._cache:
            return self._cache[sobject].source
        return None


# Global cache instance for Lambda warm starts
_config_cache: Optional[ConfigurationCache] = None


def get_config_cache() -> ConfigurationCache:
    """
    Get the global configuration cache instance.

    Creates a new instance if none exists (cold start).

    Returns:
        ConfigurationCache instance
    """
    global _config_cache
    if _config_cache is None:
        _config_cache = ConfigurationCache()
    return _config_cache


def get_object_config(sobject: str) -> Dict[str, Any]:
    """
    Convenience function to get configuration for an object.

    Args:
        sobject: Salesforce object API name

    Returns:
        Configuration dictionary
    """
    return get_config_cache().get_config(sobject)


def invalidate_config_cache(sobject: Optional[str] = None) -> None:
    """
    Convenience function to invalidate configuration cache.

    Args:
        sobject: Object type to invalidate, or None to invalidate all
    """
    cache = get_config_cache()
    cache.invalidate(sobject)