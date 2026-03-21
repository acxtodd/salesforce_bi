# Model Benchmark Scorecard

Generated: 2026-03-21 12:23 UTC
Queries: 8 (2 simple, 3 medium, 3 hard)

## Summary

| Model | Avg Quality | Avg Latency | Tool Accuracy | Keyword Hit | Errors | Est. Cost/query |
|-------|------------|-------------|---------------|-------------|--------|-----------------|
| Claude Sonnet 4.6 | 38/100 | 11.6s | 100% | 0% | 0/8 | ~$0.0165 |
| Claude Sonnet 4.5 | 35/100 | 12.1s | 88% | 0% | 0/8 | ~$0.0165 |
| Claude Sonnet 4 | 38/100 | 8.4s | 100% | 0% | 0/8 | ~$0.0165 |
| Claude Haiku 4.5 | 37/100 | 5.8s | 100% | 0% | 0/8 | ~$0.0044 |
| Amazon Nova Pro | 36/100 | 5.6s | 88% | 0% | 0/8 | ~$0.0040 |
| Amazon Nova Lite | 32/100 | 5.2s | 88% | 0% | 0/8 | ~$0.0003 |
| Mistral Large 3 | 36/100 | 3.1s | 100% | 0% | 0/8 | ~$0.0090 |
| MiniMax M2.5 | 40/100 | 11.0s | 100% | 0% | 0/8 | ~$0.0055 |
| DeepSeek V3.2 | 19/100 | 14.9s | 38% | 0% | 0/8 | ~$0.0013 |
| GLM-5 | 34/100 | 13.2s | 88% | 0% | 0/8 | ~$0.0025 |

**Best value:** Amazon Nova Lite (quality 32, latency 5.2s, ~$0.0003/query)

## Detailed Results

### Property search with filter (simple)
> Show me Class A office properties in Dallas over 100,000 SF

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 35 | 9.0s | Y | 0/2 | N |  |
| Claude Sonnet 4.5 | 35 | 6.4s | Y | 0/2 | N |  |
| Claude Sonnet 4 | 35 | 6.5s | Y | 0/2 | N |  |
| Claude Haiku 4.5 | 35 | 5.0s | Y | 0/2 | N |  |
| Amazon Nova Pro | 35 | 4.9s | Y | 0/2 | N |  |
| Amazon Nova Lite | 35 | 3.7s | Y | 0/2 | N |  |
| Mistral Large 3 | 35 | 4.7s | Y | 0/2 | N |  |
| MiniMax M2.5 | 40 | 13.3s | Y | 0/2 | Y |  |
| DeepSeek V3.2 | 40 | 27.6s | Y | 0/2 | Y |  |
| GLM-5 | 35 | 11.3s | Y | 0/2 | N |  |

### Availability with rent filter (simple)
> Show availabilities with asking rent under $25 per square foot in Houston

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 35 | 8.5s | Y | 0/2 | N |  |
| Claude Sonnet 4.5 | 45 | 13.6s | Y | 0/2 | Y |  |
| Claude Sonnet 4 | 42 | 12.0s | Y | 0/2 | Y |  |
| Claude Haiku 4.5 | 35 | 4.5s | Y | 0/2 | N |  |
| Amazon Nova Pro | 42 | 6.0s | Y | 0/2 | Y |  |
| Amazon Nova Lite | 35 | 3.4s | Y | 0/2 | N |  |
| Mistral Large 3 | 35 | 3.0s | Y | 0/2 | N |  |
| MiniMax M2.5 | 40 | 11.8s | Y | 0/2 | Y |  |
| DeepSeek V3.2 | 5 | 30.2s | N | 0/2 | N |  |
| GLM-5 | 35 | 5.3s | Y | 0/2 | N |  |

### Top deals by fee (medium)
> What are the top 10 deals by company fee in the Dallas market?

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 45 | 13.7s | Y | 0/2 | Y |  |
| Claude Sonnet 4.5 | 45 | 9.3s | Y | 0/2 | Y |  |
| Claude Sonnet 4 | 45 | 7.3s | Y | 0/2 | Y |  |
| Claude Haiku 4.5 | 45 | 5.9s | Y | 0/2 | Y |  |
| Amazon Nova Pro | 45 | 5.7s | Y | 0/2 | Y |  |
| Amazon Nova Lite | 32 | 4.9s | Y | 0/2 | N |  |
| Mistral Large 3 | 35 | 3.0s | Y | 0/2 | N |  |
| MiniMax M2.5 | 45 | 10.2s | Y | 0/2 | Y |  |
| DeepSeek V3.2 | 5 | 30.4s | N | 0/2 | N |  |
| GLM-5 | 45 | 9.2s | Y | 0/2 | Y |  |

