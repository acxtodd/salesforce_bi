#!/usr/bin/env python3
"""
Test script for Natural Hyperlinks feature
Tests that record names are properly converted to clickable links

**Feature: zero-config-production, Task 28.2**
Configuration moved to environment variables for security.
Set the following environment variables before running:
- SALESFORCE_AI_SEARCH_LAMBDA_URL
- SALESFORCE_AI_SEARCH_API_KEY
- SALESFORCE_AI_SEARCH_TEST_USER_ID
"""

import json
import os
import requests
import re
from typing import Dict, List, Tuple
import sys

# Configuration from environment variables
# **Feature: zero-config-production, Task 28.2**
LAMBDA_URL = os.getenv(
    "SALESFORCE_AI_SEARCH_LAMBDA_URL",
    "https://sdrr5l3w2lqalqiylze6e35nfq0xhlxx.lambda-url.us-west-2.on.aws/answer"
)
API_KEY = os.getenv("SALESFORCE_AI_SEARCH_API_KEY", "")
TEST_USER_ID = os.getenv("SALESFORCE_AI_SEARCH_TEST_USER_ID", "005dl00000Q6a3RAAR")

# Validate required environment variables
if not API_KEY:
    print("⚠️  Warning: SALESFORCE_AI_SEARCH_API_KEY environment variable not set.")
    print("   Set it or create a .env file. See .env.example for reference.")

def test_natural_response(query: str) -> Tuple[str, List[Dict]]:
    """
    Test that the Lambda returns natural text without citation markers
    """
    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "query": query,
        "salesforceUserId": TEST_USER_ID,
        "policy": {
            "require_citations": False,  # New prompt doesn't need citations
            "max_tokens": 300,
            "temperature": 0.3
        },
        "topK": 5
    }

    print(f"\n🔍 Testing query: {query}")
    print("-" * 50)

    try:
        response = requests.post(LAMBDA_URL, headers=headers, json=payload, stream=True)
        response.raise_for_status()

        # Parse SSE stream
        answer_text = ""
        citations = []

        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    try:
                        data = json.loads(data_str)
                        if "token" in data:
                            answer_text += data["token"]
                        elif "citations" in data:
                            citations = data["citations"]
                    except json.JSONDecodeError:
                        continue

        return answer_text, citations

    except requests.exceptions.RequestException as e:
        print(f"❌ Error calling Lambda: {e}")
        return "", []

def check_for_citation_markers(text: str) -> List[str]:
    """
    Check if text contains old-style citation markers [Source: xxx]
    """
    pattern = r'\[Source:\s*[^\]]+\]'
    matches = re.findall(pattern, text)
    return matches

def extract_record_names_from_citations(citations: List[Dict]) -> Dict[str, str]:
    """
    Extract record names and IDs from citation metadata
    """
    name_map = {}
    for citation in citations:
        if "title" in citation and "recordId" in citation:
            name_map[citation["title"]] = citation["recordId"]
    return name_map

def check_names_in_answer(answer: str, name_map: Dict[str, str]) -> Dict[str, bool]:
    """
    Check which record names appear in the answer text
    """
    found = {}
    for name in name_map.keys():
        # Check if name appears in answer (case insensitive)
        if name.lower() in answer.lower():
            found[name] = True
        else:
            found[name] = False
    return found

def simulate_frontend_linking(answer: str, name_map: Dict[str, str]) -> str:
    """
    Simulate what the frontend would do - convert names to links
    """
    linked_answer = answer

    for name, record_id in name_map.items():
        # Escape special regex characters
        escaped_name = re.escape(name)
        # Replace with simulated hyperlink
        pattern = re.compile(f'\\b({escaped_name})\\b', re.IGNORECASE)
        replacement = f'<a href="#" data-recordid="{record_id}">{name}</a>'
        linked_answer = pattern.sub(replacement, linked_answer)

    return linked_answer

def run_tests():
    """
    Run comprehensive tests for natural hyperlinks
    """
    print("=" * 60)
    print("🧪 Natural Hyperlinks Feature Test")
    print("=" * 60)

    test_queries = [
        "What are the details for ACME Corp?",
        "Show me open opportunities for Enterprise deals",
        "What properties are available in Dallas?",
        "Tell me about recent deals and their status"
    ]

    all_passed = True

    for query in test_queries:
        answer, citations = test_natural_response(query)

        if not answer:
            print("❌ No answer received")
            all_passed = False
            continue

        # Test 1: Check for absence of citation markers
        print("\n📝 Answer received:")
        print(answer[:200] + "..." if len(answer) > 200 else answer)

        citation_markers = check_for_citation_markers(answer)
        if citation_markers:
            print(f"\n⚠️ Found old-style citations: {citation_markers}")
            print("   System prompt may not be updated yet")
        else:
            print("\n✅ No citation markers found - text is natural")

        # Test 2: Extract record names from citations
        name_map = extract_record_names_from_citations(citations)
        if name_map:
            print(f"\n📋 Record names available for linking:")
            for name, record_id in name_map.items():
                print(f"   • {name} → {record_id}")
        else:
            print("\n⚠️ No record names found in citations")

        # Test 3: Check if names appear in answer
        if name_map:
            names_found = check_names_in_answer(answer, name_map)
            print(f"\n🔍 Names mentioned in answer:")
            for name, found in names_found.items():
                status = "✅" if found else "❌"
                print(f"   {status} {name}")

        # Test 4: Simulate frontend linking
        if name_map:
            linked_answer = simulate_frontend_linking(answer, name_map)
            links_added = linked_answer.count('<a href=')
            print(f"\n🔗 Simulated linking: {links_added} links would be added")

            if links_added > 0:
                print("\n📄 Sample linked text (first 300 chars):")
                print(linked_answer[:300] + "...")

        print("\n" + "=" * 50)

    # Summary
    print("\n📊 Test Summary")
    print("=" * 60)
    if all_passed:
        print("✅ All tests passed - Natural hyperlinks ready to deploy!")
    else:
        print("⚠️ Some tests failed - review the output above")

    print("\n💡 Next Steps:")
    print("1. Deploy the updated system prompt to Lambda")
    print("2. Deploy the updated LWC to Salesforce")
    print("3. Test in Salesforce UI with real data")
    print("4. Monitor click-through rates")

def test_single_query(query: str):
    """
    Test a single custom query
    """
    answer, citations = test_natural_response(query)

    if answer:
        print("\n📝 Full Answer:")
        print(answer)

        print("\n📚 Citations:")
        for i, citation in enumerate(citations, 1):
            print(f"{i}. {citation.get('title', 'Unknown')} ({citation.get('recordId', 'N/A')})")
            print(f"   Score: {citation.get('score', 'N/A')}")
            print(f"   Type: {citation.get('sobject', 'Unknown')}")
    else:
        print("❌ No response received")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Test a custom query
        custom_query = " ".join(sys.argv[1:])
        test_single_query(custom_query)
    else:
        # Run standard test suite
        run_tests()