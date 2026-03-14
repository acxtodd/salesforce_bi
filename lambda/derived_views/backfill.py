"""
Derived Views Backfill Lambda.

Nightly job to rebuild all derived views from source Salesforce data.
Target completion time: < 2 hours.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 10.2, 10.3**
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from index import (
    AvailabilityViewUpdater,
    VacancyViewUpdater,
    LeasesViewUpdater,
    ActivitiesAggUpdater,
    SalesViewUpdater,
    CDCEvent,
    AVAILABILITY_OBJECT,
    PROPERTY_OBJECT,
    LEASE_OBJECT,
    SALE_OBJECT,
    TASK_OBJECT,
    EVENT_OBJECT,
)

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Environment variables
SALESFORCE_API_URL = os.environ.get("SALESFORCE_API_URL", "")
SALESFORCE_ACCESS_TOKEN = os.environ.get("SALESFORCE_ACCESS_TOKEN", "")
BATCH_SIZE = int(os.environ.get("BACKFILL_BATCH_SIZE", "200"))
MAX_WORKERS = int(os.environ.get("BACKFILL_MAX_WORKERS", "5"))

# Table names
AVAILABILITY_VIEW_TABLE = os.environ.get(
    "AVAILABILITY_VIEW_TABLE", "salesforce-ai-search-availability-view"
)
VACANCY_VIEW_TABLE = os.environ.get(
    "VACANCY_VIEW_TABLE", "salesforce-ai-search-vacancy-view"
)
LEASES_VIEW_TABLE = os.environ.get(
    "LEASES_VIEW_TABLE", "salesforce-ai-search-leases-view"
)
ACTIVITIES_AGG_TABLE = os.environ.get(
    "ACTIVITIES_AGG_TABLE", "salesforce-ai-search-activities-agg"
)
SALES_VIEW_TABLE = os.environ.get(
    "SALES_VIEW_TABLE", "salesforce-ai-search-sales-view"
)


# =============================================================================
# Salesforce Query Helper
# =============================================================================


@dataclass
class BackfillStats:
    """Statistics for backfill operation."""

    view_name: str
    records_processed: int = 0
    records_succeeded: int = 0
    records_failed: int = 0
    elapsed_seconds: float = 0.0
    error_message: Optional[str] = None


class SalesforceClient:
    """
    Simple Salesforce API client for backfill queries.

    Uses SOQL to query source records.
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        access_token: Optional[str] = None,
    ):
        self.api_url = api_url or SALESFORCE_API_URL
        self.access_token = access_token or SALESFORCE_ACCESS_TOKEN
        self._http_client = None

    def query(self, soql: str) -> List[Dict[str, Any]]:
        """
        Execute SOQL query and return all records.

        Handles pagination automatically.
        """
        # For backfill, we would typically use requests library
        # Here we provide the interface - actual implementation depends on environment
        try:
            import requests

            records = []
            url = f"{self.api_url}/services/data/v59.0/query"
            headers = {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }

            response = requests.get(url, params={"q": soql}, headers=headers)
            response.raise_for_status()
            data = response.json()

            records.extend(data.get("records", []))

            # Handle pagination
            while data.get("nextRecordsUrl"):
                next_url = f"{self.api_url}{data['nextRecordsUrl']}"
                response = requests.get(next_url, headers=headers)
                response.raise_for_status()
                data = response.json()
                records.extend(data.get("records", []))

            return records

        except ImportError:
            LOGGER.warning("requests library not available, using mock data")
            return []
        except Exception as e:
            LOGGER.error(f"Salesforce query error: {e}")
            return []


# =============================================================================
# Backfill Processors
# =============================================================================


