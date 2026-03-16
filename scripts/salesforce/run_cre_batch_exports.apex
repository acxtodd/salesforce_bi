// Run batch exports for all CRE objects
// This exports all records modified in the last year (8760 hours)
// Run with: sf apex run --file scripts/run_cre_batch_exports.apex --target-org ascendix-beta-sandbox

System.debug('=== Starting CRE Batch Exports ===');
System.debug('Timestamp: ' + DateTime.now());

// CRE objects to export (Ascendix package)
List<String> creObjects = new List<String>{
    'ascendix__Property__c',
    'ascendix__Availability__c',
    'ascendix__Lease__c',
    'ascendix__Sale__c',
    'ascendix__Deal__c'
};

// Also export Account for relationship context
List<String> supportingObjects = new List<String>{
    'Account'
};

Integer hoursBack = 8760; // 1 year
Integer batchSize = 50;

// Export CRE objects
for (String objName : creObjects) {
    System.debug('Starting batch export for: ' + objName);
    try {
        AISearchBatchExport batch = new AISearchBatchExport(objName, hoursBack);
        Id jobId = Database.executeBatch(batch, batchSize);
        System.debug('Successfully started batch for ' + objName + ' - Job ID: ' + jobId);
    } catch (Exception e) {
        System.debug('Error starting batch for ' + objName + ': ' + e.getMessage());
    }
}

// Export supporting objects
for (String objName : supportingObjects) {
    System.debug('Starting batch export for: ' + objName);
    try {
        AISearchBatchExport batch = new AISearchBatchExport(objName, hoursBack);
        Id jobId = Database.executeBatch(batch, batchSize);
        System.debug('Successfully started batch for ' + objName + ' - Job ID: ' + jobId);
    } catch (Exception e) {
        System.debug('Error starting batch for ' + objName + ': ' + e.getMessage());
    }
}

System.debug('=== Batch Exports Initiated ===');
System.debug('Monitor progress in Setup > Apex Jobs');
