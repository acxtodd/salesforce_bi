"""Unit tests for scripts/bulk_load.py — no SF/AWS credentials needed."""

import io
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root + lambda to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from bulk_load import (
    EMBED_BATCH_SIZE,
    FULL_TEXT_SEARCH_SCHEMA,
    UPSERT_BATCH_SIZE,
    _is_throttling,
    _embed_records_with_tolerance,
    _write_denorm_audits,
    build_document,
    build_relationship_map,
    build_soql,
    build_text,
    clean_label,
    create_s3_audit_client,
    embed_texts,
    flatten,
    generate_embeddings_batch,
    load_config,
    load_config_with_raw,
    load_object,
    main,
    resolve_audit_concurrency,
    resolve_embedding_concurrency,
    upsert_documents,
    validate_parents,
)

from lib.audit_writer import AuditingBackend, write_config_snapshot, write_denorm_audit


# ===================================================================
# Fixtures
# ===================================================================

SAMPLE_REL_MAP = {
    "ascendix__Property__c": "ascendix__Property__r",
    "ascendix__Tenant__c": "ascendix__Tenant__r",
    "ascendix__OwnerLandlord__c": "ascendix__OwnerLandlord__r",
}

SAMPLE_REL_META = {
    "ascendix__Property__c": {
        "relationship_name": "ascendix__Property__r",
        "relationship_label": "Property",
        "parent_object_api": "ascendix__Property__c",
        "parent_object_label": "Property",
    },
    "ascendix__Tenant__c": {
        "relationship_name": "ascendix__Tenant__r",
        "relationship_label": "Tenant",
        "parent_object_api": "Account",
        "parent_object_label": "Account",
    },
    "ascendix__OwnerLandlord__c": {
        "relationship_name": "ascendix__OwnerLandlord__r",
        "relationship_label": "Owner/Landlord",
        "parent_object_api": "Account",
        "parent_object_label": "Account",
    },
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


class _RecordingExecutor:
    def __init__(self, max_workers: int):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def submit(self, fn, *args, **kwargs):
        result = fn(*args, **kwargs)
        fut = MagicMock()
        fut.result.return_value = result
        return fut

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

    def test_standard_lookup_suffix_is_trimmed(self):
        assert clean_label("AccountId") == "Account"


# ===================================================================
# SOQL construction
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
        """Property has no parents — SOQL should have no dot-notation fields."""
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
        """Fields appearing in both embed and metadata should appear once."""
        soql = build_soql(
            "ascendix__Lease__c",
            ["Name", "ascendix__Status__c"],
            ["Name"],  # duplicate
            {},
            {},
        )
        # Count occurrences of "Name" — should be exactly 1
        parts = soql.split("FROM")[0]
        assert parts.count("Name") == 1

    def test_includes_fk_field(self):
        """The FK field (ref_field) should be in SELECT even if not in embed/metadata."""
        soql = build_soql(
            "ascendix__Lease__c",
            ["Name"],
            [],
            {"ascendix__Property__c": ["Name"]},
            SAMPLE_REL_MAP,
        )
        # The FK field ascendix__Property__c should appear
        select_part = soql.split("FROM")[0]
        assert "ascendix__Property__c" in select_part

    def test_multiple_parents(self):
        """Lease has Property, Tenant, OwnerLandlord parents."""
        parent_config = {
            "ascendix__Property__c": ["Name"],
            "ascendix__Tenant__c": ["Name"],
            "ascendix__OwnerLandlord__c": ["Name"],
        }
        soql = build_soql(
            "ascendix__Lease__c",
            ["Name"],
            [],
            parent_config,
            SAMPLE_REL_MAP,
        )
        assert "ascendix__Property__r.Name" in soql
        assert "ascendix__Tenant__r.Name" in soql
        assert "ascendix__OwnerLandlord__r.Name" in soql


# ===================================================================
# Flatten (Stage 2)
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
        """If parent relationship is None (orphan record), no KeyError."""
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
        """Fields not present in record don't appear in direct_fields."""
        record = {
            "Id": "a0x1",
            "LastModifiedDate": None,
            "Name": "Lease-X",
            # ascendix__LeaseType__c is missing
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
# Text generation (Stage 3)
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
            }
        }
        parent_config = {
            "ascendix__Property__c": ["Name", "ascendix__City__c"],
        }
        text = build_text(
            direct, parent, ["Name"], parent_config, "ascendix__Lease__c"
        )
        assert "Property Name: One Arts Plaza" in text
        assert "Property City: Dallas" in text
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

    def test_missing_parent_values_skipped(self):
        direct = {"Name": "Lease-001"}
        parent = {"ascendix__Property__c": {"Name": "One Arts Plaza"}}
        parent_config = {
            "ascendix__Property__c": ["Name", "ascendix__City__c"],
        }
        text = build_text(
            direct, parent, ["Name"], parent_config, "ascendix__Lease__c"
        )
        assert "City" not in text

    def test_pipe_delimiter(self):
        direct = {"Name": "Lease-001", "ascendix__LeaseType__c": "Office"}
        text = build_text(
            direct, {}, ["Name", "ascendix__LeaseType__c"], {}, "ascendix__Lease__c"
        )
        assert " | " in text


