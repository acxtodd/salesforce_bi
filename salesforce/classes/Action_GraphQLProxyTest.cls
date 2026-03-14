/**
 * Action_GraphQLProxyTest - Test class for Action_GraphQLProxy
 * 
 * Tests three main scenarios:
 * 1. Successful record creation via GraphQL
 * 2. Validation errors (required fields, invalid fields, allow-list violations)
 * 3. Permission errors (CRUD, FLS)
 * 
 * Phase 2 - Agent Actions
 * Requirements: 19.1, 19.2, 19.4
 */
@isTest
private class Action_GraphQLProxyTest {
    
    /**
     * Test successful Account creation with valid inputs
     * Requirement 19.1: Build GraphQL mutation with RecordCreateInput
     * Requirement 19.3: Return record ID and selected fields
     */
    @isTest
    static void testSuccessfulAccountCreation() {
        // Setup mock HTTP response for successful creation
        Test.setMock(HttpCalloutMock.class, new GraphQLSuccessMock());
        
        // Prepare input
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test Account", "Industry": "Technology", "Phone": "555-1234"}';
        input.allowedFields = 'Name, Industry, Phone, Website, BillingCity';
        input.returnFields = 'Name, Industry, Phone';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify
        System.assertEquals(1, results.size(), 'Should return one result');
        Action_GraphQLProxy.GraphQLProxyOutput output = results[0];
        
        System.assertEquals(true, output.success, 'Operation should succeed');
        System.assertEquals('001xx000000ABCD', output.recordId, 'Should return record ID');
        System.assertNotEquals(null, output.recordDataJson, 'Should return record data');
        System.assertEquals(null, output.errorMessage, 'Should not have error message');
        
        // Verify returned data contains expected fields
        Map<String, Object> recordData = (Map<String, Object>) JSON.deserializeUntyped(output.recordDataJson);
        System.assertEquals('Test Account', recordData.get('Name'), 'Should return Name field');
        System.assertEquals('Technology', recordData.get('Industry'), 'Should return Industry field');
    }
    
    /**
     * Test successful Opportunity creation with date and currency fields
     * Requirement 19.1: Build GraphQL mutation with RecordCreateInput
     */
    @isTest
    static void testSuccessfulOpportunityCreation() {
        // Setup mock HTTP response
        Test.setMock(HttpCalloutMock.class, new GraphQLSuccessMock());
        
        // Prepare input with various field types
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createOpportunity';
        input.objectApiName = 'Opportunity';
        input.inputFieldsJson = '{"Name": "Big Deal", "Amount": 100000, "CloseDate": "2025-12-31", "StageName": "Prospecting"}';
        input.allowedFields = 'Name, Amount, CloseDate, StageName, AccountId';
        input.returnFields = 'Name, Amount, StageName';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify
        System.assertEquals(1, results.size(), 'Should return one result');
        System.assertEquals(true, results[0].success, 'Operation should succeed');
        System.assertNotEquals(null, results[0].recordId, 'Should return record ID');
    }
    
    /**
     * Test field not in allow-list is rejected
     * Requirement 19.2: Validate that all fields are in the allow-list
     */
    @isTest
    static void testFieldNotInAllowList() {
        // Prepare input with field not in allow-list
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test Account", "AnnualRevenue": 1000000}';
        input.allowedFields = 'Name, Industry, Phone'; // AnnualRevenue not allowed
        input.returnFields = 'Name';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify
        System.assertEquals(1, results.size(), 'Should return one result');
        Action_GraphQLProxy.GraphQLProxyOutput output = results[0];
        
        System.assertEquals(false, output.success, 'Operation should fail');
        System.assertEquals(null, output.recordId, 'Should not return record ID');
        System.assertNotEquals(null, output.errorMessage, 'Should have error message');
        System.assert(output.errorMessage.contains('not in the allow-list'), 
            'Error should mention allow-list: ' + output.errorMessage);
    }
    
