
# PRD — Steel Thread / Thin-Slice POC
**Project:** Ascendix Unified AI Search & Agent for Salesforce (AWS‑Hosted RAG)  
**Version:** 0.9 (POC PRD) • **Date:** 2025-11-12 • **Owner:** Ascendix Technologies

**Provenance:** This POC PRD is derived from Ascendix internal drafts “Ascendix BI for Salesforce” and “AgentForce + Search Backend For Salesforce” and the unified master architecture. It focuses on a **minimal end‑to‑end slice** proving value, security, and feasibility. fileciteturn0file0 fileciteturn0file1

---

## 1) Background & Rationale

Salesforce’s native search and current Agentforce patterns are strong at **entity‑level** lookup but weak for **cross‑entity** questions and **permission‑aware, cited** answers. A private, AWS‑hosted RAG backend addresses these gaps while keeping traffic off the public internet (Salesforce **Private Connect → AWS PrivateLink**), enforcing Salesforce **sharing/FLS**, and enabling hybrid **keyword + semantic** retrieval. The POC’s goal is to validate this approach with a thin, production‑like thread. fileciteturn0file0

---

## 2) Goals (POC)

1. **End‑to‑end value demo**: Ask natural questions in Salesforce and receive **streaming, grounded answers with citations** to Salesforce records.  
2. **Security parity**: Enforce Salesforce **sharing rules, territories, and field‑level security (FLS)** at retrieval time and in generated answers.  
3. **Cross‑entity retrieval**: Correctly answer at least two multi‑hop questions spanning **Accounts, Opportunities, and Notes**.  
4. **Private networking**: All calls traverse **Private Connect → PrivateLink** to a **Private API Gateway** in AWS.  
5. **Freshness**: Validate **near‑real‑time** updates via **AppFlow + CDC** (with a batch fallback), with observable lag metrics. fileciteturn0file1

---

## 3) Non‑Goals (POC)

- Replacing Salesforce analytics/BI or Data Cloud search.  
- Autonomous actions in Salesforce beyond read/answer.  
- Broad document types (PDFs, OCR) beyond a minimal set if required for Notes; heavy KG/graph is optional.

---

## 4) Target Users & Primary Use Cases

**Personas**: AE/Sales Rep, Sales Manager, Customer Success.  
**Top POC use cases**:  
- U1: “Show open opportunities over $1M for ACME in EMEA and summarize blockers.”  
- U2: “Which accounts have leases expiring next quarter with HVAC‑related cases in the last 90 days?”  
- U3: “Summarize renewal risks for ACME with citations to Notes.”

---

## 5) In‑Scope (POC)

- **Objects**: `Account`, `Opportunity`, `Case` (subset), `Note` (or `ContentNote`).  
- **UI**: One **Lightning Web Component (LWC)** embedded on Account and Home; optional Agentforce tool hookup.  
- **APIs**: `/retrieve` and `/answer` (private, documented below).  
- **Retrieval**: **Bedrock Knowledge Base** backed by **OpenSearch** (hybrid dense+BM25).  
- **Embeddings**: **Titan Text Embeddings v2** (binary OK if index > 50k chunks).  
- **AuthZ**: Index‑tags + query‑time filters + post‑filter “can view?” gate; FLS redaction where applicable.  
- **Freshness**: **AppFlow + Salesforce CDC** streaming → S3 → KB sync; **batch Apex export** as fallback.  
- **Observability**: Metrics for retrieval quality, latency, authZ denials, grounding compliance. fileciteturn0file0

**Out‑of‑Scope (POC)**: Contracts/Leases/Properties full model; Neptune graph; multilingual; external DMS; enterprise SSO federation changes.

---

## 6) Success Metrics (POC)

- **Retrieval precision@5** on curated set ≥ **70%** (baseline) with grounded answers.  
- **p95 first token** ≤ **800 ms** (from LWC request to first streamed token).  
- **p95 end‑to‑end answer** ≤ **4.0 s** (for < 1k token answers).  
- **0 security leaks** in red‑team tests (row/field visibility).  
- **Freshness lag P50** ≤ **5 min** (CDC path), with dashboards showing ingest → index lag.  
- **User‑perceived value**: ≥ **80%** of pilot users rate answers “useful” or better in UAT.

---

## 7) Functional Requirements

