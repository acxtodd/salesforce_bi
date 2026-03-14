# AscendixIQ Core Manifest  
**Version:** 0.1 (Draft for internal alignment)  
**Owner:** Ascendix Technologies  

> This document defines the core concepts, architecture, and conventions that all AscendixIQ implementations must follow, including the Salesforce Solution Pack and the standalone AscendixIQ application.

---

## 0. Purpose

AscendixIQ is a **vertical AI platform for Commercial Real Estate (CRE)** that provides:

- A **shared intelligence layer** (RAG, skills, runbooks, authz, evals).  
- Multiple **solution packs**: Salesforce assistant, lease abstraction, portfolio analysis, etc.  
- Multiple **delivery surfaces**: embedded (Salesforce, Teams) and standalone web.

This manifest ensures:

- One **AscendixIQ Core**, not multiple overlapping engines.  
- Salesforce work and standalone AscendixIQ work **converge** on the same abstractions.  
- New solution packs can be delivered without re-inventing architecture.

---

## 1. Core Concepts

### 1.1 AscendixIQ Core

AscendixIQ Core is the shared backend and architecture that all solution packs use. It consists of:

- Retrieval Layer (hybrid dense + keyword RAG)  
- Generation Layer (LLMs with strict grounding and guardrails)  
- Skills & Runbooks  
- Case Model  
- Template-Aware Indexing  
- AuthZ Adapter  
- Observability & Evaluation

All projects (Salesforce and standalone) are expected to use these elements.

---

## 2. Execution Paths: Fast vs Slow

### Fast Path (Synchronous / Real-Time)
- Chat assistants (Salesforce LWC, standalone chat panel)  
- API Gateway → Lambda → Retrieval → LLM  
- Strict latency budgets  

### Slow Path (Asynchronous / Workflow)
- Document ingestion, abstraction, portfolio analysis  
- Step Functions / workflow orchestration  
- Minutes-scale processing acceptable  

---

## 3. Case, Session, and Record Context

### Case  
Canonical unit of work across all solution packs.

### Session  
Frontend construct, mapped internally to a Case.

### Record Context  
Filters, anchors, and contextual hints for retrieval and reasoning.

---

## 4. Skills and Runbooks

### Skills  
Single-purpose, reusable operations with clear schemas.

### Runbooks  
Multi-step orchestrations (analysis, abstraction, enrichment, validation).

Salesforce “Agent Actions” are treated as **mini-runbooks**.

---

## 5. Template-Aware Indexing

Templates define:
- Source mappings  
- Metadata schema  
- Chunking rules  
- Index destinations  

Salesforce objects become templates (`sfdc_opportunity_v1`, etc.).

---

## 6. Metadata & Citation Schema

### Metadata (Minimum Required)
- sourceSystem  
- templateId  
- entityType / sobject  
- recordId  
- parentIds  
- territory / businessUnit / region  
- ownerId  
- sharingBuckets  
- flsProfileTags  
- hasPII  
- lastModified  
- language  

### Citation Schema
Consistent citation objects returned by Core regardless of UI.

---

## 7. Authorization & Identity

AscendixIQ uses **AuthZ Adapters**:
- SalesforceAuthzAdapter  
- Future: AscendixIdentityAdapter  

Core retrieval never bypasses authorization.

---

## 8. Observability & Evaluation

Standard metrics:
- Latency (p50/p95)  
- precision@k  
- grounding trust score  
- authz denials  
- usage/cost per tenant  

Shared dashboards and evaluation datasets.

---

## 9. Multi-Tenancy and Isolation

- Per-tenant KBs / indexes  
- Per-tenant configuration  
- Cost allocation  
- Isolation boundaries enforced at ingestion, retrieval, and runbook levels

---

## 10. Design Principles

1. Core-first, UI-second  
2. No business logic in UIs  
3. Pluggable integrations  
4. Template-aware ingestion  
5. Grounded by default  
6. One engine, many surfaces  

---

