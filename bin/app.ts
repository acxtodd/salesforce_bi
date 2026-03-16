#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { NetworkStack } from '../lib/network-stack';
import { DataStack } from '../lib/data-stack';
import { SearchStack } from '../lib/search-stack';
import { IngestionStack } from '../lib/ingestion-stack';
import { ApiStack } from '../lib/api-stack';
import { MonitoringStack } from '../lib/monitoring-stack';

const app = new cdk.App();

// Environment configuration
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

// Stack naming
const stackPrefix = 'SalesforceAISearch';
const environment = process.env.ENVIRONMENT || 'dev';

// Network Stack - VPC, Security Groups, VPC Endpoints
const networkStack = new NetworkStack(app, `${stackPrefix}-Network-${environment}`, {
  env,
  description: 'Network infrastructure for Salesforce AI Search POC',
  tags: {
    Project: 'SalesforceAISearch',
    Environment: environment,
    ManagedBy: 'CDK',
  },
});

// Data Stack - S3, DynamoDB, KMS
const dataStack = new DataStack(app, `${stackPrefix}-Data-${environment}`, {
  env,
  description: 'Data layer infrastructure for Salesforce AI Search POC',
  vpc: networkStack.vpc,
  kmsKey: networkStack.kmsKey,
  tags: {
    Project: 'SalesforceAISearch',
    Environment: environment,
    ManagedBy: 'CDK',
  },
});

dataStack.addDependency(networkStack);

// Search Stack - OpenSearch, Bedrock Knowledge Base
const searchStack = new SearchStack(app, `${stackPrefix}-Search-${environment}`, {
  env,
  description: 'Search infrastructure with OpenSearch and Bedrock Knowledge Base',
  vpc: networkStack.vpc,
  lambdaSecurityGroup: networkStack.lambdaSecurityGroup,
  kmsKey: networkStack.kmsKey,
  dataBucket: dataStack.dataBucket,
  opensearchVpcEndpointId: networkStack.opensearchVpcEndpointId,
  tags: {
    Project: 'SalesforceAISearch',
    Environment: environment,
    ManagedBy: 'CDK',
  },
});

searchStack.addDependency(dataStack);

// Resolve Salesforce credentials from existing AWS config for AppFlow
const salesforceInstanceUrl = ssm.StringParameter.valueFromLookup(
  dataStack, '/salesforce/instance_url'
);
const salesforceSecret = secretsmanager.Secret.fromSecretNameV2(
  dataStack, 'SalesforceConnectedAppSecret',
  'salesforce-ai-search/salesforce-connected-app'
);

// Ingestion Stack - Lambda functions, Step Functions, DLQ
const ingestionStack = new IngestionStack(app, `${stackPrefix}-Ingestion-${environment}`, {
  env,
  description: 'Data ingestion pipeline for Salesforce AI Search POC',
  vpc: networkStack.vpc,
  lambdaSecurityGroup: networkStack.lambdaSecurityGroup,
  kmsKey: networkStack.kmsKey,
  dataBucket: dataStack.dataBucket,
  knowledgeBaseId: searchStack.knowledgeBase.attrKnowledgeBaseId,
  dataSourceId: searchStack.dataSource.attrDataSourceId,
  // AppFlow Salesforce CDC credentials
  salesforceInstanceUrl,
  salesforceConnectedAppClientId: 'appflow-gate',  // truthiness gate only
  salesforceConnectedAppClientSecretArn: salesforceSecret.secretArn,
  // Phase 3: Graph Enhancement tables
  graphNodesTable: dataStack.graphNodesTable,
  graphEdgesTable: dataStack.graphEdgesTable,
  // Zero-Config Schema Discovery table
  schemaCacheTable: dataStack.schemaCacheTable,
  tags: {
    Project: 'SalesforceAISearch',
    Environment: environment,
    ManagedBy: 'CDK',
  },
});

ingestionStack.addDependency(dataStack);
ingestionStack.addDependency(searchStack);

// API Stack - Private API Gateway, Lambda functions for /retrieve and /answer
const apiStack = new ApiStack(app, `${stackPrefix}-Api-${environment}`, {
  env,
  description: 'Private API Gateway and Lambda functions for Salesforce AI Search POC',
  vpc: networkStack.vpc,
  lambdaSecurityGroup: networkStack.lambdaSecurityGroup,
  kmsKey: networkStack.kmsKey,
  telemetryTable: dataStack.telemetryTable,
  sessionsTable: dataStack.sessionsTable,
  authzCacheTable: dataStack.authzCacheTable,
  rateLimitsTable: dataStack.rateLimitsTable,
  actionMetadataTable: dataStack.actionMetadataTable,
  knowledgeBaseId: searchStack.knowledgeBase.attrKnowledgeBaseId,
  ingestLambda: ingestionStack.ingestLambda,
  // Phase 3: Graph Enhancement tables
  graphNodesTable: dataStack.graphNodesTable,
  graphEdgesTable: dataStack.graphEdgesTable,
  graphPathCacheTable: dataStack.graphPathCacheTable,
  dataBucket: dataStack.dataBucket,
  // Zero-Config Schema Discovery table
  schemaCacheTable: dataStack.schemaCacheTable,
  tags: {
    Project: 'SalesforceAISearch',
    Environment: environment,
    ManagedBy: 'CDK',
  },
});

apiStack.addDependency(networkStack);
apiStack.addDependency(dataStack);
apiStack.addDependency(searchStack);
apiStack.addDependency(ingestionStack);

// Monitoring Stack - CloudWatch dashboards, alarms, SNS topics
const monitoringStack = new MonitoringStack(app, `${stackPrefix}-Monitoring-${environment}`, {
  env,
  description: 'Monitoring infrastructure with CloudWatch dashboards and alarms',
  api: apiStack.api,
  retrieveLambda: apiStack.retrieveLambda,
  answerLambda: apiStack.answerLambda,
  authzLambda: apiStack.authzLambda,
  actionLambda: apiStack.actionLambda,
  collection: searchStack.collection,
  telemetryTable: dataStack.telemetryTable,
  sessionsTable: dataStack.sessionsTable,
  authzCacheTable: dataStack.authzCacheTable,
  rateLimitsTable: dataStack.rateLimitsTable,
  tags: {
    Project: 'SalesforceAISearch',
    Environment: environment,
    ManagedBy: 'CDK',
  },
});

monitoringStack.addDependency(apiStack);
monitoringStack.addDependency(dataStack);
monitoringStack.addDependency(searchStack);

app.synth();
