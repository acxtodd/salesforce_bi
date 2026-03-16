# Implementation Plan: Planner Execution & Derived View Routing

**Date:** 2025-12-06
**Author:** Claude Code
**Status:** REVISED - Incorporating QA Feedback
**QA Review:** 2025-12-06 - Accepted with modifications

---

## Executive Summary

QA reports that canary/acceptance is blocked due to:
1. Planner not executing (`plannerMs=0` in traces)
2. Derived views not being queried (aggregation queries fail)
3. Answer Function URL remains public
4. Activities data not populated
5. Latency exceeds SLA

This plan addresses issues 1-4. Issue 5 (latency SLA) requires stakeholder approval of SLA revision.

---

## Part 1: Root Cause Analysis

### Issue 1: Planner Not Executing

**Evidence:**
```bash
aws lambda get-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --region us-west-2 --query 'Environment.Variables'

# Returns:
# "PLANNER_SHADOW_MODE": "true"
# "PLANNER_TRAFFIC_PERCENT": "0"
```

**Root Cause:** Lambda configuration was never updated from Phase 0 (shadow mode) to Phase 2 (production mode). The handoffs claim Phase 2 is complete, but the deployed configuration is still in shadow mode with 0% traffic.

**Impact:**
- Planner runs but results are discarded (shadow mode)
- `plannerMs` shows as 0 because results aren't used
- No structured filtering, no aggregation routing

---

### Issue 2: Derived Views Not Being Queried

**Evidence:** Code analysis shows:
- `QueryExecutor` class has `_execute_aggregation_query()` method that routes to `DerivedViewManager`
- `QueryExecutor` has `AGGREGATION_OBJECTS` mapping and `AGGREGATION_KEYWORDS` detection
- But `index.py` imports `QueryExecutor` (line 175-176) and **never instantiates it**
- `index.py` goes directly to `_query_bedrock_kb()` without aggregation routing

**Architecture Gap:**
```
Current Flow:
  Query → Intent → Planner (shadow) → _query_bedrock_kb() → Answer

Intended Flow (per design.md):
  Query → Intent → Planner → QueryExecutor.execute_plan() →
    → AGGREGATION_VIEW path: DerivedViewManager → Answer
    → STRUCTURED_FILTER path: Bedrock KB with filters → Answer
    → GRAPH_TRAVERSAL path: Graph Retriever → Answer
```

**Impact:** Queries like "leases expiring soon" go to Bedrock KB (which has no lease rollup data) instead of `leases_view` DynamoDB table (which has 483 records, 53 with future end dates).

---

### Issue 3: Derived View Data Status

**Verified via CLI:**

| Table | Records | Status |
|-------|---------|--------|
| `salesforce-ai-search-availability-view` | 527 | Populated |
| `salesforce-ai-search-vacancy-view` | 2,466 | Populated |
| `salesforce-ai-search-leases-view` | 483 | Populated (53 with future end_date) |
| `salesforce-ai-search-activities-agg` | 0 | **Empty** |
| `salesforce-ai-search-sales-view` | 0 | Not backfilled |

**Activities Data in Salesforce:**
```sql
SELECT COUNT() FROM Task  -- Returns: 29
SELECT COUNT() FROM Event -- Returns: 23
```

**Conclusion:** Task/Event data exists in Salesforce (52 records total) but hasn't been backfilled to `activities_agg` table.

---

## Part 2: Recommended Approach

### Research Validation

Based on web research, our approach aligns with industry best practices:

