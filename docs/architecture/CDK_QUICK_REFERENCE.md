# CDK Infrastructure Quick Reference

*Last updated: 2026-03-20*

## Active Stack Set

The active CDK app currently includes:

1. `NetworkStack`
2. `DataStack`
3. `IngestionStack`
4. `ApiStack`
5. `MonitoringStack`

`SearchStack` has been removed from the active app.

## Deployment Order

```text
NetworkStack
  -> DataStack
  -> IngestionStack
  -> ApiStack
  -> MonitoringStack
```

In practice, use `cdk diff` / `cdk deploy` with awareness of cross-stack
references and current environment state.

## Stack Summary

| Stack | Purpose | Key Resources |
|---|---|---|
| `NetworkStack` | VPC and shared networking | VPC, subnets, security groups, VPC endpoints |
| `DataStack` | Shared storage | S3 buckets, DynamoDB tables, KMS-backed data resources |
| `IngestionStack` | Freshness + metadata | `cdc_sync`, `poll_sync`, `ingest`, schema discovery, drift checker |
| `ApiStack` | Query/API surfaces | API Gateway, `query`, `schema_api`, `action`, `authz` |
| `MonitoringStack` | Visibility | Dashboards, alarms, active-service monitoring |

## Active Lambda Surfaces

Main Lambdas now in play:

- `salesforce-ai-search-query`
- `salesforce-ai-search-cdc-sync`
- `salesforce-ai-search-poll-sync` when deployed
- `salesforce-ai-search-ingest`
- `salesforce-ai-search-schema-api`
- `salesforce-ai-search-schema-discovery`
- `salesforce-ai-search-schema-drift-checker`
- `salesforce-ai-search-action`
- `salesforce-ai-search-authz`

## Networking Notes

Current assumptions:

- API Gateway is regional
- Lambda functions run in the project VPC
- S3 and DynamoDB VPC endpoints are active
- Bedrock runtime connectivity remains active

Do not assume old OpenSearch-specific endpoints or private API patterns are
still part of the preferred runtime path.

## Naming Patterns

- stacks: `SalesforceAISearch-{Component}-{env}`
- Lambda functions: `salesforce-ai-search-{function}`
- S3 buckets: `salesforce-ai-search-{purpose}-{account}-{region}`
- DynamoDB tables: `salesforce-ai-search-{table}`

## Useful Commands

```bash
npm run build
npx cdk list
npx cdk diff
npx cdk synth
```

Deploy a single stack:

```bash
npx cdk deploy SalesforceAISearch-Api-dev
```

## Source Of Truth

For current infrastructure truth, trust:

1. `bin/app.ts`
2. `lib/*.ts`
3. deployed AWS resources

If a doc still references `SearchStack`, retrieve/answer Lambdas, or Bedrock KB
as the main search plane, treat it as historical unless it was updated after
the Turbopuffer migration.
