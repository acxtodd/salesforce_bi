# Archived Draft: Layered Retrieval Target Architecture

Status: archived research draft from 2026-03-31, salvaged from branch
`codex/layered-retrieval-architecture` before branch cleanup.

Do not treat this as a current implementation plan without re-review. It
predates the runtime-config convergence completed in tasks 4.26-4.28; current
runtime behavior is driven by compiled Ascendix Search config artifacts in S3
via the active-version pointer, while repo YAML is only a bundled fallback.
Several lines below still describe `denorm_config.yaml` as the live canonical
source and should be read historically.

This document defines the recommended next-generation retrieval architecture for
the connector.

It assumes the current live foundation remains in place:

- canonical denormalized entity documents are still built from
  `denorm_config.yaml`
- `lambda/cdc_sync` and `lambda/poll_sync` remain the freshness entry points
- `/query` still runs a Claude tool-use loop over `search_records` and
  `aggregate_records`
- Turbopuffer remains the search backend

The proposal does not replace the current denormalized record model. It adds
specialized retrieval representations around it so the system can improve
semantic recall, cross-record reasoning, and broad synthesis without breaking
exact filtering or aggregation.

## Why Change

The current design is strong at:

- exact filtering over denormalized parent fields
- one-record-at-a-time freshness
- simple cross-object questions that can be answered from a single flattened
  row

The current design is weaker at:

- question-style recall when the user phrasing does not resemble CRM field text
- relationship-heavy retrieval when the best evidence is smaller than one full
  row
- broad synthesis questions such as portfolio, market, or account rollups
- parent-change cascade refresh across denormalized children

Those are not reasons to abandon denormalization. They are reasons to stop
forcing one document representation to serve every retrieval job.

## Design Goals

1. Keep `search_records` and `aggregate_records` viable.
2. Preserve exact aggregation semantics by continuing to aggregate only over the
   canonical entity layer.
3. Improve recall for natural-language questions without making the query path
   depend on live Salesforce joins.
4. Add a deterministic refresh graph so parent changes can trigger selective
   child re-denormalization and summary regeneration.
5. Use LLM-generated artifacts only where they are bounded, attributable, and
   regenerable.
6. Roll out in stages with offline metrics and shadow traffic before changing
   production ranking behavior.

## Non-Goals

- Do not reintroduce the old graph traversal stack.
- Do not build an LLM-extracted enterprise knowledge graph as the primary
  source of truth.
- Do not let synthetic or summary documents participate in
  `aggregate_records`.
- Do not replace the canonical entity document as the citation anchor.

## Target Retrieval Layers

The target system has four searchable document families plus one non-search
support table.

### Layer 0: Canonical Entity Documents

This is the existing index.

Purpose:

- exact filtering
- aggregation
- final citation anchor
- source of truth for record-level attributes

Storage:

- namespace: `org_{org_id}`
- required field: `doc_kind = "entity"`

Shape:

```json
{
  "id": "a0X...",
  "doc_kind": "entity",
  "object_type": "lease",
  "text": "Lease: ... | Property City: Dallas | Tenant Name: ACME",
  "vector": [ ... ],
  "last_modified": "2026-03-31T12:34:56.000+0000",
  "salesforce_org_id": "00D...",
  "property_id": "a09...",
  "property_city": "Dallas",
  "tenant_name": "ACME"
}
```

Implementation note:

- keep using `lib.denormalize.build_text()` and `build_document()`
- add `doc_kind`
- add an optional stable `content_hash` so downstream workers can skip no-op
  regeneration

### Layer 1: Question-Proxy Documents

This is the HyPE-style layer.

Purpose:

- improve recall when users ask in natural-language question form
- bridge the gap between structured CRM text and user phrasing

Storage:

- namespace: `org_{org_id}__q`

Shape:

```json
{
  "id": "q:a0X...:03",
  "doc_kind": "question_proxy",
  "anchor_record_id": "a0X...",
  "anchor_object_type": "lease",
  "text": "Which leases in Dallas expire next year for ACME?",
  "vector": [ ... ],
  "question_rank": 3,
  "source_hash": "sha256:...",
  "generator_family": "hype",
  "generator_model": "anthropic/... or template",
  "salesforce_org_id": "00D..."
}
```

Generation rules:

- generate 3 to 10 questions per anchor record
- prefer prompt-constrained generation from the canonical entity payload, not
  from arbitrary free text
- include at least:
  - direct lookup wording
  - attribute lookup wording
  - relationship wording
  - time/range wording when relevant
- if LLM generation cost is too high or quality is unstable, start with
  doc2query-style expansion or template-generated question variants

Usage rules:

- this layer is recall-only
- search returns `anchor_record_id` candidates
- final answers still cite canonical entity docs

### Layer 2: Relation-Fact Documents

This is the proposition / edge layer.

Purpose:

- capture small, high-signal facts that are currently buried inside large row
  documents
- improve relationship-aware retrieval without runtime joins

Storage:

- namespace: `org_{org_id}__fact`

Shape:

```json
{
  "id": "f:a0X...:property_city",
  "doc_kind": "relation_fact",
  "anchor_record_id": "a0X...",
  "anchor_object_type": "lease",
  "predicate": "property_city",
  "path": "PropertyId.City",
  "object_value": "Dallas",
  "text": "Lease Tower West Suite 200 is in Dallas.",
  "vector": [ ... ],
  "salesforce_org_id": "00D..."
}
```

Generation rules:

- start deterministic, not generative
- emit one fact doc per high-signal direct field and per denormalized parent
  field
- emit extra relationship facts only for curated paths already present in
  `denorm_config.yaml`
- keep text short and normalized

Examples:

- `Availability A belongs to Property P`
- `Availability A is in Dallas`
- `Lease L tenant is ACME`
- `Property P market is Uptown`

Usage rules:

- this layer is recall-only
- candidate results are de-duplicated by `anchor_record_id`
- fact hits should never be returned directly to `aggregate_records`

### Layer 3: Neighborhood Summary Documents

This is the RAPTOR-inspired layer, but adapted to Salesforce neighborhoods
rather than generic corpus clustering.

Purpose:

- answer broad synthesis questions
- provide high-level retrieval over natural record neighborhoods
- reduce the number of raw records needed in context for market or portfolio
  questions

Storage:

- namespace: `org_{org_id}__summary`

Summary families:

- `property_summary`
- `account_summary`
- `market_summary`
- `submarket_summary`
- later, if needed: `broker_summary`, `tenant_summary`, `portfolio_summary`

Shape:

```json
{
  "id": "s:property:a09...",
  "doc_kind": "neighborhood_summary",
  "summary_type": "property_summary",
  "anchor_group_id": "a09...",
  "anchor_group_name": "Tower West",
  "text": "Tower West is a Dallas office property with 4 active availabilities, 12 leases, and major tenants including ACME.",
  "vector": [ ... ],
  "member_record_ids": ["a0A...", "a0L..."],
  "member_count": 16,
  "summary_depth": 1,
  "source_hash": "sha256:...",
  "source_last_modified_max": "2026-03-31T12:34:56.000+0000",
  "generator_family": "raptor_neighborhood",
  "salesforce_org_id": "00D..."
}
```

Generation rules:

- do not run generic clustering over the whole org
- build summaries over deterministic neighborhoods already implied by
  Salesforce relationships
- compute structured rollups first
- generate natural-language summary text from that bounded rollup payload
- persist both the structured rollup and the generated text

Summary hierarchy:

- depth 1: property, account, submarket
- depth 2: market
- depth 3: optional org-wide portfolio rollups

Usage rules:

- use this layer for broad or global questions first
- use entity docs for drill-down and final citations
- if a summary cannot justify an answer on its own, use it to guide entity
  retrieval, not to replace it

### Support Layer: Index Graph Registry

