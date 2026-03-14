"""
Query Intent Router for Phase 3 Graph Enhancement.

Classifies queries into intent types and routes them to appropriate retrievers.
Supports relationship queries for graph-aware retrieval.

**Feature: phase3-graph-enhancement**
**Requirements: 3.1, 3.2, 3.3, 3.4, 6.2**
"""
import re
import os
import time
import logging
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

import boto3

# Import metrics module for CloudWatch integration
try:
    from graph_metrics import get_intent_metrics, IntentMetrics
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    IntentMetrics = None

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Initialize DynamoDB for logging
dynamodb = boto3.resource('dynamodb')
INTENT_LOG_TABLE = os.environ.get('INTENT_CLASSIFICATION_LOG_TABLE', 'salesforce-ai-search-intent-classification-log')


class QueryIntent(Enum):
    """Types of query intents for routing."""
    SIMPLE_LOOKUP = "SIMPLE_LOOKUP"      # Basic "find X" queries
    FIELD_FILTER = "FIELD_FILTER"        # Queries with explicit field constraints
    RELATIONSHIP = "RELATIONSHIP"         # Multi-hop relationship queries
    AGGREGATION = "AGGREGATION"          # Count, sum, average, top N queries
    COMPLEX = "COMPLEX"                   # Hybrid queries requiring multiple strategies


@dataclass
class IntentClassification:
    """Result of query intent classification."""
    intent: QueryIntent
    confidence: float  # 0.0 to 1.0
    patterns_matched: List[str] = field(default_factory=list)
    extracted_entities: Dict[str, Any] = field(default_factory=dict)
    routing_hint: Optional[str] = None  # Hint for retriever selection

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "patternsMatched": self.patterns_matched,
            "extractedEntities": self.extracted_entities,
            "routingHint": self.routing_hint,
        }


