"""
Dynamic Prompt Generator for Zero-Config Production and Graph-Aware Retrieval.

Generates LLM prompts dynamically from Schema Cache + Configuration.
Builds schema context with object descriptions and semantic hints.
Includes relationship information in prompts for cross-object query handling.
Injects vocabulary hints based on relevance scoring for improved query understanding.

**Feature: zero-config-production, graph-aware-zero-config-retrieval**
**Requirements: 10.2, 13.1, 13.2, 13.3**
"""
import os
import logging
import re
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass, field

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Default number of vocab hints to include
DEFAULT_TOP_N_HINTS = 10

# Minimum word length for vocab matching
MIN_WORD_LENGTH = 2


@dataclass
class ObjectContext:
    """Context information for a single object."""
    api_name: str
    label: str
    description: Optional[str]
    semantic_hints: List[str]
    filterable_fields: List[Dict[str, Any]]
    numeric_fields: List[str]
    date_fields: List[str]
    relationships: List[Dict[str, str]]


class DynamicPromptGenerator:
    """
    Generate schema-aware prompts for query decomposition.

    Builds prompts dynamically from Schema Cache and ConfigurationCache,
    including object descriptions, semantic hints, and relationship information.
    Integrates with VocabCache to inject vocabulary hints based on relevance scoring.

    **Requirements: 10.2, 13.1, 13.2, 13.3**
    """

    def __init__(
        self,
        schema_cache=None,
        config_cache=None,
        vocab_cache=None,
    ):
        """
        Initialize with schema, config, and vocab caches.

        Args:
            schema_cache: SchemaCache instance (lazy-loaded if None)
            config_cache: ConfigurationCache instance (lazy-loaded if None)
            vocab_cache: VocabCache instance for vocabulary hints (lazy-loaded if None)
        """
        self._schema_cache = schema_cache
        self._config_cache = config_cache
        self._vocab_cache = vocab_cache
        self._context_cache: Dict[str, ObjectContext] = {}
        self._context_built = False


    def _get_schema_cache(self):
        """Get or create Schema Cache instance."""
        if self._schema_cache is not None:
            return self._schema_cache
        
        try:
            # **Feature: zero-config-production, Task 27.1**
            # Schema discovery is now provided via Lambda Layer
            import sys
            try:
                from schema_discovery.cache import SchemaCache
            except ImportError:
                # Fallback for local development
                # Note: Use single dirname to stay in lambda/retrieve/ directory
                local_schema_path = os.path.join(
                    os.path.dirname(__file__), 'schema_discovery'
                )
                if local_schema_path not in sys.path:
                    sys.path.insert(0, local_schema_path)
                from cache import SchemaCache
            
            self._schema_cache = SchemaCache()
            return self._schema_cache
        except Exception as e:
            LOGGER.error(f"Failed to create Schema Cache: {e}")
            raise
    
    def _get_config_cache(self):
        """Get or create Configuration Cache instance."""
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
            return None

    def _get_vocab_cache(self):
        """
        Get or create VocabCache instance.

        **Requirements: 13.2, 13.3**

        Returns:
            VocabCache instance or None if unavailable
        """
        if self._vocab_cache is not None:
            return self._vocab_cache

        try:
            from vocab_cache import VocabCache
            self._vocab_cache = VocabCache()
            return self._vocab_cache
        except Exception as e:
            LOGGER.warning(f"Failed to create VocabCache: {e}")
            return None

    def _build_object_contexts(self) -> Dict[str, ObjectContext]:
        """
        Build context information for all indexed objects.
        
        Returns:
            Dictionary mapping API name to ObjectContext
        """
        contexts: Dict[str, ObjectContext] = {}
        
        try:
            schema_cache = self._get_schema_cache()
            schemas = schema_cache.get_all()
            
            if not schemas:
                LOGGER.warning("No schemas found in Schema Cache")
                return contexts
            
            config_cache = self._get_config_cache()
            
            for api_name, schema in schemas.items():
                # Get configuration for this object
                config = {}
                if config_cache:
                    try:
                        config = config_cache.get_config(api_name)
                    except Exception as e:
                        LOGGER.debug(f"Could not get config for {api_name}: {e}")
                
                # Parse semantic hints
                hints_str = config.get('Semantic_Hints__c', '')
                semantic_hints = [
                    h.strip().lower() 
                    for h in hints_str.split(',') 
                    if h.strip()
                ] if hints_str else []
                
                # Get object description
                description = config.get('Object_Description__c', '')
                
                # Build filterable fields with values
                filterable_fields = []
                for f in schema.filterable:
                    field_info = {
                        'name': f.name,
                        'label': f.label,
                        'values': f.values[:20] if f.values else []
                    }
                    filterable_fields.append(field_info)
                
                # Build numeric fields
                numeric_fields = [f.name for f in schema.numeric]
                
                # Build date fields
                date_fields = [f.name for f in schema.date]
                
                # Build relationships
                relationships = []
                for f in schema.relationships:
                    rel_info = {
                        'field': f.name,
                        'label': f.label,
                        'target': f.reference_to or 'Unknown'
                    }
                    relationships.append(rel_info)
                
                contexts[api_name] = ObjectContext(
                    api_name=api_name,
                    label=schema.label,
                    description=description,
                    semantic_hints=semantic_hints,
                    filterable_fields=filterable_fields,
                    numeric_fields=numeric_fields,
                    date_fields=date_fields,
                    relationships=relationships
                )
            
            LOGGER.info(f"Built context for {len(contexts)} objects")
            return contexts
            
        except Exception as e:
            LOGGER.error(f"Error building object contexts: {e}")
            return contexts

    def _ensure_context_built(self) -> None:
        """Ensure object contexts are built."""
        if not self._context_built:
            self._context_cache = self._build_object_contexts()
            self._context_built = True

    def _build_schema_context(self) -> str:
        """
        Build schema context for LLM prompt.
        
        Includes object descriptions, semantic hints, key fields,
        and relationship information.
        
        **Requirements: 10.2**
        
        Returns:
            Schema context string for LLM prompt
        """
        self._ensure_context_built()
        
        lines = []
        lines.append("## Available Objects and Their Meanings")
        lines.append("")
        
        for i, (api_name, ctx) in enumerate(self._context_cache.items(), 1):
            lines.append(f"### {i}. {ctx.label} ({api_name})")
            
            # Add description if available
            if ctx.description:
                lines.append(f"**Concept:** {ctx.description}")
            
            # Add semantic hints
            if ctx.semantic_hints:
                hints_str = ", ".join(ctx.semantic_hints)
                lines.append(f"**Keywords:** {hints_str}")
            
            # Add filterable fields with values
            if ctx.filterable_fields:
                lines.append("**Filterable Fields:**")
                for f in ctx.filterable_fields[:10]:  # Limit to 10 fields
                    if f['values']:
                        values_str = ", ".join(f'"{v}"' for v in f['values'][:10])
                        if len(f['values']) > 10:
                            values_str += f", ... ({len(f['values'])} total)"
                        lines.append(f"  - {f['name']} ({f['label']}): [{values_str}]")
                    else:
                        lines.append(f"  - {f['name']} ({f['label']})")
            
            # Add numeric fields
            if ctx.numeric_fields:
                fields_str = ", ".join(ctx.numeric_fields[:10])
                lines.append(f"**Numeric Fields:** {fields_str}")
            
            # Add date fields
            if ctx.date_fields:
                fields_str = ", ".join(ctx.date_fields[:10])
                lines.append(f"**Date Fields:** {fields_str}")
            
            # Add relationships
            if ctx.relationships:
                lines.append("**Relationships:**")
                for rel in ctx.relationships[:10]:
                    lines.append(f"  - {rel['field']} → {rel['target']}")
            
            lines.append("")
        
        return "\n".join(lines)


    def generate_decomposition_prompt(self, query: str) -> str:
        """
        Generate a prompt for query decomposition.

        Includes:
        1. All indexed objects with their labels and semantic hints
        2. Key filterable fields for each object
        3. Relationships between objects
        4. Instructions for cross-object query handling
        5. Schema-bound filter preference instructions

        **Requirements: 10.2, 13.1**

        Args:
            query: The user's natural language query

        Returns:
            Complete system prompt for LLM decomposition
        """
        schema_context = self._build_schema_context()

        # Build schema-bound filter preference section (Requirement 13.1)
        schema_bound_section = self._build_schema_bound_instructions()

        system_prompt = f"""You are a query planner for a commercial real estate (CRE) Salesforce system.

{schema_context}

{schema_bound_section}

## Your Task
Given a user query, decompose it into a structured query plan.

IMPORTANT RULES:
1. Use the **Keywords** to understand what object the user is referring to
   - "space", "suite", "vacant" → Availability
   - "building", "asset", "location" → Property
   - "transaction", "pipeline", "fee" → Deal
   - etc.

2. Use ONLY the field names and values shown in the schema above
   - For picklist fields, use ONLY the exact values listed in brackets

3. For cross-object queries (e.g., "availabilities in Plano"):
   - If the filter field (City) exists on a related object (Property) but not the target (Availability)
   - Set needs_traversal: true
   - Include the traversal path in the response

4. PREFER SCHEMA-BOUND FILTERS over free-text matching:
   - If the query mentions a value that matches a picklist value, use structured filter
   - If the query mentions a numeric comparison, use numeric_filters
   - If the query mentions a date/time, use date_filters
   - Only use free-text search as a LAST RESORT when no schema fields match

Output JSON with:
- target_entity: The Salesforce object API name to query
- target_filters: Exact-match filters on the target entity {{field_api_name: value}}
- numeric_filters: Numeric comparisons {{field_api_name: {{"$gt"|"$lt"|"$gte"|"$lte": value}}}}
- date_filters: Date filters {{field_api_name: {{"$gt"|"$lt"|"days_ago": value}}}}
- traversals: Related entity filters [{{to: entity_api_name, filters: {{...}}}}]
- needs_traversal: true if filtering requires traversing relationships
- confidence: 0.0 to 1.0 based on how certain you are about the interpretation
- uses_schema_filters: true if structured filters were applied (preferred)

Output ONLY valid JSON, no markdown, no explanation."""

        return system_prompt

    def _build_schema_bound_instructions(self) -> str:
        """
        Build schema-bound filter preference instructions.

        **Requirements: 13.1**

        Returns:
            Instructions section for schema-bound filter preference
        """
        return """## Schema-Bound Filter Preference

CRITICAL: Always prefer structured, schema-bound filters over free-text matching.

**Priority Order:**
1. **Exact picklist match** - If user mentions "Class A", use PropertyClass filter with value "A"
2. **Numeric comparison** - If user mentions "over 50,000 sf", use numeric_filters with $gt
3. **Date range** - If user mentions "next 6 months", use date_filters with calculated range
4. **Relationship traversal** - If filtering across objects, use traversals array
5. **Free-text search** - ONLY if no schema fields match the user's intent

**Why this matters:**
- Schema-bound filters are faster and more precise
- Free-text matching may return irrelevant results
- Structured filters leverage indexed fields for performance"""

    def get_object_context(self, api_name: str) -> Optional[ObjectContext]:
        """
        Get context for a specific object.
        
        Args:
            api_name: Object API name
            
        Returns:
            ObjectContext or None if not found
        """
        self._ensure_context_built()
        return self._context_cache.get(api_name)

    def get_semantic_hints(self, api_name: str) -> List[str]:
        """
        Get semantic hints for an object.
        
        Args:
            api_name: Object API name
            
        Returns:
            List of semantic hint keywords
        """
        ctx = self.get_object_context(api_name)
        return ctx.semantic_hints if ctx else []

    def get_object_description(self, api_name: str) -> Optional[str]:
        """
        Get description for an object.
        
        Args:
            api_name: Object API name
            
        Returns:
            Object description or None
        """
        ctx = self.get_object_context(api_name)
        return ctx.description if ctx else None

    def get_all_hints_mapping(self) -> Dict[str, List[str]]:
        """
        Get mapping of all objects to their semantic hints.

        Returns:
            Dictionary mapping API name to list of hints
        """
        self._ensure_context_built()
        return {
            api_name: ctx.semantic_hints
            for api_name, ctx in self._context_cache.items()
        }

    # =========================================================================
    # Vocabulary Hints (Requirements 13.2, 13.3)
    # =========================================================================

    def _extract_query_terms(self, query: str) -> List[str]:
        """
        Extract meaningful terms from a query for vocabulary lookup.

        Args:
            query: Natural language query

        Returns:
            List of normalized query terms
        """
        # Normalize and tokenize
        query_lower = query.lower()
        # Remove punctuation and split
        words = re.findall(r'\b[a-z0-9]+\b', query_lower)
        # Filter out short words and common stop words
        stop_words = {
            'a', 'an', 'the', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'or',
            'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has',
            'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
            'may', 'might', 'must', 'can', 'with', 'from', 'by', 'as', 'that',
            'this', 'these', 'those', 'it', 'its', 'my', 'your', 'our', 'their',
            'what', 'which', 'who', 'whom', 'where', 'when', 'why', 'how', 'all',
            'any', 'some', 'no', 'not', 'only', 'just', 'more', 'most', 'less',
            'least', 'than', 'then', 'now', 'here', 'there', 'find', 'show',
            'get', 'list', 'give', 'me', 'i', 'we', 'you', 'they', 'he', 'she',
        }
        return [w for w in words if len(w) >= MIN_WORD_LENGTH and w not in stop_words]

    def get_vocab_hints(
        self,
        query: str,
        top_n: int = DEFAULT_TOP_N_HINTS,
    ) -> List[Dict[str, Any]]:
        """
        Get vocabulary hints relevant to a query based on relevance scoring.

        **Requirements: 13.2, 13.3**

        Matches query terms against the vocabulary cache and returns
        top-N hints sorted by relevance score. Uses layout/Describe/RecordType
        signals to determine relevance.

        Args:
            query: Natural language query
            top_n: Maximum number of hints to return

        Returns:
            List of vocab hint dictionaries with term, canonical_value,
            object_name, field_name, source, and relevance_score
        """
        vocab_cache = self._get_vocab_cache()
        if vocab_cache is None:
            LOGGER.debug("VocabCache not available, returning empty hints")
            return []

        # Extract query terms
        query_terms = self._extract_query_terms(query)
        if not query_terms:
            return []

        # Collect all matching vocab entries
        all_matches: List[Dict[str, Any]] = []
        seen_terms: Set[str] = set()

        for term in query_terms:
            try:
                # Try exact lookup first
                match = vocab_cache.lookup(term)
                if match and match.get("term") not in seen_terms:
                    all_matches.append(match)
                    seen_terms.add(match.get("term", ""))

                # Also try lookup_with_score for broader matches
                scored_matches = vocab_cache.lookup_with_score(term, min_score=0.3)
                for m in scored_matches:
                    if m.get("term") not in seen_terms:
                        all_matches.append(m)
                        seen_terms.add(m.get("term", ""))

            except Exception as e:
                LOGGER.debug(f"Error looking up term '{term}': {e}")
                continue

        # Sort by relevance score (descending) and take top N
        all_matches.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        top_hints = all_matches[:top_n]

        LOGGER.debug(f"Found {len(top_hints)} vocab hints for query: {query[:50]}...")
        return top_hints

    def _build_vocab_hints_section(
        self,
        hints: List[Dict[str, Any]],
    ) -> str:
        """
        Build vocab hints section for prompt injection.

        **Requirements: 13.2**

        Args:
            hints: List of vocab hint dictionaries

        Returns:
            Formatted hints section for prompt
        """
        if not hints:
            return ""

        lines = ["## Vocabulary Hints", ""]
        lines.append("These terms from your vocabulary match the query:")
        lines.append("")

        for hint in hints:
            term = hint.get("term", "")
            canonical = hint.get("canonical_value", term)
            obj_name = hint.get("object_name", "")
            field_name = hint.get("field_name", "")
            source = hint.get("source", "describe")
            score = hint.get("relevance_score", 0)

            # Format based on source
            source_label = {
                "layout": "Page Layout",
                "recordtype": "RecordType",
                "picklist": "Picklist",
                "describe": "Field",
            }.get(source, source)

            if field_name:
                lines.append(
                    f"- **{canonical}** ({source_label}): {obj_name}.{field_name} "
                    f"[score: {score:.2f}]"
                )
            else:
                lines.append(
                    f"- **{canonical}** ({source_label}): {obj_name} "
                    f"[score: {score:.2f}]"
                )

        lines.append("")
        lines.append("Use these hints to map query terms to schema fields.")
        return "\n".join(lines)

    def generate_prompt_with_hints(
        self,
        query: str,
        top_n: int = DEFAULT_TOP_N_HINTS,
    ) -> str:
        """
        Generate a prompt with vocabulary hints injected.

        **Requirements: 13.1, 13.2, 13.3**

        Combines schema context, schema-bound filter preference,
        and vocabulary hints based on the query terms.

        Args:
            query: Natural language query
            top_n: Maximum number of vocab hints to include

        Returns:
            Complete system prompt with vocab hints
        """
        # Get base schema context
        schema_context = self._build_schema_context()

        # Get schema-bound filter preference
        schema_bound_section = self._build_schema_bound_instructions()

        # Get vocab hints for this query
        hints = self.get_vocab_hints(query, top_n)
        hints_section = self._build_vocab_hints_section(hints)

        # Combine into prompt
        system_prompt = f"""You are a query planner for a commercial real estate (CRE) Salesforce system.

{schema_context}

{schema_bound_section}

{hints_section}

## Your Task
Given a user query, decompose it into a structured query plan.

IMPORTANT RULES:
1. Use the **Keywords** to understand what object the user is referring to
   - "space", "suite", "vacant" → Availability
   - "building", "asset", "location" → Property
   - "transaction", "pipeline", "fee" → Deal
   - etc.

2. Use ONLY the field names and values shown in the schema above
   - For picklist fields, use ONLY the exact values listed in brackets

3. For cross-object queries (e.g., "availabilities in Plano"):
   - If the filter field (City) exists on a related object (Property) but not target
   - Set needs_traversal: true
   - Include the traversal path in the response

4. PREFER SCHEMA-BOUND FILTERS over free-text matching:
   - If the query mentions a value that matches a picklist value, use structured filter
   - If the query mentions a numeric comparison, use numeric_filters
   - If the query mentions a date/time, use date_filters
   - Only use free-text search as a LAST RESORT when no schema fields match

5. USE VOCABULARY HINTS when available:
   - Match query terms to the hints provided
   - Use the suggested object and field mappings

Output JSON with:
- target_entity: The Salesforce object API name to query
- target_filters: Exact-match filters on the target entity {{field_api_name: value}}
- numeric_filters: Numeric comparisons {{field_api_name: {{"$gt"|"$lt"|"$gte"|"$lte": value}}}}
- date_filters: Date filters {{field_api_name: {{"$gt"|"$lt"|"days_ago": value}}}}
- traversals: Related entity filters [{{to: entity_api_name, filters: {{...}}}}]
- needs_traversal: true if filtering requires traversing relationships
- confidence: 0.0 to 1.0 based on how certain you are about the interpretation
- uses_schema_filters: true if structured filters were applied (preferred)
- matched_vocab_hints: list of vocab terms that were used

Output ONLY valid JSON, no markdown, no explanation."""

        return system_prompt

    def has_schema_bound_instructions(self, prompt: str) -> bool:
        """
        Check if a prompt contains schema-bound filter preference instructions.

        **Requirements: 13.1**

        Args:
            prompt: The generated prompt

        Returns:
            True if schema-bound instructions are present
        """
        indicators = [
            "Schema-Bound Filter Preference",
            "PREFER SCHEMA-BOUND FILTERS",
            "prefer structured",
            "schema-bound filters",
        ]
        prompt_lower = prompt.lower()
        return any(ind.lower() in prompt_lower for ind in indicators)

    def has_vocab_hints(self, prompt: str) -> bool:
        """
        Check if a prompt contains vocabulary hints.

        **Requirements: 13.2**

        Args:
            prompt: The generated prompt

        Returns:
            True if vocab hints section is present
        """
        return "## Vocabulary Hints" in prompt

    def refresh_context(self) -> None:
        """Refresh object contexts from caches."""
        self._context_cache = self._build_object_contexts()
        self._context_built = True


