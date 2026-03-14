# Handoff: Aggregation Routing & Planner Enablement - COMPLETE

**Date:** 2025-12-06
**Priority:** RESOLVED
**Status:** AGGREGATION ROUTING OPERATIONAL, PLANNER AT 20%

---

## Summary

Aggregation query routing is now operational. Queries for vacancy, leases, activities, and sales are routed to DynamoDB derived views instead of Bedrock KB. Planner is enabled at 20% traffic for canary testing.

---

## Accomplishments

### 1. Aggregation Routing Integrated into index.py

**Files Modified:** `lambda/retrieve/index.py`

Added aggregation routing that:
- Detects aggregation queries via keyword matching (`vacancy`, `lease`, `expiring`, `activity`, etc.)
- Routes to appropriate DynamoDB derived view
- Skips disambiguation for aggregation queries
- Converts derived view results to match format for downstream processing

**Key Code Additions:**
- Lines 272-293: `AGGREGATION_ROUTING_ENABLED`, `AGGREGATION_OBJECTS`, `AGGREGATION_KEYWORDS`
- Lines 1082-1169: Helper functions `_get_sobject_for_view()`, `_format_aggregation_content()`
- Lines 2115-2131: Early aggregation detection to skip disambiguation
- Lines 2787-2929: Main aggregation routing logic

### 2. IAM Permissions Fixed

Added two inline policies to Lambda role `SalesforceAISearch-Api-de-RetrieveLambdaRoleC96E78D-yBXueU3zF6C6`:

**DerivedViewsAccess:**
```json
{
  "Effect": "Allow",
  "Action": ["dynamodb:Scan", "dynamodb:Query", "dynamodb:GetItem", "dynamodb:BatchGetItem"],
  "Resource": [
    "arn:aws:dynamodb:us-west-2:382211616288:table/salesforce-ai-search-*-view",
    "arn:aws:dynamodb:us-west-2:382211616288:table/salesforce-ai-search-activities-agg"
  ]
}
```

**BedrockCrossRegionAccess:**
```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
  "Resource": ["arn:aws:bedrock:*::foundation-model/anthropic.claude-*"]
}
```

### 3. activities_agg Backfilled

- Queried 29 Tasks + 23 Events from Salesforce sandbox (`ascendix-beta-sandbox`)
- Aggregated by entity_id (WhatId/WhoId)
- Wrote 28 entity records to `salesforce-ai-search-activities-agg`
- Script: `/tmp/backfill_activities.py`

### 4. Planner Enabled at 20%

Updated Lambda environment variables:
```
PLANNER_SHADOW_MODE: "false"  (was "true")
PLANNER_TRAFFIC_PERCENT: "20" (was "0")
```

---

## Validation Results

### Test 1: Vacancy Query
```bash
Query: "show me properties with high vacancy rates"
Result: 5 matches from derived_view:vacancy_view
Aggregation: {"enabled": true, "viewUsed": "vacancy_view", "recordCount": 5, "timeMs": 60.96}
```

### Test 2: Lease Expiration Query
```bash
Query: "show me leases expiring in the next 6 months"
Result: 5 matches from derived_view:leases_view
End dates: 2025-12-29, 2026-02-10, 2026-04-03 (all within 6-month window)
Aggregation: {"enabled": true, "viewUsed": "leases_view", "recordCount": 5, "timeMs": 106.12}
```

### Test 3: Simple Query (Planner Skip)
```bash
Query: "find Class A properties in Dallas"
Result: Planner skipped (intent=FIELD_FILTER, confidence=0.70)
Routed directly to Bedrock KB
```

### Test 4: Complex Query (Planner Run)
```bash
Query: "which tenants have leases expiring at properties I manage"
Result: Planner ran (5307ms), confidence=0.35, has_traversal=true
Aggregation routing also triggered (leases_view)
```

---

## Known Issues / Remaining Challenges

### 1. DynamoDB Data Quality - vacancy_view

**Issue:** The vacancy_view table is missing actual vacancy metrics.

**Current Schema:**
```
property_id, name, city, state, property_class, updated_at
```

**Expected Schema:**
```
property_id, vacancy_pct, available_sqft, total_sqft, property_class, city, state
```

**Impact:** Vacancy queries return properties but can't filter by vacancy percentage.

**Fix Required:** Update backfill process to include `ascendix__TotalSqFt__c`, `ascendix__AvailableSqFt__c` from Property records.

### 2. Activity Date Window

**Issue:** All 52 Task/Event records have activity dates from mid-2025 (e.g., 2025-07-09).

**Impact:** `count_30d` and `count_90d` are 0 for all entities (relative to today 2025-12-06).

**Not a bug** - this is correct behavior given the data. Activities will count once new activities are created.

### 3. Planner Latency

**Issue:** Complex queries with planner take 5-7 seconds.

**Example:**
```
plannerMs: 5307.58
totalMs: 7008.23
```

**Cause:** Planner makes LLM calls which add latency.

**Mitigation:**
- Planner is only triggered for complex queries (simple queries skip it)
- 20% canary means most requests don't hit planner latency

### 4. Public Answer Function URL Deleted

The public Function URL was deleted as a security fix. Access is now only through:
- API Gateway (for testing)
- Direct Lambda invoke

---

## Current System State

| Component | Status | Details |
|-----------|--------|---------|
| Aggregation Routing | Working | vacancy_view, leases_view, activities_agg, sales_view |
| Planner | 20% Traffic | Shadow mode disabled, canary active |
| Derived Views (DynamoDB) | Populated | vacancy=2,466, leases=483, activities=28, availability=527 |
| Bedrock KB | Working | Fallback when aggregation returns 0 results |
| Answer Lambda | Working | Docker-based, streaming mode |

---

## Lambda Environment (salesforce-ai-search-retrieve)

```json
{
  "PLANNER_ENABLED": "true",
  "PLANNER_SHADOW_MODE": "false",
  "PLANNER_TRAFFIC_PERCENT": "20",
  "PLANNER_TIMEOUT_MS": "3000",
  "PLANNER_MIN_CONFIDENCE": "0.3",
  "AGGREGATION_ROUTING_ENABLED": "true" (default in code),
  "KNOWLEDGE_BASE_ID": "HOOACWECEX",
  "VACANCY_VIEW_TABLE": "salesforce-ai-search-vacancy-view",
  "LEASES_VIEW_TABLE": "salesforce-ai-search-leases-view",
  "ACTIVITIES_AGG_TABLE": "salesforce-ai-search-activities-agg"
}
```

---

## Next Steps

1. **Run Acceptance Scenarios:** Execute 20 acceptance test queries, measure pass rate
2. **Fix vacancy_view Data:** Backfill with actual vacancy metrics (sqft fields)
3. **Increase Planner Traffic:** If acceptance passes, ramp to 50%, then 100%
4. **Production Hardening:** Add API key auth to ingest Lambda, CloudWatch alarms

---

## Key Learnings

1. **Aggregation routing needs to happen before disambiguation** - Otherwise low-confidence queries return disambiguation UI instead of results.

2. **DynamoDB scan limits matter** - Date-filtered queries (like expiring leases) need larger initial scan limits to find matching records scattered across the table.

3. **Planner is designed for complex queries** - Simple field-filter queries correctly bypass the planner, which is expected behavior.

4. **IAM cross-region permissions** - Cross-region inference profiles require explicit `arn:aws:bedrock:*::foundation-model/*` permissions.
