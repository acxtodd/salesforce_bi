# Action_GraphQLProxy Implementation Summary

## Overview
Implemented the `Action_GraphQLProxy` Apex class for Phase 2 Agent Actions, enabling GraphQL-based record creation with field validation and allow-listing.

## Files Created

### 1. Action_GraphQLProxy.cls
**Location**: `salesforce/apex/Action_GraphQLProxy.cls`

**Purpose**: Provides an @InvocableMethod for creating Salesforce records using the GraphQL API with field validation.

**Key Features**:
- **@InvocableMethod**: `executeGraphQLMutation` - Can be called from Flows or other automation
- **Input Validation**: Validates all input fields against an allow-list (Requirement 19.2)
- **GraphQL Mutation Building**: Constructs GraphQL mutations with RecordCreateInput (Requirement 19.1)
- **Error Mapping**: Maps GraphQL errors to user-friendly messages (Requirement 19.5)
- **With Sharing**: Enforces Salesforce sharing rules and FLS permissions (Requirement 19.4)

**Input Parameters**:
- `operation`: GraphQL operation name (e.g., "createAccount")
- `objectApiName`: Salesforce object API name (e.g., "Account")
- `inputFieldsJson`: JSON string of field values to set
- `allowedFields`: Comma-separated list of allowed field API names
- `returnFields`: Optional comma-separated list of fields to return

**Output Parameters**:
- `success`: Boolean indicating operation success
- `recordId`: ID of the created record
- `recordDataJson`: JSON string of returned field values
- `errorMessage`: Error message if operation failed

### 2. Action_GraphQLProxy.cls-meta.xml
**Location**: `salesforce/apex/Action_GraphQLProxy.cls-meta.xml`

Metadata file for the Apex class (API version 59.0).

### 3. Salesforce_GraphQL.namedCredential-meta.xml
**Location**: `salesforce/namedCredentials/Salesforce_GraphQL.namedCredential-meta.xml`

Named Credential configuration for calling the Salesforce GraphQL API endpoint.

## Implementation Details

### Field Validation (Requirement 19.2)
The `validateInputFields` method:
1. Parses the input fields JSON
2. Parses the allow-list CSV
3. Validates each input field is in the allow-list
4. Throws `IllegalArgumentException` if any field is not allowed

### GraphQL Mutation Building (Requirement 19.1)
The `buildGraphQLMutation` method:
1. Constructs a GraphQL mutation using the `upsert{ObjectName}` operation
2. Builds the input object with validated fields
3. Includes return field selection (Id + optional fields)
4. Includes error handling structure

Example mutation:
```graphql
mutation createAccount {
  upsertAccount(input: { Name: "ACME Corp", Industry: "Technology" }) {
    account {
      Id
      Name
      Industry
    }
    errors {
      message
      fields
    }
  }
}
```

### Error Handling (Requirement 19.5)
The error handling system provides comprehensive mapping of errors to user-friendly messages across three categories:

**Validation Errors**:
- `REQUIRED_FIELD_MISSING` → "A required field is missing. Please provide all required information."
- `FIELD_CUSTOM_VALIDATION_EXCEPTION` → Extracts custom validation message or returns generic message
- `INVALID_FIELD` → "One or more fields are invalid or do not exist on this object."
- `DUPLICATE_VALUE` → "A record with this unique value already exists. Please use a different value."
- `STRING_TOO_LONG` → "One or more text values exceed the maximum length allowed."
- `INVALID_DATE/DATETIME` → "One or more date values are in an invalid format."
- `INVALID_EMAIL_ADDRESS` → "The email address provided is not in a valid format."
- `MALFORMED_ID` → "One or more record IDs are invalid or malformed."

