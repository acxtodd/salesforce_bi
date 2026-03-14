# Product Requirement Document (Mini): Augmented Schema Discovery

**Date:** December 10, 2025
**Status:** DRAFT
**Feature:** Augmented Schema Discovery (Hybrid Zero-Config + Signal Harvesting)

---

## 1. Executive Summary

The current "Zero Config" architecture relies on the Salesforce Describe API to discover objects and fields. While this provides a complete map of *what exists*, it lacks the semantic context of *what matters*. The system currently "guesses" field relevance, often treating obscure system fields as equal to critical business drivers like `RecordTypeId` or `PropertyClass`.

**The Opportunity:** Ascendix Search (`ascendix_search__*` objects) contains a rich repository of user intent—Saved Searches, Ad-Hoc Lists, and Views—configured by admins and users. These artifacts explicitly define the "Golden Paths": priority fields, driver relationships, and meaningful sort orders.

**The Solution:** Implement **Augmented Schema Discovery**. We will maintain the "Zero Config" promise (no manual setup required for *our* tool) by autonomously "harvesting" these existing configurations to bias and boost our schema understanding. We get the accuracy of a configured system with the flexibility of a zero-config one.

---

## 2. Problem Statement

*   **Signal-to-Noise Ratio:** A Salesforce object like `Property` may have 200 fields. Describe API returns all 200. Zero Config treats them equally. Users only care about 10.
*   **Relationship Ambiguity:** A `Property` might link to `Account` via 5 different lookup fields (`Manager`, `Owner`, `Developer`, etc.). Zero Config doesn't know which relationship is the primary "parent" relationship users filter by.
*   **Vocabulary Gaps:** To know that "Plano" is a city, Zero Config must scan data. Ascendix Search configs already contain "City = Plano" as a filter, providing an instant, high-confidence vocabulary seed.

---

## 3. Proposed Solution: The "Hybrid" Model

We propose a **two-layer discovery process**:

1.  **Base Layer (Standard Discovery):**
    *   **Source:** Salesforce Describe API & Global Describe.
    *   **Function:** Maps the raw physical schema (Objects, Fields, Types).
    *   **Role:** Ensures *coverage*. Guarantees the system can answer *any* query, even those never configured in Ascendix Search.

2.  **Boosting Layer (Signal Harvesting):**
    *   **Source:** `ascendix_search__Search__c` (Saved Searches) and `ascendix_search__AdHocList__c`.
    *   **Function:** Parses JSON templates to extract usage patterns.
    *   **Role:** Provides *relevance*. Biases the Planner to prefer fields/paths that have been explicitly saved by humans.

---

## 4. Scope of Harvesting

We will target the following artifacts from the `ascendix_search__` namespace:

### 4.1. Saved Searches (`ascendix_search__Search__c`)
*   **Filter Fields:** Fields appearing in `fieldsList` (criteria) are **High Relevance** (Score: 10).
    *   *Example:* `RecordTypeId`, `ascendix__PropertyClass__c`, `ascendix__City__c`.
*   **Result Columns:** Fields appearing in `resultColumns` are **Medium Relevance** (Score: 5).
    *   *Example:* `ascendix__TotalAvailableArea__c`, `Name`.
*   **Relationships:** Paths defined in `sectionsList[].relationship` (e.g., `ascendix__Property__r`) identify **Primary Graph Edges**.
*   **Sort Order:** Fields with `isSortable: true` are preferred candidates for default sorting.
*   **Vocabulary Seeds:** Extract explicit values (e.g., `"value": "Office"`, `"value": "Plano"`) to seed the Vocabulary Cache.

### 4.2. Ad-Hoc Lists (`ascendix_search__AdHocList__c`)
*   *(Investigation Pending)* Similar structure to Saved Searches; provides additional signals on user-grouped datasets.

### 4.3. Standard Salesforce ListViews (REST API)

ListViews define the default result columns and sort order for each object. These are admin-configured and represent the most commonly viewed fields.

**API Endpoint:**
```
GET /services/data/v59.0/sobjects/{objectApiName}/listviews/{listviewId}/describe
```

**Discovery Query (find ListViews for an object):**
```sql
SELECT Id, DeveloperName, Name, SobjectType
FROM ListView
WHERE SobjectType = 'ascendix__Sale__c'
```

**Response Structure:**
```json
{
  "columns": [
    {"fieldNameOrPath": "Name", "label": "Sale Name", "sortable": true},
    {"fieldNameOrPath": "ascendix__Property__r.Name", "label": "Property", "sortable": true},
    {"fieldNameOrPath": "ascendix__SaleDate__c", "label": "Sale Date", "sortable": true},
    {"fieldNameOrPath": "ascendix__SalePrice__c", "label": "Sale Price", "sortable": true}
  ],
  "orderBy": [{"fieldNameOrPath": "Name", "sortDirection": "ascending"}],
  "query": "SELECT Name, ascendix__Property__r.Name, ... FROM ascendix__Sale__c ORDER BY Name ASC"
}
```

