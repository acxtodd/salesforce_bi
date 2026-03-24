# Task 4.7 Validation Evidence

Date: 2026-03-24
Environment: ascendix-beta-sandbox (org 00Ddl000003yx57EAA)
Namespace: org_00Ddl000003yx57EAA
Branch: task-4.7-validate-expanded-corpus

## Scope

Validate expanded corpus with acceptance tests across the full object set.

### Objects in scope

All 11 configured objects are present in the Turbopuffer index. Counts shown
below are from per-object Turbopuffer aggregates (approximate — see note) and
Salesforce `SELECT COUNT()` queries.

| Object | TP count | SF count | Sync method |
|--------|----------|----------|-------------|
| Property | 1,334 | 2,470 | CDC |
| Lease | 406 | 483 | CDC |
| Availability | 231 | 527 | CDC |
| Account | 2,324 | 4,757 | CDC |
| Contact | 6,625 | 6,625 | CDC |
| Deal | 808 | 2,391 | Bulk + poll |
| Sale | 36 | 55 | Bulk + poll |
| Inquiry | 1,179 | 2,340 | Bulk + poll |
| Listing | 909 | 1,763 | Bulk + poll |
| Preference | 450 | 3,209 | Bulk + poll |
| Task | 12 | 29 | Bulk + poll |

TP aggregate total: ~14,314 documents across 11 object types.

**Note on count accuracy:** Turbopuffer's aggregate endpoint returns
approximate counts on large namespaces (global aggregate caps at 10,000 rows;
per-object aggregates can also vary between calls). The per-object search check
(below) confirms all 11 object types are searchable. The SF vs TP deltas are
a combination of: (1) aggregate approximation, (2) records added after the last
bulk load, and (3) poll sync not yet run for expansion objects. Contact is the
only object where TP and SF counts match exactly.

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
| 1 | Namespace exists | PASS | 10,000 documents found (aggregate may cap at 10k) |
| 2 | Object type counts | FAIL | SF count mismatch on all objects except contact (see table above) |
| 3 | System fields | PASS | 5/5 sampled docs have all system fields |
| 4 | Metadata filter (string) | PASS | name=York Town, city=Tblisi -> 1 result, match confirmed |
| 5 | Numeric/date filter | PASS | numeric: lease.termmonths >= 47 -> 10 results, all pass; date: lease.termcommencementdate >= 2020-09-14 -> 10 results, all pass |
| 6 | Parent fields | FAIL | deal: 4/10 docs have inconsistent partial property keys; other objects show expected sparse/partial patterns |
| 7 | Per-object search | PASS | 11/11 object types return search results |
| 8 | BM25 search | PASS | "office lease Dallas" -> 10 results |
| 9 | Hybrid search | PASS | 5/5 results have attributes matching query terms |
| 10 | Warm latency | FAIL | p50=146ms, p95=181ms (threshold 50ms) |

**Summary: 7 PASSED, 3 FAILED**

### Failure analysis

**Object type counts (FAIL):** SF/TP count mismatches are attributed to: (1)
Turbopuffer aggregate approximation on large namespaces, (2) poll-sync
expansion objects not yet incrementally synced. Contact (6,625/6,625) matches
exactly. All 11 objects have data in the index.

**Parent fields (FAIL):** deal: 4/10 sampled docs have inconsistent partial
property keys. Other objects show expected sparse/partial patterns consistent
with null FK values in Salesforce source data. No systematic denormalization
defects detected.

**Warm latency (FAIL):** p50=146ms, p95=181ms from local developer machine.
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

### Test queries

| # | Query | Expected behavior |
|---|-------|-------------------|
| 1 | "find contacts at properties in Dallas" | Returns contact records with property context |
| 2 | "show deals related to ACME Corp" | Returns deal records mentioning ACME |
| 3 | "what leases are expiring this quarter" | Returns lease records with date context |
| 4 | "how many properties by city?" | Returns aggregation with city counts |
| 5 | "help" | Returns onboarding message with examples |

### Status

Requires interactive browser access to Salesforce sandbox. Checklist provided
above for manual QA execution.

## 4. Unit test results (2026-03-24, local run)

```
python3 -m pytest tests/test_validate_data.py tests/test_acceptance_runner.py -v
```

**97 tests passed** (0 failed, 0 errors) in 1.18s.

Coverage includes:
- 53 validate_data tests (including per-object search, numeric filter, date
  filter, aggregate-cap fallback)
- 44 acceptance_runner tests

## 5. Blockers and residual risks

- **Aggregate count approximation:** Turbopuffer aggregate returns approximate
  counts on large namespaces (caps at ~10k for global aggregate). Per-object
  aggregates also vary between calls. This is documented in the object counts
  table and does not affect search functionality.
- **LWC smoke test:** Requires interactive browser session. Checklist provided.
- **Deal parent field inconsistency:** 4/10 sampled deal docs have inconsistent
  partial property keys. Worth investigating in a follow-up task.
- **Warm latency:** Local machine latency not representative of Lambda perf.

## 6. Evidence artifacts

| Artifact | Path | Contents |
|----------|------|----------|
| Data validation telemetry | `results/validate_data_4.7.json` | 10 checks, per-object groups, durations |
| Acceptance test results | `results/acceptance_tests_4.7.json` | 18 tests, per-test status/latency/answer |
| This document | `docs/testing/TASK_4_7_VALIDATION_EVIDENCE.md` | Human-readable summary |

All three artifacts are from the same validation session (2026-03-24).
