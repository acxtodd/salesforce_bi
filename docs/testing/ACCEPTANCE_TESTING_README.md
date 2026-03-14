# Acceptance Testing - Complete Guide

## Overview

This directory contains all documentation and scripts for conducting comprehensive acceptance testing of the Salesforce AI Search POC. The acceptance testing validates that the system meets all requirements and is ready for production deployment.

## Testing Components

### 1. Curated Query Test Set
**Document:** [ACCEPTANCE_TEST_QUERIES.md](./ACCEPTANCE_TEST_QUERIES.md)  
**Script:** `scripts/run_acceptance_tests.py`

Defines 20 curated test queries covering:
- Single-object queries (Accounts, Opportunities, Cases, Properties, Leases)
- Multi-object queries (cross-entity relationships)
- Edge cases (no results, ambiguous queries, complex relationships)

**Target:** Precision@5 ≥70% on curated set

**Usage:**
```bash
# Run all curated queries
python scripts/run_acceptance_tests.py \
  --api-url https://your-api-gateway.amazonaws.com \
  --api-key YOUR_API_KEY \
  --output results/acceptance_test_results.json

# Run specific query
python scripts/run_acceptance_tests.py \
  --api-url https://your-api-gateway.amazonaws.com \
  --api-key YOUR_API_KEY \
  --query-id Q6 \
  --verbose

# Run with specific user context
python scripts/run_acceptance_tests.py \
  --api-url https://your-api-gateway.amazonaws.com \
  --api-key YOUR_API_KEY \
  --user-id 005xx1 \
  --verbose
```

---

### 2. Precision and Recall Evaluation
**Script:** `scripts/evaluate_precision_recall.py`

Measures retrieval quality metrics:
- Precision@1, @3, @5, @10
- Recall@5, @10
- NDCG@5, @10
- Mean Reciprocal Rank (MRR)

**Target:** Mean Precision@5 ≥70%

**Usage:**
```bash
# Evaluate with default ground truth
python scripts/evaluate_precision_recall.py \
  --results results/acceptance_test_results.json \
  --output results/precision_recall_evaluation.json

# Evaluate with custom ground truth
python scripts/evaluate_precision_recall.py \
  --results results/acceptance_test_results.json \
  --ground-truth data/ground_truth.json \
  --output results/precision_recall_evaluation.json \
  --verbose
```

---

### 3. Security Red Team Testing
**Document:** [SECURITY_RED_TEAM_TESTS.md](./SECURITY_RED_TEAM_TESTS.md)  
**Script:** `scripts/run_security_tests.py`

Tests security controls:
- **Row-Level Security:** Sharing rules, territory access, role hierarchy
- **Field-Level Security:** FLS enforcement, redacted chunks
- **Prompt Injection:** Authorization bypass attempts, jailbreaks
- **Data Leakage:** Metadata, error messages, timing attacks

**Target:** Zero authorization leaks, zero successful attacks

**Usage:**
```bash
# Run all security tests
python scripts/run_security_tests.py \
  --api-url https://your-api-gateway.amazonaws.com \
  --api-key YOUR_API_KEY \
  --output results/security_test_results.json

# Run specific category
python scripts/run_security_tests.py \
  --api-url https://your-api-gateway.amazonaws.com \
  --api-key YOUR_API_KEY \
  --category authorization \
  --verbose

# Run specific test
python scripts/run_security_tests.py \
  --api-url https://your-api-gateway.amazonaws.com \
  --api-key YOUR_API_KEY \
  --test-id 1.1 \
  --verbose

# Run with specific test users
python scripts/run_security_tests.py \
  --api-url https://your-api-gateway.amazonaws.com \
  --api-key YOUR_API_KEY \
  --users 005xx1,005xx2,005xx3
```

---

### 4. Performance Measurement
**Script:** `scripts/measure_performance.py`

Measures system performance:
- **First Token Latency:** p50, p95, p99
- **End-to-End Latency:** p50, p95, p99
- **CDC Freshness Lag:** p50, p95 (optional)
- **Throughput:** Requests per second
- **Success Rate:** Percentage of successful requests

**Targets:**
- p95 first token latency: ≤800ms
- p95 end-to-end latency: ≤4.0s
- CDC freshness lag P50: ≤5 minutes

**Usage:**
```bash
# Run sequential performance test
python scripts/measure_performance.py \
  --api-url https://your-api-gateway.amazonaws.com \
  --api-key YOUR_API_KEY \
  --iterations 50 \
  --output results/performance_metrics.json

# Run concurrent performance test
python scripts/measure_performance.py \
  --api-url https://your-api-gateway.amazonaws.com \
  --api-key YOUR_API_KEY \
  --iterations 100 \
  --concurrent 10 \
  --output results/performance_metrics.json

# Measure CDC freshness lag
python scripts/measure_performance.py \
  --api-url https://your-api-gateway.amazonaws.com \
  --api-key YOUR_API_KEY \
  --measure-cdc \
  --salesforce-url https://your-instance.salesforce.com \
  --salesforce-token YOUR_SF_TOKEN \
  --cdc-records "Opportunity/006xx1,Account/001xx2" \
  --verbose
```

---

### 5. User Acceptance Testing (UAT)
**Document:** [UAT_PLAN.md](./UAT_PLAN.md)  
**Script:** `scripts/analyze_uat_feedback.py`

