"""
Tests for Value Normalizer.

Includes unit tests and property-based tests for value normalization.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 3.1, 3.2, 3.3, 3.4, 3.5**
"""
import os
import sys
import pytest
from datetime import date
from typing import Optional

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from value_normalizer import (
    ValueNormalizer,
    NormalizedValue,
    SizeRange,
    SizeParser,
    PercentageValue,
    PercentageParser,
    GeoExpansion,
    GeoExpander,
    StageStatusMapper,
    parse_size_range,
    parse_percentage,
    expand_geography,
    map_stage,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def normalizer():
    """Create a ValueNormalizer instance."""
    return ValueNormalizer()


@pytest.fixture
def size_parser():
    """Create a SizeParser instance."""
    return SizeParser()


@pytest.fixture
def percentage_parser():
    """Create a PercentageParser instance."""
    return PercentageParser()


@pytest.fixture
def geo_expander():
    """Create a GeoExpander instance."""
    return GeoExpander()


@pytest.fixture
def stage_mapper():
    """Create a StageStatusMapper instance."""
    return StageStatusMapper()


# =============================================================================
# SizeParser Unit Tests
# =============================================================================


class TestSizeParser:
    """Unit tests for SizeParser."""

    def test_range_pattern_basic(self, size_parser):
        """Test basic range pattern like '20k-50k sf'."""
        result = size_parser.parse("20k-50k sf")
        assert result.min_value == 20000
        assert result.max_value == 50000
        assert result.unit == "sf"

    def test_range_pattern_with_commas(self, size_parser):
        """Test range pattern with commas like '20,000-50,000 sf'."""
        result = size_parser.parse("20,000-50,000 sf")
        assert result.min_value == 20000
        assert result.max_value == 50000

    def test_over_pattern(self, size_parser):
        """Test 'over 100,000 square feet'."""
        result = size_parser.parse("over 100,000 square feet")
        assert result.min_value == 100000
        assert result.max_value is None

    def test_under_pattern(self, size_parser):
        """Test 'under 5000 sqft'."""
        result = size_parser.parse("under 5000 sqft")
        assert result.min_value is None
        assert result.max_value == 5000

    def test_between_pattern(self, size_parser):
        """Test 'between 10,000 and 20,000 sf'."""
        result = size_parser.parse("between 10,000 and 20,000 sf")
        assert result.min_value == 10000
        assert result.max_value == 20000

    def test_at_least_pattern(self, size_parser):
        """Test 'at least 15000 sq ft'."""
        result = size_parser.parse("at least 15000 sq ft")
        assert result.min_value == 15000
        assert result.max_value is None

    def test_up_to_pattern(self, size_parser):
        """Test 'up to 25k sqft'."""
        result = size_parser.parse("up to 25k sqft")
        assert result.min_value is None
        assert result.max_value == 25000

    def test_exact_pattern(self, size_parser):
        """Test exact size like '5000 sf'."""
        result = size_parser.parse("5000 sf")
        assert result.min_value == 5000
        assert result.max_value == 5000

    def test_greater_than_symbol(self, size_parser):
        """Test '> 10000 sf'."""
        result = size_parser.parse("> 10000 sf")
        assert result.min_value == 10000
        assert result.max_value is None

    def test_less_than_symbol(self, size_parser):
        """Test '< 5000 sf'."""
        result = size_parser.parse("< 5000 sf")
        assert result.min_value is None
        assert result.max_value == 5000

    def test_million_multiplier(self, size_parser):
        """Test '1m sf'."""
        result = size_parser.parse("over 1m sf")
        assert result.min_value == 1000000

    def test_invalid_expression_raises_error(self, size_parser):
        """Test that invalid expressions raise ValueError."""
        with pytest.raises(ValueError, match="Unable to parse"):
            size_parser.parse("gibberish")


# =============================================================================
# PercentageParser Unit Tests
# =============================================================================


class TestPercentageParser:
    """Unit tests for PercentageParser."""

    def test_greater_than_pattern(self, percentage_parser):
        """Test 'vacancy >25%'."""
        result = percentage_parser.parse(">25%")
        assert result.value == 25
        assert result.operator == "gt"

    def test_under_pattern(self, percentage_parser):
        """Test 'under 10%'."""
        result = percentage_parser.parse("under 10%")
        assert result.value == 10
        assert result.operator == "lt"

    def test_range_pattern(self, percentage_parser):
        """Test 'between 5-15%'."""
        result = percentage_parser.parse("5-15%")
        assert result.operator == "between"
        assert result.min_value == 5
        assert result.max_value == 15

    def test_between_pattern(self, percentage_parser):
        """Test 'between 5% and 15%'."""
        result = percentage_parser.parse("between 5% and 15%")
        assert result.operator == "between"
        assert result.min_value == 5
        assert result.max_value == 15

    def test_at_least_pattern(self, percentage_parser):
        """Test 'at least 20%'."""
        result = percentage_parser.parse("at least 20%")
        assert result.value == 20
        assert result.operator == "gte"

    def test_exact_pattern(self, percentage_parser):
        """Test 'exactly 50%'."""
        result = percentage_parser.parse("exactly 50%")
        assert result.value == 50
        assert result.operator == "eq"

    def test_simple_percentage(self, percentage_parser):
        """Test '25%'."""
        result = percentage_parser.parse("25%")
        assert result.value == 25
        assert result.operator == "eq"

    def test_decimal_percentage(self, percentage_parser):
        """Test '25.5%'."""
        result = percentage_parser.parse("25.5%")
        assert result.value == 25.5
        assert result.operator == "eq"

    def test_invalid_expression_raises_error(self, percentage_parser):
        """Test that invalid expressions raise ValueError."""
        with pytest.raises(ValueError, match="Unable to parse"):
            percentage_parser.parse("gibberish")


# =============================================================================
# GeoExpander Unit Tests
# =============================================================================


class TestGeoExpander:
    """Unit tests for GeoExpander."""

    def test_pnw_expansion(self, geo_expander):
        """Test PNW region expansion."""
        result = geo_expander.expand("PNW")
        assert "WA" in result.states
        assert "OR" in result.states
        assert "Seattle" in result.cities

    def test_bay_area_expansion(self, geo_expander):
        """Test Bay Area region expansion."""
        result = geo_expander.expand("Bay Area")
        assert "CA" in result.states
        assert "San Francisco" in result.cities
        assert len(result.submarkets) > 0

    def test_downtown_submarket(self, geo_expander):
        """Test downtown submarket alias."""
        result = geo_expander.expand("downtown")
        assert "Downtown" in result.submarkets or "CBD" in result.submarkets

    def test_case_insensitive(self, geo_expander):
        """Test case insensitivity."""
        result1 = geo_expander.expand("pnw")
        result2 = geo_expander.expand("PNW")
        assert result1.states == result2.states

    def test_unknown_region(self, geo_expander):
        """Test unknown region returns original."""
        result = geo_expander.expand("Unknown Region")
        # Should return empty lists or original value
        assert result.original == "Unknown Region"

    def test_dfw_expansion(self, geo_expander):
        """Test DFW region expansion."""
        result = geo_expander.expand("DFW")
        assert "TX" in result.states
        assert "Dallas" in result.cities
        assert "Fort Worth" in result.cities


# =============================================================================
# StageStatusMapper Unit Tests
# =============================================================================


class TestStageStatusMapper:
    """Unit tests for StageStatusMapper."""

    def test_negotiation_mapping(self, stage_mapper):
        """Test negotiation stage mapping."""
        result = stage_mapper.map("negotiation")
        assert "Negotiation" in result or "Negotiating" in result

    def test_due_diligence_mapping(self, stage_mapper):
        """Test due diligence stage mapping."""
        result = stage_mapper.map("due diligence")
        assert "Due Diligence" in result

    def test_dd_alias(self, stage_mapper):
        """Test DD alias for due diligence."""
        result = stage_mapper.map("dd")
        assert "Due Diligence" in result or "DD" in result

    def test_closed_won_mapping(self, stage_mapper):
        """Test closed won stage mapping."""
        result = stage_mapper.map("closed won")
        assert "Closed Won" in result or "Closed" in result

    def test_available_mapping(self, stage_mapper):
        """Test available status mapping."""
        result = stage_mapper.map("available")
        assert "Available" in result

    def test_fuzzy_matching(self, stage_mapper):
        """Test fuzzy matching for close matches."""
        result = stage_mapper.map("negotation")  # Typo
        # Should still find a match due to fuzzy matching
        assert len(result) > 0

    def test_unknown_stage(self, stage_mapper):
        """Test unknown stage returns original."""
        result = stage_mapper.map("completely unknown stage xyz")
        assert "completely unknown stage xyz" in result


# =============================================================================
# ValueNormalizer Integration Tests
# =============================================================================


class TestValueNormalizer:
    """Integration tests for ValueNormalizer."""

    def test_normalize_date(self, normalizer):
        """Test date normalization."""
        result = normalizer.normalize("next 6 months", "date", reference_date=date(2025, 6, 15))
        assert result.field_type == "date"
        assert result.operator in ("between", "eq")

    def test_normalize_size(self, normalizer):
        """Test size normalization."""
        result = normalizer.normalize("20k-50k sf", "size")
        assert result.field_type == "size"
        assert result.operator == "between"

    def test_normalize_percentage(self, normalizer):
        """Test percentage normalization."""
        result = normalizer.normalize(">25%", "percent")
        assert result.field_type == "percent"
        assert result.operator == "gt"
        assert result.value == 25

    def test_normalize_geography(self, normalizer):
        """Test geography normalization."""
        result = normalizer.normalize("PNW", "geography")
        assert result.field_type == "geography"
        assert isinstance(result.value, GeoExpansion)

    def test_normalize_stage(self, normalizer):
        """Test stage normalization."""
        result = normalizer.normalize("negotiation", "picklist")
        assert result.field_type == "picklist"

    def test_normalize_auto_temporal(self, normalizer):
        """Test auto-detection of temporal expressions."""
        result = normalizer.normalize_auto("next 6 months", reference_date=date(2025, 6, 15))
        assert result.field_type == "date"

    def test_normalize_auto_percentage(self, normalizer):
        """Test auto-detection of percentage expressions."""
        result = normalizer.normalize_auto(">25%")
        assert result.field_type == "percent"

    def test_normalize_auto_size(self, normalizer):
        """Test auto-detection of size expressions."""
        result = normalizer.normalize_auto("20k sf")
        assert result.field_type == "size"


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_parse_size_range(self):
        """Test parse_size_range function."""
        result = parse_size_range("20k-50k sf")
        assert result.min_value == 20000
        assert result.max_value == 50000

    def test_parse_percentage(self):
        """Test parse_percentage function."""
        result = parse_percentage(">25%")
        assert result.value == 25
        assert result.operator == "gt"

    def test_expand_geography(self):
        """Test expand_geography function."""
        result = expand_geography("PNW")
        assert "WA" in result.states

    def test_map_stage(self):
        """Test map_stage function."""
        result = map_stage("negotiation")
        assert len(result) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# =============================================================================
# Property-Based Tests
# =============================================================================

from hypothesis import given, strategies as st, settings, assume


# Strategy for generating size values (reasonable range)
size_values = st.integers(min_value=100, max_value=10_000_000)

# Strategy for generating size multiplier suffixes
size_suffixes = st.sampled_from(["", "k", "K"])

# Strategy for generating size units
size_units = st.sampled_from(["sf", "sqft", "square feet", "sq ft"])

# Strategy for generating comparison operators
comparison_ops = st.sampled_from(["over", "under", "at least", "up to", ">", "<", ">=", "<="])

# Strategy for generating percentage values (0-100)
percentage_values = st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False)


