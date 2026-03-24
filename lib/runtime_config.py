"""Runtime loader for active compiled config artifacts."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from lib.config_refresh import (
    CONFIG_SSM_PREFIX,
    active_version_parameter_name,
    compiled_artifact_key,
)

LOG = logging.getLogger(__name__)


def extract_denorm_config(runtime_artifact: dict[str, Any]) -> dict[str, Any]:
    """Return the plain denorm config from a compiled artifact or fallback payload."""
    if "denorm_config" in runtime_artifact:
        return runtime_artifact["denorm_config"]
    return runtime_artifact


class RuntimeConfigLoader:
    """Load the active config with S3 -> /tmp -> bundled fallback order."""

    def __init__(
        self,
        *,
        s3_client: Any | None = None,
        ssm_client: Any | None = None,
        bucket: str = "",
        s3_prefix: str = "config",
        ssm_prefix: str = CONFIG_SSM_PREFIX,
        cache_dir: str = "/tmp/runtime-config",
        bundled_paths: list[str] | None = None,
    ):
        self.s3_client = s3_client
        self.ssm_client = ssm_client
        self.bucket = bucket
        self.s3_prefix = s3_prefix
        self.ssm_prefix = ssm_prefix
        self.cache_dir = Path(cache_dir)
        self.bundled_paths = bundled_paths or []

    def load(self, org_id: str) -> dict[str, Any]:
        artifact = self._load_from_s3(org_id)
        if artifact is not None:
            return artifact

        artifact = self._load_from_cache(org_id)
        if artifact is not None:
            return artifact

        return self._load_bundled()

    def _load_from_s3(self, org_id: str) -> dict[str, Any] | None:
        if not self.bucket or self.s3_client is None or self.ssm_client is None:
            return None

        try:
            response = self.ssm_client.get_parameter(
                Name=active_version_parameter_name(org_id, prefix=self.ssm_prefix)
            )
            version_id = response["Parameter"]["Value"]
        except Exception as exc:
            LOG.info("No active config pointer for %s: %s", org_id, exc)
            return None

        try:
            response = self.s3_client.get_object(
                Bucket=self.bucket,
                Key=compiled_artifact_key(org_id, version_id, prefix=self.s3_prefix),
            )
            artifact = yaml.safe_load(response["Body"].read())
        except Exception as exc:
            LOG.warning("Failed to load active runtime config for %s: %s", org_id, exc)
            return None

        if not isinstance(artifact, dict):
            return None

        self._write_cache(org_id, artifact)
        return artifact

    def _cache_path(self, org_id: str) -> Path:
        return self.cache_dir / f"{org_id}.yaml"

    def _write_cache(self, org_id: str, artifact: dict[str, Any]) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(org_id).write_text(
                yaml.safe_dump(artifact, sort_keys=False, allow_unicode=False),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover - best effort cache write
            LOG.warning("Failed to cache runtime config for %s: %s", org_id, exc)

    def _load_from_cache(self, org_id: str) -> dict[str, Any] | None:
        path = self._cache_path(org_id)
        if not path.is_file():
            return None
        try:
            artifact = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            LOG.warning("Failed to read cached runtime config for %s: %s", org_id, exc)
            return None
        return artifact if isinstance(artifact, dict) else None

    def _load_bundled(self) -> dict[str, Any]:
        for candidate in self.bundled_paths:
            if not candidate:
                continue
            path = Path(candidate).resolve()
            if not path.is_file():
                continue
            LOG.info("Loading bundled runtime config from %s", path)
            with path.open(encoding="utf-8") as handle:
                denorm_config = yaml.safe_load(handle)
            if not isinstance(denorm_config, dict):
                continue
            return {
                "schema_version": 1,
                "version_id": "bundled",
                "denorm_config": denorm_config,
                "query_scope": {
                    "object_api_names": sorted(denorm_config),
                    "object_types": [],
                    "objects": {},
                },
            }
        raise FileNotFoundError(
            "Cannot find a runtime config artifact or bundled denorm_config.yaml."
        )


def bundled_paths_from_env(current_file: str) -> list[str]:
    """Return the standard bundled config search paths for a Lambda runtime."""
    return [
        os.getenv("DENORM_CONFIG_PATH", ""),
        "denorm_config.yaml",
        os.path.join(os.path.dirname(current_file), "denorm_config.yaml"),
        os.path.join(os.path.dirname(current_file), "..", "..", "denorm_config.yaml"),
    ]
