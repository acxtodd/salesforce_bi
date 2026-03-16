# Handoff: Aggregation View Priority Bug Fix

**Date:** 2025-12-10
**Status:** COMPLETE
**Session Focus:** Fix graph filter vs aggregation view priority

---

## Executive Summary

Discovered and fixed a bug where aggregation views (vacancy_view, availability_view) were incorrectly overriding graph filter results, causing queries like "show class a office properties in plano" to return wrong results from unrelated cities.

---

## Investigation Findings

### Documentation Was Wrong

Previous handoffs claimed:
- "RecordType is missing from graph nodes (0%)"
- "Task 32 is P0 blocker - add RecordType.Name to IndexConfiguration"

**Reality:**
- Graph nodes **DO have RecordType** (2,466 out of 2,470 Property nodes = 99.8%)
- RecordType values are correct (Office, Retail, Industrial, Land, etc.)
- DynamoDB query `filters={PropertyClass:A, RecordType:Office, City:Plano}` returns **3 correct results**

### The Real Bug

The issue was in `lambda/retrieve/index.py` lines 3260-3264:

```python
# BEFORE (buggy)
skip_aggregation_for_cross_object = (
    cross_object_has_results and
    aggregation_view_used == "availability_view"  # Only checked availability_view!
)
```

When querying "show class a office properties in plano":
1. Graph filter found 3 correct results (Plano Office Condo, Granite Park Three, Preston Park Financial Center)
2. Aggregation routed to `vacancy_view` which returned 5 random high-vacancy properties (LA, Ft. Worth, San Antonio)
3. System used vacancy_view results instead of graph filter results
4. LLM correctly said "I don't have information about Plano" because the context was wrong

---

## Fix Applied

**File:** `lambda/retrieve/index.py` (lines 3257-3272)

```python
# AFTER (fixed)
# Skip any derived view when graph filter has found specific IDs
graph_filter_has_results = graph_filter_candidate_ids and len(graph_filter_candidate_ids) > 0
skip_aggregation_for_graph_filter = (
    graph_filter_has_results and
    aggregation_view_used is not None  # Skip ANY derived view
)

if skip_aggregation_for_graph_filter:
    LOGGER.info(
        f"[AGGREGATION] Skipping {aggregation_view_used} ({len(aggregation_results)} records) "
        f"- using KB with graph filter IDs ({len(graph_filter_candidate_ids)} candidates) for accurate results"
    )
    aggregation_results = None  # Force KB query with recordId filter
```

Also updated variable reference at line 3329:
- Changed `cross_object_has_results` to `graph_filter_has_results`

---

## Test Results

### Before Fix
```
Query: "show class a office properties in plano"
Result: "I don't have enough information" (showing LA, Ft. Worth, San Antonio properties)
matchCount: 5 (from vacancy_view)
```

### After Fix
```
Query: "show class a office properties in plano"
Result: Lists 3 Class A Office properties in Plano:
  1. Plano Office Condo
  2. Preston Park Financial Center
  3. Granite Park Three
matchCount: 3 (from graph filter → KB)
```

### Log Evidence
```
[AGGREGATION] Skipping vacancy_view (5 records) - using KB with graph filter IDs (3 candidates) for accurate results
```

---

## Other Findings

### Cross-Object Handler Fix Already Deployed

The handoff `2025-12-09-availability-query-fix.md` claimed `ScanIndexForward=False` was "NOT YET DEPLOYED".

**Reality:** It was already deployed. The deployed Lambda code matches local code exactly.

### Task 32 is NOT a Blocker

Previous handoffs identified Task 32 (add RecordType to IndexConfiguration) as P0 blocker.

**Reality:**
- RecordType data is already in graph nodes
- The only issue was RecordType not in schema cache (causes "Unknown field" warning)
- This is cosmetic - the filter still applies correctly

---

## Deployment

| Component | Action | Status |
|-----------|--------|--------|
| Retrieve Lambda | Deployed with priority fix | ✅ Live |

---

## Files Modified

| File | Change |
|------|--------|
| `lambda/retrieve/index.py` | Fixed aggregation view priority logic (lines 3257-3272, 3329) |

---

## Verification Commands

### Test Office Properties Query
```bash
cat > /tmp/test.json << 'EOF'
{"query": "show class a office properties in plano", "salesforceUserId": "005dl00000Q6a3RAAR", "debug": true}
EOF
curl -s -X POST "https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer" \
  -H "x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ" \
  -H "Content-Type: application/json" \
  -d @/tmp/test.json | head -30
```

### Check Logs
```bash
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 5m --region us-west-2 --no-cli-pager | grep "Skipping.*using KB"
```

---

## Recommendations for Next Session

1. **Update tasks.md** - Mark Task 32 as not a blocker (RecordType data already exists)
2. **Add RecordType to schema cache** - Would remove "Unknown field" warning (cosmetic)
3. **Review other handoffs** - Multiple contained incorrect information
4. **Add integration test** - Test graph filter priority over aggregation views

---

## Lessons Learned

1. **Don't trust documentation blindly** - Always verify by inspecting actual data and code
2. **Check all code paths** - The bug only affected `vacancy_view`, not `availability_view`
3. **Variable naming matters** - Renamed `cross_object_has_results` to `graph_filter_has_results` to reflect actual purpose
