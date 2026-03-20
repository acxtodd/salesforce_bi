"""System prompt and tool definitions for the AscendixIQ query pipeline (Task 1.2).

Provides:
- ``SYSTEM_PROMPT`` — static system prompt string for Claude.
- ``TOOL_DEFINITIONS`` — Bedrock Converse API tool definition dicts.
- ``build_system_prompt(config)`` — generates a system prompt with actual field
  names derived from the parsed denorm_config.yaml.
- ``build_tool_definitions(config)`` — generates TOOL_DEFINITIONS dynamically
  from the parsed denorm_config.yaml.

The field names referenced in the prompt and tool descriptions are the alias
names accepted by ``lib.tool_dispatch.ToolDispatcher`` — i.e. the curated
semantic aliases (e.g. ``total_sf``, ``leased_sf``, ``rate_psf``) plus the
auto-generated snake_case aliases (e.g. ``property_class``).
"""

from __future__ import annotations

from datetime import date

from lib.tool_dispatch import SEMANTIC_ALIASES, _clean_label, _to_snake_case, build_field_registry

# ---------------------------------------------------------------------------
# CRE domain vocabulary (referenced in the system prompt)
# ---------------------------------------------------------------------------

_CRE_VOCABULARY = (
    "lease comp, NNN (triple net), gross lease, Class A/B/C, submarket, CBD, "
    "tenant rep, landlord rep, cap rate, PSF (per square foot), GLA, "
    "TI (tenant improvements), ROFR, LOI, asking rate, effective rate, "
    "direct/sublease availability"
)

# ---------------------------------------------------------------------------
# Field reference tables (for the prompt)
# ---------------------------------------------------------------------------

_PROPERTY_FIELDS = """\
  - name: record name / building name
  - city, state: location
  - property_class: building class (A, B, C)
  - property_type: property subtype (General, Business Park, Mixed Use, etc.) — NOT the primary type. Use text_query for "office"/"industrial"/"retail" searches.
  - total_sf: total building area in square feet
  - year_built: year the building was constructed
  - floors: number of floors
  - building_status: current status of the building
  - market: market name (e.g. "Dallas-Fort Worth")
  - submarket: submarket name (e.g. "CBD", "Uptown")
  - county, postal_code: additional location fields
  - occupancy: occupancy percentage
  - land_area: land area in square feet
  - construction_type: type of construction
  - tenancy: tenancy type
  - owner_account_name: owner/landlord account name"""

_LEASE_FIELDS = """\
  - name: lease record name
  - lease_type: type of lease (NNN, Gross, Modified Gross, etc.)
  - leased_sf: leased square footage
  - rate_psf: lease rate per square foot (per unit of measure)
  - average_rent: average rent amount
  - start_date: lease term commencement date
  - end_date: lease term expiration date
  - term_months: lease term in months
  - occupancy_date: occupancy date
  - lease_signed: date the lease was signed
  - unit_type: unit type
  - tenant_name: tenant account name
  - owner_account_name: owner/landlord account name
  - property_name: parent property name (denormalized)
  - property_city: parent property city (denormalized)
  - property_state: parent property state (denormalized)
  - property_class: parent property class (denormalized)
  - property_type: parent property subtype (denormalized) — subtypes, not primary type
  - property_total_sf: parent property total building area (denormalized)"""

_AVAILABILITY_FIELDS = """\
  - name: availability record name
  - use_type: space use type (Office, Retail, Industrial, etc.)
  - status: availability status
  - available_sf: available area in square feet
  - rent_low: asking rent low end (per SF)
  - rent_high: asking rent high end (per SF)
  - asking_price: asking sale price
  - available_date: date available from
  - max_contiguous: maximum contiguous area
  - min_divisible: minimum divisible area
  - lease_type: lease type for the space
  - lease_term_min: minimum lease term
  - lease_term_max: maximum lease term
  - market: availability market (native geography relationship)
  - submarket: availability submarket (native geography relationship)
  - region: availability region (native geography relationship)
  - property_name: parent property name (denormalized)
  - property_city: parent property city (denormalized)
  - property_state: parent property state (denormalized)
  - property_class: parent property class (denormalized)
  - property_type: parent property subtype (denormalized) — subtypes, not primary type
  - property_total_sf: parent property total building area (denormalized)"""

