
# AscendixIQ Salesforce Solution Pack – Master Architecture  
**Version:** 1.0 (Unified)  
**Owner:** Ascendix Technologies  
**Status:** Draft for Review  

This document supersedes **all prior versions** of:

- `Ascendix_SFDC_AI_Search_Master.md`  
- `Ascendix_SFDC_AI_Search_Master_v1.1.md`  

It is fully aligned with the **AscendixIQ Core Manifest** and reframes the prior Salesforce AI Search & Agent work as a formal **AscendixIQ Solution Pack**.

---

# 0. Purpose

The Salesforce Solution Pack delivers **real-time AI search, Q&A, and agentic actions inside Salesforce**, powered entirely by **AscendixIQ Core**.

It provides:

- A **Fast Path** chat experience  
- Grounded, permission-aware answers  
- Cross-entity CRE intelligence  
- Optional action execution (mini-runbooks)  
- Native Salesforce UI (LWC + Agentforce)

The backend is *not* Salesforce-specific. It is the first consumer of the AscendixIQ Core engine.

---

# 1. Architectural Alignment with AscendixIQ Core

This Solution Pack inherits the primitives defined in the Core Manifest:

- **Skills** → retrieval, grounding, summarization, ranking  
- **Runbooks** → mini-runbooks for Salesforce actions  
- **Case Model** → Salesforce chat sessions mapped to Cases  
- **Template-Aware Indexing** → Salesforce objects represented as templates  
- **AuthZ Adapter** → Salesforce Sharing/FLS enforcement  
- **Unified Metadata & Citation Schema**  
- **Fast Path Execution**  
- **Observability & Evaluation**

This ensures the work done for Salesforce immediately accelerates the standalone AscendixIQ application.

---

# 2. High-Level Architecture

```mermaid
flowchart TD
  SF[LWC / Agentforce] --> PC[Salesforce Private Connect]
  PC --> PL[AWS PrivateLink]
  PL --> APIGW[AscendixIQ API Gateway (Private)]

  subgraph FastPath[Fast Path – Real-time Retrieval & Answering]
    APIGW --> RET[Skill: rag.retrieve]
    APIGW --> ANS[Skill: rag.answer_with_citations]
    ANS --> LLM[LLM (Bedrock)]
    RET --> KB[Bedrock Knowledge Base]
    KB --> OS[OpenSearch]
    OS --> RET
  end

  subgraph Core[AscendixIQ Core Services]
    AUTHZ[AuthZ Adapter<br/>(Salesforce Sharing/FLS)]
    CASE[Case Manager]
    SKILLS[Skills Registry]
    RUN[Runbook Engine]
  end
```

---

# 3. Execution Path: Fast Path (Real-Time)

The Salesforce experience runs exclusively on the **Fast Path** defined by AscendixIQ Core:

### Characteristics
- `< 800ms` p95 first-token
- Retrieval + grounding + streaming answer
- Stateless (sessionId → caseId)
- Always uses Salesforce AuthZ Adapter
- Works inside LWC and Agentforce

### APIs (Backed by Core Skills)

1. **`POST /retrieve`**  
   Uses Core skill **`rag.retrieve`**  
2. **`POST /answer`**  
   Uses Core skill **`rag.answer_with_citations`**

Both return **AscendixIQ-compliant citation objects** and metadata.

---

# 4. Case Model Mapping

### In Salesforce:
- Chat panels use `sessionId`
- Every session is mapped to a Core **Case** with:
  - `caseType = "sfdc_chat"`
  - `sourceSystem = "salesforce"`
  - `primaryRecordId = Account/Opportunity/etc.`

### Why this matters
The standalone AscendixIQ UI will use `caseId` directly.  
Salesforce uses sessions, but *Core sees everything as Cases*.

---

# 5. Templates for Salesforce Objects

AscendixIQ requires **template-aware indexing**.

Salesforce objects are represented as templates:

- `sfdc_account_v1`
- `sfdc_opportunity_v1`
- `sfdc_case_v1`
- `sfdc_note_v1`

Each template defines:

- Fields included  
- Chunking rules  
- Metadata mappings (territory, ownerId, etc.)  
- AuthZ tag mapping  
- FLS-driven redaction rules  

This replaces hardcoded schemas from older docs.

---

# 6. AuthZ Adapter – Salesforce Implementation

