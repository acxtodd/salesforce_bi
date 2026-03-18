"""Unit tests for lambda/cdc_sync/index.py — all external deps mocked."""

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root + lambda to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))

from lib.audit_writer import AuditingBackend

from cdc_sync.index import (
    CDC_ENTITY_MAP,
    CDCEvent,
    _embed_single,
    _emit_freshness_metrics,
    _extract_s3_coordinates,
    _process_cdc_event,
    _send_to_dlq,
    parse_event,
    parse_eventbridge_s3_cdc,
)


# ===================================================================
# Helpers
# ===================================================================


def _make_s3_cdc_payload(
    entity_name: str = "ascendix__Property__ChangeEvent",
    change_type: str = "CREATE",
    record_ids: list[str] | None = None,
    commit_timestamp: int = 1700000000000,
) -> dict:
    """Build a raw CDC payload as stored in S3."""
    return {
        "ChangeEventHeader": {
            "entityName": entity_name,
            "changeType": change_type,
            "recordIds": record_ids or ["a0x000000000001AAA"],
            "commitTimestamp": commit_timestamp,
        },
        "Name": "Test Property",
        "ascendix__City__c": "Dallas",
    }


def _make_s3_event(
    bucket: str = "salesforce-cdc-bucket",
    key: str = "cdc/ascendix__Property__ChangeEvent/2025/11/13/14/event-001.json",
) -> dict:
    """Build an EventBridge-style event pointing to S3."""
    return {
        "bucket": bucket,
        "key": key,
        "eventTime": "2025-11-13T14:30:00Z",
    }


def _mock_s3_get_object(payload: dict) -> MagicMock:
    """Create a mock s3_client.get_object that returns the given payload."""
    s3_client = MagicMock()
    body = io.BytesIO(json.dumps(payload).encode("utf-8"))
    s3_client.get_object.return_value = {"Body": body}
    return s3_client


def _make_bedrock_mock(dimension: int = 1024) -> MagicMock:
    """Create a mock Bedrock client returning deterministic embeddings."""
    mock = MagicMock()

    def invoke_model(**kwargs):
        body = json.loads(kwargs["body"])
        dim = body["dimensions"]
        embedding = [0.1] * dim
        response_body = json.dumps({"embedding": embedding})
        return {"body": io.BytesIO(response_body.encode())}

    mock.invoke_model.side_effect = invoke_model
    return mock


# Minimal denorm config for tests
DENORM_CONFIG = {
    "ascendix__Property__c": {
        "embed_fields": ["Name", "ascendix__City__c"],
        "metadata_fields": ["ascendix__TotalBuildingArea__c"],
        "parents": {},
    },
    "ascendix__Lease__c": {
        "embed_fields": ["Name"],
        "metadata_fields": [],
        "parents": {},
    },
    "ascendix__Availability__c": {
        "embed_fields": ["Name"],
        "metadata_fields": [],
        "parents": {},
    },
}

SALESFORCE_ORG_ID = "00Ddl000003yx57EAA"
NAMESPACE = f"org_{SALESFORCE_ORG_ID}"
DLQ_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/cdc-dlq"


def _make_sf_client_mock(
    query_records: list[dict] | None = None,
) -> MagicMock:
    """Create a mock SalesforceClient."""
    sf = MagicMock()
    sf.query.return_value = {"records": query_records or []}
    sf.describe.return_value = {"fields": []}
    return sf


# ===================================================================
# parse_eventbridge_s3_cdc
# ===================================================================


