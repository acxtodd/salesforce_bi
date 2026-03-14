# Handoff Document: Security Hardening & Acceptance Tests

**Date:** 2025-12-05
**Session Focus:** Task 23 (Security Hardening) & Task 25 (Acceptance Tests)
**Status:** Partially Complete - Blocked on Data Re-Index

---

## Summary

Completed security hardening (Task 23) and created acceptance test suite (Task 25), but acceptance tests are failing due to stale/missing data in the knowledge base.

---

## What Was Done

### Task 23: Security Hardening ✅

| Sub-Task | Status | Details |
|----------|--------|---------|
| **23.1** Remove public Function URLs | **DEFERRED** | User decision - needed for streaming. Documented risks in `api-stack.ts:457-473` |
| **23.2** API key authentication | ✅ Complete | Verified existing `apiKeyRequired: true` on all API Gateway endpoints |
| **23.3** AOSS CMK encryption | **DEFERRED** | AWS limitation - encryption key cannot be changed after collection creation. Documented in `search-stack.ts:122-148` |
| **23.4** Scope IAM policies | ✅ Complete | Documented CDK ordering constraint. Removed root principal from AOSS access policy (`search-stack.ts:182-227`) |
| **23.5** Security tests | ✅ Complete | Added 7 new tests to `scripts/run_security_tests.py` |

### QA Findings Resolution ✅

| Finding | Issue | Resolution |
|---------|-------|------------|
| **QA-1** | Public Function URL (authType:NONE) | **DEFERRED** - Documented risks, app-level API key validation |
| **QA-2** | API Gateway REGIONAL (internet-facing) | **DOCUMENTED** - Required for SF Named Credential (Private Connect not available for POC) |
| **QA-3** | API key check fail-open | **FIXED** - `lambda/answer/main.py` now fails closed with `ApiKeyError` |
| **QA-4** | Root principal in AOSS access policy | **FIXED** - Removed from `search-stack.ts` |
| **QA-5** | No test evidence | **COMPLETED** - Security tests run, results in `results/security_test_results.json` |

### Task 25: Acceptance Tests - Partial ⚠️

| Sub-Task | Status | Details |
|----------|--------|---------|
| **25.1** Create acceptance test suite | ✅ Complete | `test_automation/graph_zero_config_acceptance.py` |
| **25.2-25.4** Implement scenarios | ✅ Complete | 12 scenarios (S1-S12) covering Req 14.1-14.10 |
| **25.5** Run tests | ⚠️ Failing | 25% pass rate, 100% empty citation rate |
| **25.6** Document results | Pending | Blocked on re-index |

---

## Deployments Made

```bash
# Both stacks deployed successfully on 2025-12-05
npx cdk deploy SalesforceAISearch-Search-dev  # AOSS policy fix
npx cdk deploy SalesforceAISearch-Api-dev     # Answer Lambda fail-closed fix
```

### Files Modified

| File | Changes |
|------|---------|
| `lib/search-stack.ts` | CMK deferral docs (L122-148), IAM policy docs (L60-65, L93-96), removed root principal (L218-223) |
| `lib/api-stack.ts` | Function URL security docs (L457-473), API Gateway REGIONAL docs (L526-554) |
| `lambda/answer/main.py` | Added `ApiKeyError` class, fail-closed API key validation (L35-111) |
| `scripts/run_security_tests.py` | Added API key tests (0.1-0.3), graph traversal tests (5.1-5.4) |
| `test_automation/graph_zero_config_acceptance.py` | **NEW** - 12 acceptance scenarios |
| `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md` | Updated Task 23, 24 status with QA findings |

---

## Open Challenges

### 1. Acceptance Tests Failing (100% Empty Rate)

**Symptoms:**
- All 12 acceptance scenarios return 0 citations
- Answer Lambda responds but knowledge base returns empty results
- Some queries time out (~7600ms), others are fast (~160ms)

**Root Cause (Likely):**
The graph data is stale. Per the 2025-12-02 handoff, the zero-config fixes were applied but **no full re-index was run**. The graph nodes are missing critical attributes (City, State, RecordType) needed for cross-object queries.

**Evidence:**
```
Pass Rate: 25% (3/12) - Target: ≥75%
Empty Rate: 100% - Target: <8%
P95 Latency: 7622ms - Target: <1500ms
```

