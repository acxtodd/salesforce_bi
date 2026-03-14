#!/usr/bin/env python3
"""
Proof of Concept: LLM-Based Query Decomposition

This script tests the concept of using an LLM to decompose natural language
queries into structured query plans that can drive graph traversal.

Usage:
    python query_decomposition_poc.py "deals for properties in Dallas"
    python query_decomposition_poc.py  # runs all test cases
"""

import json
import sys
import time
import boto3

# Initialize Bedrock client
bedrock_runtime = boto3.client('bedrock-runtime', region_name='us-west-2')

# Minimal CRE Schema for POC (subset of full schema from PRD)
CRE_SCHEMA = """
# CRE Data Model Schema for Query Decomposition

## Objects and Relationships

### ascendix__Deal__c (Deal)
A real estate transaction or opportunity.

Key Fields:
- ascendix__Status__c: Deal status (Active, Closed Won, Closed Lost, Pipeline, Pending)
- ascendix__SalesStage__c: Sales pipeline stage
- ascendix__GrossFeeAmount__c: Commission/fee amount (currency)
- ascendix__DealSubType__c: Type of deal (Lease, Sale, Sublease, Renewal)
- ascendix__CloseDate__c: Expected or actual close date

Relationships:
- ascendix__Property__c → ascendix__Property__c (lookup to Property)
- ascendix__Availability__c → ascendix__Availability__c (lookup to available space)
- ascendix__Tenant__c → Account (tenant company)

IMPORTANT: Deals do NOT have location fields (City, State). Location comes from related Property.

### ascendix__Property__c (Property)
A real estate property or building.

Location Fields (ONLY on Property):
- ascendix__City__c: City name (e.g., "Dallas", "Houston", "Austin")
- ascendix__State__c: State abbreviation (e.g., "TX", "CA")
- ascendix__Address__c: Street address
- ascendix__PostalCode__c: ZIP code

Classification Fields:
- ascendix__PropertySubType__c: Property type (Office, Retail, Industrial, Warehouse, Multifamily)
- ascendix__PropertyClass__c: Building class (Class A, Class B, Class C)
- ascendix__TotalSquareFeet__c: Total building size

Relationships:
- ascendix__Market__c → ascendix__Market__c (market/metro area)
- ascendix__SubMarket__c → ascendix__SubMarket__c (submarket)
- ascendix__OwnerLandlord__c → Account (property owner)

### ascendix__Availability__c (Available Space)
Available space within a property.

Key Fields:
- ascendix__Status__c: Availability status (Available, Under LOI, Leased)
- ascendix__SquareFeet__c: Size in square feet
- ascendix__AskingRate__c: Asking lease rate

Relationships:
- ascendix__Property__c → ascendix__Property__c (REQUIRED - parent property)

IMPORTANT: Availability INHERITS location from parent Property. To find "space in Dallas", traverse Availability → Property → City.

### ascendix__Lease__c (Lease)
A lease agreement.

Key Fields:
- ascendix__LeaseType__c: Type (NNN, Full Service, Modified Gross)
- ascendix__TermExpirationDate__c: Lease end date
- ascendix__RentPerSqFt__c: Rent rate

Relationships:
- ascendix__Property__c → ascendix__Property__c (property)
- ascendix__Tenant__c → Account (tenant)

## Query Interpretation Rules

1. Location filters (city, state, market) ALWAYS apply to Property, not Deal/Lease/Availability
2. Property type filters (office, retail, industrial) apply to Property.PropertySubType
3. "Deals in Dallas" means: Find Properties where City=Dallas, then traverse to Deals
4. "Available space in Houston" means: Find Properties where City=Houston, then find child Availabilities
5. Status filters apply to the target entity (Deal.Status, Lease.Status, etc.)
"""

