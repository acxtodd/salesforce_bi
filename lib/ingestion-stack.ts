import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";
import * as tasks from "aws-cdk-lib/aws-stepfunctions-tasks";
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as iam from "aws-cdk-lib/aws-iam";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as kms from "aws-cdk-lib/aws-kms";
import * as appflow from "aws-cdk-lib/aws-appflow";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as events from "aws-cdk-lib/aws-events";
import * as targets from "aws-cdk-lib/aws-events-targets";
import * as s3n from "aws-cdk-lib/aws-s3-notifications";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Construct } from "constructs";
import * as path from "path";

interface IngestionStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  lambdaSecurityGroup: ec2.SecurityGroup;
  kmsKey: kms.Key;
  dataBucket: s3.Bucket;
  knowledgeBaseId?: string;
  dataSourceId?: string;
  salesforceInstanceUrl?: string;
  salesforceConnectedAppClientId?: string;
  salesforceConnectedAppClientSecretArn?: string;
  salesforceJwtToken?: string;
  // Phase 3: Graph Enhancement tables
  graphNodesTable?: dynamodb.Table;
  graphEdgesTable?: dynamodb.Table;
  // Zero-Config Schema Discovery table
  schemaCacheTable?: dynamodb.Table;
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
  public readonly stateMachine: sfn.StateMachine;
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
      knowledgeBaseId,
      dataSourceId,
      salesforceInstanceUrl,
      salesforceConnectedAppClientId,
      salesforceConnectedAppClientSecretArn,
      salesforceJwtToken,
      // Phase 3: Graph Enhancement tables
      graphNodesTable,
      graphEdgesTable,
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

      // Define CDC objects to sync (POC scope: 5 Ascendix CRE objects)
      const cdcObjects = [
        "ascendix__Property__ChangeEvent",
        "ascendix__Lease__ChangeEvent",
        "ascendix__Availability__ChangeEvent",
        "ascendix__Deal__ChangeEvent",
        "ascendix__Sale__ChangeEvent",
      ];

      // Create AppFlow flow for each CDC object
      cdcObjects.forEach((objectName) => {
        // ascendix__Property__ChangeEvent → ascendix__Property__c
        const sobjectName = objectName.replace("ChangeEvent", "c");

        new appflow.CfnFlow(this, `CDCFlow${objectName}`, {
          flowName: `salesforce-ai-search-cdc-${sobjectName.toLowerCase()}`,
          triggerConfig: {
            triggerType: "Event",
          },
          sourceFlowConfig: {
            connectorType: "Salesforce",
            connectorProfileName: connectorProfile.connectorProfileName,
            sourceConnectorProperties: {
              salesforce: {
                object: objectName,
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
                    prefixConfig: {
                      prefixType: "PATH_AND_FILENAME",
                      prefixFormat: "YEAR/MONTH/DAY/HOUR",
                    },
                  },
                },
              },
            },
          ],
          tasks: [
            {
              taskType: "Filter",
              connectorOperator: {
                salesforce: "PROJECTION",
              },
              sourceFields: [],
            },
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
      });

      // Grant AppFlow permissions to write to CDC bucket
      this.cdcBucket.addToResourcePolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          principals: [new iam.ServicePrincipal("appflow.amazonaws.com")],
          actions: ["s3:PutObject", "s3:PutObjectAcl"],
          resources: [`${this.cdcBucket.bucketArn}/*`],
        }),
      );
    }

    // Lambda execution role with necessary permissions
    const lambdaRole = new iam.Role(this, "IngestionLambdaRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaVPCAccessExecutionRole",
        ),
      ],
    });

    // Separate role for Ingest Lambda to avoid circular dependency
    const ingestLambdaRole = new iam.Role(this, "IngestLambdaRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaVPCAccessExecutionRole",
        ),
      ],
    });

    // Grant permissions
    dataBucket.grantReadWrite(lambdaRole);
    kmsKey.grantEncryptDecrypt(lambdaRole);

    // Grant Bedrock permissions for embedding and KB sync
    lambdaRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "bedrock:InvokeModel",
          "bedrock:StartIngestionJob",
          "bedrock:GetIngestionJob",
        ],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
          `arn:aws:bedrock:${this.region}:${this.account}:knowledge-base/*`,
        ],
      }),
    );

    // CDC Processor Lambda
    const cdcProcessorLambda = new lambda.Function(this, "CDCProcessorLambda", {
      functionName: "salesforce-ai-search-cdc-processor",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(
        path.join(__dirname, "../lambda/cdc_processor"),
        { exclude: LAMBDA_ASSET_EXCLUDES },
      ),
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      role: lambdaRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        LOG_LEVEL: "INFO",
      },
    });

    // Grant CDC processor access to CDC bucket
    this.cdcBucket.grantRead(cdcProcessorLambda);

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
        TURBOPUFFER_API_KEY: process.env.TURBOPUFFER_API_KEY || "",
        LOG_LEVEL: "INFO",
      },
    });

    // Grant CDC sync Lambda read access to CDC bucket
    this.cdcBucket.grantRead(cdcSyncLambda);

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
        STATE_MACHINE_ARN: "", // Will be set after state machine is created
        LOG_LEVEL: "INFO",
      },
    });

    // Validate Lambda
    const validateLambda = new lambda.Function(this, "ValidateLambda", {
      functionName: "salesforce-ai-search-validate",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/validate"), { exclude: LAMBDA_ASSET_EXCLUDES }),
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      role: lambdaRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        LOG_LEVEL: "INFO",
      },
    });

    // Transform Lambda
    const transformLambda = new lambda.Function(this, "TransformLambda", {
      functionName: "salesforce-ai-search-transform",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/transform"), { exclude: LAMBDA_ASSET_EXCLUDES }),
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      role: lambdaRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        LOG_LEVEL: "INFO",
      },
    });

    // Chunking Lambda
    const chunkingLambda = new lambda.Function(this, "ChunkingLambda", {
      functionName: "salesforce-ai-search-chunking",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/chunking"), { exclude: LAMBDA_ASSET_EXCLUDES }),
      timeout: cdk.Duration.minutes(2),
      memorySize: 1024,
      role: lambdaRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        LOG_LEVEL: "INFO",
        DATA_BUCKET: dataBucket.bucketName,
        SCHEMA_CACHE_TABLE: "salesforce-ai-search-schema-cache",
      },
    });

    // Enrich Lambda
    const enrichLambda = new lambda.Function(this, "EnrichLambda", {
      functionName: "salesforce-ai-search-enrich",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/enrich"), { exclude: LAMBDA_ASSET_EXCLUDES }),
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      role: lambdaRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        LOG_LEVEL: "INFO",
        DATA_BUCKET: dataBucket.bucketName,
      },
    });

    // Embed Lambda
    const embedLambda = new lambda.Function(this, "EmbedLambda", {
      functionName: "salesforce-ai-search-embed",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/embed"), { exclude: LAMBDA_ASSET_EXCLUDES }),
      timeout: cdk.Duration.minutes(5),
      memorySize: 2048,
      role: lambdaRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        LOG_LEVEL: "INFO",
        DATA_BUCKET: dataBucket.bucketName,
      },
    });

    // Sync Lambda
    const syncLambda = new lambda.Function(this, "SyncLambda", {
      functionName: "salesforce-ai-search-sync",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/sync"), { exclude: LAMBDA_ASSET_EXCLUDES }),
      timeout: cdk.Duration.minutes(2),
      memorySize: 1024,
      role: lambdaRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        DATA_BUCKET: dataBucket.bucketName,
        KNOWLEDGE_BASE_ID: knowledgeBaseId || "",
        DATA_SOURCE_ID: dataSourceId || "",
        LOG_LEVEL: "INFO",
      },
    });

    // Phase 3: Graph Builder Lambda (conditionally created when graph tables are provided)
    let graphBuilderLambda: lambda.Function | undefined;
    if (graphNodesTable && graphEdgesTable) {
      graphBuilderLambda = new lambda.Function(this, "GraphBuilderLambda", {
        functionName: "salesforce-ai-search-graph-builder",
        runtime: lambda.Runtime.PYTHON_3_11,
        handler: "index.lambda_handler",
        code: lambda.Code.fromAsset(
          path.join(__dirname, "../lambda/graph_builder"),
          { exclude: LAMBDA_ASSET_EXCLUDES },
        ),
        timeout: cdk.Duration.seconds(60),
        memorySize: 512,
        role: lambdaRole,
        vpc,
        vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        securityGroups: [lambdaSecurityGroup],
        environment: {
          GRAPH_NODES_TABLE: graphNodesTable.tableName,
          GRAPH_EDGES_TABLE: graphEdgesTable.tableName,
          SCHEMA_CACHE_TABLE:
            schemaCacheTable?.tableName || "salesforce-ai-search-schema-cache",
          LOG_LEVEL: "INFO",
        },
      });

      // Grant Graph Builder Lambda access to graph tables
      graphNodesTable.grantReadWriteData(graphBuilderLambda);
      graphEdgesTable.grantReadWriteData(graphBuilderLambda);

      // Grant Graph Builder Lambda CloudWatch PutMetricData for graph metrics
      graphBuilderLambda.addToRolePolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["cloudwatch:PutMetricData"],
          resources: ["*"],
          conditions: {
            StringEquals: {
              "cloudwatch:namespace": "SalesforceAISearch/GraphBuilder",
            },
          },
        }),
      );

      // Grant Graph Builder Lambda read access to schema cache table
      if (schemaCacheTable) {
        schemaCacheTable.grantReadData(graphBuilderLambda);
      }
    }

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

    // Step Functions tasks
    const cdcProcessorTask = new tasks.LambdaInvoke(this, "CDCProcessorTask", {
      lambdaFunction: cdcProcessorLambda,
      outputPath: "$.Payload",
    });

    const validateTask = new tasks.LambdaInvoke(this, "ValidateTask", {
      lambdaFunction: validateLambda,
      outputPath: "$.Payload",
    });

    const transformTask = new tasks.LambdaInvoke(this, "TransformTask", {
      lambdaFunction: transformLambda,
      outputPath: "$.Payload",
    });

    const chunkTask = new tasks.LambdaInvoke(this, "ChunkTask", {
      lambdaFunction: chunkingLambda,
      outputPath: "$.Payload",
    });

    const enrichTask = new tasks.LambdaInvoke(this, "EnrichTask", {
      lambdaFunction: enrichLambda,
      outputPath: "$.Payload",
    });

    const embedTask = new tasks.LambdaInvoke(this, "EmbedTask", {
      lambdaFunction: embedLambda,
      outputPath: "$.Payload",
    });

    const syncTask = new tasks.LambdaInvoke(this, "SyncTask", {
      lambdaFunction: syncLambda,
      outputPath: "$.Payload",
    });

    // Phase 3: Graph Builder task (conditionally created)
    let graphBuilderTask: tasks.LambdaInvoke | undefined;
    if (graphBuilderLambda) {
      graphBuilderTask = new tasks.LambdaInvoke(this, "GraphBuilderTask", {
        lambdaFunction: graphBuilderLambda,
        outputPath: "$.Payload",
      });
    }

    // Define workflow
    const noValidRecords = new sfn.Succeed(this, "NoValidRecords");
    const success = new sfn.Succeed(this, "Success");
    const fail = new sfn.Fail(this, "Fail", {
      comment: "Ingestion failed, sent to DLQ",
    });

    // DLQ tasks for each step
    const sendValidateToDLQ = new tasks.SqsSendMessage(
      this,
      "SendValidateToDLQ",
      {
        queue: this.dlq,
        messageBody: sfn.TaskInput.fromJsonPathAt("$"),
      },
    ).next(fail);

    const sendTransformToDLQ = new tasks.SqsSendMessage(
      this,
      "SendTransformToDLQ",
      {
        queue: this.dlq,
        messageBody: sfn.TaskInput.fromJsonPathAt("$"),
      },
    ).next(fail);

    const sendChunkToDLQ = new tasks.SqsSendMessage(this, "SendChunkToDLQ", {
      queue: this.dlq,
      messageBody: sfn.TaskInput.fromJsonPathAt("$"),
    }).next(fail);

    const sendEnrichToDLQ = new tasks.SqsSendMessage(this, "SendEnrichToDLQ", {
      queue: this.dlq,
      messageBody: sfn.TaskInput.fromJsonPathAt("$"),
    }).next(fail);

    const sendEmbedToDLQ = new tasks.SqsSendMessage(this, "SendEmbedToDLQ", {
      queue: this.dlq,
      messageBody: sfn.TaskInput.fromJsonPathAt("$"),
    }).next(fail);

    const sendSyncToDLQ = new tasks.SqsSendMessage(this, "SendSyncToDLQ", {
      queue: this.dlq,
      messageBody: sfn.TaskInput.fromJsonPathAt("$"),
    }).next(fail);

    const sendCDCProcessorToDLQ = new tasks.SqsSendMessage(
      this,
      "SendCDCProcessorToDLQ",
      {
        queue: this.dlq,
        messageBody: sfn.TaskInput.fromJsonPathAt("$"),
      },
    ).next(fail);

    // Phase 3: Graph Builder DLQ handler (conditionally created)
    let sendGraphBuilderToDLQ: sfn.Chain | undefined;
    if (graphBuilderTask) {
      sendGraphBuilderToDLQ = new tasks.SqsSendMessage(
        this,
        "SendGraphBuilderToDLQ",
        {
          queue: this.dlq,
          messageBody: sfn.TaskInput.fromJsonPathAt("$"),
        },
      ).next(fail);
    }

    const checkValidRecords = new sfn.Choice(this, "CheckValidRecords")
      .when(sfn.Condition.numberGreaterThan("$.validCount", 0), transformTask)
      .otherwise(noValidRecords);

    // Start with CDC processor for event-driven ingestion
    const definition = cdcProcessorTask
      .addCatch(sendCDCProcessorToDLQ, {
        resultPath: "$.error",
      })
      .next(validateTask);

    validateTask
      .addCatch(sendValidateToDLQ, {
        resultPath: "$.error",
      })
      .next(checkValidRecords);

    transformTask
      .addCatch(sendTransformToDLQ, {
        resultPath: "$.error",
      })
      .next(chunkTask);

    // Phase 3: Conditionally insert Graph Builder after chunking
    if (graphBuilderTask && sendGraphBuilderToDLQ) {
      chunkTask
        .addCatch(sendChunkToDLQ, {
          resultPath: "$.error",
        })
        .next(graphBuilderTask);

      graphBuilderTask
        .addCatch(sendGraphBuilderToDLQ, {
          resultPath: "$.error",
        })
        .next(enrichTask);
    } else {
      chunkTask
        .addCatch(sendChunkToDLQ, {
          resultPath: "$.error",
        })
        .next(enrichTask);
    }

    enrichTask
      .addCatch(sendEnrichToDLQ, {
        resultPath: "$.error",
      })
      .next(embedTask);

    embedTask
      .addCatch(sendEmbedToDLQ, {
        resultPath: "$.error",
      })
      .next(syncTask);

    syncTask
      .addCatch(sendSyncToDLQ, {
        resultPath: "$.error",
      })
      .next(success);

    // Create State Machine
    this.stateMachine = new sfn.StateMachine(this, "IngestionStateMachine", {
      stateMachineName: "salesforce-ai-search-ingestion",
      definition,
      timeout: cdk.Duration.minutes(15),
      tracingEnabled: true,
    });

    // Update ingest Lambda with state machine ARN
    this.ingestLambda.addEnvironment(
      "STATE_MACHINE_ARN",
      this.stateMachine.stateMachineArn,
    );

    // Grant ingest Lambda permission to start executions
    this.stateMachine.grantStartExecution(this.ingestLambda);

    // EventBridge rule to trigger Step Functions on S3 CDC events
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

    // Add Step Functions as target
    cdcEventRule.addTarget(
      new targets.SfnStateMachine(this.stateMachine, {
        input: events.RuleTargetInput.fromObject({
          bucket: events.EventField.fromPath("$.detail.bucket.name"),
          key: events.EventField.fromPath("$.detail.object.key"),
          eventTime: events.EventField.fromPath("$.time"),
          eventSource: "cdc",
        }),
      }),
    );

    // Phase 2: Add CDC Sync Lambda as second target on the same EventBridge rule.
    // Same input transform as Step Functions target — delivers flat {bucket, key}.
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
      new cloudwatch.GraphWidget({
        title: "Step Functions Execution Duration",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/States",
            metricName: "ExecutionTime",
            statistic: "Average",
            dimensionsMap: {
              StateMachineArn: this.stateMachine.stateMachineArn,
            },
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
    new cdk.CfnOutput(this, "StateMachineArn", {
      value: this.stateMachine.stateMachineArn,
      description: "Ingestion State Machine ARN",
      exportName: `${this.stackName}-StateMachineArn`,
    });

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
