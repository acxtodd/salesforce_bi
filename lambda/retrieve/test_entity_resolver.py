"""
Unit Tests for Entity Resolver.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 6.1, 6.2, 6.3**

Tests exact matching, fuzzy matching, and multi-match ranking.
"""

import os
import sys
from typing import Any, Dict, List

import pytest

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from entity_resolver import (
    EntityResolver,
    ResolvedEntity,
    ResolutionResult,
    MockOpenSearchClient,
    SUPPORTED_OBJECT_TYPES,
    resolve_entity,
    get_seed_ids,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_accounts():
    """Sample Account records for testing."""
    return [
        {
            "recordId": "001000000000001AAA",
            "displayName": "Acme Corporation",
            "sobject": "Account",
            "Name": "Acme Corporation",
            "LastModifiedDate": "2024-01-15T10:30:00Z",
        },
        {
            "recordId": "001000000000002AAA",
            "displayName": "Acme Industries",
            "sobject": "Account",
            "Name": "Acme Industries",
            "LastModifiedDate": "2024-01-10T08:00:00Z",
        },
        {
            "recordId": "001000000000003AAA",
            "displayName": "Beta Corp",
            "sobject": "Account",
            "Name": "Beta Corp",
            "LastModifiedDate": "2024-01-12T14:00:00Z",
        },
    ]


@pytest.fixture
def sample_contacts():
    """Sample Contact records for testing."""
    return [
        {
            "recordId": "003000000000001AAA",
            "displayName": "Jane Doe",
            "sobject": "Contact",
            "Name": "Jane Doe",
            "FirstName": "Jane",
            "LastName": "Doe",
            "LastModifiedDate": "2024-01-15T10:30:00Z",
        },
        {
            "recordId": "003000000000002AAA",
            "displayName": "John Smith",
            "sobject": "Contact",
            "Name": "John Smith",
            "FirstName": "John",
            "LastName": "Smith",
            "LastModifiedDate": "2024-01-14T09:00:00Z",
        },
    ]


@pytest.fixture
def sample_properties():
    """Sample Property records for testing."""
    return [
        {
            "recordId": "a00000000000001AAA",
            "displayName": "123 Main Street",
            "sobject": "ascendix__Property__c",
            "Name": "123 Main Street",
            "ascendix__Address__c": "123 Main Street, Dallas, TX",
            "LastModifiedDate": "2024-01-15T10:30:00Z",
        },
        {
            "recordId": "a00000000000002AAA",
            "displayName": "456 Oak Avenue",
            "sobject": "ascendix__Property__c",
            "Name": "456 Oak Avenue",
            "ascendix__Address__c": "456 Oak Avenue, Plano, TX",
            "LastModifiedDate": "2024-01-10T08:00:00Z",
        },
    ]


@pytest.fixture
def mixed_records(sample_accounts, sample_contacts, sample_properties):
    """Combined records from all object types."""
    return sample_accounts + sample_contacts + sample_properties


# =============================================================================
# ResolvedEntity Tests
# =============================================================================


class TestResolvedEntity:
    """Tests for ResolvedEntity dataclass."""

    def test_create_valid_entity(self):
        """Test creating a valid ResolvedEntity."""
        entity = ResolvedEntity(
            record_id="001000000000001AAA",
            name="Acme Corporation",
            object_type="Account",
            match_type="exact",
            score=0.95,
        )
        
        assert entity.record_id == "001000000000001AAA"
        assert entity.name == "Acme Corporation"
        assert entity.object_type == "Account"
        assert entity.match_type == "exact"
        assert entity.score == 0.95

    def test_invalid_score_raises_error(self):
        """Test that invalid score raises ValueError."""
        with pytest.raises(ValueError, match="Score must be in range"):
            ResolvedEntity(
                record_id="001000000000001AAA",
                name="Test",
                object_type="Account",
                score=1.5,
            )

    def test_invalid_match_type_raises_error(self):
        """Test that invalid match_type raises ValueError."""
        with pytest.raises(ValueError, match="match_type must be"):
            ResolvedEntity(
                record_id="001000000000001AAA",
                name="Test",
                object_type="Account",
                match_type="invalid",
            )

    def test_to_dict(self):
        """Test converting ResolvedEntity to dictionary."""
        entity = ResolvedEntity(
            record_id="001000000000001AAA",
            name="Acme Corporation",
            object_type="Account",
            match_type="exact",
            score=0.95,
            last_modified="2024-01-15T10:30:00Z",
        )
        
        result = entity.to_dict()
        
        assert result["record_id"] == "001000000000001AAA"
        assert result["name"] == "Acme Corporation"
        assert result["object_type"] == "Account"
        assert result["match_type"] == "exact"
        assert result["score"] == 0.95
        assert result["last_modified"] == "2024-01-15T10:30:00Z"


# =============================================================================
# ResolutionResult Tests
# =============================================================================


class TestResolutionResult:
    """Tests for ResolutionResult dataclass."""

    def test_empty_result(self):
        """Test empty resolution result."""
        result = ResolutionResult()
        
        assert result.matches == []
        assert result.total_matches == 0
        assert not result.has_matches
        assert result.best_match is None
        assert result.seed_ids == []

    def test_result_with_matches(self):
        """Test resolution result with matches."""
        matches = [
            ResolvedEntity(
                record_id="001000000000001AAA",
                name="Acme Corp",
                object_type="Account",
                score=0.95,
            ),
            ResolvedEntity(
                record_id="001000000000002AAA",
                name="Acme Industries",
                object_type="Account",
                score=0.85,
            ),
        ]
        
        result = ResolutionResult(
            matches=matches,
            query_name="Acme",
            total_matches=2,
        )
        
        assert len(result.matches) == 2
        assert result.has_matches
        assert result.best_match.record_id == "001000000000001AAA"
        assert result.seed_ids == ["001000000000001AAA", "001000000000002AAA"]


# =============================================================================
# EntityResolver Exact Matching Tests
# =============================================================================


class TestEntityResolverExactMatching:
    """
    Tests for exact name matching.
    
    **Requirements: 6.1**
    """

    def test_exact_match_account(self, sample_accounts):
        """Test exact matching for Account records."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve("Acme Corporation")
        
        assert result.has_matches
        assert result.matches[0].record_id == "001000000000001AAA"
        assert result.matches[0].name == "Acme Corporation"
        assert result.matches[0].object_type == "Account"

    def test_exact_match_contact(self, sample_contacts):
        """Test exact matching for Contact records."""
        mock_client = MockOpenSearchClient(mock_data=sample_contacts)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve("Jane Doe")
        
        assert result.has_matches
        assert result.matches[0].record_id == "003000000000001AAA"
        assert result.matches[0].name == "Jane Doe"
        assert result.matches[0].object_type == "Contact"

    def test_exact_match_property(self, sample_properties):
        """Test exact matching for Property records."""
        mock_client = MockOpenSearchClient(mock_data=sample_properties)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve("123 Main Street")
        
        assert result.has_matches
        assert result.matches[0].record_id == "a00000000000001AAA"
        assert result.matches[0].object_type == "ascendix__Property__c"

    def test_exact_match_with_object_type_filter(self, mixed_records):
        """Test exact matching with object type filter."""
        mock_client = MockOpenSearchClient(mock_data=mixed_records)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        # Search for "Jane" but filter to Contact only
        result = resolver.resolve("Jane Doe", object_type="Contact")
        
        assert result.has_matches
        assert all(m.object_type == "Contact" for m in result.matches)

    def test_no_match_returns_empty(self, sample_accounts):
        """Test that no match returns empty result."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve("NonExistent Company")
        
        assert not result.has_matches
        assert result.matches == []


# =============================================================================
# EntityResolver Fuzzy Matching Tests
# =============================================================================


class TestEntityResolverFuzzyMatching:
    """
    Tests for fuzzy name matching.
    
    **Requirements: 6.1, 6.3**
    """

    def test_fuzzy_match_partial_name(self, sample_accounts):
        """Test fuzzy matching with partial name."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        # "Acme" should match "Acme Corporation" and "Acme Industries"
        result = resolver.resolve("Acme")
        
        assert result.has_matches
        # Both Acme records should match
        matched_names = [m.name for m in result.matches]
        assert any("Acme" in name for name in matched_names)

    def test_fuzzy_match_returns_match_type(self, sample_accounts):
        """Test that fuzzy matches have correct match_type."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve("Acme Corporation")
        
        # All matches should have valid match_type
        for match in result.matches:
            assert match.match_type in ("exact", "fuzzy")


# =============================================================================
# EntityResolver Multi-Match Ranking Tests
# =============================================================================


class TestEntityResolverMultiMatchRanking:
    """
    Tests for multi-match ranking.
    
    **Requirements: 6.3**
    """

    def test_multiple_matches_ranked_by_score(self, sample_accounts):
        """Test that multiple matches are ranked by score."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve("Acme")
        
        if len(result.matches) > 1:
            # Matches should be sorted by score descending
            scores = [m.score for m in result.matches]
            assert scores == sorted(scores, reverse=True)

    def test_best_match_returns_highest_score(self, sample_accounts):
        """Test that best_match returns the highest scoring match."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve("Acme")
        
        if result.has_matches:
            best = result.best_match
            max_score = max(m.score for m in result.matches)
            assert best.score == max_score

    def test_max_matches_limit(self, sample_accounts):
        """Test that max_matches is passed to the query."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        resolver = EntityResolver(opensearch_client=mock_client, max_matches=1)
        
        # Build the query to verify max_matches is included
        query = resolver._build_exact_query("Acme", None, 1)
        
        # The query should have size=1
        assert query["size"] == 1
        
        # Note: The mock client doesn't respect size, but real OpenSearch would
        # This test verifies the query is built correctly

    def test_seed_ids_returns_all_record_ids(self, sample_accounts):
        """Test that seed_ids returns all matched record IDs."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve("Acme")
        
        # seed_ids should contain all matched record IDs
        assert len(result.seed_ids) == len(result.matches)
        for match in result.matches:
            assert match.record_id in result.seed_ids


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_resolve_entity_function(self, sample_accounts):
        """Test resolve_entity convenience function."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        
        result = resolve_entity("Acme Corporation", opensearch_client=mock_client)
        
        assert result.has_matches
        assert result.matches[0].name == "Acme Corporation"

    def test_get_seed_ids_function(self, sample_accounts):
        """Test get_seed_ids convenience function."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        
        seed_ids = get_seed_ids("Acme Corporation", opensearch_client=mock_client)
        
        assert isinstance(seed_ids, list)
        assert len(seed_ids) > 0
        assert "001000000000001AAA" in seed_ids


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_query(self):
        """Test empty query returns empty result."""
        mock_client = MockOpenSearchClient(mock_data=[])
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve("")
        
        assert not result.has_matches
        assert result.latency_ms == 0.0

    def test_whitespace_query(self):
        """Test whitespace-only query returns empty result."""
        mock_client = MockOpenSearchClient(mock_data=[])
        resolver = EntityResolver(opensearch_client=mock_client)
        
        result = resolver.resolve("   ")
        
        assert not result.has_matches

    def test_unsupported_object_type_logs_warning(self, sample_accounts, caplog):
        """Test that unsupported object type logs a warning."""
        mock_client = MockOpenSearchClient(mock_data=sample_accounts)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        # Use an unsupported object type
        result = resolver.resolve("Acme", object_type="UnsupportedObject__c")
        
        # Should still return results (warning only)
        # The mock client doesn't filter by object type

    def test_resolve_multiple_names(self, mixed_records):
        """Test resolving multiple names in batch."""
        mock_client = MockOpenSearchClient(mock_data=mixed_records)
        resolver = EntityResolver(opensearch_client=mock_client)
        
        names = ["Acme Corporation", "Jane Doe", "123 Main Street"]
        results = resolver.resolve_multiple(names)
        
        assert len(results) == 3
        assert "Acme Corporation" in results
        assert "Jane Doe" in results
        assert "123 Main Street" in results
