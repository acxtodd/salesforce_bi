import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as kms from "aws-cdk-lib/aws-kms";
import * as appflow from "aws-cdk-lib/aws-appflow";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Construct } from "constructs";
import * as path from "path";

interface IngestionStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  lambdaSecurityGroup: ec2.SecurityGroup;
  kmsKey: kms.Key;
  dataBucket: s3.Bucket;
  salesforceInstanceUrl?: string;
  salesforceConnectedAppClientId?: string;
  salesforceConnectedAppClientSecretArn?: string;
  salesforceJwtToken?: string;
  // Zero-Config Schema Discovery table
  schemaCacheTable?: dynamodb.Table;
  // Audit trail bucket
  auditBucket?: s3.IBucket;
}

// Shared exclude patterns for Lambda asset bundling
const LAMBDA_ASSET_EXCLUDES = [
  "test_*.py",
  "*_test.py",
  "conftest.py",
  "pytest.ini",
  ".hypothesis",
  "__pycache__",
  "*.pyc",
  ".DS_Store",
  ".pytest_cache",
  "function.zip",
];

export class IngestionStack extends cdk.Stack {
  public readonly dlq: sqs.Queue;
  public readonly cdcBucket: s3.Bucket;
  public readonly ingestLambda: lambda.Function;

