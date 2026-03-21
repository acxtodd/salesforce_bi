# Model Benchmark Scorecard v4 — Stress Test

Generated: 2026-03-21 17:57 UTC
Queries: 10 (with clarification follow-up)
Models: 9

## Leaderboard

| Rank | Model | Avg Quality | Avg Latency | Tool Use | Citations | Clarify+Followup | Errors | Est. $/query |
|------|-------|-------------|-------------|----------|-----------|------------------|--------|-------------|
| 1 | Amazon Nova Pro | 44/100 | 7.9s | 100% | 90% | 0/10 | 0/10 | $0.0040 |
| 2 | MiniMax M2.5 | 42/100 | 18.6s | 100% | 60% | 4/10 | 0/10 | $0.0055 |
| 3 | Mistral Large 3 | 41/100 | 9.4s | 100% | 70% | 2/10 | 0/10 | $0.0090 |
| 4 | Claude Sonnet 4.6 | 40/100 | 19.2s | 100% | 60% | 3/10 | 0/10 | $0.0165 |
| 5 | Amazon Nova Lite | 40/100 | 7.3s | 100% | 70% | 1/10 | 0/10 | $0.0003 |
| 6 | Claude Haiku 4.5 | 40/100 | 9.5s | 100% | 60% | 2/10 | 0/10 | $0.0044 |
| 7 | Claude Sonnet 4 | 38/100 | 15.4s | 90% | 50% | 2/10 | 0/10 | $0.0165 |
| 8 | GLM-5 | 36/100 | 22.5s | 80% | 60% | 2/10 | 0/10 | $0.0025 |
| 9 | DeepSeek V3.2 | 28/100 | 12.0s | 60% | 50% | 1/10 | 0/10 | $0.0013 |

**Winner:** Amazon Nova Pro — quality 44/100, latency 7.9s, $0.0040/query

## Query Details

### 1. Direct property search [simple]
> **Query:** Show me Class A office properties in Dallas
> **Testing:** Baseline: can the model call search_records with basic filters?

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 9.3s | 2 | Y | - |  |
| Claude Sonnet 4.6 | 45 | 11.6s | 2 | Y | - |  |
| Claude Sonnet 4 | 45 | 10.7s | 2 | Y | - |  |
| Amazon Nova Pro | 45 | 7.2s | 2 | Y | - |  |
| Amazon Nova Lite | 40 | 7.1s | 4 | Y | - |  |
| Mistral Large 3 | 45 | 6.4s | 2 | Y | - |  |
| MiniMax M2.5 | 40 | 8.9s | 4 | Y | - |  |
| DeepSeek V3.2 | 45 | 9.2s | 2 | Y | - |  |
| GLM-5 | 45 | 14.1s | 2 | Y | - |  |

### 2. Count by category [simple]
> **Query:** How many deals do we have by market?
> **Testing:** Baseline: can the model call aggregate_records with group_by?

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 6.5s | 2 | Y | - |  |
| Claude Sonnet 4.6 | 45 | 10.0s | 2 | Y | - |  |
| Claude Sonnet 4 | 45 | 10.4s | 2 | Y | - |  |
| Amazon Nova Pro | 40 | 7.4s | 4 | Y | - |  |
| Amazon Nova Lite | 45 | 6.1s | 2 | Y | - |  |
| Mistral Large 3 | 45 | 6.8s | 2 | Y | - |  |
| MiniMax M2.5 | 35 | 10.2s | 0 | - | Y->fail |  |
| DeepSeek V3.2 | 10 | 2.1s | 0 | - | - |  |
| GLM-5 | 45 | 19.6s | 2 | Y | - |  |

