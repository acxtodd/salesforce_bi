# Graph Traversal Issue - Preston Park Deals Not Showing

**Date**: November 27, 2025
**Status**: FIXES DEPLOYED - AWAITING VERIFICATION
**Priority**: High
**Last Updated**: November 27, 2025

## Problem Statement

Query: "What active deals are associated with office properties in Plano?"

**Expected**: Should return multiple deals linked to Preston Park Financial Center (and other Plano properties)

**Actual**: Only returns 1 deal (Dallas Office Investors), even though:
- Graph traversal finds 179 related nodes
- Lambda returns 18 matches (8 vector + 10 graph-discovered)
- Multiple deals exist in the graph linked to Preston Park Financial Center property

## Known Data

### Preston Park Financial Center
- **Property ID**: `a0afk000000PvnfAAC`
- **Location**: Plano, TX
- **Type**: Class A office space

### Known Deals Linked to Preston Park
From DynamoDB graph edges, there are **273 deals** connected to this property, including:
- `a0Pfk000000CkdBEAS` - "Lease Listing for Preston Park Financial Center"
- `a0Pfk000000Ch7SEAS` - "Sale Listing for PPFC 2020" (Status: Open)
- `a0Pfk000000CkmAEAS`
- `a0Pfk000000CkmjEAC`
- Many more...

### Sample Deal Content (from S3)
```
# Sale Listing for PPFC 2020
Name: Sale Listing for PPFC 2020
Status: Open
Sales Stage: In the Market/Tracking
Client Role: Owner/Landlord
Deal Number: 25-4277
Deal Age: OLDER (185 days)
Property ID: a0afk000000PvnfAAC
```

## Technical Flow

### 1. Vector Search (Working ✓)
- Returns 8 properties in Plano including AMLI West Plano, Plano Office Condo
- Extracts record IDs: `a0afk000000PvG5AAK`, etc.

### 2. Graph Traversal (Working ✓)
- Uses 8 seed record IDs from vector search
- Finds 8 seed nodes in graph
- Traverses to depth 2
- Finds **179 related nodes** via graph edges
- Cache hit: True

### 3. Graph Merge (Partially Working ⚠️)
- Boosts 13 existing vector matches
- Adds 10 graph-discovered nodes
- Total: 18 matches returned

### 4. LLM Response (Issue ❌)
- Only shows 1 deal in answer
- Shows "View Citations (4)" - only 4 citations passed to LLM
- Mentions Preston Park Financial Center in note but doesn't list its deals

## Root Cause Analysis

### Issue 1: Graph-Discovered Nodes Have Minimal Content
The graph-discovered deals are being added to results but may not have rich enough content for the LLM to use them.

**Current Implementation**:
```python
# Tries to fetch S3 chunk content
chunk_key = f"chunks/{node_type}/{node_id}/chunk-0.txt"
chunk_response = s3_client.get_object(Bucket=data_bucket, Key=chunk_key)
```

**Potential Problem**: Lambda is in VPC and S3 fetch may be failing silently, falling back to minimal text like:
```
Record: Sale Listing for PPFC 2020
Type: ascendix__Deal__c
```

### Issue 2: LLM Not Using All Results
Even though 18 matches are returned, only 4 citations are shown to the LLM. This suggests:
- Results are being filtered somewhere between Lambda and LLM
- LLM is only selecting top N results based on score
- Graph-discovered nodes (score 0.75) may be ranked lower than vector results

### Issue 3: Property Node Has No Display Name
The Preston Park Financial Center property node in the graph:
```json
{
  "nodeId": "a0afk000000PvnfAAC",
  "displayName": "a0afk000000PvnfAAC",  // Just the ID!
  "type": "ascendix__Property__c",
  "attributes": {}  // Empty!
}
```

This makes it hard for vector search to find this property by name.

## Changes Made (Session 2025-11-27)

### 1. Fixed Seed Record IDs Passing
**File**: `lambda/retrieve/graph_retriever.py`

**Problem**: `seed_record_ids` parameter was accepted but not passed through to `_get_start_nodes`

**Fix**:
```python
# Updated _get_start_nodes_with_circuit_breaker signature
def _get_start_nodes_with_circuit_breaker(
    self,
    extraction: EntityExtraction,
    filters: Optional[Dict[str, Any]],
    seed_record_ids: Optional[List[str]] = None  # Added
) -> List[Dict[str, Any]]:
```

### 2. Reordered Retrieval Flow
**File**: `lambda/retrieve/index.py`

**Problem**: Graph traversal ran BEFORE vector search, so it couldn't use vector results as seeds

