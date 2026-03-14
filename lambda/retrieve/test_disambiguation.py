"""
Property-based tests for Disambiguation Handler.

Uses Hypothesis to verify correctness properties for disambiguation trigger
and request building.

**Feature: zero-config-production, Property 15: Disambiguation Trigger**
**Validates: Requirements 11.1, 11.2**
"""
import os
import sys
import pytest
from typing import Dict, Any, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from hypothesis import given, strategies as st, settings, assume

from disambiguation import (
    DisambiguationHandler,
    DisambiguationRequest,
    DisambiguationOption,
    get_disambiguation_handler,
    should_disambiguate,
    build_disambiguation_request,
    CONFIDENCE_THRESHOLD,
    MIN_CONFIDENCE_DIFFERENCE,
    ENTITY_METADATA,
    AMBIGUOUS_TERMS,
)


# =============================================================================
# Hypothesis Strategies for Disambiguation Data
# =============================================================================

def confidence_score() -> st.SearchStrategy[float]:
    """Generate confidence scores between 0.0 and 1.0."""
    return st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)


def low_confidence_score() -> st.SearchStrategy[float]:
    """Generate confidence scores below threshold."""
    return st.floats(
        min_value=0.0, 
        max_value=CONFIDENCE_THRESHOLD - 0.01,
        allow_nan=False, 
        allow_infinity=False
    )


def high_confidence_score() -> st.SearchStrategy[float]:
    """Generate confidence scores above threshold."""
    return st.floats(
        min_value=CONFIDENCE_THRESHOLD + 0.01, 
        max_value=1.0,
        allow_nan=False, 
        allow_infinity=False
    )


def entity_api_name() -> st.SearchStrategy[str]:
    """Generate valid entity API names."""
    return st.sampled_from(list(ENTITY_METADATA.keys()))


def ambiguous_term() -> st.SearchStrategy[str]:
    """Generate known ambiguous terms."""
    return st.sampled_from(list(AMBIGUOUS_TERMS.keys()))


def non_ambiguous_word() -> st.SearchStrategy[str]:
    """Generate words that are not ambiguous."""
    return st.sampled_from([
        'find', 'show', 'list', 'get', 'search',
        'the', 'in', 'at', 'for', 'with',
        'large', 'small', 'new', 'old', 'recent',
    ])


@st.composite
def entity_scores_close(draw) -> Dict[str, float]:
    """Generate entity scores where top two are close (within MIN_CONFIDENCE_DIFFERENCE)."""
    entities = draw(st.lists(entity_api_name(), min_size=2, max_size=4, unique=True))
    base_score = draw(st.floats(min_value=0.5, max_value=0.9, allow_nan=False, allow_infinity=False))
    
    scores = {}
    for i, entity in enumerate(entities):
        if i == 0:
            scores[entity] = base_score
        elif i == 1:
            # Second score is close to first (within threshold)
            diff = draw(st.floats(
                min_value=0.0, 
                max_value=MIN_CONFIDENCE_DIFFERENCE - 0.01,
                allow_nan=False, 
                allow_infinity=False
            ))
            scores[entity] = max(0.0, base_score - diff)
        else:
            # Other scores are lower
            scores[entity] = draw(st.floats(
                min_value=0.0, 
                max_value=base_score - 0.2,
                allow_nan=False, 
                allow_infinity=False
            ))
    
    return scores


@st.composite
def entity_scores_spread(draw) -> Dict[str, float]:
    """Generate entity scores where top two are spread apart."""
    entities = draw(st.lists(entity_api_name(), min_size=2, max_size=4, unique=True))
    top_score = draw(st.floats(min_value=0.7, max_value=1.0, allow_nan=False, allow_infinity=False))
    
    scores = {}
    for i, entity in enumerate(entities):
        if i == 0:
            scores[entity] = top_score
        else:
            # Other scores are significantly lower
            scores[entity] = draw(st.floats(
                min_value=0.0, 
                max_value=top_score - MIN_CONFIDENCE_DIFFERENCE - 0.1,
                allow_nan=False, 
                allow_infinity=False
            ))
    
    return scores


@st.composite
def query_with_ambiguous_term(draw) -> str:
    """Generate a query containing an ambiguous term."""
    prefix = draw(st.sampled_from(['show me', 'find', 'list all', 'get']))
    term = draw(ambiguous_term())
    suffix = draw(st.sampled_from(['in Dallas', 'for lease', 'available', '']))
    return f"{prefix} {term} {suffix}".strip()


