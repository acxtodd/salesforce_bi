"""
Property-Based Tests for Planner.

**Feature: graph-aware-zero-config-retrieval**

Tests the following properties:
- Property 1: Planner Output Structure Completeness (Requirements 1.1)
- Property 2: Planner Timeout Fallback (Requirements 1.2, 8.1)
- Property 3: Low Confidence Fallback (Requirements 1.3)
- Property 15: Plan Serialization Round-Trip (Requirements 15.1, 15.2, 15.3)
"""

import os
import sys
import time
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, strategies as st, settings, assume

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner import (
    Planner,
    StructuredPlan,
    Predicate,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_CONFIDENCE_THRESHOLD,
)


# =============================================================================
# Mock Components for Testing
# =============================================================================


class MockVocabCache:
    """Mock VocabCache for property testing."""

    def __init__(self, terms: Optional[Dict[str, Dict[str, Any]]] = None):
        self._terms: Dict[str, List[Dict[str, Any]]] = terms or {}

    def lookup(self, term: str, vocab_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        entries = self._terms.get(term.lower(), [])
        if not entries:
            return None
        return entries[0] if entries else None

    def get_terms(self, vocab_type: str, object_name: str) -> List[Dict[str, Any]]:
        return []


class MockEntityLinker:
    """Mock EntityLinker for property testing."""

    def __init__(self, matches: Optional[List[Any]] = None, confidence: float = 0.5):
        self._matches = matches or []
        self._confidence = confidence

    def link(self, query: str) -> Any:
        """Return a mock linking result."""
        class MockLinkingResult:
            def __init__(self, matches, confidence):
                self.matches = matches
                self.confidence = confidence
                self.unmatched_terms = []
                self.ambiguous_terms = []

        return MockLinkingResult(self._matches, self._confidence)


class MockValueNormalizer:
    """Mock ValueNormalizer for property testing."""

    def normalize(self, value: str, field_type: str, **kwargs) -> Any:
        class MockNormalizedValue:
            def __init__(self, val):
                self.value = val
                self.operator = "eq"
                self.original = val

        return MockNormalizedValue(value)

    def normalize_auto(self, value: str, **kwargs) -> Any:
        return self.normalize(value, "string")


class MockTraversalPlanner:
    """Mock TraversalPlanner for property testing."""

    def plan(self, start_object: str, target_object: str, **kwargs) -> Optional[Any]:
        return None


class MockEntityResolver:
    """Mock EntityResolver for property testing."""

    def resolve(self, name: str, object_type: Optional[str] = None, **kwargs) -> Any:
        class MockResolutionResult:
            def __init__(self):
                self.matches = []
                self.seed_ids = []
                self.has_matches = False

        return MockResolutionResult()


class SlowEntityLinker:
    """EntityLinker that simulates slow processing for timeout tests."""

    def __init__(self, delay_seconds: float = 1.0):
        self._delay = delay_seconds

    def link(self, query: str) -> Any:
        """Simulate slow linking by sleeping."""
        time.sleep(self._delay)

        class MockLinkingResult:
            def __init__(self):
                self.matches = []
                self.confidence = 0.5
                self.unmatched_terms = []
                self.ambiguous_terms = []

        return MockLinkingResult()


# =============================================================================
# Hypothesis Strategies
# =============================================================================


# Valid Salesforce object names
VALID_OBJECTS = [
    "Account",
    "Contact",
    "ascendix__Property__c",
    "ascendix__Availability__c",
    "ascendix__Lease__c",
    "ascendix__Sale__c",
    "Opportunity",
    "Task",
    "Event",
]

# Valid operators
VALID_OPERATORS = ["eq", "gt", "lt", "gte", "lte", "in", "contains", "between"]


@st.composite
def predicate_strategy(draw):
    """Generate a valid Predicate."""
    field = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=3, max_size=30))
    operator = draw(st.sampled_from(VALID_OPERATORS))
    value = draw(st.one_of(
        st.text(min_size=1, max_size=50),
        st.integers(min_value=0, max_value=1000000),
        st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
        st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5),
    ))
    source_object = draw(st.one_of(st.none(), st.sampled_from(VALID_OBJECTS)))

    return Predicate(
        field=field,
        operator=operator,
        value=value,
        source_object=source_object,
    )


