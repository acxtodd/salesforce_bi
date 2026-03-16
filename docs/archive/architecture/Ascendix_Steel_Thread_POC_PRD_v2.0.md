# PRD — Object-Agnostic Evolution for Steel Thread POC
**Project:** Ascendix Unified AI Search & Agent for Salesforce (AWS-Hosted RAG)
**Version:** 2.0 (Enhanced PRD with Dynamic Configuration)
**Date:** 2025-11-25
**Owner:** Ascendix Technologies

---

## Executive Summary

This PRD extends the original POC requirements to include object-agnostic capabilities, enabling customer self-deployment without code changes. Version 2.0 introduces a phased approach: complete POC with current architecture, then evolve to dynamic configuration for production deployment.

**Key Evolution:**
- **Phase 1 (Current)**: POC with hardcoded CRE objects - Prove value
- **Phase 2 (Next Sprint)**: Dynamic configuration - Enable customer deployment
- **Phase 3 (Next Quarter)**: Graph relationships - Complex queries
- **Phase 4 (Future)**: ML optimization - Intelligent indexing

---

## 1) Background & Strategic Vision

### Current State (POC)
The POC successfully demonstrates AI Search with hardcoded support for:
- Standard Objects: Account, Opportunity, Case, Note
- CRE Objects: ascendix__Property__c, ascendix__Availability__c, ascendix__Lease__c, ascendix__Sale__c, ascendix__Deal__c

### Vision (Production)
**Object-agnostic platform** where customers can:
1. Install the solution
2. Configure which objects to index via UI (no code)
3. System auto-discovers fields and relationships
4. Intelligent routing handles any query type

---

## 2) Enhanced Goals

### POC Goals (Phase 1) - Unchanged
1. **End-to-end value demo**: Natural language Q&A with citations ✓
2. **Security parity**: Enforce sharing/FLS ✓
3. **Cross-entity retrieval**: Multi-object queries (limited) ✓
4. **Private networking**: PrivateLink path ✓
5. **Performance**: <800ms first token, <4s end-to-end

### Production Goals (Phase 2-4) - New
6. **Object Agnostic**: Support ANY Salesforce object without code changes
7. **Admin Configurable**: UI-based configuration for non-technical admins
8. **Relationship Aware**: Automatic discovery and traversal of relationships
9. **Query Intelligence**: Route queries to optimal retrieval strategy
10. **Self-Service**: Customers deploy and configure independently

---

## 3) Functional Requirements - Enhanced

### F1. Dynamic Object Discovery (New)

#### F1.1 Schema Discovery Service
- **Auto-Discovery**: Query Salesforce Describe API for any object
- **Field Classification**: Automatically categorize fields by type
- **Relationship Mapping**: Discover lookups and master-detail relationships
- **Caching**: 24-hour cache with on-demand refresh

#### F1.2 Intelligent Field Selection
```python
Field Priority Algorithm:
1. Required fields (non-nullable)
2. Name-like fields (Name, Title, Subject)
3. Frequently queried fields (based on usage)
4. Long text fields (descriptions, notes)
5. Key business fields (Amount, Status, Stage)
```

### F2. Admin Configuration Interface (New)

#### F2.1 Custom Metadata Type
```
IndexConfiguration__mdt
├── Object_API_Name__c (Text)
├── Enabled__c (Checkbox)
├── Auto_Discover_Fields__c (Checkbox)
├── Text_Fields__c (TextArea) - Optional override
├── Relationship_Depth__c (Number) - 1-3 levels
├── Graph_Enabled__c (Checkbox) - Enable graph sync
└── Priority__c (Number) - Processing order
```

#### F2.2 Configuration UI (LWC)
- **Object Browser**: List all objects with search
- **Field Selector**: Multi-select fields to index
- **Preview**: Show sample chunks before saving
- **Test Query**: Run test searches immediately
- **Bulk Actions**: Enable/disable multiple objects

### F3. Relationship Graph (New)

