import * as cdk from "aws-cdk-lib";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as kms from "aws-cdk-lib/aws-kms";
import * as iam from "aws-cdk-lib/aws-iam";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as logs from "aws-cdk-lib/aws-logs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as cr from "aws-cdk-lib/custom-resources";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
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
  telemetryTable: dynamodb.Table;
  sessionsTable: dynamodb.Table;
  authzCacheTable: dynamodb.Table;
  rateLimitsTable: dynamodb.Table;
  actionMetadataTable: dynamodb.Table;
  knowledgeBaseId: string;
  ingestLambda: lambda.Function;
  // Phase 3: Graph Enhancement tables
  graphNodesTable: dynamodb.Table;
  graphEdgesTable: dynamodb.Table;
  graphPathCacheTable: dynamodb.Table;
  dataBucket: cdk.aws_s3.Bucket;
  // Zero-Config Schema Discovery table
  schemaCacheTable?: dynamodb.Table;
}

export class ApiStack extends cdk.Stack {
  public readonly api: apigateway.RestApi;
  public readonly retrieveLambda: lambda.Function;
  public readonly answerLambda: lambda.Function;
  public readonly queryLambda: lambda.DockerImageFunction;
  public readonly authzLambda: lambda.Function;
  public readonly actionLambda: lambda.Function;
  public readonly vpcEndpoint: ec2.InterfaceVpcEndpoint;
  public readonly vpcEndpointService: ec2.VpcEndpointService;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const {
      vpc,
      lambdaSecurityGroup,
      kmsKey,
      telemetryTable,
      sessionsTable,
      authzCacheTable,
      rateLimitsTable,
      actionMetadataTable,
      knowledgeBaseId,
      ingestLambda,
      graphNodesTable,
      graphEdgesTable,
      graphPathCacheTable,
      dataBucket,
      schemaCacheTable,
    } = props;

    // -------------------------------------------------------------------------
    // 1. API Gateway Private Link (Interface VPC Endpoint)
    // -------------------------------------------------------------------------

    // Security Group for API Gateway VPC Endpoint
    const vpcEndpointSecurityGroup = new ec2.SecurityGroup(
      this,
      "VpcEndpointSecurityGroup",
      {
        vpc,
        description: "Security group for API Gateway VPC endpoint",
        allowAllOutbound: true,
      },
    );

    vpcEndpointSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(443),
      "Allow HTTPS from VPC",
    );

    vpcEndpointSecurityGroup.addIngressRule(
      lambdaSecurityGroup,
      ec2.Port.tcp(443),
      "Allow HTTPS from Lambda functions",
    );

    this.vpcEndpoint = new ec2.InterfaceVpcEndpoint(
      this,
      "ApiGatewayVpcEndpoint",
      {
        vpc,
        service: new ec2.InterfaceVpcEndpointService(
          `com.amazonaws.${this.region}.execute-api`,
          443,
        ),
        privateDnsEnabled: true,
        subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        securityGroups: [vpcEndpointSecurityGroup],
      },
    );

    // -------------------------------------------------------------------------
    // 2. Network Load Balancer & VPC Endpoint Service (for Private Connect)
    // -------------------------------------------------------------------------

    // Network Load Balancer (Internal)
    const nlb = new elbv2.NetworkLoadBalancer(this, "PrivateLinkNLB", {
      vpc,
      internetFacing: false,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
    });

    // Target Group for NLB - Targets are the IPs of the VPC Endpoint
    const targetGroup = new elbv2.NetworkTargetGroup(
      this,
      "PrivateLinkTargetGroup",
      {
        vpc,
        port: 443,
        protocol: elbv2.Protocol.TCP,
        targetType: elbv2.TargetType.IP,
        healthCheck: {
          protocol: elbv2.Protocol.TCP,
          enabled: true,
        },
      },
    );

    const listener = nlb.addListener("PrivateLinkListener", {
      port: 443,
      defaultAction: elbv2.NetworkListenerAction.forward([targetGroup]),
    });

    // Custom Resource to find ENI IPs of the Interface Endpoint
    // Kept for output reference, but not used for registration automatically
    const getEndpointIpsParams: cr.AwsSdkCall = {
      service: "EC2",
      action: "describeNetworkInterfaces",
      parameters: {
        NetworkInterfaceIds: this.vpcEndpoint.vpcEndpointNetworkInterfaceIds,
      },
      physicalResourceId: cr.PhysicalResourceId.of("ApiGatewayEndpointIps"),
    };

    const getEndpointIps = new cr.AwsCustomResource(this, "GetEndpointIps", {
      onCreate: getEndpointIpsParams,
      onUpdate: getEndpointIpsParams,
      policy: cr.AwsCustomResourcePolicy.fromSdkCalls({
        resources: cr.AwsCustomResourcePolicy.ANY_RESOURCE,
      }),
    });

    // MANUAL STEP REQUIRED: Register targets
    // The automated registration via AwsCustomResource failed due to SDK module resolution issues.
    // User must manually register the IPs of 'ApiGatewayVpcEndpoint' to 'PrivateLinkTargetGroup'.

    // Create VPC Endpoint Service pointing to the NLB
    this.vpcEndpointService = new ec2.VpcEndpointService(
      this,
      "SalesforceEndpointService",
      {
        vpcEndpointServiceLoadBalancers: [nlb],
        acceptanceRequired: true,
        allowedPrincipals: [
          new iam.ArnPrincipal(`arn:aws:iam::${this.account}:root`),
        ],
      },
    );

    // -------------------------------------------------------------------------
    // 3. Lambda Roles & Functions
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
            // Claude models (inference profiles)
            `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
            // Foundation models (for direct invocation — use * region for cross-region inference profiles)
            `arn:aws:bedrock:*::foundation-model/anthropic.claude-*`,
            `arn:aws:bedrock:*::foundation-model/us.anthropic.claude-*`,
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

    // 2. Retrieve Lambda Role
    const retrieveRole = createLambdaRole(
      "RetrieveLambdaRole",
      "Role for Retrieve Lambda",
    );
    telemetryTable.grantReadWriteData(retrieveRole);

    // Phase 3: Grant access to graph tables for relationship queries
    graphNodesTable.grantReadData(retrieveRole);
    graphEdgesTable.grantReadData(retrieveRole);
    graphPathCacheTable.grantReadWriteData(retrieveRole);
    dataBucket.grantRead(retrieveRole);

    // -------------------------------------------------------------------------
    // Schema Discovery Lambda Layer
    // -------------------------------------------------------------------------
    // **Feature: zero-config-production, Task 27.1**
    // Shared Lambda Layer for schema_discovery module to avoid code duplication
    // across retrieve, graph_builder, and other lambdas that need schema access.
    //
    // The layer is structured as:
    //   /opt/python/schema_discovery/__init__.py
    //   /opt/python/schema_discovery/models.py
    //   /opt/python/schema_discovery/cache.py
    //   /opt/python/schema_discovery/discoverer.py
    //   /opt/python/schema_discovery/index.py
    //
    // Note: The layer directory must be pre-built with the correct structure.
    // Use: lambda/layers/schema_discovery/python/schema_discovery/
    const schemaDiscoveryLayer = new lambda.LayerVersion(
      this,
      "SchemaDiscoveryLayer",
      {
        layerVersionName: "salesforce-ai-search-schema-discovery",
        description: "Shared schema discovery module for Salesforce AI Search",
        code: lambda.Code.fromAsset(
          path.join(__dirname, "../lambda/layers/schema_discovery"),
          { exclude: LAMBDA_ASSET_EXCLUDES },
        ),
        compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
        compatibleArchitectures: [
          lambda.Architecture.X86_64,
          lambda.Architecture.ARM_64,
        ],
      },
    );

    // Retrieve Lambda
    this.retrieveLambda = new lambda.Function(this, "RetrieveLambda", {
      functionName: "salesforce-ai-search-retrieve",
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: "index.lambda_handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../lambda/retrieve"), { exclude: LAMBDA_ASSET_EXCLUDES }),
      timeout: cdk.Duration.seconds(29),
      memorySize: 1024,
      role: retrieveRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      // **Feature: zero-config-production, Task 27.1**
      // Use shared schema_discovery layer instead of copied module
      layers: [schemaDiscoveryLayer],
      environment: {
        AUTHZ_LAMBDA_FUNCTION_NAME: this.authzLambda.functionName,
        KNOWLEDGE_BASE_ID: knowledgeBaseId,
        TELEMETRY_TABLE_NAME: telemetryTable.tableName,
        DEFAULT_TOP_K: "15",
        MAX_TOP_K: "25",
        CACHE_TTL_SECONDS: "60",
        CACHE_MAX_SIZE: "100",
        LOG_LEVEL: "INFO",
        // Phase 3: Graph Enhancement tables
        GRAPH_NODES_TABLE: graphNodesTable.tableName,
        GRAPH_EDGES_TABLE: graphEdgesTable.tableName,
        GRAPH_PATH_CACHE_TABLE: graphPathCacheTable.tableName,
        DATA_BUCKET: dataBucket.bucketName,
        // Phase 3: Feature flags
        INTENT_ROUTING_ENABLED: "true",
        GRAPH_ROUTING_ENABLED: "true",
        INTENT_LOGGING_ENABLED: "true",
        // Zero-Config Schema Discovery
        SCHEMA_CACHE_TABLE:
          schemaCacheTable?.tableName || "salesforce-ai-search-schema-cache",
        SCHEMA_FILTER_ENABLED: "true",
      },
    });

    // Grant Retrieve Lambda read access to schema cache table
    if (schemaCacheTable) {
      schemaCacheTable.grantReadData(this.retrieveLambda);
    }

    const retrieveVersion = this.retrieveLambda.currentVersion;
    const retrieveAlias = new lambda.Alias(this, "RetrieveLambdaAlias", {
      aliasName: "live",
      version: retrieveVersion,
      provisionedConcurrentExecutions: 5,
    });

    // Grant permissions
    this.authzLambda.grantInvoke(this.retrieveLambda); // Retrieve invokes AuthZ

    // 3. Answer Lambda Role
    const answerRole = createLambdaRole(
      "AnswerLambdaRole",
      "Role for Answer Lambda",
    );
    sessionsTable.grantReadWriteData(answerRole);

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

    // Answer Lambda
    this.answerLambda = new lambda.DockerImageFunction(this, "AnswerLambda", {
      functionName: "salesforce-ai-search-answer-docker",
      code: lambda.DockerImageCode.fromImageAsset(
        path.join(__dirname, "../lambda/answer"),
      ),
      timeout: cdk.Duration.seconds(29),
      memorySize: 2048,
      architecture: lambda.Architecture.ARM_64, // Critical for Mac M1/M2 builds
      role: answerRole,
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [lambdaSecurityGroup],
      environment: {
        AWS_LWA_INVOKE_MODE: "RESPONSE_STREAM",
        RETRIEVE_LAMBDA_FUNCTION_NAME: this.retrieveLambda.functionName,
        SESSIONS_TABLE_NAME: sessionsTable.tableName,
        BEDROCK_MODEL_ID:
          "arn:aws:bedrock:us-west-2:382211616288:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        BEDROCK_GUARDRAIL_ID: process.env.BEDROCK_GUARDRAIL_ID || "",
        BEDROCK_GUARDRAIL_VERSION: "DRAFT",
        DEFAULT_TOP_K: "15",
        MAX_TOP_K: "25",
        DEFAULT_MAX_TOKENS: "600",
        DEFAULT_TEMPERATURE: "0.3",
        LOG_LEVEL: "INFO",
        // **Feature: zero-config-production, Task 28.1**
        // API key now retrieved from Secrets Manager at runtime
        API_KEY_SECRET_ARN: streamingApiKeySecret.secretArn,
      },
    });

    // Grant Answer Lambda permission to read the API key secret
    streamingApiKeySecret.grantRead(this.answerLambda);

    // Enable Function URL for Streaming
    // **SECURITY WARNING - QA Finding #1 (graph-aware-zero-config-retrieval, Task 23)**
    // This Function URL bypasses API Gateway and API key enforcement.
    // Risk: Public, unauthenticated endpoint (authType: NONE, CORS: *)
    // Mitigation: Application-level API key validation in Answer Lambda (fail-closed)
    // Status: DEFERRED for post-POC - needed for streaming responses to LWC
    // Production: Should use CloudFront + OAC, or WebSocket API Gateway
    // See: Requirement 11.1 - "no public Function URLs"
    const answerFunctionUrl = this.answerLambda.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE, // TODO: Switch to AWS_IAM with CloudFront OAC
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
      cors: {
        allowedOrigins: ["*"], // TODO: Restrict to Salesforce domains in production
        allowedMethods: [lambda.HttpMethod.POST],
        allowedHeaders: ["*"], // TODO: Restrict to required headers in production
      },
    });

    const answerVersion = this.answerLambda.currentVersion;
    const answerAlias = new lambda.Alias(this, "AnswerLambdaAlias", {
      aliasName: "live",
      version: answerVersion,
      // provisionedConcurrentExecutions: 5, // Removed to fix deployment failure
    });

    // Grant permissions
    this.retrieveLambda.grantInvoke(this.answerLambda); // Answer invokes Retrieve

    // 3b. Query Lambda (Phase 2: Turbopuffer + tool-use via /query endpoint)
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
        BEDROCK_MODEL_ID:
          "us.anthropic.claude-sonnet-4-20250514-v1:0",
        TURBOPUFFER_API_KEY: turbopufferApiKeySecret.secretValue.unsafeUnwrap(),
        LOG_LEVEL: "INFO",
        // Reuse same API key secret as answer Lambda for auth parity
        API_KEY_SECRET_ARN: streamingApiKeySecret.secretArn,
      },
    });

    // Grant Query Lambda permission to read the Turbopuffer + streaming API key secrets
    turbopufferApiKeySecret.grantRead(queryRole);
    streamingApiKeySecret.grantRead(this.queryLambda);

    const queryFunctionUrl = this.queryLambda.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
      cors: {
        allowedOrigins: ["*"],
        allowedMethods: [lambda.HttpMethod.POST],
        allowedHeaders: ["*"],
      },
    });

    // 4. Action Lambda Role
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

    // Request/Response models for validation
    const retrieveRequestModel = this.api.addModel("RetrieveRequestModel", {
      contentType: "application/json",
      modelName: "RetrieveRequest",
      schema: {
        type: apigateway.JsonSchemaType.OBJECT,
        required: ["query", "salesforceUserId"],
        properties: {
          query: { type: apigateway.JsonSchemaType.STRING },
          salesforceUserId: { type: apigateway.JsonSchemaType.STRING },
          topK: { type: apigateway.JsonSchemaType.INTEGER },
          filters: { type: apigateway.JsonSchemaType.OBJECT },
          recordContext: { type: apigateway.JsonSchemaType.OBJECT },
          hybrid: { type: apigateway.JsonSchemaType.BOOLEAN },
          authzMode: { type: apigateway.JsonSchemaType.STRING },
        },
      },
    });

    const answerRequestModel = this.api.addModel("AnswerRequestModel", {
      contentType: "application/json",
      modelName: "AnswerRequest",
      schema: {
        type: apigateway.JsonSchemaType.OBJECT,
        required: ["query", "salesforceUserId"],
        properties: {
          query: { type: apigateway.JsonSchemaType.STRING },
          salesforceUserId: { type: apigateway.JsonSchemaType.STRING },
          sessionId: { type: apigateway.JsonSchemaType.STRING },
          topK: { type: apigateway.JsonSchemaType.INTEGER },
          recordContext: { type: apigateway.JsonSchemaType.OBJECT },
          policy: { type: apigateway.JsonSchemaType.OBJECT },
        },
      },
    });

    // /retrieve endpoint
    const retrieveResource = this.api.root.addResource("retrieve");
    retrieveResource.addMethod(
      "POST",
      new apigateway.LambdaIntegration(retrieveAlias, {
        proxy: true,
        timeout: cdk.Duration.seconds(29),
      }),
      {
        apiKeyRequired: true,
        requestValidator: new apigateway.RequestValidator(
          this,
          "RetrieveRequestValidator",
          {
            restApi: this.api,
            validateRequestBody: true,
            validateRequestParameters: false,
          },
        ),
        requestModels: {
          "application/json": retrieveRequestModel,
        },
      },
    );

    // /answer endpoint
    const answerResource = this.api.root.addResource("answer");
    answerResource.addMethod(
      "POST",
      new apigateway.LambdaIntegration(answerAlias, {
        proxy: true,
        timeout: cdk.Duration.seconds(29),
      }),
      {
        apiKeyRequired: true,
        requestValidator: new apigateway.RequestValidator(
          this,
          "AnswerRequestValidator",
          {
            restApi: this.api,
            validateRequestBody: true,
            validateRequestParameters: false,
          },
        ),
        requestModels: {
          "application/json": answerRequestModel,
        },
      },
    );

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

    // CloudWatch Alarms
    new cdk.aws_cloudwatch.Alarm(
      this,
      "RetrieveProvisionedConcurrencyUtilization",
      {
        alarmName: "salesforce-ai-search-retrieve-provisioned-utilization",
        alarmDescription:
          "Alert when Retrieve Lambda provisioned concurrency utilization is high",
        metric: new cdk.aws_cloudwatch.Metric({
          namespace: "AWS/Lambda",
          metricName: "ProvisionedConcurrencyUtilization",
          dimensionsMap: {
            FunctionName: this.retrieveLambda.functionName,
            Resource: `${this.retrieveLambda.functionName}:live`,
          },
          statistic: "Average",
          period: cdk.Duration.minutes(5),
        }),
        threshold: 0.8,
        evaluationPeriods: 2,
        comparisonOperator:
          cdk.aws_cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cdk.aws_cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );

    /*
    new cdk.aws_cloudwatch.Alarm(this, 'AnswerProvisionedConcurrencyUtilization', {
      alarmName: 'salesforce-ai-search-answer-provisioned-utilization',
      alarmDescription: 'Alert when Answer Lambda provisioned concurrency utilization is high',
      metric: new cdk.aws_cloudwatch.Metric({
        namespace: 'AWS/Lambda',
        metricName: 'ProvisionedConcurrencyUtilization',
        dimensionsMap: {
          FunctionName: this.answerLambda.functionName,
          Resource: `${this.answerLambda.functionName}:live`,
        },
        statistic: 'Average',
        period: cdk.Duration.minutes(5),
      }),
      threshold: 0.8,
      evaluationPeriods: 2,
      comparisonOperator: cdk.aws_cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cdk.aws_cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    */

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

    new cdk.CfnOutput(this, "RetrieveLambdaArn", {
      value: this.retrieveLambda.functionArn,
      description: "Retrieve Lambda ARN",
      exportName: `${this.stackName}-RetrieveLambdaArn`,
    });

    new cdk.CfnOutput(this, "AnswerLambdaArn", {
      value: this.answerLambda.functionArn,
      description: "Answer Lambda ARN",
      exportName: `${this.stackName}-AnswerLambdaArn`,
    });

    new cdk.CfnOutput(this, "AuthzLambdaArn", {
      value: this.authzLambda.functionArn,
      description: "AuthZ Lambda ARN",
      exportName: `${this.stackName}-AuthzLambdaArn`,
    });

    new cdk.CfnOutput(this, "AnswerFunctionUrl", {
      value: answerFunctionUrl.url,
      description: "Answer Lambda Function URL (Streaming)",
      exportName: `${this.stackName}-AnswerFunctionUrl`,
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
