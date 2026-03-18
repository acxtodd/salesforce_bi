# Scope

This file holds repo-specific agent rules that are not obvious from code search.
Keep it narrow. The canonical roadmap is `tasks.json`, and task state changes go
through `python3 scripts/task_manager.py`.

# Default Environments

Use these without asking unless the user specifies otherwise.

- **Salesforce**: `sf` CLI alias `ascendix-beta-sandbox` (org `00Ddl000003yx57EAA`,
  user `tterry@ascendix.com.agentforce.demo.beta`). Always pass
  `-o ascendix-beta-sandbox` to `sf` commands.
- **AWS**: account `382211616288`, region `us-west-2`, IAM user `acx-todd-cli`.
  Lambda functions are prefixed `salesforce-ai-search-*` or `SalesforceAISearch-*`.
- **Audit bucket**: `salesforce-ai-search-audit-382211616288-us-west-2`. Audit
  trail is **on by default** for bulk loads and should be enabled for CDC Lambda
  via `AUDIT_BUCKET` env var. Do not disable without explicit user instruction.

# Non-Negotiable Rules

1. Use `python3 scripts/task_manager.py` for all task reads and writes. Do not
manually edit `tasks.json`.
2. Do not run multiple `task_manager.py` write commands in parallel. Use one
writer at a time or task updates can be lost.
3. Do not change acceptance test definitions or thresholds during a validation
gate rerun. If a task's acceptance criteria are wrong, revise the task criteria
first, record the rationale, and track any carried-forward issues explicitly.
4. Do not mark a task complete when unresolved validator, live-system, or data
issues remain unless the task criteria were formally updated first and the
follow-up work is tracked in child or downstream tasks.
5. The primary CDC path for the new connector is `Salesforce CDC -> AppFlow ->
S3 -> EventBridge -> lambda/cdc_sync/index.py`. Prefer fixing that path over
designing a new transport.
6. Treat `lambda/cdc_processor`, the Step Functions ingestion chain, the
`/ingest` endpoint, and `AISearchBatchExport` as legacy or fallback
infrastructure unless the task explicitly targets the old system.
7. Before assuming AppFlow is active, verify it in AWS. Check actual
`AWS::AppFlow::*` resources or run `aws appflow list-flows`; CDK code alone is
not evidence.
8. When a live AWS or Salesforce fix is required during validation, encode that
fix in repo code or task notes before closing the task. Do not leave the source
of truth in console-only state.
9. For Turbopuffer API, schema, hybrid, or performance questions, consult
`docs/turbopuffer/README.md` first, then confirm against
`lib/turbopuffer_backend.py` before changing backend behavior.

# Turbopuffer

- Region: `gcp-us-central1`. The `TurbopufferBackend` defaults to this.
- Namespace naming: `org_{salesforce_org_id}` (e.g. `org_00Ddl000003yx57EAA`).
- `object_type` values in the index are **lowercase** (`property`, `lease`,
  `availability`), not Salesforce API names. Filter queries must use lowercase.
- SDK v1.17+ requires explicit `region=` param; bare `Turbopuffer()` will error.

# Bulk Load

- Entry point: `python3 scripts/bulk_load.py --config denorm_config.yaml`.
- The auth cascade is: CLI args → env vars → SSM → sf CLI. SSM tokens go stale;
  if bulk load fails with `INVALID_SESSION_ID`, pass explicit creds:
  ```
  CREDS=$(sf org display -o ascendix-beta-sandbox --json | python3 -c "import sys,json; r=json.load(sys.stdin)['result']; print(f'{r[\"instanceUrl\"]} {r[\"accessToken\"]}')")
  python3 scripts/bulk_load.py --config denorm_config.yaml \
    --instance-url $(echo $CREDS | cut -d' ' -f1) \
    --access-token $(echo $CREDS | cut -d' ' -f2)
  ```
- Bulk load **upserts**, it does not purge. To get 1:1 parity with Salesforce,
  delete the namespace first via `ns.delete_all()`, then run the load.
- Always `export $(grep -v '^#' .env | xargs)` before running so
  `TURBOPUFFER_API_KEY` is available.

# LWC (ascendixAiSearch)

- The live query path is `/query` via `Ascendix_RAG_Query_API` Named Credential.
  The legacy `/answer` path and `Ascendix_RAG_API` credential are not used for
  search queries.
- Streaming is simulated client-side — Apex receives the full SSE response, then
  the LWC chunks it for display.
- Filter UI is intentionally disabled (`isFilterUIEnabled = false`).
- The LWC readiness checklist is at `salesforce/LWC_READINESS_CHECKLIST.md`.

# Known Failure Patterns

1. A successful downstream sync probe is not the same as user-visible
Salesforce validation. Real CDC validation requires both an AppFlow-written S3
CDC object and an observable downstream result.
2. For validator or search probes, do not use `text_query=" "` as a
"match-anything" query. Turbopuffer strips it. Use `aggregate()` or an explicit
stopword query such as `"a the is of and"`.
3. Local warm-latency results from a developer machine are not comparable to
in-region Lambda targets. If a latency gate is environment-sensitive, record
the environment in the task note before treating the result as a product issue.
4. Turbopuffer does not support `Sum(BM25, ANN)` in a single query — the `Sum`
combinator only accepts `RankByText` elements. Hybrid search uses `multi_query`
(BM25 + ANN in parallel) with application-side RRF fusion. See
`turbopuffer_backend.py:_hybrid_search`.
5. `denorm_config.yaml` and CDC map include Deal and Sale for Phase 5 readiness,
but the query layer (system prompt, tool schema, acceptance tests) scopes to
Property, Lease, Availability only. Validator check 2 will report Deal/Sale as
missing — this is expected config-vs-query scope divergence, not an ingestion bug.

> Self-Feedback Loop: If a task is confusing due to missing or contradictory repo context, add a temporary note here with:
> (a) what was confusing, (b) what wrong assumption it caused, and (c) the proposed permanent fix in code/docs.
> Remove the note once the root cause is fixed.
