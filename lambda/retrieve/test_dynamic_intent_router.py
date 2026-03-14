"""
Property-based tests for Dynamic Intent Router.

Tests the dynamic entity detection from Schema Cache using hypothesis.

**Feature: zero-config-production**
**Property 11: Dynamic Entity Detection**
**Validates: Requirements 7.1, 7.2, 7.4**
"""
import pytest
from hypothesis import given, strategies as st, settings, assume, Phase
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, List, Any
import sys
import os

# Add parent directory to path for imports
# **Feature: zero-config-production, Task 27.1**
# Updated to use schema_discovery from parent directory (Lambda Layer path)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'schema_discovery'))

from dynamic_intent_router import (
    DynamicIntentRouter,
    DynamicEntityPatterns,
    EntityMatch,
    get_dynamic_router,
    detect_entities_dynamic,
    detect_target_entity_dynamic,
)


# Hypothesis settings for property tests
settings.register_profile(
    "zero-config",
    max_examples=100,
    deadline=None,
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
)
settings.load_profile("zero-config")


# Mock ObjectSchema for testing
class MockFieldSchema:
    def __init__(self, name: str, label: str, type: str):
        self.name = name
        self.label = label
        self.type = type


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


class TestDynamicEntityDetection:
    """
    **Property 11: Dynamic Entity Detection**
    **Validates: Requirements 7.1, 7.2, 7.4**
    
    For any object in the Schema Cache, the Intent Router SHALL recognize 
    that object's API name, label, and plural label in natural language 
    queries without requiring code changes.
    """

    def setup_method(self):
        """Set up test fixtures."""
        # Create mock schemas for various objects
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
            "ascendix__Availability__c": MockObjectSchema("ascendix__Availability__c", "Availability"),
            "ascendix__Deal__c": MockObjectSchema("ascendix__Deal__c", "Deal"),
            "Account": MockObjectSchema("Account", "Account"),
            "Contact": MockObjectSchema("Contact", "Contact"),
            "Custom_Vehicle__c": MockObjectSchema("Custom_Vehicle__c", "Vehicle"),
        }
        
        self.configs = {
            "ascendix__Property__c": {"Semantic_Hints__c": "building, asset, location"},
            "ascendix__Availability__c": {"Semantic_Hints__c": "space, suite, unit, vacant"},
            "ascendix__Deal__c": {"Semantic_Hints__c": "transaction, opportunity"},
            "Account": {"Semantic_Hints__c": "company, organization, client"},
            "Contact": {"Semantic_Hints__c": "person, people"},
            "Custom_Vehicle__c": {"Semantic_Hints__c": "car, truck, automobile"},
        }
        
        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)
        
        self.router = DynamicIntentRouter(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            auto_refresh=False
        )

    @given(st.sampled_from([
        ("Property", "ascendix__Property__c"),
        ("Properties", "ascendix__Property__c"),
        ("Availability", "ascendix__Availability__c"),
        ("Availabilities", "ascendix__Availability__c"),
        ("Deal", "ascendix__Deal__c"),
        ("Deals", "ascendix__Deal__c"),
        ("Account", "Account"),
        ("Accounts", "Account"),
        ("Contact", "Contact"),
        ("Contacts", "Contact"),
        ("Vehicle", "Custom_Vehicle__c"),
        ("Vehicles", "Custom_Vehicle__c"),
    ]))
    @settings(max_examples=50)
    def test_property_11_label_detection(self, label_and_api: tuple):
        """
        **Property 11: Dynamic Entity Detection**
        **Validates: Requirements 7.1, 7.2, 7.4**
        
        For any object label or plural label, the router should detect the entity.
        """
        label, expected_api = label_and_api
        query = f"Show me all {label}"
        
        matches = self.router.detect_entities(query)
        
        # Should find at least one match
        assert len(matches) > 0, f"No matches found for '{label}' in query '{query}'"
        
        # The expected API should be in the matches
        api_names = [m.api_name for m in matches]
        assert expected_api in api_names, \
            f"Expected {expected_api} in matches for '{label}', got {api_names}"

    @given(st.sampled_from([
        ("building", "ascendix__Property__c"),
        ("asset", "ascendix__Property__c"),
        ("space", "ascendix__Availability__c"),
        ("suite", "ascendix__Availability__c"),
        ("vacant", "ascendix__Availability__c"),
        ("transaction", "ascendix__Deal__c"),
        ("company", "Account"),
        ("organization", "Account"),
        ("person", "Contact"),
        ("car", "Custom_Vehicle__c"),
        ("automobile", "Custom_Vehicle__c"),
    ]))
    @settings(max_examples=50)
    def test_property_11_semantic_hint_detection(self, hint_and_api: tuple):
        """
        **Property 11: Dynamic Entity Detection**
        **Validates: Requirements 7.5, 10.1, 10.2, 10.3**
        
        For any semantic hint configured for an object, the router should 
        detect the entity when the hint is used in a query.
        """
        hint, expected_api = hint_and_api
        query = f"Find me a {hint}"
        
        matches = self.router.detect_entities(query)
        
        # Should find at least one match
        assert len(matches) > 0, f"No matches found for hint '{hint}' in query '{query}'"
        
        # The expected API should be in the matches
        api_names = [m.api_name for m in matches]
        assert expected_api in api_names, \
            f"Expected {expected_api} in matches for hint '{hint}', got {api_names}"


    @given(st.text(alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')), min_size=1, max_size=100))
    @settings(max_examples=100)
    def test_property_11_all_queries_return_valid_matches(self, query: str):
        """
        **Property 11: Dynamic Entity Detection**
        **Validates: Requirements 7.1, 7.2, 7.4**
        
        For any query string, detect_entities should return a valid list 
        of EntityMatch objects (possibly empty).
        """
        assume(query.strip())  # Skip empty queries
        
        matches = self.router.detect_entities(query)
        
        # Should always return a list
        assert isinstance(matches, list)
        
        # All matches should be valid EntityMatch objects
        for match in matches:
            assert isinstance(match, EntityMatch)
            assert match.api_name in self.schemas
            assert 0.0 <= match.confidence <= 1.0
            assert match.match_type in ["api_name", "label", "plural", "hint", "partial"]

    def test_new_object_recognized_without_code_changes(self):
        """
        **Property 11: Dynamic Entity Detection**
        **Validates: Requirements 7.2**
        
        When a new object is added to Schema Cache, it should be recognized
        without any code changes.
        """
        # Add a new object to the schema cache
        new_schema = MockObjectSchema("Custom_Widget__c", "Widget")
        self.schemas["Custom_Widget__c"] = new_schema
        self.configs["Custom_Widget__c"] = {"Semantic_Hints__c": "gadget, device"}
        
        # Refresh patterns to pick up new object
        self.router.refresh_patterns()
        
        # Query for the new object
        query = "Show me all Widgets"
        matches = self.router.detect_entities(query)
        
        # Should find the new object
        api_names = [m.api_name for m in matches]
        assert "Custom_Widget__c" in api_names, \
            f"New object Widget not found in matches: {api_names}"
        
        # Also test semantic hint
        query2 = "Find me a gadget"
        matches2 = self.router.detect_entities(query2)
        api_names2 = [m.api_name for m in matches2]
        assert "Custom_Widget__c" in api_names2, \
            f"New object not found via hint 'gadget': {api_names2}"


class TestPatternBuilding:
    """Tests for entity pattern building functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
        }
        self.configs = {
            "ascendix__Property__c": {"Semantic_Hints__c": "building, asset"},
        }
        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)
        self.router = DynamicIntentRouter(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            auto_refresh=False
        )

    def test_pattern_includes_api_name(self):
        """Pattern should include cleaned API name."""
        self.router.refresh_patterns()
        patterns = self.router.get_all_entity_patterns()
        
        assert "ascendix__Property__c" in patterns
        pattern = patterns["ascendix__Property__c"]
        assert pattern["label"] == "Property"

    def test_pattern_includes_plural(self):
        """Pattern should include plural form."""
        self.router.refresh_patterns()
        patterns = self.router.get_all_entity_patterns()
        
        pattern = patterns["ascendix__Property__c"]
        assert pattern["plural_label"] == "Properties"

    def test_pattern_includes_semantic_hints(self):
        """Pattern should include semantic hints."""
        self.router.refresh_patterns()
        patterns = self.router.get_all_entity_patterns()
        
        pattern = patterns["ascendix__Property__c"]
        assert "building" in pattern["semantic_hints"]
        assert "asset" in pattern["semantic_hints"]


class TestPluralization:
    """Tests for the pluralization helper."""

    def setup_method(self):
        """Set up test fixtures."""
        self.router = DynamicIntentRouter(
            schema_cache=Mock(),
            config_cache=Mock(),
            auto_refresh=False
        )

    @pytest.mark.parametrize("singular,expected_plural", [
        ("Property", "Properties"),
        ("Availability", "Availabilities"),
        ("Deal", "Deals"),
        ("Account", "Accounts"),
        ("Company", "Companies"),
        ("Opportunity", "Opportunities"),
        ("Activity", "Activities"),
        ("Box", "Boxes"),
        ("Brush", "Brushes"),
        ("Match", "Matches"),
    ])
    def test_pluralization(self, singular: str, expected_plural: str):
        """Test pluralization of various words."""
        result = self.router._pluralize(singular)
        assert result == expected_plural, f"Expected '{expected_plural}' for '{singular}', got '{result}'"


class TestAPINameCleaning:
    """Tests for API name cleaning."""

    def setup_method(self):
        """Set up test fixtures."""
        self.router = DynamicIntentRouter(
            schema_cache=Mock(),
            config_cache=Mock(),
            auto_refresh=False
        )

    @pytest.mark.parametrize("api_name,expected_clean", [
        ("ascendix__Property__c", "Property"),
        ("Custom_Vehicle__c", "Custom_Vehicle"),  # No namespace, keeps full name
        ("Account", "Account"),
        ("Contact", "Contact"),
        ("ns__Custom_Object__c", "Custom_Object"),
        ("MyObject__mdt", "MyObject"),
    ])
    def test_api_name_cleaning(self, api_name: str, expected_clean: str):
        """Test cleaning of API names."""
        result = self.router._clean_api_name(api_name)
        assert result == expected_clean, f"Expected '{expected_clean}' for '{api_name}', got '{result}'"


class TestEntityRecognition:
    """Tests for entity recognition functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
            "ascendix__Availability__c": MockObjectSchema("ascendix__Availability__c", "Availability"),
        }
        self.configs = {
            "ascendix__Property__c": {"Semantic_Hints__c": "building"},
            "ascendix__Availability__c": {"Semantic_Hints__c": "space, suite"},
        }
        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)
        self.router = DynamicIntentRouter(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            auto_refresh=False
        )

    def test_is_entity_recognized(self):
        """Test entity recognition check."""
        self.router.refresh_patterns()
        
        assert self.router.is_entity_recognized("ascendix__Property__c")
        assert self.router.is_entity_recognized("ascendix__Availability__c")
        assert not self.router.is_entity_recognized("Unknown__c")

    def test_get_entity_labels(self):
        """Test getting entity labels."""
        self.router.refresh_patterns()
        
        labels = self.router.get_entity_labels()
        assert labels["ascendix__Property__c"] == "Property"
        assert labels["ascendix__Availability__c"] == "Availability"

    def test_get_entity_hints(self):
        """Test getting entity hints."""
        self.router.refresh_patterns()
        
        hints = self.router.get_entity_hints("ascendix__Property__c")
        assert "building" in hints
        
        hints2 = self.router.get_entity_hints("ascendix__Availability__c")
        assert "space" in hints2
        assert "suite" in hints2

    def test_detect_target_entity(self):
        """Test detecting primary target entity."""
        self.router.refresh_patterns()
        
        # Should detect Property as target
        target = self.router.detect_target_entity("Show me all Properties in Dallas")
        assert target == "ascendix__Property__c"
        
        # Should detect Availability as target
        target2 = self.router.detect_target_entity("Find available spaces")
        assert target2 == "ascendix__Availability__c"


