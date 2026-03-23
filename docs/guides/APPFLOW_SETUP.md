# Amazon AppFlow Setup Guide

*Last updated: 2026-03-20*

This guide covers the current CDC transport used by the connector.

## Purpose

Amazon AppFlow moves Salesforce CDC events into S3. EventBridge then triggers
`lambda/cdc_sync`, which fetches the full record, denormalizes it, embeds it,
and upserts it into Turbopuffer.

Current live CDC-managed objects:

- `Property`
- `Lease`
- `Availability`
- `Account`
- `Contact`

## Current Architecture

```text
Salesforce CDC -> AppFlow -> S3 CDC bucket -> EventBridge -> lambda/cdc_sync
```

This is not the older Step Functions ingestion path.

## Prerequisites

- Salesforce CDC enabled for the target objects
- CDC must be enabled in Salesforce Setup for all 5 target objects (Property, Lease, Availability, Account, Contact). The sandbox CDC entity allocation is limited (typically 10 slots). Verify available slots before deployment.
- Salesforce Connected App with OAuth credentials
- AWS account with AppFlow enabled
- CDK infrastructure deployed for the CDC bucket, EventBridge rule, and `cdc_sync`

## CDC Entity Selection

Salesforce CDC requires each tracked object to occupy an entity slot on the
`ChangeEvents` platform event channel. Sandbox orgs typically have **10 slots**.

### Required CDC entities

| Object       | Change Event entity                       |
|--------------|-------------------------------------------|
| Property     | `ascendix__Property__ChangeEvent`         |
| Lease        | `ascendix__Lease__ChangeEvent`            |
| Availability | `ascendix__Availability__ChangeEvent`     |
| Account      | `AccountChangeEvent`                      |
| Contact      | `ContactChangeEvent`                      |

> **Note:** Deal and Sale use poll sync, not CDC. They should **not** consume
> CDC entity slots.

### Check current allocation

Query existing members via the Tooling API:

```bash
sf data query --query \
  "SELECT Id, SelectedEntity FROM PlatformEventChannelMember" \
  --use-tooling-api -o ascendix-beta-sandbox
```

### Add a missing entity

POST to the Tooling API to register a new CDC entity:

```bash
sf api request rest \
  "/services/data/v59.0/tooling/sobjects/PlatformEventChannelMember" \
  --method POST \
  --body '{"FullName":"ChangeEvents_AccountChangeEvent","Metadata":{"eventChannel":"ChangeEvents","selectedEntity":"AccountChangeEvent"}}' \
  -o ascendix-beta-sandbox
```

Replace the `FullName` and `selectedEntity` values for each object as needed.

### Free slots when allocation is full

If all slots are consumed and you receive the error:

```
LIMIT_EXCEEDED: You can track up to 10 entities per channel ...
```

Remove non-essential entries (e.g., `sf_devops__` entities from DevOps Center)
by DELETing their `PlatformEventChannelMember` record:

```bash
sf api request rest \
  "/services/data/v59.0/tooling/sobjects/PlatformEventChannelMember/<RECORD_ID>" \
  --method DELETE \
  -o ascendix-beta-sandbox
```

Then retry adding the required entity.

## Flow Design

Use one AppFlow per CDC object.

Recommended naming:

- `salesforce-ai-search-cdc-property`
- `salesforce-ai-search-cdc-lease`
- `salesforce-ai-search-cdc-availability`
- `salesforce-ai-search-cdc-account`
- `salesforce-ai-search-cdc-contact`

Recommended source objects:

- `ascendix__Property__ChangeEvent`
- `ascendix__Lease__ChangeEvent`
- `ascendix__Availability__ChangeEvent`
- `AccountChangeEvent`
- `ContactChangeEvent`

## Destination Layout

Recommended S3 prefix pattern:

```text
s3://salesforce-ai-search-cdc-{account}-{region}/cdc/{object}/YYYY/MM/DD/HH/
```

Each AppFlow run should write JSON CDC payloads with no custom transforms.

## Manual Setup

### 1. Create connector profile

In AWS AppFlow:

1. Create a Salesforce connector profile.
2. Use OAuth 2.0 with the Connected App credentials.
3. Authorize against the correct Salesforce instance.

### 2. Create one flow per object

For each object:

1. Source: Salesforce
2. Object: the corresponding Change Event object
3. Trigger: event-driven / incremental CDC mode
4. Destination: S3 CDC bucket
5. Prefix: `cdc/{ObjectName}/`
6. Format: JSON
7. Mapping: pass fields through directly
8. Activate the flow

## What Happens Downstream

Once a CDC object lands in S3:

1. EventBridge matches the new object under `cdc/`
2. The event invokes `lambda/cdc_sync`
3. `cdc_sync` reads the CDC payload
4. `cdc_sync` fetches the current full Salesforce record when needed
5. The record is denormalized per `denorm_config.yaml`
6. The document is embedded and upserted to Turbopuffer
7. Audit artifacts may be written if audit is enabled

## Validation Checklist

For each object:

1. Update a real record in Salesforce
2. Confirm a new file appears in the CDC bucket
3. Confirm `salesforce-ai-search-cdc-sync` logs show processing
4. Confirm the changed value is searchable through `/query`
5. Confirm delete handling matches current task expectations

## Troubleshooting

### Flow not writing to S3

- Check AppFlow execution history
- Verify the flow is activated
- Verify the connector profile is still authenticated
- Verify CDC is enabled in Salesforce for that object

### S3 object exists but search result does not update

- Check EventBridge rule targets
- Check `salesforce-ai-search-cdc-sync` CloudWatch logs
- Verify the object is part of the live CDC-managed scope
- Verify denorm config covers the changed field

### Lambda returns 401 Unauthorized on CDC event

The `cdc_sync` Lambda authenticates to Salesforce to fetch the full record. A
`401 Unauthorized` usually means the cached access token has expired.

1. **Check the SSM token.** The Lambda reads the Salesforce access token from
   SSM Parameter Store at `/salesforce/access_token`.

2. **Refresh the token.** Get a fresh token and write it to SSM:

   ```bash
   # Get a fresh token from the CLI
   sf org display -o ascendix-beta-sandbox --json | jq -r '.result.accessToken'

   # Write it to SSM
   aws ssm put-parameter \
     --name /salesforce/access_token \
     --value "<FRESH_TOKEN>" \
     --type SecureString \
     --overwrite \
     --region us-west-2
   ```

3. **Force a Lambda cold start.** The Lambda caches the Salesforce client at
   module level, so updating SSM alone will not take effect until the next cold
   start. The simplest way to force one is to redeploy the ingestion stack:

   ```bash
   npx cdk deploy SalesforceAISearch-Ingestion-dev --method=direct \
     -c salesforceInstanceUrl="$(aws ssm get-parameter --name /salesforce/instance_url --query Parameter.Value --output text)" \
     -c salesforceSecretArn="$(aws secretsmanager describe-secret --secret-id salesforce-ai-search/appflow-creds --query ARN --output text)" \
     -c salesforceJwtToken="$(python3 scripts/mint_jwt.py)"
   ```

   Alternatively, add or update any environment variable on the Lambda to
   trigger a cold start without redeploying (preserve all existing vars).

4. Re-trigger a CDC event and verify the Lambda succeeds.

### Wrong object set

Do not assume older 7-object or POC examples are correct. Trust:

1. `python3 scripts/task_manager.py`
2. `docs/architecture/object_scope_and_sync.md`
3. `README.md`

## Related Docs

- `docs/architecture/object_scope_and_sync.md`
- `README.md`
- `docs/runbooks/poll_sync.md`
