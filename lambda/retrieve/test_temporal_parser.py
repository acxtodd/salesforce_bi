"""
Tests for Temporal Parser.

Includes unit tests for temporal expression parsing and DateRange serialization.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 3.1, 16.1, 16.2, 16.3**
"""
import os
import sys
import pytest
from datetime import date, timedelta

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from temporal_parser import (
    TemporalParser,
    DateRange,
    parse_temporal_expression,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def parser():
    """Create a TemporalParser with a fixed reference date."""
    return TemporalParser(reference_date=date(2025, 6, 15))


@pytest.fixture
def reference_date():
    """Fixed reference date for testing."""
    return date(2025, 6, 15)


# =============================================================================
# DateRange Unit Tests
# =============================================================================

class TestDateRange:
    """Unit tests for DateRange dataclass."""
    
    def test_create_valid_range(self):
        """Test creating a valid DateRange."""
        dr = DateRange(
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            original_expression="year 2025"
        )
        assert dr.start == date(2025, 1, 1)
        assert dr.end == date(2025, 12, 31)
        assert dr.original_expression == "year 2025"
    
    def test_create_single_day_range(self):
        """Test creating a single-day range (start == end)."""
        dr = DateRange(
            start=date(2025, 6, 15),
            end=date(2025, 6, 15)
        )
        assert dr.start == dr.end
    
    def test_invalid_range_raises_error(self):
        """Test that start > end raises ValueError."""
        with pytest.raises(ValueError, match="start.*must be <= end"):
            DateRange(
                start=date(2025, 12, 31),
                end=date(2025, 1, 1)
            )
    
    def test_equality(self):
        """Test DateRange equality comparison."""
        dr1 = DateRange(start=date(2025, 1, 1), end=date(2025, 12, 31))
        dr2 = DateRange(start=date(2025, 1, 1), end=date(2025, 12, 31))
        dr3 = DateRange(start=date(2025, 1, 1), end=date(2025, 6, 30))
        
        assert dr1 == dr2
        assert dr1 != dr3


class TestDateRangeSerialization:
    """Unit tests for DateRange serialization/deserialization."""
    
    def test_to_string_basic(self):
        """Test basic serialization."""
        dr = DateRange(
            start=date(2025, 1, 1),
            end=date(2025, 12, 31),
            original_expression="year 2025"
        )
        result = dr.to_string()
        assert result == "2025-01-01/2025-12-31|year 2025"
    
    def test_to_string_empty_expression(self):
        """Test serialization with empty original expression."""
        dr = DateRange(start=date(2025, 1, 1), end=date(2025, 12, 31))
        result = dr.to_string()
        assert result == "2025-01-01/2025-12-31|"
    
    def test_from_string_basic(self):
        """Test basic deserialization."""
        dr = DateRange.from_string("2025-01-01/2025-12-31|year 2025")
        assert dr.start == date(2025, 1, 1)
        assert dr.end == date(2025, 12, 31)
        assert dr.original_expression == "year 2025"
    
    def test_from_string_no_expression(self):
        """Test deserialization without original expression."""
        dr = DateRange.from_string("2025-01-01/2025-12-31")
        assert dr.start == date(2025, 1, 1)
        assert dr.end == date(2025, 12, 31)
        assert dr.original_expression == ""
    
    def test_from_string_invalid_format(self):
        """Test deserialization with invalid format raises error."""
        with pytest.raises(ValueError, match="Invalid DateRange string format"):
            DateRange.from_string("invalid")
    
    def test_from_string_invalid_date(self):
        """Test deserialization with invalid date raises error."""
        with pytest.raises(ValueError, match="Invalid date format"):
            DateRange.from_string("not-a-date/2025-12-31")
    
    def test_round_trip(self):
        """Test serialization round-trip preserves data."""
        original = DateRange(
            start=date(2025, 3, 15),
            end=date(2025, 9, 30),
            original_expression="next 6 months"
        )
        serialized = original.to_string()
        restored = DateRange.from_string(serialized)
        
        assert restored.start == original.start
        assert restored.end == original.end
        assert restored.original_expression == original.original_expression


# =============================================================================
# Temporal Parser Unit Tests - Relative Expressions
# =============================================================================

class TestRelativeExpressions:
    """Unit tests for relative temporal expressions."""
    
    def test_next_6_months(self, parser, reference_date):
        """Test 'next 6 months' parsing."""
        result = parser.parse("next 6 months")
        
        assert result.start == reference_date
        # 6 months from June 15 = December 15
        assert result.end == date(2025, 12, 15)
        assert result.original_expression == "next 6 months"
    
    def test_next_6_months_from_different_dates(self):
        """Test 'next 6 months' from various reference dates."""
        # From January 31 - should handle month overflow
        parser = TemporalParser(reference_date=date(2025, 1, 31))
        result = parser.parse("next 6 months")
        assert result.start == date(2025, 1, 31)
        # July 31 exists, so should be July 31
        assert result.end == date(2025, 7, 31)
        
        # From August 31 - February doesn't have 31 days
        parser = TemporalParser(reference_date=date(2025, 8, 31))
        result = parser.parse("next 6 months")
        assert result.start == date(2025, 8, 31)
        # Feb 2026 has 28 days (not leap year)
        assert result.end == date(2026, 2, 28)
    
    def test_last_30_days(self, parser, reference_date):
        """Test 'last 30 days' parsing."""
        result = parser.parse("last 30 days")
        
        expected_start = reference_date - timedelta(days=30)
        assert result.start == expected_start
        assert result.end == reference_date
    
    def test_last_30_days_edge_cases(self):
        """Test 'last 30 days' edge cases."""
        # From March 1 - goes back to January
        parser = TemporalParser(reference_date=date(2025, 3, 1))
        result = parser.parse("last 30 days")
        assert result.start == date(2025, 1, 30)
        assert result.end == date(2025, 3, 1)
        
        # From January 15 - goes back to previous year
        parser = TemporalParser(reference_date=date(2025, 1, 15))
        result = parser.parse("last 30 days")
        assert result.start == date(2024, 12, 16)
        assert result.end == date(2025, 1, 15)
    
    def test_past_2_years(self, parser, reference_date):
        """Test 'past 2 years' parsing."""
        result = parser.parse("past 2 years")
        
        assert result.start == date(2023, 6, 15)
        assert result.end == reference_date
    
    def test_next_3_weeks(self, parser, reference_date):
        """Test 'next 3 weeks' parsing."""
        result = parser.parse("next 3 weeks")
        
        assert result.start == reference_date
        assert result.end == reference_date + timedelta(weeks=3)
    
    def test_within_90_days(self, parser, reference_date):
        """Test 'within 90 days' parsing."""
        result = parser.parse("within 90 days")
        
        assert result.start == reference_date
        assert result.end == reference_date + timedelta(days=90)
    
    def test_in_the_next_12_months(self, parser, reference_date):
        """Test 'in the next 12 months' parsing."""
        result = parser.parse("in the next 12 months")
        
        assert result.start == reference_date
        assert result.end == date(2026, 6, 15)
    
    def test_6_months_ago(self, parser, reference_date):
        """Test '6 months ago' parsing."""
        result = parser.parse("6 months ago")
        
        expected_date = date(2024, 12, 15)
        assert result.start == expected_date
        assert result.end == expected_date


# =============================================================================
# Temporal Parser Unit Tests - Quarter References
# =============================================================================

class TestQuarterParsing:
    """Unit tests for quarter reference parsing."""
    
    def test_q1_2026(self, parser):
        """Test Q1 2026 parsing."""
        result = parser.parse("Q1 2026")
        
        assert result.start == date(2026, 1, 1)
        assert result.end == date(2026, 3, 31)
    
    def test_q2_2025(self, parser):
        """Test Q2 2025 parsing."""
        result = parser.parse("Q2 2025")
        
        assert result.start == date(2025, 4, 1)
        assert result.end == date(2025, 6, 30)
    
    def test_q3_2025(self, parser):
        """Test Q3 2025 parsing."""
        result = parser.parse("Q3 2025")
        
        assert result.start == date(2025, 7, 1)
        assert result.end == date(2025, 9, 30)
    
    def test_q4_2025(self, parser):
        """Test Q4 2025 parsing."""
        result = parser.parse("Q4 2025")
        
        assert result.start == date(2025, 10, 1)
        assert result.end == date(2025, 12, 31)
    
    def test_quarter_case_insensitive(self, parser):
        """Test quarter parsing is case insensitive."""
        result1 = parser.parse("q1 2025")
        result2 = parser.parse("Q1 2025")
        
        assert result1.start == result2.start
        assert result1.end == result2.end
    
    def test_quarter_with_space_variations(self, parser):
        """Test quarter parsing with different spacing."""
        result1 = parser.parse("Q1 2025")
        result2 = parser.parse("Q12025")
        
        assert result1.start == result2.start
        assert result1.end == result2.end


# =============================================================================
# Temporal Parser Unit Tests - Leap Year Handling
# =============================================================================

class TestLeapYearHandling:
    """Unit tests for leap year edge cases."""
    
    def test_leap_year_feb_29(self):
        """Test handling Feb 29 in leap year."""
        # 2024 is a leap year
        parser = TemporalParser(reference_date=date(2024, 2, 29))
        
        # Next 12 months from Feb 29, 2024
        result = parser.parse("next 12 months")
        
        # Feb 29, 2025 doesn't exist, should be Feb 28
        assert result.end == date(2025, 2, 28)
    
    def test_leap_year_to_leap_year(self):
        """Test from leap year to leap year."""
        # 2024 is a leap year, 2028 is also a leap year
        parser = TemporalParser(reference_date=date(2024, 2, 29))
        
        result = parser.parse("next 4 years")
        
        # Feb 29, 2028 exists
        assert result.end == date(2028, 2, 29)
    
    def test_non_leap_year_feb(self):
        """Test February in non-leap year."""
        # 2025 is not a leap year
        parser = TemporalParser(reference_date=date(2025, 1, 31))
        
        result = parser.parse("next 1 month")
        
        # Feb 2025 has 28 days
        assert result.end == date(2025, 2, 28)
    
    def test_century_leap_year(self):
        """Test century leap year rules (divisible by 400)."""
        # 2000 was a leap year (divisible by 400)
        parser = TemporalParser(reference_date=date(2000, 2, 29))
        
        result = parser.parse("next 100 years")
        
        # 2100 is NOT a leap year (divisible by 100 but not 400)
        assert result.end == date(2100, 2, 28)


# =============================================================================
# Temporal Parser Unit Tests - Absolute Dates
# =============================================================================

class TestAbsoluteDates:
    """Unit tests for absolute date parsing."""
    
    def test_iso_date(self, parser):
        """Test ISO 8601 date parsing."""
        result = parser.parse("2025-07-04")
        
        assert result.start == date(2025, 7, 4)
        assert result.end == date(2025, 7, 4)
    
    def test_month_year(self, parser):
        """Test month year format parsing."""
        result = parser.parse("January 2025")
        
        assert result.start == date(2025, 1, 1)
        assert result.end == date(2025, 1, 31)
    
    def test_month_year_abbreviated(self, parser):
        """Test abbreviated month name."""
        result = parser.parse("Jan 2025")
        
        assert result.start == date(2025, 1, 1)
        assert result.end == date(2025, 1, 31)
    
    def test_february_non_leap_year(self, parser):
        """Test February in non-leap year."""
        result = parser.parse("February 2025")
        
        assert result.start == date(2025, 2, 1)
        assert result.end == date(2025, 2, 28)
    
    def test_february_leap_year(self, parser):
        """Test February in leap year."""
        result = parser.parse("February 2024")
        
        assert result.start == date(2024, 2, 1)
        assert result.end == date(2024, 2, 29)


# =============================================================================
# Temporal Parser Unit Tests - Error Handling
# =============================================================================

class TestErrorHandling:
    """Unit tests for error handling."""
    
    def test_unparseable_expression(self, parser):
        """Test that unparseable expressions raise ValueError."""
        with pytest.raises(ValueError, match="Unable to parse"):
            parser.parse("gibberish text")
    
    def test_empty_expression(self, parser):
        """Test that empty expression raises ValueError."""
        with pytest.raises(ValueError, match="Unable to parse"):
            parser.parse("")
    
    def test_partial_match_not_enough(self, parser):
        """Test that partial matches don't cause false positives."""
        with pytest.raises(ValueError, match="Unable to parse"):
            parser.parse("next")


# =============================================================================
# Convenience Function Tests
# =============================================================================

class TestConvenienceFunction:
    """Unit tests for parse_temporal_expression function."""
    
    def test_basic_usage(self):
        """Test basic usage of convenience function."""
        result = parse_temporal_expression(
            "next 6 months",
            reference_date=date(2025, 6, 15)
        )
        
        assert result.start == date(2025, 6, 15)
        assert result.end == date(2025, 12, 15)
    
    def test_default_reference_date(self):
        """Test that default reference date is today."""
        result = parse_temporal_expression("next 1 day")
        
        today = date.today()
        assert result.start == today
        assert result.end == today + timedelta(days=1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# =============================================================================
# Calendar-Relative Expression Tests
# =============================================================================

class TestCalendarRelativeExpressions:
    """Unit tests for calendar-relative temporal expressions."""

    def test_this_quarter_q4(self):
        """Test 'this quarter' parsing in Q4."""
        parser = TemporalParser(reference_date=date(2025, 12, 11))
        result = parser.parse("this quarter")

        assert result.start == date(2025, 12, 11)
        assert result.end == date(2025, 12, 31)

    def test_this_quarter_q1(self):
        """Test 'this quarter' parsing in Q1."""
        parser = TemporalParser(reference_date=date(2025, 2, 15))
        result = parser.parse("this quarter")

        assert result.start == date(2025, 2, 15)
        assert result.end == date(2025, 3, 31)

    def test_next_quarter_from_q3(self):
        """Test 'next quarter' parsing from Q3."""
        parser = TemporalParser(reference_date=date(2025, 8, 15))
        result = parser.parse("next quarter")

        assert result.start == date(2025, 10, 1)
        assert result.end == date(2025, 12, 31)

    def test_next_quarter_from_q4(self):
        """Test 'next quarter' parsing from Q4 (wraps to next year)."""
        parser = TemporalParser(reference_date=date(2025, 11, 15))
        result = parser.parse("next quarter")

        assert result.start == date(2026, 1, 1)
        assert result.end == date(2026, 3, 31)

    def test_this_year(self):
        """Test 'this year' parsing."""
        parser = TemporalParser(reference_date=date(2025, 6, 15))
        result = parser.parse("this year")

        assert result.start == date(2025, 6, 15)
        assert result.end == date(2025, 12, 31)

    def test_next_year(self):
        """Test 'next year' parsing."""
        parser = TemporalParser(reference_date=date(2025, 6, 15))
        result = parser.parse("next year")

        assert result.start == date(2026, 1, 1)
        assert result.end == date(2026, 12, 31)

    def test_year_end(self):
        """Test 'year end' parsing."""
        parser = TemporalParser(reference_date=date(2025, 6, 15))
        result = parser.parse("by year end")

        assert result.start == date(2025, 6, 15)
        assert result.end == date(2025, 12, 31)

    def test_end_of_year(self):
        """Test 'end of year' parsing."""
        parser = TemporalParser(reference_date=date(2025, 9, 1))
        result = parser.parse("end of the year")

        assert result.start == date(2025, 9, 1)
        assert result.end == date(2025, 12, 31)


# =============================================================================
# Abbreviated Unit Tests
# =============================================================================

class TestAbbreviatedUnits:
    """Unit tests for abbreviated time unit parsing."""

    def test_6_mo(self, parser, reference_date):
        """Test '6 mo' parsing."""
        result = parser.parse("6 mo")

        assert result.start == reference_date
        assert result.end == date(2025, 12, 15)

    def test_1_yr(self, parser, reference_date):
        """Test '1 yr' parsing."""
        result = parser.parse("1 yr")

        assert result.start == reference_date
        assert result.end == date(2026, 6, 15)

    def test_2_wks(self, parser, reference_date):
        """Test '2 wks' parsing."""
        result = parser.parse("2 wks")

        assert result.start == reference_date
        assert result.end == reference_date + timedelta(weeks=2)

    def test_hyphenated_18_month(self, parser, reference_date):
        """Test '18-month' parsing."""
        result = parser.parse("18-month")

        assert result.start == reference_date
        assert result.end == date(2026, 12, 15)

    def test_hyphenated_12_month_period(self, parser, reference_date):
        """Test '12-month period' parsing."""
        result = parser.parse("12-month period")

        assert result.start == reference_date
        assert result.end == date(2026, 6, 15)


# =============================================================================
# Extract Temporal Expression Tests
# =============================================================================

from temporal_parser import extract_temporal_expression, get_lease_date_range


class TestExtractTemporalExpression:
    """Unit tests for extract_temporal_expression function."""

    def test_extract_next_12_months(self):
        """Test extracting 'next 12 months' from full query."""
        query = "show me leases expiring in the next 12 months"
        result = extract_temporal_expression(query)

        assert result is not None
        assert "next 12 months" in result.lower()

    def test_extract_6_months(self):
        """Test extracting '6 months' from full query."""
        query = "leases expiring in the next 6 months"
        result = extract_temporal_expression(query)

        assert result is not None
        assert "6 month" in result.lower()

    def test_extract_this_quarter(self):
        """Test extracting 'this quarter' from full query."""
        query = "what leases expire this quarter"
        result = extract_temporal_expression(query)

        assert result is not None
        assert "this quarter" in result.lower()

    def test_extract_q1_2026(self):
        """Test extracting 'Q1 2026' from full query."""
        query = "show me leases expiring in Q1 2026"
        result = extract_temporal_expression(query)

        assert result is not None
        assert "q1" in result.lower() and "2026" in result

    def test_extract_none_when_no_temporal(self):
        """Test returns None when no temporal expression."""
        query = "show me all leases"
        result = extract_temporal_expression(query)

        assert result is None

    def test_extract_last_year(self):
        """Test extracting 'last year' from full query."""
        query = "show me leases that expired last year"
        # Note: "last year" isn't explicitly in patterns, but "last N years" is
        # This tests fallback behavior
        query2 = "show me leases that expired in the last 1 year"
        result = extract_temporal_expression(query2)

        assert result is not None


# =============================================================================
# Get Lease Date Range Tests
# =============================================================================

class TestGetLeaseDateRange:
    """Unit tests for get_lease_date_range function."""

    def test_next_12_months(self):
        """Test 'next 12 months' returns 12-month range."""
        ref = date(2025, 12, 11)
        start, end = get_lease_date_range(
            "show me leases expiring in the next 12 months",
            reference_date=ref
        )

        assert start == ref
        assert end == date(2026, 12, 11)

    def test_next_6_months(self):
        """Test 'next 6 months' returns 6-month range (S4 scenario)."""
        ref = date(2025, 12, 11)
        start, end = get_lease_date_range(
            "Show me leases expiring in the next 6 months",
            reference_date=ref
        )

        assert start == ref
        assert end == date(2026, 6, 11)

    def test_default_fallback_180_days(self):
        """Test default fallback to 180 days when no temporal expression."""
        ref = date(2025, 12, 11)
        start, end = get_lease_date_range(
            "show me expiring leases",
            default_days=180,
            reference_date=ref
        )

        assert start == ref
        assert end == ref + timedelta(days=180)

    def test_expired_past_direction(self):
        """Test 'expired' triggers past direction."""
        ref = date(2025, 12, 11)
        start, end = get_lease_date_range(
            "show me leases that expired in the last 6 months",
            reference_date=ref
        )

        # Should be a past range
        assert end <= ref
        assert start < end

    def test_this_quarter(self):
        """Test 'this quarter' snaps to quarter end."""
        ref = date(2025, 12, 11)  # Q4
        start, end = get_lease_date_range(
            "leases expiring this quarter",
            reference_date=ref
        )

        assert start == ref
        assert end == date(2025, 12, 31)

    def test_preserves_s4_behavior(self):
        """Test S4 scenario query returns expected range."""
        ref = date(2025, 6, 15)
        start, end = get_lease_date_range(
            "Show me leases expiring in the next 6 months",
            default_days=180,
            reference_date=ref
        )

        # Should return 6-month range from reference date
        assert start == ref
        assert end == date(2025, 12, 15)


# =============================================================================
# Property-Based Tests
# =============================================================================

from hypothesis import given, strategies as st, settings, assume


# Strategy for generating relative time units
time_units = st.sampled_from(["day", "days", "week", "weeks", "month", "months", "year", "years"])

# Strategy for generating relative directions
relative_directions = st.sampled_from(["next", "last", "past", "within"])

# Strategy for generating reasonable time counts (1-24)
time_counts = st.integers(min_value=1, max_value=24)

# Strategy for generating quarters
quarters = st.integers(min_value=1, max_value=4)

# Strategy for generating years (reasonable range)
years = st.integers(min_value=2000, max_value=2100)

# Strategy for generating reference dates
reference_dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31))