class TestMatchConfidence:
    """Tests for match confidence calculation."""

    def setup_method(self):
        """Set up test fixtures."""
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
        }
        self.configs = {
            "ascendix__Property__c": {"Semantic_Hints__c": "building"},
        }
        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)
        self.router = DynamicIntentRouter(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            auto_refresh=False
        )

    def test_label_match_has_highest_confidence(self):
        """Label matches should have highest confidence."""
        self.router.refresh_patterns()
        
        matches = self.router.detect_entities("Show me Property")
        assert len(matches) > 0
        
        # Label or api_name match should have high confidence (both are valid)
        match = matches[0]
        assert match.confidence >= 0.85  # Both label and api_name have high confidence

    def test_hint_match_has_lower_confidence(self):
        """Hint matches should have lower confidence than label."""
        self.router.refresh_patterns()
        
        matches = self.router.detect_entities("Show me a building")
        assert len(matches) > 0
        
        # Hint match should have lower confidence
        match = matches[0]
        assert match.match_type == "hint"
        assert match.confidence < 0.9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])



class TestEntityDetectionFromSchema:
    """
    Unit tests for entity detection from schema.
    
    **Requirements: 7.1, 7.2, 7.3, 7.4**
    """

    def setup_method(self):
        """Set up test fixtures."""
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
            "ascendix__Availability__c": MockObjectSchema("ascendix__Availability__c", "Availability"),
            "ascendix__Deal__c": MockObjectSchema("ascendix__Deal__c", "Deal"),
        }
        self.configs = {
            "ascendix__Property__c": {"Semantic_Hints__c": "building, asset"},
            "ascendix__Availability__c": {"Semantic_Hints__c": "space, suite"},
            "ascendix__Deal__c": {"Semantic_Hints__c": "transaction"},
        }
        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)
        self.router = DynamicIntentRouter(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            auto_refresh=False
        )

    def test_detects_entity_by_label(self):
        """Should detect entity by its label."""
        self.router.refresh_patterns()
        
        matches = self.router.detect_entities("Show me all Properties")
        assert len(matches) == 1
        assert matches[0].api_name == "ascendix__Property__c"
        assert matches[0].label == "Property"

    def test_detects_entity_by_plural_label(self):
        """Should detect entity by its plural label."""
        self.router.refresh_patterns()
        
        matches = self.router.detect_entities("List all Availabilities")
        assert len(matches) == 1
        assert matches[0].api_name == "ascendix__Availability__c"

    def test_detects_entity_by_semantic_hint(self):
        """Should detect entity by semantic hint."""
        self.router.refresh_patterns()
        
        matches = self.router.detect_entities("Find me a building")
        assert len(matches) == 1
        assert matches[0].api_name == "ascendix__Property__c"
        assert matches[0].match_type == "hint"

    def test_detects_multiple_entities(self):
        """Should detect multiple entities in a query."""
        self.router.refresh_patterns()
        
        matches = self.router.detect_entities("Show Properties and Deals")
        assert len(matches) == 2
        api_names = {m.api_name for m in matches}
        assert "ascendix__Property__c" in api_names
        assert "ascendix__Deal__c" in api_names

    def test_case_insensitive_detection(self):
        """Should detect entities regardless of case."""
        self.router.refresh_patterns()
        
        matches1 = self.router.detect_entities("PROPERTY")
        matches2 = self.router.detect_entities("property")
        matches3 = self.router.detect_entities("Property")
        
        assert len(matches1) == 1
        assert len(matches2) == 1
        assert len(matches3) == 1
        assert matches1[0].api_name == matches2[0].api_name == matches3[0].api_name

    def test_no_match_for_unknown_entity(self):
        """Should return empty list for unknown entities."""
        self.router.refresh_patterns()
        
        matches = self.router.detect_entities("Show me all Widgets")
        assert len(matches) == 0


