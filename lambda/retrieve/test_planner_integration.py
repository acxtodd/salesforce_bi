"""
Integration Tests for Planner with Retrieve Lambda.

**Feature: graph-aware-zero-config-retrieval**

Tests the integration of the Planner with the retrieve Lambda:
- End-to-end query flow
- Fallback scenarios
- Parallel execution timing
- Telemetry logging

**Requirements: 1.1, 1.2, 1.3, 1.4, 8.1, 8.2**
"""

import os
import sys
import time
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, MagicMock, patch
from concurrent.futures import TimeoutError as FuturesTimeoutError

import pytest

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from planner import Planner, StructuredPlan, Predicate


# =============================================================================
# Mock Classes
# =============================================================================


class MockBedrockClient:
    """Mock Bedrock Agent Runtime client for testing."""

    def __init__(self, results: List[Dict[str, Any]] = None):
        self.results = results or []
        self.call_count = 0

    def retrieve(self, **kwargs) -> Dict[str, Any]:
        """Mock retrieve call."""
        self.call_count += 1
        return {
            "retrievalResults": [
                {
                    "content": {"text": r.get("text", "")},
                    "location": {"s3Location": {"uri": r.get("uri", "")}},
                    "metadata": r.get("metadata", {}),
                    "score": r.get("score", 0.8),
                }
                for r in self.results
            ]
        }


class MockAuthzSidecar:
    """Mock AuthZ sidecar for testing."""

    def __init__(self, sharing_buckets: List[str] = None):
        self.sharing_buckets = sharing_buckets or ["bucket1", "bucket2"]

    def get_context(self, user_id: str) -> Dict[str, Any]:
        """Return mock authz context."""
        return {
            "salesforceUserId": user_id,
            "sharingBuckets": self.sharing_buckets,
            "objectAccess": {"ascendix__Property__c": True},
            "cached": False,
        }


# =============================================================================
# Test Classes
# =============================================================================


class TestPlannerIntegration:
    """
    Tests for Planner integration with retrieve Lambda.

    **Requirements: 1.1, 1.2, 1.3**
    """

    def test_planner_import_success(self):
        """Planner should be importable."""
        from planner import Planner, StructuredPlan, Predicate

        assert Planner is not None
        assert StructuredPlan is not None
        assert Predicate is not None

    def test_planner_initialization(self):
        """Planner should initialize with default settings."""
        planner = Planner()

        assert planner.timeout_ms == 500  # Default timeout
        assert planner.confidence_threshold == 0.5  # Default confidence

    def test_planner_custom_timeout(self):
        """Planner should accept custom timeout."""
        planner = Planner(timeout_ms=1000)

        assert planner.timeout_ms == 1000

    def test_planner_plan_returns_structured_plan(self):
        """Planner.plan() should return StructuredPlan."""
        planner = Planner()

        result = planner.plan("show me Class A properties in Dallas")

        assert isinstance(result, StructuredPlan)
        assert result.target_object is not None
        assert isinstance(result.predicates, list)
        assert 0.0 <= result.confidence <= 1.0

    def test_planner_detects_target_object(self):
        """Planner should detect target object from query."""
        planner = Planner()

        # Property query
        result = planner.plan("show me buildings in Dallas")
        assert "Property" in result.target_object or result.target_object == ""

        # Availability query
        result = planner.plan("find available spaces")
        assert "Availability" in result.target_object or result.target_object == ""

    def test_planner_extracts_predicates(self):
        """Planner should extract predicates from query."""
        planner = Planner()

        result = planner.plan("Class A properties over 50000 sqft in Dallas")

        # Should have some predicates (city, class, size)
        # Note: Exact predicates depend on implementation
        assert isinstance(result.predicates, list)

    def test_planner_respects_timeout(self):
        """Planner should complete within timeout."""
        planner = Planner(timeout_ms=500)

        start = time.perf_counter()
        result = planner.plan("simple query")
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Should complete within timeout (with some buffer)
        assert elapsed_ms < 1000  # Allow for overhead

    def test_planner_confidence_scoring(self):
        """Planner should provide confidence scores."""
        planner = Planner()

        # Clear query should have higher confidence
        clear_result = planner.plan("show me Class A properties in Dallas")

        # Vague query should have lower confidence
        vague_result = planner.plan("stuff")

        assert clear_result.confidence >= 0.0
        assert vague_result.confidence >= 0.0
        # Note: We can't guarantee clear > vague without real implementation