**Signal Extraction:**
*   **Result Columns:** Fields in `columns[]` are **High Relevance** (Score: 8).
*   **Sortable Fields:** Fields with `sortable: true` are preferred for ordering.
*   **Cross-Object Paths:** Paths like `ascendix__Property__r.Name` indicate **Primary Relationships**.
*   **Default Sort:** `orderBy[]` fields define user-expected default ordering.

### 4.4. Search Layouts (REST API)

Search Layouts define which fields appear in global search results and lookup dialogs.

**API Endpoint:**
```
GET /services/data/v59.0/search/layout?q={objectApiName}
```

**Response Structure:**
```json
[{
  "objectType": "ascendix__Sale__c",
  "label": "Search Results",
  "searchColumns": [
    {"name": "Name", "label": "Sale Name", "field": "ascendix__Sale__c.Name"},
    {"name": "ascendix__Property__r.Name", "label": "Property", "field": "ascendix__Property__c.Name"},
    {"name": "ascendix__SaleDate__c", "label": "Sale Date", "format": "date"},
    {"name": "ascendix__SalePrice__c", "label": "Sale Price"}
  ]
}]
```

**Signal Extraction:**
*   **Search Columns:** Fields in `searchColumns[]` are **High Relevance** (Score: 10) for search disambiguation.
*   **Format Hints:** Fields with `"format": "date"` or `"format": "currency"` indicate type-specific handling.

### 4.5. Ascendix Search Settings (`ascendix_search__SearchSetting__c`)

This custom setting stores the list of searchable objects and their configurations as a JSON blob split across multiple records.

**Discovery Query:**
```sql
SELECT Name, ascendix_search__Value__c
FROM ascendix_search__SearchSetting__c
WHERE Name LIKE 'Selected Objects%'
ORDER BY Name
```

**Note:** The JSON is split across records (`Selected Objects`, `Selected Objects1`, ..., `Selected Objects8`). Concatenate `ascendix_search__Value__c` values in order before parsing.

**Response Structure (concatenated JSON):**
```json
[
  {
    "name": "ascendix__Sale__c",
    "isSearchable": true,
    "isMapEnabled": false,
    "isGeoEnabled": false,
    "isAdHocListEnabled": false,
    "fields": []  // Empty = uses OOTB defaults
  },
  {
    "name": "ascendix__Property__c",
    "isSearchable": true,
    "isMapEnabled": true,
    "fields": [
      {"name": "ascendix__City__c", "type": "string"},
      {"name": "ascendix__PropertyClass__c", "type": "picklist"}
    ]
  }
]
```

**Signal Extraction:**
*   **Searchable Objects:** Objects with `"isSearchable": true` are configured for Ascendix Search.
*   **Custom Field Config:** Non-empty `fields[]` indicates admin-configured priority fields (Score: 10).
*   **Empty Fields:** `"fields": []` means the object uses standard Salesforce field defaults (fall back to ListView/SearchLayout).
*   **Map/Geo Enabled:** Objects with `isMapEnabled: true` have location-based fields prioritized.

---

## 5. Implementation Strategy

### 5.1. Schema Cache Updates
We will extend the Schema Cache data structure to include a `relevance_score` and `usage_context` for each field.

```json
"fields": {
  "ascendix__City__c": {
    "type": "string",
    "label": "City",
    "relevance_score": 10,  // Boosted from default 1
    "usage_context": ["filter", "result_column"],
    "source_signals": ["Ascendix Search: Office Availabilities"]
  },
  "SystemModstamp": {
    "type": "datetime",
    "label": "System Modstamp",
    "relevance_score": 0,   // Default/Low
    "usage_context": []
  }
}
```

### 5.2. Discovery Logic (Lambda)
The Schema Discovery Lambda (`lambda/schema_discovery`) will be updated:

1.  **Step 1:** Perform standard Describe API fetch (existing logic).

2.  **Step 2:** Harvest signals from multiple sources (in priority order):

    | Source | API | Signal Type | Score Weight |
    |--------|-----|-------------|--------------|
    | SearchLayout | REST `/search/layout` | Search result columns | 10 |
    | ListView | REST `/listviews/{id}/describe` | Result columns, sort order | 8 |
    | Saved Searches | SOQL `ascendix_search__Search__c` | Filter fields, relationships | 10 |
    | SearchSetting | SOQL `ascendix_search__SearchSetting__c` | Searchable objects, custom fields | 5 |

