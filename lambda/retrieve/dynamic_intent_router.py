"""
Dynamic Intent Router for Zero-Config Production.

Provides dynamic entity detection from Schema Cache instead of hardcoded patterns.
Loads entity names, labels, and semantic hints from Schema Cache and ConfigurationCache.

**Feature: zero-config-production**
**Requirements: 7.1, 7.2, 7.3, 7.4, 7.5**
"""
import re
import os
import logging
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))


@dataclass
class EntityMatch:
    """Result of entity detection in a query."""
    api_name: str
    label: str
    matched_term: str
    match_type: str  # "api_name", "label", "plural", "hint"
    confidence: float


@dataclass
class DynamicEntityPatterns:
    """Entity patterns built from Schema Cache."""
    api_name: str
    label: str
    plural_label: Optional[str]
    semantic_hints: List[str]
    pattern: re.Pattern

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "api_name": self.api_name,
            "label": self.label,
            "plural_label": self.plural_label,
            "semantic_hints": self.semantic_hints,
        }


# Task 29.6: Module-level SchemaCache singleton for memory caching
_module_schema_cache = None


def _get_module_schema_cache():
    """
    Get or create module-level SchemaCache singleton.

    Task 29.6: Shares SchemaCache across all DynamicIntentRouter instances
    to benefit from in-memory caching within Lambda container lifetime.
    """
    global _module_schema_cache
    if _module_schema_cache is not None:
        return _module_schema_cache

    try:
        from schema_discovery.cache import SchemaCache
    except ImportError:
        import sys
        # Note: Use single dirname to stay in lambda/retrieve/ directory
        local_schema_path = os.path.join(
            os.path.dirname(__file__), 'schema_discovery'
        )
        if local_schema_path not in sys.path:
            sys.path.insert(0, local_schema_path)
        from cache import SchemaCache

    _module_schema_cache = SchemaCache()
    return _module_schema_cache