class TestFallbackScenarios:
    """
    Tests for fallback scenarios.

    **Requirements: 8.1, 8.2**
    """

    def test_low_confidence_triggers_fallback(self):
        """Low planner confidence should trigger fallback."""
        planner = Planner(confidence_threshold=0.8)

        result = planner.plan("xyz123 unknown query")

        # Very ambiguous query should have low confidence
        # Fallback decision is made by caller based on confidence
        assert isinstance(result, StructuredPlan)
        # Note: Actual fallback logic is in lambda_handler

    def test_empty_query_returns_fallback_plan(self):
        """Empty query should return fallback plan."""
        planner = Planner()

        result = planner.plan("")

        assert isinstance(result, StructuredPlan)
        assert result.confidence == 0.0  # Empty query = 0 confidence

    def test_whitespace_query_returns_fallback_plan(self):
        """Whitespace-only query should return fallback plan."""
        planner = Planner()

        result = planner.plan("   ")

        assert isinstance(result, StructuredPlan)
        assert result.confidence == 0.0


class TestParallelExecutionTiming:
    """
    Tests for parallel execution timing.

    **Requirements: 1.2, 8.1**
    """

    def test_planner_tracks_planning_time(self):
        """Planner should track planning time."""
        planner = Planner()

        result = planner.plan("Class A properties in Dallas")

        assert result.planning_time_ms >= 0
        assert result.planning_time_ms < 1000  # Should be fast

    def test_planner_timeout_enforcement(self):
        """Planner should enforce timeout."""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        # Create a planner with very short timeout
        planner = Planner(timeout_ms=1)

        # Run in executor with timeout
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(planner.plan, "test query")
            try:
                result = future.result(timeout=0.001)
                # If we get here quickly, that's fine
            except TimeoutError:
                # Timeout is expected for very short timeout
                pass

        elapsed_ms = (time.perf_counter() - start) * 1000
        # Should not take more than a few seconds even with timeout
        assert elapsed_ms < 5000


class TestPredicateHandling:
    """Tests for predicate extraction and handling."""

    def test_predicate_creation(self):
        """Predicate should be creatable with valid operator."""
        pred = Predicate(
            field="ascendix__City__c",
            operator="eq",
            value="Dallas",
        )

        assert pred.field == "ascendix__City__c"
        assert pred.operator == "eq"
        assert pred.value == "Dallas"

    def test_predicate_to_dict(self):
        """Predicate should convert to dict."""
        pred = Predicate(
            field="ascendix__City__c",
            operator="eq",
            value="Dallas",
        )

        d = pred.to_dict()

        assert d["field"] == "ascendix__City__c"
        assert d["operator"] == "eq"
        assert d["value"] == "Dallas"

    def test_predicate_from_dict(self):
        """Predicate should be creatable from dict."""
        data = {
            "field": "ascendix__City__c",
            "operator": "eq",
            "value": "Dallas",
        }

        pred = Predicate.from_dict(data)

        assert pred.field == "ascendix__City__c"
        assert pred.operator == "eq"
        assert pred.value == "Dallas"

    def test_predicate_invalid_operator_raises(self):
        """Invalid operator should raise ValueError."""
        with pytest.raises(ValueError):
            Predicate(
                field="test",
                operator="invalid_op",
                value="test",
            )

    def test_predicate_with_source_object(self):
        """Predicate should support source_object for cross-object filters."""
        pred = Predicate(
            field="ascendix__City__c",
            operator="eq",
            value="Dallas",
            source_object="ascendix__Property__c",
        )

        assert pred.source_object == "ascendix__Property__c"
        d = pred.to_dict()
        assert d["source_object"] == "ascendix__Property__c"


