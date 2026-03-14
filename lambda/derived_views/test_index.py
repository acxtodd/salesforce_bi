"""
Tests for Derived Views Maintenance Lambda.

Unit tests for view updaters and CDC event handling.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 17.1, 17.2, 17.3, 17.4**
"""

import os
import sys
from decimal import Decimal
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
import importlib.util

import pytest

# Load the module directly from file path to avoid import conflicts
_module_name = "derived_views_index"
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
CLAUSE_PATTERNS = _derived_views_module.CLAUSE_PATTERNS
lambda_handler = _derived_views_module.lambda_handler


# =============================================================================
# Test Fixtures
# =============================================================================


class MockDynamoDBTable:
    """Mock DynamoDB table for testing."""

    def __init__(self):
        self.items: Dict[str, Dict[str, Any]] = {}
        self.put_calls: List[Dict] = []
        self.delete_calls: List[Dict] = []
        self.update_calls: List[Dict] = []

    def put_item(self, Item: Dict[str, Any]) -> None:
        """Store an item."""
        # Create a composite key from first two keys
        keys = list(Item.keys())[:2]
        key = "#".join(str(Item.get(k, "")) for k in keys)
        self.items[key] = Item
        self.put_calls.append(Item)

    def get_item(self, Key: Dict[str, Any]) -> Dict[str, Any]:
        """Get an item."""
        key = "#".join(str(v) for v in Key.values())
        item = self.items.get(key)
        return {"Item": item} if item else {}

    def delete_item(self, Key: Dict[str, Any]) -> None:
        """Delete an item."""
        key = "#".join(str(v) for v in Key.values())
        if key in self.items:
            del self.items[key]
        self.delete_calls.append(Key)

    def update_item(self, **kwargs) -> None:
        """Update an item."""
        self.update_calls.append(kwargs)
        key = "#".join(str(v) for v in kwargs["Key"].values())
        if key in self.items:
            # Simple update - just mark as updated
            self.items[key]["_updated"] = True


class MockDynamoDBResource:
    """Mock DynamoDB resource."""

    def __init__(self):
        self.tables: Dict[str, MockDynamoDBTable] = {}

    def Table(self, name: str) -> MockDynamoDBTable:
        if name not in self.tables:
            self.tables[name] = MockDynamoDBTable()
        return self.tables[name]


@pytest.fixture
def mock_dynamodb():
    """Create mock DynamoDB resource."""
    return MockDynamoDBResource()


@pytest.fixture
def availability_updater(mock_dynamodb):
    """Create AvailabilityViewUpdater with mock DynamoDB."""
    return AvailabilityViewUpdater(dynamodb_resource=mock_dynamodb)


@pytest.fixture
def vacancy_updater(mock_dynamodb):
    """Create VacancyViewUpdater with mock DynamoDB."""
    return VacancyViewUpdater(dynamodb_resource=mock_dynamodb)


@pytest.fixture
def leases_updater(mock_dynamodb):
    """Create LeasesViewUpdater with mock DynamoDB."""
    return LeasesViewUpdater(dynamodb_resource=mock_dynamodb)


@pytest.fixture
def activities_updater(mock_dynamodb):
    """Create ActivitiesAggUpdater with mock DynamoDB."""
    return ActivitiesAggUpdater(dynamodb_resource=mock_dynamodb)


@pytest.fixture
def sales_updater(mock_dynamodb):
    """Create SalesViewUpdater with mock DynamoDB."""
    return SalesViewUpdater(dynamodb_resource=mock_dynamodb)


@pytest.fixture
def handler(mock_dynamodb):
    """Create DerivedViewsHandler with mock DynamoDB."""
    handler = DerivedViewsHandler(dynamodb_resource=mock_dynamodb)
    return handler


# =============================================================================
# Unit Tests for CDCEvent
# =============================================================================


