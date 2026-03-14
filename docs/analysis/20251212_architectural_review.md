# Architectural Review — Salesforce AI Search (Graph‑Enhanced Zero‑Config RAG)

**Date:** 2025‑12‑12  
**Author:** Technical BA (AI assistant)  
**Scope:** Unbiased review of current project architecture and recommendations to improve accuracy, latency, and operational robustness.  

---

## 1. Executive Summary

The system is a well‑structured Graph‑Enhanced RAG platform integrated with Salesforce for CRE search and agent actions. Its strongest traits are (a) layered query planning with graceful fallbacks, (b) tight security via private networking and Salesforce‑aligned AuthZ/FLS enforcement, and (c) a credible “zero‑config” trajectory grounded in Describe‑driven schema discovery and metadata configuration.  

Main risks are concentrated in the graph layer’s scalability limits on DynamoDB adjacency lists, ongoing dependence on LLM decomposition accuracy, and the operational burden of Salesforce API limits. The most valuable near‑term improvements are enabling Bedrock Knowledge Base reranking, tuning chunking/overlap per field type, and strengthening schema‑first correction loops. Longer‑term, plan for an optional Neptune migration if graph p95 traversals regress at scale.

---

## 2. What’s Strong

1. **Separation of concerns and clean fallbacks**
   - Planner/decomposer → graph filter/traversal → derived views → KB retrieval → answer generation is a sensible layered pipeline for CRE.
   - Speculative parallel planning with vector fallback is aligned with low‑latency RAG practice.

2. **Security posture appropriate for Salesforce data**
   - Salesforce Private Connect + AWS PrivateLink + private API Gateway + Named Credential authentication reduces exposure of sensitive data and follows standard enterprise patterns.  
   - Authorization at each traversal hop plus post‑filtering prevents “graph inference leaks.”

3. **Zero‑config direction is credible**
   - Describe‑driven Schema Cache as source of truth + `IndexConfiguration__mdt` overrides + semantic hints + signal harvesting is the right way to avoid brittle hard‑coding.

4. **Derived views for aggregation**
   - Materialized rollups for vacancy, availability, leases, activities, sales are the right performance lever for aggregation intents.

---

## 3. Main Risks / Weak Spots

1. **Graph on DynamoDB adjacency lists may bottleneck at scale**
   - DynamoDB graphs work well for limited hops and moderate fan‑out, but multi‑hop traversal on highly connected data can become latency/cost heavy vs. purpose‑built graph engines (Neptune).  
   - Risk signals: rising `GraphTraversalLatency` p95, high fan‑out edges, or complex relationship chains.

2. **Retrieval quality remains sensitive to LLM decomposition**
   - Even with schema validation, the planner can mis‑target objects/fields, leading to 0‑candidate graph filters and more fallbacks.  
   - Without systematic correction/evaluation loops, drift will slowly erode precision@k.

3. **Chunk sizing may be sub‑optimal for some query types**
   - 300–500 token chunks help for narrative notes, but can dilute precision for short, factoid, or filter‑heavy queries.  
   - CRE often has many short structured fields where smaller chunks + strong headings are beneficial.

4. **Salesforce API limits as an operational constraint**
   - Schema discovery, signal harvesting, relationship enrichment, and AuthZ/FLS checks all consume SF API quotas and can hit daily or per‑minute throttles.  
   - Throttling affects freshness and planner quality indirectly.

5. **Private networking narrative needs precision**
   - Data plane is private; some metadata/control‑plane calls (e.g., AppFlow/Describe) can still use public SF endpoints. This is normal but should be documented clearly to avoid confusion in reviews.

---

## 4. Suggestions to Improve Accuracy

### 4.1 Enable Bedrock KB reranking
- Use a two‑stage retrieval: retrieve top 20–30 candidates, rerank to top‑K (8).  
- Expected outcome: measurable precision@5 gain for entity‑dense CRE data with minimal latency impact.

### 4.2 Explicit search‑type routing by intent
- Map intents to KB search types:
  - SIMPLE / FIELD_FILTER → **HYBRID**
  - RELATIONSHIP with strong seed IDs → **SEMANTIC** (or HYBRID with weaker keyword weight)
  - AGGREGATION → derived views first, KB as fallback

### 4.3 Add implicit metadata filtering as a safety net
- Configure KB implicit filters (sobject, region, BU) so retrieval remains biased correctly even when the planner drops or mis‑binds a filter.

### 4.4 Tighten the schema‑first correction loop
- When planner emits a non‑existent field:
  1. Drop/repair the predicate.
  2. Log as a binding miss.
  3. If confidence falls below threshold, trigger disambiguation instead of silent fallback.

### 4.5 Strengthen evaluation
- Expand beyond acceptance scenarios:
  - Create an offline **binding accuracy** set (intent‑stratified).
  - Track weekly drift.
  - Use citations clicks and user corrections as relevance signals.

---

## 5. Suggestions to Improve Performance / Cost

### 5.1 Tune chunking per field class
- Run a sweep on Notes/Descriptions:
  - chunk sizes: 200 vs 300 tokens
  - overlap: 0% vs 10–15%
- For short structured fields, prefer smaller chunks with explicit labels/headings.
- Expected outcome: higher precision without large cost increase.

### 5.2 Set a staged Neptune migration trigger
- Keep DynamoDB graph for now, but define a migration threshold:
  - node/edge count,
  - average fan‑out,
  - traversal p95 breach,
  - or path cache miss rate spikes.
- If triggered, dual‑write to Neptune for a period, then switch traversal.

### 5.3 Reduce Salesforce API pressure
- Batch enrichment calls, cache more aggressively, and diff‑apply signal harvesting instead of full rescans.
- Run heavy signal harvesters less frequently (weekly) unless a config diff requires it.

### 5.4 Cache planner outputs for hot templates
- Short TTL plan cache keyed by (normalized query + user bucket hash).  
- Low effort, noticeable p95 savings on repeated “template” queries.

---

## 6. Operational Recommendations

1. **Document private vs public call paths**
   - Clarify that data plane traffic is private while some metadata/control calls may use public SF endpoints.

2. **Alert on early graph scaling signals**
   - Add alarms for fan‑out and traversal node cap triggers to detect scaling issues before latency regresses.

3. **Keep “Latest state” centralized**
   - Maintain a short “latest changes” pointer (date + file) in `docs/guides/PROJECT_PRIMER.md` to avoid handoff archaeology.

---

## 7. Proposed Priority Backlog (Impact‑First)

**P1 (near‑term, high impact)**
- Enable KB reranking and A/B test against acceptance + offline sets.
- Chunking size/overlap sweep on CRE long‑text objects.
- Schema‑first correction + disambiguation on invalid predicates.

**P2 (medium‑term)**
- Intent‑based search‑type routing.
- Planner output caching for hot templates.
- Diff‑based signal harvesting schedule.

**P3 (longer‑term)**
- Neptune migration plan + dual‑write proof‑of‑concept.
- More advanced re‑ranking or cross‑encoder options if Bedrock rerank plateaus.

---

## 8. Closing Note

Overall architecture is solid and aligns with best practices for secure, low‑latency enterprise RAG. The project has already resolved the largest correctness risk (schema drift) and successfully rolled planner traffic to 100%. The next gains will come from retrieval‑quality enhancements (reranking, chunk tuning) and scaling readiness for the graph layer.  

