# Search Capabilities

Last updated: 2026-03-18

## Vector Search

Turbopuffer supports vector search with filtering. Official docs say vectors are incrementally indexed in an SPFresh vector index and that writes appear in search results immediately. ANN is the standard retrieval mode for semantic search. turbopuffer states the vector index is automatically tuned for roughly 90-100% recall and exposes a recall endpoint for validation.

Use vector ANN when:

- You want semantic retrieval across a broad corpus.
- Exact string match is not sufficient.
- You need a fast first-stage retriever for RAG or agent search.

Use vector kNN when:

- You need exact nearest neighbors.
- You can first narrow the candidate set with filters.

Notes:

- `kNN` requires filters.
- Smaller vectors and `f16` improve speed and cost, with precision tradeoffs that should be validated on evals.

Primary docs:

- https://turbopuffer.com/docs/vector
- https://turbopuffer.com/docs/query
- https://turbopuffer.com/docs/performance

## Full-Text Search

Turbopuffer supports BM25 full-text search on `string` and `[]string` fields. This must be enabled in schema. Full-text search is useful for exact keywords, literal phrases, product IDs, email addresses, and any workload where lexical precision matters.

Key operational points:

- Pin tokenizer explicitly if stable behavior matters.
- `word_v3` is the documented default for new namespaces and is the recommended general-purpose tokenizer.
- `pre_tokenized_array` is the escape hatch for client-side tokenization, but it changes query operand expectations and disables several language-processing features.
- BM25 parameters `k1`, `b`, and `k3` are tunable, but official guidance is to tune empirically against evals rather than by intuition.

Primary docs:

- https://turbopuffer.com/docs/fts
- https://turbopuffer.com/docs/write

## Hybrid Search

Hybrid search in turbopuffer is built from multiple subqueries, typically vector plus BM25. turbopuffer supports multi-query in one API request and recommends combining results client-side with techniques like reciprocal-rank fusion, then reranking if needed.

Official recommendations around hybrid quality improvement include:

- Add a reranker after initial retrieval.
- Build a test set and evaluate ranking quality with NDCG.
- Try query rewriting.
- Experiment with chunking strategy.
- Consider contextual retrieval or rewritten chunks.

This is especially relevant for agents because it keeps:

- Retrieval in turbopuffer
- Fusion logic in your application
- Policy and final ranking under your control

Primary docs:

- https://turbopuffer.com/docs/hybrid
- https://turbopuffer.com/docs/concepts
- https://turbopuffer.com/docs/query

## Filters, Ordering, Aggregations

Turbopuffer query supports more than vector and BM25 ranking:

- Filters over indexed attributes
- Lookups where order is unimportant
- Ordering by attribute
- Aggregations
- Grouped aggregations
- Diversification with `limit.per`

Useful agentic cases:

- Permission filtering before retrieval
- Tenant or dataset narrowing
- Freshness ordering for operational views
- Category balancing with diversification
- Facets or grouped summaries to guide an agent before a second query

Primary docs:

- https://turbopuffer.com/docs/query

## Pagination

Offset pagination is not exposed. Official guidance is:

- Infinite scroll: exclude IDs that have already been shown
- Arbitrary page jumps: request a larger `top_k`, ignore earlier hits, and consider caching the initial result set client-side

This matters for agents because you should not promise normal `offset` semantics in a retrieval abstraction over turbopuffer.

Primary docs:

- https://turbopuffer.com/docs/query

## Consistency Model

Strong consistency is the default query behavior. Official architecture docs say writes are committed to a write-ahead log, indexed asynchronously, and still searchable immediately. Recent unindexed data may be searched exhaustively until indexing catches up.

Eventual consistency is available, but official query docs describe it as potentially up to 60 seconds stale and bounded to searching only part of the unindexed write set. Treat it as a latency and throughput tradeoff, not a general default.

Primary docs:

- https://turbopuffer.com/docs/architecture
- https://turbopuffer.com/docs/reference/query
