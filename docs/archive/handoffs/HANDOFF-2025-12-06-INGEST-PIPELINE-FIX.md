# Handoff: Ingest Pipeline Fix - Action Required

**Date:** 2025-12-06
**Priority:** HIGH - Blocking POC Validation
**Status:** REQUIRES USER ACTION IN SALESFORCE

---

## Summary

The data ingestion pipeline has been fixed on the AWS side, but requires a Salesforce Named Credential update to complete the connection. Once updated, Property records can be re-ingested with full field extraction.

---

## What Was Fixed

### 1. Chunking Lambda Updated
Added `ascendix__Property__c` to FALLBACK_CONFIGS with all key fields:
- `ascendix__PropertyClass__c`
- `ascendix__PropertyType__c`
- `ascendix__Status__c`
- `ascendix__City__c`
- `ascendix__State__c`
- `ascendix__Submarket__c`
- `ascendix__Address__c`
- `ascendix__TotalSqFt__c`
- And more...

### 2. Ingest Lambda Function URL Created
A new public endpoint is available for Salesforce batch exports:
```
https://fytm2g6rjkrfoy67klfwhwhbii0qqfky.lambda-url.us-west-2.on.aws/
```

This endpoint:
- Accepts POST requests with Property records
- Triggers Step Functions ingestion pipeline
- Processes through chunking Lambda with correct field extraction
- No API key required (to be added for production)

### 3. Test Verified
```bash
curl -s -X POST "https://fytm2g6rjkrfoy67klfwhwhbii0qqfky.lambda-url.us-west-2.on.aws/" \
  -H "Content-Type: application/json" \
  -d '{"sobject": "ascendix__Property__c", "records": [{"Id": "test", "Name": "Test"}]}'

# Response: {"accepted": true, "jobId": "arn:aws:states:...", "recordCount": 1, "sobject": "ascendix__Property__c"}
```

---

## Required User Actions

### Step 1: Update Salesforce Named Credential

1. Navigate to **Setup > Named Credentials**
2. Find `Ascendix_RAG_API`
3. Update the **URL** field:
   - **Old:** `https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws`
   - **New:** `https://fytm2g6rjkrfoy67klfwhwhbii0qqfky.lambda-url.us-west-2.on.aws`
4. Save

### Step 2: Run Property Re-Index

Execute the batch export script in Developer Console or VS Code:

```bash
sf apex run --file scripts/trigger_property_reindex.apex --target-org ascendix-beta-sandbox
```

Or run directly in Anonymous Apex:
```apex
AISearchBatchExport batch = new AISearchBatchExport('ascendix__Property__c', 8760);
Id jobId = Database.executeBatch(batch, 50);
System.debug('Job ID: ' + jobId);
```

### Step 3: Monitor Progress

1. **Salesforce:** Setup > Apex Jobs - check batch job status
2. **AWS Step Functions:** Check for new executions
   ```bash
   aws stepfunctions list-executions \
     --state-machine-arn arn:aws:states:us-west-2:382211616288:stateMachine:salesforce-ai-search-ingestion \
     --max-results 5 --region us-west-2
   ```

### Step 4: Sync Bedrock KB

After ingestion completes:
```bash
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id HOOACWECEX \
  --data-source-id <data-source-id> \
  --region us-west-2
```

---

## Technical Details

### Why the Docker Fix Failed

The answer Lambda uses Docker with Lambda Web Adapter. Building on Mac (ARM64) results in incorrect lambda-adapter binary architecture (exec format error). The fix required:
1. Explicit `--platform linux/amd64` in Dockerfile
2. Using x86_64-specific lambda-adapter image tag

The answer Lambda was rolled back to working image to preserve /answer functionality.

### Alternative: Use Separate Ingest Lambda

The `salesforce-ai-search-ingest` Lambda:
- Already exists and works correctly
- Has its own Function URL
- Doesn't require Docker (uses Python runtime)
- Is the recommended path forward

---

## Current State

| Component | Status | URL |
|-----------|--------|-----|
| Answer Lambda | Working | `https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer` |
| Ingest Lambda | Working | `https://fytm2g6rjkrfoy67klfwhwhbii0qqfky.lambda-url.us-west-2.on.aws/` |
| Chunking Lambda | Updated | Has Property field config |
| Bedrock KB | Stale | Contains Name-only records |
| SF Named Credential | Needs Update | Points to answer Lambda |

---

## Verification After Re-Ingestion

1. Check S3 for Property records with all fields:
```bash
aws s3 cp s3://salesforce-ai-search-data-382211616288-us-west-2/chunks/ascendix__Property__c/<RECORD_ID>/chunk-0.txt - --region us-west-2
```

Expected output should include PropertyClass, City, State, etc.

2. Test query:
```bash
curl -s -X POST 'https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d '{"query": "find Class A office in Dallas", "salesforceUserId": "005dl00000Q6a3RAAR"}'
```

Should return properties with full details (not just names).

---

## Files Modified

| File | Change |
|------|--------|
| `lambda/chunking/index.py` | Added `ascendix__Property__c` to FALLBACK_CONFIGS |
| `lambda/answer/Dockerfile` | Updated for x86_64 (rolled back) |
| `lambda/answer/main.py` | Added /ingest endpoint (not deployed) |

---

## Next Steps After Re-Ingestion

1. Run honest acceptance tests
2. Document results
3. Prepare Task 29 (Final Checkpoint)
