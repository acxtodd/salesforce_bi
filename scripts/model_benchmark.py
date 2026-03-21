#!/usr/bin/env python3
"""Model Benchmark Scorecard v4 — Stress Test Edition.

Sends 10 challenging queries (simple → vague → multi-step) to each model
via the live Query Lambda. If a model returns clarification options,
automatically picks the first option and re-queries to test the full
conversation loop.

Captures full answer text, latency, tool calls, citations, and
clarification behavior for a proper leaderboard.

Usage:
    python3 scripts/model_benchmark.py [--output docs/model_scorecard.md]
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

FUNCTION_URL = os.getenv(
    "QUERY_FUNCTION_URL",
    "https://bxfrvrgbtsn6mpdq7rpnak3dki0cjxpg.lambda-url.us-west-2.on.aws/",
)

ORG_ID = "00Ddl000003yx57EAA"

# Cache the API key at module level
_API_KEY = None

def _get_api_key() -> str:
    global _API_KEY
    if _API_KEY:
        return _API_KEY
    _API_KEY = os.getenv("QUERY_API_KEY", "")
    if not _API_KEY:
        try:
            sm = boto3.client("secretsmanager", region_name="us-west-2")
            secret = sm.get_secret_value(SecretId="salesforce-ai-search/streaming-api-key")
            _API_KEY = json.loads(secret["SecretString"])["apiKey"]
        except Exception:
            _API_KEY = ""
    return _API_KEY


MODELS = [
    ("Claude Haiku 4.5", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    ("Amazon Nova Pro", "us.amazon.nova-pro-v1:0"),
]

# ---------------------------------------------------------------------------
# Test queries — 10 questions, simple to stress-test
# ---------------------------------------------------------------------------

@dataclass
class TestQuery:
    name: str
    query: str
    difficulty: str  # simple, medium, hard, stress
    expected_keywords: list[str] = field(default_factory=list)
    """Keywords that should appear in a correct answer (case-insensitive)."""
    notes: str = ""
    """What we're testing for."""


QUERIES = [
    # 1. Precise multi-filter
    TestQuery(
        name="1. Precise multi-filter",
        query="Find all Class A properties in Plano or Frisco with more than 200,000 SF",
        difficulty="medium",
        expected_keywords=["plano", "frisco"],
        notes="Tests _in filter for multiple cities + numeric filter.",
    ),
    # 2. Relationship chain
    TestQuery(
        name="2. Landlord to tenant chain",
        query="Which tenants lease space in properties owned by Hartman REIT?",
        difficulty="hard",
        expected_keywords=["hartman"],
        notes="Must search properties by owner, then search leases by those property names.",
    ),
    # 3. Time-bounded aggregate
    TestQuery(
        name="3. Year-over-year deals",
        query="How many deals closed in 2024 vs 2025 by market?",
        difficulty="stress",
        expected_keywords=["2024", "2025"],
        notes="Requires two aggregate calls with different date ranges, grouped by market.",
    ),
    # 4. Conversational vague question
    TestQuery(
        name="4. Vague opportunity question",
        query="Where are the opportunities?",
        difficulty="hard",
        expected_keywords=[],
        notes="Extremely vague. Should clarify: opportunities for what? Leasing? Acquisition? Which market?",
    ),
    # 5. Cross-object with specific person
    TestQuery(
        name="5. Person activity",
        query="Show me all activity for Todd Terry — deals, tasks, contacts, everything",
        difficulty="hard",
        expected_keywords=["todd", "terry"],
        notes="Multi-object search for a specific person across all relevant object types.",
    ),
    # 6. Quantitative analysis
    TestQuery(
        name="6. Vacancy analysis",
        query="What is the total available SF by property class in Dallas? Include the number of availabilities in each class.",
        difficulty="stress",
        expected_keywords=["dallas"],
        notes="Requires aggregate on available_sf grouped by property_class + a count aggregate.",
    ),
    # 7. Competitor intelligence
    TestQuery(
        name="7. Competitor analysis",
        query="Show me all deals where JLL, CBRE, or Cushman & Wakefield appears as any broker",
        difficulty="hard",
        expected_keywords=["jll", "cbre", "cushman"],
        notes="Tests multi-value text search across broker name fields.",
    ),
    # 8. What-if advisory
    TestQuery(
        name="8. What-if advisory",
        query="If I wanted to find tenants whose leases expire in the next year who might be looking for new space, how would I do that?",
        difficulty="medium",
        expected_keywords=["lease", "expire"],
        notes="Advisory question — should explain approach and offer clickable query button.",
    ),
    # 9. The stress test from manual testing
    TestQuery(
        name="9. Revenue + deal + property chain",
        query="List the top 5 markets by total deal revenue, show the largest deal in each market, and the property associated with that deal",
        difficulty="stress",
        expected_keywords=["market", "deal", "property"],
        notes="THE hard query. Multi-step: aggregate markets, find top deal per market, look up property.",
    ),
    # 10. Summarize with insight
    TestQuery(
        name="10. Portfolio summary",
        query="Give me a summary of our deal pipeline — how many deals by stage, what's the total value, and which markets have the most pending deals?",
        difficulty="stress",
        expected_keywords=["deal"],
        notes="Requires multiple aggregates: by stage, total sum, by market filtered to pending.",
    ),
]

