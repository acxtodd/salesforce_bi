"""
Derived View Manager for Graph-Aware Zero-Config Retrieval.

Manages physically materialized views stored in DynamoDB for aggregation queries.
Views are maintained via CDC streams and nightly backfill.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7**
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

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


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Predicate:
    """
    Represents a filter predicate for derived view queries.

    Attributes:
        field: Field name to filter on
        operator: Comparison operator (eq, gt, lt, gte, lte, in, contains, between)
        value: Filter value
    """

    field: str
    operator: str
    value: Any

    def matches(self, record_value: Any) -> bool:
        """
        Check if a record value matches this predicate.

        Args:
            record_value: The value from the record to check

        Returns:
            True if the value matches the predicate
        """
        if record_value is None:
            return False

        # Convert Decimal to float for comparisons
        if isinstance(record_value, Decimal):
            record_value = float(record_value)
        if isinstance(self.value, Decimal):
            compare_value = float(self.value)
        else:
            compare_value = self.value

        if self.operator == "eq":
            return record_value == compare_value
        elif self.operator == "gt":
            return record_value > compare_value
        elif self.operator == "lt":
            return record_value < compare_value
        elif self.operator == "gte":
            return record_value >= compare_value
        elif self.operator == "lte":
            return record_value <= compare_value
        elif self.operator == "in":
            return record_value in compare_value
        elif self.operator == "contains":
            return str(compare_value).lower() in str(record_value).lower()
        elif self.operator == "between":
            if isinstance(compare_value, (list, tuple)) and len(compare_value) >= 2:
                return compare_value[0] <= record_value <= compare_value[1]
            return False
        return False


@dataclass
class AvailabilityRecord:
    """
    Represents a record from the availability_view table.

    **Requirements: 5.1**

    Attributes:
        property_id: Property record ID (PK)
        availability_id: Availability record ID (SK)
        size: Available square footage
        status: Availability status
        ti_hints: Tenant improvement hints extracted from notes
        property_class: Property class (A, B, C)
        property_type: Property type (Office, Industrial, etc.)
        city: Property city
        state: Property state
        submarket: Property submarket
        updated_at: Last update timestamp
    """

    property_id: str
    availability_id: str
    size: Optional[float] = None
    status: Optional[str] = None
    ti_hints: Optional[str] = None
    property_class: Optional[str] = None
    property_type: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    submarket: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "property_id": self.property_id,
            "availability_id": self.availability_id,
        }
        if self.size is not None:
            result["size"] = self.size
        if self.status:
            result["status"] = self.status
        if self.ti_hints:
            result["ti_hints"] = self.ti_hints
        if self.property_class:
            result["property_class"] = self.property_class
        if self.property_type:
            result["property_type"] = self.property_type
        if self.city:
            result["city"] = self.city
        if self.state:
            result["state"] = self.state
        if self.submarket:
            result["submarket"] = self.submarket
        if self.updated_at:
            result["updated_at"] = self.updated_at
        return result

    @classmethod
    def from_item(cls, item: Dict[str, Any]) -> "AvailabilityRecord":
        """Create from DynamoDB item."""
        size = item.get("size")
        if isinstance(size, Decimal):
            size = float(size)
        return cls(
            property_id=item.get("property_id", ""),
            availability_id=item.get("availability_id", ""),
            size=size,
            status=item.get("status"),
            ti_hints=item.get("ti_hints"),
            property_class=item.get("property_class"),
            property_type=item.get("property_type"),
            city=item.get("city"),
            state=item.get("state"),
            submarket=item.get("submarket"),
            updated_at=item.get("updated_at"),
        )


@dataclass
class VacancyRecord:
    """
    Represents a record from the vacancy_view table.

    **Requirements: 5.2**

    Attributes:
        property_id: Property record ID (PK)
        vacancy_pct: Vacancy percentage (0-100)
        vacancy_pct_bucket: Bucketed vacancy for GSI queries
        available_sqft: Available square footage
        total_sqft: Total square footage
        property_class: Property class
        property_type: Property type
        city: Property city
        state: Property state
        updated_at: Last update timestamp
    """

    property_id: str
    vacancy_pct: float = 0.0
    vacancy_pct_bucket: Optional[str] = None
    available_sqft: float = 0.0
    total_sqft: float = 0.0
    property_class: Optional[str] = None
    property_type: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "property_id": self.property_id,
            "vacancy_pct": self.vacancy_pct,
            "available_sqft": self.available_sqft,
            "total_sqft": self.total_sqft,
        }
        if self.vacancy_pct_bucket:
            result["vacancy_pct_bucket"] = self.vacancy_pct_bucket
        if self.property_class:
            result["property_class"] = self.property_class
        if self.property_type:
            result["property_type"] = self.property_type
        if self.city:
            result["city"] = self.city
        if self.state:
            result["state"] = self.state
        if self.updated_at:
            result["updated_at"] = self.updated_at
        return result

    @classmethod
    def from_item(cls, item: Dict[str, Any]) -> "VacancyRecord":
        """Create from DynamoDB item."""

        def to_float(val: Any) -> float:
            if val is None:
                return 0.0
            if isinstance(val, Decimal):
                return float(val)
            return float(val)

        return cls(
            property_id=item.get("property_id", ""),
            vacancy_pct=to_float(item.get("vacancy_pct", 0)),
            vacancy_pct_bucket=item.get("vacancy_pct_bucket"),
            available_sqft=to_float(item.get("available_sqft", 0)),
            total_sqft=to_float(item.get("total_sqft", 0)),
            property_class=item.get("property_class"),
            property_type=item.get("property_type"),
            city=item.get("city"),
            state=item.get("state"),
            updated_at=item.get("updated_at"),
        )


@dataclass
class LeaseRecord:
    """
    Represents a record from the leases_view table.

    **Requirements: 5.3**

    Attributes:
        property_id: Property record ID (PK)
        lease_id: Lease record ID (SK)
        end_date: Lease end date (ISO 8601)
        end_date_month: YYYY-MM format for GSI
        tenant_id: Tenant Account ID
        tenant_name: Tenant name
        status: Lease status
        has_rofr: Right of First Refusal flag
        has_ti: Tenant Improvement flag
        has_noise_clause: Noise clause flag
        has_hvac_clause: HVAC clause flag
        updated_at: Last update timestamp
    """

    property_id: str
    lease_id: str
    end_date: Optional[str] = None
    end_date_month: Optional[str] = None
    tenant_id: Optional[str] = None
    tenant_name: Optional[str] = None
    status: Optional[str] = None
    has_rofr: bool = False
    has_ti: bool = False
    has_noise_clause: bool = False
    has_hvac_clause: bool = False
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "property_id": self.property_id,
            "lease_id": self.lease_id,
            "has_rofr": self.has_rofr,
            "has_ti": self.has_ti,
            "has_noise_clause": self.has_noise_clause,
            "has_hvac_clause": self.has_hvac_clause,
        }
        if self.end_date:
            result["end_date"] = self.end_date
        if self.end_date_month:
            result["end_date_month"] = self.end_date_month
        if self.tenant_id:
            result["tenant_id"] = self.tenant_id
        if self.tenant_name:
            result["tenant_name"] = self.tenant_name
        if self.status:
            result["status"] = self.status
        if self.updated_at:
            result["updated_at"] = self.updated_at
        return result

    @classmethod
    def from_item(cls, item: Dict[str, Any]) -> "LeaseRecord":
        """Create from DynamoDB item."""
        # Handle both 'end_date' and 'expiration_date' field names for compatibility
        end_date = item.get("end_date") or item.get("expiration_date")
        return cls(
            property_id=item.get("property_id", ""),
            lease_id=item.get("lease_id", ""),
            end_date=end_date,
            end_date_month=item.get("end_date_month"),
            tenant_id=item.get("tenant_id"),
            tenant_name=item.get("tenant_name"),
            status=item.get("status"),
            has_rofr=bool(item.get("has_rofr", False)),
            has_ti=bool(item.get("has_ti", False)),
            has_noise_clause=bool(item.get("has_noise_clause", False)),
            has_hvac_clause=bool(item.get("has_hvac_clause", False)),
            updated_at=item.get("updated_at"),
        )


@dataclass
class ActivityAggRecord:
    """
    Represents a record from the activities_agg table.

    **Requirements: 5.4**

    Attributes:
        entity_id: Entity record ID (PK)
        entity_type: Entity type (Account, Contact, Property, etc.)
        count_7d: Activity count in last 7 days
        count_30d: Activity count in last 30 days
        count_90d: Activity count in last 90 days
        last_activity_date: Last activity date
        maintenance_only_count: Count of maintenance-only activities
        updated_at: Last update timestamp
    """

    entity_id: str
    entity_type: Optional[str] = None
    count_7d: int = 0
    count_30d: int = 0
    count_90d: int = 0
    last_activity_date: Optional[str] = None
    maintenance_only_count: int = 0
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "entity_id": self.entity_id,
            "count_7d": self.count_7d,
            "count_30d": self.count_30d,
            "count_90d": self.count_90d,
            "maintenance_only_count": self.maintenance_only_count,
        }
        if self.entity_type:
            result["entity_type"] = self.entity_type
        if self.last_activity_date:
            result["last_activity_date"] = self.last_activity_date
        if self.updated_at:
            result["updated_at"] = self.updated_at
        return result

    @classmethod
    def from_item(cls, item: Dict[str, Any]) -> "ActivityAggRecord":
        """Create from DynamoDB item."""

        def to_int(val: Any) -> int:
            if val is None:
                return 0
            if isinstance(val, Decimal):
                return int(val)
            return int(val)

        return cls(
            entity_id=item.get("entity_id", ""),
            entity_type=item.get("entity_type"),
            count_7d=to_int(item.get("count_7d", 0)),
            count_30d=to_int(item.get("count_30d", 0)),
            count_90d=to_int(item.get("count_90d", 0)),
            last_activity_date=item.get("last_activity_date"),
            maintenance_only_count=to_int(item.get("maintenance_only_count", 0)),
            updated_at=item.get("updated_at"),
        )


@dataclass
class SaleRecord:
    """
    Represents a record from the sales_view table.

    **Requirements: 5.5**

    Attributes:
        sale_id: Sale record ID (PK)
        sale_name: Sale name/description
        property_id: Property record ID
        property_name: Property name
        city: City location
        sale_date: Date of sale
        sale_price: Sale price amount
        listing_date: Listing date
        listing_price: Listing price
        buyer_name: Buyer name
        seller_name: Seller name
        updated_at: Last update timestamp
    """

    sale_id: str
    sale_name: Optional[str] = None
    property_id: Optional[str] = None
    property_name: Optional[str] = None
    city: Optional[str] = None
    sale_date: Optional[str] = None
    sale_price: Optional[float] = None
    listing_date: Optional[str] = None
    listing_price: Optional[float] = None
    buyer_name: Optional[str] = None
    seller_name: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {"sale_id": self.sale_id}
        if self.sale_name:
            result["sale_name"] = self.sale_name
        if self.property_id:
            result["property_id"] = self.property_id
        if self.property_name:
            result["property_name"] = self.property_name
        if self.city:
            result["city"] = self.city
        if self.sale_date:
            result["sale_date"] = self.sale_date
        if self.sale_price is not None:
            result["sale_price"] = self.sale_price
        if self.listing_date:
            result["listing_date"] = self.listing_date
        if self.listing_price is not None:
            result["listing_price"] = self.listing_price
        if self.buyer_name:
            result["buyer_name"] = self.buyer_name
        if self.seller_name:
            result["seller_name"] = self.seller_name
        if self.updated_at:
            result["updated_at"] = self.updated_at
        return result

    @classmethod
    def from_item(cls, item: Dict[str, Any]) -> "SaleRecord":
        """Create from DynamoDB item."""
        sale_price = item.get("sale_price")
        if isinstance(sale_price, Decimal):
            sale_price = float(sale_price)
        listing_price = item.get("listing_price")
        if isinstance(listing_price, Decimal):
            listing_price = float(listing_price)
        return cls(
            sale_id=item.get("sale_id", ""),
            sale_name=item.get("sale_name"),
            property_id=item.get("property_id"),
            property_name=item.get("property_name"),
            city=item.get("city"),
            sale_date=item.get("sale_date"),
            sale_price=sale_price,
            listing_date=item.get("listing_date"),
            listing_price=listing_price,
            buyer_name=item.get("buyer_name"),
            seller_name=item.get("seller_name"),
            updated_at=item.get("updated_at"),
        )


@dataclass
class MissingRollupGap:
    """
    Represents a missing rollup gap for logging.

    **Requirements: 5.7**
    """

    view_name: str
    query: str
    filters: List[Dict[str, Any]]
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# =============================================================================
# Derived View Manager Class
# =============================================================================


class DerivedViewManager:
    """
    Manages derived view queries for aggregation data.

    **Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7**

    Derived views are physically materialized DynamoDB tables that store
    pre-computed aggregations and denormalized data to avoid runtime
    computation.
    """

    def __init__(
        self,
        dynamodb_resource: Optional[Any] = None,
        availability_table_name: Optional[str] = None,
        vacancy_table_name: Optional[str] = None,
        leases_table_name: Optional[str] = None,
        activities_table_name: Optional[str] = None,
        sales_table_name: Optional[str] = None,
    ):
        """
        Initialize the DerivedViewManager.

        Args:
            dynamodb_resource: Optional boto3 DynamoDB resource (for testing)
            availability_table_name: Override availability view table name
            vacancy_table_name: Override vacancy view table name
            leases_table_name: Override leases view table name
            activities_table_name: Override activities agg table name
            sales_table_name: Override sales view table name
        """
        self._dynamodb = dynamodb_resource
        self._tables: Dict[str, Any] = {}

        # Table names
        self.availability_table_name = (
            availability_table_name or AVAILABILITY_VIEW_TABLE
        )
        self.vacancy_table_name = vacancy_table_name or VACANCY_VIEW_TABLE
        self.leases_table_name = leases_table_name or LEASES_VIEW_TABLE
        self.activities_table_name = activities_table_name or ACTIVITIES_AGG_TABLE
        self.sales_table_name = sales_table_name or SALES_VIEW_TABLE

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

    # =========================================================================
    # Availability View Queries (Requirement 5.1)
    # =========================================================================

    def query_availability_view(
        self,
        filters: Optional[List[Predicate]] = None,
        property_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[AvailabilityRecord]:
        """
        Query the availability_view table.

        **Requirements: 5.1, 5.6**

        Args:
            filters: List of Predicate filters to apply
            property_id: Optional property ID for point query
            limit: Maximum records to return

        Returns:
            List of AvailabilityRecord objects
        """
        start_time = time.time()
        table = self._get_table(self.availability_table_name)
        results: List[AvailabilityRecord] = []

        try:
            if property_id:
                # Point query by property_id
                response = table.query(
                    KeyConditionExpression="property_id = :pid",
                    ExpressionAttributeValues={":pid": property_id},
                    Limit=limit,
                )
                items = response.get("Items", [])
            else:
                # Scan with filters (for cross-property queries)
                response = table.scan(Limit=limit)
                items = response.get("Items", [])

            # Convert to records
            for item in items:
                record = AvailabilityRecord.from_item(item)
                results.append(record)

            # Apply predicate filters in memory
            if filters:
                results = self._apply_filters(results, filters)

            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.debug(
                f"query_availability_view: {len(results)} records ({elapsed_ms:.1f}ms)"
            )
            return results

        except ClientError as e:
            LOGGER.error(
                f"DynamoDB error in query_availability_view: "
                f"{e.response['Error']['Message']}"
            )
            return []
        except Exception as e:
            LOGGER.error(f"Error in query_availability_view: {str(e)}")
            return []

    # =========================================================================
    # Vacancy View Queries (Requirement 5.2)
    # =========================================================================

    def query_vacancy_view(
        self,
        filters: Optional[List[Predicate]] = None,
        property_id: Optional[str] = None,
        min_vacancy_pct: Optional[float] = None,
        max_vacancy_pct: Optional[float] = None,
        limit: int = 100,
    ) -> List[VacancyRecord]:
        """
        Query the vacancy_view table.

        **Requirements: 5.2, 5.6**

        Args:
            filters: List of Predicate filters to apply
            property_id: Optional property ID for point query
            min_vacancy_pct: Minimum vacancy percentage filter
            max_vacancy_pct: Maximum vacancy percentage filter
            limit: Maximum records to return

        Returns:
            List of VacancyRecord objects
        """
        start_time = time.time()
        table = self._get_table(self.vacancy_table_name)
        results: List[VacancyRecord] = []

        try:
            if property_id:
                # Point query by property_id
                response = table.get_item(Key={"property_id": property_id})
                item = response.get("Item")
                if item:
                    results.append(VacancyRecord.from_item(item))
            else:
                # Scan with filters
                response = table.scan(Limit=limit)
                items = response.get("Items", [])
                for item in items:
                    results.append(VacancyRecord.from_item(item))

            # Apply vacancy percentage filters
            if min_vacancy_pct is not None:
                results = [r for r in results if r.vacancy_pct >= min_vacancy_pct]
            if max_vacancy_pct is not None:
                results = [r for r in results if r.vacancy_pct <= max_vacancy_pct]

            # Apply additional predicate filters
            if filters:
                results = self._apply_filters(results, filters)

            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.debug(
                f"query_vacancy_view: {len(results)} records ({elapsed_ms:.1f}ms)"
            )
            return results

        except ClientError as e:
            LOGGER.error(
                f"DynamoDB error in query_vacancy_view: "
                f"{e.response['Error']['Message']}"
            )
            return []
        except Exception as e:
            LOGGER.error(f"Error in query_vacancy_view: {str(e)}")
            return []

    # =========================================================================
    # Leases View Queries (Requirement 5.3)
    # =========================================================================

    def query_leases_view(
        self,
        filters: Optional[List[Predicate]] = None,
        property_id: Optional[str] = None,
        end_date_month: Optional[str] = None,
        end_date_range: Optional[tuple] = None,
        limit: int = 100,
    ) -> List[LeaseRecord]:
        """
        Query the leases_view table.

        **Requirements: 5.3, 5.6**

        Args:
            filters: List of Predicate filters to apply
            property_id: Optional property ID for query
            end_date_month: YYYY-MM format for GSI query
            end_date_range: Tuple of (start_date, end_date) for range filtering
            limit: Maximum records to return

        Returns:
            List of LeaseRecord objects
        """
        start_time = time.time()
        table = self._get_table(self.leases_table_name)
        results: List[LeaseRecord] = []

        try:
            if property_id:
                # Query by property_id
                response = table.query(
                    KeyConditionExpression="property_id = :pid",
                    ExpressionAttributeValues={":pid": property_id},
                    Limit=limit,
                )
                items = response.get("Items", [])
            elif end_date_month:
                # Query by end_date_month GSI
                response = table.query(
                    IndexName="end-date-index",
                    KeyConditionExpression="end_date_month = :edm",
                    ExpressionAttributeValues={":edm": end_date_month},
                    Limit=limit,
                )
                items = response.get("Items", [])
            else:
                # Scan
                response = table.scan(Limit=limit)
                items = response.get("Items", [])

            # Convert to records
            for item in items:
                results.append(LeaseRecord.from_item(item))

            # Apply end_date_range filter
            if end_date_range and len(end_date_range) >= 2:
                start_date, end_date = end_date_range
                results = [
                    r
                    for r in results
                    if r.end_date and start_date <= r.end_date <= end_date
                ]

            # Apply additional predicate filters
            if filters:
                results = self._apply_filters(results, filters)

            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.debug(
                f"query_leases_view: {len(results)} records ({elapsed_ms:.1f}ms)"
            )
            return results

        except ClientError as e:
            LOGGER.error(
                f"DynamoDB error in query_leases_view: "
                f"{e.response['Error']['Message']}"
            )
            return []
        except Exception as e:
            LOGGER.error(f"Error in query_leases_view: {str(e)}")
            return []

    # =========================================================================
    # Activities Aggregation Queries (Requirement 5.4)
    # =========================================================================

    def query_activities_agg(
        self,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        min_count: Optional[int] = None,
        window_days: int = 30,
        limit: int = 100,
    ) -> List[ActivityAggRecord]:
        """
        Query the activities_agg table.

        **Requirements: 5.4, 5.6**

        Args:
            entity_id: Optional entity ID for point query
            entity_type: Optional entity type for GSI query
            min_count: Minimum activity count filter
            window_days: Activity window (7, 30, or 90 days)
            limit: Maximum records to return

        Returns:
            List of ActivityAggRecord objects
        """
        start_time = time.time()
        table = self._get_table(self.activities_table_name)
        results: List[ActivityAggRecord] = []

        try:
            if entity_id:
                # Point query by entity_id
                response = table.get_item(Key={"entity_id": entity_id})
                item = response.get("Item")
                if item:
                    results.append(ActivityAggRecord.from_item(item))
            elif entity_type:
                # Query by entity_type GSI
                response = table.query(
                    IndexName="entity-type-index",
                    KeyConditionExpression="entity_type = :et",
                    ExpressionAttributeValues={":et": entity_type},
                    Limit=limit,
                )
                items = response.get("Items", [])
                for item in items:
                    results.append(ActivityAggRecord.from_item(item))
            else:
                # Scan
                response = table.scan(Limit=limit)
                items = response.get("Items", [])
                for item in items:
                    results.append(ActivityAggRecord.from_item(item))

            # Apply min_count filter based on window
            if min_count is not None:
                if window_days <= 7:
                    results = [r for r in results if r.count_7d >= min_count]
                elif window_days <= 30:
                    results = [r for r in results if r.count_30d >= min_count]
                else:
                    results = [r for r in results if r.count_90d >= min_count]

            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.debug(
                f"query_activities_agg: {len(results)} records ({elapsed_ms:.1f}ms)"
            )
            return results

        except ClientError as e:
            LOGGER.error(
                f"DynamoDB error in query_activities_agg: "
                f"{e.response['Error']['Message']}"
            )
            return []
        except Exception as e:
            LOGGER.error(f"Error in query_activities_agg: {str(e)}")
            return []

    def get_activity_count(
        self, entity_id: str, window_days: int = 30
    ) -> Optional[int]:
        """
        Get activity count for an entity.

        **Requirements: 5.4**

        Args:
            entity_id: Entity record ID
            window_days: Activity window (7, 30, or 90 days)

        Returns:
            Activity count or None if not found
        """
        records = self.query_activities_agg(entity_id=entity_id)
        if not records:
            return None

        record = records[0]
        if window_days <= 7:
            return record.count_7d
        elif window_days <= 30:
            return record.count_30d
        else:
            return record.count_90d

    # =========================================================================
    # Sales View Queries (Requirement 5.5)
    # =========================================================================

    def query_sales_view(
        self,
        filters: Optional[List[Predicate]] = None,
        sale_id: Optional[str] = None,
        property_id: Optional[str] = None,
        stage: Optional[str] = None,
        broker_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[SaleRecord]:
        """
        Query the sales_view table.

        **Requirements: 5.5, 5.6**

        Args:
            filters: List of Predicate filters to apply
            sale_id: Optional sale ID for point query
            property_id: Optional property ID for GSI query
            stage: Optional stage for GSI query
            broker_id: Optional broker ID for filtering
            limit: Maximum records to return

        Returns:
            List of SaleRecord objects
        """
        start_time = time.time()
        table = self._get_table(self.sales_table_name)
        results: List[SaleRecord] = []

        try:
            if sale_id:
                # Point query by sale_id
                response = table.get_item(Key={"sale_id": sale_id})
                item = response.get("Item")
                if item:
                    results.append(SaleRecord.from_item(item))
            elif stage:
                # Query by stage GSI
                response = table.query(
                    IndexName="stage-index",
                    KeyConditionExpression="stage = :s",
                    ExpressionAttributeValues={":s": stage},
                    Limit=limit,
                )
                items = response.get("Items", [])
                for item in items:
                    results.append(SaleRecord.from_item(item))
            elif property_id:
                # Query by property_id GSI
                response = table.query(
                    IndexName="property-index",
                    KeyConditionExpression="property_id = :pid",
                    ExpressionAttributeValues={":pid": property_id},
                    Limit=limit,
                )
                items = response.get("Items", [])
                for item in items:
                    results.append(SaleRecord.from_item(item))
            else:
                # Scan
                response = table.scan(Limit=limit)
                items = response.get("Items", [])
                for item in items:
                    results.append(SaleRecord.from_item(item))

            # Apply broker_id filter
            if broker_id:
                results = [r for r in results if broker_id in r.broker_ids]

            # Apply additional predicate filters
            if filters:
                results = self._apply_filters(results, filters)

            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.debug(
                f"query_sales_view: {len(results)} records ({elapsed_ms:.1f}ms)"
            )
            return results

        except ClientError as e:
            LOGGER.error(
                f"DynamoDB error in query_sales_view: "
                f"{e.response['Error']['Message']}"
            )
            return []
        except Exception as e:
            LOGGER.error(f"Error in query_sales_view: {str(e)}")
            return []

    # =========================================================================
    # Missing Rollup Detection (Requirement 5.7)
    # =========================================================================

    def check_view_exists(
        self, view_name: str, filters: Optional[List[Predicate]] = None
    ) -> bool:
        """
        Check if required rollup data exists for a query.

        **Requirements: 5.7**

        Args:
            view_name: Name of the view to check
            filters: Filters to apply

        Returns:
            True if view has data matching criteria
        """
        try:
            if view_name == "availability_view":
                results = self.query_availability_view(filters=filters, limit=1)
            elif view_name == "vacancy_view":
                results = self.query_vacancy_view(filters=filters, limit=1)
            elif view_name == "leases_view":
                results = self.query_leases_view(filters=filters, limit=1)
            elif view_name == "activities_agg":
                results = self.query_activities_agg(limit=1)
            elif view_name == "sales_view":
                results = self.query_sales_view(filters=filters, limit=1)
            else:
                LOGGER.warning(f"Unknown view name: {view_name}")
                return False

            return len(results) > 0

        except Exception as e:
            LOGGER.error(f"Error checking view exists: {str(e)}")
            return False

    def log_missing_rollup(
        self,
        view_name: str,
        query: str,
        filters: Optional[List[Predicate]] = None,
    ) -> None:
        """
        Log a gap when required rollup is missing.

        **Requirements: 5.7**

        Args:
            view_name: Name of the missing view
            query: Original query string
            filters: Filters that were requested
        """
        filter_dicts = []
        if filters:
            for f in filters:
                filter_dicts.append(
                    {"field": f.field, "operator": f.operator, "value": str(f.value)}
                )

        gap = MissingRollupGap(
            view_name=view_name,
            query=query,
            filters=filter_dicts,
        )

        LOGGER.warning(
            "Missing rollup gap detected",
            extra={
                "view_name": gap.view_name,
                "query": gap.query[:200],
                "filters": gap.filters,
                "gap_type": "missing_rollup",
                "timestamp": gap.timestamp,
            },
        )

    def query_with_fallback(
        self,
        view_name: str,
        query: str,
        filters: Optional[List[Predicate]] = None,
        **kwargs,
    ) -> tuple[List[Any], bool]:
        """
        Query a view with fallback detection.

        **Requirements: 5.6, 5.7**

        Args:
            view_name: Name of the view to query
            query: Original query string for logging
            filters: Predicate filters
            **kwargs: Additional arguments for specific view queries

        Returns:
            Tuple of (results, used_fallback)
        """
        try:
            if view_name == "availability_view":
                results = self.query_availability_view(filters=filters, **kwargs)
            elif view_name == "vacancy_view":
                results = self.query_vacancy_view(filters=filters, **kwargs)
            elif view_name == "leases_view":
                results = self.query_leases_view(filters=filters, **kwargs)
            elif view_name == "activities_agg":
                results = self.query_activities_agg(**kwargs)
            elif view_name == "sales_view":
                results = self.query_sales_view(filters=filters, **kwargs)
            else:
                LOGGER.warning(f"Unknown view name: {view_name}")
                self.log_missing_rollup(view_name, query, filters)
                return [], True

            if not results:
                # Log gap but don't treat as fallback if query executed successfully
                self.log_missing_rollup(view_name, query, filters)
                return [], True

            return results, False

        except Exception as e:
            LOGGER.error(f"Error querying {view_name}: {str(e)}")
            self.log_missing_rollup(view_name, query, filters)
            return [], True

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _apply_filters(
        self,
        records: List[Any],
        filters: List[Predicate],
    ) -> List[Any]:
        """
        Apply predicate filters to records in memory.

        Args:
            records: List of record objects
            filters: List of Predicate filters

        Returns:
            Filtered list of records
        """
        if not filters:
            return records

        filtered: List[Any] = []
        for record in records:
            matches = True
            record_dict = record.to_dict() if hasattr(record, "to_dict") else record

            for pred in filters:
                value = record_dict.get(pred.field)
                if not pred.matches(value):
                    matches = False
                    break

            if matches:
                filtered.append(record)

        return filtered


# =============================================================================
# Convenience Functions
# =============================================================================


def get_vacancy_above_threshold(
    threshold_pct: float,
    manager: Optional[DerivedViewManager] = None,
    limit: int = 100,
) -> List[VacancyRecord]:
    """
    Get properties with vacancy above a threshold.

    **Requirements: 5.2**

    Args:
        threshold_pct: Minimum vacancy percentage
        manager: Optional DerivedViewManager instance
        limit: Maximum records to return

    Returns:
        List of VacancyRecord objects
    """
    mgr = manager or DerivedViewManager()
    return mgr.query_vacancy_view(min_vacancy_pct=threshold_pct, limit=limit)


def get_leases_expiring_in_range(
    start_date: str,
    end_date: str,
    manager: Optional[DerivedViewManager] = None,
    limit: int = 100,
) -> List[LeaseRecord]:
    """
    Get leases expiring within a date range.

    **Requirements: 5.3**

    Args:
        start_date: Start date (ISO 8601)
        end_date: End date (ISO 8601)
        manager: Optional DerivedViewManager instance
        limit: Maximum records to return

    Returns:
        List of LeaseRecord objects
    """
    mgr = manager or DerivedViewManager()
    return mgr.query_leases_view(end_date_range=(start_date, end_date), limit=limit)


def get_entities_with_activity_count(
    entity_type: str,
    min_count: int,
    window_days: int = 30,
    manager: Optional[DerivedViewManager] = None,
    limit: int = 100,
) -> List[ActivityAggRecord]:
    """
    Get entities with activity count above threshold.

    **Requirements: 5.4**

    Args:
        entity_type: Type of entity (Account, Contact, Property, etc.)
        min_count: Minimum activity count
        window_days: Activity window (7, 30, or 90 days)
        manager: Optional DerivedViewManager instance
        limit: Maximum records to return

    Returns:
        List of ActivityAggRecord objects
    """
    mgr = manager or DerivedViewManager()
    return mgr.query_activities_agg(
        entity_type=entity_type,
        min_count=min_count,
        window_days=window_days,
        limit=limit,
    )


def get_sales_by_broker(
    broker_id: str,
    stage: Optional[str] = None,
    manager: Optional[DerivedViewManager] = None,
    limit: int = 100,
) -> List[SaleRecord]:
    """
    Get sales for a broker.

    **Requirements: 5.5**

    Args:
        broker_id: Broker Contact ID
        stage: Optional stage filter
        manager: Optional DerivedViewManager instance
        limit: Maximum records to return

    Returns:
        List of SaleRecord objects
    """
    mgr = manager or DerivedViewManager()
    return mgr.query_sales_view(broker_id=broker_id, stage=stage, limit=limit)
