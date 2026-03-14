# Salesforce AI Search - Operator Guide

*Last updated: 2025-12-12 (Task 31.3)*

Day-to-day operations guide for the Salesforce AI Search system. For detailed troubleshooting procedures, see `docs/runbooks/RUNBOOK-CANARY-OPERATIONS.md`.

---

## Quick Reference

| Resource | Location |
|----------|----------|
| Full Runbook | `docs/runbooks/RUNBOOK-CANARY-OPERATIONS.md` |
| Current Config | Runbook Section 1 (Rollback Toggles) |
| Planner Troubleshooting | Runbook Section 7 |
| Latency Debugging | Runbook Section 8 |
| Derived View Maintenance | Runbook Section 9 |

---

## 1. Dashboards to Monitor

### CloudWatch Dashboard

**Name:** `SalesforceAISearch-Freshness` (or check AWS Console → CloudWatch → Dashboards)

**Key Metrics:**

| Metric | What It Shows | Alert Threshold |
|--------|---------------|-----------------|
| RetrieveLambdaErrors | Query failures | >5 per minute |
| RetrieveLatencyP95 | Query response time | See runbook for current SLOs |
| PlannerTimeouts | Planner exceeded timeout | >10% |
| PlannerFallbackRate | Fell back to vector search | >15% |
| NoResultsRate | Queries returning empty | >10% |
| CDCLag | Data freshness | >10 minutes |

### Quick Dashboard Check

```bash
# Get Lambda error count (last hour)
# Linux: use $(date -u -d '1 hour ago' ...), macOS: use $(date -u -v-1H ...)
START_TIME=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-1H +%Y-%m-%dT%H:%M:%SZ)
END_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)

aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=salesforce-ai-search-retrieve \
  --start-time "${START_TIME}" \
  --end-time "${END_TIME}" \
  --period 3600 \
  --statistics Sum \
  --region us-west-2
```

---

## 2. Alert Response Procedures

### High Error Rate

**Symptom:** RetrieveLambdaErrors spike

**Response:**
1. Check logs: `aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 15m --region us-west-2 | grep ERROR`
2. Look for: DynamoDB throttling, Bedrock errors, timeout errors
3. If sustained: Consider rollback (see runbook Section 1)

### High Latency

**Symptom:** RetrieveLatencyP95 exceeds target

**Response:**
1. Check memory cache: `grep "Memory cache" | head -10` in logs
2. If cache misses: Check for recent deployments that may have reset cache
3. For cold starts: Consider provisioned concurrency
4. Full debug: Runbook Section 8

### Planner Fallback Spike

**Symptom:** PlannerFallbackRate >15%

**Response:**
1. Check fallback reasons: `grep "fallback" in logs`
2. If timeout: Check schema cache (runbook Section 8)
3. If low_confidence: Check vocab cache
4. Full debug: Runbook Section 7

### CDC Lag

**Symptom:** Data freshness >10 minutes

**Response:**
1. Check Step Functions execution: AWS Console → Step Functions
2. Check Salesforce CDC events: Is data being pushed?
3. Check Ingest Lambda for errors

---

## 3. Daily Health Checks

Run these checks daily (or automate via CloudWatch Events):

```bash
# 1. Error summary (last 24h)
aws logs filter-log-events \
  --log-group-name /aws/lambda/salesforce-ai-search-retrieve \
  --start-time $(($(date +%s) - 86400))000 \
  --filter-pattern "ERROR" \
  --region us-west-2 \
  --query 'events | length(@)'

# 2. Schema cache populated
aws dynamodb scan \
  --table-name salesforce-ai-search-schema-cache \
  --select COUNT --region us-west-2

# 3. Graph nodes healthy
aws dynamodb scan \
  --table-name salesforce-ai-search-graph-nodes \
  --select COUNT --region us-west-2

# 4. Derived views populated
for table in vacancy-view availability-view leases-view; do
  count=$(aws dynamodb scan --table-name salesforce-ai-search-${table} \
    --select COUNT --region us-west-2 --query Count --output text)
  echo "${table}: ${count}"
done
```

### Expected Healthy State

| Check | Expected |
|-------|----------|
| Schema cache | 9 objects |
| Graph nodes | 10,000+ nodes |
| Derived views | >0 per view |
| Errors (24h) | <50 |

---

## 4. Weekly Maintenance Tasks

### Schema Drift Check

