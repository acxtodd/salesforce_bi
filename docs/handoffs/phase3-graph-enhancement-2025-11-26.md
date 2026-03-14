# Phase 3 Graph Enhancement - Handoff Document

**Date**: 2025-11-26
**Status**: Tasks 1-5 Complete, Tasks 6-15 Remaining

---

## Summary

Phase 3 adds graph-based relationship traversal to the Salesforce AI Search system, enabling complex multi-hop queries like "tenants of properties owned by Acme Corp".

---

## Completed Work

### Task 1-4: Graph Building Infrastructure (Complete)

**DynamoDB Tables Created**:
- `salesforce-ai-search-graph-nodes` - Stores graph nodes (records)
- `salesforce-ai-search-graph-edges` - Stores relationships between nodes
- `salesforce-ai-search-graph-path-cache` - Caches traversal results (TTL enabled)
- `salesforce-ai-search-intent-classification-log` - Logs query intent classifications (TTL enabled)

**Graph Builder Lambda** (`lambda/graph_builder/index.py`):
- Builds graph from Salesforce records during ingestion
- Supports CREATE, UPDATE, DELETE operations
- Depth-limited traversal (1-3 hops)
- Configuration-driven field filtering
- Integrated into Step Functions workflow (after chunking step)

**Property Tests** (`lambda/graph_builder/test_graph_builder.py`):
- Property 1: Graph Traversal Depth Limit
- Property 2: Node Structure Completeness
- Property 3: Edge Structure Completeness
- Property 9: Relationship Field Filtering
- Property 11: Graph CRUD Consistency

### Task 5: Query Intent Router (Complete)

**Intent Router Module** (`lambda/retrieve/intent_router.py`):
- `QueryIntentRouter` class with pattern-based classification
- Five intent types:
  - `SIMPLE_LOOKUP` - Basic "find X" queries
  - `FIELD_FILTER` - Queries with explicit constraints
  - `RELATIONSHIP` - Multi-hop relationship queries
  - `AGGREGATION` - Count, sum, average, top N queries
  - `COMPLEX` - Hybrid queries requiring multiple strategies

**Pattern Definitions**:
- `RELATIONSHIP_PATTERNS` - 14 patterns for detecting relationship queries
- `AGGREGATION_PATTERNS` - 13 patterns for count/sum/avg/top N
- `FIELD_FILTER_PATTERNS` - 12 patterns for filter detection
- `SIMPLE_LOOKUP_PATTERNS` - 4 patterns for basic lookups

**Integration with Retrieve Lambda** (`lambda/retrieve/index.py`):
- Classifies queries before retrieval
- Logs classifications to DynamoDB
- Adds intent info to query plan and trace
- Feature flags for controlling behavior:
  - `INTENT_ROUTING_ENABLED=true` (default)
  - `GRAPH_ROUTING_ENABLED=false` (until Task 6 complete)
  - `INTENT_LOGGING_ENABLED=true` (default)

**Property Tests** (`lambda/retrieve/test_intent_router.py`):
- 42 tests passing
- Property 4: Intent Classification Validity
- Property 5: Relationship Pattern Detection
- Property 6: Aggregation Pattern Detection

---

## Remaining Work

### Task 6: Implement Graph-Aware Retriever (Next Priority)

Create `lambda/retrieve/graph_retriever.py`:
- [ ] 6.1 Create Graph Retriever module with DynamoDB client
- [ ] 6.2 Implement entity extraction from query
- [ ] 6.3 Implement graph traversal (1-3 hops)
- [ ] 6.4 Implement authorization at each hop
- [ ] 6.5 Write Property 7: Secure Graph Traversal test
- [ ] 6.6 Implement result merging and ranking
- [ ] 6.7 Write Property 10: Filter + Relationship Consistency test
- [ ] 6.8 Implement path caching (5-min TTL)
- [ ] 6.9 Write Property 13: Path Cache Consistency test
- [ ] 6.10 Write Property 12: Cache Invalidation test

### Task 7: Checkpoint - Verify Graph Retrieval

Test single-hop, multi-hop, authorization filtering, and cache behavior.

### Task 8: Implement Graph Configuration Support

- [ ] 8.1 Update IndexConfiguration__mdt schema (Graph_Enabled__c, Relationship_Depth__c, etc.)
- [ ] 8.2 Deploy updated metadata type to Salesforce
- [ ] 8.3 Create default configurations for CRE objects
- [ ] 8.4 Write Property 8: Graph Enablement Configuration test
- [ ] 8.5 Implement configuration caching in Graph Builder

### Task 9: Implement Monitoring and Observability

- [ ] 9.1 Add CloudWatch metrics for graph operations
- [ ] 9.2 Add CloudWatch metrics for intent classification
- [ ] 9.3 Create CloudWatch alarms
- [ ] 9.4 Create Graph Operations dashboard
- [ ] 9.5 Update monitoring stack CDK

### Task 10: Implement Error Handling and Fallback

- [ ] 10.1 Implement circuit breaker for graph operations
- [ ] 10.2 Implement graceful degradation
- [ ] 10.3 Add error logging and alerting

### Task 11: Checkpoint - Verify Monitoring

Verify metrics, alarms, dashboard, and circuit breaker behavior.

### Task 12: Update UI for Relationship Results

- [ ] 12.1 Update LWC to display relationship paths
- [ ] 12.2 Add navigation for relationship paths
- [ ] 12.3 Update answer generation to include relationship context
- [ ] 12.4 Deploy updated LWC to Salesforce

### Task 13: Re-index Data with Graph Building

- [ ] 13.1 Enable graph building for CRE objects
- [ ] 13.2 Trigger batch re-export for all CRE objects
- [ ] 13.3 Verify graph data quality

### Task 14: Run Acceptance Tests

- [ ] 14.1 Create relationship query test set
- [ ] 14.2 Run full acceptance test suite (target: 85%+)
- [ ] 14.3 Measure performance against targets
- [ ] 14.4 Conduct security testing
- [ ] 14.5 Document results and gaps

### Task 15: Final Checkpoint

Verify overall acceptance rate >= 85%, relationship query accuracy >= 80%, performance targets met, zero security leaks.

---

## Key Files

| File | Description |
|------|-------------|
| `lambda/graph_builder/index.py` | Graph Builder Lambda |
| `lambda/graph_builder/test_graph_builder.py` | Graph Builder tests |
| `lambda/retrieve/intent_router.py` | Query Intent Router |
| `lambda/retrieve/test_intent_router.py` | Intent Router tests (42 passing) |
| `lambda/retrieve/index.py` | Retrieve Lambda (with Intent Router integration) |
| `lib/data-stack.ts` | DynamoDB table definitions |
| `lib/ingestion-stack.ts` | Graph Builder Lambda + Step Functions |
| `.kiro/specs/phase3-graph-enhancement/tasks.md` | Full task list |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INTENT_ROUTING_ENABLED` | `true` | Enable query intent classification |
| `GRAPH_ROUTING_ENABLED` | `false` | Enable graph-aware retrieval (enable after Task 6) |
| `INTENT_LOGGING_ENABLED` | `true` | Log classifications to DynamoDB |
| `INTENT_CLASSIFICATION_LOG_TABLE` | `salesforce-ai-search-intent-classification-log` | DynamoDB table name |

---

## Next Steps

1. **Start Task 6**: Create `lambda/retrieve/graph_retriever.py` with `GraphAwareRetriever` class
2. Implement DynamoDB queries for graph traversal
3. Add authorization checks at each hop
4. Merge graph results with vector search results
5. Enable `GRAPH_ROUTING_ENABLED=true` once Task 6 is complete
