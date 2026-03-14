/**
 * End-to-End Performance Test Script
 * 
 * This script automates performance testing for the Ascendix AI Search LWC component.
 * It measures first token latency, end-to-end latency, and validates response quality.
 * 
 * Prerequisites:
 * - Node.js installed
 * - Salesforce org with LWC deployed
 * - Test user credentials
 * - npm install puppeteer
 * 
 * Usage:
 * node e2e-performance-test.js --username=test@example.com --password=password --instanceUrl=https://test.salesforce.com
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

// Configuration
const config = {
    headless: false, // Set to true for CI/CD
    slowMo: 50, // Slow down by 50ms for visibility
    timeout: 120000, // 2 minutes
    screenshotDir: './test-results/screenshots',
    reportDir: './test-results/reports'
};

// Test queries
const testQueries = [
    "Show open opportunities",
    "Summarize recent cases",
    "List accounts in EMEA",
    "Show high-value deals closing this quarter",
    "What are the top blockers for renewals?",
    "Show opportunities over $1M",
    "Summarize activity for ACME Corp",
    "List cases with high priority",
    "Show leases expiring next quarter",
    "What contracts are up for renewal?",
    "Show opportunities in Enterprise segment",
    "List accounts with open cases",
    "Summarize Q1 pipeline",
    "Show deals at risk",
    "List properties with maintenance issues",
    "Show opportunities by region",
    "Summarize customer feedback",
    "List accounts with recent activity",
    "Show opportunities by stage",
    "What are the top revenue opportunities?"
];

// Performance targets
const targets = {
    firstTokenP95: 800, // ms
    endToEndP95: 4000 // ms
};

// Test results
const results = {
    queries: [],
    summary: {
        total: 0,
        passed: 0,
        failed: 0,
        p50FirstToken: 0,
        p95FirstToken: 0,
        p99FirstToken: 0,
        p50EndToEnd: 0,
        p95EndToEnd: 0,
        p99EndToEnd: 0
    }
};

/**
 * Main test execution function
 */
async function runTests() {
    console.log('🚀 Starting End-to-End Performance Tests...\n');
    
    // Parse command line arguments
    const args = parseArgs();
    
    if (!args.username || !args.password || !args.instanceUrl) {
        console.error('❌ Missing required arguments: --username, --password, --instanceUrl');
        process.exit(1);
    }
    
    // Create output directories
    createDirectories();
    
    // Launch browser
    const browser = await puppeteer.launch({
        headless: config.headless,
        slowMo: config.slowMo,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    try {
        const page = await browser.newPage();
        await page.setViewport({ width: 1920, height: 1080 });
        
        // Login to Salesforce
        console.log('🔐 Logging in to Salesforce...');
        await loginToSalesforce(page, args.username, args.password, args.instanceUrl);
        console.log('✅ Login successful\n');
        
        // Navigate to page with AI Search component
        console.log('📄 Navigating to test page...');
        await navigateToTestPage(page, args.instanceUrl);
        console.log('✅ Navigation successful\n');
        
        // Run performance tests
        console.log('⏱️  Running performance tests...\n');
        for (let i = 0; i < testQueries.length; i++) {
            const query = testQueries[i];
            console.log(`Test ${i + 1}/${testQueries.length}: "${query}"`);
            
            try {
                const result = await testQuery(page, query, i + 1);
                results.queries.push(result);
                
                console.log(`  ⏱️  First Token: ${result.firstTokenMs}ms`);
                console.log(`  ⏱️  End-to-End: ${result.endToEndMs}ms`);
                console.log(`  📚 Citations: ${result.citationsCount}`);
                console.log(`  ${result.passed ? '✅ PASS' : '❌ FAIL'}\n`);
                
                // Wait between queries to avoid rate limiting
                await page.waitForTimeout(2000);
                
            } catch (error) {
                console.error(`  ❌ Error: ${error.message}\n`);
                results.queries.push({
                    queryNumber: i + 1,
                    query: query,
                    passed: false,
                    error: error.message
                });
            }
        }
        
        // Calculate summary statistics
        calculateSummary();
        
        // Generate report
        generateReport();
        
        // Display summary
        displaySummary();
        
    } catch (error) {
        console.error('❌ Test execution failed:', error);
        throw error;
    } finally {
        await browser.close();
    }
}

/**
 * Login to Salesforce
 */
async function loginToSalesforce(page, username, password, instanceUrl) {
    await page.goto(instanceUrl, { waitUntil: 'networkidle2' });
    
    // Wait for login form
    await page.waitForSelector('#username', { timeout: config.timeout });
    
    // Enter credentials
    await page.type('#username', username);
    await page.type('#password', password);
    
    // Click login button
    await page.click('#Login');
    
    // Wait for navigation to complete
    await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: config.timeout });
}

