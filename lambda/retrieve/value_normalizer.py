"""
Value Normalizer for Graph-Aware Zero-Config Retrieval.

Converts natural language values (dates, sizes, percentages, geographic references,
stage/status values) into structured filter values.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 3.1, 3.2, 3.3, 3.4, 3.5**
"""

from __future__ import annotations

import logging
import os
import re
from abc import ABC  # noqa: F401 - kept for potential future use
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Protocol, Tuple

from temporal_parser import TemporalParser

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NormalizedValue:
    """
    Represents a normalized value with comparison operator.

    **Requirements: 3.1**

    Attributes:
        value: The normalized value (can be number, string, date range, list, etc.)
        operator: Comparison operator (eq, gt, lt, gte, lte, in, contains, between)
        original: The original text that was normalized
        field_type: The type of field this value is for (optional)
    """

    value: Any
    operator: str
    original: str
    field_type: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate operator."""
        valid_operators = {"eq", "gt", "lt", "gte", "lte", "in", "contains", "between", "range"}
        if self.operator not in valid_operators:
            raise ValueError(f"Invalid operator: {self.operator}. Must be one of {valid_operators}")


@dataclass
class SizeRange:
    """
    Represents a size range with min and max values.

    **Requirements: 3.2**

    Attributes:
        min_value: Minimum size (None means no lower bound)
        max_value: Maximum size (None means no upper bound)
        unit: Unit of measurement (sf, sqft, square feet, etc.)
        original: Original expression
    """

    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: str = "sf"
    original: str = ""

    def __post_init__(self) -> None:
        """Validate that min <= max when both are present."""
        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ValueError(
                    f"Invalid SizeRange: min ({self.min_value}) must be <= max ({self.max_value})"
                )


@dataclass
class PercentageValue:
    """
    Represents a percentage value with comparison operator.

    **Requirements: 3.3**

    Attributes:
        value: The percentage value (0-100)
        operator: Comparison operator
        original: Original expression
    """

    value: float
    operator: str
    original: str = ""
    min_value: Optional[float] = None  # For range comparisons
    max_value: Optional[float] = None  # For range comparisons

    def __post_init__(self) -> None:
        """Validate percentage is in valid range."""
        if self.operator == "between":
            if self.min_value is not None and (self.min_value < 0 or self.min_value > 100):
                raise ValueError(f"Percentage min_value must be in range [0, 100], got {self.min_value}")
            if self.max_value is not None and (self.max_value < 0 or self.max_value > 100):
                raise ValueError(f"Percentage max_value must be in range [0, 100], got {self.max_value}")
        elif self.value < 0 or self.value > 100:
            raise ValueError(f"Percentage value must be in range [0, 100], got {self.value}")


@dataclass
class GeoExpansion:
    """
    Represents expanded geographic values.

    **Requirements: 3.5**

    Attributes:
        cities: List of matching city names
        states: List of matching state codes/names
        submarkets: List of matching submarket names
        original: Original expression
    """

    cities: List[str] = field(default_factory=list)
    states: List[str] = field(default_factory=list)
    submarkets: List[str] = field(default_factory=list)
    original: str = ""


# =============================================================================
# VocabCache Protocol (for dependency injection)
# =============================================================================


class VocabCacheProtocol(Protocol):
    """Protocol for VocabCache to allow dependency injection."""

    def lookup(self, term: str, vocab_type: str) -> Optional[Dict[str, Any]]:
        """Look up a term in the vocabulary cache."""
        ...

    def get_terms(self, vocab_type: str, object_name: str) -> List[Dict[str, Any]]:
        """Get all terms for a vocab type and object."""
        ...


# =============================================================================
# Size Parser
# =============================================================================


class SizeParser:
    """
    Parser for size range expressions.

    **Requirements: 3.2**

    Supports formats:
    - "20k-50k sf"
    - "over 100,000 square feet"
    - "under 5000 sqft"
    - "between 10,000 and 20,000 sf"
    - "at least 15000 sq ft"
    - "up to 25k sqft"
    """

    # Unit patterns (case insensitive)
    UNIT_PATTERNS = [
        r"square\s*feet",
        r"sq\.?\s*ft\.?",
        r"sqft",
        r"sf",
    ]

    # Multiplier suffixes
    MULTIPLIERS = {
        "k": 1_000,
        "m": 1_000_000,
    }

    def parse(self, expression: str) -> SizeRange:
        """
        Parse a size expression into a SizeRange.

        **Requirements: 3.2**

        Args:
            expression: Natural language size expression

        Returns:
            SizeRange with min/max values

        Raises:
            ValueError: If expression cannot be parsed
        """
        expr_lower = expression.lower().strip()
        original = expression

        # Extract unit (default to sf)
        unit = self._extract_unit(expr_lower)

        # Try different patterns
        result = (
            self._parse_range_pattern(expr_lower)
            or self._parse_between_pattern(expr_lower)
            or self._parse_over_pattern(expr_lower)
            or self._parse_under_pattern(expr_lower)
            or self._parse_at_least_pattern(expr_lower)
            or self._parse_up_to_pattern(expr_lower)
            or self._parse_exact_pattern(expr_lower)
        )

        if result is None:
            raise ValueError(f"Unable to parse size expression: {expression}")

        min_val, max_val = result
        return SizeRange(min_value=min_val, max_value=max_val, unit=unit, original=original)

    def _extract_unit(self, expression: str) -> str:
        """Extract the unit from the expression."""
        for pattern in self.UNIT_PATTERNS:
            if re.search(pattern, expression, re.IGNORECASE):
                return "sf"
        return "sf"  # Default

    def _parse_number(self, num_str: str) -> Optional[float]:
        """
        Parse a number string, handling commas and multiplier suffixes.

        Args:
            num_str: String representation of number (e.g., "20k", "100,000")

        Returns:
            Parsed float value or None
        """
        if not num_str:
            return None

        num_str = num_str.strip().lower()

        # Remove commas
        num_str = num_str.replace(",", "")

        # Check for multiplier suffix
        multiplier = 1
        for suffix, mult in self.MULTIPLIERS.items():
            if num_str.endswith(suffix):
                multiplier = mult
                num_str = num_str[:-1]
                break

        try:
            return float(num_str) * multiplier
        except ValueError:
            return None

    def _parse_range_pattern(self, expression: str) -> Optional[Tuple[float, float]]:
        """
        Parse range pattern like "20k-50k sf".

        Returns:
            Tuple of (min, max) or None
        """
        # Pattern: number-number (with optional units)
        pattern = r"(\d+(?:,\d{3})*(?:\.\d+)?[km]?)\s*[-–—to]+\s*(\d+(?:,\d{3})*(?:\.\d+)?[km]?)"
        match = re.search(pattern, expression)
        if match:
            min_val = self._parse_number(match.group(1))
            max_val = self._parse_number(match.group(2))
            if min_val is not None and max_val is not None:
                return (min_val, max_val)
        return None

    def _parse_between_pattern(self, expression: str) -> Optional[Tuple[float, float]]:
        """
        Parse between pattern like "between 10,000 and 20,000 sf".

        Returns:
            Tuple of (min, max) or None
        """
        pattern = r"between\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)\s+and\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)"
        match = re.search(pattern, expression)
        if match:
            min_val = self._parse_number(match.group(1))
            max_val = self._parse_number(match.group(2))
            if min_val is not None and max_val is not None:
                return (min_val, max_val)
        return None

    def _parse_over_pattern(self, expression: str) -> Optional[Tuple[float, None]]:
        """
        Parse over/more than pattern like "over 100,000 square feet".

        Returns:
            Tuple of (min, None) or None
        """
        patterns = [
            r"over\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r"more\s+than\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r"greater\s+than\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r">\s*(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r">=\s*(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, expression)
            if match:
                min_val = self._parse_number(match.group(1))
                if min_val is not None:
                    return (min_val, None)
        return None

    def _parse_under_pattern(self, expression: str) -> Optional[Tuple[None, float]]:
        """
        Parse under/less than pattern like "under 5000 sqft".

        Returns:
            Tuple of (None, max) or None
        """
        patterns = [
            r"under\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r"less\s+than\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r"below\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r"<\s*(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r"<=\s*(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, expression)
            if match:
                max_val = self._parse_number(match.group(1))
                if max_val is not None:
                    return (None, max_val)
        return None

    def _parse_at_least_pattern(self, expression: str) -> Optional[Tuple[float, None]]:
        """
        Parse at least pattern like "at least 15000 sq ft".

        Returns:
            Tuple of (min, None) or None
        """
        patterns = [
            r"at\s+least\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r"minimum\s+(?:of\s+)?(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, expression)
            if match:
                min_val = self._parse_number(match.group(1))
                if min_val is not None:
                    return (min_val, None)
        return None

    def _parse_up_to_pattern(self, expression: str) -> Optional[Tuple[None, float]]:
        """
        Parse up to pattern like "up to 25k sqft".

        Returns:
            Tuple of (None, max) or None
        """
        patterns = [
            r"up\s+to\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r"maximum\s+(?:of\s+)?(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
            r"no\s+more\s+than\s+(\d+(?:,\d{3})*(?:\.\d+)?[km]?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, expression)
            if match:
                max_val = self._parse_number(match.group(1))
                if max_val is not None:
                    return (None, max_val)
        return None

    def _parse_exact_pattern(self, expression: str) -> Optional[Tuple[float, float]]:
        """
        Parse exact size pattern like "5000 sf".

        Returns:
            Tuple of (value, value) for exact match or None
        """
        # Look for a standalone number with optional unit
        pattern = r"^(\d+(?:,\d{3})*(?:\.\d+)?[km]?)\s*(?:square\s*feet|sq\.?\s*ft\.?|sqft|sf)?$"
        match = re.search(pattern, expression.strip())
        if match:
            val = self._parse_number(match.group(1))
            if val is not None:
                return (val, val)
        return None


# =============================================================================
# Percentage Parser
# =============================================================================


class PercentageParser:
    """
    Parser for percentage expressions.

    **Requirements: 3.3**

    Supports formats:
    - "vacancy >25%"
    - "under 10%"
    - "between 5-15%"
    - "at least 20%"
    - "exactly 50%"
    """

    def parse(self, expression: str) -> PercentageValue:
        """
        Parse a percentage expression.

        **Requirements: 3.3**

        Args:
            expression: Natural language percentage expression

        Returns:
            PercentageValue with value and operator

        Raises:
            ValueError: If expression cannot be parsed or value out of range
        """
        expr_lower = expression.lower().strip()
        original = expression

        # Try different patterns
        result = (
            self._parse_range_pattern(expr_lower)
            or self._parse_between_pattern(expr_lower)
            or self._parse_comparison_pattern(expr_lower)
            or self._parse_exact_pattern(expr_lower)
        )

        if result is None:
            raise ValueError(f"Unable to parse percentage expression: {expression}")

        return PercentageValue(
            value=result[0],
            operator=result[1],
            original=original,
            min_value=result[2] if len(result) > 2 else None,
            max_value=result[3] if len(result) > 3 else None,
        )

    def _extract_percentage(self, num_str: str) -> Optional[float]:
        """Extract percentage value from string."""
        if not num_str:
            return None

        # Remove % sign and whitespace
        num_str = num_str.strip().replace("%", "").strip()

        try:
            value = float(num_str)
            return value
        except ValueError:
            return None

    def _parse_range_pattern(self, expression: str) -> Optional[Tuple[float, str, float, float]]:
        """
        Parse range pattern like "5-15%" or "5% - 15%".

        Returns:
            Tuple of (mid_value, "between", min, max) or None
        """
        pattern = r"(\d+(?:\.\d+)?)\s*%?\s*[-–—to]+\s*(\d+(?:\.\d+)?)\s*%?"
        match = re.search(pattern, expression)
        if match:
            min_val = self._extract_percentage(match.group(1))
            max_val = self._extract_percentage(match.group(2))
            if min_val is not None and max_val is not None:
                if 0 <= min_val <= 100 and 0 <= max_val <= 100:
                    mid_val = (min_val + max_val) / 2
                    return (mid_val, "between", min_val, max_val)
        return None

    def _parse_between_pattern(self, expression: str) -> Optional[Tuple[float, str, float, float]]:
        """
        Parse between pattern like "between 5% and 15%".

        Returns:
            Tuple of (mid_value, "between", min, max) or None
        """
        pattern = r"between\s+(\d+(?:\.\d+)?)\s*%?\s+and\s+(\d+(?:\.\d+)?)\s*%?"
        match = re.search(pattern, expression)
        if match:
            min_val = self._extract_percentage(match.group(1))
            max_val = self._extract_percentage(match.group(2))
            if min_val is not None and max_val is not None:
                if 0 <= min_val <= 100 and 0 <= max_val <= 100:
                    mid_val = (min_val + max_val) / 2
                    return (mid_val, "between", min_val, max_val)
        return None

    def _parse_comparison_pattern(self, expression: str) -> Optional[Tuple[float, str]]:
        """
        Parse comparison patterns like ">25%", "under 10%", "at least 20%".

        Returns:
            Tuple of (value, operator) or None
        """
        patterns = [
            # Greater than patterns
            (r">\s*(\d+(?:\.\d+)?)\s*%?", "gt"),
            (r">=\s*(\d+(?:\.\d+)?)\s*%?", "gte"),
            (r"over\s+(\d+(?:\.\d+)?)\s*%?", "gt"),
            (r"more\s+than\s+(\d+(?:\.\d+)?)\s*%?", "gt"),
            (r"greater\s+than\s+(\d+(?:\.\d+)?)\s*%?", "gt"),
            (r"above\s+(\d+(?:\.\d+)?)\s*%?", "gt"),
            (r"at\s+least\s+(\d+(?:\.\d+)?)\s*%?", "gte"),
            (r"minimum\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*%?", "gte"),
            # Less than patterns
            (r"<\s*(\d+(?:\.\d+)?)\s*%?", "lt"),
            (r"<=\s*(\d+(?:\.\d+)?)\s*%?", "lte"),
            (r"under\s+(\d+(?:\.\d+)?)\s*%?", "lt"),
            (r"less\s+than\s+(\d+(?:\.\d+)?)\s*%?", "lt"),
            (r"below\s+(\d+(?:\.\d+)?)\s*%?", "lt"),
            (r"up\s+to\s+(\d+(?:\.\d+)?)\s*%?", "lte"),
            (r"no\s+more\s+than\s+(\d+(?:\.\d+)?)\s*%?", "lte"),
            (r"maximum\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*%?", "lte"),
        ]

        for pattern, operator in patterns:
            match = re.search(pattern, expression)
            if match:
                value = self._extract_percentage(match.group(1))
                if value is not None and 0 <= value <= 100:
                    return (value, operator)
        return None

    def _parse_exact_pattern(self, expression: str) -> Optional[Tuple[float, str]]:
        """
        Parse exact percentage like "25%" or "exactly 50%".

        Returns:
            Tuple of (value, "eq") or None
        """
        patterns = [
            r"exactly\s+(\d+(?:\.\d+)?)\s*%?",
            r"^(\d+(?:\.\d+)?)\s*%$",
            r"(\d+(?:\.\d+)?)\s*%",  # Fallback: any number with %
        ]

        for pattern in patterns:
            match = re.search(pattern, expression)
            if match:
                value = self._extract_percentage(match.group(1))
                if value is not None and 0 <= value <= 100:
                    return (value, "eq")
        return None


# =============================================================================
# Geographic Expander
# =============================================================================


class GeoExpander:
    """
    Expands geographic aliases to city/state/submarket values.

    **Requirements: 3.5**

    Supports:
    - Region aliases (PNW, Bay Area, Tri-State, etc.)
    - Submarket aliases (downtown, midtown, etc.)
    - State abbreviations and full names
    """

    # Default region mappings (can be overridden by vocab cache)
    DEFAULT_REGION_MAPPINGS: Dict[str, Dict[str, List[str]]] = {
        "pnw": {
            "states": ["WA", "OR"],
            "cities": ["Seattle", "Portland", "Tacoma", "Spokane", "Eugene"],
        },
        "pacific northwest": {
            "states": ["WA", "OR"],
            "cities": ["Seattle", "Portland", "Tacoma", "Spokane", "Eugene"],
        },
        "bay area": {
            "states": ["CA"],
            "cities": ["San Francisco", "Oakland", "San Jose", "Palo Alto", "Fremont"],
            "submarkets": ["South Bay", "East Bay", "North Bay", "Peninsula"],
        },
        "sf bay area": {
            "states": ["CA"],
            "cities": ["San Francisco", "Oakland", "San Jose", "Palo Alto", "Fremont"],
            "submarkets": ["South Bay", "East Bay", "North Bay", "Peninsula"],
        },
        "tri-state": {
            "states": ["NY", "NJ", "CT"],
            "cities": ["New York", "Newark", "Jersey City", "Stamford"],
        },
        "tristate": {
            "states": ["NY", "NJ", "CT"],
            "cities": ["New York", "Newark", "Jersey City", "Stamford"],
        },
        "socal": {
            "states": ["CA"],
            "cities": ["Los Angeles", "San Diego", "Irvine", "Long Beach", "Anaheim"],
            "submarkets": ["LA Metro", "Orange County", "Inland Empire"],
        },
        "southern california": {
            "states": ["CA"],
            "cities": ["Los Angeles", "San Diego", "Irvine", "Long Beach", "Anaheim"],
            "submarkets": ["LA Metro", "Orange County", "Inland Empire"],
        },
        "dfw": {
            "states": ["TX"],
            "cities": ["Dallas", "Fort Worth", "Plano", "Irving", "Arlington"],
            "submarkets": ["Uptown", "Downtown Dallas", "Las Colinas"],
        },
        "dallas-fort worth": {
            "states": ["TX"],
            "cities": ["Dallas", "Fort Worth", "Plano", "Irving", "Arlington"],
            "submarkets": ["Uptown", "Downtown Dallas", "Las Colinas"],
        },
        "dmv": {
            "states": ["DC", "MD", "VA"],
            "cities": ["Washington", "Arlington", "Alexandria", "Bethesda", "Silver Spring"],
        },
        "dc metro": {
            "states": ["DC", "MD", "VA"],
            "cities": ["Washington", "Arlington", "Alexandria", "Bethesda", "Silver Spring"],
        },
        "south florida": {
            "states": ["FL"],
            "cities": ["Miami", "Fort Lauderdale", "West Palm Beach", "Boca Raton"],
            "submarkets": ["Brickell", "Downtown Miami", "Coral Gables"],
        },
        "chicagoland": {
            "states": ["IL"],
            "cities": ["Chicago", "Naperville", "Evanston", "Oak Brook", "Schaumburg"],
            "submarkets": ["Loop", "River North", "West Loop"],
        },
    }

    # Submarket aliases
    DEFAULT_SUBMARKET_ALIASES: Dict[str, List[str]] = {
        "downtown": ["Downtown", "CBD", "Central Business District"],
        "midtown": ["Midtown"],
        "uptown": ["Uptown"],
        "cbd": ["CBD", "Central Business District", "Downtown"],
        "suburban": ["Suburban", "Suburbs"],
    }

    def __init__(self, vocab_cache: Optional[VocabCacheProtocol] = None):
        """
        Initialize the GeoExpander.

        Args:
            vocab_cache: Optional vocab cache for custom mappings
        """
        self.vocab_cache = vocab_cache
        self._region_mappings = dict(self.DEFAULT_REGION_MAPPINGS)
        self._submarket_aliases = dict(self.DEFAULT_SUBMARKET_ALIASES)

    def expand(self, expression: str) -> GeoExpansion:
        """
        Expand a geographic expression to cities/states/submarkets.

        **Requirements: 3.5**

        Args:
            expression: Geographic expression (e.g., "PNW", "downtown")

        Returns:
            GeoExpansion with matching values
        """
        expr_lower = expression.lower().strip()
        original = expression

        # Check region mappings
        if expr_lower in self._region_mappings:
            mapping = self._region_mappings[expr_lower]
            return GeoExpansion(
                cities=mapping.get("cities", []),
                states=mapping.get("states", []),
                submarkets=mapping.get("submarkets", []),
                original=original,
            )

        # Check submarket aliases
        if expr_lower in self._submarket_aliases:
            return GeoExpansion(
                submarkets=self._submarket_aliases[expr_lower],
                original=original,
            )

        # Try vocab cache if available
        if self.vocab_cache:
            cached = self._lookup_from_cache(expr_lower)
            if cached:
                return cached

        # Return as-is (might be a specific city/state)
        return GeoExpansion(
            cities=[expression] if self._looks_like_city(expression) else [],
            states=[expression] if self._looks_like_state(expression) else [],
            original=original,
        )

    def _lookup_from_cache(self, term: str) -> Optional[GeoExpansion]:
        """Look up geographic term in vocab cache."""
        if not self.vocab_cache:
            return None

        result = self.vocab_cache.lookup(term, "geography")
        if result:
            return GeoExpansion(
                cities=result.get("cities", []),
                states=result.get("states", []),
                submarkets=result.get("submarkets", []),
                original=term,
            )
        return None

    def _looks_like_city(self, value: str) -> bool:
        """Check if value looks like a city name."""
        # Simple heuristic: starts with capital, no numbers
        return bool(value) and value[0].isupper() and not any(c.isdigit() for c in value)

    def _looks_like_state(self, value: str) -> bool:
        """Check if value looks like a state code."""
        # Two uppercase letters
        return len(value) == 2 and value.isupper() and value.isalpha()

    def add_region_mapping(self, alias: str, mapping: Dict[str, List[str]]) -> None:
        """Add a custom region mapping."""
        self._region_mappings[alias.lower()] = mapping

    def add_submarket_alias(self, alias: str, values: List[str]) -> None:
        """Add a custom submarket alias."""
        self._submarket_aliases[alias.lower()] = values


# =============================================================================
# Stage/Status Mapper
# =============================================================================


class StageStatusMapper:
    """
    Maps natural language stage/status references to picklist values.

    **Requirements: 3.4**

    Supports:
    - Exact matching
    - Fuzzy matching for close matches
    - Common stage aliases
    """

    # Default stage aliases (common CRE stages)
    DEFAULT_STAGE_ALIASES: Dict[str, List[str]] = {
        # Sales/Deal stages
        "prospecting": ["Prospecting", "Prospect", "Lead"],
        "prospect": ["Prospecting", "Prospect", "Lead"],
        "qualification": ["Qualification", "Qualifying", "Qualified"],
        "qualifying": ["Qualification", "Qualifying", "Qualified"],
        "negotiation": ["Negotiation", "Negotiating", "In Negotiation"],
        "negotiating": ["Negotiation", "Negotiating", "In Negotiation"],
        "due diligence": ["Due Diligence", "DD", "Under Review"],
        "dd": ["Due Diligence", "DD", "Under Review"],
        "under contract": ["Under Contract", "Contracted", "In Contract"],
        "contracted": ["Under Contract", "Contracted", "In Contract"],
        "closed": ["Closed", "Closed Won", "Completed"],
        "closed won": ["Closed Won", "Closed", "Won"],
        "closed lost": ["Closed Lost", "Lost"],
        "lost": ["Closed Lost", "Lost"],
        "on hold": ["On Hold", "Hold", "Paused"],
        "hold": ["On Hold", "Hold", "Paused"],
        # Lease stages
        "active": ["Active", "Current", "In Effect"],
        "current": ["Active", "Current", "In Effect"],
        "expired": ["Expired", "Past", "Ended"],
        "expiring": ["Expiring", "Expiring Soon", "Near Expiration"],
        "pending": ["Pending", "Awaiting", "In Progress"],
        # Property stages
        "available": ["Available", "For Lease", "For Sale", "On Market"],
        "for lease": ["For Lease", "Available for Lease"],
        "for sale": ["For Sale", "Available for Sale"],
        "leased": ["Leased", "Occupied", "Under Lease"],
        "occupied": ["Occupied", "Leased", "In Use"],
        "vacant": ["Vacant", "Empty", "Unoccupied"],
        "under construction": ["Under Construction", "In Development", "Building"],
        "development": ["Under Construction", "In Development", "Development"],
    }

    # Fuzzy match threshold (0-1, higher = stricter)
    FUZZY_THRESHOLD = 0.7

    def __init__(self, vocab_cache: Optional[VocabCacheProtocol] = None):
        """
        Initialize the StageStatusMapper.

        Args:
            vocab_cache: Optional vocab cache for valid picklist values
        """
        self.vocab_cache = vocab_cache
        self._stage_aliases = dict(self.DEFAULT_STAGE_ALIASES)
        self._valid_values: Dict[str, List[str]] = {}  # object_name -> valid values

    def map(
        self, expression: str, object_name: Optional[str] = None, field_name: Optional[str] = None
    ) -> List[str]:
        """
        Map a natural language stage/status to picklist values.

        **Requirements: 3.4**

        Args:
            expression: Natural language stage/status expression
            object_name: Optional Salesforce object name for context
            field_name: Optional field name for context

        Returns:
            List of matching picklist values (may be empty if no match)
        """
        expr_lower = expression.lower().strip()

        # Try exact alias match first
        if expr_lower in self._stage_aliases:
            return self._stage_aliases[expr_lower]

        # Try vocab cache for valid values
        if self.vocab_cache and object_name and field_name:
            valid_values = self._get_valid_values(object_name, field_name)
            if valid_values:
                # Try exact match against valid values
                for value in valid_values:
                    if value.lower() == expr_lower:
                        return [value]

                # Try fuzzy match
                fuzzy_matches = self._fuzzy_match(expression, valid_values)
                if fuzzy_matches:
                    return fuzzy_matches

        # Try fuzzy match against all known aliases
        all_values = set()
        for values in self._stage_aliases.values():
            all_values.update(values)

        fuzzy_matches = self._fuzzy_match(expression, list(all_values))
        if fuzzy_matches:
            return fuzzy_matches

        # Return original as fallback
        return [expression]

    def _get_valid_values(self, object_name: str, field_name: str) -> List[str]:
        """Get valid picklist values from vocab cache."""
        cache_key = f"{object_name}.{field_name}"

        if cache_key not in self._valid_values:
            if self.vocab_cache:
                terms = self.vocab_cache.get_terms("picklist", f"{object_name}.{field_name}")
                self._valid_values[cache_key] = [t.get("canonical_value", "") for t in terms if t]
            else:
                self._valid_values[cache_key] = []

        return self._valid_values[cache_key]

    def _fuzzy_match(self, query: str, candidates: List[str]) -> List[str]:
        """
        Find fuzzy matches for a query against candidates.

        Args:
            query: Query string
            candidates: List of candidate strings

        Returns:
            List of matching candidates above threshold
        """
        matches = []
        query_lower = query.lower()

        for candidate in candidates:
            ratio = SequenceMatcher(None, query_lower, candidate.lower()).ratio()
            if ratio >= self.FUZZY_THRESHOLD:
                matches.append((candidate, ratio))

        # Sort by match ratio (descending) and return just the values
        matches.sort(key=lambda x: x[1], reverse=True)
        return [m[0] for m in matches]

    def add_stage_alias(self, alias: str, values: List[str]) -> None:
        """Add a custom stage alias."""
        self._stage_aliases[alias.lower()] = values


# =============================================================================
# Main Value Normalizer
# =============================================================================


class ValueNormalizer:
    """
    Main value normalizer that coordinates all normalization components.

    **Requirements: 3.1, 3.2, 3.3, 3.4, 3.5**

    Integrates:
    - TemporalParser for date expressions
    - SizeParser for size ranges
    - PercentageParser for percentage values
    - GeoExpander for geographic references
    - StageStatusMapper for stage/status values
    """

    def __init__(self, vocab_cache: Optional[VocabCacheProtocol] = None):
        """
        Initialize the ValueNormalizer.

        Args:
            vocab_cache: Optional vocab cache for lookups
        """
        self.vocab_cache = vocab_cache
        self.temporal_parser = TemporalParser()
        self.size_parser = SizeParser()
        self.percentage_parser = PercentageParser()
        self.geo_expander = GeoExpander(vocab_cache)
        self.stage_mapper = StageStatusMapper(vocab_cache)

    def normalize(
        self,
        value: str,
        field_type: str,
        object_name: Optional[str] = None,
        field_name: Optional[str] = None,
        reference_date: Optional[date] = None,
    ) -> NormalizedValue:
        """
        Normalize a value based on field type.

        **Requirements: 3.1**

        Args:
            value: The value to normalize
            field_type: Type of field (date, datetime, number, percent, picklist,
                       reference, string, geography, size)
            object_name: Optional Salesforce object name for context
            field_name: Optional field name for context
            reference_date: Optional reference date for temporal expressions

        Returns:
            NormalizedValue with normalized value and operator

        Raises:
            ValueError: If value cannot be normalized for the given field type
        """
        value_str = str(value).strip()

        if field_type in ("date", "datetime"):
            return self._normalize_temporal(value_str, reference_date)
        elif field_type == "size":
            return self._normalize_size(value_str)
        elif field_type in ("percent", "percentage"):
            return self._normalize_percentage(value_str)
        elif field_type == "geography":
            return self._normalize_geography(value_str)
        elif field_type in ("picklist", "stage", "status"):
            return self._normalize_stage(value_str, object_name, field_name)
        elif field_type == "number":
            return self._normalize_number(value_str)
        else:
            # Default: return as-is with eq operator
            return NormalizedValue(value=value_str, operator="eq", original=value_str, field_type=field_type)

    def _normalize_temporal(
        self, value: str, reference_date: Optional[date] = None
    ) -> NormalizedValue:
        """Normalize temporal expression."""
        try:
            date_range = self.temporal_parser.parse(value, reference_date)
            return NormalizedValue(
                value=date_range,
                operator="between" if date_range.start != date_range.end else "eq",
                original=value,
                field_type="date",
            )
        except ValueError as e:
            LOGGER.warning(f"Failed to parse temporal expression '{value}': {e}")
            raise

    def _normalize_size(self, value: str) -> NormalizedValue:
        """Normalize size expression."""
        try:
            size_range = self.size_parser.parse(value)

            # Determine operator based on min/max
            if size_range.min_value is not None and size_range.max_value is not None:
                if size_range.min_value == size_range.max_value:
                    operator = "eq"
                    norm_value = size_range.min_value
                else:
                    operator = "between"
                    norm_value = size_range
            elif size_range.min_value is not None:
                operator = "gte"
                norm_value = size_range.min_value
            elif size_range.max_value is not None:
                operator = "lte"
                norm_value = size_range.max_value
            else:
                raise ValueError("Invalid size range: no min or max value")

            return NormalizedValue(
                value=norm_value,
                operator=operator,
                original=value,
                field_type="size",
            )
        except ValueError as e:
            LOGGER.warning(f"Failed to parse size expression '{value}': {e}")
            raise

    def _normalize_percentage(self, value: str) -> NormalizedValue:
        """Normalize percentage expression."""
        try:
            pct_value = self.percentage_parser.parse(value)

            if pct_value.operator == "between":
                norm_value = pct_value
            else:
                norm_value = pct_value.value

            return NormalizedValue(
                value=norm_value,
                operator=pct_value.operator,
                original=value,
                field_type="percent",
            )
        except ValueError as e:
            LOGGER.warning(f"Failed to parse percentage expression '{value}': {e}")
            raise

    def _normalize_geography(self, value: str) -> NormalizedValue:
        """Normalize geographic expression."""
        geo_expansion = self.geo_expander.expand(value)

        # Build list of all expanded values
        all_values = []
        all_values.extend(geo_expansion.cities)
        all_values.extend(geo_expansion.states)
        all_values.extend(geo_expansion.submarkets)

        if not all_values:
            # No expansion found, return original
            return NormalizedValue(
                value=value,
                operator="eq",
                original=value,
                field_type="geography",
            )

        return NormalizedValue(
            value=geo_expansion,
            operator="in" if len(all_values) > 1 else "eq",
            original=value,
            field_type="geography",
        )

    def _normalize_stage(
        self, value: str, object_name: Optional[str], field_name: Optional[str]
    ) -> NormalizedValue:
        """Normalize stage/status expression."""
        mapped_values = self.stage_mapper.map(value, object_name, field_name)

        if len(mapped_values) == 1:
            return NormalizedValue(
                value=mapped_values[0],
                operator="eq",
                original=value,
                field_type="picklist",
            )
        elif len(mapped_values) > 1:
            return NormalizedValue(
                value=mapped_values,
                operator="in",
                original=value,
                field_type="picklist",
            )
        else:
            return NormalizedValue(
                value=value,
                operator="eq",
                original=value,
                field_type="picklist",
            )

    def _normalize_number(self, value: str) -> NormalizedValue:
        """Normalize numeric expression."""
        # Try to parse comparison operators
        patterns = [
            (r">\s*(\d+(?:\.\d+)?)", "gt"),
            (r">=\s*(\d+(?:\.\d+)?)", "gte"),
            (r"<\s*(\d+(?:\.\d+)?)", "lt"),
            (r"<=\s*(\d+(?:\.\d+)?)", "lte"),
            (r"(\d+(?:\.\d+)?)\s*[-–—to]+\s*(\d+(?:\.\d+)?)", "between"),
        ]

        for pattern, operator in patterns:
            match = re.search(pattern, value)
            if match:
                if operator == "between":
                    min_val = float(match.group(1))
                    max_val = float(match.group(2))
                    return NormalizedValue(
                        value=(min_val, max_val),
                        operator=operator,
                        original=value,
                        field_type="number",
                    )
                else:
                    num_val = float(match.group(1))
                    return NormalizedValue(
                        value=num_val,
                        operator=operator,
                        original=value,
                        field_type="number",
                    )

        # Try plain number
        try:
            num_val = float(value.replace(",", ""))
            return NormalizedValue(
                value=num_val,
                operator="eq",
                original=value,
                field_type="number",
            )
        except ValueError:
            return NormalizedValue(
                value=value,
                operator="eq",
                original=value,
                field_type="string",
            )

    def normalize_auto(
        self,
        value: str,
        object_name: Optional[str] = None,
        field_name: Optional[str] = None,
        reference_date: Optional[date] = None,
    ) -> NormalizedValue:
        """
        Auto-detect value type and normalize accordingly.

        Tries each normalizer in order of specificity.

        Args:
            value: The value to normalize
            object_name: Optional Salesforce object name
            field_name: Optional field name
            reference_date: Optional reference date

        Returns:
            NormalizedValue with best-effort normalization
        """
        value_str = str(value).strip()

        # Try temporal first (most specific patterns)
        try:
            return self._normalize_temporal(value_str, reference_date)
        except ValueError:
            pass

        # Try percentage (has % sign)
        if "%" in value_str:
            try:
                return self._normalize_percentage(value_str)
            except ValueError:
                pass

        # Try size (has sf/sqft/square feet)
        if any(unit in value_str.lower() for unit in ["sf", "sqft", "square"]):
            try:
                return self._normalize_size(value_str)
            except ValueError:
                pass

        # Try geography (known regions)
        geo_result = self.geo_expander.expand(value_str)
        if geo_result.cities or geo_result.states or geo_result.submarkets:
            return self._normalize_geography(value_str)

        # Try stage/status
        stage_result = self.stage_mapper.map(value_str, object_name, field_name)
        if stage_result and stage_result[0].lower() != value_str.lower():
            return self._normalize_stage(value_str, object_name, field_name)

        # Try number
        try:
            return self._normalize_number(value_str)
        except ValueError:
            pass

        # Default: return as string
        return NormalizedValue(
            value=value_str,
            operator="eq",
            original=value_str,
            field_type="string",
        )


# =============================================================================
# Convenience Functions
# =============================================================================


def normalize_value(
    value: str,
    field_type: str,
    vocab_cache: Optional[VocabCacheProtocol] = None,
    reference_date: Optional[date] = None,
) -> NormalizedValue:
    """
    Convenience function to normalize a value.

    **Requirements: 3.1**

    Args:
        value: The value to normalize
        field_type: Type of field
        vocab_cache: Optional vocab cache
        reference_date: Optional reference date

    Returns:
        NormalizedValue
    """
    normalizer = ValueNormalizer(vocab_cache)
    return normalizer.normalize(value, field_type, reference_date=reference_date)


def parse_size_range(expression: str) -> SizeRange:
    """
    Convenience function to parse a size expression.

    **Requirements: 3.2**

    Args:
        expression: Size expression

    Returns:
        SizeRange
    """
    parser = SizeParser()
    return parser.parse(expression)


def parse_percentage(expression: str) -> PercentageValue:
    """
    Convenience function to parse a percentage expression.

    **Requirements: 3.3**

    Args:
        expression: Percentage expression

    Returns:
        PercentageValue
    """
    parser = PercentageParser()
    return parser.parse(expression)


def expand_geography(expression: str, vocab_cache: Optional[VocabCacheProtocol] = None) -> GeoExpansion:
    """
    Convenience function to expand a geographic expression.

    **Requirements: 3.5**

    Args:
        expression: Geographic expression
        vocab_cache: Optional vocab cache

    Returns:
        GeoExpansion
    """
    expander = GeoExpander(vocab_cache)
    return expander.expand(expression)


def map_stage(
    expression: str,
    object_name: Optional[str] = None,
    field_name: Optional[str] = None,
    vocab_cache: Optional[VocabCacheProtocol] = None,
) -> List[str]:
    """
    Convenience function to map a stage/status expression.

    **Requirements: 3.4**

    Args:
        expression: Stage/status expression
        object_name: Optional object name
        field_name: Optional field name
        vocab_cache: Optional vocab cache

    Returns:
        List of matching picklist values
    """
    mapper = StageStatusMapper(vocab_cache)
    return mapper.map(expression, object_name, field_name)
