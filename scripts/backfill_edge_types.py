#!/usr/bin/env python3
"""
Backfill script to fix edge type field in graph-edges table.

The edge.type should match the type of the edge.fromId node (source node),
NOT the type of the edge.toId node. This allows traversal to find edges
by matching type == target_type.

Bug: graph_builder was setting type to the target node type instead of source.
Fix: This script updates all edges with the correct fromId node type.

Usage:
    python3 scripts/backfill_edge_types.py --dry-run    # Preview changes
    python3 scripts/backfill_edge_types.py              # Apply changes
"""

import argparse
import boto3
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed


REGION = 'us-west-2'
NODES_TABLE = 'salesforce-ai-search-graph-nodes'
EDGES_TABLE = 'salesforce-ai-search-graph-edges'


def get_node_types(dynamodb, node_ids: set) -> dict:
    """Batch get node types for a set of node IDs."""
    if not node_ids:
        return {}

    node_types = {}
    node_id_list = list(node_ids)

    # DynamoDB batch_get_item supports max 100 items per call
    for i in range(0, len(node_id_list), 100):
        batch = node_id_list[i:i+100]
        response = dynamodb.batch_get_item(
            RequestItems={
                NODES_TABLE: {
                    'Keys': [{'nodeId': {'S': nid}} for nid in batch],
                    'ProjectionExpression': 'nodeId, #t',
                    'ExpressionAttributeNames': {'#t': 'type'}
                }
            }
        )

        for item in response.get('Responses', {}).get(NODES_TABLE, []):
            node_id = item['nodeId']['S']
            node_type = item.get('type', {}).get('S', 'Unknown')
            node_types[node_id] = node_type

    return node_types


def scan_all_edges(dynamodb):
    """Scan all edges from the table."""
    edges = []
    paginator = dynamodb.get_paginator('scan')

    for page in paginator.paginate(TableName=EDGES_TABLE):
        for item in page.get('Items', []):
            edges.append({
                'fromId': item['fromId']['S'],
                'toIdType': item['toIdType']['S'],
                'toId': item['toId']['S'],
                'type': item.get('type', {}).get('S', ''),
                'fieldName': item.get('fieldName', {}).get('S', ''),
                'direction': item.get('direction', {}).get('S', ''),
                'createdAt': item.get('createdAt', {}).get('S', ''),
            })

    return edges


def fix_edge_types(dry_run=True):
    """Main function to fix edge types."""
    dynamodb = boto3.client('dynamodb', region_name=REGION)
    dynamodb_resource = boto3.resource('dynamodb', region_name=REGION)
    edges_table = dynamodb_resource.Table(EDGES_TABLE)

    print(f"Scanning edges table: {EDGES_TABLE}")
    edges = scan_all_edges(dynamodb)
    print(f"Found {len(edges)} edges")

    # Collect all unique fromIds
    from_ids = set(edge['fromId'] for edge in edges)
    print(f"Found {len(from_ids)} unique source nodes (fromIds)")

    # Get node types for all fromIds
    print("Fetching node types...")
    node_types = get_node_types(dynamodb, from_ids)
    print(f"Retrieved types for {len(node_types)} nodes")

    # Find edges with incorrect types
    edges_to_fix = []
    stats = defaultdict(int)

    for edge in edges:
        from_id = edge['fromId']
        current_type = edge['type']

        # Get the correct type from the fromId node
        correct_type = node_types.get(from_id)

        if correct_type is None:
            stats['missing_node'] += 1
            continue

        if current_type != correct_type:
            edges_to_fix.append({
                'fromId': from_id,
                'toIdType': edge['toIdType'],
                'toId': edge['toId'],
                'current_type': current_type,
                'correct_type': correct_type,
                'fieldName': edge['fieldName'],
                'direction': edge['direction'],
                'createdAt': edge['createdAt'],
            })
            stats[f'{current_type} -> {correct_type}'] += 1
        else:
            stats['already_correct'] += 1

    print(f"\n=== Statistics ===")
    print(f"Total edges: {len(edges)}")
    print(f"Already correct: {stats['already_correct']}")
    print(f"Missing source node: {stats['missing_node']}")
    print(f"Edges to fix: {len(edges_to_fix)}")

    print(f"\n=== Type changes ===")
    for key, count in sorted(stats.items()):
        if '->' in key:
            print(f"  {key}: {count}")

    if not edges_to_fix:
        print("\nNo edges need fixing!")
        return

    print(f"\n=== Sample fixes (first 10) ===")
    for edge in edges_to_fix[:10]:
        print(f"  {edge['fromId']} -> {edge['toId']}: {edge['current_type']} -> {edge['correct_type']}")

    if dry_run:
        print(f"\n[DRY RUN] Would update {len(edges_to_fix)} edges")
        print("Run without --dry-run to apply changes")
        return

    # Apply fixes
    print(f"\n=== Applying fixes ===")
    fixed_count = 0
    error_count = 0

    for edge in edges_to_fix:
        try:
            # Need to delete old item and create new one because toIdType (sort key) includes type
            # Delete old edge
            edges_table.delete_item(
                Key={
                    'fromId': edge['fromId'],
                    'toIdType': edge['toIdType']
                }
            )

            # Create new edge with correct type
            new_to_id_type = f"{edge['toId']}#{edge['correct_type']}"
            edges_table.put_item(
                Item={
                    'fromId': edge['fromId'],
                    'toIdType': new_to_id_type,
                    'toId': edge['toId'],
                    'type': edge['correct_type'],
                    'fieldName': edge['fieldName'],
                    'direction': edge['direction'],
                    'createdAt': edge['createdAt'],
                }
            )

            fixed_count += 1
            if fixed_count % 100 == 0:
                print(f"  Fixed {fixed_count}/{len(edges_to_fix)} edges...")

        except Exception as e:
            error_count += 1
            print(f"  Error fixing edge {edge['fromId']} -> {edge['toId']}: {e}")

    print(f"\n=== Complete ===")
    print(f"Fixed: {fixed_count}")
    print(f"Errors: {error_count}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Backfill edge types in graph-edges table')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without applying')
    args = parser.parse_args()

    fix_edge_types(dry_run=args.dry_run)