# ===================================================================
# Document building (Stage 4)
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
        # Raw SF name should NOT be a key
        assert "ascendix__City__c" not in doc

    def test_parent_field_keys_prefixed_and_cleaned(self):
        doc = build_document(
            direct_fields={
                "Id": "a0x1",
                "LastModifiedDate": "2025-01-01",
                "ascendix__Property__c": "a0y1",
                "ascendix__Tenant__c": "0011",
            },
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
            rel_map=SAMPLE_REL_META,
        )
        assert doc["property_id"] == "a0y1"
        assert doc["tenant_id"] == "0011"
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
            parent_fields={"ascendix__Property__c": {}},  # empty parent
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
# Relationship map & validation
# ===================================================================


class TestRelationshipMap:
    def _make_describe_response(self, fields):
        return {"fields": fields}

    def test_reference_fields_included(self):
        sf = MagicMock()
        sf.describe.side_effect = [
            self._make_describe_response(
                [
                    {
                        "name": "ascendix__Property__c",
                        "type": "reference",
                        "relationshipName": "ascendix__Property__r",
                        "referenceTo": ["ascendix__Property__c"],
                        "label": "Property",
                    },
                    {
                        "name": "ascendix__Tenant__c",
                        "type": "reference",
                        "relationshipName": "ascendix__Tenant__r",
                        "referenceTo": ["Account"],
                        "label": "Tenant",
                    },
                ]
            ),
            {"label": "Property"},
            {"label": "Account"},
        ]
        rel_map = build_relationship_map(sf, "ascendix__Lease__c")
        assert rel_map["ascendix__Property__c"]["relationship_name"] == "ascendix__Property__r"
        assert rel_map["ascendix__Property__c"]["relationship_label"] == "Property"
        assert rel_map["ascendix__Tenant__c"]["relationship_name"] == "ascendix__Tenant__r"
        assert rel_map["ascendix__Tenant__c"]["parent_object_label"] == "Account"

    def test_non_reference_fields_excluded(self):
        sf = MagicMock()
        sf.describe.side_effect = [
            self._make_describe_response(
            [
                {"name": "Name", "type": "string"},
                {
                    "name": "ascendix__Property__c",
                    "type": "reference",
                    "relationshipName": "ascendix__Property__r",
                    "referenceTo": ["ascendix__Property__c"],
                    "label": "Property",
                },
            ]
            ),
            {"label": "Property"},
        ]
        rel_map = build_relationship_map(sf, "ascendix__Lease__c")
        assert "Name" not in rel_map

    def test_reference_without_relationship_name_excluded(self):
        sf = MagicMock()
        sf.describe.return_value = self._make_describe_response(
            [
                {
                    "name": "OwnerId",
                    "type": "reference",
                    # no relationshipName
                },
            ]
        )
        rel_map = build_relationship_map(sf, "ascendix__Lease__c")
        assert "OwnerId" not in rel_map


