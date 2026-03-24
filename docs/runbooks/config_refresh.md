# Config Refresh Runbook

Task 4.9.1 through 4.9.5 add a config control plane for Ascendix Search admin
configuration.

## What Ships In This Slice

- `lib/config_refresh.py` normalizes the real Ascendix payload shape:
  - concatenated `Selected Objects*` fragments from `SearchSetting__c.Name` plus `ascendix_search__Value__c`
  - `Default Layout *` rows into per-object result-column fixtures
  - saved-search templates from `Search__c.ascendix_search__Template__c`
- the compiler produces a versioned runtime artifact with:
  - plain `denorm_config`
  - query-scope fixtures
  - normalized source snapshot
  - source / compiled hashes
  - diff summary and impact classification
- `lib/runtime_config.py` loads active config for `/query` with fallback order:
  1. active S3 artifact resolved from the SSM pointer
  2. last-known-good cache in `/tmp`
  3. bundled `denorm_config.yaml`
- `/query` uses `query_scope` fixtures from the active artifact to rebuild
  admin-facing prompt/tool hints for result columns, saved searches, and
  relationship paths without changing the denormalized field registry
- `lambda/config_refresh` and `scripts/run_config_refresh.py` run the same
  compile/store/apply flow.

## Storage Contract

The current storage layout uses the shared data bucket with the `config/`
prefix:

- `config/{org_id}/source/{version}.json`
- `config/{org_id}/compiled/{version}.yaml`
- `config/{org_id}/plan/{version}.json`
- `config/{org_id}/apply/{version}.json`

Active pointer and hashes live in SSM:

- `/salesforce-ai-search/config/{org_id}/active-version`
- `/salesforce-ai-search/config/{org_id}/last-source-hash`
- `/salesforce-ai-search/config/{org_id}/last-compiled-hash`

## Impact Classes

- `none`
- `prompt_only`
- `field_scope_change`
- `relationship_change`
- `object_scope_change`

Current apply policy:

- `none` and `prompt_only` auto-advance the active pointer
- `field_scope_change`, `relationship_change`, and `object_scope_change` write
  candidate artifacts but do not activate in this slice
- explicit `--apply` / event `apply=true` for those non-safe classifications
  returns a blocked activation response until targeted rebuild/apply
  orchestration lands in 4.9.6+

This is intentionally conservative until targeted reindex flows exist.

## Local Operator Flow

Compile and publish a candidate version:

```bash
python3 scripts/run_config_refresh.py \
  --bucket salesforce-ai-search-data-<account>-<region> \
  --target-org ascendix-beta-sandbox
```

Attempt activation for a non-safe change and capture the blocked response:

```bash
python3 scripts/run_config_refresh.py \
  --bucket salesforce-ai-search-data-<account>-<region> \
  --target-org ascendix-beta-sandbox \
  --apply
```

The command exits non-zero when activation is blocked so operators do not
silently publish field/object/relationship changes ahead of ingestion or
reindex work.

Limit compilation to a subset while iterating locally:

```bash
python3 scripts/run_config_refresh.py \
  --bucket salesforce-ai-search-data-<account>-<region> \
  --objects ascendix__Property__c ascendix__Lease__c
```

## Lambda Event Shape

```json
{
  "org_id": "00Ddl000003yx57EAA",
  "objects": ["ascendix__Property__c"],
  "apply": false
}
```

## Validation Added In This Slice

- compiler normalization / allowlist / query-scope tests:
  - `tests/test_config_refresh.py`
- artifact loader fallback tests:
  - `tests/test_runtime_config.py`
- query runtime loading tests:
  - `tests/test_query_lambda.py`
- Lambda entrypoint smoke:
  - `tests/test_config_refresh_lambda.py`

## Remaining 4.9 Scope

Still deferred to 4.9.6 through 4.9.10:

- runtime config loading for `poll_sync` and other ingestion consumers
- targeted reindex orchestration for field / relationship / object-scope changes
- authoritative object-seed/apply workflow for newly added objects
- automated change-detection trigger path from live admin events
- live end-to-end validation against real Ascendix config mutations
