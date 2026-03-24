#!/usr/bin/env python3
"""Local CLI for Ascendix Search config refresh."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import boto3

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))
sys.path.insert(0, str(PROJECT_ROOT))

from common.salesforce_client import SalesforceClient
from lib.config_refresh import (
    ConfigArtifactStore,
    execute_config_refresh,
    execute_targeted_apply,
    rollback_to_version,
)

LOG = logging.getLogger("config_refresh_cli")


def sf_client_from_cli(target_org: str) -> SalesforceClient:
    result = subprocess.run(
        ["sf", "org", "display", "--target-org", target_org, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sf org display failed: {result.stderr}")
    payload = json.loads(result.stdout)
    org_result = payload.get("result", {})
    instance_url = org_result.get("instanceUrl")
    access_token = org_result.get("accessToken")
    if not instance_url or not access_token:
        raise RuntimeError("Could not extract Salesforce credentials from sf CLI output")
    return SalesforceClient(instance_url, access_token)


def get_sf_client(args: argparse.Namespace) -> SalesforceClient:
    if args.instance_url and args.access_token:
        return SalesforceClient(args.instance_url, args.access_token)

    instance_url = os.environ.get("SALESFORCE_INSTANCE_URL")
    access_token = os.environ.get("SALESFORCE_ACCESS_TOKEN")
    if instance_url and access_token:
        return SalesforceClient(instance_url, access_token)

    try:
        return SalesforceClient.from_ssm()
    except Exception:
        LOG.info("Falling back to sf CLI auth for %s", args.target_org)
        return sf_client_from_cli(args.target_org)


def get_org_id(sf_client: SalesforceClient) -> str:
    result = sf_client.query("SELECT Id FROM Organization LIMIT 1")
    return result["records"][0]["Id"]


POLL_SYNC_LAMBDA_NAME = "salesforce-ai-search-poll-sync"


def _make_reindex_callback(
    lambda_client: Any = None,
    poll_sync_function_name: str = POLL_SYNC_LAMBDA_NAME,
) -> Any:
    """Build a reindex callback that invokes the poll_sync Lambda.

    For seed_new_object actions, invokes with full_sync=True.
    For reindex actions, invokes with full_sync=True for the affected object.
    """
    client = lambda_client or boto3.client("lambda")

    def reindex_callback(
        object_name: str,
        action_type: str,
        full_sync: bool = False,
    ) -> dict:
        payload = json.dumps({
            "objects": [object_name],
            "full_sync": full_sync or action_type == "seed_new_object",
        })
        LOG.info(
            "Invoking %s for %s (action=%s, full_sync=%s)",
            poll_sync_function_name,
            object_name,
            action_type,
            full_sync or action_type == "seed_new_object",
        )
        response = client.invoke(
            FunctionName=poll_sync_function_name,
            InvocationType="RequestResponse",
            Payload=payload.encode("utf-8"),
        )
        response_payload = json.loads(response["Payload"].read())
        status_code = response_payload.get("statusCode", response.get("StatusCode", 0))
        if status_code != 200:
            raise RuntimeError(
                f"poll_sync Lambda returned {status_code} for {object_name}: "
                f"{json.dumps(response_payload)}"
            )
        LOG.info("Reindex result for %s: %s", object_name, json.dumps(response_payload.get("summary", {})))
        return response_payload

    return reindex_callback


def _build_store(args: argparse.Namespace) -> ConfigArtifactStore:
    return ConfigArtifactStore(
        s3_client=boto3.client("s3"),
        ssm_client=boto3.client("ssm"),
        bucket=args.bucket,
        s3_prefix=args.prefix,
    )


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-org", default="ascendix-beta-sandbox")
    parser.add_argument("--instance-url", default="")
    parser.add_argument("--access-token", default="")
    parser.add_argument("--org-id", default="")
    parser.add_argument("--bucket", default=os.environ.get("CONFIG_ARTIFACT_BUCKET", ""))
    parser.add_argument("--prefix", default=os.environ.get("CONFIG_ARTIFACT_PREFIX", "config"))


def cmd_compile(args: argparse.Namespace) -> None:
    """Compile, publish, and optionally apply a config candidate."""
    if not args.bucket:
        raise SystemExit("--bucket or CONFIG_ARTIFACT_BUCKET is required")

    sf_client = get_sf_client(args)
    org_id = args.org_id or get_org_id(sf_client)
    store = _build_store(args)

    reindex_callback = None
    if args.apply:
        poll_fn = getattr(args, "poll_sync_function", POLL_SYNC_LAMBDA_NAME)
        reindex_callback = _make_reindex_callback(poll_sync_function_name=poll_fn)

    result = execute_config_refresh(
        sf=sf_client,
        org_id=org_id,
        store=store,
        apply=args.apply,
        applied_by="scripts/run_config_refresh.py",
        target_objects=args.objects,
        reindex_callback=reindex_callback,
    )

    compile_result = result["compile_result"]
    output: dict = {
        "org_id": org_id,
        "version_id": compile_result.version_id,
        "impact_classification": compile_result.impact_classification,
        "auto_apply_eligible": compile_result.auto_apply_eligible,
        "requires_apply": compile_result.requires_apply,
        "activated": result["activated"],
        "activation_blocked_reason": result["activation_blocked_reason"],
        "stored_keys": result["stored_keys"],
        "diff": compile_result.diff,
    }
    if result.get("apply_result") is not None:
        ar = result["apply_result"]
        output["apply_plan"] = ar.apply_plan
        output["reindex_results"] = ar.reindex_results
    print(json.dumps(output, indent=2, sort_keys=True))
    if result["activation_blocked_reason"]:
        raise SystemExit(2)


def cmd_rollback(args: argparse.Namespace) -> None:
    """Roll back to a specific previous config version."""
    if not args.bucket:
        raise SystemExit("--bucket or CONFIG_ARTIFACT_BUCKET is required")
    if not args.version:
        raise SystemExit("--version is required for rollback")

    org_id = args.org_id
    if not org_id:
        sf_client = get_sf_client(args)
        org_id = get_org_id(sf_client)

    store = _build_store(args)
    result = rollback_to_version(
        store=store,
        org_id=org_id,
        target_version_id=args.version,
        rolled_back_by="scripts/run_config_refresh.py",
        reason=args.reason or "manual_rollback",
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_status(args: argparse.Namespace) -> None:
    """Show current active config version and approval state."""
    if not args.bucket:
        raise SystemExit("--bucket or CONFIG_ARTIFACT_BUCKET is required")

    org_id = args.org_id
    if not org_id:
        sf_client = get_sf_client(args)
        org_id = get_org_id(sf_client)

    store = _build_store(args)
    active_version = store.resolve_active_version(org_id)
    output: dict = {
        "org_id": org_id,
        "active_version": active_version or "(none)",
    }
    if active_version:
        approval = store.load_approval_state(org_id, active_version)
        if approval:
            output["approval_state"] = approval
    if args.version:
        approval = store.load_approval_state(org_id, args.version)
        output["queried_version"] = args.version
        output["queried_approval_state"] = approval
    print(json.dumps(output, indent=2, sort_keys=True, default=str))


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Ascendix Search config refresh control plane CLI.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # compile (default behavior)
    compile_parser = subparsers.add_parser(
        "compile",
        help="Compile and publish a config candidate, optionally applying it.",
    )
    _add_common_args(compile_parser)
    compile_parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Request activation for the candidate. For non-safe changes, "
            "runs the targeted apply workflow (seed/reindex before activation)."
        ),
    )
    compile_parser.add_argument("--objects", nargs="+", default=None, help="Optional object subset.")
    compile_parser.add_argument(
        "--poll-sync-function",
        default=POLL_SYNC_LAMBDA_NAME,
        dest="poll_sync_function",
        help="Lambda function name for targeted reindex (default: %(default)s).",
    )

    # rollback
    rollback_parser = subparsers.add_parser(
        "rollback",
        help="Roll back active config to a previous version.",
    )
    _add_common_args(rollback_parser)
    rollback_parser.add_argument("--version", required=True, help="Version ID to roll back to.")
    rollback_parser.add_argument("--reason", default="", help="Reason for rollback.")

    # status
    status_parser = subparsers.add_parser(
        "status",
        help="Show active config version and approval state.",
    )
    _add_common_args(status_parser)
    status_parser.add_argument("--version", default="", help="Query approval state for a specific version.")

    args = parser.parse_args()

    if args.command is None:
        # Backward compatible: treat bare invocation as compile
        # Re-parse with compile as default
        compile_parser.parse_args(namespace=args)
        args.command = "compile"
        if not hasattr(args, "apply"):
            args.apply = False
        if not hasattr(args, "objects"):
            args.objects = None

    if args.command == "compile":
        cmd_compile(args)
    elif args.command == "rollback":
        cmd_rollback(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