class BackfillProcessor:
    """Base class for backfill processors."""

    def __init__(
        self,
        sf_client: SalesforceClient,
        dynamodb_resource: Optional[Any] = None,
    ):
        self.sf_client = sf_client
        self._dynamodb = dynamodb_resource

    @property
    def dynamodb(self):
        """Lazy-load DynamoDB resource."""
        if self._dynamodb is None:
            self._dynamodb = boto3.resource("dynamodb")
        return self._dynamodb

    def clear_table(self, table_name: str) -> bool:
        """Clear all items from a DynamoDB table."""
        try:
            table = self.dynamodb.Table(table_name)

            # Scan and delete in batches
            scan_kwargs = {}
            deleted_count = 0

            while True:
                response = table.scan(**scan_kwargs)
                items = response.get("Items", [])

                if not items:
                    break

                # Get key schema
                key_schema = table.key_schema
                key_names = [k["AttributeName"] for k in key_schema]

                with table.batch_writer() as batch:
                    for item in items:
                        key = {k: item[k] for k in key_names if k in item}
                        batch.delete_item(Key=key)
                        deleted_count += 1

                if "LastEvaluatedKey" not in response:
                    break
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

            LOGGER.info(f"Cleared {deleted_count} items from {table_name}")
            return True

        except ClientError as e:
            LOGGER.error(f"Error clearing table {table_name}: {e}")
            return False


class AvailabilityBackfillProcessor(BackfillProcessor):
    """Backfill processor for availability_view."""

    def __init__(
        self,
        sf_client: SalesforceClient,
        dynamodb_resource: Optional[Any] = None,
    ):
        super().__init__(sf_client, dynamodb_resource)
        self.updater = AvailabilityViewUpdater(dynamodb_resource)

    def run(self, clear_first: bool = True) -> BackfillStats:
        """Run availability view backfill."""
        stats = BackfillStats(view_name="availability_view")
        start_time = time.time()

        try:
            if clear_first:
                self.clear_table(AVAILABILITY_VIEW_TABLE)

            # Query all Availability records with Property relationship
            # Updated 2025-12-10: Use real SF field names from Schema Discovery
            # - Removed fake PropertyType__c, using RecordType.Name instead
            # - Removed fake Submarket__c (doesn't exist in SF)
            # - ascendix__Size__c replaced with ascendix__AvailableArea__c
            # Updated 2025-12-14: Changed ascendix__Notes__c to ascendix__SpaceDescription__c
            # (Notes__c does not exist on Availability object in Salesforce)
            soql = """
                SELECT Id, ascendix__Property__c, ascendix__AvailableArea__c,
                       ascendix__Status__c, ascendix__SpaceDescription__c,
                       ascendix__Property__r.ascendix__PropertyClass__c,
                       ascendix__Property__r.RecordType.Name,
                       ascendix__Property__r.ascendix__City__c,
                       ascendix__Property__r.ascendix__State__c,
                       ascendix__Property__r.ascendix__SubMarket__r.Name
                FROM ascendix__Availability__c
                WHERE ascendix__Property__c != null
            """

            records = self.sf_client.query(soql)
            stats.records_processed = len(records)

            for record in records:
                try:
                    # Convert to CDCEvent format
                    event = CDCEvent(
                        object_type=AVAILABILITY_OBJECT,
                        record_id=record.get("Id", ""),
                        operation="create",
                        record_data=self._transform_record(record),
                    )
                    if self.updater.handle_create(event):
                        stats.records_succeeded += 1
                    else:
                        stats.records_failed += 1
                except Exception as e:
                    LOGGER.error(f"Error processing availability {record.get('Id')}: {e}")
                    stats.records_failed += 1

        except Exception as e:
            stats.error_message = str(e)
            LOGGER.error(f"Availability backfill error: {e}")

        stats.elapsed_seconds = time.time() - start_time
        return stats

    def _transform_record(self, record: Dict) -> Dict:
        """Transform Salesforce record to internal format."""
        # Updated 2025-12-10: Use real SF field names from Schema Discovery
        property_ref = record.get("ascendix__Property__r") or {}
        record_type = property_ref.get("RecordType") or {}
        submarket_ref = property_ref.get("ascendix__SubMarket__r") or {}
        return {
            "Id": record.get("Id"),
            "ascendix__Property__c": record.get("ascendix__Property__c"),
            "ascendix__Size__c": record.get("ascendix__AvailableArea__c"),  # Map to expected key
            "ascendix__Status__c": record.get("ascendix__Status__c"),
            # Map SpaceDescription to the key expected by the view (was Notes__c)
            "ascendix__SpaceDescription__c": record.get("ascendix__SpaceDescription__c"),
            "Property__r": {
                "ascendix__PropertyClass__c": property_ref.get(
                    "ascendix__PropertyClass__c"
                ),
                "RecordType": record_type.get("Name", ""),  # Use RecordType.Name
                "ascendix__City__c": property_ref.get("ascendix__City__c"),
                "ascendix__State__c": property_ref.get("ascendix__State__c"),
                "ascendix__SubMarket__r": {"Name": submarket_ref.get("Name", "")},
            },
        }


