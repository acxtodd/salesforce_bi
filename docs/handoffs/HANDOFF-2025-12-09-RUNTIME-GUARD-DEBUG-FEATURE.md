# Handoff: Runtime Guard & Debug Feature Implementation

**Date:** 2025-12-09
**Status:** COMPLETE
**Session Focus:** Gap 2 (Runtime Guard) + Debug Feature for Query Intent Visibility

---

## Executive Summary

This session implemented QA's recommendation for a runtime guard to detect missing required fields after enrichment, added the Deal schema to the cache (was missing), and deployed a debug feature to the Answer Lambda that shows query intent/decomposition in the UI when `debug: true` is passed.

---

## Accomplishments

### 1. Runtime Guard for Missing Fields (Gap 2)

**Files Modified:**
- `lambda/retrieve/index.py` (lines 1415-1525, 3121, 3326-3333, 3587-3597)

**What Was Added:**
```python
REQUIRED_FIELDS_CONTRACT = {
    "ascendix__Availability__c": {
        "fields": ["propertyClass", "propertyType", "propertyCity", "propertyState", "propertyName"],
        "source": "enrichment",
    },
    "ascendix__Deal__c": {
        "fields": ["propertyClass", "propertyType", "propertyCity", "propertyState", "propertyName"],
        "source": "enrichment",
    },
    # ... similar for Lease and Property
}

def _validate_required_fields(matches, enrichment_attempted=False):
    """Validate that matches have required fields per object type."""
    # Logs [FIELD_CONTRACT] messages for missing fields
    # Returns validation summary for trace output
```

**Benefits:**
- Logs `[FIELD_CONTRACT]` warnings when matches are missing required fields
- Adds `fieldValidation` to trace output for observability
- Helps debug why LLM gives "I don't have enough information" responses

### 2. Deal Schema Added to Cache

**Issue:** Schema decomposer was logging "No schema available for ascendix__Deal__c" because Deal wasn't in the DynamoDB schema cache.

**Fix:** Manually added Deal schema to `salesforce-ai-search-schema-cache` table:
```bash
aws dynamodb put-item --table-name salesforce-ai-search-schema-cache --item '{
  "objectApiName": {"S": "ascendix__Deal__c"},
  "schema": {"M": {
    "filterable": [
      {"name": "ascendix__Status__c", "values": ["Open", "Won", "Lost"]},
      {"name": "ascendix__SalesStage__c", "values": [...]},
      {"name": "ascendix__PropertyType__c", "values": [...]},
      {"name": "ascendix__GrossFeeAmount__c", "type": "numeric"}
    ],
    "relationships": [
      {"name": "ascendix__Property__c"},
      {"name": "ascendix__Availability__c"},
      {"name": "ascendix__Client__c"}
    ]
  }}
}'
```

### 3. Debug Feature for Query Intent

**Files Modified:**
- `lambda/answer/main.py` (lines 181-207)

**What Was Added:**
When `"debug": true` is passed in the request, a `debug` SSE event is emitted FIRST, before any tokens:

```json
event: debug
data: {
  "schemaDecomposition": {
    "target_entity": "ascendix__Property__c",
    "filters": {"RecordType": "Office"},
    "confidence": 0.9
  },
  "intentClassification": {...},
  "planner": {
    "targetObject": "...",
    "predicates": [...],
    "confidence": 0.35
  },
  "aggregation": {"viewUsed": "vacancy_view", "recordCount": 5},
  "matchCount": 5
}
```

**Usage:**
```bash
curl -X POST 'https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: YOUR_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"query": "office properties", "salesforceUserId": "...", "debug": true}'
```

**Important:** Use the Docker Lambda URL (`sdrr5l3w2lqalqiylze6e35nfq0xhlxx`), NOT the API Gateway URL (`v2zweox56y5r6sdvlxnif3gzea0ffqow`).

---

## Issues Discovered

### 1. API Gateway URL Returns `{"Message":null}`

The URL `https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer` returns `{"Message":null}` for all requests. This appears to be a misconfigured endpoint.

**Correct URL:** `https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer`

### 2. Answer Lambda Has Two Implementations

The Answer Lambda has both:
- `index.py` - Original Lambda handler (streaming via Lambda response_stream)
- `main.py` - FastAPI/uvicorn handler (used by Docker container)

The debug feature was initially only added to `index.py`. Had to add it to `main.py` as well since that's what the Docker container uses.

### 3. Retrieve Lambda Timeout (35s)

Complex queries like "show deals for class a office properties in dallas" can timeout the Retrieve Lambda (35s limit). This is documented but worth noting.

### 4. Entity Detection Still Favors Property

For queries like "show deals for class a office properties in dallas":
- "office" matches Property patterns
- "properties" matches Property patterns
- "class a" matches Property patterns
- "deals" matches Deal patterns

Result: Property wins (3 matches) over Deal (2 matches). The relationship patterns added earlier help but don't fully solve this.

---

## Deployment Summary

| Component | Action | Status |
|-----------|--------|--------|
| Retrieve Lambda | Deployed with runtime guard | ✅ Live |
| Answer Lambda (Docker) | Deployed with debug feature | ✅ Live (image answer-v4) |
| Deal Schema | Added to DynamoDB cache | ✅ Live |

---

## Open Items

### P0 - Blocking

| Item | Description | Owner |
|------|-------------|-------|
| Task 32 | Add RecordType.Name to IndexConfiguration | Pending |
| RecordType Missing | Graph nodes have 0 RecordType attributes | Blocked by Task 32 |

### P1 - Important

| Item | Description | Owner |
|------|-------------|-------|
| Task 34 | Schema-driven export integration | Not Started |
| Entity Detection | Improve Deal vs Property detection | Enhancement |

### P2 - Nice to Have

| Item | Description | Owner |
|------|-------------|-------|
| API Gateway URL | Investigate why v2zw... URL returns null | DevOps |
| Schema Cache Sync | Auto-sync Deal schema from Salesforce | Enhancement |

---

## Test Commands

### Test Runtime Guard
```bash
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 5m --region us-west-2 | grep FIELD_CONTRACT
```

### Test Debug Feature
```bash
curl -s -X POST 'https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d '{"query": "office properties", "salesforceUserId": "005dl00000Q6a3RAAR", "debug": true}' | head -5
```

Expected output should start with `event: debug`.

### Test Deal Query
```bash
aws lambda invoke --function-name salesforce-ai-search-retrieve --region us-west-2 \
  --payload '{"query": "show deals for class a office properties", "salesforceUserId": "005dl00000Q6a3RAAR"}' \
  --cli-binary-format raw-in-base64-out /tmp/result.json && \
  python3 -c "import json; d=json.load(open('/tmp/result.json')); b=json.loads(d['body']); print('Matches:', len(b.get('matches',[])), 'Entity:', b.get('queryPlan',{}).get('schemaDecomposition',{}).get('target_entity'))"
```

---

## Related Files

| File | Purpose |
|------|---------|
| `lambda/retrieve/index.py` | Runtime guard implementation |
| `lambda/answer/main.py` | Debug feature (FastAPI handler) |
| `lambda/answer/index.py` | Debug feature (Lambda handler) |
| `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md` | Task tracking |

---

## Next Session Recommendations

1. **Complete Task 32** - Add RecordType.Name to IndexConfiguration and re-ingest
2. **Verify Deal Queries** - After Task 32, test "show deals for office properties in dallas"
3. **Investigate API Gateway URL** - Why does v2zw... return null?
4. **Consider Task 34** - Architectural fix to prevent future field mismatches