class TestCDCEvent:
    """Unit tests for CDCEvent dataclass."""

    def test_from_event(self):
        """Test creating CDCEvent from Lambda event."""
        event = {
            "objectType": "ascendix__Availability__c",
            "recordId": "a0XXXXX",
            "operation": "create",
            "recordData": {"Name": "Test"},
            "changedFields": ["Name"],
            "timestamp": "2025-01-01T00:00:00Z",
        }
        cdc_event = CDCEvent.from_event(event)

        assert cdc_event.object_type == "ascendix__Availability__c"
        assert cdc_event.record_id == "a0XXXXX"
        assert cdc_event.operation == "create"
        assert cdc_event.record_data["Name"] == "Test"
        assert "Name" in cdc_event.changed_fields

    def test_from_event_defaults(self):
        """Test CDCEvent with minimal event data."""
        event = {"objectType": "Task", "recordId": "00TXXXXX"}
        cdc_event = CDCEvent.from_event(event)

        assert cdc_event.object_type == "Task"
        assert cdc_event.operation == "update"
        assert cdc_event.record_data == {}
        assert cdc_event.changed_fields == []


# =============================================================================
# Unit Tests for AvailabilityViewUpdater (Requirement 5.1)
# =============================================================================


class TestAvailabilityViewUpdater:
    """Unit tests for AvailabilityViewUpdater."""

    def test_handle_create(self, availability_updater, mock_dynamodb):
        """Test handling availability creation."""
        event = CDCEvent(
            object_type="ascendix__Availability__c",
            record_id="avail001",
            operation="create",
            record_data={
                "ascendix__Property__c": "prop001",
                "ascendix__Size__c": 25000,
                "ascendix__Status__c": "Available",
                # Updated 2025-12-14: Use SpaceDescription (Notes doesn't exist on Availability)
                "ascendix__SpaceDescription__c": "TI allowance available",
            },
        )

        result = availability_updater.handle_create(event)
        assert result is True

        table = mock_dynamodb.tables[availability_updater.table_name]
        assert len(table.put_calls) == 1
        item = table.put_calls[0]
        assert item["property_id"] == "prop001"
        assert item["availability_id"] == "avail001"
        assert item["size"] == Decimal("25000")

    def test_handle_create_no_property(self, availability_updater):
        """Test handling availability without property ID."""
        event = CDCEvent(
            object_type="ascendix__Availability__c",
            record_id="avail001",
            operation="create",
            record_data={"ascendix__Size__c": 25000},
        )

        result = availability_updater.handle_create(event)
        assert result is False

    def test_handle_delete(self, availability_updater, mock_dynamodb):
        """Test handling availability deletion."""
        event = CDCEvent(
            object_type="ascendix__Availability__c",
            record_id="avail001",
            operation="delete",
            record_data={"ascendix__Property__c": "prop001"},
        )

        result = availability_updater.handle_delete(event)
        assert result is True

        table = mock_dynamodb.tables[availability_updater.table_name]
        assert len(table.delete_calls) == 1

    def test_extract_ti_hints(self, availability_updater):
        """Test TI hints extraction from notes."""
        notes = "TI allowance of $50/sf available. Tenant improvement work can begin immediately."
        hints = availability_updater._extract_ti_hints(notes)

        assert hints != ""
        assert "TI" in hints.upper() or "tenant improvement" in hints.lower()

    def test_extract_ti_hints_empty(self, availability_updater):
        """Test TI hints extraction with no TI references."""
        notes = "Standard office space with great views."
        hints = availability_updater._extract_ti_hints(notes)

        assert hints == ""


# =============================================================================
# Unit Tests for VacancyViewUpdater (Requirement 5.2)
# =============================================================================


