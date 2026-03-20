# Ascendix Search Config Refresh Plan

This plan turns Ascendix Search admin configuration into a repeatable control
plane for indexing, denormalization, and query scope.

It does not make Ascendix Search the product ceiling. Ascendix Search informs
what to index and how to shape denormalized records, while the natural language
query system remains free to reason over that indexed corpus in ways that go
beyond Ascendix's saved-search and filter-builder UX.

## Goal

When an admin changes Ascendix Search configuration, the connector should:

1. detect the change
2. compile the new configuration into runtime artifacts
3. classify the operational impact
4. apply safe changes automatically
5. require explicit approval for reindex-heavy changes until the workflow is
   proven

## Non-Goals

- Do not turn the NL search product into a strict Ascendix Search clone.
- Do not require query-time behavior to mirror Ascendix saved searches or SOQL
  builder flows.
- Do not treat Ascendix result ordering, UI constraints, or exact phrasing as
  the acceptance target for the connector.

## Current Foundation

The in-flight Phase 4 work already provides the core compiler pieces:

- `scripts/generate_denorm_config.py` harvests Salesforce metadata plus
  Ascendix Search signals
- `lib/system_prompt.py` builds query prompt and tool definitions dynamically
- `lambda/poll_sync/index.py` provides incremental sync for non-CDC objects

The missing system piece is a control plane that reacts to admin config changes
without relying on manual regeneration and redeploy.

## Actual Metadata Model

The demo org confirms that Ascendix Search config must be parsed from the live
managed-package payload shape:

- `ascendix_search__SearchSetting__c` stores config in `Name` plus
  `ascendix_search__Value__c`
- selected objects are chunked across rows named `Selected Objects`,
  `Selected Objects1`, `Selected Objects2`, and so on
- object descriptors inside that JSON include searchable flags, field-filter
  flags, and object-level field lists
- default layouts are stored as `Default Layout *` rows whose
  `ascendix_search__Value__c` is a JSON array of result-column expressions
- saved searches live in `ascendix_search__Search__c.ascendix_search__Template__c`

Control-plane work should target this actual payload model so config refreshes,
diffs, and validation logic remain package-version aware.

## Target Model

Ascendix Search remains the admin-facing source of truth, but runtime uses a
compiled config artifact.

### Source of truth

- `ascendix_search__Search__c`
- `ascendix_search__SearchSetting__c`

### Compiled runtime contract

Per org, produce a versioned artifact that contains:

- object scope
- denorm config
- query scope inputs
- source hash
- compiled hash
- change diff
- impact classification

### Runtime consumers

- `/query` Lambda
- `poll_sync` Lambda
- future config-aware ingestion paths

## Components

Add:

- `lambda/config_refresh/index.py`
- `lib/config_refresh.py`
- `lib/runtime_config.py`
- `scripts/run_config_refresh.py`
- `scripts/bundle_config_refresh.sh`
- `tests/test_config_refresh.py`
- `tests/test_runtime_config.py`
- `docs/runbooks/config_refresh.md`

Extend:

- `lambda/query/index.py`
- `lambda/poll_sync/index.py`
- `scripts/generate_denorm_config.py`

## Storage Model

Use S3 for versioned artifacts and SSM for active pointers.

### S3

- `config/{org_id}/source/{timestamp}.json`
- `config/{org_id}/compiled/{timestamp}.yaml`
- `config/{org_id}/plan/{timestamp}.json`
- `config/{org_id}/apply/{timestamp}.json`

### SSM

- `/salesforce-ai-search/config/{org_id}/active-version`
- `/salesforce-ai-search/config/{org_id}/last-source-hash`
- `/salesforce-ai-search/config/{org_id}/last-compiled-hash`

## Event Flow

### Automatic path

1. EventBridge triggers `config_refresh`
2. `config_refresh` snapshots Ascendix Search config
3. it compiles a candidate config
4. it diffs candidate vs active version
5. it classifies impact
6. it writes artifacts
7. it either auto-applies safe changes or leaves a pending apply state

### Manual path

1. Operator runs `scripts/run_config_refresh.py`
2. the same compile, diff, classify flow executes
3. operator can optionally apply the approved version

Both paths should first normalize the raw Ascendix payload by:

- ordering and concatenating `Selected Objects*` fragments
- parsing object descriptors from `ascendix_search__Value__c`
- parsing `Default Layout *` rows into per-object result-column fixtures
- parsing `Search__c` templates into filter, relationship, and result fixtures

## Impact Classes

- `none`
- `prompt_only`
- `field_scope_change`
- `relationship_change`
- `object_scope_change`

### Auto-apply initially

- `none`
- `prompt_only`

### Approval required initially

- `field_scope_change`
- `relationship_change`
- `object_scope_change`

## Apply Rules

### Prompt-only change

- publish new active config
- no reindex

### Field-scope or relationship change

- run targeted reindex for affected objects
- publish new active config after successful rebuild

### Object added

- compile config
- assign sync mode by platform policy
- run authoritative initial seed
- initialize poll watermark when applicable
- publish new active config

### Object removed

- remove from query scope first
- retire index data asynchronously

## Sync Ownership Policy

Ascendix Search config should not directly decide CDC vs poll sync.

Platform policy remains:

- CDC is explicitly curated and scarce
- poll sync is the default for new expansion objects
- promotion from poll to CDC is a separate operator decision

## Runtime Loader Contract

Implement a shared runtime loader with this fallback order:

1. S3 version from active SSM pointer
2. last-known-good cache in `/tmp`
3. bundled `denorm_config.yaml`

This is the key change that makes admin refreshes live without requiring code
redeploy for every config edit.

## Validation Scenarios

The system should prove these cases end to end:

1. admin adds a field to Ascendix Search config
2. admin adds a new searchable object
3. admin changes a saved-search relationship path
4. admin changes only labels or display text

For each scenario, the system should record:

- detected change
- classified impact
- applied action
- resulting active config version
- search validation evidence

That validation evidence should use Ascendix Search as a structural reference:

- object scope parity from `Selected Objects*`
- field allowlist parity from filtered object descriptors
- default-column parity from `Default Layout *`
- relationship-path parity from `Search__c` templates

## Recommended Delivery Order

1. extract compiler logic from `generate_denorm_config.py`
2. add versioned config artifact storage
3. implement `config_refresh` Lambda and CLI
4. add diff and impact classifier
5. add runtime config loader to query Lambda
6. add runtime config loader to poll sync
7. implement targeted reindex apply path
8. add runbook and approval flow
9. validate end to end with real admin config changes
