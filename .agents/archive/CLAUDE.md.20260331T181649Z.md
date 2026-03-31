# Scope

Repo-specific agent rules only. Keep this file narrow.
`tasks.json` is the roadmap; use `python3 scripts/task_manager.py` for all task
reads and writes.
Before changing searchable object scope or freshness behavior, read
`docs/architecture/object_scope_and_sync.md`.
For Ascendix-driven scope/config work, also read
`docs/architecture/ascendix_search_signal_priority_and_validation.md`.

# Default Environments

- Salesforce: `sf` alias `ascendix-beta-sandbox` (org `00Ddl000003yx57EAA`).
  Always pass `-o ascendix-beta-sandbox` to `sf` commands.
- AWS: account `382211616288`, region `us-west-2`.
- Audit bucket: `salesforce-ai-search-audit-382211616288-us-west-2`.

# Non-Negotiable Rules

1. Use `python3 scripts/task_manager.py` for all task reads and writes. Do not
manually edit `tasks.json`, and do not run multiple task-manager write commands
in parallel.
2. Do not change acceptance definitions or thresholds during a validation rerun.
If criteria are wrong, revise the task criteria first and record the rationale.
3. Do not mark a task complete when unresolved validator, live-system, data, or
stakeholder-review issues remain unless the criteria were formally updated and
follow-up work is tracked.
4. The primary CDC path is `Salesforce CDC -> AppFlow -> S3 -> EventBridge ->
lambda/cdc_sync/index.py`. Treat `lambda/cdc_processor`, Step Functions
ingestion, `/ingest`, and `AISearchBatchExport` as legacy unless the task says
otherwise.
5. When a live AWS or Salesforce fix is required, encode it in repo code or a
durable repo artifact before closing or handing off the task. Commit messages,
PR comments, and chat summaries are not durable evidence.
6. When changing infra/runtime behavior, add or update the nearest automated
check for that behavior. For CDK/resource-shape changes, prefer synth/assertion
tests. If only live validation is possible, record the exact commands, object,
and observed result in task notes or a checked-in validation artifact.

# Known Failure Patterns

1. A successful downstream sync probe is not the same as user-visible
Salesforce validation. Real CDC validation requires both an AppFlow-written S3
object and an observable downstream result.
2. AppFlow deployment can still fail functionally if Salesforce CDC entity
selection is wrong or the cached `/salesforce/access_token` is stale. If flows
exist but no events land or `cdc_sync` returns `401`, check those first and
document the remediation in repo artifacts.
3. For validator or search probes, do not use `text_query=" "` as a
"match-anything" query. Use `aggregate()` or an explicit stopword query such as
`"a the is of and"`.
4. Local warm-latency results from a developer machine are not comparable to
in-region Lambda targets. Record the environment before treating a latency miss
as a product issue.
5. Some repo docs still describe the legacy graph/Bedrock system. For current
connector work, prefer `README.md` and
`docs/architecture/object_scope_and_sync.md`; use the old graph docs only when
touching legacy paths like `lambda/retrieve` or `lambda/answer`.

> Self-Feedback Loop: If a task is confusing due to missing or contradictory repo context, add a temporary note here with:
> (a) what was confusing, (b) what wrong assumption it caused, and (c) the proposed permanent fix in code/docs.
> Remove the note once the root cause is fixed.