This Solution Pack provides the first implementation of the **AuthZ Adapter Interface**:

- Enforces **Sharing**, **Territory**, and **FLS**  
- Outputs:
  - `sharingBuckets[]`
  - `flsProfileTags[]`
- Core RAG engine uses these tags for filtering and snippet redaction

This adapter is pluggable, ensuring AscendixIQ Core is not tied to Salesforce.

---

# 7. Mini-Runbooks (Salesforce Agent Actions)

Salesforce “Agent Actions” become **mini-runbooks** inside the Core model.

Example mini-runbooks:

- `create_opportunity`
- `update_opportunity_stage`
- `log_task_followup`
- `create_case_from_chat`

They follow AscendixIQ Runbook conventions:

- Anchored to a `caseId`
- Schema-defined inputs and outputs
- Idempotent where possible
- Logged via the Core audit model

---

# 8. Indexing & Ingestion (Salesforce as a Data Source)

In this Solution Pack, Salesforce is treated as a **source system** for AscendixIQ.

### Preferred Ingestion
- **AppFlow + CDC**  
- Maps fields into templates  
- Triggers metadata enrichment  
- Updates indexes in near real time

### Fallback
- Scheduled Apex → NDJSON → `/ingest`

---

# 9. Metadata & Citation Schema (Core-Aligned)

This replaces older custom SFDC-specific payloads.

### Minimum metadata:
- `sourceSystem = "salesforce"`
- `templateId`
- `entityType`
- `recordId`
- `ownerId`
- `territory`
- `sharingBuckets[]`
- `flsProfileTags[]`
- `hasPII`
- `lastModified`

### Citation schema (Core Standard)
Citations must include:

- `recordId`
- `entityType`
- `loc`
- `snippet`
- `confidence`
- `metadata`

---

# 10. LWC / Agentforce UX (Headless Client)

The Salesforce frontend acts as a **thin client** to Core:

- No business logic or RAG logic in LWCs  
- LWCs call `/retrieve` and `/answer`  
- Agentforce tools call the same  
- Citations drawer reflects Core’s schema  
- Supports streaming answers  
- Supports action preview → execute mini-runbook

Everything UI-related becomes part of the Solution Pack, not Core.

---

# 11. Multi-Tenant & Isolation (Core Inheritance)

This Solution Pack inherits multi-tenancy from Core:

- One KB per client  
- Per-tenant KMS keys  
- Per-tenant cost tagging  
- Per-tenant authz config  
- Strict isolation between Salesforce orgs

---

# 12. Observability & Metrics

The Solution Pack must emit:

- Retrieval latency  
- Generation latency  
- precision@k  
- authz denials  
- grounding violations  
- cost per tenant  
- Agent Action runbook metrics

This aligns with Core dashboards.

---

# 13. POC → Pilot → Scale (Solution Pack Roadmap)

### POC (Thin Slice)
- Accounts, Opportunities, Notes  
- `/retrieve` + `/answer`  
- AuthZ Adapter v1  
- LWC chat panel

### Pilot
- Add Cases & Tasks  
- Add Agent Actions (mini-runbooks)  
- Full template definitions  
- Evaluation harness live  
- Multi-region support  

### Enterprise Scale
- Custom rankers  
- Extended adjacency / relationship boosts  
- Optional graph integration  
- Integration with standalone AscendixIQ app  

---

# 14. Provenance (Source Files Used)

Below are the raw source files merged to create this unified architecture:



<!-- SOURCE FILE: /mnt/data/Ascendix_SFDC_AI_Search_Master.md -->


# Ascendix Unified AI Search & Agent Platform for Salesforce (AWS‑Hosted RAG)
**Version:** 1.0 • **Date:** 2025‑11‑12 • **Status:** Draft for Review  
**Owner:** Ascendix Technologies

**Provenance:** This master consolidates and supersedes two internal drafts — “Ascendix BI for Salesforce” and “AgentForce + Search Backend For Salesforce” — and incorporates design improvements and feasibility analysis. fileciteturn0file0 fileciteturn0file1

---

## 0) Executive Summary

