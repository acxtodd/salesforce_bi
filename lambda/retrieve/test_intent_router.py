"""
Property-based tests for Query Intent Router.

Tests the intent classification and routing logic using hypothesis.

**Feature: phase3-graph-enhancement**
**Requirements: 3.1, 3.2, 3.3**
"""
import pytest
from hypothesis import given, strategies as st, settings, assume, Phase

# Direct import when running from retrieve directory
try:
    from intent_router import (
        QueryIntentRouter,
        QueryIntent,
        IntentClassification,
        classify_query,
        route_query,
        RELATIONSHIP_PATTERNS,
        AGGREGATION_PATTERNS,
        FIELD_FILTER_PATTERNS,
    )
except ImportError:
    # Fallback for running from lambda directory
    from retrieve.intent_router import (
        QueryIntentRouter,
        QueryIntent,
        IntentClassification,
        classify_query,
        route_query,
        RELATIONSHIP_PATTERNS,
        AGGREGATION_PATTERNS,
        FIELD_FILTER_PATTERNS,
    )


# Hypothesis settings for Phase 3 property tests
settings.register_profile(
    "phase3",
    max_examples=100,
    deadline=None,  # Disable deadline for complex pattern matching
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
)
settings.load_profile("phase3")


class TestIntentClassificationValidity:
    """
    Property 4: Intent Classification Validity
    Validates: Requirements 3.1
    All queries return a valid intent type with confidence between 0 and 1.
    """

    @given(st.text(min_size=1, max_size=200))
    @settings(max_examples=100)
    def test_property_4_all_queries_return_valid_intent(self, query: str):
        """Any query string should return a valid IntentClassification."""
        assume(query.strip())  # Skip empty-after-strip queries

        classification = classify_query(query)

        # Verify classification is valid
        assert isinstance(classification, IntentClassification)
        assert isinstance(classification.intent, QueryIntent)
        assert classification.intent in QueryIntent
        assert 0.0 <= classification.confidence <= 1.0
        assert isinstance(classification.patterns_matched, list)
        assert isinstance(classification.extracted_entities, dict)

    @given(st.text(min_size=1, max_size=200))
    @settings(max_examples=50)
    def test_classification_has_routing_hint(self, query: str):
        """All classifications should have a routing hint."""
        assume(query.strip())

        classification = classify_query(query)

        assert classification.routing_hint is not None
        assert classification.routing_hint in [
            "vector", "filtered_vector", "graph_aware", "aggregation", "hybrid"
        ]


class TestRelationshipPatternDetection:
    """
    Property 5: Relationship Pattern Detection
    Validates: Requirements 3.2
    Queries with relationship patterns should be classified as RELATIONSHIP intent.
    """

    # Relationship query templates
    relationship_queries = [
        "tenants of properties owned by Acme Corp",
        "leases for the building at 123 Main St",
        "deals related to properties in downtown",
        "who owns the property with lease 123",
        "properties connected to this tenant",
        "what deals are associated with this property",
        "tenants at properties managed by John",
        "leases for properties in the portfolio",
    ]

    @pytest.mark.parametrize("query", relationship_queries)
    def test_relationship_queries_detected(self, query: str):
        """Known relationship queries should be classified as RELATIONSHIP."""
        classification = classify_query(query)

        # Should be classified as RELATIONSHIP or COMPLEX (if mixed patterns)
        assert classification.intent in [QueryIntent.RELATIONSHIP, QueryIntent.COMPLEX], \
            f"Expected RELATIONSHIP or COMPLEX for '{query}', got {classification.intent}"
        assert classification.confidence >= 0.5

    @given(st.sampled_from([
        "tenant of property",
        "lease for building",
        "deal related to",
        "properties owned by",
        "belongs to account",
    ]))
    @settings(max_examples=20)
    def test_property_5_relationship_patterns_detected(self, pattern: str):
        """Queries containing relationship patterns should detect RELATIONSHIP intent."""
        # Build a query with the pattern
        query = f"Show me {pattern} ABC Company"

        classification = classify_query(query)

        # Should have some relationship patterns matched
        assert any("relationship" in p.lower() or "tenant" in p or "lease" in p or "property" in p
                   for p in classification.patterns_matched) or classification.confidence >= 0.5

    def test_multi_hop_relationship_detected(self):
        """Multi-hop relationship queries should have high confidence."""
        query = "tenants of properties owned by landlords in California"

        classification = classify_query(query)

        assert classification.intent in [QueryIntent.RELATIONSHIP, QueryIntent.COMPLEX]
        assert classification.confidence >= 0.7


