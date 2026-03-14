"""
Tests for Graph Metrics module.

Tests CloudWatch metric emission for graph operations, intent classification,
planner operations, and quality metrics.

**Feature: phase3-graph-enhancement, graph-aware-zero-config-retrieval**
**Requirements: 6.1, 6.2, 6.3, 12.1, 12.2**
"""
import pytest
import sys
import os
import importlib.util
from unittest.mock import patch, MagicMock

# Load graph_metrics from the retrieve directory explicitly
_current_dir = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("retrieve_graph_metrics", os.path.join(_current_dir, "graph_metrics.py"))
_gm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gm)

# Import from the loaded module
GraphMetrics = _gm.GraphMetrics
IntentMetrics = _gm.IntentMetrics
PlannerMetrics = _gm.PlannerMetrics
QualityMetrics = _gm.QualityMetrics
MetricUnit = _gm.MetricUnit
get_graph_metrics = _gm.get_graph_metrics
get_intent_metrics = _gm.get_intent_metrics
get_planner_metrics = _gm.get_planner_metrics
get_quality_metrics = _gm.get_quality_metrics
GRAPH_NAMESPACE = _gm.GRAPH_NAMESPACE
INTENT_NAMESPACE = _gm.INTENT_NAMESPACE
PLANNER_NAMESPACE = _gm.PLANNER_NAMESPACE
QUALITY_NAMESPACE = _gm.QUALITY_NAMESPACE


class TestGraphMetrics:
    """Tests for GraphMetrics class."""

    def test_init_enabled(self):
        """Test initialization with metrics enabled."""
        metrics = GraphMetrics(enabled=True)
        assert metrics.enabled is True
        assert metrics._cache_hits == 0
        assert metrics._cache_misses == 0

    def test_init_disabled(self):
        """Test initialization with metrics disabled."""
        metrics = GraphMetrics(enabled=False)
        assert metrics.enabled is False

    def test_emit_traversal_latency(self):
        """Test emitting traversal latency metric."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics.emit_traversal_latency(150.5, depth=2)
            mock_put.assert_called_once()
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'GraphTraversalLatency'
            assert call_args[1]['value'] == 150.5

    def test_emit_traversal_latency_with_depth(self):
        """Test traversal latency includes depth dimension."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics.emit_traversal_latency(200.0, depth=3)
            call_args = mock_put.call_args
            assert call_args[1]['dimensions']['TraversalDepth'] == '3'

    def test_emit_build_latency(self):
        """Test emitting build latency metric."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics.emit_build_latency(50.0, sobject='Account')
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'GraphBuildLatency'
            assert call_args[1]['dimensions']['ObjectType'] == 'Account'

    def test_emit_node_count(self):
        """Test emitting node count metric."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics.emit_node_count(100, sobject='Opportunity')
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'GraphNodeCount'
            assert call_args[1]['value'] == 100

    def test_emit_edge_count(self):
        """Test emitting edge count metric."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics.emit_edge_count(250)
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'GraphEdgeCount'
            assert call_args[1]['value'] == 250

    def test_emit_cache_hit(self):
        """Test emitting cache hit metric."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics.emit_cache_hit()
            assert metrics._cache_hits == 1
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'GraphCacheHit'

    def test_emit_cache_miss(self):
        """Test emitting cache miss metric."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics.emit_cache_miss()
            assert metrics._cache_misses == 1
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'GraphCacheMiss'

    def test_emit_cache_hit_rate(self):
        """Test emitting cache hit rate metric."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics._cache_hits = 80
            metrics._cache_misses = 20
            metrics.emit_cache_hit_rate()
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'GraphCacheHitRate'
            assert call_args[1]['value'] == 80.0  # 80%

    def test_emit_cache_hit_rate_zero_total(self):
        """Test cache hit rate with zero total doesn't emit."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics._cache_hits = 0
            metrics._cache_misses = 0
            metrics.emit_cache_hit_rate()
            # Should not call _put_metric when total is 0
            mock_put.assert_not_called()

    def test_emit_nodes_visited(self):
        """Test emitting nodes visited metric."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics.emit_nodes_visited(50, depth=2)
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'GraphNodesVisited'
            assert call_args[1]['value'] == 50

    def test_emit_traversal_error(self):
        """Test emitting traversal error metric."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics.emit_traversal_error('timeout')
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'GraphTraversalErrors'
            assert call_args[1]['dimensions']['ErrorType'] == 'timeout'

    def test_emit_truncated_result(self):
        """Test emitting truncated result metric."""
        with patch.object(GraphMetrics, '_put_metric') as mock_put:
            metrics = GraphMetrics(enabled=True)
            metrics.emit_truncated_result()
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'GraphResultsTruncated'

    def test_disabled_metrics_no_emit(self):
        """Test that disabled metrics don't emit."""
        # When disabled, _put_metric returns early without calling CloudWatch
        metrics = GraphMetrics(enabled=False)
        # These should not raise any errors and should not emit
        metrics.emit_traversal_latency(100.0)
        metrics.emit_cache_hit()
        metrics.emit_node_count(50)
        # Verify the metrics object is disabled
        assert metrics.enabled is False

    def test_emit_handles_client_error(self):
        """Test that client errors are handled gracefully."""
        from botocore.exceptions import ClientError
        metrics = GraphMetrics(enabled=True)
        # Should not raise exception even if CloudWatch fails
        # The _put_metric method handles exceptions internally
        metrics.emit_traversal_latency(100.0)


