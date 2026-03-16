# Monitoring and Observability Implementation

## Overview

This document describes the monitoring and observability infrastructure implemented for the Salesforce AI Search POC. The implementation covers CloudWatch dashboards, alarms, structured logging, and CloudWatch Insights queries.

## Components Implemented

### 1. MonitoringStack (lib/monitoring-stack.ts)

A comprehensive CDK stack that creates all monitoring resources:

#### CloudWatch Dashboards

**API Performance Dashboard**
- Request count by endpoint
- Error rates (4xx and 5xx)
- API Gateway latency
- Lambda duration (p95)
- Lambda errors and throttles
- Concurrent executions

**Retrieval Quality Dashboard**
- Retrieval hit rate
- Average match count per query
- Precision metrics (P@5, P@10)
- AuthZ post-filter rejections
- Cache hit rates (AuthZ and retrieval)

**Freshness Dashboard**
- CDC event lag (P50 and P95)
- Ingest pipeline duration
- Bedrock KB sync lag
- Records processed per minute
- Failed ingestion count

**Cost Dashboard**
- Bedrock API invocations (embeddings and generation)
- Lambda invocations
- OpenSearch CPU utilization
- DynamoDB capacity units
- Estimated cost by TenantId

#### CloudWatch Alarms

**Critical Alarms** (routed to PagerDuty via SNS):
- API Gateway 5xx rate > 5% for 5 minutes
- Lambda error rate > 10% for 5 minutes
- OpenSearch cluster status = Red
- Bedrock throttling rate > 20% for 5 minutes
- AuthZ cache miss rate > 50% for 10 minutes
- Ingestion pipeline failures > 10 in 5 minutes
- Composite system health alarm

**Warning Alarms** (routed to email via SNS):
- API p95 latency > 1.0s for 10 minutes
- First token latency > 1.0s for 10 minutes
- Retrieval precision@5 < 60%
- CDC lag P50 > 10 minutes for 15 minutes
- DynamoDB throttling detected

#### Log Groups

- Configured 90-day retention for all Lambda function logs
- Structured JSON logging format
- Log groups created for:
  - Retrieve Lambda
  - Answer Lambda
  - AuthZ Lambda

### 2. CloudWatch Insights Queries (lib/cloudwatch-insights-queries.ts)

15 pre-configured queries for common analysis patterns:

1. **Top 10 Queries by Latency** - Identify slowest queries
2. **AuthZ Denial Rate** - Track authorization filtering effectiveness
3. **Error Rate by Type** - Categorize errors for troubleshooting
4. **Average Latency by Endpoint** - Monitor endpoint performance
5. **Cache Hit Rate Analysis** - Optimize caching strategy
6. **Slow Queries Above P95** - Investigate performance outliers
7. **User Activity Analysis** - Track top users by query count
8. **First Token Latency Analysis** - Monitor streaming performance
9. **Retrieval Quality Metrics** - Track match counts and authZ pass rate
10. **Citation Validation Analysis** - Monitor citation accuracy
11. **Error Investigation** - Deep dive into errors with stack traces
12. **Request Trace Analysis** - Analyze timing breakdown by stage
13. **No Results Analysis** - Identify queries with zero results
14. **Bedrock Throttling Detection** - Detect API throttling issues
15. **Performance Breakdown by Stage** - Analyze latency by pipeline stage

### 3. Structured Logging Utility (lambda/common/structured_logger.py)

A reusable Python module for structured JSON logging:

**Features:**
- Consistent JSON format across all Lambda functions
- Automatic timestamp and requestId inclusion
- Elapsed time tracking
- Support for metadata fields
- Exception logging with stack traces
- Log level configuration via environment variable

**Usage Example:**
```python
from common.structured_logger import create_logger

logger = create_logger(__name__, request_id)
logger.info("Processing request", 
    salesforceUserId=user_id,
    query=query,
    topK=top_k)
```

## Configuration

### Environment Variables

**Monitoring Stack:**
- `CRITICAL_ALARM_EMAIL` - Email for critical alarm notifications
- `WARNING_ALARM_EMAIL` - Email for warning alarm notifications

