# End-to-End Testing for Ascendix AI Search

This directory contains end-to-end tests for the Ascendix AI Search Lightning Web Component.

## Test Files

### 1. e2e-test-plan.md
Comprehensive manual test plan covering:
- Basic query submission
- Streaming response display
- Citations display and navigation
- Authorization and security
- Error handling
- Performance measurement
- Accessibility
- Multi-turn conversations

**Use this for**: Manual testing, QA validation, acceptance testing

### 2. e2e-performance-test.js
Automated performance test script using Puppeteer to:
- Submit 20 test queries automatically
- Measure first token latency
- Measure end-to-end latency
- Calculate p50, p95, p99 statistics
- Generate HTML and JSON reports
- Take screenshots of each test

**Use this for**: Automated performance testing, CI/CD integration, regression testing

## Prerequisites

### For Manual Testing (e2e-test-plan.md)
- Salesforce org with LWC deployed
- Test users with different permission levels
- Sample data loaded and indexed
- Browser with developer tools

### For Automated Testing (e2e-performance-test.js)
- Node.js 16+ installed
- Salesforce org with LWC deployed
- Test user credentials
- npm dependencies installed

## Setup

### Install Dependencies

```bash
cd salesforce/tests
npm install
```

This will install:
- `puppeteer` - Headless browser automation

## Running Manual Tests

1. Open `e2e-test-plan.md`
2. Follow the test cases in order
3. Record results in the document
4. Calculate summary statistics
5. Document any issues found

## Running Automated Performance Tests

### Basic Usage

```bash
node e2e-performance-test.js \
  --username=test@example.com \
  --password=YourPassword123 \
  --instanceUrl=https://test.salesforce.com
```

### Headless Mode (for CI/CD)

```bash
node e2e-performance-test.js \
  --username=test@example.com \
  --password=YourPassword123 \
  --instanceUrl=https://test.salesforce.com \
  --headless=true
```

### Using npm Scripts

```bash
# Interactive mode (browser visible)
npm test -- --username=test@example.com --password=YourPassword123 --instanceUrl=https://test.salesforce.com

# Headless mode
npm run test:headless -- --username=test@example.com --password=YourPassword123 --instanceUrl=https://test.salesforce.com
```

## Test Output

### Console Output
The script provides real-time console output showing:
- Login status
- Navigation status
- Each query being tested
- First token and end-to-end latency for each query
- Pass/fail status for each query
- Summary statistics (p50, p95, p99)
- Overall pass/fail against targets

Example:
```
🚀 Starting End-to-End Performance Tests...

🔐 Logging in to Salesforce...
✅ Login successful

📄 Navigating to test page...
✅ Navigation successful

⏱️  Running performance tests...

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

### HTML Report
Generated in `test-results/reports/report-{timestamp}.html`

Contains:
- Summary statistics with color-coded target achievement
- Detailed table of all test results
- Visual indicators for pass/fail
- Timestamp and metadata

Open in browser to view formatted results.

### JSON Results
Generated in `test-results/reports/results-{timestamp}.json`

Contains:
- Raw test data for each query
- Summary statistics
- Programmatic access to results

Use for:
- Integration with other tools
- Historical trend analysis
- Custom reporting

### Screenshots
Generated in `test-results/screenshots/query-{number}.png`

One screenshot per query showing:
- Query input
- Streaming answer
- Citations (if visible)
- Overall component state

Use for:
- Visual verification
- Debugging failures
- Documentation

## Performance Targets

The automated tests validate against these targets:

| Metric | Target | Requirement |
|--------|--------|-------------|
| p95 First Token Latency | ≤800ms | Requirement 8.1 |
| p95 End-to-End Latency | ≤4.0s | Requirement 8.2 |

Tests are marked as **PASS** if both targets are met.

## Test Queries

The automated test uses 20 diverse queries covering:

**Single-Object Queries**:
- "Show open opportunities"
- "Summarize recent cases"
- "List accounts in EMEA"

**Multi-Object Queries**:
- "Show opportunities for accounts with open cases"
- "List leases expiring next quarter with associated properties"

**Complex Queries**:
- "Show opportunities over $1M in EMEA closing this quarter with blockers"
- "Summarize recent activity for ACME Corp including opportunities, cases, and notes"

**Edge Cases**:
- Long queries
- Queries with filters
- Queries requiring authorization filtering

## Troubleshooting

### Login Fails
**Issue**: Script cannot log in to Salesforce

**Solutions**:
- Verify username and password are correct
- Check if user has "API Enabled" permission
- Verify instanceUrl is correct (https://test.salesforce.com or https://login.salesforce.com)
- Check if IP restrictions are blocking access
- Try logging in manually first to verify credentials

### Component Not Found
**Issue**: Script cannot find AI Search component

**Solutions**:
- Verify LWC is deployed to the org
- Check that LWC is added to Home page layout
- Verify user has access to the page
- Check component API name matches: `c-ascendix-ai-search`
- Try navigating to the page manually to verify it loads

### Timeouts
**Issue**: Tests timeout waiting for responses

**Solutions**:
- Increase timeout in config (default: 120000ms)
- Verify AWS infrastructure is deployed and healthy
- Check Named Credential is configured correctly
- Verify Private Connect is active
- Check CloudWatch logs for backend errors
- Test API Gateway endpoint directly

### No First Token Detected
**Issue**: First token latency shows as null

**Solutions**:
- Verify streaming is working (check manually in browser)
- Check that answer text is appearing in the component
- Verify mutation observer is detecting changes
- Check browser console for JavaScript errors
- Increase first token timeout (default: 5000ms)

### Screenshots Not Saved
**Issue**: Screenshots directory is empty

**Solutions**:
- Verify write permissions on test-results directory
- Check disk space
- Ensure Puppeteer has permissions to take screenshots
- Check console for file system errors

## CI/CD Integration

### GitHub Actions Example

```yaml
name: E2E Performance Tests

