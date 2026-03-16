# Handoff Document: System Fixes & Re-Index

**Date:** 2025-12-05
**Session Focus:** Critical infrastructure fixes and data re-indexing
**Status:** System Operational - Performance tuning needed

---

## Summary

Fixed critical infrastructure issues blocking the system and performed full data re-index. The system is now operational with improved acceptance test results.

---

## Issues Fixed

### 1. API Key Secret Missing (Critical)

**Problem:** Answer Lambda failing with 500 error - Secrets Manager couldn't find the API key secret.

**Root Cause:** The security hardening (Task 23 - fail-closed API key validation) requires a secret in Secrets Manager, but it was never created.

**Fix:**
```bash
aws secretsmanager create-secret \
  --name "salesforce-ai-search/streaming-api-key" \
  --secret-string '{"apiKey": "M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ"}' \
  --region us-west-2
```

**Note:** The Lambda expects JSON format with `apiKey` field, not plain text.

### 2. Cross-Region Bedrock Permissions (Critical)

**Problem:** Lambda getting AccessDeniedException when calling Bedrock models.

**Root Cause:** IAM policy restricted to `us-west-2` but cross-region inference profiles route to any available region (e.g., `us-east-1`).

**Fix:** Updated IAM policy to allow all regions:
```json
{
  "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
  "Resource": [
    "arn:aws:bedrock:us-west-2:382211616288:inference-profile/*",
    "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
    "arn:aws:bedrock:*::foundation-model/us.anthropic.claude-*"
  ],
  "Effect": "Allow"
}
```

### 3. Acceptance Test SSE Parsing Bug

**Problem:** Tests showing 0 citations even when system returned data.

**Root Cause:** Test expected `data['citation']` but actual SSE format has `event: citation` followed by `data: {id, title, ...}` with no wrapper.

**Fix:** Updated `test_automation/graph_zero_config_acceptance.py` to track event type before parsing data.

---

## Data Re-Index

Triggered full batch export from Salesforce:

| Object | Records | Status |
|--------|---------|--------|
| Property | 50 | Completed |
| Availability | 48 | Completed |
| Deal | 10 | Completed |
| Lease | 11 | Completed |

Bedrock KB ingestion completed:
- 10,668 documents scanned
- 2,161 documents re-indexed
- 0 failures

---

## Acceptance Test Results

| Metric | Before Fixes | After Fixes | Target |
|--------|--------------|-------------|--------|
| Pass Rate | 25% | **83.3%** | ≥75% ✅ |
| Empty Rate | 100% | **50%** | <8% ❌ |
| P95 Latency | 7622ms | **6714ms** | <1500ms ❌ |

### Scenarios with Citations (6/12)
- S1: Available Class A office in Plano (2 citations)
- S3: Class A office downtown (2 citations)
- S4: Leases expiring (1 citation)
- S5: Activities on property (1 citation)
- S10: Notes about HVAC (1 citation)
- S12: Deals in Texas (1 citation)

### Failing Scenarios (2/12)
- S6: Active contacts with negotiation sales - Complex aggregation, no matching data
- S9: Properties with high vacancy rate - Requires derived vacancy_view

---

## Remaining Work

### P0 - Performance Tuning (Task 26)
- P95 latency is 6714ms (target <1500ms)
- Planner optimization needed
- Graph traversal tuning

### P1 - Data Gaps
- Empty rate still 50% (target <8%)
- Some scenarios need derived views populated
- May need more test data in sandbox

### P2 - Observability
- CloudWatch metrics error in sync Lambda (non-blocking)
- Add metrics permissions to ingestion role

---

## Files Modified

| File | Change |
|------|--------|
| `test_automation/graph_zero_config_acceptance.py` | Fixed SSE parsing for citations |

## Infrastructure Changes

| Resource | Change |
|----------|--------|
| Secrets Manager | Created `salesforce-ai-search/streaming-api-key` |
| IAM Policy | Updated `AnswerLambdaRoleDefaultPolicyA9FC101B` for cross-region Bedrock |

---

## Test Commands

```bash
# Run acceptance tests
cd salesforce-ai-search-poc
python3 test_automation/graph_zero_config_acceptance.py --verbose

# Test direct query
curl -s -X POST 'https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d '{"query": "show properties in Plano", "salesforceUserId": "005dl00000Q6a3RAAR", "filters": {}}'
```

---

## Next Session Priority

1. **Task 26: Performance Tuning** - Address latency issues
2. **Derived Views** - Populate vacancy_view and activities_agg for failing scenarios
3. **CloudWatch Permissions** - Fix metrics in sync Lambda

---

**System Status:** Operational - Ready for performance tuning
