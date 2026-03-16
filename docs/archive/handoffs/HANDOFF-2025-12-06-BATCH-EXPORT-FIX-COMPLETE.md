# Handoff: Batch Export Pipeline Fix - COMPLETE

**Date:** 2025-12-06
**Priority:** RESOLVED
**Status:** POC VALIDATION READY

---

## Summary

The data ingestion pipeline is now fully operational. All Salesforce batch exports successfully flow through to Bedrock KB with proper field extraction. Real queries return real data with City, State, and PropertyClass fields.

---

## Issues Identified & Resolved

### Issue 1: RecordType.Name in IndexConfiguration (ROOT CAUSE)

**Symptom:** Batch jobs completed with "0 errors" but made no callouts to Lambda.

**Root Cause:** The `IndexConfiguration.Property` metadata had `RecordType.Name` in `Text_Fields__c`. This is a relationship field query notation. When the batch code called `record.get('RecordType')`, it threw:
```
System.SObjectException: Invalid field RecordType for ascendix__Property__c
```

The exception was caught silently in `execute()`, logged to a non-existent error object, and the batch continued without actually sending data.

**Fix:** Removed `RecordType.Name` from `IndexConfiguration.Property.Text_Fields__c`:
```xml
<!-- Before -->
<value>Name, RecordType.Name, ascendix__City__c, ascendix__State__c, ...</value>

<!-- After -->
<value>Name, ascendix__City__c, ascendix__State__c, ...</value>
```

---

### Issue 2: AI_Search_Config__mdt Pointing to Wrong Endpoint

**Symptom:** Even after fixing Named Credentials, batch exports didn't reach Lambda.

**Root Cause:** The batch code uses `AI_Search_Config__mdt.Ingest_Endpoint__c` for the callout URL, NOT Named Credentials. The metadata was pointing to the old API Gateway URL.

**Fix:** Updated `AI_Search_Config.Default.md-meta.xml`:
```xml
<field>Ingest_Endpoint__c</field>
<value>https://fytm2g6rjkrfoy67klfwhwhbii0qqfky.lambda-url.us-west-2.on.aws</value>
```

---

### Issue 3: Missing Remote Site Setting

**Symptom:** Callouts blocked by Salesforce security.

**Root Cause:** No Remote Site Setting existed for the new Lambda Function URL.

**Fix:** Created `Ascendix_RAG_Lambda.remoteSite-meta.xml`:
```xml
<RemoteSiteSetting>
    <isActive>true</isActive>
    <url>https://fytm2g6rjkrfoy67klfwhwhbii0qqfky.lambda-url.us-west-2.on.aws</url>
</RemoteSiteSetting>
```

---

### Issue 4: AI_Search_Export_Error__c Missing Fields

**Symptom:** 790 error records created but no error messages visible.

**Root Cause:** The `AI_Search_Export_Error__c` object only has `Id` and `Name` fields. The batch code references `Job_Id__c`, `Error_Message__c`, `Stack_Trace__c`, etc. that don't exist. Error logging silently fails.

**Status:** NOT FIXED - Low priority. Errors are now rare since the root cause was fixed.

---

## Validation Results

### Test 1: Batch Execution
```
Job ID: 707dl0000a23M9BAAU
Status: Completed
Items Processed: 50 batches
Errors: 0
Lambda Invocations: 50 (confirmed in CloudWatch)
Step Functions Executions: 50 (all SUCCEEDED)
```

### Test 2: S3 Chunk Content
```bash
aws s3 cp s3://salesforce-ai-search-data-382211616288-us-west-2/chunks/ascendix__Property__c/a0afk000000PudrAAC/chunk-0.txt -
```
**Output:**
```
# 1701 Gates Ave - Ridgewood, New York

Name: 1701 Gates Ave - Ridgewood, New York
City: Ridgewood
State: NY
```

### Test 3: Query for NY Properties
```bash
curl -X POST '.../answer' -d '{"query": "find properties in New York", ...}'
```
**Result:** 5 properties returned with City, State, PropertyClass data:
- 575 Lexington Ave, New York, NY 10022
- 300 Madison Ave. (Class A)
- 3 World Financial Center (Class A)
- 407-409 East 70th Street
- 141 East 55th Street

### Test 4: Query for Class A in Plano
```bash
curl -X POST '.../answer' -d '{"query": "show me Class A office properties in Plano", ...}'
```
**Result:** 3 Class A properties in Plano, TX:
- Plano Office Condo (Class A, Plano, TX)
- NYLO Plano @ Legacy (Class A, Plano, TX)
- Berkeley Square (Class A, Plano, TX)

---

## Files Modified

| File | Change | Deployed |
|------|--------|----------|
| `salesforce/customMetadata/IndexConfiguration.Property.md-meta.xml` | Removed `RecordType.Name` from Text_Fields__c | Yes |
| `salesforce/customMetadata/AI_Search_Config.Default.md-meta.xml` | Updated Ingest_Endpoint__c to Lambda URL | Yes (previous session) |
| `salesforce/remoteSiteSettings/Ascendix_RAG_Lambda.remoteSite-meta.xml` | New - allows Lambda callouts | Yes (previous session) |
| `salesforce/namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml` | Updated endpoint (not used by batch) | Yes (previous session) |

---

## Current System State

| Component | Status | Details |
|-----------|--------|---------|
| Answer Lambda | Working | `https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer` |
| Ingest Lambda | Working | `https://fytm2g6rjkrfoy67klfwhwhbii0qqfky.lambda-url.us-west-2.on.aws/` |
| Chunking Lambda | Working | FALLBACK_CONFIGS has Property field config |
| Bedrock KB | Synced | 10,663 docs, 1,661 modified, 0 failed |
| SF Batch Export | Working | 50 batches processed successfully |
| Query API | Working | Returns real Property data with all fields |

---

## Pending Issues (Low Priority)

### 1. AI_Search_Export_Error__c Fields Missing
The error logging object doesn't have the custom fields the batch code expects. Error records are created with just auto-number Name. To fix:
- Create fields: `Job_Id__c`, `Object_Type__c`, `Error_Message__c`, `Stack_Trace__c`, `Record_Count__c`, `Timestamp__c`
- Or remove error logging code from `AISearchBatchExport.cls`

### 2. Background Docker Push Still Running
A background Docker push from a previous session is still running (shell 125f48). It was part of a failed attempt to add `/ingest` endpoint to the answer Lambda. The push can be safely cancelled as the answer Lambda was rolled back to a working image.

---

## Next Steps

1. **Task 29 (Final Checkpoint):** Prepare honest POC validation report with real query results
2. **Production Readiness:** Add API key authentication to ingest Lambda Function URL
3. **Monitoring:** Consider adding CloudWatch alarms for batch export failures

---

## Key Learnings

1. **Silent failures are dangerous:** The batch caught exceptions but the error logging failed silently. Always test error paths.

2. **Relationship fields in Text_Fields__c:** SOQL can query `RecordType.Name`, but `record.get('RecordType')` fails. The batch code needs enhancement to handle relationship fields properly.

3. **Multiple configuration sources:** Salesforce has Named Credentials, Custom Metadata, and Remote Site Settings. The batch code uses Custom Metadata directly, not Named Credentials.

4. **Batch context debugging:** No debug logs were generated for batch jobs. Had to simulate batch logic in anonymous Apex to find the root cause.
