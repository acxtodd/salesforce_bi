# Model Benchmark Scorecard v4 — Stress Test

Generated: 2026-03-21 18:09 UTC
Queries: 10 (with clarification follow-up)
Models: 5

## Leaderboard

| Rank | Model | Avg Quality | Avg Latency | Tool Use | Citations | Clarify+Followup | Errors | Est. $/query |
|------|-------|-------------|-------------|----------|-----------|------------------|--------|-------------|
| 1 | Claude Haiku 4.5 | 42/100 | 9.2s | 100% | 80% | 0/10 | 0/10 | $0.0044 |
| 2 | Amazon Nova Pro | 40/100 | 7.7s | 100% | 60% | 0/10 | 0/10 | $0.0040 |
| 3 | Claude Sonnet 4.6 | 38/100 | 21.7s | 90% | 70% | 2/10 | 0/10 | $0.0165 |
| 4 | MiniMax M2.5 | 34/100 | 19.3s | 80% | 70% | 1/10 | 0/10 | $0.0055 |
| 5 | Mistral Large 3 | 32/100 | 7.9s | 90% | 30% | 1/10 | 0/10 | $0.0090 |

**Winner:** Claude Haiku 4.5 — quality 42/100, latency 9.2s, $0.0044/query

## Query Details

### 1. Account deep-dive [hard]
> **Query:** Tell me everything we know about Aarden Equity — deals, leases, contacts, tasks
> **Testing:** Multi-object search on a specific account name across 4+ object types.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Amazon Nova Pro | 30 | 22.7s | 8 | - | - |  |
| MiniMax M2.5 | 45 | 16.6s | 8 | Y | - |  |
| Mistral Large 3 | 40 | 11.4s | 12 | Y | - |  |
| Claude Sonnet 4.6 | 45 | 23.6s | 12 | Y | - |  |
| Claude Haiku 4.5 | 45 | 16.5s | 10 | Y | - |  |

### 2. Rent comparison [medium]
> **Query:** What's the average asking rent for Class A vs Class B space in Dallas?
> **Testing:** Requires two parallel aggregate calls with different property_class filters.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Amazon Nova Pro | 30 | 5.3s | 4 | - | - |  |
| MiniMax M2.5 | 10 | 30.3s | 0 | - | - |  |
| Mistral Large 3 | 25 | 4.7s | 8 | - | - |  |
| Claude Sonnet 4.6 | 40 | 15.5s | 12 | Y | - |  |
| Claude Haiku 4.5 | 30 | 5.3s | 4 | - | - |  |

### 3. Recent activity [medium]
> **Query:** Show me all deals closed in the last 90 days
> **Testing:** Model must calculate date 90 days ago from today and use close_date_gte filter.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Amazon Nova Pro | 45 | 5.3s | 2 | Y | - |  |
| MiniMax M2.5 | 35 | 19.7s | 12 | Y | - |  |
| Mistral Large 3 | 30 | 2.3s | 2 | - | - |  |
| Claude Sonnet 4.6 | 40 | 42.1s | 6 | - | Y->fail |  |
| Claude Haiku 4.5 | 30 | 4.1s | 2 | - | - |  |

### 4. Who is active [hard]
> **Query:** Which companies are most active in our system?
> **Testing:** Very vague — active how? Deals, leases, tasks? Should clarify or make a reasonable choice.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Amazon Nova Pro | 55 | 6.9s | 2 | Y | - |  |
| MiniMax M2.5 | 45 | 26.1s | 0 | - | Y->fail |  |
| Mistral Large 3 | 45 | 4.9s | 0 | - | Y->fail |  |
| Claude Sonnet 4.6 | 45 | 14.0s | 0 | - | Y->fail |  |
| Claude Haiku 4.5 | 55 | 10.5s | 8 | Y | - |  |

### 5. Tenant at property [medium]
> **Query:** Who are the tenants at Williams Tower?
> **Testing:** Requires searching leases filtered by property_name to find tenant names.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Amazon Nova Pro | 30 | 4.4s | 2 | - | - |  |
| MiniMax M2.5 | 35 | 12.9s | 10 | Y | - |  |
| Mistral Large 3 | 25 | 3.0s | 4 | - | - |  |
| Claude Sonnet 4.6 | 40 | 9.4s | 6 | Y | - |  |
| Claude Haiku 4.5 | 45 | 4.8s | 4 | Y | - |  |

### 6. Exclusion filter [medium]
> **Query:** Show me all deals NOT in the Dallas or Houston market
> **Testing:** Tests ability to construct _ne or negative filters. May need creative filter approach.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Amazon Nova Pro | 45 | 5.6s | 2 | Y | - |  |
| MiniMax M2.5 | 40 | 15.3s | 4 | Y | - |  |
| Mistral Large 3 | 20 | 7.3s | 16 | - | - |  |
| Claude Sonnet 4.6 | 40 | 26.6s | 4 | Y | - |  |
| Claude Haiku 4.5 | 35 | 11.0s | 6 | Y | - |  |

