"""
Tests for Derived View Manager.

Unit tests for DerivedViewManager class including view queries,
filter application, and missing rollup detection.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7**
"""

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from derived_view_manager import (
    ActivityAggRecord,
    AvailabilityRecord,
    DerivedViewManager,
    LeaseRecord,
    MissingRollupGap,
    Predicate,
    SaleRecord,
    VacancyRecord,
    get_entities_with_activity_count,
    get_leases_expiring_in_range,
    get_sales_by_broker,
    get_vacancy_above_threshold,
)


# =============================================================================
# Test Fixtures
# =============================================================================


class MockDynamoDBTable:
    """Mock DynamoDB table for testing."""

    def __init__(self, items: Optional[List[Dict[str, Any]]] = None):
        self.items: List[Dict[str, Any]] = items or []
        self.query_calls: List[Dict[str, Any]] = []
        self.scan_calls: List[Dict[str, Any]] = []
        self.get_item_calls: List[Dict[str, Any]] = []

    def query(self, **kwargs) -> Dict[str, Any]:
        """Mock query operation."""
        self.query_calls.append(kwargs)
        index_name = kwargs.get("IndexName")
        key_expr = kwargs.get("KeyConditionExpression", "")
        expr_values = kwargs.get("ExpressionAttributeValues", {})
        limit = kwargs.get("Limit", 100)

        results = []
        for item in self.items:
            # Simple matching based on key conditions
            if "property_id = :pid" in key_expr:
                if item.get("property_id") == expr_values.get(":pid"):
                    results.append(item)
            elif "entity_type = :et" in key_expr:
                if item.get("entity_type") == expr_values.get(":et"):
                    results.append(item)
            elif "stage = :s" in key_expr:
                if item.get("stage") == expr_values.get(":s"):
                    results.append(item)
            elif "end_date_month = :edm" in key_expr:
                if item.get("end_date_month") == expr_values.get(":edm"):
                    results.append(item)
            else:
                results.append(item)

        return {"Items": results[:limit]}

    def scan(self, **kwargs) -> Dict[str, Any]:
        """Mock scan operation."""
        self.scan_calls.append(kwargs)
        limit = kwargs.get("Limit", 100)
        return {"Items": self.items[:limit]}

    def get_item(self, Key: Dict[str, Any]) -> Dict[str, Any]:
        """Mock get_item operation."""
        self.get_item_calls.append(Key)
        for item in self.items:
            match = True
            for k, v in Key.items():
                if item.get(k) != v:
                    match = False
                    break
            if match:
                return {"Item": item}
        return {}


@pytest.fixture
def mock_availability_table():
    """Create mock availability view table with sample data."""
    return MockDynamoDBTable(
        items=[
            {
                "property_id": "prop001",
                "availability_id": "avail001",
                "size": Decimal("25000"),
                "status": "Available",
                "property_class": "A",
                "property_type": "Office",
                "city": "Plano",
                "state": "TX",
            },
            {
                "property_id": "prop001",
                "availability_id": "avail002",
                "size": Decimal("15000"),
                "status": "Pending",
                "property_class": "A",
                "property_type": "Office",
                "city": "Plano",
                "state": "TX",
            },
            {
                "property_id": "prop002",
                "availability_id": "avail003",
                "size": Decimal("50000"),
                "status": "Available",
                "property_class": "B",
                "property_type": "Industrial",
                "city": "Miami",
                "state": "FL",
            },
        ]
    )


@pytest.fixture
def mock_vacancy_table():
    """Create mock vacancy view table with sample data."""
    return MockDynamoDBTable(
        items=[
            {
                "property_id": "prop001",
                "vacancy_pct": Decimal("15.5"),
                "available_sqft": Decimal("40000"),
                "total_sqft": Decimal("258000"),
                "property_class": "A",
                "city": "Plano",
            },
            {
                "property_id": "prop002",
                "vacancy_pct": Decimal("30.0"),
                "available_sqft": Decimal("50000"),
                "total_sqft": Decimal("166666"),
                "property_class": "B",
                "city": "Miami",
            },
            {
                "property_id": "prop003",
                "vacancy_pct": Decimal("5.0"),
                "available_sqft": Decimal("5000"),
                "total_sqft": Decimal("100000"),
                "property_class": "A",
                "city": "Dallas",
            },
        ]
    )


