"""
Property-Based Tests for Prompt Generator.

**Feature: graph-aware-zero-config-retrieval**

Tests the following properties:
- Property 17: Prompt Schema-Bound Preference (Requirements 13.1, 13.2, 13.3)
"""

import os
import sys
from typing import Any, Dict, List
from unittest.mock import Mock, MagicMock

import pytest
from hypothesis import given, strategies as st, settings, assume

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prompt_generator import (
    DynamicPromptGenerator,
    ObjectContext,
    DEFAULT_TOP_N_HINTS,
)


# =============================================================================
# Mock Classes for Property Testing
# =============================================================================


class MockFieldSchema:
    """Mock field schema for testing."""

    def __init__(
        self,
        name: str,
        label: str,
        values: List[str] = None,
        reference_to: str = None,
    ):
        self.name = name
        self.label = label
        self.values = values or []
        self.reference_to = reference_to


class MockObjectSchema:
    """Mock object schema for testing."""

    def __init__(self, api_name: str, label: str):
        self.api_name = api_name
        self.label = label
        self.filterable = []
        self.numeric = []
        self.date = []
        self.relationships = []
        self.text = []


class MockVocabCache:
    """Mock VocabCache for property testing."""

    def __init__(self, terms: List[Dict[str, Any]] = None):
        self.terms = terms or []
        self._term_index = {t.get("term", "").lower(): t for t in self.terms}

    def lookup(self, term: str, vocab_type: str = None) -> Dict[str, Any]:
        """Look up a term."""
        return self._term_index.get(term.lower())

    def lookup_with_score(
        self, term: str, min_score: float = 0.0
    ) -> List[Dict[str, Any]]:
        """Look up term with score filtering."""
        match = self._term_index.get(term.lower())
        if match and match.get("relevance_score", 0) >= min_score:
            return [match]
        return []


def create_mock_schema_cache(schemas: Dict[str, MockObjectSchema]):
    """Create a mock schema cache."""
    mock_cache = Mock()
    mock_cache.get_all.return_value = schemas
    mock_cache.get.side_effect = lambda name: schemas.get(name)
    return mock_cache


def create_mock_config_cache(configs: Dict[str, Dict[str, Any]]):
    """Create a mock config cache."""
    mock_cache = Mock()
    mock_cache.get_config.side_effect = lambda name: configs.get(name, {})
    return mock_cache


# =============================================================================
# Strategies for Property Testing
# =============================================================================

# Query term strategy - realistic CRE terms
cre_terms = st.sampled_from([
    "office", "retail", "industrial", "warehouse", "building", "property",
    "space", "suite", "unit", "lease", "tenant", "vacancy", "available",
    "class", "downtown", "plano", "dallas", "houston", "austin", "miami",
    "sqft", "square", "feet", "broker", "deal", "sale", "negotiation",
])

# Query strategy - combinations of terms
query_strategy = st.lists(cre_terms, min_size=1, max_size=5).map(
    lambda terms: " ".join(terms)
)

# Relevance score strategy
relevance_score_strategy = st.floats(min_value=0.0, max_value=1.0)

# Source strategy
source_strategy = st.sampled_from(["layout", "recordtype", "picklist", "describe"])


@st.composite
def vocab_term_strategy(draw):
    """Generate a random vocabulary term."""
    term = draw(cre_terms)
    return {
        "term": term,
        "canonical_value": term.title(),
        "object_name": draw(st.sampled_from([
            "ascendix__Property__c",
            "ascendix__Availability__c",
            "ascendix__Lease__c",
        ])),
        "field_name": draw(st.sampled_from([
            "ascendix__City__c",
            "ascendix__PropertyClass__c",
            "ascendix__Status__c",
            None,
        ])),
        "source": draw(source_strategy),
        "relevance_score": draw(relevance_score_strategy),
        "vocab_type": draw(st.sampled_from(["label", "picklist", "recordtype"])),
    }


@st.composite
def vocab_cache_strategy(draw):
    """Generate a mock vocab cache with random terms."""
    num_terms = draw(st.integers(min_value=0, max_value=20))
    terms = [draw(vocab_term_strategy()) for _ in range(num_terms)]
    return MockVocabCache(terms)


# =============================================================================
# Property 17: Prompt Schema-Bound Preference
# Requirements: 13.1, 13.2, 13.3
# =============================================================================


