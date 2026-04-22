"""AppFlow CDC flow health check — publishes CDCFlowHealthy metric."""
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Match both suffixed and unsuffixed flow names. CDK builds names as
# "salesforce-ai-search-cdc-{object}{-appflowGeneration}" where the suffix is
# empty when the context value is not provided. When appflowGeneration is set
# (today: "v2-20260421"), the suffix rotates on replay resets.
CDC_FLOW_BASES = [
    "salesforce-ai-search-cdc-account",
    "salesforce-ai-search-cdc-contact",
    "salesforce-ai-search-cdc-ascendix__property__c",
    "salesforce-ai-search-cdc-ascendix__lease__c",
    "salesforce-ai-search-cdc-ascendix__availability__c",
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
    # List per base rather than a single entry: during a generation replacement
    # an old Suspended flow and a new Active flow can briefly coexist. Keeping
    # both means the evaluator can flag the stale flow instead of letting
    # AppFlow list-order hide it.
    matches = {base: [] for base in CDC_FLOW_BASES}
    for flow in flows:
        name = flow.get("flowName", "")
        for base in CDC_FLOW_BASES:
            # Exact base (no appflowGeneration) or base followed by "-<suffix>".
            if name == base or name.startswith(f"{base}-"):
                matches[base].append(
                    {
                        "name": name,
                        "status": flow.get("flowStatus", "UNKNOWN"),
                    }
                )
                break
    return matches


def _evaluate_health(matches):
    missing = [base for base, found in matches.items() if not found]
    degraded = [
        {"name": m["name"], "status": m["status"]}
        for found in matches.values()
        for m in found
        if m["status"] != "Active"
    ]
    healthy = not missing and not degraded
    return healthy, {
        "missing_flows": missing,
        "degraded_flows": degraded,
        "total_matched": sum(len(found) for found in matches.values()),
    }
