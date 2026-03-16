
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