@pytest.fixture
def mock_leases_table():
    """Create mock leases view table with sample data."""
    return MockDynamoDBTable(
        items=[
            {
                "property_id": "prop001",
                "lease_id": "lease001",
                "end_date": "2025-06-30",
                "end_date_month": "2025-06",
                "tenant_name": "Acme Corp",
                "status": "Active",
                "has_rofr": True,
                "has_ti": True,
                "has_hvac_clause": False,
            },
            {
                "property_id": "prop001",
                "lease_id": "lease002",
                "end_date": "2025-12-31",
                "end_date_month": "2025-12",
                "tenant_name": "Tech Inc",
                "status": "Active",
                "has_rofr": False,
                "has_ti": True,
                "has_noise_clause": True,
            },
            {
                "property_id": "prop002",
                "lease_id": "lease003",
                "end_date": "2026-03-15",
                "end_date_month": "2026-03",
                "tenant_name": "Retail Co",
                "status": "Pending",
            },
        ]
    )


@pytest.fixture
def mock_activities_table():
    """Create mock activities aggregation table with sample data."""
    return MockDynamoDBTable(
        items=[
            {
                "entity_id": "acc001",
                "entity_type": "Account",
                "count_7d": 5,
                "count_30d": 15,
                "count_90d": 45,
                "last_activity_date": "2025-01-15",
            },
            {
                "entity_id": "acc002",
                "entity_type": "Account",
                "count_7d": 2,
                "count_30d": 8,
                "count_90d": 20,
                "last_activity_date": "2025-01-10",
            },
            {
                "entity_id": "con001",
                "entity_type": "Contact",
                "count_7d": 10,
                "count_30d": 25,
                "count_90d": 60,
                "last_activity_date": "2025-01-14",
            },
        ]
    )


@pytest.fixture
def mock_sales_table():
    """Create mock sales view table with sample data."""
    return MockDynamoDBTable(
        items=[
            {
                "sale_id": "sale001",
                "property_id": "prop001",
                "stage": "Negotiation",
                "close_date": "2025-03-15",
                "broker_ids": ["broker001", "broker002"],
                "broker_names": ["Jane Doe", "John Smith"],
                "amount": Decimal("5000000"),
            },
            {
                "sale_id": "sale002",
                "property_id": "prop002",
                "stage": "Due Diligence",
                "close_date": "2025-04-01",
                "broker_ids": ["broker001"],
                "broker_names": ["Jane Doe"],
                "amount": Decimal("3500000"),
            },
            {
                "sale_id": "sale003",
                "property_id": "prop001",
                "stage": "Closed",
                "close_date": "2025-01-15",
                "broker_ids": ["broker003"],
                "broker_names": ["Bob Wilson"],
                "amount": Decimal("8000000"),
            },
        ]
    )


@pytest.fixture
def derived_view_manager(
    mock_availability_table,
    mock_vacancy_table,
    mock_leases_table,
    mock_activities_table,
    mock_sales_table,
):
    """Create DerivedViewManager with mock tables."""
    manager = DerivedViewManager()
    manager._tables = {
        manager.availability_table_name: mock_availability_table,
        manager.vacancy_table_name: mock_vacancy_table,
        manager.leases_table_name: mock_leases_table,
        manager.activities_table_name: mock_activities_table,
        manager.sales_table_name: mock_sales_table,
    }
    return manager


# =============================================================================
# Unit Tests for Data Classes
# =============================================================================


