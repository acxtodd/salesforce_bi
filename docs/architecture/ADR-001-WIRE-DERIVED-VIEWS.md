# Solution Architecture Directive: Wiring Derived Views (The "Ghost Data" Fix)

**Date:** 2025-12-06
**From:** Solution Architect
**To:** Engineering Team
**Priority:** CRITICAL / P0

## Context
We have successfully built and populated the Derived Views in DynamoDB (`leases-view`, `vacancy-view`, `activities-agg`). These tables contain the exact answers to our "Money Queries" (e.g., "leases expiring soon").
However, the current `RetrieveLambda` logic relies on the LLM Planner to route these queries. The Planner is failing to trigger this route due to confidence thresholds or missing prompts, resulting in the application ignoring this data entirely ("Ghost Data").

## The Mandate
**Stop relying on the Planner for deterministic aggregation queries.**
We will implement a "Fast Path" (Regex/Keyword Router) that forces specific query patterns directly to the `DerivedViewManager` immediately, bypassing the LLM Planner overhead and uncertainty.

## Implementation Plan

### 1. Implement "Fast Path" Routing in `lambda/retrieve/index.py`
**Location:** Inside `lambda_handler`, *before* the Planner logic.

**Logic:**
Create a deterministic check for specific keywords. If matched, execute the corresponding `DerivedViewManager` query and return immediately (or merge).

**Keyword Mapping:**
*   **Pattern:** `expir` (e.g., "expiring", "expires", "expiration")
    *   **Action:** Query `DerivedViewManager.query_leases_view()`
    *   **Filter:** Default to next 6 months if no date extracted (keep it simple for now).
*   **Pattern:** `vacan` (e.g., "vacancy", "vacant")
    *   **Action:** Query `DerivedViewManager.query_vacancy_view()`
    *   **Filter:** Default to `min_vacancy_pct=0`.
*   **Pattern:** `activit` (e.g., "activity", "activities")
    *   **Action:** Query `DerivedViewManager.query_activities_agg()`

### 2. Standardize "Synthetic Matches"
The `DerivedViewManager` returns raw dictionaries/objects. These must be converted into the standard `match` format expected by the `AnswerLambda` so the LLM can read them.

**Format Requirement:**
```json
{
  "id": "derived_view:{view_name}/{record_id}",
  "score": 1.0,
  "text": "Lease for {Tenant} at {Property} expires on {Date}. Status: {Status}...",
  "metadata": { "source": "derived_view", ... }
}
```
*Note: The `text` field is critical. It must be a human-readable string summary of the record.*

### 3. Update `AnswerLambda` Prompt (If needed)
Ensure the system prompt knows how to interpret these "high confidence" facts. (Likely not needed if we format the `text` field well).

## Acceptance Criteria (The "Money Queries")

The following queries **MUST** return data from DynamoDB (not vector search) and generate a correct answer:

1.  **"Show me leases expiring in the next 6 months."**
    *   *Verify:* Returns records from `leases-view`.
2.  **"Which properties have high vacancy?"**
    *   *Verify:* Returns records from `vacancy-view`.

## Execution Steps
1.  **Modify `lambda/retrieve/index.py`**: Insert the Fast Path logic.
2.  **Deploy**: `SalesforceAISearch-Api-dev`.
3.  **Verify**: Run the acceptance tests manually using `curl` or the LWC.

---
*Stop polishing the architecture. Wire the data to the user.*
