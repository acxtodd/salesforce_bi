# Infrastructure Reference - Task 1 Implementation

## Overview

This document provides a detailed reference for the AWS infrastructure foundation deployed for the Salesforce AI Search POC.

## Task 1 Checklist

### ✅ VPC with Private Subnets and Security Groups
- **VPC**: Multi-AZ VPC with CIDR block automatically assigned
- **Subnets**: 
  - 2 private subnets (one per AZ) for Lambda functions
  - 2 public subnets (one per AZ) for NAT Gateway
- **NAT Gateway**: Single NAT Gateway for cost optimization (POC)
- **Security Group**: Lambda security group with all outbound traffic allowed
- **DNS**: DNS hostnames and DNS support enabled

**Code Location**: `lib/network-stack.ts` lines 20-38

### ✅ VPC Endpoints for AWS Services
- **S3 Gateway Endpoint**: For S3 access without internet gateway
- **DynamoDB Gateway Endpoint**: For DynamoDB access without internet gateway
- **Bedrock Runtime Interface Endpoint**: For Bedrock API calls
- **Bedrock Agent Runtime Interface Endpoint**: For Bedrock Agent API calls
- **OpenSearch Interface Endpoint**: For OpenSearch cluster access

All interface endpoints have:
- Private DNS enabled
- Attached to Lambda security group
- Deployed in private subnets

**Code Location**: `lib/network-stack.ts` lines 46-93

### ✅ KMS Keys for Encryption at Rest
- **Key Type**: Customer-managed symmetric key
- **Key Rotation**: Enabled (automatic annual rotation)
- **Removal Policy**: RETAIN (prevents accidental deletion)
- **Alias**: `salesforce-ai-search-poc`
- **Usage**: Shared across S3, DynamoDB, and future OpenSearch

**Code Location**: `lib/network-stack.ts` lines 15-20

### ✅ S3 Buckets with Lifecycle Policies

#### Data Bucket
- **Purpose**: Store chunked Salesforce documents
- **Versioning**: Enabled
- **Encryption**: KMS with customer-managed key
- **Public Access**: Blocked
- **Logging**: Access logs to logs bucket
- **Lifecycle**:
  - Old versions → Glacier after 90 days
  - Old versions expire after 365 days

#### Embeddings Bucket
- **Purpose**: Store vector embeddings
- **Versioning**: Disabled (embeddings are immutable)
- **Encryption**: KMS with customer-managed key
- **Public Access**: Blocked
- **Logging**: Access logs to logs bucket
- **Lifecycle**:
  - Intelligent Tiering after 30 days

#### Logs Bucket
- **Purpose**: Centralized access logs
- **Versioning**: Disabled
- **Encryption**: KMS with customer-managed key
- **Public Access**: Blocked
- **Lifecycle**:
  - IA after 30 days
  - Glacier after 90 days
  - Expire after 365 days

**Code Location**: `lib/data-stack.ts` lines 22-123

### ✅ DynamoDB Tables

#### Telemetry Table
- **Purpose**: Store query/answer metrics and timing
- **Keys**: 
  - Partition: `requestId` (String)
  - Sort: `timestamp` (Number)
- **GSI**: `salesforceUserId-timestamp-index` for user-specific queries
- **TTL**: 90 days (automatic deletion)
- **Billing**: On-demand (pay per request)
- **Encryption**: KMS customer-managed
- **Point-in-Time Recovery**: Enabled

#### Sessions Table
- **Purpose**: Store multi-turn conversation history
- **Keys**:
  - Partition: `sessionId` (String)
  - Sort: `turnNumber` (Number)
- **GSI**: `salesforceUserId-timestamp-index` for user history
- **TTL**: 30 days (automatic deletion)
- **Billing**: On-demand (pay per request)
- **Encryption**: KMS customer-managed
- **Point-in-Time Recovery**: Enabled

#### AuthZ Cache Table
- **Purpose**: Cache user authorization context
- **Keys**:
  - Partition: `salesforceUserId` (String)
- **TTL**: 24 hours (automatic deletion)
- **Billing**: On-demand (pay per request)
- **Encryption**: KMS customer-managed
- **Point-in-Time Recovery**: Enabled

**Code Location**: `lib/data-stack.ts` lines 125-217

## Requirements Mapping

### Requirement 4.2: Private Networking
✅ **Implemented**: 
- VPC with private subnets only for Lambda
- VPC endpoints for all AWS services
- No public internet access for data services

### Requirement 4.3: Encryption at Rest
✅ **Implemented**:
- KMS customer-managed key with rotation
- S3 buckets encrypted with KMS
- DynamoDB tables encrypted with KMS
- OpenSearch will use same KMS key (Task 3)

