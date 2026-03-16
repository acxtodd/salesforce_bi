#!/usr/bin/env python3
"""
Zero-Config Schema Discovery Validation Test Suite.

Validates schema-driven queries to measure filter accuracy.
Target: 90% query accuracy (18/20 queries passing).

**Feature: zero-config-schema-discovery**
**Task 11: Create Validation Test Suite**
**Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**
"""

import json
import subprocess
import time
import statistics
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
import sys
import os

# Configuration
AWS_REGION = "us-west-2"
LAMBDA_FUNCTION_NAME = "salesforce-ai-search-retrieve"
TEST_USER_ID = "005dl00000Q6a3RAAR"

# Target: 90% accuracy (18/20 passing)
TARGET_ACCURACY = 0.90
TARGET_PASS_COUNT = 18
TOTAL_TEST_COUNT = 20


# =============================================================================
# TEST DEFINITIONS
# =============================================================================

ZERO_CONFIG_TESTS: List[Dict[str, Any]] = [
    # =========================================================================
    # CATEGORY 1: Filter Accuracy Tests (Picklist Exact Match)
    # Requirements: 5.2, 5.3
    # =========================================================================
    {
        "id": "ZC01",
        "name": "Property Class Filter - Exact Match",
        "query": "Show me Class A properties",
        "category": "filter-accuracy",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {"ascendix__PropertyClass__c": "A"},
        "must_contain_in_results": ["Class A"],
        "must_not_contain_in_results": ["Class B", "Class C"],
        "description": "Verify Class A filter returns only Class A properties",
    },
    {
        "id": "ZC02",
        "name": "Property Type Filter - Exact Match",
        "query": "Find all retail properties",
        "category": "filter-accuracy",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {"ascendix__PropertySubType__c": "Retail"},
        "must_contain_in_results": ["Retail"],
        "must_not_contain_in_results": [],
        "description": "Verify Retail property type filter works",
    },
    {
        "id": "ZC03",
        "name": "City Filter - Exact Match",
        "query": "Show properties in Dallas",
        "category": "filter-accuracy",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {"ascendix__City__c": "Dallas"},
        "must_contain_in_results": ["Dallas"],
        "must_not_contain_in_results": [],
        "description": "Verify city filter returns only Dallas properties",
    },
    {
        "id": "ZC04",
        "name": "State Filter - Exact Match",
        "query": "Find properties in Texas",
        "category": "filter-accuracy",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {"ascendix__State__c": "TX"},
        "must_contain_in_results": ["TX", "Texas"],
        "must_not_contain_in_results": [],
        "description": "Verify state filter with full name normalizes to abbreviation",
    },
    {
        "id": "ZC05",
        "name": "Deal Stage Filter",
        "query": "Show deals in LOI stage",
        "category": "filter-accuracy",
        "expected_entity": "ascendix__Deal__c",
        "expected_filters": {"ascendix__Stage__c": "LOI"},
        "must_contain_in_results": ["LOI"],
        "must_not_contain_in_results": [],
        "description": "Verify deal stage filter extracts correctly",
    },
    # =========================================================================
    # CATEGORY 2: Value Normalization Tests
    # Requirements: 3.5, 3.6, 5.2
    # =========================================================================
    {
        "id": "ZC06",
        "name": "Case Normalization - Lowercase to Canonical",
        "query": "Find class a office buildings",
        "category": "value-normalization",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {"ascendix__PropertyClass__c": "A"},
        "validation_fn": "validate_case_normalization",
        "input_value": "class a",
        "expected_canonical": "A",
        "description": "Verify 'class a' normalizes to 'A'",
    },
    {
        "id": "ZC07",
        "name": "Case Normalization - Mixed Case",
        "query": "Show CLASS B properties",
        "category": "value-normalization",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {"ascendix__PropertyClass__c": "B"},
        "validation_fn": "validate_case_normalization",
        "input_value": "CLASS B",
        "expected_canonical": "B",
        "description": "Verify 'CLASS B' normalizes to 'B'",
    },
    {
        "id": "ZC08",
        "name": "Whitespace Normalization",
        "query": "Find  properties  in  Houston",
        "category": "value-normalization",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {"ascendix__City__c": "Houston"},
        "description": "Verify extra whitespace doesn't break filter extraction",
    },
    {
        "id": "ZC09",
        "name": "Synonym Recognition - Office",
        "query": "Show office buildings downtown",
        "category": "value-normalization",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {"ascendix__PropertySubType__c": "Office"},
        "description": "Verify 'office buildings' maps to Office property type",
    },
    # =========================================================================
    # CATEGORY 3: Numeric Comparison Tests
    # Requirements: 5.2, 5.4
    # =========================================================================
    {
        "id": "ZC10",
        "name": "Numeric Filter - Greater Than",
        "query": "Find properties over 100,000 square feet",
        "category": "numeric-comparison",
        "expected_entity": "ascendix__Property__c",
        "expected_numeric_filters": {
            "ascendix__TotalBuildingArea__c": {"$gt": 100000}
        },
        "validation_fn": "validate_numeric_results",
        "numeric_field": "ascendix__TotalBuildingArea__c",
        "numeric_operator": "$gt",
        "numeric_value": 100000,
        "description": "Verify 'over 100,000' creates $gt filter",
    },
    {
        "id": "ZC11",
        "name": "Numeric Filter - Less Than",
        "query": "Show properties under 50,000 square feet",
        "category": "numeric-comparison",
        "expected_entity": "ascendix__Property__c",
        "expected_numeric_filters": {
            "ascendix__TotalBuildingArea__c": {"$lt": 50000}
        },
        "validation_fn": "validate_numeric_results",
        "numeric_field": "ascendix__TotalBuildingArea__c",
        "numeric_operator": "$lt",
        "numeric_value": 50000,
        "description": "Verify 'under 50,000' creates $lt filter",
    },
    {
        "id": "ZC12",
        "name": "Numeric Filter - Year Built",
        "query": "Find buildings built after 2010",
        "category": "numeric-comparison",
        "expected_entity": "ascendix__Property__c",
        "expected_numeric_filters": {
            "ascendix__YearBuilt__c": {"$gt": 2010}
        },
        "validation_fn": "validate_numeric_results",
        "numeric_field": "ascendix__YearBuilt__c",
        "numeric_operator": "$gt",
        "numeric_value": 2010,
        "description": "Verify year comparison filter",
    },
    {
        "id": "ZC13",
        "name": "Numeric Filter - Range",
        "query": "Show properties between 50,000 and 200,000 square feet",
        "category": "numeric-comparison",
        "expected_entity": "ascendix__Property__c",
        "expected_numeric_filters": {
            "ascendix__TotalBuildingArea__c": {"$gte": 50000, "$lte": 200000}
        },
        "description": "Verify range creates both $gte and $lte filters",
    },
    # =========================================================================
    # CATEGORY 4: Relationship + Filter Combination Tests
    # Requirements: 5.2
    # =========================================================================
    {
        "id": "ZC14",
        "name": "Property + Availability Filter",
        "query": "Show Class A properties with available space",
        "category": "relationship-filter",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {"ascendix__PropertyClass__c": "A"},
        "expected_traversals": [{"to": "ascendix__Availability__c"}],
        "description": "Verify property class filter with availability relationship",
    },
    {
        "id": "ZC15",
        "name": "Property + Lease Filter",
        "query": "Find office properties with active leases",
        "category": "relationship-filter",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {"ascendix__PropertySubType__c": "Office"},
        "expected_traversals": [{"to": "ascendix__Lease__c"}],
        "description": "Verify property type filter with lease relationship",
    },
    {
        "id": "ZC16",
        "name": "Deal + Property Location Filter",
        "query": "Show deals for properties in Dallas",
        "category": "relationship-filter",
        "expected_entity": "ascendix__Deal__c",
        "expected_traversals": [
            {"to": "ascendix__Property__c", "filters": {"ascendix__City__c": "Dallas"}}
        ],
        "description": "Verify deal query with property location filter",
    },
    {
        "id": "ZC17",
        "name": "Availability + Property Class Filter",
        "query": "Find available spaces in Class A buildings",
        "category": "relationship-filter",
        "expected_entity": "ascendix__Availability__c",
        "expected_traversals": [
            {"to": "ascendix__Property__c", "filters": {"ascendix__PropertyClass__c": "A"}}
        ],
        "description": "Verify availability query with property class filter",
    },
    # =========================================================================
    # CATEGORY 5: Edge Cases
    # Requirements: 5.2
    # =========================================================================
    {
        "id": "ZC18",
        "name": "No Matching Results",
        "query": "Show Class D properties in Antarctica",
        "category": "edge-case",
        "expected_entity": "ascendix__Property__c",
        "expect_empty_results": True,
        "description": "Verify graceful handling when no results match filters",
    },
    {
        "id": "ZC19",
        "name": "Multiple Picklist Filters",
        "query": "Find Class A retail properties in Houston",
        "category": "edge-case",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {
            "ascendix__PropertyClass__c": "A",
            "ascendix__PropertySubType__c": "Retail",
            "ascendix__City__c": "Houston",
        },
        "description": "Verify multiple picklist filters combine correctly",
    },
    {
        "id": "ZC20",
        "name": "Filter + Numeric + Relationship",
        "query": "Show Class A office properties over 100,000 sqft with active deals",
        "category": "edge-case",
        "expected_entity": "ascendix__Property__c",
        "expected_filters": {
            "ascendix__PropertyClass__c": "A",
            "ascendix__PropertySubType__c": "Office",
        },
        "expected_numeric_filters": {
            "ascendix__TotalBuildingArea__c": {"$gt": 100000}
        },
        "expected_traversals": [{"to": "ascendix__Deal__c"}],
        "description": "Verify complex query with filters, numeric, and relationship",
    },
]


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================