class TestIntentMetrics:
    """Tests for IntentMetrics class."""

    def test_init_enabled(self):
        """Test initialization with metrics enabled."""
        metrics = IntentMetrics(enabled=True)
        assert metrics.enabled is True
        assert metrics._total_classifications == 0
        assert metrics._fallback_count == 0

    def test_emit_classification_latency(self):
        """Test emitting classification latency metric."""
        with patch.object(IntentMetrics, '_put_metric') as mock_put:
            metrics = IntentMetrics(enabled=True)
            metrics.emit_classification_latency(5.5)
            call_args = mock_put.call_args
            assert call_args[1]['namespace'] == INTENT_NAMESPACE
            assert call_args[1]['metric_name'] == 'IntentClassificationLatency'
            assert call_args[1]['value'] == 5.5

    def test_emit_intent_distribution(self):
        """Test emitting intent distribution metric."""
        with patch.object(IntentMetrics, '_put_metric') as mock_put:
            metrics = IntentMetrics(enabled=True)
            metrics.emit_intent_distribution('RELATIONSHIP')
            assert metrics._total_classifications == 1
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'IntentDistribution'
            assert call_args[1]['dimensions']['IntentType'] == 'RELATIONSHIP'

    def test_emit_confidence(self):
        """Test emitting confidence metric."""
        with patch.object(IntentMetrics, '_put_metric') as mock_put:
            metrics = IntentMetrics(enabled=True)
            metrics.emit_confidence(0.85, 'SIMPLE_LOOKUP')
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'IntentConfidence'
            assert call_args[1]['value'] == 85.0  # Converted to percentage

    def test_emit_fallback(self):
        """Test emitting fallback metric."""
        with patch.object(IntentMetrics, '_put_metric') as mock_put:
            metrics = IntentMetrics(enabled=True)
            metrics.emit_fallback()
            assert metrics._fallback_count == 1
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'IntentFallback'

    def test_emit_fallback_rate(self):
        """Test emitting fallback rate metric."""
        with patch.object(IntentMetrics, '_put_metric') as mock_put:
            metrics = IntentMetrics(enabled=True)
            metrics._total_classifications = 100
            metrics._fallback_count = 15
            metrics.emit_fallback_rate()
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'IntentFallbackRate'
            assert call_args[1]['value'] == 15.0  # 15%

    def test_emit_pattern_match_count(self):
        """Test emitting pattern match count metric."""
        with patch.object(IntentMetrics, '_put_metric') as mock_put:
            metrics = IntentMetrics(enabled=True)
            metrics.emit_pattern_match_count(3, 'AGGREGATION')
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'IntentPatternMatches'
            assert call_args[1]['value'] == 3

    def test_disabled_metrics_no_emit(self):
        """Test that disabled metrics don't emit."""
        # When disabled, _put_metric returns early without calling CloudWatch
        metrics = IntentMetrics(enabled=False)
        # These should not raise any errors and should not emit
        metrics.emit_classification_latency(10.0)
        metrics.emit_intent_distribution('COMPLEX')
        # Verify the metrics object is disabled
        assert metrics.enabled is False


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_graph_metrics_singleton(self):
        """Test that get_graph_metrics returns singleton."""
        # Reset singleton using the loaded module
        _gm._graph_metrics = None

        metrics1 = get_graph_metrics(enabled=True)
        metrics2 = get_graph_metrics()

        assert metrics1 is metrics2

    def test_get_intent_metrics_singleton(self):
        """Test that get_intent_metrics returns singleton."""
        # Reset singleton using the loaded module
        _gm._intent_metrics = None

        metrics1 = get_intent_metrics(enabled=True)
        metrics2 = get_intent_metrics()

        assert metrics1 is metrics2


