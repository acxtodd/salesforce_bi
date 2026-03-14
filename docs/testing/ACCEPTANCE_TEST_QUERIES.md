# Acceptance Test - Curated Query Set

## Overview

This document defines a curated set of test queries for acceptance testing of the Salesforce AI Search POC. Each query includes expected results and validation criteria to measure precision@5 and overall system quality.

**Target Metrics:**
- Precision@5: ≥70% on curated set
- All answers must include valid citations
- p95 first token latency: ≤800ms
- p95 end-to-end latency: ≤4.0s

## Test Queries

### Single-Object Queries

#### Q1: Account Search
**Query:** "Show me all enterprise accounts in EMEA with annual revenue over $10M"

**Expected Results:**
- Object: Account
- Filters: Region=EMEA, Industry/Type=Enterprise
- Should return accounts with AnnualRevenue > 10000000
- Expected count: 3-5 accounts

**Validation:**
- All results are Account records
- All have Region=EMEA
- All have AnnualRevenue > $10M
- Citations include Account IDs

---

#### Q2: Opportunity Search
**Query:** "What opportunities are in the proposal stage with close dates in Q1 2026?"

**Expected Results:**
- Object: Opportunity
- Filters: StageName=Proposal, CloseDate between 2026-01-01 and 2026-03-31
- Expected count: 2-4 opportunities

**Validation:**
- All results are Opportunity records
- All have StageName=Proposal
- All have CloseDate in Q1 2026
- Citations include Opportunity IDs

---

#### Q3: Case Search
**Query:** "Show high priority cases opened in the last 30 days"

**Expected Results:**
- Object: Case
- Filters: Priority=High, CreatedDate >= (today - 30 days)
- Expected count: 1-3 cases

**Validation:**
- All results are Case records
- All have Priority=High
- All have recent CreatedDate
- Citations include Case IDs

---

#### Q4: Property Search
**Query:** "Find commercial properties in downtown with parking"

**Expected Results:**
- Object: Property__c
- Filters: Property_Type__c=Commercial, City__c contains "downtown"
- Text match: "parking" in Description__c or Amenities__c
- Expected count: 1-2 properties

**Validation:**
- All results are Property__c records
- All mention parking in description
- Citations include Property__c IDs

---

#### Q5: Lease Search
**Query:** "Which leases are expiring in the next 90 days?"

**Expected Results:**
- Object: Lease__c
- Filters: End_Date__c between today and (today + 90 days)
- Expected count: 2-3 leases

**Validation:**
- All results are Lease__c records
- All have End_Date__c in next 90 days
- Citations include Lease__c IDs

---

### Multi-Object Queries

#### Q6: Account + Opportunity (U1 from Requirements)
**Query:** "Show open opportunities over $1M for ACME in EMEA and summarize blockers"

**Expected Results:**
- Objects: Opportunity (primary), Account (context)
- Filters: AccountName=ACME, Region=EMEA, Amount > 1000000, Stage IN (Prospecting, Qualification, Proposal, Negotiation)
- Expected count: 1-2 opportunities
- Answer should summarize blockers from Description or Notes

**Validation:**
- Results include Opportunity records for ACME
- All have Amount > $1M
- All have Region=EMEA
- Answer includes blocker summary
- Citations include Opportunity IDs
- Answer mentions specific blockers (budget, approval, competition, etc.)

---

#### Q7: Account + Lease + Case (U2 from Requirements)
**Query:** "Which accounts have leases expiring next quarter with HVAC-related cases in the last 90 days?"

**Expected Results:**
- Objects: Account, Lease__c, Case
- Filters: 
  - Lease__c: End_Date__c in next quarter
  - Case: Subject/Description contains "HVAC", CreatedDate >= (today - 90 days)
- Expected count: 1-2 accounts
- Answer should connect accounts with both expiring leases and HVAC cases

**Validation:**
- Results include Account records
- Each account has at least one expiring lease
- Each account has at least one HVAC-related case
- Citations include Account, Lease__c, and Case IDs
- Answer explicitly connects the relationships

---

#### Q8: Account + Note (U3 from Requirements)
**Query:** "Summarize renewal risks for ACME with citations to Notes"

**Expected Results:**
- Objects: Account (ACME), Note (related to ACME)
- Filters: AccountName=ACME
- Expected count: 2-4 notes
- Answer should summarize risks mentioned in notes

