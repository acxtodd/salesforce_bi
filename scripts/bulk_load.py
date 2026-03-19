#!/usr/bin/env python3
"""
Bulk Loader for AscendixIQ Salesforce Connector (Task 0.4).

Exports Salesforce CRE data via REST API, denormalizes parent fields,
generates embeddings via Bedrock Titan v2, and upserts into Turbopuffer.

Usage:
    # Dry run (prints sample docs, skips embed/upsert)
    python3 scripts/bulk_load.py --config denorm_config.yaml --dry-run

    # Full load with sf CLI auth
    python3 scripts/bulk_load.py --config denorm_config.yaml \\
        --target-org ascendix-beta-sandbox

    # Full load with explicit credentials
    python3 scripts/bulk_load.py --config denorm_config.yaml \\
        --instance-url https://... --access-token 00D...
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add project root and lambda dir to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))

from common.salesforce_client import SalesforceClient
from lib.denormalize import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_ID,
    FULL_TEXT_SEARCH_SCHEMA,
    build_tpuf_schema,
    build_document,
    build_relationship_map as build_relationship_spec_map,
    build_soql,
    build_text,
    clean_label,
    flatten,
)
from lib.audit_writer import (
    DEFAULT_AUDIT_CONCURRENCY,
    AuditingBackend,
    write_config_snapshot,
    write_denorm_audit,
)
from lib.turbopuffer_backend import TurbopufferBackend

LOG = logging.getLogger("bulk_load")

# Batch size constants (CLI-specific)
EMBED_BATCH_SIZE = 25
UPSERT_BATCH_SIZE = 100
DEFAULT_EMBEDDING_CONCURRENCY = 4
DEFAULT_AUDIT_WRITE_CONCURRENCY = DEFAULT_AUDIT_CONCURRENCY
EMBED_MAX_ATTEMPTS = 5
EMBEDDING_CONCURRENCY_ENV = "BULK_LOAD_EMBED_CONCURRENCY"
AUDIT_CONCURRENCY_ENV = "BULK_LOAD_AUDIT_CONCURRENCY"


@dataclass
class LoadSummary:
    """Structured per-object load result used for logging and verification."""

    object_name: str
    fetched_count: int = 0
    indexed_count: int = 0
    skipped_count: int = 0
    turbopuffer_count: int | None = None
    count_mismatch: bool = False
    skipped_ids: list[str] = field(default_factory=list)
    denorm_audit_ok: int = 0
    denorm_audit_failed: int = 0
    stage_timings: dict[str, float] = field(default_factory=dict)


# ===================================================================
# Config parsing
# ===================================================================

def load_config(config_path: str) -> dict[str, Any]:
    """Load denorm_config.yaml and return parsed dict."""
    import yaml

    with open(config_path) as f:
        return yaml.safe_load(f)


def load_config_with_raw(config_path: str) -> tuple[dict[str, Any], str]:
    """Load denorm_config.yaml and return ``(parsed_dict, raw_yaml_str)``.

    Use this when the caller needs byte-for-byte provenance (e.g. audit trail).
    """
    import yaml

    with open(config_path) as f:
        raw = f.read()
    return yaml.safe_load(raw), raw


# ===================================================================
# Salesforce auth cascade
# ===================================================================

def sf_client_from_cli(target_org: str) -> SalesforceClient:
    """Create SalesforceClient using sf CLI credentials."""
    import subprocess

    result = subprocess.run(
        ["sf", "org", "display", "--target-org", target_org, "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sf org display failed: {result.stderr}")
    data = json.loads(result.stdout)
    org_result = data.get("result", {})
    instance_url = org_result.get("instanceUrl")
    access_token = org_result.get("accessToken")
    if not instance_url or not access_token:
        raise RuntimeError("Could not extract credentials from sf CLI output")
    return SalesforceClient(instance_url, access_token)


def get_sf_client(args) -> SalesforceClient:
    """Resolve SalesforceClient: CLI args -> env vars -> SSM -> sf CLI."""
    # 1. Explicit CLI args
    if args.instance_url and args.access_token:
        LOG.info("Using credentials from CLI args")
        return SalesforceClient(args.instance_url, args.access_token)
    # 2. Environment variables
    instance_url = os.environ.get("SALESFORCE_INSTANCE_URL")
    access_token = os.environ.get("SALESFORCE_ACCESS_TOKEN")
    if instance_url and access_token:
        LOG.info("Using credentials from environment variables")
        return SalesforceClient(instance_url, access_token)
    # 3. SSM Parameter Store
    try:
        LOG.info("Trying SSM Parameter Store...")
        return SalesforceClient.from_ssm()
    except Exception:
        pass
    # 4. sf CLI fallback
    LOG.info("Falling back to sf CLI (target-org: %s)", args.target_org)
    return sf_client_from_cli(args.target_org)


# ===================================================================
# Relationship map & validation
# ===================================================================

def build_relationship_map(
    sf_client: SalesforceClient, object_name: str
) -> dict[str, dict[str, str]]:
    """Return lookup metadata for all reference fields on an object."""
    return build_relationship_spec_map(sf_client, object_name)


def validate_parents(
    rel_map: dict, config_parents: dict, object_name: str
) -> None:
    """Fail fast if any configured parent ref field has no relationshipName."""
    for ref_field in config_parents:
        if ref_field not in rel_map:
            raise ValueError(
                f"{object_name}: parent ref field '{ref_field}' has no "
                f"relationshipName in describe metadata. Cannot build SOQL. "
                f"Check denorm_config.yaml -- this field may not be a valid "
                f"reference or may have been removed from the org."
            )


# ===================================================================
# Embedding
# ===================================================================

def _is_throttling(exc: Exception) -> bool:
    """Check if an exception is a Bedrock throttling error."""
    if hasattr(exc, "response"):
        return exc.response.get("Error", {}).get("Code") == "ThrottlingException"
    return False


def _normalize_concurrency(value: int | None, *, default: int, label: str) -> int:
    """Return a validated positive concurrency value."""
    if value is None:
        return default
    if value < 1:
        raise ValueError(f"{label} must be >= 1 (got {value})")
    return value


def resolve_embedding_concurrency(explicit: int | None = None) -> int:
    """Resolve embedding concurrency from CLI or environment."""
    if explicit is not None:
        return _normalize_concurrency(
            explicit,
            default=DEFAULT_EMBEDDING_CONCURRENCY,
            label="embedding concurrency",
        )
    env_value = os.getenv(EMBEDDING_CONCURRENCY_ENV)
    if env_value:
        try:
            parsed = int(env_value)
        except ValueError as exc:
            raise ValueError(
                f"{EMBEDDING_CONCURRENCY_ENV} must be an integer >= 1 (got {env_value!r})"
            ) from exc
        return _normalize_concurrency(
            parsed,
            default=DEFAULT_EMBEDDING_CONCURRENCY,
            label=f"{EMBEDDING_CONCURRENCY_ENV}",
        )
    return DEFAULT_EMBEDDING_CONCURRENCY


def resolve_audit_concurrency(explicit: int | None = None) -> int:
    """Resolve audit write concurrency from CLI or environment."""
    if explicit is not None:
        return _normalize_concurrency(
            explicit,
            default=DEFAULT_AUDIT_WRITE_CONCURRENCY,
            label="audit concurrency",
        )
    env_value = os.getenv(AUDIT_CONCURRENCY_ENV)
    if env_value:
        try:
            parsed = int(env_value)
        except ValueError as exc:
            raise ValueError(
                f"{AUDIT_CONCURRENCY_ENV} must be an integer >= 1 (got {env_value!r})"
            ) from exc
        return _normalize_concurrency(
            parsed,
            default=DEFAULT_AUDIT_WRITE_CONCURRENCY,
            label=f"{AUDIT_CONCURRENCY_ENV}",
        )
    return DEFAULT_AUDIT_WRITE_CONCURRENCY


def create_s3_audit_client(audit_concurrency: int) -> Any:
    """Create an S3 client sized for the configured audit writer concurrency."""
    import boto3
    from botocore.config import Config

    resolved_concurrency = _normalize_concurrency(
        audit_concurrency,
        default=DEFAULT_AUDIT_WRITE_CONCURRENCY,
        label="audit concurrency",
    )
    return boto3.client(
        "s3",
        config=Config(max_pool_connections=max(resolved_concurrency, 10)),
    )


def _generate_embedding_request(
    bedrock_client: Any, text: str
) -> list[float]:
    """Generate a single embedding request via Bedrock Titan v2."""
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


def _embed_text_with_retry(
    bedrock_client: Any,
    text: str,
    *,
    request_index: int,
) -> list[float]:
    """Embed one text with per-request retry on throttling."""
    backoff = 1.0
    for attempt in range(EMBED_MAX_ATTEMPTS):
        try:
            return _generate_embedding_request(bedrock_client, text)
        except Exception as exc:
            if _is_throttling(exc):
                LOG.warning(
                    "  Throttled request %d, retrying in %.1fs (attempt %d/%d)",
                    request_index,
                    backoff,
                    attempt + 1,
                    EMBED_MAX_ATTEMPTS,
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
    raise RuntimeError(
        f"Embedding failed after {EMBED_MAX_ATTEMPTS} attempts for request {request_index}"
    )


def _embed_batch_results(
    bedrock_client: Any,
    texts: list[str],
    *,
    batch_start: int,
    concurrency: int,
) -> list[list[float] | Exception]:
    """Embed a logical batch concurrently and preserve input ordering."""
    if not texts:
        return []

    worker_count = min(
        len(texts),
        _normalize_concurrency(
            concurrency,
            default=DEFAULT_EMBEDDING_CONCURRENCY,
            label="embedding concurrency",
        ),
    )
    ordered_results: list[list[float] | Exception | None] = [None] * len(texts)
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(
                _embed_text_with_retry,
                bedrock_client,
                text,
                request_index=batch_start + idx,
            ): idx
            for idx, text in enumerate(texts)
        }
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                ordered_results[idx] = fut.result()
            except Exception as exc:
                ordered_results[idx] = exc
    return [result for result in ordered_results if result is not None]


def generate_embeddings_batch(
    bedrock_client: Any,
    texts: list[str],
    *,
    concurrency: int = DEFAULT_EMBEDDING_CONCURRENCY,
) -> list[list[float]]:
    """Generate embeddings for a logical batch with bounded concurrency."""
    results = _embed_batch_results(
        bedrock_client,
        texts,
        batch_start=0,
        concurrency=concurrency,
    )
    for result in results:
        if isinstance(result, Exception):
            raise result
    return [result for result in results if not isinstance(result, Exception)]


def embed_texts(
    bedrock_client: Any,
    texts: list[str],
    *,
    concurrency: int = DEFAULT_EMBEDDING_CONCURRENCY,
) -> list[list[float]]:
    """Embed all texts in batches of 25 with bounded concurrency."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        LOG.info(
            "  Embedding batch %d (%d texts, concurrency=%d)",
            i // EMBED_BATCH_SIZE + 1,
            len(batch),
            min(len(batch), _normalize_concurrency(
                concurrency,
                default=DEFAULT_EMBEDDING_CONCURRENCY,
                label="embedding concurrency",
            )),
        )
        embeddings = generate_embeddings_batch(
            bedrock_client,
            batch,
            concurrency=concurrency,
        )
        all_embeddings.extend(embeddings)
    return all_embeddings


