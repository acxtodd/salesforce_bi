# Per-Tenant Cost Model

*Last updated: 2026-03-22*

Estimated per-tenant monthly costs for the shared multi-tenant compute plane
described in `shared_multi_tenant_compute_plane_proposal.md`.

## Assumptions

### Tenant Profile (Small CRE Brokerage)

| Parameter | Value | Rationale |
|---|---|---|
| Indexed records | 15,000 | Similar to current POC (~14,861 docs across 11 objects) |
| Avg document size | 2 KB | Denormalized text + metadata, no vectors stored inline |
| Embedding dimensions | 1,024 (Titan V2) | 4 bytes × 1,024 = 4 KB per vector |
| Total doc + vector size | ~6 KB per record | 2 KB text/metadata + 4 KB vector |
| Queries per day | 50 | ~10 active users × 5 queries/day |
| Queries per month | 1,500 | 50/day × 30 days |
| Tool calls per query | 2 avg | 1-3 search_records / aggregate_records calls |
| CDC/sync events per month | 5,000 | ~170/day, moderate edit activity |
| Bulk reindex frequency | Quarterly | Full reload for config changes |

### Tenant Profile (Mid-Size CRE Firm)

| Parameter | Value |
|---|---|
| Indexed records | 50,000 |
| Queries per day | 200 |
| Queries per month | 6,000 |
| CDC/sync events per month | 20,000 |

### Tenant Profile (Large Enterprise)

| Parameter | Value |
|---|---|
| Indexed records | 200,000 |
| Queries per day | 1,000 |
| Queries per month | 30,000 |
| CDC/sync events per month | 100,000 |

---

## Cost Breakdown

### 1. Turbopuffer (Retrieval Index)

Turbopuffer bills on storage, queries, and writes in logical bytes.
No per-namespace fee — namespaces are organizational, not billing units.

**Plan minimum:** $64/month (Launch) or $256/month (Scale).
Multiple tenants share the same TP account, so the minimum is amortized.

| Component | Small | Mid | Large | Notes |
|---|---|---|---|---|
| **Storage** | 15K × 6 KB = 90 MB | 300 MB | 1.2 GB | Billed per logical byte stored |
| **Queries** | 1,500 × 2 calls = 3,000/mo | 12,000/mo | 60,000/mo | Each tool call = 1 TP query |
| **Query min floor** | 1.28 GB per query | same | same | Minimum billable scan per query |
| **Writes (CDC)** | 5,000 × 6 KB = 30 MB/mo | 120 MB/mo | 600 MB/mo | Billed per logical byte written |
| **Writes (reindex)** | 90 MB/quarter | 300 MB/qtr | 1.2 GB/qtr | Quarterly full reload |

**Estimated TP cost per tenant:** Difficult to pin without the exact $/GB rates from the
interactive calculator. However, at these volumes, storage is negligible and query costs
dominate due to the 1.28 GB minimum floor per query.

Rough estimate using the 1.28 GB floor:
- Small: 3,000 queries × 1.28 GB = 3,840 GB queried/month
- Mid: 12,000 × 1.28 GB = 15,360 GB/month
- Large: 60,000 × 1.28 GB = 76,800 GB/month

At scale, tiered discounts (80% at 32-128 GB, 96% above 128 GB) reduce this significantly.
The per-GB query rate needs to be confirmed from the TP pricing calculator.

**Action item:** Use the TP pricing calculator with actual namespace sizes to get precise
per-query costs. Small namespaces may hit the 1.28 GB floor on every query, making
query cost approximately flat regardless of namespace size.

### 2. AWS Bedrock — LLM Inference (Claude Haiku 4.5)

Per-query token budget:

| Component | Tokens | Notes |
|---|---|---|
| System prompt | ~3,000 input | Object/field reference, guidelines, examples |
| User query | ~100 input | Natural language question |
| Conversation history | ~500 input | 0-2 prior turns (record page only) |
| Tool call request | ~200 output | Model generates search_records call |
| Tool result | ~2,000 input | Top-10 search results returned |
| Second tool call (if any) | ~200 output | Optional aggregate or follow-up |
| Second tool result | ~1,000 input | Optional |
| Final answer | ~500 output | Formatted response with citations |
| **Total per query** | **~6,800 input, ~900 output** | Conservative estimate |

Haiku 4.5 pricing (us-west-2 on-demand):
- Input: $1.00 / 1M tokens
- Output: $5.00 / 1M tokens

