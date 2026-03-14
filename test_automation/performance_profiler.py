#!/usr/bin/env python3
"""
Performance Profiler for Task 26 - Component-Level Metrics

Captures detailed timing breakdowns for planner, traversal, retrieval, and generation.
Outputs results to results/performance_metrics.json with before/after comparison.

Usage:
    SALESFORCE_AI_SEARCH_API_URL=... SALESFORCE_AI_SEARCH_API_KEY=... python3 performance_profiler.py
"""

import json
import os
import statistics
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

# Configuration from environment
API_URL = os.getenv("SALESFORCE_AI_SEARCH_API_URL")
API_KEY = os.getenv("SALESFORCE_AI_SEARCH_API_KEY")
TEST_USER_ID = os.getenv("SALESFORCE_AI_SEARCH_TEST_USER_ID", "005dl00000Q6a3RAAR")

if not API_URL or not API_KEY:
    print("ERROR: SALESFORCE_AI_SEARCH_API_URL and SALESFORCE_AI_SEARCH_API_KEY must be set")
    sys.exit(1)

# Test queries categorized by complexity
TEST_QUERIES = {
    "simple": [
        {"query": "Show me available office space", "category": "simple"},
        {"query": "List all properties", "category": "simple"},
    ],
    "filtered": [
        {"query": "Show me Class A office in Plano", "category": "filtered"},
        {"query": "Find industrial properties in Miami", "category": "filtered"},
    ],
    "temporal": [
        {"query": "Show me leases expiring in 6 months", "category": "temporal"},
        {"query": "Find deals closed last quarter", "category": "temporal"},
    ],
    "complex": [
        {"query": "Find deals on properties in Texas with active leases", "category": "complex"},
        {"query": "Show availabilities in properties owned by Acme Corp", "category": "complex"},
    ],
}

# Number of iterations per query for statistical significance
ITERATIONS = 3


def parse_sse_response(response_text: str) -> Dict[str, Any]:
    """Parse SSE response to extract trace and answer data."""
    result = {
        "trace": {},
        "citations": 0,
        "answer_length": 0,
        "has_answer": False,
    }

    full_answer = ""
    for line in response_text.split('\n'):
        if not line.startswith('data: '):
            continue
        try:
            data = json.loads(line[6:])
            if 'trace' in data:
                result['trace'] = data['trace']
            if 'token' in data:
                full_answer += data['token']
            if 'citations' in data:
                result['citations'] = len(data.get('citations', []))
        except json.JSONDecodeError:
            pass

    result['answer_length'] = len(full_answer)
    result['has_answer'] = len(full_answer) > 50  # Non-trivial answer

    return result


def run_query(query: str) -> Dict[str, Any]:
    """Execute a single query and return timing metrics."""
    start = time.time()

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
            },
            timeout=120,
        )

        client_total_ms = (time.time() - start) * 1000

        if response.status_code != 200:
            return {
                "error": f"HTTP {response.status_code}",
                "client_total_ms": client_total_ms,
            }

        parsed = parse_sse_response(response.text)
        trace = parsed['trace']

        # Extract retrieve component metrics from nested structure
        retrieve_components = trace.get("retrieveComponents", {})

        return {
            "client_total_ms": client_total_ms,
            "server_total_ms": trace.get("totalMs", 0),
            "retrieve_ms": trace.get("retrieveMs", 0),
            "generate_ms": trace.get("generateMs", 0),
            "first_token_ms": trace.get("firstTokenMs", 0),
            # Component-level metrics (from retrieve Lambda via retrieveComponents)
            "intent_ms": retrieve_components.get("intentMs", 0),
            "schema_decomposition_ms": retrieve_components.get("schemaDecompositionMs", 0),
            "graph_filter_ms": retrieve_components.get("graphFilterMs", 0),
            "planner_ms": retrieve_components.get("plannerMs", 0),
            "cross_object_ms": retrieve_components.get("crossObjectMs", 0),
            "authz_ms": retrieve_components.get("authzMs", 0),
            "kb_query_ms": retrieve_components.get("kbQueryMs", 0),
            "graph_ms": retrieve_components.get("graphMs", 0),
            "supplemental_search_ms": retrieve_components.get("supplementalSearchMs", 0),
            "post_filter_ms": retrieve_components.get("postFilterMs", 0),
            "presigned_url_ms": retrieve_components.get("presignedUrlMs", 0),
            "ranking_ms": retrieve_components.get("rankingMs", 0),
            "fls_ms": retrieve_components.get("flsMs", 0),
            "retrieve_total_ms": retrieve_components.get("retrieveTotalMs", 0),  # Retrieve Lambda's total
            "cached": retrieve_components.get("cached", False),
            "planner_used": retrieve_components.get("plannerUsed", False),
            "planner_skipped": retrieve_components.get("plannerSkipped", False),
            "citations": parsed['citations'],
            "has_answer": parsed['has_answer'],
        }

    except requests.Timeout:
        return {"error": "timeout", "client_total_ms": 120000}
    except Exception as e:
        return {"error": str(e), "client_total_ms": 0}


def calculate_stats(values: List[float]) -> Dict[str, float]:
    """Calculate p50, p95, avg for a list of values."""
    if not values:
        return {"avg": 0, "p50": 0, "p95": 0, "min": 0, "max": 0}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    return {
        "avg": statistics.mean(sorted_vals),
        "p50": sorted_vals[int(n * 0.5)] if n > 1 else sorted_vals[0],
        "p95": sorted_vals[int(n * 0.95)] if n > 1 else sorted_vals[-1],
        "min": min(sorted_vals),
        "max": max(sorted_vals),
    }


