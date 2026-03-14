"""
CloudWatch Metrics for Graph Builder Operations.

Provides metric emission for graph building operations during ingestion.

**Feature: phase3-graph-enhancement**
**Requirements: 6.1, 6.3**
"""
import os
import logging
from typing import Dict, Any, Optional
from enum import Enum

import boto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Initialize CloudWatch client
cloudwatch = boto3.client('cloudwatch')

# Metric namespace
GRAPH_NAMESPACE = 'SalesforceAISearch/Graph'


class MetricUnit(Enum):
    """CloudWatch metric units."""
    COUNT = 'Count'
    MILLISECONDS = 'Milliseconds'
    PERCENT = 'Percent'
    NONE = 'None'


class GraphBuildMetrics:
    """
    CloudWatch metrics emitter for graph build operations.
    
    **Requirements: 6.1, 6.3**
    
    Metrics emitted:
    - GraphBuildLatency (p50, p95)
    - GraphNodesCreated (count)
    - GraphEdgesCreated (count)
    - GraphBuildErrors (count)
    - GraphBuildOperations (count by operation type)
    """
    
    def __init__(self, enabled: bool = True):
        """
        Initialize GraphBuildMetrics.
        
        Args:
            enabled: Whether to emit metrics (can be disabled for testing)
        """
        self.enabled = enabled
    
    def emit_build_latency(self, latency_ms: float, sobject: str) -> None:
        """
        Emit graph build latency metric.
        
        Args:
            latency_ms: Build latency in milliseconds
            sobject: Object type being built
        """
        self._put_metric(
            metric_name='GraphBuildLatency',
            value=latency_ms,
            unit=MetricUnit.MILLISECONDS,
            dimensions={'ObjectType': sobject}
        )
    
    def emit_nodes_created(self, count: int, sobject: str) -> None:
        """
        Emit nodes created metric.
        
        Args:
            count: Number of nodes created
            sobject: Object type
        """
        self._put_metric(
            metric_name='GraphNodesCreated',
            value=count,
            unit=MetricUnit.COUNT,
            dimensions={'ObjectType': sobject}
        )
    
    def emit_edges_created(self, count: int, sobject: str) -> None:
        """
        Emit edges created metric.
        
        Args:
            count: Number of edges created
            sobject: Object type
        """
        self._put_metric(
            metric_name='GraphEdgesCreated',
            value=count,
            unit=MetricUnit.COUNT,
            dimensions={'ObjectType': sobject}
        )
    
    def emit_build_operation(self, operation: str, sobject: str) -> None:
        """
        Emit build operation metric.
        
        Args:
            operation: Operation type (CREATE, UPDATE, DELETE)
            sobject: Object type
        """
        self._put_metric(
            metric_name='GraphBuildOperations',
            value=1,
            unit=MetricUnit.COUNT,
            dimensions={'Operation': operation, 'ObjectType': sobject}
        )
    
    def emit_build_error(self, error_type: str, sobject: str) -> None:
        """
        Emit graph build error metric.
        
        Args:
            error_type: Type of error
            sobject: Object type
        """
        self._put_metric(
            metric_name='GraphBuildErrors',
            value=1,
            unit=MetricUnit.COUNT,
            dimensions={'ErrorType': error_type, 'ObjectType': sobject}
        )
    
    def emit_records_processed(self, count: int) -> None:
        """
        Emit records processed metric.
        
        Args:
            count: Number of records processed
        """
        self._put_metric(
            metric_name='GraphRecordsProcessed',
            value=count,
            unit=MetricUnit.COUNT
        )
    
    def _put_metric(
        self,
        metric_name: str,
        value: float,
        unit: MetricUnit,
        dimensions: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Put metric to CloudWatch.
        
        Args:
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
                Namespace=GRAPH_NAMESPACE,
                MetricData=[metric_data]
            )
        except ClientError as e:
            LOGGER.debug(f"Failed to emit metric {metric_name}: {e}")
        except Exception as e:
            LOGGER.debug(f"Unexpected error emitting metric {metric_name}: {e}")


# Module-level singleton
_build_metrics: Optional[GraphBuildMetrics] = None


def get_build_metrics(enabled: bool = True) -> GraphBuildMetrics:
    """Get or create the GraphBuildMetrics singleton."""
    global _build_metrics
    if _build_metrics is None:
        _build_metrics = GraphBuildMetrics(enabled=enabled)
    return _build_metrics
