# User Acceptance Testing (UAT) Plan

## Overview

This document outlines the User Acceptance Testing plan for the Salesforce AI Search POC. The goal is to validate that the system meets user needs and provides value in real-world scenarios.

**Target:** ≥80% of users rate answers as "useful" or better

## UAT Objectives

1. **Validate Answer Quality:** Ensure answers are accurate, relevant, and helpful
2. **Assess User Experience:** Evaluate ease of use and interface design
3. **Measure Business Value:** Determine if system saves time and improves productivity
4. **Identify Gaps:** Discover missing features or data quality issues
5. **Gather Feedback:** Collect suggestions for improvements

## Participant Selection

### Target Participants: 10-20 pilot users

#### User Segments

**Sales Representatives (40% of participants)**
- Primary users of CRM data
- Need quick access to account and opportunity information
- Use cases: Pre-call research, deal preparation, competitive intelligence

**Sales Managers (30% of participants)**
- Need visibility into team performance
- Use cases: Pipeline reviews, forecasting, coaching

**Customer Success Managers (20% of participants)**
- Need account health and case information
- Use cases: Renewal planning, escalation management, customer insights

**Property Managers (10% of participants)**
- Need property, lease, and maintenance information
- Use cases: Lease renewals, maintenance tracking, tenant inquiries

### Selection Criteria

- Active Salesforce users (daily usage)
- Diverse roles and territories
- Mix of technical proficiency levels
- Willing to provide detailed feedback
- Available for 2-week testing period

## UAT Process

### Phase 1: Onboarding (Week 1, Days 1-2)

#### Activities
1. **Kickoff Meeting (1 hour)**
   - Introduce AI Search capabilities
   - Demonstrate LWC interface
   - Show example queries and results
   - Explain citation system
   - Set expectations for testing period

2. **Hands-On Training (30 minutes)**
   - Each user tries 3-5 sample queries
   - Practice using filters (Region, BU, Quarter)
   - Learn to navigate citations
   - Understand how to provide feedback

3. **Access Setup**
   - Deploy LWC to user's Salesforce org
   - Verify permissions and data access
   - Provide quick reference guide
   - Share feedback survey link

### Phase 2: Guided Testing (Week 1, Days 3-5)

#### Daily Tasks
Each user completes 5-10 queries per day based on their role:

**Sales Rep Tasks:**
- "Show me all opportunities in my territory over $500K"
- "What are the top risks for [Account Name]?"
- "Find accounts with open cases in the last 30 days"
- "Summarize recent activity for [Account Name]"
- "Which opportunities are stuck in qualification stage?"

**Sales Manager Tasks:**
- "Show me my team's pipeline by stage"
- "What deals are at risk of slipping this quarter?"
- "Compare performance across territories"
- "Find accounts without recent activity"
- "Summarize blockers across my team's opportunities"

**CSM Tasks:**
- "Show accounts with upcoming renewals"
- "Find high-priority cases for enterprise accounts"
- "Which accounts have the most support cases?"
- "Summarize health indicators for [Account Name]"
- "Find accounts with declining engagement"

**Property Manager Tasks:**
- "Show properties with leases expiring in 90 days"
- "Find properties with open maintenance cases"
- "Which tenants have late payments?"
- "Summarize property performance by region"
- "Find properties with upcoming inspections"

#### Feedback Collection
After each query, users rate:
- **Answer Quality:** Excellent / Good / Fair / Poor
- **Relevance:** Very Relevant / Somewhat Relevant / Not Relevant
- **Usefulness:** Very Useful / Useful / Somewhat Useful / Not Useful
- **Citations:** Helpful / Neutral / Not Helpful

### Phase 3: Free-Form Testing (Week 2, Days 1-5)

#### Activities
Users test the system with their own real-world queries:
- No prescribed tasks
- Use system as needed for daily work
- Encouraged to try complex queries
- Report any issues or unexpected behavior

#### Daily Check-Ins
- 15-minute daily standup (optional)
- Share interesting queries and results
- Discuss challenges or confusion
- Celebrate successes

### Phase 4: Feedback & Wrap-Up (Week 2, Days 6-7)

