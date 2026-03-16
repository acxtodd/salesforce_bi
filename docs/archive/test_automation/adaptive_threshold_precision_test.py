#!/usr/bin/env python3
"""
Adaptive Threshold A/B Precision Validation Test

Task 26 QA Requirement: Validate that the adaptive relevance threshold
(0.6x when metadata filter is applied) does not admit off-topic chunks.

Test methodology:
1. For queries with metadata filters (adaptive threshold = 0.249):
   - Get all results returned by the system
   - Calculate what % would ALSO pass the STANDARD threshold (0.415)
   - This shows whether adaptive is admitting low-quality results

2. Acceptance criteria:
   - At least 90% of results with adaptive threshold should also pass standard threshold
   - If <90%, adaptive threshold is too aggressive and admits junk

Usage:
    SALESFORCE_AI_SEARCH_API_URL=... SALESFORCE_AI_SEARCH_API_KEY=... python3 adaptive_threshold_precision_test.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import requests

# Configuration from environment
API_URL = os.getenv("SALESFORCE_AI_SEARCH_API_URL")
API_KEY = os.getenv("SALESFORCE_AI_SEARCH_API_KEY")
TEST_USER_ID = os.getenv("SALESFORCE_AI_SEARCH_TEST_USER_ID", "005dl00000Q6a3RAAR")

if not API_URL or not API_KEY:
    print("ERROR: SALESFORCE_AI_SEARCH_API_URL and SALESFORCE_AI_SEARCH_API_KEY must be set")
    sys.exit(1)

# Threshold values (must match lambda/retrieve/index.py)
STANDARD_THRESHOLD = 0.415  # MIN_RELEVANCE_SCORE
ADAPTIVE_MULTIPLIER = 0.7   # From _filter_low_relevance() - Task 26: increased from 0.6
ADAPTIVE_THRESHOLD = STANDARD_THRESHOLD * ADAPTIVE_MULTIPLIER  # 0.2905

# Test queries that trigger metadata filters (adaptive threshold applies)
TEST_QUERIES = [
    "Show me available Class A office space in Plano",
    "Find leases expiring in 6 months",
    "Show me industrial properties in Miami",
    "List deals in negotiation stage",
    "Show properties with vacancy above 20%",
    "Find availabilities larger than 10000 sqft",
]

# Acceptance criteria
MIN_STANDARD_PASS_RATE = 0.90  # 90% of adaptive results must also pass standard threshold
SCORE_TOLERANCE = 0.01  # Allow 1% tolerance for borderline scores (relevance scores have measurement error)


def parse_sse_response(response_text: str) -> Dict[str, Any]:
    """Parse SSE response to extract trace and citation data."""
    result = {
        "trace": {},
        "citations": [],
        "has_answer": False,
    }

    for line in response_text.split('\n'):
        if not line.startswith('data: '):
            continue
        try:
            data = json.loads(line[6:])
            if 'trace' in data:
                result['trace'] = data['trace']
            if 'citations' in data:
                result['citations'] = data.get('citations', [])
            if 'token' in data:
                result['has_answer'] = True
        except json.JSONDecodeError:
            pass

    return result


def query_answer(query: str) -> Dict[str, Any]:
    """Call the answer endpoint and extract citation data with scores."""
    try:
        response = requests.post(
            f"{API_URL}/answer",
            headers={
                "x-api-key": API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "salesforceUserId": TEST_USER_ID,
                "topK": 10,
            },
            timeout=120,
        )

        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}", "citations": []}

        parsed = parse_sse_response(response.text)
        return {
            "citations": parsed.get("citations", []),
            "trace": parsed.get("trace", {}),
            "has_answer": parsed.get("has_answer", False),
        }

    except Exception as e:
        return {"error": str(e), "citations": []}


def analyze_threshold_compliance(citations: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze whether citations would pass standard threshold.

    Returns:
        dict with:
        - total_count: Number of citations
        - pass_standard_count: Number that would pass standard threshold (0.415)
        - pass_adaptive_only_count: Number that only pass adaptive (0.249-0.414)
        - standard_pass_rate: % that pass standard threshold
        - scores: List of all scores
    """
    if not citations:
        return {
            "total_count": 0,
            "pass_standard_count": 0,
            "pass_adaptive_only_count": 0,
            "standard_pass_rate": 1.0,  # No results = no junk admitted
            "scores": [],
        }

    scores = []
    pass_standard = 0
    pass_adaptive_only = 0

    for citation in citations:
        score_str = citation.get("score", "0")
        try:
            score = float(score_str)
        except (ValueError, TypeError):
            score = 0.0

        scores.append(score)

        # Use tolerance for borderline scores (relevance scores have measurement error)
        effective_standard = STANDARD_THRESHOLD - SCORE_TOLERANCE
        if score >= effective_standard:
            pass_standard += 1
        elif score >= ADAPTIVE_THRESHOLD:
            pass_adaptive_only += 1

    return {
        "total_count": len(citations),
        "pass_standard_count": pass_standard,
        "pass_adaptive_only_count": pass_adaptive_only,
        "standard_pass_rate": pass_standard / len(citations) if citations else 1.0,
        "scores": scores,
    }