class VacancyBackfillProcessor(BackfillProcessor):
    """Backfill processor for vacancy_view."""

    def __init__(
        self,
        sf_client: SalesforceClient,
        dynamodb_resource: Optional[Any] = None,
    ):
        super().__init__(sf_client, dynamodb_resource)
        self.updater = VacancyViewUpdater(dynamodb_resource)

    def run(self, clear_first: bool = True) -> BackfillStats:
        """Run vacancy view backfill."""
        stats = BackfillStats(view_name="vacancy_view")
        start_time = time.time()

        try:
            if clear_first:
                self.clear_table(VACANCY_VIEW_TABLE)

            # Query all Property records
            # Updated 2025-12-10: Use real SF field names from Schema Discovery
            # - ascendix__TotalSqFt__c → ascendix__TotalBuildingArea__c
            # - ascendix__AvailableSqFt__c → ascendix__TotalAvailableArea__c
            # - ascendix__PropertyType__c → RecordType.Name
            soql = """
                SELECT Id, ascendix__TotalBuildingArea__c, ascendix__TotalAvailableArea__c,
                       ascendix__PropertyClass__c, RecordType.Name,
                       ascendix__City__c, ascendix__State__c
                FROM ascendix__Property__c
            """

            records = self.sf_client.query(soql)
            stats.records_processed = len(records)

            for record in records:
                try:
                    event = CDCEvent(
                        object_type=PROPERTY_OBJECT,
                        record_id=record.get("Id", ""),
                        operation="create",
                        record_data=record,
                    )
                    if self.updater.handle_create(event):
                        stats.records_succeeded += 1
                    else:
                        stats.records_failed += 1
                except Exception as e:
                    LOGGER.error(f"Error processing property {record.get('Id')}: {e}")
                    stats.records_failed += 1

        except Exception as e:
            stats.error_message = str(e)
            LOGGER.error(f"Vacancy backfill error: {e}")

        stats.elapsed_seconds = time.time() - start_time
        return stats


