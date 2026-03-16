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
S3 -> EventBridge -> lambda/cdc_sync/index.py`. Prefer finishing or fixing that
path over inventing a new transport.
4. Treat `lambda/cdc_processor`, the Step Functions ingestion chain, the
`/ingest` endpoint, and `AISearchBatchExport` as legacy or fallback
infrastructure unless the task explicitly targets the old system.
5. Do not claim full E2E validation from synthetic S3 writes or direct
Turbopuffer checks. Full validation requires the real Salesforce/AppFlow source
leg and observable results through the Salesforce UI or `/query` path.
6. Current open Phase 2 work is:
   - `2.4` activate real AppFlow delivery for the sandbox
   - `2.5` prove LWC `/query` observability after sync
7. Do not mark a task complete when the remaining work is still a live system
leg. Keep the parent `in_progress` and create explicit follow-up tasks instead.
8. When editing CDC-related docs, keep README, `TASK_TRACKING.md`, and the task
entries aligned. Agents repeatedly get misled when only one of those surfaces is
updated.

# Known Failure Patterns

1. Existing AppFlow code in CDK does not mean AppFlow is active in AWS. Verify
real `AWS::AppFlow::*` resources or `aws appflow list-flows` before assuming the
source leg exists.
2. The repo contains both old and new ingestion paths. Verify which path a
Lambda or endpoint feeds before reusing it for the new connector.
3. A successful downstream sync test is not the same as a user-visible
Salesforce validation. Keep those as separate checks.

> Self-Feedback Loop: If a task is confusing due to missing or contradictory repo context, add a temporary note here with:
> (a) what was confusing, (b) what wrong assumption it caused, and (c) the proposed permanent fix in code/docs.
> Remove the note once the root cause is fixed.
