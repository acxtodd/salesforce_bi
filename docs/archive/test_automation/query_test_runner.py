#!/usr/bin/env python3
"""
Automated Query Testing Framework for Salesforce AI Search
Author: Claude Code
Date: 2025-11-25
Purpose: Run acceptance test queries and measure results

**Feature: zero-config-production, Task 28.2**
Configuration moved to environment variables for security.
Set the following environment variables before running:
- SALESFORCE_AI_SEARCH_LAMBDA_URL
- SALESFORCE_AI_SEARCH_API_KEY
- SALESFORCE_AI_SEARCH_KNOWLEDGE_BASE_ID
- AWS_REGION (optional, defaults to us-west-2)
- SALESFORCE_AI_SEARCH_TEST_USER_ID (optional)
"""

import json
import os
import time
import requests
import subprocess
from datetime import datetime
from typing import Dict, List, Any, Optional
import statistics

# Configuration from environment variables
# **Feature: zero-config-production, Task 28.2**
LAMBDA_URL = os.getenv(
    "SALESFORCE_AI_SEARCH_LAMBDA_URL",
    "https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws"
)
API_KEY = os.getenv("SALESFORCE_AI_SEARCH_API_KEY", "")
KNOWLEDGE_BASE_ID = os.getenv("SALESFORCE_AI_SEARCH_KNOWLEDGE_BASE_ID", "HOOACWECEX")
AWS_REGION = os.getenv("AWS_REGION", "us-west-2")
TEST_USER_ID = os.getenv("SALESFORCE_AI_SEARCH_TEST_USER_ID", "005dl00000Q6a3RAAR")

# Validate required environment variables
if not API_KEY:
    print("⚠️  Warning: SALESFORCE_AI_SEARCH_API_KEY environment variable not set.")
    print("   Set it or create a .env file. See .env.example for reference.")

# Test Query Definitions
TEST_QUERIES = {
    # Single Object Queries (Should Work)
    "single_property_city": {
        "query": "Show me all properties in Dallas",
        "expected_object": "ascendix__Property__c",
        "expected_keywords": ["Dallas", "property", "properties"],
        "expected_min_results": 1,
        "category": "single-object"
    },
    "single_property_class": {
        "query": "Find Class A office buildings",
        "expected_object": "ascendix__Property__c",
        "expected_keywords": ["Class A", "office", "building"],
        "expected_min_results": 1,
        "category": "single-object"
    },
    "single_deal_open": {
        "query": "Show me all open deals",
        "expected_object": "ascendix__Deal__c",
        "expected_keywords": ["open", "deal"],
        "expected_min_results": 1,
        "category": "single-object"
    },
    "single_lease_expiring": {
        "query": "Which leases are expiring in the next 90 days?",
        "expected_object": "ascendix__Lease__c",
        "expected_keywords": ["lease", "expiring"],
        "expected_min_results": 0,  # May not have any
        "category": "temporal"
    },

    # Cross-Object Queries (Likely to Fail)
    "cross_property_availability": {
        "query": "Show properties in Dallas with available space",
        "expected_objects": ["ascendix__Property__c", "ascendix__Availability__c"],
        "expected_keywords": ["Dallas", "available", "space"],
        "expected_min_results": 1,
        "category": "cross-object"
    },
    "cross_deal_property": {
        "query": "Show deals for properties in New York",
        "expected_objects": ["ascendix__Deal__c", "ascendix__Property__c"],
        "expected_keywords": ["deal", "New York", "property"],
        "expected_min_results": 0,
        "category": "cross-object"
    },
    "cross_property_lease": {
        "query": "Which properties have leases expiring soon?",
        "expected_objects": ["ascendix__Property__c", "ascendix__Lease__c"],
        "expected_keywords": ["property", "lease", "expiring"],
        "expected_min_results": 0,
        "category": "cross-object"
    },

    # Specific Entity Queries
    "specific_deal": {
        "query": "What deals does StorQuest Self Storage have?",
        "expected_object": "ascendix__Deal__c",
        "expected_keywords": ["StorQuest", "deal"],
        "expected_min_results": 0,
        "category": "specific-entity"
    },
    "specific_property": {
        "query": "Show available spaces at 17Seventeen McKinney",
        "expected_object": "ascendix__Availability__c",
        "expected_keywords": ["17Seventeen McKinney", "available"],
        "expected_min_results": 0,
        "category": "specific-entity"
    }
}