```bash
# Re-run schema discovery to catch Salesforce schema changes
aws lambda invoke \
  --function-name salesforce-ai-search-schema-discovery \
  --region us-west-2 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"operation": "discover_all"}' \
  /tmp/schema-weekly.json

# Check for new/changed fields
cat /tmp/schema-weekly.json | jq
```

### Vocab Cache Health

```bash
# Check vocab cache item count
aws dynamodb scan \
  --table-name salesforce-ai-search-vocab-cache \
  --select COUNT --region us-west-2
```

### Derived View Freshness

If aggregation queries return stale data, consider backfill (see runbook Section 9).

---

## 5. Escalation Paths

### Severity Levels

| Level | Criteria | Response Time |
|-------|----------|---------------|
| P1 | System down, all queries failing | Immediate |
| P2 | Degraded (high latency, partial failures) | 4 hours |
| P3 | Minor issues (occasional failures) | Next business day |

### P1 Escalation Steps

1. **Immediate:** Check CloudWatch dashboard for obvious issues
2. **If unclear:** Check recent deployments (Lambda versions, config changes)
3. **If needed:** Execute rollback (runbook Section 1)
4. **Notify:** Team lead + stakeholders

### Common P1 Causes

| Symptom | Likely Cause | Quick Fix |
|---------|--------------|-----------|
| All queries fail | Lambda broken | Rollback to previous version |
| All queries timeout | Bedrock/DynamoDB issue | Check AWS status page |
| Auth failures | API key/creds expired | Rotate credentials |

---

## 6. Configuration Changes

**Important:** Do not modify configurations without understanding the impact.

### Safe Changes (Low Risk)

- Adjusting `PLANNER_TRAFFIC_PERCENT` (0-100)
- Adjusting `LOG_LEVEL` (DEBUG/INFO/WARNING)

### Careful Changes (Medium Risk)

- Adjusting `PLANNER_TIMEOUT_MS`
- Adjusting `PLANNER_MIN_CONFIDENCE`

### Dangerous Changes (High Risk)

- Disabling `PLANNER_ENABLED`
- Modifying `KNOWLEDGE_BASE_ID`
- Changing DynamoDB table names

**For all config changes:** See runbook Section 1 for proper procedures and verification steps.

---

## 7. Performance Tuning

For detailed latency analysis and optimization, refer to:
- **Runbook Section 8:** Latency Debugging Checklist
- **Task 29.6 handoff:** `docs/handoffs/HANDOFF-2025-12-12-LATENCY-OPTIMIZATION.md`

### Key Tuning Levers

| Parameter | Default | Effect | Risk |
|-----------|---------|--------|------|
| `SCHEMA_MEMORY_CACHE_TTL` | 300s | Longer = fewer DynamoDB calls, but staler schema | Low |
| `PLANNER_TIMEOUT_MS` | 500ms (code), 6000ms (current) | Higher = more time for complex queries | Medium |
| `PLANNER_MIN_CONFIDENCE` | 0.3 | Lower = more planner usage, higher = more fallback | Medium |

### When to Consider Tuning

- **Latency regression after deployment:** Check memory cache TTL, verify cache hits
- **Frequent planner timeouts:** Consider increasing `PLANNER_TIMEOUT_MS`
- **Too many fallbacks:** Check vocab/schema cache health first, then adjust confidence

### Reference: Latency Breakdown

| Component | Expected | If Slow |
|-----------|----------|---------|
| Schema cache | ~0ms (warm) | Check memory cache TTL |
| LLM decomposition | ~1.5s | Claude Haiku - unavoidable |
| Graph filter | ~120ms | Check DynamoDB |
| KB search | ~100ms | Check Bedrock KB |

---

## 8. Useful Log Queries

```bash
# Recent planner activity
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 30m --region us-west-2 | grep -E "CANARY|planner"

# Schema cache operations
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 30m --region us-west-2 | grep -i "schema"

# Aggregation routing
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 30m --region us-west-2 | grep -E "AGGREGATION|vacancy_view"

# Memory cache hits/misses
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 30m --region us-west-2 | grep -i "memory cache"
```

---

## Summary

| Task | Frequency | Reference |
|------|-----------|-----------|
| Dashboard check | Continuous | Section 1 |
| Alert response | As needed | Section 2 |
| Health checks | Daily | Section 3 |
| Performance tuning | As needed | Section 7, Runbook Section 8 |
| Maintenance | Weekly | Section 4 |
| Config changes | As needed | Runbook Section 1 |
| Troubleshooting | As needed | Runbook Sections 7-9 |

---

*For detailed procedures, always refer to `docs/runbooks/RUNBOOK-CANARY-OPERATIONS.md`*
