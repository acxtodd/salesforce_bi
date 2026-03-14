"""
Tests for Circuit Breaker and Graceful Degradation.

**Feature: phase3-graph-enhancement**
**Requirements: 4.3**
"""
import time
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unittest.mock import Mock, patch, MagicMock
from hypothesis import given, strategies as st, settings

from circuit_breaker import (
    GraphCircuitBreaker,
    CircuitOpenError,
    CircuitState,
    CircuitBreakerStats,
    get_graph_circuit_breaker,
    reset_graph_circuit_breaker,
    with_circuit_breaker,
)
from graceful_degradation import (
    GracefulDegradation,
    DegradationResult,
    DegradationMode,
    get_graceful_degradation,
    vector_only_fallback_result,
    partial_result_response,
)


# =============================================================================
# Circuit Breaker Unit Tests
# =============================================================================

class TestGraphCircuitBreaker:
    """Unit tests for GraphCircuitBreaker class."""

    def test_initial_state_is_closed(self):
        """Circuit breaker should start in CLOSED state."""
        cb = GraphCircuitBreaker(name="test", emit_metrics=False)
        assert cb.state == CircuitState.CLOSED
        assert cb.is_closed
        assert not cb.is_open
        assert not cb.is_half_open

    def test_successful_calls_keep_circuit_closed(self):
        """Successful calls should keep circuit in CLOSED state."""
        cb = GraphCircuitBreaker(name="test", emit_metrics=False)
        
        def success_func():
            return "success"
        
        for _ in range(10):
            result = cb.call(success_func)
            assert result == "success"
        
        assert cb.is_closed
        assert cb.stats.successful_calls == 10
        assert cb.stats.failed_calls == 0

    def test_failures_open_circuit_after_threshold(self):
        """Circuit should open after failure_threshold consecutive failures."""
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=3,
            emit_metrics=False
        )
        
        def failing_func():
            raise ValueError("test error")
        
        # First 2 failures - circuit stays closed
        for i in range(2):
            with pytest.raises(ValueError):
                cb.call(failing_func)
            assert cb.is_closed, f"Circuit should be closed after {i+1} failures"
        
        # 3rd failure - circuit opens
        with pytest.raises(ValueError):
            cb.call(failing_func)
        
        assert cb.is_open
        assert cb.stats.failed_calls == 3

    def test_open_circuit_rejects_requests(self):
        """Open circuit should reject requests with CircuitOpenError."""
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=1,
            emit_metrics=False
        )
        
        # Open the circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        
        assert cb.is_open
        
        # Subsequent calls should be rejected
        with pytest.raises(CircuitOpenError) as exc_info:
            cb.call(lambda: "should not execute")
        
        assert "open" in str(exc_info.value).lower()
        assert cb.stats.rejected_calls == 1

    def test_circuit_transitions_to_half_open_after_timeout(self):
        """Circuit should transition to HALF_OPEN after reset_timeout."""
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=1,
            reset_timeout=0.1,  # 100ms for fast test
            emit_metrics=False
        )
        
        # Open the circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        
        assert cb.is_open
        
        # Wait for reset timeout
        time.sleep(0.15)
        
        # Next call should transition to half-open and execute
        result = cb.call(lambda: "recovered")
        assert result == "recovered"
        # After success in half-open, may transition to closed
        # depending on success_threshold

    def test_half_open_closes_after_success_threshold(self):
        """Circuit should close after success_threshold successes in HALF_OPEN."""
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=1,
            reset_timeout=0.05,
            success_threshold=2,
            emit_metrics=False
        )
        
        # Open the circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        
        # Wait for reset timeout
        time.sleep(0.1)
        
        # First success - still half-open or transitioning
        cb.call(lambda: "success1")
        
        # Second success - should close
        cb.call(lambda: "success2")
        
        assert cb.is_closed

    def test_half_open_reopens_on_failure(self):
        """Circuit should reopen on any failure in HALF_OPEN state."""
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=1,
            reset_timeout=0.05,
            success_threshold=3,
            emit_metrics=False
        )
        
        # Open the circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        
        # Wait for reset timeout
        time.sleep(0.1)
        
        # Fail in half-open state
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail again")))
        
        assert cb.is_open

    def test_manual_reset(self):
        """Manual reset should close the circuit."""
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=1,
            emit_metrics=False
        )
        
        # Open the circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        
        assert cb.is_open
        
        # Manual reset
        cb.reset()
        
        assert cb.is_closed
        
        # Should accept calls again
        result = cb.call(lambda: "works")
        assert result == "works"

    def test_stats_tracking(self):
        """Circuit breaker should track statistics correctly."""
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=5,
            emit_metrics=False
        )
        
        # Some successes
        for _ in range(3):
            cb.call(lambda: "ok")
        
        # Some failures
        for _ in range(2):
            try:
                cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
            except ValueError:
                pass
        
        stats = cb.stats
        assert stats.total_calls == 5
        assert stats.successful_calls == 3
        assert stats.failed_calls == 2
        assert stats.rejected_calls == 0