This is not a search index. It is the refresh graph that closes the current
parent-change gap.

Recommended storage:

- DynamoDB table `IndexGraph`

Primary record:

```json
{
  "pk": "record#a0X...",
  "sk": "state",
  "object_type": "lease",
  "parent_ids": ["a09...", "001..."],
  "neighborhood_keys": ["property#a09...", "market#Dallas-Fort Worth"],
  "content_hash": "sha256:...",
  "last_indexed_at": "2026-03-31T12:35:10Z"
}
```

Reverse-edge records:

```json
{
  "pk": "parent#a09...",
  "sk": "child#a0X...",
  "child_object_type": "lease"
}
```

```json
{
  "pk": "group#property#a09...",
  "sk": "member#a0X...",
  "member_object_type": "lease"
}
```

Purpose:

- detect which child records must be re-denormalized after a parent change
- detect which summary neighborhoods must be regenerated after membership or
  field changes
- support delete cleanup for sidecar docs

## Query Routing Model

Add a lightweight query routing stage before tool use. It should classify the
question into one of four intents:

- `aggregate`
- `entity_lookup`
- `relationship_lookup`
- `global_summary`

Recommended insertion point:

- add a small routing helper called from `lambda/query/index.py` before
  `QueryHandler.query()`

Routing behavior:

### Aggregate

- keep current `aggregate_records`
- execute only against `org_{org_id}` with `doc_kind = "entity"`

### Entity Lookup

- `search_records` searches canonical entity docs first
- optionally merge recall candidates from question-proxy docs
- hydrate anchors back to canonical entity docs
- rerank before returning to the model

### Relationship Lookup

- `search_records` searches:
  - canonical entity docs
  - question-proxy docs
  - relation-fact docs
- de-duplicate by `anchor_record_id`
- hydrate to canonical entity docs
- rerank before returning

### Global Summary

- retrieve summary docs first
- pass summary-derived hints into the query loop
- follow with entity retrieval for evidence and citations

The initial implementation does not need a new public tool. `search_records`
can federate internally and still return canonical entity records.

## Ranking Model

The target ranking pipeline for `search_records` is:

1. candidate generation from one or more namespaces
2. anchor hydration to canonical entity docs
3. score fusion
4. reranking
5. result truncation

Recommended scoring:

- candidate generation:
  - entity namespace: existing BM25 + ANN hybrid
  - question namespace: ANN-first, BM25 optional
  - fact namespace: BM25 + ANN hybrid
- score fusion:
  - start with weighted reciprocal rank fusion across namespaces
- reranking:
  - add a cross-encoder or LLM reranker over the top 20 to 50 hydrated entity
    candidates

Important rule:

- rerank only canonical entity candidates
- do not return sidecar docs directly to the LLM unless a later implementation
  explicitly adds a summary-only tool

## Index-Time LLM Usage Rules

Use LLMs at index time only for bounded transformations.

### Allowed

- HyPE-style synthetic question generation from one canonical entity payload
- neighborhood summary generation from a deterministic rollup payload
- optional short title or abstract generation for summaries

### Not Allowed

- unconstrained graph extraction over the entire org
- free-form summaries built directly from arbitrary search results
- summary docs without stored provenance

Every generated artifact should persist:

- `source_hash`
- `generator_family`
- `generator_model`
- `prompt_version`
- `generated_at`

This makes regeneration deterministic and allows side-by-side quality checks
when prompts or models change.

## Refresh And Regeneration Flow

The canonical entity write remains the first-class event.

### On create or update

1. `cdc_sync` or `poll_sync` rebuilds the canonical entity doc exactly as it
   does today.
2. The sync path computes:
   - `content_hash`
   - current `parent_ids`
   - current `neighborhood_keys`
3. The sync path writes the entity doc.
4. The sync path compares the new graph state to the previous `IndexGraph`
   record.
5. It publishes sidecar regeneration work for:
   - question proxies for the changed record
   - relation facts for the changed record
   - neighborhood summaries whose membership or rollup inputs changed
