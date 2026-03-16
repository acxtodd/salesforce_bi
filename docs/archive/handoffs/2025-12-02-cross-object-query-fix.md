# Cross-Object Query Fix - Handoff Document

**Date:** 2025-12-02 (Updated)
**Issue:** Cross-object queries not returning expected results
**Example Query:** "what availabilities exist for class a office properties in plano?"
**Expected:** Find availabilities for Preston Park Financial Center (Class A Office in Plano)
**Actual:** Query only found test availability, not real data

---

## Executive Summary

Cross-object queries are failing because **both** the vector search path and graph traversal path lack parent object context. Initial fixes addressed the chunking Lambda (vector path), but the graph path remains broken. This document proposes a systematic fix to make the zero-config architecture actually work.

---

## Architecture Overview

The system has **two parallel paths** for cross-object queries:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CROSS-OBJECT QUERY FLOW                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  User Query: "Class A office availabilities in Plano"                        │
│                           │                                                  │
│                           ▼                                                  │
│                  ┌─────────────────┐                                         │
│                  │ Query Decomposer │                                        │
│                  │ (schema_decomposer.py)                                    │
│                  └────────┬────────┘                                         │
│                           │                                                  │
│           ┌───────────────┴───────────────┐                                  │
│           ▼                               ▼                                  │
│  ┌─────────────────┐            ┌─────────────────┐                          │
│  │  VECTOR PATH    │            │   GRAPH PATH    │                          │
│  │  (OpenSearch)   │            │   (DynamoDB)    │                          │
│  └────────┬────────┘            └────────┬────────┘                          │
│           │                              │                                   │
│           ▼                              ▼                                   │
│  Semantic search on             CrossObjectQueryHandler:                     │
│  chunk text containing          1. Query Property nodes                      │
│  "Plano", "Class A",               where City=Plano, Class=A                 │
│  "Office"                       2. Traverse edges to                         │
│           │                        Availability nodes                        │
│           │                     3. Return Availability IDs                   │
│           ▼                              │                                   │
│  ┌─────────────────┐                     │                                   │
│  │ Chunks with     │                     │                                   │
│  │ embedded parent │◄────────────────────┘                                   │
│  │ context         │     (Graph provides filter,                             │
│  └─────────────────┘      Vector provides ranking)                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Both paths require parent context to work:**
- Vector path needs "Property City: Plano" in chunk text
- Graph path needs `ascendix__City__c: "Plano"` in node attributes

---

## Root Cause Analysis

### Problem 1: Configuration Cascade Failure

Both chunking and graph builder Lambdas attempt to load configuration via this cascade:

```
1. Query Salesforce IndexConfiguration__mdt  → FAILS (no SSM permissions)
2. Load from Schema Cache (S3)               → FAILS (cache not populated)
3. Fall back to DEFAULT_CONFIG               → USELESS (generic defaults)
```

**Evidence:**
```
AccessDeniedException: ssm:GetParameter on /salesforce/instance_url
No module named 'cache'
```

### Problem 2: Chunking Lambda - Missing Parent Context (PARTIALLY FIXED)

Availability chunks only contained:
```
--- Related Context ---
Property ID: a0R...
```

Instead of:
```
--- Related Context ---
Property: Preston Park Financial Center
Property City: Plano
Property State: TX
Property Class: A
Property Type: Office
```

**Status:** Partially fixed with hardcoded `FALLBACK_CONFIGS` in `lambda/chunking/index.py`

### Problem 3: Graph Builder - Incomplete Node Attributes (NOT FIXED)

**Direct observation from DynamoDB `salesforce-ai-search-graph-nodes` table:**

#### Case Study: Preston Park Financial Center

This is a real Class A Office property in Plano with 9 availabilities. The query "availabilities for class a office properties in Plano" should find it.

**Salesforce Data (correct):**
```
Property: Preston Park Financial Center (ID: a0afk000000PvnfAAC)
  RecordType: Office ✓
  City: Plano ✓
  State: TX ✓
  PropertyClass: A ✓
  Availabilities: 9 (Suite 3400, Unit 450, Suite 500, etc.)
```