# Relationship patterns for detecting multi-hop queries
RELATIONSHIP_PATTERNS = [
    # Direct relationship keywords
    (r'\b(?:related|associated|linked|connected)\s+(?:to|with)\b', 0.8, "related_to"),
    (r'\b(?:belongs?\s+to|owned?\s+by|managed?\s+by)\b', 0.7, "belongs_to"),
    (r'\b(?:for|of)\s+(?:this|that|the)\s+\w+\b', 0.5, "possessive"),

    # Multi-hop patterns (allow optional adjectives/types between keywords)
    (r'\b(?:tenant|tenants)\s+(?:of|at|in)\s+(?:\w+\s+)?(?:properties?|buildings?)\b', 0.9, "tenant_property"),
    (r'\b(?:leases?)\s+(?:for|at|on)\s+(?:\w+\s+)?(?:properties?|buildings?)\b', 0.9, "lease_property"),
    (r'\b(?:deals?)\s+(?:for|on|at|involving|associated\s+with)\s+(?:\w+\s+)?(?:properties?|buildings?)\b', 0.9, "deal_property"),
    (r'\b(?:deals?)\s+(?:for|on|at|involving)\s+(?:\w+\s+){0,2}(?:properties?|buildings?)\b', 0.85, "deal_property_multi"),
    (r'\b(?:properties?|buildings?)\s+(?:with|having)\s+(?:leases?|tenants?|deals?|availab)\b', 0.9, "property_lease"),
    (r'\b(?:properties?|buildings?)\s+(?:owned|managed)\s+by\b', 0.8, "property_owner"),
    # Common relationship queries with object types
    (r'\b(?:active|open)\s+deals?\s+(?:for|at|on|in)\b', 0.85, "active_deal_location"),

    # Specific property/entity name queries (deals for X, leases at Y)
    # "deals for renaissance tower" = need to traverse Property → Deal
    (r'\bdeals?\s+(?:for|at|on|with|associated\s+with)\s+[A-Z]', 0.9, "deals_for_entity"),
    (r'\bleases?\s+(?:for|at|on|with)\s+[A-Z]', 0.9, "leases_for_entity"),
    (r'\btenants?\s+(?:for|at|of|in)\s+[A-Z]', 0.9, "tenants_for_entity"),
    (r'\bavailab\w*\s+(?:for|at|in)\s+[A-Z]', 0.9, "availability_for_entity"),

    # Availability/Space at property patterns (Phase 3 enhancement)
    (r'\b(?:spaces?|suites?|availab\w*)\s+(?:at|in|for)\s+(?:properties?|buildings?)\b', 0.9, "space_property"),
    (r'\b(?:spaces?|suites?|availab\w*)\s+(?:at|in)\s+(?:properties?|buildings?)\s+(?:with|having)\b', 0.95, "space_property_filter"),
    (r'\b(?:properties?|buildings?)\s+with\s+(?:active|open)\s+(?:deals?|leases?)\b', 0.9, "property_with_deal"),

    # Location-based availability queries (Availability → Property for location)
    # "available space in Dallas" needs graph traversal to get Property location
    (r'\b(?:availab\w*)\s+(?:\w+\s+)?(?:spaces?|suites?|units?)\s+(?:in|at|near)\s+(?:[A-Z][a-z]+)', 0.9, "availability_location"),
    (r'\b(?:spaces?|suites?|units?)\s+(?:in|at|near)\s+(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', 0.85, "space_location"),
    (r'\b(?:retail|office|industrial|warehouse)\s+(?:spaces?|suites?|units?|availab\w*)\s+(?:in|at)\b', 0.85, "typed_space_location"),

    # Contact/Person at entity patterns (Phase 3 enhancement)
    (r'\b(?:contacts?|people|persons?)\s+(?:for|at|of)\s+(?:tenants?|accounts?|companies?)\b', 0.9, "contact_tenant"),
    (r'\b(?:contacts?|people|persons?)\s+(?:for|at|of)\s+(?:tenants?)\s+(?:at|in|of)\b', 0.95, "contact_tenant_property"),
    (r'\bwho\s+(?:are|is)\s+(?:the\s+)?(?:contacts?|people)\b', 0.85, "who_contacts"),

    # Possessive patterns
    (r"\b(?:someone|owner|landlord|tenant|company)'s\s+(?:properties?|leases?|deals?)\b", 0.7, "possessive_relationship"),
    (r'\bwho\s+(?:owns?|manages?|leases?)\b', 0.8, "who_relationship"),
    (r'\bwhat\s+(?:properties?|leases?|deals?)\s+(?:does|do|did)\b', 0.8, "what_relationship"),

    # Chain patterns (2+ hops)
    (r'\b(?:tenants?)\s+(?:of|at)\s+(?:properties?)\s+(?:owned|managed)\s+by\b', 0.95, "tenant_property_owner"),
    (r'\b(?:leases?)\s+(?:for|at)\s+(?:properties?)\s+(?:in|near|around)\b', 0.85, "lease_property_location"),
    (r'\b(?:deals?)\s+(?:involving|for)\s+(?:tenants?|landlords?)\s+(?:at|of)\b', 0.9, "deal_party_property"),
    (r'\b(?:deals?)\s+(?:for|at)\s+(?:properties?)\s+(?:where|with)\b', 0.9, "deal_property_filter"),

    # Indirect relationship patterns
    (r'\bthrough\s+(?:the|a|an)\s+\w+\b', 0.6, "through_relationship"),
    (r'\bvia\s+(?:the|a|an)\s+\w+\b', 0.6, "via_relationship"),
    (r'\b(?:parent|child|sibling)\s+(?:of|to)\b', 0.7, "hierarchy_relationship"),

    # Generic "X with Y" relationship pattern (lower priority)
    (r'\b\w+\s+with\s+(?:active|open|pending)\s+\w+\b', 0.75, "entity_with_status"),
]

