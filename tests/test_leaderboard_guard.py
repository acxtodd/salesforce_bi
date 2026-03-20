"""Tests for _handle_aggregate post-processing: sorting, truncation, metadata (Task 4.13e).

These tests validate that grouped aggregate results come back sorted, optionally
truncated, and annotated with ordering metadata.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.tool_dispatch import ToolDispatcher, build_field_registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIMPLE_CONFIG = {
    "ascendix__Property__c": {
        "embed_fields": ["Name", "ascendix__City__c"],
        "metadata_fields": ["ascendix__TotalBuildingArea__c"],
        "parents": {},
    },
}


def _make_dispatcher(aggregate_return: dict):
    backend = MagicMock()
    backend.aggregate.return_value = aggregate_return
    registry = build_field_registry(_SIMPLE_CONFIG)
    d = ToolDispatcher(backend, "test_ns", registry)
    return d, backend


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGroupedSortDescDefault:
    """Grouped results come back sorted descending by aggregate value (default)."""

    def test_sorted_desc_by_count(self):
        d, _ = _make_dispatcher(
            aggregate_return={
                "groups": {
                    "B": {"count": 5},
                    "C": {"count": 2},
                    "A": {"count": 10},
                },
            }
        )
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "count",
                "group_by": "city",
            },
        })
        groups = result["result"]["groups"]
        keys = list(groups.keys())
        assert keys[0] == "A", f"Expected A first, got {keys}"
        assert groups["A"]["count"] >= groups[keys[1]]["count"]


class TestTopNTruncation:
    """top_n truncates and marks metadata correctly."""

    def test_top_n_truncates(self):
        d, _ = _make_dispatcher(
            aggregate_return={
                "groups": {
                    "A": {"count": 10},
                    "B": {"count": 8},
                    "C": {"count": 6},
                    "D": {"count": 4},
                    "E": {"count": 2},
                },
            }
        )
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "count",
                "group_by": "city",
                "top_n": 2,
            },
        })
        r = result["result"]
        assert len(r["groups"]) == 2
        assert r["_truncated"] is True
        assert r["_total_groups"] == 5
        assert r["_showing"] == 2


class TestSortAsc:
    """sort_order='asc' puts lowest value first."""

    def test_asc_order(self):
        d, _ = _make_dispatcher(
            aggregate_return={
                "groups": {
                    "A": {"count": 10},
                    "B": {"count": 5},
                    "C": {"count": 1},
                },
            }
        )
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "count",
                "group_by": "city",
                "sort_order": "asc",
            },
        })
        keys = list(result["result"]["groups"].keys())
        assert keys[0] == "C", f"Expected C (lowest) first, got {keys}"
        assert result["result"]["_order"] == "asc"


class TestUngroupedPassthrough:
    """Un-grouped aggregates pass through without metadata keys."""

    def test_no_groups_no_metadata(self):
        d, _ = _make_dispatcher(aggregate_return={"count": 42})
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "count",
            },
        })
        r = result["result"]
        assert r["count"] == 42
        assert "_sorted_by" not in r
        assert "_order" not in r
        assert "_truncated" not in r


class TestTieBreaking:
    """Tied aggregate values produce deterministic alphabetical ordering."""

    def test_ties_sorted_alphabetically_desc(self):
        d, _ = _make_dispatcher(
            aggregate_return={
                "groups": {
                    "Dallas": {"count": 5},
                    "Austin": {"count": 5},
                    "Chicago": {"count": 5},
                },
            }
        )
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "count",
                "group_by": "city",
                "sort_order": "desc",
            },
        })
        keys = list(result["result"]["groups"].keys())
        # All counts equal → alphabetical tiebreak: Austin, Chicago, Dallas
        assert keys == ["Austin", "Chicago", "Dallas"]

    def test_ties_sorted_alphabetically_asc(self):
        d, _ = _make_dispatcher(
            aggregate_return={
                "groups": {
                    "Z_city": {"count": 3},
                    "A_city": {"count": 3},
                    "M_city": {"count": 3},
                },
            }
        )
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "count",
                "group_by": "city",
                "sort_order": "asc",
            },
        })
        keys = list(result["result"]["groups"].keys())
        assert keys == ["A_city", "M_city", "Z_city"]

    def test_mixed_values_with_ties(self):
        """Groups with different values sort by value; ties break alphabetically."""
        d, _ = _make_dispatcher(
            aggregate_return={
                "groups": {
                    "B": {"count": 10},
                    "D": {"count": 5},
                    "A": {"count": 10},
                    "C": {"count": 5},
                },
            }
        )
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "count",
                "group_by": "city",
                "sort_order": "desc",
            },
        })
        keys = list(result["result"]["groups"].keys())
        # 10: A, B (alpha); then 5: C, D (alpha)
        assert keys == ["A", "B", "C", "D"]


class TestSortedByMetadata:
    """_sorted_by matches the aggregate function used."""

    def test_sorted_by_sum(self):
        d, _ = _make_dispatcher(
            aggregate_return={
                "groups": {
                    "A": {"sum": 100},
                    "B": {"sum": 200},
                },
            }
        )
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "sum",
                "aggregate_field": "total_sf",
                "group_by": "city",
            },
        })
        assert result["result"]["_sorted_by"] == "sum"

    def test_sorted_by_avg(self):
        d, _ = _make_dispatcher(
            aggregate_return={
                "groups": {
                    "X": {"avg": 3.5},
                    "Y": {"avg": 7.2},
                },
            }
        )
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "avg",
                "aggregate_field": "total_sf",
                "group_by": "city",
            },
        })
        assert result["result"]["_sorted_by"] == "avg"