class TestCircuitBreakerDecorator:
    """Tests for the with_circuit_breaker decorator."""

    def test_decorator_wraps_function(self):
        """Decorator should wrap function with circuit breaker."""
        cb = GraphCircuitBreaker(name="test", emit_metrics=False)
        
        @with_circuit_breaker(cb)
        def my_func(x):
            return x * 2
        
        assert my_func(5) == 10
        assert cb.stats.successful_calls == 1

    def test_decorator_with_fallback(self):
        """Decorator should use fallback when circuit is open."""
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=1,
            emit_metrics=False
        )
        
        def fallback_func(x):
            return x * 10  # Different behavior
        
        @with_circuit_breaker(cb, fallback=fallback_func)
        def my_func(x):
            raise ValueError("always fails")
        
        # First call fails and opens circuit
        with pytest.raises(ValueError):
            my_func(5)
        
        # Second call uses fallback
        result = my_func(5)
        assert result == 50  # Fallback result


# =============================================================================
# Graceful Degradation Unit Tests
# =============================================================================

class TestGracefulDegradation:
    """Unit tests for GracefulDegradation class."""

    def test_successful_execution_returns_full_mode(self):
        """Successful execution should return FULL degradation mode."""
        gd = GracefulDegradation(emit_metrics=False)
        
        def primary():
            return {"data": "success"}
        
        def fallback():
            return {"data": "fallback"}
        
        result = gd.execute_with_fallback(primary, fallback)
        
        assert result.mode == DegradationMode.FULL
        assert not result.degraded
        assert result.data == {"data": "success"}

    def test_timeout_error_returns_partial_or_fallback(self):
        """TimeoutError should trigger partial results or fallback."""
        gd = GracefulDegradation(emit_metrics=False)
        
        def primary():
            raise TimeoutError("traversal timeout")
        
        def fallback():
            return {"data": "fallback"}
        
        result = gd.execute_with_fallback(primary, fallback)
        
        assert result.degraded
        assert result.mode in (DegradationMode.PARTIAL, DegradationMode.VECTOR_ONLY)

    def test_connection_error_uses_fallback(self):
        """ConnectionError should use fallback."""
        gd = GracefulDegradation(emit_metrics=False)
        
        def primary():
            raise ConnectionError("database unavailable")
        
        def fallback():
            return {"data": "fallback"}
        
        result = gd.execute_with_fallback(primary, fallback)
        
        assert result.degraded
        assert result.mode == DegradationMode.VECTOR_ONLY
        assert result.fallback_used
        assert result.data == {"data": "fallback"}

    def test_generic_error_uses_fallback(self):
        """Generic exceptions should use fallback."""
        gd = GracefulDegradation(emit_metrics=False)
        
        def primary():
            raise RuntimeError("unexpected error")
        
        def fallback():
            return {"data": "fallback"}
        
        result = gd.execute_with_fallback(primary, fallback)
        
        assert result.degraded
        assert result.fallback_used

    def test_fallback_failure_returns_disabled_mode(self):
        """If fallback also fails, should return DISABLED mode."""
        gd = GracefulDegradation(emit_metrics=False)
        
        def primary():
            raise ValueError("primary fails")
        
        def fallback():
            raise RuntimeError("fallback also fails")
        
        result = gd.execute_with_fallback(primary, fallback)
        
        assert result.degraded
        assert result.mode == DegradationMode.DISABLED
        assert result.data is None

    def test_skip_invalid_and_continue(self):
        """Should skip invalid items and continue processing."""
        gd = GracefulDegradation(emit_metrics=False)
        
        items = [1, 2, "invalid", 4, None, 6]
        
        def processor(item):
            if not isinstance(item, int):
                raise ValueError(f"Invalid item: {item}")
            return item * 2
        
        results = gd.skip_invalid_and_continue(items, processor)
        
        assert results == [2, 4, 8, 12]  # Only valid items processed

    def test_degradation_result_to_dict(self):
        """DegradationResult should serialize to dict correctly."""
        result = DegradationResult(
            data={"test": "data"},
            mode=DegradationMode.PARTIAL,
            degraded=True,
            warning="test_warning",
            partial=True,
            latency_ms=100.5,
        )
        
        d = result.to_dict()
        
        assert d["data"] == {"test": "data"}
        assert d["degraded"] is True
        assert d["warning"] == "test_warning"
        assert d["partial"] is True
        assert d["latencyMs"] == 100.5


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_vector_only_fallback_result(self):
        """vector_only_fallback_result should create proper response."""
        vector_results = [{"id": "1"}, {"id": "2"}]
        
        result = vector_only_fallback_result(vector_results, "test_warning")
        
        assert result["success"] is True
        assert result["results"] == vector_results
        assert result["degraded"] is True
        assert result["warning"] == "test_warning"
        assert result["graphEnabled"] is False

    def test_partial_result_response(self):
        """partial_result_response should create proper response."""
        partial_results = [{"id": "1"}]
        
        result = partial_result_response(partial_results, nodes_visited=50, max_depth_reached=2)
        
        assert result["success"] is True
        assert result["results"] == partial_results
        assert result["partial"] is True
        assert result["warning"] == "traversal_timeout"
        assert result["nodesVisited"] == 50
        assert result["maxDepthReached"] == 2


