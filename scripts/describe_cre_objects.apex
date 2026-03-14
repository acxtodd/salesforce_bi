// Describe CRE Objects to get field names
// Run with: sf apex run --file scripts/describe_cre_objects.apex --target-org ascendix-beta-sandbox

System.debug('=== CRE Object Schema Discovery ===');

// Helper to describe an object
void describeObject(String objName) {
    try {
        Schema.SObjectType objType = Schema.getGlobalDescribe().get(objName);
        if (objType == null) {
            System.debug(objName + ': NOT FOUND');
            return;
        }
        
        Schema.DescribeSObjectResult objDescribe = objType.getDescribe();
        System.debug('\n--- ' + objName + ' ---');
        System.debug('Label: ' + objDescribe.getLabel());
        System.debug('Record Count Queryable: ' + objDescribe.isQueryable());
        
        Map<String, Schema.SObjectField> fields = objDescribe.fields.getMap();
        System.debug('Total Fields: ' + fields.size());
        
        // List key fields (text, textarea, lookup)
        List<String> textFields = new List<String>();
        List<String> lookupFields = new List<String>();
        
        for (String fieldName : fields.keySet()) {
            Schema.DescribeFieldResult fieldDesc = fields.get(fieldName).getDescribe();
            Schema.DisplayType fieldType = fieldDesc.getType();
            
            if (fieldType == Schema.DisplayType.STRING || 
                fieldType == Schema.DisplayType.TEXTAREA ||
                fieldType == Schema.DisplayType.PICKLIST) {
                textFields.add(fieldName);
            } else if (fieldType == Schema.DisplayType.REFERENCE) {
                lookupFields.add(fieldName + ' -> ' + fieldDesc.getReferenceTo());
            }
        }
        
        System.debug('Text/Picklist Fields: ' + String.join(textFields, ', '));
        System.debug('Lookup Fields: ' + String.join(lookupFields, ', '));
        
    } catch (Exception e) {
        System.debug(objName + ': ERROR - ' + e.getMessage());
    }
}

// Describe each CRE object
describeObject('ascendix__Property__c');
describeObject('ascendix__Availability__c');
describeObject('ascendix__Lease__c');
describeObject('ascendix__Sale__c');
describeObject('ascendix__Deal__c');

System.debug('\n=== Schema Discovery Complete ===');