### F1. Search/Chat UX (LWC)
- Single text box with **streaming answers** and a **citations drawer** (expand to show record IDs and snippets).  
- Facets: Region, BU, Quarter (static for POC).  
- Display **no‑answer** when zero allowed citations remain after authZ. fileciteturn0file1

### F2. Agentforce Integration (optional for POC)
- Register **two tools**: `retrieve_knowledge` → `/retrieve`, `answer_with_grounding` → `/answer`.  
- Agent must prefer retriever grounding over model priors when tools are available. fileciteturn0file1

### F3. Retrieval
- Hybrid query (dense + BM25) filtered by `sobject`, `region`, `businessUnit`, plus **authZ tags**.  
- `topK` default 8; re‑rank optional. Return `title`, `snippet`, `metadata`, `previewUrl` (presigned).

### F4. Answering
- Compose system prompt with grounding policy (“**answer only from allowed citations**”).  
- Require paragraph‑level citations; disallow speculative content.  
- Persist Q/A and telemetry to DynamoDB (TTL for chat rows).

### F5. Authorization Parity
- **Index‑time metadata**: `sobject, recordId, parentIds[], ownerId, territory, businessUnit, region, sharingBuckets[], flsProfileTags[], hasPII, lastModified`.  
- **AuthZ sidecar** computes `sharingBuckets[]` and `flsProfileTags[]` per `salesforceUserId` (cache 24h; bust on demand).  
- **Post‑filter**: For top‑K, validate “can view?” before generating or returning snippets.  
- **FLS variants**: Redacted vs. full chunk variants for sensitive fields. fileciteturn0file0

### F6. Ingestion & Freshness
- **Preferred**: AppFlow + CDC → S3 → EventBridge/Step Functions → Bedrock KB sync.  
- **Fallback**: Scheduled Apex export → `/ingest` → S3 → KB sync (off‑peak). fileciteturn0file0

### F7. Operations & Admin
- CloudWatch dashboard: p50/p95 latency, precision@k (from offline evals), retrieval hit rate, authZ denials, freshness lag.  
- Alarms on ingest backlog, API 5xx, OpenSearch health.

---

## 8) Non‑Functional Requirements (NFRs)

- **Security/Privacy**: PrivateLink path only; no public S3; KMS encryption (S3/OpenSearch/DynamoDB); Bedrock Guardrails on **prompt/PII/grounding**.  
- **Availability**: API p95 latency targets above; soft target **≥ 99.5%** availability for POC hours.  
- **Scalability (POC)**: Up to **100k chunks** total; retrieval cache with 30–120s TTL.  
- **Cost**: Fit within **pilot** envelope, with cost tags/alerts by `TenantId`.  
- **Accessibility**: LWC supports keyboard navigation and visible focus states. fileciteturn0file1

---

## 9) Data & Indexing

- **Chunking**: 300–500 tokens; retain headings; flatten simple tables.  
- **Indexes**:  
  - **Facts**: canonical fields/roll‑ups for precision joins.  
  - **Narratives**: long text (Notes, Case comments).  
- **Metadata schema** (minimum):  
  `sobject, recordId, parentIds[], territory, businessUnit, region, ownerId, sharingBuckets[], flsProfileTags[], hasPII, effectiveDate, lastModified, language`. fileciteturn0file0

---

## 10) Interfaces (POC)

### 10.1 `/retrieve` (Private API Gateway)
**Request**
```json
{
  "query": "Show open opportunities in EMEA over $1M",
  "filters": {"sobject": ["Opportunity"], "Region": "EMEA"},
  "recordContext": {"AccountId": "001xx"},
  "salesforceUserId": "005xx",
  "topK": 8,
  "hybrid": true,
  "authzMode": "both",
  "ranker": "default"
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
      "snippet": "ACME renewal valued at $1.2M closes 2026-02-10…",
      "metadata": {"sobject":"Opportunity","Region":"EMEA","OwnerId":"005…"},
      "previewUrl": "https://signed-s3-url/…"
    }
  ]
}
```