_ACCOUNT_FIELDS = """\
  - name: company/account name
  - type: account type
  - industry: industry classification
  - phone, website: primary company contact info
  - billing_city, billing_state, billing_postal_code: billing geography
  - annual_revenue, number_of_employees: company scale fields
  - parent_name: parent account name (denormalized)
  - billing_latitude, billing_longitude, shipping_latitude, shipping_longitude: geocoordinates"""

_CONTACT_FIELDS = """\
  - name: contact name
  - title: contact title
  - email, phone, mobile_phone: primary contact info
  - department: contact department
  - mailing_city, mailing_state, mailing_postal_code: mailing geography
  - account_name: parent account name (denormalized)
  - reports_to_name: manager/contact hierarchy name (denormalized)
  - mailing_latitude, mailing_longitude, other_latitude, other_longitude: geocoordinates"""

# Map of object type (lowercase) -> curated field description override.
# Objects not in this map get auto-generated field descriptions from the config.
_CURATED_FIELD_DESCRIPTIONS: dict[str, str] = {
    "property": _PROPERTY_FIELDS,
    "lease": _LEASE_FIELDS,
    "availability": _AVAILABILITY_FIELDS,
    "account": _ACCOUNT_FIELDS,
    "contact": _CONTACT_FIELDS,
}

# ---------------------------------------------------------------------------
# Few-shot examples
# ---------------------------------------------------------------------------

_FEW_SHOT_EXAMPLES = """\
### Example queries and tool calls

**1. Simple property search with filters**
User: "Show me Class A office buildings in Dallas over 100,000 SF"
Tool call:
  search_records(
    object_type="Property",
    filters={"city": "Dallas", "property_class": "A", "total_sf_gte": 100000},
    text_query="office"
  )

**2. Lease comp search (cross-object with property filters)**
User: "What lease comps exist in Dallas CBD for office space in the last 12 months over 10,000 SF?"
Tool call:
  search_records(
    object_type="Lease",
    filters={
      "property_city": "Dallas",
      "leased_sf_gte": 10000,
      "start_date_gte": "2025-03-15"
    },
    text_query="lease comp CBD",
    limit=20
  )
Note: Use denormalized fields (property_city, property_type) on the Lease object
to avoid a separate Property search.

**3. Availability search**
User: "Find available office spaces in Houston with rent under $30 PSF"
Tool call:
  search_records(
    object_type="Availability",
    filters={
      "property_city": "Houston",
      "use_type": "Office",
      "rent_high_lte": 30,
      "status": "Active"
    }
  )
Note: Use rent_low and rent_high for asking rate filters. There is no single asking-rate field.

**4. Aggregation (count by property class)**
User: "How many properties do we have by class in Dallas?"
Tool call:
  aggregate_records(
    object_type="Property",
    filters={"city": "Dallas"},
    aggregate="count",
    group_by="property_class"
  )

**5. Comparison (parallel aggregate calls)**
User: "Compare average asking rates for Class A properties in Dallas vs Houston"
Tool calls (parallel):
  aggregate_records(
    object_type="Availability",
    filters={"property_class": "A", "property_city": "Dallas"},
    aggregate="avg",
    aggregate_field="rent_high"
  )
  aggregate_records(
    object_type="Availability",
    filters={"property_class": "A", "property_city": "Houston"},
    aggregate="avg",
    aggregate_field="rent_high"
  )
Note: For comparison queries, always use parallel tool calls to minimize latency.

**6. Deal search**
User: "Show me deals closed this year with fee over $50,000"
Tool call:
  search_records(
    object_type="Deal",
    filters={"close_date_gte": "2026-01-01", "deal_value_gte": 50000},
    text_query="deal closed"
  )

**7. Inquiry search with cross-object filter**
User: "Find inquiries for properties in Houston"
Tool call:
  search_records(
    object_type="Inquiry",
    filters={"property_city": "Houston"}
  )\
"""