class QueryTestRunner:
    def __init__(self):
        self.results = []
        self.session = requests.Session()
        self.session.headers.update({
            "x-api-key": API_KEY,
            "Content-Type": "application/json"
        })

    def test_lambda_endpoint(self, query: str, filters: Dict = None) -> Dict:
        """Test query via Lambda Function URL."""
        start_time = time.time()

        payload = {
            "query": query,
            "salesforceUserId": TEST_USER_ID,  # From environment variable
            "filters": filters or {},
            "topK": 5
        }

        try:
            response = self.session.post(
                f"{LAMBDA_URL}/answer",
                json=payload,
                timeout=30,
                stream=True
            )

            # Measure time to first byte
            first_byte_time = time.time() - start_time

            # Collect full response
            full_response = ""
            chunks = []
            citations = []

            for line in response.iter_lines():
                if line:
                    line_str = line.decode('utf-8')
                    if line_str.startswith('data:'):
                        try:
                            data = json.loads(line_str[5:].strip())
                            if 'token' in data:
                                chunks.append(data['token'])
                            elif 'citation' in data:
                                citations.append(data['citation'])
                        except:
                            pass

            end_time = time.time()

            return {
                "success": response.status_code == 200,
                "status_code": response.status_code,
                "response_text": ''.join(chunks),
                "citations": citations,
                "citation_count": len(citations),
                "first_byte_latency": first_byte_time * 1000,  # ms
                "total_latency": (end_time - start_time) * 1000,  # ms
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "status_code": 0,
                "response_text": "",
                "citations": [],
                "citation_count": 0,
                "first_byte_latency": 0,
                "total_latency": (time.time() - start_time) * 1000,
                "error": str(e)
            }

    def test_bedrock_knowledge_base(self, query: str) -> Dict:
        """Test query directly via Bedrock Knowledge Base."""
        start_time = time.time()

        try:
            # Use AWS CLI to query Bedrock
            cmd = [
                "aws", "bedrock-agent-runtime", "retrieve",
                "--knowledge-base-id", KNOWLEDGE_BASE_ID,
                "--retrieval-query", json.dumps({"text": query}),
                "--region", AWS_REGION,
                "--no-cli-pager",
                "--output", "json"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                data = json.loads(result.stdout)
                results = data.get('retrievalResults', [])

                return {
                    "success": True,
                    "result_count": len(results),
                    "results": results[:5],  # Top 5
                    "latency": (time.time() - start_time) * 1000,
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "result_count": 0,
                    "results": [],
                    "latency": (time.time() - start_time) * 1000,
                    "error": result.stderr
                }

        except Exception as e:
            return {
                "success": False,
                "result_count": 0,
                "results": [],
                "latency": (time.time() - start_time) * 1000,
                "error": str(e)
            }

    def evaluate_response(self, response: Dict, test_case: Dict) -> Dict:
        """Evaluate response against expected results."""
        evaluation = {
            "query": test_case.get("query"),
            "category": test_case.get("category"),
            "passed": True,
            "checks": {}
        }

        # Check if response was successful
        if not response.get("success"):
            evaluation["passed"] = False
            evaluation["checks"]["api_success"] = False
            return evaluation

        evaluation["checks"]["api_success"] = True

        response_text = response.get("response_text", "").lower()

        # Check for expected keywords
        keywords_found = []
        for keyword in test_case.get("expected_keywords", []):
            if keyword.lower() in response_text:
                keywords_found.append(keyword)

        keyword_coverage = len(keywords_found) / len(test_case.get("expected_keywords", [1]))
        evaluation["checks"]["keyword_coverage"] = keyword_coverage
        evaluation["keywords_found"] = keywords_found

        if keyword_coverage < 0.5:
            evaluation["passed"] = False

        # Check citation count
        citation_count = response.get("citation_count", 0)
        min_results = test_case.get("expected_min_results", 0)

        evaluation["checks"]["has_citations"] = citation_count > 0
        evaluation["checks"]["meets_min_results"] = citation_count >= min_results
        evaluation["citation_count"] = citation_count

        if min_results > 0 and citation_count < min_results:
            evaluation["passed"] = False

        # Check for hallucination (no citations but detailed answer)
        if citation_count == 0 and len(response_text) > 100:
            evaluation["checks"]["potential_hallucination"] = True
            evaluation["passed"] = False

        # Performance checks
        evaluation["performance"] = {
            "first_byte_ms": response.get("first_byte_latency", 0),
            "total_ms": response.get("total_latency", 0),
            "meets_sla": response.get("total_latency", 0) < 4000  # 4s SLA
        }

        return evaluation

    def run_test_suite(self, test_subset: List[str] = None) -> Dict:
        """Run complete test suite or subset."""
        tests_to_run = test_subset or list(TEST_QUERIES.keys())
        suite_results = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(tests_to_run),
            "passed": 0,
            "failed": 0,
            "results": [],
            "performance_summary": {},
            "category_summary": {}
        }

        print(f"Running {len(tests_to_run)} test queries...")
        print("=" * 60)

        latencies = []

        for test_name in tests_to_run:
            test_case = TEST_QUERIES.get(test_name)
            if not test_case:
                continue

            print(f"\nTesting: {test_name}")
            print(f"Query: {test_case['query']}")

            # Test via Lambda
            response = self.test_lambda_endpoint(test_case["query"])

            # Evaluate
            evaluation = self.evaluate_response(response, test_case)
            evaluation["test_name"] = test_name

            # Track results
            if evaluation["passed"]:
                suite_results["passed"] += 1
                print("✅ PASSED")
            else:
                suite_results["failed"] += 1
                print("❌ FAILED")

            print(f"  Citations: {evaluation.get('citation_count', 0)}")
            print(f"  Latency: {response.get('total_latency', 0):.0f}ms")

            suite_results["results"].append(evaluation)
            latencies.append(response.get("total_latency", 0))

            # Track by category
            category = test_case.get("category", "unknown")
            if category not in suite_results["category_summary"]:
                suite_results["category_summary"][category] = {"passed": 0, "failed": 0}

            if evaluation["passed"]:
                suite_results["category_summary"][category]["passed"] += 1
            else:
                suite_results["category_summary"][category]["failed"] += 1

            # Small delay between tests
            time.sleep(1)

        # Calculate performance summary
        if latencies:
            suite_results["performance_summary"] = {
                "avg_latency_ms": statistics.mean(latencies),
                "p50_latency_ms": statistics.median(latencies),
                "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else latencies[0],
                "max_latency_ms": max(latencies),
                "min_latency_ms": min(latencies)
            }

        # Calculate pass rate
        suite_results["pass_rate"] = (suite_results["passed"] / suite_results["total_tests"] * 100) if suite_results["total_tests"] > 0 else 0

        return suite_results

    def generate_report(self, results: Dict, output_file: str = None):
        """Generate detailed test report."""
        report = []
        report.append("# Automated Query Test Report")
        report.append(f"**Date**: {results['timestamp']}")
        report.append(f"**Total Tests**: {results['total_tests']}")
        report.append(f"**Pass Rate**: {results['pass_rate']:.1f}%")
        report.append("")

        # Summary
        report.append("## Summary")
        report.append(f"- ✅ Passed: {results['passed']}")
        report.append(f"- ❌ Failed: {results['failed']}")
        report.append("")

        # Category breakdown
        report.append("## Results by Category")
        for category, stats in results.get("category_summary", {}).items():
            total = stats["passed"] + stats["failed"]
            pass_rate = (stats["passed"] / total * 100) if total > 0 else 0
            report.append(f"- **{category}**: {pass_rate:.0f}% pass rate ({stats['passed']}/{total})")
        report.append("")

        # Performance
        perf = results.get("performance_summary", {})
        if perf:
            report.append("## Performance Metrics")
            report.append(f"- Average Latency: {perf.get('avg_latency_ms', 0):.0f}ms")
            report.append(f"- P50 Latency: {perf.get('p50_latency_ms', 0):.0f}ms")
            report.append(f"- P95 Latency: {perf.get('p95_latency_ms', 0):.0f}ms")
            report.append(f"- Max Latency: {perf.get('max_latency_ms', 0):.0f}ms")
            report.append("")

        # Detailed results
        report.append("## Detailed Results")
        for result in results.get("results", []):
            status = "✅" if result["passed"] else "❌"
            report.append(f"\n### {status} {result['test_name']}")
            report.append(f"**Query**: {result['query']}")
            report.append(f"**Category**: {result['category']}")
            report.append(f"**Citations Found**: {result.get('citation_count', 0)}")

            if result.get("keywords_found"):
                report.append(f"**Keywords Found**: {', '.join(result['keywords_found'])}")

            perf = result.get("performance", {})
            if perf:
                report.append(f"**Latency**: {perf.get('total_ms', 0):.0f}ms")

            checks = result.get("checks", {})
            if not result["passed"]:
                report.append("**Failed Checks**:")
                for check, value in checks.items():
                    if not value:
                        report.append(f"- {check}")

        report_text = "\n".join(report)

        # Save to file if specified
        if output_file:
            with open(output_file, 'w') as f:
                f.write(report_text)
            print(f"\nReport saved to: {output_file}")

        return report_text


