import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as kms from "aws-cdk-lib/aws-kms";
import { Construct } from "constructs";

export class NetworkStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly lambdaSecurityGroup: ec2.SecurityGroup;
  public readonly kmsKey: kms.Key;
  public readonly opensearchVpcEndpointId: string;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // KMS Key for encryption at rest across all services
    this.kmsKey = new kms.Key(this, "EncryptionKey", {
      description: "KMS key for Salesforce AI Search POC encryption at rest",
      enableKeyRotation: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      alias: "salesforce-ai-search-poc",
    });

    // VPC with private subnets for Lambda functions
    this.vpc = new ec2.Vpc(this, "VPC", {
      maxAzs: 2,
      natGateways: 1, // Cost optimization for POC
      subnetConfiguration: [
        {
          name: "Private",
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
        {
          name: "Public",
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
      ],
      enableDnsHostnames: true,
      enableDnsSupport: true,
    });

    // Security Group for Lambda functions
    this.lambdaSecurityGroup = new ec2.SecurityGroup(
      this,
      "LambdaSecurityGroup",
      {
        vpc: this.vpc,
        description:
          "Security group for Lambda functions in Salesforce AI Search POC",
        allowAllOutbound: true,
      },
    );

    // VPC Endpoint for S3
    this.vpc.addGatewayEndpoint("S3Endpoint", {
      service: ec2.GatewayVpcEndpointAwsService.S3,
      subnets: [{ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }],
    });

    // VPC Endpoint for DynamoDB
    this.vpc.addGatewayEndpoint("DynamoDBEndpoint", {
      service: ec2.GatewayVpcEndpointAwsService.DYNAMODB,
      subnets: [{ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }],
    });

    // VPC Endpoint for Bedrock Runtime
    const bedrockEndpoint = new ec2.InterfaceVpcEndpoint(
      this,
      "BedrockRuntimeEndpoint",
      {
        vpc: this.vpc,
        service: new ec2.InterfaceVpcEndpointService(
          `com.amazonaws.${this.region}.bedrock-runtime`,
          443,
        ),
        privateDnsEnabled: true,
        subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        securityGroups: [this.lambdaSecurityGroup],
      },
    );

    // VPC Endpoint for Bedrock Agent Runtime
    const bedrockAgentEndpoint = new ec2.InterfaceVpcEndpoint(
      this,
      "BedrockAgentRuntimeEndpoint",
      {
        vpc: this.vpc,
        service: new ec2.InterfaceVpcEndpointService(
          `com.amazonaws.${this.region}.bedrock-agent-runtime`,
          443,
        ),
        privateDnsEnabled: true,
        subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        securityGroups: [this.lambdaSecurityGroup],
      },
    );

    // VPC Endpoint for OpenSearch Serverless
    const opensearchEndpoint = new ec2.InterfaceVpcEndpoint(
      this,
      "OpenSearchEndpoint",
      {
        vpc: this.vpc,
        service: new ec2.InterfaceVpcEndpointService(
          `com.amazonaws.${this.region}.aoss`,
          443,
        ),
        privateDnsEnabled: true,
        subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        securityGroups: [this.lambdaSecurityGroup],
      },
    );
    this.opensearchVpcEndpointId = opensearchEndpoint.vpcEndpointId;

    // Outputs
    new cdk.CfnOutput(this, "VpcId", {
      value: this.vpc.vpcId,
      description: "VPC ID",
      exportName: `${this.stackName}-VpcId`,
    });

    new cdk.CfnOutput(this, "KmsKeyId", {
      value: this.kmsKey.keyId,
      description: "KMS Key ID for encryption",
      exportName: `${this.stackName}-KmsKeyId`,
    });

    new cdk.CfnOutput(this, "KmsKeyArn", {
      value: this.kmsKey.keyArn,
      description: "KMS Key ARN for encryption",
      exportName: `${this.stackName}-KmsKeyArn`,
    });

    new cdk.CfnOutput(this, "LambdaSecurityGroupId", {
      value: this.lambdaSecurityGroup.securityGroupId,
      description: "Security Group ID for Lambda functions",
      exportName: `${this.stackName}-LambdaSecurityGroupId`,
    });

    // Tag all resources
    cdk.Tags.of(this).add("Component", "Network");
  }
}