# ---------------------------------------------------------------------------
# Guidelines
# ---------------------------------------------------------------------------

def _build_guidelines(object_names: list[str] | None = None) -> str:
    """Build guidelines text, optionally with a dynamic object list.

    *object_names* is a list of capitalized object names (e.g. ["Property",
    "Lease", ...]). If *None*, defaults to the original 5 objects.
    """
    if object_names is None:
        obj_text = (
            "Property, Lease, Availability,\n"
            "   Account, and Contact are available."
        )
    else:
        obj_text = ", ".join(object_names) + " are available."

    return f"""\
### Guidelines

1. **Search first, clarify later.** When the user's question is answerable with
   a reasonable search (even if slightly ambiguous), call a tool immediately.
   Only ask for clarification when no reasonable search is possible. Prefer
   action over questions.

2. **Minimize turns.** Answer in as few tool-call rounds as possible. Emit all
   needed tool calls in a single turn using parallel calls. Avoid exploratory
   follow-up searches when the first result set is sufficient to answer the
   question. Present what you have rather than making additional calls for
   marginal detail.

3. **Use denormalized fields to avoid multi-step queries.** Lease and Availability
   records include parent Property fields (property_city, property_class,
   property_type, property_state, property_total_sf). Use these directly
   instead of first searching Property, then searching Lease.

4. **For comparison queries, use parallel tool calls.** When the user asks to
   compare two cities, two time periods, or two property classes, emit
   multiple tool calls simultaneously rather than sequentially.

5. **Always cite source records by name and ID.** When presenting results,
   reference the record name and Salesforce ID so the user can navigate to
   the source record.

6. **If no results found, say so clearly.** Do not fabricate or hallucinate
   data. If a search returns zero results, tell the user and suggest
   broadening their filters.

7. **Asking rates use rent_low and rent_high.** The index stores asking rent
   as a low/high range on Availability records. There is no single
   asking-rate field; always use rent_low and/or rent_high.
   Use rent_low and rent_high for filtering and aggregation.

8. **Filter operators.** Append a suffix to the field name for comparisons:
   - ``_gte``: greater than or equal
   - ``_lte``: less than or equal
   - ``_gt``: greater than
   - ``_lt``: less than
   - ``_in``: set membership (value is a list)
   - ``_ne``: not equal

9. **live_salesforce_query is NOT available in this POC.** Do not attempt to
   use the live_salesforce_query tool. All queries must go through
   search_records or aggregate_records.

10. **Object types for current scope.** {obj_text}

11. **Geography scope is object-specific.** Property supports market and
   submarket. Availability supports native market, submarket, and region when
   those relationships are populated in Salesforce. Lease does not currently
   support market or submarket filters; use property_city and property_state
   for lease geography.\
"""

# Static guidelines used by the static SYSTEM_PROMPT (5-object fallback).
_GUIDELINES = _build_guidelines()

# ---------------------------------------------------------------------------
# Static SYSTEM_PROMPT
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = f"""\
You are AscendixIQ, a CRE intelligence assistant answering questions about \
commercial real estate data in the user's Salesforce org.

Today's date is {date.today().isoformat()}. Use this for any relative date \
calculations (e.g. "next year", "last 12 months").

## CRE Domain Vocabulary

You understand the following commercial real estate terminology: {_CRE_VOCABULARY}.

## Available Tools

You have access to two tools:

- **search_records**: Search indexed CRE and CRM data (Property, Lease, Availability, Account, Contact). \
Use metadata filters for precise queries. Call multiple times in parallel for \
cross-object questions. Returns matching documents with relevance scores.

- **aggregate_records**: Count, sum, or average records matching criteria, \
optionally grouped by a field. Use for "how many," "total," "average," \
"breakdown" questions.

Note: live_salesforce_query is NOT available in this POC.

## Field Reference

### Property fields
{_PROPERTY_FIELDS}

### Lease fields (includes denormalized Property fields)
{_LEASE_FIELDS}

### Availability fields (includes denormalized Property fields)
{_AVAILABILITY_FIELDS}

### Account fields
{_ACCOUNT_FIELDS}

### Contact fields
{_CONTACT_FIELDS}

{_FEW_SHOT_EXAMPLES}

{_GUIDELINES}
"""