# =============================================================================
# Property-Based Tests
# =============================================================================

class TestCircuitBreakerProperties:
    """Property-based tests for circuit breaker behavior."""

    @given(
        failure_threshold=st.integers(min_value=1, max_value=10),
        num_failures=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=50)
    def test_circuit_opens_exactly_at_threshold(self, failure_threshold, num_failures):
        """
        **Feature: phase3-graph-enhancement, Property: Circuit Opens at Threshold**
        
        Circuit should open exactly when failure count reaches threshold.
        """
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=failure_threshold,
            emit_metrics=False
        )
        
        for i in range(num_failures):
            if cb.is_open:
                break
            try:
                cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
            except (ValueError, CircuitOpenError):
                pass
        
        if num_failures >= failure_threshold:
            assert cb.is_open, f"Circuit should be open after {num_failures} failures (threshold={failure_threshold})"
        else:
            assert cb.is_closed, f"Circuit should be closed after {num_failures} failures (threshold={failure_threshold})"

    @given(
        num_successes=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=30)
    def test_successes_never_open_circuit(self, num_successes):
        """
        **Feature: phase3-graph-enhancement, Property: Successes Keep Circuit Closed**
        
        Any number of successful calls should never open the circuit.
        """
        cb = GraphCircuitBreaker(name="test", emit_metrics=False)
        
        for _ in range(num_successes):
            cb.call(lambda: "success")
        
        assert cb.is_closed
        assert cb.stats.successful_calls == num_successes

    @given(
        failure_threshold=st.integers(min_value=1, max_value=5),
        success_threshold=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=30)
    def test_circuit_state_transitions_are_valid(self, failure_threshold, success_threshold):
        """
        **Feature: phase3-graph-enhancement, Property: Valid State Transitions**
        
        Circuit state transitions should follow valid patterns:
        - CLOSED -> OPEN (on failures)
        - OPEN -> HALF_OPEN (on timeout)
        - HALF_OPEN -> CLOSED (on successes)
        - HALF_OPEN -> OPEN (on failure)
        """
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=failure_threshold,
            success_threshold=success_threshold,
            reset_timeout=0.01,
            emit_metrics=False
        )
        
        # Start closed
        assert cb.state == CircuitState.CLOSED
        
        # Failures should lead to OPEN
        for _ in range(failure_threshold):
            try:
                cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
            except ValueError:
                pass
        
        assert cb.state == CircuitState.OPEN
        
        # Wait for timeout
        time.sleep(0.02)
        
        # Next call transitions to HALF_OPEN
        try:
            cb.call(lambda: "test")
        except CircuitOpenError:
            pass
        
        # State should be HALF_OPEN or CLOSED (if success_threshold=1)
        assert cb.state in (CircuitState.HALF_OPEN, CircuitState.CLOSED)


