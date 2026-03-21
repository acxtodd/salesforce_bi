# Model Benchmark Scorecard v4 — Stress Test

Generated: 2026-03-21 18:14 UTC
Queries: 10 (with clarification follow-up)
Models: 2

## Leaderboard

| Rank | Model | Avg Quality | Avg Latency | Tool Use | Citations | Clarify+Followup | Errors | Est. $/query |
|------|-------|-------------|-------------|----------|-----------|------------------|--------|-------------|
| 1 | Amazon Nova Pro | 42/100 | 8.1s | 100% | 70% | 1/10 | 0/10 | $0.0040 |
| 2 | Claude Haiku 4.5 | 40/100 | 10.5s | 100% | 70% | 2/10 | 0/10 | $0.0044 |

**Winner:** Amazon Nova Pro — quality 42/100, latency 8.1s, $0.0040/query

## Query Details

### 1. Precise multi-filter [medium]
> **Query:** Find all Class A properties in Plano or Frisco with more than 200,000 SF
> **Testing:** Tests _in filter for multiple cities + numeric filter.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 30 | 4.5s | 2 | - | - |  |
| Amazon Nova Pro | 30 | 5.3s | 2 | - | - |  |

### 2. Landlord to tenant chain [hard]
> **Query:** Which tenants lease space in properties owned by Hartman REIT?
> **Testing:** Must search properties by owner, then search leases by those property names.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 35 | 8.9s | 6 | Y | - |  |
| Amazon Nova Pro | 25 | 5.7s | 4 | - | - |  |

### 3. Year-over-year deals [stress]
> **Query:** How many deals closed in 2024 vs 2025 by market?
> **Testing:** Requires two aggregate calls with different date ranges, grouped by market.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 40 | 8.7s | 8 | Y | - |  |
| Amazon Nova Pro | 45 | 6.5s | 4 | Y | - |  |

### 4. Vague opportunity question [hard]
> **Query:** Where are the opportunities?
> **Testing:** Extremely vague. Should clarify: opportunities for what? Leasing? Acquisition? Which market?

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 8.6s | 0 | - | Y->fail |  |
| Amazon Nova Pro | 45 | 7.6s | 0 | - | Y->fail |  |

### 5. Person activity [hard]
> **Query:** Show me all activity for Todd Terry — deals, tasks, contacts, everything
> **Testing:** Multi-object search for a specific person across all relevant object types.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 10.6s | 12 | Y | - |  |
| Amazon Nova Pro | 45 | 10.4s | 6 | Y | - |  |

### 6. Vacancy analysis [stress]
> **Query:** What is the total available SF by property class in Dallas? Include the number of availabilities in each class.
> **Testing:** Requires aggregate on available_sf grouped by property_class + a count aggregate.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 5.2s | 4 | Y | - |  |
| Amazon Nova Pro | 45 | 3.7s | 4 | Y | - |  |

### 7. Competitor analysis [hard]
> **Query:** Show me all deals where JLL, CBRE, or Cushman & Wakefield appears as any broker
> **Testing:** Tests multi-value text search across broker name fields.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 10.5s | 2 | Y | - |  |
| Amazon Nova Pro | 45 | 16.4s | 2 | Y | - |  |

### 8. What-if advisory [medium]
> **Query:** If I wanted to find tenants whose leases expire in the next year who might be looking for new space, how would I do that?
> **Testing:** Advisory question — should explain approach and offer clickable query button.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 35 | 19.8s | 0 | - | Y->fail |  |
| Amazon Nova Pro | 45 | 9.1s | 2 | Y | - |  |

### 9. Revenue + deal + property chain [stress]
> **Query:** List the top 5 markets by total deal revenue, show the largest deal in each market, and the property associated with that deal
> **Testing:** THE hard query. Multi-step: aggregate markets, find top deal per market, look up property.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 35 | 17.9s | 20 | Y | - |  |
| Amazon Nova Pro | 45 | 9.5s | 2 | Y | - |  |

### 10. Portfolio summary [stress]
> **Query:** Give me a summary of our deal pipeline — how many deals by stage, what's the total value, and which markets have the most pending deals?
> **Testing:** Requires multiple aggregates: by stage, total sum, by market filtered to pending.

| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |
|-------|---|---------|-------|-------|---------|----------------|
| Claude Haiku 4.5 | 45 | 10.3s | 6 | Y | - |  |
| Amazon Nova Pro | 45 | 7.0s | 6 | Y | - |  |

