# Quick Start Guide

*Last updated: 2025-12-12 (Task 31.1)*

Quick reference for developers and operators working with the Salesforce AI Search system.

---

## System Overview

A Graph-Enhanced RAG system for Commercial Real Estate that:
- Translates natural language queries into structured Salesforce filters
- Uses graph traversal for cross-object queries
- Enforces Salesforce sharing rules and field-level security
- Returns grounded answers via Bedrock KB + OpenSearch Serverless

**For detailed architecture:** See `docs/guides/onboarding.md`

---

## Quick Test

```bash
# Test query (get API key from Secrets Manager, user ID from Salesforce)
curl -s -X POST "${ANSWER_LAMBDA_URL}/answer" \
  -H "x-api-key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"query": "find properties in Texas", "salesforceUserId": "YOUR_SF_USER_ID", "filters": {}}'
```

**Where to find credentials:**
- `ANSWER_LAMBDA_URL`: Lambda Function URL (AWS Console → Lambda → salesforce-ai-search-answer-docker)
- `API_KEY`: Secrets Manager (`salesforce-ai-search/streaming-api-key`)
- `salesforceUserId`: Valid Salesforce User ID from your org

---

## Key Resources

| Resource | Location |
|----------|----------|
| **Runbook** | `docs/runbooks/RUNBOOK-CANARY-OPERATIONS.md` |
| **Onboarding** | `docs/guides/onboarding.md` |
| **Architecture** | `docs/architecture/salesforce_ai_search_architecture.md` |
| **Current Config** | Lambda env vars (see runbook Section 1) |
| **Task Status** | `python3 scripts/task_manager.py phases` |
| **Recent Changes** | `docs/archive/handoffs/` (sorted by date) |

---

## Common Operations

### Check System Health

```bash
# Lambda logs (recent errors)
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 30m --region us-west-2 | grep -i error

# Schema cache status
aws dynamodb scan \
  --table-name salesforce-ai-search-schema-cache \
  --select COUNT --region us-west-2

# Graph node count
aws dynamodb scan \
  --table-name salesforce-ai-search-graph-nodes \
  --select COUNT --region us-west-2
```

### Refresh Schema Cache

```bash
aws lambda invoke \
  --function-name salesforce-ai-search-schema-discovery \
  --region us-west-2 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"operation": "discover_all"}' \
  /tmp/schema-response.json
```

### Deploy Lambda Changes

```bash
cd lambda/<function-name>
zip -r /tmp/function.zip . -x "test_*" -x "__pycache__/*"
aws lambda update-function-code \
  --function-name salesforce-ai-search-<function-name> \
  --zip-file fileb:///tmp/function.zip \
  --region us-west-2
```

---

## Troubleshooting

| Issue | Quick Check | Reference |
|-------|-------------|-----------|
| Query returns empty | Check graph filter logs | Runbook Section 7 |
| High latency | Check memory cache hits | Runbook Section 8 |
| Planner fallback | Check confidence/timeout | Runbook Section 7 |
| Aggregation fails | Check derived views | Runbook Section 9 |

**Full troubleshooting:** `docs/runbooks/RUNBOOK-CANARY-OPERATIONS.md`

---

## Configuration

Current configuration values are managed via Lambda environment variables.

**Do not hardcode values here** - see the runbook Section 1 for current settings and how to modify them.

Key variables:
- `PLANNER_ENABLED` / `PLANNER_TRAFFIC_PERCENT` - Planner controls
- `PLANNER_TIMEOUT_MS` / `PLANNER_MIN_CONFIDENCE` - Planner thresholds
- `SCHEMA_MEMORY_CACHE_TTL` - Schema cache TTL (default: 300s)
- `KNOWLEDGE_BASE_ID` - Bedrock KB identifier

---

## Getting Help

1. **Check the runbook** - `docs/runbooks/RUNBOOK-CANARY-OPERATIONS.md`
2. **Check recent handoffs** - `docs/archive/handoffs/` (newest first)
3. **Check task status** - `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md`
4. **CloudWatch logs** - Use commands in runbook for specific issues

---

## Historical Note

This guide replaces the previous version which documented a historical OpenSearch migration blocker (Task 24.2.3). That migration was completed in November 2025. The system now runs on OpenSearch Serverless (AOSS) with all stacks deployed and operational.