#### F3.1 Graph Data Model
```
Node: {
  id: "RecordId",
  type: "ObjectType",
  data: {extracted_fields},
  depth: 0-3
}

Edge: {
  from: "ParentId",
  to: "ChildId",
  type: "RelationshipName",
  direction: "parent|child"
}
```

#### F3.2 Multi-Hop Queries
Support queries like:
- "Show properties with available space where the property manager has open cases"
- "Find accounts with opportunities closing next month that have unresolved support tickets"
- "List deals for properties in Dallas with leases expiring soon"

### F4. Query Intent Classification (New)

#### F4.1 Intent Types
| Intent | Example | Strategy |
|--------|---------|----------|
| SIMPLE_LOOKUP | "Show ACME account" | Direct vector search |
| FIELD_FILTER | "Opportunities over $1M" | Filtered vector search |
| RELATIONSHIP | "Accounts with open cases" | Graph traversal + vector |
| AGGREGATION | "Total pipeline this quarter" | SQL aggregation |
| COMPLEX | "Properties with expiring leases and maintenance issues" | Hybrid graph + vector |

#### F4.2 Routing Logic
```python
def route_query(query: str) -> Strategy:
    if has_aggregation_terms(query):
        return SQL_STRATEGY
    elif has_relationship_terms(query):
        return GRAPH_STRATEGY
    elif has_numeric_filters(query):
        return FILTERED_VECTOR_STRATEGY
    else:
        return VECTOR_STRATEGY
```

---

## 4) Technical Architecture - Enhanced

### Current Architecture (Phase 1)
```
Salesforce → CDC/Batch → Hardcoded Chunking → OpenSearch → Retrieval
```

### Enhanced Architecture (Phase 2-3)
```
Salesforce → CDC/Batch → Dynamic Discovery → Smart Chunking → Dual Store → Intelligent Routing
                              ↓                      ↓              ↓
                     Schema Service          Config Cache    OpenSearch + Graph
```

### Component Evolution

#### Chunking Lambda Evolution
```python
# Phase 1 (Current)
def chunk_record(record, sobject):
    config = POC_OBJECT_FIELDS[sobject]  # Hardcoded
    return process_with_config(record, config)

# Phase 2 (Dynamic)
def chunk_record(record, sobject):
    config = get_dynamic_config(sobject)  # Runtime discovery
    if not config:
        config = auto_discover(sobject)
    return process_with_config(record, config)

# Phase 3 (Graph-Aware)
def chunk_record(record, sobject):
    config = get_dynamic_config(sobject)
    graph = build_relationship_graph(record, config)
    chunks = process_with_config(record, config)
    enrich_with_graph(chunks, graph)
    return chunks
```

#### Retrieval Lambda Evolution
```python
# Phase 1 (Current)
def retrieve(query, filters):
    return vector_search(query, filters)

# Phase 2 (Intent-Aware)
def retrieve(query, filters):
    intent = classify_intent(query)
    if intent == "RELATIONSHIP":
        return graph_retrieve(query, filters)
    return vector_search(query, filters)

# Phase 3 (Hybrid)
def retrieve(query, filters):
    intent = classify_intent(query)
    strategies = get_strategies_for_intent(intent)
    results = []
    for strategy in strategies:
        results.extend(strategy.execute(query, filters))
    return merge_and_rank(results)
```

---

## 5) Implementation Phases

### Phase 1: POC Completion (Current - 1 week)
**Goal**: Prove value with hardcoded CRE objects

**Tasks**:
- [x] Deploy CRE object support
- [ ] Run batch exports for test data
- [ ] Execute acceptance tests
- [ ] Achieve 70% precision@5
- [ ] Document results

**Success Criteria**:
- Works for configured CRE objects
- Meets performance targets
- Passes security tests

### Phase 2: Dynamic Configuration (Weeks 2-4)
**Goal**: Enable object-agnostic deployment

**Tasks**:
- [ ] Implement Schema Discovery Service
- [ ] Create IndexConfiguration__mdt
- [ ] Build Configuration UI (LWC)
- [ ] Update Chunking Lambda
- [ ] Add configuration caching
- [ ] Test with 10+ different objects

