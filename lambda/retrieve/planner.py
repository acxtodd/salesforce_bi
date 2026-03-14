"""
Planner for Graph-Aware Zero-Config Retrieval.

The Planner is the central orchestrator that analyzes natural language queries
and emits structured execution plans. It integrates EntityLinker, ValueNormalizer,
TraversalPlanner, and EntityResolver to translate user intent into structured
filters and traversal specifications.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 1.1, 1.2, 1.3, 1.4, 8.1, 15.1, 15.2, 15.3**
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Protocol

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))


# =============================================================================
# Constants and Configuration
# =============================================================================

# Default timeout for planning (500ms per Requirements 1.2)
DEFAULT_TIMEOUT_MS = 500

# Default confidence threshold for fallback (Requirements 1.3)
DEFAULT_CONFIDENCE_THRESHOLD = 0.5

# Minimum confidence score
MIN_CONFIDENCE = 0.0

# Maximum confidence score
MAX_CONFIDENCE = 1.0


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Predicate:
    """
    Represents a structured filter predicate.

    **Requirements: 1.1**

    Attributes:
        field: Field API name (e.g., "PropertyClass__c")
        operator: Comparison operator (eq, gt, lt, gte, lte, in, contains, between)
        value: Normalized value
        source_object: Object name for cross-object filters (optional)
    """

    field: str
    operator: str
    value: Any
    source_object: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate operator."""
        valid_operators = {
            "eq",
            "gt",
            "lt",
            "gte",
            "lte",
            "in",
            "contains",
            "between",
            "range",
        }
        if self.operator not in valid_operators:
            raise ValueError(
                f"Invalid operator: {self.operator}. Must be one of {valid_operators}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "field": self.field,
            "operator": self.operator,
            "value": self._serialize_value(self.value),
        }
        if self.source_object:
            result["source_object"] = self.source_object
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Predicate":
        """Create Predicate from dictionary."""
        return cls(
            field=data.get("field", ""),
            operator=data.get("operator", "eq"),
            value=data.get("value"),
            source_object=data.get("source_object"),
        )

    def _serialize_value(self, value: Any) -> Any:
        """Serialize value for JSON compatibility."""
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if hasattr(value, "to_string"):
            return value.to_string()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, (list, tuple)):
            return [self._serialize_value(v) for v in value]
        return value


