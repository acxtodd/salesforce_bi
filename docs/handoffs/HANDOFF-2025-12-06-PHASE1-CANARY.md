# Handoff: Phase 1 Canary Deployment Complete

**Date:** 2025-12-06
**Tasks Completed:** 28.1 (Shadow Logging), 28.2 (Phase 1 - 20% Traffic)

---

## Accomplishments

### 1. Fixed Planner Vocab Cache Integration

**Problem:** Planner was failing with `'NoneType' object has no attribute 'lookup'`

**Root Cause:**
- VocabCache was not imported in retrieve Lambda
- Planner was initialized without vocab_cache parameter
- vocab_cache DynamoDB table was empty

**Solution:**
- Added VocabCache import with lazy singleton pattern
- Fixed Planner initialization in 2 locations (disambiguation + main path)
- Created `scripts/seed_vocab_cache.py` with 129 CRE terms
- Added IAM policy `VocabCacheAccess` to Lambda role

### 2. Deployed Phase 1 Canary Infrastructure

**New Environment Variables:**
| Variable | Value | Purpose |
|----------|-------|---------|
| `PLANNER_TRAFFIC_PERCENT` | 20 | % of requests using planner results |
| `PLANNER_MIN_CONFIDENCE` | 0.3 | Lowered threshold for canary testing |

**Code Changes:**
- Added `random` import for percentage selection
- Added `use_planner_for_request` per-request decision variable
- Updated shadow mode checks: `PLANNER_SHADOW_MODE and not use_planner_for_request`
- Added `canary`, `canaryPercent` tracking fields to query plan
- Added `[CANARY]` log prefix for canary requests

### 3. Verified Planner Entity Linking

**Test Query:** "find office buildings"

| Metric | Result |
|--------|--------|
| Target Object | `ascendix__Property__c` |
| Predicates | 1 (`office` → RecordType.Name) |
| Confidence | 0.31 |
| Would Use | `true` |
| Shadow Mode | Working |

---

## Challenges

### 1. Disambiguation Early Return

**Issue:** Most queries trigger disambiguation (confidence < 0.7 threshold), which returns HTTP 200 with disambiguation options before reaching the main canary path.

**Impact:** Canary selection logic only affects queries that don't trigger disambiguation.

**Current State:**
```
Query: "find office buildings"
→ Schema confidence: 0.5
→ Disambiguation threshold: 0.7
→ Triggers disambiguation (returns early)
→ Canary logic not reached
```

### 2. Planner Timeout in Disambiguation Path

**Issue:** First planner execution in disambiguation path times out (500ms) due to cold start overhead.

**Impact:** Low - main path still succeeds with ~550-650ms execution time.

### 3. Entity Linker Performance

**Issue:** Fuzzy matching in EntityLinker iterates over many DynamoDB queries (30+ for fuzzy matching), causing 2-3 second latency for complex queries.

**Mitigation:** Simple queries complete in ~550ms, which is acceptable for Phase 1.

---

## Open Items

### High Priority

1. **Task 28.3: Phase 2 (100% Traffic)**
   - Increase `PLANNER_TRAFFIC_PERCENT` to 100
   - Monitor error rates and latency
   - Validate structured filters improve precision

2. **Disambiguation Path Canary**
   - Add `use_planner_for_request` logic to disambiguation path
   - Would enable canary testing for all queries, not just high-confidence ones

### Medium Priority

3. **CDK Stack Update**
   - Add vocab cache table permissions to CDK stack
   - Currently using inline IAM policy (works but not infrastructure-as-code)

4. **Schema Cache Population**
   - Schema cache table is empty (`salesforce-ai-search-schema-cache`)
   - Should be populated from Salesforce Describe API
   - Would improve schema decomposition confidence

### Low Priority

5. **Entity Linker Optimization**
   - Add in-memory caching for vocab terms
   - Optimize fuzzy matching to use GSI instead of table scans
   - Target: reduce complex query latency from 2-3s to <1s

6. **Planner Timeout Tuning**
   - Consider increasing `PLANNER_TIMEOUT_MS` for complex queries
   - Current 500ms is tight for cold starts

---

## Current Configuration

```bash
# Retrieve Lambda Environment
PLANNER_ENABLED=true
PLANNER_SHADOW_MODE=true
PLANNER_TRAFFIC_PERCENT=20
PLANNER_MIN_CONFIDENCE=0.3
PLANNER_TIMEOUT_MS=500  # default
```

---

## Verification Commands

```bash
# Check vocab cache has data
aws dynamodb scan --table-name salesforce-ai-search-vocab-cache --max-items 5 --region us-west-2

# Check planner env vars
aws lambda get-function-configuration --function-name salesforce-ai-search-retrieve --region us-west-2 | grep PLANNER

# Test retrieve Lambda directly
aws lambda invoke --function-name salesforce-ai-search-retrieve --region us-west-2 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"httpMethod":"POST","path":"/retrieve","body":"{\"query\":\"find office\",\"salesforceUserId\":\"005dl00000Q6a3RAAR\",\"filters\":{}}","headers":{"content-type":"application/json"}}' \
  /tmp/response.json && cat /tmp/response.json | python3 -m json.tool

# Check planner logs
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 5m --region us-west-2 | grep -E "SHADOW|CANARY|planner"
```

---

## Files Modified This Session

| File | Change |
|------|--------|
| `lambda/retrieve/index.py` | VocabCache import, Planner init fix, canary logic (~50 lines) |
| `scripts/seed_vocab_cache.py` | NEW - 129 CRE vocabulary terms |
| `docs/handoffs/HANDOFF-2025-12-06-VOCAB-CACHE-FIX.md` | Initial handoff doc |
| `docs/handoffs/HANDOFF-2025-12-06-PHASE1-CANARY.md` | This document |

---

## Metrics to Monitor

| Metric | Location | Target |
|--------|----------|--------|
| `ShadowPlannerLatency` | CloudWatch | p95 < 500ms |
| `ShadowPlannerConfidence` | CloudWatch | avg > 0.3 |
| `PlannerFallbackRate` | CloudWatch | < 30% |
| Planner `wouldUse=true` rate | Logs | > 50% |

---

## Quick Reference

**To increase canary traffic:**
```bash
# Update to 50%
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --environment "Variables={...,PLANNER_TRAFFIC_PERCENT=50}" \
  --region us-west-2
```

**To disable canary (shadow only):**
```bash
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --environment "Variables={...,PLANNER_TRAFFIC_PERCENT=0}" \
  --region us-west-2
```

**To enable full planner (no shadow):**
```bash
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --environment "Variables={...,PLANNER_SHADOW_MODE=false}" \
  --region us-west-2
```