### 2. AOSS CMK Encryption Deferred

Cannot change encryption from AWS-owned key to CMK on existing collection. Migration requires:
1. Create new collection with CMK encryption policy
2. Recreate Bedrock Knowledge Base
3. Full re-index of all data

**Decision:** Deferred to post-POC due to complexity. Data is still encrypted at rest (just with AWS-owned key).

### 3. Public Function URL (Streaming)

The Answer Lambda Function URL is public (`authType: NONE`) to enable streaming responses to LWC. This bypasses API Gateway API key enforcement.

**Mitigations in place:**
- Application-level API key validation (fail-closed)
- Documented in code with TODO markers

**Production solution:** CloudFront + OAC or WebSocket API Gateway

---

## Security Test Results

```
API Key Tests: 3/3 PASS
- 0.1 Missing API Key: 403 ✓
- 0.2 Invalid API Key: 403 ✓
- 0.3 Missing User ID: 400 ✓

Results: results/security_test_results.json
```

---

## Proposed Next Steps

### Immediate (P0)

1. **Trigger Full Re-Index**
   ```bash
   # In Salesforce, run batch export for all CRE objects
   sf apex run --target-org ascendix-beta-sandbox <<'EOF'
   Database.executeBatch(new AISearchBatchExport('ascendix__Property__c', 100000), 50);
   EOF

   # Wait for completion, then index child objects
   Database.executeBatch(new AISearchBatchExport('ascendix__Availability__c', 100000), 50);
   Database.executeBatch(new AISearchBatchExport('ascendix__Deal__c', 100000), 50);
   Database.executeBatch(new AISearchBatchExport('ascendix__Lease__c', 100000), 50);
   ```

2. **Re-run Acceptance Tests**
   ```bash
   python3 test_automation/graph_zero_config_acceptance.py --verbose
   ```

3. **Run Full Security Test Suite**
   ```bash
   python3 scripts/run_security_tests.py \
     --api-url "https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod" \
     --api-key "M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ" \
     --verbose
   ```

### After Re-Index (P1)

4. **Task 26: Performance Tuning** (if acceptance tests pass)
   - Profile planner latency (target: p95 ≤500ms)
   - Optimize traversal (target: p95 ≤400ms)
   - Tune overall retrieval (target: p95 ≤1500ms)

5. **Task 28: Canary Deployment**
   - Shadow logging
   - 20% traffic rollout
   - 100% traffic rollout

### Post-POC (P2)

6. **AOSS CMK Migration** - Create new collection with CMK, migrate data
7. **Function URL Security** - Implement CloudFront + OAC for streaming
8. **Private API Gateway** - If Salesforce Private Connect becomes available

---

## Key Files Reference

| Purpose | Location |
|---------|----------|
| Security tests | `scripts/run_security_tests.py` |
| Acceptance tests | `test_automation/graph_zero_config_acceptance.py` |
| Answer Lambda (fixed) | `lambda/answer/main.py` |
| Search stack (AOSS policy) | `lib/search-stack.ts` |
| API stack (docs) | `lib/api-stack.ts` |
| Task tracking | `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md` |
| Security test results | `results/security_test_results.json` |
| Acceptance test results | `results/graph_zero_config_acceptance.json` |

---

## Environment Info

- **AWS Region:** us-west-2
- **API Gateway:** https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/
- **Function URL:** https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/
- **Knowledge Base ID:** HOOACWECEX
- **AOSS Collection:** salesforce-ai-search (1zmrlod7vi7veq9r5v56)
- **Test User ID:** 005dl00000Q6a3RAAR

---

## Research Notes

### AOSS Encryption Limitation
> "You can't change the encryption key for a collection after the collection is created."
> — [AWS Documentation](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-encryption.html)

### Salesforce IP Allowlisting
> "Hyperforce IPs aren't published, and allowlisting isn't supported."
> — [Salesforce Stack Exchange](https://salesforce.stackexchange.com/questions/416718/working-around-ip-whitelisting-with-hyperforce)

This means IP-based restrictions for API Gateway are not viable for Salesforce integrations on Hyperforce.

---

**Next Session Priority:** Run full re-index, then re-run acceptance tests to validate the system.
