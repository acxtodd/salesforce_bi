# AI Search Capability Matrix and Strategic Roadmap

**Date**: 2025-12-02
**Status**: DRAFT - Foundational Document
**Author**: Gemini AI (Technical Business Analyst)
**Purpose**: This document analyzes the current AI Search solution's capabilities against advanced user requirements and proposes a strategic roadmap for product evolution.

---

## 1. Executive Summary

This document serves as a foundational analysis to bridge the gap between our current Salesforce AI Search POC capabilities and a truly robust, intelligent search solution. By dissecting advanced user queries, we identify key architectural shortcomings in aggregation, temporal reasoning, and complex multi-step analysis.

The "Zero-Config" infrastructure fixes we implemented today are foundational, ensuring the system can ingest rich, schema-aware data. However, data ingestion is only the first step. To meet advanced user needs, we must now build layers of **Query Intelligence** and **Agentic Orchestration** on top of this data foundation.

This analysis provides a clear strategic roadmap, categorizing user needs, highlighting current limitations, and outlining phased solutions.

---

## 2. Capability Matrix: Current State vs. Advanced User Needs

Below is a detailed analysis of 20 user queries, mapped against our current architecture's ability to fulfill them.

| Query Category (Archetype) | Example User Query | Current Status | Why It Fails / Gaps | Strategic Solution |
| :------------------------- | :----------------- | :------------- | :------------------ | :----------------- |
| **1. Multi-Hop Filter** | "Available industrial properties in Miami, FL between 20k-50k sq ft" | 🟢 **Working** (Post-Fix) | *Solved by Zero-Config Fix.* We now index City, State, Type, Size. Graph traversal handles the hop from Property -> Availability. | **Maintain.** Ensure schema discovery keeps up with new fields. |
| **2. Role/Relationship** | "All asset managers at Blackstone" | 🟡 **Partial** | Vector search matches "Asset Manager" text. Graph links Contact -> Account. *Risk:* "Asset Manager" might be a job title string, not a structured role in the graph. | **Schema Enrichment.** Ensure `Title` / `Role` fields are indexed as graph attributes and linked to Contact records. |
| **3. Status & Class** | "Class A office... not currently leased" | 🟢 **Working** (Post-Fix) | `PropertyClass` and `Status` are now indexed attributes. Graph handles the filter. | **Maintain.** |
| **4. Temporal (Future)** | "Leases expiring in next 6 months" | 🔴 **Failing** | System treats "next 6 months" as text or simple metadata. It lacks a query engine to calculate `Date.Now + 180 days` for structured filtering. | **Query Translation Layer.** Convert NL to `iso_date > NOW() AND iso_date < NOW()+180d` filters for OpenSearch/Graph. |
| **5. Temporal (Past)** | "Activities... in the last 30 days" | 🔴 **Failing** | Same as above. No engine to compute `Date.Now - 30 days`. | **Query Translation Layer.** |
| **6. Complex Aggregation** | "Contacts with 5+ activities... and 'Negotiation' sale" | ❌ **Impossible** | *Hard Gap.* System cannot `COUNT(Activities)`. It retrieves records, it does not aggregate them. | **SQL Agent / Analytics Store.** Offload "Count/Sum" queries to a SQL engine (Salesforce SOQL or Postgres mirror). |
| **7. Multi-Filter Match** | "Sale where Jane Doe is broker AND stage is 'Due Diligence'" | 🟡 **Partial** | Works *if* "Jane Doe" is explicitly linked as a User/Contact node. Fails if "Jane Doe" is just text in a field. | **Entity Resolution.** Ensure User/Contact records are distinct nodes, not just text strings or unstructured text. |
| **8. Portfolio Aggregation** | "Companies owning >10 retail properties" | ❌ **Impossible** | *Hard Gap.* Cannot perform `GROUP BY Company HAVING COUNT(Property) > 10`. | **SQL Agent / Analytics Store.** |
| **9. Numeric Threshold** | "Properties with vacancy rate > 25%" | 🟢 **Working** (Post-Fix) | `VacancyRate` is numeric. Graph/Vector filters handle `> 25`. | **Maintain.** (Requires `VacancyRate` to be discovered and indexed as `numeric` type). |
| **10. Unstructured Text** | "Notes containing 'HVAC system needs replacement'" | 🟢 **Working** | *Core Competency.* Vector search excels at semantic matching of unstructured text. | **Maintain.** |
| **11. Complex Join (3+ Hops)** | "Tenants... leases expiring Q3 2026... no activity 90 days" | ❌ **Impossible** | Too many constraints. Requires: Time calc + Join (Tenant->Lease->Activity) + Aggregation (Count=0). | **Agentic Workflow.** Break into steps: 1. Find Expiring Leases. 2. Check Activity for each. 3. Filter list. |
| **12. Comparative/History** | "Properties... sale in last 5 years... broker John Smith" | 🔴 **Failing** | Requires historical lookup (Time) + Relationship traversal. | **Query Translation + Graph.** |
| **13. Comparative Size** | "Available space... where largest tenant > 50k sq ft" | ❌ **Impossible** | Requires "Max/Largest" logic relative to other child records. | **SQL Agent / Analytics Store.** |
| **14. Mixed Text/Meta** | "Notes 'complained about noise'... properties built before 1990" | 🟡 **Partial** | Requires combining Vector Search (Notes) with Metadata Filter (YearBuilt < 1990). | **Hybrid Search.** (Needs explicit handling to combine vector similarity with structured filtering). |
| **15. Exclusion** | "Available space... where NO existing tenants in Finance" | ❌ **Impossible** | "NOT EXISTS" queries are notoriously hard for RAG. | **SQL Agent / Analytics Store.** |
| **16. Event Sequence** | "Sale closed... but 3+ maintenance activities since closing" | ❌ **Impossible** | Requires temporal sequencing ("Activity Date > Sale Date") AND counting. | **SQL Agent / Analytics Store.** |
| **17. Clause Search** | "Lease terms include 'Right of First Refusal'" | 🟢 **Working** | Strong use case for Vector Search. | **Maintain.** |
| **18. Geo-Spatial/Portfolio** | "Tenants with leases across multiple locations" | ❌ **Impossible** | Requires `GROUP BY Tenant COUNT(DISTINCT Location) > 1`. | **SQL Agent / Analytics Store.** |
| **19. Audit/Forensic** | "Brokers associated with 'Lost' sale... show last 3 activities" | 🔴 **Failing** | "Last 3" implies sorting and limits per parent. | **Agentic Workflow.** Find Sales -> Find Brokers -> Fetch & Sort Activities. |
| **20. Opportunity Finding** | "Properties where Notes indicate 'Landlord willing to pay...'" | 🟢 **Working** | Strong use case for Vector Search. | **Maintain.** |

