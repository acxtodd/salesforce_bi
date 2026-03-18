"""Unit tests for scripts/bulk_load.py — no SF/AWS credentials needed."""

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

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
    build_document,
    build_relationship_map,
    build_soql,
    build_text,
    clean_label,
    embed_texts,
    flatten,
    generate_embeddings_batch,
    load_object,
    upsert_documents,
    validate_parents,
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
        sf.describe.return_value = self._make_describe_response(
            [
                {
                    "name": "ascendix__Property__c",
                    "type": "reference",
                    "relationshipName": "ascendix__Property__r",
                },
                {
                    "name": "ascendix__Tenant__c",
                    "type": "reference",
                    "relationshipName": "ascendix__Tenant__r",
                },
            ]
        )
        rel_map = build_relationship_map(sf, "ascendix__Lease__c")
        assert rel_map["ascendix__Property__c"] == "ascendix__Property__r"
        assert rel_map["ascendix__Tenant__c"] == "ascendix__Tenant__r"

    def test_non_reference_fields_excluded(self):
        sf = MagicMock()
        sf.describe.return_value = self._make_describe_response(
            [
                {"name": "Name", "type": "string"},
                {
                    "name": "ascendix__Property__c",
                    "type": "reference",
                    "relationshipName": "ascendix__Property__r",
                },
            ]
        )
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
        # Should have called invoke_model 30 times (one per text)
        assert bedrock.invoke_model.call_count == 30

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
            with patch(
                "bulk_load.generate_embeddings_batch",
                return_value=[[0.1] * 1024, [0.2] * 1024],
            ):
                summary = load_object(
                    sf_client=sf,
                    bedrock_client=MagicMock(),
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

    def test_embedding_batch_falls_back_to_per_record(self, caplog):
        records = [
            {"Id": "r1", "LastModifiedDate": "2025-01-01", "Name": "Good 1"},
            {"Id": "r2", "LastModifiedDate": "2025-01-01", "Name": "Bad"},
            {"Id": "r3", "LastModifiedDate": "2025-01-01", "Name": "Good 2"},
        ]
        sf = self._make_sf(records)
        backend = self._make_backend(final_count=2)

        def generate_side_effect(_bedrock, texts):
            if len(texts) > 1 and any("Bad" in text for text in texts):
                raise ValueError("batch embed failed")
            if any("Bad" in text for text in texts):
                raise ValueError("record embed failed")
            return [[0.1] * 1024 for _ in texts]

        with patch("bulk_load.generate_embeddings_batch", side_effect=generate_side_effect):
            summary = load_object(
                sf_client=sf,
                bedrock_client=MagicMock(),
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
        assert "retrying per record" in caplog.text
        assert "Skipping record r2 during embedding" in caplog.text

    def test_count_mismatch_is_surfaced_clearly(self, caplog):
        records = [
            {"Id": "r1", "LastModifiedDate": "2025-01-01", "Name": "Good 1"},
            {"Id": "r2", "LastModifiedDate": "2025-01-01", "Name": "Good 2"},
        ]
        sf = self._make_sf(records)
        backend = self._make_backend(final_count=1)

        with patch(
            "bulk_load.generate_embeddings_batch",
            return_value=[[0.1] * 1024, [0.2] * 1024],
        ):
            summary = load_object(
                sf_client=sf,
                bedrock_client=MagicMock(),
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

        with patch(
            "bulk_load.generate_embeddings_batch",
            return_value=[[0.1] * 1024],
        ):
            summary = load_object(
                sf_client=sf,
                bedrock_client=MagicMock(),
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
