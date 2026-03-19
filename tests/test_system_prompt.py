"""Tests for the system prompt module (Task 1.2).

Validates that SYSTEM_PROMPT, TOOL_DEFINITIONS, and build_system_prompt()
produce correct content for the AscendixIQ query pipeline.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# Ensure project root is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.system_prompt import SYSTEM_PROMPT, TOOL_DEFINITIONS, build_system_prompt

# =========================================================================
# Test fixtures
# =========================================================================

# Minimal config that mirrors the structure of denorm_config.yaml
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

    def test_mentions_denormalized_fields(self):
        assert "denormalized" in SYSTEM_PROMPT.lower() or "denorm" in SYSTEM_PROMPT.lower()

    def test_mentions_cite_records(self):
        assert "cite" in SYSTEM_PROMPT.lower()

    def test_mentions_availability_geography_scope(self):
        assert "Availability supports native market, submarket, and region" in SYSTEM_PROMPT
        assert "Lease does not currently" in SYSTEM_PROMPT
        assert "support market or submarket filters" in SYSTEM_PROMPT


# =========================================================================
# 2. TOOL_DEFINITIONS structure
# =========================================================================


class TestToolDefinitions:
    """Verify TOOL_DEFINITIONS structure and content."""

    def test_is_list_of_two(self):
        assert isinstance(TOOL_DEFINITIONS, list)
        assert len(TOOL_DEFINITIONS) == 2

    def test_tool_names(self):
        names = {d["toolSpec"]["name"] for d in TOOL_DEFINITIONS}
        assert names == {"search_records", "aggregate_records"}

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
        """search_records must list all active demo object types."""
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
        """aggregate_records must list all active demo object types."""
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
        result = build_system_prompt(SAMPLE_CONFIG)
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
        assert "denormalized" in result.lower() or "denorm" in result.lower()

    def test_live_salesforce_query_not_available(self):
        result = build_system_prompt(SAMPLE_CONFIG)
        assert "NOT available" in result

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
