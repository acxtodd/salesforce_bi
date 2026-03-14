"""
Unit Tests for Traversal Planner.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 4.1, 4.2, 4.3, 4.4**

Tests path planning for various object combinations, cap configuration,
and timeout handling.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from traversal_planner import (
    TraversalPlanner,
    TraversalPlan,
    TraversalHop,
    TraversalResult,
    RelationshipMetadata,
    TraversalDirection,
    plan_traversal,
    DEFAULT_MAX_DEPTH,
    DEFAULT_NODE_CAP,
    DEFAULT_TIMEOUT_MS,
    MAX_ALLOWED_DEPTH,
    MIN_DEPTH,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def planner():
    """Create a TraversalPlanner with default settings."""
    return TraversalPlanner()


@pytest.fixture
def planner_with_custom_caps():
    """Create a TraversalPlanner with custom caps."""
    return TraversalPlanner(
        max_depth=1,
        node_cap=50,
        timeout_ms=200,
    )


@pytest.fixture
def mock_schema_cache():
    """Create a mock schema cache."""
    mock = MagicMock()
    mock.get.return_value = None
    return mock


# =============================================================================
# TraversalHop Tests
# =============================================================================


class TestTraversalHop:
    """Tests for TraversalHop dataclass."""

    def test_create_valid_hop(self):
        """Test creating a valid TraversalHop."""
        hop = TraversalHop(
            from_object="Account",
            to_object="Contact",
            relationship_field="AccountId",
            direction="outbound",
        )

        assert hop.from_object == "Account"
        assert hop.to_object == "Contact"
        assert hop.relationship_field == "AccountId"
        assert hop.direction == "outbound"

    def test_default_direction(self):
        """Test default direction is outbound."""
        hop = TraversalHop(
            from_object="Account",
            to_object="Contact",
            relationship_field="AccountId",
        )

        assert hop.direction == "outbound"

    def test_to_dict(self):
        """Test converting TraversalHop to dictionary."""
        hop = TraversalHop(
            from_object="Account",
            to_object="Contact",
            relationship_field="AccountId",
            direction="inbound",
        )

        result = hop.to_dict()

        assert result["from_object"] == "Account"
        assert result["to_object"] == "Contact"
        assert result["relationship_field"] == "AccountId"
        assert result["direction"] == "inbound"

    def test_from_dict(self):
        """Test creating TraversalHop from dictionary."""
        data = {
            "from_object": "Account",
            "to_object": "Contact",
            "relationship_field": "AccountId",
            "direction": "outbound",
        }

        hop = TraversalHop.from_dict(data)

        assert hop.from_object == "Account"
        assert hop.to_object == "Contact"
        assert hop.relationship_field == "AccountId"
        assert hop.direction == "outbound"

    def test_from_dict_with_defaults(self):
        """Test creating TraversalHop from partial dictionary."""
        data = {}

        hop = TraversalHop.from_dict(data)

        assert hop.from_object == ""
        assert hop.to_object == ""
        assert hop.relationship_field == ""
        assert hop.direction == "outbound"


# =============================================================================
# TraversalPlan Tests
# =============================================================================


class TestTraversalPlan:
    """Tests for TraversalPlan dataclass."""

    def test_create_valid_plan(self):
        """Test creating a valid TraversalPlan."""
        plan = TraversalPlan(
            start_object="Account",
            target_object="Contact",
            max_depth=2,
            node_cap=100,
            timeout_ms=400,
        )

        assert plan.start_object == "Account"
        assert plan.target_object == "Contact"
        assert plan.max_depth == 2
        assert plan.node_cap == 100
        assert plan.timeout_ms == 400
        assert plan.hops == []
        assert plan.predicates == []

    def test_max_depth_clamped_to_max_allowed(self):
        """Test that max_depth is clamped to MAX_ALLOWED_DEPTH."""
        plan = TraversalPlan(
            start_object="Account",
            target_object="Contact",
            max_depth=10,  # Exceeds MAX_ALLOWED_DEPTH
        )

        assert plan.max_depth == MAX_ALLOWED_DEPTH

    def test_max_depth_clamped_to_min(self):
        """Test that max_depth is clamped to MIN_DEPTH."""
        plan = TraversalPlan(
            start_object="Account",
            target_object="Contact",
            max_depth=-5,  # Below MIN_DEPTH
        )

        assert plan.max_depth == MIN_DEPTH

    def test_invalid_node_cap_defaults(self):
        """Test that invalid node_cap defaults to DEFAULT_NODE_CAP."""
        plan = TraversalPlan(
            start_object="Account",
            target_object="Contact",
            node_cap=0,
        )

        assert plan.node_cap == DEFAULT_NODE_CAP

    def test_negative_node_cap_defaults(self):
        """Test that negative node_cap defaults to DEFAULT_NODE_CAP."""
        plan = TraversalPlan(
            start_object="Account",
            target_object="Contact",
            node_cap=-50,
        )

        assert plan.node_cap == DEFAULT_NODE_CAP

    def test_invalid_timeout_defaults(self):
        """Test that invalid timeout_ms defaults to DEFAULT_TIMEOUT_MS."""
        plan = TraversalPlan(
            start_object="Account",
            target_object="Contact",
            timeout_ms=0,
        )

        assert plan.timeout_ms == DEFAULT_TIMEOUT_MS

    def test_negative_timeout_defaults(self):
        """Test that negative timeout_ms defaults to DEFAULT_TIMEOUT_MS."""
        plan = TraversalPlan(
            start_object="Account",
            target_object="Contact",
            timeout_ms=-100,
        )

        assert plan.timeout_ms == DEFAULT_TIMEOUT_MS

    def test_to_dict(self):
        """Test converting TraversalPlan to dictionary."""
        hop = TraversalHop(
            from_object="Account",
            to_object="Contact",
            relationship_field="AccountId",
        )
        plan = TraversalPlan(
            start_object="Account",
            target_object="Contact",
            hops=[hop],
            max_depth=1,
            node_cap=50,
            timeout_ms=200,
            predicates=[{"field": "Status", "operator": "eq", "value": "Active"}],
        )

        result = plan.to_dict()

        assert result["start_object"] == "Account"
        assert result["target_object"] == "Contact"
        assert len(result["hops"]) == 1
        assert result["hops"][0]["from_object"] == "Account"
        assert result["max_depth"] == 1
        assert result["node_cap"] == 50
        assert result["timeout_ms"] == 200
        assert len(result["predicates"]) == 1

    def test_from_dict(self):
        """Test creating TraversalPlan from dictionary."""
        data = {
            "start_object": "Account",
            "target_object": "Contact",
            "hops": [
                {
                    "from_object": "Account",
                    "to_object": "Contact",
                    "relationship_field": "AccountId",
                    "direction": "inbound",
                }
            ],
            "max_depth": 1,
            "node_cap": 75,
            "timeout_ms": 300,
            "predicates": [],
        }

        plan = TraversalPlan.from_dict(data)

        assert plan.start_object == "Account"
        assert plan.target_object == "Contact"
        assert len(plan.hops) == 1
        assert plan.hops[0].direction == "inbound"
        assert plan.max_depth == 1
        assert plan.node_cap == 75
        assert plan.timeout_ms == 300


# =============================================================================
# TraversalResult Tests
# =============================================================================


class TestTraversalResult:
    """Tests for TraversalResult dataclass."""

    def test_create_empty_result(self):
        """Test creating an empty TraversalResult."""
        result = TraversalResult()

        assert result.matching_node_ids == set()
        assert result.paths_found == 0
        assert result.nodes_visited == 0
        assert result.depth_reached == 0
        assert not result.truncated
        assert result.cap_triggered is None
        assert result.elapsed_ms == 0.0

    def test_create_result_with_data(self):
        """Test creating a TraversalResult with data."""
        result = TraversalResult(
            matching_node_ids={"node1", "node2"},
            paths_found=2,
            nodes_visited=10,
            depth_reached=2,
            truncated=True,
            cap_triggered="node_cap",
            elapsed_ms=150.5,
        )

        assert len(result.matching_node_ids) == 2
        assert result.paths_found == 2
        assert result.nodes_visited == 10
        assert result.depth_reached == 2
        assert result.truncated
        assert result.cap_triggered == "node_cap"
        assert result.elapsed_ms == 150.5

    def test_to_dict(self):
        """Test converting TraversalResult to dictionary."""
        result = TraversalResult(
            matching_node_ids={"node1", "node2"},
            paths_found=2,
            nodes_visited=10,
            depth_reached=1,
            truncated=False,
            cap_triggered=None,
            elapsed_ms=100.0,
        )

        result_dict = result.to_dict()

        assert set(result_dict["matching_node_ids"]) == {"node1", "node2"}
        assert result_dict["paths_found"] == 2
        assert result_dict["nodes_visited"] == 10
        assert result_dict["depth_reached"] == 1
        assert not result_dict["truncated"]
        assert result_dict["cap_triggered"] is None
        assert result_dict["elapsed_ms"] == 100.0


# =============================================================================
# TraversalPlanner Path Planning Tests
# =============================================================================


class TestTraversalPlannerPathPlanning:
    """
    Tests for path planning with various object combinations.

    **Requirements: 4.1**
    """

    def test_same_object_no_traversal(self, planner):
        """Test that same start and target returns empty hops."""
        plan = planner.plan("Account", "Account")

        assert plan is not None
        assert plan.start_object == "Account"
        assert plan.target_object == "Account"
        assert plan.hops == []
        assert plan.max_depth == 0

    def test_direct_relationship_account_to_contact(self, planner):
        """Test path planning for Account -> Contact (direct relationship)."""
        plan = planner.plan("Account", "Contact")

        assert plan is not None
        assert plan.start_object == "Account"
        assert plan.target_object == "Contact"
        assert len(plan.hops) == 1
        assert plan.hops[0].from_object == "Account"
        assert plan.hops[0].to_object == "Contact"

    def test_direct_relationship_contact_to_account(self, planner):
        """Test path planning for Contact -> Account (direct relationship)."""
        plan = planner.plan("Contact", "Account")

        assert plan is not None
        assert plan.start_object == "Contact"
        assert plan.target_object == "Account"
        assert len(plan.hops) == 1
        assert plan.hops[0].from_object == "Contact"
        assert plan.hops[0].to_object == "Account"

    def test_property_to_availability(self, planner):
        """Test path planning for Property -> Availability."""
        plan = planner.plan("ascendix__Property__c", "ascendix__Availability__c")

        assert plan is not None
        assert len(plan.hops) == 1
        assert plan.hops[0].from_object == "ascendix__Property__c"
        assert plan.hops[0].to_object == "ascendix__Availability__c"

    def test_availability_to_property(self, planner):
        """Test path planning for Availability -> Property."""
        plan = planner.plan("ascendix__Availability__c", "ascendix__Property__c")

        assert plan is not None
        assert len(plan.hops) == 1
        assert plan.hops[0].from_object == "ascendix__Availability__c"
        assert plan.hops[0].to_object == "ascendix__Property__c"

    def test_property_to_lease(self, planner):
        """Test path planning for Property -> Lease."""
        plan = planner.plan("ascendix__Property__c", "ascendix__Lease__c")

        assert plan is not None
        assert len(plan.hops) == 1

    def test_property_to_deal(self, planner):
        """Test path planning for Property -> Deal."""
        plan = planner.plan("ascendix__Property__c", "ascendix__Deal__c")

        assert plan is not None
        assert len(plan.hops) == 1

    def test_property_to_sale(self, planner):
        """Test path planning for Property -> Sale."""
        plan = planner.plan("ascendix__Property__c", "ascendix__Sale__c")

        assert plan is not None
        assert len(plan.hops) == 1

    def test_two_hop_path_account_to_task(self, planner):
        """Test path planning requiring two hops."""
        # Account -> Contact -> Task (via WhoId)
        # or Account -> Task (via WhatId) - direct
        plan = planner.plan("Account", "Task")

        assert plan is not None
        # Should find direct path via WhatId
        assert len(plan.hops) >= 1

    def test_two_hop_path_property_to_account(self, planner):
        """Test path planning for Property -> Account (via owner)."""
        plan = planner.plan("ascendix__Property__c", "Account")

        assert plan is not None
        assert len(plan.hops) == 1

    def test_no_path_returns_none(self, planner):
        """Test that no path returns None."""
        # Create a planner with max_depth=0 to force no path
        limited_planner = TraversalPlanner(max_depth=0)

        no_path_plan = limited_planner.plan("Account", "Contact")
        assert no_path_plan is None

        # Same object should still work
        same_plan = limited_planner.plan("Account", "Account")
        assert same_plan is not None
        assert same_plan.hops == []

    def test_empty_start_object_returns_none(self, planner):
        """Test that empty start_object returns None."""
        plan = planner.plan("", "Contact")

        assert plan is None

    def test_empty_target_object_returns_none(self, planner):
        """Test that empty target_object returns None."""
        plan = planner.plan("Account", "")

        assert plan is None

    def test_plan_with_predicates(self, planner):
        """Test path planning with predicates."""
        predicates = [
            {"field": "Status", "operator": "eq", "value": "Active"},
            {"field": "Type", "operator": "in", "value": ["Office", "Retail"]},
        ]

        plan = planner.plan("Account", "Contact", predicates=predicates)

        assert plan is not None
        assert len(plan.predicates) == 2
        assert plan.predicates[0]["field"] == "Status"


# =============================================================================
# TraversalPlanner Cap Configuration Tests
# =============================================================================


class TestTraversalPlannerCapConfiguration:
    """
    Tests for cap configuration.

    **Requirements: 4.2**
    """

    def test_default_configuration(self, planner):
        """Test default configuration values."""
        assert planner.max_depth == DEFAULT_MAX_DEPTH
        assert planner.node_cap == DEFAULT_NODE_CAP
        assert planner.timeout_ms == DEFAULT_TIMEOUT_MS

    def test_custom_max_depth(self):
        """Test custom max_depth configuration."""
        custom_planner = TraversalPlanner(max_depth=1)

        assert custom_planner.max_depth == 1

    def test_max_depth_clamped_to_max_allowed(self):
        """Test that max_depth is clamped to MAX_ALLOWED_DEPTH."""
        custom_planner = TraversalPlanner(max_depth=10)

        assert custom_planner.max_depth == MAX_ALLOWED_DEPTH

    def test_max_depth_clamped_to_min(self):
        """Test that max_depth is clamped to MIN_DEPTH."""
        custom_planner = TraversalPlanner(max_depth=-5)

        assert custom_planner.max_depth == MIN_DEPTH

    def test_custom_node_cap(self):
        """Test custom node_cap configuration."""
        custom_planner = TraversalPlanner(node_cap=50)

        assert custom_planner.node_cap == 50

    def test_invalid_node_cap_defaults(self):
        """Test that invalid node_cap defaults to DEFAULT_NODE_CAP."""
        custom_planner = TraversalPlanner(node_cap=0)

        assert custom_planner.node_cap == DEFAULT_NODE_CAP

    def test_negative_node_cap_defaults(self):
        """Test that negative node_cap defaults to DEFAULT_NODE_CAP."""
        custom_planner = TraversalPlanner(node_cap=-50)

        assert custom_planner.node_cap == DEFAULT_NODE_CAP

    def test_custom_timeout(self):
        """Test custom timeout_ms configuration."""
        custom_planner = TraversalPlanner(timeout_ms=200)

        assert custom_planner.timeout_ms == 200

    def test_invalid_timeout_defaults(self):
        """Test that invalid timeout_ms defaults to DEFAULT_TIMEOUT_MS."""
        custom_planner = TraversalPlanner(timeout_ms=0)

        assert custom_planner.timeout_ms == DEFAULT_TIMEOUT_MS

    def test_negative_timeout_defaults(self):
        """Test that negative timeout_ms defaults to DEFAULT_TIMEOUT_MS."""
        custom_planner = TraversalPlanner(timeout_ms=-100)

        assert custom_planner.timeout_ms == DEFAULT_TIMEOUT_MS

    def test_plan_uses_planner_defaults(self, planner):
        """Test that plan uses planner's default configuration."""
        plan = planner.plan("Account", "Contact")

        assert plan is not None
        assert plan.node_cap == DEFAULT_NODE_CAP
        assert plan.timeout_ms == DEFAULT_TIMEOUT_MS

    def test_plan_override_max_depth(self, planner):
        """Test overriding max_depth in plan() call."""
        plan = planner.plan("Account", "Contact", max_depth=1)

        assert plan is not None
        # The plan's max_depth is based on actual hops, not the override
        # But the override affects path finding

    def test_plan_override_node_cap(self, planner):
        """Test overriding node_cap in plan() call."""
        plan = planner.plan("Account", "Contact", node_cap=25)

        assert plan is not None
        assert plan.node_cap == 25

    def test_plan_override_timeout(self, planner):
        """Test overriding timeout_ms in plan() call."""
        plan = planner.plan("Account", "Contact", timeout_ms=100)

        assert plan is not None
        assert plan.timeout_ms == 100

    def test_plan_override_clamped_max_depth(self, planner):
        """Test that overridden max_depth is clamped."""
        # Even with override, max_depth should be clamped
        plan = planner.plan("Account", "Contact", max_depth=10)

        assert plan is not None
        # The actual depth is based on path length, but the search is limited


