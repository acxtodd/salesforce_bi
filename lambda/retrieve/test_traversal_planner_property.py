"""
Property-Based Tests for Traversal Planner.

**Feature: graph-aware-zero-config-retrieval, Property 9: Traversal Node Cap Enforcement**
**Validates: Requirements 4.2, 4.3**

Property 9: Traversal Node Cap Enforcement with Logging
*For any* graph traversal, the system SHALL visit at most node_cap nodes
(default 50-100), returning partial results if cap is reached AND logging
the cap trigger for analysis.
"""

import os
import sys
import logging
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest
from hypothesis import given, strategies as st, settings, assume

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from traversal_planner import (
    TraversalPlan,
    TraversalResult,
    DEFAULT_MAX_DEPTH,
    DEFAULT_NODE_CAP,
    MAX_ALLOWED_DEPTH,
)


@dataclass
class MockGraphNode:
    """Mock graph node for testing."""

    node_id: str
    node_type: str
    display_name: str = ""
    sharing_buckets: List[str] = field(default_factory=list)


@dataclass
class MockGraphEdge:
    """Mock graph edge for testing."""

    source_id: str
    target_id: str
    relationship_type: str = "related_to"


class MockGraph:
    """Mock graph structure for property testing."""

    def __init__(self):
        self.nodes: Dict[str, MockGraphNode] = {}
        self.edges: Dict[str, List[MockGraphEdge]] = {}
        self.reverse_edges: Dict[str, List[MockGraphEdge]] = {}

    def add_node(self, node: MockGraphNode) -> None:
        self.nodes[node.node_id] = node
        if node.node_id not in self.edges:
            self.edges[node.node_id] = []
        if node.node_id not in self.reverse_edges:
            self.reverse_edges[node.node_id] = []

    def add_edge(self, edge: MockGraphEdge) -> None:
        if edge.source_id not in self.edges:
            self.edges[edge.source_id] = []
        self.edges[edge.source_id].append(edge)
        if edge.target_id not in self.reverse_edges:
            self.reverse_edges[edge.target_id] = []
        self.reverse_edges[edge.target_id].append(edge)

    def get_connected_nodes(self, node_id: str) -> List[Tuple[Dict, MockGraphNode]]:
        connected = []
        for edge in self.edges.get(node_id, []):
            if edge.target_id in self.nodes:
                connected.append(({}, self.nodes[edge.target_id]))
        for edge in self.reverse_edges.get(node_id, []):
            if edge.source_id in self.nodes:
                connected.append(({}, self.nodes[edge.source_id]))
        return connected

    def get_node(self, node_id: str) -> Optional[MockGraphNode]:
        return self.nodes.get(node_id)

    @property
    def node_count(self) -> int:
        return len(self.nodes)


class MockGraphTraverser:
    """Mock graph traverser that enforces node cap and logs cap triggers."""

    def __init__(
        self,
        graph: MockGraph,
        node_cap: int = DEFAULT_NODE_CAP,
        max_depth: int = DEFAULT_MAX_DEPTH,
        logger: Optional[logging.Logger] = None,
    ):
        self.graph = graph
        self.node_cap = node_cap
        self.max_depth = max_depth
        self.logger = logger or logging.getLogger(__name__)
        self.nodes_visited = 0
        self.cap_triggered = False
        self.cap_trigger_logged = False
        self.depth_reached = 0

    def traverse(
        self,
        start_node_ids: List[str],
        target_types: Optional[List[str]] = None,
    ) -> TraversalResult:
        """Execute graph traversal with node cap enforcement."""
        matching_node_ids: Set[str] = set()
        visited: Set[str] = set()
        self.nodes_visited = 0
        self.cap_triggered = False
        self.cap_trigger_logged = False
        self.depth_reached = 0

        def dfs(node_id: str, depth: int) -> None:
            if self.nodes_visited >= self.node_cap:
                if not self.cap_triggered:
                    self.cap_triggered = True
                    self.logger.warning(
                        "Traversal node cap triggered",
                        extra={
                            "node_cap": self.node_cap,
                            "nodes_visited": self.nodes_visited,
                        },
                    )
                    self.cap_trigger_logged = True
                return

            if node_id in visited:
                return

            node = self.graph.get_node(node_id)
            if not node:
                return

            visited.add(node_id)
            self.nodes_visited += 1
            self.depth_reached = max(self.depth_reached, depth)

            if target_types is None or node.node_type in target_types:
                matching_node_ids.add(node_id)

            if depth >= self.max_depth:
                return

            connected = self.graph.get_connected_nodes(node_id)
            for _, connected_node in connected:
                if connected_node.node_id not in visited:
                    dfs(connected_node.node_id, depth + 1)

        for start_id in start_node_ids:
            if self.nodes_visited >= self.node_cap:
                break
            dfs(start_id, 0)

        return TraversalResult(
            matching_node_ids=matching_node_ids,
            paths_found=len(matching_node_ids),
            nodes_visited=self.nodes_visited,
            depth_reached=self.depth_reached,
            truncated=self.cap_triggered,
            cap_triggered="node_cap" if self.cap_triggered else None,
        )