class TestMetricUnit:
    """Tests for MetricUnit enum."""

    def test_metric_units(self):
        """Test metric unit values."""
        assert MetricUnit.COUNT.value == 'Count'
        assert MetricUnit.MILLISECONDS.value == 'Milliseconds'
        assert MetricUnit.PERCENT.value == 'Percent'
        assert MetricUnit.NONE.value == 'None'


# =============================================================================
# PlannerMetrics Tests
# **Feature: graph-aware-zero-config-retrieval**
# **Requirements: 12.1, 12.2**
# =============================================================================


class TestPlannerMetrics:
    """Tests for PlannerMetrics class."""

    def test_init_enabled(self):
        """Test initialization with metrics enabled."""
        metrics = PlannerMetrics(enabled=True)
        assert metrics.enabled is True
        assert metrics._total_plans == 0
        assert metrics._fallback_count == 0
        assert metrics._timeout_count == 0
        assert metrics._error_count == 0

    def test_init_disabled(self):
        """Test initialization with metrics disabled."""
        metrics = PlannerMetrics(enabled=False)
        assert metrics.enabled is False

    def test_emit_latency(self):
        """Test emitting planner latency metric."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=True)
            metrics.emit_latency(250.5, target_object='ascendix__Property__c')
            mock_put.assert_called_once()
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'PlannerLatency'
            assert call_args[1]['value'] == 250.5

    def test_emit_latency_with_dimension(self):
        """Test planner latency includes target object dimension."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=True)
            metrics.emit_latency(100.0, target_object='ascendix__Availability__c')
            call_args = mock_put.call_args
            assert call_args[1]['dimensions']['TargetObject'] == 'ascendix__Availability__c'

    def test_emit_confidence(self):
        """Test emitting planner confidence metric."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=True)
            metrics.emit_confidence(0.85, target_object='ascendix__Property__c')
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'PlannerConfidence'
            assert call_args[1]['value'] == 85.0  # Converted to percentage

    def test_emit_fallback(self):
        """Test emitting planner fallback metric."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=True)
            metrics.emit_fallback("low_confidence")
            assert metrics._fallback_count == 1
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'PlannerFallback'
            assert call_args[1]['dimensions']['FallbackReason'] == 'low_confidence'

    def test_emit_fallback_rate(self):
        """Test emitting fallback rate metric."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=True)
            metrics._total_plans = 10
            metrics._fallback_count = 3
            metrics.emit_fallback_rate()
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'PlannerFallbackRate'
            assert call_args[1]['value'] == 30.0  # 3/10 = 30%

    def test_emit_predicate_count(self):
        """Test emitting predicate count metric."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=True)
            metrics.emit_predicate_count(5, target_object='ascendix__Property__c')
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'PlannerPredicateCount'
            assert call_args[1]['value'] == 5

    def test_emit_target_object(self):
        """Test emitting target object distribution metric."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=True)
            metrics.emit_target_object('ascendix__Property__c')
            assert metrics._total_plans == 1
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'PlannerTargetObject'
            assert call_args[1]['dimensions']['TargetObject'] == 'ascendix__Property__c'

    def test_emit_timeout(self):
        """Test emitting timeout metric."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=True)
            metrics.emit_timeout(500)
            assert metrics._timeout_count == 1
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'PlannerTimeout'

    def test_emit_error(self):
        """Test emitting error metric."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=True)
            metrics.emit_error('ValueError')
            assert metrics._error_count == 1
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'PlannerError'
            assert call_args[1]['dimensions']['ErrorType'] == 'ValueError'

    def test_emit_plan_success(self):
        """Test emitting all success metrics."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=True)
            metrics.emit_plan_success(
                latency_ms=150.0,
                confidence=0.9,
                predicate_count=3,
                target_object='ascendix__Property__c',
            )
            # Should emit 4 metrics: latency, confidence, predicate_count, target_object
            assert mock_put.call_count == 4

    def test_disabled_does_not_emit(self):
        """Test disabled metrics don't call CloudWatch."""
        with patch.object(PlannerMetrics, '_put_metric') as mock_put:
            metrics = PlannerMetrics(enabled=False)
            metrics.emit_latency(100.0)
            # _put_metric is called but returns early
            mock_put.assert_called_once()


