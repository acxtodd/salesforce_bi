# Task 4.17.7 Spec: Writable Field Metadata And Eligibility Contract

## 1. Metadata

- Task ID: `4.17.7`
- Title: Build writable field metadata and eligibility contract
- Status: Draft for implementation
- Owner: Todd Terry
- Last Updated: 2026-03-23
- Related Task(s): `4.17`, `4.17.1`, `4.17.2`, `4.17.3`, `4.17.4`, `4.17.5`
- Related Docs:
  - `docs/specs/salesforce-connector-spec.md`
  - `docs/architecture/object_scope_and_sync.md`

## 2. Problem

The current query system is built around indexed search objects, denormalized fields, and curated search aliases. That is suitable for retrieval, but not for write-back. A write proposal must target real Salesforce fields that are writable in the current context. Today there is no authoritative contract that separates:

- real Salesforce field API names from search aliases
- writable fields from read-only/system/formula fields
- createable vs updateable fields
- lookup fields vs plain scalar fields
- user-friendly display labels from API names

Without this layer, the agent can easily propose invalid writes such as denormalized parent fields, formula outputs, or system-maintained fields.

## 3. Goal

Provide a shared metadata contract that describes which fields are eligible for AI-assisted create/edit proposals and how those fields should be represented in prompt logic, transport payloads, and LWC rendering.

## 4. Non-Goals

- Do not implement the query-Lambda tool schema here.
- Do not implement the LWC diff or form UI here.
- Do not attempt perfect per-user FLS enforcement inside AWS.
- Do not expand object scope beyond the initial write-back allowlist chosen for the POC.

## 5. Current State

- Query prompt/tooling relies on indexed object scope and search aliases in `lib/system_prompt.py` and `lib/tool_dispatch.py`.
- The LWC action preview prettifies raw keys heuristically and does not have authoritative field metadata.
- Record-page context resolution in Apex currently provides record id, object type, and name only.
- The repo has no shared module for writable Salesforce object/field metadata.

## 6. Target Behavior

The system exposes a reusable metadata contract for supported write-back objects. For each supported object, the contract should provide a filtered list of fields that can safely appear in AI write proposals, plus enough information for both the query layer and LWC to render and validate proposals correctly.

## 7. Scope

### In Scope

- Define the canonical metadata shape for supported write-back fields.
- Choose and document the metadata source of truth.
- Filter out clearly ineligible fields.
- Capture field label, API name, type, createability, updateability, lookup target information, and required-on-create hints where available.
- Define how search-facing names or denormalized fields map to real Salesforce write fields when such mapping is allowed.
- Document the initial object allowlist for write-back.

### Out of Scope

- Rendering the diff modal or edit form.
- Tool-call transport.
- Full user-specific permission parity with native Salesforce UI.
- Dynamic support for every Salesforce object in the org.

## 8. Design

### Data Contract

Recommended contract shape:

```json
{
  "Contact": {
    "objectLabel": "Contact",
    "fields": {
      "Phone": {
        "apiName": "Phone",
        "label": "Phone",
        "dataType": "phone",
        "createable": true,
        "updateable": true,
        "requiredOnCreate": false,
        "lookupTarget": null,
        "proposalEligible": true
      }
    }
  }
}
```

Recommended rules:

- `proposalEligible` is stricter than `createable`/`updateable`.
- Formula, auto-number, calculated rollups, system timestamps, and `Id` are never proposal-eligible.
- Denormalized search fields such as `property_city` or `account_name` are never direct write targets.
- Lookup fields should carry both API name and target object info so downstream tasks can resolve IDs cleanly.

### Source Of Truth

Recommended baseline:

1. Salesforce describe metadata as the canonical source for field capabilities.
2. A repo-owned allowlist/denylist policy for POC write-back objects and field exclusions.
3. Optional LWC-side `getObjectInfo` use only for presentation support, not as the authoritative contract.

Rationale:

- The query agent needs the contract outside the LWC.
- The LWC still benefits from native object info for display, but the server-side agent cannot depend on client-only metadata.

### Control Flow

1. Build or fetch metadata for the supported write-back objects.
2. Apply exclusion policy to derive `proposalEligible` fields.
3. Publish the contract in a form usable by:
   - prompt/tool-definition builders
   - transport payload shaping
   - LWC diff/form rendering
4. Add tests that fail if a known read-only or denormalized field leaks into proposal scope.

## 9. Files / Surfaces Likely To Change

- `lib/system_prompt.py`
- `lib/query_handler.py`
- `lambda/query/index.py`
- `salesforce/classes/AscendixAISearchController.cls`
- `salesforce/lwc/ascendixAiSearch/*`
- New shared metadata module under `lib/` or `salesforce/classes/` if needed
- Tests covering metadata filtering and field eligibility

## 10. Dependencies

- Existing searchable object scope in `denorm_config.yaml`
- Salesforce describe metadata access path
- POC decision on initial writable object allowlist

## 11. Acceptance Criteria Interpretation

Concrete implementation checks:

- The contract exists in code, not only in a doc.
- At least one supported object has a validated eligible-field list.
- Known invalid fields like `Id`, `CreatedDate`, formula fields, and denormalized search-only fields are excluded.
- Downstream tasks can reference the contract without heuristic field-name guessing.

## 12. Testing Plan

### Automated

- Unit tests for field filtering rules
- Snapshot or contract tests for metadata shape
- Regression tests proving denormalized/search-only aliases are not exposed as write targets

### Manual

- Inspect generated contract for one standard object and one custom object
- Verify a known writable field and a known read-only field are classified correctly

## 13. Risks / Open Questions

- How much per-user FLS awareness is required for the POC versus org-level eligibility?
- Which objects are in the initial allowlist?
- Should lookup resolution metadata live in this contract or the transport layer?

## 14. Handoff Notes

- Start with a narrow object allowlist; do not try to make this universal on the first pass.
- Bias toward explicit deny rules for system and denormalized fields.
- Do not let prompt aliases become the write contract.
- Mark the task incomplete if the contract exists only in the LWC and not where the query agent can use it.
