# Handoff: Signal Harvesting Specification Complete

**Date:** 2025-12-10
**Session:** Signal Harvesting Tasks & Spec Alignment
**Status:** Specification Complete, Implementation Ready

---

## Executive Summary

This session promoted Signal Harvesting from R&D to v1.1 implementation. The PRD (`docs/analysis/AUGMENTED_SCHEMA_DISCOVERY_PRD.md`) was converted into formal requirements, design specifications, and implementation tasks. QA pass rate remains at 40% (4/10); signal harvesting is expected to improve this to 60-70%.

---

## Accomplished This Session

### 1. Tasks Added to `tasks.md`

| Task | Description | Priority | Status |
|------|-------------|----------|--------|
| **Task 40** | Signal Harvesting - Saved Searches | P1 | Ready |
| **Task 41** | Schema Cache Relevance Scoring | P2 | Ready |
| **Task 42** | Planner Relevance Integration | P2 | Ready |
| **Task 43** | Vocab Cache Auto-Seeding | P1 | Ready |

### 2. Requirements Added to `requirements.md`

| Requirement | Title | Status |
|-------------|-------|--------|
| **Req 24** | Signal Harvesting from Saved Searches | NEW |
| **Req 25** | Signal Harvesting from ListViews/SearchLayouts | NEW |
| **Req 26** | Relevance Scoring Infrastructure | NEW |
| **Req 27** | Planner Relevance-Based Disambiguation | NEW |
| **Req 18.4** | Updated to mark "Promoted to v1.1" | MODIFIED |

### 3. Design Added to `design.md`

- **Signal Harvesting Architecture** - Mermaid diagram showing signal flow
- **SignalHarvester Component** - Full interface specification
- **TemplateParser** - Saved Search JSON parsing logic
- **ScoreAggregator** - Multi-source score normalization
- **Updated Schema Cache Structure** - With `relevance_score`, `usage_context`, `source_signals`
- **R&D Appendix** - Updated to remove promoted items

### 4. CDK Deploy Completed

```
SalesforceAISearch-Api-dev deployed successfully
- AnswerFunctionUrl: https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/
- ApiEndpoint: https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/
- SchemaApiEndpoint: https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/schema
```

---

## Current State

### QA Pass Rate: 4/10 (40%)

| # | Scenario | Status | Issue |
|---|----------|--------|-------|
| 1 | Class A office Plano | **PASS** | 3 citations |
| 2 | Industrial Miami 20-50k | FAIL | Numeric range filter |
| 3 | Downtown vacancy >0 | **PASS** | 15 citations |
| 4 | Leases expiring 6mo | **PASS** | 5 citations |
| 5 | Activities 123 Main | FAIL | Entity resolution |
| 6 | Contacts 5+ activities | FAIL | COUNT aggregation |
| 7 | Sales recent | **PASS** | 3 citations |
| 8 | Companies 10+ retail | PARTIAL | 30 matches, 0 citations |
| 9 | Properties vacancy >25% | FAIL | Percentage filter |
| 10 | Notes HVAC | FAIL | Note object not indexed |

### Expected Impact from Signal Harvesting

| Task | Expected Improvement | Target Scenarios |
|------|---------------------|------------------|
| Task 40 (Saved Searches) | +10-20% | 5, 8, 9 |
| Task 43 (Vocab Seeding) | +10% | 5 (entity resolution) |
| Task 41+42 (Relevance) | +5-10% | 2, 8, 9 (disambiguation) |

**Projected QA after Tasks 40-43:** 6-7/10 (60-70%)

---

## Files Modified This Session

| File | Change |
|------|--------|
| `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md` | Added Tasks 40-43, updated sprint table |
| `.kiro/specs/graph-aware-zero-config-retrieval/requirements.md` | Added Requirements 24-27, updated Req 18.4 |
| `.kiro/specs/graph-aware-zero-config-retrieval/design.md` | Added Signal Harvesting section, updated R&D Appendix |

---

## What Remains

### Immediate (P1 - Start Here)

1. **Task 40: Signal Harvesting - Saved Searches**
   - Create `lambda/schema_discovery/signal_harvester.py`
   - Query `ascendix_search__Search__c`
   - Parse template JSON
   - Extract filter fields, result columns, relationships
   - Seed vocab cache with filter values

2. **Task 43: Vocab Cache Auto-Seeding**
   - Extract vocab from saved search filter values
   - Extract property names from graph nodes
   - Update EntityLinker to use seeded vocab

### Next (P2)

3. **Task 41: Schema Cache Relevance Scoring**
   - Add `relevance_score` to FieldSchema
   - Update DynamoDB schema structure
   - Backward compatible changes

4. **Task 42: Planner Relevance Integration**
   - Update EntityLinker to prefer high-score fields
   - Update TraversalPlanner for primary relationships

### Later (P3)

5. **Task 28.3: Canary Phase 2 (100% traffic)** - After QA ≥90%
6. **Task 39: Schema Drift Monitoring Dashboard**
7. **Task 31: Final Documentation**

---

## Recommended Next Steps

### Option A: Implement Task 40 (Recommended)

```bash
# 1. Create signal_harvester.py
# 2. Query saved searches from SF
# 3. Parse templates
# 4. Update schema cache with relevance scores
# 5. Run QA to measure improvement
```

**Expected Duration:** 2-4 hours
**Expected QA Impact:** +10-20%

### Option B: Quick Win - Vocab Seeding Only

Focus only on Task 43 to fix entity resolution (Scenario 5):

```bash
# 1. Extract property names from graph_nodes table
# 2. Seed vocab cache with entity names
# 3. Test "123 Main Street" entity resolution
```

**Expected Duration:** 1-2 hours
**Expected QA Impact:** +10% (Scenario 5 fix)

---

## Key Documents

| Document | Purpose |
|----------|---------|
| `docs/analysis/AUGMENTED_SCHEMA_DISCOVERY_PRD.md` | Original PRD with signal sources and scoring |
| `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md` | Implementation tasks (40-43) |
| `.kiro/specs/graph-aware-zero-config-retrieval/requirements.md` | Requirements 24-27 |
| `.kiro/specs/graph-aware-zero-config-retrieval/design.md` | Signal Harvester architecture |

---

## Verification Commands

```bash
# Check current QA pass rate
for i in {1..10}; do
  curl -s -X POST 'https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer' \
    -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
    -H 'Content-Type: application/json' \
    -d "{\"query\": \"$QUERY\", \"salesforceUserId\": \"005dl00000Q6a3RAAR\", \"debug\": true}" \
    > /tmp/qa$i.txt
done

# Check saved searches in SF (for Task 40)
sf data query --query "SELECT Name, ascendix_search__Template__c, ascendix_search__SObjectType__c FROM ascendix_search__Search__c WHERE ascendix_search__IsActive__c = true" --target-org ascendix-beta-sandbox

# Check vocab cache entries
aws dynamodb scan --table-name salesforce-ai-search-vocab-cache \
  --region us-west-2 --max-items 10
```

---

## Notes

1. **Graceful Degradation:** If Ascendix Search package is not installed, Signal Harvester returns empty results and base Schema Discovery continues normally.

2. **Score Normalization:** All relevance scores are normalized to 0-10 scale regardless of source. This allows consistent disambiguation across different signal sources.

3. **Backward Compatibility:** New schema cache fields (`relevance_score`, `usage_context`, `source_signals`) are optional. Existing entries without these fields will use defaults.
