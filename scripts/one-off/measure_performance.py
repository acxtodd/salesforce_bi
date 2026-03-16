#!/usr/bin/env python3
"""
Performance Measurement Script

This script measures system performance against defined targets:
- p95 first token latency: ≤800ms
- p95 end-to-end latency: ≤4.0s
- CDC freshness lag P50: ≤5 min

Usage:
    python scripts/measure_performance.py --api-url https://api.example.com --api-key xxx
    python scripts/measure_performance.py --iterations 100 --concurrent 10
    python scripts/measure_performance.py --measure-cdc --salesforce-url https://instance.salesforce.com
"""

import argparse
import json
import sys
import time
import statistics
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

@dataclass
class PerformanceMetrics:
    """Performance metrics for a single request"""
    request_id: str
    query: str
    first_token_ms: float
    end_to_end_ms: float
    tokens_generated: int
    citations_count: int
    success: bool
    error: Optional[str]
    timestamp: str

@dataclass
class CDCFreshnessMetrics:
    """CDC freshness metrics"""
    record_id: str
    sobject: str
    modified_time: str
    indexed_time: str
    lag_seconds: float
    lag_minutes: float

class PerformanceTester:
    """Measures system performance"""
    
    def __init__(self, api_url: str, api_key: str, user_id: str = "005xx", verbose: bool = False):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.user_id = user_id
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'x-api-key': api_key,
            'Content-Type': 'application/json'
        })
    
    # Test queries with varying complexity
    TEST_QUERIES = [
        "Show me all opportunities in EMEA",
        "What are the top accounts by revenue?",
        "Show high priority cases opened this week",
        "Find properties with active leases",
        "Summarize renewal risks for ACME with citations",
        "Which accounts have leases expiring next quarter?",
        "Show opportunities over $1M in the proposal stage",
        "What changed in the last week for enterprise accounts?",
    ]
    
    def measure_single_request(self, query: str, request_num: int) -> PerformanceMetrics:
        """Measure performance of a single request"""
        request_id = f"perf-test-{request_num}-{int(time.time())}"
        
        request_body = {
            "sessionId": request_id,
            "query": query,
            "salesforceUserId": self.user_id,
            "topK": 8,
            "policy": {
                "require_citations": True,
                "max_tokens": 600,
                "temperature": 0.3
            }
        }
        
        start_time = time.time()
        first_token_time = None
        token_count = 0
        citations_count = 0
        error = None
        
        try:
            response = self.session.post(
                f"{self.api_url}/answer",
                json=request_body,
                stream=True,
                timeout=30
            )
            response.raise_for_status()
            
            # Parse SSE stream
            for line in response.iter_lines():
                if not line:
                    continue
                
                line = line.decode('utf-8')
                if not line.startswith('data: '):
                    continue
                
                data = json.loads(line[6:])
                
                if 'token' in data:
                    if first_token_time is None:
                        first_token_time = time.time()
                    token_count += 1
                
                elif 'citation' in data:
                    citations_count += 1
            
            end_time = time.time()
            
            first_token_ms = (first_token_time - start_time) * 1000 if first_token_time else 0
            end_to_end_ms = (end_time - start_time) * 1000
            success = True
            
        except Exception as e:
            end_time = time.time()
            first_token_ms = 0
            end_to_end_ms = (end_time - start_time) * 1000
            success = False
            error = str(e)
        
        return PerformanceMetrics(
            request_id=request_id,
            query=query,
            first_token_ms=first_token_ms,
            end_to_end_ms=end_to_end_ms,
            tokens_generated=token_count,
            citations_count=citations_count,
            success=success,
            error=error,
            timestamp=datetime.now().isoformat()
        )
    
    def run_sequential_test(self, iterations: int) -> List[PerformanceMetrics]:
        """Run sequential performance test"""
        results = []
        
        for i in range(iterations):
            query = self.TEST_QUERIES[i % len(self.TEST_QUERIES)]
            
            if self.verbose:
                print(f"Request {i+1}/{iterations}: {query[:50]}...")
            
            result = self.measure_single_request(query, i)
            results.append(result)
            
            if self.verbose:
                status = "✓" if result.success else "✗"
                print(f"  {status} First Token: {result.first_token_ms:.0f}ms | "
                      f"End-to-End: {result.end_to_end_ms:.0f}ms")
            
            time.sleep(0.5)  # Small delay between requests
        
        return results
    
    def run_concurrent_test(self, iterations: int, concurrency: int) -> List[PerformanceMetrics]:
        """Run concurrent performance test"""
        results = []
        
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = []
            
            for i in range(iterations):
                query = self.TEST_QUERIES[i % len(self.TEST_QUERIES)]
                future = executor.submit(self.measure_single_request, query, i)
                futures.append(future)
            
            for i, future in enumerate(as_completed(futures), 1):
                result = future.result()
                results.append(result)
                
                if self.verbose:
                    status = "✓" if result.success else "✗"
                    print(f"Completed {i}/{iterations}: {status} "
                          f"First Token: {result.first_token_ms:.0f}ms | "
                          f"End-to-End: {result.end_to_end_ms:.0f}ms")
        
        return results
    
    def calculate_statistics(self, results: List[PerformanceMetrics]) -> Dict:
        """Calculate performance statistics"""
        successful_results = [r for r in results if r.success]
        
        if not successful_results:
            return {
                "error": "No successful requests",
                "total_requests": len(results),
                "successful_requests": 0
            }
        
        first_token_times = [r.first_token_ms for r in successful_results]
        end_to_end_times = [r.end_to_end_ms for r in successful_results]
        
        # Sort for percentile calculations
        first_token_sorted = sorted(first_token_times)
        end_to_end_sorted = sorted(end_to_end_times)
        
        # Calculate percentiles
        def percentile(data: List[float], p: float) -> float:
            index = int(len(data) * p)
            return data[min(index, len(data) - 1)]
        
        p50_first_token = percentile(first_token_sorted, 0.50)
        p95_first_token = percentile(first_token_sorted, 0.95)
        p99_first_token = percentile(first_token_sorted, 0.99)
        
        p50_end_to_end = percentile(end_to_end_sorted, 0.50)
        p95_end_to_end = percentile(end_to_end_sorted, 0.95)
        p99_end_to_end = percentile(end_to_end_sorted, 0.99)
        
        # Check targets
        first_token_target_met = p95_first_token <= 800
        end_to_end_target_met = p95_end_to_end <= 4000
        
        return {
            "total_requests": len(results),
            "successful_requests": len(successful_results),
            "failed_requests": len(results) - len(successful_results),
            "success_rate": len(successful_results) / len(results),
            "first_token_latency": {
                "mean": statistics.mean(first_token_times),
                "median": statistics.median(first_token_times),
                "p50": p50_first_token,
                "p95": p95_first_token,
                "p99": p99_first_token,
                "min": min(first_token_times),
                "max": max(first_token_times),
                "target": 800,
                "target_met": first_token_target_met
            },
            "end_to_end_latency": {
                "mean": statistics.mean(end_to_end_times),
                "median": statistics.median(end_to_end_times),
                "p50": p50_end_to_end,
                "p95": p95_end_to_end,
                "p99": p99_end_to_end,
                "min": min(end_to_end_times),
                "max": max(end_to_end_times),
                "target": 4000,
                "target_met": end_to_end_target_met
            },
            "tokens_per_request": {
                "mean": statistics.mean(r.tokens_generated for r in successful_results),
                "median": statistics.median(r.tokens_generated for r in successful_results)
            },
            "citations_per_request": {
                "mean": statistics.mean(r.citations_count for r in successful_results),
                "median": statistics.median(r.citations_count for r in successful_results)
            }
        }

