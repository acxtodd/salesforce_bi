# AscendixIQ Salesforce Connector

AI-powered search over Salesforce CRE data. Users ask natural language questions in a Salesforce Lightning Web Component and get streaming answers with source citations. Part of the **AscendixIQ** platform.

## Architecture

```
Salesforce Org                          AWS (us-west-2)
┌──────────────────┐                   ┌──────────────────────────────────────┐
│  CRE Data        │  Bulk API (init)  │                                      │
│  (Properties,    │ ─────────────────>│  Bulk Loader                         │
│   Leases,        │  CDC (ongoing)    │    Denormalize (per YAML config)     │
│   Availabilities,│ ─────────────────>│    Embed (Bedrock Titan v2)          │
│   Sales, Deals)  │                   │    Upsert (SearchBackend protocol)   │
│                  │                   │         │                            │
│                  │                   │         ▼                            │
│  LWC Search UI   │  NL Query        │  Turbopuffer (namespace per org)     │
│  ┌────────────┐  │ ─────────────────>│    Dense vectors + BM25 + filters   │
│  │ Ask a      │  │                   │    Cold on S3 (~$0.02/GB)           │
│  │ question.. │  │  Streaming Answer │         │                            │
│  │            │  │ <─────────────────│  Query Lambda                       │
│  └────────────┘  │  + Citations      │    Claude Sonnet 4 (tool-use)       │
│                  │                   │    ├── search_records (parallel)     │
│                  │                   │    ├── aggregate_records             │
│                  │                   │    └── live_salesforce_query (SOQL)  │
│                  │                   │         │                            │
│                  │                   │    Streaming SSE + citations         │
└──────────────────┘                   └──────────────────────────────────────┘
```

## How It Works

1. **Denorm config generator** harvests Salesforce metadata (compact layouts, search layouts, page layouts, list views) to auto-determine which fields to embed and which parent fields to denormalize onto child records.
2. **Bulk loader** exports records via Salesforce Bulk API 2.0, denormalizes per config, embeds via Bedrock Titan v2, and upserts to Turbopuffer.
3. **CDC sync** keeps the index fresh — the current target path is Salesforce CDC -> AppFlow -> S3 -> EventBridge -> `cdc_sync` Lambda, which fetches the full record, denormalizes, embeds, and upserts changed records.
4. **Query Lambda** receives a natural language question, gives Claude three tools (`search_records`, `aggregate_records`, `live_salesforce_query`), and streams the synthesized answer with citations.

The LLM decides the query strategy — single search, parallel cross-object searches, aggregations, or live SOQL — by choosing which tools to call. No custom planner or intent router needed.

## Current CDC Strategy