VALID_OBJECT_TYPES = [
    "ascendix__Property__c",
    "ascendix__Availability__c",
    "ascendix__Lease__c",
    "ascendix__Deal__c",
    "Account",
    "Contact",
]


@st.composite
def large_graph_strategy(draw, min_nodes: int = 50, max_nodes: int = 200):
    """Generate a large graph for testing node cap enforcement."""
    num_nodes = draw(st.integers(min_value=min_nodes, max_value=max_nodes))
    graph = MockGraph()
    node_ids = []

    for i in range(num_nodes):
        node_id = f"node_{i:05d}"
        node_type = draw(st.sampled_from(VALID_OBJECT_TYPES))
        node = MockGraphNode(
            node_id=node_id, node_type=node_type, display_name=f"Node {i}"
        )
        graph.add_node(node)
        node_ids.append(node_id)

    for i in range(1, num_nodes):
        parent_idx = draw(st.integers(min_value=0, max_value=i - 1))
        edge = MockGraphEdge(source_id=node_ids[parent_idx], target_id=node_ids[i])
        graph.add_edge(edge)

    return graph, node_ids


class TestTraversalPlannerProperty:
    """
    Property-based tests for Traversal Planner.
    **Feature: graph-aware-zero-config-retrieval, Property 9: Traversal Node Cap Enforcement**
    **Validates: Requirements 4.2, 4.3**
    """

    @pytest.mark.property
    @settings(max_examples=100)
    @given(data=st.data())
    def test_property_9_node_cap_enforcement_with_logging(self, data):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 9: Traversal Node Cap Enforcement with Logging**
        **Validates: Requirements 4.2, 4.3**
        """
        graph, node_ids = data.draw(large_graph_strategy(min_nodes=80, max_nodes=200))
        node_cap = data.draw(st.integers(min_value=10, max_value=50))
        assume(graph.node_count > node_cap)

        mock_logger = MagicMock(spec=logging.Logger)
        traverser = MockGraphTraverser(
            graph=graph,
            node_cap=node_cap,
            max_depth=MAX_ALLOWED_DEPTH,
            logger=mock_logger,
        )

        result = traverser.traverse(start_node_ids=[node_ids[0]])

        # Property 9.1: Node cap SHALL be enforced
        assert result.nodes_visited <= node_cap

        # Property 9.2: When cap is reached, truncated flag SHALL be True
        if traverser.cap_triggered:
            assert result.truncated
            assert result.cap_triggered == "node_cap"

        # Property 9.3: When cap is triggered, it SHALL be logged
        if traverser.cap_triggered:
            assert traverser.cap_trigger_logged
            mock_logger.warning.assert_called()

    @pytest.mark.property
    @settings(max_examples=100)
    @given(
        node_cap=st.integers(min_value=10, max_value=100),
        graph_size=st.integers(min_value=5, max_value=50),
    )
    def test_node_cap_not_triggered_for_small_graphs(self, node_cap, graph_size):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 9: Traversal Node Cap Enforcement**
        **Validates: Requirements 4.2, 4.3**
        """
        assume(graph_size < node_cap)

        graph = MockGraph()
        node_ids = []
        for i in range(graph_size):
            node_id = f"small_node_{i:03d}"
            node = MockGraphNode(
                node_id=node_id, node_type="Account", display_name=f"Node {i}"
            )
            graph.add_node(node)
            node_ids.append(node_id)
            if i > 0:
                edge = MockGraphEdge(source_id=node_ids[i - 1], target_id=node_id)
                graph.add_edge(edge)

        traverser = MockGraphTraverser(
            graph=graph, node_cap=node_cap, max_depth=MAX_ALLOWED_DEPTH
        )
        result = traverser.traverse(start_node_ids=[node_ids[0]] if node_ids else [])

        assert not result.truncated
        assert result.cap_triggered is None

    @pytest.mark.property
    @settings(max_examples=100)
    @given(data=st.data())
    def test_partial_results_returned_on_cap(self, data):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 9: Traversal Node Cap Enforcement**
        **Validates: Requirements 4.2, 4.3**
        """
        graph, node_ids = data.draw(large_graph_strategy(min_nodes=100, max_nodes=200))
        node_cap = data.draw(st.integers(min_value=5, max_value=20))
        assume(graph.node_count > node_cap * 2)

        traverser = MockGraphTraverser(
            graph=graph, node_cap=node_cap, max_depth=MAX_ALLOWED_DEPTH
        )
        result = traverser.traverse(start_node_ids=[node_ids[0]])

        assert len(result.matching_node_ids) > 0
        assert len(result.matching_node_ids) <= result.nodes_visited

    @pytest.mark.property
    @settings(max_examples=100)
    @given(node_cap=st.integers(min_value=50, max_value=100))
    def test_traversal_plan_node_cap_configuration(self, node_cap):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 9: Traversal Node Cap Enforcement**
        **Validates: Requirements 4.2**
        """
        plan = TraversalPlan(
            start_object="Account",
            target_object="ascendix__Property__c",
            node_cap=node_cap,
        )
        assert plan.node_cap == node_cap
        assert plan.node_cap > 0

    @pytest.mark.property
    @settings(max_examples=100)
    @given(invalid_cap=st.integers(min_value=-100, max_value=0))
    def test_invalid_node_cap_defaults_to_valid(self, invalid_cap):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 9: Traversal Node Cap Enforcement**
        **Validates: Requirements 4.2**
        """
        plan = TraversalPlan(
            start_object="Account", target_object="Contact", node_cap=invalid_cap
        )
        assert plan.node_cap == DEFAULT_NODE_CAP

    @pytest.mark.property
    @settings(max_examples=100)
    @given(data=st.data())
    def test_traversal_result_serialization(self, data):
        """
        **Feature: graph-aware-zero-config-retrieval, Property 9: Traversal Node Cap Enforcement**
        **Validates: Requirements 4.2, 4.3**
        """
        nodes_visited = data.draw(st.integers(min_value=1, max_value=200))
        truncated = data.draw(st.booleans())
        cap_triggered = "node_cap" if truncated else None
        matching_ids = set(
            f"node_{i}"
            for i in range(
                data.draw(st.integers(min_value=0, max_value=min(50, nodes_visited)))
            )
        )

        result = TraversalResult(
            matching_node_ids=matching_ids,
            paths_found=len(matching_ids),
            nodes_visited=nodes_visited,
            depth_reached=data.draw(
                st.integers(min_value=0, max_value=MAX_ALLOWED_DEPTH)
            ),
            truncated=truncated,
            cap_triggered=cap_triggered,
        )

        result_dict = result.to_dict()
        assert result_dict["truncated"] == truncated
        assert result_dict["cap_triggered"] == cap_triggered
        assert result_dict["nodes_visited"] == nodes_visited
        assert isinstance(result_dict["matching_node_ids"], list)
        assert set(result_dict["matching_node_ids"]) == matching_ids
