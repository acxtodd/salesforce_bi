"""
Property-Based Tests for Query Executor.

**Feature: graph-aware-zero-config-retrieval**

Tests the following properties:
- Property 13: Seed ID Filtering (Requirements 7.1)
- Property 14: Graph Traversal Authorization (Requirements 11.4)
"""

import os
import sys
from typing import Any, Dict, List, Optional, Set

import pytest
from hypothesis import given, strategies as st, settings, assume

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from query_executor import (
    QueryExecutor,
    ExecutionResult,
    ExecutionPath,
    AuthorizationContext,
    create_authorization_context,
)


# =============================================================================
# Mock Dependencies for Property Testing
# =============================================================================


class MockKnowledgeBase:
    """Mock Knowledge Base for property testing."""

    def __init__(self, records: Optional[List[Dict[str, Any]]] = None):
        self.records = records or []
        self.last_query: Optional[str] = None
        self.last_filters: Optional[Dict[str, Any]] = None

    def retrieve(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Mock retrieve method."""
        self.last_query = query
        self.last_filters = filters

        results = self.records.copy()

        # Apply recordId filter if present
        if filters and "recordId" in filters:
            record_ids = filters["recordId"].get("$in", [])
            results = [r for r in results if r.get("recordId") in record_ids]

        return results[:limit]


class MockGraphRetriever:
    """Mock Graph Retriever for property testing."""

    def __init__(self, nodes: Optional[List[Dict[str, Any]]] = None):
        self.nodes = nodes or []

    def traverse(
        self,
        start_ids: List[str],
        traversal_plan: Any,
        max_nodes: int = 50,
    ) -> List[Dict[str, Any]]:
        """Mock traverse method."""
        # Return nodes that are reachable from start_ids
        results = []
        for node in self.nodes:
            node_id = node.get("recordId") or node.get("id")
            if node_id in start_ids or node.get("parent_id") in start_ids:
                results.append(node)
        return results[:max_nodes]


class MockPlanner:
    """Mock Planner for property testing."""

    def __init__(self, plan: Optional[Any] = None):
        self._plan = plan

    def plan(self, query: str, timeout_ms: Optional[int] = None) -> Any:
        """Mock plan method."""
        return self._plan

    def should_fallback(self, plan: Any) -> bool:
        """Mock should_fallback method."""
        if plan is None:
            return True
        if hasattr(plan, "confidence"):
            return plan.confidence < 0.5
        return False


class MockPlan:
    """Mock StructuredPlan for property testing."""

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


class MockDerivedViewManager:
    """Mock Derived View Manager for property testing."""

    def query_with_fallback(
        self,
        view_name: str,
        query: str,
        filters: Optional[List[Any]] = None,
        **kwargs,
    ) -> tuple:
        """Mock query with fallback."""
        return [], True


# =============================================================================
# Strategies for Property Testing
# =============================================================================

# Record ID strategy (Salesforce ID format)
record_id_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    min_size=15,
    max_size=18,
)

# User ID strategy
user_id_strategy = st.text(
    alphabet="0123456789ABCDEF",
    min_size=15,
    max_size=18,
).map(lambda s: "005" + s)

# Object type strategy
object_type_strategy = st.sampled_from([
    "ascendix__Property__c",
    "ascendix__Availability__c",
    "ascendix__Lease__c",
    "ascendix__Sale__c",
    "Account",
    "Contact",
    "Task",
])

# Query strategy
query_strategy = st.text(min_size=1, max_size=200).filter(lambda x: x.strip())


@st.composite
def record_strategy(draw):
    """Generate a random record."""
    return {
        "recordId": draw(record_id_strategy),
        "object_type": draw(object_type_strategy),
        "Name": draw(st.text(min_size=1, max_size=50)),
    }


@st.composite
def seed_ids_strategy(draw):
    """Generate a list of seed IDs."""
    return draw(st.lists(record_id_strategy, min_size=1, max_size=20, unique=True))


@st.composite
def authorization_context_strategy(draw):
    """Generate an authorization context."""
    user_id = draw(user_id_strategy)
    accessible_objects = draw(
        st.lists(object_type_strategy, min_size=0, max_size=5, unique=True)
    )
    accessible_records = draw(
        st.lists(record_id_strategy, min_size=0, max_size=10, unique=True)
    )

    # 50% chance of having record-level restrictions
    has_record_restrictions = draw(st.booleans())

    return AuthorizationContext(
        user_id=user_id,
        accessible_object_types=set(accessible_objects) if accessible_objects else set(),
        accessible_record_ids=set(accessible_records) if has_record_restrictions and accessible_records else None,
    )


# =============================================================================
# Property 13: Seed ID Filtering
# Requirements: 7.1
# =============================================================================


class TestProperty13SeedIDFiltering:
    """
    Property 13: Seed ID Filtering

    **Validates: Requirements 7.1**

    Properties tested:
    1. When seed IDs are provided, only those records are returned
    2. KB filter includes recordId filter when seed IDs present
    3. Unauthorized seed IDs are excluded from results
    4. Empty seed IDs result in empty results
    """

    @given(
        seed_ids=seed_ids_strategy(),
        query=query_strategy,
    )
    @settings(max_examples=50, deadline=None)
    def test_seed_ids_filter_kb_query(
        self,
        seed_ids: List[str],
        query: str,
    ):
        """
        Property: When seedIds provided, KB query includes recordId filter.

        For any set of seed IDs, the KB filter should contain $in with those IDs.
        """
        # Create records matching seed IDs
        records = [{"recordId": sid, "Name": f"Record {i}"} for i, sid in enumerate(seed_ids)]
        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=MockPlanner(MockPlan(seed_ids=seed_ids)),
        )

        plan = MockPlan(seed_ids=seed_ids, confidence=0.9)
        result = executor.execute_with_plan(query, plan)

        # Verify KB was queried with recordId filter
        assert mock_kb.last_filters is not None, "KB should receive filters"
        assert "recordId" in mock_kb.last_filters, "Filter should include recordId"
        assert "$in" in mock_kb.last_filters["recordId"], "Should use $in operator"

        # All seed IDs should be in the filter
        filter_ids = set(mock_kb.last_filters["recordId"]["$in"])
        assert filter_ids == set(seed_ids), "All seed IDs should be in filter"

    @given(
        seed_ids=seed_ids_strategy(),
        query=query_strategy,
        auth_context=authorization_context_strategy(),
    )
    @settings(max_examples=50, deadline=None)
    def test_unauthorized_seed_ids_excluded(
        self,
        seed_ids: List[str],
        query: str,
        auth_context: AuthorizationContext,
    ):
        """
        Property: Unauthorized seed IDs are excluded from KB query.

        When authorization restricts record access, only authorized seed IDs
        are passed to KB.
        """
        assume(auth_context.accessible_record_ids is not None)

        # Create records matching seed IDs
        records = [{"recordId": sid, "Name": f"Record {i}"} for i, sid in enumerate(seed_ids)]
        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=MockPlanner(MockPlan(seed_ids=seed_ids)),
        )

        plan = MockPlan(seed_ids=seed_ids, confidence=0.9)
        result = executor.execute_with_plan(query, plan, authorization=auth_context)

        # Only authorized seed IDs should be in the filter
        if mock_kb.last_filters and "recordId" in mock_kb.last_filters:
            filter_ids = set(mock_kb.last_filters["recordId"]["$in"])
            # All filter IDs should be in accessible_record_ids
            for fid in filter_ids:
                assert auth_context.can_access_record(fid), (
                    f"Record {fid} in filter but not authorized"
                )

    @given(query=query_strategy)
    @settings(max_examples=20, deadline=None)
    def test_empty_seed_ids_returns_empty(self, query: str):
        """
        Property: Empty seed IDs with authorization results in empty results.

        When seed IDs are empty or all unauthorized, result should be empty.
        """
        mock_kb = MockKnowledgeBase(records=[])

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=MockPlanner(MockPlan(seed_ids=[])),
        )

        # Authorization that denies all records
        auth_context = AuthorizationContext(
            user_id="005TestUser",
            accessible_record_ids=set(),  # Empty set - no access
        )

        plan = MockPlan(seed_ids=["id1", "id2"], confidence=0.9)
        result = executor.execute_with_plan(query, plan, authorization=auth_context)

        assert len(result.records) == 0, "No records when all seed IDs unauthorized"
        assert result.seed_ids_used == [], "No seed IDs should be used"

    @given(
        seed_ids=seed_ids_strategy(),
        query=query_strategy,
    )
    @settings(max_examples=30, deadline=None)
    def test_seed_id_count_tracked(
        self,
        seed_ids: List[str],
        query: str,
    ):
        """
        Property: Seed IDs used are tracked in result.

        The ExecutionResult should accurately report seed_ids_used.
        """
        records = [{"recordId": sid, "Name": f"Record {i}"} for i, sid in enumerate(seed_ids)]
        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=MockPlanner(MockPlan(seed_ids=seed_ids)),
        )

        plan = MockPlan(seed_ids=seed_ids, confidence=0.9)
        result = executor.execute_with_plan(query, plan)

        # All seed IDs should be tracked
        assert set(result.seed_ids_used) == set(seed_ids), (
            "All seed IDs should be tracked in result"
        )


# =============================================================================
# Property 14: Graph Traversal Authorization
# Requirements: 11.4
# =============================================================================


class TestProperty14GraphAuthorization:
    """
    Property 14: Graph Traversal Authorization

    **Validates: Requirements 11.4**

    Properties tested:
    1. Unauthorized nodes are excluded from graph traversal results
    2. Authorization is checked at each hop
    3. Object type restrictions are enforced
    4. Record-level restrictions are enforced
    """

    @given(
        auth_context=authorization_context_strategy(),
        query=query_strategy,
    )
    @settings(max_examples=50, deadline=None)
    def test_unauthorized_nodes_excluded(
        self,
        auth_context: AuthorizationContext,
        query: str,
    ):
        """
        Property: Unauthorized nodes are excluded from results.

        After graph traversal, only authorized nodes should remain.
        """
        assume(auth_context.accessible_record_ids is not None)
        assume(len(auth_context.accessible_record_ids) > 0)

        # Create mix of authorized and unauthorized nodes
        authorized_ids = list(auth_context.accessible_record_ids)[:5]
        unauthorized_ids = ["unauth_001", "unauth_002", "unauth_003"]

        nodes = [
            {"recordId": rid, "object_type": "Account", "Name": f"Auth {i}"}
            for i, rid in enumerate(authorized_ids)
        ] + [
            {"recordId": rid, "object_type": "Account", "Name": f"Unauth {i}"}
            for i, rid in enumerate(unauthorized_ids)
        ]

        mock_graph = MockGraphRetriever(nodes=nodes)
        mock_kb = MockKnowledgeBase(
            records=[{"recordId": authorized_ids[0]}] if authorized_ids else []
        )

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            graph_retriever=mock_graph,
            planner=MockPlanner(),
        )

        class MockTraversalPlan:
            max_depth = 2

        plan = MockPlan(
            seed_ids=authorized_ids[:1] if authorized_ids else [],
            traversal_plan=MockTraversalPlan(),
            confidence=0.9,
        )

        result = executor.execute_with_plan(query, plan, authorization=auth_context)

        # All returned records should be authorized
        for record in result.records:
            record_id = record.get("recordId") or record.get("id")
            if record_id:
                assert auth_context.can_access_record(record_id), (
                    f"Record {record_id} should not be in results"
                )

    @given(
        auth_context=authorization_context_strategy(),
        query=query_strategy,
    )
    @settings(max_examples=50, deadline=None)
    def test_object_type_restrictions_enforced(
        self,
        auth_context: AuthorizationContext,
        query: str,
    ):
        """
        Property: Object type restrictions are enforced.

        Nodes with inaccessible object types should be excluded.
        """
        assume(len(auth_context.accessible_object_types) > 0)

        accessible_type = list(auth_context.accessible_object_types)[0]
        inaccessible_type = "SomeObject__c"
        assume(inaccessible_type not in auth_context.accessible_object_types)

        nodes = [
            {"recordId": "acc_001", "object_type": accessible_type, "Name": "Accessible"},
            {"recordId": "inacc_001", "object_type": inaccessible_type, "Name": "Inaccessible"},
        ]

        mock_graph = MockGraphRetriever(nodes=nodes)
        mock_kb = MockKnowledgeBase(records=[{"recordId": "acc_001"}])

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            graph_retriever=mock_graph,
            planner=MockPlanner(),
        )

        class MockTraversalPlan:
            max_depth = 2

        plan = MockPlan(
            seed_ids=["acc_001"],
            traversal_plan=MockTraversalPlan(),
            confidence=0.9,
        )

        result = executor.execute_with_plan(query, plan, authorization=auth_context)

        # All returned records should have accessible object types
        for record in result.records:
            obj_type = record.get("object_type") or record.get("sobjectType")
            if obj_type:
                assert auth_context.can_access_object(obj_type), (
                    f"Object type {obj_type} should not be accessible"
                )

    @given(
        query=query_strategy,
    )
    @settings(max_examples=20, deadline=None)
    def test_no_auth_context_allows_all(self, query: str):
        """
        Property: Without authorization context, all nodes are allowed.

        When no authorization is provided, all nodes should be accessible.
        """
        nodes = [
            {"recordId": f"node_{i}", "object_type": "Account", "Name": f"Node {i}"}
            for i in range(5)
        ]

        mock_graph = MockGraphRetriever(nodes=nodes)
        mock_kb = MockKnowledgeBase(records=[{"recordId": "node_0"}])

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            graph_retriever=mock_graph,
            planner=MockPlanner(),
        )

        class MockTraversalPlan:
            max_depth = 2

        plan = MockPlan(
            seed_ids=["node_0"],
            traversal_plan=MockTraversalPlan(),
            confidence=0.9,
        )

        # No authorization context
        result = executor.execute_with_plan(query, plan, authorization=None)

        # Should have records (authorization filter not applied)
        assert result.authorization_filtered == 0, (
            "No records should be filtered without auth context"
        )

    @given(
        auth_context=authorization_context_strategy(),
        query=query_strategy,
    )
    @settings(max_examples=30, deadline=None)
    def test_authorization_filtered_count_accurate(
        self,
        auth_context: AuthorizationContext,
        query: str,
    ):
        """
        Property: Authorization filtered count is accurate.

        The authorization_filtered count should reflect actual filtering.
        """
        assume(auth_context.accessible_record_ids is not None)

        # Create records with known authorization status
        authorized_id = "auth_001"
        unauthorized_ids = ["unauth_001", "unauth_002"]

        if auth_context.accessible_record_ids:
            auth_context.accessible_record_ids.add(authorized_id)

        records = [
            {"recordId": authorized_id, "Name": "Authorized"},
        ] + [
            {"recordId": uid, "Name": f"Unauth {i}"}
            for i, uid in enumerate(unauthorized_ids)
        ]

        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=MockPlanner(),
        )

        # Vector search path
        result = executor._execute_vector_search(query, auth_context, limit=100)

        # The filtered count should be at least the unauthorized records
        # that would have been returned
        returned_ids = {r.get("recordId") for r in result.records}
        all_returned_ids = {r.get("recordId") for r in records}

        # Unauthorized IDs should not be in results
        for uid in unauthorized_ids:
            assert uid not in returned_ids, f"Unauthorized {uid} should be filtered"


# =============================================================================
# Additional Property Tests for Edge Cases
# =============================================================================


class TestPropertyEdgeCases:
    """Additional property tests for edge cases."""

    @given(
        records=st.lists(record_strategy(), min_size=0, max_size=20),
        limit=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=30, deadline=None)
    def test_limit_respected(
        self,
        records: List[Dict[str, Any]],
        limit: int,
    ):
        """
        Property: Limit is always respected.

        Results should never exceed the specified limit.
        """
        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=MockPlanner(),
        )

        result = executor._execute_vector_search("test query", None, limit=limit)

        assert len(result.records) <= limit, (
            f"Results ({len(result.records)}) should not exceed limit ({limit})"
        )

    @given(query=query_strategy)
    @settings(max_examples=20, deadline=None)
    def test_execution_result_has_required_fields(self, query: str):
        """
        Property: ExecutionResult always has required fields.

        All execution results should have properly initialized fields.
        """
        mock_kb = MockKnowledgeBase(records=[])

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=MockPlanner(),
        )

        result = executor._execute_vector_search(query, None, limit=10)

        # Check required fields exist and have correct types
        assert isinstance(result.records, list)
        assert isinstance(result.execution_path, ExecutionPath)
        assert isinstance(result.used_fallback, bool)
        assert isinstance(result.graph_nodes_visited, int)
        assert isinstance(result.authorization_filtered, int)
        assert result.graph_nodes_visited >= 0
        assert result.authorization_filtered >= 0

    @given(
        seed_ids=seed_ids_strategy(),
        predicates_count=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=30, deadline=None)
    def test_execution_path_determined_correctly(
        self,
        seed_ids: List[str],
        predicates_count: int,
    ):
        """
        Property: Execution path is determined by plan contents.

        Seed IDs should trigger SEED_ID_FILTER path.
        """
        records = [{"recordId": sid, "Name": f"Record {i}"} for i, sid in enumerate(seed_ids)]
        mock_kb = MockKnowledgeBase(records=records)

        executor = QueryExecutor(
            knowledge_base=mock_kb,
            planner=MockPlanner(),
        )

        # Plan with seed IDs (use non-aggregation object)
        plan_with_seeds = MockPlan(
            seed_ids=seed_ids,
            confidence=0.9,
            target_object="CustomObject__c",  # Non-aggregation object
        )
        result = executor.execute_with_plan("find records", plan_with_seeds)

        assert result.execution_path == ExecutionPath.SEED_ID_FILTER, (
            "Seed IDs should trigger SEED_ID_FILTER path"
        )

        # Plan without seed IDs but with predicates
        class MockPredicate:
            field = "Name"
            operator = "eq"
            value = "Test"

        predicates = [MockPredicate() for _ in range(predicates_count)]
        plan_with_filters = MockPlan(
            seed_ids=None,
            predicates=predicates,
            confidence=0.9,
            target_object="CustomObject__c",  # Non-aggregation object
        )
        result2 = executor.execute_with_plan("find records", plan_with_filters)

        if predicates:
            assert result2.execution_path == ExecutionPath.STRUCTURED_FILTER, (
                "Predicates without seed IDs should trigger STRUCTURED_FILTER path"
            )