DECOMPOSITION_PROMPT = """You are a query planner for a commercial real estate CRM system.

Given the data model schema below and a user query, decompose the query into a structured query plan.

<schema>
{schema}
</schema>

<query>
{query}
</query>

Respond with a JSON object containing:

1. "target_entity": The Salesforce object API name the user wants to find (e.g., "ascendix__Deal__c")

2. "target_filters": Array of filters that apply directly to the target entity
   Each filter: {{"field": "API_name", "operator": "equals|in|greater_than|less_than|between|contains", "value": "..."}}

3. "related_entities": Array of related entities with filters that require traversal
   Each: {{
     "entity": "API_name",
     "relationship_field": "field that connects to target",
     "filters": [same format as target_filters],
     "traversal_direction": "target_to_related" or "related_to_target"
   }}

4. "traversal_paths": Array of strings describing the traversal path
   Example: "Deal.ascendix__Property__c → Property"

5. "search_strategy": Array describing optimal order to execute the search
   Example: ["Find Properties with filters", "Traverse to Deals", "Apply Deal filters"]

6. "confidence": Number 0-1 indicating confidence in the decomposition

7. "reasoning": Brief explanation of how you interpreted the query

Respond ONLY with valid JSON, no additional text or markdown formatting.
"""


def decompose_query(query: str, verbose: bool = True) -> dict:
    """
    Call Bedrock to decompose a natural language query into a structured query plan.

    Args:
        query: Natural language query
        verbose: Print progress messages

    Returns:
        Structured query plan dict
    """
    if verbose:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)

    # Build the prompt
    prompt = DECOMPOSITION_PROMPT.format(
        schema=CRE_SCHEMA,
        query=query
    )

    # Call Bedrock (Claude Haiku for speed/cost)
    start_time = time.time()

    try:
        response = bedrock_runtime.invoke_model(
            modelId='us.anthropic.claude-haiku-4-5-20251001-v1:0',  # Haiku 4.5 US profile
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': 1024,
                'temperature': 0,
                'messages': [
                    {
                        'role': 'user',
                        'content': prompt
                    }
                ]
            })
        )

        elapsed_ms = (time.time() - start_time) * 1000

        # Parse response
        response_body = json.loads(response['body'].read())
        content = response_body['content'][0]['text']

        # Parse the JSON from the response (strip markdown code blocks if present)
        try:
            json_content = content.strip()
            # Remove markdown code blocks if present
            if json_content.startswith('```'):
                # Find the end of the first line (```json or ```)
                first_newline = json_content.find('\n')
                if first_newline > 0:
                    json_content = json_content[first_newline + 1:]
                # Remove trailing ```
                if json_content.endswith('```'):
                    json_content = json_content[:-3].strip()

            result = json.loads(json_content)
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON: {e}")
            print(f"Raw response: {content}")
            return {"error": str(e), "raw": content}

        if verbose:
            print(f"\nDecomposition ({elapsed_ms:.0f}ms):")
            print(json.dumps(result, indent=2))

        return result

    except Exception as e:
        print(f"Error calling Bedrock: {e}")
        return {"error": str(e)}


def validate_decomposition(query: str, result: dict, expected: dict) -> bool:
    """
    Validate that the decomposition matches expected output.

    Returns True if validation passes.
    """
    passed = True
    issues = []

    # Check target entity
    if result.get('target_entity') != expected.get('target_entity'):
        issues.append(f"target_entity: got {result.get('target_entity')}, expected {expected.get('target_entity')}")
        passed = False

    # Check related entities exist
    expected_related = expected.get('related_entities', [])
    result_related = result.get('related_entities', [])

    for exp_rel in expected_related:
        found = False
        for res_rel in result_related:
            if res_rel.get('entity') == exp_rel.get('entity'):
                found = True
                # Check filters on related entity
                exp_filters = {f['field']: f['value'] for f in exp_rel.get('filters', [])}
                res_filters = {f['field']: f['value'] for f in res_rel.get('filters', [])}
                for field, value in exp_filters.items():
                    if field not in res_filters:
                        issues.append(f"Missing filter {field}={value} on {exp_rel['entity']}")
                        passed = False
                break
        if not found:
            issues.append(f"Missing related entity: {exp_rel.get('entity')}")
            passed = False

    # Check confidence
    confidence = result.get('confidence', 0)
    if confidence < 0.7:
        issues.append(f"Low confidence: {confidence}")

    # Print validation result
    if passed:
        print(f"\n✓ PASS: Decomposition is correct")
    else:
        print(f"\n✗ FAIL: Decomposition issues:")
        for issue in issues:
            print(f"  - {issue}")

    return passed


