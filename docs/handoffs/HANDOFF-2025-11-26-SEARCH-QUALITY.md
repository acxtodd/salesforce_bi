# Handoff: Search Quality & Semantic Search Limitations

**Date**: 2025-11-26
**Session Focus**: Debugging search issues, diagnosing semantic search limitations
**Status**: Paused - Ready for next session

---

## Summary

This session addressed two bugs and uncovered a fundamental limitation in the current pure vector search approach that prevents queries like "top 10 deals by fee" from returning the correct high-value records.

---

## Issues Fixed

### 1. LWC Score Display Error
**Error**: `e.score.toFixed is not a function`

**Root Cause**: Lambda returns `score` as a string (e.g., `"0.43"`), but LWC called `.toFixed()` which only works on numbers.

**Fix Applied** (`salesforce/lwc/ascendixAiSearch/ascendixAiSearch.js:526`):
```javascript
// Before
score: citation.score ? citation.score.toFixed(2) : 'N/A',

// After
score: citation.score ? Number(citation.score).toFixed(2) : 'N/A',
```

**Deployed**: Yes - to ascendix-beta-sandbox

---

### 2. AuthZ Filtering - Missing Data Owner
**Symptom**: Queries returning "I don't have enough information" or no results

**Root Cause**: AuthZ cache only had one seed data owner (`005fk0000006rG9AAI`), but newer CRE batch data was owned by `005fk0000007zjVAAQ`.

**Fix Applied** (`lambda/authz/index.py:145-154`):
```python
# Added second data owner to POC whitelist
SEED_DATA_OWNERS = [
    '005fk0000006rG9AAI',  # Original seed data owner
    '005fk0000007zjVAAQ',  # CRE batch import owner
]
```

**Deployed**: Yes - Lambda updated via `aws lambda update-function-code`
**Cache**: Invalidated for user `005dl00000Q6a3RAAR`

---

## Issue Identified (Not Fixed)

### 3. Semantic Search Ranking Problem

**Symptom**: Query "profile the top 10 deals" returns test data (Deal10, Deal11, super Deal) instead of actual high-value deals (Griffin Partners $5.25M, Aarden Equity $4.5M).

**Evidence**:
- Direct search "Griffin Partners deal" → Works (score 0.75)
- Direct search "Aarden Equity deal" → Works (score 0.64)
- Generic query "top 10 deals" → Returns "Deal10", "Deal11" (test data names)
- Generic query "largest deals by gross fee" → Returns low-value deals (~$400K)

**Root Cause**: Pure vector search doesn't understand numerical values
- "$4,500,000" doesn't semantically match "largest" or "highest value"
- Test data with literal names like "Deal10" ranks higher for "top 10 deals"

**Data Verified**:
- 20,474 chunks in S3
- 4,782 Deal chunks
- Real deals ARE indexed (Griffin Partners, Aarden Equity found in S3)
- Real deals ARE accessible (correct owner in sharing buckets)
- Problem is purely search ranking

---

## Architecture Review

Reviewed two architecture documents for alignment:

| Document | Focus | Relevance |
|----------|-------|-----------|
| Master v1.1 | Agent Actions (Create/Update) | Not relevant to search quality |
| **Steel Thread PRD v2.0** | Query Intelligence | **Directly addresses this issue** |

### PRD v2.0 Query Intent Classification (Section F4)

The PRD already plans for this exact scenario:

```
| Intent        | Example                    | Strategy               |
|---------------|----------------------------|------------------------|
| SIMPLE_LOOKUP | "Show ACME account"        | Direct vector search   |
| FIELD_FILTER  | "Opportunities over $1M"   | Filtered vector search |
| AGGREGATION   | "Total pipeline this quarter" | SQL aggregation     |
| RELATIONSHIP  | "Accounts with open cases" | Graph traversal + vector |
```

---

## Recommended Solutions (Priority Order)

### Option 3: Hybrid Search (BM25 + Vector) - RECOMMENDED FIRST
**What**: Combine keyword matching (BM25) with semantic search (vector)

**Why First**:
- Highest ROI - solves multiple problems at once
- BM25 would match "$5,250,000" when searching for high values
- Industry standard for production RAG
- OpenSearch natively supports hybrid search
- Low implementation risk

