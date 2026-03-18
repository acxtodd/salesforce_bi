"""Tests for the tool dispatch module (Task 1.1.1).

All tests use a mock SearchBackend — no network or API keys required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure project root is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.search_backend import SearchBackend
from lib.tool_dispatch import (
    FieldSet,
    FieldValidationError,
    SEMANTIC_ALIASES,
    ToolDispatcher,
    _clean_label,
    _extract_base_field,
    _extract_suffix,
    _to_snake_case,
    build_field_registry,
)

# =========================================================================
# Test fixtures
# =========================================================================

SAMPLE_CONFIG = {
    "ascendix__Property__c": {
        "embed_fields": [
            "Name",
            "ascendix__City__c",
            "ascendix__State__c",
            "ascendix__PropertyClass__c",
            "ascendix__PropertySubType__c",
            "ascendix__Description__c",
        ],
        "metadata_fields": [
            "ascendix__TotalBuildingArea__c",
            "ascendix__Floors__c",
            "ascendix__YearBuilt__c",
        ],
        "parents": {
            "ascendix__OwnerLandlord__c": ["Name"],
            "ascendix__Market__c": ["Name"],
            "ascendix__SubMarket__c": ["Name"],
        },
    },
    "ascendix__Lease__c": {
        "embed_fields": [
            "Name",
            "ascendix__LeaseType__c",
        ],
        "metadata_fields": [
            "ascendix__Size__c",
            "ascendix__LeaseRatePerUOM__c",
            "ascendix__TermCommencementDate__c",
            "ascendix__TermExpirationDate__c",
        ],
        "parents": {
            "ascendix__Property__c": [
                "Name",
                "ascendix__City__c",
                "ascendix__State__c",
                "ascendix__PropertyClass__c",
            ],
            "ascendix__Tenant__c": ["Name"],
            "ascendix__OwnerLandlord__c": ["Name"],
        },
    },
    "ascendix__Availability__c": {
        "embed_fields": [
            "Name",
            "ascendix__UseType__c",
            "ascendix__Status__c",
        ],
        "metadata_fields": [
            "ascendix__AvailableArea__c",
            "ascendix__RentLow__c",
            "ascendix__RentHigh__c",
        ],
        "parents": {
            "ascendix__Market__c": ["Name"],
            "ascendix__SubMarket__c": ["Name"],
            "ascendix__Region__c": ["Name"],
            "ascendix__Property__c": [
                "Name",
                "ascendix__City__c",
            ],
        },
    },
}


def _make_dispatcher(
    search_return=None,
    aggregate_return=None,
    config=None,
    semantic_aliases=None,
):
    """Create a ToolDispatcher wired to a mock SearchBackend."""
    backend = MagicMock(spec=SearchBackend)
    backend.search.return_value = search_return or []
    backend.aggregate.return_value = aggregate_return or {"count": 0}
    registry = build_field_registry(
        config or SAMPLE_CONFIG,
        semantic_aliases=semantic_aliases if semantic_aliases is not None else SEMANTIC_ALIASES,
    )
    dispatcher = ToolDispatcher(backend, "org_test", registry)
    return dispatcher, backend


# =========================================================================
# _clean_label
# =========================================================================


class TestCleanLabel:
    def test_strips_namespace_and_suffix(self):
        assert _clean_label("ascendix__City__c") == "City"

    def test_strips_relationship_suffix(self):
        assert _clean_label("ascendix__Property__r") == "Property"

    def test_standard_field_unchanged(self):
        assert _clean_label("Name") == "Name"

    def test_does_not_lowercase(self):
        assert _clean_label("ascendix__PropertyClass__c") == "PropertyClass"


# =========================================================================
# _to_snake_case
# =========================================================================


class TestToSnakeCase:
    def test_simple_camel(self):
        assert _to_snake_case("PropertyClass") == "property_class"

    def test_multi_word(self):
        assert _to_snake_case("TotalBuildingArea") == "total_building_area"

    def test_consecutive_uppercase(self):
        assert _to_snake_case("LeaseRatePerUOM") == "lease_rate_per_uom"

    def test_already_lower(self):
        assert _to_snake_case("city") == "city"

    def test_single_word(self):
        assert _to_snake_case("Name") == "name"


# =========================================================================
# _extract_base_field / _extract_suffix
# =========================================================================


class TestExtractBaseField:
    def test_no_suffix(self):
        assert _extract_base_field("city") == "city"

    def test_gte(self):
        assert _extract_base_field("total_sf_gte") == "total_sf"

    def test_lte(self):
        assert _extract_base_field("price_lte") == "price"

    def test_in(self):
        assert _extract_base_field("property_type_in") == "property_type"

    def test_ne(self):
        assert _extract_base_field("status_ne") == "status"

    def test_not_a_suffix(self):
        # "_date" is not a recognised suffix — leave untouched
        assert _extract_base_field("begin_date") == "begin_date"

    def test_gt(self):
        assert _extract_base_field("floors_gt") == "floors"

    def test_lt(self):
        assert _extract_base_field("floors_lt") == "floors"


class TestExtractSuffix:
    def test_no_suffix(self):
        assert _extract_suffix("city") == ""

    def test_gte(self):
        assert _extract_suffix("total_sf_gte") == "_gte"

    def test_in(self):
        assert _extract_suffix("type_in") == "_in"


# =========================================================================
# build_field_registry
# =========================================================================


class TestBuildFieldRegistry:
    @pytest.fixture(autouse=True)
    def _build(self):
        self.registry = build_field_registry(SAMPLE_CONFIG, SEMANTIC_ALIASES)

    def test_correct_object_types(self):
        assert set(self.registry.keys()) == {"property", "lease", "availability"}

    def test_property_direct_fields(self):
        fs = self.registry["property"]
        for f in ("name", "city", "state", "propertyclass", "propertysubtype",
                  "description", "totalbuildingarea", "floors", "yearbuilt"):
            assert f in fs.filterable, f"missing {f}"

    def test_property_parent_fields(self):
        fs = self.registry["property"]
        for f in ("ownerlandlord_name", "market_name", "submarket_name"):
            assert f in fs.filterable, f"missing {f}"

    def test_lease_parent_fields(self):
        fs = self.registry["lease"]
        for f in ("property_name", "property_city", "property_state",
                  "property_propertyclass", "tenant_name", "ownerlandlord_name"):
            assert f in fs.filterable, f"missing {f}"

    def test_availability_geography_parent_fields(self):
        fs = self.registry["availability"]
        for f in ("market_name", "submarket_name", "region_name"):
            assert f in fs.filterable, f"missing {f}"

    def test_platform_fields_in_every_type(self):
        for obj_type, fs in self.registry.items():
            for pf in ("object_type", "text", "last_modified", "salesforce_org_id", "name"):
                assert pf in fs.filterable, f"missing {pf} in {obj_type}"

    def test_id_is_result_only(self):
        for obj_type, fs in self.registry.items():
            assert "id" in fs.result_fields, f"id not in result_fields for {obj_type}"
            assert "id" not in fs.filterable, f"id should not be filterable for {obj_type}"

    def test_auto_aliases_generated(self):
        fs = self.registry["property"]
        assert "property_class" in fs.aliases
        assert fs.aliases["property_class"] == "propertyclass"

    def test_semantic_aliases_merged(self):
        fs = self.registry["lease"]
        assert "leased_sf" in fs.aliases
        assert fs.aliases["leased_sf"] == "size"
        assert "start_date" in fs.aliases
        assert fs.aliases["start_date"] == "termcommencementdate"

    def test_availability_geography_aliases_merged(self):
        fs = self.registry["availability"]
        assert fs.aliases["market"] == "market_name"
        assert fs.aliases["submarket"] == "submarket_name"
        assert fs.aliases["region"] == "region_name"

    def test_empty_config(self):
        reg = build_field_registry({})
        assert reg == {}


# =========================================================================
# Field resolution
# =========================================================================


class TestFieldResolution:
    @pytest.fixture(autouse=True)
    def _build(self):
        self.dispatcher, _ = _make_dispatcher()

    def test_indexed_name_passthrough(self):
        assert self.dispatcher._resolve_field("city", "property") == "city"

    def test_auto_alias_resolves(self):
        assert self.dispatcher._resolve_field("property_class", "property") == "propertyclass"

    def test_semantic_alias_resolves(self):
        assert self.dispatcher._resolve_field("leased_sf", "lease") == "size"

    def test_start_date_resolves(self):
        assert self.dispatcher._resolve_field("start_date", "lease") == "termcommencementdate"

    def test_unknown_field_raises(self):
        with pytest.raises(FieldValidationError, match="Invalid field 'bogus'"):
            self.dispatcher._resolve_field("bogus", "property")

    def test_asking_rate_psf_not_aliased(self):
        """asking_rate_psf should be rejected — not silently mapped to rentlow."""
        with pytest.raises(FieldValidationError, match="asking_rate_psf"):
            self.dispatcher._resolve_field("asking_rate_psf", "availability")

    def test_property_class_resolves_on_availability(self):
        assert self.dispatcher._resolve_field("property_class", "availability") == "property_propertyclass"

    def test_property_class_resolves_on_lease(self):
        assert self.dispatcher._resolve_field("property_class", "lease") == "property_propertyclass"

    def test_resolve_filters_preserves_suffix(self):
        result = self.dispatcher._resolve_filters(
            {"leased_sf_gte": 10000, "property_city": "Dallas"},
            "lease",
        )
        assert result == {"size_gte": 10000, "property_city": "Dallas"}

    def test_resolve_filters_alias_with_in(self):
        result = self.dispatcher._resolve_filters(
            {"property_class_in": ["A", "B"]},
            "property",
        )
        assert result == {"propertyclass_in": ["A", "B"]}


# =========================================================================
# dispatch — unknown tools
# =========================================================================


class TestDispatchUnknownTool:
    def test_unknown_tool(self):
        d, _ = _make_dispatcher()
        result = d.dispatch({"name": "bogus"})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_live_salesforce_query_rejected(self):
        d, _ = _make_dispatcher()
        result = d.dispatch({"name": "live_salesforce_query", "parameters": {}})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_missing_name(self):
        d, _ = _make_dispatcher()
        result = d.dispatch({})
        assert "error" in result


# =========================================================================
# dispatch — search_records
# =========================================================================


class TestDispatchSearchRecords:
    def test_basic_search(self):
        d, backend = _make_dispatcher(search_return=[
            {"id": "001", "dist": 0.9, "name": "Test Property"},
        ])
        result = d.dispatch({
            "name": "search_records",
            "parameters": {"object_type": "Property", "text_query": "office"},
        })
        assert "results" in result
        assert len(result["results"]) == 1
        backend.search.assert_called_once()

    def test_object_type_added_as_filter(self):
        d, backend = _make_dispatcher()
        d.dispatch({
            "name": "search_records",
            "parameters": {"object_type": "Lease", "text_query": "test"},
        })
        call_kwargs = backend.search.call_args[1]
        assert call_kwargs["filters"]["object_type"] == "lease"

    def test_text_query_forwarded(self):
        d, backend = _make_dispatcher()
        d.dispatch({
            "name": "search_records",
            "parameters": {"object_type": "Property", "text_query": "Dallas office"},
        })
        call_kwargs = backend.search.call_args[1]
        assert call_kwargs["text_query"] == "Dallas office"

    def test_default_limit_is_10(self):
        d, backend = _make_dispatcher()
        d.dispatch({
            "name": "search_records",
            "parameters": {"object_type": "Property", "text_query": "x"},
        })
        call_kwargs = backend.search.call_args[1]
        assert call_kwargs["top_k"] == 10

    def test_limit_capped_at_50(self):
        d, backend = _make_dispatcher()
        d.dispatch({
            "name": "search_records",
            "parameters": {"object_type": "Property", "text_query": "x", "limit": 100},
        })
        call_kwargs = backend.search.call_args[1]
        assert call_kwargs["top_k"] == 50

    def test_alias_resolved_in_filters(self):
        d, backend = _make_dispatcher()
        d.dispatch({
            "name": "search_records",
            "parameters": {
                "object_type": "Lease",
                "filters": {"leased_sf_gte": 10000, "start_date_gte": "2025-01-01"},
                "text_query": "lease comp",
            },
        })
        call_kwargs = backend.search.call_args[1]
        filters = call_kwargs["filters"]
        assert "size_gte" in filters
        assert "termcommencementdate_gte" in filters
        assert filters["size_gte"] == 10000

    def test_include_attributes_returns_all(self):
        d, backend = _make_dispatcher()
        d.dispatch({
            "name": "search_records",
            "parameters": {"object_type": "Property", "text_query": "x"},
        })
        call_kwargs = backend.search.call_args[1]
        assert call_kwargs["include_attributes"] is True

    def test_unknown_filter_field_returns_error(self):
        d, _ = _make_dispatcher()
        result = d.dispatch({
            "name": "search_records",
            "parameters": {
                "object_type": "Property",
                "filters": {"bogus_field": "x"},
                "text_query": "test",
            },
        })
        assert "error" in result
        assert "bogus_field" in result["error"]

    def test_missing_object_type(self):
        d, _ = _make_dispatcher()
        result = d.dispatch({
            "name": "search_records",
            "parameters": {"text_query": "test"},
        })
        assert "error" in result
        assert "object_type" in result["error"]


# =========================================================================
# dispatch — search with no text_query
# =========================================================================


class TestDispatchNoTextQuery:
    def test_no_text_query_uses_broad_scan(self):
        d, backend = _make_dispatcher()
        d.dispatch({
            "name": "search_records",
            "parameters": {
                "object_type": "Property",
                "filters": {"city": "Dallas"},
            },
        })
        call_kwargs = backend.search.call_args[1]
        assert call_kwargs["text_query"] == "Property"

    def test_filters_only_returns_results(self):
        d, backend = _make_dispatcher(search_return=[
            {"id": "001", "dist": 0.1, "name": "Test"},
        ])
        result = d.dispatch({
            "name": "search_records",
            "parameters": {
                "object_type": "Property",
                "filters": {"city": "Dallas"},
            },
        })
        assert "results" in result
        assert len(result["results"]) == 1


# =========================================================================
# dispatch — aggregate_records
# =========================================================================


class TestDispatchAggregateRecords:
    def test_basic_count(self):
        d, backend = _make_dispatcher(aggregate_return={"count": 42})
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {"object_type": "Property", "aggregate": "count"},
        })
        assert result == {"result": {"count": 42}}
        backend.aggregate.assert_called_once()

    def test_sum_with_field(self):
        d, backend = _make_dispatcher(aggregate_return={"sum": 500000})
        d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Lease",
                "aggregate": "sum",
                "aggregate_field": "leased_sf",
            },
        })
        call_kwargs = backend.aggregate.call_args[1]
        assert call_kwargs["aggregate_field"] == "size"  # resolved alias

    def test_avg_with_group_by(self):
        d, backend = _make_dispatcher(
            aggregate_return={"groups": {"A": {"avg": 35.0}, "B": {"avg": 25.0}}}
        )
        d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Availability",
                "aggregate": "avg",
                "aggregate_field": "rentlow",
                "group_by": "property_city",
            },
        })
        call_kwargs = backend.aggregate.call_args[1]
        assert call_kwargs["group_by"] == "property_city"

    def test_object_type_in_filters(self):
        d, backend = _make_dispatcher(aggregate_return={"count": 5})
        d.dispatch({
            "name": "aggregate_records",
            "parameters": {"object_type": "Lease", "aggregate": "count"},
        })
        call_kwargs = backend.aggregate.call_args[1]
        assert call_kwargs["filters"]["object_type"] == "lease"

    def test_filter_field_validation(self):
        d, _ = _make_dispatcher()
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "count",
                "filters": {"nonexistent": "val"},
            },
        })
        assert "error" in result

    def test_aggregate_field_validation(self):
        d, _ = _make_dispatcher()
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "sum",
                "aggregate_field": "nonexistent",
            },
        })
        assert "error" in result

    def test_group_by_validation(self):
        d, _ = _make_dispatcher()
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "count",
                "group_by": "nonexistent",
            },
        })
        assert "error" in result

    def test_unsupported_aggregate(self):
        d, _ = _make_dispatcher()
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "median",
            },
        })
        assert "error" in result
        assert "median" in result["error"]


# =========================================================================
# dispatch — error handling
# =========================================================================


class TestDispatchErrorHandling:
    def test_backend_exception_wrapped(self):
        d, backend = _make_dispatcher()
        backend.search.side_effect = RuntimeError("connection failed")
        result = d.dispatch({
            "name": "search_records",
            "parameters": {"object_type": "Property", "text_query": "x"},
        })
        assert "error" in result
        assert "connection failed" in result["error"]

    def test_case_insensitive_object_type(self):
        d, backend = _make_dispatcher()
        d.dispatch({
            "name": "search_records",
            "parameters": {"object_type": "PROPERTY", "text_query": "x"},
        })
        backend.search.assert_called_once()

    def test_invalid_object_type(self):
        d, _ = _make_dispatcher()
        result = d.dispatch({
            "name": "search_records",
            "parameters": {"object_type": "Widget", "text_query": "x"},
        })
        assert "error" in result
        assert "Widget" in result["error"]


# =========================================================================
# Known gaps — spec fields that should be rejected
# =========================================================================


class TestKnownGaps:
    def test_asking_rate_psf_rejected(self):
        """asking_rate_psf has no safe single-field alias (index has low/high)."""
        d, _ = _make_dispatcher()
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Availability",
                "aggregate": "avg",
                "aggregate_field": "asking_rate_psf",
            },
        })
        assert "error" in result

    def test_spec_availability_aggregation_pattern(self):
        """Spec §9 example: avg rent_low for Class A office, grouped by submarket.

        Uses property_class filter on Availability — must resolve to
        property_propertyclass.
        """
        d, backend = _make_dispatcher(
            aggregate_return={"groups": {"CBD": {"avg": 35.0}}}
        )
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Availability",
                "filters": {"property_class": "A"},
                "aggregate": "avg",
                "aggregate_field": "rent_low",
            },
        })
        assert "result" in result, f"Expected result, got: {result}"
        call_kwargs = backend.aggregate.call_args[1]
        assert call_kwargs["filters"]["property_propertyclass"] == "A"
        assert call_kwargs["aggregate_field"] == "rentlow"

    def test_availability_geography_filter_aliases(self):
        d, backend = _make_dispatcher(search_return=[])
        result = d.dispatch({
            "name": "search_records",
            "parameters": {
                "object_type": "Availability",
                "filters": {"market": "Dallas-Fort Worth", "submarket": "CBD"},
                "text_query": "office",
            },
        })
        assert "results" in result, f"Expected results, got: {result}"
        call_kwargs = backend.search.call_args[1]
        assert call_kwargs["filters"]["market_name"] == "Dallas-Fort Worth"
        assert call_kwargs["filters"]["submarket_name"] == "CBD"

    def test_broker_name_rejected(self):
        """broker_name is not indexed in POC scope."""
        d, _ = _make_dispatcher()
        result = d.dispatch({
            "name": "search_records",
            "parameters": {
                "object_type": "Lease",
                "filters": {"broker_name": "JLL"},
                "text_query": "test",
            },
        })
        assert "error" in result


# =========================================================================
# End-to-end round trips
# =========================================================================


class TestEndToEnd:
    def test_search_round_trip(self):
        d, backend = _make_dispatcher(search_return=[
            {"id": "a01", "dist": 0.95, "name": "Tower One", "city": "Dallas"},
            {"id": "a02", "dist": 0.87, "name": "Plaza Two", "city": "Houston"},
        ])
        result = d.dispatch({
            "name": "search_records",
            "parameters": {
                "object_type": "Property",
                "filters": {"property_class": "A", "city": "Dallas"},
                "text_query": "office tower",
                "limit": 5,
            },
        })
        assert "results" in result
        assert len(result["results"]) == 2
        assert result["results"][0]["name"] == "Tower One"
        # Verify the backend got resolved filters
        call_kwargs = backend.search.call_args[1]
        assert call_kwargs["filters"]["propertyclass"] == "A"
        assert call_kwargs["filters"]["city"] == "Dallas"
        assert call_kwargs["filters"]["object_type"] == "property"

    def test_aggregate_round_trip(self):
        d, backend = _make_dispatcher(
            aggregate_return={"groups": {"A": {"count": 10}, "B": {"count": 5}}}
        )
        result = d.dispatch({
            "name": "aggregate_records",
            "parameters": {
                "object_type": "Property",
                "aggregate": "count",
                "group_by": "property_class",
            },
        })
        assert "result" in result
        assert result["result"]["groups"]["A"]["count"] == 10
        call_kwargs = backend.aggregate.call_args[1]
        assert call_kwargs["group_by"] == "propertyclass"