# Aggregation patterns for detecting count/sum/avg queries
AGGREGATION_PATTERNS = [
    # Count patterns
    (r'\b(?:how\s+many|count|number\s+of|total\s+(?:number\s+of)?)\b', 0.9, "count"),
    (r'\b(?:list\s+all|show\s+all|get\s+all)\b', 0.6, "list_all"),

    # Sum/Total patterns
    (r'\b(?:total|sum|combined|aggregate)\s+(?:value|amount|fee|revenue|cost)\b', 0.9, "sum_specific"),
    (r'\b(?:sum\s+of)\b', 0.85, "sum_of"),
    (r'\b(?:what\s+is\s+the\s+total)\b', 0.85, "total_question"),

    # Average patterns
    (r'\b(?:average|avg|mean)\s+(?:value|amount|fee|price|size)\b', 0.9, "average"),
    (r'\b(?:average|avg|mean)\b', 0.7, "average_keyword"),  # Standalone average
    (r'\b(?:on\s+average)\b', 0.7, "on_average"),

    # Ranking patterns (top N, largest, smallest)
    (r'\btop\s+\d+\b', 0.95, "top_n"),
    (r'\b(?:largest|biggest|highest|most)\b', 0.85, "largest"),
    (r'\b(?:smallest|lowest|least|fewest)\b', 0.85, "smallest"),

    # Comparison patterns
    (r'\b(?:more|less|greater|fewer)\s+than\b', 0.7, "comparison"),
    (r'\b(?:between|range)\b', 0.6, "range"),

    # Grouping patterns
    (r'\b(?:by|per|grouped?\s+by)\s+(?:region|city|state|type|status)\b', 0.8, "group_by"),
    (r'\b(?:breakdown|distribution)\b', 0.75, "distribution"),
]

# Field filter patterns for detecting explicit constraints
FIELD_FILTER_PATTERNS = [
    # Equality patterns
    (r'\bwhere\s+\w+\s*(?:=|is|equals?)\b', 0.9, "where_equals"),
    (r'\bwith\s+(?:a\s+)?(?:status|type|stage)\s+(?:of|equal\s+to)\s+\w+\b', 0.85, "status_equals"),

    # Comparison patterns
    (r'\b(?:greater|more|larger|higher)\s+than\s+[\$\d]+\b', 0.9, "greater_than"),
    (r'\b(?:less|fewer|smaller|lower)\s+than\s+[\$\d]+\b', 0.9, "less_than"),
    (r'\b(?:at\s+least|minimum)\s+[\$\d]+\b', 0.85, "at_least"),
    (r'\b(?:at\s+most|maximum)\s+[\$\d]+\b', 0.85, "at_most"),

    # Range patterns
    (r'\bbetween\s+[\$\d]+\s+and\s+[\$\d]+\b', 0.9, "between"),

    # Date patterns
    (r'\b(?:after|since|from)\s+(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})\b', 0.85, "after_date"),
    (r'\b(?:before|until|to)\s+(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+\s+\d{1,2},?\s+\d{4})\b', 0.85, "before_date"),
    (r'\b(?:this|last|next)\s+(?:week|month|quarter|year)\b', 0.8, "relative_date"),

    # Location patterns
    (r'\b(?:in|at|near|around)\s+(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', 0.7, "location"),
    (r'\b(?:city|state|region)\s*(?:=|:)\s*\w+\b', 0.85, "location_equals"),

    # Status patterns
    (r'\b(?:active|expired|pending|closed|open|won|lost)\b', 0.6, "status_keyword"),
]

# Simple lookup patterns (generic search without complex constraints)
SIMPLE_LOOKUP_PATTERNS = [
    (r'^(?:find|show|get|search|lookup|what\s+is)\s+\w+$', 0.9, "simple_find"),
    (r'^(?:find|show|get)\s+(?:me\s+)?(?:a|an|the)\s+\w+$', 0.85, "simple_article"),
    (r'^(?:information|details?|info)\s+(?:about|on|for)\s+\w+$', 0.8, "info_about"),
    (r'^tell\s+me\s+about\s+\w+$', 0.8, "tell_about"),
]


