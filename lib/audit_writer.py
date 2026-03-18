"""S3 audit trail for Turbopuffer document writes.

Provides best-effort S3 mirroring of every upsert/delete so that documents
can be audited, diffed, and replayed into any namespace without Salesforce
or Bedrock credentials.

Key pattern: ``documents/{org_id}/{object_type}/{record_id}.json``
"""

from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from lib.search_backend import SearchBackend

LOG = logging.getLogger(__name__)


@dataclass
class AuditStats:
    """Counters for audit write outcomes within a single invocation."""

    audit_ok: int = 0
    audit_failed: int = 0


def write_audit_document(
    s3_client: Any, bucket: str, org_id: str, doc: dict
) -> bool:
    """Write a single document to the S3 audit trail.

    Returns True on success; on failure logs a structured warning and
    returns False.  Never raises.
    """
    object_type = doc.get("object_type", "unknown")
    record_id = doc.get("id", "unknown")
    key = f"documents/{org_id}/{object_type}/{record_id}.json"
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
    """Write delete tombstones to S3 for each record ID.

    Returns ``(ok_count, fail_count)``.
    """
    now = datetime.now(timezone.utc).isoformat()

    def _write_one(record_id: str) -> bool:
        key = f"documents/{org_id}/{object_type}/{record_id}.json"
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
                "Audit tombstone failed: record_id=%s object_type=%s",
                record_id,
                object_type,
                exc_info=True,
            )
            return False

    ok = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=min(len(record_ids), 20)) as pool:
        futures = [pool.submit(_write_one, rid) for rid in record_ids]
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
                ],
            )
        except Exception:
            LOG.warning("Failed to emit audit metrics", exc_info=True)

    # -- pass-through for attributes the callers may access -----------------

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