Ascendix will deliver a **governed, AWS‑hosted Retrieval‑Augmented Generation (RAG) platform** that natively augments **Salesforce** user search and **Agentforce** agent reasoning. The system enables **cross‑entity** discovery (e.g., *Accounts with leases expiring next quarter that have open HVAC cases*) and **grounded answers with citations**, while matching Salesforce **sharing** and **field‑level security (FLS)**. Network traffic stays private via **Salesforce Private Connect → AWS PrivateLink → API Gateway (Private)**. The retrieval substrate uses **Amazon Bedrock Knowledge Bases** backed by **OpenSearch** (hybrid semantic+keyword), with **Bedrock Guardrails** enforcing safety and grounding. fileciteturn0file0 fileciteturn0file1

This document merges the prior architecture and blueprint into one implementable plan, adds **authZ parity**, **freshness via CDC**, **graph‑aware relevance**, and **latency/cost controls**, and defines **contracts, metrics, and milestones** to take the solution from POC to enterprise scale.

---

## 1) Goals & Non‑Goals

### 1.1 Goals
- **Superior search & agent experience in Salesforce:** natural‑language Q&A over **cross‑object** Salesforce data and related documents.
- **Grounded, explainable answers:** every response cites specific records/snippets the user is allowed to see.
- **Security parity:** enforce Salesforce **sharing, role/territory**, and **FLS** in retrieval and answer synthesis.
- **Tenant isolation & governance:** partner‑operated, multi‑tenant control plane with per‑client isolation.
- **Predictable performance & cost:** low‑latency streaming UX with clear cost levers.

### 1.2 Non‑Goals (for v1)
- Replacing Salesforce reporting/BI; instead we **complement** it with search + RAG.  
- Autonomous action‑taking in Salesforce beyond read/answer (action tools can be added later).

---

## 2) Reference Architecture

### 2.1 High‑Level Diagram (informative)

```mermaid
flowchart TD
  SF[LWC / Agentforce] --> PC[Salesforce Private Connect]
  PC --> PL[AWS PrivateLink]
  PL --> APIGW[API Gateway (Private)]
  APIGW --> L_ingest[Lambda: /ingest]
  APIGW --> L_retrieve[Lambda: /retrieve]
  APIGW --> L_answer[Lambda: /answer]
  subgraph Ingestion & Indexing
    L_ingest --> S3[(S3 processed)]
    S3 --> KB[Bedrock Knowledge Base]
    KB <--> OS[OpenSearch (Serverless/Managed)]
  end
  subgraph Answering
    L_retrieve --> KB
    L_retrieve --> OS
    L_answer --> BR[Bedrock (Claude family)]
    BR --> GR[Guardrails]
    L_answer --> DDB[(DynamoDB chats)]
  end
```

**Why this design:** It keeps traffic off the public internet, centralizes control in AWS, and gives us **retrieval knobs** and **cost levers** not available in a pure Data Cloud path. It blends vector and keyword signals for precise, cross‑entity questions. fileciteturn0file0 fileciteturn0file1

### 2.2 Components (summary)

| Layer | Service | Purpose |
|---|---|---|
| Network | **Salesforce Private Connect → AWS PrivateLink** | Private channel between Salesforce and AWS. fileciteturn0file0 |
| API | **API Gateway (Private)** + **Lambda** | Endpoints: `/ingest`, `/retrieve`, `/answer`. |
| Storage | **S3 (KMS‑encrypted)** | Staging for processed artifacts and chunked text. |
| Index | **Bedrock Knowledge Base** + **OpenSearch** | Hybrid (dense + BM25) retrieval with filters. |
| Embeddings | **Titan Text Embeddings v2** | Cost‑efficient, scalable embeddings (binary optional). |
| Generation | **Bedrock (Claude family)** | Grounded answer synthesis with citations. |
| Guardrails | **Bedrock Guardrails** | PII/jailbreak/grounding enforcement. |
| State | **DynamoDB** | Conversation state, cache, telemetry. |
| Observability | **CloudWatch, X‑Ray** | Logs, traces, metrics, dashboards. |

---

## 3) Salesforce Integration (UI + Agentforce)

- **LWC Search/Chat**: A Lightning web component renders a streaming answer pane, facets (Region, BU, Stage, Quarter), and a **citations drawer**.  
- **Agentforce**: Register our private tools so agents always ground on our retriever:  
  - `retrieve_knowledge(query, filters, recordContext)` → `/retrieve`  
  - `answer_with_grounding(query, ...)` → `/answer` (optional; Agentforce may call its own LLM while we still supply grounding)  
- **Auth & Transport**: **Named Credential** to our **API Gateway (Private)** over **Private Connect/PrivateLink**. fileciteturn0file1

