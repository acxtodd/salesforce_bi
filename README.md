# Salesforce AI Search POC

A graph-enhanced RAG (Retrieval-Augmented Generation) system that makes Salesforce CRE data searchable via natural language. Users ask questions in a Salesforce Lightning Web Component and get streaming AI-generated answers with source citations.

## How It Works

```
Salesforce Org                          AWS (us-west-2)
┌──────────────────┐     CDC / Batch    ┌──────────────────────────────────────┐
│  CRE Data        │ ──────────────────>│  API Gateway (Private, VPC endpoint) │
│  (Properties,    │                    │         │                            │
│   Availabilities,│                    │   Step Functions Ingestion Pipeline  │
│   Leases, Deals, │                    │   Validate → Transform → Chunk      │
│   Sales, etc.)   │                    │   → Enrich → Embed → Sync           │
│                  │                    │         │                            │
│  LWC Search UI   │  NL Query         │   Bedrock KB (OpenSearch Serverless) │
│  ┌────────────┐  │ ──────────────────>│   Vector Store (Titan v2, 1024-dim)  │
│  │ Ask a      │  │                    │         │                            │
│  │ question.. │  │  Streaming Answer  │   Retrieve Lambda                   │
│  │            │  │ <──────────────────│   (intent → schema → graph → KB)    │
│  └────────────┘  │  + Citations       │         │                            │
│                  │                    │   Answer Lambda (Claude, SSE stream) │
└──────────────────┘                    └──────────────────────────────────────┘
```

## Supported Salesforce Objects

| Standard | Ascendix Custom |
|----------|----------------|
| Account, Contact, Opportunity, Case, Note | Property, Availability, Lease, Sale, Deal |

## AWS Infrastructure

6 CDK stacks deployed to account `382211616288` in `us-west-2`:

| Stack | Resources |
|-------|-----------|
| **Network** | VPC (multi-AZ), VPC endpoints (Bedrock, AOSS, S3, DynamoDB), KMS |
| **Data** | 4 S3 buckets, 9+ DynamoDB tables (graph nodes/edges, sessions, authz cache, telemetry, schema cache) |
| **Search** | OpenSearch Serverless collection (`salesforce-chunks` index), Bedrock Knowledge Base |
| **Ingestion** | Step Functions state machine, 6 pipeline Lambdas, SQS DLQ, CDC S3 bucket |
| **Api** | Private API Gateway, retrieve/answer/authz/action Lambdas |
| **Monitoring** | CloudWatch dashboards, alarms, SNS topics |

### Lambda Functions (16, Python 3.11)

**Ingestion pipeline:** `validate` `transform` `chunking` `enrich` `embed` `sync`

**Query path:** `retrieve` (intent classification, schema decomposition, graph filtering, KB search) `answer` (Claude streaming with citations)

**Support:** `authz` `graph_builder` `schema_discovery` `schema_drift_checker` `schema_api` `cdc_processor` `derived_views` `action`

## Data Ingestion

Three trigger sources feed the same Step Functions pipeline:

1. **CDC Platform Events** (real-time) - Salesforce change events → `cdc_processor` → Step Functions
2. **Batch Export** (scheduled) - Apex `AISearchBatchExport` → `/ingest` endpoint → Step Functions
3. **Manual** - Direct `/ingest` API call

**Pipeline:** Validate (required fields, supported object) → Transform (flatten relationships, normalize dates) → Chunk (300-500 tokens, heading retention) → Enrich (sharing buckets, FLS tags, parent metadata) → Embed (Bedrock Titan v2, batch of 25) → Sync (S3 in KB format, trigger KB ingestion)

## Query Flow

1. **Intent classification** - vector search, graph traversal, or aggregation?
2. **Schema decomposition** - map natural language terms → Salesforce fields using cached schema + vocab
3. **Graph filtering** - for cross-object queries, traverse DynamoDB graph (2-hop max) to find related record IDs
4. **Bedrock KB search** - vector search with metadata filters (object type, sharing buckets, record type, city, etc.)
5. **Answer generation** - Claude synthesizes a streaming response with chunk-level citations

## Salesforce Side

Located in `salesforce/`:

- **Apex classes:** `AscendixAISearchController` (LWC callouts), `AISearchBatchExport` (batch ingestion), scheduler
- **LWC:** `ascendixAiSearch` - query input, streaming answer display, citations drawer
- **Named Credential:** `Ascendix_RAG_API` → API Gateway via PrivateLink with API key auth
- **Custom Object:** `AI_Search_Export_Error__c` for export error logging

## Security

- **Network:** All traffic stays in VPC via PrivateLink endpoints. No public internet access.
- **Encryption:** KMS customer-managed keys (at rest), TLS 1.2+ (in transit)
- **Authorization:** Salesforce sharing bucket enforcement + FLS field filtering per user, cached 24h
- **API auth:** API key via Named Credential

## Project Structure

```
├── bin/app.ts                   # CDK app entry point
├── lib/                         # 6 CDK stack definitions
│   ├── network-stack.ts
│   ├── data-stack.ts
│   ├── search-stack.ts
│   ├── ingestion-stack.ts
│   ├── api-stack.ts
│   └── monitoring-stack.ts
├── lambda/                      # 16 Lambda handlers (Python 3.11)
│   ├── validate/
│   ├── transform/
│   ├── chunking/
│   ├── enrich/
│   ├── embed/
│   ├── sync/
│   ├── retrieve/
│   ├── answer/
│   ├── authz/
│   ├── graph_builder/
│   ├── schema_discovery/
│   ├── schema_api/
│   ├── schema_drift_checker/
│   ├── cdc_processor/
│   ├── derived_views/
│   ├── action/
│   └── common/                  # Shared utilities
├── stepfunctions/
│   └── ingestion-workflow.json  # State machine definition
├── salesforce/                  # Apex classes, LWC, Named Credentials
│   ├── classes/
│   ├── lwc/
│   └── namedCredentials/
├── docs/                        # Architecture, deployment, design docs
├── tests/
└── test_automation/
```

## Getting Started

### Prerequisites

- Node.js 18+, npm
- AWS CLI configured (`aws sts get-caller-identity`)
- AWS CDK CLI (`npm install -g aws-cdk`)
- Python 3.11 (for Lambda development)

### Deploy

```bash
npm install
cdk bootstrap        # first time only
npm run synth        # generate CloudFormation
npm run deploy       # deploy all 6 stacks
```

### Deploy Salesforce Components

```bash
cd salesforce
./deploy.sh          # interactive SFDX deploy
```

### Teardown

```bash
cdk destroy --all
```

> S3 buckets and DynamoDB tables use `RETAIN` removal policy and must be manually deleted.

## Cost

Estimated ~$500-1,000/month (dev). Key optimizations: single NAT gateway, DynamoDB on-demand billing, S3 lifecycle policies (IA @ 30d, Glacier @ 90d, expire @ 365d).

## Status

- Phase 0 (steel thread): Complete
- Graph traversal (2-hop): Working
- Schema auto-discovery: Nightly via Describe API
- Derived views for aggregations: In progress
- Agent actions (Phase 2): Planned