class TestVacancyViewUpdater:
    """Unit tests for VacancyViewUpdater."""

    def test_handle_create(self, vacancy_updater, mock_dynamodb):
        """Test handling property creation."""
        # Updated 2025-12-14: Use correct field names from SF schema
        event = CDCEvent(
            object_type="ascendix__Property__c",
            record_id="prop001",
            operation="create",
            record_data={
                "ascendix__TotalBuildingArea__c": 100000,
                "ascendix__TotalAvailableArea__c": 25000,
                "ascendix__PropertyClass__c": "A",
                "ascendix__City__c": "Dallas",
            },
        )

        result = vacancy_updater.handle_create(event)
        assert result is True

        table = mock_dynamodb.tables[vacancy_updater.table_name]
        assert len(table.put_calls) == 1
        item = table.put_calls[0]
        assert item["property_id"] == "prop001"
        assert item["vacancy_pct"] == Decimal("25")  # 25000/100000 * 100
        assert item["vacancy_pct_bucket"] == "25-30"  # 25% falls into 25-30 bucket

    def test_handle_delete(self, vacancy_updater, mock_dynamodb):
        """Test handling property deletion."""
        event = CDCEvent(
            object_type="ascendix__Property__c",
            record_id="prop001",
            operation="delete",
            record_data={},
        )

        result = vacancy_updater.handle_delete(event)
        assert result is True

        table = mock_dynamodb.tables[vacancy_updater.table_name]
        assert len(table.delete_calls) == 1

    def test_get_vacancy_bucket(self, vacancy_updater):
        """Test vacancy bucket calculation."""
        assert vacancy_updater._get_vacancy_bucket(3.0) == "0-5"
        assert vacancy_updater._get_vacancy_bucket(7.5) == "5-10"
        assert vacancy_updater._get_vacancy_bucket(12.0) == "10-15"
        assert vacancy_updater._get_vacancy_bucket(17.0) == "15-20"
        assert vacancy_updater._get_vacancy_bucket(23.0) == "20-25"
        assert vacancy_updater._get_vacancy_bucket(28.0) == "25-30"
        assert vacancy_updater._get_vacancy_bucket(35.0) == "30+"

    def test_vacancy_zero_total(self, vacancy_updater, mock_dynamodb):
        """Test vacancy calculation with zero total sqft."""
        event = CDCEvent(
            object_type="ascendix__Property__c",
            record_id="prop001",
            operation="create",
            record_data={
                "ascendix__TotalSqFt__c": 0,
                "ascendix__AvailableSqFt__c": 0,
            },
        )

        result = vacancy_updater.handle_create(event)
        assert result is True

        table = mock_dynamodb.tables[vacancy_updater.table_name]
        item = table.put_calls[0]
        assert item["vacancy_pct"] == Decimal("0")


# =============================================================================
# Unit Tests for LeasesViewUpdater (Requirement 5.3)
# =============================================================================


class TestLeasesViewUpdater:
    """Unit tests for LeasesViewUpdater."""

    def test_handle_create(self, leases_updater, mock_dynamodb):
        """Test handling lease creation."""
        event = CDCEvent(
            object_type="ascendix__Lease__c",
            record_id="lease001",
            operation="create",
            record_data={
                "ascendix__Property__c": "prop001",
                "ascendix__TermExpirationDate__c": "2025-12-31",
                "ascendix__Tenant__c": "acc001",
                # Updated 2025-12-14: Removed Status (doesn't exist on Lease)
                # Using Description instead of Notes (Notes doesn't exist on Lease)
                "ascendix__Description__c": "ROFR clause included",
                "Tenant__r": {"Name": "Acme Corp"},
            },
        )

        result = leases_updater.handle_create(event)
        assert result is True

        table = mock_dynamodb.tables[leases_updater.table_name]
        item = table.put_calls[0]
        assert item["property_id"] == "prop001"
        assert item["lease_id"] == "lease001"
        assert item["end_date_month"] == "2025-12"
        assert item["has_rofr"] is True

    def test_extract_clause_flags(self, leases_updater):
        """Test clause flag extraction from notes."""
        # Test ROFR detection
        notes = "Lease includes right of first refusal clause"
        flags = leases_updater._extract_clause_flags(notes)
        assert flags["rofr"] is True

        # Test TI detection
        notes = "Tenant improvement allowance included"
        flags = leases_updater._extract_clause_flags(notes)
        assert flags["ti"] is True

        # Test noise clause detection
        notes = "Quiet hours between 10pm-6am"
        flags = leases_updater._extract_clause_flags(notes)
        assert flags["noise"] is True

        # Test HVAC detection
        notes = "HVAC maintenance included"
        flags = leases_updater._extract_clause_flags(notes)
        assert flags["hvac"] is True

        # Test no clauses
        notes = "Standard lease terms apply"
        flags = leases_updater._extract_clause_flags(notes)
        assert flags["rofr"] is False
        assert flags["ti"] is False
        assert flags["noise"] is False
        assert flags["hvac"] is False


# =============================================================================
# Unit Tests for ActivitiesAggUpdater (Requirement 5.4)
# =============================================================================


