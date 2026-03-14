"""
CloudWatch Metrics Emitter for Schema Drift.

Emits schema drift metrics to CloudWatch with cost-conscious batching.

**Feature: schema-drift-monitoring**
**Task: 39.1**
"""
import os
from typing import Dict, List, Any
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError

from coverage import DriftResult


# CloudWatch namespace for schema drift metrics
METRICS_NAMESPACE = 'SalesforceAISearch/SchemaDrift'

# Maximum metrics per PutMetricData call (AWS limit is 1000)
MAX_METRICS_PER_BATCH = 1000

# Initialize CloudWatch client
cloudwatch = boto3.client('cloudwatch')


class MetricsEmitter:
    """
    Emit schema drift metrics to CloudWatch.

    Uses batch PutMetricData calls for cost efficiency.
    """

    def __init__(self, namespace: str = METRICS_NAMESPACE):
        """
        Initialize metrics emitter.

        Args:
            namespace: CloudWatch namespace for metrics
        """
        self.namespace = namespace

    def emit_drift_metrics(self, results: Dict[str, DriftResult]) -> bool:
        """
        Emit all drift metrics for all objects in batch.

        Args:
            results: Dict mapping object name to DriftResult

        Returns:
            True if all metrics emitted successfully, False otherwise
        """
        if not results:
            print("No drift results to emit")
            return True

        metric_data = []
        timestamp = datetime.now(timezone.utc)

        for obj_name, drift in results.items():
            # Add per-object metrics
            object_metrics = self._build_object_metrics(obj_name, drift, timestamp)
            metric_data.extend(object_metrics)

        # Add aggregate metrics
        aggregate_metrics = self._build_aggregate_metrics(results, timestamp)
        metric_data.extend(aggregate_metrics)

        # Emit in batches
        return self._emit_batched(metric_data)

    def _build_object_metrics(
        self,
        obj_name: str,
        drift: DriftResult,
        timestamp: datetime
    ) -> List[Dict[str, Any]]:
        """
        Build CloudWatch metric data for a single object.

        Args:
            obj_name: Object API name
            drift: DriftResult for this object
            timestamp: Metric timestamp

        Returns:
            List of metric data dictionaries
        """
        dimensions = [{'Name': 'ObjectName', 'Value': obj_name}]

        metrics = [
            # Field counts
            {
                'MetricName': 'SFFieldCount',
                'Dimensions': dimensions,
                'Timestamp': timestamp,
                'Value': drift.sf_field_count,
                'Unit': 'Count',
            },
            {
                'MetricName': 'CacheFieldCount',
                'Dimensions': dimensions,
                'Timestamp': timestamp,
                'Value': drift.cache_field_count,
                'Unit': 'Count',
            },
            # Coverage percentages
            {
                'MetricName': 'FilterableCoverage',
                'Dimensions': dimensions,
                'Timestamp': timestamp,
                'Value': drift.filterable_coverage,
                'Unit': 'Percent',
            },
            {
                'MetricName': 'RelationshipCoverage',
                'Dimensions': dimensions,
                'Timestamp': timestamp,
                'Value': drift.relationship_coverage,
                'Unit': 'Percent',
            },
            {
                'MetricName': 'NumericCoverage',
                'Dimensions': dimensions,
                'Timestamp': timestamp,
                'Value': drift.numeric_coverage,
                'Unit': 'Percent',
            },
            {
                'MetricName': 'DateCoverage',
                'Dimensions': dimensions,
                'Timestamp': timestamp,
                'Value': drift.date_coverage,
                'Unit': 'Percent',
            },
            # Drift indicators
            {
                'MetricName': 'FieldsInCacheNotSF',
                'Dimensions': dimensions,
                'Timestamp': timestamp,
                'Value': len(drift.fields_in_cache_not_sf),
                'Unit': 'Count',
            },
            {
                'MetricName': 'FieldsInSFNotCache',
                'Dimensions': dimensions,
                'Timestamp': timestamp,
                'Value': len(drift.fields_in_sf_not_cache),
                'Unit': 'Count',
            },
            # Cache freshness
            {
                'MetricName': 'CacheAgeHours',
                'Dimensions': dimensions,
                'Timestamp': timestamp,
                'Value': max(0, drift.cache_age_hours),  # Clamp negative values
                'Unit': 'Count',  # Hours as count
            },
            # Drift flag (1 = drift detected, 0 = no drift)
            {
                'MetricName': 'DriftDetected',
                'Dimensions': dimensions,
                'Timestamp': timestamp,
                'Value': 1 if drift.has_drift else 0,
                'Unit': 'Count',
            },
        ]

        return metrics

    def _build_aggregate_metrics(
        self,
        results: Dict[str, DriftResult],
        timestamp: datetime
    ) -> List[Dict[str, Any]]:
        """
        Build aggregate metrics across all objects.

        Args:
            results: Dict mapping object name to DriftResult
            timestamp: Metric timestamp

        Returns:
            List of metric data dictionaries
        """
        # Calculate aggregates
        total_objects = len(results)
        objects_with_drift = sum(1 for r in results.values() if r.has_drift)
        total_fake_fields = sum(len(r.fields_in_cache_not_sf) for r in results.values())
        total_missing_fields = sum(len(r.fields_in_sf_not_cache) for r in results.values())

        # Average coverages
        # IMPORTANT: Empty cache = 0% coverage, not 100%
        # This ensures the coverage alarm fires when cache is empty
        if results:
            avg_filterable = sum(r.filterable_coverage for r in results.values()) / len(results)
            avg_relationship = sum(r.relationship_coverage for r in results.values()) / len(results)
        else:
            # Empty cache is a failure state - report 0% coverage
            avg_filterable = 0.0
            avg_relationship = 0.0

        # Detect empty cache condition
        empty_cache = 1 if total_objects == 0 else 0

        metrics = [
            {
                'MetricName': 'TotalObjectsCovered',
                'Timestamp': timestamp,
                'Value': total_objects,
                'Unit': 'Count',
            },
            {
                'MetricName': 'ObjectsWithDrift',
                'Timestamp': timestamp,
                'Value': objects_with_drift,
                'Unit': 'Count',
            },
            {
                'MetricName': 'TotalFakeFields',
                'Timestamp': timestamp,
                'Value': total_fake_fields,
                'Unit': 'Count',
            },
            {
                'MetricName': 'TotalMissingFields',
                'Timestamp': timestamp,
                'Value': total_missing_fields,
                'Unit': 'Count',
            },
            {
                'MetricName': 'AvgFilterableCoverage',
                'Timestamp': timestamp,
                'Value': avg_filterable,
                'Unit': 'Percent',
            },
            {
                'MetricName': 'AvgRelationshipCoverage',
                'Timestamp': timestamp,
                'Value': avg_relationship,
                'Unit': 'Percent',
            },
            {
                'MetricName': 'EmptyCacheDetected',
                'Timestamp': timestamp,
                'Value': empty_cache,
                'Unit': 'Count',
            },
        ]

        return metrics

    def _emit_batched(self, metric_data: List[Dict[str, Any]]) -> bool:
        """
        Emit metrics in batches to stay under AWS limits.

        Args:
            metric_data: List of metric data dictionaries

        Returns:
            True if all batches succeeded, False otherwise
        """
        if not metric_data:
            return True

        success = True
        total_emitted = 0

        # Split into batches
        for i in range(0, len(metric_data), MAX_METRICS_PER_BATCH):
            batch = metric_data[i:i + MAX_METRICS_PER_BATCH]

            try:
                cloudwatch.put_metric_data(
                    Namespace=self.namespace,
                    MetricData=batch
                )
                total_emitted += len(batch)
            except ClientError as e:
                print(f"Error emitting metrics batch: {e.response['Error']['Message']}")
                success = False
            except Exception as e:
                print(f"Unexpected error emitting metrics: {str(e)}")
                success = False

        print(f"Emitted {total_emitted}/{len(metric_data)} metrics to {self.namespace}")
        return success

    def emit_check_status(self, success: bool, duration_ms: float) -> bool:
        """
        Emit metrics about the drift check execution itself.

        Args:
            success: Whether the check completed successfully
            duration_ms: Duration of the check in milliseconds

        Returns:
            True if metrics emitted successfully
        """
        timestamp = datetime.now(timezone.utc)

        metrics = [
            {
                'MetricName': 'DriftCheckSuccess',
                'Timestamp': timestamp,
                'Value': 1 if success else 0,
                'Unit': 'Count',
            },
            {
                'MetricName': 'DriftCheckDuration',
                'Timestamp': timestamp,
                'Value': duration_ms,
                'Unit': 'Milliseconds',
            },
        ]

        return self._emit_batched(metrics)
