# Agent Cheat Sheet

Last updated: 2026-03-18

## Default Recommendations

- Use hybrid retrieval by default for user-facing search or RAG.
- Keep search orchestration in application code, not in one monolithic query abstraction.
- Use strong consistency unless you have measured that eventual consistency materially improves warm latency for your workload.
- Keep namespaces as small as practical without forcing routine multi-namespace fanout.
- Return the smallest possible attribute set with `include_attributes`.
- Prewarm namespaces for latency-sensitive first queries.
- Explicitly define schema for `uuid`, `uint`, vector type, full-text options, and any non-default indexing behavior.
- Mark large non-filtered attributes as `filterable: false` to reduce cost and indexing work.

## Retrieval Decision Matrix

| Need | Use | Why |
| --- | --- | --- |
| Semantic similarity | Vector ANN | Fast broad semantic retrieval |
| Exact nearest neighbors on a narrowed subset | Vector kNN with filters | Exact search, but only after pruning |
| Keyword, SKU, email, identifier matching | BM25 | Strong lexical matching |
| Best overall search quality | Multi-query hybrid | Combines semantic and lexical recall |
| Facets, totals, grouped summaries | Aggregations / grouped aggregations | Query-side summarization |
| Stable result diversity | `limit.per` diversification | Avoids one category dominating |

Official docs:

- https://turbopuffer.com/docs/query
- https://turbopuffer.com/docs/hybrid

## Schema Defaults To Reconsider

- `filterable` defaults to `true` for standard attributes.
- If `full_text_search` or `regex` is enabled, `filterable` defaults to `false` unless explicitly overridden.
- Vector storage defaults to `f32` unless you explicitly choose `f16`.
- ANN defaults to enabled for vectors.
- Tokenizer defaults can change over time.

Official docs:

- https://turbopuffer.com/docs/write
- https://turbopuffer.com/docs/fts

## Good Agentic Patterns

- Query rewrite into multiple semantically distinct subqueries only when you can evaluate the gain.
- Combine one lexical query with one or more semantic queries, then fuse client-side.
- Rerank only a small candidate set after fusion.
- Cache candidate IDs or fused results for user pagination because offset pagination is not exposed.
- Exclude already-rendered IDs for infinite scroll.
- Use evals before changing chunking, BM25 params, embedding size, or hybrid weighting.

## Common Mistakes

- Putting every tenant or document type into one huge namespace without a strong reason.
- Returning raw chunk text, embeddings, metadata blobs, and unused fields on every query.
- Using BM25 without explicitly configuring the search field in schema.
- Depending on default tokenizer behavior for production relevance-sensitive flows.
- Using exact kNN as a broad retrieval strategy.
- Recommending eventual consistency without acknowledging the freshness tradeoff.

## Production Facts Worth Remembering

- Strong consistency is the default.
- Recent writes are searchable immediately, even before background indexing completes.
- Query responses can include billing and performance telemetry such as cache hit ratio, cache temperature, server time, query execution time, and approximate namespace size.
- Warm cache hints are available through `GET /v1/namespaces/:namespace/hint_cache_warm`.

Official docs:

- https://turbopuffer.com/docs/architecture
- https://turbopuffer.com/docs/reference/query
- https://turbopuffer.com/docs/warm-cache

## Hard Limits That Affect Design

- Max dimensions: 10,752
- Max docs per namespace: 500M documented production limit
- Max queries in one multi-query request: 16
- Max concurrent queries per namespace: 16
- Max write batch request size: 512 MB
- Max write batch rate per namespace: 1 batch/s
- Max `limit.total`: 10k
- Max aggregation groups per query: 10k

Official docs:

- https://turbopuffer.com/docs/limits