### 3. Top deals by fee [medium]
> **Query:** What are our top 10 deals by company fee?
> **Testing:** Tests sort_order + top_n on aggregate_records.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 6.3s | 2 | Y | - |  |
| Claude Sonnet 4.6 | 40 | 16.8s | 4 | Y | - |  |
| Claude Sonnet 4 | 45 | 9.2s | 2 | Y | - |  |
| Amazon Nova Pro | 45 | 5.5s | 2 | Y | - |  |
| Amazon Nova Lite | 45 | 3.8s | 2 | Y | - |  |
| Mistral Large 3 | 45 | 11.0s | 2 | Y | - |  |
| MiniMax M2.5 | 45 | 15.5s | 2 | Y | - |  |
| DeepSeek V3.2 | 35 | 8.6s | 0 | - | Y->fail |  |
| GLM-5 | 40 | 18.1s | 4 | Y | - |  |

### 4. Vague leaderboard [hard]
> **Query:** Who are our top brokers?
> **Testing:** Intentionally vague. Good models should ask: by deal count, fee, or volume? Which role?

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 6.6s | 0 | - | Y->fail |  |
| Claude Sonnet 4.6 | 45 | 21.2s | 0 | - | Y->fail |  |
| Claude Sonnet 4 | 45 | 22.4s | 0 | - | Y->fail |  |
| Amazon Nova Pro | 55 | 6.1s | 6 | Y | - |  |
| Amazon Nova Lite | 45 | 4.6s | 0 | - | Y->fail |  |
| Mistral Large 3 | 45 | 4.8s | 0 | - | Y->fail |  |
| MiniMax M2.5 | 45 | 34.6s | 0 | - | Y->fail |  |
| DeepSeek V3.2 | 20 | 3.2s | 0 | - | - |  |
| GLM-5 | 20 | 30.4s | 0 | - | - |  |

### 5. Market revenue with deal details [stress]
> **Query:** List the top 10 markets by revenue and the largest deal in each and the related property in that deal
> **Testing:** The hardest query. Requires: aggregate by market, then search top deal per market, then look up property. Multi-turn.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 35 | 22.5s | 38 | Y | - |  |
| Claude Sonnet 4.6 | 40 | 29.5s | 22 | Y | - |  |
| Claude Sonnet 4 | 10 | 30.2s | 0 | - | - |  |
| Amazon Nova Pro | 45 | 6.7s | 2 | Y | - |  |
| Amazon Nova Lite | 35 | 23.5s | 62 | Y | - |  |
| Mistral Large 3 | 35 | 30.1s | 28 | Y | - |  |
| MiniMax M2.5 | 45 | 39.1s | 2 | - | Y->fail |  |
| DeepSeek V3.2 | 10 | 3.7s | 0 | - | - |  |
| GLM-5 | 35 | 32.0s | 0 | - | Y->fail |  |

### 6. Broker involvement across objects [hard]
> **Query:** Show all deals, leases, and inquiries involving CBRE in any role
> **Testing:** Tests parallel tool calls across 3 object types.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 10.8s | 6 | Y | - |  |
| Claude Sonnet 4.6 | 45 | 20.0s | 6 | Y | - |  |
| Claude Sonnet 4 | 45 | 21.5s | 6 | Y | - |  |
| Amazon Nova Pro | 45 | 16.0s | 6 | Y | - |  |
| Amazon Nova Lite | 45 | 6.0s | 6 | Y | - |  |
| Mistral Large 3 | 45 | 9.9s | 14 | Y | - |  |
| MiniMax M2.5 | 45 | 16.0s | 6 | Y | - |  |
| DeepSeek V3.2 | 35 | 11.9s | 6 | Y | - |  |
| GLM-5 | 45 | 27.0s | 6 | Y | - |  |

### 7. Vague market analysis [hard]
> **Query:** What's happening in the Dallas market?
> **Testing:** Very vague. Good models should pick the most relevant object type or ask for specifics.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 9.4s | 14 | Y | - |  |
| Claude Sonnet 4.6 | 40 | 20.0s | 18 | Y | - |  |
| Claude Sonnet 4 | 45 | 16.1s | 8 | Y | - |  |
| Amazon Nova Pro | 45 | 12.5s | 6 | Y | - |  |
| Amazon Nova Lite | 40 | 8.6s | 12 | Y | - |  |
| Mistral Large 3 | 40 | 10.4s | 22 | Y | - |  |
| MiniMax M2.5 | 45 | 9.4s | 8 | Y | - |  |
| DeepSeek V3.2 | 35 | 24.7s | 16 | Y | - |  |
| GLM-5 | 10 | 30.2s | 0 | - | - |  |