3.  **Step 3:** Parse and aggregate signals:
    ```python
    # Pseudocode for signal aggregation
    field_scores = defaultdict(lambda: {"score": 0, "sources": []})

    # SearchLayout (highest weight for search columns)
    for col in search_layout.searchColumns:
        field_scores[col.name]["score"] += 10
        field_scores[col.name]["sources"].append("SearchLayout")

    # ListView (columns and sortable fields)
    for col in listview.columns:
        field_scores[col.fieldNameOrPath]["score"] += 8
        if col.sortable:
            field_scores[col.fieldNameOrPath]["score"] += 2  # Bonus for sortable
        field_scores[col.fieldNameOrPath]["sources"].append("ListView")

    # Saved Searches (filter fields get highest boost)
    for search in saved_searches:
        for field in search.template.fieldsList:
            field_scores[field.logicalName]["score"] += 10
            if field.value:  # Has explicit filter value
                vocab_seeds.append((field.logicalName, field.value))
    ```

4.  **Step 4:** Normalize scores (0-10 scale) and persist to Schema Cache.

5.  **Step 5:** Extract vocabulary seeds from filter values and persist to Vocab Cache.

### 5.3. Planner Integration
The Query Planner (`lambda/retrieve/planner.py`) will use these scores:
*   **Entity Linking:** When a term matches multiple fields (e.g., "Dallas" matches `City` and `BillingCity`), prefer the field with the higher `relevance_score`.
*   **Graph Traversal:** When traversing from `Availability` to `Property`, prioritize the relationship edge (`ascendix__Property__r`) found in saved searches over generic lookups.

---

## 6. Risks & Mitigations

| Risk | Mitigation |
| :--- | :--- |
| **Missing Ascendix Search:** Client doesn't have the package installed. | **Graceful Degradation:** The "Boosting Layer" is optional. If objects are missing, we log a warning and proceed with Base Layer (Standard Discovery) only. |
| **Empty/Stale Config:** Configs exist but are old/unused. | **Decay / Thresholds:** We can weight "Recent" saved searches higher than old ones. We rely on the Base Layer as the source of truth for *existence*, so we never query deleted fields. |
| **"Overfitting":** System ignores valid fields because they aren't in saved searches. | **Bias, Don't Block:** We never *hide* fields with low scores. We only prioritize high-score fields for ambiguity resolution. If a user explicitly asks for "System Modstamp", the Base Layer ensures we can still answer it. |

---

## 7. Success Metrics

*   **Planner Precision:** % of ambiguous queries resolving to the "correct" business field (e.g., "Office" mapping to `RecordType` vs `Industry`).
*   **Graph Efficiency:** Reduction in "dead-end" traversals by prioritizing known relationship paths.
*   **Setup Time:** Remains **Zero**. (No new manual config required from the user).

---

## Appendix A: Verified Signal Sources (December 2025)

The following data was extracted from the Ascendix Beta Sandbox on 2025-12-10.

### A.1. Searchable Objects (from `ascendix_search__SearchSetting__c`)

| Object | Searchable | Map Enabled | Custom Fields |
|--------|------------|-------------|---------------|
| Account | ✅ | ✅ | OOTB |
| ascendix__Availability__c | ✅ | ❌ | OOTB |
| Contact | ✅ | ✅ | OOTB |
| ascendix__Deal__c | ✅ | ❌ | OOTB |
| Lead | ✅ | ✅ | OOTB |
| ascendix__Lease__c | ✅ | ❌ | OOTB |
| ascendix__Property__c | ✅ | ❌ | OOTB |
| ascendix__Sale__c | ✅ | ❌ | OOTB |

### A.2. Saved Searches (from `ascendix_search__Search__c`)

| Name | Target Object | Key Filter Fields | Relationships |
|------|---------------|-------------------|---------------|
| Office Availabilities | ascendix__Availability__c | Name, Property, RecordType, AvailableArea, UseType | ascendix__Property__r |
| Class A office in Plano | ascendix__Property__c | PropertyClass="A+;A", City="Plano", RecordType | — |
| Deals for Class A office in Plano | ascendix__Deal__c | Name, RecordType, Client, SalesStage, GrossFeeAmount | ascendix__Property__r |

### A.3. Example: `ascendix__Sale__c` Field Prioritization

**From ListView "All Sales":**
```
Columns: Name, Property, ListingDate, ListingPrice, SaleDate, SalePrice
Sort: Name ASC
```

**From SearchLayout:**
```
SearchColumns: Name, Property, ListingDate, ListingPrice, SaleDate, SalePrice
```

**Derived Priority Fields:**

| Field | Score | Sources |
|-------|-------|---------|
| Name | 20 | ListView (10), SearchLayout (10) |
| ascendix__Property__c | 20 | ListView (10), SearchLayout (10) |
| ascendix__SaleDate__c | 18 | ListView (8+2 sortable), SearchLayout (10) |
| ascendix__SalePrice__c | 18 | ListView (8+2 sortable), SearchLayout (10) |
| ascendix__ListingDate__c | 18 | ListView (8+2 sortable), SearchLayout (10) |
| ascendix__ListingPrice__c | 18 | ListView (8+2 sortable), SearchLayout (10) |
| *(43 other fields)* | 0 | — |