class TestParseEventbridgeS3CDC:
    def test_create_event(self):
        payload = _make_s3_cdc_payload(
            change_type="CREATE",
            record_ids=["a0x1"],
        )
        s3_client = _mock_s3_get_object(payload)
        event = _make_s3_event()

        events = parse_eventbridge_s3_cdc(event, s3_client)

        assert len(events) == 1
        assert events[0].object_name == "ascendix__Property__c"
        assert events[0].change_type == "CREATE"
        assert events[0].record_ids == ["a0x1"]
        assert events[0].commit_timestamp == 1700000000000
        assert events[0].raw == payload

    def test_delete_event(self):
        payload = _make_s3_cdc_payload(
            change_type="DELETE",
            record_ids=["a0x2", "a0x3"],
        )
        s3_client = _mock_s3_get_object(payload)
        event = _make_s3_event()

        events = parse_eventbridge_s3_cdc(event, s3_client)

        assert len(events) == 1
        assert events[0].change_type == "DELETE"
        assert events[0].record_ids == ["a0x2", "a0x3"]

    def test_unknown_entity_returns_empty(self):
        payload = _make_s3_cdc_payload(entity_name="UnknownObject__ChangeEvent")
        s3_client = _mock_s3_get_object(payload)
        event = _make_s3_event(
            key="cdc/UnknownObject__ChangeEvent/2025/11/13/14/event.json"
        )

        events = parse_eventbridge_s3_cdc(event, s3_client)

        assert events == []

    def test_undelete_event(self):
        payload = _make_s3_cdc_payload(change_type="UNDELETE", record_ids=["a0x4"])
        s3_client = _mock_s3_get_object(payload)
        event = _make_s3_event()

        events = parse_eventbridge_s3_cdc(event, s3_client)

        assert events[0].change_type == "UNDELETE"

    def test_non_namespaced_entity(self):
        """Property__ChangeEvent (without ascendix__ prefix) should map correctly."""
        payload = _make_s3_cdc_payload(
            entity_name="Property__ChangeEvent", record_ids=["a0x5"]
        )
        s3_client = _mock_s3_get_object(payload)
        event = _make_s3_event(key="cdc/Property__ChangeEvent/2025/11/13/event.json")

        events = parse_eventbridge_s3_cdc(event, s3_client)

        assert len(events) == 1
        assert events[0].object_name == "ascendix__Property__c"

    def test_raw_eventbridge_s3_shape(self):
        """Raw EventBridge S3 notification (nested detail.bucket.name)."""
        payload = _make_s3_cdc_payload(record_ids=["a0x6"])
        s3_client = _mock_s3_get_object(payload)
        raw_event = {
            "source": "aws.s3",
            "detail-type": "Object Created",
            "detail": {
                "bucket": {"name": "salesforce-cdc-bucket"},
                "object": {"key": "cdc/ascendix__Property__ChangeEvent/2025/11/13/14/event-001.json"},
            },
            "time": "2025-11-13T14:30:00Z",
        }

        events = parse_eventbridge_s3_cdc(raw_event, s3_client)

        assert len(events) == 1
        assert events[0].record_ids == ["a0x6"]
        s3_client.get_object.assert_called_once_with(
            Bucket="salesforce-cdc-bucket",
            Key="cdc/ascendix__Property__ChangeEvent/2025/11/13/14/event-001.json",
        )


# ===================================================================
# _extract_s3_coordinates
# ===================================================================


class TestExtractS3Coordinates:
    def test_flat_shape(self):
        bucket, key = _extract_s3_coordinates({"bucket": "b", "key": "k"})
        assert bucket == "b"
        assert key == "k"

    def test_nested_eventbridge_shape(self):
        event = {
            "detail": {
                "bucket": {"name": "my-bucket"},
                "object": {"key": "cdc/Property/event.json"},
            }
        }
        bucket, key = _extract_s3_coordinates(event)
        assert bucket == "my-bucket"
        assert key == "cdc/Property/event.json"

    def test_unknown_shape_raises(self):
        with pytest.raises(ValueError, match="Cannot extract S3 coordinates"):
            _extract_s3_coordinates({"foo": "bar"})


# ===================================================================
# parse_event routing
# ===================================================================