class LeasesBackfillProcessor(BackfillProcessor):
    """Backfill processor for leases_view."""

    def __init__(
        self,
        sf_client: SalesforceClient,
        dynamodb_resource: Optional[Any] = None,
    ):
        super().__init__(sf_client, dynamodb_resource)
        self.updater = LeasesViewUpdater(dynamodb_resource)

    def run(self, clear_first: bool = True) -> BackfillStats:
        """Run leases view backfill."""
        stats = BackfillStats(view_name="leases_view")
        start_time = time.time()

        try:
            if clear_first:
                self.clear_table(LEASES_VIEW_TABLE)

            # Query all Lease records with Tenant relationship
            # Note: ascendix__TermExpirationDate__c is the correct field (not ascendix__EndDate__c)
            # Updated 2025-12-14: Removed ascendix__Status__c and ascendix__Notes__c
            # (these fields do NOT exist on Lease object in Salesforce)
            # Using ascendix__Description__c instead of Notes
            soql = """
                SELECT Id, ascendix__Property__c, ascendix__TermExpirationDate__c,
                       ascendix__Tenant__c, ascendix__Description__c,
                       ascendix__Tenant__r.Name
                FROM ascendix__Lease__c
                WHERE ascendix__Property__c != null
            """

            records = self.sf_client.query(soql)
            stats.records_processed = len(records)

            for record in records:
                try:
                    event = CDCEvent(
                        object_type=LEASE_OBJECT,
                        record_id=record.get("Id", ""),
                        operation="create",
                        record_data=self._transform_record(record),
                    )
                    if self.updater.handle_create(event):
                        stats.records_succeeded += 1
                    else:
                        stats.records_failed += 1
                except Exception as e:
                    LOGGER.error(f"Error processing lease {record.get('Id')}: {e}")
                    stats.records_failed += 1

        except Exception as e:
            stats.error_message = str(e)
            LOGGER.error(f"Leases backfill error: {e}")

        stats.elapsed_seconds = time.time() - start_time
        return stats

    def _transform_record(self, record: Dict) -> Dict:
        """Transform Salesforce record to internal format."""
        # Updated 2025-12-14: Removed ascendix__Status__c and ascendix__Notes__c
        # (these fields do NOT exist on Lease object in Salesforce)
        tenant_ref = record.get("ascendix__Tenant__r") or {}
        return {
            "Id": record.get("Id"),
            "ascendix__Property__c": record.get("ascendix__Property__c"),
            "ascendix__TermExpirationDate__c": record.get("ascendix__TermExpirationDate__c"),
            "ascendix__Tenant__c": record.get("ascendix__Tenant__c"),
            # Use Description instead of Notes (Notes doesn't exist on Lease)
            "ascendix__Description__c": record.get("ascendix__Description__c"),
            "Tenant__r": {"Name": tenant_ref.get("Name")},
        }


class ActivitiesBackfillProcessor(BackfillProcessor):
    """Backfill processor for activities_agg."""

    def __init__(
        self,
        sf_client: SalesforceClient,
        dynamodb_resource: Optional[Any] = None,
    ):
        super().__init__(sf_client, dynamodb_resource)
        self.updater = ActivitiesAggUpdater(dynamodb_resource)

    def run(self, clear_first: bool = True) -> BackfillStats:
        """Run activities aggregation backfill."""
        stats = BackfillStats(view_name="activities_agg")
        start_time = time.time()

        try:
            if clear_first:
                self.clear_table(ACTIVITIES_AGG_TABLE)

            # Query activities from last 90 days
            ninety_days_ago = (
                datetime.now(timezone.utc) - timedelta(days=90)
            ).strftime("%Y-%m-%d")

            # Group activities by WhatId (entity)
            activities_by_entity: Dict[str, List[Dict]] = {}

            # Query Tasks
            task_soql = f"""
                SELECT Id, WhatId, WhoId, ActivityDate, CreatedDate
                FROM Task
                WHERE ActivityDate >= {ninety_days_ago}
                AND (WhatId != null OR WhoId != null)
            """
            tasks = self.sf_client.query(task_soql)

            for task in tasks:
                entity_id = task.get("WhatId") or task.get("WhoId")
                if entity_id:
                    if entity_id not in activities_by_entity:
                        activities_by_entity[entity_id] = []
                    activities_by_entity[entity_id].append(task)

            # Query Events
            event_soql = f"""
                SELECT Id, WhatId, WhoId, ActivityDate, CreatedDate
                FROM Event
                WHERE ActivityDate >= {ninety_days_ago}
                AND (WhatId != null OR WhoId != null)
            """
            events = self.sf_client.query(event_soql)

            for event in events:
                entity_id = event.get("WhatId") or event.get("WhoId")
                if entity_id:
                    if entity_id not in activities_by_entity:
                        activities_by_entity[entity_id] = []
                    activities_by_entity[entity_id].append(event)

            stats.records_processed = len(activities_by_entity)

            # Recalculate counts for each entity
            for entity_id, activities in activities_by_entity.items():
                try:
                    if self.updater.recalculate_windows(entity_id, activities):
                        stats.records_succeeded += 1
                    else:
                        stats.records_failed += 1
                except Exception as e:
                    LOGGER.error(f"Error processing entity {entity_id}: {e}")
                    stats.records_failed += 1

        except Exception as e:
            stats.error_message = str(e)
            LOGGER.error(f"Activities backfill error: {e}")

        stats.elapsed_seconds = time.time() - start_time
        return stats


