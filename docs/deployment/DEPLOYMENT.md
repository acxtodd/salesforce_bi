# Deployment Guide - Salesforce AI Search POC Infrastructure

This guide walks through deploying the AWS infrastructure foundation for the Salesforce AI Search POC.

## Task 1: AWS Infrastructure Foundation

This deployment implements the following components as specified in the requirements:

### Components Deployed

#### Network Infrastructure
- ✅ VPC with private subnets (2 AZs) for Lambda functions
- ✅ Security groups for Lambda functions with controlled egress
- ✅ VPC Gateway Endpoints for S3 and DynamoDB
- ✅ VPC Interface Endpoints for:
  - Bedrock Runtime
  - Bedrock Agent Runtime  
  - OpenSearch (ES)

#### Encryption
- ✅ KMS customer-managed key for encryption at rest
- ✅ Automatic key rotation enabled
- ✅ Used across all services (S3, DynamoDB)

#### Storage (S3)
- ✅ Data bucket for chunked documents
  - Versioning enabled
  - KMS encryption
  - Lifecycle policies (Glacier after 90 days)
- ✅ Embeddings bucket for vector embeddings
  - KMS encryption
  - Intelligent Tiering after 30 days
- ✅ Logs bucket for access logs
  - KMS encryption
  - Lifecycle policies (IA→Glacier→Expire)

#### Database (DynamoDB)
- ✅ Telemetry table with GSI for user queries
  - 90-day TTL
  - Point-in-time recovery
- ✅ Sessions table with GSI for user history
  - 30-day TTL
  - Point-in-time recovery
- ✅ AuthZ cache table
  - 24-hour TTL
  - Point-in-time recovery

### Requirements Satisfied

- **Requirement 4.2**: Private networking - VPC endpoints ensure no public internet traffic
- **Requirement 4.3**: Encryption at rest - KMS encryption for S3, DynamoDB, OpenSearch
- **Requirement 4.4**: No public S3 buckets - All buckets block public access

## Prerequisites

1. **AWS Account**: Active AWS account with appropriate permissions
2. **AWS CLI**: Installed and configured
   ```bash
   aws configure
   ```
3. **Node.js**: Version 18 or higher
4. **AWS CDK**: Installed globally
   ```bash
   npm install -g aws-cdk
   ```

## Step-by-Step Deployment

### 1. Install Dependencies

```bash
npm install
```

### 2. Bootstrap CDK (First Time Only)

```bash
cdk bootstrap aws://ACCOUNT-ID/REGION
```

Replace `ACCOUNT-ID` and `REGION` with your values.

### 3. Review Infrastructure

Synthesize the CloudFormation templates to review what will be created:

```bash
npm run synth
```

This generates CloudFormation templates in the `cdk.out` directory.

### 4. Deploy Network Stack

Deploy the VPC, security groups, VPC endpoints, and KMS key:

```bash
cdk deploy SalesforceAISearch-Network-dev
```

**Expected Resources**:
- 1 VPC with 2 AZs
- 2 private subnets, 2 public subnets
- 1 NAT Gateway
- 1 Internet Gateway
- 2 Gateway VPC Endpoints (S3, DynamoDB)
- 3 Interface VPC Endpoints (Bedrock Runtime, Bedrock Agent Runtime, OpenSearch)
- 1 KMS Key with rotation enabled
- 1 Lambda Security Group

**Deployment Time**: ~5-7 minutes

### 5. Deploy Data Stack

Deploy S3 buckets and DynamoDB tables:

```bash
cdk deploy SalesforceAISearch-Data-dev
```

**Expected Resources**:
- 3 S3 Buckets (data, embeddings, logs)
- 3 DynamoDB Tables (telemetry, sessions, authz-cache)
- Lifecycle policies on all buckets
- GSIs on telemetry and sessions tables

**Deployment Time**: ~3-5 minutes

### 6. Deploy All Stacks at Once

Alternatively, deploy both stacks together:

```bash
npm run deploy
```

This will deploy NetworkStack first, then DataStack (due to dependency).

## Verification

### 1. Verify VPC and Endpoints

```bash
# Get VPC ID from stack outputs
VPC_ID=$(aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Network-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`VpcId`].OutputValue' \
  --output text)

# List VPC endpoints
aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'VpcEndpoints[*].[ServiceName,State]' \
  --output table
```

Expected output: 5 endpoints (S3, DynamoDB, Bedrock Runtime, Bedrock Agent Runtime, OpenSearch) in "available" state.

### 2. Verify KMS Key

```bash
# Get KMS Key ID
KMS_KEY_ID=$(aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Network-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`KmsKeyId`].OutputValue' \
  --output text)

# Verify key rotation is enabled
aws kms get-key-rotation-status --key-id $KMS_KEY_ID
```

Expected output: `"KeyRotationEnabled": true`

### 3. Verify S3 Buckets