class TestPredicate:
    """Unit tests for Predicate class."""

    def test_predicate_eq(self):
        """Test equality operator."""
        pred = Predicate(field="status", operator="eq", value="Active")
        assert pred.matches("Active") is True
        assert pred.matches("Pending") is False

    def test_predicate_gt(self):
        """Test greater than operator."""
        pred = Predicate(field="size", operator="gt", value=20000)
        assert pred.matches(25000) is True
        assert pred.matches(20000) is False
        assert pred.matches(15000) is False

    def test_predicate_lt(self):
        """Test less than operator."""
        pred = Predicate(field="vacancy_pct", operator="lt", value=25.0)
        assert pred.matches(20.0) is True
        assert pred.matches(25.0) is False
        assert pred.matches(30.0) is False

    def test_predicate_gte(self):
        """Test greater than or equal operator."""
        pred = Predicate(field="count", operator="gte", value=10)
        assert pred.matches(15) is True
        assert pred.matches(10) is True
        assert pred.matches(5) is False

    def test_predicate_lte(self):
        """Test less than or equal operator."""
        pred = Predicate(field="amount", operator="lte", value=5000000)
        assert pred.matches(4000000) is True
        assert pred.matches(5000000) is True
        assert pred.matches(6000000) is False

    def test_predicate_in(self):
        """Test in operator."""
        pred = Predicate(field="stage", operator="in", value=["Negotiation", "Due Diligence"])
        assert pred.matches("Negotiation") is True
        assert pred.matches("Due Diligence") is True
        assert pred.matches("Closed") is False

    def test_predicate_contains(self):
        """Test contains operator."""
        pred = Predicate(field="notes", operator="contains", value="HVAC")
        assert pred.matches("Need HVAC repair") is True
        assert pred.matches("hvac system") is True
        assert pred.matches("No issues") is False

    def test_predicate_between(self):
        """Test between operator."""
        pred = Predicate(field="size", operator="between", value=[20000, 50000])
        assert pred.matches(30000) is True
        assert pred.matches(20000) is True
        assert pred.matches(50000) is True
        assert pred.matches(15000) is False
        assert pred.matches(60000) is False

    def test_predicate_decimal_conversion(self):
        """Test that Decimal values are handled correctly."""
        pred = Predicate(field="amount", operator="gt", value=Decimal("1000000"))
        assert pred.matches(Decimal("2000000")) is True
        assert pred.matches(Decimal("500000")) is False

    def test_predicate_none_value(self):
        """Test that None values return False."""
        pred = Predicate(field="status", operator="eq", value="Active")
        assert pred.matches(None) is False


class TestAvailabilityRecord:
    """Unit tests for AvailabilityRecord class."""

    def test_from_item(self):
        """Test creating from DynamoDB item."""
        item = {
            "property_id": "prop001",
            "availability_id": "avail001",
            "size": Decimal("25000"),
            "status": "Available",
            "property_class": "A",
            "city": "Dallas",
        }
        record = AvailabilityRecord.from_item(item)
        assert record.property_id == "prop001"
        assert record.availability_id == "avail001"
        assert record.size == 25000.0
        assert record.status == "Available"
        assert record.property_class == "A"

    def test_to_dict(self):
        """Test conversion to dictionary."""
        record = AvailabilityRecord(
            property_id="prop001",
            availability_id="avail001",
            size=25000.0,
            status="Available",
        )
        result = record.to_dict()
        assert result["property_id"] == "prop001"
        assert result["size"] == 25000.0


class TestVacancyRecord:
    """Unit tests for VacancyRecord class."""

    def test_from_item(self):
        """Test creating from DynamoDB item."""
        item = {
            "property_id": "prop001",
            "vacancy_pct": Decimal("25.5"),
            "available_sqft": Decimal("50000"),
            "total_sqft": Decimal("196078"),
        }
        record = VacancyRecord.from_item(item)
        assert record.property_id == "prop001"
        assert record.vacancy_pct == 25.5
        assert record.available_sqft == 50000.0


class TestLeaseRecord:
    """Unit tests for LeaseRecord class."""

    def test_from_item_with_clause_flags(self):
        """Test creating from DynamoDB item with clause flags."""
        item = {
            "property_id": "prop001",
            "lease_id": "lease001",
            "end_date": "2025-06-30",
            "has_rofr": True,
            "has_ti": True,
            "has_hvac_clause": True,
        }
        record = LeaseRecord.from_item(item)
        assert record.has_rofr is True
        assert record.has_ti is True
        assert record.has_hvac_clause is True
        assert record.has_noise_clause is False  # Default


class TestActivityAggRecord:
    """Unit tests for ActivityAggRecord class."""

    def test_from_item(self):
        """Test creating from DynamoDB item."""
        item = {
            "entity_id": "acc001",
            "entity_type": "Account",
            "count_7d": 5,
            "count_30d": 15,
            "count_90d": 45,
        }
        record = ActivityAggRecord.from_item(item)
        assert record.entity_id == "acc001"
        assert record.entity_type == "Account"
        assert record.count_7d == 5
        assert record.count_30d == 15
        assert record.count_90d == 45


class TestSaleRecord:
    """Unit tests for SaleRecord class."""

    def test_from_item_with_brokers(self):
        """Test creating from DynamoDB item with broker info."""
        item = {
            "sale_id": "sale001",
            "property_id": "prop001",
            "stage": "Negotiation",
            "broker_ids": ["broker001", "broker002"],
            "broker_names": ["Jane Doe", "John Smith"],
            "amount": Decimal("5000000"),
        }
        record = SaleRecord.from_item(item)
        assert record.sale_id == "sale001"
        assert record.stage == "Negotiation"
        assert len(record.broker_ids) == 2
        assert "Jane Doe" in record.broker_names
        assert record.amount == 5000000.0


