#!/usr/bin/env python3
"""
Acceptance Test Runner for Salesforce AI Search POC

This script executes curated test queries against the /answer endpoint
and measures precision, latency, and citation accuracy.

Usage:
    python scripts/run_acceptance_tests.py --api-url https://api.example.com --api-key xxx
    python scripts/run_acceptance_tests.py --query-id Q6 --verbose
    python scripts/run_acceptance_tests.py --user-id 005xx --role SalesRep
"""

import argparse
import json
import time
import sys
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import requests
from datetime import datetime, timedelta

@dataclass
class TestQuery:
    """Represents a single test query"""
    id: str
    query: str
    expected_objects: List[str]
    expected_count_min: int
    expected_count_max: int
    filters: Optional[Dict] = None
    record_context: Optional[Dict] = None
    validation_rules: Optional[List[str]] = None

@dataclass
class TestResult:
    """Represents the result of a single test execution"""
    query_id: str
    query_text: str
    first_token_ms: float
    end_to_end_ms: float
    results_count: int
    precision_at_5: float
    citations_valid: bool
    answer_quality: str
    issues: List[str]
    precision_breakdown: List[str]
    timestamp: str

# Define curated test queries
CURATED_QUERIES = [
    TestQuery(
        id="Q1",
        query="Show me all enterprise accounts in EMEA with annual revenue over $10M",
        expected_objects=["Account"],
        expected_count_min=3,
        expected_count_max=5,
        filters={"Region": "EMEA"},
        validation_rules=["All results are Account records", "All have Region=EMEA"]
    ),
    TestQuery(
        id="Q2",
        query="What opportunities are in the proposal stage with close dates in Q1 2026?",
        expected_objects=["Opportunity"],
        expected_count_min=2,
        expected_count_max=4,
        filters={"StageName": "Proposal"},
        validation_rules=["All results are Opportunity records", "All have StageName=Proposal"]
    ),
    TestQuery(
        id="Q3",
        query="Show high priority cases opened in the last 30 days",
        expected_objects=["Case"],
        expected_count_min=1,
        expected_count_max=3,
        filters={"Priority": "High"},
        validation_rules=["All results are Case records", "All have Priority=High"]
    ),
    TestQuery(
        id="Q4",
        query="Find commercial properties in downtown with parking",
        expected_objects=["Property__c"],
        expected_count_min=1,
        expected_count_max=2,
        validation_rules=["All results are Property__c records", "All mention parking"]
    ),
    TestQuery(
        id="Q5",
        query="Which leases are expiring in the next 90 days?",
        expected_objects=["Lease__c"],
        expected_count_min=2,
        expected_count_max=3,
        validation_rules=["All results are Lease__c records", "All have End_Date__c in next 90 days"]
    ),
    TestQuery(
        id="Q6",
        query="Show open opportunities over $1M for ACME in EMEA and summarize blockers",
        expected_objects=["Opportunity", "Account"],
        expected_count_min=1,
        expected_count_max=2,
        filters={"Region": "EMEA"},
        validation_rules=[
            "Results include Opportunity records for ACME",
            "All have Amount > $1M",
            "Answer includes blocker summary"
        ]
    ),
    TestQuery(
        id="Q7",
        query="Which accounts have leases expiring next quarter with HVAC-related cases in the last 90 days?",
        expected_objects=["Account", "Lease__c", "Case"],
        expected_count_min=1,
        expected_count_max=2,
        validation_rules=[
            "Results include Account records",
            "Each account has expiring lease",
            "Each account has HVAC case"
        ]
    ),
    TestQuery(
        id="Q8",
        query="Summarize renewal risks for ACME with citations to Notes",
        expected_objects=["Account", "Note"],
        expected_count_min=2,
        expected_count_max=4,
        validation_rules=[
            "Results include Note records related to ACME",
            "Answer summarizes risks",
            "Each risk claim has citation"
        ]
    ),
    TestQuery(
        id="Q9",
        query="Show properties with active leases and maintenance contracts in the downtown area",
        expected_objects=["Property__c", "Lease__c", "Contract__c"],
        expected_count_min=1,
        expected_count_max=2,
        validation_rules=[
            "Results include Property__c records",
            "Each property has active leases",
            "Each property has maintenance contracts"
        ]
    ),
    TestQuery(
        id="Q10",
        query="What opportunities have related support cases with critical priority?",
        expected_objects=["Opportunity", "Case"],
        expected_count_min=1,
        expected_count_max=2,
        validation_rules=[
            "Results include Opportunity records",
            "Each opportunity has critical cases"
        ]
    ),
    TestQuery(
        id="Q11",
        query="Show me opportunities for XYZ Corp in Antarctica",
        expected_objects=[],
        expected_count_min=0,
        expected_count_max=0,
        validation_rules=[
            "Response indicates no results",
            "No citations provided",
            "No made-up information"
        ]
    ),
    TestQuery(
        id="Q12",
        query="Tell me about the big deal",
        expected_objects=["Opportunity"],
        expected_count_min=1,
        expected_count_max=5,
        validation_rules=["System doesn't fail", "Response is reasonable"]
    ),
]

