# Salesforce AI Search

A graph-enhanced RAG (Retrieval-Augmented Generation) system that makes Salesforce CRE data searchable via natural language. Users ask questions in a Salesforce Lightning Web Component and get streaming AI-generated answers with source citations. Part of the **AscendixIQ** platform.

## How It Works

```
Salesforce Org                          AWS (us-west-2)
┌──────────────────┐     CDC / Batch    ┌──────────────────────────────────────┐
│  CRE Data        │ ──────────────────>│  API Gateway (Regional, API key)     │
│  (Properties,    │                    │         │                            │
│   Availabilities,│                    │   Step Functions Ingestion Pipeline  │
│   Leases, Deals, │                    │   Validate → Transform → Chunk      │
│   Sales, etc.)   │                    │   → Graph Build → Enrich → Embed    │
│                  │                    │   → Sync                            │
│  Schema Describe │  Nightly           │         │                            │
│  API             │ ──────────────────>│   Schema Discovery → Schema Cache   │
│                  │                    │         │                            │
│  LWC Search UI   │  NL Query         │   Bedrock KB (OpenSearch Serverless) │
│  ┌────────────┐  │ ──────────────────>│   Vector Store (Titan v2, 1024-dim)  │
│  │ Ask a      │  │                    │         │                            │
│  │ question.. │  │  Streaming Answer  │   Retrieve Lambda (planner → schema │
│  │            │  │ <──────────────────│   decomp → graph filter → derived   │
│  └────────────┘  │  + Citations       │   views → KB search)               │
│                  │                    │         │                            │
│                  │                    │   Answer Lambda (Claude, SSE stream) │
└──────────────────┘                    └──────────────────────────────────────┘
```

## Supported Salesforce Objects

| Standard | Ascendix Custom |
|----------|----------------|
| Account, Contact, Opportunity, Case, Note, Task, Event | Property, Availability, Lease, Sale, Deal |

## AWS Infrastructure

6 CDK stacks deployed to account `382211616288` in `us-west-2`:

| Stack | Resources |
|-------|-----------|
| **Network** | VPC (multi-AZ), VPC endpoints (Bedrock, AOSS, S3, DynamoDB), KMS |
| **Data** | 3 S3 buckets, 12+ DynamoDB tables (graph nodes/edges, sessions, authz cache, telemetry, schema cache, vocab cache, derived views, rate limits) |
| **Search** | OpenSearch Serverless collection (`salesforce-chunks` index), Bedrock Knowledge Base |
| **Ingestion** | Step Functions state machine, pipeline Lambdas, SQS DLQ, CDC S3 bucket, AppFlow CDC, Schema Discovery (nightly + on-demand), Schema Drift Checker |
| **Api** | API Gateway (Regional, API key auth), retrieve/answer/authz/action/schema_api Lambdas, NLB + VPC Endpoint Service for PrivateLink |
| **Monitoring** | CloudWatch dashboards, alarms, SNS topics |

### Lambda Functions (Python 3.11)

**Ingestion pipeline:** `validate` `transform` `chunking` `graph_builder` `enrich` `embed` `sync` `ingest`

**Query path:** `retrieve` (planner, schema decomposition, graph filtering, derived views, KB search) `answer` (Claude streaming with citations)

**Support:** `authz` `schema_discovery` `schema_drift_checker` `schema_api` `cdc_processor` `derived_views` `action` `index-creator`

## Data Ingestion

Three trigger sources feed the same Step Functions pipeline:

1. **CDC via AppFlow** (near real-time) - Salesforce change events → S3 → EventBridge → Step Functions
2. **Batch Export** (scheduled) - Apex `AISearchBatchExport` → `/ingest` endpoint → Step Functions
3. **Manual** - Direct `/ingest` API call

**Pipeline:** Validate → Transform → Chunk (300-500 tokens) → Graph Build (DynamoDB nodes/edges) → Enrich (sharing buckets, FLS tags, temporal status) → Embed (Bedrock Titan v2) → Sync (S3 → KB ingestion)

**Schema Discovery** runs nightly (and on-demand) via Salesforce Describe API, populating the Schema Cache with verified fields, picklist values, relationships, and relevance scores. The Schema Cache drives both query decomposition AND batch export field lists.