### 7. Market leaderboard [stress]
> **Query:** Rank the top 5 cities by total deal count and total deal value side by side
> **Testing:** Requires two aggregate calls (count + sum) grouped by city, then merging results.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Amazon Nova Pro | 45 | 10.6s | 4 | Y | - |  |
| MiniMax M2.5 | 45 | 13.3s | 4 | Y | - |  |
| Mistral Large 3 | 45 | 7.6s | 4 | Y | - |  |
| Claude Sonnet 4.6 | 45 | 14.1s | 4 | Y | - |  |
| Claude Haiku 4.5 | 45 | 7.8s | 4 | Y | - |  |

### 8. Supply-demand match [stress]
> **Query:** Find availabilities that match tenant preferences for office space under $25 PSF in Dallas
> **Testing:** Cross-object reasoning: search preferences, then find matching availabilities.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Amazon Nova Pro | 45 | 4.8s | 2 | Y | - |  |
| MiniMax M2.5 | 40 | 16.2s | 8 | Y | - |  |
| Mistral Large 3 | 30 | 3.3s | 4 | - | - |  |
| Claude Sonnet 4.6 | 35 | 25.1s | 14 | Y | - |  |
| Claude Haiku 4.5 | 45 | 10.2s | 4 | Y | - |  |

### 9. Record detail lookup [hard]
> **Query:** Show me the details of the AMLI at the Ballpark property — all leases and availability
> **Testing:** Multi-object: property search + leases + availability filtered by property_name.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Amazon Nova Pro | 30 | 4.5s | 4 | - | - |  |
| MiniMax M2.5 | 35 | 12.5s | 10 | Y | - |  |
| Mistral Large 3 | 45 | 3.8s | 6 | Y | - |  |
| Claude Sonnet 4.6 | 40 | 16.1s | 6 | Y | - |  |
| Claude Haiku 4.5 | 45 | 8.4s | 6 | Y | - |  |

### 10. Portfolio insight [stress]
> **Query:** What are the biggest risks in our current lease portfolio? Look at expirations, vacancy, and market concentration.
> **Testing:** Requires creative multi-step analysis. Best models will aggregate leases by expiration window and market.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Amazon Nova Pro | 45 | 6.5s | 6 | Y | - |  |
| MiniMax M2.5 | 10 | 30.2s | 0 | - | - |  |
| Mistral Large 3 | 10 | 30.3s | 0 | - | - |  |
| Claude Sonnet 4.6 | 10 | 30.2s | 0 | - | - |  |
| Claude Haiku 4.5 | 45 | 12.8s | 8 | Y | - |  |

## Full Answers (for manual review)

### 1. Account deep-dive
> Tell me everything we know about Aarden Equity — deals, leases, contacts, tasks

**Amazon Nova Pro** (latency: 22.7s, tools: 4, citations: 0)
```
(no answer)
```

**MiniMax M2.5** (latency: 16.6s, tools: 4, citations: 34)
```
(no answer)
```

**Mistral Large 3** (latency: 11.4s, tools: 6, citations: 12)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 23.6s, tools: 6, citations: 42)
```
(no answer)
```

**Claude Haiku 4.5** (latency: 16.5s, tools: 5, citations: 57)
```
(no answer)
```

### 2. Rent comparison
> What's the average asking rent for Class A vs Class B space in Dallas?

**Amazon Nova Pro** (latency: 5.3s, tools: 2, citations: 0)
```
(no answer)
```

**MiniMax M2.5** (latency: 30.3s, tools: 0, citations: 0)
```
(no answer)
```

**Mistral Large 3** (latency: 4.7s, tools: 4, citations: 0)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 15.5s, tools: 6, citations: 6)
```
(no answer)
```

**Claude Haiku 4.5** (latency: 5.3s, tools: 2, citations: 0)
```
(no answer)
```

### 3. Recent activity
> Show me all deals closed in the last 90 days

**Amazon Nova Pro** (latency: 5.3s, tools: 1, citations: 1)
```
(no answer)
```

**MiniMax M2.5** (latency: 19.7s, tools: 6, citations: 14)
```
(no answer)
```

**Mistral Large 3** (latency: 2.3s, tools: 1, citations: 0)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 11.8s, tools: 3, citations: 0)
```
(no answer)
```
Clarification options:
  - All Closed Won deals regardless of date: Show me all deals with a Closed Won stage
  - Deals closed in the last 12 months: Show me all deals closed in the last 12 months
  - All deals in the pipeline: Show me all deals currently in the pipeline regardless of status

*Follow-up query:* `Show me all deals with a Closed Won stage`
*Follow-up result* (latency: 30.3s):

**Claude Haiku 4.5** (latency: 4.1s, tools: 1, citations: 0)
```
(no answer)
```

### 4. Who is active
> Which companies are most active in our system?

**Amazon Nova Pro** (latency: 6.9s, tools: 1, citations: 347)
```
(no answer)
```

