// Check for export errors
List<AI_Search_Export_Error__c> errors = [
    SELECT Id, Job_Id__c, Object_Type__c, Error_Message__c, Record_Count__c, Timestamp__c 
    FROM AI_Search_Export_Error__c 
    WHERE Timestamp__c = TODAY 
    ORDER BY Timestamp__c DESC 
    LIMIT 10
];

System.debug('Found ' + errors.size() + ' errors today');

for(AI_Search_Export_Error__c e : errors) { 
    System.debug('Error: ' + e.Object_Type__c + ' - ' + e.Error_Message__c); 
}
