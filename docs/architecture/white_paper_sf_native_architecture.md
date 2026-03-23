# AscendixIQ AI Search: Architecture White Paper

## From AWS-Hosted to Salesforce-Native — A Technical Feasibility Analysis

**Version:** 1.0
**Date:** March 23, 2026
**Author:** Todd Terry / AscendixIQ Engineering
**Status:** Draft for internal review

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture: AWS-Hosted](#2-current-architecture-aws-hosted)
   - 2.1 System Overview
   - 2.2 Data Model and Denormalization
   - 2.3 Embedding Pipeline
   - 2.4 Vector Storage (Turbopuffer)
   - 2.5 Query Orchestration (Tool-Use Loop)
   - 2.6 Change Data Capture Pipeline
   - 2.7 Incremental Poll Sync
   - 2.8 Salesforce Integration Layer
   - 2.9 Cost Structure
3. [Motivation for a Salesforce-Native Architecture](#3-motivation-for-a-salesforce-native-architecture)
4. [Component-by-Component Migration Analysis](#4-component-by-component-migration-analysis)
   - 4.1 Embeddings: Bedrock Titan V2 → OpenAI
   - 4.2 Vector Storage: Options Within and Outside Salesforce
   - 4.3 LLM Inference: Bedrock Claude → Direct Claude API
   - 4.4 CDC Pipeline: AppFlow → Apex CDC Triggers
   - 4.5 Query Orchestration: Lambda → Apex
   - 4.6 Streaming UX: SSE → Alternatives
5. [Proposed Salesforce-Native Architecture](#5-proposed-salesforce-native-architecture)
   - 5.1 Pure Apex Architecture
   - 5.2 Heroku AppLink Hybrid Architecture
   - 5.3 Agentforce / Data Cloud Architecture
6. [Governor Limits and Hard Constraints](#6-governor-limits-and-hard-constraints)
7. [Cost Comparison](#7-cost-comparison)
8. [Risk Analysis and Trade-offs](#8-risk-analysis-and-trade-offs)
9. [Recommendation](#9-recommendation)
10. [Appendices](#10-appendices)
    - A. API Key Setup for OpenAI
    - B. Apex CDC Trigger Example
    - C. Denorm Config Schema Reference
    - D. Field Mapping Tables

---

## 1. Executive Summary

AscendixIQ AI Search is a production AI-powered natural-language search system for Salesforce CRE (Commercial Real Estate) data. Users ask questions in a Lightning Web Component and receive streaming answers with citations, clarification options, and write-back proposals. The current architecture runs on AWS (Lambda, Bedrock, Turbopuffer, AppFlow) with a Salesforce LWC + Apex frontend.

This white paper evaluates three approaches to moving the system to a Salesforce-native architecture with zero or minimal AWS dependency:

| Approach | AWS Dependency | Streaming UX | Complexity | Feasibility |
|---|---|---|---|---|
| **Pure Apex** | Zero | Lost (spinner) | Lowest | Feasible with UX tradeoff |
| **Heroku AppLink Hybrid** | Zero AWS (Heroku is SF ecosystem) | Preserved | Medium | Recommended |
| **Agentforce + Data Cloud** | Zero | Platform-native | Highest | Feasible, different paradigm |

**Key finding:** A fully functional Salesforce-native implementation is feasible. The single hardest constraint is Apex's inability to stream HTTP responses, which eliminates the real-time token-by-token UX. Every other component (embeddings, vector search, LLM tool-use, CDC sync) can be ported to Apex with known patterns. The Heroku AppLink hybrid preserves streaming while staying within the Salesforce ecosystem.

---

## 2. Current Architecture: AWS-Hosted

### 2.1 System Overview

```text
Salesforce Org                              AWS (us-west-2, account 382211616288)
┌──────────────────────┐                   ┌──────────────────────────────────────────────┐
│                      │                   │                                              │
│  Salesforce CRE Data │  Bulk API seed    │  Bulk Load Pipeline                          │
│  (11 object types,   │ ────────────────> │   scripts/bulk_load.py                       │
│   ~24,500 records)   │                   │   ├─ Fetch via Salesforce REST/Bulk API      │
│                      │                   │   ├─ Denormalize (flatten + parent joins)     │
│                      │  CDC via AppFlow  │   ├─ Embed (Bedrock Titan V2, 1024 dims)     │
│                      │ ────────────────> │   └─ Upsert to Turbopuffer                   │
│                      │                   │                                              │
│  LWC Search UI       │  /query via Apex  │  Query Lambda (lambda/query)                 │
│  (ascendixAiSearch)  │ ────────────────> │   ├─ Claude tool-use loop (Bedrock Converse) │
│                      │                   │   ├─ search_records → Turbopuffer hybrid      │
│                      │  SSE streaming    │   ├─ aggregate_records → Turbopuffer group_by │
│                      │ <──────────────── │   ├─ propose_edit → write-back proposals      │
│                      │                   │   └─ SSE token streaming back to LWC          │
│                      │                   │                                              │
│  Apex Controller     │                   │  CDC Sync Lambda (lambda/cdc_sync)            │
│  (callout to API GW) │                   │   ├─ EventBridge trigger from S3              │
│                      │                   │   ├─ Re-denormalize changed records           │
│                      │                   │   ├─ Re-embed via Bedrock                     │
│                      │                   │   └─ Upsert to Turbopuffer                   │
│                      │                   │                                              │
│                      │                   │  Poll Sync Lambda (lambda/poll_sync)          │
│                      │                   │   ├─ SSM watermark tracking                  │
│                      │                   │   └─ Incremental sync for non-CDC objects     │
│                      │                   │                                              │
│                      │                   │  Supporting Lambdas                           │
│                      │                   │   ├─ lambda/action (write-back execution)     │
│                      │                   │   ├─ lambda/authz (authorization sidecar)     │
│                      │                   │   ├─ lambda/schema_api (metadata endpoint)    │
│                      │                   │   ├─ lambda/schema_discovery (describe cache) │
│                      │                   │   └─ lambda/schema_drift_checker              │
└──────────────────────┘                   └──────────────────────────────────────────────┘
                                                            │
                                                            ▼
                                            ┌──────────────────────────┐
                                            │  Turbopuffer (Serverless) │
                                            │  ├─ Namespace per org     │
                                            │  ├─ BM25 full-text search │
                                            │  ├─ ANN vector search     │
                                            │  ├─ Hybrid via multi_query│
                                            │  └─ Aggregate + group_by  │
                                            └──────────────────────────┘
```

**Active AWS services:** Lambda (7 functions), API Gateway, S3 (CDC + audit buckets), EventBridge, AppFlow, Secrets Manager, SSM Parameter Store, DynamoDB (4 tables), CloudWatch, Bedrock (Titan V2 + Claude), KMS, VPC/Security Groups.

**Active Salesforce components:** LWC (`ascendixAiSearch`), Apex controller (`AscendixAISearchController`), Named Credentials, Remote Site Settings, Custom Metadata Types.

### 2.2 Data Model and Denormalization

The system does not index raw Salesforce records. Instead, it **denormalizes** records into flat documents that embed parent relationship data directly into each child record. This eliminates the need for JOINs at query time.

**Configuration file:** `denorm_config.yaml`

**Object scope (11 objects, 3 sync paths):**

| Object | Sync Path | Record Count | Parent Relationships |
|---|---|---|---|
| Property | CDC | 2,470 | 9 lookups (Market, Complex, Developer, Owner, etc.) |
| Lease | CDC | 483 | 8 lookups (Property master-detail, Tenant, Brokers) |
| Availability | CDC | 527 | 7 lookups (Property master-detail, Market, Brokers) |
| Account | CDC | 4,756 | 0 (root object) |
| Contact | CDC | 6,625 | 1 lookup (Account) |
| Deal | Poll sync | ~2,391 | Multiple (Property, Contacts, Account) |
| Sale | Poll sync | ~small | Multiple |
| Inquiry | Poll sync | ~2,340 | Multiple |
| Listing | Poll sync | ~1,763 | Multiple |
| Preference | Poll sync | ~3,209 | Multiple |
| Task | Poll sync | ~varies | Multiple (WhoId, WhatId) |

**Denormalization strategy per relationship type:**

- **Master-detail (e.g., Property → Lease):** Full parent denormalization. The Lease document includes Property Name, City, State, Class, SubType, TotalBuildingArea. This enables queries like "leases in Dallas" without joining to Property.

- **Lookup (e.g., Contact → Account):** Compact parent set. The Contact document includes Account Name, Type, Phone, Website, Industry, AnnualRevenue. Enough for inline display and filtering.

- **Contact lookups:** Include contact-specific reachability fields: Phone, Email, MobilePhone. Enables "find the listing broker's phone for this property" without a second query.

**Per-object configuration example (Property):**

```yaml
ascendix__Property__c:
  embed_fields:         # Concatenated into searchable text, embedded as vector
    - Name
    - ascendix__City__c
    - ascendix__State__c
    - ascendix__PropertyClass__c
    - ascendix__PropertySubType__c
    - ascendix__Description__c
    - ascendix__Street__c
    - ascendix__Building_Status__c

  metadata_fields:      # Stored as filterable/sortable metadata, not embedded
    - ascendix__TotalBuildingArea__c    # float
    - ascendix__YearBuilt__c           # string (some are ranges)
    - ascendix__Floors__c              # float
    - ascendix__PostalCode__c          # string
    - ascendix__County__c              # string
    - ascendix__Occupancy__c           # float (percentage)
    - ascendix__LandArea__c            # float
    - ascendix__ConstructionType__c    # picklist
    - ascendix__Tenancy__c             # picklist
    - ascendix__Geolocation__Latitude__s   # float
    - ascendix__Geolocation__Longitude__s  # float

  parents:              # Relationships to denormalize
    ascendix__Market__c:
      fields: [Name]
    ascendix__Complex__c:
      fields: [Name]
    ascendix__OwnerLandlordAccount__c:
      fields: [Name, Type, Phone, Website, Industry, AnnualRevenue]
    ascendix__DeveloperContact__c:
      fields: [Name, Phone, Email, MobilePhone]
    # ... 9 total parent lookups
```

**Document construction pipeline (`lib/denormalize.py`):**

1. **SOQL generation** (`build_soql()`): Constructs `SELECT Id, LastModifiedDate, [embed_fields], [metadata_fields], [Parent.Field for each parent]` query.
2. **Flatten** (`flatten()`): Separates direct fields from parent fields. Handles null parents (common — data sparsity: Market fill rate is 6.6%, SubMarket 1.1%).
3. **Build text** (`build_text()`): Concatenates embed_fields + parent name fields into a single searchable string. Example: `"Greenville Tower Dallas Texas Class A Office 2-story building in Richardson submarket"`.
4. **Schema declaration**: Pre-declares 50+ numeric fields as float to prevent Turbopuffer type inference conflicts (int vs float). Text field uses `word_v3` tokenizer with English language, no stemming, no stopword removal.

### 2.3 Embedding Pipeline

**Model:** Amazon Bedrock Titan Embed Text V2 (`amazon.titan-embed-text-v2:0`)
**Dimensions:** 1024
**Cost:** $0.02 per 1M input tokens (~$0.06 for full 15K document corpus)

**Embedding flow:**
1. Build text string from embed_fields + parent names (~50-200 tokens per document)
2. Call Bedrock `InvokeModel` with `{"inputText": text, "dimensions": 1024, "normalize": true}`
3. Returns 1024-dimensional float vector

**Batch processing:** `bulk_load.py` embeds in batches of 25 with 4-way concurrency, 5 max retry attempts per batch. Processes ~6,625 Contact records in ~15 minutes including Salesforce fetch, denormalization, embedding, audit write, and Turbopuffer upsert.

### 2.4 Vector Storage (Turbopuffer)

**Service:** Turbopuffer (serverless vector database)
**Namespace isolation:** `org_{salesforce_org_id}` — one namespace per Salesforce org for multi-tenant isolation
**Distance metric:** Cosine distance

**Key capabilities used:**

| Capability | Implementation | Notes |
|---|---|---|
| **BM25 full-text search** | `word_v3` tokenizer, English, no stemming | Used when user query is text-heavy |
| **ANN vector search** | Cosine distance, 1024 dims | Used when semantic similarity matters |
| **Hybrid search** | `multi_query` with RRF | Turbopuffer does not support `Sum(BM25, ANN)` in one query; system sends two queries and fuses via Reciprocal Rank Fusion |
| **Metadata filtering** | Tuple-based filter syntax | `("And", (("city", "Eq", "Dallas"), ("total_sf", "Gte", 10000)))` |
| **Aggregate + group_by** | Server-side aggregation | Count, sum, average with grouping — used for leaderboard/breakdown queries |
| **Upsert semantics** | ID-based upsert | Same ID = update, new ID = insert |

**Filter translation (`lib/turbopuffer_backend.py`):**
The system accepts user-friendly dict filters with operator suffixes:
```python
{"city": "Dallas", "total_sf_gte": 10000, "property_type_in": ["Office", "Industrial"]}
```
And translates them to Turbopuffer's tuple format:
```python
("And", (("city", "Eq", "Dallas"), ("total_sf", "Gte", 10000), ("property_type", "In", ["Office", "Industrial"])))
```

Supported operators: `Eq` (default), `Gte`, `Lte`, `Gt`, `Lt`, `In`, `Ne`.

### 2.5 Query Orchestration (Tool-Use Loop)

The query path is a **Claude tool-use loop**, not a custom planner or RAG chain. Claude decides which tools to call, interprets results, and composes the answer.

**File:** `lib/query_handler.py`

**Flow:**
```
User question
    ↓
Build message history (prior turns, max 10)
    ↓
┌─────────── Bedrock Converse API call ──────────────┐
│  System prompt + tools + messages                   │
│  Model: Claude Haiku 4.5 (production default)       │
│  or Claude Sonnet 4 (configurable)                  │
└─────────────────────────────────────────────────────┘
    ↓
stopReason == "tool_use"?
    ├─ Yes → dispatch tool → append result → loop back ↑
    └─ No (end_turn) → extract answer, citations, clarifications
    ↓
QueryResult {
  answer, citations, tool_calls_made, turns,
  tools_used, search_result_count, write_proposal,
  tool_call_log, turn_durations, clarification_options
}
```

**Available tools:**

1. **`search_records`** — Vector/hybrid search against Turbopuffer
   - Parameters: `object_type` (enum from config), `text_query`, `filters` (dict), `top_k` (1-50)
   - Returns: list of matching records with all indexed fields
   - Used for: "Find Class A offices in Dallas over 50,000 SF"

2. **`aggregate_records`** — Server-side aggregation with optional grouping
   - Parameters: `object_type`, `filters`, `aggregate` (count/sum/avg), `aggregate_field`, `group_by`, `sort_order`, `top_n`
   - Returns: grouped results with counts/sums/averages
   - Used for: "How many leases expire this quarter by property class?"

3. **`propose_edit`** — Structured write-back proposal for existing records
   - Parameters: `object_type` (Account/Contact/Task), `record_id`, `record_name`, `summary`, `fields` (array of {apiName, proposedValue})
   - Returns: structured proposal consumed by LWC diff/edit flow
   - Used for: "Update Todd Terry's phone to 214-669-8974"

**Semantic alias system (`lib/tool_dispatch.py`):**
The agent uses user-friendly field names that are translated to indexed field names. Example aliases:
- Property: `total_sf` → `totalbuildingarea`, `year_built` → `yearbuilt`, `owner` → `ownerlandlord_name`
- Lease: `leased_sf` → `size`, `rate_psf` → `leaserateperuom`, `start_date` → `termcommencementdate`
- Availability: `available_sf` → `availablearea`, `asking_price` → `askingprice`

**Clarification extraction:**
When Claude's response contains ambiguous ranking or classification questions, the system extracts them as clickable options:
- Pattern markers: `[CLARIFY:label|query]`
- Conversational offers converted: "Would you like me to show deals by size?" → clickable button
- Delivered as `clarification_options` in the QueryResult

### 2.6 Change Data Capture Pipeline

**Primary CDC path (5 objects):**
```
Salesforce CDC Event
    ↓
AppFlow (per-object flow, event-triggered)
    ↓
S3 CDC Bucket (cdc/{sobjectName}/, JSON, 7-day lifecycle)
    ↓
EventBridge Rule (S3 PutObject notification)
    ↓
Lambda: cdc_sync/index.py
    ├─ Parse CDC event (ChangeEventHeader: entityName, changeType, recordIds)
    ├─ Map entity name via CDC_ENTITY_MAP (handles both ChangeEvent and SObject names)
    ├─ Fetch current record from Salesforce (SOQL via denorm config)
    ├─ Denormalize (flatten + parent joins)
    ├─ Embed via Bedrock Titan V2
    ├─ Upsert to Turbopuffer namespace
    └─ Write audit artifacts to S3
```

**CDC Entity Map (handles two naming conventions):**
```python
CDC_ENTITY_MAP = {
    # ChangeEvent channel names (what Salesforce publishes)
    "ascendix__Property__ChangeEvent": "ascendix__Property__c",
    "AccountChangeEvent": "Account",
    "ContactChangeEvent": "Contact",
    # SObject names (what AppFlow uses as entityName)
    "ascendix__Property__c": "ascendix__Property__c",
    "Account": "Account",
    "Contact": "Contact",
}
```

**Input adapter handles two event shapes:**
- Flat (CDK input transformer): `{"bucket": "...", "key": "..."}`
- Raw EventBridge: `{"detail": {"bucket": {"name": "..."}, "object": {"key": "..."}}}`

**Module-level caching:** The Lambda caches denorm config, Salesforce client, Bedrock client, Turbopuffer backend, and relationship maps at module level. On warm starts, these are reused without re-initialization.

**Current deployment status:** The CDC sync Lambda, EventBridge rule, and S3 bucket are deployed. The **AppFlow connector profile and flows are NOT yet deployed** — they require three CDK context values at deploy time (`salesforceInstanceUrl`, `salesforceSecretArn`, `salesforceJwtToken`). The prerequisites (SSM parameter, Secrets Manager secret) exist. See task 4.18.

### 2.7 Incremental Poll Sync

**For non-CDC objects (6 objects):** Deal, Sale, Inquiry, Listing, Preference, Task

**File:** `lambda/poll_sync/index.py`

**Mechanism:**
1. Read `LastModifiedDate` watermark from SSM Parameter Store (`/salesforce-ai-search/poll-watermark/{object}`)
2. Query Salesforce: `SELECT ... FROM {object} WHERE LastModifiedDate > {watermark} ORDER BY LastModifiedDate ASC LIMIT 200`
3. Denormalize, embed, upsert (same pipeline as CDC sync)
4. Update watermark to latest `LastModifiedDate` processed
5. Repeat until no more records or Lambda timeout safety margin (60s remaining)

**Constants:**
- Batch size: 200 records per SOQL page
- Embed batch: 25 texts at a time
- Upsert batch: 100 documents at a time
- Timeout safety: Stop if < 60s remaining in Lambda execution

### 2.8 Salesforce Integration Layer

**LWC Component:** `ascendixAiSearch`
- Textarea input + model selector dropdown + Search button
- SSE streaming display (token-by-token answer rendering)
- Rich answer formatting: tables, ranked lists, markdown
- Citation panel with record links
- Clarification pill buttons
- **Write-back flow:** Diff view modal (Field | Current Value | Proposed Value) → `lightning-record-edit-form` modal → standard SF save path
- Record-page context awareness (when placed on a record page, includes record ID/name/type)
- Conversation history (compact thread of prior exchanges)

**Apex Controller:** `AscendixAISearchController`
- `@AuraEnabled` methods for query, action, schema operations
- `callQueryEndpoint()`: HTTP callout to API Gateway `/query`, streams SSE response
- `previewWriteProposal()`: Validates proposed edits against Salesforce describe metadata, returns enriched field data with current values, labels, and data types
- `callActionEndpoint()`: HTTP callout to `/action` for write-back execution

**Named Credentials:** Used for API Gateway authentication
**Remote Site Settings:** Allowlisted API Gateway endpoint

### 2.9 Cost Structure

Based on the per-tenant cost model (`docs/architecture/per_tenant_cost_model.md`):

**Small CRE Brokerage (15K docs, 50 queries/day, 5K CDC events/month):**

| Component | Monthly Cost | % of Total |
|---|---|---|
| LLM inference (Haiku 4.5) | $16.95 | 73% |
| Turbopuffer storage + queries | ~$64 (minimum floor) | — |
| Embeddings (Titan V2) | $0.04 | <1% |
| Lambda compute | $0.27 | 1% |
| API Gateway | $0.01 | <1% |
| AppFlow | ~$2-5 | ~2% |
| S3 + EventBridge | ~$1-2 | ~1% |
| **Total AWS** | **~$85-90/month** | — |

**Key insight:** LLM inference dominates at 95-98% of variable AWS cost. Embeddings, compute, and data pipeline are rounding errors. The cost structure is driven by query volume × tokens per query, not by data volume or sync frequency.

---

## 3. Motivation for a Salesforce-Native Architecture

| Driver | Explanation |
|---|---|
| **Operational simplicity** | Current system spans 7+ AWS services. Each requires monitoring, IAM policies, deployment pipelines, and incident response. A Salesforce-native system reduces the operational surface to Apex + 2-3 external API calls. |
| **Deployment alignment** | Salesforce admins and developers work in Setup, not AWS Console. A native architecture means one deployment target, one permission model, one monitoring surface. |
| **Licensing efficiency** | Apex runtime, CDC triggers, Platform Events, and Queueable jobs are included in standard Salesforce licenses. Eliminating Lambda/API Gateway/AppFlow removes per-invocation AWS charges. |
| **Portability** | An ISV packaging the solution as a managed package can distribute to any Salesforce org without requiring customers to provision AWS accounts. |
| **Security posture** | Data stays within the Salesforce trust boundary for processing. Only embeddings and query orchestration require external calls — and those can be restricted via Named Credentials with IP allowlisting. |

---

## 4. Component-by-Component Migration Analysis

### 4.1 Embeddings: Bedrock Titan V2 → OpenAI

**Current:** Amazon Bedrock Titan Embed Text V2 (`amazon.titan-embed-text-v2:0`), 1024 dimensions, $0.02/1M tokens.

**Proposed replacement:** OpenAI `text-embedding-3-small`

| Attribute | Titan V2 | OpenAI `3-small` | OpenAI `3-large` |
|---|---|---|---|
| Dimensions | 1024 | 1,536 (native), shortable to 1024 | 3,072 (native), shortable to 1024 |
| MTEB score | ~57.5 | ~62.3 | ~64.6 |
| Price (per 1M tokens) | $0.02 | $0.02 | $0.13 |
| Matryoshka shortening | No | Yes | Yes |
| Batch support | No (one text per call) | Yes (up to 2,048 inputs per request) |
| Callable from Apex | Via Bedrock SDK only | Yes, simple HTTP POST |

**API details:**

```
POST https://api.openai.com/v1/embeddings
Headers:
  Authorization: Bearer {API_KEY}
  Content-Type: application/json
Body:
  {
    "model": "text-embedding-3-small",
    "input": "Greenville Tower Dallas Texas Class A Office",
    "dimensions": 1024
  }
Response:
  {
    "data": [{"embedding": [0.0023, -0.0091, ...], "index": 0}],
    "usage": {"prompt_tokens": 8, "total_tokens": 8}
  }
```

**Batch embedding** (recommended for bulk operations): Send up to 2,048 texts in the `input` array. Single API call, single response. Dramatically reduces callout count compared to one-at-a-time Bedrock calls.

**Apex integration pattern:**
```apex
HttpRequest req = new HttpRequest();
req.setEndpoint('callout:OpenAI_API/v1/embeddings');  // Named Credential
req.setMethod('POST');
req.setHeader('Content-Type', 'application/json');
req.setBody(JSON.serialize(new Map<String, Object>{
    'model' => 'text-embedding-3-small',
    'input' => textToEmbed,
    'dimensions' => 1024
}));
HttpResponse res = new Http().send(req);
// Parse res.getBody() for embedding vector
```

**Migration impact:** Drop-in replacement. Same dimension count (1024), same cost, better quality. The embedding vectors are NOT backward-compatible — a full re-embed of all documents is required when switching models. At ~15K documents and ~200 tokens average, re-embedding costs ~$0.06 total.

**Feasibility: Fully feasible. Recommended regardless of architecture choice.**

### 4.2 Vector Storage: Options Within and Outside Salesforce

#### Option A: Keep Turbopuffer (called from Apex instead of Lambda)

Turbopuffer's REST API is callable from Apex via standard HTTP callout. No architecture change needed for the vector store itself — only the caller changes.

```apex
// Apex callout to Turbopuffer
HttpRequest req = new HttpRequest();
req.setEndpoint('https://gcp-us-central1.turbopuffer.com/v2/namespaces/' + namespace + '/query');
req.setMethod('POST');
req.setHeader('Authorization', 'Bearer ' + apiKey);
req.setHeader('Content-Type', 'application/json');
req.setBody(queryPayload);
HttpResponse res = new Http().send(req);
```

**Hybrid search from Apex:** Would require two sequential callouts (BM25 query + ANN query) followed by Apex-side RRF fusion. This is the same pattern the Lambda currently uses, just in Apex instead of Python.

**Cost:** ~$64/month minimum (unchanged).

#### Option B: Salesforce Data Cloud Vector Database

Data Cloud (now "Data 360") includes a native vector database built on Hyper engine + Milvus.

**Capabilities:**
- Native `vector_search()` SQL function
- Callable from Apex via `ConnectApi.CdpQuery.querySql()`
- Supports hybrid (keyword + vector) search
- Handles chunking and embedding generation with pluggable models
- Automatic index management

**Architecture implications:**
- Salesforce CRM records must be mapped into Data Cloud Data Model Objects (DMOs)
- Search indexes created over DMOs
- Querying via ConnectApi, not SOQL

**Licensing:** Requires Data Cloud license. Credit-based consumption pricing. Salesforce-native data ingestion is free; AI operations consume credits. Pricing is opaque — typically bundled with Enterprise/Unlimited editions or sold as add-on at $50K-150K+/year depending on org size and usage.

**Verdict:** Technically capable but introduces significant licensing cost and architectural rework. Not recommended for the POC unless Data Cloud is already licensed.

#### Option C: Pinecone (called from Apex)

| Metric | Pinecone Serverless | Turbopuffer (Current) |
|---|---|---|
| Minimum spend | $0 (Starter free tier) | ~$64/month |
| Read cost | $8.25/1M read units | ~$0.002/query at small scale |
| Write cost | $2/1M write units | Included in storage |
| Storage | $0.33/GB/month | ~$0.02/GB (object storage) + SSD cache |
| Free tier | Yes (Starter: 2GB, 100 namespaces) | No |
| Hybrid search | Sparse-dense vectors | BM25 + ANN (native multi_query) |

Pinecone's free tier is attractive for POC/experimentation. At 15K documents × 1024 dims × 4 bytes = ~60 MB — well within Starter's 2GB limit.

**Recommendation for the SF-native POC:** Start with Pinecone Starter (free) for development, with Turbopuffer as the production target. The vector DB abstraction (`SearchBackend` protocol in `lib/search_backend.py`) already supports swappable backends.

#### Option D: Custom Objects / Big Objects (Manual Vector Storage)

**Not feasible.** Salesforce has no native vector similarity operation in SOQL. Brute-force cosine similarity in Apex heap is limited to ~750 vectors (6 MB sync heap ÷ ~8 KB per 1024-dim vector). With 15K+ documents, this is unworkable. **Do not pursue this option.**

### 4.3 LLM Inference: Bedrock Claude → Direct Claude API

**Current:** Claude via Bedrock Converse API (supports Haiku 4.5 and Sonnet 4).

**Proposed:** Direct Anthropic Messages API.

| Attribute | Bedrock Converse | Direct Claude API |
|---|---|---|
| Endpoint | Regional Bedrock endpoint | `https://api.anthropic.com/v1/messages` |
| Auth | IAM (SigV4) | API key (`x-api-key` header) |
| Streaming | Yes (response stream) | Yes (`"stream": true`) |
| Tool use | Yes (Converse API) | Yes (Messages API) |
| Pricing | Bedrock pricing (slightly higher) | Direct pricing |
| Callable from Apex | Complex (SigV4 signing) | Simple (API key header) |

**Apex integration:**
```apex
HttpRequest req = new HttpRequest();
req.setEndpoint('callout:Claude_API/v1/messages');  // Named Credential
req.setMethod('POST');
req.setHeader('Content-Type', 'application/json');
req.setHeader('anthropic-version', '2023-06-01');
req.setBody(JSON.serialize(new Map<String, Object>{
    'model' => 'claude-haiku-4-5-20251001',
    'max_tokens' => 4096,
    'system' => systemPrompt,
    'tools' => toolDefinitions,
    'messages' => conversationMessages
}));
// NOTE: stream must be false — Apex cannot process SSE
HttpResponse res = new Http().send(req);
```

**Critical constraint:** Apex `HttpResponse` returns the complete response body. There is no mechanism to incrementally read a streaming response. Claude API calls from Apex must use `"stream": false`, which means:
- The full response (including all tool-use reasoning) is returned at once
- Response time for complex queries: 5-30 seconds of blocking wait
- Response size must fit within 6 MB (sync) or 12 MB (async Queueable)

**Token pricing (direct API, as of March 2026):**

| Model | Input (per 1M tokens) | Output (per 1M tokens) |
|---|---|---|
| Claude Haiku 4.5 | $0.80 | $4.00 |
| Claude Sonnet 4 | $3.00 | $15.00 |
| Claude Opus 4 | $15.00 | $75.00 |

### 4.4 CDC Pipeline: AppFlow → Apex CDC Triggers

This is the **most compelling migration target**. The current AppFlow → S3 → EventBridge → Lambda chain is 4 services and a significant source of operational complexity. Apex CDC triggers reduce this to zero external services.

**Current pipeline (AWS):**
```
Salesforce CDC Event → AppFlow → S3 → EventBridge → Lambda (cdc_sync)
   4 AWS services, ~20 IAM permissions, CDK infrastructure
```

**Proposed pipeline (Apex):**
```
Salesforce CDC Event → Apex CDC Trigger → Queueable (embed + upsert)
   0 AWS services, standard Apex, no infrastructure to manage
```

**Apex CDC trigger pattern:**
```apex
trigger ContactCDC on ContactChangeEvent (after insert) {
    List<Id> changedRecordIds = new List<Id>();

    for (ContactChangeEvent event : Trigger.new) {
        EventBus.ChangeEventHeader header = event.ChangeEventHeader;

        if (header.changetype == 'UPDATE' || header.changetype == 'CREATE') {
            changedRecordIds.addAll(header.getRecordIds());
        }

        if (header.changetype == 'DELETE') {
            // Queue deletion from vector store
            System.enqueueJob(new VectorDeleteJob(header.getRecordIds()));
        }
    }

    if (!changedRecordIds.isEmpty()) {
        // Queue re-embed + upsert
        System.enqueueJob(new VectorUpsertJob('Contact', changedRecordIds));
    }
}
```

**Queueable chain for re-embedding:**
```apex
public class VectorUpsertJob implements Queueable, Database.AllowsCallouts {
    private String objectType;
    private List<Id> recordIds;

    public void execute(QueueableContext context) {
        // 1. Query current record data (SOQL — denormalize inline)
        // 2. Build embed text (same logic as Python denormalize.py)
        // 3. Call OpenAI embeddings API (HTTP callout)
        // 4. Call Turbopuffer/Pinecone upsert API (HTTP callout)

        // If more records to process, chain another Queueable
        if (remainingRecords.size() > 0) {
            System.enqueueJob(new VectorUpsertJob(objectType, remainingRecords));
        }
    }
}
```

**Limits to respect:**
- Max 50 Queueable jobs enqueued per transaction
- Each Queueable gets fresh governor limits (100 callouts, 120s timeout, 12 MB heap)
- CDC events delivered in batches — a single trigger invocation may contain multiple record changes
- Platform Event daily delivery limit: 25K-250K depending on edition

**Advantages over current AppFlow pipeline:**
- No S3 bucket, no EventBridge rule, no AppFlow connector profile
- No JWT token minting for AppFlow auth
- No CDK infrastructure to deploy and maintain
- Simpler debugging — all code is Apex, viewable in Setup
- ISV-packageable — triggers deploy with the managed package

**Feasibility: Fully feasible. Recommended as the first migration target regardless of overall architecture choice.**

### 4.5 Query Orchestration: Lambda → Apex

The query Lambda (`lambda/query/index.py`) orchestrates the Claude tool-use loop, dispatches search/aggregate calls, and streams the response via SSE. Porting this to Apex is feasible but requires navigating governor limits.

**Current Lambda flow:**
```python
# Unbounded loop — runs until Claude says "end_turn" or max turns reached
while turns < MAX_TURNS:
    response = bedrock.converse(messages, tools, system_prompt)
    if response.stop_reason == "tool_use":
        # Dispatch tool, append result, continue loop
    elif response.stop_reason == "end_turn":
        # Extract answer, break
```

**Equivalent Apex pattern:**
```apex
// Apex version — must respect 100 callout limit and 120s cumulative timeout
Integer turns = 0;
while (turns < MAX_TURNS) {
    HttpResponse claudeResponse = callClaudeAPI(messages, tools, systemPrompt);
    Map<String, Object> parsed = parseClaudeResponse(claudeResponse);
    String stopReason = (String) parsed.get('stop_reason');

    if (stopReason == 'tool_use') {
        // Each tool dispatch = 1-2 callouts (embed query + vector search)
        Map<String, Object> toolResult = dispatchTool(parsed);
        messages.add(toolResult);
        turns++;
    } else {
        answer = extractAnswer(parsed);
        break;
    }
}
// Return complete answer to LWC (no streaming)
return answer;
```

**Callout budget analysis per query:**

| Step | Callouts | Time (typical) |
|---|---|---|
| Embed user query (OpenAI) | 1 | 200ms |
| Vector search (Turbopuffer) | 1-2 (BM25 + ANN for hybrid) | 100-300ms |
| Claude API call #1 | 1 | 5-15s |
| Tool dispatch (if Claude requests search) | 1-2 | 200-500ms |
| Claude API call #2 | 1 | 5-15s |
| Tool dispatch #2 (if needed) | 1-2 | 200-500ms |
| Claude API call #3 (final answer) | 1 | 5-10s |
| **Total** | **7-10** | **15-45s** |

With 100 callouts and 120s cumulative timeout, most queries fit comfortably. Complex multi-turn queries (4+ tool calls) approach the limits.

**Continuation pattern (for long-running queries):**
For queries that may exceed synchronous limits, use the Apex Continuation pattern:
- LWC calls Apex with `@AuraEnabled(continuation=true)`
- Apex initiates up to 3 parallel callouts
- Salesforce holds the connection, returns to the callback method when responses arrive
- Each Continuation gets fresh limits (but 1 MB response cap per callout)

**Feasibility: Feasible for most queries. Complex multi-tool queries may timeout. Continuation pattern provides headroom for longer operations.**

### 4.6 Streaming UX: SSE → Alternatives

**This is the single hardest constraint.**

The current system streams Claude's response token-by-token via SSE to the LWC. Users see the answer building in real-time. Apex HTTP callouts are strictly synchronous — there is no mechanism to incrementally read a streaming response.

**Alternative approaches:**

#### Option 1: Accept "spinner then full response" (simplest)

Replace streaming with a loading spinner. The full answer appears at once after 5-30 seconds.

- **Pros:** Zero additional infrastructure. Simple Apex implementation.
- **Cons:** Perceived latency increases dramatically. Users may think the system is frozen for complex queries. Modern AI UX norms expect streaming.
- **Mitigation:** Show a progress indicator with estimated wait time. Use Claude's `thinking` output to show "Searching records..." → "Analyzing 47 results..." status updates (requires polling).

#### Option 2: Platform Event polling (medium complexity)

1. LWC fires Apex callout (async via Queueable)
2. Queueable calls Claude API, receives complete response
3. Queueable publishes Platform Events with answer chunks
4. LWC subscribes to Platform Events via `empApi` and renders chunks as they arrive

- **Pros:** Simulates streaming. Uses native Salesforce eventing.
- **Cons:** Platform Events have delivery latency (100-500ms per event). Not truly real-time — more like "chunked delivery." Daily Platform Event limits apply (25K-250K/day). Adds significant code complexity.

#### Option 3: Heroku AppLink streaming proxy (preserves current UX)

1. LWC calls Heroku endpoint directly (CORS configured)
2. Heroku app (Python/Node.js) calls Claude API with `stream: true`
3. Heroku streams SSE back to LWC in real-time
4. Heroku calls vector DB as needed during tool-use loop

- **Pros:** Identical UX to current system. No governor limits on Heroku. Full Python/Node.js flexibility.
- **Cons:** Not "zero external compute" — Heroku is a separate service. Adds Heroku operational surface (though minimal for a single dyno).
- **Cost:** Heroku Basic dyno: $7/month. Eco dyno: $5/month.

**Recommendation:** Option 3 (Heroku AppLink) for production. Option 1 for quick POC validation.

---

## 5. Proposed Salesforce-Native Architecture

### 5.1 Pure Apex Architecture (Zero External Compute)

```text
Salesforce Org
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  LWC (ascendixAiSearch)                                          │
│    ↓                                                             │
│  Apex Controller (AscendixAISearchController)                    │
│    ├── @AuraEnabled queryAI(question, context, history)          │
│    │     1. Build embed text from question                       │
│    │     2. Callout → OpenAI embeddings API (Named Credential)   │
│    │     3. Callout → Turbopuffer query (Named Credential)       │
│    │     4. Callout → Claude API with tool-use (Named Credential)│
│    │     5. If tool_use → repeat 2-4 (loop)                     │
│    │     6. Return complete answer + citations to LWC            │
│    │                                                             │
│    ├── previewWriteProposal(proposalJson)  [existing]            │
│    └── saveRecord() via lightning-record-edit-form  [existing]   │
│                                                                  │
│  CDC Triggers (replacing AppFlow → Lambda pipeline)              │
│    ├── ContactCDC on ContactChangeEvent                          │
│    ├── AccountCDC on AccountChangeEvent                          │
│    ├── PropertyCDC on ascendix__Property__ChangeEvent             │
│    ├── LeaseCDC on ascendix__Lease__ChangeEvent                   │
│    └── AvailabilityCDC on ascendix__Availability__ChangeEvent     │
│          ↓                                                       │
│    Queueable: VectorUpsertJob                                    │
│      1. Query changed record (SOQL with parent joins)            │
│      2. Denormalize (flatten + build text)                       │
│      3. Callout → OpenAI embeddings API                          │
│      4. Callout → Turbopuffer upsert API                         │
│      5. Chain next batch if needed                               │
│                                                                  │
│  Bulk Load (Batchable Apex)                                      │
│    ├── BatchVectorLoad implements Database.Batchable              │
│    │     start(): SOQL query all records for object              │
│    │     execute(): denormalize + embed + upsert (batch of 200)  │
│    │     finish(): log summary                                   │
│    └── Invocable from Flow or Developer Console                  │
│                                                                  │
│  Named Credentials                                               │
│    ├── OpenAI_API (api.openai.com, API key auth)                 │
│    ├── Claude_API (api.anthropic.com, API key auth)              │
│    └── Turbopuffer_API (gcp-us-central1.turbopuffer.com, Bearer) │
│                                                                  │
│  Custom Metadata / Custom Settings                               │
│    ├── AI_Search_Config__mdt (model, dimensions, namespace)      │
│    └── Denorm_Config__mdt (per-object field configuration)       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘

External APIs (no compute, just API calls):
  ┌─────────────────────┐  ┌─────────────────────┐  ┌────────────────────┐
  │  OpenAI API         │  │  Anthropic Claude    │  │  Turbopuffer       │
  │  (embeddings)       │  │  (LLM tool-use)      │  │  (vector storage)  │
  └─────────────────────┘  └─────────────────────┘  └────────────────────┘
```

**What's preserved from current system:**
- Same denormalization strategy and document model
- Same tool-use loop pattern (search_records, aggregate_records, propose_edit)
- Same LWC UI (diff modal, edit form, citations, clarification pills)
- Same write-back flow via `lightning-record-edit-form`
- Same namespace-per-org multi-tenant isolation

**What changes:**
- No Lambda, API Gateway, AppFlow, EventBridge, S3 CDC bucket, Secrets Manager, SSM
- Query orchestration moves from Python to Apex
- Embeddings move from Bedrock Titan V2 to OpenAI
- LLM calls move from Bedrock Converse to direct Claude API
- CDC sync moves from Lambda to Apex triggers + Queueables
- Bulk load moves from Python script to Batchable Apex
- **No SSE streaming** — answer appears complete after processing

### 5.2 Heroku AppLink Hybrid Architecture (Recommended)

```text
Salesforce Org                          Heroku (AppLink)
┌─────────────────────────┐            ┌──────────────────────────────┐
│                         │            │                              │
│  LWC (ascendixAiSearch) │ ─SSE───── │  Query Orchestrator          │
│    ↓                    │  stream   │  (Python/Node.js, 1 dyno)    │
│  Apex Controller        │ <──────── │    ├─ Claude tool-use loop    │
│    (for write-back,     │            │    ├─ OpenAI embeddings       │
│     schema, non-query)  │            │    ├─ Turbopuffer queries     │
│                         │            │    └─ SSE streaming to LWC    │
│  CDC Triggers [Apex]    │            │                              │
│    ↓                    │            │  (No data storage on Heroku   │
│  Queueable chain        │            │   — pure compute proxy)       │
│    ↓                    │            │                              │
│  OpenAI embed callout   │            └──────────────────────────────┘
│    ↓                    │
│  Turbopuffer upsert     │
│                         │
└─────────────────────────┘

External APIs:
  OpenAI (embeddings) — called from both Apex (CDC) and Heroku (query)
  Claude (LLM) — called from Heroku only
  Turbopuffer (vectors) — called from both Apex (CDC) and Heroku (query)
```

**Key design decisions:**
- **Query path goes through Heroku** — preserves SSE streaming, eliminates Apex callout limits for query orchestration
- **CDC sync stays in Apex** — simpler than current AppFlow pipeline, no Heroku needed for sync
- **Heroku is stateless** — no database, no persistent storage. It's a pure compute proxy.
- **Heroku AppLink** provides native Salesforce integration (Setup UI, Named Credentials, monitoring)

**Cost addition:** Heroku Basic dyno: $7/month. The query orchestrator is a single-dyno app — no scaling needed at POC volumes.

### 5.3 Agentforce + Data Cloud Architecture (Alternative)

For organizations already invested in the Salesforce AI ecosystem:

```text
Salesforce Platform
┌──────────────────────────────────────────────────────┐
│                                                      │
│  Agentforce Agent                                    │
│    ├── Topic: "CRE Search"                           │
│    ├── Actions:                                      │
│    │     ├── Search Records (Apex Invocable)         │
│    │     ├── Aggregate Records (Apex Invocable)      │
│    │     └── Propose Edit (Apex Invocable)           │
│    └── LLM: Einstein (or BYOLLM → Claude)            │
│                                                      │
│  Data Cloud                                          │
│    ├── CRM Data mapped to DMOs                       │
│    ├── Vector Search Indexes                         │
│    ├── Embedding: OpenAI via Einstein Studio          │
│    └── Search via ConnectApi.CdpQuery                │
│                                                      │
│  CDC: Automatic via Data Cloud CRM ingestion         │
│                                                      │
└──────────────────────────────────────────────────────┘
```

**Pros:** Fully platform-native. No external API calls. Salesforce handles embeddings, vector storage, and LLM inference.
**Cons:** Data Cloud license ($50K-150K+/year). Agentforce is a different paradigm from custom tool-use — less control over tool dispatch and prompt engineering. BYOLLM has fewer features than direct Claude API.

**Recommendation:** Only viable if Data Cloud is already licensed and Agentforce is an organizational commitment. For a focused CRE search product, the Pure Apex or Heroku Hybrid approaches are more cost-effective and flexible.

---

## 6. Governor Limits and Hard Constraints

### Apex Callout Limits

| Limit | Synchronous | Asynchronous (Queueable) | Continuation |
|---|---|---|---|
| **Max timeout per callout** | 120s | 120s | 120s |
| **Cumulative timeout** | 120s per transaction | 120s per transaction | N/A (new transaction on callback) |
| **Max response size** | 6 MB | 12 MB | 1 MB per callout |
| **Max callouts per transaction** | 100 | 100 | 3 per Continuation, chainable |
| **Heap size** | 6 MB | 12 MB | 6 MB |
| **CPU time** | 10,000 ms | 60,000 ms | 10,000 ms |
| **SOQL queries** | 100 | 200 | 100 |
| **DML statements** | 150 | 150 | 150 |

### Impact on Key Operations

| Operation | Callouts Needed | Time (typical) | Limit Risk |
|---|---|---|---|
| Simple query (1 search + 1 Claude call) | 4 | 8-15s | Low |
| Complex query (3 searches + 3 Claude calls) | 10-12 | 25-45s | Medium |
| Very complex query (5+ tool rounds) | 15-20 | 45-90s | High (timeout risk) |
| CDC re-embed single record | 2 | 1-3s | None |
| CDC re-embed batch (50 records) | ~52 | 30-60s | Low |
| Bulk load 200 records (Batchable) | ~204 | 120s+ | **Exceeds limit** — requires chunking |

### Mitigations

1. **Query timeout:** Set Claude `max_tokens` lower. Limit tool-use rounds to 3. Use Continuation for complex queries.
2. **Bulk load:** Use Batchable Apex with batch size 10-25 (each execute() gets fresh limits). OpenAI batch embedding (2,048 inputs per call) reduces callouts dramatically.
3. **CDC burst:** If 50 records change simultaneously, the CDC trigger enqueues a Queueable that processes in batches with chaining.

---

## 7. Cost Comparison

### Monthly Cost at Current Scale (~15K docs, 50 queries/day)

| Component | Current (AWS) | Pure Apex | Heroku Hybrid |
|---|---|---|---|
| **LLM inference** | Bedrock Claude: ~$17 | Direct Claude API: ~$15 | Direct Claude API: ~$15 |
| **Embeddings** | Bedrock Titan V2: $0.06 | OpenAI 3-small: $0.06 | OpenAI 3-small: $0.06 |
| **Vector DB** | Turbopuffer: ~$64 | Turbopuffer: ~$64 | Turbopuffer: ~$64 |
| **Compute** | Lambda + API GW: ~$5 | $0 (Apex included) | Heroku Basic: $7 |
| **CDC pipeline** | AppFlow + EB + S3: ~$5 | $0 (Apex triggers) | $0 (Apex triggers) |
| **Secrets/config** | Secrets Mgr + SSM: ~$2 | $0 (Named Creds) | $0 (Named Creds) |
| **Monitoring** | CloudWatch: ~$2 | $0 (Debug Logs) | $0 (Heroku Logs) |
| **Total** | **~$95/month** | **~$79/month** | **~$86/month** |

**Cost delta is modest.** The savings come primarily from eliminating AWS compute and pipeline services (~$14/month). The dominant cost (LLM inference + vector DB) is unchanged across all architectures.

### At Scale (~100K docs, 500 queries/day)

| Component | Current (AWS) | Pure Apex | Heroku Hybrid |
|---|---|---|---|
| **LLM inference** | ~$170 | ~$150 | ~$150 |
| **Embeddings** | $0.40 | $0.40 | $0.40 |
| **Vector DB** | ~$80 | ~$80 | ~$80 |
| **Compute** | ~$20 | $0 | $14 (Standard dyno) |
| **CDC + pipeline** | ~$15 | $0 | $0 |
| **Total** | **~$285/month** | **~$230/month** | **~$244/month** |

---

## 8. Risk Analysis and Trade-offs

### Hard Blockers (Pure Apex)

| Risk | Impact | Mitigation |
|---|---|---|
| **No SSE streaming** | UX degradation — 5-30s spinner instead of real-time tokens | Accept for POC; migrate to Heroku AppLink for production |
| **120s cumulative callout timeout** | Complex multi-turn queries may fail | Limit tool rounds; use Continuation; simplify prompts |
| **6 MB sync response limit** | Large Claude responses (many search results) may truncate | Limit `top_k`; paginate results; use async Queueable (12 MB) |

### Manageable Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Governor limits on bulk operations** | Initial data load is slower than Python script | Batchable Apex with small batch sizes; OpenAI batch embedding |
| **Platform Event daily limits** | CDC at high volume may hit caps | Monitor via Usage API; request limit increase if needed |
| **Queueable chain depth** | Long chains may be delayed under platform load | Priority queueing; batch processing; monitor queue depth |
| **OpenAI API dependency** | Outage blocks embedding + CDC sync | Cache recent embeddings; retry with backoff; health monitoring |
| **Cross-model embedding compatibility** | Switching from Titan V2 to OpenAI requires full re-embed | One-time migration cost (~$0.06); schedule during maintenance window |

### Advantages of Migration

| Benefit | Details |
|---|---|
| **Operational simplicity** | 1 deployment target (Salesforce) vs. 7+ AWS services |
| **ISV packageability** | Managed package distributable to any org — no customer AWS setup |
| **Security** | All processing within Salesforce trust boundary (except API calls via Named Credentials) |
| **Developer experience** | Apex + LWC is standard Salesforce skill set — no Python/CDK/AWS expertise needed |
| **Simpler CDC** | Apex triggers replace 4-service pipeline |

---

## 9. Recommendation

### For POC / Experimentation

**Start with Pure Apex (Architecture 5.1).**

- Fastest to implement — no Heroku setup needed
- Validates the core flow: Apex → OpenAI embed → Turbopuffer search → Claude tool-use → answer
- Accept the "spinner then full response" UX for now
- CDC triggers are a strict improvement over AppFlow — implement these first

**Implementation order:**
1. Named Credentials for OpenAI, Claude, Turbopuffer
2. Apex CDC triggers + Queueable re-embed chain (replaces AppFlow pipeline)
3. Apex query controller with tool-use loop (replaces Lambda)
4. Port denormalization logic from Python to Apex
5. Batchable Apex for initial data load

### For Production

**Migrate to Heroku AppLink Hybrid (Architecture 5.2).**

- Preserves SSE streaming UX
- Eliminates Apex callout limits for query path
- CDC stays in Apex (simpler than AppFlow)
- Single Heroku dyno: $7-14/month
- Heroku AppLink provides native Salesforce integration

### Components to Build Regardless of Architecture Choice

These components are needed in any Salesforce-native approach and can be built incrementally:

1. **Apex denormalization engine** — port `lib/denormalize.py` to Apex classes
2. **Named Credentials** — OpenAI, Claude, Turbopuffer
3. **CDC triggers** — 5 triggers + Queueable chain (replaces AppFlow)
4. **Custom Metadata configuration** — port `denorm_config.yaml` to `AI_Search_Config__mdt`
5. **Batchable bulk loader** — port `scripts/bulk_load.py` to Batchable Apex

---

## 10. Appendices

### Appendix A: API Key Setup

#### OpenAI

1. Sign up at [platform.openai.com](https://platform.openai.com)
2. Navigate to **API Keys** → **Create new secret key**
3. Note the key (shown once)
4. Create a Named Credential in Salesforce:
   - Name: `OpenAI_API`
   - URL: `https://api.openai.com`
   - Authentication: Custom Header → `Authorization: Bearer {key}`

**Models to enable:** `text-embedding-3-small` (embeddings)
**Free tier:** $5 credit for new accounts. After that, pay-as-you-go.

#### Anthropic (Claude)

1. Sign up at [console.anthropic.com](https://console.anthropic.com)
2. Navigate to **API Keys** → **Create Key**
3. Create Named Credential:
   - Name: `Claude_API`
   - URL: `https://api.anthropic.com`
   - Authentication: Custom Header → `x-api-key: {key}` and `anthropic-version: 2023-06-01`

#### Turbopuffer

1. Sign up at [turbopuffer.com](https://turbopuffer.com)
2. Get API key from dashboard
3. Create Named Credential:
   - Name: `Turbopuffer_API`
   - URL: `https://gcp-us-central1.turbopuffer.com`
   - Authentication: Custom Header → `Authorization: Bearer {key}`

### Appendix B: Apex CDC Trigger Example (Full)

```apex
/**
 * CDC trigger for Contact object changes.
 * Enqueues vector re-embedding when contacts are created, updated, or deleted.
 */
trigger ContactCDC on ContactChangeEvent (after insert) {
    List<Id> upsertIds = new List<Id>();
    List<Id> deleteIds = new List<Id>();

    for (ContactChangeEvent event : Trigger.new) {
        EventBus.ChangeEventHeader header = event.ChangeEventHeader;
        String changeType = header.changetype;
        List<String> recordIds = header.getRecordIds();

        switch on changeType {
            when 'CREATE', 'UPDATE', 'UNDELETE' {
                for (String rid : recordIds) {
                    upsertIds.add(Id.valueOf(rid));
                }
            }
            when 'DELETE' {
                for (String rid : recordIds) {
                    deleteIds.add(Id.valueOf(rid));
                }
            }
        }
    }

    if (!upsertIds.isEmpty()) {
        System.enqueueJob(new VectorUpsertJob('Contact', upsertIds));
    }
    if (!deleteIds.isEmpty()) {
        System.enqueueJob(new VectorDeleteJob('Contact', deleteIds));
    }
}
```

### Appendix C: Denorm Config Schema Reference

The `denorm_config.yaml` file drives the entire data pipeline. Each object entry specifies:

```yaml
{SObject_API_Name}:
  embed_fields:       # List of field API names → concatenated into searchable text → embedded
  metadata_fields:    # List of field API names → stored as filterable metadata (not embedded)
  parents:            # Map of relationship field → {fields: [parent field names to denormalize]}
```

**Field naming convention in Turbopuffer:** All field names are lowercased and snake_cased. Ascendix namespace prefix (`ascendix__`) and suffixes (`__c`, `__r`) are stripped. Example: `ascendix__TotalBuildingArea__c` → `totalbuildingarea`.

**Parent field naming:** `{relationship_name}_{parent_field}`. Example: Property's Developer Contact name → `developer_name`.

### Appendix D: Field Mapping Tables

#### Contact: Salesforce → Denormalized Document

| Salesforce Field | Document Field | Type | Category |
|---|---|---|---|
| `Name` | `name` | string | embed |
| `FirstName` | `firstname` | string | embed |
| `LastName` | `lastname` | string | embed |
| `Email` | `email` | string | embed |
| `Phone` | `phone` | string | embed |
| `Title` | `title` | string | embed |
| `MobilePhone` | `mobilephone` | string | metadata |
| `Department` | `department` | string | metadata |
| `MailingCity` | `mailingcity` | string | metadata |
| `MailingState` | `mailingstate` | string | metadata |
| `Account.Name` | `account_name` | string | parent (embed) |
| `Account.Type` | `account_type` | string | parent (metadata) |
| `Account.Phone` | `account_phone` | string | parent (metadata) |
| `Account.Industry` | `account_industry` | string | parent (metadata) |

#### Property: Salesforce → Denormalized Document

| Salesforce Field | Document Field | Type | Category |
|---|---|---|---|
| `Name` | `name` | string | embed |
| `ascendix__City__c` | `city` | string | embed |
| `ascendix__State__c` | `state` | string | embed |
| `ascendix__PropertyClass__c` | `propertyclass` | string | embed |
| `ascendix__PropertySubType__c` | `propertysubtype` | string | embed |
| `ascendix__Description__c` | `description` | string | embed |
| `ascendix__TotalBuildingArea__c` | `totalbuildingarea` | float | metadata |
| `ascendix__YearBuilt__c` | `yearbuilt` | string | metadata |
| `ascendix__Floors__c` | `floors` | float | metadata |
| `ascendix__Occupancy__c` | `occupancy` | float | metadata |
| `Market.Name` | `market_name` | string | parent (embed) |
| `SubMarket.Name` | `submarket_name` | string | parent (embed) |
| `OwnerLandlordAccount.Name` | `ownerlandlord_name` | string | parent (metadata) |

---

*This document is intended for internal technical evaluation. All cost figures are estimates based on published pricing as of March 2026 and actual usage patterns observed in the AscendixIQ POC environment.*
