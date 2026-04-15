"""Tool dispatch module for AscendixIQ query pipeline (Task 1.1.1).

Translates Claude tool-call JSON (search_records, aggregate_records,
propose_edit) into
SearchBackend method calls.  Pure module — no network I/O.  Takes a
SearchBackend instance as an injected dependency so it can be unit-tested
with mocks.

The two-layer alias strategy resolves both:
  1. Auto-generated snake_case aliases from CamelCase field names
     (e.g. property_class → propertyclass)
  2. Curated semantic aliases from spec §9 vocabulary
     (e.g. leased_sf → size, start_date → termcommencementdate)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lib.search_backend import SearchBackend
from lib.write_proposal import (
    WriteProposalValidationError,
    normalize_propose_edit_input,
)

# ---------------------------------------------------------------------------
# Field-name utilities
# ---------------------------------------------------------------------------

def _clean_label(field_name: str) -> str:
    """Strip Salesforce namespace prefix and custom suffixes.

    Mirrors ``scripts/bulk_load.clean_label`` exactly.
    """
    cleaned = (
        field_name.replace("ascendix__", "")
        .replace("__Latitude__s", "Latitude")
        .replace("__Longitude__s", "Longitude")
        .replace("__c", "")
        .replace("__r", "")
    )
    if cleaned.endswith("Id") and cleaned != "Id":
        cleaned = cleaned[:-2]
    return cleaned


def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case.

    >>> _to_snake_case("PropertyClass")
    'property_class'
    >>> _to_snake_case("TotalBuildingArea")
    'total_building_area'
    >>> _to_snake_case("LeaseRatePerUOM")
    'lease_rate_per_uom'
    """
    # Insert _ before uppercase runs followed by lowercase, or between
    # lowercase/digit and uppercase.
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


# Operator suffixes recognised on filter keys.
_FILTER_SUFFIXES = ("_gte", "_lte", "_gt", "_lt", "_in", "_ne")


def _extract_base_field(key: str) -> str:
    """Strip a recognised operator suffix and return the base field name.

    >>> _extract_base_field("total_sf_gte")
    'total_sf'
    >>> _extract_base_field("city")
    'city'
    """
    for suffix in _FILTER_SUFFIXES:
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def _extract_suffix(key: str) -> str:
    """Return the operator suffix of *key*, or empty string."""
    for suffix in _FILTER_SUFFIXES:
        if key.endswith(suffix):
            return suffix
    return ""


# ---------------------------------------------------------------------------
# Curated semantic aliases  (spec §9 vocabulary → indexed attribute names)
# ---------------------------------------------------------------------------