# ---------------------------------------------------------------------------
# Query execution with clarification follow-up
# ---------------------------------------------------------------------------

def call_query_lambda(question: str, model_id: str, timeout: int = 45) -> dict:
    """Call the Query Lambda and parse SSE response."""
    payload = json.dumps({
        "question": question,
        "org_id": ORG_ID,
        "session_id": f"bench-{int(time.time())}-{hash(question) % 10000}",
        "model_id": model_id,
    }).encode()

    req = urllib.request.Request(
        FUNCTION_URL + "query",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": _get_api_key(),
        },
        method="POST",
    )

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": f"HTTP {e.code}: {body[:300]}", "latency": time.time() - start}
    except Exception as e:
        return {"error": str(e)[:200], "latency": time.time() - start}

    latency = time.time() - start

    # Parse SSE
    answer = ""
    citations = []
    tool_calls = 0
    turns = 0
    returned_model = ""
    clarifications = []
    error = ""

    for line in body.split("\n"):
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                if current_event == "answer":
                    answer = data.get("answer", "")
                elif current_event == "citations":
                    citations = data.get("citations", [])
                elif current_event == "clarification":
                    clarifications = data.get("options", [])
                elif current_event == "error":
                    error = data.get("message", "")
                elif current_event == "done":
                    tool_calls = data.get("tool_calls", 0)
                    turns = data.get("turns", 0)
                    returned_model = data.get("model_id", "")
            except json.JSONDecodeError:
                pass

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


def run_query_with_followup(question: str, model_id: str) -> dict:
    """Run a query; if clarifications come back, pick the first and re-query."""
    result = call_query_lambda(question, model_id)

    # If the model returned clarification options, follow up
    followup_result = None
    if result.get("clarifications") and not result.get("error"):
        first_option = result["clarifications"][0]
        followup_query = first_option.get("query", "")
        if followup_query:
            time.sleep(1)  # Brief pause
            followup_result = call_query_lambda(followup_query, model_id)

    return {
        "initial": result,
        "followup": followup_result,
        "followup_query": first_option.get("query", "") if followup_result else None,
        "total_latency": result["latency"] + (followup_result["latency"] if followup_result else 0),
        "had_clarification": bool(result.get("clarifications")),
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

# Approximate cost per 1K tokens (input, output)
MODEL_COSTS = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (0.0008, 0.004),
    "us.anthropic.claude-sonnet-4-6": (0.003, 0.015),
    "us.anthropic.claude-sonnet-4-20250514-v1:0": (0.003, 0.015),
    "us.amazon.nova-pro-v1:0": (0.0008, 0.0032),
    "us.amazon.nova-lite-v1:0": (0.00006, 0.00024),
    "mistral.mistral-large-3-675b-instruct": (0.002, 0.006),
    "minimax.minimax-m2.5": (0.0011, 0.0044),
    "deepseek.v3.2": (0.0003, 0.0008),
    "zai.glm-5": (0.0005, 0.002),
}


