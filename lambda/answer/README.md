# Answer Lambda

This Lambda function implements the `/answer` endpoint for the Salesforce AI Search POC. It generates streaming answers with citations using Amazon Bedrock and retrieval context.

## Features

- **Streaming Response**: Uses Server-Sent Events (SSE) to stream answer tokens as they're generated
- **Context Retrieval**: Integrates with Retrieve Lambda to get relevant chunks from Bedrock Knowledge Base
- **Grounding Policy**: Constructs system prompts that require citations for all factual claims
- **Bedrock Integration**: Streams answer generation using Claude 3 Sonnet with optional Guardrails
- **Citation Extraction**: Parses and validates citation markers in format `[Source: RecordId]`
- **Session Persistence**: Stores query, answer, and citations in DynamoDB with 30-day TTL

## Request Format

```json
{
  "sessionId": "optional-session-id",
  "query": "Show open opportunities over $1M for ACME",
  "recordContext": {
    "AccountId": "001xx"
  },
  "salesforceUserId": "005xx000000XXXXX",
  "topK": 8,
  "policy": {
    "max_tokens": 600,
    "temperature": 0.3,
    "require_citations": true
  }
}
```

## Response Format (SSE Stream)

```
event: token
data: {"token": "ACME"}

event: token
data: {"token": " has"}

event: citation
data: {"id": "Opportunity/006xx1", "sobject": "Opportunity", "recordId": "006xx1", "text": "..."}

event: done
data: {"citations": [...], "trace": {"retrieveMs": 210, "generateMs": 840, "totalMs": 1052}}
```

## Environment Variables

- `RETRIEVE_LAMBDA_FUNCTION_NAME`: ARN or name of the Retrieve Lambda function
- `BEDROCK_MODEL_ID`: Bedrock model ID (default: `anthropic.claude-3-sonnet-20240229-v1:0`)
- `BEDROCK_GUARDRAIL_ID`: Optional Bedrock Guardrail ID
- `BEDROCK_GUARDRAIL_VERSION`: Guardrail version (default: `DRAFT`)
- `SESSIONS_TABLE_NAME`: DynamoDB table name for session persistence
- `DEFAULT_TOP_K`: Default number of chunks to retrieve (default: 8)
- `MAX_TOP_K`: Maximum allowed topK value (default: 20)
- `DEFAULT_MAX_TOKENS`: Default max tokens for answer (default: 600)
- `DEFAULT_TEMPERATURE`: Default temperature for generation (default: 0.3)
- `LOG_LEVEL`: Logging level (default: INFO)

## Error Handling

- **400 Bad Request**: Validation errors (invalid request format)
- **502 Bad Gateway**: Retrieval Lambda errors
- **503 Service Unavailable**: Bedrock generation errors
- **500 Internal Server Error**: Unexpected errors

All errors are returned as SSE events with `event: error`.

## Performance Targets

- **p95 First Token Latency**: ≤800ms
- **p95 End-to-End Latency**: ≤4.0s for answers under 1000 tokens

## Dependencies

- `boto3`: AWS SDK for Lambda, Bedrock, and DynamoDB
- `botocore`: AWS core library

See `requirements.txt` for version details.
