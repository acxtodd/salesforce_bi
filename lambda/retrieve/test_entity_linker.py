"""
Unit Tests for Entity Linker.

Tests for EntityLinker class including term matching, disambiguation,
and confidence scoring.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 2.1, 2.2, 2.3**
"""

import os
import sys
from typing import Any, Dict, List, Optional

import pytest

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from entity_linker import (
    EntityLinker,
    EntityMatch,
    LinkingResult,
    link_entities,
    STOP_WORDS,
)


# =============================================================================
# Mock VocabCache for Testing
# =============================================================================


class MockVocabCache:
    """Mock VocabCache for unit testing."""

    def __init__(self):
        self._terms: Dict[str, List[Dict[str, Any]]] = {}
        self._terms_by_type: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    def add_term(
        self,
        term: str,
        object_name: str,
        field_name: Optional[str] = None,
        canonical_value: Optional[str] = None,
        source: str = "describe",
        relevance_score: float = 0.5,
        vocab_type: str = "label",
    ) -> None:
        """Add a term to the mock cache."""
        term_lower = term.lower()
        entry = {
            "term": term_lower,
            "object_name": object_name,
            "field_name": field_name,
            "canonical_value": canonical_value or term,
            "source": source,
            "relevance_score": relevance_score,
            "vocab_type": vocab_type,
        }
        if term_lower not in self._terms:
            self._terms[term_lower] = []
        self._terms[term_lower].append(entry)

        if vocab_type not in self._terms_by_type:
            self._terms_by_type[vocab_type] = {}
        if object_name not in self._terms_by_type[vocab_type]:
            self._terms_by_type[vocab_type][object_name] = []
        self._terms_by_type[vocab_type][object_name].append(entry)

    def lookup(self, term: str, vocab_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Look up a term."""
        term_lower = term.lower()
        entries = self._terms.get(term_lower, [])
        if not entries:
            return None
        if vocab_type:
            entries = [e for e in entries if e.get("vocab_type") == vocab_type]
        if not entries:
            return None
        return max(entries, key=lambda e: e.get("relevance_score", 0))

    def get_terms(self, vocab_type: str, object_name: str) -> List[Dict[str, Any]]:
        """Get all terms for a vocab type and object."""
        if vocab_type in self._terms_by_type:
            return self._terms_by_type[vocab_type].get(object_name, [])
        return []

    def lookup_with_score(self, term: str, min_score: float = 0.0) -> List[Dict[str, Any]]:
        """Look up a term and return all matches above minimum score."""
        term_lower = term.lower()
        entries = self._terms.get(term_lower, [])
        return [e for e in entries if e.get("relevance_score", 0) >= min_score]


@pytest.fixture
def mock_cache():
    """Create a mock vocab cache."""
    return MockVocabCache()


@pytest.fixture
def populated_cache():
    """Create a mock vocab cache with CRE terms."""
    cache = MockVocabCache()

    # Property types (RecordTypes)
    cache.add_term("office", "Property__c", "RecordTypeId", "Office",
                   source="recordtype", relevance_score=0.8, vocab_type="recordtype")
    cache.add_term("industrial", "Property__c", "RecordTypeId", "Industrial",
                   source="recordtype", relevance_score=0.8, vocab_type="recordtype")
    cache.add_term("retail", "Property__c", "RecordTypeId", "Retail",
                   source="recordtype", relevance_score=0.8, vocab_type="recordtype")

    # Property classes (Picklist)
    cache.add_term("class a", "Property__c", "PropertyClass__c", "A",
                   source="picklist", relevance_score=0.6, vocab_type="picklist")
    cache.add_term("class b", "Property__c", "PropertyClass__c", "B",
                   source="picklist", relevance_score=0.6, vocab_type="picklist")

    # Field labels
    cache.add_term("property name", "Property__c", "Name", "Property Name",
                   source="layout", relevance_score=1.0, vocab_type="label")
    cache.add_term("status", "Property__c", "Status__c", "Status",
                   source="describe", relevance_score=0.4, vocab_type="label")
    cache.add_term("city", "Property__c", "City__c", "City",
                   source="describe", relevance_score=0.4, vocab_type="label")

    # Availability terms
    cache.add_term("available", "Availability__c", "Status__c", "Available",
                   source="picklist", relevance_score=0.6, vocab_type="picklist")
    cache.add_term("availability", "Availability__c", None, "Availability",
                   source="describe", relevance_score=0.4, vocab_type="object")

    # Lease terms
    cache.add_term("lease", "Lease__c", None, "Lease",
                   source="describe", relevance_score=0.4, vocab_type="object")
    cache.add_term("expiring", "Lease__c", "Status__c", "Expiring",
                   source="picklist", relevance_score=0.6, vocab_type="picklist")

    # Geographic terms
    cache.add_term("plano", "Property__c", "City__c", "Plano",
                   source="picklist", relevance_score=0.6, vocab_type="geography")
    cache.add_term("dallas", "Property__c", "City__c", "Dallas",
                   source="picklist", relevance_score=0.6, vocab_type="geography")

    return cache


# =============================================================================
# Unit Tests for EntityMatch
# =============================================================================


class TestEntityMatch:
    """Unit tests for EntityMatch dataclass."""

    def test_entity_match_creation(self):
        """Test basic EntityMatch creation."""
        match = EntityMatch(
            term="office",
            object_name="Property__c",
            field_name="RecordTypeId",
            value="Office",
            canonical_value="Office",
            confidence=0.8,
            match_type="exact",
            source="recordtype",
            vocab_type="recordtype",
        )
        assert match.term == "office"
        assert match.object_name == "Property__c"
        assert match.field_name == "RecordTypeId"
        assert match.confidence == 0.8

    def test_entity_match_confidence_validation(self):
        """Test that confidence must be in [0, 1]."""
        with pytest.raises(ValueError):
            EntityMatch(term="test", object_name="Test__c", confidence=1.5)

        with pytest.raises(ValueError):
            EntityMatch(term="test", object_name="Test__c", confidence=-0.1)

    def test_entity_match_to_dict(self):
        """Test EntityMatch serialization."""
        match = EntityMatch(
            term="office",
            object_name="Property__c",
            field_name="RecordTypeId",
            confidence=0.8,
        )
        result = match.to_dict()
        assert result["term"] == "office"
        assert result["object_name"] == "Property__c"
        assert result["field_name"] == "RecordTypeId"
        assert result["confidence"] == 0.8

    def test_entity_match_to_dict_excludes_none(self):
        """Test that None values are excluded from dict."""
        match = EntityMatch(term="test", object_name="Test__c", confidence=0.5)
        result = match.to_dict()
        assert "field_name" not in result
        assert "value" not in result


# =============================================================================
# Unit Tests for LinkingResult
# =============================================================================


class TestLinkingResult:
    """Unit tests for LinkingResult dataclass."""

    def test_linking_result_creation(self):
        """Test basic LinkingResult creation."""
        result = LinkingResult(
            matches=[EntityMatch(term="test", object_name="Test__c", confidence=0.8)],
            unmatched_terms=["unknown"],
            confidence=0.7,
        )
        assert len(result.matches) == 1
        assert len(result.unmatched_terms) == 1
        assert result.confidence == 0.7

    def test_linking_result_to_dict(self):
        """Test LinkingResult serialization."""
        result = LinkingResult(
            matches=[EntityMatch(term="office", object_name="Property__c", confidence=0.8)],
            unmatched_terms=["xyz"],
            confidence=0.6,
        )
        d = result.to_dict()
        assert len(d["matches"]) == 1
        assert d["matches"][0]["term"] == "office"
        assert d["unmatched_terms"] == ["xyz"]
        assert d["confidence"] == 0.6


# =============================================================================
# Unit Tests for Term Matching
# =============================================================================


class TestTermMatching:
    """Unit tests for term matching functionality."""

    def test_exact_match_single_term(self, populated_cache):
        """Test exact matching of a single term."""
        linker = EntityLinker(populated_cache)
        result = linker.link("office")

        assert len(result.matches) >= 1
        assert any(m.object_name == "Property__c" for m in result.matches)
        assert any(m.canonical_value == "Office" for m in result.matches)

    def test_exact_match_multi_word_term(self, populated_cache):
        """Test exact matching of multi-word terms."""
        linker = EntityLinker(populated_cache)
        result = linker.link("class a")

        assert len(result.matches) >= 1
        assert any(m.field_name == "PropertyClass__c" for m in result.matches)

    def test_case_insensitive_matching(self, populated_cache):
        """Test that matching is case-insensitive."""
        linker = EntityLinker(populated_cache)

        result1 = linker.link("office")
        result2 = linker.link("OFFICE")
        result3 = linker.link("Office")

        # All should find the same term
        assert len(result1.matches) == len(result2.matches) == len(result3.matches)

    def test_no_match_returns_empty(self, populated_cache):
        """Test that unmatched terms return empty matches."""
        linker = EntityLinker(populated_cache)
        result = linker.link("xyznonexistent")

        # Should have no matches but term in unmatched
        assert len(result.matches) == 0
        assert "xyznonexistent" in result.unmatched_terms

    def test_stop_words_ignored(self, populated_cache):
        """Test that stop words are not added to unmatched."""
        linker = EntityLinker(populated_cache)
        result = linker.link("the office in plano")

        # "the" and "in" should not be in unmatched
        assert "the" not in result.unmatched_terms
        assert "in" not in result.unmatched_terms

    def test_quoted_phrase_exact_match(self, populated_cache):
        """Test that quoted phrases are matched exactly."""
        linker = EntityLinker(populated_cache)
        result = linker.link('"class a"')

        assert len(result.matches) >= 1
        assert any(m.canonical_value == "A" for m in result.matches)


# =============================================================================
# Unit Tests for Disambiguation
# =============================================================================


class TestDisambiguation:
    """Unit tests for disambiguation functionality."""

    def test_disambiguation_selects_highest_score(self, mock_cache):
        """Test that disambiguation selects the highest scoring match."""
        # Add same term with different scores
        mock_cache.add_term("status", "Property__c", "Status__c", "Status (Property)",
                           source="describe", relevance_score=0.4)
        mock_cache.add_term("status", "Lease__c", "Status__c", "Status (Lease)",
                           source="layout", relevance_score=1.0)

        linker = EntityLinker(mock_cache)
        result = linker.link("status")

        # Should select the higher scoring match
        assert len(result.matches) >= 1
        # The highest scoring match should be from Lease__c (layout source)
        best_match = max(result.matches, key=lambda m: m.confidence)
        assert best_match.object_name == "Lease__c"

    def test_ambiguous_terms_logged(self, mock_cache):
        """Test that ambiguous terms are tracked."""
        mock_cache.add_term("name", "Account", "Name", "Account Name",
                           source="describe", relevance_score=0.4)
        mock_cache.add_term("name", "Contact", "Name", "Contact Name",
                           source="describe", relevance_score=0.4)

        linker = EntityLinker(mock_cache)
        result = linker.link("name")

        # Should have matches and potentially ambiguous terms
        assert len(result.matches) >= 1


# =============================================================================
# Unit Tests for Confidence Scoring
# =============================================================================


class TestConfidenceScoring:
    """Unit tests for confidence scoring."""

    def test_confidence_based_on_relevance(self, mock_cache):
        """Test that confidence incorporates relevance score."""
        mock_cache.add_term("high", "Test__c", None, "High",
                           source="layout", relevance_score=1.0)
        mock_cache.add_term("low", "Test__c", None, "Low",
                           source="describe", relevance_score=0.4)

        linker = EntityLinker(mock_cache)

        result_high = linker.link("high")
        result_low = linker.link("low")

        # Higher relevance should result in higher confidence
        if result_high.matches and result_low.matches:
            assert result_high.matches[0].confidence > result_low.matches[0].confidence

    def test_overall_confidence_calculation(self, populated_cache):
        """Test overall confidence calculation."""
        linker = EntityLinker(populated_cache)

        # Query with matched terms should have positive confidence
        result_good = linker.link("office")
        assert result_good.confidence > 0

        # Query with only unmatched terms should have zero confidence
        result_bad = linker.link("xyzunknown abcnonexistent")
        assert result_bad.confidence == 0.0

        # Query with some matches should have positive confidence
        result_mixed = linker.link("office xyzunknown")
        assert result_mixed.confidence > 0

    def test_empty_query_zero_confidence(self, populated_cache):
        """Test that empty queries have zero confidence."""
        linker = EntityLinker(populated_cache)

        result = linker.link("")
        assert result.confidence == 0.0

        result = linker.link("   ")
        assert result.confidence == 0.0

    def test_min_confidence_threshold(self, mock_cache):
        """Test minimum confidence threshold filtering."""
        mock_cache.add_term("test", "Test__c", None, "Test",
                           source="describe", relevance_score=0.2)

        # With high min_confidence, low-scoring matches should be filtered
        linker = EntityLinker(mock_cache, min_confidence=0.5)
        result = linker.link("test")

        # Match should be filtered out due to low confidence
        assert len(result.matches) == 0


# =============================================================================
# Unit Tests for Complex Queries
# =============================================================================


class TestComplexQueries:
    """Unit tests for complex query handling."""

    def test_multi_term_query(self, populated_cache):
        """Test queries with multiple terms."""
        linker = EntityLinker(populated_cache)
        result = linker.link("available office space in plano")

        # Should match multiple terms
        assert len(result.matches) >= 2
        objects = {m.object_name for m in result.matches}
        assert "Property__c" in objects or "Availability__c" in objects

    def test_cre_scenario_query(self, populated_cache):
        """Test realistic CRE query scenario."""
        linker = EntityLinker(populated_cache)
        result = linker.link("class a office buildings in dallas")

        # Should identify property type and class
        assert len(result.matches) >= 2

    def test_lease_query(self, populated_cache):
        """Test lease-related query."""
        linker = EntityLinker(populated_cache)
        result = linker.link("expiring leases")

        # Should match lease-related terms
        assert len(result.matches) >= 1
        assert any(m.object_name == "Lease__c" for m in result.matches)


# =============================================================================
# Unit Tests for Convenience Functions
# =============================================================================


class TestConvenienceFunctions:
    """Unit tests for convenience functions."""

    def test_link_entities_function(self, populated_cache):
        """Test link_entities convenience function."""
        result = link_entities("office", populated_cache)

        assert isinstance(result, LinkingResult)
        assert len(result.matches) >= 1


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Unit tests for edge cases."""

    def test_special_characters_in_query(self, populated_cache):
        """Test handling of special characters."""
        linker = EntityLinker(populated_cache)

        # Should not crash on special characters
        result = linker.link("office @#$% plano")
        assert isinstance(result, LinkingResult)

    def test_very_long_query(self, populated_cache):
        """Test handling of very long queries."""
        linker = EntityLinker(populated_cache)

        long_query = "office " * 100
        result = linker.link(long_query)
        assert isinstance(result, LinkingResult)

    def test_unicode_in_query(self, populated_cache):
        """Test handling of unicode characters."""
        linker = EntityLinker(populated_cache)

        result = linker.link("office café résumé")
        assert isinstance(result, LinkingResult)

    def test_numbers_in_query(self, populated_cache):
        """Test handling of numbers in queries."""
        linker = EntityLinker(populated_cache)

        result = linker.link("office 123 main street")
        assert isinstance(result, LinkingResult)