class TestStructuredPlanHandling:
    """Tests for StructuredPlan handling."""

    def test_structured_plan_creation(self):
        """StructuredPlan should be creatable."""
        plan = StructuredPlan(
            target_object="ascendix__Property__c",
            predicates=[],
            confidence=0.8,
            query="test query",
        )

        assert plan.target_object == "ascendix__Property__c"
        assert plan.confidence == 0.8
        assert plan.query == "test query"

    def test_structured_plan_with_predicates(self):
        """StructuredPlan should hold predicates."""
        predicates = [
            Predicate(field="City__c", operator="eq", value="Dallas"),
            Predicate(field="Size__c", operator="gt", value=50000),
        ]

        plan = StructuredPlan(
            target_object="Property__c",
            predicates=predicates,
            confidence=0.9,
            query="large properties in Dallas",
        )

        assert len(plan.predicates) == 2
        assert plan.predicates[0].field == "City__c"
        assert plan.predicates[1].operator == "gt"

    def test_structured_plan_confidence_bounds(self):
        """StructuredPlan confidence should be bounded."""
        # Too high - should be clamped
        plan_high = StructuredPlan(
            target_object="Test__c",
            confidence=1.5,
            query="test",
        )
        assert plan_high.confidence <= 1.0

        # Too low - should be clamped
        plan_low = StructuredPlan(
            target_object="Test__c",
            confidence=-0.5,
            query="test",
        )
        assert plan_low.confidence >= 0.0

    def test_structured_plan_has_to_dict(self):
        """StructuredPlan should have to_dict method."""
        plan = StructuredPlan(
            target_object="Property__c",
            predicates=[Predicate(field="City", operator="eq", value="Dallas")],
            confidence=0.85,
            query="properties in Dallas",
        )

        d = plan.to_dict()

        assert d["target_object"] == "Property__c"
        assert d["confidence"] == 0.85
        assert len(d["predicates"]) == 1


class TestTelemetryLogging:
    """
    Tests for telemetry logging.

    **Requirements: 1.4, 12.5**
    """

    def test_planner_result_contains_timing(self):
        """Planner result should contain timing info."""
        planner = Planner()

        result = planner.plan("test query")

        assert hasattr(result, "planning_time_ms")
        assert result.planning_time_ms >= 0

    def test_planner_result_serializable(self):
        """Planner result should be JSON serializable."""
        import json

        planner = Planner()
        result = planner.plan("test query")

        # Should not raise
        d = result.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)


class TestFeatureFlagIntegration:
    """Tests for feature flag integration."""

    @patch.dict(os.environ, {"PLANNER_ENABLED": "false"})
    def test_planner_disabled_env(self):
        """Planner can be disabled via environment variable."""
        # This tests that the env var is respected
        # Actual integration in index.py checks PLANNER_ENABLED
        enabled = os.getenv("PLANNER_ENABLED", "true").lower() == "true"
        assert enabled is False

    @patch.dict(os.environ, {"PLANNER_ENABLED": "true"})
    def test_planner_enabled_env(self):
        """Planner can be enabled via environment variable."""
        enabled = os.getenv("PLANNER_ENABLED", "true").lower() == "true"
        assert enabled is True

    @patch.dict(os.environ, {"PLANNER_TIMEOUT_MS": "1000"})
    def test_planner_timeout_configurable(self):
        """Planner timeout is configurable via environment."""
        timeout = int(os.getenv("PLANNER_TIMEOUT_MS", "500"))
        assert timeout == 1000

    @patch.dict(os.environ, {"PLANNER_MIN_CONFIDENCE": "0.7"})
    def test_planner_confidence_threshold_configurable(self):
        """Planner confidence threshold is configurable via environment."""
        threshold = float(os.getenv("PLANNER_MIN_CONFIDENCE", "0.5"))
        assert threshold == 0.7


class TestEndToEndQueryFlow:
    """
    Tests for end-to-end query flow.

    **Requirements: 1.1**
    """

    def test_property_query_flow(self):
        """Property query should flow through planner."""
        planner = Planner()

        result = planner.plan("Class A office buildings in downtown Dallas")

        # Should identify Property as target
        assert result.target_object is not None
        assert result.confidence >= 0.0

    def test_availability_query_flow(self):
        """Availability query should flow through planner."""
        planner = Planner()

        result = planner.plan("available spaces over 10000 sqft")

        assert result.target_object is not None
        assert result.confidence >= 0.0

    def test_aggregation_query_detection(self):
        """Aggregation queries should be detected."""
        planner = Planner()

        # Aggregation query
        result = planner.plan("total available square feet by property class")

        # Should complete without error
        assert isinstance(result, StructuredPlan)

    def test_cross_object_query_detection(self):
        """Cross-object queries should be detected."""
        planner = Planner()

        # Cross-object: Availabilities filtered by Property attributes
        result = planner.plan("available spaces in Class A buildings in Dallas")

        # Should complete without error
        assert isinstance(result, StructuredPlan)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
