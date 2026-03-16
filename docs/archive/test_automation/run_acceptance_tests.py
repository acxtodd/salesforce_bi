#!/usr/bin/env python3
"""
CRE Acceptance Test Suite Runner
Runs all 22 queries from the acceptance test document
"""

import json
import subprocess
import time
from datetime import datetime
from typing import Dict, List, Tuple
import sys

# Configuration
KNOWLEDGE_BASE_ID = "HOOACWECEX"
AWS_REGION = "us-west-2"

# Full Acceptance Test Query Set from the document
ACCEPTANCE_TESTS = [
    # Property Queries
    {
        "id": "Q1",
        "name": "Property Search by City",
        "query": "Show me all properties in Dallas",
        "expected_object": "ascendix__Property__c",
        "expected_keywords": ["Dallas"],
        "expected_count_min": 1
    },
    {
        "id": "Q2",
        "name": "Property Search by Class",
        "query": "Find Class A office buildings",
        "expected_object": "ascendix__Property__c",
        "expected_keywords": ["Class A", "office"],
        "expected_count_min": 1
    },
    {
        "id": "Q3",
        "name": "Property Search Multi-City",
        "query": "What properties do we have in Los Angeles and Houston?",
        "expected_object": "ascendix__Property__c",
        "expected_keywords": ["Los Angeles", "Houston"],
        "expected_count_min": 1
    },
    # Availability Queries
    {
        "id": "Q4",
        "name": "Available Space Search",
        "query": "Show available spaces at 17Seventeen McKinney",
        "expected_object": "ascendix__Availability__c",
        "expected_keywords": ["17Seventeen McKinney", "available"],
        "expected_count_min": 1
    },
    {
        "id": "Q5",
        "name": "Availability by Property",
        "query": "What suites are available for lease?",
        "expected_object": "ascendix__Availability__c",
        "expected_keywords": ["available", "suite"],
        "expected_count_min": 1
    },
    # Lease Queries
    {
        "id": "Q6",
        "name": "Expiring Leases",
        "query": "Which leases are expiring in the next 90 days?",
        "expected_object": "ascendix__Lease__c",
        "expected_keywords": ["lease", "expiring"],
        "expected_count_min": 0  # May not have any
    },
    {
        "id": "Q7",
        "name": "Lease Search by Tenant",
        "query": "Show leases for Thompson & Grey",
        "expected_object": "ascendix__Lease__c",
        "expected_keywords": ["Thompson", "Grey"],
        "expected_count_min": 0
    },
    {
        "id": "Q8",
        "name": "Lease Search by Property",
        "query": "What are the current leases at Preston Park Financial Center?",
        "expected_object": "ascendix__Lease__c",
        "expected_keywords": ["Preston Park"],
        "expected_count_min": 0
    },
    # Deal Queries
    {
        "id": "Q9",
        "name": "Open Deals",
        "query": "Show me all open deals",
        "expected_object": "ascendix__Deal__c",
        "expected_keywords": ["open", "deal"],
        "expected_count_min": 1
    },
    {
        "id": "Q10",
        "name": "Deal Search by Client",
        "query": "What deals do we have with StorQuest Self Storage?",
        "expected_object": "ascendix__Deal__c",
        "expected_keywords": ["StorQuest"],
        "expected_count_min": 0
    },
    {
        "id": "Q11",
        "name": "Deal Search by Stage",
        "query": "Show deals in LOI stage",
        "expected_object": "ascendix__Deal__c",
        "expected_keywords": ["LOI", "deal"],
        "expected_count_min": 0
    },
    {
        "id": "Q12",
        "name": "Won Deals",
        "query": "List all won deals",
        "expected_object": "ascendix__Deal__c",
        "expected_keywords": ["won", "deal"],
        "expected_count_min": 0
    },
    {
        "id": "Q13",
        "name": "Deal by Type",
        "query": "Show me new lease deals",
        "expected_object": "ascendix__Deal__c",
        "expected_keywords": ["new lease", "deal"],
        "expected_count_min": 0
    },
    # Sale Queries
    {
        "id": "Q14",
        "name": "Property Sales",
        "query": "Show recent property sales",
        "expected_object": "ascendix__Sale__c",
        "expected_keywords": ["sale", "property"],
        "expected_count_min": 0
    },
    # Multi-Object Queries
    {
        "id": "Q15",
        "name": "Property + Availability",
        "query": "Show properties in Dallas with available space",
        "expected_objects": ["ascendix__Property__c", "ascendix__Availability__c"],
        "expected_keywords": ["Dallas", "available"],
        "expected_count_min": 1
    },
    {
        "id": "Q16",
        "name": "Property + Lease",
        "query": "Which properties have leases expiring soon?",
        "expected_objects": ["ascendix__Property__c", "ascendix__Lease__c"],
        "expected_keywords": ["property", "lease", "expiring"],
        "expected_count_min": 0
    },
    {
        "id": "Q17",
        "name": "Deal + Property",
        "query": "Show deals for properties in New York",
        "expected_objects": ["ascendix__Deal__c", "ascendix__Property__c"],
        "expected_keywords": ["deal", "New York"],
        "expected_count_min": 0
    },
    {
        "id": "Q18",
        "name": "Account + Deal",
        "query": "What deals does Account4 have?",
        "expected_objects": ["ascendix__Deal__c", "Account"],
        "expected_keywords": ["Account4", "deal"],
        "expected_count_min": 0
    },
    {
        "id": "Q19",
        "name": "Property + Lease + Deal",
        "query": "Show the Ascendix lease deal details",
        "expected_objects": ["ascendix__Deal__c", "ascendix__Lease__c"],
        "expected_keywords": ["Ascendix", "lease"],
        "expected_count_min": 0
    },
    # Edge Cases
    {
        "id": "Q20",
        "name": "No Results Query",
        "query": "Show properties in Antarctica",
        "expected_object": None,
        "expected_keywords": [],
        "expected_count_min": 0,
        "expect_no_results": True
    },
    {
        "id": "Q21",
        "name": "Ambiguous Query",
        "query": "Tell me about the big deal",
        "expected_object": "ascendix__Deal__c",
        "expected_keywords": ["deal"],
        "expected_count_min": 0
    },
    {
        "id": "Q22",
        "name": "Specific Deal Query",
        "query": "What's the status of the 7820 Sunset Boulevard Acquisition?",
        "expected_object": "ascendix__Deal__c",
        "expected_keywords": ["7820 Sunset"],
        "expected_count_min": 0
    }
]


