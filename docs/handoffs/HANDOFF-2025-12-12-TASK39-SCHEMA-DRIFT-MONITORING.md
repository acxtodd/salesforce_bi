# HANDOFF: Task 39 - Schema Drift Monitoring Dashboard

**Date:** 2025-12-12
**Status:** ✅ P1 MVP COMPLETE - Validated
**Task Reference:** `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md` (Task 39)

---

## Overview

Implementing schema drift monitoring to detect and alert when the Schema Cache diverges from Salesforce's actual schema. This prevents query failures caused by fake/missing fields.

---

## Problem Statement

No monitoring exists for schema drift between Salesforce and the schema cache. When Salesforce schema changes (fields added/removed/modified), the cache can become stale, causing:
- Query failures (planner expects fields that don't exist)
- Missing filter capabilities (new filterable fields not discovered)
- Relationship path gaps (new lookups not available for traversal)

**Historical context:** Task 37 discovered 40% of schema cache fields were fabricated (20 fake fields). This task prevents recurrence.

---

## Approved Plan

### Design Principles

1. **Dynamic Object Discovery** - Never hardcode object lists; derive from Schema Cache at runtime
2. **Read-Only Checker** - Drift checker observes only; MUST NOT update Schema Cache
3. **Precise Coverage Semantics** - Compare normalized API names; exclude system fields from denominators
4. **Cost-Conscious Metrics** - Batch `PutMetricData` calls; emit per-object metrics only for enabled objects
5. **False Positive Avoidance** - Suppress alerts during active discovery; require consecutive breaches

### Coverage Calculation Rules

```python
# Filterable Coverage
filterable_coverage = len(cache_filterable ∩ sf_filterable) / len(sf_filterable)

# Relationship Coverage
relationship_coverage = len(cache_relationships ∩ sf_relationships) / len(sf_relationships)

# Exclusions from denominators:
EXCLUDED_SYSTEM_FIELDS = {'Id', 'IsDeleted', 'SystemModstamp', 'CreatedById',
                          'LastModifiedById', 'CreatedDate', 'LastModifiedDate'}

# Comparison uses normalized API names (case-insensitive)
def normalize_field_name(name: str) -> str:
    return name.lower().strip()
```

### Phased Delivery

| Phase | Scope | Status |
|-------|-------|--------|
| **P1 (MVP)** | Lambda + Metrics + Dashboard + Alarms | ✅ Code Complete |
| **P2** | Nightly report to S3 + drift-delta notification | 🔲 Not Started |
| **P3** | Picklist/RecordType value drift detection | 🔲 Future |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SCHEMA DRIFT MONITORING ARCHITECTURE                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐       │
│  │  EventBridge    │────▶│ Schema Drift    │────▶│  CloudWatch     │       │
│  │  (Nightly +     │     │ Checker Lambda  │     │  Metrics        │       │
│  │   On-Demand)    │     └─────────────────┘     └────────┬────────┘       │
│  └─────────────────┘              │                       │                │
│                                   │                       ▼                │
│                                   │              ┌─────────────────┐       │
│                                   │              │  CloudWatch     │       │
│                                   ▼              │  Dashboard      │       │
│                          ┌─────────────────┐     └─────────────────┘       │
│  ┌─────────────────┐     │  DynamoDB       │              │                │
│  │  Salesforce     │◀───▶│  Schema Cache   │              ▼                │
│  │  Describe API   │     └─────────────────┘     ┌─────────────────┐       │
│  └─────────────────┘                             │  CloudWatch     │       │
│                                                  │  Alarms → SNS   │       │
│                                                  └─────────────────┘       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## P1 MVP Implementation

### Files Created

| File | Purpose | Status |
|------|---------|--------|
| `lambda/schema_drift_checker/index.py` | Main Lambda handler | ✅ Created |
| `lambda/schema_drift_checker/metrics.py` | CloudWatch metric emission | ✅ Created |
| `lambda/schema_drift_checker/coverage.py` | Coverage calculation logic | ✅ Created |
| `lambda/schema_drift_checker/requirements.txt` | Dependencies | ✅ Created |
| `lambda/schema_drift_checker/test_coverage.py` | Unit tests | ✅ Created |
| `lib/monitoring-stack.ts` | Dashboard + Alarms (additions) | ✅ Updated |

### CloudWatch Metrics

**Namespace:** `SalesforceAISearch/SchemaDrift`

| Metric Name | Dimensions | Description |
|-------------|------------|-------------|
| `SFFieldCount` | ObjectName | Field count from SF Describe |
| `CacheFieldCount` | ObjectName | Field count in schema cache |
| `FilterableCoverage` | ObjectName | % of SF filterable fields in cache |
| `RelationshipCoverage` | ObjectName | % of SF relationships in cache |
| `FieldsInCacheNotSF` | ObjectName | Fields in cache not in SF (CRITICAL) |
| `FieldsInSFNotCache` | ObjectName | Fields in SF not yet cached |
| `CacheAgeHours` | ObjectName | Hours since last discovery |
| `TotalObjectsCovered` | - | Count of objects in cache |
| `DriftDetected` | ObjectName | 1 if drift detected, 0 otherwise |

### CloudWatch Alarms

| Alarm Name | Metric | Threshold | Severity |
|------------|--------|-----------|----------|
| `schema-drift-fake-fields-critical` | FieldsInCacheNotSF | > 0 | CRITICAL |
| `schema-drift-coverage-low-warning` | FilterableCoverage | < 80% | WARNING |
| `schema-drift-relationship-low-warning` | RelationshipCoverage | < 50% | WARNING |
| `schema-drift-cache-stale-warning` | CacheAgeHours | > 48 | WARNING |
| `schema-drift-objects-missing-critical` | TotalObjectsCovered | < EXPECTED | CRITICAL |

### Dashboard Layout

**Dashboard Name:** `Salesforce-AI-Search-Schema-Drift`

```
Row 1: Overall Health (3 single-value widgets)
- Total Objects Covered
- Avg Filterable Coverage
- Drift Alerts Count

Row 2: Coverage by Object
- Filterable Coverage % (Stacked Bar)
- Relationship Coverage % (Stacked Bar)

Row 3: Drift Indicators
- Fields In Cache Not SF (Line Graph - CRITICAL)
- Cache Age Hours by Object (Line Graph)

Row 4: Field Counts
- SF vs Cache Field Count Comparison (Grouped Bar)
```

---

## Key Implementation Details

### Dynamic Object List (No Hardcoding)

```python
def get_monitored_objects() -> List[str]:
    """Derive monitored objects from Schema Cache at runtime."""
    cache = SchemaCache()
    cached_schemas = cache.get_all()
    return list(cached_schemas.keys())

# Alarm threshold from config, not hardcoded
EXPECTED_OBJECT_COUNT = int(os.environ.get('EXPECTED_SCHEMA_OBJECT_COUNT', '9'))
```

### Read-Only Enforcement

```python
class SchemaDriftChecker:
    """
    IMPORTANT: This class is READ-ONLY.
    It compares SF Describe output with Schema Cache but NEVER mutates the cache.
    Schema updates are handled exclusively by Schema Discovery Lambda.
    """

    def __init__(self):
        self.discoverer = SchemaDiscoverer()  # For SF Describe calls
        self.cache = SchemaCache()            # Read-only access

    def check_drift(self) -> Dict[str, DriftResult]:
        # Discover from SF (read)
        sf_schemas = self.discoverer.discover_all()
        # Read from cache (read)
        cached_schemas = self.cache.get_all()
        # Compare and emit metrics (no writes to cache)
        return self._compare(sf_schemas, cached_schemas)
```

### False Positive Suppression

```python
def should_notify(drift_detected: bool, drift_delta: Dict) -> bool:
    """Only notify on NEW or WORSE drift, not during active discovery."""
    if is_discovery_running():
        return False
    if not drift_delta:  # No new drift
        return False
    return True
```

### Credential Reuse

```python
# Reuse EXACT same credential flow as Schema Discovery
from schema_discovery.discoverer import (
    get_salesforce_credentials,
    get_salesforce_instance_url,
    SchemaDiscoverer
)
```

---

## BA/QA Feedback Incorporated

### BA Feedback (Incorporated)
- [x] Dynamic object list (not hardcoded)
- [x] Read-only checker design
- [x] Precise coverage semantics defined
- [x] Config-driven alarm thresholds
- [x] Drift-delta notification logic
- [x] Picklist/value drift deferred to P3

### QA Feedback (Incorporated)
- [x] Batch metric emission (cost control)
- [x] Coverage calculation precision defined
- [x] Suppression window during discovery
- [x] Credential reuse from Schema Discovery
- [x] Unit test requirements defined

---

## Testing Requirements

```python
# Minimum test coverage for P1

def test_coverage_calculation_excludes_system_fields():
    """System fields should not inflate/deflate coverage percentages."""
    pass

def test_drift_detected_for_fake_fields():
    """Fields in cache but not in SF should be flagged as drift."""
    pass

def test_no_notification_during_discovery():
    """Suppress notifications when discovery Lambda is actively running."""
    pass

def test_dynamic_object_list():
    """Object list should come from cache, not hardcoded."""
    pass
```

---

## Deployment Steps

1. Create Lambda function with IAM role (DynamoDB read, CloudWatch write, Secrets Manager read)
2. Add dashboard and alarms to `monitoring-stack.ts`
3. Deploy with `npx cdk deploy SalesforceAISearch-Monitoring-dev`
4. Manually invoke Lambda to verify metrics appear
5. Verify dashboard renders correctly
6. Test alarm by temporarily setting threshold to trigger

---

## Time Estimate

| Phase | Duration | Tasks |
|-------|----------|-------|
| 1 | 3-4 hours | Lambda + metrics + read-only design |
| 2 | 2-3 hours | CDK dashboard + alarms + SSM config |
| 3 | 1-2 hours | Unit tests |
| 4 | 1-2 hours | Deploy + validation |

**Total: ~1.5 days** (10-13 hours)

---

## Progress Tracker

### P1 MVP Checklist

- [x] **39.1.1** Create `lambda/schema_drift_checker/` directory structure
- [x] **39.1.2** Implement `coverage.py` with precise calculation logic
- [x] **39.1.3** Implement `metrics.py` with batch CloudWatch emission
- [x] **39.1.4** Implement `index.py` main handler (read-only)
- [x] **39.1.5** Add dynamic object list logic
- [x] **39.2.1** Add Schema Drift Dashboard to `monitoring-stack.ts`
- [x] **39.2.2** Add CloudWatch Alarms to `monitoring-stack.ts`
- [x] **39.2.3** Add SSM parameter for expected object count (via env var)
- [x] **39.3.1** Write unit tests for coverage calculation
- [x] **39.3.2** Write unit tests for drift detection
- [x] **39.4.1** Deploy to dev environment
- [x] **39.4.2** Validate metrics in CloudWatch
- [x] **39.4.3** Validate dashboard renders
- [x] **39.4.4** Test alarm triggering

### P2 Report Checklist (Deferred)

- [ ] **39.5.1** Create S3 bucket with KMS + retention
- [ ] **39.5.2** Implement report generation
- [ ] **39.5.3** Add EventBridge nightly trigger
- [ ] **39.5.4** Implement drift-delta notification logic

---

## Dependencies

| Dependency | Location | Status |
|------------|----------|--------|
| SchemaDiscoverer | `lambda/schema_discovery/discoverer.py` | ✅ Exists |
| SchemaCache | `lambda/schema_discovery/cache.py` | ✅ Exists |
| SNS Topics | `lib/monitoring-stack.ts` | ✅ Exists |
| SF Credentials | Secrets Manager | ✅ Configured |

---

## Rollback Plan

If issues arise:
1. Disable EventBridge rule (if deployed)
2. Delete Lambda function
3. Remove dashboard/alarms from CDK and redeploy
4. No data plane impact - this is observational only

---

## QA Review Feedback (2025-12-12)

### Gaps Addressed

| Gap | Issue | Resolution |
|-----|-------|------------|
| #4 | Empty cache handling | Fixed: Empty cache now reports 0% coverage (not 100%). Added `EmptyCacheDetected` metric. |
| #5 | TotalObjectsCovered duplication | Verified: Already correct - emitted once per run without per-object dimensions. |

### Gaps Requiring Validation at Deploy

| Gap | Issue | Action Required |
|-----|-------|-----------------|
| #1 | Validation pending | Deploy and invoke Lambda, verify metrics/dashboard/alarms |
| #2 | Alarm flapping | Coverage alarms already use 3 evaluation periods - monitor for flapping |
| #3 | Credential reuse | Verified: Uses same `SchemaDiscoverer` credential flow from `schema_discovery/` |
| #6 | Dashboard sanity | Verify widget names match metric names after deploy |
| #7 | Failure alarm | `treatMissingData: BREACHING` is set - will fire if Lambda doesn't run |

### Code Changes Made Post-QA

1. `metrics.py`: Changed empty cache coverage from 100% to 0%
2. `metrics.py`: Added `EmptyCacheDetected` metric (1 if cache empty, 0 otherwise)
3. `test_coverage.py`: Added `TestEmptyCacheHandling` test class with 2 test cases

---

## Deployment Results (2025-12-12)

### Deployed Resources

| Resource | ARN/Name | Status |
|----------|----------|--------|
| Lambda | `arn:aws:lambda:us-west-2:382211616288:function:salesforce-ai-search-schema-drift-checker` | ✅ Deployed |
| Dashboard | `Salesforce-AI-Search-Schema-Drift` | ✅ Created |
| Alarm (fake-fields) | `salesforce-ai-search-schema-drift-fake-fields-critical` | ✅ Active (ALARM) |
| Alarm (filterable) | `salesforce-ai-search-schema-drift-filterable-coverage-warning` | ✅ Active (OK) |
| Alarm (relationship) | `salesforce-ai-search-schema-drift-relationship-coverage-warning` | ✅ Active (OK) |
| Alarm (objects) | `salesforce-ai-search-schema-drift-objects-covered-critical` | ✅ Active (OK) |
| Alarm (failure) | `salesforce-ai-search-schema-drift-check-failure-warning` | ✅ Active (OK) |
| EventBridge Rule | `salesforce-ai-search-schema-drift-check-nightly` | ✅ Created (6 AM UTC) |
| Lambda Layer | `salesforce-ai-search-schema-discovery-ingestion` | ✅ Created |

### Deployment Issues Resolved

1. **Layer imports**: Changed from relative imports (`from models`) to package-relative (`from .models`) in layer files
2. **Salesforce credentials**: Lambda requires `SALESFORCE_ACCESS_TOKEN` env var (manually configured to match Schema Discovery Lambda)

### Token Refresh (Resolved)

Token was refreshed using SF CLI:
```bash
sf org display --target-org ascendix-beta-sandbox --json
```

Both Lambdas updated with fresh `SALESFORCE_ACCESS_TOKEN`.

**Post-refresh validation:**
- `objects_checked`: 9
- `objects_with_drift`: 0
- `total_fake_fields`: 0
- All objects at 100% coverage
- `TotalFakeFields` metric now emitting 0

**Note for future**: Consider switching to OAuth client credentials flow for automatic token refresh.

### Metrics Verification

Successfully emitting to CloudWatch namespace `SalesforceAISearch/SchemaDrift`:
- Per-object metrics: SFFieldCount, CacheFieldCount, FilterableCoverage, RelationshipCoverage, etc.
- Aggregate metrics: TotalObjectsCovered, AvgFilterableCoverage, AvgRelationshipCoverage
- 97 metrics emitted per invocation

### Dashboard URL

`https://console.aws.amazon.com/cloudwatch/home?region=us-west-2#dashboards:name=Salesforce-AI-Search-Schema-Drift`

---

## Next Agent Instructions

If continuing this work:

1. Read this handoff document first
2. Check the Progress Tracker above for current status
3. Start with the next unchecked item
4. Update this handoff when P1 is complete
5. Mark completed items with [x] as you finish them

**Key files to understand:**
- `lambda/schema_discovery/discoverer.py` - SchemaDiscoverer class to reuse
- `lambda/schema_discovery/cache.py` - SchemaCache class to reuse
- `lib/monitoring-stack.ts` - Where dashboard/alarms go

**Critical constraints:**
- Drift checker MUST be read-only
- Object list MUST be dynamic (not hardcoded)
- Metrics MUST be batch-emitted for cost control
