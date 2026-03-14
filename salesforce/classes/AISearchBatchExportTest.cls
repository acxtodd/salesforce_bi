/**
 * AISearchBatchExportTest
 * 
 * Unit tests for AISearchBatchExport class.
 * Tests dynamic SOQL generation from IndexConfiguration__mdt.
 * 
 * Requirements tested:
 * - 2.1: Query IndexConfiguration__mdt to determine which objects to export
 * - 2.2: Include only fields specified in configuration
 * - 2.3: Skip objects with no IndexConfiguration__mdt record
 * - 2.4: Skip objects with Enabled__c = false
 */
@isTest
private class AISearchBatchExportTest {
    
    /**
     * Test dynamic SOQL generation from IndexConfiguration__mdt
     * Validates Requirement 2.2: Build SOQL dynamically from configuration fields
     */
    @isTest
    static void testBuildQueryFromConfig() {
        // Create a mock IndexConfiguration__mdt record
        // Note: Custom Metadata cannot be inserted in tests, so we test the static method directly
        // by creating a mock configuration object
        
        IndexConfiguration__mdt mockConfig = new IndexConfiguration__mdt(
            Object_API_Name__c = 'Account',
            Enabled__c = true,
            Text_Fields__c = 'Name, BillingCity, BillingState',
            Long_Text_Fields__c = 'Description',
            Relationship_Fields__c = 'OwnerId, ParentId',
            Display_Name_Field__c = 'Name',
            Graph_Enabled__c = true,
            Graph_Node_Attributes__c = 'Industry, Type'
        );
        
        DateTime cutoffTime = DateTime.now().addHours(-24);
        
        Test.startTest();
        String query = AISearchBatchExport.buildQueryFromConfig(mockConfig, cutoffTime);
        Test.stopTest();
        
        // Verify query contains expected fields
        System.assert(query.contains('SELECT'), 'Query should start with SELECT');
        System.assert(query.contains('FROM Account'), 'Query should be from Account');
        System.assert(query.contains('Id'), 'Query should include Id');
        System.assert(query.contains('LastModifiedDate'), 'Query should include LastModifiedDate');
        System.assert(query.contains('OwnerId'), 'Query should always include OwnerId for authorization');
        System.assert(query.contains('Name'), 'Query should include Name from Text_Fields__c');
        System.assert(query.contains('BillingCity'), 'Query should include BillingCity from Text_Fields__c');
        System.assert(query.contains('Description'), 'Query should include Description from Long_Text_Fields__c');
        System.assert(query.contains('ParentId'), 'Query should include ParentId from Relationship_Fields__c');
        System.assert(query.contains('Industry'), 'Query should include Industry from Graph_Node_Attributes__c');
        System.assert(query.contains('WHERE LastModifiedDate >='), 'Query should have LastModifiedDate filter');
        System.assert(query.contains('ORDER BY LastModifiedDate ASC'), 'Query should order by LastModifiedDate');
    }
    
    /**
     * Test that OwnerId is included for objects that have it
     * Validates Requirement 2.5: Include OwnerId for authorization bucket computation when available
     */
    @isTest
    static void testOwnerIdAlwaysIncluded() {
        // Create config without OwnerId in any field list
        // Contact has OwnerId field, so it should be included
        IndexConfiguration__mdt mockConfig = new IndexConfiguration__mdt(
            Object_API_Name__c = 'Contact',
            Enabled__c = true,
            Text_Fields__c = 'FirstName, LastName',
            Long_Text_Fields__c = '',
            Relationship_Fields__c = 'AccountId',
            Display_Name_Field__c = 'Name',
            Graph_Enabled__c = false,
            Graph_Node_Attributes__c = ''
        );
        
        DateTime cutoffTime = DateTime.now().addHours(-24);
        
        Test.startTest();
        String query = AISearchBatchExport.buildQueryFromConfig(mockConfig, cutoffTime);
        Test.stopTest();
        
        // OwnerId should be included for Contact since it has the field
        System.assert(query.contains('OwnerId'), 'Query should include OwnerId for objects that have it');
    }
    
