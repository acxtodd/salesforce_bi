# Salesforce AI Search Architecture (Graph-Enhanced RAG)
**As of:** 2025-12-10
**Author:** QA Lead
**Source of Truth:** Live deployment and code (Lambda, CDK, Apex), not legacy docs.

---

## Executive Summary

### What This Is

This is an AI-powered search interface for Salesforce CRE data. Users type natural language questions instead of building structured queries, and the system figures out the appropriate filters, traverses object relationships, and returns relevant records with citations.

It augments the traditional query-builder approach—where users select objects, pick fields, set filter values, and configure joins—with a conversational interface. Instead of knowing that "Class A office in Plano" means `RecordType.Name = 'Office'` AND `PropertyClass__c = 'A'` AND `City__c = 'Plano'`, users just ask the question.

### How It Works

The system has three main components:

1. **Schema-Aware Query Planning** — On a nightly schedule, the system calls Salesforce's Describe API to learn your org's schema: which fields exist, what picklist values are valid, which record types are defined, and how objects relate to each other. When a query comes in, this metadata helps translate natural language into structured filters.

2. **Knowledge Graph** — CRE data is relational. Properties have availabilities. Availabilities connect to leases. Leases have tenants. The graph stores these relationships in DynamoDB, enabling cross-object queries. Ask for "availabilities at Class A office properties in Plano" and the system first finds matching properties, then traverses to their child availability records.

3. **Vector Search (Bedrock Knowledge Base)** — Record data is chunked, embedded, and stored in Amazon Bedrock's managed vector store. This handles semantic matching for unstructured content like notes and descriptions. It also enforces Salesforce sharing rules via metadata filters—users only see records they're authorized to access.

### Key Characteristics

- **Zero-config field mapping**: Schema discovery runs automatically; no manual field configuration per query type
- **Cross-object queries**: Graph traversal handles Property → Availability → Lease relationships up to 2 hops deep
- **Salesforce sharing enforcement**: Authorization metadata propagates through the pipeline; KB queries filter by user's sharing buckets
- **Streaming responses**: Answers stream token-by-token for responsive UX
- **Debug mode**: Pass `debug: true` to see schema decomposition, planner output, match counts, and timing

### Current Limitations

- Complex aggregations ("companies owning more than 10 properties") require derived views or fall back to less precise vector matching
- Cross-object queries add latency (2-5 seconds vs. sub-second for direct queries)
- The system depends on schema cache accuracy—if fields aren't discovered, they can't be filtered

### Document Structure

- **Sections 1-3**: Data flow from Salesforce through ingestion to query execution
- **Sections 4-5**: Data stores, table schemas, and security model
- **Sections 6-7**: Operational state and known issues
- **Sections 8-14**: Deployment footprint, configuration flags, and ownership

---

## 1. High-Level Topology
- **Salesforce Org**  
  - Apex batch export (scheduled/triggered) and CDC Platform Events produce record payloads.  
  - Named Credential (AI_Search_Config) used for outbound calls to AWS Schema API.  
  - Custom Metadata `IndexConfiguration__mdt` still present for fallback; `Override_Schema_Cache__c` flag controls use.

- **AWS**  
  - **API Gateway / Lambda URLs**: public entrypoints for Retrieve and Answer.  
  - **Lambda Functions**: retrieve (planner + graph filter + KB search), answer (LLM synthesis), schema_discovery, schema_api, ingestion stages (validate, transform, chunking, enrich, embed, sync), graph_builder, derived_views, CDC processor.  
  - **Step Functions**: orchestrate backfill/CDC pipelines: Validate → Transform → Chunk → Graph Builder → Enrich → Embed → Sync.  
  - **DynamoDB**: schema_cache, vocab_cache, graph_nodes, graph_edges, availability_view, vacancy_view, leases_view, activities_agg, sales_view, authz_cache.  
  - **S3**: raw export landings, transformed objects, chunk bundles for KB, Lambda artifacts.  
  - **Bedrock Knowledge Base**: vector store for chunks, filterable metadata.  
  - **Amazon OpenSearch Serverless (AOSS)**: optional hybrid search; currently KB is primary.  
  - **KMS**: CMKs for DynamoDB, S3, and AOSS encryption.  
- **CloudWatch**: logs/metrics for Lambdas and pipelines; alarms partial.

---

## API Endpoints (Production)
- **Answer API (Lambda URL)**: `https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer`  
- **API Gateway (Retrieve/Schema)**: `https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/`  
- **Schema API**: `https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/schema/{objectApiName}`  
- **Service Key ID**: `hfhxij4lr0`

---

## 2. Data Flow (Ingestion)
1. **Schema Discovery (Nightly / On-Demand)**  
   - `lambda/schema_discovery` calls SF Describe to build canonical schema (filterable fields, relationships, record types). Stores results in `schema_cache` DynamoDB.  
   - RecordType detection included (Task 37).  
2. **Batch Export (Salesforce → S3)**  
   - Apex `AISearchBatchExport` fetches export fields from `schema_api` (Task 34) using Named Credential. Auto-includes `RecordType.Name` when `has_record_types=true`.  
   - Falls back to `IndexConfiguration__mdt` when `Override_Schema_Cache__c=true`.  