class AcceptanceTestRunner:
    def __init__(self):
        self.results = []
        self.start_time = None
        self.end_time = None

    def query_knowledge_base(self, query: str) -> Tuple[bool, Dict]:
        """Query via our Retrieve Lambda (which includes intent detection and hybrid search)."""
        try:
            # Build Lambda payload with intent detection and hybrid search enabled
            payload = {
                "query": query,
                "salesforceUserId": "005dl00000Q6a3RAAR",  # Test user
                "topK": 5,
                "filters": {},
                "hybrid": True,
                "authzMode": "both"
            }

            cmd = [
                "aws", "lambda", "invoke",
                "--function-name", "salesforce-ai-search-retrieve",
                "--payload", json.dumps(payload),
                "--cli-binary-format", "raw-in-base64-out",
                "--region", AWS_REGION,
                "--no-cli-pager",
                "/tmp/retrieve_result.json"
            ]

            start = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            latency = (time.time() - start) * 1000

            if result.returncode == 0:
                # Read result from output file
                with open("/tmp/retrieve_result.json", "r") as f:
                    lambda_response = json.loads(f.read())

                body = json.loads(lambda_response.get("body", "{}"))
                results = body.get("matches", [])

                # Convert to format expected by test runner
                converted_results = []
                for match in results:
                    converted_results.append({
                        "content": {"text": match.get("text", "")},
                        "score": match.get("score", 0),
                        "metadata": match.get("metadata", {}),
                        "location": match.get("location", {})
                    })

                return True, {
                    "results": converted_results,
                    "count": len(converted_results),
                    "latency_ms": latency,
                    "top_score": converted_results[0]['score'] if converted_results else 0
                }
            else:
                return False, {
                    "error": result.stderr,
                    "latency_ms": latency
                }
        except Exception as e:
            return False, {"error": str(e)}

    def evaluate_test(self, test: Dict, response: Dict) -> Dict:
        """Evaluate test results against expectations."""
        evaluation = {
            "test_id": test["id"],
            "test_name": test["name"],
            "query": test["query"],
            "passed": False,
            "result_count": response.get("count", 0),
            "latency_ms": response.get("latency_ms", 0),
            "top_score": response.get("top_score", 0),
            "issues": []
        }

        results = response.get("results", [])

        # Check if we got results
        if test.get("expect_no_results"):
            if results:
                evaluation["issues"].append("Expected no results but got some")
            else:
                evaluation["passed"] = True
        else:
            # Check minimum result count
            if evaluation["result_count"] < test["expected_count_min"]:
                evaluation["issues"].append(f"Got {evaluation['result_count']} results, expected at least {test['expected_count_min']}")

            # Check for expected object types
            if results and test.get("expected_object"):
                top_result_object = results[0].get("metadata", {}).get("sobject")
                if top_result_object != test["expected_object"]:
                    evaluation["issues"].append(f"Top result is {top_result_object}, expected {test['expected_object']}")
                else:
                    evaluation["correct_object"] = True

            # Check for expected keywords in results
            if test.get("expected_keywords") and results:
                result_text = " ".join([r.get("content", {}).get("text", "")[:200] for r in results[:3]])
                found_keywords = []
                for keyword in test["expected_keywords"]:
                    if keyword.lower() in result_text.lower():
                        found_keywords.append(keyword)

                evaluation["keyword_coverage"] = len(found_keywords) / len(test["expected_keywords"])
                if evaluation["keyword_coverage"] < 0.5:
                    evaluation["issues"].append(f"Low keyword coverage: {evaluation['keyword_coverage']:.0%}")

            # Check latency
            if evaluation["latency_ms"] > 4000:
                evaluation["issues"].append(f"High latency: {evaluation['latency_ms']:.0f}ms")

            # Mark as passed if no major issues
            if not evaluation["issues"] and evaluation["result_count"] > 0:
                evaluation["passed"] = True

        return evaluation

    def run_all_tests(self) -> Dict:
        """Run all acceptance tests."""
        self.start_time = datetime.now()
        print(f"Starting CRE Acceptance Test Suite")
        print(f"Time: {self.start_time.isoformat()}")
        print(f"Total Tests: {len(ACCEPTANCE_TESTS)}")
        print("=" * 80)

        summary = {
            "passed": 0,
            "failed": 0,
            "total": len(ACCEPTANCE_TESTS),
            "by_category": {}
        }

        for test in ACCEPTANCE_TESTS:
            print(f"\n{test['id']}: {test['name']}")
            print(f"Query: {test['query']}")

            # Run query
            success, response = self.query_knowledge_base(test["query"])

            if success:
                # Evaluate results
                evaluation = self.evaluate_test(test, response)
                self.results.append(evaluation)

                # Update summary
                if evaluation["passed"]:
                    summary["passed"] += 1
                    print(f"✅ PASSED | Results: {evaluation['result_count']} | Latency: {evaluation['latency_ms']:.0f}ms")
                else:
                    summary["failed"] += 1
                    print(f"❌ FAILED | Results: {evaluation['result_count']} | Issues: {', '.join(evaluation['issues'])}")

                # Categorize
                if test['id'].startswith('Q1') and test['id'] <= 'Q14':
                    category = "single-object"
                elif test['id'] >= 'Q15' and test['id'] <= 'Q19':
                    category = "cross-object"
                else:
                    category = "edge-case"

                if category not in summary["by_category"]:
                    summary["by_category"][category] = {"passed": 0, "failed": 0}

                if evaluation["passed"]:
                    summary["by_category"][category]["passed"] += 1
                else:
                    summary["by_category"][category]["failed"] += 1
            else:
                print(f"❌ ERROR: Query failed - {response.get('error', 'Unknown error')}")
                summary["failed"] += 1

            # Small delay between tests
            time.sleep(0.5)

        self.end_time = datetime.now()
        summary["duration_seconds"] = (self.end_time - self.start_time).total_seconds()
        summary["pass_rate"] = (summary["passed"] / summary["total"]) * 100

        return summary

    def generate_report(self, summary: Dict) -> str:
        """Generate detailed markdown report."""
        report = []
        report.append("# CRE Acceptance Test Report")
        report.append(f"**Date**: {self.start_time.isoformat()}")
        report.append(f"**Duration**: {summary['duration_seconds']:.1f} seconds")
        report.append(f"**Knowledge Base**: {KNOWLEDGE_BASE_ID}")
        report.append("")

        # Executive Summary
        report.append("## Executive Summary")
        report.append(f"- **Total Tests**: {summary['total']}")
        report.append(f"- **Pass Rate**: {summary['pass_rate']:.1f}%")
        report.append(f"- **Passed**: {summary['passed']}")
        report.append(f"- **Failed**: {summary['failed']}")
        report.append("")

        # Category Breakdown
        report.append("## Results by Category")
        report.append("")
        report.append("| Category | Pass Rate | Passed | Failed | Total |")
        report.append("|----------|-----------|--------|--------|-------|")

        for category, stats in summary["by_category"].items():
            total = stats["passed"] + stats["failed"]
            pass_rate = (stats["passed"] / total * 100) if total > 0 else 0
            report.append(f"| {category} | {pass_rate:.0f}% | {stats['passed']} | {stats['failed']} | {total} |")

        report.append("")

        # Performance Metrics
        latencies = [r["latency_ms"] for r in self.results if "latency_ms" in r]
        if latencies:
            report.append("## Performance Metrics")
            report.append(f"- **Average Latency**: {sum(latencies)/len(latencies):.0f}ms")
            report.append(f"- **Max Latency**: {max(latencies):.0f}ms")
            report.append(f"- **Min Latency**: {min(latencies):.0f}ms")
            p95_index = int(len(sorted(latencies)) * 0.95)
            report.append(f"- **P95 Latency**: {sorted(latencies)[p95_index-1]:.0f}ms")
            report.append("")

        # Detailed Results
        report.append("## Detailed Test Results")
        report.append("")

        for result in self.results:
            status = "✅" if result["passed"] else "❌"
            report.append(f"### {result['test_id']}: {result['test_name']} {status}")
            report.append(f"**Query**: {result['query']}")
            report.append(f"**Results**: {result['result_count']} | **Latency**: {result['latency_ms']:.0f}ms | **Top Score**: {result['top_score']:.3f}")

            if result.get("issues"):
                report.append("**Issues**:")
                for issue in result["issues"]:
                    report.append(f"- {issue}")

            report.append("")

        # Recommendations
        report.append("## Recommendations")

        if summary["by_category"].get("cross-object", {}).get("failed", 0) > 2:
            report.append("- **Critical**: Cross-object queries are failing. Implement relationship enrichment in chunking.")

        if summary["pass_rate"] < 70:
            report.append("- **High Priority**: Overall pass rate below 70% target. Review chunking and indexing strategy.")

        avg_latency = sum(latencies)/len(latencies) if latencies else 0
        if avg_latency > 2000:
            report.append("- **Performance**: Average latency above 2s. Consider caching or query optimization.")

        return "\n".join(report)


