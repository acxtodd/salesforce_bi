# Scope

Repo-specific agent rules only. Keep this file narrow.
Use `python3 scripts/task_manager.py` for all task reads and writes.
Before changing searchable object scope or freshness behavior, read
`docs/architecture/object_scope_and_sync.md`.
For Ascendix-driven scope/config work, also read
`docs/architecture/ascendix_search_signal_priority_and_validation.md`.

# Non-Negotiable Rules

1. Do not manually edit `tasks.json`, and do not run multiple task-manager
write commands in parallel.
2. If a task leaves implementation choices, naming contracts, or validation
queries ambiguous, stop and tighten the task/spec before coding.
3. When changing model-facing search fields or aliases, update the alias or
field-registry layer, `lib/system_prompt.py`, and focused tests in the same
PR.
4. If you touch `lib/system_prompt.py`, regenerate
`docs/agent_prompt_export.md` with
`python3 scripts/export_agent_prompt.py`; never edit the export manually.
5. For delegated work, use isolated worktrees and zero-trust QA: the
orchestrator reviews every diff, reruns the relevant tests after integration,
and owns the final PR.
6. Do not mark a task complete while bulk reindex, live validation, operator
approval, or stakeholder review is still pending; record the blocker in task
state instead.

# Known Failure Patterns

1. Ambiguous 4.x tasks cause code churn. If the task mixes pipeline changes,
prompt changes, and rollout steps without locked field names or scope, split
it into explicit subtasks before implementation.
2. Model-contract changes fail partially when only code or only prompt text
changes. Verify the old behavior is gone by checking aliases, prompt examples,
exported prompt, and targeted tests together.
3. Keep `record_type`, `property_record_type`, `property_type`, and `use_type`
semantically distinct. Do not collapse primary building type, subtype, and
space-use meaning into one field.
4. For record-page write flows, the model needs the real Salesforce
`record_id` in context and server-side ID validation. Do not rely on record
names as identifiers.

> Self-Feedback Loop: If a task is confusing due to missing or contradictory repo context, add a temporary note here with:
> (a) what was confusing, (b) what wrong assumption it caused, and (c) the proposed permanent fix in code/docs.
> Remove the note once the root cause is fixed.
