
# CDK Scaffolding Checklist — Ascendix Salesforce AI Search (POC)
**Scope:** Stand up the minimum AWS + Salesforce plumbing for a private retriever and grounded answers.  
**Date:** 2025-11-12 • **Owner:** Ascendix Engineering

> This checklist aligns with the unified architecture and the two source drafts. Use it to bootstrap the POC quickly and safely. fileciteturn0file0 fileciteturn0file1

## 0) Assumptions
- You have an Ascendix sandbox Salesforce org and an AWS management account with Control Tower (or a single POC account).  
- Agentforce is available in the org; you can register private tools. fileciteturn0file1

## 1) Prerequisites
- [ ] AWS CLI v2, Node 18+, PNPM/Yarn, **AWS CDK v2** installed.  
- [ ] Accounts: `mgmt`, `tenant‑poc` (or a single POC account).  
- [ ] **KMS key policy** pattern for per‑tenant keys ready.  
- [ ] Salesforce **Named Credential** pattern approved. fileciteturn0file0

## 2) Repository layout (monorepo)
```
/infra           # CDK app (TypeScript)
  /stacks
  /pipelines
  cdk.json
/services
  /ingest        # Lambda code
  /retrieve
  /answer
/apps
  /sfdc-lwc      # Lightning Web Component(s)
/ops
  /runbooks
  /dashboards
```
fileciteturn0file0

## 3) Environments & naming
- [ ] Stages: `dev`, `pilot`, `prod` (or `poc` only).  
- [ ] Tagging standard: `TenantId`, `Env`, `CostCenter`, `DataClass`.  
- [ ] Parameterize with **SSM Parameter Store** for endpoints/ARNS; secrets in **Secrets Manager**. fileciteturn0file0

## 4) Bootstrap
- [ ] `cdk bootstrap aws://ACCOUNT/REGION` for each environment.  
- [ ] Enable cross‑account roles if using Control Tower Pipelines.  
- [ ] Create CI pipeline (GitHub Actions or CodePipeline) to synth, diff, deploy. fileciteturn0file0

## 5) Networking & ingress
- [ ] **VPC** with 2+ AZs; private subnets; NAT as needed.  
- [ ] **VPC endpoints**: S3 (Gateway), Bedrock (Interface), Logs/X‑Ray (Interface) as required.  
- [ ] **Private ingress** for Salesforce via **PrivateLink** (Salesforce Private Connect) to your API layer’s private endpoint (NLB‑fronted).  
- [ ] Security groups: least‑privilege; block public egress from data planes. fileciteturn0file0

## 6) Storage & index
- [ ] **S3 buckets**: `ingest/raw`, `ingest/processed`, `previews/` — all KMS‑encrypted, block public access.  
- [ ] **OpenSearch** (Serverless or Managed) collection/domain for hybrid retrieval.  
- [ ] **Bedrock Knowledge Base** connected to S3 + OpenSearch; configure **Titan Text Embeddings v2**. fileciteturn0file0

## 7) Compute & APIs
- [ ] **API Gateway (Private)** with endpoints: `/ingest`, `/retrieve`, `/answer`.  
- [ ] **Lambdas**: `ingest`, `retrieve`, `answer` with provisioned concurrency for hot paths.  
- [ ] **IAM**: least‑privilege roles to S3, OpenSearch, Bedrock, logs.  
- [ ] **DynamoDB**: table for chats/telemetry (TTL on chat items). fileciteturn0file0

## 8) Ingestion path
- [ ] **Preferred:** **Amazon AppFlow + Salesforce CDC** to stream deltas into S3.  
- [ ] **Fallback:** Scheduled Apex → NDJSON → `/ingest`.  
- [ ] **Chunker**: 300–500 token chunks; attach metadata (sobject, recordId, ownerId, territory, BU, region, hasPII, lastModified). fileciteturn0file1

## 9) Authorization parity
- [ ] Implement **AuthZ sidecar** to compute `sharingBuckets[]` and `flsProfileTags[]` for a `salesforceUserId`.  
- [ ] Index‑time tags + **query‑time filters**; **post‑filter** “can view?” gate before citations/LLM.  
- [ ] Maintain redacted vs. full variants when FLS differs materially. fileciteturn0file0

## 10) Agentforce & Salesforce wiring
- [ ] **Named Credential** → Private endpoint (Private Connect).  
- [ ] Register tools:  
  - `retrieve_knowledge(query, filters, recordContext)` → `/retrieve`  
  - `answer_with_grounding(query, …)` → `/answer`  
- [ ] LWC: search/chat panel with streaming and **citations drawer**. fileciteturn0file1

## 11) Guardrails & policies
- [ ] **Bedrock Guardrails**: require citations; PII boundaries; jailbreak filters.  
- [ ] Prompt policy: “answer only from allowed citations; otherwise provide a helpful no‑answer.” fileciteturn0file0

## 12) Observability & cost
- [ ] CloudWatch metrics: retrieval latency, generate latency, precision@k (from eval jobs), refusal rate.  
- [ ] Tracing: X‑Ray for Lambdas/Steps; OpenSearch audit logs.  
- [ ] Cost tagging & budgets; dashboards in QuickSight. fileciteturn0file0

## 13) Acceptance tests (POC exit)
- [ ] **Precision@5** ≥ target on 50 curated questions.  
- [ ] **Zero authZ leaks** (automated red‑team queries).  
- [ ] **p95** end‑to‑end under UX budget with streaming.  
- [ ] **Citations** on every paragraph; “explain this answer” shows top‑K with scores. fileciteturn0file1

## 14) Runbooks (starter)
- [ ] **Index freshness**: AppFlow backlog alarms; manual re‑sync steps.  
- [ ] **Cold‑start spikes**: verify provisioned concurrency; warmers.  
- [ ] **OpenSearch health**: shard/collection alarms; slow‑query log review.  
- [ ] **AuthZ drift**: nightly sample compare (SFDC “can view?” vs. index filter). fileciteturn0file1

## 15) Teardown (POC)
- [ ] Delete stacks in reverse dependency order; purge S3 prefixes; revoke PrivateLink.  
- [ ] Export cost & usage report for the pilot. fileciteturn0file0

**Sources:** Internal drafts “Ascendix BI for Salesforce” and “AgentForce + Search Backend For Salesforce.” fileciteturn0file0 fileciteturn0file1