**MiniMax M2.5** (latency: 3.8s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - By deal count: Which companies have the most deals (as buyer, seller, tenant, or landlord)?
  - By property count: Which companies own the most properties in our system?
  - By lease count: Which companies are tenants in the most leases?
  - By broker transactions: Which broker companies have closed the most deals?

*Follow-up query:* `Which companies have the most deals (as buyer, seller, tenant, or landlord)?`
*Follow-up result* (latency: 22.3s):

**Mistral Large 3** (latency: 2.7s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Most active in deals (by count): Show companies with the most deals in the system
  - Most active in deals (by deal value): Show companies with the highest total deal value
  - Most active in property ownership (by count): Show companies that own the most properties
  - Most active in property ownership (by square footage): Show companies that own the most square footage

*Follow-up query:* `Show companies with the most deals in the system`
*Follow-up result* (latency: 2.2s):

**Claude Sonnet 4.6** (latency: 6.8s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Companies by number of deals: Show top 10 companies by number of deals as client, buyer, seller, or tenant
  - Companies by total deal value: Show top 10 companies by total gross deal value
  - Companies by number of leases: Show top 10 companies by number of leases as tenant
  - Companies by number of properties owned: Show top 10 companies by number of properties owned
  - Companies by number of inquiries: Show top 10 companies by number of active inquiries

*Follow-up query:* `Show top 10 companies by number of deals as client, buyer, seller, or tenant`
*Follow-up result* (latency: 7.2s):

**Claude Haiku 4.5** (latency: 10.5s, tools: 4, citations: 2097)
```
(no answer)
```

### 5. Tenant at property
> Who are the tenants at Williams Tower?

**Amazon Nova Pro** (latency: 4.4s, tools: 1, citations: 0)
```
(no answer)
```

**MiniMax M2.5** (latency: 12.9s, tools: 5, citations: 22)
```
(no answer)
```

**Mistral Large 3** (latency: 3.0s, tools: 2, citations: 0)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 9.4s, tools: 3, citations: 44)
```
(no answer)
```

**Claude Haiku 4.5** (latency: 4.8s, tools: 2, citations: 1)
```
(no answer)
```

### 6. Exclusion filter
> Show me all deals NOT in the Dallas or Houston market

**Amazon Nova Pro** (latency: 5.6s, tools: 1, citations: 10)
```
(no answer)
```

**MiniMax M2.5** (latency: 15.3s, tools: 2, citations: 51)
```
(no answer)
```

**Mistral Large 3** (latency: 7.3s, tools: 8, citations: 0)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 26.6s, tools: 2, citations: 50)
```
(no answer)
```

**Claude Haiku 4.5** (latency: 11.0s, tools: 3, citations: 100)
```
(no answer)
```

### 7. Market leaderboard
> Rank the top 5 cities by total deal count and total deal value side by side

**Amazon Nova Pro** (latency: 10.6s, tools: 2, citations: 584)
```
(no answer)
```

**MiniMax M2.5** (latency: 13.3s, tools: 2, citations: 584)
```
(no answer)
```

**Mistral Large 3** (latency: 7.6s, tools: 2, citations: 314)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 14.1s, tools: 2, citations: 584)
```
(no answer)
```

**Claude Haiku 4.5** (latency: 7.8s, tools: 2, citations: 584)
```
(no answer)
```

### 8. Supply-demand match
> Find availabilities that match tenant preferences for office space under $25 PSF in Dallas

**Amazon Nova Pro** (latency: 4.8s, tools: 1, citations: 10)
```
(no answer)
```

**MiniMax M2.5** (latency: 16.2s, tools: 4, citations: 13)
```
(no answer)
```

**Mistral Large 3** (latency: 3.3s, tools: 2, citations: 0)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 25.1s, tools: 7, citations: 30)
```
(no answer)
```

**Claude Haiku 4.5** (latency: 10.2s, tools: 2, citations: 25)
```
(no answer)
```

### 9. Record detail lookup
> Show me the details of the AMLI at the Ballpark property — all leases and availability

**Amazon Nova Pro** (latency: 4.5s, tools: 2, citations: 0)
```
(no answer)
```

**MiniMax M2.5** (latency: 12.5s, tools: 5, citations: 30)
```
(no answer)
```

**Mistral Large 3** (latency: 3.8s, tools: 3, citations: 1)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 16.1s, tools: 3, citations: 10)
```
(no answer)
```

**Claude Haiku 4.5** (latency: 8.4s, tools: 3, citations: 4)
```
(no answer)
```

### 10. Portfolio insight
> What are the biggest risks in our current lease portfolio? Look at expirations, vacancy, and market concentration.

**Amazon Nova Pro** (latency: 6.5s, tools: 3, citations: 94)
```
(no answer)
```

**MiniMax M2.5** (latency: 30.2s, tools: 0, citations: 0)
```
(no answer)
```

**Mistral Large 3** (latency: 30.3s, tools: 0, citations: 0)
```
(no answer)
```

**Claude Sonnet 4.6** (latency: 30.2s, tools: 0, citations: 0)
```
(no answer)
```

**Claude Haiku 4.5** (latency: 12.8s, tools: 4, citations: 793)
```
(no answer)
```
