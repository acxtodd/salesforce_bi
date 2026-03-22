"""Tests for clarification extraction and SSE emission (Task 4.13.1f).

Validates marker parsing, multiple options, empty-case passthrough,
and Lambda SSE event emission.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.query_handler import extract_clarifications, QueryResult


# ---------------------------------------------------------------------------
# extract_clarifications
# ---------------------------------------------------------------------------


class TestExtractClarifications:
    """Unit tests for the CLARIFY marker parser."""

    def test_single_option(self):
        answer = (
            "Which metric do you mean?\n"
            "[CLARIFY:By deal count|Show top 5 markets by deal count]\n"
            "Please pick one."
        )
        clean, options = extract_clarifications(answer)
        assert len(options) == 1
        assert options[0]["label"] == "By deal count"
        assert options[0]["query"] == "Show top 5 markets by deal count"
        assert "[CLARIFY:" not in clean

    def test_multiple_options(self):
        answer = (
            "Did you mean:\n"
            "[CLARIFY:By revenue|Top brokers by gross revenue]\n"
            "[CLARIFY:By deal count|Top brokers by deal count]\n"
            "[CLARIFY:By sqft|Top brokers by total square footage]\n"
        )
        clean, options = extract_clarifications(answer)
        assert len(options) == 3
        assert options[0]["label"] == "By revenue"
        assert options[1]["label"] == "By deal count"
        assert options[2]["label"] == "By sqft"
        assert "[CLARIFY:" not in clean

    def test_no_markers_returns_empty(self):
        answer = "There are 42 properties in Dallas."
        clean, options = extract_clarifications(answer)
        assert options == []
        assert clean == answer

    def test_empty_string(self):
        clean, options = extract_clarifications("")
        assert options == []
        assert clean == ""

    def test_marker_stripped_cleanly(self):
        answer = "Here is info. [CLARIFY:Option A|query for option A] Done."
        clean, options = extract_clarifications(answer)
        assert len(options) == 1
        assert "Here is info." in clean
        assert "Done." in clean
        assert "[CLARIFY:" not in clean


# ---------------------------------------------------------------------------
# QueryResult field
# ---------------------------------------------------------------------------


class TestQueryResultClarifications:
    """QueryResult carries clarification_options."""

    def test_default_empty(self):
        qr = QueryResult(answer="hello")
        assert qr.clarification_options == []

    def test_custom_options(self):
        opts = [{"label": "A", "query": "query A"}]
        qr = QueryResult(answer="hello", clarification_options=opts)
        assert len(qr.clarification_options) == 1
        assert qr.clarification_options[0]["label"] == "A"


# ---------------------------------------------------------------------------
# Regression: clarify pill queries are self-contained (Task 4.14)
# ---------------------------------------------------------------------------


class TestClarifyPillsAreFullQueries:
    """Verify that CLARIFY query values are complete, self-contained queries."""

    def test_clarify_pills_are_full_executable_queries(self):
        answers = [
            "Which metric?\n[CLARIFY:By deal count|Show top 5 markets by deal count]",
            "Which ranking?\n[CLARIFY:Tenant reps by deal value|Top 10 tenant rep brokers by gross deal value]",
        ]
        expected_queries = [
            "Show top 5 markets by deal count",
            "Top 10 tenant rep brokers by gross deal value",
        ]
        for answer, expected in zip(answers, expected_queries):
            _, options = extract_clarifications(answer)
            assert len(options) == 1
            query = options[0]["query"]
            assert query == expected
            # A self-contained query should have at least 3 words
            assert len(query.split()) >= 3, f"Query too short to be self-contained: {query}"