@dataclass
class QueryScore:
    has_answer: bool = False
    has_error: bool = False
    error_msg: str = ""
    answer_length: int = 0
    tool_calls: int = 0
    turns: int = 0
    has_citations: bool = False
    had_clarification: bool = False
    followup_worked: bool = False
    keywords_found: int = 0
    keywords_total: int = 0
    latency: float = 0.0
    total_latency: float = 0.0
    answer_preview: str = ""

    @property
    def quality(self) -> int:
        """0-100 composite quality score."""
        if self.has_error:
            return 0
        score = 0
        # Has a substantive answer (or useful clarification)
        if self.has_answer and self.answer_length > 30:
            score += 25
        elif self.had_clarification:
            score += 15  # Clarification is acceptable behavior
        # Used tools appropriately
        if self.tool_calls > 0:
            score += 20
        elif self.had_clarification:
            score += 10  # No tools needed if clarifying
        # Keywords in answer
        if self.keywords_total > 0:
            score += int(20 * (self.keywords_found / self.keywords_total))
        else:
            score += 10  # No keywords to check
        # Citations present
        if self.has_citations:
            score += 15
        # Efficient (few turns)
        if self.turns <= 2:
            score += 10
        elif self.turns <= 3:
            score += 5
        # Clarification follow-up worked
        if self.had_clarification and self.followup_worked:
            score += 10
        return min(score, 100)


def score_query(tq: TestQuery, run_result: dict) -> QueryScore:
    """Score a single query run."""
    initial = run_result["initial"]
    followup = run_result.get("followup")
    s = QueryScore()

    # Use the best result (followup if it exists and has an answer)
    best = followup if followup and followup.get("answer") and not followup.get("error") else initial

    s.has_error = bool(best.get("error"))
    s.error_msg = best.get("error", "")[:100]
    s.has_answer = bool(best.get("answer") and len(best["answer"]) > 20)
    s.answer_length = best.get("answer_length", 0)
    s.tool_calls = best.get("tool_calls", 0) + initial.get("tool_calls", 0)
    s.turns = best.get("turns", 0)
    s.has_citations = len(best.get("citations", [])) > 0
    s.had_clarification = run_result.get("had_clarification", False)
    s.followup_worked = bool(followup and followup.get("answer") and len(followup.get("answer", "")) > 30)
    s.latency = initial.get("latency", 0)
    s.total_latency = run_result.get("total_latency", s.latency)

    # Keyword matching on best answer
    answer_lower = best.get("answer", "").lower()
    s.keywords_total = len(tq.expected_keywords)
    s.keywords_found = sum(1 for kw in tq.expected_keywords if kw.lower() in answer_lower)

    # Answer preview (first 120 chars, cleaned)
    preview = best.get("answer", "")[:120].replace("\n", " ").replace("|", "/")
    s.answer_preview = preview

    return s


# ---------------------------------------------------------------------------
# Scorecard generation
# ---------------------------------------------------------------------------

