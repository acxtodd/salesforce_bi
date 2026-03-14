# Project Primer — Salesforce AI Search (Graph‑Enhanced Zero‑Config RAG)

**Audience:** new engineers/agents, technical BAs, QA.  
**Purpose:** give a single, fast, accurate orientation so you can be productive in ~15–20 minutes without rereading every spec and handoff.  
**Last updated:** 2025‑12‑12.

---

## 1. TL;DR

This project delivers a **Salesforce‑native AI Search & Agent experience for Commercial Real Estate (CRE)**. Users ask natural‑language questions in a Lightning Web Component (LWC). The AWS backend:

- **Plans** the query into structured filters and traversal steps using auto‑discovered Salesforce schema.
- **Filters/traverses a relationship graph** (DynamoDB nodes/edges) for cross‑object constraints.
- **Uses derived views** for fast aggregations (vacancy, availability, leases, activities, sales).
- **Searches Bedrock Knowledge Base + OpenSearch hybrid index** with metadata and seed‑ID filters.
- **Enforces Salesforce sharing + FLS**, then returns grounded answers with citations.

The system is designed to be **“zero‑config”**: adding a new object should require *only metadata configuration* (or schema discovery), not code changes.

---

## 2. Core Problem & Domain

CRE brokers and admins need to ask questions like:

- “Available Class A office space in Plano.”
- “Leases expiring in the next 6 months.”
- “Properties with vacancy >25%.”
- “Deals where Transwestern is involved.”

They shouldn’t need to know Salesforce object models, field names, or relationship paths. The system must return **precise results, quickly, and only when authorized**.

---

## 3. Architecture at a Glance

**Salesforce side**
- LWC chat UI (streaming answers + citations drawer).
- CDC events + optional Batch Export (Apex).
- `IndexConfiguration__mdt` (objects/fields to index, graph settings, semantic hints).
- Named Credential for private AWS access.

**AWS side**
- Private API Gateway (`/retrieve`, `/answer`, `/action`, `/schema/{object}`).
- Retrieve Lambda (planner/decomposition, graph filtering/traversal, KB search).
- Answer Lambda (calls retrieve, streams grounded answer).
- AuthZ Sidecar (sharing buckets + FLS tags, cached).
- Ingestion Step Functions (validate → transform → chunk → enrich → graph build → derived views → embed → sync).
- DynamoDB: schema cache, vocab cache, graph nodes/edges, derived views, authz cache, telemetry/sessions.
- Bedrock KB with Titan v2 embeddings + OpenSearch hybrid retrieval.

---

## 4. Query Flow (End‑to‑End)

1. **User query** arrives via LWC → PrivateLink → API Gateway → `/answer` or `/retrieve`.
2. **Speculative parallel execution** starts:
   - **Planner path (≤500ms p95 cutoff):**
     - Dynamic **entity detection** (labels + semantic hints).
     - **Schema‑aware decomposition** into:
       - target object
       - predicates (filters)
       - traversal plan (if cross‑object / relationship)
       - seed IDs (if names/addresses resolve)
       - confidence score
     - **Entity linking** (vocab cache + relevance scoring).
     - **Value normalization** (ranges, picklists, geo, percent).
     - **Temporal parsing** (relative dates, quarters).
   - **Vector fallback path** begins immediately (hybrid search without structured filters).
3. **Pre‑filtering & traversal**
   - If structured filters exist, **Graph Attribute Filter** finds candidate node IDs.
   - If **0 candidates**, short‑circuit to empty **unless the query is aggregation‑class** (then derived views must still run).
   - If cross‑object, planner orders: **filter parent → traverse to target**.
4. **Aggregation routing**
   - For aggregation intents, **Derived View Manager** is queried first.
   - If a required rollup is missing, system logs a gap and falls back to vector + filters.
5. **KB / OpenSearch retrieval**
   - Bedrock KB hybrid search runs with metadata filters and/or seed IDs.
   - Top‑K defaults to 8 (POC), tuned in prod via config.
6. **Authorization**
   - AuthZ Sidecar provides **sharing buckets** + **FLS profile tags** (cached 24h).
   - Graph traversal enforces access **at every hop**.
   - Post‑filter validates each candidate is viewable.
   - FLS redacts fields when `FLS_ENFORCEMENT=enabled`.
7. **Answer generation**
   - Answer Lambda builds grounding prompt and streams response.
   - Citations are validated and returned with record IDs and location pointers.

**Key fallbacks**
- Planner timeout/low confidence → hybrid vector search.
- Graph unavailable/traversal error → vector‑only search.
- Derived view missing → vector + filters with gap log.

---

