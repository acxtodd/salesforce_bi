# API Gateway Deployment Guide

## Overview

This document describes the Private API Gateway infrastructure created for the Salesforce AI Search POC. The API Gateway provides secure, private access to the `/retrieve` and `/answer` endpoints via AWS PrivateLink.

## Architecture

### Components Created

1. **Private API Gateway**
   - Endpoint Type: PRIVATE (no public access)
   - Stage: `prod`
   - CloudWatch logging enabled
   - Request/response validation enabled

2. **Lambda Functions**
   - `salesforce-ai-search-authz`: AuthZ Sidecar for computing sharing buckets and FLS tags
   - `salesforce-ai-search-retrieve`: Retrieve endpoint for hybrid search
   - `salesforce-ai-search-answer`: Answer endpoint with streaming support

3. **API Keys & Usage Plans**
   - **User API Key**: For requests from Salesforce Named Credential
     - Rate Limit: 100 req/sec
     - Burst: 200 requests
     - Quota: 10,000 req/day
   
   - **Service API Key**: For ingestion and batch operations
     - Rate Limit: 50 req/sec
     - Burst: 100 requests
     - Quota: 50,000 req/day

4. **VPC Endpoint (PrivateLink)**
   - Service: `com.amazonaws.<region>.execute-api`
   - Private DNS enabled
   - Security group allows HTTPS (443) from VPC CIDR

5. **Security**
   - API Gateway policy restricts access to VPC endpoint only
   - All Lambda functions run in private subnets
   - KMS encryption for data at rest
   - TLS 1.2+ for data in transit

## Endpoints

### POST /retrieve

Performs hybrid search across indexed Salesforce data.

**Request:**
```json
{
  "query": "string (required)",
  "salesforceUserId": "string (required, 15 or 18 chars starting with 005)",
  "topK": "integer (optional, default 8, max 20)",
  "filters": {
    "sobject": "string",
    "region": "string",
    "businessUnit": "string"
  },
  "recordContext": {},
  "hybrid": "boolean (optional, default true)",
  "authzMode": "string (optional, default 'both')"
}
```

**Response:**
```json
{
  "matches": [
    {
      "id": "string",
      "title": "string",
      "score": "number",
      "snippet": "string",
      "metadata": {},
      "previewUrl": "string"
    }
  ],
  "queryPlan": {},
  "trace": {}
}
```

### POST /answer

Generates streaming answer with citations using Bedrock.

**Request:**
```json
{
  "query": "string (required)",
  "salesforceUserId": "string (required)",
  "sessionId": "string (optional)",
  "topK": "integer (optional, default 8)",
  "recordContext": {},
  "policy": {
    "max_tokens": "integer (optional, default 600)",
    "temperature": "number (optional, default 0.3)",
    "require_citations": "boolean (optional, default true)"
  }
}
```

**Response:** Server-Sent Events (SSE) stream
```
event: token
data: {"token": "text"}

event: citation
data: {"id": "...", "sobject": "...", "recordId": "..."}

event: done
data: {"citations": [...], "trace": {...}}
```

## Deployment

### Prerequisites

1. AWS CLI configured with appropriate credentials
2. Node.js 18+ and npm installed
3. AWS CDK CLI installed: `npm install -g aws-cdk`
4. Environment variables set (optional):
   - `SALESFORCE_API_ENDPOINT`: Salesforce instance URL
   - `BEDROCK_GUARDRAIL_ID`: Bedrock Guardrails ID (if using)

### Deploy All Stacks

```bash
# Install dependencies
npm install

# Build TypeScript
npm run build

# Bootstrap CDK (first time only)
cdk bootstrap

# Deploy all stacks
cdk deploy --all

# Or deploy API stack only
cdk deploy SalesforceAISearch-Api-dev
```

### Retrieve API Keys

After deployment, retrieve the API key values:

```bash
# Get User API Key value
aws apigateway get-api-key \
  --api-key $(aws cloudformation describe-stacks \
    --stack-name SalesforceAISearch-Api-dev \
    --query "Stacks[0].Outputs[?OutputKey=='UserApiKeyId'].OutputValue" \
    --output text) \
  --include-value \
  --query 'value' \
  --output text

# Get Service API Key value
aws apigateway get-api-key \
  --api-key $(aws cloudformation describe-stacks \
    --stack-name SalesforceAISearch-Api-dev \
    --query "Stacks[0].Outputs[?OutputKey=='ServiceApiKeyId'].OutputValue" \
    --output text) \
  --include-value \
  --query 'value' \
  --output text
```

