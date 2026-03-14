"""
Traversal Planner for Graph-Aware Zero-Config Retrieval.

Determines optimal traversal paths for cross-object queries, specifying
depth, node/edge caps, and timeout limits.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 4.1, 4.2, 4.3, 4.4**
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))


# =============================================================================
# Constants and Configuration
# =============================================================================

# Default configuration values
DEFAULT_MAX_DEPTH = 2
DEFAULT_NODE_CAP = 100
DEFAULT_TIMEOUT_MS = 400
MIN_DEPTH = 0
MAX_ALLOWED_DEPTH = 2  # Per Requirements 4.1, 4.2 - max depth is 2


class TraversalDirection(Enum):
    """Direction of graph traversal."""
    OUTBOUND = "outbound"  # Follow edges from source to target
    INBOUND = "inbound"    # Follow edges from target to source
    BOTH = "both"          # Follow edges in both directions


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class TraversalHop:
    """
    Represents a single hop in a traversal path.

    **Requirements: 4.1**

    Attributes:
        from_object: Source object type
        to_object: Target object type
        relationship_field: Field that defines the relationship
        direction: Direction of traversal (outbound/inbound)
    """
    from_object: str
    to_object: str
    relationship_field: str
    direction: str = "outbound"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "from_object": self.from_object,
            "to_object": self.to_object,
            "relationship_field": self.relationship_field,
            "direction": self.direction,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraversalHop":
        """Create TraversalHop from dictionary."""
        return cls(
            from_object=data.get("from_object", ""),
            to_object=data.get("to_object", ""),
            relationship_field=data.get("relationship_field", ""),
            direction=data.get("direction", "outbound"),
        )


@dataclass
class TraversalPlan:
    """
    Specification for graph traversal.

    **Requirements: 4.1, 4.2**

    Attributes:
        start_object: Starting node type
        target_object: Target node type
        hops: List of traversal hops
        max_depth: Maximum traversal depth (0-2)
        node_cap: Maximum nodes to visit per query
        timeout_ms: Hard timeout in milliseconds
        predicates: Optional filters to apply during traversal
    """
    start_object: str
    target_object: str
    hops: List[TraversalHop] = field(default_factory=list)
    max_depth: int = DEFAULT_MAX_DEPTH
    node_cap: int = DEFAULT_NODE_CAP
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    predicates: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate and clamp configuration values."""
        # Enforce max_depth constraint (Requirements 4.1, 4.2)
        self.max_depth = max(MIN_DEPTH, min(MAX_ALLOWED_DEPTH, self.max_depth))

        # Ensure node_cap is positive
        if self.node_cap <= 0:
            self.node_cap = DEFAULT_NODE_CAP

        # Ensure timeout_ms is positive
        if self.timeout_ms <= 0:
            self.timeout_ms = DEFAULT_TIMEOUT_MS

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "start_object": self.start_object,
            "target_object": self.target_object,
            "hops": [h.to_dict() for h in self.hops],
            "max_depth": self.max_depth,
            "node_cap": self.node_cap,
            "timeout_ms": self.timeout_ms,
            "predicates": self.predicates,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraversalPlan":
        """Create TraversalPlan from dictionary."""
        hops = [TraversalHop.from_dict(h) for h in data.get("hops", [])]
        return cls(
            start_object=data.get("start_object", ""),
            target_object=data.get("target_object", ""),
            hops=hops,
            max_depth=data.get("max_depth", DEFAULT_MAX_DEPTH),
            node_cap=data.get("node_cap", DEFAULT_NODE_CAP),
            timeout_ms=data.get("timeout_ms", DEFAULT_TIMEOUT_MS),
            predicates=data.get("predicates", []),
        )


@dataclass
class TraversalResult:
    """
    Result of a traversal execution.

    **Requirements: 4.2, 4.3**

    Attributes:
        matching_node_ids: Set of node IDs that match the traversal
        paths_found: Number of valid paths found
        nodes_visited: Total nodes visited during traversal
        depth_reached: Maximum depth reached
        truncated: True if results were limited by caps
        cap_triggered: Type of cap that was triggered (if any)
        elapsed_ms: Time taken for traversal
    """
    matching_node_ids: Set[str] = field(default_factory=set)
    paths_found: int = 0
    nodes_visited: int = 0
    depth_reached: int = 0
    truncated: bool = False
    cap_triggered: Optional[str] = None  # "node_cap", "timeout", "depth"
    elapsed_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "matching_node_ids": list(self.matching_node_ids),
            "paths_found": self.paths_found,
            "nodes_visited": self.nodes_visited,
            "depth_reached": self.depth_reached,
            "truncated": self.truncated,
            "cap_triggered": self.cap_triggered,
            "elapsed_ms": self.elapsed_ms,
        }