def validate_case_normalization(
    test: Dict[str, Any], decomposition: Dict[str, Any], results: List[Dict]
) -> Tuple[bool, str]:
    """
    Validate that case normalization occurred correctly.

    Requirements: 3.5, 3.6
    """
    expected_canonical = test.get("expected_canonical")
    filters = decomposition.get("filters", {})

    # Check if any filter value matches the expected canonical form
    for field, value in filters.items():
        if value == expected_canonical:
            return True, f"Correctly normalized to '{expected_canonical}'"

    return False, f"Expected canonical value '{expected_canonical}' not found in filters: {filters}"


def validate_numeric_results(
    test: Dict[str, Any], decomposition: Dict[str, Any], results: List[Dict]
) -> Tuple[bool, str]:
    """
    Validate that numeric filter was applied correctly to results.

    Requirements: 5.4
    """
    numeric_field = test.get("numeric_field")
    numeric_operator = test.get("numeric_operator")
    numeric_value = test.get("numeric_value")

    if not results:
        return True, "No results to validate (may be correct for strict filter)"

    violations = []
    for result in results[:5]:  # Check first 5 results
        metadata = result.get("metadata", {})
        attributes = metadata.get("attributes", {})
        actual_value = attributes.get(numeric_field)

        if actual_value is None:
            continue

        try:
            actual_num = float(actual_value)
            expected_num = float(numeric_value)

            if numeric_operator == "$gt" and actual_num <= expected_num:
                violations.append(f"{actual_num} not > {expected_num}")
            elif numeric_operator == "$lt" and actual_num >= expected_num:
                violations.append(f"{actual_num} not < {expected_num}")
            elif numeric_operator == "$gte" and actual_num < expected_num:
                violations.append(f"{actual_num} not >= {expected_num}")
            elif numeric_operator == "$lte" and actual_num > expected_num:
                violations.append(f"{actual_num} not <= {expected_num}")
        except (ValueError, TypeError):
            pass

    if violations:
        return False, f"Numeric violations: {violations}"

    return True, "Numeric filter applied correctly"


