# Salesforce Connector Architecture

*Last updated: 2026-03-20*

## Scope

This document describes the current connector architecture in this repo.

For live object/sync ownership, also read:

- `README.md`
- `docs/architecture/object_scope_and_sync.md`

## Executive Summary

The active system is:

- denormalized Salesforce records indexed into Turbopuffer
- `lambda/query` using Claude tool use over `search_records` and `aggregate_records`
- `lambda/cdc_sync` as the live freshness path for 5 CDC-managed objects
- bulk load plus `lambda/poll_sync` as the expansion path for non-CDC objects
- Salesforce LWC calling AWS through Apex

The older graph-enhanced RAG path is no longer the active design.

## High-Level Topology

```text
Salesforce Org
  ├─ LWC / Apex callout
  ├─ CDC change events
  ├─ Batch export fallback
  └─ Describe API

AWS
  ├─ API Gateway
  │   ├─ /query
  │   ├─ /schema/{object}
  │   └─ /ingest
  ├─ Query Lambda
  ├─ CDC Sync Lambda
  ├─ Poll Sync Lambda
  ├─ Ingest Lambda
  ├─ Schema Discovery / Drift Checker
  ├─ Turbopuffer
  ├─ S3 buckets
  └─ DynamoDB support tables
```

## Data Model

The system indexes denormalized documents, not graph nodes/chunks.

At write time:

1. Salesforce record is fetched or exported
2. document is flattened via `lib/denormalize.py`
3. selected parent fields are copied onto the child document
4. text is built for embedding
5. metadata fields remain filterable
6. the final document is embedded and upserted into Turbopuffer

This design replaces most graph traversal with write-time denormalization.

## Freshness Paths

### Live CDC path

For `Property`, `Lease`, `Availability`, `Account`, and `Contact`:

```text
Salesforce CDC -> AppFlow -> S3 -> EventBridge -> lambda/cdc_sync
```

### Expansion path

For broader searchable scope:

```text
Bulk seed -> Turbopuffer
Incremental updates -> lambda/poll_sync
```

Poll sync is incremental unless a deliberate full-sync path is invoked.

### Preserved fallback path

`/ingest` and `AISearchBatchExport` still exist for compatibility, but they are
not the preferred new-work path.

## Query Path

`lambda/query` receives the user question and runs a tool-use loop.

Current tools:

- `search_records`
- `aggregate_records`

Key behavior:

- normal search questions trigger search immediately
- ambiguous grouped rankings clarify instead of fabricating results
- broad help/onboarding prompts avoid long capability dumps
- answers stream with citations and, when needed, clarification options

## Main Components

### CDK

- `lib/network-stack.ts`
- `lib/data-stack.ts`
- `lib/ingestion-stack.ts`
- `lib/api-stack.ts`
- `lib/monitoring-stack.ts`

### Runtime libraries

- `lib/search_backend.py`
- `lib/turbopuffer_backend.py`
- `lib/denormalize.py`
- `lib/query_handler.py`
- `lib/tool_dispatch.py`
- `lib/system_prompt.py`
- `lib/audit_writer.py`

### Lambda handlers

- `lambda/query`
- `lambda/cdc_sync`
- `lambda/poll_sync`
- `lambda/ingest`
- `lambda/schema_api`
- `lambda/schema_discovery`
- `lambda/schema_drift_checker`

## Security And Networking

- Lambdas run in the project VPC
- S3 and DynamoDB use VPC endpoints
- Bedrock runtime access remains active
- API Gateway is regional
- `/schema` and `/ingest` remain exposed because Salesforce still uses them

## Observability

Current monitoring should focus on:

- Query Lambda errors and latency
- CDC sync success/error counts
- poll sync watermark behavior and record counts
- schema drift monitoring
- API Gateway health for `/query`, `/schema`, `/ingest`

## Historical Note

If you need the older graph/Bedrock architecture for comparison or cleanup
work, use `docs/archive/` and the migration spec. Do not treat those documents
as the current runtime design.