### Configure Salesforce Named Credential

1. In Salesforce Setup, navigate to **Named Credentials**
2. Create a new Named Credential:
   - **Label**: Salesforce AI Search API
   - **Name**: Salesforce_AI_Search_API
   - **URL**: Use the VPC Endpoint DNS from CloudFormation outputs
   - **Identity Type**: Named Principal
   - **Authentication Protocol**: Custom
   - **Custom Headers**:
     - `x-api-key`: [User API Key value from above]
   - **Generate Authorization Header**: Unchecked

## Testing

### Test from VPC (EC2 or Lambda)

```bash
# Get API endpoint from CloudFormation
API_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Api-dev \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
  --output text)

# Get User API Key
USER_API_KEY=$(aws apigateway get-api-key \
  --api-key $(aws cloudformation describe-stacks \
    --stack-name SalesforceAISearch-Api-dev \
    --query "Stacks[0].Outputs[?OutputKey=='UserApiKeyId'].OutputValue" \
    --output text) \
  --include-value \
  --query 'value' \
  --output text)

# Test /retrieve endpoint
curl -X POST "${API_ENDPOINT}retrieve" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${USER_API_KEY}" \
  -d '{
    "query": "Show open opportunities over $1M",
    "salesforceUserId": "005xx000001234567"
  }'

# Test /answer endpoint (streaming)
curl -X POST "${API_ENDPOINT}answer" \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${USER_API_KEY}" \
  -d '{
    "query": "Summarize renewal risks for ACME",
    "salesforceUserId": "005xx000001234567"
  }'
```

## Monitoring

### CloudWatch Logs

- API Gateway logs: `/aws/apigateway/salesforce-ai-search`
- Lambda logs:
  - `/aws/lambda/salesforce-ai-search-authz`
  - `/aws/lambda/salesforce-ai-search-retrieve`
  - `/aws/lambda/salesforce-ai-search-answer`

### CloudWatch Metrics

- API Gateway: Request count, latency, 4xx/5xx errors
- Lambda: Invocations, duration, errors, throttles
- DynamoDB: Read/write capacity, throttles

### Alarms (to be configured)

- API Gateway 5xx rate > 5%
- Lambda error rate > 10%
- Lambda duration > p95 targets
- DynamoDB throttling > 0

## Security Considerations

1. **Private Access Only**: API Gateway has no public endpoint
2. **VPC Endpoint Policy**: Restricts access to specific VPC endpoint
3. **API Key Rotation**: Rotate API keys every 90 days
4. **IAM Roles**: Lambda functions use least-privilege IAM roles
5. **Encryption**: KMS encryption for DynamoDB, S3, and environment variables
6. **Salesforce Token**: Store in SSM Parameter Store with encryption

## Troubleshooting

### API Gateway returns 403 Forbidden

- Verify request is coming from VPC endpoint
- Check API key is included in `x-api-key` header
- Verify API key is associated with usage plan

### Lambda timeout

- Check Lambda CloudWatch logs for errors
- Verify VPC endpoints for Bedrock, DynamoDB, S3 are configured
- Check security group rules allow outbound HTTPS

### No results from /retrieve

- Verify Knowledge Base is synced with data
- Check AuthZ Lambda is computing sharing buckets correctly
- Review telemetry in DynamoDB for authZ denials

### Streaming not working for /answer

- Verify API Gateway integration is set to proxy mode
- Check Lambda response format includes SSE headers
- Test with curl to verify SSE events are being sent

## Next Steps

1. Configure Salesforce Private Connect to AWS PrivateLink
2. Deploy LWC component to Salesforce
3. Set up CloudWatch dashboards and alarms
4. Configure Bedrock Guardrails (if not already done)
5. Implement CDC pipeline for data ingestion
6. Run acceptance tests with curated query set

## References

- [AWS PrivateLink Documentation](https://docs.aws.amazon.com/vpc/latest/privatelink/)
- [API Gateway Private APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-private-apis.html)
- [Salesforce Private Connect](https://help.salesforce.com/s/articleView?id=sf.private_connect_overview.htm)
- [Amazon Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