**Derived Views** are maintained from CDC events and nightly backfill for aggregation queries (vacancy %, lease expirations, activity counts, sales).

## Query Flow

1. **Planner** (≤500ms p95) - Entity detection, schema-aware decomposition into target object + predicates + traversal plan, entity linking via vocab cache, value normalization, temporal parsing
2. **Speculative parallel execution** - Structured planner path runs alongside a vector fallback path
3. **Graph filtering** - For cross-object queries, traverse DynamoDB graph (2-hop max) to find candidate record IDs
4. **Aggregation routing** - For aggregation intents (vacancy, expirations), query derived views first
5. **Bedrock KB search** - Hybrid vector + metadata filter search with seed IDs from graph
6. **Authorization** - AuthZ sidecar enforces sharing buckets + FLS at every hop, post-filters results
7. **Answer generation** - Claude synthesizes a streaming response with chunk-level citations

**Fallbacks:** Planner timeout/low confidence → hybrid vector search. Graph unavailable → vector-only. Derived view missing → vector + filters with gap log.

## Salesforce Side

Located in `salesforce/`:

- **Apex classes:** `AscendixAISearchController` (LWC callouts for `/answer`, `/retrieve`, `/action`), `AISearchBatchExport` (schema-driven batch ingestion), `AISearchBatchExportScheduler`, `SchemaCacheClient` (AWS Schema API client with Platform Cache), `ActionEnablementController` (Phase 2 admin)
- **LWC:** `ascendixAiSearch` — query input, streaming answer display, citations drawer with record navigation, action preview/confirm modal (Phase 2); `actionEnablementAdmin` — admin UI for agent actions
- **Named Credential:** `Ascendix_RAG_API` → API Gateway with API key auth
- **Custom Metadata:** `IndexConfiguration__mdt` (objects/fields to index, graph settings, semantic hints), `AI_Search_Config__mdt` (API connectivity)
- **Custom Objects:** `AI_Search_Export_Error__c` (export error logging), `AI_Action_Audit__c` (agent action audit trail)
- **Flows:** `Create_Opportunity_Flow`, `Update_Opportunity_Stage_Flow` (Phase 2 agent actions)
- **Permission Set:** `AI_Agent_Actions_Editor`
- **Agentforce tools:** `salesforce/agentforce/` — tool schemas for `retrieve_knowledge_tool`, `answer_with_grounding_tool`, `create_opportunity_action`, `update_opportunity_stage_action`

## Security

