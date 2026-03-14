"""
Entity Linker for Graph-Aware Zero-Config Retrieval.

Maps user query terms to Salesforce objects and field values using auto-built
vocabulary from schema metadata (Describe API labels, picklist values,
RecordTypes, page layouts).

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 2.1, 2.2, 2.3**
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))


# =============================================================================
# Constants
# =============================================================================

# Fuzzy match threshold (0-1, higher = stricter)
DEFAULT_FUZZY_THRESHOLD = 0.75

# Minimum confidence score to consider a match valid
MIN_CONFIDENCE_THRESHOLD = 0.3

# Boost factors for different match types
EXACT_MATCH_BOOST = 1.0
FUZZY_MATCH_BOOST = 0.8
PARTIAL_MATCH_BOOST = 0.6

# Common stop words to ignore in queries
STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with",
    "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall",
    "can", "need", "dare", "ought", "used", "all", "any", "both",
    "each", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "just", "also", "now", "where", "when", "what", "which",
    "who", "whom", "this", "that", "these", "those", "am", "show",
    "me", "find", "get", "list", "give", "tell", "search", "look",
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class EntityMatch:
    """
    Represents a matched entity from the vocabulary.

    **Requirements: 2.2**

    Attributes:
        term: Original term from query that was matched
        object_name: Salesforce object API name
        field_name: Field API name (if applicable)
        value: Resolved value (if applicable, e.g., picklist value)
        canonical_value: The canonical/display value
        confidence: Match confidence score (0.0-1.0)
        match_type: Type of match (exact, fuzzy, partial)
        source: Source of the vocabulary term (describe, picklist, recordtype, layout)
        vocab_type: Type of vocabulary (label, picklist, recordtype, object, geography)
    """

    term: str
    object_name: str
    field_name: Optional[str] = None
    value: Optional[str] = None
    canonical_value: Optional[str] = None
    confidence: float = 0.0
    match_type: str = "exact"
    source: str = "describe"
    vocab_type: str = "label"

    def __post_init__(self) -> None:
        """Validate confidence score."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence must be in range [0, 1], got {self.confidence}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "term": self.term,
            "object_name": self.object_name,
            "confidence": self.confidence,
            "match_type": self.match_type,
            "source": self.source,
            "vocab_type": self.vocab_type,
        }
        if self.field_name:
            result["field_name"] = self.field_name
        if self.value:
            result["value"] = self.value
        if self.canonical_value:
            result["canonical_value"] = self.canonical_value
        return result


@dataclass
class LinkingResult:
    """
    Result of entity linking for a query.

    Attributes:
        matches: List of entity matches found
        unmatched_terms: Terms that could not be matched
        ambiguous_terms: Terms with multiple possible matches
        confidence: Overall confidence score for the linking
    """

    matches: List[EntityMatch] = field(default_factory=list)
    unmatched_terms: List[str] = field(default_factory=list)
    ambiguous_terms: List[Tuple[str, List[EntityMatch]]] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "matches": [m.to_dict() for m in self.matches],
            "unmatched_terms": self.unmatched_terms,
            "ambiguous_terms": [
                {"term": t, "candidates": [c.to_dict() for c in candidates]}
                for t, candidates in self.ambiguous_terms
            ],
            "confidence": self.confidence,
        }


# =============================================================================
# VocabCache Protocol (for dependency injection)
# =============================================================================


