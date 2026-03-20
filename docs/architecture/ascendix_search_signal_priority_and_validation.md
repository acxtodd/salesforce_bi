# Ascendix Search Signal Priority And Validation

This document defines how Ascendix Search configuration should influence the
connector and where it is useful as a structural validation reference.

## Why This Matters

Ascendix Search is not just a UI. It is an admin-maintained configuration layer
that expresses:

- which objects should be searchable
- which fields should be searchable and viewable
- which result columns matter
- which related-object sections matter
- which saved-search patterns matter

For this connector, Ascendix Search should be treated as a business-signal layer
on top of raw Salesforce metadata.

## Actual Package Shape In The Demo Org

The live demo org does not expose the Ascendix Search config in the field shape
we initially inferred from the public docs.

- `ascendix_search__SearchSetting__c` stores config primarily in
  `Name` plus `ascendix_search__Value__c`
- `Selected Objects` is split across multiple rows named `Selected Objects`,
  `Selected Objects1`, `Selected Objects2`, and so on
- those row fragments concatenate into one JSON array of object descriptors
- each object descriptor includes flags such as
  `isSearchable`, `isSearchOrResultFieldsFiltered`, and `fields`
- default layouts are stored as rows whose `Name` starts with
  `Default Layout ` and whose `ascendix_search__Value__c` is a JSON array of
  result-column expressions
- `ascendix_search__Search__c.ascendix_search__Template__c` stores saved-search
  templates as JSON with `sectionsList`, `fieldsList`, `relationship`, and
  `resultColumns`

This matters because parser, control-plane, and validation work should target
the actual managed-package payload shape, not just the older inferred schema.

## Signal Priority

When compiling object scope and denormalization rules, use signals in this
priority order:

1. **Selected searchable objects**
   - Source: concatenated `Selected Objects*` rows from
     `ascendix_search__SearchSetting__c`
   - Use for: top-level object scope

2. **Explicit searchable and viewable field restrictions**
   - Source: object descriptors inside `Selected Objects*` JSON
   - Use for: admin-authored allowlist of criteria fields and result fields

3. **Default result columns**
   - Source: `Default Layout *` rows in `ascendix_search__SearchSetting__c`
   - Use for: high-signal result fields and parent denorm candidates

4. **Saved searches and related sections**
   - Source: `ascendix_search__Search__c.ascendix_search__Template__c`
   - Use for: real filter usage, relationship paths, and recurring query shapes

5. **Generic Salesforce metadata**
   - Source: describe, layouts, list views, compact layouts
   - Use for: fallback completion, type validation, and parent lookup discovery

## Compiler Rules

### Object scope

- If Ascendix Search marks an object as searchable, it is a candidate for index
  scope.
- Parser logic must reconstruct the full selected-object payload by ordering and
  concatenating all `Selected Objects*` rows before JSON parsing.
- Sync ownership remains a platform decision, not an Ascendix Search decision.
  Searchable does not automatically mean CDC-backed.

### Field scope

- If Ascendix Search explicitly filters which fields are searchable or viewable,
  treat that as authoritative over generic metadata scoring.
- If `isSearchOrResultFieldsFiltered` is `true`, the associated `fields` list
  should be treated as an admin-authored allowlist.
- If no Ascendix Search field filter exists, generic metadata can fill the gap.

### Parent denorm

- Parent fields referenced by default columns or saved-search related sections
  are stronger denorm signals than parent fields inferred only from generic
  layouts.
- Denorm depth should remain shallow and explicit because Ascendix Search itself
  has relationship limits.

### Runtime scope

- Query prompt and tool definitions should be compiled from the active config,
  not hardcoded object lists.

## Why It Is Useful For Validation

Yes. Ascendix Search is useful for validation because it already captures the
same structural ingredients the connector is trying to compile:

- searchable objects
- searchable or viewable fields
- related-object sections and relationship paths
- saved-search filters
- result columns that shape user-visible output

In practice, Ascendix Search behaves like an admin-authored SOQL builder plus
result-layout model. That makes it a strong structural reference for config
parity and targeted search-behavior checks.

## What Ascendix Search Is Not

