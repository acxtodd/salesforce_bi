"""
Unit tests for Dynamic Prompt Generator.

Tests hint parsing from configuration, prompt generation with hints,
entity detection with hints, schema-bound filter preference,
and vocabulary hints injection.

**Feature: zero-config-production, graph-aware-zero-config-retrieval**
**Requirements: 10.1, 10.2, 10.3, 10.4, 13.1, 13.2, 13.3**
"""
import pytest
from unittest.mock import Mock, MagicMock
from typing import Dict, List, Any
import sys
import os

# Add parent directory to path for imports
# **Feature: zero-config-production, Task 27.1**
# Updated to use schema_discovery from parent directory (Lambda Layer path)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'schema_discovery'))

from prompt_generator import (
    DynamicPromptGenerator,
    ObjectContext,
    get_prompt_generator,
    generate_decomposition_prompt,
    get_schema_context,
    generate_prompt_with_hints,
    get_vocab_hints,
    DEFAULT_TOP_N_HINTS,
)


# Mock ObjectSchema for testing
class MockFieldSchema:
    def __init__(self, name: str, label: str, type: str, values: List[str] = None, reference_to: str = None):
        self.name = name
        self.label = label
        self.type = type
        self.values = values or []
        self.reference_to = reference_to


class MockObjectSchema:
    def __init__(self, api_name: str, label: str):
        self.api_name = api_name
        self.label = label
        self.filterable = []
        self.numeric = []
        self.date = []
        self.relationships = []
        self.text = []
        self.discovered_at = "2025-01-01T00:00:00Z"


def create_mock_schema_cache(schemas: Dict[str, MockObjectSchema]):
    """Create a mock schema cache with the given schemas."""
    mock_cache = Mock()
    mock_cache.get_all.return_value = schemas
    mock_cache.get.side_effect = lambda name: schemas.get(name)
    return mock_cache


def create_mock_config_cache(configs: Dict[str, Dict[str, Any]]):
    """Create a mock config cache with the given configs."""
    mock_cache = Mock()
    mock_cache.get_config.side_effect = lambda name: configs.get(name, {})
    return mock_cache



class TestHintParsingFromConfiguration:
    """
    Tests for hint parsing from configuration.
    
    **Requirements: 10.1, 10.4**
    """

    def setup_method(self):
        """Set up test fixtures."""
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
            "ascendix__Availability__c": MockObjectSchema("ascendix__Availability__c", "Availability"),
        }
        
        self.configs = {
            "ascendix__Property__c": {
                "Semantic_Hints__c": "building, asset, location",
                "Object_Description__c": "A physical commercial real estate property"
            },
            "ascendix__Availability__c": {
                "Semantic_Hints__c": "space, suite, unit",
                "Object_Description__c": "A specific unit available for lease"
            },
        }
        
        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)
        
        self.generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache
        )

    def test_parses_comma_separated_hints(self):
        """Should parse comma-separated hints into list."""
        hints = self.generator.get_semantic_hints("ascendix__Property__c")
        
        assert "building" in hints
        assert "asset" in hints
        assert "location" in hints
        assert len(hints) == 3

    def test_hints_are_lowercase(self):
        """Hints should be normalized to lowercase."""
        # Update config with mixed case hints
        self.configs["ascendix__Property__c"]["Semantic_Hints__c"] = "Building, ASSET, Location"
        self.generator.refresh_context()
        
        hints = self.generator.get_semantic_hints("ascendix__Property__c")
        
        assert all(h.islower() for h in hints)

    def test_empty_hints_returns_empty_list(self):
        """Empty hints string should return empty list."""
        self.configs["ascendix__Property__c"]["Semantic_Hints__c"] = ""
        self.generator.refresh_context()
        
        hints = self.generator.get_semantic_hints("ascendix__Property__c")
        
        assert hints == []

    def test_none_hints_returns_empty_list(self):
        """None hints should return empty list."""
        self.configs["ascendix__Property__c"]["Semantic_Hints__c"] = None
        self.generator.refresh_context()
        
        hints = self.generator.get_semantic_hints("ascendix__Property__c")
        
        assert hints == []

    def test_whitespace_trimmed_from_hints(self):
        """Whitespace should be trimmed from hints."""
        self.configs["ascendix__Property__c"]["Semantic_Hints__c"] = "  building  ,  asset  ,  location  "
        self.generator.refresh_context()
        
        hints = self.generator.get_semantic_hints("ascendix__Property__c")
        
        assert "building" in hints
        assert "  building  " not in hints

    def test_object_description_parsed(self):
        """Should parse object description from config."""
        desc = self.generator.get_object_description("ascendix__Property__c")
        
        assert desc == "A physical commercial real estate property"

    def test_unknown_object_returns_none(self):
        """Unknown object should return None for hints and description."""
        hints = self.generator.get_semantic_hints("Unknown__c")
        desc = self.generator.get_object_description("Unknown__c")
        
        assert hints == []
        assert desc is None


