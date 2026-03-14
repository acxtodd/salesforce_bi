"""
Temporal Parser for Graph-Aware Zero-Config Retrieval.

Parses natural language temporal expressions into concrete date ranges.
Supports relative expressions, quarter references, and absolute dates.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 3.1, 16.1, 16.2, 16.3**
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Tuple

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))


@dataclass
class DateRange:
    """
    Represents a date range with start and end dates.

    **Requirements: 16.1, 16.2, 16.3**

    Attributes:
        start: Start date of the range (inclusive)
        end: End date of the range (inclusive)
        original_expression: The original temporal expression that was parsed
    """

    start: date
    end: date
    original_expression: str = ""

    def __post_init__(self) -> None:
        """Validate that start <= end."""
        if self.start > self.end:
            raise ValueError(f"Invalid DateRange: start ({self.start}) must be <= end ({self.end})")

    def to_string(self) -> str:
        """
        Serialize DateRange to ISO 8601 string format.

        **Requirements: 16.3**

        Returns:
            String in format "YYYY-MM-DD/YYYY-MM-DD|original_expression"
        """
        return f"{self.start.isoformat()}/{self.end.isoformat()}|{self.original_expression}"

    @classmethod
    def from_string(cls, s: str) -> "DateRange":
        """
        Deserialize DateRange from string format.

        **Requirements: 16.3**

        Args:
            s: String in format "YYYY-MM-DD/YYYY-MM-DD|original_expression"

        Returns:
            DateRange instance

        Raises:
            ValueError: If string format is invalid
        """
        if "|" in s:
            date_part, original_expression = s.rsplit("|", 1)
        else:
            date_part = s
            original_expression = ""

        if "/" not in date_part:
            raise ValueError(f"Invalid DateRange string format: {s}")

        start_str, end_str = date_part.split("/", 1)

        try:
            start = date.fromisoformat(start_str)
            end = date.fromisoformat(end_str)
        except ValueError as e:
            raise ValueError(f"Invalid date format in DateRange string: {e}")

        return cls(start=start, end=end, original_expression=original_expression)

    def __eq__(self, other: object) -> bool:
        """Check equality based on start and end dates."""
        if not isinstance(other, DateRange):
            return False
        return self.start == other.start and self.end == other.end


class TemporalParser:
    """
    Parser for natural language temporal expressions.

    **Requirements: 3.1, 16.1, 16.2**

    Supports:
    - Relative expressions: "next N months", "last N days", "past N years"
    - Quarter references: "Q1 2026", "Q3 2025"
    - Absolute dates: "2025-01-01", "January 2025"
    - Ranges: "from X to Y", "between X and Y"
    """

    # Patterns for relative expressions
    RELATIVE_PATTERNS = [
        # "next N months/days/weeks/years"
        (r"next\s+(\d+)\s+(month|day|week|year)s?", "next"),
        # "last N months/days/weeks/years"
        (r"last\s+(\d+)\s+(month|day|week|year)s?", "last"),
        # "past N months/days/weeks/years"
        (r"past\s+(\d+)\s+(month|day|week|year)s?", "past"),
        # "in the next N months/days/weeks/years"
        (r"in\s+the\s+next\s+(\d+)\s+(month|day|week|year)s?", "next"),
        # "within N months/days/weeks/years"
        (r"within\s+(\d+)\s+(month|day|week|year)s?", "next"),
        # "N months/days/weeks/years ago"
        (r"(\d+)\s+(month|day|week|year)s?\s+ago", "ago"),
        # Hyphenated forms: "18-month", "12-month", "6-month"
        (r"(\d+)[-\s]?(month|day|week|year)s?(?:\s+(?:period|window|range))?", "next"),
        # Abbreviations: "6 mo", "1 yr", "2 wks"
        (r"(\d+)\s*(mo|mos|yr|yrs|wk|wks)\b", "next"),
    ]

    # Calendar-relative patterns (this quarter, next quarter, this year, year end)
    CALENDAR_PATTERNS = [
        (r"this\s+quarter", "this_quarter"),
        (r"next\s+quarter", "next_quarter"),
        (r"this\s+year", "this_year"),
        (r"next\s+year", "next_year"),
        (r"(?:by\s+)?year\s*end|end\s+of\s+(?:the\s+)?year", "year_end"),
        (r"(?:by\s+)?quarter\s*end|end\s+of\s+(?:the\s+)?quarter", "quarter_end"),
    ]

    # Pattern for quarter references
    QUARTER_PATTERN = r"Q([1-4])\s*(\d{4})"

    # Pattern for absolute dates
    ISO_DATE_PATTERN = r"(\d{4})-(\d{2})-(\d{2})"

    # Month names for parsing
    MONTH_NAMES = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sep": 9,
        "sept": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }

    def __init__(self, reference_date: Optional[date] = None):
        """
        Initialize the temporal parser.

        Args:
            reference_date: Reference date for relative expressions.
                           Defaults to today if not provided.
        """
        self._reference_date = reference_date

    @property
    def reference_date(self) -> date:
        """Get the reference date, defaulting to today."""
        return self._reference_date or date.today()

    def parse(self, expression: str, reference_date: Optional[date] = None) -> DateRange:
        """
        Parse a temporal expression into a DateRange.

        **Requirements: 3.1, 16.1, 16.2**

        Args:
            expression: Natural language temporal expression
            reference_date: Override reference date for this parse

        Returns:
            DateRange with start and end dates

        Raises:
            ValueError: If expression cannot be parsed
        """
        ref_date = reference_date or self.reference_date
        expr_lower = expression.lower().strip()

        # Try calendar-relative patterns first (this quarter, next quarter, etc.)
        calendar_result = self._parse_calendar_relative(expr_lower, ref_date)
        if calendar_result:
            return DateRange(
                start=calendar_result[0], end=calendar_result[1], original_expression=expression
            )

        # Try quarter pattern (Q1 2026, etc.)
        quarter_result = self._parse_quarter(expr_lower)
        if quarter_result:
            return DateRange(
                start=quarter_result[0], end=quarter_result[1], original_expression=expression
            )

        # Try relative patterns
        for pattern, direction in self.RELATIVE_PATTERNS:
            match = re.search(pattern, expr_lower)
            if match:
                result = self._parse_relative(match, direction, ref_date)
                if result:
                    return DateRange(start=result[0], end=result[1], original_expression=expression)

        # Try ISO date pattern
        iso_result = self._parse_iso_date(expr_lower)
        if iso_result:
            return DateRange(start=iso_result, end=iso_result, original_expression=expression)

        # Try month year pattern (e.g., "January 2025")
        month_year_result = self._parse_month_year(expr_lower)
        if month_year_result:
            return DateRange(
                start=month_year_result[0], end=month_year_result[1], original_expression=expression
            )

        # Try range patterns
        range_result = self._parse_range(expr_lower, ref_date)
        if range_result:
            return DateRange(
                start=range_result[0], end=range_result[1], original_expression=expression
            )

        raise ValueError(f"Unable to parse temporal expression: {expression}")

    def _parse_quarter(self, expression: str) -> Optional[Tuple[date, date]]:
        """
        Parse quarter reference (e.g., "Q1 2026", "Q3 2025").

        **Requirements: 16.2**

        Args:
            expression: Lowercase expression to parse

        Returns:
            Tuple of (start_date, end_date) or None
        """
        match = re.search(self.QUARTER_PATTERN, expression, re.IGNORECASE)
        if not match:
            return None

        quarter = int(match.group(1))
        year = int(match.group(2))

        # Calculate quarter start and end dates
        quarter_starts = {
            1: (1, 1),  # Jan 1
            2: (4, 1),  # Apr 1
            3: (7, 1),  # Jul 1
            4: (10, 1),  # Oct 1
        }

        quarter_ends = {
            1: (3, 31),  # Mar 31
            2: (6, 30),  # Jun 30
            3: (9, 30),  # Sep 30
            4: (12, 31),  # Dec 31
        }

        start_month, start_day = quarter_starts[quarter]
        end_month, end_day = quarter_ends[quarter]

        return (date(year, start_month, start_day), date(year, end_month, end_day))

    def _parse_calendar_relative(
        self, expression: str, ref_date: date
    ) -> Optional[Tuple[date, date]]:
        """
        Parse calendar-relative expressions (this quarter, next quarter, this year, year end).

        **Requirements: 16.1, 16.2**

        Args:
            expression: Lowercase expression to parse
            ref_date: Reference date

        Returns:
            Tuple of (start_date, end_date) or None
        """
        for pattern, cal_type in self.CALENDAR_PATTERNS:
            if re.search(pattern, expression):
                return self._calculate_calendar_range(cal_type, ref_date)
        return None

    def _calculate_calendar_range(
        self, cal_type: str, ref_date: date
    ) -> Tuple[date, date]:
        """
        Calculate date range for calendar-relative expressions.

        Args:
            cal_type: Type of calendar reference (this_quarter, next_quarter, etc.)
            ref_date: Reference date

        Returns:
            Tuple of (start_date, end_date)
        """
        current_quarter = (ref_date.month - 1) // 3 + 1
        current_year = ref_date.year

        if cal_type == "this_quarter":
            # From today to end of current quarter
            q_end = self._quarter_end(current_year, current_quarter)
            return (ref_date, q_end)

        elif cal_type == "next_quarter":
            # Full next quarter
            if current_quarter < 4:
                next_q = current_quarter + 1
                next_year = current_year
            else:
                next_q = 1
                next_year = current_year + 1
            return (
                self._quarter_start(next_year, next_q),
                self._quarter_end(next_year, next_q),
            )

        elif cal_type == "this_year":
            # From today to end of current year
            return (ref_date, date(current_year, 12, 31))

        elif cal_type == "next_year":
            # Full next year
            return (date(current_year + 1, 1, 1), date(current_year + 1, 12, 31))

        elif cal_type == "year_end":
            # From today to end of current year
            return (ref_date, date(current_year, 12, 31))

        elif cal_type == "quarter_end":
            # From today to end of current quarter
            q_end = self._quarter_end(current_year, current_quarter)
            return (ref_date, q_end)

        return (ref_date, ref_date)

    def _quarter_start(self, year: int, quarter: int) -> date:
        """Get the first day of a quarter."""
        quarter_starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
        month, day = quarter_starts[quarter]
        return date(year, month, day)

    def _quarter_end(self, year: int, quarter: int) -> date:
        """Get the last day of a quarter."""
        quarter_ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
        month, day = quarter_ends[quarter]
        return date(year, month, day)

    def _parse_relative(
        self, match: re.Match, direction: str, ref_date: date
    ) -> Optional[Tuple[date, date]]:
        """
        Parse relative temporal expression.

        **Requirements: 16.1**

        Args:
            match: Regex match object
            direction: "next", "last", "past", or "ago"
            ref_date: Reference date

        Returns:
            Tuple of (start_date, end_date) or None
        """
        try:
            count = int(match.group(1))
            unit = match.group(2).lower()
        except (IndexError, ValueError):
            return None

        # Normalize abbreviated units
        unit_map = {
            "mo": "month", "mos": "month", "month": "month", "months": "month",
            "yr": "year", "yrs": "year", "year": "year", "years": "year",
            "wk": "week", "wks": "week", "week": "week", "weeks": "week",
            "day": "day", "days": "day",
        }
        unit = unit_map.get(unit, unit)

        # Calculate delta based on unit
        if unit == "day":
            delta = timedelta(days=count)
        elif unit == "week":
            delta = timedelta(weeks=count)
        elif unit == "month":
            # Approximate months as 30 days for delta calculation
            # but use proper month arithmetic for accuracy
            return self._calculate_month_range(count, direction, ref_date)
        elif unit == "year":
            return self._calculate_year_range(count, direction, ref_date)
        else:
            return None

        if direction in ("next", "within"):
            # Future range: from today to today + delta
            return (ref_date, ref_date + delta)
        elif direction in ("last", "past"):
            # Past range: from today - delta to today
            return (ref_date - delta, ref_date)
        elif direction == "ago":
            # Point in time: approximate as a single day
            target_date = ref_date - delta
            return (target_date, target_date)

        return None

    def _calculate_month_range(
        self, count: int, direction: str, ref_date: date
    ) -> Tuple[date, date]:
        """
        Calculate date range for month-based expressions.

        Handles month arithmetic properly, including leap years.

        Args:
            count: Number of months
            direction: "next", "last", "past", or "ago"
            ref_date: Reference date

        Returns:
            Tuple of (start_date, end_date)
        """
        if direction in ("next", "within"):
            # Future: from ref_date to ref_date + N months
            end_date = self._add_months(ref_date, count)
            return (ref_date, end_date)
        elif direction in ("last", "past"):
            # Past: from ref_date - N months to ref_date
            start_date = self._add_months(ref_date, -count)
            return (start_date, ref_date)
        elif direction == "ago":
            # Point in time
            target_date = self._add_months(ref_date, -count)
            return (target_date, target_date)

        return (ref_date, ref_date)

    def _calculate_year_range(
        self, count: int, direction: str, ref_date: date
    ) -> Tuple[date, date]:
        """
        Calculate date range for year-based expressions.

        Args:
            count: Number of years
            direction: "next", "last", "past", or "ago"
            ref_date: Reference date

        Returns:
            Tuple of (start_date, end_date)
        """
        if direction in ("next", "within"):
            # Future: from ref_date to ref_date + N years
            end_date = self._add_years(ref_date, count)
            return (ref_date, end_date)
        elif direction in ("last", "past"):
            # Past: from ref_date - N years to ref_date
            start_date = self._add_years(ref_date, -count)
            return (start_date, ref_date)
        elif direction == "ago":
            # Point in time
            target_date = self._add_years(ref_date, -count)
            return (target_date, target_date)

        return (ref_date, ref_date)

    def _add_months(self, d: date, months: int) -> date:
        """
        Add months to a date, handling edge cases.

        Args:
            d: Base date
            months: Number of months to add (can be negative)

        Returns:
            New date with months added
        """
        # Calculate new month and year
        new_month = d.month + months
        new_year = d.year

        while new_month > 12:
            new_month -= 12
            new_year += 1

        while new_month < 1:
            new_month += 12
            new_year -= 1

        # Handle day overflow (e.g., Jan 31 + 1 month = Feb 28/29)
        max_day = self._days_in_month(new_year, new_month)
        new_day = min(d.day, max_day)

        return date(new_year, new_month, new_day)

    def _add_years(self, d: date, years: int) -> date:
        """
        Add years to a date, handling leap year edge cases.

        Args:
            d: Base date
            years: Number of years to add (can be negative)

        Returns:
            New date with years added
        """
        new_year = d.year + years

        # Handle Feb 29 in non-leap years
        if d.month == 2 and d.day == 29:
            if not self._is_leap_year(new_year):
                return date(new_year, 2, 28)

        return date(new_year, d.month, d.day)

    def _days_in_month(self, year: int, month: int) -> int:
        """Get the number of days in a month."""
        if month in (1, 3, 5, 7, 8, 10, 12):
            return 31
        elif month in (4, 6, 9, 11):
            return 30
        elif month == 2:
            return 29 if self._is_leap_year(year) else 28
        return 30

    def _is_leap_year(self, year: int) -> bool:
        """Check if a year is a leap year."""
        return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)

    def _parse_iso_date(self, expression: str) -> Optional[date]:
        """
        Parse ISO 8601 date format.

        Args:
            expression: Expression to parse

        Returns:
            Parsed date or None
        """
        match = re.search(self.ISO_DATE_PATTERN, expression)
        if not match:
            return None

        try:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return date(year, month, day)
        except ValueError:
            return None

    def _parse_month_year(self, expression: str) -> Optional[Tuple[date, date]]:
        """
        Parse month year format (e.g., "January 2025").

        Args:
            expression: Expression to parse

        Returns:
            Tuple of (first_day, last_day) of the month or None
        """
        for month_name, month_num in self.MONTH_NAMES.items():
            pattern = rf"{month_name}\s+(\d{{4}})"
            match = re.search(pattern, expression)
            if match:
                year = int(match.group(1))
                first_day = date(year, month_num, 1)
                last_day = date(year, month_num, self._days_in_month(year, month_num))
                return (first_day, last_day)

        return None

    def _parse_range(self, expression: str, ref_date: date) -> Optional[Tuple[date, date]]:
        """
        Parse range expressions (e.g., "from X to Y", "between X and Y").

        Args:
            expression: Expression to parse
            ref_date: Reference date for relative parts

        Returns:
            Tuple of (start_date, end_date) or None
        """
        # Pattern: "from X to Y" or "between X and Y"
        range_patterns = [
            r"from\s+(.+?)\s+to\s+(.+)",
            r"between\s+(.+?)\s+and\s+(.+)",
        ]

        for pattern in range_patterns:
            match = re.search(pattern, expression)
            if match:
                start_expr = match.group(1).strip()
                end_expr = match.group(2).strip()

                try:
                    # Try to parse each part
                    start_range = self.parse(start_expr, ref_date)
                    end_range = self.parse(end_expr, ref_date)
                    return (start_range.start, end_range.end)
                except ValueError:
                    # Try as ISO dates directly
                    start_date = self._parse_iso_date(start_expr)
                    end_date = self._parse_iso_date(end_expr)
                    if start_date and end_date:
                        return (start_date, end_date)

        return None


def parse_temporal_expression(expression: str, reference_date: Optional[date] = None) -> DateRange:
    """
    Convenience function to parse a temporal expression.

    **Requirements: 3.1, 16.1, 16.2**

    Args:
        expression: Natural language temporal expression
        reference_date: Reference date for relative expressions

    Returns:
        DateRange with start and end dates

    Raises:
        ValueError: If expression cannot be parsed
    """
    parser = TemporalParser(reference_date=reference_date)
    return parser.parse(expression)


def extract_temporal_expression(query: str) -> Optional[str]:
    """
    Extract temporal expression from a full query string.

    Looks for temporal phrases in the query and returns the first match.
    Used to extract "next 12 months" from "show me leases expiring in the next 12 months".

    Args:
        query: Full query string

    Returns:
        Extracted temporal phrase or None if no temporal expression found
    """
    query_lower = query.lower()

    # Patterns to extract temporal expressions (ordered by specificity)
    extraction_patterns = [
        # "in the next N months/days/weeks/years"
        r"in\s+the\s+next\s+\d+\s+(?:month|day|week|year)s?",
        # "next N months/days/weeks/years"
        r"next\s+\d+\s+(?:month|day|week|year)s?",
        # "last N months/days/weeks/years"
        r"last\s+\d+\s+(?:month|day|week|year)s?",
        # "past N months/days/weeks/years"
        r"past\s+\d+\s+(?:month|day|week|year)s?",
        # "within N months/days/weeks/years"
        r"within\s+\d+\s+(?:month|day|week|year)s?",
        # "N months/days/weeks/years ago"
        r"\d+\s+(?:month|day|week|year)s?\s+ago",
        # Hyphenated: "18-month", "12-month"
        r"\d+[-\s]?(?:month|day|week|year)s?(?:\s+(?:period|window|range))?",
        # Abbreviations: "6 mo", "1 yr"
        r"\d+\s*(?:mo|mos|yr|yrs|wk|wks)\b",
        # Calendar relative: "this quarter", "next quarter", "this year", "year end"
        r"this\s+quarter",
        r"next\s+quarter",
        r"this\s+year",
        r"next\s+year",
        r"(?:by\s+)?year\s*end|end\s+of\s+(?:the\s+)?year",
        r"(?:by\s+)?quarter\s*end|end\s+of\s+(?:the\s+)?quarter",
        # Quarter with year: "Q1 2026"
        r"Q[1-4]\s*\d{4}",
        # Month year: "January 2025"
        r"(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+\d{4}",
    ]

    for pattern in extraction_patterns:
        match = re.search(pattern, query_lower, re.IGNORECASE)
        if match:
            return match.group(0)

    return None


def get_lease_date_range(
    query: str,
    default_days: int = 180,
    reference_date: Optional[date] = None,
) -> Tuple[date, date]:
    """
    Parse a lease query and return a date range for filtering.

    Detects direction from query:
    - "expiring" / "expires" / "upcoming" → future range (today → end)
    - "expired" / "past" / "previous" → backward range (start → today)

    **Requirements: 3.1, 16.1**

    Args:
        query: Full query string (e.g., "leases expiring in the next 12 months")
        default_days: Default window if no temporal expression found (default: 180)
        reference_date: Override reference date (default: today)

    Returns:
        Tuple of (start_date, end_date) for filtering
    """
    ref_date = reference_date or date.today()
    query_lower = query.lower()

    # Detect direction from query
    past_keywords = ["expired", "past", "previous", "last", "ago", "ended", "terminated"]
    is_past = any(kw in query_lower for kw in past_keywords)

    # Try to extract and parse temporal expression
    temporal_expr = extract_temporal_expression(query)

    if temporal_expr:
        try:
            parser = TemporalParser(reference_date=ref_date)
            date_range = parser.parse(temporal_expr)

            if is_past:
                # For past queries, use parser's range as-is
                # (e.g., "last year" already returns past range)
                return (date_range.start, date_range.end)
            else:
                # For future queries, clamp start to today
                start = max(ref_date, date_range.start)
                return (start, date_range.end)

        except ValueError:
            LOGGER.debug(f"Could not parse temporal expression: {temporal_expr}")

    # Default fallback
    if is_past:
        start = ref_date - timedelta(days=default_days)
        return (start, ref_date)
    else:
        end = ref_date + timedelta(days=default_days)
        return (ref_date, end)