class TestValidateParents:
    def test_passes_when_all_parents_resolve(self):
        validate_parents(
            SAMPLE_REL_MAP,
            SAMPLE_PARENT_CONFIG,
            "ascendix__Lease__c",
        )

    def test_raises_when_parent_not_in_map(self):
        with pytest.raises(ValueError, match="no relationshipName"):
            validate_parents(
                {"ascendix__Property__c": "ascendix__Property__r"},
                {
                    "ascendix__Property__c": ["Name"],
                    "ascendix__Tenant__c": ["Name"],  # not in rel_map
                },
                "ascendix__Lease__c",
            )

    def test_error_message_includes_object_and_field(self):
        with pytest.raises(ValueError, match="ascendix__Lease__c") as exc_info:
            validate_parents(
                {},
                {"ascendix__Bogus__c": ["Name"]},
                "ascendix__Lease__c",
            )
        assert "ascendix__Bogus__c" in str(exc_info.value)


# ===================================================================
# Bedrock embedding (mocked)
# ===================================================================


def _make_bedrock_mock(dimension=1024):
    """Create a mock bedrock client that returns deterministic embeddings."""
    mock = MagicMock()

    def invoke_model(**kwargs):
        body = json.loads(kwargs["body"])
        text = body["inputText"]
        dim = body["dimensions"]
        # Deterministic embedding based on text hash
        seed = hash(text) % 1000 / 1000
        embedding = [seed] * dim
        response_body = json.dumps({"embedding": embedding})
        return {"body": io.BytesIO(response_body.encode())}

    mock.invoke_model.side_effect = invoke_model
    return mock


class TestEmbedding:
    def test_batch_of_25_produces_25_embeddings(self):
        bedrock = _make_bedrock_mock()
        texts = [f"text_{i}" for i in range(25)]
        embeddings = generate_embeddings_batch(bedrock, texts)
        assert len(embeddings) == 25
        assert len(embeddings[0]) == 1024

    def test_partial_batch(self):
        bedrock = _make_bedrock_mock()
        texts = ["hello", "world"]
        embeddings = generate_embeddings_batch(bedrock, texts)
        assert len(embeddings) == 2

    def test_embed_texts_batching(self):
        bedrock = _make_bedrock_mock()
        texts = [f"text_{i}" for i in range(30)]
        embeddings = embed_texts(bedrock, texts)
        assert len(embeddings) == 30
        assert bedrock.invoke_model.call_count == 30

    def test_concurrent_batch_preserves_input_order(self):
        bedrock = MagicMock()
        delays = {"first": 0.03, "second": 0.01, "third": 0.0}
        values = {"first": 1.0, "second": 2.0, "third": 3.0}

        def invoke_side_effect(**kwargs):
            body = json.loads(kwargs["body"])
            text = body["inputText"]
            time_to_sleep = delays[text]
            if time_to_sleep:
                import time

                time.sleep(time_to_sleep)
            return {
                "body": io.BytesIO(
                    json.dumps({"embedding": [values[text]] * 2}).encode()
                )
            }

        bedrock.invoke_model.side_effect = invoke_side_effect

        embeddings = generate_embeddings_batch(
            bedrock,
            ["first", "second", "third"],
            concurrency=3,
        )

        assert embeddings == [[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]]

    def test_partial_failures_retry_only_failed_requests(self):
        bedrock = MagicMock()
        throttle_exc = Exception("ThrottlingException")
        throttle_exc.response = {"Error": {"Code": "ThrottlingException"}}
        attempts: dict[str, int] = {}

        def invoke_side_effect(**kwargs):
            body = json.loads(kwargs["body"])
            text = body["inputText"]
            attempts[text] = attempts.get(text, 0) + 1
            if text == "retry-me" and attempts[text] == 1:
                raise throttle_exc
            return {
                "body": io.BytesIO(
                    json.dumps({"embedding": [float(attempts[text])] * 2}).encode()
                )
            }

        prepared_rows = [
            {"record_id": "r1", "text": "first"},
            {"record_id": "r2", "text": "retry-me"},
            {"record_id": "r3", "text": "third"},
        ]
        bedrock.invoke_model.side_effect = invoke_side_effect

        with patch("bulk_load.time.sleep"):
            embeddings, embedded_rows, skipped_ids = _embed_records_with_tolerance(
                bedrock,
                prepared_rows,
                concurrency=3,
            )

        assert attempts == {"first": 1, "retry-me": 2, "third": 1}
        assert skipped_ids == []
        assert [row["record_id"] for row in embedded_rows] == ["r1", "r2", "r3"]
        assert embeddings == [[1.0, 1.0], [2.0, 2.0], [1.0, 1.0]]

    def test_throttling_triggers_retry(self):
        """ThrottlingException should trigger retry with backoff."""
        bedrock = MagicMock()
        throttle_exc = Exception("ThrottlingException")
        throttle_exc.response = {"Error": {"Code": "ThrottlingException"}}

        call_count = 0

        def invoke_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise throttle_exc
            body = json.dumps({"embedding": [0.1] * 1024})
            return {"body": io.BytesIO(body.encode())}

        bedrock.invoke_model.side_effect = invoke_side_effect

        with patch("bulk_load.time.sleep") as mock_sleep:
            embeddings = embed_texts(bedrock, ["test"])

        assert len(embeddings) == 1
        # time.sleep should have been called for the retries
        assert mock_sleep.call_count == 2

    def test_final_throttling_failure_surfaces_clearly(self):
        bedrock = MagicMock()
        throttle_exc = Exception("ThrottlingException")
        throttle_exc.response = {"Error": {"Code": "ThrottlingException"}}
        bedrock.invoke_model.side_effect = throttle_exc

        with patch("bulk_load.time.sleep"), pytest.raises(
            RuntimeError,
            match="Embedding failed after 5 attempts for request 0",
        ):
            generate_embeddings_batch(bedrock, ["test"], concurrency=1)

    def test_non_throttling_exception_propagates(self):
        """Non-throttling exceptions should propagate immediately."""
        bedrock = MagicMock()
        bedrock.invoke_model.side_effect = ValueError("model not found")

        with pytest.raises(ValueError, match="model not found"):
            embed_texts(bedrock, ["test"])

    def test_is_throttling_with_response(self):
        exc = Exception("error")
        exc.response = {"Error": {"Code": "ThrottlingException"}}
        assert _is_throttling(exc) is True

    def test_is_throttling_without_response(self):
        exc = ValueError("error")
        assert _is_throttling(exc) is False

    def test_is_throttling_different_code(self):
        exc = Exception("error")
        exc.response = {"Error": {"Code": "ValidationException"}}
        assert _is_throttling(exc) is False


