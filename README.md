# AscendixIQ Salesforce Connector

AI-powered search over Salesforce CRE data. Users ask natural-language questions in a Salesforce Lightning Web Component and receive streaming answers with citations. The current connector architecture is Turbopuffer-backed retrieval plus Claude tool use, not the older Bedrock KB / OpenSearch RAG stack.

## Current Status

- Phases 0-3 are complete.
- Phase 4 `Full Database Search` is the active workstream (`22/42` tasks complete).
- Live searchable objects today: `Property`, `Lease`, `Availability`, `Account`, `Contact`.
- Expansion objects in code/config: `Deal`, `Sale`, `Inquiry`, `Listing`, `Preference`, `Task`.
- `Lead` and `ContentNote` remain deferred/config-only.
- Legacy SearchStack / retrieve / answer / Step Functions ingestion code has been removed from the active CDK app. If those AWS resources still exist in the account, they require decommission deployment and stack cleanup.

Authoritative status commands:

```bash
python3 scripts/task_manager.py phases
python3 scripts/task_manager.py next
```

## Architecture

```text
Salesforce Org                              AWS (us-west-2)
┌──────────────────┐                       ┌──────────────────────────────────────────┐
│ CRE data         │  Bulk API seed        │ Bulk load / replay / poll sync          │
│ (live +          │ ─────────────────────> │  - denormalize per YAML config          │
│ expansion objs)  │                        │  - embed with Bedrock Titan v2          │
│                  │  CDC via AppFlow       │  - upsert to Turbopuffer                │
│                  │ ─────────────────────> │                                          │
│ LWC search UI    │  /query via Apex       │ Query Lambda                             │
│                  │ ─────────────────────> │  - Claude tool use                      │
│                  │                        │  - search_records                       │
│                  │  streaming SSE         │  - aggregate_records                    │
│                  │ <───────────────────── │  - clarification options / citations    │
└──────────────────┘                       │                                          │
                                           │ Turbopuffer                              │
                                           │  - org namespace                         │
                                           │  - vector + metadata filtering           │
                                           └──────────────────────────────────────────┘
```

## Active Runtime Surfaces

Primary runtime components:

- `lambda/query` — natural-language `/query` API, SSE streaming, citations, clarification options
- `lambda/cdc_sync` — live CDC processor for the 5 CDC-managed objects
- `lambda/poll_sync` — incremental sync path for non-CDC expansion objects after bulk seed
- `lambda/config_refresh` — compiles versioned Ascendix Search runtime artifacts and advances the active pointer for safe changes
- `lambda/ingest` — preserved because Salesforce batch export still points at `/ingest`
- `lambda/schema_api` — `/schema/{object}` endpoint used by Salesforce schema cache client
- `lambda/schema_discovery` and `lambda/schema_drift_checker` — metadata discovery and drift monitoring
- `lambda/action` and `lambda/authz` — supporting Lambda surfaces used by the Salesforce integration

Active CDK stacks:

- `DataStack`
- `NetworkStack`
- `IngestionStack`
- `ApiStack`
- `MonitoringStack`

Retired from the active code path:

- `SearchStack`
- `lambda/retrieve`
- `lambda/answer`
- Step Functions ingestion pipeline (`cdc_processor`, `validate`, `transform`, `chunking`, `enrich`, `embed`, `sync`, `graph_builder`)
- OpenSearch Serverless / Bedrock Knowledge Base orchestration code

## Object Scope And Freshness

### Live now

| Object | Freshness path |
|---|---|
| Property | CDC via `AppFlow -> S3 -> EventBridge -> lambda/cdc_sync` |
| Lease | CDC via `AppFlow -> S3 -> EventBridge -> lambda/cdc_sync` |
| Availability | CDC via `AppFlow -> S3 -> EventBridge -> lambda/cdc_sync` |
| Account | CDC via `AppFlow -> S3 -> EventBridge -> lambda/cdc_sync` |
| Contact | CDC via `AppFlow -> S3 -> EventBridge -> lambda/cdc_sync` |

Recent live namespace evidence recorded in Phase 4 task notes:

- Property: 2,470
- Lease: 483
- Availability: 527
- Account: 4,756
- Contact: 6,625
- Total: 14,861 documents

### In flight

| Object | Planned path | Notes |
|---|---|---|
| Deal | Bulk load seed + poll sync | Restores transaction scope |
| Sale | Bulk load seed + poll sync | Small volume |
| Inquiry | Bulk load seed + poll sync | Expansion object |
| Listing | Bulk load seed + poll sync | Expansion object |
| Preference | Bulk load seed + poll sync | Expansion object |
| Task | Bulk load seed + poll sync | Requires object-specific validation |
| Lead | Deferred | Config-only until records exist |
| ContentNote | Deferred | Config-only until records exist |

Important nuance: `denorm_config.yaml` and the prompt/tooling already support more than the 5 live CDC objects, but production coverage should not be described as complete until bulk-load counts, query validation, and incremental sync evidence exist.

## Query Model

The `/query` path is a tool-use loop, not a custom planner.

The model can:

- call `search_records`
- call `aggregate_records`
- ask for clarification when a grouped ranking is ambiguous
- stream the final answer with citations and optional clarification pills

Current guardrails:

- broad help questions should return short onboarding-style answers, not capability dumps
- ambiguous leaderboard / top-N requests should clarify instead of fabricating rankings
- supported ranked outputs should come from grouped aggregate results with deterministic ordering

## Project Structure

