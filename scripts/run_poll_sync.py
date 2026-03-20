#!/usr/bin/env python3
"""CLI wrapper for poll sync — runs locally, not through Lambda.

Usage:
    python3 scripts/run_poll_sync.py --objects ascendix__Deal__c ascendix__Sale__c
    python3 scripts/run_poll_sync.py --objects ascendix__Deal__c --full-sync
    python3 scripts/run_poll_sync.py --objects ascendix__Deal__c --full-sync \
        --target-org ascendix-beta-sandbox
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add lambda dir FIRST so poll_sync.index resolves to lambda/poll_sync/index.py
# (not this script). Then project root for lib.* imports.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))
sys.path.insert(0, str(PROJECT_ROOT))

import boto3
import yaml

from common.salesforce_client import SalesforceClient
from lib.turbopuffer_backend import TurbopufferBackend
from poll_sync.index import _sync_object

LOG = logging.getLogger("poll_sync_cli")


# ===================================================================
# Salesforce auth cascade (same as bulk_load.py)
# ===================================================================

def sf_client_from_cli(target_org: str) -> SalesforceClient:
    """Create SalesforceClient using sf CLI credentials."""
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


def get_sf_client(args: argparse.Namespace) -> SalesforceClient:
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


def get_org_id(sf_client: SalesforceClient) -> str:
    """Get the Salesforce org ID."""
    records = sf_client.query("SELECT Id FROM Organization LIMIT 1")
    return records["records"][0]["Id"]


# ===================================================================
# Main
# ===================================================================

def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Poll Salesforce for changed records and sync to Turbopuffer.",
    )
    parser.add_argument(
        "--objects",
        nargs="+",
        required=True,
        help="Salesforce objects to poll (e.g., ascendix__Deal__c)",
    )
    parser.add_argument(
        "--full-sync",
        action="store_true",
        help="Reset watermark to epoch and re-sync all records",
    )
    parser.add_argument(
        "--config",
        default=str(PROJECT_ROOT / "denorm_config.yaml"),
        help="Path to denorm_config.yaml",
    )
    parser.add_argument(
        "--target-org",
        default="ascendix-beta-sandbox",
        help="sf CLI alias for fallback auth (default: ascendix-beta-sandbox)",
    )
    parser.add_argument("--instance-url", default="")
    parser.add_argument("--access-token", default="")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Records per SOQL page (default: 200)",
    )

    args = parser.parse_args()

    # Load denorm config
    with open(args.config) as f:
        denorm_config = yaml.safe_load(f.read())

    # Validate requested objects exist in config
    for obj in args.objects:
        if obj not in denorm_config:
            LOG.error(
                "Object '%s' not found in config. Available: %s",
                obj,
                list(denorm_config.keys()),
            )
            sys.exit(1)

    # Connect to Salesforce
    sf = get_sf_client(args)
    org_id = get_org_id(sf)
    namespace = f"org_{org_id}"
    LOG.info("Namespace: %s", namespace)

    # Initialize clients
    bedrock_client = boto3.client("bedrock-runtime")
    backend = TurbopufferBackend()
    ssm_client = boto3.client("ssm")
    cloudwatch_client = boto3.client("cloudwatch")

    # Sync each object
    summary: dict[str, Any] = {}
    for obj in args.objects:
        LOG.info("=== Polling %s ===", obj)
        result = _sync_object(
            obj,
            full_sync=args.full_sync,
            context=None,
            sf_client=sf,
            bedrock_client=bedrock_client,
            backend=backend,
            cloudwatch_client=cloudwatch_client,
            ssm_client=ssm_client,
            denorm_config=denorm_config,
            namespace=namespace,
            salesforce_org_id=org_id,
            page_size=args.batch_size,
        )
        summary[obj] = result

    # Print summary
    LOG.info("=== Poll Sync Complete ===")
    for obj, result in summary.items():
        LOG.info(
            "  %s: %d records synced, watermark=%s%s",
            obj,
            result["records_synced"],
            result["watermark"],
            " (continuation needed)" if result.get("continuation_needed") else "",
        )


if __name__ == "__main__":
    main()
