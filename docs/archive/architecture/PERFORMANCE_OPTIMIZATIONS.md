# Performance Optimizations Implementation Summary

## Overview

This document summarizes the performance optimizations implemented for the Salesforce AI Search POC to meet latency targets and improve user experience.

## Implemented Optimizations

### 1. AuthZ Context Caching (Task 12.1)

**Implementation:**
- DynamoDB table `authz_cache_table` with 24-hour TTL
- Cache check before computing authorization context
- CloudWatch metrics for cache hit/miss tracking

**Key Features:**
- **Cache TTL:** 24 hours (configurable via `CACHE_TTL_HOURS`)
- **Cache Key:** Salesforce User ID
- **Cached Data:** Sharing buckets, FLS profile tags, computed timestamp
- **Metrics:** `CacheHit` and `CacheMiss` metrics in `SalesforceAISearch/AuthZ` namespace

**Performance Impact:**
- Cache hit latency: <10ms (vs 200ms for cache miss)
- Target cache hit rate: >95%
- Reduces Salesforce API calls by ~95%

**Code Location:**
- Lambda: `lambda/authz/index.py`
- Infrastructure: `lib/data-stack.ts` (DynamoDB table)
- Metrics: CloudWatch custom metrics

### 2. Lambda Provisioned Concurrency (Task 12.2)

**Implementation:**
- Provisioned concurrency configured for Retrieve and Answer Lambdas
- Lambda aliases created for version management
- CloudWatch alarms for utilization monitoring

**Configuration:**
- **Retrieve Lambda:** 5 provisioned concurrent executions
- **Answer Lambda:** 5 provisioned concurrent executions
- **Alias Name:** `live` (used by API Gateway)

**Performance Impact:**
- Eliminates cold start latency (~1-3 seconds)
- Consistent p95 latency for first token
- Improved user experience for interactive queries

**Monitoring:**
- Utilization alarms trigger at 80% threshold
- Metrics tracked: `ProvisionedConcurrencyUtilization`
- Evaluation period: 5 minutes, 2 consecutive periods

**Code Location:**
- Infrastructure: `lib/api-stack.ts`
- Alarms: CloudWatch alarms for utilization

### 3. Retrieval Results Caching (Task 12.3)

**Implementation:**
- In-memory LRU cache with TTL for retrieval results
- Cache key based on query hash (query + filters + topK + userId)
- CloudWatch metrics for cache performance

**Configuration:**
- **Cache TTL:** 60 seconds (configurable via `CACHE_TTL_SECONDS`)
- **Max Cache Size:** 100 queries (configurable via `CACHE_MAX_SIZE`)
- **Cache Strategy:** LRU (Least Recently Used) eviction

**Key Features:**
- Deterministic cache key generation using SHA-256 hash
- Automatic expiration based on TTL
- LRU eviction when cache is full
- Persists across warm Lambda invocations

**Performance Impact:**
- Cache hit latency: <5ms (vs 200-400ms for Bedrock KB query)
- Target cache hit rate: >60% for repeated queries
- Reduces Bedrock KB API calls and costs

**Metrics:**
- `RetrievalCacheHit` and `RetrievalCacheMiss` in `SalesforceAISearch/Retrieve` namespace
- Cache check time tracked in `trace.cacheCheckMs`
- Cache status included in response trace

**Code Location:**
- Lambda: `lambda/retrieve/index.py`
- Cache class: `RetrievalCache` with LRU implementation
- Environment variables: `CACHE_TTL_SECONDS`, `CACHE_MAX_SIZE`

## Performance Targets

### Latency Targets (from Requirements)

| Metric | Target | Optimization Impact |
|--------|--------|---------------------|
| p95 First Token Latency | ≤800ms | Provisioned concurrency eliminates cold starts |
| p95 End-to-End Latency | ≤4.0s | All three optimizations contribute |
| AuthZ Cache Hit Rate | >95% | Task 12.1 implementation |
| Retrieval Cache Hit Rate | >60% | Task 12.3 implementation |

### Expected Performance Improvements

**Without Optimizations:**
- Cold start: 1-3 seconds
- AuthZ computation: 200ms per request
- Bedrock KB query: 200-400ms per request
- Total p95: ~5-7 seconds

**With Optimizations:**
- Cold start: 0ms (provisioned concurrency)
- AuthZ computation: <10ms (95% cache hit rate)
- Bedrock KB query: <5ms (60% cache hit rate)
- Total p95: ~800ms-1.5s (meets targets)

## Monitoring and Observability

### CloudWatch Metrics

**AuthZ Cache Metrics:**
- Namespace: `SalesforceAISearch/AuthZ`
- Metrics: `CacheHit`, `CacheMiss`
- Dimensions: None (function-level)

**Retrieval Cache Metrics:**
- Namespace: `SalesforceAISearch/Retrieve`
- Metrics: `RetrievalCacheHit`, `RetrievalCacheMiss`
- Dimensions: None (function-level)

**Provisioned Concurrency Metrics:**
- Namespace: `AWS/Lambda`
- Metrics: `ProvisionedConcurrencyUtilization`
- Dimensions: `FunctionName`, `Resource` (alias)

### CloudWatch Alarms

**Provisioned Concurrency Utilization:**
- Alarm: `salesforce-ai-search-retrieve-provisioned-utilization`
- Threshold: 80% utilization
- Evaluation: 2 periods of 5 minutes
- Action: Alert to increase provisioned concurrency