1. **Query Routing Pattern** ([Medium - Advanced RAG](https://medium.com/@malik789534/build-an-advanced-rag-app-query-routing-e468757c888a)): Query routing is a technique that analyzes the query and makes a decision on the next action from predefined choices. This is exactly what `QueryExecutor` implements.

2. **DynamoDB Aggregation via GSIs** ([AWS Docs](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-gsi-aggregation.html)): AWS recommends using GSIs for maintaining near real-time aggregations. Our derived view tables have appropriate GSIs already configured.

3. **CQRS Pattern** ([Packt - Event Sourcing](https://subscription.packtpub.com/book/cloud-and-networking/9781788470414/2/ch02lvl1sec16)): Materialized views for queries align with CQRS where downstream services create views tailored to their needs.

4. **Hybrid Retrieval** ([AWS Bedrock](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-knowledge-bases-now-supports-hybrid-search/)): Using both vector search and structured filters together, which is what our planner enables.

---

## Part 3: Implementation Steps (Revised per QA Feedback)

### Phase 1: Enable Planner at 20% Traffic (Low Risk)

**QA Guidance:** Start at low traffic % with shadow logs before going to 100%.

**Action:** Update to 20% traffic with shadow mode still ON for dual logging.

```bash
# Get current full env vars
CURRENT_ENV=$(aws lambda get-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --region us-west-2 \
  --query 'Environment.Variables' \
  --output json --no-cli-pager)

# Phase 1: 20% traffic, shadow mode on for comparison logging
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --region us-west-2 \
  --environment "Variables=$(echo $CURRENT_ENV | jq '. + {"PLANNER_SHADOW_MODE":"true","PLANNER_TRAFFIC_PERCENT":"20"}')" \
  --no-cli-pager
```

**Verification:**
```bash
# Check config applied
aws lambda get-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --query 'Environment.Variables.{SHADOW:PLANNER_SHADOW_MODE,TRAFFIC:PLANNER_TRAFFIC_PERCENT}' \
  --region us-west-2 --no-cli-pager

# Test query and check logs
curl -s -X POST 'https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d '{"query":"find Class A office in Plano","salesforceUserId":"005dl00000Q6a3RAAR"}'

# Check for CANARY logs (20% will show [CANARY], 80% will show [SHADOW])
aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
  --since 5m --region us-west-2 | grep -E "CANARY|SHADOW|plannerMs"
```

**Success Criteria:**
- ~20% of requests show `[CANARY]` prefix
- ~80% of requests show `[SHADOW]` prefix
- `plannerMs > 0` for CANARY requests
- No increase in error rate

**Rollback:**
```bash
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --region us-west-2 \
  --environment "Variables=$(echo $CURRENT_ENV | jq '. + {"PLANNER_SHADOW_MODE":"true","PLANNER_TRAFFIC_PERCENT":"0"}')" \
  --no-cli-pager
```

---

### Phase 2: QueryExecutor Integration (Medium Risk)

**QA Guidance:** Option A (full QueryExecutor integration) is the right long-term path. Add unit/integration tests.

**Architecture Overview:**

```
Current Flow (broken):
  index.py → Planner → (result discarded) → _query_bedrock_kb()

Target Flow:
  index.py → Planner → QueryExecutor.execute_plan() →
    ├── AGGREGATION_VIEW path: DerivedViewManager.query_*_view()
    ├── STRUCTURED_FILTER path: Bedrock KB with predicates
    ├── GRAPH_TRAVERSAL path: GraphAwareRetriever
    └── VECTOR_ONLY path: Bedrock KB (fallback)
```

**Implementation Steps:**

#### Step 2.1: Add Feature Flag for QueryExecutor

```python
# Add to index.py around line 250
QUERY_EXECUTOR_ROUTING_ENABLED = os.getenv(
    "QUERY_EXECUTOR_ROUTING_ENABLED", "false"
).lower() == "true"
```

#### Step 2.2: Create KB Adapter for QueryExecutor

The `QueryExecutor` expects a `KnowledgeBaseProtocol` interface. Create an adapter:

```python
# lambda/retrieve/kb_adapter.py
from typing import List, Dict, Any, Optional

class BedrockKBAdapter:
    """Adapter to make _query_bedrock_kb compatible with QueryExecutor."""

    def __init__(self, query_fn, hybrid: bool = True):
        self._query_fn = query_fn
        self._hybrid = hybrid

    def retrieve(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[List[Dict]] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve from Bedrock KB with optional filters."""
        return self._query_fn(query, limit, filters or [], use_hybrid=self._hybrid)
```

#### Step 2.3: Integrate QueryExecutor into index.py

```python
# Add around line 2640 in index.py, after planner_used check

# =====================================================================
# QueryExecutor Routing - Use for aggregation and structured queries
# **Requirements: 5.6, 5.7, 7.1, 7.2** - Aggregation and structured filter routing
# =====================================================================
use_query_executor = (
    QUERY_EXECUTOR_ROUTING_ENABLED
    and QUERY_EXECUTOR_AVAILABLE
    and planner_used
    and planner_result
    and planner_result.confidence >= PLANNER_MIN_CONFIDENCE
)

if use_query_executor:
    LOGGER.info(f"Using QueryExecutor for structured routing")
    try:
        from kb_adapter import BedrockKBAdapter

        # Create adapter for existing _query_bedrock_kb function
        kb_adapter = BedrockKBAdapter(
            query_fn=_query_bedrock_kb,
            hybrid=request_payload.get("hybrid", True)
        )

        # Create authorization context
        auth_context = AuthorizationContext(
            user_id=request_payload["salesforceUserId"],
            sharing_buckets=authz_context.get("sharingBuckets", []),
        ) if authz_context else None

        # Initialize QueryExecutor
        executor = QueryExecutor(
            knowledge_base=kb_adapter,
            planner_timeout_ms=PLANNER_TIMEOUT_MS,
            min_planner_confidence=PLANNER_MIN_CONFIDENCE,
        )

        # Execute plan
        exec_result = executor.execute_plan(
            query=request_payload["query"],
            plan=planner_result,
            authorization=auth_context,
            limit=retrieval_top_k,
        )

        # Convert ExecutionResult to matches format
        if exec_result.records:
            matches = exec_result.records
            LOGGER.info(
                f"QueryExecutor returned {len(matches)} records via "
                f"{exec_result.execution_path.value}"
            )
            query_plan["executorPath"] = exec_result.execution_path.value
            query_plan["usedFallback"] = exec_result.used_fallback
        else:
            LOGGER.info("QueryExecutor returned no records, using KB fallback")

    except Exception as e:
        LOGGER.warning(f"QueryExecutor failed, falling back to KB: {e}")
        # Fall through to existing _query_bedrock_kb call
```

#### Step 2.4: Add Unit Tests

```python
# lambda/retrieve/test_query_executor_integration.py
import pytest
from unittest.mock import MagicMock, patch

class TestQueryExecutorIntegration:
    """Integration tests for QueryExecutor routing in index.py."""

    def test_leases_expiring_routes_to_derived_view(self):
        """Verify 'leases expiring' queries route to leases_view."""
        # Mock planner to return Lease target
        mock_planner_result = MagicMock()
        mock_planner_result.target_object = "ascendix__Lease__c"
        mock_planner_result.confidence = 0.7
        mock_planner_result.predicates = []

        # Mock DerivedViewManager
        with patch('derived_view_manager.DerivedViewManager') as mock_dvm:
            mock_dvm.return_value.query_leases_view.return_value = [
                {"lease_id": "L001", "end_date": "2026-03-15"}
            ]

            executor = QueryExecutor()
            result = executor.execute_plan(
                query="leases expiring in next 6 months",
                plan=mock_planner_result,
                authorization=None,
                limit=10
            )

            assert result.execution_path.value == "aggregation_view"
            assert len(result.records) == 1

    def test_vacancy_routes_to_derived_view(self):
        """Verify vacancy queries route to vacancy_view."""
        # Similar test for vacancy queries
        pass

    def test_fallback_on_error(self):
        """Verify fallback to KB on derived view error."""
        pass
```

**Deploy Command:**
```bash
# After code changes, rebuild and deploy Lambda
cd lambda/retrieve
zip -r ../retrieve.zip .
aws lambda update-function-code \
  --function-name salesforce-ai-search-retrieve \
  --zip-file fileb://../retrieve.zip \
  --region us-west-2 --no-cli-pager

# Enable feature flag
aws lambda update-function-configuration \
  --function-name salesforce-ai-search-retrieve \
  --environment "Variables=$(aws lambda get-function-configuration \
    --function-name salesforce-ai-search-retrieve \
    --query 'Environment.Variables' --output json --no-cli-pager | \
    jq '. + {"QUERY_EXECUTOR_ROUTING_ENABLED":"true"}')" \
  --region us-west-2 --no-cli-pager
```

---

### Phase 3: Populate activities_agg (Low Risk)

**QA Guidance:** Backfill needed to make activity scenarios testable.

**Data Source (Verified via SF CLI):**
- Task: 29 records
- Event: 23 records
- Total: 52 activities

**Implementation Script:**

```bash
# scripts/backfill_activities.sh
#!/bin/bash

# Query Tasks from Salesforce
echo "Fetching Tasks..."
sf data query --query "SELECT Id, WhoId, WhatId, ActivityDate, Subject FROM Task" \
  --target-org ascendix-beta-sandbox --json > /tmp/tasks.json

# Query Events from Salesforce
echo "Fetching Events..."
sf data query --query "SELECT Id, WhoId, WhatId, ActivityDateTime, Subject FROM Event" \
  --target-org ascendix-beta-sandbox --json > /tmp/events.json

# Run Python backfill
python3 scripts/backfill_activities.py
```

```python
# scripts/backfill_activities.py
import boto3
import json
from datetime import datetime, timedelta
from collections import defaultdict

def parse_date(date_str):
    """Parse SF date string to datetime."""
    if not date_str:
        return None
    try:
        # Handle both date and datetime formats
        if 'T' in date_str:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return datetime.strptime(date_str, '%Y-%m-%d')
    except:
        return None

def main():
    # Load data from SF CLI exports
    with open('/tmp/tasks.json') as f:
        tasks = json.load(f).get('result', {}).get('records', [])
    with open('/tmp/events.json') as f:
        events = json.load(f).get('result', {}).get('records', [])

    print(f"Processing {len(tasks)} tasks and {len(events)} events")

    # Aggregate by entity
    entity_data = defaultdict(lambda: {
        "count_7d": 0, "count_30d": 0, "count_90d": 0,
        "entity_type": "Unknown", "last_activity_date": None
    })
    now = datetime.now()

    for record in tasks + events:
        # Get entity ID (WhatId for related record, WhoId for contact/lead)
        entity_id = record.get("WhatId") or record.get("WhoId")
        if not entity_id:
            continue

        # Get activity date
        date_field = record.get("ActivityDate") or record.get("ActivityDateTime")
        activity_date = parse_date(date_field)
        if not activity_date:
            continue

        days_ago = (now - activity_date.replace(tzinfo=None)).days

        # Update counts
        if days_ago <= 7:
            entity_data[entity_id]["count_7d"] += 1
        if days_ago <= 30:
            entity_data[entity_id]["count_30d"] += 1
        if days_ago <= 90:
            entity_data[entity_id]["count_90d"] += 1

        # Update last activity date
        if entity_data[entity_id]["last_activity_date"] is None or \
           activity_date > parse_date(entity_data[entity_id]["last_activity_date"]):
            entity_data[entity_id]["last_activity_date"] = date_field

        # Determine entity type from ID prefix
        prefix = entity_id[:3]
        entity_types = {"001": "Account", "003": "Contact", "00Q": "Lead", "a0a": "Property"}
        entity_data[entity_id]["entity_type"] = entity_types.get(prefix, "Other")

    # Write to DynamoDB
    dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
    table = dynamodb.Table("salesforce-ai-search-activities-agg")

    for entity_id, data in entity_data.items():
        item = {
            "entity_id": entity_id,
            "entity_type": data["entity_type"],
            "count_7d": data["count_7d"],
            "count_30d": data["count_30d"],
            "count_90d": data["count_90d"],
            "last_activity_date": data["last_activity_date"] or "",
            "updated_at": datetime.now().isoformat()
        }
        table.put_item(Item=item)
        print(f"  {entity_id}: 7d={data['count_7d']}, 30d={data['count_30d']}, 90d={data['count_90d']}")

    print(f"\nBackfilled {len(entity_data)} entities to activities_agg")

if __name__ == "__main__":
    main()
```

**Verification:**
```bash
# Check table count after backfill
aws dynamodb scan --table-name salesforce-ai-search-activities-agg \
  --select COUNT --region us-west-2 --no-cli-pager

# Sample data
aws dynamodb scan --table-name salesforce-ai-search-activities-agg \
  --limit 3 --region us-west-2 --no-cli-pager
```

---

### Phase 4: Secure Answer Function URL (Medium Risk)

**QA Guidance:** Disable or IAM-protect the Answer Function URL before raising traffic.

**Current State:**
- Answer Lambda Function URL: `https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws`
- AuthType: `NONE` (public)
- Mitigation: App-level API key validation

**Option A: Switch to IAM Auth (Recommended)**

```bash
# Update Function URL to require IAM auth
aws lambda update-function-url-config \
  --function-name salesforce-ai-search-answer \
  --auth-type AWS_IAM \
  --region us-west-2 --no-cli-pager

# Clients must now use SigV4 signing
# For testing, use AWS CLI with credentials:
aws lambda invoke-url \
  --function-url 'https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer' \
  --method POST \
  --body '{"query":"test","salesforceUserId":"005..."}' \
  output.json
```

**Note:** This requires updating Salesforce Named Credential to use AWS IAM signing, which may not be straightforward. Need to verify Named Credential capabilities.

**Option B: Delete Function URL, Use API Gateway Only**

```bash
# Delete the public Function URL
aws lambda delete-function-url-config \
  --function-name salesforce-ai-search-answer \
  --region us-west-2 --no-cli-pager

# All traffic must now go through API Gateway (which requires API key)
```

**Note:** This breaks streaming responses since API Gateway doesn't support Lambda streaming.

**Option C: Keep Current with Enhanced Monitoring (Tactical)**

For POC, keep current API key validation with enhanced monitoring:

```bash
# Add CloudWatch alarm for unauthorized access attempts
# (Already implemented in app-level validation)
```

**Recommendation:** For POC, proceed with Option C. Document as tech debt for production.

### Phase 5: Run Acceptance Tests and Report Results

**QA Guidance:** Run full 20 acceptance scenarios with real data; report pass/fail, citations, retrieve/first-token p95.

**Test Script:**
```bash
# Run full acceptance suite
cd test_automation
python3 graph_zero_config_acceptance.py --all --output results/acceptance_2025-12-06.json

# Generate summary report
python3 -c "
import json
with open('results/acceptance_2025-12-06.json') as f:
    results = json.load(f)

passed = sum(1 for r in results['scenarios'] if r['passed'])
total = len(results['scenarios'])
print(f'Pass Rate: {passed}/{total} ({100*passed/total:.1f}%)')
print(f'P95 Retrieve: {results[\"metrics\"][\"retrieve_p95_ms\"]}ms')
print(f'P95 First Token: {results[\"metrics\"][\"first_token_p95_ms\"]}ms')
print()
print('Failed Scenarios:')
for r in results['scenarios']:
    if not r['passed']:
        print(f'  - {r[\"id\"]}: {r[\"name\"]} - {r[\"failure_reason\"]}')
"
```

**Expected Report Format:**
```
Acceptance Test Results - 2025-12-06
=====================================

| Category | Count | Details |
|----------|-------|---------|
| PASS | X/20 | With citations |
| FAIL (Architecture) | Y | Need routing fix |
| FAIL (Data Gap) | Z | Need backfill |

Metrics:
- Retrieve p95: Xms (target: 1500ms)
- First-token p95: Xms (target: 2000ms)

Citations:
- S1: Plano Office Tower (Class A, Plano TX)
- S4: 53 leases expiring by 2026-06-06
...
```

---

## Part 4: Test Plan

### Verification Steps

1. **After Step 1 (Lambda Config):**
   ```bash
   # Test query and check logs for planner usage
   curl -X POST 'https://.../answer' \
     -H 'x-api-key: ...' \
     -d '{"query":"find Class A office in Plano","salesforceUserId":"..."}'

   # Check logs for plannerMs > 0
   aws logs tail /aws/lambda/salesforce-ai-search-retrieve \
     --since 5m --filter-pattern "plannerMs"
   ```

2. **After Step 2 (Aggregation Routing):**
   ```bash
   # Test lease expiration query
   curl -X POST 'https://.../answer' \
     -d '{"query":"show me leases expiring in the next 6 months",...}'

   # Should return citations with lease data, not "no information"
   ```

3. **After Step 3 (Activities Backfill):**
   ```bash
   # Verify table populated
   aws dynamodb scan --table-name salesforce-ai-search-activities-agg \
     --select COUNT --region us-west-2

   # Test activity query
   curl -X POST 'https://.../answer' \
     -d '{"query":"contacts with 5+ activities last 30 days",...}'
   ```

---

## Part 5: Risk Assessment

| Step | Risk | Mitigation |
|------|------|------------|
| 1. Lambda Config | Low | Instant rollback via env var change |
| 2. Aggregation Routing | Medium | Feature flag, fallback to KB on error |
| 3. Activities Backfill | Low | Read-only operation on SF, additive to DDB |
| 4. Function URL Security | N/A | Document only, no code change |

---

## Part 6: Implementation Order (QA Approved)

Based on QA feedback, the implementation order is:

| Phase | Action | Risk | Dependency |
|-------|--------|------|------------|
| 1 | Enable planner at 20% traffic | Low | None |
| 2 | Integrate QueryExecutor for aggregation routing | Medium | Phase 1 stable |
| 3 | Backfill activities_agg (52 records) | Low | None (can parallel) |
| 4 | Security: Keep API key mitigation for POC | Low | Document as tech debt |
| 5 | Run full acceptance suite | Low | Phases 1-3 complete |

**Escalation to 100% traffic** happens after Phase 5 shows acceptable pass rate and metrics.

---

## Part 7: Remaining Decisions

Please confirm before starting:

1. **Phase 1:** Proceed with 20% traffic + shadow mode for dual logging?

2. **Phase 4 Security:** Accept Option C (keep API key mitigation) for POC, document for production hardening?

3. **Timeline:** Execute phases sequentially, or parallelize Phase 3 (backfill) with Phase 2 (code changes)?

---

## Sources

- [AWS DynamoDB GSI Aggregation](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-gsi-aggregation.html)
- [Advanced RAG Query Routing](https://medium.com/@malik789534/build-an-advanced-rag-app-query-routing-e468757c888a)
- [AWS Bedrock Hybrid Search](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-knowledge-bases-now-supports-hybrid-search/)
- [AWS Bedrock Metadata Filtering](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-knowledge-bases-now-supports-metadata-filtering-to-improve-retrieval-accuracy/)
- [CQRS Pattern with DynamoDB](https://subscription.packtpub.com/book/cloud-and-networking/9781788470414/2/ch02lvl1sec16)
