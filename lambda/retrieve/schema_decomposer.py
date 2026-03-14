"""
Schema-Aware Query Decomposer.

Decomposes natural language queries using schema knowledge for validation.
Uses auto-discovered Salesforce schema to validate filter values against
actual picklist options.

**Feature: zero-config-schema-discovery**
**Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import boto3

# Import schema models - handle both local and Lambda Layer environments
# **Feature: zero-config-production, Task 27.1**
# Schema discovery module is now provided via Lambda Layer at /opt/python/schema_discovery
try:
    from schema_discovery.models import ObjectSchema, FieldSchema  # noqa: F401
    from schema_discovery.cache import SchemaCache
    print(f"[INIT] schema_discovery imported successfully from package path")
except ImportError as e:
    import sys
    import traceback
    print(f"[INIT] schema_discovery import failed with ImportError: {e}")
    print(f"[INIT] Traceback: {traceback.format_exc()}")
    # Try Lambda Layer path (/opt/python is automatically in sys.path for layers)
    layer_path = "/opt/python"
    if layer_path not in sys.path:
        sys.path.insert(0, layer_path)
    try:
        from schema_discovery.models import ObjectSchema, FieldSchema  # noqa: F401
        from schema_discovery.cache import SchemaCache
        print(f"[INIT] Successfully imported from Lambda Layer path")
    except ImportError:
        # Fallback for local development - try relative path
        # Note: Use single dirname to stay in lambda/retrieve/ directory
        local_schema_path = os.path.join(os.path.dirname(__file__), "schema_discovery")
        print(f"[INIT] Trying local development path: {local_schema_path}")
        sys.path.insert(0, local_schema_path)
        from models import ObjectSchema, FieldSchema  # noqa: F401
        from cache import SchemaCache
        print(f"[INIT] Successfully imported from local development path")

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Fuzzy matching threshold (0.0 to 1.0)
FUZZY_MATCH_THRESHOLD = float(os.getenv("FUZZY_MATCH_THRESHOLD", "0.7"))

# Task 29.6: Schema decomposition timeout (ms) - hard budget for LLM call
# On timeout, falls back to heuristic decomposition
SCHEMA_DECOMP_TIMEOUT_MS = int(os.getenv("SCHEMA_DECOMP_TIMEOUT_MS", "700"))

# Heuristic patterns for fast fallback decomposition
# Maps query keywords to (target_entity, parent_entity, default_filters)
HEURISTIC_PATTERNS = {
    # Availability patterns - target Availability with Property parent filters
    "availability": {
        "target": "ascendix__Availability__c",
        "parent": "ascendix__Property__c",
        "needs_traversal": True,
    },
    "availabilities": {
        "target": "ascendix__Availability__c",
        "parent": "ascendix__Property__c",
        "needs_traversal": True,
    },
    "space": {
        "target": "ascendix__Availability__c",
        "parent": "ascendix__Property__c",
        "needs_traversal": True,
    },
    "spaces": {
        "target": "ascendix__Availability__c",
        "parent": "ascendix__Property__c",
        "needs_traversal": True,
    },
    "suite": {
        "target": "ascendix__Availability__c",
        "parent": "ascendix__Property__c",
        "needs_traversal": True,
    },
    "suites": {
        "target": "ascendix__Availability__c",
        "parent": "ascendix__Property__c",
        "needs_traversal": True,
    },
    # Lease patterns
    "lease": {
        "target": "ascendix__Lease__c",
        "parent": "ascendix__Property__c",
        "needs_traversal": True,
    },
    "leases": {
        "target": "ascendix__Lease__c",
        "parent": "ascendix__Property__c",
        "needs_traversal": True,
    },
    # Property patterns (no traversal needed)
    "property": {
        "target": "ascendix__Property__c",
        "parent": None,
        "needs_traversal": False,
    },
    "properties": {
        "target": "ascendix__Property__c",
        "parent": None,
        "needs_traversal": False,
    },
    "building": {
        "target": "ascendix__Property__c",
        "parent": None,
        "needs_traversal": False,
    },
    "buildings": {
        "target": "ascendix__Property__c",
        "parent": None,
        "needs_traversal": False,
    },
}

# Property class mappings for heuristic extraction
PROPERTY_CLASS_KEYWORDS = {
    "class a": "A",
    "class-a": "A",
    "class b": "B",
    "class-b": "B",
    "class c": "C",
    "class-c": "C",
}

# Record type mappings for heuristic extraction
RECORD_TYPE_KEYWORDS = {
    "office": "Office",
    "retail": "Retail",
    "industrial": "Industrial",
    "land": "Land",
    "multifamily": "Multifamily",
    "mixed use": "Mixed Use",
    "mixed-use": "Mixed Use",
}


@dataclass
class StructuredQuery:
    """
    Result of schema-aware query decomposition.

    **Requirements: 3.1, 3.7, 9.1, 9.2, 9.3, 9.4**

    Attributes:
        target_entity: The entity to find (e.g., 'ascendix__Deal__c')
        filters: Exact-match filters {field: value}
        numeric_filters: Comparison filters {field: {operator: value}}
        date_filters: Date filters {field: {operator: value/days}}
        traversals: Relationship traversals [{to: entity, filters: {...}}]
        confidence: Confidence score (0.0 to 1.0)
        original_query: The original natural language query
        validation_warnings: List of validation warnings
        needs_cross_object_traversal: True if filters apply to related object
        cross_object_filter_entity: The entity where filters actually apply
        cross_object_path: Path from filter entity to target entity
    """

    target_entity: str
    filters: Dict[str, Any] = field(default_factory=dict)
    numeric_filters: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    date_filters: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    traversals: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    original_query: str = ""
    validation_warnings: List[str] = field(default_factory=list)
    needs_cross_object_traversal: bool = False
    cross_object_filter_entity: Optional[str] = None
    cross_object_path: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "target_entity": self.target_entity,
            "filters": self.filters,
            "numeric_filters": self.numeric_filters,
            "date_filters": self.date_filters,
            "traversals": self.traversals,
            "confidence": self.confidence,
            "original_query": self.original_query,
            "validation_warnings": self.validation_warnings,
            "needs_cross_object_traversal": self.needs_cross_object_traversal,
            "cross_object_filter_entity": self.cross_object_filter_entity,
            "cross_object_path": self.cross_object_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StructuredQuery":
        """Create StructuredQuery from dictionary."""
        return cls(
            target_entity=data.get("target_entity", ""),
            filters=data.get("filters", {}),
            numeric_filters=data.get("numeric_filters", {}),
            date_filters=data.get("date_filters", {}),
            traversals=data.get("traversals", []),
            confidence=data.get("confidence", 1.0),
            original_query=data.get("original_query", ""),
            validation_warnings=data.get("validation_warnings", []),
            needs_cross_object_traversal=data.get("needs_cross_object_traversal", False),
            cross_object_filter_entity=data.get("cross_object_filter_entity"),
            cross_object_path=data.get("cross_object_path", []),
        )


# Entity detection patterns for CRE domain
ENTITY_PATTERNS = {
    "ascendix__Property__c": [
        r"\bpropert(?:y|ies)\b",
        r"\bbuilding(?:s)?\b",
        r"\boffice(?:s)?\b(?!\s+space)",  # "office" but not "office space"
        r"\btower(?:s)?\b",
        r"\bclass\s+[abc]\b",
    ],
    "ascendix__Deal__c": [
        r"\bdeal(?:s)?\b",
        r"\btransaction(?:s)?\b",
        r"\bopportunit(?:y|ies)\b",
        r"\bpipeline\b",
        r"\bfee(?:s)?\b",
        # Relationship patterns: "deals on/for/in properties" should target Deal, not Property
        r"\bdeal(?:s)?\s+(?:on|for|at|in|involving)\s+",
        r"\bactive\s+deal(?:s)?\b",
        r"\bopen\s+deal(?:s)?\b",
    ],
    "ascendix__Availability__c": [
        r"\bavailab(?:le|ility)\b",
        r"\bavailable\s+space(?:s)?\b",  # "available space" specifically
        r"\boffice\s+space(?:s)?\b",  # "office space" → Availability (Property excludes this)
        r"\bvacant\b",
        r"\bvacanc(?:y|ies)\b",
        r"\bspace(?:s)?\s+(?:for|to)\s+(?:lease|rent)\b",
        r"\bfor\s+lease\b",
    ],
    "ascendix__Lease__c": [
        r"\blease(?:s)?\b(?!\s+deal)",  # "lease" but not "lease deal"
        r"\btenant(?:s)?\b",
        r"\brental\b",
        r"\bexpir(?:ing|ation)\b",
    ],
    "ascendix__Sale__c": [
        r"\bsale(?:s)?\b(?!\s+(?:listing|price))",  # "sale/sales" but not "sales listing" or "sale price"
        r"\bsold\s+propert(?:y|ies)\b",
        r"\bclosed\s+(?:transaction|deal)(?:s)?\b",
        r"\bpast\s+(?:transaction|deal)(?:s)?\b",
        r"\bcompleted\s+(?:transaction|deal)(?:s)?\b",
    ],
    "ascendix__Listing__c": [
        r"\blisting(?:s)?\b",
        r"\bfor\s+sale\b",
        r"\bmarket(?:ed)?\b",
    ],
    "ascendix__Inquiry__c": [
        r"\binquir(?:y|ies)\b",
        r"\blead(?:s)?\b",
        r"\brequest(?:s)?\b",
    ],
    "Account": [
        r"\baccount(?:s)?\b",
        r"\bcompan(?:y|ies)\b",
        r"\bclient(?:s)?\b",
    ],
    "Contact": [
        r"\bcontact(?:s)?\b",
        r"\bperson\b",
        r"\bpeople\b",
    ],
}

# Default entity when none detected
DEFAULT_ENTITY = "ascendix__Property__c"


class SchemaAwareDecomposer:
    """
    Decompose queries using schema for validation.

    **Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
    """

    def __init__(
        self,
        schema_cache: Optional[SchemaCache] = None,
        llm_client: Optional[Any] = None,
        model_id: Optional[str] = None,
    ):
        """
        Initialize with schema cache and LLM client.

        Args:
            schema_cache: SchemaCache instance for loading schemas
            llm_client: Bedrock runtime client (optional, will create if not provided)
            model_id: LLM model ID to use
        """
        self.schema_cache = schema_cache or SchemaCache()
        self._llm_client = llm_client
        self.model_id = model_id or os.getenv(
            "DECOMPOSER_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        )
        self._schema_context_cache: Dict[str, str] = {}

    @property
    def llm_client(self):
        """Lazy initialization of Bedrock client."""
        if self._llm_client is None:
            self._llm_client = boto3.client(
                "bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-west-2")
            )
        return self._llm_client

    def detect_target_entity(self, query: str) -> str:
        """
        Detect target entity type from query text.

        **Requirements: 3.1**

        Args:
            query: Natural language query

        Returns:
            Salesforce object API name
        """
        query_lower = query.lower()
        matches: List[Tuple[str, int]] = []

        for entity, patterns in ENTITY_PATTERNS.items():
            match_count = 0
            for pattern in patterns:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    match_count += 1

            if match_count > 0:
                matches.append((entity, match_count))

        if not matches:
            LOGGER.info(f"No entity detected in query, defaulting to {DEFAULT_ENTITY}")
            return DEFAULT_ENTITY

        # Sort by match count descending
        matches.sort(key=lambda x: x[1], reverse=True)
        detected = matches[0][0]

        LOGGER.info(f"Detected entity: {detected} (matches: {matches[0][1]})")
        return detected

    def _heuristic_decompose(self, query: str) -> StructuredQuery:
        """
        Fast heuristic decomposition without LLM call.

        **Task 29.6: Timeout fallback path**

        Extracts target entity and filters using pattern matching:
        - Target entity from keywords (availability, property, lease, etc.)
        - Property class from "class a/b/c" patterns
        - Record type from "office/retail/industrial" patterns
        - City from common city names or patterns

        For cross-object queries (e.g., availabilities + property filters),
        constructs traversal to parent Property entity.

        Args:
            query: Natural language query

        Returns:
            StructuredQuery with heuristically extracted filters
        """
        start_time = time.time()
        query_lower = query.lower()

        # 1. Detect target entity and parent from heuristic patterns
        target_entity = None
        parent_entity = None
        needs_traversal = False

        for keyword, pattern_info in HEURISTIC_PATTERNS.items():
            if keyword in query_lower:
                target_entity = pattern_info["target"]
                parent_entity = pattern_info["parent"]
                needs_traversal = pattern_info["needs_traversal"]
                break

        # Default to Property if no pattern matched
        if target_entity is None:
            target_entity = "ascendix__Property__c"
            parent_entity = None
            needs_traversal = False

        # 2. Extract property class (A, B, C)
        property_class = None
        for keyword, class_value in PROPERTY_CLASS_KEYWORDS.items():
            if keyword in query_lower:
                property_class = class_value
                break

        # 3. Extract record type (Office, Retail, Industrial, etc.)
        record_type = None
        for keyword, type_value in RECORD_TYPE_KEYWORDS.items():
            if keyword in query_lower:
                record_type = type_value
                break

        # 4. Extract city using common patterns
        city = None
        # Common Texas cities
        texas_cities = ["dallas", "plano", "houston", "austin", "san antonio", "fort worth"]
        # Common Florida cities
        florida_cities = ["miami", "orlando", "tampa", "jacksonville"]
        # Other major cities
        other_cities = ["new york", "los angeles", "chicago", "phoenix", "denver"]

        all_cities = texas_cities + florida_cities + other_cities
        for city_name in all_cities:
            if city_name in query_lower:
                # Capitalize properly
                city = city_name.title()
                break

        # 5. Build filters based on target entity
        filters = {}
        parent_filters = {}

        if needs_traversal:
            # Filters go on parent (Property) for cross-object queries
            if property_class:
                parent_filters["ascendix__PropertyClass__c"] = property_class
            if record_type:
                parent_filters["RecordType"] = record_type
            if city:
                parent_filters["ascendix__City__c"] = city
        else:
            # Filters go directly on target (Property)
            if property_class:
                filters["ascendix__PropertyClass__c"] = property_class
            if record_type:
                filters["RecordType"] = record_type
            if city:
                filters["ascendix__City__c"] = city

        # 6. Build traversals for cross-object queries
        traversals = []
        cross_object_path = []
        if needs_traversal and parent_entity and parent_filters:
            traversals.append({
                "to": parent_entity,
                "filters": parent_filters,
            })
            cross_object_path = [target_entity, parent_entity]

        elapsed_ms = (time.time() - start_time) * 1000

        # Calculate confidence based on how many filters we extracted
        filter_count = len(filters) + len(parent_filters)
        confidence = min(0.8, 0.5 + (filter_count * 0.1))  # Max 0.8 for heuristic

        result = StructuredQuery(
            target_entity=target_entity,
            filters=filters,
            numeric_filters={},
            date_filters={},
            traversals=traversals,
            confidence=confidence,
            original_query=query,
            validation_warnings=["Used heuristic fallback due to LLM timeout"],
            needs_cross_object_traversal=needs_traversal,
            cross_object_filter_entity=parent_entity if needs_traversal else None,
            cross_object_path=cross_object_path,
        )

        LOGGER.info(
            f"[HEURISTIC] Decomposed query in {elapsed_ms:.1f}ms: "
            f"entity={target_entity}, filters={filter_count}, "
            f"traversal={needs_traversal}, confidence={confidence:.2f}"
        )

        return result

    def _build_schema_context(
        self, schema: ObjectSchema, related_schemas: Optional[List[ObjectSchema]] = None
    ) -> str:
        """
        Build prompt context with field names and valid values.

        **Requirements: 3.2, 3.3**

        Args:
            schema: Primary object schema
            related_schemas: List of related object schemas

        Returns:
            Schema context string for LLM prompt
        """
        lines = []

        # Primary object schema
        lines.append(f"## {schema.label} ({schema.api_name})")
        lines.append("")

        # Filterable fields with picklist values
        if schema.filterable:
            lines.append("### Filterable Fields (picklists)")
            for f in schema.filterable:
                if f.values:
                    values_str = ", ".join(f'"{v}"' for v in f.values[:20])
                    if len(f.values) > 20:
                        values_str += f", ... ({len(f.values)} total)"
                    lines.append(f"- {f.name} ({f.label}): [{values_str}]")
                else:
                    lines.append(f"- {f.name} ({f.label})")
            lines.append("")

        # Numeric fields
        if schema.numeric:
            lines.append("### Numeric Fields (support >, <, >=, <=)")
            for f in schema.numeric:
                lines.append(f"- {f.name} ({f.label})")
            lines.append("")

        # Date fields
        if schema.date:
            lines.append("### Date Fields (support temporal queries)")
            for f in schema.date:
                lines.append(f"- {f.name} ({f.label})")
            lines.append("")

        # Relationship fields
        if schema.relationships:
            lines.append("### Relationships")
            for f in schema.relationships:
                target = f.reference_to or "Unknown"
                lines.append(f"- {f.name} ({f.label}) → {target}")
            lines.append("")

        # Related schemas
        if related_schemas:
            lines.append("## Related Objects")
            lines.append("")
            for rel_schema in related_schemas:
                lines.append(f"### {rel_schema.label} ({rel_schema.api_name})")

                # Only include filterable fields for related objects
                if rel_schema.filterable:
                    for f in rel_schema.filterable:
                        if f.values:
                            values_str = ", ".join(f'"{v}"' for v in f.values[:10])
                            if len(f.values) > 10:
                                values_str += f", ... ({len(f.values)} total)"
                            lines.append(f"- {f.name}: [{values_str}]")
                lines.append("")

        return "\n".join(lines)

    def _fuzzy_match(self, value: str, valid_values: List[str]) -> Optional[str]:
        """
        Fuzzy match value to closest valid option.

        **Requirements: 3.5, 3.6**

        Args:
            value: User-provided value
            valid_values: List of valid picklist values

        Returns:
            Matched canonical value, or None if no match
        """
        if not value or not valid_values:
            return None

        value_normalized = value.strip().lower()

        # First, try exact match (case-insensitive)
        for valid in valid_values:
            if valid.lower() == value_normalized:
                return valid

        # Try matching without whitespace
        value_no_space = re.sub(r"\s+", "", value_normalized)
        for valid in valid_values:
            if re.sub(r"\s+", "", valid.lower()) == value_no_space:
                return valid

        # Fuzzy matching using SequenceMatcher
        best_match = None
        best_ratio = 0.0

        for valid in valid_values:
            ratio = SequenceMatcher(None, value_normalized, valid.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = valid

        if best_ratio >= FUZZY_MATCH_THRESHOLD:
            LOGGER.info(f"Fuzzy matched '{value}' to '{best_match}' (ratio: {best_ratio:.2f})")
            return best_match

        return None

    def _validate_values(
        self, decomposition: Dict[str, Any], schema: ObjectSchema
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        Validate extracted values against picklist options.

        **Requirements: 3.4, 3.5, 3.6**

        Args:
            decomposition: Raw decomposition from LLM
            schema: Object schema for validation

        Returns:
            Tuple of (validated decomposition, list of warnings)
        """
        warnings: List[str] = []
        validated = decomposition.copy()

        # Validate target_filters
        target_filters = validated.get("target_filters", {})
        validated_filters: Dict[str, Any] = {}

        for field_name, value in target_filters.items():
            # Find the field in schema
            field_schema = schema.get_field(field_name)

            if field_schema is None:
                # Try to find by label
                for f in schema.filterable + schema.numeric + schema.date:
                    if f.label.lower() == field_name.lower():
                        field_schema = f
                        field_name = f.name  # Use API name
                        break

            if field_schema is None:
                warnings.append(f"Unknown field: {field_name}")
                validated_filters[field_name] = value
                continue

            # Validate picklist values
            if field_schema.type == "filterable" and field_schema.values:
                if isinstance(value, str):
                    matched = self._fuzzy_match(value, field_schema.values)
                    if matched:
                        validated_filters[field_name] = matched
                    else:
                        warnings.append(
                            f"Invalid value '{value}' for {field_name}. "
                            f"Valid values: {field_schema.values[:5]}"
                        )
                        validated_filters[field_name] = value
                elif isinstance(value, list):
                    validated_list = []
                    for v in value:
                        matched = self._fuzzy_match(str(v), field_schema.values)
                        if matched:
                            validated_list.append(matched)
                        else:
                            warnings.append(f"Invalid value '{v}' for {field_name}")
                            validated_list.append(v)
                    validated_filters[field_name] = validated_list
                else:
                    validated_filters[field_name] = value
            else:
                validated_filters[field_name] = value

        validated["target_filters"] = validated_filters

        return validated, warnings

    def _load_related_schemas(self, target_entity: str) -> List[ObjectSchema]:
        """
        Load schemas for entities related to the target.

        Args:
            target_entity: Target entity API name

        Returns:
            List of related ObjectSchemas
        """
        related: List[ObjectSchema] = []

        # Define common relationships
        relationship_map = {
            "ascendix__Deal__c": ["ascendix__Property__c", "ascendix__Availability__c"],
            "ascendix__Availability__c": ["ascendix__Property__c"],
            "ascendix__Lease__c": ["ascendix__Property__c", "Account"],
            "ascendix__Listing__c": ["ascendix__Property__c"],
            "ascendix__Inquiry__c": ["ascendix__Property__c", "Contact"],
        }

        related_entities = relationship_map.get(target_entity, [])

        for entity in related_entities:
            try:
                schema = self.schema_cache.get(entity)
                if schema:
                    related.append(schema)
            except Exception as e:
                LOGGER.warning(f"Failed to load related schema {entity}: {e}")

        return related

    def _build_system_prompt(self, schema_context: str, target_entity: str) -> str:
        """
        Build the system prompt with schema context.

        **Requirements: 9.1, 9.2, 9.3**

        Args:
            schema_context: Schema context string
            target_entity: Target entity for cross-object detection hints

        Returns:
            Complete system prompt
        """
        # Add cross-object query hints based on target entity
        cross_object_hints = self._get_cross_object_hints(target_entity)
        
        return f"""You are a query planner for a commercial real estate (CRE) Salesforce system.

## Available Schema
{schema_context}

{cross_object_hints}

## Your Task
Given a user query, decompose it into a structured query plan.

IMPORTANT RULES:
1. Use ONLY the field names and values shown in the schema above.
2. For picklist fields, use ONLY the exact values listed in brackets.
3. For CROSS-OBJECT queries (e.g., "availabilities in Plano"):
   - If the filter field (like City) exists on a RELATED object (Property) but NOT on the target (Availability)
   - Set needs_traversal: true
   - Put the filter in traversals with the related object
   - Example: "availabilities in Plano" → target_entity: Availability, traversals: [{{to: Property, filters: {{City: "Plano"}}}}]

Output JSON with:
- target_entity: The Salesforce object API name to query
- target_filters: Exact-match filters on the target entity {{field_api_name: value}}
- numeric_filters: Numeric comparisons {{field_api_name: {{"$gt"|"$lt"|"$gte"|"$lte": value}}}}
- date_filters: Date filters {{field_api_name: {{"$gt"|"$lt"|"days_ago": value}}}}
- traversals: Related entity filters [{{to: entity_api_name, filters: {{...}}}}]
- needs_traversal: true if filtering requires traversing relationships to a related object

Output ONLY valid JSON, no markdown, no explanation."""

    def _get_cross_object_hints(self, target_entity: str) -> str:
        """
        Get cross-object query hints for the target entity.

        **Requirements: 9.3**

        Args:
            target_entity: Target entity API name

        Returns:
            Cross-object hints string for LLM prompt
        """
        hints = []
        
        # Define cross-object relationships and common filter fields
        # NOTE: Field names must match actual Ascendix schema:
        # - ascendix__PropertyClass__c: Class A, B, C
        # - ascendix__PropertySubType__c: Office, Retail, Industrial, Warehouse, Multifamily
        # - ascendix__LandUse__c: Commercial, Residential, etc.
        cross_object_info = {
            "ascendix__Availability__c": {
                "parent": "ascendix__Property__c",
                "parent_fields": ["ascendix__City__c", "ascendix__State__c",
                                  "ascendix__PropertyClass__c", "ascendix__PropertySubType__c",
                                  "ascendix__LandUse__c", "ascendix__SubMarket__c"],
                "example": '"availabilities in Plano for Class A office" → filter Property by City=Plano, PropertyClass=A, PropertySubType=Office, traverse to Availability'
            },
            "ascendix__Lease__c": {
                "parent": "ascendix__Property__c",
                "parent_fields": ["ascendix__City__c", "ascendix__State__c",
                                  "ascendix__PropertyClass__c", "ascendix__PropertySubType__c",
                                  "ascendix__LandUse__c"],
                "example": '"leases in Dallas office buildings" → filter Property by City=Dallas, PropertySubType=Office, traverse to Lease'
            },
            "ascendix__Deal__c": {
                "parent": "ascendix__Property__c",
                "parent_fields": ["ascendix__City__c", "ascendix__State__c",
                                  "ascendix__PropertyClass__c", "ascendix__PropertySubType__c",
                                  "ascendix__LandUse__c"],
                "example": '"deals in Austin for Class A properties" → filter Property by City=Austin, PropertyClass=A, traverse to Deal'
            },
        }
        
        info = cross_object_info.get(target_entity)
        if info:
            hints.append("## Cross-Object Query Guidance")
            hints.append(f"The target object ({target_entity}) is related to {info['parent']}.")
            hints.append(f"Filterable fields exist on {info['parent']}, NOT on {target_entity}.")
            hints.append(f"Example: {info['example']}")
            hints.append("")

        # Add explicit field mapping rules to prevent LLM confusion
        hints.append("## CRITICAL Field Mapping Rules for Property Filters")
        hints.append("Use EXACTLY these field names when filtering properties:")
        hints.append("")
        hints.append("For PROPERTY TYPE (Office, Retail, Industrial, Warehouse, Multifamily):")
        hints.append("  → USE: RecordType")
        hints.append("  → This is the Salesforce Record Type name")
        hints.append("  → DO NOT USE: ascendix__PropertySubType__c or ascendix__LandUse__c")
        hints.append("")
        hints.append("For PROPERTY CLASS (Class A, Class B, Class C, or just A, B, C):")
        hints.append("  → USE: ascendix__PropertyClass__c")
        hints.append("  → Value should be just 'A', 'B', or 'C' (not 'Class A')")
        hints.append("")
        hints.append("For CITY (Plano, Dallas, Houston, Austin, etc.):")
        hints.append("  → USE: ascendix__City__c")
        hints.append("  → DO NOT USE: ascendix__Market__c or ascendix__SubMarket__c")
        hints.append("")
        hints.append("For STATE:")
        hints.append("  → USE: ascendix__State__c")
        hints.append("")

        return "\n".join(hints)

    def decompose(self, query: str) -> StructuredQuery:
        """
        Decompose natural language query into structured query.

        **Requirements: 3.1, 3.2, 3.3, 3.4, 3.7**
        **Task 29.6: Hard timeout with heuristic fallback**

        1. Detect target entity from query
        2. Load schema for target and related entities
        3. Build schema context for LLM prompt
        4. Call LLM for decomposition (with timeout)
        5. On timeout, fall back to heuristic decomposition
        6. Validate and normalize extracted values

        Args:
            query: Natural language query

        Returns:
            StructuredQuery with validated filters
        """
        start_time = time.time()
        timeout_seconds = SCHEMA_DECOMP_TIMEOUT_MS / 1000.0

        # Try LLM decomposition with timeout, fall back to heuristic on timeout
        # Task 29.6: Use explicit shutdown(wait=False) to avoid blocking on context manager exit
        executor = None
        try:
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(self._llm_decompose, query)
            try:
                result = future.result(timeout=timeout_seconds)
                elapsed_ms = (time.time() - start_time) * 1000
                LOGGER.info(
                    f"[DECOMPOSE] LLM decomposition completed in {elapsed_ms:.0f}ms "
                    f"(timeout={SCHEMA_DECOMP_TIMEOUT_MS}ms)"
                )
                return result
            except FuturesTimeoutError:
                elapsed_ms = (time.time() - start_time) * 1000
                LOGGER.warning(
                    f"[DECOMPOSE_TIMEOUT] LLM decomposition timed out after {elapsed_ms:.0f}ms "
                    f"(budget={SCHEMA_DECOMP_TIMEOUT_MS}ms), using heuristic fallback"
                )
                # Cancel the future (best effort - LLM call may still complete in background)
                future.cancel()
                # Use heuristic fallback immediately
                return self._heuristic_decompose(query)
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.error(
                f"[DECOMPOSE_ERROR] Unexpected error in decompose after {elapsed_ms:.0f}ms: {e}, "
                f"using heuristic fallback"
            )
            return self._heuristic_decompose(query)
        finally:
            # Shutdown without waiting - let background thread complete on its own
            if executor:
                executor.shutdown(wait=False)

    def _llm_decompose(self, query: str) -> StructuredQuery:
        """
        Internal LLM-based decomposition (called with timeout).

        **Task 29.6: Extracted from decompose() for timeout wrapping**

        Args:
            query: Natural language query

        Returns:
            StructuredQuery with validated filters
        """
        start_time = time.time()

        # 1. Detect target entity
        target_entity = self.detect_target_entity(query)

        # 2. Load schema for target
        try:
            target_schema = self.schema_cache.get(target_entity)
        except Exception as e:
            LOGGER.warning(f"Failed to load schema for {target_entity}: {e}")
            target_schema = None

        # If no schema, return basic decomposition
        if target_schema is None:
            LOGGER.warning(
                f"No schema available for {target_entity}, returning basic decomposition"
            )
            return StructuredQuery(
                target_entity=target_entity,
                original_query=query,
                confidence=0.5,
                validation_warnings=[f"No schema available for {target_entity}"],
            )

        # 3. Load related schemas
        related_schemas = self._load_related_schemas(target_entity)

        # 4. Build schema context
        schema_context = self._build_schema_context(target_schema, related_schemas)

        # 5. Build system prompt with cross-object hints
        system_prompt = self._build_system_prompt(schema_context, target_entity)

        # 6. Call LLM
        try:
            response = self.llm_client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(
                    {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 512,
                        "temperature": 0,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": query}],
                    }
                ),
            )

            response_body = json.loads(response["body"].read())
            content = response_body["content"][0]["text"]

            # Strip markdown code blocks if present
            json_content = content.strip()
            if json_content.startswith("```"):
                first_newline = json_content.find("\n")
                if first_newline > 0:
                    json_content = json_content[first_newline + 1 :]
                if json_content.endswith("```"):
                    json_content = json_content[:-3].strip()

            decomposition = json.loads(json_content)

        except json.JSONDecodeError as e:
            LOGGER.warning(f"Failed to parse LLM response: {e}")
            return StructuredQuery(
                target_entity=target_entity,
                original_query=query,
                confidence=0.3,
                validation_warnings=[f"Failed to parse LLM response: {e}"],
            )
        except Exception as e:
            LOGGER.error(f"LLM call failed: {e}")
            return StructuredQuery(
                target_entity=target_entity,
                original_query=query,
                confidence=0.3,
                validation_warnings=[f"LLM call failed: {e}"],
            )

        # 7. Validate and normalize values
        validated, warnings = self._validate_values(decomposition, target_schema)

        # 8. Build StructuredQuery
        elapsed_ms = (time.time() - start_time) * 1000

        # Detect cross-object traversal from LLM response
        # **Requirements: 9.1, 9.2, 9.4**
        needs_cross_object = validated.get("needs_traversal", False)
        traversals = validated.get("traversals", [])
        cross_object_filter_entity = None
        cross_object_path = []

        if needs_cross_object and traversals:
            # Extract the filter entity from traversals
            for traversal in traversals:
                filter_entity = traversal.get("to")
                if filter_entity:
                    cross_object_filter_entity = filter_entity
                    cross_object_path = [target_entity, filter_entity]
                    break

        result = StructuredQuery(
            target_entity=validated.get("target_entity", target_entity),
            filters=validated.get("target_filters", {}),
            numeric_filters=validated.get("numeric_filters", {}),
            date_filters=validated.get("date_filters", {}),
            traversals=traversals,
            confidence=1.0 - (len(warnings) * 0.1),  # Reduce confidence for each warning
            original_query=query,
            validation_warnings=warnings,
            needs_cross_object_traversal=needs_cross_object,
            cross_object_filter_entity=cross_object_filter_entity,
            cross_object_path=cross_object_path,
        )

        LOGGER.info(
            f"Decomposed query in {elapsed_ms:.0f}ms: "
            f"entity={result.target_entity}, "
            f"filters={len(result.filters)}, "
            f"needs_cross_object={needs_cross_object}, "
            f"warnings={len(warnings)}"
        )

        return result