def run_performance_test() -> Dict[str, Any]:
    """Run full performance test suite."""
    print("=" * 70)
    print("TASK 26 PERFORMANCE PROFILER")
    print("=" * 70)
    print(f"API URL: {API_URL}")
    print(f"Iterations per query: {ITERATIONS}")
    print(f"Total queries: {sum(len(q) for q in TEST_QUERIES.values()) * ITERATIONS}")
    print()

    all_results = []
    category_results = {cat: [] for cat in TEST_QUERIES.keys()}

    for category, queries in TEST_QUERIES.items():
        print(f"\n--- {category.upper()} QUERIES ---")

        for query_info in queries:
            query = query_info["query"]
            print(f"\nQuery: {query[:50]}...")

            for i in range(ITERATIONS):
                result = run_query(query)
                result["query"] = query
                result["category"] = category
                result["iteration"] = i + 1

                if "error" not in result:
                    all_results.append(result)
                    category_results[category].append(result)

                    print(f"  Run {i+1}: retrieve={result['retrieve_ms']:.0f}ms, "
                          f"generate={result['generate_ms']:.0f}ms, "
                          f"total={result['server_total_ms']:.0f}ms "
                          f"{'[cached]' if result['cached'] else ''}")
                else:
                    print(f"  Run {i+1}: ERROR - {result['error']}")

                # Small delay between iterations
                time.sleep(1)

    # Calculate aggregate statistics
    print("\n" + "=" * 70)
    print("AGGREGATE RESULTS")
    print("=" * 70)

    # Overall metrics
    retrieve_times = [r["retrieve_ms"] for r in all_results if not r.get("cached")]
    generate_times = [r["generate_ms"] for r in all_results]
    total_times = [r["server_total_ms"] for r in all_results]
    first_token_times = [r["first_token_ms"] for r in all_results]

    # Component metrics
    planner_times = [r["planner_ms"] for r in all_results if r["planner_ms"] > 0]
    intent_times = [r["intent_ms"] for r in all_results if r["intent_ms"] > 0]
    schema_times = [r["schema_decomposition_ms"] for r in all_results if r["schema_decomposition_ms"] > 0]

    overall_stats = {
        "retrieve": calculate_stats(retrieve_times),
        "generate": calculate_stats(generate_times),
        "total": calculate_stats(total_times),
        "first_token": calculate_stats(first_token_times),
        "planner": calculate_stats(planner_times),
        "intent": calculate_stats(intent_times),
        "schema_decomposition": calculate_stats(schema_times),
    }

    # Per-category stats
    category_stats = {}
    for category, results in category_results.items():
        if results:
            retrieve = [r["retrieve_ms"] for r in results if not r.get("cached")]
            category_stats[category] = {
                "retrieve": calculate_stats(retrieve),
                "total": calculate_stats([r["server_total_ms"] for r in results]),
                "count": len(results),
            }

    # Print summary
    print(f"\nOVERALL (n={len(all_results)}, non-cached retrieve n={len(retrieve_times)}):")
    print(f"  Retrieve p95: {overall_stats['retrieve']['p95']:.0f}ms (target: 1500ms)")
    print(f"  Retrieve avg: {overall_stats['retrieve']['avg']:.0f}ms")
    print(f"  Generate p95: {overall_stats['generate']['p95']:.0f}ms")
    print(f"  Total p95:    {overall_stats['total']['p95']:.0f}ms")
    print(f"  First Token p95: {overall_stats['first_token']['p95']:.0f}ms (target: 800ms)")

    print(f"\nCOMPONENT METRICS:")
    print(f"  Planner p95:  {overall_stats['planner']['p95']:.0f}ms (target: 500ms)")
    print(f"  Intent p95:   {overall_stats['intent']['p95']:.0f}ms")
    print(f"  Schema p95:   {overall_stats['schema_decomposition']['p95']:.0f}ms")

    print(f"\nBY CATEGORY:")
    for category, stats in category_stats.items():
        print(f"  {category}: retrieve p95={stats['retrieve']['p95']:.0f}ms, "
              f"total p95={stats['total']['p95']:.0f}ms (n={stats['count']})")

    # Check targets
    targets = {
        "retrieve_p95_ms": {"target": 1500, "actual": overall_stats['retrieve']['p95']},
        "first_token_p95_ms": {"target": 800, "actual": overall_stats['first_token']['p95']},
        "planner_p95_ms": {"target": 500, "actual": overall_stats['planner']['p95']},
    }

    print(f"\nTARGET COMPLIANCE:")
    all_met = True
    for metric, data in targets.items():
        met = data['actual'] <= data['target']
        all_met = all_met and met
        status = "PASS" if met else "FAIL"
        print(f"  {metric}: {data['actual']:.0f}ms vs {data['target']}ms [{status}]")

    # Build output
    output = {
        "timestamp": datetime.utcnow().isoformat(),
        "config": {
            "api_url": API_URL,
            "iterations": ITERATIONS,
            "total_queries": len(all_results),
        },
        "overall": overall_stats,
        "by_category": category_stats,
        "targets": targets,
        "all_targets_met": all_met,
        "raw_results": all_results,
    }

    return output


def main():
    results = run_performance_test()

    # Save to results directory
    results_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "results"
    )
    os.makedirs(results_dir, exist_ok=True)

    output_path = os.path.join(results_dir, "performance_metrics.json")

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_path}")

    # Exit with appropriate code
    sys.exit(0 if results["all_targets_met"] else 1)


if __name__ == "__main__":
    main()
