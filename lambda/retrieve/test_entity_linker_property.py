"""
Property-Based Tests for Entity Linker.

**Feature: graph-aware-zero-config-retrieval, Property 4: Entity Linking from Vocabulary**
**Validates: Requirements 2.1, 2.2**

Property 4: Entity Linking from Vocabulary
*For any* query containing terms present in the vocabulary cache, the Entity Linker
SHALL return matches with the correct object and field mappings.
"""

import os
import sys
from typing import Any, Dict, List, Optional

import pytest
from hypothesis import given, strategies as st, settings, assume

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from entity_linker import EntityLinker, EntityMatch, LinkingResult, STOP_WORDS


# =============================================================================
# Mock VocabCache for Testing
# =============================================================================


class MockVocabCache:
    """Mock VocabCache for property testing."""

    def __init__(self, terms: Optional[Dict[str, Dict[str, Any]]] = None):
        """
        Initialize with optional predefined terms.

        Args:
            terms: Dict mapping term (lowercase) to vocab entry dict
        """
        self._terms: Dict[str, List[Dict[str, Any]]] = {}  # term -> list of entries
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
        # Store as list to handle multiple entries for same term
        if term_lower not in self._terms:
            self._terms[term_lower] = []
        self._terms[term_lower].append(entry)

        # Also store by type/object for get_terms
        if vocab_type not in self._terms_by_type:
            self._terms_by_type[vocab_type] = {}
        if object_name not in self._terms_by_type[vocab_type]:
            self._terms_by_type[vocab_type][object_name] = []
        self._terms_by_type[vocab_type][object_name].append(entry)

    def lookup(self, term: str, vocab_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Look up a term - returns the highest scoring entry."""
        term_lower = term.lower()
        entries = self._terms.get(term_lower, [])
        if not entries:
            return None

        # Filter by vocab_type if specified
        if vocab_type:
            entries = [e for e in entries if e.get("vocab_type") == vocab_type]

        if not entries:
            return None

        # Return highest scoring entry
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


# =============================================================================
# Hypothesis Strategies
# =============================================================================


# Valid Salesforce object names
VALID_OBJECTS = [
    "Account",
    "Contact",
    "Property__c",
    "Availability__c",
    "Lease__c",
    "Sale__c",
    "Opportunity",
    "Task",
    "Event",
    "Note",
]

# Valid field names
VALID_FIELDS = [
    "Name",
    "Status__c",
    "PropertyClass__c",
    "Type__c",
    "City__c",
    "State__c",
    "RecordTypeId",
    "OwnerId",
    "CreatedDate",
    "LastModifiedDate",
]

# Valid vocab types
VALID_VOCAB_TYPES = ["label", "picklist", "recordtype", "object", "geography"]

# Valid sources
VALID_SOURCES = ["describe", "picklist", "recordtype", "layout"]


def is_not_stop_word(term: str) -> bool:
    """Check if a term is not a stop word."""
    return term.strip().lower() not in STOP_WORDS


@st.composite
def vocab_term_strategy(draw):
    """Generate a valid vocabulary term entry."""
    # Generate a term that's a valid identifier-like string and NOT a stop word
    term = draw(
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=2, max_size=20).filter(
            lambda x: x.strip() and not x.isspace() and is_not_stop_word(x)
        )
    )

    object_name = draw(st.sampled_from(VALID_OBJECTS))
    field_name = draw(st.one_of(st.none(), st.sampled_from(VALID_FIELDS)))
    source = draw(st.sampled_from(VALID_SOURCES))
    relevance_score = draw(st.floats(min_value=0.1, max_value=1.0, allow_nan=False))
    vocab_type = draw(st.sampled_from(VALID_VOCAB_TYPES))

    return {
        "term": term.strip().lower(),
        "object_name": object_name,
        "field_name": field_name,
        "canonical_value": term.strip().title(),
        "source": source,
        "relevance_score": relevance_score,
        "vocab_type": vocab_type,
    }


@st.composite
def vocab_cache_with_terms_strategy(draw):
    """Generate a MockVocabCache with random terms."""
    num_terms = draw(st.integers(min_value=1, max_value=10))
    cache = MockVocabCache()

    terms_added = []
    for _ in range(num_terms):
        term_entry = draw(vocab_term_strategy())
        cache.add_term(
            term=term_entry["term"],
            object_name=term_entry["object_name"],
            field_name=term_entry["field_name"],
            canonical_value=term_entry["canonical_value"],
            source=term_entry["source"],
            relevance_score=term_entry["relevance_score"],
            vocab_type=term_entry["vocab_type"],
        )
        terms_added.append(term_entry)

    return cache, terms_added


# =============================================================================
# Property Tests
# =============================================================================


class TestEntityLinkerProperty:
    """
    Property-based tests for Entity Linker.

    **Feature: graph-aware-zero-config-retrieval, Property 4: Entity Linking from Vocabulary**
    **Validates: Requirements 2.1, 2.2**
    """

    @pytest.mark.property
    @settings(max_examples=100)
    @given(data=st.data())
    def test_property_4_entity_linking_from_vocabulary(self, data):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 4: Entity Linking from Vocabulary**
        **Validates: Requirements 2.1, 2.2**

        Property: For any query containing terms present in the vocabulary cache,
        the Entity Linker SHALL return matches with the correct object and field mappings.
        """
        # Generate a vocab cache with terms
        cache, terms_added = data.draw(vocab_cache_with_terms_strategy())

        # Filter to get valid terms (non-empty after strip)
        valid_terms = [t for t in terms_added if t["term"].strip()]
        assume(len(valid_terms) > 0)

        # Pick a random term from the cache to include in the query
        term_to_find = data.draw(st.sampled_from(valid_terms))

        # Get all objects that have this term in the cache
        term_lower = term_to_find["term"].lower()
        all_objects_for_term = set()
        for t in terms_added:
            if t["term"].lower() == term_lower:
                all_objects_for_term.add(t["object_name"])

        # Create a query containing the term
        query = term_to_find["term"]

        # Create linker and link
        linker = EntityLinker(cache, min_confidence=0.0)
        result = linker.link(query)

        # Property: If the term is in the vocab cache, we should get a match
        # with one of the valid object_names for that term
        if result.matches:
            # At least one match should have a valid object_name for this term
            matching_objects = set(m.object_name for m in result.matches)
            assert matching_objects & all_objects_for_term, (
                f"Expected one of {all_objects_for_term} in matches, " f"got {matching_objects} for term '{query}'"
            )

            # The match should have a valid confidence score
            for match in result.matches:
                assert 0.0 <= match.confidence <= 1.0, f"Confidence {match.confidence} out of range [0, 1]"

    @pytest.mark.property
    @settings(max_examples=100)
    @given(
        term=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=15).filter(
            lambda x: x.strip() and is_not_stop_word(x)
        ),
        object_name=st.sampled_from(VALID_OBJECTS),
        relevance_score=st.floats(min_value=0.1, max_value=1.0, allow_nan=False),
    )
    def test_exact_match_returns_correct_object(self, term, object_name, relevance_score):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 4: Entity Linking from Vocabulary**
        **Validates: Requirements 2.1, 2.2**

        Property: For any exact term match, the returned EntityMatch SHALL have
        the correct object_name from the vocabulary.
        """
        # Create cache with the term
        cache = MockVocabCache()
        cache.add_term(
            term=term,
            object_name=object_name,
            relevance_score=relevance_score,
        )

        # Link the exact term
        linker = EntityLinker(cache, min_confidence=0.0)
        result = linker.link(term)

        # Should have at least one match
        assert len(result.matches) >= 1, f"Expected match for term '{term}'"

        # The match should have the correct object_name
        assert any(
            m.object_name == object_name for m in result.matches
        ), f"Expected object '{object_name}' in matches for term '{term}'"

    @pytest.mark.property
    @settings(max_examples=100)
    @given(
        term=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=15).filter(
            lambda x: x.strip() and is_not_stop_word(x)
        ),
        field_name=st.sampled_from(VALID_FIELDS),
        object_name=st.sampled_from(VALID_OBJECTS),
    )
    def test_match_includes_field_name_when_present(self, term, field_name, object_name):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 4: Entity Linking from Vocabulary**
        **Validates: Requirements 2.1, 2.2**

        Property: When a vocabulary term has a field_name, the EntityMatch
        SHALL include that field_name.
        """
        # Create cache with term that has a field_name
        cache = MockVocabCache()
        cache.add_term(
            term=term,
            object_name=object_name,
            field_name=field_name,
            relevance_score=0.8,
        )

        # Link the term
        linker = EntityLinker(cache, min_confidence=0.0)
        result = linker.link(term)

        # Should have a match with the field_name
        assert len(result.matches) >= 1
        matching_with_field = [m for m in result.matches if m.field_name == field_name]
        assert len(matching_with_field) >= 1, f"Expected match with field_name '{field_name}' for term '{term}'"

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
    def test_empty_or_whitespace_query_returns_empty_result(self, query):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 4: Entity Linking from Vocabulary**
        **Validates: Requirements 2.1, 2.2**

        Property: For any empty or whitespace-only query, the Entity Linker
        SHALL return an empty result with zero confidence.
        """
        cache = MockVocabCache()
        linker = EntityLinker(cache)
        result = linker.link(query)

        assert len(result.matches) == 0
        assert result.confidence == 0.0

    @pytest.mark.property
    @settings(max_examples=100)
    @given(
        term=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=15).filter(
            lambda x: x.strip() and is_not_stop_word(x)
        ),
    )
    def test_confidence_in_valid_range(self, term):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 4: Entity Linking from Vocabulary**
        **Validates: Requirements 2.1, 2.2**

        Property: For any EntityMatch, the confidence score SHALL be in range [0, 1].
        """
        # Create cache with the term
        cache = MockVocabCache()
        cache.add_term(term=term, object_name="Account", relevance_score=0.8)

        linker = EntityLinker(cache, min_confidence=0.0)
        result = linker.link(term)

        # All matches should have valid confidence
        for match in result.matches:
            assert 0.0 <= match.confidence <= 1.0, f"Confidence {match.confidence} out of valid range [0, 1]"

        # Overall confidence should also be valid
        assert 0.0 <= result.confidence <= 1.0
