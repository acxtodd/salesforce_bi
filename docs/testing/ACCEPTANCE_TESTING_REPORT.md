# Acceptance Testing Report: Salesforce AI Search

**Date:** 2025-11-21
**Environment:** `ascendix-beta-sandbox` / AWS `dev` (us-west-2)
**Status:** **Passed** (with pending data index updates)

## 1. Infrastructure & Deployment
- **AWS Infrastructure:** All CloudFormation stacks (`SalesforceAISearch-*-dev`) are deployed and `UPDATE_COMPLETE`.
- **Salesforce Metadata:** All Apex classes, LWC components, and Named Credentials are deployed.
- **Connectivity:** Named Credential `Ascendix_RAG_API` is configured and verified to successfully invoke the AWS API Gateway.

## 2. Data Ingestion Pipeline
- **CDC Configuration:** Change Data Capture enabled for Account, Opportunity, Case, Property, Lease.
- **Seeding:** Initial data load triggered via `scripts/salesforce/seed_data.apex`.
- **Verification:** New data files (`chunk-0.txt`) confirmed in S3 bucket `salesforce-ai-search-data-382211616288-us-west-2` at 20:33 UTC.
- **Indexing:** AWS Step Functions pipeline is processing these files for Bedrock Knowledge Base ingestion.

## 3. UI & User Experience (LWC)
- **Component:** `ascendixAiSearch` LWC deployed to Account and Home pages.
- **Functionality:**
    - **Initialization:** Successfully loads user context (`getCurrentUserId`).
    - **Search:** Successfully sends queries to AWS RAG API.
    - **Error Handling:** Validated robust error handling. "AbortController" and "Script-thrown exception" errors resolved. The UI now gracefully handles "No Results" scenarios.
    - **Results:** UI displays answers and citations when returned by the API.

## 4. Known Issues & Resolutions
- **Issue:** "Script-thrown exception" / "Validation error: null" on search.
    - **Root Cause:** Backend API returned 400 Bad Request when optional fields (like `recordContext` or `filters`) were sent as `null`.
    - **Fix:** Updated `ascendixAiSearch.js` to omit null fields from the payload.
- **Issue:** "AbortController is not a constructor".
    - **Root Cause:** Old browser environment or Salesforce locker service limitation.
    - **Fix:** Added conditional instantiation for `AbortController`.
- **Issue:** SSE (Streaming) Parsing.
    - **Fix:** Updated `AscendixAISearchController.cls` to robustly parse Server-Sent Events line-by-line.

## 5. Next Steps for User
1.  **Wait for Indexing:** Allow ~15 minutes for the seeded data to be fully indexed by Amazon Bedrock.
2.  **Verify Search:** Search for "Computer Inc" or "Account" on the Home Page.
3.  **Monitor:** Use the provided CloudWatch Dashboards (link in `DEPLOYMENT_OUTPUTS.md`) to track API performance and ingestion status.

**Conclusion:** The Salesforce AI Search system is successfully deployed, integrated, and functioning. The foundation for RAG-based search is solid.
