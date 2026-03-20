# Phase 4 PRD: Hybrid Graph-RAG & No-Code Configuration

> Superseded historical spec. This document describes an older graph-RAG
> direction that is not the active connector architecture. For current work,
> use `docs/specs/salesforce-connector-spec.md`, `README.md`, and
> `docs/architecture/object_scope_and_sync.md`.

## 1. Executive Summary
This phase enhances the Salesforce AI Search system by introducing a "Hybrid Graph-RAG" architecture. By integrating AWS Neptune (Graph DB) alongside the existing OpenSearch (Vector DB), the system will gain the ability to answer complex structured queries involving **relationships**, **numeric ranges**, **dates**, and **aggregations**—capabilities that pure Vector RAG struggles with.

Crucially, this capability will be exposed via a **No-Code Admin Interface**, allowing Salesforce administrators to define which fields and relationships are searchable without engineering intervention.

## 2. The "Steel Thread" Goal
To validate this architecture, we will implement a specific "Steel Thread" use case:

**User Query:** *"Show me office properties in Dallas with available space between 10,000 and 15,000 sq ft."*

**Why this requires Graph-RAG:**
*   **Relationship:** "Available space" (`Availability__c`) is a child record of "Property" (`Property__c`). The user wants to see the *Parent* based on the *Child's* attribute.
*   **Range Filter:** "Between 10,000 and 15,000" requires precise numeric filtering logic (`>= 10000 AND <= 15000`), which vector similarity cannot guarantee.
*   **Structure:** "Office" and "Dallas" are structured fields (`Property_Type__c`, `City__c`) that demand exact matches, not "semantically similar" matches.

## 3. Architecture: The "Dual Context" Approach

The system will use a two-step retrieval process:
1.  **The Spine (Graph):** AWS Neptune filters for IDs based on structured criteria (Ranges, Dates, Relationships).
2.  **The Flesh (Vector):** OpenSearch provides the semantic content (Descriptions, Notes) for those specific IDs.

### 3.1 Data Flow
1.  **Ingestion (Dual-Write):**
    *   Salesforce CDC event triggers ingestion.
    *   **Path A (Vector):** Text fields are chunked, embedded, and sent to OpenSearch (Existing).
    *   **Path B (Graph):** Numeric/Date/Relationship fields are extracted and upserted as Nodes/Edges in Neptune (New).
2.  **Retrieval (ID-First):**
    *   User asks a question.
    *   **Intent Classifier:** Detects "Structured Filter" intent.
    *   **Query Translator:** LLM converts text to Gremlin query.
    *   **Graph Search:** Neptune executes Gremlin, returns list of `RecordIds`.
    *   **Vector Search:** OpenSearch queries for context, *filtered by the list of RecordIds*.
    *   **Synthesis:** LLM summarizes the results.

## 4. No-Code Configuration Model
We will extend the `IndexConfiguration__mdt` custom metadata type to drive this behavior dynamically.

**New Metadata Fields:**
*   `Graph_Enabled__c` (Checkbox): Sync this object to Neptune?
*   `Graph_Numeric_Fields__c` (Long Text): Comma-separated fields to index as sortable/filterable numbers (e.g., `Square_Footage__c`, `Amount`).
*   `Graph_Date_Fields__c` (Long Text): Comma-separated fields to index as dates (e.g., `Lease_Expiration__c`).
*   `Graph_Parent_Field__c` (Text): API name of the lookup field defining the hierarchy (e.g., `Property__c` on Availability).

## 5. Implementation Plan (Steel Thread)

### 5.1 Infrastructure (CDK)
*   [ ] **Deploy AWS Neptune:** Add `GraphStack` to CDK.
    *   Provision Neptune Cluster (Serverless or Provisioned).
    *   Configure VPC endpoints and Security Groups (PrivateLink access).
    *   Enable IAM database authentication.

### 5.2 Configuration (Salesforce)
*   [ ] **Update Metadata Schema:** Add Graph fields to `IndexConfiguration__mdt`.
*   [ ] **Configure Steel Thread Objects:**
    *   **Property__c:**
        *   `Graph_Enabled__c`: True
        *   `Graph_Filter_Fields__c`: City__c, Property_Type__c
    *   **Availability__c:**
        *   `Graph_Enabled__c`: True
        *   `Graph_Numeric_Fields__c`: Square_Footage__c
        *   `Graph_Parent_Field__c`: Property__c

### 5.3 Ingestion Logic (Lambda)
*   [ ] **Enhance `TransformLambda`:** Read configuration and extract "Graph Payload" (Nodes/Edges) alongside "Vector Payload".
*   [ ] **Create `GraphSyncLambda`:** New function to receive Graph Payload and execute Gremlin `upsert` queries to Neptune.
    *   *Logic:* `g.addV('Availability').property('id', 'a1').property('sq_ft', 12000).addE('BELONGS_TO').to(g.V('p1'))`

### 5.4 Retrieval Logic (Lambda)
*   [ ] **Update `RetrieveLambda`:**
    *   Add Intent Classification step (LLM Prompt).
    *   Add Gremlin Generation step (LLM Prompt with Schema definition).
    *   Execute Neptune Query.
    *   Pass resulting IDs to Bedrock Knowledge Base as a `recordId` filter.

## 6. Success Criteria
1.  **Accuracy:** Querying for "10k-15k sq ft" returns *only* properties with availabilities in that range.
2.  **Performance:** End-to-end latency < 5 seconds.
3.  **Flexibility:** Admin can enable "Lease Expiration" filtering by simply adding the field to the Metadata record, with **zero code changes**.
