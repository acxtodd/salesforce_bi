#!/usr/bin/env python3
"""Replay documents from the S3 audit trail into a Turbopuffer namespace.

Reads JSON document snapshots written by the AuditingBackend and upserts
them into a target namespace — no Salesforce or Bedrock credentials needed.

Usage:
    # Dry run — list keys without upserting
    python3 scripts/replay_from_audit.py \
        --audit-bucket my-audit-bucket \
        --namespace sandbox_test \
        --org-id 00Ddl000003yx57EAA \
        --dry-run

    # Authoritative replay into a fresh namespace
    python3 scripts/replay_from_audit.py \
        --audit-bucket my-audit-bucket \
        --namespace sandbox_fresh \
        --org-id 00Ddl000003yx57EAA \
        --require-empty

    # Point-in-time replay
    python3 scripts/replay_from_audit.py \
        --audit-bucket my-audit-bucket \
        --namespace sandbox_pit \
        --org-id 00Ddl000003yx57EAA \
        --as-of 2026-03-15T00:00:00Z
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.denormalize import FULL_TEXT_SEARCH_SCHEMA
from lib.turbopuffer_backend import TurbopufferBackend

LOG = logging.getLogger("replay_from_audit")

BATCH_SIZE_DEFAULT = 100


def _list_current_versions(
    s3_client: Any,
    bucket: str,
    prefix: str,
    object_types: list[str] | None,
) -> list[str]:
    """List current S3 object keys under *prefix*, filtering by object type."""
    keys: list[str] = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # Skip _meta/ config snapshots
            if "/_meta/" in key:
                continue
            if object_types:
                # Key pattern: documents/{org_id}/{object_type}/{record_id}.json
                parts = key.split("/")
                if len(parts) >= 3 and parts[2] not in object_types:
                    continue
            keys.append(key)
    return keys


def _list_point_in_time_versions(
    s3_client: Any,
    bucket: str,
    prefix: str,
    as_of: datetime,
    object_types: list[str] | None,
) -> list[tuple[str, str]]:
    """Return ``[(key, version_id), ...]`` for the latest version of each
    key with ``LastModified <= as_of``.
    """
    # Collect all versions per key
    key_versions: dict[str, list[tuple[datetime, str]]] = {}
    paginator = s3_client.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for version in page.get("Versions", []):
            key = version["Key"]
            if "/_meta/" in key:
                continue
            if object_types:
                parts = key.split("/")
                if len(parts) >= 3 and parts[2] not in object_types:
                    continue
            last_mod = version["LastModified"]
            # Ensure timezone-aware
            if last_mod.tzinfo is None:
                last_mod = last_mod.replace(tzinfo=timezone.utc)
            if last_mod <= as_of:
                key_versions.setdefault(key, []).append(
                    (last_mod, version["VersionId"])
                )

    # Pick the latest version per key that is <= as_of
    result: list[tuple[str, str]] = []
    for key, versions in key_versions.items():
        versions.sort(key=lambda x: x[0], reverse=True)
        result.append((key, versions[0][1]))
    return result


def _validate_config(
    s3_client: Any,
    bucket: str,
    prefix: str,
    local_config_path: str = "denorm_config.yaml",
) -> None:
    """Compare latest ``_meta/`` config snapshot hash with local config."""
    import yaml

    meta_prefix = f"{prefix}_meta/"
    # Find the latest .json metadata file
    paginator = s3_client.get_paginator("list_objects_v2")
    meta_keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=meta_prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".json"):
                meta_keys.append(obj["Key"])
    if not meta_keys:
        LOG.warning("No config snapshots found under %s", meta_prefix)
        return

    meta_keys.sort()
    latest_key = meta_keys[-1]
    resp = s3_client.get_object(Bucket=bucket, Key=latest_key)
    remote_meta = json.loads(resp["Body"].read())
    remote_hash = remote_meta.get("config_hash", "")

    local_path = Path(local_config_path)
    if not local_path.exists():
        local_path = PROJECT_ROOT / local_config_path
    if not local_path.exists():
        LOG.warning("Local config %s not found — skipping validation", local_config_path)
        return

    local_hash = hashlib.sha256(local_path.read_bytes()).hexdigest()
    if local_hash == remote_hash:
        LOG.info("Config hashes match (local == remote snapshot)")
    else:
        LOG.warning(
            "CONFIG DRIFT DETECTED: local hash %s != remote hash %s (snapshot: %s)",
            local_hash[:16],
            remote_hash[:16],
            latest_key,
        )


def _assert_namespace_empty(backend: Any, namespace: str) -> None:
    """Abort with ``sys.exit(1)`` unless *namespace* contains zero documents.

    Fails closed: if the aggregate query itself raises, we abort rather than
    proceeding as if the namespace were empty.
    """
    try:
        result = backend.aggregate(namespace, aggregate="count")
        count = result.get("count", 0)
    except Exception:
        LOG.error(
            "Cannot verify namespace '%s' is empty — aggregate query failed. "
            "Aborting to protect authoritative replay guarantee.",
            namespace,
            exc_info=True,
        )
        sys.exit(1)
    if count > 0:
        LOG.error(
            "Target namespace '%s' contains %d documents. "
            "Create a fresh namespace or omit --require-empty for additive replay.",
            namespace,
            count,
        )
        sys.exit(1)
    LOG.info("Namespace '%s' is empty — authoritative replay", namespace)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Replay documents from S3 audit trail into Turbopuffer.",
    )
    parser.add_argument("--audit-bucket", required=True, help="S3 audit bucket name")
    parser.add_argument("--namespace", required=True, help="Target Turbopuffer namespace")
    parser.add_argument("--org-id", required=True, help="Salesforce org ID (S3 prefix filter)")
    parser.add_argument(
        "--objects", nargs="+",
        help="Filter by object type(s), e.g. property lease",
    )
    parser.add_argument(
        "--as-of",
        help="ISO timestamp for point-in-time replay (uses S3 versioning)",
    )
    parser.add_argument("--dry-run", action="store_true", help="List keys without upserting")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT)
    parser.add_argument(
        "--validate-config", action="store_true",
        help="Compare _meta/ config snapshot with local denorm_config.yaml",
    )
    parser.add_argument(
        "--require-empty", action="store_true",
        help="Verify target namespace is empty before replaying (authoritative mode)",
    )

    args = parser.parse_args()

    import boto3

    s3_client = boto3.client("s3")
    prefix = f"documents/{args.org_id}/"

    # Validate config if requested
    if args.validate_config:
        _validate_config(s3_client, args.audit_bucket, prefix)

    # Check --require-empty (fail closed: if we can't verify, abort)
    if args.require_empty and not args.dry_run:
        _assert_namespace_empty(TurbopufferBackend(), args.namespace)

    # Enumerate documents
    as_of = None
    if args.as_of:
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))

    if as_of:
        LOG.info("Point-in-time mode: as_of=%s", as_of.isoformat())
        versioned_keys = _list_point_in_time_versions(
            s3_client, args.audit_bucket, prefix, as_of, args.objects
        )
        LOG.info("Found %d versioned keys", len(versioned_keys))
    else:
        current_keys = _list_current_versions(
            s3_client, args.audit_bucket, prefix, args.objects
        )
        LOG.info("Found %d current keys", len(current_keys))
        versioned_keys = [(k, None) for k in current_keys]

    if args.dry_run:
        for key, vid in versioned_keys:
            version_str = f" (version={vid})" if vid else ""
            print(f"  {key}{version_str}")
        print(f"\nTotal: {len(versioned_keys)} keys (dry run — no upserts)")
        return

    # Replay
    backend = TurbopufferBackend()
    loaded = 0
    tombstones = 0
    errors = 0
    batch: list[dict] = []
    first_batch = True

    for key, version_id in versioned_keys:
        try:
            get_kwargs: dict[str, Any] = {"Bucket": args.audit_bucket, "Key": key}
            if version_id:
                get_kwargs["VersionId"] = version_id
            resp = s3_client.get_object(**get_kwargs)
            doc = json.loads(resp["Body"].read())
        except Exception:
            LOG.warning("Failed to read %s", key, exc_info=True)
            errors += 1
            continue

        if doc.get("deleted"):
            tombstones += 1
            continue

        batch.append(doc)
        if len(batch) >= args.batch_size:
            schema = FULL_TEXT_SEARCH_SCHEMA if first_batch else None
            backend.upsert(args.namespace, documents=batch, schema=schema)
            loaded += len(batch)
            first_batch = False
            batch = []

    # Flush remaining
    if batch:
        schema = FULL_TEXT_SEARCH_SCHEMA if first_batch else None
        backend.upsert(args.namespace, documents=batch, schema=schema)
        loaded += len(batch)

    mode = "authoritative (--require-empty)" if args.require_empty else "additive"
    LOG.info(
        "Replay complete (%s): loaded=%d tombstones_skipped=%d errors=%d",
        mode,
        loaded,
        tombstones,
        errors,
    )


if __name__ == "__main__":
    main()
