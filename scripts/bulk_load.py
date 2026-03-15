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
from pathlib import Path
from typing import Any

# Add project root and lambda dir to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))

from common.salesforce_client import SalesforceClient
from lib.turbopuffer_backend import TurbopufferBackend

LOG = logging.getLogger("bulk_load")

# Embedding constants
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024
EMBED_BATCH_SIZE = 25

# Upsert constants
UPSERT_BATCH_SIZE = 100
FULL_TEXT_SEARCH_SCHEMA = {"text": {"type": "string", "full_text_search": True}}


# ===================================================================
# Config parsing
# ===================================================================

def load_config(config_path: str) -> dict[str, Any]:
    """Load denorm_config.yaml and return parsed dict."""
    import yaml

    with open(config_path) as f:
        return yaml.safe_load(f)


# ===================================================================
# Field name utilities
# ===================================================================

def clean_label(field_name: str) -> str:
    """Strip namespace prefix and custom suffixes for human-readable labels.

    ascendix__City__c -> City, ascendix__Property__r -> Property, Name -> Name
    """
    return field_name.replace("ascendix__", "").replace("__c", "").replace("__r", "")


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
# Stage 1: SOQL construction + query
# ===================================================================

def build_soql(
    object_name: str,
    embed_fields: list[str],
    metadata_fields: list[str],
    parent_config: dict[str, list[str]],
    rel_map: dict[str, str],
) -> str:
    """Build SELECT SOQL with direct fields + parent relationship fields."""
    select_parts: list[str] = ["Id", "LastModifiedDate"]
    seen: set[str] = set(select_parts)

    # Direct fields (embed + metadata), deduped
    for f in embed_fields + metadata_fields:
        if f not in seen:
            select_parts.append(f)
            seen.add(f)

    # Parent relationship fields
    for ref_field, parent_fields in parent_config.items():
        rel_name = rel_map[ref_field]  # already validated
        # Include the FK field itself if not already present
        if ref_field not in seen:
            select_parts.append(ref_field)
            seen.add(ref_field)
        for pf in parent_fields:
            dotted = f"{rel_name}.{pf}"
            if dotted not in seen:
                select_parts.append(dotted)
                seen.add(dotted)

    return f"SELECT {', '.join(select_parts)} FROM {object_name}"


# ===================================================================
# Stage 2: Flatten
# ===================================================================

def flatten(
    record: dict,
    embed_fields: list[str],
    metadata_fields: list[str],
    parent_config: dict[str, list[str]],
    rel_map: dict[str, str],
) -> tuple[dict, dict]:
    """Extract direct_fields and parent_fields from a raw SF record.

    Returns:
        direct_fields: {raw_field_name: value} for embed + metadata + system fields
        parent_fields: {ref_field: {raw_parent_field: value}} per config
    """
    direct_fields: dict[str, Any] = {}
    for f in embed_fields + metadata_fields:
        val = record.get(f)
        if val is not None:
            direct_fields[f] = val

    # System fields always present
    direct_fields["Id"] = record["Id"]
    direct_fields["LastModifiedDate"] = record.get("LastModifiedDate")

    parent_fields: dict[str, dict] = {}
    for ref_field, pfield_names in parent_config.items():
        rel_name = rel_map[ref_field]
        parent_record = record.get(rel_name) or {}
        pvals: dict[str, Any] = {}
        for pf in pfield_names:
            val = parent_record.get(pf)
            if val is not None:
                pvals[pf] = val
        parent_fields[ref_field] = pvals

    return direct_fields, parent_fields


# ===================================================================
# Stage 3: Text generation
# ===================================================================

def build_text(
    direct_fields: dict,
    parent_fields: dict,
    embed_field_names: list[str],
    parent_config: dict,
    object_type: str,
) -> str:
    """Build embedding text from direct + parent fields.

    Lookups use raw SF names; labels are cleaned for readability.
    """
    parts: list[str] = [f"{clean_label(object_type)}:"]

    # Direct embed fields
    for field in embed_field_names:
        val = direct_fields.get(field)
        if val is not None:
            parts.append(f"{clean_label(field)}: {val}")

    # Parent denormalized fields
    for ref_field, pfield_names in parent_config.items():
        parent_vals = parent_fields.get(ref_field, {})
        for pf in pfield_names:
            val = parent_vals.get(pf)
            if val is not None:
                parts.append(f"{clean_label(pf)}: {val}")

    return " | ".join(parts)