6. If parent links changed, it updates reverse edges and schedules any affected
   child re-denormalization.

### On delete

1. delete the canonical entity doc
2. delete sidecar docs keyed to the anchor record
3. remove `IndexGraph` forward and reverse edges
4. regenerate affected summaries

### On parent update

1. handle the parent entity update normally
2. use `IndexGraph` reverse edges to find denormalized children
3. enqueue those child record ids for re-denormalization
4. enqueue affected summary groups

### On config refresh

When `lambda/config_refresh` changes field scope or relationships:

- rebuild affected canonical entity docs first
- then rebuild affected question and fact docs
- then rebuild affected summaries

Do not regenerate sidecar indexes before the canonical layer is current.

## Proposed New Components

Add:

- `lib/query_router.py`
- `lib/federated_retriever.py`
- `lib/index_graph.py`
- `lib/question_proxy.py`
- `lib/relation_facts.py`
- `lib/neighborhood_summary.py`
- `lambda/index_enrichment/index.py`
- `tests/test_query_router.py`
- `tests/test_federated_retriever.py`
- `tests/test_index_graph.py`
- `tests/test_question_proxy.py`
- `tests/test_relation_facts.py`
- `tests/test_neighborhood_summary.py`

Extend:

- `lambda/query/index.py`
- `lib/query_handler.py`
- `lib/tool_dispatch.py`
- `lambda/cdc_sync/index.py`
- `lambda/poll_sync/index.py`
- `lib/denormalize.py`

Responsibilities:

- `cdc_sync` and `poll_sync` continue to own canonical entity writes
- `index_enrichment` owns sidecar generation and refresh-graph maintenance
- `query_router` and `federated_retriever` own multi-index recall and ranking

## Rollout Order

### Phase 1: Instrument And Protect

- add `doc_kind = "entity"` to canonical docs
- add `content_hash`
- add `IndexGraph`
- add regression tests for aggregate isolation

Exit criteria:

- no behavior regression in `search_records`
- no behavior regression in `aggregate_records`
- parent-change cascade jobs can be scheduled deterministically

### Phase 2: Add Reranking

- keep retrieval on the canonical entity namespace
- add reranking of top candidates before returning results

Exit criteria:

- offline ranking gain with no unacceptable latency regression

### Phase 3: Add Question Proxies

- generate question-proxy docs for `Availability` and `Lease` first
- shadow-rank against baseline
- only then merge into production scoring

Exit criteria:

- measurable recall lift on question-style benchmarks
- acceptable index-time cost per changed record

### Phase 4: Add Relation Facts

- generate deterministic fact docs for `Availability`, `Lease`, `Property`
- federate them into `search_records`

Exit criteria:

- measurable gain on relationship-heavy questions
- no aggregate contamination

### Phase 5: Add Neighborhood Summaries

- start with `property_summary`, `account_summary`, `market_summary`
- use summaries only for routed `global_summary` queries

Exit criteria:

- measurable gain on broad synthesis questions
- acceptable freshness lag after member-record changes

## Evaluation Plan

Build an offline benchmark with four buckets:

1. exact filter queries
2. question-style semantic queries
3. relationship-heavy queries
4. global synthesis queries

Suggested sources:

- Ascendix saved searches as structural fixtures
- historical user queries from `/query` logs
- synthetic gap-focused queries authored from real denormalized records

Primary retrieval metrics:

- Recall@10 and Recall@20 on anchor record ids
- MRR@10
- nDCG@10

Primary answer metrics:

- citation precision
- citation coverage
- groundedness / unsupported-claim rate
- answer task success on a reviewed rubric

Operational metrics:

- P50 and P95 query latency
- P95 freshness lag after CDC or poll-sync writes
- sidecar regeneration cost per changed record
- summary regeneration queue depth

Acceptance rules by layer:

- question proxies must improve recall on question-style queries by a meaningful
  margin without increasing unsupported answers
