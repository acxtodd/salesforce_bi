# Go/No-Go Decision: AscendixIQ AI Search POC

**Date:** 2026-03-20
**Author:** Todd Terry
**Status:** CONDITIONAL GO

---

## 1. Acceptance Test Results

| Metric | Value |
|--------|-------|
| Total tests | 652 |
| Passed | 652 |
| Failed | 0 |
| Skipped | 1 |
| Pass rate | **100%** |

Test coverage spans: tool dispatch (field resolution, semantic aliases, aggregation sorting), system prompt (static + dynamic builder, 11-object scope, leaderboard guards, clarification markers, help guidelines), query handler (citation extraction, clarification parsing), and LWC (answer formatting, table rendering, clarification pills).

## 2. Cost Comparison

| Component | AI Search (new) | Legacy Graph (current) |
|-----------|----------------|----------------------|
| LLM (Bedrock Haiku + Sonnet) | $127/mo | N/A |
| Lambda (query + CDC sync) | $37/mo | included below |
| AppFlow + S3 + ECR | $5/mo | N/A |
| Turbopuffer (vector store) | ~$5/mo | N/A |
| OpenSearch | decomm | $1,024/mo |
| Neptune | decomm | $147/mo |
| ELB + Step Functions | decomm | $16/mo |
| **Total** | **$177/mo** | **$1,187/mo** |

- **Target budget:** $200/mo for 1 org
- **Projected:** $177/mo (within budget)
- **Steady-state estimate:** $80-90/mo (excluding bulk-load spikes)
- **Net savings on legacy decommission:** ~$1,010/mo

Measurement window: 7 days, 123 user queries, 10,000 indexed documents across 11 object types.

## 3. Unresolved Items

| # | Item | Severity | Plan |
|---|------|----------|------|
| 1 | Account/Contact CDC blocked by sandbox entity limit (sf_devops consumes 5/5 slots) | Medium | Workaround: poll sync + bulk load. Root fix: uninstall DevOps Center or use production org (higher limits) |
| 2 | CDC Lambda SSM token expires — no auto-refresh | Low | Token refreshed manually. Production: use JWT bearer flow for auto-renewable tokens |
| 3 | Record context not passed from LWC to Lambda (task 3.6) | Low | Deferred to Phase 4. Queries work without it; contextual queries get a clarification prompt |
| 4 | Ascendix Search config refresh pipeline not built (task 4.9) | Medium | Manual bulk reload for now. 4.9 tracks full automation |
| 5 | Turbopuffer billing not API-accessible from current key | Low | Dashboard-only. Costs are within free tier at 10K vectors |

## 4. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM cost spike on high query volume | Low | Medium | Haiku is the primary model; cost scales linearly at ~$0.10/query. 200 queries/day = ~$6/day |
| Fabricated rankings from ambiguous queries | Low (mitigated) | High | Prompt guardrails + sort_order/top_n backend enforcement + CLARIFY marker UX deployed |
| Stale index data | Medium | Medium | CDC active for 5 Ascendix objects; poll sync for others; bulk reload available |
| Token/auth failures on CDC path | Medium | Low | Manual refresh documented; production JWT flow eliminates this |

## 5. Recommendation: CONDITIONAL GO

**Proceed to production planning** with the following conditions:

1. **Before production deploy:** Implement JWT bearer flow for Lambda-to-Salesforce auth (eliminates manual token refresh)
2. **Before production deploy:** Verify CDC entity allocation on production org (typically higher than sandbox)
3. **Accepted for v1:** Poll sync covers Account/Contact until CDC entity limit is resolved
4. **Accepted for v1:** Manual Ascendix Search config refresh (task 4.9 deferred to v1.1)

## 6. Phase 5 Production Cutover Outline

1. **Pre-cutover (1 week)**
   - Provision production Turbopuffer namespace
   - Deploy CDK stacks to production account
   - Configure JWT bearer auth for Lambda-to-Salesforce
   - Run bulk load against production org
   - Validate query quality against production data

2. **Cutover day**
   - Deploy Salesforce metadata (LWC + Apex + Named Credential) to production
   - Activate CDC flows for production org
   - Smoke test: 10 representative queries from UAT script
   - Enable for pilot user group

3. **Post-cutover (2 weeks)**
   - Monitor cost, latency, and error rates via CloudWatch
   - Collect user feedback
   - Schedule legacy graph system decommission after 30-day parallel run

4. **Decommission legacy (30 days post-cutover)**
   - Remove OpenSearch domain
   - Remove Neptune cluster
   - Remove legacy Lambda functions (retrieve, answer-docker)
   - Projected savings: ~$1,010/mo
