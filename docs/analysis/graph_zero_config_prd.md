# Graph-Aware Zero-Config Retrieval PRD

## Goal
Translate natural-language CRE queries into structured graph + KB filters without per-query hard-coding; bind user intent to the correct objects/fields/values and return precise, authorized results.

## Outcomes & Targets
- Binding accuracy (precision/recall on test set ≥0.90/0.90).
- p95 retrieval latency ≤1.0s (≤1.5s when graph path used); planner SLO ≤500ms with hard cutoff/fallback; traversal ≤400ms.
- Freshness: CDC end-to-end P95 < 10 minutes; nightly backfill completes < 2 hours.
- Quality: precision@5 ≥ 0.75, empty-result rate < 8%, fallback-to-vector-only < 10%.
- <2% of results depend solely on name-text matches when structured fields exist.

## Scope
- Intent→structured-plan layer (planner) ahead of vector search.
- Auto schema/vocab ingestion from Salesforce Describe, RecordTypes, picklists, page layouts; EventLog for query terms. (Report mining deferred.)
- Graph traversal planning (target node, predicates, depth) and structured filters passed to Bedrock KB + graph tables, with hard caps: max depth 2 (configurable), max nodes visited per query (e.g., 50–100), timeouts.
- Derived views/rollups to avoid runtime aggregation where possible (materialized physical views):
  - `availability_view` (size, status, TI hints, link to property)
  - `vacancy_view` (vacancy %, available sqft per property)
  - `leases_view` (end dates, tenant, ROFR/TI/noise/HVAC flags from notes)
  - `activities_agg` (counts 7/30/90d per entity; last-activity timestamps; maintenance-only counts)
  - `sales_view` (stage, close date, brokers)
- (Postpone) Bounded Aggregation Agent: keep design on ice; do not ship initially. Re-evaluate after rollups + planner metrics. If enabled later, it must be guardrailed (allowlist, FLS, timeouts, row limits) and behind a feature flag.
- Prompt/data-plane changes only (no UI redesign).

Out of scope: new data sources beyond SF/Bedrock/OpenSearch; security model changes beyond those listed.

## Objects & Fields (discover per org)
- Property: RecordType.Name (type), PropertyClass__c (class), City/State/Submarket, size fields (Total/Available/Common Area), Vacancy%, Ownership (Company).
- Availability: Size, Status, Notes, link to Property.
- Lease: EndDate/Term, Status, clauses (notes/long text), Tenant (Company/Contact).
- Sale Transaction: Stage, CloseDate, Brokers, Amount.
- Activity (Task/Event): Type, Date, RelatedTo, Who/What, Completed flag.
- Company/Contact: Role/Title, Industry, Parent, owned property count.
- Notes: Body text linked to parent (Property/Lease/Availability/Sale/Activity).

## Functional Requirements
1) Planner emits `{targetObject, predicates[], traversalPlan, seedIds?, confidence}`.
2) Entity/field linker uses auto-built vocab (labels, picklists, RecordTypes, report columns, query usage).
3) Value normalization: date windows, ranges (sf, vacancy%), stages, roles, industries, geos.
4) Traversal strategy (depth 0–2 by default; configurable) chooses hops (e.g., Property→Availability, Company→Property, Sale→Activity) with node/edge caps and timeouts.
5) Execution: if seedIds -> filter KB by recordId; else apply structured filters to KB and graph traversal with same predicates; enforce node/edge caps and timeouts.
6) Fallback: low confidence → current hybrid vector; log miss.
7) Telemetry: planner I/O, filters applied, hits/misses, latency, user corrections; log rollup gaps and traversal caps triggered.
8) Learning loop: nightly vocab rebuild from Describe, picklists, RecordTypes, page layouts; EventLog query terms; optional linker fine-tune from logged misses. (Report mining deferred.)
9) Field relevance scoring: start with layout/Describe/RecordType signals; inject top-N per query into planner/prompt hints (report signals can be added later).
10) Prompting: retrieval/answer prompts prefer schema-bound filters; supply top-N vocab hints per query.
11) Rollups are the primary path for aggregation/NOT-exists asks. If a required rollup is missing, fall back to vector+filter and log the gap; only after evaluation consider enabling the (postponed) Aggregation Agent behind a flag.
12) Entity resolution: resolve names to IDs (Accounts/Contacts/Properties) via lightweight exact/approx index before applying filters to reduce text matches and enforce auth.

## Non-Functional
- Reliability: planner failure must not fail request; graceful fallback.
- Security & Ingress: private API (VPC/PrivateLink); remove public Function URLs; API key/Named Credential only. AOSS encrypted with CMK; IAM scoped to single collection/index; env-suffixed tables/secrets.
- Observability: dashboards for latency, freshness, quality, cost (OCU, Bedrock calls), planner confidence, CDC lag; alarms on CDC lag, fallback spikes, latency regressions.
- Zero-config: no manual field lists; all from discovery/usage mining per org.

