"""
Schema Drift Checker Lambda Handler.

Compares Salesforce Describe API schemas with cached schemas and emits drift metrics.

IMPORTANT: This Lambda is READ-ONLY. It observes schema drift but NEVER mutates
the Schema Cache. Schema updates are handled exclusively by Schema Discovery Lambda.

**Feature: schema-drift-monitoring**
**Task: 39**
"""
import json
import os
import sys
import time
from typing import Dict, Any, Optional

# Lambda layers are mounted at /opt/python
# Add layer path for schema_discovery module
layer_path = '/opt/python'
if layer_path not in sys.path:
    sys.path.insert(0, layer_path)

from coverage import CoverageCalculator, DriftResult
from metrics import MetricsEmitter

# Import from schema_discovery Lambda Layer
from schema_discovery.discoverer import SchemaDiscoverer
from schema_discovery.cache import SchemaCache


# Environment variables
EXPECTED_OBJECT_COUNT = int(os.environ.get('EXPECTED_SCHEMA_OBJECT_COUNT', '9'))
ENABLE_NOTIFICATIONS = os.environ.get('ENABLE_DRIFT_NOTIFICATIONS', 'false').lower() == 'true'


def get_monitored_objects() -> list:
    """
    Derive monitored objects dynamically from Schema Cache.

    This ensures we only check objects that are actually being tracked,
    and automatically adapts as objects are added/removed.

    Returns:
        List of object API names from cache
    """
    cache = SchemaCache()
    cached_schemas = cache.get_all()
    return list(cached_schemas.keys())


def is_discovery_running() -> bool:
    """
    Check if Schema Discovery Lambda is currently running.

    Used to suppress alerts during active discovery to avoid false positives.

    TODO: Implement via DynamoDB lock check or CloudWatch Logs Insights query.
    For now, returns False (no suppression).

    Returns:
        True if discovery is running, False otherwise
    """
    # Future implementation:
    # - Check for a 'discovery_lock' item in schema cache
    # - Or query CloudWatch Logs for recent discovery Lambda invocations
    return False


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for schema drift checking.

    This function:
    1. Discovers schemas from Salesforce (read-only)
    2. Reads schemas from cache (read-only)
    3. Calculates drift metrics
    4. Emits metrics to CloudWatch
    5. Optionally generates a report

    Trigger sources:
    - EventBridge scheduled rule (nightly)
    - Manual invocation (on-demand)

    Args:
        event: Lambda event (may contain 'notify': true to send notifications)
        context: Lambda context

    Returns:
        Response dict with drift results and metrics
    """
    start_time = time.time()
    print(f"Schema drift check started at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")

    # Initialize components
    discoverer = SchemaDiscoverer(enable_signal_harvesting=False)  # Skip signals for perf
    cache = SchemaCache()
    calculator = CoverageCalculator()
    emitter = MetricsEmitter()

    results = {}
    success = True
    error_message = None

    try:
        # Step 1: Get monitored objects from cache
        monitored_objects = get_monitored_objects()
        print(f"Monitoring {len(monitored_objects)} objects: {monitored_objects}")

        if not monitored_objects:
            print("WARNING: No objects in schema cache. Emitting zero-coverage metrics.")
            results = {}
        else:
            # Step 2: Discover schemas from Salesforce (READ-ONLY)
            print("Discovering schemas from Salesforce...")
            sf_schemas_raw = discoverer.discover_all(objects=monitored_objects)

            # Convert ObjectSchema to dict for comparison
            sf_schemas = {
                name: schema.to_dict()
                for name, schema in sf_schemas_raw.items()
            }
            print(f"Discovered {len(sf_schemas)} schemas from Salesforce")

            # Step 3: Read schemas from cache (READ-ONLY)
            print("Reading schemas from cache...")
            cache_schemas_raw = cache.get_all()

            # Convert ObjectSchema to dict for comparison
            cache_schemas = {
                name: schema.to_dict()
                for name, schema in cache_schemas_raw.items()
            }
            print(f"Read {len(cache_schemas)} schemas from cache")

            # Step 4: Calculate drift
            print("Calculating drift...")
            results = calculator.calculate_all_drift(sf_schemas, cache_schemas)

            # Log results
            for obj_name, drift in results.items():
                if drift.has_drift:
                    print(f"DRIFT DETECTED: {obj_name}")
                    print(f"  - Fake fields: {drift.fields_in_cache_not_sf}")
                else:
                    print(f"OK: {obj_name} (filterable: {drift.filterable_coverage:.1f}%, "
                          f"relationships: {drift.relationship_coverage:.1f}%)")

        # Step 5: Emit metrics to CloudWatch
        print("Emitting metrics to CloudWatch...")
        emitter.emit_drift_metrics(results)

        # Generate summary
        summary = calculator.summarize(results)
        print(f"Summary: {json.dumps(summary, indent=2)}")

        # Check for critical drift (fake fields)
        if summary.get('total_fake_fields', 0) > 0:
            print("CRITICAL: Fake fields detected in schema cache!")
            if ENABLE_NOTIFICATIONS and not is_discovery_running():
                # TODO: Send SNS notification
                print("Notification would be sent (notifications enabled)")

    except Exception as e:
        success = False
        error_message = str(e)
        print(f"ERROR during drift check: {error_message}")
        import traceback
        traceback.print_exc()

    # Calculate duration
    duration_ms = (time.time() - start_time) * 1000
    print(f"Schema drift check completed in {duration_ms:.0f}ms")

    # Emit check status metric
    emitter.emit_check_status(success, duration_ms)

    # Build response
    response = {
        'statusCode': 200 if success else 500,
        'body': {
            'success': success,
            'duration_ms': round(duration_ms, 2),
            'objects_checked': len(results),
            'objects_with_drift': sum(1 for r in results.values() if r.has_drift),
            'total_fake_fields': sum(len(r.fields_in_cache_not_sf) for r in results.values()),
            'results': {name: drift.to_dict() for name, drift in results.items()},
        }
    }

    if error_message:
        response['body']['error'] = error_message

    return response


# For local testing
if __name__ == '__main__':
    # Mock event for local testing
    test_event = {
        'source': 'local-test',
        'notify': False
    }

    result = handler(test_event, None)
    print(json.dumps(result, indent=2, default=str))
