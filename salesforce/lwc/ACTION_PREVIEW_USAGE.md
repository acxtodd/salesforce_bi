# Action Preview and Confirmation - Developer Guide

## Overview
This guide explains how to use the action preview and confirmation functionality in the Ascendix AI Search LWC component.

## How It Works

### 1. Agent Suggests an Action
The agent can suggest actions by including special markers in the response:

```
[ACTION:create_opportunity|Name:ACME Deal|Amount:500000|CloseDate:2026-03-15|StageName:Prospecting]
```

### 2. Parsing Action Suggestions
The LWC automatically parses action markers using the `parseActionSuggestions()` method:

```javascript
// Format: [ACTION:actionName|Field1:Value1|Field2:Value2|...]
const actionData = this.parseActionSuggestions(answerText);
// Returns: { actionName: 'create_opportunity', inputs: { Name: 'ACME Deal', Amount: 500000, ... } }
```

### 3. Showing the Preview Modal
To display the action preview modal programmatically:

```javascript
this.showActionPreviewModal({
    actionName: 'create_opportunity',
    inputs: {
        Name: 'ACME Deal',
        Amount: 500000,
        CloseDate: '2026-03-15',
        StageName: 'Prospecting'
    }
});
```

### 4. User Confirms or Cancels
- **Confirm**: Generates confirmation token and calls `/action` endpoint
- **Cancel**: Closes modal without executing action

### 5. Action Execution
When user confirms:
1. Confirmation token generated: `token_{hash}_{timestamp}`
2. Request sent to `/action` endpoint via Apex
3. Response handled with success or error display

## API Contract

### Request to /action Endpoint
```json
{
  "actionName": "create_opportunity",
  "inputs": {
    "Name": "ACME Deal",
    "Amount": 500000,
    "CloseDate": "2026-03-15",
    "StageName": "Prospecting"
  },
  "salesforceUserId": "005xx000001234567",
  "sessionId": "session_1731600000_abc123",
  "confirmationToken": "token_123456789_1731600000"
}
```

### Success Response
```json
{
  "success": true,
  "recordIds": ["006xx000001234567"],
  "outputValues": {
    "id": "006xx000001234567"
  },
  "actionName": "create_opportunity",
  "requestId": "req-abc-123",
  "trace": {
    "executionMs": 850,
    "totalMs": 920
  }
}
```

### Error Response
```json
{
  "error": "You've reached the daily limit of 20 for this action. Try again tomorrow."
}
```

## Error Handling

### Error Types and Messages

| HTTP Status | Error Type | User Message | Retry Available |
|-------------|-----------|--------------|-----------------|
| 400 | Validation | "Validation error: {details}" | No |
| 403 | Permission | "You don't have permission to execute this action." | No |
| 429 | Rate Limit | "You've reached the daily limit of {N} for this action. Try again tomorrow." | No |
| 503 | Disabled | "This action is temporarily unavailable. Please try again later." | No |
| 502 | Salesforce API | "Action execution failed: {details}" | Yes |
| 504 | Timeout | "The action took too long to execute. Please try again." | Yes |

### Handling Errors in Code

```javascript
try {
    const response = await callActionEndpoint({ requestBodyJson });
    this.handleActionSuccess(response.recordIds, actionName);
} catch (error) {
    this.handleActionError(error);
}
```

## Field Value Formatting

The component automatically formats field values for display:

| Data Type | Format | Example |
|-----------|--------|---------|
| String | As-is | "ACME Deal" |
| Number (< 1000) | Plain number | "500" |
| Number (>= 1000) | Currency | "$500,000.00" |
| Boolean | Yes/No | "Yes" |
| Date | ISO string | "2026-03-15" |
| Object | JSON | `{ "key": "value" }` |
| Null/Undefined | (empty) | "(empty)" |

## Customization

### Custom Field Labels
Field labels are auto-generated from camelCase:
- `Name` → "Name"
- `CloseDate` → "Close Date"
- `StageName` → "Stage Name"

To customize, modify the `actionPreviewFields` getter:

```javascript
get actionPreviewFields() {
    return Object.entries(this.actionPreviewData.inputs).map(([key, value]) => {
        return {
            key: key,
            label: this.getCustomLabel(key), // Custom label logic
            value: this.formatFieldValue(value),
            rawValue: value
        };
    });
}
```

### Custom Value Formatting
To add custom formatting for specific field types:

```javascript
formatFieldValue(value) {
    // Add custom logic here
    if (this.isDateField(value)) {
        return new Date(value).toLocaleDateString();
    }
    
    // Default formatting
    return this.defaultFormatFieldValue(value);
}
```

## Testing

### Manual Testing Checklist
- [ ] Preview modal displays all fields correctly
- [ ] Confirm button executes action
- [ ] Cancel button closes modal without executing
- [ ] Success toast appears with record link
- [ ] Record navigation works
- [ ] Error messages display correctly
- [ ] Rate limit error shows limit information
- [ ] Disabled action shows unavailable message
- [ ] Validation errors show field details
- [ ] Timeout errors show retry option

### Automated Testing
See `salesforce/lwc/ascendixAiSearch/__tests__/ascendixAiSearch.test.js` for existing tests.

To add action preview tests (optional task 19.4):

```javascript
describe('Action Preview and Confirmation', () => {
    it('should display action preview modal', async () => {
        // Test implementation
    });
    
    it('should execute action on confirm', async () => {
        // Test implementation
    });
    
    it('should handle rate limit errors', async () => {
        // Test implementation
    });
});
```

## Accessibility

### Keyboard Navigation
- **Tab**: Navigate between buttons
- **Enter**: Activate focused button
- **Escape**: Close modal

### Screen Reader Support
- Modal has `role="dialog"` and `aria-modal="true"`
- Modal title has `aria-labelledby`
- Table has proper header structure
- All buttons have descriptive labels

### Focus Management
- Focus moves to modal when opened
- Focus returns to trigger element when closed
- Focus trapped within modal while open

## Security Considerations

### Confirmation Token
- Generated client-side for POC
- Format: `token_{hash}_{timestamp}`
- Production should use server-signed JWT tokens
- Should include expiration and single-use enforcement

### Input Validation
- All inputs validated server-side
- Client-side validation for UX only
- Never trust client-generated tokens in production

### Permission Checks
- Server validates user permissions
- Client displays appropriate error messages
- No sensitive data in error messages

## Troubleshooting

### Modal Not Appearing
1. Check `actionPreviewData` is set correctly
2. Verify `showActionPreview` is true
3. Check browser console for errors

### Action Not Executing
1. Verify Named Credential is configured
2. Check API Gateway endpoint is accessible
3. Review Apex debug logs
4. Verify user has AI_Agent_Actions_Editor permission set

### Confirmation Token Invalid
1. Check token generation logic
2. Verify timestamp is recent (< 5 minutes)
3. Ensure token format matches server expectations

### Record Navigation Not Working
1. Verify record ID format (15 or 18 characters)
2. Check NavigationMixin is imported
3. Ensure user has access to record

## Best Practices

1. **Always validate inputs** - Both client and server side
2. **Provide clear error messages** - Help users understand what went wrong
3. **Show loading states** - Keep users informed during execution
4. **Enable keyboard navigation** - Support all interaction methods
5. **Test with different user permissions** - Ensure proper access control
6. **Log all actions** - Maintain audit trail in AI_Action_Audit__c
7. **Handle rate limits gracefully** - Show clear messages with reset time
8. **Use descriptive field labels** - Make preview easy to understand
9. **Format values appropriately** - Currency, dates, booleans, etc.
10. **Provide record links** - Allow easy navigation to created/updated records

## Related Documentation

- [Task 19 Implementation Summary](./TASK-19-IMPLEMENTATION-SUMMARY.md)
- [Action Lambda Documentation](../../lambda/action/README.md)
- [Requirements Document](../../.kiro/specs/salesforce-ai-search-poc/requirements.md)
- [Design Document](../../.kiro/specs/salesforce-ai-search-poc/design.md)

## Support

For issues or questions:
1. Check CloudWatch logs for Lambda errors
2. Review Salesforce debug logs for Apex errors
3. Check browser console for JavaScript errors
4. Review AI_Action_Audit__c records for execution history