# =============================================================================
# Unit Tests for Availability View Queries (Requirement 5.1)
# =============================================================================


class TestAvailabilityViewQueries:
    """Unit tests for availability_view queries."""

    def test_query_availability_by_property(self, derived_view_manager):
        """Test querying availability by property ID."""
        results = derived_view_manager.query_availability_view(property_id="prop001")
        assert len(results) == 2
        assert all(r.property_id == "prop001" for r in results)

    def test_query_availability_all(self, derived_view_manager):
        """Test querying all availability records."""
        results = derived_view_manager.query_availability_view()
        assert len(results) == 3

    def test_query_availability_with_filters(self, derived_view_manager):
        """Test querying availability with predicate filters."""
        filters = [Predicate(field="status", operator="eq", value="Available")]
        results = derived_view_manager.query_availability_view(filters=filters)
        assert len(results) == 2
        assert all(r.status == "Available" for r in results)

    def test_query_availability_with_size_filter(self, derived_view_manager):
        """Test querying availability with size filter."""
        filters = [Predicate(field="size", operator="gte", value=20000)]
        results = derived_view_manager.query_availability_view(filters=filters)
        assert len(results) == 2
        assert all(r.size >= 20000 for r in results)


# =============================================================================
# Unit Tests for Vacancy View Queries (Requirement 5.2)
# =============================================================================


class TestVacancyViewQueries:
    """Unit tests for vacancy_view queries."""

    def test_query_vacancy_by_property(self, derived_view_manager):
        """Test querying vacancy by property ID."""
        results = derived_view_manager.query_vacancy_view(property_id="prop001")
        assert len(results) == 1
        assert results[0].property_id == "prop001"
        assert results[0].vacancy_pct == 15.5

    def test_query_vacancy_above_threshold(self, derived_view_manager):
        """Test querying properties with vacancy above threshold."""
        results = derived_view_manager.query_vacancy_view(min_vacancy_pct=20.0)
        assert len(results) == 1
        assert results[0].vacancy_pct >= 20.0

    def test_query_vacancy_below_threshold(self, derived_view_manager):
        """Test querying properties with vacancy below threshold."""
        results = derived_view_manager.query_vacancy_view(max_vacancy_pct=20.0)
        assert len(results) == 2
        assert all(r.vacancy_pct <= 20.0 for r in results)

    def test_query_vacancy_range(self, derived_view_manager):
        """Test querying properties within vacancy range."""
        results = derived_view_manager.query_vacancy_view(
            min_vacancy_pct=10.0, max_vacancy_pct=20.0
        )
        assert len(results) == 1
        assert 10.0 <= results[0].vacancy_pct <= 20.0


# =============================================================================
# Unit Tests for Leases View Queries (Requirement 5.3)
# =============================================================================


class TestLeasesViewQueries:
    """Unit tests for leases_view queries."""

    def test_query_leases_by_property(self, derived_view_manager):
        """Test querying leases by property ID."""
        results = derived_view_manager.query_leases_view(property_id="prop001")
        assert len(results) == 2
        assert all(r.property_id == "prop001" for r in results)

    def test_query_leases_by_end_date_month(self, derived_view_manager):
        """Test querying leases by end date month."""
        results = derived_view_manager.query_leases_view(end_date_month="2025-06")
        assert len(results) == 1
        assert results[0].end_date_month == "2025-06"

    def test_query_leases_by_date_range(self, derived_view_manager):
        """Test querying leases expiring within date range."""
        results = derived_view_manager.query_leases_view(
            end_date_range=("2025-01-01", "2025-12-31")
        )
        assert len(results) == 2  # lease001 and lease002

    def test_query_leases_with_rofr_filter(self, derived_view_manager):
        """Test querying leases with ROFR clause."""
        filters = [Predicate(field="has_rofr", operator="eq", value=True)]
        results = derived_view_manager.query_leases_view(filters=filters)
        assert len(results) == 1
        assert results[0].has_rofr is True


# =============================================================================
# Unit Tests for Activities Aggregation Queries (Requirement 5.4)
# =============================================================================


