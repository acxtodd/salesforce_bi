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
    build_document,
    build_soql,
    build_text,
    clean_label,
    flatten,
)
from lib.turbopuffer_backend import TurbopufferBackend

LOG = logging.getLogger("bulk_load")

# Batch size constants (CLI-specific)
EMBED_BATCH_SIZE = 25
UPSERT_BATCH_SIZE = 100


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


# ===================================================================
# Config parsing
# ===================================================================

def load_config(config_path: str) -> dict[str, Any]:
    """Load denorm_config.yaml and return parsed dict."""
    import yaml

    with open(config_path) as f:
        return yaml.safe_load(f)


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
) -> dict[str, str]:
    """Return {field_api_name: relationshipName} for all reference fields."""
    desc = sf_client.describe(object_name)
    rel_map = {}
    for field in desc["fields"]:
        if field["type"] == "reference" and field.get("relationshipName"):
            rel_map[field["name"]] = field["relationshipName"]
    return rel_map


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


def generate_embeddings_batch(
    bedrock_client: Any, texts: list[str]
) -> list[list[float]]:
    """Generate embeddings for a batch of texts using Bedrock Titan v2."""
    embeddings: list[list[float]] = []
    for text in texts:
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
        embeddings.append(response_body["embedding"])
    return embeddings


def embed_texts(
    bedrock_client: Any, texts: list[str]
) -> list[list[float]]:
    """Embed all texts in batches of 25 with retry on throttling."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        LOG.info(
            "  Embedding batch %d (%d texts)",
            i // EMBED_BATCH_SIZE + 1,
            len(batch),
        )
        backoff = 1.0
        for attempt in range(5):
            try:
                embeddings = generate_embeddings_batch(bedrock_client, batch)
                all_embeddings.extend(embeddings)
                break
            except Exception as e:
                if _is_throttling(e):
                    LOG.warning(
                        "  Throttled, retrying in %.1fs (attempt %d)",
                        backoff,
                        attempt + 1,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                else:
                    raise
        else:
            raise RuntimeError(
                f"Embedding failed after 5 attempts for batch starting at {i}"
            )
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
    for i in range(0, len(documents), UPSERT_BATCH_SIZE):
        batch = documents[i : i + UPSERT_BATCH_SIZE]
        schema = FULL_TEXT_SEARCH_SCHEMA if i == 0 else None
        LOG.info(
            "  Upserting batch %d (%d docs)",
            i // UPSERT_BATCH_SIZE + 1,
            len(batch),
        )
        backend.upsert(namespace, documents=batch, schema=schema)


def _embed_batch_with_retry(
    bedrock_client: Any, texts: list[str], *, batch_start: int
) -> list[list[float]]:
    """Embed one batch with retry on throttling."""
    backoff = 1.0
    for attempt in range(5):
        try:
            return generate_embeddings_batch(bedrock_client, texts)
        except Exception as e:
            if _is_throttling(e):
                LOG.warning(
                    "  Throttled, retrying in %.1fs (attempt %d)",
                    backoff,
                    attempt + 1,
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
    raise RuntimeError(
        f"Embedding failed after 5 attempts for batch starting at {batch_start}"
    )


def _embed_records_with_tolerance(
    bedrock_client: Any, prepared_rows: list[dict[str, Any]]
) -> tuple[list[list[float]], list[dict[str, Any]], list[str]]:
    """Embed rows in batches, falling back to per-record skip on hard failures."""
    embeddings: list[list[float]] = []
    embedded_rows: list[dict[str, Any]] = []
    skipped_ids: list[str] = []

    for i in range(0, len(prepared_rows), EMBED_BATCH_SIZE):
        batch_rows = prepared_rows[i : i + EMBED_BATCH_SIZE]
        batch_texts = [row["text"] for row in batch_rows]
        LOG.info(
            "  Embedding batch %d (%d texts)",
            i // EMBED_BATCH_SIZE + 1,
            len(batch_rows),
        )
        try:
            batch_embeddings = _embed_batch_with_retry(
                bedrock_client, batch_texts, batch_start=i
            )
            embeddings.extend(batch_embeddings)
            embedded_rows.extend(batch_rows)
            continue
        except Exception as exc:
            LOG.warning(
                "  Embedding batch %d failed (%s); retrying per record",
                i // EMBED_BATCH_SIZE + 1,
                exc,
            )

        for row in batch_rows:
            record_id = row["record_id"]
            try:
                vector = _embed_batch_with_retry(
                    bedrock_client, [row["text"]], batch_start=i
                )[0]
            except Exception as exc:
                LOG.warning(
                    "  Skipping record %s during embedding: %s", record_id, exc
                )
                skipped_ids.append(record_id)
                continue
            embeddings.append(vector)
            embedded_rows.append(row)

    return embeddings, embedded_rows, skipped_ids


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
) -> LoadSummary:
    """Run full pipeline for one object and return a structured summary."""
    LOG.info("=== Processing %s ===", object_name)
    summary = LoadSummary(object_name=object_name)

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
    records = sf_client.query_all(soql)
    summary.fetched_count = len(records)
    LOG.info("  Fetched %d records", summary.fetched_count)

    if not records:
        return summary

    # Stage 2 + 3: Flatten + build text
    prepared_rows: list[dict[str, Any]] = []
    for record in records:
        record_id = record.get("Id", "<unknown>")
        try:
            direct_fields, parent_fields = flatten(
                record, embed_fields, metadata_fields, parent_config, rel_map
            )
            text = build_text(
                direct_fields, parent_fields, embed_fields, parent_config, object_name
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
            )
            for k, v in sample_doc.items():
                if k == "vector":
                    LOG.info("    %s: [placeholder]", k)
                else:
                    LOG.info("    %s: %s", k, str(v)[:80])
        summary.indexed_count = len(prepared_rows)
        return summary

    if not prepared_rows:
        LOG.warning("  No valid records remained after preparation")
        summary.turbopuffer_count = _count_indexed_docs(backend, namespace, object_name)
        return summary

    # Stage 3.5: Embed
    LOG.info("  Embedding %d texts...", len(prepared_rows))
    vectors, embedded_rows, embed_skipped_ids = _embed_records_with_tolerance(
        bedrock_client, prepared_rows
    )
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
    upsert_documents(backend, namespace, documents)
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

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

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

    # Initialize Bedrock + Turbopuffer (only if not dry-run)
    bedrock_client = None
    backend = None
    if not args.dry_run:
        import boto3

        bedrock_client = boto3.client("bedrock-runtime")
        backend = TurbopufferBackend()

    # Process each object
    total_fetched = 0
    total_indexed = 0
    total_skipped = 0
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
        )
        total_fetched += summary.fetched_count
        total_indexed += summary.indexed_count
        total_skipped += summary.skipped_count

    LOG.info(
        "=== Complete: fetched=%d indexed=%d skipped=%d across %d objects ===",
        total_fetched,
        total_indexed,
        total_skipped,
        len(object_names),
    )


if __name__ == "__main__":
    main()