### Requirement 4.4: No Public S3 Buckets
✅ **Implemented**:
- All S3 buckets have `BlockPublicAccess.BLOCK_ALL`
- No bucket policies allowing public access
- Access logs enabled for audit trail

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         AWS Account                          │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                    VPC (2 AZs)                         │ │
│  │                                                        │ │
│  │  ┌──────────────┐              ┌──────────────┐      │ │
│  │  │ Private      │              │ Private      │      │ │
│  │  │ Subnet AZ-A  │              │ Subnet AZ-B  │      │ │
│  │  │              │              │              │      │ │
│  │  │ [Lambda SG]  │              │ [Lambda SG]  │      │ │
│  │  └──────┬───────┘              └──────┬───────┘      │ │
│  │         │                             │              │ │
│  │         └─────────────┬───────────────┘              │ │
│  │                       │                              │ │
│  │         ┌─────────────▼──────────────┐               │ │
│  │         │   VPC Endpoints            │               │ │
│  │         │   - S3 (Gateway)           │               │ │
│  │         │   - DynamoDB (Gateway)     │               │ │
│  │         │   - Bedrock (Interface)    │               │ │
│  │         │   - OpenSearch (Interface) │               │ │
│  │         └────────────────────────────┘               │ │
│  │                                                        │ │
│  │  ┌──────────────┐              ┌──────────────┐      │ │
│  │  │ Public       │              │ Public       │      │ │
│  │  │ Subnet AZ-A  │              │ Subnet AZ-B  │      │ │
│  │  │              │              │              │      │ │
│  │  │ [NAT GW]     │              │              │      │ │
│  │  └──────────────┘              └──────────────┘      │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                    S3 Buckets                          │ │
│  │  - Data Bucket (versioned, lifecycle)                 │ │
│  │  - Embeddings Bucket (intelligent tiering)            │ │
│  │  - Logs Bucket (access logs, lifecycle)               │ │
│  │  [All encrypted with KMS]                             │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                 DynamoDB Tables                        │ │
│  │  - Telemetry (90d TTL, GSI)                           │ │
│  │  - Sessions (30d TTL, GSI)                            │ │
│  │  - AuthZ Cache (24h TTL)                              │ │
│  │  [All encrypted with KMS, PITR enabled]               │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                    KMS Key                             │ │
│  │  - Customer-managed                                    │ │
│  │  - Automatic rotation enabled                          │ │
│  │  - Alias: salesforce-ai-search-poc                     │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Stack Dependencies

```
NetworkStack (creates VPC, KMS, Security Groups)
    │
    └──> DataStack (uses VPC and KMS from NetworkStack)
```

## Exported Values

### NetworkStack Exports
- `SalesforceAISearch-Network-dev-VpcId`
- `SalesforceAISearch-Network-dev-KmsKeyId`
- `SalesforceAISearch-Network-dev-KmsKeyArn`
- `SalesforceAISearch-Network-dev-LambdaSecurityGroupId`

### DataStack Exports
- `SalesforceAISearch-Data-dev-DataBucketName`
- `SalesforceAISearch-Data-dev-EmbeddingsBucketName`
- `SalesforceAISearch-Data-dev-LogsBucketName`
- `SalesforceAISearch-Data-dev-TelemetryTableName`
- `SalesforceAISearch-Data-dev-SessionsTableName`
- `SalesforceAISearch-Data-dev-AuthzCacheTableName`

These exports can be imported by subsequent stacks (SearchStack, APIStack, etc.).

## Security Best Practices Implemented

1. ✅ **Least Privilege**: Security groups allow only necessary outbound traffic
2. ✅ **Encryption**: All data encrypted at rest with customer-managed keys
3. ✅ **Network Isolation**: Private subnets with no direct internet access
4. ✅ **Audit Logging**: S3 access logs enabled for all buckets
5. ✅ **Key Rotation**: KMS key rotation enabled automatically
6. ✅ **Point-in-Time Recovery**: Enabled for all DynamoDB tables
7. ✅ **Versioning**: Enabled for data bucket to prevent accidental deletion
8. ✅ **Lifecycle Policies**: Automatic archival and deletion to reduce costs
9. ✅ **Retention Policies**: RETAIN on critical resources to prevent data loss
10. ✅ **Public Access Blocking**: All S3 buckets block public access

## Cost Optimization Features

1. **Single NAT Gateway**: Reduces cost from ~$64/month to ~$32/month
2. **On-Demand DynamoDB**: Pay only for actual usage (no provisioned capacity)
3. **S3 Lifecycle Policies**: Automatic transition to cheaper storage classes
4. **Intelligent Tiering**: S3 automatically moves data to optimal storage class
5. **TTL on DynamoDB**: Automatic deletion of old data reduces storage costs
6. **Gateway Endpoints**: Free for S3 and DynamoDB (vs. interface endpoints)

## Monitoring and Observability

All resources are tagged with:
- `Project: SalesforceAISearch`
- `Environment: dev/staging/production`
- `ManagedBy: CDK`
- `Component: Network/Data`

Use these tags for:
- Cost allocation reports
- Resource grouping
- Automated operations
- Compliance tracking

## Future Enhancements

The infrastructure is designed to support future additions:

1. **Multi-Region**: VPC peering or Transit Gateway for multi-region deployment
2. **High Availability**: Additional NAT Gateways (one per AZ)
3. **Disaster Recovery**: Cross-region replication for S3 and DynamoDB
4. **Enhanced Monitoring**: VPC Flow Logs, CloudWatch Logs Insights
5. **Cost Optimization**: Reserved capacity for DynamoDB, S3 Glacier Deep Archive
6. **Security**: AWS WAF, GuardDuty, Security Hub integration

## Related Documentation

- [README.md](README.md) - Project overview and quick start
- [DEPLOYMENT.md](DEPLOYMENT.md) - Step-by-step deployment guide
- [Design Document](.kiro/specs/salesforce-ai-search-poc/design.md) - Full system design
- [Requirements](.kiro/specs/salesforce-ai-search-poc/requirements.md) - Detailed requirements
