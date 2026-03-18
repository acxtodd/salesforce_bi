import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

interface DataStackProps extends cdk.StackProps {
  vpc: ec2.Vpc;
  kmsKey: kms.Key;
}

export class DataStack extends cdk.Stack {
  public readonly dataBucket: s3.Bucket;
  public readonly embeddingsBucket: s3.Bucket;
  public readonly auditBucket: s3.Bucket;
  public readonly logsBucket: s3.Bucket;
  public readonly telemetryTable: dynamodb.Table;
  public readonly sessionsTable: dynamodb.Table;
  public readonly authzCacheTable: dynamodb.Table;
  public readonly rateLimitsTable: dynamodb.Table;
  public readonly actionMetadataTable: dynamodb.Table;
  // Phase 3: Graph Enhancement tables
  public readonly graphNodesTable: dynamodb.Table;
  public readonly graphEdgesTable: dynamodb.Table;
  public readonly graphPathCacheTable: dynamodb.Table;
  public readonly intentClassificationLogTable: dynamodb.Table;
  // Zero-Config Schema Discovery table
  public readonly schemaCacheTable: dynamodb.Table;
  // Graph-Aware Zero-Config Retrieval: Derived View tables
  public readonly availabilityViewTable: dynamodb.Table;
  public readonly vacancyViewTable: dynamodb.Table;
  public readonly leasesViewTable: dynamodb.Table;
  public readonly activitiesAggTable: dynamodb.Table;
  public readonly salesViewTable: dynamodb.Table;
  public readonly vocabCacheTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);

    const { vpc, kmsKey } = props;

    // S3 Bucket for logs (must be created first for access logging)
    this.logsBucket = new s3.Bucket(this, 'LogsBucket', {
      bucketName: `salesforce-ai-search-logs-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: kmsKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: false,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      lifecycleRules: [
        {
          id: 'TransitionToIA',
          transitions: [
            {
              storageClass: s3.StorageClass.INFREQUENT_ACCESS,
              transitionAfter: cdk.Duration.days(30),
            },
          ],
        },
        {
          id: 'TransitionToGlacier',
          transitions: [
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
        },
        {
          id: 'ExpireOldLogs',
          expiration: cdk.Duration.days(365),
        },
      ],
    });

    // S3 Bucket for data storage (chunked documents)
    this.dataBucket = new s3.Bucket(this, 'DataBucket', {
      bucketName: `salesforce-ai-search-data-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: kmsKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      serverAccessLogsBucket: this.logsBucket,
      serverAccessLogsPrefix: 'data-bucket-access-logs/',
      lifecycleRules: [
        {
          id: 'TransitionOldVersions',
          noncurrentVersionTransitions: [
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
        },
        {
          id: 'ExpireOldVersions',
          noncurrentVersionExpiration: cdk.Duration.days(365),
        },
      ],
    });

    // S3 Bucket for embeddings
    this.embeddingsBucket = new s3.Bucket(this, 'EmbeddingsBucket', {
      bucketName: `salesforce-ai-search-embeddings-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: kmsKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: false,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      serverAccessLogsBucket: this.logsBucket,
      serverAccessLogsPrefix: 'embeddings-bucket-access-logs/',
      lifecycleRules: [
        {
          id: 'TransitionToIA',
          transitions: [
            {
              storageClass: s3.StorageClass.INTELLIGENT_TIERING,
              transitionAfter: cdk.Duration.days(30),
            },
          ],
        },
      ],
    });

    // S3 Bucket for audit trail (document snapshots + config provenance)
    this.auditBucket = new s3.Bucket(this, 'AuditBucket', {
      bucketName: `salesforce-ai-search-audit-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: kmsKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      serverAccessLogsBucket: this.logsBucket,
      serverAccessLogsPrefix: 'audit-bucket-access-logs/',
      lifecycleRules: [
        {
          id: 'TransitionNoncurrentToGlacier',
          noncurrentVersionTransitions: [
            {
              storageClass: s3.StorageClass.GLACIER,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
        },
        {
          id: 'ExpireNoncurrentVersions',
          noncurrentVersionExpiration: cdk.Duration.days(365),
        },
      ],
    });

    // DynamoDB Table for telemetry
    this.telemetryTable = new dynamodb.Table(this, 'TelemetryTable', {
      tableName: 'salesforce-ai-search-telemetry',
      partitionKey: {
        name: 'requestId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.NUMBER,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      timeToLiveAttribute: 'ttl',
    });

    // GSI for querying by user
    this.telemetryTable.addGlobalSecondaryIndex({
      indexName: 'salesforceUserId-timestamp-index',
      partitionKey: {
        name: 'salesforceUserId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.NUMBER,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // DynamoDB Table for sessions
    this.sessionsTable = new dynamodb.Table(this, 'SessionsTable', {
      tableName: 'salesforce-ai-search-sessions',
      partitionKey: {
        name: 'sessionId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'turnNumber',
        type: dynamodb.AttributeType.NUMBER,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      timeToLiveAttribute: 'ttl',
    });

    // GSI for querying sessions by user
    this.sessionsTable.addGlobalSecondaryIndex({
      indexName: 'salesforceUserId-timestamp-index',
      partitionKey: {
        name: 'salesforceUserId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.NUMBER,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // DynamoDB Table for AuthZ cache
    this.authzCacheTable = new dynamodb.Table(this, 'AuthzCacheTable', {
      tableName: 'salesforce-ai-search-authz-cache',
      partitionKey: {
        name: 'salesforceUserId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      timeToLiveAttribute: 'ttl',
    });

    // DynamoDB Table for rate limits (Phase 2)
    this.rateLimitsTable = new dynamodb.Table(this, 'RateLimitsTable', {
      tableName: 'salesforce-ai-search-rate-limits',
      partitionKey: {
        name: 'userId_actionName_date',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      timeToLiveAttribute: 'ttl',
    });

    // DynamoDB Table for action metadata (Phase 2)
    this.actionMetadataTable = new dynamodb.Table(this, 'ActionMetadataTable', {
      tableName: 'salesforce-ai-search-action-metadata',
      partitionKey: {
        name: 'actionName',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // =========================================================================
    // Phase 3: Graph Enhancement Tables
    // =========================================================================

    // DynamoDB Table for graph nodes
    // Stores Salesforce records as graph nodes with key attributes
    this.graphNodesTable = new dynamodb.Table(this, 'GraphNodesTable', {
      tableName: 'salesforce-ai-search-graph-nodes',
      partitionKey: {
        name: 'nodeId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      timeToLiveAttribute: 'ttl',
    });

    // GSI for querying nodes by object type and creation time
    this.graphNodesTable.addGlobalSecondaryIndex({
      indexName: 'type-createdAt-index',
      partitionKey: {
        name: 'type',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'createdAt',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // DynamoDB Table for graph edges
    // Stores relationships between Salesforce records
    this.graphEdgesTable = new dynamodb.Table(this, 'GraphEdgesTable', {
      tableName: 'salesforce-ai-search-graph-edges',
      partitionKey: {
        name: 'fromId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'toIdType',  // Composite key: toId#type for uniqueness
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // GSI for reverse traversal (find edges pointing TO a node)
    this.graphEdgesTable.addGlobalSecondaryIndex({
      indexName: 'toId-index',
      partitionKey: {
        name: 'toId',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'fromId',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // DynamoDB Table for graph path cache
    // Caches frequently accessed traversal paths (5-minute TTL)
    this.graphPathCacheTable = new dynamodb.Table(this, 'GraphPathCacheTable', {
      tableName: 'salesforce-ai-search-graph-path-cache',
      partitionKey: {
        name: 'pathKey',  // Hash of start node + relationship pattern + userId
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      removalPolicy: cdk.RemovalPolicy.DESTROY,  // Cache can be destroyed safely
      timeToLiveAttribute: 'ttl',  // 5-minute TTL for cache entries
    });

    // DynamoDB Table for intent classification logging
    // Logs query intent classifications for monitoring and improvement
    this.intentClassificationLogTable = new dynamodb.Table(this, 'IntentClassificationLogTable', {
      tableName: 'salesforce-ai-search-intent-classification-log',
      partitionKey: {
        name: 'requestId',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      removalPolicy: cdk.RemovalPolicy.DESTROY,  // Logs can be destroyed safely
      timeToLiveAttribute: 'ttl',  // 30-day TTL for log entries
    });

    // GSI for querying intent logs by intent type and timestamp
    this.intentClassificationLogTable.addGlobalSecondaryIndex({
      indexName: 'intent-timestamp-index',
      partitionKey: {
        name: 'intent',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'timestamp',
        type: dynamodb.AttributeType.NUMBER,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // =========================================================================
    // Zero-Config Schema Discovery Table
    // =========================================================================

    // DynamoDB Table for schema cache
    // Stores discovered Salesforce object schemas for fast query-time lookup
    // **Feature: zero-config-schema-discovery**
    // **Requirements: 1.6, 1.7**
    this.schemaCacheTable = new dynamodb.Table(this, 'SchemaCacheTable', {
      tableName: 'salesforce-ai-search-schema-cache',
      partitionKey: {
        name: 'objectApiName',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      timeToLiveAttribute: 'ttl',  // 24-hour TTL for schema entries
    });

    // =========================================================================
    // Graph-Aware Zero-Config Retrieval: Derived View Tables
    // =========================================================================

    // DynamoDB Table for availability_view
    // Stores denormalized availability data with property attributes
    // **Feature: graph-aware-zero-config-retrieval**
    // **Requirements: 5.1**
    this.availabilityViewTable = new dynamodb.Table(this, 'AvailabilityViewTable', {
      tableName: 'salesforce-ai-search-availability-view',
      partitionKey: {
        name: 'property_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'availability_id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // DynamoDB Table for vacancy_view
    // Stores vacancy percentage and available sqft per property
    // **Feature: graph-aware-zero-config-retrieval**
    // **Requirements: 5.2**
    this.vacancyViewTable = new dynamodb.Table(this, 'VacancyViewTable', {
      tableName: 'salesforce-ai-search-vacancy-view',
      partitionKey: {
        name: 'property_id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // GSI for querying by vacancy percentage
    this.vacancyViewTable.addGlobalSecondaryIndex({
      indexName: 'vacancy-pct-index',
      partitionKey: {
        name: 'vacancy_pct_bucket',  // Bucketed for efficient range queries
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'property_id',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // DynamoDB Table for leases_view
    // Stores lease data with extracted clause flags
    // **Feature: graph-aware-zero-config-retrieval**
    // **Requirements: 5.3**
    this.leasesViewTable = new dynamodb.Table(this, 'LeasesViewTable', {
      tableName: 'salesforce-ai-search-leases-view',
      partitionKey: {
        name: 'property_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'lease_id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // GSI for querying leases by end date
    this.leasesViewTable.addGlobalSecondaryIndex({
      indexName: 'end-date-index',
      partitionKey: {
        name: 'end_date_month',  // YYYY-MM format for efficient range queries
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'lease_id',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // DynamoDB Table for activities_agg
    // Stores activity counts for 7/30/90 day windows per entity
    // **Feature: graph-aware-zero-config-retrieval**
    // **Requirements: 5.4**
    this.activitiesAggTable = new dynamodb.Table(this, 'ActivitiesAggTable', {
      tableName: 'salesforce-ai-search-activities-agg',
      partitionKey: {
        name: 'entity_id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // GSI for querying by entity type
    this.activitiesAggTable.addGlobalSecondaryIndex({
      indexName: 'entity-type-index',
      partitionKey: {
        name: 'entity_type',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'entity_id',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // DynamoDB Table for sales_view
    // Stores sale data with broker information
    // **Feature: graph-aware-zero-config-retrieval**
    // **Requirements: 5.5**
    this.salesViewTable = new dynamodb.Table(this, 'SalesViewTable', {
      tableName: 'salesforce-ai-search-sales-view',
      partitionKey: {
        name: 'sale_id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // GSI for querying sales by stage
    this.salesViewTable.addGlobalSecondaryIndex({
      indexName: 'stage-index',
      partitionKey: {
        name: 'stage',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'sale_id',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI for querying sales by property
    this.salesViewTable.addGlobalSecondaryIndex({
      indexName: 'property-index',
      partitionKey: {
        name: 'property_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'sale_id',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // DynamoDB Table for vocab_cache
    // Stores auto-built vocabulary from Salesforce metadata
    // **Feature: graph-aware-zero-config-retrieval**
    // **Requirements: 2.1, 2.4**
    this.vocabCacheTable = new dynamodb.Table(this, 'VocabCacheTable', {
      tableName: 'salesforce-ai-search-vocab-cache',
      partitionKey: {
        name: 'vocab_key',  // Format: vocab_type#object_name
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'term',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: kmsKey,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      timeToLiveAttribute: 'ttl',  // 24-hour TTL for vocab entries
    });

    // GSI for term lookup across all vocab types
    this.vocabCacheTable.addGlobalSecondaryIndex({
      indexName: 'term-lookup-index',
      partitionKey: {
        name: 'term',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'vocab_key',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // Outputs
    new cdk.CfnOutput(this, 'DataBucketName', {
      value: this.dataBucket.bucketName,
      description: 'S3 bucket for data storage',
      exportName: `${this.stackName}-DataBucketName`,
    });

    new cdk.CfnOutput(this, 'EmbeddingsBucketName', {
      value: this.embeddingsBucket.bucketName,
      description: 'S3 bucket for embeddings',
      exportName: `${this.stackName}-EmbeddingsBucketName`,
    });

    new cdk.CfnOutput(this, 'AuditBucketName', {
      value: this.auditBucket.bucketName,
      description: 'S3 bucket for document audit trail',
      exportName: `${this.stackName}-AuditBucketName`,
    });

    new cdk.CfnOutput(this, 'LogsBucketName', {
      value: this.logsBucket.bucketName,
      description: 'S3 bucket for logs',
      exportName: `${this.stackName}-LogsBucketName`,
    });

    new cdk.CfnOutput(this, 'TelemetryTableName', {
      value: this.telemetryTable.tableName,
      description: 'DynamoDB table for telemetry',
      exportName: `${this.stackName}-TelemetryTableName`,
    });

    new cdk.CfnOutput(this, 'SessionsTableName', {
      value: this.sessionsTable.tableName,
      description: 'DynamoDB table for sessions',
      exportName: `${this.stackName}-SessionsTableName`,
    });

    new cdk.CfnOutput(this, 'AuthzCacheTableName', {
      value: this.authzCacheTable.tableName,
      description: 'DynamoDB table for AuthZ cache',
      exportName: `${this.stackName}-AuthzCacheTableName`,
    });

    new cdk.CfnOutput(this, 'RateLimitsTableName', {
      value: this.rateLimitsTable.tableName,
      description: 'DynamoDB table for rate limits (Phase 2)',
      exportName: `${this.stackName}-RateLimitsTableName`,
    });

    new cdk.CfnOutput(this, 'ActionMetadataTableName', {
      value: this.actionMetadataTable.tableName,
      description: 'DynamoDB table for action metadata (Phase 2)',
      exportName: `${this.stackName}-ActionMetadataTableName`,
    });

    // Phase 3: Graph Enhancement table outputs
    new cdk.CfnOutput(this, 'GraphNodesTableName', {
      value: this.graphNodesTable.tableName,
      description: 'DynamoDB table for graph nodes (Phase 3)',
      exportName: `${this.stackName}-GraphNodesTableName`,
    });

    new cdk.CfnOutput(this, 'GraphNodesTableArn', {
      value: this.graphNodesTable.tableArn,
      description: 'DynamoDB table ARN for graph nodes (Phase 3)',
      exportName: `${this.stackName}-GraphNodesTableArn`,
    });

    new cdk.CfnOutput(this, 'GraphEdgesTableName', {
      value: this.graphEdgesTable.tableName,
      description: 'DynamoDB table for graph edges (Phase 3)',
      exportName: `${this.stackName}-GraphEdgesTableName`,
    });

    new cdk.CfnOutput(this, 'GraphEdgesTableArn', {
      value: this.graphEdgesTable.tableArn,
      description: 'DynamoDB table ARN for graph edges (Phase 3)',
      exportName: `${this.stackName}-GraphEdgesTableArn`,
    });

    new cdk.CfnOutput(this, 'GraphPathCacheTableName', {
      value: this.graphPathCacheTable.tableName,
      description: 'DynamoDB table for graph path cache (Phase 3)',
      exportName: `${this.stackName}-GraphPathCacheTableName`,
    });

    new cdk.CfnOutput(this, 'IntentClassificationLogTableName', {
      value: this.intentClassificationLogTable.tableName,
      description: 'DynamoDB table for intent classification logs (Phase 3)',
      exportName: `${this.stackName}-IntentClassificationLogTableName`,
    });

    // Zero-Config Schema Discovery table outputs
    new cdk.CfnOutput(this, 'SchemaCacheTableName', {
      value: this.schemaCacheTable.tableName,
      description: 'DynamoDB table for schema cache (Zero-Config Schema Discovery)',
      exportName: `${this.stackName}-SchemaCacheTableName`,
    });

    new cdk.CfnOutput(this, 'SchemaCacheTableArn', {
      value: this.schemaCacheTable.tableArn,
      description: 'DynamoDB table ARN for schema cache (Zero-Config Schema Discovery)',
      exportName: `${this.stackName}-SchemaCacheTableArn`,
    });

    // Graph-Aware Zero-Config Retrieval: Derived View table outputs
    new cdk.CfnOutput(this, 'AvailabilityViewTableName', {
      value: this.availabilityViewTable.tableName,
      description: 'DynamoDB table for availability view (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-AvailabilityViewTableName`,
    });

    new cdk.CfnOutput(this, 'AvailabilityViewTableArn', {
      value: this.availabilityViewTable.tableArn,
      description: 'DynamoDB table ARN for availability view (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-AvailabilityViewTableArn`,
    });

    new cdk.CfnOutput(this, 'VacancyViewTableName', {
      value: this.vacancyViewTable.tableName,
      description: 'DynamoDB table for vacancy view (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-VacancyViewTableName`,
    });

    new cdk.CfnOutput(this, 'VacancyViewTableArn', {
      value: this.vacancyViewTable.tableArn,
      description: 'DynamoDB table ARN for vacancy view (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-VacancyViewTableArn`,
    });

    new cdk.CfnOutput(this, 'LeasesViewTableName', {
      value: this.leasesViewTable.tableName,
      description: 'DynamoDB table for leases view (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-LeasesViewTableName`,
    });

    new cdk.CfnOutput(this, 'LeasesViewTableArn', {
      value: this.leasesViewTable.tableArn,
      description: 'DynamoDB table ARN for leases view (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-LeasesViewTableArn`,
    });

    new cdk.CfnOutput(this, 'ActivitiesAggTableName', {
      value: this.activitiesAggTable.tableName,
      description: 'DynamoDB table for activities aggregation (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-ActivitiesAggTableName`,
    });

    new cdk.CfnOutput(this, 'ActivitiesAggTableArn', {
      value: this.activitiesAggTable.tableArn,
      description: 'DynamoDB table ARN for activities aggregation (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-ActivitiesAggTableArn`,
    });

    new cdk.CfnOutput(this, 'SalesViewTableName', {
      value: this.salesViewTable.tableName,
      description: 'DynamoDB table for sales view (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-SalesViewTableName`,
    });

    new cdk.CfnOutput(this, 'SalesViewTableArn', {
      value: this.salesViewTable.tableArn,
      description: 'DynamoDB table ARN for sales view (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-SalesViewTableArn`,
    });

    new cdk.CfnOutput(this, 'VocabCacheTableName', {
      value: this.vocabCacheTable.tableName,
      description: 'DynamoDB table for vocab cache (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-VocabCacheTableName`,
    });

    new cdk.CfnOutput(this, 'VocabCacheTableArn', {
      value: this.vocabCacheTable.tableArn,
      description: 'DynamoDB table ARN for vocab cache (Graph-Aware Zero-Config)',
      exportName: `${this.stackName}-VocabCacheTableArn`,
    });

    // Tag all resources
    cdk.Tags.of(this).add('Component', 'Data');
  }
}
