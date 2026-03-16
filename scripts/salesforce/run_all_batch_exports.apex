// Run batch exports for all configured objects
List<String> objectsToExport = new List<String>{
    'Account',
    'Opportunity',
    'Case',
    'Note',
    'Property__c',
    'Lease__c',
    'Contract__c'
};

for (String objName : objectsToExport) {
    System.debug('Starting batch export for: ' + objName);
    try {
        AISearchBatchExport batch = new AISearchBatchExport(objName, 24);
        Database.executeBatch(batch, 50); // Batch size 50 to avoid limits
        System.debug('Successfully started batch for: ' + objName);
    } catch (Exception e) {
        System.debug('Error starting batch for ' + objName + ': ' + e.getMessage());
    }
}
