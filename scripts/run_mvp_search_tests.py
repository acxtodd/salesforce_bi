#!/usr/bin/env python3
"""Run MVP search tests from the QA spreadsheet against the live query Lambda.

Extracts Search capability tests from the CSV, runs each against the deployed
Lambda, and reports pass/fail with gap analysis.
"""

import csv
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
AWS_REGION = "us-west-2"

# Object type keywords to detect in answers
OBJECT_KEYWORDS = {
    "Property": ["property", "building", "properties", "buildings"],
    "Lease": ["lease", "leases"],
    "Availability": ["availability", "available", "availabilities", "space"],
    "Account": ["account", "company", "companies", "accounts"],
    "Contact": ["contact", "contacts"],
    "Deal": ["deal", "deals"],
    "Sale": ["sale", "sales", "comp", "comps"],
    "Inquiry": ["inquiry", "inquiries"],
    "Listing": ["listing", "listings"],
    "Preference": ["preference", "preferences"],
    "Task": ["task", "tasks"],
}


def _get_api_key() -> str:
    key = os.environ.get("QUERY_API_KEY", "")
    if key:
        return key
    raw = subprocess.check_output([
        "aws", "secretsmanager", "get-secret-value",
        "--secret-id", "salesforce-ai-search/streaming-api-key",
        "--region", AWS_REGION,
        "--query", "SecretString",
        "--output", "text",
    ], text=True).strip()
    return json.loads(raw).get("apiKey", "")


def run_query(question: str, api_key: str) -> dict:
    """Run a single query and return parsed results."""
    payload = json.dumps({
        "question": question,
        "org_id": ORG_ID,
    }).encode()

    req = urllib.request.Request(
        QUERY_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
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

    tokens = []
    tool_calls = 0
    turns = 0
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                d = json.loads(line[6:])
                if "text" in d:
                    tokens.append(d["text"])
                if "tool_calls" in d:
                    tool_calls = d["tool_calls"]
                    turns = d.get("turns", 0)
            except json.JSONDecodeError:
                pass

    answer = " ".join(tokens).strip()
    return {
        "answer": answer,
        "tool_calls": tool_calls,
        "turns": turns,
        "elapsed": elapsed,
    }


def detect_object_type(answer: str) -> str:
    """Guess which object type the answer is about."""
    answer_lower = answer.lower()
    for obj_type, keywords in OBJECT_KEYWORDS.items():
        for kw in keywords:
            if kw in answer_lower:
                return obj_type
    return "Unknown"


def check_expected(answer: str, expected: str) -> tuple[bool, str]:
    """Check if the answer meets the expected result description."""
    answer_lower = answer.lower()
    expected_lower = expected.lower()

    # No answer at all
    if len(answer) < 20:
        return False, "NO_ANSWER"

    # Check for "no results" when we expected results
    no_result_phrases = ["no results", "no records", "not found", "no matching",
                         "couldn't find", "could not find", "0 results", "none found",
                         "no data", "no active"]
    has_no_results = any(p in answer_lower for p in no_result_phrases)

    # Check if expected type appears in answer
    if "retrieve" in expected_lower:
        # Expected to retrieve records
        expected_type = expected_lower.replace("retrieve ", "").strip()
        if has_no_results:
            return False, f"EMPTY_RESULTS (expected {expected_type})"

    # Check for table/list (indicates structured results)
    has_table = "|" in answer and "---" in answer
    has_list = answer.count("\n") > 2

    if has_no_results and "missing" not in expected_lower:
        return False, "EMPTY_RESULTS"

    return True, "OK"


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else \
        "/Users/toddadmin/Downloads/[xRE Chat] MVP Prompts and tests(MVP Prompts (Make a copy)).csv"

    api_key = _get_api_key()

    # Parse CSV — search tests are in columns 10-18
    with open(csv_path) as f:
        reader = csv.reader(f)
        rows = list(reader)

    tests = []
    for row in rows[2:]:  # Skip headers
        if len(row) > 13:
            test_no = row[10].strip()
            prompt = row[12].strip()
            expected = row[13].strip()
            if prompt:
                tests.append({
                    "id": f"S{test_no}" if test_no else "S?",
                    "prompt": prompt,
                    "expected": expected,
                })

    print(f"\n{'=' * 70}")
    print(f"  MVP Search Tests — {len(tests)} tests")
    print(f"{'=' * 70}")

    results = []
    for test in tests:
        print(f"\n--- {test['id']}: {test['prompt'][:80]}...")
        result = run_query(test["prompt"], api_key)

        passed, status = check_expected(result["answer"], test["expected"])
        obj_type = detect_object_type(result["answer"])
        preview = result["answer"][:200] + ("..." if len(result["answer"]) > 200 else "")

        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}] {result['elapsed']:.1f}s | tools={result['tool_calls']} | {status}")
        print(f"  Expected: {test['expected']}")
        print(f"  Detected: {obj_type}")
        print(f"  Answer: {preview}")

        results.append({
            **test,
            "passed": passed,
            "status": status,
            "elapsed": result["elapsed"],
            "tool_calls": result["tool_calls"],
            "answer_preview": preview,
            "detected_type": obj_type,
        })

    # Summary
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])

    print(f"\n{'=' * 70}")
    print(f"  SUMMARY: {passed}/{len(results)} passed, {failed} failed")
    print(f"  Avg latency: {sum(r['elapsed'] for r in results) / len(results):.1f}s")

    if failed:
        print(f"\n  GAPS:")
        for r in results:
            if not r["passed"]:
                print(f"    {r['id']}: {r['status']}")
                print(f"      Prompt: {r['prompt'][:100]}")
                print(f"      Expected: {r['expected']}")

    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
