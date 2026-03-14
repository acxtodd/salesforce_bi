"""
Disambiguation Handler for Zero-Config Production.

Handles ambiguous queries by asking users for clarification when the system
cannot confidently determine the user's intent. For example, when "space"
could mean Availability (units for lease) or Property (land/open areas).

**Feature: zero-config-production**
**Requirements: 11.1, 11.2, 11.3, 11.4**
"""
import os
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Default confidence threshold - below this, ask for clarification
# **Requirements: 11.1**
CONFIDENCE_THRESHOLD = float(os.environ.get('DISAMBIGUATION_CONFIDENCE_THRESHOLD', '0.7'))

# Minimum confidence difference between top candidates to consider ambiguous
MIN_CONFIDENCE_DIFFERENCE = float(os.environ.get('MIN_CONFIDENCE_DIFFERENCE', '0.15'))


@dataclass
class DisambiguationOption:
    """
    A clarification option to present to the user.
    
    **Requirements: 11.2**
    
    Attributes:
        entity: The Salesforce object API name
        label: Human-readable label for the entity
        description: Description of what this entity represents
        example_query: Example of how to phrase a query for this entity
        confidence: Confidence score for this option
    """
    entity: str
    label: str
    description: str
    example_query: str
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "entity": self.entity,
            "label": self.label,
            "description": self.description,
            "exampleQuery": self.example_query,
            "confidence": self.confidence,
        }


@dataclass
class DisambiguationRequest:
    """
    Request for user clarification.
    
    **Requirements: 11.2**
    
    Attributes:
        original_query: The original natural language query
        message: Message explaining why clarification is needed
        options: List of clarification options
        ambiguous_terms: Terms in the query that caused ambiguity
    """
    original_query: str
    message: str
    options: List[DisambiguationOption]
    ambiguous_terms: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "needsDisambiguation": True,
            "originalQuery": self.original_query,
            "message": self.message,
            "options": [opt.to_dict() for opt in self.options],
            "ambiguousTerms": self.ambiguous_terms,
        }



# Entity metadata for building disambiguation options
# Maps object API name to human-readable info
ENTITY_METADATA = {
    "ascendix__Property__c": {
        "label": "Property",
        "description": "Physical buildings, real estate assets, and locations",
        "keywords": ["building", "property", "office", "tower", "asset", "location", "site"],
        "example": "Show me Class A properties in Dallas",
    },
    "ascendix__Availability__c": {
        "label": "Availability",
        "description": "Specific units, suites, or floors available for lease",
        "keywords": ["space", "suite", "unit", "floor", "vacancy", "available", "for lease"],
        "example": "Show me available spaces over 10,000 sqft",
    },
    "ascendix__Deal__c": {
        "label": "Deal",
        "description": "Transactions, opportunities, and pipeline items",
        "keywords": ["deal", "transaction", "opportunity", "pipeline", "fee", "commission"],
        "example": "Show me open deals this quarter",
    },
    "ascendix__Lease__c": {
        "label": "Lease",
        "description": "Tenant leases and rental agreements",
        "keywords": ["lease", "tenant", "rental", "rent", "expiring"],
        "example": "Show me leases expiring this year",
    },
    "ascendix__Listing__c": {
        "label": "Listing",
        "description": "Properties or spaces listed for sale or lease",
        "keywords": ["listing", "for sale", "marketed"],
        "example": "Show me active listings in Austin",
    },
    "ascendix__Sale__c": {
        "label": "Sale",
        "description": "Property sales and acquisition transactions",
        "keywords": ["sale", "sold", "acquisition", "purchase"],
        "example": "Show me recent sales over $10M",
    },
    "ascendix__Inquiry__c": {
        "label": "Inquiry",
        "description": "Leads and requests from potential clients",
        "keywords": ["inquiry", "lead", "request"],
        "example": "Show me inquiries from this week",
    },
    "Account": {
        "label": "Account",
        "description": "Companies, clients, and organizations",
        "keywords": ["account", "company", "client", "customer", "organization"],
        "example": "Show me accounts in the technology industry",
    },
    "Contact": {
        "label": "Contact",
        "description": "Individual people and contacts",
        "keywords": ["contact", "person", "people"],
        "example": "Show me contacts at ABC Company",
    },
}