### 10.2 `/answer` (Private API Gateway)
**Request**
```json
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

---

## 11) UX Requirements (POC)

- **Streaming**: show tokens as they arrive; skeleton state for citations.  
- **Citations drawer**: record IDs + snippet; clicking opens a side panel with preview (presigned S3) or deep link.  
- **Facet chips**: Region/BU/Quarter filters applied to `/retrieve`.  
- **Error handling**: Friendly messages for “no results”, “access denied”, and transient errors. fileciteturn0file1

---

## 12) Acceptance Criteria (POC Exit)

1. **Value**: 10–20 curated questions return **correct, cited** answers; precision@5 ≥ **70%**.  
2. **Security**: Red‑team suite finds **no leaks** (FLS & sharing).  
3. **Performance**: First token ≤ **800 ms** p95; end‑to‑end ≤ **4.0 s** p95 on standard prompts.  
4. **Freshness**: CDC path shows **≤ 5 min** P50 ingest‑to‑index lag on change events.  
5. **Reliability**: No Sev‑1 incidents during a defined test window; alarms function as expected. fileciteturn0file0

---

## 13) Deliverables

- LWC (search/chat + citations drawer) and optional Agentforce tool wiring.  
- Private **API Gateway** with `/retrieve`, `/answer`; **Lambdas**; **DynamoDB** (chats/telemetry).  
- **Bedrock KB** + **OpenSearch** index(es); **Titan v2** embeddings.  
- **AppFlow + CDC** ingestion + Step Functions pipeline; batch fallback.  
- CloudWatch dashboards, alarms; basic runbooks.  
- PRD + API contracts + eval dataset and test harness. fileciteturn0file1

---

## 14) Milestones (Phase‑gated)

- **M1 — Thin thread online**: LWC → Private API → `/retrieve` → citations (no generation).  
- **M2 — Grounded answers**: `/answer` streaming with paragraph‑level citations and guardrails.  
- **M3 — AuthZ parity**: index‑filter + post‑filter gates; redaction variants pass tests.  
- **M4 — Freshness**: CDC/AppFlow lag within target; dashboards & alarms live.  
- **M5 — Pilot hardening**: cache, cold‑start mitigation, eval harness & UAT complete. fileciteturn0file0

---

## 15) Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| AuthZ mismatch leaks data | High | Sidecar + index tags + post‑filter validation; redaction variants; prompt guard. |
| PrivateLink/Private Connect nuances | Medium | Follow reference setup; start in a single region; smoke tests before LWC wiring. |
| Latency spikes | Medium | Provisioned concurrency; retrieval cache; stream early; pre‑warm OpenSearch. |
| Freshness gaps | Medium | CDC + DLQs; back‑pressure; batch fallback off‑peak. |
| Relevance on cross‑entity queries | Medium | Composite “dossier” docs; optional re‑rank; lightweight relationship boosts. |

---

## 16) Dependencies & Assumptions

- Salesforce sandbox with Agentforce enabled, **Named Credential** approved.  
- AWS account(s) with Bedrock, OpenSearch, PrivateLink, AppFlow access in target region.  
- Tenant data sample available for initial ingest; PII policy defined. fileciteturn0file1

---

## 17) Test Plan (POC)

- **Unit**: chunker, metadata tags, authZ sidecar, citation assembler.  
- **Integration**: `/retrieve` hybrid filters; `/answer` guardrails; PrivateLink path validation.  
- **E2E**: scripted queries for U1–U3; measure latency & correctness.  
- **Security**: red‑team with users at different roles/profiles; verify FLS redaction.  
- **Reliability**: inject faults (OpenSearch throttle; Bedrock timeout) → observe graceful degradation. fileciteturn0file0

---

## 18) Rollback & Teardown (POC)

- Disable LWC tab; unregister Agentforce tools.  
- Drain traffic; disable API; snapshot dashboards; export logs.  
- Tear down stacks in reverse dependency; purge S3 prefixes with retention policy.

---

## 19) Open Questions

- Do we require **binary embeddings** in POC or only at pilot scale?  
- Should we include **Case** in the first thread or defer to pilot?  
- Preferred **answer style** (bullet vs. narrative) and max tokens per response?

---

**Appendix A — Minimal Metadata Schema**  
`sobject, recordId, parentIds[], territory, businessUnit, region, ownerId, sharingBuckets[], flsProfileTags[], hasPII, effectiveDate, lastModified, language`

**Appendix B — Prompt Policy (excerpt)**  
- Answer only from allowed citations. If none, return a helpful **no‑answer**.  
- Include citations per paragraph, with record ID + pointer (field or note anchor).

**References:** Internal drafts “Ascendix BI for Salesforce” and “AgentForce + Search Backend For Salesforce.” fileciteturn0file0 fileciteturn0file1