**Fix**: Moved vector search first, then pass results to graph traversal:
```python
# Run vector search FIRST
matches = _query_bedrock_kb(...)

# Extract seed IDs from vector results
seed_record_ids = []
for match in matches[:15]:
    record_id = match.get("metadata", {}).get("recordId")
    if record_id:
        seed_record_ids.append(record_id)

# Execute graph retrieval with seeds
graph_result = graph_retriever.retrieve(..., seed_record_ids=seed_record_ids)
```

### 3. Added Graph-Discovered Nodes to Results
**File**: `lambda/retrieve/index.py` - `_merge_graph_and_vector_results()`

**Problem**: Graph traversal found 179 nodes but only boosted existing vector results - didn't ADD new nodes

**Fix**: Added logic to fetch graph-only nodes and add them to results:
```python
graph_only_nodes = matching_node_ids - vector_record_ids

for node_id in sorted_nodes[:15]:
    # Fetch node from DynamoDB
    # Try to fetch S3 chunk content
    # Create match entry with score 0.75
    # Add to merged_matches
```

### 4. Added S3 Chunk Fetching
**Problem**: Graph-discovered nodes had minimal text

**Fix**: Try to fetch actual chunk content from S3:
```python
chunk_key = f"chunks/{node_type}/{node_id}/chunk-0.txt"
chunk_response = s3_client.get_object(Bucket=data_bucket, Key=chunk_key)
chunk_text = chunk_response['Body'].read().decode('utf-8')
if chunk_text:
    text_parts = [chunk_text]  # Use actual content
```

### 5. Prioritized Deal Types
**Problem**: Graph-discovered nodes might include non-deal types

**Fix**: Sort to process deals first:
```python
sorted_nodes = sorted(
    list(graph_only_nodes),
    key=lambda x: 0 if x.startswith('a0P') else 1  # a0P = Deal prefix
)
```

### 6. Added Decimal JSON Encoder
**Problem**: DynamoDB Decimal types caused JSON serialization errors

**Fix**:
```python
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        from decimal import Decimal
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)
```

### 7. Enhanced Test Suite
**File**: `test_automation/relationship_query_tests.py`

Added:
- Known test data with actual record IDs
- Validation checks for expected record IDs
- Graph traversal verification tests
- Tests specifically for Preston Park deals

## Current Logs

```
[INFO] Using 8 seed records for graph traversal
[INFO] Found 8 seed nodes in graph
[INFO] Found 8 starting nodes
[INFO] Graph retrieval: 179 nodes, depth=2, cache_hit=True
[INFO] Graph merge: 179 graph nodes, 13 boosted matches, 10 added from graph
[INFO] After graph merge: 18 matches
[INFO] Post-filter returned 18 matches
```

## Next Steps to Debug

### 1. Check S3 Fetch Success
Add logging to see if S3 chunks are being fetched:
```python
LOGGER.info(f"Fetched S3 chunk for {node_id}: {len(chunk_text)} chars")
```

Look for these log messages in next invocation.

### 2. Check What's Being Returned
Log the actual record IDs and types of the 18 matches:
```python
LOGGER.info(f"Final matches: {[(m.get('metadata',{}).get('recordId'), m.get('metadata',{}).get('sobject')) for m in matches]}")
```

### 3. Check LLM Input
The issue might be in how results are passed to the LLM. Check:
- Are all 18 matches being sent to the LLM?
- Is there a limit on citations (currently showing only 4)?
- Are graph-discovered nodes being filtered out before LLM?

### 4. Verify S3 Access from VPC
Lambda is in VPC. Check if it has:
- VPC endpoint for S3
- NAT Gateway for internet access
- Proper IAM permissions for S3

Test with:
```bash
aws lambda invoke --function-name salesforce-ai-search-retrieve \
  --payload '{"test":"s3"}' /tmp/test.json
```

### 5. Check Graph Node Quality
The property node `a0afk000000PvnfAAC` has no displayName or attributes. This might be why vector search doesn't find it well. Consider:
- Re-running graph builder to populate displayName
- Adding property name to node attributes
- Enriching graph nodes with more metadata

## Workaround Options

### Option A: Boost Graph-Discovered Scores Higher
Change score from 0.75 to 0.85 so they rank higher:
```python
"score": 0.85,  # Higher than vector results
```

### Option B: Force Deal Types to Top
Sort final results to put deals first:
```python
merged_matches.sort(key=lambda x: (
    0 if x.get('metadata',{}).get('sobject') == 'ascendix__Deal__c' else 1,
    -x.get('score', 0)
))
```

### Option C: Increase Citation Limit
If there's a limit on citations passed to LLM, increase it to include more graph-discovered nodes.

