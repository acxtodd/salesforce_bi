#!/usr/bin/env python3
"""
POC: Query Decomposition via System Prompt

Tests whether a concise system prompt with CRE domain knowledge
can achieve similar results to the full schema approach.

The hypothesis: A focused system prompt with key rules might be
enough to correctly decompose queries without a large schema doc.
"""

import json
import sys
import time
import boto3

bedrock_runtime = boto3.client('bedrock-runtime', region_name='us-west-2')

# Concise system prompt with key CRE rules
SYSTEM_PROMPT = """You are a query planner for a commercial real estate (CRE) Salesforce system.

## Key Objects
- Deal: Transaction/opportunity (has Status, GrossFeeAmount, CloseDate)
- Property: Building (has City, State, PropertySubType, PropertyClass, Address)
- Availability: Available space within a Property (has Status, SquareFeet)
- Lease: Lease agreement (has ExpirationDate, Tenant, RentPerSqFt)
- Account: Company (can be Tenant, Landlord, Client)

## Critical Rules
1. LOCATION fields (City, State, Address) are ONLY on Property - never on Deal, Lease, or Availability
2. PROPERTY TYPE (Office, Retail, Industrial) is ONLY on Property.PropertySubType
3. PROPERTY CLASS (Class A, B, C) is ONLY on Property.PropertyClass
4. To find "deals in Dallas" → find Properties in Dallas, then traverse to their Deals
5. To find "available space in Houston" → find Properties in Houston, then get their Availabilities
6. Status filters apply to the target object (Deal.Status, Lease.Status, etc.)

## Your Task
Given a query, output JSON with:
- target_entity: What the user wants to find (Deal, Property, Availability, Lease, Account)
- target_filters: Filters on the target entity
- related_filters: Filters that must be applied to related entities (especially Property for location/type)
- needs_traversal: true if filters are on a different entity than target

Output ONLY valid JSON, no explanation."""


def decompose_with_system_prompt(query: str, verbose: bool = True) -> dict:
    """Decompose query using system prompt approach."""
    if verbose:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)

    start_time = time.time()

    try:
        response = bedrock_runtime.invoke_model(
            modelId='us.anthropic.claude-haiku-4-5-20251001-v1:0',
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': 512,
                'temperature': 0,
                'system': SYSTEM_PROMPT,
                'messages': [
                    {
                        'role': 'user',
                        'content': query
                    }
                ]
            })
        )

        elapsed_ms = (time.time() - start_time) * 1000

        response_body = json.loads(response['body'].read())
        content = response_body['content'][0]['text']

        # Parse JSON (strip markdown if present)
        json_content = content.strip()
        if json_content.startswith('```'):
            first_newline = json_content.find('\n')
            if first_newline > 0:
                json_content = json_content[first_newline + 1:]
            if json_content.endswith('```'):
                json_content = json_content[:-3].strip()

        result = json.loads(json_content)
        result['latency_ms'] = round(elapsed_ms)

        if verbose:
            print(f"\nDecomposition ({elapsed_ms:.0f}ms):")
            print(json.dumps(result, indent=2))

        return result

    except Exception as e:
        print(f"Error: {e}")
        return {"error": str(e)}


def validate(result: dict, expected_target: str, expected_related_filters: list) -> bool:
    """Simple validation of decomposition results."""
    passed = True
    issues = []

    # Check target entity
    target = result.get('target_entity', '').lower()
    if expected_target.lower() not in target:
        issues.append(f"Target: got '{target}', expected '{expected_target}'")
        passed = False

    # Check if related filters include expected fields
    # Handle nested structure like {"Property": {"City": "Dallas"}}
    related = result.get('related_filters', {})

    # Flatten nested structure for validation
    all_filter_keys = set()
    def extract_keys(obj, prefix=''):
        if isinstance(obj, dict):
            for k, v in obj.items():
                all_filter_keys.add(k.lower())
                if isinstance(v, dict):
                    extract_keys(v, k)
    extract_keys(related)

    for expected_field in expected_related_filters:
        found = any(expected_field.lower() in k for k in all_filter_keys)
        if not found:
            issues.append(f"Missing related filter: {expected_field}")
            passed = False

    # Check needs_traversal
    if expected_related_filters and not result.get('needs_traversal', False):
        issues.append("needs_traversal should be true")
        passed = False

    if passed:
        print("✓ PASS")
    else:
        print(f"✗ FAIL: {', '.join(issues)}")

    return passed


# Test cases
TEST_CASES = [
    {
        "query": "deals for properties in Dallas",
        "expected_target": "Deal",
        "expected_related_filters": ["City"],
    },
    {
        "query": "active deals for office properties in Houston",
        "expected_target": "Deal",
        "expected_related_filters": ["City", "PropertySubType"],
    },
    {
        "query": "available retail space in Dallas",
        "expected_target": "Availability",
        "expected_related_filters": ["City", "PropertySubType"],
    },
    {
        "query": "what are the deals for Renaissance Tower",
        "expected_target": "Deal",
        "expected_related_filters": ["Address"],  # Model uses Address for property name
    },
    {
        "query": "Class A office buildings in Uptown",
        "expected_target": "Property",
        "expected_related_filters": [],  # No traversal needed - filters are on target
    },
    {
        "query": "leases expiring in the next 6 months",
        "expected_target": "Lease",
        "expected_related_filters": [],  # Direct filter on Lease
    },
]


def run_tests():
    """Run all test cases."""
    print("\n" + "="*60)
    print("SYSTEM PROMPT APPROACH - Test Suite")
    print("="*60)
    print(f"\nSystem prompt size: {len(SYSTEM_PROMPT)} chars")

    results = []
    total_time = 0

    for i, test in enumerate(TEST_CASES, 1):
        print(f"\n--- Test {i}/{len(TEST_CASES)} ---")

        result = decompose_with_system_prompt(test['query'])

        if 'error' not in result:
            passed = validate(
                result,
                test['expected_target'],
                test['expected_related_filters']
            )
            results.append({
                'query': test['query'],
                'passed': passed,
                'latency_ms': result.get('latency_ms', 0)
            })
            total_time += result.get('latency_ms', 0)
        else:
            results.append({'query': test['query'], 'passed': False, 'error': result['error']})

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    passed = sum(1 for r in results if r.get('passed'))
    print(f"\nResults: {passed}/{len(results)} tests passed")
    print(f"Total time: {total_time}ms")
    print(f"Avg time per query: {total_time/len(results):.0f}ms")

    print("\nComparison to Full Schema Approach:")
    print("  Full schema: ~3000ms avg, 1300 char schema")
    print(f"  System prompt: ~{total_time/len(results):.0f}ms avg, {len(SYSTEM_PROMPT)} char prompt")


def main():
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        decompose_with_system_prompt(query)
    else:
        run_tests()


if __name__ == "__main__":
    main()