class TestPatternRefresh:
    """
    Unit tests for pattern refresh functionality.
    
    **Requirements: 7.2**
    """

    def setup_method(self):
        """Set up test fixtures."""
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
        }
        self.configs = {
            "ascendix__Property__c": {"Semantic_Hints__c": "building"},
        }
        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)
        self.router = DynamicIntentRouter(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            auto_refresh=False
        )

    def test_refresh_loads_patterns(self):
        """Refresh should load patterns from schema cache."""
        assert not self.router._patterns_built
        
        self.router.refresh_patterns()
        
        assert self.router._patterns_built
        assert len(self.router._entity_patterns) == 1

    def test_refresh_updates_patterns(self):
        """Refresh should update patterns when schema changes."""
        self.router.refresh_patterns()
        assert len(self.router._entity_patterns) == 1
        
        # Add new schema
        self.schemas["New_Object__c"] = MockObjectSchema("New_Object__c", "NewObject")
        
        self.router.refresh_patterns()
        assert len(self.router._entity_patterns) == 2

    def test_auto_refresh_on_first_detect(self):
        """Should auto-refresh patterns on first detect call."""
        router = DynamicIntentRouter(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            auto_refresh=True
        )
        
        assert not router._patterns_built
        
        # First detect should trigger refresh
        router.detect_entities("test query")
        
        assert router._patterns_built