class TestActivitiesAggUpdater:
    """Unit tests for ActivitiesAggUpdater."""

    def test_handle_create(self, activities_updater, mock_dynamodb):
        """Test handling activity creation."""
        event = CDCEvent(
            object_type="Task",
            record_id="task001",
            operation="create",
            record_data={
                "WhatId": "001XXXXX",
                "ActivityDate": "2025-01-15",
                "CreatedDate": "2025-01-15T10:00:00Z",
            },
        )

        result = activities_updater.handle_create(event)
        assert result is True

        table = mock_dynamodb.tables[activities_updater.table_name]
        assert len(table.put_calls) == 1
        item = table.put_calls[0]
        assert item["entity_id"] == "001XXXXX"
        assert item["entity_type"] == "Account"
        assert item["count_7d"] == 1

    def test_handle_delete(self, activities_updater, mock_dynamodb):
        """Test handling activity deletion decrements counts."""
        # First ensure table exists by doing a get (which creates the table)
        activities_updater._get_table(activities_updater.table_name)

        # Add existing record to the table
        table = mock_dynamodb.tables[activities_updater.table_name]
        table.items["001XXXXX"] = {
            "entity_id": "001XXXXX",
            "entity_type": "Account",
            "count_7d": 5,
            "count_30d": 10,
            "count_90d": 20,
        }

        event = CDCEvent(
            object_type="Task",
            record_id="task001",
            operation="delete",
            record_data={"WhatId": "001XXXXX", "ActivityDate": "2025-01-15"},
        )

        result = activities_updater.handle_delete(event)
        assert result is True

    def test_get_entity_type(self, activities_updater):
        """Test entity type detection from ID prefix."""
        assert activities_updater._get_entity_type("001XXXXX") == "Account"
        assert activities_updater._get_entity_type("003XXXXX") == "Contact"
        assert activities_updater._get_entity_type("006XXXXX") == "Opportunity"
        assert activities_updater._get_entity_type("00QXXXXX") == "Lead"
        assert activities_updater._get_entity_type("XXXXXXXX") == "Unknown"


# =============================================================================
# Unit Tests for SalesViewUpdater (Requirement 5.5)
# =============================================================================


class TestSalesViewUpdater:
    """Unit tests for SalesViewUpdater."""

    def test_handle_create(self, sales_updater, mock_dynamodb):
        """Test handling sale creation."""
        event = CDCEvent(
            object_type="ascendix__Sale__c",
            record_id="sale001",
            operation="create",
            record_data={
                "ascendix__Property__c": "prop001",
                "ascendix__Stage__c": "Negotiation",
                "ascendix__CloseDate__c": "2025-03-15",
                "ascendix__Amount__c": 5000000,
                "ascendix__PrimaryBroker__c": "broker001",
                "PrimaryBroker__r": {"Name": "Jane Doe"},
            },
        )

        result = sales_updater.handle_create(event)
        assert result is True

        table = mock_dynamodb.tables[sales_updater.table_name]
        item = table.put_calls[0]
        assert item["sale_id"] == "sale001"
        assert item["property_id"] == "prop001"
        assert item["stage"] == "Negotiation"
        assert "broker001" in item["broker_ids"]
        assert "Jane Doe" in item["broker_names"]

    def test_handle_create_multiple_brokers(self, sales_updater, mock_dynamodb):
        """Test handling sale with multiple brokers."""
        event = CDCEvent(
            object_type="ascendix__Sale__c",
            record_id="sale001",
            operation="create",
            record_data={
                "ascendix__Property__c": "prop001",
                "ascendix__Stage__c": "Negotiation",
                "ascendix__PrimaryBroker__c": "broker001",
                "ascendix__SecondaryBroker__c": "broker002",
                "PrimaryBroker__r": {"Name": "Jane Doe"},
                "SecondaryBroker__r": {"Name": "John Smith"},
            },
        )

        result = sales_updater.handle_create(event)
        assert result is True

        table = mock_dynamodb.tables[sales_updater.table_name]
        item = table.put_calls[0]
        assert len(item["broker_ids"]) == 2
        assert len(item["broker_names"]) == 2

    def test_handle_delete(self, sales_updater, mock_dynamodb):
        """Test handling sale deletion."""
        event = CDCEvent(
            object_type="ascendix__Sale__c",
            record_id="sale001",
            operation="delete",
            record_data={},
        )

        result = sales_updater.handle_delete(event)
        assert result is True

        table = mock_dynamodb.tables[sales_updater.table_name]
        assert len(table.delete_calls) == 1


# =============================================================================
# Unit Tests for DerivedViewsHandler
# =============================================================================


