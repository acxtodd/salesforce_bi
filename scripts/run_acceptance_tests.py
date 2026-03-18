#!/usr/bin/env python3
"""Acceptance test runner for the AscendixIQ query pipeline (Task 1.3).

Loads CRE test cases from a YAML file, executes each question through
QueryHandler (real Bedrock + real Turbopuffer), evaluates answers against
acceptance criteria, and reports pass/fail with latency statistics.

Usage:
    # Run all tests
    python3 scripts/run_acceptance_tests.py

    # Run specific category
    python3 scripts/run_acceptance_tests.py --category simple_search

    # Run a single test
    python3 scripts/run_acceptance_tests.py --test search-01

    # Custom config / namespace
    python3 scripts/run_acceptance_tests.py --config denorm_config.yaml \\
        --namespace org_00Ddl000003yx57EAA

    # Output JSON results
    python3 scripts/run_acceptance_tests.py --output results/acceptance_test_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.query_handler import QueryHandler, QueryResult
from lib.tool_dispatch import build_field_registry
from lib.turbopuffer_backend import TurbopufferBackend

LOG = logging.getLogger("acceptance_tests")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AcceptanceTestCase:
    """A single acceptance test case loaded from YAML."""

    __test__ = False  # prevent pytest collection

    id: str
    question: str
    category: str
    expected: dict = field(default_factory=dict)


# Backwards-compatible aliases (kept short for internal use and imports).
TestCase = AcceptanceTestCase


@dataclass
class AcceptanceTestResult:
    """Result of evaluating one test case."""

    __test__ = False  # prevent pytest collection

    test_id: str
    question: str
    category: str
    status: str  # PASS, FAIL, SKIP, ERROR
    latency_s: float
    checks: list[dict] = field(default_factory=list)
    answer_snippet: str = ""
    tool_calls_made: int = 0
    turns: int = 0
    citations_count: int = 0
    error: str = ""
    tool_call_log: list[dict] = field(default_factory=list)
    turn_durations: list[float] = field(default_factory=list)
    tpuf_telemetry: list[dict] = field(default_factory=list)


TestCaseResult = AcceptanceTestResult


def _drain_backend_telemetry(backend: Any) -> list[dict]:
    """Return drained backend telemetry when supported by the backend."""
    drain = getattr(backend, "drain_telemetry", None)
    if callable(drain):
        drained = drain()
        if isinstance(drained, list):
            return drained
    return []


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

def load_test_cases(test_file: str) -> list[TestCase]:
    """Parse the YAML test file and return a list of TestCase objects."""
    path = Path(test_file)
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    with open(path) as f:
        data = yaml.safe_load(f)

    cases: list[TestCase] = []
    for entry in data.get("tests", []):
        cases.append(TestCase(
            id=entry["id"],
            question=entry["question"],
            category=entry.get("category", "uncategorized"),
            expected=entry.get("expected", {}),
        ))
    return cases


# ---------------------------------------------------------------------------
# Evaluation logic
# ---------------------------------------------------------------------------

_ERROR_PREFIXES = (
    "i'm sorry",
    "i cannot",
    "i can't",
    "i am unable",
    "sorry,",
    "unfortunately, i cannot",
    "unfortunately, i can't",
)


def evaluate_result(
    test_case: TestCase,
    query_result: QueryResult,
    latency_s: float,
) -> AcceptanceTestResult:
    """Evaluate a QueryResult against the test case's expected criteria.

    A test passes only if ALL its expected criteria are met.
    """
    expected = test_case.expected
    checks: list[dict] = []
    answer = query_result.answer
    answer_lower = answer.lower()

    # --- answer_contains_any ---
    if "answer_contains_any" in expected:
        terms = expected["answer_contains_any"]
        matched = [t for t in terms if t.lower() in answer_lower]
        ok = len(matched) > 0
        checks.append({
            "name": "answer_contains_any",
            "pass": ok,
            "detail": f"matched {matched}" if ok else f"none of {terms} found",
        })

    # --- answer_contains_number ---
    if expected.get("answer_contains_number"):
        has_number = bool(re.search(r"\d", answer))
        checks.append({
            "name": "answer_contains_number",
            "pass": has_number,
            "detail": "digit found" if has_number else "no digits in answer",
        })

    # --- min_results (actual search result count) ---
    if "min_results" in expected:
        min_r = expected["min_results"]
        actual = query_result.search_result_count
        ok = actual >= min_r
        checks.append({
            "name": "min_results",
            "pass": ok,
            "detail": f"search_result_count={actual} (need >={min_r})",
        })

    # --- tool_used (check actual tool names called) ---
    if "tool_used" in expected:
        expected_tool = expected["tool_used"]
        ok = expected_tool in query_result.tools_used
        checks.append({
            "name": "tool_used",
            "pass": ok,
            "detail": f"expected '{expected_tool}' in {query_result.tools_used}",
        })

    # --- no_error ---
    if expected.get("no_error"):
        has_error = any(answer_lower.startswith(prefix) for prefix in _ERROR_PREFIXES)
        ok = not has_error
        checks.append({
            "name": "no_error",
            "pass": ok,
            "detail": "no error prefix" if ok else "answer starts with error phrase",
        })

    # --- has_citations ---
    if expected.get("has_citations"):
        ok = len(query_result.citations) > 0
        checks.append({
            "name": "has_citations",
            "pass": ok,
            "detail": f"citations={len(query_result.citations)}",
        })

    # --- latency_under ---
    if "latency_under" in expected:
        max_s = expected["latency_under"]
        ok = latency_s <= max_s
        checks.append({
            "name": "latency_under",
            "pass": ok,
            "detail": f"{latency_s:.1f}s (limit {max_s}s)",
        })

    all_pass = all(c["pass"] for c in checks)

    return AcceptanceTestResult(
        test_id=test_case.id,
        question=test_case.question,
        category=test_case.category,
        status="PASS" if all_pass else "FAIL",
        latency_s=latency_s,
        checks=checks,
        answer_snippet=answer[:200],
        tool_calls_made=query_result.tool_calls_made,
        turns=query_result.turns,
        citations_count=len(query_result.citations),
        tool_call_log=query_result.tool_call_log,
        turn_durations=query_result.turn_durations,
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_acceptance_tests(
    config_path: str = "denorm_config.yaml",
    test_file: str = "scripts/acceptance_tests.yaml",
    namespace: str | None = None,
    org_id: str = "00Ddl000003yx57EAA",
    model_id: str = "us.anthropic.claude-sonnet-4-20250514-v1:0",
    category: str | None = None,
    test_id: str | None = None,
) -> dict:
    """Run all acceptance tests and return results summary.

    Parameters
    ----------
    config_path:
        Path to the denorm_config.yaml file.
    test_file:
        Path to the acceptance_tests.yaml file.
    namespace:
        Turbopuffer namespace.  Auto-derived from *org_id* if None.
    org_id:
        Salesforce org ID used to build the namespace.
    model_id:
        Bedrock model identifier for Claude.
    category:
        If set, only run tests matching this category.
    test_id:
        If set, only run the test with this ID.

    Returns
    -------
    dict with keys: pass_rate, total, passed, failed, skipped, results,
    latency_stats, failures.
    """
    import boto3

    # --- Load config ---
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = PROJECT_ROOT / cfg_path
    with open(cfg_path) as f:
        config = yaml.safe_load(f)

    field_registry = build_field_registry(config)

    # --- Namespace ---
    if namespace is None:
        namespace = f"org_{org_id}"

    # --- Backend + Bedrock client ---
    backend = TurbopufferBackend()
    bedrock_client = boto3.client("bedrock-runtime")

    # --- Query handler ---
    handler = QueryHandler(
        bedrock_client=bedrock_client,
        backend=backend,
        namespace=namespace,
        field_registry=field_registry,
        model_id=model_id,
    )

    # --- Load and filter test cases ---
    cases = load_test_cases(test_file)
    if test_id:
        cases = [c for c in cases if c.id == test_id]
    if category:
        cases = [c for c in cases if c.category == category]

    if not cases:
        LOG.warning("No test cases matched filters (test_id=%s, category=%s)", test_id, category)
        return {
            "pass_rate": 0.0,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
            "latency_stats": {},
            "failures": [],
        }

    # --- Run each test ---
    results: list[AcceptanceTestResult] = []
    for case in cases:
        LOG.info("Running test %s: %s", case.id, case.question)
        tpuf_telemetry: list[dict] = []
        try:
            start = time.perf_counter()
            query_result = handler.query(case.question)
            latency_s = time.perf_counter() - start

            result = evaluate_result(case, query_result, latency_s)
            tpuf_telemetry = _drain_backend_telemetry(backend)
            result.tpuf_telemetry = tpuf_telemetry
        except Exception as exc:
            latency_s = time.perf_counter() - start if "start" in dir() else 0.0
            tpuf_telemetry = _drain_backend_telemetry(backend)
            result = AcceptanceTestResult(
                test_id=case.id,
                question=case.question,
                category=case.category,
                status="ERROR",
                latency_s=latency_s,
                error=str(exc),
                tpuf_telemetry=tpuf_telemetry,
            )
        results.append(result)

    # --- Compute summary ---
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status in ("FAIL", "ERROR"))
    skipped = sum(1 for r in results if r.status == "SKIP")
    total = len(results)
    pass_rate = passed / total if total > 0 else 0.0

    latencies = [r.latency_s for r in results if r.latency_s > 0]
    latency_stats: dict[str, float] = {}
    if latencies:
        latency_stats = {
            "min": round(min(latencies), 2),
            "max": round(max(latencies), 2),
            "mean": round(statistics.mean(latencies), 2),
            "median": round(statistics.median(latencies), 2),
        }
        if len(latencies) >= 2:
            sorted_lat = sorted(latencies)
            p95_idx = int(len(sorted_lat) * 0.95)
            p95_idx = min(p95_idx, len(sorted_lat) - 1)
            latency_stats["p95"] = round(sorted_lat[p95_idx], 2)

    failures: list[dict] = []
    for r in results:
        if r.status in ("FAIL", "ERROR"):
            failed_checks = [c for c in r.checks if not c["pass"]]
            failures.append({
                "test_id": r.test_id,
                "question": r.question,
                "status": r.status,
                "error": r.error,
                "failed_checks": failed_checks,
                "answer_snippet": r.answer_snippet,
            })

    # --- Per-category latency breakdown ---
    category_latency: dict[str, dict[str, float]] = {}
    cats: dict[str, list[float]] = {}
    for r in results:
        if r.latency_s > 0:
            cats.setdefault(r.category, []).append(r.latency_s)
    for cat, lats in sorted(cats.items()):
        entry: dict[str, float] = {
            "count": len(lats),
            "min": round(min(lats), 2),
            "max": round(max(lats), 2),
            "mean": round(statistics.mean(lats), 2),
            "median": round(statistics.median(lats), 2),
        }
        if len(lats) >= 2:
            s = sorted(lats)
            idx = min(int(len(s) * 0.95), len(s) - 1)
            entry["p95"] = round(s[idx], 2)
        category_latency[cat] = entry

    summary = {
        "pass_rate": round(pass_rate, 4),
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "results": [asdict(r) for r in results],
        "latency_stats": latency_stats,
        "category_latency": category_latency,
        "failures": failures,
        "tpuf_telemetry_event_count": sum(len(r.tpuf_telemetry) for r in results),
    }

    return summary


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_report(summary: dict) -> str:
    """Format the summary dict as a human-readable console report."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("  AscendixIQ Acceptance Test Report")
    lines.append("=" * 72)
    lines.append("")

    for r in summary.get("results", []):
        status = r["status"]
        status_tag = f"[{status}]"
        latency = f"{r['latency_s']:.1f}s"
        lines.append(
            f"  {status_tag:<7} {r['test_id']:<12} ({latency:>5}) {r['question'][:55]}"
        )
        # Show failed checks
        for c in r.get("checks", []):
            if not c["pass"]:
                lines.append(f"           FAIL: {c['name']} - {c['detail']}")
        if r.get("error"):
            lines.append(f"           ERROR: {r['error'][:80]}")

    lines.append("")
    lines.append("-" * 72)

    total = summary["total"]
    passed = summary["passed"]
    failed = summary["failed"]
    skipped = summary["skipped"]
    rate = summary["pass_rate"]

    lines.append(f"  Total: {total}  |  Passed: {passed}  |  Failed: {failed}  |  Skipped: {skipped}")
    lines.append(f"  Pass rate: {rate:.0%}  (interim target: >=70%)")

    lat = summary.get("latency_stats", {})
    if lat:
        parts = [f"{k}={v}s" for k, v in lat.items()]
        lines.append(f"  Latency (overall): {', '.join(parts)}")

    cat_lat = summary.get("category_latency", {})
    if cat_lat:
        lines.append("")
        lines.append("  Latency by category:")
        for cat, stats in cat_lat.items():
            parts = [f"{k}={v}" for k, v in stats.items()]
            lines.append(f"    {cat:<16} {', '.join(parts)}")

    lines.append("")

    if summary.get("failures"):
        lines.append("  Failure Analysis:")
        for f in summary["failures"]:
            lines.append(f"    {f['test_id']}: {f['status']}")
            for fc in f.get("failed_checks", []):
                lines.append(f"      - {fc['name']}: {fc['detail']}")
            if f.get("error"):
                lines.append(f"      - error: {f['error'][:100]}")
            if f.get("answer_snippet"):
                lines.append(f"      - answer: {f['answer_snippet'][:100]}...")
        lines.append("")

    lines.append("=" * 72)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Run acceptance tests for the AscendixIQ query pipeline.",
    )
    parser.add_argument(
        "--config", default="denorm_config.yaml",
        help="Path to denorm_config.yaml (default: denorm_config.yaml)",
    )
    parser.add_argument(
        "--test-file", default="scripts/acceptance_tests.yaml",
        help="Path to test case YAML file (default: scripts/acceptance_tests.yaml)",
    )
    parser.add_argument(
        "--namespace", default=None,
        help="Turbopuffer namespace (default: derived from --org-id)",
    )
    parser.add_argument(
        "--org-id", default="00Ddl000003yx57EAA",
        help="Salesforce org ID (default: 00Ddl000003yx57EAA)",
    )
    parser.add_argument(
        "--model-id", default="us.anthropic.claude-sonnet-4-20250514-v1:0",
        help="Bedrock model ID",
    )
    parser.add_argument(
        "--category", default=None,
        help="Run only tests in this category",
    )
    parser.add_argument(
        "--test", default=None, dest="test_id",
        help="Run only the test with this ID",
    )
    parser.add_argument(
        "--output", default=None,
        help="Write JSON results to this file",
    )

    args = parser.parse_args()

    summary = run_acceptance_tests(
        config_path=args.config,
        test_file=args.test_file,
        namespace=args.namespace,
        org_id=args.org_id,
        model_id=args.model_id,
        category=args.category,
        test_id=args.test_id,
    )

    report = format_report(summary)
    print(report)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"Results written to: {args.output}")

    sys.exit(0 if summary["pass_rate"] >= 0.70 else 1)


if __name__ == "__main__":
    main()
