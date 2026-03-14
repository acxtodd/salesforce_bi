# Batch Export Fallback Configuration

## Overview

This document explains the batch export fallback mechanism for the AI Search ingestion pipeline. When CDC/AppFlow is unavailable or experiencing issues, scheduled Apex batch jobs export modified records directly to the AWS ingestion endpoint.

## Architecture

```
Salesforce Batch Apex → /ingest API → Step Functions → Ingestion Pipeline
```

**Data Flow**:
1. Scheduled Apex job queries modified records (last 24 hours)
2. Batch processes records in chunks of 200
3. HTTP callout to AWS /ingest endpoint
4. Ingest Lambda starts Step Functions execution
5. Step Functions orchestrates the ingestion pipeline

## When to Use Batch Export

**Primary Use Cases**:
- CDC/AppFlow is temporarily unavailable
- Initial bulk load of historical data
- Backfill after system outage
- Testing and development environments

**Not Recommended For**:
- Real-time data synchronization (use CDC instead)
- High-frequency updates (CDC is more efficient)
- Production steady-state (CDC provides better latency)

## Salesforce Components

### 1. Custom Metadata Type: AI_Search_Config__mdt

Stores configuration for the batch export:

**Fields**:
- `Ingest_Endpoint__c` (URL): AWS API Gateway /ingest endpoint
- `API_Key__c` (Text): API key for authentication
- `Batch_Size__c` (Number): Records per batch (default: 200)
- `Hours_Back__c` (Number): Hours to look back for modified records (default: 24)
- `Enabled__c` (Checkbox): Enable/disable batch export

**Setup**:
1. Navigate to **Setup** → **Custom Metadata Types** → **AI Search Config**
2. Click **Manage Records** → **New**
3. Configure:
   - **Label**: Default
   - **AI Search Config Name**: Default
   - **Ingest Endpoint**: `https://your-api-gateway-url/ingest`
   - **API Key**: [Your API Gateway key]
   - **Batch Size**: 200
   - **Hours Back**: 24
   - **Enabled**: Checked
4. Click **Save**

### 2. Custom Object: AI_Search_Export_Error__c

Logs errors from batch export jobs:

**Fields**:
- `Job_Id__c` (Text): Async Apex job ID
- `Object_Type__c` (Text): Salesforce object type
- `Error_Message__c` (Long Text): Error message
- `Stack_Trace__c` (Long Text): Stack trace
- `Record_Count__c` (Number): Number of records in failed batch
- `Timestamp__c` (DateTime): When the error occurred

**Deployment**:
```bash
sfdx force:source:deploy -p salesforce/objects/AI_Search_Export_Error__c.object
```

### 3. Apex Class: AISearchBatchExport

Batch Apex class that exports modified records:

**Key Methods**:
- `start()`: Queries modified records for the specified object
- `execute()`: Processes batch of records and sends to AWS
- `finish()`: Logs completion and sends error notifications

**Supported Objects**:
- Account, Opportunity, Case, Note
- Property__c, Lease__c, Contract__c

**Deployment**:
```bash
sfdx force:source:deploy -p salesforce/apex/AISearchBatchExport.cls
```

### 4. Apex Class: AISearchBatchExportScheduler

Schedulable class to run batch exports:

**Key Methods**:
- `execute()`: Called by Salesforce scheduler
- `scheduleAll()`: Schedule all objects with staggered times
- `unscheduleAll()`: Remove all scheduled jobs
- `triggerExport()`: Manually trigger export for testing

**Deployment**:
```bash
sfdx force:source:deploy -p salesforce/apex/AISearchBatchExportScheduler.cls
```

## AWS Components

### Ingest Lambda Function

**Purpose**: Receive batch export requests from Salesforce and start Step Functions execution.

**Location**: `lambda/ingest/index.py`

**Environment Variables**:
- `STATE_MACHINE_ARN`: ARN of the ingestion Step Functions state machine
- `LOG_LEVEL`: Logging level (INFO, DEBUG, ERROR)

