"""
Property-Based Tests for Derived View Manager.

**Feature: graph-aware-zero-config-retrieval**

Tests the following properties:
- Property 11: Missing Rollup Fallback with Gap Logging (Requirements 5.7)
"""

import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
import logging

import pytest
from hypothesis import given, strategies as st, settings, assume

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from derived_view_manager import (
    DerivedViewManager,
    Predicate,
    AvailabilityRecord,
    VacancyRecord,
    LeaseRecord,
    ActivityAggRecord,
    SaleRecord,
)


# =============================================================================
# Strategies for Property Testing
# =============================================================================

# Strategy for valid view names
valid_view_names = st.sampled_from([
    "availability_view",
    "vacancy_view",
    "leases_view",
    "activities_agg",
    "sales_view",
])

# Strategy for invalid/unknown view names
invalid_view_names = st.text(min_size=1, max_size=50).filter(
    lambda x: x not in [
        "availability_view",
        "vacancy_view",
        "leases_view",
        "activities_agg",
        "sales_view",
    ]
)

# Strategy for query strings
query_strings = st.text(min_size=1, max_size=200).filter(lambda x: x.strip())

# Strategy for filter operators
filter_operators = st.sampled_from(["eq", "gt", "lt", "gte", "lte", "in", "contains"])

# Strategy for field names
field_names = st.sampled_from([
    "status",
    "property_class",
    "city",
    "state",
    "size",
    "vacancy_pct",
    "stage",
    "entity_type",
])

# Strategy for filter values
filter_values = st.one_of(
    st.text(min_size=1, max_size=20),
    st.integers(min_value=0, max_value=1000000),
    st.floats(min_value=0, max_value=100, allow_nan=False),
)


# Strategy for predicates
@st.composite
def predicate_strategy(draw):
    """Generate a random Predicate."""
    field = draw(field_names)
    operator = draw(filter_operators)

    # Adjust value based on operator
    if operator == "in":
        value = draw(st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=5))
    elif operator == "contains":
        value = draw(st.text(min_size=1, max_size=20))
    else:
        value = draw(filter_values)

    return Predicate(field=field, operator=operator, value=value)


# Strategy for list of predicates
predicates_strategy = st.lists(predicate_strategy(), min_size=0, max_size=5)


# =============================================================================
# Mock DynamoDB Table for Property Testing
# =============================================================================


class EmptyMockTable:
    """Mock DynamoDB table that returns no results."""

    def query(self, **kwargs) -> Dict[str, Any]:
        return {"Items": []}

    def scan(self, **kwargs) -> Dict[str, Any]:
        return {"Items": []}

    def get_item(self, Key: Dict[str, Any]) -> Dict[str, Any]:
        return {}


class ErrorMockTable:
    """Mock DynamoDB table that raises errors."""

    def query(self, **kwargs) -> Dict[str, Any]:
        raise Exception("DynamoDB connection error")

    def scan(self, **kwargs) -> Dict[str, Any]:
        raise Exception("DynamoDB connection error")

    def get_item(self, Key: Dict[str, Any]) -> Dict[str, Any]:
        raise Exception("DynamoDB connection error")


# =============================================================================
# Property 11: Missing Rollup Fallback with Gap Logging
# Requirements: 5.7
# =============================================================================


