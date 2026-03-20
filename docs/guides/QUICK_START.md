# Quick Start Guide

*Last updated: 2026-03-20*

Quick reference for developers and operators working on the current
Salesforce connector.

## What This System Is

The live connector path is:

- Turbopuffer as the search backend
- denormalized Salesforce records as the indexed document model
- `lambda/query` for natural-language query handling
- `search_records` and `aggregate_records` as the runtime tools
- `lambda/cdc_sync` for the 5 live CDC-managed objects
- bulk load plus `lambda/poll_sync` for non-CDC expansion objects

It is not the older Bedrock KB / OpenSearch / retrieve+answer stack.

Start with:

1. `README.md`
2. `docs/architecture/object_scope_and_sync.md`
3. `CLAUDE.md`

## Quick Checks

### Project status

```bash
python3 scripts/task_manager.py phases
python3 scripts/task_manager.py next
```

### Build and test

```bash
npm run build
python3 -m pytest tests/ -v
```

### Query Lambda prompt/runtime tests

```bash
python3 -m pytest \
  tests/test_query_lambda.py \
  tests/test_query_handler.py \
  tests/test_tool_dispatch.py \
  tests/test_system_prompt.py -v
```

## Key Resources

| Resource | Location |
|---|---|
| Current architecture/status | `README.md` |
| Object scope + sync ownership | `docs/architecture/object_scope_and_sync.md` |
| Poll sync operations | `docs/runbooks/poll_sync.md` |
| Task workflow | `TASK_TRACKING.md` |
| Prompt export | `docs/agent_prompt_export.md` |
| Historical material | `docs/archive/README.md` |

## Common Operations

### Generate denorm config

```bash
python3 scripts/generate_denorm_config.py \
  --objects ascendix__Property__c ascendix__Lease__c ascendix__Availability__c \
  --output denorm_config.yaml
```

Mock mode:

```bash
python3 scripts/generate_denorm_config.py --mock --output denorm_config.yaml
```

### Run poll sync locally

```bash
python3 scripts/run_poll_sync.py --objects ascendix__Deal__c
```

### Replay from audit

```bash
python3 scripts/replay_from_audit.py \
  --bucket salesforce-ai-search-audit-382211616288-us-west-2 \
  --org-id 00Ddl000003yx57EAA \
  --target-namespace test_replay \
  --dry-run
```

## AWS Health Checks

```bash
aws sts get-caller-identity

aws lambda get-function-configuration \
  --function-name salesforce-ai-search-query \
  --region us-west-2 \
  --query '{FunctionName:FunctionName,LastModified:LastModified,Runtime:Runtime}'
```

## Current Runtime Surfaces

- `salesforce-ai-search-query`
- `salesforce-ai-search-cdc-sync`
- `salesforce-ai-search-poll-sync` when deployed
- `salesforce-ai-search-ingest`
- `salesforce-ai-search-schema-api`
- `salesforce-ai-search-schema-discovery`
- `salesforce-ai-search-schema-drift-checker`

## Do Not Use This Guide For

- legacy `lambda/retrieve` / `lambda/answer` debugging
- Bedrock KB / OpenSearch troubleshooting
- Step Functions ingestion operations

Those are historical topics. Use `docs/archive/` if a task explicitly targets
legacy cleanup or postmortem analysis.
