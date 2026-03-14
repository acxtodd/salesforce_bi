# Search Stack Deployment Guide

This guide covers the deployment and configuration of the SearchStack, which includes:
- OpenSearch cluster with hybrid search configuration
- Bedrock Knowledge Base with Titan Text Embeddings v2
- S3 data source integration
- Index schema with authorization metadata fields

## Prerequisites

1. NetworkStack and DataStack must be deployed first
2. AWS CLI configured with appropriate credentials
3. CDK CLI installed (`npm install -g aws-cdk`)
4. Python 3.11+ for setup scripts

## Architecture Overview

The SearchStack creates:

### OpenSearch Cluster
- **Instance Type**: r6g.large.search (2 nodes)
- **Storage**: 100GB GP3 per node (3000 IOPS)
- **Shards**: 2 primary shards, 1 replica
- **Encryption**: KMS encryption at rest, node-to-node encryption
- **Network**: VPC-based with private subnets
- **Scale**: Designed for 100k chunks (POC)

### Bedrock Knowledge Base
- **Embedding Model**: Titan Text Embeddings v2 (1024 dimensions)
- **Vector Store**: Managed OpenSearch domain (`storageConfiguration.type = "OPENSEARCH_MANAGED_CLUSTER"`)
- **Data Source**: S3 bucket (chunks/ prefix)
- **Sync Mode**: On-demand via API
- **Search Type**: Hybrid (dense vector + BM25 keyword)

### Index Schema
- **Index Name**: salesforce-chunks
- **Vector Field**: embedding (1024-dim, HNSW algorithm)
- **Text Field**: text (BM25 indexing)
- **Metadata Fields**:
  - Authorization: sharingBuckets, flsProfileTags, hasPII
  - Filtering: sobject, region, businessUnit, territory
  - Temporal: effectiveDate, lastModified
  - Content: chunkIndex, totalChunks, sourceField

## Deployment Steps

### 1. Deploy the SearchStack

```bash
# Set environment
export ENVIRONMENT=dev

# Deploy SearchStack
cdk deploy SalesforceAISearch-Search-${ENVIRONMENT}

# This will create:
# - OpenSearch cluster (takes ~15-20 minutes)
# - Bedrock Knowledge Base
# - S3 Data Source
```

### 2. Wait for OpenSearch Cluster

The OpenSearch cluster takes approximately 15-20 minutes to become available. Monitor the deployment:

```bash
# Check CloudFormation stack status
aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Search-${ENVIRONMENT} \
  --query 'Stacks[0].StackStatus'

# Check OpenSearch domain status
aws opensearch describe-domain \
  --domain-name salesforce-ai-search \
  --query 'DomainStatus.Processing'
```

### 3. Set Up OpenSearch Index

After the cluster is available, create the index with the proper schema:

```bash
# Get the OpenSearch endpoint
export OPENSEARCH_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Search-${ENVIRONMENT} \
  --query 'Stacks[0].Outputs[?OutputKey==`OpenSearchDomainEndpoint`].OutputValue' \
  --output text)

# Install Python dependencies
pip install -r scripts/requirements.txt

# Run the setup script
python scripts/setup-opensearch-index.py \
  --endpoint $OPENSEARCH_ENDPOINT \
  --region us-east-1
```

The script will:
1. Connect to OpenSearch using AWS IAM authentication
2. Create the `salesforce-chunks` index with proper mappings
3. Configure hybrid search (vector + BM25)
4. Set up authorization metadata fields
5. Verify the index was created correctly

### 4. Verify Deployment

```bash
# Get all stack outputs
aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Search-${ENVIRONMENT} \
  --query 'Stacks[0].Outputs'

# Test OpenSearch connectivity
curl -XGET "https://${OPENSEARCH_ENDPOINT}/_cluster/health" \
  --aws-sigv4 "aws:amz:us-east-1:es" \
  --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY"

# Verify index exists
curl -XGET "https://${OPENSEARCH_ENDPOINT}/salesforce-chunks" \
  --aws-sigv4 "aws:amz:us-east-1:es" \
  --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY"
```

## Configuration Details

### OpenSearch Cluster Configuration

**Capacity**:
- 2 data nodes (r6g.large.search)
- 4 vCPU, 16 GB RAM per node
- 100 GB GP3 storage per node
- Total capacity: ~200 GB, 8 vCPU, 32 GB RAM