class TestProperty11MissingRollupFallback:
    """
    Property 11: Missing Rollup Fallback with Gap Logging

    **Validates: Requirements 5.7**

    Properties tested:
    1. Unknown views always trigger fallback
    2. Empty results trigger gap logging
    3. DynamoDB errors trigger fallback gracefully
    4. Fallback flag is correctly set
    5. Gap logging includes view name, query, and filters
    """

    @given(view_name=invalid_view_names, query=query_strings)
    @settings(max_examples=50, deadline=None)
    def test_unknown_view_triggers_fallback(self, view_name: str, query: str):
        """
        Property: Querying an unknown view always triggers fallback.

        For any view name not in the known views, query_with_fallback
        should return empty results and used_fallback=True.
        """
        manager = DerivedViewManager()

        # Set up empty tables to avoid actual DynamoDB calls
        manager._tables = {
            manager.availability_table_name: EmptyMockTable(),
            manager.vacancy_table_name: EmptyMockTable(),
            manager.leases_table_name: EmptyMockTable(),
            manager.activities_table_name: EmptyMockTable(),
            manager.sales_table_name: EmptyMockTable(),
        }

        results, used_fallback = manager.query_with_fallback(
            view_name=view_name,
            query=query,
        )

        # Unknown view should trigger fallback
        assert used_fallback is True, (
            f"Unknown view '{view_name}' should trigger fallback"
        )
        assert results == [], (
            f"Unknown view '{view_name}' should return empty results"
        )

    @given(view_name=valid_view_names, query=query_strings, filters=predicates_strategy)
    @settings(max_examples=50, deadline=None)
    def test_empty_results_trigger_fallback(
        self, view_name: str, query: str, filters: List[Predicate]
    ):
        """
        Property: Empty results from a valid view trigger fallback.

        When a valid view returns no matching results, the fallback
        flag should be True and gap should be logged.
        """
        manager = DerivedViewManager()

        # Set up empty tables
        manager._tables = {
            manager.availability_table_name: EmptyMockTable(),
            manager.vacancy_table_name: EmptyMockTable(),
            manager.leases_table_name: EmptyMockTable(),
            manager.activities_table_name: EmptyMockTable(),
            manager.sales_table_name: EmptyMockTable(),
        }

        results, used_fallback = manager.query_with_fallback(
            view_name=view_name,
            query=query,
            filters=filters if filters else None,
        )

        # Empty results should trigger fallback
        assert used_fallback is True, (
            f"Empty results from '{view_name}' should trigger fallback"
        )
        assert results == [], (
            f"Empty results from '{view_name}' should return empty list"
        )

    @given(view_name=valid_view_names, query=query_strings)
    @settings(max_examples=30, deadline=None)
    def test_dynamodb_error_triggers_fallback(self, view_name: str, query: str):
        """
        Property: DynamoDB errors are handled gracefully with fallback.

        When DynamoDB raises an error, the manager should return
        empty results and trigger fallback without raising exceptions.
        """
        manager = DerivedViewManager()

        # Set up error-throwing tables
        manager._tables = {
            manager.availability_table_name: ErrorMockTable(),
            manager.vacancy_table_name: ErrorMockTable(),
            manager.leases_table_name: ErrorMockTable(),
            manager.activities_table_name: ErrorMockTable(),
            manager.sales_table_name: ErrorMockTable(),
        }

        # Should not raise, should return fallback
        results, used_fallback = manager.query_with_fallback(
            view_name=view_name,
            query=query,
        )

        # Error should trigger fallback
        assert used_fallback is True, (
            f"DynamoDB error in '{view_name}' should trigger fallback"
        )
        assert results == [], (
            f"DynamoDB error in '{view_name}' should return empty results"
        )

    @given(view_name=invalid_view_names, query=query_strings, filters=predicates_strategy)
    @settings(max_examples=30, deadline=None)
    def test_gap_logging_includes_required_fields(
        self, view_name: str, query: str, filters: List[Predicate]
    ):
        """
        Property: Gap logging includes view name, query, and filters.

        When a missing rollup gap is logged, it should include
        all required information for analysis.
        """
        manager = DerivedViewManager()

        # Set up empty tables
        manager._tables = {
            manager.availability_table_name: EmptyMockTable(),
            manager.vacancy_table_name: EmptyMockTable(),
            manager.leases_table_name: EmptyMockTable(),
            manager.activities_table_name: EmptyMockTable(),
            manager.sales_table_name: EmptyMockTable(),
        }

        # Capture log output
        with patch.object(logging.getLogger(), 'warning') as mock_log:
            manager.log_missing_rollup(
                view_name=view_name,
                query=query,
                filters=filters if filters else None,
            )

            # Verify logging was called
            mock_log.assert_called_once()

            # Get the call arguments
            call_args = mock_log.call_args
            log_message = call_args[0][0] if call_args[0] else ""
            log_extra = call_args[1].get('extra', {}) if call_args[1] else {}

            # Verify required fields are present in extra
            assert 'view_name' in log_extra, "Gap log should include view_name"
            assert 'query' in log_extra, "Gap log should include query"
            assert 'filters' in log_extra, "Gap log should include filters"
            assert 'gap_type' in log_extra, "Gap log should include gap_type"

            # Verify values match
            assert log_extra['view_name'] == view_name
            assert log_extra['gap_type'] == 'missing_rollup'

    @given(view_name=valid_view_names)
    @settings(max_examples=20, deadline=None)
    def test_check_view_exists_returns_boolean(self, view_name: str):
        """
        Property: check_view_exists always returns a boolean.

        For any valid view name, the method should return
        True or False, never raise an exception.
        """
        manager = DerivedViewManager()

        # Set up empty tables
        manager._tables = {
            manager.availability_table_name: EmptyMockTable(),
            manager.vacancy_table_name: EmptyMockTable(),
            manager.leases_table_name: EmptyMockTable(),
            manager.activities_table_name: EmptyMockTable(),
            manager.sales_table_name: EmptyMockTable(),
        }

        result = manager.check_view_exists(view_name)

        # Should always return a boolean
        assert isinstance(result, bool), (
            f"check_view_exists('{view_name}') should return bool, got {type(result)}"
        )

    @given(view_name=invalid_view_names)
    @settings(max_examples=20, deadline=None)
    def test_check_view_exists_unknown_returns_false(self, view_name: str):
        """
        Property: check_view_exists returns False for unknown views.

        For any unknown view name, the method should return False.
        """
        manager = DerivedViewManager()

        result = manager.check_view_exists(view_name)

        assert result is False, (
            f"check_view_exists('{view_name}') should return False for unknown view"
        )


