# Shared Multi-Tenant Compute Plane Proposal

*Last updated: 2026-03-21*

## Scope

This document proposes a simplified target architecture for packaging the Ascendix Salesforce search experience as:

- Salesforce-native UI and admin surfaces per customer
- a shared AWS compute plane across customers
- a tenant-isolated external retrieval index
- minimal or no customer business-data storage in AWS

This is a forward-looking proposal, not the current production architecture.

## Executive Summary

The core recommendation is to use an external retrieval model that is better suited to agentic search UX than Salesforce-native live-query approaches, while limiting or streamlining tenant-specific AWS infrastructure.

In this design:

- Salesforce remains the system of record
- each customer gets a dedicated partition in an external vector/search index
- AWS runs shared stateless query and indexing services
- AWS stores only minimal control-plane metadata, not durable customer record payloads
- Agentforce or the LWC can surface the experience, but AWS remains the retrieval and answer-shaping brain

This design aims to deliver several advantages:

- denormalized retrieval instead of live SOQL planning
- predictable prompt/tool contracts
- lower latency than model-generated live query execution
- lower cost than repeatedly asking an agent to reason over raw Salesforce data

## Why This Direction

The main architectural gain does not come from "using AWS" in the abstract. It comes from moving work out of query time and into a curated retrieval plane:

- denormalization happens before retrieval
- the model queries a constrained search interface instead of the whole Salesforce schema
- ambiguity guards and grouped-query constraints live in deterministic tool code
- answer rendering and citation behavior are shaped against a stable retrieval contract

By contrast, fully Salesforce-native agent patterns that generate SOQL or run live queries tend to be:

- slower
- more expensive
- harder to make consistent
- harder to tune for multi-object search UX

The recommended simplification is therefore:

- keep the external retrieval index and query plane
- simplify AWS into shared multi-tenant compute
- avoid per-tenant AWS stacks and avoid durable AWS copies of customer records

## Goals

- Keep the current retrieval quality and UX advantages over live SOQL agent execution.
- Make AWS tenant-agnostic at the application layer.
- Avoid durable storage of customer business records in AWS.
- Support one isolated index partition per tenant.
- Keep the customer-facing package centered in Salesforce: LWC, Apex, optional Agentforce integration.
- Preserve room for deterministic backend guardrails rather than relying on prompt-only controls.

## Non-Goals

- Do not eliminate all external infrastructure. The retrieval index remains external to Salesforce.
- Do not move core retrieval planning fully into Agentforce.
- Do not promise zero customer data transit through AWS. Query and indexing payloads still pass through AWS for processing.
- Do not assume Salesforce sharing/FLS parity is solved automatically by namespace isolation alone.
- Do not treat this proposal as a full production-control framework for compliance certifications.

## Proposed Architecture

### High-Level Model

Each customer gets:

- the managed-package Salesforce components
- a tenant identity, typically the Salesforce org ID
- a dedicated partition in the external retrieval index
- tenant-level config and feature flags

Shared across all customers:

- one API entrypoint
- one shared query service
- one shared indexing service
- one shared codebase and deployment pipeline
- one shared tenant registry and secrets/control plane

The AWS layer becomes a compute-only service that:

- receives signed requests
- resolves the tenant and namespace server-side
- performs retrieval, ranking, guardrails, and answer shaping
- writes to or reads from the tenant namespace
- returns the result

It does not keep a durable copy of the customer record corpus.

### High-Level Topology

```text
Customer Salesforce Org
  ├─ LWC and/or Agentforce surface
  ├─ Apex callout layer
  ├─ async denorm/index publisher
  └─ custom metadata / package config

Shared AWS Compute Plane
  ├─ API Gateway or equivalent shared API
  ├─ tenant auth / resolver layer
  ├─ query Lambda
  ├─ index Lambda
  ├─ minimal tenant registry
  └─ logs / metrics / secrets

External Retrieval Index
  ├─ namespace: sf_<tenant_1_org_id>
  ├─ namespace: sf_<tenant_2_org_id>
  └─ namespace: sf_<tenant_n_org_id>
```

### Division Of Responsibility

Salesforce:

- owns source records
- owns customer-facing UI
- owns package configuration and onboarding UX
- can optionally build denormalized payloads before publishing
- authenticates to the shared AWS API

AWS:

- owns query orchestration
- owns embeddings generation if semantic retrieval remains required
- owns external-index upsert/delete/query calls
- owns deterministic retrieval constraints and answer-shaping logic
- owns tenant resolution and enforcement

External retrieval index:

- stores the tenant-isolated search corpus
- stores vectors and filterable metadata
- does not replace tenant/auth logic

### Request Contracts

The shared compute plane should expose only a small number of runtime contracts.

### 1. `POST /v1/index`

Purpose:

