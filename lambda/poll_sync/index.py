"""Poll Sync Lambda — incremental sync for non-CDC objects.

Queries Salesforce for records modified since the last watermark,
denormalizes, embeds, and upserts into Turbopuffer.

Environment variables:
    SALESFORCE_ORG_ID          — Salesforce org ID (e.g. 00Ddl000003yx57EAA)
    POLL_OBJECTS               — Comma-separated list of objects to poll
    DENORM_CONFIG_PATH         — path to denorm_config.yaml (default: denorm_config.yaml)
    CONFIG_ARTIFACT_BUCKET     — S3 bucket for runtime config artifacts (optional)
    CONFIG_ARTIFACT_PREFIX     — S3 prefix for config artifacts (default: config)
    POLL_BATCH_SIZE            — records per page (default: 200)
    AUDIT_BUCKET               — S3 bucket for audit trail
    LOG_LEVEL                  — logging level (default: INFO)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import yaml

# ---------------------------------------------------------------------------
# Path setup — support both local dev (repo layout) and Lambda (flat bundle)
# ---------------------------------------------------------------------------
_this_dir = Path(__file__).resolve().parent
_project_root = _this_dir.parent.parent
# Local dev: add project root + lambda dir so lib.* and common.* resolve
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "lambda"))
# Lambda bundle: shared modules are copied into the deployment package
sys.path.insert(0, str(_this_dir))

from common.salesforce_client import SalesforceClient  # noqa: E402
from lib.denormalize import (  # noqa: E402
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_ID,
    FULL_TEXT_SEARCH_SCHEMA,
    build_document,
    build_relationship_map as build_relationship_spec_map,
    build_soql,
    build_text,
    build_tpuf_schema,
    clean_label,
    flatten,
)
from lib.audit_writer import (  # noqa: E402
    AuditingBackend,
    write_config_snapshot,
    write_denorm_audit,
)
from lib.turbopuffer_backend import TurbopufferBackend  # noqa: E402
from lib.runtime_config import (  # noqa: E402
    RuntimeConfigLoader,
    bundled_paths_from_env,
    extract_denorm_config,
)

LOG = logging.getLogger("poll_sync")
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_POLL_BATCH_SIZE = 200
EMBED_BATCH_SIZE = 25
UPSERT_BATCH_SIZE = 100
SSM_WATERMARK_PREFIX = "/salesforce-ai-search/poll-watermark"
TIMEOUT_SAFETY_MS = 60_000  # stop if < 60s remaining

# ---------------------------------------------------------------------------
# Module-level cold-start initialization
# ---------------------------------------------------------------------------

_denorm_config: dict | None = None
_denorm_config_raw_yaml: str = ""
_denorm_config_version: str = ""
_runtime_config_loader: RuntimeConfigLoader | None = None
_sf_client: SalesforceClient | None = None
_bedrock_client: Any = None
_backend: TurbopufferBackend | None = None
_cloudwatch_client: Any = None
_ssm_client: Any = None
_s3_client: Any = None
_relationship_maps: dict[str, dict[str, str]] = {}
_config_snapshot_written: bool = False


def _get_runtime_config_loader() -> RuntimeConfigLoader:
    """Get or create the RuntimeConfigLoader (cached at module level)."""
    global _runtime_config_loader
    if _runtime_config_loader is None:
        bucket = os.getenv("CONFIG_ARTIFACT_BUCKET", "")
        _runtime_config_loader = RuntimeConfigLoader(
            s3_client=boto3.client("s3") if bucket else None,
            ssm_client=boto3.client("ssm") if bucket else None,
            bucket=bucket,
            s3_prefix=os.getenv("CONFIG_ARTIFACT_PREFIX", "config"),
            bundled_paths=bundled_paths_from_env(__file__),
        )
    return _runtime_config_loader


def _load_denorm_config(org_id: str = "") -> tuple[dict, str]:
    """Load denorm config via RuntimeConfigLoader with safe fallback.

    Uses the control-plane fallback order: S3 active artifact → /tmp
    cache → bundled denorm_config.yaml.

    Returns ``(parsed_dict, raw_yaml_str)`` so callers that need byte-
    for-byte provenance (audit trail) can use the raw string.
    """
    global _denorm_config, _denorm_config_raw_yaml, _denorm_config_version
    if _denorm_config is not None:
        return _denorm_config, _denorm_config_raw_yaml

    org_id = org_id or os.environ.get("SALESFORCE_ORG_ID", "")
    try:
        loader = _get_runtime_config_loader()
        artifact = loader.load(org_id)
        _denorm_config = extract_denorm_config(artifact)
        _denorm_config_version = str(artifact.get("version_id", "unknown"))
        _denorm_config_raw_yaml = yaml.safe_dump(
            _denorm_config, sort_keys=False, allow_unicode=False
        )
        LOG.info(
            "poll_sync loaded runtime config version %s for org %s",
            _denorm_config_version,
            org_id,
        )
    except Exception:
        LOG.warning(
            "RuntimeConfigLoader failed — falling back to static YAML",
            exc_info=True,
        )
        config_path = os.environ.get("DENORM_CONFIG_PATH", "denorm_config.yaml")
        with open(config_path) as f:
            _denorm_config_raw_yaml = f.read()
        _denorm_config = yaml.safe_load(_denorm_config_raw_yaml)
        _denorm_config_version = "bundled-fallback"

    return _denorm_config, _denorm_config_raw_yaml


def _get_sf_client() -> SalesforceClient:
    """Get or create SalesforceClient (cached)."""
    global _sf_client
    if _sf_client is None:
        _sf_client = SalesforceClient.from_ssm()
    return _sf_client


def _get_bedrock_client() -> Any:
    """Get or create Bedrock runtime client (cached)."""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client("bedrock-runtime")
    return _bedrock_client


def _get_backend() -> TurbopufferBackend:
    """Get or create Turbopuffer backend (cached)."""
    global _backend
    if _backend is None:
        _backend = TurbopufferBackend()
    return _backend


def _get_cloudwatch_client() -> Any:
    """Get or create CloudWatch client (cached)."""
    global _cloudwatch_client
    if _cloudwatch_client is None:
        _cloudwatch_client = boto3.client("cloudwatch")
    return _cloudwatch_client


def _get_ssm_client() -> Any:
    """Get or create SSM client (cached)."""
    global _ssm_client
    if _ssm_client is None:
        _ssm_client = boto3.client("ssm")
    return _ssm_client


def _get_s3_client() -> Any:
    """Get or create S3 client (cached)."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def _get_relationship_map(
    sf_client: SalesforceClient, object_name: str
) -> dict[str, dict[str, str]]:
    """Get or build relationship map for an object (cached per object)."""
    if object_name not in _relationship_maps:
        _relationship_maps[object_name] = build_relationship_spec_map(
            sf_client, object_name
        )
    return _relationship_maps[object_name]


