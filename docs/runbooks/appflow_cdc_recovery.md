# AppFlow CDC Recovery Runbook

Operational runbook for the `salesforce-ai-search-cdc-flow-health-critical`
CloudWatch alarm. The alarm fires when any of the 5 Salesforce CDC AppFlow
flows transitions to a non-Active state (for example, Suspended by
Salesforce after a Cometd replay-ID expiry).

## Purpose

Salesforce CDC AppFlow flows can silently suspend when a subscription is
rejected by Salesforce (aged-out replay IDs, credential rotation, entity
selection changes). Suspended flows emit no `FlowExecutionsFailed` metric
because no execution is attempted, which is how the 2026-04-16 to
2026-04-21 CDC outage went undetected for 5 days.

This runbook covers detection, recovery, and validation. The detection
mechanism is a scheduled health-check Lambda
(`salesforce-ai-search-appflow-health-check`) that calls `appflow:ListFlows`
every 5 minutes and publishes
`SalesforceAISearch/Ingestion::CDCFlowHealthy` (1 = all 5 flows Active,
0 = one or more non-Active or missing).

## When The Alarm Fires

The alarm is critical. It fires when `CDCFlowHealthy` is less than 1 for
3 consecutive 5-minute datapoints (15-minute SLA). It also fires if the
health-check Lambda itself stops publishing (missing data is treated as
breaching).

Expected CDC flows matched by prefix:

- `salesforce-ai-search-cdc-account-*`
- `salesforce-ai-search-cdc-contact-*`
- `salesforce-ai-search-cdc-ascendix__property__c-*`
- `salesforce-ai-search-cdc-ascendix__lease__c-*`
- `salesforce-ai-search-cdc-ascendix__availability__c-*`

Suffix rotates on replay resets (set by CDK context `appflowGeneration`).

## Immediate Checks

1. Confirm the alarm condition in AWS:
   ```
   aws appflow list-flows --region us-west-2 \
     --query 'flows[?starts_with(flowName, `salesforce-ai-search-cdc-`)].{name:flowName,status:flowStatus}' \
     --output table
   ```
2. Identify which flows are non-Active. Common states:
   - `Suspended` — Salesforce-side subscription rejected. Most common.
   - `Errored` — repeated AppFlow execution failures.
   - Missing — flow was deleted or never created in this environment.
3. Check the health-check Lambda itself:
   ```
   aws logs tail /aws/lambda/salesforce-ai-search-appflow-health-check \
     --region us-west-2 --since 30m
   ```
   If no invocations or consistent errors, the alarm is firing on missing
   data; fix the Lambda first.
4. Check the Salesforce access token freshness and expected CDC entity
   selection (see `docs/runbooks/poll_sync.md` and `environments.md`).

## Recovery: Resume vs Replace Decision Tree

Two recovery paths, determined by the 2026-04-21 incident:

- **Resume (`aws appflow start-flow`)**: works for flows that suspended
  on transient issues (credential hiccup, short outage). Does NOT work
  when the Cometd replay ID has aged out. Try resume once. If the flow
  suspends again within minutes, go to replace.
- **Replace (CDK redeploy with a fresh `appflowGeneration` context
  value)**: required when replay IDs are stale. This is the
  known-good recovery from 2026-04-21.

### Resume

```
aws appflow start-flow \
  --flow-name salesforce-ai-search-cdc-account-v2-20260421 \
  --region us-west-2
```

Wait 5 minutes. Re-check `flowStatus`. If back to Suspended, resume has
failed — move to replace.

### Replace (CDK redeploy)

1. Choose a new generation suffix (typically today's date, e.g.
   `v3-20260422`).
2. Deploy with the new suffix:
   ```
   npx cdk deploy SalesforceAISearch-Ingestion-dev --method=direct \
     -c salesforceInstanceUrl="$(aws ssm get-parameter --name /salesforce/instance_url --region us-west-2 --query Parameter.Value --output text)" \
     -c salesforceSecretArn="$(aws secretsmanager describe-secret --secret-id salesforce-ai-search/appflow-creds --region us-west-2 --query ARN --output text)" \
     -c salesforceJwtToken="$(python3 scripts/mint_jwt.py)" \
     -c appflowGeneration=v3-20260422
   ```
3. CDK will create new flows with fresh replay-ID subscriptions and
   delete the stale ones.
4. Confirm new flows are Active via `aws appflow list-flows`.

## Validation After Recovery

A successful `appflow list-flows` return is not user-visible validation.
Confirm end-to-end:

1. Make a controlled edit in the Salesforce sandbox on a record of each
   affected object type.
2. Confirm `cdc_sync` logs show `Upserted <object> <record_id>` within
   the 5-minute SLA:
   ```
   aws logs tail /aws/lambda/salesforce-ai-search-cdc-sync \
     --region us-west-2 --since 10m | grep Upserted
   ```
3. Run `/query` against the edited record and confirm the updated value
   is searchable.

## Failure Modes To Watch

- Resuming a Suspended flow repeatedly without checking Salesforce-side
  replay-ID state. Resume will succeed briefly then re-suspend.
- Declaring recovery on the basis of `appflow list-flows` showing Active
  without a user-visible `/query` validation.
- Redeploying with the same `appflowGeneration` value — that is a no-op
  CFN and does NOT reset replay IDs.
- Ignoring the alarm because CDC lag metrics still look fine — a newly
  Suspended flow emits no events at all, so CDC lag can look healthy
  even while the flow is broken.

## Related Docs

- `docs/runbooks/poll_sync.md`
- `environments.md`
- `README.md`
- `CLAUDE.md`