class TestParseEvent:
    def test_s3_event_routes_to_eventbridge_adapter(self):
        payload = _make_s3_cdc_payload()
        s3_client = _mock_s3_get_object(payload)
        event = _make_s3_event()

        events = parse_event(event, s3_client)

        assert len(events) == 1
        assert events[0].object_name == "ascendix__Property__c"

    def test_raw_eventbridge_s3_routes_to_adapter(self):
        """Raw EventBridge S3 shape (nested detail) routes correctly."""
        payload = _make_s3_cdc_payload()
        s3_client = _mock_s3_get_object(payload)
        raw_event = {
            "detail": {
                "bucket": {"name": "b"},
                "object": {"key": "cdc/ascendix__Property__ChangeEvent/event.json"},
            }
        }

        events = parse_event(raw_event, s3_client)
        assert len(events) == 1
        assert events[0].object_name == "ascendix__Property__c"

    def test_unknown_shape_raises_value_error(self):
        with pytest.raises(ValueError, match="Unrecognized event shape"):
            parse_event({"foo": "bar"}, MagicMock())

    def test_pubsub_event_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            parse_event({"pubsub": {}}, MagicMock())


# ===================================================================
# Sync pipeline: _process_cdc_event
# ===================================================================


class TestProcessCDCEvent:
    """Tests for the per-event sync pipeline."""

    def _make_deps(
        self,
        sf_records: list[dict] | None = None,
    ) -> dict:
        """Build keyword deps for _process_cdc_event."""
        sf = _make_sf_client_mock(sf_records)
        return {
            "sf_client": sf,
            "bedrock_client": _make_bedrock_mock(),
            "backend": MagicMock(),
            "cloudwatch_client": MagicMock(),
            "sqs_client": MagicMock(),
            "namespace": NAMESPACE,
            "salesforce_org_id": SALESFORCE_ORG_ID,
            "denorm_config": DENORM_CONFIG,
            "dlq_url": DLQ_URL,
        }

    def test_create_happy_path(self):
        """CREATE event: fetch, denorm, embed, upsert."""
        record = {
            "Id": "a0x1",
            "LastModifiedDate": "2025-03-01T00:00:00Z",
            "Name": "Test Property",
            "ascendix__City__c": "Dallas",
            "ascendix__TotalBuildingArea__c": 50000,
        }
        deps = self._make_deps(sf_records=[record])
        cdc = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="CREATE",
            record_ids=["a0x1"],
            commit_timestamp=1700000000000,
        )

        _process_cdc_event(cdc, **deps)

        # Verify upsert was called
        backend = deps["backend"]
        backend.upsert.assert_called_once()
        call_kwargs = backend.upsert.call_args
        assert call_kwargs[0][0] == NAMESPACE
        docs = call_kwargs[1]["documents"]
        assert len(docs) == 1
        assert docs[0]["id"] == "a0x1"
        assert docs[0]["object_type"] == "property"
        # CDC metadata fields NOT in document
        assert "_cdc_change_type" not in docs[0]
        assert "_cdc_commit_timestamp" not in docs[0]
        # Freshness metric emitted
        deps["cloudwatch_client"].put_metric_data.assert_called_once()

    def test_update_same_as_create(self):
        """UPDATE event uses the same fetch+denorm+embed+upsert pipeline."""
        record = {
            "Id": "a0x1",
            "LastModifiedDate": "2025-03-01T00:00:00Z",
            "Name": "Updated Property",
            "ascendix__City__c": "Houston",
        }
        deps = self._make_deps(sf_records=[record])
        cdc = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="UPDATE",
            record_ids=["a0x1"],
            commit_timestamp=1700000000000,
        )

        _process_cdc_event(cdc, **deps)

        deps["backend"].upsert.assert_called_once()

    def test_delete_calls_backend_delete(self):
        """DELETE event calls backend.delete with correct IDs."""
        deps = self._make_deps()
        cdc = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="DELETE",
            record_ids=["a0x1", "a0x2"],
            commit_timestamp=1700000000000,
        )

        _process_cdc_event(cdc, **deps)

        deps["backend"].delete.assert_called_once_with(
            NAMESPACE, ids=["a0x1", "a0x2"]
        )
        # Should NOT call upsert for DELETE
        deps["backend"].upsert.assert_not_called()

    def test_undelete_treated_as_create(self):
        """UNDELETE event should fetch, denorm, embed, upsert (same as CREATE)."""
        record = {
            "Id": "a0x1",
            "LastModifiedDate": "2025-03-01T00:00:00Z",
            "Name": "Undeleted Property",
            "ascendix__City__c": "Austin",
        }
        deps = self._make_deps(sf_records=[record])
        cdc = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="UNDELETE",
            record_ids=["a0x1"],
            commit_timestamp=1700000000000,
        )

        _process_cdc_event(cdc, **deps)

        deps["backend"].upsert.assert_called_once()

    def test_batch_of_three_events(self):
        """Multiple record IDs in one event = multiple SF queries + upserts."""
        record_template = {
            "LastModifiedDate": "2025-03-01T00:00:00Z",
            "Name": "Prop",
            "ascendix__City__c": "Dallas",
        }
        # Each query returns one record (different IDs)
        records = [
            {"Id": f"a0x{i}", **record_template} for i in range(3)
        ]
        deps = self._make_deps()
        # Return one record per query call
        deps["sf_client"].query.side_effect = [
            {"records": [records[0]]},
            {"records": [records[1]]},
            {"records": [records[2]]},
        ]
        cdc = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="CREATE",
            record_ids=["a0x0", "a0x1", "a0x2"],
            commit_timestamp=1700000000000,
        )

        _process_cdc_event(cdc, **deps)

        assert deps["backend"].upsert.call_count == 3

    def test_unknown_entity_skipped(self):
        """Object not in denorm config is skipped without error."""
        deps = self._make_deps()
        cdc = CDCEvent(
            object_name="Unknown__c",
            change_type="CREATE",
            record_ids=["a0x1"],
            commit_timestamp=1700000000000,
        )

        _process_cdc_event(cdc, **deps)

        deps["backend"].upsert.assert_not_called()
        deps["backend"].delete.assert_not_called()
        deps["sqs_client"].send_message.assert_not_called()

    def test_sf_fetch_failure_sends_to_dlq_and_raises(self):
        """Salesforce query failure sends event to DLQ and re-raises."""
        deps = self._make_deps()
        deps["sf_client"].query.side_effect = RuntimeError("SF unavailable")
        cdc = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="CREATE",
            record_ids=["a0x1"],
            commit_timestamp=1700000000000,
        )

        with pytest.raises(RuntimeError, match="SF unavailable"):
            _process_cdc_event(cdc, **deps)

        # DLQ should be called
        deps["sqs_client"].send_message.assert_called_once()
        dlq_body = json.loads(
            deps["sqs_client"].send_message.call_args[1]["MessageBody"]
        )
        assert dlq_body["object_name"] == "ascendix__Property__c"
        assert "SF unavailable" in dlq_body["error"]

    def test_embed_failure_sends_to_dlq_and_raises(self):
        """Bedrock embed failure sends event to DLQ and re-raises."""
        record = {
            "Id": "a0x1",
            "LastModifiedDate": "2025-03-01T00:00:00Z",
            "Name": "Test Property",
            "ascendix__City__c": "Dallas",
        }
        deps = self._make_deps(sf_records=[record])
        deps["bedrock_client"].invoke_model.side_effect = RuntimeError(
            "Bedrock unavailable"
        )
        cdc = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="CREATE",
            record_ids=["a0x1"],
            commit_timestamp=1700000000000,
        )

        with pytest.raises(RuntimeError, match="Bedrock unavailable"):
            _process_cdc_event(cdc, **deps)

        # DLQ should be called
        deps["sqs_client"].send_message.assert_called_once()
        dlq_body = json.loads(
            deps["sqs_client"].send_message.call_args[1]["MessageBody"]
        )
        assert "Bedrock unavailable" in dlq_body["error"]

    def test_freshness_metrics_emitted(self):
        """CloudWatch put_metric_data is called with correct namespace."""
        deps = self._make_deps()
        cdc = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="DELETE",
            record_ids=["a0x1"],
            commit_timestamp=1700000000000,
        )

        _process_cdc_event(cdc, **deps)

        cw = deps["cloudwatch_client"]
        cw.put_metric_data.assert_called_once()
        call_kwargs = cw.put_metric_data.call_args[1]
        assert call_kwargs["Namespace"] == "SalesforceAISearch/CDCSync"
        metric = call_kwargs["MetricData"][0]
        assert metric["MetricName"] == "CDCSyncLag"
        assert metric["Unit"] == "Milliseconds"
        dims = {d["Name"]: d["Value"] for d in metric["Dimensions"]}
        assert dims["SObject"] == "ascendix__Property__c"


