# PRD: Semantic Query Decomposition for AI Search

**Document Version:** 1.0
**Date:** November 28, 2024
**Status:** Draft
**Author:** AI Search Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Solution Overview](#3-solution-overview)
4. [Data Model Schema Document](#4-data-model-schema-document)
5. [Query Categories & Examples](#5-query-categories--examples)
6. [Implementation Phases](#6-implementation-phases)
7. [Technical Architecture](#7-technical-architecture)
8. [Success Criteria](#8-success-criteria)
9. [Test Cases](#9-test-cases)
10. [Appendix](#10-appendix)

---

## 1. Executive Summary

### Background

The current AI Search system uses regex-based pattern matching to classify query intent and route to appropriate retrievers. While this approach works for simple queries, it fails for semantically complex queries that require understanding relationships between Salesforce objects.

### Problem Example

**Query:** "What active deals for office properties in Dallas"

**Current Behavior:**
- System searches for "Dallas" in Deal records
- Returns deals with "Dallas" in the name
- Misses deals that are *related to* properties in Dallas

**Expected Behavior:**
- Understand that "Dallas" is a city that lives on Property, not Deal
- Understand that "office" is a property type
- Traverse Property → Deal relationship to find matching deals

### Proposed Solution

Implement an LLM-based query decomposition layer that:
1. Parses natural language queries into structured query plans
2. Identifies target entities vs. filter entities
3. Determines required traversal paths
4. Drives the existing graph traversal infrastructure

---

## 2. Problem Statement

### 2.1 Current Architecture Limitations

The existing `intent_router.py` uses **58 regex patterns** to classify queries into 5 intent types:
- SIMPLE_LOOKUP
- FIELD_FILTER
- RELATIONSHIP
- AGGREGATION
- COMPLEX

**Fundamental limitations:**

| Gap | Description | Impact |
|-----|-------------|--------|
| No Semantic Understanding | Regex cannot understand that "Dallas" is a city field on Property | Queries filtered on wrong entity |
| No Field-to-Object Mapping | System doesn't know which fields belong to which objects | Cannot route filters correctly |
| No Query Planning | No ability to reason about traversal order | Inefficient or incorrect retrieval |
| No Multi-Path Awareness | Cannot determine multiple valid traversal paths | Misses results via indirect relationships |
| Pattern Explosion | Each new query pattern requires new regex | Unmaintainable at scale |

### 2.2 Specific Failure Cases

#### Case 1: Location on Related Entity
```
Query: "Active deals for office properties in Dallas"
Problem: Deal has no City field; City is on Property
Required: Deal.ascendix__Property__c → Property.ascendix__City__c = "Dallas"
```

#### Case 2: Multi-Hop Traversal
```
Query: "Deals for available space in Dallas"
Problem: Need to traverse Deal → Availability → Property → City
Required: Two-hop traversal with filter on leaf node
```

#### Case 3: Role-Based Queries
```
Query: "Brokers with active listings in Austin"
Problem: Broker (User) → Listing → Property → City
Required: Role resolution + multi-hop + location filter
```

### 2.3 Why Pattern Matching Won't Scale

To handle all variations of location-based deal queries alone:
- "deals in Dallas"
- "deals for properties in Dallas"
- "deals for office properties in Dallas"
- "active deals for office properties in Dallas"
- "open deals on office buildings in Dallas TX"
- "Dallas office deals"
- "office deals in the Dallas area"
- ... hundreds more variations

**LLM-based decomposition handles ALL variations with ONE schema document.**

---

## 3. Solution Overview

### 3.1 Approach: LLM-Based Query Decomposition + Schema-Aware Prompting

Add a pre-processing step before retrieval that uses an LLM to decompose natural language queries into structured query plans.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        NEW: Query Decomposition Layer               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  User Query ──► LLM + Schema Context ──► Structured Query Plan     │
│                                                                     │
│  "Active deals for office properties in Dallas"                     │
│                           │                                         │
│                           ▼                                         │
│  {                                                                  │
│    "target_entity": "ascendix__Deal__c",                           │
│    "target_filters": {"ascendix__Status__c": "Active"},            │
│    "related_entities": [{                                          │
│      "entity": "ascendix__Property__c",                            │
│      "filters": {                                                  │
│        "ascendix__City__c": "Dallas",                              │
│        "ascendix__PropertySubType__c": "Office"                    │
│      }                                                              │
│    }],                                                              │
│    "traversal_paths": [                                            │
│      "Deal.ascendix__Property__c → Property",                      │
│      "Deal.ascendix__Availability__c → Availability → Property"   │
│    ]                                                                │
│  }                                                                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    EXISTING: Graph-Aware Retrieval                  │
├─────────────────────────────────────────────────────────────────────┤
│  1. Vector search for Properties (City=Dallas, Type=Office)        │
│  2. Graph traversal: Property → Deal (reverse edges)               │
│  3. Filter Deals by Status=Active                                   │
│  4. Return merged results                                           │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Why This Approach

| Benefit | Description |
|---------|-------------|
| **Handles Novel Queries** | LLM can reason about queries never seen before |
| **Single Point of Maintenance** | One schema document vs. hundreds of regex patterns |
| **Leverages Existing Infrastructure** | Bedrock already available; graph traversal already works |
| **Scales to Complexity** | 4-hop queries work the same as 1-hop queries |
| **Self-Documenting** | Schema document serves as training data AND documentation |

### 3.3 Performance Considerations

- **Model Choice:** Claude Haiku for decomposition (~$0.25/million tokens)
- **Latency Budget:** <200ms for decomposition step
- **Caching:** Cache decomposition results for repeated queries
- **Fallback:** If decomposition fails, fall back to current pattern-based routing

---

## 4. Data Model Schema Document

This schema document is the "training data" for the LLM. It must be comprehensive, accurate, and maintained as the data model evolves.

### 4.1 Object Relationship Diagram

```
                                    ┌─────────────┐
                                    │   Market    │
                                    └──────▲──────┘
                                           │
┌─────────────┐    ┌─────────────┐   ┌─────┴───────┐    ┌─────────────┐
│   Broker    │◄───│   Listing   │◄──│  Property   │───►│  Submarket  │
│   (User)    │    └──────┬──────┘   └──────┬──────┘    └─────────────┘
└─────────────┘           │                 │
                          │           ┌─────▼───────┐
                          │           │ Availability│
                          │           └─────┬───────┘
                          │                 │
                          ▼                 ▼
                    ┌─────────────────────────────┐
                    │            Deal             │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
              ┌─────────┐   ┌───────────┐   ┌─────────┐
              │ Tenant  │   │  Landlord │   │  Lease  │
              │(Account)│   │ (Account) │   └────┬────┘
              └─────────┘   └───────────┘        │
                                                 ▼
                                           ┌───────────┐
                                           │   Sale    │
                                           └───────────┘
```

### 4.2 Object Definitions

```yaml
# =============================================================================
# CRE Data Model Schema for Query Interpretation
# Version: 1.0
# Last Updated: 2024-11-28
# =============================================================================

objects:

  # ---------------------------------------------------------------------------
  # DEAL
  # ---------------------------------------------------------------------------
  ascendix__Deal__c:
    display_name: "Deal"
    description: "Represents a real estate transaction or opportunity"

    key_fields:
      ascendix__Status__c:
        type: picklist
        description: "Deal status"
        values: [Active, Closed Won, Closed Lost, Pipeline, Pending, On Hold]

      ascendix__SalesStage__c:
        type: picklist
        description: "Sales pipeline stage"
        values: [Prospecting, Qualification, Proposal, Negotiation, Closed]

      ascendix__GrossFeeAmount__c:
        type: currency
        description: "Commission/fee amount"

      ascendix__DealSubType__c:
        type: picklist
        description: "Type of deal"
        values: [Lease, Sale, Sublease, Renewal, Expansion]

      ascendix__CloseDate__c:
        type: date
        description: "Expected or actual close date"

    relationships:
      ascendix__Property__c:
        target: ascendix__Property__c
        type: lookup
        description: "Direct link to property involved in deal"
        traversal: "Use this to find deals for a specific property"

      ascendix__Availability__c:
        target: ascendix__Availability__c
        type: lookup
        description: "Link to specific available space"
        traversal: "Use this for deals on specific available spaces; also traverse to Property"

      ascendix__Tenant__c:
        target: Account
        type: lookup
        description: "The tenant in a lease deal"

      ascendix__Client__c:
        target: Account
        type: lookup
        description: "The client/customer for this deal"

      ascendix__Buyer__c:
        target: Account
        type: lookup
        description: "Buyer in a sale deal"

      ascendix__Seller__c:
        target: Account
        type: lookup
        description: "Seller in a sale deal"

      ascendix__OwnerLandlord__c:
        target: Account
        type: lookup
        description: "Property owner/landlord"

      OwnerId:
        target: User
        type: lookup
        description: "Broker/agent who owns this deal"

    important_notes:
      - "Deals do NOT have location fields (City, State, Address)"
      - "Location information must come from related Property"
      - "To find 'deals in Dallas', traverse Deal → Property → City"

  # ---------------------------------------------------------------------------
  # PROPERTY
  # ---------------------------------------------------------------------------
  ascendix__Property__c:
    display_name: "Property"
    description: "Represents a real estate property or building"

    location_fields:
      ascendix__City__c:
        type: text
        description: "City name"
        examples: ["Dallas", "Houston", "Austin", "San Antonio"]

      ascendix__State__c:
        type: text
        description: "State abbreviation"
        examples: ["TX", "CA", "NY", "FL"]

      ascendix__Address__c:
        type: text
        description: "Street address"

      ascendix__PostalCode__c:
        type: text
        description: "ZIP/postal code"

    classification_fields:
      ascendix__PropertySubType__c:
        type: picklist
        description: "Property type"
        values: [Office, Retail, Industrial, Warehouse, Multifamily, Land, Mixed Use]
        synonyms:
          office: ["office", "office building", "office space", "office tower"]
          retail: ["retail", "shopping", "strip mall", "shopping center"]
          industrial: ["industrial", "warehouse", "distribution", "manufacturing"]
          multifamily: ["multifamily", "apartment", "residential"]

      ascendix__PropertyClass__c:
        type: picklist
        description: "Building class/quality"
        values: [Class A, Class B, Class C]
        synonyms:
          class_a: ["class a", "class-a", "A class", "trophy"]
          class_b: ["class b", "class-b", "B class"]
          class_c: ["class c", "class-c", "C class"]

      ascendix__TotalSquareFeet__c:
        type: number
        description: "Total building size in square feet"

    relationships:
      ascendix__Market__c:
        target: ascendix__Market__c
        type: lookup
        description: "Market/metro area"

      ascendix__Submarket__c:
        target: ascendix__Submarket__c
        type: lookup
        description: "Submarket within the market"

      ascendix__OwnerLandlord__c:
        target: Account
        type: lookup
        description: "Property owner"

      ascendix__PropertyManager__c:
        target: Account
        type: lookup
        description: "Property management company"

      OwnerId:
        target: User
        type: lookup
        description: "Broker/agent responsible for this property"

    child_relationships:
      - "Availability records (available spaces within this property)"
      - "Listing records (active listings for this property)"
      - "Lease records (leases at this property)"
      - "Deal records (deals involving this property)"

  # ---------------------------------------------------------------------------
  # AVAILABILITY
  # ---------------------------------------------------------------------------
  ascendix__Availability__c:
    display_name: "Availability"
    alternate_names: ["Available Space", "Space", "Suite", "Unit"]
    description: "Represents available space within a property"

    key_fields:
      ascendix__Status__c:
        type: picklist
        description: "Availability status"
        values: [Available, Under LOI, Leased, Off Market]

      ascendix__SquareFeet__c:
        type: number
        description: "Size of available space in square feet"

      ascendix__AskingRate__c:
        type: currency
        description: "Asking lease rate"

      ascendix__LeaseType__c:
        type: picklist
        description: "Type of lease"
        values: [NNN, Full Service, Modified Gross, Gross]

    relationships:
      ascendix__Property__c:
        target: ascendix__Property__c
        type: lookup
        required: true
        description: "Parent property"
        traversal: "ALWAYS traverse to Property for location/type filters"

      ascendix__Floor__c:
        target: ascendix__Floor__c
        type: lookup
        description: "Floor within the building"

      ascendix__Listing__c:
        target: ascendix__Listing__c
        type: lookup
        description: "Associated listing"

    important_notes:
      - "Availability INHERITS location from parent Property"
      - "To find 'available space in Dallas', traverse Availability → Property → City"
      - "Size filters (sqft) apply directly to Availability"

  # ---------------------------------------------------------------------------
  # LEASE
  # ---------------------------------------------------------------------------
  ascendix__Lease__c:
    display_name: "Lease"
    description: "Represents a lease agreement"

    key_fields:
      ascendix__LeaseType__c:
        type: picklist
        description: "Type of lease"
        values: [NNN, Full Service, Modified Gross, Gross]

      ascendix__TermCommencementDate__c:
        type: date
        description: "Lease start date"

      ascendix__TermExpirationDate__c:
        type: date
        description: "Lease end date"
        temporal_queries:
          expiring: "TermExpirationDate within next 6-12 months"
          expired: "TermExpirationDate < today"
          active: "TermCommencementDate <= today AND TermExpirationDate >= today"

      ascendix__RentPerSqFt__c:
        type: currency
        description: "Rent rate per square foot"

      ascendix__LeasedSquareFeet__c:
        type: number
        description: "Total leased square footage"

    relationships:
      ascendix__Property__c:
        target: ascendix__Property__c
        type: lookup
        description: "Property where lease is located"

      ascendix__Tenant__c:
        target: Account
        type: lookup
        description: "Tenant company"

      ascendix__OwnerLandlord__c:
        target: Account
        type: lookup
        description: "Landlord/owner"

      ascendix__OriginatingDeal__c:
        target: ascendix__Deal__c
        type: lookup
        description: "Deal that created this lease"

  # ---------------------------------------------------------------------------
  # LISTING
  # ---------------------------------------------------------------------------
  ascendix__Listing__c:
    display_name: "Listing"
    description: "Represents an active property listing"

    key_fields:
      ascendix__Status__c:
        type: picklist
        description: "Listing status"
        values: [Active, Pending, Closed, Expired, Withdrawn]

      ascendix__ListingType__c:
        type: picklist
        description: "Type of listing"
        values: [For Lease, For Sale, For Sublease]

    relationships:
      ascendix__Property__c:
        target: ascendix__Property__c
        type: lookup
        description: "Property being listed"

      OwnerId:
        target: User
        type: lookup
        description: "Listing broker/agent"
        traversal: "Use this to find brokers with listings"

  # ---------------------------------------------------------------------------
  # SALE
  # ---------------------------------------------------------------------------
  ascendix__Sale__c:
    display_name: "Sale"
    description: "Represents a completed property sale"

    key_fields:
      ascendix__SalePrice__c:
        type: currency
        description: "Sale price"

      ascendix__SaleDate__c:
        type: date
        description: "Date of sale"

      ascendix__PricePerSqFt__c:
        type: currency
        description: "Price per square foot"

    relationships:
      ascendix__Property__c:
        target: ascendix__Property__c
        type: lookup
        description: "Property that was sold"

      ascendix__Buyer__c:
        target: Account
        type: lookup
        description: "Buyer"

      ascendix__Seller__c:
        target: Account
        type: lookup
        description: "Seller"

      ascendix__OriginatingDeal__c:
        target: ascendix__Deal__c
        type: lookup
        description: "Deal that resulted in this sale"

  # ---------------------------------------------------------------------------
  # MARKET & SUBMARKET
  # ---------------------------------------------------------------------------
  ascendix__Market__c:
    display_name: "Market"
    description: "Metro area or major market"
    key_fields:
      Name:
        type: text
        description: "Market name"
        examples: ["DFW", "Houston", "Austin", "San Antonio"]

  ascendix__Submarket__c:
    display_name: "Submarket"
    description: "Submarket within a metro area"
    key_fields:
      Name:
        type: text
        description: "Submarket name"
        examples: ["Uptown", "Downtown", "CBD", "North Dallas", "Galleria"]
    relationships:
      ascendix__Market__c:
        target: ascendix__Market__c
        type: lookup
        description: "Parent market"

  # ---------------------------------------------------------------------------
  # ACCOUNT (Tenant, Landlord, Company)
  # ---------------------------------------------------------------------------
  Account:
    display_name: "Account"
    alternate_names: ["Company", "Tenant", "Landlord", "Client"]
    description: "Represents a company that can be a tenant, landlord, client, etc."

    key_fields:
      Name:
        type: text
        description: "Company name"

      Industry:
        type: picklist
        description: "Industry classification"

      BillingCity:
        type: text
        description: "Company headquarters city"

      BillingState:
        type: text
        description: "Company headquarters state"

    relationships:
      ParentId:
        target: Account
        type: lookup
        description: "Parent company"

  # ---------------------------------------------------------------------------
  # USER (Broker, Agent)
  # ---------------------------------------------------------------------------
  User:
    display_name: "User"
    alternate_names: ["Broker", "Agent", "Rep"]
    description: "Represents a broker or agent in the system"

    key_fields:
      Name:
        type: text
        description: "Full name"

      Email:
        type: email
        description: "Email address"

      City:
        type: text
        description: "User's city"

    important_notes:
      - "Users own Deals, Properties, Listings via OwnerId field"
      - "To find 'brokers in Dallas with listings', traverse Listing.OwnerId → User"

# =============================================================================
# COMMON QUERY PATTERNS
# =============================================================================

query_patterns:

  location_on_related_entity:
    description: "When location filter applies to a related entity, not the target"
    examples:
      - query: "Deals in Dallas"
        wrong: "Search Deal records for 'Dallas'"
        right: "Traverse Deal → Property, filter Property.City = Dallas"
      - query: "Available space in Houston"
        wrong: "Search Availability for 'Houston'"
        right: "Traverse Availability → Property, filter Property.City = Houston"
    rule: "Location filters (city, state, market, submarket) almost always apply to Property"

  type_on_related_entity:
    description: "When property type filter applies to a related entity"
    examples:
      - query: "Office deals"
        wrong: "Search Deal records for 'office'"
        right: "Traverse Deal → Property, filter Property.PropertySubType = Office"
      - query: "Industrial leases"
        wrong: "Search Lease for 'industrial'"
        right: "Traverse Lease → Property, filter Property.PropertySubType = Industrial"
    rule: "Property type filters (office, retail, industrial) apply to Property, not Deal/Lease"

  multi_hop_traversal:
    description: "When target entity is 2+ hops from filter entity"
    examples:
      - query: "Deals for available space in Dallas"
        path: "Deal → Availability → Property (City=Dallas)"
      - query: "Contacts for tenants at Class A buildings"
        path: "Contact → Account(Tenant) → Lease → Property (Class=A)"
    rule: "Identify all entities mentioned and map the shortest traversal path"

  role_resolution:
    description: "When query mentions roles that map to User or Account"
    mappings:
      broker: "User (via OwnerId on Deal, Listing, Property)"
      agent: "User (via OwnerId)"
      tenant: "Account (via Tenant__c lookup)"
      landlord: "Account (via OwnerLandlord__c lookup)"
      owner: "Account (via OwnerLandlord__c) or User (via OwnerId)"
      client: "Account (via Client__c lookup)"

  temporal_filters:
    description: "Time-based query patterns"
    mappings:
      active_deals: "ascendix__Status__c = 'Active'"
      closed_deals: "ascendix__Status__c IN ('Closed Won', 'Closed Lost')"
      expiring_leases: "ascendix__TermExpirationDate__c within next 6 months"
      new_listings: "CreatedDate within last 7 days"
      this_quarter: "Date within current fiscal quarter"
      last_year: "Date within previous 12 months"
```

---

## 5. Query Categories & Examples

### 5.1 Query Tier Classification

| Tier | Description | Complexity | Examples |
|------|-------------|------------|----------|
| **Tier 1** | Single entity with filters on related entity | 1-hop traversal | Properties in Dallas with available space |
| **Tier 2** | Target entity filtered by attributes across 2+ hops | Multi-hop traversal | Brokers with active listings in Dallas |
| **Tier 3** | Analytical queries with aggregation or time-series | Aggregation + computation | Lease rate trends over 36 months |

### 5.2 Category A: Location-Based Queries
*Filter by geographic attributes that live on Property*

| ID | Query | Target | Filter Entity | Filter Fields | Traversal |
|----|-------|--------|---------------|---------------|-----------|
| A1 | "Properties in Dallas" | Property | - | City | Direct |
| A2 | "Deals for properties in Houston" | Deal | Property | City | Deal → Property |
| A3 | "Available space in the DFW market" | Availability | Property → Market | Market.Name | Availability → Property → Market |
| A4 | "Leases in the Uptown submarket" | Lease | Property → Submarket | Submarket.Name | Lease → Property → Submarket |
| A5 | "Brokers with listings in Austin" | User | Listing → Property | City | Listing.OwnerId → User, Listing → Property |

**Example Decomposition (A2):**
```yaml
Query ID: A2
Natural Language: "Deals for properties in Houston"
Tier: 1

Target Entity: ascendix__Deal__c
Target Filters: none

Related Entity Filters:
  - Entity: ascendix__Property__c
    Relationship: Deal.ascendix__Property__c
    Filters:
      - Field: ascendix__City__c
        Operator: equals
        Value: "Houston"

Traversal Paths:
  - "Deal.ascendix__Property__c → Property"
  - "Deal.ascendix__Availability__c → Availability.ascendix__Property__c → Property"

Search Strategy:
  1. Find Properties where City = "Houston"
  2. Traverse Property → Deal (reverse) via ascendix__Property__c
  3. Also find Availabilities at those Properties
  4. Traverse Availability → Deal via ascendix__Availability__c

Variations:
  - "Houston deals"
  - "Deals in Houston"
  - "What deals are in Houston"
  - "Show me deals for Houston properties"
```

### 5.3 Category B: Property Type Queries
*Filter by property classification*

| ID | Query | Target | Filter Entity | Filter Fields |
|----|-------|--------|---------------|---------------|
| B1 | "Office properties in Dallas" | Property | - | PropertySubType, City |
| B2 | "Class A buildings" | Property | - | PropertyClass |
| B3 | "Deals for industrial properties" | Deal | Property | PropertySubType |
| B4 | "Available retail space" | Availability | Property | PropertySubType |
| B5 | "Warehouse leases in Houston" | Lease | Property | PropertySubType, City |

**Example Decomposition (B3):**
```yaml
Query ID: B3
Natural Language: "Deals for industrial properties"
Tier: 1

Target Entity: ascendix__Deal__c
Target Filters: none

Related Entity Filters:
  - Entity: ascendix__Property__c
    Relationship: Deal.ascendix__Property__c
    Filters:
      - Field: ascendix__PropertySubType__c
        Operator: in
        Value: ["Industrial", "Warehouse"]

Traversal Paths:
  - "Deal.ascendix__Property__c → Property"

Search Strategy:
  1. Find Properties where PropertySubType IN (Industrial, Warehouse)
  2. Traverse Property → Deal (reverse)

Variations:
  - "Industrial deals"
  - "Warehouse property deals"
  - "Deals on industrial buildings"
```

### 5.4 Category C: Numeric/Size Filters
*Filters involving numeric comparisons*

| ID | Query | Target | Filter Entity | Filter Fields |
|----|-------|--------|---------------|---------------|
| C1 | "Properties over 100,000 sqft" | Property | - | TotalSquareFeet > 100000 |
| C2 | "Available space between 5,000-10,000 sqft" | Availability | - | SquareFeet BETWEEN 5000 AND 10000 |
| C3 | "Deals over $1M gross fee" | Deal | - | GrossFeeAmount > 1000000 |
| C4 | "Leases with rent above $25/sqft" | Lease | - | RentPerSqFt > 25 |
| C5 | "Properties with more than 3 available spaces" | Property | Availability | COUNT(Availability) > 3 |

**Example Decomposition (C2):**
```yaml
Query ID: C2
Natural Language: "Available space between 5,000-10,000 sqft"
Tier: 1

Target Entity: ascendix__Availability__c
Target Filters:
  - Field: ascendix__SquareFeet__c
    Operator: between
    Value: [5000, 10000]

Related Entity Filters: none

Traversal Paths: none (direct query)

Search Strategy:
  1. Find Availabilities where SquareFeet BETWEEN 5000 AND 10000
  2. Return matching Availability records

Variations:
  - "Spaces 5000 to 10000 square feet"
  - "Available suites around 5-10k sf"
  - "Medium-sized available spaces"
```

### 5.5 Category D: Status/Stage Filters
*Filters by lifecycle status*

| ID | Query | Target | Filter Entity | Filter Fields |
|----|-------|--------|---------------|---------------|
| D1 | "Active deals" | Deal | - | Status = Active |
| D2 | "Properties with active listings" | Property | Listing | Listing.Status = Active |
| D3 | "Expiring leases" | Lease | - | TermExpirationDate < 6 months |
| D4 | "Closed deals this quarter" | Deal | - | Status = Closed, CloseDate in Q |
| D5 | "Available spaces not under LOI" | Availability | - | Status != Under LOI |

### 5.6 Category E: Person/Role Queries
*Queries involving brokers, owners, managers*

| ID | Query | Target | Filter Entity | Filter Fields |
|----|-------|--------|---------------|---------------|
| E1 | "Brokers in Dallas with active listings" | User | Listing → Property | City, Listing.Status |
| E2 | "Properties managed by ABC Company" | Property | - | PropertyManager = ABC |
| E3 | "Deals where John Smith is the broker" | Deal | - | OwnerId = John Smith |
| E4 | "Tenants at properties owned by XYZ REIT" | Account | Lease → Property | OwnerLandlord = XYZ |
| E5 | "Landlords with expiring leases" | Account | Lease | TermExpirationDate < 6 months |

**Example Decomposition (E1):**
```yaml
Query ID: E1
Natural Language: "Brokers in Dallas with active listings"
Tier: 2

Target Entity: User
Target Filters:
  - Field: City
    Operator: equals
    Value: "Dallas"
    Note: "This is broker's location, may also want listing location"

Related Entity Filters:
  - Entity: ascendix__Listing__c
    Relationship: Listing.OwnerId → User
    Filters:
      - Field: ascendix__Status__c
        Operator: equals
        Value: "Active"
  - Entity: ascendix__Property__c
    Relationship: Listing.ascendix__Property__c → Property
    Filters:
      - Field: ascendix__City__c
        Operator: equals
        Value: "Dallas"
        Note: "Listings in Dallas, not just brokers based in Dallas"

Traversal Paths:
  - "Listing.OwnerId → User"
  - "Listing.ascendix__Property__c → Property"

Search Strategy:
  1. Find Listings where Status = Active
  2. Join to Property, filter by City = Dallas
  3. Get unique User IDs from Listing.OwnerId
  4. Return matching Users

Ambiguity Note:
  "in Dallas" could mean:
  a) Brokers located in Dallas (User.City)
  b) Brokers with listings on Dallas properties (Listing → Property.City)
  Recommend interpretation (b) unless user specifies "based in Dallas"
```

### 5.7 Category F: Multi-Hop Relationship Queries
*Queries requiring 2+ traversals*

| ID | Query | Target | Traversal Path |
|----|-------|--------|----------------|
| F1 | "Deals for tenants at properties in Dallas" | Deal | Property(City=Dallas) → Lease → Tenant → Deal(Tenant) |
| F2 | "Contacts for landlords of Class A buildings" | Contact | Property(Class=A) → Landlord(Account) → Contact |
| F3 | "Brokers with deals for tenants in tech industry" | User | Account(Industry=Tech) → Deal(Tenant) → User(Owner) |
| F4 | "Properties where deals closed this year for retail tenants" | Property | Deal(CloseDate, Tenant.Industry=Retail) → Property |

### 5.8 Category G: Compound Filters (AND/OR)
*Multiple filter conditions*

| ID | Query | Conditions |
|----|-------|------------|
| G1 | "Class A office in Dallas or Houston" | (Class=A AND Type=Office) AND (City=Dallas OR City=Houston) |
| G2 | "Active deals over $500K for industrial properties" | Status=Active AND GrossFee>500K AND PropertyType=Industrial |
| G3 | "Available space in CBD that's either retail or office" | Submarket=CBD AND (Type=Retail OR Type=Office) |
| G4 | "Expiring leases for Class A or B office in DFW market" | LeaseExpiring AND Class IN (A,B) AND Type=Office AND Market=DFW |

**Example Decomposition (G2):**
```yaml
Query ID: G2
Natural Language: "Active deals over $500K for industrial properties"
Tier: 1

Target Entity: ascendix__Deal__c
Target Filters:
  - Field: ascendix__Status__c
    Operator: equals
    Value: "Active"
  - Field: ascendix__GrossFeeAmount__c
    Operator: greater_than
    Value: 500000

Related Entity Filters:
  - Entity: ascendix__Property__c
    Relationship: Deal.ascendix__Property__c
    Filters:
      - Field: ascendix__PropertySubType__c
        Operator: in
        Value: ["Industrial", "Warehouse"]

Traversal Paths:
  - "Deal.ascendix__Property__c → Property"

Search Strategy:
  1. Find Properties where PropertySubType IN (Industrial, Warehouse)
  2. Find Deals where Property IN (step 1 results)
  3. Filter Deals where Status = Active AND GrossFeeAmount > 500000
  4. Return matching Deals

Filter Order Optimization:
  Most selective filter first: GrossFeeAmount > 500K (likely smallest result set)
```

### 5.9 Category H: Temporal Queries
*Time-based filters*

| ID | Query | Time Dimension |
|----|-------|----------------|
| H1 | "Deals closed in Q4 2024" | CloseDate BETWEEN 2024-10-01 AND 2024-12-31 |
| H2 | "Leases expiring in the next 6 months" | TermExpirationDate BETWEEN today AND today+180 |
| H3 | "New listings this week" | CreatedDate >= 7 days ago |
| H4 | "Properties sold in the last 2 years" | Sale.SaleDate >= 2 years ago |
| H5 | "Deals closed this quarter" | CloseDate in current quarter |

### 5.10 Category I: Aggregation Queries (Tier 2-3)
*Counts, sums, averages*

| ID | Query | Aggregation Type | Complexity |
|----|-------|------------------|------------|
| I1 | "How many active deals in Dallas" | COUNT(Deal) WHERE Status=Active, Property.City=Dallas | Tier 2 |
| I2 | "Total square feet available in Uptown" | SUM(Availability.SquareFeet) WHERE Property.Submarket=Uptown | Tier 2 |
| I3 | "Average lease rate for Class A office" | AVG(Lease.RentPerSqFt) WHERE Property.Class=A, Type=Office | Tier 2 |
| I4 | "Top 10 deals by gross fee this year" | TOP 10 Deal ORDER BY GrossFeeAmount DESC WHERE CloseDate in year | Tier 2 |
| I5 | "Vacancy rate by submarket" | (SUM(Available)/SUM(Total)) GROUP BY Submarket | Tier 3 |

### 5.11 Category J: Trend/Analytical Queries (Tier 3)
*Time-series analysis*

| ID | Query | Analysis Type | Data Required |
|----|-------|---------------|---------------|
| J1 | "Lease rate trends for Class A office in Dallas over 36 months" | Time series | Lease.RentPerSqFt, Lease.CommencementDate, Property filters |
| J2 | "How has vacancy changed in the CBD since 2022" | Trend comparison | Availability snapshots over time |
| J3 | "Deal volume by quarter for the last 2 years" | Periodic aggregation | Deal.CloseDate, COUNT by quarter |
| J4 | "Compare lease rates between Uptown and Downtown" | Comparative analysis | Lease.RentPerSqFt grouped by Submarket |
| J5 | "Which submarkets are trending up for industrial" | Trend ranking | Multiple metrics over time |

**Note:** Tier 3 queries require additional infrastructure:
- Historical data snapshots
- Time-series storage
- Aggregation pipeline
- Visualization support

---

## 6. Implementation Phases

### Phase 1: Foundation (Tier 1 Queries)
**Scope:** Single entity + 1-hop filter queries
**Categories:** A, B, C, D (location, type, numeric, status filters)

**Deliverables:**
1. Schema document v1.0 (objects, fields, relationships)
2. Query decomposition Lambda function
3. Integration with existing graph retriever
4. Test suite with 40+ examples from Categories A-D

**Success Criteria:**
- 90% accuracy on Tier 1 query decomposition
- <200ms added latency for decomposition
- All Category A-D test cases passing

### Phase 2: Multi-Hop & Role Queries (Tier 2)
**Scope:** Multi-hop traversal, person/role resolution, compound filters
**Categories:** E, F, G, H

**Deliverables:**
1. Extended schema document with role mappings
2. Multi-hop traversal planning
3. Compound filter (AND/OR) support
4. Temporal filter handling
5. Test suite with 30+ examples from Categories E-H

**Success Criteria:**
- 85% accuracy on Tier 2 query decomposition
- Correct traversal path selection for 2-3 hop queries
- Role resolution working for broker, tenant, landlord queries

### Phase 3: Aggregation & Analytics (Tier 3)
**Scope:** Aggregation, trends, time-series analysis
**Categories:** I, J

**Deliverables:**
1. Aggregation query detection and planning
2. Time-series data model (if not already present)
3. Trend calculation pipeline
4. Comparative analysis support
5. Test suite with 20+ examples from Categories I-J

**Success Criteria:**
- Correct aggregation type detection
- Accurate trend calculations
- Sub-second response for simple aggregations

### Phase Summary

| Phase | Categories | Example Count | Timeline |
|-------|------------|---------------|----------|
| Phase 1 | A, B, C, D | 40+ | 4-6 weeks |
| Phase 2 | E, F, G, H | 30+ | 4-6 weeks |
| Phase 3 | I, J | 20+ | 6-8 weeks |

---

## 7. Technical Architecture

### 7.1 New Component: Query Decomposition Lambda

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Query Decomposition Lambda                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Input:                                                             │
│  {                                                                  │
│    "query": "Active deals for office properties in Dallas",        │
│    "salesforceUserId": "005xxx",                                    │
│    "sessionId": "uuid"                                              │
│  }                                                                  │
│                                                                     │
│  Processing:                                                        │
│  1. Load schema document from cache/S3                              │
│  2. Build decomposition prompt                                      │
│  3. Call Bedrock (Claude Haiku)                                     │
│  4. Parse JSON response                                             │
│  5. Validate against schema                                         │
│  6. Return structured query plan                                    │
│                                                                     │
│  Output:                                                            │
│  {                                                                  │
│    "target_entity": "ascendix__Deal__c",                           │
│    "target_filters": [...],                                         │
│    "related_entities": [...],                                       │
│    "traversal_paths": [...],                                        │
│    "search_order": [...],                                           │
│    "decomposition_confidence": 0.95                                 │
│  }                                                                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.2 Integration with Existing Retrieve Lambda

```
┌──────────────┐     ┌─────────────────┐     ┌────────────────────┐
│   /answer    │────►│  Decomposition  │────►│     /retrieve      │
│   endpoint   │     │     Lambda      │     │     (modified)     │
└──────────────┘     └─────────────────┘     └────────────────────┘
                                                      │
                            ┌─────────────────────────┼─────────────────────────┐
                            │                         │                         │
                            ▼                         ▼                         ▼
                     ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
                     │   Vector    │          │    Graph    │          │   Filter    │
                     │   Search    │          │  Traversal  │          │   Apply     │
                     │(seed entity)│          │ (from seeds)│          │  (target)   │
                     └─────────────┘          └─────────────┘          └─────────────┘
```

### 7.3 Decomposition Prompt Template

```
You are a query planner for a commercial real estate CRM system.

Given the data model schema below and a user query, decompose the query into a structured query plan.

<schema>
{schema_document}
</schema>

<query>
{user_query}
</query>

Respond with a JSON object containing:

1. "target_entity": The Salesforce object API name the user wants to find (e.g., "ascendix__Deal__c")

2. "target_filters": Array of filters that apply directly to the target entity
   Each filter: {"field": "API_name", "operator": "equals|in|greater_than|less_than|between|contains", "value": "..."}

3. "related_entities": Array of related entities with filters that require traversal
   Each: {
     "entity": "API_name",
     "relationship_field": "field that connects to target or intermediate entity",
     "filters": [same format as target_filters]
   }

4. "traversal_paths": Array of strings describing the traversal path from target to filter entities
   Example: "Deal.ascendix__Property__c → Property"

5. "search_order": Array describing optimal order to execute the search
   Example: ["Find Properties with filters", "Traverse to Deals", "Apply Deal filters"]

6. "confidence": Number 0-1 indicating confidence in the decomposition

Important rules:
- Location fields (City, State, Market, Submarket) are on Property, not Deal or Lease
- Property type fields (PropertySubType, PropertyClass) are on Property
- Status fields are on the object they describe (Deal.Status, Listing.Status, etc.)
- "Broker" maps to User via OwnerId
- "Tenant" maps to Account via Tenant__c lookups
- "Landlord" maps to Account via OwnerLandlord__c lookups

Respond ONLY with valid JSON, no additional text.
```

### 7.4 Caching Strategy

| Cache Type | TTL | Key | Storage |
|------------|-----|-----|---------|
| Schema Document | 1 hour | Static | S3 + Lambda memory |
| Query Decomposition | 5 minutes | Hash(query + userId) | DynamoDB |
| Common Query Patterns | 24 hours | Query template | DynamoDB |

### 7.5 Fallback Strategy

```python
def decompose_query(query, user_id):
    try:
        # Try LLM decomposition
        result = call_decomposition_lambda(query)
        if result.confidence >= 0.7:
            return result
    except Exception as e:
        log.warning(f"Decomposition failed: {e}")

    # Fall back to pattern-based intent router
    intent = legacy_intent_router.classify(query)
    return convert_intent_to_query_plan(intent)
```

---

## 8. Success Criteria

### 8.1 Accuracy Metrics

| Metric | Phase 1 Target | Phase 2 Target | Phase 3 Target |
|--------|----------------|----------------|----------------|
| Decomposition Accuracy | 90% | 85% | 80% |
| Correct Entity Detection | 95% | 92% | 90% |
| Correct Filter Extraction | 90% | 85% | 80% |
| Correct Traversal Path | 90% | 85% | 80% |
| End-to-End Retrieval Precision | 85% | 80% | 75% |

### 8.2 Performance Metrics

| Metric | Target | Maximum |
|--------|--------|---------|
| Decomposition Latency | 150ms | 300ms |
| Total Added Latency | 200ms | 400ms |
| Cache Hit Rate | 60% | - |

### 8.3 Business Metrics

| Metric | Baseline | Target |
|--------|----------|--------|
| User Satisfaction (query relevance) | TBD | +20% improvement |
| Zero-Result Queries | TBD | -50% reduction |
| Query Reformulation Rate | TBD | -30% reduction |

---

## 9. Test Cases

### 9.1 Test Case Template

```yaml
Test ID: TC-A2-001
Category: A (Location-Based)
Query: "Deals for properties in Houston"
Expected Decomposition:
  target_entity: ascendix__Deal__c
  target_filters: []
  related_entities:
    - entity: ascendix__Property__c
      relationship_field: ascendix__Property__c
      filters:
        - field: ascendix__City__c
          operator: equals
          value: Houston
  traversal_paths:
    - "Deal.ascendix__Property__c → Property"
  search_order:
    - "Find Properties where City = Houston"
    - "Traverse Property → Deal"
Expected Results:
  - Deals linked to properties in Houston via ascendix__Property__c
  - Deals linked to availabilities at Houston properties via ascendix__Availability__c
Variations:
  - "Houston deals" → Same decomposition
  - "Deals in Houston" → Same decomposition
  - "What deals are in Houston" → Same decomposition
```

### 9.2 Test Categories

| Category | Test Count | Priority |
|----------|------------|----------|
| A: Location | 10 | P0 |
| B: Property Type | 10 | P0 |
| C: Numeric | 8 | P1 |
| D: Status | 8 | P1 |
| E: Person/Role | 10 | P1 |
| F: Multi-Hop | 10 | P1 |
| G: Compound | 8 | P2 |
| H: Temporal | 8 | P2 |
| I: Aggregation | 10 | P2 |
| J: Trends | 8 | P3 |

### 9.3 Edge Case Tests

| ID | Description | Query | Expected Behavior |
|----|-------------|-------|-------------------|
| EC-001 | Ambiguous location | "Deals in Dallas" | Interpret as Property.City, not Deal text |
| EC-002 | Unknown entity | "Widgets in Houston" | Low confidence, fallback to vector search |
| EC-003 | Conflicting filters | "Active closed deals" | Detect contradiction, ask for clarification |
| EC-004 | Missing object | "Properties for XYZ tenant" | Handle when tenant doesn't exist |
| EC-005 | Synonym handling | "Warehouse" vs "Industrial" | Map to same PropertySubType |

---

## 10. Appendix

### 10.1 Glossary

| Term | Definition |
|------|------------|
| Query Decomposition | Breaking a natural language query into structured components |
| Target Entity | The Salesforce object the user wants to find/return |
| Filter Entity | A related entity whose attributes are used to filter results |
| Traversal Path | The relationship chain connecting target and filter entities |
| Seed Entity | The entity searched first to provide starting points for traversal |

### 10.2 Related Documents

- Phase 3 Graph Enhancement PRD
- Intent Router Design Document
- Graph Retriever Technical Specification
- Bedrock Knowledge Base Configuration

### 10.3 Open Questions

1. **Schema versioning:** How do we handle schema changes when the Salesforce data model is updated?
2. **Multi-tenant:** Should decomposition be tenant-specific (different field configurations)?
3. **Feedback loop:** How do we capture decomposition errors for model improvement?
4. **Cost monitoring:** What's the budget for decomposition LLM calls?

### 10.4 Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2024-11-28 | AI Search Team | Initial draft |

---

*End of Document*
