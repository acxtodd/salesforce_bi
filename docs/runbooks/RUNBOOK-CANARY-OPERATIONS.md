# Runbook: Canary Operations

**Task:** 28.4 - Create Runbooks
**Version:** 1.2
**Last Updated:** 2025-12-12

---

## Key Endpoints

> **Environment Note:** URLs and IDs below are examples from dev environment.
> For your environment, retrieve from AWS Console or use these variables:
> - `ANSWER_LAMBDA_URL`: AWS Console → Lambda → salesforce-ai-search-answer-docker → Function URL
> - `SF_USER_ID`: Valid Salesforce User ID from your org
> - `API_KEY`: Secrets Manager → `salesforce-ai-search/streaming-api-key`

| Service | Example (Dev) |
|---------|---------------|
| Answer Lambda | `${ANSWER_LAMBDA_URL}/answer` |
| Ingest Lambda | `${INGEST_LAMBDA_URL}/` |

**API Key:** Secrets Manager (`salesforce-ai-search/streaming-api-key`) or `API_KEY` env var

---

## Table of Contents

1. [Rollback Toggles](#1-rollback-toggles)
2. [Schema Diff Handling](#2-schema-diff-handling)
3. [KB/Index Health Monitoring](#3-kbindex-health-monitoring)
4. [Data Quality Checks](#4-data-quality-checks)
5. [Emergency Procedures](#5-emergency-procedures)
6. [Recent Architectural Changes](#6-recent-architectural-changes-2025-12-1011)
7. [Planner Troubleshooting Checklist](#7-planner-troubleshooting-checklist)
8. [Latency Debugging Checklist](#8-latency-debugging-checklist)
9. [Derived View Maintenance](#9-derived-view-maintenance)

---

## 1. Rollback Toggles

### Current Configuration (as of 2025-12-11)

| Variable | Current Value | Code Default | Description |
|----------|--------------|--------------|-------------|
| `PLANNER_ENABLED` | `true` | `true` | Enable/disable planner entirely |
| `PLANNER_SHADOW_MODE` | `false` | `false` | Shadow mode logs but doesn't affect results |
| `PLANNER_TRAFFIC_PERCENT` | `100` | `0` | Percentage of requests using planner |
| `PLANNER_MIN_CONFIDENCE` | `0.3` | `0.5` | Minimum confidence to use planner results |
| `PLANNER_TIMEOUT_MS` | `6000` | `500` | Planner timeout in milliseconds |

**Note:** Code defaults are in `lambda/retrieve/index.py:280-290`. Current values set via Lambda environment variables.

### Rollback Procedures

#### Disable Planner Entirely (Emergency)

```bash
# Full disable - planner code won't execute
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --environment "Variables={
    PLANNER_ENABLED=false,
    PLANNER_SHADOW_MODE=true,
    PLANNER_TRAFFIC_PERCENT=0,
    PLANNER_MIN_CONFIDENCE=0.3,
    PLANNER_TIMEOUT_MS=6000,
    SCHEMA_FILTER_ENABLED=true,
    KNOWLEDGE_BASE_ID=HOOACWECEX,
    LOG_LEVEL=INFO
  }" \
  --region us-west-2
```

#### Re-enable Shadow Mode (Partial Rollback)

```bash
# Planner runs but doesn't affect results
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --environment "Variables={
    PLANNER_ENABLED=true,
    PLANNER_SHADOW_MODE=true,
    PLANNER_TRAFFIC_PERCENT=0,
    PLANNER_MIN_CONFIDENCE=0.3,
    PLANNER_TIMEOUT_MS=6000,
    SCHEMA_FILTER_ENABLED=true,
    KNOWLEDGE_BASE_ID=HOOACWECEX,
    LOG_LEVEL=INFO
  }" \
  --region us-west-2
```

#### Reduce Traffic Percentage (Gradual Rollback)

```bash
# Reduce to 20% traffic
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --environment "Variables={
    PLANNER_ENABLED=true,
    PLANNER_SHADOW_MODE=false,
    PLANNER_TRAFFIC_PERCENT=20,
    PLANNER_MIN_CONFIDENCE=0.3,
    PLANNER_TIMEOUT_MS=6000,
    SCHEMA_FILTER_ENABLED=true,
    KNOWLEDGE_BASE_ID=HOOACWECEX,
    LOG_LEVEL=INFO
  }" \
  --region us-west-2
```

#### Restore Full Canary (Current State)

```bash
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --environment "Variables={
    PLANNER_ENABLED=true,
    PLANNER_SHADOW_MODE=false,
    PLANNER_TRAFFIC_PERCENT=100,
    PLANNER_MIN_CONFIDENCE=0.3,
    PLANNER_TIMEOUT_MS=6000,
    SCHEMA_FILTER_ENABLED=true,
    KNOWLEDGE_BASE_ID=HOOACWECEX,
    LOG_LEVEL=INFO
  }" \
  --region us-west-2
```

### Verify Configuration

```bash
aws lambda get-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --region us-west-2 \
  --query 'Environment.Variables' | jq '.PLANNER_ENABLED, .PLANNER_SHADOW_MODE, .PLANNER_TRAFFIC_PERCENT'
```

---

## 2. Schema Diff Handling

### Check Current Schema Cache

```bash
# Count items in schema cache
aws dynamodb scan \
  --table-name salesforce-ai-search-schema-cache \
  --region us-west-2 \
  --select COUNT

# List cached objects
aws dynamodb scan \
  --table-name salesforce-ai-search-schema-cache \
  --region us-west-2 \
  --projection-expression "objectName"
```

### Refresh Schema Cache

Run schema discovery to update cache from Salesforce:

```bash
# Invoke schema discovery Lambda - discover all CRE objects
aws lambda invoke \
  --function-name salesforce-ai-search-schema-discovery \
  --region us-west-2 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"operation": "discover_all"}' \
  /tmp/schema-refresh-response.json

cat /tmp/schema-refresh-response.json | jq

# Or discover a specific object
aws lambda invoke \
  --function-name salesforce-ai-search-schema-discovery \
  --region us-west-2 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"operation": "discover_object", "sobject": "ascendix__Property__c"}' \
  /tmp/schema-object-response.json
```

**Supported operations:** `discover_all`, `discover_object`, `get_schema`, `invalidate_cache`, `get_export_fields`

See: `lambda/schema_discovery/index.py:20-49` for full payload documentation.

### Handle Schema Drift

1. **Detect Drift:**
   ```bash
   # Get current cache state
   aws dynamodb scan \
     --table-name salesforce-ai-search-schema-cache \
     --region us-west-2 \
     --projection-expression "objectApiName,discoveredAt" | jq '.Items'

   # Invalidate and re-discover
   aws lambda invoke \
     --function-name salesforce-ai-search-schema-discovery \
     --region us-west-2 \
     --cli-binary-format raw-in-base64-out \
     --payload '{"operation": "invalidate_cache"}' \
     /tmp/invalidate-response.json

   aws lambda invoke \
     --function-name salesforce-ai-search-schema-discovery \
     --region us-west-2 \
     --cli-binary-format raw-in-base64-out \
     --payload '{"operation": "discover_all"}' \
     /tmp/rediscover-response.json
   ```

2. **If Fields Added/Removed:**
   - Re-run schema discovery (above)
   - **If new filterable field needed in graph nodes:** Re-index affected objects via Batch Export
   - Trigger KB re-sync if text fields changed

3. **If Objects Added:**
   - Add to `FALLBACK_CONFIGS` in `lambda/chunking/index.py`
   - Add to `CRE_OBJECTS` in `lambda/schema_discovery/discoverer.py`
   - Deploy Lambdas
   - Run initial ingestion for new object

---

## 3. KB/Index Health Monitoring

### Check Bedrock KB Status

```bash
# Get KB details
aws bedrock-agent get-knowledge-base \
  --knowledge-base-id HOOACWECEX \
  --region us-west-2

# List data sources
aws bedrock-agent list-data-sources \
  --knowledge-base-id HOOACWECEX \
  --region us-west-2
```

### Check Ingestion Job Status

```bash
# List recent ingestion jobs
aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id HOOACWECEX \
  --data-source-id <DATA_SOURCE_ID> \
  --region us-west-2 \
  --max-results 5
```

### Verify S3 Chunk Counts

```bash
# Count chunks per object type
for obj in ascendix__Property__c ascendix__Availability__c ascendix__Lease__c ascendix__Deal__c Account; do
  count=$(aws s3 ls s3://salesforce-ai-search-data-dev/chunks/${obj}/ --recursive --region us-west-2 | wc -l)
  echo "${obj}: ${count} chunks"
done
```

### Check OpenSearch Index Health

```bash
# Get OpenSearch domain status
aws opensearchserverless get-access-policy \
  --name salesforce-ai-search \
  --type data \
  --region us-west-2
```

---

## 4. Data Quality Checks

### Derived View Counts

```bash
# Check all derived view tables
for table in availability-view vacancy-view leases-view activities-agg sales-view; do
  count=$(aws dynamodb scan \
    --table-name salesforce-ai-search-${table} \
    --region us-west-2 \
    --select COUNT \
    --query 'Count' \
    --output text)
  echo "salesforce-ai-search-${table}: ${count} items"
done
```

### Vocab Cache Health

```bash
# Check vocab cache item count
aws dynamodb scan \
  --table-name salesforce-ai-search-vocab-cache \
  --region us-west-2 \
  --select COUNT

# Sample vocab terms
aws dynamodb scan \
  --table-name salesforce-ai-search-vocab-cache \
  --region us-west-2 \
  --max-items 10 \
  --projection-expression "term, #t" \
  --expression-attribute-names '{"#t": "type"}'
```

### Property Field Coverage

```bash
# Query KB for field coverage sample
# Replace ${ANSWER_LAMBDA_URL}, ${API_KEY}, ${SF_USER_ID} with your environment values
curl -s -X POST "${ANSWER_LAMBDA_URL}/answer" \
  -H "x-api-key: ${API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"query":"list 10 properties with their city and state","salesforceUserId":"'"${SF_USER_ID}"'","filters":{}}'
```

### Test Query Suite

```bash
# Run quick validation queries
queries=(
  "find properties in Texas"
  "find properties in Arizona"
  "find properties in Georgia"
)

for q in "${queries[@]}"; do
  echo "Testing: $q"
  curl -s -X POST "${ANSWER_LAMBDA_URL}/answer" \
    -H "x-api-key: ${API_KEY}" \
    -H 'Content-Type: application/json' \
    -d "{\"query\":\"$q\",\"salesforceUserId\":\"${SF_USER_ID}\",\"filters\":{}}" \
    | grep -c "event: citation"
  echo "---"
done
```

---

## 5. Emergency Procedures

### Complete System Disable

If system is causing production issues:

```bash
# 1. Disable Answer Lambda Function URL
aws lambda delete-function-url-config \
  --function-name salesforce-ai-search-answer-docker \
  --region us-west-2

# 2. Or update API Gateway to return 503
# (requires API Gateway console or CDK update)
```

### Restore from Backup

If KB data is corrupted:

```bash
# 1. Trigger full re-sync from S3 chunks
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id HOOACWECEX \
  --data-source-id <DATA_SOURCE_ID> \
  --region us-west-2

# 2. Refresh schema cache via Schema Discovery Lambda
# (seed_schema_cache.py is DEPRECATED - use Lambda instead)
aws lambda invoke \
  --function-name salesforce-ai-search-schema-discovery \
  --region us-west-2 \
  --cli-binary-format raw-in-base64-out \
  --payload '{"operation": "discover_all"}' \
  /tmp/schema-restore.json

# 3. Verify schema cache populated
aws dynamodb scan \
  --table-name salesforce-ai-search-schema-cache \
  --select COUNT --region us-west-2
```

### Salesforce Token Refresh

When Salesforce access token expires:

```bash
# 1. Get new token from Salesforce admin
# 2. Update SSM parameter
aws ssm put-parameter \
  --name /salesforce/access_token \
  --value "<NEW_TOKEN>" \
  --type SecureString \
  --overwrite \
  --region us-west-2

# 3. Verify connection
python3 -c "
from lambda.common.salesforce_client import SalesforceClient
client = SalesforceClient.from_ssm()
result = client.query('SELECT COUNT() FROM Account')
print(f'Connected: {result}')
"
```

---

## CloudWatch Alerts

### Key Metrics to Monitor

| Metric | Threshold | Action |
|--------|-----------|--------|
| `RetrieveLambdaErrors` | >5 per minute | Investigate, consider rollback |
| `RetrieveLatencyP95` | >5s (simple), >10s (complex) | Check Bedrock KB health |
| `PlannerTimeouts` | >10% | Increase `PLANNER_TIMEOUT_MS` (current: 6000ms) |
| `PlannerFallbackRate` | >15% | Check vocab cache, schema cache |
| `NoResultsRate` | >10% | Check KB ingestion, graph nodes |
| `CDCLag` | >10 minutes | Check CDC pipeline, Step Functions |
| `RollupFreshness` | >30 minutes | Run derived view backfill |

**Note:** Planner timeout is currently 6000ms. If timeouts spike, first check if schema cache/vocab cache are accessible, then consider increasing timeout.

### Log Queries

```bash
# Recent errors
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 30m --region us-west-2 | grep -i error

# Planner activity
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 30m --region us-west-2 | grep -E "CANARY|planner|Bypassing"

# Latency traces
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 30m --region us-west-2 | grep "totalMs"

# Schema cache hits/misses
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 30m --region us-west-2 | grep -i "schema"

# Signal harvesting (relevance scoring)
aws logs tail /aws/lambda/salesforce-ai-search-schema-discovery \
  --since 30m --region us-west-2 | grep -E "signal|relevance|SavedSearch"
```

---

## 6. Recent Architectural Changes (2025-12-10/11)

### Schema-Driven Export (Task 34)

The batch export now reads field configuration from Schema Cache instead of IndexConfiguration__mdt.

**Key Files:**
- `lambda/schema_discovery/index.py` - Added `get_export_fields` operation
- `salesforce/classes/SchemaCacheClient.cls` - Apex client for Schema Cache API
- `salesforce/classes/AISearchBatchExport.cls` - Modified to use Schema Cache

**What Changed:**
- Batch export SOQL queries are dynamically generated from Schema Cache
- `RecordType.Name` auto-included when object has RecordTypes
- Falls back to IndexConfiguration__mdt when `Override_Schema_Cache__c = true`

**If Batch Export Fails:**
1. Check Schema Cache has the object: `aws dynamodb get-item --table-name salesforce-ai-search-schema-cache --key '{"objectApiName":{"S":"<OBJECT>"}}'`
2. Verify Schema Discovery Lambda has Salesforce credentials
3. Enable override: Set `Override_Schema_Cache__c = true` in IndexConfiguration__mdt

### Ingest-Time Field Validation (Task 38)

Fail-fast validation ensures exported fields match schema cache expectations.

**Behavior:**
- Graph Builder validates incoming records against Schema Cache field contract
- Logs `[FIELD_CONTRACT]` warnings for missing/unexpected fields
- Validation does NOT block ingestion (warning only) but helps identify drift

**Debug Commands:**
```bash
# Check for field contract warnings
aws logs tail /aws/lambda/salesforce-ai-search-graph-builder \
  --since 1d --region us-west-2 | grep "FIELD_CONTRACT"
```

### Signal Harvesting & Relevance Scoring (Tasks 40-44)

Schema Discovery now harvests usage signals from Salesforce Saved Searches, ListViews, and SearchLayouts to score field relevance.

**Key Files:**
- `lambda/schema_discovery/signal_harvester.py` - Extracts signals from SF
- `lambda/schema_discovery/models.py` - `relevance_score` field (0-10 scale)
- `lambda/retrieve/planner.py` - Uses relevance for confidence boosting
- `lambda/retrieve/entity_linker.py` - Uses relevance for disambiguation

**What Changed:**
- Fields used in Saved Searches get higher relevance (score: 7-10)
- Planner boosts confidence for queries matching high-relevance fields
- Entity linker prefers high-relevance fields for ambiguous term resolution
- Vocab cache auto-seeded from filter values in Saved Searches

**Post-Deployment for Signal Harvesting:**
```bash
# 1. Re-run schema discovery to harvest signals
aws lambda invoke --function-name salesforce-ai-search-schema-discovery \
  --payload '{"operation": "discover_all"}' --cli-binary-format raw-in-base64-out \
  --region us-west-2 /tmp/discover.json

# 2. (If broker edges needed) Re-index Deal/Listing/Inquiry
# This populates Broker__c/Party__c relationship edges in graph
# Run via Batch Export from Salesforce
```

### Aggregation Bypass Fix (2025-12-11)

Fixed graph filter short-circuit blocking aggregation queries (vacancy, etc.).

**Behavior:**
- Queries containing aggregation keywords (`vacancy`, `total`, `count`, etc.) bypass graph filter short-circuit
- Routes to derived views (`vacancy_view`, `availability_view`) even when graph filter returns 0

**If Vacancy Queries Fail:**
1. Check derived view has data: `aws dynamodb scan --table-name salesforce-ai-search-vacancy-view --select COUNT`
2. Run backfill: `python3 scripts/one-off/backfill_vacancy_metrics.py --clear`

---

*This runbook should be reviewed and updated after each production incident.*

---

## IAM Policies Added (Manual)

The following inline policies were added to the retrieve Lambda role (`SalesforceAISearch-Api-de-RetrieveLambdaRoleC96E78D-yBXueU3zF6C6`):

| Policy Name | Resources | Actions |
|-------------|-----------|---------|
| `VocabCacheAccess` | `salesforce-ai-search-vocab-cache` | GetItem, Query, Scan, BatchGetItem |
| `SchemaCacheAccess` | `salesforce-ai-search-schema-cache` | GetItem, Query, Scan, BatchGetItem |
| `DerivedViewsAccess` | `salesforce-ai-search-*-view`, `salesforce-ai-search-activities-agg` | Scan, Query, GetItem, BatchGetItem |
| `BedrockCrossRegionAccess` | `arn:aws:bedrock:*::foundation-model/anthropic.claude-*` | InvokeModel, InvokeModelWithResponseStream |

**Note:** These should be migrated to CDK stack in future.

---

## Vacancy View Backfill

When vacancy data needs refreshing:

```bash
# Run backfill script
# Navigate to project root (adjust path for your environment)
cd "${PROJECT_ROOT:-/path/to/salesforce-ai-search}"
python3 scripts/one-off/backfill_vacancy_metrics.py --clear

# Verify counts
aws dynamodb scan --table-name salesforce-ai-search-vacancy-view --select COUNT --region us-west-2
```

---

## Streaming Response Troubleshooting

If streaming responses return empty body or timeout:

### Check Function URL InvokeMode

```bash
# Should return "RESPONSE_STREAM", not "BUFFERED"
aws lambda get-function-url-config \
  --function-name salesforce-ai-search-answer-docker \
  --region us-west-2 \
  --query 'InvokeMode'
```

### Fix If InvokeMode is BUFFERED

```bash
aws lambda update-function-url-config \
  --function-name salesforce-ai-search-answer-docker \
  --invoke-mode RESPONSE_STREAM \
  --region us-west-2
```

### Check Lambda Web Adapter Environment

```bash
# Should show AWS_LWA_INVOKE_MODE=RESPONSE_STREAM
aws lambda get-function-configuration \
  --function-name salesforce-ai-search-answer-docker \
  --region us-west-2 \
  --query 'Environment.Variables.AWS_LWA_INVOKE_MODE'
```

### Test Streaming Response

```bash
# Set SF_USER_ID and ANSWER_LAMBDA_URL for your environment first
curl -N -s -X POST "${ANSWER_LAMBDA_URL}/answer" \
  -H "Content-Type: application/json" \
  -H "x-api-key: $(aws secretsmanager get-secret-value --secret-id salesforce-ai-search/streaming-api-key --region us-west-2 --query 'SecretString' --output text | jq -r '.apiKey')" \
  -d '{"query":"find properties in Texas","salesforceUserId":"'"${SF_USER_ID}"'","filters":{}}' | head -20
# Should show "event: token" and "data:" lines streaming
```

---

## Quick Test Commands

```bash
# Set your Salesforce user ID first
export SF_USER_ID="<your-salesforce-user-id>"

# Test retrieve Lambda directly
aws lambda invoke \
  --function-name salesforce-ai-search-retrieve \
  --cli-binary-format raw-in-base64-out \
  --payload '{"httpMethod":"POST","path":"/retrieve","body":"{\"query\":\"find properties in Texas\",\"salesforceUserId\":\"'"${SF_USER_ID}"'\",\"filters\":{}}","headers":{"content-type":"application/json"}}' \
  --region us-west-2 \
  /tmp/test_response.json && jq -r '.body' /tmp/test_response.json | jq '.matches | length'

# Test aggregation routing (vacancy)
aws lambda invoke \
  --function-name salesforce-ai-search-retrieve \
  --cli-binary-format raw-in-base64-out \
  --payload '{"httpMethod":"POST","path":"/retrieve","body":"{\"query\":\"show me properties with high vacancy rates\",\"salesforceUserId\":\"'"${SF_USER_ID}"'\",\"filters\":{}}","headers":{"content-type":"application/json"}}' \
  --region us-west-2 \
  /tmp/vacancy_response.json && jq -r '.body' /tmp/vacancy_response.json | jq '.queryPlan.aggregation'
```

---

## 7. Planner Troubleshooting Checklist

*Added: Task 31.2 (2025-12-12)*

Use this checklist when queries fail or fall back to vector search unexpectedly.

### Decision Flow

```
Query returns "I don't have enough information"
    │
    ├─▶ Check logs for "graphFilterShortCircuit: true"?
    │       │
    │       ├─▶ YES: Graph filter returned 0 matches
    │       │       │
    │       │       ├─▶ Check schema decomposition filters in logs
    │       │       │   Look for: "Schema decomposition: entity=..., filters={...}"
    │       │       │
    │       │       ├─▶ Query graph nodes for those filters:
    │       │       │   aws dynamodb scan --table-name salesforce-ai-search-graph-nodes \
    │       │       │     --filter-expression "attribute_exists(attributes.FIELD_NAME)" \
    │       │       │     --select COUNT
    │       │       │
    │       │       └─▶ If field missing → Check Schema Cache → Re-run Schema Discovery
    │       │
    │       └─▶ NO: Continue to planner timeout check
    │
    └─▶ Check logs for "Planner timeout" or "fallbackReason: timeout"?
            │
            ├─▶ YES: Planner exceeded timeout
            │       │
            │       ├─▶ Check schema cache hits: grep "Memory cache"
            │       └─▶ If cache misses → Check SCHEMA_MEMORY_CACHE_TTL
            │
            └─▶ NO: Check "fallbackReason: low_confidence"?
                    │
                    └─▶ YES: Planner confidence below threshold
                            └─▶ Check PLANNER_MIN_CONFIDENCE setting
```

### Quick Checks

```bash
# 1. Check planner is enabled
aws lambda get-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --region us-west-2 \
  --query 'Environment.Variables | {PLANNER_ENABLED, PLANNER_TRAFFIC_PERCENT}'

# 2. Check recent fallback reasons
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 15m --region us-west-2 | grep -E "fallback|timeout|short-circuit"

# 3. Verify schema cache is populated
aws dynamodb scan \
  --table-name salesforce-ai-search-schema-cache \
  --select COUNT --region us-west-2
```

### Where Current Config Values Live

| Setting | Location |
|---------|----------|
| Planner timeout, traffic %, confidence | Lambda env vars (see Section 1) |
| Schema memory cache TTL | `SCHEMA_MEMORY_CACHE_TTL` env var (default: 300s) |
| Current acceptance results | `tasks.md` → Task 29 checkpoint |
| Recent fixes/changes | Latest handoff in `docs/archive/handoffs/` |

---

## 8. Latency Debugging Checklist

*Added: Task 31.2 (2025-12-12)*

Use this when retrieve p95 exceeds targets (see `tasks.md` Task 29.2 for current SLOs).

### Latency Breakdown (Expected)

| Component | Typical | Check If |
|-----------|---------|----------|
| LLM decomposition | ~1.5s | Claude Haiku call |
| Graph filter | ~120ms | DynamoDB query |
| KB search | ~100ms | Bedrock KB |
| Schema cache | ~0ms (cached) | ~2.5s if cache miss |

### Debug Steps

```bash
# 1. Check memory cache is working
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 5m --region us-west-2 | grep -i "memory cache"
# Should see: "Memory cache hit for ..." (0.0ms)
# Red flag: "Memory cache miss" or DynamoDB scan times

# 2. Profile a request (look for totalMs)
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 5m --region us-west-2 | grep "totalMs"

# 3. Check for cold starts
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 10m --region us-west-2 | grep "INIT"
# Cold start = cache needs to warm up
```

### Memory Cache Verification

If latency regresses after deployment:

```bash
# Verify SchemaCache has in-memory caching
grep -n "_memory_cache" lambda/retrieve/schema_discovery/cache.py

# Check TTL setting
aws lambda get-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --region us-west-2 \
  --query 'Environment.Variables.SCHEMA_MEMORY_CACHE_TTL'
# Default: 300 (5 minutes)
```

### Reference: Latency Fix History

| Date | Issue | Fix | Handoff |
|------|-------|-----|---------|
| 2025-12-12 | p95 9.5s → 2.2s | Added in-memory schema cache | `HANDOFF-2025-12-12-LATENCY-OPTIMIZATION.md` |

---

## 9. Derived View Maintenance

*Added: Task 31.2 (2025-12-12)*

### View Tables

| View | Table | Purpose |
|------|-------|---------|
| Availability | `salesforce-ai-search-availability-view` | Available spaces per property |
| Vacancy | `salesforce-ai-search-vacancy-view` | Vacancy percentages |
| Leases | `salesforce-ai-search-leases-view` | Lease details with expiration |
| Activities | `salesforce-ai-search-activities-agg` | Activity counts (7/30/90 day) |
| Sales | `salesforce-ai-search-sales-view` | Sale records with broker info |

### Backfill Process

When derived view data needs refreshing:

```bash
# 1. Check current counts
for table in availability-view vacancy-view leases-view activities-agg sales-view; do
  count=$(aws dynamodb scan \
    --table-name salesforce-ai-search-${table} \
    --select COUNT --region us-west-2 --query 'Count' --output text)
  echo "${table}: ${count}"
done

# 2. Run backfill (clears and rebuilds)
# Note: Script path and cadence documented in tasks.md
python3 scripts/one-off/backfill_vacancy_metrics.py --clear

# 3. Verify after backfill
aws dynamodb scan \
  --table-name salesforce-ai-search-vacancy-view \
  --select COUNT --region us-west-2
```

### When to Backfill

- After schema changes affecting aggregation fields
- If derived view queries return stale data
- After source data bulk updates from Salesforce

**Note:** Backfill cadence/schedule is operational; see `tasks.md` or latest handoff for current recommendations.

---

*Last updated: 2025-12-12 (Task 31.2)*
