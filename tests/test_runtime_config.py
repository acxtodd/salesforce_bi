"""Tests for runtime config loading and fallback order."""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import yaml

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from lib.runtime_config import RuntimeConfigLoader, extract_denorm_config


class _FakeS3:
    def __init__(self, artifact: dict) -> None:
        self.artifact = artifact

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        return {"Body": BytesIO(yaml.safe_dump(self.artifact).encode("utf-8"))}


class _FakeSSM:
    def __init__(self, version_id: str) -> None:
        self.version_id = version_id

    def get_parameter(self, *, Name: str) -> dict:
        return {"Parameter": {"Value": self.version_id}}


def test_runtime_loader_prefers_active_s3_artifact(tmp_path: Path):
    artifact = {
        "version_id": "20260324T010203Z-abc123def456",
        "denorm_config": {"ascendix__Deal__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}}},
    }
    loader = RuntimeConfigLoader(
        s3_client=_FakeS3(artifact),
        ssm_client=_FakeSSM(artifact["version_id"]),
        bucket="config-bucket",
        cache_dir=str(tmp_path / "cache"),
    )

    loaded = loader.load("00DTEST")
    assert loaded["version_id"] == artifact["version_id"]
    assert extract_denorm_config(loaded)["ascendix__Deal__c"]["embed_fields"] == ["Name"]


def test_runtime_loader_falls_back_to_cache_then_bundled(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cached_artifact = {
        "version_id": "cached-version",
        "denorm_config": {"ascendix__Property__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}}},
    }
    (cache_dir / "00DTEST.yaml").write_text(yaml.safe_dump(cached_artifact), encoding="utf-8")

    loader = RuntimeConfigLoader(
        cache_dir=str(cache_dir),
        bundled_paths=[str(tmp_path / "missing.yaml")],
    )
    assert loader.load("00DTEST")["version_id"] == "cached-version"

    bundled_path = tmp_path / "denorm_config.yaml"
    bundled_path.write_text(
        yaml.safe_dump(
            {"ascendix__Lease__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}}}
        ),
        encoding="utf-8",
    )
    bundled_loader = RuntimeConfigLoader(
        cache_dir=str(tmp_path / "empty-cache"),
        bundled_paths=[str(bundled_path)],
    )
    bundled = bundled_loader.load("00DOTHER")
    assert bundled["version_id"] == "bundled"
    assert "ascendix__Lease__c" in extract_denorm_config(bundled)