def main():
    """Main test execution."""
    import sys

    # Parse arguments
    test_subset = None
    if len(sys.argv) > 1:
        if sys.argv[1] == "--single-object":
            test_subset = [k for k, v in TEST_QUERIES.items() if v["category"] == "single-object"]
        elif sys.argv[1] == "--cross-object":
            test_subset = [k for k, v in TEST_QUERIES.items() if v["category"] == "cross-object"]
        elif sys.argv[1] == "--quick":
            test_subset = ["single_property_city", "single_deal_open", "cross_property_availability"]
        else:
            test_subset = sys.argv[1].split(",")

    # Run tests
    runner = QueryTestRunner()
    results = runner.run_test_suite(test_subset)

    # Generate report
    print("\n" + "=" * 60)
    print("TEST RESULTS SUMMARY")
    print("=" * 60)
    print(f"Pass Rate: {results['pass_rate']:.1f}%")
    print(f"Passed: {results['passed']}/{results['total_tests']}")

    print("\nCategory Performance:")
    for category, stats in results["category_summary"].items():
        total = stats["passed"] + stats["failed"]
        pass_rate = (stats["passed"] / total * 100) if total > 0 else 0
        print(f"  {category}: {pass_rate:.0f}% ({stats['passed']}/{total})")

    # Save report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"test_report_{timestamp}.md"
    runner.generate_report(results, report_file)

    # Exit code based on pass rate
    if results['pass_rate'] >= 70:
        sys.exit(0)  # Success
    else:
        sys.exit(1)  # Failure


if __name__ == "__main__":
    main()