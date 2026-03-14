import * as cdk from 'aws-cdk-lib';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';

interface CloudWatchInsightsQueriesProps {
  retrieveLambdaLogGroup: logs.ILogGroup;
  answerLambdaLogGroup?: logs.ILogGroup;
  authzLambdaLogGroup: logs.ILogGroup;
}

export class CloudWatchInsightsQueries extends Construct {
  public readonly queryDefinitions: logs.CfnQueryDefinition[];

  constructor(scope: Construct, id: string, props: CloudWatchInsightsQueriesProps) {
    super(scope, id);

    const { retrieveLambdaLogGroup, answerLambdaLogGroup, authzLambdaLogGroup } = props;

    this.queryDefinitions = [];

    // Helper to build log group list
    const getLogGroups = (groups: (logs.ILogGroup | undefined)[]) => {
      return groups
        .filter((g): g is logs.ILogGroup => !!g)
        .map(g => g.logGroupName);
    };

    const allGroups = getLogGroups([retrieveLambdaLogGroup, answerLambdaLogGroup, authzLambdaLogGroup]);
    const apiGroups = getLogGroups([retrieveLambdaLogGroup, answerLambdaLogGroup]);
    const answerGroup = getLogGroups([answerLambdaLogGroup]);
    const retrieveGroup = getLogGroups([retrieveLambdaLogGroup]);
    const authzGroup = getLogGroups([authzLambdaLogGroup]);

    // Query 1: Top 10 Queries by Latency
    if (apiGroups.length > 0) {
      const topQueriesByLatency = new logs.CfnQueryDefinition(this, 'TopQueriesByLatency', {
        name: 'Salesforce-AI-Search/Top-10-Queries-By-Latency',
        queryString: `fields @timestamp, query, totalMs, endpoint, salesforceUserId
| filter endpoint = "/answer" or endpoint = "/retrieve"
| sort totalMs desc
| limit 10`,
        logGroupNames: apiGroups,
      });
      this.queryDefinitions.push(topQueriesByLatency);
    }

    // Query 2: AuthZ Denial Rate
    const authzDenialRate = new logs.CfnQueryDefinition(this, 'AuthzDenialRate', {
      name: 'Salesforce-AI-Search/AuthZ-Denial-Rate',
      queryString: `fields @timestamp, preFilterCount, postFilterCount
| filter postFilterCount < preFilterCount
| stats count(*) as denials, sum(preFilterCount - postFilterCount) as totalDenied by bin(5m)
| sort @timestamp desc`,
      logGroupNames: retrieveGroup,
    });
    this.queryDefinitions.push(authzDenialRate);

    // Query 3: Error Rate by Type
    if (allGroups.length > 0) {
      const errorRateByType = new logs.CfnQueryDefinition(this, 'ErrorRateByType', {
        name: 'Salesforce-AI-Search/Error-Rate-By-Type',
        queryString: `fields @timestamp, level, message, error, errorType
| filter level = "ERROR"
| stats count(*) as errorCount by errorType
| sort errorCount desc`,
        logGroupNames: allGroups,
      });
      this.queryDefinitions.push(errorRateByType);
    }

    // Query 4: Average Latency by Endpoint
    if (apiGroups.length > 0) {
      const avgLatencyByEndpoint = new logs.CfnQueryDefinition(this, 'AvgLatencyByEndpoint', {
        name: 'Salesforce-AI-Search/Average-Latency-By-Endpoint',
        queryString: `fields @timestamp, endpoint, totalMs
| filter ispresent(totalMs)
| stats avg(totalMs) as avgLatency, max(totalMs) as maxLatency, min(totalMs) as minLatency, count(*) as requestCount by endpoint
| sort avgLatency desc`,
        logGroupNames: apiGroups,
      });
      this.queryDefinitions.push(avgLatencyByEndpoint);
    }

    // Query 5: Cache Hit Rate Analysis
    const cacheHitRateAnalysis = new logs.CfnQueryDefinition(this, 'CacheHitRateAnalysis', {
      name: 'Salesforce-AI-Search/Cache-Hit-Rate-Analysis',
      queryString: `fields @timestamp, salesforceUserId, cached
| filter ispresent(cached)
| stats count(*) as total, sum(cached) as hits by bin(5m)
| fields @timestamp, (hits / total * 100) as hitRatePercent, total, hits
| sort @timestamp desc`,
      logGroupNames: authzGroup,
    });
    this.queryDefinitions.push(cacheHitRateAnalysis);

    // Query 6: Slow Queries (p95 threshold)
    if (apiGroups.length > 0) {
      const slowQueries = new logs.CfnQueryDefinition(this, 'SlowQueries', {
        name: 'Salesforce-AI-Search/Slow-Queries-Above-P95',
        queryString: `fields @timestamp, query, totalMs, endpoint, salesforceUserId, trace
| filter totalMs > 1000
| sort totalMs desc
| limit 50`,
        logGroupNames: apiGroups,
      });
      this.queryDefinitions.push(slowQueries);
    }

    // Query 7: User Activity Analysis
    if (apiGroups.length > 0) {
      const userActivityAnalysis = new logs.CfnQueryDefinition(this, 'UserActivityAnalysis', {
        name: 'Salesforce-AI-Search/User-Activity-Analysis',
        queryString: `fields @timestamp, salesforceUserId, endpoint, query
| filter ispresent(salesforceUserId)
| stats count(*) as queryCount by salesforceUserId
| sort queryCount desc
| limit 20`,
        logGroupNames: apiGroups,
      });
      this.queryDefinitions.push(userActivityAnalysis);
    }

    // Query 8: First Token Latency Analysis
    if (answerGroup.length > 0) {
      const firstTokenLatency = new logs.CfnQueryDefinition(this, 'FirstTokenLatency', {
        name: 'Salesforce-AI-Search/First-Token-Latency-Analysis',
        queryString: `fields @timestamp, query, trace.firstTokenMs as firstTokenMs, trace.totalMs as totalMs
| filter ispresent(firstTokenMs)
| stats avg(firstTokenMs) as avgFirstToken, max(firstTokenMs) as maxFirstToken, pct(firstTokenMs, 95) as p95FirstToken by bin(5m)
| sort @timestamp desc`,
        logGroupNames: answerGroup,
      });
      this.queryDefinitions.push(firstTokenLatency);
    }

    // Query 9: Retrieval Quality Metrics
    const retrievalQualityMetrics = new logs.CfnQueryDefinition(this, 'RetrievalQualityMetrics', {
      name: 'Salesforce-AI-Search/Retrieval-Quality-Metrics',
      queryString: `fields @timestamp, matchCount, trace.preFilterCount as preFilter, trace.postFilterCount as postFilter
| filter ispresent(matchCount)
| stats avg(matchCount) as avgMatches, avg(preFilter) as avgPreFilter, avg(postFilter) as avgPostFilter, count(*) as queries by bin(5m)
| fields @timestamp, avgMatches, avgPreFilter, avgPostFilter, (avgPostFilter / avgPreFilter * 100) as authzPassRate, queries
| sort @timestamp desc`,
      logGroupNames: retrieveGroup,
    });
    this.queryDefinitions.push(retrievalQualityMetrics);

    // Query 10: Citation Validation Analysis
    if (answerGroup.length > 0) {
      const citationValidation = new logs.CfnQueryDefinition(this, 'CitationValidation', {
        name: 'Salesforce-AI-Search/Citation-Validation-Analysis',
        queryString: `fields @timestamp, query, trace.citationCount as validCitations, trace.invalidCitationCount as invalidCitations
| filter ispresent(validCitations)
| stats avg(validCitations) as avgValid, avg(invalidCitations) as avgInvalid, sum(invalidCitations) as totalInvalid by bin(5m)
| fields @timestamp, avgValid, avgInvalid, totalInvalid, (avgInvalid / (avgValid + avgInvalid) * 100) as invalidRate
| sort @timestamp desc`,
        logGroupNames: answerGroup,
      });
      this.queryDefinitions.push(citationValidation);
    }

    // Query 11: Error Investigation
    if (allGroups.length > 0) {
      const errorInvestigation = new logs.CfnQueryDefinition(this, 'ErrorInvestigation', {
        name: 'Salesforce-AI-Search/Error-Investigation',
        queryString: `fields @timestamp, level, message, error, errorType, requestId, salesforceUserId, stackTrace
| filter level = "ERROR"
| sort @timestamp desc
| limit 100`,
        logGroupNames: allGroups,
      });
      this.queryDefinitions.push(errorInvestigation);
    }

    // Query 12: Request Trace Analysis
    if (apiGroups.length > 0) {
      const requestTraceAnalysis = new logs.CfnQueryDefinition(this, 'RequestTraceAnalysis', {
        name: 'Salesforce-AI-Search/Request-Trace-Analysis',
        queryString: `fields @timestamp, requestId, endpoint, trace.authzMs, trace.retrieveMs, trace.generateMs, trace.totalMs
| filter ispresent(requestId)
| sort @timestamp desc
| limit 50`,
        logGroupNames: apiGroups,
      });
      this.queryDefinitions.push(requestTraceAnalysis);
    }

    // Query 13: No Results Analysis
    const noResultsAnalysis = new logs.CfnQueryDefinition(this, 'NoResultsAnalysis', {
      name: 'Salesforce-AI-Search/No-Results-Analysis',
      queryString: `fields @timestamp, query, salesforceUserId, matchCount, filters
| filter matchCount = 0 or postFilterCount = 0
| stats count(*) as noResultCount by query
| sort noResultCount desc
| limit 20`,
      logGroupNames: retrieveGroup,
    });
    this.queryDefinitions.push(noResultsAnalysis);

    // Query 14: Bedrock Throttling Detection
    if (apiGroups.length > 0) {
      const bedrockThrottling = new logs.CfnQueryDefinition(this, 'BedrockThrottling', {
        name: 'Salesforce-AI-Search/Bedrock-Throttling-Detection',
        queryString: `fields @timestamp, message, error
| filter message like /throttl/i or error like /throttl/i
| stats count(*) as throttleCount by bin(5m)
| sort @timestamp desc`,
        logGroupNames: apiGroups,
      });
      this.queryDefinitions.push(bedrockThrottling);
    }

    // Query 15: Performance Breakdown by Stage
    if (answerGroup.length > 0) {
      const performanceBreakdown = new logs.CfnQueryDefinition(this, 'PerformanceBreakdown', {
        name: 'Salesforce-AI-Search/Performance-Breakdown-By-Stage',
        queryString: `fields @timestamp, 
  trace.authzMs as authz, 
  trace.retrieveMs as retrieve, 
  trace.promptMs as prompt,
  trace.firstTokenMs as firstToken,
  trace.generateMs as generate,
  trace.citationMs as citation,
  trace.totalMs as total
| filter ispresent(total)
| stats avg(authz) as avgAuthz, avg(retrieve) as avgRetrieve, avg(prompt) as avgPrompt, avg(firstToken) as avgFirstToken, avg(generate) as avgGenerate, avg(citation) as avgCitation, avg(total) as avgTotal by bin(5m)
| sort @timestamp desc`,
        logGroupNames: answerGroup,
      });
      this.queryDefinitions.push(performanceBreakdown);
    }
  }
}