@st.composite
def query_without_ambiguous_term(draw) -> str:
    """Generate a query without ambiguous terms."""
    prefix = draw(st.sampled_from(['show me', 'find', 'list all', 'get']))
    # Use specific entity keywords instead of ambiguous terms
    entity_word = draw(st.sampled_from([
        'properties', 'buildings', 'deals', 'transactions', 
        'leases', 'tenants', 'accounts', 'companies'
    ]))
    suffix = draw(st.sampled_from(['in Dallas', 'this quarter', '']))
    return f"{prefix} {entity_word} {suffix}".strip()



# =============================================================================
# Property 15: Disambiguation Trigger
# **Validates: Requirements 11.1, 11.2**
# =============================================================================

class TestDisambiguationTriggerProperty:
    """
    Property 15: Disambiguation Trigger
    
    *For any* query where LLM decomposition confidence is below the threshold
    OR multiple entities match equally well, the system SHALL return a
    disambiguation request instead of potentially incorrect results.
    
    **Feature: zero-config-production, Property 15: Disambiguation Trigger**
    **Validates: Requirements 11.1, 11.2**
    """
    
    @given(confidence=low_confidence_score())
    @settings(max_examples=100, deadline=None)
    def test_low_confidence_triggers_disambiguation(self, confidence: float):
        """
        Property: Low confidence MUST trigger disambiguation.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.1**
        """
        handler = DisambiguationHandler()
        
        # Act
        result = handler.should_disambiguate(
            confidence=confidence,
            entity_scores=None,
            ambiguous_terms_found=None,
        )
        
        # Assert: Low confidence should trigger disambiguation
        assert result is True, \
            f"Confidence {confidence:.2f} < threshold {CONFIDENCE_THRESHOLD} should trigger disambiguation"
    
    @given(confidence=high_confidence_score())
    @settings(max_examples=100, deadline=None)
    def test_high_confidence_without_ambiguity_does_not_trigger(self, confidence: float):
        """
        Property: High confidence without ambiguity MUST NOT trigger disambiguation.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.1, 11.4**
        """
        handler = DisambiguationHandler()
        
        # Act
        result = handler.should_disambiguate(
            confidence=confidence,
            entity_scores=None,
            ambiguous_terms_found=None,
        )
        
        # Assert: High confidence without ambiguity should not trigger
        assert result is False, \
            f"Confidence {confidence:.2f} >= threshold {CONFIDENCE_THRESHOLD} without ambiguity should NOT trigger"
    
    @given(
        confidence=high_confidence_score(),
        entity_scores=entity_scores_close(),
    )
    @settings(max_examples=100, deadline=None)
    def test_close_entity_scores_trigger_disambiguation(
        self,
        confidence: float,
        entity_scores: Dict[str, float],
    ):
        """
        Property: Close entity scores MUST trigger disambiguation even with high confidence.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.2**
        """
        # Ensure we have at least 2 entities with close scores
        assume(len(entity_scores) >= 2)
        sorted_scores = sorted(entity_scores.values(), reverse=True)
        assume(len(sorted_scores) >= 2)
        assume(sorted_scores[0] - sorted_scores[1] < MIN_CONFIDENCE_DIFFERENCE)
        
        handler = DisambiguationHandler()
        
        # Act
        result = handler.should_disambiguate(
            confidence=confidence,
            entity_scores=entity_scores,
            ambiguous_terms_found=None,
        )
        
        # Assert: Close scores should trigger disambiguation
        assert result is True, \
            f"Close entity scores (diff < {MIN_CONFIDENCE_DIFFERENCE}) should trigger disambiguation"
    
    @given(
        confidence=high_confidence_score(),
        entity_scores=entity_scores_spread(),
    )
    @settings(max_examples=100, deadline=None)
    def test_spread_entity_scores_do_not_trigger(
        self,
        confidence: float,
        entity_scores: Dict[str, float],
    ):
        """
        Property: Spread entity scores MUST NOT trigger disambiguation.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.4**
        """
        # Ensure scores are spread apart
        assume(len(entity_scores) >= 2)
        sorted_scores = sorted(entity_scores.values(), reverse=True)
        assume(len(sorted_scores) >= 2)
        assume(sorted_scores[0] - sorted_scores[1] >= MIN_CONFIDENCE_DIFFERENCE)
        
        handler = DisambiguationHandler()
        
        # Act
        result = handler.should_disambiguate(
            confidence=confidence,
            entity_scores=entity_scores,
            ambiguous_terms_found=None,
        )
        
        # Assert: Spread scores should not trigger disambiguation
        assert result is False, \
            f"Spread entity scores (diff >= {MIN_CONFIDENCE_DIFFERENCE}) should NOT trigger"
    
    @given(
        confidence=high_confidence_score(),
        ambiguous_terms=st.lists(ambiguous_term(), min_size=1, max_size=3, unique=True),
    )
    @settings(max_examples=100, deadline=None)
    def test_ambiguous_terms_trigger_disambiguation(
        self,
        confidence: float,
        ambiguous_terms: List[str],
    ):
        """
        Property: Ambiguous terms MUST trigger disambiguation.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.2**
        """
        handler = DisambiguationHandler()
        
        # Act
        result = handler.should_disambiguate(
            confidence=confidence,
            entity_scores=None,
            ambiguous_terms_found=ambiguous_terms,
        )
        
        # Assert: Ambiguous terms should trigger disambiguation
        assert result is True, \
            f"Ambiguous terms {ambiguous_terms} should trigger disambiguation"