class VocabCacheProtocol(Protocol):
    """Protocol for VocabCache to allow dependency injection."""

    def lookup(self, term: str, vocab_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Look up a term in the vocabulary cache."""
        ...

    def get_terms(self, vocab_type: str, object_name: str) -> List[Dict[str, Any]]:
        """Get all terms for a vocab type and object."""
        ...

    def lookup_with_score(self, term: str, min_score: float = 0.0) -> List[Dict[str, Any]]:
        """Look up a term and return all matches above minimum score."""
        ...


class SchemaCacheProtocol(Protocol):
    """Protocol for SchemaCache to allow dependency injection (Task 42.1)."""

    def get(self, sobject: str) -> Optional[Any]:
        """Get schema for an object."""
        ...


# =============================================================================
# Entity Linker Class
# =============================================================================


class EntityLinker:
    """
    Links query terms to Salesforce objects and fields using vocabulary cache.

    **Requirements: 2.1, 2.2, 2.3**

    The Entity Linker:
    1. Tokenizes the query into candidate terms
    2. Matches terms against the vocabulary cache
    3. Supports exact and fuzzy matching
    4. Disambiguates multiple matches using relevance scoring
    5. Returns EntityMatch objects with confidence scores
    """

    def __init__(
        self,
        vocab_cache: VocabCacheProtocol,
        fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
        min_confidence: float = MIN_CONFIDENCE_THRESHOLD,
        schema_cache: Optional[SchemaCacheProtocol] = None,
    ):
        """
        Initialize the EntityLinker.

        Args:
            vocab_cache: VocabCache instance for term lookup
            fuzzy_threshold: Threshold for fuzzy matching (0-1)
            min_confidence: Minimum confidence to consider a match valid
            schema_cache: Optional SchemaCache for field relevance scoring (Task 42.1)
        """
        self.vocab_cache = vocab_cache
        self.fuzzy_threshold = fuzzy_threshold
        self.min_confidence = min_confidence
        self.schema_cache = schema_cache

    def link(self, query: str) -> LinkingResult:
        """
        Link entities in a query to Salesforce objects/fields.

        **Requirements: 2.1, 2.2**

        Args:
            query: Natural language query

        Returns:
            LinkingResult with matches, unmatched terms, and confidence
        """
        if not query or not query.strip():
            return LinkingResult(confidence=0.0)

        # Extract candidate terms from query
        candidates = self._extract_candidates(query)

        if not candidates:
            return LinkingResult(confidence=0.0)

        matches: List[EntityMatch] = []
        unmatched: List[str] = []
        ambiguous: List[Tuple[str, List[EntityMatch]]] = []
        matched_spans: Set[Tuple[int, int]] = set()

        # Sort candidates by length (longer first) to prefer multi-word matches
        sorted_candidates = sorted(candidates, key=lambda x: len(x[0]), reverse=True)

        for term, start, end in sorted_candidates:
            # Skip if this span overlaps with an already matched span
            if self._overlaps_matched(start, end, matched_spans):
                continue

            # Try to match the term
            term_matches = self._match_term(term)

            if not term_matches:
                # Only add to unmatched if it's not a stop word
                if term.lower() not in STOP_WORDS:
                    unmatched.append(term)
            elif len(term_matches) == 1:
                # Single match - use it
                matches.append(term_matches[0])
                matched_spans.add((start, end))
            else:
                # Multiple matches - disambiguate
                best_match = self._disambiguate(term, term_matches)
                if best_match:
                    matches.append(best_match)
                    matched_spans.add((start, end))
                    # Log ambiguous match for analysis
                    if len(term_matches) > 1:
                        ambiguous.append((term, term_matches))
                        LOGGER.debug(
                            f"Ambiguous term '{term}' resolved to {best_match.object_name}.{best_match.field_name}"
                        )

        # Calculate overall confidence
        overall_confidence = self._calculate_overall_confidence(matches, unmatched)

        return LinkingResult(
            matches=matches,
            unmatched_terms=unmatched,
            ambiguous_terms=ambiguous,
            confidence=overall_confidence,
        )

    def _extract_candidates(self, query: str) -> List[Tuple[str, int, int]]:
        """
        Extract candidate terms from query.

        Returns list of (term, start_pos, end_pos) tuples.
        Includes both single words and multi-word phrases.
        """
        candidates: List[Tuple[str, int, int]] = []

        # Clean the query
        query_clean = query.strip()

        # Extract quoted phrases first (exact matches)
        quoted_pattern = r'"([^"]+)"'
        for match in re.finditer(quoted_pattern, query_clean):
            candidates.append((match.group(1), match.start(), match.end()))

        # Remove quoted phrases for further processing
        query_no_quotes = re.sub(quoted_pattern, " ", query_clean)

        # Tokenize into words
        words = re.findall(r'\b[\w\'-]+\b', query_no_quotes)

        # Add single words
        pos = 0
        for word in words:
            start = query_no_quotes.find(word, pos)
            if start >= 0:
                end = start + len(word)
                if word.lower() not in STOP_WORDS:
                    candidates.append((word, start, end))
                pos = end

        # Add multi-word phrases (2-4 words)
        for n in range(2, min(5, len(words) + 1)):
            for i in range(len(words) - n + 1):
                phrase_words = words[i:i + n]
                # Skip if all words are stop words
                if all(w.lower() in STOP_WORDS for w in phrase_words):
                    continue
                phrase = " ".join(phrase_words)
                # Find position in original query
                start = query_no_quotes.find(phrase)
                if start >= 0:
                    candidates.append((phrase, start, start + len(phrase)))

        return candidates

    def _overlaps_matched(
        self, start: int, end: int, matched_spans: Set[Tuple[int, int]]
    ) -> bool:
        """Check if a span overlaps with any already matched spans."""
        for m_start, m_end in matched_spans:
            if start < m_end and end > m_start:
                return True
        return False

    def _match_term(self, term: str) -> List[EntityMatch]:
        """
        Match a term against the vocabulary cache.

        **Requirements: 2.2**

        Supports exact and fuzzy matching.

        Args:
            term: Term to match

        Returns:
            List of EntityMatch objects (may be empty)
        """
        matches: List[EntityMatch] = []
        term_lower = term.lower()

        # Try exact match first
        exact_result = self.vocab_cache.lookup(term_lower)
        if exact_result:
            match = self._create_match_from_vocab(term, exact_result, "exact", EXACT_MATCH_BOOST)
            if match.confidence >= self.min_confidence:
                matches.append(match)

        # Try lookup_with_score for multiple matches
        try:
            all_matches = self.vocab_cache.lookup_with_score(term_lower, min_score=0.0)
            for vocab_result in all_matches:
                # Skip if we already have this exact match
                if exact_result and vocab_result.get("canonical_value") == exact_result.get("canonical_value"):
                    continue
                match = self._create_match_from_vocab(term, vocab_result, "exact", EXACT_MATCH_BOOST)
                if match.confidence >= self.min_confidence:
                    matches.append(match)
        except (AttributeError, TypeError):
            # lookup_with_score may not be available
            pass

        # If no exact matches, try fuzzy matching
        if not matches:
            fuzzy_matches = self._fuzzy_match_term(term)
            matches.extend(fuzzy_matches)

        return matches

    def _fuzzy_match_term(self, term: str) -> List[EntityMatch]:
        """
        Perform fuzzy matching for a term.

        Args:
            term: Term to match

        Returns:
            List of fuzzy EntityMatch objects
        """
        matches: List[EntityMatch] = []
        term_lower = term.lower()

        # Get all terms from common vocab types and check similarity
        # Include entity_name (Task 43) and filter_value (Task 40) for seeded vocab
        vocab_types = ["label", "picklist", "recordtype", "object", "geography", "entity_name", "filter_value"]
        common_objects = [
            "Property__c", "Account", "Contact", "Opportunity", "Availability__c", "Lease__c",
            # Ascendix objects (Task 43)
            "ascendix__Property__c", "ascendix__Availability__c", "ascendix__Lease__c",
            "ascendix__Deal__c", "ascendix__Sale__c",
        ]

        checked_terms: Set[str] = set()

        for vocab_type in vocab_types:
            for obj_name in common_objects:
                try:
                    terms = self.vocab_cache.get_terms(vocab_type, obj_name)
                    for vocab_term in terms:
                        vocab_term_str = vocab_term.get("term", "")
                        if vocab_term_str in checked_terms:
                            continue
                        checked_terms.add(vocab_term_str)

                        # Calculate similarity
                        similarity = self._calculate_similarity(term_lower, vocab_term_str)
                        if similarity >= self.fuzzy_threshold:
                            match = EntityMatch(
                                term=term,
                                object_name=vocab_term.get("object_name", obj_name),
                                field_name=vocab_term.get("field_name"),
                                value=vocab_term.get("canonical_value"),
                                canonical_value=vocab_term.get("canonical_value"),
                                confidence=(
                                    similarity * FUZZY_MATCH_BOOST
                                    * float(vocab_term.get("relevance_score", 0.5))
                                ),
                                match_type="fuzzy",
                                source=vocab_term.get("source", "describe"),
                                vocab_type=vocab_type,
                            )
                            if match.confidence >= self.min_confidence:
                                matches.append(match)
                except Exception as e:
                    LOGGER.debug(f"Error getting terms for {vocab_type}#{obj_name}: {e}")
                    continue

        return matches

    def _calculate_similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity using SequenceMatcher."""
        return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()

    def _create_match_from_vocab(
        self,
        term: str,
        vocab_result: Dict[str, Any],
        match_type: str,
        boost: float,
    ) -> EntityMatch:
        """Create an EntityMatch from a vocabulary lookup result."""
        relevance_score = float(vocab_result.get("relevance_score", 0.5))
        confidence = relevance_score * boost

        return EntityMatch(
            term=term,
            object_name=vocab_result.get("object_name", ""),
            field_name=vocab_result.get("field_name"),
            value=vocab_result.get("canonical_value"),
            canonical_value=vocab_result.get("canonical_value"),
            confidence=min(confidence, 1.0),  # Cap at 1.0
            match_type=match_type,
            source=vocab_result.get("source", "describe"),
            vocab_type=vocab_result.get("vocab_type", "label"),
        )

    def _disambiguate(self, term: str, matches: List[EntityMatch]) -> Optional[EntityMatch]:
        """
        Disambiguate multiple matches using relevance scoring.

        **Requirements: 2.3, Task 42.1**

        Uses both vocab relevance and schema field relevance to pick the best match.
        Schema field relevance is used when available to boost high-signal fields.

        Args:
            term: Original term
            matches: List of candidate matches

        Returns:
            Best match based on relevance scoring, or None
        """
        if not matches:
            return None

        if len(matches) == 1:
            return matches[0]

        # Boost confidence using schema field relevance (Task 42.1)
        scored_matches = []
        for match in matches:
            boosted_confidence = match.confidence
            schema_relevance = None

            # Look up field relevance from schema cache if available
            if self.schema_cache and match.object_name and match.field_name:
                try:
                    schema = self.schema_cache.get(match.object_name)
                    if schema:
                        field = schema.get_field(match.field_name) if hasattr(schema, 'get_field') else None
                        if field and hasattr(field, 'relevance_score') and field.relevance_score is not None:
                            schema_relevance = field.relevance_score
                            # Boost confidence by schema relevance (normalized to 0-0.2 range)
                            # This gives signal-harvested fields (7-10) a significant boost
                            relevance_boost = schema_relevance / 50.0  # Max 0.2 boost for score 10
                            boosted_confidence = min(1.0, match.confidence + relevance_boost)
                except Exception as e:
                    LOGGER.debug(f"Error getting schema relevance for {match.object_name}.{match.field_name}: {e}")

            scored_matches.append((match, boosted_confidence, schema_relevance))

        # Sort by boosted confidence
        scored_matches.sort(key=lambda x: x[1], reverse=True)

        best_match, best_confidence, best_relevance = scored_matches[0]

        # Log disambiguation decision with schema relevance
        if len(scored_matches) > 1:
            relevance_info = f", schema_relevance={best_relevance}" if best_relevance else ""
            LOGGER.info(
                f"Disambiguated term '{term}': selected {best_match.object_name}.{best_match.field_name} "
                f"(confidence={best_confidence:.2f}{relevance_info}) over {len(scored_matches) - 1} other candidates"
            )

        return best_match

    def _calculate_overall_confidence(
        self, matches: List[EntityMatch], unmatched: List[str]
    ) -> float:
        """
        Calculate overall confidence for the linking result.

        Args:
            matches: List of successful matches
            unmatched: List of unmatched terms

        Returns:
            Overall confidence score (0.0-1.0)
        """
        if not matches and not unmatched:
            return 0.0

        if not matches:
            return 0.0

        # Average confidence of matches, penalized by unmatched ratio
        avg_confidence = sum(m.confidence for m in matches) / len(matches)

        total_terms = len(matches) + len(unmatched)
        match_ratio = len(matches) / total_terms if total_terms > 0 else 0

        # Overall confidence is average confidence weighted by match ratio
        return avg_confidence * (0.5 + 0.5 * match_ratio)

    def build_vocabulary(self, schema: Dict[str, Any], object_name: str) -> int:
        """
        Build vocabulary from schema metadata.

        **Requirements: 2.1, 2.4**

        This is a convenience method that delegates to VocabCache.build_vocabulary.

        Args:
            schema: Schema dictionary with fields, recordtypes, layouts
            object_name: Salesforce object API name

        Returns:
            Number of terms stored
        """
        # Delegate to vocab cache if it has build_vocabulary method
        if hasattr(self.vocab_cache, "build_vocabulary"):
            return self.vocab_cache.build_vocabulary(schema, object_name)
        return 0


# =============================================================================
# Convenience Functions
# =============================================================================


def link_entities(
    query: str,
    vocab_cache: VocabCacheProtocol,
    schema_cache: Optional[SchemaCacheProtocol] = None,
) -> LinkingResult:
    """
    Convenience function to link entities in a query.

    Args:
        query: Natural language query
        vocab_cache: VocabCache instance
        schema_cache: Optional SchemaCache for field relevance scoring (Task 42)

    Returns:
        LinkingResult with matches and confidence
    """
    linker = EntityLinker(vocab_cache, schema_cache=schema_cache)
    return linker.link(query)