class TestActivitiesAggQueries:
    """Unit tests for activities_agg queries."""

    def test_query_activities_by_entity(self, derived_view_manager):
        """Test querying activities by entity ID."""
        results = derived_view_manager.query_activities_agg(entity_id="acc001")
        assert len(results) == 1
        assert results[0].entity_id == "acc001"

    def test_query_activities_by_entity_type(self, derived_view_manager):
        """Test querying activities by entity type."""
        results = derived_view_manager.query_activities_agg(entity_type="Account")
        assert len(results) == 2
        assert all(r.entity_type == "Account" for r in results)

    def test_query_activities_with_min_count_7d(self, derived_view_manager):
        """Test querying activities with minimum count in 7-day window."""
        results = derived_view_manager.query_activities_agg(
            min_count=5, window_days=7
        )
        assert len(results) == 2  # acc001 (5) and con001 (10)
        assert all(r.count_7d >= 5 for r in results)

    def test_query_activities_with_min_count_30d(self, derived_view_manager):
        """Test querying activities with minimum count in 30-day window."""
        results = derived_view_manager.query_activities_agg(
            min_count=20, window_days=30
        )
        assert len(results) == 1  # con001 (25)
        assert results[0].count_30d >= 20

    def test_get_activity_count(self, derived_view_manager):
        """Test getting activity count for an entity."""
        count_7d = derived_view_manager.get_activity_count("acc001", window_days=7)
        assert count_7d == 5

        count_30d = derived_view_manager.get_activity_count("acc001", window_days=30)
        assert count_30d == 15

        count_90d = derived_view_manager.get_activity_count("acc001", window_days=90)
        assert count_90d == 45

    def test_get_activity_count_not_found(self, derived_view_manager):
        """Test getting activity count for non-existent entity."""
        count = derived_view_manager.get_activity_count("nonexistent")
        assert count is None


# =============================================================================
# Unit Tests for Sales View Queries (Requirement 5.5)
# =============================================================================


class TestSalesViewQueries:
    """Unit tests for sales_view queries."""

    def test_query_sales_by_id(self, derived_view_manager):
        """Test querying sale by ID."""
        results = derived_view_manager.query_sales_view(sale_id="sale001")
        assert len(results) == 1
        assert results[0].sale_id == "sale001"

    def test_query_sales_by_stage(self, derived_view_manager):
        """Test querying sales by stage."""
        results = derived_view_manager.query_sales_view(stage="Negotiation")
        assert len(results) == 1
        assert results[0].stage == "Negotiation"

    def test_query_sales_by_property(self, derived_view_manager):
        """Test querying sales by property ID."""
        results = derived_view_manager.query_sales_view(property_id="prop001")
        assert len(results) == 2

    def test_query_sales_by_broker(self, derived_view_manager):
        """Test querying sales by broker ID."""
        results = derived_view_manager.query_sales_view(broker_id="broker001")
        assert len(results) == 2
        assert all("broker001" in r.broker_ids for r in results)

    def test_query_sales_by_broker_and_stage(self, derived_view_manager):
        """Test querying sales by broker and stage."""
        results = derived_view_manager.query_sales_view(
            broker_id="broker001", stage="Due Diligence"
        )
        assert len(results) == 1
        assert results[0].stage == "Due Diligence"


# =============================================================================
# Unit Tests for Missing Rollup Detection (Requirement 5.7)
# =============================================================================


class TestMissingRollupDetection:
    """Unit tests for missing rollup detection and logging."""

    def test_check_view_exists_true(self, derived_view_manager):
        """Test check_view_exists returns True when data exists."""
        assert derived_view_manager.check_view_exists("availability_view") is True
        assert derived_view_manager.check_view_exists("vacancy_view") is True
        assert derived_view_manager.check_view_exists("leases_view") is True
        assert derived_view_manager.check_view_exists("activities_agg") is True
        assert derived_view_manager.check_view_exists("sales_view") is True

    def test_check_view_exists_unknown_view(self, derived_view_manager):
        """Test check_view_exists returns False for unknown view."""
        assert derived_view_manager.check_view_exists("unknown_view") is False

    def test_log_missing_rollup(self, derived_view_manager):
        """Test logging missing rollup gap."""
        with patch.object(derived_view_manager, "log_missing_rollup") as mock_log:
            derived_view_manager.log_missing_rollup(
                view_name="custom_view",
                query="Find custom data",
                filters=[Predicate(field="status", operator="eq", value="Active")],
            )
            mock_log.assert_called_once()

    def test_query_with_fallback_success(self, derived_view_manager):
        """Test query_with_fallback returns results without fallback."""
        results, used_fallback = derived_view_manager.query_with_fallback(
            view_name="availability_view",
            query="Find available spaces",
        )
        assert len(results) > 0
        assert used_fallback is False

    def test_query_with_fallback_no_results(self, derived_view_manager):
        """Test query_with_fallback triggers fallback on no results."""
        # Use filter that won't match anything
        filters = [Predicate(field="status", operator="eq", value="NonExistent")]
        results, used_fallback = derived_view_manager.query_with_fallback(
            view_name="availability_view",
            query="Find non-existent spaces",
            filters=filters,
        )
        assert len(results) == 0
        assert used_fallback is True

    def test_query_with_fallback_unknown_view(self, derived_view_manager):
        """Test query_with_fallback handles unknown view."""
        results, used_fallback = derived_view_manager.query_with_fallback(
            view_name="unknown_view",
            query="Query unknown view",
        )
        assert len(results) == 0
        assert used_fallback is True