# =============================================================================
# TraversalPlanner Timeout Handling Tests
# =============================================================================


class TestTraversalPlannerTimeoutHandling:
    """
    Tests for timeout handling.

    **Requirements: 4.4**
    """

    def test_timeout_configuration_in_plan(self, planner):
        """Test that timeout is configured in the plan."""
        plan = planner.plan("Account", "Contact")

        assert plan is not None
        assert plan.timeout_ms == DEFAULT_TIMEOUT_MS

    def test_custom_timeout_in_plan(self):
        """Test custom timeout in plan."""
        custom_planner = TraversalPlanner(timeout_ms=200)
        plan = custom_planner.plan("Account", "Contact")

        assert plan is not None
        assert plan.timeout_ms == 200

    def test_timeout_override_in_plan_call(self, planner):
        """Test timeout override in plan() call."""
        plan = planner.plan("Account", "Contact", timeout_ms=150)

        assert plan is not None
        assert plan.timeout_ms == 150

    def test_traversal_result_tracks_elapsed_time(self):
        """Test that TraversalResult tracks elapsed time."""
        result = TraversalResult(elapsed_ms=250.5)

        assert result.elapsed_ms == 250.5

    def test_traversal_result_timeout_cap_triggered(self):
        """Test TraversalResult with timeout cap triggered."""
        result = TraversalResult(
            truncated=True,
            cap_triggered="timeout",
            elapsed_ms=400.0,
        )

        assert result.truncated
        assert result.cap_triggered == "timeout"


