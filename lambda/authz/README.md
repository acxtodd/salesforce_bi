# AuthZ Sidecar Lambda

Authorization service that computes sharing buckets and FLS profile tags for Salesforce users.

## Overview

The AuthZ Sidecar Lambda provides centralized authorization context computation with caching to reduce Salesforce API calls and improve performance.

## Features

- **Sharing Bucket Computation**: Computes authorization tags based on user's role, territory, and ownership
- **FLS Profile Tags**: Placeholder for Phase 3 field-level security (currently returns empty list)
- **DynamoDB Caching**: 24-hour TTL cache to minimize Salesforce API calls
- **Cache Invalidation**: Manual cache busting for immediate updates

## Operations

### 1. Get Authorization Context

Retrieves authorization context for a user (from cache or computes fresh).

**Request:**
```json
{
  "operation": "getAuthZContext",
  "salesforceUserId": "005xx000001234567"
}
```

**Response:**
```json
{
  "statusCode": 200,
  "body": {
    "salesforceUserId": "005xx000001234567",
    "sharingBuckets": [
      "owner:005xx000001234567",
      "role:00Exx000000ABCD",
      "role_name:SalesManager",
      "territory:0Mxxx000000EFGH"
    ],
    "flsProfileTags": [],
    "computedAt": "2025-11-13T10:30:00Z",
    "cached": true
  }
}
```

### 2. Invalidate Cache

Deletes cached authorization context for a user, forcing fresh computation on next request.

**Request:**
```json
{
  "operation": "invalidateCache",
  "salesforceUserId": "005xx000001234567"
}
```

**Response:**
```json
{
  "statusCode": 200,
  "body": {
    "success": true,
    "message": "Cache invalidated for user 005xx000001234567"
  }
}
```

## Sharing Bucket Tags

Sharing buckets represent authorization contexts that determine which records a user can access:

| Tag Format | Description | Example |
|------------|-------------|---------|
| `owner:{userId}` | User owns the record | `owner:005xx000001234567` |
| `role:{roleId}` | User's role in hierarchy | `role:00Exx000000ABCD` |
| `role_name:{roleName}` | User's role name (for debugging) | `role_name:SalesManager` |
| `territory:{territoryId}` | User's territory assignment | `territory:0Mxxx000000EFGH` |

## Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `AUTHZ_CACHE_TABLE` | DynamoDB table name for cache | Yes | `authz_cache_table` |
| `SALESFORCE_API_ENDPOINT` | Salesforce instance URL | Yes | - |
| `SALESFORCE_API_VERSION` | Salesforce API version | No | `v59.0` |
| `SALESFORCE_TOKEN_PARAM` | SSM parameter name for access token | No | `/salesforce/access_token` |
| `SALESFORCE_ACCESS_TOKEN` | Direct access token (for testing) | No | - |

## DynamoDB Schema

**Table Name:** `authz_cache_table`

**Primary Key:**
- Partition Key: `salesforceUserId` (String)

**Attributes:**
- `sharingBuckets` (List of Strings)
- `flsProfileTags` (List of Strings)
- `computedAt` (String, ISO 8601 timestamp)
- `ttl` (Number, Unix timestamp for DynamoDB TTL)

**TTL Configuration:**
- TTL Attribute: `ttl`
- TTL Duration: 24 hours from computation

## Performance Characteristics

| Metric | Target | Notes |
|--------|--------|-------|
| Cache Hit Latency | < 10ms | DynamoDB single-item read |
| Cache Miss Latency | < 200ms | Includes Salesforce API calls |
| Cache Hit Rate | > 95% | With 24-hour TTL |
| Throughput | 1000 req/sec | DynamoDB on-demand capacity |

## Usage in Other Lambdas

### Retrieve Lambda Example

```python
import boto3
import json

lambda_client = boto3.client('lambda')

def get_authz_context(user_id: str) -> dict:
    """Call AuthZ Sidecar to get authorization context."""
    response = lambda_client.invoke(
        FunctionName='authz-sidecar-lambda',
        InvocationType='RequestResponse',
        Payload=json.dumps({
            'operation': 'getAuthZContext',
            'salesforceUserId': user_id
        })
    )
    
    result = json.loads(response['Payload'].read())
    return json.loads(result['body'])

# Use in retrieval
authz_context = get_authz_context('005xx000001234567')
sharing_buckets = authz_context['sharingBuckets']

# Build OpenSearch query with authZ filters
query = {
    "bool": {
        "must": [
            {"match": {"text": user_query}}
        ],
        "filter": [
            {"terms": {"metadata.sharingBuckets": sharing_buckets}}
        ]
    }
}
```

### Answer Lambda Example