class TestIntegrationWithIntentRouter:
    """
    Unit tests for integration with existing IntentRouter.
    
    **Requirements: 7.1, 7.2, 7.3, 7.4**
    """

    def test_dynamic_router_module_functions(self):
        """Test module-level convenience functions."""
        # Create mock caches
        schemas = {
            "Test__c": MockObjectSchema("Test__c", "Test"),
        }
        configs = {
            "Test__c": {"Semantic_Hints__c": "example"},
        }
        schema_cache = create_mock_schema_cache(schemas)
        config_cache = create_mock_config_cache(configs)
        
        # Get router with mocks
        router = get_dynamic_router(schema_cache, config_cache)
        assert router is not None
        
        # Test detect functions
        matches = detect_entities_dynamic("Show me Test")
        # May be empty if global router not initialized with our mocks
        assert isinstance(matches, list)

    def test_entity_match_dataclass(self):
        """Test EntityMatch dataclass."""
        match = EntityMatch(
            api_name="Test__c",
            label="Test",
            matched_term="test",
            match_type="label",
            confidence=0.95
        )
        
        assert match.api_name == "Test__c"
        assert match.label == "Test"
        assert match.matched_term == "test"
        assert match.match_type == "label"
        assert match.confidence == 0.95

    def test_dynamic_entity_patterns_dataclass(self):
        """Test DynamicEntityPatterns dataclass."""
        pattern = DynamicEntityPatterns(
            api_name="Test__c",
            label="Test",
            plural_label="Tests",
            semantic_hints=["example", "sample"],
            pattern=re.compile(r'\btest\b', re.IGNORECASE)
        )
        
        result = pattern.to_dict()
        assert result["api_name"] == "Test__c"
        assert result["label"] == "Test"
        assert result["plural_label"] == "Tests"
        assert result["semantic_hints"] == ["example", "sample"]


