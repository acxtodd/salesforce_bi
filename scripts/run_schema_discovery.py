#!/usr/bin/env python3
"""
Script to invoke the Schema Discovery Lambda and verify results.

**Feature: zero-config-schema-discovery**
**Requirements: 1.1, 1.2**

Usage:
    python scripts/run_schema_discovery.py [--profile PROFILE] [--region REGION]
    
This script:
1. Invokes the schema discovery Lambda for all CRE objects
2. Verifies all 8 objects were discovered successfully
3. Verifies picklist values were extracted
4. Prints a summary of discovered schemas
"""
import argparse
import json
import sys
import boto3
from botocore.exceptions import ClientError

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

LAMBDA_FUNCTION_NAME = "salesforce-ai-search-schema-discovery"


def invoke_schema_discovery(lambda_client, operation: str = "discover_all", objects: list = None):
    """
    Invoke the schema discovery Lambda.
    
    Args:
        lambda_client: Boto3 Lambda client
        operation: Operation to perform (discover_all, discover_object, get_schema)
        objects: Optional list of objects to discover
        
    Returns:
        Response from Lambda
    """
    payload = {
        "operation": operation,
    }
    
    if objects:
        payload["objects"] = objects
    
    try:
        response = lambda_client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload)
        )
        
        # Parse response
        response_payload = json.loads(response["Payload"].read().decode("utf-8"))
        
        if response.get("FunctionError"):
            print(f"Lambda error: {response_payload}")
            return None
            
        return response_payload
        
    except ClientError as e:
        print(f"Error invoking Lambda: {e}")
        return None


def verify_schema_discovery(dynamodb_client, table_name: str = "salesforce-ai-search-schema-cache"):
    """
    Verify schemas were cached in DynamoDB.
    
    Args:
        dynamodb_client: Boto3 DynamoDB client
        table_name: Schema cache table name
        
    Returns:
        Dictionary of discovered schemas
    """
    schemas = {}
    
    try:
        # Scan the table to get all cached schemas
        response = dynamodb_client.scan(TableName=table_name)
        items = response.get("Items", [])
        
        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = dynamodb_client.scan(
                TableName=table_name,
                ExclusiveStartKey=response["LastEvaluatedKey"]
            )
            items.extend(response.get("Items", []))
        
        for item in items:
            object_name = item.get("objectApiName", {}).get("S", "")
            schema_data = item.get("schema", {}).get("M", {})
            
            if object_name:
                schemas[object_name] = schema_data
                
        return schemas
        
    except ClientError as e:
        print(f"Error reading from DynamoDB: {e}")
        return {}


def print_schema_summary(schemas: dict):
    """Print a summary of discovered schemas."""
    print("\n" + "=" * 60)
    print("SCHEMA DISCOVERY SUMMARY")
    print("=" * 60)
    
    for object_name in CRE_OBJECTS:
        if object_name in schemas:
            schema = schemas[object_name]
            
            # Count fields by type
            filterable = schema.get("filterable", {}).get("L", [])
            numeric = schema.get("numeric", {}).get("L", [])
            date = schema.get("date", {}).get("L", [])
            relationships = schema.get("relationships", {}).get("L", [])
            text = schema.get("text", {}).get("L", [])
            
            print(f"\n{object_name}:")
            print(f"  Filterable fields: {len(filterable)}")
            print(f"  Numeric fields: {len(numeric)}")
            print(f"  Date fields: {len(date)}")
            print(f"  Relationship fields: {len(relationships)}")
            print(f"  Text fields: {len(text)}")
            
            # Show sample picklist values
            if filterable:
                print("  Sample picklist fields:")
                for field in filterable[:3]:
                    field_data = field.get("M", {})
                    field_name = field_data.get("name", {}).get("S", "")
                    values = field_data.get("values", {}).get("L", [])
                    value_count = len(values)
                    print(f"    - {field_name}: {value_count} values")
        else:
            print(f"\n{object_name}: NOT FOUND")
    
    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Run schema discovery for CRE objects")
    parser.add_argument("--profile", default=None, help="AWS profile to use")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing schemas")
    args = parser.parse_args()
    
    # Create boto3 session
    session_kwargs = {"region_name": args.region}
    if args.profile:
        session_kwargs["profile_name"] = args.profile
    
    session = boto3.Session(**session_kwargs)
    lambda_client = session.client("lambda")
    dynamodb_client = session.client("dynamodb")
    
    if not args.verify_only:
        print("Invoking schema discovery Lambda...")
        print(f"Objects to discover: {CRE_OBJECTS}")
        
        # Invoke schema discovery
        response = invoke_schema_discovery(lambda_client, "discover_all", CRE_OBJECTS)
        
        if response:
            # Parse the body if it's a string
            body = response.get("body")
            if isinstance(body, str):
                body = json.loads(body)
            
            status_code = response.get("statusCode", 0)
            
            if status_code == 200:
                print(f"\nSchema discovery completed successfully!")
                print(f"  Discovered: {body.get('discovered_count', 0)}/{body.get('total_objects', 0)} objects")
                print(f"  Cached: {body.get('cached_count', 0)} objects")
                
                # Print summary from response
                summary = body.get("summary", {})
                for obj_name, obj_summary in summary.items():
                    print(f"\n  {obj_name}:")
                    print(f"    Filterable: {obj_summary.get('filterable_count', 0)}")
                    print(f"    Numeric: {obj_summary.get('numeric_count', 0)}")
                    print(f"    Date: {obj_summary.get('date_count', 0)}")
                    print(f"    Relationships: {obj_summary.get('relationship_count', 0)}")
            else:
                print(f"\nSchema discovery failed with status {status_code}")
                print(f"Error: {body.get('error', 'Unknown error')}")
                sys.exit(1)
        else:
            print("\nFailed to invoke schema discovery Lambda")
            sys.exit(1)
    
    # Verify schemas in DynamoDB
    print("\nVerifying schemas in DynamoDB...")
    schemas = verify_schema_discovery(dynamodb_client)
    
    # Check all CRE objects were discovered
    missing = [obj for obj in CRE_OBJECTS if obj not in schemas]
    
    if missing:
        print(f"\nWARNING: Missing schemas for: {missing}")
    else:
        print(f"\nAll {len(CRE_OBJECTS)} CRE objects discovered successfully!")
    
    # Print detailed summary
    print_schema_summary(schemas)
    
    # Verify picklist values were extracted
    print("\nVerifying picklist values extraction...")
    objects_with_picklists = 0
    total_picklist_values = 0
    
    for object_name, schema in schemas.items():
        filterable = schema.get("filterable", {}).get("L", [])
        if filterable:
            objects_with_picklists += 1
            for field in filterable:
                values = field.get("M", {}).get("values", {}).get("L", [])
                total_picklist_values += len(values)
    
    print(f"  Objects with picklist fields: {objects_with_picklists}")
    print(f"  Total picklist values extracted: {total_picklist_values}")
    
    if total_picklist_values > 0:
        print("\n✓ Picklist values extraction verified!")
    else:
        print("\n⚠ No picklist values found - this may indicate an issue")
    
    # Final status
    if not missing and total_picklist_values > 0:
        print("\n" + "=" * 60)
        print("SCHEMA DISCOVERY VERIFICATION: PASSED")
        print("=" * 60)
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print("SCHEMA DISCOVERY VERIFICATION: NEEDS ATTENTION")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
