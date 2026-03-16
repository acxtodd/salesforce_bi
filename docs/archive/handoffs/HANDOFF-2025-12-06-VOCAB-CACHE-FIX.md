# Handoff: Vocab Cache Fix & Phase 1 Canary Deployment

**Date:** 2025-12-06
**Session Focus:** Fix planner vocab cache integration (Task 28.1) and Phase 1 canary deployment (Task 28.2)

## Summary

Fixed the planner's vocab cache integration which was causing the `'NoneType' object has no attribute 'lookup'` error. Shadow logging is now working correctly with entity linking.

## Changes Made

### 1. VocabCache Import Added (`lambda/retrieve/index.py`)

Added VocabCache import and lazy-initialization singleton:
```python
# VocabCache for entity linking in Planner
try:
    from vocab_cache import VocabCache
    VOCAB_CACHE_AVAILABLE = True
    _vocab_cache_instance = None
    def get_vocab_cache() -> VocabCache:
        global _vocab_cache_instance
        if _vocab_cache_instance is None:
            _vocab_cache_instance = VocabCache()
        return _vocab_cache_instance
except ImportError as e:
    VOCAB_CACHE_AVAILABLE = False
```

### 2. Planner Initialization Fixed (2 locations)

Both planner initialization sites now pass vocab_cache:
```python
vocab_cache = get_vocab_cache() if VOCAB_CACHE_AVAILABLE and get_vocab_cache else None
planner = Planner(vocab_cache=vocab_cache, timeout_ms=PLANNER_TIMEOUT_MS)
```

Locations:
- Line ~2048: Disambiguation path shadow logging
- Line ~2366: Main planner path

### 3. Vocab Cache Seeded

Created `scripts/seed_vocab_cache.py` and populated `salesforce-ai-search-vocab-cache` table with 129 CRE terms:
- Object names and aliases (property, availability, lease, deal, etc.)
- Property types (office, industrial, retail, multifamily)
- Property classes (Class A, Class B, Class C)
- Deal stages (prospecting, negotiation, closed)
- Geographic terms (DFW, Austin, Plano, etc.)
- Field labels (size, sqft, vacancy, rent)

### 4. IAM Permissions Added

Added inline policy `VocabCacheAccess` to Lambda role:
```json
{
  "Effect": "Allow",
  "Action": ["dynamodb:Query", "dynamodb:GetItem", "dynamodb:Scan", "dynamodb:BatchGetItem"],
  "Resource": [
    "arn:aws:dynamodb:us-west-2:382211616288:table/salesforce-ai-search-vocab-cache",
    "arn:aws:dynamodb:us-west-2:382211616288:table/salesforce-ai-search-vocab-cache/index/*"
  ]
}
```

## Test Results

| Query | Predicates | Confidence | Time (ms) |
|-------|------------|------------|-----------|
| "find office buildings" | 1 | 0.31 | 649 |
| "Class A office properties in Plano" | 3 | 0.47 | 2690 |

Shadow logging now shows:
```
[SHADOW] Planner result: target=ascendix__Property__c, predicates=3, confidence=0.47
```

## Current State

- **Task 28.1 Shadow Logging:** ✅ COMPLETE - Working correctly
- **Task 28.2 Phase 1 (20%):** ⏳ PENDING
- **PLANNER_SHADOW_MODE:** `true`
- **PLANNER_ENABLED:** `true`

## Known Issues

### 1. Fuzzy Matching Performance
EntityLinker's fuzzy matching iterates over all vocab types × objects (30+ DynamoDB queries). Simple queries complete in ~650ms but complex queries take 2-3 seconds.

**Mitigation Options:**
- Increase timeout for complex queries
- Optimize fuzzy matching to use GSI lookups instead of table scans
- Add in-memory caching for vocab terms

### 2. Disambiguation Path Timeout
The first planner execution in disambiguation path always times out (500ms limit) because it runs before the Lambda is fully warm.

**Impact:** Low - main path still runs successfully

## Task 28.2: Phase 1 Canary Deployment

### Changes Made

1. **Added `PLANNER_TRAFFIC_PERCENT` env var** - Controls percentage of requests using planner results
2. **Added `random` import** - For percentage-based selection
3. **Added per-request canary decision** - `use_planner_for_request` variable
4. **Updated planner logic** - Shadow mode respects canary selection
5. **Added canary tracking** - `canary`, `canaryPercent` fields in query plan

### Current Configuration

```
PLANNER_ENABLED=true
PLANNER_SHADOW_MODE=true
PLANNER_TRAFFIC_PERCENT=20
PLANNER_MIN_CONFIDENCE=0.3
```

### Test Results

| Metric | Value |
|--------|-------|
| Planner predicates | 1 (for "office") |
| Planner confidence | 0.31 |
| Planner `wouldUse` | true |
| Shadow mode | Working |

### Known Limitation: Disambiguation Path

Most queries trigger **disambiguation** (confidence < 0.7 threshold), which returns early from retrieve Lambda. The disambiguation path runs planner in shadow mode only - it doesn't check `use_planner_for_request`.

**Impact:** Canary selection only affects queries that don't trigger disambiguation.

**Workarounds:**
1. Lower disambiguation threshold (not recommended - reduces UX)
2. Add canary logic to disambiguation path (future enhancement)
3. Use queries with higher schema confidence

## Next Steps

1. **Monitor canary metrics** - CloudWatch `ShadowPlannerLatency`, `ShadowPlannerConfidence`
2. **Increase traffic** - Raise `PLANNER_TRAFFIC_PERCENT` to 50%, then 100% for Task 28.3
3. **Performance optimization** - Consider increasing `PLANNER_TIMEOUT_MS` for complex queries
4. **CDK Stack Update** - Add vocab cache table permissions to CDK (currently inline policy)

## Files Modified

| File | Change |
|------|--------|
| `lambda/retrieve/index.py` | Added VocabCache import, fixed Planner init, added canary logic |
| `scripts/seed_vocab_cache.py` | NEW - Vocab cache seeder script (129 CRE terms) |

## Environment Variables Added

| Variable | Value | Description |
|----------|-------|-------------|
| `PLANNER_TRAFFIC_PERCENT` | 20 | Percentage of requests to use planner results |
| `PLANNER_MIN_CONFIDENCE` | 0.3 | Lowered from 0.5 to allow more planner usage |

## IAM Policies Added

| Policy | Role | Resource |
|--------|------|----------|
| `VocabCacheAccess` | `SalesforceAISearch-Api-de-RetrieveLambdaRoleC96E78D-*` | `salesforce-ai-search-vocab-cache` table + indexes |

## Verification Commands

```bash
# Check vocab cache has data
aws dynamodb scan --table-name salesforce-ai-search-vocab-cache --max-items 5

# Check planner logs
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 5m | grep -E "SHADOW|Planner|predicate"

# Test query
curl -X POST "https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer" \
  -H "x-api-key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "find office buildings", "salesforceUserId": "005dl00000Q6a3RAAR"}'
```
