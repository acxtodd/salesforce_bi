# Task 4.16 Spec: Property RecordType Indexing And Child Denormalization

## 1. Metadata

- Task ID: `4.16`
- Title: Index Property RecordType and denormalize to child objects
- Status: Draft for implementation
- Owner: Todd Terry
- Last Updated: 2026-03-31
- Related Task(s): `4.16.1`, `4.16.2`, `4.16.3`, `4.16.4`, `4.16.5`
- Related Docs:
  - `docs/architecture/object_scope_and_sync.md`
  - `docs/specs/salesforce-connector-spec.md`
  - `docs/agent_prompt_export.md`

## 2. Problem

The current search stack does not expose Property `RecordType.Name` as a
structured filter. That causes two user-visible failures:

- primary building type words like `office`, `retail`, and `industrial` fall
  back to `text_query` instead of a deterministic filter
- the existing `property_type` alias already means `PropertySubType`, so the
  model has no clean way to distinguish:
  - building primary type: `Office`, `Retail`, `Industrial`
  - building subtype: `General`, `Business Park`, `Mixed Use`
  - space use on Availability: `use_type`

This is partly a config/compiler gap and partly a denorm pipeline gap:

- the generator currently excludes `RecordTypeId` / `RecordType`
- Property documents cannot currently acquire `recordtype_name`
- child objects cannot currently flatten `Property.RecordType.Name` into a flat
  indexed attribute without extra nested-parent support
- the prompt explicitly teaches the model to use `text_query="office"` for
  Property queries, which is now the wrong retrieval strategy once the field is
  indexed

## 3. Goal

Expose Property primary type as a first-class structured filter on live objects.
After the task ships, Property queries should use `record_type`, and
Availability / Lease queries should use `property_record_type`, while
`property_type` continues to mean subtype.

## 4. Non-Goals

- Do not include `Listing` in the rollout. It remains an expansion object.
- Do not broaden generic standard-relationship harvesting beyond the minimum
  required for `RecordTypeId` and nested `RecordType.Name` under Property.
- Do not change the meaning of existing `property_type`; it remains subtype.
- Do not solve global parent-change cascade refresh here.
- Do not add a new public query tool. This task stays within
  `search_records` / `aggregate_records`.

## 5. Current State

- Live searchable objects today are `Property`, `Lease`, `Availability`,
  `Account`, and `Contact`.
- `scripts/generate_denorm_config.py` excludes `RecordType`, `RecordTypeId`,
  and the `RecordType` parent object from parent denorm generation.
- `lib/denormalize.py` handles:
  - direct fields through `record.get(field)`
  - one-level parent fields through `record[parent_rel].get(parent_field)`
- `lib/tool_dispatch.py` and `lib/system_prompt.py` currently reserve
  `property_type` for subtype and teach `text_query` for primary type words.
- `docs/agent_prompt_export.md` is generated from `lib/system_prompt.py` and
  must be regenerated, not edited by hand.

## 6. Target Behavior

After implementation:

- Property entity docs contain `recordtype_name`
- Availability and Lease entity docs contain `property_recordtype_name`
- the field registry exposes curated aliases:
  - Property: `record_type -> recordtype_name`
  - Availability / Lease: `property_record_type -> property_recordtype_name`
- the prompt teaches:
  - `record_type` = primary building type
  - `property_type` = subtype
  - `use_type` = space use on Availability
- common queries for office / retail / industrial use structured filters, not
  `text_query`

## 7. Scope

### In Scope

- Targeted generator support for Property `RecordTypeId`
- Property denorm config updates
- Nested parent-field support for `Property.RecordType.Name` on Availability
  and Lease
- Flat attribute-name normalization for dotted parent fields
- Curated alias and prompt migration
- Bulk reindex of `Property`, `Availability`, and `Lease`
- Live query validation with explicit test cases

### Out of Scope

- `Listing`, `Inquiry`, `Deal`, `Sale`, `Preference`, `Task`
- `Owner.Name` / `CreatedBy.Name`
- Generic multi-hop graph retrieval
- New LWC UX or operator console changes

## 8. Design

### Data Contract

Canonical indexed attributes:

```json
{
  "property": {
    "recordtype_name": "Office"
  },
  "availability": {
    "property_recordtype_name": "Office"
  },
  "lease": {
    "property_recordtype_name": "Industrial"
  }
}
```

Curated search aliases:

```json
{
  "property": {
    "record_type": "recordtype_name",
    "property_type": "propertysubtype"
  },
  "availability": {
    "property_record_type": "property_recordtype_name",
    "property_type": "property_propertysubtype",
    "use_type": "usetype"
  },
  "lease": {
    "property_record_type": "property_recordtype_name",
    "property_type": "property_propertysubtype"
  }
}
```

