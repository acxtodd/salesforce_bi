"""
Tests for Graph Builder Metrics module.

Tests CloudWatch metric emission for graph build operations.

**Feature: phase3-graph-enhancement**
**Requirements: 6.1, 6.3**
"""

import os
import sys
import importlib.util

import pytest
from unittest.mock import patch, MagicMock

# Load the module directly from file path to avoid import conflicts with retrieve/graph_metrics.py
_module_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graph_metrics.py")
_spec = importlib.util.spec_from_file_location("graph_builder_metrics", _module_path)
_graph_metrics_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_graph_metrics_module)

# Import from the loaded module
GraphBuildMetrics = _graph_metrics_module.GraphBuildMetrics
MetricUnit = _graph_metrics_module.MetricUnit
get_build_metrics = _graph_metrics_module.get_build_metrics
GRAPH_NAMESPACE = _graph_metrics_module.GRAPH_NAMESPACE


class TestGraphBuildMetrics:
    """Tests for GraphBuildMetrics class."""

    def test_init_enabled(self):
        """Test initialization with metrics enabled."""
        metrics = GraphBuildMetrics(enabled=True)
        assert metrics.enabled is True

    def test_init_disabled(self):
        """Test initialization with metrics disabled."""
        metrics = GraphBuildMetrics(enabled=False)
        assert metrics.enabled is False

    def test_emit_build_latency(self):
        """Test emitting build latency metric."""
        mock_cloudwatch = MagicMock()
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=True)
            metrics.emit_build_latency(75.5, sobject="Account")

            mock_cloudwatch.put_metric_data.assert_called_once()
            call_args = mock_cloudwatch.put_metric_data.call_args
            assert call_args[1]["Namespace"] == GRAPH_NAMESPACE
            metric_data = call_args[1]["MetricData"][0]
            assert metric_data["MetricName"] == "GraphBuildLatency"
            assert metric_data["Value"] == 75.5
            assert metric_data["Unit"] == "Milliseconds"
            dimensions = {d["Name"]: d["Value"] for d in metric_data["Dimensions"]}
            assert dimensions["ObjectType"] == "Account"
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch

    def test_emit_nodes_created(self):
        """Test emitting nodes created metric."""
        mock_cloudwatch = MagicMock()
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=True)
            metrics.emit_nodes_created(15, sobject="Opportunity")

            call_args = mock_cloudwatch.put_metric_data.call_args
            metric_data = call_args[1]["MetricData"][0]
            assert metric_data["MetricName"] == "GraphNodesCreated"
            assert metric_data["Value"] == 15
            assert metric_data["Unit"] == "Count"
            dimensions = {d["Name"]: d["Value"] for d in metric_data["Dimensions"]}
            assert dimensions["ObjectType"] == "Opportunity"
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch

    def test_emit_edges_created(self):
        """Test emitting edges created metric."""
        mock_cloudwatch = MagicMock()
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=True)
            metrics.emit_edges_created(30, sobject="Case")

            call_args = mock_cloudwatch.put_metric_data.call_args
            metric_data = call_args[1]["MetricData"][0]
            assert metric_data["MetricName"] == "GraphEdgesCreated"
            assert metric_data["Value"] == 30
            dimensions = {d["Name"]: d["Value"] for d in metric_data["Dimensions"]}
            assert dimensions["ObjectType"] == "Case"
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch

    def test_emit_build_operation_create(self):
        """Test emitting CREATE operation metric."""
        mock_cloudwatch = MagicMock()
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=True)
            metrics.emit_build_operation("CREATE", sobject="Contact")

            call_args = mock_cloudwatch.put_metric_data.call_args
            metric_data = call_args[1]["MetricData"][0]
            assert metric_data["MetricName"] == "GraphBuildOperations"
            assert metric_data["Value"] == 1
            dimensions = {d["Name"]: d["Value"] for d in metric_data["Dimensions"]}
            assert dimensions["Operation"] == "CREATE"
            assert dimensions["ObjectType"] == "Contact"
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch

    def test_emit_build_operation_update(self):
        """Test emitting UPDATE operation metric."""
        mock_cloudwatch = MagicMock()
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=True)
            metrics.emit_build_operation("UPDATE", sobject="Lead")

            call_args = mock_cloudwatch.put_metric_data.call_args
            metric_data = call_args[1]["MetricData"][0]
            dimensions = {d["Name"]: d["Value"] for d in metric_data["Dimensions"]}
            assert dimensions["Operation"] == "UPDATE"
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch

    def test_emit_build_operation_delete(self):
        """Test emitting DELETE operation metric."""
        mock_cloudwatch = MagicMock()
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=True)
            metrics.emit_build_operation("DELETE", sobject="Account")

            call_args = mock_cloudwatch.put_metric_data.call_args
            metric_data = call_args[1]["MetricData"][0]
            dimensions = {d["Name"]: d["Value"] for d in metric_data["Dimensions"]}
            assert dimensions["Operation"] == "DELETE"
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch

    def test_emit_build_error(self):
        """Test emitting build error metric."""
        mock_cloudwatch = MagicMock()
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=True)
            metrics.emit_build_error("ValidationError", sobject="Account")

            call_args = mock_cloudwatch.put_metric_data.call_args
            metric_data = call_args[1]["MetricData"][0]
            assert metric_data["MetricName"] == "GraphBuildErrors"
            assert metric_data["Value"] == 1
            dimensions = {d["Name"]: d["Value"] for d in metric_data["Dimensions"]}
            assert dimensions["ErrorType"] == "ValidationError"
            assert dimensions["ObjectType"] == "Account"
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch

    def test_emit_records_processed(self):
        """Test emitting records processed metric."""
        mock_cloudwatch = MagicMock()
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=True)
            metrics.emit_records_processed(50)

            call_args = mock_cloudwatch.put_metric_data.call_args
            metric_data = call_args[1]["MetricData"][0]
            assert metric_data["MetricName"] == "GraphRecordsProcessed"
            assert metric_data["Value"] == 50
            assert metric_data["Unit"] == "Count"
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch

    def test_disabled_metrics_no_emit(self):
        """Test that disabled metrics don't emit."""
        mock_cloudwatch = MagicMock()
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=False)
            metrics.emit_build_latency(100.0, "Account")
            metrics.emit_nodes_created(10, "Account")
            metrics.emit_build_error("Error", "Account")

            mock_cloudwatch.put_metric_data.assert_not_called()
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch

    def test_emit_handles_client_error(self):
        """Test that client errors are handled gracefully."""
        from botocore.exceptions import ClientError

        mock_cloudwatch = MagicMock()
        mock_cloudwatch.put_metric_data.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "PutMetricData",
        )
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=True)
            # Should not raise exception
            metrics.emit_build_latency(100.0, "Account")
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch

    def test_emit_handles_generic_exception(self):
        """Test that generic exceptions are handled gracefully."""
        mock_cloudwatch = MagicMock()
        mock_cloudwatch.put_metric_data.side_effect = Exception("Network error")
        original_cloudwatch = _graph_metrics_module.cloudwatch
        _graph_metrics_module.cloudwatch = mock_cloudwatch
        
        try:
            metrics = GraphBuildMetrics(enabled=True)
            # Should not raise exception
            metrics.emit_nodes_created(5, "Account")
        finally:
            _graph_metrics_module.cloudwatch = original_cloudwatch


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_build_metrics_singleton(self):
        """Test that get_build_metrics returns singleton."""
        # Reset singleton
        _graph_metrics_module._build_metrics = None

        metrics1 = get_build_metrics(enabled=True)
        metrics2 = get_build_metrics()

        assert metrics1 is metrics2

    def test_get_build_metrics_creates_new_instance(self):
        """Test that get_build_metrics creates instance when None."""
        _graph_metrics_module._build_metrics = None

        metrics = get_build_metrics(enabled=True)
        assert metrics is not None
        assert isinstance(metrics, GraphBuildMetrics)


class TestMetricUnit:
    """Tests for MetricUnit enum."""

    def test_metric_units(self):
        """Test metric unit values."""
        assert MetricUnit.COUNT.value == "Count"
        assert MetricUnit.MILLISECONDS.value == "Milliseconds"
        assert MetricUnit.PERCENT.value == "Percent"
        assert MetricUnit.NONE.value == "None"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