    /**
     * Test required field missing validation error
     * Requirement 19.5: Map GraphQL errors to user-friendly messages
     */
    @isTest
    static void testRequiredFieldMissing() {
        // Setup mock for required field error
        Test.setMock(HttpCalloutMock.class, new GraphQLRequiredFieldErrorMock());
        
        // Prepare input missing required field
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createOpportunity';
        input.objectApiName = 'Opportunity';
        input.inputFieldsJson = '{"Name": "Test Opp"}'; // Missing CloseDate, StageName
        input.allowedFields = 'Name, CloseDate, StageName, Amount';
        input.returnFields = 'Name';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify
        System.assertEquals(1, results.size(), 'Should return one result');
        Action_GraphQLProxy.GraphQLProxyOutput output = results[0];
        
        System.assertEquals(false, output.success, 'Operation should fail');
        System.assertNotEquals(null, output.errorMessage, 'Should have error message');
        System.assert(output.errorMessage.contains('required') || output.errorMessage.contains('Required'), 
            'Error should mention required field: ' + output.errorMessage);
    }
    
    /**
     * Test invalid field name validation error
     * Requirement 19.5: Map GraphQL errors to user-friendly messages
     */
    @isTest
    static void testInvalidFieldName() {
        // Setup mock for invalid field error
        Test.setMock(HttpCalloutMock.class, new GraphQLInvalidFieldErrorMock());
        
        // Prepare input with invalid field
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test", "InvalidField__c": "value"}';
        input.allowedFields = 'Name, InvalidField__c';
        input.returnFields = 'Name';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify
        System.assertEquals(1, results.size(), 'Should return one result');
        Action_GraphQLProxy.GraphQLProxyOutput output = results[0];
        
        System.assertEquals(false, output.success, 'Operation should fail');
        System.assertNotEquals(null, output.errorMessage, 'Should have error message');
        System.assert(output.errorMessage.contains('invalid') || output.errorMessage.contains('Invalid'), 
            'Error should mention invalid field: ' + output.errorMessage);
    }
    
    /**
     * Test duplicate value validation error
     * Requirement 19.5: Map GraphQL errors to user-friendly messages
     */
    @isTest
    static void testDuplicateValue() {
        // Setup mock for duplicate error
        Test.setMock(HttpCalloutMock.class, new GraphQLDuplicateErrorMock());
        
        // Prepare input
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Existing Account", "ExternalId__c": "EXT-001"}';
        input.allowedFields = 'Name, ExternalId__c';
        input.returnFields = 'Name';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify
        System.assertEquals(1, results.size(), 'Should return one result');
        Action_GraphQLProxy.GraphQLProxyOutput output = results[0];
        
        System.assertEquals(false, output.success, 'Operation should fail');
        System.assertNotEquals(null, output.errorMessage, 'Should have error message');
        System.assert(output.errorMessage.contains('duplicate') || output.errorMessage.contains('Duplicate'), 
            'Error should mention duplicate: ' + output.errorMessage);
    }
    
    /**
     * Test insufficient access (CRUD) permission error
     * Requirement 19.4: Enforce with sharing behavior and respect FLS permissions
     * Requirement 19.5: Map GraphQL errors to user-friendly messages
     */
    @isTest
    static void testInsufficientAccessCRUD() {
        // Setup mock for permission error
        Test.setMock(HttpCalloutMock.class, new GraphQLPermissionErrorMock());
        
        // Prepare input
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test Account"}';
        input.allowedFields = 'Name, Industry';
        input.returnFields = 'Name';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify
        System.assertEquals(1, results.size(), 'Should return one result');
        Action_GraphQLProxy.GraphQLProxyOutput output = results[0];
        
        System.assertEquals(false, output.success, 'Operation should fail');
        System.assertNotEquals(null, output.errorMessage, 'Should have error message');
        System.assert(output.errorMessage.contains('permission') || output.errorMessage.contains('Permission'), 
            'Error should mention permission: ' + output.errorMessage);
    }
    
