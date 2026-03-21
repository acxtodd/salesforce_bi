#!/usr/bin/env python3
"""Model Benchmark Scorecard for AscendixIQ AI Search.

Sends a battery of queries (simple → complex) to the live Query Lambda
with each model, measures latency / tool-use / answer quality, and
produces a Markdown scorecard.

Usage:
    python3 scripts/model_benchmark.py [--output docs/model_scorecard.md]

Requires:
    - Query Lambda Function URL (auto-detected from CDK output or env)
    - API key in Secrets Manager or .env
    - Models accessible in the Bedrock account
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import boto3
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Query Lambda Function URL (override with QUERY_FUNCTION_URL env var)
FUNCTION_URL = os.getenv(
    "QUERY_FUNCTION_URL",
    "https://bxfrvrgbtsn6mpdq7rpnak3dki0cjxpg.lambda-url.us-west-2.on.aws/",
)

ORG_ID = "00Ddl000003yx57EAA"

MODELS = [
    ("Claude Sonnet 4.6", "us.anthropic.claude-sonnet-4-6"),
    ("Claude Sonnet 4.5", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"),
    ("Claude Sonnet 4", "us.anthropic.claude-sonnet-4-20250514-v1:0"),
    ("Claude Haiku 4.5", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("Amazon Nova Pro", "us.amazon.nova-pro-v1:0"),
    ("Amazon Nova Lite", "us.amazon.nova-lite-v1:0"),
    ("Mistral Large 3", "mistral.mistral-large-3-675b-instruct"),
    ("MiniMax M2.5", "minimax.minimax-m2.5"),
]

# ---------------------------------------------------------------------------
# Test queries — graded by difficulty
# ---------------------------------------------------------------------------

@dataclass
class TestQuery:
    name: str
    query: str
    difficulty: str  # simple, medium, hard
    expected_tool: str  # search_records, aggregate_records, both
    expected_keywords: list[str] = field(default_factory=list)
    """Keywords that should appear in a correct answer (case-insensitive)."""


QUERIES = [
    # --- Simple: single object, direct filter ---
    TestQuery(
        name="Property lookup by city",
        query="Show me all properties in Austin, Texas",
        difficulty="simple",
        expected_tool="search_records",
        expected_keywords=["austin"],
    ),
    TestQuery(
        name="Count with filter",
        query="How many active leases do we have?",
        difficulty="simple",
        expected_tool="aggregate_records",
        expected_keywords=[],
    ),
    TestQuery(
        name="Contact search",
        query="Find contacts at CBRE",
        difficulty="simple",
        expected_tool="search_records",
        expected_keywords=["cbre"],
    ),
    TestQuery(
        name="Availability with rent filter",
        query="Show availabilities with asking rent under $25 per square foot",
        difficulty="simple",
        expected_tool="search_records",
        expected_keywords=["rent"],
    ),

    # --- Medium: multi-filter, aggregation, sorting ---
    TestQuery(
        name="Top deals by fee",
        query="What are the top 10 deals by company fee in the Dallas market?",
        difficulty="medium",
        expected_tool="aggregate_records",
        expected_keywords=["deal", "dallas"],
    ),
    TestQuery(
        name="Breakdown by property class",
        query="Break down our properties by class in Houston",
        difficulty="medium",
        expected_tool="aggregate_records",
        expected_keywords=["houston", "class"],
    ),
    TestQuery(
        name="Lease comps with multiple filters",
        query="Find lease comps in Dallas CBD for office space over 10,000 SF signed in the last 12 months",
        difficulty="medium",
        expected_tool="search_records",
        expected_keywords=["dallas", "lease"],
    ),
    TestQuery(
        name="Task search with status filter",
        query="Show me all open tasks related to Aarden Equity",
        difficulty="medium",
        expected_tool="search_records",
        expected_keywords=["aarden"],
    ),

    # --- Hard: multi-object, reasoning, advisory ---
    TestQuery(
        name="Cross-city comparison",
        query="Compare total deal volume in Dallas vs Houston vs Austin",
        difficulty="hard",
        expected_tool="both",
        expected_keywords=["dallas", "houston", "austin"],
    ),
    TestQuery(
        name="Multi-object broker activity",
        query="Show all deals, leases, and inquiries involving Colliers in any role",
        difficulty="hard",
        expected_tool="search_records",
        expected_keywords=["colliers"],
    ),
    TestQuery(
        name="Advisory with runnable suggestion",
        query="How would I find which properties have the most availability right now?",
        difficulty="hard",
        expected_tool="none",
        expected_keywords=["availability", "property"],
    ),
    TestQuery(
        name="Ambiguous leaderboard",
        query="Who are the top performing brokers?",
        difficulty="hard",
        expected_tool="aggregate_records",
        expected_keywords=[],  # Should emit clarification options
    ),
]

# ---------------------------------------------------------------------------
# Query execution
# ---------------------------------------------------------------------------

def call_query_lambda(question: str, model_id: str, timeout: int = 60) -> dict:
    """Call the Query Lambda Function URL and parse SSE response."""
    payload = json.dumps({
        "question": question,
        "org_id": ORG_ID,
        "session_id": f"benchmark-{int(time.time())}",
        "model_id": model_id,
    }).encode()

    api_key = os.getenv("QUERY_API_KEY", "")
    if not api_key:
        # Try fetching from Secrets Manager
        try:
            sm = boto3.client("secretsmanager", region_name="us-west-2")
            secret = sm.get_secret_value(SecretId="salesforce-ai-search/streaming-api-key")
            api_key = json.loads(secret["SecretString"])["apiKey"]
        except Exception:
            pass

    req = urllib.request.Request(
        FUNCTION_URL + "query",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
        method="POST",
    )

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {
            "error": f"HTTP {e.code}: {body[:200]}",
            "latency": time.time() - start,
        }
    except Exception as e:
        return {
            "error": str(e),
            "latency": time.time() - start,
        }
    latency = time.time() - start

    # Parse SSE events
    answer = ""
    citations = []
    tool_calls = 0
    turns = 0
    returned_model = ""
    clarifications = []
    error = ""

    for line in body.split("\n"):
        if line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                event_type = data.get("type", "")
                if "answer" in data:
                    answer = data["answer"]
                elif "citations" in data:
                    citations = data["citations"]
                elif "options" in data:
                    clarifications = data["options"]
                elif "message" in data and not answer:
                    error = data["message"]
                if "tool_calls" in data:
                    tool_calls = data["tool_calls"]
                if "turns" in data:
                    turns = data["turns"]
                if "model_id" in data:
                    returned_model = data["model_id"]
            except json.JSONDecodeError:
                pass
        elif line.startswith("event: "):
            pass  # event type line

    # Re-parse: SSE format is "event: X\ndata: {...}\n\n"
    # Let's parse more carefully
    events = []
    current_event = ""
    for line in body.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                events.append((current_event, data))
            except json.JSONDecodeError:
                pass

    for evt_type, data in events:
        if evt_type == "answer":
            answer = data.get("answer", "")
        elif evt_type == "citations":
            citations = data.get("citations", [])
        elif evt_type == "clarification":
            clarifications = data.get("options", [])
        elif evt_type == "error":
            error = data.get("message", "")
        elif evt_type == "done":
            tool_calls = data.get("tool_calls", 0)
            turns = data.get("turns", 0)
            returned_model = data.get("model_id", "")

    return {
        "answer": answer,
        "citations": citations,
        "clarifications": clarifications,
        "tool_calls": tool_calls,
        "turns": turns,
        "model_id": returned_model,
        "latency": latency,
        "error": error,
        "answer_length": len(answer),
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class Score:
    tool_use_correct: bool = False
    keywords_found: int = 0
    keywords_total: int = 0
    has_answer: bool = False
    has_citations: bool = False
    has_clarifications: bool = False
    latency: float = 0.0
    error: str = ""
    answer_length: int = 0
    tool_calls: int = 0
    turns: int = 0

    @property
    def keyword_score(self) -> float:
        if self.keywords_total == 0:
            return 1.0
        return self.keywords_found / self.keywords_total

    @property
    def quality_score(self) -> float:
        """0-100 composite score."""
        if self.error:
            return 0.0
        score = 0.0
        if self.has_answer:
            score += 30
        if self.tool_use_correct:
            score += 30
        score += self.keyword_score * 25
        if self.has_citations:
            score += 10
        # Penalize excessive turns
        if self.turns <= 2:
            score += 5
        elif self.turns <= 3:
            score += 2
        return min(score, 100)


def score_result(tq: TestQuery, result: dict) -> Score:
    """Score a single query result."""
    s = Score()
    s.latency = result.get("latency", 0)
    s.error = result.get("error", "")
    s.answer_length = result.get("answer_length", 0)
    s.tool_calls = result.get("tool_calls", 0)
    s.turns = result.get("turns", 0)

    answer = result.get("answer", "")
    s.has_answer = bool(answer and len(answer) > 20)
    s.has_citations = len(result.get("citations", [])) > 0
    s.has_clarifications = len(result.get("clarifications", [])) > 0

    # Tool use correctness
    if tq.expected_tool == "none":
        s.tool_use_correct = s.tool_calls == 0
    elif tq.expected_tool == "both":
        s.tool_use_correct = s.tool_calls >= 2
    else:
        s.tool_use_correct = s.tool_calls >= 1

    # Keyword matching
    answer_lower = answer.lower()
    s.keywords_total = len(tq.expected_keywords)
    s.keywords_found = sum(
        1 for kw in tq.expected_keywords if kw.lower() in answer_lower
    )

    return s


# ---------------------------------------------------------------------------
# Scorecard generation
# ---------------------------------------------------------------------------

# Approximate input/output token costs per 1K tokens (USD)
MODEL_COSTS = {
    "us.anthropic.claude-sonnet-4-6": (0.003, 0.015),
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": (0.003, 0.015),
    "us.anthropic.claude-sonnet-4-20250514-v1:0": (0.003, 0.015),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (0.0008, 0.004),
    "us.amazon.nova-pro-v1:0": (0.0008, 0.0032),
    "us.amazon.nova-lite-v1:0": (0.00006, 0.00024),
    "mistral.mistral-large-3-675b-instruct": (0.002, 0.006),
    "minimax.minimax-m2.5": (0.0011, 0.0044),
}


def generate_scorecard(
    all_results: dict[str, dict[str, Any]],
) -> str:
    """Generate Markdown scorecard from all results."""
    lines: list[str] = []
    lines.append("# Model Benchmark Scorecard")
    lines.append(f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    lines.append(f"Queries: {len(QUERIES)} ({sum(1 for q in QUERIES if q.difficulty == 'simple')} simple, "
                 f"{sum(1 for q in QUERIES if q.difficulty == 'medium')} medium, "
                 f"{sum(1 for q in QUERIES if q.difficulty == 'hard')} hard)")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Model | Avg Quality | Avg Latency | Tool Accuracy | Keyword Hit | Errors | Est. Cost/query |")
    lines.append("|-------|------------|-------------|---------------|-------------|--------|-----------------|")

    model_summaries = []
    for model_name, model_id in MODELS:
        if model_id not in all_results:
            continue
        scores: list[Score] = all_results[model_id]["scores"]
        n = len(scores)
        if n == 0:
            continue

        avg_quality = sum(s.quality_score for s in scores) / n
        avg_latency = sum(s.latency for s in scores) / n
        tool_acc = sum(1 for s in scores if s.tool_use_correct) / n * 100
        kw_hit = sum(s.keyword_score for s in scores) / n * 100
        errors = sum(1 for s in scores if s.error)

        # Rough cost estimate (assume ~3K input tokens for prompt + ~500 output)
        input_cost, output_cost = MODEL_COSTS.get(model_id, (0.003, 0.015))
        est_cost = (3 * input_cost) + (0.5 * output_cost)

        lines.append(
            f"| {model_name} | {avg_quality:.0f}/100 | {avg_latency:.1f}s | "
            f"{tool_acc:.0f}% | {kw_hit:.0f}% | {errors}/{n} | ~${est_cost:.4f} |"
        )
        model_summaries.append((model_name, model_id, avg_quality, avg_latency, est_cost))

    lines.append("")

    # Best value pick
    if model_summaries:
        # Score = quality / (latency * cost) — higher is better
        best = max(
            model_summaries,
            key=lambda x: x[2] / max(x[3] * x[4] * 1000, 0.001),
        )
        lines.append(f"**Best value:** {best[0]} (quality {best[2]:.0f}, latency {best[3]:.1f}s, ~${best[4]:.4f}/query)")
        lines.append("")

    # Detailed results per query
    lines.append("## Detailed Results")
    lines.append("")

    for tq in QUERIES:
        lines.append(f"### {tq.name} ({tq.difficulty})")
        lines.append(f"> {tq.query}")
        lines.append("")
        lines.append("| Model | Quality | Latency | Tools | Keywords | Citations | Answer Preview |")
        lines.append("|-------|---------|---------|-------|----------|-----------|----------------|")

        for model_name, model_id in MODELS:
            if model_id not in all_results:
                continue
            result = all_results[model_id]["raw"].get(tq.name, {})
            score = all_results[model_id]["score_map"].get(tq.name)
            if not score:
                continue

            preview = result.get("answer", "")[:80].replace("|", "\\|").replace("\n", " ")
            if score.error:
                preview = f"ERROR: {score.error[:60]}"

            lines.append(
                f"| {model_name} | {score.quality_score:.0f} | {score.latency:.1f}s | "
                f"{'Y' if score.tool_use_correct else 'N'} | "
                f"{score.keywords_found}/{score.keywords_total} | "
                f"{'Y' if score.has_citations else 'N'} | {preview} |"
            )

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Model benchmark for AscendixIQ")
    parser.add_argument("--output", default="docs/model_scorecard.md", help="Output file")
    parser.add_argument("--models", nargs="*", help="Subset of model IDs to test")
    parser.add_argument("--queries", nargs="*", help="Subset of query names to test")
    parser.add_argument("--timeout", type=int, default=60, help="Per-query timeout (seconds)")
    args = parser.parse_args()

    models_to_test = MODELS
    if args.models:
        models_to_test = [(n, m) for n, m in MODELS if m in args.models or n in args.models]

    queries_to_test = QUERIES
    if args.queries:
        queries_to_test = [q for q in QUERIES if q.name in args.queries]

    print(f"Testing {len(models_to_test)} models x {len(queries_to_test)} queries = "
          f"{len(models_to_test) * len(queries_to_test)} calls")
    print(f"Function URL: {FUNCTION_URL}")
    print()

    all_results: dict[str, dict[str, Any]] = {}

    for model_name, model_id in models_to_test:
        print(f"=== {model_name} ({model_id}) ===")
        raw_results = {}
        score_map = {}
        scores = []

        for tq in queries_to_test:
            print(f"  [{tq.difficulty}] {tq.name}...", end=" ", flush=True)
            result = call_query_lambda(tq.query, model_id, timeout=args.timeout)
            s = score_result(tq, result)

            raw_results[tq.name] = result
            score_map[tq.name] = s
            scores.append(s)

            status = f"Q={s.quality_score:.0f} L={s.latency:.1f}s"
            if s.error:
                status = f"ERROR: {s.error[:40]}"
            print(status)

            # Small delay between calls to avoid throttling
            time.sleep(1)

        all_results[model_id] = {
            "scores": scores,
            "raw": raw_results,
            "score_map": score_map,
        }
        print()

    # Generate scorecard
    scorecard = generate_scorecard(all_results)
    output_path = args.output
    with open(output_path, "w") as f:
        f.write(scorecard)
    print(f"Scorecard written to {output_path}")

    # Also print summary to stdout
    print("\n" + "=" * 60)
    for line in scorecard.split("\n"):
        if line.startswith("|") or line.startswith("**Best"):
            print(line)


if __name__ == "__main__":
    main()