class AcceptanceTestRunner:
    """Runs acceptance tests against the API"""
    
    def __init__(self, api_url: str, api_key: str, user_id: str = "005fk0000006rG9AAI", streaming_api_url: Optional[str] = None, verbose: bool = False):
        self.api_url = api_url.rstrip('/')
        self.streaming_api_url = (streaming_api_url or api_url).rstrip('/')
        self.api_key = api_key
        self.user_id = user_id
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'x-api-key': api_key,
            'Content-Type': 'application/json'
        })
    
    def execute_query(self, test_query: TestQuery) -> TestResult:
        """Execute a single test query and measure results"""
        if self.verbose:
            print(f"\n{'='*80}")
            print(f"Executing Query {test_query.id}: {test_query.query}")
            print(f"{'='*80}")
        
        # Prepare request
        request_body = {
            "sessionId": f"test-{test_query.id}-{int(time.time())}",
            "query": test_query.query,
            "salesforceUserId": self.user_id,
            "topK": 8,
            "policy": {
                "require_citations": True,
                "max_tokens": 600,
                "temperature": 0.3
            }
        }
        
        if test_query.filters:
            request_body["filters"] = test_query.filters
        
        if test_query.record_context:
            request_body["recordContext"] = test_query.record_context
        
        # Execute request
        start_time = time.time()
        first_token_time = None
        answer_tokens = []
        citations = []
        
        try:
            response = self.session.post(
                f"{self.streaming_api_url}/answer",
                json=request_body,
                stream=True,
                timeout=30
            )
            response.raise_for_status()
            
            # Parse SSE stream
            current_event = None
            buffer_content = ""
            
            for line in response.iter_lines():
                if not line:
                    continue
                
                line_decoded = line.decode('utf-8')
                if self.verbose:
                    print(f"DEBUG RAW LINE: {line_decoded}")
                
                # Check for buffered JSON response (Function URL fallback)
                if line_decoded.strip().startswith('{') and '"statusCode":' in line_decoded:
                    try:
                        resp_json = json.loads(line_decoded)
                        if 'body' in resp_json:
                            # Treat the body as the stream content
                            body_content = resp_json['body']
                            # The body might be newline-separated SSE events
                            for body_line in body_content.split('\n'):
                                if not body_line: continue
                                if body_line.startswith('event: '):
                                    current_event = body_line[7:].strip()
                                elif body_line.startswith('data: '):
                                    data = json.loads(body_line[6:])
                                    if current_event == 'token' and 'token' in data:
                                        if first_token_time is None: first_token_time = time.time()
                                        answer_tokens.append(data['token'])
                                    elif current_event == 'citation':
                                        citations.append(data)
                                    elif 'token' in data:
                                        if first_token_time is None: first_token_time = time.time()
                                        answer_tokens.append(data['token'])
                                    elif 'citation' in data:
                                        citations.append(data['citation'])
                            break # Stop processing main stream as we consumed the buffered body
                    except json.JSONDecodeError:
                        pass

                if line_decoded.startswith('event: '):
                    current_event = line_decoded[7:].strip()
                    continue
                
                if not line_decoded.startswith('data: '):
                    continue
                
                data = json.loads(line_decoded[6:])
                
                if current_event == 'token' and 'token' in data:
                    if first_token_time is None:
                        first_token_time = time.time()
                    answer_tokens.append(data['token'])
                
                elif current_event == 'citation':
                    citations.append(data)
                
                elif 'token' in data: # Fallback
                    if first_token_time is None:
                        first_token_time = time.time()
                    answer_tokens.append(data['token'])
                
                elif 'citation' in data: # Fallback
                    citations.append(data['citation'])
                
                if current_event == 'token' and 'token' in data:
                    if first_token_time is None:
                        first_token_time = time.time()
                    answer_tokens.append(data['token'])
                
                elif current_event == 'citation':
                    citations.append(data)
                
                elif 'token' in data: # Fallback
                    if first_token_time is None:
                        first_token_time = time.time()
                    answer_tokens.append(data['token'])
                
                elif 'citation' in data: # Fallback
                    citations.append(data['citation'])
            
            end_time = time.time()
            
            # Calculate metrics
            first_token_ms = (first_token_time - start_time) * 1000 if first_token_time else 0
            end_to_end_ms = (end_time - start_time) * 1000
            
            # Validate results
            answer_text = ''.join(answer_tokens)
            citations_valid = self._validate_citations(citations)
            precision_at_5 = self._calculate_precision(test_query, citations[:5])
            answer_quality = self._assess_answer_quality(answer_text, test_query)
            issues = self._identify_issues(test_query, citations, answer_text)
            precision_breakdown = self._get_precision_breakdown(test_query, citations[:5])
            
            if self.verbose:
                print(f"\nFirst Token: {first_token_ms:.0f}ms")
                print(f"End-to-End: {end_to_end_ms:.0f}ms")
                print(f"Results: {len(citations)}")
                print(f"Precision@5: {precision_at_5:.1%}")
                print(f"Citations Valid: {citations_valid}")
                print(f"Answer Quality: {answer_quality}")
                if issues:
                    print(f"Issues: {', '.join(issues)}")
                print(f"\nAnswer:\n{answer_text[:200]}...")
            
            return TestResult(
                query_id=test_query.id,
                query_text=test_query.query,
                first_token_ms=first_token_ms,
                end_to_end_ms=end_to_end_ms,
                results_count=len(citations),
                precision_at_5=precision_at_5,
                citations_valid=citations_valid,
                answer_quality=answer_quality,
                issues=issues,
                precision_breakdown=precision_breakdown,
                timestamp=datetime.now().isoformat()
            )
            
        except Exception as e:
            print(f"ERROR executing query {test_query.id}: {str(e)}")
            return TestResult(
                query_id=test_query.id,
                query_text=test_query.query,
                first_token_ms=0,
                end_to_end_ms=0,
                results_count=0,
                precision_at_5=0.0,
                citations_valid=False,
                answer_quality="Error",
                issues=[str(e)],
                precision_breakdown=[],
                timestamp=datetime.now().isoformat()
            )
    
    def _validate_citations(self, citations: List[Dict]) -> bool:
        """Validate that all citations have required fields"""
        if not citations:
            return True
        
        for citation in citations:
            if 'id' not in citation or 'text' not in citation:
                return False
        
        return True
    
    def _calculate_precision(self, test_query: TestQuery, top_5_citations: List[Dict]) -> float:
        """Calculate precision@5 based on expected objects"""
        if not top_5_citations:
            return 0.0 if test_query.expected_count_min > 0 else 1.0
        
        relevant_count = 0
        for citation in top_5_citations:
            citation_id = citation.get('id', '')
            # Check if citation matches expected object types
            for expected_obj in test_query.expected_objects:
                if citation_id.startswith(expected_obj):
                    relevant_count += 1
                    break
        
        return relevant_count / min(5, len(top_5_citations))
    
    def _assess_answer_quality(self, answer: str, test_query: TestQuery) -> str:
        """Assess answer quality based on content"""
        if not answer:
            return "Poor"
        
        # Check for key indicators
        has_citations = '[Source:' in answer
        has_content = len(answer) > 50
        no_errors = 'error' not in answer.lower() and 'sorry' not in answer.lower()
        
        if has_citations and has_content and no_errors:
            return "Good"
        elif has_content:
            return "Fair"
        else:
            return "Poor"
    
    def _identify_issues(self, test_query: TestQuery, citations: List[Dict], answer: str) -> List[str]:
        """Identify any issues with the response"""
        issues = []
        
        # Check result count
        if len(citations) < test_query.expected_count_min:
            issues.append(f"Too few results: {len(citations)} < {test_query.expected_count_min}")
        elif len(citations) > test_query.expected_count_max:
            issues.append(f"Too many results: {len(citations)} > {test_query.expected_count_max}")
        
        # Check for citations in answer
        if citations and '[Source:' not in answer:
            issues.append("Answer missing citation markers")
        
        # Check for empty answer
        if not answer or len(answer) < 20:
            issues.append("Answer too short or empty")
        
        return issues
    
    def _get_precision_breakdown(self, test_query: TestQuery, top_5_citations: List[Dict]) -> List[str]:
        """Get detailed precision breakdown for top 5 results"""
        breakdown = []
        
        for i, citation in enumerate(top_5_citations, 1):
            citation_id = citation.get('id', 'Unknown')
            is_relevant = any(citation_id.startswith(obj) for obj in test_query.expected_objects)
            relevance = "Relevant" if is_relevant else "Not Relevant"
            breakdown.append(f"{i}. {citation_id}: {relevance}")
        
        return breakdown
    
    def run_all_tests(self, query_ids: Optional[List[str]] = None) -> List[TestResult]:
        """Run all or specified test queries"""
        queries_to_run = CURATED_QUERIES
        
        if query_ids:
            queries_to_run = [q for q in CURATED_QUERIES if q.id in query_ids]
        
        results = []
        for query in queries_to_run:
            result = self.execute_query(query)
            results.append(result)
            time.sleep(1)  # Rate limiting
        
        return results
    
    def generate_report(self, results: List[TestResult]) -> Dict:
        """Generate summary report from test results"""
        if not results:
            return {}
        
        # Calculate aggregate metrics
        total_queries = len(results)
        avg_first_token = sum(r.first_token_ms for r in results) / total_queries
        avg_end_to_end = sum(r.end_to_end_ms for r in results) / total_queries
        avg_precision = sum(r.precision_at_5 for r in results) / total_queries
        
        # Calculate p95 latencies
        first_token_times = sorted(r.first_token_ms for r in results)
        end_to_end_times = sorted(r.end_to_end_ms for r in results)
        p95_index = int(len(results) * 0.95)
        p95_first_token = first_token_times[p95_index] if p95_index < len(first_token_times) else first_token_times[-1]
        p95_end_to_end = end_to_end_times[p95_index] if p95_index < len(end_to_end_times) else end_to_end_times[-1]
        
        # Count issues
        total_issues = sum(len(r.issues) for r in results)
        queries_with_issues = sum(1 for r in results if r.issues)
        
        # Pass/fail criteria
        precision_pass = avg_precision >= 0.70
        first_token_pass = p95_first_token <= 800
        end_to_end_pass = p95_end_to_end <= 4000
        
        return {
            "summary": {
                "total_queries": total_queries,
                "timestamp": datetime.now().isoformat(),
                "pass": precision_pass and first_token_pass and end_to_end_pass
            },
            "metrics": {
                "avg_first_token_ms": round(avg_first_token, 2),
                "avg_end_to_end_ms": round(avg_end_to_end, 2),
                "p95_first_token_ms": round(p95_first_token, 2),
                "p95_end_to_end_ms": round(p95_end_to_end, 2),
                "avg_precision_at_5": round(avg_precision, 3),
                "total_issues": total_issues,
                "queries_with_issues": queries_with_issues
            },
            "targets": {
                "precision_at_5": {"target": 0.70, "actual": round(avg_precision, 3), "pass": precision_pass},
                "p95_first_token_ms": {"target": 800, "actual": round(p95_first_token, 2), "pass": first_token_pass},
                "p95_end_to_end_ms": {"target": 4000, "actual": round(p95_end_to_end, 2), "pass": end_to_end_pass}
            },
            "results": [asdict(r) for r in results]
        }

