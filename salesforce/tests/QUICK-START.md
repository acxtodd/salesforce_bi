# Quick Start Guide - End-to-End Testing

## 🚀 Get Started in 5 Minutes

This guide helps you quickly verify the end-to-end flow from LWC to AWS and back.

---

## Prerequisites Check

Before starting, verify you have:

- [ ] Salesforce org with LWC deployed
- [ ] AWS infrastructure deployed and healthy
- [ ] Test user credentials
- [ ] Sample data loaded and indexed

**Not sure?** Run these quick checks:

```bash
# Check AWS infrastructure
aws cloudformation list-stacks --region us-east-1 --no-cli-pager | grep Ascendix

# Check Salesforce deployment
sfdx force:org:list
```

---

## Option 1: Quick Smoke Test (5 minutes)

**Best for**: First-time verification, quick sanity check

### Steps

1. **Login to Salesforce**
   - Navigate to your sandbox/org
   - Go to Home page or Account page

2. **Find AI Search Component**
   - Look for "Ascendix AI Search" component on the page
   - If not visible, check page layout configuration

3. **Submit Test Query**
   ```
   Query: "Show open opportunities"
   ```
   - Type the query in the text area
   - Click "Search" button

4. **Verify Response**
   - ✅ Loading spinner appears
   - ✅ Answer text streams progressively
   - ✅ Citations button appears (e.g., "View Citations (5)")
   - ✅ No errors in browser console (F12)

5. **Check Citations**
   - Click "View Citations" button
   - ✅ Drawer opens with citation list
   - Click a citation
   - ✅ Navigates to Salesforce record

**Result**: If all ✅ checks pass, basic functionality is working!

---

## Option 2: Automated Performance Test (15 minutes)

**Best for**: Performance validation, regression testing, CI/CD

### Setup (One-time)

```bash
# Navigate to tests directory
cd salesforce/tests

# Install dependencies
npm install
```

### Run Test

```bash
# Run automated test
node e2e-performance-test.js \
  --username=test@example.com \
  --password=YourPassword123 \
  --instanceUrl=https://test.salesforce.com
```

**Replace**:
- `test@example.com` with your test user email
- `YourPassword123` with your password
- `https://test.salesforce.com` with your org URL

### Watch Progress

The script will:
1. Login to Salesforce ✅
2. Navigate to AI Search component ✅
3. Run 20 test queries ⏱️
4. Measure performance for each query 📊
5. Generate reports 📄

### Review Results

**Console Output**:
```
Test 1/20: "Show open opportunities"
  ⏱️  First Token: 650ms
  ⏱️  End-to-End: 2100ms
  📚 Citations: 5
  ✅ PASS

...

📊 TEST SUMMARY
============================================================
Total Tests: 20
Passed: 19
Failed: 1
Pass Rate: 95.0%

First Token Latency:
  P50: 620ms
  P95: 780ms ✅ (Target: ≤800ms)
  P99: 850ms

End-to-End Latency:
  P50: 2200ms
  P95: 3800ms ✅ (Target: ≤4000ms)
  P99: 4200ms
============================================================

✅ ALL PERFORMANCE TARGETS MET
```

**HTML Report**:
```bash
# Open the HTML report
open test-results/reports/report-*.html
```

**Screenshots**:
```bash
# View screenshots
ls test-results/screenshots/
```

---

## Option 3: Comprehensive Manual Testing (2-3 hours)

**Best for**: Thorough validation, acceptance testing, first deployment

### Steps

1. **Open Test Plan**
   ```bash
   open e2e-test-plan.md
   ```

2. **Follow Test Suites**
   - Test Suite 1: Basic Query Submission (3 tests)
   - Test Suite 2: Streaming Display (2 tests)
   - Test Suite 3: Citations (4 tests)
   - Test Suite 4: Authorization (3 tests)
   - Test Suite 5: Error Handling (3 tests)
   - Test Suite 6: Performance (2 tests)
   - Test Suite 7: Accessibility (2 tests)
   - Test Suite 8: Multi-Turn (1 test)

3. **Record Results**
   - Use the templates in the test plan
   - Document any issues found
   - Take screenshots of failures

4. **Calculate Statistics**
   - Calculate p50, p95, p99 latencies
   - Determine pass/fail for each test
   - Calculate overall pass rate

---

## Performance Targets

Your tests should meet these targets:

| Metric | Target | Requirement |
|--------|--------|-------------|
| p95 First Token Latency | ≤800ms | Req 8.1 |
| p95 End-to-End Latency | ≤4.0s | Req 8.2 |
| Pass Rate | ≥90% | General |

---

## Troubleshooting

### ❌ Login Fails

