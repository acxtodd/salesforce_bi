# Object Scope And Sync

Current source of truth for what is indexed, how it stays fresh, and which
expansion work is still in flight.

## Current Live State

As of 2026-03-20, the live searchable set is:

| Object | Sync method | Status |
|--------|-------------|--------|
| Property | CDC via AppFlow -> S3 -> EventBridge -> `lambda/cdc_sync/index.py` | Live |
| Lease | CDC via AppFlow -> S3 -> EventBridge -> `lambda/cdc_sync/index.py` | Live |
| Availability | CDC via AppFlow -> S3 -> EventBridge -> `lambda/cdc_sync/index.py` | Live |
| Account | CDC via AppFlow -> S3 -> EventBridge -> `lambda/cdc_sync/index.py` | Live |
| Contact | CDC via AppFlow -> S3 -> EventBridge -> `lambda/cdc_sync/index.py` | Live |

Recent authoritative rebuild evidence recorded in task `4.6.4`:

- Property: 2,470
- Lease: 483
- Availability: 527
- Account: 4,756
- Contact: 6,625
- Total live namespace: 14,861 documents

## Expansion In Flight

The active Phase 4 move expands searchable scope beyond the 5-object CDC demo.
Target additions are:

| Object | Planned sync method | Notes |
|--------|---------------------|-------|
| Deal | Bulk load seed + poll sync | Restores broader transaction scope |
| Sale | Bulk load seed + poll sync | Small volume |
| Inquiry | Bulk load seed + poll sync | New searchable object |
| Listing | Bulk load seed + poll sync | New searchable object |
| Preference | Bulk load seed + poll sync | New searchable object |
| Task | Bulk load seed + poll sync | Requires object-specific review during implementation |
| Lead | Config-only for now | Defer until records exist |
| ContentNote | Config-only for now | Defer until records exist |

This expansion does not replace the primary CDC path for the 5 live objects.

## Sync Model

Two sync paths now matter:

1. `cdc_sync` is the primary freshness path for the 5 live demo objects.
2. Poll sync is the planned incremental path for non-CDC expansion objects after
   their initial bulk seed.

Initial seed for poll-sync objects is authoritative bulk load, not poll sync.
Poll sync is incremental-only unless a deliberate `full_sync` path is invoked.

## Query Scope

Current POC runtime tools are:

- `search_records`
- `aggregate_records`

`live_salesforce_query` remains deferred from the POC. The query path is still
custom `/query` Lambda orchestration over Turbopuffer, not direct live Salesforce
tooling.

Ascendix Search configuration may inform which objects and fields deserve
coverage, but query-time behavior is not meant to be limited to Ascendix's UI
or saved-search patterns.

## What To Trust

For current connector work, trust these sources in this order:

1. `tasks.json` via `python3 scripts/task_manager.py`
2. This document
3. `README.md`

Treat the following as historical unless the task explicitly touches legacy
graph/Bedrock code:

- `docs/guides/onboarding.md`
- `docs/architecture/salesforce_ai_search_architecture.md`
- `lambda/retrieve/`
- `lambda/answer/`

## Open Limits

- Parent-change cascade refresh is still not automatic across all denormalized
  children.
- Poll sync is an in-flight design and is not the current live source of truth
  for any object yet.
- Object expansion should not be described as complete until bulk-load counts,
  query validation, and incremental sync evidence all exist.