class CDCFreshnessTester:
    """Measures CDC freshness lag"""
    
    def __init__(self, salesforce_url: str, salesforce_token: str, 
                 api_url: str, api_key: str, verbose: bool = False):
        self.salesforce_url = salesforce_url.rstrip('/')
        self.salesforce_token = salesforce_token
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.verbose = verbose
    
    def measure_cdc_lag(self, record_id: str, sobject: str) -> Optional[CDCFreshnessMetrics]:
        """Measure CDC lag for a specific record"""
        # Get record's last modified time from Salesforce
        sf_headers = {
            'Authorization': f'Bearer {self.salesforce_token}',
            'Content-Type': 'application/json'
        }
        
        try:
            # Query Salesforce for LastModifiedDate
            query = f"SELECT Id, LastModifiedDate FROM {sobject} WHERE Id = '{record_id}'"
            sf_response = requests.get(
                f"{self.salesforce_url}/services/data/v58.0/query",
                headers=sf_headers,
                params={'q': query}
            )
            sf_response.raise_for_status()
            
            sf_data = sf_response.json()
            if not sf_data.get('records'):
                return None
            
            modified_time_str = sf_data['records'][0]['LastModifiedDate']
            modified_time = datetime.fromisoformat(modified_time_str.replace('Z', '+00:00'))
            
            # Query search index to see if record is indexed
            search_headers = {
                'x-api-key': self.api_key,
                'Content-Type': 'application/json'
            }
            
            search_body = {
                "query": f"recordId:{record_id}",
                "salesforceUserId": "005xx",
                "topK": 1
            }
            
            search_response = requests.post(
                f"{self.api_url}/retrieve",
                headers=search_headers,
                json=search_body
            )
            search_response.raise_for_status()
            
            search_data = search_response.json()
            
            if not search_data.get('matches'):
                # Record not yet indexed
                return None
            
            # Get indexed time from metadata
            indexed_time_str = search_data['matches'][0]['metadata'].get('lastModified')
            if not indexed_time_str:
                return None
            
            indexed_time = datetime.fromisoformat(indexed_time_str.replace('Z', '+00:00'))
            
            # Calculate lag
            lag = (indexed_time - modified_time).total_seconds()
            
            return CDCFreshnessMetrics(
                record_id=record_id,
                sobject=sobject,
                modified_time=modified_time_str,
                indexed_time=indexed_time_str,
                lag_seconds=lag,
                lag_minutes=lag / 60
            )
            
        except Exception as e:
            if self.verbose:
                print(f"Error measuring CDC lag for {record_id}: {e}")
            return None
    
    def measure_multiple_records(self, records: List[Tuple[str, str]]) -> List[CDCFreshnessMetrics]:
        """Measure CDC lag for multiple records"""
        results = []
        
        for record_id, sobject in records:
            if self.verbose:
                print(f"Measuring CDC lag for {sobject}/{record_id}...")
            
            result = self.measure_cdc_lag(record_id, sobject)
            if result:
                results.append(result)
                
                if self.verbose:
                    print(f"  Lag: {result.lag_minutes:.2f} minutes")
        
        return results
    
    def calculate_cdc_statistics(self, results: List[CDCFreshnessMetrics]) -> Dict:
        """Calculate CDC freshness statistics"""
        if not results:
            return {"error": "No CDC measurements"}
        
        lag_minutes = [r.lag_minutes for r in results]
        lag_sorted = sorted(lag_minutes)
        
        def percentile(data: List[float], p: float) -> float:
            index = int(len(data) * p)
            return data[min(index, len(data) - 1)]
        
        p50_lag = percentile(lag_sorted, 0.50)
        p95_lag = percentile(lag_sorted, 0.95)
        
        target_met = p50_lag <= 5.0  # 5 minutes
        
        return {
            "total_measurements": len(results),
            "lag_minutes": {
                "mean": statistics.mean(lag_minutes),
                "median": statistics.median(lag_minutes),
                "p50": p50_lag,
                "p95": p95_lag,
                "min": min(lag_minutes),
                "max": max(lag_minutes),
                "target": 5.0,
                "target_met": target_met
            }
        }

