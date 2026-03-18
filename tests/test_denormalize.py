"""Unit tests for lib/denormalize.py — pure function tests, no I/O."""

import sys
from pathlib import Path

import pytest

# Add project root + lambda to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))

from lib.denormalize import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_ID,
    FULL_TEXT_SEARCH_SCHEMA,
    PINNED_TEXT_FULL_TEXT_SETTINGS,
    build_document,
    build_soql,
    build_text,
    clean_label,
    flatten,
)


# ===================================================================
# Fixtures
# ===================================================================

SAMPLE_REL_MAP = {
    "ascendix__Property__c": "ascendix__Property__r",
    "ascendix__Tenant__c": "ascendix__Tenant__r",
    "ascendix__OwnerLandlord__c": "ascendix__OwnerLandlord__r",
}

SAMPLE_EMBED_FIELDS = [
    "ascendix__LeaseType__c",
    "Name",
    "ascendix__Status__c",
    "ascendix__LeasedSF__c",
]

SAMPLE_METADATA_FIELDS = ["ascendix__Property__c"]

SAMPLE_PARENT_CONFIG = {
    "ascendix__Property__c": ["Name", "ascendix__City__c", "ascendix__State__c"],
    "ascendix__Tenant__c": ["Name", "Industry"],
}

SAMPLE_SF_RECORD = {
    "attributes": {"type": "ascendix__Lease__c", "url": "/services/data/v59.0/..."},
    "Id": "a0x000000000001AAA",
    "LastModifiedDate": "2025-03-01T12:00:00.000+0000",
    "ascendix__LeaseType__c": "Office",
    "Name": "Lease-001",
    "ascendix__Status__c": "Active",
    "ascendix__LeasedSF__c": 15000,
    "ascendix__Property__c": "a0y000000000001AAA",
    "ascendix__Property__r": {
        "attributes": {"type": "ascendix__Property__c"},
        "Name": "One Arts Plaza",
        "ascendix__City__c": "Dallas",
        "ascendix__State__c": "TX",
    },
    "ascendix__Tenant__r": {
        "attributes": {"type": "Account"},
        "Name": "ACME Corp",
        "Industry": "Technology",
    },
}


# ===================================================================
# clean_label
# ===================================================================


class TestCleanLabel:
    def test_strips_namespace_and_custom_suffix(self):
        assert clean_label("ascendix__City__c") == "City"

    def test_strips_relationship_suffix(self):
        assert clean_label("ascendix__Property__r") == "Property"

    def test_standard_field_unchanged(self):
        assert clean_label("Name") == "Name"
        assert clean_label("Industry") == "Industry"

    def test_id_field(self):
        assert clean_label("Id") == "Id"

    def test_double_underscore_only_namespace(self):
        """Field with only namespace prefix, no __c."""
        assert clean_label("ascendix__Foo") == "Foo"


# ===================================================================
# build_soql
# ===================================================================


class TestBuildSOQL:
    def test_basic_select_with_embed_and_metadata(self):
        soql = build_soql(
            "ascendix__Lease__c",
            ["ascendix__LeaseType__c", "Name"],
            ["ascendix__Property__c"],
            {},
            {},
        )
        assert soql.startswith("SELECT ")
        assert "Id" in soql
        assert "LastModifiedDate" in soql
        assert "ascendix__LeaseType__c" in soql
        assert "Name" in soql
        assert "ascendix__Property__c" in soql
        assert soql.endswith("FROM ascendix__Lease__c")

    def test_includes_parent_relationship_fields(self):
        soql = build_soql(
            "ascendix__Lease__c",
            SAMPLE_EMBED_FIELDS,
            SAMPLE_METADATA_FIELDS,
            SAMPLE_PARENT_CONFIG,
            SAMPLE_REL_MAP,
        )
        assert "ascendix__Property__r.Name" in soql
        assert "ascendix__Property__r.ascendix__City__c" in soql
        assert "ascendix__Property__r.ascendix__State__c" in soql
        assert "ascendix__Tenant__r.Name" in soql
        assert "ascendix__Tenant__r.Industry" in soql

    def test_no_parents_object(self):
        soql = build_soql(
            "ascendix__Property__c",
            ["Name", "ascendix__City__c"],
            [],
            {},
            {},
        )
        assert "." not in soql
        assert "FROM ascendix__Property__c" in soql

    def test_deduplication(self):
        soql = build_soql(
            "ascendix__Lease__c",
            ["Name", "ascendix__Status__c"],
            ["Name"],  # duplicate
            {},
            {},
        )
        parts = soql.split("FROM")[0]
        assert parts.count("Name") == 1

    def test_includes_fk_field(self):
        soql = build_soql(
            "ascendix__Lease__c",
            ["Name"],
            [],
            {"ascendix__Property__c": ["Name"]},
            SAMPLE_REL_MAP,
        )
        select_part = soql.split("FROM")[0]
        assert "ascendix__Property__c" in select_part