# ---------------------------------------------------------------------------
# Watermark helpers
# ---------------------------------------------------------------------------


def parse_watermark(raw: str) -> tuple[str, str]:
    """Parse composite watermark into (timestamp, last_id).

    Format: ``{ISO-8601 timestamp}|{last_processed_salesforce_id}``
    """
    if raw and "|" in raw:
        ts, last_id = raw.split("|", 1)
        return ts, last_id
    return "1970-01-01T00:00:00Z", ""


def format_watermark(timestamp: str, last_id: str) -> str:
    """Format composite watermark string."""
    return f"{timestamp}|{last_id}"


def _read_watermark(ssm_client: Any, object_name: str) -> tuple[str, str]:
    """Read watermark from SSM Parameter Store."""
    param_name = f"{SSM_WATERMARK_PREFIX}/{object_name}"
    try:
        response = ssm_client.get_parameter(Name=param_name)
        return parse_watermark(response["Parameter"]["Value"])
    except ssm_client.exceptions.ParameterNotFound:
        LOG.info("No watermark found for %s — starting from epoch", object_name)
        return "1970-01-01T00:00:00Z", ""
    except Exception:
        LOG.exception("Failed to read watermark for %s", object_name)
        return "1970-01-01T00:00:00Z", ""


def _write_watermark(
    ssm_client: Any, object_name: str, timestamp: str, last_id: str
) -> None:
    """Write watermark to SSM Parameter Store."""
    param_name = f"{SSM_WATERMARK_PREFIX}/{object_name}"
    value = format_watermark(timestamp, last_id)
    try:
        ssm_client.put_parameter(
            Name=param_name,
            Value=value,
            Type="String",
            Overwrite=True,
        )
        LOG.info("Watermark for %s updated to %s", object_name, value)
    except Exception:
        LOG.exception("Failed to write watermark for %s", object_name)
        raise


