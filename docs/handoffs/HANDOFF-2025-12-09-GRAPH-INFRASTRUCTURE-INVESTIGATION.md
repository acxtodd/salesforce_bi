# Handoff: Graph Infrastructure Investigation & Root Cause Analysis

> **⚠️ SUPERSEDED (2025-12-10)**
>
> **The conclusions in this document are incorrect.** Investigation on 2025-12-10 revealed:
> - RecordType IS present in 99.8% of Property graph nodes (not 0% as stated below)
> - The actual root causes were: (1) aggregation routing bug, (2) 40% fake fields in schema cache
>
> **See correct analysis:**
> - [`HANDOFF-2025-12-10-AGGREGATION-PRIORITY-FIX.md`](./HANDOFF-2025-12-10-AGGREGATION-PRIORITY-FIX.md) - Aggregation bug fix
> - [`HANDOFF-2025-12-10-SCHEMA-AUDIT.md`](./HANDOFF-2025-12-10-SCHEMA-AUDIT.md) - Schema cache audit
>
> This file is retained for traceability only.

---

**Date:** 2025-12-09
**Status:** ~~INVESTIGATION COMPLETE~~ **SUPERSEDED** - See above
**Severity:** ~~P0~~ Resolved via different fixes

---

## Executive Summary

Investigation into why "show class a office properties in plano" returns "I don't have enough information" revealed that **graph nodes are missing the `RecordType` attribute**. The query decomposes to filters including `RecordType: 'Office'`, but no graph nodes have this attribute, causing the graph filter to return 0 matches.

**Key Finding:** This is NOT a "schema loader import failure" causing "empty attributes" as initially hypothesized. The graph nodes DO have attributes (City, State, PropertyClass). The issue is that `RecordType.Name` is not included in the IndexConfiguration__mdt, so it's never exported from Salesforce and never stored in graph nodes.

---

## Corrected Root Cause Chain

```
IndexConfiguration__mdt missing RecordType.Name in Text_Fields__c and Graph_Node_Attributes__c
    ↓
Batch Export SOQL: SELECT Id, Name, City, State, PropertyClass... (no RecordType)
    ↓
Input to Graph Builder: {Id, Name, City, State, PropertyClass}
    ↓
Graph Builder stores: {Name, City, State, PropertyClass}  ← These ARE stored correctly
    ↓
Query decomposes to: filters={'PropertyClass': 'A', 'RecordType': 'Office', 'City': 'Plano'}
    ↓
Graph Filter queries: RecordType='Office' → 0 matches (field doesn't exist)
    ↓
AND logic: City=Plano (1985) AND PropertyClass=A (92) AND RecordType=Office (0) = 0
    ↓
Short-circuit → "I don't have enough information"
```

---

## Investigation Timeline

### Initial Hypothesis (INCORRECT)
"Schema loader import fails silently → empty attributes"

### Corrected Finding
Graph nodes DO have attributes. The issue is specific missing fields.

### Evidence: Graph Node Attribute Counts

```bash
aws dynamodb scan --table-name salesforce-ai-search-graph-nodes \
  --filter-expression "#t = :type" \
  --expression-attribute-names '{"#t": "type"}' \
  --expression-attribute-values '{":type": {"S": "ascendix__Property__c"}}'
```

| Attribute | Count | Percentage | Status |
|-----------|-------|------------|--------|
| Name | 2,468 | 99.9% | ✅ Present |
| ParentId_0 | 2,466 | 99.8% | ✅ Present |
| ascendix__City__c | 1,985 | 80.4% | ✅ Present |
| ascendix__State__c | 1,957 | 79.2% | ✅ Present |
| ascendix__PropertyClass__c | 92 | 3.7% | ✅ Present (sparse) |
| RecordType | 0 | 0% | ❌ **Never in input** |
| ascendix__Status__c | 0 | 0% | ❌ Never in input |

**Total Property nodes:** 2,470
**Nodes with empty attributes:** Only 2

### Evidence: Query Decomposition Logs

```
[INFO] Schema decomposition: entity=ascendix__Property__c, 
  filters={'ascendix__PropertyClass__c': 'A', 'RecordType': 'Office', 'ascendix__City__c': 'Plano'}, 
  confidence=0.9, needs_cross_object=False
```

The query correctly identifies the filters, but `RecordType` doesn't exist in graph nodes.

### Evidence: IndexConfiguration__mdt

**File:** `salesforce/customMetadata/IndexConfiguration.Property.md-meta.xml`

```xml
<values>
    <field>Text_Fields__c</field>
    <value>Name, ascendix__City__c, ascendix__State__c, ascendix__PropertyClass__c, ascendix__PropertySubType__c</value>
</values>
<values>
    <field>Graph_Node_Attributes__c</field>
    <value>Name, ascendix__City__c, ascendix__State__c, ascendix__PropertyClass__c, ascendix__PropertySubType__c</value>
</values>
```

**Missing:** `RecordType.Name` is not in either field list.

---

## Why Initial Analysis Was Wrong

### Misinterpretation 1: "Empty Attributes"
The CloudWatch log `[INHERIT] Final inherited attrs: {}` refers to **inherited attributes from parent relationships**, not all attributes. Direct attributes (City, State, etc.) are stored through a different code path.

### Misinterpretation 2: "Schema Loader Failure"
While the schema loader does log "Schema discovery not available", this is a secondary issue. Even with working schema discovery, the Graph Builder can't extract `RecordType` from records that don't contain it.