#### Activities
1. **Individual Interviews (30 minutes each)**
   - What worked well?
   - What didn't work?
   - What features are missing?
   - Would you use this in production?
   - Net Promoter Score (NPS)

2. **Group Retrospective (1 hour)**
   - Share experiences across roles
   - Identify common themes
   - Prioritize improvement areas
   - Discuss deployment readiness

3. **Final Survey**
   - Comprehensive feedback form
   - Quantitative ratings
   - Open-ended comments
   - Feature requests

## Feedback Instruments

### Query-Level Feedback (After Each Query)

```
Query: [User's query text]

1. How would you rate the answer quality?
   ○ Excellent - Accurate, complete, and well-cited
   ○ Good - Mostly accurate with minor issues
   ○ Fair - Partially helpful but incomplete
   ○ Poor - Inaccurate or not helpful

2. How relevant were the results to your query?
   ○ Very Relevant - Exactly what I needed
   ○ Somewhat Relevant - Related but not ideal
   ○ Not Relevant - Didn't match my intent

3. How useful was this answer for your work?
   ○ Very Useful - Saved significant time
   ○ Useful - Helped me find information
   ○ Somewhat Useful - Provided some value
   ○ Not Useful - Didn't help

4. Were the citations helpful?
   ○ Yes - Helped me verify and explore further
   ○ Neutral - Didn't use them
   ○ No - Confusing or not useful

5. Any issues or comments? (Optional)
   [Free text]
```

### Daily Feedback (End of Each Day)

```
Date: [Date]

1. How many queries did you run today?
   [Number]

2. What percentage of answers were useful?
   ○ 80-100% (Most were useful)
   ○ 60-79% (Many were useful)
   ○ 40-59% (Some were useful)
   ○ 0-39% (Few were useful)

3. Did you encounter any errors or issues?
   ○ Yes [Describe]
   ○ No

4. What was your best query today?
   [Free text]

5. What was your worst query today?
   [Free text]

6. Any suggestions for improvement?
   [Free text]
```

### Final Survey (End of UAT)

```
User Acceptance Testing - Final Survey

Background:
- Name: [Name]
- Role: [Role]
- Territory/Region: [Territory]
- Years using Salesforce: [Number]

Overall Experience:

1. Overall, how satisfied are you with the AI Search system?
   ○ Very Satisfied
   ○ Satisfied
   ○ Neutral
   ○ Dissatisfied
   ○ Very Dissatisfied

2. How likely are you to recommend this system to a colleague? (NPS)
   0 (Not at all likely) - 10 (Extremely likely)
   [0] [1] [2] [3] [4] [5] [6] [7] [8] [9] [10]

3. How often would you use this system if deployed?
   ○ Multiple times per day
   ○ Daily
   ○ Weekly
   ○ Monthly
   ○ Rarely

Answer Quality:

4. What percentage of answers were useful for your work?
   ○ 80-100%
   ○ 60-79%
   ○ 40-59%
   ○ 20-39%
   ○ 0-19%

5. How accurate were the answers?
   ○ Very Accurate - Rarely found errors
   ○ Mostly Accurate - Occasional errors
   ○ Somewhat Accurate - Frequent errors
   ○ Not Accurate - Many errors

6. How complete were the answers?
   ○ Very Complete - Answered fully
   ○ Mostly Complete - Minor gaps
   ○ Somewhat Complete - Significant gaps
   ○ Incomplete - Often missing information

User Experience:

7. How easy was the system to use?
   ○ Very Easy
   ○ Easy
   ○ Neutral
   ○ Difficult
   ○ Very Difficult

8. How intuitive was the interface?
   ○ Very Intuitive
   ○ Intuitive
   ○ Neutral
   ○ Confusing
   ○ Very Confusing

9. How helpful were the citations?
   ○ Very Helpful - Used them frequently
   ○ Helpful - Used them occasionally
   ○ Neutral - Didn't use them
   ○ Not Helpful - Confusing or irrelevant

Performance:

10. How would you rate the response speed?
    ○ Very Fast - Instant results
    ○ Fast - Acceptable wait time
    ○ Neutral - Noticeable delay
    ○ Slow - Frustrating wait time
    ○ Very Slow - Unacceptable

Business Value:

11. Did this system save you time compared to manual searching?
    ○ Yes, significant time savings (>30 min/day)
    ○ Yes, moderate time savings (10-30 min/day)
    ○ Yes, minor time savings (<10 min/day)
    ○ No time savings
    ○ Actually took more time

12. Did this system help you find information you wouldn't have found otherwise?
    ○ Yes, frequently
    ○ Yes, occasionally
    ○ Rarely
    ○ Never

13. Did this system improve your decision-making?
    ○ Yes, significantly
    ○ Yes, somewhat
    ○ No impact
    ○ Made it worse

Specific Feedback:

14. What did you like most about the system?
    [Free text]

15. What did you like least about the system?
    [Free text]

16. What features are missing that you need?
    [Free text]

17. What would you change or improve?
    [Free text]

18. Any other comments or suggestions?
    [Free text]
```

