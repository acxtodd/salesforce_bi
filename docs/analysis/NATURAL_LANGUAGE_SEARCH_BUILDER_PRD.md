# Product Requirement Document: Natural Language Search Builder for Ascendix Search

**Date:** December 11, 2025
**Status:** DRAFT
**Author:** AI Search Team
**Scope:** Ascendix Search Natural Language Frontend & Configuration Automation

---

## 1. Executive Summary

Ascendix Search provides a powerful, highly configurable search interface for Salesforce, allowing users to build complex, multi-criteria queries across related objects (e.g., "Find Class A Office Properties with Availabilities > 5,000 SF"). However, the power of the UI can be overwhelming for users who simply want to ask a question.

This PRD proposes the **Natural Language Search Builder**, an agentic layer that translates plain English queries into the precise JSON configuration required by Ascendix Search. By automating the creation of `ascendix_search__Search__c` records, we can deliver a "Google-like" experience while leveraging the robust, native visualization and bulk-action capabilities of the existing Ascendix Search product.

To prevent database clutter ("Saved Search Sprawl"), we introduce the **"AI Scratchpad"** architecture, recycling a single search record per user for ad-hoc queries until they explicitly choose to save one.

---

## 2. Problem Statement

### 2.1 The Friction of Power
Ascendix Search allows for granular filtering (Radius search, related object criteria, boolean logic). Constructing these searches requires:
1.  Selecting the correct base object (e.g., Property vs. Deal).
2.  Navigating field pickers.
3.  Understanding data relationships (e.g., "City" is on Property, not Availability).
4.  Saving the search to view results.

### 2.2 The "Blank Page" Syndrome
Users often know *what* they want ("Show me retail in Plano") but struggle to map that to the specific fields (`ascendix__PropertySubType__c = 'Retail'`, `ascendix__City__c = 'Plano'`) required to build the query.

---

## 3. Proposed Solution

We will build a **Natural Language (NL) Frontend** that acts as a configuration engine for Ascendix Search.

### 3.1 Core Functionality
1.  **Input:** User types a query: *"Show me Class A office buildings in Dallas with more than 10,000 sqft available."*
2.  **Processing:** An AI Agent interprets the query using the org's schema.
3.  **Output:** The Agent generates a valid Ascendix Search JSON configuration payload (`ascendix_search__Template__c`).
4.  **Action:** The Agent updates a dedicated "Scratchpad" search record in Salesforce.
5.  **Result:** The user is deep-linked to this search record in the Ascendix UI, where they see the results on the map/grid immediately.

---

## 4. Architecture & Data Flow

### 4.1 The "AI Scratchpad" Pattern (Sprawl Mitigation)
To avoid creating thousands of one-off search records (e.g., "Search 1", "Search 2", "Search by Todd"), we implement a **Recycle & Promote** strategy.

*   **The Scratchpad:** Every user has exactly *one* dynamic search record named `Current AI Search - [User Name]`.
*   **The Workflow:**
    1.  **User Query:** User submits a request via the Agent interface.
    2.  **Lookup:** System checks for the existence of the user's Scratchpad record.
    3.  **Update/Create:**
        *   *Exists:* The system overwrites the `ascendix_search__Template__c` field with the new JSON criteria.
        *   *Missing:* The system creates the record.
    4.  **View:** User views results in Ascendix Search.
    5.  **Promote (Optional):** If the user wants to keep this list (e.g., for a marketing campaign), they use the native "Save As" button in Ascendix Search to give it a permanent name (e.g., "Q1 Prospecting List").
    6.  **Reset:** The next time the user asks a question, the Scratchpad is overwritten, but the "Q1 Prospecting List" remains untouched.

### 4.2 JSON Configuration Generation
The Agent must construct a JSON object matching the `ascendix_search__Template__c` schema.

**Example Input:** "Class A Office in Plano"

