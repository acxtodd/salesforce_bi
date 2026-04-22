import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { IngestionStack } from '../lib/ingestion-stack';

/**
 * CDK synthesis assertions for the IngestionStack AppFlow resources.
 *
 * Covers the exact defect fixed in this PR: AppFlow flows defaulting to Draft
 * instead of Active when Salesforce credentials are provided.
 */

function buildStack(props?: { withSalesforceCreds?: boolean }) {
  const app = new cdk.App();

  // Prerequisite resources in a support stack
  const supportStack = new cdk.Stack(app, 'SupportStack', {
    env: { account: '123456789012', region: 'us-west-2' },
  });
  const vpc = new ec2.Vpc(supportStack, 'Vpc');
  const sg = new ec2.SecurityGroup(supportStack, 'SG', { vpc });
  const key = new kms.Key(supportStack, 'Key');
  const bucket = new s3.Bucket(supportStack, 'Bucket');

  const ingestionProps: Record<string, unknown> = {
    env: { account: '123456789012', region: 'us-west-2' },
    vpc,
    lambdaSecurityGroup: sg,
    kmsKey: key,
    dataBucket: bucket,
  };

  if (props?.withSalesforceCreds) {
    ingestionProps.salesforceInstanceUrl = 'https://example.my.salesforce.com';
    ingestionProps.salesforceConnectedAppClientId = 'test-client-id';
    ingestionProps.salesforceConnectedAppClientSecretArn =
      'arn:aws:secretsmanager:us-west-2:123456789012:secret:test-secret-abc123';
    ingestionProps.salesforceJwtToken = 'test-jwt-token';
  }

  const stack = new IngestionStack(
    app,
    'TestIngestionStack',
    ingestionProps as any,
  );

  return Template.fromStack(stack);
}

describe('IngestionStack AppFlow resources', () => {
  let template: Template;

  beforeAll(() => {
    template = buildStack({ withSalesforceCreds: true });
  });

  test('creates AppFlow flows with FlowStatus Active (not Draft)', () => {
    template.allResourcesProperties('AWS::AppFlow::Flow', {
      FlowStatus: 'Active',
    });
  });

  test('creates exactly 5 AppFlow CDC flows', () => {
    template.resourceCountIs('AWS::AppFlow::Flow', 5);
  });

  test('creates an AppFlow ConnectorProfile', () => {
    template.resourceCountIs('AWS::AppFlow::ConnectorProfile', 1);
  });
});

describe('IngestionStack without Salesforce credentials', () => {
  let template: Template;

  beforeAll(() => {
    template = buildStack({ withSalesforceCreds: false });
  });

  test('does not create AppFlow flows when credentials are absent', () => {
    template.resourceCountIs('AWS::AppFlow::Flow', 0);
  });

  test('does not create AppFlow ConnectorProfile when credentials are absent', () => {
    template.resourceCountIs('AWS::AppFlow::ConnectorProfile', 0);
  });
});

describe('IngestionStack AppFlow health check (Task 4.29)', () => {
  let template: Template;

  beforeAll(() => {
    template = buildStack({ withSalesforceCreds: true });
  });

  test('creates the health check Lambda with the expected function name', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      FunctionName: 'salesforce-ai-search-appflow-health-check',
      Runtime: 'python3.11',
      Handler: 'index.lambda_handler',
    });
  });

  test('creates a 5-minute EventBridge schedule rule for the health check', () => {
    template.hasResourceProperties('AWS::Events::Rule', {
      Name: 'salesforce-ai-search-appflow-health-check-schedule',
      ScheduleExpression: 'rate(5 minutes)',
    });
  });

  test('health check role grants appflow:ListFlows', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Effect: 'Allow',
            Action: 'appflow:ListFlows',
            Resource: '*',
          }),
        ]),
      },
    });
  });

  test('health check role scopes PutMetricData to SalesforceAISearch/Ingestion namespace', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Effect: 'Allow',
            Action: 'cloudwatch:PutMetricData',
            Condition: {
              StringEquals: {
                'cloudwatch:namespace': 'SalesforceAISearch/Ingestion',
              },
            },
          }),
        ]),
      },
    });
  });
});
