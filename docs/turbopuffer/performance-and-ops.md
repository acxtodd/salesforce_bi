# Performance And Ops

Last updated: 2026-03-18

## Official Performance Model

Turbopuffer is built to serve search from object storage with cache-backed hot paths. Official docs cite:

- cold queries on 1M vectors: p90 around 444 ms
- warm queries on 1M vectors: p50 around 8 ms

This means the first optimization question is often cache temperature, not only query syntax.

Primary docs:

- https://turbopuffer.com/docs/index

## Highest-Leverage Tuning Knobs

### 1. Region placement

Choose the region closest to your backend. This is the simplest latency win.

Primary docs:

- https://turbopuffer.com/docs/performance
- https://turbopuffer.com/docs/regions

### 2. Reuse one client instance

Official docs recommend reusing the same `Turbopuffer` client instance so the SDK connection pool can avoid repeated TCP and TLS handshakes.

Primary docs:

- https://turbopuffer.com/docs/performance

### 3. Keep namespaces small

If there is a natural partitioning key, smaller namespaces can query and index faster than one very large namespace. The rule of thumb from the docs is to make namespaces as small as possible without routinely needing to query more than one at a time.

This is highly relevant for agent systems where common fanout patterns are:

- per tenant
- per workspace
- per corpus type
- per permission domain

Primary docs:

- https://turbopuffer.com/docs/performance

### 4. Mark non-filtered fields as non-filterable

Filterable attributes are indexed into an inverted index. For fields you never filter on, setting `filterable: false` improves indexing performance and the docs state it grants a 50% discount. This is especially important for raw text, images, large JSON blobs, or derived text that exists only for generation.

Primary docs:

- https://turbopuffer.com/docs/performance
- https://turbopuffer.com/docs/write

### 5. Reduce vector size and storage precision when justified

Smaller vectors are faster to search. `f16` is faster than `f32`. This is a cost, latency, and recall tradeoff, so only change it after running evals on your own corpus.

Primary docs:

- https://turbopuffer.com/docs/performance

### 6. Batch and parallelize writes

Official docs recommend fewer, larger write batches and using multiple processes in parallel when ingest throughput matters. Batch requests can be up to 512 MB.

Primary docs:

- https://turbopuffer.com/docs/performance
- https://turbopuffer.com/docs/limits

### 7. Control response size

Only request the attributes you need. Returning extra fields slows queries and increases cost.

Primary docs:

- https://turbopuffer.com/docs/performance

## Warm vs Cold Strategy

Use warm-cache hints when:

- a user opens search
- a user starts a chat session
- you know which namespaces are likely to be queried next

Official docs say the warm hint is free if the namespace is already warm or is already being prepared; otherwise it is billed like a zero-row query.

Primary docs:

- https://turbopuffer.com/docs/warm-cache

## Write Path Expectations

The architecture trades some write latency for durability and scale. Official tradeoff docs describe writes as taking up to about 200 ms to commit while still supporting high namespace write throughput and immediate visibility through the consistent read model.

Primary docs:

- https://turbopuffer.com/docs/tradeoffs
- https://turbopuffer.com/docs/architecture

## Consistency Tradeoff

Strong consistency:

- default
- freshest data
- searches all unindexed writes
- better choice for interactive agent systems

Eventual consistency:

- can reduce warm latency
- may be up to 60 seconds stale
- searches only a bounded amount of unindexed writes

Primary docs:

- https://turbopuffer.com/docs/reference/query
- https://turbopuffer.com/docs/architecture

## Query Telemetry To Observe

Official query docs say responses can expose:

- `cache_hit_ratio`
- `cache_temperature`
- `server_total_ms`
- `query_execution_ms`
- `exhaustive_search_count`
- `approx_namespace_size`
- billable logical bytes queried and returned

Use these fields to separate:

- query logic problems
- cold-cache problems
- payload bloat
- namespace sizing issues

Primary docs:

- https://turbopuffer.com/docs/reference/query

## Anti-Patterns

- One oversized namespace when a stable partitioning key exists
- Large response payloads in first-stage retrieval
- Default tokenizer reliance in relevance-sensitive workloads
- Exact kNN without first pruning the search space
- Unbounded regex or glob-heavy filters without measurement
- Tuning BM25 or embedding size without evals

## Design Heuristics For Agents

- Favor one namespace per query path when possible.
- Favor one multi-query request over separate network round trips when doing hybrid retrieval.
- Keep first-stage retrieval cheap and broad enough for recall.
- Keep second-stage reranking expensive and narrow.
- Measure cold and warm latency separately.
- Treat schema design as part of search quality, not only storage layout.
