# Infrastructure Reference

*Last updated: 2026-03-20*

## Scope

This document summarizes the current AWS infrastructure shape for the active
connector.

## Active Stacks

- `NetworkStack`
- `DataStack`
- `IngestionStack`
- `ApiStack`
- `MonitoringStack`

The old `SearchStack` is no longer part of the active CDK app.

## Network

Current network foundations:

- VPC with private Lambda subnets
- NAT for outbound access where needed
- security group shared by VPC-attached Lambdas
- gateway endpoints for S3 and DynamoDB
- interface endpoints for active Bedrock/runtime access

The old OpenSearch-specific network assumptions should be treated as historical.

## Data Resources

The active system still uses shared AWS storage resources such as:

- CDC bucket
- audit bucket
- logs bucket
- data/support buckets from `DataStack`
- DynamoDB support tables including schema cache

Not every retained data resource means it is part of the preferred current
query path. Some remain for compatibility or staged decommission.

## API Layer

Current API surfaces:

- `/query`
- `/schema/{object}`
- `/ingest`

Key nuance:

- `/query` is the active search interface
- `/schema` is still used by Salesforce export/schema logic
- `/ingest` remains preserved because Salesforce batch export still references it

## Ingestion Layer

Current active ingestion/freshness components:

- `lambda/cdc_sync`
- `lambda/poll_sync`
- `lambda/ingest`
- `lambda/schema_discovery`
- `lambda/schema_drift_checker`

The Step Functions ingestion chain has been removed from the active CDK app.

## Query Layer

Current active query/support components:

- `lambda/query`
- `lambda/action`
- `lambda/authz`
- `lambda/schema_api`

## Observability

Monitoring is handled in `MonitoringStack` for the active components above.
Legacy retrieve/answer/search-stack dashboards should not be used as the main
operator view for current work.

## What To Trust

For current infrastructure truth, use:

1. `bin/app.ts`
2. `lib/*.ts`
3. deployed AWS resources

Do not treat old OpenSearch / Bedrock KB diagrams as current-state
infrastructure documentation.