**Graph Node (incomplete):**
```python
{
  "nodeId": "a0afk000000PvnfAAC",
  "displayName": "Preston Park Financial Center",
  "type": "ascendix__Property__c",
  "depth": 0,  # Directly indexed, good!
  "attributes": {
    "LastModifiedDate": "2025-05-23T10:00:26Z",
    "ascendix__PropertyClass__c": "A",        # ✓ Present
    "ascendix__PropertySubType__c": "General",
    "Name": "Preston Park Financial Center"
    # ❌ MISSING: ascendix__City__c (Plano)
    # ❌ MISSING: ascendix__State__c (TX)
    # ❌ MISSING: RecordType.Name (Office)
  }
}
```

**Availability Nodes (no inherited context):**
```python
{
  "nodeId": "a0Dfk000002JuDVEA0",
  "displayName": "Suite 3400",
  "type": "ascendix__Availability__c",
  "attributes": {
    "LastModifiedDate": "2025-05-23T11:16:08Z",
    "ascendix__Status__c": "Open",
    "Name": "Suite 3400"
    # ❌ MISSING: propertyCity, propertyClass, propertyType (not inherited)
  }
}
```

**Why the query fails:**

The `CrossObjectQueryHandler._query_nodes_by_attributes()` tries to find Properties matching:
- `ascendix__City__c = "Plano"` → **FAILS** (City not in node attributes)
- `RecordType.Name = "Office"` → **FAILS** (RecordType not in node attributes)
- `ascendix__PropertyClass__c = "A"` → ✓ Would match

Since City and RecordType filters fail, **zero Properties match**, so no graph traversal happens, and the 9 availabilities are never found.

**The test record "Suite 100 - Available Space" at "Plano Office Tower" IS found** because it was manually created with all inherited attributes in the chunk text. Real data lacks this context.

#### Root Causes:

1. **Graph_Node_Attributes__c config is incomplete:**
   ```
   Configured: Name, ascendix__City__c, ascendix__State__c, ascendix__PropertyClass__c, ascendix__PropertySubType__c
   Missing: RecordType.Name
   ```

2. **City and State not making it into graph nodes** despite being in config - likely the SOQL query fetches them but they're lost in the pipeline

3. **Availability nodes don't inherit parent attributes** because `_inherit_parent_attributes()` fetches from parent node which is missing the fields

### Problem 4: Indexing Order Race Condition

Salesforce batch jobs run **asynchronously in parallel**. Even though `trigger_full_export.apex` lists Property before Availability:

```apex
Database.executeBatch(new AISearchBatchExport('ascendix__Property__c', 100000), 50);
Database.executeBatch(new AISearchBatchExport('ascendix__Availability__c', 100000), 50);
```

Both batches start simultaneously. Child objects often get indexed before their parents, creating stub nodes that never get enriched.

### Problem 5: Data Quality in Salesforce

Even when configuration works, some Properties lack key fields:

```
Properties with PropertyClass populated: 90 out of 2,466 (3.6%)
Properties with City populated: ~500 out of 2,466 (~20%)
```

This is a data quality issue, not a system issue, but it limits what queries can succeed.

---

## What Was Done (Initial Fixes)

### 1. Fixed Chunking Lambda Fallback Logic

**File:** `lambda/chunking/index.py`

- Added `FALLBACK_CONFIGS` at module level with relationship traversal fields
- Added smart config selection that detects useless defaults
- Added RecordType.Name extraction from nested relationship data

### 2. Deployed IndexConfiguration Metadata

Deployed to both orgs with proper `Relationship_Fields__c`:
```
ascendix__Property__c, ascendix__Property__r.Name, 
ascendix__Property__r.ascendix__City__c, 
ascendix__Property__r.ascendix__State__c, 
ascendix__Property__r.ascendix__PropertyClass__c, 
ascendix__Property__r.RecordType.Name
```

### 3. What These Fixes Address