## Acceptance Scenarios (must pass)
1. Available Class A office space in Plano → target Availability; filters Property.RecordType=Office, PropertyClass=Class A, City=Plano.
2. Available industrial properties in Miami, FL 20k–50k sf → Availability; Property.Type=Industrial; City=Miami; State=FL; Availability.Size range.
3. Class A office buildings downtown with vacancy >0 → Property; PropertyClass=Class A; RecordType=Office; Submarket~Downtown; Vacancy>0 or Availability exists.
4. Leases expiring in next 6 months → Lease; EndDate window.
5. Activities on Property 123 Main Street last 30 days → Activity; WhatId=Property; Date range; completed+open.
6. Contacts with ≥5 activities last week and Sale stage=Negotiation → Contact; activity count; related Sale Stage.
7. Sales where Broker=Jane Doe and Stage=Due Diligence → Sale; Broker contact; Stage.
8. Companies owning ≥10 retail properties in PNW → Company; count Properties Region∈PNW; Type=Retail.
9. Properties with vacancy rate >25% → Property; Vacancy%.
10. Notes containing “HVAC system needs replacement” → Note; return linked parent IDs.
11–20: advanced multi-hop scenarios (leases Q3 2026 + no activity; Midtown sale comps with opposing broker; availability where largest tenant >50k sf; tours with noise complaints; data-center suitable availability with no finance tenants; post-close issues; ROFR clause; companies with multi-state leases; lost sales brokers + last 3 activities; availability notes offering full TI).

- Use derived views (`vacancy_view`, `activities_agg`, `leases_view` flags, `sales_view`) as physical/materialized data (DDB items/attributes) to answer counts, vacancy%, NOT-exists (e.g., “no activity in 90 days”), and flag extraction (ROFR/TI/noise/HVAC) without runtime GROUP BY where feasible.
- If rollup missing, fall back to vector+filter and log the gap. The Aggregation Agent is postponed; only consider enabling (behind a flag) after observing gaps and latency/quality metrics.

## Tests
- Planner unit tests: query → predicates/traversal for scenarios 1–20 (mock SchemaCache with RecordType/PropertyClass/size/vacancy fields).
- Value normalization tests: date windows, size ranges, “next 6 months”, “last 30 days/5 years”.
- Linker tests: synonyms → fields (Class A → PropertyClass__c; office → RecordType.Name=Office; vacancy → Vacancy%).
- Graph traversal tests: seeded graph verifies matchingNodeIds for multi-hop cases (1,3,11,13,15,18).
- Integration: Retrieve Lambda with fixtures; assert KB filters & seeds; assert IDs returned.
- Regression: nightly suite over 20 scenarios; track precision/recall, latency, fallback rate.
- Canary: shadow mode (logs only) → 20% traffic with filters enforced; monitor misses/user corrections.

## Observability & Dashboards
- Metrics: planner confidence, binding precision@k, fallback rate, empty-result rate, latency (planner/graph/KB total), CDC lag, rollup freshness, AOSS OCU, Bedrock invocations, authz cache hit rate.
- Dashboards: latency SLO, quality (precision@5, empty rate), freshness, cost, errors; alerts on SLO breaches and CDC lag >10m.

## Rollout & Timeline
- Phase 0: planner shadow logging (no user impact).
- Phase 1: 20% traffic; structured filters enforced; monitor precision/latency.
- Phase 2: 100% with nightly regression gate; vocab refresh enabled.
- Phase 3: optional linker fine-tune from logged misses/corrections.

- Target timeline (6 weeks):
  - Week 1: Ingress/IAM hardening; schema-cache perms; temporal normalizer stub.
  - Week 2: Build derived views (availability, vacancy, leases flags, activities_agg, sales_view).
  - Week 3: Planner intents/routing; traversal rules; filter-first execution; disambiguation path.
  - Week 4: Synthetic harness + dashboards; tune topK per intent.
  - Week 5: Perf tuning (caches, OCU caps, embed batching); CDC lag alarms; shadow → 20%.
  - Week 6: Gate to 100% (≥90% suite pass, SLOs green); runbooks for schema diff/index health/fallback toggles.

## Data Fixtures (minimal)
Properties (office/industrial/retail; classes; cities/states/submarkets; vacancy%; size fields); Availabilities (sizes/status/notes, linked); Leases (EndDate, notes with clauses, tenants); Sales (stages, brokers, close dates); Activities (types, dates, Who/What, completion); Notes (HVAC, TI, noise); Companies/Contacts (roles, industries, ownership links).

## Open Items / Assumptions
- RecordType.Name is property type; PropertyClass__c holds class (verify per org).
- Size/vacancy fields may be on Property and/or Availability; planner should try both and log gaps.
- Activities: standard Task/Event, include completed; Notes entity available.
- Geos/regions/submarkets vary by org; discover via picklists/RecordTypes/report usage.
- No PII mining in this phase; EventLog/report mining limited to field names/usage counts.

## R&D Appendix (flagged / not in v1 path)
- Report & Layout Mining: mine SF reports/layouts to derive field relevance scores; use as optional signal for planner prompts and to propose new rollups. Ship behind a flag after data-quality validation.
- Aggregation Agent (runtime SOQL): postponed; only consider as an explicit opt-in “deep analysis” mode with strict guardrails, separate SLO (≤3s), and user opt-in.
- Deeper Traversal: depth>2 only if node cap and timeout budgets permit, and only when backed by precomputed hops; otherwise remain off by default.
- Ascendix Search Artifacts (signals to harvest when R&D is enabled):
  - Saved searches in `ascendix_search__Search__c` (e.g., “Office Availabilities” targeting `ascendix__Availability__c`).
  - Search settings in `ascendix_search__SearchSetting__c` with JSON (`ascendix_search__Value__c`) listing selected objects (Account, Contact, Availability, Deal, Lease, Property, Sale, Lead, etc.) and map/geo/ad-hoc flags.
  - Existing reports (recently run): Properties by Type, Leases in All Properties (namespace `ascendix`), Deals by Stage & Type, Lease Expirations, Listings with Activities, Calls Made This Week; folder “AI Agent Actions Analytics” with Daily Action Counts / Failure Reasons / Top Objects Modified (not recently run).
  - Use these only as discovery signals for object/field importance, relationship patterns, and candidate rollups/boosting; do not rely on them in v1 execution.