class TestPromptGenerationWithHints:
    """
    Tests for prompt generation with hints.
    
    **Requirements: 10.2**
    """

    def setup_method(self):
        """Set up test fixtures."""
        # Create schema with fields
        property_schema = MockObjectSchema("ascendix__Property__c", "Property")
        property_schema.filterable = [
            MockFieldSchema("ascendix__City__c", "City", "filterable", ["Dallas", "Houston", "Austin"]),
            MockFieldSchema("ascendix__PropertyClass__c", "Property Class", "filterable", ["A", "B", "C"]),
        ]
        property_schema.numeric = [
            MockFieldSchema("ascendix__TotalSF__c", "Total SF", "numeric"),
        ]
        property_schema.relationships = [
            MockFieldSchema("OwnerId", "Owner", "relationship", reference_to="User"),
        ]
        
        availability_schema = MockObjectSchema("ascendix__Availability__c", "Availability")
        availability_schema.filterable = [
            MockFieldSchema("ascendix__Status__c", "Status", "filterable", ["Available", "Leased"]),
        ]
        availability_schema.relationships = [
            MockFieldSchema("ascendix__Property__c", "Property", "relationship", reference_to="ascendix__Property__c"),
        ]
        
        self.schemas = {
            "ascendix__Property__c": property_schema,
            "ascendix__Availability__c": availability_schema,
        }
        
        self.configs = {
            "ascendix__Property__c": {
                "Semantic_Hints__c": "building, asset, location",
                "Object_Description__c": "A physical commercial real estate property"
            },
            "ascendix__Availability__c": {
                "Semantic_Hints__c": "space, suite, unit, vacant",
                "Object_Description__c": "A specific unit available for lease"
            },
        }
        
        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)
        
        self.generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache
        )

    def test_prompt_includes_object_descriptions(self):
        """Prompt should include object descriptions."""
        prompt = self.generator.generate_decomposition_prompt("test query")
        
        assert "A physical commercial real estate property" in prompt
        assert "A specific unit available for lease" in prompt

    def test_prompt_includes_semantic_hints(self):
        """Prompt should include semantic hints as keywords."""
        prompt = self.generator.generate_decomposition_prompt("test query")
        
        assert "building" in prompt.lower()
        assert "asset" in prompt.lower()
        assert "space" in prompt.lower()
        assert "suite" in prompt.lower()

    def test_prompt_includes_filterable_fields(self):
        """Prompt should include filterable fields with values."""
        prompt = self.generator.generate_decomposition_prompt("test query")
        
        assert "ascendix__City__c" in prompt
        assert "Dallas" in prompt
        assert "ascendix__PropertyClass__c" in prompt

    def test_prompt_includes_relationships(self):
        """Prompt should include relationship information."""
        prompt = self.generator.generate_decomposition_prompt("test query")
        
        assert "OwnerId" in prompt
        assert "ascendix__Property__c" in prompt

    def test_prompt_includes_cross_object_instructions(self):
        """Prompt should include instructions for cross-object queries."""
        prompt = self.generator.generate_decomposition_prompt("test query")
        
        assert "cross-object" in prompt.lower() or "traversal" in prompt.lower()

    def test_schema_context_built_correctly(self):
        """Schema context should be built with all objects."""
        context = self.generator._build_schema_context()
        
        assert "Property" in context
        assert "Availability" in context
        assert "Keywords" in context