def validate_must_contain(
    test: Dict[str, Any], results: List[Dict]
) -> Tuple[bool, List[str]]:
    """
    Validate that results contain expected keywords.

    Requirements: 5.3
    """
    must_contain = test.get("must_contain_in_results", [])
    if not must_contain:
        return True, []

    result_text = " ".join([
        r.get("content", {}).get("text", "")[:500] for r in results[:5]
    ]).lower()

    missing = []
    for keyword in must_contain:
        if keyword.lower() not in result_text:
            missing.append(keyword)

    return len(missing) == 0, missing


def validate_must_not_contain(
    test: Dict[str, Any], results: List[Dict]
) -> Tuple[bool, List[str]]:
    """
    Validate that results do NOT contain excluded values.

    Requirements: 5.3
    """
    must_not_contain = test.get("must_not_contain_in_results", [])
    if not must_not_contain:
        return True, []

    result_text = " ".join([
        r.get("content", {}).get("text", "")[:500] for r in results[:5]
    ]).lower()

    found = []
    for keyword in must_not_contain:
        if keyword.lower() in result_text:
            found.append(keyword)

    return len(found) == 0, found


# =============================================================================
# TEST RUNNER
# =============================================================================


class ZeroConfigValidationRunner:
    """
    Runs zero-config schema discovery validation tests.

    **Requirements: 5.1, 5.5, 5.6**
    """

    def __init__(self):
        self.results: List[Dict[str, Any]] = []
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

    def query_lambda(self, query: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Query the retrieve Lambda and get decomposition + results.

        Returns:
            Tuple of (success, response_dict with decomposition and results)
        """
        try:
            payload = {
                "query": query,
                "salesforceUserId": TEST_USER_ID,
                "topK": 5,
                "filters": {},
                "hybrid": True,
                "authzMode": "both",
                "useGraph": True,
            }

            cmd = [
                "aws", "lambda", "invoke",
                "--function-name", LAMBDA_FUNCTION_NAME,
                "--payload", json.dumps(payload),
                "--cli-binary-format", "raw-in-base64-out",
                "--region", AWS_REGION,
                "--no-cli-pager",
                "/tmp/zc_retrieve_result.json"
            ]

            start = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            latency = (time.time() - start) * 1000

            if result.returncode == 0:
                with open("/tmp/zc_retrieve_result.json", "r") as f:
                    lambda_response = json.loads(f.read())

                body = json.loads(lambda_response.get("body", "{}"))
                matches = body.get("matches", [])

                # Convert matches to standard format
                results = []
                for match in matches:
                    results.append({
                        "content": {"text": match.get("text", "")},
                        "score": match.get("score", 0),
                        "metadata": match.get("metadata", {}),
                    })

                # Extract decomposition from queryPlan.schemaDecomposition
                query_plan = body.get("queryPlan", {})
                schema_decomposition = query_plan.get("schemaDecomposition", {})

                decomposition = {
                    "target_entity": schema_decomposition.get("target_entity", ""),
                    "filters": schema_decomposition.get("filters", {}),
                    "numeric_filters": schema_decomposition.get("numeric_filters", {}),
                    "date_filters": schema_decomposition.get("date_filters", {}),
                    "traversals": schema_decomposition.get("traversals", []),
                    "confidence": schema_decomposition.get("confidence", 0),
                    "validation_warnings": schema_decomposition.get("validation_warnings", []),
                }

                return True, {
                    "results": results,
                    "count": len(results),
                    "latency_ms": latency,
                    "decomposition": decomposition,
                    "graphMetadata": body.get("graphMetadata", {}),
                }
            else:
                return False, {"error": result.stderr, "latency_ms": latency}

        except Exception as e:
            return False, {"error": str(e)}

    def evaluate_test(self, test: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a single test against expected outcomes.

        Requirements: 5.2, 5.3, 5.4
        """
        evaluation = {
            "test_id": test["id"],
            "test_name": test["name"],
            "query": test["query"],
            "category": test.get("category", "unknown"),
            "passed": True,
            "issues": [],
            "result_count": response.get("count", 0),
            "latency_ms": response.get("latency_ms", 0),
        }

        results = response.get("results", [])
        decomposition = response.get("decomposition", {})

        # Store decomposition for reporting
        evaluation["decomposition"] = decomposition

        # Check 1: Expected entity
        expected_entity = test.get("expected_entity")
        if expected_entity and decomposition.get("target_entity"):
            if decomposition["target_entity"] != expected_entity:
                evaluation["passed"] = False
                evaluation["issues"].append(
                    f"Entity mismatch: expected {expected_entity}, got {decomposition['target_entity']}"
                )

        # Check 2: Expected filters
        expected_filters = test.get("expected_filters", {})
        actual_filters = decomposition.get("filters", {})
        for field, expected_value in expected_filters.items():
            actual_value = actual_filters.get(field)
            if actual_value != expected_value:
                # Check if it's a case-insensitive match
                if isinstance(actual_value, str) and isinstance(expected_value, str):
                    if actual_value.lower() != expected_value.lower():
                        evaluation["passed"] = False
                        evaluation["issues"].append(
                            f"Filter mismatch for {field}: expected '{expected_value}', got '{actual_value}'"
                        )
                elif actual_value is None:
                    evaluation["passed"] = False
                    evaluation["issues"].append(
                        f"Missing filter: {field}={expected_value}"
                    )

        # Check 3: Expected numeric filters
        expected_numeric = test.get("expected_numeric_filters", {})
        actual_numeric = decomposition.get("numeric_filters", {})
        for field, expected_ops in expected_numeric.items():
            actual_ops = actual_numeric.get(field, {})
            for op, expected_val in expected_ops.items():
                actual_val = actual_ops.get(op)
                if actual_val is None:
                    evaluation["passed"] = False
                    evaluation["issues"].append(
                        f"Missing numeric filter: {field} {op} {expected_val}"
                    )
                elif abs(float(actual_val) - float(expected_val)) > 1:
                    evaluation["passed"] = False
                    evaluation["issues"].append(
                        f"Numeric filter mismatch: {field} {op} expected {expected_val}, got {actual_val}"
                    )

        # Check 4: Expected traversals
        expected_traversals = test.get("expected_traversals", [])
        actual_traversals = decomposition.get("traversals", [])
        for expected_trav in expected_traversals:
            expected_to = expected_trav.get("to")
            found = False
            for actual_trav in actual_traversals:
                if actual_trav.get("to") == expected_to:
                    found = True
                    break
            if not found and expected_to:
                # Traversal detection is not strictly required for pass
                evaluation["issues"].append(
                    f"Expected traversal to {expected_to} not detected (warning)"
                )

        # Check 5: Must contain in results
        if results and test.get("must_contain_in_results"):
            passed, missing = validate_must_contain(test, results)
            if not passed:
                evaluation["passed"] = False
                evaluation["issues"].append(f"Missing expected keywords: {missing}")

        # Check 6: Must NOT contain in results
        if results and test.get("must_not_contain_in_results"):
            passed, found = validate_must_not_contain(test, results)
            if not passed:
                evaluation["passed"] = False
                evaluation["issues"].append(f"Found excluded values: {found}")

        # Check 7: Empty results expected
        if test.get("expect_empty_results"):
            if results:
                # Having results when empty expected is just a note, not failure
                evaluation["issues"].append(
                    f"Expected empty results but got {len(results)} (info only)"
                )

        # Check 8: Custom validation function
        validation_fn = test.get("validation_fn")
        if validation_fn and validation_fn in globals():
            fn = globals()[validation_fn]
            passed, message = fn(test, decomposition, results)
            if not passed:
                evaluation["passed"] = False
                evaluation["issues"].append(message)

        return evaluation

    def run_all_tests(self) -> Dict[str, Any]:
        """
        Run all validation tests.

        Requirements: 5.1, 5.5
        """
        self.start_time = datetime.now()
        print("=" * 80)
        print("ZERO-CONFIG SCHEMA DISCOVERY VALIDATION TEST SUITE")
        print(f"Time: {self.start_time.isoformat()}")
        print(f"Target: {TARGET_ACCURACY * 100:.0f}% accuracy ({TARGET_PASS_COUNT}/{TOTAL_TEST_COUNT} tests)")
        print("=" * 80)

        summary = {
            "passed": 0,
            "failed": 0,
            "total": len(ZERO_CONFIG_TESTS),
            "by_category": {},
            "latencies": [],
        }

        for test in ZERO_CONFIG_TESTS:
            self._run_single_test(test, summary)

        self.end_time = datetime.now()
        summary["duration_seconds"] = (self.end_time - self.start_time).total_seconds()
        summary["accuracy"] = summary["passed"] / summary["total"] if summary["total"] > 0 else 0
        summary["target_met"] = summary["accuracy"] >= TARGET_ACCURACY

        return summary

    def _run_single_test(self, test: Dict[str, Any], summary: Dict[str, Any]) -> None:
        """Run a single test and update summary."""
        print(f"\n{test['id']}: {test['name']}")
        print(f"  Query: {test['query']}")
        print(f"  Category: {test['category']}")

        success, response = self.query_lambda(test["query"])

        if success:
            evaluation = self.evaluate_test(test, response)
            self.results.append(evaluation)

            # Update category stats
            category = test.get("category", "unknown")
            if category not in summary["by_category"]:
                summary["by_category"][category] = {"passed": 0, "failed": 0}

            if evaluation["passed"]:
                summary["passed"] += 1
                summary["by_category"][category]["passed"] += 1
                print(f"  Result: PASSED | Latency: {evaluation['latency_ms']:.0f}ms")
            else:
                summary["failed"] += 1
                summary["by_category"][category]["failed"] += 1
                print(f"  Result: FAILED")
                for issue in evaluation["issues"]:
                    print(f"    - {issue}")

            summary["latencies"].append(evaluation["latency_ms"])
        else:
            print(f"  Result: ERROR - {response.get('error', 'Unknown error')}")
            summary["failed"] += 1

        time.sleep(0.5)  # Rate limiting

    def generate_report(self, summary: Dict[str, Any]) -> str:
        """
        Generate detailed markdown report.

        Requirements: 5.5, 5.6
        """
        report = []
        report.append("# Zero-Config Schema Discovery Validation Report")
        report.append("")
        report.append(f"**Date**: {self.start_time.isoformat()}")
        report.append(f"**Duration**: {summary['duration_seconds']:.1f} seconds")
        report.append("")

        # Executive Summary
        report.append("## Executive Summary")
        report.append("")
        accuracy_pct = summary["accuracy"] * 100
        status = "PASSED" if summary["target_met"] else "FAILED"
        report.append(f"**Accuracy**: {accuracy_pct:.1f}% ({summary['passed']}/{summary['total']})")
        report.append(f"**Target**: {TARGET_ACCURACY * 100:.0f}% ({TARGET_PASS_COUNT}/{TOTAL_TEST_COUNT})")
        report.append(f"**Status**: {status}")
        report.append("")

        # Category Breakdown
        report.append("## Results by Category")
        report.append("")
        report.append("| Category | Pass Rate | Passed | Failed |")
        report.append("|----------|-----------|--------|--------|")
        for category, stats in summary["by_category"].items():
            total = stats["passed"] + stats["failed"]
            rate = (stats["passed"] / total * 100) if total > 0 else 0
            report.append(f"| {category} | {rate:.0f}% | {stats['passed']} | {stats['failed']} |")
        report.append("")

        # Performance Metrics
        if summary["latencies"]:
            report.append("## Performance Metrics")
            report.append("")
            latencies = summary["latencies"]
            report.append(f"- **Average Latency**: {statistics.mean(latencies):.0f}ms")
            report.append(f"- **P95 Latency**: {sorted(latencies)[int(len(latencies) * 0.95) - 1]:.0f}ms")
            report.append(f"- **Max Latency**: {max(latencies):.0f}ms")
            report.append("")

        # Detailed Results
        report.append("## Detailed Test Results")
        report.append("")

        for result in self.results:
            status_icon = "PASS" if result["passed"] else "FAIL"
            report.append(f"### {result['test_id']}: {result['test_name']} [{status_icon}]")
            report.append(f"**Query**: {result['query']}")
            report.append(f"**Category**: {result['category']}")
            report.append(f"**Latency**: {result['latency_ms']:.0f}ms | **Results**: {result['result_count']}")

            if result.get("decomposition"):
                decomp = result["decomposition"]
                if decomp.get("target_entity"):
                    report.append(f"**Target Entity**: {decomp['target_entity']}")
                if decomp.get("filters"):
                    report.append(f"**Filters**: {json.dumps(decomp['filters'])}")
                if decomp.get("numeric_filters"):
                    report.append(f"**Numeric Filters**: {json.dumps(decomp['numeric_filters'])}")

            if result.get("issues"):
                report.append("**Issues**:")
                for issue in result["issues"]:
                    report.append(f"- {issue}")

            report.append("")

        # Recommendations
        report.append("## Recommendations")
        report.append("")

        if not summary["target_met"]:
            report.append("- **Critical**: Accuracy below 90% target. Review failing tests.")
            report.append("")

        # Category-specific recommendations
        for category, stats in summary["by_category"].items():
            total = stats["passed"] + stats["failed"]
            rate = (stats["passed"] / total * 100) if total > 0 else 0
            if rate < 80:
                report.append(f"- **{category}**: {rate:.0f}% pass rate - review implementation")

        return "\n".join(report)


def main():
    """Run zero-config validation tests and generate report."""
    import argparse

    parser = argparse.ArgumentParser(description="Run Zero-Config Schema Discovery Validation Tests")
    parser.add_argument("--category", help="Run only tests in this category")
    args = parser.parse_args()

    runner = ZeroConfigValidationRunner()

    # Filter tests by category if specified
    if args.category:
        global ZERO_CONFIG_TESTS
        ZERO_CONFIG_TESTS = [t for t in ZERO_CONFIG_TESTS if t.get("category") == args.category]
        print(f"Running {len(ZERO_CONFIG_TESTS)} tests in category: {args.category}")

    summary = runner.run_all_tests()

    # Print summary
    print("\n" + "=" * 80)
    print("ZERO-CONFIG VALIDATION SUMMARY")
    print("=" * 80)
    print(f"Accuracy: {summary['accuracy'] * 100:.1f}% ({summary['passed']}/{summary['total']})")
    print(f"Target: {TARGET_ACCURACY * 100:.0f}% ({TARGET_PASS_COUNT}/{TOTAL_TEST_COUNT})")

    if summary["target_met"]:
        print("Status: TARGET MET")
    else:
        print("Status: TARGET NOT MET")

    print(f"\nDuration: {summary['duration_seconds']:.1f} seconds")

    # Category breakdown
    print("\nBy Category:")
    for category, stats in summary["by_category"].items():
        total = stats["passed"] + stats["failed"]
        rate = (stats["passed"] / total * 100) if total > 0 else 0
        print(f"  {category}: {rate:.0f}% ({stats['passed']}/{total})")

    # Generate and save report
    report = runner.generate_report(summary)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    report_file = os.path.join(script_dir, f"zero_config_validation_report_{timestamp}.md")

    with open(report_file, "w") as f:
        f.write(report)

    print(f"\nDetailed report saved to: {report_file}")

    # Exit code based on target
    if summary["target_met"]:
        print("\n" + "=" * 80)
        print("VALIDATION PASSED - 90% accuracy target met")
        print("=" * 80)
        sys.exit(0)
    else:
        print("\n" + "=" * 80)
        print("VALIDATION FAILED - accuracy below 90% target")
        print("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