    /**
     * Test field-level security (FLS) permission error
     * Requirement 19.4: Enforce with sharing behavior and respect FLS permissions
     * Requirement 19.5: Map GraphQL errors to user-friendly messages
     */
    @isTest
    static void testFieldLevelSecurityError() {
        // Setup mock for FLS error
        Test.setMock(HttpCalloutMock.class, new GraphQLFLSErrorMock());
        
        // Prepare input with field user cannot set
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test", "OwnerId": "005xx000000ABCD"}';
        input.allowedFields = 'Name, OwnerId';
        input.returnFields = 'Name';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify
        System.assertEquals(1, results.size(), 'Should return one result');
        Action_GraphQLProxy.GraphQLProxyOutput output = results[0];
        
        System.assertEquals(false, output.success, 'Operation should fail');
        System.assertNotEquals(null, output.errorMessage, 'Should have error message');
        System.assert(output.errorMessage.containsIgnoreCase('permission') || output.errorMessage.containsIgnoreCase('field'), 
            'Error should mention permission or field: ' + output.errorMessage);
    }
    
    /**
     * Test HTTP error handling (non-200 status)
     * Requirement 19.5: Map GraphQL errors to user-friendly messages
     */
    @isTest
    static void testHTTPError() {
        // Setup mock for HTTP error
        Test.setMock(HttpCalloutMock.class, new GraphQLHTTPErrorMock());
        
        // Prepare input
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test"}';
        input.allowedFields = 'Name';
        input.returnFields = 'Name';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify
        System.assertEquals(1, results.size(), 'Should return one result');
        Action_GraphQLProxy.GraphQLProxyOutput output = results[0];
        
        System.assertEquals(false, output.success, 'Operation should fail');
        System.assertNotEquals(null, output.errorMessage, 'Should have error message');
    }
    
    /**
     * Test special characters in field values are properly escaped
     * Requirement 19.1: Build GraphQL mutation with RecordCreateInput
     */
    @isTest
    static void testSpecialCharacterEscaping() {
        // Setup mock
        Test.setMock(HttpCalloutMock.class, new GraphQLSuccessMock());
        
        // Prepare input with special characters
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test \\"Account\\" with \\nNewline", "Description": "Line1\\nLine2"}';
        input.allowedFields = 'Name, Description';
        input.returnFields = 'Name';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify - should succeed without errors
        System.assertEquals(1, results.size(), 'Should return one result');
        System.assertEquals(true, results[0].success, 'Operation should succeed with escaped characters');
    }
    
    /**
     * Test batch processing of multiple operations
     * Requirement 19.1: Support multiple operations in single invocation
     */
    @isTest
    static void testBatchOperations() {
        // Setup mock
        Test.setMock(HttpCalloutMock.class, new GraphQLSuccessMock());
        
        // Prepare multiple inputs
        List<Action_GraphQLProxy.GraphQLProxyInput> inputs = new List<Action_GraphQLProxy.GraphQLProxyInput>();
        
        Action_GraphQLProxy.GraphQLProxyInput input1 = new Action_GraphQLProxy.GraphQLProxyInput();
        input1.operation = 'createAccount1';
        input1.objectApiName = 'Account';
        input1.inputFieldsJson = '{"Name": "Account 1"}';
        input1.allowedFields = 'Name';
        input1.returnFields = 'Name';
        inputs.add(input1);
        
        Action_GraphQLProxy.GraphQLProxyInput input2 = new Action_GraphQLProxy.GraphQLProxyInput();
        input2.operation = 'createAccount2';
        input2.objectApiName = 'Account';
        input2.inputFieldsJson = '{"Name": "Account 2"}';
        input2.allowedFields = 'Name';
        input2.returnFields = 'Name';
        inputs.add(input2);
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(inputs);
        Test.stopTest();
        
        // Verify
        System.assertEquals(2, results.size(), 'Should return two results');
        System.assertEquals(true, results[0].success, 'First operation should succeed');
        System.assertEquals(true, results[1].success, 'Second operation should succeed');
    }
    