SEMANTIC_ALIASES: dict[str, dict[str, str]] = {
    "property": {
        "record_type": "recordtype_name",
        "property_type": "propertysubtype",
        "property_subtype": "propertysubtype",
        "total_sf": "totalbuildingarea",
        "year_built": "yearbuilt",
        "zip": "postalcode",
        "address": "street",
        "building_status": "buildingstatus",
        "construction_type": "constructiontype",
        "land_area": "landarea",
        "postal_code": "postalcode",
        "owner_account_name": "ownerlandlord_name",
        "submarket": "submarket_name",
        "market": "market_name",
    },
    "lease": {
        "property_record_type": "property_recordtype_name",
        "leased_sf": "size",
        "rate_psf": "leaserateperuom",
        "lease_rate": "leaserateperuom",
        "average_rent": "averagerent",
        "start_date": "termcommencementdate",
        "end_date": "termexpirationdate",
        "lease_term_months": "termmonths",
        "term_months": "termmonths",
        "occupancy_date": "occupancydate",
        "lease_signed": "leasesigned",
        "lease_type": "leasetype",
        "unit_type": "unittype",
        "tenant_name": "tenant_name",
        "owner_account_name": "ownerlandlord_name",
        "property_type": "property_propertysubtype",
        "property_class": "property_propertyclass",
        "property_subtype": "property_propertysubtype",
        "property_total_sf": "property_totalbuildingarea",
        "city": "property_city",
        "state": "property_state",
    },
    "availability": {
        "property_record_type": "property_recordtype_name",
        "available_sf": "availablearea",
        # asking_rate_psf intentionally NOT aliased — spec has a single field
        # but the index stores a low/high range (rentlow / renthigh).  Aliasing
        # to either would silently distort aggregations.
        "asking_price": "askingprice",
        "available_date": "availablefrom",
        "availability_type": "usetype",
        "space_type": "usetype",
        "lease_type": "leasetype",
        "use_type": "usetype",
        "use_sub_type": "usesubtype",
        "max_contiguous": "maxcontiguousarea",
        "min_divisible": "mindivisiblearea",
        "lease_term_min": "leasetermmin",
        "lease_term_max": "leasetermmax",
        "rent_low": "rentlow",
        "rent_high": "renthigh",
        "property_type": "property_propertysubtype",
        "property_class": "property_propertyclass",
        "property_subtype": "property_propertysubtype",
        "property_total_sf": "property_totalbuildingarea",
        "city": "property_city",
        "state": "property_state",
        "market": "market_name",
        "submarket": "submarket_name",
        "region": "region_name",
    },
    "deal": {
        "deal_stage": "salesstage",
        "deal_value": "grossfeeamount",
        "gross_fee": "grossfeeamount",
        "close_date": "closedateestimated",
        "actual_close_date": "closedateactual",
        "deal_size": "size",
        "lease_rate": "leaserateperuom",
        "lease_term": "leasetermmonths",
        "client_name": "client_name",
        "buyer_name": "buyer_name",
        "seller_name": "seller_name",
        "tenant_name": "tenant_name",
        "property_name": "property_name",
        "property_city": "property_city",
        "property_state": "property_state",
        "city": "property_city",
        "state": "property_state",
    },
    "sale": {
        "sale_price": "saleprice",
        "price_psf": "salepriceperuom",
        "price_per_unit": "salepriceperunit",
        "cap_rate": "capratepercent",
        "listing_price": "listingprice",
        "listing_date": "listingdate",
        "sale_date": "saledate",
        "total_area": "totalarea",
        "noi": "netincome",
        "units": "numberunitsrooms",
        "property_name": "property_name",
        "property_city": "property_city",
        "property_state": "property_state",
        "city": "property_city",
        "state": "property_state",
        "street": "property_street",
        "zip": "property_postalcode",
        "postal_code": "property_postalcode",
        "total_units": "property_totalunits",
        "listing_broker": "listingbrokercompany_name",
        # NOTE: property_yearbuilt / property_yearrenovated are Text(255)
        # in Salesforce and are intentionally NOT advertised as filter
        # aliases. They remain indexed and appear in Sale result documents
        # for display, but range operators (_gte/_lte) on text storage
        # are either lexicographic or backend-defined and unsafe.
        # If a future task normalizes them to int at ingestion, add the
        # semantic aliases back here.
    },
    "inquiry": {
        "min_size": "areaminimum",
        "max_size": "areamaximum",
        "min_rent": "rentminimum",
        "max_rent": "rentmaximum",
        "min_price": "priceminimum",
        "max_price": "pricemaximum",
        "move_in_date": "requiredmoveindate",
        "property_name": "property_name",
        "property_city": "property_city",
        "property_state": "property_state",
        "city": "property_city",
        "state": "property_state",
        "broker_name": "brokercompany_name",
        "listing_name": "listing_name",
        "market": "market_name",
        "submarket": "submarket_name",
    },
    "listing": {
        "listing_date": "listingdate",
        "expiration_date": "listingexpiration",
        "asking_price": "askingprice",
        "vacant_area": "vacantarea",
        "property_name": "property_name",
        "property_city": "property_city",
        "city": "property_city",
        "listing_broker": "listingbrokercompany_name",
        "owner_name": "ownerlandlord_name",
        "market": "market_name",
        "submarket": "submarket_name",
    },
    "preference": {
        "min_size": "areaminimum",
        "max_size": "areamaximum",
        "min_rent": "rentminimum",
        "max_rent": "rentmaximum",
        "min_price": "priceminimum",
        "max_price": "pricemaximum",
        "move_in_date": "requiredmoveindate",
        "lease_expiration": "currentleaseexpirationdate",
        "sale_or_lease": "saleorlease",
        "account_name": "account_name",
        "contact_name": "contact_name",
        "market": "market_name",
        "submarket": "submarket_name",
    },
    "task": {
        "subject": "subject",
        "due_date": "activitydate",
        "who_name": "who_name",
        "what_name": "what_name",
        "account_name": "account_name",
    },
}
# NOTE: asking_rate_psf is intentionally absent from SEMANTIC_ALIASES.
# The spec uses it as a single field, but the index stores a low/high range
# (rentlow / renthigh).  The system prompt (task 1.2) must use rent_low /
# rent_high instead.  See spec §8 Availability document schema.

