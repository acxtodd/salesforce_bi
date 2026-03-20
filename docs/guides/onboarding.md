# Agent Onboarding Guide

*Last updated: 2026-03-20*

This guide is for the current Turbopuffer-based connector.

## Read This First

Start with these files in order:

1. `README.md`
2. `docs/architecture/object_scope_and_sync.md`
3. `CLAUDE.md`
4. `TASK_TRACKING.md`

If your task touches sync expansion:

5. `docs/runbooks/poll_sync.md`

If your task touches prompt/query behavior:

6. `docs/agent_prompt_export.md`

## Current System Shape

The live architecture is:

- Salesforce LWC -> Apex -> `/query`
- `lambda/query` orchestrates Claude tool use
- tools are `search_records` and `aggregate_records`
- documents are denormalized Salesforce records stored in Turbopuffer
- current live freshness for 5 objects is `AppFlow -> S3 -> EventBridge -> lambda/cdc_sync`
- broader object scope is moving through bulk seed + poll sync

The active searchable set today is:

- `Property`
- `Lease`
- `Availability`
- `Account`
- `Contact`

Expansion work in Phase 4 covers:

- `Deal`
- `Sale`
- `Inquiry`
- `Listing`
- `Preference`
- `Task`

Deferred/config-only:

- `Lead`
- `ContentNote`

## What Changed From The Older System

The repo previously contained a graph-enhanced RAG stack built around:

- `lambda/retrieve`
- `lambda/answer`
- Step Functions ingestion
- Bedrock Knowledge Base
- OpenSearch Serverless
- graph tables and derived views

That is no longer the active architecture. Most of that code has been removed
from the active CDK app, and the remaining historical material should not be
used as the source of truth for current connector work.

## Current Repo Landmarks

### CDK

- `bin/app.ts`
- `lib/network-stack.ts`
- `lib/data-stack.ts`
- `lib/ingestion-stack.ts`
- `lib/api-stack.ts`
- `lib/monitoring-stack.ts`

### Runtime Python

- `lib/search_backend.py`
- `lib/turbopuffer_backend.py`
- `lib/denormalize.py`
- `lib/query_handler.py`
- `lib/tool_dispatch.py`
- `lib/system_prompt.py`
- `lib/audit_writer.py`

### Lambda handlers

- `lambda/query/`
- `lambda/cdc_sync/`
- `lambda/poll_sync/`
- `lambda/ingest/`
- `lambda/schema_api/`
- `lambda/schema_discovery/`
- `lambda/schema_drift_checker/`
- `lambda/action/`
- `lambda/authz/`

### Salesforce

- `salesforce/classes/AscendixAISearchController.cls`
- `salesforce/classes/AISearchBatchExport.cls`
- `salesforce/classes/SchemaCacheClient.cls`
- `salesforce/lwc/ascendixAiSearch/`

## Operating Rules

- Use `python3 scripts/task_manager.py` for all task reads/writes.
- Read `docs/architecture/object_scope_and_sync.md` before changing scope or sync behavior.
- Treat `/ingest` and `AISearchBatchExport` as preserved fallback paths, not the primary new-work path.
- Do not assume old docs are current just because they exist outside `docs/archive/`.

## Recommended First Commands

```bash
python3 scripts/task_manager.py phases
python3 scripts/task_manager.py next
git status --short
npm run build
python3 -m pytest tests/test_query_handler.py tests/test_tool_dispatch.py -v
```

## If You Need Historical Context

Use these only when a task explicitly targets legacy cleanup, archaeology, or
cost decommissioning:

- `docs/archive/`
- `docs/specs/phase4-graph-rag-prd.md`
- historical handoffs under `docs/archive/handoffs/`

For current work, prefer `README.md` and the active architecture/runbook docs.