# ===================================================================
# CDCEvent dataclass
# ===================================================================


class TestCDCEvent:
    def test_fields(self):
        evt = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="CREATE",
            record_ids=["a0x1"],
            commit_timestamp=1700000000000,
        )
        assert evt.object_name == "ascendix__Property__c"
        assert evt.change_type == "CREATE"
        assert evt.record_ids == ["a0x1"]
        assert evt.commit_timestamp == 1700000000000
        assert evt.raw == {}

    def test_raw_default(self):
        evt = CDCEvent(
            object_name="x",
            change_type="UPDATE",
            record_ids=[],
            commit_timestamp=0,
        )
        assert evt.raw == {}

    def test_raw_custom(self):
        raw = {"key": "value"}
        evt = CDCEvent(
            object_name="x",
            change_type="UPDATE",
            record_ids=[],
            commit_timestamp=0,
            raw=raw,
        )
        assert evt.raw == raw


# ===================================================================
# CDC_ENTITY_MAP
# ===================================================================


class TestCDCEntityMap:
    def test_all_namespaced_entities_present(self):
        assert "ascendix__Property__ChangeEvent" in CDC_ENTITY_MAP
        assert "ascendix__Lease__ChangeEvent" in CDC_ENTITY_MAP
        assert "ascendix__Availability__ChangeEvent" in CDC_ENTITY_MAP

    def test_non_namespaced_entities_present(self):
        assert "Property__ChangeEvent" in CDC_ENTITY_MAP
        assert "Lease__ChangeEvent" in CDC_ENTITY_MAP
        assert "Availability__ChangeEvent" in CDC_ENTITY_MAP

    def test_mapping_values(self):
        assert CDC_ENTITY_MAP["ascendix__Property__ChangeEvent"] == "ascendix__Property__c"
        assert CDC_ENTITY_MAP["Property__ChangeEvent"] == "ascendix__Property__c"
        assert CDC_ENTITY_MAP["ascendix__Lease__ChangeEvent"] == "ascendix__Lease__c"
        assert CDC_ENTITY_MAP["Lease__ChangeEvent"] == "ascendix__Lease__c"


