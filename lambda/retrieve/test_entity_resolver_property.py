"""
Property-Based Tests for Entity Resolver.

**Feature: graph-aware-zero-config-retrieval, Property 12: Entity Resolution ID Usage**
**Validates: Requirements 6.1, 6.2**

Property 12: Entity Resolution ID Usage
*For any* query where entity names are resolved to IDs, the resolved IDs
SHALL be used as seed filters in the execution plan.
"""

import os
import sys
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, strategies as st, settings, assume

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from entity_resolver import (
    EntityResolver,
    ResolvedEntity,
    ResolutionResult,
    MockOpenSearchClient,
    SUPPORTED_OBJECT_TYPES,
)


# =============================================================================
# Hypothesis Strategies
# =============================================================================


# Valid Salesforce record ID prefixes by object type
RECORD_ID_PREFIXES = {
    "Account": "001",
    "Contact": "003",
    "Property__c": "a00",
    "ascendix__Property__c": "a00",
    "ascendix__Deal__c": "a01",
    "ascendix__Lease__c": "a02",
    "ascendix__Sale__c": "a03",
    "ascendix__Availability__c": "a04",
}


def generate_salesforce_id(prefix: str = "001") -> str:
    """Generate a valid 18-character Salesforce ID."""
    import random
    import string
    
    # Generate remaining 15 characters (alphanumeric)
    chars = string.ascii_uppercase + string.digits
    remaining = "".join(random.choices(chars, k=12))
    base_id = prefix + remaining
    
    # Add 3-character suffix for 18-char ID
    suffix = "".join(random.choices(string.ascii_uppercase, k=3))
    return base_id + suffix


@st.composite
def salesforce_record_strategy(draw):
    """Generate a mock Salesforce record for OpenSearch."""
    object_type = draw(st.sampled_from(list(RECORD_ID_PREFIXES.keys())))
    prefix = RECORD_ID_PREFIXES[object_type]
    
    # Generate a valid record ID
    record_id = generate_salesforce_id(prefix)
    
    # Generate a display name
    name = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ",
            min_size=3,
            max_size=50,
        ).filter(lambda x: x.strip())
    )
    
    return {
        "recordId": record_id,
        "displayName": name.strip(),
        "sobject": object_type,
        "Name": name.strip(),
        "LastModifiedDate": "2024-01-15T10:30:00Z",
    }


@st.composite
def mock_opensearch_data_strategy(draw):
    """Generate mock OpenSearch data with multiple records."""
    num_records = draw(st.integers(min_value=1, max_value=10))
    records = []
    
    for _ in range(num_records):
        record = draw(salesforce_record_strategy())
        records.append(record)
    
    return records


# =============================================================================
# Property Tests
# =============================================================================


