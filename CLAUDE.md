# Scope

Repo-specific agent rules only. Keep this file narrow.
`tasks.json` is the roadmap; use `python3 scripts/task_manager.py` for all task
state changes.
For current searchable object scope and sync ownership, read
`docs/architecture/object_scope_and_sync.md` before changing indexing or query
scope.
For Ascendix-driven scope/config work, also read
`docs/architecture/ascendix_search_signal_priority_and_validation.md`.

# Default Environments

- Salesforce: `sf` alias `ascendix-beta-sandbox` (org `00Ddl000003yx57EAA`).
  Always pass `-o ascendix-beta-sandbox` to `sf` commands.
- AWS: account `382211616288`, region `us-west-2`.
- Audit bucket: `salesforce-ai-search-audit-382211616288-us-west-2`.

# Non-Negotiable Rules

1. Use `python3 scripts/task_manager.py` for all task reads and writes. Do not
manually edit `tasks.json`, and do not run multiple write commands in parallel.
2. Do not change acceptance definitions or thresholds during a validation rerun.
If criteria are wrong, revise the task criteria first and record the rationale.
3. Do not mark a task complete when unresolved validator, live-system, data, or
stakeholder-review issues remain unless the criteria were formally updated and
follow-up work is tracked.
4. The primary CDC path is `Salesforce CDC -> AppFlow -> S3 -> EventBridge ->
lambda/cdc_sync/index.py`. Treat `lambda/cdc_processor`, Step Functions
ingestion, `/ingest`, and `AISearchBatchExport` as legacy unless the task says
otherwise.
5. Before assuming CDC/AppFlow is working, verify live AWS resources or behavior.
CDK code alone is not evidence. When a live AWS or Salesforce fix is required,
encode it in repo code or task notes before closing the task.
6. For bulk load, use `python3 scripts/bulk_load.py --config denorm_config.yaml`.
Bulk load upserts; for 1:1 Salesforce parity, delete the namespace first. If
auth fails with `INVALID_SESSION_ID`, pass explicit creds from `sf org display`.
7. The live LWC search path is `/query` via `Ascendix_RAG_Query_API`. The filter
UI is intentionally disabled. Phase 2 validated Apex callout behavior, not full
LWC browser rendering.

# Known Failure Patterns

1. A successful downstream sync probe is not the same as user-visible
Salesforce validation. Real CDC validation requires both an AppFlow-written S3
object and an observable downstream result.
2. For validator or search probes, do not use `text_query=" "` as a
"match-anything" query. Use `aggregate()` or an explicit stopword query such as
`"a the is of and"`.
3. Local warm-latency results from a developer machine are not comparable to
in-region Lambda targets. Record the environment before treating a latency miss
as a product issue.
4. Turbopuffer does not support `Sum(BM25, ANN)` in one query. Hybrid search
must use `multi_query` with application-side RRF. Consult
`docs/turbopuffer/README.md` first, then confirm against
`lib/turbopuffer_backend.py` before changing backend behavior.
5. Human-facing audit or inspection artifacts must be readable by stakeholders.
Do not treat raw vector payloads, binary blobs, or machine-oriented dumps as an
"inspectable document" unless the user explicitly asked for that format. Default
to pretty JSON or Markdown and exclude embedding vectors from the human-facing
view unless vectors are the subject of the task.
6. Some repo docs still describe the legacy graph/Bedrock system. For current
connector work, prefer `README.md` and
`docs/architecture/object_scope_and_sync.md`; use the old graph docs only when
touching legacy paths like `lambda/retrieve` or `lambda/answer`.
7. Treat Ascendix Search as an admin-intent signal and structural validation
reference, not as the capability ceiling of the NL search product. Do not
assume query behavior must mirror Ascendix saved searches, result ordering, or
SOQL-builder constraints.

> Self-Feedback Loop: If a task is confusing due to missing or contradictory repo context, add a temporary note here with:
> (a) what was confusing, (b) what wrong assumption it caused, and (c) the proposed permanent fix in code/docs.
> Remove the note once the root cause is fixed.