# ===================================================================
# _embed_single
# ===================================================================


class TestEmbedSingle:
    def test_returns_embedding_vector(self):
        bedrock = _make_bedrock_mock()
        vector = _embed_single(bedrock, "test text")
        assert len(vector) == 1024
        assert all(isinstance(v, float) for v in vector)


# ===================================================================
# _send_to_dlq
# ===================================================================


class TestSendToDLQ:
    def test_sends_message(self):
        sqs = MagicMock()
        evt = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="CREATE",
            record_ids=["a0x1"],
            commit_timestamp=0,
            raw={"foo": "bar"},
        )

        _send_to_dlq(sqs, DLQ_URL, evt, RuntimeError("test error"))

        sqs.send_message.assert_called_once()
        call_kwargs = sqs.send_message.call_args[1]
        assert call_kwargs["QueueUrl"] == DLQ_URL
        body = json.loads(call_kwargs["MessageBody"])
        assert body["object_name"] == "ascendix__Property__c"
        assert body["error"] == "test error"
        assert body["raw"] == {"foo": "bar"}

    def test_sqs_failure_does_not_raise(self):
        """DLQ send failure is swallowed (logged, not raised)."""
        sqs = MagicMock()
        sqs.send_message.side_effect = RuntimeError("SQS down")
        evt = CDCEvent(
            object_name="x",
            change_type="CREATE",
            record_ids=[],
            commit_timestamp=0,
        )

        # Should not raise
        _send_to_dlq(sqs, DLQ_URL, evt, RuntimeError("original"))


# ===================================================================
# Audit trail integration
# ===================================================================


