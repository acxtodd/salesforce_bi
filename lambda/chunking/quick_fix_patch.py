"""
Quick Fix Patch for Cross-Object Query Support
Date: 2025-11-25
Purpose: Add relationship context and temporal status to chunks

This patch can be integrated into the existing chunking Lambda
to immediately improve cross-object query performance.
"""

from datetime import datetime, timedelta
import re

def add_temporal_context(record, chunk_text):
    """
    Add computed temporal status to chunk text for time-based queries.
    """
    temporal_additions = []

    # Handle Lease expiration
    if record.get('sobject') == 'ascendix__Lease__c':
        exp_date_str = record.get('ascendix__TermExpirationDate__c')
        if exp_date_str:
            try:
                exp_date = datetime.fromisoformat(exp_date_str.replace('Z', '+00:00'))
                days_until = (exp_date - datetime.now()).days

                if days_until < 0:
                    status = "EXPIRED"
                    temporal_additions.append(f"Lease Status: EXPIRED ({abs(days_until)} days ago)")
                elif days_until <= 30:
                    status = "EXPIRING_THIS_MONTH"
                    temporal_additions.append(f"Lease Status: EXPIRING THIS MONTH ({days_until} days)")
                elif days_until <= 90:
                    status = "EXPIRING_SOON"
                    temporal_additions.append(f"Lease Status: EXPIRING SOON ({days_until} days)")
                else:
                    status = "ACTIVE"
                    temporal_additions.append(f"Lease Status: ACTIVE (expires in {days_until} days)")
            except:
                pass

    # Handle Deal age
    if record.get('sobject') == 'ascendix__Deal__c':
        created_date = record.get('CreatedDate')
        if created_date:
            try:
                created = datetime.fromisoformat(created_date.replace('Z', '+00:00'))
                days_old = (datetime.now() - created).days

                if days_old <= 7:
                    temporal_additions.append("Deal Age: NEW (this week)")
                elif days_old <= 30:
                    temporal_additions.append("Deal Age: RECENT (this month)")
                elif days_old <= 90:
                    temporal_additions.append("Deal Age: ACTIVE (last 3 months)")
            except:
                pass

    # Add temporal context to chunk
    if temporal_additions:
        chunk_text = chunk_text.rstrip() + "\n\n" + "\n".join(temporal_additions)

    return chunk_text


def add_relationship_context(record, chunk_text):
    """
    Add related object context to chunk text for cross-object queries.
    Note: In production, these values should be fetched from Salesforce.
    For quick fix, we'll add placeholders for the relationship references.
    """
    relationship_additions = []

    # Add context based on object type
    if record.get('sobject') == 'ascendix__Lease__c':
        # Add property reference context
        property_id = record.get('ascendix__Property__c')
        if property_id:
            relationship_additions.append(f"Property Reference: {property_id}")
            # In production, fetch: property name, city, class

        # Add tenant reference
        tenant_id = record.get('ascendix__Tenant__c')
        if tenant_id:
            relationship_additions.append(f"Tenant Reference: {tenant_id}")

    elif record.get('sobject') == 'ascendix__Deal__c':
        # Add property reference
        property_id = record.get('ascendix__Property__c')
        if property_id:
            relationship_additions.append(f"Property Reference: {property_id}")

        # Add client reference
        client_id = record.get('ascendix__Client__c')
        if client_id:
            relationship_additions.append(f"Client Reference: {client_id}")

    elif record.get('sobject') == 'ascendix__Availability__c':
        # Add property reference
        property_id = record.get('ascendix__Property__c')
        if property_id:
            relationship_additions.append(f"Property Reference: {property_id}")

    # Add relationship context to chunk
    if relationship_additions:
        chunk_text = chunk_text.rstrip() + "\n\nRelated Objects:\n" + "\n".join(relationship_additions)

    return chunk_text


def rewrite_query_for_relationships(query):
    """
    Rewrite user queries to improve cross-object matching.
    """
    # Common query patterns and their rewrites
    rewrites = {
        # Property + Availability
        r"properties? in (\w+) with available space":
            r"(property \1) OR (availability property \1) OR (available space \1)",

        # Lease temporal
        r"leases? expiring (soon|in the next \d+ days?)":
            r"lease EXPIRING_SOON OR lease EXPIRING_THIS_MONTH OR lease expiration",

        # Deal + Property location
        r"deals? for properties? in (\w+)":
            r"(deal property \1) OR (deal \1) OR (property \1 deal)",

        # Deal by client
        r"deals? (for|with) (\w+)":
            r"(deal client \2) OR (deal \2) OR (\2 deal)",

        # Property class
        r"class ([A-C]\+?) (office |)buildings?":
            r"(property class \1) OR (class \1 property) OR (property type office class \1)"
    }

    # Apply rewrites
    rewritten = query
    for pattern, replacement in rewrites.items():
        rewritten = re.sub(pattern, replacement, rewritten, flags=re.IGNORECASE)

    return rewritten