# ---------------------------------------------------------------------------
# Non-filterable field denylist
# ---------------------------------------------------------------------------
#
# Indexed field names that must NOT be used as search/aggregate/group_by
# filters, even when the registry exposes them via auto-generated aliases.
# Keyed by object type (lowercase). Applied at two layers:
#
#   1. Dispatcher (_resolve_field): rejects the filter before it reaches
#      the backend, covering every alias form that resolves to the denied
#      indexed name.
#   2. Prompt export (_collect_field_names in system_prompt): omits the
#      field from the advertised filter field list so the model is never
#      trained to try it in the first place.
#
# Fields are still indexed in the document (denorm_config controls that
# separately) and still appear in search result payloads for display.
# The denylist only blocks them as filter targets.
#
# Current entries:
#   sale.property_yearbuilt  — ascendix__YearBuilt__c is Text(255)
#
# (YearRenovated was dropped from the Sale denorm entirely to fit the
# Turbopuffer 256-attribute namespace cap, so it doesn't need a
# denylist entry.)
#
# When ingestion normalizes YearBuilt to int (future task), remove the
# entry and the generated `property_year_built` alias becomes safely
# filterable.
NON_FILTERABLE_FIELDS: dict[str, set[str]] = {
    "sale": {
        "property_yearbuilt",
    },
}


# ---------------------------------------------------------------------------
# Field registry
# ---------------------------------------------------------------------------

# Fields present on every document (written by bulk_load.build_document).
_PLATFORM_FILTERABLE = {"object_type", "text", "last_modified", "salesforce_org_id", "name"}
_RESULT_ONLY = {"id", "dist"}


@dataclass
class FieldSet:
    """Known field metadata for one object type."""

    filterable: set[str] = field(default_factory=set)
    """Field names valid in filters / aggregate_field / group_by."""

    result_fields: set[str] = field(default_factory=set)
    """Field names that may appear in search results (filterable + id)."""

    aliases: dict[str, str] = field(default_factory=dict)
    """Alias → indexed field name  (auto snake_case + curated semantic)."""


def build_field_registry(
    config: dict,
    semantic_aliases: dict[str, dict[str, str]] | None = None,
) -> dict[str, FieldSet]:
    """Build ``{object_type: FieldSet}`` from a parsed denorm config YAML.

    *config* is the dict returned by ``yaml.safe_load(open("denorm_config.yaml"))``.
    *semantic_aliases* is an optional per-object-type dict of curated aliases
    (default: :data:`SEMANTIC_ALIASES`).
    """
    if semantic_aliases is None:
        semantic_aliases = SEMANTIC_ALIASES

    registry: dict[str, FieldSet] = {}

    for raw_object_name, obj_cfg in config.items():
        obj_type = _clean_label(raw_object_name).lower()
        fs = FieldSet()
        aliases: dict[str, str] = {}

        # --- Direct fields (embed + metadata) ---
        for raw_field in obj_cfg.get("embed_fields", []) + obj_cfg.get("metadata_fields", []):
            # The YAML may have inline comments stored as tuples by some
            # generators, but our YAML uses plain strings.
            if isinstance(raw_field, (list, tuple)):
                raw_field = raw_field[0]
            indexed = _clean_label(raw_field).lower()
            fs.filterable.add(indexed)
            # Auto snake_case alias
            snake = _to_snake_case(_clean_label(raw_field))
            if snake != indexed:
                aliases[snake] = indexed

        # --- Parent fields ---
        for ref_field, parent_entry in obj_cfg.get("parents", {}).items():
            parent_fields = (
                parent_entry.get("fields", [])
                if isinstance(parent_entry, dict)
                else parent_entry
            )
            prefix = _clean_label(ref_field).lower()
            prefix_snake = _to_snake_case(_clean_label(ref_field))
            for pf in parent_fields:
                if isinstance(pf, (list, tuple)):
                    pf = pf[0]
                if "." in pf:
                    # Dotted parent field: flatten all parts
                    parts = pf.split(".")
                    pf_clean = "_".join(_clean_label(p).lower() for p in parts)
                else:
                    pf_clean = _clean_label(pf).lower()
                indexed = f"{prefix}_{pf_clean}"
                fs.filterable.add(indexed)
                # Auto snake_case alias for the parent field portion
                if "." in pf:
                    pf_snake = "_".join(_to_snake_case(_clean_label(p)) for p in pf.split("."))
                else:
                    pf_snake = _to_snake_case(_clean_label(pf))
                alias_key = f"{prefix}_{pf_snake}"
                if alias_key != indexed:
                    aliases[alias_key] = indexed
                snake_prefix_alias_key = f"{prefix_snake}_{pf_snake}"
                if snake_prefix_alias_key != indexed:
                    aliases[snake_prefix_alias_key] = indexed

        # --- Platform fields ---
        fs.filterable |= _PLATFORM_FILTERABLE

        # --- Result-only fields ---
        fs.result_fields = fs.filterable | _RESULT_ONLY

        # --- Merge semantic aliases (curated overrides auto on conflict) ---
        for alias_key, indexed in (semantic_aliases.get(obj_type, {})).items():
            aliases[alias_key] = indexed

        fs.aliases = aliases
        registry[obj_type] = fs

    return registry


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FieldValidationError(ValueError):
    """A field name is not valid for the given object type."""


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_SUPPORTED_TOOLS = frozenset({"search_records", "aggregate_records", "propose_edit"})
_SUPPORTED_AGGREGATES = frozenset({"count", "sum", "avg"})
_MAX_LIMIT = 50
_DEFAULT_LIMIT = 10


