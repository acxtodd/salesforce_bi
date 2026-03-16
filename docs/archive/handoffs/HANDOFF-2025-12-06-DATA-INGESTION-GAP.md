# Handoff: Critical Data Ingestion Gap Discovered

**Date:** 2025-12-06
**Priority:** HIGH
**Status:** BLOCKED - Requires Fix Before POC Validation

---

## Executive Summary

During Phase 2 canary deployment validation, we discovered that **query results are returning synthetic/mocked test data instead of real Salesforce data**. The POC cannot be validated until this is fixed.

---

## The Problem

### What We Found

| Data Source | Type | Example |
|-------------|------|---------|
| Query Result: "Plano Office Tower" | **SYNTHETIC** | `a0afk000000TEST1` |
| Real SF Property: "1717 McKinney" | **REAL** (but incomplete) | `a0adl000004Djg9AAC` |

### Real Property Record (from S3):
```
# 1717 McKinney

Name: 1717 McKinney
```
**Missing:** PropertyClass, City, State, Type, Size, etc.

### Synthetic Test Record (from S3):
```
# Plano Office Tower

Name: Plano Office Tower
Property Class: A
City: Plano
State: TX
```
**Has all fields** because it was manually seeded with proper metadata.

---

## Root Cause Analysis

### 1. Chunking Lambda Configuration Gap

The `lambda/chunking/index.py` has `FALLBACK_CONFIGS` for some CRE objects but **NOT for Property**:

```python
# Lines 51-75: FALLBACK_CONFIGS defined for:
FALLBACK_CONFIGS = {
    "ascendix__Availability__c": {...},  # Has relationship fields
    "ascendix__Lease__c": {...},         # Has relationship fields
    "ascendix__Deal__c": {...},          # Has relationship fields
    # ascendix__Property__c is MISSING!
}
```

### 2. Property Falls Through to Default Config

When Property records are processed, they use `DEFAULT_CHUNKING_CONFIG`:

```python
# Lines 77-84:
DEFAULT_CHUNKING_CONFIG = {
    "Display_Name_Field__c": "Name",
    "Text_Fields__c": "Name",              # <-- ONLY Name!
    "Long_Text_Fields__c": "",
    "Relationship_Fields__c": "OwnerId",   # <-- No useful relationships
    "Enabled__c": True,
}
```

### 3. No Config Cache Table

The `salesforce-ai-search-config-cache` DynamoDB table **does not exist**, so `ConfigurationCache` returns nothing.

### 4. Result: Property Records Missing Key Fields

**Metadata comparison:**

| Field | Real Property | Synthetic Property |
|-------|--------------|-------------------|
| `sobject` | ascendix__Property__c | ascendix__Property__c |
| `name` | 1717 McKinney | Plano Office Tower |
| `ascendix__PropertyClass__c` | **MISSING** | A |
| `ascendix__City__c` | **MISSING** | Plano |
| `ascendix__State__c` | **MISSING** | TX |

---

## Impact

1. **POC Cannot Be Validated** - Using synthetic data doesn't prove the system works
2. **~2,468 Property Records** are in S3 with only Name field extracted
3. **Queries for "Class A office in Plano"** return synthetic test data, not real properties
4. **Acceptance tests are misleading** - They pass because of seeded test data

---

## Data Inventory

### S3 Bucket: `salesforce-ai-search-data-382211616288-us-west-2`

| Object Type | Record Count | Data Quality |
|-------------|--------------|--------------|
| `ascendix__Property__c` | ~2,468 | Name only (BROKEN) |
| `Account` | Multiple | Basic fields |
| `ascendix__Availability__c` | Few | Has TEST records |

### DynamoDB Derived Views (100% Synthetic):

| Table | Status |
|-------|--------|
| `salesforce-ai-search-availability-view` | Synthetic test data |
| `salesforce-ai-search-vacancy-view` | Synthetic test data |
| `salesforce-ai-search-leases-view` | Synthetic test data |
| `salesforce-ai-search-activities-agg` | Synthetic test data |
| `salesforce-ai-search-sales-view` | Synthetic test data |

---

## Required Fix

### Step 1: Add Property to FALLBACK_CONFIGS