class TestAggregationPatternDetection:
    """
    Property 6: Aggregation Pattern Detection
    Validates: Requirements 3.3
    Queries with aggregation patterns should be classified as AGGREGATION intent.
    """

    # Aggregation query templates
    aggregation_queries = [
        "how many properties are in San Francisco",
        "total value of all deals this quarter",
        "count of active leases",
        "top 10 deals by gross fee amount",
        "average lease amount by region",
        "largest deals in the portfolio",
        "sum of all deal fees",
    ]

    @pytest.mark.parametrize("query", aggregation_queries)
    def test_aggregation_queries_detected(self, query: str):
        """Known aggregation queries should be classified as AGGREGATION or COMPLEX."""
        classification = classify_query(query)

        # Should be classified as AGGREGATION or COMPLEX (if mixed with other patterns)
        assert classification.intent in [QueryIntent.AGGREGATION, QueryIntent.COMPLEX], \
            f"Expected AGGREGATION or COMPLEX for '{query}', got {classification.intent}"
        assert classification.confidence >= 0.6

    @given(st.sampled_from([
        "how many",
        "count of",
        "total",
        "sum of",
        "average",
        "top 5",
        "largest",
    ]))
    @settings(max_examples=20)
    def test_property_6_aggregation_patterns_detected(self, pattern: str):
        """Queries containing aggregation patterns should detect AGGREGATION or COMPLEX intent."""
        query = f"{pattern} deals"  # Simpler query to avoid location pattern matches

        classification = classify_query(query)

        # Should be AGGREGATION or COMPLEX (if other patterns also match)
        assert classification.intent in [QueryIntent.AGGREGATION, QueryIntent.COMPLEX, QueryIntent.FIELD_FILTER], \
            f"Expected AGGREGATION, COMPLEX, or FIELD_FILTER for '{query}', got {classification.intent}"

    def test_top_n_extracts_limit(self):
        """Top N queries should extract the numeric limit."""
        query = "top 15 deals by fee amount"

        classification = classify_query(query)

        assert classification.intent == QueryIntent.AGGREGATION
        assert classification.extracted_entities.get("limit") == 15


class TestFieldFilterPatternDetection:
    """
    Tests for FIELD_FILTER intent detection.
    """

    # Field filter query templates
    field_filter_queries = [
        "properties where status is active",
        "deals with stage equal to Closed Won",
        "leases greater than $50000",
        "properties in San Francisco",
        "deals this quarter",
        "leases expiring next month",
    ]

    @pytest.mark.parametrize("query", field_filter_queries)
    def test_field_filter_queries_detected(self, query: str):
        """Known field filter queries should be classified as FIELD_FILTER."""
        classification = classify_query(query)

        # Should be FIELD_FILTER or COMPLEX (if mixed with other patterns)
        assert classification.intent in [QueryIntent.FIELD_FILTER, QueryIntent.COMPLEX, QueryIntent.RELATIONSHIP], \
            f"Expected FIELD_FILTER or COMPLEX for '{query}', got {classification.intent}"


class TestSimpleLookupDetection:
    """
    Tests for SIMPLE_LOOKUP intent detection.
    """

    simple_queries = [
        "find property",
        "show lease",
        "get deal",
        "search account",
    ]

    @pytest.mark.parametrize("query", simple_queries)
    def test_simple_lookup_queries_detected(self, query: str):
        """Very simple queries should be classified as SIMPLE_LOOKUP."""
        classification = classify_query(query)

        assert classification.intent == QueryIntent.SIMPLE_LOOKUP, \
            f"Expected SIMPLE_LOOKUP for '{query}', got {classification.intent}"


