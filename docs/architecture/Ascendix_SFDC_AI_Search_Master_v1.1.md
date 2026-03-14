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