def generate_scorecard(all_results: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append("# Model Benchmark Scorecard v4 — Stress Test")
    lines.append(f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    lines.append(f"Queries: {len(QUERIES)} (with clarification follow-up)")
    lines.append(f"Models: {len([m for m in MODELS if m[1] in all_results])}")
    lines.append("")

    # --- Leaderboard ---
    lines.append("## Leaderboard")
    lines.append("")
    lines.append("| Rank | Model | Avg Quality | Avg Latency | Tool Use | Citations | Clarify+Followup | Errors | Est. $/query |")
    lines.append("|------|-------|-------------|-------------|----------|-----------|------------------|--------|-------------|")

    leaderboard = []
    for model_name, model_id in MODELS:
        if model_id not in all_results:
            continue
        scores: list[QueryScore] = all_results[model_id]["scores"]
        n = len(scores)
        if n == 0:
            continue

        avg_q = sum(s.quality for s in scores) / n
        avg_lat = sum(s.total_latency for s in scores) / n
        tool_pct = sum(1 for s in scores if s.tool_calls > 0 or s.had_clarification) / n * 100
        cite_pct = sum(1 for s in scores if s.has_citations) / n * 100
        clarify_ct = sum(1 for s in scores if s.had_clarification)
        followup_ok = sum(1 for s in scores if s.followup_worked)
        errors = sum(1 for s in scores if s.has_error)

        input_cost, output_cost = MODEL_COSTS.get(model_id, (0.003, 0.015))
        est_cost = (3 * input_cost) + (0.5 * output_cost)

        leaderboard.append({
            "name": model_name, "id": model_id, "avg_q": avg_q,
            "avg_lat": avg_lat, "tool_pct": tool_pct, "cite_pct": cite_pct,
            "clarify": clarify_ct, "followup_ok": followup_ok,
            "errors": errors, "n": n, "est_cost": est_cost,
        })

    # Sort by quality desc, then latency asc
    leaderboard.sort(key=lambda x: (-x["avg_q"], x["avg_lat"]))

    for rank, m in enumerate(leaderboard, 1):
        clarify_str = f"{m['clarify']}/{m['n']}"
        if m["followup_ok"]:
            clarify_str += f" ({m['followup_ok']} OK)"
        lines.append(
            f"| {rank} | {m['name']} | {m['avg_q']:.0f}/100 | {m['avg_lat']:.1f}s | "
            f"{m['tool_pct']:.0f}% | {m['cite_pct']:.0f}% | {clarify_str} | "
            f"{m['errors']}/{m['n']} | ${m['est_cost']:.4f} |"
        )

    lines.append("")
    if leaderboard:
        best = leaderboard[0]
        lines.append(f"**Winner:** {best['name']} — quality {best['avg_q']:.0f}/100, "
                     f"latency {best['avg_lat']:.1f}s, ${best['est_cost']:.4f}/query")
    lines.append("")

    # --- Per-query detail ---
    lines.append("## Query Details")
    lines.append("")

    for tq in QUERIES:
        lines.append(f"### {tq.name} [{tq.difficulty}]")
        lines.append(f"> **Query:** {tq.query}")
        lines.append(f"> **Testing:** {tq.notes}")
        lines.append("")
        lines.append("| Model | Q | Latency | Tools | Cites | Clarify | Answer Preview |")
        lines.append("|-------|---|---------|-------|-------|---------|----------------|")

        for model_name, model_id in MODELS:
            if model_id not in all_results:
                continue
            s = all_results[model_id]["score_map"].get(tq.name)
            if not s:
                continue

            clarify = "Y" if s.had_clarification else "-"
            if s.followup_worked:
                clarify = "Y->OK"
            elif s.had_clarification and not s.followup_worked:
                clarify = "Y->fail"

            preview = s.answer_preview[:80] if not s.has_error else f"ERR: {s.error_msg[:60]}"

            lines.append(
                f"| {model_name} | {s.quality} | {s.total_latency:.1f}s | "
                f"{s.tool_calls} | {'Y' if s.has_citations else '-'} | "
                f"{clarify} | {preview} |"
            )

        lines.append("")

    # --- Full answers for review ---
    lines.append("## Full Answers (for manual review)")
    lines.append("")

    for tq in QUERIES:
        lines.append(f"### {tq.name}")
        lines.append(f"> {tq.query}")
        lines.append("")

        for model_name, model_id in MODELS:
            if model_id not in all_results:
                continue
            run = all_results[model_id]["raw"].get(tq.name)
            if not run:
                continue

            initial = run["initial"]
            followup = run.get("followup")

            lines.append(f"**{model_name}** (latency: {initial['latency']:.1f}s, tools: {initial.get('tool_calls', 0)}, "
                        f"citations: {len(initial.get('citations', []))})")

            answer = initial.get("answer", "")
            if initial.get("error"):
                lines.append(f"```\nERROR: {initial['error'][:200]}\n```")
            elif answer:
                # Truncate very long answers for readability
                if len(answer) > 1000:
                    lines.append(f"```\n{answer[:1000]}\n... (truncated, {len(answer)} chars total)\n```")
                else:
                    lines.append(f"```\n{answer}\n```")
            else:
                lines.append("```\n(no answer)\n```")

            if initial.get("clarifications"):
                opts = [f"  - {o.get('label', '?')}: {o.get('query', '?')}" for o in initial["clarifications"]]
                lines.append("Clarification options:\n" + "\n".join(opts))

            if followup:
                lines.append(f"\n*Follow-up query:* `{run.get('followup_query', '')}`")
                lines.append(f"*Follow-up result* (latency: {followup['latency']:.1f}s):")
                f_answer = followup.get("answer", "")
                if followup.get("error"):
                    lines.append(f"```\nERROR: {followup['error'][:200]}\n```")
                elif f_answer:
                    if len(f_answer) > 800:
                        lines.append(f"```\n{f_answer[:800]}\n... (truncated)\n```")
                    else:
                        lines.append(f"```\n{f_answer}\n```")

            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Model benchmark v4 — stress test")
    parser.add_argument("--output", default="docs/model_scorecard.md", help="Output file")
    parser.add_argument("--models", nargs="*", help="Subset of model IDs to test")
    parser.add_argument("--timeout", type=int, default=45, help="Per-query timeout (seconds)")
    args = parser.parse_args()

    models_to_test = MODELS
    if args.models:
        models_to_test = [(n, m) for n, m in MODELS if m in args.models or n in args.models]

    total_calls = len(models_to_test) * len(QUERIES)
    print(f"Benchmark v4: {len(models_to_test)} models x {len(QUERIES)} queries = {total_calls} calls")
    print(f"(+ clarification follow-ups where applicable)")
    print(f"Function URL: {FUNCTION_URL}")
    print()

    all_results: dict[str, dict] = {}

    for model_name, model_id in models_to_test:
        print(f"=== {model_name} ({model_id}) ===")
        raw_results = {}
        score_map = {}
        scores = []

        for tq in QUERIES:
            print(f"  [{tq.difficulty:6s}] {tq.name}...", end=" ", flush=True)

            run = run_query_with_followup(tq.query, model_id)
            s = score_query(tq, run)

            raw_results[tq.name] = run
            score_map[tq.name] = s
            scores.append(s)

            status = f"Q={s.quality:2d} L={s.total_latency:.1f}s T={s.tool_calls}"
            if s.had_clarification:
                status += " [clarify"
                if s.followup_worked:
                    status += "->OK"
                status += "]"
            if s.has_error:
                status = f"ERROR: {s.error_msg[:40]}"
            print(status)

            time.sleep(1)

        all_results[model_id] = {
            "scores": scores,
            "raw": raw_results,
            "score_map": score_map,
        }
        print()

    # Generate scorecard
    scorecard = generate_scorecard(all_results)
    with open(args.output, "w") as f:
        f.write(scorecard)
    print(f"\nScorecard written to {args.output}")
    print(f"Total: {len(QUERIES)} queries x {len(models_to_test)} models")

    # Print leaderboard
    print("\n" + "=" * 70)
    for line in scorecard.split("\n"):
        if line.startswith("| Rank") or line.startswith("| ---") or (line.startswith("|") and line[2:3].isdigit()) or line.startswith("**Winner"):
            print(line)


if __name__ == "__main__":
    main()
