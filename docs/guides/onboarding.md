# Agent Onboarding Guide

Welcome! This guide will help you understand the Salesforce AI Search project structure, architecture, and how to work effectively on this codebase.

## Read This First (15–20 min)

Start with `docs/guides/PROJECT_PRIMER.md` for a consolidated overview of the system, current state, key flows, and load‑bearing requirements.  
Then return here for detailed repo orientation and debugging playbooks.

## Project Overview

This is a **Graph-Enhanced RAG (Retrieval-Augmented Generation) system** for Commercial Real Estate (CRE) that:
- Translates natural language queries into structured filters
- Uses graph traversal for cross-object queries (e.g., "available space in Class A office buildings")
- Enforces Salesforce sharing rules and field-level security
- Returns precise, authorized results without per-query hard-coding

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SALESFORCE                                      │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │ Batch Export    │    │ CDC Events      │    │ Schema Describe │         │
│  │ (Apex)          │    │ (Platform Events)│    │ API             │         │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘         │
└───────────┼──────────────────────┼──────────────────────┼───────────────────┘
            │                      │                      │
            ▼                      ▼                      ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                                 AWS                                            │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │                    INGESTION PIPELINE (Step Functions)                    │ │
│  │  CDC Processor → Validate → Transform → Chunk → Graph Builder → Enrich   │ │
│  │                                             │           │                 │ │
│  │                                             ▼           ▼                 │ │
│  │                                       Graph Nodes   Embed → Sync          │ │
│  │                                       Graph Edges        │                │ │
│  │                                             │            ▼                │ │
│  │                                             │      Bedrock KB             │ │
│  └─────────────────────────────────────────────┼────────────┼────────────────┘ │
│                                                │            │                  │
│  ┌─────────────────────────────────────────────┼────────────┼────────────────┐ │
│  │                    QUERY PATH                │            │                │ │
│  │                                              ▼            ▼                │ │
│  │  Query → Planner → Schema Decomposer → Graph Filter → KB Search → Answer  │ │
│  │              │                              │                              │ │
│  │              ▼                              ▼                              │ │
│  │        Schema Cache ◄──────────────── Vocab Cache                         │ │
│  │              │                                                             │ │
│  │              └──── Schema Discovery (nightly) ◄─── Salesforce Describe    │ │
│  └────────────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────┘
```

## Critical Architectural Principle: Single Source of Truth

**The Schema Cache must be the single source of truth for both query decomposition AND data export.**

```
CORRECT:
  Schema Discovery → Schema Cache → Planner (expects field X)
                          │
                          └──→ Batch Export (includes field X)
                                    │
                                    └──→ Graph Builder (stores field X)

INCORRECT (causes bugs):
  Schema Discovery → Schema Cache → Planner (expects field X)

  IndexConfiguration__mdt → Batch Export (missing field X) ← DISCONNECTED!
                                  │
                                  └──→ Graph Builder (missing field X)
