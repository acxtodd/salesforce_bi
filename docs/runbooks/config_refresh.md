# Config Refresh Runbook

Operator reference for the Ascendix Search config control plane.

## Architecture

The control plane detects admin changes in Ascendix Search configuration,
compiles them into versioned runtime artifacts, classifies the operational
impact, and either auto-applies safe changes or requires explicit operator
approval for reindex-heavy changes.

### Runtime consumers

Both `/query` and `poll_sync` Lambdas load the active runtime config via
`RuntimeConfigLoader` with the fallback order:

1. Active S3 artifact (resolved from SSM active-version pointer)
2. Last-known-good cache in `/tmp`
3. Bundled `denorm_config.yaml`

This means admin config changes take effect without code redeploy.

### Components

- `lib/config_refresh.py` — compiler, differ, artifact store, apply workflow
- `lib/runtime_config.py` — runtime loader with S3→cache→bundled fallback
- `lib/structural_validation.py` — structural parity harness
- `lambda/config_refresh/index.py` — Lambda entrypoint
- `scripts/run_config_refresh.py` — operator CLI (compile, rollback, status)

## Storage Contract

S3 (shared data bucket, `config/` prefix):

- `config/{org_id}/source/{version}.json` — raw Ascendix source snapshot
- `config/{org_id}/compiled/{version}.yaml` — compiled runtime artifact
- `config/{org_id}/plan/{version}.json` — diff and impact plan
- `config/{org_id}/apply/{version}.json` — activation record
- `config/{org_id}/approval/{version}.json` — operator approval state

SSM:

- `/salesforce-ai-search/config/{org_id}/active-version`
- `/salesforce-ai-search/config/{org_id}/last-source-hash`
- `/salesforce-ai-search/config/{org_id}/last-compiled-hash`

## Impact Classification

| Class | Auto-Apply | Reindex Required |
|-------|-----------|-----------------|
| `none` | Yes | No |
| `prompt_only` | Yes | No |
| `field_scope_change` | No | Yes — targeted reindex of affected objects |
| `relationship_change` | No | Yes — targeted reindex of affected objects |
| `object_scope_change` | No | Yes — seed/retire of added/removed objects |

## Operator Flow: Detect → Review → Approve → Apply → Rollback

### Step 1: Detect (compile a candidate)

```bash
python3 scripts/run_config_refresh.py compile \
  --bucket salesforce-ai-search-data-<account>-<region> \
  --target-org ascendix-beta-sandbox
```

Output includes `impact_classification`, `diff`, and `version_id`.

For safe changes (`none`, `prompt_only`), the candidate is auto-applied.
No further operator action needed.

For non-safe changes, the candidate is published with `pending_approval`
state. The command exits with code 2 to signal that activation requires
explicit approval.

### Step 2: Review

Inspect the output from Step 1:

- `impact_classification` — what kind of change
- `diff.added_objects` / `diff.removed_objects` — object scope changes
- `diff.field_changes` — per-object field additions/removals
- `diff.relationship_changes` — per-object parent config changes

Review the plan artifact in S3:
`config/{org_id}/plan/{version}.json`

### Step 3: Approve and Apply

```bash
python3 scripts/run_config_refresh.py compile \
  --bucket salesforce-ai-search-data-<account>-<region> \
  --target-org ascendix-beta-sandbox \
  --apply
```

This runs the targeted apply workflow:

1. Builds an apply plan from the diff
2. Invokes the `poll_sync` Lambda for each affected object that requires
   seed or reindex (full_sync=true)
3. Only activates the candidate after all reindex invocations succeed
4. Records apply evidence in S3

The CLI invokes the deployed `salesforce-ai-search-poll-sync` Lambda by
default. Override with `--poll-sync-function <name>` if needed.

If a reindex invocation fails, activation is blocked and the error is
recorded. Fix the issue and re-run `compile --apply`.

### Step 4: Verify

```bash
python3 scripts/run_config_refresh.py status \
  --bucket salesforce-ai-search-data-<account>-<region> \
  --org-id 00Ddl000003yx57EAA
```

Verify:
- `active_version` matches the expected version
- `approval_state` is `applied`

### Step 5: Rollback (if needed)

```bash
python3 scripts/run_config_refresh.py rollback \
  --bucket salesforce-ai-search-data-<account>-<region> \
  --org-id 00Ddl000003yx57EAA \
  --version <previous-version-id> \
  --reason "regression found in QA"
```

Rollback immediately sets the active pointer to the target version.
Both `/query` and `poll_sync` will pick up the rolled-back config on
their next invocation.

## Auto-Apply vs Approval-Required

| Change Type | Example | Behavior |
|------------|---------|----------|
| Label/display text change | Admin renames "Property" to "Building" | Auto-applied: new query_scope fixtures update prompt/tool hints |
| Default Layout column change | Admin adds column to result grid | Auto-applied: query_scope result_columns updated |
| Field added to object | Admin enables a new search field | Approval required: targeted reindex to embed new field data |
| Relationship path changed | Admin adds cross-object filter | Approval required: targeted reindex to update parent embeddings |
| New object added | Admin enables a new searchable object | Approval required: initial seed + poll watermark init |
| Object removed | Admin disables a searchable object | Approval required: scope removal + async data retirement |

## Lambda Event Shape

```json
{
  "org_id": "00Ddl000003yx57EAA",
  "objects": ["ascendix__Property__c"],
  "apply": false
}
```

## Validation and Tests

- Compiler normalization, allowlist, query-scope: `tests/test_config_refresh.py`
- Artifact loader fallback: `tests/test_runtime_config.py`
- Query runtime loading: `tests/test_query_lambda.py`
- Poll sync runtime loading: `tests/test_poll_sync.py`
- Lambda entrypoint: `tests/test_config_refresh_lambda.py`
- Structural validation harness: `tests/test_structural_validation.py`
- End-to-end config refresh scenarios: `tests/test_e2e_config_refresh.py`
- Apply workflow, rollback: `tests/test_config_refresh.py`