```python
# Get authZ context before retrieval
authz_context = get_authz_context(salesforce_user_id)

# Pass to Retrieve Lambda
retrieve_response = lambda_client.invoke(
    FunctionName='retrieve-lambda',
    Payload=json.dumps({
        'query': user_query,
        'authZContext': authz_context,
        'topK': 8
    })
)
```

## Cache Invalidation Scenarios

Invalidate cache when:

1. **User Role Changes**: User promoted/demoted
2. **Territory Assignment Changes**: User moved to different territory
3. **Profile Changes**: User's profile updated
4. **Permission Set Changes**: Permission sets added/removed
5. **Manual Request**: Admin manually invalidates cache

### Automated Invalidation (Future)

In production, set up Salesforce Platform Events or CDC to trigger cache invalidation:

```apex
// Salesforce Apex Trigger
trigger UserRoleChangeTrigger on User (after update) {
    for (User u : Trigger.new) {
        if (u.UserRoleId != Trigger.oldMap.get(u.Id).UserRoleId) {
            // Call AWS Lambda to invalidate cache
            HttpRequest req = new HttpRequest();
            req.setEndpoint('callout:AuthZ_Sidecar');
            req.setMethod('POST');
            req.setBody(JSON.serialize(new Map<String, String>{
                'operation' => 'invalidateCache',
                'salesforceUserId' => u.Id
            }));
            Http http = new Http();
            http.send(req);
        }
    }
}
```

## Testing

### Unit Tests

Run unit tests with pytest:

```bash
cd lambda/authz
pytest test_authz.py -v
```

### Integration Tests

Test against real Salesforce org:

```bash
# Set environment variables
export SALESFORCE_API_ENDPOINT="https://your-instance.salesforce.com"
export SALESFORCE_ACCESS_TOKEN="your-access-token"
export AUTHZ_CACHE_TABLE="authz_cache_table_dev"

# Run integration tests
pytest test_authz_integration.py -v
```

### Manual Testing

Use AWS CLI to invoke Lambda:

```bash
# Get authorization context
aws lambda invoke \
  --function-name authz-sidecar-lambda \
  --payload '{"operation":"getAuthZContext","salesforceUserId":"005xx000001234567"}' \
  response.json

cat response.json

# Invalidate cache
aws lambda invoke \
  --function-name authz-sidecar-lambda \
  --payload '{"operation":"invalidateCache","salesforceUserId":"005xx000001234567"}' \
  response.json

cat response.json
```

## Error Handling

| Error | Status Code | Response |
|-------|-------------|----------|
| Missing `salesforceUserId` | 400 | `{"error": "salesforceUserId is required"}` |
| Invalid User ID format | 400 | `{"error": "Invalid Salesforce User ID format"}` |
| Unknown operation | 400 | `{"error": "Unknown operation: xyz"}` |
| Salesforce API error | 500 | `{"error": "Error querying Salesforce: ..."}` |
| DynamoDB error | 500 | `{"error": "Error retrieving from cache: ..."}` |

## Monitoring

### CloudWatch Metrics

- **Invocations**: Total Lambda invocations
- **Duration**: Execution time (p50, p95, p99)
- **Errors**: Failed invocations
- **Throttles**: Rate limit exceeded

### Custom Metrics

Log the following for analysis:

- Cache hit rate (hits / total requests)
- Salesforce API call count
- Average latency by operation
- User ID patterns (for debugging)

### CloudWatch Logs Insights Queries

**Cache Hit Rate:**
```
fields @timestamp
| filter @message like /Cache hit/ or @message like /Cache miss/
| stats count(*) as total, 
        sum(@message like /Cache hit/) as hits
| extend hitRate = hits / total * 100
```

**Average Latency by Operation:**
```
fields @timestamp, operation, @duration
| stats avg(@duration) as avgLatency by operation
```

## Security Considerations

1. **Access Token Storage**: Store Salesforce access tokens in AWS SSM Parameter Store with encryption
2. **IAM Permissions**: Lambda execution role should have minimal permissions (DynamoDB, SSM, CloudWatch Logs)
3. **VPC Configuration**: Deploy in private subnet with VPC endpoints for AWS services
4. **Input Validation**: Validate User ID format to prevent injection attacks
5. **Rate Limiting**: Implement rate limiting to prevent abuse

## Phase 3 Enhancements

See `FLS_POC_LIMITATION.md` for details on Phase 3 FLS implementation.

### Planned Features

1. **Full FLS Enforcement**: Compute field-level permissions
2. **Dynamic Object Support**: Query sharing rules for any object
3. **Advanced Caching**: Multi-level cache with ElastiCache
4. **Batch Operations**: Process multiple users in single request
5. **Audit Logging**: Log all authorization decisions

## References

- Requirements: 2.1, 2.2, 2.3
- Design Document: Section "5. AuthZ Sidecar Lambda"
- Tasks: 4.1, 4.2, 4.3
