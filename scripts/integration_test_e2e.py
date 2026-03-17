#!/usr/bin/env python3
"""End-to-end integration test: SF record change -> CDC -> sync -> searchable.

Requires live infrastructure (SF sandbox, Lambda, Turbopuffer, Bedrock).
Run with:
    python3 scripts/integration_test_e2e.py --config denorm_config.yaml \
        --target-org ascendix-beta-sandbox

    # Real AppFlow mode (validates full Salesforce CDC -> AppFlow -> S3 path):
    python3 scripts/integration_test_e2e.py \
        --target-org ascendix-beta-sandbox --real-appflow --timeout 300

Tests:
1. CREATE: Create test Property in SF -> poll Turbopuffer -> verify searchable
2. UPDATE: Update field (City) -> poll -> verify updated value
3. DELETE: Delete record -> poll -> verify removed
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))

import boto3

from common.salesforce_client import SalesforceClient
from lib.turbopuffer_backend import TurbopufferBackend

LOG = logging.getLogger("e2e_test")

# Test record constants
TEST_RECORD_PREFIX = "E2E_TEST_"
POLL_INTERVAL_SECONDS = 10
POLL_TIMEOUT_SECONDS = 300  # 5 minutes

# CDC bucket — used to simulate AppFlow delivery when AppFlow is not configured
CDC_BUCKET = os.environ.get(
    "CDC_BUCKET",
    "salesforce-ai-search-cdc-382211616288-us-west-2",
)


def create_test_property(sf_client: SalesforceClient, test_id: str) -> str:
    """Create a test Property record in Salesforce. Returns record ID."""
    import urllib.request

    body = json.dumps({
        "Name": f"{TEST_RECORD_PREFIX}{test_id}",
        "ascendix__City__c": "TestCity",
        "ascendix__State__c": "TX",
        "ascendix__PropertyClass__c": "A",
    }).encode("utf-8")

    url = f"{sf_client._base_url}/sobjects/ascendix__Property__c"
    req = urllib.request.Request(
        url,
        data=body,
        headers=sf_client._build_headers(),
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
        record_id = result["id"]
        LOG.info("Created test Property: %s (ID: %s)", f"{TEST_RECORD_PREFIX}{test_id}", record_id)
        return record_id


def update_test_property(sf_client: SalesforceClient, record_id: str, city: str) -> None:
    """Update City field on test Property."""
    import urllib.request

    body = json.dumps({"ascendix__City__c": city}).encode("utf-8")
    url = f"{sf_client._base_url}/sobjects/ascendix__Property__c/{record_id}"
    req = urllib.request.Request(
        url,
        data=body,
        headers=sf_client._build_headers(),
        method="PATCH",
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        pass  # 204 No Content on success

    LOG.info("Updated Property %s: City -> %s", record_id, city)


def delete_test_property(sf_client: SalesforceClient, record_id: str) -> None:
    """Delete test Property from Salesforce."""
    import urllib.request

    url = f"{sf_client._base_url}/sobjects/ascendix__Property__c/{record_id}"
    req = urllib.request.Request(
        url,
        headers=sf_client._build_headers(),
        method="DELETE",
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        pass  # 204 No Content on success

    LOG.info("Deleted Property %s", record_id)


def write_cdc_event_to_s3(
    record_id: str,
    change_type: str,
) -> None:
    """Write a CDC event to S3 to trigger the CDC sync Lambda.

    This simulates the AppFlow delivery path. When AppFlow CDC flows are
    configured, this function becomes unnecessary — AppFlow writes the
    event to S3 automatically.
    """
    s3 = boto3.client("s3")
    cdc_payload = {
        "ChangeEventHeader": {
            "entityName": "ascendix__Property__ChangeEvent",
            "changeType": change_type,
            "recordIds": [record_id],
            "commitTimestamp": int(time.time() * 1000),
        },
    }
    key = f"cdc/Property__c/{time.strftime('%Y/%m/%d/%H')}/e2e-{change_type.lower()}-{int(time.time())}.json"
    s3.put_object(Bucket=CDC_BUCKET, Key=key, Body=json.dumps(cdc_payload))
    LOG.info("Wrote CDC %s event to s3://%s/%s", change_type, CDC_BUCKET, key)


# AppFlow writes CDC files under cdc/{sobjectName}/ where sobjectName is
# e.g. ascendix__Property__c (the ChangeEvent suffix replaced with __c).
# This is distinct from the synthetic prefix cdc/Property__c/ used above.
APPFLOW_CDC_PREFIX = "cdc/ascendix__Property__c/"


def poll_for_appflow_cdc_file(
    record_id: str,
    change_type: str,
    after_timestamp: float,
    timeout: int = POLL_TIMEOUT_SECONDS,
) -> dict | None:
    """Poll S3 for an AppFlow-written CDC file matching the record and change type.

    Returns dict with 's3_key', 'arrival_ts', and 'payload' on success, or None on timeout.
    Only considers objects written after ``after_timestamp`` (epoch seconds) to
    exclude stale files from previous runs.
    """
    s3 = boto3.client("s3")
    after_dt = datetime.fromtimestamp(after_timestamp, tz=timezone.utc)
    start = time.time()

    while time.time() - start < timeout:
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=CDC_BUCKET, Prefix=APPFLOW_CDC_PREFIX):
                for obj in page.get("Contents", []):
                    # Skip files written before the mutation
                    if obj["LastModified"].replace(tzinfo=timezone.utc) <= after_dt:
                        continue

                    key = obj["Key"]
                    try:
                        resp = s3.get_object(Bucket=CDC_BUCKET, Key=key)
                        body = json.loads(resp["Body"].read().decode("utf-8"))
                    except Exception:
                        LOG.debug("Failed to read candidate %s, skipping", key)
                        continue

                    header = body.get("ChangeEventHeader", {})
                    if (
                        record_id in header.get("recordIds", [])
                        and header.get("changeType") == change_type
                    ):
                        arrival_ts = obj["LastModified"].isoformat()
                        LOG.info(
                            "Found AppFlow CDC file: s3://%s/%s (changeType=%s, arrival=%s)",
                            CDC_BUCKET, key, change_type, arrival_ts,
                        )
                        return {
                            "s3_key": key,
                            "arrival_ts": arrival_ts,
                            "payload": body,
                        }
        except Exception as e:
            LOG.debug("S3 poll error: %s", e)

        LOG.info(
            "  Polling S3 for AppFlow CDC file (%s %s)... (%.0fs elapsed)",
            change_type, record_id, time.time() - start,
        )
        time.sleep(POLL_INTERVAL_SECONDS)

    LOG.warning("No AppFlow CDC file found for %s %s within %ds", change_type, record_id, timeout)
    return None


def poll_for_record(
    backend: TurbopufferBackend,
    namespace: str,
    record_id: str,
    record_name: str | None = None,
    timeout: int = POLL_TIMEOUT_SECONDS,
) -> dict | None:
    """Poll Turbopuffer until record appears. Returns record or None on timeout.

    Uses the record name as a BM25 text query (since the indexed text contains
    field values, not the Salesforce ID). Then confirms the match by checking
    the document ``id`` field against the expected ``record_id``.
    """
    # BM25 query uses the test record name (which IS in the indexed text)
    search_text = record_name or TEST_RECORD_PREFIX
    start = time.time()
    while time.time() - start < timeout:
        try:
            results = backend.search(
                namespace,
                text_query=search_text,
                top_k=5,
                include_attributes=["id", "name", "city", "object_type"],
            )
            for r in results:
                if r.get("id") == record_id:
                    return r
        except Exception as e:
            LOG.debug("Poll error (expected during propagation): %s", e)

        LOG.info("  Polling... (%.0fs elapsed)", time.time() - start)
        time.sleep(POLL_INTERVAL_SECONDS)

    return None


def poll_for_record_absent(
    backend: TurbopufferBackend,
    namespace: str,
    record_id: str,
    record_name: str | None = None,
    timeout: int = POLL_TIMEOUT_SECONDS,
) -> bool:
    """Poll until record is no longer found. Returns True if absent.

    Does NOT treat search exceptions as "absent" — only an explicit search
    that returns no matching document ID counts.
    """
    search_text = record_name or TEST_RECORD_PREFIX
    start = time.time()
    while time.time() - start < timeout:
        try:
            results = backend.search(
                namespace,
                text_query=search_text,
                top_k=5,
                include_attributes=["id"],
            )
            found = any(r.get("id") == record_id for r in results)
            if not found:
                return True
        except Exception as e:
            # Do NOT treat exceptions as "absent" — that gives false positives
            LOG.warning("Poll error during deletion check: %s", e)

        LOG.info("  Polling for deletion... (%.0fs elapsed)", time.time() - start)
        time.sleep(POLL_INTERVAL_SECONDS)

    return False


def _iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_test_entry(
    name: str,
    status: str,
    *,
    reason: str = "",
    mutation_ts: str = "",
    cdc_s3_key: str = "",
    cdc_arrival_ts: str = "",
    turbopuffer_visible_ts: str = "",
    latency_seconds: float | None = None,
) -> dict:
    """Build a test result entry with optional timing fields."""
    entry: dict[str, Any] = {"name": name, "status": status}
    if reason:
        entry["reason"] = reason
    if mutation_ts:
        entry["mutation_ts"] = mutation_ts
    if cdc_s3_key:
        entry["cdc_s3_key"] = cdc_s3_key
    if cdc_arrival_ts:
        entry["cdc_arrival_ts"] = cdc_arrival_ts
    if turbopuffer_visible_ts:
        entry["turbopuffer_visible_ts"] = turbopuffer_visible_ts
    if latency_seconds is not None:
        entry["latency_seconds"] = round(latency_seconds, 1)
    return entry


def run_e2e_tests(
    sf_client: SalesforceClient,
    backend: TurbopufferBackend,
    namespace: str,
    *,
    real_appflow: bool = False,
) -> dict:
    """Run all E2E test scenarios. Returns results dict."""
    test_id = str(int(time.time()))
    record_name = f"{TEST_RECORD_PREFIX}{test_id}"
    mode = "real_appflow" if real_appflow else "synthetic"
    results: dict[str, Any] = {"mode": mode, "passed": 0, "failed": 0, "tests": []}
    record_id = None

    create_succeeded = False

    try:
        # Test 1: CREATE
        LOG.info("=== Test 1: CREATE (mode=%s) ===", mode)
        mutation_ts = _iso_now()
        mutation_epoch = time.time()
        record_id = create_test_property(sf_client, test_id)

        cdc_s3_key = ""
        cdc_arrival_ts = ""

        if real_appflow:
            cdc_file = poll_for_appflow_cdc_file(record_id, "CREATE", mutation_epoch)
            if cdc_file:
                cdc_s3_key = cdc_file["s3_key"]
                cdc_arrival_ts = cdc_file["arrival_ts"]
            else:
                LOG.error("FAIL: No AppFlow CDC file for CREATE within timeout")
                results["failed"] += 1
                results["tests"].append(_build_test_entry(
                    "CREATE", "FAIL",
                    reason="AppFlow CDC file not found in S3 within timeout",
                    mutation_ts=mutation_ts,
                ))
                return results  # Cannot continue without CDC delivery
        else:
            write_cdc_event_to_s3(record_id, "CREATE")

        record = poll_for_record(backend, namespace, record_id, record_name=record_name)
        if record:
            turbopuffer_visible_ts = _iso_now()
            latency = time.time() - mutation_epoch
            LOG.info("PASS: Record found in Turbopuffer after CREATE (%.1fs)", latency)
            results["passed"] += 1
            results["tests"].append(_build_test_entry(
                "CREATE", "PASS",
                mutation_ts=mutation_ts,
                cdc_s3_key=cdc_s3_key,
                cdc_arrival_ts=cdc_arrival_ts,
                turbopuffer_visible_ts=turbopuffer_visible_ts,
                latency_seconds=latency,
            ))
            create_succeeded = True
        else:
            LOG.error("FAIL: Record not found within %ds", POLL_TIMEOUT_SECONDS)
            results["failed"] += 1
            results["tests"].append(_build_test_entry(
                "CREATE", "FAIL",
                reason="Record not found within timeout",
                mutation_ts=mutation_ts,
                cdc_s3_key=cdc_s3_key,
                cdc_arrival_ts=cdc_arrival_ts,
            ))

        # Test 2: UPDATE (depends on CREATE succeeding)
        if create_succeeded:
            LOG.info("=== Test 2: UPDATE (mode=%s) ===", mode)
            mutation_ts = _iso_now()
            mutation_epoch = time.time()
            new_city = f"UpdatedCity_{test_id}"
            update_test_property(sf_client, record_id, new_city)

            cdc_s3_key = ""
            cdc_arrival_ts = ""

            if real_appflow:
                cdc_file = poll_for_appflow_cdc_file(record_id, "UPDATE", mutation_epoch)
                if cdc_file:
                    cdc_s3_key = cdc_file["s3_key"]
                    cdc_arrival_ts = cdc_file["arrival_ts"]
                else:
                    LOG.error("FAIL: No AppFlow CDC file for UPDATE within timeout")
                    results["failed"] += 1
                    results["tests"].append(_build_test_entry(
                        "UPDATE", "FAIL",
                        reason="AppFlow CDC file not found in S3 within timeout",
                        mutation_ts=mutation_ts,
                    ))
                    # Continue to DELETE test — don't abort entirely
                    create_succeeded = True  # still try delete
                    # Jump past the Turbopuffer poll for UPDATE
                    cdc_file = None
            else:
                write_cdc_event_to_s3(record_id, "UPDATE")
                cdc_file = True  # sentinel to enter poll block

            if cdc_file:
                start = time.time()
                updated = False
                while time.time() - start < POLL_TIMEOUT_SECONDS:
                    record = poll_for_record(backend, namespace, record_id, record_name=record_name, timeout=30)
                    if record and record.get("city") == new_city:
                        updated = True
                        break
                    time.sleep(POLL_INTERVAL_SECONDS)

                if updated:
                    turbopuffer_visible_ts = _iso_now()
                    latency = time.time() - mutation_epoch
                    LOG.info("PASS: Record updated in Turbopuffer after UPDATE (%.1fs)", latency)
                    results["passed"] += 1
                    results["tests"].append(_build_test_entry(
                        "UPDATE", "PASS",
                        mutation_ts=mutation_ts,
                        cdc_s3_key=cdc_s3_key,
                        cdc_arrival_ts=cdc_arrival_ts,
                        turbopuffer_visible_ts=turbopuffer_visible_ts,
                        latency_seconds=latency,
                    ))
                else:
                    LOG.error("FAIL: Updated value not reflected within %ds", POLL_TIMEOUT_SECONDS)
                    results["failed"] += 1
                    results["tests"].append(_build_test_entry(
                        "UPDATE", "FAIL",
                        reason="Updated value not reflected within timeout",
                        mutation_ts=mutation_ts,
                        cdc_s3_key=cdc_s3_key,
                        cdc_arrival_ts=cdc_arrival_ts,
                    ))
        else:
            LOG.warning("SKIP: UPDATE skipped because CREATE failed")
            results["tests"].append(_build_test_entry(
                "UPDATE", "SKIP", reason="CREATE failed — cannot validate UPDATE"))

        # Test 3: DELETE (depends on CREATE succeeding)
        if create_succeeded:
            LOG.info("=== Test 3: DELETE (mode=%s) ===", mode)
            mutation_ts = _iso_now()
            mutation_epoch = time.time()
            delete_test_property(sf_client, record_id)

            cdc_s3_key = ""
            cdc_arrival_ts = ""

            if real_appflow:
                cdc_file = poll_for_appflow_cdc_file(record_id, "DELETE", mutation_epoch)
                if cdc_file:
                    cdc_s3_key = cdc_file["s3_key"]
                    cdc_arrival_ts = cdc_file["arrival_ts"]
                else:
                    LOG.error("FAIL: No AppFlow CDC file for DELETE within timeout")
                    results["failed"] += 1
                    results["tests"].append(_build_test_entry(
                        "DELETE", "FAIL",
                        reason="AppFlow CDC file not found in S3 within timeout",
                        mutation_ts=mutation_ts,
                    ))
                    cdc_file = None
            else:
                write_cdc_event_to_s3(record_id, "DELETE")
                cdc_file = True

            if cdc_file:
                absent = poll_for_record_absent(backend, namespace, record_id, record_name=record_name)
                if absent:
                    turbopuffer_visible_ts = _iso_now()
                    latency = time.time() - mutation_epoch
                    LOG.info("PASS: Record removed from Turbopuffer after DELETE (%.1fs)", latency)
                    results["passed"] += 1
                    results["tests"].append(_build_test_entry(
                        "DELETE", "PASS",
                        mutation_ts=mutation_ts,
                        cdc_s3_key=cdc_s3_key,
                        cdc_arrival_ts=cdc_arrival_ts,
                        turbopuffer_visible_ts=turbopuffer_visible_ts,
                        latency_seconds=latency,
                    ))
                    record_id = None  # Already cleaned up
                else:
                    LOG.error("FAIL: Record still present after %ds", POLL_TIMEOUT_SECONDS)
                    results["failed"] += 1
                    results["tests"].append(_build_test_entry(
                        "DELETE", "FAIL",
                        reason="Record still present after timeout",
                        mutation_ts=mutation_ts,
                        cdc_s3_key=cdc_s3_key,
                        cdc_arrival_ts=cdc_arrival_ts,
                    ))
        else:
            LOG.warning("SKIP: DELETE skipped because CREATE failed (would be vacuously true)")
            results["tests"].append(_build_test_entry(
                "DELETE", "SKIP", reason="CREATE failed — DELETE would be vacuously true"))

    except Exception as e:
        LOG.error("E2E test error: %s", e)
        results["failed"] += 1
        results["tests"].append(_build_test_entry("UNEXPECTED", "FAIL", reason=str(e)))

    finally:
        # Cleanup: delete test record if still exists
        if record_id:
            try:
                delete_test_property(sf_client, record_id)
                LOG.info("Cleaned up test record %s", record_id)
            except Exception as e:
                LOG.warning("Cleanup failed for %s: %s", record_id, e)

    return results


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="E2E integration test for CDC sync pipeline")
    parser.add_argument("--namespace", help="Turbopuffer namespace (default: org_{org_id})")
    parser.add_argument("--target-org", default="ascendix-beta-sandbox")
    parser.add_argument("--instance-url", default="")
    parser.add_argument("--access-token", default="")
    parser.add_argument("--timeout", type=int, default=300, help="Poll timeout in seconds")
    parser.add_argument(
        "--real-appflow", action="store_true",
        help="Use real AppFlow CDC delivery instead of synthetic S3 writes. "
             "Polls S3 for AppFlow-written CDC files after each Salesforce mutation.",
    )
    args = parser.parse_args()

    global POLL_TIMEOUT_SECONDS
    POLL_TIMEOUT_SECONDS = args.timeout

    # Connect to SF
    if args.instance_url and args.access_token:
        sf = SalesforceClient(args.instance_url, args.access_token)
    else:
        from scripts.bulk_load import sf_client_from_cli
        sf = sf_client_from_cli(args.target_org)

    # Get org ID for namespace
    org_records = sf.query("SELECT Id FROM Organization LIMIT 1")
    org_id = org_records["records"][0]["Id"]
    namespace = args.namespace or f"org_{org_id}"

    backend = TurbopufferBackend()

    mode_label = "real_appflow" if args.real_appflow else "synthetic"
    LOG.info("Running E2E tests against namespace: %s (mode=%s)", namespace, mode_label)
    results = run_e2e_tests(sf, backend, namespace, real_appflow=args.real_appflow)

    # Report
    LOG.info("=== E2E Results ===")
    LOG.info("Passed: %d, Failed: %d", results["passed"], results["failed"])
    for t in results["tests"]:
        status = "PASS" if t["status"] == "PASS" else f"FAIL: {t.get('reason', '')}"
        LOG.info("  %s: %s", t["name"], status)

    # Write results
    results_path = PROJECT_ROOT / "results" / "e2e_test_results.json"
    results_path.parent.mkdir(exist_ok=True)
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    sys.exit(1 if results["failed"] > 0 else 0)


if __name__ == "__main__":
    main()
