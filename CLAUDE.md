# Scope

Repo-specific agent rules only. Keep this file narrow.
Use `python3 scripts/task_manager.py` for all task reads and writes.
For environments, CDC pipeline, and operational notes see
[`environments.md`](environments.md).
Before changing searchable object scope or freshness behavior, read
`docs/architecture/object_scope_and_sync.md`.
For Ascendix-driven scope/config work, also read
`docs/architecture/ascendix_search_signal_priority_and_validation.md`.
For runtime config artifact refresh or promotion, read
`docs/architecture/ascendix_search_config_refresh_plan.md`.

# Non-Negotiable Rules

1. Do not manually edit `tasks.json`, and do not run multiple task-manager
write commands in parallel.
2. If a task leaves implementation choices, naming contracts, or validation
queries ambiguous, stop and tighten the task/spec before coding.
3. For runtime config changes, separate candidate compile, describe-backed
gate, operator approval, pointer promotion, cold start, and replay. Verify the
active-version pointer and watermarks before and after each live step.
4. When updating Lambda environment variables directly, fetch current env,
merge into file-backed JSON, and push the full set. Never use inline
`Variables={...}` updates that can drop existing keys.
5. When a bundled Lambda imports a new repo module, update the matching
`scripts/bundle_*.sh`, rebuild the bundle before CDK diff/deploy, and confirm
the asset hash changed.
6. When changing model-facing search fields or aliases, update the alias or
field-registry layer, `lib/system_prompt.py`, focused tests, and regenerate
`docs/agent_prompt_export.md` if the prompt changes.
7. For delegated work, use isolated worktrees and zero-trust QA: the
orchestrator reviews every diff, reruns the relevant tests after integration,
and owns the final PR.
8. Do not mark a task complete while bulk reindex, live validation, operator
approval, or stakeholder review is still pending; record the blocker in task
state instead.

# Known Failure Patterns

1. Salesforce SOQL field lists must be describe-backed. Bare relationship
names such as `Owner` or `Account`, dotted traversals in direct fields, and
cross-object phantom fields belong in parent config or must be dropped.
2. For `/salesforce-ai-search/poll-watermark/*`, seed SSM parameters as
`String`, not `SecureString`; `poll_sync` reads them without decryption.
Replay one object at a time and treat `records_synced=0` as a proven-empty gap
only after response, logs, metric, and query evidence are checked.
3. AppFlow and CDC fixes need user-visible validation. Logs and S3 arrivals
are not enough; prove the changed or replayed record through `/query` unless
the gap is proven empty.
4. Keep `record_type`, `property_record_type`, `property_type`, and `use_type`
semantically distinct. Do not collapse primary building type, subtype, and
space-use meaning into one field.

> Self-Feedback Loop: If a task is confusing due to missing or contradictory repo context, add a temporary note here with:
> (a) what was confusing, (b) what wrong assumption it caused, and (c) the proposed permanent fix in code/docs.
> Remove the note once the root cause is fixed.