# Ambiguous terms that could match multiple entities
# Maps term to list of possible entities with relative weights
AMBIGUOUS_TERMS = {
    "space": [
        ("ascendix__Availability__c", 0.7),  # Most likely: available space
        ("ascendix__Property__c", 0.3),      # Could be: property with open space
    ],
    "spaces": [
        ("ascendix__Availability__c", 0.7),
        ("ascendix__Property__c", 0.3),
    ],
    "unit": [
        ("ascendix__Availability__c", 0.8),
        ("ascendix__Lease__c", 0.2),
    ],
    "units": [
        ("ascendix__Availability__c", 0.8),
        ("ascendix__Lease__c", 0.2),
    ],
    "opportunity": [
        ("ascendix__Deal__c", 0.6),
        ("ascendix__Availability__c", 0.4),
    ],
    "opportunities": [
        ("ascendix__Deal__c", 0.6),
        ("ascendix__Availability__c", 0.4),
    ],
    "asset": [
        ("ascendix__Property__c", 0.7),
        ("ascendix__Deal__c", 0.3),
    ],
    "assets": [
        ("ascendix__Property__c", 0.7),
        ("ascendix__Deal__c", 0.3),
    ],
}


class DisambiguationHandler:
    """
    Handle ambiguous queries by requesting clarification.
    
    **Property 15: Disambiguation Trigger**
    **Validates: Requirements 11.1, 11.2**
    
    Detects when a query is ambiguous and builds a clarification request
    with options for the user to choose from.
    """
    
    def __init__(
        self,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        min_confidence_difference: float = MIN_CONFIDENCE_DIFFERENCE,
        schema_cache=None,
        config_cache=None,
    ):
        """
        Initialize disambiguation handler.
        
        Args:
            confidence_threshold: Below this confidence, ask for clarification
            min_confidence_difference: Minimum difference between top candidates
            schema_cache: SchemaCache instance for entity metadata
            config_cache: ConfigurationCache for semantic hints
        """
        self.confidence_threshold = confidence_threshold
        self.min_confidence_difference = min_confidence_difference
        self._schema_cache = schema_cache
        self._config_cache = config_cache
    
    def should_disambiguate(
        self,
        confidence: float,
        entity_scores: Optional[Dict[str, float]] = None,
        ambiguous_terms_found: Optional[List[str]] = None,
    ) -> bool:
        """
        Check if query needs disambiguation.
        
        **Property 15: Disambiguation Trigger**
        **Validates: Requirements 11.1, 11.2**
        
        Returns True if:
        - Confidence below threshold
        - Multiple entities match equally well (within min_confidence_difference)
        - Ambiguous terms detected in query
        
        Args:
            confidence: Confidence score from decomposition (0.0 to 1.0)
            entity_scores: Optional dict of entity -> confidence scores
            ambiguous_terms_found: Optional list of ambiguous terms found in query
            
        Returns:
            True if disambiguation is needed
        """
        # Rule 1: Low confidence triggers disambiguation
        if confidence < self.confidence_threshold:
            LOGGER.info(
                f"Disambiguation triggered: confidence {confidence:.2f} < "
                f"threshold {self.confidence_threshold}"
            )
            return True
        
        # Rule 2: Multiple entities with similar scores
        if entity_scores and len(entity_scores) >= 2:
            sorted_scores = sorted(entity_scores.values(), reverse=True)
            if len(sorted_scores) >= 2:
                top_diff = sorted_scores[0] - sorted_scores[1]
                if top_diff < self.min_confidence_difference:
                    LOGGER.info(
                        f"Disambiguation triggered: top entity scores too close "
                        f"(diff={top_diff:.2f} < {self.min_confidence_difference})"
                    )
                    return True
        
        # Rule 3: Ambiguous terms found
        if ambiguous_terms_found and len(ambiguous_terms_found) > 0:
            LOGGER.info(
                f"Disambiguation triggered: ambiguous terms found: "
                f"{ambiguous_terms_found}"
            )
            return True
        
        return False
    
    def detect_ambiguous_terms(self, query: str) -> List[str]:
        """
        Detect ambiguous terms in the query.
        
        Args:
            query: Natural language query
            
        Returns:
            List of ambiguous terms found
        """
        query_lower = query.lower()
        found_terms = []
        
        for term in AMBIGUOUS_TERMS.keys():
            # Check for word boundary match
            if re.search(rf'\b{re.escape(term)}\b', query_lower):
                found_terms.append(term)
        
        return found_terms
    
    def get_candidate_entities(
        self,
        query: str,
        ambiguous_terms: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        """
        Get candidate entities with confidence scores for ambiguous query.
        
        Args:
            query: Natural language query
            ambiguous_terms: List of ambiguous terms found
            
        Returns:
            Dict of entity API name -> confidence score
        """
        candidates: Dict[str, float] = {}
        
        # If we have ambiguous terms, use their entity mappings
        if ambiguous_terms:
            for term in ambiguous_terms:
                term_entities = AMBIGUOUS_TERMS.get(term, [])
                for entity, weight in term_entities:
                    current = candidates.get(entity, 0.0)
                    candidates[entity] = max(current, weight)
        
        # If no candidates from ambiguous terms, use keyword matching
        if not candidates:
            query_lower = query.lower()
            for entity, metadata in ENTITY_METADATA.items():
                keywords = metadata.get("keywords", [])
                match_count = 0
                for keyword in keywords:
                    if keyword in query_lower:
                        match_count += 1
                
                if match_count > 0:
                    # Score based on keyword matches
                    score = min(1.0, match_count * 0.3)
                    candidates[entity] = score
        
        return candidates
    
    def build_disambiguation_request(
        self,
        query: str,
        candidates: Dict[str, float],
        ambiguous_terms: Optional[List[str]] = None,
    ) -> DisambiguationRequest:
        """
        Build a disambiguation request with options.
        
        **Requirements: 11.2**
        
        Args:
            query: Original natural language query
            candidates: Dict of entity -> confidence score
            ambiguous_terms: List of ambiguous terms found
            
        Returns:
            DisambiguationRequest with options for user
        """
        ambiguous_terms = ambiguous_terms or []
        
        # Sort candidates by confidence
        sorted_candidates = sorted(
            candidates.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Build options from top candidates
        options: List[DisambiguationOption] = []
        for entity, confidence in sorted_candidates[:4]:  # Max 4 options
            metadata = ENTITY_METADATA.get(entity, {})
            
            option = DisambiguationOption(
                entity=entity,
                label=metadata.get("label", entity),
                description=metadata.get("description", ""),
                example_query=metadata.get("example", ""),
                confidence=confidence,
            )
            options.append(option)
        
        # Build message
        if ambiguous_terms:
            terms_str = ", ".join(f'"{t}"' for t in ambiguous_terms)
            message = (
                f"Your query contains ambiguous terms ({terms_str}) that could "
                f"refer to different types of records. Please clarify what you're looking for:"
            )
        else:
            message = (
                "I'm not sure what type of records you're looking for. "
                "Please select one of the following options:"
            )
        
        return DisambiguationRequest(
            original_query=query,
            message=message,
            options=options,
            ambiguous_terms=ambiguous_terms,
        )
    
    def handle_clarification(
        self,
        original_query: str,
        selected_entity: str,
    ) -> Dict[str, Any]:
        """
        Handle user's clarification response.
        
        **Requirements: 11.3**
        
        Args:
            original_query: The original ambiguous query
            selected_entity: The entity the user selected
            
        Returns:
            Dict with clarified query parameters
        """
        return {
            "query": original_query,
            "clarified_entity": selected_entity,
            "filters": {
                "sobject": [selected_entity],
            },
            "disambiguation_applied": True,
        }


# Module-level convenience functions
_disambiguation_handler: Optional[DisambiguationHandler] = None


def get_disambiguation_handler(
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> DisambiguationHandler:
    """
    Get or create the default DisambiguationHandler instance.
    
    Args:
        confidence_threshold: Confidence threshold for disambiguation
        
    Returns:
        DisambiguationHandler instance
    """
    global _disambiguation_handler
    if _disambiguation_handler is None:
        _disambiguation_handler = DisambiguationHandler(
            confidence_threshold=confidence_threshold
        )
    return _disambiguation_handler


def should_disambiguate(
    confidence: float,
    entity_scores: Optional[Dict[str, float]] = None,
    ambiguous_terms_found: Optional[List[str]] = None,
) -> bool:
    """
    Convenience function to check if disambiguation is needed.
    
    Args:
        confidence: Confidence score from decomposition
        entity_scores: Optional dict of entity -> confidence scores
        ambiguous_terms_found: Optional list of ambiguous terms
        
    Returns:
        True if disambiguation is needed
    """
    return get_disambiguation_handler().should_disambiguate(
        confidence=confidence,
        entity_scores=entity_scores,
        ambiguous_terms_found=ambiguous_terms_found,
    )


def build_disambiguation_request(
    query: str,
    candidates: Dict[str, float],
    ambiguous_terms: Optional[List[str]] = None,
) -> DisambiguationRequest:
    """
    Convenience function to build disambiguation request.
    
    Args:
        query: Original query
        candidates: Entity candidates with scores
        ambiguous_terms: Ambiguous terms found
        
    Returns:
        DisambiguationRequest
    """
    return get_disambiguation_handler().build_disambiguation_request(
        query=query,
        candidates=candidates,
        ambiguous_terms=ambiguous_terms,
    )