# Test cases with expected outputs
TEST_CASES = [
    {
        "query": "deals for properties in Dallas",
        "expected": {
            "target_entity": "ascendix__Deal__c",
            "related_entities": [
                {
                    "entity": "ascendix__Property__c",
                    "filters": [
                        {"field": "ascendix__City__c", "value": "Dallas"}
                    ]
                }
            ]
        },
        "description": "Location filter on related Property"
    },
    {
        "query": "active deals for office properties in Houston",
        "expected": {
            "target_entity": "ascendix__Deal__c",
            "target_filters": [
                {"field": "ascendix__Status__c", "value": "Active"}
            ],
            "related_entities": [
                {
                    "entity": "ascendix__Property__c",
                    "filters": [
                        {"field": "ascendix__City__c", "value": "Houston"},
                        {"field": "ascendix__PropertySubType__c", "value": "Office"}
                    ]
                }
            ]
        },
        "description": "Status filter on target + location/type on related"
    },
    {
        "query": "available retail space in Dallas",
        "expected": {
            "target_entity": "ascendix__Availability__c",
            "related_entities": [
                {
                    "entity": "ascendix__Property__c",
                    "filters": [
                        {"field": "ascendix__City__c", "value": "Dallas"},
                        {"field": "ascendix__PropertySubType__c", "value": "Retail"}
                    ]
                }
            ]
        },
        "description": "Availability with Property location/type filter"
    },
    {
        "query": "what are the deals for Renaissance Tower",
        "expected": {
            "target_entity": "ascendix__Deal__c",
            "related_entities": [
                {
                    "entity": "ascendix__Property__c",
                    "filters": [
                        {"field": "Name", "value": "Renaissance Tower"}
                    ]
                }
            ]
        },
        "description": "Deals for specific property by name"
    },
    {
        "query": "leases expiring in the next 6 months",
        "expected": {
            "target_entity": "ascendix__Lease__c",
            "target_filters": [
                {"field": "ascendix__TermExpirationDate__c", "operator": "less_than"}
            ]
        },
        "description": "Temporal filter on target entity"
    },
]


def run_all_tests():
    """Run all test cases and report results."""
    print("\n" + "="*60)
    print("QUERY DECOMPOSITION POC - Running Test Suite")
    print("="*60)

    results = []
    total_time = 0

    for i, test in enumerate(TEST_CASES, 1):
        print(f"\n--- Test {i}/{len(TEST_CASES)}: {test['description']} ---")

        start = time.time()
        result = decompose_query(test['query'], verbose=True)
        elapsed = time.time() - start
        total_time += elapsed

        if 'error' not in result:
            passed = validate_decomposition(test['query'], result, test['expected'])
            results.append({
                'query': test['query'],
                'passed': passed,
                'time_ms': elapsed * 1000,
                'confidence': result.get('confidence', 0)
            })
        else:
            results.append({
                'query': test['query'],
                'passed': False,
                'time_ms': elapsed * 1000,
                'error': result.get('error')
            })

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    passed = sum(1 for r in results if r.get('passed'))
    print(f"\nResults: {passed}/{len(results)} tests passed")
    print(f"Total time: {total_time*1000:.0f}ms")
    print(f"Avg time per query: {total_time*1000/len(results):.0f}ms")

    avg_confidence = sum(r.get('confidence', 0) for r in results) / len(results)
    print(f"Avg confidence: {avg_confidence:.2f}")

    print("\nDetailed Results:")
    for r in results:
        status = "✓" if r.get('passed') else "✗"
        print(f"  {status} {r['query'][:50]}... ({r['time_ms']:.0f}ms, conf={r.get('confidence', 'N/A')})")

    return results


def main():
    if len(sys.argv) > 1:
        # Run single query from command line
        query = " ".join(sys.argv[1:])
        result = decompose_query(query)

        if 'error' not in result:
            print("\n--- How to use this decomposition ---")

            target = result.get('target_entity', 'unknown')
            related = result.get('related_entities', [])

            if related:
                rel = related[0]
                rel_entity = rel.get('entity', 'unknown')
                rel_filters = rel.get('filters', [])

                print(f"\n1. Vector search for {rel_entity} with filters:")
                for f in rel_filters:
                    print(f"   - {f.get('field')} {f.get('operator', '=')} {f.get('value')}")

                print(f"\n2. Graph traverse {rel_entity} → {target}")

                target_filters = result.get('target_filters', [])
                if target_filters:
                    print(f"\n3. Filter {target} by:")
                    for f in target_filters:
                        print(f"   - {f.get('field')} {f.get('operator', '=')} {f.get('value')}")
    else:
        # Run all test cases
        run_all_tests()


if __name__ == "__main__":
    main()