@given(
    min_val=st.integers(min_value=100, max_value=500_000),
    max_val=st.integers(min_value=100, max_value=500_000),
    unit=size_units,
)
@settings(max_examples=100)
def test_property_size_range_normalization(min_val, max_val, unit):
    """
    **Feature: graph-aware-zero-config-retrieval, Property 6: Size Range Normalization**
    **Validates: Requirements 3.2**

    *For any* size range expression, the Value Normalizer SHALL produce
    numeric predicates with min ≤ max (when range).
    """
    # Ensure min <= max for valid range
    if min_val > max_val:
        min_val, max_val = max_val, min_val

    # Build expression
    expression = f"{min_val}-{max_val} {unit}"

    parser = SizeParser()
    result = parser.parse(expression)

    # Property: min must be <= max when both are present
    if result.min_value is not None and result.max_value is not None:
        assert result.min_value <= result.max_value, (
            f"SizeRange min ({result.min_value}) must be <= max ({result.max_value}) "
            f"for expression '{expression}'"
        )

    # Property: values should be positive
    if result.min_value is not None:
        assert result.min_value >= 0, f"min_value should be >= 0, got {result.min_value}"
    if result.max_value is not None:
        assert result.max_value >= 0, f"max_value should be >= 0, got {result.max_value}"