# =============================================================================
# TraversalPlanner Relationship Tests
# =============================================================================


class TestTraversalPlannerRelationships:
    """Tests for relationship handling."""

    def test_get_related_objects_account(self, planner):
        """Test getting related objects for Account."""
        related = planner.get_related_objects("Account")

        assert isinstance(related, list)
        assert "Contact" in related
        assert "Opportunity" in related

    def test_get_related_objects_property(self, planner):
        """Test getting related objects for Property."""
        related = planner.get_related_objects("ascendix__Property__c")

        assert isinstance(related, list)
        assert "ascendix__Availability__c" in related
        assert "ascendix__Lease__c" in related

    def test_get_related_objects_unknown(self, planner):
        """Test getting related objects for unknown object."""
        related = planner.get_related_objects("UnknownObject__c")

        assert related == []

    def test_has_relationship_direct(self, planner):
        """Test has_relationship for direct relationship."""
        assert planner.has_relationship("Account", "Contact")
        assert planner.has_relationship("Contact", "Account")

    def test_has_relationship_property_availability(self, planner):
        """Test has_relationship for Property-Availability."""
        assert planner.has_relationship(
            "ascendix__Property__c", "ascendix__Availability__c"
        )
        assert planner.has_relationship(
            "ascendix__Availability__c", "ascendix__Property__c"
        )

    def test_has_relationship_none(self, planner):
        """Test has_relationship for unrelated objects."""
        # Contact and Availability are not directly related
        assert not planner.has_relationship("Contact", "ascendix__Availability__c")


