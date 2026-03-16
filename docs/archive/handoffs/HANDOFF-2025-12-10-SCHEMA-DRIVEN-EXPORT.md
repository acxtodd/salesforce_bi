# Handoff: Schema-Driven Export Integration

**Date:** 2025-12-10
**Tasks:** Task 37 (Schema Cache Remediation), Task 34 (Schema-Driven Export Integration)
**Status:** Both Complete and Deployed

---

## Summary

This session completed two critical tasks that fix schema drift between query decomposition and batch export:

1. **Task 37**: Remediated schema cache - replaced 20 fake fields with 350+ real fields from SF Describe API
2. **Task 34**: Connected Schema Discovery to Batch Export - AISearchBatchExport now reads field config from Schema Cache API

## Architecture Change

**Before (Manual, Error-Prone):**
```
IndexConfiguration__mdt (manual) → Batch Export → Graph (drift risk)
Schema Discovery → Schema Cache → Query Planner (different fields!)
```

**After (Automatic, Consistent):**
```
Schema Discovery → Schema Cache → Query Planner (expects fields)
                        ↓
              Schema Cache API → Batch Export → Graph (same fields!)
```

---

## Deployments Completed

### AWS (CDK)
- **Stack:** `SalesforceAISearch-Api-dev`
- **New Lambda:** `salesforce-ai-search-schema-api`
- **New Endpoint:** `GET /schema/{objectApiName}`
- **Endpoint URL:** `https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/schema`

### Salesforce
- **Classes Deployed:**
  - `SchemaCacheClient.cls` (NEW) - Apex client for Schema Cache API
  - `AISearchBatchExport.cls` (MODIFIED) - Now uses Schema Cache first
- **Metadata Updated:**
  - `IndexConfiguration__mdt` - Added `Override_Schema_Cache__c`, `Additional_Fields__c`

---

## Files Created/Modified

| File | Change |
|------|--------|
| `lambda/schema_api/index.py` | NEW - Lightweight schema cache API Lambda |
| `lambda/schema_discovery/index.py` | Added `get_export_fields` operation |
| `lambda/schema_discovery/discoverer.py` | Added `_extract_record_types()` method |
| `lib/api-stack.ts` | Added `/schema/{objectApiName}` endpoint |
| `salesforce/classes/SchemaCacheClient.cls` | NEW - Apex client with Platform Cache |
| `salesforce/classes/AISearchBatchExport.cls` | Uses Schema Cache with IndexConfig fallback |
| `salesforce/objects/IndexConfiguration__mdt.object` | Added override fields |
| `docs/guides/SCHEMA_DISCOVERY_CREDENTIALS_SETUP.md` | NEW - Credentials setup guide |

---

## How It Works

### AISearchBatchExport Field Resolution Priority

1. **Check `Override_Schema_Cache__c`** - If true, use IndexConfiguration fields only
2. **Call Schema Cache API** via `SchemaCacheClient.getExportFields()`
3. **Auto-include `RecordType.Name`** when `has_record_types: true`
4. **Add `Additional_Fields__c`** from IndexConfiguration if specified
5. **Fall back to IndexConfiguration** if Schema Cache unavailable

### Schema Cache API Response

```json
{
  "success": true,
  "sobject": "ascendix__Property__c",
  "text_fields": ["Name", "ascendix__City__c", ...],
  "filterable_fields": [{"name": "RecordType", "label": "Record Type", "values": [...]}],
  "relationship_fields": [{"name": "OwnerId", "label": "Owner", "related_to": "User"}],
  "graph_attributes": ["Name", "ascendix__City__c", "ascendix__State__c", "RecordType", "RecordType.Name"],
  "has_record_types": true,
  "field_counts": {"text": 84, "filterable": 27, "relationships": 19, "graph_attributes": 7}
}
```

---

## Schema Discovery Results

After running `discover_all`, the schema cache now contains:

| Object | Filterable | Relationships | RecordType |
|--------|------------|---------------|------------|
| ascendix__Property__c | 27 | 19 | Yes |
| ascendix__Deal__c | 20 | 27 | Yes |
| ascendix__Availability__c | 6 | 10 | Yes |
| ascendix__Listing__c | 7 | 13 | Yes |
| ascendix__Inquiry__c | 4 | 17 | No |
| ascendix__Lease__c | 6 | 15 | Yes |
| Account | 10 | 5 | No |
| Contact | 5 | 8 | No |

---

## Verification Commands

### Test Schema API
```bash
API_KEY=$(aws apigateway get-api-key --api-key hfhxij4lr0 --include-value --region us-west-2 --query 'value' --output text)
curl -s "https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/schema/ascendix__Property__c" -H "x-api-key: $API_KEY" | python3 -m json.tool
```

### Test Schema Discovery Lambda
```bash
aws lambda invoke --function-name salesforce-ai-search-schema-discovery \
  --payload '{"operation": "get_export_fields", "sobject": "ascendix__Property__c"}' \
  --cli-binary-format raw-in-base64-out --region us-west-2 /tmp/result.json
```

### Test Query (End-to-End)
```bash
curl -s -X POST "https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer" \
  -H "x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ" \
  -H "Content-Type: application/json" \
  -d '{"query": "show me class A office properties in plano", "salesforceUserId": "005dl00000Q6a3RAAR"}'
```

---

## Token Management

The Schema Discovery Lambda uses a Salesforce access token that expires (~2 hours). To refresh:

```bash
ACCESS_TOKEN=$(sf org display --target-org ascendix-beta-sandbox --json | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['accessToken'])")
aws lambda update-function-configuration --function-name salesforce-ai-search-schema-discovery \
  --environment "Variables={SALESFORCE_INSTANCE_URL=https://ascendix-agentforce-demo--beta.sandbox.my.salesforce.com,SCHEMA_CACHE_TABLE=salesforce-ai-search-schema-cache,SALESFORCE_ACCESS_TOKEN=$ACCESS_TOKEN,LOG_LEVEL=INFO}" \
  --region us-west-2
```

For automated token refresh, see `docs/guides/SCHEMA_DISCOVERY_CREDENTIALS_SETUP.md`.

---

## Next Steps

1. **Task 38**: Ingest-time field contract enforcement (CI gate)
2. **Task 28**: Complete canary deployment (Phase 2)
3. **Optional**: Configure Platform Cache partition in Salesforce for SchemaCacheClient caching
4. **Optional**: Set up automated SF token refresh with Client Credentials flow

---

## Known Limitations

1. **Platform Cache not configured** - SchemaCacheClient works without caching (graceful degradation)
2. **SF token expiration** - Manual refresh required unless Client Credentials flow is configured
3. **Task 34.6-34.7 deferred** - Field validation and coverage reports are lower priority enhancements

---

## Documentation

- `docs/guides/SCHEMA_DISCOVERY_CREDENTIALS_SETUP.md` - Lambda credentials setup
- `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md` - Full task tracking

---

*Handoff created: 2025-12-10 08:50 UTC*