**Request Format**:
```json
{
  "sobject": "Account",
  "operation": "upsert",
  "records": [
    {
      "Id": "001xx000001234AAA",
      "Name": "ACME Corporation",
      "BillingStreet": "123 Main St",
      ...
    }
  ],
  "source": "batch_export",
  "timestamp": "2025-11-13T14:30:00Z"
}
```

**Response Format**:
```json
{
  "accepted": true,
  "jobId": "arn:aws:states:...:execution:...",
  "recordCount": 100,
  "sobject": "Account"
}
```

**Error Responses**:
- `400 Bad Request`: Invalid request format or validation error
- `500 Internal Server Error`: AWS service error

### API Gateway /ingest Endpoint

**Method**: POST
**Authentication**: API Key (x-api-key header)
**Timeout**: 29 seconds
**Rate Limiting**: 100 requests per second (configurable)

**Integration**: Lambda proxy integration with Ingest Lambda

## Setup Instructions

### Step 1: Deploy AWS Infrastructure

Deploy the ingestion stack with the ingest Lambda:

```bash
cdk deploy IngestionStack
```

Note the outputs:
- `IngestLambdaArn`: ARN of the ingest Lambda function
- `StateMachineArn`: ARN of the Step Functions state machine

### Step 2: Add /ingest Endpoint to API Gateway

Add the ingest endpoint to your API Gateway (in `lib/api-stack.ts`):

```typescript
// Add ingest resource
const ingestResource = api.root.addResource('ingest');

// Add POST method with API key authentication
ingestResource.addMethod('POST', new apigateway.LambdaIntegration(ingestLambda), {
  apiKeyRequired: true,
  requestValidator: new apigateway.RequestValidator(this, 'IngestRequestValidator', {
    restApi: api,
    validateRequestBody: true,
    validateRequestParameters: false,
  }),
});
```

Deploy the API stack:

```bash
cdk deploy ApiStack
```

Note the API Gateway URL and create an API key.

### Step 3: Configure Salesforce Remote Site Settings

Allow Salesforce to make callouts to AWS:

1. Navigate to **Setup** → **Security** → **Remote Site Settings**
2. Click **New Remote Site**
3. Configure:
   - **Remote Site Name**: AWS_AI_Search_Ingest
   - **Remote Site URL**: `https://your-api-gateway-url`
   - **Disable Protocol Security**: Unchecked
   - **Active**: Checked
4. Click **Save**

### Step 4: Deploy Salesforce Metadata

Deploy the custom metadata type and error object:

```bash
# Deploy custom metadata type
sfdx force:source:deploy -p salesforce/metadata/AI_Search_Config__mdt.xml

# Deploy error logging object
sfdx force:source:deploy -p salesforce/objects/AI_Search_Export_Error__c.object
```

### Step 5: Deploy Apex Classes

Deploy the batch export classes:

```bash
# Deploy batch export class
sfdx force:source:deploy -p salesforce/apex/AISearchBatchExport.cls

# Deploy scheduler class
sfdx force:source:deploy -p salesforce/apex/AISearchBatchExportScheduler.cls
```

### Step 6: Configure AI Search Config Metadata

Create the configuration record (see section 1 above).

### Step 7: Schedule Batch Jobs

Schedule all objects to run daily at 2 AM:

```apex
// Execute in Developer Console or Execute Anonymous
AISearchBatchExportScheduler.scheduleAll();
```

Or schedule individual objects:

```apex
// Schedule Account export daily at 2:00 AM
AISearchBatchExportScheduler scheduler = new AISearchBatchExportScheduler('Account', 24);
String cronExp = '0 0 2 * * ?';
System.schedule('AI Search Export - Account', cronExp, scheduler);
```

## Monitoring

### View Scheduled Jobs

Check scheduled jobs in Salesforce:

```apex
List<Map<String, String>> jobs = AISearchBatchExportScheduler.getScheduledJobs();
for (Map<String, String> job : jobs) {
    System.debug(job.get('Name') + ': ' + job.get('State') + ', Next: ' + job.get('NextFireTime'));
}
```