```

When these systems are disconnected, queries fail because the Planner expects fields that were never exported.

## Project Structure

```
salesforce-ai-search/
├── .kiro/
│   └── specs/
│       ├── salesforce-ai-search-poc/          # Original POC spec
│       └── graph-aware-zero-config-retrieval/ # Current phase spec
│           ├── requirements.md    # Feature requirements with user stories
│           ├── design.md          # Architecture and design decisions
│           └── tasks.md           # Implementation task list
├── bin/
│   └── app.ts                     # CDK app entry point
├── lib/
│   ├── network-stack.ts           # VPC, security groups, PrivateLink
│   ├── data-stack.ts              # DynamoDB tables, S3, KMS
│   ├── ingestion-stack.ts         # Lambda functions, Step Functions
│   ├── search-stack.ts            # Bedrock KB, OpenSearch Serverless
│   └── api-stack.ts               # API Gateway, Lambda URLs
├── lambda/
│   ├── retrieve/                  # Query processing Lambda
│   │   ├── index.py               # Main handler
│   │   ├── planner.py             # Query planner
│   │   ├── schema_decomposer.py   # NL → structured filters
│   │   ├── graph_filter.py        # Graph node filtering
│   │   └── entity_linker.py       # Term → SF object mapping
│   ├── answer/                    # Answer generation Lambda
│   ├── graph_builder/             # Graph node/edge creation
│   ├── schema_discovery/          # Schema auto-discovery
│   ├── derived_views/             # Materialized view maintenance
│   ├── cdc_processor/             # CDC event processing
│   ├── validate/                  # Record validation
│   ├── transform/                 # Record transformation
│   ├── chunking/                  # Text chunking
│   ├── enrich/                    # Metadata enrichment
│   ├── embed/                     # Embedding generation
│   └── sync/                      # S3/KB sync
├── salesforce/
│   ├── classes/                   # Apex classes
│   │   ├── AISearchBatchExport.cls       # Batch export job
│   │   └── AISearchCDCHandler.cls        # CDC event handler
│   ├── customMetadata/            # Custom metadata types
│   │   └── IndexConfiguration.*.xml      # Object export configuration
│   ├── namedCredentials/          # AWS API credentials
│   └── remoteSiteSettings/        # Callout allowlist
├── docs/
│   ├── guides/                    # How-to guides
│   └── handoffs/                  # Session handoff documents
└── test_automation/               # Acceptance test scripts
```

## Key Data Stores

### DynamoDB Tables

| Table | Purpose | Key Schema |
|-------|---------|------------|
| `salesforce-ai-search-schema-cache` | Auto-discovered schema metadata | PK: `objectApiName` |
| `salesforce-ai-search-vocab-cache` | Term → field/value mappings | PK: `vocab_type#object`, SK: `term` |
| `salesforce-ai-search-graph-nodes` | Entity nodes with attributes | PK: `nodeId`, GSI: `type-createdAt` |
| `salesforce-ai-search-graph-edges` | Relationships between entities | PK: `sourceId`, SK: `targetId` |
| `salesforce-ai-search-availability-view` | Availability rollups | PK: `property_id`, SK: `availability_id` |
| `salesforce-ai-search-vacancy-view` | Vacancy percentages | PK: `property_id` |
| `salesforce-ai-search-authz-cache` | User authorization tags | PK: `userId` |

### Bedrock Knowledge Base

- **KB ID**: Check `KNOWLEDGE_BASE_ID` env var in Retrieve Lambda
- Contains chunked, embedded text with metadata
- Metadata includes: `sobject`, `recordId`, `sharingBuckets`, filterable fields

## The Query Flow

Understanding the query flow is essential for debugging:

```
1. User Query: "show class a office properties in plano"
        │
        ▼
2. Intent Classification: FIELD_FILTER (confidence: 0.85)
        │
        ▼
3. Schema Decomposition:
   {
     entity: "ascendix__Property__c",
     filters: {
       "ascendix__PropertyClass__c": "A",
       "RecordType": "Office",           ← Must exist in graph nodes!
       "ascendix__City__c": "Plano"
     }
   }
        │
        ▼
4. Graph Filter: Query DynamoDB graph-nodes for matching records
        │
        ├── If matches found: Use as seed IDs for KB search
        │
        └── If 0 matches: SHORT-CIRCUIT (return empty) ← Common failure point!
        │
        ▼
5. KB Search: Vector + metadata filter search
        │
        ▼
6. Authorization: Filter by user's sharing buckets
        │
        ▼
7. Answer Generation: LLM generates response from retrieved chunks
```

## Common Debugging Scenarios

### Scenario: "I don't have enough information" for valid queries

**Symptoms:**
- Query returns no results
- Bedrock KB has the data (verified via direct KB query)
- Graph filter short-circuits

**Root Cause Investigation:**
```bash
# 1. Check Retrieve Lambda logs for the query
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 10m --format short

# Look for: "Graph filter: 0 candidates" or "graphFilterShortCircuit: true"

# 2. Check what filters the decomposer produced
# Look for: "Schema decomposition: entity=..., filters={...}"

# 3. Check if filter fields exist in graph nodes
aws dynamodb scan \
  --table-name salesforce-ai-search-graph-nodes \
  --filter-expression "#t = :type" \
  --expression-attribute-names '{"#t":"type"}' \
  --expression-attribute-values '{":type":{"S":"ascendix__Property__c"}}' \
  --projection-expression "nodeId, attributes" \
  --max-items 5

# 4. If attributes are missing, check IndexConfiguration
sf data query --query "SELECT Object_API_Name__c, Text_Fields__c, Graph_Node_Attributes__c FROM IndexConfiguration__mdt WHERE Object_API_Name__c = 'ascendix__Property__c'" --target-org <org-alias>
```

