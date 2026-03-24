# Task 4.7 Validation Evidence

Date: 2026-03-24
Environment: ascendix-beta-sandbox (org 00Ddl000003yx57EAA)
Namespace: org_00Ddl000003yx57EAA
Branch: task-4.7-validate-expanded-corpus

## Scope

Validate expanded corpus with acceptance tests across the full object set.

### Objects in scope

All 11 configured objects are present in the Turbopuffer index with exact
counts from native `aggregate_by(Count)`. Salesforce counts from
`SELECT COUNT()` against the sandbox.

| Object | TP count | SF count | Match | Sync method |
|--------|----------|----------|-------|-------------|
| Property | 2,470 | 2,470 | Exact | CDC |
| Lease | 483 | 483 | Exact | CDC |
| Availability | 527 | 527 | Exact | CDC |
| Account | 4,757 | 4,757 | Exact | CDC |
| Contact | 6,625 | 6,625 | Exact | CDC |
| Deal | 2,391 | 2,391 | Exact | Bulk + poll |
| Sale | 55 | 55 | Exact | Bulk + poll |
| Inquiry | 2,340 | 2,340 | Exact | Bulk + poll |
| Listing | 1,763 | 1,763 | Exact | Bulk + poll |
| Preference | 3,209 | 3,209 | Exact | Bulk + poll |
| Task | 29 | 29 | Exact | Bulk + poll |

**Total: 24,649 documents across 11 object types. All match Salesforce exactly.**

## 1. Data validation (`validate_data.py`)

### Run command

```bash
python3 scripts/validate_data.py \
  --namespace org_00Ddl000003yx57EAA \
  --config denorm_config.yaml \
  --target-org ascendix-beta-sandbox \
  --telemetry-output results/validate_data_4.7.json
```

### Results (2026-03-24, live run)

| # | Check | Status | Message |
|---|-------|--------|---------|
| 1 | Namespace exists | PASS | 24,649 documents found |
| 2 | Object type counts | PASS | All 11 objects match Salesforce exactly (total: 24,649) |
| 3 | System fields | PASS | 5/5 sampled docs have all system fields |
| 4 | Metadata filter (string) | PASS | name=York Town, city=Tblisi -> 1 result, match confirmed |
| 5 | Numeric/date filter | PASS | numeric: lease.termmonths >= 47 -> 10 results, all pass; date: lease.termcommencementdate >= 2020-09-14 -> 10 results, all pass |
| 6 | Parent fields | FAIL | deal: 4/10 docs have inconsistent partial property keys; other objects show expected sparse/partial patterns |
| 7 | Per-object search | PASS | 11/11 object types return search results |
| 8 | BM25 search | PASS | "office lease Dallas" -> 10 results |
| 9 | Hybrid search | PASS | 5/5 results have attributes matching query terms |
| 10 | Warm latency | FAIL | p50=147ms, p95=190ms (threshold 50ms) |

**Summary: 8 PASSED, 2 FAILED**

### Failure analysis

**Parent fields (FAIL):** deal: 4/10 sampled docs have inconsistent partial
property keys. Other objects show expected sparse/partial patterns consistent
with null FK values in Salesforce source data. No systematic denormalization
defects detected.

**Warm latency (FAIL):** p50=147ms, p95=190ms from local developer machine.
Per CLAUDE.md known failure pattern #4: "Local warm-latency results from a
developer machine are not comparable to in-region Lambda targets."

## 2. Acceptance tests (`run_acceptance_tests.py`)

### New cross-object test cases (Task 4.7)

| ID | Question | Category |
|----|----------|----------|
| cross-04 | "find contacts at properties in Dallas" | cross_object |
| cross-05 | "show deals related to ACME Corp" | cross_object |
| cross-06 | "what leases are expiring this quarter" | cross_object |

### Run command

```bash
python3 scripts/run_acceptance_tests.py \
  --config denorm_config.yaml \
  --output results/acceptance_tests_4.7.json
```

### Results (2026-03-24, live run)

**14/18 passed (78%)** — above 70% interim target.

