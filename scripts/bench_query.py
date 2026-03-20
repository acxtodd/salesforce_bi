#!/usr/bin/env python3
"""Benchmark query Lambda with a battery of test queries.

Queries the deployed Lambda, verifies which model is serving, and checks
answer quality including behavioral rules (no IDs, no emojis, tool usage).

Usage:
    python3 scripts/bench_query.py                  # auto-detects model
    python3 scripts/bench_query.py "Haiku 4.5"      # cosmetic label override
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error

QUERY_URL = "https://bxfrvrgbtsn6mpdq7rpnak3dki0cjxpg.lambda-url.us-west-2.on.aws/query"
ORG_ID = "00Ddl000003yx57EAA"
LAMBDA_NAME = "salesforce-ai-search-query"
AWS_REGION = "us-west-2"

# Regex for Salesforce 15/18-char IDs (e.g. a0Pfk000000CkTLEA0, 003fk000000gO3GAAU)
_SF_ID_PATTERN = re.compile(r"\b[a-zA-Z0-9]{15,18}\b")
# Common SF ID prefixes (3-char key prefixes for standard/custom objects)
_SF_ID_PREFIXES = re.compile(
    r"\b(?:001|003|005|006|00T|00U|a0[A-Za-z])[a-zA-Z0-9]{12,15}\b"
)
# Emoji detection (Unicode emoji ranges)
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F9FF"  # Misc Symbols, Emoticons, etc.
    "\U00002702-\U000027B0"  # Dingbats
    "\U0000FE00-\U0000FE0F"  # Variation Selectors
    "\U0000200D"             # ZWJ
    "\U000025A0-\U000025FF"  # Geometric Shapes
    "]+",
    re.UNICODE,
)


def _get_deployed_model() -> str:
    """Read BEDROCK_MODEL_ID from the deployed Lambda's environment."""
    try:
        raw = subprocess.check_output([
            "aws", "lambda", "get-function-configuration",
            "--function-name", LAMBDA_NAME,
            "--query", "Environment.Variables.BEDROCK_MODEL_ID",
            "--output", "text",
            "--region", AWS_REGION,
        ], text=True, stderr=subprocess.DEVNULL).strip()
        return raw
    except Exception:
        return "unknown"


def _get_api_key() -> str:
    """Retrieve API key from Secrets Manager."""
    key = os.environ.get("QUERY_API_KEY", "")
    if key:
        return key
    secret_arn = "salesforce-ai-search/streaming-api-key"
    raw = subprocess.check_output([
        "aws", "secretsmanager", "get-secret-value",
        "--secret-id", secret_arn,
        "--region", AWS_REGION,
        "--query", "SecretString",
        "--output", "text",
    ], text=True).strip()
    return json.loads(raw).get("apiKey", "")


API_KEY = _get_api_key()

QUERIES = [
    ("Property filter+text",   "Show me Class A office buildings in Dallas"),
    ("Deal pipeline",          "Find closed deals this year with gross fee over 50000"),
    ("Sale comp",              "What sale comps exist in Dallas with cap rate above 5%?"),
    ("Inquiry geography",      "Show active inquiries for office space in Houston"),
    ("Listing price filter",   "Find active listings with asking price under 5 million"),
    ("Contact text search",    "Show me contacts at Transwestern"),
    ("Cross-object",           "Show me deals and listings for properties in Dallas"),
    ("Aggregation",            "How many deals do we have by sales stage?"),
]


def run_benchmark() -> None:
    # Detect deployed model
    deployed_model = _get_deployed_model()
    label = sys.argv[1] if len(sys.argv) > 1 else deployed_model

    print(f"\n{'=' * 70}")
    print(f"  Benchmark: {label}")
    print(f"  Deployed model: {deployed_model}")
    print(f"  Endpoint: {QUERY_URL}")
    print(f"{'=' * 70}")

    total_pass = 0
    total_fail = 0
    total_latency = 0.0
    behavioral_violations: list[str] = []

    for tag, question in QUERIES:
        payload = json.dumps({
            "question": question,
            "org_id": ORG_ID,
        }).encode()

        req = urllib.request.Request(
            QUERY_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": API_KEY,
            },
        )

        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode()
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
        except Exception as e:
            body = f"ERROR: {e}"
        elapsed = time.perf_counter() - start
        total_latency += elapsed

        # Parse SSE
        tokens: list[str] = []
        tool_calls = 0
        turns = 0
        for line in body.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                data_str = line[6:]
                try:
                    d = json.loads(data_str)
                    if "text" in d:
                        tokens.append(d["text"])
                    if "tool_calls" in d:
                        tool_calls = d["tool_calls"]
                        turns = d.get("turns", 0)
                except json.JSONDecodeError:
                    pass

        answer = " ".join(tokens).strip()
        answer_preview = answer[:250] + ("..." if len(answer) > 250 else "")

        # --- Quality checks ---
        has_answer = len(answer) > 20
        used_tools = tool_calls > 0

        # Behavioral checks
        sf_ids_found = _SF_ID_PREFIXES.findall(answer)
        has_leaked_ids = len(sf_ids_found) > 0
        emojis_found = _EMOJI_PATTERN.findall(answer)
        has_emojis = len(emojis_found) > 0

        # Overall quality
        issues: list[str] = []
        if not has_answer:
            issues.append("NO_ANSWER")
        if not used_tools:
            issues.append("NO_TOOLS")
        if has_leaked_ids:
            issues.append(f"LEAKED_IDS({len(sf_ids_found)})")
        if has_emojis:
            issues.append(f"EMOJIS({len(emojis_found)})")

        if issues:
            quality = "FAIL" if ("NO_ANSWER" in issues or "NO_TOOLS" in issues) else "WARN"
            total_fail += 1
            for issue in issues:
                behavioral_violations.append(f"[{tag}] {issue}")
        else:
            quality = "OK"
            total_pass += 1

        status_str = f"{quality} {' '.join(issues)}" if issues else quality
        print(f"\n[{tag}] {elapsed:.1f}s | tools={tool_calls} turns={turns} | {status_str}")
        print(f"  Q: {question}")
        print(f"  A: {answer_preview}")

    # Summary
    avg_latency = total_latency / len(QUERIES) if QUERIES else 0
    print(f"\n{'=' * 70}")
    print(f"  SUMMARY: {label} ({deployed_model})")
    print(f"  Pass: {total_pass}/{len(QUERIES)} | Avg latency: {avg_latency:.1f}s")
    if behavioral_violations:
        print(f"  Behavioral violations:")
        for v in behavioral_violations:
            print(f"    - {v}")
    else:
        print(f"  Behavioral: all clean (no IDs, no emojis)")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    run_benchmark()