## Full Answers (for manual review)

### 1. Precise multi-filter
> Find all Class A properties in Plano or Frisco with more than 200,000 SF

**Claude Haiku 4.5** (latency: 4.5s, tools: 1, citations: 0)
```
(no answer)
```

**Amazon Nova Pro** (latency: 5.3s, tools: 1, citations: 0)
```
(no answer)
```

### 2. Landlord to tenant chain
> Which tenants lease space in properties owned by Hartman REIT?

**Claude Haiku 4.5** (latency: 8.9s, tools: 3, citations: 1)
```
(no answer)
```

**Amazon Nova Pro** (latency: 5.7s, tools: 2, citations: 0)
```
(no answer)
```

### 3. Year-over-year deals
> How many deals closed in 2024 vs 2025 by market?

**Claude Haiku 4.5** (latency: 8.7s, tools: 4, citations: 22)
```
(no answer)
```

**Amazon Nova Pro** (latency: 6.5s, tools: 2, citations: 22)
```
(no answer)
```

### 4. Vague opportunity question
> Where are the opportunities?

**Claude Haiku 4.5** (latency: 3.4s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Active deals in pipeline: Show all deals not yet closed, grouped by stage
  - Open inquiries: Show all active inquiries from prospects
  - Available space: Show currently available properties for lease or sale
  - Expiring leases: Show leases ending in the next 12 months
  - Geographic focus: Show opportunities (deals/inquiries/listings) in a specific market or city

*Follow-up query:* `Show all deals not yet closed, grouped by stage`
*Follow-up result* (latency: 5.2s):

**Amazon Nova Pro** (latency: 3.3s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - Deal opportunities: What are the current deal opportunities in our system?
  - Listing opportunities: What are the current listing opportunities in our system?
  - Inquiry opportunities: What are the current inquiry opportunities in our system?

*Follow-up query:* `What are the current deal opportunities in our system?`
*Follow-up result* (latency: 4.3s):

### 5. Person activity
> Show me all activity for Todd Terry — deals, tasks, contacts, everything

**Claude Haiku 4.5** (latency: 10.6s, tools: 6, citations: 21)
```
(no answer)
```

**Amazon Nova Pro** (latency: 10.4s, tools: 3, citations: 14)
```
(no answer)
```

### 6. Vacancy analysis
> What is the total available SF by property class in Dallas? Include the number of availabilities in each class.

**Claude Haiku 4.5** (latency: 5.2s, tools: 2, citations: 3)
```
(no answer)
```

**Amazon Nova Pro** (latency: 3.7s, tools: 2, citations: 3)
```
(no answer)
```

### 7. Competitor analysis
> Show me all deals where JLL, CBRE, or Cushman & Wakefield appears as any broker

**Claude Haiku 4.5** (latency: 10.5s, tools: 1, citations: 24)
```
(no answer)
```

**Amazon Nova Pro** (latency: 16.4s, tools: 1, citations: 42)
```
(no answer)
```

### 8. What-if advisory
> If I wanted to find tenants whose leases expire in the next year who might be looking for new space, how would I do that?

**Claude Haiku 4.5** (latency: 5.7s, tools: 0, citations: 0)
```
(no answer)
```
Clarification options:
  - All active tenant preferences expiring within 12 months: Find all tenants with lease expirations between now and March 2027 who have active space preferences
  - Specific market expiries: Show tenants with expirations in the next year for a specific market (e.g., Dallas, Houston)

*Follow-up query:* `Find all tenants with lease expirations between now and March 2027 who have active space preferences`
*Follow-up result* (latency: 14.2s):

**Amazon Nova Pro** (latency: 9.1s, tools: 1, citations: 10)
```
(no answer)
```

### 9. Revenue + deal + property chain
> List the top 5 markets by total deal revenue, show the largest deal in each market, and the property associated with that deal

**Claude Haiku 4.5** (latency: 17.9s, tools: 10, citations: 609)
```
(no answer)
```

**Amazon Nova Pro** (latency: 9.5s, tools: 1, citations: 584)
```
(no answer)
```

### 10. Portfolio summary
> Give me a summary of our deal pipeline — how many deals by stage, what's the total value, and which markets have the most pending deals?

**Claude Haiku 4.5** (latency: 10.3s, tools: 3, citations: 594)
```
(no answer)
```

**Amazon Nova Pro** (latency: 7.0s, tools: 3, citations: 20)
```
(no answer)
```