Or navigate to **Setup** → **Apex Jobs** → **Scheduled Jobs**

### View Batch Job Status

Check batch job execution history:

1. Navigate to **Setup** → **Apex Jobs** → **Apex Jobs**
2. Filter by **Job Type**: Batch Apex
3. Look for jobs starting with "AISearchBatchExport"
4. Click on a job to view:
   - Status (Queued, Processing, Completed, Failed)
   - Records processed
   - Failures
   - Start/end time

### View Export Errors

Query the error logging object:

```apex
List<AI_Search_Export_Error__c> errors = [
    SELECT Job_Id__c, Object_Type__c, Error_Message__c, Timestamp__c
    FROM AI_Search_Export_Error__c
    WHERE Timestamp__c = LAST_N_DAYS:7
    ORDER BY Timestamp__c DESC
];

for (AI_Search_Export_Error__c error : errors) {
    System.debug(error.Object_Type__c + ': ' + error.Error_Message__c);
}
```

Or create a report:
1. Navigate to **Reports** → **New Report**
2. Select **AI Search Export Errors**
3. Add columns: Object Type, Error Message, Timestamp, Record Count
4. Filter: Timestamp = Last 7 Days
5. Save and run

### CloudWatch Logs

Monitor AWS side in CloudWatch Logs:

- **Ingest Lambda**: `/aws/lambda/salesforce-ai-search-ingest`
- **Step Functions**: `/aws/vendedlogs/states/salesforce-ai-search-ingestion`

## Testing

### Manual Test - Single Object

Trigger a batch export manually for testing:

```apex
// Export Account records modified in last 1 hour
Id batchId = AISearchBatchExportScheduler.triggerExport('Account', 1);
System.debug('Batch job started: ' + batchId);

// Wait a few seconds, then check status
AsyncApexJob job = [
    SELECT Id, Status, NumberOfErrors, JobItemsProcessed, TotalJobItems
    FROM AsyncApexJob
    WHERE Id = :batchId
];
System.debug('Status: ' + job.Status + ', Processed: ' + job.JobItemsProcessed + '/' + job.TotalJobItems);
```

### End-to-End Test

Test the full batch export flow:

1. Update a record in Salesforce (e.g., Account)
2. Trigger batch export manually:
   ```apex
   Id batchId = AISearchBatchExportScheduler.triggerExport('Account', 1);
   ```
3. Wait for batch to complete (check Apex Jobs)
4. Verify HTTP callout succeeded (check Debug Logs)
5. Verify Step Functions execution started (check AWS Console)
6. Verify chunk written to data bucket
7. Query Bedrock KB to confirm chunk is indexed

**Expected Time**: 5-10 minutes (batch processing + ingestion pipeline)

### Load Test

Test with larger volume:

```apex
// Create 1000 test accounts
List<Account> accounts = new List<Account>();
for (Integer i = 0; i < 1000; i++) {
    accounts.add(new Account(
        Name = 'Test Account ' + i,
        BillingCity = 'San Francisco',
        Description = 'Test account for batch export load testing'
    ));
}
insert accounts;

// Trigger batch export
Id batchId = AISearchBatchExportScheduler.triggerExport('Account', 1);

// Monitor progress
// Batch will process 200 records at a time (5 batches total)
```

## Troubleshooting

### Batch Job Fails to Start

**Issue**: Scheduled job does not start or fails immediately.

**Solutions**:
1. Check that AI_Search_Config__mdt is configured correctly
2. Verify Remote Site Settings allow callouts to AWS
3. Check Apex class deployment status
4. Review System Debug Logs for errors
5. Ensure user has API Enabled permission

### HTTP Callout Fails

**Issue**: Batch job runs but HTTP callout to AWS fails.

