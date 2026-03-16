#!/usr/bin/env python3
"""
Local Schema Discovery using SF CLI.
Discovers Salesforce object schemas and writes directly to DynamoDB schema cache.
Now includes RecordType extraction from recordTypeInfos.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
import boto3
from decimal import Decimal

# CRE Objects to discover
CRE_OBJECTS = [
    "ascendix__Property__c",
    "ascendix__Deal__c",
    "ascendix__Availability__c",
    "ascendix__Listing__c",
    "ascendix__Inquiry__c",
    "ascendix__Lease__c",
    "Account",
    "Contact"
]

# Field type constants
PICKLIST_TYPES = {'picklist', 'multipicklist'}
NUMERIC_TYPES = {'double', 'currency', 'int', 'percent'}
DATE_TYPES = {'date', 'datetime'}
TEXT_TYPES = {'string', 'textarea', 'email', 'phone', 'url'}

# DynamoDB client
dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
table = dynamodb.Table('salesforce-ai-search-schema-cache')

def describe_object(sobject: str) -> dict:
    """Call sf sobject describe for an object."""
    cmd = [
        'sf', 'sobject', 'describe',
        '--sobject', sobject,
        '--target-org', 'ascendix-beta-sandbox',
        '--json'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error describing {sobject}: {result.stderr}")
        return None
    return json.loads(result.stdout).get('result', {})

def classify_field_type(sf_field: dict) -> str:
    """Classify a Salesforce field into a schema category."""
    sf_type = sf_field.get('type', '').lower()

    if sf_type in PICKLIST_TYPES:
        return 'filterable'
    if sf_type in NUMERIC_TYPES:
        return 'numeric'
    if sf_type in DATE_TYPES:
        return 'date'
    if sf_type == 'reference':
        if sf_field.get('referenceTo'):
            return 'relationship'
    if sf_type in TEXT_TYPES:
        return 'text'
    return 'text'

def extract_picklist_values(sf_field: dict) -> list:
    """Extract active picklist values from field definition."""
    values = []
    for pv in sf_field.get('picklistValues', []):
        if pv.get('active', False):
            value = pv.get('value', '')
            if value:
                values.append(value)
    return values

def extract_record_types(describe: dict) -> dict:
    """Extract RecordType as a synthetic filterable field from recordTypeInfos."""
    record_type_infos = describe.get('recordTypeInfos', [])
    if not record_type_infos:
        return None

    # Extract active record type names (excluding Master)
    values = []
    for rt in record_type_infos:
        if rt.get('active', False) and rt.get('available', True):
            name = rt.get('name', '')
            if name and name != 'Master':  # Exclude Master record type
                values.append(name)

    if not values:
        return None

    return {
        'name': 'RecordType',
        'label': 'Record Type',
        'type': 'filterable',
        'sf_type': 'recordType',  # synthetic type for traceability
        'values': values
    }

def build_field_schema(sf_field: dict) -> dict:
    """Build a field schema dict from SF field definition."""
    name = sf_field.get('name', '')
    label = sf_field.get('label', name)
    sf_type = sf_field.get('type', '')
    field_type = classify_field_type(sf_field)

    # Skip system fields
    if name in ('Id', 'IsDeleted', 'SystemModstamp'):
        return None

    result = {
        'name': name,
        'label': label,
        'type': field_type,
        'sf_type': sf_type
    }

    if field_type == 'filterable':
        result['values'] = extract_picklist_values(sf_field)
    elif field_type == 'relationship':
        ref_to = sf_field.get('referenceTo', [])
        if ref_to:
            result['reference_to'] = ref_to[0]

    return result

def discover_object(sobject: str) -> dict:
    """Discover complete schema for an object."""
    print(f"Discovering {sobject}...")
    describe = describe_object(sobject)
    if not describe:
        return None

    api_name = describe.get('name', sobject)
    label = describe.get('label', sobject)

    filterable = []
    numeric = []
    date = []
    relationships = []
    text = []

    # First, add RecordType if available
    record_type_field = extract_record_types(describe)
    if record_type_field:
        filterable.append(record_type_field)
        print(f"  Added RecordType with {len(record_type_field['values'])} values: {record_type_field['values'][:5]}...")

    for sf_field in describe.get('fields', []):
        field_schema = build_field_schema(sf_field)
        if not field_schema:
            continue

        field_type = field_schema['type']
        if field_type == 'filterable':
            filterable.append(field_schema)
        elif field_type == 'numeric':
            numeric.append(field_schema)
        elif field_type == 'date':
            date.append(field_schema)
        elif field_type == 'relationship':
            relationships.append(field_schema)
        elif field_type == 'text':
            text.append(field_schema)

    schema = {
        'api_name': api_name,
        'label': label,
        'filterable': filterable,
        'numeric': numeric,
        'date': date,
        'relationships': relationships,
        'text': text,
        'discovered_at': datetime.now(timezone.utc).isoformat()
    }

    print(f"  {len(filterable)} filterable, {len(numeric)} numeric, "
          f"{len(date)} date, {len(relationships)} relationships, {len(text)} text")

    return schema

def write_to_cache(sobject: str, schema: dict, ttl_hours: int = 168):
    """Write schema to DynamoDB cache (default 7 day TTL)."""
    ttl_timestamp = int(
        (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).timestamp()
    )

    item = {
        'objectApiName': sobject,
        'schema': schema,
        'discoveredAt': schema['discovered_at'],
        'ttl': ttl_timestamp
    }

    table.put_item(Item=item)
    print(f"  Cached {sobject} (TTL: {ttl_hours}h)")

def main():
    """Discover all CRE objects and cache in DynamoDB."""
    print("=" * 60)
    print("Local Schema Discovery - Using SF CLI")
    print("With RecordType extraction from recordTypeInfos")
    print("=" * 60)

    success = 0
    errors = []

    for sobject in CRE_OBJECTS:
        try:
            schema = discover_object(sobject)
            if schema:
                write_to_cache(sobject, schema)
                success += 1
            else:
                errors.append(f"{sobject}: No schema returned")
        except Exception as e:
            errors.append(f"{sobject}: {str(e)}")
            print(f"  ERROR: {e}")

    print()
    print("=" * 60)
    print(f"SUMMARY: {success}/{len(CRE_OBJECTS)} objects discovered and cached")
    print("=" * 60)

    if errors:
        print("\nErrors:")
        for err in errors:
            print(f"  - {err}")

    return 0 if success == len(CRE_OBJECTS) else 1

if __name__ == '__main__':
    sys.exit(main())