### Option D: Fix Graph Node Data
Re-run graph builder with enhanced node creation:
```python
node = {
    'nodeId': record_id,
    'displayName': record.get('Name', record_id),
    'type': sobject_type,
    'attributes': {
        'Name': record.get('Name'),
        'Status': record.get('Status__c'),
        # Add more relevant fields
    }
}
```

## Files Modified

1. `lambda/retrieve/index.py` - Main retrieval logic
2. `lambda/retrieve/graph_retriever.py` - Graph traversal
3. `test_automation/relationship_query_tests.py` - Test definitions
4. `test_automation/run_phase3_acceptance_tests.py` - Test runner

## Related Issues

- Graph nodes have minimal metadata (no displayName, empty attributes)
- S3 fetch from VPC Lambda may be failing
- LLM only using 4 of 18 citations
- Need better logging to diagnose where results are lost

## Success Criteria

Query "What active deals are associated with office properties in Plano?" should return:
- Multiple deals (at least 3-5)
- Include deals from Preston Park Financial Center
- Show deal details (status, stage, amount, etc.)
- Properly attribute deals to their properties

## Resolution (November 27, 2025)

### Root Cause Identified

The **actual root cause** was an **IAM permission issue** - the Retrieve Lambda role did not have permissions to:
1. Query DynamoDB graph tables (nodes, edges, path-cache)
2. Query DynamoDB GSI `type-createdAt-index`
3. Read from S3 data bucket for chunk content

This caused all graph queries to fail silently with `AccessDeniedException`, falling back to vector-only search.

### Fix Applied

**Files Modified:**
1. `lib/api-stack.ts` - Added graph tables and data bucket to ApiStack props
2. `bin/app.ts` - Pass graph tables to ApiStack

**Changes in api-stack.ts:**

```typescript
// Added to ApiStackProps interface
graphNodesTable: dynamodb.Table;
graphEdgesTable: dynamodb.Table;
graphPathCacheTable: dynamodb.Table;
dataBucket: cdk.aws_s3.Bucket;

// Added permissions for Retrieve Lambda role
graphNodesTable.grantReadData(retrieveRole);
graphEdgesTable.grantReadData(retrieveRole);
graphPathCacheTable.grantReadWriteData(retrieveRole);
dataBucket.grantRead(retrieveRole);

// Added environment variables
GRAPH_NODES_TABLE: graphNodesTable.tableName,
GRAPH_EDGES_TABLE: graphEdgesTable.tableName,
GRAPH_PATH_CACHE_TABLE: graphPathCacheTable.tableName,
DATA_BUCKET: dataBucket.bucketName,
INTENT_ROUTING_ENABLED: 'true',
GRAPH_ROUTING_ENABLED: 'true',
```

### Verification

After deploying `npx cdk deploy SalesforceAISearch-Api-dev`:

**CloudWatch Logs (Before Fix):**
```
[WARNING] Error querying nodes by type ascendix__Deal__c: AccessDeniedException
```

**CloudWatch Logs (After Fix):**
```
[INFO] Using 8 seed records for graph traversal
[INFO] Found 8 seed nodes in graph
[INFO] Graph retrieval: 179 nodes, depth=2, cache_hit=False
[INFO] Fetched S3 chunk for a0Pfk000000Ch7BEAS: 274 chars
[INFO] Fetched S3 chunk for a0Pfk000000Ch7AEAS: 302 chars
... (15 S3 chunks fetched)
[INFO] Graph merge: 179 graph nodes, 18 boosted matches, 15 added from graph
[INFO] After graph merge: 23 matches
[INFO] Post-filter returned 23 matches
```

**Query Result (topK=20):**
- Now returns **7 active deals** associated with Plano office properties
- Correctly identifies **Preston Park Financial Center** and lists its deals
- Graph-discovered deals have full chunk content from S3

### Additional Fix: Increased DEFAULT_TOP_K

The initial IAM fix enabled graph retrieval, but results were still limited due to `DEFAULT_TOP_K=8`.

**Changes Made:**
- `DEFAULT_TOP_K`: 8 → 15
- `MAX_TOP_K`: 20 → 25

**Result After Both Fixes:**
```
Bedrock KB returned 15 matches (pre-filter)
Graph merge: 179 graph nodes, 20 boosted matches, 15 added from graph
After graph merge: 30 matches
Post-filter returned 30 matches
```

**LLM Response Now Shows:**
- Deals at Preston Park Financial Center (multiple deals with details)
- Plano Office Condo (correctly notes no active deals)
- Proper relationship attribution

### Fix 3: Property Name Resolution in Graph Context