---

## 4) Security & Compliance Posture

- **Zero‑trust network**: VPC‑only endpoints; S3 buckets blocked from public; service endpoints via PrivateLink.  
- **Encryption**: KMS CMKs for S3, OpenSearch, DynamoDB, and any OCR output; optional BYOK semantics.  
- **Data minimization**: No long‑term storage of raw chat beyond policy; presigned S3 for short‑lived previews.  
- **Auditability**: CloudTrail per tenant; OpenSearch audit logs; Agentforce tool call logs.  
- **Model privacy**: Bedrock models do not train on tenant data.  
- **Guardrails**: Reject answers without allowed citations; scrub/limit PII unless requestor has permission. fileciteturn0file0

---

## 5) Authorization Parity (Row + Field‑Level) — **Required**

**Problem:** If retrieval returns content the user **shouldn’t** see, trust is lost. The initial drafts did not fully specify FLS/sharing enforcement at retrieval time. fileciteturn0file0

**Design (hybrid authZ):**
1. **Index‑time scoping**: Each chunk carries metadata:  
   `sobject, recordId, parentIds[], ownerId, territory, businessUnit, sharingBuckets[], flsProfileTags[], hasPII, effectiveDate, lastModified, language`  
2. **Query‑time filter**: A **lightweight AuthZ sidecar** receives `salesforceUserId` and returns allowed `sharingBuckets[]` and `flsProfileTags[]` (daily cache + on‑demand refresh for edge cases). `/retrieve` adds these as **OpenSearch filters** before scoring.  
3. **Post‑filter gate**: Re‑validate top‑K via a **“can view?”** check (e.g., proxy SOQL with `with sharing`) before passing any snippet to the LLM. If none survive, return a **no‑access** message.  
4. **FLS variants**: Where field visibility differs, maintain **redacted vs. full** chunk variants at index‑time.  
5. **Prompt guard**: The system prompt enforces “**answer only from allowed citations**.”

---

## 6) Ingestion & Freshness

**Preferred pipeline (near‑real‑time):**
- **Amazon AppFlow + Salesforce CDC/Platform Events** stream deltas into S3 (private VPC endpoints).  
- **EventBridge → Step Functions → Lambda** normalize, chunk (300–500 tokens), and enrich with metadata.  
- **Bedrock KB sync** indexes into **OpenSearch** with hybrid retrieval.  

**Fallback (batch):** Scheduled Apex export → `/ingest` → S3 → KB sync. This is viable but may pressure governor limits and increase staleness; the CDC path is recommended for pilots onward. The original “scheduled export” approach is preserved here as a fallback. fileciteturn0file0 fileciteturn0file1

**Document classes:**  
- **Facts index**: concise, canonical fields & roll‑ups for precision joins.  
- **Narratives index**: long text (notes, emails, case comments, docs).  
Blend both at query time for **cross‑entity** questions.

---

## 7) Retrieval, Ranking & Cross‑Entity Quality

- **Hybrid retrieval**: Dense vectors (Titan v2) + BM25 in a single query for semantic + exact matches.  
- **Re‑rank (optional)**: Cross‑encoder or LLM rerank on top‑K for higher precision.  
- **Query decomposition**: Extract filters/time ranges → retrieve per entity → on‑the‑fly join in Lambda → assemble grounded answer with per‑entity citations.  
- **Graph‑aware boosting (lightweight)**: Store adjacency lists (e.g., Account→Opportunity→Product, Lease→Property→Owner) and **boost** candidates within N hops of `recordContext`. If needed later, graduate to **Neptune/Neptune Analytics** for richer path scoring. fileciteturn0file1

---

## 8) API Contracts (v1)

All endpoints are **private** (API Gateway Private) and require a **Named Credential** from Salesforce.

### 8.1 `/retrieve` (search only)

**Request**

```json
POST /retrieve
{
  "query": "Show open opportunities in EMEA over $1M",
  "filters": {"sobject": ["Opportunity"], "Region": "EMEA"},
  "recordContext": {"AccountId": "001xx"},
  "salesforceUserId": "005xx",
  "topK": 8,
  "hybrid": true,
  "authzMode": "both",   // indexFilter | postFilter | both
  "ranker": "default"    // default | crossEncoder
}
```

**Response**