def main():
    parser = argparse.ArgumentParser(description='Measure system performance against targets')
    parser.add_argument('--api-url', required=True, help='API Gateway URL')
    parser.add_argument('--api-key', required=True, help='API key for authentication')
    parser.add_argument('--user-id', default='005xx', help='Salesforce User ID')
    parser.add_argument('--iterations', type=int, default=50, help='Number of test iterations')
    parser.add_argument('--concurrent', type=int, default=1, help='Concurrent requests (1=sequential)')
    parser.add_argument('--measure-cdc', action='store_true', help='Measure CDC freshness lag')
    parser.add_argument('--salesforce-url', help='Salesforce instance URL (for CDC measurement)')
    parser.add_argument('--salesforce-token', help='Salesforce access token (for CDC measurement)')
    parser.add_argument('--cdc-records', help='Comma-separated record IDs for CDC measurement')
    parser.add_argument('--output', default='results/performance_metrics.json', help='Output file')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    # Run latency tests
    print(f"\n{'='*80}")
    print("PERFORMANCE TESTING")
    print(f"{'='*80}")
    print(f"Iterations: {args.iterations}")
    print(f"Concurrency: {args.concurrent}")
    
    tester = PerformanceTester(
        api_url=args.api_url,
        api_key=args.api_key,
        user_id=args.user_id,
        verbose=args.verbose
    )
    
    if args.concurrent > 1:
        print(f"\nRunning concurrent test with {args.concurrent} workers...")
        results = tester.run_concurrent_test(args.iterations, args.concurrent)
    else:
        print("\nRunning sequential test...")
        results = tester.run_sequential_test(args.iterations)
    
    stats = tester.calculate_statistics(results)
    
    # Measure CDC freshness if requested
    cdc_stats = None
    if args.measure_cdc:
        if not args.salesforce_url or not args.salesforce_token:
            print("\nERROR: --salesforce-url and --salesforce-token required for CDC measurement")
        else:
            print(f"\n{'='*80}")
            print("CDC FRESHNESS TESTING")
            print(f"{'='*80}")
            
            cdc_tester = CDCFreshnessTester(
                salesforce_url=args.salesforce_url,
                salesforce_token=args.salesforce_token,
                api_url=args.api_url,
                api_key=args.api_key,
                verbose=args.verbose
            )
            
            # Parse record IDs
            if args.cdc_records:
                records = []
                for record_spec in args.cdc_records.split(','):
                    parts = record_spec.split('/')
                    if len(parts) == 2:
                        records.append((parts[1], parts[0]))
                
                cdc_results = cdc_tester.measure_multiple_records(records)
                cdc_stats = cdc_tester.calculate_cdc_statistics(cdc_results)
    
    # Print summary
    print(f"\n{'='*80}")
    print("PERFORMANCE SUMMARY")
    print(f"{'='*80}")
    print(f"Total Requests: {stats['total_requests']}")
    print(f"Successful: {stats['successful_requests']} ({stats['success_rate']:.1%})")
    print(f"Failed: {stats['failed_requests']}")
    
    print(f"\nFirst Token Latency:")
    print(f"  Mean: {stats['first_token_latency']['mean']:.0f}ms")
    print(f"  P50: {stats['first_token_latency']['p50']:.0f}ms")
    print(f"  P95: {stats['first_token_latency']['p95']:.0f}ms (target: ≤800ms)")
    print(f"  P99: {stats['first_token_latency']['p99']:.0f}ms")
    print(f"  Target Met: {'✓ PASS' if stats['first_token_latency']['target_met'] else '✗ FAIL'}")
    
    print(f"\nEnd-to-End Latency:")
    print(f"  Mean: {stats['end_to_end_latency']['mean']:.0f}ms")
    print(f"  P50: {stats['end_to_end_latency']['p50']:.0f}ms")
    print(f"  P95: {stats['end_to_end_latency']['p95']:.0f}ms (target: ≤4000ms)")
    print(f"  P99: {stats['end_to_end_latency']['p99']:.0f}ms")
    print(f"  Target Met: {'✓ PASS' if stats['end_to_end_latency']['target_met'] else '✗ FAIL'}")
    
    if cdc_stats:
        print(f"\nCDC Freshness Lag:")
        print(f"  Mean: {cdc_stats['lag_minutes']['mean']:.2f} minutes")
        print(f"  P50: {cdc_stats['lag_minutes']['p50']:.2f} minutes (target: ≤5 min)")
        print(f"  P95: {cdc_stats['lag_minutes']['p95']:.2f} minutes")
        print(f"  Target Met: {'✓ PASS' if cdc_stats['lag_minutes']['target_met'] else '✗ FAIL'}")
    
    # Overall pass/fail
    all_targets_met = (
        stats['first_token_latency']['target_met'] and
        stats['end_to_end_latency']['target_met'] and
        (not cdc_stats or cdc_stats['lag_minutes']['target_met'])
    )
    
    print(f"\nOverall: {'✓ ALL TARGETS MET' if all_targets_met else '✗ SOME TARGETS MISSED'}")
    
    # Save results
    import os
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    output_data = {
        "latency_statistics": stats,
        "cdc_statistics": cdc_stats,
        "all_targets_met": all_targets_met,
        "timestamp": datetime.now().isoformat()
    }
    
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nResults saved to: {args.output}")
    
    sys.exit(0 if all_targets_met else 1)

if __name__ == '__main__':
    main()