class TestProperty17PromptSchemaPreference:
    """
    Property 17: Prompt Schema-Bound Preference

    **Validates: Requirements 13.1, 13.2, 13.3**

    Properties tested:
    1. All prompts contain schema-bound filter preference instructions
    2. Prompts with vocab cache include vocabulary hints section
    3. Vocabulary hints are sorted by relevance score
    4. Top-N limit is respected
    """

    def setup_method(self):
        """Set up test fixtures."""
        # Create basic schema
        property_schema = MockObjectSchema("ascendix__Property__c", "Property")
        property_schema.filterable = [
            MockFieldSchema("ascendix__City__c", "City", ["Dallas", "Houston"]),
            MockFieldSchema("ascendix__PropertyClass__c", "Class", ["A", "B", "C"]),
        ]
        property_schema.numeric = [
            MockFieldSchema("ascendix__TotalSF__c", "Total SF"),
        ]

        availability_schema = MockObjectSchema(
            "ascendix__Availability__c", "Availability"
        )
        availability_schema.filterable = [
            MockFieldSchema("ascendix__Status__c", "Status", ["Available", "Leased"]),
        ]
        availability_schema.relationships = [
            MockFieldSchema(
                "ascendix__Property__c",
                "Property",
                reference_to="ascendix__Property__c",
            ),
        ]

        self.schemas = {
            "ascendix__Property__c": property_schema,
            "ascendix__Availability__c": availability_schema,
        }

        self.configs = {
            "ascendix__Property__c": {
                "Semantic_Hints__c": "building, asset, location",
                "Object_Description__c": "A commercial property",
            },
            "ascendix__Availability__c": {
                "Semantic_Hints__c": "space, suite, unit",
                "Object_Description__c": "A leasable space",
            },
        }

        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)

    @given(query=query_strategy)
    @settings(max_examples=50, deadline=None)
    def test_prompt_always_has_schema_bound_instructions(self, query: str):
        """
        Property: All prompts contain schema-bound filter preference instructions.

        **Validates: Requirement 13.1**

        For any query, the generated prompt should include instructions
        preferring schema-bound filters over free-text matching.
        """
        generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
        )

        prompt = generator.generate_decomposition_prompt(query)

        # Should contain schema-bound instructions
        assert generator.has_schema_bound_instructions(prompt), (
            "Prompt should contain schema-bound filter preference instructions"
        )

        # Should contain key phrases
        assert "PREFER SCHEMA-BOUND FILTERS" in prompt or \
               "schema-bound" in prompt.lower(), (
            "Prompt should contain schema-bound filter preference text"
        )

    @given(query=query_strategy, vocab_cache=vocab_cache_strategy())
    @settings(max_examples=50, deadline=None)
    def test_prompt_with_hints_includes_vocab_section(
        self, query: str, vocab_cache: MockVocabCache
    ):
        """
        Property: Prompts with vocab cache include vocabulary hints section.

        **Validates: Requirement 13.2**

        When a vocab cache is provided and matches are found,
        the prompt should include a vocabulary hints section.
        """
        generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            vocab_cache=vocab_cache,
        )

        prompt = generator.generate_prompt_with_hints(query)

        # Should always have schema-bound instructions
        assert generator.has_schema_bound_instructions(prompt)

        # If vocab cache has matching terms, should have hints section
        hints = generator.get_vocab_hints(query)
        if hints:
            assert generator.has_vocab_hints(prompt), (
                "Prompt should have vocab hints section when matches found"
            )

    @given(vocab_cache=vocab_cache_strategy())
    @settings(max_examples=50, deadline=None)
    def test_vocab_hints_sorted_by_relevance(self, vocab_cache: MockVocabCache):
        """
        Property: Vocabulary hints are sorted by relevance score (descending).

        **Validates: Requirement 13.3**

        The returned hints should be sorted by relevance_score
        from highest to lowest.
        """
        generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            vocab_cache=vocab_cache,
        )

        # Use a query that might match vocab terms
        query = "office building in downtown"
        hints = generator.get_vocab_hints(query, top_n=100)

        if len(hints) >= 2:
            scores = [h.get("relevance_score", 0) for h in hints]
            # Verify descending order
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1], (
                    f"Hints should be sorted by relevance: {scores}"
                )

    @given(
        query=query_strategy,
        top_n=st.integers(min_value=1, max_value=20),
        vocab_cache=vocab_cache_strategy(),
    )
    @settings(max_examples=50, deadline=None)
    def test_top_n_limit_respected(
        self, query: str, top_n: int, vocab_cache: MockVocabCache
    ):
        """
        Property: Top-N limit is respected for vocabulary hints.

        **Validates: Requirement 13.2**

        The number of returned hints should not exceed top_n.
        """
        generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            vocab_cache=vocab_cache,
        )

        hints = generator.get_vocab_hints(query, top_n=top_n)

        assert len(hints) <= top_n, (
            f"Hints count {len(hints)} should not exceed top_n={top_n}"
        )

    @given(query=query_strategy)
    @settings(max_examples=30, deadline=None)
    def test_prompt_with_hints_has_all_sections(self, query: str):
        """
        Property: Prompt with hints has all required sections.

        **Validates: Requirements 13.1, 13.2**

        The full prompt should contain:
        - Schema context
        - Schema-bound filter preference
        - Task instructions
        - Output format specification
        """
        vocab_terms = [
            {
                "term": "office",
                "canonical_value": "Office",
                "object_name": "ascendix__Property__c",
                "field_name": "RecordTypeId",
                "source": "recordtype",
                "relevance_score": 0.8,
                "vocab_type": "recordtype",
            },
        ]
        vocab_cache = MockVocabCache(vocab_terms)

        generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            vocab_cache=vocab_cache,
        )

        prompt = generator.generate_prompt_with_hints(query)

        # Check for required sections
        assert "## Available Objects" in prompt, "Should have objects section"
        assert "Schema-Bound Filter Preference" in prompt, (
            "Should have schema-bound section"
        )
        assert "## Your Task" in prompt, "Should have task section"
        assert "target_entity" in prompt, "Should have output format"

    @given(query=st.text(min_size=0, max_size=5))
    @settings(max_examples=30, deadline=None)
    def test_empty_or_short_query_handles_gracefully(self, query: str):
        """
        Property: Empty or short queries are handled gracefully.

        For very short or empty queries, the generator should not crash
        and should still produce a valid prompt.
        """
        generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            vocab_cache=MockVocabCache([]),
        )

        # Should not raise
        prompt = generator.generate_decomposition_prompt(query)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

        # generate_prompt_with_hints should also work
        prompt_with_hints = generator.generate_prompt_with_hints(query)
        assert isinstance(prompt_with_hints, str)
        assert len(prompt_with_hints) > 0