@dataclass
class StructuredPlan:
    """
    Represents a structured execution plan emitted by the Planner.

    **Requirements: 1.1, 15.1, 15.2**

    Attributes:
        target_object: Target Salesforce object (e.g., "Availability", "Property")
        predicates: List of structured filter predicates
        traversal_plan: Optional graph traversal specification
        seed_ids: Optional pre-resolved record IDs
        confidence: Confidence score (0.0-1.0)
        query: Original query string
        planning_time_ms: Time taken to generate the plan
    """

    target_object: str
    predicates: List[Predicate] = field(default_factory=list)
    traversal_plan: Optional[Any] = None  # TraversalPlan from traversal_planner
    seed_ids: Optional[List[str]] = None
    confidence: float = 0.0
    query: str = ""
    planning_time_ms: float = 0.0

    def __post_init__(self) -> None:
        """Validate confidence score."""
        if not MIN_CONFIDENCE <= self.confidence <= MAX_CONFIDENCE:
            self.confidence = max(MIN_CONFIDENCE, min(MAX_CONFIDENCE, self.confidence))

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for serialization.

        **Requirements: 15.1**
        """
        result = {
            "target_object": self.target_object,
            "predicates": [p.to_dict() for p in self.predicates],
            "confidence": self.confidence,
            "query": self.query,
            "planning_time_ms": self.planning_time_ms,
        }
        if self.traversal_plan:
            if hasattr(self.traversal_plan, "to_dict"):
                result["traversal_plan"] = self.traversal_plan.to_dict()
            else:
                result["traversal_plan"] = self.traversal_plan
        if self.seed_ids:
            result["seed_ids"] = self.seed_ids
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StructuredPlan":
        """
        Create StructuredPlan from dictionary.

        **Requirements: 15.2**
        """
        predicates = [Predicate.from_dict(p) for p in data.get("predicates", [])]

        # Handle traversal_plan reconstruction
        traversal_plan = None
        if data.get("traversal_plan"):
            # Import here to avoid circular dependency
            try:
                from traversal_planner import TraversalPlan

                traversal_plan = TraversalPlan.from_dict(data["traversal_plan"])
            except (ImportError, Exception):
                traversal_plan = data["traversal_plan"]

        return cls(
            target_object=data.get("target_object", ""),
            predicates=predicates,
            traversal_plan=traversal_plan,
            seed_ids=data.get("seed_ids"),
            confidence=float(data.get("confidence", 0.0)),
            query=data.get("query", ""),
            planning_time_ms=float(data.get("planning_time_ms", 0.0)),
        )

    def is_fallback(self) -> bool:
        """Check if this is a fallback plan (low confidence, no predicates)."""
        return self.confidence == 0.0 and not self.predicates


# =============================================================================
# Protocol Definitions (for dependency injection)
# =============================================================================


class VocabCacheProtocol(Protocol):
    """Protocol for VocabCache."""

    def lookup(
        self, term: str, vocab_type: Optional[str] = None
    ) -> Optional[Dict[str, Any]]: ...

    def get_terms(self, vocab_type: str, object_name: str) -> List[Dict[str, Any]]: ...


class SchemaCacheProtocol(Protocol):
    """Protocol for SchemaCache."""

    def get(self, object_name: str) -> Optional[Any]: ...


class EntityLinkerProtocol(Protocol):
    """Protocol for EntityLinker."""

    def link(self, query: str) -> Any: ...


class ValueNormalizerProtocol(Protocol):
    """Protocol for ValueNormalizer."""

    def normalize(
        self,
        value: str,
        field_type: str,
        object_name: Optional[str] = None,
        field_name: Optional[str] = None,
        reference_date: Optional[date] = None,
    ) -> Any: ...

    def normalize_auto(
        self,
        value: str,
        object_name: Optional[str] = None,
        field_name: Optional[str] = None,
        reference_date: Optional[date] = None,
    ) -> Any: ...


class TraversalPlannerProtocol(Protocol):
    """Protocol for TraversalPlanner."""

    def plan(
        self,
        start_object: str,
        target_object: str,
        predicates: Optional[List[Dict[str, Any]]] = None,
        max_depth: Optional[int] = None,
        node_cap: Optional[int] = None,
        timeout_ms: Optional[int] = None,
    ) -> Optional[Any]: ...


class EntityResolverProtocol(Protocol):
    """Protocol for EntityResolver."""

    def resolve(
        self,
        name: str,
        object_type: Optional[str] = None,
        max_matches: Optional[int] = None,
    ) -> Any: ...


# =============================================================================
# Planner Class
# =============================================================================


class Planner:
    """
    Central orchestrator for query planning.

    **Requirements: 1.1, 1.2, 1.3, 1.4, 8.1**

    The Planner:
    1. Analyzes natural language queries
    2. Performs entity linking to map terms to objects/fields
    3. Normalizes values (dates, sizes, percentages, etc.)
    4. Plans graph traversals for cross-object queries
    5. Resolves entity names to record IDs
    6. Emits structured execution plans with confidence scores
    """

    # Common CRE object mappings
    OBJECT_KEYWORDS = {
        "availability": "ascendix__Availability__c",
        "availabilities": "ascendix__Availability__c",
        "space": "ascendix__Availability__c",
        "spaces": "ascendix__Availability__c",
        "property": "ascendix__Property__c",
        "properties": "ascendix__Property__c",
        "building": "ascendix__Property__c",
        "buildings": "ascendix__Property__c",
        "lease": "ascendix__Lease__c",
        "leases": "ascendix__Lease__c",
        "deal": "ascendix__Deal__c",
        "deals": "ascendix__Deal__c",
        "sale": "ascendix__Sale__c",
        "sales": "ascendix__Sale__c",
        "account": "Account",
        "accounts": "Account",
        "company": "Account",
        "companies": "Account",
        "contact": "Contact",
        "contacts": "Contact",
        "activity": "Task",
        "activities": "Task",
        "task": "Task",
        "tasks": "Task",
        "event": "Event",
        "events": "Event",
        "note": "Note",
        "notes": "Note",
    }

    def __init__(
        self,
        vocab_cache: Optional[VocabCacheProtocol] = None,
        schema_cache: Optional[SchemaCacheProtocol] = None,
        entity_linker: Optional[EntityLinkerProtocol] = None,
        value_normalizer: Optional[ValueNormalizerProtocol] = None,
        traversal_planner: Optional[TraversalPlannerProtocol] = None,
        entity_resolver: Optional[EntityResolverProtocol] = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ):
        """
        Initialize the Planner.

        **Requirements: 1.1**

        Args:
            vocab_cache: VocabCache instance for term lookup
            schema_cache: SchemaCache instance for relationship metadata
            entity_linker: EntityLinker instance (created if not provided)
            value_normalizer: ValueNormalizer instance (created if not provided)
            traversal_planner: TraversalPlanner instance (created if not provided)
            entity_resolver: EntityResolver instance (created if not provided)
            timeout_ms: Planning timeout in milliseconds (default 500ms)
            confidence_threshold: Threshold for fallback (default 0.5)
        """
        self.vocab_cache = vocab_cache
        self.schema_cache = schema_cache
        self.timeout_ms = timeout_ms
        self.confidence_threshold = confidence_threshold

        # Initialize components (lazy or provided)
        self._entity_linker = entity_linker
        self._value_normalizer = value_normalizer
        self._traversal_planner = traversal_planner
        self._entity_resolver = entity_resolver

    @property
    def entity_linker(self) -> EntityLinkerProtocol:
        """Lazy initialization of EntityLinker."""
        if self._entity_linker is None:
            from entity_linker import EntityLinker

            self._entity_linker = EntityLinker(self.vocab_cache)
        return self._entity_linker

    @property
    def value_normalizer(self) -> ValueNormalizerProtocol:
        """Lazy initialization of ValueNormalizer."""
        if self._value_normalizer is None:
            from value_normalizer import ValueNormalizer

            self._value_normalizer = ValueNormalizer(self.vocab_cache)
        return self._value_normalizer

    @property
    def traversal_planner(self) -> TraversalPlannerProtocol:
        """Lazy initialization of TraversalPlanner."""
        if self._traversal_planner is None:
            from traversal_planner import TraversalPlanner

            self._traversal_planner = TraversalPlanner(self.schema_cache)
        return self._traversal_planner

    @property
    def entity_resolver(self) -> EntityResolverProtocol:
        """Lazy initialization of EntityResolver."""
        if self._entity_resolver is None:
            from entity_resolver import EntityResolver

            self._entity_resolver = EntityResolver()
        return self._entity_resolver

    def plan(
        self,
        query: str,
        timeout_ms: Optional[int] = None,
        reference_date: Optional[date] = None,
    ) -> StructuredPlan:
        """
        Analyze query and emit structured plan.

        **Requirements: 1.1, 1.2, 8.1**

        Args:
            query: Natural language query
            timeout_ms: Override default timeout (milliseconds)
            reference_date: Reference date for temporal expressions

        Returns:
            StructuredPlan with target object, predicates, and confidence
        """
        start_time = time.time()
        effective_timeout = timeout_ms if timeout_ms is not None else self.timeout_ms
        timeout_seconds = effective_timeout / 1000.0

        if not query or not query.strip():
            return self._create_fallback_plan(query, 0.0, "empty_query")

        # Calculate deadline for cooperative cancellation
        deadline = start_time + timeout_seconds

        try:
            # Use ThreadPoolExecutor for timeout enforcement
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self._do_planning,
                    query,
                    reference_date,
                    start_time,
                    deadline,  # Pass deadline for cooperative cancellation
                )
                try:
                    plan = future.result(timeout=timeout_seconds)
                    return plan
                except FuturesTimeoutError:
                    # Timeout - return fallback plan
                    elapsed_ms = (time.time() - start_time) * 1000
                    LOGGER.warning(
                        f"Planner timeout after {elapsed_ms:.1f}ms for query: {query[:100]}"
                    )
                    self._log_telemetry(
                        query=query,
                        plan=None,
                        elapsed_ms=elapsed_ms,
                        event="timeout",
                    )
                    return self._create_fallback_plan(query, elapsed_ms, "timeout")

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.error(f"Planner error: {e}")
            self._log_telemetry(
                query=query,
                plan=None,
                elapsed_ms=elapsed_ms,
                event="error",
                error=str(e),
            )
            return self._create_fallback_plan(query, elapsed_ms, "error")

    def _do_planning(
        self,
        query: str,
        reference_date: Optional[date],
        start_time: float,
        deadline: float,
    ) -> StructuredPlan:
        """
        Perform the actual planning work with cooperative cancellation.

        **Requirements: 1.1, 1.2**

        The deadline parameter enables cooperative cancellation - if the deadline
        is exceeded at any checkpoint, we return a fallback plan immediately rather
        than continuing expensive work that will be discarded anyway.
        """

        def _check_deadline(step_name: str) -> bool:
            """Check if deadline exceeded. Returns True if we should abort."""
            if time.time() > deadline:
                elapsed_ms = (time.time() - start_time) * 1000
                LOGGER.warning(
                    f"Planner cooperative cancel at {step_name}: "
                    f"elapsed={elapsed_ms:.0f}ms, deadline exceeded"
                )
                return True
            return False

        # Step 1: Entity linking
        linking_result = self.entity_linker.link(query)

        # Checkpoint after entity linking (often the slowest step)
        if _check_deadline("entity_linking"):
            elapsed_ms = (time.time() - start_time) * 1000
            return self._create_fallback_plan(query, elapsed_ms, "cooperative_cancel")

        # Step 2: Determine target object
        target_object = self._determine_target_object(query, linking_result)

        # Checkpoint after target object determination
        if _check_deadline("target_object"):
            elapsed_ms = (time.time() - start_time) * 1000
            return self._create_fallback_plan(query, elapsed_ms, "cooperative_cancel")

        # Step 3: Build predicates from entity matches
        predicates = self._build_predicates(linking_result, reference_date)

        # Checkpoint after predicate building
        if _check_deadline("build_predicates"):
            elapsed_ms = (time.time() - start_time) * 1000
            return self._create_fallback_plan(query, elapsed_ms, "cooperative_cancel")

        # Step 4: Check for entity names to resolve
        seed_ids = self._resolve_entity_names(query, target_object)

        # Checkpoint after entity resolution
        if _check_deadline("entity_resolution"):
            elapsed_ms = (time.time() - start_time) * 1000
            return self._create_fallback_plan(query, elapsed_ms, "cooperative_cancel")

        # Step 5: Plan traversal if cross-object query detected
        traversal_plan = self._plan_traversal(query, target_object, linking_result)

        # Checkpoint after traversal planning
        if _check_deadline("traversal_planning"):
            elapsed_ms = (time.time() - start_time) * 1000
            return self._create_fallback_plan(query, elapsed_ms, "cooperative_cancel")

        # Step 6: Calculate confidence (Task 42.3: includes field relevance boost)
        confidence = self._calculate_confidence(
            linking_result,
            predicates,
            seed_ids,
            traversal_plan,
            target_object,
        )

        elapsed_ms = (time.time() - start_time) * 1000

        plan = StructuredPlan(
            target_object=target_object,
            predicates=predicates,
            traversal_plan=traversal_plan,
            seed_ids=seed_ids if seed_ids else None,
            confidence=confidence,
            query=query,
            planning_time_ms=elapsed_ms,
        )

        # Log telemetry
        self._log_telemetry(
            query=query,
            plan=plan,
            elapsed_ms=elapsed_ms,
            event="success",
        )

        return plan

    def _determine_target_object(self, query: str, linking_result: Any) -> str:
        """
        Determine the target Salesforce object from query and linking result.

        Args:
            query: Original query
            linking_result: Result from entity linker

        Returns:
            Target object API name
        """
        query_lower = query.lower()

        # Check for explicit object keywords in query
        for keyword, obj_name in self.OBJECT_KEYWORDS.items():
            if keyword in query_lower:
                return obj_name

        # Check entity linking matches for object hints
        if hasattr(linking_result, "matches") and linking_result.matches:
            # Use the object from the highest confidence match
            best_match = max(linking_result.matches, key=lambda m: m.confidence)
            if best_match.object_name:
                return best_match.object_name

        # Default to Property for CRE queries
        return "ascendix__Property__c"

    def _build_predicates(
        self,
        linking_result: Any,
        reference_date: Optional[date],
    ) -> List[Predicate]:
        """
        Build predicates from entity linking result.

        Args:
            linking_result: Result from entity linker
            reference_date: Reference date for temporal expressions

        Returns:
            List of Predicate objects
        """
        predicates: List[Predicate] = []

        if not hasattr(linking_result, "matches"):
            return predicates

        for match in linking_result.matches:
            if not match.field_name or not match.value:
                continue

            # Determine operator based on value type
            operator = "eq"
            value = match.value

            # Try to normalize the value
            try:
                normalized = self.value_normalizer.normalize_auto(
                    str(match.value),
                    object_name=match.object_name,
                    field_name=match.field_name,
                    reference_date=reference_date,
                )
                if hasattr(normalized, "operator"):
                    operator = normalized.operator
                if hasattr(normalized, "value"):
                    value = normalized.value
            except Exception as e:
                LOGGER.debug(f"Value normalization failed for {match.value}: {e}")

            predicates.append(
                Predicate(
                    field=match.field_name,
                    operator=operator,
                    value=value,
                    source_object=match.object_name,
                )
            )

        return predicates

    def _resolve_entity_names(
        self,
        query: str,
        target_object: str,
    ) -> List[str]:
        """
        Resolve entity names in query to record IDs.

        **Requirements: 6.1, 6.2**

        Args:
            query: Original query
            target_object: Target object type

        Returns:
            List of resolved record IDs (seed IDs)
        """
        seed_ids: List[str] = []

        # Look for quoted names or proper nouns
        # Pattern: "Name" or capitalized multi-word names
        quoted_pattern = r'"([^"]+)"'
        quoted_matches = re.findall(quoted_pattern, query)

        for name in quoted_matches:
            try:
                result = self.entity_resolver.resolve(name)
                if hasattr(result, "seed_ids") and result.seed_ids:
                    seed_ids.extend(result.seed_ids[:5])  # Limit to top 5
            except Exception as e:
                LOGGER.debug(f"Entity resolution failed for '{name}': {e}")

        return seed_ids

    def _plan_traversal(
        self,
        query: str,
        target_object: str,
        linking_result: Any,
    ) -> Optional[Any]:
        """
        Plan graph traversal for cross-object queries.

        **Requirements: 4.1**

        Args:
            query: Original query
            target_object: Target object type
            linking_result: Result from entity linker

        Returns:
            TraversalPlan if cross-object query detected, None otherwise
        """
        # Detect if query involves multiple objects
        objects_mentioned: set = {target_object}

        if hasattr(linking_result, "matches"):
            for match in linking_result.matches:
                if match.object_name and match.object_name != target_object:
                    objects_mentioned.add(match.object_name)

        # If multiple objects, plan traversal
        if len(objects_mentioned) > 1:
            # Find the "start" object (usually the one with filters)
            start_object = None
            for match in linking_result.matches:
                if match.object_name != target_object:
                    start_object = match.object_name
                    break

            if start_object:
                try:
                    return self.traversal_planner.plan(
                        start_object=start_object,
                        target_object=target_object,
                    )
                except Exception as e:
                    LOGGER.debug(f"Traversal planning failed: {e}")

        return None

    def _calculate_confidence(
        self,
        linking_result: Any,
        predicates: List[Predicate],
        seed_ids: List[str],
        traversal_plan: Optional[Any],
        target_object: Optional[str] = None,
    ) -> float:
        """
        Calculate overall confidence score for the plan.

        **Requirements: 1.1, Task 42.3**

        Boosts confidence when using high-relevance fields from signal harvesting.

        Args:
            linking_result: Result from entity linker
            predicates: Built predicates
            seed_ids: Resolved seed IDs
            traversal_plan: Traversal plan (if any)
            target_object: Target object for schema lookup (Task 42.3)

        Returns:
            Confidence score (0.0-1.0)
        """
        confidence = 0.0

        # Base confidence from entity linking
        if hasattr(linking_result, "confidence"):
            confidence = linking_result.confidence * 0.4

        # Boost for predicates, with additional boost for high-relevance fields (Task 42.3)
        if predicates:
            predicate_boost = 0.0
            high_relevance_count = 0

            for pred in predicates:
                predicate_boost += 0.1

                # Check field relevance from schema cache (Task 42.3)
                if self.schema_cache and target_object and pred.field:
                    try:
                        schema = self.schema_cache.get(target_object)
                        if schema:
                            field = schema.get_field(pred.field) if hasattr(schema, 'get_field') else None
                            if field and hasattr(field, 'relevance_score') and field.relevance_score is not None:
                                # High-relevance field (score >= 7, i.e., signal-harvested)
                                if field.relevance_score >= 7.0:
                                    high_relevance_count += 1
                    except Exception:
                        pass

            # Cap base predicate boost at 0.3
            predicate_boost = min(predicate_boost, 0.3)

            # Additional boost for high-relevance fields (up to 0.1)
            relevance_boost = min(high_relevance_count * 0.03, 0.1)

            confidence += predicate_boost + relevance_boost

        # Boost for seed IDs
        if seed_ids:
            confidence += 0.2

        # Boost for successful traversal plan
        if traversal_plan:
            confidence += 0.1

        return min(confidence, MAX_CONFIDENCE)

    def _create_fallback_plan(
        self,
        query: str,
        elapsed_ms: float,
        reason: str,
    ) -> StructuredPlan:
        """
        Create a fallback plan for timeout or error cases.

        **Requirements: 1.2, 8.1**

        Args:
            query: Original query
            elapsed_ms: Time elapsed before fallback
            reason: Reason for fallback

        Returns:
            Fallback StructuredPlan with confidence=0
        """
        LOGGER.info(
            f"Creating fallback plan: reason={reason}, elapsed_ms={elapsed_ms:.1f}"
        )

        return StructuredPlan(
            target_object="",
            predicates=[],
            traversal_plan=None,
            seed_ids=None,
            confidence=0.0,
            query=query,
            planning_time_ms=elapsed_ms,
        )

    def should_fallback(self, plan: StructuredPlan) -> bool:
        """
        Check if plan should trigger fallback to vector search.

        **Requirements: 1.3**

        Args:
            plan: The structured plan to check

        Returns:
            True if fallback should be triggered
        """
        return plan.confidence < self.confidence_threshold

    def _log_telemetry(
        self,
        query: str,
        plan: Optional[StructuredPlan],
        elapsed_ms: float,
        event: str,
        error: Optional[str] = None,
    ) -> None:
        """
        Log telemetry for planner operations.

        **Requirements: 1.4, 12.5**

        Args:
            query: Original query
            plan: Generated plan (if any)
            elapsed_ms: Planning time
            event: Event type (success, timeout, error)
            error: Error message (if any)
        """
        telemetry = {
            "event": f"planner_{event}",
            "query": query[:200],  # Truncate long queries
            "elapsed_ms": elapsed_ms,
        }

        if plan:
            telemetry.update(
                {
                    "target_object": plan.target_object,
                    "predicate_count": len(plan.predicates),
                    "has_traversal": plan.traversal_plan is not None,
                    "has_seed_ids": bool(plan.seed_ids),
                    "confidence": plan.confidence,
                }
            )

        if error:
            telemetry["error"] = error

        LOGGER.info(f"Planner telemetry: {json.dumps(telemetry)}")

    # =========================================================================
    # Serialization Methods
    # =========================================================================

    def to_json(self, plan: StructuredPlan) -> str:
        """
        Serialize plan to JSON string.

        **Requirements: 15.1**

        Args:
            plan: StructuredPlan to serialize

        Returns:
            JSON string representation
        """
        return json.dumps(plan.to_dict(), default=str)

    def from_json(self, json_str: str) -> StructuredPlan:
        """
        Deserialize plan from JSON string.

        **Requirements: 15.2**

        Args:
            json_str: JSON string to deserialize

        Returns:
            StructuredPlan instance
        """
        data = json.loads(json_str)
        return StructuredPlan.from_dict(data)


# =============================================================================
# Convenience Functions
# =============================================================================


def create_plan(
    query: str,
    vocab_cache: Optional[VocabCacheProtocol] = None,
    schema_cache: Optional[SchemaCacheProtocol] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> StructuredPlan:
    """
    Convenience function to create a plan for a query.

    **Requirements: 1.1**

    Args:
        query: Natural language query
        vocab_cache: Optional vocab cache
        schema_cache: Optional schema cache
        timeout_ms: Planning timeout

    Returns:
        StructuredPlan
    """
    planner = Planner(
        vocab_cache=vocab_cache,
        schema_cache=schema_cache,
        timeout_ms=timeout_ms,
    )
    return planner.plan(query)


def is_fallback_plan(plan: StructuredPlan) -> bool:
    """
    Check if a plan is a fallback plan.

    Args:
        plan: Plan to check

    Returns:
        True if this is a fallback plan
    """
    return plan.is_fallback()
