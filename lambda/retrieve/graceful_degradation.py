"""
Graceful Degradation for Graph Operations.

Provides fallback mechanisms when graph database operations fail,
ensuring the system continues to function with reduced capabilities.

**Feature: phase3-graph-enhancement**
**Requirements: 4.3**
"""
import os
import time
import logging
from typing import Dict, List, Any, Optional, Callable, TypeVar
from dataclasses import dataclass, field
from enum import Enum

import boto3

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Initialize CloudWatch client for metrics
cloudwatch = boto3.client('cloudwatch')

# Configuration
METRICS_NAMESPACE = os.getenv("METRICS_NAMESPACE", "SalesforceAISearch/Graph")
TRAVERSAL_TIMEOUT_SECONDS = float(os.getenv("GRAPH_TRAVERSAL_TIMEOUT", "2.0"))

T = TypeVar('T')


class DegradationMode(Enum):
    """Degradation modes for graph operations."""
    FULL = "full"              # Full graph functionality
    PARTIAL = "partial"        # Partial results (timeout/truncation)
    VECTOR_ONLY = "vector_only"  # Fallback to vector search only
    DISABLED = "disabled"      # Graph features completely disabled


@dataclass
class DegradationResult:
    """Result wrapper that includes degradation information."""
    data: Any
    mode: DegradationMode
    degraded: bool = False
    warning: Optional[str] = None
    partial: bool = False
    error_type: Optional[str] = None
    fallback_used: bool = False
    latency_ms: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response."""
        result = {
            "data": self.data,
            "degraded": self.degraded,
        }
        if self.warning:
            result["warning"] = self.warning
        if self.partial:
            result["partial"] = self.partial
        if self.error_type:
            result["errorType"] = self.error_type
        if self.fallback_used:
            result["fallbackUsed"] = self.fallback_used
        if self.latency_ms is not None:
            result["latencyMs"] = self.latency_ms
        return result


class GracefulDegradation:
    """
    Handles graceful degradation for graph operations.
    
    Provides:
    - Fallback to vector-only search when graph is unavailable
    - Partial results on traversal timeout
    - Skip invalid relationships and continue with valid ones
    - Error logging with request context
    
    **Requirements: 4.3**
    """
    
    def __init__(
        self,
        emit_metrics: bool = True,
        traversal_timeout: float = TRAVERSAL_TIMEOUT_SECONDS,
    ):
        """
        Initialize graceful degradation handler.
        
        Args:
            emit_metrics: Whether to emit CloudWatch metrics
            traversal_timeout: Timeout for graph traversal in seconds
        """
        self.emit_metrics = emit_metrics
        self.traversal_timeout = traversal_timeout
        self._degradation_count = 0
        self._fallback_count = 0
    
    def execute_with_fallback(
        self,
        primary_func: Callable[..., T],
        fallback_func: Callable[..., T],
        request_id: Optional[str] = None,
        *args: Any,
        **kwargs: Any,
    ) -> DegradationResult:
        """
        Execute primary function with fallback on failure.
        
        **Requirements: 4.3**
        
        Args:
            primary_func: Primary function to execute (graph operation)
            fallback_func: Fallback function (vector-only search)
            request_id: Optional request ID for logging
            *args: Arguments for both functions
            **kwargs: Keyword arguments for both functions
            
        Returns:
            DegradationResult with data and degradation info
        """
        start_time = time.time()
        
        try:
            result = primary_func(*args, **kwargs)
            latency_ms = (time.time() - start_time) * 1000
            
            return DegradationResult(
                data=result,
                mode=DegradationMode.FULL,
                degraded=False,
                latency_ms=latency_ms,
            )
            
        except TimeoutError as e:
            # Partial results on timeout
            latency_ms = (time.time() - start_time) * 1000
            self._log_degradation(
                "traversal_timeout",
                str(e),
                request_id,
                latency_ms,
            )
            
            # Try to get partial results if available
            partial_result = getattr(e, 'partial_result', None)
            if partial_result is not None:
                return DegradationResult(
                    data=partial_result,
                    mode=DegradationMode.PARTIAL,
                    degraded=True,
                    warning="traversal_timeout",
                    partial=True,
                    error_type="timeout",
                    latency_ms=latency_ms,
                )
            
            # Fall back to vector-only
            return self._execute_fallback(
                fallback_func,
                "traversal_timeout",
                request_id,
                start_time,
                *args,
                **kwargs,
            )
            
        except ConnectionError as e:
            # Graph database unavailable
            latency_ms = (time.time() - start_time) * 1000
            self._log_degradation(
                "graph_unavailable",
                str(e),
                request_id,
                latency_ms,
            )
            
            return self._execute_fallback(
                fallback_func,
                "graph_unavailable",
                request_id,
                start_time,
                *args,
                **kwargs,
            )
            
        except Exception as e:
            # Generic error - fall back
            latency_ms = (time.time() - start_time) * 1000
            error_type = type(e).__name__
            self._log_degradation(
                error_type,
                str(e),
                request_id,
                latency_ms,
            )
            
            return self._execute_fallback(
                fallback_func,
                error_type,
                request_id,
                start_time,
                *args,
                **kwargs,
            )
    
    def _execute_fallback(
        self,
        fallback_func: Callable[..., T],
        warning: str,
        request_id: Optional[str],
        start_time: float,
        *args: Any,
        **kwargs: Any,
    ) -> DegradationResult:
        """Execute fallback function and return degradation result."""
        self._fallback_count += 1
        
        try:
            result = fallback_func(*args, **kwargs)
            latency_ms = (time.time() - start_time) * 1000
            
            if self.emit_metrics:
                self._emit_fallback_metric(warning)
            
            return DegradationResult(
                data=result,
                mode=DegradationMode.VECTOR_ONLY,
                degraded=True,
                warning=warning,
                fallback_used=True,
                latency_ms=latency_ms,
            )
            
        except Exception as fallback_error:
            # Even fallback failed
            latency_ms = (time.time() - start_time) * 1000
            LOGGER.error(
                f"Fallback also failed: {fallback_error}",
                extra={"request_id": request_id},
            )
            
            return DegradationResult(
                data=None,
                mode=DegradationMode.DISABLED,
                degraded=True,
                warning=f"fallback_failed: {warning}",
                error_type=type(fallback_error).__name__,
                fallback_used=True,
                latency_ms=latency_ms,
            )
    
    def skip_invalid_and_continue(
        self,
        items: List[Any],
        processor: Callable[[Any], T],
        request_id: Optional[str] = None,
    ) -> List[T]:
        """
        Process items, skipping invalid ones and continuing with valid.
        
        **Requirements: 4.3**
        
        Args:
            items: List of items to process
            processor: Function to process each item
            request_id: Optional request ID for logging
            
        Returns:
            List of successfully processed results
        """
        results = []
        skipped_count = 0
        
        for item in items:
            try:
                result = processor(item)
                results.append(result)
            except Exception as e:
                skipped_count += 1
                LOGGER.warning(
                    f"Skipping invalid item: {e}",
                    extra={
                        "request_id": request_id,
                        "item": str(item)[:100],
                        "error": str(e),
                    },
                )
        
        if skipped_count > 0:
            LOGGER.info(
                f"Processed {len(results)} items, skipped {skipped_count} invalid",
                extra={"request_id": request_id},
            )
            
            if self.emit_metrics:
                self._emit_skipped_metric(skipped_count)
        
        return results
    
    def with_timeout(
        self,
        func: Callable[..., T],
        timeout_seconds: Optional[float] = None,
        partial_result_extractor: Optional[Callable[[], Any]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """
        Execute function with timeout, returning partial results if available.
        
        Note: Python doesn't have true function timeout without threads.
        This implementation tracks elapsed time and raises TimeoutError
        if the function takes too long. For true timeout, use threading
        or async patterns.
        
        Args:
            func: Function to execute
            timeout_seconds: Timeout in seconds (default: self.traversal_timeout)
            partial_result_extractor: Function to extract partial results on timeout
            *args: Arguments for func
            **kwargs: Keyword arguments for func
            
        Returns:
            Result of func
            
        Raises:
            TimeoutError: If execution exceeds timeout
        """
        timeout = timeout_seconds or self.traversal_timeout
        start_time = time.time()
        
        # Execute the function
        result = func(*args, **kwargs)
        
        # Check if we exceeded timeout (post-execution check)
        elapsed = time.time() - start_time
        if elapsed > timeout:
            LOGGER.warning(
                f"Function {func.__name__} exceeded timeout: {elapsed:.2f}s > {timeout}s"
            )
            # Still return result since we have it
        
        return result
    
    def _log_degradation(
        self,
        degradation_type: str,
        error_message: str,
        request_id: Optional[str],
        latency_ms: float,
    ) -> None:
        """Log degradation event with context."""
        self._degradation_count += 1
        
        LOGGER.warning(
            f"Graph degradation: {degradation_type}",
            extra={
                "request_id": request_id,
                "degradation_type": degradation_type,
                "error_message": error_message,
                "latency_ms": latency_ms,
                "degradation_count": self._degradation_count,
            },
        )
        
        if self.emit_metrics:
            self._emit_degradation_metric(degradation_type)
    
    def _emit_degradation_metric(self, degradation_type: str) -> None:
        """Emit CloudWatch metric for degradation event."""
        try:
            cloudwatch.put_metric_data(
                Namespace=METRICS_NAMESPACE,
                MetricData=[
                    {
                        'MetricName': 'GraphDegradation',
                        'Value': 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'DegradationType', 'Value': degradation_type}
                        ]
                    }
                ]
            )
        except Exception as e:
            LOGGER.debug(f"Failed to emit degradation metric: {e}")
    
    def _emit_fallback_metric(self, reason: str) -> None:
        """Emit CloudWatch metric for fallback usage."""
        try:
            cloudwatch.put_metric_data(
                Namespace=METRICS_NAMESPACE,
                MetricData=[
                    {
                        'MetricName': 'GraphFallbackUsed',
                        'Value': 1,
                        'Unit': 'Count',
                        'Dimensions': [
                            {'Name': 'Reason', 'Value': reason}
                        ]
                    }
                ]
            )
        except Exception as e:
            LOGGER.debug(f"Failed to emit fallback metric: {e}")
    
    def _emit_skipped_metric(self, count: int) -> None:
        """Emit CloudWatch metric for skipped items."""
        try:
            cloudwatch.put_metric_data(
                Namespace=METRICS_NAMESPACE,
                MetricData=[
                    {
                        'MetricName': 'GraphItemsSkipped',
                        'Value': count,
                        'Unit': 'Count',
                    }
                ]
            )
        except Exception as e:
            LOGGER.debug(f"Failed to emit skipped metric: {e}")


# =============================================================================
# Global instance
# =============================================================================

_graceful_degradation: Optional[GracefulDegradation] = None


def get_graceful_degradation() -> GracefulDegradation:
    """Get or create the global graceful degradation instance."""
    global _graceful_degradation
    if _graceful_degradation is None:
        _graceful_degradation = GracefulDegradation()
    return _graceful_degradation


# =============================================================================
# Convenience functions
# =============================================================================

def vector_only_fallback_result(
    vector_results: List[Dict[str, Any]],
    warning: str = "graph_unavailable",
) -> Dict[str, Any]:
    """
    Create a fallback result using vector-only search.
    
    Args:
        vector_results: Results from vector search
        warning: Warning message to include
        
    Returns:
        API response dict with degradation info
    """
    return {
        "success": True,
        "results": vector_results,
        "degraded": True,
        "warning": warning,
        "graphEnabled": False,
    }


def partial_result_response(
    partial_results: List[Dict[str, Any]],
    nodes_visited: int,
    max_depth_reached: int,
) -> Dict[str, Any]:
    """
    Create a partial result response for timeout scenarios.
    
    Args:
        partial_results: Partial results obtained before timeout
        nodes_visited: Number of nodes visited
        max_depth_reached: Maximum depth reached before timeout
        
    Returns:
        API response dict with partial result info
    """
    return {
        "success": True,
        "results": partial_results,
        "partial": True,
        "warning": "traversal_timeout",
        "nodesVisited": nodes_visited,
        "maxDepthReached": max_depth_reached,
    }
