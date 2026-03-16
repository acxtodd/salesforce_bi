#!/usr/bin/env python3
"""
Precision and Recall Evaluation Script

This script evaluates retrieval quality by measuring precision@K and recall
for the curated test set. It compares retrieved results against ground truth
relevance judgments.

Usage:
    python scripts/evaluate_precision_recall.py --results results/acceptance_test_results.json
    python scripts/evaluate_precision_recall.py --ground-truth data/ground_truth.json --results results/acceptance_test_results.json
"""

import argparse
import json
import sys
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass
from collections import defaultdict
import statistics

@dataclass
class RelevanceJudgment:
    """Ground truth relevance judgment for a query-document pair"""
    query_id: str
    document_id: str
    relevance: int  # 0=not relevant, 1=partially relevant, 2=highly relevant

@dataclass
class EvaluationMetrics:
    """Evaluation metrics for a single query"""
    query_id: str
    precision_at_1: float
    precision_at_3: float
    precision_at_5: float
    precision_at_10: float
    recall_at_5: float
    recall_at_10: float
    ndcg_at_5: float
    ndcg_at_10: float
    mean_reciprocal_rank: float
    relevant_retrieved: int
    total_relevant: int
    total_retrieved: int

class PrecisionRecallEvaluator:
    """Evaluates precision and recall metrics"""
    
    def __init__(self, ground_truth: Dict[str, List[RelevanceJudgment]]):
        """
        Initialize evaluator with ground truth relevance judgments
        
        Args:
            ground_truth: Dict mapping query_id to list of relevance judgments
        """
        self.ground_truth = ground_truth
    
    def evaluate_query(self, query_id: str, retrieved_docs: List[str]) -> EvaluationMetrics:
        """
        Evaluate a single query's results
        
        Args:
            query_id: Query identifier
            retrieved_docs: List of retrieved document IDs in rank order
            
        Returns:
            EvaluationMetrics for this query
        """
        # Get ground truth for this query
        gt_judgments = self.ground_truth.get(query_id, [])
        relevant_docs = {j.document_id: j.relevance for j in gt_judgments if j.relevance > 0}
        
        if not relevant_docs:
            # No ground truth available
            return EvaluationMetrics(
                query_id=query_id,
                precision_at_1=0.0,
                precision_at_3=0.0,
                precision_at_5=0.0,
                precision_at_10=0.0,
                recall_at_5=0.0,
                recall_at_10=0.0,
                ndcg_at_5=0.0,
                ndcg_at_10=0.0,
                mean_reciprocal_rank=0.0,
                relevant_retrieved=0,
                total_relevant=0,
                total_retrieved=len(retrieved_docs)
            )
        
        # Calculate metrics
        p_at_1 = self._precision_at_k(retrieved_docs, relevant_docs, 1)
        p_at_3 = self._precision_at_k(retrieved_docs, relevant_docs, 3)
        p_at_5 = self._precision_at_k(retrieved_docs, relevant_docs, 5)
        p_at_10 = self._precision_at_k(retrieved_docs, relevant_docs, 10)
        
        r_at_5 = self._recall_at_k(retrieved_docs, relevant_docs, 5)
        r_at_10 = self._recall_at_k(retrieved_docs, relevant_docs, 10)
        
        ndcg_5 = self._ndcg_at_k(retrieved_docs, relevant_docs, 5)
        ndcg_10 = self._ndcg_at_k(retrieved_docs, relevant_docs, 10)
        
        mrr = self._mean_reciprocal_rank(retrieved_docs, relevant_docs)
        
        relevant_retrieved = sum(1 for doc in retrieved_docs if doc in relevant_docs)
        
        return EvaluationMetrics(
            query_id=query_id,
            precision_at_1=p_at_1,
            precision_at_3=p_at_3,
            precision_at_5=p_at_5,
            precision_at_10=p_at_10,
            recall_at_5=r_at_5,
            recall_at_10=r_at_10,
            ndcg_at_5=ndcg_5,
            ndcg_at_10=ndcg_10,
            mean_reciprocal_rank=mrr,
            relevant_retrieved=relevant_retrieved,
            total_relevant=len(relevant_docs),
            total_retrieved=len(retrieved_docs)
        )
    
    def _precision_at_k(self, retrieved: List[str], relevant: Dict[str, int], k: int) -> float:
        """Calculate precision@k"""
        if not retrieved or k == 0:
            return 0.0
        
        top_k = retrieved[:k]
        relevant_count = sum(1 for doc in top_k if doc in relevant)
        
        return relevant_count / len(top_k)
    
    def _recall_at_k(self, retrieved: List[str], relevant: Dict[str, int], k: int) -> float:
        """Calculate recall@k"""
        if not relevant:
            return 0.0
        
        top_k = retrieved[:k]
        relevant_count = sum(1 for doc in top_k if doc in relevant)
        
        return relevant_count / len(relevant)
    
    def _ndcg_at_k(self, retrieved: List[str], relevant: Dict[str, int], k: int) -> float:
        """Calculate Normalized Discounted Cumulative Gain@k"""
        if not retrieved or not relevant:
            return 0.0
        
        # Calculate DCG
        dcg = 0.0
        for i, doc in enumerate(retrieved[:k], 1):
            rel = relevant.get(doc, 0)
            dcg += (2 ** rel - 1) / (self._log2(i + 1))
        
        # Calculate IDCG (ideal DCG)
        ideal_rels = sorted(relevant.values(), reverse=True)[:k]
        idcg = sum((2 ** rel - 1) / self._log2(i + 2) for i, rel in enumerate(ideal_rels))
        
        return dcg / idcg if idcg > 0 else 0.0
    
    def _mean_reciprocal_rank(self, retrieved: List[str], relevant: Dict[str, int]) -> float:
        """Calculate Mean Reciprocal Rank"""
        for i, doc in enumerate(retrieved, 1):
            if doc in relevant:
                return 1.0 / i
        return 0.0
    
    @staticmethod
    def _log2(x: float) -> float:
        """Calculate log base 2"""
        import math
        return math.log2(x) if x > 0 else 0.0
    
    def evaluate_all(self, results: Dict[str, List[str]]) -> List[EvaluationMetrics]:
        """
        Evaluate all queries
        
        Args:
            results: Dict mapping query_id to list of retrieved document IDs
            
        Returns:
            List of EvaluationMetrics for all queries
        """
        metrics = []
        for query_id, retrieved_docs in results.items():
            metric = self.evaluate_query(query_id, retrieved_docs)
            metrics.append(metric)
        return metrics
    
    def aggregate_metrics(self, metrics: List[EvaluationMetrics]) -> Dict:
        """Calculate aggregate metrics across all queries"""
        if not metrics:
            return {}
        
        return {
            "mean_precision_at_1": statistics.mean(m.precision_at_1 for m in metrics),
            "mean_precision_at_3": statistics.mean(m.precision_at_3 for m in metrics),
            "mean_precision_at_5": statistics.mean(m.precision_at_5 for m in metrics),
            "mean_precision_at_10": statistics.mean(m.precision_at_10 for m in metrics),
            "mean_recall_at_5": statistics.mean(m.recall_at_5 for m in metrics),
            "mean_recall_at_10": statistics.mean(m.recall_at_10 for m in metrics),
            "mean_ndcg_at_5": statistics.mean(m.ndcg_at_5 for m in metrics),
            "mean_ndcg_at_10": statistics.mean(m.ndcg_at_10 for m in metrics),
            "mean_mrr": statistics.mean(m.mean_reciprocal_rank for m in metrics),
            "total_queries": len(metrics),
            "queries_with_results": sum(1 for m in metrics if m.total_retrieved > 0),
            "avg_relevant_retrieved": statistics.mean(m.relevant_retrieved for m in metrics),
            "avg_total_relevant": statistics.mean(m.total_relevant for m in metrics)
        }

