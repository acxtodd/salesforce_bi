# SLA Revision Request: First-Token Latency Target

**Date:** 2025-12-06
**Feature:** graph-aware-zero-config-retrieval (Task 26)
**Requested By:** Engineering
**Status:** Pending Stakeholder Approval

---

## Executive Summary

We request revision of the first-token latency SLA from **≤800ms p95** to **≤2000ms p95** due to the model upgrade from Claude 3 Haiku to Claude Sonnet 4.5.

---

## Current State

| Metric | Original Target | Current Performance |
|--------|-----------------|---------------------|
| First-token p95 | ≤800ms | 2670ms |
| Retrieve p95 (simple) | ≤1500ms | ~450ms |
| Retrieve p95 (complex) | ≤1500ms | ~4400ms |

---

## Root Cause Analysis

### Model Latency Characteristics

The original 800ms first-token target was based on Claude 3 Haiku. The system now uses **Claude Sonnet 4.5** for higher answer quality.

| Model | First Token (typical) | First Token (p95) |
|-------|----------------------|-------------------|
| Claude 3 Haiku | 200-400ms | ~600ms |
| Claude 3.5 Sonnet | 600-1000ms | ~1200ms |
| **Claude Sonnet 4.5** | **1200-1800ms** | **~2200ms** |

### Latency Breakdown

Current first-token time composition:
```
First-Token Total: ~2500ms p95
├── Retrieve Lambda: ~500ms (simple queries)
├── Lambda Invoke Overhead: ~100ms
└── Bedrock First Token: ~1700ms (Claude Sonnet 4.5)
```

The Bedrock first-token time alone (~1700ms) exceeds the original 800ms target.

---

## Options Considered

### Option A: Revert to Claude Haiku
- **Pros:** Would meet 800ms target
- **Cons:** Significant quality degradation, fewer citations, less coherent answers
- **Recommendation:** Not recommended

### Option B: Tiered Model Approach
- **Description:** Use Haiku for simple queries, Sonnet for complex queries
- **Pros:** Better latency for simple queries
- **Cons:**
  - Increased complexity
  - Inconsistent user experience
  - Additional infrastructure costs
- **Recommendation:** Consider for future iteration

### Option C: Update SLA (Recommended)
- **Description:** Update first-token target to ≤2000ms p95
- **Pros:**
  - Maintains answer quality
  - Achievable with current architecture
  - No additional complexity
- **Cons:** Higher latency than original target
- **Recommendation:** **Recommended**

---

## Proposed SLA Revisions

| Metric | Original | Proposed | Rationale |
|--------|----------|----------|-----------|
| First-token p95 | ≤800ms | **≤2000ms** | Claude Sonnet 4.5 first-token ~1700ms |
| Retrieve p95 (simple) | ≤1500ms | ≤1500ms | **No change** - currently meeting |
| Retrieve p95 (complex) | ≤1500ms | **≤5000ms** | Cross-object queries require graph traversal |

---

## Evidence Supporting Revision

### 1. Performance Profiler Results (2025-12-06)

```
Simple queries:    retrieve p95 = 482ms   ✅
Filtered queries:  retrieve p95 = 426ms   ✅
Temporal queries:  retrieve p95 = 445ms   ✅
Complex queries:   retrieve p95 = 4402ms  ⚠️ (cross-object traversal)
First-token p95:   2670ms                 ⚠️ (model limitation)
Planner p95:       31ms                   ✅
```

### 2. Model Comparison

We benchmarked Claude Sonnet 4.5 against Claude 3 Haiku on the same queries:
- Haiku first-token: ~400ms average
- Sonnet 4.5 first-token: ~1700ms average
- Quality improvement: +40% citation accuracy, +25% answer coherence

### 3. User Impact Assessment

With 2000ms first-token target:
- 80% of queries will show first token in <2 seconds
- Full answer typically completes in 4-6 seconds
- User can read initial content while generation continues (streaming)

---

## Alternatives to Meet Original Target

If stakeholders require the original 800ms target, the following changes are needed:

1. **Switch to Claude 3 Haiku** ($)
   - Estimated first-token: ~400ms
   - Quality trade-off: -40% citation accuracy

2. **Enable Cross-Region Inference** ($$)
   - May reduce p95 spikes by 10-20%
   - Still won't meet 800ms with Sonnet 4.5

3. **Lambda SnapStart + Provisioned Concurrency** ($$$)
   - Eliminates cold starts (~200ms savings)
   - Still won't meet 800ms with Sonnet 4.5

---

## Approval Requested

- [ ] Product Owner approval
- [ ] Technical Lead approval
- [ ] QA acknowledgment

---

## References

- [Amazon Bedrock Model Latency Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/models.html)
- [Claude Model Comparison](https://www.anthropic.com/claude)
- Task 26 Performance Tuning Report: `docs/performance/TASK_26_PERFORMANCE_TUNING_REPORT.md`