class SalesBackfillProcessor(BackfillProcessor):
    """Backfill processor for sales_view."""

    def __init__(
        self,
        sf_client: SalesforceClient,
        dynamodb_resource: Optional[Any] = None,
    ):
        super().__init__(sf_client, dynamodb_resource)
        self.updater = SalesViewUpdater(dynamodb_resource)

    def run(self, clear_first: bool = True) -> BackfillStats:
        """Run sales view backfill."""
        stats = BackfillStats(view_name="sales_view")
        start_time = time.time()

        try:
            if clear_first:
                self.clear_table(SALES_VIEW_TABLE)

            # Query all Sale records with Broker relationships
            soql = """
                SELECT Id, ascendix__Property__c, ascendix__Stage__c,
                       ascendix__CloseDate__c, ascendix__Amount__c,
                       ascendix__PrimaryBroker__c, ascendix__SecondaryBroker__c,
                       ascendix__PrimaryBroker__r.Name,
                       ascendix__SecondaryBroker__r.Name
                FROM ascendix__Sale__c
            """

            records = self.sf_client.query(soql)
            stats.records_processed = len(records)

            for record in records:
                try:
                    event = CDCEvent(
                        object_type=SALE_OBJECT,
                        record_id=record.get("Id", ""),
                        operation="create",
                        record_data=self._transform_record(record),
                    )
                    if self.updater.handle_create(event):
                        stats.records_succeeded += 1
                    else:
                        stats.records_failed += 1
                except Exception as e:
                    LOGGER.error(f"Error processing sale {record.get('Id')}: {e}")
                    stats.records_failed += 1

        except Exception as e:
            stats.error_message = str(e)
            LOGGER.error(f"Sales backfill error: {e}")

        stats.elapsed_seconds = time.time() - start_time
        return stats

    def _transform_record(self, record: Dict) -> Dict:
        """Transform Salesforce record to internal format."""
        primary_broker = record.get("ascendix__PrimaryBroker__r") or {}
        secondary_broker = record.get("ascendix__SecondaryBroker__r") or {}
        return {
            "Id": record.get("Id"),
            "ascendix__Property__c": record.get("ascendix__Property__c"),
            "ascendix__Stage__c": record.get("ascendix__Stage__c"),
            "ascendix__CloseDate__c": record.get("ascendix__CloseDate__c"),
            "ascendix__Amount__c": record.get("ascendix__Amount__c"),
            "ascendix__PrimaryBroker__c": record.get("ascendix__PrimaryBroker__c"),
            "ascendix__SecondaryBroker__c": record.get("ascendix__SecondaryBroker__c"),
            "PrimaryBroker__r": {"Name": primary_broker.get("Name")},
            "SecondaryBroker__r": {"Name": secondary_broker.get("Name")},
        }


# =============================================================================
# Main Backfill Runner
# =============================================================================


