# CRE Acceptance Test - Curated Query Set

## Overview

This document defines a curated set of test queries for acceptance testing of the Salesforce AI Search POC, focused on Commercial Real Estate (CRE) objects from the Ascendix package.

**Target Objects:**
- `ascendix__Property__c` (2,466 records)
- `ascendix__Availability__c` (527 records)
- `ascendix__Lease__c` (483 records)
- `ascendix__Sale__c` (55 records)
- `ascendix__Deal__c` (2,391 records)
- `Account` (4,756 records)

**Target Metrics:**
- Precision@5: ≥70% on curated set
- All answers must include valid citations
- p95 first token latency: ≤800ms
- p95 end-to-end latency: ≤4.0s

---

## Test Queries

### Property Queries

#### Q1: Property Search by City
**Query:** "Show me all properties in Dallas"

**Expected Results:**
- Object: ascendix__Property__c
- Filter: ascendix__City__c = 'DALLAS' or 'Dallas'
- Expected count: ~95 properties

**Validation:**
- All results are Property records
- All have City = Dallas (case-insensitive)
- Citations include Property IDs

---

#### Q2: Property Search by Class
**Query:** "Find Class A office buildings"

**Expected Results:**
- Object: ascendix__Property__c
- Filter: ascendix__PropertyClass__c = 'A' or 'A+'
- Expected count: ~74 properties (66 A + 8 A+)

**Validation:**
- All results are Property records
- All have PropertyClass = A or A+
- Citations include Property IDs

---

#### Q3: Property Search Multi-City
**Query:** "What properties do we have in Los Angeles and Houston?"

**Expected Results:**
- Object: ascendix__Property__c
- Filter: ascendix__City__c IN ('Los Angeles', 'Houston')
- Expected count: ~87 properties (47 LA + 40 Houston)

**Validation:**
- Results include properties from both cities
- Citations include Property IDs
- Answer summarizes by city

---

### Availability Queries

#### Q4: Available Space Search
**Query:** "Show available spaces at 17Seventeen McKinney"

**Expected Results:**
- Object: ascendix__Availability__c
- Filter: Property Name contains '17Seventeen McKinney'
- Expected count: 5+ availabilities (based on sample data)

**Validation:**
- All results are Availability records
- All linked to 17Seventeen McKinney property
- Citations include Availability IDs

---

#### Q5: Availability by Property
**Query:** "What suites are available for lease?"

**Expected Results:**
- Object: ascendix__Availability__c
- Expected count: Up to 527 availabilities
- Answer should summarize available spaces

**Validation:**
- Results are Availability records
- Answer mentions suite numbers and properties
- Citations include Availability IDs

---

### Lease Queries

#### Q6: Expiring Leases
**Query:** "Which leases are expiring in the next 90 days?"

**Expected Results:**
- Object: ascendix__Lease__c
- Filter: ascendix__TermExpirationDate__c between today and today+90
- Expected count: 2 leases

**Validation:**
- All results are Lease records
- All have expiration dates within 90 days
- Citations include Lease IDs
- Answer includes tenant and property info

---

#### Q7: Lease Search by Tenant
**Query:** "Show leases for Thompson & Grey"

**Expected Results:**
- Object: ascendix__Lease__c
- Filter: Tenant Name = 'Thompson & Grey'
- Expected count: 1+ leases

**Validation:**
- All results are Lease records
- All have Thompson & Grey as tenant
- Citations include Lease IDs

---

#### Q8: Lease Search by Property
**Query:** "What are the current leases at Preston Park Financial Center?"

**Expected Results:**
- Object: ascendix__Lease__c
- Filter: Property Name = 'Preston Park Financial Center'
- Expected count: 1+ leases

**Validation:**
- All results are Lease records
- All linked to Preston Park Financial Center
- Citations include Lease IDs

---

### Deal Queries

#### Q9: Open Deals
**Query:** "Show me all open deals"

**Expected Results:**
- Object: ascendix__Deal__c
- Filter: ascendix__Status__c = 'Open'
- Expected count: ~2,308 deals