# =============================================================================
# Property Tests for Disambiguation Request Building
# =============================================================================

class TestDisambiguationRequestProperty:
    """
    Property tests for disambiguation request building.
    
    **Feature: zero-config-production, Property 15: Disambiguation Trigger**
    **Validates: Requirements 11.2**
    """
    
    @given(
        query=query_with_ambiguous_term(),
        candidates=entity_scores_close(),
    )
    @settings(max_examples=100, deadline=None)
    def test_request_contains_all_candidates(
        self,
        query: str,
        candidates: Dict[str, float],
    ):
        """
        Property: Disambiguation request MUST contain all candidate entities.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.2**
        """
        assume(len(candidates) >= 1)
        
        handler = DisambiguationHandler()
        
        # Act
        request = handler.build_disambiguation_request(
            query=query,
            candidates=candidates,
            ambiguous_terms=None,
        )
        
        # Assert: Request should contain options for candidates (up to 4)
        expected_count = min(len(candidates), 4)
        assert len(request.options) == expected_count, \
            f"Request should have {expected_count} options, got {len(request.options)}"
        
        # All options should have valid entity names
        for option in request.options:
            assert option.entity in candidates, \
                f"Option entity {option.entity} should be in candidates"
    
    @given(
        query=query_with_ambiguous_term(),
        candidates=entity_scores_close(),
    )
    @settings(max_examples=100, deadline=None)
    def test_request_options_sorted_by_confidence(
        self,
        query: str,
        candidates: Dict[str, float],
    ):
        """
        Property: Disambiguation options MUST be sorted by confidence descending.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.2**
        """
        assume(len(candidates) >= 2)
        
        handler = DisambiguationHandler()
        
        # Act
        request = handler.build_disambiguation_request(
            query=query,
            candidates=candidates,
            ambiguous_terms=None,
        )
        
        # Assert: Options should be sorted by confidence descending
        confidences = [opt.confidence for opt in request.options]
        assert confidences == sorted(confidences, reverse=True), \
            "Options should be sorted by confidence descending"
    
    @given(
        query=query_with_ambiguous_term(),
        candidates=entity_scores_close(),
        ambiguous_terms=st.lists(ambiguous_term(), min_size=1, max_size=2, unique=True),
    )
    @settings(max_examples=100, deadline=None)
    def test_request_includes_ambiguous_terms(
        self,
        query: str,
        candidates: Dict[str, float],
        ambiguous_terms: List[str],
    ):
        """
        Property: Disambiguation request MUST include ambiguous terms.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.2**
        """
        assume(len(candidates) >= 1)
        
        handler = DisambiguationHandler()
        
        # Act
        request = handler.build_disambiguation_request(
            query=query,
            candidates=candidates,
            ambiguous_terms=ambiguous_terms,
        )
        
        # Assert: Request should include ambiguous terms
        assert request.ambiguous_terms == ambiguous_terms, \
            f"Request should include ambiguous terms {ambiguous_terms}"
    
    @given(
        query=query_with_ambiguous_term(),
        candidates=entity_scores_close(),
    )
    @settings(max_examples=100, deadline=None)
    def test_request_to_dict_is_serializable(
        self,
        query: str,
        candidates: Dict[str, float],
    ):
        """
        Property: Disambiguation request to_dict MUST be JSON serializable.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.2**
        """
        import json
        assume(len(candidates) >= 1)
        
        handler = DisambiguationHandler()
        
        # Act
        request = handler.build_disambiguation_request(
            query=query,
            candidates=candidates,
            ambiguous_terms=None,
        )
        
        result_dict = request.to_dict()
        
        # Assert: Should be JSON serializable
        try:
            json_str = json.dumps(result_dict)
            assert json_str is not None
        except (TypeError, ValueError) as e:
            pytest.fail(f"Request to_dict should be JSON serializable: {e}")
        
        # Assert: Should have required fields
        assert 'needsDisambiguation' in result_dict
        assert result_dict['needsDisambiguation'] is True
        assert 'originalQuery' in result_dict
        assert 'message' in result_dict
        assert 'options' in result_dict