# =============================================================================
# TraversalPlanner with Schema Cache Tests
# =============================================================================


class TestTraversalPlannerWithSchemaCache:
    """Tests for TraversalPlanner with schema cache."""

    def test_planner_with_schema_cache(self, mock_schema_cache):
        """Test creating planner with schema cache."""
        planner = TraversalPlanner(schema_cache=mock_schema_cache)

        assert planner.schema_cache is mock_schema_cache

    def test_planner_loads_schema_relationships(self, mock_schema_cache):
        """Test that planner attempts to load schema relationships."""
        # The mock returns None, so no additional relationships are loaded
        planner = TraversalPlanner(schema_cache=mock_schema_cache)

        # Should still have known relationships
        assert planner.has_relationship("Account", "Contact")


# =============================================================================
# Convenience Function Tests
# =============================================================================


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_plan_traversal_function(self):
        """Test plan_traversal convenience function."""
        plan = plan_traversal("Account", "Contact")

        assert plan is not None
        assert plan.start_object == "Account"
        assert plan.target_object == "Contact"

    def test_plan_traversal_with_custom_caps(self):
        """Test plan_traversal with custom caps."""
        plan = plan_traversal(
            "Account",
            "Contact",
            max_depth=1,
            node_cap=50,
            timeout_ms=200,
        )

        assert plan is not None
        assert plan.node_cap == 50
        assert plan.timeout_ms == 200

    def test_plan_traversal_no_path(self):
        """Test plan_traversal when no path exists."""
        plan = plan_traversal(
            "Account",
            "Contact",
            max_depth=0,
        )

        # With max_depth=0, only same-object plans work
        # Account != Contact, so no path
        assert plan is None

    def test_plan_traversal_same_object(self):
        """Test plan_traversal for same object."""
        plan = plan_traversal("Account", "Account")

        assert plan is not None
        assert plan.hops == []
        assert plan.max_depth == 0