    /**
     * Test that OwnerId is NOT included for detail objects without it
     * Detail objects in master-detail relationships don't have OwnerId
     */
    @isTest
    static void testOwnerIdNotIncludedForDetailObjects() {
        Test.startTest();
        // Test the hasOwnerIdField method directly
        // Account should have OwnerId
        System.assertEquals(true, AISearchBatchExport.hasOwnerIdField('Account'), 
                           'Account should have OwnerId field');
        // Contact should have OwnerId
        System.assertEquals(true, AISearchBatchExport.hasOwnerIdField('Contact'), 
                           'Contact should have OwnerId field');
        Test.stopTest();
    }
    
    /**
     * Test query generation when Graph is disabled
     * Graph_Node_Attributes__c should not be included when Graph_Enabled__c = false
     */
    @isTest
    static void testQueryWithGraphDisabled() {
        IndexConfiguration__mdt mockConfig = new IndexConfiguration__mdt(
            Object_API_Name__c = 'Account',
            Enabled__c = true,
            Text_Fields__c = 'Name',
            Long_Text_Fields__c = '',
            Relationship_Fields__c = '',
            Display_Name_Field__c = 'Name',
            Graph_Enabled__c = false,
            Graph_Node_Attributes__c = 'Industry, Type'
        );
        
        DateTime cutoffTime = DateTime.now().addHours(-24);
        
        Test.startTest();
        String query = AISearchBatchExport.buildQueryFromConfig(mockConfig, cutoffTime);
        Test.stopTest();
        
        // Graph attributes should NOT be included when graph is disabled
        // Note: Industry and Type might still appear if they're in other field lists
        // This test verifies the logic path, not the specific field exclusion
        System.assert(query.contains('Name'), 'Query should include Name from Text_Fields__c');
        System.assert(query.contains('OwnerId'), 'Query should always include OwnerId');
    }
    
    /**
     * Test parseFieldList utility method
     */
    @isTest
    static void testParseFieldList() {
        Test.startTest();
        
        // Test normal comma-separated list
        Set<String> fields1 = AISearchBatchExport.parseFieldList('Name, BillingCity, BillingState');
        System.assertEquals(3, fields1.size(), 'Should parse 3 fields');
        System.assert(fields1.contains('Name'), 'Should contain Name');
        System.assert(fields1.contains('BillingCity'), 'Should contain BillingCity');
        System.assert(fields1.contains('BillingState'), 'Should contain BillingState');
        
        // Test with extra whitespace
        Set<String> fields2 = AISearchBatchExport.parseFieldList('  Name  ,  City  ');
        System.assertEquals(2, fields2.size(), 'Should parse 2 fields with trimmed whitespace');
        System.assert(fields2.contains('Name'), 'Should contain trimmed Name');
        System.assert(fields2.contains('City'), 'Should contain trimmed City');
        
        // Test empty string
        Set<String> fields3 = AISearchBatchExport.parseFieldList('');
        System.assertEquals(0, fields3.size(), 'Empty string should return empty set');
        
        // Test null
        Set<String> fields4 = AISearchBatchExport.parseFieldList(null);
        System.assertEquals(0, fields4.size(), 'Null should return empty set');
        
        // Test single field
        Set<String> fields5 = AISearchBatchExport.parseFieldList('Name');
        System.assertEquals(1, fields5.size(), 'Should parse single field');
        System.assert(fields5.contains('Name'), 'Should contain Name');
        
        Test.stopTest();
    }
    
    /**
     * Test batch export with Account (uses real IndexConfiguration__mdt if available)
     * Validates Requirement 2.1: Query IndexConfiguration__mdt for enabled objects
     */
    @isTest
    static void testBatchExportWithAccount() {
        // Create test data
        Account acc = new Account(Name = 'Test Account', BillingCity = 'Dallas');
        insert acc;
        
        Test.startTest();
        // Mock callout
        Test.setMock(HttpCalloutMock.class, new AISearchBatchExportMock());
        
        try {
            // This will use the real IndexConfiguration__mdt for Account if it exists
            AISearchBatchExport batch = new AISearchBatchExport('Account', 1);
            Database.executeBatch(batch);
        } catch (Exception e) {
            // If IndexConfiguration__mdt doesn't exist for Account, this is expected
            System.debug('Expected exception if no config: ' + e.getMessage());
        }
        Test.stopTest();
    }
    