@st.composite
def structured_plan_strategy(draw):
    """Generate a valid StructuredPlan."""
    target_object = draw(st.sampled_from(VALID_OBJECTS))
    predicates = draw(st.lists(predicate_strategy(), min_size=0, max_size=5))
    seed_ids = draw(st.one_of(
        st.none(),
        st.lists(st.text(alphabet="0123456789abcdefABCDEF", min_size=15, max_size=18), min_size=1, max_size=5),
    ))
    confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    query = draw(st.text(min_size=1, max_size=200))
    planning_time_ms = draw(st.floats(min_value=0.0, max_value=1000.0, allow_nan=False))

    return StructuredPlan(
        target_object=target_object,
        predicates=predicates,
        traversal_plan=None,  # Simplified for testing
        seed_ids=seed_ids,
        confidence=confidence,
        query=query,
        planning_time_ms=planning_time_ms,
    )


@st.composite
def query_strategy(draw):
    """Generate a valid natural language query."""
    # Generate queries that look like CRE queries
    prefixes = ["show me", "find", "list", "get", "search for", ""]
    objects = ["properties", "availabilities", "leases", "contacts", "accounts", "deals"]
    locations = ["in Dallas", "in Miami", "downtown", "in PNW", ""]
    filters = ["Class A", "office", "industrial", "retail", "with vacancy", ""]

    prefix = draw(st.sampled_from(prefixes))
    obj = draw(st.sampled_from(objects))
    location = draw(st.sampled_from(locations))
    filter_text = draw(st.sampled_from(filters))

    parts = [p for p in [prefix, obj, location, filter_text] if p]
    query = " ".join(parts)

    # Ensure non-empty
    if not query.strip():
        query = "properties"

    return query


# =============================================================================
# Property Tests
# =============================================================================


class TestPlannerPropertyOutputStructure:
    """
    Property-based tests for Planner output structure.

    **Feature: graph-aware-zero-config-retrieval, Property 1: Planner Output Structure Completeness**
    **Validates: Requirements 1.1**
    """

    @pytest.mark.property
    @settings(max_examples=100)
    @given(query=query_strategy())
    def test_property_1_planner_output_structure_completeness(self, query):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 1: Planner Output Structure Completeness**
        **Validates: Requirements 1.1**

        Property: For any valid natural language query, the Planner SHALL emit a
        StructuredPlan containing all required fields (target_object, predicates,
        confidence) with valid types.
        """
        # Create planner with mock components
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        # Plan the query
        plan = planner.plan(query)

        # Verify required fields exist and have valid types
        assert isinstance(plan, StructuredPlan), "Plan should be a StructuredPlan instance"
        assert isinstance(plan.target_object, str), "target_object should be a string"
        assert isinstance(plan.predicates, list), "predicates should be a list"
        assert isinstance(plan.confidence, float), "confidence should be a float"

        # Verify confidence is in valid range
        assert 0.0 <= plan.confidence <= 1.0, f"confidence {plan.confidence} should be in [0, 1]"

        # Verify predicates are valid
        for pred in plan.predicates:
            assert isinstance(pred, Predicate), "Each predicate should be a Predicate instance"
            assert isinstance(pred.field, str), "predicate.field should be a string"
            assert isinstance(pred.operator, str), "predicate.operator should be a string"

        # Verify query is preserved
        assert plan.query == query, "Original query should be preserved in plan"

        # Verify planning_time_ms is non-negative
        assert plan.planning_time_ms >= 0, "planning_time_ms should be non-negative"


class TestPlannerPropertyTimeoutFallback:
    """
    Property-based tests for Planner timeout fallback.

    **Feature: graph-aware-zero-config-retrieval, Property 2: Planner Timeout Fallback**
    **Validates: Requirements 1.2, 8.1**
    """

    @pytest.mark.property
    @settings(max_examples=20, deadline=None)  # Fewer examples due to sleep, no deadline
    @given(query=query_strategy())
    def test_property_2_planner_timeout_fallback(self, query):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 2: Planner Timeout Fallback**
        **Validates: Requirements 1.2, 8.1**

        Property: For any query where planning exceeds the timeout threshold, the
        system SHALL return a fallback plan with confidence=0 and empty predicates,
        triggering vector-only search.
        """
        # Create planner with slow entity linker that will timeout
        # Use a very short timeout (50ms) and a linker that sleeps for 200ms
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=SlowEntityLinker(delay_seconds=0.2),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
            timeout_ms=50,  # Very short timeout
        )

        # Plan the query - should timeout
        plan = planner.plan(query)

        # Verify fallback plan characteristics
        assert plan.confidence == 0.0, "Fallback plan should have confidence=0"
        assert len(plan.predicates) == 0, "Fallback plan should have empty predicates"
        assert plan.is_fallback(), "Plan should be identified as fallback"