class DynamicIntentRouter:
    """
    Intent router with dynamic entity detection from Schema Cache + Semantic Hints.
    
    Replaces hardcoded entity regex patterns with dynamically built patterns
    from Schema Cache and ConfigurationCache.
    
    **Property 11: Dynamic Entity Detection**
    **Validates: Requirements 7.1, 7.2, 7.4**
    
    **Property 12: Semantic Hints Recognition**
    **Validates: Requirements 7.5, 10.1, 10.2, 10.3**
    """
    
    def __init__(
        self,
        schema_cache=None,
        config_cache=None,
        auto_refresh: bool = True
    ):
        """
        Initialize with schema and config caches for entity discovery.
        
        Args:
            schema_cache: SchemaCache instance (lazy-loaded if None)
            config_cache: ConfigurationCache instance (lazy-loaded if None)
            auto_refresh: Whether to auto-refresh patterns on cache miss
        """
        self._schema_cache = schema_cache
        self._config_cache = config_cache
        self._auto_refresh = auto_refresh
        self._entity_patterns: Dict[str, DynamicEntityPatterns] = {}
        self._patterns_built = False
        self._last_refresh_time: float = 0
        self._refresh_interval_seconds = 300  # 5 minutes

    def _get_schema_cache(self):
        """
        Get or create Schema Cache instance.

        Task 29.6: Uses module-level singleton for memory caching.

        Returns:
            SchemaCache instance
        """
        if self._schema_cache is not None:
            return self._schema_cache

        try:
            # Task 29.6: Use module-level singleton to benefit from memory caching
            self._schema_cache = _get_module_schema_cache()
            return self._schema_cache
        except Exception as e:
            LOGGER.error(f"Failed to create Schema Cache: {e}")
            raise
    
    def _get_config_cache(self):
        """
        Get or create Configuration Cache instance.
        
        Returns:
            ConfigurationCache instance
        """
        if self._config_cache is not None:
            return self._config_cache
        
        try:
            import sys
            graph_builder_path = os.path.join(
                os.path.dirname(__file__), '..', 'graph_builder'
            )
            if graph_builder_path not in sys.path:
                sys.path.insert(0, graph_builder_path)
            
            from config_cache import ConfigurationCache
            self._config_cache = ConfigurationCache()
            return self._config_cache
        except Exception as e:
            LOGGER.warning(f"Failed to create Configuration Cache: {e}")
            # Config cache is optional - semantic hints won't be available
            return None
    
    def _build_entity_patterns(self) -> Dict[str, DynamicEntityPatterns]:
        """
        Build entity detection patterns from Schema Cache + Semantic Hints.
        
        For each indexed object:
        - API name (e.g., "ascendix__Property__c")
        - Label (e.g., "Property")
        - Plural label (e.g., "Properties")
        - Semantic hints from IndexConfiguration (e.g., "building", "asset")
        
        **Requirements: 7.1, 7.4**
        
        Returns:
            Dictionary mapping API name to DynamicEntityPatterns
        """
        patterns: Dict[str, DynamicEntityPatterns] = {}
        
        try:
            schema_cache = self._get_schema_cache()
            schemas = schema_cache.get_all()
            
            if not schemas:
                LOGGER.warning("No schemas found in Schema Cache")
                return patterns
            
            config_cache = self._get_config_cache()
            
            for api_name, schema in schemas.items():
                # Get label from schema
                label = schema.label
                
                # Generate plural label (simple English pluralization)
                plural_label = self._pluralize(label)
                
                # Get semantic hints from configuration
                semantic_hints = []
                if config_cache:
                    try:
                        config = config_cache.get_config(api_name)
                        hints_str = config.get('Semantic_Hints__c', '')
                        if hints_str:
                            semantic_hints = [
                                h.strip().lower() 
                                for h in hints_str.split(',') 
                                if h.strip()
                            ]
                    except Exception as e:
                        LOGGER.debug(f"Could not get config for {api_name}: {e}")
                
                # Build regex pattern for this entity
                pattern = self._build_pattern_for_entity(
                    api_name, label, plural_label, semantic_hints
                )
                
                patterns[api_name] = DynamicEntityPatterns(
                    api_name=api_name,
                    label=label,
                    plural_label=plural_label,
                    semantic_hints=semantic_hints,
                    pattern=pattern
                )
                
                LOGGER.debug(
                    f"Built pattern for {api_name}: label={label}, "
                    f"plural={plural_label}, hints={semantic_hints}"
                )
            
            LOGGER.info(f"Built entity patterns for {len(patterns)} objects")
            return patterns
            
        except Exception as e:
            LOGGER.error(f"Error building entity patterns: {e}")
            return patterns
    
    def _pluralize(self, word: str) -> str:
        """
        Simple English pluralization.
        
        Args:
            word: Singular word
            
        Returns:
            Plural form
        """
        if not word:
            return word
        
        word_lower = word.lower()
        
        # Handle common irregular plurals
        irregulars = {
            'property': 'properties',
            'availability': 'availabilities',
            'company': 'companies',
            'opportunity': 'opportunities',
            'activity': 'activities',
            'entity': 'entities',
            'category': 'categories',
            'territory': 'territories',
        }
        
        if word_lower in irregulars:
            # Preserve original case
            plural = irregulars[word_lower]
            if word[0].isupper():
                return plural.capitalize()
            return plural
        
        # Standard pluralization rules
        if word_lower.endswith('y') and len(word) > 1 and word[-2].lower() not in 'aeiou':
            return word[:-1] + 'ies'
        elif word_lower.endswith(('s', 'x', 'z', 'ch', 'sh')):
            return word + 'es'
        else:
            return word + 's'

    def _build_pattern_for_entity(
        self,
        api_name: str,
        label: str,
        plural_label: str,
        semantic_hints: List[str]
    ) -> re.Pattern:
        """
        Build regex pattern for a single entity.
        
        **Requirements: 7.4**
        
        Args:
            api_name: Object API name
            label: Object label
            plural_label: Plural form of label
            semantic_hints: List of semantic hint keywords
            
        Returns:
            Compiled regex pattern
        """
        # Collect all terms to match
        terms: Set[str] = set()
        
        # Add API name (without namespace prefix and __c suffix)
        clean_api_name = self._clean_api_name(api_name)
        if clean_api_name:
            terms.add(clean_api_name.lower())
        
        # Add label and plural
        if label:
            terms.add(label.lower())
        if plural_label:
            terms.add(plural_label.lower())
        
        # Add semantic hints
        for hint in semantic_hints:
            if hint:
                terms.add(hint.lower())
        
        # Build regex pattern - match any of the terms as whole words
        if not terms:
            # Fallback pattern that won't match anything
            return re.compile(r'(?!x)x')
        
        # Escape special regex characters and join with OR
        escaped_terms = [re.escape(term) for term in sorted(terms, key=len, reverse=True)]
        pattern_str = r'\b(' + '|'.join(escaped_terms) + r')s?\b'
        
        return re.compile(pattern_str, re.IGNORECASE)
    
    def _clean_api_name(self, api_name: str) -> str:
        """
        Clean API name by removing namespace prefix and __c suffix.
        
        Args:
            api_name: Full API name (e.g., "ascendix__Property__c")
            
        Returns:
            Cleaned name (e.g., "Property")
        """
        name = api_name
        
        # Remove namespace prefix (e.g., "ascendix__")
        if '__' in name:
            parts = name.split('__')
            if len(parts) >= 2:
                # Take the middle part (object name)
                name = parts[-2] if parts[-1] in ('c', 'r', 'mdt') else parts[-1]
        
        # Remove __c, __r, __mdt suffixes
        for suffix in ('__c', '__r', '__mdt'):
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break
        
        return name
    
    def refresh_patterns(self) -> None:
        """
        Refresh entity patterns from Schema Cache.
        
        Called when schema cache is updated or on demand.
        
        **Requirements: 7.2**
        """
        import time
        
        LOGGER.info("Refreshing entity patterns from Schema Cache")
        self._entity_patterns = self._build_entity_patterns()
        self._patterns_built = True
        self._last_refresh_time = time.time()
    
    def _ensure_patterns_loaded(self) -> None:
        """Ensure patterns are loaded, refreshing if needed."""
        import time
        
        if not self._patterns_built:
            self.refresh_patterns()
            return
        
        # Check if refresh is needed based on interval
        if self._auto_refresh:
            elapsed = time.time() - self._last_refresh_time
            if elapsed > self._refresh_interval_seconds:
                self.refresh_patterns()
    
    def detect_entities(self, query: str) -> List[EntityMatch]:
        """
        Detect entities mentioned in a query.
        
        **Property 11: Dynamic Entity Detection**
        **Validates: Requirements 7.1, 7.2, 7.4**
        
        Args:
            query: Natural language query
            
        Returns:
            List of EntityMatch objects for detected entities
        """
        self._ensure_patterns_loaded()
        
        matches: List[EntityMatch] = []
        query_lower = query.lower()
        
        for api_name, entity_pattern in self._entity_patterns.items():
            match = entity_pattern.pattern.search(query_lower)
            if match:
                matched_term = match.group(1)
                match_type = self._determine_match_type(
                    matched_term,
                    entity_pattern
                )
                confidence = self._calculate_match_confidence(
                    matched_term,
                    match_type,
                    entity_pattern
                )
                
                matches.append(EntityMatch(
                    api_name=api_name,
                    label=entity_pattern.label,
                    matched_term=matched_term,
                    match_type=match_type,
                    confidence=confidence
                ))
        
        # Sort by confidence descending
        matches.sort(key=lambda m: m.confidence, reverse=True)
        
        return matches
    
    def _determine_match_type(
        self,
        matched_term: str,
        entity_pattern: DynamicEntityPatterns
    ) -> str:
        """
        Determine what type of match occurred.
        
        Args:
            matched_term: The term that matched
            entity_pattern: The entity pattern that matched
            
        Returns:
            Match type string
        """
        term_lower = matched_term.lower()
        
        # Check API name
        clean_api = self._clean_api_name(entity_pattern.api_name).lower()
        if term_lower == clean_api or term_lower == clean_api + 's':
            return "api_name"
        
        # Check label
        if term_lower == entity_pattern.label.lower():
            return "label"
        
        # Check plural
        if entity_pattern.plural_label and term_lower == entity_pattern.plural_label.lower():
            return "plural"
        
        # Check semantic hints
        if term_lower in [h.lower() for h in entity_pattern.semantic_hints]:
            return "hint"
        
        return "partial"
    
    def _calculate_match_confidence(
        self,
        matched_term: str,
        match_type: str,
        entity_pattern: DynamicEntityPatterns
    ) -> float:
        """
        Calculate confidence score for a match.
        
        Args:
            matched_term: The term that matched
            match_type: Type of match
            entity_pattern: The entity pattern
            
        Returns:
            Confidence score between 0 and 1
        """
        # Base confidence by match type
        confidence_map = {
            "label": 0.95,
            "plural": 0.90,
            "api_name": 0.85,
            "hint": 0.80,
            "partial": 0.60,
        }
        
        return confidence_map.get(match_type, 0.50)

    def detect_target_entity(self, query: str) -> Optional[str]:
        """
        Detect the primary target entity from a query.
        
        Returns the API name of the most likely target entity.
        
        **Requirements: 7.1, 7.2**
        
        Args:
            query: Natural language query
            
        Returns:
            API name of target entity, or None if not detected
        """
        matches = self.detect_entities(query)
        
        if not matches:
            return None
        
        # Return the highest confidence match
        return matches[0].api_name
    
    def get_entity_labels(self) -> Dict[str, str]:
        """
        Get mapping of API names to labels for all indexed entities.
        
        Returns:
            Dictionary mapping API name to label
        """
        self._ensure_patterns_loaded()
        
        return {
            api_name: pattern.label
            for api_name, pattern in self._entity_patterns.items()
        }
    
    def get_entity_hints(self, api_name: str) -> List[str]:
        """
        Get semantic hints for an entity.
        
        Args:
            api_name: Object API name
            
        Returns:
            List of semantic hint keywords
        """
        self._ensure_patterns_loaded()
        
        if api_name in self._entity_patterns:
            return self._entity_patterns[api_name].semantic_hints
        return []
    
    def get_all_entity_patterns(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all entity patterns for debugging/monitoring.
        
        Returns:
            Dictionary of entity patterns
        """
        self._ensure_patterns_loaded()
        
        return {
            api_name: pattern.to_dict()
            for api_name, pattern in self._entity_patterns.items()
        }
    
    def is_entity_recognized(self, api_name: str) -> bool:
        """
        Check if an entity is recognized by the router.
        
        **Requirements: 7.2**
        
        Args:
            api_name: Object API name
            
        Returns:
            True if entity is in the pattern cache
        """
        self._ensure_patterns_loaded()
        return api_name in self._entity_patterns


# Module-level convenience functions
_dynamic_router: Optional[DynamicIntentRouter] = None


def get_dynamic_router(
    schema_cache=None,
    config_cache=None
) -> DynamicIntentRouter:
    """
    Get or create the default DynamicIntentRouter instance.
    
    Args:
        schema_cache: Optional SchemaCache instance
        config_cache: Optional ConfigurationCache instance
        
    Returns:
        DynamicIntentRouter instance
    """
    global _dynamic_router
    if _dynamic_router is None:
        _dynamic_router = DynamicIntentRouter(
            schema_cache=schema_cache,
            config_cache=config_cache
        )
    return _dynamic_router


def detect_entities_dynamic(query: str) -> List[EntityMatch]:
    """
    Convenience function to detect entities using the default router.
    
    Args:
        query: Natural language query
        
    Returns:
        List of EntityMatch objects
    """
    return get_dynamic_router().detect_entities(query)


def detect_target_entity_dynamic(query: str) -> Optional[str]:
    """
    Convenience function to detect target entity using the default router.
    
    Args:
        query: Natural language query
        
    Returns:
        API name of target entity, or None
    """
    return get_dynamic_router().detect_target_entity(query)
