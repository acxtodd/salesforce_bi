# Handoff: Schema Cache Recovery

**Date:** 2025-12-15
**Session Focus:** Smoke test failure - "show me leases on properties in plano"
**Status:** PARTIAL - Schema cache fixed, cross-object timeout remains

---

## Executive Summary

Fixed schema cache outage caused by SF token with escaped `!` character. Simple and temporal queries now work. Cross-object queries still fail due to graph traversal timeout (separate issue).

---

## What Was Done

### 1. Root Cause Identified

**Primary Issue:** Schema cache was empty (only 1 object: ascendix__Sale__c)

**Why:** SF access token in Lambda env var had escaped `\!` instead of `!`
- CLI `aws lambda update-function-configuration` with `--environment` flag escaped the `!` character
- Lambda sent `Bearer 00D...!\AQE...` (with backslash) to Salesforce
- SF rejected with 401 INVALID_AUTH_HEADER

### 2. Fix Applied

Used boto3 Python SDK to bypass shell escaping issues:

```python
lambda_client.update_function_configuration(
    FunctionName='salesforce-ai-search-schema-discovery',
    Environment={
        'Variables': {
            'SALESFORCE_ACCESS_TOKEN': token,  # No shell escaping
            ...
        }
    }
)
```

### 3. Schema Discovery Executed

```
Result: 8/8 objects discovered and cached
Total cache: 9 objects (including pre-existing ascendix__Sale__c)
```

### 4. Verification

| Test | Result |
|------|--------|
| Schema cache count | ✅ 9 objects |
| Field audit | ✅ 0 fake fields, 656 valid |
| Simple property query | ✅ 3 results |
| Temporal lease query | ✅ 5 results |
| Cross-object query | ❌ Timeout |

---

## Remaining Issue

**Query:** "show me leases on properties in plano"
**Status:** Still fails

**Root Cause:** Graph traversal timeout (NOT schema cache)

```
[INFO] Cross-object filter results: scanned=2447, matched=18, type=ascendix__Property__c
[WARNING] [CROSS_OBJECT_TIMEOUT] Graph traversal timed out after 2019ms (budget=2000ms)
```

The query correctly:
1. Identified 18 properties in Plano
2. Started graph edge traversal to find related Leases
3. **Timed out** before completing (2019ms > 2000ms budget)

**This is a performance issue, not a schema issue.**

---

## Commands for Future Token Refresh

**Recommended Method (Python SDK):**

```bash
# Create script
cat > /tmp/refresh_token.py << 'EOF'
import json
import subprocess
import boto3

result = subprocess.run(
    ["sf", "org", "display", "--target-org", "ascendix-beta-sandbox", "--json"],
    capture_output=True, text=True
)
org_info = json.loads(result.stdout)
token = org_info['result']['accessToken']
instance_url = org_info['result']['instanceUrl']

lambda_client = boto3.client('lambda', region_name='us-west-2')
lambda_client.update_function_configuration(
    FunctionName='salesforce-ai-search-schema-discovery',
    Environment={
        'Variables': {
            'SALESFORCE_INSTANCE_URL': instance_url,
            'SCHEMA_CACHE_TABLE': 'salesforce-ai-search-schema-cache',
            'SALESFORCE_ACCESS_TOKEN': token,
            'LOG_LEVEL': 'INFO'
        }
    }
)
print(f"Token updated: {len(token)} chars")
EOF

python3 /tmp/refresh_token.py
```

**Then invoke schema discovery:**

```bash
aws lambda invoke \
  --function-name salesforce-ai-search-schema-discovery \
  --payload '{"action": "discover_all"}' \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/out.json && cat /tmp/out.json
```

---

## Follow-up Recommendations

### Immediate (P1)
1. **Increase cross-object timeout** - Current 2000ms is too tight for 18+ property traversals
2. **Add CloudWatch alarm** - Alert when schema cache item count < 8

### Short-term (P1)
3. **Task 46: OAuth Client Credentials** - Eliminate manual token refresh

### Medium-term (P2)
4. **Optimize graph edge queries** - Current implementation scans too many edges
5. **Consider edge caching** - Cache common Property→Lease relationships

---

## Test Commands

```bash
# Test simple query
python3 /tmp/test_api.py "show me class a office properties in plano"

# Test temporal query
python3 /tmp/test_api.py "show me leases expiring in the next 6 months"

# Test cross-object (currently failing)
python3 /tmp/test_api.py "show me leases on properties in plano"

# Check schema cache
aws dynamodb scan --table-name salesforce-ai-search-schema-cache \
  --region us-west-2 --projection-expression "objectApiName" --select COUNT
```

---

## Files Created

- `/tmp/update_lambda_env.py` - Token refresh script
- `/tmp/test_api.py` - Query test script

---

## Key Learnings

1. **Shell escaping with `!`**: AWS CLI `--environment` flag escapes `!` to `\!`. Use boto3 SDK instead.

2. **Token refresh sequence**:
   - Update Lambda config (forces cold start)
   - Wait for config propagation
   - Invoke schema discovery

3. **Cross-object timeout separate from schema**: Graph traversal has its own timeout budget (2000ms) independent of schema cache.

---

*Handoff created: 2025-12-15 11:45 UTC*
*Next session: Consider increasing CROSS_OBJECT_TIMEOUT_MS or optimizing graph edge queries*
