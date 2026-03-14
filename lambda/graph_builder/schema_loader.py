"""
Schema Loader for Graph Builder.

Loads object schemas from the DynamoDB schema cache for populating
graph node attributes with all filterable fields.

**Feature: zero-config-schema-discovery**
**Requirements: 2.1**
"""
import os
import sys
from typing import Dict, Any, Optional

# Add parent directory to path for schema_discovery imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import schema discovery models and cache
try:
    from schema_discovery.models import ObjectSchema
    from schema_discovery.cache import SchemaCache
    SCHEMA_DISCOVERY_AVAILABLE = True
except ImportError:
    SCHEMA_DISCOVERY_AVAILABLE = False
    ObjectSchema = None
    SchemaCache = None

# Environment variables
SCHEMA_CACHE_TABLE = os.environ.get('SCHEMA_CACHE_TABLE', 'salesforce-ai-search-schema-cache')

# Module-level cache instance (lazy initialized)
_schema_cache: Optional['SchemaCache'] = None
_schema_memory_cache: Dict[str, 'ObjectSchema'] = {}


def get_schema_cache() -> Optional['SchemaCache']:
    """
    Get or create the schema cache instance.
    
    Returns:
        SchemaCache instance or None if schema discovery not available
    """
    global _schema_cache
    
    if not SCHEMA_DISCOVERY_AVAILABLE:
        return None
    
    if _schema_cache is None:
        _schema_cache = SchemaCache(table_name=SCHEMA_CACHE_TABLE)
    
    return _schema_cache


def load_schema(sobject: str, use_memory_cache: bool = True) -> Optional['ObjectSchema']:
    """
    Load schema for an object from the DynamoDB cache.
    
    **Requirements: 2.1**
    
    This function attempts to load the schema from:
    1. In-memory cache (if enabled) for fast repeated access
    2. DynamoDB schema cache
    3. Returns None if not found (caller should fall back to configuration or defaults)
    
    Args:
        sobject: Salesforce object API name (e.g., 'ascendix__Property__c')
        use_memory_cache: Whether to use in-memory caching (default: True)
        
    Returns:
        ObjectSchema if found in cache, None otherwise
    """
    global _schema_memory_cache
    
    # Check in-memory cache first
    if use_memory_cache and sobject in _schema_memory_cache:
        return _schema_memory_cache[sobject]
    
    # Get schema cache instance
    cache = get_schema_cache()
    if cache is None:
        print(f"Schema discovery not available, falling back to defaults for {sobject}")
        return None
    
    try:
        # Load from DynamoDB cache
        schema = cache.get(sobject)
        
        if schema is not None:
            # Store in memory cache for fast repeated access
            if use_memory_cache:
                _schema_memory_cache[sobject] = schema
            print(f"Loaded schema for {sobject} from cache")
            return schema
        else:
            print(f"Schema not found in cache for {sobject}")
            return None
            
    except Exception as e:
        print(f"Error loading schema for {sobject}: {str(e)}")
        return None


def clear_memory_cache(sobject: Optional[str] = None) -> None:
    """
    Clear the in-memory schema cache.
    
    Args:
        sobject: Specific object to clear, or None to clear all
    """
    global _schema_memory_cache
    
    if sobject:
        _schema_memory_cache.pop(sobject, None)
    else:
        _schema_memory_cache.clear()


def is_schema_available(sobject: str) -> bool:
    """
    Check if schema is available for an object.
    
    Args:
        sobject: Salesforce object API name
        
    Returns:
        True if schema is available in cache, False otherwise
    """
    schema = load_schema(sobject)
    return schema is not None


def get_filterable_fields(sobject: str) -> list:
    """
    Get list of filterable field names for an object.
    
    Args:
        sobject: Salesforce object API name
        
    Returns:
        List of filterable field names, empty list if schema not available
    """
    schema = load_schema(sobject)
    if schema is None:
        return []
    return schema.get_all_filterable_field_names()


def get_numeric_fields(sobject: str) -> list:
    """
    Get list of numeric field names for an object.
    
    Args:
        sobject: Salesforce object API name
        
    Returns:
        List of numeric field names, empty list if schema not available
    """
    schema = load_schema(sobject)
    if schema is None:
        return []
    return schema.get_all_numeric_field_names()


def get_date_fields(sobject: str) -> list:
    """
    Get list of date field names for an object.
    
    Args:
        sobject: Salesforce object API name
        
    Returns:
        List of date field names, empty list if schema not available
    """
    schema = load_schema(sobject)
    if schema is None:
        return []
    return schema.get_all_date_field_names()