| Issue | Vector Path | Graph Path |
|-------|-------------|------------|
| Missing parent context in chunks | ✅ Fixed | ❌ Not addressed |
| Empty graph node attributes | N/A | ❌ Not fixed |
| Configuration cascade failure | ⚠️ Workaround | ❌ Not fixed |
| Indexing order race condition | N/A | ❌ Not fixed |

---

## What Remains Broken

### Graph Traversal Path is Non-Functional

**Demonstrated with real query:** "what availabilities for class a office properties (like Preston Park Financial Center) in Plano?"

**Expected:** Find 9 availabilities for Preston Park Financial Center
**Actual:** Found only 1 test record ("Suite 100 - Available Space" at "Plano Office Tower")

The `CrossObjectQueryHandler` in `lambda/retrieve/cross_object_handler.py`:

1. **`_query_nodes_by_attributes()`** - Queries Property nodes where `City=Plano`, `Class=A`, `RecordType=Office`
   - **FAILS**: Property nodes are missing `City` and `RecordType` in attributes
   - Preston Park Financial Center has `PropertyClass=A` but no `City` or `RecordType`
   - Query returns zero matching Properties

2. **`_traverse_to_target()`** - Traverses edges from Property to Availability
   - **NEVER EXECUTES**: No Property nodes match filters, so no traversal happens

3. **Result**: The 9 real availabilities for Preston Park Financial Center are never found

**Why the test record IS found:** The test availability "Suite 100" was created with full parent context embedded in the chunk text ("Property City: Plano, Property Class: A, Property Type: Office"). The vector search finds it via semantic matching. Real data lacks this embedded context.

### Schema Discovery Not Running

The zero-config architecture depends on schema discovery populating S3:
```
s3://salesforce-ai-search-data-{account}-{region}/schema/{object}.json
```

**Current state:** No schema files exist in S3. Schema discovery has never run successfully.

---

## Proposed Systematic Fix

### Option A: Make Zero-Config Actually Work (Recommended)

**Goal:** Fix the infrastructure so the configuration cascade succeeds.

#### A1. Grant SSM Permissions to Lambdas

Add IAM permissions to chunking and graph_builder Lambdas:
```json
{
  "Effect": "Allow",
  "Action": ["ssm:GetParameter", "ssm:GetParameters"],
  "Resource": "arn:aws:ssm:*:*:parameter/salesforce/*"
}
```

**Effort:** Low (CDK change)
**Impact:** Lambdas can query Salesforce for IndexConfiguration__mdt

#### A2. Run Schema Discovery

Create a scheduled job or manual trigger to:
1. Query Salesforce Describe API for each configured object
2. Extract filterable, numeric, date, and relationship fields
3. Store schema JSON in S3

**Effort:** Medium (Lambda exists, needs to be wired up)
**Impact:** Schema cache fallback works, zero-config extracts all filterable fields

#### A3. Fix Graph Builder Fallback Config

Add `FALLBACK_CONFIGS` to `lambda/graph_builder/index.py` similar to chunking Lambda:

```python
FALLBACK_CONFIGS = {
    "ascendix__Property__c": {
        "Graph_Node_Attributes__c": "Name, ascendix__City__c, ascendix__State__c, ascendix__PropertyClass__c, ascendix__PropertySubType__c, RecordType.Name",
        "Relationship_Fields__c": "OwnerId, ascendix__OwnerLandlord__c, ascendix__PropertyManager__c",
    },
    "ascendix__Availability__c": {
        "Graph_Node_Attributes__c": "Name, ascendix__Status__c, ascendix__UseType__c",
        "Relationship_Fields__c": "ascendix__Property__c",
    },
    # ... other objects
}
```

**Effort:** Low (code change)
**Impact:** Graph nodes get populated with correct attributes

#### A4. Implement Two-Phase Indexing

Modify `trigger_full_export.apex` to ensure parent objects are indexed first:

```apex
// Phase 1: Parent objects (wait for completion)
Id propertyJobId = Database.executeBatch(new AISearchBatchExport('ascendix__Property__c', 100000), 50);
Id accountJobId = Database.executeBatch(new AISearchBatchExport('Account', 100000), 200);

// Phase 2: Child objects (scheduled to run after Phase 1)
// Use Schedulable or Queueable to chain after Phase 1 completes
```

Or create a Step Functions workflow that orchestrates indexing order.

**Effort:** Medium
**Impact:** Parent nodes exist with attributes before children try to inherit

---

### Option B: Pass Configuration Through Pipeline

**Goal:** Apex batch already queries IndexConfiguration__mdt. Pass it through the pipeline.

#### B1. Include Config in Batch Payload

Modify `AISearchBatchExport.cls` to include the config in the payload sent to the ingest endpoint:

```apex
Map<String, Object> payload = new Map<String, Object>{
    'sobject' => this.sobjectType,
    'records' => records,
    'config' => new Map<String, Object>{
        'Text_Fields__c' => this.objectConfig.Text_Fields__c,
        'Relationship_Fields__c' => this.objectConfig.Relationship_Fields__c,
        'Graph_Node_Attributes__c' => this.objectConfig.Graph_Node_Attributes__c
        // ... other fields
    }
};
```

#### B2. Propagate Config Through Step Functions

Modify the Step Functions state machine to pass config to each Lambda:
- Ingest → Transform → Chunking → Graph Builder

Each Lambda receives the config from the event instead of querying Salesforce.

**Effort:** Medium (Apex + Step Functions changes)
**Impact:** Config is always available, no SSM/Salesforce dependency in Lambdas

---

### Option C: Hybrid Approach (Pragmatic)

Combine quick wins from both options:

1. **Immediate:** Add `FALLBACK_CONFIGS` to graph builder (Option A3)
2. **Immediate:** Resync all data with correct order (Properties first, then children)
3. **Short-term:** Grant SSM permissions (Option A1)
4. **Short-term:** Run schema discovery once to populate S3 cache (Option A2)
5. **Medium-term:** Implement config passthrough in pipeline (Option B)

---

## Recommended Action Plan

### Phase 1: Immediate (This Week)

1. **Add FALLBACK_CONFIGS to graph builder Lambda**
   - File: `lambda/graph_builder/index.py`
   - Copy pattern from `lambda/chunking/index.py`
   - **Include RecordType.Name** in Graph_Node_Attributes__c
   - Deploy Lambda

2. **Update IndexConfiguration__mdt for Property**
   - Add `RecordType.Name` to `Graph_Node_Attributes__c`
   - Current: `Name, ascendix__City__c, ascendix__State__c, ascendix__PropertyClass__c, ascendix__PropertySubType__c`
   - New: `Name, RecordType.Name, ascendix__City__c, ascendix__State__c, ascendix__PropertyClass__c, ascendix__PropertySubType__c`

3. **Debug why City/State aren't in graph nodes**
   - They ARE in the config but NOT in the stored attributes
   - Check if SOQL query includes them
   - Check if transform/chunking pipeline preserves them
   - Check if graph builder extracts them

4. **Resync data in correct order**
   ```bash
   # Step 1: Index parent objects
   sf apex run --target-org ascendix-beta-sandbox <<'EOF'
   Database.executeBatch(new AISearchBatchExport('ascendix__Property__c', 100000), 50);
   EOF
   
   # Step 2: Wait for completion (check Apex Jobs in Setup)
   
   # Step 3: Index child objects
   sf apex run --target-org ascendix-beta-sandbox <<'EOF'
   Database.executeBatch(new AISearchBatchExport('ascendix__Availability__c', 100000), 50);
   Database.executeBatch(new AISearchBatchExport('ascendix__Deal__c', 100000), 50);
   Database.executeBatch(new AISearchBatchExport('ascendix__Lease__c', 100000), 50);
   EOF
   ```

3. **Verify graph nodes have attributes**
   ```python
   # Check Property nodes
   aws dynamodb scan --table-name salesforce-ai-search-graph-nodes \
     --filter-expression "#t = :type" \
     --expression-attribute-names '{"#t": "type"}' \
     --expression-attribute-values '{":type": {"S": "ascendix__Property__c"}}' \
     --max-items 5
   ```