Even with more matches, the LLM couldn't connect deals to properties because:
- Deal chunks only contain: `Property ID: a0afk000000PvnfAAC`
- Property chunks contain the name but not prominently linked

**Best Practice Applied:**
- **Data Layer**: Use IDs for relationships (correct - graph uses IDs)
- **Presentation Layer**: Resolve IDs to names for LLM context

**Code Change in `lambda/retrieve/index.py`:**
```python
# Build a cache of node ID to display name for path resolution
node_name_cache: Dict[str, str] = {}
for path_node_id in all_path_node_ids:
    resp = graph_nodes_table.get_item(Key={'nodeId': path_node_id})
    node_name_cache[path_node_id] = resp['Item'].get('displayName', path_node_id)

# When adding graph-discovered deals:
path_names = [node_name_cache.get(nid, nid) for nid in path_nodes]
text_parts.append(f"Relationship Path: {' → '.join(path_names)}")
text_parts.append(f"ASSOCIATED WITH PROPERTY: {start_node_name}")
```

**Result:**
- LLM now sees: "ASSOCIATED WITH PROPERTY: Preston Park Financial Center"
- Response: "Preston Park Financial Center... has multiple active deals"

### Fix 4: Intent Router Pattern Matching

The query "what are the active deals for office properties in Plano?" was being classified as `FIELD_FILTER` instead of `RELATIONSHIP` because:

1. "active" and "in Plano" matched FIELD_FILTER patterns (status_keyword, location)
2. "deals for **office** properties" didn't match RELATIONSHIP pattern because "office" was between "for" and "properties"

**Changes in `lambda/retrieve/intent_router.py`:**
```python
# Before: Only matched "deals for properties"
(r'\b(?:deals?)\s+(?:for|on|involving)\s+(?:properties?|buildings?)\b', 0.9, "deal_property"),

# After: Allows optional adjectives/types between keywords
(r'\b(?:deals?)\s+(?:for|on|at|involving|associated\s+with)\s+(?:\w+\s+)?(?:properties?|buildings?)\b', 0.9, "deal_property"),
(r'\b(?:deals?)\s+(?:for|on|at|involving)\s+(?:\w+\s+){0,2}(?:properties?|buildings?)\b', 0.85, "deal_property_multi"),
(r'\b(?:active|open)\s+deals?\s+(?:for|at|on|in)\b', 0.85, "active_deal_location"),
```

## Final Summary

Four fixes deployed:
1. **IAM Permissions** - Retrieve Lambda can access graph tables and S3
2. **DEFAULT_TOP_K = 15** - More context passed to LLM
3. **Property Name Resolution** - Graph-discovered deals include property names
4. **Intent Router Patterns** - Better RELATIONSHIP pattern matching for queries with adjectives

## Status: All Fixes Deployed - Ready for Verification

**Fixes Deployed (November 27, 2025):**
1. ✅ IAM Permissions - Retrieve Lambda can access graph tables and S3
2. ✅ DEFAULT_TOP_K = 15 - More context passed to LLM
3. ✅ Property Name Resolution - Graph-discovered deals include property names
4. ✅ Intent Router Patterns - Better RELATIONSHIP pattern matching for queries with adjectives

**What's Working:**
- Graph traversal finds 179 related nodes
- S3 chunk fetching works (15+ deals fetched)
- Property names resolved in relationship context
- IAM permissions correct
- Intent router patterns updated for "deals for [type] properties"

**Verification Needed When Resuming:**
- Verify intent router now classifies "deals for office properties" as RELATIONSHIP
- Confirm Preston Park Financial Center deals appear in response
- End-to-end test via LWC

## Files Modified

1. `lib/api-stack.ts` - IAM permissions, DEFAULT_TOP_K, env vars
2. `bin/app.ts` - Pass graph tables to ApiStack
3. `lambda/retrieve/index.py` - Property name resolution in graph context
4. `lambda/retrieve/intent_router.py` - Better relationship pattern matching

## Next Steps

1. Test the query "what are the active deals for office properties in Plano?" in LWC
2. Check CloudWatch logs for `Intent Classification: intent=RELATIONSHIP`
3. Verify Preston Park deals appear with proper property association
4. If still not working, may need to boost RELATIONSHIP score weight over FIELD_FILTER

## Contact

Continue troubleshooting from this point. Key diagnostic:
```bash
aws logs tail "/aws/lambda/salesforce-ai-search-retrieve" --since 2m | grep -E "(Intent|Graph|matches)"
```

Expected output after fix:
```
Intent Classification: intent=RELATIONSHIP, confidence=0.9, routing=graph_aware
Graph retrieval: 179 nodes, depth=2
Graph merge: X graph nodes, Y boosted matches, Z added from graph
```