- upsert or delete a single denormalized document in the tenant namespace

Request shape:

```json
{
  "operation": "upsert",
  "record": {
    "tenant_record_id": "Property:006xx000001ABC",
    "record_id": "006xx000001ABC",
    "object_type": "Property",
    "title": "One Main Place",
    "source_url": "https://tenant.my.salesforce.com/lightning/r/ascendix__Property__c/006xx000001ABC/view",
    "text": "Property Name: One Main Place\nCity: Dallas\nClass: A\nSubmarket: CBD\nOwner: ACME Holdings",
    "metadata": {
      "city": "Dallas",
      "state": "TX",
      "property_class": "A",
      "market": "Dallas-Fort Worth",
      "submarket": "CBD"
    },
    "relationships": {
      "owner_account": {
        "id": "001xx000009ZZZ",
        "name": "ACME Holdings"
      }
    },
    "acl": {
      "visibility": "private",
      "principal_ids": ["005xx0000001AAA", "00Gxx0000002BBB"]
    },
    "version": "2026-03-21T12:00:00Z"
  }
}
```

Response shape:

```json
{
  "status": "ok",
  "operation": "upsert",
  "tenant_record_id": "Property:006xx000001ABC"
}
```

### 2. `POST /v1/query`

Purpose:

- run the shared retrieval and answer-generation flow against the tenant namespace

Request shape:

```json
{
  "query": "Show me Class A office buildings in Dallas over 100,000 SF",
  "conversation_id": "conv_123",
  "record_context": {
    "record_id": "001xx000009ZZZ",
    "object_type": "Account"
  },
  "user_context": {
    "user_id": "005xx0000001AAA",
    "locale": "en-US",
    "timezone": "America/Chicago"
  },
  "response_mode": "answer_with_citations"
}
```

Response shape:

```json
{
  "answer": "I found 7 Class A office properties in Dallas over 100,000 SF. The strongest matches are One Main Place and Trammell Center.",
  "citations": [
    {
      "record_id": "006xx000001ABC",
      "object_type": "Property",
      "title": "One Main Place",
      "url": "https://tenant.my.salesforce.com/lightning/r/ascendix__Property__c/006xx000001ABC/view"
    }
  ],
  "clarifications": []
}
```

### 3. Optional `POST /v1/config/refresh`

Purpose:

- refresh prompt/object-scope configuration for a tenant without redeploying the shared AWS codebase

This is optional for the first cut. It becomes more important if configuration drift and admin-driven scope changes must be applied without release work.

### Query Brain Placement

The shared query service should retain the logic that most clearly differentiates this approach from slower Salesforce-native agent experiences.

Keep in AWS:

- the query prompt and field/object guidance
- `search_records`
- `aggregate_records`
- grouped-ranking guards
- ambiguity handling
- citation assembly
- response shaping for the LWC or Agentforce surface

Do not move those behaviors wholesale into Agentforce prompt templates if the goal is to preserve the current UX and cost profile. Agentforce can be a shell or surface, but the constrained retrieval contract should remain server-side.

### Indexing Model

There are two viable indexing variants.

### Variant A: Thin AWS Indexer

Salesforce builds the full denormalized payload and sends it to `/v1/index`.

Pros:

- AWS stays closer to stateless compute only
- less customer business logic duplicated in AWS
- easier to explain that AWS is not the system of record

Cons:

- denormalization and parent-fanout logic move into Apex/async Salesforce code
- large backfills and reindex workflows become more awkward

### Variant B: Hybrid AWS Indexer

Salesforce sends a normalized event or source snapshot. AWS performs the final document shaping before embedding and upsert.

Pros:

- denormalization logic stays in one backend service
- easier to keep document shape consistent

Cons:

- more business-data processing responsibility lives in AWS
- security review must account for a somewhat heavier compute role

Recommendation:

- start with Variant A if the Salesforce package can realistically construct the denormalized payloads
- fall back to Variant B only where Apex limits make Variant A impractical

### Minimal Tenant Registry

Even with a no-business-data objective, the shared compute plane still needs a small control-plane store.

Per tenant, track:

- `tenant_id`
- `salesforce_org_id`
- `index_namespace`
- `index_api_key_secret_ref` or shared-account routing
- `config_version`
- `auth_mode`
- `acl_mode`
- `status`

Example:

```json
{
  "tenant_id": "tenant_acme",
  "salesforce_org_id": "00Dxx0000001234EAA",
  "index_namespace": "sf_00Dxx0000001234EAA",
  "index_api_key_secret_ref": "secrets/index/acme",
  "config_version": "2026-03-21.1",
  "auth_mode": "jwt",
  "acl_mode": "record_visibility",
  "status": "active"
}
```

This registry is operational metadata, not customer business content.

### Tenant Isolation Model

Tenant isolation must not depend on trusting a browser- or LWC-supplied namespace.

