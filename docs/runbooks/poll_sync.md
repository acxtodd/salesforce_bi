# Poll Sync Runbook

Operational notes for the planned non-CDC sync path. This runbook becomes
active once task block `4.8.x` is deployed.

## Purpose

Poll sync exists for searchable objects that are not on the live CDC transport.
It is not the default seed path.

Use it for:

- incremental catch-up after the initial bulk load
- targeted on-demand re-sync of poll-managed objects
- controlled full re-sync when explicitly requested

Do not use it to claim initial indexing coverage for a new object unless bulk
load evidence already exists.

## Expected Inputs

- `POLL_OBJECTS` env var: comma-separated SObject API names
- SSM watermark per object:
  `/salesforce-ai-search/poll-watermark/{object}`
- `denorm_config.yaml`
- Turbopuffer auth
- Salesforce auth

## Normal Flow

1. Read object list from event override or `POLL_OBJECTS`.
2. Read the stored watermark for each object.
3. Query Salesforce for records modified after the watermark.
4. Denormalize, embed, and upsert each changed record.
5. Advance the watermark only after the corresponding page or batch is safely
   committed.
6. Emit per-object sync counts and return a summary.

## Required Evidence Before Closing Poll Sync Work

- A modified record appears in Turbopuffer with the updated field value.
- Watermark state advances as expected for the tested object.
- A second immediate run with no changes is a no-op.
- CloudWatch metrics or logs show the synced-record count.

## Operator Checks

- Compare Salesforce `COUNT()` with Turbopuffer counts after any deliberate full
  re-sync.
- Validate at least one real search query after sync, not only raw record
  existence.
- Record whether the run was incremental or full-sync.
- Treat watermark resets as operationally significant and document them in the
  task notes.

## Failure Modes To Watch

- Watermark advances without corresponding searchable updates.
- Search validation is skipped after a successful sync log line.
- A full-sync path is used informally and mistaken for the standard incremental
  run.
- Poll sync is treated as evidence for CDC health on live CDC-managed objects.

## Related Docs

- `docs/architecture/object_scope_and_sync.md`
- `README.md`
- `CLAUDE.md`