@given(
    value=st.integers(min_value=100, max_value=1_000_000),
    op=st.sampled_from(["over", "under", "at least", "up to"]),
    unit=size_units,
)
@settings(max_examples=100)
def test_property_size_comparison_normalization(value, op, unit):
    """
    **Feature: graph-aware-zero-config-retrieval, Property 6: Size Range Normalization**
    **Validates: Requirements 3.2**

    *For any* size comparison expression (over/under/at least/up to),
    the Value Normalizer SHALL produce valid numeric predicates.
    """
    expression = f"{op} {value} {unit}"

    parser = SizeParser()
    result = parser.parse(expression)

    # Property: one of min or max should be set
    assert result.min_value is not None or result.max_value is not None, (
        f"At least one of min_value or max_value should be set for '{expression}'"
    )

    # Property: the set value should match the input
    if op in ("over", "at least"):
        assert result.min_value is not None, f"min_value should be set for '{op}'"
        assert result.min_value == value, f"min_value should be {value}, got {result.min_value}"
    elif op in ("under", "up to"):
        assert result.max_value is not None, f"max_value should be set for '{op}'"
        assert result.max_value == value, f"max_value should be {value}, got {result.max_value}"


@given(
    value=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_property_percentage_normalization(value):
    """
    **Feature: graph-aware-zero-config-retrieval, Property 7: Percentage Normalization**
    **Validates: Requirements 3.3**

    *For any* percentage expression, the Value Normalizer SHALL produce
    a numeric comparison with value in range [0, 100].
    """
    # Round to avoid floating point precision issues in string formatting
    value = round(value, 1)

    expression = f"{value}%"

    parser = PercentageParser()
    result = parser.parse(expression)

    # Property: value must be in range [0, 100]
    assert 0 <= result.value <= 100, (
        f"Percentage value must be in range [0, 100], got {result.value} "
        f"for expression '{expression}'"
    )

    # Property: value should match input (within floating point tolerance)
    assert abs(result.value - value) < 0.01, (
        f"Percentage value should be {value}, got {result.value}"
    )


@given(
    min_pct=st.floats(min_value=0, max_value=50, allow_nan=False, allow_infinity=False),
    max_pct=st.floats(min_value=50, max_value=100, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100)
def test_property_percentage_range_normalization(min_pct, max_pct):
    """
    **Feature: graph-aware-zero-config-retrieval, Property 7: Percentage Normalization**
    **Validates: Requirements 3.3**

    *For any* percentage range expression, the Value Normalizer SHALL produce
    numeric comparisons with values in range [0, 100] and min ≤ max.
    """
    # Round to avoid floating point precision issues
    min_pct = round(min_pct, 1)
    max_pct = round(max_pct, 1)

    # Ensure min <= max
    if min_pct > max_pct:
        min_pct, max_pct = max_pct, min_pct

    expression = f"{min_pct}%-{max_pct}%"

    parser = PercentageParser()
    result = parser.parse(expression)

    # Property: operator should be "between" for range
    assert result.operator == "between", (
        f"Operator should be 'between' for range expression, got '{result.operator}'"
    )

    # Property: min and max values must be in range [0, 100]
    assert result.min_value is not None and 0 <= result.min_value <= 100, (
        f"min_value must be in range [0, 100], got {result.min_value}"
    )
    assert result.max_value is not None and 0 <= result.max_value <= 100, (
        f"max_value must be in range [0, 100], got {result.max_value}"
    )

    # Property: min must be <= max
    assert result.min_value <= result.max_value, (
        f"min_value ({result.min_value}) must be <= max_value ({result.max_value})"
    )


@given(
    value=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
    op=st.sampled_from([">", "<", ">=", "<=", "over", "under", "at least", "up to"]),
)
@settings(max_examples=100)
def test_property_percentage_comparison_normalization(value, op):
    """
    **Feature: graph-aware-zero-config-retrieval, Property 7: Percentage Normalization**
    **Validates: Requirements 3.3**

    *For any* percentage comparison expression, the Value Normalizer SHALL produce
    a numeric comparison with value in range [0, 100].
    """
    value = round(value, 1)
    expression = f"{op} {value}%"

    parser = PercentageParser()
    result = parser.parse(expression)

    # Property: value must be in range [0, 100]
    assert 0 <= result.value <= 100, (
        f"Percentage value must be in range [0, 100], got {result.value} "
        f"for expression '{expression}'"
    )

    # Property: operator should be appropriate for the comparison
    expected_ops = {
        ">": "gt",
        "<": "lt",
        ">=": "gte",
        "<=": "lte",
        "over": "gt",
        "under": "lt",
        "at least": "gte",
        "up to": "lte",
    }
    assert result.operator == expected_ops[op], (
        f"Operator should be '{expected_ops[op]}' for '{op}', got '{result.operator}'"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
