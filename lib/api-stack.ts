import * as cdk from "aws-cdk-lib";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as kms from "aws-cdk-lib/aws-kms";
import * as iam from "aws-cdk-lib/aws-iam";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as logs from "aws-cdk-lib/aws-logs";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";
import * as path from "path";

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

interface ApiStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  lambdaSecurityGroup: ec2.SecurityGroup;
  kmsKey: kms.Key;
  authzCacheTable: dynamodb.Table;
  rateLimitsTable: dynamodb.Table;
  actionMetadataTable: dynamodb.Table;
  ingestLambda: lambda.Function;
  // Zero-Config Schema Discovery table
  schemaCacheTable?: dynamodb.Table;
  configArtifactBucket: s3.Bucket;
}

export class ApiStack extends cdk.Stack {
  public readonly api: apigateway.RestApi;
  public readonly queryLambda: lambda.DockerImageFunction;
  public readonly authzLambda: lambda.Function;
  public readonly actionLambda: lambda.Function;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const {
      vpc,
      lambdaSecurityGroup,
      kmsKey,
      authzCacheTable,
      rateLimitsTable,
      actionMetadataTable,
      ingestLambda,
      schemaCacheTable,
      configArtifactBucket,
    } = props;

    // -------------------------------------------------------------------------
    // 1. Lambda Roles & Functions
    // -------------------------------------------------------------------------

    // Helper to create a Lambda role with common permissions
    const createLambdaRole = (id: string, description: string) => {
      const role = new iam.Role(this, id, {
        assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
        description,
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName(
            "service-role/AWSLambdaVPCAccessExecutionRole",
          ),
        ],
      });

      // Grant common permissions
      kmsKey.grantEncryptDecrypt(role);

      // **Feature: zero-config-production, Task 28.3**
      // Split Bedrock and Marketplace permissions for least privilege

