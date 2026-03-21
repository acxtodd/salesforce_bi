# Model Benchmark Scorecard

Generated: 2026-03-21 12:01 UTC
Queries: 12 (4 simple, 4 medium, 4 hard)

## Summary

| Model | Avg Quality | Avg Latency | Tool Accuracy | Keyword Hit | Errors | Est. Cost/query |
|-------|------------|-------------|---------------|-------------|--------|-----------------|
| Claude Sonnet 4.6 | 41/100 | 11.3s | 92% | 17% | 0/12 | ~$0.0165 |
| Claude Sonnet 4.5 | 42/100 | 11.4s | 92% | 17% | 0/12 | ~$0.0165 |
| Claude Sonnet 4 | 42/100 | 9.3s | 92% | 17% | 0/12 | ~$0.0165 |
| Claude Haiku 4.5 | 39/100 | 7.8s | 83% | 17% | 0/12 | ~$0.0044 |
| Amazon Nova Pro | 39/100 | 5.9s | 83% | 17% | 0/12 | ~$0.0040 |
| Amazon Nova Lite | 38/100 | 6.0s | 83% | 17% | 0/12 | ~$0.0003 |
| Mistral Large 3 | 41/100 | 5.0s | 92% | 17% | 0/12 | ~$0.0090 |
| MiniMax M2.5 | 39/100 | 10.0s | 83% | 17% | 0/12 | ~$0.0055 |

**Best value:** Amazon Nova Lite (quality 38, latency 6.0s, ~$0.0003/query)

## Detailed Results

### Property lookup by city (simple)
> Show me all properties in Austin, Texas

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 45 | 18.2s | Y | 0/1 | Y |  |
| Claude Sonnet 4.5 | 45 | 17.3s | Y | 0/1 | Y |  |
| Claude Sonnet 4 | 45 | 15.4s | Y | 0/1 | Y |  |
| Claude Haiku 4.5 | 35 | 3.8s | Y | 0/1 | N |  |
| Amazon Nova Pro | 35 | 3.0s | Y | 0/1 | N |  |
| Amazon Nova Lite | 35 | 3.2s | Y | 0/1 | N |  |
| Mistral Large 3 | 45 | 12.2s | Y | 0/1 | Y |  |
| MiniMax M2.5 | 45 | 9.1s | Y | 0/1 | Y |  |

### Count with filter (simple)
> How many active leases do we have?

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 60 | 5.1s | Y | 0/0 | N |  |
| Claude Sonnet 4.5 | 60 | 4.2s | Y | 0/0 | N |  |
| Claude Sonnet 4 | 60 | 5.1s | Y | 0/0 | N |  |
| Claude Haiku 4.5 | 60 | 3.8s | Y | 0/0 | N |  |
| Amazon Nova Pro | 57 | 4.9s | Y | 0/0 | N |  |
| Amazon Nova Lite | 65 | 8.0s | Y | 0/0 | Y |  |
| Mistral Large 3 | 60 | 2.3s | Y | 0/0 | N |  |
| MiniMax M2.5 | 57 | 6.6s | Y | 0/0 | N |  |

### Contact search (simple)
> Find contacts at CBRE

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 45 | 9.5s | Y | 0/1 | Y |  |
| Claude Sonnet 4.5 | 45 | 24.4s | Y | 0/1 | Y |  |
| Claude Sonnet 4 | 45 | 10.2s | Y | 0/1 | Y |  |
| Claude Haiku 4.5 | 45 | 6.0s | Y | 0/1 | Y |  |
| Amazon Nova Pro | 45 | 8.8s | Y | 0/1 | Y |  |
| Amazon Nova Lite | 45 | 4.6s | Y | 0/1 | Y |  |
| Mistral Large 3 | 45 | 19.9s | Y | 0/1 | Y |  |
| MiniMax M2.5 | 45 | 8.5s | Y | 0/1 | Y |  |

### Availability with rent filter (simple)
> Show availabilities with asking rent under $25 per square foot

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 35 | 9.8s | Y | 0/1 | N |  |
| Claude Sonnet 4.5 | 45 | 15.5s | Y | 0/1 | Y |  |
| Claude Sonnet 4 | 45 | 11.3s | Y | 0/1 | Y |  |
| Claude Haiku 4.5 | 45 | 7.8s | Y | 0/1 | Y |  |
| Amazon Nova Pro | 45 | 11.1s | Y | 0/1 | Y |  |
| Amazon Nova Lite | 45 | 5.8s | Y | 0/1 | Y |  |
| Mistral Large 3 | 32 | 3.0s | Y | 0/1 | N |  |
| MiniMax M2.5 | 40 | 19.4s | Y | 0/1 | Y |  |

### Top deals by fee (medium)
> What are the top 10 deals by company fee in the Dallas market?

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 45 | 15.2s | Y | 0/2 | Y |  |
| Claude Sonnet 4.5 | 45 | 11.9s | Y | 0/2 | Y |  |
| Claude Sonnet 4 | 45 | 12.2s | Y | 0/2 | Y |  |
| Claude Haiku 4.5 | 45 | 5.0s | Y | 0/2 | Y |  |
| Amazon Nova Pro | 40 | 11.6s | Y | 0/2 | Y |  |
| Amazon Nova Lite | 40 | 19.6s | Y | 0/2 | Y |  |
| Mistral Large 3 | 45 | 3.4s | Y | 0/2 | Y |  |
| MiniMax M2.5 | 42 | 20.1s | Y | 0/2 | Y |  |

