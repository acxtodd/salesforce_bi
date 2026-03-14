System.debug('Checking for export errors...');
List<AI_Search_Export_Error__c> errors = [SELECT Id FROM AI_Search_Export_Error__c LIMIT 5];
System.debug('Total errors found: ' + errors.size());
