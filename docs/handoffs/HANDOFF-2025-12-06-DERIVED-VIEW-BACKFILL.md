# Handoff: Derived View Backfill & Honest Assessment

**Date:** 2025-12-06
**Session Focus:** Execute QA remediation plan - backfill derived views, run honest tests, create runbooks
**Status:** COMPLETE (with findings)

---

## Summary

Addressed QA analyst concerns about synthetic data and test validity. Successfully backfilled derived views with real Salesforce data and documented honest assessment of system capabilities.

---

## Accomplishments

### 1. Salesforce Token Refresh

**Problem:** SSM token `/salesforce/access_token` was expired (401 Unauthorized)

**Solution:** Used SF CLI to get fresh token from `ascendix-beta-sandbox` org:
```bash
sf org display --target-org ascendix-beta-sandbox --json | jq -r '.result.accessToken'
aws ssm put-parameter --name /salesforce/access_token --value "$TOKEN" --type SecureString --overwrite
```

### 2. Derived View Backfill

Successfully populated all three derived view tables with real Salesforce data:

| Table | Records | Source |
|-------|---------|--------|
| `salesforce-ai-search-availability-view` | 527 | ascendix__Availability__c |
| `salesforce-ai-search-vacancy-view` | 2,466 | ascendix__Property__c |
| `salesforce-ai-search-leases-view` | 483 | ascendix__Lease__c |

**Script:** `/tmp/backfill_correct_keys.py` - uses SF CLI for SOQL queries

**Key Schema Discovery:**
- `availability-view`: `property_id` (HASH), `availability_id` (RANGE)
- `vacancy-view`: `property_id` (HASH only)
- `leases-view`: `property_id` (HASH), `lease_id` (RANGE)

**Field Mapping (this org vs expected):**
- `ascendix__AvailableArea__c` → size (not `ascendix__Size__c`)
- `ascendix__TermExpirationDate__c` → end_date (not `ascendix__EndDate__c`)

### 3. Honest Acceptance Tests

Ran real API tests against production endpoint. Results documented in `docs/reports/ACCEPTANCE_TEST_HONEST_2025-12-06.md`.

| Category | Count | Notes |
|----------|-------|-------|
| PASS | 4 | Location queries (Alpharetta, Arizona, Dallas, Plano) |
| FAIL (Architecture) | 4 | Derived views populated but not queried |
| FAIL (Data Quality) | 2 | PropertyClass 5% populated |

**Honest Pass Rate: 36%**

### 4. Task 28.4 Runbooks

Created `docs/runbooks/RUNBOOK-CANARY-OPERATIONS.md` covering:
- Rollback toggle procedures
- Schema diff handling
- KB/Index health monitoring
- Data quality checks
- Emergency procedures

### 5. SLA Change Request

Created `docs/reports/SLA_REVISION_REQUEST_2025-12-06.md`:
- Current target: 1,500ms p95
- Proposed target: 5,000ms p95
- Evidence: Simple queries ~3-5s, complex queries ~6-10s

### 6. Security Verification

| Component | Status |
|-----------|--------|
| Answer Function URL | `AuthType: NONE` but app-level API key validation enforced |
| Ingest Function URL | DELETED (was public) |
| API Gateway | Private with API key |

---

## Key Finding: Architecture Gap

**Derived views are populated but NOT queried by the RAG system.**

The current flow:
```
User Query → Intent → Bedrock KB (S3 chunks) → Answer
```

The derived views (DynamoDB) are designed for:
- CDC event processing
- Planner-directed aggregation queries
- Graph traversal path

But the planner isn't routing queries to them:
- `plannerMs: 0` in traces
- Confidence thresholds not met for derived view routing

**Implication:** Even with real data in DynamoDB, queries like "leases expiring soon" return "no information" because they only search the Bedrock KB.

---

## What Works (Verified)

```bash
# Location-based queries return real citations
"find properties in Alpharetta Georgia" → 2 citations (850 Mayfield Rd, 1605 Mansell Rd)
"find properties in Arizona" → 4 citations
"find properties in Dallas Texas" → 5 citations
"find properties in Plano Texas" → 5 citations
```

## What Doesn't Work (Architecture Gap)

```bash
# Derived view queries return "no information"
"show me leases expiring soon" → no_accessible_results
"properties with vacancy rate > 25%" → no_accessible_results
"contacts with 5+ activities" → no_accessible_results (activities-agg also empty)
```

---

## Files Created/Modified

| File | Description |
|------|-------------|
| `docs/reports/ACCEPTANCE_TEST_HONEST_2025-12-06.md` | Honest test results with real data |
| `docs/runbooks/RUNBOOK-CANARY-OPERATIONS.md` | Task 28.4 operational runbooks |
| `docs/reports/SLA_REVISION_REQUEST_2025-12-06.md` | Latency SLA change evidence |
| `/tmp/backfill_correct_keys.py` | Backfill script using SF CLI |

---

## DynamoDB Table Counts (After Backfill)

```bash
salesforce-ai-search-availability-view: 527 items
salesforce-ai-search-vacancy-view: 2466 items
salesforce-ai-search-leases-view: 483 items
salesforce-ai-search-activities-agg: 0 items (no Task/Event data in SF org)
salesforce-ai-search-sales-view: 0 items (not backfilled - no Sale object)
```

---

## Recommendations

### Immediate (POC Scope)

1. **De-scope derived view scenarios** from acceptance criteria
   - S4 (leases expiring), S6 (activity counts), S9 (vacancy rates)
   - These require architecture changes to query DynamoDB

2. **Approve SLA revision** - 1.5s → 5s p95 latency target

3. **Focus POC demo on location queries** - these work reliably

### Future (Production)

1. **Implement planner routing to derived views**
   - Add query patterns that trigger DynamoDB queries
   - Integrate derived view results into RAG response

2. **Sync with richer Salesforce org**
   - Current beta sandbox has sparse City/State/PropertyClass data
   - KB data came from different source with better coverage

3. **Add activities-agg backfill**
   - Requires Task/Event data in connected SF org

---

## Verification Commands

```bash
# Check derived view counts
for tbl in availability-view vacancy-view leases-view; do
  aws dynamodb scan --table-name salesforce-ai-search-$tbl --region us-west-2 --select COUNT
done

# Test API
curl -s -X POST 'https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d '{"query":"find properties in Texas","salesforceUserId":"005dl00000Q6a3RAAR","filters":{}}'

# Check SF CLI connection
sf data query --query "SELECT COUNT() FROM ascendix__Property__c" --target-org ascendix-beta-sandbox
```

---

## Next Steps

1. **POC Checkpoint Meeting** - Present honest assessment, get SLA approval
2. **Architecture Decision** - Whether to implement derived view query path
3. **Data Strategy** - Whether to sync with richer Salesforce data source

---

*This handoff documents real findings without synthetic data or auto-passes.*