- Reuse the existing `AppFlow -> S3 -> EventBridge` transport and the new `lambda/cdc_sync` processor for the Turbopuffer-based connector.
- Treat the older `/ingest` endpoint, `AISearchBatchExport`, and Step Functions ingestion chain as legacy or fallback infrastructure, not the primary path for new connector work.
- Phase 2 code tasks merged (`1f7dd3f`, PR #4, 2026-03-16):
  - `2.4.1` AppFlow props wired via deploy-time CfnDynamicReference
  - `2.4.2` CDC object list aligned to 5-object POC scope (JWT_BEARER auth)
  - `2.5.1` /query Lambda with SSE streaming + API key auth deployed
- Remaining deploy/validate tasks:
  - `2.4.3` deploy AppFlow flows, `2.4.4` validate real CDC delivery
  - `2.5.2` deploy /query Lambda, `2.5.3` validate LWC observability

## Supported Objects

| POC (Phase 0-3) | v1 (Phase 5+) |
|-----------------|----------------|
| Property, Lease, Availability, Deal, Sale | + Account, Contact |

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Search backend | Turbopuffer (behind `SearchBackend` ABC) | Object-storage-native, namespace-per-tenant, cold orgs cost pennies |
| Query orchestration | Claude tool-use | Replaces custom planner/decomposer/intent router with ~3 tool definitions |
| Cross-object queries | Denormalized documents | Parent fields inlined on children at write time; no graph traversal needed |
| Field selection | Metadata-driven (auto-generated YAML) | Salesforce compact/search/page layouts tell us what's important |
| Permissions | Per-user OAuth (POC) | Notion's pattern — honest about enforcement scope |
| Multi-tenant | Namespace-per-org | Inactive orgs on S3 at ~$0.02/GB |

Full spec: [`docs/specs/salesforce-connector-spec.md`](docs/specs/salesforce-connector-spec.md)

## Project Structure

```
├── lib/                            # Search backend
│   ├── search_backend.py           # Vendor-agnostic ABC (search, aggregate, upsert, delete, warm)
│   └── turbopuffer_backend.py      # Turbopuffer implementation (only file that imports tpuf SDK)
├── scripts/
│   ├── generate_denorm_config.py   # Metadata-driven field selection → YAML config
│   └── task_manager.py             # Task tracking CLI (manages tasks.json)
├── lambda/                         # Lambda handlers (Python 3.11)
│   ├── retrieve/                   # [legacy] Query processing — being replaced by Query Lambda
│   ├── answer/                     # [legacy] Streaming answers — being replaced by Query Lambda
│   ├── cdc_sync/                   # Current CDC processor for Turbopuffer sync
│   ├── cdc_processor/              # [legacy] CDC event parsing for old ingestion workflow
│   ├── transform/                  # Record transformation (adapting for denormalization)
│   ├── embed/                      # Bedrock Titan v2 embeddings (reusing)
│   ├── schema_discovery/           # [legacy] Nightly Describe API — replaced by denorm config generator
│   └── ...                         # Other legacy Lambdas (graph, derived views, etc.)
├── salesforce/                     # Salesforce metadata & components
│   ├── classes/                    # Apex (AscendixAISearchController — adapting)
│   ├── lwc/                        # ascendixAiSearch LWC (adapting API contract)
│   ├── customMetadata/             # IndexConfiguration__mdt, AI_Search_Config__mdt
│   ├── namedCredentials/           # AWS API credentials
│   └── ...                         # Flows, permission sets, objects, agentforce tools
├── tests/
│   ├── test_search_backend.py      # 28 tests (ABC, filters, integration)
│   └── test_denorm_generator.py    # 51 tests (scoring, parents, YAML output)
├── docs/
│   ├── specs/
│   │   └── salesforce-connector-spec.md  # Unified product & design spec
│   ├── architecture/               # Legacy system design docs
│   ├── guides/                     # Onboarding, deployment
│   └── handoffs/                   # Session handoff documents
├── tasks.json                      # Phase-based task tracking (use task_manager.py)
├── TASK_TRACKING.md                # Task tracking guide
└── denorm_config.yaml              # Generated denormalization config (after running generator)
```

## Getting Started

### Prerequisites

- Python 3.11+
- AWS CLI configured (`aws sts get-caller-identity`)
- Turbopuffer API key (stored in `.env` as `TURBOPUFFER_API_KEY`)
- Salesforce sandbox with Ascendix CRE package

### Quick Start

```bash
# 1. Set up environment
cp .env.example .env
# Edit .env with your Turbopuffer API key and Salesforce credentials

# 2. Generate denormalization config from Salesforce metadata
python3 scripts/generate_denorm_config.py \
  --objects ascendix__Property__c ascendix__Lease__c ascendix__Availability__c \
  --output denorm_config.yaml

# Or use mock mode without Salesforce credentials:
python3 scripts/generate_denorm_config.py --mock --output denorm_config.yaml

# 3. Check current task progress
python3 scripts/task_manager.py phases
python3 scripts/task_manager.py next
```

### Run Tests

```bash
# Unit tests (no credentials needed)
python3 -m pytest tests/ -v

# Including live Turbopuffer integration test
TURBOPUFFER_API_KEY=your-key python3 -m pytest tests/ -v
```

## Cost

| Scenario | Old System | New Target |
|----------|-----------|------------|
| 1 org (dev) | $500-1,000/mo | $115-180/mo |
| 10 orgs (3 active) | $500-1,000/mo | $300-500/mo |
| 100 orgs (10 active) | Not viable | $600-1,200/mo |
| Marginal cost per cold org | ~$50-100/mo | ~$1-5/mo |

## Migration Status

The project is migrating from a graph-enhanced RAG system (Bedrock KB + OpenSearch + DynamoDB graph + 6 CDK stacks) to a Turbopuffer + LLM tool-use architecture. The old system still exists in the repo and runs in parallel until the validation gate (Phase 3) passes.

```bash
python3 scripts/task_manager.py phases
```

| Phase | Name | Status |
|-------|------|--------|
| 0 | Foundations | Completed |
| 1 | Intelligence Layer | In progress (`1.3` live validation still open) |
| 2 | Salesforce Integration | In progress (code merged; `2.4.3`/`2.4.4` deploy + `2.5.2`/`2.5.3` validate remain) |
| 3 | Validation Gate | Pending |

See [`TASK_TRACKING.md`](TASK_TRACKING.md) for task management commands and workflow.

## Documentation

- [`docs/specs/salesforce-connector-spec.md`](docs/specs/salesforce-connector-spec.md) — Unified product & design spec (start here)
- [`TASK_TRACKING.md`](TASK_TRACKING.md) — Task tracking guide
- `docs/guides/PROJECT_PRIMER.md` — Legacy system orientation
- `docs/architecture/` — Legacy system design docs