# ===================================================================
# flatten
# ===================================================================


class TestFlatten:
    def test_direct_fields_contain_embed_and_metadata(self):
        direct, parent = flatten(
            SAMPLE_SF_RECORD,
            SAMPLE_EMBED_FIELDS,
            SAMPLE_METADATA_FIELDS,
            SAMPLE_PARENT_CONFIG,
            SAMPLE_REL_MAP,
        )
        assert direct["ascendix__LeaseType__c"] == "Office"
        assert direct["Name"] == "Lease-001"
        assert direct["ascendix__Status__c"] == "Active"
        assert direct["ascendix__LeasedSF__c"] == 15000
        assert direct["ascendix__Property__c"] == "a0y000000000001AAA"

    def test_system_fields_always_present(self):
        direct, _ = flatten(
            SAMPLE_SF_RECORD,
            SAMPLE_EMBED_FIELDS,
            SAMPLE_METADATA_FIELDS,
            SAMPLE_PARENT_CONFIG,
            SAMPLE_REL_MAP,
        )
        assert direct["Id"] == "a0x000000000001AAA"
        assert "LastModifiedDate" in direct

    def test_parent_fields_structured_by_ref_field(self):
        _, parent = flatten(
            SAMPLE_SF_RECORD,
            SAMPLE_EMBED_FIELDS,
            SAMPLE_METADATA_FIELDS,
            SAMPLE_PARENT_CONFIG,
            SAMPLE_REL_MAP,
        )
        assert parent["ascendix__Property__c"]["Name"] == "One Arts Plaza"
        assert parent["ascendix__Property__c"]["ascendix__City__c"] == "Dallas"
        assert parent["ascendix__Tenant__c"]["Name"] == "ACME Corp"
        assert parent["ascendix__Tenant__c"]["Industry"] == "Technology"

    def test_null_parent_relationship_yields_empty_dict(self):
        record = dict(SAMPLE_SF_RECORD)
        record["ascendix__Property__r"] = None
        _, parent = flatten(
            record,
            SAMPLE_EMBED_FIELDS,
            SAMPLE_METADATA_FIELDS,
            SAMPLE_PARENT_CONFIG,
            SAMPLE_REL_MAP,
        )
        assert parent["ascendix__Property__c"] == {}

    def test_missing_optional_fields_excluded(self):
        record = {
            "Id": "a0x1",
            "LastModifiedDate": None,
            "Name": "Lease-X",
        }
        direct, _ = flatten(
            record,
            ["Name", "ascendix__LeaseType__c"],
            [],
            {},
            {},
        )
        assert "Name" in direct
        assert "ascendix__LeaseType__c" not in direct


# ===================================================================
# build_text
# ===================================================================


