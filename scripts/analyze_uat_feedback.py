#!/usr/bin/env python3
"""
UAT Feedback Analysis Script

This script analyzes user acceptance testing feedback and generates
a comprehensive report with metrics and insights.

Usage:
    python scripts/analyze_uat_feedback.py --feedback data/uat_feedback.json
    python scripts/analyze_uat_feedback.py --feedback data/uat_feedback.json --output results/uat_report.json
"""

import argparse
import json
import sys
import statistics
from typing import Dict, List
from dataclasses import dataclass
from collections import defaultdict, Counter
from datetime import datetime

@dataclass
class QueryFeedback:
    """Feedback for a single query"""
    user_id: str
    query: str
    answer_quality: str  # Excellent, Good, Fair, Poor
    relevance: str  # Very Relevant, Somewhat Relevant, Not Relevant
    usefulness: str  # Very Useful, Useful, Somewhat Useful, Not Useful
    citations_helpful: str  # Yes, Neutral, No
    comments: str
    timestamp: str

@dataclass
class DailyFeedback:
    """Daily feedback from a user"""
    user_id: str
    date: str
    queries_count: int
    useful_percentage: str  # 80-100%, 60-79%, 40-59%, 0-39%
    had_issues: bool
    best_query: str
    worst_query: str
    suggestions: str

@dataclass
class FinalSurvey:
    """Final survey response from a user"""
    user_id: str
    name: str
    role: str
    territory: str
    years_using_sf: int
    overall_satisfaction: str
    nps_score: int
    usage_frequency: str
    useful_percentage: str
    accuracy: str
    completeness: str
    ease_of_use: str
    intuitiveness: str
    citations_helpful: str
    response_speed: str
    time_savings: str
    found_new_info: str
    improved_decisions: str
    liked_most: str
    liked_least: str
    missing_features: str
    improvements: str
    other_comments: str