**Common Causes:**
1. **Filter field not in IndexConfiguration** → Add to `Text_Fields__c` and `Graph_Node_Attributes__c`
2. **RecordType not included** → Add `RecordType.Name` to configuration
3. **Data not re-exported** → Trigger batch export after config change

### Scenario: Graph nodes exist but missing attributes

**Check attribute coverage:**
```bash
aws dynamodb scan \
  --table-name salesforce-ai-search-graph-nodes \
  --filter-expression "#t = :type" \
  --expression-attribute-names '{"#t":"type"}' \
  --expression-attribute-values '{":type":{"S":"ascendix__Property__c"}}' \
  --select COUNT

# Then sample records to see what attributes they have
```

**Root Cause:** The batch export SOQL query didn't include the field because it wasn't in IndexConfiguration.

### Scenario: Verifying Bedrock KB has data

```bash
# Create query file
echo '{"text": "Class A office Plano"}' > /tmp/kb_query.json

# Query Bedrock KB directly
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id <KB_ID> \
  --retrieval-query file:///tmp/kb_query.json \
  --region us-west-2
```

## Task Execution Workflow

### Before Starting ANY Task

**CRITICAL**: Always read these files first:
1. `.kiro/specs/graph-aware-zero-config-retrieval/requirements.md`
2. `.kiro/specs/graph-aware-zero-config-retrieval/design.md`
3. `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md`
4. Latest handoff in `docs/handoffs/` (sorted by date)

### Task Execution Steps

1. **Read Context Documents** - Never skip this
2. **Identify the Task** - Check for sub-tasks and dependencies
3. **Focus on ONE Task** - Don't implement beyond scope
4. **Verify Against Requirements** - Cross-reference acceptance criteria
5. **Test the Change** - Run relevant tests
6. **Update Task Status** - Mark as completed
7. **Stop and Wait** - Let user review before continuing

## Key Concepts

### Authorization Model

- **Sharing Buckets**: Computed tags representing Salesforce sharing rule membership
- **FLS Profile Tags**: Field-level security tags for user profiles
- **AuthZ Mode**: `strict` (all filters enforced) vs `relaxed` (partial match allowed)

### Data Pipeline (Step Functions)

```
CDC Processor → Validate → Transform → Chunk → Graph Builder → Enrich → Embed → Sync
                                                    │
                                                    ▼
                                              Graph Nodes/Edges
```

### Supported Objects

- **Standard**: Account, Opportunity, Case, Note, Task, Event
- **Custom**: ascendix__Property__c, ascendix__Lease__c, ascendix__Availability__c

### RecordType Handling

RecordType is a **standard Salesforce relationship** requiring special SOQL syntax:
- Use `RecordType.Name` (not `RecordType` or `RecordTypeId`) for the display name
- Must be explicitly included in IndexConfiguration `Text_Fields__c`

## Performance Targets

| Metric | Target | Notes |
|--------|--------|-------|
| Planner latency | ≤500ms p95 | Hard cutoff with fallback |
| Retrieve latency (simple) | ≤1500ms p95 | Single-object queries |
| Retrieve latency (complex) | ≤5000ms p95 | Cross-object graph traversal |
| First token latency | ≤2000ms p95 | Model-dependent |
| Empty result rate | <8% | For valid queries |
| Precision@5 | ≥75% | Top 5 results relevance |

## Security Considerations

- All data encrypted at rest (KMS)
- API Gateway requires API key authentication
- Named Credentials for Salesforce → AWS callouts
- Graph traversal enforces authorization at each hop
- No public S3 buckets or unauthenticated endpoints

## Common Pitfalls to Avoid

### 1. Disconnected Schema Discovery and Data Export

**Wrong:** Manually maintaining IndexConfiguration separately from Schema Discovery
**Right:** Schema Cache should drive both query decomposition AND data export