**Deliverables**:
- Schema Discovery Lambda
- Configuration Management UI
- Dynamic Chunking Pipeline
- Admin Documentation

**Success Criteria**:
- Admin can configure new object in <5 minutes
- No code changes required
- Performance within 20% of hardcoded

### Phase 3: Graph Enhancement (Weeks 5-8)
**Goal**: Support complex relationship queries

**Tasks**:
- [ ] Deploy graph database (Neptune or DynamoDB)
- [ ] Implement Graph Builder
- [ ] Add Query Intent Classifier
- [ ] Create Graph-Aware Retriever
- [ ] Build relationship traversal logic
- [ ] Test multi-hop queries

**Deliverables**:
- Graph synchronization pipeline
- Intent classification service
- Enhanced retrieval strategies
- Query routing engine

**Success Criteria**:
- 3-hop relationship queries work
- Graph queries faster than nested vector searches
- 80% intent classification accuracy

### Phase 4: Intelligence Layer (Future)
**Goal**: Self-optimizing system

**Features**:
- ML-based field importance ranking
- Automatic chunking strategy selection
- Query pattern learning
- Cross-tenant optimization
- Predictive caching

---

## 6) Success Metrics - Enhanced

### POC Metrics (Phase 1)
- Retrieval precision@5 ≥ 70% ✓
- P95 first token ≤ 800ms
- P95 end-to-end ≤ 4.0s
- Zero security leaks
- CDC freshness ≤ 5 min

### Production Metrics (Phase 2-3)
- **Configuration Time**: <5 min per object
- **Auto-Discovery Success**: >90% of objects
- **Query Routing Accuracy**: >85%
- **Relationship Query Performance**: <2s for 2-hop
- **Admin Satisfaction**: >4/5 rating

### Scalability Metrics
| Metric | POC | Phase 2 | Phase 3 | Production |
|--------|-----|---------|---------|------------|
| Objects Supported | 7 | 50+ | 100+ | Unlimited |
| Manual Config | 100% | 20% | 10% | 0% |
| Query Types | 2 | 4 | 6 | All |
| Relationship Depth | 1 | 2 | 3+ | Unlimited |
| Performance Impact | Baseline | +20% | +10% | Optimized |

---

## 7) Risk Analysis - Enhanced

### Technical Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Schema discovery performance | High | Medium | Aggressive caching, async discovery |
| Graph database complexity | High | Low | Start with DynamoDB, migrate to Neptune |
| Query misclassification | Medium | Medium | Fallback strategies, user feedback |
| Configuration errors | Medium | High | Validation, preview, rollback |
| Performance degradation | High | Medium | Monitoring, circuit breakers |

### Business Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Customer deployment complexity | High | Medium | Detailed docs, video tutorials |
| Feature creep | Medium | High | Strict phase gates |
| Adoption challenges | Medium | Medium | Admin training, templates |

---

## 8) Test Plan - Enhanced

### Phase 1 Testing (POC)
- Unit tests for hardcoded objects ✓
- Integration tests for pipeline ✓
- E2E tests for CRE queries
- Performance benchmarks
- Security validation

### Phase 2 Testing (Dynamic Config)
- Schema discovery for 20+ objects
- Configuration UI usability testing
- Performance comparison (dynamic vs hardcoded)
- Cache effectiveness testing
- Error handling validation

### Phase 3 Testing (Graph)
- Multi-hop query accuracy
- Graph build performance
- Intent classification accuracy
- Hybrid retrieval effectiveness
- Scale testing (1M+ nodes)

### Test Objects for Validation

#### Standard Objects
- Account, Contact, Opportunity, Case, Lead

#### Custom Objects (Examples)
- Property__c, Lease__c (Real Estate)
- Project__c, Milestone__c (Project Management)
- Invoice__c, Payment__c (Billing)
- Equipment__c, Maintenance__c (Asset Management)

#### Complex Relationships
- Account → Opportunities → Products
- Property → Leases → Tenants → Cases
- Project → Milestones → Tasks → Assignees