**Validation:**
- All results are Deal records
- All have Status = Open
- Citations include Deal IDs

---

#### Q10: Deal Search by Client
**Query:** "What deals do we have with StorQuest Self Storage?"

**Expected Results:**
- Object: ascendix__Deal__c
- Filter: Client Name = 'StorQuest Self Storage'
- Expected count: 1+ deals (2825 N. 1st Ave Sale)

**Validation:**
- All results are Deal records
- All have StorQuest Self Storage as client
- Citations include Deal IDs
- Answer includes deal details (fee, stage)

---

#### Q11: Deal Search by Stage
**Query:** "Show deals in LOI stage"

**Expected Results:**
- Object: ascendix__Deal__c
- Filter: ascendix__SalesStage__c = 'LOI'
- Expected count: 2+ deals

**Validation:**
- All results are Deal records
- All have SalesStage = LOI
- Citations include Deal IDs

---

#### Q12: Won Deals
**Query:** "List all won deals"

**Expected Results:**
- Object: ascendix__Deal__c
- Filter: ascendix__Status__c = 'Won'
- Expected count: ~78 deals

**Validation:**
- All results are Deal records
- All have Status = Won
- Citations include Deal IDs

---

#### Q13: Deal by Type
**Query:** "Show me new lease deals"

**Expected Results:**
- Object: ascendix__Deal__c
- Filter: ascendix__DealSubType__c = 'New Lease'
- Expected count: ~9 deals

**Validation:**
- All results are Deal records
- All have DealSubType = New Lease
- Citations include Deal IDs

---

### Sale Queries

#### Q14: Property Sales
**Query:** "Show recent property sales"

**Expected Results:**
- Object: ascendix__Sale__c
- Expected count: Up to 55 sales

**Validation:**
- All results are Sale records
- Citations include Sale IDs
- Answer summarizes sale details

---

### Multi-Object Queries

#### Q15: Property + Availability
**Query:** "Show properties in Dallas with available space"

**Expected Results:**
- Objects: ascendix__Property__c, ascendix__Availability__c
- Filter: Property City = Dallas, has related Availability
- Expected count: Properties with availabilities

**Validation:**
- Results include both Property and Availability records
- Properties are in Dallas
- Citations include both object types

---

#### Q16: Property + Lease
**Query:** "Which properties have leases expiring soon?"

**Expected Results:**
- Objects: ascendix__Property__c, ascendix__Lease__c
- Filter: Lease expiration within 90 days
- Expected count: 2 properties (based on 2 expiring leases)

**Validation:**
- Results connect properties to expiring leases
- Citations include Property and Lease IDs
- Answer identifies specific properties and tenants

---

#### Q17: Deal + Property
**Query:** "Show deals for properties in New York"

**Expected Results:**
- Objects: ascendix__Deal__c, ascendix__Property__c
- Filter: Property City = 'NEW YORK'
- Expected count: Deals linked to NY properties

**Validation:**
- Results include Deal records
- All linked to New York properties
- Citations include Deal and Property IDs

---

#### Q18: Account + Deal
**Query:** "What deals does Account4 have?"

**Expected Results:**
- Objects: ascendix__Deal__c, Account
- Filter: Client = Account4
- Expected count: 1+ deals (DEALZ)

**Validation:**
- Results include Deal records for Account4
- Citations include Deal IDs
- Answer includes deal details

---

#### Q19: Property + Lease + Deal
**Query:** "Show the Ascendix lease deal details"

**Expected Results:**
- Objects: ascendix__Deal__c, ascendix__Lease__c, ascendix__Property__c
- Filter: Deal Name contains 'Ascendix Lease'
- Expected count: 1 deal with fee $73,500

**Validation:**
- Results include the Ascendix Lease deal
- Answer includes fee amount and stage (LOI)
- Citations include Deal ID

---

### Edge Cases

#### Q20: No Results Query
**Query:** "Show properties in Antarctica"

**Expected Results:**
- No matching records
- System should return "no results" message

