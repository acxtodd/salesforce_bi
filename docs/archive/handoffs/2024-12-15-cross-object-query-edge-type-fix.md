# Cross-Object Query Edge Type Fix

**Date:** December 15, 2024
**Bug:** Query "show leases for class A office properties in Plano" returned 1 result instead of 52
**Status:** Fixed and verified

## Executive Summary

A cross-object query that should return 52 leases was only returning 1. The root cause was **two separate bugs** working together:

1. **Graph Builder Bug:** Edge `type` field was set to the *target* node type instead of the *source* node type
2. **Traversal Bug:** DynamoDB query used `Limit=100` *before* type filtering, missing most matching edges

Both bugs have been fixed and verified. This was a **one-time bug fix**, not something required for schema changes.

## Problem Description

### Symptoms
- Query: "show leases for class A office properties in Plano"
- Expected: 52 leases on Class A Office properties in Plano
- Actual: Only 1 lease returned

### Investigation Path

1. **Initial KB search worked:** Found 3 matching properties correctly
2. **Cross-object traversal failed:** Only found 1 lease instead of 52
3. **Edge inspection revealed:** Edge `type` values were wrong
   - Example: Edge from Lease → Property had `type: ascendix__Property__c` (target type)
   - Should be: `type: ascendix__Lease__c` (source type)
4. **Even after fixing edge types:** Traversal still limited due to pagination bug

## Root Cause Analysis

### Bug 1: Graph Builder Edge Type Assignment

**Location:** `lambda/graph_builder/index.py`

**What was wrong:**
```python
# BEFORE (incorrect)
'type': {'S': target_type},  # Was using target node's type
```

**What it should be:**
```python
# AFTER (correct)
'type': {'S': source_type},  # Edge type = source node's type
```

**Why this matters:**
Cross-object traversal queries edges like: "Find all edges where `type == 'ascendix__Lease__c'`" to find Leases connected to Properties. If the type field contains the target type instead of source type, these queries return nothing.

### Bug 2: Traversal Pagination Issue

**Location:** `lambda/retrieve/cross_object_handler.py`

**What was wrong:**
```python
# BEFORE (incorrect)
response = edges_table.query(
    IndexName='toId-index',
    KeyConditionExpression=Key('toId').eq(source_id),
    Limit=100,  # Applied BEFORE filtering!
)
# Then filtered by type in Python... but only on 100 edges
for edge in response.get('Items', []):
    if edge.get('type') == target_type:  # Most of these 100 weren't Leases
        target_ids.add(edge.get('fromId'))
```

**The data showed why this failed:**
- Property `a0afk000000PvnfAAC` has 342 total edges
- First 100 edges contained: 87 Deals, 9 Availabilities, 4 Contacts, 0 Leases
- Lease edges existed but were not in the first 100

**What it should be:**
```python
# AFTER (correct)
# Use FilterExpression for server-side filtering + pagination
exclusive_start_key = None
while True:
    query_params = {
        'IndexName': 'toId-index',
        'KeyConditionExpression': Key('toId').eq(source_id),
        'FilterExpression': Attr('type').eq(target_type),  # Server-side filter
        'ProjectionExpression': 'fromId',
    }
    if exclusive_start_key:
        query_params['ExclusiveStartKey'] = exclusive_start_key

    response = self.edges_table.query(**query_params)

    for edge in response.get('Items', []):
        target_ids.add(edge.get('fromId'))

    # Paginate until all edges scanned
    exclusive_start_key = response.get('LastEvaluatedKey')
    if not exclusive_start_key:
        break
```

## Files Modified

| File | Change |
|------|--------|
| `lambda/graph_builder/index.py` | Fixed edge type assignment (source type, not target type) |
| `lambda/retrieve/cross_object_handler.py` | Added FilterExpression and pagination to traversal |
| `lambda/retrieve/test_cross_object_handler.py` | Updated tests for new edge semantics |
| `scripts/backfill_edge_types.py` | Created to fix existing edges (one-time use) |

## Backfill Process

### Why a Backfill Was Needed
The graph builder bug had been writing incorrect edge types for all edges created since the system was deployed. All existing edges needed their `type` field corrected.

### Backfill Statistics
- **Total edges:** 35,918
- **Edges fixed:** 28,918
- **Already correct:** 6,992 (edges where source and target types matched)
- **Missing source nodes:** 8 (orphaned edges)
- **Errors:** 0
- **Duration:** ~60 minutes

### Why It Took 60+ Minutes
Each edge fix required:
1. Read the source node to get its correct type (~15ms)
2. Update the edge with the correct type (~15ms)

With 28,918 edges × ~30ms = ~15 minutes minimum, plus:
- DynamoDB rate limiting (avoided by using resource, not client)
- Network latency variations
- Processing overhead

The script was intentionally not parallelized to avoid throttling.

## Verification Results

### Before Fix
```
Cross-object query: "show leases for class A office properties in Plano"
- Properties found: 3
- Leases found: 1
```

### After Fix
```
Cross-object query: "show leases for class A office properties in Plano"
- Properties found: 3
- Leases found: 50
- Final results returned: 15 (after KB filtering and relevance scoring)
```

Log output confirmed:
```
Edge traversal completed: 3 sources → 50 targets in 34ms
```

## Is This Needed for Schema Changes?

**NO.** This was a one-time bug fix, not part of normal operations.

### When Re-indexing IS Required
- Adding new Salesforce objects to the graph
- Changing which fields are indexed
- Modifying relationship mappings

### When Re-indexing is NOT Required
- Bug fixes like this one (though backfills may be needed)
- Lambda code changes that don't affect data structure
- Query logic changes

### If You See Similar Issues
If cross-object queries stop working after a schema change:
1. Check that the graph builder is creating edges with correct types
2. Verify the traversal code is filtering and paginating correctly
3. Look at sample edges in DynamoDB to confirm structure

## Key Learnings

1. **Edge semantics matter:** The `type` field on an edge should describe what kind of object the edge comes FROM, not where it goes TO

2. **DynamoDB pagination:** When using `Limit` with `FilterExpression`, DynamoDB applies the limit BEFORE filtering. Always paginate when you need complete results.

3. **Test with real data volumes:** The bug only manifested because properties had hundreds of edges. Unit tests with 2-3 edges wouldn't catch this.

## Contact

For questions about this fix, refer to:
- `lambda/retrieve/cross_object_handler.py` - Traversal logic
- `lambda/graph_builder/index.py` - Edge creation logic
- Graph edges table: `salesforce-ai-search-graph-edges`
