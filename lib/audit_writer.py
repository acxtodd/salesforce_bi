"""S3 audit trail for Turbopuffer document writes.

Two artifact types at different pipeline stages:

1. **Denorm audit** (human-readable, pre-vector):
   ``documents/{org_id}/{object_type}/{record_id}.json``
   Structured JSON with ``direct_fields``, ``parent_fields``, ``text``.
   Written after flatten+build_text, BEFORE embedding.

2. **Replay artifact** (machine-readable, post-vector):
   ``replay/{org_id}/{object_type}/{record_id}.json``
   Full Turbopuffer payload with vector.  Written after upsert.
"""

from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from lib.denormalize import clean_label
from lib.search_backend import SearchBackend

LOG = logging.getLogger(__name__)


@dataclass
class AuditStats:
    """Counters for audit write outcomes within a single invocation."""

    audit_ok: int = 0
    audit_failed: int = 0
    denorm_audit_ok: int = 0
    denorm_audit_failed: int = 0


def write_denorm_audit(
    s3_client: Any,
    bucket: str,
    org_id: str,
    *,
    record_id: str,
    object_type: str,
    direct_fields: dict,
    parent_fields: dict,
    text: str,
    salesforce_org_id: str,
    last_modified: str | None,
) -> bool:
    """Write a human-readable denorm audit artifact to S3.

    Captures the pre-vector pipeline state (after flatten+build_text, before
    embedding) so stakeholders can inspect denormalization effectiveness.

    S3 key: ``documents/{org_id}/{cleaned_type}/{record_id}.json``
    Returns True on success; on failure logs a warning and returns False.
    Never raises.
    """
    cleaned_type = clean_label(object_type).lower()
    key = f"documents/{org_id}/{cleaned_type}/{record_id}.json"
    body = {
        "record_id": record_id,
        "object_type": object_type,
        "salesforce_org_id": salesforce_org_id,
        "last_modified": last_modified,
        "text": text,
        "direct_fields": direct_fields,
        "parent_fields": parent_fields,
    }
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(body, indent=2, sort_keys=True, default=str),
            ContentType="application/json",
        )
        return True
    except Exception:
        LOG.warning(
            "Denorm audit write failed: record_id=%s object_type=%s",
            record_id,
            object_type,
            exc_info=True,
        )
        return False


def write_audit_document(
    s3_client: Any, bucket: str, org_id: str, doc: dict
) -> bool:
    """Write a single replay artifact (full Turbopuffer payload) to S3.

    S3 key: ``replay/{org_id}/{object_type}/{record_id}.json``
    Returns True on success; on failure logs a structured warning and
    returns False.  Never raises.
    """
    object_type = doc.get("object_type", "unknown")
    record_id = doc.get("id", "unknown")
    key = f"replay/{org_id}/{object_type}/{record_id}.json"
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(doc, default=str),
            ContentType="application/json",
        )
        return True
    except Exception:
        LOG.warning(
            "Audit write failed: record_id=%s object_type=%s error=see_traceback",
            record_id,
            object_type,
            exc_info=True,
        )
        return False


def write_audit_tombstone(
    s3_client: Any,
    bucket: str,
    org_id: str,
    object_type: str,
    record_ids: list[str],
) -> tuple[int, int]:
    """Write delete tombstones to **both** S3 prefixes for each record ID.

    Writes to ``documents/{org_id}/{object_type}/{record_id}.json`` (denorm
    audit) and ``replay/{org_id}/{object_type}/{record_id}.json`` (replay).

    Returns ``(ok_count, fail_count)`` aggregated across both prefixes.
    """
    now = datetime.now(timezone.utc).isoformat()

    def _write_one(prefix: str, record_id: str) -> bool:
        key = f"{prefix}/{org_id}/{object_type}/{record_id}.json"
        body = {"deleted": True, "record_id": record_id, "deleted_at": now}
        try:
            s3_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(body, default=str),
                ContentType="application/json",
            )
            return True
        except Exception:
            LOG.warning(
                "Audit tombstone failed: prefix=%s record_id=%s object_type=%s",
                prefix,
                record_id,
                object_type,
                exc_info=True,
            )
            return False

    ok = 0
    failed = 0
    tasks = [
        (prefix, rid)
        for rid in record_ids
        for prefix in ("documents", "replay")
    ]
    with ThreadPoolExecutor(max_workers=min(len(tasks), 20)) as pool:
        futures = [pool.submit(_write_one, pfx, rid) for pfx, rid in tasks]
        for fut in as_completed(futures):
            if fut.result():
                ok += 1
            else:
                failed += 1
    return ok, failed