# ---------------------------------------------------------------------------
# Pagination query builder
# ---------------------------------------------------------------------------


def build_poll_where(watermark_ts: str, watermark_id: str) -> str:
    """Build WHERE + ORDER BY + pagination clause for poll query.

    Uses composite watermark for deterministic, gap-free ordering:
    records are ordered by (LastModifiedDate ASC, Id ASC) and the
    WHERE clause ensures no duplicates across pages.
    """
    if watermark_id:
        return (
            f"WHERE (LastModifiedDate > {watermark_ts}) "
            f"OR (LastModifiedDate = {watermark_ts} AND Id > '{watermark_id}') "
            f"ORDER BY LastModifiedDate ASC, Id ASC"
        )
    return (
        f"WHERE LastModifiedDate > {watermark_ts} "
        f"ORDER BY LastModifiedDate ASC, Id ASC"
    )


# ---------------------------------------------------------------------------
# Embedding (single-record, matching cdc_sync pattern)
# ---------------------------------------------------------------------------


def _embed_single(bedrock_client: Any, text: str) -> list[float]:
    """Generate embedding for a single text via Bedrock Titan v2."""
    request_body = {
        "inputText": text,
        "dimensions": EMBEDDING_DIMENSIONS,
        "normalize": True,
    }
    response = bedrock_client.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(request_body),
    )
    response_body = json.loads(response["body"].read())
    return response_body["embedding"]


# ---------------------------------------------------------------------------
# Batch embedding (matching bulk_load pattern)
# ---------------------------------------------------------------------------


