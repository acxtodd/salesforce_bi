# Freshness Lag Metrics and Monitoring

## Overview

This document explains the freshness lag metrics emitted by the CDC ingestion pipeline and how to monitor data freshness to ensure the P50 target of ≤5 minutes is met.

## Freshness Lag Definition

**Freshness Lag** is the time elapsed from when a record is modified in Salesforce until it becomes searchable in the AI Search system.

**Target**: P50 ≤ 5 minutes (50th percentile of all ingestion events)

## Metric Stages

The ingestion pipeline tracks lag at multiple stages:

### 1. CDC to S3 Lag

**Definition**: Time from Salesforce CDC commit to S3 object creation

**Components**:
- Salesforce CDC publish time (< 1 second)
- AppFlow polling interval (1-5 minutes, average 3 minutes)
- AppFlow processing and S3 write (< 10 seconds)

**Expected Range**: 1-5 minutes (P50: ~3 minutes)

**Metric Name**: `CDCToS3Lag`
**Namespace**: `SalesforceAISearch/Ingestion`
**Dimensions**: `SObject`, `Stage=CDCToS3`
**Unit**: Milliseconds

### 2. S3 to Processing Lag

**Definition**: Time from S3 object creation to CDC Processor Lambda start

**Components**:
- S3 EventBridge notification (< 1 second)
- EventBridge rule evaluation (< 1 second)
- Step Functions execution start (< 1 second)
- Lambda cold start (0-3 seconds with provisioned concurrency)

**Expected Range**: 1-5 seconds (P50: ~2 seconds)

**Metric Name**: `S3ToProcessingLag`
**Namespace**: `SalesforceAISearch/Ingestion`
**Dimensions**: `SObject`, `Stage=S3ToProcessing`
**Unit**: Milliseconds

### 3. Total Ingest Lag

**Definition**: Time from CDC Processor start to completion

**Components**:
- CDC Processor Lambda (< 5 seconds)
- Validate Lambda (< 2 seconds)
- Transform Lambda (< 3 seconds)
- Chunking Lambda (5-10 seconds)
- Enrich Lambda (< 3 seconds)
- Embed Lambda (10-30 seconds, depends on chunk count)
- Sync Lambda (< 5 seconds)

**Expected Range**: 30-60 seconds (P50: ~45 seconds)

**Metric Name**: `TotalIngestLag`
**Namespace**: `SalesforceAISearch/Ingestion`
**Dimensions**: `SObject`, `Stage=Total`
**Unit**: Milliseconds

### 4. End-to-End Lag

**Definition**: Time from Salesforce CDC commit to Sync Lambda completion

**Formula**: `CDCToS3Lag + S3ToProcessingLag + TotalIngestLag`

**Expected Range**: 2-6 minutes (P50: ~4 minutes)

**Target**: P50 ≤ 5 minutes

**Metric Name**: `EndToEndLag`
**Namespace**: `SalesforceAISearch/Ingestion`
**Dimensions**: `SObject`, `Stage=EndToEnd`
**Unit**: Milliseconds

## CloudWatch Dashboard

The freshness dashboard provides real-time visibility into ingestion lag:

**Dashboard Name**: `salesforce-ai-search-freshness`

**Widgets**:

1. **CDC to S3 Lag (P50, P95)**
   - Shows AppFlow polling and processing time
   - Helps identify AppFlow delays

2. **S3 to Processing Lag (P50, P95)**
   - Shows EventBridge and Lambda startup time
   - Helps identify cold start issues

3. **End-to-End Ingest Lag (P50, P95)**
   - Shows total time from Salesforce to indexed chunk
   - Includes 5-minute target line
   - Primary metric for freshness SLO

4. **Total Ingest Lag (P50, P95)**
   - Shows Step Functions execution time
   - Helps identify pipeline bottlenecks

5. **Chunks Synced by Object**
   - Shows ingestion volume by object type
   - Helps identify high-volume objects

6. **Step Functions Execution Duration**
   - Shows average execution time
   - Helps identify performance degradation

**Access Dashboard**:
```
https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=salesforce-ai-search-freshness
```