```bash
# List buckets
aws s3 ls | grep salesforce-ai-search

# Verify encryption on data bucket
DATA_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Data-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

aws s3api get-bucket-encryption --bucket $DATA_BUCKET
```

Expected output: KMS encryption configuration with the KMS key ARN.

### 4. Verify DynamoDB Tables

```bash
# List tables
aws dynamodb list-tables | grep salesforce-ai-search

# Describe telemetry table
aws dynamodb describe-table \
  --table-name salesforce-ai-search-telemetry \
  --query 'Table.[TableName,TableStatus,BillingModeSummary,SSEDescription]'
```

Expected output: Table in "ACTIVE" status with PAY_PER_REQUEST billing and KMS encryption.

### 5. Verify Security

```bash
# Verify no public S3 buckets
aws s3api get-public-access-block --bucket $DATA_BUCKET
```

Expected output: All public access blocked.

## Stack Outputs

After deployment, retrieve important values:

```bash
# Network Stack outputs
aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Network-dev \
  --query 'Stacks[0].Outputs'

# Data Stack outputs
aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Data-dev \
  --query 'Stacks[0].Outputs'
```

Save these outputs for use in subsequent stack deployments.

## Cost Estimation

### Monthly Costs (POC Scale)

- **VPC**: 
  - NAT Gateway: ~$32/month
  - VPC Endpoints: ~$22/month (5 endpoints × $7.20/month × 0.6 utilization)
- **S3**: 
  - Storage: ~$5/month (100 GB)
  - Requests: ~$1/month
- **DynamoDB**: 
  - On-demand: ~$10/month (low traffic)
- **KMS**: 
  - Key: $1/month
  - API calls: ~$1/month

**Total Estimated Cost**: ~$72/month for infrastructure foundation

## Troubleshooting

### Issue: VPC Endpoint Creation Fails

**Error**: `Service com.amazonaws.REGION.bedrock-runtime not available`

**Solution**: Verify Bedrock is available in your region:
```bash
aws ec2 describe-vpc-endpoint-services --region us-east-1 | grep bedrock
```

If not available, deploy to a supported region (us-east-1, us-west-2).

### Issue: S3 Bucket Name Already Exists

**Error**: `Bucket name already exists`

**Solution**: Bucket names are globally unique. Modify bucket names in `lib/data-stack.ts` to include a unique suffix:
```typescript
bucketName: `salesforce-ai-search-data-${this.account}-${this.region}-${Date.now()}`
```

### Issue: KMS Key Permissions

**Error**: `User is not authorized to perform: kms:CreateKey`

**Solution**: Add KMS permissions to your IAM role:
```json
{
  "Effect": "Allow",
  "Action": [
    "kms:CreateKey",
    "kms:DescribeKey",
    "kms:EnableKeyRotation",
    "kms:PutKeyPolicy"
  ],
  "Resource": "*"
}
```

### Issue: DynamoDB Table Already Exists

**Error**: `Table already exists`

**Solution**: If redeploying after a failed deployment, delete the existing table:
```bash
aws dynamodb delete-table --table-name salesforce-ai-search-telemetry
```

Wait for deletion to complete, then redeploy.

## Cleanup

To remove all infrastructure:

```bash
# Delete stacks in reverse order
cdk destroy SalesforceAISearch-Data-dev
cdk destroy SalesforceAISearch-Network-dev
```

**Note**: Due to `RETAIN` removal policy, you must manually delete:
1. S3 buckets (after emptying them)
2. DynamoDB tables
3. KMS key (after 7-day waiting period)

```bash
# Empty and delete S3 buckets
aws s3 rm s3://$DATA_BUCKET --recursive
aws s3 rb s3://$DATA_BUCKET

# Delete DynamoDB tables
aws dynamodb delete-table --table-name salesforce-ai-search-telemetry
aws dynamodb delete-table --table-name salesforce-ai-search-sessions
aws dynamodb delete-table --table-name salesforce-ai-search-authz-cache

# Schedule KMS key deletion (7-30 days)
aws kms schedule-key-deletion --key-id $KMS_KEY_ID --pending-window-in-days 7
```

## Next Steps

After successfully deploying the infrastructure foundation:

1. ✅ **Task 1 Complete**: AWS infrastructure foundation deployed
2. ⏭️ **Task 2**: Implement data ingestion and chunking pipeline
3. ⏭️ **Task 3**: Set up Bedrock Knowledge Base and OpenSearch
4. ⏭️ **Task 4**: Implement AuthZ Sidecar Lambda
5. ⏭️ **Task 5**: Implement Retrieve Lambda and /retrieve endpoint

## Support

For issues or questions:
- Review [README.md](README.md) for architecture overview
- Check [Design Document](.kiro/specs/salesforce-ai-search-poc/design.md)
- Review [Requirements](.kiro/specs/salesforce-ai-search-poc/requirements.md)
- AWS CDK Documentation: https://docs.aws.amazon.com/cdk/
