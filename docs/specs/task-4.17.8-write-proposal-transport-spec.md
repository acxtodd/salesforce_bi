# Task 4.17.8 Spec: Structured Write Proposal Transport

## 1. Metadata

- Task ID: `4.17.8`
- Title: Add structured write proposal transport from query Lambda to LWC
- Status: Draft for implementation
- Owner: Todd Terry
- Last Updated: 2026-03-23
- Related Task(s): `4.17`, `4.17.1`, `4.17.2`, `4.17.4`, `4.17.5`, `4.17.6`
- Related Docs:
  - `docs/specs/salesforce-connector-spec.md`
  - `docs/specs/task-4.17.7-writable-field-metadata-spec.md`

## 2. Problem

The existing action-preview path is based on bracketed `[ACTION:...]` markers embedded in answer text and parsed in the LWC. That format is too weak for write-back:

- it is stringly typed
- it mixes answer rendering with action control flow
- it cannot reliably carry richer payloads such as object type, parent context, lookup IDs, or multi-step plans
- the Apex bridge currently returns only answer text, citations, clarifications, and metadata

Write-back needs a first-class payload contract that survives the full path from model tool call to LWC state.

## 3. Goal

Define and implement a typed write-proposal payload that moves through query execution, Lambda response shaping, Apex parsing, and LWC state without relying on free-form answer markers.

## 4. Non-Goals

- Do not implement edit/create UI here.
- Do not solve field eligibility here; consume the metadata contract from `4.17.7`.
- Do not preserve the bracket-marker path unless compatibility is low-cost.

## 5. Current State

- Query handler only understands `search_records` and `aggregate_records`.
- Lambda `/query` returns SSE events that Apex flattens into a response map.
- Apex currently parses `token`, `citations`, `clarification`, and `done` events.
- The LWC has `parseActionSuggestions()` for free-form `[ACTION:...]` markers.

## 6. Target Behavior

When the model emits a write proposal through a dedicated tool, the query stack returns a typed proposal payload alongside normal answer data. Apex preserves that structure, and the LWC can render the correct UI branch without regex parsing answer text.

## 7. Scope

### In Scope

- Define the proposal payload schema.
- Define where the proposal appears in `QueryResult`, Lambda response, and Apex response.
- Update the query loop to recognize write-proposal tool results.
- Update Apex SSE/JSON parsing to pass the proposal through.
- Update LWC state shape to consume typed proposals.

### Out of Scope

- Rendering the full diff or form UI
- Supporting every future proposal type beyond the initial edit/create/multi skeleton
- Long-term deprecation cleanup of old marker code unless it blocks the new path

## 8. Design

### Proposed Contract

Recommended top-level response field:

```json
{
  "answer": "I found the contact and prepared an edit proposal.",
  "writeProposal": {
    "kind": "edit",
    "objectType": "Contact",
    "recordId": "003...",
    "summary": "Update John Smith phone number",
    "fields": [
      {
        "apiName": "Phone",
        "label": "Phone",
        "proposedValue": "2146698974"
      }
    ]
  }
}
```

For create:

```json
{
  "writeProposal": {
    "kind": "create",
    "objectType": "Lease",
    "summary": "Create a new lease for Greenville Tower",
    "fields": [...],
    "parentContext": {
      "fieldApiName": "ascendix__Property__c",
      "recordId": "a0X..."
    }
  }
}
```

For multi-record:

```json
{
  "writeProposal": {
    "kind": "multi",
    "steps": [...]
  }
}
```

### Control Flow

1. Claude calls `propose_edit` or `propose_create`.
2. Query handler recognizes the tool result as a control payload, not a search payload.
3. `QueryResult` carries `write_proposal` separately from `answer`.
4. Lambda `/query` includes the proposal in SSE `done` data or equivalent JSON fallback.
5. Apex preserves the proposal in the response map returned to LWC.
6. LWC branches into diff/create-preview logic from the typed payload.

### Backward Compatibility

Recommended approach:

- Keep `parseActionSuggestions()` only as legacy fallback for old action flows.
- Do not route new write-back features through `[ACTION:...]` markers.

## 9. Files / Surfaces Likely To Change

- `lib/system_prompt.py`
- `lib/query_handler.py`
- `lambda/query/index.py`
- `salesforce/classes/AscendixAISearchController.cls`
- `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.js`
- Query/LWC/Apex tests

## 10. Dependencies

- `4.17.7` metadata contract
- A decision on the write-proposal payload schema
- Existing SSE response path in Apex

## 11. Acceptance Criteria Interpretation

Concrete implementation checks:

- A typed proposal object reaches the LWC without parsing answer text.
- Edit and create proposals both round-trip end to end.
- Existing answer/citation/clarification behavior remains intact.
- The implementation does not silently fall back to brittle marker parsing for new write-back scenarios.

## 12. Testing Plan

### Automated

- Query handler tests for write-proposal tool outputs
- Lambda handler tests for SSE/JSON payload shape
- Apex tests for proposal parsing
- LWC tests asserting typed proposal consumption

### Manual

- Simulate edit proposal and verify LWC receives structured data
- Simulate create proposal and verify parent context survives the round trip

## 13. Risks / Open Questions

- Should the typed proposal travel in a dedicated SSE event or only in `done`?
- How much proposal detail belongs in answer text versus the typed payload?
- Is compatibility with the legacy `/action` bracket flow worth preserving?

## 14. Handoff Notes

- Treat this as a protocol task, not a UI task.
- Keep the payload small but explicit.
- Do not bury proposal state inside the rendered answer string.
- Update tests at each boundary; this task crosses multiple seams and is prone to partial breakage.