```json
{
  "matches": [
    {
      "id": "Opportunity/006xx1",
      "title": "ACME Renewal",
      "score": 0.82,
      "snippet": "ACME renewal valued at $1.2M closes 2026‑02‑10…",
      "metadata": {"sobject":"Opportunity","Region":"EMEA","OwnerId":"005…"},
      "previewUrl": "https://signed-s3-url/…"
    }
  ]
}
```

### 8.2 `/answer` (retrieve + generate)

**Request**

```json
POST /answer
{
  "sessionId": "acct-001xx-2025-11-12",
  "query": "Summarize renewal risks for ACME.",
  "recordContext": {"AccountId": "001xx"},
  "salesforceUserId": "005xx",
  "topK": 6,
  "policy": {"require_citations": true, "max_tokens": 600}
}
```

**Response**

```json
{
  "answer": "ACME's renewal risks include…",
  "citations": [
    {"id": "Opportunity/006xx1", "loc": "field:Risk_Notes__c"},
    {"id": "Case/500xx2", "loc": "comment:2025-06-03"}
  ],
  "trace": {"retrieveMs": 210, "generateMs": 840, "authZPostFilter": 2}
}
```

### 8.3 `/ingest` (batch fallback)

Accepts NDJSON records from Salesforce export; writes to S3 and triggers KB sync. Kept for completeness with the earlier drafts. fileciteturn0file0

---

## 9) UX, Latency & Caching

- **Streaming answers** to the LWC/Agentforce panel (first‑token under ~300–600 ms target).  
- **Retrieval cache** (30–120s TTL) keyed on:  
  `hash(query, filters, recordContext, salesforceUserId)` → reduce chatter on popular questions.  
- **Cold‑start control**: Provisioned Concurrency for hot Lambdas; warm OpenSearch collections before business hours.  
- **Short‑circuit**: If filters eliminate everything, return “no result” immediately (skip LLM).

---

## 10) Multi‑Tenant Operating Model

- **Isolation:** one AWS account per client (preferred) or strong namespace isolation; per‑tenant **KMS keys**.  
- **Control plane:** AWS Organizations/Control Tower; IaC via **CDK Pipelines**.  
- **Per‑tenant KB:** one Bedrock KB per client; cost and telemetry tagged by `TenantId`.  
- **Monitoring:** Cross‑account CloudWatch dashboards; Athena + QuickSight for cost/usage. fileciteturn0file0

---

## 11) Cost Envelope (order‑of‑magnitude)

- **Pilot:** \$500–\$1,000 / month  
- **Department:** \$1,500–\$3,000 / month  
- **Enterprise:** \$8,000–\$12,000 / month  

Drivers: token volume, retrieval frequency, active users, index size; binary embeddings reduce storage/memory for large corpora. The original ranges are reconciled here into a single conservative envelope. fileciteturn0file0 fileciteturn0file1

---

## 12) Data Cloud vs. AWS‑Hosted RAG (when to use which)

| Situation | Data Cloud RAG | AWS‑Hosted RAG (this design) |
|---|---|---|
| Tight admin UX inside SFDC, fewer knobs | ✅ |  |
| Custom rankers, cross‑entity joins, external corpora at scale |  | ✅ |
| No PrivateLink setup | ✅ |  |
| Strict per‑tenant isolation, BYOK, custom guardrails |  | ✅ |
| Willing to pay DC credits/storage for convenience | ✅ |  |
| Need one retriever that also serves non‑SFDC apps |  | ✅ |

Both paths can co‑exist; this design emphasizes **flexibility and control**. fileciteturn0file1

---

## 13) Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| AuthZ leak (sharing/FLS mismatch) | High | Index‑tags + query filters + post‑filter SOQL check; redacted variants; prompt guard. |
| Freshness gaps / API limits | High | Prefer AppFlow + CDC; back‑pressure & DLQs; fall back to batch exports off‑peak. |
| Latency spikes | Medium | Streaming; retrieval cache; provisioned concurrency; pre‑warm OpenSearch. |
| Relevance on cross‑entity queries | Medium | Composite “dossier” docs; graph‑aware boosts; optional rerank. |
| Cost creep | Medium | Binary embeddings for large corpora; model tiering; cache; dashboards and budgets. |

---

## 14) Milestones & Acceptance Criteria