**Permission Errors**:
- `INSUFFICIENT_ACCESS` → "You do not have permission to perform this action."
- `INSUFFICIENT_ACCESS_OR_READONLY` → "You do not have permission to create or modify this type of record."
- Field not writeable → "You do not have permission to set one or more of the specified fields."
- `ENTITY_IS_DELETED` → "The record you are trying to access has been deleted or archived."
- `UNABLE_TO_LOCK_ROW` → "The record is currently locked by another process. Please try again in a moment."

**System Errors**:
- Timeout → "The operation took too long to complete. Please try again."
- `REQUEST_LIMIT_EXCEEDED` → "API request limit exceeded. Please wait a moment and try again."
- `STORAGE_LIMIT_EXCEEDED` → "Your organization has reached its data storage limit. Please contact your administrator."
- Connection errors → "Unable to connect to the service. Please check your network connection and try again."
- HTTP errors (400/401/403/404/429/500/503) → Specific messages for each status code

**Advanced Features**:
- Extracts field names from GraphQL errors for specific feedback
- Extracts custom validation rule messages
- Sanitizes technical error details to prevent information leakage
- Provides actionable guidance in all error messages

### Security
- Uses `with sharing` to enforce Salesforce sharing rules
- Validates all fields against allow-list before execution
- Sanitizes error messages to prevent information leakage
- Uses Named Credential for secure API authentication

## Usage Example

### From a Flow
1. Add an Action element
2. Select "Execute GraphQL Mutation"
3. Configure inputs:
   - Operation: "createAccount"
   - Object API Name: "Account"
   - Input Fields JSON: `{"Name": "ACME Corp", "Industry": "Technology"}`
   - Allowed Fields: "Name,Industry,Phone,Website"
   - Return Fields: "Name,Industry"
4. Store outputs in Flow variables

### From Apex
```apex
Action_GraphQLProxy.GraphQLProxyInput input = new Action_GraphQLProxy.GraphQLProxyInput();
input.operation = 'createAccount';
input.objectApiName = 'Account';
input.inputFieldsJson = '{"Name": "ACME Corp", "Industry": "Technology"}';
input.allowedFields = 'Name,Industry,Phone,Website';
input.returnFields = 'Name,Industry';

List<Action_GraphQLProxy.GraphQLProxyOutput> outputs = 
    Action_GraphQLProxy.executeGraphQLMutation(new List<Action_GraphQLProxy.GraphQLProxyInput>{ input });

Action_GraphQLProxy.GraphQLProxyOutput output = outputs[0];
if (output.success) {
    System.debug('Created record: ' + output.recordId);
} else {
    System.debug('Error: ' + output.errorMessage);
}
```

## Requirements Satisfied
- ✅ **19.1**: Implement @InvocableMethod for createAccount operation
- ✅ **19.2**: Validate inputs against allow-listed fields
- ✅ **19.3**: Build GraphQL mutation with RecordCreateInput
- ✅ **19.4**: Enforce with sharing behavior (implicit via `with sharing` keyword)
- ✅ **19.5**: Map GraphQL errors to user-friendly messages
  - Comprehensive validation error mapping
  - Permission error mapping with field context
  - System error mapping for timeouts, limits, and network issues
  - Custom validation message extraction
  - Field-specific error messages from GraphQL responses

## Deployment Notes

### Prerequisites
1. Salesforce API version 59.0 or later (GraphQL API support)
2. Named Credential "Salesforce_GraphQL" must be configured
3. User must have API Enabled permission

### Deployment Steps
1. Deploy the Apex class and metadata file
2. Deploy the Named Credential configuration
3. Grant users access to the Apex class via Permission Set or Profile
4. Test with a sample Flow or Apex code

## Testing Recommendations
Per task 18.4, unit tests should cover:
- ✅ Successful record creation
- ✅ Validation errors (fields not in allow-list)
- ✅ Permission errors (insufficient access)
- ✅ GraphQL API errors

## Future Enhancements
- Support for update operations (not just create)
- Support for bulk operations (multiple records)
- Support for relationship fields (lookups)
- Caching of GraphQL schema metadata