---

## 9) Migration Path

### From POC to Production

#### Step 1: Complete POC (Week 1)
```
Current State → Validate Value → Document Results
```

#### Step 2: Add Dynamic Layer (Weeks 2-3)
```
Hardcoded + Dynamic Fallback → Test → Validate
```

#### Step 3: Enable Auto-Discovery (Week 4)
```
Dynamic Primary + Hardcoded Fallback → Test → Validate
```

#### Step 4: Add Graph Layer (Weeks 5-8)
```
Vector + Graph Hybrid → Test → Optimize
```

### Rollback Plan
Each phase maintains backward compatibility:
- Phase 2 falls back to hardcoded configs
- Phase 3 falls back to vector-only search
- Configuration changes are versioned and reversible

---

## 10) Acceptance Criteria - Final

### POC Exit Criteria (Phase 1)
- [ ] CRE objects indexed and searchable
- [ ] 22 test queries return accurate results
- [ ] Performance targets met
- [ ] Security tests passed
- [ ] Documentation complete

### Production Ready Criteria (Phase 2-3)
- [ ] Any Salesforce object configurable via UI
- [ ] Auto-discovery works for 90% of objects
- [ ] Relationship queries accurate
- [ ] Admin can deploy without engineering
- [ ] Performance acceptable for all query types

### Customer Success Criteria
- [ ] Install solution in <1 hour
- [ ] Configure first object in <5 minutes
- [ ] Run first query successfully
- [ ] No code changes required
- [ ] Results are accurate and useful

---

## Appendices

### Appendix A: Configuration Templates

#### Simple Object
```json
{
  "objectName": "Contact",
  "autoDiscover": true
}
```

#### Complex Object
```json
{
  "objectName": "CustomDeal__c",
  "autoDiscover": false,
  "fields": {
    "text": ["Name", "Status__c"],
    "longText": ["Description__c"],
    "relationships": ["Account__c", "Property__c"],
    "numeric": ["Amount__c"],
    "date": ["CloseDate__c"]
  },
  "relationshipDepth": 2,
  "graphEnabled": true
}
```

### Appendix B: Query Examples by Phase

#### Phase 1 (Hardcoded)
- "Show properties in Dallas"
- "Find leases expiring next month"
- "List open deals over $1M"

#### Phase 2 (Dynamic)
- "Show all CustomObject__c records modified today"
- "Find AnyObject__c where Status = 'Active'"
- "Search NewObject__c with keyword 'urgent'"

#### Phase 3 (Graph)
- "Properties with available space where property manager has open tasks"
- "Accounts with opportunities that have unresolved cases"
- "Deals connected to properties with expiring leases"

### Appendix C: Performance Benchmarks

| Operation | Phase 1 | Phase 2 | Phase 3 | Target |
|-----------|---------|---------|---------|--------|
| Schema Discovery | N/A | 200ms | 150ms (cached) | <200ms |
| Config Load | 5ms | 50ms | 30ms (cached) | <50ms |
| Chunking/Record | 100ms | 120ms | 150ms | <200ms |
| Simple Query | 200ms | 250ms | 200ms | <300ms |
| Relationship Query | N/A | 500ms | 300ms | <500ms |
| Graph Build | N/A | N/A | 100ms/node | <2s total |

### Appendix D: Decision Log

| Decision | Date | Rationale |
|----------|------|-----------|
| Use Custom Metadata for config | 2025-11-25 | Deployable, versionable, admin-friendly |
| DynamoDB before Neptune | 2025-11-25 | Simpler, cheaper for POC scale |
| Auto-discovery default on | 2025-11-25 | Better UX, admin can override |
| 3-level relationship max | 2025-11-25 | Balance complexity vs performance |
| Cache schema 24 hours | 2025-11-25 | Balance freshness vs API limits |

---

## References
- Original POC PRD v0.9
- Master Architecture v1.1
- Phase 4 Graph-RAG PRD
- Salesforce Metadata API Documentation
- AWS Best Practices for Serverless