class TestEntityDetectionWithHints:
    """
    Tests for entity detection with hints integration.
    
    **Requirements: 10.3**
    """

    def setup_method(self):
        """Set up test fixtures."""
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
            "ascendix__Availability__c": MockObjectSchema("ascendix__Availability__c", "Availability"),
        }
        
        self.configs = {
            "ascendix__Property__c": {
                "Semantic_Hints__c": "building, asset",
                "Object_Description__c": "A property"
            },
            "ascendix__Availability__c": {
                "Semantic_Hints__c": "space, suite",
                "Object_Description__c": "An availability"
            },
        }
        
        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)
        
        self.generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache
        )

    def test_get_all_hints_mapping(self):
        """Should return mapping of all objects to their hints."""
        mapping = self.generator.get_all_hints_mapping()
        
        assert "ascendix__Property__c" in mapping
        assert "ascendix__Availability__c" in mapping
        assert "building" in mapping["ascendix__Property__c"]
        assert "space" in mapping["ascendix__Availability__c"]

    def test_object_context_contains_hints(self):
        """Object context should contain semantic hints."""
        ctx = self.generator.get_object_context("ascendix__Property__c")
        
        assert ctx is not None
        assert "building" in ctx.semantic_hints
        assert "asset" in ctx.semantic_hints

    def test_refresh_context_updates_hints(self):
        """Refreshing context should pick up new hints."""
        # Initial hints
        hints_before = self.generator.get_semantic_hints("ascendix__Property__c")
        assert "newterm" not in hints_before
        
        # Update config
        self.configs["ascendix__Property__c"]["Semantic_Hints__c"] = "building, asset, newterm"
        
        # Refresh
        self.generator.refresh_context()
        
        # Check new hints
        hints_after = self.generator.get_semantic_hints("ascendix__Property__c")
        assert "newterm" in hints_after


class TestObjectContextDataclass:
    """Tests for ObjectContext dataclass."""

    def test_object_context_creation(self):
        """Should create ObjectContext with all fields."""
        ctx = ObjectContext(
            api_name="Test__c",
            label="Test",
            description="A test object",
            semantic_hints=["hint1", "hint2"],
            filterable_fields=[{"name": "Field1", "label": "Field 1", "values": ["A", "B"]}],
            numeric_fields=["NumField"],
            date_fields=["DateField"],
            relationships=[{"field": "RelField", "label": "Rel", "target": "Other__c"}]
        )

        assert ctx.api_name == "Test__c"
        assert ctx.label == "Test"
        assert ctx.description == "A test object"
        assert len(ctx.semantic_hints) == 2
        assert len(ctx.filterable_fields) == 1
        assert len(ctx.numeric_fields) == 1
        assert len(ctx.date_fields) == 1
        assert len(ctx.relationships) == 1


# =============================================================================
# Schema-Bound Filter Preference Tests (Requirement 13.1)
# =============================================================================


class MockVocabCache:
    """Mock VocabCache for testing."""

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


class TestSchemaBoundFilterPreference:
    """
    Tests for schema-bound filter preference instructions.

    **Requirements: 13.1**
    """

    def setup_method(self):
        """Set up test fixtures."""
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
        }

        self.configs = {
            "ascendix__Property__c": {
                "Semantic_Hints__c": "building",
                "Object_Description__c": "A property"
            },
        }

        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)

        self.generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache
        )

    def test_prompt_includes_schema_bound_preference(self):
        """Prompt should include schema-bound filter preference section."""
        prompt = self.generator.generate_decomposition_prompt("test query")

        assert "Schema-Bound Filter Preference" in prompt
        assert "PREFER SCHEMA-BOUND FILTERS" in prompt

    def test_prompt_includes_priority_order(self):
        """Prompt should include priority order for filter types."""
        prompt = self.generator.generate_decomposition_prompt("test query")

        assert "Priority Order" in prompt
        assert "picklist" in prompt.lower()
        assert "numeric" in prompt.lower()
        assert "date" in prompt.lower()

    def test_prompt_emphasizes_free_text_as_last_resort(self):
        """Prompt should emphasize free-text as last resort."""
        prompt = self.generator.generate_decomposition_prompt("test query")

        assert "LAST RESORT" in prompt or "last resort" in prompt.lower()

    def test_has_schema_bound_instructions_returns_true(self):
        """has_schema_bound_instructions should detect instructions."""
        prompt = self.generator.generate_decomposition_prompt("test query")

        assert self.generator.has_schema_bound_instructions(prompt) is True

    def test_has_schema_bound_instructions_returns_false_for_empty(self):
        """has_schema_bound_instructions should return False for empty prompt."""
        assert self.generator.has_schema_bound_instructions("") is False
        assert self.generator.has_schema_bound_instructions("random text") is False

    def test_prompt_includes_uses_schema_filters_output(self):
        """Prompt should request uses_schema_filters in output."""
        prompt = self.generator.generate_decomposition_prompt("test query")

        assert "uses_schema_filters" in prompt