**Performance**:
- 3000 IOPS per node (GP3 baseline)
- 125 MB/s throughput per node
- Designed for 100k chunks (POC scale)
- Can scale to 1M chunks with additional nodes

**Security**:
- VPC-based deployment (private subnets)
- KMS encryption at rest
- Node-to-node encryption (TLS)
- Fine-grained access control with IAM
- No public endpoint

### Bedrock Knowledge Base Configuration

**Embedding Model**:
- Model: amazon.titan-embed-text-v2:0
- Dimensions: 1024
- Cost: $0.0001 per 1k tokens
- Language: English (primary)

**Hybrid Search**:
- Dense vector search (cosine similarity)
- BM25 keyword search (standard analyzer)
- Default weights: 0.5 vector, 0.5 keyword
- Configurable at query time

**Data Source**:
- S3 bucket: salesforce-ai-search-data-{account}-{region}
- Prefix: chunks/
- Format: JSON with text, embedding, metadata
- Sync: On-demand via StartIngestionJob API

### Index Schema Details

**Vector Configuration**:
- Algorithm: HNSW (Hierarchical Navigable Small World)
- Space: Cosine similarity
- Engine: nmslib
- Parameters:
  - ef_construction: 512 (build-time accuracy)
  - m: 16 (connections per node)
  - ef_search: 512 (query-time accuracy)

**Text Configuration**:
- Analyzer: Standard (lowercase, stop words)
- Tokenizer: Standard
- BM25 scoring with default parameters

**Metadata Fields**:

*Authorization Fields*:
- `sharingBuckets`: Array of sharing rule tags
  - Format: "territory:EMEA", "role:SalesManager", "owner:005xx"
  - Used for filtering results by user access
- `flsProfileTags`: Array of field-level security tags
  - Format: "profile:Standard", "permset:SalesAnalytics"
  - Used for field-level access control
- `hasPII`: Boolean flag for PII content
  - Used to apply additional security controls

*Filtering Fields*:
- `sobject`: Salesforce object type (Account, Opportunity, etc.)
- `region`: Geographic region (EMEA, AMER, APAC)
- `businessUnit`: Business unit (Enterprise, SMB, etc.)
- `territory`: Sales territory
- `ownerId`: Record owner ID

*Temporal Fields*:
- `effectiveDate`: When the record became effective
- `lastModified`: Last modification timestamp
- Used for freshness filtering and sorting

## Testing the Deployment

### 1. Test OpenSearch Cluster

```bash
# Check cluster health
curl -XGET "https://${OPENSEARCH_ENDPOINT}/_cluster/health?pretty" \
  --aws-sigv4 "aws:amz:us-east-1:es" \
  --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY"

# Expected: status "green" or "yellow"

# Check index stats
curl -XGET "https://${OPENSEARCH_ENDPOINT}/salesforce-chunks/_stats?pretty" \
  --aws-sigv4 "aws:amz:us-east-1:es" \
  --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY"
```

### 2. Test Bedrock Knowledge Base

```bash
# Get Knowledge Base ID
export KB_ID=$(aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Search-${ENVIRONMENT} \
  --query 'Stacks[0].Outputs[?OutputKey==`KnowledgeBaseId`].OutputValue' \
  --output text)

# Get Knowledge Base details
aws bedrock-agent get-knowledge-base \
  --knowledge-base-id $KB_ID

# Get Data Source details
export DS_ID=$(aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Search-${ENVIRONMENT} \
  --query 'Stacks[0].Outputs[?OutputKey==`DataSourceId`].OutputValue' \
  --output text)

aws bedrock-agent get-data-source \
  --knowledge-base-id $KB_ID \
  --data-source-id $DS_ID
```

### 3. Test Index with Sample Document

```python
# test_index.py
import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Setup
region = 'us-east-1'
endpoint = 'your-opensearch-endpoint'
credentials = boto3.Session().get_credentials()
awsauth = AWS4Auth(credentials.access_key, credentials.secret_key, region, 'es', session_token=credentials.token)

client = OpenSearch(
    hosts=[{'host': endpoint, 'port': 443}],
    http_auth=awsauth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection
)

# Index a test document
doc = {
    'id': 'test-001',
    'text': 'This is a test document for Salesforce AI Search',
    'embedding': [0.1] * 1024,  # Dummy embedding
    'metadata': {
        'sobject': 'Account',
        'recordId': '001xx',
        'region': 'EMEA',
        'sharingBuckets': ['territory:EMEA'],
        'hasPII': False
    }
}

response = client.index(index='salesforce-chunks', body=doc, id='test-001')
print(f"Indexed document: {response}")

# Search for the document
query = {
    'query': {
        'match': {
            'text': 'test document'
        }
    }
}

response = client.search(index='salesforce-chunks', body=query)
print(f"Search results: {response}")
```

