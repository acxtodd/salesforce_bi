# AscendixIQ Salesforce Connector — Unified Product & Design Specification

**Status:** DRAFT — Open for Collaboration
**Authors:** Todd / Claude
**Date:** 2026-03-14
**Version:** 0.1
**Supersedes:** ASCENDIXIQ_AGENTIC_SEARCH_BACKEND_PRD.md, ASCENDIXIQ_SALESFORCE_CONNECTOR_PDR.md

---

## Table of Contents

1. [Context & Problem Statement](#1-context--problem-statement)
2. [Product Vision](#2-product-vision)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [Users & Jobs To Be Done](#4-users--jobs-to-be-done)
5. [Current-State Assessment](#5-current-state-assessment)
6. [Design Principles](#6-design-principles)
7. [Target Architecture](#7-target-architecture)
8. [Denormalized Document Model](#8-denormalized-document-model)
9. [Query Architecture — LLM Tool-Use](#9-query-architecture--llm-tool-use)
10. [Connector Layer — Salesforce Sync](#10-connector-layer--salesforce-sync)
11. [Permission Model](#11-permission-model)
12. [Infrastructure & Cost](#12-infrastructure--cost)
13. [Migration Strategy](#13-migration-strategy)
14. [What We Keep, What We Delete, What We Defer](#14-what-we-keep-what-we-delete-what-we-defer)
15. [POC Scope & Success Criteria](#15-poc-scope--success-criteria)
16. [POC Implementation Plan](#16-poc-implementation-plan)
17. [Risks & Mitigations](#17-risks--mitigations)
18. [Resolved Contradictions](#18-resolved-contradictions)
19. [Decision Log](#19-decision-log)
20. [Open Questions](#20-open-questions)
21. [Appendix: Reference Architecture](#21-appendix-reference-architecture)

---

## 1. Context & Problem Statement

### What we built

A graph-enhanced RAG system for CRE Salesforce data: 6 CDK stacks, 16+ Lambdas, 12+ DynamoDB tables, OpenSearch Serverless, Bedrock KB, Step Functions pipeline, custom planner/decomposer/graph traversal. Technically validated (83% acceptance test pass rate, 5/6 scenarios passing).

### Why it cannot be productized as-is

| Problem | Detail |
|---------|--------|
| **Cost floor** | ~$500-1K/mo per org (OpenSearch Serverless OCU minimum, VPC endpoints, Bedrock KB sync, DynamoDB graph). Cannot offer at a price point customers will pay. |
| **Complexity** | 6 AWS stacks, 12+ DynamoDB tables, 8-step ingestion pipeline. Every bug crosses 3-4 services. Operational cost of maintaining this is prohibitive. |
| **Multi-tenant economics** | Each new customer org adds near-linear cost. No way to park inactive tenants cheaply. |
| **Vendor coupling** | Retrieval logic is hard-coded to Bedrock KB and OpenSearch Serverless semantics. Switching backends would require rewriting production handlers. |
| **Permission gaps** | Incomplete FLS support. Sharing bucket computation is complex, incomplete, and a security risk when stale. |
| **Over-engineering** | Zero-config schema discovery, graph traversal, derived views — built for generality when we own the schema and know the queries. |

### What changed

1. **Turbopuffer** emerged as a viable search backend: serverless, object-storage-native, 10-50x cheaper at rest, namespace-per-tenant isolation with cold/warm tiering. Proven at scale by Notion (10B+ vectors, 1M+ namespaces), Cursor (tens of millions of namespaces), and Anthropic.
2. **Notion shipped a Salesforce AI Connector** on Turbopuffer — proving the pattern works at production scale for CRM data. Scoped to 4 standard objects, no FLS, no graph traversal. Ships as a feature, not a platform.
3. **LLM tool-use matured** — multi-agent query patterns (parallel tool calls, synthesis) can replace rigid planner + graph traversal pipelines with more flexibility and less code.

### The thesis

Replace the search/graph/aggregation/orchestration infrastructure with Turbopuffer + LLM tool-use. Keep the Salesforce integration work, CRE domain knowledge, and LWC UI. Ship as the **AscendixIQ Salesforce Connector** — the first connector in the AscendixIQ Search Platform.

> **Scope acknowledgment:** This is broader than a search-plane swap. The orchestration layer (planner, decomposer, intent router, query executor) was tightly coupled to the Bedrock KB / OpenSearch substrate it was built for. Replacing the search plane without replacing the orchestration that wraps it would create an impedance mismatch. This spec addresses both planes as a coordinated replacement.

---

## 2. Product Vision

**One-liner:** AscendixIQ lets CRE professionals ask questions about their Salesforce data in natural language and get instant, accurate, grounded answers — powered by agentic search and Claude reasoning.

The backend should support:

- semantic search over Salesforce records and notes
- exact filtering over structured Salesforce fields
- cross-object retrieval for common business questions
- live query fallbacks for questions that need freshest state or exact aggregations
- citations and traceability for agent answers
- a connector pattern reusable across future systems (Yardi, CoStar, HubSpot)

### Product framing

- **The deliverable** is the "AscendixIQ Salesforce Connector" — a concrete, shippable feature.
- **The platform it plugs into** is the "AscendixIQ Search Platform" — the shared backend that future connectors will also use.
- This distinction matters: connector-level decisions (which Salesforce objects, CDC mechanism, denormalization rules) are scoped to this connector. Platform-level decisions (search backend protocol, canonical document schema, namespace strategy) are designed for reuse.

---

## 3. Goals & Non-Goals

### 3.1 Product Goals

- Provide a reusable backend for Ascendix products, not a one-off Salesforce demo stack.
- Make Salesforce data searchable by agents with both semantic and structured retrieval.
- Support the most valuable CRE and CRM search workflows first.
- Create a foundation that can later support additional connectors.

### 3.2 Technical Goals

- Replace Bedrock KB + OpenSearch Serverless + custom orchestration as the primary search and query substrate.
- Own the canonical search document schema and indexing lifecycle.
- Support direct upsert and delete semantics.
- Separate indexed retrieval from live Salesforce query execution.
- Reduce infrastructure from 6 CDK stacks / 16+ Lambdas / 12+ DynamoDB tables to ≤2 stacks / ~3 Lambdas / 1-2 tables.

### 3.3 Business Goals

- Reduce fixed infrastructure cost per tenant by at least 50% (target: 70%+).
- Enable multi-tenant economics where inactive orgs cost pennies, not hundreds of dollars.
- Reduce operational complexity and vendor-specific coupling.
- Create a platform asset that multiple Ascendix products can share.

### 3.4 Non-Goals

- Perfect replication of all Salesforce sharing and FLS edge cases in POC or v1.
- Building a general-purpose BI warehouse.
- Supporting every Salesforce object or every advanced analytical query in POC.
- Rewriting the Salesforce LWC/UI surface before the backend seam is established.
- Building a non-Salesforce connector in this phase.

---

## 4. Users & Jobs To Be Done

### 4.1 End Users

- Brokers, researchers, and operators who want fast answers about properties, leases, deals, availabilities, contacts, and notes.
- Internal users who want search and grounded AI assistance inside Salesforce or adjacent Ascendix apps.

### 4.2 Agent Users

- Retrieval agents that need relevant records and citations.
- Workflow agents that need search first, then live Salesforce actions.
- Analyst-style agents that need exact answers or follow-up live queries for counts, sorting, and latest-state checks.

### 4.3 Jobs To Be Done

- "Find the most relevant records for this question."
- "Search notes and long text, but respect structured filters."
- "Show me records connected across common parent/child relationships."
- "Answer with citations I can inspect."
- "If the answer requires exact fresh state or aggregation, use a live query path instead of pretending semantic search is enough."

---

## 5. Current-State Assessment

### What works

- Narrow semantic retrieval over indexed Salesforce content
- Some graph-filtered cross-object queries
- Some derived-view-backed aggregation shortcuts
- Streaming answer UX
- CRE domain knowledge: temporal parsing, value normalization, entity linking vocabulary
- Salesforce integration: CDC processing, batch export, schema discovery
- Salesforce-native packaging: LWC, Apex controller, named credentials

### What does not scale

- Bedrock KB-centric ingestion and retrieval flow
- OpenSearch Serverless cost floor (~$350/mo minimum)
- Custom planner/decomposer/intent router tightly coupled to search substrate
- DynamoDB graph (12+ tables, complex traversal code)
- Duplicate embedding and indexing concerns
- Incomplete delete propagation
- Incomplete FLS support
- Post-filter-heavy authorization
- Vendor-specific logic spread directly into production handlers

---

## 6. Design Principles

1. **Own the search contract.** Our canonical document schema should not be dictated by a managed KB product. Define it ourselves, index it ourselves.
2. **Split indexed and live retrieval.** Search and exact query are different tools. Semantic search for relevance; live SOQL for freshness, aggregations, and permissions.
3. **Denormalize aggressively.** We own the CRE schema. Pre-join parent fields onto child records at write time so most queries are a single search.
4. **Let the LLM reason, not a custom planner.** Replace the rigid planner/decomposer/graph pipeline with LLM tool-use. The LLM decides which searches to run and synthesizes results.
5. **Keep graph only where it earns its cost.** Use graph support for specific retrieval needs, not as a default answer to all cross-object questions. If denormalization + multi-search covers a use case, prefer it.
6. **Namespace-per-org.** Each Salesforce org is a search namespace. Cold when idle, warm on demand. Multi-tenant economics that actually work.
7. **Connector, not monolith.** The Salesforce integration is a data pipe into the platform, not the product itself. Design for future connectors.
8. **Simple auth, not perfect auth.** Per-user OAuth for permission-sensitive queries. Don't rebuild Salesforce's permission model outside Salesforce. If a question is highly permission-sensitive, prefer the live Salesforce path.
9. **Avoid vendor re-coupling.** Turbopuffer is the implementation, not the interface. Keep a thin search backend protocol so this migration doesn't repeat the Bedrock KB coupling mistake.
10. **Prove, then prune.** Don't delete existing capabilities (graph, derived views) until the new system proves it covers their use cases. But don't build them into the new system either.

---

## 7. Target Architecture

### 7.1 High-Level Shape

Two retrieval paths:

- **Indexed search path** — semantic + keyword + structured filter retrieval, backed by Turbopuffer behind a `SearchBackend` protocol. Optimized for citations, relevance, and fast search.
- **Live query path** — direct Salesforce SOQL execution for exact counts, sorting, fresh state, permission-sensitive queries, and harder analytical cases. Invoked selectively by the LLM.

### 7.2 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    AscendixIQ Search Platform                    │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                   Intelligence Layer                       │  │
│  │                                                            │  │
│  │  User Query                                                │  │
│  │    │                                                       │  │
│  │    ▼                                                       │  │
│  │  Claude (tool-use) ← SearchBackend protocol                │  │
│  │    ├── search_records(Lease, filters={...})     ──┐        │  │
│  │    ├── search_records(Property, filters={...})   ─┤parallel│  │
│  │    ├── aggregate_records(Sale, group_by=broker)  ─┘        │  │
│  │    └── live_sfdc_query(SOQL)  ← per-user OAuth             │  │
│  │    │                                                       │  │
│  │    ▼                                                       │  │
│  │  Synthesis → Streaming answer + citations                  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          │                                      │
│  ┌───────────────────────┼───────────────────────────────────┐  │
│  │          Data Layer   │  (SearchBackend → Turbopuffer)     │  │
│  │                       ▼                                    │  │
│  │  Namespace: org_{salesforce_org_id}                        │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  Denormalized documents                              │  │  │
│  │  │  objectType ∈ {Property, Lease, Availability,        │  │  │
│  │  │                Sale, Deal, Account, Contact}          │  │  │
│  │  │                                                      │  │  │
│  │  │  Each doc: vector + full-text + typed attributes     │  │  │
│  │  │  Parent fields inlined (Property→Lease, Acct→Deal)   │  │  │
│  │  │                                                      │  │  │
│  │  │  Cold on S3 when org inactive (~$0.02/GB)            │  │  │
│  │  │  Warm in <500ms on first query                       │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                   Connector Layer                          │  │
│  │                                                            │  │
│  │  ┌─────────────────┐  ┌──────────┐  ┌──────────────────┐ │  │
│  │  │ Salesforce       │  │ Yardi    │  │ CoStar           │ │  │
│  │  │ Connector        │  │ (future) │  │ (future)         │ │  │
│  │  │                  │  │          │  │                  │ │  │
│  │  │ Bulk API (init)  │  │          │  │                  │ │  │
│  │  │ CDC (ongoing)    │  │          │  │                  │ │  │
│  │  │ OAuth (per-user) │  │          │  │                  │ │  │
│  │  └─────────────────┘  └──────────┘  └──────────────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                   Surface Layer                            │  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐  │  │
│  │  │ Salesforce   │  │ AscendixIQ   │  │ API            │  │  │
│  │  │ LWC          │  │ Web App      │  │ (Embed / SDK)  │  │  │
│  │  └──────────────┘  └──────────────┘  └────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 Major Components

| Component | Purpose | New vs. Existing |
|-----------|---------|------------------|
| SearchBackend protocol | Thin Python ABC wrapping search operations | New (~1 day) |
| TurbopufferBackend | SearchBackend implementation for Turbopuffer | New |
| Query Lambda | Claude tool-use orchestration + streaming SSE | New (replaces retrieve + answer Lambdas) |
| Sync Lambda | CDC → Transform → Embed → Upsert | New (simplified from 8-step pipeline) |
| Bulk Loader | Initial Salesforce → Turbopuffer load | New (adapts existing batch export logic) |
| Denorm Config Generator | Metadata-driven field discovery → YAML config | New (runs at initial load; adapts signal_harvester.py) |
| LWC (ascendixAiSearch) | Chat UI in Salesforce | Existing (adapt API contract) |
| Apex controller | SSE parsing, callout logic | Existing (adapt endpoint) |

### 7.4 Key Differences from Current Architecture

| Concern | Current | Target |
|---------|---------|--------|
| Search backend | OpenSearch Serverless + Bedrock KB | Turbopuffer (via SearchBackend protocol) |
| Cross-object queries | DynamoDB graph traversal (2-hop) | Denormalized attributes + parallel LLM tool calls |
| Aggregations | DynamoDB derived views (5 tables) | Turbopuffer aggregations + LLM synthesis; live SOQL fallback |
| Query orchestration | Custom planner + decomposer + entity linker + intent router | LLM tool-use (Claude chooses which tools to call) |
| Authorization | Sharing bucket computation + FLS enforcement | Per-user OAuth + live SOQL for permission-sensitive queries |
| Multi-tenant | Shared OpenSearch collection (expensive idle) | Namespace-per-org (pennies when cold) |
| Schema management | Nightly Salesforce Describe API | Metadata-driven field discovery at initial load → generated denorm config (see §8.5) |
| Ingestion | 8-step Step Functions pipeline | 3-step Lambda: Transform → Embed → Upsert |
| Infrastructure | 6 CDK stacks, 16+ Lambdas, 12+ DynamoDB tables | ≤2 CDK stacks, ~3 Lambdas, 1-2 DynamoDB tables |

---

## 8. Denormalized Document Model

### Design principle

Every document should contain enough context to answer the most common queries about that record **without a second lookup**. Denormalize parent attributes onto child records at write time.

### Object hierarchy (Ascendix CRE)

```
Account (owner/company)
  ├── Contact
  ├── Opportunity / Deal
  │     └── (linked to Property)
  └── Property
        ├── Availability (space for lease)
        ├── Lease
        │     └── (linked to tenant Account)
        └── Sale
```

### Canonical Document Schema

Every document in the search backend conforms to this schema. Fields marked **platform** are required for all connectors; fields marked **connector** are Salesforce-specific.

| Field | Type | Required | Scope | Description |
|-------|------|----------|-------|-------------|
| id | string | yes | platform | Unique document ID (Salesforce record ID) |
| objectType | string | yes | platform | Object type enum |
| vector | float[] | yes | platform | Embedding vector (1024-dim Titan v2) |
| text | string | yes | platform | Full-text representation for BM25 + embedding source |
| chunk_id | string | no | platform | Optional chunk identifier (for future use on long-text fields) |
| last_modified | datetime | yes | platform | Source record last modified timestamp |
| salesforce_org_id | string | yes | connector | Tenant identifier |

> **Note on chunk_id:** The canonical schema includes `chunk_id` as an optional field to support future chunking of long-text fields (Notes, Descriptions). For POC, all records are stored as single documents — no chunking. If retrieval quality degrades on long-text fields, chunking can be activated by populating `chunk_id` without schema changes. See [Decision D-02](#19-decision-log).

### Document schemas

#### Property document

```json
{
  "id": "a0x001...",
  "objectType": "Property",
  "vector": [/* 1024-dim */],
  "text": "One Arts Plaza, 1722 Routh St, Dallas TX 75201. Class A Office...",

  "name": "One Arts Plaza",
  "address": "1722 Routh St",
  "city": "Dallas",
  "state": "TX",
  "zip": "75201",
  "submarket": "CBD",
  "property_class": "A",
  "property_type": "Office",
  "property_subtype": "High-Rise",
  "total_sf": 650000,
  "year_built": 2007,
  "floors": 24,
  "record_type": "Office",

  "owner_account_name": "Crescent Real Estate",
  "owner_account_id": "001ABC...",

  "last_modified": "2026-03-10T14:30:00Z",
  "salesforce_org_id": "00DXXX..."
}
```

#### Lease document (denormalized with Property parent)

```json
{
  "id": "a1y002...",
  "objectType": "Lease",
  "vector": [/* embedding */],
  "text": "Lease: Acme Corp at One Arts Plaza, Suite 1200. 12,500 SF NNN...",

  "tenant_name": "Acme Corp",
  "tenant_account_id": "001DEF...",
  "suite": "1200",
  "leased_sf": 12500,
  "lease_type": "NNN",
  "rate_psf": 32.50,
  "start_date": "2024-01-15",
  "end_date": "2027-01-14",
  "lease_term_months": 36,
  "has_rofr": true,
  "has_ti_allowance": true,
  "ti_amount_psf": 45.00,

  "property_name": "One Arts Plaza",
  "property_id": "a0x001...",
  "property_city": "Dallas",
  "property_submarket": "CBD",
  "property_class": "A",
  "property_type": "Office",
  "property_total_sf": 650000,

  "owner_account_name": "Crescent Real Estate",

  "last_modified": "2026-02-20T09:15:00Z",
  "salesforce_org_id": "00DXXX..."
}
```

#### Availability document (denormalized with Property parent)

```json
{
  "id": "a2z003...",
  "objectType": "Availability",
  "vector": [/* embedding */],
  "text": "Available: Suite 800, 8,200 SF at One Arts Plaza. Direct lease...",

  "suite": "800",
  "available_sf": 8200,
  "availability_type": "Direct",
  "available_date": "2026-06-01",
  "asking_rate_psf": 35.00,
  "lease_type": "NNN",
  "condition": "Spec Suite",
  "floor": 8,

  "property_name": "One Arts Plaza",
  "property_id": "a0x001...",
  "property_city": "Dallas",
  "property_submarket": "CBD",
  "property_class": "A",
  "property_type": "Office",
  "property_total_sf": 650000,

  "last_modified": "2026-03-01T11:00:00Z",
  "salesforce_org_id": "00DXXX..."
}
```

#### Sale document (denormalized with Property + broker)

```json
{
  "id": "a3w004...",
  "objectType": "Sale",
  "vector": [/* embedding */],
  "text": "Sale: One Arts Plaza sold for $285M ($438/SF). Buyer: Gaedeke Group...",

  "sale_price": 285000000,
  "price_psf": 438.46,
  "sale_date": "2025-09-15",
  "cap_rate": 6.2,
  "buyer_name": "Gaedeke Group",
  "seller_name": "Crescent Real Estate",
  "broker_name": "JLL",
  "sale_type": "Investment",

  "property_name": "One Arts Plaza",
  "property_id": "a0x001...",
  "property_city": "Dallas",
  "property_submarket": "CBD",
  "property_class": "A",
  "property_type": "Office",
  "property_total_sf": 650000,

  "last_modified": "2025-09-20T16:00:00Z",
  "salesforce_org_id": "00DXXX..."
}
```

#### Deal document (denormalized with Property + Account)

```json
{
  "id": "a4v005...",
  "objectType": "Deal",
  "vector": [/* embedding */],
  "text": "Deal: Tenant rep for Acme Corp, 15,000 SF office requirement in Dallas CBD...",

  "deal_name": "Acme Corp - Dallas CBD Requirement",
  "stage": "Proposal",
  "deal_type": "Tenant Rep",
  "requirement_sf": 15000,
  "target_occupancy": "2026-Q3",
  "deal_value": 1800000,

  "account_name": "Acme Corp",
  "account_id": "001DEF...",
  "broker_name": "Jane Smith",
  "broker_id": "005GHI...",

  "property_name": "One Arts Plaza",
  "property_id": "a0x001...",
  "property_city": "Dallas",
  "property_submarket": "CBD",
  "property_class": "A",
  "property_type": "Office",

  "last_modified": "2026-03-12T10:30:00Z",
  "salesforce_org_id": "00DXXX..."
}
```

### Denormalization cascade rules

When a parent record changes, child documents must be updated with the new parent values.

| Parent Change | Affected Children | Update Strategy |
|---------------|-------------------|-----------------|
| Property field changes | All Leases, Availabilities, Sales, Deals on that Property | CDC event → query search backend for `property_id = X` → re-upsert with new values |
| Account.name changes | All Deals, Leases where account is tenant/owner | CDC event → query search backend for `account_id = X` → re-upsert |
| Property deleted | Cascade delete children | CDC DELETE → delete by `property_id` filter |

**POC:** Cascade is deferred. Accept ~1hr staleness. Most parent fields (city, class, type) change rarely.
**v1:** Implement hybrid cascade — eager for name/address/type fields, lazy for less critical fields.

### Metadata-Driven Field Selection (Denorm Config Generator)

The document schemas above are illustrative. In practice, which fields to embed and which parent fields to denormalize should be **derived automatically from Salesforce metadata**, not hand-curated. Salesforce already tells you what's important through its own UI configuration.

This approach follows the **Coveo pattern** — a declarative, metadata-driven configuration of which fields to index and which parent/child relationships to traverse, generated from the source system's own metadata rather than requiring manual field-by-field curation.

#### Signal sources (ranked by strength)

| Tier | Source | Salesforce API | Signal | Weight |
|------|--------|---------------|--------|--------|
| **T1** | Compact Layouts | `GET /sobjects/{obj}/describe/compactLayouts/` | The 4-10 fields an admin hand-picked as "most important." Highlights panel, hover cards, mobile. | 15 |
| **T2** | Search Layouts | `GET /search/layout/?q={obj}` | Fields shown in global search results. Direct proxy for "what matters when searching." | 10 |
| **T3** | Page Layouts (first section) | `GET /sobjects/{obj}/describe/layouts` | Fields on the add/edit form. Required fields (`nillable=false`) are near-universal. | Required=20, Other=5 |
| **T4** | List View columns + filters | `GET /sobjects/{obj}/listviews/{id}/describe` | Aggregate across all views — frequently-appearing fields are high-signal. Filter fields = facet candidates. | columns=10/view, filters=10/view |
| **T5** | Report Types | `GET /analytics/reportTypes` | Fields users report on. Aggregation and grouping candidates. | 5 |
| **T6** | Quick Actions | Tooling API `QuickAction` | Default field values on entity creation = high-priority context. | 5 |
| **T7** | Field Describe intrinsics | `GET /sobjects/{obj}/describe` → `fields[]` | `nameField`, `filterable`, `groupable`, `nillable=false`, `type=reference`, `calculated=true` | Baseline (see below) |

#### Intrinsic field properties (Tier 7 baseline)

These properties from the sObject Describe API provide a floor signal even without layout metadata:

| Property | Denormalization Signal |
|----------|----------------------|
| `nameField=true` | **Always index.** Primary name field. |
| `nillable=false` + `createable=true` | **Always index.** Required field — admin decided it matters. |
| `idLookup=true` | **Always index.** Unique identifier (Email, CaseNumber). |
| `externalId=true` | **Always index.** External system ID. |
| `type=reference` + `referenceTo` | **Denormalization trigger.** Fetch parent's compact layout fields. |
| `filterable=true` + `groupable=true` | Good facet/filter candidate for metadata attributes. |
| `calculated=true` | Formula field — someone thought it mattered enough to compute. |
| `type` in `(picklist, multipicklist)` | Facet candidate. Store as filterable attribute. |
| `deprecatedAndHidden=true` | **Exclude.** |

#### Parent field denormalization rules

For each `reference` (lookup/master-detail) field on the target object:

1. **Always denormalize** the parent's `nameField` (e.g., Account.Name on a Deal).
2. **Fetch the parent's compact layout** → denormalize those fields (e.g., Property compact layout fields onto Lease).
3. **Check the child's list views** for dot-notation columns (e.g., `Account.Industry` on a Contact list view) → denormalize those fields. This is the strongest cross-object signal because the admin explicitly placed the parent field on the child's view.
4. **For master-detail relationships** (`cascadeDelete=true` on the child relationship): denormalize more aggressively than for lookups. These are tightly coupled objects.
5. **For the parent's search layout fields**: include as secondary candidates.

#### Child data aggregation rules

For child relationships (from parent's `childRelationships[]` array):

1. **If the child object is in the target set** (e.g., Lease is a target object and a child of Property): skip — it has its own search document.
2. **If the child is a "detail" object** (e.g., Lease Period, Note, Activity, Task):
   - Pull the child's compact layout fields.
   - Concatenate child text into the parent's `text` representation.
   - Optionally store aggregates as metadata attributes (count, latest date).

#### Scoring formula

```
field_score = (
    compact_layout_appearances * 15 +
    search_layout_appearances * 10 +
    list_view_column_appearances * 10 +
    list_view_filter_appearances * 10 +
    report_type_appearances * 5 +
    quick_action_appearances * 5 +
    is_required * 20 +
    is_name_field * 15 +
    is_filterable * 2 +
    is_formula * 3
)
```

Fields scoring above a threshold (e.g., ≥10) are included in the denormalized document. Fields scoring ≥20 are included in the `text` representation (for embedding). All scored fields are included as typed metadata attributes (for filtering).

#### Generated config format

The generator outputs a YAML config per object, human-reviewable before use:

```yaml
# Auto-generated from Salesforce org 00DXXX metadata
# Generated: 2026-03-14T10:30:00Z
# Review and commit before use

Property:
  embed_fields:        # Included in text representation + metadata attributes
    - Name             # nameField, compact, search, score=55
    - RecordType.Name  # compact, list_view(3), score=45
    - City__c          # compact, list_view(5), filter(3), score=80
    - State__c         # compact, list_view(4), filter(2), score=65
    - PropertyClass__c # compact, search, list_view(4), filter(4), score=85
    - PropertySubType__c # compact, list_view(2), score=40
    - Description__c   # long_text, page_layout(first_section), score=25
  metadata_fields:     # Metadata attributes only (for filtering)
    - TotalSF__c       # numeric, list_view(3), filter(2), score=30
    - YearBuilt__c     # numeric, list_view(1), score=15
    - Floors__c        # numeric, score=12
  parents:
    OwnerLandlord__c:  # reference field → Account
      - Name           # parent compact
      - Industry       # parent compact
    Market__c:         # reference field → Market
      - Name           # parent nameField
  children:
    Availability__c:
      aggregate: [count, earliest(AvailableDate__c)]
    Lease__c:
      aggregate: [count, earliest(TermExpirationDate__c)]

Lease:
  embed_fields:
    - Name
    - LeaseType__c
    - Description__c
  metadata_fields:
    - LeasedSF__c
    - RatePSF__c
    - TermCommencementDate__c
    - TermExpirationDate__c
  parents:
    Property__c:       # master-detail → aggressive denorm
      - Name           # parent compact
      - City__c        # parent compact + child list_view dot notation
      - State__c       # parent compact
      - PropertyClass__c # parent compact + child list_view dot notation
      - PropertySubType__c # parent compact
      - TotalSF__c     # parent compact
      - SubMarket__c   # child list_view dot notation (Property__r.SubMarket__c)
    Tenant__c:         # lookup → Account
      - Name           # parent nameField
    OwnerLandlord__c:  # lookup → Account
      - Name           # parent nameField
  children:
    LeasePeriod__c:
      embed: [RentAmount__c, PeriodType__c, StartDate__c, EndDate__c]
      aggregate: [count]
```

#### Execution flow

```
At initial load (Step 0, before bulk export):

1. Authenticate to Salesforce org.
2. For each target object:
   a. GET /sobjects/{obj}/describe → fields, childRelationships
   b. GET /sobjects/{obj}/describe/compactLayouts/ → T1 fields
   c. GET /search/layout/?q={obj} → T2 fields
   d. GET /sobjects/{obj}/describe/layouts → T3 fields (first section, required)
   e. GET /sobjects/{obj}/listviews → iterate → describe each → T4 columns + filters
   f. Score all fields using formula above.
3. For each reference field:
   a. Identify parent object from referenceTo[].
   b. Fetch parent's compact layout → parent denorm fields.
   c. Check child list views for parent.field dot notation → additional parent denorm fields.
4. For each child relationship (childRelationships[]):
   a. If child is in target set → skip.
   b. If child is detail object → fetch child's compact layout → child embed/aggregate fields.
5. Generate YAML config.
6. Human review → commit to repo.
7. Bulk loader reads config → drives denormalization at index time.

Subsequent runs (monthly cron, production):
- Re-run generator → diff against committed config → alert on changes.
- Human reviews diff → approves/adjusts → commits.
- Next sync cycle picks up new config.
```

#### Prior art in this codebase

The existing `signal_harvester.py` already reads Saved Searches, SearchLayouts, ListView columns, and sortable fields to compute relevance scores (1-10). The existing `IndexConfiguration__mdt` metadata provides manual override. The denorm config generator subsumes and extends this work:

- **What it replaces:** The nightly schema discovery pipeline (discoverer.py, cache.py, schema_loader.py) and the signal_harvester.py scoring. These fed a graph builder + chunking pipeline; the new generator feeds a denormalization builder.
- **What it reuses:** The signal harvesting logic (adapted for the new scoring formula), the Salesforce OAuth/API patterns, and the fallback chain concept (generated config → manual override → defaults).
- **What it adds:** Compact layout and page layout signals (not in the current system), parent-field denormalization rules, child aggregation rules, and YAML config generation.

---

## 9. Query Architecture — LLM Tool-Use

### Core concept

Instead of a rigid planner → decomposer → graph → KB pipeline, the LLM decides which searches to run via tool-use. Claude sees the user's question, emits one or more tool calls (potentially in parallel), receives results, and synthesizes a grounded answer.

This satisfies the requirement for an "orchestration layer that decides whether a query should use indexed search, live query, or both." The orchestration is implemented via prompt engineering + tool definitions rather than custom routing code. The LLM implicitly classifies query intent by choosing which tools to call.

### Tool definitions

```yaml
tools:
  - name: search_records
    description: |
      Search AscendixIQ for CRE records. Returns matching documents
      with relevance scores. Supports vector similarity, full-text
      BM25, and metadata filtering. Use multiple calls in parallel
      for cross-object queries.
    parameters:
      object_type:
        enum: [Property, Lease, Availability, Sale, Deal, Account, Contact]
      filters:
        type: object
        description: |
          Field-value filter pairs. Supports exact match, comparison
          (field_gte, field_lte), and set membership (field_in).
          Examples:
            property_city: "Dallas"
            property_class: "A"
            leased_sf_gte: 10000
            end_date_lte: "2026-09-14"
            property_type_in: ["Office", "Industrial"]
      text_query:
        type: string
        description: Natural language search text for BM25 + vector ranking
      limit:
        type: integer
        default: 10
        maximum: 50

  - name: aggregate_records
    description: |
      Count or sum records matching criteria, optionally grouped.
      Use for "how many," "total," "average," "breakdown" questions.
    parameters:
      object_type:
        enum: [Property, Lease, Availability, Sale, Deal]
      filters:
        type: object
      aggregate:
        enum: [count, sum, avg]
      aggregate_field:
        type: string
        description: Field to sum/average (required for sum/avg)
      group_by:
        type: string
        description: Field to group results by

  - name: live_salesforce_query
    description: |
      Run a live SOQL query against Salesforce as the current user.
      Use ONLY when: (1) data must be real-time, (2) query requires
      complex joins not available in indexed data, or (3) user asks
      about their own records/permissions. Slower than search_records.
    parameters:
      soql:
        type: string
        description: Valid SOQL query
```

### Query classification (implicit via tool choice)

| Query Type | Claude's Tool Choice |
|------------|---------------------|
| Simple search | 1x `search_records` |
| Filtered search | 1x `search_records` with filters |
| Cross-object | 2x `search_records` in parallel (different object_types) |
| Aggregation | 1x `aggregate_records` |
| Comparison | 2x `aggregate_records` in parallel + synthesis |
| Permission-sensitive | 1x `live_salesforce_query` |
| Complex multi-step | Sequential tool calls (result of call 1 feeds call 2) |
| Freshness-sensitive | 1x `live_salesforce_query` |

### Example query decompositions

**Query:** "What lease comps exist in Dallas CBD on office property in the last 12 months for >10,000 SF?"

```
Claude emits:
  search_records(
    object_type: "Lease",
    filters: {
      property_city: "Dallas",
      property_submarket: "CBD",
      property_type: "Office",
      start_date_gte: "2025-03-14",
      leased_sf_gte: 10000
    },
    text_query: "lease comp",
    limit: 20
  )

→ Single search backend query. One round-trip. ~10-50ms warm.
→ Claude synthesizes lease comp summary from results.
```

**Query:** "Compare average asking rates for Class A office in CBD vs Uptown"

```
Claude emits (parallel):
  aggregate_records(
    object_type: "Availability",
    filters: { property_class: "A", property_type: "Office", property_submarket: "CBD" },
    aggregate: "avg",
    aggregate_field: "asking_rate_psf"
  )
  aggregate_records(
    object_type: "Availability",
    filters: { property_class: "A", property_type: "Office", property_submarket: "Uptown" },
    aggregate: "avg",
    aggregate_field: "asking_rate_psf"
  )

→ Two parallel search backend queries. One multi-query round-trip.
→ Claude compares and presents side-by-side.
```

**Query:** "Which brokers have the most active deals on properties with expiring leases?"

```
Claude emits (sequential):
  Step 1: search_records(
    object_type: "Lease",
    filters: { end_date_lte: "2026-09-14", end_date_gte: "2026-03-14" },
    limit: 50
  )

  → Claude extracts property_ids from results

  Step 2: aggregate_records(
    object_type: "Deal",
    filters: { property_id_in: ["a0x001...", "a0x002...", ...], stage: "Active" },
    aggregate: "count",
    group_by: "broker_name"
  )

→ Two sequential queries. Two round-trips.
→ Claude ranks brokers and presents with deal counts.
```

### How tool calls map to the SearchBackend protocol

Each tool call is translated by the query Lambda into a `SearchBackend` method call:

```python
from abc import ABC, abstractmethod
from typing import Any

class SearchBackend(ABC):
    """Platform-level search abstraction. Turbopuffer is the first implementation."""

    @abstractmethod
    def search(self, namespace: str, rank_by: list, filters: list,
               top_k: int, include_attributes: list[str]) -> list[dict]:
        ...

    @abstractmethod
    def aggregate(self, namespace: str, filters: list,
                  aggregate_by: dict, group_by: str | None) -> dict:
        ...

    @abstractmethod
    def upsert(self, namespace: str, ids: list[str],
               vectors: list[list[float]], attributes: dict[str, list]) -> None:
        ...

    @abstractmethod
    def delete(self, namespace: str, ids: list[str]) -> None:
        ...

    @abstractmethod
    def warm(self, namespace: str) -> None:
        ...
```

The `TurbopufferBackend` implementation translates these to Turbopuffer API calls:

```python
import turbopuffer as tpuf

class TurbopufferBackend(SearchBackend):
    def search(self, namespace, rank_by, filters, top_k, include_attributes):
        return tpuf.Namespace(namespace).query(
            rank_by=rank_by,
            filters=filters,
            top_k=top_k,
            include_attributes=include_attributes,
        )

    def aggregate(self, namespace, filters, aggregate_by, group_by):
        return tpuf.Namespace(namespace).query(
            filters=filters,
            aggregate_by=aggregate_by,
            group_by=group_by,
        )

    # ... upsert, delete, warm similarly
```

### System prompt (abbreviated)

```
You are AscendixIQ, a CRE intelligence assistant. You answer questions
about commercial real estate data stored in the user's Salesforce org.

You have access to these tools:
- search_records: Search indexed CRE data (Property, Lease, Availability,
  Sale, Deal). Use metadata filters for precise queries. Call multiple
  times in parallel for cross-object questions.
- aggregate_records: Count, sum, or average records with grouping.
- live_salesforce_query: Run SOQL directly (use sparingly, only when
  real-time data or permission context is required).

Guidelines:
- Use denormalized fields (e.g., property_city on a Lease) to avoid
  multi-step queries when possible.
- For comparison queries, use parallel tool calls.
- Always cite source records by name and ID.
- If no results found, say so clearly — do not fabricate data.
- For "my deals" or "my pipeline" queries, prefer live_salesforce_query
  to respect user-specific permissions.
```

---

## 10. Connector Layer — Salesforce Sync

### Initial load

1. Authenticate to Salesforce org via OAuth (Connected App).
2. **Generate denorm config:** Run the Denorm Config Generator (see §8.5) against the org. This harvests compact layouts, search layouts, page layouts, list views, and field describe metadata to produce a YAML config defining which fields to embed, which parent fields to denormalize, and which child aggregations to compute. Human reviews and commits the config. On subsequent orgs with the same schema, the existing config is reused with a validation pass to confirm field existence. See [Decision D-01](#19-decision-log).
3. Query all supported objects via Bulk API 2.0.
4. For each record:
   - Flatten and denormalize (inline parent fields per denorm config).
   - Generate text representation for embedding (from `embed_fields` in config).
   - Embed via Bedrock Titan v2 (1024-dim).
   - Batch upsert to search backend namespace `org_{salesforce_org_id}`.
5. Estimated time: ~1M records/hour at Turbopuffer write throughput.

### Ongoing sync (CDC)

```
Salesforce CDC Platform Event
  → Lambda trigger
    → Fetch full record (if needed for denormalization)
    → Denormalize (inline parent fields)
    → Embed text
    → Upsert to search backend
    → If parent changed: cascade update children (v1; deferred in POC)
    → If deleted: delete from search backend by ID
```

**POC CDC mechanism:** Platform Event subscription → Lambda (simpler, fewer moving parts).
**Production fallback:** AppFlow → S3 → EventBridge → Lambda if Platform Events hit volume limits.

### Sync pipeline (simplified)

```
Current:  CDC → Validate → Transform → Chunk → GraphBuild → Enrich → Embed → Sync
Target:   CDC → Transform+Denormalize → Embed → Upsert
```

3 steps instead of 8. No graph building (denormalized). No separate chunking step (store full record text; see [Decision D-02](#19-decision-log)). No separate enrich step (denormalization handles it). No sync step (direct upsert to search backend).

---

## 11. Permission Model

### POC: Per-User OAuth (Notion's approach)

Each user authenticates to Salesforce via OAuth. Permission-sensitive queries run live SOQL as that user. Indexed search has no per-user auth filters — it returns all data in the org's namespace.

| Aspect | Behavior |
|--------|----------|
| Indexed search | Returns all org data regardless of user permissions |
| Live SOQL queries | Execute as the authenticated user — full Salesforce permission enforcement |
| Mitigation | For queries that might surface restricted records, prefer `live_salesforce_query` tool. System prompt guides this. |

**Why this is acceptable for POC:** It is exactly what Notion ships for their Salesforce AI Connector at enterprise scale. It avoids the complexity of sharing bucket computation (which is incomplete and brittle in the current system anyway). It is honest about what it does and does not enforce.

### v1: Push Permissions Into Indexed Search

Post-POC, evaluate adding attribute-based permission filtering to indexed documents:

- Store `owner_role_hierarchy` and `record_type` on documents.
- Filter at query time by the user's role.
- Fall back to live SOQL for edge cases (manual sharing rules, team-based access).

This satisfies the principle of "push permissions down" without attempting to replicate Salesforce's full sharing model.

### Non-negotiable constraints

- **No FLS in v1.** Field-level security is not enforced at the index level. This matches Notion's approach and avoids creating a false sense of security. If FLS is required, use `live_salesforce_query`.
- **Tenant isolation is structural.** Each org has its own namespace. One org's data is never co-mingled with or accessible from another org's queries.

---

## 12. Infrastructure & Cost

### POC infrastructure

| Component | Purpose | Est. Cost/mo |
|-----------|---------|-------------|
| Turbopuffer (Launch) | Search backend | $64 (minimum) + usage |
| Turbopuffer usage | Storage + queries | ~$10-30 (POC data volume) |
| Lambda (2-3 functions) | Sync pipeline + query API | ~$5-20 |
| API Gateway | Query endpoint | ~$5 |
| Bedrock (Claude Sonnet 4) | LLM tool-use + answer synthesis | ~$20-50 (POC query volume) |
| Bedrock (Titan v2) | Embedding generation | ~$5-10 |
| DynamoDB (1-2 tables) | Sessions, telemetry | ~$5 |
| **Total** | | **~$115-180/mo** |

### Cost comparison

| Scenario | Current | POC Target | Production Target |
|----------|---------|------------|-------------------|
| 1 org (dev) | $500-1,000/mo | $115-180/mo | $150-300/mo |
| 10 orgs (3 active) | $500-1,000/mo (shared) | ~$200-350/mo | ~$300-500/mo |
| 100 orgs (10 active) | Not viable | ~$400-700/mo | ~$600-1,200/mo |
| Marginal cost per cold org | ~$50-100/mo | ~$1-5/mo | ~$2-10/mo |

### Why the economics work

Turbopuffer's object-storage-first architecture means cold data costs ~$0.02/GB (S3) vs. $2+/GB (in-memory vector DBs). Active query cost is $4/million queries. Inactive orgs cost almost nothing. This is the multi-tenant unlock that makes the product viable at scale.

---

## 13. Migration Strategy

### Approach: Parallel POC Build + Shadow Validation

This is not an incremental migration inside the existing system. It is a parallel build of the new architecture, validated against the same acceptance tests, with a kill-or-keep gate before switching over.

**Why not incremental migration:** The current orchestration layer (planner, decomposer, intent router) is tightly coupled to the search substrate (Bedrock KB, OpenSearch). Introducing a `SearchBackend` abstraction *inside the existing system first* would require untangling that coupling — effort that is better spent building the replacement directly. The acceptance test suite provides the validation mechanism.

### Phase 0: Alignment (This Document)

- [x] Align on target product shape.
- [x] Choose target search backend (Turbopuffer behind SearchBackend protocol).
- [x] Choose POC permission posture (per-user OAuth).
- [x] Choose POC object scope (Property, Lease, Availability).
- [x] Choose orchestration approach (LLM tool-use).

### Phase 1: Turbopuffer Foundation (Week 1-2)

**Goal:** Data in the search backend, queryable.

- [ ] Create Turbopuffer account (Launch plan, $64/mo).
- [ ] Implement `SearchBackend` protocol + `TurbopufferBackend`.
- [ ] Define namespace schema for POC org.
- [ ] Write denorm config generator (adapting signal_harvester.py):
  - Connect to Salesforce sandbox.
  - Harvest compact layouts, search layouts, page layouts, list views, field describe.
  - Score fields, identify parent denorm fields, identify child aggregations.
  - Generate YAML config → human review → commit.
- [ ] Write bulk loader script:
  - Connect to Salesforce sandbox via Bulk API 2.0.
  - Export Property, Lease, Availability records.
  - Denormalize (inline parent Property fields on Lease/Availability).
  - Generate text representation per record.
  - Embed via Bedrock Titan v2.
  - Batch upsert via SearchBackend.
- [ ] Validate: run test queries directly against search backend API.
  - Metadata filter queries.
  - Hybrid BM25 + vector queries.
  - Aggregation queries.
- [ ] Measure: cold query latency, warm query latency, recall vs. current system.

**Deliverable:** Search backend namespace with denormalized CRE data, queryable via API.

### Phase 2: Intelligence Layer (Week 2-3)

**Goal:** LLM-powered query endpoint.

- [ ] New Lambda: `query` handler.
  - Accepts user question + org context.
  - Calls Claude Sonnet 4 with tool definitions (search_records, aggregate_records).
  - Translates tool calls → SearchBackend method calls.
  - Returns tool results to Claude.
  - Streams synthesized answer via SSE.
- [ ] System prompt with CRE domain knowledge (reuse temporal parsing, value normalization, entity linking vocabulary from current system).
- [ ] Citation extraction + record ID linking.
- [ ] Cache-warm search backend namespace on session start.
- [ ] Error handling: tool call failures, empty results, LLM refusals.

**Deliverable:** Working `/query` endpoint that takes a question and streams an answer.

### Phase 3: Salesforce Integration (Week 3-4)

**Goal:** End-to-end from LWC.

- [ ] Adapt LWC `ascendixAiSearch` to call new `/query` endpoint.
- [ ] Adapt Apex controller for new API contract.
- [ ] Update Named Credential endpoint.
- [ ] Basic CDC sync Lambda:
  - Subscribe to Salesforce CDC Platform Events (Property, Lease, Availability).
  - On change: fetch full record, denormalize, embed, upsert via SearchBackend.
  - On delete: delete from SearchBackend by ID.
- [ ] Test end-to-end: change record in Salesforce → verify updated in search results.

**Deliverable:** Working Salesforce-to-AscendixIQ connector with live sync.

### Phase 4: Validation Gate (Week 4-5)

**Goal:** Prove parity or improvement vs. current system. This is a kill-or-keep gate.

- [ ] Run full acceptance test suite against new system.
- [ ] Side-by-side latency comparison (current vs. new).
- [ ] Side-by-side cost comparison (actual billing).
- [ ] Qualitative review: answer quality, citation accuracy, edge cases.
- [ ] Identify any queries where the current system's graph traversal or derived views produce better results than denormalization + LLM tool-use.
- [ ] Document gaps, failures, and issues.
- [ ] **Gate decision:**
  - If ≥83% acceptance test pass rate and no critical regressions → proceed to Phase 5.
  - If specific graph-dependent queries regress → evaluate whether adding parent fields to denormalized model fixes it before reaching for graph infrastructure.
  - If fundamental approach fails → re-evaluate (see [Decision D-05](#19-decision-log)).

**Deliverable:** Validation report with go/no-go recommendation.

### Phase 5: Production Cutover (Week 5-8)

- [ ] Add Sale, Deal objects.
- [ ] Denormalization cascade on parent updates.
- [ ] Per-user OAuth for `live_salesforce_query` tool.
- [ ] CDK stack for new infrastructure (≤2 stacks: data + api).
- [ ] Shadow-read period: run both systems in parallel, compare results on live traffic. Log discrepancies for review.
- [ ] Monitoring dashboard (CloudWatch).
- [ ] Decommission old infrastructure (OpenSearch, Bedrock KB, graph DynamoDB tables, Step Functions workflow).
- [ ] Delete deprecated code from repository.

---

## 14. What We Keep, What We Delete, What We Defer

### What we keep

| Asset | How Reused | Effort |
|-------|-----------|--------|
| **CRE domain knowledge** | Query patterns, field semantics, "lease comp" understanding → system prompt + tool descriptions | Zero (copy) |
| **Temporal parsing** (temporal_parser.py) | Date range normalization in filter translation | Zero (import) |
| **Value normalization** (value_normalizer.py) | Picklist/range normalization in filter translation | Zero (import) |
| **Entity linking vocabulary** | Powers LLM's ability to map colloquial terms → field values | Low (seed as reference data) |
| **CDC processor** (event parsing logic) | Salesforce event parsing | Low (adapt I/O) |
| **Transform logic** | Flattening + relationship extraction | Low (adapt for denormalization) |
| **Embedding pipeline** | Bedrock Titan v2 invocation + batching | Low (reuse) |
| **LWC UI** (ascendixAiSearch) | Query input, streaming display, citations | Low (adapt API contract) |
| **Apex controller** (AscendixAISearchController) | SSE parsing, callout logic | Low (adapt endpoint) |
| **Acceptance test queries** | Gold-standard evaluation suite | Zero (reuse as-is) |
| **Batch export logic** (AISearchBatchExport) | Initial load from Salesforce | Medium (adapt for denormalization + SearchBackend) |
| **Named Credential + Remote Site** | API connectivity | Low (update endpoint URL) |

### What we delete (after Phase 4 validation gate)

| Component | Why | When |
|-----------|-----|------|
| `lib/search-stack.ts` | OpenSearch + Bedrock KB → replaced by Turbopuffer | After Phase 5 shadow-read |
| `lambda/sync/` | Bedrock KB writer → replaced by SearchBackend upsert | After Phase 5 |
| `lambda/retrieve/planner.py` | Rigid planner → replaced by LLM tool-use | After Phase 4 gate |
| `lambda/retrieve/schema_decomposer.py` | Schema decomposition → replaced by LLM tool-use | After Phase 4 gate |
| `lambda/retrieve/query_executor.py` | Multi-path executor → replaced by tool dispatch | After Phase 4 gate |
| `lambda/retrieve/intent_router.py` | Intent classification → implicit in LLM tool choice | After Phase 4 gate |
| `lambda/schema_discovery/` | Nightly Describe API → replaced by one-time validation | After Phase 4 gate |
| `lambda/schema_drift_checker/` | Schema drift detection → not needed | After Phase 4 gate |
| `lambda/schema_api/` | Schema API for Apex → not needed | After Phase 4 gate |
| `lambda/index-creator/` | OpenSearch bootstrap → not needed | After Phase 5 |
| AppFlow flows (7) | CDC → simplified to Platform Events | After Phase 5 |
| Step Functions workflow | 8-step pipeline → 3-step Lambda | After Phase 5 |
| VPC endpoints (AOSS, Bedrock Agent) | Network infrastructure no longer needed | After Phase 5 |

### What we defer (don't build, don't delete — decide at gate)

| Component | Current Role | Deferral Rationale |
|-----------|-------------|-------------------|
| `lambda/graph_builder/` | DynamoDB graph node/edge creation | Don't build in new system. Keep code until Phase 4 proves denormalization covers graph use cases. |
| `lambda/retrieve/graph_filter.py` | Graph node filtering | Same as above. |
| `lambda/retrieve/graph_retriever.py` | Graph traversal | Same as above. |
| `lambda/derived_views/` | DynamoDB materialized aggregations | Don't build in new system. Keep code until Phase 4 proves Turbopuffer aggregations + LLM synthesis + live SOQL cover the cases. |
| `lambda/retrieve/derived_view_manager.py` | Derived view query routing | Same as above. |
| DynamoDB graph tables (3) | Nodes, edges, path cache | Infrastructure stays until Phase 5 decommission. |
| DynamoDB derived view tables (5) | Vacancy, leases, availability, activities, sales | Infrastructure stays until Phase 5 decommission. |

---

## 15. POC Scope & Success Criteria

### POC scope (4-6 weeks)

**In scope:**

- [ ] SearchBackend protocol + TurbopufferBackend implementation
- [ ] Denorm config generator — harvest Salesforce metadata → generate YAML config for POC org
- [ ] Turbopuffer namespace creation + bulk load of 1 Salesforce org's data
- [ ] Denormalized document model for Property, Lease, Availability (3 objects)
- [ ] Embedding pipeline (Bedrock Titan v2 → SearchBackend upsert)
- [ ] Query Lambda with Claude tool-use (search_records, aggregate_records)
- [ ] Streaming answer generation with citations
- [ ] Basic CDC sync (Salesforce Platform Events → Lambda → SearchBackend)
- [ ] Existing LWC adapted to call new query endpoint
- [ ] Cache-warm on LWC component mount

**Out of scope (POC):**

- Sale, Deal objects (add in Phase 5)
- Account, Contact as standalone searchable objects
- Per-user OAuth / live SOQL tool
- Agentforce integration
- Action/mutation capabilities
- Multi-org / multi-tenant
- Production security hardening
- Denormalization cascade on parent updates

### Success criteria

| Criterion | Target | How Measured |
|-----------|--------|-------------|
| **Acceptance test pass rate** | ≥83% (no regression from current system) | Run existing acceptance test queries against new system |
| **Query latency (simple)** | ≤1s p95 (end-to-end including LLM) | Timed from LWC submit to first token |
| **Query latency (cross-object)** | ≤2s p95 | Multi-tool-call queries |
| **Monthly cost (1 org, POC data)** | ≤$200 | AWS + Turbopuffer billing |
| **Codebase size** | ≤30% of current Lambda code | Line count comparison |
| **Deployment complexity** | ≤2 CDK stacks | Stack count |
| **Retrieval precision** | Qualitative parity or improvement vs. current system | Side-by-side comparison on test queries |

> **Note:** The acceptance test threshold is ≥83%, not ≥80%. The current system passes 83% (5/6 scenarios). A regression would undermine the case for migration regardless of cost savings. See [Decision D-09](#19-decision-log).

---

## 16. POC Implementation Plan

See [Phase 1 through Phase 4](#13-migration-strategy) in the Migration Strategy section for the detailed week-by-week plan.

---

## 17. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Turbopuffer cold query latency degrades UX** | Medium | Medium | Cache-warm namespace on LWC mount. First query ~500ms, then warm queries <10ms. |
| **LLM tool-use adds latency vs. direct search** | High | Low | Budget ~500-800ms for LLM reasoning. Still faster than current planner+graph path (~2-5s). Optimize with prompt caching. |
| **LLM generates wrong filters** | Medium | Medium | Validate filters against known field names before executing. Include field enums in tool schema. Few-shot examples in system prompt. |
| **Denormalization doesn't cover all graph use cases** | Medium | Medium | Phase 4 validation gate explicitly tests graph-dependent queries. If regression, evaluate adding more denormalized fields before reaching for graph infrastructure. |
| **Turbopuffer vendor lock-in** | Low | High | SearchBackend protocol ensures all application code is backend-agnostic. Data is standard JSON + vectors — portable to OpenSearch, Pinecone, or self-hosted. |
| **Turbopuffer doesn't support needed filter operators** | Low | Low | Validated: supports Eq, In, Lt/Gt, Glob, Regex, Contains, And/Or/Not. Covers all CRE query patterns. |
| **Aggregation queries need features Turbopuffer lacks** | Medium | Medium | Turbopuffer has count + sum + group_by. For complex aggregations (percentiles, rolling windows), fall back to LLM computing from raw results or live SOQL. |
| **Permission model insufficient for enterprise** | Medium | High | Start with per-user OAuth (Notion's pattern). Evaluate attribute-based filtering in v1. Live SOQL provides a permission-perfect escape hatch. |
| **Broader rewrite than planned** | Medium | Medium | Scope acknowledgment in Section 1. Phase 4 validation gate provides explicit kill-or-keep decision. Existing system runs in parallel until Phase 5 cutover. |
| **Cascade complexity at scale** | Medium | Medium | Defer cascade to v1. Most parent fields (city, class, type) change rarely. Accept ~1hr staleness in POC. |
| **CDC Platform Events hit volume limits** | Low | Medium | AppFlow → S3 → EventBridge → Lambda is a proven fallback (current system uses it). Switch to AppFlow at scale if needed. |

---

## 18. Resolved Contradictions

This section documents where the source PRD and PDR disagreed, and how this unified spec resolves each conflict.

### RC-01: Schema Discovery

**PRD said:** Keep schema discovery as a connector responsibility. Preserve the nightly Describe API integration.
**PDR said:** Delete schema discovery entirely — we own the schema, it's over-engineering.
**Resolution:** Neither fully. Replace nightly schema discovery with a **metadata-driven denorm config generator** (see §8.5) that runs at initial load and optionally monthly. This recovers the PRD's intent (use Salesforce metadata to inform indexing) without the PDR's complaint (over-engineered nightly Describe cycle). The generator reads compact layouts, search layouts, page layouts, list views, and field intrinsics to automatically determine which fields to embed, which parent fields to denormalize, and which child data to aggregate. Output is a human-reviewable YAML config. The existing `signal_harvester.py` logic is adapted into the new generator. No schema cache, no drift checker, no nightly job — but the metadata signals that made schema discovery valuable are preserved and extended.

### RC-02: Chunking

**PRD said:** Preserve chunking. Include `chunk_id` in the canonical document schema.
**PDR said:** No chunking — store full record text as one document.
**Resolution:** No chunking for POC. Most CRE records are structured data, not long prose. The canonical schema includes `chunk_id` as an **optional** field so chunking can be activated for Notes/Descriptions later without schema changes. If retrieval quality degrades on long-text fields, chunking is the first lever to pull.

### RC-03: Graph Retention

**PRD said:** Keep graph capabilities behind interfaces as a safety net. Don't over-correct away from graph.
**PDR said:** Delete all graph infrastructure immediately.
**Resolution:** Don't build graph capabilities in the new system. Don't delete graph code from the repository until Phase 4 validation proves denormalization covers the graph-dependent acceptance tests. Explicit kill-or-keep decision at the Phase 4 gate. If specific graph-dependent queries regress, first evaluate whether adding more denormalized parent fields fixes it. Graph infrastructure (DynamoDB tables) remains running until Phase 5 decommission.

### RC-04: Vendor Abstraction

**PRD said:** Introduce a `SearchBackend` abstraction. Don't hard-code to Turbopuffer.
**PDR said:** Code directly to Turbopuffer API. (Claims abstraction exists in risk table but all code samples use `tpuf` directly.)
**Resolution:** Introduce a thin `SearchBackend` Python ABC protocol with `TurbopufferBackend` as the only implementation. All query and sync code calls the protocol, not `tpuf` directly. ~1 day of work. This prevents repeating the Bedrock KB coupling mistake without adding meaningful complexity.

### RC-05: Derived Views

**PRD said:** Keep derived views where useful temporarily.
**PDR said:** Delete all 5 derived view tables and Lambda code.
**Resolution:** Same treatment as graph (RC-03). Don't build derived views in the new system. Don't delete code until Phase 4 validates that Turbopuffer aggregations + LLM synthesis + live SOQL cover the use cases. DynamoDB tables remain until Phase 5 decommission.

### RC-06: Orchestration Layer

**PRD said:** The system must support an explicit orchestration layer that decides query routing.
**PDR said:** Delete the planner, decomposer, intent router. Let LLM tool-use handle orchestration implicitly.
**Resolution:** Side with PDR. LLM tool-use **is** the orchestration layer. The PRD's requirement (decide between indexed search, live query, or both) is satisfied — it's implemented via prompt engineering + tool definitions rather than custom routing code. This is an explicit architectural decision, not an omission. The current planner is "strong product logic" — but that logic is encoded into the system prompt and tool schemas, not deleted.

### RC-07: Scope of Replace vs. Keep

**PRD said:** Search-plane rip-and-replace, not a full system rewrite. Keep schema discovery, chunking, graph, derived views, answer generation.
**PDR said:** Replace search plane + orchestration + planning + schema + chunking + graph + derived views.
**Resolution:** Acknowledge this is broader than the PRD scoped. The orchestration layer was tightly coupled to the search substrate. The replacement is coordinated across both planes. This is justified because (a) the orchestration layer would need significant rework anyway, (b) LLM tool-use is a fundamentally better orchestration model for this domain, and (c) the acceptance test suite provides validation. The "prove, then prune" principle (Principle 10) ensures nothing is permanently deleted until the new system proves coverage.

### Soft Tensions (resolved by convention)

| Tension | Resolution |
|---------|-----------|
| **Permission emphasis** (PRD: push down; PDR: per-user OAuth) | Per-user OAuth for POC. Attribute-based filtering evaluated for v1. |
| **Migration philosophy** (PRD: incremental; PDR: parallel build) | Parallel POC build. Shadow-read validation in Phase 5 before cutover. |
| **Success metrics precision** (PRD: qualitative; PDR: quantitative) | Use PDR's quantitative targets. Tighten acceptance threshold to ≥83% (no regression). |
| **CDC mechanism** (PRD: silent; PDR: Platform Events) | Platform Events for POC. AppFlow as fallback at scale. |
| **Product framing** (PRD: "backend"; PDR: "connector") | "Salesforce Connector" for deliverable; "Search Platform" for the backend. |
| **Object scope** (PRD: open question; PDR: 3 objects) | 3 objects (Property, Lease, Availability) for POC. Sale + Deal in Phase 5. |
| **Deployment model** (PRD: 3 options; PDR: namespace-per-org) | Namespace-per-org. All object types in the same namespace, differentiated by `objectType` attribute. |
| **Multi-tenant in POC** (PRD: design principle; PDR: out of scope) | Out of scope for POC. Namespace-per-org architecture inherently supports it; validation deferred. |
| **Freshness targets** (PRD: undefined; PDR: ~1hr for POC) | ~1hr staleness acceptable for POC via CDC. Target ≤15min for production. |
| **Shadow-read approach** (PRD: during migration; PDR: end-of-build) | End-of-build validation in Phase 4. Shadow-reads in Phase 5 before decommission. |
| **Entity resolution** (PRD: replace, not delete; PDR: keeps vocab, deletes execution) | Entity linking vocabulary preserved as reference data. LLM handles resolution via system prompt. |
| **DynamoDB retention** (PRD: keep behind interfaces; PDR: delete 11 of 12 tables) | Tables remain until Phase 5. Code is preserved (not built in new system) until Phase 4 gate. |
| **Answer generation** (PRD: don't replace; PDR: replaces orchestration) | Orchestration is replaced; answer synthesis (Claude streaming + SSE) is preserved and adapted. |

---

## 19. Decision Log

Decisions made in this spec. Each has an ID for cross-reference.

| ID | Decision | Rationale | Reversibility |
|----|----------|-----------|---------------|
| **D-01** | Metadata-driven denorm config generation at initial load, not nightly discovery | Salesforce metadata (compact layouts, search layouts, page layouts, list views) tells us which fields matter. Generate a YAML config automatically, human-review it, use it to drive denormalization. Replaces both the PRD's nightly discovery and the PDR's static mapping. Monthly re-generation in production to catch view/layout changes. | Easy — increase frequency or add drift alerting if schemas evolve faster than expected. |
| **D-02** | No chunking for POC; `chunk_id` reserved in schema | CRE records are structured data, not long prose. Full-text per record is sufficient. Chunking adds ingestion complexity. | Easy — activate by populating `chunk_id` if retrieval quality degrades on Notes/Descriptions. |
| **D-03** | Denormalization replaces graph for cross-object queries | Most cross-object queries (lease comps by property, deals by submarket) are handled by pre-joining parent fields. Remaining cases use sequential LLM tool calls. | Medium — would need to build graph infrastructure if complex multi-hop traversals prove necessary. Phase 4 gate is the decision point. |
| **D-04** | `SearchBackend` protocol with Turbopuffer implementation | Prevents vendor coupling (lesson learned from Bedrock KB). Thin ABC adds ~1 day of effort. | Easy — swap implementation to any vector database. |
| **D-05** | Parallel POC build, not incremental migration | Existing orchestration is too coupled to Bedrock KB/OpenSearch to migrate incrementally. Parallel build is faster and cleaner. Shadow-reads validate in Phase 5. | Hard — switching to incremental migration would require untangling the existing system first. |
| **D-06** | LLM tool-use as orchestration layer | Claude's tool-use accuracy is high for structured search tools. Parallel tool calls map naturally to cross-object queries. Replaces ~4 custom routing modules. | Medium — could reintroduce explicit planner if LLM tool selection proves unreliable on CRE domain. |
| **D-07** | Per-user OAuth for permissions (POC) | Matches Notion's production pattern. Avoids sharing bucket complexity. Honest about enforcement boundaries. | Easy — add attribute-based filtering in v1 for stricter enforcement. |
| **D-08** | Platform Events for CDC (POC) | Simpler than AppFlow pipeline. Fewer moving parts. Sufficient for POC volume. | Easy — switch to AppFlow at scale (current system already has it). |
| **D-09** | ≥83% acceptance test pass rate (no regression) | Current system achieves 83%. Allowing regression undermines the case for migration regardless of cost savings. | N/A — this is a success criterion, not a design decision. |
| **D-10** | 3 objects for POC (Property, Lease, Availability) | These cover the highest-value CRE queries (space search, lease comps, availability). Minimizes denormalization work while proving the pattern. | Easy — add Sale and Deal in Phase 5. |
| **D-11** | One namespace per Salesforce org, all object types in same namespace | Simpler management. `objectType` attribute provides filtering. Turbopuffer handles large namespaces efficiently. | Medium — splitting to per-object-type namespaces would require re-ingestion. |
| **D-12** | Claude Sonnet 4 via Bedrock for LLM tool-use | Best tool-use accuracy, streaming support, reasonable cost. Bedrock avoids adding an Anthropic API dependency. | Easy — swap to Haiku for cost, or Anthropic API direct for independence from AWS. |
| **D-13** | Prove, then prune (deferred deletion) | Existing graph/derived view code is preserved until Phase 4 validates the new system covers those use cases. De-risks the migration. | N/A — this is a process decision. |

---

## 20. Open Questions

These are unresolved decision points for collaborative discussion.

### Q1: Embedding model

**Current recommendation:** Continue with Bedrock Titan v2 (1024-dim). Already proven, available in us-west-2, low cost.

**Alternatives:**
- OpenAI `text-embedding-3-small` (1536-dim, potentially better quality)
- Cohere Embed v3 (good multilingual support)
- Turbopuffer-native embedding (if available — reduces a moving part)

### Q2: Where does the query Lambda run?

**Current recommendation:** AWS Lambda with Function URL (streaming). Same pattern as current Answer Lambda.

**Alternatives:**
- ECS/Fargate container (more control, no cold starts, higher base cost)
- Cloudflare Workers (edge, low latency, but vendor shift)

### Q3: CDK or alternative IaC?

**Current recommendation:** CDK, 2 stacks max (data + api).

**Alternatives:** Terraform, SST, or Pulumi if team prefers.

### Q4: Denorm config generator — threshold tuning

The scoring formula in §8.5 uses a threshold (proposed: ≥10 for metadata attributes, ≥20 for text embedding) to decide which fields make it into the denormalized document. **These thresholds need validation against a real Ascendix org.** Run the generator against the sandbox, review the YAML output, and tune thresholds until the config captures 80-90% of fields the team considers important without excessive noise. The document schemas in Section 8 serve as a manual baseline to compare against.

### Q5: Cascade strategy for production

**Options:**
- **(A) Eager cascade** — update children immediately on parent change. Consistent but more writes.
- **(B) Lazy cascade** — update children on next CDC cycle. Slightly stale but fewer writes.
- **(C) Hybrid** — eager for name/address/type fields, lazy for less critical fields.

**Recommendation:** (C) Hybrid. Deferred to v1.

### Q6: Salesforce component fork approach

The current project has Apex classes, LWC, Named Credentials, custom metadata, etc. **Recommendation:** Fork the Salesforce components. Keep `ascendixAiSearch` LWC and `AscendixAISearchController` Apex. Adapt to new API contract. Delete Phase 2 action components, batch export scheduler, schema cache client.

### Q7: AscendixIQ surface beyond Salesforce?

**POC:** Salesforce LWC only. The query API is surface-agnostic, so a web UI or embedded widget can be added later without changing the backend.

### Q8: Aggregation gaps

Turbopuffer supports count + sum + group_by. What CRE queries require more complex aggregations (weighted averages, percentiles, rolling windows)? These would need live SOQL fallback. **Ascendix team should enumerate known aggregation queries** to validate coverage.

---

## 21. Appendix: Reference Architecture

### Notion Salesforce AI Connector (for reference)

Shipped 2026-03-11. Direct market validation of this architectural pattern.

- **Objects:** Account, Lead, Opportunity, Contact (4 standard objects only)
- **Custom objects:** Not supported
- **FLS:** Not supported
- **Search backend:** Turbopuffer (10B+ vectors, 1M+ namespaces)
- **Embedding:** OpenAI zero-retention API + open-source models on Ray/Anyscale
- **LLM:** Anthropic (Claude)
- **Sync:** Initial load up to 72 hours, ongoing within 1 hour
- **Auth:** Per-user OAuth; each workspace member authenticates individually
- **Advanced queries:** SOQL translation via member login for complex/permission-sensitive queries
- **SOC2:** Type II certified
- **Cost savings:** 60% reduction on search engine spend via Turbopuffer migration; removed per-user AI charges

### Current system metrics (baseline for comparison)

- Acceptance test pass rate: 83% (5/6 scenarios)
- Simple query latency: ~1.5s p95
- Cross-object query latency: ~2.9s p95 (optimized from 8.7s)
- First token latency: ~800ms
- Monthly cost: ~$500-1,000 (1 org, dev)
- Codebase: 16+ Lambdas, 12+ DynamoDB tables, 6 CDK stacks

### Key SearchBackend / Turbopuffer API patterns

```python
import turbopuffer as tpuf

# Upsert denormalized documents
ns = tpuf.Namespace("org_00DXXX")
ns.upsert(
    ids=["a0x001"],
    vectors=[[0.1, 0.2, ...]],
    attributes={
        "objectType": ["Property"],
        "name": ["One Arts Plaza"],
        "city": ["Dallas"],
        "property_class": ["A"],
        "total_sf": [650000],
        "text": ["One Arts Plaza, 1722 Routh St..."]
    }
)

# Hybrid search with metadata filters
results = ns.query(
    rank_by=["Sum",
        ["text", "BM25", "class a office dallas"],
        ["vector", "ANN", query_vector]
    ],
    filters=["And",
        ["objectType", "Eq", "Lease"],
        ["property_city", "Eq", "Dallas"],
        ["leased_sf", "Gte", 10000]
    ],
    top_k=20,
    include_attributes=["name", "property_name", "leased_sf", "rate_psf"]
)

# Aggregation
agg_results = ns.query(
    filters=["And",
        ["objectType", "Eq", "Availability"],
        ["property_submarket", "Eq", "CBD"]
    ],
    aggregate_by={"type": "count"},
    group_by="property_class"
)

# Cache warm (on LWC mount)
ns.warm()
```

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2026-03-14 | Initial unified draft — synthesized from ASCENDIXIQ_AGENTIC_SEARCH_BACKEND_PRD.md and ASCENDIXIQ_SALESFORCE_CONNECTOR_PDR.md |