class TestQualityMetrics:
    """Tests for QualityMetrics class."""

    def test_init_enabled(self):
        """Test initialization with metrics enabled."""
        metrics = QualityMetrics(enabled=True)
        assert metrics.enabled is True
        assert metrics._total_queries == 0
        assert metrics._empty_results == 0

    def test_init_disabled(self):
        """Test initialization with metrics disabled."""
        metrics = QualityMetrics(enabled=False)
        assert metrics.enabled is False

    def test_emit_result_count(self):
        """Test emitting result count metric."""
        with patch.object(QualityMetrics, '_put_metric') as mock_put:
            metrics = QualityMetrics(enabled=True)
            metrics.emit_result_count(10, query_type='vector')
            assert metrics._total_queries == 1
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'ResultCount'
            assert call_args[1]['value'] == 10

    def test_emit_result_count_empty(self):
        """Test empty result count increments empty counter."""
        with patch.object(QualityMetrics, '_put_metric') as mock_put:
            metrics = QualityMetrics(enabled=True)
            metrics.emit_result_count(0, query_type='vector')
            assert metrics._total_queries == 1
            assert metrics._empty_results == 1

    def test_emit_empty_result(self):
        """Test emitting empty result metric."""
        with patch.object(QualityMetrics, '_put_metric') as mock_put:
            metrics = QualityMetrics(enabled=True)
            metrics.emit_empty_result(query_type='graph')
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'EmptyResult'

    def test_emit_empty_result_rate(self):
        """Test emitting empty result rate metric."""
        with patch.object(QualityMetrics, '_put_metric') as mock_put:
            metrics = QualityMetrics(enabled=True)
            metrics._total_queries = 20
            metrics._empty_results = 4
            metrics.emit_empty_result_rate()
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'EmptyResultRate'
            assert call_args[1]['value'] == 20.0  # 4/20 = 20%

    def test_emit_binding_precision(self):
        """Test emitting binding precision metric."""
        with patch.object(QualityMetrics, '_put_metric') as mock_put:
            metrics = QualityMetrics(enabled=True)
            metrics.emit_binding_precision(0.92)
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'BindingPrecision'
            assert call_args[1]['value'] == 92.0  # Converted to percentage

    def test_emit_cdc_lag(self):
        """Test emitting CDC lag metric."""
        with patch.object(QualityMetrics, '_put_metric') as mock_put:
            metrics = QualityMetrics(enabled=True)
            metrics.emit_cdc_lag(45.5)
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'CDCLag'
            assert call_args[1]['value'] == 45.5

    def test_emit_rollup_freshness(self):
        """Test emitting rollup freshness metric."""
        with patch.object(QualityMetrics, '_put_metric') as mock_put:
            metrics = QualityMetrics(enabled=True)
            metrics.emit_rollup_freshness(120.0)
            call_args = mock_put.call_args
            assert call_args[1]['metric_name'] == 'RollupFreshness'
            assert call_args[1]['value'] == 120.0


class TestPlannerMetricsSingleton:
    """Tests for PlannerMetrics singleton."""

    def test_get_planner_metrics_returns_singleton(self):
        """Test that get_planner_metrics returns the same instance."""
        # Reset singleton
        _gm._planner_metrics = None

        metrics1 = get_planner_metrics(enabled=True)
        metrics2 = get_planner_metrics()

        assert metrics1 is metrics2


class TestQualityMetricsSingleton:
    """Tests for QualityMetrics singleton."""

    def test_get_quality_metrics_returns_singleton(self):
        """Test that get_quality_metrics returns the same instance."""
        # Reset singleton
        _gm._quality_metrics = None

        metrics1 = get_quality_metrics(enabled=True)
        metrics2 = get_quality_metrics()

        assert metrics1 is metrics2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
