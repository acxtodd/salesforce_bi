"""Unit tests for lib/audit_writer.py."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.audit_writer import (
    AuditingBackend,
    AuditStats,
    write_audit_document,
    write_audit_tombstone,
    write_config_snapshot,
)


# ===================================================================
# write_audit_document
# ===================================================================


class TestWriteAuditDocument:
    def test_correct_key_and_body(self):
        s3 = MagicMock()
        doc = {"id": "a0x1", "object_type": "property", "name": "Test"}
        result = write_audit_document(s3, "my-bucket", "org123", doc)

        assert result is True
        s3.put_object.assert_called_once()
        kwargs = s3.put_object.call_args[1]
        assert kwargs["Bucket"] == "my-bucket"
        assert kwargs["Key"] == "documents/org123/property/a0x1.json"
        body = json.loads(kwargs["Body"])
        assert body["id"] == "a0x1"
        assert body["object_type"] == "property"
        assert body["name"] == "Test"

    def test_best_effort_returns_false_on_error(self):
        s3 = MagicMock()
        s3.put_object.side_effect = RuntimeError("S3 down")
        doc = {"id": "a0x1", "object_type": "property"}
        result = write_audit_document(s3, "bucket", "org", doc)

        assert result is False

    def test_missing_fields_use_unknown(self):
        s3 = MagicMock()
        doc = {"some_field": "value"}
        write_audit_document(s3, "bucket", "org", doc)

        key = s3.put_object.call_args[1]["Key"]
        assert key == "documents/org/unknown/unknown.json"


# ===================================================================
# write_audit_tombstone
# ===================================================================


class TestWriteAuditTombstone:
    def test_writes_per_record(self):
        s3 = MagicMock()
        ok, failed = write_audit_tombstone(
            s3, "bucket", "org123", "property", ["a0x1", "a0x2"]
        )

        assert ok == 2
        assert failed == 0
        assert s3.put_object.call_count == 2

        keys = [c[1]["Key"] for c in s3.put_object.call_args_list]
        assert "documents/org123/property/a0x1.json" in keys
        assert "documents/org123/property/a0x2.json" in keys

        body = json.loads(s3.put_object.call_args_list[0][1]["Body"])
        assert body["deleted"] is True
        assert "deleted_at" in body

    def test_partial_failure(self):
        s3 = MagicMock()
        s3.put_object.side_effect = [None, RuntimeError("fail")]
        ok, failed = write_audit_tombstone(
            s3, "bucket", "org", "lease", ["r1", "r2"]
        )
        assert ok == 1
        assert failed == 1


# ===================================================================
# write_config_snapshot
# ===================================================================


class TestWriteConfigSnapshot:
    def test_content(self):
        s3 = MagicMock()
        yaml_str = "property:\n  embed_fields: [Name]\n"
        write_config_snapshot(
            s3, "bucket", "org123", {"property": {}}, yaml_str, "bulk_load"
        )

        assert s3.put_object.call_count == 2
        calls = {c[1]["Key"].rsplit(".", 1)[-1]: c[1] for c in s3.put_object.call_args_list}

        # YAML file
        assert "yaml" in calls
        assert calls["yaml"]["Body"] == yaml_str

        # JSON metadata
        assert "json" in calls
        meta = json.loads(calls["json"]["Body"])
        assert meta["source"] == "bulk_load"
        assert "config_hash" in meta
        assert len(meta["config_hash"]) == 64  # SHA-256 hex
        assert "timestamp" in meta

    def test_best_effort_on_failure(self):
        s3 = MagicMock()
        s3.put_object.side_effect = RuntimeError("fail")
        # Should not raise
        write_config_snapshot(s3, "bucket", "org", {}, "yaml", "cdc_cold_start")


# ===================================================================
# AuditingBackend
# ===================================================================


class TestAuditingBackend:
    def _make_backend(self, s3_ok=True):
        inner = MagicMock()
        s3 = MagicMock()
        if not s3_ok:
            s3.put_object.side_effect = RuntimeError("S3 down")
        ab = AuditingBackend(inner, s3, "audit-bucket", "org123")
        return ab, inner, s3

    def test_upsert_writes_then_audits(self):
        ab, inner, s3 = self._make_backend()
        docs = [
            {"id": "a0x1", "object_type": "property", "name": "P1"},
            {"id": "a0x2", "object_type": "property", "name": "P2"},
        ]

        ab.upsert("ns", documents=docs, schema={"text": {}})

        inner.upsert.assert_called_once_with(
            "ns", documents=docs, distance_metric="cosine_distance", schema={"text": {}}
        )
        assert s3.put_object.call_count == 2

    def test_audit_failure_does_not_break_upsert(self):
        ab, inner, s3 = self._make_backend(s3_ok=False)
        docs = [{"id": "a0x1", "object_type": "property"}]

        # Should not raise
        ab.upsert("ns", documents=docs)

        inner.upsert.assert_called_once()

    def test_stats_counting(self):
        inner = MagicMock()
        s3 = MagicMock()
        # First call succeeds, second fails
        s3.put_object.side_effect = [None, RuntimeError("fail")]
        ab = AuditingBackend(inner, s3, "bucket", "org")

        docs = [
            {"id": "a0x1", "object_type": "property"},
            {"id": "a0x2", "object_type": "property"},
        ]
        ab.upsert("ns", documents=docs)

        assert ab.stats.audit_ok == 1
        assert ab.stats.audit_failed == 1

    def test_delete_delegates_only(self):
        ab, inner, s3 = self._make_backend()

        ab.delete("ns", ids=["a0x1", "a0x2"])

        inner.delete.assert_called_once_with("ns", ids=["a0x1", "a0x2"])
        s3.put_object.assert_not_called()

    def test_search_delegates(self):
        ab, inner, _ = self._make_backend()
        inner.search.return_value = [{"id": "a0x1"}]

        result = ab.search("ns", vector=[0.1], top_k=5)

        inner.search.assert_called_once_with("ns", vector=[0.1], top_k=5)
        assert result == [{"id": "a0x1"}]

    def test_aggregate_delegates(self):
        ab, inner, _ = self._make_backend()
        inner.aggregate.return_value = {"count": 42}

        result = ab.aggregate("ns", aggregate="count")

        assert result == {"count": 42}

    def test_warm_delegates(self):
        ab, inner, _ = self._make_backend()
        ab.warm("ns")
        inner.warm.assert_called_once_with("ns")

    def test_emit_audit_metrics(self):
        ab, _, _ = self._make_backend()
        ab.stats.audit_ok = 10
        ab.stats.audit_failed = 2
        cw = MagicMock()

        ab.emit_audit_metrics(cw)

        cw.put_metric_data.assert_called_once()
        kwargs = cw.put_metric_data.call_args[1]
        assert kwargs["Namespace"] == "SalesforceAISearch/CDCSync"
        metrics = {m["MetricName"]: m["Value"] for m in kwargs["MetricData"]}
        assert metrics["AuditWriteSuccess"] == 10
        assert metrics["AuditWriteFailure"] == 2