Important rule:

- no dotted field names may survive into indexed attribute keys or field
  registry entries

### Control Flow

1. The generator emits `RecordTypeId` as a parent on `Property`, with parent
   field `Name`.
2. Property ingestion queries `RecordType.Name` and builds `recordtype_name`.
3. Availability / Lease parent config for `ascendix__Property__c` includes
   `RecordType.Name`.
4. `build_soql()` emits `ascendix__Property__r.RecordType.Name`.
5. `flatten()` resolves nested parent paths instead of calling
   `parent_record.get("RecordType.Name")`.
6. `build_document()` flattens dotted parent field names into flat attribute
   keys such as `property_recordtype_name`.
7. `build_field_registry()` uses the same normalization rule so filters do not
   contain dots.
8. Curated aliases and prompt examples move the model from `text_query="office"`
   to structured `record_type` / `property_record_type` filters.
9. Bulk reindex runs for the three live objects in scope.
10. Live query validation confirms the model uses the new filters.

### Design Decisions Locked

- Choose the generic nested-parent-field path for child objects.
  `4.16.2` should not leave “synthetic injection vs nested traversal” to the
  implementer.
- Keep the indexed attribute names predictable:
  - `recordtype_name`
  - `property_recordtype_name`
- Use curated aliases for developer- and model-facing ergonomics:
  - `record_type`
  - `property_record_type`
- Keep `property_type` as subtype.
- Keep `use_type` separate from `property_record_type`.

### UX Notes

Prompt guidance must explicitly distinguish:

- `record_type`: the building’s primary type
- `property_type`: the building subtype
- `use_type`: the available space use within the building

This matters because values overlap. A valid query may need both:

- “retail space in office buildings in Dallas” means
  `use_type = Retail` and `property_record_type = Office`

## 9. Files / Surfaces Likely To Change

- `scripts/generate_denorm_config.py`
- `denorm_config.yaml`
- `lib/denormalize.py`
- `lib/tool_dispatch.py`
- `lib/system_prompt.py`
- `scripts/export_agent_prompt.py`
- `docs/agent_prompt_export.md`
- `tests/test_denorm_generator.py`
- `tests/test_denormalize.py`
- `tests/test_tool_dispatch.py`
- `tests/test_system_prompt.py`

## 10. Dependencies

- Live object scope in `docs/architecture/object_scope_and_sync.md`
- Existing prompt export workflow in `scripts/export_agent_prompt.py`
- Bulk-load/reindex path already used for authoritative rebuilds

## 11. Acceptance Criteria Interpretation

Concrete checks:

- Property config contains `RecordTypeId -> [Name]`
- Availability / Lease Property parent config contains `RecordType.Name`
- flattened attribute keys never contain dots
- the field registry resolves `record_type` and `property_record_type`
- prompt examples for property-type queries stop using `text_query="office"`
- reindex evidence is restricted to Property / Availability / Lease

## 12. Testing Plan

### Automated

- generator test proving `RecordTypeId` is emitted for Property parent config
- denormalize tests proving nested parent path resolution for
  `RecordType.Name`
- field-registry tests proving dotted parent fields normalize to flat indexed
  keys and curated aliases resolve
- system prompt tests proving primary type examples use structured filters

### Manual

Run these validation queries after reindex:

1. `Show me office properties in Dallas`
2. `Show me office properties in the Dallas-Fort Worth market`
3. `Find office availabilities in Dallas`
4. `What lease comps exist for industrial space in Houston?`
5. `Show me retail space in office buildings in Dallas`
6. Negative: `Find General Business Park properties`

Expected behavior:

- Queries 1-4 use `record_type` / `property_record_type`
- Query 5 uses both `use_type` and `property_record_type`
- Query 6 uses subtype `property_type`, not `record_type`

## 13. Risks / Open Questions

- Exact RecordType value spelling must match live Salesforce labels
  (`Multi-Family` vs `Multifamily`, etc.)
- Prompt export must be regenerated after prompt changes or the repo snapshot
  will drift from runtime behavior
- If the generator change causes unrelated config churn, that is a task bug;
  keep scope bounded to Property / Availability / Lease

## 14. Handoff Notes

- Implement `4.16.1` first and keep it narrowly scoped.
- In `4.16.2`, add a reusable dotted-parent resolver and shared flat-key
  normalization rather than special-casing `RecordType.Name` in multiple
  places.
- Do not change the meaning of `property_type`.
- Regenerate `docs/agent_prompt_export.md` after `lib/system_prompt.py` changes.
- Do not mark complete without live validation for the six explicit queries.
