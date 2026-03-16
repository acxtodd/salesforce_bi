# EventBridge CDC Trigger Configuration

## Overview

This document explains how EventBridge is configured to trigger the ingestion pipeline when CDC data arrives in S3 from AppFlow.

## Architecture

```
S3 CDC Bucket → EventBridge → Step Functions → Ingestion Pipeline
```

**Event Flow**:
1. AppFlow writes CDC event to S3 (e.g., `cdc/Account/2025/11/13/14/event-001.json`)
2. S3 emits `Object Created` event to EventBridge
3. EventBridge rule matches the event pattern
4. EventBridge invokes Step Functions state machine
5. Step Functions orchestrates the ingestion pipeline

## EventBridge Rule Configuration

### Rule Pattern

The EventBridge rule matches S3 object creation events for CDC data:

```json
{
  "source": ["aws.s3"],
  "detail-type": ["Object Created"],
  "detail": {
    "bucket": {
      "name": ["salesforce-ai-search-cdc-{account}-{region}"]
    },
    "object": {
      "key": [{
        "prefix": "cdc/"
      }]
    }
  }
}
```

**Pattern Explanation**:
- **source**: Only S3 events
- **detail-type**: Only object creation events (not updates or deletes)
- **bucket.name**: Only the CDC bucket
- **object.key.prefix**: Only objects under the `cdc/` prefix

### Rule Target

The rule targets the Step Functions state machine with a transformed input:

```json
{
  "bucket": "$.detail.bucket.name",
  "key": "$.detail.object.key",
  "eventTime": "$.time",
  "eventSource": "cdc"
}
```

**Input Transformation**:
- **bucket**: S3 bucket name from the event
- **key**: S3 object key (e.g., `cdc/Account/2025/11/13/14/event-001.json`)
- **eventTime**: Timestamp when the event occurred
- **eventSource**: Set to "cdc" to distinguish from batch ingestion

## Step Functions Workflow

The ingestion workflow starts with the CDC Processor Lambda:

```
CDCProcessor → Validate → Transform → Chunk → Enrich → Embed → Sync
```

### CDC Processor Lambda

**Purpose**: Read CDC event from S3 and transform it into the format expected by the ingestion pipeline.

**Input** (from EventBridge):
```json
{
  "bucket": "salesforce-ai-search-cdc-123456789012-us-east-1",
  "key": "cdc/Account/2025/11/13/14/event-001.json",
  "eventTime": "2025-11-13T14:30:00Z",
  "eventSource": "cdc"
}
```