Edit `lambda/chunking/index.py` to add:

```python
FALLBACK_CONFIGS = {
    # ... existing configs ...

    "ascendix__Property__c": {
        "Display_Name_Field__c": "Name",
        "Text_Fields__c": "Name, ascendix__PropertyClass__c, ascendix__City__c, ascendix__State__c, ascendix__Country__c, ascendix__PropertyType__c, ascendix__TotalBuildingSize__c, ascendix__YearBuilt__c",
        "Long_Text_Fields__c": "ascendix__PropertyDescription__c",
        "Relationship_Fields__c": "OwnerId, RecordType.Name",
        "Enabled__c": True,
    },
}
```

### Step 2: Deploy Updated Lambda

```bash
cd lambda/chunking
zip -r chunking.zip .
aws lambda update-function-code \
  --function-name salesforce-ai-search-chunking \
  --zip-file fileb://chunking.zip \
  --region us-west-2
```

### Step 3: Re-Ingest Property Records

Trigger backfill/CDC to re-process all Property records through the updated pipeline.

### Step 4: Verify Real Data in KB

```bash
# Check a real property has all fields
aws s3 cp s3://salesforce-ai-search-data-382211616288-us-west-2/chunks/ascendix__Property__c/[REAL_ID]/chunk-0.txt -
```

### Step 5: Remove Synthetic Test Data

Delete TEST records from S3:
```bash
aws s3 rm s3://salesforce-ai-search-data-382211616288-us-west-2/chunks/ascendix__Property__c/a0afk000000TEST1/ --recursive
```

---

## Questions to Resolve

1. **What Property fields exist in the Salesforce sandbox?**
   - Need to query Salesforce Describe API to get available fields
   - May need to check which fields have data populated

2. **How to trigger Property re-ingestion?**
   - Is there a backfill mechanism?
   - Can we use CDC to re-process?
   - Manual Step Functions execution?

3. **Should we create the config-cache table?**
   - Would allow dynamic configuration without code changes
   - Could be populated from Salesforce custom metadata

---

## Files Involved

| File | Issue |
|------|-------|
| `lambda/chunking/index.py` | Missing Property in FALLBACK_CONFIGS |
| `scripts/seed_derived_views.py` | Creates synthetic test data |
| `scripts/seed_vocab_cache.py` | Seeds vocabulary (OK) |

---

## Timeline Impact

| Task | Status | Blocked By |
|------|--------|------------|
| Task 28.3 (Phase 2 Canary) | Marked complete but invalid | Using synthetic data |
| Task 28.4 (Runbooks) | Pending | Should wait for real data |
| Task 29 (Final Checkpoint) | Blocked | Cannot validate with synthetic data |

---

## Verification Commands

```bash
# Check Property record content (should show only Name for real records)
aws s3 cp s3://salesforce-ai-search-data-382211616288-us-west-2/chunks/ascendix__Property__c/a0adl000004Djg9AAC/chunk-0.txt -

# Check Property metadata (should be missing key fields)
aws s3 cp s3://salesforce-ai-search-data-382211616288-us-west-2/chunks/ascendix__Property__c/a0adl000004Djg9AAC/chunk-0.txt.metadata.json - | python3 -m json.tool

# Count Property records
aws s3 ls s3://salesforce-ai-search-data-382211616288-us-west-2/chunks/ascendix__Property__c/ | wc -l

# List TEST records that should be removed
aws s3 ls s3://salesforce-ai-search-data-382211616288-us-west-2/chunks/ascendix__Property__c/ | grep TEST
```

---

## Next Steps

1. **Determine Property fields** - Query Salesforce sandbox for available fields
2. **Update chunking Lambda** - Add Property to FALLBACK_CONFIGS
3. **Deploy and re-ingest** - Process all Property records with correct config
4. **Validate with real data** - Run acceptance tests against actual Salesforce records
5. **Clean up synthetic data** - Remove TEST records from KB

---

## Key Insight

> "Even though it's a POC, we MUST prove this works, and we have plenty of data in the sandbox to do so." - User feedback

The POC validation is meaningless if we're testing against synthetic data. The system needs to demonstrate it works with **real Salesforce CRE data** to prove value.