```text
.
├── bin/
│   └── app.ts                         # CDK entrypoint
├── lib/
│   ├── api-stack.ts                   # API Gateway, /query, /ingest, /schema, auth/action Lambdas
│   ├── data-stack.ts                  # Buckets, tables, shared data resources
│   ├── ingestion-stack.ts             # CDC sync, poll sync, schema discovery, drift checker
│   ├── monitoring-stack.ts            # Dashboards, alarms, active-service monitoring
│   ├── network-stack.ts               # VPC, endpoints, security groups, shared networking
│   ├── search_backend.py              # Backend abstraction
│   ├── turbopuffer_backend.py         # Turbopuffer implementation
│   ├── denormalize.py                 # Record flattening and document building
│   ├── query_handler.py               # Query loop and SSE-friendly result shaping
│   ├── tool_dispatch.py               # search_records / aggregate_records handlers
│   ├── system_prompt.py               # Runtime prompt builder
│   └── audit_writer.py                # Audit trail and replay support
├── lambda/
│   ├── action/
│   ├── authz/
│   ├── cdc_sync/
│   ├── ingest/
│   ├── poll_sync/
│   ├── query/
│   ├── schema_api/
│   ├── schema_discovery/
│   ├── schema_drift_checker/
│   ├── common/
│   └── layers/schema_discovery/
├── salesforce/
│   ├── classes/                       # Apex controllers, schema client, batch export
│   ├── lwc/                           # ascendixAiSearch component
│   ├── customMetadata/
│   ├── namedCredentials/
│   └── remoteSiteSettings/
├── scripts/
│   ├── generate_denorm_config.py      # Metadata-driven config generation
│   ├── run_config_refresh.py          # Local config refresh / artifact publish CLI
│   ├── task_manager.py                # Task workflow CLI
│   ├── run_poll_sync.py               # Poll sync runner
│   ├── replay_from_audit.py           # Replay docs from audit bucket
│   ├── bundle_*.sh                    # Lambda bundle scripts
│   └── salesforce/                    # Salesforce CLI helpers
├── tests/
│   ├── test_cdc_sync.py
│   ├── test_poll_sync.py
│   ├── test_query_lambda.py
│   ├── test_query_handler.py
│   ├── test_tool_dispatch.py
│   ├── test_system_prompt.py
│   ├── test_leaderboard_guard.py
│   ├── test_clarification_flow.py
│   └── ...
├── docs/
│   ├── architecture/
│   ├── runbooks/
│   ├── specs/
│   ├── testing/
│   └── archive/
├── denorm_config.yaml
├── tasks.json
├── TASK_TRACKING.md
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js for CDK / TypeScript builds
- AWS CLI configured
- Salesforce sandbox with Ascendix CRE package
- Turbopuffer API key
- Bedrock access for embeddings and query-time inference

### Local Setup

```bash
cp .env.example .env
# Fill in AWS / Salesforce / Turbopuffer settings

python3 scripts/task_manager.py phases
python3 scripts/task_manager.py next
```

### Generate Denorm Config

```bash
python3 scripts/generate_denorm_config.py \
  --objects ascendix__Property__c ascendix__Lease__c ascendix__Availability__c \
  --output denorm_config.yaml
```

Mock mode is available when Salesforce credentials are not configured:

```bash
python3 scripts/generate_denorm_config.py --mock --output denorm_config.yaml
```

### Refresh Runtime Config

```bash
python3 scripts/run_config_refresh.py \
  --bucket salesforce-ai-search-data-<account>-<region> \
  --target-org ascendix-beta-sandbox
```

`/query` resolves runtime config in this order:

1. active compiled artifact from S3 via the SSM active-version pointer
2. last-known-good cache in `/tmp`
3. bundled `denorm_config.yaml`

### Run Tests

```bash
python3 -m pytest tests/ -v
```

### Build CDK

```bash
npm run build
npx cdk synth
```

## Audit Trail And Replay

Bulk load and sync flows can write denormalized documents to S3 before upsert. This makes diffing, replay, and postmortem validation possible without rerunning Salesforce export or Bedrock embedding.

```bash
python3 scripts/replay_from_audit.py \
  --bucket salesforce-ai-search-audit-382211616288-us-west-2 \
  --org-id 00Ddl000003yx57EAA \
  --target-namespace test_replay \
  --dry-run
```

Key layout:

- `documents/{org_id}/{object_type}/{record_id}.json`
- `documents/{org_id}/_meta/`
- `replay/{org_id}/...`

## Migration And Decommission Status

The codebase is past the earlier graph-enhanced RAG design.

What is true now:

- Turbopuffer is the active search backend.
- `/query` is the active query surface.
- `retrieve` / `answer` / KB / AOSS orchestration has been removed from the active CDK app.
- `/ingest` and `/schema` remain because Salesforce still uses them.
- AWS decommission still requires deployment and stack deletion in environments where the legacy resources exist.

Do not use old docs or removed directories as architecture truth unless a task explicitly targets historical cleanup.

## Documentation

Start here:

- [`docs/specs/salesforce-connector-spec.md`](docs/specs/salesforce-connector-spec.md)
- [`docs/architecture/object_scope_and_sync.md`](docs/architecture/object_scope_and_sync.md)
- [`TASK_TRACKING.md`](TASK_TRACKING.md)

Useful operational docs:

- [`docs/runbooks/poll_sync.md`](docs/runbooks/poll_sync.md)
- [`docs/architecture/ascendix_search_signal_priority_and_validation.md`](docs/architecture/ascendix_search_signal_priority_and_validation.md)
- [`docs/agent_prompt_export.md`](docs/agent_prompt_export.md)

Treat `docs/archive/` as historical unless a task explicitly says otherwise.