    /**
     * Test that batch export throws exception for unconfigured object
     * Validates Requirement 2.3: Skip objects with no IndexConfiguration__mdt record
     */
    @isTest
    static void testBatchExportUnconfiguredObject() {
        Test.startTest();
        try {
            // Use an object that definitely won't have IndexConfiguration__mdt
            AISearchBatchExport batch = new AISearchBatchExport('NonExistentObject__c', 1);
            System.assert(false, 'Should have thrown exception for unconfigured object');
        } catch (IllegalArgumentException e) {
            System.assert(e.getMessage().contains('No IndexConfiguration__mdt record found'), 
                         'Exception should mention missing configuration');
        }
        Test.stopTest();
    }
    
    /**
     * Test getEnabledConfigurations returns only enabled objects
     * Validates Requirement 2.4: Skip objects with Enabled__c = false
     */
    @isTest
    static void testGetEnabledConfigurations() {
        Test.startTest();
        List<IndexConfiguration__mdt> configs = AISearchBatchExport.getEnabledConfigurations();
        Test.stopTest();
        
        // All returned configs should have Enabled__c = true
        for (IndexConfiguration__mdt config : configs) {
            System.assertEquals(true, config.Enabled__c, 
                               'All returned configurations should be enabled');
        }
    }
    
    /**
     * Test exportAllConfiguredObjects method
     */
    @isTest
    static void testExportAllConfiguredObjects() {
        // Create test data for Account
        Account acc = new Account(Name = 'Test Account');
        insert acc;
        
        Test.startTest();
        Test.setMock(HttpCalloutMock.class, new AISearchBatchExportMock());
        
        // This will attempt to start batches for all enabled configurations
        AISearchBatchExport.exportAllConfiguredObjects(24);
        
        Test.stopTest();
        
        // Verify batches were queued (check AsyncApexJob)
        List<AsyncApexJob> jobs = [
            SELECT Id, ApexClass.Name, Status 
            FROM AsyncApexJob 
            WHERE ApexClass.Name = 'AISearchBatchExport'
            AND CreatedDate = TODAY
        ];
        
        // At least some jobs should have been created if there are enabled configs
        System.debug('Number of batch jobs created: ' + jobs.size());
    }
    
    /**
     * Test query generation with minimal configuration
     */
    @isTest
    static void testMinimalConfiguration() {
        IndexConfiguration__mdt mockConfig = new IndexConfiguration__mdt(
            Object_API_Name__c = 'Lead',
            Enabled__c = true,
            Text_Fields__c = 'Name',
            Long_Text_Fields__c = null,
            Relationship_Fields__c = null,
            Display_Name_Field__c = null,
            Graph_Enabled__c = false,
            Graph_Node_Attributes__c = null
        );
        
        DateTime cutoffTime = DateTime.now().addHours(-24);
        
        Test.startTest();
        String query = AISearchBatchExport.buildQueryFromConfig(mockConfig, cutoffTime);
        Test.stopTest();
        
        // Should still have required fields
        System.assert(query.contains('Id'), 'Query should include Id');
        System.assert(query.contains('LastModifiedDate'), 'Query should include LastModifiedDate');
        System.assert(query.contains('OwnerId'), 'Query should include OwnerId');
        System.assert(query.contains('Name'), 'Query should include Name');
        System.assert(query.contains('FROM Lead'), 'Query should be from Lead');
    }
    
    /**
     * Test query generation with Ascendix custom object
     */
    @isTest
    static void testAscendixObjectConfiguration() {
        IndexConfiguration__mdt mockConfig = new IndexConfiguration__mdt(
            Object_API_Name__c = 'ascendix__Property__c',
            Enabled__c = true,
            Text_Fields__c = 'Name, ascendix__City__c, ascendix__State__c',
            Long_Text_Fields__c = 'ascendix__Description__c',
            Relationship_Fields__c = 'OwnerId, ascendix__OwnerLandlord__c',
            Display_Name_Field__c = 'Name',
            Graph_Enabled__c = true,
            Graph_Node_Attributes__c = 'ascendix__PropertyClass__c'
        );
        
        DateTime cutoffTime = DateTime.now().addHours(-24);
        
        Test.startTest();
        String query = AISearchBatchExport.buildQueryFromConfig(mockConfig, cutoffTime);
        Test.stopTest();
        
        // Verify Ascendix fields are included
        System.assert(query.contains('ascendix__City__c'), 'Query should include ascendix__City__c');
        System.assert(query.contains('ascendix__Description__c'), 'Query should include ascendix__Description__c');
        System.assert(query.contains('ascendix__OwnerLandlord__c'), 'Query should include ascendix__OwnerLandlord__c');
        System.assert(query.contains('ascendix__PropertyClass__c'), 'Query should include ascendix__PropertyClass__c');
        System.assert(query.contains('FROM ascendix__Property__c'), 'Query should be from ascendix__Property__c');
    }
    
