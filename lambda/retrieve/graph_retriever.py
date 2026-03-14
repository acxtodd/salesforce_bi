"""
Graph-Aware Retriever for Phase 3 Graph Enhancement.

Combines graph traversal with vector search for relationship queries.
Implements secure multi-hop traversal with authorization at each hop.

**Feature: phase3-graph-enhancement**
**Requirements: 1.1, 1.2, 1.3, 4.3, 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 8.5, 6.1, 6.3**
"""
import os
import re
import time
import json
import logging
import hashlib
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

import boto3
from boto3.dynamodb.conditions import Key

# Import metrics module for CloudWatch integration
try:
    from graph_metrics import get_graph_metrics, GraphMetrics
    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False
    GraphMetrics = None

# Import circuit breaker for resilience (Task 10.1)
try:
    from circuit_breaker import (
        GraphCircuitBreaker,
        CircuitOpenError,
        get_graph_circuit_breaker,
        with_circuit_breaker,
    )
    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False
    GraphCircuitBreaker = None
    CircuitOpenError = Exception
    get_graph_circuit_breaker = None

# Import graceful degradation for fallback (Task 10.2)
try:
    from graceful_degradation import (
        GracefulDegradation,
        DegradationResult,
        DegradationMode,
        get_graceful_degradation,
        vector_only_fallback_result,
    )
    GRACEFUL_DEGRADATION_AVAILABLE = True
except ImportError:
    GRACEFUL_DEGRADATION_AVAILABLE = False
    GracefulDegradation = None
    DegradationResult = None
    DegradationMode = None
    get_graceful_degradation = None

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
cloudwatch = boto3.client('cloudwatch')

# Environment variables
GRAPH_NODES_TABLE = os.environ.get('GRAPH_NODES_TABLE', 'salesforce-ai-search-graph-nodes')
GRAPH_EDGES_TABLE = os.environ.get('GRAPH_EDGES_TABLE', 'salesforce-ai-search-graph-edges')
GRAPH_PATH_CACHE_TABLE = os.environ.get('GRAPH_PATH_CACHE_TABLE', 'salesforce-ai-search-graph-path-cache')
AUTHZ_LAMBDA_FUNCTION_NAME = os.environ.get('AUTHZ_LAMBDA_FUNCTION_NAME', '')

# Configuration
DEFAULT_MAX_DEPTH = 2
MAX_TRAVERSAL_DEPTH = 3
PATH_CACHE_TTL_SECONDS = 300  # 5 minutes
MAX_NODES_PER_HOP = 50  # Limit nodes per traversal hop for performance (reduced from 100)


class TraversalDirection(Enum):
    """Direction of graph traversal."""
    OUTBOUND = "outbound"  # Follow edges from source to target
    INBOUND = "inbound"    # Follow edges from target to source
    BOTH = "both"          # Follow edges in both directions


@dataclass
class GraphPath:
    """Represents a path through the graph."""
    nodes: List[str]  # List of node IDs in path order
    edges: List[Dict[str, Any]]  # Edge metadata for each hop
    start_type: str
    end_type: str
    depth: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "startType": self.start_type,
            "endType": self.end_type,
            "depth": self.depth,
        }


@dataclass
class GraphTraversalResult:
    """Result of a graph traversal operation."""
    paths: List[GraphPath]
    matching_node_ids: Set[str]
    traversal_depth: int
    nodes_visited: int
    cache_hit: bool = False
    truncated: bool = False  # True if results were limited

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "paths": [p.to_dict() for p in self.paths],
            "matchingNodeIds": list(self.matching_node_ids),
            "traversalDepth": self.traversal_depth,
            "nodesVisited": self.nodes_visited,
            "cacheHit": self.cache_hit,
            "truncated": self.truncated,
        }


@dataclass
class EntityExtraction:
    """Extracted entities from a query."""
    object_types: List[str]
    relationship_patterns: List[str]
    filter_criteria: Dict[str, Any]
    traversal_depth_hint: int = DEFAULT_MAX_DEPTH