**Solutions**:
1. Verify API Gateway URL is correct in AI_Search_Config__mdt
2. Check API key is valid and not expired
3. Verify Remote Site Settings include the correct URL
4. Check API Gateway logs for authentication errors
5. Test endpoint with Postman or curl
6. Verify network connectivity (firewall, proxy)

### Records Not Appearing in Search

**Issue**: Batch export succeeds but records don't appear in search results.

**Solutions**:
1. Check Step Functions execution completed successfully
2. Verify chunks were written to S3 data bucket
3. Check Bedrock KB sync status
4. Query OpenSearch directly to verify indexing
5. Check for authorization filtering (user may not have access)
6. Verify record meets indexing criteria (required fields present)

### High Latency

**Issue**: Batch export takes longer than expected.

**Solutions**:
1. Reduce batch size in AI_Search_Config__mdt (e.g., 100 instead of 200)
2. Increase Lambda timeout if needed
3. Check for Salesforce governor limits (heap size, CPU time)
4. Monitor API Gateway throttling
5. Check Step Functions execution duration
6. Consider splitting large objects into multiple scheduled jobs

### Governor Limit Errors

**Issue**: Batch job fails with governor limit errors.

**Solutions**:
1. Reduce batch size (e.g., 100 or 50)
2. Optimize SOQL queries (select only needed fields)
3. Reduce HTTP callout payload size
4. Check heap size usage (limit: 12 MB for batch Apex)
5. Avoid complex logic in execute() method

## Performance Considerations

### Batch Size

- **Default**: 200 records per batch
- **Recommended**: 100-200 for most objects
- **Large records**: 50-100 (e.g., Case with long descriptions)
- **Small records**: 200-500 (e.g., Note)

### Scheduling

- **Frequency**: Daily during off-peak hours (2-4 AM)
- **Stagger**: 10-minute intervals between objects
- **Avoid**: Peak business hours, maintenance windows

### API Limits

- **Salesforce**: 100 callouts per batch execution
- **API Gateway**: 100 requests/second (default)
- **Step Functions**: 1,000 concurrent executions (default)

### Cost Optimization

- **Salesforce**: No additional cost (uses existing API limits)
- **AWS Lambda**: $0.20 per 1M requests + compute time
- **Step Functions**: $0.025 per 1,000 state transitions
- **Estimated cost**: ~$5-10/month for daily batch of 10k records

## Best Practices

1. **Use CDC as Primary**: Batch export should be fallback only
2. **Schedule Off-Peak**: Run during low-traffic hours
3. **Monitor Errors**: Set up alerts for failed batches
4. **Test Regularly**: Run manual tests to verify functionality
5. **Optimize Queries**: Select only needed fields
6. **Handle Failures**: Implement retry logic for transient errors
7. **Log Everything**: Use Debug Logs and error object for troubleshooting
8. **Limit Scope**: Only export objects that need indexing

## Security Considerations

### API Key Management

- Store API key in Custom Metadata (encrypted at rest)
- Rotate API keys every 90 days
- Use separate keys for production and sandbox
- Never hardcode API keys in Apex code

### Data Protection

- Use HTTPS for all callouts (TLS 1.2+)
- Validate SSL certificates (don't disable protocol security)
- Sanitize PII before logging
- Respect field-level security (use WITH SECURITY_ENFORCED)

### Access Control

- Limit access to AI_Search_Config__mdt to admins only
- Use private sharing model for AI_Search_Export_Error__c
- Grant API Enabled permission only to integration users
- Monitor callout activity in Event Monitoring

## Next Steps

After batch export is configured:
1. Proceed to **Task 8.5**: Add freshness lag metrics to CloudWatch
2. Test end-to-end batch export flow
3. Monitor batch job execution and errors
4. Set up CloudWatch alarms for failures
5. Document runbook for troubleshooting

## References

- [Salesforce Batch Apex Developer Guide](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_batch.htm)
- [Salesforce HTTP Callouts](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_callouts_http.htm)
- [Salesforce Governor Limits](https://developer.salesforce.com/docs/atlas.en-us.apexcode.meta/apexcode/apex_gov_limits.htm)
