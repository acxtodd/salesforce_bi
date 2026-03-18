# Scope

This file is for repo-local agent guidance that is not obvious from quick code
search. Keep it narrow. The canonical roadmap is `tasks.json`, updated only via
`python3 scripts/task_manager.py`.

# Non-Negotiable Rules

1. Use `python3 scripts/task_manager.py` for all task reads and writes. Do not
manually edit `tasks.json`.
2. Do not run multiple `task_manager.py` write commands in parallel. Use one
writer at a time or task updates can be lost.
3. The primary CDC path for the new connector is `Salesforce CDC -> AppFlow ->
S3 -> EventBridge -> lambda/cdc_sync/index.py`. Prefer fixing or finishing that
path over designing a new transport.
4. Treat `lambda/cdc_processor`, the Step Functions ingestion chain, the
`/ingest` endpoint, and `AISearchBatchExport` as legacy or fallback
infrastructure unless the task explicitly targets the old system.
5. Before assuming AppFlow is active, verify it in AWS. Check actual
`AWS::AppFlow::*` resources or run `aws appflow list-flows`; CDK code alone is
not evidence.
6. Do not claim full E2E validation from synthetic S3 writes or direct
Turbopuffer checks. Full validation requires the real Salesforce/AppFlow source
leg and observable results through the Salesforce UI or `/query` path.
7. Current closing path for Phase 2 is `2.4` AppFlow activation, then `2.5`
LWC `/query` observability. Do not jump to Phase 3 before those are closed.
8. Do not mark a task complete when the remaining work is still a live system
leg. Keep the parent `in_progress` and create explicit follow-up tasks instead.
9. When editing CDC-related docs, keep `README.md`, `TASK_TRACKING.md`, and the
relevant task entries aligned in the same change.

# Known Failure Patterns

1. Existing AppFlow code in CDK does not mean AppFlow is active in AWS. In this
repo, `bin/app.ts` can omit the props that would create the flows.
2. The repo contains both old and new ingestion paths. Verify which path a
Lambda or endpoint feeds before reusing it for the new connector.
3. A successful downstream sync test is not the same as a user-visible
Salesforce validation. Keep those as separate checks.

> Self-Feedback Loop: If a task is confusing due to missing or contradictory repo context, add a temporary note here with:
> (a) what was confusing, (b) what wrong assumption it caused, and (c) the proposed permanent fix in code/docs.
> Remove the note once the root cause is fixed.
