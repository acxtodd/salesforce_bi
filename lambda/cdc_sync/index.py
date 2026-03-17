"""CDC Sync Lambda — processes CDC events and syncs to Turbopuffer.

Receives CDC change events (via EventBridge/S3 or Pub/Sub), fetches
the full record from Salesforce, denormalizes it, generates embeddings,
and upserts (or deletes) in Turbopuffer.

Environment variables:
    SALESFORCE_ORG_ID   — Salesforce org ID (e.g. 00Ddl000003yx57EAA)
    DENORM_CONFIG_PATH  — path to denorm_config.yaml (default: denorm_config.yaml)
    DLQ_URL             — SQS dead-letter queue URL for failed events
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
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
    build_soql,
    build_text,
    flatten,
)
from lib.turbopuffer_backend import TurbopufferBackend  # noqa: E402

LOG = logging.getLogger("cdc_sync")
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# CDC entity name mapping
# ---------------------------------------------------------------------------

CDC_ENTITY_MAP: dict[str, str] = {
    "ascendix__Property__ChangeEvent": "ascendix__Property__c",
    "ascendix__Lease__ChangeEvent": "ascendix__Lease__c",
    "ascendix__Availability__ChangeEvent": "ascendix__Availability__c",
    "ascendix__Deal__ChangeEvent": "ascendix__Deal__c",
    "ascendix__Sale__ChangeEvent": "ascendix__Sale__c",
    # Non-namespaced fallbacks
    "Property__ChangeEvent": "ascendix__Property__c",
    "Lease__ChangeEvent": "ascendix__Lease__c",
    "Availability__ChangeEvent": "ascendix__Availability__c",
    "Deal__ChangeEvent": "ascendix__Deal__c",
    "Sale__ChangeEvent": "ascendix__Sale__c",
    # AppFlow CDC uses SObject names (not ChangeEvent channel names) as entityName
    "ascendix__Property__c": "ascendix__Property__c",
    "ascendix__Lease__c": "ascendix__Lease__c",
    "ascendix__Availability__c": "ascendix__Availability__c",
    "ascendix__Deal__c": "ascendix__Deal__c",
    "ascendix__Sale__c": "ascendix__Sale__c",
}

# ---------------------------------------------------------------------------
# CDCEvent dataclass
# ---------------------------------------------------------------------------


@dataclass
class CDCEvent:
    """Transport-agnostic CDC event."""

    object_name: str  # e.g. "ascendix__Property__c"
    change_type: str  # CREATE | UPDATE | DELETE | UNDELETE
    record_ids: list[str]  # affected Salesforce record IDs
    commit_timestamp: int  # millis since epoch
    raw: dict = field(default_factory=dict)  # original payload for debugging


# ---------------------------------------------------------------------------
# Input adapters
# ---------------------------------------------------------------------------


def _extract_s3_coordinates(event: dict) -> tuple[str, str]:
    """Extract bucket name and object key from an S3 event.

    Supports two shapes:
    1. Transformed (from CDK input transformer in ingestion-stack.ts:897):
       {"bucket": "...", "key": "...", "eventTime": "..."}
    2. Raw EventBridge S3 notification:
       {"detail": {"bucket": {"name": "..."}, "object": {"key": "..."}}}
    """
    # Shape 1: flat/transformed (existing CDK pipeline)
    if "bucket" in event and "key" in event:
        return event["bucket"], event["key"]

    # Shape 2: raw EventBridge S3 notification
    detail = event.get("detail", {})
    bucket_obj = detail.get("bucket", {})
    object_obj = detail.get("object", {})
    if isinstance(bucket_obj, dict) and "name" in bucket_obj and isinstance(object_obj, dict) and "key" in object_obj:
        return bucket_obj["name"], object_obj["key"]

    raise ValueError(
        f"Cannot extract S3 coordinates from event. Expected flat "
        f"'bucket'+'key' or nested 'detail.bucket.name'+'detail.object.key', "
        f"got keys: {sorted(event.keys())}"
    )


def parse_eventbridge_s3_cdc(
    event: dict, s3_client: Any
) -> list[CDCEvent]:
    """Read CDC payload from S3 and parse ChangeEventHeader.

    Accepts both the CDK-transformed flat shape and the raw EventBridge
    S3 notification shape (with nested detail.bucket.name / detail.object.key).
    """
    bucket, key = _extract_s3_coordinates(event)

    response = s3_client.get_object(Bucket=bucket, Key=key)
    cdc_payload = json.loads(response["Body"].read().decode("utf-8"))

    header = cdc_payload.get("ChangeEventHeader", {})
    entity_name = header.get("entityName", "")
    change_type = header.get("changeType", "UPDATE")
    record_ids = header.get("recordIds", [])
    commit_timestamp = header.get("commitTimestamp", 0)

    object_name = CDC_ENTITY_MAP.get(entity_name)
    if object_name is None:
        # Try extracting from S3 key path as fallback
        parts = key.split("/")
        if len(parts) >= 2 and parts[0] == "cdc":
            entity_name = parts[1]
            object_name = CDC_ENTITY_MAP.get(entity_name)

    if object_name is None:
        LOG.warning("Unknown CDC entity: %s (key=%s)", entity_name, key)
        return []

    return [
        CDCEvent(
            object_name=object_name,
            change_type=change_type,
            record_ids=record_ids,
            commit_timestamp=commit_timestamp,
            raw=cdc_payload,
        )
    ]


def parse_pubsub_cdc(event: dict) -> list[CDCEvent]:
    """Parse CDC event from Salesforce Pub/Sub API.

    Not yet implemented — placeholder for Phase 3.
    """
    raise NotImplementedError("Pub/Sub CDC adapter not yet implemented")


def parse_event(event: dict, s3_client: Any) -> list[CDCEvent]:
    """Route incoming event to the correct input adapter.

    Recognises:
    - Flat S3 shape: {"bucket": ..., "key": ...}  (CDK input transformer)
    - Raw EventBridge S3: {"detail": {"bucket": {"name": ...}, "object": {"key": ...}}}
    - Pub/Sub shape: {"pubsub": ...}  (stub)
    """
    # Flat transformed shape
    if "bucket" in event and "key" in event:
        return parse_eventbridge_s3_cdc(event, s3_client)

    # Raw EventBridge S3 notification shape
    detail = event.get("detail", {})
    if isinstance(detail, dict) and "bucket" in detail and "object" in detail:
        return parse_eventbridge_s3_cdc(event, s3_client)

    if "pubsub" in event:
        return parse_pubsub_cdc(event)

    raise ValueError(
        f"Unrecognized event shape — expected flat 'bucket'+'key', "
        f"nested 'detail.bucket.name'+'detail.object.key', or 'pubsub'. "
        f"Got keys: {sorted(event.keys())}"
    )


# ---------------------------------------------------------------------------
# Module-level cold-start initialization
# ---------------------------------------------------------------------------

_denorm_config: dict | None = None
_sf_client: SalesforceClient | None = None
_bedrock_client: Any = None
_backend: TurbopufferBackend | None = None
_cloudwatch_client: Any = None
_sqs_client: Any = None
_s3_client: Any = None
_relationship_maps: dict[str, dict[str, str]] = {}


def _load_denorm_config() -> dict:
    """Load denorm config (cached at module level after first call)."""
    global _denorm_config
    if _denorm_config is None:
        config_path = os.environ.get("DENORM_CONFIG_PATH", "denorm_config.yaml")
        with open(config_path) as f:
            _denorm_config = yaml.safe_load(f)
    return _denorm_config


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


def _get_sqs_client() -> Any:
    """Get or create SQS client (cached)."""
    global _sqs_client
    if _sqs_client is None:
        _sqs_client = boto3.client("sqs")
    return _sqs_client


def _get_s3_client() -> Any:
    """Get or create S3 client (cached)."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def _get_relationship_map(
    sf_client: SalesforceClient, object_name: str
) -> dict[str, str]:
    """Get or build relationship map for an object (cached per object)."""
    if object_name not in _relationship_maps:
        desc = sf_client.describe(object_name)
        rel_map: dict[str, str] = {}
        for fld in desc["fields"]:
            if fld["type"] == "reference" and fld.get("relationshipName"):
                rel_map[fld["name"]] = fld["relationshipName"]
        _relationship_maps[object_name] = rel_map
    return _relationship_maps[object_name]


