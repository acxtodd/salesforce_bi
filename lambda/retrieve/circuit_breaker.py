"""
Circuit Breaker for Graph Operations.

Implements the circuit breaker pattern to prevent cascading failures
when graph database operations fail repeatedly.

**Feature: phase3-graph-enhancement**
**Requirements: 4.3**
"""
import os
import time
import logging
import threading
from typing import Callable, TypeVar, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps

import boto3

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Initialize CloudWatch client for metrics
cloudwatch = boto3.client('cloudwatch')

# Configuration from environment
FAILURE_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5"))
RESET_TIMEOUT_SECONDS = int(os.getenv("CIRCUIT_BREAKER_RESET_TIMEOUT", "30"))
SUCCESS_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_SUCCESS_THRESHOLD", "3"))
METRICS_NAMESPACE = os.getenv("METRICS_NAMESPACE", "SalesforceAISearch/Graph")

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation, requests pass through
    OPEN = "open"          # Failing, requests are blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open and blocking requests."""
    
    def __init__(self, message: str = "Circuit breaker is open", 
                 time_until_retry: Optional[float] = None):
        super().__init__(message)
        self.time_until_retry = time_until_retry


@dataclass
class CircuitBreakerStats:
    """Statistics for circuit breaker monitoring."""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    state_changes: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    last_state_change_time: Optional[float] = None
    
    def to_dict(self) -> dict:
        """Convert stats to dictionary for logging/metrics."""
        return {
            "totalCalls": self.total_calls,
            "successfulCalls": self.successful_calls,
            "failedCalls": self.failed_calls,
            "rejectedCalls": self.rejected_calls,
            "stateChanges": self.state_changes,
            "lastFailureTime": self.last_failure_time,
            "lastSuccessTime": self.last_success_time,
            "lastStateChangeTime": self.last_state_change_time,
        }