1) **Thin‑slice POC** (Accounts, Opportunities, Notes)  
   - AppFlow + CDC; Facts + Narratives indexes; hybrid authZ; streaming answers.  
   - **Exit**: precision@5 ≥ target on 50‑question set; zero authZ leaks in red‑team; p95 latency within UX budget.

2) **Cross‑Entity V1**  
   - Composite “Account dossier” docs; adjacency boosts; LWC facets & citations pane.  
   - **Exit**: 80% accuracy on multi‑hop eval set; A/B shows user preference over native search.

3) **Pilot Hardening**  
   - Binary embeddings for large tenants; provisioned concurrency; retrieval cache; dashboards.

4) **Enterprise Scale**  
   - Optional OpenSearch **managed** cluster; Neptune for relationship‑heavy workloads; extend to Contracts/Leases/Properties and external doc stores. fileciteturn0file1

---

## 15) Appendices

### A) Minimum Metadata Schema
```
sobject, recordId, parentIds[], territory, businessUnit, region,
ownerId, sharingBuckets[], flsProfileTags[], hasPII,
effectiveDate, lastModified, language, churnRiskTag?, contractType?
```

### B) AuthZ Sidecar Interface (sketch)
**`POST /authz/eval`**  
**Input:** `{ "salesforceUserId": "005…", "recordContext": {...} }`  
**Output:** `{ "sharingBuckets": ["R1","BU:CRE-Dallas",…], "flsProfileTags": ["FLS:std","Note:redacted"] }`

### C) Retrieval Cache Key
`sha256(query + filters + recordContext + salesforceUserId)` → TTL 30–120s

### D) Grounding & Prompt Policy (excerpt)
- Always answer **only** from allowed citations.  
- If **no allowed** citations remain after post‑filter, respond with a helpful **no‑answer**.  
- Include citations at the paragraph level (record IDs + anchors).

### E) Example Lightning UX Behaviors
- Toggle facets; click citation → side panel opens record preview via signed S3 URL or deep link.  
- “Explain this answer” expands to show top‑K candidates, scores, and filters applied.

---

**This document merges and refines the earlier drafts so it can serve as the single source of truth for implementation planning and stakeholder review.** fileciteturn0file0 fileciteturn0file1


<!-- SOURCE FILE: /mnt/data/Ascendix_SFDC_AI_Search_Master_v1.1.md -->

# Ascendix Unified AI Search & Agent Platform for Salesforce (AWS‑Hosted RAG)

*Base document missing in this environment; generating Actions section as a standalone addendum below.*

---

## 16) Agent Actions (Create/Update) — Safe “Act” Path for the Embedded Agent
**Status:** Added in v1.1 (extends Sections 3, 8, 11, 14) • **Purpose:** allow the chat agent to **create and update Salesforce records** safely, without expanding the AWS surface area. Principle: **retrieval in AWS**, **writes in Salesforce**. fileciteturn0file0 fileciteturn0file1

### 16.1 Design Principles
- **Keep DML inside Salesforce** to inherit sharing, FLS, validation rules, triggers, duplicate rules, and transactionality.
- **Expose narrow, business‑named actions** to the agent (no generic “execute GraphQL/soql” tool).
- **Two‑step UX**: the agent proposes an action **preview**; the user **confirms** before execution.
- **Idempotency and auditability** are first‑class (per‑action idempotency keys; durable audit logs).

### 16.2 Patterns (choose per action)
**A) Agent Action → Flow/Apex (preferred)**  
Autolaunched **Flows** or Apex invocables perform DML **with sharing**. Lowest risk and admin‑friendly.

**B) Agent Action → Apex proxy → Salesforce GraphQL (targeted)**  
For “create and immediately return selected fields in one call,” wrap **GraphQL UI API mutations** behind an Apex proxy with allow‑listed objects/fields. Use sparingly (still Beta; UI‑API‑supported objects only).

> We do **not** grant the LLM a raw “GraphQL” tool. All mutations go through **named, schema‑checked actions**. fileciteturn0file1