# ---------------------------------------------------------------------------
# Embedding (single-record)
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
# Freshness metrics
# ---------------------------------------------------------------------------


def _emit_freshness_metrics(
    cloudwatch_client: Any,
    object_name: str,
    commit_timestamp: int,
) -> None:
    """Emit CDC-to-processing freshness lag to CloudWatch."""
    try:
        now = datetime.now(timezone.utc)
        commit_time = datetime.fromtimestamp(
            commit_timestamp / 1000.0, tz=timezone.utc
        )
        total_lag_ms = int((now - commit_time).total_seconds() * 1000)

        cloudwatch_client.put_metric_data(
            Namespace="SalesforceAISearch/CDCSync",
            MetricData=[
                {
                    "MetricName": "CDCSyncLag",
                    "Value": total_lag_ms,
                    "Unit": "Milliseconds",
                    "Dimensions": [
                        {"Name": "SObject", "Value": object_name},
                    ],
                }
            ],
        )
        LOG.info(
            "Freshness metric: %s total_lag=%dms",
            object_name,
            total_lag_ms,
        )
    except Exception:
        LOG.exception("Failed to emit freshness metrics")


# ---------------------------------------------------------------------------
# DLQ
# ---------------------------------------------------------------------------


def _send_to_dlq(
    sqs_client: Any, dlq_url: str, cdc_event: CDCEvent, error: Exception
) -> None:
    """Send a failed event to the dead-letter queue."""
    try:
        message = {
            "object_name": cdc_event.object_name,
            "change_type": cdc_event.change_type,
            "record_ids": cdc_event.record_ids,
            "error": str(error),
            "raw": cdc_event.raw,
        }
        sqs_client.send_message(
            QueueUrl=dlq_url,
            MessageBody=json.dumps(message, default=str),
        )
        LOG.info(
            "Sent failed event to DLQ: %s %s %s",
            cdc_event.object_name,
            cdc_event.change_type,
            cdc_event.record_ids,
        )
    except Exception:
        LOG.exception("Failed to send event to DLQ")