**Effort**: 2-3 days

### Option 2: Intent Detection + Query Routing - RECOMMENDED SECOND
**What**: Classify query intent, route to optimal retrieval strategy

**Why Second**:
- Handles aggregation queries ("total pipeline value")
- Handles relationship queries ("deals for accounts with cases")
- Foundation for Phase 2 of PRD v2.0
- Requires more implementation effort

**Effort**: 1 week

### Option 1: Metadata Filtering - QUICK FIX IF NEEDED
**What**: Add numeric fields to chunk metadata, filter at query time

**Why Last**:
- Only helps if you know which field to filter
- Doesn't generalize well
- But useful as quick targeted fix

**Effort**: 1-2 days

---

## Investigation Needed (Next Session)

Before implementing Hybrid Search:
1. Check current OpenSearch index configuration
2. Verify if Bedrock KB supports hybrid search natively
3. Determine if OpenSearch Serverless supports hybrid queries
4. Identify configuration changes needed

---

## Key Resources

| Resource | Value |
|----------|-------|
| Lambda Function URL | `https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/` |
| Knowledge Base ID | HOOACWECEX |
| Data Source ID | HWFQ9Q5FOB |
| API Key | M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ |
| Salesforce Org | ascendix-beta-sandbox |
| Test User ID | 005dl00000Q6a3RAAR |

---

## Files Changed This Session

| File | Change |
|------|--------|
| `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.js` | Fixed score Number conversion |
| `lambda/authz/index.py` | Added second data owner to POC whitelist |

---

## Tasks.md Updates Suggested

The current tasks.md doesn't capture the search quality improvement work aligned with PRD v2.0. Suggest adding:

### New Task Block: Phase 2.6 - Search Quality Improvements

```markdown
## Phase 2.6: Search Quality Improvements (⏳ NOT STARTED)

**Context**: Pure vector search has limitations with numerical queries and generic "top N" queries.
**Reference**: Steel Thread PRD v2.0 Section F4 (Query Intent Classification)

- [ ] 39. Implement Hybrid Search (BM25 + Vector)
  - [ ] 39.1 Investigate OpenSearch Serverless hybrid search support
  - [ ] 39.2 Configure BM25 + vector search in OpenSearch index
  - [ ] 39.3 Update Retrieve Lambda to use hybrid search
  - [ ] 39.4 Tune alpha/weights for BM25 vs vector balance
  - [ ] 39.5 Test "top deals by fee" queries return high-value records

- [ ] 40. Implement Basic Intent Detection
  - [ ] 40.1 Create intent classifier for query patterns
  - [ ] 40.2 Detect FIELD_FILTER intent ("over $1M", "largest", "top N by X")
  - [ ] 40.3 Detect AGGREGATION intent ("total", "count", "sum")
  - [ ] 40.4 Route to appropriate retrieval strategy
  - [ ] 40.5 Test intent classification accuracy
```

---

## Test Commands

```bash
# Test query - should return high-value deals after fix
cat > /tmp/test_top_deals.json << 'EOF'
{"query": "Show me the largest deals by gross fee amount", "salesforceUserId": "005dl00000Q6a3RAAR", "filters": {}}
EOF

curl -s -X POST 'https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d @/tmp/test_top_deals.json

# Direct name search - works now
cat > /tmp/test_griffin.json << 'EOF'
{"query": "Griffin Partners deal", "salesforceUserId": "005dl00000Q6a3RAAR", "filters": {}}
EOF

curl -s -X POST 'https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d @/tmp/test_griffin.json
```

---

## Next Session Priorities

1. **Investigate Hybrid Search feasibility** in OpenSearch Serverless / Bedrock KB
2. **Implement Option 3** (Hybrid Search) if supported
3. **Then implement Option 2** (Intent Detection) for aggregation/relationship queries
4. **Clean up test data** from KB if still causing issues

---

## Questions for User

1. Should we delete test data chunks (Deal10, Deal11, etc.) from KB as interim fix?
2. What's the acceptable timeline for implementing hybrid search?
3. Are there specific query patterns we should prioritize for intent detection?
