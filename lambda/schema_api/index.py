"""
Schema API Lambda Handler.

Lightweight API endpoint for reading schema cache export fields.
Used by Apex (AISearchBatchExport) to get field configuration from Schema Cache
instead of hardcoded IndexConfiguration__mdt.

**Task 34.1: Schema-Driven Export Integration**
"""
import json
import os
import boto3
from typing import Dict, Any, Optional

# Initialize DynamoDB
dynamodb = boto3.resource('dynamodb')
SCHEMA_CACHE_TABLE = os.environ.get('SCHEMA_CACHE_TABLE', 'salesforce-ai-search-schema-cache')
table = dynamodb.Table(SCHEMA_CACHE_TABLE)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    API Gateway Lambda handler for schema cache reads.

    Supports:
    - GET /schema/{objectApiName} - Get export fields for an object
    - GET /schema - List all cached objects

    Returns JSON response suitable for Apex consumption.
    """
    try:
        # Handle API Gateway proxy integration
        http_method = event.get('httpMethod', 'GET')
        path_params = event.get('pathParameters') or {}
        object_api_name = path_params.get('objectApiName')

        # Also support direct Lambda invocation
        if not object_api_name:
            object_api_name = event.get('sobject')

        if http_method == 'GET':
            if object_api_name:
                return get_export_fields(object_api_name)
            else:
                return list_cached_objects()
        else:
            return api_response(405, {'error': f'Method {http_method} not allowed'})

    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        return api_response(500, {'error': str(e)})


def get_export_fields(sobject: str) -> Dict[str, Any]:
    """
    Get export fields for a specific object from schema cache.

    Returns fields in format suitable for AISearchBatchExport:
    - text_fields: Fields for text search/KB
    - filterable_fields: Picklist fields for filtering
    - relationship_fields: Lookup relationships
    - graph_attributes: Fields for graph node attributes
    - has_record_types: Whether to include RecordType.Name
    """
    try:
        response = table.get_item(Key={'objectApiName': sobject})
        item = response.get('Item')

        if not item:
            return api_response(404, {
                'success': False,
                'sobject': sobject,
                'message': f'Schema not found for {sobject}. Run schema discovery first.'
            })

        schema = item.get('schema', {})

        # Extract text fields
        text_fields = []
        for field in schema.get('text', []):
            text_fields.append(field.get('name'))

        # Extract filterable fields and check for RecordTypes
        filterable_fields = []
        has_record_types = False
        for field in schema.get('filterable', []):
            name = field.get('name')
            if name == 'RecordType':
                has_record_types = True
            filterable_fields.append({
                'name': name,
                'label': field.get('label', name),
                'values': field.get('values', [])
            })

        # Extract relationship fields
        relationship_fields = []
        for field in schema.get('relationships', []):
            relationship_fields.append({
                'name': field.get('name'),
                'label': field.get('label', field.get('name')),
                'related_to': field.get('related_to')
            })

        # Build graph attributes from key fields
        graph_attributes = build_graph_attributes(schema)

        return api_response(200, {
            'success': True,
            'sobject': sobject,
            'text_fields': text_fields,
            'filterable_fields': filterable_fields,
            'relationship_fields': relationship_fields,
            'graph_attributes': graph_attributes,
            'has_record_types': has_record_types,
            'discovered_at': schema.get('discovered_at'),
            'field_counts': {
                'text': len(text_fields),
                'filterable': len(filterable_fields),
                'relationships': len(relationship_fields),
                'graph_attributes': len(graph_attributes)
            }
        })

    except Exception as e:
        print(f"Error getting export fields for {sobject}: {str(e)}")
        return api_response(500, {'error': str(e), 'sobject': sobject})


def build_graph_attributes(schema: Dict[str, Any]) -> list:
    """
    Build list of graph node attributes from schema.

    Includes key text fields (City, State, Name) and
    key filterable fields (RecordType, PropertyClass, Status).
    """
    graph_attrs = []
    seen = set()

    # Key text fields for graph filtering
    key_text = ['ascendix__City__c', 'ascendix__State__c', 'Name']
    for field in schema.get('text', []):
        name = field.get('name')
        if name in key_text and name not in seen:
            graph_attrs.append(name)
            seen.add(name)

    # Key filterable fields for graph filtering
    key_filterable = [
        'RecordType', 'ascendix__PropertyClass__c', 'ascendix__BuildingStatus__c',
        'ascendix__UseType__c', 'ascendix__PropertyType__c'
    ]
    for field in schema.get('filterable', []):
        name = field.get('name')
        if name in key_filterable and name not in seen:
            graph_attrs.append(name)
            seen.add(name)
        # Include RecordType.Name specifically
        if name == 'RecordType' and 'RecordType.Name' not in seen:
            graph_attrs.append('RecordType.Name')
            seen.add('RecordType.Name')

    return graph_attrs


def list_cached_objects() -> Dict[str, Any]:
    """
    List all objects in the schema cache.
    """
    try:
        response = table.scan(
            ProjectionExpression='objectApiName, #l, #s.discovered_at, #s.#la',
            ExpressionAttributeNames={
                '#l': 'label',
                '#s': 'schema',
                '#la': 'label'
            }
        )

        objects = []
        for item in response.get('Items', []):
            schema = item.get('schema', {})
            objects.append({
                'objectApiName': item.get('objectApiName'),
                'label': schema.get('label', item.get('label')),
                'discovered_at': schema.get('discovered_at')
            })

        return api_response(200, {
            'success': True,
            'objects': objects,
            'count': len(objects)
        })

    except Exception as e:
        print(f"Error listing cached objects: {str(e)}")
        return api_response(500, {'error': str(e)})


def api_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create API Gateway compatible response.
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(body)
    }