**Validation:**
- Response indicates no results found
- No citations provided
- No made-up information

---

#### Q21: Ambiguous Query
**Query:** "Tell me about the big deal"

**Expected Results:**
- System should ask for clarification OR
- Return deals with highest fee amounts

**Validation:**
- System doesn't fail
- Response is reasonable
- Citations provided for any claims

---

#### Q22: Specific Deal Query
**Query:** "What's the status of the 7820 Sunset Boulevard Acquisition?"

**Expected Results:**
- Object: ascendix__Deal__c
- Filter: Name = '7820 Sunset Boulevard Acquisition'
- Expected: Status = Open, Fee = $0

**Validation:**
- Result is the specific deal
- Answer includes status and details
- Citation includes Deal ID

---

## Test Data Summary

Based on evaluation run on 2025-11-25:

### Record Counts
| Object | Count |
|--------|-------|
| ascendix__Property__c | 2,466 |
| ascendix__Availability__c | 527 |
| ascendix__Lease__c | 483 |
| ascendix__Sale__c | 55 |
| ascendix__Deal__c | 2,391 |
| Account | 4,756 |

### Deal Status Distribution
| Status | Count |
|--------|-------|
| Open | 2,308 |
| Won | 78 |
| null | 4 |
| Under Negotiation | 1 |

### Deal Type Distribution
| Type | Count |
|------|-------|
| null | 2,359 |
| New Lease | 9 |
| Loan Acquisition | 6 |
| Investment Sale | 4 |
| Investment Purchase | 3 |
| Expansion | 2 |
| Lease Listing - Exclusive | 2 |
| Other types | 6 |

### Property Class Distribution
| Class | Count |
|-------|-------|
| null | 2,376 |
| A | 66 |
| B | 16 |
| A+ | 8 |

### Top Cities (Properties)
| City | Count |
|------|-------|
| Dallas | 95 |
| Los Angeles | 47 |
| Houston | 40 |
| New York | 38 |
| Chicago | 29 |
| Denver | 27 |
| Phoenix | 23 |
| Miami | 23 |
| Austin | 21 |
| San Antonio | 20 |

### Key Test Records
- **17Seventeen McKinney**: Property with multiple availabilities
- **Prime Corporate Center**: Property with leases
- **Preston Park Financial Center**: Property with lease (2020 Exhibits tenant)
- **Thompson & Grey**: Tenant with lease at 1717 McKinney
- **StorQuest Self Storage**: Client with deal (2825 N. 1st Ave Sale, $30K fee)
- **Ascendix Lease**: Deal in LOI stage, $73,500 fee
- **7820 Sunset Boulevard Acquisition**: Open deal

---

## Test Execution Instructions

### Setup
1. Run batch export for CRE objects to index data
2. Configure test users with appropriate permissions
3. Deploy latest LWC and API endpoints
4. Clear caches before testing

### Batch Export Commands
```apex
// Run from Developer Console or sf apex run
Database.executeBatch(new AISearchBatchExport('ascendix__Property__c', 8760), 50);
Database.executeBatch(new AISearchBatchExport('ascendix__Availability__c', 8760), 50);
Database.executeBatch(new AISearchBatchExport('ascendix__Lease__c', 8760), 50);
Database.executeBatch(new AISearchBatchExport('ascendix__Sale__c', 8760), 50);
Database.executeBatch(new AISearchBatchExport('ascendix__Deal__c', 8760), 50);
```

### Execution Process
1. Execute each query through the LWC interface
2. Record response time (first token and end-to-end)
3. Evaluate precision@5 (are top 5 results relevant?)
4. Verify all citations are valid and accessible
5. Check answer quality and completeness
6. Document any issues

### Success Criteria
- **Overall Precision@5**: ≥70% across all queries
- **Citation Accuracy**: 100% (all citations must be valid)
- **No Hallucinations**: 0 instances of made-up information
- **Performance**: 
  - p95 first token: ≤800ms
  - p95 end-to-end: ≤4.0s
