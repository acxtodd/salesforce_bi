import * as cdk from "aws-cdk-lib";
import * as opensearchserverless from "aws-cdk-lib/aws-opensearchserverless";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as kms from "aws-cdk-lib/aws-kms";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as bedrock from "aws-cdk-lib/aws-bedrock";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as cr from "aws-cdk-lib/custom-resources";
import * as path from "path";
import { Construct } from "constructs";

interface SearchStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  lambdaSecurityGroup: ec2.SecurityGroup;
  kmsKey: kms.Key;
  dataBucket: s3.Bucket;
  opensearchVpcEndpointId: string;
}

export class SearchStack extends cdk.Stack {
  public readonly collection: opensearchserverless.CfnCollection;
  public readonly knowledgeBase: bedrock.CfnKnowledgeBase;
  public readonly dataSource: bedrock.CfnDataSource;

  constructor(scope: Construct, id: string, props: SearchStackProps) {
    super(scope, id, props);

    const { vpc, lambdaSecurityGroup, kmsKey, dataBucket, opensearchVpcEndpointId } = props;

    // IAM role for Bedrock Knowledge Base
    // Defined early to use its ARN in access policies
    const knowledgeBaseRole = new iam.Role(this, "KnowledgeBaseRole", {
      assumedBy: new iam.ServicePrincipal("bedrock.amazonaws.com"),
      description:
        "Role for Bedrock Knowledge Base to access S3 and OpenSearch Serverless",
    });

    // Grant S3 permissions
    dataBucket.grantRead(knowledgeBaseRole);

    // Grant Bedrock model invocation permissions
    knowledgeBaseRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["bedrock:InvokeModel"],
        resources: [
          `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
        ],
      }),
    );

    // Grant OpenSearch Serverless permissions
    // CRITICAL: Need both control-plane AND data-plane actions
    // **Feature: graph-aware-zero-config-retrieval, Task 23.4**
    // **Requirements: 11.3 - IAM policies scoped to single collection/index**
    // NOTE: The collection ARN includes a UUID that isn't known until after creation.
    // CDK requires IAM policies to exist before the collection (for access policies).
    // This creates a deployment ordering constraint that requires wildcard here.
    // FUTURE: Post-deployment, tighten to specific collection ARN via separate update.
    knowledgeBaseRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "aoss:APIAccessAll", // Control plane
          "aoss:DashboardsAccessAll", // Dashboard access
          "aoss:BatchGetCollection", // Collection operations
          "aoss:CreateCollectionItems", // Collection items
          "aoss:UpdateCollectionItems",
          "aoss:DescribeCollectionItems",
          "aoss:ReadDocument", // Data plane read
          "aoss:WriteDocument", // Data plane write
        ],
        resources: [`arn:aws:aoss:${this.region}:${this.account}:collection/*`],
      }),
    );

    // Role for Index Creator Lambda
    const indexCreatorRole = new iam.Role(this, "IndexCreatorRole", {
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AWSLambdaVPCAccessExecutionRole",
        ),
      ],
    });

    // CRITICAL: Index creator needs comprehensive permissions
    // **Feature: graph-aware-zero-config-retrieval, Task 23.4**
    // **Requirements: 11.3 - IAM policies scoped to single collection/index**
    // NOTE: Same CDK ordering constraint as knowledgeBaseRole above.
    indexCreatorRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "aoss:APIAccessAll", // Control plane
          "aoss:DashboardsAccessAll", // Dashboard access
          "aoss:BatchGetCollection", // Collection operations
          "aoss:CreateCollectionItems", // Collection items
          "aoss:UpdateCollectionItems",
          "aoss:DescribeCollectionItems",
          "aoss:ReadDocument", // Data plane read
          "aoss:WriteDocument", // Data plane write
        ],
        resources: [`arn:aws:aoss:${this.region}:${this.account}:collection/*`],
      }),
    );

    // 1. VPC Endpoint for OpenSearch Serverless Collection
    // CRITICAL: Must be created BEFORE network policy references it
    const collectionVpcEndpoint = new opensearchserverless.CfnVpcEndpoint(
      this,
      "CollectionVpcEndpoint",
      {
        name: "salesforce-ai-search-vpce",
        vpcId: vpc.vpcId,
        subnetIds: vpc.privateSubnets.map((subnet) => subnet.subnetId),
        securityGroupIds: [lambdaSecurityGroup.securityGroupId],
      },
    );

    // 2. Encryption Policy
    // **Feature: graph-aware-zero-config-retrieval, Task 23.3**
    // **Requirements: 11.2 - AOSS encryption**
    // NOTE: AOSS encryption key cannot be changed after collection creation.
    // Current collection uses AWS-owned key. CMK migration requires:
    // 1. Create new collection with CMK encryption policy
    // 2. Recreate Bedrock Knowledge Base pointing to new collection
    // 3. Full re-index of all data
    // DECISION: Deferred to post-POC due to migration complexity.
    // See: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-encryption.html
    const encryptionPolicy = new opensearchserverless.CfnSecurityPolicy(
      this,
      "EncryptionPolicy",
      {
        name: "salesforce-ai-search-encryption",
        type: "encryption",
        policy: JSON.stringify({
          Rules: [
            {
              ResourceType: "collection",
              Resource: [`collection/salesforce-ai-search`],
            },
          ],
          AWSOwnedKey: true, // AWS-owned key for POC; CMK deferred to post-POC
        }),
      },
    );

    // 3. Network Policy (Private VPC Access)
    // CRITICAL: Must whitelist BOTH VPC endpoint AND bedrock.amazonaws.com service
    const networkPolicy = new opensearchserverless.CfnSecurityPolicy(
      this,
      "NetworkPolicy",
      {
        name: "salesforce-ai-search-network",
        type: "network",
        policy: JSON.stringify([
          {
            Description: "Private access for Bedrock and Lambda via VPC endpoint",
            Rules: [
              {
                ResourceType: "collection",
                Resource: [`collection/salesforce-ai-search`],
              },
              {
                ResourceType: "dashboard",
                Resource: [`collection/salesforce-ai-search`],
              },
            ],
            AllowFromPublic: false,
            SourceVPCEs: [collectionVpcEndpoint.attrId], // Reference the collection VPC endpoint
            SourceServices: ["bedrock.amazonaws.com"], // CRITICAL: Allow Bedrock service access
          },
        ]),
      },
    );

    // Network policy must wait for VPC endpoint to be created
    networkPolicy.node.addDependency(collectionVpcEndpoint);

    // 4. Access Policy (Data Access)
    // CRITICAL: Must include BOTH collection-level AND index-level permissions
    // **Security Fix: graph-aware-zero-config-retrieval, Task 23 - QA Finding #4**
    // Removed account root principal - only service roles should have access
    const accessPolicy = new opensearchserverless.CfnAccessPolicy(
      this,
      "AccessPolicy",
      {
        name: "salesforce-ai-search-access",
        type: "data",
        policy: JSON.stringify([
          {
            Rules: [
              {
                ResourceType: "collection",
                Resource: [`collection/salesforce-ai-search`],
                Permission: [
                  "aoss:CreateCollectionItems",
                  "aoss:DeleteCollectionItems",
                  "aoss:UpdateCollectionItems",
                  "aoss:DescribeCollectionItems",
                ],
              },
              {
                ResourceType: "index",
                Resource: [`index/salesforce-ai-search/*`],
                Permission: [
                  "aoss:CreateIndex",
                  "aoss:DeleteIndex",
                  "aoss:UpdateIndex",
                  "aoss:DescribeIndex",
                  "aoss:ReadDocument", // CRITICAL: Data-plane read
                  "aoss:WriteDocument", // CRITICAL: Data-plane write
                ],
              },
            ],
            Principal: [
              knowledgeBaseRole.roleArn,
              indexCreatorRole.roleArn,
              // NOTE: Account root principal removed for security (Req 11.3)
              // For debugging, add your IAM role ARN temporarily if needed
            ],
          },
        ]),
      },
    );

    // 5. OpenSearch Serverless Collection
    // Configured for minimum cost: 1 OCU (2 half-OCUs) ≈ $175/month for POC
    this.collection = new opensearchserverless.CfnCollection(
      this,
      "Collection",
      {
        name: "salesforce-ai-search",
        type: "VECTORSEARCH",
        description: "Vector collection for Salesforce AI Search POC - Private VPC access",
        // Note: Standby replicas disabled for POC to minimize cost (1 OCU minimum)
        // For production, enable standby replicas for HA
      },
    );

    // Ensure policies and VPC endpoint are created before collection
    this.collection.node.addDependency(encryptionPolicy);
    this.collection.node.addDependency(networkPolicy);
    this.collection.node.addDependency(accessPolicy);
    this.collection.node.addDependency(collectionVpcEndpoint);

    // 6. Index Creator Lambda & Custom Resource
    // CRITICAL: Vector index must be created before Bedrock KB can sync data
    const indexCreator = new lambda.Function(this, "IndexCreator", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromAsset(
        path.join(__dirname, "../lambda/index-creator"),
      ),
      role: indexCreatorRole,
      vpc: vpc,
      securityGroups: [lambdaSecurityGroup],
      timeout: cdk.Duration.minutes(5),
      environment: {
        COLLECTION_ENDPOINT: this.collection.attrCollectionEndpoint,
        INDEX_NAME: "salesforce-chunks",
      },
    });

    const indexProvider = new cr.Provider(this, "IndexProvider", {
      onEventHandler: indexCreator,
    });

    const indexResource = new cdk.CustomResource(this, "IndexResource", {
      serviceToken: indexProvider.serviceToken,
      properties: {
        endpoint: this.collection.attrCollectionEndpoint,
        indexName: "salesforce-chunks",
        // Trigger recreation if collection changes
        collectionArn: this.collection.attrArn,
      },
    });

    // Index creation must wait for collection and access policy
    indexResource.node.addDependency(this.collection);
    indexResource.node.addDependency(accessPolicy);

    // 7. Bedrock Knowledge Base
    // Configured for private access via OpenSearch Serverless with VPC endpoint
    this.knowledgeBase = new bedrock.CfnKnowledgeBase(this, "KnowledgeBase", {
      name: "salesforce-ai-search-kb",
      description:
        "Knowledge Base for Salesforce AI Search POC - Private VPC access via OpenSearch Serverless",
      roleArn: knowledgeBaseRole.roleArn,

      knowledgeBaseConfiguration: {
        type: "VECTOR",
        vectorKnowledgeBaseConfiguration: {
          embeddingModelArn: `arn:aws:bedrock:${this.region}::foundation-model/amazon.titan-embed-text-v2:0`,
        },
      },

      storageConfiguration: {
        type: "OPENSEARCH_SERVERLESS",
        opensearchServerlessConfiguration: {
          collectionArn: this.collection.attrArn,
          vectorIndexName: "salesforce-chunks",
          fieldMapping: {
            vectorField: "embedding",
            textField: "text",
            metadataField: "metadata",
          },
        },
      },
    });

    // CRITICAL: KB must wait for role, collection, index, and network policy
    // Network policy with bedrock.amazonaws.com service allows Bedrock to access collection
    this.knowledgeBase.node.addDependency(knowledgeBaseRole);
    this.knowledgeBase.node.addDependency(this.collection);
    this.knowledgeBase.node.addDependency(indexResource);
    this.knowledgeBase.node.addDependency(networkPolicy);

    // 8. S3 Data Source
    this.dataSource = new bedrock.CfnDataSource(this, "DataSource", {
      name: "salesforce-data-source",
      description: "S3 data source for Salesforce chunked documents",
      knowledgeBaseId: this.knowledgeBase.attrKnowledgeBaseId,

      dataSourceConfiguration: {
        type: "S3",
        s3Configuration: {
          bucketArn: dataBucket.bucketArn,
          inclusionPrefixes: ["chunks/"],
        },
      },

      vectorIngestionConfiguration: {
        chunkingConfiguration: {
          chunkingStrategy: "NONE", // We handle chunking in Lambda
        },
      },
    });

    // Outputs
    new cdk.CfnOutput(this, "CollectionVpcEndpointId", {
      value: collectionVpcEndpoint.attrId,
      description: "OpenSearch Serverless Collection VPC Endpoint ID",
      exportName: `${this.stackName}-CollectionVpcEndpointId`,
    });

    new cdk.CfnOutput(this, "CollectionEndpoint", {
      value: this.collection.attrCollectionEndpoint,
      description: "OpenSearch Serverless Collection Endpoint",
      exportName: `${this.stackName}-CollectionEndpoint`,
    });

    new cdk.CfnOutput(this, "CollectionArn", {
      value: this.collection.attrArn,
      description: "OpenSearch Serverless Collection ARN",
      exportName: `${this.stackName}-CollectionArn`,
    });

    new cdk.CfnOutput(this, "KnowledgeBaseId", {
      value: this.knowledgeBase.attrKnowledgeBaseId,
      description: "Bedrock Knowledge Base ID",
      exportName: `${this.stackName}-KnowledgeBaseId`,
    });

    new cdk.CfnOutput(this, "KnowledgeBaseArn", {
      value: this.knowledgeBase.attrKnowledgeBaseArn,
      description: "Bedrock Knowledge Base ARN",
      exportName: `${this.stackName}-KnowledgeBaseArn`,
    });

    new cdk.CfnOutput(this, "DataSourceId", {
      value: this.dataSource.attrDataSourceId,
      description: "Bedrock Data Source ID",
      exportName: `${this.stackName}-DataSourceId`,
    });

    // Tag all resources
    cdk.Tags.of(this).add("Component", "Search");
  }
}
