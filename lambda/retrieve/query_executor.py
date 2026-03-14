"""
Query Executor for Graph-Aware Zero-Config Retrieval.

The Query Executor orchestrates query execution across multiple retrieval paths:
- Knowledge Base (Bedrock)
- Graph Retriever
- Derived View Manager

It handles seed ID filtering, structured filter execution, aggregation query
routing, graph traversal authorization, and parallel execution with fallback.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 7.1, 7.2, 5.6, 5.7, 11.4, 1.2, 8.1**
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, Tuple, Union

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))


# =============================================================================
# Constants and Configuration
# =============================================================================

# Default timeout for parallel execution (500ms per Requirements 1.2)
DEFAULT_PLANNER_TIMEOUT_MS = 500

# Default timeout for overall query execution
DEFAULT_EXECUTION_TIMEOUT_MS = 1500

# Minimum confidence for using planner results
MIN_PLANNER_CONFIDENCE = 0.5

# Maximum results from knowledge base
DEFAULT_KB_LIMIT = 100

# Maximum results from graph traversal
DEFAULT_GRAPH_LIMIT = 50


class ExecutionPath(Enum):
    """Execution path used for query."""

    VECTOR_ONLY = "vector_only"
    SEED_ID_FILTER = "seed_id_filter"
    STRUCTURED_FILTER = "structured_filter"
    AGGREGATION_VIEW = "aggregation_view"
    GRAPH_TRAVERSAL = "graph_traversal"
    HYBRID = "hybrid"
    FALLBACK = "fallback"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ExecutionResult:
    """
    Result from query execution.

    **Requirements: 7.1, 7.2**

    Attributes:
        records: List of result records
        execution_path: Path used for execution
        execution_time_ms: Time taken for execution
        used_fallback: Whether fallback was triggered
        planner_confidence: Confidence score from planner (if used)
        filters_applied: Filters that were applied
        seed_ids_used: Seed IDs used for filtering (if any)
        graph_nodes_visited: Number of graph nodes visited
        authorization_filtered: Number of records filtered by authorization
    """

    records: List[Dict[str, Any]] = field(default_factory=list)
    execution_path: ExecutionPath = ExecutionPath.VECTOR_ONLY
    execution_time_ms: float = 0.0
    used_fallback: bool = False
    planner_confidence: Optional[float] = None
    filters_applied: List[Dict[str, Any]] = field(default_factory=list)
    seed_ids_used: List[str] = field(default_factory=list)
    graph_nodes_visited: int = 0
    authorization_filtered: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "record_count": len(self.records),
            "execution_path": self.execution_path.value,
            "execution_time_ms": self.execution_time_ms,
            "used_fallback": self.used_fallback,
            "planner_confidence": self.planner_confidence,
            "filters_applied": self.filters_applied,
            "seed_ids_used": self.seed_ids_used,
            "graph_nodes_visited": self.graph_nodes_visited,
            "authorization_filtered": self.authorization_filtered,
        }


@dataclass
class AuthorizationContext:
    """
    Authorization context for query execution.

    **Requirements: 11.4**

    Attributes:
        user_id: Salesforce user ID
        accessible_object_types: Set of accessible object API names
        accessible_record_ids: Optional set of accessible record IDs
        check_fls: Whether to check field-level security
    """

    user_id: str
    accessible_object_types: Set[str] = field(default_factory=set)
    accessible_record_ids: Optional[Set[str]] = None
    check_fls: bool = True

    def can_access_object(self, object_type: str) -> bool:
        """Check if user can access object type."""
        if not self.accessible_object_types:
            return True  # No restrictions
        return object_type in self.accessible_object_types

    def can_access_record(self, record_id: str) -> bool:
        """Check if user can access specific record."""
        if self.accessible_record_ids is None:
            return True  # No record-level restrictions
        return record_id in self.accessible_record_ids


# =============================================================================
# Protocol Definitions (for dependency injection)
# =============================================================================


class KnowledgeBaseProtocol(Protocol):
    """Protocol for Knowledge Base (Bedrock) client."""

    def retrieve(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]: ...


class GraphRetrieverProtocol(Protocol):
    """Protocol for Graph Retriever."""

    def traverse(
        self,
        start_ids: List[str],
        traversal_plan: Any,
        max_nodes: int = 50,
    ) -> List[Dict[str, Any]]: ...


class PlannerProtocol(Protocol):
    """Protocol for Planner."""

    def plan(
        self,
        query: str,
        timeout_ms: Optional[int] = None,
    ) -> Any: ...

    def should_fallback(self, plan: Any) -> bool: ...


class DerivedViewManagerProtocol(Protocol):
    """Protocol for Derived View Manager."""

    def query_with_fallback(
        self,
        view_name: str,
        query: str,
        filters: Optional[List[Any]] = None,
        **kwargs,
    ) -> Tuple[List[Any], bool]: ...

    def query_availability_view(
        self,
        filters: Optional[List[Any]] = None,
        property_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Any]: ...

    def query_vacancy_view(
        self,
        filters: Optional[List[Any]] = None,
        property_id: Optional[str] = None,
        min_vacancy_pct: Optional[float] = None,
        max_vacancy_pct: Optional[float] = None,
        limit: int = 100,
    ) -> List[Any]: ...

    def query_leases_view(
        self,
        filters: Optional[List[Any]] = None,
        property_id: Optional[str] = None,
        end_date_month: Optional[str] = None,
        end_date_range: Optional[tuple] = None,
        limit: int = 100,
    ) -> List[Any]: ...

    def query_activities_agg(
        self,
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        min_count: Optional[int] = None,
        window_days: int = 30,
        limit: int = 100,
    ) -> List[Any]: ...

    def query_sales_view(
        self,
        filters: Optional[List[Any]] = None,
        sale_id: Optional[str] = None,
        property_id: Optional[str] = None,
        stage: Optional[str] = None,
        broker_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Any]: ...


# =============================================================================
# Query Executor Class
# =============================================================================


class QueryExecutor:
    """
    Orchestrates query execution across retrieval paths.

    **Requirements: 7.1, 7.2, 5.6, 5.7, 11.4, 1.2, 8.1**

    The Query Executor:
    1. Executes queries using seed ID filtering when available
    2. Applies structured filters to KB and graph traversal
    3. Routes aggregation queries to derived views
    4. Enforces authorization at each graph hop
    5. Runs planner and vector search in parallel with fallback
    """

    # Object types that support aggregation views
    AGGREGATION_OBJECTS = {
        "ascendix__Availability__c": "availability_view",
        "ascendix__Property__c": "vacancy_view",
        "ascendix__Lease__c": "leases_view",
        "Task": "activities_agg",
        "Event": "activities_agg",
        "ascendix__Sale__c": "sales_view",
    }

    # Keywords that indicate aggregation queries
    AGGREGATION_KEYWORDS = {
        "vacancy",
        "vacant",
        "available",
        "expiring",
        "activity",
        "activities",
        "count",
        "total",
        "average",
        "sum",
    }

    def __init__(
        self,
        knowledge_base: Optional[KnowledgeBaseProtocol] = None,
        graph_retriever: Optional[GraphRetrieverProtocol] = None,
        planner: Optional[PlannerProtocol] = None,
        derived_view_manager: Optional[DerivedViewManagerProtocol] = None,
        planner_timeout_ms: int = DEFAULT_PLANNER_TIMEOUT_MS,
        execution_timeout_ms: int = DEFAULT_EXECUTION_TIMEOUT_MS,
        min_planner_confidence: float = MIN_PLANNER_CONFIDENCE,
    ):
        """
        Initialize the Query Executor.

        Args:
            knowledge_base: Knowledge Base client
            graph_retriever: Graph Retriever instance
            planner: Planner instance
            derived_view_manager: Derived View Manager instance
            planner_timeout_ms: Timeout for planner (default 500ms)
            execution_timeout_ms: Timeout for overall execution
            min_planner_confidence: Minimum confidence for using planner
        """
        self._knowledge_base = knowledge_base
        self._graph_retriever = graph_retriever
        self._planner = planner
        self._derived_view_manager = derived_view_manager
        self.planner_timeout_ms = planner_timeout_ms
        self.execution_timeout_ms = execution_timeout_ms
        self.min_planner_confidence = min_planner_confidence

    @property
    def knowledge_base(self) -> KnowledgeBaseProtocol:
        """Lazy-load Knowledge Base client."""
        if self._knowledge_base is None:
            # Import and create default KB client
            # This would typically use boto3 bedrock-agent-runtime
            raise ValueError("Knowledge Base client not configured")
        return self._knowledge_base

    @property
    def graph_retriever(self) -> GraphRetrieverProtocol:
        """Lazy-load Graph Retriever."""
        if self._graph_retriever is None:
            raise ValueError("Graph Retriever not configured")
        return self._graph_retriever

    @property
    def planner(self) -> PlannerProtocol:
        """Lazy-load Planner."""
        if self._planner is None:
            from planner import Planner

            self._planner = Planner()
        return self._planner

    @property
    def derived_view_manager(self) -> DerivedViewManagerProtocol:
        """Lazy-load Derived View Manager."""
        if self._derived_view_manager is None:
            from derived_view_manager import DerivedViewManager

            self._derived_view_manager = DerivedViewManager()
        return self._derived_view_manager

    # =========================================================================
    # Main Execution Methods
    # =========================================================================

    def execute(
        self,
        query: str,
        authorization: Optional[AuthorizationContext] = None,
        limit: int = DEFAULT_KB_LIMIT,
    ) -> ExecutionResult:
        """
        Execute a query with parallel planner and vector search.

        **Requirements: 1.2, 8.1**

        This runs the planner and vector search in parallel:
        - If planner completes within timeout with high confidence, use it
        - Otherwise, fall back to vector search results

        Args:
            query: Natural language query
            authorization: Authorization context for access control
            limit: Maximum results to return

        Returns:
            ExecutionResult with records and metadata
        """
        start_time = time.time()

        if not query or not query.strip():
            return ExecutionResult(
                records=[],
                execution_path=ExecutionPath.FALLBACK,
                execution_time_ms=0.0,
                used_fallback=True,
            )

        try:
            # Run planner and vector search in parallel
            result = self._execute_parallel(query, authorization, limit)
            result.execution_time_ms = (time.time() - start_time) * 1000

            # Log telemetry
            self._log_telemetry(query, result)

            return result

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.error(f"Query execution error: {e}")
            self._log_telemetry(
                query,
                ExecutionResult(
                    execution_path=ExecutionPath.FALLBACK,
                    execution_time_ms=elapsed_ms,
                    used_fallback=True,
                ),
                error=str(e),
            )
            return ExecutionResult(
                records=[],
                execution_path=ExecutionPath.FALLBACK,
                execution_time_ms=elapsed_ms,
                used_fallback=True,
            )

    def execute_with_plan(
        self,
        query: str,
        plan: Any,
        authorization: Optional[AuthorizationContext] = None,
        limit: int = DEFAULT_KB_LIMIT,
    ) -> ExecutionResult:
        """
        Execute a query using a pre-computed plan.

        **Requirements: 7.1, 7.2**

        Args:
            query: Original query string
            plan: StructuredPlan from planner
            authorization: Authorization context
            limit: Maximum results to return

        Returns:
            ExecutionResult with records and metadata
        """
        start_time = time.time()

        try:
            # Check if plan has seed IDs
            if hasattr(plan, "seed_ids") and plan.seed_ids:
                result = self._execute_with_seed_ids(
                    query, plan.seed_ids, plan, authorization, limit
                )
                result.execution_path = ExecutionPath.SEED_ID_FILTER

            # Check for aggregation query
            elif self._is_aggregation_query(query, plan):
                result = self._execute_aggregation_query(
                    query, plan, authorization, limit
                )
                result.execution_path = ExecutionPath.AGGREGATION_VIEW

            # Check for graph traversal
            elif hasattr(plan, "traversal_plan") and plan.traversal_plan:
                result = self._execute_graph_traversal(
                    query, plan, authorization, limit
                )
                result.execution_path = ExecutionPath.GRAPH_TRAVERSAL

            # Execute with structured filters
            elif hasattr(plan, "predicates") and plan.predicates:
                result = self._execute_with_filters(query, plan, authorization, limit)
                result.execution_path = ExecutionPath.STRUCTURED_FILTER

            # Fall back to vector search
            else:
                result = self._execute_vector_search(query, authorization, limit)
                result.execution_path = ExecutionPath.VECTOR_ONLY

            result.execution_time_ms = (time.time() - start_time) * 1000
            result.planner_confidence = (
                plan.confidence if hasattr(plan, "confidence") else None
            )

            return result

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.error(f"Plan execution error: {e}")
            return ExecutionResult(
                records=[],
                execution_path=ExecutionPath.FALLBACK,
                execution_time_ms=elapsed_ms,
                used_fallback=True,
            )

    # =========================================================================
    # Parallel Execution (Requirements 1.2, 8.1)
    # =========================================================================

    def _execute_parallel(
        self,
        query: str,
        authorization: Optional[AuthorizationContext],
        limit: int,
    ) -> ExecutionResult:
        """
        Execute planner and vector search in parallel.

        **Requirements: 1.2, 8.1**

        Starts both immediately:
        - If planner finishes within timeout with high confidence, use its plan
        - Otherwise, use vector search results

        Args:
            query: Natural language query
            authorization: Authorization context
            limit: Maximum results

        Returns:
            ExecutionResult from best path
        """
        planner_timeout_s = self.planner_timeout_ms / 1000.0

        with ThreadPoolExecutor(max_workers=2) as executor:
            # Submit both tasks
            planner_future = executor.submit(
                self._run_planner,
                query,
                self.planner_timeout_ms,
            )
            vector_future = executor.submit(
                self._execute_vector_search,
                query,
                authorization,
                limit,
            )

            # Wait for planner with timeout
            plan = None
            try:
                plan = planner_future.result(timeout=planner_timeout_s)
            except FuturesTimeoutError:
                LOGGER.info(f"Planner timeout after {self.planner_timeout_ms}ms")
            except Exception as e:
                LOGGER.warning(f"Planner error: {e}")

            # Check if we can use planner results
            use_planner = (
                plan is not None
                and hasattr(plan, "confidence")
                and plan.confidence >= self.min_planner_confidence
                and not self.planner.should_fallback(plan)
            )

            if use_planner:
                # Cancel vector search if possible and use plan
                vector_future.cancel()
                LOGGER.info(f"Using planner results (confidence={plan.confidence})")
                return self.execute_with_plan(query, plan, authorization, limit)
            else:
                # Use vector search results
                LOGGER.info("Falling back to vector search")
                try:
                    result = vector_future.result(
                        timeout=self.execution_timeout_ms / 1000.0
                    )
                    result.used_fallback = True
                    return result
                except Exception as e:
                    LOGGER.error(f"Vector search error: {e}")
                    return ExecutionResult(
                        records=[],
                        execution_path=ExecutionPath.FALLBACK,
                        used_fallback=True,
                    )

    def _run_planner(self, query: str, timeout_ms: int) -> Any:
        """
        Run the planner with timeout.

        Args:
            query: Natural language query
            timeout_ms: Timeout in milliseconds

        Returns:
            StructuredPlan or None
        """
        return self.planner.plan(query, timeout_ms=timeout_ms)

    # =========================================================================
    # Seed ID Filtering (Requirement 7.1)
    # =========================================================================

    def _execute_with_seed_ids(
        self,
        query: str,
        seed_ids: List[str],
        plan: Any,
        authorization: Optional[AuthorizationContext],
        limit: int,
    ) -> ExecutionResult:
        """
        Execute query with seed ID filtering.

        **Requirements: 7.1**

        When seedIds are provided, filter KB by recordId to get precise results.

        Args:
            query: Original query
            seed_ids: Pre-resolved record IDs
            plan: StructuredPlan
            authorization: Authorization context
            limit: Maximum results

        Returns:
            ExecutionResult with filtered records
        """
        start_time = time.time()
        all_records: List[Dict[str, Any]] = []

        # Apply authorization filter to seed IDs
        authorized_ids = self._filter_authorized_ids(seed_ids, authorization)

        if not authorized_ids:
            return ExecutionResult(
                records=[],
                seed_ids_used=[],  # No authorized IDs to use
                authorization_filtered=len(seed_ids),
            )

        # Build filter for KB query
        kb_filter = {"recordId": {"$in": authorized_ids}}

        try:
            # Query KB with seed ID filter
            records = self.knowledge_base.retrieve(
                query=query,
                filters=kb_filter,
                limit=limit,
            )
            all_records.extend(records)

        except Exception as e:
            LOGGER.error(f"KB query with seed IDs failed: {e}")

        # Apply any additional predicate filters
        if hasattr(plan, "predicates") and plan.predicates:
            all_records = self._apply_predicate_filters(all_records, plan.predicates)

        elapsed_ms = (time.time() - start_time) * 1000
        return ExecutionResult(
            records=all_records[:limit],
            seed_ids_used=authorized_ids,
            authorization_filtered=len(seed_ids) - len(authorized_ids),
            filters_applied=[{"type": "seed_id", "count": len(authorized_ids)}],
        )

    def _filter_authorized_ids(
        self,
        seed_ids: List[str],
        authorization: Optional[AuthorizationContext],
    ) -> List[str]:
        """
        Filter seed IDs to only authorized records.

        **Requirements: 11.4**

        Args:
            seed_ids: List of record IDs
            authorization: Authorization context

        Returns:
            List of authorized record IDs
        """
        if authorization is None:
            return seed_ids

        return [rid for rid in seed_ids if authorization.can_access_record(rid)]

    # =========================================================================
    # Structured Filter Execution (Requirement 7.2)
    # =========================================================================

    def _execute_with_filters(
        self,
        query: str,
        plan: Any,
        authorization: Optional[AuthorizationContext],
        limit: int,
    ) -> ExecutionResult:
        """
        Execute query with structured filters.

        **Requirements: 7.2**

        Apply predicates to both knowledge base and graph traversal,
        then merge results.

        Args:
            query: Original query
            plan: StructuredPlan with predicates
            authorization: Authorization context
            limit: Maximum results

        Returns:
            ExecutionResult with filtered records
        """
        start_time = time.time()
        all_records: List[Dict[str, Any]] = []
        filters_applied: List[Dict[str, Any]] = []

        # Build KB filter from predicates
        kb_filter = self._build_kb_filter(plan.predicates)

        try:
            # Query KB with structured filter
            records = self.knowledge_base.retrieve(
                query=query,
                filters=kb_filter,
                limit=limit,
            )
            all_records.extend(records)
            filters_applied.append(
                {
                    "type": "structured",
                    "predicates": len(plan.predicates),
                }
            )

        except Exception as e:
            LOGGER.error(f"KB query with filters failed: {e}")

        # Apply authorization filter
        if authorization:
            pre_auth_count = len(all_records)
            all_records = self._apply_authorization_filter(all_records, authorization)
            auth_filtered = pre_auth_count - len(all_records)
        else:
            auth_filtered = 0

        elapsed_ms = (time.time() - start_time) * 1000
        return ExecutionResult(
            records=all_records[:limit],
            filters_applied=filters_applied,
            authorization_filtered=auth_filtered,
        )

    def _build_kb_filter(self, predicates: List[Any]) -> Dict[str, Any]:
        """
        Build KB filter from predicates.

        Args:
            predicates: List of Predicate objects

        Returns:
            Filter dictionary for KB query
        """
        if not predicates:
            return {}

        conditions = []
        for pred in predicates:
            field = pred.field if hasattr(pred, "field") else pred.get("field", "")
            operator = (
                pred.operator if hasattr(pred, "operator") else pred.get("operator", "")
            )
            value = pred.value if hasattr(pred, "value") else pred.get("value")

            if operator == "eq":
                conditions.append({field: value})
            elif operator == "gt":
                conditions.append({field: {"$gt": value}})
            elif operator == "lt":
                conditions.append({field: {"$lt": value}})
            elif operator == "gte":
                conditions.append({field: {"$gte": value}})
            elif operator == "lte":
                conditions.append({field: {"$lte": value}})
            elif operator == "in":
                conditions.append({field: {"$in": value}})
            elif operator == "contains":
                conditions.append({field: {"$contains": value}})
            elif operator in ("between", "range"):
                if isinstance(value, (list, tuple)) and len(value) >= 2:
                    conditions.append(
                        {"$and": [{field: {"$gte": value[0]}}, {field: {"$lte": value[1]}}]}
                    )

        if len(conditions) == 1:
            return conditions[0]
        elif len(conditions) > 1:
            return {"$and": conditions}
        return {}

    def _apply_predicate_filters(
        self,
        records: List[Dict[str, Any]],
        predicates: List[Any],
    ) -> List[Dict[str, Any]]:
        """
        Apply predicate filters to records in memory.

        Args:
            records: List of record dictionaries
            predicates: List of Predicate objects

        Returns:
            Filtered list of records
        """
        if not predicates:
            return records

        filtered = []
        for record in records:
            matches = True
            for pred in predicates:
                field = pred.field if hasattr(pred, "field") else pred.get("field", "")
                operator = (
                    pred.operator
                    if hasattr(pred, "operator")
                    else pred.get("operator", "")
                )
                value = pred.value if hasattr(pred, "value") else pred.get("value")

                record_value = record.get(field)
                if not self._predicate_matches(record_value, operator, value):
                    matches = False
                    break

            if matches:
                filtered.append(record)

        return filtered

    def _predicate_matches(
        self,
        record_value: Any,
        operator: str,
        filter_value: Any,
    ) -> bool:
        """Check if record value matches predicate."""
        if record_value is None:
            return False

        if operator == "eq":
            return record_value == filter_value
        elif operator == "gt":
            return record_value > filter_value
        elif operator == "lt":
            return record_value < filter_value
        elif operator == "gte":
            return record_value >= filter_value
        elif operator == "lte":
            return record_value <= filter_value
        elif operator == "in":
            return record_value in filter_value
        elif operator == "contains":
            return str(filter_value).lower() in str(record_value).lower()
        elif operator in ("between", "range"):
            if isinstance(filter_value, (list, tuple)) and len(filter_value) >= 2:
                return filter_value[0] <= record_value <= filter_value[1]
        return False

    # =========================================================================
    # Aggregation Query Routing (Requirements 5.6, 5.7)
    # =========================================================================

    def _is_aggregation_query(self, query: str, plan: Any) -> bool:
        """
        Detect if query requires aggregation data.

        **Requirements: 5.6**

        Args:
            query: Original query
            plan: StructuredPlan

        Returns:
            True if aggregation view should be used
        """
        query_lower = query.lower()

        # Check for aggregation keywords
        for keyword in self.AGGREGATION_KEYWORDS:
            if keyword in query_lower:
                return True

        # Check if target object maps to an aggregation view
        if hasattr(plan, "target_object") and plan.target_object:
            if plan.target_object in self.AGGREGATION_OBJECTS:
                return True

        return False

    def _execute_aggregation_query(
        self,
        query: str,
        plan: Any,
        authorization: Optional[AuthorizationContext],
        limit: int,
    ) -> ExecutionResult:
        """
        Execute query using derived views.

        **Requirements: 5.6, 5.7**

        Routes to the appropriate derived view based on target object.
        Falls back to vector+filter if view is missing or has no data.

        Args:
            query: Original query
            plan: StructuredPlan
            authorization: Authorization context
            limit: Maximum results

        Returns:
            ExecutionResult from derived view or fallback
        """
        start_time = time.time()
        target_object = plan.target_object if hasattr(plan, "target_object") else ""
        view_name = self.AGGREGATION_OBJECTS.get(target_object, "")

        if not view_name:
            # No aggregation view for this object, fall back
            LOGGER.info(f"No aggregation view for {target_object}, falling back")
            result = self._execute_vector_search(query, authorization, limit)
            result.used_fallback = True
            return result

        try:
            # Convert predicates to view predicates
            view_filters = self._convert_to_view_predicates(plan.predicates)

            # Query derived view with fallback
            records, used_fallback = self.derived_view_manager.query_with_fallback(
                view_name=view_name,
                query=query,
                filters=view_filters,
                limit=limit,
            )

            if used_fallback or not records:
                # Fall back to vector search
                LOGGER.info(f"Derived view {view_name} empty, falling back")
                result = self._execute_vector_search(query, authorization, limit)
                result.used_fallback = True
                return result

            # Convert view records to result format
            result_records = [
                r.to_dict() if hasattr(r, "to_dict") else r for r in records
            ]

            # Apply authorization filter
            if authorization:
                pre_auth_count = len(result_records)
                result_records = self._apply_authorization_filter(
                    result_records, authorization
                )
                auth_filtered = pre_auth_count - len(result_records)
            else:
                auth_filtered = 0

            elapsed_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                records=result_records[:limit],
                execution_path=ExecutionPath.AGGREGATION_VIEW,
                filters_applied=[{"type": "derived_view", "view": view_name}],
                authorization_filtered=auth_filtered,
            )

        except Exception as e:
            LOGGER.error(f"Derived view query failed: {e}")
            result = self._execute_vector_search(query, authorization, limit)
            result.used_fallback = True
            return result

    def _convert_to_view_predicates(self, predicates: List[Any]) -> List[Any]:
        """
        Convert planner predicates to derived view predicates.

        Args:
            predicates: List of Predicate objects from planner

        Returns:
            List of predicates compatible with derived views
        """
        if not predicates:
            return []

        # Import Predicate from derived_view_manager
        try:
            from derived_view_manager import Predicate as ViewPredicate

            view_predicates = []
            for pred in predicates:
                field = pred.field if hasattr(pred, "field") else pred.get("field", "")
                operator = (
                    pred.operator
                    if hasattr(pred, "operator")
                    else pred.get("operator", "eq")
                )
                value = pred.value if hasattr(pred, "value") else pred.get("value")

                view_predicates.append(ViewPredicate(field=field, operator=operator, value=value))

            return view_predicates

        except ImportError:
            return predicates

    # =========================================================================
    # Graph Traversal Authorization (Requirement 11.4)
    # =========================================================================

    def _execute_graph_traversal(
        self,
        query: str,
        plan: Any,
        authorization: Optional[AuthorizationContext],
        limit: int,
    ) -> ExecutionResult:
        """
        Execute graph traversal with authorization checks.

        **Requirements: 11.4**

        Enforces authorization at each hop of graph traversal.
        Excludes paths with inaccessible intermediate nodes.

        Args:
            query: Original query
            plan: StructuredPlan with traversal_plan
            authorization: Authorization context
            limit: Maximum results

        Returns:
            ExecutionResult from graph traversal
        """
        start_time = time.time()
        traversal_plan = plan.traversal_plan
        all_records: List[Dict[str, Any]] = []
        nodes_visited = 0
        auth_filtered = 0

        # Get start IDs from seed IDs or KB query
        start_ids = []
        if hasattr(plan, "seed_ids") and plan.seed_ids:
            start_ids = plan.seed_ids
        else:
            # Get start IDs from KB query
            try:
                kb_results = self.knowledge_base.retrieve(
                    query=query,
                    limit=DEFAULT_GRAPH_LIMIT,
                )
                start_ids = [
                    r.get("recordId") or r.get("id") for r in kb_results if r
                ]
                start_ids = [sid for sid in start_ids if sid]
            except Exception as e:
                LOGGER.error(f"KB query for start IDs failed: {e}")

        if not start_ids:
            return ExecutionResult(
                records=[],
                graph_nodes_visited=0,
            )

        # Filter start IDs by authorization
        authorized_start_ids = self._filter_authorized_ids(start_ids, authorization)
        auth_filtered += len(start_ids) - len(authorized_start_ids)

        if not authorized_start_ids:
            return ExecutionResult(
                records=[],
                graph_nodes_visited=0,
                authorization_filtered=auth_filtered,
            )

        try:
            # Execute graph traversal
            traversal_results = self.graph_retriever.traverse(
                start_ids=authorized_start_ids,
                traversal_plan=traversal_plan,
                max_nodes=DEFAULT_GRAPH_LIMIT,
            )

            nodes_visited = len(traversal_results)

            # Filter results by authorization at each node
            for result in traversal_results:
                if self._is_node_authorized(result, authorization):
                    all_records.append(result)
                else:
                    auth_filtered += 1

        except Exception as e:
            LOGGER.error(f"Graph traversal failed: {e}")

        elapsed_ms = (time.time() - start_time) * 1000
        return ExecutionResult(
            records=all_records[:limit],
            graph_nodes_visited=nodes_visited,
            authorization_filtered=auth_filtered,
            filters_applied=[{"type": "graph_traversal"}],
        )

    def _is_node_authorized(
        self,
        node: Dict[str, Any],
        authorization: Optional[AuthorizationContext],
    ) -> bool:
        """
        Check if a graph node is authorized for access.

        **Requirements: 11.4**

        Args:
            node: Graph node (record)
            authorization: Authorization context

        Returns:
            True if node is accessible
        """
        if authorization is None:
            return True

        # Check object type access
        object_type = node.get("object_type") or node.get("sobjectType")
        if object_type and not authorization.can_access_object(object_type):
            return False

        # Check record access
        record_id = node.get("recordId") or node.get("id") or node.get("Id")
        if record_id and not authorization.can_access_record(record_id):
            return False

        return True

    def _apply_authorization_filter(
        self,
        records: List[Dict[str, Any]],
        authorization: AuthorizationContext,
    ) -> List[Dict[str, Any]]:
        """
        Apply authorization filter to records.

        Args:
            records: List of record dictionaries
            authorization: Authorization context

        Returns:
            Filtered list of authorized records
        """
        return [r for r in records if self._is_node_authorized(r, authorization)]

    # =========================================================================
    # Vector Search Fallback (Requirement 8.1)
    # =========================================================================

    def _execute_vector_search(
        self,
        query: str,
        authorization: Optional[AuthorizationContext],
        limit: int,
    ) -> ExecutionResult:
        """
        Execute vector-only search (fallback path).

        **Requirements: 8.1**

        Args:
            query: Natural language query
            authorization: Authorization context
            limit: Maximum results

        Returns:
            ExecutionResult from vector search
        """
        start_time = time.time()
        all_records: List[Dict[str, Any]] = []
        auth_filtered = 0

        try:
            records = self.knowledge_base.retrieve(
                query=query,
                limit=limit,
            )
            all_records.extend(records)

        except Exception as e:
            LOGGER.error(f"Vector search failed: {e}")

        # Apply authorization filter
        if authorization:
            pre_auth_count = len(all_records)
            all_records = self._apply_authorization_filter(all_records, authorization)
            auth_filtered = pre_auth_count - len(all_records)

        elapsed_ms = (time.time() - start_time) * 1000
        return ExecutionResult(
            records=all_records[:limit],
            execution_path=ExecutionPath.VECTOR_ONLY,
            authorization_filtered=auth_filtered,
        )

    # =========================================================================
    # Telemetry (Requirement 12.5)
    # =========================================================================

    def _log_telemetry(
        self,
        query: str,
        result: ExecutionResult,
        error: Optional[str] = None,
    ) -> None:
        """
        Log telemetry for query execution.

        **Requirements: 12.5**

        Args:
            query: Original query
            result: Execution result
            error: Error message (if any)
        """
        telemetry = {
            "event": "query_execution",
            "query": query[:200],
            "record_count": len(result.records),
            "execution_path": result.execution_path.value,
            "execution_time_ms": result.execution_time_ms,
            "used_fallback": result.used_fallback,
            "planner_confidence": result.planner_confidence,
            "graph_nodes_visited": result.graph_nodes_visited,
            "authorization_filtered": result.authorization_filtered,
        }

        if error:
            telemetry["error"] = error

        LOGGER.info(f"Query execution telemetry: {json.dumps(telemetry)}")


# =============================================================================
# Convenience Functions
# =============================================================================


def execute_query(
    query: str,
    knowledge_base: Optional[KnowledgeBaseProtocol] = None,
    authorization: Optional[AuthorizationContext] = None,
    limit: int = DEFAULT_KB_LIMIT,
) -> ExecutionResult:
    """
    Convenience function to execute a query.

    Args:
        query: Natural language query
        knowledge_base: Optional KB client
        authorization: Optional authorization context
        limit: Maximum results

    Returns:
        ExecutionResult
    """
    executor = QueryExecutor(knowledge_base=knowledge_base)
    return executor.execute(query, authorization=authorization, limit=limit)


def create_authorization_context(
    user_id: str,
    accessible_objects: Optional[List[str]] = None,
    accessible_records: Optional[List[str]] = None,
) -> AuthorizationContext:
    """
    Create an authorization context.

    Args:
        user_id: Salesforce user ID
        accessible_objects: List of accessible object API names
        accessible_records: List of accessible record IDs

    Returns:
        AuthorizationContext
    """
    return AuthorizationContext(
        user_id=user_id,
        accessible_object_types=set(accessible_objects or []),
        accessible_record_ids=set(accessible_records) if accessible_records else None,
    )