### 8. City comparison [stress]
> **Query:** Compare deal activity in Dallas, Houston, and Austin — total count, total value, and average deal size
> **Testing:** Requires 3+ parallel aggregate calls with different metrics.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 30 | 8.4s | 18 | - | - |  |
| Claude Sonnet 4.6 | 30 | 15.6s | 18 | - | - |  |
| Claude Sonnet 4 | 30 | 14.0s | 18 | - | - |  |
| Amazon Nova Pro | 45 | 7.9s | 18 | Y | - |  |
| Amazon Nova Lite | 45 | 5.2s | 8 | Y | - |  |
| Mistral Large 3 | 45 | 5.9s | 18 | Y | - |  |
| MiniMax M2.5 | 45 | 12.7s | 6 | Y | - |  |
| DeepSeek V3.2 | 35 | 17.1s | 6 | Y | - |  |
| GLM-5 | 45 | 17.0s | 6 | Y | - |  |

### 9. Advisory question [medium]
> **Query:** How would I find which companies have expiring leases in the next 6 months?
> **Testing:** Should NOT call tools. Should explain approach and offer clickable query.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 35 | 9.6s | 0 | - | Y->fail |  |
| Claude Sonnet 4.6 | 35 | 17.9s | 0 | - | Y->fail |  |
| Claude Sonnet 4 | 35 | 12.9s | 0 | - | Y->fail |  |
| Amazon Nova Pro | 45 | 5.3s | 2 | Y | - |  |
| Amazon Nova Lite | 30 | 4.7s | 2 | - | - |  |
| Mistral Large 3 | 35 | 5.6s | 0 | - | Y->fail |  |
| MiniMax M2.5 | 35 | 11.4s | 0 | - | Y->fail |  |
| DeepSeek V3.2 | 45 | 9.1s | 2 | Y | - |  |
| GLM-5 | 35 | 14.6s | 0 | - | Y->fail |  |

### 10. Temporal + multi-filter [stress]
> **Query:** Find all lease comps signed in 2025 for spaces over 20,000 SF with rent above $30 PSF in Texas
> **Testing:** Tests date filter construction, numeric filters, and state-level geography.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 30 | 5.6s | 2 | - | - |  |
| Claude Sonnet 4.6 | 40 | 29.3s | 4 | - | Y->fail |  |
| Claude Sonnet 4 | 30 | 7.0s | 2 | - | - |  |
| Amazon Nova Pro | 30 | 4.6s | 2 | - | - |  |
| Amazon Nova Lite | 30 | 3.9s | 2 | - | - |  |
| Mistral Large 3 | 30 | 3.0s | 2 | - | - |  |
| MiniMax M2.5 | 35 | 28.2s | 10 | Y | - |  |
| DeepSeek V3.2 | 10 | 30.2s | 0 | - | - |  |
| GLM-5 | 40 | 22.4s | 4 | Y | - |  |

## Full Answers (for manual review)

### 1. Direct property search
> Show me Class A office properties in Dallas

**Claude Haiku 4.5** (latency: 9.3s, tools: 1, citations: 8)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 11.6s, tools: 1, citations: 8)
```
(no answer)
```

**Claude Sonnet 4** (latency: 10.7s, tools: 1, citations: 8)
```
(no answer)
```

**Amazon Nova Pro** (latency: 7.2s, tools: 1, citations: 8)
```
(no answer)
```

**Amazon Nova Lite** (latency: 7.1s, tools: 2, citations: 8)
```
(no answer)
```

**Mistral Large 3** (latency: 6.4s, tools: 1, citations: 8)
```
(no answer)
```

**MiniMax M2.5** (latency: 8.9s, tools: 2, citations: 8)
```
(no answer)
```

**DeepSeek V3.2** (latency: 9.2s, tools: 1, citations: 8)
```
(no answer)
```

**GLM-5** (latency: 14.1s, tools: 1, citations: 8)
```
(no answer)
```