**Validation:**
- Results include Note records related to ACME
- Answer summarizes risks (pricing, competition, budget, timeline, etc.)
- Citations include Note IDs
- Each risk claim has a citation

---

#### Q9: Property + Lease + Contract
**Query:** "Show properties with active leases and maintenance contracts in the downtown area"

**Expected Results:**
- Objects: Property__c, Lease__c, Contract__c
- Filters: 
  - Property__c: City__c contains "downtown"
  - Lease__c: Status__c=Active
  - Contract__c: Contract_Type__c=Maintenance, Status__c=Active
- Expected count: 1-2 properties

**Validation:**
- Results include Property__c records
- Each property has active leases
- Each property has maintenance contracts
- Citations include Property__c, Lease__c, and Contract__c IDs

---

#### Q10: Opportunity + Case
**Query:** "What opportunities have related support cases with critical priority?"

**Expected Results:**
- Objects: Opportunity, Case
- Filters: Case.Priority=Critical
- Expected count: 1-2 opportunities
- Answer should connect opportunities to their critical cases

**Validation:**
- Results include Opportunity records
- Each opportunity has related critical cases
- Citations include Opportunity and Case IDs
- Answer explains the relationship

---

### Edge Cases and Complex Queries

#### Q11: No Results Query
**Query:** "Show me opportunities for XYZ Corp in Antarctica"

**Expected Results:**
- No matching records
- System should return "no results" message
- Should NOT generate speculative content

**Validation:**
- Response indicates no results found
- No citations provided
- No made-up information
- Friendly error message

---

#### Q12: Ambiguous Query
**Query:** "Tell me about the big deal"

**Expected Results:**
- System should ask for clarification OR
- Return top opportunities by amount
- Should handle ambiguity gracefully

**Validation:**
- System doesn't fail
- Response is reasonable
- Citations provided for any claims

---

#### Q13: Cross-Entity Relationship
**Query:** "Which properties managed by John Smith have open maintenance cases?"

**Expected Results:**
- Objects: Property__c, Case
- Filters: Property_Manager__c.Name=John Smith, Case.Status!=Closed
- Expected count: 1-2 properties

**Validation:**
- Results include Property__c records
- All managed by John Smith
- Each has open maintenance cases
- Citations include Property__c and Case IDs

---

#### Q14: Temporal Query
**Query:** "What changed in the last week for ACME account?"

**Expected Results:**
- Objects: Account, Opportunity, Case, Note (all related to ACME)
- Filters: LastModifiedDate >= (today - 7 days)
- Expected count: 2-5 records

**Validation:**
- All results related to ACME
- All have recent LastModifiedDate
- Answer summarizes changes
- Citations include various object types

---

#### Q15: Aggregation Query
**Query:** "What's the total pipeline value for EMEA region?"

**Expected Results:**
- Objects: Opportunity
- Filters: Region=EMEA, Stage IN (open stages)
- Answer should sum Amount fields

**Validation:**
- Answer includes total value
- Citations include Opportunity IDs used in calculation
- Calculation is accurate

---

#### Q16: Comparison Query
**Query:** "Compare renewal opportunities for ACME vs GlobalTech"

**Expected Results:**
- Objects: Opportunity
- Filters: AccountName IN (ACME, GlobalTech), Type=Renewal
- Expected count: 2-4 opportunities

**Validation:**
- Results include opportunities for both accounts
- Answer compares key metrics (amount, stage, close date)
- Citations include Opportunity IDs for both accounts

---

#### Q17: Negative Filter Query
**Query:** "Show accounts without any open opportunities"

**Expected Results:**
- Objects: Account
- Complex filter: No related Opportunity with open stage
- Expected count: 3-5 accounts

**Validation:**
- Results include Account records
- None have open opportunities
- Citations include Account IDs

---

#### Q18: Field-Specific Query
**Query:** "Which opportunities have risk notes mentioning budget concerns?"

**Expected Results:**
- Objects: Opportunity
- Text match: "budget" in Risk_Notes__c or Description
- Expected count: 1-3 opportunities

**Validation:**
- All results mention budget in relevant fields
- Citations include Opportunity IDs
- Answer quotes relevant text

---

#### Q19: Multi-Hop Relationship
**Query:** "Show cases for properties owned by enterprise accounts"

