# AscendixIQ Salesforce Solution Pack – Thin Slice POC PRD  
**Version:** 1.0 (Unified)**  
**Owner:** Ascendix Technologies**  
**Status:** Draft for Review**

This PRD defines the **Thin Slice POC** for the *Salesforce Solution Pack* of the **AscendixIQ Platform**, validating the **Fast Path**, **Core Skills**, **AuthZ Adapter**, **Templates**, **Case Model**, and **Mini‑Runbooks (Agent Actions)**.

---

# 0. Purpose of the POC

The POC validates that **AscendixIQ Core** can power a **real-time, permission-aware, grounded search and agent assistant** inside Salesforce.

The POC acts as:

- The **first production-grade workload** on AscendixIQ Core  
- A validation of the Fast Path (real-time chat + retrieval + grounding)  
- A validation of the **SalesforceAuthZAdapter**  
- The first implementation of **Agent Actions** as **mini-runbooks**  
- A foundation for the standalone AscendixIQ application  

---

# 1. Scope

## 1.1 In Scope

### **Core Fast Path**
- `/retrieve` → Core skill `rag.retrieve`
- `/answer` → Core skill `rag.answer_with_citations`
- Streaming responses
- Unified citation schema

### **Salesforce Solution Pack Components**
- LWC Chat UI (thin client)
- Agentforce tool wiring
- Case model mapping (`sessionId` → `caseId`)
- Template-aware indexing for:
  - Account  
  - Opportunity  
  - Note  
- AppFlow + CDC ingestion

### **AuthZ Adapter**
- Sharing & Territory
- Field-level Security (FLS)
- Post-filter validation
- Redacted snippet variants

### **Mini-Runbooks (Agent Actions)**
Included per user choice (**Option A**):
- `create_opportunity`
- `update_opportunity_stage`
- `log_task_followup`
- `create_case_from_chat`

### **Observability**
- Latency (retrieveMs, generateMs)
- precision@5
- grounding trust score
- authz denials
- runbook execution metrics

---

# 2. Non‑Scope

- Full Standalone AscendixIQ UI  
- Heavy Runbooks (Lease Abstraction, Portfolio Analysis)  
- Advanced graph boosting  
- OCR/Textract pipelines  
- Multi-language  
- External DMS integrations  
- Enterprise-wide guardrail tuning  

These are planned for Pilot or V1.

---

# 3. Objectives (POC Goals)

1. **Real-time grounded answers inside Salesforce**
   - Streaming
   - Citations per paragraph
   - No hallucinations, no ungrounded content

2. **AuthZ parity with Salesforce**
   - Sharing & Territory model enforced
   - FLS-driven redaction
   - Zero data leakage

3. **Cross-entity retrieval**
   - Accounts
   - Opportunities
   - Notes

4. **Fast Path validation**
   - p95 first token under 800ms
   - p95 full answer under 4s

5. **Agent Action execution**
   - Preview → Confirm → Execute
   - Logged via Core Runbook Engine
   - CDC updates reflected in retriever within freshness SLA

6. **Single engine powering Salesforce + future standalone app**
   - Skills, Templates, Runbooks reused across solution packs

---

# 4. Architecture Overview (Aligned with AscendixIQ Core)

```mermaid
flowchart TD
  SF[LWC / Agentforce] --> PC[Private Connect]
  PC --> PL[AWS PrivateLink]

  PL --> APIGW[AscendixIQ API Gateway (Private)]

  APIGW --> RET[Skill: rag.retrieve]
  APIGW --> ANS[Skill: rag.answer_with_citations]

  RET --> KB[Bedrock Knowledge Base]
  KB --> OS[OpenSearch]

  ANS --> LLM[LLM (Bedrock)]
  ANS --> CASE[Case Manager]

  subgraph Core[AscendixIQ Core]
    AUTHZ[AuthZ Adapter<br/>(Salesforce Sharing + FLS)]
    SKILLS[Skills Registry]
    RUN[Runbook Engine<br/>(Mini-Runbooks)]
  end
```

---

# 5. Detailed Requirements

## 5.1 Functional Requirements