### 2. Count by category
> How many deals do we have by market?

**Claude Haiku 4.5** (latency: 6.5s, tools: 1, citations: 584)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 10.0s, tools: 1, citations: 584)
```
(no answer)
```

**Claude Sonnet 4** (latency: 10.4s, tools: 1, citations: 584)
```
(no answer)
```

**Amazon Nova Pro** (latency: 7.4s, tools: 2, citations: 584)
```
(no answer)
```

**Amazon Nova Lite** (latency: 6.1s, tools: 1, citations: 584)
```
(no answer)
```

**Mistral Large 3** (latency: 6.8s, tools: 1, citations: 584)
```
(no answer)
```

**MiniMax M2.5** (latency: 3.2s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Deals by city: Count deals grouped by property_city
  - Deals by state: Count deals grouped by property_state

*Follow-up query:* `Count deals grouped by property_city`
*Follow-up result* (latency: 7.0s):

**DeepSeek V3.2** (latency: 2.1s, tools: 0, citations: 0)
```
(no answer)
```

**GLM-5** (latency: 19.6s, tools: 1, citations: 584)
```
(no answer)
```

### 3. Top deals by fee
> What are our top 10 deals by company fee?

**Claude Haiku 4.5** (latency: 6.3s, tools: 1, citations: 1511)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 16.8s, tools: 2, citations: 57)
```
(no answer)
```

**Claude Sonnet 4** (latency: 9.2s, tools: 1, citations: 1511)
```
(no answer)
```

**Amazon Nova Pro** (latency: 5.5s, tools: 1, citations: 347)
```
(no answer)
```

**Amazon Nova Lite** (latency: 3.8s, tools: 1, citations: 8)
```
(no answer)
```

**Mistral Large 3** (latency: 11.0s, tools: 1, citations: 1511)
```
(no answer)
```

**MiniMax M2.5** (latency: 15.5s, tools: 1, citations: 1511)
```
(no answer)
```