def load_ground_truth(filepath: str) -> Dict[str, List[RelevanceJudgment]]:
    """Load ground truth relevance judgments from JSON file"""
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    ground_truth = defaultdict(list)
    for item in data:
        judgment = RelevanceJudgment(
            query_id=item['query_id'],
            document_id=item['document_id'],
            relevance=item['relevance']
        )
        ground_truth[judgment.query_id].append(judgment)
    
    return dict(ground_truth)

def load_test_results(filepath: str) -> Dict[str, List[str]]:
    """Load test results from acceptance test output"""
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    results = {}
    for result in data.get('results', []):
        query_id = result['query_id']
        # Extract document IDs from precision breakdown
        doc_ids = []
        for breakdown in result.get('precision_breakdown', []):
            # Format: "1. Opportunity/006xx1: Relevant"
            parts = breakdown.split(': ')
            if len(parts) >= 2:
                doc_id = parts[0].split('. ', 1)[1] if '. ' in parts[0] else parts[0]
                doc_ids.append(doc_id)
        results[query_id] = doc_ids
    
    return results

def create_default_ground_truth() -> Dict[str, List[RelevanceJudgment]]:
    """Create default ground truth based on expected object types"""
    ground_truth = defaultdict(list)
    
    # Q1: Account search
    ground_truth['Q1'] = [
        RelevanceJudgment('Q1', 'Account/001xx1', 2),
        RelevanceJudgment('Q1', 'Account/001xx2', 2),
        RelevanceJudgment('Q1', 'Account/001xx3', 2),
    ]
    
    # Q2: Opportunity search
    ground_truth['Q2'] = [
        RelevanceJudgment('Q2', 'Opportunity/006xx1', 2),
        RelevanceJudgment('Q2', 'Opportunity/006xx2', 2),
    ]
    
    # Q3: Case search
    ground_truth['Q3'] = [
        RelevanceJudgment('Q3', 'Case/500xx1', 2),
        RelevanceJudgment('Q3', 'Case/500xx2', 2),
    ]
    
    # Q4: Property search
    ground_truth['Q4'] = [
        RelevanceJudgment('Q4', 'Property__c/a00xx1', 2),
    ]
    
    # Q5: Lease search
    ground_truth['Q5'] = [
        RelevanceJudgment('Q5', 'Lease__c/a01xx1', 2),
        RelevanceJudgment('Q5', 'Lease__c/a01xx2', 2),
    ]
    
    # Q6: Multi-object (ACME opportunities)
    ground_truth['Q6'] = [
        RelevanceJudgment('Q6', 'Opportunity/006xx1', 2),
        RelevanceJudgment('Q6', 'Opportunity/006xx2', 2),
        RelevanceJudgment('Q6', 'Account/001xx1', 1),  # Context
    ]
    
    # Q7: Multi-object (Accounts with leases and cases)
    ground_truth['Q7'] = [
        RelevanceJudgment('Q7', 'Account/001xx1', 2),
        RelevanceJudgment('Q7', 'Lease__c/a01xx1', 2),
        RelevanceJudgment('Q7', 'Case/500xx1', 2),
    ]
    
    # Q8: ACME notes
    ground_truth['Q8'] = [
        RelevanceJudgment('Q8', 'Note/002xx1', 2),
        RelevanceJudgment('Q8', 'Note/002xx2', 2),
        RelevanceJudgment('Q8', 'Note/002xx3', 2),
    ]
    
    # Q9: Properties with leases and contracts
    ground_truth['Q9'] = [
        RelevanceJudgment('Q9', 'Property__c/a00xx1', 2),
        RelevanceJudgment('Q9', 'Lease__c/a01xx1', 1),
        RelevanceJudgment('Q9', 'Contract__c/a02xx1', 1),
    ]
    
    # Q10: Opportunities with critical cases
    ground_truth['Q10'] = [
        RelevanceJudgment('Q10', 'Opportunity/006xx1', 2),
        RelevanceJudgment('Q10', 'Case/500xx1', 2),
    ]
    
    # Q11: No results query
    ground_truth['Q11'] = []  # No relevant documents
    
    # Q12: Ambiguous query
    ground_truth['Q12'] = [
        RelevanceJudgment('Q12', 'Opportunity/006xx1', 1),
        RelevanceJudgment('Q12', 'Opportunity/006xx2', 1),
    ]
    
    return dict(ground_truth)