/**
 * Navigate to page with AI Search component
 */
async function navigateToTestPage(page, instanceUrl) {
    // Navigate to Home page (adjust URL as needed)
    const homeUrl = `${instanceUrl}/lightning/page/home`;
    await page.goto(homeUrl, { waitUntil: 'networkidle2' });
    
    // Wait for AI Search component to load
    await page.waitForSelector('c-ascendix-ai-search', { timeout: config.timeout });
    
    // Wait for component to be fully initialized
    await page.waitForTimeout(2000);
}

/**
 * Test a single query
 */
async function testQuery(page, query, queryNumber) {
    const result = {
        queryNumber: queryNumber,
        query: query,
        firstTokenMs: null,
        endToEndMs: null,
        citationsCount: 0,
        passed: false,
        error: null
    };
    
    try {
        // Find query input within shadow DOM
        const queryInput = await page.evaluateHandle(() => {
            const component = document.querySelector('c-ascendix-ai-search');
            return component.shadowRoot.querySelector('lightning-textarea[name="query"]');
        });
        
        if (!queryInput) {
            throw new Error('Query input not found');
        }
        
        // Clear previous query
        await page.evaluate((input) => {
            input.value = '';
        }, queryInput);
        
        // Type query
        await page.evaluate((input, text) => {
            input.value = text;
            input.dispatchEvent(new Event('change', { bubbles: true }));
        }, queryInput, query);
        
        // Find and click search button
        const searchButton = await page.evaluateHandle(() => {
            const component = document.querySelector('c-ascendix-ai-search');
            return component.shadowRoot.querySelector('lightning-button.submit-button');
        });
        
        if (!searchButton) {
            throw new Error('Search button not found');
        }
        
        // Start timing
        const startTime = Date.now();
        let firstTokenTime = null;
        
        // Set up mutation observer to detect first token
        await page.evaluate(() => {
            window.firstTokenDetected = false;
            window.firstTokenTime = null;
            
            const component = document.querySelector('c-ascendix-ai-search');
            const answerContainer = component.shadowRoot.querySelector('.answer-text');
            
            if (answerContainer) {
                const observer = new MutationObserver((mutations) => {
                    if (!window.firstTokenDetected && answerContainer.textContent.trim().length > 0) {
                        window.firstTokenDetected = true;
                        window.firstTokenTime = Date.now();
                    }
                });
                
                observer.observe(answerContainer, {
                    childList: true,
                    subtree: true,
                    characterData: true
                });
            }
        });
        
        // Click search button
        await page.evaluate((button) => {
            button.click();
        }, searchButton);
        
        // Wait for first token (max 5 seconds)
        await page.waitForFunction(() => window.firstTokenDetected, {
            timeout: 5000
        }).catch(() => {
            console.warn('  ⚠️  First token not detected within 5 seconds');
        });
        
        // Get first token time
        firstTokenTime = await page.evaluate(() => window.firstTokenTime);
        if (firstTokenTime) {
            result.firstTokenMs = firstTokenTime - startTime;
        }
        
        // Wait for streaming to complete (loading spinner disappears)
        await page.waitForFunction(() => {
            const component = document.querySelector('c-ascendix-ai-search');
            const spinner = component.shadowRoot.querySelector('lightning-spinner');
            return !spinner || spinner.style.display === 'none';
        }, { timeout: config.timeout });
        
        // Calculate end-to-end time
        const endTime = Date.now();
        result.endToEndMs = endTime - startTime;
        
        // Get citations count
        result.citationsCount = await page.evaluate(() => {
            const component = document.querySelector('c-ascendix-ai-search');
            const citationsButton = component.shadowRoot.querySelector('lightning-button[label*="Citations"]');
            if (citationsButton) {
                const match = citationsButton.label.match(/\((\d+)\)/);
                return match ? parseInt(match[1]) : 0;
            }
            return 0;
        });
        
        // Take screenshot
        const screenshotPath = path.join(config.screenshotDir, `query-${queryNumber}.png`);
        await page.screenshot({ path: screenshotPath, fullPage: true });
        
        // Check if passed
        result.passed = result.firstTokenMs !== null && 
                       result.endToEndMs !== null && 
                       result.endToEndMs < config.timeout;
        
    } catch (error) {
        result.error = error.message;
        result.passed = false;
    }
    
    return result;
}

