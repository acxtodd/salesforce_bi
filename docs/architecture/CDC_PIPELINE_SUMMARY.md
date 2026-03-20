# CDC Pipeline Summary

*Last updated: 2026-03-20*

## Scope

This document describes the current CDC path used by the connector.

## Current Live CDC Pipeline

```text
Salesforce CDC -> AppFlow -> S3 CDC bucket -> EventBridge -> lambda/cdc_sync
```

Managed objects:

- `Property`
- `Lease`
- `Availability`
- `Account`
- `Contact`

## Runtime Behavior

When a CDC file lands in S3:

1. EventBridge invokes `lambda/cdc_sync`
2. `cdc_sync` reads the CDC payload
3. changed record IDs and event type are extracted
4. the Lambda fetches current full Salesforce records where needed
5. documents are denormalized and embedded
6. documents are upserted or deleted in Turbopuffer
7. audit artifacts are written when enabled

## Why This Matters

This pipeline is now the primary freshness path for the live 5-object scope.
It replaces the older Step Functions-based ingestion flow for current connector
work.

## What This Pipeline Is Not

It is not:

- the old `cdc_processor -> validate -> transform -> chunk -> enrich -> embed -> sync` chain
- a Bedrock KB ingestion workflow
- the poll-sync path for expansion objects

## Validation Expectations

A CDC task should not be considered validated until all of these are true:

1. Salesforce generated a real change event
2. AppFlow wrote a new S3 object
3. EventBridge triggered `cdc_sync`
4. the document changed in Turbopuffer
5. the updated value is observable through the actual query surface

## Related Docs

- `docs/guides/APPFLOW_SETUP.md`
- `docs/architecture/object_scope_and_sync.md`
- `README.md`