class TestGracefulDegradationProperties:
    """Property-based tests for graceful degradation."""

    @given(
        num_items=st.integers(min_value=0, max_value=20),
        num_failures=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=50)
    def test_skip_invalid_processes_all_valid_items(self, num_items, num_failures):
        """
        **Feature: phase3-graph-enhancement, Property: All Valid Items Processed**
        
        skip_invalid_and_continue should process all valid items.
        """
        gd = GracefulDegradation(emit_metrics=False)
        
        # Create items with unique identifiers
        items = list(range(num_items))
        # Determine which indices should fail (capped to actual item count)
        fail_indices = set(range(min(num_failures, num_items)))
        
        def processor(item):
            if item in fail_indices:
                raise ValueError("simulated failure")
            return item * 2
        
        results = gd.skip_invalid_and_continue(items, processor)
        
        # Count expected valid items
        expected_count = num_items - len(fail_indices)
        
        assert len(results) == expected_count

    @given(
        primary_succeeds=st.booleans(),
        fallback_succeeds=st.booleans(),
    )
    @settings(max_examples=20)
    def test_degradation_mode_consistency(self, primary_succeeds, fallback_succeeds):
        """
        **Feature: phase3-graph-enhancement, Property: Degradation Mode Consistency**
        
        Degradation mode should be consistent with execution outcome.
        """
        gd = GracefulDegradation(emit_metrics=False)
        
        def primary():
            if not primary_succeeds:
                raise ValueError("primary failed")
            return "primary"
        
        def fallback():
            if not fallback_succeeds:
                raise RuntimeError("fallback failed")
            return "fallback"
        
        result = gd.execute_with_fallback(primary, fallback)
        
        if primary_succeeds:
            assert result.mode == DegradationMode.FULL
            assert not result.degraded
        elif fallback_succeeds:
            assert result.mode == DegradationMode.VECTOR_ONLY
            assert result.degraded
            assert result.fallback_used
        else:
            assert result.mode == DegradationMode.DISABLED
            assert result.degraded


# =============================================================================
# Integration Tests
# =============================================================================

class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker with graph retriever."""

    @patch('circuit_breaker.cloudwatch')
    def test_metrics_emitted_on_state_change(self, mock_cloudwatch):
        """Circuit breaker should emit metrics on state changes."""
        cb = GraphCircuitBreaker(
            name="test",
            failure_threshold=1,
            emit_metrics=True
        )
        
        # Trigger state change
        try:
            cb.call(lambda: (_ for _ in ()).throw(ValueError("fail")))
        except ValueError:
            pass
        
        # Verify metrics were emitted
        assert mock_cloudwatch.put_metric_data.called

    def test_global_circuit_breaker_singleton(self):
        """get_graph_circuit_breaker should return singleton."""
        reset_graph_circuit_breaker()
        
        cb1 = get_graph_circuit_breaker()
        cb2 = get_graph_circuit_breaker()
        
        assert cb1 is cb2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
