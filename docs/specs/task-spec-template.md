# Task Spec Template

Use this template for implementation-ready task plans that sit below a roadmap task in `tasks.json`.

Keep the spec narrow. It should make one task assignable to a dev agent without forcing the agent to reverse-engineer missing product or architectural decisions.

## 1. Metadata

- Task ID:
- Title:
- Status:
- Owner:
- Last Updated:
- Related Task(s):
- Related Docs:

## 2. Problem

Describe the exact gap this task closes and why the existing system is insufficient.

## 3. Goal

State the intended outcome in one or two sentences.

## 4. Non-Goals

- Explicitly list what this task does not implement.
- Call out adjacent work that belongs to other tasks.

## 5. Current State

- Relevant existing code paths
- Current behavior
- Known constraints or failure modes

## 6. Target Behavior

Describe the desired runtime behavior after this task ships.

## 7. Scope

### In Scope

- Concrete deliverables for this task

### Out of Scope

- Nearby work intentionally deferred

## 8. Design

### Data Contract

- Request/response shapes
- Internal payloads
- Persistence or cache shape if relevant

### Control Flow

1. Step-by-step path through the system
2. Caller and callee responsibilities
3. Error and fallback handling

### UX Notes

- Only include if the task affects the LWC or user-visible behavior

## 9. Files / Surfaces Likely To Change

- `path/to/file`
- `path/to/other/file`

## 10. Dependencies

- Upstream tasks, docs, runtime assumptions, or platform constraints

## 11. Acceptance Criteria Interpretation

Rewrite ambiguous task AC into concrete implementation checks if needed.

## 12. Testing Plan

### Automated

- Unit tests
- Integration tests
- Regression coverage

### Manual

- Operator or UI validation steps

## 13. Risks / Open Questions

- Remaining uncertainty
- Decision points that must be resolved before implementation

## 14. Handoff Notes

Short, assignment-oriented notes for the dev agent:

- Recommended implementation order
- Known traps
- Required validation before marking complete