/**
 * Calculate summary statistics
 */
function calculateSummary() {
    const validResults = results.queries.filter(r => r.passed && r.firstTokenMs !== null);
    
    if (validResults.length === 0) {
        console.error('❌ No valid results to calculate summary');
        return;
    }
    
    results.summary.total = results.queries.length;
    results.summary.passed = validResults.length;
    results.summary.failed = results.summary.total - results.summary.passed;
    
    // Sort by first token latency
    const firstTokenLatencies = validResults.map(r => r.firstTokenMs).sort((a, b) => a - b);
    results.summary.p50FirstToken = percentile(firstTokenLatencies, 50);
    results.summary.p95FirstToken = percentile(firstTokenLatencies, 95);
    results.summary.p99FirstToken = percentile(firstTokenLatencies, 99);
    
    // Sort by end-to-end latency
    const endToEndLatencies = validResults.map(r => r.endToEndMs).sort((a, b) => a - b);
    results.summary.p50EndToEnd = percentile(endToEndLatencies, 50);
    results.summary.p95EndToEnd = percentile(endToEndLatencies, 95);
    results.summary.p99EndToEnd = percentile(endToEndLatencies, 99);
}

/**
 * Calculate percentile
 */
function percentile(arr, p) {
    if (arr.length === 0) return 0;
    const index = Math.ceil((p / 100) * arr.length) - 1;
    return Math.round(arr[index]);
}

/**
 * Generate HTML report
 */
function generateReport() {
    const reportPath = path.join(config.reportDir, `report-${Date.now()}.html`);
    
    const html = `
<!DOCTYPE html>
<html>
<head>
    <title>E2E Performance Test Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #0070d2; }
        .summary { background: #f3f3f3; padding: 20px; border-radius: 5px; margin-bottom: 20px; }
        .summary-item { margin: 10px 0; }
        .pass { color: green; font-weight: bold; }
        .fail { color: red; font-weight: bold; }
        table { border-collapse: collapse; width: 100%; margin-top: 20px; }
        th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
        th { background-color: #0070d2; color: white; }
        tr:nth-child(even) { background-color: #f9f9f9; }
        .target-met { background-color: #d4edda; }
        .target-missed { background-color: #f8d7da; }
    </style>
</head>
<body>
    <h1>End-to-End Performance Test Report</h1>
    <p><strong>Date:</strong> ${new Date().toISOString()}</p>
    
    <div class="summary">
        <h2>Summary</h2>
        <div class="summary-item">Total Tests: ${results.summary.total}</div>
        <div class="summary-item">Passed: <span class="pass">${results.summary.passed}</span></div>
        <div class="summary-item">Failed: <span class="fail">${results.summary.failed}</span></div>
        <div class="summary-item">Pass Rate: ${((results.summary.passed / results.summary.total) * 100).toFixed(1)}%</div>
        
        <h3>First Token Latency</h3>
        <div class="summary-item">P50: ${results.summary.p50FirstToken}ms</div>
        <div class="summary-item ${results.summary.p95FirstToken <= targets.firstTokenP95 ? 'target-met' : 'target-missed'}">
            P95: ${results.summary.p95FirstToken}ms (Target: ≤${targets.firstTokenP95}ms)
        </div>
        <div class="summary-item">P99: ${results.summary.p99FirstToken}ms</div>
        
        <h3>End-to-End Latency</h3>
        <div class="summary-item">P50: ${results.summary.p50EndToEnd}ms</div>
        <div class="summary-item ${results.summary.p95EndToEnd <= targets.endToEndP95 ? 'target-met' : 'target-missed'}">
            P95: ${results.summary.p95EndToEnd}ms (Target: ≤${targets.endToEndP95}ms)
        </div>
        <div class="summary-item">P99: ${results.summary.p99EndToEnd}ms</div>
    </div>
    
    <h2>Detailed Results</h2>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Query</th>
                <th>First Token (ms)</th>
                <th>End-to-End (ms)</th>
                <th>Citations</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
            ${results.queries.map(r => `
                <tr>
                    <td>${r.queryNumber}</td>
                    <td>${r.query}</td>
                    <td>${r.firstTokenMs || 'N/A'}</td>
                    <td>${r.endToEndMs || 'N/A'}</td>
                    <td>${r.citationsCount}</td>
                    <td class="${r.passed ? 'pass' : 'fail'}">${r.passed ? 'PASS' : 'FAIL'}</td>
                </tr>
            `).join('')}
        </tbody>
    </table>
</body>
</html>
    `;
    
    fs.writeFileSync(reportPath, html);
    console.log(`\n📊 HTML report generated: ${reportPath}`);
    
    // Also save JSON results
    const jsonPath = path.join(config.reportDir, `results-${Date.now()}.json`);
    fs.writeFileSync(jsonPath, JSON.stringify(results, null, 2));
    console.log(`📊 JSON results saved: ${jsonPath}`);
}

