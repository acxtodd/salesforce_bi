# CDK Infrastructure Code Analysis

## Executive Summary
This is a sophisticated AWS CDK project for Salesforce AI Search POC with 6 well-organized stacks, demonstrating mature infrastructure-as-code patterns with security considerations and multi-phase feature rollout.

---

## 1. STACK ORGANIZATION & ARCHITECTURE

### Stack Hierarchy (Layered Approach)
The infrastructure uses a **layered, dependency-based stack organization**:

```
NetworkStack (Foundation)
    ↓
DataStack + SearchStack (Storage & Indexing)
    ↓
IngestionStack (Data Pipeline)
    ↓
ApiStack (Business Logic)
    ↓
MonitoringStack (Observability)
```

### 6 Stacks Identified:

1. **NetworkStack** - Foundation layer
   - VPC with public/private subnets (2 AZs for HA)
   - KMS key for encryption at rest across all services
   - VPC Endpoints (S3, DynamoDB, Bedrock, OpenSearch)
   - Security Groups for Lambda functions

2. **DataStack** - Data persistence layer
   - S3 buckets (data, embeddings, logs)
   - 9 DynamoDB tables for different purposes:
     - Telemetry, Sessions, AuthZ Cache, Rate Limits, Action Metadata
     - Graph Nodes, Graph Edges, Path Cache (Phase 3)
     - Schema Cache (Zero-Config Discovery)

3. **SearchStack** - Vector search layer
   - OpenSearch Serverless with Vector collections
   - Bedrock Knowledge Base integration
   - IAM roles for cross-service access

4. **IngestionStack** - ETL/data processing pipeline
   - Lambda functions (CDC Processor, Ingest, Validate, Transform, etc.)
   - Step Functions state machine
   - AppFlow for Salesforce CDC
   - SQS Dead Letter Queue

5. **ApiStack** - REST API layer
   - API Gateway (Regional endpoint with CORS)
   - 4 Lambda functions (AuthZ, Retrieve, Answer, Action)
   - Function URLs for streaming (Answer Lambda)
   - VPC endpoints and private link setup

6. **MonitoringStack** - Observability layer
   - CloudWatch dashboards (API Performance, Retrieval Quality, Cost, Graph Operations)
   - SNS topics for alarms (Critical & Warning)
   - Custom CloudWatch insights queries

### Stack Dependency Management
Uses explicit `addDependency()` calls:
```
dataStack.addDependency(networkStack);
searchStack.addDependency(dataStack);
ingestionStack.addDependency(dataStack);
ingestionStack.addDependency(searchStack);
apiStack.addDependency(networkStack);
apiStack.addDependency(dataStack);
apiStack.addDependency(searchStack);
apiStack.addDependency(ingestionStack);
monitoringStack.addDependency(apiStack);
monitoringStack.addDependency(dataStack);
monitoringStack.addDependency(searchStack);
```

---

## 2. RESOURCE NAMING CONVENTIONS

### Pattern Analysis:
- **Stack names**: `{SalesforceAISearch}-{Component}-{environment}` 
  - Example: `SalesforceAISearch-Network-dev`, `SalesforceAISearch-Api-prod`

- **S3 buckets**: `{purpose}-ai-search-{type}-{account}-{region}`
  - `salesforce-ai-search-data-123456789-us-east-1`
  - `salesforce-ai-search-logs-123456789-us-east-1`
  - `salesforce-ai-search-embeddings-123456789-us-east-1`
  - `salesforce-ai-search-cdc-123456789-us-east-1`

- **DynamoDB tables**: `salesforce-ai-search-{purpose}`
  - `salesforce-ai-search-telemetry`
  - `salesforce-ai-search-authz-cache`
  - `salesforce-ai-search-graph-nodes`

- **Lambda functions**: `salesforce-ai-search-{function-type}`
  - `salesforce-ai-search-authz`
  - `salesforce-ai-search-retrieve`
  - `salesforce-ai-search-answer-docker`
  - `salesforce-ai-search-embed`

- **KMS Key**: Uses alias `salesforce-ai-search-poc`

- **OpenSearch Collection**: `salesforce-ai-search`

### Strengths:
✓ Consistent hierarchical naming
✓ Globally unique (includes account + region for resources)
✓ Descriptive purpose in names
✓ Supports multi-environment deployments