### Breakdown by property class (medium)
> Break down our properties by class in Houston

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 45 | 5.9s | Y | 0/2 | Y |  |
| Claude Sonnet 4.5 | 45 | 7.0s | Y | 0/2 | Y |  |
| Claude Sonnet 4 | 45 | 6.8s | Y | 0/2 | Y |  |
| Claude Haiku 4.5 | 45 | 4.3s | Y | 0/2 | Y |  |
| Amazon Nova Pro | 45 | 3.4s | Y | 0/2 | Y |  |
| Amazon Nova Lite | 45 | 3.0s | Y | 0/2 | Y |  |
| Mistral Large 3 | 45 | 2.0s | Y | 0/2 | Y |  |
| MiniMax M2.5 | 45 | 4.2s | Y | 0/2 | Y |  |

### Lease comps with multiple filters (medium)
> Find lease comps in Dallas CBD for office space over 10,000 SF signed in the last 12 months

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 42 | 20.1s | Y | 0/2 | Y |  |
| Claude Sonnet 4.5 | 35 | 8.8s | Y | 0/2 | N |  |
| Claude Sonnet 4 | 35 | 8.8s | Y | 0/2 | N |  |
| Claude Haiku 4.5 | 35 | 6.2s | Y | 0/2 | N |  |
| Amazon Nova Pro | 32 | 5.9s | Y | 0/2 | N |  |
| Amazon Nova Lite | 30 | 6.7s | Y | 0/2 | N |  |
| Mistral Large 3 | 35 | 3.4s | Y | 0/2 | N |  |
| MiniMax M2.5 | 40 | 15.2s | Y | 0/2 | Y |  |

### Task search with status filter (medium)
> Show me all open tasks related to Aarden Equity

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 32 | 10.1s | Y | 0/1 | N |  |
| Claude Sonnet 4.5 | 35 | 7.4s | Y | 0/1 | N |  |
| Claude Sonnet 4 | 35 | 5.7s | Y | 0/1 | N |  |
| Claude Haiku 4.5 | 32 | 5.8s | Y | 0/1 | N |  |
| Amazon Nova Pro | 35 | 3.6s | Y | 0/1 | N |  |
| Amazon Nova Lite | 35 | 3.3s | Y | 0/1 | N |  |
| Mistral Large 3 | 35 | 2.5s | Y | 0/1 | N |  |
| MiniMax M2.5 | 40 | 16.0s | Y | 0/1 | Y |  |

### Cross-city comparison (hard)
> Compare total deal volume in Dallas vs Houston vs Austin

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 35 | 9.0s | Y | 0/3 | N |  |
| Claude Sonnet 4.5 | 35 | 11.2s | Y | 0/3 | N |  |
| Claude Sonnet 4 | 35 | 9.7s | Y | 0/3 | N |  |
| Claude Haiku 4.5 | 35 | 4.3s | Y | 0/3 | N |  |
| Amazon Nova Pro | 45 | 4.2s | Y | 0/3 | Y |  |
| Amazon Nova Lite | 40 | 6.1s | Y | 0/3 | Y |  |
| Mistral Large 3 | 35 | 3.3s | Y | 0/3 | N |  |
| MiniMax M2.5 | 5 | 3.2s | N | 0/3 | N |  |

### Multi-object broker activity (hard)
> Show all deals, leases, and inquiries involving Colliers in any role

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 45 | 19.6s | Y | 0/1 | Y |  |
| Claude Sonnet 4.5 | 45 | 18.4s | Y | 0/1 | Y |  |
| Claude Sonnet 4 | 45 | 17.8s | Y | 0/1 | Y |  |
| Claude Haiku 4.5 | 45 | 12.6s | Y | 0/1 | Y |  |
| Amazon Nova Pro | 45 | 6.7s | Y | 0/1 | Y |  |
| Amazon Nova Lite | 45 | 4.7s | Y | 0/1 | Y |  |
| Mistral Large 3 | 45 | 4.0s | Y | 0/1 | Y |  |
| MiniMax M2.5 | 45 | 9.2s | Y | 0/1 | Y |  |

### Advisory with runnable suggestion (hard)
> How would I find which properties have the most availability right now?

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 35 | 6.4s | Y | 0/2 | N |  |
| Claude Sonnet 4.5 | 35 | 5.2s | Y | 0/2 | N |  |
| Claude Sonnet 4 | 35 | 4.4s | Y | 0/2 | N |  |
| Claude Haiku 4.5 | 15 | 6.8s | N | 0/2 | Y |  |
| Amazon Nova Pro | 15 | 4.4s | N | 0/2 | Y |  |
| Amazon Nova Lite | 5 | 4.7s | N | 0/2 | N |  |
| Mistral Large 3 | 35 | 1.9s | Y | 0/2 | N |  |
| MiniMax M2.5 | 35 | 4.1s | Y | 0/2 | N |  |

### Ambiguous leaderboard (hard)
> Who are the top performing brokers?

| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |
|-------|---------|---------|-------|----------|-----------|----------------|
| Claude Sonnet 4.6 | 30 | 6.4s | N | 0/0 | N |  |
| Claude Sonnet 4.5 | 30 | 5.4s | N | 0/0 | N |  |
| Claude Sonnet 4 | 30 | 4.7s | N | 0/0 | N |  |
| Claude Haiku 4.5 | 30 | 26.8s | N | 0/0 | N |  |
| Amazon Nova Pro | 30 | 2.9s | N | 0/0 | N |  |
| Amazon Nova Lite | 30 | 3.0s | N | 0/0 | N |  |
| Mistral Large 3 | 30 | 2.4s | N | 0/0 | N |  |
| MiniMax M2.5 | 30 | 4.7s | N | 0/0 | N |  |