# ===================================================================
# Upsert
# ===================================================================

def upsert_documents(
    backend: TurbopufferBackend,
    namespace: str,
    documents: list[dict],
) -> None:
    """Upsert documents in batches of 100. Schema on first batch only."""
    if not documents:
        return
    schema = build_tpuf_schema(documents, base_schema=FULL_TEXT_SEARCH_SCHEMA)
    for i in range(0, len(documents), UPSERT_BATCH_SIZE):
        batch = documents[i : i + UPSERT_BATCH_SIZE]
        LOG.info(
            "  Upserting batch %d (%d docs)",
            i // UPSERT_BATCH_SIZE + 1,
            len(batch),
        )
        backend.upsert(
            namespace,
            documents=batch,
            schema=schema if i == 0 else None,
        )


def _embed_records_with_tolerance(
    bedrock_client: Any,
    prepared_rows: list[dict[str, Any]],
    *,
    concurrency: int,
) -> tuple[list[list[float]], list[dict[str, Any]], list[str]]:
    """Embed rows in batches, skipping only records that fail all retries."""
    embeddings: list[list[float]] = []
    embedded_rows: list[dict[str, Any]] = []
    skipped_ids: list[str] = []

    for i in range(0, len(prepared_rows), EMBED_BATCH_SIZE):
        batch_rows = prepared_rows[i : i + EMBED_BATCH_SIZE]
        batch_texts = [row["text"] for row in batch_rows]
        LOG.info(
            "  Embedding batch %d (%d texts, concurrency=%d)",
            i // EMBED_BATCH_SIZE + 1,
            len(batch_rows),
            min(
                len(batch_rows),
                _normalize_concurrency(
                    concurrency,
                    default=DEFAULT_EMBEDDING_CONCURRENCY,
                    label="embedding concurrency",
                ),
            ),
        )
        batch_results = _embed_batch_results(
            bedrock_client,
            batch_texts,
            batch_start=i,
            concurrency=concurrency,
        )
        for row, result in zip(batch_rows, batch_results):
            record_id = row["record_id"]
            if isinstance(result, Exception):
                LOG.warning(
                    "  Skipping record %s during embedding: %s", record_id, result
                )
                skipped_ids.append(record_id)
                continue
            embeddings.append(result)
            embedded_rows.append(row)

    return embeddings, embedded_rows, skipped_ids


