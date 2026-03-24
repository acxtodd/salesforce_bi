#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { NetworkStack } from '../lib/network-stack';
import { DataStack } from '../lib/data-stack';
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

// AppFlow ConnectorProfile Early Validation rejects SSM dynamic references and
// partial secret ARNs. All three values must be passed as CDK context at deploy
// time so they are literal in the synthesized template:
//
//   npx cdk deploy SalesforceAISearch-Ingestion-dev --method=direct \
//     -c salesforceInstanceUrl="$(aws ssm get-parameter --name /salesforce/instance_url --region us-west-2 --query Parameter.Value --output text)" \
//     -c salesforceSecretArn="$(aws secretsmanager describe-secret --secret-id salesforce-ai-search/appflow-creds --region us-west-2 --query ARN --output text)" \
//     -c salesforceJwtToken="$(python3 scripts/mint_jwt.py)"
const salesforceInstanceUrl = app.node.tryGetContext('salesforceInstanceUrl') || '';
const salesforceSecretArn = app.node.tryGetContext('salesforceSecretArn') || '';
const salesforceJwtToken = app.node.tryGetContext('salesforceJwtToken') || '';

// Fail fast: if any AppFlow context value is provided, all three are required.
const appflowContextValues = [salesforceInstanceUrl, salesforceSecretArn, salesforceJwtToken];
const appflowContextProvided = appflowContextValues.filter(Boolean).length;
if (appflowContextProvided > 0 && appflowContextProvided < 3) {
  throw new Error(
    'Partial AppFlow context: all three of salesforceInstanceUrl, salesforceSecretArn, ' +
    'and salesforceJwtToken must be provided via -c flags. See deploy recipe above.',
  );
}

const salesforceSecret = salesforceSecretArn
  ? secretsmanager.Secret.fromSecretCompleteArn(
      dataStack, 'SalesforceConnectedAppSecret', salesforceSecretArn,
    )
  : undefined;

// Ingestion Stack - Lambda functions, DLQ, AppFlow CDC
const ingestionStack = new IngestionStack(app, `${stackPrefix}-Ingestion-${environment}`, {
  env,
  description: 'Data ingestion pipeline for Salesforce AI Search POC',
  vpc: networkStack.vpc,
  lambdaSecurityGroup: networkStack.lambdaSecurityGroup,
  kmsKey: networkStack.kmsKey,
  dataBucket: dataStack.dataBucket,
  // AppFlow Salesforce CDC credentials (JWT_BEARER flow)
  salesforceInstanceUrl,
  salesforceConnectedAppClientId: salesforceSecretArn ? 'appflow-gate' : undefined,  // truthiness gate only
  salesforceConnectedAppClientSecretArn: salesforceSecret?.secretArn,
  salesforceJwtToken,
  // Zero-Config Schema Discovery table
  schemaCacheTable: dataStack.schemaCacheTable,
  // Audit trail bucket
  auditBucket: dataStack.auditBucket,
  tags: {
    Project: 'SalesforceAISearch',
    Environment: environment,
    ManagedBy: 'CDK',
  },
});

ingestionStack.addDependency(dataStack);

// API Stack - API Gateway, Lambda functions for /query, /schema, /ingest, /action
const apiStack = new ApiStack(app, `${stackPrefix}-Api-${environment}`, {
  env,
  description: 'API Gateway and Lambda functions for Salesforce AI Search',
  vpc: networkStack.vpc,
  lambdaSecurityGroup: networkStack.lambdaSecurityGroup,
  kmsKey: networkStack.kmsKey,
  authzCacheTable: dataStack.authzCacheTable,
  rateLimitsTable: dataStack.rateLimitsTable,
  actionMetadataTable: dataStack.actionMetadataTable,
  ingestLambda: ingestionStack.ingestLambda,
  // Zero-Config Schema Discovery table
  schemaCacheTable: dataStack.schemaCacheTable,
  configArtifactBucket: dataStack.dataBucket,
  tags: {
    Project: 'SalesforceAISearch',
    Environment: environment,
    ManagedBy: 'CDK',
  },
});

apiStack.addDependency(networkStack);
apiStack.addDependency(dataStack);
apiStack.addDependency(ingestionStack);

// Monitoring Stack - CloudWatch dashboards, alarms, SNS topics
const monitoringStack = new MonitoringStack(app, `${stackPrefix}-Monitoring-${environment}`, {
  env,
  description: 'Monitoring infrastructure with CloudWatch dashboards and alarms',
  api: apiStack.api,
  authzLambda: apiStack.authzLambda,
  actionLambda: apiStack.actionLambda,
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

app.synth();