class TestBuildText:
    def test_includes_object_type_prefix(self):
        direct = {"ascendix__LeaseType__c": "Office", "Name": "Lease-001"}
        text = build_text(
            direct, {}, ["ascendix__LeaseType__c", "Name"], {}, "ascendix__Lease__c"
        )
        assert text.startswith("Lease:")

    def test_embed_fields_with_cleaned_labels(self):
        direct = {"ascendix__LeaseType__c": "Office", "Name": "Lease-001"}
        text = build_text(
            direct, {}, ["ascendix__LeaseType__c", "Name"], {}, "ascendix__Lease__c"
        )
        assert "LeaseType: Office" in text
        assert "Name: Lease-001" in text

    def test_parent_fields_included(self):
        direct = {"Name": "Lease-001"}
        parent = {
            "ascendix__Property__c": {
                "Name": "One Arts Plaza",
                "ascendix__City__c": "Dallas",
            },
            "ascendix__Tenant__c": {
                "Name": "ACME Corp",
            }
        }
        parent_config = {
            "ascendix__Property__c": ["Name", "ascendix__City__c"],
            "ascendix__Tenant__c": ["Name"],
        }
        text = build_text(
            direct, parent, ["Name"], parent_config, "ascendix__Lease__c"
        )
        assert "Property Name: One Arts Plaza" in text
        assert "Property City: Dallas" in text
        assert "Tenant Name: ACME Corp" in text
        assert " | Name: One Arts Plaza" not in text

    def test_null_values_skipped(self):
        direct = {"ascendix__LeaseType__c": "Office"}
        text = build_text(
            direct,
            {},
            ["ascendix__LeaseType__c", "ascendix__Status__c"],
            {},
            "ascendix__Lease__c",
        )
        assert "Status" not in text
        assert "None" not in text

    def test_pipe_delimiter(self):
        direct = {"Name": "Lease-001", "ascendix__LeaseType__c": "Office"}
        text = build_text(
            direct, {}, ["Name", "ascendix__LeaseType__c"], {}, "ascendix__Lease__c"
        )
        assert " | " in text


# ===================================================================
# build_document
# ===================================================================


class TestBuildDocument:
    def test_system_fields_present(self):
        doc = build_document(
            direct_fields={"Id": "a0x1", "LastModifiedDate": "2025-01-01", "Name": "X"},
            parent_fields={},
            text="test text",
            vector=[0.1] * 1024,
            record_id="a0x1",
            object_type="ascendix__Lease__c",
            salesforce_org_id="00Dxx",
            embed_field_names=["Name"],
            metadata_field_names=[],
            parent_config={},
        )
        assert doc["id"] == "a0x1"
        assert doc["vector"] == [0.1] * 1024
        assert doc["text"] == "test text"
        assert doc["object_type"] == "lease"
        assert doc["last_modified"] == "2025-01-01"
        assert doc["salesforce_org_id"] == "00Dxx"

    def test_direct_field_keys_cleaned(self):
        doc = build_document(
            direct_fields={
                "Id": "a0x1",
                "LastModifiedDate": "2025-01-01",
                "ascendix__City__c": "Dallas",
                "Name": "Test",
            },
            parent_fields={},
            text="t",
            vector=[0.0],
            record_id="a0x1",
            object_type="ascendix__Property__c",
            salesforce_org_id="00D",
            embed_field_names=["ascendix__City__c", "Name"],
            metadata_field_names=[],
            parent_config={},
        )
        assert doc["city"] == "Dallas"
        assert doc["name"] == "Test"
        assert "ascendix__City__c" not in doc

    def test_parent_field_keys_prefixed_and_cleaned(self):
        doc = build_document(
            direct_fields={"Id": "a0x1", "LastModifiedDate": "2025-01-01"},
            parent_fields={
                "ascendix__Property__c": {
                    "Name": "One Arts Plaza",
                    "ascendix__City__c": "Dallas",
                },
                "ascendix__Tenant__c": {"Industry": "Technology"},
            },
            text="t",
            vector=[0.0],
            record_id="a0x1",
            object_type="ascendix__Lease__c",
            salesforce_org_id="00D",
            embed_field_names=[],
            metadata_field_names=[],
            parent_config={
                "ascendix__Property__c": ["Name", "ascendix__City__c"],
                "ascendix__Tenant__c": ["Industry"],
            },
        )
        assert doc["property_name"] == "One Arts Plaza"
        assert doc["property_city"] == "Dallas"
        assert doc["tenant_industry"] == "Technology"

    def test_no_raw_sf_names_in_document(self):
        doc = build_document(
            direct_fields={
                "Id": "a0x1",
                "LastModifiedDate": "2025-01-01",
                "ascendix__PropertyClass__c": "A",
                "ascendix__TotalSF__c": 50000,
            },
            parent_fields={},
            text="t",
            vector=[0.0],
            record_id="a0x1",
            object_type="ascendix__Property__c",
            salesforce_org_id="00D",
            embed_field_names=["ascendix__PropertyClass__c", "ascendix__TotalSF__c"],
            metadata_field_names=[],
            parent_config={},
        )
        for key in doc:
            assert "ascendix__" not in key, f"Raw SF name found: {key}"
            assert "__c" not in key, f"Custom suffix found: {key}"

    def test_missing_direct_value_not_in_doc(self):
        doc = build_document(
            direct_fields={"Id": "a0x1", "LastModifiedDate": "2025-01-01"},
            parent_fields={},
            text="t",
            vector=[0.0],
            record_id="a0x1",
            object_type="ascendix__Property__c",
            salesforce_org_id="00D",
            embed_field_names=["ascendix__City__c"],
            metadata_field_names=[],
            parent_config={},
        )
        assert "city" not in doc

    def test_missing_parent_value_not_in_doc(self):
        doc = build_document(
            direct_fields={"Id": "a0x1", "LastModifiedDate": "2025-01-01"},
            parent_fields={"ascendix__Property__c": {}},
            text="t",
            vector=[0.0],
            record_id="a0x1",
            object_type="ascendix__Lease__c",
            salesforce_org_id="00D",
            embed_field_names=[],
            metadata_field_names=[],
            parent_config={"ascendix__Property__c": ["Name", "ascendix__City__c"]},
        )
        assert "property_name" not in doc
        assert "property_city" not in doc