class GraphCircuitBreaker:
    """
    Circuit breaker for graph database operations.
    
    Implements the circuit breaker pattern:
    - CLOSED: Normal operation, requests pass through
    - OPEN: After consecutive failures, block requests
    - HALF_OPEN: After timeout, allow test requests
    
    **Requirements: 4.3**
    
    Configuration:
    - failure_threshold: Number of consecutive failures to open circuit (default: 5)
    - reset_timeout: Seconds to wait before attempting reset (default: 30)
    - success_threshold: Successful calls needed to close circuit (default: 3)
    
    Thread Safety:
    - Uses threading.Lock for state management
    - Safe for concurrent Lambda invocations within same container
    """
    
    def __init__(
        self,
        name: str = "graph",
        failure_threshold: int = FAILURE_THRESHOLD,
        reset_timeout: float = RESET_TIMEOUT_SECONDS,
        success_threshold: int = SUCCESS_THRESHOLD,
        emit_metrics: bool = True,
    ):
        """
        Initialize the circuit breaker.
        
        Args:
            name: Name for logging and metrics
            failure_threshold: Consecutive failures to open circuit
            reset_timeout: Seconds before attempting reset
            success_threshold: Successes needed to close from half-open
            emit_metrics: Whether to emit CloudWatch metrics
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.success_threshold = success_threshold
        self.emit_metrics = emit_metrics
        
        # State management
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._last_state_change_time: Optional[float] = None
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Statistics
        self._stats = CircuitBreakerStats()
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            return self._state
    
    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self.state == CircuitState.OPEN
    
    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing recovery)."""
        return self.state == CircuitState.HALF_OPEN
    
    @property
    def stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        with self._lock:
            return CircuitBreakerStats(
                total_calls=self._stats.total_calls,
                successful_calls=self._stats.successful_calls,
                failed_calls=self._stats.failed_calls,
                rejected_calls=self._stats.rejected_calls,
                state_changes=self._stats.state_changes,
                last_failure_time=self._stats.last_failure_time,
                last_success_time=self._stats.last_success_time,
                last_state_change_time=self._stats.last_state_change_time,
            )
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self._last_failure_time is None:
            return True
        return time.time() - self._last_failure_time >= self.reset_timeout
    
    def _time_until_retry(self) -> Optional[float]:
        """Calculate time remaining until retry is allowed."""
        if self._last_failure_time is None:
            return None
        elapsed = time.time() - self._last_failure_time
        remaining = self.reset_timeout - elapsed
        return max(0, remaining)
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state with logging and metrics."""
        old_state = self._state
        if old_state == new_state:
            return
        
        self._state = new_state
        self._last_state_change_time = time.time()
        self._stats.state_changes += 1
        self._stats.last_state_change_time = self._last_state_change_time
        
        LOGGER.info(
            f"Circuit breaker '{self.name}' state change: {old_state.value} -> {new_state.value}"
        )
        
        if self.emit_metrics:
            self._emit_state_metric(new_state)
    
    def _on_success(self) -> None:
        """Handle successful call."""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.successful_calls += 1
            self._stats.last_success_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0
    
    def _on_failure(self, exception: Exception) -> None:
        """Handle failed call."""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.failed_calls += 1
            self._stats.last_failure_time = time.time()
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open returns to open
                self._transition_to(CircuitState.OPEN)
                self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
            
            LOGGER.warning(
                f"Circuit breaker '{self.name}' recorded failure: {type(exception).__name__}: {exception}"
            )
    
    def _check_state(self) -> None:
        """Check and potentially update circuit state before a call."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to(CircuitState.HALF_OPEN)
                    self._success_count = 0
    
    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute a function through the circuit breaker.
        
        Args:
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result of func
            
        Raises:
            CircuitOpenError: If circuit is open and blocking requests
            Exception: Any exception raised by func
        """
        # Check if we should transition from OPEN to HALF_OPEN
        self._check_state()
        
        # Check if circuit is open
        with self._lock:
            if self._state == CircuitState.OPEN:
                self._stats.rejected_calls += 1
                time_until_retry = self._time_until_retry()
                LOGGER.warning(
                    f"Circuit breaker '{self.name}' is OPEN, rejecting request. "
                    f"Retry in {time_until_retry:.1f}s"
                )
                if self.emit_metrics:
                    self._emit_rejected_metric()
                raise CircuitOpenError(
                    f"Circuit breaker '{self.name}' is open",
                    time_until_retry=time_until_retry
                )
        
        # Execute the function
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure(e)
            raise
    
    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            LOGGER.info(f"Circuit breaker '{self.name}' manually reset")
    
    def _emit_state_metric(self, state: CircuitState) -> None:
        """Emit CloudWatch metric for state change."""
        try:
            # Map state to numeric value for graphing
            state_value = {
                CircuitState.CLOSED: 0,
                CircuitState.HALF_OPEN: 1,
                CircuitState.OPEN: 2,
            }.get(state, 0)
            
            cloudwatch.put_metric_data(
                Namespace=METRICS_NAMESPACE,
                MetricData=[
                    {
                        'MetricName': 'CircuitBreakerState',
                        'Value': state_value,
                        'Unit': 'None',
                        'Dimensions': [
                            {'Name': 'CircuitName', 'Value': self.name}
                        ]
                    },
                    {
                        'MetricName': 'CircuitBreakerStateChange',
                        'Value': 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'CircuitName', 'Value': self.name},
                            {'Name': 'NewState', 'Value': state.value}
                        ]
                    }
                ]
            )
        except Exception as e:
            LOGGER.debug(f"Failed to emit circuit breaker metric: {e}")
    
    def _emit_rejected_metric(self) -> None:
        """Emit CloudWatch metric for rejected request."""
        try:
            cloudwatch.put_metric_data(
                Namespace=METRICS_NAMESPACE,
                MetricData=[
                    {
                        'MetricName': 'CircuitBreakerRejected',
                        'Value': 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'CircuitName', 'Value': self.name}
                        ]
                    }
                ]
            )
        except Exception as e:
            LOGGER.debug(f"Failed to emit rejected metric: {e}")


# =============================================================================
# Decorator for easy circuit breaker usage
# =============================================================================

def with_circuit_breaker(
    circuit_breaker: GraphCircuitBreaker,
    fallback: Optional[Callable[..., T]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to wrap a function with circuit breaker protection.
    
    Args:
        circuit_breaker: The circuit breaker instance to use
        fallback: Optional fallback function to call when circuit is open
        
    Returns:
        Decorated function
        
    Example:
        @with_circuit_breaker(graph_circuit_breaker, fallback=lambda *a, **k: [])
        def query_graph(node_id: str) -> List[Dict]:
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            try:
                return circuit_breaker.call(func, *args, **kwargs)
            except CircuitOpenError:
                if fallback is not None:
                    LOGGER.info(f"Circuit open, using fallback for {func.__name__}")
                    return fallback(*args, **kwargs)
                raise
        return wrapper
    return decorator


# =============================================================================
# Global circuit breaker instance for graph operations
# =============================================================================

_graph_circuit_breaker: Optional[GraphCircuitBreaker] = None


def get_graph_circuit_breaker() -> GraphCircuitBreaker:
    """Get or create the global graph circuit breaker instance."""
    global _graph_circuit_breaker
    if _graph_circuit_breaker is None:
        _graph_circuit_breaker = GraphCircuitBreaker(
            name="graph",
            failure_threshold=FAILURE_THRESHOLD,
            reset_timeout=RESET_TIMEOUT_SECONDS,
            success_threshold=SUCCESS_THRESHOLD,
        )
    return _graph_circuit_breaker


def reset_graph_circuit_breaker() -> None:
    """Reset the global graph circuit breaker (useful for testing)."""
    global _graph_circuit_breaker
    if _graph_circuit_breaker is not None:
        _graph_circuit_breaker.reset()
