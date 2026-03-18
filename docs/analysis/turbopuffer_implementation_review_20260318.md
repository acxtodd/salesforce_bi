# Turbopuffer Implementation Review

**Date:** 2026-03-18
**Reference docs:** `docs/turbopuffer/` (agent cheatsheet, search capabilities, how-tos, performance-and-ops, SDK examples)
**Code reviewed:** `lib/turbopuffer_backend.py`, `lambda/cdc_sync/.bundle/lib/denormalize.py` (schema), `lambda/query/` (query Lambda)
**Method:** Cross-reference official Turbopuffer guidance against current implementation

---

## 1. Alignment — What We're Doing Right

### Hybrid search via multi_query + RRF

The recent fix (`2731e26`) correctly replaced the broken `Sum(BM25, ANN)` single-query with `multi_query` + client-side Reciprocal Rank Fusion. This matches the official guidance exactly:

> "Hybrid orchestration is expected to live in your app layer. Official guidance explicitly recommends keeping search logic in your own search.py, using turbopuffer for initial retrieval, then applying rank fusion and optional reranking outside the database."

Implementation: `turbopuffer_backend.py:163-211` — `_hybrid_search()` runs BM25 and ANN as two subqueries in one `multi_query` call, then fuses with RRF (k=60).

### Namespace-per-org

We use `org_{sf_org_id}` as the namespace key. This follows the "keep namespaces as small as practical without forcing routine multi-namespace fanout" guidance. One namespace per Salesforce org is the natural partition key for this multi-tenant architecture.

### BM25 with schema declaration

`FULL_TEXT_SEARCH_SCHEMA` declares `"text": {"type": "string", "full_text_search": True}`. Correct — BM25 must be enabled in schema.

### Single client reuse

`TurbopufferBackend.__init__` creates one `Turbopuffer(region=...)` client instance. The docs recommend this to avoid repeated TCP/TLS handshakes.

### Strong consistency (default)

We don't override to eventual consistency. The docs say strong consistency is the right choice for interactive agent systems where fresh writes must be visible immediately — which matches our CDC sync use case.

---

## 2. Issues Identified

### TPUF-1: Tokenizer Not Pinned in Schema

**Current:** `"text": {"type": "string", "full_text_search": True}`

**Docs say:** "turbopuffer may upgrade the default tokenizer over time. Pin the tokenizer in schema if behavior stability matters."

**Risk:** A Turbopuffer-side tokenizer upgrade could silently change BM25 ranking behavior in production. Our acceptance tests and query quality are calibrated against the current tokenizer.

**Fix:**
```python
"text": {
    "type": "string",
    "full_text_search": {
        "tokenizer": "word_v3",
        "language": "english",
        "stemming": False,
        "remove_stopwords": False,
    },
}
```

**Impact:** Low effort, high stability. Prevents silent relevance drift.

---

### TPUF-2: Non-Filtered String Fields Default to `filterable: true`

**Current:** Fields like `text`, `description`, `street`, `spacedescription`, `leasetype`, `unittype` are not declared in schema, so they inherit the default `filterable: true`.

**Docs say:** "For fields you never filter on, setting filterable: false improves indexing performance and the docs state it grants a 50% discount. This is especially important for raw text, images, large JSON blobs, or derived text that exists only for generation."

**Affected fields** (never used as filter targets):
- `text` — BM25 search field, never filtered directly (but note: enabling `full_text_search` already defaults `filterable` to `false` for that field, so this one may already be correct)
- `description` — free-text, searched via embedding, never filtered
- `street` — address text, never filtered
- `spacedescription` — availability text, never filtered
- `last_modified` — could arguably be filtered for freshness, but isn't today

**Fields that should remain filterable:**
- `object_type` — filtered on every query
- `city`, `state`, `propertyclass`, `propertysubtype` — core filter targets
- All numeric fields (size, rate, area, etc.) — range filter candidates
- All date fields — range filter candidates
- All parent `_name` fields — equality filter candidates

**Fix:** Add non-filtered fields to schema with `"filterable": False`. Requires namespace re-index.

**Impact:** Cost reduction (50% discount on affected fields), faster indexing.

---

### TPUF-3: Warm Method Uses Dummy Query Instead of Official API

**Current:** `turbopuffer_backend.py:339-345`
```python
def warm(self, namespace: str) -> None:
    try:
        self._ns(namespace).query(
            rank_by=("text", "BM25", " "),
            top_k=1,
        )
    except Exception:
        pass
```

**Docs say:** Use `GET /v1/namespaces/:namespace/hint_cache_warm`. "The warm hint is free if the namespace is already warm or is already being prepared; otherwise it is billed like a zero-row query."

**Current approach drawbacks:**
- Sends a real query with `" "` as search text, which is semantically meaningless
- Gets billed as a real query, not a free cache hint
- May not actually warm the vector index (only exercises BM25 path)

**Fix:** Replace with the official warm endpoint. Check if the Python SDK exposes it directly; if not, use a raw HTTP call.