Or navigate to **CloudWatch** → **Dashboards** → **salesforce-ai-search-freshness**

## CloudWatch Alarms

### P50 Lag Alarm

**Alarm Name**: `salesforce-ai-search-p50-lag-high`

**Condition**: P50 end-to-end lag > 10 minutes for 2 consecutive 15-minute periods

**Threshold**: 600,000 milliseconds (10 minutes)

**Severity**: Warning

**Action**: Investigate AppFlow delays or pipeline bottlenecks

### P95 Lag Alarm

**Alarm Name**: `salesforce-ai-search-p95-lag-high`

**Condition**: P95 end-to-end lag > 15 minutes for 2 consecutive 15-minute periods

**Threshold**: 900,000 milliseconds (15 minutes)

**Severity**: Critical

**Action**: Immediate investigation required

## Querying Metrics

### CloudWatch Insights Queries

**Average lag by object (last hour)**:
```
fields @timestamp, SObject, EndToEndLag
| filter MetricName = "EndToEndLag"
| stats avg(EndToEndLag) as AvgLag by SObject
| sort AvgLag desc
```

**P50 and P95 lag (last 24 hours)**:
```
fields @timestamp, EndToEndLag
| filter MetricName = "EndToEndLag"
| stats pct(EndToEndLag, 50) as P50, pct(EndToEndLag, 95) as P95 by bin(1h)
```

**Lag distribution by stage**:
```
fields @timestamp, Stage, @value
| filter Namespace = "SalesforceAISearch/Ingestion"
| stats avg(@value) as AvgLag by Stage
```

### AWS CLI Queries

**Get P50 end-to-end lag (last hour)**:
```bash
aws cloudwatch get-metric-statistics \
  --namespace SalesforceAISearch/Ingestion \
  --metric-name EndToEndLag \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics p50 \
  --region us-east-1
```

**Get lag by object**:
```bash
aws cloudwatch get-metric-statistics \
  --namespace SalesforceAISearch/Ingestion \
  --metric-name EndToEndLag \
  --dimensions Name=SObject,Value=Account \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics p50,p95 \
  --region us-east-1
```

## Troubleshooting High Lag

### CDC to S3 Lag > 5 minutes

**Possible Causes**:
1. AppFlow polling interval too long
2. AppFlow throttling or errors
3. Salesforce API rate limits
4. Network connectivity issues

**Solutions**:
1. Check AppFlow execution history for delays
2. Review AppFlow CloudWatch Logs for errors
3. Verify Salesforce Connected App credentials
4. Check Salesforce API usage limits
5. Consider increasing AppFlow capacity (if available)

### S3 to Processing Lag > 10 seconds

**Possible Causes**:
1. Lambda cold starts
2. EventBridge rule delays
3. Step Functions throttling
4. VPC networking issues

**Solutions**:
1. Enable provisioned concurrency for CDC Processor Lambda
2. Check EventBridge metrics for rule invocations
3. Verify Step Functions execution limits
4. Check VPC endpoint connectivity
5. Review Lambda CloudWatch Logs for errors

### Total Ingest Lag > 2 minutes

**Possible Causes**:
1. Embedding API throttling (Bedrock)
2. Large chunk count (long documents)
3. Lambda timeout or memory issues
4. DynamoDB throttling
5. S3 write delays

**Solutions**:
1. Check Bedrock API throttling metrics
2. Optimize chunking strategy (reduce chunk count)
3. Increase Lambda memory allocation
4. Enable DynamoDB auto-scaling
5. Monitor S3 PUT request latency
6. Review Step Functions execution details

### End-to-End Lag > 10 minutes

**Possible Causes**:
1. Combination of above issues
2. System-wide performance degradation
3. High ingestion volume
4. Resource contention

**Solutions**:
1. Identify bottleneck stage using dashboard
2. Scale up resources (Lambda concurrency, DynamoDB capacity)
3. Implement batching for high-volume objects
4. Consider parallel processing for independent records
5. Review CloudWatch Logs for all pipeline stages