class TestDerivedViewsHandler:
    """Unit tests for main DerivedViewsHandler."""

    def test_handle_availability_event(self, handler, mock_dynamodb):
        """Test handling Availability CDC event."""
        event = CDCEvent(
            object_type="ascendix__Availability__c",
            record_id="avail001",
            operation="create",
            record_data={
                "ascendix__Property__c": "prop001",
                "ascendix__Size__c": 25000,
            },
        )

        result = handler.handle_event(event)
        assert result["success"] is True

    def test_handle_property_event(self, handler, mock_dynamodb):
        """Test handling Property CDC event."""
        event = CDCEvent(
            object_type="ascendix__Property__c",
            record_id="prop001",
            operation="create",
            record_data={
                "ascendix__TotalSqFt__c": 100000,
                "ascendix__AvailableSqFt__c": 25000,
            },
        )

        result = handler.handle_event(event)
        assert result["success"] is True

    def test_handle_unknown_object(self, handler):
        """Test handling unknown object type."""
        event = CDCEvent(
            object_type="Unknown__c",
            record_id="rec001",
            operation="create",
            record_data={},
        )

        result = handler.handle_event(event)
        assert result["success"] is True  # No error, just no handler


# =============================================================================
# Unit Tests for Lambda Handler
# =============================================================================


class TestLambdaHandler:
    """Unit tests for lambda_handler function."""

    def test_lambda_handler_single_event(self, mock_dynamodb):
        """Test lambda handler with single event."""
        # Patch the module-level DerivedViewsHandler in the dynamically loaded module
        with patch.object(_derived_views_module, "DerivedViewsHandler") as MockHandler:
            mock_instance = MagicMock()
            mock_instance.handle_event.return_value = {"success": True, "elapsed_ms": 10}
            MockHandler.return_value = mock_instance

            event = {
                "objectType": "ascendix__Availability__c",
                "recordId": "avail001",
                "operation": "create",
                "recordData": {"ascendix__Property__c": "prop001"},
            }

            result = lambda_handler(event, None)

            assert result["processed"] == 1
            assert result["succeeded"] == 1

    def test_lambda_handler_batch_events(self, mock_dynamodb):
        """Test lambda handler with batch events."""
        # Patch the module-level DerivedViewsHandler in the dynamically loaded module
        with patch.object(_derived_views_module, "DerivedViewsHandler") as MockHandler:
            mock_instance = MagicMock()
            mock_instance.handle_event.return_value = {"success": True, "elapsed_ms": 10}
            MockHandler.return_value = mock_instance

            event = {
                "records": [
                    {"objectType": "ascendix__Availability__c", "recordId": "avail001", "operation": "create", "recordData": {"ascendix__Property__c": "prop001"}},
                    {"objectType": "ascendix__Property__c", "recordId": "prop001", "operation": "update", "recordData": {}},
                ]
            }

            result = lambda_handler(event, None)

            assert result["processed"] == 2


# =============================================================================
# Unit Tests for Clause Pattern Matching
# =============================================================================


class TestClausePatterns:
    """Unit tests for clause detection patterns."""

    def test_rofr_pattern(self):
        """Test ROFR clause detection."""
        pattern = CLAUSE_PATTERNS["rofr"]
        assert pattern.search("ROFR included")
        assert pattern.search("Right of First Refusal clause")
        assert not pattern.search("Standard terms")

    def test_ti_pattern(self):
        """Test TI clause detection."""
        pattern = CLAUSE_PATTERNS["ti"]
        assert pattern.search("TI allowance included")
        assert pattern.search("Tenant improvement package")
        assert pattern.search("Build out allowance")
        assert not pattern.search("No modifications allowed")

    def test_noise_pattern(self):
        """Test noise clause detection."""
        pattern = CLAUSE_PATTERNS["noise"]
        assert pattern.search("Noise restrictions apply")
        assert pattern.search("Quiet hours enforced")
        assert not pattern.search("Open floor plan")

    def test_hvac_pattern(self):
        """Test HVAC clause detection."""
        pattern = CLAUSE_PATTERNS["hvac"]
        assert pattern.search("HVAC maintenance included")
        assert pattern.search("Heating and cooling provided")
        assert pattern.search("Cooling system installed")
        assert not pattern.search("Utilities separate")
