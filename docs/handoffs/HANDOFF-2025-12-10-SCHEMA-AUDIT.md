# Handoff: Schema Cache Audit & Fake Field Discovery

**Date:** 2025-12-10
**Session Duration:** Extended investigation
**Status:** Investigation Complete, Remediation Task Created

---

## Executive Summary

Discovered that **40% of schema cache fields are fabricated** - they don't exist in Salesforce. This explains why many queries fail. Created Task 37 for remediation.

---

## Key Discoveries

### 1. Task 32 Was Based on Incorrect Information

Previous handoffs claimed RecordType was missing from graph nodes (0%).

**Reality:**
- RecordType IS in graph nodes: 2,466/2,470 Property nodes (99.8%)
- The issue was schema cache had fake field `ascendix__PropertyType__c` instead

### 2. Schema Cache Has 40% Fake Fields

| Object | Fake | Real | % Fake |
|--------|------|------|--------|
| ascendix__Property__c | 10 | 6 | 63% |
| ascendix__Availability__c | 4 | 4 | 50% |
| ascendix__Lease__c | 5 | 4 | 56% |
| Contact | 1 | 6 | 14% |
| **Total** | **20** | **30** | **40%** |

### 3. Source of Fake Fields

`scripts/seed_schema_cache.py` was written with **guessed field names** based on CRE conventions, not by querying actual Salesforce metadata.

Example fake field proven not to exist:
```bash
sf sobject describe --sobject ascendix__Property__c --json | grep PropertyType
# Result: No match - field doesn't exist
```

### 4. Aggregation View Priority Bug Fixed

Separate issue found and fixed: When graph filter found results, vacancy_view was incorrectly overriding them.

**File:** `lambda/retrieve/index.py` lines 3260-3272
**Fix:** Skip ANY derived view when graph filter has specific results

---

## Fixes Applied Today

| Change | File | Status |
|--------|------|--------|
| Added RecordType to schema cache | DynamoDB `salesforce-ai-search-schema-cache` | Deployed |
| Fixed aggregation priority bug | `lambda/retrieve/index.py` | Deployed |
| Created Task 37 | `docs/tasks/TASK-37-SCHEMA-FIELD-REMEDIATION.md` | Complete |
| Updated Task 32 status | `.kiro/specs/.../tasks.md` | Complete |

---

## Test Results After Fixes

| Query | Before | After |
|-------|--------|-------|
| "class a office properties in plano" | "I don't have enough information" | 3 properties listed |
| "available class a office space in plano" | Working | Still working |
| "leases expiring in 6 months" | Working | Still working |

---

## Data Flow Understanding

```
Salesforce Schema (source)
       ↓
IndexConfiguration (what to export)
       ↓
Batch Export
       ↓
Graph Nodes (actual data)     Schema Cache (SHOULD match)
       ↓                            ↓
[Has: RecordType, City,       [Had: PropertyType (fake),
 State, PropertyClass]         VacancyRate (fake), etc.]
```

**Problem:** Schema cache was populated independently of actual data flow.

---

## Files Created

| File | Purpose |
|------|---------|
| `docs/tasks/TASK-37-SCHEMA-FIELD-REMEDIATION.md` | Detailed remediation task |
| `docs/handoffs/HANDOFF-2025-12-10-AGGREGATION-PRIORITY-FIX.md` | Earlier fix documentation |
| `docs/handoffs/HANDOFF-2025-12-10-SCHEMA-AUDIT.md` | This document |

---

## Next Steps (Task 37)

1. **Phase 1:** Remove 20 fake fields from DynamoDB schema cache
2. **Phase 2:** Update chunking Lambda FALLBACK_CONFIGS
3. **Phase 3:** Fix derived views field references
4. **Phase 4:** Deprecate seed_schema_cache.py (align with Task 34)

---

## Verification Commands

### Audit Schema Cache
```bash
python3 /tmp/audit_schema.py
```

### Check If Field Exists in SF
```bash
sf sobject describe --sobject ascendix__Property__c --target-org ascendix-beta-sandbox --json \
  | python3 -c "import json,sys; print('ascendix__PropertyType__c' in [f['name'] for f in json.load(sys.stdin)['result']['fields']])"
# Expected: False
```

### Test Query
```bash
curl -X POST "https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer" \
  -H "x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ" \
  -H "Content-Type: application/json" \
  -d '{"query": "class a office properties in plano", "salesforceUserId": "005dl00000Q6a3RAAR", "debug": true}'
```

---

## Lessons Learned

1. **Don't trust documentation** - Previous handoffs contained incorrect information
2. **Validate against source** - Schema cache fields should trace back to SF metadata
3. **Check all layers** - The bug was in schema cache, not graph nodes as documented
4. **Ad-hoc seeding is dangerous** - `seed_schema_cache.py` created without SF validation

---

## Related Documents

- Task 34: Schema-Driven Export (architectural fix)
- Task 37: Schema Cache Field Remediation (immediate fix)
- `HANDOFF-2025-12-10-AGGREGATION-PRIORITY-FIX.md`