    /**
     * Test mapping of various error types
     */
    @isTest
    static void testErrorMapping() {
        // We can't directly access private methods, but we can trigger them via executeGraphQLMutation
        // by mocking specific error responses or exceptions.
        
        // 1. Test Custom Validation Exception
        Test.setMock(HttpCalloutMock.class, new GraphQLCustomValidationErrorMock());
        
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test"}';
        input.allowedFields = 'Name';
        
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        System.assert(results[0].errorMessage.contains('Validation failed') || results[0].errorMessage.contains('validation requirements'));
    }

    private class GraphQLCustomValidationErrorMock implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(200);
            res.setBody('{"data": {"upsertAccount": {"account": null, "errors": [{"message": "FIELD_CUSTOM_VALIDATION_EXCEPTION: Custom error message"}]}}}');
            return res;
        }
    }
    
    // ========== HTTP MOCK CLASSES ==========
    
    /**
     * Test timeout error handling
     * Requirement 19.5: Map system errors to user-friendly messages
     */
    @isTest
    static void testTimeoutError() {
        // Setup mock for timeout
        Test.setMock(HttpCalloutMock.class, new GraphQLTimeoutMock());
        
        // Prepare input
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test"}';
        input.allowedFields = 'Name';
        
        // Execute
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        // Verify
        System.assertEquals(false, results[0].success, 'Operation should fail');
        System.assert(results[0].errorMessage.contains('took too long'), 
            'Error should mention timeout: ' + results[0].errorMessage);
    }

    /**
     * Test various system errors for coverage
     */
    @isTest
    static void testSystemErrors() {
        // We'll test one representative system error here to avoid creating too many inner classes
        Test.setMock(HttpCalloutMock.class, new GraphQLSystemErrorMock('STORAGE_LIMIT_EXCEEDED'));
        
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test"}';
        input.allowedFields = 'Name';
        
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        System.assert(results[0].errorMessage.contains('storage limit'), 
            'Error should mention storage limit: ' + results[0].errorMessage);
    }

    /**
     * Test API limit exceeded error
     */
    @isTest
    static void testAPILimitError() {
        Test.setMock(HttpCalloutMock.class, new GraphQLSystemErrorMock('REQUEST_LIMIT_EXCEEDED'));
        
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test"}';
        input.allowedFields = 'Name';
        
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        System.assert(results[0].errorMessage.contains('API request limit'), 
            'Error should mention API limit: ' + results[0].errorMessage);
    }

    /**
     * Test various exception mappings for coverage
     */
    @isTest
    static void testExceptionMappingCoverage() {
        // Test INVALID_EMAIL_ADDRESS
        Test.setMock(HttpCalloutMock.class, new GraphQLSystemErrorMock('INVALID_EMAIL_ADDRESS'));
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test"}';
        input.allowedFields = 'Name';
        
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        
        System.assert(results[0].errorMessage.contains('email address'), 
            'Error should mention email: ' + results[0].errorMessage);

        // Test REQUIRED_FIELD_MISSING
        Test.setMock(HttpCalloutMock.class, new GraphQLSystemErrorMock('REQUIRED_FIELD_MISSING'));
        results = Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        System.assert(results[0].errorMessage.contains('required field'), 
            'Error should mention required field: ' + results[0].errorMessage);

        // Test DUPLICATE_VALUE
        Test.setMock(HttpCalloutMock.class, new GraphQLSystemErrorMock('DUPLICATE_VALUE'));
        results = Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        System.assert(results[0].errorMessage.contains('unique value'), 
            'Error should mention unique value: ' + results[0].errorMessage);

        Test.stopTest();
    }

    /**
     * Generic mock for system errors
     */
    private class GraphQLSystemErrorMock implements HttpCalloutMock {
        private String errorMsg;
        
        public GraphQLSystemErrorMock(String msg) {
            this.errorMsg = msg;
        }
        
        public HttpResponse respond(HttpRequest req) {
            throw new CalloutException(this.errorMsg);
        }
    }

    /**
     * Test response with no data
     */
    @isTest
    static void testNoDataReturned() {
        Test.setMock(HttpCalloutMock.class, new GraphQLResponseMock('{"data": null}'));
        
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test"}';
        input.allowedFields = 'Name';
        
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        System.assert(results[0].errorMessage.contains('did not return any data'), 
            'Error should mention no data: ' + results[0].errorMessage);
    }

    /**
     * Test response with no mutation result
     */
    @isTest
    static void testNoMutationResult() {
        Test.setMock(HttpCalloutMock.class, new GraphQLResponseMock('{"data": {}}'));
        
        Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
        input.operation = 'createAccount';
        input.objectApiName = 'Account';
        input.inputFieldsJson = '{"Name": "Test"}';
        input.allowedFields = 'Name';
        
        Test.startTest();
        List<Action_GraphQLProxy.GraphQLProxyOutput> results = 
            Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{input});
        Test.stopTest();
        
        System.assert(results[0].errorMessage.contains('did not complete successfully'), 
            'Error should mention completion failure: ' + results[0].errorMessage);
    }

    /**
     * Generic mock for custom JSON responses
     */
    private class GraphQLResponseMock implements HttpCalloutMock {
        private String jsonBody;
        
        public GraphQLResponseMock(String json) {
            this.jsonBody = json;
        }
        
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(200);
            res.setBody(this.jsonBody);
            return res;
        }
    }

    /**
     * Mock for timeout error
     */
    private class GraphQLTimeoutMock implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest req) {
            throw new CalloutException('Read timed out');
        }
    }

    /**
     * Mock for successful GraphQL response
     */
    private class GraphQLSuccessMock implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(200);
            res.setBody('{"data": {"upsertAccount": {"account": {"Id": "001xx000000ABCD", "Name": "Test Account", "Industry": "Technology"}, "errors": []}}}');
            return res;
        }
    }
    
    /**
     * Mock for required field missing error
     */
    private class GraphQLRequiredFieldErrorMock implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(200);
            res.setBody('{"data": {"upsertOpportunity": {"opportunity": null, "errors": [{"message": "Required field missing: CloseDate", "fields": ["CloseDate"]}]}}}');
            return res;
        }
    }
    
    /**
     * Mock for invalid field error
     */
    private class GraphQLInvalidFieldErrorMock implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(200);
            res.setBody('{"data": {"upsertAccount": {"account": null, "errors": [{"message": "No such column \'InvalidField__c\' on entity \'Account\'", "fields": ["InvalidField__c"]}]}}}');
            return res;
        }
    }
    
    /**
     * Mock for duplicate value error
     */
    private class GraphQLDuplicateErrorMock implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(200);
            res.setBody('{"data": {"upsertAccount": {"account": null, "errors": [{"message": "duplicate value found: ExternalId__c duplicates value on record", "fields": ["ExternalId__c"]}]}}}');
            return res;
        }
    }
    
    /**
     * Mock for permission error (CRUD)
     */
    private class GraphQLPermissionErrorMock implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(200);
            res.setBody('{"data": {"upsertAccount": {"account": null, "errors": [{"message": "insufficient access rights on object id"}]}}}');
            return res;
        }
    }
    
    /**
     * Mock for field-level security error
     */
    private class GraphQLFLSErrorMock implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(200);
            res.setBody('{"data": {"upsertAccount": {"account": null, "errors": [{"message": "Field OwnerId is not writeable", "fields": ["OwnerId"]}]}}}');
            return res;
        }
    }
    
    /**
     * Mock for HTTP error (non-200 status)
     */
    private class GraphQLHTTPErrorMock implements HttpCalloutMock {
        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(500);
            res.setBody('{"error": "Internal Server Error"}');
            return res;
        }
    }
}