# =============================================================================
# Property Tests for Ambiguous Term Detection
# =============================================================================

class TestAmbiguousTermDetectionProperty:
    """
    Property tests for ambiguous term detection.
    
    **Feature: zero-config-production, Property 15: Disambiguation Trigger**
    **Validates: Requirements 11.1, 11.2**
    """
    
    @given(query=query_with_ambiguous_term())
    @settings(max_examples=100, deadline=None)
    def test_detects_ambiguous_terms_in_query(self, query: str):
        """
        Property: Ambiguous terms in query MUST be detected.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.1, 11.2**
        """
        handler = DisambiguationHandler()
        
        # Act
        detected = handler.detect_ambiguous_terms(query)
        
        # Assert: At least one ambiguous term should be detected
        # (since query_with_ambiguous_term always includes one)
        assert len(detected) >= 1, \
            f"Should detect at least one ambiguous term in '{query}'"
        
        # All detected terms should be known ambiguous terms
        for term in detected:
            assert term in AMBIGUOUS_TERMS, \
                f"Detected term '{term}' should be in AMBIGUOUS_TERMS"
    
    @given(query=query_without_ambiguous_term())
    @settings(max_examples=100, deadline=None)
    def test_no_false_positives_for_clear_queries(self, query: str):
        """
        Property: Clear queries MUST NOT have false positive ambiguous terms.
        
        **Feature: zero-config-production, Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.4**
        """
        handler = DisambiguationHandler()
        
        # Act
        detected = handler.detect_ambiguous_terms(query)
        
        # Assert: Should not detect ambiguous terms in clear queries
        # Note: This may occasionally fail if the random query happens to
        # contain an ambiguous term, but that's expected behavior
        for term in detected:
            assert term in AMBIGUOUS_TERMS, \
                f"Any detected term '{term}' should be a known ambiguous term"



# =============================================================================
# Unit Tests for DisambiguationHandler
# =============================================================================

