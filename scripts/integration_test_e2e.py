#!/usr/bin/env python3
"""End-to-end integration test: SF record change -> CDC -> sync -> searchable.

Requires live infrastructure (SF sandbox, Lambda, Turbopuffer, Bedrock).
Run with:
    python3 scripts/integration_test_e2e.py --config denorm_config.yaml \
        --target-org ascendix-beta-sandbox

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


def run_e2e_tests(
    sf_client: SalesforceClient,
    backend: TurbopufferBackend,
    namespace: str,
) -> dict:
    """Run all E2E test scenarios. Returns results dict."""
    test_id = str(int(time.time()))
    record_name = f"{TEST_RECORD_PREFIX}{test_id}"
    results = {"passed": 0, "failed": 0, "tests": []}
    record_id = None

    create_succeeded = False

    try:
        # Test 1: CREATE
        LOG.info("=== Test 1: CREATE ===")
        record_id = create_test_property(sf_client, test_id)
        write_cdc_event_to_s3(record_id, "CREATE")
        record = poll_for_record(backend, namespace, record_id, record_name=record_name)
        if record:
            LOG.info("PASS: Record found in Turbopuffer after CREATE")
            results["passed"] += 1
            results["tests"].append({"name": "CREATE", "status": "PASS"})
            create_succeeded = True
        else:
            LOG.error("FAIL: Record not found within %ds", POLL_TIMEOUT_SECONDS)
            results["failed"] += 1
            results["tests"].append({"name": "CREATE", "status": "FAIL",
                                     "reason": "Record not found within timeout"})

        # Test 2: UPDATE (depends on CREATE succeeding)
        if create_succeeded:
            LOG.info("=== Test 2: UPDATE ===")
            new_city = f"UpdatedCity_{test_id}"
            update_test_property(sf_client, record_id, new_city)
            write_cdc_event_to_s3(record_id, "UPDATE")
            start = time.time()
            updated = False
            while time.time() - start < POLL_TIMEOUT_SECONDS:
                record = poll_for_record(backend, namespace, record_id, record_name=record_name, timeout=30)
                if record and record.get("city") == new_city:
                    updated = True
                    break
                time.sleep(POLL_INTERVAL_SECONDS)

            if updated:
                LOG.info("PASS: Record updated in Turbopuffer after UPDATE")
                results["passed"] += 1
                results["tests"].append({"name": "UPDATE", "status": "PASS"})
            else:
                LOG.error("FAIL: Updated value not reflected within %ds", POLL_TIMEOUT_SECONDS)
                results["failed"] += 1
                results["tests"].append({"name": "UPDATE", "status": "FAIL",
                                         "reason": "Updated value not reflected within timeout"})
        else:
            LOG.warning("SKIP: UPDATE skipped because CREATE failed")
            results["tests"].append({"name": "UPDATE", "status": "SKIP",
                                     "reason": "CREATE failed — cannot validate UPDATE"})

        # Test 3: DELETE (depends on CREATE succeeding)
        if create_succeeded:
            LOG.info("=== Test 3: DELETE ===")
            delete_test_property(sf_client, record_id)
            write_cdc_event_to_s3(record_id, "DELETE")
            absent = poll_for_record_absent(backend, namespace, record_id, record_name=record_name)
            if absent:
                LOG.info("PASS: Record removed from Turbopuffer after DELETE")
                results["passed"] += 1
                results["tests"].append({"name": "DELETE", "status": "PASS"})
                record_id = None  # Already cleaned up
            else:
                LOG.error("FAIL: Record still present after %ds", POLL_TIMEOUT_SECONDS)
                results["failed"] += 1
                results["tests"].append({"name": "DELETE", "status": "FAIL",
                                         "reason": "Record still present after timeout"})
        else:
            LOG.warning("SKIP: DELETE skipped because CREATE failed (would be vacuously true)")
            results["tests"].append({"name": "DELETE", "status": "SKIP",
                                     "reason": "CREATE failed — DELETE would be vacuously true"})

    except Exception as e:
        LOG.error("E2E test error: %s", e)
        results["failed"] += 1
        results["tests"].append({"name": "UNEXPECTED", "status": "FAIL", "reason": str(e)})

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

    LOG.info("Running E2E tests against namespace: %s", namespace)
    results = run_e2e_tests(sf, backend, namespace)

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
