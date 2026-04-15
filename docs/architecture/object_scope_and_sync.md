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

## Runtime Denorm Config Sourcing

**The authoritative runtime denorm config is compiled from Ascendix Search
Salesforce metadata, not from `denorm_config.yaml` in the repo.** This is the
single most common source of "I edited the YAML but nothing changed at
runtime" confusion, so it's called out explicitly here.

`lambda/query` and `lambda/poll_sync` resolve denorm config in this order:

1. **Active compiled artifact in S3** via the SSM active-version pointer.
   The artifact is built by `lib/config_refresh.py::compile_config_artifact`,
   which pulls `SearchSetting__c` and `Search__c` records via
   `fetch_ascendix_source(sf)` and then harvests Salesforce describe metadata
   through `SalesforceHarvester`. `denorm_config.yaml` in the repo is not
   read at this layer.
2. **Last-known-good cache** in `/tmp` on the Lambda.
3. **Bundled `denorm_config.yaml`** from the Lambda deployment package as a
   final fallback when neither S3 nor the cache is usable.

Implications for contributors:

- Editing `denorm_config.yaml` only affects the bundled fallback. Once the
  SSM pointer is set to an active version, the Lambda will never read the
  bundled YAML again in normal operation.
- Adding fields to Sale's denormalized document in production requires
  editing Ascendix Search config in the target Salesforce org (typically via
  the Ascendix Search LWC / admin UI that writes to `Search__c`), then running
  `python3 scripts/run_config_refresh.py compile --apply ...` to recompile,
  reindex, and advance the pointer.
- Attribute-count constraints (Turbopuffer has a hard 256 attributes per
  namespace) apply to whatever shape the compiled Ascendix config produces.
  Trimming fields in `denorm_config.yaml` does not help if the cap is being
  hit by the Ascendix-driven config.
- The bundled YAML is useful for local unit tests, the schema-discovery
  tools, and as a readable reference of what a "reasonable" denorm looks
  like. It should be kept roughly in sync with what Ascendix produces so the
  fallback path does something sensible, but divergence between the two is
  normal during active config work.

Reference:

- `lib/config_refresh.py` - compile / activate / rollback flow
- `scripts/run_config_refresh.py` - CLI wrapper
- `docs/architecture/ascendix_search_config_refresh_plan.md`
- `docs/architecture/ascendix_search_signal_priority_and_validation.md`

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