# ---------------------------------------------------------------------------
# Sync pipeline (per-event)
# ---------------------------------------------------------------------------


def _process_cdc_event(
    cdc_event: CDCEvent,
    *,
    sf_client: SalesforceClient,
    bedrock_client: Any,
    backend: TurbopufferBackend,
    cloudwatch_client: Any,
    sqs_client: Any,
    namespace: str,
    salesforce_org_id: str,
    denorm_config: dict,
    dlq_url: str,
) -> None:
    """Process a single CDCEvent through the sync pipeline."""
    object_name = cdc_event.object_name

    # Look up object config
    obj_config = denorm_config.get(object_name)
    if obj_config is None:
        LOG.warning("No denorm config for %s — skipping", object_name)
        return

    try:
        if cdc_event.change_type == "DELETE":
            backend.delete(namespace, ids=cdc_event.record_ids)
            LOG.info(
                "Deleted %d records from %s: %s",
                len(cdc_event.record_ids),
                namespace,
                cdc_event.record_ids,
            )
        else:
            # CREATE / UPDATE / UNDELETE — full re-index
            embed_fields = obj_config.get("embed_fields", [])
            metadata_fields = obj_config.get("metadata_fields", [])
            parent_config = obj_config.get("parents", {})
            rel_map = _get_relationship_map(sf_client, object_name)

            soql_base = build_soql(
                object_name, embed_fields, metadata_fields, parent_config, rel_map
            )

            for record_id in cdc_event.record_ids:
                soql = f"{soql_base} WHERE Id = '{record_id}' LIMIT 1"
                result = sf_client.query(soql)
                records = result.get("records", [])
                if not records:
                    LOG.warning(
                        "Record %s not found for %s — may have been deleted",
                        record_id,
                        object_name,
                    )
                    continue

                record = records[0]
                direct_fields, parent_fields = flatten(
                    record, embed_fields, metadata_fields, parent_config, rel_map
                )
                text = build_text(
                    direct_fields,
                    parent_fields,
                    embed_fields,
                    parent_config,
                    object_name,
                )
                vector = _embed_single(bedrock_client, text)
                doc = build_document(
                    direct_fields=direct_fields,
                    parent_fields=parent_fields,
                    text=text,
                    vector=vector,
                    record_id=record_id,
                    object_type=object_name,
                    salesforce_org_id=salesforce_org_id,
                    embed_field_names=embed_fields,
                    metadata_field_names=metadata_fields,
                    parent_config=parent_config,
                )
                backend.upsert(
                    namespace,
                    documents=[doc],
                    schema=FULL_TEXT_SEARCH_SCHEMA,
                )
                LOG.info("Upserted %s %s", object_name, record_id)

        # Emit freshness metrics
        if cdc_event.commit_timestamp:
            _emit_freshness_metrics(
                cloudwatch_client, object_name, cdc_event.commit_timestamp
            )

    except Exception as exc:
        LOG.exception(
            "Failed to process CDC event: %s %s %s",
            cdc_event.object_name,
            cdc_event.change_type,
            cdc_event.record_ids,
        )
        if dlq_url:
            _send_to_dlq(sqs_client, dlq_url, cdc_event, exc)
        raise  # Re-raise so lambda_handler counts this as failed


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def lambda_handler(event: dict, context: Any) -> dict:
    """AWS Lambda entry point for CDC sync.

    Accepts events from EventBridge (S3-backed CDC payloads).
    """
    salesforce_org_id = os.environ.get("SALESFORCE_ORG_ID", "")
    namespace = f"org_{salesforce_org_id}"
    dlq_url = os.environ.get("DLQ_URL", "")

    s3_client = _get_s3_client()
    sf_client = _get_sf_client()
    bedrock_client = _get_bedrock_client()
    backend = _get_backend()
    cloudwatch_client = _get_cloudwatch_client()
    sqs_client = _get_sqs_client()
    denorm_config = _load_denorm_config()

    cdc_events = parse_event(event, s3_client)

    succeeded = 0
    failed = 0
    for cdc_event in cdc_events:
        try:
            _process_cdc_event(
                cdc_event,
                sf_client=sf_client,
                bedrock_client=bedrock_client,
                backend=backend,
                cloudwatch_client=cloudwatch_client,
                sqs_client=sqs_client,
                namespace=namespace,
                salesforce_org_id=salesforce_org_id,
                denorm_config=denorm_config,
                dlq_url=dlq_url,
            )
            succeeded += 1
        except Exception:
            failed += 1
            # _process_cdc_event already logged + sent to DLQ

    LOG.info("CDC sync: %d succeeded, %d failed (of %d total)", succeeded, failed, len(cdc_events))
    return {"succeeded": succeeded, "failed": failed}