### Gaps:
- No version tracking in names (important for Lambda aliases)
- Limited use of descriptive suffixes (e.g., no -v1, -v2)

---

## 3. CROSS-STACK REFERENCES PATTERNS

### Method 1: Direct Object Passing (PREFERRED)
Stack inputs accept resources from other stacks:
```typescript
interface ApiStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  lambdaSecurityGroup: ec2.SecurityGroup;
  kmsKey: kms.Key;
  telemetryTable: dynamodb.Table;
  knowledgeBaseId: string;
  // ... 15 parameters
}
```

### Method 2: CloudFormation Exports
Uses `CfnOutput` with `exportName`:
```typescript
new cdk.CfnOutput(this, "VpcId", {
  value: this.vpc.vpcId,
  exportName: `${this.stackName}-VpcId`,
});
```

### Method 3: Stack Chaining
Sequential creation with explicit dependencies:
```typescript
const networkStack = new NetworkStack(app, ...);
const dataStack = new DataStack(app, ..., { vpc: networkStack.vpc });
dataStack.addDependency(networkStack);
```

### Cross-Stack Reference Examples:
1. **Network → Data**: VPC, KMS key
2. **Data → Search**: S3 bucket, DynamoDB tables
3. **Search → Ingestion**: Knowledge Base ID, Data Source ID
4. **Data → API**: All 9 DynamoDB tables, S3 bucket
5. **All → Monitoring**: Lambda functions, API Gateway, tables

### Strengths:
✓ Strong type safety (object passing over strings)
✓ Clear dependency graph visualization
✓ Circular dependency prevention
✓ CloudFormation exports for cross-account (if needed)

### Potential Improvements:
- No context-based sharing (cdk.json context values)
- Limited use of SSM Parameter Store for dynamic references
- Export names could include stack names for clarity

---

## 4. ENVIRONMENT CONFIGURATION (Dev/Prod Differences)

### Environment Variable Usage:
```typescript
// bin/app.ts
const environment = process.env.ENVIRONMENT || 'dev';
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
};
```

### Current Configuration Gaps:

#### ✗ No explicit dev/prod branching in stacks
- Same resource configurations for all environments
- No conditional logic based on environment

#### Environment-specific settings NOT implemented:
```typescript
// NOT FOUND IN CODE:
if (environment === 'prod') {
  // Larger instance sizes
  // High availability settings
  // Enhanced security
}
```

#### Hardcoded values that should be environment-dependent:
```typescript
// In api-stack.ts line 309
API_KEY: 'M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ', // HARDCODED!

// In search-stack.ts - OpenSearch uses 1 OCU (minimal, POC-only)
// Note: Standby replicas disabled for POC to minimize cost
```

#### Features with environment logic that EXISTS:
1. **VPC**: Configurable NAT Gateways (1 for POC)
2. **DynamoDB**: All use on-demand billing (no provisioned capacity)
3. **Lambda aliases**: Only on Retrieve Lambda, not Answer Lambda
4. **OpenSearch**: Hardcoded to minimal (no standby replicas)

### Environment Variations by Inspection:
| Aspect | Current Implementation |
|--------|------------------------|
| VPC NAT Gateways | Fixed to 1 (POC optimization) |
| DynamoDB Billing | On-demand (no environment logic) |
| Lambda Concurrency | Retrieve: 5 provisioned; Answer: commented out |
| OpenSearch Replicas | Disabled (POC cost optimization) |
| API Endpoint | Regional (noted as workaround for public access) |
| Log Retention | 3 months (same for all) |
| API Rate Limits | User: 100/1s, 10k/day; Service: 50/1s, 50k/day |

### Missing Environment-Specific Configs:
- [ ] Database instance types/sizes
- [ ] Lambda memory allocation
- [ ] Lambda timeout durations
- [ ] HA/failover settings
- [ ] Backup retention policies
- [ ] Encryption key rotation frequency
- [ ] CloudWatch alarm thresholds

---

## 5. IAM PERMISSION PATTERNS

### Pattern 1: Least Privilege with Grant Methods (L2 Constructs)
```typescript
// Data table grants - PREFERRED pattern
authzCacheTable.grantReadWriteData(authzRole);
graphNodesTable.grantReadData(retrieveRole);
dataBucket.grantRead(retrieveRole);
kmsKey.grantEncryptDecrypt(authzRole);
```

