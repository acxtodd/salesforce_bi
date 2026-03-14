# Schema-Driven AI Search Configuration

## Product Requirements Document

**Version**: 0.1 (Draft)
**Created**: 2025-11-28
**Status**: Discovery / Analysis
**Author**: AI Search Team

---

## Executive Summary

This document proposes a **declarative, admin-configurable AI search system** for Salesforce that eliminates the need for developer involvement in search configuration. Salesforce administrators would configure search capabilities through a UI, specifying which objects are searchable, which fields are filterable, which relationships to traverse, and which fields support numeric calculations. The system would then automatically:

1. Build the appropriate graph structure
2. Index fields correctly (vector vs. structured)
3. Decompose natural language queries using schema awareness
4. Execute hybrid retrieval (graph traversal + vector search)

The system could either stand alone with a new admin UI or integrate with **Ascendix Search** to provide a unified configuration experience.

### Key Discovery: Automatic Schema Detection

Analysis of Salesforce APIs (specifically the Describe API and Tooling API) reveals that **we can auto-discover the complete schema** without manual configuration:

| Metadata | API Source | Auto-Discoverable |
|----------|------------|-------------------|
| All objects | `EntityDefinition` | Yes - with IsQueryable, IsSearchable flags |
| Field types | `sobject describe` | Yes - string, picklist, double, date, reference |
| Picklist values | `sobject describe` | Yes - complete value lists |
| Relationships | `sobject describe` | Yes - referenceTo and childRelationships |
| Field filterability | `sobject describe` | Yes - filterable, sortable flags |

