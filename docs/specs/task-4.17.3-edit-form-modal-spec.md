# Task 4.17.3 Spec: Embedded Edit Form Modal

## 1. Metadata

- Task ID: `4.17.3`
- Title: Edit form modal with pre-filled proposed values
- Status: Draft for implementation
- Owner: Todd Terry
- Last Updated: 2026-03-23
- Related Task(s): `4.17`, `4.17.2`, `4.17.7`
- Related Docs:
  - `docs/specs/task-4.17.7-writable-field-metadata-spec.md`
  - `docs/specs/task-4.17.8-write-proposal-transport-spec.md`

## 2. Problem

The BA task now correctly scopes Scenario A to an embedded edit experience, but the implementation path is still ambiguous. The repo does not yet have a proven pattern for taking an AI proposal, showing a diff, then letting the user edit and save those exact fields through supported Salesforce form components.

Without a narrow task plan, a dev agent may overreach into unsupported “full layout” behavior or reintroduce server-side DML.

## 3. Goal

Implement a supported embedded edit-form flow for Scenario A that:

- starts from the typed edit proposal
- renders only the proposed writable fields
- submits through standard Salesforce form mechanisms
- surfaces native validation behavior

## 4. Non-Goals

- Do not implement “show all fields” full-layout editing here.
- Do not navigate away to the native full edit page.
- Do not use Lambda-side Salesforce API writes for this scenario.
- Do not solve create flow behavior here.

## 5. Current State

- The LWC already has modal infrastructure and an action preview modal.
- Existing preview rendering is a simple key/value table.
- There is no embedded edit form for AI write-back today.
- The repo already uses navigation patterns and toasts in the LWC.

## 6. Target Behavior

From a diff-view modal, the user clicks `Edit in Form`. A second modal opens with an embedded Salesforce edit form scoped to the proposed fields on the target record. The form starts with the proposed values, the user can adjust them, and save runs through standard Salesforce behavior with native validation/error display.

## 7. Scope

### In Scope

- Modal transition from diff review into edit form
- Embedded form for proposed fields only
- Prefill strategy for proposed values
- Success handling in the LWC
- Inline display of Salesforce validation failures

### Out of Scope

- Full page layout expansion
- Dynamic rendering of arbitrary unsupported field types without a validated component path
- Multi-record orchestration

## 8. Design

### Recommended Component Pattern

Use the supported custom-layout edit path. The key design constraint is to keep the implementation tied to explicit writable fields rather than a layout-driven “all fields” view.

The dev agent should validate the exact prefill mechanism before building broadly. If a direct prefill pattern with `lightning-record-edit-form` and `lightning-input-field` is insufficient, the fallback is still to keep the task scoped to an embedded, explicit-field edit experience rather than widening scope.

### Control Flow

1. LWC receives typed `edit` proposal.
2. Task `4.17.2` shows diff modal.
3. User clicks `Edit in Form`.
4. LWC opens edit-form modal with:
   - target `recordId`
   - `objectApiName`
   - proposed writable field set
5. User adjusts values and clicks save.
6. Standard Salesforce form submission runs.
7. On success:
   - close modal
   - show toast
   - append success message with record link in chat
8. On validation error:
   - keep modal open
   - surface native field/form errors

### UX Notes

- The form should show only fields the AI proposed changing.
- If a field type cannot be cleanly supported in the embedded experience, fail safe rather than silently omitting or misbinding it.
- Preserve chat context behind the modal.

## 9. Files / Surfaces Likely To Change

- `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.js`
- `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.html`
- `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.css`
- LWC tests for modal state and success/error paths

## 10. Dependencies

- `4.17.2` diff modal
- `4.17.7` writable metadata contract
- `4.17.8` transport if the proposal state is not already available in the LWC

## 11. Acceptance Criteria Interpretation

Concrete implementation checks:

- The modal uses the typed proposal’s real writable fields.
- Save occurs through supported Salesforce form behavior, not custom AWS DML.
- Validation failures are visible and keep the user in the form.
- The task is not considered complete if it only opens a preview and punts to an unsupported full-layout approach.

## 12. Testing Plan

### Automated

- LWC tests for modal open/close transitions
- LWC tests for edit submission success handling
- LWC tests for validation failure handling
- Regression tests to prove the wrong fields are not rendered

### Manual

1. Open a record-page chat context.
2. Trigger an edit proposal for one simple field, such as phone.
3. Review diff modal.
4. Enter edit form and save a valid change.
5. Repeat with an invalid value to confirm native validation is surfaced.

## 13. Risks / Open Questions

- Exact supported prefill behavior for the chosen Salesforce form components
- Handling of lookup and picklist fields inside the embedded modal
- Whether some field types require explicit exclusions in the first iteration

## 14. Handoff Notes

- Keep the first version narrow and proven.
- Do not take on “all fields” or “full layout” in this task.
- Preserve the core product promise: the agent prepares, the user confirms, Salesforce validates.