class TestPlannerPropertyLowConfidenceFallback:
    """
    Property-based tests for low confidence fallback.

    **Feature: graph-aware-zero-config-retrieval, Property 3: Low Confidence Fallback**
    **Validates: Requirements 1.3**
    """

    @pytest.mark.property
    @settings(max_examples=100)
    @given(
        query=query_strategy(),
        confidence=st.floats(min_value=0.0, max_value=0.49, allow_nan=False),
    )
    def test_property_3_low_confidence_fallback(self, query, confidence):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 3: Low Confidence Fallback**
        **Validates: Requirements 1.3**

        Property: For any plan with confidence below the configured threshold,
        the system SHALL trigger fallback to hybrid vector search.
        """
        # Create planner with entity linker that returns low confidence
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(confidence=confidence),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
            confidence_threshold=0.5,  # Default threshold
        )

        # Plan the query
        plan = planner.plan(query)

        # Verify should_fallback returns True for low confidence
        assert planner.should_fallback(plan), (
            f"should_fallback should return True for confidence {plan.confidence} "
            f"below threshold {planner.confidence_threshold}"
        )


class TestPlannerPropertySerializationRoundTrip:
    """
    Property-based tests for plan serialization round-trip.

    **Feature: graph-aware-zero-config-retrieval, Property 15: Plan Serialization Round-Trip**
    **Validates: Requirements 15.1, 15.2, 15.3**
    """

    @pytest.mark.property
    @settings(max_examples=100)
    @given(plan=structured_plan_strategy())
    def test_property_15_plan_serialization_round_trip(self, plan):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 15: Plan Serialization Round-Trip**
        **Validates: Requirements 15.1, 15.2, 15.3**

        Property: For any valid StructuredPlan, serializing to JSON and deserializing
        back SHALL produce an equivalent plan.
        """
        planner = Planner()

        # Serialize to JSON
        json_str = planner.to_json(plan)

        # Deserialize back
        restored_plan = planner.from_json(json_str)

        # Verify equivalence
        assert restored_plan.target_object == plan.target_object, "target_object should match"
        assert restored_plan.confidence == plan.confidence, "confidence should match"
        assert restored_plan.query == plan.query, "query should match"
        assert len(restored_plan.predicates) == len(plan.predicates), "predicate count should match"

        # Verify predicates match
        for orig, restored in zip(plan.predicates, restored_plan.predicates):
            assert restored.field == orig.field, "predicate field should match"
            assert restored.operator == orig.operator, "predicate operator should match"
            assert restored.source_object == orig.source_object, "predicate source_object should match"

        # Verify seed_ids match
        assert restored_plan.seed_ids == plan.seed_ids, "seed_ids should match"

    @pytest.mark.property
    @settings(max_examples=100)
    @given(predicate=predicate_strategy())
    def test_predicate_serialization_round_trip(self, predicate):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 15: Plan Serialization Round-Trip**
        **Validates: Requirements 15.1, 15.2, 15.3**

        Property: For any valid Predicate, converting to dict and back SHALL
        produce an equivalent Predicate.
        """
        # Convert to dict
        pred_dict = predicate.to_dict()

        # Convert back
        restored = Predicate.from_dict(pred_dict)

        # Verify equivalence
        assert restored.field == predicate.field, "field should match"
        assert restored.operator == predicate.operator, "operator should match"
        assert restored.source_object == predicate.source_object, "source_object should match"


class TestPlannerPropertyEmptyQuery:
    """
    Property-based tests for empty query handling.
    """

    @pytest.mark.property
    @settings(max_examples=50)
    @given(
        query=st.one_of(
            st.just(""),
            st.just(" "),
            st.just("  "),
            st.just("\t"),
            st.just("\n"),
            st.text(alphabet=" \t\n\r", min_size=0, max_size=10),
        )
    )
    def test_empty_query_returns_fallback(self, query):
        """
        Property: For any empty or whitespace-only query, the Planner SHALL
        return a fallback plan.
        """
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        plan = planner.plan(query)

        # Empty queries should return fallback
        assert plan.is_fallback(), "Empty query should return fallback plan"
        assert plan.confidence == 0.0, "Empty query should have zero confidence"