**Expected Results:**
- Objects: Case, Property__c, Account
- Filters: Account.Type=Enterprise
- Relationship: Case → Property__c → Account
- Expected count: 2-4 cases

**Validation:**
- Results include Case records
- Each case relates to property owned by enterprise account
- Citations include Case, Property__c, and Account IDs

---

#### Q20: Contextual Query
**Query:** "What are the next steps?" (with recordContext: OpportunityId=006xx)

**Expected Results:**
- Objects: Opportunity, Note, Task (related to 006xx)
- Context-aware: Uses provided OpportunityId
- Answer should summarize next steps from notes/tasks

**Validation:**
- Response is specific to provided opportunity
- Citations include records related to 006xx
- Answer includes actionable next steps

---

## Test Execution Instructions

### Setup
1. Ensure test data is loaded in Salesforce sandbox
2. Configure test users with different roles (Rep, Manager, Admin)
3. Deploy latest version of LWC and API endpoints
4. Clear any caches before testing

### Execution Process
1. Execute each query through the LWC interface
2. Record response time (first token and end-to-end)
3. Evaluate precision@5 (are top 5 results relevant?)
4. Verify all citations are valid and accessible
5. Check answer quality and completeness
6. Document any issues or unexpected behavior

### Precision Calculation
For each query:
- **Relevant**: Result directly answers the query
- **Partially Relevant**: Result is related but not ideal
- **Not Relevant**: Result doesn't match query intent

Precision@5 = (Relevant + 0.5 × Partially Relevant) / 5

**Example:**
- 4 Relevant, 1 Partially Relevant: (4 + 0.5) / 5 = 90%
- 3 Relevant, 2 Not Relevant: 3 / 5 = 60%

### Success Criteria
- **Overall Precision@5**: ≥70% across all queries
- **Citation Accuracy**: 100% (all citations must be valid)
- **No Hallucinations**: 0 instances of made-up information
- **Performance**: 
  - p95 first token: ≤800ms
  - p95 end-to-end: ≤4.0s

## Test Data Requirements

To execute these queries, the following test data should exist:

### Accounts
- ACME Corporation (Enterprise, EMEA, $50M revenue)
- GlobalTech Inc (Enterprise, Americas, $30M revenue)
- 3-5 additional accounts with varying attributes

### Opportunities
- 2-3 opportunities for ACME (various stages, $1M+)
- 2-3 opportunities for GlobalTech
- Mix of stages: Prospecting, Qualification, Proposal, Negotiation
- Close dates spanning Q4 2025 - Q2 2026

### Cases
- 2-3 high priority cases (last 30 days)
- 1-2 HVAC-related cases for accounts with expiring leases
- 1-2 critical priority cases related to opportunities

### Properties (Property__c)
- 2-3 commercial properties in downtown area
- At least 1 with parking amenities
- Properties managed by John Smith

### Leases (Lease__c)
- 2-3 leases expiring in next 90 days
- 1-2 active leases for downtown properties

### Contracts (Contract__c)
- 1-2 maintenance contracts for downtown properties
- Mix of active and expired contracts

### Notes
- 3-4 notes for ACME mentioning renewal risks
- Notes should mention: budget concerns, competition, pricing, timeline

## Results Template

```markdown
## Test Execution Results - [Date]

### Query: [Query Text]
- **Execution Time**: [First Token]ms / [End-to-End]ms
- **Results Returned**: [Count]
- **Precision@5**: [Score]
- **Citations Valid**: [Yes/No]
- **Answer Quality**: [Excellent/Good/Fair/Poor]
- **Issues**: [Any problems observed]

### Precision Breakdown:
1. [Result 1]: [Relevant/Partially/Not Relevant]
2. [Result 2]: [Relevant/Partially/Not Relevant]
3. [Result 3]: [Relevant/Partially/Not Relevant]
4. [Result 4]: [Relevant/Partially/Not Relevant]
5. [Result 5]: [Relevant/Partially/Not Relevant]

### Notes:
[Additional observations]
```

## Automated Testing

For automated execution, use the test script:

```bash
# Run all curated queries
python scripts/run_acceptance_tests.py --queries docs/ACCEPTANCE_TEST_QUERIES.md --output results/acceptance_test_results.json

# Run specific query
python scripts/run_acceptance_tests.py --query-id Q6 --verbose

# Run with specific user context
python scripts/run_acceptance_tests.py --user-id 005xx --role SalesRep
```
