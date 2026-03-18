# Turbopuffer Agent Reference

Last updated: 2026-03-18

This library is a compact, agent-oriented reference for turbopuffer search systems. It is biased toward official turbopuffer documentation and cross-checked against Context7 entries for the official docs and SDKs.

Use this library when you need to answer questions like:

- Which search mode should I use: vector, BM25, exact kNN, or hybrid?
- How should I model schema for search, filtering, and cost control?
- What query patterns are recommended for agentic retrieval systems?
- How do I tune latency, warm caches, namespace layout, and payload size?

Start here:

- [Agent Cheat Sheet](./agent-cheatsheet.md)
- [Search Capabilities](./search-capabilities.md)
- [How-To Patterns](./how-tos.md)
- [SDK Examples](./sdk-examples.md)
- [Performance And Ops](./performance-and-ops.md)
- [Sources](./sources.md)

## Project Overlay

Keep this library generic. For repo-specific behavior, defer to code and
`CLAUDE.md`.

Current project specifics:

- Turbopuffer is wrapped only in `lib/turbopuffer_backend.py`; application code
  should continue to depend on `SearchBackend`, not the SDK directly.
- Hybrid retrieval in this repo uses `multi_query` plus application-side RRF
  fusion. Do not reintroduce `Sum(BM25, ANN)` query construction.
- Namespaces are per Salesforce org.
- The current POC query layer scopes to `Property`, `Lease`, and
  `Availability`, even though `denorm_config.yaml` and CDC mapping keep
  `Deal` and `Sale` for later-phase readiness.
- Use this folder for Turbopuffer API, schema, hybrid, and performance
  questions before making backend design changes.

## What Turbopuffer Is

Turbopuffer is a search engine that combines vector and full-text search on top of object storage. Its architecture keeps active data warm in cache while storing the full corpus in low-cost object storage. Official docs position it as horizontally scalable to billions of documents, with cold p90 queries around 444 ms on 1M vectors and warm p50 around 8 ms when cached.

Primary docs:

- https://turbopuffer.com/docs/index
- https://turbopuffer.com/docs/architecture

## Core Retrieval Model

Turbopuffer supports:

- Vector search with ANN and filters
- Exact vector search with kNN over filtered subsets
- BM25 full-text search on `string` and `[]string`
- Hybrid search via multi-query plus client-side fusion
- Attribute ordering, lookups, aggregations, grouped aggregations

Important design point: hybrid orchestration is expected to live in your app layer. Official guidance explicitly recommends keeping search logic in your own `search.py` or `search.ts`, using turbopuffer for initial retrieval, then applying rank fusion and optional reranking outside the database.

Primary docs:

- https://turbopuffer.com/docs/query
- https://turbopuffer.com/docs/vector
- https://turbopuffer.com/docs/fts
- https://turbopuffer.com/docs/hybrid

## Agentic Guidance

For agentic search systems, the default pattern should usually be:

1. Keep namespaces narrow enough that a user query usually hits one namespace.
2. Run hybrid retrieval with one or more vector queries plus one BM25 query.
3. Fuse results client-side, then rerank a small candidate set.
4. Return only the attributes needed for the current model step.
5. Measure on eval queries before changing embedding dimensions, BM25 parameters, or chunking.

Why:

- Vector search improves semantic recall.
- BM25 captures exact strings, identifiers, and literal phrasing.
- Multi-query keeps the retrieval fanout inside a single API round trip.
- Client-side fusion gives you control over agent behavior instead of burying ranking logic in one opaque query.

## High-Value Caveats

- Exact `kNN` requires filters. Use it for exact search over narrowed subsets, not broad corpus retrieval.
- Full-text search must be enabled in schema and only works on `string` or `[]string`.
- `full_text_search: true` changes the default `filterable` behavior for that field; set `filterable: true` explicitly only if you need both.
- turbopuffer may upgrade the default tokenizer over time. Pin the tokenizer in schema if behavior stability matters.
- Changing the type of an existing attribute is an error.
- Offset pagination is not exposed. For infinite scroll, exclude already-returned IDs instead.
- Multi-query has a documented limit of 16 subqueries per request.
- Eventual consistency can be up to 60 seconds stale and only searches a bounded amount of unindexed writes.

## Suggested Library Usage

If another agent is answering a question:

- Read [Agent Cheat Sheet](./agent-cheatsheet.md) first for defaults.
- Read [How-To Patterns](./how-tos.md) for implementation guidance.
- Read [Performance And Ops](./performance-and-ops.md) before recommending schema or architecture changes.
- Follow every recommendation back to [Sources](./sources.md) if precision matters.