class TestAuditIntegration:
    """Tests for audit trail wiring in CDC sync."""

    def _make_deps(
        self,
        sf_records: list[dict] | None = None,
        audit_bucket: str = "",
    ) -> dict:
        sf = _make_sf_client_mock(sf_records)
        deps = {
            "sf_client": sf,
            "bedrock_client": _make_bedrock_mock(),
            "backend": MagicMock(),
            "cloudwatch_client": MagicMock(),
            "sqs_client": MagicMock(),
            "namespace": NAMESPACE,
            "salesforce_org_id": SALESFORCE_ORG_ID,
            "denorm_config": DENORM_CONFIG,
            "dlq_url": DLQ_URL,
            "audit_bucket": audit_bucket,
            "audit_s3_client": MagicMock() if audit_bucket else None,
        }
        return deps

    def test_upsert_audits_via_wrapper(self):
        """AuditingBackend writes to S3 on upsert."""
        inner = MagicMock()
        s3 = MagicMock()
        ab = AuditingBackend(inner, s3, "audit-bucket", SALESFORCE_ORG_ID)
        docs = [{"id": "a0x1", "object_type": "property", "name": "Test"}]

        ab.upsert(NAMESPACE, documents=docs, schema={"text": {}})

        inner.upsert.assert_called_once()
        s3.put_object.assert_called_once()
        assert ab.stats.audit_ok == 1
        assert ab.stats.audit_failed == 0

    def test_delete_writes_tombstone(self):
        """DELETE event writes tombstone to S3 when audit_bucket is set."""
        deps = self._make_deps(audit_bucket="audit-bucket")
        # Wrap backend with AuditingBackend so stats are tracked
        inner_backend = deps["backend"]
        ab = AuditingBackend(
            inner_backend, deps["audit_s3_client"], "audit-bucket", SALESFORCE_ORG_ID
        )
        deps["backend"] = ab
        cdc = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="DELETE",
            record_ids=["a0x1", "a0x2"],
            commit_timestamp=1700000000000,
        )

        _process_cdc_event(cdc, **deps)

        inner_backend.delete.assert_called_once()
        # Tombstone writes: one per record_id
        audit_s3 = deps["audit_s3_client"]
        assert audit_s3.put_object.call_count == 2
        keys = [c[1]["Key"] for c in audit_s3.put_object.call_args_list]
        assert any("a0x1.json" in k for k in keys)
        assert any("a0x2.json" in k for k in keys)
        # Tombstone outcomes are rolled into the backend stats
        assert ab.stats.audit_ok == 2
        assert ab.stats.audit_failed == 0

    def test_audit_failure_counted_not_raised(self):
        """Mock S3 to raise; verify upsert succeeds and audit_failed incremented."""
        inner = MagicMock()
        s3 = MagicMock()
        s3.put_object.side_effect = RuntimeError("S3 down")
        ab = AuditingBackend(inner, s3, "bucket", "org")
        docs = [{"id": "a0x1", "object_type": "property"}]

        ab.upsert("ns", documents=docs)

        inner.upsert.assert_called_once()
        assert ab.stats.audit_ok == 0
        assert ab.stats.audit_failed == 1

    def test_no_audit_when_bucket_empty(self):
        """When audit_bucket is empty, no tombstone writes on DELETE."""
        deps = self._make_deps(audit_bucket="")
        cdc = CDCEvent(
            object_name="ascendix__Property__c",
            change_type="DELETE",
            record_ids=["a0x1"],
            commit_timestamp=1700000000000,
        )

        _process_cdc_event(cdc, **deps)

        deps["backend"].delete.assert_called_once()
        # No audit_s3_client means no S3 writes
        assert deps["audit_s3_client"] is None

    def test_config_snapshot_on_cold_start(self):
        """Verify _meta/ write happens via write_config_snapshot."""
        from lib.audit_writer import write_config_snapshot

        s3 = MagicMock()
        write_config_snapshot(
            s3, "audit-bucket", SALESFORCE_ORG_ID,
            DENORM_CONFIG, "raw_yaml_content", "cdc_cold_start",
        )

        assert s3.put_object.call_count == 2
        keys = [c[1]["Key"] for c in s3.put_object.call_args_list]
        assert any("_meta/" in k and ".yaml" in k for k in keys)
        assert any("_meta/" in k and ".json" in k for k in keys)