def write_config_snapshot(
    s3_client: Any,
    bucket: str,
    org_id: str,
    denorm_config_dict: dict,
    denorm_config_yaml_str: str,
    source: str,
) -> None:
    """Write denorm config snapshot to ``_meta/`` for drift detection.

    Best-effort — logs warning on failure, never raises.
    """
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    prefix = f"documents/{org_id}/_meta/denorm_config_{source}_{ts}"

    config_hash = hashlib.sha256(denorm_config_yaml_str.encode()).hexdigest()
    meta = {
        "config_hash": config_hash,
        "source": source,
        "timestamp": now.isoformat(),
    }

    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{prefix}.yaml",
            Body=denorm_config_yaml_str,
            ContentType="text/yaml",
        )
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{prefix}.json",
            Body=json.dumps(meta, default=str),
            ContentType="application/json",
        )
    except Exception:
        LOG.warning(
            "Config snapshot write failed: org_id=%s source=%s",
            org_id,
            source,
            exc_info=True,
        )


class AuditingBackend:
    """Decorator that adds S3 audit writes around an inner SearchBackend.

    Upsert calls are forwarded to the inner backend first, then each
    document is mirrored to S3.  Audit failures are counted but never
    propagate to the caller.
    """

    def __init__(
        self,
        inner: SearchBackend,
        s3_client: Any,
        bucket: str,
        org_id: str,
    ) -> None:
        self._inner = inner
        self._s3 = s3_client
        self._bucket = bucket
        self._org_id = org_id
        self.stats = AuditStats()

    # -- write path (audited) -----------------------------------------------

    def upsert(
        self,
        namespace: str,
        *,
        documents: list[dict],
        distance_metric: str = "cosine_distance",
        schema: dict | None = None,
    ) -> None:
        self._inner.upsert(
            namespace,
            documents=documents,
            distance_metric=distance_metric,
            schema=schema,
        )
        with ThreadPoolExecutor(max_workers=min(len(documents), 20)) as pool:
            futures = {
                pool.submit(write_audit_document, self._s3, self._bucket, self._org_id, doc): doc
                for doc in documents
            }
            for fut in as_completed(futures):
                if fut.result():
                    self.stats.audit_ok += 1
                else:
                    self.stats.audit_failed += 1

    def delete(self, namespace: str, *, ids: list[str]) -> None:
        self._inner.delete(namespace, ids=ids)

    # -- read path (pure delegation) ----------------------------------------

    def search(self, namespace: str, **kwargs: Any) -> list[dict]:
        return self._inner.search(namespace, **kwargs)

    def aggregate(self, namespace: str, **kwargs: Any) -> dict:
        return self._inner.aggregate(namespace, **kwargs)

    def warm(self, namespace: str) -> None:
        self._inner.warm(namespace)

    # -- observability ------------------------------------------------------

    def emit_audit_metrics(self, cloudwatch_client: Any) -> None:
        """Emit invocation-level audit success/failure counts to CloudWatch."""
        try:
            cloudwatch_client.put_metric_data(
                Namespace="SalesforceAISearch/CDCSync",
                MetricData=[
                    {
                        "MetricName": "AuditWriteSuccess",
                        "Value": self.stats.audit_ok,
                        "Unit": "Count",
                    },
                    {
                        "MetricName": "AuditWriteFailure",
                        "Value": self.stats.audit_failed,
                        "Unit": "Count",
                    },
                    {
                        "MetricName": "DenormAuditWriteSuccess",
                        "Value": self.stats.denorm_audit_ok,
                        "Unit": "Count",
                    },
                    {
                        "MetricName": "DenormAuditWriteFailure",
                        "Value": self.stats.denorm_audit_failed,
                        "Unit": "Count",
                    },
                ],
            )
        except Exception:
            LOG.warning("Failed to emit audit metrics", exc_info=True)

    # -- pass-through for attributes the callers may access -----------------

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
