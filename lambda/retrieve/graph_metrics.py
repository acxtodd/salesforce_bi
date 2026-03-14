"""
CloudWatch Metrics for Graph Operations.

Provides centralized metric emission for graph traversal, intent classification,
planner operations, and cache operations.

**Feature: phase3-graph-enhancement, graph-aware-zero-config-retrieval**
**Requirements: 6.1, 6.2, 6.3, 12.1, 12.2**
"""
import os
import time
import logging
from typing import Dict, Any, Optional
from enum import Enum
from functools import wraps

import boto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Initialize CloudWatch client
cloudwatch = boto3.client('cloudwatch')

# Metric namespace
GRAPH_NAMESPACE = 'SalesforceAISearch/Graph'
INTENT_NAMESPACE = 'SalesforceAISearch/Intent'
PLANNER_NAMESPACE = 'SalesforceAISearch/Planner'
QUALITY_NAMESPACE = 'SalesforceAISearch/Quality'


class MetricUnit(Enum):
    """CloudWatch metric units."""
    COUNT = 'Count'
    MILLISECONDS = 'Milliseconds'
    PERCENT = 'Percent'
    NONE = 'None'


class GraphMetrics:
    """
    CloudWatch metrics emitter for graph operations.
    
    **Requirements: 6.1, 6.3**
    
    Metrics emitted:
    - GraphTraversalLatency (p50, p95, p99)
    - GraphNodeCount (gauge)
    - GraphEdgeCount (gauge)
    - GraphCacheHitRate (percentage)
    - GraphBuildLatency (p50, p95)
    - GraphTraversalDepth (count)
    - GraphNodesVisited (count)
    - GraphTraversalErrors (count)
    """
    
    def __init__(self, enabled: bool = True):
        """
        Initialize GraphMetrics.
        
        Args:
            enabled: Whether to emit metrics (can be disabled for testing)
        """
        self.enabled = enabled
        self._cache_hits = 0
        self._cache_misses = 0
    
    def emit_traversal_latency(self, latency_ms: float, depth: int = 2) -> None:
        """
        Emit graph traversal latency metric.
        
        Args:
            latency_ms: Traversal latency in milliseconds
            depth: Traversal depth (1-3)
        """
        self._put_metric(
            namespace=GRAPH_NAMESPACE,
            metric_name='GraphTraversalLatency',
            value=latency_ms,
            unit=MetricUnit.MILLISECONDS,
            dimensions={'TraversalDepth': str(depth)}
        )
    
    def emit_build_latency(self, latency_ms: float, sobject: str) -> None:
        """
        Emit graph build latency metric.
        
        Args:
            latency_ms: Build latency in milliseconds
            sobject: Object type being built
        """
        self._put_metric(
            namespace=GRAPH_NAMESPACE,
            metric_name='GraphBuildLatency',
            value=latency_ms,
            unit=MetricUnit.MILLISECONDS,
            dimensions={'ObjectType': sobject}
        )
    
    def emit_node_count(self, count: int, sobject: Optional[str] = None) -> None:
        """
        Emit graph node count metric.
        
        Args:
            count: Number of nodes
            sobject: Optional object type filter
        """
        dimensions = {}
        if sobject:
            dimensions['ObjectType'] = sobject
        
        self._put_metric(
            namespace=GRAPH_NAMESPACE,
            metric_name='GraphNodeCount',
            value=count,
            unit=MetricUnit.COUNT,
            dimensions=dimensions
        )
    
    def emit_edge_count(self, count: int, relationship_type: Optional[str] = None) -> None:
        """
        Emit graph edge count metric.
        
        Args:
            count: Number of edges
            relationship_type: Optional relationship type filter
        """
        dimensions = {}
        if relationship_type:
            dimensions['RelationshipType'] = relationship_type
        
        self._put_metric(
            namespace=GRAPH_NAMESPACE,
            metric_name='GraphEdgeCount',
            value=count,
            unit=MetricUnit.COUNT,
            dimensions=dimensions
        )
    
    def emit_cache_hit(self) -> None:
        """Record a cache hit."""
        self._cache_hits += 1
        self._put_metric(
            namespace=GRAPH_NAMESPACE,
            metric_name='GraphCacheHit',
            value=1,
            unit=MetricUnit.COUNT
        )
    
    def emit_cache_miss(self) -> None:
        """Record a cache miss."""
        self._cache_misses += 1
        self._put_metric(
            namespace=GRAPH_NAMESPACE,
            metric_name='GraphCacheMiss',
            value=1,
            unit=MetricUnit.COUNT
        )
    
    def emit_cache_hit_rate(self) -> None:
        """Emit cache hit rate as percentage."""
        total = self._cache_hits + self._cache_misses
        if total > 0:
            hit_rate = (self._cache_hits / total) * 100
            self._put_metric(
                namespace=GRAPH_NAMESPACE,
                metric_name='GraphCacheHitRate',
                value=hit_rate,
                unit=MetricUnit.PERCENT
            )
    
    def emit_nodes_visited(self, count: int, depth: int = 2) -> None:
        """
        Emit nodes visited during traversal.
        
        Args:
            count: Number of nodes visited
            depth: Traversal depth
        """
        self._put_metric(
            namespace=GRAPH_NAMESPACE,
            metric_name='GraphNodesVisited',
            value=count,
            unit=MetricUnit.COUNT,
            dimensions={'TraversalDepth': str(depth)}
        )
    
    def emit_traversal_error(self, error_type: str) -> None:
        """
        Emit graph traversal error metric.
        
        Args:
            error_type: Type of error (e.g., 'timeout', 'auth_failure', 'db_error')
        """
        self._put_metric(
            namespace=GRAPH_NAMESPACE,
            metric_name='GraphTraversalErrors',
            value=1,
            unit=MetricUnit.COUNT,
            dimensions={'ErrorType': error_type}
        )
    
    def emit_truncated_result(self) -> None:
        """Emit metric when results are truncated due to limits."""
        self._put_metric(
            namespace=GRAPH_NAMESPACE,
            metric_name='GraphResultsTruncated',
            value=1,
            unit=MetricUnit.COUNT
        )
    
    def _put_metric(
        self,
        namespace: str,
        metric_name: str,
        value: float,
        unit: MetricUnit,
        dimensions: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Put metric to CloudWatch.
        
        Args:
            namespace: Metric namespace
            metric_name: Name of the metric
            value: Metric value
            unit: Metric unit
            dimensions: Optional dimensions
        """
        if not self.enabled:
            return
        
        try:
            metric_data = {
                'MetricName': metric_name,
                'Value': value,
                'Unit': unit.value,
            }
            
            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': k, 'Value': v} for k, v in dimensions.items()
                ]
            
            cloudwatch.put_metric_data(
                Namespace=namespace,
                MetricData=[metric_data]
            )
        except ClientError as e:
            LOGGER.debug(f"Failed to emit metric {metric_name}: {e}")
        except Exception as e:
            LOGGER.debug(f"Unexpected error emitting metric {metric_name}: {e}")


class IntentMetrics:
    """
    CloudWatch metrics emitter for intent classification.
    
    **Requirements: 6.2**
    
    Metrics emitted:
    - IntentClassificationLatency (p50, p95)
    - IntentDistribution (count by type)
    - IntentConfidence (average)
    - IntentFallbackRate (percentage)
    """
    
    def __init__(self, enabled: bool = True):
        """
        Initialize IntentMetrics.
        
        Args:
            enabled: Whether to emit metrics
        """
        self.enabled = enabled
        self._total_classifications = 0
        self._fallback_count = 0
    
    def emit_classification_latency(self, latency_ms: float) -> None:
        """
        Emit intent classification latency metric.
        
        Args:
            latency_ms: Classification latency in milliseconds
        """
        self._put_metric(
            namespace=INTENT_NAMESPACE,
            metric_name='IntentClassificationLatency',
            value=latency_ms,
            unit=MetricUnit.MILLISECONDS
        )
    
    def emit_intent_distribution(self, intent_type: str) -> None:
        """
        Emit intent type distribution metric.
        
        Args:
            intent_type: The classified intent type
        """
        self._total_classifications += 1
        self._put_metric(
            namespace=INTENT_NAMESPACE,
            metric_name='IntentDistribution',
            value=1,
            unit=MetricUnit.COUNT,
            dimensions={'IntentType': intent_type}
        )
    
    def emit_confidence(self, confidence: float, intent_type: str) -> None:
        """
        Emit intent confidence metric.
        
        Args:
            confidence: Confidence score (0.0 to 1.0)
            intent_type: The classified intent type
        """
        self._put_metric(
            namespace=INTENT_NAMESPACE,
            metric_name='IntentConfidence',
            value=confidence * 100,  # Convert to percentage
            unit=MetricUnit.PERCENT,
            dimensions={'IntentType': intent_type}
        )
    
    def emit_fallback(self) -> None:
        """Record a fallback to default intent."""
        self._fallback_count += 1
        self._put_metric(
            namespace=INTENT_NAMESPACE,
            metric_name='IntentFallback',
            value=1,
            unit=MetricUnit.COUNT
        )
    
    def emit_fallback_rate(self) -> None:
        """Emit fallback rate as percentage."""
        if self._total_classifications > 0:
            fallback_rate = (self._fallback_count / self._total_classifications) * 100
            self._put_metric(
                namespace=INTENT_NAMESPACE,
                metric_name='IntentFallbackRate',
                value=fallback_rate,
                unit=MetricUnit.PERCENT
            )
    
    def emit_pattern_match_count(self, count: int, intent_type: str) -> None:
        """
        Emit count of patterns matched for classification.
        
        Args:
            count: Number of patterns matched
            intent_type: The classified intent type
        """
        self._put_metric(
            namespace=INTENT_NAMESPACE,
            metric_name='IntentPatternMatches',
            value=count,
            unit=MetricUnit.COUNT,
            dimensions={'IntentType': intent_type}
        )
    
    def _put_metric(
        self,
        namespace: str,
        metric_name: str,
        value: float,
        unit: MetricUnit,
        dimensions: Optional[Dict[str, str]] = None
    ) -> None:
        """Put metric to CloudWatch."""
        if not self.enabled:
            return

        try:
            metric_data = {
                'MetricName': metric_name,
                'Value': value,
                'Unit': unit.value,
            }

            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': k, 'Value': v} for k, v in dimensions.items()
                ]

            cloudwatch.put_metric_data(
                Namespace=namespace,
                MetricData=[metric_data]
            )
        except ClientError as e:
            LOGGER.debug(f"Failed to emit metric {metric_name}: {e}")
        except Exception as e:
            LOGGER.debug(f"Unexpected error emitting metric {metric_name}: {e}")


class PlannerMetrics:
    """
    CloudWatch metrics emitter for planner operations.

    **Feature: graph-aware-zero-config-retrieval**
    **Requirements: 12.1, 12.2**

    Metrics emitted:
    - PlannerLatency (p50, p95, p99)
    - PlannerConfidence (average)
    - PlannerFallbackRate (percentage)
    - PlannerPredicateCount (count)
    - PlannerTargetObjectDistribution (count by object)
    - PlannerTimeoutCount (count)
    - PlannerErrorCount (count)
    """

    def __init__(self, enabled: bool = True):
        """
        Initialize PlannerMetrics.

        Args:
            enabled: Whether to emit metrics (can be disabled for testing)
        """
        self.enabled = enabled
        self._total_plans = 0
        self._fallback_count = 0
        self._timeout_count = 0
        self._error_count = 0

    def emit_latency(
        self,
        latency_ms: float,
        target_object: Optional[str] = None,
    ) -> None:
        """
        Emit planner latency metric.

        **Requirements: 12.1**

        Args:
            latency_ms: Planning latency in milliseconds
            target_object: Target object identified by planner
        """
        dimensions = {}
        if target_object:
            dimensions['TargetObject'] = target_object

        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='PlannerLatency',
            value=latency_ms,
            unit=MetricUnit.MILLISECONDS,
            dimensions=dimensions if dimensions else None,
        )

    def emit_confidence(
        self,
        confidence: float,
        target_object: Optional[str] = None,
    ) -> None:
        """
        Emit planner confidence metric.

        **Requirements: 12.1**

        Args:
            confidence: Confidence score (0.0 to 1.0)
            target_object: Target object identified by planner
        """
        dimensions = {}
        if target_object:
            dimensions['TargetObject'] = target_object

        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='PlannerConfidence',
            value=confidence * 100,  # Convert to percentage
            unit=MetricUnit.PERCENT,
            dimensions=dimensions if dimensions else None,
        )

    def emit_fallback(self, reason: str) -> None:
        """
        Record a planner fallback.

        **Requirements: 12.2**

        Args:
            reason: Reason for fallback (timeout, low_confidence, error)
        """
        self._fallback_count += 1
        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='PlannerFallback',
            value=1,
            unit=MetricUnit.COUNT,
            dimensions={'FallbackReason': reason},
        )

    def emit_fallback_rate(self) -> None:
        """
        Emit fallback rate as percentage.

        **Requirements: 12.2**
        """
        if self._total_plans > 0:
            fallback_rate = (self._fallback_count / self._total_plans) * 100
            self._put_metric(
                namespace=PLANNER_NAMESPACE,
                metric_name='PlannerFallbackRate',
                value=fallback_rate,
                unit=MetricUnit.PERCENT,
            )

    def emit_predicate_count(
        self,
        count: int,
        target_object: Optional[str] = None,
    ) -> None:
        """
        Emit count of predicates extracted by planner.

        Args:
            count: Number of predicates
            target_object: Target object identified by planner
        """
        dimensions = {}
        if target_object:
            dimensions['TargetObject'] = target_object

        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='PlannerPredicateCount',
            value=count,
            unit=MetricUnit.COUNT,
            dimensions=dimensions if dimensions else None,
        )

    def emit_target_object(self, target_object: str) -> None:
        """
        Emit target object distribution metric.

        Args:
            target_object: Target object identified by planner
        """
        self._total_plans += 1
        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='PlannerTargetObject',
            value=1,
            unit=MetricUnit.COUNT,
            dimensions={'TargetObject': target_object},
        )

    def emit_timeout(self, timeout_ms: int) -> None:
        """
        Record a planner timeout.

        Args:
            timeout_ms: Timeout value in milliseconds
        """
        self._timeout_count += 1
        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='PlannerTimeout',
            value=1,
            unit=MetricUnit.COUNT,
            dimensions={'TimeoutMs': str(timeout_ms)},
        )

    def emit_error(self, error_type: str) -> None:
        """
        Record a planner error.

        Args:
            error_type: Type of error
        """
        self._error_count += 1
        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='PlannerError',
            value=1,
            unit=MetricUnit.COUNT,
            dimensions={'ErrorType': error_type},
        )

    def emit_plan_success(
        self,
        latency_ms: float,
        confidence: float,
        predicate_count: int,
        target_object: str,
    ) -> None:
        """
        Emit all metrics for a successful plan in a single call.

        Args:
            latency_ms: Planning latency in milliseconds
            confidence: Confidence score (0.0 to 1.0)
            predicate_count: Number of predicates extracted
            target_object: Target object identified
        """
        self.emit_latency(latency_ms, target_object)
        self.emit_confidence(confidence, target_object)
        self.emit_predicate_count(predicate_count, target_object)
        self.emit_target_object(target_object)

    def emit_shadow_execution(
        self,
        latency_ms: float,
        confidence: float,
        predicate_count: int,
        target_object: str,
        would_use: bool,
        query_hash: str,
    ) -> None:
        """
        Emit metrics for shadow mode execution.

        **Task: 28.1 - Shadow Logging for Canary Deployment**
        """
        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='ShadowPlannerLatency',
            value=latency_ms,
            unit=MetricUnit.MILLISECONDS,
            dimensions={'Mode': 'shadow'},
        )
        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='ShadowPlannerConfidence',
            value=confidence * 100,
            unit=MetricUnit.PERCENT,
            dimensions={'TargetObject': target_object or 'unknown'},
        )
        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='ShadowPlannerWouldUse',
            value=1 if would_use else 0,
            unit=MetricUnit.COUNT,
            dimensions={'WouldUse': str(would_use)},
        )

    def emit_shadow_fallback(self, reason: str) -> None:
        """Record a shadow mode planner fallback."""
        self._put_metric(
            namespace=PLANNER_NAMESPACE,
            metric_name='ShadowPlannerFallback',
            value=1,
            unit=MetricUnit.COUNT,
            dimensions={'FallbackReason': reason, 'Mode': 'shadow'},
        )

    def _put_metric(
        self,
        namespace: str,
        metric_name: str,
        value: float,
        unit: MetricUnit,
        dimensions: Optional[Dict[str, str]] = None,
    ) -> None:
        """Put metric to CloudWatch."""
        if not self.enabled:
            return

        try:
            metric_data = {
                'MetricName': metric_name,
                'Value': value,
                'Unit': unit.value,
            }

            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': k, 'Value': v} for k, v in dimensions.items()
                ]

            cloudwatch.put_metric_data(
                Namespace=namespace,
                MetricData=[metric_data],
            )
        except ClientError as e:
            LOGGER.debug(f"Failed to emit metric {metric_name}: {e}")
        except Exception as e:
            LOGGER.debug(f"Unexpected error emitting metric {metric_name}: {e}")


class QualityMetrics:
    """
    CloudWatch metrics emitter for retrieval quality.

    **Feature: graph-aware-zero-config-retrieval**
    **Requirements: 12.1, 12.2**

    Metrics emitted:
    - EmptyResultRate (percentage)
    - BindingPrecision (percentage)
    - CDCLag (seconds)
    - RollupFreshness (seconds)
    - ResultCount (count)
    """

    def __init__(self, enabled: bool = True):
        """
        Initialize QualityMetrics.

        Args:
            enabled: Whether to emit metrics
        """
        self.enabled = enabled
        self._total_queries = 0
        self._empty_results = 0

    def emit_result_count(
        self,
        count: int,
        query_type: Optional[str] = None,
    ) -> None:
        """
        Emit result count metric.

        Args:
            count: Number of results returned
            query_type: Optional query type (vector, graph, aggregation)
        """
        self._total_queries += 1
        if count == 0:
            self._empty_results += 1

        dimensions = {}
        if query_type:
            dimensions['QueryType'] = query_type

        self._put_metric(
            namespace=QUALITY_NAMESPACE,
            metric_name='ResultCount',
            value=count,
            unit=MetricUnit.COUNT,
            dimensions=dimensions if dimensions else None,
        )

    def emit_empty_result(self, query_type: Optional[str] = None) -> None:
        """
        Record an empty result.

        Args:
            query_type: Optional query type
        """
        dimensions = {}
        if query_type:
            dimensions['QueryType'] = query_type

        self._put_metric(
            namespace=QUALITY_NAMESPACE,
            metric_name='EmptyResult',
            value=1,
            unit=MetricUnit.COUNT,
            dimensions=dimensions if dimensions else None,
        )

    def emit_empty_result_rate(self) -> None:
        """
        Emit empty result rate as percentage.

        **Requirements: 12.2**
        """
        if self._total_queries > 0:
            empty_rate = (self._empty_results / self._total_queries) * 100
            self._put_metric(
                namespace=QUALITY_NAMESPACE,
                metric_name='EmptyResultRate',
                value=empty_rate,
                unit=MetricUnit.PERCENT,
            )

    def emit_binding_precision(self, precision: float) -> None:
        """
        Emit binding precision metric.

        **Requirements: 12.1**

        Args:
            precision: Precision score (0.0 to 1.0)
        """
        self._put_metric(
            namespace=QUALITY_NAMESPACE,
            metric_name='BindingPrecision',
            value=precision * 100,  # Convert to percentage
            unit=MetricUnit.PERCENT,
        )

    def emit_cdc_lag(self, lag_seconds: float) -> None:
        """
        Emit CDC lag metric.

        **Requirements: 12.2**

        Args:
            lag_seconds: CDC processing lag in seconds
        """
        self._put_metric(
            namespace=QUALITY_NAMESPACE,
            metric_name='CDCLag',
            value=lag_seconds,
            unit=MetricUnit.NONE,  # Seconds, but CloudWatch doesn't have a seconds unit
        )

    def emit_rollup_freshness(self, freshness_seconds: float) -> None:
        """
        Emit rollup freshness metric.

        **Requirements: 12.2**

        Args:
            freshness_seconds: Time since last rollup in seconds
        """
        self._put_metric(
            namespace=QUALITY_NAMESPACE,
            metric_name='RollupFreshness',
            value=freshness_seconds,
            unit=MetricUnit.NONE,  # Seconds
        )

    def _put_metric(
        self,
        namespace: str,
        metric_name: str,
        value: float,
        unit: MetricUnit,
        dimensions: Optional[Dict[str, str]] = None,
    ) -> None:
        """Put metric to CloudWatch."""
        if not self.enabled:
            return

        try:
            metric_data = {
                'MetricName': metric_name,
                'Value': value,
                'Unit': unit.value,
            }

            if dimensions:
                metric_data['Dimensions'] = [
                    {'Name': k, 'Value': v} for k, v in dimensions.items()
                ]

            cloudwatch.put_metric_data(
                Namespace=namespace,
                MetricData=[metric_data],
            )
        except ClientError as e:
            LOGGER.debug(f"Failed to emit metric {metric_name}: {e}")
        except Exception as e:
            LOGGER.debug(f"Unexpected error emitting metric {metric_name}: {e}")


# Decorator for timing functions
def timed_metric(metric_emitter, metric_method: str):
    """
    Decorator to automatically emit timing metrics.
    
    Args:
        metric_emitter: GraphMetrics or IntentMetrics instance
        metric_method: Method name to call on emitter (e.g., 'emit_traversal_latency')
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                latency_ms = (time.time() - start_time) * 1000
                method = getattr(metric_emitter, metric_method, None)
                if method:
                    method(latency_ms)
        return wrapper
    return decorator


# Module-level singleton instances
_graph_metrics: Optional[GraphMetrics] = None
_intent_metrics: Optional[IntentMetrics] = None
_planner_metrics: Optional[PlannerMetrics] = None
_quality_metrics: Optional[QualityMetrics] = None


def get_graph_metrics(enabled: bool = True) -> GraphMetrics:
    """Get or create the GraphMetrics singleton."""
    global _graph_metrics
    if _graph_metrics is None:
        _graph_metrics = GraphMetrics(enabled=enabled)
    return _graph_metrics


def get_intent_metrics(enabled: bool = True) -> IntentMetrics:
    """Get or create the IntentMetrics singleton."""
    global _intent_metrics
    if _intent_metrics is None:
        _intent_metrics = IntentMetrics(enabled=enabled)
    return _intent_metrics


def get_planner_metrics(enabled: bool = True) -> PlannerMetrics:
    """
    Get or create the PlannerMetrics singleton.

    **Feature: graph-aware-zero-config-retrieval**
    **Requirements: 12.1**
    """
    global _planner_metrics
    if _planner_metrics is None:
        _planner_metrics = PlannerMetrics(enabled=enabled)
    return _planner_metrics


def get_quality_metrics(enabled: bool = True) -> QualityMetrics:
    """
    Get or create the QualityMetrics singleton.

    **Feature: graph-aware-zero-config-retrieval**
    **Requirements: 12.1**
    """
    global _quality_metrics
    if _quality_metrics is None:
        _quality_metrics = QualityMetrics(enabled=enabled)
    return _quality_metrics