**Generated JSON:**
```json
{
  "version": { "majorRelease": 1, "minorRelease": 23, "patch": 0 },
  "sectionsList": [
    {
      "objectName": "ascendix__Property__c",
      "label": "Property Details",
      "fieldsList": [
        {
          "logicalName": "ascendix__PropertyClass__c",
          "operator": "=",
          "value": "A",
          "type": "picklist"
        },
        {
          "logicalName": "ascendix__PropertySubType__c",
          "operator": "=",
          "value": "Office",
          "type": "picklist"
        },
        {
          "logicalName": "ascendix__City__c",
          "operator": "=",
          "value": "Plano",
          "type": "string"
        }
      ]
    }
  ],
  "resultColumns": [
    { "logicalName": "Name", "type": "string" },
    { "logicalName": "ascendix__City__c", "type": "string" }
  ]
}
```

---

## 5. Technical Requirements

### 5.1 Schema Awareness
The Agent requires context to map loose terms to strict API names.
*   **Context Injection:** The prompt must include a "Schema Summary" listing key objects (`Property`, `Lease`, `Deal`), their API names (`ascendix__Property__c`), and common picklist values.
*   **Vocabulary Mapping:**
    *   "Office" -> `ascendix__PropertySubType__c` OR `RecordTypeId`
    *   "Dallas" -> `ascendix__City__c`
    *   "Larger than" -> Operator `>`

### 5.2 Agent Actions (Tool Definitions)

#### `upsert_scratchpad_search`
*   **Purpose:** specific tool to manage the single user record.
*   **Inputs:**
    *   `userId` (String): Salesforce User ID.
    *   `searchJSON` (String): The complete, valid JSON configuration.
    *   `description` (String): Human-readable summary of the query (e.g., "Class A Office in Plano").
*   **Logic:**
    *   Query `ascendix_search__Search__c` where `OwnerId = :userId` AND `Name = 'Current AI Search'`.
    *   If found: Update `ascendix_search__Template__c`.
    *   If not found: Insert new record.

---

## 6. User Experience (UX)

### 6.1 The Interface
*   **Simple Input:** A chat interface or a simple command bar.
*   **Feedback:** "I've updated your search view to show **Class A Office properties in Plano**."
*   **Action:** A button/link: [Open Results in Ascendix Search]

### 6.2 Conversational Refinement
The system supports iterative refinement *before* viewing results.
*   *User:* "Show me office properties in Plano."
*   *Agent:* "Updated. I found 500 records."
*   *User:* "Only the Class A ones."
*   *Agent:* "Updated. Filters are now: City=Plano AND Class=A. Count is 50 records."
*   *User:* [Opens Search]

---

## 7. Feasibility & Risk

### 7.1 Feasibility
*   **High Feasibility:** The `ascendix_search__Search__c` object is a standard Salesforce object. We have full CRUD access via API. The JSON schema is verbose but structured and deterministic.
*   **Validation:** We have successfully retrieved and analyzed existing JSON templates from the sandbox.

### 7.2 Risks
*   **Schema Hallucination:** The Agent might invent field names (e.g., `City__c` instead of `ascendix__City__c`).
    *   *Mitigation:* Use the "Augmented Schema Discovery" (defined in separate PRD) to feed the Agent a verified list of valid fields.
*   **JSON Syntax Errors:** Invalid JSON will crash the Ascendix UI.
    *   *Mitigation:* Implement strict JSON validation in the `upsert` tool before writing to Salesforce.
*   **Complex Logic:** Nested boolean logic (A AND (B OR C)) is hard to represent in the linear JSON structure if it relies on complex "Criteria Sections".
    *   *Mitigation:* Start with support for linear AND logic (most common). Fail gracefully or ask for simplification if complex OR logic is requested.

---

## 8. Future Roadmap

1.  **"Search Doctor":** An agent that analyzes *existing* saved searches that return 0 results and suggests fixes (e.g., "You searched for City='Plano' AND State='NY'. Did you mean Plano, TX?").
2.  **Hybrid Native App:** Embed the chat interface directly into the Salesforce utility bar, allowing the "scratchpad" to update the main window in real-time via Lightning Message Service (LMS).