| Tenant | Queries/mo | Input tokens | Output tokens | Input cost | Output cost | **Total LLM** |
|---|---|---|---|---|---|---|
| Small | 1,500 | 10.2M | 1.35M | $10.20 | $6.75 | **$16.95** |
| Mid | 6,000 | 40.8M | 5.4M | $40.80 | $27.00 | **$67.80** |
| Large | 30,000 | 204M | 27M | $204.00 | $135.00 | **$339.00** |

### 3. AWS Bedrock — Embeddings (Titan V2)

Used at index time only (not per query — BM25 queries don't need embeddings).

| Component | Tokens per doc | Notes |
|---|---|---|
| Embed text | ~400 | Avg denormalized document text |

Titan V2 pricing: $0.02 / 1M tokens

| Tenant | CDC writes/mo | Tokens | **Monthly cost** |
|---|---|---|---|
| Small | 5,000 | 2M | **$0.04** |
| Mid | 20,000 | 8M | **$0.16** |
| Large | 100,000 | 40M | **$0.80** |

Embedding cost is negligible.

### 4. AWS Lambda (Shared — Amortized)

Query Lambda: ~5-10 seconds per invocation, 1024 MB memory.

Lambda pricing: $0.0000166667 per GB-second

| Tenant | Queries/mo | GB-seconds | **Monthly cost** |
|---|---|---|---|
| Small | 1,500 | 1,500 × 7.5s × 1 GB = 11,250 | **$0.19** |
| Mid | 6,000 | 45,000 | **$0.75** |
| Large | 30,000 | 225,000 | **$3.75** |

Index/CDC Lambda: ~2 seconds per invocation, 512 MB memory.

| Tenant | Events/mo | GB-seconds | **Monthly cost** |
|---|---|---|---|
| Small | 5,000 | 5,000 | **$0.08** |
| Mid | 20,000 | 20,000 | **$0.33** |
| Large | 100,000 | 100,000 | **$1.67** |

### 5. API Gateway (Shared — Amortized)

$1.00 per million requests (REST API).

| Tenant | Requests/mo | **Monthly cost** |
|---|---|---|
| Small | 6,500 | **$0.01** |
| Mid | 26,000 | **$0.03** |
| Large | 130,000 | **$0.13** |

---

## Summary (Excluding Turbopuffer Query Costs)

| Component | Small | Mid | Large |
|---|---|---|---|
| **LLM inference** | $16.95 | $67.80 | $339.00 |
| **Embeddings** | $0.04 | $0.16 | $0.80 |
| **Lambda compute** | $0.27 | $1.08 | $5.42 |
| **API Gateway** | $0.01 | $0.03 | $0.13 |
| **Subtotal (AWS)** | **$17.27** | **$69.07** | **$345.35** |
| **Turbopuffer** | TBD | TBD | TBD |

### Key Observations

1. **LLM inference dominates.** Bedrock Haiku 4.5 is 95-98% of the AWS cost.
   Switching to a cheaper model (if quality permits) is the biggest cost lever.

2. **Embeddings, Lambda, and API Gateway are rounding errors.** Combined they're
   under $1/month for a small tenant.

3. **Turbopuffer query cost is the unknown.** The 1.28 GB minimum floor per query
   means small namespaces pay the same per-query scan cost as large ones. This
   needs calculator validation. If TP query cost is comparable to LLM cost,
   total per-tenant cost roughly doubles.

4. **Cost scales linearly with query volume.** A tenant that queries 10× more
   pays ~10× more. There are no significant fixed costs per tenant beyond the
   shared TP plan minimum (amortized across all tenants).

5. **At 10 tenants on Launch plan ($64/mo TP minimum):** TP platform cost is
   $6.40/tenant/month before usage. AWS cost for a small tenant is ~$17/month.
   **Estimated total: ~$25-35/month per small tenant** (pending TP query rates).

6. **At 50 tenants on Scale plan ($256/mo TP minimum):** TP platform cost drops
   to $5.12/tenant/month. Amortization improves with scale.

## Cost Optimization Levers

| Lever | Impact | Trade-off |
|---|---|---|
| Cheaper LLM model | High | Quality/accuracy risk |
| Bedrock provisioned throughput | Medium | Commit required, better for steady load |
| Reduce tool calls per query | Medium | May limit search scope |
| Cache frequent queries | Medium | Staleness, complexity |
| Batch CDC writes | Low | Slight freshness lag |
| Reduce embedding dimensions | Negligible | Embedding cost is already negligible |