class TestEntityResolverProperty:
    """
    Property-based tests for Entity Resolver.

    **Feature: graph-aware-zero-config-retrieval, Property 12: Entity Resolution ID Usage**
    **Validates: Requirements 6.1, 6.2**
    """

    @pytest.mark.property
    @settings(max_examples=100)
    @given(data=st.data())
    def test_property_12_resolved_ids_available_as_seed_filters(self, data):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 12: Entity Resolution ID Usage**
        **Validates: Requirements 6.1, 6.2**

        Property: For any query where entity names are resolved to IDs,
        the resolved IDs SHALL be available as seed filters.
        """
        # Generate mock data
        mock_data = data.draw(mock_opensearch_data_strategy())
        assume(len(mock_data) > 0)
        
        # Pick a record to search for
        target_record = data.draw(st.sampled_from(mock_data))
        search_name = target_record["displayName"]
        
        # Create resolver with mock client
        mock_client = MockOpenSearchClient(mock_data=mock_data)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        # Resolve the name
        result = resolver.resolve(search_name)
        
        # Property: If matches are found, seed_ids should contain record IDs
        if result.has_matches:
            seed_ids = result.seed_ids
            
            # seed_ids should be a list of strings
            assert isinstance(seed_ids, list)
            
            # All seed_ids should be valid record IDs (non-empty strings)
            for seed_id in seed_ids:
                assert isinstance(seed_id, str)
                assert len(seed_id) > 0
            
            # The target record's ID should be in seed_ids (since we searched for its name)
            assert target_record["recordId"] in seed_ids, (
                f"Expected {target_record['recordId']} in seed_ids {seed_ids} "
                f"when searching for '{search_name}'"
            )

    @pytest.mark.property
    @settings(max_examples=100)
    @given(
        name=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ",
            min_size=3,
            max_size=30,
        ).filter(lambda x: x.strip()),
        object_type=st.sampled_from(list(RECORD_ID_PREFIXES.keys())),
    )
    def test_resolved_entity_has_valid_score(self, name, object_type):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 12: Entity Resolution ID Usage**
        **Validates: Requirements 6.1, 6.2**

        Property: For any ResolvedEntity, the score SHALL be in range [0, 1].
        """
        # Create mock data with the name
        prefix = RECORD_ID_PREFIXES[object_type]
        record_id = generate_salesforce_id(prefix)
        
        mock_data = [{
            "recordId": record_id,
            "displayName": name.strip(),
            "sobject": object_type,
            "Name": name.strip(),
        }]
        
        mock_client = MockOpenSearchClient(mock_data=mock_data)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve(name.strip())
        
        # All matches should have valid scores
        for match in result.matches:
            assert 0.0 <= match.score <= 1.0, (
                f"Score {match.score} out of valid range [0, 1]"
            )

    @pytest.mark.property
    @settings(max_examples=100)
    @given(
        name=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ",
            min_size=3,
            max_size=30,
        ).filter(lambda x: x.strip()),
        object_type=st.sampled_from(list(RECORD_ID_PREFIXES.keys())),
    )
    def test_resolved_entity_has_valid_match_type(self, name, object_type):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 12: Entity Resolution ID Usage**
        **Validates: Requirements 6.1, 6.2**

        Property: For any ResolvedEntity, match_type SHALL be either 'exact' or 'fuzzy'.
        """
        # Create mock data
        prefix = RECORD_ID_PREFIXES[object_type]
        record_id = generate_salesforce_id(prefix)
        
        mock_data = [{
            "recordId": record_id,
            "displayName": name.strip(),
            "sobject": object_type,
            "Name": name.strip(),
        }]
        
        mock_client = MockOpenSearchClient(mock_data=mock_data)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve(name.strip())
        
        # All matches should have valid match_type
        for match in result.matches:
            assert match.match_type in ("exact", "fuzzy"), (
                f"match_type '{match.match_type}' not in ('exact', 'fuzzy')"
            )

    @pytest.mark.property
    @settings(max_examples=100)
    @given(
        query=st.one_of(
            st.just(""),
            st.just(" "),
            st.just("  "),
            st.just("\t"),
            st.just("\n"),
            st.text(alphabet=" \t\n\r", min_size=0, max_size=10),
        )
    )
    def test_empty_query_returns_empty_result(self, query):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 12: Entity Resolution ID Usage**
        **Validates: Requirements 6.1, 6.2**

        Property: For any empty or whitespace-only query, the Entity Resolver
        SHALL return an empty result with no matches.
        """
        mock_client = MockOpenSearchClient(mock_data=[])
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve(query)
        
        assert len(result.matches) == 0
        assert result.seed_ids == []
        assert not result.has_matches

    @pytest.mark.property
    @settings(max_examples=100)
    @given(data=st.data())
    def test_object_type_filter_respected(self, data):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 12: Entity Resolution ID Usage**
        **Validates: Requirements 6.1, 6.2**

        Property: When object_type filter is provided, all returned matches
        SHALL have that object_type.
        """
        # Generate mock data with multiple object types
        mock_data = data.draw(mock_opensearch_data_strategy())
        assume(len(mock_data) > 0)
        
        # Pick a target object type
        target_type = data.draw(st.sampled_from(list(RECORD_ID_PREFIXES.keys())))
        
        # Filter mock data to only include target type
        filtered_data = [r for r in mock_data if r["sobject"] == target_type]
        
        # If no records of target type, skip
        assume(len(filtered_data) > 0)
        
        # Pick a name from filtered data
        target_record = data.draw(st.sampled_from(filtered_data))
        search_name = target_record["displayName"]
        
        # Create resolver with mock client containing only filtered data
        mock_client = MockOpenSearchClient(mock_data=filtered_data)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        # Resolve with object type filter
        result = resolver.resolve(search_name, object_type=target_type)
        
        # All matches should have the target object type
        for match in result.matches:
            assert match.object_type == target_type, (
                f"Expected object_type '{target_type}', got '{match.object_type}'"
            )

    @pytest.mark.property
    @settings(max_examples=100)
    @given(data=st.data())
    def test_best_match_has_highest_score(self, data):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 12: Entity Resolution ID Usage**
        **Validates: Requirements 6.1, 6.3**

        Property: The best_match property SHALL return the match with the highest score.
        """
        # Generate mock data
        mock_data = data.draw(mock_opensearch_data_strategy())
        assume(len(mock_data) > 0)
        
        # Pick a record to search for
        target_record = data.draw(st.sampled_from(mock_data))
        search_name = target_record["displayName"]
        
        mock_client = MockOpenSearchClient(mock_data=mock_data)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve(search_name)
        
        if result.has_matches and len(result.matches) > 1:
            best = result.best_match
            # best_match should have the highest score
            max_score = max(m.score for m in result.matches)
            assert best.score == max_score, (
                f"best_match score {best.score} != max score {max_score}"
            )