def main():
    """Run acceptance tests and generate report."""
    runner = AcceptanceTestRunner()

    # Run tests
    summary = runner.run_all_tests()

    # Print summary
    print("\n" + "=" * 80)
    print("ACCEPTANCE TEST SUMMARY")
    print("=" * 80)
    print(f"Pass Rate: {summary['pass_rate']:.1f}%")
    print(f"Passed: {summary['passed']}/{summary['total']}")
    print(f"Duration: {summary['duration_seconds']:.1f} seconds")

    print("\nBy Category:")
    for category, stats in summary["by_category"].items():
        total = stats["passed"] + stats["failed"]
        pass_rate = (stats["passed"] / total * 100) if total > 0 else 0
        print(f"  {category}: {pass_rate:.0f}% ({stats['passed']}/{total})")

    # Generate and save report
    report = runner.generate_report(summary)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"acceptance_test_report_{timestamp}.md"

    with open(report_file, 'w') as f:
        f.write(report)

    print(f"\n📄 Detailed report saved to: {report_file}")

    # Exit code based on pass rate
    if summary['pass_rate'] >= 70:
        print("\n✅ ACCEPTANCE CRITERIA MET (≥70% pass rate)")
        sys.exit(0)
    else:
        print(f"\n❌ ACCEPTANCE CRITERIA NOT MET (Required: 70%, Actual: {summary['pass_rate']:.1f}%)")
        sys.exit(1)


if __name__ == "__main__":
    main()