## Success Criteria

### Primary Metric
- **≥80% of users rate answers as "useful" or better** (Very Useful or Useful)

### Secondary Metrics
- **Answer Quality:** ≥70% of answers rated "Good" or "Excellent"
- **Relevance:** ≥75% of results rated "Very Relevant" or "Somewhat Relevant"
- **User Satisfaction:** ≥70% "Satisfied" or "Very Satisfied"
- **Net Promoter Score:** ≥30 (Promoters - Detractors)
- **Adoption Intent:** ≥70% would use "Daily" or "Multiple times per day"
- **Time Savings:** ≥60% report time savings
- **Error Rate:** <10% of queries result in errors

### Qualitative Success Indicators
- Users discover new insights they wouldn't have found manually
- Users trust the citations and verify information
- Users prefer AI Search over manual searching for common tasks
- Users request deployment to production
- Users provide constructive feedback for improvements

## Data Collection & Analysis

### Quantitative Data
- Query-level ratings (stored in DynamoDB telemetry table)
- Daily feedback scores
- Final survey responses
- Usage metrics (queries per user, session duration)
- Performance metrics (latency, error rate)

### Qualitative Data
- Interview transcripts
- Open-ended survey responses
- Daily standup notes
- Support tickets or issues reported
- Feature requests

### Analysis Methods
1. **Descriptive Statistics:** Calculate means, medians, percentages for all metrics
2. **Segmentation:** Analyze by user role, territory, experience level
3. **Trend Analysis:** Track metrics over time (Week 1 vs Week 2)
4. **Thematic Analysis:** Identify common themes in qualitative feedback
5. **Correlation Analysis:** Identify factors that predict satisfaction

## Reporting

### Weekly Status Report
- Participation rate
- Queries executed
- Average ratings
- Top issues
- Key insights

### Final UAT Report

**Executive Summary:**
- Overall success/failure against criteria
- Key findings and recommendations
- Go/no-go recommendation for production

**Detailed Results:**
- All quantitative metrics with charts
- Qualitative themes and quotes
- User segmentation analysis
- Performance data
- Issue log and resolutions

**Recommendations:**
- Must-fix issues before production
- Nice-to-have improvements
- Future enhancements
- Training needs
- Deployment plan

## Risk Mitigation

### Potential Risks

**Low Participation**
- Mitigation: Executive sponsorship, incentives, flexible scheduling
- Contingency: Extend UAT period, recruit additional users

**Technical Issues**
- Mitigation: Thorough pre-UAT testing, dedicated support channel
- Contingency: Pause UAT, fix issues, resume testing

**Poor Results**
- Mitigation: Set realistic expectations, focus on learning
- Contingency: Iterate on design, conduct additional UAT round

**Data Quality Issues**
- Mitigation: Pre-load high-quality test data, document known gaps
- Contingency: Improve data quality, re-test affected scenarios

**User Confusion**
- Mitigation: Clear training, quick reference guide, support channel
- Contingency: Additional training sessions, improved documentation

## Post-UAT Actions

### If Success Criteria Met (≥80% useful)
1. Address critical issues identified
2. Implement high-priority improvements
3. Prepare production deployment plan
4. Develop user training materials
5. Plan phased rollout to broader user base

### If Success Criteria Not Met (<80% useful)
1. Conduct root cause analysis
2. Prioritize improvements based on feedback
3. Implement fixes and enhancements
4. Conduct second UAT round with subset of users
5. Re-evaluate deployment timeline

