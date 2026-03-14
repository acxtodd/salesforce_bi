# CDK Infrastructure - Quick Reference Guide

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────┐
│                   MonitoringStack                        │
│        (CloudWatch, SNS Topics, Dashboards)              │
└─────────────────────────────────────────────────────────┘
                            ↑
        ┌───────────────────┼───────────────────┐
        ↑                   ↑                   ↑
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  ApiStack    │    │DataStack     │    │SearchStack   │
│ (API Gateway)│    │(S3, DDB, KMS)│    │(OpenSearch,  │
│ (4 Lambdas)  │    │(9 Tables)    │    │ Bedrock KB)  │
└──────────────┘    └──────────────┘    └──────────────┘
        ↑                   ↑                   ↑
        └───────────────────┼───────────────────┘
                            ↑
        ┌───────────────────┴───────────────────┐
        ↑                                       ↑
┌──────────────────┐              ┌──────────────────┐
│ IngestionStack   │              │  NetworkStack    │
│(Lambda Pipeline) │              │(VPC, KMS, SGs)   │
│(Step Functions)  │              │(VPC Endpoints)   │
│(AppFlow CDC)     │              │(2 AZs)           │
└──────────────────┘              └──────────────────┘
```

## Stack Dependencies (Deployment Order)

1. **NetworkStack** (First - Foundation)
2. **DataStack** (Requires: NetworkStack)
3. **SearchStack** (Requires: DataStack)
4. **IngestionStack** (Requires: DataStack + SearchStack)
5. **ApiStack** (Requires: NetworkStack + DataStack + SearchStack + IngestionStack)
6. **MonitoringStack** (Requires: ApiStack + DataStack + SearchStack)

## Resource Summary

| Stack | Type | Key Resources |
|-------|------|---------------|
| NetworkStack | Networking | VPC (2 AZs), 5 VPC Endpoints, KMS Key, 1 Security Group |
| DataStack | Storage | 4 S3 buckets, 9 DynamoDB tables, KMS encryption |
| SearchStack | Search | OpenSearch Serverless, Bedrock KB, 2 IAM roles |
| IngestionStack | Pipeline | 7+ Lambda functions, Step Functions, AppFlow, SQS DLQ |
| ApiStack | API | API Gateway, 4 Lambda functions, 2 API Keys, NLB |
| MonitoringStack | Monitoring | 4 CloudWatch dashboards, 2 SNS topics, Alarms |

## Key Metrics

- **Total Lambdas**: 15+ (Ingest, Validate, Transform, Chunk, Enrich, Embed, Sync, Graph Builder, Schema Discovery, Authz, Retrieve, Answer, Action, Index Creator, CDC Processor)
- **DynamoDB Tables**: 9 (Telemetry, Sessions, AuthZ Cache, Rate Limits, Action Metadata, Graph Nodes, Graph Edges, Path Cache, Schema Cache)
- **S3 Buckets**: 4 (Data, Embeddings, Logs, CDC)
- **VPC Endpoints**: 5 (S3, DynamoDB, Bedrock Runtime, Bedrock Agent, OpenSearch)
- **IAM Roles**: 8+ (1 per Lambda type + service roles)

## Current Environment Variables

```bash
# Required for deployment
export CDK_DEFAULT_ACCOUNT="123456789012"
export CDK_DEFAULT_REGION="us-east-1"
export ENVIRONMENT="dev"  # or "prod", "staging"