3. **CDC Processor**  
   - Handles Platform Events; normalizes payload; pushes to Step Functions.
4. **Step Functions Pipeline**  
   - **Validate**: FLS/sharing checks, required fields contract.  
   - **Transform**: flattens SF JSON, normalizes dates/ranges.  
   - **Chunking** (`lambda/chunking`): builds text chunks; strips `RecordType.Name` from text metadata, keeps `RecordType`/`RecordTypeName`.  
   - **Graph Builder**: emits `graph_nodes` (typed, with attributes: Name, RecordType, City, PropertyClass, etc.) and `graph_edges` (relationships).  
   - **Enrich**: attaches cross-object metadata (property → availability → lease).  
   - **Embed**: sends chunks to Bedrock embeddings.  
   - **Sync**: writes chunks+metadata to Bedrock KB.
5. **Derived Views**  
   - `availability_view`, `vacancy_view`, `leases_view`, `activities_agg`, `sales_view` populated during enrich; backfill Lambda exists but was **not run** in production. Legacy test data from deprecated seeds was cleared 2025-12-10; views (except vacancy_view) are empty pending clean backfill.  
   - **Deprecated**: `scripts/DEPRECATED_seed_derived_views.py` and `scripts/DEPRECATED_seed_schema_cache.py` must not be used (they inserted fake fields/data).

---

## 3. Query Flow (Runtime)
1. **API Entry**  
   - Retrieve Lambda invoked via API Gateway/Lambda URL.  
   - Request carries `query`, optional filters (Region, Business Unit, Quarter), and `salesforceUserId`.
2. **Planner** (`lambda/retrieve/planner.py`)  
   - Intent classification → plan with `targetObject`, `predicates`, `traversalPlan`, `seedIds`, `confidence`.  
   - Fallback to hybrid vector when confidence below threshold.
3. **Schema Decomposition** (`schema_decomposer.py`)  
   - Uses schema_cache + vocab_cache to map NL terms to fields/values.  
   - Value normalization (temporal, ranges, percentages, stage/status, geo aliases) handled by `value_normalizer.py` and `temporal_parser.py`.  
   - Deals vs Availability vs Property routing fixed in recent updates.
4. **Graph Filter & Traversal** (`graph_filter.py`, `cross_object_handler.py`)  
   - Uses `graph_nodes` GSI `type-createdAt` (ScanIndexForward now set to false to fetch newest first).  
   - Cross-object queries: resolve parent (e.g., Property) filters (Class, City, RecordType) → seed availability IDs via edges.  
   - Node/edge caps configurable; depth ≤2.
5. **Metadata Filters**  
   - Graph candidate IDs injected as `recordId IN (...)` KB filter (fix in retrieve index).  
   - Additional predicates applied to KB metadata (RecordTypeName, PropertyClass, City, etc.).
6. **KB Search (Bedrock KB)**  
   - Vector + metadata filter; `topK` configurable.  
   - Authorization via `sharingBuckets` metadata (user’s buckets in request).
7. **Enrichment** (`enrich_availability_matches_with_property_data`)  
   - Fetches parent property metadata from `graph_nodes`/`availability_view`; attaches Name, Class, City, Type.
8. **Answer Generation** (`lambda/answer`)  
   - Consumes chunks + enriched facts; LLM prompt steers toward structured bullet answers; supports debug SSE when `debug:true`.

---

## 4. Data Stores & Schemas
- **DynamoDB Tables**
  - `salesforce-ai-search-schema-cache`: `objectApiName` PK; fields: filterable_fields, relationships, graph_attributes, has_record_types.  
  - `salesforce-ai-search-vocab-cache`: PK `vocab_type#object`, SK `term`; stores term→field/value mappings.  
  - `salesforce-ai-search-graph-nodes`: PK `nodeId`, GSI `type-createdAt`; attributes include Name, RecordType, City, PropertyClass, PropertyType.  
  - `salesforce-ai-search-graph-edges`: PK `fromId`, SK `toIdType`; fields: fromId, toId, toIdType, fieldName, type, direction, createdAt; GSI `toId-index` for reverse lookups.  
  - Derived views: `availability_view` (property_id, availability_id), `vacancy_view` (~2,236 current records), `leases_view`, `activities_agg`, `sales_view` (latter three empty pending clean backfill).  
  - `authz_cache`: user → sharing buckets.
- **Bedrock Knowledge Base**  
  - Chunks with metadata: `sobject`, `recordId`, `RecordType`, `RecordTypeName`, `PropertyClass`, `City`, `PropertyId`, `AvailabilityId`, `sharingBuckets`.
- **S3 Buckets**  
  - Raw export landing, transformed JSON, chunk payloads, KB sync artifacts.

---

## 5. Security & Access Control
- API secured via API key/Named Credential; no public unauthenticated endpoints.  
- FLS/sharing respected: sharing buckets applied at KB filter; graph traversal expected to be auth-aware (intermediate nodes filtered if inaccessible).  
- Data at rest encrypted with KMS (DynamoDB, S3, AOSS).  
- Lambda IAM roles scoped to specific tables/buckets/collections.

