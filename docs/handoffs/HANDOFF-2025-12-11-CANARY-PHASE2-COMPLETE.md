# Handoff: Task 28.3 - Canary Phase 2 Complete

**Date:** 2025-12-11
**Status:** COMPLETE
**Session Focus:** Enable 100% planner traffic with QA gate validation

---

## Executive Summary

Phase 2 of the canary deployment is now complete. All 6 acceptance test scenarios pass (100%), exceeding the 90% gate requirement. The planner is now enabled at 100% traffic for all users.

---

## Bugs Fixed This Session

### Bug 1: Float-to-Decimal Conversion in Schema Cache

**File:** `lambda/schema_discovery/models.py`
**Lines:** 60-75, 85-88

**Problem:** DynamoDB doesn't support Python float types. The `relevance_score` field in `FieldSchema` was being stored as a float, causing all schema cache writes to fail with error:
```
Float types are not supported. Use Decimal types instead.
```

**Fix:** Convert floats to Decimal in `to_dict()` and back to float in `from_dict()`:
```python
# to_dict()
if self.relevance_score is not None:
    result['relevance_score'] = Decimal(str(self.relevance_score))

# from_dict()
relevance_score = data.get('relevance_score')
if relevance_score is not None:
    relevance_score = float(relevance_score)
```

**Result:** Schema cache now properly stores all 9 objects (was 1, now 9).

---

### Bug 2: Aggregation Queries Blocked by Graph Filter Short-Circuit

**File:** `lambda/retrieve/index.py`
**Lines:** 2372-2390

**Problem:** When graph filter returned 0 results, the code short-circuited to empty result BEFORE the aggregation routing could be reached. Vacancy queries like "Show me properties with high vacancy" were failing because:
1. Schema decomposer added numeric filter: `TotalAvailableArea > 0`
2. Graph nodes don't have this attribute
3. Graph filter returned 0 results
4. Code short-circuited, never reached vacancy_view routing

**Fix:** Added check to bypass short-circuit for aggregation queries:
```python
# Check if this is an aggregation query that should bypass short-circuit
query_lower = request_payload["query"].lower()
is_aggregation = any(kw in query_lower for kw in AGGREGATION_KEYWORDS)

if cross_object_also_failed:
    # ... existing fallback logic
elif is_aggregation:
    # Aggregation queries should bypass short-circuit and use derived views
    LOGGER.info(
        f"Graph filter returned zero matches, but aggregation query detected - "
        f"bypassing short-circuit for derived view routing"
    )
    graph_filter_candidate_ids = None  # Allow aggregation routing to proceed
else:
    # ... existing short-circuit logic
```

**Result:** Vacancy queries now correctly route to `vacancy_view` derived table.

---

## Deployment Summary

| Component | Action | Status |
|-----------|--------|--------|
| schema_discovery Lambda | Deployed with Decimal fix | Deployed |
| retrieve Lambda | Deployed with aggregation bypass | Deployed |
| chunking Lambda | Deployed (Task 44) | Deployed |
| Schema Cache | Re-populated (9 objects) | Live |
| PLANNER_TRAFFIC_PERCENT | Set to 100% | Live |

---

## Acceptance Test Results

| Scenario | Query | Citations | Status |
|----------|-------|-----------|--------|
| S1 | Class A office properties in Plano | 3 | PASS |
| S3 | Class A office with vacancy >0 | 5 | PASS |
| S4 | Leases expiring in 6 months | 5 | PASS |
| S7 | Recent sales | 3 | PASS |
| S9 | Properties with high vacancy | 5 | PASS |
| S10 | Properties in Texas | 5 | PASS |

**Total: 6/6 (100%)** - Gate PASSED (requirement: ≥90%)

---

## Configuration Changes

```bash
# Lambda Environment Variables
PLANNER_TRAFFIC_PERCENT=100  # Was 20, now 100
PLANNER_ENABLED=true
PLANNER_SHADOW_MODE=false
PLANNER_MIN_CONFIDENCE=0.3
PLANNER_TIMEOUT_MS=6000
```

---

## Files Modified

| File | Change |
|------|--------|
| `lambda/schema_discovery/models.py` | Float→Decimal conversion for DynamoDB |
| `lambda/retrieve/index.py` | Aggregation bypass for graph filter short-circuit |

---

## Rollback Procedure

If issues arise, rollback to 20% traffic:
```bash
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --environment "Variables={...,PLANNER_TRAFFIC_PERCENT=20,...}" \
  --region us-west-2
```

---

## Next Steps

| Task | Description | Priority |
|------|-------------|----------|
| Task 39 | Schema drift monitoring dashboard | P3 |
| Task 31 | Final documentation + cleanup | P3 |
| Task 4 (Step 4) | Reindex Deal/Listing/Inquiry for broker edges | Deferred |

---

## Test Commands

### Verify Phase 2 Configuration
```bash
aws lambda get-function-configuration --function-name salesforce-ai-search-retrieve \
  --region us-west-2 --query 'Environment.Variables.PLANNER_TRAFFIC_PERCENT'
```

### Test Vacancy Query
```bash
curl -s -X POST 'https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: <API_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{"query": "Show me properties with high vacancy", "salesforceUserId": "005dl00000Q6a3RAAR"}'
```

### Check Lambda Logs for Aggregation Routing
```bash
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 5m --region us-west-2 \
  | grep -E "(AGGREGATION|vacancy_view|bypassing short-circuit)"
```

---

## Related Files

| File | Purpose |
|------|---------|
| `lambda/retrieve/index.py` | Main retrieve handler with aggregation fix |
| `lambda/schema_discovery/models.py` | Schema models with Decimal fix |
| `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md` | Task tracking |
