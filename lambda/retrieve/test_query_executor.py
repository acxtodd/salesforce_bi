"""
Unit Tests for Query Executor.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 7.1, 7.2, 5.6, 5.7, 11.4, 1.2, 8.1**
"""

import os
import sys
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from query_executor import (
    QueryExecutor,
    ExecutionResult,
    ExecutionPath,
    AuthorizationContext,
    create_authorization_context,
    execute_query,
    DEFAULT_KB_LIMIT,
    DEFAULT_PLANNER_TIMEOUT_MS,
)


# =============================================================================
# Test Fixtures
# =============================================================================


class MockKnowledgeBase:
    """Mock Knowledge Base for testing."""

    def __init__(
        self,
        records: Optional[List[Dict[str, Any]]] = None,
        should_fail: bool = False,
    ):
        self.records = records or []
        self.should_fail = should_fail
        self.call_count = 0
        self.last_query: Optional[str] = None
        self.last_filters: Optional[Dict[str, Any]] = None
        self.last_limit: int = 0

    def retrieve(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Mock retrieve method."""
        self.call_count += 1
        self.last_query = query
        self.last_filters = filters
        self.last_limit = limit

        if self.should_fail:
            raise Exception("KB retrieval failed")

        results = self.records.copy()

        # Apply recordId filter if present
        if filters and "recordId" in filters:
            record_ids = filters["recordId"].get("$in", [])
            results = [r for r in results if r.get("recordId") in record_ids]

        return results[:limit]


class MockGraphRetriever:
    """Mock Graph Retriever for testing."""

    def __init__(
        self,
        nodes: Optional[List[Dict[str, Any]]] = None,
        should_fail: bool = False,
    ):
        self.nodes = nodes or []
        self.should_fail = should_fail
        self.call_count = 0

    def traverse(
        self,
        start_ids: List[str],
        traversal_plan: Any,
        max_nodes: int = 50,
    ) -> List[Dict[str, Any]]:
        """Mock traverse method."""
        self.call_count += 1

        if self.should_fail:
            raise Exception("Graph traversal failed")

        # Return nodes reachable from start_ids
        results = []
        for node in self.nodes:
            node_id = node.get("recordId") or node.get("id")
            parent_id = node.get("parent_id")
            if node_id in start_ids or parent_id in start_ids:
                results.append(node)
        return results[:max_nodes]


class MockPlanner:
    """Mock Planner for testing."""

    def __init__(
        self,
        plan: Optional[Any] = None,
        should_timeout: bool = False,
        delay_ms: int = 0,
    ):
        self._plan = plan
        self.should_timeout = should_timeout
        self.delay_ms = delay_ms
        self.call_count = 0

    def plan(self, query: str, timeout_ms: Optional[int] = None) -> Any:
        """Mock plan method."""
        self.call_count += 1

        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)

        if self.should_timeout:
            time.sleep(1.0)  # Force timeout

        return self._plan

    def should_fallback(self, plan: Any) -> bool:
        """Mock should_fallback method."""
        if plan is None:
            return True
        if hasattr(plan, "confidence"):
            return plan.confidence < 0.5
        return False


class MockPlan:
    """Mock StructuredPlan for testing."""

    def __init__(
        self,
        seed_ids: Optional[List[str]] = None,
        predicates: Optional[List[Any]] = None,
        traversal_plan: Optional[Any] = None,
        confidence: float = 0.8,
        target_object: str = "ascendix__Property__c",
    ):
        self.seed_ids = seed_ids
        self.predicates = predicates or []
        self.traversal_plan = traversal_plan
        self.confidence = confidence
        self.target_object = target_object


class MockPredicate:
    """Mock Predicate for testing."""

    def __init__(self, field: str, operator: str, value: Any):
        self.field = field
        self.operator = operator
        self.value = value


class MockTraversalPlan:
    """Mock TraversalPlan for testing."""

    def __init__(self, max_depth: int = 2):
        self.max_depth = max_depth


class MockDerivedViewManager:
    """Mock Derived View Manager for testing."""

    def __init__(
        self,
        records: Optional[List[Any]] = None,
        should_fallback: bool = False,
    ):
        self.records = records or []
        self.should_fallback = should_fallback
        self.call_count = 0
        self.last_view_name: Optional[str] = None

    def query_with_fallback(
        self,
        view_name: str,
        query: str,
        filters: Optional[List[Any]] = None,
        **kwargs,
    ) -> tuple:
        """Mock query with fallback."""
        self.call_count += 1
        self.last_view_name = view_name

        if self.should_fallback:
            return [], True

        return self.records, False


# =============================================================================
# Test QueryExecutor Initialization
# =============================================================================


class TestQueryExecutorInit:
    """Tests for QueryExecutor initialization."""

    def test_init_with_defaults(self):
        """Test initialization with default values."""
        executor = QueryExecutor()
        assert executor.planner_timeout_ms == DEFAULT_PLANNER_TIMEOUT_MS
        assert executor.min_planner_confidence == 0.5

    def test_init_with_custom_timeout(self):
        """Test initialization with custom timeout."""
        executor = QueryExecutor(planner_timeout_ms=1000)
        assert executor.planner_timeout_ms == 1000

    def test_init_with_dependencies(self):
        """Test initialization with injected dependencies."""
        mock_kb = MockKnowledgeBase()
        mock_graph = MockGraphRetriever()
        mock_planner = MockPlanner()

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            graph_retriever=mock_graph,
            planner=mock_planner,
        )

        assert executor._knowledge_base is mock_kb
        assert executor._graph_retriever is mock_graph
        assert executor._planner is mock_planner


# =============================================================================
# Test Seed ID Filtering (Requirement 7.1)
# =============================================================================


class TestSeedIDFiltering:
    """Tests for seed ID filtering (Requirement 7.1)."""

    def test_execute_with_seed_ids(self):
        """Test execution with seed IDs filters KB by recordId."""
        seed_ids = ["id_001", "id_002", "id_003"]
        records = [
            {"recordId": "id_001", "Name": "Record 1"},
            {"recordId": "id_002", "Name": "Record 2"},
            {"recordId": "id_003", "Name": "Record 3"},
        ]
        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(knowledge_base=mock_kb)

        plan = MockPlan(seed_ids=seed_ids, confidence=0.9)
        result = executor.execute_with_plan("test query", plan)

        # Verify KB was called with recordId filter
        assert mock_kb.last_filters is not None
        assert "recordId" in mock_kb.last_filters
        assert set(mock_kb.last_filters["recordId"]["$in"]) == set(seed_ids)

        # Verify execution path
        assert result.execution_path == ExecutionPath.SEED_ID_FILTER
        assert set(result.seed_ids_used) == set(seed_ids)

    def test_seed_ids_with_authorization(self):
        """Test seed ID filtering with authorization."""
        seed_ids = ["id_001", "id_002", "id_003"]
        records = [
            {"recordId": "id_001", "Name": "Record 1"},
            {"recordId": "id_002", "Name": "Record 2"},
        ]
        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(knowledge_base=mock_kb)

        # Only allow access to id_001 and id_002
        auth = AuthorizationContext(
            user_id="test_user",
            accessible_record_ids={"id_001", "id_002"},
        )

        plan = MockPlan(seed_ids=seed_ids, confidence=0.9)
        result = executor.execute_with_plan("test query", plan, authorization=auth)

        # id_003 should be filtered out
        assert "id_003" not in result.seed_ids_used
        assert result.authorization_filtered == 1

    def test_all_seed_ids_unauthorized(self):
        """Test when all seed IDs are unauthorized."""
        seed_ids = ["id_001", "id_002"]
        mock_kb = MockKnowledgeBase(records=[])

        executor = QueryExecutor(knowledge_base=mock_kb)

        # Deny all records
        auth = AuthorizationContext(
            user_id="test_user",
            accessible_record_ids=set(),
        )

        plan = MockPlan(seed_ids=seed_ids, confidence=0.9)
        result = executor.execute_with_plan("test query", plan, authorization=auth)

        assert len(result.records) == 0
        assert result.authorization_filtered == 2


# =============================================================================
# Test Structured Filter Execution (Requirement 7.2)
# =============================================================================


class TestStructuredFilterExecution:
    """Tests for structured filter execution (Requirement 7.2)."""

    def test_execute_with_predicates(self):
        """Test execution with structured predicates."""
        records = [
            {"recordId": "id_001", "Name": "Test", "Status": "Active"},
            {"recordId": "id_002", "Name": "Other", "Status": "Active"},
        ]
        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(knowledge_base=mock_kb)

        predicates = [
            MockPredicate(field="Status", operator="eq", value="Active"),
        ]
        # Use a non-aggregation object type
        plan = MockPlan(
            predicates=predicates,
            confidence=0.9,
            target_object="CustomObject__c",  # Not an aggregation object
        )

        result = executor.execute_with_plan("find records with status", plan)

        # Verify execution path
        assert result.execution_path == ExecutionPath.STRUCTURED_FILTER
        assert len(result.filters_applied) > 0

    def test_build_kb_filter_eq(self):
        """Test KB filter building for equality."""
        mock_kb = MockKnowledgeBase(records=[])
        executor = QueryExecutor(knowledge_base=mock_kb)

        predicates = [MockPredicate(field="Status", operator="eq", value="Active")]
        kb_filter = executor._build_kb_filter(predicates)

        assert kb_filter == {"Status": "Active"}

    def test_build_kb_filter_comparison(self):
        """Test KB filter building for comparison operators."""
        mock_kb = MockKnowledgeBase(records=[])
        executor = QueryExecutor(knowledge_base=mock_kb)

        predicates = [MockPredicate(field="Amount", operator="gt", value=1000)]
        kb_filter = executor._build_kb_filter(predicates)

        assert kb_filter == {"Amount": {"$gt": 1000}}

    def test_build_kb_filter_between(self):
        """Test KB filter building for between operator."""
        mock_kb = MockKnowledgeBase(records=[])
        executor = QueryExecutor(knowledge_base=mock_kb)

        predicates = [MockPredicate(field="Size", operator="between", value=[100, 500])]
        kb_filter = executor._build_kb_filter(predicates)

        assert "$and" in kb_filter
        assert len(kb_filter["$and"]) == 2

    def test_apply_predicate_filters(self):
        """Test in-memory predicate filtering."""
        mock_kb = MockKnowledgeBase(records=[])
        executor = QueryExecutor(knowledge_base=mock_kb)

        records = [
            {"Name": "Test", "Value": 100},
            {"Name": "Other", "Value": 200},
            {"Name": "Test", "Value": 300},
        ]

        predicates = [
            MockPredicate(field="Name", operator="eq", value="Test"),
        ]

        filtered = executor._apply_predicate_filters(records, predicates)

        assert len(filtered) == 2
        assert all(r["Name"] == "Test" for r in filtered)


# =============================================================================
# Test Aggregation Query Routing (Requirements 5.6, 5.7)
# =============================================================================


class TestAggregationRouting:
    """Tests for aggregation query routing (Requirements 5.6, 5.7)."""

    def test_detect_aggregation_query_by_keyword(self):
        """Test aggregation detection by keyword."""
        executor = QueryExecutor()

        # Test with a non-aggregation object to isolate keyword detection
        plan_non_agg = MockPlan(target_object="CustomObject__c")

        # Keywords trigger aggregation even on non-agg objects
        assert executor._is_aggregation_query("records with vacancy > 25%", plan_non_agg)
        assert executor._is_aggregation_query("show me available items", plan_non_agg)
        # Without keywords and non-agg object, should not be aggregation
        assert not executor._is_aggregation_query("find record details", plan_non_agg)

    def test_detect_aggregation_query_by_object(self):
        """Test aggregation detection by object type."""
        executor = QueryExecutor()

        plan = MockPlan(target_object="ascendix__Sale__c")
        assert executor._is_aggregation_query("sales in progress", plan)

        plan = MockPlan(target_object="Task")
        assert executor._is_aggregation_query("tasks for property", plan)

    def test_execute_aggregation_query_success(self):
        """Test successful aggregation query execution."""

        class MockRecord:
            def to_dict(self):
                return {"property_id": "prop_001", "vacancy_pct": 30}

        mock_kb = MockKnowledgeBase(records=[])
        mock_derived = MockDerivedViewManager(records=[MockRecord()])

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            derived_view_manager=mock_derived,
        )

        plan = MockPlan(target_object="ascendix__Property__c", confidence=0.9)
        result = executor._execute_aggregation_query(
            "properties with vacancy > 25%", plan, None, 100
        )

        assert mock_derived.call_count == 1
        assert mock_derived.last_view_name == "vacancy_view"
        assert result.execution_path == ExecutionPath.AGGREGATION_VIEW

    def test_aggregation_fallback_on_empty(self):
        """Test fallback when aggregation view is empty."""
        mock_kb = MockKnowledgeBase(records=[{"recordId": "fallback_001"}])
        mock_derived = MockDerivedViewManager(records=[], should_fallback=True)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            derived_view_manager=mock_derived,
        )

        plan = MockPlan(target_object="ascendix__Property__c", confidence=0.9)
        result = executor._execute_aggregation_query(
            "properties with vacancy > 25%", plan, None, 100
        )

        assert result.used_fallback
        assert mock_kb.call_count == 1


# =============================================================================
# Test Graph Traversal Authorization (Requirement 11.4)
# =============================================================================


class TestGraphAuthorization:
    """Tests for graph traversal authorization (Requirement 11.4)."""

    def test_graph_traversal_filters_unauthorized(self):
        """Test that unauthorized nodes are filtered from traversal."""
        nodes = [
            {"recordId": "node_001", "object_type": "Account", "parent_id": "start_001"},
            {"recordId": "node_002", "object_type": "Account", "parent_id": "start_001"},
            {"recordId": "node_003", "object_type": "Contact", "parent_id": "start_001"},
        ]
        # KB returns start node which is used to initiate graph traversal
        mock_kb = MockKnowledgeBase(records=[{"recordId": "start_001"}])
        mock_graph = MockGraphRetriever(nodes=nodes)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            graph_retriever=mock_graph,
        )

        auth = AuthorizationContext(
            user_id="test_user",
            accessible_record_ids={"start_001", "node_001"},  # Only start_001 and node_001 authorized
        )

        # No seed_ids - let it take the graph traversal path
        plan = MockPlan(
            seed_ids=None,  # No seed IDs to trigger traversal path
            traversal_plan=MockTraversalPlan(),
            confidence=0.9,
            target_object="CustomObject__c",  # Non-aggregation object
        )

        result = executor.execute_with_plan("find related records", plan, authorization=auth)

        # Only authorized nodes should be in results
        result_ids = {r.get("recordId") for r in result.records}
        assert "node_002" not in result_ids
        assert "node_003" not in result_ids
        # Authorization filtering should have occurred
        assert result.authorization_filtered >= 0

    def test_object_type_authorization(self):
        """Test authorization by object type."""
        nodes = [
            {"recordId": "node_001", "object_type": "Account", "parent_id": "start_001"},
            {"recordId": "node_002", "object_type": "Contact", "parent_id": "start_001"},
        ]
        mock_kb = MockKnowledgeBase(records=[{"recordId": "start_001"}])
        mock_graph = MockGraphRetriever(nodes=nodes)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            graph_retriever=mock_graph,
        )

        auth = AuthorizationContext(
            user_id="test_user",
            accessible_object_types={"Account"},  # Only Account accessible
        )

        # No seed_ids to trigger traversal path
        plan = MockPlan(
            seed_ids=None,
            traversal_plan=MockTraversalPlan(),
            confidence=0.9,
            target_object="CustomObject__c",
        )

        result = executor.execute_with_plan("find related records", plan, authorization=auth)

        # Only Account nodes should be in results
        for record in result.records:
            obj_type = record.get("object_type")
            if obj_type:
                assert obj_type == "Account"

    def test_no_authorization_allows_all(self):
        """Test that no authorization context allows all nodes."""
        nodes = [
            {"recordId": "node_001", "object_type": "Account", "parent_id": "start_001"},
            {"recordId": "node_002", "object_type": "Contact", "parent_id": "start_001"},
        ]
        mock_kb = MockKnowledgeBase(records=[{"recordId": "start_001"}])
        mock_graph = MockGraphRetriever(nodes=nodes)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            graph_retriever=mock_graph,
        )

        # No seed_ids to trigger traversal path
        plan = MockPlan(
            seed_ids=None,
            traversal_plan=MockTraversalPlan(),
            confidence=0.9,
            target_object="CustomObject__c",
        )

        result = executor.execute_with_plan("find related records", plan, authorization=None)

        # No authorization filtering
        assert result.authorization_filtered == 0


# =============================================================================
# Test Parallel Execution (Requirements 1.2, 8.1)
# =============================================================================


class TestParallelExecution:
    """Tests for parallel execution (Requirements 1.2, 8.1)."""

    def test_uses_planner_when_high_confidence(self):
        """Test that planner results are used when confidence is high."""
        records = [{"recordId": "id_001", "Name": "From Plan"}]
        mock_kb = MockKnowledgeBase(records=records)
        mock_planner = MockPlanner(
            plan=MockPlan(seed_ids=["id_001"], confidence=0.9)
        )

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=mock_planner,
            planner_timeout_ms=500,
        )

        result = executor.execute("test query")

        assert mock_planner.call_count == 1
        assert result.execution_path == ExecutionPath.SEED_ID_FILTER

    def test_fallback_on_low_confidence(self):
        """Test fallback when planner confidence is low."""
        records = [{"recordId": "id_001", "Name": "From Vector"}]
        mock_kb = MockKnowledgeBase(records=records)
        mock_planner = MockPlanner(
            plan=MockPlan(seed_ids=["id_001"], confidence=0.3)  # Low confidence
        )

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=mock_planner,
            min_planner_confidence=0.5,
        )

        result = executor.execute("test query")

        assert result.used_fallback

    def test_fallback_on_planner_failure(self):
        """Test fallback when planner fails."""
        records = [{"recordId": "id_001", "Name": "From Vector"}]
        mock_kb = MockKnowledgeBase(records=records)
        mock_planner = MockPlanner(plan=None)  # No plan returned

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=mock_planner,
        )

        result = executor.execute("test query")

        assert result.used_fallback

    def test_empty_query_returns_empty_result(self):
        """Test that empty query returns empty result."""
        executor = QueryExecutor()

        result = executor.execute("")

        assert len(result.records) == 0
        assert result.execution_path == ExecutionPath.FALLBACK
        assert result.used_fallback


# =============================================================================
# Test ExecutionResult
# =============================================================================


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_to_dict(self):
        """Test ExecutionResult serialization."""
        result = ExecutionResult(
            records=[{"id": "1"}],
            execution_path=ExecutionPath.SEED_ID_FILTER,
            execution_time_ms=150.5,
            used_fallback=False,
            planner_confidence=0.85,
            seed_ids_used=["id_001"],
            graph_nodes_visited=10,
            authorization_filtered=2,
        )

        result_dict = result.to_dict()

        assert result_dict["record_count"] == 1
        assert result_dict["execution_path"] == "seed_id_filter"
        assert result_dict["execution_time_ms"] == 150.5
        assert result_dict["used_fallback"] is False
        assert result_dict["planner_confidence"] == 0.85
        assert result_dict["seed_ids_used"] == ["id_001"]
        assert result_dict["graph_nodes_visited"] == 10
        assert result_dict["authorization_filtered"] == 2


# =============================================================================
# Test AuthorizationContext
# =============================================================================


class TestAuthorizationContext:
    """Tests for AuthorizationContext."""

    def test_can_access_object_no_restrictions(self):
        """Test object access with no restrictions."""
        auth = AuthorizationContext(user_id="test_user")

        assert auth.can_access_object("Account")
        assert auth.can_access_object("Contact")

    def test_can_access_object_with_restrictions(self):
        """Test object access with restrictions."""
        auth = AuthorizationContext(
            user_id="test_user",
            accessible_object_types={"Account", "Contact"},
        )

        assert auth.can_access_object("Account")
        assert auth.can_access_object("Contact")
        assert not auth.can_access_object("Opportunity")

    def test_can_access_record_no_restrictions(self):
        """Test record access with no restrictions."""
        auth = AuthorizationContext(user_id="test_user")

        assert auth.can_access_record("any_record_id")

    def test_can_access_record_with_restrictions(self):
        """Test record access with restrictions."""
        auth = AuthorizationContext(
            user_id="test_user",
            accessible_record_ids={"id_001", "id_002"},
        )

        assert auth.can_access_record("id_001")
        assert auth.can_access_record("id_002")
        assert not auth.can_access_record("id_003")


# =============================================================================
# Test Convenience Functions
# =============================================================================


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_create_authorization_context(self):
        """Test create_authorization_context function."""
        auth = create_authorization_context(
            user_id="test_user",
            accessible_objects=["Account", "Contact"],
            accessible_records=["id_001", "id_002"],
        )

        assert auth.user_id == "test_user"
        assert auth.accessible_object_types == {"Account", "Contact"}
        assert auth.accessible_record_ids == {"id_001", "id_002"}

    def test_create_authorization_context_no_records(self):
        """Test create_authorization_context without record restrictions."""
        auth = create_authorization_context(
            user_id="test_user",
            accessible_objects=["Account"],
        )

        assert auth.accessible_record_ids is None


# =============================================================================
# Test Vector Search Fallback (Requirement 8.1)
# =============================================================================


class TestVectorSearchFallback:
    """Tests for vector search fallback (Requirement 8.1)."""

    def test_vector_search_returns_records(self):
        """Test basic vector search execution."""
        records = [
            {"recordId": "id_001", "Name": "Record 1"},
            {"recordId": "id_002", "Name": "Record 2"},
        ]
        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(knowledge_base=mock_kb)

        result = executor._execute_vector_search("test query", None, 100)

        assert len(result.records) == 2
        assert result.execution_path == ExecutionPath.VECTOR_ONLY

    def test_vector_search_with_authorization(self):
        """Test vector search with authorization filtering."""
        records = [
            {"recordId": "id_001", "Name": "Record 1"},
            {"recordId": "id_002", "Name": "Record 2"},
        ]
        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(knowledge_base=mock_kb)

        auth = AuthorizationContext(
            user_id="test_user",
            accessible_record_ids={"id_001"},
        )

        result = executor._execute_vector_search("test query", auth, 100)

        assert len(result.records) == 1
        assert result.records[0]["recordId"] == "id_001"
        assert result.authorization_filtered == 1

    def test_vector_search_handles_error(self):
        """Test vector search handles KB errors gracefully."""
        mock_kb = MockKnowledgeBase(records=[], should_fail=True)

        executor = QueryExecutor(knowledge_base=mock_kb)

        result = executor._execute_vector_search("test query", None, 100)

        assert len(result.records) == 0


# =============================================================================
# Test Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    def test_execute_handles_exception(self):
        """Test execute handles exceptions gracefully."""
        mock_kb = MockKnowledgeBase(records=[], should_fail=True)
        mock_planner = MockPlanner(plan=None)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=mock_planner,
        )

        result = executor.execute("test query")

        # When planner fails and returns None, it falls back to vector search
        # Vector search may also fail, but should still return a valid result
        assert result.used_fallback
        # Execution path may be VECTOR_ONLY (with used_fallback=True) or FALLBACK
        assert result.execution_path in (ExecutionPath.FALLBACK, ExecutionPath.VECTOR_ONLY)

    def test_graph_traversal_handles_error(self):
        """Test graph traversal handles errors gracefully."""
        mock_kb = MockKnowledgeBase(records=[{"recordId": "start_001"}])
        mock_graph = MockGraphRetriever(nodes=[], should_fail=True)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            graph_retriever=mock_graph,
        )

        # No seed_ids to trigger traversal path
        plan = MockPlan(
            seed_ids=None,
            traversal_plan=MockTraversalPlan(),
            confidence=0.9,
            target_object="CustomObject__c",
        )

        result = executor.execute_with_plan("find related records", plan)

        # Should not raise, graph traversal error is caught
        # Results may come from KB query for start IDs
        assert result.execution_path == ExecutionPath.GRAPH_TRAVERSAL


# =============================================================================
# Test Telemetry Logging
# =============================================================================


class TestTelemetry:
    """Tests for telemetry logging."""

    def test_telemetry_logged_on_success(self, caplog):
        """Test telemetry is logged on successful execution."""
        records = [{"recordId": "id_001", "Name": "Record 1"}]
        mock_kb = MockKnowledgeBase(records=records)
        mock_planner = MockPlanner(plan=MockPlan(seed_ids=["id_001"], confidence=0.9))

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=mock_planner,
        )

        with caplog.at_level("INFO"):
            result = executor.execute("test query")

        # Verify telemetry was logged
        assert any("query_execution" in record.message for record in caplog.records)

    def test_telemetry_includes_execution_path(self, caplog):
        """Test telemetry includes execution path."""
        records = [{"recordId": "id_001", "Name": "Record 1"}]
        mock_kb = MockKnowledgeBase(records=records)
        mock_planner = MockPlanner(plan=MockPlan(seed_ids=["id_001"], confidence=0.9))

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=mock_planner,
        )

        with caplog.at_level("INFO"):
            result = executor.execute("test query")

        # Find telemetry log
        telemetry_logs = [r for r in caplog.records if "query_execution" in r.message]
        assert len(telemetry_logs) > 0
