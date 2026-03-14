# AscendixIQ Salesforce Solution Pack – Admin Runbook (Unified)
**Version:** 1.0 (Unified)  
**Owner:** Ascendix Technologies  
**Status:** Draft for Review

This document supersedes the prior:
- `Ascendix_Admin_Runbook_Agent_Actions.md`

It brings the Admin Runbook into full alignment with the **AscendixIQ Core Manifest** and the **Salesforce Solution Pack Master Architecture**, reframing Salesforce Agent Actions as **AscendixIQ Mini‑Runbooks**.

---

# 0. Purpose

This runbook enables Salesforce Admins to safely configure, manage, and monitor:
- **Agent Actions** (Mini‑Runbooks) executed from chat or Agentforce  
- **AuthZ Adapter integration**  
- **Case mapping**  
- **Template and metadata alignment**  
- **Audit and observability requirements**

This ensures that all actions executed inside Salesforce are:
- Secure  
- Governed  
- Logged  
- Idempotent  
- Fully compatible with AscendixIQ Core  

---

# 1. Prerequisites

Admins must have:
- Salesforce sandbox or org participating in the POC/Pilot  
- AscendixIQ API Gateway PrivateLink endpoint configured  
- Named Credential set up  
- Required permissions to create Flows, Apex classes, and Permission Sets  

Core services must be deployed:
- Case Manager  
- Skills Registry  
- Runbook Engine  
- AuthZ Adapter (Salesforce implementation)  
- Templates for `Account`, `Opportunity`, `Note`

---

# 2. Concepts Admins Must Understand

### 2.1 Mini‑Runbooks (Salesforce Agent Actions)  
In AscendixIQ, an Agent Action is a **mini‑runbook**:
- Defined as a deterministic transactional workflow  
- Invoked from Salesforce  
- Executed via Flow/Apex, but represented in Core as a Runbook execution  
- Anchored to a `caseId`  
- Logged in the AscendixIQ audit log

### 2.2 Case Mapping  
- Every chat session maps to a `caseId` with `caseType = sfdc_chat`  
- Every action execution links to that same case  
- This allows long‑term traceability, grounding, and auditing

### 2.3 AuthZ Adapter  
- All actions must respect Sharing and FLS  
- Enforcement occurs BOTH in Salesforce (Flow/Apex) and in AscendixIQ Core  
- Admins configure FLS and sharing normally; no additional configuration required  

---

# 3. Enablement Checklist

### 3.1 Permission Set: `AIQ_Action_Executor`
Must include:
- CRUD/FLS for target objects  
- Access to Flows  
- Access to Named Credential used for PrivateLink calls  
- Access to Apex proxy (if used)

### 3.2 Custom Metadata: `AIQ_Action_Config__mdt`
Fields:
- `ActionName__c`  
- `Enabled__c`  
- `MaxPerUserPerDay__c`  
- `RequiresConfirmation__c`  

Acts as the **runbook kill switch** and rate limiter.

### 3.3 Audit Object: `AIQ_Action_Audit__c`
Stores:
- UserId  
- CaseId  
- ActionName  
- InputsJson (encrypted)  
- InputsHash  
- Result  
- Timestamp  
- ExecutionTimeMs  
- Error/Failure Reason  

### 3.4 Flows (Autolaunched)
Each Action requires:
- A Flow named exactly after the mini-runbook (e.g., `create_opportunity`)  
- With Sharing enabled  
- Validation steps  
- Error handling  
- Output structure matching the runbook schema  

Flows serve as the **Salesforce execution layer** for AscendixIQ mini-runbooks.

### 3.5 Register Actions With Agentforce
For each Action, define:
- Name  
- Description  
- JSON input schema  
- JSON output schema  
- Example calls  
- Confirmation UI requirement  

---

# 4. Supported Mini‑Runbooks (POC)

### 4.1 `create_opportunity`
Input:
- `AccountId`, `Name`, `Amount`, `CloseDate`, `StageName`

Behavior:
- Creates Opportunity  
- Enforces duplicate rules  
- Enforces FLS  
- Links to Case via runbook logging

### 4.2 `update_opportunity_stage`
Input:
- `OpportunityId`, `StageName`

Behavior:
- Validates Stage  
- Updates and logs change  

### 4.3 `log_task_followup`
Input:
- `WhatId`, `Subject`, `DueDate`

Behavior:
- Creates Task on the record in context  

### 4.4 `create_case_from_chat`
Input:
- `AccountId`, `ContactId`, `Subject`, `Description`

Behavior:
- Creates Case  
- Optionally associates chat transcript  

---

# 5. Guardrails (Mandatory)

1. **Two-Step Confirmation**  
   User must click “Confirm” before any action executes.

2. **FLS Enforcement**  
   Flows must run **with sharing**.

3. **Input Allow-Listing**  
   Reject unknown fields. No dynamic field sets.

4. **Idempotency**  
   Actions use external IDs or input-hash logic.

5. **Rate Limits**  
   Enforced by `AIQ_Action_Config__mdt`.

6. **Error Handling**  
   Friendly, deterministic errors returned to chat.

7. **Audit Logging**  
   All executions recorded in `AIQ_Action_Audit__c`.

8. **CDC Sync**  
   After action execution, AppFlow/CDC must update AscendixIQ index.

---

# 6. Monitoring & Observability

Admins must monitor:

### In Salesforce:
- Runbook failures (Flow errors)  
- Permission issues (CRUD/FLS failures)  
- Validation rule violations  
- Audit record volume  

### In AscendixIQ Core:
- Runbook execution duration  
- Error rate  
- AuthZ Adapter denials  
- Retrieval freshness (CDC lag)  
- Per-tenant usage  

Dashboards are provided in CloudWatch and QuickSight.

---

# 7. UAT Requirements

Test with three profiles:
- Sales User  
- Sales Manager  
- Admin  

Required tests:
- FLS variations  
- Sharing-rule edge cases  
- Redaction variant selection  
- Action preview → confirm → result workflow  
- CDC updates reflected in SFDC search  

Red-team scenarios MUST include:
- Attempted unauthorized updates  
- Prompt injection attempts  
- Field overposting  
- Invalid schema payloads  

---

# 8. Rollback Procedures

If any issue arises:
1. Set `Enabled__c = false` in `AIQ_Action_Config__mdt`  
2. Remove permission set from users  
3. Unregister Agentforce Action  
4. Leave retriever active (read-only mode)  
5. Validate CDC/ingestion pipelines  

Rollback completes in < 1 minute.

---

# 9. Future Hardening Plans

- Versioned mini-runbooks with migration support  
- Action packs for Property, Lease, and Custom Objects  
- SF → Core → SF bi-directional workflow graphs  
- Action throttling based on business rules  
- Expanded HITL UIs for approvals  

---

# 10. Provenance

This unified runbook replaces and consolidates:
- `/mnt/data/Ascendix_Admin_Runbook_Agent_Actions.md`
- AscendixIQ Core Manifest  
- Salesforce Solution Pack Master Architecture  