- **Network:** VPC with PrivateLink endpoints for Bedrock, OpenSearch, S3, DynamoDB. NLB + VPC Endpoint Service for Salesforce PrivateLink access.
- **Encryption:** KMS customer-managed keys (at rest, key rotation enabled), TLS 1.2+ (in transit)
- **Authorization:** Salesforce sharing bucket enforcement + FLS field filtering per user (cached 24h). Graph traversal enforces access at every hop.
- **API auth:** API key via Named Credential, usage plans with rate limiting
- **Streaming endpoint:** Lambda Function URL with application-level API key validation (CloudFront wrapping recommended for production)

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
├── lambda/                      # Lambda handlers (Python 3.11)
│   ├── retrieve/                # Query processing (planner, schema decomposer,
│   │                            #   graph filter, derived view manager, entity linker)
│   ├── answer/                  # Streaming answer generation (Claude + SSE)
│   ├── validate/                # Record validation
│   ├── transform/               # Record transformation
│   ├── chunking/                # Text chunking (300-500 tokens)
│   ├── graph_builder/           # DynamoDB graph node/edge creation
│   ├── enrich/                  # Metadata enrichment
│   ├── embed/                   # Bedrock Titan v2 embeddings
│   ├── sync/                    # S3/KB sync
│   ├── ingest/                  # Direct ingestion endpoint
│   ├── authz/                   # Authorization sidecar (sharing + FLS)
│   ├── schema_discovery/        # Salesforce Describe → Schema Cache
│   ├── schema_drift_checker/    # Nightly schema drift detection
│   ├── schema_api/              # /schema endpoint for Apex export
│   ├── cdc_processor/           # CDC event processing
│   ├── derived_views/           # Aggregation view maintenance
│   ├── action/                  # Phase 2 agent actions
│   ├── index-creator/           # OpenSearch index bootstrap
│   ├── layers/                  # Shared Lambda layers
│   └── common/                  # Shared utilities
├── stepfunctions/
│   └── ingestion-workflow.json  # State machine definition
├── salesforce/                  # Salesforce metadata & components
│   ├── classes/                 # Apex classes
│   ├── lwc/                     # Lightning Web Components
│   ├── agentforce/              # Agentforce tool schemas
│   ├── flows/                   # Phase 2 action flows
│   ├── customMetadata/          # IndexConfiguration, AI_Search_Config
│   ├── objects/                 # Custom objects
│   ├── namedCredentials/        # AWS API credentials
│   ├── permissionsets/          # AI Agent Actions permission set
│   ├── reports/                 # AI Agent Actions analytics
│   └── remoteSiteSettings/      # Callout allowlist
├── scripts/                     # Operational scripts (acceptance tests,
│                                #   schema discovery, performance, audits)
├── results/                     # Test & evaluation results
├── docs/                        # Architecture, deployment, design docs
│   ├── architecture/
│   ├── guides/                  # Onboarding, deployment, operator guides
│   ├── handoffs/                # Session handoff documents
│   ├── testing/                 # Acceptance test plans & results
│   ├── analysis/                # PRDs, competitive analysis
│   └── AscendixIQ_for_SFDC/    # Broader AscendixIQ context
└── test_automation/             # Automated test scripts
```

## Getting Started

### Prerequisites

- Node.js 18+, npm
- AWS CLI configured (`aws sts get-caller-identity`)
- AWS CDK CLI (`npm install -g aws-cdk`)
- Python 3.11 (for Lambda development)
- Salesforce CLI (`sf`) for Salesforce deployment

### Deploy AWS

```bash
npm install
cdk bootstrap        # first time only
npm run synth        # generate CloudFormation
npm run deploy       # deploy all 6 stacks
```

### Deploy Salesforce Components

```bash
cd salesforce
./deploy.sh          # interactive SFDX deploy (Phase 1)
./deploy-phase2.sh   # Phase 2 agent actions
```

See `docs/guides/QUICK_START.md` and `docs/NEXT_STEPS.md` for detailed deployment steps.

### Teardown

```bash
cdk destroy --all
```

> S3 buckets and DynamoDB tables use `RETAIN` removal policy and must be manually deleted.

## Performance Targets

| Metric | Target |
|--------|--------|
| Planner latency | ≤500ms p95 |
| Retrieve latency (simple) | ≤1.5s p95 |
| Retrieve latency (complex) | ≤5s p95 |
| First token latency | ≤800ms p95 |
| Empty-result rate | <8% for valid queries |
| Precision@5 | ≥75% |

## Cost

Estimated ~$500-1,000/month (dev). Key optimizations: single NAT gateway, DynamoDB on-demand billing, S3 lifecycle policies (IA @ 30d, Glacier @ 90d, expire @ 365d).

## Status

- Phase 1 (graph-enhanced search): Complete — 83% acceptance test pass rate (5/6 scenarios)
- Graph traversal (2-hop): Working — cross-object queries at ≤5s p95
- Schema auto-discovery: Operational — nightly via Describe API, 9 objects discovered
- Derived views (vacancy, leases, activities, sales): Complete
- Agent actions (Phase 2): Framework built — create/update opportunities with preview-confirm flow
- Agentforce integration: Tool schemas ready, pending confirmation token bridge
- Salesforce deployment: Pending API key configuration

## Documentation

- `docs/guides/PROJECT_PRIMER.md` — fast orientation for new contributors
- `docs/guides/onboarding.md` — detailed repo walkthrough and debugging playbooks
- `docs/handoffs/` — chronological session handoffs (read newest first)
- `docs/architecture/` — system design, ADRs, infrastructure details
- `docs/testing/` — acceptance test plans and results
- `docs/analysis/` — PRDs, competitive analysis vs. Agentforce