class ToolDispatcher:
    """Translate Claude tool-call dicts into SearchBackend method calls.

    Pure: no network I/O.  Takes *backend* as an injected dependency.

    Parameters
    ----------
    backend:
        A :class:`SearchBackend` instance (e.g. ``TurbopufferBackend``).
    namespace:
        Turbopuffer namespace (e.g. ``"org_00Ddl000003yx57EAA"``).
    field_registry:
        Output of :func:`build_field_registry`.
    """

    def __init__(
        self,
        backend: SearchBackend,
        namespace: str,
        field_registry: dict[str, FieldSet],
    ) -> None:
        self._backend = backend
        self._namespace = namespace
        self._registry = field_registry

    # -- public API --------------------------------------------------------

    def dispatch(self, tool_call: dict) -> dict:
        """Execute *tool_call* and return a response dict.

        Returns ``{"results": [...]}`` for search, ``{"result": {...}}``
        for aggregate, or ``{"error": "..."}`` on failure.
        """
        name = tool_call.get("name")
        params = tool_call.get("parameters") or tool_call.get("input") or {}

        if name not in _SUPPORTED_TOOLS:
            return {
                "error": f"Unknown tool '{name}'. "
                f"Supported: {sorted(_SUPPORTED_TOOLS)}"
            }

        try:
            if name == "search_records":
                return self._handle_search(params)
            elif name == "aggregate_records":
                return self._handle_aggregate(params)
            else:
                return self._handle_propose_edit(params)
        except FieldValidationError as exc:
            return {"error": str(exc)}
        except WriteProposalValidationError as exc:
            return {"error": str(exc)}
        except Exception as exc:
            return {"error": f"Tool execution failed: {exc}"}

    # -- field resolution --------------------------------------------------

    def _resolve_field(self, field_name: str, object_type: str) -> str:
        """Resolve *field_name* to the indexed attribute name.

        Checks (in order):
        1. Exact match in filterable set → candidate is *field_name*.
        2. Match in aliases dict → candidate is the mapped name.
        3. No match → raise :exc:`FieldValidationError`.

        The candidate is then checked against the per-object
        :data:`NON_FILTERABLE_FIELDS` denylist. A denylisted match
        raises :exc:`FieldValidationError` regardless of which alias
        form the caller used, so every path that lands on the same
        indexed attribute is blocked uniformly.
        """
        fs = self._registry[object_type]
        if field_name in fs.filterable:
            candidate = field_name
        elif field_name in fs.aliases:
            candidate = fs.aliases[field_name]
        else:
            valid = sorted(
                (fs.filterable | set(fs.aliases.keys()))
                - NON_FILTERABLE_FIELDS.get(object_type, set())
            )
            raise FieldValidationError(
                f"Invalid field '{field_name}' for object type '{object_type}'. "
                f"Valid fields: {valid}"
            )

        denylist = NON_FILTERABLE_FIELDS.get(object_type, set())
        if candidate in denylist:
            raise FieldValidationError(
                f"Field '{field_name}' (indexed as '{candidate}') is not available "
                f"as a filter on '{object_type}'. It is stored as text and cannot "
                f"be safely equality- or range-compared. The value is still "
                f"returned in search results for display."
            )
        return candidate

    def _resolve_filters(self, filters: dict, object_type: str) -> dict:
        """Resolve alias names and preserve operator suffixes."""
        resolved: dict[str, Any] = {}
        for key, value in filters.items():
            suffix = _extract_suffix(key)
            base = key[: -len(suffix)] if suffix else key
            indexed_base = self._resolve_field(base, object_type)
            resolved[indexed_base + suffix] = value
        return resolved

    # -- object type -------------------------------------------------------

    def _validate_object_type(self, raw: str) -> str:
        normalised = raw.lower()
        if normalised not in self._registry:
            valid = sorted(self._registry.keys())
            raise FieldValidationError(
                f"Unknown object_type '{raw}'. Valid types: {valid}"
            )
        return normalised

    # -- handlers ----------------------------------------------------------

    def _handle_search(self, params: dict) -> dict:
        raw_type = params.get("object_type")
        if not raw_type:
            raise FieldValidationError("'object_type' is required for search_records")
        object_type = self._validate_object_type(raw_type)

        # Resolve and merge filters
        user_filters = params.get("filters") or {}
        resolved = self._resolve_filters(user_filters, object_type)
        resolved["object_type"] = object_type

        text_query = params.get("text_query")
        if text_query is None:
            # Use the object type name as a broad BM25 scan.  Every
            # document's text field starts with "Property:", "Lease:", or
            # "Availability:", so this guarantees non-zero BM25 scores for
            # filter-only queries (a bare " " returns 0 results on
            # Turbopuffer).
            text_query = object_type.capitalize()

        limit = min(int(params.get("limit", _DEFAULT_LIMIT)), _MAX_LIMIT)

        results = self._backend.search(
            self._namespace,
            text_query=text_query,
            filters=resolved,
            top_k=limit,
            include_attributes=True,
        )
        return {"results": results}

    def _handle_aggregate(self, params: dict) -> dict:
        raw_type = params.get("object_type")
        if not raw_type:
            raise FieldValidationError("'object_type' is required for aggregate_records")
        object_type = self._validate_object_type(raw_type)

        aggregate = params.get("aggregate", "count")
        if aggregate not in _SUPPORTED_AGGREGATES:
            raise FieldValidationError(
                f"Unsupported aggregate '{aggregate}'. "
                f"Valid: {sorted(_SUPPORTED_AGGREGATES)}"
            )

        user_filters = params.get("filters") or {}
        resolved = self._resolve_filters(user_filters, object_type)
        resolved["object_type"] = object_type

        aggregate_field = params.get("aggregate_field")
        if aggregate_field:
            aggregate_field = self._resolve_field(aggregate_field, object_type)

        group_by = params.get("group_by")
        if group_by:
            group_by = self._resolve_field(group_by, object_type)

        sort_order = params.get("sort_order", "desc")
        top_n = params.get("top_n")

        result = self._backend.aggregate(
            self._namespace,
            filters=resolved,
            aggregate=aggregate,
            aggregate_field=aggregate_field,
            group_by=group_by,
        )

        # Post-process grouped results: sort and optionally truncate.
        if "groups" in result and result["groups"]:
            groups = result["groups"]
            agg_key = aggregate  # "count", "sum", or "avg"
            reverse = (sort_order != "asc")

            # Sort by aggregate value (desc or asc), then alphabetically by
            # group key for deterministic ordering when values tie.
            if reverse:
                sorted_items = sorted(
                    groups.items(),
                    key=lambda kv: (-kv[1].get(agg_key, 0), kv[0]),
                )
            else:
                sorted_items = sorted(
                    groups.items(),
                    key=lambda kv: (kv[1].get(agg_key, 0), kv[0]),
                )

            total_groups = len(sorted_items)

            truncated = False
            if top_n and top_n < total_groups:
                sorted_items = sorted_items[:top_n]
                truncated = True

            result["groups"] = dict(sorted_items)
            result["_sorted_by"] = agg_key
            result["_order"] = "desc" if reverse else "asc"
            result["_total_groups"] = total_groups
            result["_showing"] = len(sorted_items)
            result["_truncated"] = truncated

        return {"result": result}

    def _handle_propose_edit(self, params: dict) -> dict:
        """Validate and normalize a structured edit proposal."""
        proposal = normalize_propose_edit_input(params)
        return {"write_proposal": proposal}
