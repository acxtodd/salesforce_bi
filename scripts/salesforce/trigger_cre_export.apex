// Trigger batch export for all Ascendix CRE objects
// Using 10000 hours back to get all records regardless of LastModifiedDate
// Batch size of 50 to avoid Step Functions payload limits

Database.executeBatch(new AISearchBatchExport('ascendix__Property__c', 10000), 50);
Database.executeBatch(new AISearchBatchExport('ascendix__Deal__c', 10000), 50);
Database.executeBatch(new AISearchBatchExport('ascendix__Availability__c', 10000), 50);
Database.executeBatch(new AISearchBatchExport('ascendix__Lease__c', 10000), 50);
Database.executeBatch(new AISearchBatchExport('ascendix__Sale__c', 10000), 50);
