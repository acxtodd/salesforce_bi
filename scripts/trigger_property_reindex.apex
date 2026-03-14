// Trigger re-index for Property objects with schema-driven attributes
// **Feature: zero-config-schema-discovery**
// **Requirements: 2.2, 2.3, 2.4**
//
// This script triggers a batch export for Property objects which will:
// 1. Export all Property records
// 2. Process through the ingestion pipeline
// 3. Build graph nodes with ALL filterable attributes from schema
// 4. Store numeric fields as numbers
// 5. Store date fields in ISO 8601 format
//
// Run with: sf apex run --file scripts/trigger_property_reindex.apex --target-org ascendix-beta-sandbox

System.debug('=== Starting Property Re-Index for Schema-Driven Attributes ===');
System.debug('Timestamp: ' + DateTime.now());

// Property object to re-index
String objName = 'ascendix__Property__c';

// Export all records modified in the last year
Integer hoursBack = 8760; // 1 year
Integer batchSize = 50;

System.debug('Starting batch export for: ' + objName);
System.debug('Hours back: ' + hoursBack);
System.debug('Batch size: ' + batchSize);

try {
    AISearchBatchExport batch = new AISearchBatchExport(objName, hoursBack);
    Id jobId = Database.executeBatch(batch, batchSize);
    System.debug('Successfully started batch for ' + objName + ' - Job ID: ' + jobId);
    System.debug('');
    System.debug('=== Re-Index Initiated ===');
    System.debug('Job ID: ' + jobId);
    System.debug('');
    System.debug('Monitor progress:');
    System.debug('1. Setup > Apex Jobs - Check batch job status');
    System.debug('2. CloudWatch Logs - Check graph builder Lambda logs');
    System.debug('3. DynamoDB - Verify graph nodes have schema-driven attributes');
    System.debug('');
    System.debug('Expected attributes on Property nodes:');
    System.debug('- ascendix__PropertyClass__c (filterable)');
    System.debug('- ascendix__PropertySubType__c (filterable)');
    System.debug('- ascendix__City__c (filterable)');
    System.debug('- ascendix__State__c (filterable)');
    System.debug('- ascendix__BuildingStatus__c (filterable)');
    System.debug('- ascendix__TotalBuildingArea__c (numeric)');
    System.debug('- ascendix__YearBuilt__c (numeric)');
    System.debug('- LastActivityDate (date - ISO 8601)');
} catch (Exception e) {
    System.debug('Error starting batch for ' + objName + ': ' + e.getMessage());
    System.debug('Stack trace: ' + e.getStackTraceString());
}