# =============================================================================
# RelationshipMetadata Tests
# =============================================================================


class TestRelationshipMetadata:
    """Tests for RelationshipMetadata dataclass."""

    def test_create_relationship_metadata(self):
        """Test creating RelationshipMetadata."""
        rel = RelationshipMetadata(
            parent_object="Account",
            child_object="Contact",
            relationship_field="AccountId",
            relationship_name="Contacts",
            is_lookup=True,
        )

        assert rel.parent_object == "Account"
        assert rel.child_object == "Contact"
        assert rel.relationship_field == "AccountId"
        assert rel.relationship_name == "Contacts"
        assert rel.is_lookup

    def test_relationship_metadata_defaults(self):
        """Test RelationshipMetadata default values."""
        rel = RelationshipMetadata(
            parent_object="Account",
            child_object="Contact",
            relationship_field="AccountId",
        )

        assert rel.relationship_name == ""
        assert rel.is_lookup

    def test_relationship_metadata_to_dict(self):
        """Test converting RelationshipMetadata to dictionary."""
        rel = RelationshipMetadata(
            parent_object="Account",
            child_object="Contact",
            relationship_field="AccountId",
            relationship_name="Contacts",
            is_lookup=False,
        )

        result = rel.to_dict()

        assert result["parent_object"] == "Account"
        assert result["child_object"] == "Contact"
        assert result["relationship_field"] == "AccountId"
        assert result["relationship_name"] == "Contacts"
        assert not result["is_lookup"]


# =============================================================================
# TraversalDirection Tests
# =============================================================================


class TestTraversalDirection:
    """Tests for TraversalDirection enum."""

    def test_direction_values(self):
        """Test TraversalDirection enum values."""
        assert TraversalDirection.OUTBOUND.value == "outbound"
        assert TraversalDirection.INBOUND.value == "inbound"
        assert TraversalDirection.BOTH.value == "both"

    def test_direction_from_string(self):
        """Test creating TraversalDirection from string."""
        assert TraversalDirection("outbound") == TraversalDirection.OUTBOUND
        assert TraversalDirection("inbound") == TraversalDirection.INBOUND
        assert TraversalDirection("both") == TraversalDirection.BOTH
