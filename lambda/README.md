# Salesforce AI Search - Data Ingestion Pipeline

This directory contains Lambda functions for the data ingestion and chunking pipeline.

## Architecture

The ingestion pipeline processes Salesforce records through the following stages:

1. **Validate** - Validates record structure and required fields
2. **Transform** - Flattens relationships and extracts text fields
3. **Chunk** - Splits text into 300-500 token segments with heading retention
4. **Enrich** - Adds metadata (sobject, recordId, parentIds, ownerId, territory, businessUnit, region, sharingBuckets, flsProfileTags)
5. **Embed** - Generates embeddings using Titan Text Embeddings v2
6. **Sync** - Writes to S3 in Bedrock KB format

## Lambda Functions

### validate/
Validates Salesforce records before processing.
- Checks for required fields (Id, LastModifiedDate)
- Validates object type is supported (7 POC objects)
- Returns valid and invalid records

### transform/
Transforms and flattens Salesforce records.
- Flattens nested relationship objects
- Extracts text fields for chunking
- Prepares records for chunking

### chunking/
Splits text into 300-500 token chunks.
- Implements text splitting with heading retention
- Generates chunk IDs: `{sobject}/{recordId}/chunk-{index}`
- Hardcoded field mappings for 7 POC objects:
  - Account, Opportunity, Case, Note
  - Property__c, Lease__c, Contract__c

### enrich/
Enriches chunks with authorization and business metadata.
- Adds sharing buckets (owner, territory, businessUnit, region)
- Adds FLS profile tags (POC: no FLS enforcement)
- Marks PII status (POC: false)
- Sets effective date

### embed/
Generates embeddings using Amazon Bedrock.
- Uses Titan Text Embeddings v2 model
- Batches up to 25 chunks per request
- 1024-dimensional normalized embeddings
- Handles batching for efficient processing

### sync/
Writes embedded chunks to S3.
- Formats chunks in Bedrock KB expected format
- Writes to S3 in JSONL format
- Triggers Bedrock KB sync (future enhancement)

## POC Object Field Mappings

The chunking Lambda uses hardcoded field mappings for 7 objects:

```python
POC_OBJECT_FIELDS = {
    "Account": {
        "text_fields": ["Name", "BillingStreet", "BillingCity", "BillingState", "Phone", "Website"],
        "long_text_fields": ["Description"],
        "relationship_fields": ["OwnerId", "ParentId"],
        "display_name": "Name"
    },
    "Opportunity": {
        "text_fields": ["Name", "StageName", "LeadSource"],
        "long_text_fields": ["Description"],
        "relationship_fields": ["AccountId", "OwnerId"],
        "display_name": "Name"
    },
    # ... (see chunking/index.py for complete mappings)
}
```

## Step Functions Workflow

The workflow is defined in `stepfunctions/ingestion-workflow.json` and orchestrates:
- Sequential execution of Lambda functions
- Error handling and retry logic (exponential backoff)
- Dead Letter Queue (DLQ) for failed records
- State transitions based on validation results

## Environment Variables

### sync/
- `DATA_BUCKET` - S3 bucket for storing chunks

## Deployment

Lambda functions are deployed via CDK in `lib/ingestion-stack.ts`:

```bash
npm run build
npm run deploy
```

## Testing

To test the pipeline locally, create a test event:

```json
{
  "records": [
    {
      "sobject": "Account",
      "data": {
        "Id": "001xx000001234567",
        "Name": "ACME Corporation",
        "Description": "Leading provider of enterprise solutions...",
        "OwnerId": "005xx000001234567",
        "LastModifiedDate": "2025-11-13T10:30:00Z"
      }
    }
  ]
}
```

Invoke the Step Functions state machine with this event to test end-to-end processing.

## Requirements

- Python 3.11
- boto3 (for embed and sync functions)
- AWS Lambda execution role with:
  - VPC access
  - S3 read/write permissions
  - Bedrock InvokeModel permissions
  - KMS encrypt/decrypt permissions

## Performance

- **Validate**: ~10ms per record
- **Transform**: ~5ms per record
- **Chunk**: ~50ms per record (depends on text length)
- **Enrich**: ~10ms per chunk
- **Embed**: ~100ms per batch (25 chunks)
- **Sync**: ~50ms per batch

Total pipeline latency: ~2-5 minutes for CDC path (P50 target: 5 minutes)