def _write_denorm_audits(
    audit_s3_client: Any,
    audit_bucket: str,
    salesforce_org_id: str,
    object_name: str,
    prepared_rows: list[dict[str, Any]],
    *,
    audit_concurrency: int,
) -> tuple[int, int]:
    """Write denorm audit artifacts with bounded shared concurrency."""
    if not prepared_rows:
        return 0, 0

    def _write_denorm(row: dict[str, Any]) -> bool:
        return write_denorm_audit(
            audit_s3_client,
            audit_bucket,
            salesforce_org_id,
            record_id=row["record_id"],
            object_type=object_name,
            direct_fields=row["direct_fields"],
            parent_fields=row["parent_fields"],
            text=row["text"],
            salesforce_org_id=salesforce_org_id,
            last_modified=row["direct_fields"].get("LastModifiedDate"),
        )

    ok = 0
    failed = 0
    worker_count = min(
        len(prepared_rows),
        _normalize_concurrency(
            audit_concurrency,
            default=DEFAULT_AUDIT_WRITE_CONCURRENCY,
            label="audit concurrency",
        ),
    )
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(_write_denorm, row) for row in prepared_rows]
        for fut in as_completed(futures):
            if fut.result():
                ok += 1
            else:
                failed += 1
    return ok, failed


def _log_stage_timings(prefix: str, stage_timings: dict[str, float]) -> None:
    """Emit stable human-readable stage timing output."""
    ordered_keys = ("fetch", "prep_audit", "embed", "upsert", "total")
    parts = [
        f"{key}={stage_timings[key]:.2f}s"
        for key in ordered_keys
        if key in stage_timings
    ]
    LOG.info("%s stage timings: %s", prefix, " ".join(parts))