## Performance Optimization

### Reduce CDC to S3 Lag

- **AppFlow**: Cannot directly control polling frequency
- **Alternative**: Use Salesforce Platform Events with EventBridge (future enhancement)
- **Workaround**: Accept 1-5 minute lag as inherent to AppFlow

### Reduce S3 to Processing Lag

- **Provisioned Concurrency**: Eliminate Lambda cold starts
  ```typescript
  cdcProcessorLambda.addAlias('live', {
    provisionedConcurrentExecutions: 5,
  });
  ```
- **VPC Optimization**: Use VPC endpoints for all AWS services
- **EventBridge**: Already near-instant, no optimization needed

### Reduce Total Ingest Lag

- **Parallel Processing**: Process chunks in parallel (future enhancement)
- **Batch Embedding**: Call Bedrock with multiple chunks (up to 25)
- **Optimize Chunking**: Reduce chunk count for short documents
- **Increase Memory**: Allocate more memory to Lambda functions
- **Caching**: Cache embeddings for duplicate chunks

### Monitor and Iterate

1. Establish baseline metrics (first week)
2. Identify bottleneck stages
3. Implement targeted optimizations
4. Measure impact on P50/P95 lag
5. Iterate until P50 ≤ 5 minutes consistently

## Reporting

### Daily Freshness Report

Generate a daily report of freshness metrics:

```python
import boto3
from datetime import datetime, timedelta

cloudwatch = boto3.client('cloudwatch')

# Get P50 and P95 for last 24 hours
end_time = datetime.utcnow()
start_time = end_time - timedelta(hours=24)

response = cloudwatch.get_metric_statistics(
    Namespace='SalesforceAISearch/Ingestion',
    MetricName='EndToEndLag',
    StartTime=start_time,
    EndTime=end_time,
    Period=86400,  # 24 hours
    Statistics=['p50', 'p95', 'Average', 'Maximum']
)

for datapoint in response['Datapoints']:
    print(f"P50: {datapoint['p50']/1000:.1f}s")
    print(f"P95: {datapoint['p95']/1000:.1f}s")
    print(f"Avg: {datapoint['Average']/1000:.1f}s")
    print(f"Max: {datapoint['Maximum']/1000:.1f}s")
```

### Weekly Trend Analysis

Track P50 lag over time to identify trends:

```python
# Get P50 for last 7 days (daily buckets)
response = cloudwatch.get_metric_statistics(
    Namespace='SalesforceAISearch/Ingestion',
    MetricName='EndToEndLag',
    StartTime=datetime.utcnow() - timedelta(days=7),
    EndTime=datetime.utcnow(),
    Period=86400,  # 1 day
    Statistics=['p50']
)

# Plot trend
import matplotlib.pyplot as plt

timestamps = [dp['Timestamp'] for dp in response['Datapoints']]
p50_values = [dp['p50']/1000 for dp in response['Datapoints']]

plt.plot(timestamps, p50_values)
plt.axhline(y=300, color='r', linestyle='--', label='Target (5 min)')
plt.xlabel('Date')
plt.ylabel('P50 Lag (seconds)')
plt.title('End-to-End Lag Trend (P50)')
plt.legend()
plt.show()
```

## Best Practices

1. **Monitor Daily**: Check dashboard daily for anomalies
2. **Set Alerts**: Configure SNS notifications for alarms
3. **Baseline Metrics**: Establish normal ranges for each stage
4. **Investigate Spikes**: Immediately investigate P50 > 10 minutes
5. **Optimize Iteratively**: Focus on bottleneck stages first
6. **Document Changes**: Track optimizations and their impact
7. **Review Weekly**: Analyze trends and plan improvements
8. **Test Changes**: Measure impact of infrastructure changes

## References

- [CloudWatch Metrics](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/working_with_metrics.html)
- [CloudWatch Alarms](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/AlarmThatSendsEmail.html)
- [CloudWatch Dashboards](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Dashboards.html)
- [Step Functions Metrics](https://docs.aws.amazon.com/step-functions/latest/dg/procedure-cw-metrics.html)