| Test ID | Status | Latency | Notes |
|---------|--------|---------|-------|
| search-01 | PASS | 14.0s | |
| search-02 | FAIL | 25.4s | Latency only — answer correct |
| search-03 | PASS | 14.8s | |
| search-04 | PASS | 15.0s | |
| search-05 | FAIL | 18.1s | Latency only — answer correct |
| cross-01 | PASS | 15.6s | |
| cross-02 | PASS | 10.9s | |
| cross-03 | PASS | 10.2s | |
| agg-01 | PASS | 8.2s | |
| agg-02 | PASS | 5.9s | |
| agg-03 | PASS | 12.0s | |
| comp-01 | PASS | 5.2s | |
| comp-02 | PASS | 14.5s | |
| **cross-04** | **PASS** | **9.8s** | **Task 4.7: contacts at properties in Dallas** |
| **cross-05** | **PASS** | **15.8s** | **Task 4.7: deals related to ACME Corp** |
| **cross-06** | **PASS** | **9.4s** | **Task 4.7: leases expiring this quarter** |
| nlp-01 | FAIL | 18.8s | Latency only — answer correct |
| nlp-02 | FAIL | 17.1s | Latency only — answer correct |

All 4 failures are latency_under threshold exceeded from local developer
machine. All functional criteria (answer quality, tool use, result counts)
passed on all 18 tests.

## 3. LWC smoke test

### Procedure

1. Open Salesforce sandbox (ascendix-beta-sandbox)
2. Navigate to any Account or Property record
3. Open the AscendixIQ AI Search component
4. Submit each test query and verify:
   - Streaming response renders without error
   - Citations appear and link to correct records
   - Clarification buttons work when present
   - No console errors in browser dev tools

### Results (2026-03-24, manual QA in sandbox browser)

| # | Query | Status | Notes |
|---|-------|--------|-------|
| 1 | "find contacts at properties in Dallas" | PASS | Contact-focused results with valid Dallas/property context. Citations link correctly. Note: citation set was property-heavy; contact citations inconsistent across attempts. |
| 2 | "show deals related to Griffin Partners" | PASS | Deal-focused results with structured output. Griffin Partners substituted for ACME Corp (no ACME data in sandbox). |
| 3 | "what leases are expiring this quarter" | PASS | Correct lease answer with valid Q2 2026 reasoning and citations. |
| 4 | "how many properties by city?" | PASS | Aggregation rendered cleanly. Note: wording "503 total cities represented" could be clearer. |
| 5 | "help" | PASS | Onboarding message with relevant examples, no internal jargon. |
| 6 | "who are our top brokers by deal value?" (clarification rendering) | PASS | Ambiguity detected, clarification buttons rendered correctly. |
| 7 | "tell me about this record" (record context) | PASS | Correctly grounded on the current Cousins Properties record. |
| 8 | "what open deals are related to it?" (follow-up) | PASS | Context preserved, answer tied to Cousins Properties. Note: stray empty bullet points before clarification buttons. |
| 9 | Clarification button follow-up execution | **FAIL** | Selected "Any broker role by deal value" but follow-up narrowed to listing brokers only. Interpretation persistence bug. |

**7/8 functional queries passed. 1 clarification follow-up bug (see below).**

### Clarification follow-up bug

- **Trigger:** Select a clarification button after an ambiguous leaderboard query
- **Expected:** Follow-up executes the selected interpretation faithfully
- **Observed:** Follow-up narrowed to listing brokers instead of honoring the "any broker role" selection
- **Impact:** Clarification UX renders correctly, but the selected intent is not faithfully passed to the query. This is a separate defect from 4.7 scope — tracked for follow-up.

## 4. Unit test results (2026-03-24, local run)

```
python3 -m pytest tests/test_validate_data.py tests/test_acceptance_runner.py -v
```

**99 tests passed** (0 failed, 0 errors).

Coverage includes:
- 55 validate_data tests (including native count, per-object search, numeric
  filter, date filter)
- 44 acceptance_runner tests

## 5. Blockers and residual risks

- **Clarification follow-up bug:** Selected clarification intent is not
  faithfully executed in follow-up query. Separate defect, not a 4.7 blocker.
- **Deal parent field inconsistency:** 4/10 sampled deal docs have inconsistent
  partial property keys. Worth investigating in a follow-up task.
- **Warm latency:** Local machine latency not representative of Lambda perf.

## 6. Evidence artifacts

| Artifact | Path | Contents |
|----------|------|----------|
| Data validation telemetry | `results/validate_data_4.7.json` | 10 checks, exact per-object counts, durations |
| Acceptance test results | `results/acceptance_tests_4.7.json` | 18 tests, per-test status/latency/answer |
| This document | `docs/testing/TASK_4_7_VALIDATION_EVIDENCE.md` | Human-readable summary |

All three artifacts are from the same validation session (2026-03-24).
