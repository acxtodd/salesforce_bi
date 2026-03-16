# Performance Optimization (Low-Risk, Recall-Preserving)
**Date:** 2025-12-10  
**Author:** QA Lead  
**Scope:** Retrieve + Answer path (planner, graph filter, traversal, KB search, Lambda), infra (OpenSearch Serverless, DynamoDB, Lambda runtime).  
**Goal:** Reduce `/answer` p95 end‑to‑end latency for cross‑object Availability queries from ~30s to **<10s** (retrieval‑only target **<2s**) without degrading recall or parent/child context quality.

---

## Guiding Principles
1. **Preserve recall first.** Prefer pruning early by _certainty_ (seed IDs, deterministic filters) rather than by truncating vectors or chunks.  
2. **Pay once per query.** Avoid repeated traversals or re-fetching parent metadata; cache within the request.  
3. **Cap work, don’t fail.** Enforce time/node caps with graceful fallbacks (seed-filtered KB only) instead of timeouts.  
4. **Measure every hop.** Emit timing for planner, graph filter, traversal, KB search, enrichment, answer.

---

## Current Symptoms (from smoke tests)
- Cross-object availability queries still reach ~30s and occasionally time out.  
- Enrichment sometimes collapses multiple properties into one, leading to missing Class A properties (e.g., Granite Park, Legacy submarket).  
- Multi-value filter (`A OR A+`) returns zero candidates on graph filter.  
- Planner/graph are returning 3 properties & 9 availabilities; KB returns 8 chunks; enrichment only attaches 1 property → grouping failure.

---

## Recommended Optimizations (prioritized, safe for recall)

### 1) Executor Short-Circuit & Caps (logic-only, no data loss)
- **Skip traversal only when seeds fully constrain the target set.** Pass deterministic seed IDs directly to KB and skip further hops **only if no additional relationship predicates require traversal.**
  - Safe to skip when: (a) seeds are for the *target* object, or (b) seeds are for the parent object and all child‑side constraints are enforceable via KB metadata filters or derived views.
  - Do **not** skip when child‑side filters (e.g., Availability status/size/date predicates) must be applied via graph hops.
- **Tighten traversal caps (intent‑conditional):** for 1‑hop relationship intents (e.g., Property→Availability), cap depth ≤1; for other relationship intents keep depth ≤2 default. Reduce `MAX_NODES_PER_HOP` 50→20 and budget ~800ms/hop with soft stop + partial results.  
- **Guard enrichment:** log mismatch counts (candidate IDs vs fetched parent records) and return partial grouped results instead of failing whole answer.

### 2) Metadata Fetch Efficiency
- **Batch parent fetches** for properties/leases in a single DynamoDB `BatchGet` (≤100) instead of per-availability queries.  
- **Projection expressions** to fetch only Name, Class, City, RecordType, PropertyType—fields required by the contract—reducing payload and latency.  
- **Negative cache** for missing IDs within the request to avoid repeated lookups.

### 3) KB / Vector Search Tuning (recall-safe)
- **Lower `topK` on narrow filters**: when seed IDs are present, use `topK=20` (was 50) to cut rerank cost.  
- **Enable Bedrock KB reranking for top candidates**: retrieve top 20–30 then rerank to 8 when result sets are large; skip rerank when <10 chunks.  
- **Raise `ef_search` only when filters are empty (Faiss HNSW).** For filtered queries keep moderate `ef_search`; rely on metadata filters for precision.  
- **Use OpenSearch Serverless auto‑optimize** to tune HNSW/quantization to your latency/recall SLA.  
- **Segment/refresh hygiene (serverless limits):** serverless vector collections don’t expose manual warmup or segment merge controls; focus on minimal shard counts, avoiding bursty re‑indexing, and monitoring refresh/segment metrics for tail latency.

### 4) DynamoDB Graph Nodes/Edges
- **Query, never scan.** Ensure traversal uses `KeyConditionExpression` on PK/GSI and avoids filters that force Scan.  
- **Hot-partition avoidance:** validate partition keys have high cardinality; if `type` alone is hot, add hashed suffix or time bucket to spread load.  
- **Projection & pagination:** use projection expressions + 1MB page cap; iterate until cap/time budget hit.