## UAT Checklist

### Pre-UAT (1 week before)
- [ ] Recruit 10-20 pilot users
- [ ] Schedule kickoff meeting
- [ ] Prepare training materials
- [ ] Deploy LWC to sandbox
- [ ] Load test data
- [ ] Set up feedback surveys
- [ ] Create support channel (Slack/Teams)
- [ ] Test all functionality
- [ ] Prepare quick reference guide

### During UAT (2 weeks)
- [ ] Conduct kickoff and training
- [ ] Monitor daily participation
- [ ] Respond to support requests
- [ ] Collect daily feedback
- [ ] Track issues and resolutions
- [ ] Send weekly status updates
- [ ] Conduct individual interviews
- [ ] Host group retrospective

### Post-UAT (1 week after)
- [ ] Analyze all feedback data
- [ ] Create final UAT report
- [ ] Present findings to stakeholders
- [ ] Prioritize improvements
- [ ] Make go/no-go decision
- [ ] Plan next steps
- [ ] Thank participants

## Support During UAT

### Support Channels
- **Slack Channel:** #ai-search-uat (real-time support)
- **Email:** ai-search-support@company.com
- **Office Hours:** Daily 10-11am and 3-4pm

### Support Team
- Product Manager: Overall coordination
- Technical Lead: Technical issues and bugs
- UX Designer: Interface and usability questions
- Data Analyst: Data quality and results questions

### Response SLAs
- Critical issues (system down): 1 hour
- High priority (blocking work): 4 hours
- Medium priority (workaround available): 1 day
- Low priority (enhancement request): End of UAT

## Communication Plan

### Kickoff Email (1 week before)
- Welcome and thank you
- UAT objectives and timeline
- What to expect
- How to provide feedback
- Support contacts

### Daily Reminders (During UAT)
- Reminder to complete daily tasks
- Highlight interesting queries from other users
- Share tips and tricks
- Celebrate milestones

### Weekly Updates (During UAT)
- Participation summary
- Key insights so far
- Issues resolved
- Upcoming activities

### Wrap-Up Email (End of UAT)
- Thank you message
- Summary of participation
- Next steps
- Timeline for results
- How feedback will be used

## Appendix: Sample Queries by Role

### Sales Representative Queries
1. "Show me all opportunities in my territory over $500K"
2. "What are the top risks for ACME Corporation?"
3. "Find accounts with open cases in the last 30 days"
4. "Summarize recent activity for GlobalTech"
5. "Which opportunities are stuck in qualification stage?"
6. "Show me accounts without activity in 60 days"
7. "What deals are closing this quarter?"
8. "Find competitive losses in the last quarter"
9. "Show me all notes mentioning pricing concerns"
10. "Which accounts have the highest engagement?"

### Sales Manager Queries
1. "Show me my team's pipeline by stage"
2. "What deals are at risk of slipping this quarter?"
3. "Compare performance across territories"
4. "Find accounts without recent activity"
5. "Summarize blockers across my team's opportunities"
6. "Show me win rate by product line"
7. "Which reps need coaching on qualification?"
8. "Find opportunities with long sales cycles"
9. "Show me forecast accuracy by rep"
10. "What are the top reasons for lost deals?"

### Customer Success Manager Queries
1. "Show accounts with upcoming renewals"
2. "Find high-priority cases for enterprise accounts"
3. "Which accounts have the most support cases?"
4. "Summarize health indicators for ACME"
5. "Find accounts with declining engagement"
6. "Show me at-risk renewals this quarter"
7. "Which accounts have escalated cases?"
8. "Find accounts with low product adoption"
9. "Show me customer satisfaction trends"
10. "Which accounts need executive engagement?"

### Property Manager Queries
1. "Show properties with leases expiring in 90 days"
2. "Find properties with open maintenance cases"
3. "Which tenants have late payments?"
4. "Summarize property performance by region"
5. "Find properties with upcoming inspections"
6. "Show me vacancy rates by property type"
7. "Which properties have the highest maintenance costs?"
8. "Find leases with renewal options"
9. "Show me tenant satisfaction scores"
10. "Which properties need capital improvements?"