**Processing**:
1. Extract sobject name from S3 key (`cdc/Account/...` → `Account`)
2. Download CDC event JSON from S3
3. Parse `ChangeEventHeader` to determine change type
4. Skip DELETE events (we don't index deleted records)
5. Extract record data (all fields except `ChangeEventHeader`)
6. Add CDC metadata (`_cdc_change_type`, `_cdc_commit_timestamp`)

**Output**:
```json
{
  "records": [
    {
      "sobject": "Account",
      "data": {
        "Id": "001xx000001234AAA",
        "Name": "ACME Corporation",
        "BillingStreet": "123 Main St",
        "Description": "Leading provider of...",
        "_cdc_change_type": "UPDATE",
        "_cdc_commit_timestamp": 1699887600000
      }
    }
  ]
}
```

### Subsequent Steps

After CDC Processor, the workflow continues with the standard ingestion pipeline:

1. **Validate**: Check record structure and required fields
2. **Transform**: Flatten relationships and extract text fields
3. **Chunk**: Split text into 300-500 token segments
4. **Enrich**: Add metadata (sobject, recordId, sharing buckets, etc.)
5. **Embed**: Generate embeddings using Titan Text Embeddings v2
6. **Sync**: Write to S3 in Bedrock KB format

## Enabling EventBridge Notifications

The CDC bucket must have EventBridge notifications enabled:

```typescript
cdcBucket.enableEventBridgeNotification();
```

This allows S3 to send events to EventBridge instead of using legacy S3 event notifications.

## Monitoring

### CloudWatch Metrics

EventBridge publishes metrics for the rule:

- **Invocations** - Number of times the rule was triggered
- **TriggeredRules** - Number of times the rule matched an event
- **FailedInvocations** - Number of failed invocations

### CloudWatch Logs

Step Functions execution logs are available in CloudWatch Logs:

- Log group: `/aws/vendedlogs/states/salesforce-ai-search-ingestion`
- Contains detailed execution logs for each CDC event processed

### Viewing Execution History

1. Navigate to **AWS Console** → **Step Functions**
2. Click on **salesforce-ai-search-ingestion** state machine
3. Click **Executions** tab
4. View:
   - Execution status (Running, Succeeded, Failed)
   - Start time and duration
   - Input/output for each step
   - Error messages (if any)

## Error Handling

### CDC Processor Failures

If the CDC Processor Lambda fails:
- Error is caught by Step Functions
- Event is sent to Dead Letter Queue (DLQ)
- CloudWatch alarm is triggered (if configured)
- Execution stops (does not proceed to Validate step)

**Common Failures**:
- S3 object not found (race condition)
- Invalid JSON format
- Missing required fields in CDC event
- Unsupported sobject type

### Downstream Failures

If any downstream step fails (Validate, Transform, etc.):
- Error is caught by Step Functions
- Event is sent to DLQ with error details
- Execution stops at the failed step

### Dead Letter Queue

Failed events are sent to the DLQ for manual inspection:

- Queue name: `salesforce-ai-search-ingestion-dlq`
- Retention: 14 days
- Encrypted with KMS

**Inspecting Failed Events**:
1. Navigate to **AWS Console** → **SQS**
2. Click on **salesforce-ai-search-ingestion-dlq**
3. Click **Send and receive messages** → **Poll for messages**
4. View message body to see the failed event and error details

## Performance Considerations

### Event Volume

- Each CDC event triggers one Step Functions execution
- High-volume objects (e.g., Case) may generate many events
- Step Functions has a limit of 1,000 concurrent executions per account (default)
- Monitor execution count and request limit increases if needed

### Latency

**Target**: P50 latency ≤ 5 minutes from Salesforce change to indexed chunk

**Breakdown**:
- Salesforce CDC publish: < 1 second
- AppFlow polling: 1-5 minutes (average 3 minutes)
- S3 write + EventBridge trigger: < 1 second
- Step Functions execution: 30-60 seconds
- **Total P50**: ~4 minutes (within target)

### Cost Optimization

- **EventBridge**: $1.00 per million events
- **Step Functions**: $0.025 per 1,000 state transitions (7 steps = $0.175 per 1,000 events)
- **Lambda**: $0.20 per 1 million requests + compute time
- **Estimated POC cost**: ~$10-20/month for 10k events/day

## Troubleshooting

### Rule Not Triggering

**Issue**: EventBridge rule is not invoking Step Functions when CDC data arrives in S3.

**Solutions**:
1. Verify EventBridge notifications are enabled on the CDC bucket:
   ```bash
   aws s3api get-bucket-notification-configuration --bucket salesforce-ai-search-cdc-{account}-{region}
   ```
2. Check that the rule is **Enabled** in EventBridge console
3. Verify the event pattern matches the S3 event structure
4. Check IAM permissions for EventBridge to invoke Step Functions
5. Look for events in EventBridge event bus (may be delayed)

### Step Functions Not Starting

**Issue**: EventBridge rule is triggered but Step Functions execution does not start.

**Solutions**:
1. Check IAM role for EventBridge rule has `states:StartExecution` permission
2. Verify Step Functions state machine ARN is correct in the rule target
3. Check Step Functions execution history for errors
4. Look for throttling errors in CloudWatch Logs

### CDC Processor Failures

**Issue**: CDC Processor Lambda fails with errors.

**Solutions**:
1. Check CloudWatch Logs for the Lambda function:
   - Log group: `/aws/lambda/salesforce-ai-search-cdc-processor`
2. Common errors:
   - **S3 object not found**: Race condition, retry the event
   - **Invalid JSON**: Check AppFlow output format
   - **Missing fields**: Verify CDC event structure
3. Inspect the failed event in the DLQ
4. Manually test the Lambda with a sample event

### High Latency

**Issue**: CDC events take longer than 5 minutes to be indexed.

**Solutions**:
1. Check AppFlow execution history for delays
2. Monitor Step Functions execution duration
3. Check for Lambda cold starts (use provisioned concurrency)
4. Look for throttling in Bedrock API calls
5. Monitor DynamoDB and S3 latency

## Testing

### Manual Test

Trigger the pipeline manually by uploading a test CDC event to S3:

```bash
# Create test CDC event
cat > test-cdc-event.json << EOF
{
  "ChangeEventHeader": {
    "entityName": "Account",
    "recordIds": ["001xx000001234AAA"],
    "changeType": "UPDATE",
    "changeOrigin": "com.salesforce.api.rest",
    "transactionKey": "00000000-0000-0000-0000-000000000000",
    "sequenceNumber": 1,
    "commitTimestamp": 1699887600000,
    "commitNumber": 123456789,
    "commitUser": "005xx000001234AAA"
  },
  "Id": "001xx000001234AAA",
  "Name": "ACME Corporation Test",
  "BillingStreet": "123 Main St",
  "BillingCity": "San Francisco",
  "BillingState": "CA",
  "Description": "Test account for CDC pipeline",
  "OwnerId": "005xx000001234AAA",
  "LastModifiedDate": "2025-11-13T14:30:00.000Z"
}
EOF

# Upload to S3
aws s3 cp test-cdc-event.json s3://salesforce-ai-search-cdc-{account}-{region}/cdc/Account/2025/11/13/14/test-event.json
```

**Expected Result**:
1. EventBridge rule triggers within 1 second
2. Step Functions execution starts
3. CDC Processor reads the event from S3
4. Pipeline processes the record through all steps
5. Chunk appears in Bedrock KB within 1 minute

### End-to-End Test

Test the full CDC flow from Salesforce to indexed chunk:

1. Update a record in Salesforce (e.g., Account)
2. Wait for CDC event to be published (< 1 second)
3. Wait for AppFlow to poll and write to S3 (1-5 minutes)
4. Verify S3 object created in CDC bucket
5. Verify EventBridge rule triggered (check CloudWatch metrics)
6. Verify Step Functions execution started and succeeded
7. Verify chunk written to data bucket
8. Query Bedrock KB to confirm chunk is indexed

**Total Expected Time**: 4-6 minutes (P50 target: 5 minutes)

## Security Considerations

### IAM Permissions

**EventBridge Rule Role**:
- `states:StartExecution` on the Step Functions state machine

**CDC Processor Lambda Role**:
- `s3:GetObject` on the CDC bucket
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

**Step Functions Execution Role**:
- `lambda:InvokeFunction` on all pipeline Lambda functions
- `sqs:SendMessage` on the DLQ

### Data Encryption

- **S3 CDC Bucket**: Encrypted with KMS customer-managed key
- **EventBridge Events**: Encrypted in transit (TLS 1.2+)
- **Step Functions State**: Encrypted at rest
- **DLQ Messages**: Encrypted with KMS

### Access Control

- CDC bucket has public access blocked
- Only AppFlow and Lambda can write/read CDC data
- EventBridge rule can only invoke the specific Step Functions state machine
- DLQ is only accessible to authorized IAM roles

## Next Steps

After EventBridge is configured:
1. Proceed to **Task 8.4**: Implement batch Apex export as fallback
2. Test end-to-end CDC flow from Salesforce to indexed chunk
3. Monitor EventBridge metrics and Step Functions executions
4. Set up CloudWatch alarms for failures and high latency

## References

- [Amazon EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/)
- [S3 Event Notifications with EventBridge](https://docs.aws.amazon.com/AmazonS3/latest/userguide/EventBridge.html)
- [Step Functions Integration with EventBridge](https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-cloudwatch-events-target.html)
