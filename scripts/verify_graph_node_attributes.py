#!/usr/bin/env python3
"""
Script to verify graph node attributes after re-indexing.

**Feature: zero-config-schema-discovery**
**Requirements: 2.2, 2.3, 2.4**

This script:
1. Queries DynamoDB for sample Property nodes
2. Verifies attributes include PropertyClass, PropertySubType, City, etc.
3. Verifies numeric values are stored as numbers
4. Verifies date values are in ISO 8601 format

Usage:
    python scripts/verify_graph_node_attributes.py [--profile PROFILE] [--region REGION]
"""
import argparse
import json
import sys
import re
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
from decimal import Decimal

GRAPH_NODES_TABLE = "salesforce-ai-search-graph-nodes"

# Expected filterable attributes for Property objects
EXPECTED_FILTERABLE_ATTRS = [
    "ascendix__PropertyClass__c",
    "ascendix__PropertySubType__c",
    "ascendix__City__c",
    "ascendix__State__c",
    "ascendix__BuildingStatus__c",
]

# Expected numeric attributes
EXPECTED_NUMERIC_ATTRS = [
    "ascendix__TotalBuildingArea__c",
    "ascendix__YearBuilt__c",
]

# Expected date attributes
EXPECTED_DATE_ATTRS = [
    "LastActivityDate",
    "CreatedDate",
    "LastModifiedDate",
]

# ISO 8601 date pattern
ISO_8601_PATTERN = re.compile(
    r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?)?$'
)


def query_property_nodes(dynamodb_client, limit: int = 10):
    """
    Query Property nodes from the graph nodes table.
    
    Args:
        dynamodb_client: Boto3 DynamoDB client
        limit: Maximum number of nodes to retrieve
        
    Returns:
        List of Property node items
    """
    try:
        # Query using the type-createdAt GSI
        response = dynamodb_client.query(
            TableName=GRAPH_NODES_TABLE,
            IndexName="type-createdAt-index",
            KeyConditionExpression="#type = :type",
            ExpressionAttributeNames={"#type": "type"},
            ExpressionAttributeValues={":type": {"S": "ascendix__Property__c"}},
            Limit=limit,
            ScanIndexForward=False  # Most recent first
        )
        
        return response.get("Items", [])
        
    except ClientError as e:
        print(f"Error querying DynamoDB: {e}")
        return []


def deserialize_dynamodb_item(item: dict) -> dict:
    """Convert DynamoDB item to Python dict."""
    result = {}
    for key, value in item.items():
        if "S" in value:
            result[key] = value["S"]
        elif "N" in value:
            result[key] = float(value["N"]) if "." in value["N"] else int(value["N"])
        elif "BOOL" in value:
            result[key] = value["BOOL"]
        elif "M" in value:
            result[key] = deserialize_dynamodb_item(value["M"])
        elif "L" in value:
            result[key] = [deserialize_dynamodb_item({"v": v})["v"] if "M" in v else 
                          v.get("S") or v.get("N") or v.get("BOOL") 
                          for v in value["L"]]
        elif "NULL" in value:
            result[key] = None
    return result


def verify_filterable_attributes(attributes: dict) -> dict:
    """
    Verify filterable attributes are present and are strings.
    
    Returns:
        Dict with verification results
    """
    results = {
        "found": [],
        "missing": [],
        "type_errors": []
    }
    
    for attr in EXPECTED_FILTERABLE_ATTRS:
        if attr in attributes:
            value = attributes[attr]
            if isinstance(value, str):
                results["found"].append(attr)
            else:
                results["type_errors"].append(f"{attr}: expected string, got {type(value).__name__}")
        else:
            results["missing"].append(attr)
    
    return results


def verify_numeric_attributes(attributes: dict) -> dict:
    """
    Verify numeric attributes are stored as numbers.
    
    **Requirements: 2.3**
    
    Returns:
        Dict with verification results
    """
    results = {
        "found": [],
        "missing": [],
        "type_errors": []
    }
    
    for attr in EXPECTED_NUMERIC_ATTRS:
        if attr in attributes:
            value = attributes[attr]
            if isinstance(value, (int, float, Decimal)):
                results["found"].append(f"{attr}={value}")
            else:
                results["type_errors"].append(f"{attr}: expected number, got {type(value).__name__} ({value})")
        else:
            results["missing"].append(attr)
    
    return results


def verify_date_attributes(attributes: dict) -> dict:
    """
    Verify date attributes are in ISO 8601 format.
    
    **Requirements: 2.4**
    
    Returns:
        Dict with verification results
    """
    results = {
        "found": [],
        "missing": [],
        "format_errors": []
    }
    
    for attr in EXPECTED_DATE_ATTRS:
        if attr in attributes:
            value = attributes[attr]
            if isinstance(value, str) and ISO_8601_PATTERN.match(value):
                results["found"].append(f"{attr}={value}")
            else:
                results["format_errors"].append(f"{attr}: not ISO 8601 format ({value})")
        else:
            results["missing"].append(attr)
    
    return results