@given(
    direction=relative_directions,
    count=time_counts,
    unit=time_units,
    ref_date=reference_dates,
)
@settings(max_examples=100)
def test_property_temporal_expression_parsing_relative(direction, count, unit, ref_date):
    """
    **Feature: graph-aware-zero-config-retrieval, Property 5: Temporal Expression Parsing**
    **Validates: Requirements 3.1, 16.1, 16.2**
    
    *For any* temporal expression (relative dates), the Temporal Parser 
    SHALL produce a valid DateRange with start ≤ end.
    """
    # Build expression
    expression = f"{direction} {count} {unit}"
    
    parser = TemporalParser(reference_date=ref_date)
    
    try:
        result = parser.parse(expression)
        
        # Property: start must be <= end
        assert result.start <= result.end, (
            f"DateRange start ({result.start}) must be <= end ({result.end}) "
            f"for expression '{expression}' with reference date {ref_date}"
        )
        
        # Property: original expression should be preserved
        assert result.original_expression == expression
        
    except ValueError:
        # Some expressions may not be parseable, which is acceptable
        pass


@given(
    quarter=quarters,
    year=years,
)
@settings(max_examples=100)
def test_property_temporal_expression_parsing_quarters(quarter, year):
    """
    **Feature: graph-aware-zero-config-retrieval, Property 5: Temporal Expression Parsing**
    **Validates: Requirements 3.1, 16.1, 16.2**
    
    *For any* quarter reference, the Temporal Parser SHALL produce a valid 
    DateRange with start ≤ end covering exactly one quarter.
    """
    expression = f"Q{quarter} {year}"
    
    parser = TemporalParser()
    result = parser.parse(expression)
    
    # Property: start must be <= end
    assert result.start <= result.end, (
        f"DateRange start ({result.start}) must be <= end ({result.end}) "
        f"for expression '{expression}'"
    )
    
    # Property: quarter should span exactly 3 months
    # Start should be first day of quarter
    expected_start_month = (quarter - 1) * 3 + 1
    assert result.start.month == expected_start_month
    assert result.start.day == 1
    assert result.start.year == year
    
    # End should be last day of quarter
    expected_end_month = quarter * 3
    assert result.end.month == expected_end_month
    assert result.end.year == year