def enhance_chunk(record, chunk_text):
    """
    Main enhancement function to add all context to a chunk.
    This should be called after the standard chunking process.
    """
    # Add temporal context
    chunk_text = add_temporal_context(record, chunk_text)

    # Add relationship context
    chunk_text = add_relationship_context(record, chunk_text)

    return chunk_text


# Enhanced field mappings with relationship fields
ENHANCED_CRE_FIELDS = {
    'ascendix__Deal__c': {
        'text_fields': [
            'Name',
            'ascendix__DealNumber__c',
            'ascendix__Status__c',
            'ascendix__SalesStage__c',
            'ascendix__DealType__c',
            'ascendix__DealSubType__c',
            'ascendix__DealRole__c',
            'ascendix__Territory__c',
            # ADD THESE FOR RELATIONSHIPS:
            'ascendix__Property__r.Name',  # Property name via relationship
            'ascendix__Property__r.ascendix__City__c',  # Property city
            'ascendix__Property__r.ascendix__PropertyClass__c',  # Property class
            'ascendix__Client__r.Name',  # Client name via relationship
        ],
        'currency_fields': [
            'ascendix__Fee__c',
            'ascendix__ExpectedCloseValue__c'
        ],
        'date_fields': [
            'ascendix__TargetCloseDate__c',
            'CreatedDate'
        ]
    },

    'ascendix__Lease__c': {
        'text_fields': [
            'Name',
            'ascendix__LeaseNumber__c',
            'ascendix__LeaseType__c',
            'ascendix__TenantLegalName__c',
            'ascendix__Status__c',
            # ADD THESE FOR RELATIONSHIPS:
            'ascendix__Property__r.Name',  # Property name
            'ascendix__Property__r.ascendix__City__c',  # Property city
            'ascendix__Property__r.ascendix__State__c',  # Property state
            'ascendix__Property__r.ascendix__PropertyClass__c',  # Property class
            'ascendix__Tenant__r.Name',  # Tenant account name
        ],
        'currency_fields': [
            'ascendix__AnnualRent__c',
            'ascendix__BaseRentPSF__c',
            'ascendix__TotalValue__c'
        ],
        'date_fields': [
            'ascendix__TermCommencementDate__c',
            'ascendix__TermExpirationDate__c'
        ]
    },

    'ascendix__Availability__c': {
        'text_fields': [
            'Name',
            'ascendix__Suite__c',
            'ascendix__SpaceType__c',
            'ascendix__Status__c',
            # ADD THESE FOR RELATIONSHIPS:
            'ascendix__Property__r.Name',  # Property name
            'ascendix__Property__r.ascendix__City__c',  # Property city
            'ascendix__Property__r.ascendix__PropertyClass__c',  # Property class
        ],
        'numeric_fields': [
            'ascendix__RentableArea__c',
            'ascendix__ContiguousSize__c'
        ],
        'currency_fields': [
            'ascendix__AskingRent__c'
        ],
        'date_fields': [
            'ascendix__AvailableDate__c'
        ]
    }
}


def test_enhancements():
    """
    Test the enhancement functions with sample data.
    """
    # Test temporal context
    test_lease = {
        'sobject': 'ascendix__Lease__c',
        'ascendix__TermExpirationDate__c': '2026-02-15T00:00:00Z'
    }

    chunk_text = "Lease Agreement\nTenant: Test Corp"
    enhanced = add_temporal_context(test_lease, chunk_text)
    print("Temporal Enhancement:")
    print(enhanced)
    print()

    # Test query rewriting
    test_queries = [
        "properties in Dallas with available space",
        "leases expiring soon",
        "deals for properties in New York",
        "Class A office buildings"
    ]

    print("Query Rewrites:")
    for query in test_queries:
        rewritten = rewrite_query_for_relationships(query)
        if rewritten != query:
            print(f"Original: {query}")
            print(f"Rewritten: {rewritten}")
            print()


if __name__ == "__main__":
    test_enhancements()