### Misinterpretation 3: Node Counts
Initial claim: "3,799 nodes with empty attributes"
Actual: 11,897 total nodes, 2,470 Property nodes, only 2 with empty attributes

---

## Current System State

| Component | Status | Details |
|-----------|--------|---------|
| Graph Builder Lambda | ✅ Working | Creates nodes with available attributes |
| Graph Nodes Table | ✅ Populated | 2,470 Property nodes with City, State, PropertyClass |
| RecordType Attribute | ❌ Missing | Not in IndexConfiguration, never exported |
| Schema Loader | ⚠️ Falls back | Secondary issue, not root cause |
| Graph Filter | ✅ Working correctly | Returns 0 when RecordType filter matches 0 nodes |

---

## Impact Assessment

### Queries That WORK
- "properties in Plano" → City filter works (1,985 nodes)
- "properties in Texas" → State filter works (1,957 nodes)
- "Class A properties" → PropertyClass filter works (92 nodes)

### Queries That FAIL
- "office properties in Plano" → RecordType='Office' matches 0 nodes
- "retail properties" → RecordType='Retail' matches 0 nodes
- Any query requiring RecordType filter

### Acceptance Scenarios

| ID | Scenario | Requires RecordType? | Status |
|----|----------|---------------------|--------|
| 14.1 | Available Class A office Plano | ✅ Yes | ❌ FAILS |
| 14.2 | Industrial Miami 20k-50k sf | ✅ Yes (Industrial) | ❌ FAILS |
| 14.3 | Class A office downtown | ✅ Yes | ❌ FAILS |
| 14.4 | Leases expiring 6 months | No | ⚠️ May work |
| 14.5-14.10 | Various | Varies | Varies |

---

## Remediation Plan

### Primary Fix: Add RecordType to IndexConfiguration

**Step 1:** Update `salesforce/customMetadata/IndexConfiguration.Property.md-meta.xml`:
```xml
<values>
    <field>Text_Fields__c</field>
    <value>Name, ascendix__City__c, ascendix__State__c, ascendix__PropertyClass__c, ascendix__PropertySubType__c, RecordType.Name</value>
</values>
<values>
    <field>Graph_Node_Attributes__c</field>
    <value>Name, ascendix__City__c, ascendix__State__c, ascendix__PropertyClass__c, ascendix__PropertySubType__c, RecordType.Name</value>
</values>
```

**Step 2:** Deploy to Salesforce:
```bash
sf project deploy start --source-dir salesforce/customMetadata --target-org ascendix-beta-sandbox
```

**Step 3:** Re-run batch export to re-ingest all Property records:
```apex
// In Salesforce Developer Console
AscendixAISearch.BatchExportController.triggerBatchExport('ascendix__Property__c');
```

**Step 4:** Verify graph nodes have RecordType:
```bash
aws dynamodb scan --table-name salesforce-ai-search-graph-nodes \
  --filter-expression "attribute_exists(attributes.RecordType)" \
  --select COUNT
```

**Effort:** ~1-2 hours
**Risk:** Low - configuration change only

### Secondary Fix (Nice-to-Have): Fix Schema Loader Import

The schema loader import issue is real but secondary. Fixing it would:
- Enable dynamic schema discovery in Graph Builder
- Reduce reliance on explicit IndexConfiguration
- But won't help if source records don't have the field

**File:** `lambda/graph_builder/schema_loader.py`
**Issue:** Import path for `schema_discovery.models` fails
**Effort:** ~1 hour

---

## Verification Commands

### Check RecordType in Graph Nodes (After Fix)
```bash
aws dynamodb scan --table-name salesforce-ai-search-graph-nodes \
  --filter-expression "#t = :type AND attribute_exists(attributes.RecordType)" \
  --expression-attribute-names '{"#t": "type"}' \
  --expression-attribute-values '{":type": {"S": "ascendix__Property__c"}}' \
  --select COUNT --output json --no-cli-pager
```

### Test Query (After Fix)
```bash
curl -X POST "https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $(aws secretsmanager get-secret-value --secret-id salesforce-ai-search/streaming-api-key --query SecretString --output text)" \
  -d '{"query": "show class a office properties in plano", "userId": "005dl00000Q6a3RAAR", "sessionId": "test-session"}'
```

---

## Lessons Learned

1. **Verify data before assuming code bugs** - The initial hypothesis blamed schema loader when the data was actually present
2. **Check the full data pipeline** - The issue was in Salesforce configuration, not Lambda code
3. **AND filters are strict** - One missing attribute causes entire filter to fail
4. **Log messages can be misleading** - "Final inherited attrs: {}" referred to parent inheritance, not all attributes

---

## Files to Modify

| File | Change Required | Priority |
|------|-----------------|----------|
| `salesforce/customMetadata/IndexConfiguration.Property.md-meta.xml` | Add RecordType.Name | P0 |
| `lambda/graph_builder/schema_loader.py` | Fix import path | P2 (nice-to-have) |
| `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md` | Update with corrected analysis | P1 |

---

## Conclusion

The root cause is **missing RecordType.Name in IndexConfiguration__mdt**, not a schema loader failure or empty attributes. The fix is straightforward: add RecordType.Name to the configuration and re-export data.

**Immediate Action:**
1. Update IndexConfiguration.Property.md-meta.xml to include RecordType.Name
2. Deploy to Salesforce
3. Re-run batch export for Property records
4. Verify graph nodes have RecordType attribute
5. Re-test "show class a office properties in plano" query
