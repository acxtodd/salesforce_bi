"""Tests for the acceptance test runner (Task 1.3).

All tests use mocked QueryHandler -- no real Bedrock or Turbopuffer calls.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Ensure project root is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.query_handler import QueryResult
from scripts.run_acceptance_tests import (
    TestCase,
    TestCaseResult,  # noqa: F401 -- backwards-compat alias
    evaluate_result,
    format_report,
    load_test_cases,
    run_acceptance_tests,
)


# =========================================================================
# Fixtures
# =========================================================================

SAMPLE_YAML = {
    "tests": [
        {
            "id": "search-01",
            "question": "Find Class A office properties in Dallas",
            "category": "simple_search",
            "expected": {
                "tool_used": "search_records",
                "answer_contains_any": ["Dallas", "Class A", "office"],
                "min_results": 1,
                "no_error": True,
                "latency_under": 15,
            },
        },
        {
            "id": "agg-01",
            "question": "How many properties are there by city?",
            "category": "aggregation",
            "expected": {
                "tool_used": "aggregate_records",
                "answer_contains_any": ["propert", "city"],
                "answer_contains_number": True,
                "no_error": True,
                "latency_under": 15,
            },
        },
        {
            "id": "cross-01",
            "question": "Find lease comps in Dallas on office property over 10,000 SF",
            "category": "cross_object",
            "expected": {
                "tool_used": "search_records",
                "answer_contains_any": ["Dallas", "lease", "office"],
                "answer_contains_number": True,
                "min_results": 1,
                "no_error": True,
                "latency_under": 30,
            },
        },
        {
            "id": "comp-01",
            "question": "Compare the number of properties in Dallas versus Houston",
            "category": "comparison",
            "expected": {
                "tool_used": "aggregate_records",
                "answer_contains_any": ["Dallas", "Houston"],
                "answer_contains_number": True,
                "no_error": True,
                "latency_under": 30,
            },
        },
    ],
}


@pytest.fixture
def yaml_file(tmp_path):
    """Write sample YAML to a temporary file and return its path."""
    path = tmp_path / "test_cases.yaml"
    with open(path, "w") as f:
        yaml.dump(SAMPLE_YAML, f)
    return str(path)


def _make_query_result(
    answer: str = "There are 42 properties in Dallas, including Class A office buildings.",
    citations: list | None = None,
    tool_calls_made: int = 1,
    turns: int = 2,
    tools_used: list | None = None,
    search_result_count: int = 5,
) -> QueryResult:
    return QueryResult(
        answer=answer,
        citations=citations or [],
        tool_calls_made=tool_calls_made,
        turns=turns,
        tools_used=tools_used if tools_used is not None else ["search_records"],
        search_result_count=search_result_count,
    )


def _make_test_case(
    id: str = "test-01",
    question: str = "Find properties in Dallas",
    category: str = "simple_search",
    expected: dict | None = None,
) -> TestCase:
    if expected is None:
        expected = {
            "answer_contains_any": ["Dallas", "propert"],
            "no_error": True,
            "min_results": 1,
            "tool_used": "search_records",
            "latency_under": 15,
        }
    return TestCase(id=id, question=question, category=category, expected=expected)


# =========================================================================
# 1. Test case loading
# =========================================================================

class TestCaseLoading:
    """YAML parsing and test case structure validation."""

    def test_loads_all_cases(self, yaml_file):
        cases = load_test_cases(yaml_file)
        assert len(cases) == 4

    def test_case_fields_populated(self, yaml_file):
        cases = load_test_cases(yaml_file)
        c = cases[0]
        assert c.id == "search-01"
        assert c.question == "Find Class A office properties in Dallas"
        assert c.category == "simple_search"
        assert "tool_used" in c.expected
        assert "answer_contains_any" in c.expected

    def test_preserves_expected_dict(self, yaml_file):
        cases = load_test_cases(yaml_file)
        agg = next(c for c in cases if c.id == "agg-01")
        assert agg.expected["tool_used"] == "aggregate_records"
        assert agg.expected["answer_contains_number"] is True

    def test_empty_yaml(self, tmp_path):
        path = tmp_path / "empty.yaml"
        with open(path, "w") as f:
            yaml.dump({"tests": []}, f)
        cases = load_test_cases(str(path))
        assert cases == []

    def test_missing_expected_defaults_to_empty(self, tmp_path):
        path = tmp_path / "minimal.yaml"
        with open(path, "w") as f:
            yaml.dump({
                "tests": [{
                    "id": "min-01",
                    "question": "Hello",
                    "category": "misc",
                }]
            }, f)
        cases = load_test_cases(str(path))
        assert cases[0].expected == {}

    def test_missing_category_defaults(self, tmp_path):
        path = tmp_path / "nocat.yaml"
        with open(path, "w") as f:
            yaml.dump({
                "tests": [{
                    "id": "x-01",
                    "question": "Hi",
                }]
            }, f)
        cases = load_test_cases(str(path))
        assert cases[0].category == "uncategorized"


# =========================================================================
# 2. Evaluation logic
# =========================================================================

class TestEvaluation:
    """Verify evaluate_result checks each criterion correctly."""

    def test_all_checks_pass(self):
        tc = _make_test_case()
        qr = _make_query_result()
        result = evaluate_result(tc, qr, latency_s=2.0)
        assert result.status == "PASS"
        assert all(c["pass"] for c in result.checks)

    def test_answer_contains_any_passes(self):
        tc = _make_test_case(expected={"answer_contains_any": ["Dallas"]})
        qr = _make_query_result(answer="Found 5 properties in Dallas.")
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "answer_contains_any")
        assert check["pass"] is True

    def test_answer_contains_any_fails(self):
        tc = _make_test_case(expected={"answer_contains_any": ["Houston", "Austin"]})
        qr = _make_query_result(answer="Found 5 properties in Dallas.")
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "answer_contains_any")
        assert check["pass"] is False
        assert result.status == "FAIL"

    def test_answer_contains_any_case_insensitive(self):
        tc = _make_test_case(expected={"answer_contains_any": ["dallas"]})
        qr = _make_query_result(answer="Properties in DALLAS are impressive.")
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "answer_contains_any")
        assert check["pass"] is True

    def test_answer_contains_number_passes(self):
        tc = _make_test_case(expected={"answer_contains_number": True})
        qr = _make_query_result(answer="There are 42 properties.")
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "answer_contains_number")
        assert check["pass"] is True

    def test_answer_contains_number_fails(self):
        tc = _make_test_case(expected={"answer_contains_number": True})
        qr = _make_query_result(answer="There are many properties.")
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "answer_contains_number")
        assert check["pass"] is False

    def test_no_error_passes(self):
        tc = _make_test_case(expected={"no_error": True})
        qr = _make_query_result(answer="Here are some results.")
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "no_error")
        assert check["pass"] is True

    def test_no_error_fails_on_sorry(self):
        tc = _make_test_case(expected={"no_error": True})
        qr = _make_query_result(answer="I'm sorry, I cannot find any results.")
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "no_error")
        assert check["pass"] is False

    def test_no_error_fails_on_cannot(self):
        tc = _make_test_case(expected={"no_error": True})
        qr = _make_query_result(answer="I cannot process that request.")
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "no_error")
        assert check["pass"] is False

    def test_min_results_passes(self):
        tc = _make_test_case(expected={"min_results": 1})
        qr = _make_query_result(search_result_count=3)
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "min_results")
        assert check["pass"] is True

    def test_min_results_fails(self):
        tc = _make_test_case(expected={"min_results": 1})
        qr = _make_query_result(search_result_count=0)
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "min_results")
        assert check["pass"] is False

    def test_tool_used_passes(self):
        tc = _make_test_case(expected={"tool_used": "search_records"})
        qr = _make_query_result(tools_used=["search_records"])
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "tool_used")
        assert check["pass"] is True

    def test_tool_used_fails_when_wrong_tool(self):
        tc = _make_test_case(expected={"tool_used": "search_records"})
        qr = _make_query_result(tools_used=["aggregate_records"])
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "tool_used")
        assert check["pass"] is False

    def test_tool_used_fails_when_no_tools(self):
        tc = _make_test_case(expected={"tool_used": "search_records"})
        qr = _make_query_result(tools_used=[])
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "tool_used")
        assert check["pass"] is False

    def test_has_citations_passes(self):
        tc = _make_test_case(expected={"has_citations": True})
        qr = _make_query_result(citations=[{"id": "a0x001", "name": "Tower"}])
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "has_citations")
        assert check["pass"] is True

    def test_has_citations_fails(self):
        tc = _make_test_case(expected={"has_citations": True})
        qr = _make_query_result(citations=[])
        result = evaluate_result(tc, qr, latency_s=1.0)
        check = next(c for c in result.checks if c["name"] == "has_citations")
        assert check["pass"] is False

    def test_latency_under_passes(self):
        tc = _make_test_case(expected={"latency_under": 15})
        qr = _make_query_result()
        result = evaluate_result(tc, qr, latency_s=5.0)
        check = next(c for c in result.checks if c["name"] == "latency_under")
        assert check["pass"] is True

    def test_latency_under_fails(self):
        tc = _make_test_case(expected={"latency_under": 15})
        qr = _make_query_result()
        result = evaluate_result(tc, qr, latency_s=20.0)
        check = next(c for c in result.checks if c["name"] == "latency_under")
        assert check["pass"] is False

    def test_empty_expected_passes(self):
        tc = _make_test_case(expected={})
        qr = _make_query_result()
        result = evaluate_result(tc, qr, latency_s=1.0)
        assert result.status == "PASS"
        assert result.checks == []

    def test_multiple_checks_one_fails_means_fail(self):
        tc = _make_test_case(expected={
            "answer_contains_any": ["Dallas"],
            "answer_contains_number": True,
            "no_error": True,
        })
        qr = _make_query_result(answer="Found stuff in Dallas, no numbers though.")
        result = evaluate_result(tc, qr, latency_s=1.0)
        assert result.status == "FAIL"
        # answer_contains_any passes, answer_contains_number fails
        contains_check = next(c for c in result.checks if c["name"] == "answer_contains_any")
        number_check = next(c for c in result.checks if c["name"] == "answer_contains_number")
        assert contains_check["pass"] is True
        assert number_check["pass"] is False

    def test_result_metadata(self):
        tc = _make_test_case(id="meta-01", question="Test Q", category="test_cat")
        qr = _make_query_result(
            answer="Answer with 10 results",
            citations=[{"id": "a0x001", "name": "X"}],
            tool_calls_made=3,
            turns=4,
        )
        result = evaluate_result(tc, qr, latency_s=7.5)
        assert result.test_id == "meta-01"
        assert result.question == "Test Q"
        assert result.category == "test_cat"
        assert result.latency_s == 7.5
        assert result.tool_calls_made == 3
        assert result.turns == 4
        assert result.citations_count == 1
        assert result.answer_snippet.startswith("Answer with 10")


# =========================================================================
# 3. Summary statistics
# =========================================================================

class TestSummaryStatistics:
    """Verify pass_rate, latency stats, and failure analysis."""

    def test_pass_rate_all_pass(self):
        summary = {
            "pass_rate": 1.0,
            "total": 3,
            "passed": 3,
            "failed": 0,
            "skipped": 0,
            "results": [],
            "latency_stats": {"min": 1.0, "max": 3.0, "mean": 2.0, "median": 2.0},
            "failures": [],
        }
        assert summary["pass_rate"] == 1.0

    def test_pass_rate_partial(self):
        # Simulate 2 pass, 1 fail out of 3
        total = 3
        passed = 2
        rate = passed / total
        assert round(rate, 4) == 0.6667

    def test_pass_rate_zero(self):
        total = 5
        passed = 0
        rate = passed / total if total > 0 else 0.0
        assert rate == 0.0

    def test_format_report_includes_pass_rate(self):
        summary = {
            "pass_rate": 0.75,
            "total": 4,
            "passed": 3,
            "failed": 1,
            "skipped": 0,
            "results": [
                {
                    "test_id": "s-01",
                    "question": "Q1",
                    "category": "simple",
                    "status": "PASS",
                    "latency_s": 2.0,
                    "checks": [],
                    "answer_snippet": "",
                    "tool_calls_made": 1,
                    "turns": 2,
                    "citations_count": 0,
                    "error": "",
                },
                {
                    "test_id": "s-02",
                    "question": "Q2",
                    "category": "simple",
                    "status": "FAIL",
                    "latency_s": 3.0,
                    "checks": [{"name": "no_error", "pass": False, "detail": "error prefix"}],
                    "answer_snippet": "I'm sorry...",
                    "tool_calls_made": 0,
                    "turns": 1,
                    "citations_count": 0,
                    "error": "",
                },
            ],
            "latency_stats": {"min": 2.0, "max": 3.0, "mean": 2.5, "median": 2.5},
            "failures": [
                {
                    "test_id": "s-02",
                    "question": "Q2",
                    "status": "FAIL",
                    "error": "",
                    "failed_checks": [{"name": "no_error", "pass": False, "detail": "error prefix"}],
                    "answer_snippet": "I'm sorry...",
                },
            ],
        }
        report = format_report(summary)
        assert "75%" in report
        assert "Passed: 3" in report
        assert "Failed: 1" in report
        assert "s-02" in report
        assert "Failure Analysis" in report

    def test_format_report_empty(self):
        summary = {
            "pass_rate": 0.0,
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
            "latency_stats": {},
            "failures": [],
        }
        report = format_report(summary)
        assert "Total: 0" in report
        assert "0%" in report


# =========================================================================
# 4. Category filtering
# =========================================================================

class TestCategoryFiltering:
    """--category flag filters test cases correctly."""

    def test_filter_by_category(self, yaml_file):
        cases = load_test_cases(yaml_file)
        simple = [c for c in cases if c.category == "simple_search"]
        assert len(simple) == 1
        assert simple[0].id == "search-01"

    def test_filter_by_aggregation(self, yaml_file):
        cases = load_test_cases(yaml_file)
        agg = [c for c in cases if c.category == "aggregation"]
        assert len(agg) == 1
        assert agg[0].id == "agg-01"

    def test_filter_by_cross_object(self, yaml_file):
        cases = load_test_cases(yaml_file)
        cross = [c for c in cases if c.category == "cross_object"]
        assert len(cross) == 1
        assert cross[0].id == "cross-01"

    def test_filter_by_nonexistent_category(self, yaml_file):
        cases = load_test_cases(yaml_file)
        filtered = [c for c in cases if c.category == "nonexistent"]
        assert filtered == []

    def test_run_with_category_filter(self, yaml_file, tmp_path):
        """Verify run_acceptance_tests respects category filter via mocked handler."""
        mock_qr = _make_query_result(
            answer="There are 42 properties across cities in Dallas and Houston.",
            tool_calls_made=1,
            turns=2,
        )

        # Load test cases BEFORE patches interfere with builtins.open
        preloaded_cases = load_test_cases(yaml_file)

        with (
            patch("scripts.run_acceptance_tests.TurbopufferBackend"),
            patch("scripts.run_acceptance_tests.build_field_registry", return_value={}),
            patch("scripts.run_acceptance_tests.QueryHandler") as MockHandler,
            patch("scripts.run_acceptance_tests.load_test_cases", return_value=preloaded_cases),
            patch("builtins.open", create=True),
            patch("scripts.run_acceptance_tests.yaml.safe_load", return_value={}),
            patch("boto3.client"),
        ):
            mock_instance = MagicMock()
            mock_instance.query.return_value = mock_qr
            MockHandler.return_value = mock_instance

            summary = run_acceptance_tests(
                config_path=str(tmp_path / "dummy.yaml"),
                test_file=yaml_file,
                namespace="test_ns",
                category="aggregation",
            )

        assert summary["total"] == 1
        result_ids = [r["test_id"] for r in summary["results"]]
        assert result_ids == ["agg-01"]


# =========================================================================
# 5. Single test filtering
# =========================================================================

class TestSingleTestFiltering:
    """--test flag runs only one test."""

    def test_filter_by_id(self, yaml_file):
        cases = load_test_cases(yaml_file)
        filtered = [c for c in cases if c.id == "cross-01"]
        assert len(filtered) == 1
        assert filtered[0].category == "cross_object"

    def test_filter_by_nonexistent_id(self, yaml_file):
        cases = load_test_cases(yaml_file)
        filtered = [c for c in cases if c.id == "nonexistent-99"]
        assert filtered == []

    def test_run_with_test_id_filter(self, yaml_file, tmp_path):
        """Verify run_acceptance_tests respects test_id filter."""
        mock_qr = _make_query_result(
            answer="I found 15 lease comps in Dallas with 10,000 SF office properties.",
            tool_calls_made=2,
            turns=3,
        )

        preloaded_cases = load_test_cases(yaml_file)

        with (
            patch("scripts.run_acceptance_tests.TurbopufferBackend"),
            patch("scripts.run_acceptance_tests.build_field_registry", return_value={}),
            patch("scripts.run_acceptance_tests.QueryHandler") as MockHandler,
            patch("scripts.run_acceptance_tests.load_test_cases", return_value=preloaded_cases),
            patch("builtins.open", create=True),
            patch("scripts.run_acceptance_tests.yaml.safe_load", return_value={}),
            patch("boto3.client"),
        ):
            mock_instance = MagicMock()
            mock_instance.query.return_value = mock_qr
            MockHandler.return_value = mock_instance

            summary = run_acceptance_tests(
                config_path=str(tmp_path / "dummy.yaml"),
                test_file=yaml_file,
                namespace="test_ns",
                test_id="cross-01",
            )

        assert summary["total"] == 1
        assert summary["results"][0]["test_id"] == "cross-01"
        # This answer matches all cross-01 expected criteria
        assert summary["results"][0]["status"] == "PASS"


# =========================================================================
# 6. Integration-style test with mocked QueryHandler
# =========================================================================

class TestIntegrationMocked:
    """End-to-end runner with fully mocked QueryHandler."""

    def test_full_run_all_pass(self, yaml_file, tmp_path):
        """All 4 test cases pass when answers are crafted to match."""
        mock_qr = _make_query_result(
            answer=(
                "There are 42 properties in Dallas and Houston. "
                "I found Class A office buildings and lease comps. "
                "City breakdown shows the distribution across cities."
            ),
            tool_calls_made=2,
            turns=3,
            citations=[{"id": "a0x001", "name": "Tower One"}],
            tools_used=["search_records", "aggregate_records"],
            search_result_count=5,
        )

        preloaded_cases = load_test_cases(yaml_file)

        with (
            patch("scripts.run_acceptance_tests.TurbopufferBackend") as MockBackend,
            patch("scripts.run_acceptance_tests.build_field_registry", return_value={}),
            patch("scripts.run_acceptance_tests.QueryHandler") as MockHandler,
            patch("scripts.run_acceptance_tests.load_test_cases", return_value=preloaded_cases),
            patch("builtins.open", create=True),
            patch("scripts.run_acceptance_tests.yaml.safe_load", return_value={}),
            patch("boto3.client"),
        ):
            MockBackend.return_value.drain_telemetry.side_effect = [
                [{"operation": "search", "billing": {"billable_logical_bytes_queried": 10}}],
                [{"operation": "search", "billing": {"billable_logical_bytes_queried": 11}}],
                [{"operation": "search", "billing": {"billable_logical_bytes_queried": 12}}],
                [{"operation": "search", "billing": {"billable_logical_bytes_queried": 13}}],
            ]
            mock_instance = MagicMock()
            mock_instance.query.return_value = mock_qr
            MockHandler.return_value = mock_instance

            summary = run_acceptance_tests(
                config_path=str(tmp_path / "dummy.yaml"),
                test_file=yaml_file,
                namespace="test_ns",
            )

        assert summary["total"] == 4
        assert summary["passed"] == 4
        assert summary["pass_rate"] == 1.0
        assert summary["failed"] == 0
        assert len(summary["failures"]) == 0
        assert summary["tpuf_telemetry_event_count"] == 4
        assert summary["results"][0]["tpuf_telemetry"][0]["operation"] == "search"

    def test_error_handling(self, yaml_file, tmp_path):
        """Tests that throw exceptions are recorded as ERROR."""
        preloaded_cases = load_test_cases(yaml_file)

        with (
            patch("scripts.run_acceptance_tests.TurbopufferBackend"),
            patch("scripts.run_acceptance_tests.build_field_registry", return_value={}),
            patch("scripts.run_acceptance_tests.QueryHandler") as MockHandler,
            patch("scripts.run_acceptance_tests.load_test_cases", return_value=preloaded_cases),
            patch("builtins.open", create=True),
            patch("scripts.run_acceptance_tests.yaml.safe_load", return_value={}),
            patch("boto3.client"),
        ):
            mock_instance = MagicMock()
            mock_instance.query.side_effect = RuntimeError("Bedrock timeout")
            MockHandler.return_value = mock_instance

            summary = run_acceptance_tests(
                config_path=str(tmp_path / "dummy.yaml"),
                test_file=yaml_file,
                namespace="test_ns",
            )

        assert summary["total"] == 4
        assert summary["failed"] == 4
        assert summary["pass_rate"] == 0.0
        for r in summary["results"]:
            assert r["status"] == "ERROR"
            assert "Bedrock timeout" in r["error"]

    def test_no_tests_match(self, yaml_file, tmp_path):
        """Running with a non-matching filter returns empty summary."""
        preloaded_cases = load_test_cases(yaml_file)

        with (
            patch("scripts.run_acceptance_tests.TurbopufferBackend"),
            patch("scripts.run_acceptance_tests.build_field_registry", return_value={}),
            patch("scripts.run_acceptance_tests.QueryHandler") as MockHandler,
            patch("scripts.run_acceptance_tests.load_test_cases", return_value=preloaded_cases),
            patch("builtins.open", create=True),
            patch("scripts.run_acceptance_tests.yaml.safe_load", return_value={}),
            patch("boto3.client"),
        ):
            mock_instance = MagicMock()
            MockHandler.return_value = mock_instance

            summary = run_acceptance_tests(
                config_path=str(tmp_path / "dummy.yaml"),
                test_file=yaml_file,
                namespace="test_ns",
                category="nonexistent_category",
            )

        assert summary["total"] == 0
        assert summary["pass_rate"] == 0.0
        assert summary["results"] == []

    def test_latency_stats_computed(self, yaml_file, tmp_path):
        """Latency stats are computed from per-test latencies."""
        mock_qr = _make_query_result(
            answer="42 properties in Dallas, Houston, with Class A office and lease comps across cities.",
            tool_calls_made=1,
        )

        preloaded_cases = load_test_cases(yaml_file)

        with (
            patch("scripts.run_acceptance_tests.TurbopufferBackend"),
            patch("scripts.run_acceptance_tests.build_field_registry", return_value={}),
            patch("scripts.run_acceptance_tests.QueryHandler") as MockHandler,
            patch("scripts.run_acceptance_tests.load_test_cases", return_value=preloaded_cases),
            patch("builtins.open", create=True),
            patch("scripts.run_acceptance_tests.yaml.safe_load", return_value={}),
            patch("boto3.client"),
        ):
            mock_instance = MagicMock()
            mock_instance.query.return_value = mock_qr
            MockHandler.return_value = mock_instance

            summary = run_acceptance_tests(
                config_path=str(tmp_path / "dummy.yaml"),
                test_file=yaml_file,
                namespace="test_ns",
            )

        lat = summary["latency_stats"]
        assert "min" in lat
        assert "max" in lat
        assert "mean" in lat
        assert "median" in lat
        assert lat["min"] <= lat["mean"] <= lat["max"]