/**
 * Display summary in console
 */
function displaySummary() {
    console.log('\n' + '='.repeat(60));
    console.log('📊 TEST SUMMARY');
    console.log('='.repeat(60));
    console.log(`Total Tests: ${results.summary.total}`);
    console.log(`Passed: ${results.summary.passed}`);
    console.log(`Failed: ${results.summary.failed}`);
    console.log(`Pass Rate: ${((results.summary.passed / results.summary.total) * 100).toFixed(1)}%`);
    console.log('');
    console.log('First Token Latency:');
    console.log(`  P50: ${results.summary.p50FirstToken}ms`);
    console.log(`  P95: ${results.summary.p95FirstToken}ms ${results.summary.p95FirstToken <= targets.firstTokenP95 ? '✅' : '❌'} (Target: ≤${targets.firstTokenP95}ms)`);
    console.log(`  P99: ${results.summary.p99FirstToken}ms`);
    console.log('');
    console.log('End-to-End Latency:');
    console.log(`  P50: ${results.summary.p50EndToEnd}ms`);
    console.log(`  P95: ${results.summary.p95EndToEnd}ms ${results.summary.p95EndToEnd <= targets.endToEndP95 ? '✅' : '❌'} (Target: ≤${targets.endToEndP95}ms)`);
    console.log(`  P99: ${results.summary.p99EndToEnd}ms`);
    console.log('='.repeat(60));
    
    // Overall pass/fail
    const overallPass = results.summary.p95FirstToken <= targets.firstTokenP95 && 
                       results.summary.p95EndToEnd <= targets.endToEndP95 &&
                       results.summary.passed >= results.summary.total * 0.9; // 90% pass rate
    
    if (overallPass) {
        console.log('\n✅ ALL PERFORMANCE TARGETS MET');
    } else {
        console.log('\n❌ PERFORMANCE TARGETS NOT MET');
    }
    
    console.log('');
}

/**
 * Parse command line arguments
 */
function parseArgs() {
    const args = {};
    process.argv.slice(2).forEach(arg => {
        const [key, value] = arg.split('=');
        args[key.replace('--', '')] = value;
    });
    return args;
}

/**
 * Create output directories
 */
function createDirectories() {
    [config.screenshotDir, config.reportDir].forEach(dir => {
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }
    });
}

// Run tests
runTests().catch(error => {
    console.error('❌ Fatal error:', error);
    process.exit(1);
});
