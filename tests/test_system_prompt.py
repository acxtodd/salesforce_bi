"""Tests for the system prompt module (Task 1.2 / Task 4.6.5.3).

Validates that SYSTEM_PROMPT, TOOL_DEFINITIONS, build_system_prompt(), and
build_tool_definitions() produce correct content for the AscendixIQ query
pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# Ensure project root is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.system_prompt import (
    SYSTEM_PROMPT,
    TOOL_DEFINITIONS,
    build_system_prompt,
    build_tool_definitions,
)
from scripts.export_agent_prompt import generate_export_document

# =========================================================================
# Test fixtures
# =========================================================================

# Minimal 3-object config (original test fixture)
SAMPLE_CONFIG = {
    "ascendix__Property__c": {
        "embed_fields": [
            "Name",
            "ascendix__City__c",
            "ascendix__State__c",
            "ascendix__PropertyClass__c",
            "ascendix__PropertySubType__c",
            "ascendix__Description__c",
            "ascendix__Street__c",
            "ascendix__BuildingStatus__c",
        ],
        "metadata_fields": [
            "ascendix__TotalBuildingArea__c",
            "ascendix__YearBuilt__c",
            "ascendix__Floors__c",
            "ascendix__PostalCode__c",
            "ascendix__County__c",
            "ascendix__Occupancy__c",
            "ascendix__LandArea__c",
            "ascendix__ConstructionType__c",
            "ascendix__Tenancy__c",
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
            "ascendix__Description__c",
            "ascendix__UnitType__c",
        ],
        "metadata_fields": [
            "ascendix__Size__c",
            "ascendix__LeaseRatePerUOM__c",
            "ascendix__AverageRent__c",
            "ascendix__TermCommencementDate__c",
            "ascendix__TermExpirationDate__c",
            "ascendix__TermMonths__c",
            "ascendix__OccupancyDate__c",
            "ascendix__LeaseSigned__c",
        ],
        "parents": {
            "ascendix__Property__c": [
                "Name",
                "ascendix__City__c",
                "ascendix__State__c",
                "ascendix__PropertyClass__c",
                "ascendix__PropertySubType__c",
                "ascendix__TotalBuildingArea__c",
            ],
            "ascendix__Tenant__c": ["Name"],
            "ascendix__OwnerLandlord__c": ["Name"],
        },
    },
    "ascendix__Availability__c": {
        "embed_fields": [
            "Name",
            "ascendix__UseType__c",
            "ascendix__UseSubType__c",
            "ascendix__Status__c",
            "ascendix__SpaceDescription__c",
            "ascendix__LeaseType__c",
        ],
        "metadata_fields": [
            "ascendix__AvailableArea__c",
            "ascendix__RentLow__c",
            "ascendix__RentHigh__c",
            "ascendix__AskingPrice__c",
            "ascendix__AvailableFrom__c",
            "ascendix__MaxContiguousArea__c",
            "ascendix__MinDivisibleArea__c",
            "ascendix__LeaseTermMin__c",
            "ascendix__LeaseTermMax__c",
        ],
        "parents": {
            "ascendix__Property__c": [
                "Name",
                "ascendix__City__c",
                "ascendix__State__c",
                "ascendix__PropertyClass__c",
                "ascendix__PropertySubType__c",
                "ascendix__TotalBuildingArea__c",
            ],
        },
    },
}


# 11-object config for dynamic builder tests
SAMPLE_CONFIG_11 = {
    **SAMPLE_CONFIG,
    "Account": {
        "embed_fields": ["Name", "Type", "Industry", "Phone"],
        "metadata_fields": ["AnnualRevenue", "NumberOfEmployees", "BillingCity", "BillingState"],
        "parents": {"ParentId": ["Name"]},
    },
    "Contact": {
        "embed_fields": ["Name", "Title", "Email", "Phone", "Department"],
        "metadata_fields": ["MailingCity", "MailingState", "MailingPostalCode"],
        "parents": {
            "AccountId": ["Name"],
            "ReportsToId": ["Name"],
        },
    },
    "ascendix__Deal__c": {
        "embed_fields": ["Name", "ascendix__TransactionType__c", "ascendix__SalesStage__c"],
        "metadata_fields": [
            "ascendix__GrossFeeAmount__c",
            "ascendix__CloseDateEstimated__c",
        ],
        "parents": {
            "ascendix__Client__c": ["Name"],
            "ascendix__Buyer__c": ["Name"],
            "ascendix__Seller__c": ["Name"],
            "ascendix__Tenant__c": ["Name"],
            "ascendix__Property__c": ["Name", "ascendix__City__c", "ascendix__State__c"],
        },
    },
    "ascendix__Sale__c": {
        "embed_fields": ["Name"],
        "metadata_fields": [
            "ascendix__SalePrice__c",
            "ascendix__SalePricePerUOM__c",
            "ascendix__CapRatePercent__c",
            "ascendix__ListingPrice__c",
            "ascendix__ListingDate__c",
            "ascendix__TotalArea__c",
            "ascendix__NetIncome__c",
        ],
        "parents": {
            "ascendix__Property__c": ["Name", "ascendix__City__c"],
        },
    },
    "ascendix__Inquiry__c": {
        "embed_fields": ["Name"],
        "metadata_fields": [],
        "parents": {
            "ascendix__Property__c": ["Name", "ascendix__City__c", "ascendix__State__c"],
            "ascendix__BrokerCompany__c": ["Name"],
            "ascendix__Listing__c": ["Name"],
        },
    },
    "ascendix__Listing__c": {
        "embed_fields": ["Name"],
        "metadata_fields": [],
        "parents": {
            "ascendix__Property__c": ["Name", "ascendix__City__c"],
            "ascendix__ListingBrokerCompany__c": ["Name"],
            "ascendix__OwnerLandlord__c": ["Name"],
        },
    },
    "ascendix__Preference__c": {
        "embed_fields": ["Name"],
        "metadata_fields": [],
        "parents": {
            "ascendix__Account__c": ["Name"],
            "ascendix__Contact__c": ["Name"],
        },
    },
    "Task": {
        "embed_fields": ["Subject"],
        "metadata_fields": [],
        "parents": {
            "WhoId": ["Name"],
            "WhatId": ["Name"],
        },
    },
}


# =========================================================================
# 1. SYSTEM_PROMPT basic content checks
# =========================================================================


class TestSystemPrompt:
    """Verify the static SYSTEM_PROMPT string."""

    def test_is_nonempty_string(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 100

    def test_contains_ascendixiq(self):
        assert "AscendixIQ" in SYSTEM_PROMPT

    def test_contains_cre(self):
        assert "CRE" in SYSTEM_PROMPT

    def test_contains_commercial_real_estate(self):
        assert "commercial real estate" in SYSTEM_PROMPT

    def test_contains_cre_vocabulary(self):
        """System prompt must include CRE domain vocabulary."""
        for term in [
            "lease comp",
            "NNN",
            "triple net",
            "gross lease",
            "Class A/B/C",
            "submarket",
            "CBD",
            "cap rate",
            "PSF",
            "per square foot",
            "GLA",
            "TI",
            "tenant improvements",
            "ROFR",
            "LOI",
            "asking rate",
            "effective rate",
            "direct/sublease",
        ]:
            assert term in SYSTEM_PROMPT, f"Missing CRE vocabulary term: {term}"

    def test_does_not_mention_asking_rate_psf(self):
        """System prompt must NOT use asking_rate_psf — use rent_low/rent_high instead."""
        assert "asking_rate_psf" not in SYSTEM_PROMPT

    def test_mentions_rent_low(self):
        assert "rent_low" in SYSTEM_PROMPT

    def test_mentions_rent_high(self):
        assert "rent_high" in SYSTEM_PROMPT

    def test_mentions_parallel_tool_calls(self):
        assert "parallel" in SYSTEM_PROMPT.lower()

    def test_live_salesforce_query_not_available(self):
        """live_salesforce_query must be noted as NOT available in POC."""
        assert "live_salesforce_query" in SYSTEM_PROMPT
        assert "NOT available" in SYSTEM_PROMPT

    def test_has_few_shot_examples(self):
        """System prompt must contain few-shot examples."""
        assert "Example queries" in SYSTEM_PROMPT or "Example" in SYSTEM_PROMPT
        # Check for at least the key example patterns
        assert "search_records" in SYSTEM_PROMPT
        assert "aggregate_records" in SYSTEM_PROMPT

    def test_has_guidelines(self):
        assert "Guidelines" in SYSTEM_PROMPT
        assert "<guidelines>" in SYSTEM_PROMPT
        assert "<field_reference>" in SYSTEM_PROMPT
        assert "<examples>" in SYSTEM_PROMPT

    def test_mentions_denormalized_fields(self):
        assert "denormalized" in SYSTEM_PROMPT.lower() or "denorm" in SYSTEM_PROMPT.lower()

    def test_mentions_write_proposals(self):
        assert "propose_edit" in SYSTEM_PROMPT
        assert "Supported writable objects" in SYSTEM_PROMPT
        assert "Confirm the target record" in SYSTEM_PROMPT

    def test_mentions_cite_records(self):
        assert "cite" in SYSTEM_PROMPT.lower()

    def test_mentions_geography_scope(self):
        assert "Geography scope varies by object" in SYSTEM_PROMPT
        assert "market" in SYSTEM_PROMPT.lower()
        assert "property_city" in SYSTEM_PROMPT

    def test_mentions_grouped_ranking_guard(self):
        assert "Do not fabricate grouped rankings" in SYSTEM_PROMPT
        assert "leaderboard" in SYSTEM_PROMPT
        assert "grouped aggregate" in SYSTEM_PROMPT
        assert "CLARIFY markers (defined above)" in SYSTEM_PROMPT

    def test_mentions_clarify_spec_and_error_handling(self):
        assert "Clickable option format (CLARIFY markers)" in SYSTEM_PROMPT
        assert "If a tool returns an error or unexpected result" in SYSTEM_PROMPT

    def test_mentions_interpretation_footer(self):
        assert "If interpretation materially affects correctness" in SYSTEM_PROMPT
        assert "Interpreted as:" in SYSTEM_PROMPT
        assert "Try next:" in SYSTEM_PROMPT

    def test_has_ambiguous_leaderboard_example(self):
        assert "Name the top ten brokers in our system by deal size" in SYSTEM_PROMPT
        assert "[CLARIFY:" in SYSTEM_PROMPT

    def test_has_deal_few_shot_example(self):
        """Static prompt includes the Deal few-shot example."""
        assert "Deal" in SYSTEM_PROMPT
        assert "deal_value_gte" in SYSTEM_PROMPT or "deal closed" in SYSTEM_PROMPT

    def test_has_prompt_quality_examples(self):
        assert "Note: Dates in examples below are illustrative." in SYSTEM_PROMPT
        assert "Anti-pattern examples - do NOT do these" in SYSTEM_PROMPT
        assert "unnecessary multi-step when denormalized fields exist" in SYSTEM_PROMPT
        assert "using text_query as a match-everything hack" in SYSTEM_PROMPT

    def test_clarify_spec_appears_once(self):
        assert SYSTEM_PROMPT.count("Clickable option format (CLARIFY markers)") == 1

    def test_removes_standalone_asking_rates_guideline(self):
        assert "Asking rates use rent_low and rent_high" not in SYSTEM_PROMPT

    def test_has_inquiry_few_shot_example(self):
        """Static prompt includes the Inquiry few-shot example."""
        assert "Inquiry" in SYSTEM_PROMPT

    def test_has_property_market_few_shot_example(self):
        """Static prompt includes an explicit Property market-filter example."""
        assert "Dallas-Fort Worth market" in SYSTEM_PROMPT
        assert 'filters={"market": "Dallas-Fort Worth"}' in SYSTEM_PROMPT

    def test_preserves_market_geography_grain(self):
        """Prompt tells the model not to silently replace market with city."""
        assert "Preserve the user's geography grain" in SYSTEM_PROMPT
        assert "use market/submarket filters" in SYSTEM_PROMPT


# =========================================================================
# 2. TOOL_DEFINITIONS structure
# =========================================================================


class TestToolDefinitions:
    """Verify TOOL_DEFINITIONS structure and content."""

    def test_is_list_of_two(self):
        assert isinstance(TOOL_DEFINITIONS, list)
        assert len(TOOL_DEFINITIONS) == 3

    def test_tool_names(self):
        names = {d["toolSpec"]["name"] for d in TOOL_DEFINITIONS}
        assert names == {"search_records", "aggregate_records", "propose_edit"}

    def test_bedrock_converse_structure(self):
        """Each tool must follow Bedrock Converse API format."""
        for tool in TOOL_DEFINITIONS:
            assert "toolSpec" in tool
            spec = tool["toolSpec"]
            assert "name" in spec
            assert "description" in spec
            assert "inputSchema" in spec
            assert "json" in spec["inputSchema"]
            schema = spec["inputSchema"]["json"]
            assert schema["type"] == "object"
            assert "properties" in schema
            assert "required" in schema

    def test_search_records_object_types(self):
        """search_records must list the original 5 demo object types."""
        search_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "search_records"
        )
        schema = search_tool["toolSpec"]["inputSchema"]["json"]
        enum = schema["properties"]["object_type"]["enum"]
        assert "Property" in enum
        assert "Lease" in enum
        assert "Availability" in enum
        assert "Account" in enum
        assert "Contact" in enum

    def test_search_records_has_filters(self):
        search_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "search_records"
        )
        schema = search_tool["toolSpec"]["inputSchema"]["json"]
        assert "filters" in schema["properties"]

    def test_search_records_has_text_query(self):
        search_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "search_records"
        )
        schema = search_tool["toolSpec"]["inputSchema"]["json"]
        assert "text_query" in schema["properties"]

    def test_search_records_has_limit(self):
        search_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "search_records"
        )
        schema = search_tool["toolSpec"]["inputSchema"]["json"]
        assert "limit" in schema["properties"]

    def test_aggregate_records_object_types(self):
        """aggregate_records must list the original 5 demo object types."""
        agg_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "aggregate_records"
        )
        schema = agg_tool["toolSpec"]["inputSchema"]["json"]
        enum = schema["properties"]["object_type"]["enum"]
        assert "Property" in enum
        assert "Lease" in enum
        assert "Availability" in enum
        assert "Account" in enum
        assert "Contact" in enum

    def test_aggregate_records_valid_aggregates(self):
        """aggregate_records must list count, sum, avg."""
        agg_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "aggregate_records"
        )
        schema = agg_tool["toolSpec"]["inputSchema"]["json"]
        enum = schema["properties"]["aggregate"]["enum"]
        assert set(enum) == {"count", "sum", "avg"}

    def test_aggregate_records_has_group_by(self):
        agg_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "aggregate_records"
        )
        schema = agg_tool["toolSpec"]["inputSchema"]["json"]
        assert "group_by" in schema["properties"]

    def test_aggregate_records_has_aggregate_field(self):
        agg_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "aggregate_records"
        )
        schema = agg_tool["toolSpec"]["inputSchema"]["json"]
        assert "aggregate_field" in schema["properties"]

    def test_tool_descriptions_do_not_mention_asking_rate_psf(self):
        """Tool descriptions must not reference asking_rate_psf."""
        for tool in TOOL_DEFINITIONS:
            desc = tool["toolSpec"]["description"]
            assert "asking_rate_psf" not in desc

    def test_tool_descriptions_mention_rent_low_rent_high(self):
        """At least one tool description should reference rent_low/rent_high."""
        all_descs = " ".join(d["toolSpec"]["description"] for d in TOOL_DEFINITIONS)
        assert "rent_low" in all_descs
        assert "rent_high" in all_descs

    def test_no_live_salesforce_query_tool(self):
        """live_salesforce_query must NOT be in tool definitions for POC."""
        names = {d["toolSpec"]["name"] for d in TOOL_DEFINITIONS}
        assert "live_salesforce_query" not in names

    def test_propose_edit_object_types(self):
        propose_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "propose_edit"
        )
        schema = propose_tool["toolSpec"]["inputSchema"]["json"]
        enum = schema["properties"]["object_type"]["enum"]
        assert enum == ["Account", "Contact", "Task"]

    def test_propose_edit_has_fields_array(self):
        propose_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "propose_edit"
        )
        schema = propose_tool["toolSpec"]["inputSchema"]["json"]
        assert "fields" in schema["properties"]
        assert schema["properties"]["fields"]["type"] == "array"
        assert schema["properties"]["fields"]["minItems"] == 1

    def test_propose_edit_mentions_minimal_writable_changes(self):
        propose_tool = next(
            d for d in TOOL_DEFINITIONS if d["toolSpec"]["name"] == "propose_edit"
        )
        desc = propose_tool["toolSpec"]["description"]
        assert "minimal" in desc.lower()
        assert "writable fields" in desc.lower()


# =========================================================================
# 3. build_system_prompt()
# =========================================================================


class TestBuildSystemPrompt:
    """Verify the dynamic prompt builder."""

    def test_returns_string(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert isinstance(result, str)
        assert len(result) > 100

    def test_contains_key_phrases(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "AscendixIQ" in result
        assert "CRE" in result
        assert "commercial real estate" in result

    def test_includes_property_fields(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "city" in result
        assert "state" in result
        assert "property_class" in result

    def test_includes_lease_fields(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "leased_sf" in result or "size" in result
        assert "rate_psf" in result or "leaserateperuom" in result
        assert "start_date" in result or "termcommencementdate" in result

    def test_includes_availability_fields(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "available_sf" in result or "availablearea" in result
        assert "rent_low" in result
        assert "rent_high" in result

    def test_mentions_account_and_contact_scope(self):
        """Account and Contact appear when config includes them."""
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert "Account" in result
        assert "Contact" in result

    def test_does_not_mention_asking_rate_psf(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "asking_rate_psf" not in result

    def test_includes_few_shot_examples(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "search_records" in result
        assert "aggregate_records" in result
        assert "parallel" in result.lower()

    def test_includes_guidelines(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "Guidelines" in result
        assert "<guidelines>" in result
        assert "<field_reference>" in result
        assert "<examples>" in result
        assert "denormalized" in result.lower() or "denorm" in result.lower()

    def test_includes_market_grain_guidance(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "Preserve the user's geography grain" in result
        assert 'filters={"market": "Dallas-Fort Worth"}' in result

    def test_includes_grouped_ranking_guard(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert "Do not fabricate grouped rankings" in result
        assert "leaderboard" in result
        assert "gross deal value, gross fee, or square footage" in result

    def test_includes_interpretation_footer_guidance(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert "If interpretation materially affects correctness" in result
        assert "Interpreted as:" in result
        assert "Limitation:" in result

    def test_live_salesforce_query_not_available(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "NOT available" in result

    def test_includes_write_proposal_guidance(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert "propose_edit" in result
        assert "Supported writable objects" in result
        assert "Account, Contact, Task" in result
        assert "never fabricate" in result

    def test_includes_prompt_quality_sections(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert "Clickable option format (CLARIFY markers)" in result
        assert "Note: Dates in examples below are illustrative." in result
        assert "Anti-pattern examples - do NOT do these" in result
        assert "If a tool returns an error or unexpected result" in result

    def test_includes_cre_vocabulary(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "lease comp" in result
        assert "NNN" in result
        assert "cap rate" in result

    def test_with_real_denorm_config(self):
        """If denorm_config.yaml exists, build_system_prompt should work with it."""
        config_path = Path(__file__).resolve().parent.parent / "denorm_config.yaml"
        if not config_path.exists():
            pytest.skip("denorm_config.yaml not found")

        with open(config_path) as f:
            config = yaml.safe_load(f)

        result = build_system_prompt(config)
        assert isinstance(result, str)
        assert "AscendixIQ" in result
        # Verify fields from the real config show up
        assert "property_class" in result
        assert "rent_low" in result
        assert "rent_high" in result

    def test_dynamic_builder_includes_all_objects(self):
        """build_system_prompt with 11-object config includes all object types."""
        result = build_system_prompt(SAMPLE_CONFIG_11)
        # All 11 object types should appear in the field reference
        for obj_type in (
            "Account", "Availability", "Contact", "Deal", "Inquiry",
            "Lease", "Listing", "Preference", "Property", "Sale", "Task",
        ):
            assert f"### {obj_type} fields" in result, (
                f"Missing field section for {obj_type}"
            )
        # The Available Tools section should list all objects
        assert "Deal" in result
        assert "Sale" in result
        assert "Inquiry" in result
        assert "Listing" in result
        assert "Preference" in result
        assert "Task" in result

    def test_dynamic_guideline_10_lists_all_objects(self):
        """Guideline 10 in the dynamic prompt lists all 11 object types."""
        result = build_system_prompt(SAMPLE_CONFIG_11)
        # Guideline 10 should mention all object types as available
        assert "Deal" in result
        assert "Inquiry" in result
        assert "are available" in result
        assert "propose_edit" in result

    def test_curated_descriptions_used_for_original_objects(self):
        """Property/Lease/Availability/Account/Contact use curated field descriptions."""
        result = build_system_prompt(SAMPLE_CONFIG_11)
        # Check that a curated description phrase is present (from _PROPERTY_FIELDS)
        assert "record name / building name" in result
        # Check that a curated lease description is present
        assert "lease rate per square foot" in result

    def test_prompt_quality_scaffold_is_present(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert "reason about object selection before calling tools" in result
        assert "(a) What entity is the user asking about?" in result
        assert "(b) What action do they want?" in result
        assert "(c) Which object's fields best match the intent?" in result

    def test_prompt_quality_sections_are_wrapped_once(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert result.count("<field_reference>") == 1
        assert result.count("<examples>") == 1
        assert result.count("<guidelines>") == 1

    def test_prompt_quality_clarify_spec_appears_once(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert result.count("Clickable option format (CLARIFY markers)") == 1

    def test_prompt_quality_removes_standalone_asking_rates_guideline(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert "Asking rates use rent_low and rent_high" not in result


# =========================================================================
# 4. build_tool_definitions()
# =========================================================================


class TestBuildToolDefinitions:
    """Verify the dynamic tool definition builder."""

    def test_build_tool_definitions_enum(self):
        """build_tool_definitions returns correct object_type enum for 11-object config."""
        tools = build_tool_definitions(SAMPLE_CONFIG_11)
        search_tool = next(t for t in tools if t["toolSpec"]["name"] == "search_records")
        enum = search_tool["toolSpec"]["inputSchema"]["json"]["properties"]["object_type"]["enum"]
        expected = sorted([
            "Account", "Availability", "Contact", "Deal", "Inquiry",
            "Lease", "Listing", "Preference", "Property", "Sale", "Task",
        ])
        assert enum == expected

    def test_build_tool_definitions_aggregate_enum(self):
        """aggregate_records also gets the full enum."""
        tools = build_tool_definitions(SAMPLE_CONFIG_11)
        agg_tool = next(t for t in tools if t["toolSpec"]["name"] == "aggregate_records")
        enum = agg_tool["toolSpec"]["inputSchema"]["json"]["properties"]["object_type"]["enum"]
        assert "Deal" in enum
        assert "Sale" in enum
        assert "Inquiry" in enum

    def test_build_tool_definitions_structure(self):
        """Dynamic tool definitions follow Bedrock Converse API format."""
        tools = build_tool_definitions(SAMPLE_CONFIG_11)
        assert isinstance(tools, list)
        assert len(tools) == 3
        for tool in tools:
            assert "toolSpec" in tool
            spec = tool["toolSpec"]
            assert "name" in spec
            assert "description" in spec
            assert "inputSchema" in spec
            schema = spec["inputSchema"]["json"]
            assert schema["type"] == "object"

    def test_build_tool_definitions_include_propose_edit(self):
        tools = build_tool_definitions(SAMPLE_CONFIG_11)
        names = {t["toolSpec"]["name"] for t in tools}
        assert "propose_edit" in names

        propose_tool = next(t for t in tools if t["toolSpec"]["name"] == "propose_edit")
        schema = propose_tool["toolSpec"]["inputSchema"]["json"]
        assert schema["properties"]["object_type"]["enum"] == ["Account", "Contact", "Task"]
        assert "properties" in schema
        assert "required" in schema
        assert "object_type" in schema["required"]

    def test_build_tool_definitions_description_includes_all_objects(self):
        """Tool descriptions mention all 11 object types."""
        tools = build_tool_definitions(SAMPLE_CONFIG_11)
        search_desc = next(
            t for t in tools if t["toolSpec"]["name"] == "search_records"
        )["toolSpec"]["description"]
        for obj in ("Deal", "Sale", "Inquiry", "Listing", "Preference", "Task"):
            assert obj in search_desc, f"Missing {obj} in search description"

    def test_build_tool_definitions_filter_fields_per_object(self):
        """Dynamic tool descriptions include filter fields for each object type."""
        tools = build_tool_definitions(SAMPLE_CONFIG_11)
        search_desc = next(
            t for t in tools if t["toolSpec"]["name"] == "search_records"
        )["toolSpec"]["description"]
        # Deal should have its semantic alias fields listed
        assert "Deal:" in search_desc
        assert "Sale:" in search_desc

    def test_build_tool_definitions_empty_config_fallback(self):
        """Empty config falls back to static TOOL_DEFINITIONS."""
        tools = build_tool_definitions({})
        assert tools is TOOL_DEFINITIONS

    def test_build_tool_definitions_3_object_config(self):
        """3-object config produces correct enum."""
        tools = build_tool_definitions(SAMPLE_CONFIG)
        search_tool = next(t for t in tools if t["toolSpec"]["name"] == "search_records")
        enum = search_tool["toolSpec"]["inputSchema"]["json"]["properties"]["object_type"]["enum"]
        assert enum == ["Availability", "Lease", "Property"]


# =========================================================================
# 5. Leaderboard tool params (Task 4.13e)
# =========================================================================


class TestLeaderboardToolParams:
    """Verify sort_order and top_n exist in aggregate_records definitions."""

    def _get_agg_props(self, tools):
        agg = next(t for t in tools if t["toolSpec"]["name"] == "aggregate_records")
        return agg["toolSpec"]["inputSchema"]["json"]["properties"]

    def test_static_has_sort_order(self):
        props = self._get_agg_props(TOOL_DEFINITIONS)
        assert "sort_order" in props
        assert props["sort_order"]["enum"] == ["desc", "asc"]

    def test_static_has_top_n(self):
        props = self._get_agg_props(TOOL_DEFINITIONS)
        assert "top_n" in props
        assert props["top_n"]["type"] == "integer"

    def test_dynamic_has_sort_order(self):
        tools = build_tool_definitions(SAMPLE_CONFIG_11)
        props = self._get_agg_props(tools)
        assert "sort_order" in props

    def test_dynamic_has_top_n(self):
        tools = build_tool_definitions(SAMPLE_CONFIG_11)
        props = self._get_agg_props(tools)
        assert "top_n" in props

    def test_guideline_6_in_static_prompt(self):
        assert "Do not fabricate grouped rankings" in SYSTEM_PROMPT
        assert "sort_order" in SYSTEM_PROMPT

    def test_guideline_6_in_dynamic_prompt(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert "sort_order" in result
        assert "top_n" in result

    def test_clarify_marker_format_in_static_prompt(self):
        """The [CLARIFY:label|query] marker format must be documented in the prompt."""
        assert "[CLARIFY:" in SYSTEM_PROMPT
        assert "full self-contained query text" in SYSTEM_PROMPT
        assert "CLARIFY markers (defined above)" in SYSTEM_PROMPT

    def test_clarify_marker_format_in_dynamic_prompt(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert "[CLARIFY:" in result
        assert "CLARIFY markers (defined above)" in result


# =========================================================================
# 6. Help-response guideline (Task 4.12.4)
# =========================================================================


class TestHelpResponseGuideline:
    """Verify guideline 18 (help/onboarding) exists in prompts."""

    def test_static_prompt_has_help_guidance(self):
        assert "help, capability, or onboarding questions" in SYSTEM_PROMPT

    def test_dynamic_prompt_has_help_guidance(self):
        result = build_system_prompt(SAMPLE_CONFIG_11)
        assert "help, capability, or onboarding questions" in result

    def test_guideline_discourages_capability_dumps(self):
        assert "Do NOT enumerate every object type" in SYSTEM_PROMPT
        assert "Do NOT call any tools for pure" in SYSTEM_PROMPT


# =========================================================================
# 7. Prompt export regeneration
# =========================================================================


class TestPromptExport:
    """Verify the export script renders the same prompt surface deterministically."""

    def test_export_document_summary_counts(self):
        document, stats = generate_export_document(SAMPLE_CONFIG_11)
        assert document.startswith("<!-- Auto-generated")
        assert "SYSTEM PROMPT" in document
        assert "TOOL DEFINITIONS" in document
        assert stats.object_types == [
            "Account",
            "Availability",
            "Contact",
            "Deal",
            "Inquiry",
            "Lease",
            "Listing",
            "Preference",
            "Property",
            "Sale",
            "Task",
        ]
        assert stats.tool_names == ["search_records", "aggregate_records", "propose_edit"]
        assert stats.guideline_count == 20
        assert "Tool definitions: 3 tools (search_records, aggregate_records, propose_edit)" in document
        assert "Guidelines: 20" in document