# =============================================================================
# Additional Property Tests for Robustness
# =============================================================================


class TestPredicateProperties:
    """Property tests for Predicate matching behavior."""

    @given(
        field=field_names,
        operator=st.sampled_from(["gt", "gte"]),
        value=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=50, deadline=None)
    def test_gt_gte_consistency(self, field: str, operator: str, value: int):
        """
        Property: For numeric comparisons, gte(x) implies gt(x-1) for x > 0.
        """
        assume(value > 0)

        pred_gte = Predicate(field=field, operator="gte", value=value)
        pred_gt = Predicate(field=field, operator="gt", value=value - 1)

        # If gte matches value, gt(value-1) should also match
        if pred_gte.matches(value):
            assert pred_gt.matches(value), (
                f"If {value} >= {value}, then {value} > {value-1}"
            )

    @given(
        field=field_names,
        operator=st.sampled_from(["lt", "lte"]),
        value=st.integers(min_value=0, max_value=1000),
    )
    @settings(max_examples=50, deadline=None)
    def test_lt_lte_consistency(self, field: str, operator: str, value: int):
        """
        Property: For numeric comparisons, lte(x) implies lt(x+1).
        """
        pred_lte = Predicate(field=field, operator="lte", value=value)
        pred_lt = Predicate(field=field, operator="lt", value=value + 1)

        # If lte matches value, lt(value+1) should also match
        if pred_lte.matches(value):
            assert pred_lt.matches(value), (
                f"If {value} <= {value}, then {value} < {value+1}"
            )

    @given(
        field=field_names,
        values=st.lists(st.text(min_size=1, max_size=10), min_size=1, max_size=10),
    )
    @settings(max_examples=50, deadline=None)
    def test_in_operator_membership(self, field: str, values: List[str]):
        """
        Property: 'in' operator matches if and only if value is in list.
        """
        pred = Predicate(field=field, operator="in", value=values)

        for v in values:
            assert pred.matches(v), f"'{v}' should match 'in' {values}"

        # A value not in the list should not match
        non_member = "definitely_not_in_list_12345"
        assume(non_member not in values)
        assert not pred.matches(non_member), (
            f"'{non_member}' should not match 'in' {values}"
        )

    @given(field=field_names, value=filter_values)
    @settings(max_examples=50, deadline=None)
    def test_none_never_matches(self, field: str, value: Any):
        """
        Property: None values never match any predicate.
        """
        for op in ["eq", "gt", "lt", "gte", "lte", "contains"]:
            pred = Predicate(field=field, operator=op, value=value)
            assert not pred.matches(None), (
                f"None should not match {op} predicate"
            )