class BackfillRunner:
    """
    Orchestrates backfill for all derived views.

    **Requirements: 10.2, 10.3**
    """

    def __init__(
        self,
        sf_client: Optional[SalesforceClient] = None,
        dynamodb_resource: Optional[Any] = None,
    ):
        self.sf_client = sf_client or SalesforceClient()
        self._dynamodb = dynamodb_resource

        self.processors = {
            "availability_view": AvailabilityBackfillProcessor(
                self.sf_client, dynamodb_resource
            ),
            "vacancy_view": VacancyBackfillProcessor(
                self.sf_client, dynamodb_resource
            ),
            "leases_view": LeasesBackfillProcessor(
                self.sf_client, dynamodb_resource
            ),
            "activities_agg": ActivitiesBackfillProcessor(
                self.sf_client, dynamodb_resource
            ),
            "sales_view": SalesBackfillProcessor(
                self.sf_client, dynamodb_resource
            ),
        }

    def run_all(
        self,
        clear_first: bool = True,
        parallel: bool = True,
        views: Optional[List[str]] = None,
    ) -> Dict[str, BackfillStats]:
        """
        Run backfill for all views.

        Args:
            clear_first: Clear tables before backfill
            parallel: Run backfills in parallel
            views: Optional list of specific views to backfill

        Returns:
            Dictionary of view name to BackfillStats
        """
        start_time = time.time()
        results: Dict[str, BackfillStats] = {}

        # Determine which views to process
        views_to_process = views or list(self.processors.keys())

        LOGGER.info(f"Starting backfill for views: {views_to_process}")

        if parallel:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {}
                for view_name in views_to_process:
                    processor = self.processors.get(view_name)
                    if processor:
                        future = executor.submit(processor.run, clear_first)
                        futures[future] = view_name

                for future in as_completed(futures):
                    view_name = futures[future]
                    try:
                        stats = future.result()
                        results[view_name] = stats
                        LOGGER.info(
                            f"Completed {view_name}: "
                            f"{stats.records_succeeded}/{stats.records_processed} "
                            f"in {stats.elapsed_seconds:.1f}s"
                        )
                    except Exception as e:
                        LOGGER.error(f"Error in {view_name} backfill: {e}")
                        results[view_name] = BackfillStats(
                            view_name=view_name, error_message=str(e)
                        )
        else:
            for view_name in views_to_process:
                processor = self.processors.get(view_name)
                if processor:
                    stats = processor.run(clear_first)
                    results[view_name] = stats
                    LOGGER.info(
                        f"Completed {view_name}: "
                        f"{stats.records_succeeded}/{stats.records_processed} "
                        f"in {stats.elapsed_seconds:.1f}s"
                    )

        total_time = time.time() - start_time
        LOGGER.info(f"Backfill complete in {total_time:.1f}s")

        return results


# =============================================================================
# Lambda Handler
# =============================================================================


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for derived view backfill.

    **Requirements: 10.2, 10.3**

    Event format:
    {
        "views": ["availability_view", "vacancy_view"],  // Optional, default all
        "clear_first": true,                             // Optional, default true
        "parallel": true                                 // Optional, default true
    }
    """
    LOGGER.info("Derived views backfill invoked")

    views = event.get("views")
    clear_first = event.get("clear_first", True)
    parallel = event.get("parallel", True)

    runner = BackfillRunner()
    results = runner.run_all(
        clear_first=clear_first,
        parallel=parallel,
        views=views,
    )

    # Build response
    response = {
        "success": True,
        "views": {},
        "total_records_processed": 0,
        "total_records_succeeded": 0,
        "total_records_failed": 0,
    }

    for view_name, stats in results.items():
        response["views"][view_name] = {
            "records_processed": stats.records_processed,
            "records_succeeded": stats.records_succeeded,
            "records_failed": stats.records_failed,
            "elapsed_seconds": stats.elapsed_seconds,
            "error": stats.error_message,
        }
        response["total_records_processed"] += stats.records_processed
        response["total_records_succeeded"] += stats.records_succeeded
        response["total_records_failed"] += stats.records_failed

        if stats.error_message:
            response["success"] = False

    LOGGER.info(
        f"Backfill complete: "
        f"{response['total_records_succeeded']}/{response['total_records_processed']} "
        f"records processed"
    )

    return response
