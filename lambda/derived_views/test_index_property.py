"""
Property-Based Tests for Derived Views Maintenance.

**Feature: graph-aware-zero-config-retrieval**

Tests the following properties:
- Property 10: Derived View Maintenance Consistency (Requirements 5.1-5.5, 17.1-17.3)
"""

import os
import sys
from typing import Any, Dict, List, Optional
from decimal import Decimal
import importlib.util

import pytest
from hypothesis import given, strategies as st, settings, assume

# Load the module directly from file path to avoid import conflicts
_module_name = "derived_views_index_prop"
_module_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.py")
_spec = importlib.util.spec_from_file_location(_module_name, _module_path)
_derived_views_module = importlib.util.module_from_spec(_spec)
# Register in sys.modules BEFORE exec_module to fix dataclass issues in Python 3.14
sys.modules[_module_name] = _derived_views_module
_spec.loader.exec_module(_derived_views_module)

# Import from the loaded module
CDCEvent = _derived_views_module.CDCEvent
DerivedViewsHandler = _derived_views_module.DerivedViewsHandler
AvailabilityViewUpdater = _derived_views_module.AvailabilityViewUpdater
VacancyViewUpdater = _derived_views_module.VacancyViewUpdater
LeasesViewUpdater = _derived_views_module.LeasesViewUpdater
ActivitiesAggUpdater = _derived_views_module.ActivitiesAggUpdater
SalesViewUpdater = _derived_views_module.SalesViewUpdater
AVAILABILITY_OBJECT = _derived_views_module.AVAILABILITY_OBJECT
PROPERTY_OBJECT = _derived_views_module.PROPERTY_OBJECT
LEASE_OBJECT = _derived_views_module.LEASE_OBJECT
SALE_OBJECT = _derived_views_module.SALE_OBJECT
TASK_OBJECT = _derived_views_module.TASK_OBJECT
EVENT_OBJECT = _derived_views_module.EVENT_OBJECT


# =============================================================================
# Mock DynamoDB for Property Testing
# =============================================================================


class PropertyTestDynamoDBTable:
    """Mock DynamoDB table for property testing."""

    def __init__(self):
        self.items: Dict[str, Dict[str, Any]] = {}
        self._key_cache: Dict[str, str] = {}  # Maps record_id to composite key

    def put_item(self, Item: Dict[str, Any]) -> None:
        """Store an item."""
        # Use first two keys for composite key, or just first if only one
        keys = list(Item.keys())[:2]
        key = "#".join(str(Item.get(k, "")) for k in keys)
        self.items[key] = Item.copy()

        # Cache for single-key deletes (e.g., sale_id)
        for k in keys:
            self._key_cache[str(Item.get(k, ""))] = key

    def get_item(self, Key: Dict[str, Any]) -> Dict[str, Any]:
        """Get an item."""
        key = "#".join(str(v) for v in Key.values())
        item = self.items.get(key)
        return {"Item": item} if item else {}

    def delete_item(self, Key: Dict[str, Any]) -> None:
        """Delete an item."""
        # Try composite key first
        key = "#".join(str(v) for v in Key.values())
        if key in self.items:
            del self.items[key]
            return

        # Try single key lookup via cache
        for v in Key.values():
            cached_key = self._key_cache.get(str(v))
            if cached_key and cached_key in self.items:
                del self.items[cached_key]
                return

    def update_item(self, **kwargs) -> None:
        """Update an item."""
        key = "#".join(str(v) for v in kwargs["Key"].values())
        if key not in self.items:
            self.items[key] = {}
        self.items[key]["_updated"] = True


class PropertyTestDynamoDBResource:
    """Mock DynamoDB resource for property testing."""

    def __init__(self):
        self.tables: Dict[str, PropertyTestDynamoDBTable] = {}

    def Table(self, name: str) -> PropertyTestDynamoDBTable:
        if name not in self.tables:
            self.tables[name] = PropertyTestDynamoDBTable()
        return self.tables[name]