### F1 – **Chat Panel (LWC)**
- Single text entry
- Streaming tokens
- Citations drawer reading unified schema
- Error states (no results, access denied, model refusal)
- Session management for mapping to `caseId`

### F2 – **Agentforce Tools**
- Tool: `retrieve_knowledge` → `/retrieve`
- Tool: `answer_with_grounding` → `/answer`
- Tool: `execute_action` → mini-runbook invocation

### F3 – **Retrieval**
- Hybrid dense + BM25
- Filters using template metadata
- AuthZ filters (index + runtime)
- topK configurable (default: 8)
- Core skill: `rag.retrieve`

### F4 – **Answering**
- Grounded generation
- Paragraph-level citations
- Refusal policy for ungrounded questions
- Core skill: `rag.answer_with_citations`

### F5 – **Agent Actions (Mini‑Runbooks)**
- Preview → Confirm → Execute
- Executed via SF Flows/Apex but represented as Core runbooks
- Logged in Core runbook audit model

### F6 – **Case Model Integration**
- `sessionId` → `caseId` mapping  
- Case type: `sfdc_chat`
- Context: Account/Opportunity scope

### F7 – **Indexing & Ingestion**
- AppFlow + CDC ingestion
- Templates: `sfdc_account_v1`, `sfdc_opportunity_v1`, `sfdc_note_v1`
- Chunking 300–500 tokens
- Metadata enrichment:
  - sharingBuckets  
  - flsProfileTags  
  - ownerId  
  - region/businessUnit  

### F8 – **Authorization Parity**
- Index-time scoping
- AuthZ Adapter producing:
  - sharingBuckets  
  - flsProfileTags  
- Post-filter FLS enforcement
- Redaction variants

### F9 – **Observability**
- CloudWatch dashboards:
  - retrieveMs, generateMs  
  - precision@5  
  - authZ denials  
  - runbook failures  
  - cost per tenant  
- Evaluation dataset for curated queries

---

# 6. Success Metrics

### Retrieval Quality
- precision@5 ≥ 70%  
- grounding violations = 0  

### Performance
- First token p95 ≤ 800ms  
- Full answer p95 ≤ 4s  

### Security
- 0 FLS leaks  
- 0 sharing-rule violations  
- 100% compliance in red-team tests  

### Mini-Runbook Execution
- ≥ 95% successful action executions  
- CDC freshness p50 ≤ 5 min  
- Index reflects updates produced by actions  

### UX
- 80%+ pilot users report improved search relevance  
- 80%+ adoption among target profiles  

---

# 7. Acceptance Criteria (POC Exit)

A POC is considered complete when:

1. LWC chat component works end-to-end with streaming and citations.  
2. AuthZ adapter passes all red-team tests.  
3. Answers remain grounded 100% of the time.  
4. Cross-entity retrieval validated.  
5. Mini-runbooks functional:  
   - `create_opportunity`  
   - `update_opportunity_stage`  
   - `log_task_followup`  
6. CDC ingestion successfully updates the index.  
7. Dashboards live and reporting metrics.  
8. No Sev-1 or Sev-2 issues under load.  

---

# 8. Out-of-Scope (Clarified for Future Phases)

- LeaseIQ workflows  
- OCR and document Runbooks  
- Graph-based contextual boosts  
- Custom rankers  
- Template editor UI  
- Full standalone AscendixIQ web app

These depend on completing this POC.

---

# 9. Future Path: Pilot → V1

### Pilot
- Add Cases & Tasks objects  
- Expand Actions catalog  
- Add graph adjacency boosts  
- Add more templates (Documents, Events, Emails)  
- Hardening for multi-region HA  

### V1
- Plug standalone AscendixIQ UI into same Fast Path  
- Expand Runbook Engine  
- Full template library  
- Integration with document intelligence pipelines  

---

# 10. Provenance

This unified document was generated by merging and realigning:

- `/mnt/data/Ascendix_Steel_Thread_POC_PRD.md`  
- AscendixIQ Core Manifest  
- AscendixIQ Salesforce Solution Pack Master Architecture  

All outdated terminology and structures have been replaced.

