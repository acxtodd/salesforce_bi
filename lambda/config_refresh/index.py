"""Config refresh Lambda for Ascendix Search control-plane updates."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import boto3

_this_dir = Path(__file__).resolve().parent
_project_root = _this_dir.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "lambda"))
sys.path.insert(0, str(_this_dir))

from common.salesforce_client import SalesforceClient  # noqa: E402
from lib.config_refresh import ConfigArtifactStore, execute_config_refresh  # noqa: E402

LOG = logging.getLogger("config_refresh")
LOG.setLevel(os.getenv("LOG_LEVEL", "INFO"))


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    org_id = str(event.get("org_id") or os.environ.get("SALESFORCE_ORG_ID", "")).strip()
    if not org_id:
        return {"statusCode": 400, "error": "org_id is required"}

    bucket = str(os.environ.get("CONFIG_ARTIFACT_BUCKET", "")).strip()
    if not bucket:
        return {"statusCode": 500, "error": "CONFIG_ARTIFACT_BUCKET is not configured"}

    sf_client = SalesforceClient.from_ssm()
    store = ConfigArtifactStore(
        s3_client=boto3.client("s3"),
        ssm_client=boto3.client("ssm"),
        bucket=bucket,
        s3_prefix=os.getenv("CONFIG_ARTIFACT_PREFIX", "config"),
    )

    refresh_result = execute_config_refresh(
        sf=sf_client,
        org_id=org_id,
        store=store,
        apply=bool(event.get("apply", False)),
        applied_by="lambda/config_refresh",
        target_objects=event.get("objects"),
    )
    compile_result = refresh_result["compile_result"]
    body = {
        "version_id": compile_result.version_id,
        "impact_classification": compile_result.impact_classification,
        "auto_apply_eligible": compile_result.auto_apply_eligible,
        "requires_apply": compile_result.requires_apply,
        "activated": refresh_result["activated"],
        "activation_blocked_reason": refresh_result.get("activation_blocked_reason", ""),
        "stored_keys": refresh_result["stored_keys"],
        "diff": compile_result.diff,
    }
    LOG.info("Config refresh complete: %s", json.dumps(body, sort_keys=True))
    status_code = 409 if body["activation_blocked_reason"] else 200
    return {"statusCode": status_code, "body": body}