# ---------------------------------------------------------------------------
# Tool definitions (Bedrock Converse API format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "toolSpec": {
            "name": "search_records",
            "description": (
                "Search AscendixIQ for CRE records. Returns matching documents "
                "with relevance scores. Supports full-text BM25, and metadata "
                "filtering. Use multiple calls in parallel for cross-object queries.\n\n"
                "Object types: Property, Lease, Availability, Account, Contact.\n\n"
                "Filter field names (use semantic aliases):\n"
                "  Property: city, state, property_class, property_type, total_sf, "
                "year_built, floors, building_status, market, submarket, county, "
                "postal_code, occupancy, land_area, construction_type, tenancy, "
                "owner_account_name\n"
                "  Lease: lease_type, leased_sf, rate_psf, average_rent, start_date, "
                "end_date, term_months, occupancy_date, lease_signed, unit_type, "
                "tenant_name, owner_account_name, property_name, property_city, "
                "property_state, property_class, property_type, property_total_sf\n"
                "  Availability: use_type, status, available_sf, rent_low, rent_high, "
                "asking_price, available_date, max_contiguous, min_divisible, "
                "lease_type, lease_term_min, lease_term_max, market, submarket, "
                "region, property_name, property_city, property_state, "
                "property_class, property_type, property_total_sf\n"
                "  Account: name, type, industry, phone, website, billing_city, "
                "billing_state, billing_postal_code, annual_revenue, "
                "number_of_employees, parent_name\n"
                "  Contact: name, title, email, phone, mobile_phone, department, "
                "mailing_city, mailing_state, mailing_postal_code, account_name, "
                "reports_to_name\n\n"
                "Filter operators: append _gte, _lte, _gt, _lt, _in, _ne to field names."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "object_type": {
                            "type": "string",
                            "enum": ["Property", "Lease", "Availability", "Account", "Contact"],
                            "description": "The indexed object type to search.",
                        },
                        "filters": {
                            "type": "object",
                            "description": (
                                "Field-value filter pairs. Supports exact match, "
                                "comparison (field_gte, field_lte), and set membership "
                                "(field_in). Examples: "
                                '{"city": "Dallas", "property_class": "A", '
                                '"total_sf_gte": 100000}'
                            ),
                        },
                        "text_query": {
                            "type": "string",
                            "description": (
                                "Natural language search text for BM25 ranking. "
                                "Optional — omit for pure filter queries."
                            ),
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default 10, max 50).",
                        },
                    },
                    "required": ["object_type"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "aggregate_records",
            "description": (
                "Count, sum, or average CRE records matching criteria, optionally "
                "grouped by a field. Use for 'how many,' 'total,' 'average,' "
                "'breakdown' questions.\n\n"
                "Object types: Property, Lease, Availability, Account, Contact.\n\n"
                "Supported aggregates: count, sum, avg.\n"
                "For sum/avg, aggregate_field is required."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "object_type": {
                            "type": "string",
                            "enum": ["Property", "Lease", "Availability", "Account", "Contact"],
                            "description": "The indexed object type to aggregate.",
                        },
                        "filters": {
                            "type": "object",
                            "description": (
                                "Field-value filter pairs to narrow the aggregation. "
                                "Same syntax as search_records filters."
                            ),
                        },
                        "aggregate": {
                            "type": "string",
                            "enum": ["count", "sum", "avg"],
                            "description": "Aggregation function to apply (default: count).",
                        },
                        "aggregate_field": {
                            "type": "string",
                            "description": (
                                "Field to sum or average. Required when aggregate "
                                "is 'sum' or 'avg'. Examples: total_sf, leased_sf, "
                                "rate_psf, rent_low, rent_high."
                            ),
                        },
                        "group_by": {
                            "type": "string",
                            "description": (
                                "Field to group results by. Examples: property_class, "
                                "city, lease_type, use_type."
                            ),
                        },
                    },
                    "required": ["object_type"],
                }
            },
        }
    },
]