**Lambda Functions:**
- `LOG_LEVEL` - Logging level (INFO, DEBUG, WARNING, ERROR)

### SNS Topics

Two SNS topics are created for alarm notifications:
- `salesforce-ai-search-critical-alarms` - For critical issues requiring immediate attention
- `salesforce-ai-search-warning-alarms` - For warnings requiring investigation

## Deployment

The MonitoringStack should be deployed after the API, Data, and Search stacks:

```bash
cdk deploy MonitoringStack
```

## Accessing Dashboards

Dashboard URLs are provided as CloudFormation outputs:
- API Performance Dashboard
- Retrieval Quality Dashboard
- Freshness Dashboard
- Cost Dashboard

Access via AWS Console:
```
CloudWatch → Dashboards → Salesforce-AI-Search-*
```

## Accessing CloudWatch Insights Queries

Saved queries are available in CloudWatch Logs Insights:
```
CloudWatch → Logs → Insights → Saved queries → Salesforce-AI-Search/*
```

## Metrics Published

Custom metrics published to the `SalesforceAISearch` namespace:

**Retrieval Metrics:**
- `RetrievalHitRate` - Percentage of queries with results
- `MatchCount` - Number of matches per query
- `AuthzPostFilterRejections` - Records filtered by authorization
- `AuthzCacheHitRate` - Cache hit rate for authorization context
- `RetrievalCacheHitRate` - Cache hit rate for retrieval results
- `PrecisionAt5` - Precision at 5 results
- `PrecisionAt10` - Precision at 10 results

**Ingestion Metrics:**
- `CDCEventLag` - Time from CDC event to indexing
- `IngestPipelineDuration` - Total pipeline processing time
- `BedrockKBSyncLag` - Time for Bedrock KB sync
- `RecordsProcessed` - Number of records processed
- `FailedIngestions` - Number of failed ingestions

**Answer Generation Metrics:**
- `FirstTokenLatency` - Time to first token in streaming response
- `CitationCount` - Number of valid citations
- `InvalidCitationCount` - Number of invalid citations

**Cost Metrics:**
- `EstimatedCost` - Estimated cost by TenantId

## Best Practices

1. **Review dashboards daily** during POC phase to identify issues early
2. **Set up alarm notifications** to appropriate channels (PagerDuty, email, Slack)
3. **Use CloudWatch Insights queries** for troubleshooting and analysis
4. **Monitor cost dashboard** to track spending and optimize resources
5. **Adjust alarm thresholds** based on actual usage patterns
6. **Archive logs to S3** for long-term retention (1 year)

## Future Enhancements

- Add X-Ray tracing for distributed request tracing
- Implement custom metrics for business KPIs
- Add anomaly detection for automatic issue identification
- Create Grafana dashboards for advanced visualization
- Implement log aggregation with Elasticsearch
- Add performance profiling for Lambda functions
- Create automated reports for stakeholders

## Troubleshooting

### High Error Rates
1. Check Error Investigation query in CloudWatch Insights
2. Review Lambda function logs for stack traces
3. Check API Gateway logs for request/response details
4. Verify upstream service health (Bedrock, OpenSearch, Salesforce)

### High Latency
1. Use Performance Breakdown query to identify bottlenecks
2. Check cache hit rates - low rates indicate cache issues
3. Review OpenSearch cluster metrics
4. Check Bedrock throttling metrics
5. Analyze slow queries for optimization opportunities

### Low Retrieval Quality
1. Review Retrieval Quality dashboard
2. Check precision metrics against targets
3. Analyze no results queries
4. Review AuthZ post-filter rejection rate
5. Investigate match count distribution

### Cost Overruns
1. Review Cost Dashboard for spending trends
2. Check Bedrock invocation counts
3. Review Lambda execution counts and duration
4. Analyze DynamoDB capacity usage
5. Optimize caching to reduce API calls

## References

- [AWS CloudWatch Documentation](https://docs.aws.amazon.com/cloudwatch/)
- [CloudWatch Insights Query Syntax](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html)
- [CDK CloudWatch Construct Library](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_cloudwatch-readme.html)