# Object type patterns for entity extraction
OBJECT_TYPE_PATTERNS = {
    "ascendix__Property__c": [
        r'\bpropert(?:y|ies)\b',
        r'\bbuilding(?:s)?\b',
    ],
    "ascendix__Lease__c": [
        r'\blease(?:s)?\b',
        r'\btenant(?:s)?\b',
    ],
    "ascendix__Deal__c": [
        r'\bdeal(?:s)?\b',
        r'\btransaction(?:s)?\b',
    ],
    "ascendix__Availability__c": [
        r'\bavailab(?:le|ility|ilities)\b',
        r'\bvacant\b',
        r'\bspace(?:s)?\b',
    ],
    "ascendix__Sale__c": [
        r'\bsale(?:s)?\b',
        r'\bsold\b',
    ],
    "Account": [
        r'\baccount(?:s)?\b',
        r'\bcompan(?:y|ies)\b',
        r'\bclient(?:s)?\b',
    ],
    "Opportunity": [
        r'\bopportunit(?:y|ies)\b',
    ],
    "Case": [
        r'\bcase(?:s)?\b',
        r'\bissue(?:s)?\b',
        r'\bticket(?:s)?\b',
    ],
}

# Relationship patterns for extraction
RELATIONSHIP_EXTRACTION_PATTERNS = [
    (r'\b(?:with|having)\s+(?:open|active|expiring|pending)\s+(\w+)', "has_status"),
    (r'\b(?:owned|managed)\s+by\s+(\w+)', "owned_by"),
    (r'\b(?:related|connected|linked)\s+to\s+(\w+)', "related_to"),
    (r'\b(\w+)\s+(?:for|at|on|in)\s+(?:the\s+)?(\w+)', "for_location"),
]


