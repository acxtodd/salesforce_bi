# LWC Readiness Checklist

This checklist is the current source of truth for getting the `ascendixAiSearch`
Lightning Web Component to a real working state in Salesforce.

Use this before broad UAT. The goal is to eliminate false positives caused by
deployment drift, stale index state, or outdated setup assumptions.

## Working Definition

For this project, "working LWC" means:

- The component renders on a Salesforce Home page and an Account record page.
- A user can submit a natural-language query from the LWC.
- The Apex controller successfully calls the live backend.
- The UI displays an answer and citations.
- A citation click navigates to the expected Salesforce record.
- Known retrieval misses are classified as product behavior, not deployment failure.

This is narrower than full UAT. It is the minimum bar before expanding pilot
coverage.

## Current Truths

- The live query path is the `/query` surface, not the legacy `/answer` flow.
- `salesforce/classes/AscendixAISearchController.cls` is the runtime source of
  truth for endpoint usage.
- The controller currently uses:
  - `Ascendix_RAG_Query_API` for `/query`
  - `Ascendix_RAG_API` for `/retrieve` and `/action`
- The existing `salesforce/DEPLOYMENT_GUIDE.md` and `salesforce/README.md`
  still emphasize the older Private Connect and `Ascendix_RAG_API` setup.
- Phase 2 validated Apex callout behavior, not LWC browser rendering. LWC smoke
  was explicitly deferred to Phase 3 UAT.

Treat any older deployment document as secondary to the current Apex controller
until the docs are reconciled.

## Must-Have Before First LWC Smoke

### 1. Salesforce metadata is deployed

- Deploy the current Salesforce package from `salesforce/package.xml`.
- Confirm these assets exist in the target org:
  - `AscendixAISearchController`
  - `ascendixAiSearch`
  - `Account_Record_Page`
  - `Home_Page`

### 2. Named Credential and External Credential are aligned with current code

- Verify `Ascendix_RAG_Query_API` exists in Salesforce.
- Verify its URL matches the intended live query endpoint.
- Verify the External Credential backing `Ascendix_RAG_Query_API` has a real API
  key instead of `REPLACE_IN_SETUP`.
- Verify `Ascendix_RAG_API` is configured if `/retrieve` or `/action` paths are
  still expected to work in this org.

Failure pattern:
- If the component renders but every query fails immediately, start here before
  touching LWC code.

### 3. Pilot users have access

- Confirm the pilot user has Apex access to `AscendixAISearchController`.
- Confirm the user can see the page where the LWC is placed.
- Confirm required Named Credential and External Credential permissions are
  available in the org.

### 4. The indexed namespace is fresh enough for UAT

- Do not start LWC UAT on a stale namespace.
- Re-run targeted validation after any major Salesforce data cleanup that should
  affect search.
- The recent Property and Availability refresh reduced stale-data false positives,
  so remaining misses should now be treated as retrieval or normalization issues
  unless proven otherwise.

### 5. Scope expectations are set correctly

- The LWC simulates streaming after Apex returns a response. It is not true
  browser-native SSE streaming.
- The filter UI is intentionally disabled because `/query` does not currently
  accept those filter parameters.
- A shorthand query miss is not automatically an LWC defect.

## First Smoke Sequence

Run these in order:

1. Open the Home page with the LWC and confirm the component renders without a
   spinner loop or immediate error state.
2. Submit a known-good broad query that already works through the live backend.
3. Confirm:
   - answer text appears
   - citations appear
   - no uncaught Apex error is shown
4. Open the citations drawer.
5. Click one citation and confirm record navigation works.
6. Open an Account record page containing the same LWC.
7. Submit one record-context query and confirm the component still behaves.

If any of those fail, stop broad UAT and classify the failure before continuing.

## Should-Have Before Broad UAT

### 1. Zero-trust smoke pack

Prepare a short query pack with:

- 2 broad known-good queries
- 2 record-context queries
- 2 known-risk shorthand or alias queries
- 2 no-result or guardrail queries

For each failure, classify it as:

- `setup`
- `data freshness`
- `retrieval/normalization`
- `planner/tooling`
- `ui rendering`

This keeps LWC debugging from turning into a vague backend hunt.

### 2. Audit and replay capability

Task `3.4` is not required for first render, but it is the highest-value
troubleshooting investment after basic wiring. It will make it much faster to
answer:

- what exact denormalized document was indexed
- whether the bug is in Salesforce data, denormalization, indexing, or UI
- whether a failure can be replayed without live Salesforce dependency

### 3. UAT query expectations

Known example:

- A canonical geography phrase can work while a shorthand phrase like `Dallas
  CBD` still fails.

Interpretation:

- That is now a retrieval or normalization gap, not proof that the LWC is
  broken.

## Likely Troubleshooting Hotspots

These are the areas most likely to consume time:

### Credential drift

- The code path has moved faster than the deployment docs.
- Always compare Salesforce setup against the live Apex controller, not just the
  deployment guide.

### Backend quality disguised as UI failure

- If the component returns zero results for a user-style query, confirm whether
  the same query succeeds through the backend first.
- If canonical phrasing works and shorthand does not, the issue is retrieval
  quality, not deployment.

### Stale data assumptions

- If Salesforce data was remediated recently, verify the active namespace was
  refreshed before blaming the component.

### Unsupported expectations

- Filter controls are disabled by design.
- Streaming is simulated.
- Older fallback infrastructure exists in the repo, but the primary path for the
  current connector is `/query`.

## Recommended Order Of Operations

1. Confirm Named Credential and External Credential setup in Salesforce.
2. Deploy current metadata.
3. Run one Home page smoke test.
4. Run one Account page smoke test.
5. Run the zero-trust smoke pack.
6. Only then expand into broader pilot or UAT coverage.
7. Prioritize task `3.4` before large-scale LWC troubleshooting if failures are
   mixing UI, data, and indexing uncertainty.

## Not A Blocker For First Working LWC

- Task `3.2` cost modeling
- Task `3.3.3` go/no-go document
- Query-intent translation or synonym expansion

Those may matter later, but they should not block proving the component works.