def main():
    parser = argparse.ArgumentParser(description='Evaluate precision and recall for acceptance tests')
    parser.add_argument('--results', required=True, help='Path to acceptance test results JSON')
    parser.add_argument('--ground-truth', help='Path to ground truth relevance judgments JSON')
    parser.add_argument('--output', default='results/precision_recall_evaluation.json', help='Output file')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    # Load ground truth
    if args.ground_truth:
        ground_truth = load_ground_truth(args.ground_truth)
    else:
        print("No ground truth file provided, using default ground truth")
        ground_truth = create_default_ground_truth()
    
    # Load test results
    try:
        test_results = load_test_results(args.results)
    except Exception as e:
        print(f"ERROR loading test results: {e}")
        sys.exit(1)
    
    # Create evaluator
    evaluator = PrecisionRecallEvaluator(ground_truth)
    
    # Evaluate all queries
    metrics = evaluator.evaluate_all(test_results)
    
    # Calculate aggregate metrics
    aggregate = evaluator.aggregate_metrics(metrics)
    
    # Print results
    if args.verbose:
        print(f"\n{'='*80}")
        print("PER-QUERY METRICS")
        print(f"{'='*80}")
        for m in metrics:
            print(f"\nQuery {m.query_id}:")
            print(f"  Precision@5: {m.precision_at_5:.1%}")
            print(f"  Recall@5: {m.recall_at_5:.1%}")
            print(f"  NDCG@5: {m.ndcg_at_5:.3f}")
            print(f"  MRR: {m.mean_reciprocal_rank:.3f}")
            print(f"  Retrieved: {m.relevant_retrieved}/{m.total_relevant} relevant")
    
    print(f"\n{'='*80}")
    print("AGGREGATE METRICS")
    print(f"{'='*80}")
    print(f"Mean Precision@1: {aggregate['mean_precision_at_1']:.1%}")
    print(f"Mean Precision@3: {aggregate['mean_precision_at_3']:.1%}")
    print(f"Mean Precision@5: {aggregate['mean_precision_at_5']:.1%} (target: ≥70%)")
    print(f"Mean Precision@10: {aggregate['mean_precision_at_10']:.1%}")
    print(f"Mean Recall@5: {aggregate['mean_recall_at_5']:.1%}")
    print(f"Mean Recall@10: {aggregate['mean_recall_at_10']:.1%}")
    print(f"Mean NDCG@5: {aggregate['mean_ndcg_at_5']:.3f}")
    print(f"Mean NDCG@10: {aggregate['mean_ndcg_at_10']:.3f}")
    print(f"Mean MRR: {aggregate['mean_mrr']:.3f}")
    print(f"\nTotal Queries: {aggregate['total_queries']}")
    print(f"Queries with Results: {aggregate['queries_with_results']}")
    
    # Check if target met
    target_met = aggregate['mean_precision_at_5'] >= 0.70
    print(f"\nTarget Achievement: {'✓ PASS' if target_met else '✗ FAIL'}")
    
    # Save results
    import os
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    output_data = {
        "aggregate_metrics": aggregate,
        "per_query_metrics": [
            {
                "query_id": m.query_id,
                "precision_at_1": m.precision_at_1,
                "precision_at_3": m.precision_at_3,
                "precision_at_5": m.precision_at_5,
                "precision_at_10": m.precision_at_10,
                "recall_at_5": m.recall_at_5,
                "recall_at_10": m.recall_at_10,
                "ndcg_at_5": m.ndcg_at_5,
                "ndcg_at_10": m.ndcg_at_10,
                "mrr": m.mean_reciprocal_rank,
                "relevant_retrieved": m.relevant_retrieved,
                "total_relevant": m.total_relevant,
                "total_retrieved": m.total_retrieved
            }
            for m in metrics
        ],
        "target_met": target_met
    }
    
    with open(args.output, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"\nResults saved to: {args.output}")
    
    sys.exit(0 if target_met else 1)

if __name__ == '__main__':
    main()