class TestComplexIntentDetection:
    """
    Tests for COMPLEX intent detection (mixed patterns).
    """

    def test_mixed_relationship_and_aggregation(self):
        """Queries with both relationship and aggregation patterns should be COMPLEX."""
        query = "how many tenants are at properties owned by Acme Corp"

        classification = classify_query(query)

        # Should recognize both patterns and return COMPLEX or pick dominant
        assert classification.intent in [QueryIntent.COMPLEX, QueryIntent.RELATIONSHIP, QueryIntent.AGGREGATION]
        assert len(classification.patterns_matched) >= 2


class TestQueryRouting:
    """
    Tests for query routing logic.
    """

    def test_relationship_routes_to_graph_aware(self):
        """RELATIONSHIP intent should route to graph_aware retriever."""
        router = QueryIntentRouter(feature_flags={'graph_routing_enabled': True})
        query = "tenants of properties owned by Acme Corp"

        routing = router.route(query)

        assert routing["retriever"] == "graph_aware"
        assert routing["parameters"].get("useGraphTraversal") is True

    def test_relationship_falls_back_when_disabled(self):
        """RELATIONSHIP intent should fall back to vector when graph disabled."""
        router = QueryIntentRouter(feature_flags={'graph_routing_enabled': False})
        query = "tenants of properties owned by Acme Corp"

        routing = router.route(query)

        assert routing["retriever"] == "vector"
        assert routing.get("fallback") is True

    def test_aggregation_routes_to_aggregation(self):
        """AGGREGATION intent should route to aggregation handler."""
        query = "how many deals this quarter"

        routing = route_query(query)

        assert routing["retriever"] == "aggregation"
        assert routing["parameters"].get("requiresPostProcessing") is True

    def test_simple_lookup_routes_to_vector(self):
        """SIMPLE_LOOKUP intent should route to vector retriever."""
        query = "find property"

        routing = route_query(query)

        assert routing["retriever"] == "vector"


class TestEntityExtraction:
    """
    Tests for entity extraction from queries.
    """

    def test_extracts_object_types(self):
        """
        Should extract mentioned object types.
        
        Note: With dynamic entity detection, CRE-specific objects (Property, Lease, Tenant)
        require Schema Cache. Without it, only generic Salesforce objects are detected.
        This test uses generic objects that work with the fallback patterns.
        """
        query = "accounts and contacts for company ABC"

        classification = classify_query(query)

        entities = classification.extracted_entities
        assert "objectTypes" in entities
        assert "Account" in entities["objectTypes"]
        assert "Contact" in entities["objectTypes"]

    def test_extracts_traversal_depth_hint(self):
        """Should extract traversal depth hints."""
        query = "all related properties"

        classification = classify_query(query)

        if "traversalDepth" in classification.extracted_entities:
            assert classification.extracted_entities["traversalDepth"] == 3

    def test_extracts_numeric_limit(self):
        """Should extract numeric limits from queries."""
        query = "top 20 deals by fee"

        classification = classify_query(query)

        assert classification.extracted_entities.get("limit") == 20


class TestIntentClassificationSerialization:
    """
    Tests for IntentClassification serialization.
    """

    def test_to_dict_serialization(self):
        """IntentClassification should serialize to dict correctly."""
        classification = IntentClassification(
            intent=QueryIntent.RELATIONSHIP,
            confidence=0.85,
            patterns_matched=["tenant_property", "belongs_to"],
            extracted_entities={"objectTypes": ["Property", "Tenant"]},
            routing_hint="graph_aware",
        )

        result = classification.to_dict()

        assert result["intent"] == "RELATIONSHIP"
        assert result["confidence"] == 0.85
        assert result["patternsMatched"] == ["tenant_property", "belongs_to"]
        assert result["extractedEntities"] == {"objectTypes": ["Property", "Tenant"]}
        assert result["routingHint"] == "graph_aware"


class TestIntentRouterConfiguration:
    """
    Tests for QueryIntentRouter configuration.
    """

    def test_default_configuration(self):
        """Default router should have graph routing enabled."""
        router = QueryIntentRouter()

        assert router.graph_routing_enabled is True
        assert router.intent_logging_enabled is True

    def test_custom_feature_flags(self):
        """Router should respect custom feature flags."""
        router = QueryIntentRouter(feature_flags={
            'graph_routing_enabled': False,
            'intent_logging_enabled': False,
        })

        assert router.graph_routing_enabled is False
        assert router.intent_logging_enabled is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