class UATAnalyzer:
    """Analyzes UAT feedback data"""
    
    # Rating scales
    ANSWER_QUALITY_SCALE = {"Excellent": 4, "Good": 3, "Fair": 2, "Poor": 1}
    RELEVANCE_SCALE = {"Very Relevant": 3, "Somewhat Relevant": 2, "Not Relevant": 1}
    USEFULNESS_SCALE = {"Very Useful": 4, "Useful": 3, "Somewhat Useful": 2, "Not Useful": 1}
    SATISFACTION_SCALE = {"Very Satisfied": 5, "Satisfied": 4, "Neutral": 3, "Dissatisfied": 2, "Very Dissatisfied": 1}
    
    def __init__(self, query_feedback: List[QueryFeedback], 
                 daily_feedback: List[DailyFeedback],
                 final_surveys: List[FinalSurvey]):
        self.query_feedback = query_feedback
        self.daily_feedback = daily_feedback
        self.final_surveys = final_surveys
    
    def analyze_query_feedback(self) -> Dict:
        """Analyze query-level feedback"""
        if not self.query_feedback:
            return {}
        
        # Count ratings
        quality_counts = Counter(f.answer_quality for f in self.query_feedback)
        relevance_counts = Counter(f.relevance for f in self.query_feedback)
        usefulness_counts = Counter(f.usefulness for f in self.query_feedback)
        citations_counts = Counter(f.citations_helpful for f in self.query_feedback)
        
        # Calculate percentages
        total = len(self.query_feedback)
        
        # Usefulness metric (primary success criterion)
        useful_count = sum(1 for f in self.query_feedback 
                          if f.usefulness in ["Very Useful", "Useful"])
        useful_percentage = (useful_count / total) * 100
        
        # Quality metric
        good_quality_count = sum(1 for f in self.query_feedback 
                                if f.answer_quality in ["Excellent", "Good"])
        quality_percentage = (good_quality_count / total) * 100
        
        # Relevance metric
        relevant_count = sum(1 for f in self.query_feedback 
                            if f.relevance in ["Very Relevant", "Somewhat Relevant"])
        relevance_percentage = (relevant_count / total) * 100
        
        return {
            "total_queries": total,
            "usefulness": {
                "very_useful": quality_counts.get("Very Useful", 0),
                "useful": quality_counts.get("Useful", 0),
                "somewhat_useful": quality_counts.get("Somewhat Useful", 0),
                "not_useful": quality_counts.get("Not Useful", 0),
                "useful_percentage": useful_percentage,
                "target": 80.0,
                "target_met": useful_percentage >= 80.0
            },
            "answer_quality": {
                "excellent": quality_counts.get("Excellent", 0),
                "good": quality_counts.get("Good", 0),
                "fair": quality_counts.get("Fair", 0),
                "poor": quality_counts.get("Poor", 0),
                "good_or_better_percentage": quality_percentage,
                "target": 70.0,
                "target_met": quality_percentage >= 70.0
            },
            "relevance": {
                "very_relevant": relevance_counts.get("Very Relevant", 0),
                "somewhat_relevant": relevance_counts.get("Somewhat Relevant", 0),
                "not_relevant": relevance_counts.get("Not Relevant", 0),
                "relevant_percentage": relevance_percentage,
                "target": 75.0,
                "target_met": relevance_percentage >= 75.0
            },
            "citations": {
                "helpful": citations_counts.get("Yes", 0),
                "neutral": citations_counts.get("Neutral", 0),
                "not_helpful": citations_counts.get("No", 0)
            }
        }
    
    def analyze_final_surveys(self) -> Dict:
        """Analyze final survey responses"""
        if not self.final_surveys:
            return {}
        
        total_users = len(self.final_surveys)
        
        # Overall satisfaction
        satisfaction_counts = Counter(s.overall_satisfaction for s in self.final_surveys)
        satisfied_count = sum(satisfaction_counts.get(level, 0) 
                             for level in ["Very Satisfied", "Satisfied"])
        satisfaction_percentage = (satisfied_count / total_users) * 100
        
        # NPS calculation
        nps_scores = [s.nps_score for s in self.final_surveys]
        promoters = sum(1 for score in nps_scores if score >= 9)
        passives = sum(1 for score in nps_scores if 7 <= score <= 8)
        detractors = sum(1 for score in nps_scores if score <= 6)
        nps = ((promoters - detractors) / total_users) * 100
        
        # Usage frequency
        frequency_counts = Counter(s.usage_frequency for s in self.final_surveys)
        daily_users = sum(frequency_counts.get(freq, 0) 
                         for freq in ["Multiple times per day", "Daily"])
        adoption_percentage = (daily_users / total_users) * 100
        
        # Time savings
        time_savings_counts = Counter(s.time_savings for s in self.final_surveys)
        time_savers = sum(1 for s in self.final_surveys 
                         if "Yes" in s.time_savings)
        time_savings_percentage = (time_savers / total_users) * 100
        
        # Useful percentage from final survey
        useful_80_plus = sum(1 for s in self.final_surveys 
                            if s.useful_percentage in ["80-100%", "60-79%"])
        final_useful_percentage = (useful_80_plus / total_users) * 100
        
        return {
            "total_participants": total_users,
            "overall_satisfaction": {
                "very_satisfied": satisfaction_counts.get("Very Satisfied", 0),
                "satisfied": satisfaction_counts.get("Satisfied", 0),
                "neutral": satisfaction_counts.get("Neutral", 0),
                "dissatisfied": satisfaction_counts.get("Dissatisfied", 0),
                "very_dissatisfied": satisfaction_counts.get("Very Dissatisfied", 0),
                "satisfied_percentage": satisfaction_percentage,
                "target": 70.0,
                "target_met": satisfaction_percentage >= 70.0
            },
            "nps": {
                "score": nps,
                "promoters": promoters,
                "passives": passives,
                "detractors": detractors,
                "target": 30.0,
                "target_met": nps >= 30.0
            },
            "adoption_intent": {
                "multiple_per_day": frequency_counts.get("Multiple times per day", 0),
                "daily": frequency_counts.get("Daily", 0),
                "weekly": frequency_counts.get("Weekly", 0),
                "monthly": frequency_counts.get("Monthly", 0),
                "rarely": frequency_counts.get("Rarely", 0),
                "daily_or_more_percentage": adoption_percentage,
                "target": 70.0,
                "target_met": adoption_percentage >= 70.0
            },
            "time_savings": {
                "significant": time_savings_counts.get("Yes, significant time savings (>30 min/day)", 0),
                "moderate": time_savings_counts.get("Yes, moderate time savings (10-30 min/day)", 0),
                "minor": time_savings_counts.get("Yes, minor time savings (<10 min/day)", 0),
                "none": time_savings_counts.get("No time savings", 0),
                "negative": time_savings_counts.get("Actually took more time", 0),
                "time_savings_percentage": time_savings_percentage,
                "target": 60.0,
                "target_met": time_savings_percentage >= 60.0
            },
            "usefulness_final": {
                "percentage_80_plus": final_useful_percentage
            }
        }
    
    def analyze_by_role(self) -> Dict:
        """Analyze feedback segmented by user role"""
        role_data = defaultdict(lambda: {
            "query_count": 0,
            "useful_count": 0,
            "satisfaction_scores": []
        })
        
        # Map users to roles
        user_roles = {s.user_id: s.role for s in self.final_surveys}
        
        # Aggregate query feedback by role
        for feedback in self.query_feedback:
            role = user_roles.get(feedback.user_id, "Unknown")
            role_data[role]["query_count"] += 1
            if feedback.usefulness in ["Very Useful", "Useful"]:
                role_data[role]["useful_count"] += 1
        
        # Add satisfaction scores
        for survey in self.final_surveys:
            role = survey.role
            sat_score = self.SATISFACTION_SCALE.get(survey.overall_satisfaction, 3)
            role_data[role]["satisfaction_scores"].append(sat_score)
        
        # Calculate percentages
        results = {}
        for role, data in role_data.items():
            useful_pct = (data["useful_count"] / data["query_count"] * 100) if data["query_count"] > 0 else 0
            avg_satisfaction = statistics.mean(data["satisfaction_scores"]) if data["satisfaction_scores"] else 0
            
            results[role] = {
                "query_count": data["query_count"],
                "useful_percentage": useful_pct,
                "average_satisfaction": avg_satisfaction,
                "participant_count": len(data["satisfaction_scores"])
            }
        
        return results
    
    def extract_themes(self) -> Dict:
        """Extract common themes from qualitative feedback"""
        # Collect all text feedback
        liked_most = [s.liked_most for s in self.final_surveys if s.liked_most]
        liked_least = [s.liked_least for s in self.final_surveys if s.liked_least]
        missing_features = [s.missing_features for s in self.final_surveys if s.missing_features]
        improvements = [s.improvements for s in self.final_surveys if s.improvements]
        
        return {
            "liked_most": liked_most,
            "liked_least": liked_least,
            "missing_features": missing_features,
            "improvements": improvements,
            "total_comments": len(liked_most) + len(liked_least) + len(missing_features) + len(improvements)
        }
    
    def generate_report(self) -> Dict:
        """Generate comprehensive UAT report"""
        query_analysis = self.analyze_query_feedback()
        survey_analysis = self.analyze_final_surveys()
        role_analysis = self.analyze_by_role()
        themes = self.extract_themes()
        
        # Overall success determination
        primary_target_met = query_analysis.get("usefulness", {}).get("target_met", False)
        
        all_targets_met = (
            primary_target_met and
            query_analysis.get("answer_quality", {}).get("target_met", False) and
            query_analysis.get("relevance", {}).get("target_met", False) and
            survey_analysis.get("overall_satisfaction", {}).get("target_met", False) and
            survey_analysis.get("nps", {}).get("target_met", False) and
            survey_analysis.get("adoption_intent", {}).get("target_met", False) and
            survey_analysis.get("time_savings", {}).get("target_met", False)
        )
        
        return {
            "summary": {
                "primary_target_met": primary_target_met,
                "all_targets_met": all_targets_met,
                "recommendation": "GO" if primary_target_met else "NO-GO",
                "timestamp": datetime.now().isoformat()
            },
            "query_feedback": query_analysis,
            "final_surveys": survey_analysis,
            "by_role": role_analysis,
            "qualitative_themes": themes
        }