- relation facts must improve relationship queries without harming exact lookup
  quality
- summaries must improve global synthesis tasks without becoming the only cited
  evidence

## Recommended Initial Scope

Do first:

- `Availability`
- `Lease`
- `Property`
- `Account`

Why:

- these objects already drive the strongest denormalized value
- they cover both CRE and CRM query shapes
- they provide clear natural neighborhoods for summaries

Do later:

- `Task`
- `Inquiry`
- `Listing`
- `Preference`
- `Sale`
- `Deal`

Those objects can join once the federation and refresh graph are proven.

## Explicit Decisions

- Keep the canonical entity document as the citation anchor.
- Keep `aggregate_records` entity-only.
- Use separate namespaces for sidecar layers to avoid double counting and
  reduce accidental tool-surface leakage.
- Prefer deterministic relationship neighborhoods over generic GraphRAG graph
  extraction.
- Use RAPTOR-style summaries only over bounded Salesforce neighborhoods, not
  over the full org corpus.
- Treat HyPE-style question generation as a recall booster, not as a new source
  of truth.

## Why This Is Better Than A Generic GraphRAG Rewrite

The connector already has a real graph: Salesforce foreign keys plus the
compiler-generated denormalization contract.

The right move is to:

- materialize the useful parts of that graph deterministically
- add retrieval representations tuned to different question classes
- keep final answers anchored in canonical records

That yields most of the practical value that people want from "graph search"
without paying the complexity cost of runtime traversal or full LLM-extracted
knowledge-graph maintenance.

## Research Inputs

The proposal was shaped by:

- RAPTOR: recursive summary trees for retrieval augmentation
- HyPE-style hypothetical prompt or question indexing for query-form recall
- doc2query and related document expansion work
- proposition-level retrieval results showing that smaller retrieval units can
  outperform coarse chunks
- heterogeneous RAG findings that retrieval and generation benefit from
  different document representations

Useful references:

- RAPTOR: https://arxiv.org/abs/2401.18059
- HyPE preprint: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5139335
- HyDE: https://arxiv.org/abs/2212.10496
- doc2query: https://arxiv.org/abs/1904.08375
- Query2doc: https://arxiv.org/abs/2303.07678
- Dense X Retrieval: https://arxiv.org/abs/2312.06648
- HeteRAG: https://arxiv.org/abs/2504.10529
- GraphRAG: https://arxiv.org/abs/2404.16130
- BenchmarkQED: https://www.microsoft.com/en-us/research/blog/benchmarkqed-automated-benchmarking-of-rag-systems/

---

## Addendum: BA Review And Commentary

_Added 2026-03-31 after independent analysis of HyPE, RAPTOR, and index-time
LLM summaries against the current production baseline._

### Overall Assessment

This document is architecturally sound. The core insight — stop forcing one
document representation to serve every retrieval job — directly addresses
real weaknesses in the current system. The QA adapted academic techniques to
our specific constraints (CDC freshness, structured CRM data, existing
tool-use loop, aggregate integrity) rather than proposing generic adoption.

The remainder of this addendum captures areas where the BA analysis diverged,
risks that deserve explicit tracking, and sequencing recommendations.

### What This Document Gets Right

**Async sidecar generation solves the CDC latency problem.** Independent
analysis identified CDC latency as the primary blocker for any index-time LLM
work. The current CDC path processes a record in ~1 second; adding a
synchronous LLM summary call would push that to 3-6 seconds. This document
solves it cleanly: canonical entity writes stay on the fast path, sidecar
documents (questions, facts, summaries) regenerate asynchronously via
`lambda/index_enrichment`. The freshness contract is preserved.

**Deterministic neighborhoods avoid RAPTOR's clustering instability.**
Independent analysis rejected RAPTOR because unsupervised clustering produces
non-deterministic tree structures that don't align with CRE business
hierarchies. This document sidesteps the problem entirely by using Salesforce
FK-based groupings (Property rollups, Account rollups, Market/Submarket
rollups) instead of algorithmic clusters. The hierarchy is real and stable.

