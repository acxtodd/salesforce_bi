"""
Schema Discovery Lambda Handler.

Discovers Salesforce object schemas using the Describe API and caches them
in DynamoDB for fast query-time lookup.

**Feature: zero-config-schema-discovery**
**Requirements: 1.1, 1.6**
"""
import json
import os
import traceback
from typing import Dict, Any, List, Optional

from models import ObjectSchema
from discoverer import SchemaDiscoverer, CRE_OBJECTS
from cache import SchemaCache


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for schema discovery.
    
    **Requirements: 1.1, 1.6**
    
    Supported operations:
    1. discover_all - Discover and cache schema for all CRE objects
    2. discover_object - Discover and cache schema for a specific object
    3. get_schema - Get cached schema for an object
    4. invalidate_cache - Invalidate cached schema
    
    Event format:
    {
        "operation": "discover_all" | "discover_object" | "get_schema" | "invalidate_cache",
        "sobject": "ascendix__Property__c",  // Required for discover_object, get_schema
        "objects": ["Account", "Contact"],   // Optional for discover_all
        "ttl_hours": 24                       // Optional TTL override
    }
    
    Returns:
    {
        "statusCode": 200,
        "body": {
            "success": true,
            "schemas": {...},
            "message": "..."
        }
    }
    """
    try:
        operation = event.get('operation', 'discover_all')
        sobject = event.get('sobject')
        objects = event.get('objects')
        ttl_hours = event.get('ttl_hours', 24)
        
        print(f"Schema Discovery: operation={operation}, sobject={sobject}")
        
        # Initialize components
        cache = SchemaCache()
        
        if operation == 'discover_all':
            return _handle_discover_all(cache, objects, ttl_hours)
        
        elif operation == 'discover_object':
            if not sobject:
                return _error_response(400, "sobject is required for discover_object")
            return _handle_discover_object(cache, sobject, ttl_hours)
        
        elif operation == 'get_schema':
            if not sobject:
                return _error_response(400, "sobject is required for get_schema")
            return _handle_get_schema(cache, sobject)
        
        elif operation == 'invalidate_cache':
            return _handle_invalidate_cache(cache, sobject)
        
        else:
            return _error_response(400, f"Unknown operation: {operation}")
    
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        traceback.print_exc()
        return _error_response(500, str(e))


def _handle_discover_all(
    cache: SchemaCache,
    objects: Optional[List[str]],
    ttl_hours: int
) -> Dict[str, Any]:
    """
    Discover and cache schema for all CRE objects.
    
    **Requirements: 1.1, 1.6**
    """
    discoverer = SchemaDiscoverer()
    objects_to_discover = objects or CRE_OBJECTS
    
    schemas = discoverer.discover_all(objects_to_discover)
    
    # Cache all discovered schemas
    cached_count = 0
    for sobject, schema in schemas.items():
        if cache.put(sobject, schema, ttl_hours):
            cached_count += 1
    
    # Build summary
    summary = {}
    for sobject, schema in schemas.items():
        summary[sobject] = {
            'filterable_count': len(schema.filterable),
            'numeric_count': len(schema.numeric),
            'date_count': len(schema.date),
            'relationship_count': len(schema.relationships),
            'text_count': len(schema.text),
        }
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'success': True,
            'discovered_count': len(schemas),
            'cached_count': cached_count,
            'total_objects': len(objects_to_discover),
            'summary': summary,
            'message': f"Discovered {len(schemas)}/{len(objects_to_discover)} objects"
        })
    }


def _handle_discover_object(
    cache: SchemaCache,
    sobject: str,
    ttl_hours: int
) -> Dict[str, Any]:
    """
    Discover and cache schema for a specific object.
    
    **Requirements: 1.1, 1.6**
    """
    discoverer = SchemaDiscoverer()
    
    try:
        schema = discoverer.discover_object(sobject)
        
        # Cache the schema
        cached = cache.put(sobject, schema, ttl_hours)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'sobject': sobject,
                'cached': cached,
                'schema': schema.to_dict(),
                'summary': {
                    'filterable_count': len(schema.filterable),
                    'numeric_count': len(schema.numeric),
                    'date_count': len(schema.date),
                    'relationship_count': len(schema.relationships),
                    'text_count': len(schema.text),
                }
            })
        }
    except Exception as e:
        return _error_response(500, f"Failed to discover {sobject}: {str(e)}")


def _handle_get_schema(cache: SchemaCache, sobject: str) -> Dict[str, Any]:
    """
    Get cached schema for an object.
    
    **Requirements: 1.6, 1.7**
    """
    schema = cache.get(sobject)
    
    if schema is None:
        return {
            'statusCode': 404,
            'body': json.dumps({
                'success': False,
                'sobject': sobject,
                'message': f"Schema not found in cache for {sobject}"
            })
        }
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'success': True,
            'sobject': sobject,
            'schema': schema.to_dict(),
            'cached': True
        })
    }


def _handle_invalidate_cache(
    cache: SchemaCache,
    sobject: Optional[str]
) -> Dict[str, Any]:
    """
    Invalidate cached schema.
    """
    success = cache.invalidate(sobject)
    
    message = f"Cache invalidated for {sobject}" if sobject else "All cache invalidated"
    
    return {
        'statusCode': 200 if success else 500,
        'body': json.dumps({
            'success': success,
            'message': message
        })
    }


def _error_response(status_code: int, message: str) -> Dict[str, Any]:
    """Create error response."""
    return {
        'statusCode': status_code,
        'body': json.dumps({
            'success': False,
            'error': message
        })
    }


# Convenience function for direct invocation
def discover_all(objects: Optional[List[str]] = None) -> Dict[str, ObjectSchema]:
    """
    Discover all CRE object schemas.
    
    **Requirements: 1.1**
    
    Args:
        objects: Optional list of object API names to discover
        
    Returns:
        Dictionary mapping object API name to ObjectSchema
    """
    discoverer = SchemaDiscoverer()
    return discoverer.discover_all(objects)
