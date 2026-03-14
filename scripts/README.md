# OpenSearch Setup Scripts

This directory contains scripts for setting up and managing the OpenSearch cluster for the Salesforce AI Search POC.

## Prerequisites

1. AWS CLI configured with appropriate credentials
2. Python 3.11 or higher
3. OpenSearch cluster deployed via CDK

## Installation

Install the required Python packages:

```bash
pip install -r scripts/requirements.txt
```

## Setup OpenSearch Index

After deploying the SearchStack via CDK, run this script to create the OpenSearch index with the proper schema:

```bash
# Get the OpenSearch endpoint from CDK outputs
export OPENSEARCH_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Search-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`OpenSearchDomainEndpoint`].OutputValue' \
  --output text)

# Run the setup script
python scripts/setup-opensearch-index.py \
  --endpoint $OPENSEARCH_ENDPOINT \
  --region us-east-1
```

### Script Options

- `--endpoint`: OpenSearch domain endpoint (required, without https://)
- `--region`: AWS region (default: us-east-1)
- `--index-name`: Index name (default: salesforce-chunks)

### What the Script Does

1. Connects to the OpenSearch cluster using AWS IAM authentication
2. Creates an index named `salesforce-chunks` with:
   - **2 primary shards** and **1 replica** (POC scale)
   - **Vector field** for embeddings (1024 dimensions for Titan v2)
   - **Text field** for chunk content with BM25 indexing
   - **Metadata fields** for authorization and filtering:
     - `sobject`: Salesforce object type
     - `recordId`: Salesforce record ID
     - `sharingBuckets`: Authorization tags for sharing rules
     - `flsProfileTags`: Field-level security tags
     - `hasPII`: Boolean flag for PII content
     - `region`, `businessUnit`, `territory`: Filtering fields
     - Additional fields for dates, ownership, and object-specific data
3. Configures hybrid search with:
   - **HNSW algorithm** for vector search (cosine similarity)
   - **Standard analyzer** for BM25 keyword search
4. Verifies the index was created correctly

### Index Schema

The index supports hybrid search combining:
- **Dense vector search**: Using Titan Text Embeddings v2 (1024-dim)
- **BM25 keyword search**: Using standard text analysis

Key metadata fields for authorization:
- `sharingBuckets`: Array of sharing rule tags (e.g., "territory:EMEA", "role:SalesManager")
- `flsProfileTags`: Array of field-level security tags (e.g., "profile:Standard")
- `hasPII`: Boolean indicating if chunk contains PII

Filtering fields:
- `sobject`: Filter by Salesforce object type
- `region`: Filter by geographic region
- `businessUnit`: Filter by business unit
- `territory`: Filter by sales territory
- `ownerId`: Filter by record owner

## Troubleshooting

### Connection Issues

If you get connection errors:
1. Verify the OpenSearch cluster is deployed and healthy
2. Check that your AWS credentials have permissions to access OpenSearch
3. Verify the VPC endpoints are configured correctly
4. Ensure the security groups allow access from your IP (if running locally)

### Index Already Exists

If the index already exists, the script will prompt you to delete and recreate it. This is useful for updating the schema during development.

### Permission Errors

Ensure your IAM role/user has the following permissions:
- `es:ESHttpGet`
- `es:ESHttpPut`
- `es:ESHttpPost`
- `es:ESHttpDelete`
- `es:DescribeElasticsearchDomain`

## Next Steps

After setting up the index:
1. Deploy the ingestion pipeline (IngestionStack)
2. Test the pipeline by ingesting sample Salesforce records
3. Verify chunks are indexed correctly in OpenSearch
4. Test hybrid search queries via the Bedrock Knowledge Base