### 5) Lambda Runtime & Packaging
- **Arm64 + Python 3.11 build**: Lambda on Graviton2/arm64 can deliver up to ~34% better price‑performance (and ~20% lower cost) vs x86; adopt multi‑arch images with arm64 default.  
- **Provisioned Concurrency on retrieve** during business hours; keep low base (e.g., 5) and autoscale with metrics. If first‑token p95 remains high, add a small PC floor on Answer Lambda as well.  
- **Trim deployment size** (remove unused deps, exclude docs/tests, prefer layers) to reduce init duration.  
- **Warm ping** sparingly if Provisioned Concurrency is off to limit cold‑start risk without excess invocations.

### 6) Planner & Filter Correctness (indirect perf gain)
- **Fix multi-value predicates** so `["A","A+"]` uses IN semantics; prevents empty graph seeds and wasted traversal.  
- **Early contract check**: if required fields missing, short-circuit to vector-only with clear warning instead of full traversal that will fail later.

### 7) Chunking / Answer Path
- **Smaller chunks for availability facts** (200–300 tokens) to reduce token I/O and match Bedrock KB chunking guidance (default ~200–300 tokens, 0–20% overlap); keep property metadata in chunk metadata, not text, to avoid duplication.  
- **Rerank only top 20** when seed IDs present (Bedrock KB rerank or lightweight re‑score); skip rerank when candidate set is small.  
- **Stream answers** as soon as first property group is assembled; continue enriching remaining groups in background if needed (latency/user experience win).

### 8) Observability for Performance
- Emit per-stage timings: planner, graph filter, traversal, KB, enrichment, answer.  
- Add CloudWatch metric filters for: traversal timeouts, enrichment mismatch, KB latency >1s, lambda cold start indicator (`Init Duration`).  
- Daily report on: p95 latency, empty-result rate, traversal cap hit rate, cold-start rate.

---

## Minimal-Risk Implementation Order (1 sprint)
1. Short-circuit traversal + reduced caps (exec path only).  
2. Batch parent fetch + projection expressions.  
3. Fix multi-value IN predicate; add enrichment mismatch logging.  
4. Deploy arm64 image + Provisioned Concurrency (retrieve only).  
5. Tune topK/ef_search policy and enable OpenSearch auto-optimize job.  
6. Add performance metrics dashboard & alerts.

---

## Metrics to Track Success
- p95 end-to-end latency (goal: <10s for cross-object availability; <2s for single-object).  
- Traversal timeout rate (goal: <2%).  
- Empty-result rate for availability queries with filters (goal: <5%).  
- Recall proxy: # of properties returned vs seed IDs found (goal: ≥95%).  
- Cold start rate during peak hours (goal: <5%).

---

## References
1. OpenSearch Serverless auto‑optimize for vector indices: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-auto-optimize.html  
2. OpenSearch Serverless vector search (Faiss HNSW capabilities/limits): https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-vector-search.html  
3. DynamoDB best practice — prefer Query over Scan: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-query-scan.html  
4. DynamoDB partition key design / avoid hot partitions: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html  
5. Lambda arm64/Graviton2 price‑performance and cost: https://aws.amazon.com/about-aws/whats-new/2021/09/aws-lambda-graviton2-processor/  
6. Lambda Provisioned Concurrency: https://docs.aws.amazon.com/lambda/latest/dg/provisioned-concurrency.html  
7. Lambda deployment package size best practices: https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html#function-code-dependencies  
8. Bedrock Knowledge Bases rerankers: https://aws.amazon.com/blogs/aws/amazon-bedrock-knowledge-bases-now-support-rerankers/  
9. Bedrock Knowledge Bases chunking strategies: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-chunking-strategies.html  
10. OpenSearch k‑NN HNSW tuning (for advanced cases): https://opensearch.org/docs/latest/search-plugins/knn/knn-index/