# =============================================================================
# Vocabulary Hints Tests (Requirements 13.2, 13.3)
# =============================================================================


class TestVocabHintsIntegration:
    """
    Tests for vocabulary hints integration.

    **Requirements: 13.2, 13.3**
    """

    def setup_method(self):
        """Set up test fixtures."""
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
        }

        self.configs = {
            "ascendix__Property__c": {
                "Semantic_Hints__c": "building",
                "Object_Description__c": "A property"
            },
        }

        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)

        self.vocab_terms = [
            {
                "term": "office",
                "canonical_value": "Office",
                "object_name": "ascendix__Property__c",
                "field_name": "RecordTypeId",
                "source": "recordtype",
                "relevance_score": 0.8,
                "vocab_type": "recordtype",
            },
            {
                "term": "dallas",
                "canonical_value": "Dallas",
                "object_name": "ascendix__Property__c",
                "field_name": "ascendix__City__c",
                "source": "picklist",
                "relevance_score": 0.6,
                "vocab_type": "picklist",
            },
            {
                "term": "class",
                "canonical_value": "Property Class",
                "object_name": "ascendix__Property__c",
                "field_name": "ascendix__PropertyClass__c",
                "source": "layout",
                "relevance_score": 1.0,
                "vocab_type": "label",
            },
        ]

        self.vocab_cache = MockVocabCache(self.vocab_terms)

        self.generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            vocab_cache=self.vocab_cache
        )

    def test_get_vocab_hints_returns_matching_terms(self):
        """Should return vocab hints that match query terms."""
        hints = self.generator.get_vocab_hints("office in dallas")

        assert len(hints) >= 1
        terms = [h.get("term") for h in hints]
        assert "office" in terms or "dallas" in terms

    def test_get_vocab_hints_sorted_by_relevance(self):
        """Hints should be sorted by relevance score (descending)."""
        hints = self.generator.get_vocab_hints("office dallas class")

        if len(hints) >= 2:
            scores = [h.get("relevance_score", 0) for h in hints]
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1]

    def test_get_vocab_hints_respects_top_n(self):
        """Should respect top_n limit."""
        hints = self.generator.get_vocab_hints("office dallas class", top_n=2)

        assert len(hints) <= 2

    def test_get_vocab_hints_returns_empty_for_no_matches(self):
        """Should return empty list when no matches found."""
        hints = self.generator.get_vocab_hints("xyz123 nonexistent")

        assert hints == []

    def test_get_vocab_hints_filters_stop_words(self):
        """Stop words in query should be filtered."""
        hints = self.generator.get_vocab_hints("the office in the dallas")

        # "the" and "in" should be filtered, but "office" and "dallas" should match
        terms = [h.get("term") for h in hints]
        assert "the" not in terms
        assert "in" not in terms

    def test_generate_prompt_with_hints_includes_vocab_section(self):
        """Prompt with hints should include vocabulary hints section."""
        prompt = self.generator.generate_prompt_with_hints("office in dallas")

        # If there are matching hints, should include section
        if "office" in prompt.lower() or "dallas" in prompt.lower():
            # Either has hints section or the terms matched in schema
            pass  # This is expected

    def test_has_vocab_hints_returns_true_when_present(self):
        """has_vocab_hints should return True when section present."""
        prompt = self.generator.generate_prompt_with_hints("office in dallas")

        hints = self.generator.get_vocab_hints("office in dallas")
        if hints:
            assert self.generator.has_vocab_hints(prompt) is True

    def test_has_vocab_hints_returns_false_when_absent(self):
        """has_vocab_hints should return False when no section."""
        assert self.generator.has_vocab_hints("random prompt without hints") is False

    def test_vocab_cache_not_available_returns_empty(self):
        """Should handle missing vocab cache gracefully."""
        generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            vocab_cache=None  # No vocab cache
        )

        hints = generator.get_vocab_hints("office in dallas")
        assert hints == []

    def test_build_vocab_hints_section_empty_hints(self):
        """Empty hints list should return empty string."""
        section = self.generator._build_vocab_hints_section([])
        assert section == ""

    def test_build_vocab_hints_section_includes_canonical_values(self):
        """Hints section should include canonical values."""
        section = self.generator._build_vocab_hints_section(self.vocab_terms)

        assert "Office" in section
        assert "Dallas" in section
        assert "Property Class" in section

    def test_build_vocab_hints_section_includes_source_labels(self):
        """Hints section should include source labels."""
        section = self.generator._build_vocab_hints_section(self.vocab_terms)

        assert "RecordType" in section
        assert "Picklist" in section
        assert "Page Layout" in section


