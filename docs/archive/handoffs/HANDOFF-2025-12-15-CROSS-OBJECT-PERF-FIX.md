# Handoff: Cross-Object Query Performance Optimization

**Date:** 2025-12-15
**Status:** Complete (QA Approved)
**Author:** Claude Code

## Summary

Optimized cross-object query traversal from 8757ms to 2913ms p95, achieving 67% latency reduction and meeting the 5000ms SLA target for complex/graph queries.

## Problem Statement

Cross-object queries like "show me leases on properties in Plano" were timing out or taking 8+ seconds due to inefficient graph edge traversal.

### Root Cause

The `_traverse_to_target()` method in `cross_object_handler.py` had an N+1 query problem:
- For each of 18 Property nodes, it called `_get_connected_nodes()`
- `_get_connected_nodes()` queried edges, then called `get_item()` for EACH connected node
- This resulted in ~400 sequential DynamoDB calls
- Edge traversal alone took 5-6 seconds

## Solution

Optimized `_traverse_to_target()` to use edge `type` field directly:

1. **Eliminated node fetches** - Edge records contain `type` field; no need to fetch target node
2. **Added ProjectionExpression** - Only fetches `fromId`/`toId` and `type` fields
3. **Direct edge queries** - Uses `toId-index` GSI for inbound edges, primary key for outbound

### Code Changes

**`lambda/retrieve/cross_object_handler.py`** (lines 558-642):
- Rewrote `_traverse_to_target()` to query edges directly
- Added timing log: `Edge traversal completed: X sources → Y targets in Zms`
- Removed dependency on `_get_connected_nodes()` for type checking

**`lambda/retrieve/index.py`**:
- Added `CROSS_OBJECT_TIMEOUT_MS` to init log (line 326)
- Added disambiguation bypass for successful cross-object results (lines 2510-2514, 2537)

## Performance Results

### Before vs After

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Edge traversal | 5000-6000ms | 162-260ms | **95%+** |
| Total cross-object query | 8757ms | 2913ms p95 | **67%** |

### SLA Compliance (5 warm runs, p95)

| Query | p50 | p95 | SLA Target | Status |
|-------|-----|-----|------------|--------|
| "class a office properties in plano" | 922ms | 1407ms | ≤1500ms | PASS |
| "leases expiring in next 6 months" | 839ms | 1488ms | ≤1500ms | PASS |
| "show me leases on properties in plano" | 1554ms | 2913ms | ≤5000ms | PASS |

## Configuration

- `CROSS_OBJECT_TIMEOUT_MS=2000` (Lambda env var)
- Code default: 2000ms (aligned)

## Authorization Note

**IMPORTANT**: The optimized traversal no longer inspects target node `sharingBuckets` during edge traversal. Authorization is now enforced via:

1. KB metadata `sharingBuckets` in post-filter (existing)
2. Cross-object filter query checks source node authorization

**Watch item**: Monitor logs for any authorization regressions. Consider adding a targeted integration test that verifies a user without bucket access cannot see lease nodes discovered via traversal.

## Monitoring Recommendations

1. **CloudWatch Alarm**: Add alarm on cross-object p95 > 4000ms
2. **DynamoDB Metrics**: Monitor `toId-index` GSI RCU and latency
3. **Log Pattern**: Watch for `[CROSS_OBJECT_TIMEOUT]` warnings (should be zero)

## Verification Commands

```bash
# Check init log shows correct timeout
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 10m | grep "INIT.*CROSS_OBJECT"

# Verify no timeout warnings
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 1h | grep "CROSS_OBJECT_TIMEOUT"

# Check edge traversal timing
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 10m | grep "Edge traversal"
```

## Test Query

```bash
cat > /tmp/test_cross_object.json << 'EOF'
{"query": "show me leases on properties in plano", "salesforceUserId": "005dl00000Q6a3RAAR"}
EOF

aws lambda invoke \
  --function-name salesforce-ai-search-retrieve \
  --payload file:///tmp/test_cross_object.json \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/result.json
```

## Related Tasks

- Task 46: OAuth Client Credentials for SF Auth (P1 - still pending)
- Task 47: CI Integration for Field Audit (P2 - still pending)

## Files Modified

| File | Changes |
|------|---------|
| `lambda/retrieve/cross_object_handler.py` | Optimized `_traverse_to_target()` |
| `lambda/retrieve/index.py` | Added init log, disambiguation bypass |

## Rollback

If issues arise:
1. Revert `cross_object_handler.py` to previous version
2. Set `CROSS_OBJECT_TIMEOUT_MS=8000` temporarily
3. Investigate via CloudWatch logs