### Phase 2: Short-Term (Next Sprint)

1. Grant SSM permissions to Lambdas via CDK
2. Run schema discovery to populate S3 cache
3. Test that configuration cascade works end-to-end

### Phase 3: Medium-Term (Future)

1. Implement config passthrough in Step Functions
2. Create orchestrated indexing workflow
3. Add monitoring/alerting for configuration failures

---

## Verification Checklist

After implementing fixes, verify:

- [ ] Property graph nodes have `attributes` with City, State, Class
- [ ] Property graph nodes have `depth: 0` (directly indexed, not stubs)
- [ ] Availability graph nodes inherit parent attributes
- [ ] Cross-object query "Class A office in Plano" returns results
- [ ] Schema cache exists in S3 (if Option A2 implemented)
- [ ] Lambda logs show "Loaded config from Salesforce" (if Option A1 implemented)

---

## Files to Modify

| File | Change | Priority |
|------|--------|----------|
| `lambda/graph_builder/index.py` | Add FALLBACK_CONFIGS | P0 |
| `lib/salesforce-ai-search-stack.ts` | Add SSM permissions | P1 |
| `lambda/schema_discovery/index.py` | Wire up scheduled execution | P1 |
| `salesforce/classes/AISearchBatchExport.cls` | Include config in payload | P2 |
| `stepfunctions/ingestion.asl.json` | Pass config through states | P2 |

---

## Appendix: Diagnostic Commands

### Check Preston Park Financial Center (The Test Case)
```bash
python3 << 'EOF'
import boto3
import json
dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
table = dynamodb.Table('salesforce-ai-search-graph-nodes')

# Preston Park Financial Center - should have City=Plano, Class=A, RecordType=Office
response = table.get_item(Key={'nodeId': 'a0afk000000PvnfAAC'})
item = response.get('Item')
if item:
    print("Preston Park Financial Center node:")
    print(f"  displayName: {item.get('displayName')}")
    print(f"  depth: {item.get('depth')}")
    print(f"  attributes: {json.dumps(item.get('attributes', {}), indent=4)}")
    
    # Check what's missing
    attrs = item.get('attributes', {})
    expected = ['ascendix__City__c', 'ascendix__State__c', 'RecordType.Name', 'ascendix__PropertyClass__c']
    for field in expected:
        status = "✓" if field in attrs else "❌ MISSING"
        print(f"  {field}: {status}")
else:
    print("Node not found!")
EOF
```

### Check Graph Node Attributes
```bash
python3 << 'EOF'
import boto3
from boto3.dynamodb.conditions import Key
dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
table = dynamodb.Table('salesforce-ai-search-graph-nodes')

# Check Property nodes
response = table.query(
    IndexName='type-createdAt-index',
    KeyConditionExpression=Key('type').eq('ascendix__Property__c'),
    Limit=5
)
for item in response.get('Items', []):
    print(f"ID: {item['nodeId']}")
    print(f"  displayName: {item.get('displayName')}")
    print(f"  depth: {item.get('depth')}")
    print(f"  attributes: {item.get('attributes', {})}")
EOF
```

### Check Chunk Content
```bash
aws s3 cp s3://salesforce-ai-search-data-382211616288-us-west-2/staging/chunks/latest.json - | python3 -m json.tool | head -100
```

### Check Lambda Logs
```bash
aws logs tail /aws/lambda/salesforce-ai-search-graph-builder --follow --filter-pattern "config"
```

---

## References

- `lambda/chunking/index.py` - Chunking Lambda with FALLBACK_CONFIGS
- `lambda/graph_builder/index.py` - Graph builder Lambda (needs fix)
- `lambda/graph_builder/config_cache.py` - Configuration cascade logic
- `lambda/retrieve/cross_object_handler.py` - Cross-object query execution
- `salesforce/classes/AISearchBatchExport.cls` - Apex batch export