def print_node_summary(node: dict, index: int):
    """Print summary of a single node."""
    print(f"\n--- Node {index + 1} ---")
    print(f"  ID: {node.get('nodeId', 'N/A')}")
    print(f"  Type: {node.get('type', 'N/A')}")
    print(f"  Display Name: {node.get('displayName', 'N/A')}")
    
    attributes = node.get("attributes", {})
    print(f"  Attributes ({len(attributes)} total):")
    
    for key, value in sorted(attributes.items()):
        value_type = type(value).__name__
        if isinstance(value, str) and len(value) > 50:
            value = value[:50] + "..."
        print(f"    {key}: {value} ({value_type})")


def main():
    parser = argparse.ArgumentParser(description="Verify graph node attributes after re-indexing")
    parser.add_argument("--profile", default=None, help="AWS profile to use")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--limit", type=int, default=5, help="Number of nodes to check")
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    args = parser.parse_args()
    
    # Create boto3 session
    session_kwargs = {"region_name": args.region}
    if args.profile:
        session_kwargs["profile_name"] = args.profile
    
    session = boto3.Session(**session_kwargs)
    dynamodb_client = session.client("dynamodb")
    
    print("=" * 60)
    print("GRAPH NODE ATTRIBUTE VERIFICATION")
    print("=" * 60)
    print(f"\nQuerying {args.limit} Property nodes from {GRAPH_NODES_TABLE}...")
    
    # Query Property nodes
    items = query_property_nodes(dynamodb_client, args.limit)
    
    if not items:
        print("\nNo Property nodes found in the graph nodes table.")
        print("Make sure to run the re-indexing process first.")
        sys.exit(1)
    
    print(f"Found {len(items)} Property nodes")
    
    # Aggregate verification results
    total_filterable_found = 0
    total_filterable_missing = 0
    total_numeric_found = 0
    total_numeric_errors = 0
    total_date_found = 0
    total_date_errors = 0
    
    for i, item in enumerate(items):
        node = deserialize_dynamodb_item(item)
        attributes = node.get("attributes", {})
        
        if args.verbose:
            print_node_summary(node, i)
        
        # Verify filterable attributes
        filterable_results = verify_filterable_attributes(attributes)
        total_filterable_found += len(filterable_results["found"])
        total_filterable_missing += len(filterable_results["missing"])
        
        # Verify numeric attributes
        numeric_results = verify_numeric_attributes(attributes)
        total_numeric_found += len(numeric_results["found"])
        total_numeric_errors += len(numeric_results["type_errors"])
        
        # Verify date attributes
        date_results = verify_date_attributes(attributes)
        total_date_found += len(date_results["found"])
        total_date_errors += len(date_results["format_errors"])
        
        if args.verbose:
            if filterable_results["type_errors"]:
                print(f"  Filterable type errors: {filterable_results['type_errors']}")
            if numeric_results["type_errors"]:
                print(f"  Numeric type errors: {numeric_results['type_errors']}")
            if date_results["format_errors"]:
                print(f"  Date format errors: {date_results['format_errors']}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    
    print(f"\nFilterable Attributes (Requirements 2.2):")
    print(f"  Found: {total_filterable_found}/{len(items) * len(EXPECTED_FILTERABLE_ATTRS)}")
    print(f"  Expected fields: {EXPECTED_FILTERABLE_ATTRS}")
    
    print(f"\nNumeric Attributes (Requirements 2.3):")
    print(f"  Found as numbers: {total_numeric_found}/{len(items) * len(EXPECTED_NUMERIC_ATTRS)}")
    print(f"  Type errors: {total_numeric_errors}")
    print(f"  Expected fields: {EXPECTED_NUMERIC_ATTRS}")
    
    print(f"\nDate Attributes (Requirements 2.4):")
    print(f"  Found in ISO 8601: {total_date_found}/{len(items) * len(EXPECTED_DATE_ATTRS)}")
    print(f"  Format errors: {total_date_errors}")
    print(f"  Expected fields: {EXPECTED_DATE_ATTRS}")
    
    # Determine overall status
    all_passed = (
        total_numeric_errors == 0 and
        total_date_errors == 0 and
        total_filterable_found > 0
    )
    
    print("\n" + "=" * 60)
    if all_passed:
        print("VERIFICATION: PASSED")
        print("Graph nodes have schema-driven attributes with correct types!")
    else:
        print("VERIFICATION: NEEDS ATTENTION")
        if total_numeric_errors > 0:
            print("- Some numeric fields are not stored as numbers")
        if total_date_errors > 0:
            print("- Some date fields are not in ISO 8601 format")
        if total_filterable_found == 0:
            print("- No filterable attributes found")
    print("=" * 60)
    
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
