/**
 * Action_GraphQLProxy - Apex class for executing GraphQL mutations with allow-listed fields
 * 
 * This class provides an @InvocableMethod for creating Salesforce records using GraphQL API.
 * It validates inputs against allow-listed fields and builds GraphQL mutations with RecordCreateInput.
 * 
 * Phase 2 - Agent Actions
 * Requirements: 19.1, 19.2
 */
public with sharing class Action_GraphQLProxy {
    
    private static final String GRAPHQL_ENDPOINT = '/services/data/v59.0/graphql';
    private static final Integer TIMEOUT_MS = 30000; // 30 seconds
    
    /**
     * Input wrapper for the invocable method
     */
    public class GraphQLProxyInput {
        @InvocableVariable(label='Operation' description='GraphQL operation name (e.g., createAccount)' required=true)
        public String operation;
        
        @InvocableVariable(label='Object API Name' description='Salesforce object API name (e.g., Account)' required=true)
        public String objectApiName;
        
        @InvocableVariable(label='Input Fields JSON' description='JSON string of field values to set' required=true)
        public String inputFieldsJson;
        
        @InvocableVariable(label='Allowed Fields' description='Comma-separated list of allowed field API names' required=true)
        public String allowedFields;
        
        @InvocableVariable(label='Return Fields' description='Comma-separated list of fields to return' required=false)
        public String returnFields;
    }
    
    /**
     * Output wrapper for the invocable method
     */
    public class GraphQLProxyOutput {
        @InvocableVariable(label='Success' description='Whether the operation succeeded')
        public Boolean success;
        
        @InvocableVariable(label='Record ID' description='ID of the created record')
        public String recordId;
        
        @InvocableVariable(label='Record Data' description='JSON string of returned field values')
        public String recordDataJson;
        
        @InvocableVariable(label='Error Message' description='Error message if operation failed')
        public String errorMessage;
    }
    
    /**
     * Invocable method for creating records via GraphQL
     * 
     * @param inputs List of GraphQLProxyInput containing operation details
     * @return List of GraphQLProxyOutput with results
     */
    @InvocableMethod(label='Execute GraphQL Mutation' description='Creates a Salesforce record using GraphQL API with field validation' category='Agent Actions')
    public static List<GraphQLProxyOutput> executeGraphQLMutation(List<GraphQLProxyInput> inputs) {
        List<GraphQLProxyOutput> outputs = new List<GraphQLProxyOutput>();
        
        for (GraphQLProxyInput input : inputs) {
            GraphQLProxyOutput output = new GraphQLProxyOutput();
            
            try {
                // Validate inputs against allow-list
                Map<String, Object> inputFields = validateInputFields(input.inputFieldsJson, input.allowedFields);
                
                // Build GraphQL mutation
                String mutation = buildGraphQLMutation(input.operation, input.objectApiName, inputFields, input.returnFields);
                
                // Execute GraphQL mutation
                Map<String, Object> result = executeGraphQL(mutation);
                
                // Parse response
                output = parseGraphQLResponse(result, input.operation);
                
            } catch (Exception e) {
                output.success = false;
                output.errorMessage = mapErrorToUserFriendlyMessage(e);
                System.debug('Error in executeGraphQLMutation: ' + e.getMessage() + '\n' + e.getStackTraceString());
            }
            
            outputs.add(output);
        }
        
        return outputs;
    }
    
    /**
     * Validate input fields against allow-list
     * Requirement 19.2: Validate that all fields are in the allow-list
     * 
     * @param inputFieldsJson JSON string of field values
     * @param allowedFieldsCsv Comma-separated list of allowed field names
     * @return Map of validated field names to values
     * @throws IllegalArgumentException if any field is not in allow-list
     */
    private static Map<String, Object> validateInputFields(String inputFieldsJson, String allowedFieldsCsv) {
        // Parse input fields
        Map<String, Object> inputFields = (Map<String, Object>) JSON.deserializeUntyped(inputFieldsJson);
        
        // Parse allowed fields
        Set<String> allowedFieldsSet = new Set<String>();
        for (String field : allowedFieldsCsv.split(',')) {
            allowedFieldsSet.add(field.trim());
        }
        
        // Validate each input field
        for (String fieldName : inputFields.keySet()) {
            if (!allowedFieldsSet.contains(fieldName)) {
                throw new IllegalArgumentException('Field "' + fieldName + '" is not in the allow-list for this operation');
            }
        }
        
        return inputFields;
    }
    
    /**
     * Build GraphQL mutation with RecordCreateInput
     * Requirement 19.1: Build GraphQL mutation with RecordCreateInput
     * 
     * @param operation Operation name (e.g., 'createAccount')
     * @param objectApiName Salesforce object API name
     * @param inputFields Map of field names to values
     * @param returnFieldsCsv Comma-separated list of fields to return
     * @return GraphQL mutation string
     */
    private static String buildGraphQLMutation(String operation, String objectApiName, Map<String, Object> inputFields, String returnFieldsCsv) {
        // Build the input object
        String inputObject = buildInputObject(inputFields);
        
        // Build return fields selection
        String returnFieldsSelection = buildReturnFieldsSelection(returnFieldsCsv);
        
        // Build the complete mutation
        String mutation = 'mutation ' + operation + ' {' +
            '  upsert' + objectApiName + '(input: ' + inputObject + ') {' +
            '    ' + objectApiName.toLowerCase() + ' {' +
            '      Id' +
            returnFieldsSelection +
            '    }' +
            '    errors {' +
            '      message' +
            '      fields' +
            '    }' +
            '  }' +
            '}';
        
        return mutation;
    }
    
    /**
     * Build GraphQL input object from field map
     * 
     * @param inputFields Map of field names to values
     * @return GraphQL input object string
     */
    private static String buildInputObject(Map<String, Object> inputFields) {
        List<String> fieldPairs = new List<String>();
        
        for (String fieldName : inputFields.keySet()) {
            Object fieldValue = inputFields.get(fieldName);
            String formattedValue = formatGraphQLValue(fieldValue);
            fieldPairs.add(fieldName + ': ' + formattedValue);
        }
        
        return '{ ' + String.join(fieldPairs, ', ') + ' }';
    }
    
    /**
     * Format a value for GraphQL syntax
     * 
     * @param value The value to format
     * @return Formatted value string
     */
    private static String formatGraphQLValue(Object value) {
        if (value == null) {
            return 'null';
        } else if (value instanceof String) {
            // Escape quotes and backslashes
            String strValue = (String) value;
            strValue = strValue.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r');
            return '"' + strValue + '"';
        } else if (value instanceof Boolean || value instanceof Integer || value instanceof Long || value instanceof Decimal) {
            return String.valueOf(value);
        } else if (value instanceof Date) {
            return '"' + String.valueOf(value) + '"';
        } else if (value instanceof DateTime) {
            return '"' + ((DateTime) value).format('yyyy-MM-dd\'T\'HH:mm:ss\'Z\'') + '"';
        } else {
            // For other types, convert to JSON string
            return '"' + String.valueOf(value) + '"';
        }
    }
    
    /**
     * Build return fields selection for GraphQL query
     * 
     * @param returnFieldsCsv Comma-separated list of field names
     * @return GraphQL field selection string
     */
    private static String buildReturnFieldsSelection(String returnFieldsCsv) {
        if (String.isBlank(returnFieldsCsv)) {
            return '';
        }
        
        List<String> fields = new List<String>();
        for (String field : returnFieldsCsv.split(',')) {
            String trimmedField = field.trim();
            if (String.isNotBlank(trimmedField) && trimmedField != 'Id') {
                fields.add('      ' + trimmedField);
            }
        }
        
        return fields.isEmpty() ? '' : '\n' + String.join(fields, '\n');
    }
    
    /**
     * Execute GraphQL mutation via Salesforce GraphQL API
     * Requirement 19.3: Call Salesforce GraphQL endpoint
     * 
     * @param mutation GraphQL mutation string
     * @return Parsed response map
     * @throws CalloutException if HTTP request fails
     */
    private static Map<String, Object> executeGraphQL(String mutation) {
        // Build HTTP request
        HttpRequest req = new HttpRequest();
        req.setEndpoint('callout:Salesforce_GraphQL' + GRAPHQL_ENDPOINT);
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setTimeout(TIMEOUT_MS);
        
        // Build request body
        Map<String, Object> requestBody = new Map<String, Object>{
            'query' => mutation
        };
        req.setBody(JSON.serialize(requestBody));
        
        // Send request
        Http http = new Http();
        HttpResponse res = http.send(req);
        
        // Check response status
        if (res.getStatusCode() != 200) {
            throw new CalloutException('GraphQL API returned status ' + res.getStatusCode() + ': ' + res.getBody());
        }
        
        // Parse response
        Map<String, Object> responseData = (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
        
        return responseData;
    }
    
    /**
     * Parse GraphQL response and extract record data
     * Requirement 19.3: Return record ID and selected fields
     * Requirement 19.5: Map GraphQL errors to user-friendly messages
     * 
     * @param responseData GraphQL response map
     * @param operation Operation name
     * @return GraphQLProxyOutput with parsed data
     */
    private static GraphQLProxyOutput parseGraphQLResponse(Map<String, Object> responseData, String operation) {
        GraphQLProxyOutput output = new GraphQLProxyOutput();
        
        try {
            // Check for top-level errors (syntax, authentication, etc.)
            if (responseData.containsKey('errors')) {
                List<Object> errors = (List<Object>) responseData.get('errors');
                if (!errors.isEmpty()) {
                    Map<String, Object> firstError = (Map<String, Object>) errors[0];
                    String errorMsg = (String) firstError.get('message');
                    output.success = false;
                    output.errorMessage = mapGraphQLErrorMessage(errorMsg, firstError);
                    return output;
                }
            }
            
            // Extract data
            Map<String, Object> data = (Map<String, Object>) responseData.get('data');
            if (data == null) {
                output.success = false;
                output.errorMessage = 'The service did not return any data. Please try again.';
                return output;
            }
            
            // Find the mutation result (key varies by operation)
            Map<String, Object> mutationResult = null;
            for (String key : data.keySet()) {
                if (key.startsWith('upsert')) {
                    mutationResult = (Map<String, Object>) data.get(key);
                    break;
                }
            }
            
            if (mutationResult == null) {
                output.success = false;
                output.errorMessage = 'The operation did not complete successfully. Please try again.';
                return output;
            }
            
            // Check for mutation errors (validation, permissions, etc.)
            if (mutationResult.containsKey('errors')) {
                List<Object> mutationErrors = (List<Object>) mutationResult.get('errors');
                if (!mutationErrors.isEmpty()) {
                    Map<String, Object> firstError = (Map<String, Object>) mutationErrors[0];
                    String errorMsg = (String) firstError.get('message');
                    output.success = false;
                    output.errorMessage = mapGraphQLErrorMessage(errorMsg, firstError);
                    return output;
                }
            }
            
            // Extract record data (key varies by object type)
            Map<String, Object> recordData = null;
            for (String key : mutationResult.keySet()) {
                if (key != 'errors' && mutationResult.get(key) instanceof Map<String, Object>) {
                    recordData = (Map<String, Object>) mutationResult.get(key);
                    break;
                }
            }
            
            if (recordData == null) {
                output.success = false;
                output.errorMessage = 'The record was not created successfully. Please try again.';
                return output;
            }
            
            // Extract record ID
            output.recordId = (String) recordData.get('Id');
            
            if (String.isBlank(output.recordId)) {
                output.success = false;
                output.errorMessage = 'The record was created but no ID was returned. Please contact your administrator.';
                return output;
            }
            
            // Serialize record data to JSON
            output.recordDataJson = JSON.serialize(recordData);
            
            output.success = true;
            return output;
            
        } catch (Exception e) {
            // Handle any unexpected parsing errors
            output.success = false;
            output.errorMessage = 'An error occurred while processing the response. Please contact your administrator.';
            System.debug('Error parsing GraphQL response: ' + e.getMessage() + '\n' + e.getStackTraceString());
            return output;
        }
    }
    
    /**
     * Map GraphQL error message to user-friendly message
     * Handles errors returned by the GraphQL API
     * 
     * @param errorMsg Error message from GraphQL
     * @param errorObj Full error object with additional context
     * @return User-friendly error message
     */
    private static String mapGraphQLErrorMessage(String errorMsg, Map<String, Object> errorObj) {
        if (String.isBlank(errorMsg)) {
            return 'An unknown error occurred. Please contact your administrator.';
        }
        
        // Extract error code if available
        String errorCode = '';
        if (errorObj.containsKey('errorCode')) {
            errorCode = (String) errorObj.get('errorCode');
        }
        
        // Extract affected fields if available
        List<String> affectedFields = new List<String>();
        if (errorObj.containsKey('fields')) {
            List<Object> fields = (List<Object>) errorObj.get('fields');
            for (Object field : fields) {
                affectedFields.add((String) field);
            }
        }
        
        // Map based on error message patterns
        String lowerMsg = errorMsg.toLowerCase();
        
        // Validation errors
        if (lowerMsg.contains('required') || lowerMsg.contains('missing')) {
            if (!affectedFields.isEmpty()) {
                return 'Required field missing: ' + String.join(affectedFields, ', ') + '. Please provide a value.';
            }
            return 'One or more required fields are missing. Please provide all required information.';
        }
        
        if (lowerMsg.contains('invalid') && lowerMsg.contains('field')) {
            if (!affectedFields.isEmpty()) {
                return 'Invalid field: ' + String.join(affectedFields, ', ') + '. This field does not exist or cannot be set.';
            }
            return 'One or more fields are invalid or cannot be set.';
        }
        
        if (lowerMsg.contains('duplicate')) {
            if (!affectedFields.isEmpty()) {
                return 'Duplicate value for field: ' + String.join(affectedFields, ', ') + '. Please use a unique value.';
            }
            return 'A record with this value already exists. Please use a unique value.';
        }
        
        if (errorMsg.contains('FIELD_CUSTOM_VALIDATION_EXCEPTION')) {
            // Extract validation rule message if available
            String validationMsg = extractValidationMessage(errorMsg);
            if (String.isNotBlank(validationMsg)) {
                return 'Validation failed: ' + validationMsg;
            }
            return 'The data you provided does not meet validation requirements.';
        }

        if (lowerMsg.contains('not writeable')) {
            if (!affectedFields.isEmpty()) {
                return 'You do not have permission to set field: ' + String.join(affectedFields, ', ') + '.';
            }
            return 'You do not have permission to set this field.';
        }
        
        // Permission errors
        if (lowerMsg.contains('permission') || lowerMsg.contains('access') || lowerMsg.contains('unauthorized')) {
            if (!affectedFields.isEmpty()) {
                return 'You do not have permission to set field: ' + String.join(affectedFields, ', ') + '.';
            }
            return 'You do not have permission to perform this action.';
        }
        
        // System errors
        if (lowerMsg.contains('internal error') || lowerMsg.contains('system error')) {
            return 'A system error occurred. Please try again later.';
        }
        
        // If the error message is already user-friendly (short and clear), return it
        if (errorMsg.length() < 150 && !errorMsg.contains('Exception') && !errorMsg.contains('null')) {
            return errorMsg;
        }
        
        // Default: sanitized generic message
        return 'An error occurred while processing your request. Please contact your administrator.';
    }
    
    /**
     * Map exception to user-friendly error message
     * Requirement 19.5: Map GraphQL errors to user-friendly messages
     * 
     * Handles three main categories:
     * 1. Validation Errors - Data format, required fields, custom validation rules
     * 2. Permission Errors - CRUD, FLS, sharing rule violations
     * 3. System Errors - Timeouts, API limits, network issues
     * 
     * @param e Exception to map
     * @return User-friendly error message
     */
    private static String mapErrorToUserFriendlyMessage(Exception e) {
        String errorMessage = e.getMessage();
        String errorType = e.getTypeName();
        
        // === VALIDATION ERRORS ===
        
        // Required field validation
        if (errorMessage.contains('REQUIRED_FIELD_MISSING')) {
            return 'A required field is missing. Please provide all required information.';
        }
        
        // Custom validation rules
        if (errorMessage.contains('FIELD_CUSTOM_VALIDATION_EXCEPTION')) {
            // Extract validation rule message if available
            String validationMsg = extractValidationMessage(errorMessage);
            if (String.isNotBlank(validationMsg)) {
                return 'Validation failed: ' + validationMsg;
            }
            return 'The data you provided does not meet validation requirements.';
        }
        
        // Invalid field names or types
        if (errorMessage.contains('INVALID_FIELD') || errorMessage.contains('No such column')) {
            return 'One or more fields are invalid or do not exist on this object.';
        }
        
        // Duplicate value on unique field
        if (errorMessage.contains('DUPLICATE_VALUE') || errorMessage.contains('duplicate value found')) {
            return 'A record with this unique value already exists. Please use a different value.';
        }
        
        // Invalid field value or format
        if (errorMessage.contains('INVALID_FIELD_FOR_INSERT_UPDATE') || 
            errorMessage.contains('INVALID_TYPE_FOR_OPERATION')) {
            return 'One or more field values are invalid or in the wrong format.';
        }
        
        // String too long
        if (errorMessage.contains('STRING_TOO_LONG')) {
            return 'One or more text values exceed the maximum length allowed.';
        }
        
        // Invalid date/datetime format
        if (errorMessage.contains('INVALID_DATE') || errorMessage.contains('INVALID_DATETIME')) {
            return 'One or more date values are in an invalid format.';
        }
        
        // Invalid email format
        if (errorMessage.contains('INVALID_EMAIL_ADDRESS')) {
            return 'The email address provided is not in a valid format.';
        }
        
        // Invalid ID format
        if (errorMessage.contains('MALFORMED_ID') || errorMessage.contains('INVALID_ID_FIELD')) {
            return 'One or more record IDs are invalid or malformed.';
        }
        
        // Allow-list validation (from our custom validation)
        if (errorMessage.contains('not in the allow-list')) {
            return errorMessage; // Already user-friendly
        }
        
        // === PERMISSION ERRORS ===
        
        // Insufficient access (CRUD)
        if (errorMessage.contains('INSUFFICIENT_ACCESS_OR_READONLY') || 
            errorMessage.contains('INSUFFICIENT_ACCESS_ON_CROSS_REFERENCE_ENTITY')) {
            return 'You do not have permission to create or modify this type of record.';
        }
        
        // Generic insufficient access
        if (errorMessage.contains('INSUFFICIENT_ACCESS')) {
            return 'You do not have permission to perform this action.';
        }
        
        // Field-level security violation
        if (errorMessage.contains('INVALID_FIELD_FOR_INSERT_UPDATE') && 
            errorMessage.contains('not writeable')) {
            return 'You do not have permission to set one or more of the specified fields.';
        }
        
        // Object not accessible
        if (errorMessage.contains('ENTITY_IS_DELETED') || errorMessage.contains('ENTITY_IS_ARCHIVED')) {
            return 'The record you are trying to access has been deleted or archived.';
        }
        
        // Record locked
        if (errorMessage.contains('UNABLE_TO_LOCK_ROW')) {
            return 'The record is currently locked by another process. Please try again in a moment.';
        }
        
        // === SYSTEM ERRORS ===
        
        // Timeout errors
        if (errorMessage.contains('timeout') || errorMessage.contains('Read timed out') || 
            errorType == 'System.CalloutException' && errorMessage.contains('timed out')) {
            return 'The operation took too long to complete. Please try again.';
        }
        
        // API limits exceeded
        if (errorMessage.contains('REQUEST_LIMIT_EXCEEDED') || errorMessage.contains('TooManyRequests')) {
            return 'API request limit exceeded. Please wait a moment and try again.';
        }
        
        // Storage limits
        if (errorMessage.contains('STORAGE_LIMIT_EXCEEDED')) {
            return 'Your organization has reached its data storage limit. Please contact your administrator.';
        }
        
        // Network/connection errors
        if (errorType == 'System.CalloutException' && 
            (errorMessage.contains('Connection refused') || errorMessage.contains('Connection reset'))) {
            return 'Unable to connect to the service. Please check your network connection and try again.';
        }
        
        // HTTP error codes from GraphQL API
        if (errorMessage.contains('GraphQL API returned status')) {
            if (errorMessage.contains('status 400')) {
                return 'The request was invalid. Please check your input and try again.';
            } else if (errorMessage.contains('status 401') || errorMessage.contains('status 403')) {
                return 'Authentication failed. Please contact your administrator.';
            } else if (errorMessage.contains('status 404')) {
                return 'The requested resource was not found.';
            } else if (errorMessage.contains('status 429')) {
                return 'Too many requests. Please wait a moment and try again.';
            } else if (errorMessage.contains('status 500') || errorMessage.contains('status 503')) {
                return 'The service is temporarily unavailable. Please try again later.';
            }
        }
        
        // Generic system error
        if (errorType == 'System.CalloutException') {
            return 'A system error occurred while communicating with the service. Please try again.';
        }
        
        // Unexpected errors
        if (errorType == 'System.NullPointerException') {
            return 'An unexpected error occurred. Please contact your administrator.';
        }
        
        // === DEFAULT ===
        // Generic error message with sanitized details
        // Don't expose internal error details to end users
        return 'An error occurred while processing your request. Please contact your administrator if the problem persists.';
    }
    
    /**
     * Extract validation rule message from error string
     * 
     * @param errorMessage Full error message
     * @return Extracted validation message or empty string
     */
    private static String extractValidationMessage(String errorMessage) {
        // Validation messages often appear after a colon or in brackets
        if (errorMessage.contains(':')) {
            List<String> parts = errorMessage.split(':');
            if (parts.size() > 1) {
                String msg = parts[parts.size() - 1].trim();
                // Remove any error codes or technical details
                msg = msg.replaceAll('\\[.*?\\]', '').trim();
                if (msg.length() > 0 && msg.length() < 200) {
                    return msg;
                }
            }
        }
        return '';
    }
}
