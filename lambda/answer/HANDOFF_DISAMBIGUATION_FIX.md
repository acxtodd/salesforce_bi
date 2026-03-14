# Handoff: Answer Lambda Disambiguation Fix

## Status: Code Ready, Deployment Pending

## Problem
The Ascendix AI Search UI shows "I don't have enough information to answer that question" when a disambiguation query is submitted (e.g., "show availabilities for class a office space in Dallas").

**Root Cause**: The answer Lambda doesn't handle disambiguation responses from the retrieve Lambda. It only checks for `matches` - when retrieve returns disambiguation instead of matches, answer Lambda treats it as "no context" and returns the error message.

## Fix Applied (Not Yet Deployed)

**File**: `lambda/answer/index.py`
**Location**: Lines 669-699 (after retrieval, before empty matches check)

Added disambiguation handling:
```python
# Check if retrieve Lambda returned a disambiguation request
# **Feature: zero-config-schema-discovery, Task 29**
disambiguation = retrieval_response.get("disambiguation", {})
if disambiguation.get("needsDisambiguation"):
    LOGGER.info(
        "Disambiguation requested: %s options, terms=%s",
        len(disambiguation.get("options", [])),
        disambiguation.get("ambiguousTerms", [])
    )
    # Return disambiguation request to frontend via SSE
    stream_body = _format_sse_event("disambiguation", disambiguation)
    stream_body += _format_sse_event("done", {
        "reason": "disambiguation_needed",
        "trace": {...},
    })
    # ... return response
```

## Deployment Steps

The answer Lambda uses Docker (FastAPI + Lambda Web Adapter). To deploy:

### 1. Authenticate to ECR
```bash
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 382211616288.dkr.ecr.us-west-2.amazonaws.com
```

### 2. Build Docker Image
```bash
cd lambda/answer
docker build --platform linux/arm64 -t salesforce-ai-search-answer .
```

### 3. Tag and Push to ECR
```bash
# Get the current image tag from Lambda
IMAGE_URI=$(aws lambda get-function --function-name salesforce-ai-search-answer-docker --region us-west-2 --query "Code.ImageUri" --output text)

# Tag with same repository
docker tag salesforce-ai-search-answer:latest ${IMAGE_URI%:*}:latest

# Push
docker push ${IMAGE_URI%:*}:latest
```

### 4. Update Lambda Function
```bash
aws lambda update-function-code \
  --function-name salesforce-ai-search-answer-docker \
  --image-uri ${IMAGE_URI%:*}:latest \
  --region us-west-2
```

### Alternative: CDK Deploy
If there's a CDK stack for the answer Lambda, deploying via CDK may be simpler:
```bash
npx cdk deploy SalesforceAISearchAnswerStack  # (or whatever the stack name is)
```

## Frontend Considerations

The frontend needs to handle the new `disambiguation` SSE event type. Current events the frontend likely handles:
- `token` - Streaming answer tokens
- `done` - Completion signal
- `debug` - Debug information

New event to handle:
- `disambiguation` - Contains disambiguation options for user selection

The disambiguation payload looks like:
```json
{
  "needsDisambiguation": true,
  "originalQuery": "show availabilities for class a office space in Dallas",
  "message": "Your query contains ambiguous terms...",
  "options": [
    {
      "entity": "ascendix__Availability__c",
      "label": "Availability",
      "description": "Specific units, suites, or floors available for lease",
      "exampleQuery": "Show me available spaces over 10,000 sqft",
      "confidence": 0.7
    },
    ...
  ],
  "ambiguousTerms": ["space"]
}
```

## Testing After Deployment

```bash
# Test via direct Lambda invoke
cat > /tmp/test_disamb_answer.json << 'EOF'
{
  "query": "show availabilities for class a office space in Dallas",
  "salesforceUserId": "005dl00000Q6a3RAAR",
  "filters": {}
}
EOF

curl -X POST 'https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer' \
  -H 'x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ' \
  -H 'Content-Type: application/json' \
  -d @/tmp/test_disamb_answer.json
```

Expected: SSE events including `event: disambiguation` with options.

## Related Changes (Already Deployed)

The retrieve Lambda (`salesforce-ai-search-retrieve`) has been updated with:
1. Schema decomposition timeout (700ms) with heuristic fallback
2. Cross-object query timeout (2000ms)
3. Planner timeout fix (non-blocking executor shutdown)
4. Disambiguation flow fix (timeout doesn't skip disambiguation)

All latency tests now pass under 3.5s (target was 5s).

## Date
2025-12-12
