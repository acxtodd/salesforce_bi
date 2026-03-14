"""
Unit Tests for Planner.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 1.1, 1.2, 1.3, 1.4, 15.1, 15.2, 15.3**

Tests:
- Plan generation
- Timeout handling
- Confidence fallback
- Serialization
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner import (
    Planner,
    StructuredPlan,
    Predicate,
    create_plan,
    is_fallback_plan,
    DEFAULT_TIMEOUT_MS,
    DEFAULT_CONFIDENCE_THRESHOLD,
)


# =============================================================================
# Mock Components
# =============================================================================


class MockVocabCache:
    """Mock VocabCache for testing."""

    def __init__(self, terms: Optional[Dict[str, Dict[str, Any]]] = None):
        self._terms = terms or {}

    def lookup(self, term: str, vocab_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self._terms.get(term.lower())

    def get_terms(self, vocab_type: str, object_name: str) -> List[Dict[str, Any]]:
        return []


class MockEntityLinker:
    """Mock EntityLinker for testing."""

    def __init__(self, matches: Optional[List[Any]] = None, confidence: float = 0.5):
        self._matches = matches or []
        self._confidence = confidence

    def link(self, query: str) -> Any:
        class MockLinkingResult:
            def __init__(self, matches, confidence):
                self.matches = matches
                self.confidence = confidence
                self.unmatched_terms = []
                self.ambiguous_terms = []

        return MockLinkingResult(self._matches, self._confidence)


class MockEntityMatch:
    """Mock EntityMatch for testing."""

    def __init__(
        self,
        term: str,
        object_name: str,
        field_name: Optional[str] = None,
        value: Optional[str] = None,
        confidence: float = 0.8,
    ):
        self.term = term
        self.object_name = object_name
        self.field_name = field_name
        self.value = value
        self.confidence = confidence


class MockValueNormalizer:
    """Mock ValueNormalizer for testing."""

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
    """Mock TraversalPlanner for testing."""

    def __init__(self, return_plan: bool = False):
        self._return_plan = return_plan

    def plan(self, start_object: str, target_object: str, **kwargs) -> Optional[Any]:
        if self._return_plan:
            class MockTraversalPlan:
                def __init__(self):
                    self.start_object = start_object
                    self.target_object = target_object
                    self.hops = []
                    self.max_depth = 2

                def to_dict(self):
                    return {
                        "start_object": self.start_object,
                        "target_object": self.target_object,
                        "hops": [],
                        "max_depth": 2,
                    }

            return MockTraversalPlan()
        return None


class MockEntityResolver:
    """Mock EntityResolver for testing."""

    def __init__(self, seed_ids: Optional[List[str]] = None):
        self._seed_ids = seed_ids or []

    def resolve(self, name: str, object_type: Optional[str] = None, **kwargs) -> Any:
        class MockResolutionResult:
            def __init__(self, seed_ids):
                self.matches = []
                self.seed_ids = seed_ids
                self.has_matches = bool(seed_ids)

        return MockResolutionResult(self._seed_ids)


class SlowEntityLinker:
    """EntityLinker that simulates slow processing."""

    def __init__(self, delay_seconds: float = 1.0):
        self._delay = delay_seconds

    def link(self, query: str) -> Any:
        time.sleep(self._delay)

        class MockLinkingResult:
            def __init__(self):
                self.matches = []
                self.confidence = 0.5
                self.unmatched_terms = []
                self.ambiguous_terms = []

        return MockLinkingResult()


# =============================================================================
# Unit Tests
# =============================================================================


class TestPlannerInitialization:
    """Tests for Planner initialization."""

    def test_planner_initializes_with_defaults(self):
        """Test that Planner initializes with default values."""
        planner = Planner()

        assert planner.timeout_ms == DEFAULT_TIMEOUT_MS
        assert planner.confidence_threshold == DEFAULT_CONFIDENCE_THRESHOLD

    def test_planner_accepts_custom_timeout(self):
        """Test that Planner accepts custom timeout."""
        planner = Planner(timeout_ms=1000)

        assert planner.timeout_ms == 1000

    def test_planner_accepts_custom_confidence_threshold(self):
        """Test that Planner accepts custom confidence threshold."""
        planner = Planner(confidence_threshold=0.7)

        assert planner.confidence_threshold == 0.7

    def test_planner_accepts_injected_components(self):
        """Test that Planner accepts injected components."""
        vocab_cache = MockVocabCache()
        entity_linker = MockEntityLinker()
        value_normalizer = MockValueNormalizer()
        traversal_planner = MockTraversalPlanner()
        entity_resolver = MockEntityResolver()

        planner = Planner(
            vocab_cache=vocab_cache,
            entity_linker=entity_linker,
            value_normalizer=value_normalizer,
            traversal_planner=traversal_planner,
            entity_resolver=entity_resolver,
        )

        assert planner.vocab_cache is vocab_cache
        assert planner._entity_linker is entity_linker
        assert planner._value_normalizer is value_normalizer
        assert planner._traversal_planner is traversal_planner
        assert planner._entity_resolver is entity_resolver


class TestPlanGeneration:
    """Tests for plan generation."""

    def test_plan_returns_structured_plan(self):
        """Test that plan() returns a StructuredPlan."""
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        plan = planner.plan("show me properties in Dallas")

        assert isinstance(plan, StructuredPlan)

    def test_plan_preserves_query(self):
        """Test that plan preserves the original query."""
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        query = "find Class A office buildings"
        plan = planner.plan(query)

        assert plan.query == query

    def test_plan_detects_property_object(self):
        """Test that plan detects Property object from keywords."""
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        plan = planner.plan("show me properties in Dallas")

        assert plan.target_object == "ascendix__Property__c"

    def test_plan_detects_availability_object(self):
        """Test that plan detects Availability object from keywords."""
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        plan = planner.plan("find available spaces")

        assert plan.target_object == "ascendix__Availability__c"

    def test_plan_detects_lease_object(self):
        """Test that plan detects Lease object from keywords."""
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        plan = planner.plan("leases expiring next month")

        assert plan.target_object == "ascendix__Lease__c"

    def test_plan_builds_predicates_from_matches(self):
        """Test that plan builds predicates from entity matches."""
        matches = [
            MockEntityMatch(
                term="Class A",
                object_name="ascendix__Property__c",
                field_name="PropertyClass__c",
                value="Class A",
            )
        ]

        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(matches=matches, confidence=0.8),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        plan = planner.plan("Class A properties")

        assert len(plan.predicates) >= 1

    def test_plan_records_planning_time(self):
        """Test that plan records planning time."""
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        plan = planner.plan("properties")

        assert plan.planning_time_ms >= 0


class TestTimeoutHandling:
    """Tests for timeout handling."""

    def test_timeout_returns_fallback_plan(self):
        """Test that timeout returns a fallback plan."""
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=SlowEntityLinker(delay_seconds=0.5),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
            timeout_ms=100,  # Very short timeout
        )

        plan = planner.plan("properties")

        assert plan.confidence == 0.0
        assert len(plan.predicates) == 0
        assert plan.is_fallback()

    def test_timeout_override_works(self):
        """Test that timeout can be overridden per-call."""
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=SlowEntityLinker(delay_seconds=0.3),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
            timeout_ms=1000,  # Long default timeout
        )

        # Override with short timeout
        plan = planner.plan("properties", timeout_ms=50)

        assert plan.is_fallback()


class TestConfidenceFallback:
    """Tests for confidence-based fallback."""

    def test_should_fallback_returns_true_for_low_confidence(self):
        """Test that should_fallback returns True for low confidence."""
        planner = Planner(confidence_threshold=0.5)

        plan = StructuredPlan(
            target_object="Property__c",
            predicates=[],
            confidence=0.3,
            query="test",
        )

        assert planner.should_fallback(plan) is True

    def test_should_fallback_returns_false_for_high_confidence(self):
        """Test that should_fallback returns False for high confidence."""
        planner = Planner(confidence_threshold=0.5)

        plan = StructuredPlan(
            target_object="Property__c",
            predicates=[],
            confidence=0.7,
            query="test",
        )

        assert planner.should_fallback(plan) is False

    def test_should_fallback_at_threshold(self):
        """Test should_fallback at exactly the threshold."""
        planner = Planner(confidence_threshold=0.5)

        plan = StructuredPlan(
            target_object="Property__c",
            predicates=[],
            confidence=0.5,
            query="test",
        )

        # At threshold, should not fallback
        assert planner.should_fallback(plan) is False


class TestEmptyQueryHandling:
    """Tests for empty query handling."""

    def test_empty_string_returns_fallback(self):
        """Test that empty string returns fallback plan."""
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        plan = planner.plan("")

        assert plan.is_fallback()
        assert plan.confidence == 0.0

    def test_whitespace_only_returns_fallback(self):
        """Test that whitespace-only query returns fallback plan."""
        planner = Planner(
            vocab_cache=MockVocabCache(),
            entity_linker=MockEntityLinker(),
            value_normalizer=MockValueNormalizer(),
            traversal_planner=MockTraversalPlanner(),
            entity_resolver=MockEntityResolver(),
        )

        plan = planner.plan("   ")

        assert plan.is_fallback()


class TestSerialization:
    """Tests for plan serialization."""

    def test_to_json_produces_valid_json(self):
        """Test that to_json produces valid JSON."""
        planner = Planner()

        plan = StructuredPlan(
            target_object="Property__c",
            predicates=[
                Predicate(field="City__c", operator="eq", value="Dallas"),
            ],
            confidence=0.8,
            query="properties in Dallas",
        )

        json_str = planner.to_json(plan)

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["target_object"] == "Property__c"
        assert parsed["confidence"] == 0.8

    def test_from_json_restores_plan(self):
        """Test that from_json restores the plan."""
        planner = Planner()

        original = StructuredPlan(
            target_object="Property__c",
            predicates=[
                Predicate(field="City__c", operator="eq", value="Dallas"),
            ],
            confidence=0.8,
            query="properties in Dallas",
        )

        json_str = planner.to_json(original)
        restored = planner.from_json(json_str)

        assert restored.target_object == original.target_object
        assert restored.confidence == original.confidence
        assert restored.query == original.query
        assert len(restored.predicates) == len(original.predicates)

    def test_round_trip_preserves_predicates(self):
        """Test that round-trip preserves predicates."""
        planner = Planner()

        original = StructuredPlan(
            target_object="Property__c",
            predicates=[
                Predicate(field="City__c", operator="eq", value="Dallas"),
                Predicate(field="State__c", operator="eq", value="TX"),
            ],
            confidence=0.8,
            query="test",
        )

        json_str = planner.to_json(original)
        restored = planner.from_json(json_str)

        assert len(restored.predicates) == 2
        assert restored.predicates[0].field == "City__c"
        assert restored.predicates[1].field == "State__c"

    def test_round_trip_preserves_seed_ids(self):
        """Test that round-trip preserves seed_ids."""
        planner = Planner()

        original = StructuredPlan(
            target_object="Property__c",
            predicates=[],
            seed_ids=["001ABC123", "001DEF456"],
            confidence=0.8,
            query="test",
        )

        json_str = planner.to_json(original)
        restored = planner.from_json(json_str)

        assert restored.seed_ids == original.seed_ids


class TestPredicateClass:
    """Tests for Predicate class."""

    def test_predicate_validates_operator(self):
        """Test that Predicate validates operator."""
        with pytest.raises(ValueError):
            Predicate(field="test", operator="invalid", value="test")

    def test_predicate_accepts_valid_operators(self):
        """Test that Predicate accepts valid operators."""
        valid_operators = ["eq", "gt", "lt", "gte", "lte", "in", "contains", "between"]

        for op in valid_operators:
            pred = Predicate(field="test", operator=op, value="test")
            assert pred.operator == op

    def test_predicate_to_dict(self):
        """Test Predicate.to_dict()."""
        pred = Predicate(
            field="City__c",
            operator="eq",
            value="Dallas",
            source_object="Property__c",
        )

        d = pred.to_dict()

        assert d["field"] == "City__c"
        assert d["operator"] == "eq"
        assert d["value"] == "Dallas"
        assert d["source_object"] == "Property__c"

    def test_predicate_from_dict(self):
        """Test Predicate.from_dict()."""
        d = {
            "field": "City__c",
            "operator": "eq",
            "value": "Dallas",
            "source_object": "Property__c",
        }

        pred = Predicate.from_dict(d)

        assert pred.field == "City__c"
        assert pred.operator == "eq"
        assert pred.value == "Dallas"
        assert pred.source_object == "Property__c"


class TestStructuredPlanClass:
    """Tests for StructuredPlan class."""

    def test_structured_plan_clamps_confidence(self):
        """Test that StructuredPlan clamps confidence to [0, 1]."""
        plan = StructuredPlan(
            target_object="Property__c",
            predicates=[],
            confidence=1.5,  # Over max
            query="test",
        )

        assert plan.confidence == 1.0

    def test_structured_plan_is_fallback(self):
        """Test StructuredPlan.is_fallback()."""
        fallback = StructuredPlan(
            target_object="",
            predicates=[],
            confidence=0.0,
            query="test",
        )

        assert fallback.is_fallback() is True

        non_fallback = StructuredPlan(
            target_object="Property__c",
            predicates=[Predicate(field="test", operator="eq", value="test")],
            confidence=0.5,
            query="test",
        )

        assert non_fallback.is_fallback() is False


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_create_plan_function(self):
        """Test create_plan convenience function."""
        plan = create_plan("properties in Dallas")

        assert isinstance(plan, StructuredPlan)

    def test_is_fallback_plan_function(self):
        """Test is_fallback_plan convenience function."""
        fallback = StructuredPlan(
            target_object="",
            predicates=[],
            confidence=0.0,
            query="test",
        )

        assert is_fallback_plan(fallback) is True
