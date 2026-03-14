"""
Graph Attribute Filter for Schema-Driven Filtering.

Filters graph nodes by attribute values before vector search.
Supports exact-match filtering for picklist fields and numeric comparisons.

**Feature: zero-config-schema-discovery**
**Requirements: 4.1, 4.2, 4.3, 4.4, 4.5**
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key, Attr

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Environment variables
GRAPH_NODES_TABLE = os.environ.get("GRAPH_NODES_TABLE", "salesforce-ai-search-graph-nodes")

# Configuration
MAX_FILTER_RESULTS = int(os.getenv("MAX_FILTER_RESULTS", "500"))


class GraphAttributeFilter:
    """
    Filter graph nodes by attribute values.

    **Requirements: 4.1, 4.2, 4.3**

    Supports:
    - Exact-match filtering for picklist fields
    - Numeric comparison filtering ($gt, $lt, $gte, $lte)
    - Multiple filters with AND logic
    """

    def __init__(self, nodes_table: Optional[Any] = None):
        """
        Initialize with DynamoDB nodes table.

        Args:
            nodes_table: DynamoDB Table resource (optional, will create if not provided)
        """
        self._nodes_table = nodes_table
        self._dynamodb = None

    @property
    def dynamodb(self):
        """Lazy initialization of DynamoDB resource."""
        if self._dynamodb is None:
            self._dynamodb = boto3.resource("dynamodb")
        return self._dynamodb

    @property
    def nodes_table(self):
        """Lazy initialization of nodes table."""
        if self._nodes_table is None:
            self._nodes_table = self.dynamodb.Table(GRAPH_NODES_TABLE)
        return self._nodes_table

    def query_by_attributes(
        self,
        object_type: str,
        filters: Optional[Dict[str, Any]] = None,
        numeric_filters: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[str]:
        """
        Query graph nodes matching attribute filters.

        **Requirements: 4.1, 4.2, 4.3**

        Args:
            object_type: Salesforce object type (e.g., 'ascendix__Property__c')
            filters: Exact match filters {field: value}
            numeric_filters: Comparison filters {field: {$gt/$lt/$gte/$lte: value}}

        Returns:
            List of matching node IDs
        """
        start_time = time.time()

        # Build filter expression
        filter_expression = self._build_filter_expression(filters, numeric_filters)

        try:
            # Query by object type using GSI
            query_params = {
                "IndexName": "type-createdAt-index",
                "KeyConditionExpression": Key("type").eq(object_type),
                "Limit": MAX_FILTER_RESULTS,
            }

            if filter_expression:
                query_params["FilterExpression"] = filter_expression

            response = self.nodes_table.query(**query_params)
            items = response.get("Items", [])

            # Handle pagination if needed
            while "LastEvaluatedKey" in response and len(items) < MAX_FILTER_RESULTS:
                query_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.nodes_table.query(**query_params)
                items.extend(response.get("Items", []))

            # Extract node IDs
            node_ids = [item["nodeId"] for item in items if "nodeId" in item]

            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.info(
                f"Graph filter query completed: "
                f"type={object_type}, "
                f"filters={len(filters or {})}, "
                f"numeric_filters={len(numeric_filters or {})}, "
                f"results={len(node_ids)}, "
                f"latency={elapsed_ms:.0f}ms"
            )

            return node_ids

        except Exception as e:
            LOGGER.error(f"Graph filter query failed: {e}")
            raise

    def _build_filter_expression(
        self,
        filters: Optional[Dict[str, Any]] = None,
        numeric_filters: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Optional[Any]:
        """
        Build DynamoDB filter expression from filters.

        **Requirements: 4.2, 4.3**

        Args:
            filters: Exact match filters
            numeric_filters: Numeric comparison filters

        Returns:
            Combined filter expression or None
        """
        conditions = []

        # Build exact-match conditions for picklist fields
        if filters:
            for field_name, value in filters.items():
                if value is not None:
                    # Access nested attribute in 'attributes' map
                    attr_path = Attr(f"attributes.{field_name}")
                    conditions.append(attr_path.eq(value))

        # Build numeric comparison conditions
        if numeric_filters:
            for field_name, comparisons in numeric_filters.items():
                if isinstance(comparisons, dict):
                    for operator, value in comparisons.items():
                        attr_path = Attr(f"attributes.{field_name}")
                        condition = self._build_numeric_condition(
                            attr_path, operator, value
                        )
                        if condition is not None:
                            conditions.append(condition)

        # Combine all conditions with AND logic
        if not conditions:
            return None

        combined = conditions[0]
        for condition in conditions[1:]:
            combined = combined & condition

        return combined

    def _build_numeric_condition(
        self, attr_path: Attr, operator: str, value: Any
    ) -> Optional[Any]:
        """
        Build numeric comparison condition.

        **Requirements: 4.3**

        Args:
            attr_path: DynamoDB Attr for the field
            operator: Comparison operator ($gt, $lt, $gte, $lte)
            value: Comparison value

        Returns:
            DynamoDB condition or None
        """
        # Normalize operator
        op = operator.lower().lstrip("$")

        if op == "gt":
            return attr_path.gt(value)
        elif op == "lt":
            return attr_path.lt(value)
        elif op == "gte":
            return attr_path.gte(value)
        elif op == "lte":
            return attr_path.lte(value)
        elif op == "eq":
            return attr_path.eq(value)
        elif op == "ne":
            return attr_path.ne(value)
        else:
            LOGGER.warning(f"Unknown numeric operator: {operator}")
            return None

    def filter_nodes(
        self,
        nodes: List[Dict[str, Any]],
        filters: Optional[Dict[str, Any]] = None,
        numeric_filters: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Filter a list of nodes in-memory by attribute values.

        Useful for post-filtering when nodes are already loaded.

        **Requirements: 4.1, 4.2, 4.3**

        Args:
            nodes: List of node dictionaries
            filters: Exact match filters {field: value}
            numeric_filters: Comparison filters {field: {$gt/$lt/$gte/$lte: value}}

        Returns:
            List of matching nodes
        """
        if not filters and not numeric_filters:
            return nodes

        matching = []

        for node in nodes:
            attributes = node.get("attributes", {})

            # Check exact-match filters
            if filters:
                if not self._matches_exact_filters(attributes, filters):
                    continue

            # Check numeric filters
            if numeric_filters:
                if not self._matches_numeric_filters(attributes, numeric_filters):
                    continue

            matching.append(node)

        return matching

    def _matches_exact_filters(
        self, attributes: Dict[str, Any], filters: Dict[str, Any]
    ) -> bool:
        """
        Check if attributes match all exact-match filters.

        **Requirements: 4.2**

        Args:
            attributes: Node attributes
            filters: Exact match filters

        Returns:
            True if all filters match
        """
        for field_name, expected_value in filters.items():
            if expected_value is None:
                continue

            actual_value = attributes.get(field_name)

            # Handle case-insensitive string comparison
            if isinstance(expected_value, str) and isinstance(actual_value, str):
                if actual_value.lower() != expected_value.lower():
                    return False
            elif actual_value != expected_value:
                return False

        return True

    def _matches_numeric_filters(
        self, attributes: Dict[str, Any], numeric_filters: Dict[str, Dict[str, Any]]
    ) -> bool:
        """
        Check if attributes match all numeric filters.

        **Requirements: 4.3**

        Args:
            attributes: Node attributes
            numeric_filters: Numeric comparison filters

        Returns:
            True if all filters match
        """
        for field_name, comparisons in numeric_filters.items():
            actual_value = attributes.get(field_name)

            if actual_value is None:
                return False

            # Convert to number if needed
            try:
                actual_num = float(actual_value)
            except (ValueError, TypeError):
                return False

            if not isinstance(comparisons, dict):
                continue

            for operator, expected_value in comparisons.items():
                try:
                    expected_num = float(expected_value)
                except (ValueError, TypeError):
                    continue

                op = operator.lower().lstrip("$")

                if op == "gt" and not (actual_num > expected_num):
                    return False
                elif op == "lt" and not (actual_num < expected_num):
                    return False
                elif op == "gte" and not (actual_num >= expected_num):
                    return False
                elif op == "lte" and not (actual_num <= expected_num):
                    return False
                elif op == "eq" and not (actual_num == expected_num):
                    return False
                elif op == "ne" and not (actual_num != expected_num):
                    return False

        return True


def apply_graph_filter(
    object_type: str,
    filters: Optional[Dict[str, Any]] = None,
    numeric_filters: Optional[Dict[str, Dict[str, Any]]] = None,
    nodes_table: Optional[Any] = None,
) -> List[str]:
    """
    Convenience function to apply graph attribute filtering.

    **Requirements: 4.1, 4.2, 4.3**

    Args:
        object_type: Salesforce object type
        filters: Exact match filters
        numeric_filters: Numeric comparison filters
        nodes_table: Optional DynamoDB table

    Returns:
        List of matching node IDs
    """
    graph_filter = GraphAttributeFilter(nodes_table=nodes_table)
    return graph_filter.query_by_attributes(
        object_type=object_type,
        filters=filters,
        numeric_filters=numeric_filters,
    )