# Import re for the test above
import re



class TestProperty12SemanticHintsRecognition:
    """
    **Property 12: Semantic Hints Recognition**
    **Validates: Requirements 7.5, 10.1, 10.2, 10.3**
    
    For any object with configured Semantic_Hints__c, the Intent Router SHALL 
    recognize those hint keywords as references to that object in natural 
    language queries.
    """

    def setup_method(self):
        """Set up test fixtures with semantic hints."""
        self.schemas = {
            "ascendix__Property__c": MockObjectSchema("ascendix__Property__c", "Property"),
            "ascendix__Availability__c": MockObjectSchema("ascendix__Availability__c", "Availability"),
            "ascendix__Deal__c": MockObjectSchema("ascendix__Deal__c", "Deal"),
            "ascendix__Lease__c": MockObjectSchema("ascendix__Lease__c", "Lease"),
            "Account": MockObjectSchema("Account", "Account"),
        }
        
        # Configure semantic hints for each object
        self.configs = {
            "ascendix__Property__c": {
                "Semantic_Hints__c": "building, asset, location, site, tower",
                "Object_Description__c": "A physical commercial real estate property"
            },
            "ascendix__Availability__c": {
                "Semantic_Hints__c": "space, suite, unit, vacant, vacancy",
                "Object_Description__c": "A specific unit available for lease"
            },
            "ascendix__Deal__c": {
                "Semantic_Hints__c": "transaction, opportunity, pipeline, fee",
                "Object_Description__c": "A CRE transaction being tracked"
            },
            "ascendix__Lease__c": {
                "Semantic_Hints__c": "tenant, rental, expiring, occupancy",
                "Object_Description__c": "A lease agreement"
            },
            "Account": {
                "Semantic_Hints__c": "company, organization, client, customer",
                "Object_Description__c": "A company or organization"
            },
        }
        
        self.schema_cache = create_mock_schema_cache(self.schemas)
        self.config_cache = create_mock_config_cache(self.configs)
        
        self.router = DynamicIntentRouter(
            schema_cache=self.schema_cache,
            config_cache=self.config_cache,
            auto_refresh=False
        )

    @given(st.sampled_from([
        # (hint_keyword, expected_api_name)
        ("building", "ascendix__Property__c"),
        ("asset", "ascendix__Property__c"),
        ("location", "ascendix__Property__c"),
        ("site", "ascendix__Property__c"),
        ("tower", "ascendix__Property__c"),
        ("space", "ascendix__Availability__c"),
        ("suite", "ascendix__Availability__c"),
        ("unit", "ascendix__Availability__c"),
        ("vacant", "ascendix__Availability__c"),
        ("vacancy", "ascendix__Availability__c"),
        ("transaction", "ascendix__Deal__c"),
        ("opportunity", "ascendix__Deal__c"),
        ("pipeline", "ascendix__Deal__c"),
        ("fee", "ascendix__Deal__c"),
        ("tenant", "ascendix__Lease__c"),
        ("rental", "ascendix__Lease__c"),
        ("expiring", "ascendix__Lease__c"),
        ("company", "Account"),
        ("organization", "Account"),
        ("client", "Account"),
        ("customer", "Account"),
    ]))
    @settings(max_examples=100)
    def test_property_12_hint_maps_to_correct_object(self, hint_and_api: tuple):
        """
        **Property 12: Semantic Hints Recognition**
        **Validates: Requirements 7.5, 10.1, 10.2, 10.3**
        
        For any semantic hint keyword, the router should map it to the 
        correct object that has that hint configured.
        """
        hint, expected_api = hint_and_api
        
        # Test with various query patterns
        queries = [
            f"Show me all {hint}",
            f"Find {hint} in Dallas",
            f"List {hint}",
            f"Search for {hint}",
        ]
        
        for query in queries:
            matches = self.router.detect_entities(query)
            
            # Should find at least one match
            assert len(matches) > 0, \
                f"No matches found for hint '{hint}' in query '{query}'"
            
            # The expected API should be in the matches
            api_names = [m.api_name for m in matches]
            assert expected_api in api_names, \
                f"Expected {expected_api} for hint '{hint}', got {api_names}"
            
            # The match should be of type "hint"
            hint_matches = [m for m in matches if m.api_name == expected_api]
            assert any(m.match_type == "hint" for m in hint_matches), \
                f"Expected match_type='hint' for '{hint}', got {[m.match_type for m in hint_matches]}"

    @given(st.sampled_from(list({
        "ascendix__Property__c": ["building", "asset", "location", "site", "tower"],
        "ascendix__Availability__c": ["space", "suite", "unit", "vacant", "vacancy"],
        "ascendix__Deal__c": ["transaction", "opportunity", "pipeline", "fee"],
        "ascendix__Lease__c": ["tenant", "rental", "expiring", "occupancy"],
        "Account": ["company", "organization", "client", "customer"],
    }.keys())))
    @settings(max_examples=50)
    def test_property_12_all_hints_for_object_recognized(self, api_name: str):
        """
        **Property 12: Semantic Hints Recognition**
        **Validates: Requirements 7.5, 10.1**
        
        For any object, ALL of its configured semantic hints should be 
        recognized and map back to that object.
        """
        # Get the hints for this object
        hints_str = self.configs[api_name].get('Semantic_Hints__c', '')
        hints = [h.strip() for h in hints_str.split(',') if h.strip()]
        
        for hint in hints:
            query = f"Find me a {hint}"
            matches = self.router.detect_entities(query)
            
            # Should find the object
            api_names = [m.api_name for m in matches]
            assert api_name in api_names, \
                f"Hint '{hint}' should map to {api_name}, got {api_names}"

    def test_property_12_hints_updated_within_5_minutes(self):
        """
        **Property 12: Semantic Hints Recognition**
        **Validates: Requirements 10.4**
        
        When hints are updated in configuration, the system should 
        recognize the new hints after refresh (within 5 minutes).
        """
        # Initial state - "gadget" is not recognized
        query = "Find me a gadget"
        matches = self.router.detect_entities(query)
        assert len(matches) == 0, "gadget should not be recognized initially"
        
        # Update configuration with new hint
        self.configs["ascendix__Property__c"]["Semantic_Hints__c"] = \
            "building, asset, location, site, tower, gadget"
        
        # Refresh patterns (simulates 5-minute refresh)
        self.router.refresh_patterns()
        
        # Now "gadget" should be recognized
        matches = self.router.detect_entities(query)
        assert len(matches) > 0, "gadget should be recognized after refresh"
        
        api_names = [m.api_name for m in matches]
        assert "ascendix__Property__c" in api_names, \
            f"gadget should map to Property, got {api_names}"

    def test_property_12_hint_confidence_lower_than_label(self):
        """
        **Property 12: Semantic Hints Recognition**
        **Validates: Requirements 10.3**
        
        Hint matches should have lower confidence than label matches,
        ensuring that explicit entity names take precedence.
        """
        # Query with label
        label_matches = self.router.detect_entities("Show me Property")
        assert len(label_matches) > 0
        label_confidence = label_matches[0].confidence
        
        # Query with hint
        hint_matches = self.router.detect_entities("Show me a building")
        assert len(hint_matches) > 0
        hint_confidence = hint_matches[0].confidence
        
        # Label should have higher confidence
        assert label_confidence > hint_confidence, \
            f"Label confidence ({label_confidence}) should be > hint confidence ({hint_confidence})"

    def test_property_12_no_hints_falls_back_to_label(self):
        """
        **Property 12: Semantic Hints Recognition**
        **Validates: Requirements 10.5**
        
        When no hints are configured, the system should fall back to 
        using object labels and API names only.
        """
        # Create object with no hints
        self.schemas["NoHints__c"] = MockObjectSchema("NoHints__c", "NoHints")
        self.configs["NoHints__c"] = {"Semantic_Hints__c": ""}  # Empty hints
        
        # Refresh to pick up new object
        self.router.refresh_patterns()
        
        # Should still detect by label
        matches = self.router.detect_entities("Show me NoHints")
        assert len(matches) > 0
        assert matches[0].api_name == "NoHints__c"
        assert matches[0].match_type in ["label", "api_name"]
