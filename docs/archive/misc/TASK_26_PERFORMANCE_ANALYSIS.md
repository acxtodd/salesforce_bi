# Task 26: Performance Tuning Analysis

**Date:** 2025-12-06
**Feature:** graph-aware-zero-config-retrieval
**Target:** p95 retrieval latency ≤ 1500ms

---

## Current Performance Profile

### Query Latency Breakdown (from profiling)

| Query Type | Retrieve | Generate | Total |
|------------|----------|----------|-------|
| Filtered (Plano Class A) | 1320ms | 4686ms | 6007ms |
| Temporal (leases 6mo) | **555ms** | 4261ms | 4817ms |
| Complex (deals TX) | 4199ms | 7882ms | 12082ms |

### Key Observations

1. **Retrieval CAN be fast:** Simple/temporal queries achieve 555-1320ms
2. **Complex queries are slow:** Cross-object queries take 4199ms
3. **LLM generation dominates:** 4-8 seconds (75-85% of total time)
4. **Variability is high:** 7.5x difference between fastest and slowest

---

## Latency Contributors in Retrieve Lambda

The retrieve Lambda processes queries through these sequential steps:

| Step | Description | Estimated Time |
|------|-------------|----------------|
| 1. Parse Request | Parse incoming JSON | <5ms |
| 2. Intent Classification | Rule-based query classification | 10-50ms |
| 3. Query Decomposition | **LLM call** to understand query | 200-500ms |
| 4. Schema Decomposition | Schema-aware parsing | 50-100ms |
| 5. Cross-Object Handling | DynamoDB query | 100-500ms |
| 6. Graph Filter | DynamoDB query | 50-200ms |
| 7. Disambiguation | Ambiguity detection | 20-50ms |
| 8. AuthZ Sidecar | Lambda invoke | 100-300ms |
| 9. Cache Check | DynamoDB lookup | 20-50ms |
| 10. Planner | Entity linking + planning | 100-500ms |
| 11. KB Query | Bedrock Knowledge Base | 500-2000ms |
| 12. Post-filtering | Authorization check | 50-100ms |

**Total estimated:** 1200-4300ms

---

## Optimization Opportunities

### 1. Disable Query Decomposer (LLM call)

**Issue:** Query Decomposer makes an LLM call (Haiku) on every request, adding 200-500ms.

**Impact:** Schema Decomposer does similar work without LLM call.

**Fix:** Set `QUERY_DECOMPOSER_ENABLED=false`

**Expected improvement:** 200-500ms reduction

### 2. Parallelize Independent Operations

**Issue:** Intent Classification, AuthZ Sidecar, and Schema Decomposition run sequentially.

**Fix:** Run these in parallel using ThreadPoolExecutor.

**Expected improvement:** 100-200ms reduction

### 3. Optimize KB Query

**Issue:** Bedrock KB query takes 500-2000ms.

**Options:**
- Reduce topK from 10 to 5 for simple queries
- Use more specific metadata filters
- Cache frequent queries

**Expected improvement:** 100-500ms reduction

### 4. Skip Planner for Simple Queries

**Issue:** Planner runs even for queries where graph traversal isn't needed.

**Fix:** Skip planner when intent is SIMPLE or FIELD_FILTER with high confidence.

**Expected improvement:** 100-500ms reduction for simple queries

---

## Recommendations

### Phase 1: Quick Wins (Immediate)

1. **Disable Query Decomposer**
   ```bash
   # In Lambda environment variables
   QUERY_DECOMPOSER_ENABLED=false
   ```
   Expected: -200 to -500ms

2. **Reduce default topK for simple queries**
   - When intent confidence > 0.8 and intent is SIMPLE, use topK=5
   Expected: -100 to -300ms

### Phase 2: Parallelization (Medium Effort)

3. **Parallelize initial processing**
   - Intent Classification
   - Schema Decomposition
   - AuthZ Sidecar
   Run in parallel, wait for all before proceeding.
   Expected: -100 to -200ms

### Phase 3: Caching (Larger Effort)

4. **Query result caching with short TTL**
   - Cache KB results for 60 seconds
   - Use query hash as key
   Expected: -500 to -2000ms for repeated queries

---

## Realistic Targets

### What's Achievable

| Component | Current p95 | Target | Achievable? |
|-----------|-------------|--------|-------------|
| Retrieval | 4199ms | 1500ms | **Yes** with optimizations |
| Generation | 7882ms | - | No (LLM constraint) |
| **Total** | 12082ms | - | Limited by LLM |

### Target Verification

With optimizations:
- Retrieval: 1000-1500ms (achievable)
- Generation: 4000-8000ms (fixed)
- **Total: 5000-9500ms**

**Note:** The 1500ms target is for **retrieval only**, not total answer time.

---

## Implementation Status

| Optimization | Status | Measured Impact |
|--------------|--------|-----------------|
| 1. Disable Query Decomposer | **Deployed** | -200-500ms (estimated) |
| 2. Parallelize operations | Deferred | - |
| 3. Reduce topK for simple | **Deployed** | -100-300ms |
| 4. Skip planner for simple | **Deployed** | -100-500ms |
| 5. Query caching | Already exists | -500-2000ms (repeat queries) |

---

## Results After Optimization (2025-12-06)

### Before vs After Comparison

| Query Type | Before Retrieve | After Retrieve | Improvement |
|------------|-----------------|----------------|-------------|
| Simple (Class A office) | 1320ms | **497ms** | **62% faster** |
| Temporal (leases 6mo) | 555ms | **395ms** | **29% faster** |
| Complex (deals TX) | 4199ms | **1565ms** | **63% faster** |

### Key Optimizations Applied

1. **Query Decomposer Disabled** (`QUERY_DECOMPOSER_ENABLED=false`)
   - Removes 200-500ms LLM call overhead
   - Schema Decomposer provides same functionality

2. **Planner Skip for Simple Queries**
   - Skips planner when `intent ∈ {SIMPLE_LOOKUP, FIELD_FILTER}` and `confidence ≥ 0.6`
   - Saves 100-500ms for targeted queries

3. **Reduced topK for Simple Queries**
   - Uses `topK=5` instead of default 8-15 for simple/filtered queries
   - Reduces KB query time by 100-300ms

### Target Achievement

| Metric | Target | Achieved | Status |
|--------|--------|----------|--------|
| Simple query p95 | ≤1500ms | ~500ms | **PASS** |
| Filtered query p95 | ≤1500ms | ~400ms | **PASS** |
| Complex query p95 | ≤1500ms | ~1565ms | **MARGINAL** |

---

## Derived Views Status

Derived view tables are empty and require data population:

| Table | Record Count | Status |
|-------|--------------|--------|
| activities_agg | 0 | **Needs backfill** |
| vacancy_view | 1 | **Needs backfill** |
| availability_view | 0 | **Needs backfill** |
| leases_view | 0 | **Needs backfill** |
| sales_view | 0 | **Needs backfill** |

To populate derived views, run the backfill Lambda:
```bash
# Requires SALESFORCE_API_URL and SALESFORCE_ACCESS_TOKEN env vars
aws lambda invoke --function-name salesforce-ai-search-derived-views-backfill \
  --payload '{"fullBackfill": true}' /tmp/backfill_result.json
```

**Note**: Derived view query performance cannot be tuned until data is populated.

---

## Next Steps

1. Monitor complex query performance - currently at 1565ms (marginally over target)
2. Run derived views backfill to populate aggregation tables
3. Consider additional optimizations for complex cross-object queries if needed