class GraphAwareRetriever:
    """
    Graph-aware retriever that combines graph traversal with vector search.

    Supports:
    - Multi-hop relationship traversal (1-3 hops)
    - Authorization validation at each hop
    - Result merging with vector search
    - Path caching for performance
    - CloudWatch metrics for monitoring
    - Circuit breaker for resilience (Task 10.1)
    - Graceful degradation on failures (Task 10.2)

    **Requirements: 1.1, 1.2, 1.3, 4.3, 8.1, 8.2, 8.3, 6.1, 6.3**
    """

    def __init__(self, feature_flags: Optional[Dict[str, bool]] = None):
        """
        Initialize the Graph-Aware Retriever.

        Args:
            feature_flags: Optional feature flags for controlling behavior
                - cache_enabled: Enable path caching (default: True)
                - strict_auth: Require auth validation at every hop (default: True)
                - metrics_enabled: Enable CloudWatch metrics (default: True)
                - circuit_breaker_enabled: Enable circuit breaker (default: True)
                - graceful_degradation_enabled: Enable graceful degradation (default: True)
        """
        self.feature_flags = feature_flags or {}
        self.cache_enabled = self.feature_flags.get('cache_enabled', True)
        self.strict_auth = self.feature_flags.get('strict_auth', True)
        self.metrics_enabled = self.feature_flags.get('metrics_enabled', True)
        self.circuit_breaker_enabled = self.feature_flags.get('circuit_breaker_enabled', True)
        self.graceful_degradation_enabled = self.feature_flags.get('graceful_degradation_enabled', True)

        # Initialize table references
        self._nodes_table = None
        self._edges_table = None
        self._cache_table = None
        
        # Initialize metrics
        self._metrics: Optional[GraphMetrics] = None
        if METRICS_AVAILABLE and self.metrics_enabled:
            self._metrics = get_graph_metrics(enabled=True)
        
        # Initialize circuit breaker (Task 10.1)
        self._circuit_breaker: Optional[GraphCircuitBreaker] = None
        if CIRCUIT_BREAKER_AVAILABLE and self.circuit_breaker_enabled:
            self._circuit_breaker = get_graph_circuit_breaker()
        
        # Initialize graceful degradation (Task 10.2)
        self._degradation: Optional[GracefulDegradation] = None
        if GRACEFUL_DEGRADATION_AVAILABLE and self.graceful_degradation_enabled:
            self._degradation = get_graceful_degradation()

    @property
    def nodes_table(self):
        """Lazy initialization of nodes table."""
        if self._nodes_table is None:
            self._nodes_table = dynamodb.Table(GRAPH_NODES_TABLE)
        return self._nodes_table

    @property
    def edges_table(self):
        """Lazy initialization of edges table."""
        if self._edges_table is None:
            self._edges_table = dynamodb.Table(GRAPH_EDGES_TABLE)
        return self._edges_table

    @property
    def cache_table(self):
        """Lazy initialization of cache table."""
        if self._cache_table is None:
            self._cache_table = dynamodb.Table(GRAPH_PATH_CACHE_TABLE)
        return self._cache_table

    def retrieve(
        self,
        query: str,
        user_context: Dict[str, Any],
        filters: Optional[Dict[str, Any]] = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
        vector_fallback_func: Optional[callable] = None,
        seed_record_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute graph-aware retrieval for relationship queries.

        **Requirements: 1.1, 1.2, 4.3, 6.1, 6.3**

        Args:
            query: The user's natural language query
            user_context: User authorization context with sharing buckets
            filters: Optional metadata filters (sobject, region, etc.)
            max_depth: Maximum traversal depth (1-3)
            vector_fallback_func: Optional fallback function for vector-only search
            seed_record_ids: Optional list of record IDs from vector search to seed traversal

        Returns:
            Dictionary with matching node IDs, paths, and metadata
        """
        start_time = time.time()
        request_id = user_context.get('requestId', str(time.time()))

        # Clamp depth to valid range
        max_depth = max(1, min(MAX_TRAVERSAL_DEPTH, max_depth))

        # Extract entities from query
        extraction = self.extract_entities(query)
        LOGGER.info(f"Extracted entities: {extraction.object_types}, depth_hint={extraction.traversal_depth_hint}")

        # Use extraction depth hint if provided
        if extraction.traversal_depth_hint:
            max_depth = min(max_depth, extraction.traversal_depth_hint)

        # Check circuit breaker state first (Task 10.1)
        if self._circuit_breaker and self._circuit_breaker.is_open:
            LOGGER.warning(f"Circuit breaker is open, using fallback for request {request_id}")
            return self._handle_circuit_open(
                query, user_context, filters, max_depth, 
                vector_fallback_func, start_time, request_id
            )

        # Get starting nodes based on filters, object types, or seed record IDs
        try:
            start_nodes = self._get_start_nodes_with_circuit_breaker(
                extraction, filters, seed_record_ids
            )
        except CircuitOpenError:
            return self._handle_circuit_open(
                query, user_context, filters, max_depth,
                vector_fallback_func, start_time, request_id
            )
        except Exception as e:
            LOGGER.warning(f"Error getting start nodes: {e}")
            return self._handle_graph_error(
                e, query, user_context, filters, max_depth,
                vector_fallback_func, start_time, request_id
            )
        
        LOGGER.info(f"Found {len(start_nodes)} starting nodes")

        if not start_nodes:
            return {
                "success": True,
                "matchingNodeIds": [],
                "paths": [],
                "traversalDepth": max_depth,
                "nodesVisited": 0,
                "latencyMs": int((time.time() - start_time) * 1000),
            }

        # Check cache first
        cache_key = self._compute_cache_key(query, user_context, filters, max_depth)
        if self.cache_enabled:
            cached_result = self._get_cached_result(cache_key, user_context)
            if cached_result:
                cached_result["cacheHit"] = True
                cached_result["latencyMs"] = int((time.time() - start_time) * 1000)
                # Emit cache hit metric
                if self._metrics:
                    self._metrics.emit_cache_hit()
                else:
                    self._emit_metric("GraphCacheHit")
                return cached_result

        # Emit cache miss metric
        if self._metrics:
            self._metrics.emit_cache_miss()
        else:
            self._emit_metric("GraphCacheMiss")

        try:
            # Execute graph traversal with circuit breaker protection (Task 10.1)
            traversal_result = self._execute_traversal_with_circuit_breaker(
                start_nodes=start_nodes,
                user_context=user_context,
                max_depth=max_depth,
                target_types=extraction.object_types,
            )

            latency_ms = (time.time() - start_time) * 1000

            # Build result
            result = {
                "success": True,
                "matchingNodeIds": list(traversal_result.matching_node_ids),
                "paths": [p.to_dict() for p in traversal_result.paths],
                "traversalDepth": traversal_result.traversal_depth,
                "nodesVisited": traversal_result.nodes_visited,
                "cacheHit": False,
                "truncated": traversal_result.truncated,
                "latencyMs": int(latency_ms),
            }

            # Cache the result
            if self.cache_enabled and traversal_result.matching_node_ids:
                self._cache_result(cache_key, result, user_context)

            # Emit metrics (Task 9.1)
            if self._metrics:
                self._metrics.emit_traversal_latency(latency_ms, max_depth)
                self._metrics.emit_nodes_visited(traversal_result.nodes_visited, max_depth)
                self._metrics.emit_node_count(len(traversal_result.matching_node_ids))
                if traversal_result.truncated:
                    self._metrics.emit_truncated_result()
            else:
                self._emit_metric("GraphTraversalLatency", latency_ms)

            return result

        except CircuitOpenError:
            # Circuit breaker opened during traversal (Task 10.1)
            return self._handle_circuit_open(
                query, user_context, filters, max_depth,
                vector_fallback_func, start_time, request_id
            )
        except Exception as e:
            # Handle other errors with graceful degradation (Task 10.2)
            return self._handle_graph_error(
                e, query, user_context, filters, max_depth,
                vector_fallback_func, start_time, request_id
            )

    def _get_start_nodes_with_circuit_breaker(
        self,
        extraction: EntityExtraction,
        filters: Optional[Dict[str, Any]],
        seed_record_ids: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get starting nodes with circuit breaker protection.
        
        **Requirements: 4.3**
        """
        if self._circuit_breaker:
            return self._circuit_breaker.call(
                self._get_start_nodes, extraction, filters, seed_record_ids
            )
        return self._get_start_nodes(extraction, filters, seed_record_ids)

    def _execute_traversal_with_circuit_breaker(
        self,
        start_nodes: List[Dict[str, Any]],
        user_context: Dict[str, Any],
        max_depth: int,
        target_types: Optional[List[str]] = None,
    ) -> GraphTraversalResult:
        """
        Execute graph traversal with circuit breaker protection.
        
        **Requirements: 4.3**
        """
        if self._circuit_breaker:
            return self._circuit_breaker.call(
                self._traverse_with_auth,
                start_nodes=start_nodes,
                user_context=user_context,
                max_depth=max_depth,
                target_types=target_types,
            )
        return self._traverse_with_auth(
            start_nodes=start_nodes,
            user_context=user_context,
            max_depth=max_depth,
            target_types=target_types,
        )

    def _handle_circuit_open(
        self,
        query: str,
        user_context: Dict[str, Any],
        filters: Optional[Dict[str, Any]],
        max_depth: int,
        vector_fallback_func: Optional[callable],
        start_time: float,
        request_id: str,
    ) -> Dict[str, Any]:
        """
        Handle circuit breaker open state with graceful degradation.
        
        **Requirements: 4.3**
        """
        latency_ms = (time.time() - start_time) * 1000
        
        # Log the circuit open event (Task 10.3)
        LOGGER.warning(
            f"Graph circuit breaker open for request {request_id}",
            extra={
                "request_id": request_id,
                "query": query[:100],
                "error_type": "circuit_open",
            }
        )
        
        # Emit metric for circuit open fallback
        if self._metrics:
            self._metrics.emit_traversal_error("CircuitOpen")
        
        # Use vector fallback if provided (Task 10.2)
        if vector_fallback_func and self.graceful_degradation_enabled:
            try:
                fallback_result = vector_fallback_func(query, user_context, filters)
                return {
                    "success": True,
                    "matchingNodeIds": [],
                    "paths": [],
                    "traversalDepth": 0,
                    "nodesVisited": 0,
                    "cacheHit": False,
                    "latencyMs": int(latency_ms),
                    "degraded": True,
                    "warning": "circuit_breaker_open",
                    "fallbackResults": fallback_result,
                }
            except Exception as fallback_error:
                LOGGER.error(f"Fallback also failed: {fallback_error}")
        
        # Return empty result with degradation info
        return {
            "success": True,
            "matchingNodeIds": [],
            "paths": [],
            "traversalDepth": 0,
            "nodesVisited": 0,
            "cacheHit": False,
            "latencyMs": int(latency_ms),
            "degraded": True,
            "warning": "circuit_breaker_open",
        }

    def _handle_graph_error(
        self,
        error: Exception,
        query: str,
        user_context: Dict[str, Any],
        filters: Optional[Dict[str, Any]],
        max_depth: int,
        vector_fallback_func: Optional[callable],
        start_time: float,
        request_id: str,
    ) -> Dict[str, Any]:
        """
        Handle graph errors with graceful degradation.
        
        **Requirements: 4.3**
        """
        latency_ms = (time.time() - start_time) * 1000
        error_type = type(error).__name__
        
        # Log the error with context (Task 10.3)
        LOGGER.error(
            f"Graph error for request {request_id}: {error_type}: {error}",
            extra={
                "request_id": request_id,
                "query": query[:100],
                "error_type": error_type,
                "error_message": str(error),
            }
        )
        
        # Emit error metric
        if self._metrics:
            self._metrics.emit_traversal_error(error_type)
        
        # Use vector fallback if provided (Task 10.2)
        if vector_fallback_func and self.graceful_degradation_enabled:
            try:
                LOGGER.info(f"Using vector fallback for request {request_id}")
                fallback_result = vector_fallback_func(query, user_context, filters)
                return {
                    "success": True,
                    "matchingNodeIds": [],
                    "paths": [],
                    "traversalDepth": 0,
                    "nodesVisited": 0,
                    "cacheHit": False,
                    "latencyMs": int(latency_ms),
                    "degraded": True,
                    "warning": f"graph_error_{error_type.lower()}",
                    "fallbackResults": fallback_result,
                }
            except Exception as fallback_error:
                LOGGER.error(f"Fallback also failed: {fallback_error}")
        
        # Return empty result with error info
        return {
            "success": False,
            "matchingNodeIds": [],
            "paths": [],
            "traversalDepth": 0,
            "nodesVisited": 0,
            "cacheHit": False,
            "latencyMs": int(latency_ms),
            "degraded": True,
            "warning": f"graph_error_{error_type.lower()}",
            "error": str(error),
        }

    def extract_entities(self, query: str) -> EntityExtraction:
        """
        Extract object types, relationships, and filters from query.

        **Requirements: 1.1**

        Args:
            query: The user's natural language query

        Returns:
            EntityExtraction with detected entities
        """
        query_lower = query.lower()
        object_types = []
        relationship_patterns = []
        filter_criteria = {}

        # Extract object types
        for obj_type, patterns in OBJECT_TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    if obj_type not in object_types:
                        object_types.append(obj_type)
                    break

        # Extract relationship patterns
        for pattern, rel_type in RELATIONSHIP_EXTRACTION_PATTERNS:
            match = re.search(pattern, query_lower, re.IGNORECASE)
            if match:
                relationship_patterns.append(rel_type)

        # Determine traversal depth hint
        depth_hint = DEFAULT_MAX_DEPTH
        if re.search(r'\b(?:all|every|any)\s+(?:related|connected)\b', query_lower):
            depth_hint = 3  # Deep traversal
        elif re.search(r'\b(?:directly?|immediate(?:ly)?)\b', query_lower):
            depth_hint = 1  # Single hop

        return EntityExtraction(
            object_types=object_types,
            relationship_patterns=relationship_patterns,
            filter_criteria=filter_criteria,
            traversal_depth_hint=depth_hint,
        )


    def _get_start_nodes(
        self,
        extraction: EntityExtraction,
        filters: Optional[Dict[str, Any]],
        seed_record_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get starting nodes for traversal based on extraction, filters, or seed IDs.

        **Optimization**: When seed_record_ids are provided (from vector search),
        use those specific nodes as starting points instead of querying by type.
        This enables queries like "deals for Preston Park" to work correctly.

        Args:
            extraction: Extracted entities from query
            filters: Optional metadata filters
            seed_record_ids: Optional list of record IDs from vector search to use as seeds

        Returns:
            List of starting node dictionaries
        """
        start_nodes = []

        # Priority 1: Use seed record IDs from vector search results
        if seed_record_ids:
            LOGGER.info(f"Using {len(seed_record_ids)} seed record IDs for graph traversal")
            for record_id in seed_record_ids[:MAX_NODES_PER_HOP]:
                try:
                    response = self.nodes_table.get_item(Key={'nodeId': record_id})
                    if 'Item' in response:
                        item = response['Item']
                        start_nodes.append({
                            'nodeId': item['nodeId'],
                            'type': item.get('type', ''),
                            'displayName': item.get('displayName', ''),
                            'sharingBuckets': item.get('sharingBuckets', []),
                        })
                except Exception as e:
                    LOGGER.warning(f"Error fetching seed node {record_id}: {e}")

            if start_nodes:
                LOGGER.info(f"Found {len(start_nodes)} seed nodes in graph")
                return start_nodes

        # Priority 2: Query by object type (fallback)
        target_types = extraction.object_types
        if not target_types and filters:
            sobject_filter = filters.get("sobject", [])
            if isinstance(sobject_filter, str):
                target_types = [sobject_filter]
            elif isinstance(sobject_filter, list):
                target_types = sobject_filter

        if not target_types:
            target_types = ["ascendix__Property__c", "ascendix__Deal__c", "ascendix__Lease__c"]

        for obj_type in target_types[:3]:
            try:
                response = self.nodes_table.query(
                    IndexName='type-createdAt-index',
                    KeyConditionExpression=Key('type').eq(obj_type),
                    Limit=MAX_NODES_PER_HOP,
                )
                for item in response.get('Items', []):
                    start_nodes.append({
                        'nodeId': item['nodeId'],
                        'type': item['type'],
                        'displayName': item.get('displayName', ''),
                        'sharingBuckets': item.get('sharingBuckets', []),
                    })
            except Exception as e:
                LOGGER.warning(f"Error querying nodes by type {obj_type}: {e}")

        return start_nodes[:MAX_NODES_PER_HOP]

    def _traverse_with_auth(
        self,
        start_nodes: List[Dict[str, Any]],
        user_context: Dict[str, Any],
        max_depth: int,
        target_types: Optional[List[str]] = None,
    ) -> GraphTraversalResult:
        """
        Traverse graph with authorization check at each hop.

        **Requirements: 1.3, 8.1, 8.2, 8.3**

        Args:
            start_nodes: Starting nodes for traversal
            user_context: User authorization context
            max_depth: Maximum traversal depth
            target_types: Optional target object types to find

        Returns:
            GraphTraversalResult with paths and matching nodes
        """
        valid_paths: List[GraphPath] = []
        matching_node_ids: Set[str] = set()
        visited: Set[str] = set()
        nodes_visited = 0
        truncated = False

        user_sharing_buckets = set(user_context.get('sharingBuckets', []))

        def dfs(
            current_node: Dict[str, Any],
            path: List[str],
            edges: List[Dict[str, Any]],
            depth: int
        ) -> None:
            """Depth-first search with authorization."""
            nonlocal nodes_visited, truncated

            node_id = current_node['nodeId']

            # Check authorization for current node
            # **Property 7: Secure Graph Traversal**
            if not self._validate_access(current_node, user_sharing_buckets):
                LOGGER.debug(f"Access denied to node {node_id}")
                return  # Stop this path - user cannot access

            path.append(node_id)
            visited.add(node_id)
            nodes_visited += 1

            # Check if we've hit limits
            if nodes_visited > MAX_NODES_PER_HOP * max_depth:
                truncated = True
                path.pop()
                return

            # Add to matching nodes if at target depth or matches target type
            node_type = current_node.get('type', '')
            is_target_match = target_types is None or node_type in target_types
            if is_target_match:
                matching_node_ids.add(node_id)
                if len(matching_node_ids) <= 30:  # Log first 30
                    LOGGER.info(f"GRAPH_MATCH: Added {node_id} (type={node_type}, depth={depth}, name={current_node.get('displayName', 'N/A')})")

                # Record path for ALL matching nodes (not just at max_depth)
                # This enables depth-based prioritization in merge logic
                if len(path) > 1:
                    graph_path = GraphPath(
                        nodes=path.copy(),
                        edges=edges.copy(),
                        start_type=start_nodes[0].get('type', '') if start_nodes else '',
                        end_type=node_type,
                        depth=depth,
                    )
                    valid_paths.append(graph_path)

            elif depth > 0 and node_type and node_type.startswith('ascendix__'):
                # Log skipped Salesforce objects that didn't match target types
                LOGGER.debug(f"GRAPH_SKIP: {node_id} type={node_type} not in {target_types}")

            # If at max depth, return (stop traversing deeper)
            if depth >= max_depth:
                path.pop()
                return

            # Get connected nodes
            connected = self._get_connected_nodes(node_id)

            # Debug: Log connected nodes for seed records (depth 0)
            if depth == 0 and len(connected) > 0:
                connected_types = [(c[1].get('nodeId', ''), c[1].get('type', '')) for c in connected[:10]]
                LOGGER.info(f"Seed {node_id} ({node_type}) has {len(connected)} connected: {connected_types}")

            for edge_info, connected_node in connected:
                connected_id = connected_node.get('nodeId')
                if connected_id and connected_id not in visited:
                    edges.append(edge_info)
                    dfs(connected_node, path, edges, depth + 1)
                    edges.pop()

            path.pop()

        # Start DFS from each authorized starting node
        for start_node in start_nodes:
            if start_node['nodeId'] not in visited:
                dfs(start_node, [], [], 0)

            if truncated:
                break

        # Log summary of matching Deal IDs specifically
        deal_matches = [nid for nid in matching_node_ids if nid.startswith('a0P')]
        LOGGER.info(f"GRAPH_TRAVERSAL_DONE: {len(matching_node_ids)} total matches, {len(deal_matches)} deals: {deal_matches[:10]}")

        return GraphTraversalResult(
            paths=valid_paths,
            matching_node_ids=matching_node_ids,
            traversal_depth=max_depth,
            nodes_visited=nodes_visited,
            truncated=truncated,
        )

    def _validate_access(
        self,
        node: Dict[str, Any],
        user_sharing_buckets: Set[str]
    ) -> bool:
        """
        Validate user has access to node via sharing rules.

        **Requirements: 8.1, 8.2, 8.3**
        **Property 7: Secure Graph Traversal**

        Args:
            node: Node to validate access for
            user_sharing_buckets: User's sharing bucket tags

        Returns:
            True if user has access, False otherwise
        """
        if not self.strict_auth:
            return True  # Skip auth check if disabled

        node_sharing_buckets = node.get('sharingBuckets', [])

        # If node has no sharing buckets, allow access (public)
        if not node_sharing_buckets:
            return True

        # Check if any user bucket matches node buckets
        node_bucket_set = set(node_sharing_buckets)
        return bool(user_sharing_buckets & node_bucket_set)

    def _get_connected_nodes(
        self,
        node_id: str
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """
        Get nodes connected to the given node.

        **Requirements: 1.1, 1.2**

        Args:
            node_id: Source node ID

        Returns:
            List of (edge_info, connected_node) tuples
        """
        connected = []

        try:
            # Query outbound edges (fromId = node_id)
            outbound_response = self.edges_table.query(
                KeyConditionExpression=Key('fromId').eq(node_id),
                Limit=MAX_NODES_PER_HOP,
            )

            for edge in outbound_response.get('Items', []):
                to_id = edge.get('toId')
                if to_id:
                    # Get the connected node
                    node_response = self.nodes_table.get_item(Key={'nodeId': to_id})
                    if 'Item' in node_response:
                        edge_info = {
                            'fromId': node_id,
                            'toId': to_id,
                            'type': edge.get('type', ''),
                            'fieldName': edge.get('fieldName', ''),
                            'direction': edge.get('direction', 'outbound'),
                        }
                        connected.append((edge_info, node_response['Item']))

            # Query inbound edges using GSI (toId = node_id)
            inbound_response = self.edges_table.query(
                IndexName='toId-index',
                KeyConditionExpression=Key('toId').eq(node_id),
                Limit=MAX_NODES_PER_HOP,
            )

            for edge in inbound_response.get('Items', []):
                from_id = edge.get('fromId')
                if from_id:
                    # Get the connected node
                    node_response = self.nodes_table.get_item(Key={'nodeId': from_id})
                    if 'Item' in node_response:
                        edge_info = {
                            'fromId': from_id,
                            'toId': node_id,
                            'type': edge.get('type', ''),
                            'fieldName': edge.get('fieldName', ''),
                            'direction': 'inbound',
                        }
                        connected.append((edge_info, node_response['Item']))

        except Exception as e:
            LOGGER.warning(f"Error getting connected nodes for {node_id}: {e}")

        return connected


    def merge_and_rank(
        self,
        graph_results: Dict[str, Any],
        vector_results: List[Dict[str, Any]],
        boost_graph_matches: float = 1.5,
    ) -> List[Dict[str, Any]]:
        """
        Merge graph traversal results with vector search results.

        **Requirements: 7.3**
        **Property 10: Filter + Relationship Query Consistency**

        Args:
            graph_results: Results from graph traversal
            vector_results: Results from vector search
            boost_graph_matches: Score boost for graph-matched results

        Returns:
            Merged and ranked list of results
        """
        graph_node_ids = set(graph_results.get('matchingNodeIds', []))
        paths_by_node = {}

        # Index paths by end node for quick lookup
        for path in graph_results.get('paths', []):
            nodes = path.get('nodes', [])
            if nodes:
                end_node = nodes[-1]
                if end_node not in paths_by_node:
                    paths_by_node[end_node] = []
                paths_by_node[end_node].append(path)

        merged_results = []

        for result in vector_results:
            # Extract record ID from result
            record_id = result.get('recordId') or result.get('metadata', {}).get('recordId')

            if not record_id:
                # Try to extract from text or other fields
                merged_results.append(result)
                continue

            # Check if this result matches a graph node
            is_graph_match = record_id in graph_node_ids

            # Calculate combined score
            original_score = result.get('score', 0.5)
            if is_graph_match:
                # Boost score for graph matches
                combined_score = min(1.0, original_score * boost_graph_matches)
                result['graphMatch'] = True
                result['relationshipPaths'] = paths_by_node.get(record_id, [])
            else:
                combined_score = original_score
                result['graphMatch'] = False

            result['combinedScore'] = combined_score
            merged_results.append(result)

        # Sort by combined score descending
        merged_results.sort(key=lambda x: x.get('combinedScore', 0), reverse=True)

        return merged_results

    def _compute_cache_key(
        self,
        query: str,
        user_context: Dict[str, Any],
        filters: Optional[Dict[str, Any]],
        max_depth: int,
    ) -> str:
        """
        Compute cache key for graph traversal results.

        Includes user ID for security (Property 12, 13).

        Args:
            query: Original query
            user_context: User context
            filters: Applied filters
            max_depth: Traversal depth

        Returns:
            Cache key string
        """
        user_id = user_context.get('salesforceUserId', 'anonymous')

        cache_data = {
            'query': query.lower().strip(),
            'userId': user_id,
            'filters': filters or {},
            'maxDepth': max_depth,
        }

        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.sha256(cache_str.encode()).hexdigest()

    def _get_cached_result(
        self,
        cache_key: str,
        user_context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached traversal result if available and valid.

        **Property 13: Path Cache Consistency**

        Args:
            cache_key: Cache key
            user_context: User context for validation

        Returns:
            Cached result or None
        """
        if not self.cache_enabled:
            return None

        try:
            response = self.cache_table.get_item(Key={'pathKey': cache_key})

            if 'Item' not in response:
                return None

            item = response['Item']

            # Check TTL
            ttl = item.get('ttl', 0)
            if ttl < int(time.time()):
                return None

            # Verify user ID matches (security)
            cached_user_id = item.get('userId')
            current_user_id = user_context.get('salesforceUserId')
            if cached_user_id != current_user_id:
                return None

            LOGGER.info(f"Cache hit for key {cache_key[:16]}...")
            return {
                'matchingNodeIds': item.get('nodeIds', []),
                'paths': item.get('paths', []),
                'traversalDepth': item.get('traversalDepth', 0),
                'nodesVisited': item.get('nodesVisited', 0),
            }

        except Exception as e:
            LOGGER.warning(f"Error reading from cache: {e}")
            return None

    def _cache_result(
        self,
        cache_key: str,
        result: Dict[str, Any],
        user_context: Dict[str, Any],
    ) -> None:
        """
        Cache traversal result with TTL.

        **Property 13: Path Cache Consistency**

        Args:
            cache_key: Cache key
            result: Result to cache
            user_context: User context
        """
        if not self.cache_enabled:
            return

        try:
            ttl = int(time.time()) + PATH_CACHE_TTL_SECONDS

            item = {
                'pathKey': cache_key,
                'nodeIds': result.get('matchingNodeIds', []),
                'paths': result.get('paths', []),
                'traversalDepth': result.get('traversalDepth', 0),
                'nodesVisited': result.get('nodesVisited', 0),
                'userId': user_context.get('salesforceUserId', ''),
                'computedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'ttl': ttl,
            }

            self.cache_table.put_item(Item=item)
            LOGGER.info(f"Cached result for key {cache_key[:16]}...")

        except Exception as e:
            LOGGER.warning(f"Error caching result: {e}")

    def invalidate_cache_for_node(self, node_id: str) -> None:
        """
        Invalidate cache entries containing a specific node.

        **Property 12: Cache Invalidation on Sharing Change**

        Note: This is a simplified implementation. In production,
        we would need a more sophisticated approach using secondary
        indexes or a separate cache invalidation queue.

        Args:
            node_id: Node ID to invalidate cache for
        """
        # For POC, we rely on TTL for cache expiration
        # Full implementation would scan and delete matching entries
        LOGGER.info(f"Cache invalidation requested for node {node_id}")

    def _emit_metric(self, metric_name: str, value: float = 1.0) -> None:
        """
        Emit CloudWatch metric for monitoring.

        Args:
            metric_name: Name of the metric
            value: Metric value
        """
        try:
            cloudwatch.put_metric_data(
                Namespace='SalesforceAISearch/Graph',
                MetricData=[
                    {
                        'MetricName': metric_name,
                        'Value': value,
                        'Unit': 'Count' if value == 1.0 else 'Milliseconds',
                    }
                ]
            )
        except Exception as e:
            LOGGER.debug(f"Failed to emit metric {metric_name}: {e}")


# =============================================================================
# Module-level convenience functions
# =============================================================================

_default_retriever: Optional[GraphAwareRetriever] = None


def get_retriever(feature_flags: Optional[Dict[str, bool]] = None) -> GraphAwareRetriever:
    """Get or create the default retriever instance."""
    global _default_retriever
    if _default_retriever is None or feature_flags:
        _default_retriever = GraphAwareRetriever(feature_flags)
    return _default_retriever


def retrieve_with_graph(
    query: str,
    user_context: Dict[str, Any],
    filters: Optional[Dict[str, Any]] = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Dict[str, Any]:
    """
    Convenience function for graph-aware retrieval.

    Args:
        query: User query
        user_context: User authorization context
        filters: Optional filters
        max_depth: Maximum traversal depth

    Returns:
        Retrieval results
    """
    retriever = get_retriever()
    return retriever.retrieve(query, user_context, filters, max_depth)


def merge_results(
    graph_results: Dict[str, Any],
    vector_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convenience function for merging graph and vector results.

    Args:
        graph_results: Graph traversal results
        vector_results: Vector search results

    Returns:
        Merged and ranked results
    """
    retriever = get_retriever()
    return retriever.merge_and_rank(graph_results, vector_results)

