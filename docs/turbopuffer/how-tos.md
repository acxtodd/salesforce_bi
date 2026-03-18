# How-To Patterns

Last updated: 2026-03-18

This file focuses on patterns that agents and application code will routinely need. The snippets are intentionally minimal and reflect documented query shapes rather than one specific SDK wrapper.

## 1. Create A Namespace Schema For Hybrid Retrieval

Use this when you need:

- Vector retrieval
- BM25 on chunk text
- Metadata filters
- Lower cost on large non-filtered fields

```json
{
  "distance_metric": "cosine_distance",
  "schema": {
    "id": { "type": "uuid" },
    "chunk_text": {
      "type": "string",
      "full_text_search": {
        "tokenizer": "word_v3",
        "language": "english",
        "stemming": false,
        "remove_stopwords": false
      }
    },
    "doc_id": { "type": "uuid", "filterable": true },
    "tenant_id": { "type": "uuid", "filterable": true },
    "section": { "type": "string", "filterable": true },
    "created_at": { "type": "datetime", "filterable": true },
    "embedding": {
      "vector": { "type": "[1024]f16", "ann": true }
    },
    "raw_markdown": { "type": "string", "filterable": false }
  }
}
```

Why this shape works:

- `chunk_text` is searchable with BM25.
- metadata fields remain filterable.
- `raw_markdown` avoids unnecessary indexing cost.
- `f16` reduces vector footprint when acceptable for your evals.

Primary docs:

- https://turbopuffer.com/docs/write
- https://turbopuffer.com/docs/fts
- https://turbopuffer.com/docs/performance

## 2. Run Basic Vector Retrieval

```json
{
  "top_k": 20,
  "rank_by": ["vector", "ANN", [0.12, 0.87, 0.44]],
  "include_attributes": ["chunk_text", "doc_id", "section"]
}
```

Use this for first-stage semantic recall. Keep `include_attributes` tight.

Primary docs:

- https://turbopuffer.com/docs/query
- https://turbopuffer.com/docs/vector

## 3. Add Security Or Tenant Filters

```json
{
  "top_k": 20,
  "rank_by": ["vector", "ANN", [0.12, 0.87, 0.44]],
  "filters": ["And", [
    ["tenant_id", "Eq", "ee1f7c89-a3aa-43c1-8941-c987ee03e7bc"],
    ["section", "In", ["api", "guide", "reference"]]
  ]],
  "include_attributes": ["chunk_text", "doc_id", "section"]
}
```

For agents, filter before reranking whenever the constraint is hard.

Primary docs:

- https://turbopuffer.com/docs/query

## 4. Run BM25 For Exact Language

```json
{
  "top_k": 20,
  "rank_by": ["chunk_text", "BM25", "uuid native type filterable false"],
  "include_attributes": ["chunk_text", "doc_id", "section"]
}
```

Use this when exact terms matter more than semantics.

Primary docs:

- https://turbopuffer.com/docs/query
- https://turbopuffer.com/docs/fts

## 5. Run Hybrid Retrieval In One Request

```json
{
  "queries": [
    {
      "top_k": 30,
      "rank_by": ["vector", "ANN", [0.12, 0.87, 0.44]],
      "include_attributes": ["chunk_text", "doc_id", "section"]
    },
    {
      "top_k": 30,
      "rank_by": ["chunk_text", "BM25", "uuid native type filterable false"],
      "include_attributes": ["chunk_text", "doc_id", "section"]
    }
  ]
}
```

Recommended client flow:

1. Run multi-query.
2. Fuse by reciprocal-rank fusion or another transparent strategy.
3. Rerank the top fused candidates if needed.
4. Pass only the final shortlist to the model.

Primary docs:

- https://turbopuffer.com/docs/hybrid
- https://turbopuffer.com/docs/query

## 6. Diversify Results

If one attribute dominates the top hits, use `limit.per` to cap over-representation. This is useful when agents otherwise keep seeing near-duplicate chunks from one source or category.

Primary docs:

- https://turbopuffer.com/docs/query

## 7. Paginate Without Offsets

For infinite scroll:

- Track returned IDs.
- Use `["id", "NotIn", [...]]` to exclude them in the next query.

For arbitrary page jumps:

- Request a larger `top_k`.
- Ignore earlier rows client-side.
- Cache the result set if pagination is frequent.

Primary docs:

- https://turbopuffer.com/docs/query

## 8. Prewarm Before A Latency-Sensitive Session

Use `GET /v1/namespaces/:namespace/hint_cache_warm` when a user opens a search-heavy surface or starts a new assistant session. The docs specifically call out warming all namespaces associated with a user at session start to avoid cold first-query latency.

Primary docs:

- https://turbopuffer.com/docs/warm-cache

## 9. Choose Consistency Intentionally

Use strong consistency when:

- Fresh writes must be visible immediately
- Search powers a user-edit loop
- Agents rely on recent writes or state transitions

Consider eventual consistency only when:

- Lower warm latency is more important than freshest writes
- You can tolerate up to 60 seconds of staleness

Primary docs:

- https://turbopuffer.com/docs/architecture
- https://turbopuffer.com/docs/reference/query

## 10. Measure Before Tuning

Before changing retrieval configuration, create a repeatable eval set and measure:

- recall / recall@k
- NDCG or ranking quality
- latency split by cold and warm
- response payload size
- cache hit ratio and query execution metrics

Primary docs:

- https://turbopuffer.com/docs/hybrid
- https://turbopuffer.com/docs/vector
- https://turbopuffer.com/docs/reference/query