Conducts structured UAT with 10-20 pilot users:
- **Phase 1:** Onboarding and training (2 days)
- **Phase 2:** Guided testing (3 days)
- **Phase 3:** Free-form testing (5 days)
- **Phase 4:** Feedback and wrap-up (2 days)

**Target:** ≥80% of users rate answers as "useful" or better

**Usage:**
```bash
# Analyze UAT feedback
python scripts/analyze_uat_feedback.py \
  --feedback data/uat_feedback.json \
  --output results/uat_report.json \
  --verbose
```

---

## Complete Testing Workflow

### Step 1: Prepare Test Environment
```bash
# Ensure API is deployed and accessible
# Load test data in Salesforce sandbox
# Create test users with different roles and permissions
# Configure API keys and credentials
```

### Step 2: Run Automated Tests
```bash
# 1. Run curated query tests
python scripts/run_acceptance_tests.py \
  --api-url $API_URL \
  --api-key $API_KEY \
  --output results/acceptance_test_results.json

# 2. Evaluate precision and recall
python scripts/evaluate_precision_recall.py \
  --results results/acceptance_test_results.json \
  --output results/precision_recall_evaluation.json

# 3. Run security tests
python scripts/run_security_tests.py \
  --api-url $API_URL \
  --api-key $API_KEY \
  --output results/security_test_results.json

# 4. Measure performance
python scripts/measure_performance.py \
  --api-url $API_URL \
  --api-key $API_KEY \
  --iterations 100 \
  --concurrent 10 \
  --output results/performance_metrics.json
```

### Step 3: Conduct UAT
```bash
# 1. Recruit 10-20 pilot users
# 2. Conduct kickoff and training
# 3. Monitor daily usage and collect feedback
# 4. Conduct interviews and retrospective
# 5. Analyze feedback

python scripts/analyze_uat_feedback.py \
  --feedback data/uat_feedback.json \
  --output results/uat_report.json
```

### Step 4: Generate Final Report
```bash
# Combine all test results into final acceptance report
# Review against success criteria
# Make go/no-go recommendation
```

---

## Success Criteria Summary

### Primary Criteria (Must Pass)
- ✓ **Precision@5:** ≥70% on curated query set
- ✓ **UAT Usefulness:** ≥80% of users rate answers as useful
- ✓ **Security:** Zero authorization leaks
- ✓ **Performance:** p95 first token ≤800ms, p95 end-to-end ≤4.0s

### Secondary Criteria (Should Pass)
- ✓ **Answer Quality:** ≥70% rated "Good" or "Excellent"
- ✓ **Relevance:** ≥75% rated "Very Relevant" or "Somewhat Relevant"
- ✓ **User Satisfaction:** ≥70% "Satisfied" or "Very Satisfied"
- ✓ **NPS:** ≥30
- ✓ **Adoption Intent:** ≥70% would use daily or more
- ✓ **Time Savings:** ≥60% report time savings
- ✓ **CDC Freshness:** P50 lag ≤5 minutes

---

## Test Data Requirements

### Salesforce Test Data
- **Accounts:** 10-15 accounts with varying attributes (region, revenue, industry)
- **Opportunities:** 20-30 opportunities across different stages and amounts
- **Cases:** 10-15 cases with varying priorities and statuses
- **Properties:** 5-10 properties with different types and locations
- **Leases:** 10-15 leases with varying statuses and dates
- **Contracts:** 5-10 contracts with different types
- **Notes:** 10-15 notes with relevant content

### Test Users
- **Sales Rep (005xx1):** Limited access, West Coast territory
- **Sales Manager (005xx2):** Elevated access, West Coast + EMEA
- **System Admin (005xx3):** Full access, all territories

---

## Results Directory Structure

```
results/
├── acceptance_test_results.json      # Curated query test results
├── precision_recall_evaluation.json  # Precision/recall metrics
├── security_test_results.json        # Security test results
├── performance_metrics.json          # Performance measurements
└── uat_report.json                   # UAT analysis report
```

---

## Troubleshooting

### Common Issues

**Issue:** Tests fail with authentication errors  
**Solution:** Verify API key is correct and has proper permissions

**Issue:** No results returned for queries  
**Solution:** Verify test data is loaded and indexed in OpenSearch

**Issue:** Authorization tests pass when they should fail  
**Solution:** Verify test users have correct roles and permissions

**Issue:** Performance tests show high latency  
**Solution:** Check Lambda provisioned concurrency, OpenSearch cluster health

**Issue:** UAT participants not providing feedback  
**Solution:** Send reminders, offer incentives, simplify feedback forms

---

## Next Steps After Testing

### If All Criteria Met
1. Address any non-critical issues identified
2. Implement high-priority improvements
3. Prepare production deployment plan
4. Develop user training materials
5. Plan phased rollout

### If Criteria Not Met
1. Conduct root cause analysis
2. Prioritize fixes based on impact
3. Implement improvements
4. Re-run failed tests
5. Consider second UAT round if needed

---

## Support

For questions or issues with acceptance testing:
- **Technical Issues:** Contact technical lead
- **Test Data:** Contact data team
- **UAT Coordination:** Contact product manager
- **Results Analysis:** Contact data analyst

---

## References

- [Requirements Document](../.kiro/specs/salesforce-ai-search-poc/requirements.md)
- [Design Document](../.kiro/specs/salesforce-ai-search-poc/design.md)
- [Tasks Document](../.kiro/specs/salesforce-ai-search-poc/tasks.md)
- [Deployment Guide](../DEPLOYMENT.md)