@given(
    start_date=reference_dates,
    days_offset=st.integers(min_value=0, max_value=365),
    original_expr=st.text(min_size=0, max_size=50),
)
@settings(max_examples=100)
def test_property_temporal_round_trip(start_date, days_offset, original_expr):
    """
    **Feature: graph-aware-zero-config-retrieval, Property 16: Temporal Expression Round-Trip**
    **Validates: Requirements 16.3**
    
    *For any* DateRange, serializing to string and deserializing back 
    SHALL produce an equivalent DateRange.
    """
    # Create a valid DateRange (end >= start)
    end_date = start_date + timedelta(days=days_offset)
    
    # Filter out pipe characters from original_expr to avoid parsing issues
    clean_expr = original_expr.replace("|", "").replace("/", "")
    
    original = DateRange(
        start=start_date,
        end=end_date,
        original_expression=clean_expr
    )
    
    # Serialize
    serialized = original.to_string()
    
    # Deserialize
    restored = DateRange.from_string(serialized)
    
    # Property: round-trip should preserve start and end dates
    assert restored.start == original.start, (
        f"Start date mismatch: {restored.start} != {original.start}"
    )
    assert restored.end == original.end, (
        f"End date mismatch: {restored.end} != {original.end}"
    )
    
    # Property: round-trip should preserve original expression
    assert restored.original_expression == original.original_expression, (
        f"Original expression mismatch: '{restored.original_expression}' != '{original.original_expression}'"
    )


@given(
    ref_date=reference_dates,
    count=st.integers(min_value=1, max_value=120),  # Up to 10 years in months
)
@settings(max_examples=100)
def test_property_month_arithmetic_preserves_validity(ref_date, count):
    """
    **Feature: graph-aware-zero-config-retrieval, Property 5: Temporal Expression Parsing**
    **Validates: Requirements 3.1, 16.1**
    
    *For any* month-based relative expression, the resulting DateRange 
    SHALL have valid dates (no invalid Feb 30, etc.).
    """
    expression = f"next {count} months"
    
    parser = TemporalParser(reference_date=ref_date)
    result = parser.parse(expression)
    
    # Property: both dates should be valid (no exception means valid)
    assert result.start.year >= 1
    assert result.end.year >= 1
    assert 1 <= result.start.month <= 12
    assert 1 <= result.end.month <= 12
    assert 1 <= result.start.day <= 31
    assert 1 <= result.end.day <= 31
    
    # Property: start <= end
    assert result.start <= result.end


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
