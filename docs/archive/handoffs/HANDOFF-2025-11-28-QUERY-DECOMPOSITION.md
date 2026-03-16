# Handoff: LLM-Based Query Decomposition Implementation

**Date**: 2025-11-28
**Session Focus**: Implementing semantic query decomposition for CRE domain queries
**Status**: Paused - Needs comprehensive query pattern analysis before continuing

---

## Summary

Implemented an LLM-based query decomposition system that correctly identifies target entities and filters from natural language queries. The system works but exposed a fundamental limitation: **the Knowledge Base metadata doesn't include filterable fields** like `PropertySubType`, `City`, or `PropertyClass`, causing false positives when filtering by property attributes.

---

## What Was Built

### 1. Query Decomposition Module (`lambda/retrieve/query_decomposer.py`)
- Uses Claude Haiku 4.5 via Bedrock to decompose queries
- Returns structured JSON with target entity, filters, and traversal needs
- ~1.5s latency, can be tuned via YAML config

### 2. YAML Configuration (`lambda/retrieve/prompts/query_decomposition.yaml`)
- Editable system prompt for query interpretation
- Contains CRE domain knowledge (Property has City/PropertySubType, Deal doesn't)
- Includes multi-path traversal rules (Deal→Property, Deal→Availability→Property)
- Version controlled, hot-reloadable

### 3. Lambda Integration (`lambda/retrieve/index.py`)
- Feature flag: `QUERY_DECOMPOSER_ENABLED` (default: True)
- Decomposition runs after intent classification
- Supplemental Property search based on decomposition filters
- Direct connection prioritization for graph-discovered deals

---

## What Works

### Query Decomposition (Correct)
```
Query: "show active deals for class a office space in plano"

Decomposition:
{
  "target_entity": "Deal",
  "target_filters": {"Status": "Active"},
  "related_filters": {
    "Property": {
      "PropertyClass": "Class A",
      "PropertySubType": "Office",
      "City": "Plano"
    }
  },
  "needs_traversal": true
}
```

### Supplemental Property Search (Partial)
- Correctly builds search query: "Class A Office property in Plano"
- Finds additional properties not in initial vector search
- Preston Park Financial now appears in results (was missing before)

---

## The Problem

### Query That Fails
```
Query: "show active deals that are leases related to retail properties in dallas"

Result: Returns "3 Park Central Lease Listing" - an OFFICE property deal
```

### Root Cause
The Knowledge Base metadata only contains:
- `sobject` (e.g., "ascendix__Property__c")
- `recordId`
- `name`
- `ownerId`, `sharingBuckets` (security fields)

**Missing from metadata:**
- `PropertySubType` (Office, Retail, Industrial, etc.)
- `PropertyClass` (Class A, Class B, Class C)
- `City`, `State`

So when we search for "Retail property in Dallas":
1. We can only filter by `sobject = ascendix__Property__c`
2. Vector search returns semantically similar results
3. "3 Park Central" matches because its description mentions "retail centers"
4. But it's actually an Office property

---

## Files Changed

| File | Change |
|------|--------|
| `lambda/retrieve/query_decomposer.py` | NEW - LLM decomposition module |
| `lambda/retrieve/prompts/query_decomposition.yaml` | NEW - Editable system prompt config |
| `lambda/retrieve/index.py` | Added decomposition integration, supplemental search |
| `lambda/retrieve/requirements.txt` | Added PyYAML>=6.0 |

---

## Deployed Changes

- Lambda `salesforce-ai-search-retrieve` updated with decomposition code
- Query decomposition is LIVE and logging to CloudWatch
- Supplemental Property search is ACTIVE

---

## Next Steps (Agreed)

### Before Continuing Implementation

**Build a comprehensive query pattern matrix:**

1. **Enumerate common query patterns** users will ask
2. **Identify required filter fields** for each pattern
3. **Map entity relationships** and which filters apply where
4. **Determine KB metadata changes** needed

### Example Query Pattern Matrix (To Be Expanded)

| Query Pattern | Target | Required Filters |
|--------------|--------|------------------|
| "deals for retail properties in Dallas" | Deal | Property.PropertySubType, Property.City |
| "Class A office space available" | Availability | Property.PropertyClass, Property.PropertySubType |
| "leases expiring in 6 months" | Lease | Lease.TermExpirationDate |
| "deals for Preston Park Financial" | Deal | Property.Name |
| "accounts in Houston" | Account | Account.City |
| "active deals over $1M" | Deal | Deal.Status, Deal.GrossFeeAmount |
| "available space under $25/sqft" | Availability | Availability.AskingRate |

### Implementation Options (After Pattern Analysis)

**Option 1: Add Metadata Fields to KB Sync**
- Modify chunk sync process to include Property fields as metadata
- Re-sync all Property chunks
- Enable metadata filtering in supplemental search
- **Effort**: Medium (sync changes + full re-sync)

**Option 2: Post-Filter Results**
- After vector search, read chunk content
- Parse and validate filter matches
- Only include records that match criteria
- **Effort**: Low but adds latency

**Option 3: Separate Structured Index**
- Maintain a DynamoDB/OpenSearch index with structured Property data
- Query structured index for Property IDs matching filters
- Use those IDs as seeds for graph traversal
- **Effort**: Higher but most flexible

---

## Key Resources

| Resource | Value |
|----------|-------|
| Lambda Function URL | `https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/` |
| Knowledge Base ID | HOOACWECEX |
| API Key | M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ |
| Test User ID | 005dl00000Q6a3RAAR |
| Decomposition Model | us.anthropic.claude-haiku-4-5-20251001-v1:0 |

---

## Test Commands

```bash
# Test decomposition for Plano Class A Office (works)
cat > /tmp/test_plano.json << 'EOF'
{"query": "what are the active deals for class a office space in plano?", "salesforceUserId": "005dl00000Q6a3RAAR", "filters": {}}
EOF

curl -s -X POST 'https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d @/tmp/test_plano.json

# Test decomposition for Dallas Retail (returns wrong property type)
cat > /tmp/test_retail.json << 'EOF'
{"query": "show active deals that are leases related to retail properties in dallas", "salesforceUserId": "005dl00000Q6a3RAAR", "filters": {}}
EOF

curl -s -X POST 'https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d @/tmp/test_retail.json

# Check CloudWatch logs for decomposition
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --region us-west-2 --since 5m \
  | grep -E "(decomposition|supplemental)"
```

---

## Reference Documents

| Document | Location | Relevance |
|----------|----------|-----------|
| Query Decomposition PRD | `docs/analysis/SEMANTIC_QUERY_DECOMPOSITION_PRD.md` | Original requirements |
| Query Decomposition YAML | `lambda/retrieve/prompts/query_decomposition.yaml` | Editable config |
| Intent Router | `lambda/retrieve/intent_router.py` | Current regex-based routing |

---

## Session Metrics

| Metric | Value |
|--------|-------|
| Decomposition Latency | ~1.5s (Haiku 4.5) |
| Supplemental Search | ~300ms |
| Properties Found | 6-10 per query |
| Direct Connected Deals | 18 found for Plano query |

---

## Questions for Next Session

1. What are the 20-30 most common query patterns users will ask?
2. Which property attributes are most important to filter on?
3. Is re-syncing the KB acceptable (time/effort)?
4. Should we consider a separate structured index for entity attributes?