**Provisioned Concurrency Utilization:**
- Alarm: `salesforce-ai-search-answer-provisioned-utilization`
- Threshold: 80% utilization
- Evaluation: 2 periods of 5 minutes
- Action: Alert to increase provisioned concurrency

### Telemetry Tracking

**Request Trace Fields:**
- `authzMs`: Time spent on AuthZ computation
- `cacheCheckMs`: Time spent checking retrieval cache
- `retrieveMs`: Time spent querying Bedrock KB
- `postFilterMs`: Time spent on post-filter validation
- `presignedUrlMs`: Time spent generating presigned URLs
- `totalMs`: Total request time
- `cached`: Boolean indicating if retrieval was cached
- `authzCached`: Boolean indicating if AuthZ was cached (from AuthZ context)

## Configuration

### Environment Variables

**AuthZ Lambda:**
- `AUTHZ_CACHE_TABLE`: DynamoDB table name for AuthZ cache
- `CACHE_TTL_HOURS`: Cache TTL in hours (default: 24)

**Retrieve Lambda:**
- `CACHE_TTL_SECONDS`: Retrieval cache TTL in seconds (default: 60)
- `CACHE_MAX_SIZE`: Maximum number of cached queries (default: 100)

### Tuning Recommendations

**AuthZ Cache:**
- Increase TTL to 48 hours if sharing rules change infrequently
- Monitor cache invalidation patterns
- Consider user-specific TTL based on role changes

**Retrieval Cache:**
- Increase TTL to 120 seconds for stable data
- Increase max size to 200 for high query volume
- Monitor cache hit rate and adjust based on query patterns

**Provisioned Concurrency:**
- Start with 5 instances per Lambda
- Monitor utilization and scale up if >80% consistently
- Consider auto-scaling based on CloudWatch metrics

## Cost Considerations

### Provisioned Concurrency Costs

**Pricing (us-east-1):**
- Provisioned concurrency: $0.0000041667 per GB-second
- Retrieve Lambda: 1GB × 5 instances = 5 GB-hours/hour
- Answer Lambda: 2GB × 5 instances = 10 GB-hours/hour
- Total: ~$220/month for 24/7 provisioned concurrency

**Optimization:**
- Use scheduled scaling to reduce provisioned concurrency during off-hours
- Monitor actual usage and adjust instance count
- Consider on-demand for low-traffic periods

### Cache Cost Savings

**AuthZ Cache:**
- Reduces Salesforce API calls by ~95%
- Saves ~$0.01 per 1000 requests (API call costs)
- DynamoDB costs: ~$5/month for 1M requests

**Retrieval Cache:**
- Reduces Bedrock KB API calls by ~60%
- Saves ~$0.10 per 1000 requests (Bedrock costs)
- No additional infrastructure costs (in-memory)

## Testing and Validation

### Performance Testing

**Load Testing:**
1. Simulate 10 concurrent users (POC target)
2. Measure p50, p95, p99 latency under load
3. Verify cache hit rates meet targets
4. Monitor provisioned concurrency utilization

**Cache Testing:**
1. Execute repeated queries to measure cache hit rate
2. Verify cache expiration behavior
3. Test cache eviction under high load
4. Measure cache check latency

**Cold Start Testing:**
1. Invoke Lambda after idle period (>15 minutes)
2. Verify provisioned concurrency eliminates cold starts
3. Compare latency with and without provisioned concurrency

### Validation Checklist

- [ ] AuthZ cache hit rate >95% in production
- [ ] Retrieval cache hit rate >60% for repeated queries
- [ ] p95 first token latency ≤800ms
- [ ] p95 end-to-end latency ≤4.0s
- [ ] Provisioned concurrency utilization <80% during peak hours
- [ ] CloudWatch metrics and alarms functioning correctly
- [ ] Cost monitoring and optimization in place

## Future Enhancements

### Additional Optimizations

1. **Query Result Prefetching:**
   - Predict common queries based on user patterns
   - Pre-warm cache with likely queries
   - Reduce perceived latency for common use cases

2. **Adaptive Cache TTL:**
   - Adjust TTL based on data freshness requirements
   - Shorter TTL for frequently updated objects
   - Longer TTL for stable reference data

3. **Distributed Caching:**
   - Use ElastiCache Redis for shared cache across Lambda instances
   - Increase cache hit rate for multi-instance deployments
   - Support cache invalidation across all instances

4. **Smart Provisioned Concurrency Scaling:**
   - Auto-scale based on CloudWatch metrics
   - Scheduled scaling for predictable traffic patterns
   - Cost optimization during off-peak hours

5. **Query Optimization:**
   - Analyze slow queries and optimize filters
   - Implement query rewriting for common patterns
   - Use Bedrock KB query optimization features

## References

- Requirements: `.kiro/specs/salesforce-ai-search-poc/requirements.md` (Requirement 8.1, 8.2)
- Design: `.kiro/specs/salesforce-ai-search-poc/design.md`
- Tasks: `.kiro/specs/salesforce-ai-search-poc/tasks.md` (Task 12)
- AWS Lambda Provisioned Concurrency: https://docs.aws.amazon.com/lambda/latest/dg/provisioned-concurrency.html
- DynamoDB TTL: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/TTL.html