## Monitoring

### CloudWatch Metrics

The OpenSearch cluster automatically publishes metrics to CloudWatch:

- **Cluster Health**: ClusterStatus.green, ClusterStatus.yellow, ClusterStatus.red
- **Performance**: SearchLatency, IndexingLatency, SearchRate, IndexingRate
- **Resources**: CPUUtilization, JVMMemoryPressure, DiskQueueDepth
- **Storage**: FreeStorageSpace, ClusterUsedSpace

### CloudWatch Alarms

Recommended alarms:
- ClusterStatus.red > 0 for 5 minutes (critical)
- CPUUtilization > 80% for 15 minutes (warning)
- JVMMemoryPressure > 80% for 10 minutes (warning)
- FreeStorageSpace < 20% (warning)

### Logs

OpenSearch logs are published to CloudWatch Logs:
- `/aws/opensearch/domains/salesforce-ai-search/application-logs`
- `/aws/opensearch/domains/salesforce-ai-search/search-logs`
- `/aws/opensearch/domains/salesforce-ai-search/index-logs`

## Troubleshooting

### OpenSearch Cluster Issues

**Cluster stuck in "Processing" state**:
- Wait 20-30 minutes for initial deployment
- Check CloudFormation events for errors
- Verify VPC and subnet configuration

**Cannot connect to cluster**:
- Verify security groups allow access
- Check IAM permissions for es:ESHttp* actions
- Ensure VPC endpoints are configured

**Index creation fails**:
- Verify cluster is in "Active" state
- Check IAM permissions
- Review OpenSearch logs in CloudWatch

### Bedrock Knowledge Base Issues

**Knowledge Base creation fails**:
- Verify IAM role has correct permissions
- Check S3 bucket exists and is accessible
- Ensure Bedrock service is available in region

**Data source sync fails**:
- Verify S3 bucket has data in chunks/ prefix
- Check data format matches expected schema
- Review Bedrock Agent logs

## Scaling Considerations

### Current Configuration (POC)
- Capacity: 100k chunks
- Throughput: ~100 queries/second
- Latency: p95 < 200ms for retrieval

### Scaling to Pilot (1M chunks)
- Add 1-2 more data nodes (3-4 total)
- Increase instance size to r6g.xlarge
- Add more shards (4-6 primary shards)
- Enable Multi-AZ with standby

### Scaling to Production (10M+ chunks)
- Use dedicated master nodes (3x)
- Scale data nodes to 6-10 nodes
- Use r6g.2xlarge or larger instances
- Increase shards to 10-20 primary shards
- Enable UltraWarm for cold data
- Consider OpenSearch Serverless

## Cost Estimation

### POC Configuration
- OpenSearch: ~$200-300/month (2x r6g.large)
- Bedrock Embeddings: ~$10-50/month (100k chunks)
- Bedrock Queries: ~$20-100/month (1000 queries/day)
- Data Transfer: ~$10-20/month
- **Total**: ~$250-500/month

### Pilot Configuration
- OpenSearch: ~$600-900/month (4x r6g.xlarge)
- Bedrock Embeddings: ~$100-200/month (1M chunks)
- Bedrock Queries: ~$200-500/month (10k queries/day)
- Data Transfer: ~$50-100/month
- **Total**: ~$1000-2000/month

## Next Steps

After deploying the SearchStack:

1. **Deploy IngestionStack**: Set up the data ingestion pipeline
2. **Test Ingestion**: Ingest sample Salesforce records
3. **Verify Indexing**: Check that chunks appear in OpenSearch
4. **Test Retrieval**: Query the Knowledge Base via Bedrock API
5. **Deploy API Stack**: Set up Lambda functions for /retrieve and /answer endpoints
6. **End-to-End Testing**: Test the full flow from LWC to OpenSearch and back

## References

- [OpenSearch Documentation](https://opensearch.org/docs/latest/)
- [Bedrock Knowledge Base Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
- [Titan Embeddings Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)
- [HNSW Algorithm](https://arxiv.org/abs/1603.09320)