**Symptoms**: Automated test can't login

**Quick Fixes**:
```bash
# Verify credentials work manually
sfdx auth:web:login -a test-org

# Check if API access is enabled
# Setup > Users > [Your User] > API Enabled checkbox
```

### ❌ Component Not Found

**Symptoms**: "AI Search component not found"

**Quick Fixes**:
1. Verify LWC is deployed:
   ```bash
   sfdx force:source:retrieve -m LightningComponentBundle:ascendixAiSearch -u test-org
   ```

2. Check page layout:
   - Setup > Lightning App Builder
   - Verify component is on Home page

### ❌ No Search Results

**Symptoms**: Queries return no results

**Quick Fixes**:
1. Check data is indexed:
   ```bash
   aws bedrock-agent list-knowledge-bases --region us-east-1 --no-cli-pager
   ```

2. Verify CDC pipeline is running:
   ```bash
   aws stepfunctions list-executions --state-machine-arn YOUR_STATE_MACHINE_ARN --region us-east-1 --no-cli-pager
   ```

3. Check Named Credential:
   - Setup > Named Credentials > Ascendix RAG API
   - Click "Test Connection"
   - Should return 200 OK

### ❌ Slow Performance

**Symptoms**: Latency exceeds targets

**Quick Fixes**:
1. Check Lambda provisioned concurrency:
   ```bash
   aws lambda get-provisioned-concurrency-config --function-name retrieve-lambda --region us-east-1 --no-cli-pager
   ```

2. Check OpenSearch cluster health:
   ```bash
   aws opensearch describe-domain --domain-name ascendix-ai-search --region us-east-1 --no-cli-pager
   ```

3. Review CloudWatch metrics:
   - Lambda duration
   - API Gateway latency
   - OpenSearch search latency

---

## Next Steps

### ✅ If Tests Pass

1. **Mark task complete** in tasks.md
2. **Archive test results** for future reference
3. **Proceed to next task** (Task 11: Observability)
4. **Set up automated tests** for continuous monitoring

### ❌ If Tests Fail

1. **Document failures** in detail
2. **Create bug reports** for each issue
3. **Prioritize fixes** (critical first)
4. **Fix and re-test**
5. **Do not proceed** until tests pass

---

## Getting Help

### Documentation
- **Test Plan**: `e2e-test-plan.md` - Detailed test cases
- **Checklist**: `TASK-10.4-CHECKLIST.md` - Execution guide
- **README**: `README.md` - Complete documentation
- **Summary**: `IMPLEMENTATION-SUMMARY.md` - What was created

### Logs
- **Browser Console**: F12 > Console tab
- **Salesforce Debug Logs**: Setup > Debug Logs
- **AWS CloudWatch**: CloudWatch > Log Groups
- **Network Tab**: F12 > Network tab

### Support
- Check `../DEPLOYMENT_GUIDE.md` for deployment issues
- Check `../README.md` for general information
- Review CloudWatch dashboards for AWS issues

---

## Quick Reference

### Test Commands

```bash
# Install dependencies
cd salesforce/tests && npm install

# Run automated test (interactive)
node e2e-performance-test.js --username=USER --password=PASS --instanceUrl=URL

# Run automated test (headless for CI)
node e2e-performance-test.js --username=USER --password=PASS --instanceUrl=URL --headless=true

# View results
open test-results/reports/report-*.html
```

### AWS Checks

```bash
# Check infrastructure
aws cloudformation list-stacks --region us-east-1 --no-cli-pager | grep Ascendix

# Check Lambda functions
aws lambda list-functions --region us-east-1 --no-cli-pager | grep -E "retrieve|answer|authz"

# Check OpenSearch
aws opensearch describe-domain --domain-name ascendix-ai-search --region us-east-1 --no-cli-pager

# Check Bedrock KB
aws bedrock-agent list-knowledge-bases --region us-east-1 --no-cli-pager
```

### Salesforce Checks

```bash
# List orgs
sfdx force:org:list

# Check deployment
sfdx force:source:retrieve -m LightningComponentBundle:ascendixAiSearch -u test-org

# Tail debug logs
sfdx force:apex:log:tail -u test-org
```

---

## Success Checklist

- [ ] Smoke test passed (5 minutes)
- [ ] Automated test passed (15 minutes)
- [ ] Performance targets met (p95 ≤800ms, ≤4.0s)
- [ ] No security leaks (sharing rules enforced)
- [ ] No console errors
- [ ] Citations work correctly
- [ ] Results documented
- [ ] Ready to proceed to next task

---

**Need more details?** See the full documentation in `README.md` or `e2e-test-plan.md`.

**Ready to start?** Pick an option above and begin testing! 🚀