Ascendix Search should not become the capability ceiling of the natural
language search experience.

- It should inform index scope and denorm choices.
- It should not force the connector to behave like a strict SOQL builder.
- It should not limit retrieval or answer synthesis to only the query shapes
  exposed in the Ascendix UI.
- It should not block the NL system from answering questions that go beyond
  existing saved searches, default layouts, or explicit filter widgets.

The product goal is not to rebuild Ascendix Search with an LLM facade. The goal
is to use Ascendix Search as a high-signal configuration input while allowing
the NL search system to exceed that baseline when the indexed data supports it.

## Ascendix Search As Structural Validation Reference

Ascendix Search is useful for validation, but only for the parts of the system
it actually models well.

### Good structural reference for

- object inclusion and exclusion
- searchable field availability
- result-column coverage
- related-object join intent
- saved-search filter intent
- whether a field or object change should trigger recompile or reindex

### Not a full reference for

- semantic retrieval quality
- BM25 ranking quality
- embedding quality
- citation quality
- LLM answer synthesis
- long-text search behavior
- arbitrary deep relationship traversal

## Important Product Limits

Ascendix Search docs describe constraints that must shape both compiler and
validation behavior:

- long text fields are not available as search criteria
- fields from 3rd-generation relationships and beyond are not supported
- lookup result columns from related objects show only the lookup record name
- maximum displayed/exported columns are capped
- Task and some system-view objects have API or feature limits
- polymorphic fields such as `Who` and `What` have special limits

These limits mean validation should not demand behavior that Ascendix Search
itself does not support.

## Recommended Validation Strategy

Use Ascendix Search as a structured reference in two layers.

### Layer 1: Config parity tests

Validate that the compiled connector config matches Ascendix Search admin
intent:

- concatenated `Selected Objects*` rows are reflected in compiled scope
- filtered `fields` allowlists are reflected in compiled field scope
- `Default Layout *` rows are reflected in field boosts or denorm candidates
- saved-search relationship paths are reflected in parent config

### Layer 2: Search-behavior spot checks

Use Ascendix Search saved searches as test fixtures:

- derive expected object scope from a saved search
- derive expected filter fields from a saved search
- derive expected parent relationships from related sections
- compare connector search output against the fixture at the structural level

Do not require identical ranking or answer wording.

### Suggested fixture sources

- object scope fixtures from concatenated `Selected Objects*` config
- field allowlist fixtures from object descriptors where
  `isSearchOrResultFieldsFiltered` is true
- default-column fixtures from `Default Layout *` rows
- relationship and filter fixtures from `Search__c` templates

## Suggested Test Categories

1. **Object scope parity**
   - Admin adds or removes an object in Ascendix Search
   - Compiler reflects the change

2. **Field allowlist parity**
   - Admin restricts searchable/viewable fields
   - Compiler suppresses fields outside the allowlist

3. **Default column parity**
   - Admin changes result columns
   - Compiler updates field boost or query-scope visibility

4. **Saved-search relationship parity**
   - Admin adds a related-object section
   - Compiler updates parent denorm config

5. **Prompt-only vs reindex-required classification**
   - Label-only change should not require reindex
   - Field or relationship shape change should require reindex

6. **Ascendix fixture parity**
   - A saved search or default layout is used as a fixture
   - Validation asserts structural parity without requiring identical ranking

## Implementation Notes

- The current extractor and tests should be updated to parse
  `ascendix_search__SearchSetting__c.Name` plus
  `ascendix_search__Value__c` rather than assuming dedicated custom fields like
  `ascendix_search__SelectedObjects__c` or
  `ascendix_search__ResultColumns__c`
- Validation should prefer structural assertions:
  object set, field presence, relationship path, and result-column coverage
- Validation should not assert rank order equality between Ascendix Search UI
  results and connector retrieval results

## Practical Recommendation

Treat Ascendix Search as:

- the primary reference for admin intent
- a partial reference for structural validation
- not a limiter on natural language search capability
- not the final oracle for retrieval or LLM quality

That gives the connector a stable control plane without overfitting runtime
behavior to the Ascendix Search UI.