### 16.3 Action Catalog (POC → Pilot)
| Action | Type | Inputs (minimal) | Output | Notes |
|---|---|---|---|---|
| `create_opportunity` | Flow | `AccountId, Name, Amount, CloseDate, StageName` | `OpportunityId, Name` | Validate `StageName` vs pipeline values; duplicate check on `(AccountId, Name, CloseDate)` |
| `update_opportunity_stage` | Flow | `OpportunityId, StageName` | `success` | Optimistic concurrency: check `LastModifiedDate` if provided |
| `log_task_followup` | Flow | `WhatId, Subject, DueDate, OwnerId?` | `TaskId` | Default owner = current user |
| `create_case_from_chat` | Flow | `AccountId?, ContactId?, Subject, Description, Origin` | `CaseId` | Optional link to transcript |
| `add_contact_to_account` | Flow | `AccountId, FirstName, LastName, Email` | `ContactId` | Duplicate rule: match on Email |
| `update_account_ownership` | Flow | `AccountId, OwnerId` | `success` | Enforce territory rules |
| `add_note_to_record` | Flow | `ParentId, Title, Body` | `ContentNoteId` | Strip HTML; store chat link |
| `create_event_meeting` | Flow | `WhatId?, WhoId?, Start, End, Subject, Location?` | `EventId` | Calendar collisions optional |

All actions: **validate CRUD/FLS**; reject unknown fields; require **user confirmation**.

### 16.4 Agent‑Facing Contracts (examples)

**`create_opportunity`**
```json
{
  "name": "create_opportunity",
  "description": "Create a new Opportunity for an existing Account.",
  "input_schema": {
    "type": "object",
    "required": ["AccountId","Name","Amount","CloseDate","StageName"],
    "properties": {
      "AccountId": {"type":"string","pattern":"^001"},
      "Name": {"type":"string","minLength":3},
      "Amount": {"type":"number","minimum":0},
      "CloseDate": {"type":"string","format":"date"},
      "StageName": {"type":"string"}
    }
  },
  "output_schema": {
    "type":"object",
    "required":["OpportunityId","Name"],
    "properties":{"OpportunityId":{"type":"string"},"Name":{"type":"string"}}
  }
}
```

**`update_opportunity_stage`**
```json
{
  "name": "update_opportunity_stage",
  "description": "Advance or change the stage of an Opportunity.",
  "input_schema": {
    "type":"object",
    "required":["OpportunityId","StageName"],
    "properties": {
      "OpportunityId":{"type":"string","pattern":"^006"},
      "StageName":{"type":"string"}
    }
  },
  "output_schema":{"type":"object","properties":{"success":{"type":"boolean"}}}
}
```

### 16.5 UX Flow (LWC)
1) User asks: “Create an opportunity for ACME for $1.2M closing Feb 10.”  
2) Agent drafts: **Action Preview** (natural summary + structured inputs).  
3) User clicks **Confirm** → Flow executes → returns ID.  
4) UI shows success toast + deep link; CDC/AppFlow updates the retriever within freshness SLO. fileciteturn0file0

### 16.6 Security & Guardrails
- **With‑sharing** execution; CRUD/FLS checked; territory/validation/duplicate rules honored.  
- **Allow‑listed fields/objects** per action; reject extras; sanitize strings.  
- **Two‑step confirmation** in UI; **dry‑run mode** available in sandboxes.  
- **Idempotency keys** on creates; optimistic concurrency on updates.  
- **Audit** every action (who, what, when, inputs hash, record IDs, result).  
- **Rate limits** per user and per action; **kill switch** via Custom Metadata `ActionEnablement__mdt`. fileciteturn0file1

### 16.7 Observability & Audit
- **Custom Object** `AI_Action_Audit__c`: `UserId, ActionName, InputsHash, Records[], Success, Error, ChatSessionId, LatencyMs`.  
- **CloudWatch** (if any AWS‑side orchestration) mirrors: correlationId = chat session.  
- Dashboards: daily action volume, failure reasons, undo candidates. fileciteturn0file0

### 16.8 GraphQL Proxy (optional) — Skeleton
Use an **Apex invocable** that accepts validated inputs and executes **UI‑API GraphQL** `RecordCreate`/`RecordUpdate`. Keep **allow‑lists** for objects/fields; set `allOrNone` where needed. (Full implementation in the runbook appendix.)

### 16.9 Acceptance Tests (Actions)
- **Security**: different profiles exercising CRUD/FLS paths; red‑team prompt injection (agent must refuse unsupported actions).  
- **Correctness**: created records visible with expected defaults; updates respect validation rules.  
- **Freshness**: new/updated records appear in answers/search within SLO.  
- **UX**: preview → confirm → toast → link flow is reliable; errors are friendly and actionable.



---

