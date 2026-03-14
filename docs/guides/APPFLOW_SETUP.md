# Amazon AppFlow Setup Guide

## Overview

This guide explains how to configure Amazon AppFlow to stream Salesforce Change Data Capture (CDC) events to S3 for the AI Search ingestion pipeline.

## Prerequisites

- Salesforce CDC configured (see `CDC_CONFIGURATION.md`)
- Salesforce Connected App with OAuth credentials
- AWS account with AppFlow service enabled
- CDK infrastructure deployed (creates CDC S3 bucket)

## Architecture

```
Salesforce CDC → AppFlow → S3 (CDC Bucket) → EventBridge → Step Functions
```

**Data Flow**:
1. Salesforce publishes change events to CDC channel
2. AppFlow subscribes to change events and polls every 1-5 minutes
3. AppFlow writes events to S3 in JSON format with partitioning
4. S3 triggers EventBridge rule on object creation
5. EventBridge invokes Step Functions ingestion workflow

## AppFlow Configuration Methods

### Method 1: CDK Deployment (Recommended)

The CDK stack automatically creates AppFlow flows when Salesforce credentials are provided.

#### Step 1: Store Salesforce Credentials in Secrets Manager

Create a secret containing the Connected App credentials:

```bash
aws secretsmanager create-secret \
  --name salesforce-ai-search-credentials \
  --description "Salesforce Connected App credentials for AI Search AppFlow" \
  --secret-string '{
    "clientId": "YOUR_CONSUMER_KEY",
    "clientSecret": "YOUR_CONSUMER_SECRET",
    "instanceUrl": "https://your-instance.salesforce.com"
  }' \
  --region us-east-1
```

Note the secret ARN from the output.

#### Step 2: Deploy CDK Stack with Salesforce Parameters

Update your CDK context or pass parameters:

```typescript
// In bin/app.ts or cdk.json context
const ingestionStack = new IngestionStack(app, 'IngestionStack', {
  vpc: networkStack.vpc,
  lambdaSecurityGroup: networkStack.lambdaSecurityGroup,
  kmsKey: dataStack.kmsKey,
  dataBucket: dataStack.dataBucket,
  salesforceInstanceUrl: 'https://your-instance.salesforce.com',
  salesforceConnectedAppClientId: 'YOUR_CONSUMER_KEY',
  salesforceConnectedAppClientSecretArn: 'arn:aws:secretsmanager:...',
});
```

Deploy:

```bash
cdk deploy IngestionStack
```

This creates:
- Salesforce connector profile
- 7 AppFlow flows (one per CDC object)
- S3 bucket for CDC data with partitioning
- IAM permissions for AppFlow to write to S3

### Method 2: Manual Console Configuration

If not using CDK automation, configure AppFlow manually:

#### Step 1: Create Connector Profile

1. Navigate to **AWS Console** → **AppFlow**
2. Click **Connectors** → **Create connector profile**
3. Configure:
   - **Connector**: Salesforce
   - **Connection name**: salesforce-ai-search-cdc-profile
   - **Connection mode**: Public
   - **Salesforce environment**: Production (or Sandbox)
   - **Instance URL**: `https://your-instance.salesforce.com`
   - **Authentication**: OAuth 2.0
   - **Client ID**: [Connected App Consumer Key]
   - **Client Secret**: [Connected App Consumer Secret]
4. Click **Connect**
5. Authorize the connection in Salesforce

#### Step 2: Create Flow for Each CDC Object

Repeat for each object: Account, Opportunity, Case, Note, Property__c, Lease__c, Contract__c

1. Click **Create flow**
2. Configure **Flow details**:
   - **Flow name**: `salesforce-ai-search-cdc-account` (adjust for each object)
   - **Description**: CDC flow for Account change events
3. Configure **Source**:
   - **Source name**: Salesforce
   - **Choose Salesforce connection**: salesforce-ai-search-cdc-profile
   - **Choose Salesforce object**: AccountChangeEvent (adjust for each object)
   - **Trigger**: Event-driven
4. Configure **Destination**:
   - **Destination name**: Amazon S3
   - **Bucket**: [CDC Bucket from CDK output]
   - **Bucket prefix**: `cdc/Account/` (adjust for each object)
   - **File format**: JSON
   - **Aggregation**: None (write each event immediately)
   - **Prefix format**: Year/Month/Day/Hour
5. Configure **Mapping**:
   - **Mapping method**: Map all fields directly
   - No transformations needed
6. Configure **Filters**: None
7. Click **Create flow**
8. Click **Activate flow**

## AppFlow Flow Configuration Details

### Source Configuration

- **Connector**: Salesforce
- **Object**: Change Event (e.g., AccountChangeEvent)
- **Trigger**: Event-driven (polls every 1-5 minutes)
- **API Version**: Latest (59.0+)

### Destination Configuration

- **Connector**: Amazon S3
- **Bucket**: `salesforce-ai-search-cdc-{account}-{region}`
- **Prefix**: `cdc/{SObjectName}/`
- **File Format**: JSON (one event per file for immediate processing)
- **Partitioning**: `YEAR/MONTH/DAY/HOUR` for organization
- **Compression**: None (for faster processing)

### Field Mapping

Map all fields from the change event to S3:
- `ChangeEventHeader` - Contains metadata about the change
- All object fields - Actual field values from the record

**Key Fields**:
- `ChangeEventHeader.changeType` - INSERT, UPDATE, DELETE, UNDELETE
- `ChangeEventHeader.recordIds` - List of affected record IDs
- `ChangeEventHeader.entityName` - Object type (e.g., Account)
- `ChangeEventHeader.changeOrigin` - Source of the change
- `ChangeEventHeader.transactionKey` - Transaction identifier
- `ChangeEventHeader.commitTimestamp` - When the change occurred