def _embed_batch(bedrock_client: Any, texts: list[str]) -> list[list[float]]:
    """Embed texts in batches of EMBED_BATCH_SIZE."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        LOG.info(
            "  Embedding batch %d (%d texts)",
            i // EMBED_BATCH_SIZE + 1,
            len(batch),
        )
        for text in batch:
            all_embeddings.append(_embed_single(bedrock_client, text))
    return all_embeddings


# ---------------------------------------------------------------------------
# CloudWatch metrics
# ---------------------------------------------------------------------------


def _emit_poll_metrics(
    cloudwatch_client: Any, object_name: str, records_synced: int
) -> None:
    """Emit records_synced metric to CloudWatch."""
    try:
        cloudwatch_client.put_metric_data(
            Namespace="SalesforceAISearch/PollSync",
            MetricData=[
                {
                    "MetricName": "RecordsSynced",
                    "Value": records_synced,
                    "Unit": "Count",
                    "Dimensions": [
                        {"Name": "SObject", "Value": object_name},
                    ],
                }
            ],
        )
        LOG.info(
            "Metric emitted: %s records_synced=%d",
            object_name,
            records_synced,
        )
    except Exception:
        LOG.exception("Failed to emit poll sync metrics")


# ---------------------------------------------------------------------------
# Sync pipeline (per-object)
# ---------------------------------------------------------------------------


def _sync_object(
    object_name: str,
    *,
    full_sync: bool = False,
    context: Any = None,
    sf_client: SalesforceClient | None = None,
    bedrock_client: Any = None,
    backend: TurbopufferBackend | None = None,
    cloudwatch_client: Any = None,
    ssm_client: Any = None,
    denorm_config: dict | None = None,
    namespace: str | None = None,
    salesforce_org_id: str | None = None,
    page_size: int | None = None,
    audit_bucket: str = "",
    audit_s3_client: Any = None,
) -> dict:
    """Sync a single object: query changed records, embed, upsert.

    Returns dict with {records_synced, watermark, continuation_needed}.
    """
    # Resolve dependencies (support both Lambda globals and CLI injection)
    sf = sf_client or _get_sf_client()
    bedrock = bedrock_client or _get_bedrock_client()
    tpuf = backend or _get_backend()
    cw = cloudwatch_client or _get_cloudwatch_client()
    ssm = ssm_client or _get_ssm_client()
    config = denorm_config or _load_denorm_config()[0]
    org_id = salesforce_org_id or os.environ.get("SALESFORCE_ORG_ID", "")
    ns = namespace or f"org_{org_id}"
    batch_size = page_size or int(
        os.environ.get("POLL_BATCH_SIZE", str(DEFAULT_POLL_BATCH_SIZE))
    )

    obj_config = config.get(object_name)
    if obj_config is None:
        LOG.warning("No denorm config for %s — skipping", object_name)
        return {"records_synced": 0, "watermark": "", "error": "no config"}

    embed_fields = obj_config.get("embed_fields", [])
    metadata_fields = obj_config.get("metadata_fields", [])
    parent_config = obj_config.get("parents", {})
    rel_map = _get_relationship_map(sf, object_name)

    # Build base SOQL (SELECT ... FROM object)
    soql_base = build_soql(
        object_name, embed_fields, metadata_fields, parent_config, rel_map
    )

    # Read or reset watermark
    if full_sync:
        watermark_ts, watermark_id = "1970-01-01T00:00:00Z", ""
        LOG.info("Full sync for %s — watermark reset to epoch", object_name)
    else:
        watermark_ts, watermark_id = _read_watermark(ssm, object_name)
        LOG.info(
            "Polling %s from watermark: %s",
            object_name,
            format_watermark(watermark_ts, watermark_id),
        )

    total_synced = 0
    continuation_needed = False

    while True:
        # Lambda timeout safety check
        if context is not None and hasattr(context, "get_remaining_time_in_millis"):
            remaining_ms = context.get_remaining_time_in_millis()
            if remaining_ms < TIMEOUT_SAFETY_MS:
                LOG.warning(
                    "Only %dms remaining — stopping poll for %s (continuation needed)",
                    remaining_ms,
                    object_name,
                )
                continuation_needed = True
                break

        # Build paginated query
        where_clause = build_poll_where(watermark_ts, watermark_id)
        soql = f"{soql_base} {where_clause} LIMIT {batch_size}"
        LOG.info("  SOQL: %s", soql[:300])

        result = sf.query(soql)
        records = result.get("records", [])

        if not records:
            LOG.info("  No more records for %s", object_name)
            break

        LOG.info("  Fetched %d records for %s", len(records), object_name)

        # Prepare all records: flatten + build_text
        prepared_rows: list[dict[str, Any]] = []
        for record in records:
            record_id = record.get("Id", "<unknown>")
            try:
                direct_fields, parent_fields = flatten(
                    record, embed_fields, metadata_fields, parent_config, rel_map
                )
                text = build_text(
                    direct_fields,
                    parent_fields,
                    embed_fields,
                    parent_config,
                    object_name,
                    rel_map,
                )

                # Write denorm audit artifact (pre-vector, human-readable)
                if audit_bucket and audit_s3_client:
                    try:
                        write_denorm_audit(
                            audit_s3_client,
                            audit_bucket,
                            org_id,
                            record_id=record_id,
                            object_type=object_name,
                            direct_fields=direct_fields,
                            parent_fields=parent_fields,
                            text=text,
                            salesforce_org_id=org_id,
                            last_modified=direct_fields.get("LastModifiedDate"),
                        )
                    except Exception:
                        LOG.exception("  Audit write failed for %s", record_id)

                prepared_rows.append(
                    {
                        "record_id": record_id,
                        "direct_fields": direct_fields,
                        "parent_fields": parent_fields,
                        "text": text,
                        "record": record,
                    }
                )
            except Exception:
                LOG.exception("  Skipping record %s during flatten/text", record_id)
                continue

        if not prepared_rows:
            LOG.warning("  All records in page skipped for %s", object_name)
            # Advance watermark past these records to avoid infinite loop
            last_record = records[-1]
            watermark_ts = last_record.get("LastModifiedDate", watermark_ts)
            watermark_id = last_record.get("Id", watermark_id)
            continue

        # Batch embed
        texts = [row["text"] for row in prepared_rows]
        embeddings = _embed_batch(bedrock, texts)

        # Build documents
        documents: list[dict] = []
        for idx, row in enumerate(prepared_rows):
            try:
                doc = build_document(
                    direct_fields=row["direct_fields"],
                    parent_fields=row["parent_fields"],
                    text=row["text"],
                    vector=embeddings[idx],
                    record_id=row["record_id"],
                    object_type=object_name,
                    salesforce_org_id=org_id,
                    embed_field_names=embed_fields,
                    metadata_field_names=metadata_fields,
                    parent_config=parent_config,
                    rel_map=rel_map,
                )
                documents.append(doc)
            except Exception:
                LOG.exception(
                    "  Skipping record %s during document build", row["record_id"]
                )

        # Batch upsert
        if documents:
            schema = build_tpuf_schema(documents, base_schema=FULL_TEXT_SEARCH_SCHEMA)
            for i in range(0, len(documents), UPSERT_BATCH_SIZE):
                batch = documents[i : i + UPSERT_BATCH_SIZE]
                LOG.info(
                    "  Upserting batch %d (%d docs)",
                    i // UPSERT_BATCH_SIZE + 1,
                    len(batch),
                )
                tpuf.upsert(
                    ns,
                    documents=batch,
                    schema=schema if i == 0 else None,
                )

        total_synced += len(documents)

        # Advance watermark to last record in page
        last_record = records[-1]
        watermark_ts = last_record.get("LastModifiedDate", watermark_ts)
        watermark_id = last_record.get("Id", watermark_id)

        # Persist watermark after each page is committed
        _write_watermark(ssm, object_name, watermark_ts, watermark_id)

        # If fewer records than page_size, we've reached the end
        if len(records) < batch_size:
            break

    # Emit CloudWatch metrics
    _emit_poll_metrics(cw, object_name, total_synced)

    final_watermark = format_watermark(watermark_ts, watermark_id)
    LOG.info(
        "Poll sync for %s complete: %d records synced, watermark=%s",
        object_name,
        total_synced,
        final_watermark,
    )

    return {
        "records_synced": total_synced,
        "watermark": final_watermark,
        "continuation_needed": continuation_needed,
    }


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def lambda_handler(event: dict, context: Any) -> dict:
    """AWS Lambda entry point for poll sync.

    Accepts events from EventBridge Schedule or on-demand invocation.

    Event shape:
        {
            "objects": ["ascendix__Deal__c", "ascendix__Sale__c"],  // optional
            "full_sync": false  // optional, reset watermark to epoch
        }
    """
    global _config_snapshot_written

    objects = event.get("objects") or os.environ.get("POLL_OBJECTS", "").split(",")
    objects = [o.strip() for o in objects if o.strip()]
    full_sync = event.get("full_sync", False)

    if not objects:
        LOG.error("No objects specified — set POLL_OBJECTS env var or pass in event")
        return {"statusCode": 400, "error": "no objects specified"}

    salesforce_org_id = os.environ.get("SALESFORCE_ORG_ID", "")
    audit_bucket = os.environ.get("AUDIT_BUCKET", "")

    # Wrap backend with audit writer if AUDIT_BUCKET is configured
    backend = _get_backend()
    audit_s3_client = None
    if audit_bucket:
        s3_client = _get_s3_client()
        audit_s3_client = s3_client
        backend = AuditingBackend(backend, audit_s3_client, audit_bucket, salesforce_org_id)
        if not _config_snapshot_written:
            denorm_config, raw_yaml = _load_denorm_config(salesforce_org_id)
            write_config_snapshot(
                audit_s3_client,
                audit_bucket,
                salesforce_org_id,
                denorm_config,
                raw_yaml,
                "poll_sync_cold_start",
            )
            _config_snapshot_written = True

    LOG.info(
        "Poll sync starting: objects=%s full_sync=%s audit=%s",
        objects,
        full_sync,
        bool(audit_bucket),
    )

    summary: dict[str, Any] = {}
    for obj in objects:
        result = _sync_object(
            obj,
            full_sync=full_sync,
            context=context,
            backend=backend,
            audit_bucket=audit_bucket,
            audit_s3_client=audit_s3_client,
        )
        summary[obj] = result

    # Emit audit metrics once per invocation
    if isinstance(backend, AuditingBackend):
        LOG.info(
            "Audit stats: replay_ok=%d replay_failed=%d denorm_ok=%d denorm_failed=%d",
            backend.stats.audit_ok,
            backend.stats.audit_failed,
            backend.stats.denorm_audit_ok,
            backend.stats.denorm_audit_failed,
        )
        backend.emit_audit_metrics(_get_cloudwatch_client())

    return {"statusCode": 200, "summary": summary}
