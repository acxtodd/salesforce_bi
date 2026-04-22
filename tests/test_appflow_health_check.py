"""Unit tests for lambda/appflow_health_check/index.py — boto3 mocked."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))

from appflow_health_check.index import (
    CDC_FLOW_BASES,
    METRIC_NAME,
    METRIC_NAMESPACE,
    _evaluate_health,
    _list_all_flows,
    _match_cdc_flows,
    lambda_handler,
)


def _flow(name, status="Active"):
    return {"flowName": name, "flowStatus": status}


def _all_active_flows():
    return [
        _flow("salesforce-ai-search-cdc-account-v2-20260421"),
        _flow("salesforce-ai-search-cdc-contact-v2-20260421"),
        _flow("salesforce-ai-search-cdc-ascendix__property__c-v2-20260421"),
        _flow("salesforce-ai-search-cdc-ascendix__lease__c-v2-20260421"),
        _flow("salesforce-ai-search-cdc-ascendix__availability__c-v2-20260421"),
    ]


class TestListAllFlows:
    def test_single_page(self):
        client = MagicMock()
        client.list_flows.return_value = {"flows": _all_active_flows()}
        flows = _list_all_flows(client)
        assert len(flows) == 5
        client.list_flows.assert_called_once_with(maxResults=100)

    def test_multi_page(self):
        client = MagicMock()
        page1 = _all_active_flows()[:2]
        page2 = _all_active_flows()[2:]
        client.list_flows.side_effect = [
            {"flows": page1, "nextToken": "abc"},
            {"flows": page2},
        ]
        flows = _list_all_flows(client)
        assert len(flows) == 5
        assert client.list_flows.call_count == 2
        second_call = client.list_flows.call_args_list[1]
        assert second_call.kwargs == {"maxResults": 100, "nextToken": "abc"}


class TestMatchCdcFlows:
    def test_all_five_match(self):
        matches = _match_cdc_flows(_all_active_flows())
        assert all(found for found in matches.values())
        assert len(matches) == 5

    def test_match_with_arbitrary_suffix(self):
        flows = [_flow("salesforce-ai-search-cdc-account-v9-99999999")]
        matches = _match_cdc_flows(flows)
        base = "salesforce-ai-search-cdc-account"
        assert matches[base][0]["name"] == flows[0]["flowName"]

    def test_match_unsuffixed_name(self):
        # When appflowGeneration CDK context is not set, flow names have no
        # trailing suffix. These must still match.
        flows = [
            _flow("salesforce-ai-search-cdc-account"),
            _flow("salesforce-ai-search-cdc-contact"),
            _flow("salesforce-ai-search-cdc-ascendix__property__c"),
            _flow("salesforce-ai-search-cdc-ascendix__lease__c"),
            _flow("salesforce-ai-search-cdc-ascendix__availability__c"),
        ]
        matches = _match_cdc_flows(flows)
        assert all(found for found in matches.values())
        assert (
            matches["salesforce-ai-search-cdc-account"][0]["name"]
            == "salesforce-ai-search-cdc-account"
        )

    def test_missing_flow_yields_empty_list(self):
        flows = [f for f in _all_active_flows() if "account" not in f["flowName"]]
        matches = _match_cdc_flows(flows)
        base = "salesforce-ai-search-cdc-account"
        assert matches[base] == []

    def test_unrelated_flow_ignored(self):
        flows = _all_active_flows() + [_flow("salesforce-ai-search-poll-sync")]
        matches = _match_cdc_flows(flows)
        assert sum(1 for found in matches.values() if found) == 5

    def test_similar_but_non_matching_flow_ignored(self):
        # "accountability" must not match the "account" base — we require
        # either an exact match or a "-" separator after the base.
        flows = [_flow("salesforce-ai-search-cdc-accountability")]
        matches = _match_cdc_flows(flows)
        assert matches["salesforce-ai-search-cdc-account"] == []

    def test_status_propagates(self):
        flows = [_flow("salesforce-ai-search-cdc-account-x", status="Suspended")]
        matches = _match_cdc_flows(flows)
        base = "salesforce-ai-search-cdc-account"
        assert matches[base][0]["status"] == "Suspended"

    def test_captures_all_generations_for_a_base(self):
        # During a generation replacement, both the old and the new generation
        # can briefly coexist in AppFlow. The matcher must retain both so the
        # evaluator can flag any non-Active copy.
        flows = [
            _flow("salesforce-ai-search-cdc-account-v1-old", status="Suspended"),
            _flow("salesforce-ai-search-cdc-account-v2-new", status="Active"),
        ]
        matches = _match_cdc_flows(flows)
        base = "salesforce-ai-search-cdc-account"
        assert len(matches[base]) == 2
        statuses = {m["status"] for m in matches[base]}
        assert statuses == {"Suspended", "Active"}


class TestDuplicateGenerationOrdering:
    """Health evaluation must not depend on list_flows ordering.

    Regression guard for the PR #24 review finding: when old (Suspended) and
    new (Active) generations coexist for the same CDC base, either ordering
    must report degraded.
    """

    def _make_flows_plus_dup(self, dup_pair):
        base_flows = _all_active_flows()[1:]  # drop the account Active flow
        return dup_pair + base_flows

    def test_suspended_old_then_active_new_reports_degraded(self):
        flows = self._make_flows_plus_dup(
            [
                _flow(
                    "salesforce-ai-search-cdc-account-v1-old", status="Suspended"
                ),
                _flow(
                    "salesforce-ai-search-cdc-account-v2-new", status="Active"
                ),
            ]
        )
        matches = _match_cdc_flows(flows)
        healthy, details = _evaluate_health(matches)
        assert healthy is False
        assert any(
            d["status"] == "Suspended" and "v1-old" in d["name"]
            for d in details["degraded_flows"]
        )

    def test_active_new_then_suspended_old_reports_degraded(self):
        flows = self._make_flows_plus_dup(
            [
                _flow(
                    "salesforce-ai-search-cdc-account-v2-new", status="Active"
                ),
                _flow(
                    "salesforce-ai-search-cdc-account-v1-old", status="Suspended"
                ),
            ]
        )
        matches = _match_cdc_flows(flows)
        healthy, details = _evaluate_health(matches)
        assert healthy is False
        assert any(
            d["status"] == "Suspended" and "v1-old" in d["name"]
            for d in details["degraded_flows"]
        )


class TestEvaluateHealth:
    def test_all_active_is_healthy(self):
        matches = _match_cdc_flows(_all_active_flows())
        healthy, details = _evaluate_health(matches)
        assert healthy is True
        assert details["missing_flows"] == []
        assert details["degraded_flows"] == []
        assert details["total_matched"] == 5

    def test_any_suspended_is_degraded(self):
        flows = _all_active_flows()
        flows[0]["flowStatus"] = "Suspended"
        matches = _match_cdc_flows(flows)
        healthy, details = _evaluate_health(matches)
        assert healthy is False
        assert len(details["degraded_flows"]) == 1
        assert details["degraded_flows"][0]["status"] == "Suspended"

    def test_missing_flow_is_degraded(self):
        flows = _all_active_flows()[:4]
        matches = _match_cdc_flows(flows)
        healthy, details = _evaluate_health(matches)
        assert healthy is False
        assert len(details["missing_flows"]) == 1
        assert details["total_matched"] == 4

    def test_both_missing_and_suspended(self):
        flows = _all_active_flows()[:4]
        flows[0]["flowStatus"] = "Errored"
        matches = _match_cdc_flows(flows)
        healthy, details = _evaluate_health(matches)
        assert healthy is False
        assert len(details["missing_flows"]) == 1
        assert len(details["degraded_flows"]) == 1


class TestLambdaHandler:
    def _patched_clients(self, flows):
        appflow = MagicMock()
        appflow.list_flows.return_value = {"flows": flows}
        cloudwatch = MagicMock()
        return appflow, cloudwatch

    def test_healthy_emits_value_1(self):
        appflow, cloudwatch = self._patched_clients(_all_active_flows())
        with patch("boto3.client") as boto_factory:
            boto_factory.side_effect = (
                lambda svc, **kw: appflow if svc == "appflow" else cloudwatch
            )
            result = lambda_handler({}, None)
        assert result["healthy"] is True
        cloudwatch.put_metric_data.assert_called_once()
        call = cloudwatch.put_metric_data.call_args
        assert call.kwargs["Namespace"] == METRIC_NAMESPACE
        metric = call.kwargs["MetricData"][0]
        assert metric["MetricName"] == METRIC_NAME
        assert metric["Value"] == 1

    def test_degraded_emits_value_0(self):
        flows = _all_active_flows()
        flows[1]["flowStatus"] = "Suspended"
        appflow, cloudwatch = self._patched_clients(flows)
        with patch("boto3.client") as boto_factory:
            boto_factory.side_effect = (
                lambda svc, **kw: appflow if svc == "appflow" else cloudwatch
            )
            result = lambda_handler({}, None)
        assert result["healthy"] is False
        metric = cloudwatch.put_metric_data.call_args.kwargs["MetricData"][0]
        assert metric["Value"] == 0

    def test_missing_flow_emits_value_0(self):
        flows = _all_active_flows()[:3]
        appflow, cloudwatch = self._patched_clients(flows)
        with patch("boto3.client") as boto_factory:
            boto_factory.side_effect = (
                lambda svc, **kw: appflow if svc == "appflow" else cloudwatch
            )
            result = lambda_handler({}, None)
        assert result["healthy"] is False
        metric = cloudwatch.put_metric_data.call_args.kwargs["MetricData"][0]
        assert metric["Value"] == 0


class TestConstants:
    def test_five_cdc_flow_bases(self):
        assert len(CDC_FLOW_BASES) == 5
        for base in CDC_FLOW_BASES:
            assert base.startswith("salesforce-ai-search-cdc-")
            assert not base.endswith("-")

    def test_metric_namespace_matches_alarm(self):
        assert METRIC_NAMESPACE == "SalesforceAISearch/Ingestion"
        assert METRIC_NAME == "CDCFlowHealthy"