class TestQueryTermExtraction:
    """Tests for query term extraction logic."""

    def setup_method(self):
        """Set up test fixtures."""
        self.generator = DynamicPromptGenerator(
            schema_cache=create_mock_schema_cache({}),
            config_cache=create_mock_config_cache({}),
        )

    @given(query=query_strategy)
    @settings(max_examples=50, deadline=None)
    def test_extracted_terms_are_lowercase(self, query: str):
        """
        Property: All extracted terms should be lowercase.
        """
        terms = self.generator._extract_query_terms(query)

        for term in terms:
            assert term == term.lower(), f"Term '{term}' should be lowercase"

    @given(query=query_strategy)
    @settings(max_examples=50, deadline=None)
    def test_extracted_terms_have_minimum_length(self, query: str):
        """
        Property: All extracted terms should meet minimum length requirement.
        """
        from prompt_generator import MIN_WORD_LENGTH

        terms = self.generator._extract_query_terms(query)

        for term in terms:
            assert len(term) >= MIN_WORD_LENGTH, (
                f"Term '{term}' should have length >= {MIN_WORD_LENGTH}"
            )

    @given(query=query_strategy)
    @settings(max_examples=50, deadline=None)
    def test_stop_words_filtered(self, query: str):
        """
        Property: Common stop words should be filtered out.
        """
        terms = self.generator._extract_query_terms(query)
        stop_words = {'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'and'}

        for term in terms:
            assert term not in stop_words, (
                f"Stop word '{term}' should be filtered"
            )


class TestVocabHintsSection:
    """Tests for vocab hints section building."""

    def setup_method(self):
        """Set up test fixtures."""
        self.generator = DynamicPromptGenerator(
            schema_cache=create_mock_schema_cache({}),
            config_cache=create_mock_config_cache({}),
        )

    def test_empty_hints_returns_empty_string(self):
        """Empty hints list should return empty string."""
        section = self.generator._build_vocab_hints_section([])
        assert section == ""

    @given(hints=st.lists(vocab_term_strategy(), min_size=1, max_size=10))
    @settings(max_examples=30, deadline=None)
    def test_hints_section_includes_all_hints(self, hints: List[Dict[str, Any]]):
        """
        Property: Hints section should include all provided hints.
        """
        section = self.generator._build_vocab_hints_section(hints)

        # Should have header
        assert "## Vocabulary Hints" in section

        # Should include canonical values
        for hint in hints:
            canonical = hint.get("canonical_value", hint.get("term", ""))
            assert canonical in section, f"Should include '{canonical}'"

    @given(hints=st.lists(vocab_term_strategy(), min_size=1, max_size=5))
    @settings(max_examples=30, deadline=None)
    def test_hints_section_includes_relevance_scores(
        self, hints: List[Dict[str, Any]]
    ):
        """
        Property: Hints section should include relevance scores.

        **Validates: Requirement 13.3**
        """
        section = self.generator._build_vocab_hints_section(hints)

        # Should include score indicators
        assert "score:" in section.lower(), "Should include relevance scores"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
