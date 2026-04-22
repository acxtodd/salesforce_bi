import * as cdk from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as sns from "aws-cdk-lib/aws-sns";
import * as subscriptions from "aws-cdk-lib/aws-sns-subscriptions";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as logs from "aws-cdk-lib/aws-logs";
import * as actions from "aws-cdk-lib/aws-cloudwatch-actions";
import { Construct } from "constructs";

interface MonitoringStackProps extends cdk.StackProps {
  api: apigateway.RestApi;
  authzLambda: lambda.Function;
  actionLambda?: lambda.Function; // Phase 2
  telemetryTable: dynamodb.Table;
  sessionsTable: dynamodb.Table;
  authzCacheTable: dynamodb.Table;
  rateLimitsTable?: dynamodb.Table; // Phase 2
  // True when the IngestionStack created AppFlow CDC flows (i.e. Salesforce
  // context was provided at deploy time). Gates the CDC flow health alarm,
  // which would otherwise page permanently on missing data in environments
  // where AppFlow was never deployed.
  appflowEnabled?: boolean;
}

export class MonitoringStack extends cdk.Stack {
  public readonly criticalAlarmTopic: sns.Topic;
  public readonly warningAlarmTopic: sns.Topic;
  public readonly apiPerformanceDashboard: cloudwatch.Dashboard;
  public readonly retrievalQualityDashboard: cloudwatch.Dashboard;
  public readonly freshnessDashboard: cloudwatch.Dashboard;
  public readonly costDashboard: cloudwatch.Dashboard;
  public readonly agentActionsDashboard?: cloudwatch.Dashboard; // Phase 2
  public readonly plannerPerformanceDashboard?: cloudwatch.Dashboard; // Graph-Aware Zero-Config

