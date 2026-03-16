# Handoff: Task 29.6 - Latency Optimization Complete

**Date:** 2025-12-12
**Status:** COMPLETE
**Session Focus:** Reduce retrieve p95 latency from 9.5s to under 5s target

---

## Executive Summary

Task 29.6 (short-term latency optimization) is complete. Retrieve p95 dropped from **9,526ms to 2,209ms** (4.3x improvement), well under the 5,000ms target. The primary fix was adding in-memory caching to SchemaCache and fixing broken import paths that caused each request to scan DynamoDB.

---

## Performance Results

| Metric | Before | After | Target | Status |
|--------|--------|-------|--------|--------|
| **Retrieve P95** | 9,526ms | **2,209ms** | ≤5,000ms | PASS |
| Retrieve Avg | ~5,000ms | 1,831ms | - | - |
| Retrieve Min | - | 1,581ms | - | - |
| Planner P95 | 519ms | ~500ms | ≤500ms | PASS |

---

## Root Cause Analysis

### Primary Bottleneck: SchemaCache.get_all() DynamoDB Scan

Each request was triggering a full DynamoDB table scan (~2.5s) because:

1. **Broken import path** in `index.py`:
   ```python
   # BROKEN - was looking in ../schema_discovery which doesn't exist
   sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'schema_discovery'))
   from cache import SchemaCache  # Failed with "No module named 'cache'"
   ```

2. **Multiple SchemaCache instances**: Each component (`SchemaAwareDecomposer`, `DynamicIntentRouter`) created its own `SchemaCache()` instance, none benefiting from caching.

3. **No in-memory caching**: Every `get_all()` call scanned DynamoDB, even for the same data.

---

## Fixes Applied

### Fix 1: Corrected SchemaCache Import Path

**File:** `lambda/retrieve/index.py`
**Lines:** 175-177

```python
# BEFORE (broken)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'schema_discovery'))
from cache import SchemaCache

# AFTER (working)
from schema_discovery.cache import SchemaCache
```

---

### Fix 2: Added In-Memory Caching to SchemaCache

**File:** `lambda/retrieve/schema_discovery/cache.py`

Added TTL-based in-memory cache (5 minutes default) for both individual and bulk lookups:

```python
# New instance variables
self._memory_cache: Dict[str, Tuple[ObjectSchema, float]] = {}
self._all_schemas_cache: Optional[Tuple[Dict[str, ObjectSchema], float]] = None
self._memory_cache_ttl = memory_cache_ttl_seconds  # Default: 300s

def _is_memory_cache_valid(self, timestamp: float) -> bool:
    return (time.time() - timestamp) < self._memory_cache_ttl

def get(self, sobject: str) -> Optional[ObjectSchema]:
    # Check memory cache first
    if sobject in self._memory_cache:
        schema, timestamp = self._memory_cache[sobject]
        if self._is_memory_cache_valid(timestamp):
            return schema  # 0.0ms vs ~30ms DynamoDB
    # ... DynamoDB fallback, then cache result

def get_all(self) -> Dict[str, ObjectSchema]:
    # Check memory cache first
    if self._all_schemas_cache is not None:
        schemas, timestamp = self._all_schemas_cache
        if self._is_memory_cache_valid(timestamp):
            return schemas  # 0.0ms vs ~180ms DynamoDB scan
    # ... DynamoDB fallback, then cache result
```

---

### Fix 3: Module-Level SchemaCache Singleton

**File:** `lambda/retrieve/dynamic_intent_router.py`
**Lines:** 49-76

Created a module-level singleton so all components share the same cached instance:

```python
_module_schema_cache = None

def _get_module_schema_cache():
    """Module-level singleton for memory caching across Lambda lifetime."""
    global _module_schema_cache
    if _module_schema_cache is not None:
        return _module_schema_cache

    from schema_discovery.cache import SchemaCache
    _module_schema_cache = SchemaCache()
    return _module_schema_cache
```

---

### Fix 4: Pass Schema Cache to SchemaAwareDecomposer

**File:** `lambda/retrieve/index.py`
**Lines:** 2259-2261

```python
# BEFORE - created new SchemaCache each time
schema_decomposer = SchemaAwareDecomposer()

# AFTER - uses module-level singleton
schema_cache = get_schema_cache() if SCHEMA_CACHE_AVAILABLE else None
schema_decomposer = SchemaAwareDecomposer(schema_cache=schema_cache)
```

---

## Remaining Latency Breakdown

The remaining ~1.7-2.2s per request is expected:

| Component | Time | Notes |
|-----------|------|-------|
| LLM Call (Bedrock) | ~1.5s | Claude Haiku 4.5 query decomposition |
| Graph Filter | ~120ms | DynamoDB query for candidates |
| KB Search | ~100ms | Bedrock KB vector search |
| Other | ~100ms | Intent detection, auth, serialization |

The LLM latency is unavoidable without query result caching (which exists at a higher layer).

---

## Configuration Notes

### Schema Memory Cache TTL

- **Default:** 5 minutes (300 seconds)
- **Environment variable:** `SCHEMA_MEMORY_CACHE_TTL`
- **Implication:** Schema changes (from discovery Lambda) may take up to 5 minutes to propagate to retrieve Lambda

### LLM Model for Query Decomposition

- **Model:** Claude Haiku 4.5
- **Model ID:** `us.anthropic.claude-haiku-4-5-20251001-v1:0`
- **Environment variable:** `DECOMPOSER_MODEL_ID`
- **Location:** `lambda/retrieve/schema_decomposer.py:219-220`

---

## Files Modified

| File | Change |
|------|--------|
| `lambda/retrieve/schema_discovery/cache.py` | Added `_memory_cache`, `_all_schemas_cache` with 5-min TTL |
| `lambda/retrieve/index.py` | Fixed import path, use module-level singleton for SchemaAwareDecomposer |
| `lambda/retrieve/dynamic_intent_router.py` | Added `_get_module_schema_cache()` singleton |
| `lambda/retrieve/entity_linker.py` | Removed profiling code (cleanup) |

---

## Testing Performed

### Latency Benchmark (10 requests)

```
Request 1: 2177ms
Request 2: 1655ms
Request 3: 2209ms
Request 4: 1886ms
Request 5: 1697ms
Request 6: 1653ms
Request 7: 1581ms
Request 8: 2099ms
Request 9: 1740ms
Request 10: 1612ms

P95: 2209ms (target: ≤5000ms) - PASS
```

### Memory Cache Verification

CloudWatch logs confirm memory cache hits:
```
Memory cache hit for ascendix__Property__c (0.0ms)
Memory cache hit for get_all: 9 schemas (0.0ms)
```

---

## Cautions for Future Work

1. **Schema Cache Staleness**: The 5-minute in-memory TTL means schema updates (from discovery Lambda) can be stale for up to 5 minutes. If immediate propagation is needed, add an explicit invalidation hook after schema discovery completes.

2. **Vocab Cache Not Added**: The entity_linker's `_fuzzy_match_term()` still iterates 77 vocab_type/object combinations. If latency regresses under heavier term loads, consider adding similar in-memory caching to `VocabCache.get_terms()`.

3. **Lambda Cold Starts**: First request after cold start will still hit DynamoDB to populate the memory cache. Consider provisioned concurrency if cold start latency becomes an issue.

---

## Task Status Update

### Task 29 - Final Checkpoint

| Sub-task | Status |
|----------|--------|
| 29.1 Acceptance tests | PASS (6/6) |
| 29.2 Latency SLOs | PASS (p95: 2.2s) |
| 29.3 Security review | PASS |
| 29.4 Quality metrics | PASS |
| 29.5 Documentation | Pending (Task 31) |
| **29.6 Latency optimization** | **COMPLETE** |

Task 29 is now effectively complete. Remaining work:
- Task 31: Final documentation (P3)
- Task 39: Schema drift monitoring (P3)

---

## Quick Reference Commands

```bash
# Check retrieve latency
aws lambda invoke --function-name salesforce-ai-search-retrieve \
  --payload '{"query": "class a office in plano", "salesforceUserId": "005dl00000Q6a3RAAR"}' \
  --cli-binary-format raw-in-base64-out --region us-west-2 /tmp/test.json

# Check memory cache hits in logs
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 5m --format short | grep "Memory cache"

# Deploy retrieve Lambda
cd lambda/retrieve && zip -r /tmp/retrieve.zip . -x "test_*" -x "__pycache__/*" && \
aws lambda update-function-code --function-name salesforce-ai-search-retrieve \
  --zip-file fileb:///tmp/retrieve.zip --region us-west-2
```

---

## Session End State

- **Retrieve p95:** 2,209ms (target: ≤5,000ms) - PASS
- **All acceptance tests:** 6/6 passing
- **Planner traffic:** 100%
- **Schema cache:** 9 objects with in-memory caching
- **Memory cache TTL:** 5 minutes
- **LLM model:** Claude Haiku 4.5
