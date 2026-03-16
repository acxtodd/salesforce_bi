# API Gateway 502 Error - Streaming Incompatibility

**Date:** 2025-12-06
**Status:** Known Limitation
**Severity:** Medium (workaround available)

## Issue

API Gateway `/answer` endpoint returns 502 Bad Gateway errors:

```bash
curl -X POST "https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/answer" ...
# Returns: {"message": "Internal server error"}
```

API Gateway access logs show:
```json
{"status":"502","resourcePath":"/answer","responseLength":"36"}
```

## Root Cause

The answer Lambda uses **response streaming** which is incompatible with API Gateway Lambda proxy integration:

1. **Answer Lambda Architecture:**
   - Uses FastAPI with `StreamingResponse` for SSE (Server-Sent Events)
   - Uses Lambda Web Adapter to handle HTTP
   - Returns streaming response via `text/event-stream` content type

2. **API Gateway Limitation:**
   - Lambda proxy integration expects standard response format:
     ```json
     {"statusCode": 200, "headers": {...}, "body": "string"}
     ```
   - Cannot handle streaming responses from Lambda
   - Results in 502 when Lambda returns chunked/streaming data

3. **Function URL Works:**
   - Lambda Function URL supports response streaming natively
   - Lambda Web Adapter properly handles streaming via Function URL

## Evidence

From `lambda/answer/Dockerfile`:
```dockerfile
# Copy Lambda Web Adapter
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.8.1 /lambda-adapter /opt/extensions/lambda-adapter
```

From `lambda/answer/main.py`:
```python
from fastapi.responses import StreamingResponse
...
return StreamingResponse(generate_stream(), media_type="text/event-stream")
```

## Impact

| Endpoint | Status | Use Case |
|----------|--------|----------|
| API Gateway (`/answer`) | **Broken** (502) | Salesforce Named Credential |
| Function URL (`/answer`) | **Working** | Direct API calls |

## Workaround

Use the Lambda Function URL instead of API Gateway:

```bash
# Working endpoint
https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer

# Broken endpoint
https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/answer
```

**Security Note:** The Function URL has fail-closed API key validation (implemented in Task 23). It checks against Secrets Manager and rejects requests without valid keys.

## Resolution Options

| Option | Effort | Pros | Cons |
|--------|--------|------|------|
| 1. Continue using Function URL | None | Already working, secure | Not using API Gateway features (throttling, etc.) |
| 2. Create non-streaming API Gateway endpoint | Medium | Works with API Gateway | No streaming, higher latency for users |
| 3. Use API Gateway WebSocket API | High | Supports streaming | Major refactor, different API pattern |
| 4. Use CloudFront + Function URL | Medium | Can add API Gateway-like features | Additional infrastructure |

## Recommendation

**Short-term:** Continue using Function URL with API key validation. Document this for Salesforce Named Credential configuration.

**Long-term:** If API Gateway features (usage plans, throttling, WAF) are required, consider Option 4 (CloudFront + Function URL) as it preserves streaming while adding protection.

## References

- AWS Lambda Response Streaming: https://docs.aws.amazon.com/lambda/latest/dg/configuration-response-streaming.html
- Lambda Web Adapter: https://github.com/awslabs/aws-lambda-web-adapter
- API Gateway Lambda Integration: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html
