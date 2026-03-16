# Task Tracking Guide

This guide describes how to manage project roadmap tasks with
`scripts/task_manager.py`.

## Scope
- This is for AscendixIQ Salesforce Connector development tasks.
- It uses a phase-based `tasks.json` at repository root.
- Phases map to the migration strategy in `docs/specs/salesforce-connector-spec.md` §13.

## Policy

**Always use `scripts/task_manager.py` for all task operations.** Do not parse
`tasks.json` directly with ad-hoc Python, jq, or manual JSON reading. Do not
write temporary scripts to query or modify tasks. The task manager handles
atomic writes, ID allocation, phase completion, and dependency tracking — ad-hoc
approaches bypass all of these.

**Do not run multiple `task_manager.py` write commands in parallel.** Use a
single writer for `create`, `update`, `add-note`, `add-ac`, `set-depends`, and
similar commands. Parallel writes can race and drop task updates.

When a task is code-complete but live validation is still missing, keep the
parent task `in_progress` and create explicit follow-up tasks for the missing
live legs. Do not mark the parent complete and carry the real work only in free
text notes.

## Quick Reference

| Action | Command |
|---|---|
| List all tasks | `python3 scripts/task_manager.py list` |
| List by status | `python3 scripts/task_manager.py list --status pending` |
| Show phase summary | `python3 scripts/task_manager.py phases` |
| Show next actionable task | `python3 scripts/task_manager.py next` |
| Show task details | `python3 scripts/task_manager.py show 0.1` |
| Start task | `python3 scripts/task_manager.py start 0.1` |
| Update task status | `python3 scripts/task_manager.py update 0.1 --status blocked --note "Waiting on API key"` |
| Complete task | `python3 scripts/task_manager.py complete 0.1 --commit <sha>` |
| Delete task | `python3 scripts/task_manager.py delete 0.1` |
| Force-delete task tree | `python3 scripts/task_manager.py delete 0.1 --force` |
| Add progress note | `python3 scripts/task_manager.py add-note 0.1 "Turbopuffer namespace created"` |
| Add modified file | `python3 scripts/task_manager.py add-file 0.1 "lib/search_backend.py"` |
| Create top-level task | `python3 scripts/task_manager.py create --phase 0 --title "New task"` |
| Create subtask | `python3 scripts/task_manager.py create --parent 0.1 --title "Subtask"` |
| Create phase | `python3 scripts/task_manager.py create-phase --phase 4 --name "Production Cutover" --description "Shadow reads, decommission old infra"` |
| Update phase metadata | `python3 scripts/task_manager.py update-phase --phase 0 --status in_progress` |
| Add acceptance criteria | `python3 scripts/task_manager.py add-ac 0.1 --ac "API key works from Lambda"` |
| Set dependencies | `python3 scripts/task_manager.py set-depends 0.4 --on 0.2 --on 0.3` |
| Clear dependencies | `python3 scripts/task_manager.py clear-depends 0.4` |
| Set description | `python3 scripts/task_manager.py set-description 0.1 "Updated scope"` |
| Set title | `python3 scripts/task_manager.py set-title 0.1 "New title"` |
| List tasks for owner | `python3 scripts/task_manager.py my-tasks --owner "Todd"` |
| Use alternate file | `python3 scripts/task_manager.py --file /path/to/tasks.json list` |

## Status Model

Task statuses:
- `pending`
- `in_progress`
- `blocked`
- `review`
- `completed`
- `skipped`

Phase statuses:
- `pending`
- `in_progress`
- `running`
- `completed`
- `rolled_back`

Terminal task statuses:
- `completed`
- `skipped`

When all tasks in a phase are terminal, `task_manager.py` auto-sets the phase status to `completed`.

## Task ID Format

Format: `<phase>.<sequence>[.<subsequence>...]`

Examples:
- `0.1` top-level task in phase 0
- `0.1.1` subtask under `0.1`
- `99.5` backlog task in phase 99

## Phases

| Phase | Name | Spec Section |
|-------|------|-------------|
| 0 | Foundations | §13 Phase 1 |
| 1 | Intelligence Layer | §13 Phase 2 |
| 2 | Salesforce Integration | §13 Phase 3 |
| 3 | Validation Gate | §13 Phase 4 |

Phase 4 (Production Cutover) and Phase 5 (Polish) from the spec will be added after the Phase 3 validation gate passes.

## Current Project Path

Phase 2 closing path — code tasks 2.4.1, 2.4.2, 2.5.1 merged to main in
`1f7dd3f` (PR #4, 2026-03-16). Remaining deploy/validate tasks:

1. `2.4` (in_progress) — **2.4.3** deploy AppFlow flows, **2.4.4** validate
   real CDC delivery. Pre-deploy: create SSM parameters
   `/salesforce/instance_url` (String) and `/salesforce/appflow_jwt_token`
   (SecureString).
2. `2.5` (in_progress) — **2.5.2** deploy /query Lambda, **2.5.3** validate
   LWC observability after CDC sync.
3. `3.1` Begin the side-by-side validation gate (blocked on 2.4 + 2.5).

This project already has legacy ingestion infrastructure. For new connector
work, treat `AppFlow -> S3 -> EventBridge -> cdc_sync` as the primary CDC path.
Treat the older `/ingest` endpoint, `AISearchBatchExport`, and Step Functions
chain as legacy or fallback infrastructure unless a task explicitly says
otherwise.

## Delete Semantics

- `delete` is conservative by default.
- If the target task has subtasks, delete is rejected.
- If other tasks reference the target in `depends_on`, delete is rejected.
- Use `--force` to:
  - delete the target task and all descendant subtasks
  - scrub deleted task IDs from `depends_on` lists across phases

## Typical Workflow

```bash
# 1) Find and start the next task
python3 scripts/task_manager.py next
python3 scripts/task_manager.py start 0.1

# 2) Do the work

# 3) Track progress
python3 scripts/task_manager.py add-file 0.1 "lib/search_backend.py"
python3 scripts/task_manager.py add-note 0.1 "SearchBackend ABC implemented"

# 4) Complete task
python3 scripts/task_manager.py complete 0.1 --commit <sha>
```
