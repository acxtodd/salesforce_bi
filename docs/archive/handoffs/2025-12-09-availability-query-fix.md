# Handoff: Availability Query Fix

**Date**: 2025-12-09
**Status**: In Progress
**Priority**: High

## Summary

Fixing AI Search queries for Availability records (e.g., "show me available space we have for class a office space in plano"). The query was returning "I don't have enough information" due to multiple issues in the pipeline.

## Issues Fixed

### 1. Graph Filter Candidate IDs Not Used in KB Query (COMPLETED)
**File**: `/lambda/retrieve/index.py` (lines ~2906-2915)

The graph filter was finding correct candidates but the KB query wasn't using them to filter results.

**Fix**: Added code to pass graph filter candidate IDs to KB query:
```python
if graph_filter_candidate_ids and len(graph_filter_candidate_ids) > 0:
    effective_metadata_filters.append({
        "field": "recordId",
        "operator": "IN",
        "values": list(graph_filter_candidate_ids)[:500],
    })
```

### 2. RecordType.Name OpenSearch Mapping Conflict (COMPLETED)
**File**: `/lambda/chunking/index.py`

KB ingestion was failing with: `Could not dynamically add mapping for field [RecordType.Name]`

**Fix**: Removed `RecordType.Name` from `FALLBACK_CONFIGS.Text_Fields__c` for both:
- `ascendix__Property__c`
- `ascendix__Availability__c`

Metadata now uses `RecordType` and `RecordTypeName` instead (no dot notation).

### 3. Entity Detection Routing to Wrong Object (COMPLETED)
**File**: `/lambda/retrieve/schema_decomposer.py` (lines ~144-152)

"available space" queries were routing to `ascendix__Property__c` instead of `ascendix__Availability__c` due to tie-breaking.

**Fix**: Added more patterns to Availability entity detection:
```python
"ascendix__Availability__c": [
    r"\bavailab(?:le|ility)\b",
    r"\bavailable\s+space(?:s)?\b",  # NEW - "available space" specifically
    r"\boffice\s+space(?:s)?\b",      # NEW - "office space" → Availability
    r"\bvacant\b",
    r"\bvacanc(?:y|ies)\b",
    r"\bspace(?:s)?\s+(?:for|to)\s+(?:lease|rent)\b",
    r"\bfor\s+lease\b",
],
```

### 4. Cross-Object Handler Query Order (IN PROGRESS)
**File**: `/lambda/retrieve/cross_object_handler.py` (line ~469-474)

Cross-object queries were returning no results because the DynamoDB query was sorted by `createdAt` ascending (oldest first), and Plano Office properties are recent.

**Fix Applied** (needs deployment):
```python
response = self.nodes_table.query(
    IndexName='type-createdAt-index',
    KeyConditionExpression=Key('type').eq(object_type),
    Limit=MAX_NODES_PER_HOP * 10,
    ScanIndexForward=False,  # NEW - Newest first
)
```

## Current State

### Deployments Completed
1. **Chunking Lambda** - Deployed with RecordType.Name fix
2. **Retrieve Lambda** - Deployed with entity detection fix
3. **Property Chunks** - Re-indexed in S3 (2466 records)
4. **KB Sync** - Completed successfully (2400 documents, 0 failures)

### Pending Deployment
The cross-object handler fix (`ScanIndexForward=False`) is saved but **NOT YET DEPLOYED**.

## To Continue

### Step 1: Deploy Retrieve Lambda with Cross-Object Fix
```bash
cd "/Users/toddadmin/Library/CloudStorage/OneDrive-AscendixTechnologiesInc/Salesforce BI/lambda/retrieve"
zip -r /tmp/retrieve-lambda-final.zip *.py
aws lambda update-function-code --function-name salesforce-ai-search-retrieve --zip-file fileb:///tmp/retrieve-lambda-final.zip --region us-west-2
```

### Step 2: Test the Query
```bash
curl -s -X POST 'https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d '{"query": "show me available space we have for class a office space in plano", "salesforceUserId": "005dl00000Q6a3RAAR", "filters": {}}'
```

### Step 3: Verify in Salesforce UI
Test the same query in the Ascendix AI Search UI to confirm results appear correctly.

## Expected Results

The query should now:
1. Detect entity as `ascendix__Availability__c` (3 pattern matches)
2. Detect cross-object filter: Property with Class=A, RecordType=Office, City=Plano
3. Find 3 matching Properties (Granite Park Three, Plano Office Condo, Preston Park Financial Center)
4. Traverse to their related Availability records
5. Return those Availabilities as results

## Verification Queries

### Check Entity Detection
In logs, should see:
```
Detected entity: ascendix__Availability__c (matches: 3)
```

### Check Cross-Object Detection
In logs, should see:
```
Cross-object query detected: target=ascendix__Availability__c, filter_entity=ascendix__Property__c, filters={'ascendix__PropertyClass__c': 'A', 'RecordType': 'Office', 'ascendix__City__c': 'Plano'}
```

### Check Property Nodes Found
In logs, should see:
```
Found 3 ascendix__Property__c records matching filters
```

## Files Modified

| File | Changes |
|------|---------|
| `/lambda/retrieve/index.py` | Added graph filter candidate IDs to KB query |
| `/lambda/chunking/index.py` | Removed RecordType.Name from FALLBACK_CONFIGS |
| `/lambda/retrieve/schema_decomposer.py` | Added Availability entity patterns |
| `/lambda/retrieve/cross_object_handler.py` | Added ScanIndexForward=False (NOT DEPLOYED) |

## Related Data

- **Knowledge Base ID**: HOOACWECEX
- **Data Source ID**: HWFQ9Q5FOB
- **Lambda URL**: https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer
- **Graph Nodes Table**: salesforce-ai-search-graph-nodes
- **Test User ID**: 005dl00000Q6a3RAAR

## Plano Office Properties in Graph

| Node ID | Name | Class |
|---------|------|-------|
| a0afk000000PvFWAA0 | Plano Office Condo | A |
| a0afk000000PvFIAA0 | Granite Park Three | A |
| a0afk000000PvnfAAC | Preston Park Financial Center | A |
| a0afk000000PvFDAA0 | Granite Park One | - |
| a0afk000000Pv7rAAC | 1022 E 15th St, Plano, TX | - |
| a0afk000000PvFLAA0 | 5800 Granite Pkwy | - |