      // Grant Bedrock permissions with specific resource ARNs
      role.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            "bedrock:InvokeModel",
            "bedrock:InvokeModelWithResponseStream",
          ],
          resources: [
            // Titan embedding model
            `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
            // Inference profiles (cross-region)
            `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
            // Foundation models — all providers for model selector A/B testing
            `arn:aws:bedrock:*::foundation-model/anthropic.claude-*`,
            `arn:aws:bedrock:*::foundation-model/amazon.nova-*`,
            `arn:aws:bedrock:*::foundation-model/cohere.*`,
            `arn:aws:bedrock:*::foundation-model/mistral.*`,
            `arn:aws:bedrock:*::foundation-model/minimax.*`,
            `arn:aws:bedrock:*::foundation-model/deepseek.*`,
            `arn:aws:bedrock:*::foundation-model/zai.*`,
          ],
        }),
      );

      // Grant Bedrock Knowledge Base permissions with specific resource ARNs
      role.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
          resources: [
            `arn:aws:bedrock:${this.region}:${this.account}:knowledge-base/*`,
          ],
        }),
      );

      // Grant AWS Marketplace permissions (requires '*' resource per AWS documentation)
      role.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: [
            "aws-marketplace:ViewSubscriptions",
            "aws-marketplace:Subscribe",
            "aws-marketplace:Unsubscribe",
          ],
          resources: ["*"], // Marketplace actions require '*' resource per AWS documentation
        }),
      );

      // Grant SSM permissions
      role.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["ssm:GetParameter"],
          resources: [
            `arn:aws:ssm:${this.region}:${this.account}:parameter/salesforce/*`,
            `arn:aws:ssm:${this.region}:${this.account}:parameter/salesforce-ai-search/config/*`,
          ],
        }),
      );

      // Grant CloudWatch custom metrics
      role.addToPolicy(
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["cloudwatch:PutMetricData"],
          resources: ["*"],
          conditions: {
            StringEquals: {
              "cloudwatch:namespace": [
                "SalesforceAISearch/AuthZ",
                "SalesforceAISearch/Retrieve",
              ],
            },
          },
        }),
      );

      return role;
    };

    // 1. AuthZ Lambda Role
    const authzRole = createLambdaRole(
      "AuthzLambdaRole",
      "Role for AuthZ Sidecar Lambda",
    );
    authzCacheTable.grantReadWriteData(authzRole);

    // AuthZ Sidecar Lambda
    this.authzLambda = new lambda.Function(this, "AuthzLambda", {
      functionName: "salesforce-ai-search-authz",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/authz"), { exclude: LAMBDA_ASSET_EXCLUDES }),
      timeout: cdk.Duration.seconds(29),
      memorySize: 512,
      role: authzRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        AUTHZ_CACHE_TABLE: authzCacheTable.tableName,
        SALESFORCE_API_ENDPOINT: process.env.SALESFORCE_API_ENDPOINT || "",
        SALESFORCE_API_VERSION: "v59.0",
        SALESFORCE_TOKEN_PARAM: "/salesforce/access_token",
        LOG_LEVEL: "INFO",
      },
    });

    // -------------------------------------------------------------------------
    // Secrets Manager for API Key (Security Fix - Task 28.1)
    // -------------------------------------------------------------------------
    // **Feature: zero-config-production, Task 28.1**
    // Move hardcoded API key to Secrets Manager for secure storage
    // The secret should be created manually or via CLI before deployment:
    // aws secretsmanager create-secret --name salesforce-ai-search/streaming-api-key \
    //   --secret-string '{"apiKey":"<your-api-key>"}' --region us-west-2
    const streamingApiKeySecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      "StreamingApiKeySecret",
      "salesforce-ai-search/streaming-api-key",
    );

    // 2. Query Lambda (Phase 2: Turbopuffer + tool-use via /query endpoint)
    const queryRole = createLambdaRole(
      "QueryLambdaRole",
      "Role for Query Lambda",
    );

    // Turbopuffer API key from Secrets Manager (plain-text secret)
    const turbopufferApiKeySecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      "TurbopufferApiKeySecret",
      "salesforce-ai-search/turbopuffer-api-key",
    );

    this.queryLambda = new lambda.DockerImageFunction(this, "QueryLambda", {
      functionName: "salesforce-ai-search-query",
      code: lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, "../lambda/query"),
      ),
      timeout: cdk.Duration.seconds(29),
      memorySize: 1024,
      architecture: lambda.Architecture.ARM_64,
      role: queryRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        AWS_LWA_INVOKE_MODE: "RESPONSE_STREAM",
        DENORM_CONFIG_PATH: "denorm_config.yaml",
        CONFIG_ARTIFACT_BUCKET: configArtifactBucket.bucketName,
        CONFIG_ARTIFACT_PREFIX: "config",
        BEDROCK_MODEL_ID:
          "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        TURBOPUFFER_API_KEY: turbopufferApiKeySecret.secretValue.unsafeUnwrap(),
        LOG_LEVEL: "INFO",
        // Reuse same API key secret as answer Lambda for auth parity
        API_KEY_SECRET_ARN: streamingApiKeySecret.secretArn,
      },
    });

    // Grant Query Lambda permission to read the Turbopuffer + streaming API key secrets
    turbopufferApiKeySecret.grantRead(queryRole);
    streamingApiKeySecret.grantRead(this.queryLambda);
    configArtifactBucket.grantRead(queryRole);

    const queryFunctionUrl = this.queryLambda.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
      cors: {
        allowedOrigins: ["*"],
        allowedMethods: [lambda.HttpMethod.POST],
        allowedHeaders: ["*"],
      },
    });

    // 3. Action Lambda Role
    const actionRole = createLambdaRole(
      "ActionLambdaRole",
      "Role for Action Lambda",
    );
    rateLimitsTable.grantReadWriteData(actionRole);
    actionMetadataTable.grantReadWriteData(actionRole);

    // Action Lambda
    this.actionLambda = new lambda.Function(this, "ActionLambda", {
      functionName: "salesforce-ai-search-action",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/action"), { exclude: LAMBDA_ASSET_EXCLUDES }),
      timeout: cdk.Duration.seconds(29),
      memorySize: 1024,
      role: actionRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        AUTHZ_LAMBDA_FUNCTION_NAME: this.authzLambda.functionName,
        RATE_LIMITS_TABLE_NAME: rateLimitsTable.tableName,
        ACTION_METADATA_TABLE_NAME: actionMetadataTable.tableName,
        SALESFORCE_API_ENDPOINT: process.env.SALESFORCE_API_ENDPOINT || "",
        SALESFORCE_API_VERSION: "v59.0",
        SALESFORCE_TOKEN_PARAM: "/salesforce/access_token",
        LOG_LEVEL: "INFO",
      },
    });

    // Grant permissions
    this.authzLambda.grantInvoke(this.actionLambda); // Action invokes AuthZ

    // CloudWatch Log Group for API Gateway
    const apiLogGroup = new logs.LogGroup(this, "ApiGatewayLogGroup", {
      logGroupName: "/aws/apigateway/salesforce-ai-search",
      retention: logs.RetentionDays.THREE_MONTHS,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // Create API Gateway
    // **SECURITY NOTE - QA Finding #2 (graph-aware-zero-config-retrieval, Task 23)**
    // API Gateway is REGIONAL (public) rather than PRIVATE for POC because:
    // 1. Salesforce Private Connect is a paid add-on not available for POC
    // 2. Salesforce Hyperforce doesn't publish IPs, making IP allowlisting infeasible
    // 3. API key requirement provides authentication layer
    // Mitigations:
    // - All endpoints require API key (apiKeyRequired: true)
    // - Usage plans with rate limiting and quotas
    // - Request validation on all endpoints
    // Production: Consider Private API Gateway with Salesforce Private Connect
    // See: Requirement 11.1
    this.api = new apigateway.RestApi(this, "PrivateApi", {
      restApiName: "salesforce-ai-search-private-api",
      description: "API Gateway for Salesforce AI Search POC (REGIONAL for Named Credential access)",
      endpointConfiguration: {
        types: [apigateway.EndpointType.REGIONAL], // POC: Public for Salesforce Named Credential access
      },
      policy: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            principals: [new iam.AnyPrincipal()],
            actions: ["execute-api:Invoke"],
            resources: ["execute-api:/*"],
            // POC: No VPC endpoint restriction (requires Salesforce Private Connect)
          }),
        ],
      }),
      deployOptions: {
        stageName: "prod",
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
        dataTraceEnabled: true,
        metricsEnabled: true,
        accessLogDestination: new apigateway.LogGroupLogDestination(
          apiLogGroup,
        ),
        accessLogFormat: apigateway.AccessLogFormat.jsonWithStandardFields({
          caller: true,
          httpMethod: true,
          ip: true,
          protocol: true,
          requestTime: true,
          resourcePath: true,
          responseLength: true,
          status: true,
          user: true,
        }),
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: [
          "Content-Type",
          "X-Amz-Date",
          "Authorization",
          "X-Api-Key",
          "X-Amz-Security-Token",
        ],
      },
    });

    // /ingest endpoint (for batch export)
    const ingestResource = this.api.root.addResource("ingest");
    ingestResource.addMethod(
      "POST",
      new apigateway.LambdaIntegration(ingestLambda, {
        proxy: true,
        timeout: cdk.Duration.seconds(29),
      }),
      {
        apiKeyRequired: true,
        // No strict request model validation for ingestion to allow flexibility
      },
    );

    // -------------------------------------------------------------------------
    // Schema API Lambda - Task 34.1: Schema-Driven Export Integration
    // -------------------------------------------------------------------------
    // Lightweight Lambda for reading schema cache, used by Apex (AISearchBatchExport)
    // to get field configuration from Schema Cache instead of hardcoded IndexConfiguration__mdt
    if (schemaCacheTable) {
      const schemaApiLambda = new lambda.Function(this, "SchemaApiLambda", {
        functionName: "salesforce-ai-search-schema-api",
        runtime: lambda.Runtime.PYTHON_3_11,
        handler: "index.lambda_handler",
        code: lambda.Code.fromAsset(
          path.join(__dirname, "../lambda/schema_api"),
          { exclude: LAMBDA_ASSET_EXCLUDES },
        ),
        timeout: cdk.Duration.seconds(10),
        memorySize: 256,
        environment: {
          SCHEMA_CACHE_TABLE: schemaCacheTable.tableName,
        },
        logRetention: logs.RetentionDays.TWO_WEEKS,
      });

      // Grant read access to schema cache table
      schemaCacheTable.grantReadData(schemaApiLambda);

      // /schema endpoint - list all cached objects
      const schemaResource = this.api.root.addResource("schema");
      schemaResource.addMethod(
        "GET",
        new apigateway.LambdaIntegration(schemaApiLambda, {
          proxy: true,
          timeout: cdk.Duration.seconds(10),
        }),
        {
          apiKeyRequired: true,
        },
      );

      // /schema/{objectApiName} endpoint - get export fields for specific object
      const schemaObjectResource = schemaResource.addResource("{objectApiName}");
      schemaObjectResource.addMethod(
        "GET",
        new apigateway.LambdaIntegration(schemaApiLambda, {
          proxy: true,
          timeout: cdk.Duration.seconds(10),
        }),
        {
          apiKeyRequired: true,
        },
      );

      // Output the schema API endpoint
      new cdk.CfnOutput(this, "SchemaApiEndpoint", {
        value: `${this.api.url}schema`,
        description: "Schema API endpoint for Apex integration",
        exportName: `${this.stackName}-SchemaApiEndpoint`,
      });
    }

    // API Keys for authentication
    const userApiKey = this.api.addApiKey("UserApiKey", {
      apiKeyName: "salesforce-ai-search-user-key",
      description: "API key for user requests from Salesforce Named Credential",
    });

    const serviceApiKey = this.api.addApiKey("ServiceApiKey", {
      apiKeyName: "salesforce-ai-search-service-key",
      description: "API key for service requests (ingestion, batch operations)",
    });

    // Usage Plans
    const userUsagePlan = this.api.addUsagePlan("UserUsagePlan", {
      name: "salesforce-ai-search-user-plan",
      description: "Usage plan for user requests with rate limiting",
      throttle: {
        rateLimit: 100,
        burstLimit: 200,
      },
      quota: {
        limit: 10000,
        period: apigateway.Period.DAY,
      },
      apiStages: [
        {
          api: this.api,
          stage: this.api.deploymentStage,
        },
      ],
    });

    const serviceUsagePlan = this.api.addUsagePlan("ServiceUsagePlan", {
      name: "salesforce-ai-search-service-plan",
      description: "Usage plan for service requests with higher limits",
      throttle: {
        rateLimit: 50,
        burstLimit: 100,
      },
      quota: {
        limit: 50000,
        period: apigateway.Period.DAY,
      },
      apiStages: [
        {
          api: this.api,
          stage: this.api.deploymentStage,
        },
      ],
    });

    userUsagePlan.addApiKey(userApiKey);
    serviceUsagePlan.addApiKey(serviceApiKey);

    // Outputs
    new cdk.CfnOutput(this, "ApiId", {
      value: this.api.restApiId,
      description: "Private API Gateway ID",
      exportName: `${this.stackName}-ApiId`,
    });

    new cdk.CfnOutput(this, "UserApiKeyId", {
      value: userApiKey.keyId,
      description: "User API Key ID",
      exportName: `${this.stackName}-UserApiKeyId`,
    });

    new cdk.CfnOutput(this, "ServiceApiKeyId", {
      value: serviceApiKey.keyId,
      description: "Service API Key ID",
      exportName: `${this.stackName}-ServiceApiKeyId`,
    });

    new cdk.CfnOutput(this, "ApiEndpoint", {
      value: this.api.url,
      description: "Private API Gateway endpoint URL",
      exportName: `${this.stackName}-ApiEndpoint`,
    });

    new cdk.CfnOutput(this, "AuthzLambdaArn", {
      value: this.authzLambda.functionArn,
      description: "AuthZ Lambda ARN",
      exportName: `${this.stackName}-AuthzLambdaArn`,
    });

    new cdk.CfnOutput(this, "QueryFunctionUrl", {
      value: queryFunctionUrl.url,
      description: "Query Lambda Function URL (Streaming SSE)",
      exportName: `${this.stackName}-QueryFunctionUrl`,
    });

    // Tag all resources
    cdk.Tags.of(this).add("Component", "API");
  }
}