on:
  schedule:
    - cron: '0 0 * * *'  # Daily at midnight
  workflow_dispatch:

jobs:
  e2e-tests:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: '18'
      
      - name: Install dependencies
        run: |
          cd salesforce/tests
          npm install
      
      - name: Run E2E tests
        env:
          SF_USERNAME: ${{ secrets.SF_USERNAME }}
          SF_PASSWORD: ${{ secrets.SF_PASSWORD }}
          SF_INSTANCE_URL: ${{ secrets.SF_INSTANCE_URL }}
        run: |
          cd salesforce/tests
          node e2e-performance-test.js \
            --username=$SF_USERNAME \
            --password=$SF_PASSWORD \
            --instanceUrl=$SF_INSTANCE_URL \
            --headless=true
      
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: test-results
          path: salesforce/tests/test-results/
      
      - name: Fail if targets not met
        run: |
          # Parse JSON results and fail if targets not met
          # Add custom logic here
```

### Jenkins Example

```groovy
pipeline {
    agent any
    
    environment {
        SF_USERNAME = credentials('salesforce-username')
        SF_PASSWORD = credentials('salesforce-password')
        SF_INSTANCE_URL = 'https://test.salesforce.com'
    }
    
    stages {
        stage('Setup') {
            steps {
                sh 'cd salesforce/tests && npm install'
            }
        }
        
        stage('Run E2E Tests') {
            steps {
                sh '''
                    cd salesforce/tests
                    node e2e-performance-test.js \
                        --username=$SF_USERNAME \
                        --password=$SF_PASSWORD \
                        --instanceUrl=$SF_INSTANCE_URL \
                        --headless=true
                '''
            }
        }
    }
    
    post {
        always {
            archiveArtifacts artifacts: 'salesforce/tests/test-results/**/*', allowEmptyArchive: true
            publishHTML([
                reportDir: 'salesforce/tests/test-results/reports',
                reportFiles: 'report-*.html',
                reportName: 'E2E Test Report'
            ])
        }
    }
}
```

## Best Practices

### For Manual Testing
1. Test with multiple user profiles (Rep, Manager, Admin)
2. Test with different data sets
3. Test during different times of day (check for performance variations)
4. Document all issues with screenshots
5. Verify authorization rules are enforced
6. Test error scenarios (timeouts, network issues)

### For Automated Testing
1. Run tests regularly (daily or after deployments)
2. Monitor trends over time (are latencies increasing?)
3. Run tests from different locations (if using distributed teams)
4. Keep test queries up to date with real user queries
5. Archive test results for historical analysis
6. Alert on performance regressions

## Extending the Tests

### Adding New Test Queries

Edit `e2e-performance-test.js` and add to the `testQueries` array:

```javascript
const testQueries = [
    // ... existing queries
    "Your new test query here"
];
```

### Customizing Performance Targets

Edit the `targets` object in `e2e-performance-test.js`:

```javascript
const targets = {
    firstTokenP95: 800, // ms
    endToEndP95: 4000 // ms
};
```

### Adding Custom Validations

Add validation logic in the `testQuery` function:

```javascript
// Example: Validate citations count
if (result.citationsCount === 0) {
    console.warn('  ⚠️  No citations returned');
}

// Example: Validate answer quality
const answerText = await page.evaluate(() => {
    const component = document.querySelector('c-ascendix-ai-search');
    return component.shadowRoot.querySelector('.answer-text').textContent;
});

if (answerText.length < 50) {
    console.warn('  ⚠️  Answer seems too short');
}
```

## Support

For issues or questions:
- Check CloudWatch logs for backend errors
- Check browser console for frontend errors
- Review Salesforce debug logs
- Consult the main README.md and DEPLOYMENT_GUIDE.md

## Related Documentation

- **Main README**: `../README.md`
- **Deployment Guide**: `../DEPLOYMENT_GUIDE.md`
- **Design Document**: `../../.kiro/specs/salesforce-ai-search-poc/design.md`
- **Requirements**: `../../.kiro/specs/salesforce-ai-search-poc/requirements.md`
- **Tasks**: `../../.kiro/specs/salesforce-ai-search-poc/tasks.md`

## Version History

- **v1.0** (2025-11-13): Initial release
  - Manual test plan with 23 test cases
  - Automated performance test script
  - HTML and JSON reporting
  - Screenshot capture

## License

Internal use only - Ascendix Corporation