**DeepSeek V3.2** (latency: 3.9s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Deals with the highest broker fees: Company fee meaning broker/consultant fee

*Follow-up query:* `Company fee meaning broker/consultant fee`
*Follow-up result* (latency: 4.7s):

**GLM-5** (latency: 18.1s, tools: 2, citations: 1518)
```
(no answer)
```

### 4. Vague leaderboard
> Who are our top brokers?

**Claude Haiku 4.5** (latency: 3.6s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Top brokers by deal count: Show brokers ranked by number of deals closed
  - Top brokers by deal value: Show brokers ranked by total gross deal value
  - Top brokers by fee: Show brokers ranked by total gross fees earned
  - Top brokers by transaction size: Show brokers ranked by average deal size (SF)

*Follow-up query:* `Show brokers ranked by number of deals closed`
*Follow-up result* (latency: 3.0s):

**Claude Sonnet 4.6** (latency: 7.4s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Top brokers by gross deal value (all time): Show top 10 brokers ranked by total gross deal value, grouped by lead broker company, all time
  - Top brokers by gross fee earned (all time): Show top 10 brokers ranked by total gross fee amount, grouped by lead broker company, all time
  - Top brokers by deal count (all time): Show top 10 brokers ranked by number of deals, grouped by lead broker company, all time
  - Top tenant rep brokers by gross deal value: Show top 10 tenant rep brokers ranked by total gross deal value, all time
  - Top listing brokers by gross deal value: Show top 10 listing brokers ranked by total gross deal value, all time
  - Top buyer rep brokers by gross deal value: Show top 10 buyer rep brokers ranked by total gross deal value, all time
  - Top lead brokers by deal count this year: Show top 10 lead brokers by number of deals closed in 2026
  - Top lead brokers by gross deal value last 12 months: Show top 10 lead brokers by total gross deal value in the last 12 months (March 2025 – March 2026)

*Follow-up query:* `Show top 10 brokers ranked by total gross deal value, grouped by lead broker company, all time`
*Follow-up result* (latency: 13.8s):

**Claude Sonnet 4** (latency: 5.9s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Lead brokers by total deal value: Top 10 lead brokers by total gross deal value this year
  - Tenant rep brokers by deal value: Top 10 tenant rep brokers by total gross deal value this year
  - Listing brokers by deal value: Top 10 listing brokers by total gross deal value this year
  - Lead brokers by gross fees: Top 10 lead brokers by total gross fee revenue this year
  - All brokers by company fees: Top 10 brokers by company gross fee revenue this year
  - Brokers by deal count: Top 10 brokers by number of closed deals this year

*Follow-up query:* `Top 10 lead brokers by total gross deal value this year`
*Follow-up result* (latency: 16.5s):

**Amazon Nova Pro** (latency: 6.1s, tools: 3, citations: 57)
```
(no answer)
```

**Amazon Nova Lite** (latency: 2.5s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Lead brokers by deal value: Top 10 lead brokers by gross deal value
  - Lead brokers by gross fee: Top 10 lead brokers by gross fee amount
  - Tenant reps by deal value: Top 10 tenant rep brokers by gross deal value
  - Listing brokers by deal value: Top 10 listing brokers by gross deal value

*Follow-up query:* `Top 10 lead brokers by gross deal value`
*Follow-up result* (latency: 2.1s):

**Mistral Large 3** (latency: 2.3s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Lead brokers by deal value: Show the top brokers by gross deal value
  - Lead brokers by gross fee: Show the top brokers by gross fee amount
  - Tenant rep brokers by deal value: Show the top tenant rep brokers by gross deal value
  - Listing brokers by deal value: Show the top listing brokers by gross deal value
  - Brokers by closed deal count: Show the top brokers by number of closed deals

*Follow-up query:* `Show the top brokers by gross deal value`
*Follow-up result* (latency: 2.5s):

**MiniMax M2.5** (latency: 4.4s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Lead brokers by deal value: Show top lead brokers by gross deal value this year
  - Lead brokers by gross fee: Show top lead brokers by gross fee this year
  - Tenant reps by deal count: Show top tenant rep brokers by deal count this year
  - Listing brokers by deal count: Show top listing brokers by deal count this year

*Follow-up query:* `Show top lead brokers by gross deal value this year`
*Follow-up result* (latency: 30.2s):

**DeepSeek V3.2** (latency: 3.2s, tools: 0, citations: 0)
```
(no answer)
```

**GLM-5** (latency: 30.4s, tools: 0, citations: 0)
```
(no answer)
```

### 5. Market revenue with deal details
> List the top 10 markets by revenue and the largest deal in each and the related property in that deal

**Claude Haiku 4.5** (latency: 22.5s, tools: 19, citations: 806)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 29.5s, tools: 11, citations: 806)
```
(no answer)
```

**Claude Sonnet 4** (latency: 30.2s, tools: 0, citations: 0)
```
(no answer)
```

**Amazon Nova Pro** (latency: 6.7s, tools: 1, citations: 584)
```
(no answer)
```

**Amazon Nova Lite** (latency: 23.5s, tools: 31, citations: 591)
```
(no answer)
```

**Mistral Large 3** (latency: 30.1s, tools: 14, citations: 591)
```
(no answer)
```

**MiniMax M2.5** (latency: 8.6s, tools: 1, citations: 0)
```
(no answer)
```
Clarification options:
  - Top 10 markets by deal count: Show top 10 markets by number of closed deals, with the largest deal by value in each
  - Top 10 markets by gross deal value: Show top 10 markets by total gross deal value, with the largest deal in each
  - Top 10 markets by gross fee: Show top 10 markets by total gross fee earned, with the largest deal in each
  - Top 10 markets by lease revenue: Show top 10 markets by total leased SF, with the largest lease in each

*Follow-up query:* `Show top 10 markets by number of closed deals, with the largest deal by value in each`
*Follow-up result* (latency: 30.4s):

**DeepSeek V3.2** (latency: 3.7s, tools: 0, citations: 0)
```
(no answer)
```

**GLM-5** (latency: 12.9s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Gross deal value: Top 10 markets by gross deal value, showing largest deal and property in each
  - Gross fee: Top 10 markets by gross fee amount, showing largest deal and property in each
  - Company gross fee: Top 10 markets by company gross fee, showing largest deal and property in each

*Follow-up query:* `Top 10 markets by gross deal value, showing largest deal and property in each`
*Follow-up result* (latency: 19.1s):

### 6. Broker involvement across objects
> Show all deals, leases, and inquiries involving CBRE in any role

**Claude Haiku 4.5** (latency: 10.8s, tools: 3, citations: 19)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 20.0s, tools: 3, citations: 19)
```
(no answer)
```

**Claude Sonnet 4** (latency: 21.5s, tools: 3, citations: 19)
```
(no answer)
```

**Amazon Nova Pro** (latency: 16.0s, tools: 3, citations: 19)
```
(no answer)
```

**Amazon Nova Lite** (latency: 6.0s, tools: 3, citations: 19)
```
(no answer)
```

**Mistral Large 3** (latency: 9.9s, tools: 7, citations: 4)
```
(no answer)
```

**MiniMax M2.5** (latency: 16.0s, tools: 3, citations: 19)
```
(no answer)
```

**DeepSeek V3.2** (latency: 11.9s, tools: 3, citations: 19)
```
(no answer)
```

**GLM-5** (latency: 27.0s, tools: 3, citations: 19)
```
(no answer)
```

### 7. Vague market analysis
> What's happening in the Dallas market?

**Claude Haiku 4.5** (latency: 9.4s, tools: 7, citations: 10)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 20.0s, tools: 9, citations: 25)
```
(no answer)
```

**Claude Sonnet 4** (latency: 16.1s, tools: 4, citations: 30)
```
(no answer)
```

**Amazon Nova Pro** (latency: 12.5s, tools: 3, citations: 23)
```
(no answer)
```

**Amazon Nova Lite** (latency: 8.6s, tools: 6, citations: 20)
```
(no answer)
```

**Mistral Large 3** (latency: 10.4s, tools: 11, citations: 6)
```
(no answer)
```

**MiniMax M2.5** (latency: 9.4s, tools: 4, citations: 10)
```
(no answer)
```

**DeepSeek V3.2** (latency: 24.7s, tools: 8, citations: 40)
```
(no answer)
```

**GLM-5** (latency: 30.2s, tools: 0, citations: 0)
```
(no answer)
```

### 8. City comparison
> Compare deal activity in Dallas, Houston, and Austin — total count, total value, and average deal size

**Claude Haiku 4.5** (latency: 8.4s, tools: 9, citations: 0)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 15.6s, tools: 9, citations: 0)
```
(no answer)
```

**Claude Sonnet 4** (latency: 14.0s, tools: 9, citations: 0)
```
(no answer)
```

**Amazon Nova Pro** (latency: 7.9s, tools: 9, citations: 3)
```
(no answer)
```

**Amazon Nova Lite** (latency: 5.2s, tools: 4, citations: 3)
```
(no answer)
```

**Mistral Large 3** (latency: 5.9s, tools: 9, citations: 1)
```
(no answer)
```

**MiniMax M2.5** (latency: 12.7s, tools: 3, citations: 3)
```
(no answer)
```

**DeepSeek V3.2** (latency: 17.1s, tools: 3, citations: 5)
```
(no answer)
```

**GLM-5** (latency: 17.0s, tools: 3, citations: 3)
```
(no answer)
```

### 9. Advisory question
> How would I find which companies have expiring leases in the next 6 months?

**Claude Haiku 4.5** (latency: 3.9s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - All expiring leases: Show all leases expiring in the next 6 months with tenant and owner names
  - Expiring leases by tenant: Count expiring leases grouped by tenant company
  - Expiring leases by market: Show expiring leases grouped by property city

*Follow-up query:* `Show all leases expiring in the next 6 months with tenant and owner names`
*Follow-up result* (latency: 5.7s):

**Claude Sonnet 4.6** (latency: 7.6s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - All expiring leases in next 6 months: Show all leases expiring between 2026-03-21 and 2026-09-21 with tenant names and square footage
  - Expiring office leases next 6 months: Show all office leases expiring between 2026-03-21 and 2026-09-21 with tenant names and square footage
  - Large expiring leases next 6 months (10,000+ SF): Show all leases expiring between 2026-03-21 and 2026-09-21 with leased SF over 10,000
  - Expiring leases by tenant company — grouped count: How many leases are expiring between 2026-03-21 and 2026-09-21, grouped by tenant name

*Follow-up query:* `Show all leases expiring between 2026-03-21 and 2026-09-21 with tenant names and square footage`
*Follow-up result* (latency: 10.3s):

**Claude Sonnet 4** (latency: 4.1s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Show leases expiring in next 6 months: Find all leases with end dates between now and September 2026, showing tenant companies and expiration dates

*Follow-up query:* `Find all leases with end dates between now and September 2026, showing tenant companies and expiration dates`
*Follow-up result* (latency: 8.8s):

**Amazon Nova Pro** (latency: 5.3s, tools: 1, citations: 3)
```
(no answer)
```

**Amazon Nova Lite** (latency: 4.7s, tools: 1, citations: 0)
```
(no answer)
```

**Mistral Large 3** (latency: 2.2s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Expiring leases by company: Show all leases expiring in the next 6 months, grouped by tenant company
  - Expiring leases with details: List all leases expiring in the next 6 months, including property, tenant, and end date

*Follow-up query:* `Show all leases expiring in the next 6 months, grouped by tenant company`
*Follow-up result* (latency: 3.4s):

**MiniMax M2.5** (latency: 4.8s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - All expiring leases in 6 months: Show all leases expiring in the next 6 months with tenant name and property
  - Expiring leases by city: Show leases expiring in the next 6 months grouped by property city
  - Large tenants with expiring leases: Show leases expiring in the next 6 months for tenants with 10,000+ SF

*Follow-up query:* `Show all leases expiring in the next 6 months with tenant name and property`
*Follow-up result* (latency: 6.7s):

**DeepSeek V3.2** (latency: 9.1s, tools: 1, citations: 2)
```
(no answer)
```

**GLM-5** (latency: 5.8s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - All expiring leases: Show all leases expiring in the next 6 months with tenant names
  - Expiring leases over 5,000 SF: Show leases expiring in the next 6 months with at least 5,000 SF

*Follow-up query:* `Show all leases expiring in the next 6 months with tenant names`
*Follow-up result* (latency: 8.8s):

### 10. Temporal + multi-filter
> Find all lease comps signed in 2025 for spaces over 20,000 SF with rent above $30 PSF in Texas

**Claude Haiku 4.5** (latency: 5.6s, tools: 1, citations: 0)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 13.3s, tools: 2, citations: 0)
```
(no answer)
```
Clarification options:
  - Texas leases by start date in 2025: Find lease comps with start date in 2025 for spaces over 20,000 SF with rent above $30 PSF in Texas
  - Texas large leases since 2024: Find lease comps signed since January 2024 for spaces over 20,000 SF with rent above $30 PSF in Texas
  - Texas leases in 2025 over 20,000 SF (no rate filter): Find lease comps signed in 2025 for spaces over 20,000 SF in Texas, any rent

*Follow-up query:* `Find lease comps with start date in 2025 for spaces over 20,000 SF with rent above $30 PSF in Texas`
*Follow-up result* (latency: 16.0s):

**Claude Sonnet 4** (latency: 7.0s, tools: 1, citations: 0)
```
(no answer)
```

**Amazon Nova Pro** (latency: 4.6s, tools: 1, citations: 0)
```
(no answer)
```

**Amazon Nova Lite** (latency: 3.9s, tools: 1, citations: 0)
```
(no answer)
```

**Mistral Large 3** (latency: 3.0s, tools: 1, citations: 0)
```
(no answer)
```

**MiniMax M2.5** (latency: 28.2s, tools: 5, citations: 40)
```
(no answer)
```

**DeepSeek V3.2** (latency: 30.2s, tools: 0, citations: 0)
```
(no answer)
```

**GLM-5** (latency: 22.4s, tools: 2, citations: 10)
```
(no answer)
```