# =============================================================================
# Strategies for Property Testing
# =============================================================================

# Record ID strategy
record_id_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=15,
    max_size=18,
)

# Operation strategy
operation_strategy = st.sampled_from(["create", "update", "delete"])

# Size strategy (square feet)
size_strategy = st.integers(min_value=0, max_value=1000000)

# Percentage strategy
percentage_strategy = st.floats(min_value=0, max_value=100, allow_nan=False)

# Status strategy
status_strategy = st.sampled_from(["Active", "Pending", "Available", "Leased", "Closed"])

# Date strategy (YYYY-MM-DD format)
date_strategy = st.dates().map(lambda d: d.isoformat())

# Notes with possible clauses
clause_keywords = ["ROFR", "TI", "tenant improvement", "quiet hours", "HVAC", "noise"]
notes_strategy = st.one_of(
    st.just(""),
    st.text(min_size=0, max_size=200),
    st.sampled_from(clause_keywords).map(lambda k: f"Includes {k} clause"),
)


@st.composite
def availability_record_strategy(draw):
    """Generate random availability record data."""
    # Updated 2025-12-14: Use SpaceDescription (Notes doesn't exist on Availability)
    return {
        "ascendix__Property__c": draw(record_id_strategy),
        "ascendix__Size__c": draw(size_strategy),
        "ascendix__Status__c": draw(status_strategy),
        "ascendix__SpaceDescription__c": draw(notes_strategy),
    }


@st.composite
def property_record_strategy(draw):
    """Generate random property record data."""
    total = draw(st.integers(min_value=1000, max_value=1000000))
    available = draw(st.integers(min_value=0, max_value=total))
    return {
        "ascendix__TotalSqFt__c": total,
        "ascendix__AvailableSqFt__c": available,
        "ascendix__PropertyClass__c": draw(st.sampled_from(["A", "B", "C"])),
        "ascendix__City__c": draw(st.text(min_size=1, max_size=20)),
        "ascendix__State__c": draw(st.sampled_from(["TX", "CA", "NY", "FL"])),
    }


@st.composite
def lease_record_strategy(draw):
    """Generate random lease record data."""
    # Updated 2025-12-14: Removed Status (doesn't exist on Lease)
    # Using Description instead of Notes (Notes doesn't exist on Lease)
    return {
        "ascendix__Property__c": draw(record_id_strategy),
        "ascendix__TermExpirationDate__c": draw(date_strategy),
        "ascendix__Tenant__c": draw(record_id_strategy),
        "ascendix__Description__c": draw(notes_strategy),
    }


@st.composite
def activity_record_strategy(draw):
    """Generate random activity (Task/Event) record data."""
    # Generate a valid SF ID prefix for WhatId
    prefix = draw(st.sampled_from(["001", "003", "006"]))
    what_id = prefix + draw(
        st.text(
            alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            min_size=12,
            max_size=12,
        )
    )
    return {
        "WhatId": what_id,
        "ActivityDate": draw(date_strategy),
        "CreatedDate": draw(date_strategy) + "T00:00:00Z",
    }


@st.composite
def sale_record_strategy(draw):
    """Generate random sale record data."""
    return {
        "ascendix__Property__c": draw(record_id_strategy),
        "ascendix__Stage__c": draw(
            st.sampled_from(["Prospecting", "Negotiation", "Due Diligence", "Closed"])
        ),
        "ascendix__CloseDate__c": draw(date_strategy),
        "ascendix__Amount__c": draw(st.integers(min_value=0, max_value=100000000)),
        "ascendix__PrimaryBroker__c": draw(record_id_strategy),
    }


# =============================================================================
# Property 10: Derived View Maintenance Consistency
# Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 17.1, 17.2, 17.3
# =============================================================================


