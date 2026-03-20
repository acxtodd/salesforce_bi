# Runbook: Legacy Canary Operations

*Last updated: 2026-03-20*

## Status

This runbook is historical.

It documented the old canary controls for:

- `lambda/retrieve`
- `lambda/answer`
- planner rollout
- Bedrock KB / OpenSearch tuning

That path is no longer the active connector architecture.

## Do Not Use This For Current Operations

For current connector work, use:

- `README.md`
- `docs/guides/OPERATOR_GUIDE.md`
- `docs/architecture/object_scope_and_sync.md`
- `docs/runbooks/poll_sync.md`

## When This File Still Matters

Only consult this file when a task explicitly involves:

- legacy AWS decommission
- historical postmortem analysis
- migration archaeology
- comparing old planner/canary behavior against the current `/query` path

## Legacy Scope Summary

The retired canary path was built around retrieve/answer Lambdas, planner
traffic controls, and Bedrock KB / OpenSearch behavior. Those controls are not
the right mental model for the current Turbopuffer + tool-use system.