The recommended pattern is:

1. Salesforce Apex signs the request or obtains a short-lived JWT.
2. AWS verifies the token.
3. AWS derives `tenant_id` and `salesforce_org_id` from verified claims.
4. AWS resolves the namespace from the tenant registry.
5. AWS forces all read/write operations into that namespace.

Expected auth claims:

- `org_id`
- `user_id`
- `scope`
- `iat`
- `exp`

This should be combined with:

- least-privilege IAM
- per-tenant secret references or a shared-account namespace policy
- request validation and schema enforcement

## Public Reference Points

The following public examples are relevant because they show that serious products already externalize Salesforce-adjacent retrieval into purpose-built search infrastructure rather than relying only on live agent-generated SOQL.

### Notion

Publicly documented facts:

- Notion has an official Salesforce AI Connector for accounts, leads, opportunities, and contacts: <https://www.notion.com/help/salesforce-ai-connector>
- Notion states that its AI connectors create and store embeddings in a vector database hosted by Turbopuffer: <https://www.notion.com/help/notion-ai-connectors>
- Notion's Salesforce connector page says Salesforce objects and records are stored as embeddings using a vector/search system such as Turbopuffer: <https://www.notion.com/help/salesforce-ai-connector>
- Notion states that member login enables advanced SOQL for more complex queries, implying that indexed retrieval is complemented by some live-query capability rather than replaced by SOQL alone: <https://www.notion.com/help/salesforce-ai-connector>
- Turbopuffer publicly identifies Notion as a customer and describes Notion as using Turbopuffer for Q&A, research, and third-party data search: <https://turbopuffer.com/customers/notion>

Documented limits in Notion's public Salesforce connector docs:

- field-level permissions are "not supported yet"
- Salesforce retention rules are not currently supported
- new Salesforce content is generally searchable within about an hour
- initial connector setup and ingestion can take up to 36 to 72 hours

Relevant architectural inference:

- Notion appears to use a pattern close to the one proposed here: externalized indexed retrieval over third-party SaaS content, permissions mapping, and an optional live-query path for cases the indexed layer does not fully answer

### Coveo

Publicly documented facts:

- Coveo provides a Salesforce integration and documents a Salesforce source that indexes Salesforce objects and fields into Coveo: <https://docs.coveo.com/en/1052/coveo-for-salesforce/add-a-salesforce-source>
- Coveo states that the Salesforce security model is replicated in the Coveo organization by indexing content together with permissions: <https://docs.coveo.com/en/1052/coveo-for-salesforce/add-a-salesforce-source>
- Coveo documents several important authorization and security limitations, including unsupported Salesforce restriction rules and unsupported field-level security in the index: <https://docs.coveo.com/en/1052/coveo-for-salesforce/add-a-salesforce-source>

Relevant architectural inference:

- Coveo is another public example of the same broad product move: use Salesforce as the system of record, externalize search into a dedicated search plane, and treat authorization mapping as a first-class design concern rather than relying on live object queries alone

### Why These Examples Matter

These references do not prove that the exact architecture proposed in this document is the right one. They do show that:

- externalized search over Salesforce data is a credible market pattern
- permission-mapping limitations are normal and must be disclosed explicitly
- search UX often benefits from indexed retrieval even when some live-query capability remains available
- security review is usually more about authorization fidelity and data-flow clarity than about the mere existence of a shared compute layer

For this proposal, the Notion and Coveo examples strengthen the case that the main product decision should be:

- keep the external retrieval plane
- simplify the compute plane
- be explicit about the authorization model and its limitations

## Security Review Viability

### Short Answer

This architecture is viable for security review, but only if the security model is explicit and enforced in code rather than implied by "stateless Lambda" language.

It is not inherently disqualifying that data transits AWS. The harder review questions will usually be:

- how tenant isolation is guaranteed
- how Salesforce sharing/FLS semantics are preserved or consciously scoped
- what data is logged
- what exactly is stored in the external retrieval index
- whether any customer business data is durably retained in AWS
- how secrets and tenant credentials are managed

If those controls are designed up front, this proposal should be reviewable and defensible. If they are deferred, the architecture will attract justified pushback.

### Why Reviewers May Accept It

This design has several security-positive properties:

- AWS is not the system of record.
- The business corpus is not durably copied into S3 or DynamoDB by default.
- Tenant scope is explicit through namespace isolation and signed tenant resolution.
- The runtime surface can be kept small: one query API, one index API, one tenant registry.
- Secrets handling can be centralized.
- Logging can be constrained to metadata, request IDs, and operational status rather than payload bodies.

That is often easier to defend than a more sprawling multi-service architecture with buckets full of replay artifacts and ad hoc tenant-specific stacks.

### Main Security Review Concerns

#### 1. Multi-Tenant Isolation