# ===================================================================
# Stage 4: Document building
# ===================================================================

def build_document(
    direct_fields: dict,
    parent_fields: dict,
    text: str,
    vector: list[float],
    record_id: str,
    object_type: str,
    salesforce_org_id: str,
    embed_field_names: list[str],
    metadata_field_names: list[str],
    parent_config: dict,
) -> dict:
    """Build final Turbopuffer document with cleaned attribute keys."""
    doc: dict[str, Any] = {
        "id": record_id,
        "vector": vector,
        "text": text,
        "object_type": clean_label(object_type).lower(),
        "last_modified": direct_fields.get("LastModifiedDate", ""),
        "salesforce_org_id": salesforce_org_id,
    }

    # Direct fields with cleaned keys
    for f in embed_field_names + metadata_field_names:
        val = direct_fields.get(f)
        if val is not None:
            doc[clean_label(f).lower()] = val

    # Parent fields with prefixed cleaned keys
    for ref_field, pfield_names in parent_config.items():
        prefix = clean_label(ref_field).lower()
        parent_vals = parent_fields.get(ref_field, {})
        for pf in pfield_names:
            val = parent_vals.get(pf)
            if val is not None:
                doc[f"{prefix}_{clean_label(pf).lower()}"] = val

    return doc


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
) -> int:
    """Run full pipeline for one object. Returns count of documents."""
    LOG.info("=== Processing %s ===", object_name)

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
    LOG.info("  Fetched %d records", len(records))

    if not records:
        return 0

    # Stage 2 + 3: Flatten + build text
    texts: list[str] = []
    flat_data: list[tuple[dict, dict]] = []
    for record in records:
        direct_fields, parent_fields = flatten(
            record, embed_fields, metadata_fields, parent_config, rel_map
        )
        text = build_text(
            direct_fields, parent_fields, embed_fields, parent_config, object_name
        )
        texts.append(text)
        flat_data.append((direct_fields, parent_fields))

    if dry_run:
        LOG.info("  [DRY RUN] Sample texts:")
        for idx, text in enumerate(texts[:3]):
            LOG.info("    [%d] %s", idx, text[:200])
        LOG.info("  [DRY RUN] Sample document keys (first record):")
        sample_doc = build_document(
            direct_fields=flat_data[0][0],
            parent_fields=flat_data[0][1],
            text=texts[0],
            vector=[0.0] * 8,  # placeholder
            record_id=flat_data[0][0]["Id"],
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
        return len(records)

    # Stage 3.5: Embed
    LOG.info("  Embedding %d texts...", len(texts))
    vectors = embed_texts(bedrock_client, texts)

    # Stage 4: Build documents
    documents: list[dict] = []
    for idx, (direct_fields, parent_fields) in enumerate(flat_data):
        doc = build_document(
            direct_fields=direct_fields,
            parent_fields=parent_fields,
            text=texts[idx],
            vector=vectors[idx],
            record_id=direct_fields["Id"],
            object_type=object_name,
            salesforce_org_id=salesforce_org_id,
            embed_field_names=embed_fields,
            metadata_field_names=metadata_fields,
            parent_config=parent_config,
        )
        documents.append(doc)

    # Stage 5: Upsert
    LOG.info("  Upserting %d documents to %s...", len(documents), namespace)
    upsert_documents(backend, namespace, documents)
    LOG.info("  Done: %d documents loaded for %s", len(documents), object_name)

    return len(documents)


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
    total = 0
    for obj_name in object_names:
        count = load_object(
            sf_client=sf,
            bedrock_client=bedrock_client,
            backend=backend,
            object_name=obj_name,
            object_config=config[obj_name],
            namespace=namespace,
            salesforce_org_id=org_id,
            dry_run=args.dry_run,
        )
        total += count

    LOG.info(
        "=== Complete: %d documents across %d objects ===",
        total,
        len(object_names),
    )


if __name__ == "__main__":
    main()