This enables a **zero-configuration baseline** with optional admin refinement.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Vision & Goals](#2-vision--goals)
3. [Current State Analysis](#3-current-state-analysis)
4. [Proposed Architecture](#4-proposed-architecture)
5. [Configuration Model](#5-configuration-model)
6. [Query Processing Pipeline](#6-query-processing-pipeline)
7. [Integration Options](#7-integration-options)
8. [Risks & Mitigations](#8-risks--mitigations)
9. [Implementation Phases](#9-implementation-phases)
10. [Success Criteria](#10-success-criteria)
11. [Automatic Schema Discovery](#11-automatic-schema-discovery) **(NEW)**
12. [Open Questions](#12-open-questions)
13. [Appendix](#appendix)

---

## 1. Problem Statement

### 1.1 Current Challenges

The existing AI Search implementation has several limitations that prevent it from handling complex CRE (Commercial Real Estate) queries accurately:

| Problem | Example | Root Cause |
|---------|---------|------------|
| **Missing filterable metadata** | "retail properties in Dallas" returns Office properties | KB metadata lacks `PropertySubType`, `City` fields |
| **No structured filtering** | "deals over $1M" returns random deals | Vector search doesn't understand numeric comparisons |
| **Value mapping failures** | "Class A" doesn't match "A" in data | No schema awareness of picklist values |
| **Temporal query gaps** | "no activity in 30 days" fails | Date fields not indexed as filterable |
| **Manual configuration** | Every change requires code updates | No admin-facing configuration UI |

### 1.2 The Fundamental Gap

The system lacks **schema awareness**. It doesn't know:
- Which fields can be filtered on (vs. searched as text)
- What valid values exist for picklist fields
- Which fields are numeric (for comparisons/aggregations)
- Which fields are dates (for temporal queries)
- How objects relate to each other

Without this knowledge, query decomposition is guesswork.

---

## 2. Vision & Goals

### 2.1 Vision Statement

> Enable Salesforce administrators to configure AI search capabilities through a declarative UI, without writing code. The system learns the data model from configuration and automatically handles query understanding, graph traversal, and result retrieval.

### 2.2 Primary Goals

| Goal | Description | Success Metric |
|------|-------------|----------------|
| **No-Code Configuration** | Admins configure search via UI | Zero developer involvement for standard configs |
| **Schema-Aware Queries** | System understands field types and values | 90%+ query decomposition accuracy |
| **Automatic Graph Building** | Graph structure derived from config | Config change → graph update (< 5 min) |
| **Accurate Filtering** | Structured filters work correctly | "retail in Dallas" returns only retail |
| **Unified Experience** | Optional integration with Ascendix Search | Single configuration point |

### 2.3 User Stories

#### Admin Configuration
```
As a Salesforce Administrator,
I want to configure which objects and fields are searchable,
So that the AI search works correctly for my org's data model
Without requiring developer assistance.
```

#### Complex Query Handling
```
As a CRE Broker,
I want to ask "which deals related to class A office space in the Dallas CBD
have had no activity in the last 30 days",
So that I can identify stale deals that need attention.
```

#### Filter Accuracy
```
As a CRE Analyst,
I want to search for "retail properties in Dallas",
So that I get ONLY retail properties (not office buildings that mention retail).
```

---

## 3. Current State Analysis

### 3.1 What Exists Today

| Component | Status | Gaps |
|-----------|--------|------|
| **IndexConfiguration__mdt** | Partially built | Missing: Searchable, Filterable, Numeric, Date field configs |
| **Graph Builder** | Working | Node attributes empty or minimal |
| **Graph Retriever** | Working | No structured filtering on node attributes |
| **Query Decomposer** | Prototype | No schema awareness, relies on LLM guessing |
| **KB Metadata** | Basic | Only: sobject, recordId, name, ownerId |
| **Intent Router** | Working | Pattern-based, not schema-aware |

### 3.2 Current IndexConfiguration__mdt Schema

```xml
<!-- Existing Fields -->
<fields>
    <fullName>Enabled__c</fullName>              <!-- Object enabled for indexing -->
    <fullName>Graph_Enabled__c</fullName>        <!-- Include in graph -->
    <fullName>Relationship_Depth__c</fullName>   <!-- Traversal depth 1-3 -->
    <fullName>Relationship_Fields__c</fullName>  <!-- Which lookups to traverse -->
    <fullName>Graph_Node_Attributes__c</fullName><!-- Fields to store on nodes -->
</fields>

<!-- MISSING - Need to Add -->
<fields>
    <fullName>Searchable_Fields__c</fullName>    <!-- Text fields for vector search -->
    <fullName>Filterable_Fields__c</fullName>    <!-- Structured filter fields -->
    <fullName>Numeric_Fields__c</fullName>       <!-- For comparisons/aggregations -->
    <fullName>Date_Fields__c</fullName>          <!-- For temporal queries -->
    <fullName>Picklist_Values_Cache__c</fullName><!-- Cached values for LLM -->
</fields>
```

### 3.3 Ascendix Search Configuration (Existing)

The Ascendix Search package already has configuration infrastructure:

| Object/Setting | Purpose | Data Found |
|----------------|---------|------------|
| `SearchSetting__c` | Global settings | Selected Objects (Account, Contact, Lead) |
| `SearchableObject__mdt` | Object-level config | Not populated |
| `Selected Objects` JSON | Object + field config | Includes map settings, AdHoc list flags |

**Current Selected Objects Config**:
```json
[
  {
    "name": "Account",
    "isSearchable": true,
    "isMapEnabled": true,
    "isAdHocListEnabled": true,
    "mapData": {"geolocation": "BillingAddress"}
  },
  {
    "name": "Contact",
    "isSearchable": true,
    "isMapEnabled": true
  },
  {
    "name": "Lead",
    "isSearchable": true,
    "isMapEnabled": true
  }
]
```

**Gap**: CRE objects (Property, Deal, Availability, Lease) not configured.

---

## 4. Proposed Architecture

### 4.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SALESFORCE ORG                                │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    Admin Configuration UI                      │  │
│  │  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐  │  │
│  │  │ Objects         │ │ Fields          │ │ Relationships   │  │  │
│  │  │                 │ │                 │ │                 │  │  │
│  │  │ ☑ Property      │ │ Property:       │ │ Property →      │  │  │
│  │  │ ☑ Deal          │ │  ☑ Name      [S]│ │   Availability  │  │  │
│  │  │ ☑ Availability  │ │  ☑ City      [F]│ │   Listing       │  │  │
│  │  │ ☑ Lease         │ │  ☑ Class     [F]│ │   Deal          │  │  │
│  │  │ ☑ Account       │ │  ☑ SubType   [F]│ │                 │  │  │
│  │  │ ☐ Contact       │ │  ☑ TotalSF   [N]│ │ Deal →          │  │  │
│  │  │                 │ │  ☑ YearBuilt [N]│ │   Property      │  │  │
│  │  └─────────────────┘ └─────────────────┘ │   Client        │  │  │
│  │                                          │   Tenant        │  │  │
│  │  Legend: [S]=Searchable [F]=Filterable   └─────────────────┘  │  │
│  │          [N]=Numeric    [D]=Date                              │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│                              ▼                                       │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              IndexConfiguration__mdt (Enhanced)                │  │
│  │  Object: Property                                              │  │
│  │  ├─ Searchable: Name, Description, Comments                    │  │
│  │  ├─ Filterable: City, State, PropertyClass, PropertySubType   │  │
│  │  ├─ Numeric: TotalArea, YearBuilt, Stories, AskingPrice       │  │
│  │  ├─ Date: AcquisitionDate, LastActivityDate                   │  │
│  │  ├─ Relationships: Availability, Listing, Deal                │  │
│  │  └─ PicklistValues: {PropertyClass: [A,B,C], SubType: [...]}  │  │
│  └───────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ CDC / Batch Sync
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           AWS BACKEND                                │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    Schema Registry Service                     │  │
│  │  • Syncs IndexConfiguration__mdt from Salesforce               │  │
│  │  • Caches schema for fast query-time lookup                    │  │
│  │  • Detects changes → triggers selective reindex                │  │
│  │  • Provides schema to all consumers                            │  │
│  └───────────────────────────────────────────────────────────────┘  │
│           │                    │                    │               │
│           ▼                    ▼                    ▼               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │  Graph Builder  │  │  Chunk Indexer  │  │   Query Engine      │ │
│  │                 │  │                 │  │                     │ │
│  │  Uses schema:   │  │  Uses schema:   │  │  ┌───────────────┐  │ │
│  │  • Node attrs   │  │  • Filterable   │  │  │Schema-Aware   │  │ │
│  │    from Filter- │  │    fields →     │  │  │Query          │  │ │
│  │    able_Fields  │  │    KB metadata  │  │  │Decomposer     │  │ │
│  │  • Edges from   │  │  • Searchable   │  │  │               │  │ │
│  │    Relationship │  │    fields →     │  │  │NL → Structured│  │ │
│  │    _Fields      │  │    vector text  │  │  │using schema   │  │ │
│  └────────┬────────┘  └────────┬────────┘  │  └───────────────┘  │ │
│           │                    │           └──────────┬──────────┘ │
│           ▼                    ▼                      ▼            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│  │   Graph DB      │  │   Bedrock KB    │  │  Hybrid Retriever   │ │
│  │   (DynamoDB)    │  │   (OpenSearch)  │  │                     │ │
│  │                 │  │                 │  │  1. Filter on graph │ │
│  │  Nodes with:    │  │  Chunks with:   │  │     node attrs      │ │
│  │  • Filterable   │  │  • Filterable   │  │  2. Traverse rels   │ │
│  │    attrs        │  │    metadata     │  │  3. Vector search   │ │
│  │  • Relationships│  │  • Vector       │  │     on matches      │ │
│  └─────────────────┘  │    embeddings   │  │  4. Merge & rank    │ │
│                       └─────────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Data Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                     CONFIGURATION FLOW                            │
│                                                                   │
│  Admin UI ──► IndexConfiguration__mdt ──► Schema Registry        │
│                                               │                   │
│              ┌────────────────────────────────┼──────────────┐   │
│              ▼                                ▼              ▼   │
│        Graph Builder               Chunk Indexer      Query Engine│
│              │                           │                   │   │
│              ▼                           ▼                   │   │
│         Graph DB                     Bedrock KB              │   │
│              │                           │                   │   │
│              └───────────────────────────┴───────────────────┘   │
│                                    │                              │
│                              Query Results                        │
└──────────────────────────────────────────────────────────────────┘
```

```
┌──────────────────────────────────────────────────────────────────┐
│                        QUERY FLOW                                 │
│                                                                   │
│  "Class A office properties in Dallas with available space"      │
│                              │                                    │
│                              ▼                                    │
│                    ┌─────────────────┐                           │
│                    │ Query Decomposer │                          │
│                    │ (Schema-Aware)   │                          │
│                    └────────┬────────┘                           │
│                             │                                     │
│     Schema says:            │      Produces:                     │
│     • PropertyClass: [F]    │      {                             │
│     • PropertySubType: [F]  │        target: "Property",         │
│     • City: [F]             │        filters: {                  │
│     • Property→Availability │          PropertyClass: "A",       │
│                             │          PropertySubType: "Office",│
│                             │          City: "Dallas"            │
│                             │        },                          │
│                             │        traversals: [{              │
│                             │          to: "Availability",       │
│                             │          filters: {Status:"Avail"} │
│                             │        }]                          │
│                             │      }                             │
│                             ▼                                     │
│                    ┌─────────────────┐                           │
│                    │ Hybrid Retriever │                          │
│                    └────────┬────────┘                           │
│                             │                                     │
│     1. Query Graph:         │                                     │
│        Property nodes       │                                     │
│        WHERE Class=A        │                                     │
│        AND SubType=Office   │                                     │
│        AND City=Dallas      │                                     │
│                             │                                     │
│     2. Traverse to          │                                     │
│        Availability nodes   │                                     │
│        WHERE Status=Avail   │                                     │
│                             │                                     │
│     3. Vector search        │                                     │
│        on matching IDs      │                                     │
│                             │                                     │
│     4. Merge & Return       │                                     │
│                             ▼                                     │
│                       Accurate Results                            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 5. Configuration Model

### 5.1 Enhanced IndexConfiguration__mdt Schema

```xml
<?xml version="1.0" encoding="UTF-8"?>
<CustomObject xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Index Configuration</label>
    <pluralLabel>Index Configurations</pluralLabel>

    <!-- === EXISTING FIELDS === -->
    <fields>
        <fullName>Enabled__c</fullName>
        <type>Checkbox</type>
        <defaultValue>false</defaultValue>
        <description>Enable this object for AI search indexing</description>
    </fields>

    <fields>
        <fullName>Graph_Enabled__c</fullName>
        <type>Checkbox</type>
        <defaultValue>false</defaultValue>
        <description>Include this object in graph database for relationship queries</description>
    </fields>

    <fields>
        <fullName>Relationship_Depth__c</fullName>
        <type>Number</type>
        <precision>1</precision>
        <defaultValue>2</defaultValue>
        <description>How many levels of relationships to traverse (1-3)</description>
    </fields>

    <fields>
        <fullName>Relationship_Fields__c</fullName>
        <type>LongTextArea</type>
        <length>32768</length>
        <description>JSON array of lookup/master-detail fields to traverse</description>
    </fields>

    <!-- === NEW FIELDS === -->
    <fields>
        <fullName>Searchable_Fields__c</fullName>
        <type>LongTextArea</type>
        <length>32768</length>
        <description>
            JSON array of fields to include in vector search text.
            These fields are concatenated into the chunk text for semantic search.
            Example: ["Name", "Description", "Comments__c"]
        </description>
    </fields>

    <fields>
        <fullName>Filterable_Fields__c</fullName>
        <type>LongTextArea</type>
        <length>32768</length>
        <description>
            JSON array of fields for structured filtering.
            These become: (1) Graph node attributes, (2) KB chunk metadata.
            Example: ["City", "State", "PropertyClass__c", "PropertySubType__c"]
        </description>
    </fields>

    <fields>
        <fullName>Numeric_Fields__c</fullName>
        <type>LongTextArea</type>
        <length>32768</length>
        <description>
            JSON array of numeric fields for comparisons and aggregations.
            Enables queries like "over $1M", "largest by area", "total value".
            Example: ["TotalArea__c", "AskingPrice__c", "YearBuilt__c"]
        </description>
    </fields>

    <fields>
        <fullName>Date_Fields__c</fullName>
        <type>LongTextArea</type>
        <length>32768</length>
        <description>
            JSON array of date fields for temporal queries.
            Enables queries like "last 30 days", "expiring next month".
            Example: ["LastActivityDate", "LeaseExpiration__c", "CreatedDate"]
        </description>
    </fields>

    <fields>
        <fullName>Picklist_Values__c</fullName>
        <type>LongTextArea</type>
        <length>131072</length>
        <description>
            JSON object caching picklist values for each filterable field.
            Used by query decomposer for value matching/validation.
            Example: {"PropertyClass__c": ["A", "B", "C"], "Status__c": ["Active", "Pending"]}
        </description>
    </fields>

    <fields>
        <fullName>Display_Name_Field__c</fullName>
        <type>Text</type>
        <length>100</length>
        <defaultValue>"Name"</defaultValue>
        <description>
            Field to use as display name in graph nodes and results.
            Falls back to: Name, Subject, Title, then record ID.
        </description>
    </fields>

    <fields>
        <fullName>Last_Schema_Sync__c</fullName>
        <type>DateTime</type>
        <description>Timestamp of last schema sync to AWS</description>
    </fields>

    <fields>
        <fullName>Reindex_Required__c</fullName>
        <type>Checkbox</type>
        <defaultValue>false</defaultValue>
        <description>Flag indicating configuration changed and reindex needed</description>
    </fields>
</CustomObject>
```

### 5.2 Example Configuration Records

#### Property Configuration
```json
{
  "DeveloperName": "Property",
  "Object_API_Name__c": "ascendix__Property__c",
  "Enabled__c": true,
  "Graph_Enabled__c": true,
  "Relationship_Depth__c": 2,

  "Searchable_Fields__c": [
    "Name",
    "ascendix__Description__c",
    "ascendix__LocationDescription__c",
    "ascendix__MarketDescription__c"
  ],

  "Filterable_Fields__c": [
    "ascendix__City__c",
    "ascendix__State__c",
    "ascendix__PropertyClass__c",
    "ascendix__PropertySubType__c",
    "ascendix__BuildingStatus__c",
    "ascendix__Market__c",
    "ascendix__Submarket__c"
  ],

  "Numeric_Fields__c": [
    "ascendix__TotalArea__c",
    "ascendix__LandArea__c",
    "ascendix__Stories__c",
    "ascendix__YearBuilt__c",
    "ascendix__YearRenovated__c",
    "ascendix__ParkingSpaces__c"
  ],

  "Date_Fields__c": [
    "ascendix__AcquisitionDate__c",
    "LastActivityDate",
    "LastModifiedDate"
  ],

  "Relationship_Fields__c": [
    "ascendix__Complex__c",
    "ascendix__Market__c",
    "OwnerId"
  ],

  "Picklist_Values__c": {
    "ascendix__PropertyClass__c": ["A", "B", "C"],
    "ascendix__PropertySubType__c": ["Office", "Retail", "Industrial", "Multifamily", "Mixed-Use", "Land"],
    "ascendix__BuildingStatus__c": ["Existing", "Under Construction", "Proposed", "Demolished"]
  },

  "Display_Name_Field__c": "Name"
}
```

#### Deal Configuration
```json
{
  "DeveloperName": "Deal",
  "Object_API_Name__c": "ascendix__Deal__c",
  "Enabled__c": true,
  "Graph_Enabled__c": true,
  "Relationship_Depth__c": 2,

  "Searchable_Fields__c": [
    "Name",
    "ascendix__DealNotes__c",
    "ascendix__Comments__c"
  ],

  "Filterable_Fields__c": [
    "ascendix__Status__c",
    "ascendix__SalesStage__c",
    "ascendix__DealType__c",
    "ascendix__ClientRole__c"
  ],

  "Numeric_Fields__c": [
    "ascendix__GrossFeeAmount__c",
    "ascendix__NetFeeAmount__c",
    "ascendix__DealSize__c",
    "ascendix__SquareFeet__c"
  ],

  "Date_Fields__c": [
    "ascendix__CloseDate__c",
    "ascendix__ProjectedCloseDate__c",
    "LastActivityDate",
    "CreatedDate"
  ],

  "Relationship_Fields__c": [
    "ascendix__Property__c",
    "ascendix__Client__c",
    "ascendix__Tenant__c",
    "ascendix__Availability__c",
    "OwnerId"
  ],

  "Picklist_Values__c": {
    "ascendix__Status__c": ["Open", "Closed Won", "Closed Lost", "On Hold"],
    "ascendix__SalesStage__c": ["Prospecting", "Qualification", "Proposal", "Negotiation", "Closed"],
    "ascendix__DealType__c": ["Lease", "Sale", "Sublease"]
  }
}
```

### 5.3 Field Type Implications

| Field Type | Graph Node | KB Metadata | Query Capability |
|------------|------------|-------------|------------------|
| **Searchable** | - | In chunk text | Semantic similarity |
| **Filterable** | Node attribute | Metadata field | Exact match, IN list |
| **Numeric** | Node attribute | Metadata field | >, <, >=, <=, range |
| **Date** | Node attribute | Metadata field | Before, after, range, relative |
| **Relationship** | Edge | - | Graph traversal |

---

## 6. Query Processing Pipeline

### 6.1 Schema-Aware Query Decomposer

```python
class SchemaAwareQueryDecomposer:
    """
    Decomposes natural language queries using schema knowledge.
    """

    def __init__(self, schema_registry: SchemaRegistry):
        self.schema = schema_registry
        self.llm = BedrockClient(model="claude-haiku")

    def decompose(self, query: str) -> StructuredQuery:
        """
        Decompose query using schema context.

        Example:
        Query: "Class A office properties in Dallas CBD with available space
                that had no activity in 30 days"

        Schema provides:
        - Property has filterable: City, PropertyClass, PropertySubType
        - Property has date: LastActivityDate
        - Property → Availability relationship
        - Availability has filterable: Status

        Returns:
        {
            "target_entity": "Property",
            "filters": {
                "PropertyClass": {"operator": "eq", "value": "A"},
                "PropertySubType": {"operator": "eq", "value": "Office"},
                "City": {"operator": "eq", "value": "Dallas"}
            },
            "date_filters": {
                "LastActivityDate": {"operator": "older_than", "days": 30}
            },
            "traversals": [
                {
                    "to": "Availability",
                    "via": "ascendix__Property__c",
                    "filters": {
                        "Status": {"operator": "eq", "value": "Available"}
                    }
                }
            ],
            "confidence": 0.92
        }
        """

        # Build schema context for LLM
        schema_context = self._build_schema_context(query)

        # LLM decomposition with schema awareness
        decomposition = self._llm_decompose(query, schema_context)

        # Validate against schema
        validated = self._validate_decomposition(decomposition)

        return validated

    def _build_schema_context(self, query: str) -> str:
        """
        Build schema context relevant to the query.
        Includes: objects, filterable fields, valid values, relationships.
        """
        # Detect mentioned entities
        entities = self._detect_entities(query)

        context_parts = []
        for entity in entities:
            config = self.schema.get_config(entity)
            if config:
                context_parts.append(f"""
Object: {entity}
  Filterable Fields: {config.filterable_fields}
  Valid Values: {config.picklist_values}
  Numeric Fields: {config.numeric_fields}
  Date Fields: {config.date_fields}
  Relationships: {config.relationships}
""")

        return "\n".join(context_parts)

    def _validate_decomposition(self, decomposition: Dict) -> StructuredQuery:
        """
        Validate extracted values against schema.
        - Check field names exist
        - Validate values against picklist options
        - Normalize value formats
        """
        for field, filter_spec in decomposition.get("filters", {}).items():
            config = self.schema.get_field_config(field)
            if config and config.picklist_values:
                # Fuzzy match value against valid options
                filter_spec["value"] = self._match_value(
                    filter_spec["value"],
                    config.picklist_values
                )

        return StructuredQuery(**decomposition)
```

### 6.2 Query Execution Flow

```python
class HybridQueryExecutor:
    """
    Executes decomposed queries using graph + vector search.
    """

    def execute(self, query: StructuredQuery, user_context: Dict) -> List[Result]:
        """
        Execute hybrid retrieval based on query structure.
        """

        # Step 1: Filter on graph node attributes
        if query.filters:
            candidate_nodes = self.graph_db.query_nodes(
                object_type=query.target_entity,
                filters=query.filters,
                date_filters=query.date_filters
            )
        else:
            candidate_nodes = None  # No pre-filtering

        # Step 2: Execute relationship traversals
        if query.traversals:
            for traversal in query.traversals:
                candidate_nodes = self.graph_db.traverse(
                    from_nodes=candidate_nodes,
                    to_type=traversal.to,
                    via_field=traversal.via,
                    filters=traversal.filters
                )

        # Step 3: Get candidate record IDs
        if candidate_nodes:
            candidate_ids = [n.record_id for n in candidate_nodes]
        else:
            candidate_ids = None

        # Step 4: Vector search with ID filter
        vector_results = self.bedrock_kb.search(
            query=query.original_text,
            filter={
                "recordId": {"$in": candidate_ids} if candidate_ids else None,
                "sobject": query.target_entity
            }
        )

        # Step 5: Enrich with relationship context
        enriched = self._enrich_with_paths(vector_results, candidate_nodes)

        # Step 6: Apply authorization
        authorized = self._apply_authz(enriched, user_context)

        return authorized
```

---

## 7. Integration Options

### 7.1 Option A: Standalone IndexConfiguration__mdt

**Description**: Use enhanced `IndexConfiguration__mdt` with new admin UI.

**Pros**:
- Independent of Ascendix Search package
- Custom metadata is deployable/versionable
- Full control over schema
- No package dependency risk

**Cons**:
- Duplicate configuration if using both tools
- Need to build admin UI from scratch
- Training for admins on new interface

**Implementation Effort**: Medium-High (8-10 weeks)

### 7.2 Option B: Extend Ascendix Search Configuration

**Description**: Add AI-specific fields to existing `SearchSetting__c`.

**Pros**:
- Single configuration point
- Admins already know the UI
- Leverages existing investment

**Cons**:
- Package dependency
- May need custom fields in managed package
- Package upgrades could break integration

**Implementation Effort**: Medium (6-8 weeks)

### 7.3 Option C: Unified Configuration Service (Recommended)

**Description**: Read from both sources, merge at runtime.

```
┌─────────────────────────────────────────────────────────────────┐
│                 Unified Configuration Service                    │
│                                                                  │
│   ┌─────────────────┐          ┌─────────────────┐              │
│   │ Ascendix Search │          │ IndexConfig__mdt│              │
│   │ Config (Objects,│          │ (AI-specific    │              │
│   │ Fields, Maps)   │          │ Field Types)    │              │
│   └────────┬────────┘          └────────┬────────┘              │
│            │                            │                        │
│            └──────────┬─────────────────┘                        │
│                       ▼                                          │
│            ┌─────────────────────┐                               │
│            │  Merge & Reconcile  │                               │
│            │  • Object enabled?  │                               │
│            │  • Field types      │                               │
│            │  • Relationships    │                               │
│            └──────────┬──────────┘                               │
│                       ▼                                          │
│            ┌─────────────────────┐                               │
│            │  Unified Schema API │                               │
│            │  /schema/objects    │                               │
│            │  /schema/fields     │                               │
│            │  /schema/relations  │                               │
│            └─────────────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
```

**Pros**:
- Best of both worlds
- Gradual migration path
- Works with or without Ascendix Search
- Can enhance without breaking existing

**Cons**:
- Most complex implementation
- Need conflict resolution logic
- Two places to potentially configure

**Implementation Effort**: High (10-12 weeks)

### 7.4 Decision Framework

| Factor | Option A | Option B | Option C |
|--------|----------|----------|----------|
| Ascendix Search dependency | None | High | Optional |
| Implementation effort | Medium | Medium | High |
| Admin learning curve | High | Low | Medium |
| Long-term flexibility | High | Low | High |
| Risk of breaking changes | Low | Medium | Low |
| Single source of truth | Yes | Yes | No* |

*Option C has two sources but unified API

**Recommendation**: Start with **Option A** (standalone), design for **Option C** compatibility.

---

## 8. Risks & Mitigations

### 8.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Value mapping failures** | High | Medium | Cache picklist values, fuzzy matching, LLM validation |
| **Reindex cost/time** | Medium | High | Incremental reindex, background processing, delta detection |
| **Schema drift** | Medium | Medium | Metadata API sync, validation on change, alerts |
| **Complex query performance** | Medium | Medium | Depth limits, path caching, pre-compute popular traversals |
| **LLM decomposition accuracy** | Medium | High | Schema context, validation layer, fallback to vector-only |

### 8.2 Value Mapping Challenge

**Problem**: User says "Class A", data has "A" or "CLASS_A" or "Class A".

**Solution**: Multi-layer matching

```python
def match_value(user_value: str, valid_values: List[str]) -> str:
    """
    Match user input to valid picklist values.
    """
    # 1. Exact match
    if user_value in valid_values:
        return user_value

    # 2. Case-insensitive match
    for v in valid_values:
        if v.lower() == user_value.lower():
            return v

    # 3. Fuzzy match (contains)
    for v in valid_values:
        if user_value.lower() in v.lower() or v.lower() in user_value.lower():
            return v

    # 4. LLM semantic match
    return llm_match_value(user_value, valid_values)
```

### 8.3 Temporal Query Handling

**Problem**: "Last 30 days", "next quarter", "expiring soon"

**Solution**: Date expression parser

```python
DATE_EXPRESSIONS = {
    r"last (\d+) days?": lambda m: (now() - timedelta(days=int(m.group(1))), now()),
    r"next (\d+) months?": lambda m: (now(), now() + relativedelta(months=int(m.group(1)))),
    r"this quarter": lambda m: get_quarter_range(now()),
    r"expiring soon": lambda m: (now(), now() + timedelta(days=90)),
    r"no activity in (\d+) days?": lambda m: (None, now() - timedelta(days=int(m.group(1)))),
}
```

---

## 9. Implementation Phases

### Phase 1: Enhanced Configuration (2-3 weeks)

**Goal**: Extend IndexConfiguration__mdt with new field types

- [ ] Add Searchable_Fields__c, Filterable_Fields__c, Numeric_Fields__c, Date_Fields__c
- [ ] Add Picklist_Values__c with auto-population from SF
- [ ] Create configuration records for CRE objects
- [ ] Deploy to sandbox

**Deliverable**: Complete schema for Property, Deal, Availability, Lease, Account

### Phase 2: Schema Registry Service (2 weeks)

**Goal**: AWS service that syncs and caches schema

- [ ] Create Lambda to fetch IndexConfiguration__mdt
- [ ] Cache schema in DynamoDB or Lambda memory
- [ ] Expose schema API for other components
- [ ] Implement change detection

**Deliverable**: Schema available at query time with < 10ms latency

### Phase 3: Graph Builder Enhancement (2 weeks)

**Goal**: Use schema to build richer graph nodes

- [ ] Read Filterable_Fields from schema
- [ ] Store all filterable values as node attributes
- [ ] Validate against picklist values
- [ ] Re-index all objects

**Deliverable**: Graph nodes with complete filterable attributes

### Phase 4: KB Metadata Enhancement (1-2 weeks)

**Goal**: Add filterable fields to KB chunk metadata

- [ ] Update chunk sync to include filterable fields
- [ ] Add numeric and date fields to metadata
- [ ] Re-sync all chunks

**Deliverable**: KB chunks with filterable metadata for all configured fields

### Phase 5: Schema-Aware Query Decomposer (3-4 weeks)

**Goal**: Query decomposition using schema context

- [ ] Implement SchemaAwareQueryDecomposer
- [ ] Build schema context for LLM prompts
- [ ] Implement value matching/validation
- [ ] Add date expression parsing
- [ ] Integration tests with real queries

**Deliverable**: 85%+ accuracy on test query set

### Phase 6: Hybrid Query Executor (2-3 weeks)

**Goal**: Execute decomposed queries on graph + KB

- [ ] Implement graph node attribute filtering
- [ ] Implement traversal with filters at each hop
- [ ] Merge graph + vector results
- [ ] Performance optimization

**Deliverable**: E2E query execution with < 2s latency

### Phase 7: Admin UI (Optional, 4-6 weeks)

**Goal**: LWC for configuration management

- [ ] Object selection component
- [ ] Field classification component
- [ ] Relationship mapping component
- [ ] Validation and preview
- [ ] Reindex trigger

**Deliverable**: Admin can configure search without editing metadata directly

---

## 9.2 POC Sprint: 1-Week Zero-Config Validation

Given this project is a POC connected to a sandbox environment, we can take an accelerated approach to validate the zero-config hypothesis before committing to the full implementation phases above.

### Sprint Goal

> Prove that auto-discovered schema enables accurate filtering in 1 week, without manual configuration.

### Sprint Overview

| Day | Focus | Deliverable |
|-----|-------|-------------|
| 1-2 | Schema Discovery Service | Lambda that auto-discovers and caches schema for all CRE objects |
| 2-3 | Graph Builder Update | Graph nodes populated with all filterable attributes from schema |
| 3-4 | Schema-Aware Decomposer | Query decomposition validated against schema picklist values |
| 4-5 | Graph Attribute Filtering | Filter on graph node attributes before vector search |
| 5-6 | Re-index with Schema | Property, Listing, Inquiry re-indexed with full attributes |
| 6-7 | Validation & Testing | 20 test queries validated for filter accuracy |

### Day 1-2: Schema Discovery Service

**Files to Create**:
```
lambda/
└── schema_discovery/
    ├── index.py           # Main handler
    ├── discoverer.py      # SF API integration
    ├── cache.py           # DynamoDB caching
    └── test_discovery.py  # Unit tests
```

**Core Implementation**:
```python
# lambda/schema_discovery/discoverer.py

class SchemaDiscoverer:
    """Auto-discover Salesforce object schema."""

    CRE_OBJECTS = [
        "ascendix__Property__c",
        "ascendix__Deal__c",
        "ascendix__Availability__c",
        "ascendix__Listing__c",
        "ascendix__Inquiry__c",
        "ascendix__Lease__c",
        "Account",
        "Contact"
    ]

    def discover_object(self, sobject: str) -> ObjectSchema:
        """
        Discover complete schema for an object using SF Describe API.
        Returns classified fields: filterable, numeric, date, relationships.
        """
        describe = self.sf_client.describe(sobject)

        schema = ObjectSchema(api_name=sobject, label=describe['label'])

        for field in describe['fields']:
            if field['type'] in ('picklist', 'multipicklist'):
                schema.filterable.append({
                    'name': field['name'],
                    'label': field['label'],
                    'values': [pv['value'] for pv in field['picklistValues'] if pv['active']]
                })
            elif field['type'] in ('double', 'currency', 'int', 'percent'):
                schema.numeric.append({
                    'name': field['name'],
                    'label': field['label']
                })
            elif field['type'] in ('date', 'datetime'):
                schema.date.append({
                    'name': field['name'],
                    'label': field['label']
                })
            elif field['type'] == 'reference' and field['referenceTo']:
                schema.relationships.append({
                    'name': field['name'],
                    'target': field['referenceTo'][0],
                    'relationshipName': field['relationshipName']
                })

        return schema

    def discover_all(self) -> Dict[str, ObjectSchema]:
        """Discover and cache schema for all CRE objects."""
        schemas = {}
        for obj in self.CRE_OBJECTS:
            schemas[obj] = self.discover_object(obj)
            self.cache.put(obj, schemas[obj])
        return schemas
```

**DynamoDB Table**: `schema_cache`
- Partition Key: `objectApiName`
- Attributes: `schema` (JSON), `discoveredAt`, `ttl`

**Success Criteria**:
- [ ] All 8 objects discovered successfully
- [ ] Picklist values extracted for all filterable fields
- [ ] Schema cached and retrievable in < 10ms

---

### Day 2-3: Graph Builder Update

**Files to Modify**:
```
lambda/
└── graph_builder/
    ├── index.py           # Update to use schema
    └── schema_loader.py   # Load schema from cache
```

**Core Change**:
```python
# lambda/graph_builder/index.py

def build_node(record: Dict, object_type: str) -> Dict:
    """Build node with ALL filterable fields as attributes."""

    # Load schema from cache
    schema = schema_cache.get(object_type)

    attributes = {}

    # Auto-populate ALL filterable fields
    for field in schema.filterable:
        value = record.get(field['name'])
        if value:
            attributes[field['name']] = value

    # Auto-populate ALL numeric fields
    for field in schema.numeric:
        value = record.get(field['name'])
        if value is not None:
            attributes[field['name']] = float(value)

    # Auto-populate key date fields
    for field in schema.date:
        value = record.get(field['name'])
        if value:
            attributes[field['name']] = value

    return {
        "nodeId": record["Id"],
        "type": object_type,
        "displayName": record.get("Name", record["Id"]),
        "attributes": attributes
    }
```

**Before vs After**:
```json
// BEFORE: Empty attributes
{
  "nodeId": "a0afk000000PvnfAAC",
  "type": "ascendix__Property__c",
  "displayName": "Preston Park Financial Center",
  "attributes": {}
}

// AFTER: Full filterable attributes
{
  "nodeId": "a0afk000000PvnfAAC",
  "type": "ascendix__Property__c",
  "displayName": "Preston Park Financial Center",
  "attributes": {
    "ascendix__PropertyClass__c": "A",
    "ascendix__PropertySubType__c": "Office",
    "ascendix__City__c": "Plano",
    "ascendix__State__c": "TX",
    "ascendix__BuildingStatus__c": "Existing",
    "ascendix__TotalBuildingArea__c": 250000,
    "LastActivityDate": "2025-11-15"
  }
}
```

**Success Criteria**:
- [ ] Graph nodes have all picklist values as attributes
- [ ] Numeric fields stored as numbers (for comparisons)
- [ ] Date fields stored in queryable format

---

### Day 3-4: Schema-Aware Query Decomposer

**Files to Create/Modify**:
```
lambda/
└── retrieve/
    ├── schema_decomposer.py   # NEW: Schema-aware decomposition
    └── prompts/
        └── schema_decomposition.yaml  # UPDATE: Add schema context
```

**Core Implementation**:
```python
# lambda/retrieve/schema_decomposer.py

class SchemaAwareDecomposer:
    """Decompose queries using schema for validation."""

    def decompose(self, query: str) -> StructuredQuery:
        # 1. Detect target entity from query
        target = self._detect_target_entity(query)

        # 2. Load schema for target (and related objects)
        schema = self.schema_cache.get(target)
        related_schemas = self._get_related_schemas(schema)

        # 3. Build schema context for LLM
        context = self._build_schema_context(schema, related_schemas)

        # 4. LLM decomposition with schema awareness
        decomposition = self._llm_decompose(query, context)

        # 5. Validate and normalize values
        validated = self._validate_values(decomposition, schema)

        return validated

    def _build_schema_context(self, schema: ObjectSchema, related: List) -> str:
        """Build prompt context with field names and valid values."""
        return f"""
Target Object: {schema.label} ({schema.api_name})

Filterable Fields (use exact values):
{self._format_filterable_fields(schema.filterable)}

Numeric Fields (support >, <, >=, <=, range):
{self._format_numeric_fields(schema.numeric)}

Date Fields (support relative: "last 30 days", "this month"):
{self._format_date_fields(schema.date)}

Relationships (can traverse to):
{self._format_relationships(schema.relationships)}

Related Objects:
{self._format_related_schemas(related)}
"""

    def _validate_values(self, decomposition: Dict, schema: ObjectSchema) -> Dict:
        """Validate extracted values against picklist options."""
        for field_name, value in decomposition.get('filters', {}).items():
            field_schema = schema.get_field(field_name)
            if field_schema and field_schema.get('values'):
                # Fuzzy match to valid value
                matched = self._fuzzy_match(value, field_schema['values'])
                decomposition['filters'][field_name] = matched

        return decomposition
```

**Schema Context Example** (sent to LLM):
```
Target Object: Property (ascendix__Property__c)

Filterable Fields (use exact values):
- PropertyClass: A+, A, B, C
- PropertySubType: Office, Retail, Industrial, Multifamily, ...
- City: (text field)
- BuildingStatus: Proposed, Under Construction, Existing, Demolished

Numeric Fields (support >, <, >=, <=):
- TotalBuildingArea (SF)
- YearBuilt
- Floors

Relationships (can traverse to):
- Availability (via ascendix__Property__c)
- Listing (via ascendix__Property__c)
- Deal (via ascendix__Property__c)
```

**Success Criteria**:
- [ ] "Class A" correctly maps to "A" in PropertyClass
- [ ] "retail" correctly maps to "Retail" in PropertySubType
- [ ] Invalid values flagged or best-matched

---

### Day 4-5: Graph Attribute Filtering

**Files to Modify**:
```
lambda/
└── retrieve/
    ├── index.py              # UPDATE: Add graph filtering step
    └── graph_filter.py       # NEW: Query graph by attributes
```

**Core Implementation**:
```python
# lambda/retrieve/graph_filter.py

class GraphAttributeFilter:
    """Filter graph nodes by attribute values."""

    def query_by_attributes(
        self,
        object_type: str,
        filters: Dict[str, Any]
    ) -> List[str]:
        """
        Query graph nodes matching attribute filters.
        Returns list of matching node IDs.
        """
        # Build DynamoDB filter expression
        filter_expr = Attr('type').eq(object_type)

        for field, value in filters.items():
            attr_path = f'attributes.{field}'

            if isinstance(value, dict):
                # Numeric comparison: {"$gt": 1000000}
                if '$gt' in value:
                    filter_expr &= Attr(attr_path).gt(value['$gt'])
                elif '$lt' in value:
                    filter_expr &= Attr(attr_path).lt(value['$lt'])
                elif '$gte' in value:
                    filter_expr &= Attr(attr_path).gte(value['$gte'])
                elif '$lte' in value:
                    filter_expr &= Attr(attr_path).lte(value['$lte'])
            else:
                # Exact match
                filter_expr &= Attr(attr_path).eq(value)

        # Scan with filter (for POC; would use GSI in production)
        response = self.nodes_table.scan(FilterExpression=filter_expr)

        return [item['nodeId'] for item in response['Items']]
```

**Integration in Retrieve Lambda**:
```python
# lambda/retrieve/index.py

def retrieve(query: str, user_context: Dict) -> List[Dict]:
    # 1. Decompose query with schema awareness
    decomposition = schema_decomposer.decompose(query)

    # 2. If we have filters, query graph FIRST
    candidate_ids = None
    if decomposition.filters:
        candidate_ids = graph_filter.query_by_attributes(
            object_type=decomposition.target,
            filters=decomposition.filters
        )

        if not candidate_ids:
            return []  # No matches for filters

        logger.info(f"Graph filter: {len(candidate_ids)} candidates")

    # 3. Vector search (with ID filter if we have candidates)
    kb_filter = {"sobject": decomposition.target}
    if candidate_ids:
        kb_filter["recordId"] = {"$in": candidate_ids}

    results = bedrock_kb.search(query=query, filter=kb_filter)

    # 4. Continue with existing flow...
    return results
```

**Query Flow**:
```
User: "retail properties in Dallas"

1. Decompose: {target: "Property", filters: {PropertySubType: "Retail", City: "Dallas"}}

2. Graph Filter:
   SELECT nodeId FROM graph_nodes
   WHERE type = 'ascendix__Property__c'
   AND attributes.PropertySubType = 'Retail'
   AND attributes.City = 'Dallas'
   → Returns: [id1, id2, id3] (only 3 properties match)

3. Vector Search:
   Search KB WHERE recordId IN [id1, id2, id3]
   → Returns chunks for only those 3 properties

4. Result: ONLY retail properties in Dallas
```

**Success Criteria**:
- [ ] Graph filter returns only matching node IDs
- [ ] Vector search is scoped to filtered IDs
- [ ] "retail in Dallas" returns 0 Office properties

---

### Day 5-6: Re-index with Schema

**Commands**:
```bash
# 1. Deploy updated graph builder
cd /path/to/salesforce-ai-search-poc
npx cdk deploy SalesforceAISearch-Ingestion-dev

# 2. Trigger re-index for Property (largest object)
sf apex run -o ascendix-beta-sandbox -f scripts/trigger_property_export.apex

# 3. Verify graph nodes have attributes
aws dynamodb scan \
  --table-name graph-nodes-dev \
  --filter-expression "begins_with(#t, :prefix)" \
  --expression-attribute-names '{"#t": "type"}' \
  --expression-attribute-values '{":prefix": {"S": "ascendix__Property"}}' \
  --max-items 5

# 4. Repeat for Listing, Inquiry if time permits
```

**Verification Query**:
```python
# Verify Property nodes have attributes
response = dynamodb.scan(
    TableName='graph-nodes-dev',
    FilterExpression='#t = :type',
    ExpressionAttributeNames={'#t': 'type'},
    ExpressionAttributeValues={':type': {'S': 'ascendix__Property__c'}},
    Limit=5
)

for item in response['Items']:
    print(f"Node: {item['displayName']}")
    print(f"Attributes: {json.dumps(item.get('attributes', {}), indent=2)}")
```

**Success Criteria**:
- [ ] Property nodes have PropertyClass, PropertySubType, City attributes
- [ ] Numeric fields stored as numbers
- [ ] At least 100 Property nodes re-indexed

---

### Day 6-7: Validation & Testing

**Test Suite**:
```python
# test_automation/validate_zero_config.py

TEST_QUERIES = [
    # Filter accuracy tests
    {
        "query": "retail properties in Dallas",
        "expected_filters": {"PropertySubType": "Retail"},
        "must_not_contain": ["Office", "Industrial"]
    },
    {
        "query": "Class A office buildings",
        "expected_filters": {"PropertyClass": "A", "PropertySubType": "Office"},
        "must_not_contain": ["Class B", "Class C", "Retail"]
    },
    {
        "query": "properties over 100,000 square feet",
        "expected_filters": {"TotalBuildingArea": {"$gt": 100000}},
        "validate": lambda r: all(p.get("TotalBuildingArea", 0) > 100000 for p in r)
    },

    # Relationship + filter tests
    {
        "query": "Class A office with available space",
        "expected_filters": {"PropertyClass": "A", "PropertySubType": "Office"},
        "expected_traversal": "Availability"
    },
    {
        "query": "active listings for retail properties",
        "expected_target": "Listing",
        "expected_filters": {"Status": "Active", "PropertyType": "Retail"}
    },

    # Inquiry tests
    {
        "query": "inquiries from LoopNet",
        "expected_target": "Inquiry",
        "expected_filters": {"InquirySource": "LoopNet"}
    },
    {
        "query": "inquiries for Class A office space",
        "expected_target": "Inquiry",
        "expected_filters": {"PropertyClass": "A", "PropertyType": "Office"}
    },

    # Value normalization tests
    {
        "query": "class a properties",  # lowercase
        "expected_filters": {"PropertyClass": "A"}  # normalized to "A"
    },
    {
        "query": "RETAIL properties",  # uppercase
        "expected_filters": {"PropertySubType": "Retail"}  # normalized
    },

    # Numeric comparison tests
    {
        "query": "listings under $5 million",
        "expected_filters": {"AskingPrice": {"$lt": 5000000}}
    },
]

def run_validation():
    results = {"passed": 0, "failed": 0, "errors": []}

    for test in TEST_QUERIES:
        try:
            # Call search API
            response = call_search_api(test["query"])

            # Validate decomposition
            decomposition = response.get("decomposition", {})
            if test.get("expected_filters"):
                assert decomposition.get("filters") == test["expected_filters"]

            # Validate results don't contain excluded values
            if test.get("must_not_contain"):
                for record in response.get("records", []):
                    for excluded in test["must_not_contain"]:
                        assert excluded not in str(record), f"Found excluded: {excluded}"

            results["passed"] += 1
            print(f"✓ {test['query']}")

        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"query": test["query"], "error": str(e)})
            print(f"✗ {test['query']}: {e}")

    print(f"\nResults: {results['passed']}/{len(TEST_QUERIES)} passed")
    return results
```

**Success Criteria**:
- [ ] 18/20 queries pass (90% accuracy)
- [ ] Zero false positives on filter queries (100% precision)
- [ ] Value normalization works for case variations

---

### Sprint Success Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Schema Discovery | 100% | All 8 objects discovered with fields classified |
| Filter Accuracy | 100% | "retail in Dallas" returns ONLY retail |
| Value Normalization | 90% | "class a" maps to "A", "RETAIL" maps to "Retail" |
| Query Accuracy | 90% | 18/20 test queries return correct results |
| Latency | < 3s | End-to-end query response time |

### Sprint Deliverables

1. **Schema Discovery Lambda** - Auto-discovers and caches schema
2. **Updated Graph Builder** - Populates node attributes from schema
3. **Schema-Aware Decomposer** - Validates queries against schema
4. **Graph Attribute Filter** - Filters nodes before vector search
5. **Validation Test Suite** - 20 test queries with expected results
6. **Results Documentation** - What worked, what didn't, next steps

---

### Post-Sprint Decision

After the 1-week sprint, we'll have data to decide:

| If Sprint Succeeds | If Sprint Fails |
|--------------------|-----------------|
| Proceed with full implementation (Phases 1-7) | Identify blockers and adjust approach |
| Expand to all CRE objects | Consider hybrid manual+auto config |
| Build admin refinement UI | Investigate alternative architectures |

---

## 10. Success Criteria

### 10.1 Functional Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Query decomposition accuracy | 85%+ | Manual review of 100 test queries |
| Filter accuracy | 95%+ | "retail in Dallas" returns only retail |
| Relationship traversal | 90%+ | Multi-hop queries return correct results |
| Temporal queries | 90%+ | Date-based filters work correctly |
| Configuration coverage | 100% | All CRE objects configurable |

### 10.2 Performance Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Query latency (p95) | < 2.5s | 2-hop relationship queries |
| Schema lookup | < 10ms | Cached schema retrieval |
| Reindex time | < 30 min | Full reindex of 10K records |
| Graph node query | < 100ms | Filter on node attributes |

### 10.3 Usability Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| Admin configuration time | < 30 min | Configure new object end-to-end |
| Zero code changes | 100% | Standard configurations require no code |
| Documentation coverage | 100% | All features documented |

---

## 11. Automatic Schema Discovery

### 11.1 Discovery Capability

The Salesforce Describe API and Tooling API provide complete metadata about objects, fields, and relationships. This enables **automatic schema discovery** without manual configuration.

#### API Commands for Discovery

```bash
# List all queryable/searchable objects
sf data query --use-tooling-api \
  --query "SELECT QualifiedApiName, Label, IsQueryable, IsSearchable
           FROM EntityDefinition
           WHERE IsCustomizable = true"

# Get complete field metadata for an object
sf sobject describe --sobject ascendix__Property__c --json

# Get relationship information
sf data query --use-tooling-api \
  --query "SELECT ChildSobjectId, FieldId FROM RelationshipInfo
           WHERE ChildSobjectId = 'Property'"
```

#### What the Describe API Returns

For each object, we can extract:

```json
{
  "object": "ascendix__Property__c",
  "label": "Property",

  "text_fields": [
    {"name": "Name", "label": "Property Name", "type": "string"},
    {"name": "ascendix__Description__c", "label": "Description", "type": "textarea"}
  ],

  "picklist_fields": [
    {
      "name": "ascendix__PropertyClass__c",
      "label": "Property Class",
      "values": ["A+", "A", "B", "C"]
    },
    {
      "name": "ascendix__PropertySubType__c",
      "label": "Property Sub Type",
      "values": ["Office", "Retail", "Industrial", "Multifamily", ...]
    }
  ],

  "numeric_fields": [
    {"name": "ascendix__TotalBuildingArea__c", "label": "Total Building Area (SF)", "type": "double"},
    {"name": "ascendix__AverageRent__c", "label": "Average Rent /SF", "type": "currency"}
  ],

  "date_fields": [
    {"name": "LastActivityDate", "label": "Last Activity Date", "type": "date"},
    {"name": "ascendix__ExpansionDate__c", "label": "Expansion Date", "type": "date"}
  ],

  "lookup_fields": [
    {"name": "ascendix__Market__c", "label": "Market", "referenceTo": "ascendix__Geography__c"},
    {"name": "ascendix__SubMarket__c", "label": "Sub Market", "referenceTo": "ascendix__Geography__c"},
    {"name": "ascendix__OwnerLandlord__c", "label": "Owner/Landlord", "referenceTo": "Account"}
  ],

  "child_relationships": [
    {"childObject": "ascendix__Availability__c", "field": "ascendix__Property__c"},
    {"childObject": "ascendix__Deal__c", "field": "ascendix__Property__c"}
  ]
}
```

### 11.2 Auto-Discovery vs. Manual Configuration

| Aspect | Auto-Discovery | Manual Config | Recommendation |
|--------|----------------|---------------|----------------|
| **Which objects to index** | All with IsSearchable=true | Admin selects | Auto + allow disable |
| **Text fields for search** | All string/textarea | Admin selects | Auto all, weight important ones |
| **Filterable fields** | All picklists + filterable=true | Admin selects | Auto all picklists |
| **Picklist values** | Direct from API | N/A | Always auto |
| **Numeric fields** | All double/currency/int | Admin selects | Auto all |
| **Date fields** | All date/datetime | Admin selects | Auto all |
| **Relationships** | All lookups + child relationships | Admin selects important | Auto, prune low-value |
| **Display name field** | Name > Subject > Title | Admin override | Auto with fallback chain |

### 11.3 What Cannot Be Auto-Discovered

| Aspect | Why Manual Input Needed |
|--------|-------------------------|
| **Business importance** | API doesn't know which objects/fields are important to users |
| **Synonyms/aliases** | "Class A" vs "A" vs "Premium" - business language |
| **Field semantics** | API knows it's a picklist, not that "Office" means commercial office space |
| **Traversal priority** | Which relationships are most useful for queries |
| **Index exclusions** | Fields that should NOT be searchable (sensitive data) |

### 11.4 Recommended Hybrid Approach

```
┌─────────────────────────────────────────────────────────────────────┐
│                     ZERO-CONFIG BASELINE                             │
│                                                                      │
│  1. Auto-discover all objects with IsSearchable=true                │
│  2. Auto-classify fields by type:                                    │
│     - string/textarea → Searchable (vector index)                   │
│     - picklist → Filterable (graph node attr + KB metadata)         │
│     - double/currency → Numeric (comparisons/aggregations)          │
│     - date/datetime → Date (temporal queries)                       │
│     - reference → Relationship (graph edges)                        │
│  3. Auto-extract all picklist values                                │
│  4. Auto-build graph from all lookup relationships                  │
│                                                                      │
│  Result: Working search with NO configuration required               │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     OPTIONAL ADMIN REFINEMENT                        │
│                                                                      │
│  • Disable objects that shouldn't be searchable                     │
│  • Boost/demote specific fields for relevance                       │
│  • Add synonyms for picklist values                                 │
│  • Configure traversal depth per relationship                       │
│  • Exclude sensitive fields from indexing                           │
│  • Set display name field override                                  │
│                                                                      │
│  Result: Optimized search tailored to org needs                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 11.5 Auto-Discovery Implementation

```python
class SchemaDiscoveryService:
    """
    Auto-discovers Salesforce schema for AI Search configuration.
    """

    def discover_object_schema(self, sobject: str) -> ObjectSchema:
        """
        Discover complete schema for an object using Describe API.
        """
        # Call Salesforce Describe API
        describe_result = self.sf_client.sobject_describe(sobject)

        schema = ObjectSchema(
            api_name=describe_result['name'],
            label=describe_result['label'],
            is_searchable=describe_result.get('searchable', True),
            is_queryable=describe_result.get('queryable', True),
        )

        for field in describe_result['fields']:
            field_type = field['type']

            if field_type in ('string', 'textarea'):
                schema.searchable_fields.append(FieldConfig(
                    name=field['name'],
                    label=field['label'],
                    type='searchable'
                ))

            elif field_type in ('picklist', 'multipicklist'):
                schema.filterable_fields.append(FieldConfig(
                    name=field['name'],
                    label=field['label'],
                    type='filterable',
                    values=[pv['value'] for pv in field['picklistValues'] if pv['active']]
                ))

            elif field_type in ('double', 'currency', 'int', 'percent'):
                schema.numeric_fields.append(FieldConfig(
                    name=field['name'],
                    label=field['label'],
                    type='numeric'
                ))

            elif field_type in ('date', 'datetime'):
                schema.date_fields.append(FieldConfig(
                    name=field['name'],
                    label=field['label'],
                    type='date'
                ))

            elif field_type == 'reference' and field['referenceTo']:
                schema.relationships.append(RelationshipConfig(
                    field_name=field['name'],
                    label=field['label'],
                    target_object=field['referenceTo'][0],
                    relationship_name=field['relationshipName']
                ))

        # Also get child relationships
        for child_rel in describe_result.get('childRelationships', []):
            if child_rel.get('relationshipName'):
                schema.child_relationships.append(ChildRelationshipConfig(
                    child_object=child_rel['childSObject'],
                    field=child_rel['field'],
                    relationship_name=child_rel['relationshipName']
                ))

        return schema

    def discover_all_objects(self) -> List[ObjectSchema]:
        """
        Discover schema for all searchable custom objects.
        """
        # Query EntityDefinition for searchable objects
        entities = self.tooling_api.query("""
            SELECT QualifiedApiName, Label, IsSearchable, IsQueryable
            FROM EntityDefinition
            WHERE IsCustomizable = true
            AND IsSearchable = true
        """)

        schemas = []
        for entity in entities:
            schema = self.discover_object_schema(entity['QualifiedApiName'])
            schemas.append(schema)

        return schemas
```

### 11.6 Property Object Discovery Example

Actual output from `sf sobject describe --sobject ascendix__Property__c`:

| Category | Count | Examples |
|----------|-------|----------|
| **Text fields** | 38 | Name, Description, LocationDescription, Comments |
| **Picklist fields** | 26 | PropertyClass (A+, A, B, C), PropertySubType (Office, Retail...), BuildingStatus |
| **Numeric fields** | ~100 | TotalBuildingArea, AverageRent, Floors, ParkingTotal |
| **Date fields** | 8 | LastActivityDate, ExpansionDate, EnergyStarCertification |
| **Lookup fields** | 19 | Market, SubMarket, OwnerLandlord, PropertyManager, Developer |
| **Child relationships** | 10+ | Availability, Deal, Lease, Listing, Floor |

**This means**: For the Property object alone, we can auto-generate a complete search configuration with:
- 38 text fields for semantic search
- 26 filterable dimensions with all valid values
- ~100 numeric fields for comparisons
- 8 date fields for temporal queries
- 19 parent relationships + 10+ child relationships for graph traversal

---

## 12. Open Questions

### 12.1 Architecture Questions

1. **Should we use IndexConfiguration__mdt or a custom object for configuration?**
   - Custom metadata is deployable but harder to update frequently
   - Custom object allows real-time updates but less portable

2. **How do we handle Submarket/Geography hierarchies?**
   - "Dallas CBD" is a Submarket, not a City
   - Need Geography__c → Submarket → City hierarchy?

3. **Should picklist values be cached or fetched on-demand?**
   - Cached = faster but can be stale
   - On-demand = always current but adds latency

### 12.2 Integration Questions

4. **What's the priority: standalone UI or Ascendix Search integration?**
   - Standalone is faster to build
   - Integration provides unified experience

5. **Should configuration changes trigger automatic reindex?**
   - Automatic = seamless but resource-intensive
   - Manual = controlled but requires admin action

### 12.3 Scope Questions

6. **Which objects should be in the initial rollout?**
   - CRE: Property, Deal, Availability, Listing, Inquiry, Lease, Sale
   - Standard: Account, Contact, Opportunity, Case

7. **What's the maximum traversal depth we need to support?**
   - Current: 3 hops
   - Complex queries might need more?

---

## Appendix

### A.1 Example Queries and Expected Decomposition

| Query | Target | Filters | Traversals | Date Filters |
|-------|--------|---------|------------|--------------|
| "retail properties in Dallas" | Property | SubType=Retail, City=Dallas | - | - |
| "Class A office with available space" | Property | Class=A, SubType=Office | →Availability(Status=Available) | - |
| "deals over $1M" | Deal | GrossFee > 1000000 | - | - |
| "leases expiring in 6 months" | Lease | - | - | Expiration < +6mo |
| "deals for Preston Park Financial" | Deal | - | →Property(Name=Preston Park) | - |
| "accounts in Houston with open opportunities" | Account | City=Houston | →Opportunity(Stage!=Closed) | - |
| "properties with no activity in 30 days" | Property | - | - | LastActivity < -30d |
| "active listings for office properties" | Listing | Status=Active, PropertyType=Office | - | - |
| "inquiries from LoopNet this month" | Inquiry | InquirySource=LoopNet | - | CreatedDate = this month |
| "listings with pending sales over $5M" | Listing | Status=Sale Pending, AskingPrice > 5M | - | - |
| "inquiries that converted to deals" | Inquiry | - | →ConvertedDeal (exists) | - |
| "properties with active listings and inquiries" | Property | - | →Listing(Status=Active), →Inquiry | - |

### A.2 CRE Object Relationship Map

```
                           ┌─────────────┐
                           │   Account   │
                           │  (Client)   │
                           └──────┬──────┘
                                  │ Client__c, OwnerLandlord__c
                                  ▼
     ┌─────────────┐       ┌─────────────┐       ┌─────────────┐
     │  Property   │◄──────│    Deal     │──────►│   Contact   │
     │             │       │             │       │  (Tenant)   │
     └──────┬──────┘       └─────────────┘       └─────────────┘
            │                     ▲
            │ Property__c         │ OriginatingDeal__c, ConvertedDeal__c
            ▼                     │
     ┌─────────────┐       ┌──────┴──────┐       ┌─────────────┐
     │ Availability│       │   Listing   │◄──────│   Inquiry   │
     │             │       │             │       │             │
     └──────┬──────┘       └──────┬──────┘       └─────────────┘
            │                     │                     │
            │                     │ Property__c         │ Property__c
            └──────────┬──────────┘                     │ Availability__c
                       ▼                                │ Listing__c
                ┌─────────────┐                         │
                │    Lease    │                         │
                │             │◄────────────────────────┘
                └─────────────┘
                       │
                       │ Property__c
                       ▼
                ┌─────────────┐
                │    Sale     │
                │             │
                └─────────────┘
```

### A.3 Complete CRE Objects Summary

| Object | Key Picklists | Key Numerics | Key Relationships |
|--------|---------------|--------------|-------------------|
| **Property** | PropertyClass, PropertySubType, BuildingStatus | TotalArea, YearBuilt, Floors | Market, SubMarket, OwnerLandlord |
| **Deal** | Status, SalesStage, DealType | GrossFeeAmount, SquareFeet | Property, Client, Tenant |
| **Availability** | Status, UseType, LeaseType | AvailableArea, AskingRate | Property, Listing |
| **Listing** | Status, PropertyType, UseType, SaleType | AskingPrice, SalePrice, VacantArea | Property, OwnerLandlord, OriginatingDeal |
| **Inquiry** | InquirySource, PropertyType, PropertyClass | AreaMin/Max, PriceMin/Max, RentMin/Max | Property, Availability, Listing, ConvertedDeal |
| **Lease** | Status, LeaseType | MonthlyRent, TermMonths | Property, Tenant |
| **Sale** | Status, SaleType | SalePrice, PricePerSF | Property, Buyer, Seller |

### A.4 Reference: Ascendix Search Field Configuration

From sandbox analysis, Ascendix Search stores field configuration in `SearchSetting__c`:

```json
{
  "name": "Account",
  "isSearchable": true,
  "isMapEnabled": true,
  "isAdHocListEnabled": true,
  "fields": [],  // Could be populated with field config
  "mapData": {
    "objectName": "Account",
    "longitude": "BillingLongitude",
    "latitude": "BillingLatitude",
    "geolocation": "BillingAddress"
  }
}
```

This structure could be extended to include AI search field types.

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2025-11-28 | AI Search Team | Initial draft |

---

## Next Steps

1. **Review and refine** this PRD with stakeholders
2. **Prioritize** integration option (A, B, or C)
3. **Define** initial object/field scope
4. **Begin Phase 1** implementation