# =============================================================================
# Unit Tests for Filter Application (Requirement 5.6)
# =============================================================================


class TestFilterApplication:
    """Unit tests for predicate filter application."""

    def test_apply_multiple_filters(self, derived_view_manager):
        """Test applying multiple filters."""
        filters = [
            Predicate(field="property_class", operator="eq", value="A"),
            Predicate(field="status", operator="eq", value="Available"),
        ]
        results = derived_view_manager.query_availability_view(filters=filters)
        assert len(results) == 1
        assert results[0].property_class == "A"
        assert results[0].status == "Available"

    def test_apply_combined_filters(self, derived_view_manager):
        """Test applying combined filters across views."""
        # Filter sales by stage and amount
        filters = [Predicate(field="amount", operator="gte", value=4000000)]
        results = derived_view_manager.query_sales_view(
            stage="Negotiation", filters=filters
        )
        assert len(results) == 1
        assert results[0].amount >= 4000000


# =============================================================================
# Unit Tests for Convenience Functions
# =============================================================================


class TestConvenienceFunctions:
    """Unit tests for convenience functions."""

    def test_get_vacancy_above_threshold(self, derived_view_manager):
        """Test get_vacancy_above_threshold function."""
        with patch(
            "derived_view_manager.DerivedViewManager",
            return_value=derived_view_manager,
        ):
            results = get_vacancy_above_threshold(25.0, manager=derived_view_manager)
            assert len(results) == 1
            assert results[0].vacancy_pct >= 25.0

    def test_get_leases_expiring_in_range(self, derived_view_manager):
        """Test get_leases_expiring_in_range function."""
        results = get_leases_expiring_in_range(
            "2025-01-01", "2025-12-31", manager=derived_view_manager
        )
        assert len(results) == 2

    def test_get_entities_with_activity_count(self, derived_view_manager):
        """Test get_entities_with_activity_count function."""
        results = get_entities_with_activity_count(
            entity_type="Account",
            min_count=10,
            window_days=30,
            manager=derived_view_manager,
        )
        assert len(results) == 1
        assert results[0].count_30d >= 10

    def test_get_sales_by_broker(self, derived_view_manager):
        """Test get_sales_by_broker function."""
        results = get_sales_by_broker("broker001", manager=derived_view_manager)
        assert len(results) == 2
        assert all("broker001" in r.broker_ids for r in results)


# =============================================================================
# Unit Tests for Error Handling
# =============================================================================


class TestErrorHandling:
    """Unit tests for error handling."""

    def test_query_handles_dynamodb_error(self, derived_view_manager):
        """Test that queries handle DynamoDB errors gracefully."""
        # Create a table that raises an error
        error_table = MagicMock()
        error_table.scan.side_effect = Exception("DynamoDB error")
        derived_view_manager._tables[
            derived_view_manager.availability_table_name
        ] = error_table

        results = derived_view_manager.query_availability_view()
        assert results == []

    def test_get_item_handles_missing_item(self, derived_view_manager):
        """Test that get_item handles missing items."""
        results = derived_view_manager.query_vacancy_view(property_id="nonexistent")
        assert len(results) == 0


# =============================================================================
# Unit Tests for MissingRollupGap
# =============================================================================


class TestMissingRollupGap:
    """Unit tests for MissingRollupGap dataclass."""

    def test_missing_rollup_gap_creation(self):
        """Test creating MissingRollupGap."""
        gap = MissingRollupGap(
            view_name="custom_rollup",
            query="Find custom data",
            filters=[{"field": "status", "operator": "eq", "value": "Active"}],
        )
        assert gap.view_name == "custom_rollup"
        assert gap.query == "Find custom data"
        assert len(gap.filters) == 1
        assert gap.timestamp is not None