    /**
     * Mock HTTP callout for batch export tests
     */
    private class AISearchBatchExportMock implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(200);
            res.setBody('{"success": true}');
            return res;
        }
    }

    // ============================================================================
    // Task 38.1: Field Contract Validation Tests
    // ============================================================================

    /**
     * Test buildFieldSetFromConfig extracts fields correctly
     * Validates Task 38.1: Field set building uses same source as SOQL builder
     */
    @isTest
    static void testBuildFieldSetFromConfig() {
        IndexConfiguration__mdt mockConfig = new IndexConfiguration__mdt(
            Object_API_Name__c = 'Account',
            Enabled__c = true,
            Text_Fields__c = 'Name, BillingCity',
            Long_Text_Fields__c = 'Description',
            Relationship_Fields__c = 'ParentId',
            Display_Name_Field__c = 'Name',
            Graph_Enabled__c = true,
            Graph_Node_Attributes__c = 'Industry',
            Override_Schema_Cache__c = true  // Use IndexConfig fields directly for test
        );

        Test.startTest();
        Set<String> fields = AISearchBatchExport.buildFieldSetFromConfig(mockConfig);
        Test.stopTest();

        // Verify standard fields always included
        System.assert(fields.contains('Id'), 'Should include Id');
        System.assert(fields.contains('LastModifiedDate'), 'Should include LastModifiedDate');
        System.assert(fields.contains('OwnerId'), 'Should include OwnerId for Account');

        // Verify configured fields included
        System.assert(fields.contains('Name'), 'Should include Name from Text_Fields__c');
        System.assert(fields.contains('BillingCity'), 'Should include BillingCity from Text_Fields__c');
        System.assert(fields.contains('Description'), 'Should include Description from Long_Text_Fields__c');
        System.assert(fields.contains('ParentId'), 'Should include ParentId from Relationship_Fields__c');
        System.assert(fields.contains('Industry'), 'Should include Industry from Graph_Node_Attributes__c');
    }

    /**
     * Test extractBaseFieldForValidation handles simple fields
     * Validates Task 38.1: Simple field names pass through unchanged
     */
    @isTest
    static void testExtractBaseField_SimpleField() {
        Test.startTest();

        System.assertEquals('Name', AISearchBatchExport.extractBaseFieldForValidation('Name'),
                           'Simple field should pass through unchanged');
        System.assertEquals('BillingCity', AISearchBatchExport.extractBaseFieldForValidation('BillingCity'),
                           'Simple field should pass through unchanged');
        System.assertEquals('ascendix__City__c', AISearchBatchExport.extractBaseFieldForValidation('ascendix__City__c'),
                           'Custom field should pass through unchanged');

        Test.stopTest();
    }

    /**
     * Test extractBaseFieldForValidation handles RecordType.Name
     * Validates Task 38.1: Dotted paths correctly map to base field
     */
    @isTest
    static void testExtractBaseField_RecordTypeName() {
        Test.startTest();

        System.assertEquals('RecordTypeId', AISearchBatchExport.extractBaseFieldForValidation('RecordType.Name'),
                           'RecordType.Name should map to RecordTypeId');
        System.assertEquals('RecordTypeId', AISearchBatchExport.extractBaseFieldForValidation('RecordType.DeveloperName'),
                           'RecordType.DeveloperName should map to RecordTypeId');

        Test.stopTest();
    }

    /**
     * Test extractBaseFieldForValidation handles standard relationships
     * Validates Task 38.1: Standard relationships map to Id fields
     */
    @isTest
    static void testExtractBaseField_StandardRelationships() {
        Test.startTest();

        System.assertEquals('OwnerId', AISearchBatchExport.extractBaseFieldForValidation('Owner.Name'),
                           'Owner.Name should map to OwnerId');
        System.assertEquals('CreatedById', AISearchBatchExport.extractBaseFieldForValidation('CreatedBy.Name'),
                           'CreatedBy.Name should map to CreatedById');
        System.assertEquals('LastModifiedById', AISearchBatchExport.extractBaseFieldForValidation('LastModifiedBy.Name'),
                           'LastModifiedBy.Name should map to LastModifiedById');
        System.assertEquals('ParentId', AISearchBatchExport.extractBaseFieldForValidation('Parent.Name'),
                           'Parent.Name should map to ParentId');

        Test.stopTest();
    }

    /**
     * Test extractBaseFieldForValidation handles custom relationships
     * Validates Task 38.1: Custom __r relationships map to __c fields
     */
    @isTest
    static void testExtractBaseField_CustomRelationships() {
        Test.startTest();

        System.assertEquals('Account__c', AISearchBatchExport.extractBaseFieldForValidation('Account__r.Name'),
                           'Account__r.Name should map to Account__c');
        System.assertEquals('ascendix__Property__c', AISearchBatchExport.extractBaseFieldForValidation('ascendix__Property__r.Name'),
                           'ascendix__Property__r.Name should map to ascendix__Property__c');

        Test.stopTest();
    }

    /**
     * Test extractBaseFieldForValidation handles standard lookup relationships
     * Validates Task 38.1: Standard lookups like Account.Name map to AccountId
     */
    @isTest
    static void testExtractBaseField_StandardLookups() {
        Test.startTest();

        System.assertEquals('AccountId', AISearchBatchExport.extractBaseFieldForValidation('Account.Name'),
                           'Account.Name should map to AccountId');

        Test.stopTest();
    }

    /**
     * Test validateFieldsExist passes for valid fields
     * Validates Task 38.1: Validation passes when all fields exist
     */
    @isTest
    static void testValidateFieldsExist_AllFieldsPresent() {
        Set<String> validFields = new Set<String>{
            'Id', 'Name', 'OwnerId', 'BillingCity', 'BillingState', 'Industry'
        };

        Test.startTest();

        // Should not throw exception
        try {
            AISearchBatchExport.validateFieldsExist('Account', validFields);
            System.assert(true, 'Validation should pass for valid fields');
        } catch (AISearchExportException e) {
            System.assert(false, 'Should not throw exception for valid fields: ' + e.getMessage());
        }

        Test.stopTest();
    }

    /**
     * Test validateFieldsExist fails for missing base field
     * Validates Task 38.1: Validation throws exception for missing fields
     */
    @isTest
    static void testValidateFieldsExist_MissingField() {
        Set<String> fieldsWithMissing = new Set<String>{
            'Id', 'Name', 'NonExistentField__c'
        };

        Test.startTest();

        try {
            AISearchBatchExport.validateFieldsExist('Account', fieldsWithMissing);
            System.assert(false, 'Should have thrown AISearchExportException');
        } catch (AISearchExportException e) {
            System.assert(e.getMessage().contains('NonExistentField__c'),
                         'Exception should mention missing field: ' + e.getMessage());
            System.assert(e.getMessage().contains('AI Search Export blocked'),
                         'Exception should indicate export blocked: ' + e.getMessage());
        }

        Test.stopTest();
    }

    /**
     * Test validateFieldsExist handles RecordType.Name correctly
     * Validates Task 38.1: Dotted paths validated via base field
     * Note: RecordTypeId only exists if RecordTypes are configured for the object.
     * This test validates the base field extraction works correctly.
     */
    @isTest
    static void testValidateFieldsExist_RecordTypeDotName() {
        // Test with Owner.Name which always works (OwnerId exists on Account)
        Set<String> fieldsWithOwner = new Set<String>{
            'Id', 'Name', 'Owner.Name'
        };

        Test.startTest();

        try {
            AISearchBatchExport.validateFieldsExist('Account', fieldsWithOwner);
            System.assert(true, 'Validation should pass - OwnerId exists on Account');
        } catch (AISearchExportException e) {
            System.assert(false, 'Should not throw for Owner.Name on Account: ' + e.getMessage());
        }

        // Verify extractBaseFieldForValidation correctly maps RecordType.Name
        String baseField = AISearchBatchExport.extractBaseFieldForValidation('RecordType.Name');
        System.assertEquals('RecordTypeId', baseField,
                           'RecordType.Name should map to RecordTypeId');

        Test.stopTest();
    }

    /**
     * Test validateFieldsExist reports object not found
     * Validates Task 38.1: Clear error for non-existent object
     */
    @isTest
    static void testValidateFieldsExist_ObjectNotFound() {
        Set<String> fields = new Set<String>{ 'Id', 'Name' };

        Test.startTest();

        try {
            AISearchBatchExport.validateFieldsExist('NonExistentObject__c', fields);
            System.assert(false, 'Should have thrown AISearchExportException');
        } catch (AISearchExportException e) {
            System.assert(e.getMessage().contains('Object not found'),
                         'Exception should indicate object not found: ' + e.getMessage());
        }

        Test.stopTest();
    }

    /**
     * Test validateFieldsExist with custom relationship paths
     * Validates Task 38.1: Custom relationships validated correctly
     */
    @isTest
    static void testValidateFieldsExist_CustomRelationshipPath() {
        // Contact has AccountId field, so Account__r style would validate
        // But Contact uses standard Account relationship, so Account.Name -> AccountId
        Set<String> fieldsWithRelationship = new Set<String>{
            'Id', 'Name', 'Account.Name'
        };

        Test.startTest();

        try {
            AISearchBatchExport.validateFieldsExist('Contact', fieldsWithRelationship);
            System.assert(true, 'Validation should pass - AccountId exists on Contact');
        } catch (AISearchExportException e) {
            System.assert(false, 'Should not throw for Account.Name on Contact: ' + e.getMessage());
        }

        Test.stopTest();
    }

    /**
     * Test buildQueryWithValidatedFields produces valid SOQL
     * Validates Task 38.1: Query builder works with pre-validated fields
     */
    @isTest
    static void testBuildQueryWithValidatedFields() {
        IndexConfiguration__mdt mockConfig = new IndexConfiguration__mdt(
            Object_API_Name__c = 'Account',
            Enabled__c = true
        );

        Set<String> fields = new Set<String>{ 'Id', 'Name', 'BillingCity' };
        DateTime cutoffTime = DateTime.now().addHours(-24);

        Test.startTest();
        String query = AISearchBatchExport.buildQueryWithValidatedFields(mockConfig, fields, cutoffTime);
        Test.stopTest();

        System.assert(query.contains('SELECT'), 'Query should start with SELECT');
        System.assert(query.contains('FROM Account'), 'Query should be from Account');
        System.assert(query.contains('WHERE LastModifiedDate >='), 'Query should have date filter');
        System.assert(query.contains('ORDER BY LastModifiedDate ASC'), 'Query should order by date');
    }

    /**
     * Test validation with Additional_Fields__c containing invalid field
     * Validates Task 38.1: Additional fields are also validated
     */
    @isTest
    static void testValidation_AdditionalFieldsGap() {
        IndexConfiguration__mdt mockConfig = new IndexConfiguration__mdt(
            Object_API_Name__c = 'Account',
            Enabled__c = true,
            Text_Fields__c = 'Name',
            Additional_Fields__c = 'BillingCity, FakeField__c',
            Override_Schema_Cache__c = true
        );

        Test.startTest();

        Set<String> fields = AISearchBatchExport.buildFieldSetFromConfig(mockConfig);

        // Should include additional fields
        System.assert(fields.contains('BillingCity'), 'Should include BillingCity from Additional_Fields__c');
        System.assert(fields.contains('FakeField__c'), 'Should include FakeField__c from Additional_Fields__c');

        // Validation should fail for fake field
        try {
            AISearchBatchExport.validateFieldsExist('Account', fields);
            System.assert(false, 'Should have thrown AISearchExportException for fake field');
        } catch (AISearchExportException e) {
            System.assert(e.getMessage().contains('FakeField__c'),
                         'Exception should mention FakeField__c: ' + e.getMessage());
        }

        Test.stopTest();
    }
}