# =============================================================================
# Schema Cache Protocol
# =============================================================================


class SchemaCacheProtocol(Protocol):
    """Protocol for SchemaCache to allow dependency injection."""

    def get(self, object_name: str) -> Optional[Any]:
        """Get schema for an object."""
        ...


# =============================================================================
# Relationship Metadata
# =============================================================================


@dataclass
class RelationshipMetadata:
    """
    Metadata about a relationship between two objects.

    Attributes:
        parent_object: Parent object API name
        child_object: Child object API name
        relationship_field: Field on child that references parent
        relationship_name: Name of the relationship
        is_lookup: True if lookup, False if master-detail
        is_primary: True if marked as primary by signal harvesting (Task 42.2)
    """
    parent_object: str
    child_object: str
    relationship_field: str
    relationship_name: str = ""
    is_lookup: bool = True
    is_primary: bool = False  # Task 42.2: Primary relationships from signal harvesting

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "parent_object": self.parent_object,
            "child_object": self.child_object,
            "relationship_field": self.relationship_field,
            "relationship_name": self.relationship_name,
            "is_lookup": self.is_lookup,
            "is_primary": self.is_primary,
        }


# =============================================================================
# Traversal Planner
# =============================================================================


class TraversalPlanner:
    """
    Plans optimal traversal paths for cross-object queries.

    **Requirements: 4.1, 4.2, 4.3, 4.4**

    The Traversal Planner:
    1. Loads relationship metadata from schema cache
    2. Determines optimal path between objects
    3. Configures depth, node caps, and timeouts
    4. Returns a TraversalPlan for execution
    """

    # Known relationships between CRE objects
    # Maps (child_object, parent_object) -> relationship_field
    KNOWN_RELATIONSHIPS: Dict[Tuple[str, str], str] = {
        # Property relationships
        ("ascendix__Availability__c", "ascendix__Property__c"): "ascendix__Property__c",
        ("ascendix__Lease__c", "ascendix__Property__c"): "ascendix__Property__c",
        ("ascendix__Deal__c", "ascendix__Property__c"): "ascendix__Property__c",
        ("ascendix__Listing__c", "ascendix__Property__c"): "ascendix__Property__c",
        ("ascendix__Sale__c", "ascendix__Property__c"): "ascendix__Property__c",
        # Account relationships
        ("Contact", "Account"): "AccountId",
        ("Opportunity", "Account"): "AccountId",
        ("Case", "Account"): "AccountId",
        ("Task", "Account"): "WhatId",
        ("Event", "Account"): "WhatId",
        # Contact relationships
        ("Task", "Contact"): "WhoId",
        ("Event", "Contact"): "WhoId",
        # Property to Account (owner)
        ("ascendix__Property__c", "Account"): "ascendix__Owner__c",
    }

    def __init__(
        self,
        schema_cache: Optional[SchemaCacheProtocol] = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
        node_cap: int = DEFAULT_NODE_CAP,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ):
        """
        Initialize the TraversalPlanner.

        **Requirements: 4.2**

        Args:
            schema_cache: SchemaCache instance for relationship metadata
            max_depth: Maximum traversal depth (default 2, max 2)
            node_cap: Maximum nodes to visit (default 100)
            timeout_ms: Timeout in milliseconds (default 400)
        """
        self.schema_cache = schema_cache
        self._max_depth = max(MIN_DEPTH, min(MAX_ALLOWED_DEPTH, max_depth))
        self._node_cap = node_cap if node_cap > 0 else DEFAULT_NODE_CAP
        self._timeout_ms = timeout_ms if timeout_ms > 0 else DEFAULT_TIMEOUT_MS

        # Build relationship graph from known relationships
        self._relationship_graph = self._build_relationship_graph()

    @property
    def max_depth(self) -> int:
        """Get configured max depth."""
        return self._max_depth

    @property
    def node_cap(self) -> int:
        """Get configured node cap."""
        return self._node_cap

    @property
    def timeout_ms(self) -> int:
        """Get configured timeout."""
        return self._timeout_ms

    def _build_relationship_graph(self) -> Dict[str, List[RelationshipMetadata]]:
        """
        Build a graph of relationships for path finding.

        Returns:
            Dictionary mapping object names to list of relationships
        """
        graph: Dict[str, List[RelationshipMetadata]] = {}

        for (child, parent), rel_field in self.KNOWN_RELATIONSHIPS.items():
            # Add child -> parent relationship
            if child not in graph:
                graph[child] = []
            graph[child].append(RelationshipMetadata(
                parent_object=parent,
                child_object=child,
                relationship_field=rel_field,
            ))

            # Add parent -> child (reverse) relationship
            if parent not in graph:
                graph[parent] = []
            graph[parent].append(RelationshipMetadata(
                parent_object=parent,
                child_object=child,
                relationship_field=rel_field,
            ))

        # Load additional relationships from schema cache if available
        if self.schema_cache:
            self._load_schema_relationships(graph)

        return graph

    def _load_schema_relationships(
        self, graph: Dict[str, List[RelationshipMetadata]]
    ) -> None:
        """
        Load relationships from schema cache.

        **Task 42.2**: Also loads primary_relationships and marks them as primary.

        Args:
            graph: Relationship graph to update
        """
        # Common CRE objects to check
        objects_to_check = [
            "ascendix__Property__c",
            "ascendix__Availability__c",
            "ascendix__Lease__c",
            "ascendix__Deal__c",
            "ascendix__Sale__c",
            "ascendix__Listing__c",
            "ascendix__Inquiry__c",
            "Account",
            "Contact",
            "Opportunity",
        ]

        for obj_name in objects_to_check:
            try:
                schema = self.schema_cache.get(obj_name)
                if schema and hasattr(schema, 'relationships'):
                    # Get primary relationships from schema (Task 42.2)
                    primary_rels = set()
                    if hasattr(schema, 'primary_relationships') and schema.primary_relationships:
                        primary_rels = set(schema.primary_relationships)

                    for rel in schema.relationships:
                        if rel.reference_to:
                            # Check if this relationship is marked as primary
                            is_primary = rel.name in primary_rels

                            # Add relationship if not already known
                            rel_key = (obj_name, rel.reference_to)
                            if rel_key not in self.KNOWN_RELATIONSHIPS:
                                if obj_name not in graph:
                                    graph[obj_name] = []
                                graph[obj_name].append(RelationshipMetadata(
                                    parent_object=rel.reference_to,
                                    child_object=obj_name,
                                    relationship_field=rel.name,
                                    is_primary=is_primary,
                                ))
                            elif is_primary:
                                # Update existing relationship to mark as primary
                                for existing in graph.get(obj_name, []):
                                    if existing.relationship_field == rel.name:
                                        existing.is_primary = True
                                        break
            except Exception as e:
                LOGGER.debug(f"Error loading schema for {obj_name}: {e}")

    def plan(
        self,
        start_object: str,
        target_object: str,
        predicates: Optional[List[Dict[str, Any]]] = None,
        max_depth: Optional[int] = None,
        node_cap: Optional[int] = None,
        timeout_ms: Optional[int] = None,
    ) -> Optional[TraversalPlan]:
        """
        Plan a traversal from start_object to target_object.

        **Requirements: 4.1, 4.2**

        Args:
            start_object: Starting object type
            target_object: Target object type to find
            predicates: Optional filters to apply during traversal
            max_depth: Override default max depth
            node_cap: Override default node cap
            timeout_ms: Override default timeout

        Returns:
            TraversalPlan if path found, None otherwise
        """
        if not start_object or not target_object:
            LOGGER.warning("Cannot plan traversal: missing start or target object")
            return None

        # Use provided values or defaults
        effective_max_depth = max_depth if max_depth is not None else self._max_depth
        effective_node_cap = node_cap if node_cap is not None else self._node_cap
        effective_timeout = timeout_ms if timeout_ms is not None else self._timeout_ms

        # Enforce max depth constraint (Requirements 4.1, 4.2)
        effective_max_depth = max(MIN_DEPTH, min(MAX_ALLOWED_DEPTH, effective_max_depth))

        # Same object - no traversal needed
        if start_object == target_object:
            return TraversalPlan(
                start_object=start_object,
                target_object=target_object,
                hops=[],
                max_depth=0,
                node_cap=effective_node_cap,
                timeout_ms=effective_timeout,
                predicates=predicates or [],
            )

        # Find path between objects
        path = self._find_path(start_object, target_object, effective_max_depth)

        if not path:
            LOGGER.info(
                f"No path found from {start_object} to {target_object} "
                f"within depth {effective_max_depth}"
            )
            return None

        # Build hops from path
        hops = self._build_hops(path)

        return TraversalPlan(
            start_object=start_object,
            target_object=target_object,
            hops=hops,
            max_depth=len(hops),
            node_cap=effective_node_cap,
            timeout_ms=effective_timeout,
            predicates=predicates or [],
        )

    def _find_path(
        self,
        start: str,
        target: str,
        max_depth: int,
    ) -> Optional[List[str]]:
        """
        Find shortest path between two objects using BFS.

        **Requirements: 4.1**

        Args:
            start: Starting object type
            target: Target object type
            max_depth: Maximum path length

        Returns:
            List of object types in path, or None if no path found
        """
        if start == target:
            return [start]

        if max_depth <= 0:
            return None

        # BFS to find shortest path, preferring primary relationships (Task 42.2)
        visited: Set[str] = {start}
        queue: List[Tuple[str, List[str]]] = [(start, [start])]

        while queue:
            current, path = queue.pop(0)

            # Check depth limit
            if len(path) > max_depth + 1:
                continue

            # Get connected objects, sorted by is_primary (primary first)
            relationships = self._relationship_graph.get(current, [])
            # Sort: primary relationships first, then alphabetically for determinism
            sorted_rels = sorted(
                relationships,
                key=lambda r: (not r.is_primary, r.relationship_field)
            )

            for rel in sorted_rels:
                # Determine next object
                if rel.parent_object == current:
                    next_obj = rel.child_object
                else:
                    next_obj = rel.parent_object

                if next_obj in visited:
                    continue

                new_path = path + [next_obj]

                if next_obj == target:
                    return new_path

                if len(new_path) <= max_depth + 1:
                    visited.add(next_obj)
                    queue.append((next_obj, new_path))

        return None

    def _build_hops(self, path: List[str]) -> List[TraversalHop]:
        """
        Build TraversalHop objects from a path.

        Args:
            path: List of object types in path order

        Returns:
            List of TraversalHop objects
        """
        hops: List[TraversalHop] = []

        for i in range(len(path) - 1):
            from_obj = path[i]
            to_obj = path[i + 1]

            # Find relationship field
            rel_field = self._get_relationship_field(from_obj, to_obj)
            direction = self._get_direction(from_obj, to_obj)

            hops.append(TraversalHop(
                from_object=from_obj,
                to_object=to_obj,
                relationship_field=rel_field,
                direction=direction,
            ))

        return hops

    def _get_relationship_field(self, from_obj: str, to_obj: str) -> str:
        """
        Get the relationship field between two objects.

        Args:
            from_obj: Source object
            to_obj: Target object

        Returns:
            Relationship field name
        """
        # Check direct relationship (child -> parent)
        key = (from_obj, to_obj)
        if key in self.KNOWN_RELATIONSHIPS:
            return self.KNOWN_RELATIONSHIPS[key]

        # Check reverse relationship (parent -> child)
        key = (to_obj, from_obj)
        if key in self.KNOWN_RELATIONSHIPS:
            return self.KNOWN_RELATIONSHIPS[key]

        # Check relationship graph
        for rel in self._relationship_graph.get(from_obj, []):
            if rel.parent_object == to_obj or rel.child_object == to_obj:
                return rel.relationship_field

        return ""

    def _get_direction(self, from_obj: str, to_obj: str) -> str:
        """
        Determine traversal direction between objects.

        Args:
            from_obj: Source object
            to_obj: Target object

        Returns:
            Direction string ("outbound" or "inbound")
        """
        # If from_obj is child and to_obj is parent, it's outbound
        if (from_obj, to_obj) in self.KNOWN_RELATIONSHIPS:
            return "outbound"

        # If from_obj is parent and to_obj is child, it's inbound
        if (to_obj, from_obj) in self.KNOWN_RELATIONSHIPS:
            return "inbound"

        return "outbound"  # Default

    def get_related_objects(self, object_name: str) -> List[str]:
        """
        Get objects related to the given object.

        Args:
            object_name: Object API name

        Returns:
            List of related object API names
        """
        related: Set[str] = set()

        for rel in self._relationship_graph.get(object_name, []):
            if rel.parent_object != object_name:
                related.add(rel.parent_object)
            if rel.child_object != object_name:
                related.add(rel.child_object)

        return list(related)

    def has_relationship(self, object1: str, object2: str) -> bool:
        """
        Check if two objects have a direct relationship.

        Args:
            object1: First object API name
            object2: Second object API name

        Returns:
            True if objects are directly related
        """
        return (
            (object1, object2) in self.KNOWN_RELATIONSHIPS or
            (object2, object1) in self.KNOWN_RELATIONSHIPS
        )


# =============================================================================
# Convenience Functions
# =============================================================================


def plan_traversal(
    start_object: str,
    target_object: str,
    schema_cache: Optional[SchemaCacheProtocol] = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    node_cap: int = DEFAULT_NODE_CAP,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> Optional[TraversalPlan]:
    """
    Convenience function to plan a traversal.

    Args:
        start_object: Starting object type
        target_object: Target object type
        schema_cache: Optional schema cache
        max_depth: Maximum depth (default 2)
        node_cap: Node cap (default 100)
        timeout_ms: Timeout (default 400ms)

    Returns:
        TraversalPlan if path found, None otherwise
    """
    planner = TraversalPlanner(
        schema_cache=schema_cache,
        max_depth=max_depth,
        node_cap=node_cap,
        timeout_ms=timeout_ms,
    )
    return planner.plan(start_object, target_object)
