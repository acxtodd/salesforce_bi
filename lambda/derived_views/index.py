"""
Derived Views Maintenance Lambda.

Processes CDC events from Salesforce source objects and updates derived views
in DynamoDB. Supports create, update, and delete operations.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 17.1, 17.2, 17.3, 17.4**
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Callable

import boto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Environment variables for table names
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

# Object API names (Ascendix CRE package)
AVAILABILITY_OBJECT = "ascendix__Availability__c"
PROPERTY_OBJECT = "ascendix__Property__c"
LEASE_OBJECT = "ascendix__Lease__c"
SALE_OBJECT = "ascendix__Sale__c"
TASK_OBJECT = "Task"
EVENT_OBJECT = "Event"

# Clause detection patterns for lease notes
CLAUSE_PATTERNS = {
    "rofr": re.compile(r"\b(rofr|right\s+of\s+first\s+refusal)\b", re.IGNORECASE),
    "ti": re.compile(
        r"\b(ti|tenant\s+improvement|build\s*out|buildout)\b", re.IGNORECASE
    ),
    "noise": re.compile(r"\b(noise|quiet\s+hours|sound)\b", re.IGNORECASE),
    "hvac": re.compile(r"\b(hvac|heating|cooling|air\s+condition)\b", re.IGNORECASE),
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class CDCEvent:
    """
    Represents a CDC event from Salesforce.

    Attributes:
        object_type: Salesforce object API name
        record_id: Record ID
        operation: Operation type (create, update, delete)
        record_data: Full record data (for create/update)
        changed_fields: List of changed field names (for update)
        timestamp: Event timestamp
    """

    object_type: str
    record_id: str
    operation: str  # create, update, delete
    record_data: Dict[str, Any] = field(default_factory=dict)
    changed_fields: List[str] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_event(cls, event: Dict[str, Any]) -> "CDCEvent":
        """Create CDCEvent from Lambda event payload."""
        return cls(
            object_type=event.get("objectType", ""),
            record_id=event.get("recordId", ""),
            operation=event.get("operation", "update"),
            record_data=event.get("recordData", {}),
            changed_fields=event.get("changedFields", []),
            timestamp=event.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )


# =============================================================================
# View Updater Base Class
# =============================================================================


class ViewUpdater:
    """Base class for derived view updaters."""

    def __init__(self, dynamodb_resource: Optional[Any] = None):
        self._dynamodb = dynamodb_resource
        self._tables: Dict[str, Any] = {}

    @property
    def dynamodb(self):
        """Lazy-load DynamoDB resource."""
        if self._dynamodb is None:
            self._dynamodb = boto3.resource("dynamodb")
        return self._dynamodb

    def _get_table(self, table_name: str):
        """Get or create table resource."""
        if table_name not in self._tables:
            self._tables[table_name] = self.dynamodb.Table(table_name)
        return self._tables[table_name]

    def _put_item(self, table_name: str, item: Dict[str, Any]) -> bool:
        """Put an item to DynamoDB."""
        try:
            table = self._get_table(table_name)
            # Convert floats to Decimal for DynamoDB
            converted_item = self._convert_floats(item)
            table.put_item(Item=converted_item)
            return True
        except ClientError as e:
            LOGGER.error(f"DynamoDB put_item error: {e.response['Error']['Message']}")
            return False

    def _delete_item(self, table_name: str, key: Dict[str, Any]) -> bool:
        """Delete an item from DynamoDB."""
        try:
            table = self._get_table(table_name)
            table.delete_item(Key=key)
            return True
        except ClientError as e:
            LOGGER.error(
                f"DynamoDB delete_item error: {e.response['Error']['Message']}"
            )
            return False

    def _get_item(self, table_name: str, key: Dict[str, Any]) -> Optional[Dict]:
        """Get an item from DynamoDB."""
        try:
            table = self._get_table(table_name)
            response = table.get_item(Key=key)
            return response.get("Item")
        except ClientError as e:
            LOGGER.error(f"DynamoDB get_item error: {e.response['Error']['Message']}")
            return None

    def _update_item(
        self,
        table_name: str,
        key: Dict[str, Any],
        update_expr: str,
        expr_values: Dict[str, Any],
        expr_names: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Update an item in DynamoDB."""
        try:
            table = self._get_table(table_name)
            converted_values = self._convert_floats(expr_values)
            kwargs = {
                "Key": key,
                "UpdateExpression": update_expr,
                "ExpressionAttributeValues": converted_values,
            }
            if expr_names:
                kwargs["ExpressionAttributeNames"] = expr_names
            table.update_item(**kwargs)
            return True
        except ClientError as e:
            LOGGER.error(
                f"DynamoDB update_item error: {e.response['Error']['Message']}"
            )
            return False

    def _convert_floats(self, obj: Any) -> Any:
        """Convert floats to Decimal for DynamoDB."""
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {k: self._convert_floats(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_floats(v) for v in obj]
        return obj


# =============================================================================
# Availability View Updater (Requirement 5.1)
# =============================================================================


class AvailabilityViewUpdater(ViewUpdater):
    """
    Updates the availability_view derived view.

    **Requirements: 5.1, 17.1, 17.2, 17.3**

    Handles Availability object CDC events and denormalizes Property attributes.
    """

    def __init__(
        self,
        dynamodb_resource: Optional[Any] = None,
        table_name: Optional[str] = None,
    ):
        super().__init__(dynamodb_resource)
        self.table_name = table_name or AVAILABILITY_VIEW_TABLE

    def handle_create(self, event: CDCEvent) -> bool:
        """Handle Availability record creation."""
        return self._upsert_availability(event)

    def handle_update(self, event: CDCEvent) -> bool:
        """Handle Availability record update."""
        return self._upsert_availability(event)

    def handle_delete(self, event: CDCEvent) -> bool:
        """Handle Availability record deletion."""
        record = event.record_data
        property_id = record.get("ascendix__Property__c", "")
        availability_id = event.record_id

        if not property_id:
            LOGGER.warning(f"Cannot delete availability {availability_id}: no property_id")
            return False

        return self._delete_item(
            self.table_name,
            {"property_id": property_id, "availability_id": availability_id},
        )

    def _upsert_availability(self, event: CDCEvent) -> bool:
        """Create or update availability view record."""
        record = event.record_data
        property_id = record.get("ascendix__Property__c", "")
        availability_id = event.record_id

        if not property_id:
            LOGGER.warning(
                f"Cannot upsert availability {availability_id}: no property_id"
            )
            return False

        # Extract TI hints from space description (Availability has SpaceDescription, not Notes)
        ti_hints = self._extract_ti_hints(record.get("ascendix__SpaceDescription__c", ""))

        item = {
            "property_id": property_id,
            "availability_id": availability_id,
            "size": record.get("ascendix__Size__c", 0),
            "status": record.get("ascendix__Status__c", ""),
            "ti_hints": ti_hints,
            # Denormalized Property attributes (if available in record)
            "property_class": record.get("Property__r", {}).get(
                "ascendix__PropertyClass__c", ""
            ),
            # Updated 2025-12-10: Use RecordType instead of fake PropertyType__c
            "property_type": record.get("Property__r", {}).get(
                "RecordType", record.get("Property__r", {}).get("RecordType", {}).get("Name", "")
            ),
            "city": record.get("Property__r", {}).get("ascendix__City__c", ""),
            "state": record.get("Property__r", {}).get("ascendix__State__c", ""),
            # SubMarket is a lookup field, using relationship traversal
            "submarket": record.get("Property__r", {}).get(
                "ascendix__SubMarket__r", {}
            ).get("Name", ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        return self._put_item(self.table_name, item)

    def _extract_ti_hints(self, notes: str) -> str:
        """
        Extract tenant improvement hints from notes.

        **Requirements: 5.1**
        """
        if not notes:
            return ""

        hints = []
        # Look for TI-related terms
        ti_pattern = re.compile(
            r"(ti|tenant\s+improvement|build\s*out|allowance|renovation)",
            re.IGNORECASE,
        )
        if ti_pattern.search(notes):
            # Extract sentences containing TI references
            sentences = re.split(r"[.!?]+", notes)
            for sentence in sentences:
                if ti_pattern.search(sentence):
                    hints.append(sentence.strip())

        return " | ".join(hints[:3])  # Limit to 3 hints


# =============================================================================
# Vacancy View Updater (Requirement 5.2)
# =============================================================================


class VacancyViewUpdater(ViewUpdater):
    """
    Updates the vacancy_view derived view.

    **Requirements: 5.2, 17.1, 17.2, 17.3**

    Handles Property CDC events and recalculates vacancy percentage.
    Also updates when Availability changes affect the property.
    """

    def __init__(
        self,
        dynamodb_resource: Optional[Any] = None,
        table_name: Optional[str] = None,
    ):
        super().__init__(dynamodb_resource)
        self.table_name = table_name or VACANCY_VIEW_TABLE

    def handle_create(self, event: CDCEvent) -> bool:
        """Handle Property record creation."""
        return self._upsert_vacancy(event)

    def handle_update(self, event: CDCEvent) -> bool:
        """Handle Property record update."""
        return self._upsert_vacancy(event)

    def handle_delete(self, event: CDCEvent) -> bool:
        """Handle Property record deletion."""
        property_id = event.record_id
        return self._delete_item(self.table_name, {"property_id": property_id})

    def handle_availability_change(
        self, property_id: str, available_sqft_delta: float
    ) -> bool:
        """
        Update vacancy when Availability changes.

        Called when Availability records are created/updated/deleted.
        """
        existing = self._get_item(self.table_name, {"property_id": property_id})
        if not existing:
            LOGGER.warning(f"Cannot update vacancy for property {property_id}: not found")
            return False

        current_available = float(existing.get("available_sqft", 0))
        total_sqft = float(existing.get("total_sqft", 1))

        new_available = max(0, current_available + available_sqft_delta)
        new_vacancy_pct = (new_available / total_sqft * 100) if total_sqft > 0 else 0

        return self._update_item(
            self.table_name,
            {"property_id": property_id},
            "SET available_sqft = :avail, vacancy_pct = :pct, "
            "vacancy_pct_bucket = :bucket, updated_at = :ts",
            {
                ":avail": new_available,
                ":pct": new_vacancy_pct,
                ":bucket": self._get_vacancy_bucket(new_vacancy_pct),
                ":ts": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _upsert_vacancy(self, event: CDCEvent) -> bool:
        """Create or update vacancy view record."""
        record = event.record_data
        property_id = event.record_id

        # Updated 2025-12-10: Use real SF field names from Schema Discovery
        total_sqft = float(record.get("ascendix__TotalBuildingArea__c", 0) or 0)
        available_sqft = float(record.get("ascendix__TotalAvailableArea__c", 0) or 0)

        # Calculate vacancy percentage
        vacancy_pct = (available_sqft / total_sqft * 100) if total_sqft > 0 else 0

        item = {
            "property_id": property_id,
            "vacancy_pct": vacancy_pct,
            "vacancy_pct_bucket": self._get_vacancy_bucket(vacancy_pct),
            "available_sqft": available_sqft,
            "total_sqft": total_sqft,
            "property_class": record.get("ascendix__PropertyClass__c", ""),
            # Updated 2025-12-10: Use RecordType instead of fake PropertyType__c
            "property_type": record.get("RecordType", record.get("RecordType", {}).get("Name", "") if isinstance(record.get("RecordType"), dict) else record.get("RecordType", "")),
            "city": record.get("ascendix__City__c", ""),
            "state": record.get("ascendix__State__c", ""),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        return self._put_item(self.table_name, item)

    def _get_vacancy_bucket(self, vacancy_pct: float) -> str:
        """
        Get vacancy percentage bucket for GSI.

        Buckets: 0-5%, 5-10%, 10-15%, 15-20%, 20-25%, 25-30%, 30+%
        """
        if vacancy_pct < 5:
            return "0-5"
        elif vacancy_pct < 10:
            return "5-10"
        elif vacancy_pct < 15:
            return "10-15"
        elif vacancy_pct < 20:
            return "15-20"
        elif vacancy_pct < 25:
            return "20-25"
        elif vacancy_pct < 30:
            return "25-30"
        else:
            return "30+"


# =============================================================================
# Leases View Updater (Requirement 5.3)
# =============================================================================


class LeasesViewUpdater(ViewUpdater):
    """
    Updates the leases_view derived view.

    **Requirements: 5.3, 17.1, 17.2, 17.3**

    Handles Lease CDC events, extracts clause flags from notes,
    and denormalizes tenant info.
    """

    def __init__(
        self,
        dynamodb_resource: Optional[Any] = None,
        table_name: Optional[str] = None,
    ):
        super().__init__(dynamodb_resource)
        self.table_name = table_name or LEASES_VIEW_TABLE

    def handle_create(self, event: CDCEvent) -> bool:
        """Handle Lease record creation."""
        return self._upsert_lease(event)

    def handle_update(self, event: CDCEvent) -> bool:
        """Handle Lease record update."""
        return self._upsert_lease(event)

    def handle_delete(self, event: CDCEvent) -> bool:
        """Handle Lease record deletion."""
        record = event.record_data
        property_id = record.get("ascendix__Property__c", "")
        lease_id = event.record_id

        if not property_id:
            LOGGER.warning(f"Cannot delete lease {lease_id}: no property_id")
            return False

        return self._delete_item(
            self.table_name,
            {"property_id": property_id, "lease_id": lease_id},
        )

    def _upsert_lease(self, event: CDCEvent) -> bool:
        """Create or update lease view record."""
        record = event.record_data
        property_id = record.get("ascendix__Property__c", "")
        lease_id = event.record_id

        if not property_id:
            LOGGER.warning(f"Cannot upsert lease {lease_id}: no property_id")
            return False

        # Extract clause flags from description (Lease has Description, not Notes)
        description = record.get("ascendix__Description__c", "") or ""
        clause_flags = self._extract_clause_flags(description)

        # Parse end date (correct field: ascendix__TermExpirationDate__c)
        end_date = record.get("ascendix__TermExpirationDate__c", "")
        end_date_month = ""
        if end_date:
            try:
                # Extract YYYY-MM from date
                end_date_month = end_date[:7] if len(end_date) >= 7 else ""
            except Exception:
                pass

        # Get tenant info (denormalized)
        tenant_info = record.get("Tenant__r", {}) or {}

        item = {
            "property_id": property_id,
            "lease_id": lease_id,
            "end_date": end_date,
            "end_date_month": end_date_month,
            "tenant_id": record.get("ascendix__Tenant__c", ""),
            "tenant_name": tenant_info.get("Name", ""),
            # Note: Lease object does NOT have ascendix__Status__c field in Salesforce
            # Status is intentionally omitted from the view
            "has_rofr": clause_flags.get("rofr", False),
            "has_ti": clause_flags.get("ti", False),
            "has_noise_clause": clause_flags.get("noise", False),
            "has_hvac_clause": clause_flags.get("hvac", False),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        return self._put_item(self.table_name, item)

    def _extract_clause_flags(self, notes: str) -> Dict[str, bool]:
        """
        Extract clause flags from lease notes.

        **Requirements: 5.3**

        Detects: ROFR, TI, noise, HVAC clauses.
        """
        flags = {}
        for clause_name, pattern in CLAUSE_PATTERNS.items():
            flags[clause_name] = bool(pattern.search(notes))
        return flags


# =============================================================================
# Activities Aggregation Updater (Requirement 5.4)
# =============================================================================


class ActivitiesAggUpdater(ViewUpdater):
    """
    Updates the activities_agg derived view.

    **Requirements: 5.4, 17.1, 17.2, 17.3**

    Handles Task/Event CDC events and maintains rolling activity counts
    for 7/30/90 day windows.
    """

    def __init__(
        self,
        dynamodb_resource: Optional[Any] = None,
        table_name: Optional[str] = None,
    ):
        super().__init__(dynamodb_resource)
        self.table_name = table_name or ACTIVITIES_AGG_TABLE

    def handle_create(self, event: CDCEvent) -> bool:
        """Handle Task/Event record creation."""
        return self._update_activity_counts(event, delta=1)

    def handle_update(self, event: CDCEvent) -> bool:
        """
        Handle Task/Event record update.

        For updates, we only need to update if WhatId changed.
        """
        if "WhatId" in event.changed_fields:
            # Entity association changed - need to decrement old and increment new
            # For simplicity, just update the current entity
            return self._update_activity_counts(event, delta=0)
        return True

    def handle_delete(self, event: CDCEvent) -> bool:
        """Handle Task/Event record deletion."""
        return self._update_activity_counts(event, delta=-1)

    def _update_activity_counts(self, event: CDCEvent, delta: int) -> bool:
        """Update activity counts for the related entity."""
        record = event.record_data
        entity_id = record.get("WhatId", "") or record.get("WhoId", "")

        if not entity_id:
            LOGGER.debug(f"Activity {event.record_id} has no related entity")
            return True

        # Determine entity type from ID prefix
        entity_type = self._get_entity_type(entity_id)

        # Get or create aggregation record
        existing = self._get_item(self.table_name, {"entity_id": entity_id})

        activity_date = record.get("ActivityDate", "") or record.get(
            "CreatedDate", ""
        )[:10]

        if existing:
            # Update existing counts
            new_7d = max(0, int(existing.get("count_7d", 0)) + delta)
            new_30d = max(0, int(existing.get("count_30d", 0)) + delta)
            new_90d = max(0, int(existing.get("count_90d", 0)) + delta)

            # Update last activity date if this is newer
            last_date = existing.get("last_activity_date", "")
            if delta > 0 and activity_date > last_date:
                last_date = activity_date

            return self._update_item(
                self.table_name,
                {"entity_id": entity_id},
                "SET count_7d = :c7, count_30d = :c30, count_90d = :c90, "
                "last_activity_date = :last, updated_at = :ts",
                {
                    ":c7": new_7d,
                    ":c30": new_30d,
                    ":c90": new_90d,
                    ":last": last_date,
                    ":ts": datetime.now(timezone.utc).isoformat(),
                },
            )
        else:
            # Create new aggregation record
            if delta <= 0:
                return True  # Nothing to create for delete

            item = {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "count_7d": max(0, delta),
                "count_30d": max(0, delta),
                "count_90d": max(0, delta),
                "last_activity_date": activity_date,
                "maintenance_only_count": 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            return self._put_item(self.table_name, item)

    def _get_entity_type(self, entity_id: str) -> str:
        """Determine entity type from Salesforce ID prefix."""
        if not entity_id or len(entity_id) < 3:
            return "Unknown"

        prefix = entity_id[:3]
        prefix_map = {
            "001": "Account",
            "003": "Contact",
            "006": "Opportunity",
            "00Q": "Lead",
            "a0": "Property",  # Custom object prefix varies
        }

        # Check exact matches first
        if prefix in prefix_map:
            return prefix_map[prefix]

        # Check partial matches for custom objects
        if entity_id.startswith("a0"):
            return "Property"

        return "Unknown"

    def recalculate_windows(self, entity_id: str, activities: List[Dict]) -> bool:
        """
        Recalculate activity counts from full activity list.

        Used during backfill operations.
        """
        now = datetime.now(timezone.utc).date()
        day_7 = now - timedelta(days=7)
        day_30 = now - timedelta(days=30)
        day_90 = now - timedelta(days=90)

        count_7d = 0
        count_30d = 0
        count_90d = 0
        last_date = ""

        for activity in activities:
            activity_date_str = activity.get("ActivityDate", "")
            if not activity_date_str:
                continue

            try:
                activity_date = datetime.strptime(
                    activity_date_str[:10], "%Y-%m-%d"
                ).date()

                if activity_date >= day_7:
                    count_7d += 1
                if activity_date >= day_30:
                    count_30d += 1
                if activity_date >= day_90:
                    count_90d += 1

                if activity_date_str > last_date:
                    last_date = activity_date_str
            except ValueError:
                continue

        entity_type = self._get_entity_type(entity_id)

        item = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "count_7d": count_7d,
            "count_30d": count_30d,
            "count_90d": count_90d,
            "last_activity_date": last_date,
            "maintenance_only_count": 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        return self._put_item(self.table_name, item)


# =============================================================================
# Sales View Updater (Requirement 5.5)
# =============================================================================


class SalesViewUpdater(ViewUpdater):
    """
    Updates the sales_view derived view.

    **Requirements: 5.5, 17.1, 17.2, 17.3**

    Handles Sale CDC events and denormalizes broker info.
    """

    def __init__(
        self,
        dynamodb_resource: Optional[Any] = None,
        table_name: Optional[str] = None,
    ):
        super().__init__(dynamodb_resource)
        self.table_name = table_name or SALES_VIEW_TABLE

    def handle_create(self, event: CDCEvent) -> bool:
        """Handle Sale record creation."""
        return self._upsert_sale(event)

    def handle_update(self, event: CDCEvent) -> bool:
        """Handle Sale record update."""
        return self._upsert_sale(event)

    def handle_delete(self, event: CDCEvent) -> bool:
        """Handle Sale record deletion."""
        sale_id = event.record_id
        return self._delete_item(self.table_name, {"sale_id": sale_id})

    def _upsert_sale(self, event: CDCEvent) -> bool:
        """Create or update sale view record."""
        record = event.record_data
        sale_id = event.record_id

        # Extract broker information
        broker_ids = []
        broker_names = []

        # Primary broker
        primary_broker_id = record.get("ascendix__PrimaryBroker__c", "")
        if primary_broker_id:
            broker_ids.append(primary_broker_id)
            broker_info = record.get("PrimaryBroker__r", {}) or {}
            if broker_info.get("Name"):
                broker_names.append(broker_info["Name"])

        # Secondary broker (if exists)
        secondary_broker_id = record.get("ascendix__SecondaryBroker__c", "")
        if secondary_broker_id:
            broker_ids.append(secondary_broker_id)
            broker_info = record.get("SecondaryBroker__r", {}) or {}
            if broker_info.get("Name"):
                broker_names.append(broker_info["Name"])

        item = {
            "sale_id": sale_id,
            "property_id": record.get("ascendix__Property__c", ""),
            "stage": record.get("ascendix__Stage__c", ""),
            "close_date": record.get("ascendix__CloseDate__c", ""),
            "broker_ids": broker_ids,
            "broker_names": broker_names,
            "amount": record.get("ascendix__Amount__c", 0),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        return self._put_item(self.table_name, item)


# =============================================================================
# Main Handler
# =============================================================================


class DerivedViewsHandler:
    """
    Main handler for derived view maintenance.

    Routes CDC events to appropriate view updaters.
    """

    def __init__(self, dynamodb_resource: Optional[Any] = None):
        self.availability_updater = AvailabilityViewUpdater(dynamodb_resource)
        self.vacancy_updater = VacancyViewUpdater(dynamodb_resource)
        self.leases_updater = LeasesViewUpdater(dynamodb_resource)
        self.activities_updater = ActivitiesAggUpdater(dynamodb_resource)
        self.sales_updater = SalesViewUpdater(dynamodb_resource)

        # Map object types to handlers
        self._handlers: Dict[str, Dict[str, Callable]] = {
            AVAILABILITY_OBJECT: {
                "create": self._handle_availability,
                "update": self._handle_availability,
                "delete": self._handle_availability,
            },
            PROPERTY_OBJECT: {
                "create": self._handle_property,
                "update": self._handle_property,
                "delete": self._handle_property,
            },
            LEASE_OBJECT: {
                "create": self._handle_lease,
                "update": self._handle_lease,
                "delete": self._handle_lease,
            },
            TASK_OBJECT: {
                "create": self._handle_activity,
                "update": self._handle_activity,
                "delete": self._handle_activity,
            },
            EVENT_OBJECT: {
                "create": self._handle_activity,
                "update": self._handle_activity,
                "delete": self._handle_activity,
            },
            SALE_OBJECT: {
                "create": self._handle_sale,
                "update": self._handle_sale,
                "delete": self._handle_sale,
            },
        }

    def handle_event(self, event: CDCEvent) -> Dict[str, Any]:
        """
        Process a CDC event and update affected derived views.

        **Requirements: 17.1, 17.2, 17.3**
        """
        start_time = time.time()

        object_type = event.object_type
        operation = event.operation.lower()

        LOGGER.info(
            f"Processing CDC event: {object_type} {operation} {event.record_id}"
        )

        results = {"success": True, "updates": [], "errors": []}

        # Get handlers for this object type
        handlers = self._handlers.get(object_type, {})
        handler = handlers.get(operation)

        if handler:
            try:
                success = handler(event)
                results["updates"].append(
                    {
                        "object_type": object_type,
                        "operation": operation,
                        "success": success,
                    }
                )
                if not success:
                    results["success"] = False
            except Exception as e:
                LOGGER.error(f"Handler error for {object_type} {operation}: {e}")
                results["errors"].append(str(e))
                results["success"] = False
        else:
            LOGGER.debug(f"No handler for {object_type} {operation}")

        elapsed_ms = (time.time() - start_time) * 1000
        results["elapsed_ms"] = elapsed_ms

        LOGGER.info(f"CDC event processed in {elapsed_ms:.1f}ms: {results['success']}")

        return results

    def _handle_availability(self, event: CDCEvent) -> bool:
        """Handle Availability object events."""
        operation = event.operation.lower()

        if operation == "create":
            return self.availability_updater.handle_create(event)
        elif operation == "update":
            return self.availability_updater.handle_update(event)
        elif operation == "delete":
            return self.availability_updater.handle_delete(event)
        return False

    def _handle_property(self, event: CDCEvent) -> bool:
        """Handle Property object events."""
        operation = event.operation.lower()

        if operation == "create":
            return self.vacancy_updater.handle_create(event)
        elif operation == "update":
            return self.vacancy_updater.handle_update(event)
        elif operation == "delete":
            return self.vacancy_updater.handle_delete(event)
        return False

    def _handle_lease(self, event: CDCEvent) -> bool:
        """Handle Lease object events."""
        operation = event.operation.lower()

        if operation == "create":
            return self.leases_updater.handle_create(event)
        elif operation == "update":
            return self.leases_updater.handle_update(event)
        elif operation == "delete":
            return self.leases_updater.handle_delete(event)
        return False

    def _handle_activity(self, event: CDCEvent) -> bool:
        """Handle Task/Event object events."""
        operation = event.operation.lower()

        if operation == "create":
            return self.activities_updater.handle_create(event)
        elif operation == "update":
            return self.activities_updater.handle_update(event)
        elif operation == "delete":
            return self.activities_updater.handle_delete(event)
        return False

    def _handle_sale(self, event: CDCEvent) -> bool:
        """Handle Sale object events."""
        operation = event.operation.lower()

        if operation == "create":
            return self.sales_updater.handle_create(event)
        elif operation == "update":
            return self.sales_updater.handle_update(event)
        elif operation == "delete":
            return self.sales_updater.handle_delete(event)
        return False


# =============================================================================
# Lambda Handler
# =============================================================================


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda handler for derived view maintenance.

    **Requirements: 17.1, 17.2, 17.3, 17.4**

    Expects event format:
    {
        "objectType": "ascendix__Availability__c",
        "recordId": "a0XXXXX",
        "operation": "create|update|delete",
        "recordData": { ... },
        "changedFields": ["field1", "field2"],
        "timestamp": "2025-01-01T00:00:00Z"
    }

    Or batch format:
    {
        "records": [
            { "objectType": ..., "recordId": ..., ... },
            ...
        ]
    }
    """
    LOGGER.info(f"Derived views handler invoked")

    handler = DerivedViewsHandler()
    results = {"processed": 0, "succeeded": 0, "failed": 0, "details": []}

    # Handle batch or single event
    if "records" in event:
        records = event["records"]
    else:
        records = [event]

    for record in records:
        try:
            cdc_event = CDCEvent.from_event(record)
            result = handler.handle_event(cdc_event)

            results["processed"] += 1
            if result["success"]:
                results["succeeded"] += 1
            else:
                results["failed"] += 1

            results["details"].append(
                {
                    "record_id": cdc_event.record_id,
                    "success": result["success"],
                    "elapsed_ms": result.get("elapsed_ms", 0),
                }
            )

        except Exception as e:
            LOGGER.error(f"Error processing record: {e}")
            results["processed"] += 1
            results["failed"] += 1
            results["details"].append({"error": str(e)})

    LOGGER.info(
        f"Derived views update complete: "
        f"{results['succeeded']}/{results['processed']} succeeded"
    )

    return results