## S3 Bucket Structure

AppFlow writes CDC events to S3 with the following structure:

```
s3://salesforce-ai-search-cdc-{account}-{region}/
├── cdc/
│   ├── Account/
│   │   └── 2025/11/13/14/
│   │       ├── event-001.json
│   │       ├── event-002.json
│   │       └── event-003.json
│   ├── Opportunity/
│   │   └── 2025/11/13/14/
│   │       └── event-001.json
│   ├── Case/
│   ├── Note/
│   ├── Property__c/
│   ├── Lease__c/
│   └── Contract__c/
```

### Event File Format

Each JSON file contains a single CDC event:

```json
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
  "Name": "ACME Corporation",
  "BillingStreet": "123 Main St",
  "BillingCity": "San Francisco",
  "BillingState": "CA",
  "Description": "Leading provider of...",
  "OwnerId": "005xx000001234AAA",
  "LastModifiedDate": "2025-11-13T14:30:00.000Z"
}
```

## Monitoring AppFlow

### CloudWatch Metrics

AppFlow publishes metrics to CloudWatch:

- **FlowExecutionRecordsProcessed** - Number of records processed
- **FlowExecutionsFailed** - Number of failed executions
- **FlowExecutionsStarted** - Number of flow executions started
- **FlowExecutionsSucceeded** - Number of successful executions

### View Flow Execution History

1. Navigate to **AppFlow** → **Flows**
2. Click on a flow name
3. Click **Execution history** tab
4. View:
   - Execution time
   - Records processed
   - Status (Succeeded, Failed, Partial Success)
   - Error messages (if any)

### CloudWatch Logs

AppFlow logs are available in CloudWatch Logs:

- Log group: `/aws/appflow/{flow-name}`
- Contains detailed execution logs and error messages

## Troubleshooting

### Flow Not Triggering

**Issue**: AppFlow flow is not executing when records change in Salesforce.

**Solutions**:
1. Verify CDC is enabled for the object in Salesforce
2. Check that the flow is **Activated** in AppFlow
3. Verify the connector profile is connected (green status)
4. Check Salesforce Connected App has correct OAuth scopes
5. Ensure change events are being published (check Salesforce Event Monitor)
6. Wait up to 5 minutes for polling interval

### Authentication Errors

**Issue**: AppFlow shows "Authentication failed" or "Connection expired".

**Solutions**:
1. Re-authenticate the connector profile:
   - Go to **Connectors** → Select profile → **Edit**
   - Click **Connect** and re-authorize
2. Verify Connected App credentials are correct
3. Check that the integration user has not been deactivated
4. Ensure OAuth refresh token is valid (may expire after 90 days of inactivity)

### No Data in S3

**Issue**: AppFlow executions succeed but no files appear in S3.

**Solutions**:
1. Check that records are actually changing in Salesforce
2. Verify the S3 bucket name and prefix are correct
3. Check IAM permissions for AppFlow to write to S3
4. Look for files in the time-partitioned folders (YEAR/MONTH/DAY/HOUR)
5. Verify KMS key permissions if bucket is encrypted

### High Latency

**Issue**: CDC events take longer than 5 minutes to appear in S3.

**Solutions**:
1. Check AppFlow execution history for processing time
2. Verify Salesforce CDC is publishing events promptly
3. Consider increasing AppFlow polling frequency (if configurable)
4. Check for Salesforce API rate limits
5. Monitor CloudWatch metrics for flow execution duration

## Performance Optimization

### Polling Frequency

- Default: 1-5 minutes (AppFlow managed)
- Cannot be configured directly in AppFlow
- Total P50 latency target: 5 minutes (includes polling + processing)

### Batch Size

- AppFlow processes events individually for CDC (no batching)
- Each change event creates one S3 file
- This ensures minimal latency but higher S3 PUT costs

### Cost Optimization

- **AppFlow costs**: $0.001 per flow execution + $0.001 per GB processed
- **S3 costs**: Standard storage + PUT requests
- **Estimated POC cost**: ~$50-100/month for 10k events/day
- Use S3 lifecycle policies to delete old CDC data after 7 days

## Security Considerations

### Data Encryption

- **In transit**: TLS 1.2+ for Salesforce → AppFlow → S3
- **At rest**: S3 bucket encrypted with KMS customer-managed key
- **Credentials**: Stored in AWS Secrets Manager with encryption

### Access Control

- AppFlow uses IAM service role with least-privilege permissions
- S3 bucket has public access blocked
- Only AppFlow and Step Functions can write/read CDC data
- Salesforce Connected App uses OAuth 2.0 with client credentials flow

### Compliance

- CDC events may contain PII - ensure proper handling
- S3 bucket has versioning enabled for audit trail
- CloudWatch logs retained for 90 days
- CDC data deleted after 7 days (lifecycle policy)

## Next Steps

After AppFlow is configured:
1. Proceed to **Task 8.3**: Create EventBridge rule to trigger ingestion
2. Test end-to-end flow by creating/updating a record in Salesforce
3. Verify CDC event appears in S3 within 5 minutes
4. Monitor AppFlow execution history and CloudWatch metrics

## References

- [Amazon AppFlow User Guide](https://docs.aws.amazon.com/appflow/latest/userguide/)
- [AppFlow Salesforce Connector](https://docs.aws.amazon.com/appflow/latest/userguide/salesforce.html)
- [Salesforce CDC Events](https://developer.salesforce.com/docs/atlas.en-us.change_data_capture.meta/change_data_capture/)
