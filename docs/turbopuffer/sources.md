# Sources

Last updated: 2026-03-18

This library is intentionally biased toward official turbopuffer sources. Context7 was used as a retrieval aid for the official docs corpus and official SDK references, then cross-checked against the live docs pages below.

## Official Turbopuffer Docs

- Introduction: https://turbopuffer.com/docs/index
- Architecture: https://turbopuffer.com/docs/architecture
- Concepts: https://turbopuffer.com/docs/concepts
- Limits: https://turbopuffer.com/docs/limits
- Regions: https://turbopuffer.com/docs/regions
- Performance: https://turbopuffer.com/docs/performance
- Tradeoffs: https://turbopuffer.com/docs/tradeoffs
- Vector Search Guide: https://turbopuffer.com/docs/vector
- Full-Text Search Guide: https://turbopuffer.com/docs/fts
- Hybrid Search Guide: https://turbopuffer.com/docs/hybrid
- Write API: https://turbopuffer.com/docs/write
- Query API: https://turbopuffer.com/docs/query
- Query Reference: https://turbopuffer.com/docs/reference/query
- Warm Cache API: https://turbopuffer.com/docs/warm-cache

## Context7 Libraries Used

- Official docs corpus: `/websites/turbopuffer`
- Official TypeScript SDK: `/turbopuffer/turbopuffer-typescript`
- Official Python SDK: `/turbopuffer/turbopuffer-python`

## Notes On Confidence

High-confidence claims in this library are limited to behavior documented in the sources above, including:

- search modes and query model
- schema and indexing behavior
- performance and consistency guidance
- documented limits
- official recommended patterns for hybrid retrieval

Areas where you should verify against the latest docs before making irreversible design changes:

- current region availability
- pricing and discounts
- roadmap-adjacent features
- SDK ergonomics and version-specific details
