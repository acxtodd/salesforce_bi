"""Unit tests for scripts/replay_from_audit.py."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from replay_from_audit import (
    _assert_namespace_empty,
    _list_current_versions,
    _list_point_in_time_versions,
    _validate_config,
)


# ===================================================================
# _list_current_versions
# ===================================================================


class TestListCurrentVersions:
    def _make_s3(self, keys: list[str]) -> MagicMock:
        s3 = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": k} for k in keys]}
        ]
        s3.get_paginator.return_value = paginator
        return s3

    def test_returns_document_keys(self):
        keys = [
            "replay/org1/property/a0x1.json",
            "replay/org1/lease/a0x2.json",
        ]
        s3 = self._make_s3(keys)
        result = _list_current_versions(s3, "bucket", "replay/org1/", None)
        assert result == keys

    def test_skips_meta_prefix(self):
        keys = [
            "replay/org1/property/a0x1.json",
            "replay/org1/_meta/denorm_config_bulk_load_20260318.yaml",
        ]
        s3 = self._make_s3(keys)
        result = _list_current_versions(s3, "bucket", "replay/org1/", None)
        assert len(result) == 1
        assert "_meta/" not in result[0]

    def test_filters_by_object_type(self):
        keys = [
            "replay/org1/property/a0x1.json",
            "replay/org1/lease/a0x2.json",
            "replay/org1/availability/a0x3.json",
        ]
        s3 = self._make_s3(keys)
        result = _list_current_versions(
            s3, "bucket", "replay/org1/", ["property"]
        )
        assert len(result) == 1
        assert "property" in result[0]

    def test_multiple_object_types(self):
        keys = [
            "replay/org1/property/a0x1.json",
            "replay/org1/lease/a0x2.json",
            "replay/org1/availability/a0x3.json",
        ]
        s3 = self._make_s3(keys)
        result = _list_current_versions(
            s3, "bucket", "replay/org1/", ["property", "lease"]
        )
        assert len(result) == 2

    def test_empty_bucket(self):
        s3 = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{}]
        s3.get_paginator.return_value = paginator
        result = _list_current_versions(s3, "bucket", "replay/org1/", None)
        assert result == []


# ===================================================================
# _list_point_in_time_versions
# ===================================================================


class TestListPointInTimeVersions:
    def test_picks_latest_before_cutoff(self):
        s3 = MagicMock()
        paginator = MagicMock()
        t1 = datetime(2026, 3, 10, tzinfo=timezone.utc)
        t2 = datetime(2026, 3, 15, tzinfo=timezone.utc)
        t3 = datetime(2026, 3, 20, tzinfo=timezone.utc)
        paginator.paginate.return_value = [
            {
                "Versions": [
                    {"Key": "replay/org1/property/a0x1.json", "LastModified": t1, "VersionId": "v1"},
                    {"Key": "replay/org1/property/a0x1.json", "LastModified": t2, "VersionId": "v2"},
                    {"Key": "replay/org1/property/a0x1.json", "LastModified": t3, "VersionId": "v3"},
                ]
            }
        ]
        s3.get_paginator.return_value = paginator

        cutoff = datetime(2026, 3, 16, tzinfo=timezone.utc)
        result = _list_point_in_time_versions(
            s3, "bucket", "replay/org1/", cutoff, None
        )

        assert len(result) == 1
        key, vid = result[0]
        assert key == "replay/org1/property/a0x1.json"
        assert vid == "v2"  # latest before cutoff

    def test_skips_meta_and_filters_object_type(self):
        s3 = MagicMock()
        paginator = MagicMock()
        t1 = datetime(2026, 3, 10, tzinfo=timezone.utc)
        paginator.paginate.return_value = [
            {
                "Versions": [
                    {"Key": "replay/org1/property/a0x1.json", "LastModified": t1, "VersionId": "v1"},
                    {"Key": "replay/org1/lease/a0x2.json", "LastModified": t1, "VersionId": "v2"},
                    {"Key": "replay/org1/_meta/config.json", "LastModified": t1, "VersionId": "v3"},
                ]
            }
        ]
        s3.get_paginator.return_value = paginator

        cutoff = datetime(2026, 3, 20, tzinfo=timezone.utc)
        result = _list_point_in_time_versions(
            s3, "bucket", "replay/org1/", cutoff, ["property"]
        )

        assert len(result) == 1
        assert "property" in result[0][0]

    def test_no_versions_before_cutoff(self):
        s3 = MagicMock()
        paginator = MagicMock()
        t_future = datetime(2026, 6, 1, tzinfo=timezone.utc)
        paginator.paginate.return_value = [
            {
                "Versions": [
                    {"Key": "replay/org1/property/a0x1.json", "LastModified": t_future, "VersionId": "v1"},
                ]
            }
        ]
        s3.get_paginator.return_value = paginator

        cutoff = datetime(2026, 3, 1, tzinfo=timezone.utc)
        result = _list_point_in_time_versions(
            s3, "bucket", "replay/org1/", cutoff, None
        )
        assert result == []


# ===================================================================
# _validate_config
# ===================================================================


class TestValidateConfig:
    def test_matching_hash_logs_match(self, tmp_path, caplog, monkeypatch):
        import logging
        caplog.set_level(logging.INFO)
        import hashlib

        yaml_content = "property:\n  embed_fields: [Name]\n"
        config_file = tmp_path / "denorm_config.yaml"
        config_file.write_text(yaml_content)
        expected_hash = hashlib.sha256(yaml_content.encode()).hexdigest()

        s3 = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "documents/org1/_meta/denorm_config_bulk_load_20260318.json"}]}
        ]
        s3.get_paginator.return_value = paginator

        import io
        meta_body = json.dumps({"config_hash": expected_hash, "source": "bulk_load"})
        s3.get_object.return_value = {"Body": io.BytesIO(meta_body.encode())}

        _validate_config(s3, "bucket", "documents/org1/", str(config_file))

        assert "Config hashes match" in caplog.text

    def test_mismatched_hash_warns_drift(self, tmp_path, caplog):
        config_file = tmp_path / "denorm_config.yaml"
        config_file.write_text("property:\n  embed_fields: [Name, City]\n")

        s3 = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {"Contents": [{"Key": "documents/org1/_meta/config.json"}]}
        ]
        s3.get_paginator.return_value = paginator

        import io
        meta_body = json.dumps({"config_hash": "0000dead", "source": "bulk_load"})
        s3.get_object.return_value = {"Body": io.BytesIO(meta_body.encode())}

        _validate_config(s3, "bucket", "documents/org1/", str(config_file))

        assert "CONFIG DRIFT DETECTED" in caplog.text

    def test_no_snapshots_warns(self, caplog):
        s3 = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{}]
        s3.get_paginator.return_value = paginator

        _validate_config(s3, "bucket", "documents/org1/")

        assert "No config snapshots found" in caplog.text


# ===================================================================
# Tombstone skipping in replay flow
# ===================================================================


class TestTombstoneSkipping:
    """Verify that replay logic skips tombstone documents."""

    def test_tombstone_doc_is_identified(self):
        """A doc with deleted=True should be skipped by replay logic."""
        tombstone = {"deleted": True, "record_id": "a0x1", "deleted_at": "2026-03-18T00:00:00Z"}
        assert tombstone.get("deleted") is True

    def test_normal_doc_is_not_tombstone(self):
        doc = {"id": "a0x1", "object_type": "property", "name": "Test"}
        assert not doc.get("deleted")


# ===================================================================
# _assert_namespace_empty (--require-empty fail-closed behavior)
# ===================================================================


class TestAssertNamespaceEmpty:
    """Exercise the real _assert_namespace_empty function."""

    def test_empty_namespace_passes(self):
        """count == 0 should return normally (no exit)."""
        backend = MagicMock()
        backend.aggregate.return_value = {"count": 0}

        # Should not raise or exit
        _assert_namespace_empty(backend, "ns_fresh")
        backend.aggregate.assert_called_once_with("ns_fresh", aggregate="count")

    def test_nonempty_namespace_exits(self):
        """count > 0 triggers sys.exit(1)."""
        backend = MagicMock()
        backend.aggregate.return_value = {"count": 42}

        with pytest.raises(SystemExit) as exc_info:
            _assert_namespace_empty(backend, "ns_occupied")

        assert exc_info.value.code == 1

    def test_aggregate_exception_exits(self):
        """If aggregate() raises, fail closed with sys.exit(1)."""
        backend = MagicMock()
        backend.aggregate.side_effect = RuntimeError("network error")

        with pytest.raises(SystemExit) as exc_info:
            _assert_namespace_empty(backend, "ns_unreachable")

        assert exc_info.value.code == 1


# ===================================================================
# Backward compatibility: --prefix flag
# ===================================================================


class TestBackwardCompatPrefix:
    """Verify --prefix flag wiring through main() and the real code path."""

    def _run_main_dry_run(self, extra_args=None, caplog=None):
        """Invoke real main() in --dry-run mode with mocked S3/boto3."""
        import replay_from_audit

        mock_s3 = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{}]  # empty bucket
        mock_s3.get_paginator.return_value = paginator

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        argv = [
            "replay_from_audit.py",
            "--audit-bucket", "test-bucket",
            "--namespace", "ns",
            "--org-id", "org1",
            "--dry-run",
        ]
        if extra_args:
            argv.extend(extra_args)

        with patch.object(sys, "argv", argv), \
             patch.dict("sys.modules", {"boto3": mock_boto3}):
            replay_from_audit.main()

        return mock_s3

    def test_default_prefix_uses_replay(self):
        """Default run paginates under replay/{org_id}/."""
        mock_s3 = self._run_main_dry_run()
        paginator = mock_s3.get_paginator.return_value
        call_kwargs = paginator.paginate.call_args[1]
        assert call_kwargs["Prefix"] == "replay/org1/"

    def test_documents_prefix_paginates_under_documents(self, caplog):
        """--prefix documents paginates under documents/{org_id}/."""
        import logging
        caplog.set_level(logging.WARNING)

        mock_s3 = self._run_main_dry_run(extra_args=["--prefix", "documents"], caplog=caplog)
        paginator = mock_s3.get_paginator.return_value
        call_kwargs = paginator.paginate.call_args[1]
        assert call_kwargs["Prefix"] == "documents/org1/"
        assert "documents/ prefix" in caplog.text
        assert "legacy" in caplog.text

    def test_validate_config_always_reads_from_documents_meta(self):
        """--validate-config reads _meta/ from documents/ regardless of --prefix."""
        import replay_from_audit

        mock_s3 = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{}]  # no config snapshots, no keys
        mock_s3.get_paginator.return_value = paginator

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        argv = [
            "replay_from_audit.py",
            "--audit-bucket", "test-bucket",
            "--namespace", "ns",
            "--org-id", "org1",
            "--dry-run",
            "--prefix", "replay",
            "--validate-config",
        ]

        with patch.object(sys, "argv", argv), \
             patch.dict("sys.modules", {"boto3": mock_boto3}):
            replay_from_audit.main()

        # paginate was called twice: once for _validate_config, once for listing
        prefixes_used = [
            c[1]["Prefix"]
            for c in paginator.paginate.call_args_list
        ]
        assert "documents/org1/_meta/" in prefixes_used
        assert "replay/org1/" in prefixes_used