### 2. Missing RecordType in Export

**Wrong:** Assuming RecordType will be included automatically
**Right:** Explicitly add `RecordType.Name` to IndexConfiguration for objects with RecordTypes

### 2a. Bypassing TemporalParser

**Wrong:** Adding ad-hoc date/tense parsing in handlers
**Right:** Use `lambda/retrieve/temporal_parser.py` (with `ValueNormalizer`) so all date ranges share one source of truth

### 3. Testing Against Empty Graph

**Wrong:** Assuming graph has data without verification
**Right:** Always verify graph node count and attribute coverage before debugging query issues

### 4. Ignoring Short-Circuit Behavior

**Wrong:** Assuming KB is always queried
**Right:** Graph filter returning 0 results short-circuits the entire query path

### 5. Hardcoding Field Names

**Wrong:** Hardcoding field names in decomposer hints that don't match actual fields
**Right:** Use Schema Cache as source of truth for valid field names

### 6. Dropping Additional_Fields__c in Export Paths

**Wrong:** Adding extra fields only when Schema Cache is available
**Right:** Always merge `Additional_Fields__c` regardless of override/fallback so exports and Schema Cache stay aligned

## Useful Commands

### Check Lambda Logs
```bash
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --since 10m --format short
aws logs tail /aws/lambda/salesforce-ai-search-answer --since 10m --format short
aws logs tail /aws/lambda/salesforce-ai-search-graph-builder --since 1d --format short
```

### Check DynamoDB Table Counts
```bash
aws dynamodb scan --table-name salesforce-ai-search-graph-nodes --select COUNT
aws dynamodb scan --table-name salesforce-ai-search-graph-edges --select COUNT
```

### Test Query Directly
```bash
cat > /tmp/test_query.json << 'EOF'
{"query": "show class a office properties in plano", "salesforceUserId": "<USER_ID>"}
EOF

curl -s -X POST "https://<LAMBDA_URL>/answer" \
  -H "Content-Type: application/json" \
  -H "x-api-key: <API_KEY>" \
  -d @/tmp/test_query.json
```

### Deploy Salesforce Metadata
```bash
sf project deploy start --source-dir salesforce/customMetadata --target-org <org-alias>
```

### Deploy Lambda Changes
```bash
cd lambda/<function>
zip -r function.zip .
aws lambda update-function-code --function-name salesforce-ai-search-<function> --zip-file fileb://function.zip
```

## Getting Help

1. **Check handoffs** in `docs/handoffs/` for recent context
2. **Check the design doc** for architectural decisions
3. **Check requirements** to understand the "why"
4. **Search existing code** for similar patterns
5. **Check CloudWatch logs** for runtime behavior

## Where to Find Current State (avoid stale configs)

- **Sprint tasks, flags, timeouts:** `.kiro/specs/graph-aware-zero-config-retrieval/tasks.md`
- **Latest fixes/hotspots:** `docs/handoffs/` (read the newest first)
- **Ops / rollback procedures:** `docs/runbooks/RUNBOOK-CANARY-OPERATIONS.md`
- **Secrets (API keys/URLs):** retrieve from Secrets Manager or env vars; never hardcode in code or docs.

## Before You Code (quick checklist)

1. Read onboarding → requirements → design → tasks → latest handoff.
2. Pull endpoints/keys from Secrets Manager; avoid pasting secrets.
3. Reuse existing components:
   - `TemporalParser` / `ValueNormalizer` for all date/range logic
   - `DerivedViewManager` for aggregation (availability, vacancy, leases, activities, sales)
   - `SchemaCacheClient` for export field lists; `VocabCache` / `EntityLinker` for term binding
4. Build field lists from Schema Cache (or Schema API), not from manual guesses.
5. For derived/aggregation queries, try derived views first, then KB fallback.
6. Follow best practices as documented in .kiro/steering

## Remember

- **Data flow matters**: Schema Discovery → Schema Cache → Both Planner AND Export
- **Verify assumptions**: Always check that graph/KB has the data you expect
- **One task at a time**: Don't jump ahead or over-engineer
- **Context is everything**: Read specs and handoffs before coding
- **Test the actual system**: Don't trust code alone, verify in AWS
