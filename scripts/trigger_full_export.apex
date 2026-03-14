// FULL EXPORT - All Salesforce Records for AI Search
// This triggers a complete re-index of ALL records regardless of LastModifiedDate
// Using 100000 hours (~11.4 years) to ensure we capture everything
// 
// Run this in Salesforce Developer Console: Execute Anonymous
// Monitor progress: Setup > Apex Jobs

// ============================================
// STANDARD SALESFORCE OBJECTS
// ============================================

// Accounts - Core CRM object (companies/organizations)
Database.executeBatch(new AISearchBatchExport('Account', 100000), 200);

// Contacts - People associated with accounts
Database.executeBatch(new AISearchBatchExport('Contact', 100000), 200);

// Opportunities (Deals in standard SF)
Database.executeBatch(new AISearchBatchExport('Opportunity', 100000), 200);

// Cases - Support/service cases
Database.executeBatch(new AISearchBatchExport('Case', 100000), 200);

// Notes - Notes attached to records
Database.executeBatch(new AISearchBatchExport('Note', 100000), 200);

// Tasks - Activity records (calls, to-dos, etc.)
Database.executeBatch(new AISearchBatchExport('Task', 100000), 200);

// Events - Calendar events/meetings
Database.executeBatch(new AISearchBatchExport('Event', 100000), 200);

// ============================================
// CUSTOM OBJECTS (if applicable in your org)
// ============================================

// Custom Property object
Database.executeBatch(new AISearchBatchExport('Property__c', 100000), 200);

// Custom Lease object
Database.executeBatch(new AISearchBatchExport('Lease__c', 100000), 200);

// Custom Contract object
Database.executeBatch(new AISearchBatchExport('Contract__c', 100000), 200);

// ============================================
// ASCENDIX CRE OBJECTS (Primary CRE Data)
// Using smaller batch size (50) to avoid payload limits
// ============================================

// Ascendix Properties - Commercial Real Estate properties
Database.executeBatch(new AISearchBatchExport('ascendix__Property__c', 100000), 50);

// Ascendix Deals - HIGH VALUE DEALS (Griffin Partners $5.26M, etc.)
Database.executeBatch(new AISearchBatchExport('ascendix__Deal__c', 100000), 50);

// Ascendix Availabilities - Space listings
Database.executeBatch(new AISearchBatchExport('ascendix__Availability__c', 100000), 50);

// Ascendix Leases - Lease records
Database.executeBatch(new AISearchBatchExport('ascendix__Lease__c', 100000), 50);

// Ascendix Sales - Sale transactions
Database.executeBatch(new AISearchBatchExport('ascendix__Sale__c', 100000), 50);
