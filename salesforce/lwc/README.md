# Ascendix AI Search Lightning Web Component

## Overview

The Ascendix AI Search LWC provides a natural language search interface for Salesforce users to query their data using AI-powered search and answer generation. The component integrates with the AWS-hosted RAG system via Private API Gateway.

## Features

### Core Functionality
- **Natural Language Queries**: Users can ask questions in plain English
- **Streaming Answers**: Responses are displayed progressively as they're generated
- **Citations**: All answers include citations to source Salesforce records
- **Facet Filters**: Filter results by Region, Business Unit, and Quarter
- **Record Context**: Automatically includes current record context when placed on record pages

### User Experience
- **Skeleton Loading States**: Visual feedback during answer generation
- **Error Handling**: Friendly error messages with retry options for transient errors
- **Citation Preview**: View record previews or navigate directly to Salesforce records
- **Responsive Design**: Works on desktop and mobile devices

### Accessibility
- **Keyboard Navigation**: Full keyboard support (Ctrl+Enter to submit, Escape to close modals)
- **ARIA Labels**: Comprehensive screen reader support
- **Focus Management**: Visible focus states on all interactive elements
- **High Contrast Mode**: Enhanced visibility in high contrast mode
- **Reduced Motion**: Respects user's motion preferences

## Component Structure

```
salesforce/lwc/ascendixAiSearch/
├── ascendixAiSearch.html          # Component template
├── ascendixAiSearch.js            # Component logic
├── ascendixAiSearch.css           # Component styles
└── ascendixAiSearch.js-meta.xml   # Component metadata
```

## Apex Controller

The component uses `AscendixAISearchController.cls` to make callouts to the AWS API:

```
salesforce/apex/
├── AscendixAISearchController.cls           # Apex controller
└── AscendixAISearchController.cls-meta.xml  # Metadata
```

### Methods
- `callAnswerEndpoint(String requestBodyJson)`: Calls the /answer endpoint for AI-generated answers
- `callRetrieveEndpoint(String requestBodyJson)`: Calls the /retrieve endpoint for search results
- `getCurrentUserId()`: Returns the current user's Salesforce ID

## Configuration

### Named Credential
The component requires a Named Credential called `Ascendix_AI_Search_API` configured with:
- Endpoint: Your Private API Gateway URL
- Authentication: API Key
- Timeout: 120 seconds

### Page Layouts
The component can be added to:
- **Home Page**: For general search across all data
- **Record Pages**: For context-aware search (Account, Opportunity, Case)
- **App Pages**: For custom layouts

## Usage

### Basic Query
1. Enter a natural language question in the text area
2. Optionally select filters (Region, Business Unit, Quarter)
3. Click "Search" or press Ctrl+Enter
4. View the streaming answer as it's generated
5. Click "View Citations" to see source records

### Keyboard Shortcuts
- **Ctrl+Enter** (or Cmd+Enter on Mac): Submit query
- **Escape**: Close modals (citations drawer or preview)
- **Tab**: Navigate between interactive elements

### Filter Usage
Filters help narrow down results:
- **Region**: AMER, EMEA, APAC, LATAM
- **Business Unit**: Enterprise, Commercial, SMB
- **Quarter**: Current and upcoming quarters

Active filters are displayed as chips and can be removed individually or all at once.

## Error Handling

The component handles various error scenarios:

| Error Type | Message | Retry Available |
|------------|---------|-----------------|
| Access Denied | "You don't have permission to view these records" | No |
| No Results | "No results found that you have access to" | No |
| Timeout | "The request took too long. Please try again." | Yes |
| Rate Limit | "Too many requests. Please wait a moment and try again." | Yes |
| Connection Error | "Unable to connect to the service" | Yes |
| Generic Error | "An unexpected error occurred. Please try again." | Yes |

## API Integration

### Request Format
```json
{
  "sessionId": "session_1234567890_abc123",
  "query": "Show open opportunities over $1M for ACME",
  "recordContext": { "recordId": "001xx000003DGb2AAG" },
  "salesforceUserId": "005xx000001X8UzAAK",
  "topK": 8,
  "policy": {
    "require_citations": true,
    "max_tokens": 1000
  },
  "filters": {
    "region": "EMEA",
    "businessUnit": "Enterprise"
  }
}
```

### Response Format
```json
{
  "answer": "Based on the data, ACME has 3 open opportunities...",
  "citations": [
    {
      "id": "Opportunity/006xx1/chunk-0",
      "recordId": "006xx000001X8UzAAK",
      "title": "ACME Renewal",
      "sobject": "Opportunity",
      "score": 0.92,
      "snippet": "ACME renewal valued at $1.2M...",
      "previewUrl": "https://s3.amazonaws.com/..."
    }
  ],
  "trace": {
    "retrieveMs": 210,
    "generateMs": 840,
    "totalMs": 1050
  }
}
```

## Deployment

### Prerequisites
1. Named Credential configured for API Gateway
2. Apex class deployed to org
3. Remote Site Settings configured (if needed)

### Deployment Steps
```bash
# Deploy Apex controller
sfdx force:source:deploy -p salesforce/apex/AscendixAISearchController.cls

# Deploy LWC component
sfdx force:source:deploy -p salesforce/lwc/ascendixAiSearch

# Assign to page layouts
# Use Lightning App Builder to add component to desired pages
```

## Testing

### Manual Testing
1. Add component to a test page
2. Submit various queries:
   - Single object: "Show all open opportunities"
   - Multi-object: "Which accounts have cases and leases?"
   - With filters: "EMEA opportunities over $1M"
3. Test error scenarios:
   - Invalid query
   - No results
   - Network timeout
4. Test accessibility:
   - Keyboard navigation
   - Screen reader compatibility

### Automated Testing
Jest tests for the LWC component are marked as optional (task 9.7*) and can be implemented separately.

## Troubleshooting

### Common Issues

**"Unable to connect to the service"**
- Verify Named Credential is configured correctly
- Check API Gateway endpoint URL
- Ensure Private Connect is established

**"Access Denied"**
- Verify user has appropriate permissions
- Check Salesforce sharing rules
- Confirm AuthZ Sidecar is functioning

**"No results found"**
- Try broader query terms
- Remove or adjust filters
- Verify data has been indexed

**Streaming not working**
- Note: True SSE streaming is not supported in Salesforce LWC
- Component simulates streaming by chunking the response
- Full answer is retrieved from Apex, then displayed progressively

## Requirements Mapping

This component satisfies the following requirements:

- **1.1**: Natural language queries with streaming answers
- **1.5**: Streaming token display
- **6.1**: Citations drawer with record links
- **6.2**: Citation preview panel
- **6.3**: Deep links to Salesforce records
- **7.1**: Facet filters for Region, BU, Quarter
- **7.2**: Filter application and updates
- **11.1**: Keyboard navigation
- **11.2**: Visible focus states
- **11.3**: ARIA labels and roles
- **11.4**: Error handling and user feedback

## Future Enhancements

- Real-time streaming via WebSocket (when supported by Salesforce)
- Multi-turn conversation support
- Query history and saved searches
- Advanced filter options (date ranges, custom fields)
- Export results to CSV or PDF
- Integration with Agentforce for agent actions (Phase 2)