# ===================================================================
# FULL_TEXT_SEARCH_SCHEMA structure
# ===================================================================


class TestSchema:
    def test_text_field_has_full_text_search(self):
        assert "text" in FULL_TEXT_SEARCH_SCHEMA
        assert FULL_TEXT_SEARCH_SCHEMA["text"]["type"] == "string"
        assert (
            FULL_TEXT_SEARCH_SCHEMA["text"]["full_text_search"]
            == PINNED_TEXT_FULL_TEXT_SETTINGS
        )

    def test_text_field_pins_expected_tokenizer_settings(self):
        assert PINNED_TEXT_FULL_TEXT_SETTINGS == {
            "tokenizer": "word_v3",
            "language": "english",
            "stemming": False,
            "remove_stopwords": False,
        }

    def test_numeric_fields_are_float(self):
        numeric_keys = [k for k in FULL_TEXT_SEARCH_SCHEMA if k != "text"]
        for key in numeric_keys:
            assert FULL_TEXT_SEARCH_SCHEMA[key]["type"] == "float", (
                f"{key} should be float"
            )

    def test_expected_numeric_fields_present(self):
        expected = [
            "totalbuildingarea",
            "floors",
            "occupancy",
            "landarea",
            "size",
            "leaserateperuom",
            "averagerent",
            "termmonths",
            "availablearea",
            "rentlow",
            "renthigh",
            "askingprice",
            "maxcontiguousarea",
            "mindivisiblearea",
            "leasetermmin",
            "leasetermmax",
            "property_totalbuildingarea",
        ]
        for field in expected:
            assert field in FULL_TEXT_SEARCH_SCHEMA, f"Missing: {field}"


# ===================================================================
# Constants
# ===================================================================


class TestConstants:
    def test_embedding_model_id(self):
        assert EMBEDDING_MODEL_ID == "amazon.titan-embed-text-v2:0"

    def test_embedding_dimensions(self):
        assert EMBEDDING_DIMENSIONS == 1024