# ---------------------------------------------------------------------------
# Dynamic prompt builder
# ---------------------------------------------------------------------------

def _collect_field_names(config: dict) -> dict[str, list[str]]:
    """Extract field names per object type from denorm config.

    Returns a dict mapping object type (lowercase) to a sorted list of
    user-facing field names (aliases preferred over raw indexed names).
    """
    registry = build_field_registry(config)
    result: dict[str, list[str]] = {}

    for obj_type, fs in registry.items():
        # Build reverse alias map: indexed -> preferred alias
        reverse: dict[str, str] = {}
        for alias, indexed in fs.aliases.items():
            # Prefer shorter / more readable aliases
            if indexed not in reverse or len(alias) < len(reverse[indexed]):
                reverse[indexed] = alias

        names: set[str] = set()
        # Platform fields we suppress from the user-facing list
        _suppress = {"object_type", "text", "last_modified", "salesforce_org_id", "id", "dist"}
        for field_name in fs.filterable:
            if field_name in _suppress:
                continue
            # Use the alias if one exists, otherwise the raw name
            names.add(reverse.get(field_name, field_name))

        # Also include semantic aliases as valid names
        for alias in (SEMANTIC_ALIASES.get(obj_type, {})):
            names.add(alias)

        result[obj_type] = sorted(names)

    return result


def build_system_prompt(config: dict) -> str:
    """Build a system prompt with actual field names from *config*.

    *config* is the dict returned by ``yaml.safe_load(open("denorm_config.yaml"))``.
    The generated prompt includes the same structure as :data:`SYSTEM_PROMPT`
    but with a field reference section derived from the config rather than
    hard-coded.  Objects with curated field descriptions (Property, Lease,
    Availability, Account, Contact) use those; all other objects get
    auto-generated field descriptions from the field map.
    """
    field_map = _collect_field_names(config)

    # Build object name list for dynamic sections
    object_names = [k.capitalize() for k in sorted(field_map.keys())]
    object_list_str = ", ".join(object_names)

    field_sections: list[str] = []
    for obj_type in sorted(field_map.keys()):
        title = obj_type.capitalize()
        if obj_type in _CURATED_FIELD_DESCRIPTIONS:
            # Use the curated human-written description
            field_sections.append(f"### {title} fields\n{_CURATED_FIELD_DESCRIPTIONS[obj_type]}")
        else:
            # Auto-generate from field map
            fields = field_map[obj_type]
            field_list = ", ".join(fields)
            field_sections.append(f"### {title} fields\n  {field_list}")

    field_reference = "\n\n".join(field_sections)

    # Build dynamic guidelines with actual object list
    guidelines = _build_guidelines(object_names)

    return f"""\
You are AscendixIQ, a CRE intelligence assistant answering questions about \
commercial real estate data in the user's Salesforce org.

Today's date is {date.today().isoformat()}. Use this for any relative date \
calculations (e.g. "next year", "last 12 months").

## CRE Domain Vocabulary

You understand the following commercial real estate terminology: {_CRE_VOCABULARY}.

## Available Tools

You have access to two tools:

- **search_records**: Search indexed CRE and CRM data ({object_list_str}). \
Use metadata filters for precise queries. Call multiple times in parallel for \
cross-object questions. Returns matching documents with relevance scores.

- **aggregate_records**: Count, sum, or average records matching criteria, \
optionally grouped by a field. Use for "how many," "total," "average," \
"breakdown" questions.

Note: live_salesforce_query is NOT available in this POC.

## Field Reference

{field_reference}

{_FEW_SHOT_EXAMPLES}

{guidelines}
"""