def load_feedback_data(filepath: str) -> tuple:
    """Load UAT feedback data from JSON file"""
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    query_feedback = [QueryFeedback(**item) for item in data.get('query_feedback', [])]
    daily_feedback = [DailyFeedback(**item) for item in data.get('daily_feedback', [])]
    final_surveys = [FinalSurvey(**item) for item in data.get('final_surveys', [])]
    
    return query_feedback, daily_feedback, final_surveys

def main():
    parser = argparse.ArgumentParser(description='Analyze UAT feedback data')
    parser.add_argument('--feedback', required=True, help='Path to UAT feedback JSON file')
    parser.add_argument('--output', default='results/uat_report.json', help='Output file')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    
    # Load feedback data
    try:
        query_feedback, daily_feedback, final_surveys = load_feedback_data(args.feedback)
    except Exception as e:
        print(f"ERROR loading feedback data: {e}")
        sys.exit(1)
    
    # Create analyzer
    analyzer = UATAnalyzer(query_feedback, daily_feedback, final_surveys)
    
    # Generate report
    report = analyzer.generate_report()
    
    # Print summary
    print(f"\n{'='*80}")
    print("UAT REPORT SUMMARY")
    print(f"{'='*80}")
    
    print(f"\nPrimary Success Criterion:")
    useful_pct = report['query_feedback']['usefulness']['useful_percentage']
    print(f"  Useful Answers: {useful_pct:.1f}% (target: ≥80%)")
    print(f"  Status: {'✓ PASS' if report['summary']['primary_target_met'] else '✗ FAIL'}")
    
    print(f"\nSecondary Metrics:")
    quality_pct = report['query_feedback']['answer_quality']['good_or_better_percentage']
    print(f"  Answer Quality: {quality_pct:.1f}% (target: ≥70%)")
    
    relevance_pct = report['query_feedback']['relevance']['relevant_percentage']
    print(f"  Relevance: {relevance_pct:.1f}% (target: ≥75%)")
    
    satisfaction_pct = report['final_surveys']['overall_satisfaction']['satisfied_percentage']
    print(f"  User Satisfaction: {satisfaction_pct:.1f}% (target: ≥70%)")
    
    nps = report['final_surveys']['nps']['score']
    print(f"  NPS: {nps:.0f} (target: ≥30)")
    
    adoption_pct = report['final_surveys']['adoption_intent']['daily_or_more_percentage']
    print(f"  Adoption Intent: {adoption_pct:.1f}% (target: ≥70%)")
    
    time_savings_pct = report['final_surveys']['time_savings']['time_savings_percentage']
    print(f"  Time Savings: {time_savings_pct:.1f}% (target: ≥60%)")
    
    print(f"\nRecommendation: {report['summary']['recommendation']}")
    print(f"All Targets Met: {'✓ YES' if report['summary']['all_targets_met'] else '✗ NO'}")
    
    if args.verbose:
        print(f"\n{'='*80}")
        print("BY ROLE ANALYSIS")
        print(f"{'='*80}")
        for role, data in report['by_role'].items():
            print(f"\n{role}:")
            print(f"  Participants: {data['participant_count']}")
            print(f"  Queries: {data['query_count']}")
            print(f"  Useful: {data['useful_percentage']:.1f}%")
            print(f"  Avg Satisfaction: {data['average_satisfaction']:.2f}/5")
    
    # Save report
    import os
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\nFull report saved to: {args.output}")
    
    # Exit with appropriate code
    sys.exit(0 if report['summary']['primary_target_met'] else 1)

if __name__ == '__main__':
    main()