Reviewers will want proof that:

- tenant A cannot read tenant B's namespace
- tenant A cannot write into tenant B's namespace
- tenant identity is derived from verified credentials, not request body fields

This needs automated tests and explicit threat-model coverage.

#### 2. Sharing And FLS Parity

A dedicated namespace per tenant is not sufficient if user-level permissions must be honored.

The review question will be:

- does the system enforce org-level isolation only, or user-level record access too?

If user-level access matters, the design needs one of:

- ACL metadata indexed with each document and enforced at query time
- a constrained, well-documented partitioning model
- a product decision that the index is only for data already authorized to the entire tenant audience

This is likely the hardest review topic.

#### 3. Secrets And Customer-Owned Index Credentials

If each tenant owns a separate retrieval-index account or API key, the secrets model must answer:

- where tenant keys live
- who can rotate them
- how they are accessed by the shared runtime
- how blast radius is limited

Operationally, a shared retrieval-index account with one namespace per tenant is easier to secure and operate than tenant-owned keys, but that may have commercial or contractual downsides.

#### 4. Logging And Data Retention

The shared compute plane must not accidentally turn CloudWatch logs into a data lake.

Controls should include:

- log redaction by default
- no full request/response body logging in production
- explicit retention windows
- separate debug modes that require elevated operator action

#### 5. Prompt Injection And Result Safety

Because this remains an agentic retrieval flow, reviewers may ask how prompt injection or malicious record content is contained.

The main answers are:

- tool access is constrained to server-defined contracts
- retrieval logic is not replaced by free-form model browsing
- ambiguous grouped queries are gated by backend logic
- output can be filtered or normalized before return

This does not eliminate LLM risk, but it gives a more defensible control story than unrestricted live-query agents.

### Controls Required For A Credible Security Review

The following should be considered mandatory for production review.

#### Identity And Access

- signed server-to-server auth from Salesforce to AWS
- tenant resolution from verified claims only
- no trusted namespace or tenant ID from client payloads
- least-privilege IAM for query and index paths
- separate runtime roles for query and indexing if practical

#### Data Protection

- TLS in transit end to end
- encrypted secrets at rest
- no durable AWS storage of customer business payloads by default
- explicit retention policy for logs and metrics
- payload-size and schema validation on all ingest/query requests

#### Tenant Isolation

- namespace enforcement server-side
- integration tests for cross-tenant isolation failure cases
- per-tenant rate limits or abuse controls
- clear production runbook for tenant disable / credential revoke

#### Application Safety

- deterministic backend validation for tool inputs
- strict allowlists for filterable fields and operations
- response sanitization for citations and generated URLs
- safe handling for malformed or hostile denormalized text payloads

#### Governance

- documented data-flow diagram
- documented data-retention statement
- documented incident-response path
- documented key rotation process
- security review of package-installed Apex callout/auth logic

## Security Review Assessment

Current viability assessment:

- tenant-level review: high, if signed tenant resolution and namespace enforcement are implemented cleanly
- enterprise product-security review: medium to high, if logging, secrets, and retention controls are tightened
- strict per-user data-visibility review: medium until ACL/FLS enforcement is designed and validated
- "no customer data leaves Salesforce" policy review: low, because this architecture explicitly externalizes a search copy into an external retrieval index

So the key point is:

- this architecture can pass a serious review
- it cannot pass a review that forbids externalized data on principle
- its hardest security problem is authorization fidelity, not Lambda itself

## Open Design Decisions

- Will the first version enforce tenant-only isolation or per-user ACLs too?
- Will Salesforce build denormalized payloads, or will AWS do the final shaping?
- Will the retrieval index use a shared-account namespace-per-tenant model or a tenant-owned account-per-customer model?
- How much configuration is pushed from Salesforce versus managed in the shared AWS control plane?
- Is Agentforce a primary surface, or an optional shell over the shared query service?

## Recommended Initial Cut

For the first implementation, the recommended architecture is:

- one shared query Lambda
- one shared index Lambda
- one shared API
- one isolated index namespace per tenant
- a minimal tenant registry in AWS
- signed Apex-to-AWS authentication
- no S3 document audit trail by default
- no per-tenant AWS stacks
- AWS-owned retrieval orchestration and answer shaping
- explicit roadmap follow-up for ACL/FLS parity if per-user authorization is a requirement

This keeps the strongest parts of the current system while materially reducing AWS complexity and tenant-specific operational burden.

## Next Steps

Before implementing this architecture, the next design work should produce:

1. a tenant-auth and namespace-enforcement spec
2. an indexing ownership decision: Salesforce denorm versus AWS denorm
3. a security model decision for ACL/FLS parity
4. an onboarding/bootstrap flow for new tenants
5. a migration plan from the current single-tenant architecture to the shared compute-plane model