def build_tool_definitions(config: dict) -> list[dict]:
    """Build TOOL_DEFINITIONS dynamically from *config*.

    *config* is the dict returned by ``yaml.safe_load(open("denorm_config.yaml"))``.
    Returns the same Bedrock Converse API tool definition structure as
    :data:`TOOL_DEFINITIONS`, but with the ``object_type`` enum and filter
    field descriptions derived from the config.

    Falls back to :data:`TOOL_DEFINITIONS` if *config* is empty.
    """
    field_map = _collect_field_names(config)
    if not field_map:
        return TOOL_DEFINITIONS

    # Build enum: capitalized, sorted
    object_enum = [k.capitalize() for k in sorted(field_map.keys())]

    # Build filter field description lines per object type
    filter_lines: list[str] = []
    for obj_type in sorted(field_map.keys()):
        title = obj_type.capitalize()
        fields = field_map[obj_type]
        filter_lines.append(f"  {title}: {', '.join(fields)}")
    filter_desc = "\n".join(filter_lines)

    object_list_str = ", ".join(object_enum)

    return [
        {
            "toolSpec": {
                "name": "search_records",
                "description": (
                    "Search AscendixIQ for CRE records. Returns matching documents "
                    "with relevance scores. Supports full-text BM25, and metadata "
                    "filtering. Use multiple calls in parallel for cross-object queries.\n\n"
                    f"Object types: {object_list_str}.\n\n"
                    "Filter field names (use semantic aliases):\n"
                    f"{filter_desc}\n\n"
                    "Filter operators: append _gte, _lte, _gt, _lt, _in, _ne to field names."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "object_type": {
                                "type": "string",
                                "enum": object_enum,
                                "description": "The indexed object type to search.",
                            },
                            "filters": {
                                "type": "object",
                                "description": (
                                    "Field-value filter pairs. Supports exact match, "
                                    "comparison (field_gte, field_lte), and set membership "
                                    "(field_in). Examples: "
                                    '{"city": "Dallas", "property_class": "A", '
                                    '"total_sf_gte": 100000}'
                                ),
                            },
                            "text_query": {
                                "type": "string",
                                "description": (
                                    "Natural language search text for BM25 ranking. "
                                    "Optional — omit for pure filter queries."
                                ),
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of results to return (default 10, max 50).",
                            },
                        },
                        "required": ["object_type"],
                    }
                },
            }
        },
        {
            "toolSpec": {
                "name": "aggregate_records",
                "description": (
                    "Count, sum, or average CRE records matching criteria, optionally "
                    "grouped by a field. Use for 'how many,' 'total,' 'average,' "
                    "'breakdown' questions.\n\n"
                    f"Object types: {object_list_str}.\n\n"
                    "Supported aggregates: count, sum, avg.\n"
                    "For sum/avg, aggregate_field is required."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "object_type": {
                                "type": "string",
                                "enum": object_enum,
                                "description": "The indexed object type to aggregate.",
                            },
                            "filters": {
                                "type": "object",
                                "description": (
                                    "Field-value filter pairs to narrow the aggregation. "
                                    "Same syntax as search_records filters."
                                ),
                            },
                            "aggregate": {
                                "type": "string",
                                "enum": ["count", "sum", "avg"],
                                "description": "Aggregation function to apply (default: count).",
                            },
                            "aggregate_field": {
                                "type": "string",
                                "description": (
                                    "Field to sum or average. Required when aggregate "
                                    "is 'sum' or 'avg'. Examples: total_sf, leased_sf, "
                                    "rate_psf, rent_low, rent_high."
                                ),
                            },
                            "group_by": {
                                "type": "string",
                                "description": (
                                    "Field to group results by. Examples: property_class, "
                                    "city, lease_type, use_type."
                                ),
                            },
                        },
                        "required": ["object_type"],
                    }
                },
            }
        },
    ]