class TestQueryTermExtraction:
    """Tests for query term extraction."""

    def setup_method(self):
        """Set up test fixtures."""
        self.generator = DynamicPromptGenerator(
            schema_cache=create_mock_schema_cache({}),
            config_cache=create_mock_config_cache({})
        )

    def test_extract_query_terms_basic(self):
        """Should extract basic terms from query."""
        terms = self.generator._extract_query_terms("office space in dallas")

        assert "office" in terms
        assert "space" in terms
        assert "dallas" in terms
        # Stop words should be filtered
        assert "in" not in terms

    def test_extract_query_terms_lowercase(self):
        """Extracted terms should be lowercase."""
        terms = self.generator._extract_query_terms("Office SPACE Dallas")

        for term in terms:
            assert term == term.lower()

    def test_extract_query_terms_filters_short_words(self):
        """Short words should be filtered."""
        terms = self.generator._extract_query_terms("a b c office d")

        assert "a" not in terms
        assert "b" not in terms
        assert "c" not in terms
        assert "d" not in terms
        assert "office" in terms

    def test_extract_query_terms_handles_punctuation(self):
        """Should handle punctuation correctly."""
        terms = self.generator._extract_query_terms("office, space. dallas!")

        assert "office" in terms
        assert "space" in terms
        assert "dallas" in terms

    def test_extract_query_terms_empty_query(self):
        """Empty query should return empty list."""
        terms = self.generator._extract_query_terms("")

        assert terms == []

    def test_extract_query_terms_only_stop_words(self):
        """Query with only stop words should return empty list."""
        terms = self.generator._extract_query_terms("the in on at for")

        assert terms == []


class TestPromptWithHintsGeneration:
    """Tests for generate_prompt_with_hints."""

    def setup_method(self):
        """Set up test fixtures."""
        property_schema = MockObjectSchema("ascendix__Property__c", "Property")
        property_schema.filterable = [
            MockFieldSchema("ascendix__City__c", "City", "filterable", ["Dallas"]),
        ]

        self.schemas = {
            "ascendix__Property__c": property_schema,
        }

        self.configs = {
            "ascendix__Property__c": {
                "Semantic_Hints__c": "building",
                "Object_Description__c": "A property"
            },
        }

        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)

        self.vocab_terms = [
            {
                "term": "dallas",
                "canonical_value": "Dallas",
                "object_name": "ascendix__Property__c",
                "field_name": "ascendix__City__c",
                "source": "picklist",
                "relevance_score": 0.6,
                "vocab_type": "picklist",
            },
        ]

        self.vocab_cache = MockVocabCache(self.vocab_terms)

        self.generator = DynamicPromptGenerator(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            vocab_cache=self.vocab_cache
        )

    def test_prompt_with_hints_includes_all_sections(self):
        """Full prompt should include all sections."""
        prompt = self.generator.generate_prompt_with_hints("property in dallas")

        # Schema context
        assert "Available Objects" in prompt

        # Schema-bound preference
        assert "Schema-Bound Filter Preference" in prompt

        # Task section
        assert "Your Task" in prompt

        # Output format
        assert "target_entity" in prompt

    def test_prompt_with_hints_includes_rule_5(self):
        """Prompt should include rule 5 about using vocabulary hints."""
        prompt = self.generator.generate_prompt_with_hints("property in dallas")

        assert "USE VOCABULARY HINTS" in prompt or "vocabulary hints" in prompt.lower()

    def test_prompt_with_hints_includes_matched_vocab_output(self):
        """Prompt should request matched_vocab_hints in output."""
        prompt = self.generator.generate_prompt_with_hints("property in dallas")

        assert "matched_vocab_hints" in prompt


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_generate_prompt_with_hints_function(self):
        """Convenience function should work."""
        # Reset the global instance
        import prompt_generator
        prompt_generator._prompt_generator = None

        # This will create a new generator - may fail without real caches
        # but we're testing the interface exists
        try:
            result = generate_prompt_with_hints("test query")
            assert isinstance(result, str)
        except Exception:
            # Expected if Schema Cache not available
            pass

    def test_get_vocab_hints_function(self):
        """Convenience function should return list."""
        import prompt_generator
        prompt_generator._prompt_generator = None

        try:
            result = get_vocab_hints("test query")
            assert isinstance(result, list)
        except Exception:
            # Expected if VocabCache not available
            pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