### Lease comps with multiple filters (medium)
> Find lease comps in Dallas for office space over 10,000 SF signed in the last 12 months

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 42 | 18.3s | Y | 0/2 | Y |  |
| Claude Sonnet 4.5 | 35 | 7.6s | Y | 0/2 | N |  |
| Claude Sonnet 4 | 35 | 5.5s | Y | 0/2 | N |  |
| Claude Haiku 4.5 | 35 | 5.6s | Y | 0/2 | N |  |
| Amazon Nova Pro | 35 | 4.3s | Y | 0/2 | N |  |
| Amazon Nova Lite | 30 | 6.6s | Y | 0/2 | N |  |
| Mistral Large 3 | 35 | 2.8s | Y | 0/2 | N |  |
| MiniMax M2.5 | 42 | 16.0s | Y | 0/2 | Y |  |
| DeepSeek V3.2 | 5 | 3.4s | N | 0/2 | N |  |
| GLM-5 | 40 | 20.8s | Y | 0/2 | Y |  |

### Task search with context (medium)
> Show me all open tasks related to Aarden Equity

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 32 | 9.4s | Y | 0/1 | N |  |
| Claude Sonnet 4.5 | 35 | 6.3s | Y | 0/1 | N |  |
| Claude Sonnet 4 | 35 | 7.5s | Y | 0/1 | N |  |
| Claude Haiku 4.5 | 32 | 5.7s | Y | 0/1 | N |  |
| Amazon Nova Pro | 35 | 4.0s | Y | 0/1 | N |  |
| Amazon Nova Lite | 32 | 6.2s | Y | 0/1 | N |  |
| Mistral Large 3 | 35 | 2.2s | Y | 0/1 | N |  |
| MiniMax M2.5 | 40 | 11.7s | Y | 0/1 | Y |  |
| DeepSeek V3.2 | 5 | 3.5s | N | 0/1 | N |  |
| GLM-5 | 35 | 5.3s | Y | 0/1 | N |  |

### Cross-city comparison (hard)
> Compare total deal volume in Dallas vs Houston vs Austin

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 35 | 9.3s | Y | 0/3 | N |  |
| Claude Sonnet 4.5 | 5 | 30.4s | N | 0/3 | N |  |
| Claude Sonnet 4 | 35 | 8.2s | Y | 0/3 | N |  |
| Claude Haiku 4.5 | 35 | 4.7s | Y | 0/3 | N |  |
| Amazon Nova Pro | 35 | 4.3s | Y | 0/3 | N |  |
| Amazon Nova Lite | 35 | 3.5s | Y | 0/3 | N |  |
| Mistral Large 3 | 35 | 3.8s | Y | 0/3 | N |  |
| MiniMax M2.5 | 35 | 7.3s | Y | 0/3 | N |  |
| DeepSeek V3.2 | 15 | 6.8s | N | 0/3 | Y |  |
| GLM-5 | 45 | 11.6s | Y | 0/3 | Y |  |

### Multi-object broker activity (hard)
> Show all deals, leases, and inquiries involving Colliers in any role

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 45 | 19.2s | Y | 0/1 | Y |  |
| Claude Sonnet 4.5 | 45 | 17.8s | Y | 0/1 | Y |  |
| Claude Sonnet 4 | 45 | 14.3s | Y | 0/1 | Y |  |
| Claude Haiku 4.5 | 45 | 11.4s | Y | 0/1 | Y |  |
| Amazon Nova Pro | 45 | 10.4s | Y | 0/1 | Y |  |
| Amazon Nova Lite | 45 | 4.7s | Y | 0/1 | Y |  |
| Mistral Large 3 | 45 | 3.1s | Y | 0/1 | Y |  |
| MiniMax M2.5 | 42 | 12.7s | Y | 0/1 | Y |  |
| DeepSeek V3.2 | 40 | 12.7s | Y | 0/1 | Y |  |
| GLM-5 | 5 | 30.2s | N | 0/1 | N |  |

### Advisory with runnable suggestion (hard)
> How would I find which properties have the most availability right now?

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 35 | 5.7s | Y | 0/2 | N |  |
| Claude Sonnet 4.5 | 35 | 5.6s | Y | 0/2 | N |  |
| Claude Sonnet 4 | 35 | 5.9s | Y | 0/2 | N |  |
| Claude Haiku 4.5 | 35 | 3.9s | Y | 0/2 | N |  |
| Amazon Nova Pro | 15 | 5.4s | N | 0/2 | Y |  |
| Amazon Nova Lite | 10 | 8.2s | N | 0/2 | Y |  |
| Mistral Large 3 | 35 | 2.0s | Y | 0/2 | N |  |
| MiniMax M2.5 | 35 | 4.8s | Y | 0/2 | N |  |
| DeepSeek V3.2 | 35 | 4.5s | Y | 0/2 | N |  |
| GLM-5 | 35 | 11.6s | Y | 0/2 | N |  |