def normalize_value(value: str, valid_values: List[str]) -> str:
    """
    Normalize a value to match canonical picklist value.

    **Property 4: Value Normalization**
    **Validates: Requirements 3.5, 3.6**

    Handles:
    - Case normalization (e.g., "class a" → "A")
    - Whitespace normalization
    - Fuzzy matching for close matches

    Args:
        value: User-provided value
        valid_values: List of valid picklist values

    Returns:
        Normalized canonical value, or original if no match
    """
    if not value or not valid_values:
        return value

    value_normalized = value.strip().lower()

    # Exact match (case-insensitive)
    for valid in valid_values:
        if valid.lower() == value_normalized:
            return valid

    # Match without whitespace
    value_no_space = re.sub(r"\s+", "", value_normalized)
    for valid in valid_values:
        if re.sub(r"\s+", "", valid.lower()) == value_no_space:
            return valid

    # Fuzzy matching
    best_match = None
    best_ratio = 0.0

    for valid in valid_values:
        ratio = SequenceMatcher(None, value_normalized, valid.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = valid

    if best_ratio >= FUZZY_MATCH_THRESHOLD:
        return best_match

    # No match found, return original
    return value


# Convenience function for simple usage
def decompose_with_schema(
    query: str, schema_cache: Optional[SchemaCache] = None
) -> StructuredQuery:
    """
    Convenience function to decompose a query with schema validation.

    Args:
        query: Natural language query
        schema_cache: Optional SchemaCache instance

    Returns:
        StructuredQuery with validated filters
    """
    decomposer = SchemaAwareDecomposer(schema_cache=schema_cache)
    return decomposer.decompose(query)