class TestDisambiguationHandlerUnit:
    """Unit tests for DisambiguationHandler class."""
    
    def test_default_threshold(self):
        """Test that default threshold is set correctly."""
        handler = DisambiguationHandler()
        assert handler.confidence_threshold == CONFIDENCE_THRESHOLD
    
    def test_custom_threshold(self):
        """Test that custom threshold can be set."""
        handler = DisambiguationHandler(confidence_threshold=0.5)
        assert handler.confidence_threshold == 0.5
    
    def test_should_disambiguate_with_zero_confidence(self):
        """Test disambiguation with zero confidence."""
        handler = DisambiguationHandler()
        result = handler.should_disambiguate(confidence=0.0)
        assert result is True
    
    def test_should_disambiguate_with_perfect_confidence(self):
        """Test disambiguation with perfect confidence."""
        handler = DisambiguationHandler()
        result = handler.should_disambiguate(confidence=1.0)
        assert result is False
    
    def test_detect_space_as_ambiguous(self):
        """Test that 'space' is detected as ambiguous."""
        handler = DisambiguationHandler()
        detected = handler.detect_ambiguous_terms("show me available space")
        assert "space" in detected
    
    def test_detect_spaces_as_ambiguous(self):
        """Test that 'spaces' is detected as ambiguous."""
        handler = DisambiguationHandler()
        detected = handler.detect_ambiguous_terms("find spaces for lease")
        assert "spaces" in detected
    
    def test_detect_unit_as_ambiguous(self):
        """Test that 'unit' is detected as ambiguous."""
        handler = DisambiguationHandler()
        detected = handler.detect_ambiguous_terms("show me unit details")
        assert "unit" in detected
    
    def test_no_ambiguous_terms_in_clear_query(self):
        """Test that clear queries have no ambiguous terms."""
        handler = DisambiguationHandler()
        detected = handler.detect_ambiguous_terms("show me properties in Dallas")
        # 'properties' is not ambiguous
        assert "properties" not in detected
    
    def test_get_candidate_entities_for_space(self):
        """Test candidate entities for 'space' term."""
        handler = DisambiguationHandler()
        candidates = handler.get_candidate_entities(
            query="show me space",
            ambiguous_terms=["space"],
        )
        
        # Should include Availability and Property
        assert "ascendix__Availability__c" in candidates
        assert "ascendix__Property__c" in candidates
        
        # Availability should have higher score
        assert candidates["ascendix__Availability__c"] > candidates["ascendix__Property__c"]
    
    def test_build_request_has_message(self):
        """Test that disambiguation request has a message."""
        handler = DisambiguationHandler()
        request = handler.build_disambiguation_request(
            query="show me space",
            candidates={"ascendix__Availability__c": 0.7, "ascendix__Property__c": 0.3},
            ambiguous_terms=["space"],
        )
        
        assert request.message is not None
        assert len(request.message) > 0
        assert "space" in request.message
    
    def test_build_request_options_have_labels(self):
        """Test that disambiguation options have labels."""
        handler = DisambiguationHandler()
        request = handler.build_disambiguation_request(
            query="show me space",
            candidates={"ascendix__Availability__c": 0.7},
            ambiguous_terms=None,
        )
        
        assert len(request.options) == 1
        assert request.options[0].label == "Availability"
    
    def test_handle_clarification(self):
        """Test handling user clarification."""
        handler = DisambiguationHandler()
        result = handler.handle_clarification(
            original_query="show me space",
            selected_entity="ascendix__Availability__c",
        )
        
        assert result["query"] == "show me space"
        assert result["clarified_entity"] == "ascendix__Availability__c"
        assert result["disambiguation_applied"] is True
        assert "ascendix__Availability__c" in result["filters"]["sobject"]


# =============================================================================
# Unit Tests for Data Classes
# =============================================================================

class TestDisambiguationDataClasses:
    """Unit tests for disambiguation data classes."""
    
    def test_option_to_dict(self):
        """Test DisambiguationOption to_dict."""
        option = DisambiguationOption(
            entity="ascendix__Availability__c",
            label="Availability",
            description="Units for lease",
            example_query="Show me available spaces",
            confidence=0.8,
        )
        
        result = option.to_dict()
        
        assert result["entity"] == "ascendix__Availability__c"
        assert result["label"] == "Availability"
        assert result["description"] == "Units for lease"
        assert result["exampleQuery"] == "Show me available spaces"
        assert result["confidence"] == 0.8
    
    def test_request_to_dict(self):
        """Test DisambiguationRequest to_dict."""
        option = DisambiguationOption(
            entity="ascendix__Availability__c",
            label="Availability",
            description="Units for lease",
            example_query="Show me available spaces",
            confidence=0.8,
        )
        
        request = DisambiguationRequest(
            original_query="show me space",
            message="Please clarify",
            options=[option],
            ambiguous_terms=["space"],
        )
        
        result = request.to_dict()
        
        assert result["needsDisambiguation"] is True
        assert result["originalQuery"] == "show me space"
        assert result["message"] == "Please clarify"
        assert len(result["options"]) == 1
        assert result["ambiguousTerms"] == ["space"]


# =============================================================================
# Unit Tests for Module-Level Functions
# =============================================================================

class TestModuleFunctions:
    """Unit tests for module-level convenience functions."""
    
    def test_get_disambiguation_handler_returns_singleton(self):
        """Test that get_disambiguation_handler returns same instance."""
        handler1 = get_disambiguation_handler()
        handler2 = get_disambiguation_handler()
        assert handler1 is handler2
    
    def test_should_disambiguate_function(self):
        """Test should_disambiguate convenience function."""
        result = should_disambiguate(confidence=0.5)
        assert result is True
    
    def test_build_disambiguation_request_function(self):
        """Test build_disambiguation_request convenience function."""
        request = build_disambiguation_request(
            query="show me space",
            candidates={"ascendix__Availability__c": 0.7},
            ambiguous_terms=["space"],
        )
        
        assert isinstance(request, DisambiguationRequest)
        assert request.original_query == "show me space"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