def _count_indexed_docs(
    backend: TurbopufferBackend | None, namespace: str, object_name: str
) -> int | None:
    """Return final Turbopuffer count for one object type when available."""
    if backend is None:
        return None
    obj_type = clean_label(object_name).lower()
    try:
        result = backend.aggregate(
            namespace,
            filters={"object_type": obj_type},
            aggregate="count",
        )
    except Exception as exc:
        LOG.error("  Could not verify post-load count for %s: %s", object_name, exc)
        return None
    return int(result.get("count", 0))


# ===================================================================
# Org ID
# ===================================================================

def get_org_id(sf_client: SalesforceClient) -> str:
    """Get the Salesforce org ID."""
    records = sf_client.query("SELECT Id FROM Organization LIMIT 1")
    return records["records"][0]["Id"]


# ===================================================================
# Main pipeline
# ===================================================================

def load_object(
    sf_client: SalesforceClient,
    bedrock_client: Any,
    backend: TurbopufferBackend | None,
    object_name: str,
    object_config: dict,
    namespace: str,
    salesforce_org_id: str,
    dry_run: bool = False,
    audit_s3_client: Any = None,
    audit_bucket: str = "",
    embedding_concurrency: int = DEFAULT_EMBEDDING_CONCURRENCY,
    audit_write_concurrency: int = DEFAULT_AUDIT_WRITE_CONCURRENCY,
) -> LoadSummary:
    """Run full pipeline for one object and return a structured summary."""
    LOG.info("=== Processing %s ===", object_name)
    summary = LoadSummary(object_name=object_name)
    object_started = time.perf_counter()

    embed_fields = object_config.get("embed_fields", [])
    metadata_fields = object_config.get("metadata_fields", [])
    parent_config = object_config.get("parents", {})

    # Build relationship map and validate parents
    rel_map = build_relationship_map(sf_client, object_name)
    validate_parents(rel_map, parent_config, object_name)

    # Stage 1: Query
    soql = build_soql(
        object_name, embed_fields, metadata_fields, parent_config, rel_map
    )
    LOG.info("  SOQL: %s", soql[:200])
    fetch_started = time.perf_counter()
    records = sf_client.query_all(soql)
    summary.stage_timings["fetch"] = time.perf_counter() - fetch_started
    summary.fetched_count = len(records)
    LOG.info("  Fetched %d records", summary.fetched_count)

    if not records:
        summary.stage_timings["prep_audit"] = 0.0
        summary.stage_timings["embed"] = 0.0
        summary.stage_timings["upsert"] = 0.0
        summary.stage_timings["total"] = time.perf_counter() - object_started
        _log_stage_timings(f"  {object_name}", summary.stage_timings)
        return summary

    # Stage 2 + 3: Flatten + build text
    prep_started = time.perf_counter()
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
        except Exception as exc:
            LOG.warning(
                "  Skipping record %s during flatten/text preparation: %s",
                record_id,
                exc,
            )
            summary.skipped_count += 1
            summary.skipped_ids.append(record_id)
            continue
        prepared_rows.append(
            {
                "record_id": record_id,
                "direct_fields": direct_fields,
                "parent_fields": parent_fields,
                "text": text,
            }
        )

    # Stage 2.5: Write denorm audit artifacts (pre-vector, human-readable)
    if audit_s3_client and audit_bucket and prepared_rows and not dry_run:
        denorm_audit_ok, denorm_audit_failed = _write_denorm_audits(
            audit_s3_client,
            audit_bucket,
            salesforce_org_id,
            object_name,
            prepared_rows,
            audit_concurrency=audit_write_concurrency,
        )
        summary.denorm_audit_ok = denorm_audit_ok
        summary.denorm_audit_failed = denorm_audit_failed
        if isinstance(backend, AuditingBackend):
            backend.stats.denorm_audit_ok += denorm_audit_ok
            backend.stats.denorm_audit_failed += denorm_audit_failed
        LOG.info(
            "  Denorm audit: ok=%d failed=%d",
            denorm_audit_ok,
            denorm_audit_failed,
        )
    summary.stage_timings["prep_audit"] = time.perf_counter() - prep_started

    if dry_run:
        LOG.info("  [DRY RUN] Sample texts:")
        for idx, row in enumerate(prepared_rows[:3]):
            text = row["text"]
            LOG.info("    [%d] %s", idx, text[:200])
        if prepared_rows:
            LOG.info("  [DRY RUN] Sample document keys (first record):")
            sample = prepared_rows[0]
            sample_doc = build_document(
                direct_fields=sample["direct_fields"],
                parent_fields=sample["parent_fields"],
                text=sample["text"],
                vector=[0.0] * 8,  # placeholder
                record_id=sample["record_id"],
                object_type=object_name,
                salesforce_org_id=salesforce_org_id,
                embed_field_names=embed_fields,
                metadata_field_names=metadata_fields,
                parent_config=parent_config,
                rel_map=rel_map,
            )
            for k, v in sample_doc.items():
                if k == "vector":
                    LOG.info("    %s: [placeholder]", k)
                else:
                    LOG.info("    %s: %s", k, str(v)[:80])
        summary.indexed_count = len(prepared_rows)
        summary.stage_timings["embed"] = 0.0
        summary.stage_timings["upsert"] = 0.0
        summary.stage_timings["total"] = time.perf_counter() - object_started
        _log_stage_timings(f"  {object_name}", summary.stage_timings)
        return summary

    if not prepared_rows:
        LOG.warning("  No valid records remained after preparation")
        summary.turbopuffer_count = _count_indexed_docs(backend, namespace, object_name)
        summary.stage_timings["embed"] = 0.0
        summary.stage_timings["upsert"] = 0.0
        summary.stage_timings["total"] = time.perf_counter() - object_started
        _log_stage_timings(f"  {object_name}", summary.stage_timings)
        return summary

    # Stage 3.5: Embed
    LOG.info("  Embedding %d texts...", len(prepared_rows))
    embed_started = time.perf_counter()
    vectors, embedded_rows, embed_skipped_ids = _embed_records_with_tolerance(
        bedrock_client,
        prepared_rows,
        concurrency=embedding_concurrency,
    )
    summary.stage_timings["embed"] = time.perf_counter() - embed_started
    summary.skipped_count += len(embed_skipped_ids)
    summary.skipped_ids.extend(embed_skipped_ids)

    # Stage 4: Build documents
    documents: list[dict] = []
    for idx, row in enumerate(embedded_rows):
        record_id = row["record_id"]
        try:
            doc = build_document(
                direct_fields=row["direct_fields"],
                parent_fields=row["parent_fields"],
                text=row["text"],
                vector=vectors[idx],
                record_id=record_id,
                object_type=object_name,
                salesforce_org_id=salesforce_org_id,
                embed_field_names=embed_fields,
                metadata_field_names=metadata_fields,
                parent_config=parent_config,
                rel_map=rel_map,
            )
        except Exception as exc:
            LOG.warning("  Skipping record %s during document build: %s", record_id, exc)
            summary.skipped_count += 1
            summary.skipped_ids.append(record_id)
            continue
        documents.append(doc)

    summary.indexed_count = len(documents)

    # Stage 5: Upsert
    LOG.info("  Upserting %d documents to %s...", len(documents), namespace)
    upsert_started = time.perf_counter()
    upsert_documents(backend, namespace, documents)
    summary.stage_timings["upsert"] = time.perf_counter() - upsert_started
    summary.turbopuffer_count = _count_indexed_docs(backend, namespace, object_name)
    if summary.turbopuffer_count is None:
        summary.count_mismatch = True
        LOG.error(
            "  Post-load count verification unavailable for %s: fetched=%d indexed=%d skipped=%d",
            object_name,
            summary.fetched_count,
            summary.indexed_count,
            summary.skipped_count,
        )
    elif summary.turbopuffer_count != summary.indexed_count:
        summary.count_mismatch = True
        LOG.error(
            "  Post-load count mismatch for %s: fetched=%d indexed=%d skipped=%d turbopuffer=%d",
            object_name,
            summary.fetched_count,
            summary.indexed_count,
            summary.skipped_count,
            summary.turbopuffer_count,
        )
    else:
        LOG.info(
            "  Done: fetched=%d indexed=%d skipped=%d turbopuffer=%d",
            summary.fetched_count,
            summary.indexed_count,
            summary.skipped_count,
            summary.turbopuffer_count,
        )

    summary.stage_timings["total"] = time.perf_counter() - object_started
    _log_stage_timings(f"  {object_name}", summary.stage_timings)
    return summary


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Bulk load Salesforce CRE data into Turbopuffer.",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to denorm_config.yaml",
    )
    parser.add_argument(
        "--objects",
        nargs="+",
        help="Subset of objects to load (default: all in config)",
    )
    parser.add_argument(
        "--namespace",
        help="Turbopuffer namespace (default: org_{sf_org_id})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Export + denormalize + build text only; skip embed/upsert",
    )
    parser.add_argument(
        "--target-org",
        default="ascendix-beta-sandbox",
        help="sf CLI alias for fallback auth (default: ascendix-beta-sandbox)",
    )
    parser.add_argument("--instance-url", default="")
    parser.add_argument("--access-token", default="")
    parser.add_argument(
        "--audit-bucket",
        default="salesforce-ai-search-audit-382211616288-us-west-2",
        help="S3 bucket for audit trail. Defaults to the project audit bucket. "
        "Pass empty string to disable: --audit-bucket ''",
    )
    parser.add_argument(
        "--embedding-concurrency",
        type=int,
        default=None,
        help=(
            "Max concurrent Bedrock embedding requests per logical batch "
            f"(default: env {EMBEDDING_CONCURRENCY_ENV} or {DEFAULT_EMBEDDING_CONCURRENCY})."
        ),
    )
    parser.add_argument(
        "--audit-concurrency",
        type=int,
        default=None,
        help=(
            "Max concurrent S3 audit writes for denorm and replay artifacts "
            f"(default: env {AUDIT_CONCURRENCY_ENV} or {DEFAULT_AUDIT_WRITE_CONCURRENCY})."
        ),
    )

    args = parser.parse_args()
    try:
        embedding_concurrency = resolve_embedding_concurrency(
            args.embedding_concurrency
        )
        audit_write_concurrency = resolve_audit_concurrency(
            args.audit_concurrency
        )
    except ValueError as exc:
        parser.error(str(exc))

    # Load config
    config, raw_yaml_str = load_config_with_raw(args.config)

    # Determine which objects to load
    object_names = args.objects or list(config.keys())
    for obj in object_names:
        if obj not in config:
            LOG.error(
                "Object '%s' not found in config. Available: %s",
                obj,
                list(config.keys()),
            )
            sys.exit(1)

    # Connect to Salesforce
    sf = get_sf_client(args)

    # Get org ID for namespace
    org_id = get_org_id(sf)
    namespace = args.namespace or f"org_{org_id}"
    LOG.info("Namespace: %s", namespace)
    LOG.info(
        "Loader concurrency: embedding=%d audit=%d",
        embedding_concurrency,
        audit_write_concurrency,
    )

    # Initialize Bedrock + Turbopuffer (only if not dry-run)
    bedrock_client = None
    backend = None
    audit_s3_client = None
    if not args.dry_run:
        import boto3

        bedrock_client = boto3.client("bedrock-runtime")
        backend = TurbopufferBackend()

        # Wrap with audit writer if --audit-bucket provided
        if args.audit_bucket:
            audit_s3_client = create_s3_audit_client(audit_write_concurrency)
            backend = AuditingBackend(
                backend,
                audit_s3_client,
                args.audit_bucket,
                org_id,
                audit_concurrency=audit_write_concurrency,
            )
            write_config_snapshot(
                audit_s3_client, args.audit_bucket, org_id,
                config, raw_yaml_str, "bulk_load",
            )

    # Process each object
    run_started = time.perf_counter()
    total_fetched = 0
    total_indexed = 0
    total_skipped = 0
    total_denorm_audit_ok = 0
    total_denorm_audit_failed = 0
    aggregate_stage_timings = {
        "fetch": 0.0,
        "prep_audit": 0.0,
        "embed": 0.0,
        "upsert": 0.0,
    }
    audit_bkt = args.audit_bucket if audit_s3_client else ""
    for obj_name in object_names:
        summary = load_object(
            sf_client=sf,
            bedrock_client=bedrock_client,
            backend=backend,
            object_name=obj_name,
            object_config=config[obj_name],
            namespace=namespace,
            salesforce_org_id=org_id,
            dry_run=args.dry_run,
            audit_s3_client=audit_s3_client,
            audit_bucket=audit_bkt,
            embedding_concurrency=embedding_concurrency,
            audit_write_concurrency=audit_write_concurrency,
        )
        total_fetched += summary.fetched_count
        total_indexed += summary.indexed_count
        total_skipped += summary.skipped_count
        total_denorm_audit_ok += summary.denorm_audit_ok
        total_denorm_audit_failed += summary.denorm_audit_failed
        for key in aggregate_stage_timings:
            aggregate_stage_timings[key] += summary.stage_timings.get(key, 0.0)

    if isinstance(backend, AuditingBackend):
        LOG.info(
            "Audit stats: replay_ok=%d replay_failed=%d denorm_ok=%d denorm_failed=%d",
            backend.stats.audit_ok,
            backend.stats.audit_failed,
            backend.stats.denorm_audit_ok,
            backend.stats.denorm_audit_failed,
        )
    elif audit_s3_client:
        LOG.info(
            "Audit stats: replay_ok=%d replay_failed=%d denorm_ok=%d denorm_failed=%d",
            0,
            0,
            total_denorm_audit_ok,
            total_denorm_audit_failed,
        )

    aggregate_stage_timings["total"] = time.perf_counter() - run_started
    _log_stage_timings("Bulk load total", aggregate_stage_timings)
    LOG.info(
        "=== Complete: fetched=%d indexed=%d skipped=%d across %d objects ===",
        total_fetched,
        total_indexed,
        total_skipped,
        len(object_names),
    )


if __name__ == "__main__":
    main()