  constructor(scope: Construct, id: string, props: MonitoringStackProps) {
    super(scope, id, props);

    const {
      api,
      authzLambda,
      actionLambda,
      telemetryTable,
      sessionsTable,
      authzCacheTable,
      rateLimitsTable,
      appflowEnabled,
    } = props;

    // SNS Topics for alarm notifications
    this.criticalAlarmTopic = new sns.Topic(this, "CriticalAlarmTopic", {
      topicName: "salesforce-ai-search-critical-alarms",
      displayName: "Critical Alarms for Salesforce AI Search",
    });

    this.warningAlarmTopic = new sns.Topic(this, "WarningAlarmTopic", {
      topicName: "salesforce-ai-search-warning-alarms",
      displayName: "Warning Alarms for Salesforce AI Search",
    });

    // Add email subscriptions (configure via environment variables or parameters)
    const criticalEmail = process.env.CRITICAL_ALARM_EMAIL;
    const warningEmail = process.env.WARNING_ALARM_EMAIL;

    if (criticalEmail) {
      this.criticalAlarmTopic.addSubscription(
        new subscriptions.EmailSubscription(criticalEmail),
      );
    }

    if (warningEmail) {
      this.warningAlarmTopic.addSubscription(
        new subscriptions.EmailSubscription(warningEmail),
      );
    }

    // 1. API Performance Dashboard
    this.apiPerformanceDashboard = new cloudwatch.Dashboard(
      this,
      "ApiPerformanceDashboard",
      {
        dashboardName: "Salesforce-AI-Search-API-Performance",
      },
    );

    // API Gateway metrics
    const apiRequestCount = new cloudwatch.Metric({
      namespace: "AWS/ApiGateway",
      metricName: "Count",
      dimensionsMap: {
        ApiName: api.restApiName,
      },
      statistic: "Sum",
      period: cdk.Duration.minutes(1),
    });

    const api4xxErrors = new cloudwatch.Metric({
      namespace: "AWS/ApiGateway",
      metricName: "4XXError",
      dimensionsMap: {
        ApiName: api.restApiName,
      },
      statistic: "Sum",
      period: cdk.Duration.minutes(1),
    });

    const api5xxErrors = new cloudwatch.Metric({
      namespace: "AWS/ApiGateway",
      metricName: "5XXError",
      dimensionsMap: {
        ApiName: api.restApiName,
      },
      statistic: "Sum",
      period: cdk.Duration.minutes(1),
    });

    const apiLatency = new cloudwatch.Metric({
      namespace: "AWS/ApiGateway",
      metricName: "Latency",
      dimensionsMap: {
        ApiName: api.restApiName,
      },
      statistic: "Average",
      period: cdk.Duration.minutes(1),
    });

    // Add widgets to API Performance Dashboard
    this.apiPerformanceDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "API Request Count by Endpoint",
        left: [apiRequestCount],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "API Error Rates",
        left: [api4xxErrors, api5xxErrors],
        width: 12,
        height: 6,
      }),
    );

    this.apiPerformanceDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "API Gateway Latency (ms)",
        left: [apiLatency],
        width: 24,
        height: 6,
      }),
    );

    // 2. Retrieval Quality Dashboard
    this.retrievalQualityDashboard = new cloudwatch.Dashboard(
      this,
      "RetrievalQualityDashboard",
      {
        dashboardName: "Salesforce-AI-Search-Retrieval-Quality",
      },
    );

    // Custom metrics from telemetry table (logged by Lambda functions)
    const retrievalHitRate = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "RetrievalHitRate",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    const avgMatchCount = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "MatchCount",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    const authzPostFilterRejectionRate = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "AuthzPostFilterRejections",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    });

    const authzCacheHitRate = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "AuthzCacheHitRate",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    const retrievalCacheHitRate = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "RetrievalCacheHitRate",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    const precisionAt5 = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "PrecisionAt5",
      statistic: "Average",
      period: cdk.Duration.hours(1),
    });

    const precisionAt10 = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "PrecisionAt10",
      statistic: "Average",
      period: cdk.Duration.hours(1),
    });

    // Add widgets to Retrieval Quality Dashboard
    this.retrievalQualityDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Retrieval Hit Rate (%)",
        left: [retrievalHitRate],
        width: 12,
        height: 6,
        leftYAxis: {
          min: 0,
          max: 100,
        },
      }),
      new cloudwatch.GraphWidget({
        title: "Average Match Count per Query",
        left: [avgMatchCount],
        width: 12,
        height: 6,
      }),
    );

    this.retrievalQualityDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Precision Metrics",
        left: [precisionAt5, precisionAt10],
        width: 12,
        height: 6,
        leftYAxis: {
          min: 0,
          max: 1,
        },
      }),
      new cloudwatch.GraphWidget({
        title: "AuthZ Post-Filter Rejections",
        left: [authzPostFilterRejectionRate],
        width: 12,
        height: 6,
      }),
    );

    this.retrievalQualityDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Cache Hit Rates (%)",
        left: [authzCacheHitRate, retrievalCacheHitRate],
        width: 24,
        height: 6,
        leftYAxis: {
          min: 0,
          max: 100,
        },
      }),
    );

    // 3. Freshness Dashboard
    this.freshnessDashboard = new cloudwatch.Dashboard(
      this,
      "FreshnessDashboard",
      {
        dashboardName: "Salesforce-AI-Search-Freshness",
      },
    );

    // CDC and ingestion metrics
    const cdcEventLagP50 = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "CDCEventLag",
      statistic: "p50",
      period: cdk.Duration.minutes(1),
    });

    const cdcEventLagP95 = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "CDCEventLag",
      statistic: "p95",
      period: cdk.Duration.minutes(1),
    });

    const ingestPipelineDuration = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "IngestPipelineDuration",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    const bedrockKbSyncLag = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "BedrockKBSyncLag",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    const recordsProcessedPerMinute = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "RecordsProcessed",
      statistic: "Sum",
      period: cdk.Duration.minutes(1),
    });

    const failedIngestionCount = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "FailedIngestions",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    });

    // Add widgets to Freshness Dashboard
    this.freshnessDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "CDC Event Lag (minutes)",
        left: [cdcEventLagP50, cdcEventLagP95],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Ingest Pipeline Duration (seconds)",
        left: [ingestPipelineDuration],
        width: 12,
        height: 6,
      }),
    );

    this.freshnessDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Bedrock KB Sync Lag (minutes)",
        left: [bedrockKbSyncLag],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Records Processed per Minute",
        left: [recordsProcessedPerMinute],
        width: 12,
        height: 6,
      }),
    );

    this.freshnessDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Failed Ingestion Count",
        left: [failedIngestionCount],
        width: 24,
        height: 6,
      }),
    );

    // 4. Cost Dashboard
    this.costDashboard = new cloudwatch.Dashboard(this, "CostDashboard", {
      dashboardName: "Salesforce-AI-Search-Cost",
    });

    // Bedrock API costs (estimated from invocations)
    const bedrockEmbeddingInvocations = new cloudwatch.Metric({
      namespace: "AWS/Bedrock",
      metricName: "Invocations",
      dimensionsMap: {
        ModelId: "cohere.embed-v4",
      },
      statistic: "Sum",
      period: cdk.Duration.hours(1),
    });

    const bedrockGenerationInvocations = new cloudwatch.Metric({
      namespace: "AWS/Bedrock",
      metricName: "Invocations",
      dimensionsMap: {
        ModelId: "anthropic.claude-3-sonnet-20240229-v1:0",
      },
      statistic: "Sum",
      period: cdk.Duration.hours(1),
    });

    // Lambda invocation costs
    const totalLambdaInvocations = authzLambda.metricInvocations({
      statistic: "Sum",
      period: cdk.Duration.hours(1),
    });

    // DynamoDB read/write costs
    const dynamoDbReadCapacity = new cloudwatch.MathExpression({
      expression: "telemetryRead + sessionsRead + authzRead",
      usingMetrics: {
        telemetryRead: telemetryTable.metricConsumedReadCapacityUnits({
          statistic: "Sum",
          period: cdk.Duration.hours(1),
        }),
        sessionsRead: sessionsTable.metricConsumedReadCapacityUnits({
          statistic: "Sum",
          period: cdk.Duration.hours(1),
        }),
        authzRead: authzCacheTable.metricConsumedReadCapacityUnits({
          statistic: "Sum",
          period: cdk.Duration.hours(1),
        }),
      },
      period: cdk.Duration.hours(1),
    });

    const dynamoDbWriteCapacity = new cloudwatch.MathExpression({
      expression: "telemetryWrite + sessionsWrite + authzWrite",
      usingMetrics: {
        telemetryWrite: telemetryTable.metricConsumedWriteCapacityUnits({
          statistic: "Sum",
          period: cdk.Duration.hours(1),
        }),
        sessionsWrite: sessionsTable.metricConsumedWriteCapacityUnits({
          statistic: "Sum",
          period: cdk.Duration.hours(1),
        }),
        authzWrite: authzCacheTable.metricConsumedWriteCapacityUnits({
          statistic: "Sum",
          period: cdk.Duration.hours(1),
        }),
      },
      period: cdk.Duration.hours(1),
    });

    // Add widgets to Cost Dashboard
    this.costDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Bedrock API Invocations (Hourly)",
        left: [bedrockEmbeddingInvocations, bedrockGenerationInvocations],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Lambda Invocations (Hourly)",
        left: [totalLambdaInvocations],
        width: 12,
        height: 6,
      }),
    );

    this.costDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "DynamoDB Capacity Units (Hourly)",
        left: [dynamoDbReadCapacity, dynamoDbWriteCapacity],
        width: 24,
        height: 6,
      }),
    );

    // Cost by TenantId (custom metric)
    const costByTenant = new cloudwatch.Metric({
      namespace: "SalesforceAISearch",
      metricName: "EstimatedCost",
      statistic: "Sum",
      period: cdk.Duration.hours(1),
    });

    this.costDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Estimated Cost by TenantId (Hourly)",
        left: [costByTenant],
        width: 24,
        height: 6,
      }),
    );

    // 5. Agent Actions Dashboard (Phase 2)
    if (actionLambda && rateLimitsTable) {
      this.agentActionsDashboard = new cloudwatch.Dashboard(
        this,
        "AgentActionsDashboard",
        {
          dashboardName: "Salesforce-AI-Search-Agent-Actions",
        },
      );

      // Action Lambda metrics
      const actionLambdaInvocations = actionLambda.metricInvocations({
        statistic: "Sum",
        period: cdk.Duration.minutes(5),
      });

      const actionLambdaErrors = actionLambda.metricErrors({
        statistic: "Sum",
        period: cdk.Duration.minutes(5),
      });

      const actionLambdaDuration = actionLambda.metricDuration({
        statistic: "p95",
        period: cdk.Duration.minutes(5),
      });

      const actionLambdaDurationP50 = actionLambda.metricDuration({
        statistic: "p50",
        period: cdk.Duration.minutes(5),
      });

      const actionLambdaDurationP99 = actionLambda.metricDuration({
        statistic: "p99",
        period: cdk.Duration.minutes(5),
      });

      // Custom metrics from Action Lambda logs
      const actionCountByName = new cloudwatch.Metric({
        namespace: "SalesforceAISearch",
        metricName: "ActionCount",
        statistic: "Sum",
        period: cdk.Duration.minutes(5),
      });

      const actionSuccessRate = new cloudwatch.Metric({
        namespace: "SalesforceAISearch",
        metricName: "ActionSuccessRate",
        statistic: "Average",
        period: cdk.Duration.minutes(5),
      });

      const rateLimitRejections = new cloudwatch.Metric({
        namespace: "SalesforceAISearch",
        metricName: "RateLimitRejections",
        statistic: "Sum",
        period: cdk.Duration.minutes(5),
      });

      const actionMutationVolume = new cloudwatch.Metric({
        namespace: "SalesforceAISearch",
        metricName: "MutationVolume",
        statistic: "Sum",
        period: cdk.Duration.hours(1),
      });

      // Rate limits table metrics
      const rateLimitsReadCapacity =
        rateLimitsTable.metricConsumedReadCapacityUnits({
          statistic: "Sum",
          period: cdk.Duration.minutes(5),
        });

      const rateLimitsWriteCapacity =
        rateLimitsTable.metricConsumedWriteCapacityUnits({
          statistic: "Sum",
          period: cdk.Duration.minutes(5),
        });

      // Add widgets to Agent Actions Dashboard
      this.agentActionsDashboard.addWidgets(
        new cloudwatch.GraphWidget({
          title: "Action Count by Action Name",
          left: [actionCountByName],
          width: 12,
          height: 6,
        }),
        new cloudwatch.GraphWidget({
          title: "Action Success Rate (%)",
          left: [actionSuccessRate],
          width: 12,
          height: 6,
          leftYAxis: {
            min: 0,
            max: 100,
          },
        }),
      );

      this.agentActionsDashboard.addWidgets(
        new cloudwatch.GraphWidget({
          title: "Action Latency (ms)",
          left: [
            actionLambdaDurationP50,
            actionLambdaDuration,
            actionLambdaDurationP99,
          ],
          width: 12,
          height: 6,
        }),
        new cloudwatch.GraphWidget({
          title: "Rate Limit Rejections (429 responses)",
          left: [rateLimitRejections],
          width: 12,
          height: 6,
        }),
      );

      this.agentActionsDashboard.addWidgets(
        new cloudwatch.GraphWidget({
          title: "Lambda Invocations and Errors",
          left: [actionLambdaInvocations],
          right: [actionLambdaErrors],
          width: 12,
          height: 6,
        }),
        new cloudwatch.GraphWidget({
          title: "Mutation Volume (Hourly)",
          left: [actionMutationVolume],
          width: 12,
          height: 6,
        }),
      );

      this.agentActionsDashboard.addWidgets(
        new cloudwatch.GraphWidget({
          title: "Rate Limits Table Capacity Units",
          left: [rateLimitsReadCapacity, rateLimitsWriteCapacity],
          width: 12,
          height: 6,
        }),
        new cloudwatch.LogQueryWidget({
          title: "Top Users by Action Count",
          logGroupNames: [
            actionLambda.logGroup?.logGroupName ||
            `/aws/lambda/${actionLambda.functionName}`,
          ],
          queryLines: [
            "fields @timestamp, salesforceUserId, actionName",
            "filter @message like /Processing action request/",
            "stats count() as actionCount by salesforceUserId",
            "sort actionCount desc",
            "limit 10",
          ],
          width: 12,
          height: 6,
        }),
      );

      // Output for Agent Actions Dashboard
      new cdk.CfnOutput(this, "AgentActionsDashboardUrl", {
        value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${this.agentActionsDashboard.dashboardName}`,
        description: "URL to Agent Actions Dashboard",
      });
    }

    // ========================================
    // Graph-Aware Zero-Config: Planner Performance Dashboard (Task 21.3)
    // ========================================
    this.plannerPerformanceDashboard = new cloudwatch.Dashboard(
      this,
      "PlannerPerformanceDashboard",
      {
        dashboardName: "Salesforce-AI-Search-Planner-Performance",
      },
    );

    // Planner latency metrics (Req 12.1)
    const plannerLatencyP50 = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Planner",
      metricName: "PlannerLatency",
      statistic: "p50",
      period: cdk.Duration.minutes(5),
    });

    const plannerLatencyP95 = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Planner",
      metricName: "PlannerLatency",
      statistic: "p95",
      period: cdk.Duration.minutes(5),
    });

    const plannerLatencyP99 = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Planner",
      metricName: "PlannerLatency",
      statistic: "p99",
      period: cdk.Duration.minutes(5),
    });

    // Planner confidence metrics (Req 12.1)
    const plannerConfidenceAvg = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Planner",
      metricName: "PlannerConfidence",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    // Planner fallback metrics (Req 12.2)
    const plannerFallbackCount = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Planner",
      metricName: "PlannerFallback",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    });

    const plannerFallbackRate = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Planner",
      metricName: "PlannerFallbackRate",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    // Planner timeout and error metrics
    const plannerTimeoutCount = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Planner",
      metricName: "PlannerTimeout",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    });

    const plannerErrorCount = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Planner",
      metricName: "PlannerError",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    });

    // Predicate count metrics
    const plannerPredicateCountAvg = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Planner",
      metricName: "PlannerPredicateCount",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    // Quality metrics for derived views (Req 12.1, 12.2)
    const emptyResultRate = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Quality",
      metricName: "EmptyResultRate",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    const bindingPrecision = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Quality",
      metricName: "BindingPrecision",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    const cdcLag = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Quality",
      metricName: "CDCLag",
      statistic: "Average",
      period: cdk.Duration.minutes(1),
    });

    const rollupFreshness = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Quality",
      metricName: "RollupFreshness",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    const resultCount = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Quality",
      metricName: "ResultCount",
      statistic: "Average",
      period: cdk.Duration.minutes(5),
    });

    const emptyResultCount = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/Quality",
      metricName: "EmptyResult",
      statistic: "Sum",
      period: cdk.Duration.minutes(5),
    });

    // Add widgets to Planner Performance Dashboard
    this.plannerPerformanceDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Planner Latency (ms)",
        left: [plannerLatencyP50, plannerLatencyP95, plannerLatencyP99],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Planner Confidence (%)",
        left: [plannerConfidenceAvg],
        width: 12,
        height: 6,
        leftYAxis: {
          min: 0,
          max: 100,
        },
      }),
    );

    this.plannerPerformanceDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Planner Fallback Rate & Count",
        left: [plannerFallbackRate],
        right: [plannerFallbackCount],
        width: 12,
        height: 6,
        leftYAxis: {
          min: 0,
          max: 100,
        },
      }),
      new cloudwatch.GraphWidget({
        title: "Planner Timeouts & Errors",
        left: [plannerTimeoutCount, plannerErrorCount],
        width: 12,
        height: 6,
      }),
    );

    this.plannerPerformanceDashboard.addWidgets(
      new cloudwatch.SingleValueWidget({
        title: "Avg Predicates per Query",
        metrics: [plannerPredicateCountAvg],
        width: 6,
        height: 6,
      }),
      new cloudwatch.SingleValueWidget({
        title: "Binding Precision",
        metrics: [bindingPrecision],
        width: 6,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Result Count & Empty Results",
        left: [resultCount],
        right: [emptyResultCount],
        width: 12,
        height: 6,
      }),
    );

    this.plannerPerformanceDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "CDC Lag (seconds)",
        left: [cdcLag],
        width: 12,
        height: 6,
      }),
      new cloudwatch.GraphWidget({
        title: "Rollup Freshness (seconds)",
        left: [rollupFreshness],
        width: 12,
        height: 6,
      }),
    );

    // Add empty result rate to dashboard
    this.plannerPerformanceDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Empty Result Rate (%)",
        left: [emptyResultRate],
        width: 24,
        height: 6,
        leftYAxis: {
          min: 0,
          max: 100,
        },
      }),
    );

    // Output for Planner Performance Dashboard
    new cdk.CfnOutput(this, "PlannerPerformanceDashboardUrl", {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${this.plannerPerformanceDashboard.dashboardName}`,
      description: "URL to Planner Performance Dashboard (Graph-Aware Zero-Config)",
    });

    // ========================================
    // Graph-Aware Zero-Config: CloudWatch Alarms (Task 21.2)
    // ========================================

    // Critical: CDC lag > 10 minutes (600 seconds) (Req 12.3)
    const cdcLagCriticalAlarm = new cloudwatch.Alarm(
      this,
      "CDCLagCriticalAlarm",
      {
        alarmName: "salesforce-ai-search-cdc-lag-critical",
        alarmDescription: "CDC lag exceeds 10 minutes - data freshness is degraded",
        metric: cdcLag,
        threshold: 600, // 10 minutes in seconds
        evaluationPeriods: 3,
        datapointsToAlarm: 3,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    cdcLagCriticalAlarm.addAlarmAction(
      new actions.SnsAction(this.criticalAlarmTopic),
    );

    // Critical: AppFlow CDC flow health (Task 4.29)
    // Catches Salesforce CDC flows transitioning to a non-Active state
    // (e.g. Suspended by Salesforce replay-ID expiry). Suspended flows emit
    // no FlowExecution metrics, so we rely on a scheduled health-check Lambda
    // that publishes SalesforceAISearch/Ingestion::CDCFlowHealthy every 5 min.
    // Missing data is treated as BREACHING so the alarm still fires if the
    // health-check Lambda itself stops publishing.
    //
    // Gated on appflowEnabled: the IngestionStack only creates the
    // health-check Lambda when AppFlow is configured, so enabling the alarm
    // in environments without AppFlow would fire forever on missing data.
    if (appflowEnabled) {
      const cdcFlowHealthyMetric = new cloudwatch.Metric({
        namespace: "SalesforceAISearch/Ingestion",
        metricName: "CDCFlowHealthy",
        statistic: "Minimum",
        period: cdk.Duration.minutes(5),
      });

      const cdcFlowHealthCriticalAlarm = new cloudwatch.Alarm(
        this,
        "CDCFlowHealthCriticalAlarm",
        {
          alarmName: "salesforce-ai-search-cdc-flow-health-critical",
          alarmDescription:
            "One or more Salesforce CDC AppFlow flows is in a non-Active state. See docs/runbooks/appflow_cdc_recovery.md",
          metric: cdcFlowHealthyMetric,
          threshold: 1,
          evaluationPeriods: 3,
          datapointsToAlarm: 3,
          comparisonOperator:
            cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.BREACHING,
        },
      );
      cdcFlowHealthCriticalAlarm.addAlarmAction(
        new actions.SnsAction(this.criticalAlarmTopic),
      );
    }

    // Critical: Planner latency p95 > 1.5s (Req 12.4)
    const plannerLatencyCriticalAlarm = new cloudwatch.Alarm(
      this,
      "PlannerLatencyCriticalAlarm",
      {
        alarmName: "salesforce-ai-search-planner-latency-critical",
        alarmDescription: "Planner p95 latency exceeds 1.5 seconds - performance regression",
        metric: plannerLatencyP95,
        threshold: 1500, // 1.5 seconds in milliseconds
        evaluationPeriods: 3,
        datapointsToAlarm: 3,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    plannerLatencyCriticalAlarm.addAlarmAction(
      new actions.SnsAction(this.criticalAlarmTopic),
    );

    // Warning: Fallback rate spike > 15% (Req 12.3)
    const plannerFallbackRateWarningAlarm = new cloudwatch.Alarm(
      this,
      "PlannerFallbackRateWarningAlarm",
      {
        alarmName: "salesforce-ai-search-planner-fallback-rate-warning",
        alarmDescription: "Planner fallback rate exceeds 15% - possible degradation",
        metric: plannerFallbackRate,
        threshold: 15, // 15%
        evaluationPeriods: 5,
        datapointsToAlarm: 5,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    plannerFallbackRateWarningAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // Warning: Empty result rate > 10% (Req 12.4)
    const emptyResultRateWarningAlarm = new cloudwatch.Alarm(
      this,
      "EmptyResultRateWarningAlarm",
      {
        alarmName: "salesforce-ai-search-empty-result-rate-warning",
        alarmDescription: "Empty result rate exceeds 10% - retrieval quality degraded",
        metric: emptyResultRate,
        threshold: 10, // 10%
        evaluationPeriods: 10,
        datapointsToAlarm: 10,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    emptyResultRateWarningAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // Warning: Rollup freshness > 30 minutes (1800 seconds)
    const rollupFreshnessWarningAlarm = new cloudwatch.Alarm(
      this,
      "RollupFreshnessWarningAlarm",
      {
        alarmName: "salesforce-ai-search-rollup-freshness-warning",
        alarmDescription: "Rollup freshness exceeds 30 minutes - derived views may be stale",
        metric: rollupFreshness,
        threshold: 1800, // 30 minutes in seconds
        evaluationPeriods: 5,
        datapointsToAlarm: 5,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    rollupFreshnessWarningAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // Warning: Low binding precision < 50%
    const bindingPrecisionWarningAlarm = new cloudwatch.Alarm(
      this,
      "BindingPrecisionWarningAlarm",
      {
        alarmName: "salesforce-ai-search-binding-precision-warning",
        alarmDescription: "Binding precision below 50% - planner quality degraded",
        metric: bindingPrecision,
        threshold: 50, // 50%
        evaluationPeriods: 10,
        datapointsToAlarm: 10,
        comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    bindingPrecisionWarningAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // Outputs for Graph-Aware Zero-Config alarms
    new cdk.CfnOutput(this, "CDCLagCriticalAlarmName", {
      value: cdcLagCriticalAlarm.alarmName,
      description: "Alarm for CDC lag critical threshold",
    });

    new cdk.CfnOutput(this, "PlannerLatencyCriticalAlarmName", {
      value: plannerLatencyCriticalAlarm.alarmName,
      description: "Alarm for planner latency critical threshold",
    });

    new cdk.CfnOutput(this, "PlannerFallbackRateWarningAlarmName", {
      value: plannerFallbackRateWarningAlarm.alarmName,
      description: "Alarm for planner fallback rate warning",
    });

    new cdk.CfnOutput(this, "EmptyResultRateWarningAlarmName", {
      value: emptyResultRateWarningAlarm.alarmName,
      description: "Alarm for empty result rate warning",
    });

    new cdk.CfnOutput(this, "RollupFreshnessWarningAlarmName", {
      value: rollupFreshnessWarningAlarm.alarmName,
      description: "Alarm for rollup freshness warning",
    });

    new cdk.CfnOutput(this, "BindingPrecisionWarningAlarmName", {
      value: bindingPrecisionWarningAlarm.alarmName,
      description: "Alarm for binding precision warning",
    });

    // Outputs
    new cdk.CfnOutput(this, "CriticalAlarmTopicArn", {
      value: this.criticalAlarmTopic.topicArn,
      description: "SNS Topic ARN for critical alarms",
      exportName: `${this.stackName}-CriticalAlarmTopicArn`,
    });

    new cdk.CfnOutput(this, "WarningAlarmTopicArn", {
      value: this.warningAlarmTopic.topicArn,
      description: "SNS Topic ARN for warning alarms",
      exportName: `${this.stackName}-WarningAlarmTopicArn`,
    });

    new cdk.CfnOutput(this, "ApiPerformanceDashboardUrl", {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${this.apiPerformanceDashboard.dashboardName}`,
      description: "URL to API Performance Dashboard",
    });

    new cdk.CfnOutput(this, "RetrievalQualityDashboardUrl", {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${this.retrievalQualityDashboard.dashboardName}`,
      description: "URL to Retrieval Quality Dashboard",
    });

    new cdk.CfnOutput(this, "FreshnessDashboardUrl", {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${this.freshnessDashboard.dashboardName}`,
      description: "URL to Freshness Dashboard",
    });

    new cdk.CfnOutput(this, "CostDashboardUrl", {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${this.costDashboard.dashboardName}`,
      description: "URL to Cost Dashboard",
    });

    // ========================================
    // CloudWatch Alarms
    // ========================================

    // Critical Alarms (PagerDuty)

    // API Gateway 5xx rate > 5% for 5 minutes
    const api5xxRateAlarm = new cloudwatch.Alarm(this, "Api5xxRateAlarm", {
      alarmName: "salesforce-ai-search-api-5xx-rate-critical",
      alarmDescription: "API Gateway 5xx error rate exceeds 5% for 5 minutes",
      metric: api5xxErrors,
      threshold: 5,
      evaluationPeriods: 5,
      datapointsToAlarm: 5,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    api5xxRateAlarm.addAlarmAction(
      new actions.SnsAction(this.criticalAlarmTopic),
    );

    // OpenSearch Serverless does not expose ClusterStatus.red metric in the same way.
    // We can rely on dashboard metrics for OCU usage and errors.
    // Skipping ClusterStatus alarm for Serverless.

    // Bedrock throttling rate > 20% for 5 minutes
    const bedrockThrottlingAlarm = new cloudwatch.Alarm(
      this,
      "BedrockThrottlingAlarm",
      {
        alarmName: "salesforce-ai-search-bedrock-throttling-critical",
        alarmDescription: "Bedrock throttling rate exceeds 20% for 5 minutes",
        metric: new cloudwatch.Metric({
          namespace: "AWS/Bedrock",
          metricName: "ModelInvocationThrottles",
          statistic: "Sum",
          period: cdk.Duration.minutes(1),
        }),
        threshold: 20,
        evaluationPeriods: 5,
        datapointsToAlarm: 5,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    bedrockThrottlingAlarm.addAlarmAction(
      new actions.SnsAction(this.criticalAlarmTopic),
    );

    // AuthZ Sidecar cache miss rate > 50% for 10 minutes
    const authzCacheMissRateAlarm = new cloudwatch.Alarm(
      this,
      "AuthzCacheMissRateAlarm",
      {
        alarmName: "salesforce-ai-search-authz-cache-miss-rate-critical",
        alarmDescription: "AuthZ cache miss rate exceeds 50% for 10 minutes",
        metric: new cloudwatch.MathExpression({
          expression: "100 - hitRate",
          usingMetrics: {
            hitRate: authzCacheHitRate,
          },
          period: cdk.Duration.minutes(1),
        }),
        threshold: 50,
        evaluationPeriods: 10,
        datapointsToAlarm: 10,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    authzCacheMissRateAlarm.addAlarmAction(
      new actions.SnsAction(this.criticalAlarmTopic),
    );

    // Ingestion pipeline failures > 10 in 5 minutes
    const ingestionFailuresAlarm = new cloudwatch.Alarm(
      this,
      "IngestionFailuresAlarm",
      {
        alarmName: "salesforce-ai-search-ingestion-failures-critical",
        alarmDescription: "Ingestion pipeline failures exceed 10 in 5 minutes",
        metric: failedIngestionCount,
        threshold: 10,
        evaluationPeriods: 1,
        datapointsToAlarm: 1,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    ingestionFailuresAlarm.addAlarmAction(
      new actions.SnsAction(this.criticalAlarmTopic),
    );

    // Warning Alarms (Email)

    // API p95 latency > 1.0s for 10 minutes
    const apiLatencyWarningAlarm = new cloudwatch.Alarm(
      this,
      "ApiLatencyWarningAlarm",
      {
        alarmName: "salesforce-ai-search-api-latency-warning",
        alarmDescription: "API p95 latency exceeds 1.0s for 10 minutes",
        metric: new cloudwatch.Metric({
          namespace: "AWS/ApiGateway",
          metricName: "Latency",
          dimensionsMap: {
            ApiName: api.restApiName,
          },
          statistic: "p95",
          period: cdk.Duration.minutes(1),
        }),
        threshold: 1000, // milliseconds
        evaluationPeriods: 10,
        datapointsToAlarm: 10,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    apiLatencyWarningAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // First token latency > 1.0s for 10 minutes
    const firstTokenLatencyWarningAlarm = new cloudwatch.Alarm(
      this,
      "FirstTokenLatencyWarningAlarm",
      {
        alarmName: "salesforce-ai-search-first-token-latency-warning",
        alarmDescription: "First token latency exceeds 1.0s for 10 minutes",
        metric: new cloudwatch.Metric({
          namespace: "SalesforceAISearch",
          metricName: "FirstTokenLatency",
          statistic: "p95",
          period: cdk.Duration.minutes(1),
        }),
        threshold: 1000, // milliseconds
        evaluationPeriods: 10,
        datapointsToAlarm: 10,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    firstTokenLatencyWarningAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // Retrieval precision@5 < 60% (daily eval)
    const precisionWarningAlarm = new cloudwatch.Alarm(
      this,
      "PrecisionWarningAlarm",
      {
        alarmName: "salesforce-ai-search-precision-warning",
        alarmDescription: "Retrieval precision@5 below 60% in daily evaluation",
        metric: precisionAt5,
        threshold: 0.6,
        evaluationPeriods: 1,
        datapointsToAlarm: 1,
        comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    precisionWarningAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // CDC lag P50 > 10 minutes for 15 minutes
    const cdcLagWarningAlarm = new cloudwatch.Alarm(
      this,
      "CdcLagWarningAlarm",
      {
        alarmName: "salesforce-ai-search-cdc-lag-warning",
        alarmDescription: "CDC lag P50 exceeds 10 minutes for 15 minutes",
        metric: cdcEventLagP50,
        threshold: 10, // minutes
        evaluationPeriods: 15,
        datapointsToAlarm: 15,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    cdcLagWarningAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // DynamoDB throttling > 0 for 5 minutes
    const dynamoDbThrottlingAlarm = new cloudwatch.Alarm(
      this,
      "DynamoDbThrottlingAlarm",
      {
        alarmName: "salesforce-ai-search-dynamodb-throttling-warning",
        alarmDescription: "DynamoDB throttling detected for 5 minutes",
        metric: new cloudwatch.MathExpression({
          expression: "telemetryErrors + sessionsErrors + authzErrors",
          usingMetrics: {
            telemetryErrors: telemetryTable.metricUserErrors({
              statistic: "Sum",
              period: cdk.Duration.minutes(1),
            }),
            sessionsErrors: sessionsTable.metricUserErrors({
              statistic: "Sum",
              period: cdk.Duration.minutes(1),
            }),
            authzErrors: authzCacheTable.metricUserErrors({
              statistic: "Sum",
              period: cdk.Duration.minutes(1),
            }),
          },
          period: cdk.Duration.minutes(1),
        }),
        threshold: 0,
        evaluationPeriods: 5,
        datapointsToAlarm: 5,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    dynamoDbThrottlingAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // Action-Specific Alarms (Phase 2)
    if (actionLambda) {
      // Critical: Action failure rate > 50% for 5 minutes
      const actionFailureRateAlarm = new cloudwatch.Alarm(
        this,
        "ActionFailureRateAlarm",
        {
          alarmName: "salesforce-ai-search-action-failure-rate-critical",
          alarmDescription: "Action failure rate exceeds 50% for 5 minutes",
          metric: new cloudwatch.Metric({
            namespace: "SalesforceAISearch",
            metricName: "ActionFailureRate",
            statistic: "Average",
            period: cdk.Duration.minutes(1),
          }),
          threshold: 50,
          evaluationPeriods: 5,
          datapointsToAlarm: 5,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
      actionFailureRateAlarm.addAlarmAction(
        new actions.SnsAction(this.criticalAlarmTopic),
      );

      // Warning: Consecutive failures (>3) per user
      const consecutiveFailuresAlarm = new cloudwatch.Alarm(
        this,
        "ConsecutiveFailuresAlarm",
        {
          alarmName: "salesforce-ai-search-consecutive-failures-warning",
          alarmDescription:
            "More than 3 consecutive failures detected for a single user",
          metric: new cloudwatch.Metric({
            namespace: "SalesforceAISearch",
            metricName: "ConsecutiveFailures",
            statistic: "Maximum",
            period: cdk.Duration.minutes(5),
          }),
          threshold: 3,
          evaluationPeriods: 1,
          datapointsToAlarm: 1,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
      consecutiveFailuresAlarm.addAlarmAction(
        new actions.SnsAction(this.warningAlarmTopic),
      );

      // Warning: Mutation volume > 1000/hour
      const mutationVolumeAlarm = new cloudwatch.Alarm(
        this,
        "MutationVolumeAlarm",
        {
          alarmName: "salesforce-ai-search-mutation-volume-warning",
          alarmDescription: "Mutation volume exceeds 1000 per hour",
          metric: new cloudwatch.Metric({
            namespace: "SalesforceAISearch",
            metricName: "MutationVolume",
            statistic: "Sum",
            period: cdk.Duration.hours(1),
          }),
          threshold: 1000,
          evaluationPeriods: 1,
          datapointsToAlarm: 1,
          comparisonOperator:
            cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        },
      );
      mutationVolumeAlarm.addAlarmAction(
        new actions.SnsAction(this.warningAlarmTopic),
      );

      // Output for action alarms
      new cdk.CfnOutput(this, "ActionFailureRateAlarmName", {
        value: actionFailureRateAlarm.alarmName,
        description: "Alarm for action failure rate",
      });

      new cdk.CfnOutput(this, "ConsecutiveFailuresAlarmName", {
        value: consecutiveFailuresAlarm.alarmName,
        description: "Alarm for consecutive failures per user",
      });

      new cdk.CfnOutput(this, "MutationVolumeAlarmName", {
        value: mutationVolumeAlarm.alarmName,
        description: "Alarm for mutation volume",
      });
    }

    // Composite alarm for overall system health
    const systemHealthAlarm = new cloudwatch.CompositeAlarm(
      this,
      "SystemHealthAlarm",
      {
        alarmDescription: "Overall system health is degraded",
        compositeAlarmName: "salesforce-ai-search-system-health",
        alarmRule: cloudwatch.AlarmRule.anyOf(
          cloudwatch.AlarmRule.fromAlarm(
            api5xxRateAlarm,
            cloudwatch.AlarmState.ALARM,
          ),
        ),
      },
    );
    systemHealthAlarm.addAlarmAction(
      new actions.SnsAction(this.criticalAlarmTopic),
    );

    // Outputs for alarms
    new cdk.CfnOutput(this, "SystemHealthAlarmName", {
      value: "salesforce-ai-search-system-health",
      description: "Composite alarm for overall system health",
    });

    // ========================================
    // Log Groups with Retention and Archiving
    // ========================================

    // Import existing log groups (created by Lambda or ApiStack)
    // We use fromLogGroupName to reference them for Insights queries
    const authzLambdaLogGroup = logs.LogGroup.fromLogGroupName(
      this,
      "AuthzLambdaLogGroupName", // Fixed ID collision risk by changing ID
      `/aws/lambda/${authzLambda.functionName}`
    );

    // Note: S3 archiving for 1-year retention is configured via CloudWatch Logs subscription filters
    // This would typically be set up using a separate Lambda function or Kinesis Firehose
    // For POC, we rely on CloudWatch Logs retention policy set in ApiStack or default

    // Outputs for log groups
    new cdk.CfnOutput(this, "AuthzLambdaLogGroupNameOutput", { // Fixed output name collision
      value: authzLambdaLogGroup.logGroupName,
      description: "Log group for AuthZ Lambda",
    });

    // ========================================
    // Task 39: Schema Drift Monitoring Dashboard
    // ========================================

    const schemaDriftDashboard = new cloudwatch.Dashboard(
      this,
      "SchemaDriftDashboard",
      {
        dashboardName: "Salesforce-AI-Search-Schema-Drift",
      },
    );

    // Schema Drift Metrics
    const totalObjectsCovered = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/SchemaDrift",
      metricName: "TotalObjectsCovered",
      statistic: "Average",
      period: cdk.Duration.hours(1),
    });

    const avgFilterableCoverage = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/SchemaDrift",
      metricName: "AvgFilterableCoverage",
      statistic: "Average",
      period: cdk.Duration.hours(1),
    });

    const avgRelationshipCoverage = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/SchemaDrift",
      metricName: "AvgRelationshipCoverage",
      statistic: "Average",
      period: cdk.Duration.hours(1),
    });

    const totalFakeFields = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/SchemaDrift",
      metricName: "TotalFakeFields",
      statistic: "Sum",
      period: cdk.Duration.hours(1),
    });

    const totalMissingFields = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/SchemaDrift",
      metricName: "TotalMissingFields",
      statistic: "Sum",
      period: cdk.Duration.hours(1),
    });

    const objectsWithDrift = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/SchemaDrift",
      metricName: "ObjectsWithDrift",
      statistic: "Sum",
      period: cdk.Duration.hours(1),
    });

    const driftCheckSuccess = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/SchemaDrift",
      metricName: "DriftCheckSuccess",
      statistic: "Sum",
      period: cdk.Duration.hours(1),
    });

    const driftCheckDuration = new cloudwatch.Metric({
      namespace: "SalesforceAISearch/SchemaDrift",
      metricName: "DriftCheckDuration",
      statistic: "Average",
      period: cdk.Duration.hours(1),
    });

    // Row 1: Overall Health (Single Value Widgets)
    schemaDriftDashboard.addWidgets(
      new cloudwatch.SingleValueWidget({
        title: "Objects Covered",
        metrics: [totalObjectsCovered],
        width: 6,
        height: 4,
      }),
      new cloudwatch.SingleValueWidget({
        title: "Avg Filterable Coverage (%)",
        metrics: [avgFilterableCoverage],
        width: 6,
        height: 4,
      }),
      new cloudwatch.SingleValueWidget({
        title: "Avg Relationship Coverage (%)",
        metrics: [avgRelationshipCoverage],
        width: 6,
        height: 4,
      }),
      new cloudwatch.SingleValueWidget({
        title: "Objects With Drift",
        metrics: [objectsWithDrift],
        width: 6,
        height: 4,
      }),
    );

    // Row 2: Drift Indicators (CRITICAL)
    schemaDriftDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Fake Fields in Cache (CRITICAL)",
        left: [totalFakeFields],
        width: 12,
        height: 6,
        leftAnnotations: [
          {
            value: 0,
            label: "Target: 0",
            color: "#2ca02c",
          },
        ],
      }),
      new cloudwatch.GraphWidget({
        title: "Missing Fields (SF → Cache)",
        left: [totalMissingFields],
        width: 12,
        height: 6,
      }),
    );

    // Row 3: Coverage Trends
    schemaDriftDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Coverage Trends (%)",
        left: [avgFilterableCoverage, avgRelationshipCoverage],
        width: 12,
        height: 6,
        leftYAxis: {
          min: 0,
          max: 100,
        },
      }),
      new cloudwatch.GraphWidget({
        title: "Drift Check Health",
        left: [driftCheckSuccess],
        right: [driftCheckDuration],
        width: 12,
        height: 6,
      }),
    );

    // Output for Schema Drift Dashboard
    new cdk.CfnOutput(this, "SchemaDriftDashboardUrl", {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${schemaDriftDashboard.dashboardName}`,
      description: "URL to Schema Drift Monitoring Dashboard (Task 39)",
    });

    // ========================================
    // Task 39: Schema Drift Alarms
    // ========================================

    // CRITICAL: Fake fields detected (fields in cache but not in SF)
    const fakeFieldsAlarm = new cloudwatch.Alarm(
      this,
      "SchemaDriftFakeFieldsAlarm",
      {
        alarmName: "salesforce-ai-search-schema-drift-fake-fields-critical",
        alarmDescription:
          "Schema cache contains fields that do not exist in Salesforce - possible fake/fabricated fields",
        metric: totalFakeFields,
        threshold: 0,
        evaluationPeriods: 1,
        datapointsToAlarm: 1,
        comparisonOperator:
          cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    fakeFieldsAlarm.addAlarmAction(
      new actions.SnsAction(this.criticalAlarmTopic),
    );

    // WARNING: Filterable coverage below 80%
    const filterableCoverageAlarm = new cloudwatch.Alarm(
      this,
      "SchemaDriftFilterableCoverageAlarm",
      {
        alarmName: "salesforce-ai-search-schema-drift-filterable-coverage-warning",
        alarmDescription:
          "Average filterable field coverage below 80% - some filter queries may fail",
        metric: avgFilterableCoverage,
        threshold: 80,
        evaluationPeriods: 3,
        datapointsToAlarm: 3,
        comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    filterableCoverageAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // WARNING: Relationship coverage below 50%
    const relationshipCoverageAlarm = new cloudwatch.Alarm(
      this,
      "SchemaDriftRelationshipCoverageAlarm",
      {
        alarmName: "salesforce-ai-search-schema-drift-relationship-coverage-warning",
        alarmDescription:
          "Average relationship coverage below 50% - cross-object queries may fail",
        metric: avgRelationshipCoverage,
        threshold: 50,
        evaluationPeriods: 3,
        datapointsToAlarm: 3,
        comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      },
    );
    relationshipCoverageAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // CRITICAL: Objects covered dropped below expected count
    // Expected count should be configured via SSM Parameter or env var
    const expectedObjectCount = 8; // Minimum expected objects (configurable)
    const objectsCoveredAlarm = new cloudwatch.Alarm(
      this,
      "SchemaDriftObjectsCoveredAlarm",
      {
        alarmName: "salesforce-ai-search-schema-drift-objects-covered-critical",
        alarmDescription: `Schema cache has fewer than ${expectedObjectCount} objects - possible data loss or misconfiguration`,
        metric: totalObjectsCovered,
        threshold: expectedObjectCount,
        evaluationPeriods: 2,
        datapointsToAlarm: 2,
        comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.BREACHING,
      },
    );
    objectsCoveredAlarm.addAlarmAction(
      new actions.SnsAction(this.criticalAlarmTopic),
    );

    // WARNING: Drift check failures
    const driftCheckFailureAlarm = new cloudwatch.Alarm(
      this,
      "SchemaDriftCheckFailureAlarm",
      {
        alarmName: "salesforce-ai-search-schema-drift-check-failure-warning",
        alarmDescription: "Schema drift check failed to complete - monitoring gap",
        metric: driftCheckSuccess,
        threshold: 1,
        evaluationPeriods: 2,
        datapointsToAlarm: 2,
        comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.BREACHING,
      },
    );
    driftCheckFailureAlarm.addAlarmAction(
      new actions.SnsAction(this.warningAlarmTopic),
    );

    // Outputs for Schema Drift Alarms
    new cdk.CfnOutput(this, "SchemaDriftFakeFieldsAlarmName", {
      value: fakeFieldsAlarm.alarmName,
      description: "Alarm for fake fields in schema cache (Task 39)",
    });

    new cdk.CfnOutput(this, "SchemaDriftFilterableCoverageAlarmName", {
      value: filterableCoverageAlarm.alarmName,
      description: "Alarm for low filterable coverage (Task 39)",
    });

    new cdk.CfnOutput(this, "SchemaDriftRelationshipCoverageAlarmName", {
      value: relationshipCoverageAlarm.alarmName,
      description: "Alarm for low relationship coverage (Task 39)",
    });

    new cdk.CfnOutput(this, "SchemaDriftObjectsCoveredAlarmName", {
      value: objectsCoveredAlarm.alarmName,
      description: "Alarm for insufficient objects in cache (Task 39)",
    });

    // Tag all resources
    cdk.Tags.of(this).add("Component", "Monitoring");
  }
}