  constructor(scope: Construct, id: string, props: IngestionStackProps) {
    super(scope, id, props);

    const {
      vpc,
      lambdaSecurityGroup,
      kmsKey,
      dataBucket,
      salesforceInstanceUrl,
      salesforceConnectedAppClientId,
      salesforceConnectedAppClientSecretArn,
      salesforceJwtToken,
      // Zero-Config Schema Discovery table
      schemaCacheTable,
    } = props;

    // Dead Letter Queue for failed records
    this.dlq = new sqs.Queue(this, "IngestionDLQ", {
      queueName: "salesforce-ai-search-ingestion-dlq",
      encryption: sqs.QueueEncryption.KMS,
      encryptionMasterKey: kmsKey,
      retentionPeriod: cdk.Duration.days(14),
      visibilityTimeout: cdk.Duration.minutes(5),
    });

    // S3 bucket for CDC data from AppFlow
    this.cdcBucket = new s3.Bucket(this, "CDCBucket", {
      bucketName: `salesforce-ai-search-cdc-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: kmsKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      lifecycleRules: [
        {
          id: "DeleteOldCDCData",
          enabled: true,
          expiration: cdk.Duration.days(7), // CDC data only needed temporarily
        },
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // AppFlow configuration (if Salesforce credentials provided)
    if (
      salesforceInstanceUrl &&
      salesforceConnectedAppClientId &&
      salesforceConnectedAppClientSecretArn
    ) {
      // Reference the existing secret containing Salesforce credentials.
      // Use fromSecretPartialArn because the ARN from Secret.fromSecretNameV2
      // in bin/app.ts does not include the 6-character random suffix.
      const salesforceSecret = secretsmanager.Secret.fromSecretPartialArn(
        this,
        "SalesforceSecret",
        salesforceConnectedAppClientSecretArn,
      );

      // Create Salesforce connector profile for AppFlow
      const connectorProfile = new appflow.CfnConnectorProfile(
        this,
        "SalesforceConnectorProfile",
        {
          connectorProfileName: "salesforce-ai-search-cdc-profile",
          connectorType: "Salesforce",
          connectionMode: "Public",
          connectorProfileConfig: {
            connectorProfileProperties: {
              salesforce: {
                instanceUrl: salesforceInstanceUrl,
                isSandboxEnvironment: true,
              },
            },
            connectorProfileCredentials: {
              salesforce: {
                clientCredentialsArn: salesforceSecret.secretArn,
                jwtToken: salesforceJwtToken,
                oAuth2GrantType: "JWT_BEARER",
              },
            },
          },
        },
      );

      // Define CDC objects to sync (demo scope: 3 CRE objects + Account/Contact)
      const cdcObjects = [
        {
          changeEventObject: "ascendix__Property__ChangeEvent",
          sobjectName: "ascendix__Property__c",
        },
        {
          changeEventObject: "ascendix__Lease__ChangeEvent",
          sobjectName: "ascendix__Lease__c",
        },
        {
          changeEventObject: "ascendix__Availability__ChangeEvent",
          sobjectName: "ascendix__Availability__c",
        },
        {
          changeEventObject: "AccountChangeEvent",
          sobjectName: "Account",
        },
        {
          changeEventObject: "ContactChangeEvent",
          sobjectName: "Contact",
        },
      ];

      // Create AppFlow flow for each CDC object
      cdcObjects.forEach(({ changeEventObject, sobjectName }) => {
        const flow = new appflow.CfnFlow(this, `CDCFlow${changeEventObject}`, {
          flowName: `salesforce-ai-search-cdc-${sobjectName.toLowerCase()}`,
          triggerConfig: {
            triggerType: "Event",
          },
          sourceFlowConfig: {
            connectorType: "Salesforce",
            connectorProfileName: connectorProfile.connectorProfileName,
            sourceConnectorProperties: {
              salesforce: {
                object: changeEventObject,
                enableDynamicFieldUpdate: false,
              },
            },
          },
          destinationFlowConfigList: [
            {
              connectorType: "S3",
              destinationConnectorProperties: {
                s3: {
                  bucketName: this.cdcBucket.bucketName,
                  bucketPrefix: `cdc/${sobjectName}/`,
                  s3OutputFormatConfig: {
                    fileType: "JSON",
                    aggregationConfig: {
                      aggregationType: "None",
                    },
                  },
                },
              },
            },
          ],
          tasks: [
            {
              taskType: "Map_all",
              connectorOperator: {
                salesforce: "NO_OP",
              },
              sourceFields: [],
              taskProperties: [
                {
                  key: "EXCLUDE_SOURCE_FIELDS_LIST",
                  value: "[]",
                },
              ],
            },
          ],
        });
        // Flows must wait for the connector profile to be created
        flow.addDependency(connectorProfile);
      });

      // Grant AppFlow permissions to write to CDC bucket.
      // AppFlow requires PutObject + PutObjectAcl on objects AND GetBucketAcl on the bucket.
      this.cdcBucket.addToResourcePolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          principals: [new iam.ServicePrincipal("appflow.amazonaws.com")],
          actions: ["s3:PutObject", "s3:PutObjectAcl", "s3:GetBucketAcl"],
          resources: [
            this.cdcBucket.bucketArn,
            `${this.cdcBucket.bucketArn}/*`,
          ],
        }),
      );
    }

    // Separate role for Ingest Lambda to avoid circular dependency
    const ingestLambdaRole = new iam.Role(this, "IngestLambdaRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaVPCAccessExecutionRole",
        ),
      ],
    });

    // =========================================================================
    // Phase 2: CDC Sync Lambda — direct Turbopuffer sync via denorm+embed+upsert
    // =========================================================================

    // Dedicated role for CDC Sync Lambda (needs Bedrock, SSM, S3, SQS, CloudWatch)
    const cdcSyncRole = new iam.Role(this, "CDCSyncLambdaRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaVPCAccessExecutionRole",
        ),
      ],
    });

    // Bedrock Titan Embed v2 for generating embeddings
    cdcSyncRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["bedrock:InvokeModel"],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
        ],
      }),
    );

    // SSM for Salesforce credentials
    cdcSyncRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["ssm:GetParameter", "ssm:GetParameters"],
        resources: [
          `arn:aws:ssm:${this.region}:${this.account}:parameter/salesforce/*`,
        ],
      }),
    );

    // CloudWatch for freshness metrics
    cdcSyncRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["cloudwatch:PutMetricData"],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "cloudwatch:namespace": "SalesforceAISearch/CDCSync",
          },
        },
      }),
    );

    // SQS for DLQ
    this.dlq.grantSendMessages(cdcSyncRole);

    // KMS for encrypted resources
    kmsKey.grantEncryptDecrypt(cdcSyncRole);

    // Turbopuffer API key from Secrets Manager (plain-text secret)
    const turbopufferApiKeySecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      "TurbopufferApiKeySecret",
      "salesforce-ai-search/turbopuffer-api-key",
    );

    // Bundle cdc_sync Lambda with shared modules using a pre-built directory.
    // scripts/bundle_cdc_sync.sh creates the deployment package at
    // lambda/cdc_sync/.bundle/ with handler + lib/ + common/ + config.
    const cdcSyncLambda = new lambda.Function(this, "CDCSyncLambda", {
      functionName: "salesforce-ai-search-cdc-sync",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(
        path.join(__dirname, "../lambda/cdc_sync/.bundle"),
        { exclude: LAMBDA_ASSET_EXCLUDES },
      ),
      timeout: cdk.Duration.minutes(2),
      memorySize: 1024,
      role: cdcSyncRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        SALESFORCE_ORG_ID: "00Ddl000003yx57EAA",
        DENORM_CONFIG_PATH: "denorm_config.yaml",
        DLQ_URL: this.dlq.queueUrl,
        TURBOPUFFER_API_KEY: turbopufferApiKeySecret.secretValue.unsafeUnwrap(),
        LOG_LEVEL: "INFO",
        ...(props.auditBucket ? { AUDIT_BUCKET: props.auditBucket.bucketName } : {}),
      },
    });

    // Grant CDC sync Lambda read access to Turbopuffer API key secret
    turbopufferApiKeySecret.grantRead(cdcSyncRole);

    // Grant CDC sync Lambda read access to CDC bucket
    this.cdcBucket.grantRead(cdcSyncLambda);

    // Grant CDC sync Lambda write access to audit bucket
    if (props.auditBucket) {
      props.auditBucket.grantWrite(cdcSyncLambda);
    }

    // =========================================================================
    // Poll Sync Lambda — incremental sync for non-CDC objects
    // =========================================================================

    const pollSyncSchedule = this.node.tryGetContext("pollSyncSchedule") as
      | string
      | undefined;

    // Dedicated role for Poll Sync Lambda
    const pollSyncRole = new iam.Role(this, "PollSyncLambdaRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaVPCAccessExecutionRole",
        ),
      ],
    });

    // Bedrock Titan Embed v2
    pollSyncRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["bedrock:InvokeModel"],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
        ],
      }),
    );

    // SSM for Salesforce credentials + poll watermarks
    pollSyncRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:PutParameter",
        ],
        resources: [
          `arn:aws:ssm:${this.region}:${this.account}:parameter/salesforce/*`,
          `arn:aws:ssm:${this.region}:${this.account}:parameter/salesforce-ai-search/poll-watermark/*`,
        ],
      }),
    );

    // CloudWatch for sync metrics
    pollSyncRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["cloudwatch:PutMetricData"],
        resources: ["*"],
        conditions: {
          StringEquals: {
            "cloudwatch:namespace": "SalesforceAISearch/PollSync",
          },
        },
      }),
    );

    // SQS for DLQ
    this.dlq.grantSendMessages(pollSyncRole);

    // KMS
    kmsKey.grantEncryptDecrypt(pollSyncRole);

    // Turbopuffer API key
    turbopufferApiKeySecret.grantRead(pollSyncRole);

    const pollSyncLambda = new lambda.Function(this, "PollSyncLambda", {
      functionName: "salesforce-ai-search-poll-sync",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(
        path.join(__dirname, "../lambda/poll_sync/.bundle"),
        { exclude: LAMBDA_ASSET_EXCLUDES },
      ),
      timeout: cdk.Duration.minutes(5),
      memorySize: 1024,
      role: pollSyncRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        SALESFORCE_ORG_ID: "00Ddl000003yx57EAA",
        POLL_OBJECTS:
          "ascendix__Deal__c,ascendix__Sale__c,ascendix__Inquiry__c," +
          "ascendix__Listing__c,ascendix__Preference__c,Task",
        DENORM_CONFIG_PATH: "denorm_config.yaml",
        POLL_BATCH_SIZE: "200",
        TURBOPUFFER_API_KEY:
          turbopufferApiKeySecret.secretValue.unsafeUnwrap(),
        LOG_LEVEL: "INFO",
        ...(props.auditBucket
          ? { AUDIT_BUCKET: props.auditBucket.bucketName }
          : {}),
      },
    });

    // Grant poll sync write access to audit bucket
    if (props.auditBucket) {
      props.auditBucket.grantWrite(pollSyncLambda);
    }

    // Optional EventBridge scheduled rule for poll sync
    if (pollSyncSchedule) {
      const pollSyncRule = new events.Rule(this, "PollSyncScheduleRule", {
        ruleName: "salesforce-ai-search-poll-sync-schedule",
        description: "Scheduled poll sync for non-CDC objects",
        schedule: events.Schedule.expression(pollSyncSchedule),
      });

      pollSyncRule.addTarget(
        new targets.LambdaFunction(pollSyncLambda, {
          retryAttempts: 2,
        }),
      );
    }

    // Ingest Lambda (for batch export fallback)
    this.ingestLambda = new lambda.Function(this, "IngestLambda", {
      functionName: "salesforce-ai-search-ingest",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/ingest"), { exclude: LAMBDA_ASSET_EXCLUDES }),
      timeout: cdk.Duration.seconds(29),
      memorySize: 512,
      role: ingestLambdaRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        LOG_LEVEL: "INFO",
      },
    });

    // =========================================================================
    // Zero-Config Schema Discovery Lambda
    // =========================================================================
    // **Feature: zero-config-schema-discovery**
    // **Requirements: 1.1, 1.6**

    // Schema Discovery Lambda (conditionally created when schema cache table is provided)
    let schemaDiscoveryLambda: lambda.Function | undefined;
    if (schemaCacheTable) {
      // Create a separate role for Schema Discovery Lambda with Salesforce API access
      const schemaDiscoveryRole = new iam.Role(
        this,
        "SchemaDiscoveryLambdaRole",
        {
          assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
          managedPolicies: [
            iam.ManagedPolicy.fromAwsManagedPolicyName(
              "service-role/AWSLambdaVPCAccessExecutionRole",
            ),
          ],
        },
      );

      // Grant KMS permissions
      kmsKey.grantEncryptDecrypt(schemaDiscoveryRole);

      // Grant Secrets Manager access for Salesforce credentials
      if (salesforceConnectedAppClientSecretArn) {
        schemaDiscoveryRole.addToPolicy(
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: ["secretsmanager:GetSecretValue"],
            resources: [salesforceConnectedAppClientSecretArn],
          }),
        );
      }

      // Grant SSM Parameter Store access for Salesforce API credentials
      // **Feature: zero-config-production, Task 26.1**
      // **Requirements: 1.1 - Configuration Service needs Salesforce API access**
      schemaDiscoveryRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["ssm:GetParameter", "ssm:GetParameters"],
          resources: [
            `arn:aws:ssm:${this.region}:${this.account}:parameter/salesforce/*`,
          ],
        }),
      );

      schemaDiscoveryLambda = new lambda.Function(
        this,
        "SchemaDiscoveryLambda",
        {
          functionName: "salesforce-ai-search-schema-discovery",
          runtime: lambda.Runtime.PYTHON_3_11,
          handler: "index.lambda_handler",
          code: lambda.Code.fromAsset(
            path.join(__dirname, "../lambda/schema_discovery"),
            { exclude: LAMBDA_ASSET_EXCLUDES },
          ),
          timeout: cdk.Duration.minutes(5), // Schema discovery can take time for many objects
          memorySize: 512,
          role: schemaDiscoveryRole,
          vpc,
          vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
          securityGroups: [lambdaSecurityGroup],
          environment: {
            SCHEMA_CACHE_TABLE: schemaCacheTable.tableName,
            SALESFORCE_INSTANCE_URL: salesforceInstanceUrl || "",
            SALESFORCE_CLIENT_SECRET_ARN:
              salesforceConnectedAppClientSecretArn || "",
            LOG_LEVEL: "INFO",
          },
        },
      );

      // Grant Schema Discovery Lambda read/write access to schema cache table
      schemaCacheTable.grantReadWriteData(schemaDiscoveryLambda);
    }

    // =========================================================================
    // Task 39: Schema Drift Checker Lambda
    // =========================================================================
    // **Feature: schema-drift-monitoring**
    // **Task: 39**
    // READ-ONLY checker that compares SF Describe with Schema Cache and emits metrics

    let schemaDriftCheckerLambda: lambda.Function | undefined;
    if (schemaCacheTable) {
      // Lambda Layer for schema_discovery module (shared with API stack)
      const schemaDiscoveryLayer = new lambda.LayerVersion(
        this,
        "SchemaDriftCheckerSchemaDiscoveryLayer",
        {
          layerVersionName: "salesforce-ai-search-schema-discovery-ingestion",
          description: "Schema discovery module for drift checker Lambda",
          code: lambda.Code.fromAsset(
            path.join(__dirname, "../lambda/layers/schema_discovery"),
            { exclude: LAMBDA_ASSET_EXCLUDES },
          ),
          compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
        },
      );
      // Create a separate role for Schema Drift Checker Lambda
      // Needs same Salesforce API access as Schema Discovery but READ-ONLY cache access
      const schemaDriftCheckerRole = new iam.Role(
        this,
        "SchemaDriftCheckerLambdaRole",
        {
          assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
          managedPolicies: [
            iam.ManagedPolicy.fromAwsManagedPolicyName(
              "service-role/AWSLambdaVPCAccessExecutionRole",
            ),
          ],
        },
      );

      // Grant KMS permissions
      kmsKey.grantEncryptDecrypt(schemaDriftCheckerRole);

      // Grant Secrets Manager access for Salesforce credentials
      if (salesforceConnectedAppClientSecretArn) {
        schemaDriftCheckerRole.addToPolicy(
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: ["secretsmanager:GetSecretValue"],
            resources: [salesforceConnectedAppClientSecretArn],
          }),
        );
      }

      // Grant SSM Parameter Store access for Salesforce API credentials
      schemaDriftCheckerRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["ssm:GetParameter", "ssm:GetParameters"],
          resources: [
            `arn:aws:ssm:${this.region}:${this.account}:parameter/salesforce/*`,
          ],
        }),
      );

      // Grant CloudWatch PutMetricData for drift metrics
      schemaDriftCheckerRole.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["cloudwatch:PutMetricData"],
          resources: ["*"],
          conditions: {
            StringEquals: {
              "cloudwatch:namespace": "SalesforceAISearch/SchemaDrift",
            },
          },
        }),
      );

      schemaDriftCheckerLambda = new lambda.Function(
        this,
        "SchemaDriftCheckerLambda",
        {
          functionName: "salesforce-ai-search-schema-drift-checker",
          runtime: lambda.Runtime.PYTHON_3_11,
          handler: "index.handler",
          code: lambda.Code.fromAsset(
            path.join(__dirname, "../lambda/schema_drift_checker"),
            { exclude: LAMBDA_ASSET_EXCLUDES },
          ),
          timeout: cdk.Duration.minutes(5),
          memorySize: 512,
          role: schemaDriftCheckerRole,
          vpc,
          vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
          securityGroups: [lambdaSecurityGroup],
          // Use shared schema_discovery layer for SchemaDiscoverer and SchemaCache classes
          layers: [schemaDiscoveryLayer],
          environment: {
            SCHEMA_CACHE_TABLE: schemaCacheTable.tableName,
            SALESFORCE_INSTANCE_URL: salesforceInstanceUrl || "",
            SALESFORCE_CLIENT_SECRET_ARN:
              salesforceConnectedAppClientSecretArn || "",
            EXPECTED_SCHEMA_OBJECT_COUNT: "9",
            LOG_LEVEL: "INFO",
          },
        },
      );

      // Grant READ-ONLY access to schema cache table
      schemaCacheTable.grantReadData(schemaDriftCheckerLambda);

      // EventBridge rule for nightly drift check (6 AM UTC)
      const driftCheckRule = new events.Rule(this, "SchemaDriftCheckRule", {
        ruleName: "salesforce-ai-search-schema-drift-check-nightly",
        description: "Nightly schema drift check (Task 39)",
        schedule: events.Schedule.cron({
          minute: "0",
          hour: "6",
          day: "*",
          month: "*",
          year: "*",
        }),
      });

      driftCheckRule.addTarget(
        new targets.LambdaFunction(schemaDriftCheckerLambda, {
          retryAttempts: 2,
        }),
      );
    }

    // EventBridge rule to trigger CDC Sync Lambda on S3 CDC events
    const cdcEventRule = new events.Rule(this, "CDCEventRule", {
      ruleName: "salesforce-ai-search-cdc-trigger",
      description: "Trigger ingestion pipeline when CDC data arrives in S3",
      eventPattern: {
        source: ["aws.s3"],
        detailType: ["Object Created"],
        detail: {
          bucket: {
            name: [this.cdcBucket.bucketName],
          },
          object: {
            key: [
              {
                prefix: "cdc/",
              },
            ],
          },
        },
      },
    });

    // CDC Sync Lambda as EventBridge target
    cdcEventRule.addTarget(
      new targets.LambdaFunction(cdcSyncLambda, {
        event: events.RuleTargetInput.fromObject({
          bucket: events.EventField.fromPath("$.detail.bucket.name"),
          key: events.EventField.fromPath("$.detail.object.key"),
          eventTime: events.EventField.fromPath("$.time"),
          eventSource: "cdc",
        }),
        retryAttempts: 2,
      }),
    );

    // Enable EventBridge notifications on CDC bucket
    this.cdcBucket.enableEventBridgeNotification();

    // CloudWatch Dashboard for Freshness Metrics
    const freshnessDashboard = new cloudwatch.Dashboard(
      this,
      "FreshnessDashboard",
      {
        dashboardName: "salesforce-ai-search-freshness",
      },
    );

    // Add widgets for freshness lag metrics
    freshnessDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "CDC to S3 Lag (P50, P95)",
        left: [
          new cloudwatch.Metric({
            namespace: "SalesforceAISearch/Ingestion",
            metricName: "CDCToS3Lag",
            statistic: "p50",
            label: "P50",
            period: cdk.Duration.minutes(5),
          }),
          new cloudwatch.Metric({
            namespace: "SalesforceAISearch/Ingestion",
            metricName: "CDCToS3Lag",
            statistic: "p95",
            label: "P95",
            period: cdk.Duration.minutes(5),
          }),
        ],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: "S3 to Processing Lag (P50, P95)",
        left: [
          new cloudwatch.Metric({
            namespace: "SalesforceAISearch/Ingestion",
            metricName: "S3ToProcessingLag",
            statistic: "p50",
            label: "P50",
            period: cdk.Duration.minutes(5),
          }),
          new cloudwatch.Metric({
            namespace: "SalesforceAISearch/Ingestion",
            metricName: "S3ToProcessingLag",
            statistic: "p95",
            label: "P95",
            period: cdk.Duration.minutes(5),
          }),
        ],
        width: 12,
      }),
    );

    freshnessDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "End-to-End Ingest Lag (P50, P95)",
        left: [
          new cloudwatch.Metric({
            namespace: "SalesforceAISearch/Ingestion",
            metricName: "EndToEndLag",
            statistic: "p50",
            label: "P50 (Target: 5 min)",
            period: cdk.Duration.minutes(5),
          }),
          new cloudwatch.Metric({
            namespace: "SalesforceAISearch/Ingestion",
            metricName: "EndToEndLag",
            statistic: "p95",
            label: "P95",
            period: cdk.Duration.minutes(5),
          }),
        ],
        width: 12,
        leftYAxis: {
          label: "Milliseconds",
          showUnits: false,
        },
        leftAnnotations: [
          {
            value: 300000, // 5 minutes in milliseconds
            label: "P50 Target (5 min)",
            color: "#ff7f0e",
          },
        ],
      }),
      new cloudwatch.GraphWidget({
        title: "Total Ingest Lag (P50, P95)",
        left: [
          new cloudwatch.Metric({
            namespace: "SalesforceAISearch/Ingestion",
            metricName: "TotalIngestLag",
            statistic: "p50",
            label: "P50",
            period: cdk.Duration.minutes(5),
          }),
          new cloudwatch.Metric({
            namespace: "SalesforceAISearch/Ingestion",
            metricName: "TotalIngestLag",
            statistic: "p95",
            label: "P95",
            period: cdk.Duration.minutes(5),
          }),
        ],
        width: 12,
      }),
    );

    freshnessDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Chunks Synced by Object",
        left: [
          new cloudwatch.Metric({
            namespace: "SalesforceAISearch/Ingestion",
            metricName: "ChunksSynced",
            statistic: "Sum",
            period: cdk.Duration.minutes(5),
          }),
        ],
        width: 12,
      }),
    );

    // CloudWatch Alarms for freshness lag
    const p50LagAlarm = new cloudwatch.Alarm(this, "P50LagAlarm", {
      alarmName: "salesforce-ai-search-p50-lag-high",
      alarmDescription: "P50 end-to-end ingest lag exceeds 10 minutes",
      metric: new cloudwatch.Metric({
        namespace: "SalesforceAISearch/Ingestion",
        metricName: "EndToEndLag",
        statistic: "p50",
        period: cdk.Duration.minutes(15),
      }),
      threshold: 600000, // 10 minutes in milliseconds
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    const p95LagAlarm = new cloudwatch.Alarm(this, "P95LagAlarm", {
      alarmName: "salesforce-ai-search-p95-lag-high",
      alarmDescription: "P95 end-to-end ingest lag exceeds 15 minutes",
      metric: new cloudwatch.Metric({
        namespace: "SalesforceAISearch/Ingestion",
        metricName: "EndToEndLag",
        statistic: "p95",
        period: cdk.Duration.minutes(15),
      }),
      threshold: 900000, // 15 minutes in milliseconds
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    // Outputs
    new cdk.CfnOutput(this, "DLQUrl", {
      value: this.dlq.queueUrl,
      description: "Dead Letter Queue URL",
      exportName: `${this.stackName}-DLQUrl`,
    });

    new cdk.CfnOutput(this, "CDCBucketName", {
      value: this.cdcBucket.bucketName,
      description: "CDC Data Bucket Name",
      exportName: `${this.stackName}-CDCBucketName`,
    });

    new cdk.CfnOutput(this, "CDCBucketArn", {
      value: this.cdcBucket.bucketArn,
      description: "CDC Data Bucket ARN",
      exportName: `${this.stackName}-CDCBucketArn`,
    });

    new cdk.CfnOutput(this, "CDCEventRuleArn", {
      value: cdcEventRule.ruleArn,
      description: "EventBridge Rule ARN for CDC events",
      exportName: `${this.stackName}-CDCEventRuleArn`,
    });

    new cdk.CfnOutput(this, "IngestLambdaArn", {
      value: this.ingestLambda.functionArn,
      description: "Ingest Lambda Function ARN (for batch export)",
      exportName: `${this.stackName}-IngestLambdaArn`,
    });

    new cdk.CfnOutput(this, "CDCSyncLambdaArn", {
      value: cdcSyncLambda.functionArn,
      description: "CDC Sync Lambda Function ARN (Phase 2: Turbopuffer sync)",
      exportName: `${this.stackName}-CDCSyncLambdaArn`,
    });

    new cdk.CfnOutput(this, "PollSyncLambdaArn", {
      value: pollSyncLambda.functionArn,
      description: "Poll Sync Lambda Function ARN (incremental sync for non-CDC objects)",
      exportName: `${this.stackName}-PollSyncLambdaArn`,
    });

    // Zero-Config Schema Discovery Lambda output
    if (schemaDiscoveryLambda) {
      new cdk.CfnOutput(this, "SchemaDiscoveryLambdaArn", {
        value: schemaDiscoveryLambda.functionArn,
        description: "Schema Discovery Lambda Function ARN",
        exportName: `${this.stackName}-SchemaDiscoveryLambdaArn`,
      });
    }

    // Task 39: Schema Drift Checker Lambda output
    if (schemaDriftCheckerLambda) {
      new cdk.CfnOutput(this, "SchemaDriftCheckerLambdaArn", {
        value: schemaDriftCheckerLambda.functionArn,
        description: "Schema Drift Checker Lambda Function ARN (Task 39)",
        exportName: `${this.stackName}-SchemaDriftCheckerLambdaArn`,
      });
    }

    new cdk.CfnOutput(this, "FreshnessDashboardUrl", {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${freshnessDashboard.dashboardName}`,
      description: "CloudWatch Freshness Dashboard URL",
    });

    new cdk.CfnOutput(this, "P50LagAlarmArn", {
      value: p50LagAlarm.alarmArn,
      description: "P50 Lag Alarm ARN",
      exportName: `${this.stackName}-P50LagAlarmArn`,
    });

    new cdk.CfnOutput(this, "P95LagAlarmArn", {
      value: p95LagAlarm.alarmArn,
      description: "P95 Lag Alarm ARN",
      exportName: `${this.stackName}-P95LagAlarmArn`,
    });

    // Tag all resources
    cdk.Tags.of(this).add("Component", "Ingestion");
  }
}