### Pattern 2: Service Principal Assumption
```typescript
const authzRole = new iam.Role(this, id, {
  assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
  managedPolicies: [
    iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaVPCAccessExecutionRole'),
  ],
});
```

### Pattern 3: Explicit Policy Statements for Wildcard Resources
```typescript
// When service requires it (Marketplace)
role.addToPolicy(new iam.PolicyStatement({
  effect: iam.Effect.ALLOW,
  actions: [
    'bedrock:InvokeModel',
    'bedrock:Retrieve',
    'aws-marketplace:ViewSubscriptions',
  ],
  resources: ['*'], // Required for marketplace
}));
```

### Pattern 4: Resource-Scoped Policies
```typescript
// Good example - ARN scoped to specific parameter path
role.addToPolicy(new iam.PolicyStatement({
  effect: iam.Effect.ALLOW,
  actions: ['ssm:GetParameter'],
  resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/salesforce/*`],
}));
```

### Pattern 5: Namespace-Scoped CloudWatch Metrics
```typescript
role.addToPolicy(new iam.PolicyStatement({
  effect: iam.Effect.ALLOW,
  actions: ['cloudwatch:PutMetricData'],
  resources: ['*'],
  conditions: {
    StringEquals: {
      'cloudwatch:namespace': ['SalesforceAISearch/AuthZ', 'SalesforceAISearch/Retrieve'],
    },
  },
}));
```

### IAM Role Summary:

| Role | Permissions | Pattern | Scope |
|------|-----------|---------|-------|
| NetworkStack | KMS, VPC, EC2 | L2 Grants | Component-specific |
| DataStack | N/A (storage) | N/A | N/A |
| SearchStack | Bedrock, AOSS, S3 | Mixed (L1+L2) | Knowledge Base read/write |
| IngestionStack | DynamoDB, S3, KMS, Secrets | L2 Grants | Per-Lambda roles |
| ApiStack | DynamoDB, S3, Bedrock, Secrets | L2 Grants | Per-Lambda roles |
| MonitoringStack | CloudWatch, SNS | L2 Grants | Read-only metrics |

### Least Privilege Assessment:

#### ✓ Good Practices:
- DynamoDB table grants use specific operations (grantReadData, grantReadWriteData)
- S3 bucket grants use specific operations (grantRead, grantReadWrite)
- KMS grants are granular (grantEncryptDecrypt)
- SSM parameters are ARN-scoped to `/salesforce/*`
- Bedrock model access is scoped to specific foundation models
- OpenSearch (AOSS) uses both control-plane (APIAccessAll) and data-plane actions

#### ✗ Areas for Improvement:
1. **Bedrock permissions too broad**:
   ```typescript
   resources: [
     `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
     `arn:aws:bedrock:${this.region}:${this.account}:knowledge-base/*`,
   ],
   ```
   Should be: `arn:aws:bedrock:${this.region}:${this.account}:knowledge-base/${knowledgeBaseId}`

2. **OpenSearch IndexCreator role lacks granularity**:
   ```typescript
   resources: [`arn:aws:aoss:${this.region}:${this.account}:collection/*`],
   ```
   Should reference specific collection ARN

3. **Hardcoded API Key in Lambda environment**:
   ```typescript
   API_KEY: 'M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ', // SECURITY RISK!
   ```
   Should use Secrets Manager

4. **CORS wildcard on Answer Lambda Function URL**:
   ```typescript
   cors: {
     allowedOrigins: ['*'],
     allowedMethods: [lambda.HttpMethod.POST],
     allowedHeaders: ['*'],
   },
   ```

5. **API Gateway policy allows any principal**:
   ```typescript
   policy: new iam.PolicyDocument({
     statements: [
       new iam.PolicyStatement({
         effect: iam.Effect.ALLOW,
         principals: [new iam.AnyPrincipal()],
         actions: ['execute-api:Invoke'],
         resources: ['execute-api:/*'],
         // REMOVED CONDITION FOR VPC ENDPOINT RESTRICTION (comment in code!)
       }),
     ],
   }),
   ```
   This is PUBLIC API, not private as intended!

---

## 6. TAGGING STRATEGIES

### Tags Applied at Stack Level
```typescript
// Applied to ALL stacks
tags: {
  Project: 'SalesforceAISearch',
  Environment: environment,  // dev/prod from process.env
  ManagedBy: 'CDK',
}
```

### Component-Level Tags
```typescript
// Added via Tags.of()
cdk.Tags.of(this).add('Component', 'Network');    // NetworkStack
cdk.Tags.of(this).add('Component', 'Data');       // DataStack
cdk.Tags.of(this).add('Component', 'Search');     // SearchStack
cdk.Tags.of(this).add('Component', 'Ingestion');  // IngestionStack
cdk.Tags.of(this).add('Component', 'API');        // ApiStack
cdk.Tags.of(this).add('Component', 'Monitoring'); // MonitoringStack
```

### Tag Application Scope
- **Stack-level tags**: Applied to all resources in stack
- **Component tags**: Applied to all resources in stack
- **No resource-level tags**: Individual resources don't override parent tags

### Tags Found:
```
Project: SalesforceAISearch
Environment: dev/prod/staging
Component: Network/Data/Search/Ingestion/API/Monitoring
ManagedBy: CDK
```

### Tagging Assessment:

#### ✓ Strengths:
- Consistent project naming
- Environment tracking
- Component organization
- CDK-managed indicator

#### ✗ Gaps:
- **Missing**: Cost allocation tags (CostCenter, Owner, Team)
- **Missing**: Lifecycle tags (Retention, Backup)
- **Missing**: Security tags (DataClassification, Compliance)
- **Missing**: Operational tags (Runbook, AlertingGroup, SLA)
- **Missing**: Business tags (Application, Version)

### Recommended Enhanced Tagging:
```typescript
tags: {
  // Organizational
  Project: 'SalesforceAISearch',
  Environment: environment,
  Component: 'Network', // should vary by stack
  
  // Ownership & Support
  Owner: process.env.OWNER_EMAIL || 'unknown',
  Team: 'Platform/DataEngineering',
  CostCenter: 'CC-12345',
  
  // Data & Compliance
  DataClassification: 'Confidential', // or 'Public'
  Compliance: 'SOC2',
  BackupRequired: 'true',
  BackupRetention: '30days',
  
  // Operational
  AlertingGroup: 'salesforce-ai-search-team',
  Runbook: 'https://wiki.company.com/runbooks/salesforce-ai-search',
  SLA: '99.5%',
  
  // Lifecycle
  Deprecated: 'false',
  DeprecationDate: '', // YYYY-MM-DD
  ManagedBy: 'CDK',
  LastReview: '2025-11-30',
},
```

---

## 7. CONSTRUCT PATTERNS (L1 vs L2 vs L3)

### L1 (CloudFormation) Constructs Used:
```typescript
// Cfn* constructs (low-level, directly map to CloudFormation)
opensearchserverless.CfnCollection()
bedrock.CfnKnowledgeBase()
bedrock.CfnDataSource()
appflow.CfnConnectorProfile()
appflow.CfnFlow()
opensearchserverless.CfnVpcEndpoint()
opensearchserverless.CfnSecurityPolicy()
opensearchserverless.CfnAccessPolicy()
```

### L2 (Higher-level, intent-based) Constructs Used:
```typescript
// Core infrastructure
ec2.Vpc()                    // VPC with defaults
ec2.SecurityGroup()          // Security group with helper methods
ec2.InterfaceVpcEndpoint()   // VPC endpoint abstraction

// Storage
s3.Bucket()                  // S3 with encryption, versioning helpers
dynamodb.Table()             // DynamoDB with billing mode, encryption
kms.Key()                    // KMS key with rotation helpers

// Compute
lambda.Function()            // Lambda with asset handling, role creation
lambda.DockerImageFunction() // Docker image-based Lambda

// API
apigateway.RestApi()         // REST API with deployment helpers
apigateway.LambdaIntegration() // Lambda integration
apigateway.RequestValidator() // Request validation

// Monitoring
cloudwatch.Dashboard()       // CloudWatch dashboard
cloudwatch.Metric()          // Metric definition
sns.Topic()                  // SNS topic
```

### L3 (Custom, pattern-based) Constructs:
```typescript
// Custom helper class
export class CloudWatchInsightsQueries extends Construct {
  // Encapsulates CloudWatch Insights query logic
}
```

### Construct Usage Summary:

| Layer | Count | Examples | Use Case |
|-------|-------|----------|----------|
| L1    | 8     | CfnCollection, CfnKnowledgeBase | Bedrock, OpenSearch (limited CDK support) |
| L2    | 25+   | Vpc, SecurityGroup, Lambda, Bucket | Core infrastructure, good default behavior |
| L3    | 1     | CloudWatchInsightsQueries | Custom patterns for team reuse |

### Pattern Analysis:

#### ✓ Good: Mostly L2 for maintainability
Most infrastructure uses L2 constructs that provide:
- Default security configurations
- Helper methods (grant*, add*)
- Automatic CloudWatch logging

#### ✓ Good: L1 used appropriately
L1 constructs (CfnCollection, CfnKnowledgeBase) used where L2 support is limited:
- OpenSearch Serverless (early feature)
- Bedrock Knowledge Base (new service)

#### ✗ Concern: Limited L3 abstraction
Only 1 custom L3 construct (CloudWatchInsightsQueries). Could benefit from:
```typescript
// Potential L3 constructs for code reuse:
class SalesforceAISearchLambda extends lambda.Function {
  // Automatic role setup
  // Standard environment variables
  // VPC networking
  // Security group configuration
}

class SalesforceAISearchTable extends dynamodb.Table {
  // Standard encryption
  // Standard TTL
  // Standard backup
}

class SalesforceAISearchBucket extends s3.Bucket {
  // Standard encryption
  // Standard logging
  // Standard lifecycle
}
```

### Construct Evolution Across Stacks:
- **NetworkStack**: L2 for VPC/Security, L1 for VPC Endpoints (custom service names)
- **DataStack**: L2 for all resources (mature constructs)
- **SearchStack**: Mix of L2 (IAM, Lambda) and L1 (OpenSearch, Bedrock)
- **IngestionStack**: L2 for Lambda/Step Functions, L1 for AppFlow
- **ApiStack**: L2 for API Gateway, Lambda, VPC - well-supported
- **MonitoringStack**: L2 for CloudWatch/SNS/Alarms

---

## SECURITY & ORGANIZATIONAL ASSESSMENT

### Security Findings:

#### 🔴 CRITICAL:
1. **Hardcoded API Key** (api-stack.ts:309)
   ```typescript
   API_KEY: 'M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ',
   ```
   **Action**: Move to Secrets Manager, use `secretsmanager.Secret.fromSecretCompleteArn()`

2. **Public API Gateway** (api-stack.ts:376-387)
   - Endpoint is REGIONAL (not PRIVATE)
   - Comment states: "CHANGED TO REGIONAL FOR PUBLIC ACCESS WORKAROUND"
   - Policy allows AnyPrincipal
   - **Action**: Implement proper private API via VPC Endpoint Service

3. **Overbroad OpenSearch Permissions** (search-stack.ts)
   - Collection wildcard: `collection/*` instead of specific collection ARN
   - **Action**: Scope to `collection/salesforce-ai-search`

#### 🟡 HIGH:
1. **CORS Wildcard on Lambda URL** (api-stack.ts:318)
   - `allowedOrigins: ['*']`
   - Should specify allowed domains

2. **Bedrock Knowledge Base ARN too broad**
   - `knowledge-base/*` instead of specific KB ID

3. **Answer Lambda Docker Image**
   - Hardcoded inference profile ARN (us-west-2)
   - May not work in other regions

#### 🟢 GOOD:
- KMS encryption at rest (all services)
- VPC-only Lambda execution
- Security group egress control
- DynamoDB encryption + PITR enabled
- S3 versioning and lifecycle policies
- CloudWatch logging at scale (INFO level)

### Organizational Improvements:

#### Missing Best Practices:

1. **No Stack Organization Pattern**
   - Could use CDK Aspects for cross-cutting concerns
   - Could implement tagging policies via Aspects

2. **No Configuration Management**
   - Environment configs hardcoded in stack properties
   - Could use Config files or Parameter Store

3. **Limited Resource Naming**
   - No version tracking
   - No regional awareness beyond ${region}

4. **No Infrastructure Versioning**
   - Stacks don't track versions
   - CloudFormation stack names are fixed

5. **Minimal Custom Constructs**
   - Only 1 L3 construct (CloudWatchInsightsQueries)
   - Could abstract common patterns

---

## PATTERNS IN USE (Summary)

### CDK Patterns ✓ IMPLEMENTED:
1. **Stack Dependency Chain** - Explicit addDependency()
2. **Cross-Stack References** - Interface-based object passing
3. **CloudFormation Exports** - Named outputs for sharing
4. **Service Principal Assumption** - Role assumption
5. **Managed Policy Application** - AWS managed policies + custom policies
6. **Least Privilege Grants** - grant* methods for table/bucket access
7. **VPC Networking** - Private subnets, Security Groups, VPC Endpoints
8. **Resource Tagging** - Stack-level and component-level tags
9. **Custom Constructs** - CloudWatchInsightsQueries example
10. **Lambda Aliases** - Version management (Retrieve Lambda only)
11. **Custom Resources** - AWS SDK calls via cr.AwsCustomResource
12. **Environment Variables** - Via Lambda environment property

### CDK Patterns ✗ NOT IMPLEMENTED:
1. **Aspects** - No cross-cutting concerns via Aspects
2. **Context Values** - Not using cdk.json context for configuration
3. **Assertions** - No assertion testing in stacks
4. **Composition Pattern** - Limited use of sub-constructs
5. **Stages/Regions** - No Stage/Region abstraction
6. **Environment-Specific Logic** - No conditional branch by environment
7. **Parameter Store Integration** - No SSM parameters for configuration
8. **Nested Stacks** - All 6 stacks are top-level, no nesting
9. **Stack Sets** - No cross-account deployment
10. **CDK Pipelines** - No automated deployment pipeline in CDK

---

## BEST PRACTICES THAT COULD BE ADOPTED

### 1. Use CDK Aspects for Cross-Cutting Concerns
```typescript
// Example: Enforce encryption on all storage resources
import * as cdk from 'aws-cdk-lib';

class EncryptionAspect implements cdk.IAspect {
  visit(node: cdk.IConstruct) {
    if (node instanceof s3.Bucket) {
      if (node.encryption === undefined) {
        cdk.Annotations.of(node).addWarning('S3 bucket must be encrypted');
      }
    }
  }
}

app.aspects.add(new EncryptionAspect());
```

### 2. Externalize Configuration to cdk.json
```json
{
  "context": {
    "environments": {
      "dev": {
        "lambdaMemory": 512,
        "natGateways": 1,
        "openSearchOcus": 1
      },
      "prod": {
        "lambdaMemory": 2048,
        "natGateways": 2,
        "openSearchOcus": 4
      }
    }
  }
}
```

### 3. Implement Environment-Specific Stack Variants
```typescript
// In bin/app.ts
const config = app.node.tryGetContext('environments')[environment];

const dataStack = new DataStack(app, ..., {
  dynamoDbBillingMode: config.dynamoDbBillingMode,
  retentionDays: config.logRetentionDays,
});
```

### 4. Create Custom Constructs for Reusable Patterns
```typescript
// lib/constructs/salesforce-lambda.ts
export class SalesforceAISearchLambda extends lambda.Function {
  constructor(scope: Construct, id: string, props: SalesforceAISearchLambdaProps) {
    const role = new iam.Role(scope, `${id}Role`, {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaVPCAccessExecutionRole'),
      ],
    });

    super(scope, id, {
      role,
      vpc: props.vpc,
      securityGroups: [props.securityGroup],
      ...props,
    });
  }
}
```

### 5. Use Parameter Store for Secrets
```typescript
// Instead of hardcoding
const apiKey = secretsmanager.Secret.fromSecretCompleteArn(
  this,
  'ApiKey',
  `arn:aws:secretsmanager:${this.region}:${this.account}:secret:salesforce-ai-search/api-key`,
);

lambda.environment = {
  API_KEY_ARN: apiKey.secretArn,
};
```

### 6. Implement Stack Set for Multi-Region/Multi-Account
```typescript
// Deploy to multiple regions
const regions = ['us-east-1', 'us-west-2', 'eu-west-1'];
regions.forEach(region => {
  new SalesforceAISearchStack(app, `SalesforceAISearch-${region}`, {
    env: { account, region },
  });
});
```

### 7. Add CDK Assertions for Testing
```typescript
// tests/stacks.test.ts
import * as assertions from 'aws-cdk-lib/assertions';

test('Data bucket has encryption enabled', () => {
  const template = assertions.Template.fromStack(dataStack);
  
  template.hasResourceProperties('AWS::S3::Bucket', {
    BucketEncryption: {
      ServerSideEncryptionConfiguration: [{
        ServerSideEncryptionByDefault: {
          SSEAlgorithm: 'aws:kms',
        },
      }],
    },
  });
});
```

### 8. Use CDK Pipelines for Automated Deployments
```typescript
// lib/cicd-stack.ts
import { pipelines } from 'aws-cdk-lib';

const pipeline = new pipelines.CodePipeline(this, 'Pipeline', {
  synth: new pipelines.ShellStep('Synth', {
    input: pipelines.CodePipelineSource.connection(...),
    commands: ['npm run build', 'npm run cdk synth'],
  }),
});

pipeline.addStage(new SalesforceAISearchStage(this, 'Dev'));
pipeline.addStage(new SalesforceAISearchStage(this, 'Prod'));
```

### 9. Implement Fine-Grained IAM Policies
```typescript
// Instead of wildcard resources
knowledgeBaseRole.addToPolicy(new iam.PolicyStatement({
  effect: iam.Effect.ALLOW,
  actions: ['bedrock:InvokeModel'],
  resources: [
    `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
  ],
}));

// Instead of knowledge-base/*
knowledgeBaseRole.addToPolicy(new iam.PolicyStatement({
  effect: iam.Effect.ALLOW,
  actions: ['bedrock:Retrieve', 'bedrock:RetrieveAndGenerate'],
  resources: [
    `arn:aws:bedrock:${this.region}:${this.account}:knowledge-base/${knowledgeBaseId}`,
  ],
}));
```

### 10. Enhanced Tagging Policy
```typescript
// Apply comprehensive tagging via Aspect
class TaggingAspect implements cdk.IAspect {
  constructor(private tags: { [key: string]: string }) {}

  visit(node: cdk.IConstruct) {
    if (cdk.Tags.isTaggable(node)) {
      Object.entries(this.tags).forEach(([key, value]) => {
        cdk.Tags.of(node).add(key, value);
      });
    }
  }
}

app.aspects.add(new TaggingAspect({
  CostCenter: 'CC-12345',
  Owner: 'platform-team',
  DataClassification: 'Confidential',
}));
```

---

## SUMMARY TABLE

| Category | Status | Assessment |
|----------|--------|------------|
| **Stack Organization** | ✓ Good | 6 well-organized, dependency-ordered stacks |
| **Naming Conventions** | ✓ Good | Hierarchical, globally unique, descriptive |
| **Cross-Stack References** | ✓ Good | Type-safe object passing + CloudFormation exports |
| **Environment Config** | 🔴 Poor | No dev/prod branching logic, hardcoded values |
| **IAM Permissions** | 🟡 Mixed | Good grant patterns, but overbroad wildcards in places |
| **Tagging Strategy** | 🟡 Basic | Core tags present, missing cost/compliance/ops tags |
| **Construct Patterns** | ✓ Good | Proper L2 usage, L1 where needed, minimal L3 |
| **Security** | 🔴 Critical | Hardcoded secrets, public API endpoint, ovbroad perms |
| **Infrastructure Maturity** | ✓ Advanced | Complex multi-component system, good separation |
| **Best Practices** | 🟡 Partial | Missing Aspects, testing, CDK Pipelines, context |

---

## RECOMMENDATIONS (Priority Order)

### 🔴 CRITICAL (Do Immediately):
1. Move hardcoded API key to Secrets Manager
2. Fix API Gateway to use true private endpoint (not Regional workaround)
3. Scope Bedrock knowledge-base ARN from `*` to specific KB ID
4. Scope OpenSearch collection ARN from `*` to specific collection

### 🟠 HIGH (Next Sprint):
1. Implement environment-specific configurations (dev vs prod)
2. Add comprehensive tagging (cost, compliance, operational)
3. Restrict CORS to specific domains
4. Create custom L3 constructs for code reuse

### 🟡 MEDIUM (Future Sprints):
1. Add CDK Aspects for cross-cutting concerns
2. Move configuration to cdk.json context
3. Implement automated testing (assertions)
4. Create CDK Pipelines for deployment automation

### 🟢 LOW (Nice-to-Have):
1. Add Stack Set support for multi-region
2. Implement version tracking in resource names
3. Create team runbooks and documentation
4. Add more custom L3 constructs
