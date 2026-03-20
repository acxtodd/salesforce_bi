# Acceptance Testing Report

*Historical report preserved for reference.*

## Status

This document describes a 2025 acceptance pass against the older Bedrock KB /
OpenSearch system. It is not the acceptance report for the current Turbopuffer
connector.

## Do Not Use This As Current Evidence

It does not reflect:

- the current `/query` Lambda path
- current Phase 3 completion status
- current Phase 4 object-expansion work
- current prompt/query behavior
- current CDC and poll-sync validation state

## For Current Validation Status Use

- `python3 scripts/task_manager.py phases`
- `python3 scripts/task_manager.py show <task-id>`
- `README.md`
- `docs/architecture/object_scope_and_sync.md`

## Historical Context

This file is retained because it captures earlier deployment/testing evidence
from the legacy architecture. If needed, consult it as a historical artifact,
not as a current release or go/no-go record.