# Module-level convenience functions
_prompt_generator: Optional[DynamicPromptGenerator] = None


def get_prompt_generator(
    schema_cache=None,
    config_cache=None,
    vocab_cache=None,
) -> DynamicPromptGenerator:
    """
    Get or create the default DynamicPromptGenerator instance.

    Args:
        schema_cache: Optional SchemaCache instance
        config_cache: Optional ConfigurationCache instance
        vocab_cache: Optional VocabCache instance

    Returns:
        DynamicPromptGenerator instance
    """
    global _prompt_generator
    if _prompt_generator is None:
        _prompt_generator = DynamicPromptGenerator(
            schema_cache=schema_cache,
            config_cache=config_cache,
            vocab_cache=vocab_cache,
        )
    return _prompt_generator


def generate_decomposition_prompt(query: str) -> str:
    """
    Convenience function to generate decomposition prompt.

    Args:
        query: Natural language query

    Returns:
        System prompt for LLM
    """
    return get_prompt_generator().generate_decomposition_prompt(query)


def generate_prompt_with_hints(
    query: str,
    top_n: int = DEFAULT_TOP_N_HINTS,
) -> str:
    """
    Convenience function to generate prompt with vocabulary hints.

    **Requirements: 13.1, 13.2, 13.3**

    Args:
        query: Natural language query
        top_n: Maximum number of vocab hints

    Returns:
        System prompt with vocab hints
    """
    return get_prompt_generator().generate_prompt_with_hints(query, top_n)


def get_schema_context() -> str:
    """
    Convenience function to get schema context.

    Returns:
        Schema context string
    """
    return get_prompt_generator()._build_schema_context()


def get_vocab_hints(
    query: str,
    top_n: int = DEFAULT_TOP_N_HINTS,
) -> List[Dict[str, Any]]:
    """
    Convenience function to get vocabulary hints for a query.

    **Requirements: 13.2, 13.3**

    Args:
        query: Natural language query
        top_n: Maximum number of hints

    Returns:
        List of vocab hint dictionaries
    """
    return get_prompt_generator().get_vocab_hints(query, top_n)