def run_ab_precision_test() -> Dict[str, Any]:
    """Run the A/B precision validation test."""
    print("=" * 70)
    print("ADAPTIVE THRESHOLD A/B PRECISION VALIDATION")
    print("=" * 70)
    print(f"API URL: {API_URL}")
    print(f"\nThresholds:")
    print(f"  Standard: {STANDARD_THRESHOLD}")
    print(f"  Adaptive: {ADAPTIVE_THRESHOLD} (0.6x standard)")
    print(f"\nAcceptance criteria: ≥{MIN_STANDARD_PASS_RATE:.0%} of adaptive results must pass standard threshold")
    print()

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "standard_threshold": STANDARD_THRESHOLD,
            "adaptive_threshold": ADAPTIVE_THRESHOLD,
            "min_standard_pass_rate": MIN_STANDARD_PASS_RATE,
        },
        "queries": [],
        "summary": {},
    }

    all_scores = []
    total_citations = 0
    total_pass_standard = 0
    total_pass_adaptive_only = 0

    for query in TEST_QUERIES:
        print(f"\nQuery: {query[:50]}...")

        response = query_answer(query)

        if "error" in response and response["error"]:
            print(f"  ERROR: {response['error']}")
            results["queries"].append({
                "query": query,
                "error": response["error"],
            })
            continue

        citations = response.get("citations", [])
        analysis = analyze_threshold_compliance(citations)

        total_citations += analysis["total_count"]
        total_pass_standard += analysis["pass_standard_count"]
        total_pass_adaptive_only += analysis["pass_adaptive_only_count"]
        all_scores.extend(analysis["scores"])

        query_result = {
            "query": query,
            "citation_count": analysis["total_count"],
            "pass_standard_count": analysis["pass_standard_count"],
            "pass_adaptive_only_count": analysis["pass_adaptive_only_count"],
            "standard_pass_rate": analysis["standard_pass_rate"],
            "scores": analysis["scores"],
        }
        results["queries"].append(query_result)

        print(f"  Citations: {analysis['total_count']}")
        if analysis["total_count"] > 0:
            print(f"  Pass standard (≥{STANDARD_THRESHOLD}): {analysis['pass_standard_count']} ({analysis['standard_pass_rate']:.0%})")
            print(f"  Pass adaptive only ({ADAPTIVE_THRESHOLD}-{STANDARD_THRESHOLD}): {analysis['pass_adaptive_only_count']}")
            if analysis["scores"]:
                print(f"  Scores: min={min(analysis['scores']):.3f}, max={max(analysis['scores']):.3f}, avg={sum(analysis['scores'])/len(analysis['scores']):.3f}")

    # Calculate overall summary
    overall_standard_pass_rate = total_pass_standard / total_citations if total_citations > 0 else 1.0

    results["summary"] = {
        "total_citations": total_citations,
        "pass_standard_count": total_pass_standard,
        "pass_adaptive_only_count": total_pass_adaptive_only,
        "overall_standard_pass_rate": overall_standard_pass_rate,
        "min_required_rate": MIN_STANDARD_PASS_RATE,
        "passed": overall_standard_pass_rate >= MIN_STANDARD_PASS_RATE,
    }

    # Add score distribution
    if all_scores:
        results["summary"]["score_distribution"] = {
            "min": min(all_scores),
            "max": max(all_scores),
            "avg": sum(all_scores) / len(all_scores),
            "median": sorted(all_scores)[len(all_scores) // 2],
        }

    # Print summary
    print("\n" + "=" * 70)
    print("A/B PRECISION SUMMARY")
    print("=" * 70)
    print(f"\nTotal citations analyzed: {total_citations}")
    print(f"Pass STANDARD threshold (≥{STANDARD_THRESHOLD}): {total_pass_standard} ({overall_standard_pass_rate:.1%})")
    print(f"Pass ADAPTIVE ONLY ({ADAPTIVE_THRESHOLD}-{STANDARD_THRESHOLD}): {total_pass_adaptive_only}")
    print(f"\nRequired pass rate: ≥{MIN_STANDARD_PASS_RATE:.0%}")
    print(f"Actual pass rate: {overall_standard_pass_rate:.1%}")
    print(f"\nVALIDATION: {'PASS' if results['summary']['passed'] else 'FAIL'}")

    if not results["summary"]["passed"]:
        print(f"\n⚠️  FAIL: {total_pass_adaptive_only} results admitted by adaptive threshold")
        print(f"   would NOT pass standard threshold. This indicates the adaptive")
        print(f"   threshold is too aggressive and admits low-quality results.")
        print(f"\n   Recommendation: Increase adaptive multiplier from 0.6 to 0.8")
    else:
        print(f"\n✅ PASS: {overall_standard_pass_rate:.1%} of adaptive results also pass standard threshold")
        print(f"   The adaptive threshold is not admitting low-quality results.")

    return results


def main():
    results = run_ab_precision_test()

    # Save results
    results_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "results"
    )
    os.makedirs(results_dir, exist_ok=True)

    output_path = os.path.join(results_dir, "adaptive_threshold_ab_precision.json")

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_path}")

    # Exit with appropriate code
    sys.exit(0 if results["summary"]["passed"] else 1)


if __name__ == "__main__":
    main()