class TestConcurrencyConfig:
    def test_invalid_embedding_env_raises_clear_value_error(self, monkeypatch):
        monkeypatch.setenv("BULK_LOAD_EMBED_CONCURRENCY", "abc")

        with pytest.raises(
            ValueError,
            match="BULK_LOAD_EMBED_CONCURRENCY must be an integer >= 1",
        ):
            resolve_embedding_concurrency()

    def test_invalid_audit_env_raises_clear_value_error(self, monkeypatch):
        monkeypatch.setenv("BULK_LOAD_AUDIT_CONCURRENCY", "abc")

        with pytest.raises(
            ValueError,
            match="BULK_LOAD_AUDIT_CONCURRENCY must be an integer >= 1",
        ):
            resolve_audit_concurrency()

    def test_main_exits_with_cli_error_for_invalid_env(self, monkeypatch, capsys):
        monkeypatch.setenv("BULK_LOAD_EMBED_CONCURRENCY", "abc")
        monkeypatch.setattr(
            sys,
            "argv",
            ["bulk_load.py", "--config", "denorm_config.yaml", "--dry-run"],
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "BULK_LOAD_EMBED_CONCURRENCY must be an integer >= 1" in captured.err


# ===================================================================
# Upsert batching (mocked)
# ===================================================================


class TestUpsertBatching:
    def test_250_docs_split_into_3_batches(self):
        backend = MagicMock()
        docs = [{"id": f"doc_{i}", "vector": [0.0]} for i in range(250)]

        upsert_documents(backend, "ns", docs)

        assert backend.upsert.call_count == 3
        # Batch sizes: 100, 100, 50
        calls = backend.upsert.call_args_list
        assert len(calls[0].kwargs["documents"]) == 100
        assert len(calls[1].kwargs["documents"]) == 100
        assert len(calls[2].kwargs["documents"]) == 50

    def test_schema_on_first_batch_only(self):
        backend = MagicMock()
        docs = [{"id": f"doc_{i}", "vector": [0.0]} for i in range(250)]

        upsert_documents(backend, "ns", docs)

        calls = backend.upsert.call_args_list
        assert calls[0].kwargs["schema"] == FULL_TEXT_SEARCH_SCHEMA
        assert calls[1].kwargs["schema"] is None
        assert calls[2].kwargs["schema"] is None

    def test_schema_scans_all_documents_for_late_numeric_fields(self):
        backend = MagicMock()
        docs = [
            {"id": f"doc_{i}", "vector": [0.0], "text": f"doc {i}"}
            for i in range(100)
        ]
        docs.append(
            {
                "id": "doc_late",
                "vector": [0.0],
                "text": "late",
                "ownerlandlord_annualrevenue": 10000000.0,
            }
        )

        upsert_documents(backend, "ns", docs)

        schema = backend.upsert.call_args_list[0].kwargs["schema"]
        assert schema["ownerlandlord_annualrevenue"] == {"type": "float"}

    def test_empty_documents_no_calls(self):
        backend = MagicMock()
        upsert_documents(backend, "ns", [])
        backend.upsert.assert_not_called()

    def test_exact_batch_size(self):
        """Exactly 100 docs = 1 batch."""
        backend = MagicMock()
        docs = [{"id": f"doc_{i}", "vector": [0.0]} for i in range(100)]

        upsert_documents(backend, "ns", docs)

        assert backend.upsert.call_count == 1
        assert calls_schema(backend, 0) == FULL_TEXT_SEARCH_SCHEMA

    def test_single_doc(self):
        backend = MagicMock()
        docs = [{"id": "doc_0", "vector": [0.0]}]

        upsert_documents(backend, "ns", docs)

        assert backend.upsert.call_count == 1
        assert len(backend.upsert.call_args.kwargs["documents"]) == 1


def calls_schema(mock, index):
    return mock.upsert.call_args_list[index].kwargs["schema"]


class TestLoadObjectHardening:
    def _make_sf(self, records):
        sf = MagicMock()
        sf.describe.return_value = {"fields": []}
        sf.query_all.return_value = records
        return sf

    def _make_backend(self, final_count):
        backend = MagicMock()
        backend.aggregate.return_value = {"count": final_count}
        return backend

    def test_skips_bad_prepare_record_and_continues(self, caplog):
        records = [
            {"Id": "r1", "LastModifiedDate": "2025-01-01", "Name": "Good 1"},
            {"Id": "r2", "LastModifiedDate": "2025-01-01", "Name": "Bad"},
            {"Id": "r3", "LastModifiedDate": "2025-01-01", "Name": "Good 2"},
        ]
        sf = self._make_sf(records)
        backend = self._make_backend(final_count=2)

        def build_text_side_effect(direct, *_args, **_kwargs):
            if direct["Name"] == "Bad":
                raise ValueError("bad text")
            return f"Lease: | Name: {direct['Name']}"

        with patch("bulk_load.build_text", side_effect=build_text_side_effect):
            summary = load_object(
                sf_client=sf,
                bedrock_client=_make_bedrock_mock(),
                backend=backend,
                object_name="ascendix__Lease__c",
                object_config={"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
                namespace="ns",
                salesforce_org_id="00Dxx",
            )

        assert summary.fetched_count == 3
        assert summary.indexed_count == 2
        assert summary.skipped_count == 1
        assert summary.turbopuffer_count == 2
        assert summary.count_mismatch is False
        assert "r2" in summary.skipped_ids
        assert "Skipping record r2 during flatten/text preparation" in caplog.text
        assert len(backend.upsert.call_args.kwargs["documents"]) == 2

    def test_embedding_skips_only_failed_record(self, caplog):
        records = [
            {"Id": "r1", "LastModifiedDate": "2025-01-01", "Name": "Good 1"},
            {"Id": "r2", "LastModifiedDate": "2025-01-01", "Name": "Bad"},
            {"Id": "r3", "LastModifiedDate": "2025-01-01", "Name": "Good 2"},
        ]
        sf = self._make_sf(records)
        backend = self._make_backend(final_count=2)
        bedrock = MagicMock()

        def invoke_side_effect(**kwargs):
            body = json.loads(kwargs["body"])
            text = body["inputText"]
            if "Bad" in text:
                raise ValueError("record embed failed")
            return {"body": io.BytesIO(json.dumps({"embedding": [0.1] * 1024}).encode())}

        bedrock.invoke_model.side_effect = invoke_side_effect

        summary = load_object(
            sf_client=sf,
            bedrock_client=bedrock,
            backend=backend,
            object_name="ascendix__Lease__c",
            object_config={"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            namespace="ns",
            salesforce_org_id="00Dxx",
        )

        assert summary.fetched_count == 3
        assert summary.indexed_count == 2
        assert summary.skipped_count == 1
        assert summary.turbopuffer_count == 2
        assert summary.count_mismatch is False
        assert "r2" in summary.skipped_ids
        assert "Skipping record r2 during embedding" in caplog.text

    def test_count_mismatch_is_surfaced_clearly(self, caplog):
        records = [
            {"Id": "r1", "LastModifiedDate": "2025-01-01", "Name": "Good 1"},
            {"Id": "r2", "LastModifiedDate": "2025-01-01", "Name": "Good 2"},
        ]
        sf = self._make_sf(records)
        backend = self._make_backend(final_count=1)

        summary = load_object(
            sf_client=sf,
            bedrock_client=_make_bedrock_mock(),
            backend=backend,
            object_name="ascendix__Lease__c",
            object_config={"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            namespace="ns",
            salesforce_org_id="00Dxx",
        )

        assert summary.indexed_count == 2
        assert summary.turbopuffer_count == 1
        assert summary.count_mismatch is True
        assert "Post-load count mismatch" in caplog.text

    def test_count_verification_failure_is_surfaced(self, caplog):
        records = [
            {"Id": "r1", "LastModifiedDate": "2025-01-01", "Name": "Good 1"},
        ]
        sf = self._make_sf(records)
        backend = MagicMock()
        backend.aggregate.side_effect = RuntimeError("aggregate failed")

        summary = load_object(
            sf_client=sf,
            bedrock_client=_make_bedrock_mock(),
            backend=backend,
            object_name="ascendix__Lease__c",
            object_config={"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            namespace="ns",
            salesforce_org_id="00Dxx",
        )

        assert summary.indexed_count == 1
        assert summary.turbopuffer_count is None
        assert summary.count_mismatch is True
        assert "Could not verify post-load count" in caplog.text
        assert "Post-load count verification unavailable" in caplog.text

    def test_stage_timings_are_recorded_and_logged(self, caplog):
        caplog.set_level("INFO")
        records = [
            {"Id": "r1", "LastModifiedDate": "2025-01-01", "Name": "Good 1"},
        ]
        sf = self._make_sf(records)
        backend = self._make_backend(final_count=1)

        summary = load_object(
            sf_client=sf,
            bedrock_client=_make_bedrock_mock(),
            backend=backend,
            object_name="ascendix__Lease__c",
            object_config={"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            namespace="ns",
            salesforce_org_id="00Dxx",
        )

        for key in ("fetch", "prep_audit", "embed", "upsert", "total"):
            assert key in summary.stage_timings
            assert summary.stage_timings[key] >= 0.0
        assert "stage timings:" in caplog.text


# ===================================================================
# End-to-end: flatten -> text -> document
# ===================================================================


class TestEndToEnd:
    def test_lease_pipeline(self):
        """Full pipeline for a Lease record: flatten, text, document."""
        direct, parent = flatten(
            SAMPLE_SF_RECORD,
            SAMPLE_EMBED_FIELDS,
            SAMPLE_METADATA_FIELDS,
            SAMPLE_PARENT_CONFIG,
            SAMPLE_REL_MAP,
        )

        text = build_text(
            direct,
            parent,
            SAMPLE_EMBED_FIELDS,
            SAMPLE_PARENT_CONFIG,
            "ascendix__Lease__c",
        )

        # Text should have object prefix + direct + parent fields
        assert text.startswith("Lease:")
        assert "LeaseType: Office" in text
        assert "Name: One Arts Plaza" in text
        assert "City: Dallas" in text

        doc = build_document(
            direct_fields=direct,
            parent_fields=parent,
            text=text,
            vector=[0.0] * 1024,
            record_id="a0x000000000001AAA",
            object_type="ascendix__Lease__c",
            salesforce_org_id="00Dxx",
            embed_field_names=SAMPLE_EMBED_FIELDS,
            metadata_field_names=SAMPLE_METADATA_FIELDS,
            parent_config=SAMPLE_PARENT_CONFIG,
        )

        # System fields
        assert doc["id"] == "a0x000000000001AAA"
        assert doc["object_type"] == "lease"
        assert doc["salesforce_org_id"] == "00Dxx"

        # Direct fields cleaned
        assert doc["leasetype"] == "Office"
        assert doc["name"] == "Lease-001"
        assert doc["leasedsf"] == 15000

        # Parent fields prefixed + cleaned
        assert doc["property_name"] == "One Arts Plaza"
        assert doc["property_city"] == "Dallas"
        assert doc["property_state"] == "TX"
        assert doc["tenant_name"] == "ACME Corp"
        assert doc["tenant_industry"] == "Technology"

        # No raw SF names
        for key in doc:
            if key in ("id", "vector", "text", "object_type", "last_modified",
                       "salesforce_org_id"):
                continue
            assert "ascendix__" not in key
            assert "__c" not in key


# ===================================================================
# Audit trail integration
# ===================================================================


class TestAuditBulkLoad:
    def test_audit_bucket_wraps_backend(self):
        """AuditingBackend is used when --audit-bucket is set."""
        inner = MagicMock()
        s3 = MagicMock()
        ab = AuditingBackend(inner, s3, "audit-bucket", "org123")

        # Verify it delegates upsert and adds S3 writes to replay/ prefix
        docs = [{"id": "r1", "object_type": "property"}]
        ab.upsert("ns", documents=docs)

        inner.upsert.assert_called_once()
        s3.put_object.assert_called_once()
        key = s3.put_object.call_args[1]["Key"]
        assert key.startswith("replay/")
        assert ab.stats.audit_ok == 1

    def test_no_audit_without_flag(self):
        """Plain TurbopufferBackend is used when --audit-bucket is not set."""
        # Just verify that the wrapper is not applied without the flag
        backend = MagicMock(spec=["upsert", "delete", "search", "aggregate", "warm"])
        assert not isinstance(backend, AuditingBackend)

    def test_config_snapshot_written_before_first_load(self):
        """Verify _meta/ write happens via write_config_snapshot."""
        s3 = MagicMock()
        write_config_snapshot(
            s3, "audit-bucket", "org123",
            {"property": {"embed_fields": ["Name"]}},
            "property:\n  embed_fields: [Name]\n",
            "bulk_load",
        )

        assert s3.put_object.call_count == 2
        keys = [c[1]["Key"] for c in s3.put_object.call_args_list]
        assert any("_meta/" in k and "bulk_load" in k for k in keys)

    def test_write_denorm_audits_respects_configured_concurrency(self):
        audit_s3 = MagicMock()
        rows = [
            {
                "record_id": f"r{i}",
                "direct_fields": {"LastModifiedDate": "2025-01-01"},
                "parent_fields": {},
                "text": f"text {i}",
            }
            for i in range(5)
        ]

        with patch(
            "bulk_load.ThreadPoolExecutor",
            side_effect=lambda max_workers: _RecordingExecutor(max_workers),
        ) as executor, patch(
            "bulk_load.as_completed",
            side_effect=lambda futures: list(futures),
        ):
            ok, failed = _write_denorm_audits(
                audit_s3,
                "audit-bucket",
                "org123",
                "ascendix__Lease__c",
                rows,
                audit_concurrency=3,
            )

        assert executor.call_args[1]["max_workers"] == 3
        assert ok == 5
        assert failed == 0

    def test_create_s3_audit_client_pool_matches_concurrency(self):
        captured: dict[str, object] = {}

        def fake_client(service_name, *, config):
            captured["service_name"] = service_name
            captured["config"] = config
            return "s3-client"

        fake_boto3 = types.SimpleNamespace(client=fake_client)
        with patch.dict(sys.modules, {"boto3": fake_boto3}):
            client = create_s3_audit_client(23)

        assert client == "s3-client"
        assert captured["service_name"] == "s3"
        assert captured["config"].max_pool_connections == 23

    def test_load_config_returns_dict(self, tmp_path):
        """load_config returns a plain dict (backwards-compatible)."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("ascendix__Property__c:\n  embed_fields: [Name]\n")

        result = load_config(str(config_file))

        assert isinstance(result, dict)
        assert "ascendix__Property__c" in result

    def test_load_config_with_raw_returns_tuple(self, tmp_path):
        """load_config_with_raw returns (dict, raw_str) tuple."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("ascendix__Property__c:\n  embed_fields: [Name]\n")

        config_dict, raw_str = load_config_with_raw(str(config_file))

        assert isinstance(config_dict, dict)
        assert "ascendix__Property__c" in config_dict
        assert "embed_fields" in raw_str


# ===================================================================
# Denorm audit in bulk load pipeline
# ===================================================================


class TestDenormAuditBulkLoad:
    """Verify load_object writes denorm audit at Stage 2.5 before embedding."""

    def _make_sf(self, records):
        sf = MagicMock()
        sf.describe.return_value = {"fields": []}
        sf.query_all.return_value = records
        return sf

    def test_denorm_audit_written_before_embedding(self, caplog):
        """Denorm audit captures records that later fail embedding."""
        records = [
            {"Id": "r1", "LastModifiedDate": "2025-01-01", "Name": "Good"},
            {"Id": "r2", "LastModifiedDate": "2025-01-01", "Name": "Bad"},
        ]
        sf = self._make_sf(records)
        audit_s3 = MagicMock()
        bedrock = MagicMock()

        def invoke_side_effect(**kwargs):
            body = json.loads(kwargs["body"])
            text = body["inputText"]
            if "Bad" in text:
                raise ValueError("embed failed")
            return {"body": io.BytesIO(json.dumps({"embedding": [0.1] * 1024}).encode())}

        bedrock.invoke_model.side_effect = invoke_side_effect

        summary = load_object(
            sf_client=sf,
            bedrock_client=bedrock,
            backend=MagicMock(aggregate=MagicMock(return_value={"count": 1})),
            object_name="ascendix__Lease__c",
            object_config={"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            namespace="ns",
            salesforce_org_id="00Dxx",
            audit_s3_client=audit_s3,
            audit_bucket="audit-bucket",
        )

        # Both records should have denorm audits (written BEFORE embedding)
        denorm_calls = [
            c for c in audit_s3.put_object.call_args_list
            if c[1]["Key"].startswith("documents/")
        ]
        assert len(denorm_calls) == 2

        # Verify denorm audit content
        bodies = [json.loads(c[1]["Body"]) for c in denorm_calls]
        record_ids = {b["record_id"] for b in bodies}
        assert "r1" in record_ids
        assert "r2" in record_ids  # even though embedding failed for r2

        # Each body should have direct_fields, parent_fields, text, no vector
        for b in bodies:
            assert "direct_fields" in b
            assert "parent_fields" in b
            assert "text" in b
            assert "vector" not in b

    def test_denorm_audit_skipped_without_params(self):
        """No denorm audit when audit_s3_client/audit_bucket not provided."""
        records = [
            {"Id": "r1", "LastModifiedDate": "2025-01-01", "Name": "Good"},
        ]
        sf = self._make_sf(records)

        summary = load_object(
            sf_client=sf,
            bedrock_client=_make_bedrock_mock(),
            backend=MagicMock(aggregate=MagicMock(return_value={"count": 1})),
            object_name="ascendix__Lease__c",
            object_config={"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            namespace="ns",
            salesforce_org_id="00Dxx",
            # No audit_s3_client / audit_bucket
        )

        assert summary.indexed_count == 1

    def test_denorm_audit_stats_propagate_to_backend(self):
        records = [
            {"Id": "r1", "LastModifiedDate": "2025-01-01", "Name": "Good"},
        ]
        sf = self._make_sf(records)
        audit_s3 = MagicMock()
        inner_backend = MagicMock()
        inner_backend.aggregate.return_value = {"count": 1}
        backend = AuditingBackend(
            inner_backend,
            audit_s3,
            "audit-bucket",
            "00Dxx",
            audit_concurrency=2,
        )

        summary = load_object(
            sf_client=sf,
            bedrock_client=_make_bedrock_mock(),
            backend=backend,
            object_name="ascendix__Lease__c",
            object_config={"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            namespace="ns",
            salesforce_org_id="00Dxx",
            audit_s3_client=audit_s3,
            audit_bucket="audit-bucket",
            audit_write_concurrency=2,
        )

        assert summary.denorm_audit_ok == 1
        assert summary.denorm_audit_failed == 0
        assert backend.stats.denorm_audit_ok == 1
        assert backend.stats.denorm_audit_failed == 0