## 5. Ingestion / Indexing Flow

1. **Data change sources**
   - **CDC via AppFlow** (preferred, near real‑time).
   - **Batch Apex export** (fallback/bootstrapping).
2. **Step Functions pipeline**
   - CDC Processor → Validate → Transform → Chunk (300–500 tokens) → Enrich Relationships → Compute Temporal Status → **Build Graph** (if enabled) → Enrich Metadata (incl. authz tags) → Embed → Sync to Bedrock KB.
3. **Schema Discovery**
   - Nightly (and on‑demand) Describe‑based discovery updates **Schema Cache** with real fields, picklists, relationships, and relevance scores.
4. **Schema‑driven export**
   - Batch export uses Schema Cache API to generate SOQL field lists, ensuring planner expectations match exported graph attributes.
5. **Derived views**
   - Maintained from CDC + nightly backfill; used for aggregation queries.

---

## 6. Configuration & “Zero‑Config” Model

**Primary admin control: `IndexConfiguration__mdt`**
- Which objects are indexed (`Enabled__c`).
- Text and long‑text fields to chunk.
- Relationship fields for enrichment/graph.
- Graph enablement + depth + node attributes.
- Display name field for results.
- **Semantic hints** (keywords/aliases like “space”, “building”, “suite”).

**Automatic sources**
- **Schema Cache** (Describe API):
  - filterable, numeric, date, text, relationship fields
  - picklist values
  - `has_record_types` ⇒ auto‑include `RecordType.Name`
  - relevance scores (defaulted + signal‑harvested)
- **Vocab Cache**:
  - term→field/value mappings from schema, layouts, record types, picklists
  - auto‑seeded entity names from graph nodes
- **Signal harvesting (v1.1)**:
  - Saved Searches/ListViews/SearchLayouts add relevance scores and primary relationships.

**Fallback order**
1. Config cache (IndexConfiguration)
2. Schema cache
3. Defaults (minimal safe set)

---

## 7. Current State & Recent Milestones

- **2025‑12‑11:** Canary Phase 2 complete; **planner at 100% traffic**; 6/6 acceptance scenarios passing.  
- **2025‑12‑10:** Major zero‑config hardening:
  - **Fake schema fields removed** (40% fabricated) and replaced with Describe‑verified fields.
  - **Schema‑driven batch export integrated** via Schema Cache API.
  - **Relevance scoring + planner disambiguation wired** end‑to‑end.
  - **Aggregation priority + short‑circuit fixes** (derived views no longer override specific graph results; aggregations bypass zero‑candidate short‑circuit).
  - **Signal harvesting spec promoted to v1.1** and tasks implemented.
- **Earlier:** POC steel thread, CDC ingestion stabilized, streaming UI delivered, Phase 2 agent actions with preview/confirm + audit object.

**Latest change log:** read the newest file in `docs/handoffs/` (sorted by date).

---

## 8. SLOs / Quality Targets (Load‑Bearing)

| Metric | Target |
|---|---|
| Planner latency | ≤500ms p95 (hard cutoff) |
| Retrieve latency | ≤1.5s p95 simple / ≤5s p95 complex |
| First token latency | ≤800ms p95 |
| Empty‑result rate | <8% for valid queries |
| Precision@5 | ≥75% |
| CDC freshness | p95 <10 minutes |
| Security | zero sharing/FLS leaks |

---

## 9. Common Pitfalls & Fast Debugging

- **Schema drift** is the #1 failure mode. Planner and export must use the **same Schema Cache**.
- **Graph short‑circuit**: 0 candidates should return empty **only for non‑aggregation intents**.
- **Derived view priority**: never override a specific graph‑filtered candidate set.
- **RecordType handling**: always rely on `RecordType.Name` auto‑inclusion, not manual guesses.

**Where to look first**
- Retrieve Lambda logs for: decomposition output, graph candidates count, fallback reasons.
- Schema Cache contents for missing/fake fields.
- Derived view tables for aggregation gaps.
- Latest handoff for recently touched logic.

---

## 10. Reading Map (Priority Order)

1. `docs/guides/onboarding.md` — tactical repo orientation + debugging checklists.
2. `.kiro/specs/graph-aware-zero-config-retrieval/requirements.md` — current product contract.
3. `.kiro/specs/graph-aware-zero-config-retrieval/design.md` — how planner/derived views/signals work.
4. `.kiro/specs/zero-config-production/*` — zero‑hardcoding goal and dynamic config model.
5. `.kiro/specs/phase3-graph-enhancement/*` — graph DB + traversal semantics.
6. Newest `docs/handoffs/*` — what changed last and why.

