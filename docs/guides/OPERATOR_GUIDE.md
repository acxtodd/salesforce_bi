# Salesforce Connector Operator Guide

*Last updated: 2026-03-20*

Day-to-day operations guide for the current Turbopuffer connector.

## Scope

This guide covers:

- `lambda/query`
- `lambda/cdc_sync`
- `lambda/poll_sync`
- `/schema`
- `/ingest`
- schema discovery / schema drift monitoring

It does not cover the retired retrieve/answer/planner/KB canary path.

## Quick Reference

| Need | Where to look |
|---|---|
| Current object/sync ownership | `docs/architecture/object_scope_and_sync.md` |
| Poll sync operations | `docs/runbooks/poll_sync.md` |
| Task status | `python3 scripts/task_manager.py phases` |
| Prompt behavior | `docs/agent_prompt_export.md` |
| Historical legacy ops | `docs/archive/README.md` |

## Dashboards And Signals

Monitor these areas in CloudWatch:

- Query Lambda errors and latency
- CDC sync errors and processed counts
- Poll sync errors and per-object counts
- Schema drift checker alarms and metrics
- API Gateway 4xx/5xx on `/query`, `/schema`, `/ingest`

## Quick AWS Checks

```bash
aws lambda get-function-configuration \
  --function-name salesforce-ai-search-query \
  --region us-west-2 \
  --query '{FunctionName:FunctionName,Runtime:Runtime,LastModified:LastModified}'

aws lambda get-function-configuration \
  --function-name salesforce-ai-search-cdc-sync \
  --region us-west-2 \
  --query '{FunctionName:FunctionName,Runtime:Runtime,LastModified:LastModified}'
```

## Query Path Checks

### Smoke test the `/query` surface

Use the Salesforce LWC path or Apex callout path for end-to-end validation.
For backend-only validation, inspect Query Lambda logs and recent deployment
config.

Things to verify:

- streaming answers complete successfully
- citations render
- clarification options appear for ambiguous leaderboard queries
- broad help questions return concise onboarding responses

## CDC Checks

For the 5 live objects:

1. confirm AppFlow wrote a fresh S3 object
2. confirm EventBridge fired
3. confirm `salesforce-ai-search-cdc-sync` processed the record
4. confirm the updated value is searchable

Do not treat downstream logs alone as user-visible validation.

## Schema Checks

### Refresh schema discovery

```bash
aws lambda invoke \
  --function-name salesforce-ai-search-schema-discovery \
  --region us-west-2 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"operation": "discover_all"}' \
  /tmp/schema-discovery.json
cat /tmp/schema-discovery.json | jq
```

### Validate schema drift checker health

```bash
aws logs tail /aws/lambda/salesforce-ai-search-schema-drift-checker \
  --since 30m --region us-west-2
```

## Poll Sync Checks

Use `docs/runbooks/poll_sync.md` as the detailed runbook. At a high level:

- watermark must advance only after committed updates
- immediate rerun with no changes should be a no-op
- at least one post-sync real query should be validated

## Preserved Fallback Surfaces

These remain active for compatibility:

- `/schema` is still used by Salesforce schema export logic
- `/ingest` is still used by `AISearchBatchExport`

Do not remove or reconfigure them casually even though they are no longer the
preferred path for new connector work.

## Escalation Hints

### Query answers are wrong but Lambda is healthy

- check prompt/tooling changes
- check denorm config coverage
- check object scope expectations
- check whether the query was ambiguous and should have clarified

### CDC appears healthy but user cannot find the record

- verify the changed field is indexed
- verify the object is part of current live scope
- verify search behavior through the actual LWC path, not just logs

### Poll sync changed data but results still look stale

- verify watermark handling
- verify audit/replay artifacts
- verify the document actually changed in Turbopuffer

## Related Docs

- `README.md`
- `docs/architecture/object_scope_and_sync.md`
- `docs/runbooks/poll_sync.md`
- `docs/agent_prompt_export.md`
