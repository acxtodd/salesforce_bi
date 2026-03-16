#!/usr/bin/env python3
"""
Seed Vocab Cache with CRE Terminology.

Populates the vocab_cache DynamoDB table with essential Commercial Real Estate
terminology for entity linking in the Planner.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 2.1, 2.2, 2.3**

Usage:
    python scripts/seed_vocab_cache.py [--dry-run]
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any

import boto3
from botocore.exceptions import ClientError

# Table name
VOCAB_CACHE_TABLE = os.environ.get("VOCAB_CACHE_TABLE", "salesforce-ai-search-vocab-cache")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")

# TTL: 30 days for seeded vocabulary (longer than normal 24h for auto-built)
DEFAULT_TTL_DAYS = 30

# Relevance scores by source
RELEVANCE_SCORES = {
    "seed": 0.7,  # Seeded vocabulary - higher than describe, lower than layout
    "picklist": 0.6,
    "recordtype": 0.8,
}


def get_cre_vocabulary() -> List[Dict[str, Any]]:
    """
    Get comprehensive CRE vocabulary for seeding.

    Returns vocabulary terms organized by:
    - Object names and aliases
    - Property types (RecordType values)
    - Property classes
    - Geographic terms
    - Status/stage values
    - Common CRE terminology
    """
    vocab = []

    # ==========================================================================
    # Object Names and Aliases
    # ==========================================================================
    object_terms = [
        # Property
        {"term": "property", "canonical": "ascendix__Property__c", "type": "object"},
        {"term": "properties", "canonical": "ascendix__Property__c", "type": "object"},
        {"term": "building", "canonical": "ascendix__Property__c", "type": "object"},
        {"term": "buildings", "canonical": "ascendix__Property__c", "type": "object"},

        # Availability
        {"term": "availability", "canonical": "ascendix__Availability__c", "type": "object"},
        {"term": "availabilities", "canonical": "ascendix__Availability__c", "type": "object"},
        {"term": "space", "canonical": "ascendix__Availability__c", "type": "object"},
        {"term": "spaces", "canonical": "ascendix__Availability__c", "type": "object"},
        {"term": "available space", "canonical": "ascendix__Availability__c", "type": "object"},

        # Lease
        {"term": "lease", "canonical": "ascendix__Lease__c", "type": "object"},
        {"term": "leases", "canonical": "ascendix__Lease__c", "type": "object"},
        {"term": "tenant", "canonical": "ascendix__Lease__c", "type": "object"},
        {"term": "tenants", "canonical": "ascendix__Lease__c", "type": "object"},

        # Deal
        {"term": "deal", "canonical": "ascendix__Deal__c", "type": "object"},
        {"term": "deals", "canonical": "ascendix__Deal__c", "type": "object"},
        {"term": "transaction", "canonical": "ascendix__Deal__c", "type": "object"},
        {"term": "transactions", "canonical": "ascendix__Deal__c", "type": "object"},

        # Sale
        {"term": "sale", "canonical": "ascendix__Sale__c", "type": "object"},
        {"term": "sales", "canonical": "ascendix__Sale__c", "type": "object"},

        # Account/Company
        {"term": "account", "canonical": "Account", "type": "object"},
        {"term": "accounts", "canonical": "Account", "type": "object"},
        {"term": "company", "canonical": "Account", "type": "object"},
        {"term": "companies", "canonical": "Account", "type": "object"},

        # Contact
        {"term": "contact", "canonical": "Contact", "type": "object"},
        {"term": "contacts", "canonical": "Contact", "type": "object"},
        {"term": "broker", "canonical": "Contact", "type": "object"},
        {"term": "brokers", "canonical": "Contact", "type": "object"},

        # Activity
        {"term": "activity", "canonical": "Task", "type": "object"},
        {"term": "activities", "canonical": "Task", "type": "object"},
        {"term": "task", "canonical": "Task", "type": "object"},
        {"term": "tasks", "canonical": "Task", "type": "object"},
        {"term": "event", "canonical": "Event", "type": "object"},
        {"term": "events", "canonical": "Event", "type": "object"},

        # Note
        {"term": "note", "canonical": "Note", "type": "object"},
        {"term": "notes", "canonical": "Note", "type": "object"},
    ]

    for t in object_terms:
        vocab.append({
            "vocab_key": f"object#{t['canonical']}",
            "term": t["term"].lower(),
            "canonical_value": t["canonical"],
            "source": "seed",
            "relevance_score": RELEVANCE_SCORES["seed"],
        })

    # ==========================================================================
    # Property Types (RecordType)
    # ==========================================================================
    property_types = [
        {"term": "office", "canonical": "Office", "field": "RecordType.Name"},
        {"term": "industrial", "canonical": "Industrial", "field": "RecordType.Name"},
        {"term": "retail", "canonical": "Retail", "field": "RecordType.Name"},
        {"term": "multifamily", "canonical": "Multifamily", "field": "RecordType.Name"},
        {"term": "multi-family", "canonical": "Multifamily", "field": "RecordType.Name"},
        {"term": "apartment", "canonical": "Multifamily", "field": "RecordType.Name"},
        {"term": "apartments", "canonical": "Multifamily", "field": "RecordType.Name"},
        {"term": "land", "canonical": "Land", "field": "RecordType.Name"},
        {"term": "warehouse", "canonical": "Industrial", "field": "RecordType.Name"},
        {"term": "flex", "canonical": "Flex", "field": "RecordType.Name"},
        {"term": "mixed use", "canonical": "Mixed Use", "field": "RecordType.Name"},
        {"term": "mixed-use", "canonical": "Mixed Use", "field": "RecordType.Name"},
        {"term": "hospitality", "canonical": "Hospitality", "field": "RecordType.Name"},
        {"term": "hotel", "canonical": "Hospitality", "field": "RecordType.Name"},
    ]

    for t in property_types:
        vocab.append({
            "vocab_key": f"recordtype#ascendix__Property__c",
            "term": t["term"].lower(),
            "canonical_value": t["canonical"],
            "field_name": t["field"],
            "source": "seed",
            "relevance_score": RELEVANCE_SCORES["recordtype"],
        })

    # ==========================================================================
    # Property Classes
    # ==========================================================================
    property_classes = [
        {"term": "class a", "canonical": "A", "field": "ascendix__PropertyClass__c"},
        {"term": "class-a", "canonical": "A", "field": "ascendix__PropertyClass__c"},
        {"term": "class b", "canonical": "B", "field": "ascendix__PropertyClass__c"},
        {"term": "class-b", "canonical": "B", "field": "ascendix__PropertyClass__c"},
        {"term": "class c", "canonical": "C", "field": "ascendix__PropertyClass__c"},
        {"term": "class-c", "canonical": "C", "field": "ascendix__PropertyClass__c"},
        {"term": "trophy", "canonical": "A", "field": "ascendix__PropertyClass__c"},
    ]

    for t in property_classes:
        vocab.append({
            "vocab_key": f"picklist#ascendix__Property__c",
            "term": t["term"].lower(),
            "canonical_value": t["canonical"],
            "field_name": t["field"],
            "source": "seed",
            "relevance_score": RELEVANCE_SCORES["picklist"],
        })

    # ==========================================================================
    # Deal/Sale Stages
    # ==========================================================================
    deal_stages = [
        {"term": "prospecting", "canonical": "Prospecting"},
        {"term": "qualification", "canonical": "Qualification"},
        {"term": "negotiation", "canonical": "Negotiation"},
        {"term": "due diligence", "canonical": "Due Diligence"},
        {"term": "under contract", "canonical": "Under Contract"},
        {"term": "closed", "canonical": "Closed"},
        {"term": "closed won", "canonical": "Closed Won"},
        {"term": "closed lost", "canonical": "Closed Lost"},
        {"term": "proposal", "canonical": "Proposal"},
        {"term": "active", "canonical": "Active"},
        {"term": "pending", "canonical": "Pending"},
    ]

    for obj in ["ascendix__Deal__c", "ascendix__Sale__c"]:
        for t in deal_stages:
            vocab.append({
                "vocab_key": f"picklist#{obj}",
                "term": t["term"].lower(),
                "canonical_value": t["canonical"],
                "field_name": "ascendix__Stage__c",
                "source": "seed",
                "relevance_score": RELEVANCE_SCORES["picklist"],
            })

    # ==========================================================================
    # Availability Status
    # ==========================================================================
    availability_status = [
        {"term": "available", "canonical": "Available"},
        {"term": "leased", "canonical": "Leased"},
        {"term": "pending", "canonical": "Pending"},
        {"term": "off market", "canonical": "Off Market"},
        {"term": "under construction", "canonical": "Under Construction"},
    ]

    for t in availability_status:
        vocab.append({
            "vocab_key": f"picklist#ascendix__Availability__c",
            "term": t["term"].lower(),
            "canonical_value": t["canonical"],
            "field_name": "ascendix__Status__c",
            "source": "seed",
            "relevance_score": RELEVANCE_SCORES["picklist"],
        })

    # ==========================================================================
    # Geographic Terms (Region Aliases)
    # ==========================================================================
    geo_terms = [
        # Texas
        {"term": "dfw", "canonical": "Dallas-Fort Worth", "type": "region"},
        {"term": "dallas-fort worth", "canonical": "Dallas-Fort Worth", "type": "region"},
        {"term": "austin", "canonical": "Austin", "type": "city"},
        {"term": "houston", "canonical": "Houston", "type": "city"},
        {"term": "san antonio", "canonical": "San Antonio", "type": "city"},
        {"term": "plano", "canonical": "Plano", "type": "city"},
        {"term": "frisco", "canonical": "Frisco", "type": "city"},
        {"term": "dallas", "canonical": "Dallas", "type": "city"},
        {"term": "fort worth", "canonical": "Fort Worth", "type": "city"},
        {"term": "texas", "canonical": "TX", "type": "state"},
        {"term": "tx", "canonical": "TX", "type": "state"},

        # Florida
        {"term": "miami", "canonical": "Miami", "type": "city"},
        {"term": "tampa", "canonical": "Tampa", "type": "city"},
        {"term": "orlando", "canonical": "Orlando", "type": "city"},
        {"term": "jacksonville", "canonical": "Jacksonville", "type": "city"},
        {"term": "florida", "canonical": "FL", "type": "state"},
        {"term": "fl", "canonical": "FL", "type": "state"},

        # Pacific Northwest
        {"term": "pnw", "canonical": "Pacific Northwest", "type": "region"},
        {"term": "pacific northwest", "canonical": "Pacific Northwest", "type": "region"},
        {"term": "seattle", "canonical": "Seattle", "type": "city"},
        {"term": "portland", "canonical": "Portland", "type": "city"},
        {"term": "washington", "canonical": "WA", "type": "state"},
        {"term": "wa", "canonical": "WA", "type": "state"},
        {"term": "oregon", "canonical": "OR", "type": "state"},
        {"term": "or", "canonical": "OR", "type": "state"},

        # Submarket types
        {"term": "downtown", "canonical": "Downtown", "type": "submarket"},
        {"term": "cbd", "canonical": "CBD", "type": "submarket"},
        {"term": "suburban", "canonical": "Suburban", "type": "submarket"},
        {"term": "midtown", "canonical": "Midtown", "type": "submarket"},
        {"term": "uptown", "canonical": "Uptown", "type": "submarket"},
    ]

    for t in geo_terms:
        field_name = {
            "city": "ascendix__City__c",
            "state": "ascendix__State__c",
            "region": "ascendix__Region__c",
            "submarket": "ascendix__SubMarket__c",  # Note: capital M
        }.get(t["type"], "ascendix__City__c")

        vocab.append({
            "vocab_key": f"geography#ascendix__Property__c",
            "term": t["term"].lower(),
            "canonical_value": t["canonical"],
            "field_name": field_name,
            "source": "seed",
            "relevance_score": RELEVANCE_SCORES["seed"],
        })

    # ==========================================================================
    # Common CRE Terminology (Field Labels)
    # ==========================================================================
    field_labels = [
        # Size fields
        {"term": "size", "canonical": "Size", "field": "ascendix__Size__c", "object": "ascendix__Availability__c"},
        {"term": "square feet", "canonical": "Size", "field": "ascendix__Size__c", "object": "ascendix__Availability__c"},
        {"term": "sqft", "canonical": "Size", "field": "ascendix__Size__c", "object": "ascendix__Availability__c"},
        {"term": "sf", "canonical": "Size", "field": "ascendix__Size__c", "object": "ascendix__Availability__c"},
        {"term": "rsf", "canonical": "RentableSize", "field": "ascendix__RentableSize__c", "object": "ascendix__Property__c"},

        # Vacancy
        {"term": "vacancy", "canonical": "Vacancy", "field": "ascendix__Vacancy__c", "object": "ascendix__Property__c"},
        {"term": "vacancy rate", "canonical": "VacancyRate", "field": "ascendix__VacancyRate__c", "object": "ascendix__Property__c"},
        {"term": "vacant", "canonical": "Vacancy", "field": "ascendix__Vacancy__c", "object": "ascendix__Property__c"},

        # Dates (verified field names as of 2025-12-14)
        {"term": "expiring", "canonical": "TermExpirationDate", "field": "ascendix__TermExpirationDate__c", "object": "ascendix__Lease__c"},
        {"term": "expiration", "canonical": "TermExpirationDate", "field": "ascendix__TermExpirationDate__c", "object": "ascendix__Lease__c"},
        {"term": "lease expiration", "canonical": "TermExpirationDate", "field": "ascendix__TermExpirationDate__c", "object": "ascendix__Lease__c"},
        {"term": "close date", "canonical": "CloseDateEstimated", "field": "ascendix__CloseDateEstimated__c", "object": "ascendix__Deal__c"},

        # Other common terms
        {"term": "rent", "canonical": "Rent", "field": "ascendix__Rent__c", "object": "ascendix__Availability__c"},
        {"term": "asking rent", "canonical": "AskingRent", "field": "ascendix__AskingRent__c", "object": "ascendix__Availability__c"},
        {"term": "ti", "canonical": "TI", "field": "ascendix__TI__c", "object": "ascendix__Availability__c"},
        {"term": "tenant improvement", "canonical": "TI", "field": "ascendix__TI__c", "object": "ascendix__Availability__c"},
    ]

    for t in field_labels:
        vocab.append({
            "vocab_key": f"label#{t['object']}",
            "term": t["term"].lower(),
            "canonical_value": t["canonical"],
            "field_name": t["field"],
            "source": "seed",
            "relevance_score": RELEVANCE_SCORES["seed"],
        })

    return vocab


def seed_vocab_cache(dry_run: bool = False) -> int:
    """
    Seed the vocab cache DynamoDB table.

    Args:
        dry_run: If True, print what would be done without actually writing

    Returns:
        Number of items written
    """
    vocab = get_cre_vocabulary()
    print(f"Generated {len(vocab)} vocabulary terms")

    if dry_run:
        print("\n[DRY RUN] Would write the following terms:")
        for v in vocab[:20]:
            print(f"  {v['vocab_key']}: {v['term']} -> {v['canonical_value']}")
        if len(vocab) > 20:
            print(f"  ... and {len(vocab) - 20} more")
        return 0

    # Connect to DynamoDB
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(VOCAB_CACHE_TABLE)

    # Calculate TTL
    ttl = int((datetime.now(timezone.utc) + timedelta(days=DEFAULT_TTL_DAYS)).timestamp())
    updated_at = datetime.now(timezone.utc).isoformat()

    # Write in batches
    written = 0
    try:
        with table.batch_writer() as batch:
            for v in vocab:
                item = {
                    "vocab_key": v["vocab_key"],
                    "term": v["term"],
                    "canonical_value": v["canonical_value"],
                    "source": v["source"],
                    "relevance_score": str(v["relevance_score"]),
                    "ttl": ttl,
                    "updated_at": updated_at,
                }
                if "field_name" in v:
                    item["field_name"] = v["field_name"]

                batch.put_item(Item=item)
                written += 1

        print(f"Successfully wrote {written} vocabulary terms to {VOCAB_CACHE_TABLE}")
        return written

    except ClientError as e:
        print(f"Error writing to DynamoDB: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description="Seed vocab cache with CRE terminology")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    args = parser.parse_args()

    try:
        count = seed_vocab_cache(dry_run=args.dry_run)
        if not args.dry_run:
            print(f"\nVocab cache seeded successfully with {count} terms")
    except Exception as e:
        print(f"Failed to seed vocab cache: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
