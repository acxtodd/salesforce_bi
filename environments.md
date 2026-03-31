# Environments

## Default Targets

- Salesforce: `sf` alias `ascendix-beta-sandbox` (org `00Ddl000003yx57EAA`).
  Always pass `-o ascendix-beta-sandbox` to `sf` commands.
- AWS: account `382211616288`, region `us-west-2`.
- Audit bucket: `salesforce-ai-search-audit-382211616288-us-west-2`.

## CDC Pipeline

The primary CDC path is `Salesforce CDC -> AppFlow -> S3 -> EventBridge ->
lambda/cdc_sync/index.py`. Treat `lambda/cdc_processor`, Step Functions
ingestion, `/ingest`, and `AISearchBatchExport` as legacy unless the task says
otherwise.

## Operational Notes

- When a live AWS or Salesforce fix is required, encode it in repo code or a
  durable repo artifact before closing or handing off the task. Commit messages,
  PR comments, and chat summaries are not durable evidence.
- When changing infra/runtime behavior, add or update the nearest automated
  check for that behavior. For CDK/resource-shape changes, prefer synth/assertion
  tests. If only live validation is possible, record the exact commands, object,
  and observed result in task notes or a checked-in validation artifact.
- AppFlow deployment can still fail functionally if Salesforce CDC entity
  selection is wrong or the cached `/salesforce/access_token` is stale. If flows
  exist but no events land or `cdc_sync` returns `401`, check those first and
  document the remediation in repo artifacts.
- A successful downstream sync probe is not the same as user-visible Salesforce
  validation. Real CDC validation requires both an AppFlow-written S3 object and
  an observable downstream result.
- Local warm-latency results from a developer machine are not comparable to
  in-region Lambda targets. Record the environment before treating a latency miss
  as a product issue.
- For validator or search probes, do not use `text_query=" "` as a
  "match-anything" query. Use `aggregate()` or an explicit stopword query such as
  `"a the is of and"`.
- Some repo docs still describe the legacy graph/Bedrock system. For current
  connector work, prefer `README.md` and
  `docs/architecture/object_scope_and_sync.md`; use the old graph docs only when
  touching legacy paths like `lambda/retrieve` or `lambda/answer`.