class QueryIntentRouter:
    """
    Routes queries to appropriate retrievers based on intent classification.

    Supports:
    - SIMPLE_LOOKUP: Basic vector retrieval
    - FIELD_FILTER: Filtered vector retrieval with metadata constraints
    - RELATIONSHIP: Graph-aware retrieval with relationship traversal
    - AGGREGATION: Aggregation handler (requires post-processing)
    - COMPLEX: Hybrid retrieval combining multiple strategies

    **Requirements: 3.1, 6.2**
    """

    def __init__(self, feature_flags: Optional[Dict[str, bool]] = None):
        """
        Initialize the Intent Router.

        Args:
            feature_flags: Optional feature flags for controlling behavior
                - graph_routing_enabled: Enable routing to graph retriever (default: True)
                - intent_logging_enabled: Enable logging to DynamoDB (default: True)
                - metrics_enabled: Enable CloudWatch metrics (default: True)
        """
        self.feature_flags = feature_flags or {}
        self.graph_routing_enabled = self.feature_flags.get('graph_routing_enabled', True)
        self.intent_logging_enabled = self.feature_flags.get('intent_logging_enabled', True)
        self.metrics_enabled = self.feature_flags.get('metrics_enabled', True)
        
        # Initialize metrics (Task 9.2)
        self._metrics: Optional[IntentMetrics] = None
        if METRICS_AVAILABLE and self.metrics_enabled:
            self._metrics = get_intent_metrics(enabled=True)

    def classify(self, query: str) -> IntentClassification:
        """
        Classify a query into an intent type.

        **Requirements: 3.1, 6.2**

        Args:
            query: The user's natural language query

        Returns:
            IntentClassification with intent type and confidence
        """
        start_time = time.time()
        query_lower = query.lower().strip()

        # Track all matched patterns with scores
        relationship_matches = self._match_patterns(query_lower, RELATIONSHIP_PATTERNS)
        aggregation_matches = self._match_patterns(query_lower, AGGREGATION_PATTERNS)
        field_filter_matches = self._match_patterns(query_lower, FIELD_FILTER_PATTERNS)
        simple_lookup_matches = self._match_patterns(query_lower, SIMPLE_LOOKUP_PATTERNS)

        # Calculate intent scores
        relationship_score = self._calculate_score(relationship_matches)
        aggregation_score = self._calculate_score(aggregation_matches)
        field_filter_score = self._calculate_score(field_filter_matches)
        simple_lookup_score = self._calculate_score(simple_lookup_matches)

        # Determine primary intent
        scores = {
            QueryIntent.RELATIONSHIP: relationship_score,
            QueryIntent.AGGREGATION: aggregation_score,
            QueryIntent.FIELD_FILTER: field_filter_score,
            QueryIntent.SIMPLE_LOOKUP: simple_lookup_score,
        }

        # Sort by score descending
        sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        primary_intent, primary_score = sorted_intents[0]

        # Collect all matched patterns
        all_matches = (
            [p[2] for p in relationship_matches] +
            [p[2] for p in aggregation_matches] +
            [p[2] for p in field_filter_matches] +
            [p[2] for p in simple_lookup_matches]
        )

        # Check for COMPLEX intent (multiple high-scoring intents)
        high_score_count = sum(1 for _, score in sorted_intents if score >= 0.5)
        is_fallback = False
        if high_score_count >= 2 and primary_score < 0.9:
            # Multiple intents detected - use COMPLEX
            intent = QueryIntent.COMPLEX
            confidence = min(1.0, (primary_score + sorted_intents[1][1]) / 2)
            routing_hint = "hybrid"
        else:
            intent = primary_intent
            confidence = primary_score
            routing_hint = self._get_routing_hint(intent)

        # If no patterns matched, default to SIMPLE_LOOKUP
        if confidence < 0.1:
            intent = QueryIntent.SIMPLE_LOOKUP
            confidence = 0.5  # Medium confidence for default
            routing_hint = "vector"
            is_fallback = True

        # Extract entities from the query
        extracted_entities = self._extract_entities(query)

        # Emit metrics (Task 9.2)
        latency_ms = (time.time() - start_time) * 1000
        if self._metrics:
            self._metrics.emit_classification_latency(latency_ms)
            self._metrics.emit_intent_distribution(intent.value)
            self._metrics.emit_confidence(confidence, intent.value)
            self._metrics.emit_pattern_match_count(len(all_matches), intent.value)
            if is_fallback:
                self._metrics.emit_fallback()

        return IntentClassification(
            intent=intent,
            confidence=round(confidence, 3),
            patterns_matched=all_matches,
            extracted_entities=extracted_entities,
            routing_hint=routing_hint,
        )

    def _match_patterns(
        self,
        query: str,
        patterns: List[Tuple[str, float, str]]
    ) -> List[Tuple[str, float, str]]:
        """Match patterns against query and return matches with scores."""
        matches = []
        for pattern, base_score, name in patterns:
            if re.search(pattern, query, re.IGNORECASE):
                matches.append((pattern, base_score, name))
        return matches

    def _calculate_score(self, matches: List[Tuple[str, float, str]]) -> float:
        """Calculate combined score from pattern matches."""
        if not matches:
            return 0.0

        # Use max score plus a bonus for multiple matches
        max_score = max(m[1] for m in matches)
        match_bonus = min(0.1, 0.02 * (len(matches) - 1))  # Up to 0.1 bonus

        return min(1.0, max_score + match_bonus)

    def _get_routing_hint(self, intent: QueryIntent) -> str:
        """Get routing hint for the classified intent."""
        hints = {
            QueryIntent.SIMPLE_LOOKUP: "vector",
            QueryIntent.FIELD_FILTER: "filtered_vector",
            QueryIntent.RELATIONSHIP: "graph_aware",
            QueryIntent.AGGREGATION: "aggregation",
            QueryIntent.COMPLEX: "hybrid",
        }
        return hints.get(intent, "vector")

    def _extract_entities(self, query: str) -> Dict[str, Any]:
        """
        Extract entities from the query for routing.
        
        Uses DynamicIntentRouter for dynamic entity detection from Schema Cache
        when available, with fallback to basic pattern matching.
        
        **Requirements: 7.1, 7.2, 7.3, 7.4**
        """
        entities: Dict[str, Any] = {}
        query_lower = query.lower()

        # Try dynamic entity detection first (from Schema Cache)
        mentioned_objects = self._extract_entities_dynamic(query)
        
        # Fallback to basic patterns if dynamic detection unavailable or empty
        if not mentioned_objects:
            mentioned_objects = self._extract_entities_fallback(query_lower)

        if mentioned_objects:
            entities["objectTypes"] = mentioned_objects

        # Extract relationship depth hints
        if re.search(r'\b(?:all|every|any)\s+(?:related|connected)\b', query_lower):
            entities["traversalDepth"] = 3  # Deep traversal
        elif re.search(r'\b(?:directly?|immediate(?:ly)?)\s+(?:related|connected)\b', query_lower):
            entities["traversalDepth"] = 1  # Single hop

        # Extract numeric limits
        top_n_match = re.search(r'\btop\s+(\d+)\b', query_lower)
        if top_n_match:
            entities["limit"] = int(top_n_match.group(1))

        return entities

    def _extract_entities_dynamic(self, query: str) -> List[str]:
        """
        Extract entities using DynamicIntentRouter from Schema Cache.
        
        **Property 11: Dynamic Entity Detection**
        **Validates: Requirements 7.1, 7.2, 7.4**
        
        Args:
            query: Natural language query
            
        Returns:
            List of detected entity labels
        """
        try:
            # Import dynamically to avoid circular imports
            from dynamic_intent_router import get_dynamic_router
            
            router = get_dynamic_router()
            matches = router.detect_entities(query)
            
            # Return labels for detected entities
            return [match.label for match in matches]
        except ImportError:
            LOGGER.debug("DynamicIntentRouter not available, using fallback")
            return []
        except Exception as e:
            LOGGER.warning(f"Dynamic entity detection failed: {e}")
            return []

    def _extract_entities_fallback(self, query_lower: str) -> List[str]:
        """
        Fallback entity extraction using basic patterns.
        
        Used when DynamicIntentRouter is unavailable or returns no results.
        These are generic patterns that work across different Salesforce orgs.
        
        Args:
            query_lower: Lowercase query string
            
        Returns:
            List of detected entity names
        """
        # Generic patterns that work across orgs (not CRE-specific)
        generic_patterns = {
            "Account": r'\b(?:account|company|organization)(?:s)?\b',
            "Contact": r'\b(?:contact|person|people)(?:s)?\b',
            "Opportunity": r'\b(?:opportunit(?:y|ies))\b',
            "ascendix__Deal__c": r'\b(?:deal(?:s)?)\b',
            "ascendix__Sale__c": r'\b(?:sale(?:s)?|sold\s+propert(?:y|ies)|closed\s+transaction(?:s)?)\b',
            "Lead": r'\b(?:lead(?:s)?)\b',
            "Case": r'\b(?:case(?:s)?|ticket(?:s)?)\b',
        }

        mentioned_objects = []
        for obj_name, pattern in generic_patterns.items():
            if re.search(pattern, query_lower):
                mentioned_objects.append(obj_name)

        return mentioned_objects

    def route(self, query: str, classification: Optional[IntentClassification] = None) -> Dict[str, Any]:
        """
        Route a query to the appropriate retriever based on intent.

        Args:
            query: The user's natural language query
            classification: Optional pre-computed classification

        Returns:
            Routing decision with retriever type and parameters
        """
        if classification is None:
            classification = self.classify(query)

        routing = {
            "retriever": classification.routing_hint,
            "intent": classification.intent.value,
            "confidence": classification.confidence,
            "parameters": {},
        }

        # Add retriever-specific parameters
        if classification.intent == QueryIntent.RELATIONSHIP:
            if not self.graph_routing_enabled:
                # Fall back to vector if graph routing disabled
                routing["retriever"] = "vector"
                routing["fallback"] = True
            else:
                routing["parameters"]["useGraphTraversal"] = True
                depth = classification.extracted_entities.get("traversalDepth", 2)
                routing["parameters"]["maxDepth"] = depth

        elif classification.intent == QueryIntent.AGGREGATION:
            limit = classification.extracted_entities.get("limit", 10)
            routing["parameters"]["limit"] = limit
            routing["parameters"]["requiresPostProcessing"] = True

        elif classification.intent == QueryIntent.FIELD_FILTER:
            routing["parameters"]["useMetadataFilters"] = True

        elif classification.intent == QueryIntent.COMPLEX:
            routing["parameters"]["useGraphTraversal"] = self.graph_routing_enabled
            routing["parameters"]["useMetadataFilters"] = True
            routing["parameters"]["hybridMode"] = True

        return routing

    def log_classification(
        self,
        query: str,
        classification: IntentClassification,
        user_id: str,
        request_id: str,
    ) -> None:
        """
        Log intent classification to DynamoDB for analysis.

        Args:
            query: The original query
            classification: The classification result
            user_id: Salesforce user ID
            request_id: Request ID for correlation
        """
        if not self.intent_logging_enabled:
            return

        try:
            table = dynamodb.Table(INTENT_LOG_TABLE)

            item = {
                "requestId": request_id,
                "timestamp": int(time.time()),
                "query": query[:500],  # Truncate long queries
                "intent": classification.intent.value,
                "confidence": str(classification.confidence),  # DynamoDB needs string for decimals
                "patternsMatched": classification.patterns_matched,
                "extractedEntities": classification.extracted_entities,
                "routingHint": classification.routing_hint,
                "salesforceUserId": user_id,
                # TTL for automatic cleanup (30 days)
                "ttl": int(time.time()) + (30 * 24 * 60 * 60),
            }

            table.put_item(Item=item)
            LOGGER.info(f"Logged intent classification: {classification.intent.value} (conf={classification.confidence})")

        except Exception as e:
            # Don't fail the request if logging fails
            LOGGER.warning(f"Failed to log intent classification: {e}")


# Module-level convenience function
_default_router: Optional[QueryIntentRouter] = None


def get_router(feature_flags: Optional[Dict[str, bool]] = None) -> QueryIntentRouter:
    """Get or create the default router instance."""
    global _default_router
    if _default_router is None or feature_flags:
        _default_router = QueryIntentRouter(feature_flags)
    return _default_router


def classify_query(query: str) -> IntentClassification:
    """Convenience function to classify a query using the default router."""
    return get_router().classify(query)


def route_query(query: str) -> Dict[str, Any]:
    """Convenience function to route a query using the default router."""
    router = get_router()
    classification = router.classify(query)
    return router.route(query, classification)