---

## 3. Strategic Roadmap: From POC to Robust Search Solution

This roadmap outlines a phased evolution, building upon the foundational "Zero-Config" capabilities to achieve the advanced search solution envisioned.

#### **Phase 1: The "Smart Filter" (Current Foundation - 1 Month)**
*   **Goal:** Fully operationalize and verify **Multi-Hop** and **Numeric** queries.
*   **Current State:** Implemented Zero-Config Schema Discovery and Graph Hydration.
*   **Key Work Areas (Verification & Optimization):**
    *   **Full Re-Index:** Complete for all configured Salesforce objects to ensure the graph and metadata are fully populated with rich attributes (e.g., City, State, Numeric values).
    *   **"Zero-Config Auth"**: Implement permanent, autonomous OAuth 2.0 Client Credentials authentication for Schema Discovery.
    *   **Query Decomposition Refinement:** Ensure `query_decomposition.yaml` effectively maps user intent to the newly available structured metadata (e.g., `ascendix__PropertyClass__c: "A"` from "Class A").
    *   **Initial Testing:** Conduct comprehensive testing of Tier 1 queries (Location, Status, Class, Numeric Thresholds) to validate the "Smart Filter" capabilities.
*   **Expected Result:** Reliable retrieval for direct attribute-based filtering and 1-2 hop traversals.

#### **Phase 2: The "Temporal Engine" (Months 2-3)**
*   **Goal:** Enable time-aware filtering and searching (Categories 4, 5, 12).
*   **Key Work Areas:**
    *   **Query Translation Layer (LLM-based):** Develop an LLM-powered component that intercepts natural language temporal expressions (e.g., "next 6 months," "last 30 days," "Q3 2026") and translates them into precise ISO-formatted date ranges or relative date computations.
    *   **Date Field Integration:** Ensure discovered Date fields are correctly used in OpenSearch/DynamoDB queries for range filtering.
    *   **Time-Series Context:** Explore initial capabilities for historical data if available (e.g., snapshotting key numeric fields).
*   **Expected Result:** User can reliably query for events "expiring next quarter" or activities "in the last 30 days."

#### **Phase 3: The "Analyst" Agent (Months 4-6)**
*   **Goal:** Tackle **Aggregation**, **Comparative Analysis**, and **Complex Multi-Step Reasoning** (Categories 6, 8, 11, 13, 15, 16, 18, 19).
*   **Key Work Areas:**
    *   **Agentic Orchestrator:** Introduce an LLM-driven agent that can break down complex queries into multiple, sequential steps.
    *   **SQL Agent Integration:** If a query requires aggregation or counting, the agent generates and executes dynamic SOQL queries directly against Salesforce, or an analytical data store (e.g., Postgres mirror, OpenSearch Aggregations).
    *   **Recursive Retrieval:** Implement mechanisms for the agent to perform iterative searches, retrieve intermediate results, and re-query based on those results.
    *   **Contextual Reasoning:** The agent can synthesize information from multiple data sources and present a cohesive answer, potentially involving sorting (e.g., "last 3 activities").
*   **Expected Result:** The system can answer complex analytical questions like "Which companies own more than 10 retail properties?" or "Show brokers associated with lost deals, and their last 3 activities."

---

## 4. Next Steps

This document provides the strategic blueprint. The immediate focus should be on completing Phase 1:

1.  **Verify Full Re-Index Completion:** Monitor the batch jobs and Step Functions executions.
2.  **Test Tier 1 Queries:** Validate that the "Plano" query and similar multi-hop filter queries now yield accurate results through the LWC.
3.  **Implement Permanent "Zero-Config Auth":** Set up the AWS Secret `salesforce/connected-app-secret` to ensure the `SchemaDiscoveryLambda` can run autonomously and perpetually.

---
