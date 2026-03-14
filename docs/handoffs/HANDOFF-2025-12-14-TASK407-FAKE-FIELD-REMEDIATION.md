# Handoff: Task 40.7 Fake Field Remediation

**Date:** 2025-12-14
**Task:** 40.7 Field Audit Guard - Fake Field Remediation
**Status:** CLOSED

## Summary

Remediated all 5 fake fields detected by the audit script. Audit now returns exit 0 with zero fake fields.

## Problem

The field audit script (`scripts/audit_fields.py`) detected 5 fake fields being referenced in code/config that do not exist in Salesforce:

| Object | Fake Field | Issue |
|--------|-----------|-------|
| Property | `ascendix__Submarket__c` | Case mismatch (should be `SubMarket` with capital M) |
| Availability | `ascendix__Submarket__c` | Case mismatch |
| Availability | `ascendix__Notes__c` | Field doesn't exist |
| Lease | `ascendix__Status__c` | Field doesn't exist |
| Lease | `ascendix__Notes__c` | Field doesn't exist |

## Resolution

### 1. SubMarket Casing Fix (6 files)

Changed `ascendix__Submarket__c` → `ascendix__SubMarket__c`:

- `lambda/retrieve/schema_decomposer.py` (lines 786, 828)
- `lambda/retrieve/index.py` (line 1664)
- `lambda/retrieve/cross_object_handler.py` (line 117)
- `lambda/retrieve/query_decomposition_poc.py` (line 60)
- `lambda/retrieve/test_cross_object_handler.py` (line 73)

### 2. Lease Fake Fields (Notes, Status)

**Lease does NOT have `ascendix__Status__c` or `ascendix__Notes__c`.**

- Changed `ascendix__Notes__c` → `ascendix__Description__c` (verified exists, type: textarea)
- Removed `ascendix__Status__c` from view schema (field doesn't exist)

Files modified:
- `lambda/derived_views/index.py` - Updated `_upsert_lease()` method
- `lambda/derived_views/backfill.py` - Updated SOQL and `_transform_record()`

### 3. Availability Fake Field (Notes)

**Availability does NOT have `ascendix__Notes__c`.**

- Changed `ascendix__Notes__c` → `ascendix__SpaceDescription__c` (verified exists, type: textarea)
- `ascendix__Status__c` is VALID on Availability (kept)

Files modified:
- `lambda/derived_views/index.py` - Updated `_upsert_availability()` method
- `lambda/derived_views/backfill.py` - Updated SOQL and `_transform_record()`

### 4. Salesforce IndexConfiguration Metadata

Fixed SubMarket casing in relationship fields:

- `salesforce/customMetadata/IndexConfiguration.Property.md-meta.xml`
- `salesforce/customMetadata/IndexConfiguration.Availability.md-meta.xml`

Deployed to sandbox: `sf project deploy start --source-dir customMetadata/...`

### 5. Test Files Updated

- `lambda/derived_views/test_index.py` - Updated test data
- `lambda/derived_views/test_index_property.py` - Updated record strategies

## Verification

```
Audit Results:
- fake_count: 0
- valid_count: 91
- missing_export_count: 233 (P3 triage item)
- status: PASS

Tests: 28/28 passing

Deployments:
- SF metadata: Deployed 2025-12-14T08:54:21Z
- Retrieve Lambda: Deployed 2025-12-14T08:58:25Z
```

## Field Reference (Correct Names)

| Object | Correct Field | Label | Type |
|--------|--------------|-------|------|
| Property | `ascendix__SubMarket__c` | Sub Market | reference |
| Availability | `ascendix__SubMarket__c` | Sub Market | reference |
| Availability | `ascendix__Status__c` | Status | picklist |
| Availability | `ascendix__SpaceDescription__c` | Space Description | textarea |
| Lease | `ascendix__Description__c` | Description | textarea |
| Lease | `ascendix__TermExpirationDate__c` | Expiration Date | date |

## Outstanding Items

### P3: Missing Exports (233 fields)

The audit reports 233 Salesforce filterable/relationship fields that exist but aren't exported. These are warnings, not errors. Triage needed to determine which should be added to IndexConfiguration.

### Backfill Recommendation

After next full CDK deploy, run backfill for affected views:

```bash
# From lambda/derived_views directory
python3 -c "
from backfill import LeasesBackfillProcessor, AvailabilityBackfillProcessor
from salesforce_client import SalesforceClient

sf = SalesforceClient.from_ssm()
LeasesBackfillProcessor(sf).run()
AvailabilityBackfillProcessor(sf).run()
"
```

## Files Modified

```
lambda/retrieve/schema_decomposer.py
lambda/retrieve/index.py
lambda/retrieve/cross_object_handler.py
lambda/retrieve/query_decomposition_poc.py
lambda/retrieve/test_cross_object_handler.py
lambda/derived_views/index.py
lambda/derived_views/backfill.py
lambda/derived_views/test_index.py
lambda/derived_views/test_index_property.py
salesforce/customMetadata/IndexConfiguration.Property.md-meta.xml
salesforce/customMetadata/IndexConfiguration.Availability.md-meta.xml
.kiro/specs/graph-aware-zero-config-retrieval/tasks.md
```

## Key Learnings

1. **Case sensitivity matters**: Salesforce field names are case-sensitive. `Submarket` ≠ `SubMarket`.

2. **Verify fields exist before using**: Always check SF Describe API before referencing fields in code.

3. **IndexConfiguration drives audit**: The audit script queries live Salesforce IndexConfiguration__mdt, not local XML files. Deploy metadata before re-running audit.

4. **Availability vs Lease fields differ**:
   - Availability has `Status__c` and `SpaceDescription__c`
   - Lease has `Description__c` but NO `Status__c` or `Notes__c`
