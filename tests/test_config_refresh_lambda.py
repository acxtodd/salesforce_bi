"""Tests for the config_refresh Lambda entrypoint."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _import_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "config_refresh_lambda",
        Path(_PROJECT_ROOT) / "lambda" / "config_refresh" / "index.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["config_refresh_lambda"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_mod = _import_module()


def test_handler_requires_org_id(monkeypatch):
    monkeypatch.delenv("SALESFORCE_ORG_ID", raising=False)
    response = _mod.lambda_handler({}, None)
    assert response["statusCode"] == 400


@patch("config_refresh_lambda.execute_config_refresh")
@patch("config_refresh_lambda.ConfigArtifactStore")
@patch("config_refresh_lambda.SalesforceClient")
@patch("config_refresh_lambda.boto3")
def test_handler_returns_refresh_summary(mock_boto3, MockSalesforceClient, MockStore, mock_execute, monkeypatch):
    monkeypatch.setenv("SALESFORCE_ORG_ID", "00DTEST")
    monkeypatch.setenv("CONFIG_ARTIFACT_BUCKET", "config-bucket")

    MockSalesforceClient.from_ssm.return_value = MagicMock()
    mock_store = MockStore.return_value
    mock_execute.return_value = {
        "compile_result": MagicMock(
            version_id="20260324T010203Z-abc123def456",
            impact_classification="prompt_only",
            auto_apply_eligible=True,
            requires_apply=False,
            diff={"classification": "prompt_only"},
        ),
        "stored_keys": {"compiled": "config/00DTEST/compiled/test.yaml"},
        "activated": True,
        "activation_blocked_reason": "",
    }

    response = _mod.lambda_handler({}, None)

    assert response["statusCode"] == 200
    assert response["body"]["version_id"] == "20260324T010203Z-abc123def456"
    assert response["body"]["impact_classification"] == "prompt_only"
    MockStore.assert_called_once()
    mock_execute.assert_called_once()
    assert mock_store is MockStore.return_value


@patch("config_refresh_lambda.execute_config_refresh")
@patch("config_refresh_lambda.ConfigArtifactStore")
@patch("config_refresh_lambda.SalesforceClient")
@patch("config_refresh_lambda.boto3")
def test_handler_returns_conflict_when_activation_is_blocked(
    mock_boto3,
    MockSalesforceClient,
    MockStore,
    mock_execute,
    monkeypatch,
):
    monkeypatch.setenv("SALESFORCE_ORG_ID", "00DTEST")
    monkeypatch.setenv("CONFIG_ARTIFACT_BUCKET", "config-bucket")

    MockSalesforceClient.from_ssm.return_value = MagicMock()
    mock_execute.return_value = {
        "compile_result": MagicMock(
            version_id="20260324T010203Z-abc123def456",
            impact_classification="field_scope_change",
            auto_apply_eligible=False,
            requires_apply=True,
            diff={"classification": "field_scope_change"},
        ),
        "stored_keys": {"compiled": "config/00DTEST/compiled/test.yaml"},
        "activated": False,
        "activation_blocked_reason": "blocked",
    }

    response = _mod.lambda_handler({"apply": True}, None)

    assert response["statusCode"] == 409
    assert response["body"]["activation_blocked_reason"] == "blocked"