# Optional Lambda environment
export SALESFORCE_API_ENDPOINT="https://..."
export BEDROCK_GUARDRAIL_ID="..."
export CRITICAL_ALARM_EMAIL="..."
export WARNING_ALARM_EMAIL="..."
```

## Naming Patterns

- **Stacks**: `SalesforceAISearch-{Component}-{env}`
- **S3**: `salesforce-ai-search-{purpose}-{account}-{region}`
- **DynamoDB**: `salesforce-ai-search-{table-type}`
- **Lambda**: `salesforce-ai-search-{function}`
- **KMS Key**: `salesforce-ai-search-poc` (alias)
- **OpenSearch**: `salesforce-ai-search` (collection)

## Tags Applied

All stacks and resources receive:
```
Project: SalesforceAISearch
Environment: dev/prod/staging
Component: Network/Data/Search/Ingestion/API/Monitoring
ManagedBy: CDK
```

## Critical Security Findings

### MUST FIX IMMEDIATELY:
1. Hardcoded API Key in Answer Lambda (line 309 api-stack.ts)
2. API Gateway is REGIONAL not PRIVATE (security workaround noted in code)
3. Bedrock KB resource ARN wildcard: `knowledge-base/*`
4. OpenSearch collection ARN wildcard: `collection/*`

### SHOULD FIX:
1. CORS allows `*` on Answer Lambda Function URL
2. API Gateway policy allows `AnyPrincipal`
3. Hardcoded model ARN for us-west-2 in Answer Lambda

## Construct Usage Summary

| Construct Type | Count | Distribution |
|---|---|---|
| L1 (Cfn*) | 8 | OpenSearch, Bedrock, AppFlow, VPC Endpoints |
| L2 (AWS) | 25+ | VPC, SecurityGroup, Lambda, Bucket, Table, etc. |
| L3 (Custom) | 1 | CloudWatchInsightsQueries |

## Tagging Gaps

Missing important tag categories:
- Cost allocation (Owner, Team, CostCenter)
- Compliance (DataClassification, Compliance, BackupRequired)
- Operational (Runbook, AlertingGroup, SLA)
- Lifecycle (Retention, DeprecationDate)

## Environment Configuration

### Current State:
- `ENVIRONMENT` variable controls stack names
- All resources use identical configs regardless of environment
- No conditional logic for dev/prod differences

### What's NOT Environment-Specific:
- Lambda memory allocation
- Lambda timeout
- DynamoDB billing mode (all on-demand)
- OpenSearch size (all 1 OCU minimal)
- NAT Gateways (all 1)
- API rate limits (same for all)

## Best Practices Missing

1. **CDK Aspects** - No cross-cutting policies
2. **Configuration Management** - Hardcoded or env vars only
3. **Custom Constructs** - Only 1 L3 construct
4. **Testing** - No CDK assertions
5. **CDK Pipelines** - No automated deployment
6. **Context Values** - Not using cdk.json context
7. **SSM Parameter Store** - Not used for configuration
8. **Stack Sets** - No multi-region support
9. **Nested Stacks** - All top-level

## Deployment Commands

```bash
# View synthesis
npm run cdk synth

# Deploy all stacks
npm run deploy

# Deploy specific stack
npx cdk deploy SalesforceAISearch-Network-dev

# List all stacks
npx cdk list

# Show resource changes
npx cdk diff

# View outputs
npx cdk deploy --outputs-file outputs.json
```

## CloudFormation Exports

Each stack exports key outputs for cross-stack reference:
- VPC ID, Subnet IDs
- KMS Key ID and ARN
- S3 Bucket names
- DynamoDB Table names
- API endpoints and IDs
- Lambda function ARNs

## Recommended Actions (Priority)

### CRITICAL (Week 1):
1. [ ] Move API key to Secrets Manager
2. [ ] Implement true private API Gateway
3. [ ] Scope Bedrock/OpenSearch ARNs precisely

### HIGH (Sprint 1):
1. [ ] Add environment-specific configurations
2. [ ] Enhance tagging strategy
3. [ ] Restrict CORS origins
4. [ ] Create custom L3 constructs

### MEDIUM (Sprint 2):
1. [ ] Implement CDK Aspects
2. [ ] Move config to cdk.json
3. [ ] Add CDK assertion tests
4. [ ] Create CDK Pipelines

### LOW (Future):
1. [ ] Multi-region deployment
2. [ ] Version tracking in names
3. [ ] Complete custom construct library

## File Locations (Relative to Project Root)

- **App Entry**: `bin/app.ts`
- **Stacks**: `lib/*.ts` (6 files)
- **Config**: `cdk.json`
- **Lambda Code**: `lambda/*/` (15+ directories)
- **Build Output**: `dist/` and `cdk.out/`

## Key Learnings

✓ **Strengths**:
- Well-organized stack hierarchy
- Type-safe cross-stack references
- Good use of L2 constructs
- Comprehensive monitoring
- Multi-phase feature planning (Phase 1, 2, 3)

✗ **Gaps**:
- Hardcoded sensitive values
- Public API when private intended
- Overbroad IAM permissions
- No environment differentiation
- Limited custom abstractions

## Contact & Support

See code comments for:
- CRITICAL notes on OpenSearch setup
- VPC Endpoint workarounds
- Known issues with provisioned concurrency
- Docker Lambda build requirements

---
*Analysis Date: 2025-11-30*
*CDK Version: 2.110.0*
*Node Runtime: 20.x, Python 3.11*