class TestProperty10DerivedViewMaintenance:
    """
    Property 10: Derived View Maintenance Consistency

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 17.1, 17.2, 17.3**

    Properties tested:
    1. Create operations always add records to views
    2. Delete operations always remove records from views
    3. Update operations preserve record existence
    4. Clause extraction is deterministic
    5. Vacancy calculations are consistent
    """

    @given(
        record_id=record_id_strategy,
        record_data=availability_record_strategy(),
    )
    @settings(max_examples=50, deadline=None)
    def test_availability_create_adds_record(
        self, record_id: str, record_data: Dict
    ):
        """
        Property: Create operation always adds availability record to view.

        For any valid availability record, handle_create should succeed
        and the record should exist in the view.
        """
        dynamodb = PropertyTestDynamoDBResource()
        updater = AvailabilityViewUpdater(dynamodb_resource=dynamodb)

        event = CDCEvent(
            object_type=AVAILABILITY_OBJECT,
            record_id=record_id,
            operation="create",
            record_data=record_data,
        )

        result = updater.handle_create(event)

        # Should succeed if property_id is present
        if record_data.get("ascendix__Property__c"):
            assert result is True, "Create should succeed with valid property_id"
            table = dynamodb.tables[updater.table_name]
            assert len(table.items) == 1, "One record should be in view"
        else:
            assert result is False, "Create should fail without property_id"

    @given(
        record_id=record_id_strategy,
        record_data=property_record_strategy(),
    )
    @settings(max_examples=50, deadline=None)
    def test_vacancy_calculation_consistent(
        self, record_id: str, record_data: Dict
    ):
        """
        Property: Vacancy calculation is mathematically consistent.

        vacancy_pct = (available_sqft / total_sqft) * 100
        """
        dynamodb = PropertyTestDynamoDBResource()
        updater = VacancyViewUpdater(dynamodb_resource=dynamodb)

        event = CDCEvent(
            object_type=PROPERTY_OBJECT,
            record_id=record_id,
            operation="create",
            record_data=record_data,
        )

        result = updater.handle_create(event)
        assert result is True

        table = dynamodb.tables[updater.table_name]
        assert len(table.items) == 1

        # Get the stored item
        item = list(table.items.values())[0]

        # Calculate expected vacancy
        total = float(record_data.get("ascendix__TotalSqFt__c", 0))
        available = float(record_data.get("ascendix__AvailableSqFt__c", 0))
        expected_pct = (available / total * 100) if total > 0 else 0

        # Compare (with Decimal conversion tolerance)
        stored_pct = float(item["vacancy_pct"])
        assert abs(stored_pct - expected_pct) < 0.01, (
            f"Vacancy {stored_pct} should match calculated {expected_pct}"
        )

    @given(
        record_id=record_id_strategy,
        record_data=lease_record_strategy(),
    )
    @settings(max_examples=50, deadline=None)
    def test_lease_clause_extraction_deterministic(
        self, record_id: str, record_data: Dict
    ):
        """
        Property: Clause extraction is deterministic.

        Running clause extraction twice on the same notes should
        produce identical results.
        """
        dynamodb = PropertyTestDynamoDBResource()
        updater = LeasesViewUpdater(dynamodb_resource=dynamodb)

        # Updated 2025-12-14: Use Description (Notes doesn't exist on Lease)
        notes = record_data.get("ascendix__Description__c", "")

        # Extract clauses twice
        flags1 = updater._extract_clause_flags(notes)
        flags2 = updater._extract_clause_flags(notes)

        # Should be identical
        assert flags1 == flags2, "Clause extraction should be deterministic"

    @given(
        record_id=record_id_strategy,
        record_data=activity_record_strategy(),
    )
    @settings(max_examples=50, deadline=None)
    def test_activity_entity_type_detection(
        self, record_id: str, record_data: Dict
    ):
        """
        Property: Entity type detection is consistent with ID prefix.

        Entity type should always be correctly detected from ID prefix.
        """
        dynamodb = PropertyTestDynamoDBResource()
        updater = ActivitiesAggUpdater(dynamodb_resource=dynamodb)

        what_id = record_data.get("WhatId", "")
        entity_type = updater._get_entity_type(what_id)

        # Verify entity type matches expected
        if what_id.startswith("001"):
            assert entity_type == "Account"
        elif what_id.startswith("003"):
            assert entity_type == "Contact"
        elif what_id.startswith("006"):
            assert entity_type == "Opportunity"
        elif what_id.startswith("00Q"):
            assert entity_type == "Lead"
        else:
            # Custom objects or unknown
            assert entity_type in ["Property", "Unknown"]

    @given(
        record_id=record_id_strategy,
        record_data=sale_record_strategy(),
    )
    @settings(max_examples=50, deadline=None)
    def test_sale_create_then_delete_removes_record(
        self, record_id: str, record_data: Dict
    ):
        """
        Property: Create followed by delete removes the record.

        After creating and then deleting a sale, the view should be empty.
        """
        dynamodb = PropertyTestDynamoDBResource()
        updater = SalesViewUpdater(dynamodb_resource=dynamodb)

        # Create event
        create_event = CDCEvent(
            object_type=SALE_OBJECT,
            record_id=record_id,
            operation="create",
            record_data=record_data,
        )
        create_result = updater.handle_create(create_event)
        assert create_result is True

        # Verify record exists
        table = dynamodb.tables[updater.table_name]
        assert len(table.items) == 1

        # Delete event
        delete_event = CDCEvent(
            object_type=SALE_OBJECT,
            record_id=record_id,
            operation="delete",
            record_data={},
        )
        delete_result = updater.handle_delete(delete_event)
        assert delete_result is True

        # Verify record removed
        assert len(table.items) == 0, "Record should be removed after delete"

    @given(vacancy_pct=st.floats(min_value=0, max_value=100, allow_nan=False))
    @settings(max_examples=100, deadline=None)
    def test_vacancy_bucket_covers_all_values(self, vacancy_pct: float):
        """
        Property: Vacancy bucket assignment covers all valid percentages.

        Any vacancy percentage from 0-100 should map to a valid bucket.
        """
        dynamodb = PropertyTestDynamoDBResource()
        updater = VacancyViewUpdater(dynamodb_resource=dynamodb)

        bucket = updater._get_vacancy_bucket(vacancy_pct)

        valid_buckets = ["0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30+"]
        assert bucket in valid_buckets, f"Bucket {bucket} should be valid"

        # Verify bucket is appropriate for value
        if vacancy_pct < 5:
            assert bucket == "0-5"
        elif vacancy_pct < 10:
            assert bucket == "5-10"
        elif vacancy_pct < 15:
            assert bucket == "10-15"
        elif vacancy_pct < 20:
            assert bucket == "15-20"
        elif vacancy_pct < 25:
            assert bucket == "20-25"
        elif vacancy_pct < 30:
            assert bucket == "25-30"
        else:
            assert bucket == "30+"

    @given(
        operations=st.lists(
            operation_strategy,
            min_size=1,
            max_size=10,
        ),
        record_data=availability_record_strategy(),
    )
    @settings(max_examples=30, deadline=None)
    def test_operation_sequence_consistency(
        self, operations: List[str], record_data: Dict
    ):
        """
        Property: Sequence of operations results in consistent state.

        After any sequence of create/update/delete operations,
        the final state should be consistent.
        """
        assume(record_data.get("ascendix__Property__c"))

        dynamodb = PropertyTestDynamoDBResource()
        updater = AvailabilityViewUpdater(dynamodb_resource=dynamodb)

        record_id = "test_record_001"

        for op in operations:
            event = CDCEvent(
                object_type=AVAILABILITY_OBJECT,
                record_id=record_id,
                operation=op,
                record_data=record_data,
            )

            if op == "create":
                updater.handle_create(event)
            elif op == "update":
                updater.handle_update(event)
            elif op == "delete":
                updater.handle_delete(event)

        table = dynamodb.tables[updater.table_name]

        # Final state depends on last operation
        last_op = operations[-1]
        if last_op == "delete":
            assert len(table.items) == 0, "Should be empty after delete"
        else:
            # Create or update should result in record present
            assert len(table.items) <= 1, "Should have at most one record"