def main():
    parser = argparse.ArgumentParser(description='Run acceptance tests for Salesforce AI Search POC')
    parser.add_argument('--api-url', required=True, help='API Gateway URL for non-streaming endpoints (e.g., /retrieve).')
    parser.add_argument('--api-key', required=True, help='API key for authentication')
    parser.add_argument('--user-id', default='005fk0000006rG9AAI', help='Salesforce User ID for testing')
    parser.add_argument('--streaming-api-url', help='Optional: Dedicated URL for streaming endpoints (e.g., Lambda Function URL for /answer). Defaults to --api-url if not provided.')
    parser.add_argument('--query-id', help='Run specific query by ID (e.g., Q6)')
    parser.add_argument('--output', default='results/acceptance_test_results.json', help='Output file for results')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    # Create runner
    runner = AcceptanceTestRunner(
        api_url=args.api_url,
        api_key=args.api_key,
        user_id=args.user_id,
        streaming_api_url=args.streaming_api_url,
        verbose=args.verbose
    )
    
    # Run tests
    query_ids = [args.query_id] if args.query_id else None
    results = runner.run_all_tests(query_ids)
    
    # Generate report
    report = runner.generate_report(results)
    
    # Save results
    import os
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Print summary
    print(f"\n{'='*80}")
    print("ACCEPTANCE TEST SUMMARY")
    print(f"{'='*80}")
    print(f"Total Queries: {report['summary']['total_queries']}")
    print(f"Average Precision@5: {report['metrics']['avg_precision_at_5']:.1%} (target: ≥70%)")
    print(f"P95 First Token: {report['metrics']['p95_first_token_ms']:.0f}ms (target: ≤800ms)")
    print(f"P95 End-to-End: {report['metrics']['p95_end_to_end_ms']:.0f}ms (target: ≤4000ms)")
    print(f"\nTarget Achievement:")
    print(f"  Precision@5: {'✓ PASS' if report['targets']['precision_at_5']['pass'] else '✗ FAIL'}")
    print(f"  First Token Latency: {'✓ PASS' if report['targets']['p95_first_token_ms']['pass'] else '✗ FAIL'}")
    print(f"  End-to-End Latency: {'✓ PASS' if report['targets']['p95_end_to_end_ms']['pass'] else '✗ FAIL'}")
    print(f"\nOverall: {'✓ PASS' if report['summary']['pass'] else '✗ FAIL'}")
    print(f"\nResults saved to: {args.output}")
    
    # Exit with appropriate code
    sys.exit(0 if report['summary']['pass'] else 1)

if __name__ == '__main__':
    main()