**Impact:** Correct warming behavior, potentially free, warms both BM25 and vector indexes.

---

### TPUF-4: Aggregation Uses Client-Side Scan Instead of Native Aggregation

**Current:** `turbopuffer_backend.py:213-308` — `aggregate()` does a BM25 query for `"a the is of and to in for"` with `top_k=10_000` to fetch all matching docs into Python, then computes count/sum/avg locally.

**Docs say:** Turbopuffer supports native "Aggregations / grouped aggregations" as query capabilities, described as "query-side summarization."

**Current approach problems:**
- Fetches up to 10,000 full rows over the network for a simple count
- Falls back to zero-vector ANN scan if BM25 returns empty — unreliable
- Client-side aggregation is O(n) in records returned, not O(1) server-side
- The `top_k=10_000` cap silently truncates aggregations on large datasets
- Three nested fallback attempts (BM25 → zero-vector 1024-dim → zero-vector 8-dim) add complexity and latency

**Fix:** Investigate whether the Python SDK (v1.17.0) exposes native aggregation. If so, replace the entire method with a single server-side aggregation call. If not, track as a future improvement when the SDK catches up.

**Impact:** Dramatically faster aggregations, lower network cost, correct results on large namespaces (no 10K cap).

---

### TPUF-5: No Result Diversification for Multi-Object Queries

**Current:** All object types (property, lease, availability) share one namespace. A BM25 or vector search returns the top-k globally ranked results, which can be dominated by one object type.

**Docs say:** "If one attribute dominates the top hits, use `limit.per` to cap over-representation. This is useful when agents otherwise keep seeing near-duplicate chunks from one source or category."

**Example:** A search for "Preston Park Financial Center" returns mostly leases (51 for PPFC alone) before any properties or availabilities appear.

**Fix:** Consider adding `limit.per` on `object_type` for the query Lambda's search tool, or implement application-level diversification in the tool-use layer. This is a query quality decision — the LLM tool-use layer may already compensate by issuing separate filtered searches per object type.

**Impact:** Better result balance for broad queries. Needs eval measurement before deploying.

---

### TPUF-6: Vector Storage Uses Default `f32`

**Current:** Vectors are 1024-dimensional Bedrock Titan v2 embeddings stored at default `f32` precision.

**Docs say:** "Smaller vectors are faster to search. f16 is faster than f32. This is a cost, latency, and recall tradeoff, so only change it after running evals on your own corpus."

**Current state:** With ~1,000 documents, this is not a meaningful cost or latency concern. At scale (100K+ documents per namespace), the 2x storage and speed difference becomes material.

**Fix:** Defer until scale warrants it. When ready, declare vector schema explicitly as `[1024]f16` and measure recall on the acceptance test suite before and after.

**Impact:** Deferred. Note for production scaling.

---

## 3. Summary

### Act Now (low effort, high value)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| TPUF-1 | Tokenizer not pinned | Add `"tokenizer": "word_v3"` to schema | One-line change + re-index |
| TPUF-3 | Dummy warm query | Replace with official `hint_cache_warm` API | Small code change |

### Act Before Production (medium effort, cost/correctness)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| TPUF-2 | Non-filtered fields indexing unnecessarily | Add `"filterable": false` to schema for text fields | Schema update + re-index |
| TPUF-4 | Client-side aggregation scan | Replace with native aggregation if SDK supports it | Medium — SDK investigation |

### Evaluate Later (needs measurement)

| # | Issue | Fix | Effort |
|---|-------|-----|--------|
| TPUF-5 | No result diversification | Consider `limit.per` on `object_type` | Query quality eval needed |
| TPUF-6 | f32 vectors | Switch to f16 if recall holds | Eval at scale |

---

## 4. Schema Recommendation

If all "Act Now" and "Act Before Production" items are implemented, the schema would evolve from:

**Current:**
```python
FULL_TEXT_SEARCH_SCHEMA = {
    "text": {"type": "string", "full_text_search": True},
    "totalbuildingarea": {"type": "float"},
    # ... numeric fields ...
}
```

**Recommended:**
```python
FULL_TEXT_SEARCH_SCHEMA = {
    "text": {
        "type": "string",
        "full_text_search": {
            "tokenizer": "word_v3",
            "language": "english",
            "stemming": False,
            "remove_stopwords": False,
        },
    },
    # Non-filtered text fields — 50% cost discount
    "description": {"type": "string", "filterable": False},
    "street": {"type": "string", "filterable": False},
    "spacedescription": {"type": "string", "filterable": False},
    # Numeric fields (filterable by default — correct for range queries)
    "totalbuildingarea": {"type": "float"},
    "floors": {"type": "float"},
    # ... remaining numeric fields unchanged ...
}
```

Note: Changing schema on an existing namespace requires a re-index (write all documents again with the new schema on the first batch). This naturally pairs with the bulk re-load recommended in the denorm audit (RC-1/RC-2).