**Aggregate isolation is explicitly protected.** The separate-namespace
strategy (`org_{id}__q`, `org_{id}__fact`, `org_{id}__summary`) with
`doc_kind` fencing ensures that `aggregate_records` only touches canonical
entity documents. This preserves the current exact-aggregation semantics that
users depend on.

**The IndexGraph refresh model closes a real gap.** The parent-change cascade
is a known weakness today. When a Property's city changes, we re-fetch child
records via SOQL and re-embed, but the trigger depends on the child record
itself appearing in a CDC event or poll-sync window. The DynamoDB reverse-edge
design enables deterministic fan-out from parent changes to affected children
and summary groups.

### Areas Of Concern

#### 1. Layer 2 (Relation-Fact Documents) may not carry its weight

The proposal generates micro-propositions like `"Lease Tower West Suite 200 is
in Dallas."` The claimed benefit is capturing small, high-signal facts buried
inside large row documents.

However, our entity documents are not large unstructured chunks. They are
structured field concatenations where every fact is already atomic and
filterable. `property_city = "Dallas"` is already a first-class attribute on
every Lease document, and the embedding text already contains
`"Property City: Dallas"`. Proposition-level retrieval research (Dense X
Retrieval) shows the strongest gains when applied to long-form documents like
PDFs or knowledge articles where key facts are buried in paragraphs — not to
structured CRM records where facts are already disaggregated.

**Recommendation:** Defer Layer 2 until query-log evidence shows specific
relationship-retrieval failures that Layers 0, 1, and 3 cannot address. If
Layer 2 is pursued, start with a narrow pilot (e.g., only cross-object
relationship facts, not direct-field facts that are already filterable) and
measure incremental recall lift against the baseline with Layers 0+1 already
active.

#### 2. Query routing adds a classification step that could conflict with tool use

The proposed 4-way intent classifier (`aggregate`, `entity_lookup`,
`relationship_lookup`, `global_summary`) runs before the Claude tool-use loop.
But Claude already performs implicit routing — it decides whether to call
`search_records` or `aggregate_records` based on the question.

Two routing decisions in series create a disagreement surface. A pre-router
that classifies *"Show me top 5 markets by available SF with declining
occupancy"* as `aggregate` might prevent the tool-use loop from also pulling
summary context that would help with the "declining" qualifier.

The document itself acknowledges this tension: *"The initial implementation
does not need a new public tool. `search_records` can federate internally and
still return canonical entity records."* Internal federation within
`search_records` avoids the pre-classification problem entirely and is more
consistent with the existing architecture.

**Recommendation:** Implement multi-namespace federation inside
`search_records` and `tool_dispatch.py` rather than adding a pre-router. If
query-log analysis later reveals systematic misrouting by the tool-use loop,
revisit the pre-classification approach with evidence.

#### 3. The evaluation baseline does not exist yet

The evaluation plan proposes Recall@10, MRR@10, nDCG@10 across four query
buckets — this is textbook-correct. But we do not currently measure any of
these metrics. Every phase's exit criteria depend on showing "measurable recall
lift" or "no regression," which requires a labeled baseline.

Building the evaluation harness — a set of 50-100 queries with labeled
relevant records across the four query categories — is a prerequisite for
every phase of this plan. Without it, the exit criteria are unmeasurable and we
risk shipping complexity without proven value.

**Recommendation:** Scope the evaluation harness as a standalone task that
precedes or runs in parallel with Phase 1. Sources: Ascendix saved searches
(structural fixtures), historical `/query` audit logs, and synthetic
gap-focused queries authored from real denormalized records. This investment
pays off regardless of whether the full layered architecture is pursued.

#### 4. The cost model is absent

The document does not estimate:

- LLM cost per record for question generation (3-10 questions × ~500 input
  tokens + ~200 output tokens each)