---

## 6. Reliability & Monitoring (Current State)
- CloudWatch logs for Lambdas; Step Functions execution history.  
- Runtime guard logs `[FIELD_CONTRACT]` warnings when required fields missing (Task 36).  
- CI gate for schema cache contract (Task 38.2/38.3) implemented via `test_automation/test_schema_cache_contract.py` on 2025-12-10.  
- Not yet complete: field coverage nightly report, schema drift dashboard (Tasks 34.6/34.7/34.9/39).  
- Latency still high on cross-object availability queries; traversal/KB stages dominate.

---

## 7. Known Issues (as of 2025-12-10)
- Multi-value predicates (`A` OR `A+`) not correctly applied in cross-object filter → zero seeds.  
- Performance: cross-object queries can exceed 30s; traversal not always short-circuited when seeds exist.  
- Missing Name/metadata in some chunks causes “not enough information” responses.  
- Derived views were polluted by deprecated seeding; fake data cleared 2025-12-10.  
- `vacancy_view` currently holds 2,236 real records; other derived views are empty pending clean backfill.  
- Monitoring gaps: no automated schema drift/coverage alerts; limited per-stage latency metrics.

---

## 8. Deployment Footprint
- **CDK Stacks**: data-stack (DynamoDB, KMS), ingestion-stack (Lambdas, Step Functions), search-stack (Bedrock KB/AOSS), api-stack (schema_api, retrieve/answer endpoints).  
- **Lambda Runtimes**: Python 3.11; mix of zip and container; x86_64 in production (arm64 migration recommended).  
- **Salesforce Metadata**: Apex classes (AISearchBatchExport, AISearchCDCHandler, SchemaCacheClient), IndexConfiguration__mdt with override flag, named credential for AWS calls.

---

## 9. Functional Capabilities
- Natural language to structured filters with zero manual per-query config (planner + schema/vocab caches).  
- Cross-object retrieval: e.g., Availability filtered by Property class/city/record type.  
- Derived-view aggregation (vacancy, leases, activities, sales) used when planner routes to aggregates.  
- Value normalization: temporal ranges, size ranges, percentages, stage/status, geo aliases.  
- Debug mode streaming insight: schema decomposition, planner plan, aggregation view, match counts.

---

## 10. Key Configuration Flags
- `Override_Schema_Cache__c` (IndexConfiguration__mdt): bypass schema cache for export.  
- `has_record_types` (schema_cache per object): auto-includes RecordType in export.  
- `MAX_NODES_PER_HOP`, traversal depth/time caps in retrieve.  
- Planner confidence threshold; fallback to hybrid vector when low.  
- Knowledge Base `topK`, rerank settings; chunk size config in chunking lambda.

---

## 11. Future Hardening (non-exhaustive)
- Harden ingest-time required-field contract beyond the existing CI gate (Task 38) if gaps remain.  
- Add nightly field coverage and schema drift dashboards (Tasks 34.7, 39).  
- Fix multi-value predicate handling and enrichment parent-fetch bug.  
- Optimize traversal short-circuiting and KB parameters for latency.  
- Migrate retrieve/answer to arm64 with provisioned concurrency; trim packages.  
- Add per-stage latency/timeout metrics with alerts.

---

## 12. Request/Response Examples (Live Path)
**Query:** “show class A office availabilities in Plano”  
1) Planner → `targetObject=ascendix__Availability__c`, predicates: PropertyClass=A, City=Plano, RecordType=Office.  
2) Graph filter → property seeds (expected 3).  
3) KB search → filter recordId IN seeds; topK ~20; returns availability chunks.  
4) Enrich → attach parent property metadata (Name, Class, City, Type).  
5) Answer → bullet list of suites with status, property, class, city; citation list from KB chunks.

---

## 13. Artifact Locations
- **Code**: `lambda/retrieve`, `lambda/answer`, `lambda/schema_discovery`, `lambda/schema_api`, `lambda/chunking`, `lambda/graph_builder`, `lambda/enrich`, `lambda/embed`.  
- **Infrastructure**: `lib/*.ts` (CDK stacks).  
- **Salesforce**: `salesforce/classes/*.cls`, `salesforce/customMetadata/IndexConfiguration__mdt.*`, triggers `trigger_cre_export.apex`, `trigger_export.apex`.  
- **Specs (for reference only)**: `.kiro/specs/graph-aware-zero-config-retrieval/*`.  
- **CI Validation**: `test_automation/test_schema_cache_contract.py` (schema cache contract test).  
- **Deprecated Scripts (do not use)**: `scripts/DEPRECATED_seed_schema_cache.py`, `scripts/DEPRECATED_seed_derived_views.py`.

---

## 14. Contacts / Ownership
- **Runtime (Retrieve/Answer)**: Search team (Lambda owners).  
- **Ingestion / Graph**: Data platform team.  
- **Salesforce Export**: Salesforce team owning AISearchBatchExport + IndexConfiguration__mdt.  
- **Schema Cache / Discovery**: Platform team.  
- **Observability**: Shared; needs completion per tasks above.
