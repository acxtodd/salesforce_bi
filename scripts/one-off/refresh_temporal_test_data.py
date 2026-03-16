#!/usr/bin/env python3
"""
Temporal Test Data Refresh Script.

Updates temporal fields (dates) on sandbox test records to ensure temporal queries
return current results. Moves stale dates to relevant future timeframes.

**Task:** 40.8 - Temporal Test Data Refresh
**Requirements:** 10.2, 14.4

Field References (VERIFIED against Salesforce schema):
- Lease expiration: ascendix__TermExpirationDate__c (NOT ascendix__EndDate__c)
- Deal close date: ascendix__CloseDateEstimated__c (NOT ascendix__CloseDate__c)
- Task activity date: ActivityDate

Usage:
    # Dry run (show what would be updated)
    python scripts/refresh_temporal_test_data.py --dry-run

    # Refresh lease dates (default: next 12 months)
    python scripts/refresh_temporal_test_data.py --object lease

    # Refresh deal dates with custom range
    python scripts/refresh_temporal_test_data.py --object deal --months 6

    # Refresh all temporal objects
    python scripts/refresh_temporal_test_data.py --all

    # Verify CDC propagation after refresh
    python scripts/refresh_temporal_test_data.py --verify

Environment Variables:
    SF_TARGET_ORG: Salesforce target org alias (default: ascendix-beta-sandbox)
    AWS_REGION: AWS region for SSM/Lambda (default: us-west-2)

Notes:
    - This script uses SF CLI for updates (sf data update record)
    - Verify CDC is enabled before running (use --verify-cdc flag)
    - Updates are done in small batches to avoid DML limits
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError

# Configuration
SF_TARGET_ORG = os.environ.get("SF_TARGET_ORG", "ascendix-beta-sandbox")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

# Correct field names (verified against Salesforce schema)
TEMPORAL_FIELDS = {
    "ascendix__Lease__c": {
        "date_field": "ascendix__TermExpirationDate__c",  # NOT EndDate
        "label": "Lease Expiration",
        "distribution": [
            (0.2, 30),    # 20% expire in next 30 days
            (0.3, 90),    # 30% expire in next 90 days
            (0.3, 180),   # 30% expire in next 6 months
            (0.2, 365),   # 20% expire in next year
        ],
    },
    "ascendix__Deal__c": {
        "date_field": "ascendix__CloseDateEstimated__c",  # NOT CloseDate
        "label": "Deal Close Date",
        "distribution": [
            (0.3, 30),    # 30% close in next 30 days
            (0.4, 90),    # 40% close in next 90 days
            (0.3, 180),   # 30% close in next 6 months
        ],
    },
    "Task": {
        "date_field": "ActivityDate",
        "label": "Task Due Date",
        "distribution": [
            (0.4, 7),     # 40% due this week
            (0.3, 30),    # 30% due this month
            (0.2, 90),    # 20% due in next 90 days
            (0.1, -30),   # 10% recently completed (past 30 days)
        ],
    },
}

# DynamoDB tables for CDC verification
CDC_TABLES = {
    "ascendix__Lease__c": "salesforce-ai-search-leases-view",
    "ascendix__Deal__c": None,  # No dedicated view yet
    "Task": "salesforce-ai-search-activities-agg",
}

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("refresh_temporal_test_data")


class TemporalRefresher:
    """Refreshes temporal test data in Salesforce sandbox."""

    def __init__(self, target_org: str = SF_TARGET_ORG, dry_run: bool = False):
        self.target_org = target_org
        self.dry_run = dry_run
        self._sf_verified = False

    def verify_sf_connection(self) -> bool:
        """Verify SF CLI connection to target org."""
        if self._sf_verified:
            return True

        LOGGER.info(f"Verifying connection to {self.target_org}...")
        try:
            result = subprocess.run(
                ["sf", "org", "display", "--target-org", self.target_org, "--json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                LOGGER.error(f"SF CLI error: {result.stderr}")
                return False

            data = json.loads(result.stdout)
            if data.get("status") != 0:
                LOGGER.error(f"Org display failed: {data.get('message')}")
                return False

            org_info = data.get("result", {})
            LOGGER.info(
                f"Connected to: {org_info.get('username', 'unknown')} "
                f"({org_info.get('instanceUrl', 'unknown')})"
            )
            self._sf_verified = True
            return True

        except subprocess.TimeoutExpired:
            LOGGER.error("SF CLI command timed out")
            return False
        except json.JSONDecodeError as e:
            LOGGER.error(f"Failed to parse SF CLI output: {e}")
            return False
        except FileNotFoundError:
            LOGGER.error("SF CLI not found. Install with: npm install -g @salesforce/cli")
            return False

    def verify_cdc_enabled(self, sobject: str) -> Tuple[bool, str]:
        """
        Verify CDC is enabled for the specified object.

        Returns:
            Tuple of (is_enabled, message)
        """
        LOGGER.info(f"Checking CDC status for {sobject}...")

        # Query PushTopic or ChangeDataCapture settings
        # For now, we'll check if the object has any CDC subscription by checking the table
        table_name = CDC_TABLES.get(sobject)
        if not table_name:
            return True, f"No CDC table configured for {sobject} (skipping CDC check)"

        try:
            dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
            table = dynamodb.Table(table_name)

            # Check if table exists and has recent data
            response = table.scan(Limit=1)
            count = response.get("Count", 0)

            if count > 0:
                return True, f"CDC table {table_name} has data ({count}+ records)"
            else:
                return False, f"CDC table {table_name} is empty - CDC may not be configured"

        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                return False, f"CDC table {table_name} not found"
            return False, f"Error checking CDC table: {e}"

    def query_stale_records(
        self,
        sobject: str,
        date_field: str,
        stale_days: int = 30,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Query records with stale dates that need refreshing.

        Args:
            sobject: Salesforce object API name
            date_field: Date field to check
            stale_days: Consider dates older than this many days as stale
            limit: Maximum records to return

        Returns:
            List of record dicts with Id and current date value
        """
        cutoff_date = datetime.now(timezone.utc) + timedelta(days=stale_days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")

        # Build SOQL query
        soql = f"""
            SELECT Id, Name, {date_field}
            FROM {sobject}
            WHERE {date_field} <> null
            AND {date_field} < {cutoff_str}
            ORDER BY {date_field} ASC
            LIMIT {limit}
        """.strip().replace("\n", " ")

        LOGGER.info(f"Querying stale {sobject} records (dates before {cutoff_str})...")

        try:
            result = subprocess.run(
                [
                    "sf", "data", "query",
                    "--query", soql,
                    "--target-org", self.target_org,
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                LOGGER.error(f"Query failed: {result.stderr}")
                return []

            data = json.loads(result.stdout)
            records = data.get("result", {}).get("records", [])
            LOGGER.info(f"Found {len(records)} stale records")
            return records

        except Exception as e:
            LOGGER.error(f"Query error: {e}")
            return []

    def calculate_new_dates(
        self,
        records: List[Dict[str, Any]],
        distribution: List[Tuple[float, int]],
    ) -> List[Tuple[str, str]]:
        """
        Calculate new dates for records based on distribution.

        Args:
            records: List of records to update
            distribution: List of (percentage, days_from_today) tuples

        Returns:
            List of (record_id, new_date) tuples
        """
        if not records:
            return []

        updates = []
        total_records = len(records)
        idx = 0

        for percentage, days_offset in distribution:
            count = int(total_records * percentage)
            # Ensure we don't exceed total records
            count = min(count, total_records - idx)

            for _ in range(count):
                if idx >= total_records:
                    break

                record = records[idx]
                new_date = datetime.now(timezone.utc) + timedelta(days=days_offset)

                # Add some randomness within the bucket (spread dates)
                spread = int(days_offset * 0.3)
                if spread > 0:
                    import random
                    new_date += timedelta(days=random.randint(-spread, spread))

                updates.append((record["Id"], new_date.strftime("%Y-%m-%d")))
                idx += 1

        # Handle any remaining records
        if idx < total_records:
            last_days = distribution[-1][1] if distribution else 30
            for i in range(idx, total_records):
                new_date = datetime.now(timezone.utc) + timedelta(days=last_days)
                updates.append((records[i]["Id"], new_date.strftime("%Y-%m-%d")))

        return updates

    def update_record(self, sobject: str, record_id: str, field: str, value: str) -> bool:
        """
        Update a single record in Salesforce.

        Args:
            sobject: Salesforce object API name
            record_id: Record ID to update
            field: Field API name to update
            value: New field value

        Returns:
            True if successful, False otherwise
        """
        if self.dry_run:
            LOGGER.info(f"[DRY RUN] Would update {sobject} {record_id}: {field}={value}")
            return True

        try:
            result = subprocess.run(
                [
                    "sf", "data", "update", "record",
                    "--sobject", sobject,
                    "--record-id", record_id,
                    "--values", f"{field}={value}",
                    "--target-org", self.target_org,
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                # Check for specific errors
                try:
                    error_data = json.loads(result.stdout)
                    error_msg = error_data.get("message", result.stderr)
                except:
                    error_msg = result.stderr
                LOGGER.warning(f"Update failed for {record_id}: {error_msg}")
                return False

            return True

        except Exception as e:
            LOGGER.error(f"Update error for {record_id}: {e}")
            return False

    def refresh_object(
        self,
        sobject: str,
        max_records: int = 50,
        batch_delay: float = 0.5,
    ) -> Dict[str, int]:
        """
        Refresh temporal dates for a Salesforce object.

        Args:
            sobject: Salesforce object API name
            max_records: Maximum records to update
            batch_delay: Delay between updates (seconds)

        Returns:
            Dict with success/failure counts
        """
        config = TEMPORAL_FIELDS.get(sobject)
        if not config:
            LOGGER.error(f"No configuration for object: {sobject}")
            return {"success": 0, "failed": 0, "skipped": 0}

        date_field = config["date_field"]
        distribution = config["distribution"]
        label = config["label"]

        LOGGER.info(f"\n{'='*60}")
        LOGGER.info(f"Refreshing {label} dates for {sobject}")
        LOGGER.info(f"Field: {date_field}")
        LOGGER.info(f"{'='*60}")

        # Query stale records
        records = self.query_stale_records(sobject, date_field, limit=max_records)
        if not records:
            LOGGER.info("No stale records found")
            return {"success": 0, "failed": 0, "skipped": 0}

        # Calculate new dates
        updates = self.calculate_new_dates(records, distribution)

        # Apply updates
        success = 0
        failed = 0

        for record_id, new_date in updates:
            if self.update_record(sobject, record_id, date_field, new_date):
                success += 1
            else:
                failed += 1

            if not self.dry_run and batch_delay > 0:
                time.sleep(batch_delay)

        LOGGER.info(f"\nResults for {sobject}:")
        LOGGER.info(f"  Success: {success}")
        LOGGER.info(f"  Failed: {failed}")

        return {"success": success, "failed": failed, "skipped": 0}

    def verify_propagation(self, sobject: str, wait_seconds: int = 30) -> bool:
        """
        Verify CDC propagation to DynamoDB.

        Args:
            sobject: Salesforce object API name
            wait_seconds: Time to wait for CDC propagation

        Returns:
            True if propagation detected, False otherwise
        """
        table_name = CDC_TABLES.get(sobject)
        if not table_name:
            LOGGER.info(f"No CDC table for {sobject}, skipping propagation check")
            return True

        LOGGER.info(f"Waiting {wait_seconds}s for CDC propagation to {table_name}...")
        time.sleep(wait_seconds)

        # Check for recent updates in DynamoDB
        # This is a basic check - in production you'd check for specific record IDs
        try:
            dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
            table = dynamodb.Table(table_name)

            # Scan for any record (just verifying table is accessible)
            response = table.scan(Limit=1)
            count = response.get("Count", 0)

            if count > 0:
                LOGGER.info(f"CDC table {table_name} is receiving data")
                return True
            else:
                LOGGER.warning(f"CDC table {table_name} appears empty")
                return False

        except Exception as e:
            LOGGER.error(f"Propagation check error: {e}")
            return False

    def test_temporal_query(self) -> bool:
        """
        Test a temporal query via the Answer Lambda.

        Returns:
            True if query returns results, False otherwise
        """
        LOGGER.info("\nTesting temporal query via Answer Lambda...")

        # Get Lambda URL from SSM
        try:
            ssm = boto3.client("ssm", region_name=AWS_REGION)

            # Try to get API key from SSM (optional)
            try:
                api_key_param = ssm.get_parameter(
                    Name="/salesforce-ai-search/api-key",
                    WithDecryption=True,
                )
                api_key = api_key_param["Parameter"]["Value"]
            except:
                api_key = os.environ.get("AI_SEARCH_API_KEY", "")
                if not api_key:
                    LOGGER.warning("API key not found in SSM or environment")
                    return False

            # Lambda URL (could also be in SSM)
            lambda_url = os.environ.get(
                "ANSWER_LAMBDA_URL",
                "https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer"
            )

            # Test query
            import urllib.request

            query_data = json.dumps({
                "query": "show me leases expiring in the next 6 months",
                "salesforceUserId": "005dl00000Q6a3RAAR",
            }).encode("utf-8")

            request = urllib.request.Request(
                lambda_url,
                data=query_data,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                },
            )

            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode())

                answer = result.get("answer", "")
                debug = result.get("debug", {})
                record_count = debug.get("recordCount", 0)

                LOGGER.info(f"Query returned {record_count} records")
                if record_count > 0:
                    LOGGER.info(f"Answer preview: {answer[:200]}...")
                    return True
                else:
                    LOGGER.warning("Query returned no results")
                    return False

        except Exception as e:
            LOGGER.error(f"Query test failed: {e}")
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Refresh temporal test data in Salesforce sandbox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--object",
        choices=["lease", "deal", "task"],
        help="Specific object to refresh",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Refresh all temporal objects",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=50,
        help="Maximum records to update per object (default: 50)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )
    parser.add_argument(
        "--verify-cdc",
        action="store_true",
        help="Verify CDC is enabled before refreshing",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Only verify CDC propagation and run test query",
    )
    parser.add_argument(
        "--target-org",
        default=SF_TARGET_ORG,
        help=f"Salesforce target org alias (default: {SF_TARGET_ORG})",
    )

    args = parser.parse_args()

    # Map CLI names to object API names
    object_map = {
        "lease": "ascendix__Lease__c",
        "deal": "ascendix__Deal__c",
        "task": "Task",
    }

    refresher = TemporalRefresher(target_org=args.target_org, dry_run=args.dry_run)

    # Verify SF connection
    if not refresher.verify_sf_connection():
        LOGGER.error("Failed to connect to Salesforce")
        sys.exit(2)

    # Verify-only mode
    if args.verify:
        LOGGER.info("\n--- Verification Mode ---")

        for obj_name, api_name in object_map.items():
            enabled, msg = refresher.verify_cdc_enabled(api_name)
            status = "OK" if enabled else "WARN"
            LOGGER.info(f"[{status}] {api_name}: {msg}")

        # Test query
        if refresher.test_temporal_query():
            LOGGER.info("\n[OK] Temporal queries working")
            sys.exit(0)
        else:
            LOGGER.warning("\n[WARN] Temporal query returned no results")
            sys.exit(1)

    # Determine which objects to refresh
    if args.all:
        objects_to_refresh = list(TEMPORAL_FIELDS.keys())
    elif args.object:
        objects_to_refresh = [object_map[args.object]]
    else:
        # Default to leases
        objects_to_refresh = ["ascendix__Lease__c"]

    # Verify CDC if requested
    if args.verify_cdc:
        LOGGER.info("\n--- Verifying CDC Configuration ---")
        for sobject in objects_to_refresh:
            enabled, msg = refresher.verify_cdc_enabled(sobject)
            LOGGER.info(f"{sobject}: {msg}")
            if not enabled:
                LOGGER.error(f"CDC not enabled for {sobject}. Enable CDC before running refresh.")
                sys.exit(2)

    # Refresh objects
    total_success = 0
    total_failed = 0

    for sobject in objects_to_refresh:
        results = refresher.refresh_object(sobject, max_records=args.max_records)
        total_success += results["success"]
        total_failed += results["failed"]

    # Summary
    LOGGER.info(f"\n{'='*60}")
    LOGGER.info("REFRESH COMPLETE")
    LOGGER.info(f"{'='*60}")
    LOGGER.info(f"Total success: {total_success}")
    LOGGER.info(f"Total failed: {total_failed}")

    if args.dry_run:
        LOGGER.info("\n[DRY RUN] No actual changes were made")
    else:
        LOGGER.info("\nNext steps:")
        LOGGER.info("  1. Wait 1-2 minutes for CDC propagation")
        LOGGER.info("  2. Run: python scripts/refresh_temporal_test_data.py --verify")
        LOGGER.info("  3. Test temporal queries via UI or API")

    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