- LLM cost per summary neighborhood (structured rollup + narrative generation)
- DynamoDB read/write cost for IndexGraph at scale
- Additional Turbopuffer storage for 3 new namespaces
- Lambda compute cost for `lambda/index_enrichment`

Back-of-envelope at current scale (14,861 records):

- Question proxies: 14,861 records × 5 questions × ~700 tokens ≈ 52M tokens.
  At Haiku pricing (~$0.25/MTok input, ~$1.25/MTok output) ≈ $15-25 for full
  generation. Regeneration on CDC (~100 events/day) ≈ $0.10/day.
- Neighborhood summaries: ~2,500 Property + ~4,700 Account + ~50 Market
  summaries ≈ 7,250 summaries × ~1,500 tokens each ≈ 11M tokens ≈ $5-10 for
  full generation.
- Turbopuffer: index grows from ~15K to ~90-100K vectors. Storage cost
  increase is modest.
- DynamoDB: ~15K items + ~30K reverse edges. Well within on-demand free tier
  at this scale.

Total estimated monthly cost at current volumes: under $50/month. The cost
concern is not the dollar amount — it is the operational complexity of
managing regeneration queues, handling generation failures, and debugging
stale sidecars.

**Recommendation:** Add cost estimates per phase to the rollout plan. Track
operational complexity (queue depth, regeneration failure rate, staleness
p95) alongside retrieval metrics.

#### 5. Implementation scope is large relative to Phase 4 remaining work

The component list is substantial: 6 new modules, 6 new test files, 1 new
Lambda, 1 new DynamoDB table, and extensions to 6 existing files. Phase 4
still has 19 pending tasks including user-facing features (write-back 4.17,
RecordType indexing 4.16, Apollo enrichment 4.19).

**Recommendation:** Position this as a Phase 5 initiative, not a Phase 4
task. Phase 1 of this plan (instrument + IndexGraph) is low-risk and delivers
independent value (parent-change cascade fix), so it could be pulled into
late Phase 4 if capacity allows. Phases 2-5 should follow after Phase 4
user-facing work is delivered.

### Revised Layer Priority

After synthesizing both the QA analysis and independent BA review:

| Layer | Priority | Rationale |
|-------|----------|-----------|
| Phase 1: Instrument + IndexGraph | **High — do first** | Low risk, solves real parent-cascade gap, prerequisite for everything else |
| Evaluation harness | **High — do in parallel with Phase 1** | Prerequisite for measuring value of all subsequent phases |
| Phase 2: Reranking | **Medium** | Improves result quality within existing retrieval, no new index infrastructure |
| Phase 3: Question proxies (Layer 1) | **Medium** | Strongest recall-lift case for natural-language queries, but value depends on baseline measurement |
| Phase 5: Neighborhood summaries (Layer 3) | **Medium-Low** | Real value for portfolio/market queries, but `aggregate_records` already handles most cases today |
| Phase 4: Relation facts (Layer 2) | **Low — defer** | Weakest case for structured CRM data; pursue only if query-log evidence shows specific failures |

### Open Questions For Stakeholder Review

1. Do we have query-log evidence of semantic recall failures today? If the
   tool-use loop already compensates for embedding-gap queries via structured
   filters, the ROI of Layers 1-3 may be lower than expected.

2. What is the acceptable freshness lag for sidecar documents? The canonical
   entity stays fresh within seconds (CDC). If a question-proxy or summary
   takes 30 seconds to regenerate, is that acceptable? 5 minutes? The SLA
   drives the `index_enrichment` Lambda's concurrency and cost profile.

3. Should the evaluation harness be scoped as a standalone task now,
   independent of the layered retrieval decision? Its value extends to prompt
   tuning, model upgrades, and regression testing regardless of this
   architecture.

4. Is there a user-facing pain point today that would serve as a compelling
   pilot for one specific layer? A concrete before/after demo is more
   persuasive than retrieval metrics for stakeholder buy-in.
