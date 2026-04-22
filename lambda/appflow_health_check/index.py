"""AppFlow CDC flow health check — publishes CDCFlowHealthy metric."""
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Prefix-match: the appflowGeneration suffix (-v2-20260421 today) rotates on
# replay resets, so we cannot hard-code full flow names.
CDC_FLOW_PREFIXES = [
    "salesforce-ai-search-cdc-account-",
    "salesforce-ai-search-cdc-contact-",
    "salesforce-ai-search-cdc-ascendix__property__c-",
    "salesforce-ai-search-cdc-ascendix__lease__c-",
    "salesforce-ai-search-cdc-ascendix__availability__c-",
]

METRIC_NAMESPACE = "SalesforceAISearch/Ingestion"
METRIC_NAME = "CDCFlowHealthy"


def lambda_handler(event, context):
    appflow = boto3.client("appflow")
    cloudwatch = boto3.client("cloudwatch")

    flows = _list_all_flows(appflow)
    matches = _match_cdc_flows(flows)
    healthy, details = _evaluate_health(matches)

    cloudwatch.put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[
            {
                "MetricName": METRIC_NAME,
                "Value": 1 if healthy else 0,
                "Unit": "Count",
            }
        ],
    )

    level = logging.INFO if healthy else logging.ERROR
    logger.log(
        level,
        "AppFlow CDC health: %s -- %s",
        "healthy" if healthy else "degraded",
        details,
    )

    return {"healthy": healthy, "details": details}


def _list_all_flows(client):
    flows = []
    next_token = None
    while True:
        kwargs = {"maxResults": 100}
        if next_token:
            kwargs["nextToken"] = next_token
        resp = client.list_flows(**kwargs)
        flows.extend(resp.get("flows", []))
        next_token = resp.get("nextToken")
        if not next_token:
            break
    return flows


def _match_cdc_flows(flows):
    matches = {p: None for p in CDC_FLOW_PREFIXES}
    for flow in flows:
        name = flow.get("flowName", "")
        for prefix in CDC_FLOW_PREFIXES:
            if name.startswith(prefix):
                matches[prefix] = {
                    "name": name,
                    "status": flow.get("flowStatus", "UNKNOWN"),
                }
                break
    return matches


def _evaluate_health(matches):
    missing = [p for p, m in matches.items() if m is None]
    degraded = [
        {"name": m["name"], "status": m["status"]}
        for m in matches.values()
        if m is not None and m["status"] != "Active"
    ]
    healthy = not missing and not degraded
    return healthy, {
        "missing_prefixes": missing,
        "degraded_flows": degraded,
        "total_matched": sum(1 for m in matches.values() if m is not None),
    }
