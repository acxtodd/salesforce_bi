"""
Vocabulary Cache for Graph-Aware Zero-Config Retrieval.

Caches auto-built vocabulary from Salesforce metadata (Describe API labels,
picklist values, RecordTypes, page layouts) in DynamoDB with 24-hour TTL.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 2.1, 2.3, 2.4, 13.3**
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Environment variables
VOCAB_CACHE_TABLE = os.environ.get("VOCAB_CACHE_TABLE", "salesforce-ai-search-vocab-cache")

# Default TTL: 24 hours
DEFAULT_TTL_HOURS = 24

# Relevance score weights by source (higher = more relevant)
# **Requirements: 2.3, 13.3**
RELEVANCE_SCORES = {
    "layout": 1.0,  # Page layout fields are most relevant
    "entity_name": 0.95,  # Entity names from graph nodes are highly relevant (Task 43)
    "saved_search": 0.9,  # Saved search filter values are highly relevant (Task 40)
    "recordtype": 0.8,  # RecordType names are highly relevant
    "picklist": 0.6,  # Picklist values are moderately relevant
    "describe": 0.4,  # Describe API labels are baseline relevant
}

# Graph nodes table for entity name extraction (Task 43.2)
GRAPH_NODES_TABLE = os.environ.get("GRAPH_NODES_TABLE", "salesforce-ai-search-graph-nodes")

# Entity types to extract from graph nodes
ENTITY_TYPES_FOR_VOCAB = {
    "ascendix__Property__c",
    "Property__c",
    "Account",
    "Contact",
    "ascendix__Deal__c",
    "ascendix__Lease__c",
    "ascendix__Sale__c",
    "ascendix__Availability__c",
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class VocabTerm:
    """
    Represents a vocabulary term with metadata.

    **Requirements: 2.1, 2.3**

    Attributes:
        term: The vocabulary term (lowercase for matching)
        canonical_value: The canonical/display value
        object_name: Salesforce object API name
        field_name: Field API name (if applicable)
        source: Source of the term (describe, picklist, recordtype, layout)
        relevance_score: Relevance score for ranking (0.0-1.0)
        vocab_type: Type of vocabulary (label, picklist, recordtype, geography, etc.)
    """

    term: str
    canonical_value: str
    object_name: str
    field_name: Optional[str] = None
    source: str = "describe"
    relevance_score: float = 0.4
    vocab_type: str = "label"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DynamoDB storage."""
        result = {
            "term": self.term,
            "canonical_value": self.canonical_value,
            "object_name": self.object_name,
            "source": self.source,
            "relevance_score": str(self.relevance_score),  # DynamoDB stores as Decimal
            "vocab_type": self.vocab_type,
        }
        if self.field_name:
            result["field_name"] = self.field_name
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VocabTerm":
        """Create VocabTerm from dictionary."""
        return cls(
            term=data["term"],
            canonical_value=data["canonical_value"],
            object_name=data["object_name"],
            field_name=data.get("field_name"),
            source=data.get("source", "describe"),
            relevance_score=float(data.get("relevance_score", 0.4)),
            vocab_type=data.get("vocab_type", "label"),
        )


@dataclass
class VocabEntry:
    """
    Represents a complete vocabulary entry for DynamoDB.

    Attributes:
        vocab_key: Partition key (format: vocab_type#object_name)
        term: Sort key (the vocabulary term)
        canonical_value: The canonical/display value
        field_name: Field API name (if applicable)
        source: Source of the term
        relevance_score: Relevance score
        ttl: TTL timestamp for expiration
        updated_at: Last update timestamp
    """

    vocab_key: str
    term: str
    canonical_value: str
    field_name: Optional[str] = None
    source: str = "describe"
    relevance_score: float = 0.4
    ttl: int = 0
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format."""
        item = {
            "vocab_key": self.vocab_key,
            "term": self.term,
            "canonical_value": self.canonical_value,
            "source": self.source,
            "relevance_score": str(self.relevance_score),
            "ttl": self.ttl,
            "updated_at": self.updated_at,
        }
        if self.field_name:
            item["field_name"] = self.field_name
        return item

    @classmethod
    def from_item(cls, item: Dict[str, Any]) -> "VocabEntry":
        """Create VocabEntry from DynamoDB item."""
        return cls(
            vocab_key=item["vocab_key"],
            term=item["term"],
            canonical_value=item["canonical_value"],
            field_name=item.get("field_name"),
            source=item.get("source", "describe"),
            relevance_score=float(item.get("relevance_score", 0.4)),
            ttl=int(item.get("ttl", 0)),
            updated_at=item.get("updated_at", ""),
        )


# =============================================================================
# Vocab Cache Class
# =============================================================================


class VocabCache:
    """
    DynamoDB-backed vocabulary cache with TTL support.

    **Requirements: 2.1, 2.3, 2.4**

    Table Schema:
    - Partition Key: vocab_key (String) - Format: vocab_type#object_name
    - Sort Key: term (String) - The vocabulary term (lowercase)
    - Attributes:
      - canonical_value: Display value
      - field_name: Field API name (optional)
      - source: Source of term (describe/picklist/recordtype/layout)
      - relevance_score: Relevance score (0.0-1.0)
      - ttl: Unix timestamp for TTL expiration
      - updated_at: ISO timestamp

    GSI: term-lookup-index
    - Partition Key: term
    - Sort Key: vocab_key
    """

    def __init__(
        self,
        table_name: Optional[str] = None,
        default_ttl_hours: int = DEFAULT_TTL_HOURS,
        dynamodb_resource: Optional[Any] = None,
    ):
        """
        Initialize VocabCache.

        Args:
            table_name: DynamoDB table name (defaults to VOCAB_CACHE_TABLE env var)
            default_ttl_hours: Default TTL in hours (default: 24)
            dynamodb_resource: Optional boto3 DynamoDB resource for testing
        """
        self.table_name = table_name or VOCAB_CACHE_TABLE
        self.default_ttl_hours = default_ttl_hours
        self._dynamodb = dynamodb_resource
        self._table = None

    @property
    def dynamodb(self):
        """Lazy-load DynamoDB resource."""
        if self._dynamodb is None:
            self._dynamodb = boto3.resource("dynamodb")
        return self._dynamodb

    @property
    def table(self):
        """Lazy-load DynamoDB table resource."""
        if self._table is None:
            self._table = self.dynamodb.Table(self.table_name)
        return self._table

    def _make_vocab_key(self, vocab_type: str, object_name: str) -> str:
        """Create the partition key for vocab entries."""
        return f"{vocab_type}#{object_name}"

    def _calculate_ttl(self, ttl_hours: Optional[int] = None) -> int:
        """Calculate TTL timestamp."""
        hours = ttl_hours or self.default_ttl_hours
        return int((datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp())

    def _is_expired(self, ttl: int) -> bool:
        """Check if a TTL timestamp has expired."""
        current_time = int(datetime.now(timezone.utc).timestamp())
        return ttl < current_time

    # =========================================================================
    # Core CRUD Operations
    # =========================================================================

    def get_terms(self, vocab_type: str, object_name: str) -> List[Dict[str, Any]]:
        """
        Get all terms for a vocab type and object.

        **Requirements: 2.1**

        Args:
            vocab_type: Type of vocabulary (label, picklist, recordtype, etc.)
            object_name: Salesforce object API name

        Returns:
            List of term dictionaries with canonical_value, field_name, etc.
        """
        start_time = time.time()
        vocab_key = self._make_vocab_key(vocab_type, object_name)

        try:
            response = self.table.query(
                KeyConditionExpression="vocab_key = :vk",
                ExpressionAttributeValues={":vk": vocab_key},
            )

            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.table.query(
                    KeyConditionExpression="vocab_key = :vk",
                    ExpressionAttributeValues={":vk": vocab_key},
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            # Filter expired items and convert to dicts
            current_time = int(datetime.now(timezone.utc).timestamp())
            valid_items = []
            for item in items:
                ttl = int(item.get("ttl", 0))
                if ttl >= current_time:
                    valid_items.append(
                        {
                            "term": item.get("term"),
                            "canonical_value": item.get("canonical_value"),
                            "field_name": item.get("field_name"),
                            "source": item.get("source", "describe"),
                            "relevance_score": float(item.get("relevance_score", 0.4)),
                        }
                    )

            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.debug(f"get_terms({vocab_type}, {object_name}): {len(valid_items)} terms ({elapsed_ms:.1f}ms)")

            return valid_items

        except ClientError as e:
            LOGGER.error(f"DynamoDB error in get_terms: {e.response['Error']['Message']}")
            return []
        except Exception as e:
            LOGGER.error(f"Error in get_terms: {str(e)}")
            return []

    def put_terms(
        self,
        vocab_type: str,
        object_name: str,
        terms: List[VocabTerm],
        ttl_hours: Optional[int] = None,
    ) -> bool:
        """
        Store multiple terms for a vocab type and object.

        **Requirements: 2.1**

        Args:
            vocab_type: Type of vocabulary
            object_name: Salesforce object API name
            terms: List of VocabTerm objects to store
            ttl_hours: TTL in hours (defaults to default_ttl_hours)

        Returns:
            True if successful, False otherwise
        """
        if not terms:
            return True

        vocab_key = self._make_vocab_key(vocab_type, object_name)
        ttl = self._calculate_ttl(ttl_hours)
        updated_at = datetime.now(timezone.utc).isoformat()

        try:
            with self.table.batch_writer() as batch:
                for term in terms:
                    item = {
                        "vocab_key": vocab_key,
                        "term": term.term.lower(),  # Normalize to lowercase
                        "canonical_value": term.canonical_value,
                        "source": term.source,
                        "relevance_score": str(term.relevance_score),
                        "ttl": ttl,
                        "updated_at": updated_at,
                    }
                    if term.field_name:
                        item["field_name"] = term.field_name
                    batch.put_item(Item=item)

            LOGGER.info(f"Stored {len(terms)} terms for {vocab_type}#{object_name}")
            return True

        except ClientError as e:
            LOGGER.error(f"DynamoDB error in put_terms: {e.response['Error']['Message']}")
            return False
        except Exception as e:
            LOGGER.error(f"Error in put_terms: {str(e)}")
            return False

    def lookup(self, term: str, vocab_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Look up a term in the vocabulary cache.

        **Requirements: 2.1, 2.2**

        Uses the GSI (term-lookup-index) for efficient term lookup across all
        vocab types and objects.

        Args:
            term: The term to look up (case-insensitive)
            vocab_type: Optional vocab type to filter by

        Returns:
            Best matching term dict with highest relevance score, or None
        """
        start_time = time.time()
        term_lower = term.lower()

        try:
            # Query the GSI by term
            response = self.table.query(
                IndexName="term-lookup-index",
                KeyConditionExpression="term = :t",
                ExpressionAttributeValues={":t": term_lower},
            )

            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.table.query(
                    IndexName="term-lookup-index",
                    KeyConditionExpression="term = :t",
                    ExpressionAttributeValues={":t": term_lower},
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            if not items:
                elapsed_ms = (time.time() - start_time) * 1000
                LOGGER.debug(f"lookup({term}): no match ({elapsed_ms:.1f}ms)")
                return None

            # Filter by vocab_type if specified, and filter expired
            current_time = int(datetime.now(timezone.utc).timestamp())
            valid_items = []
            for item in items:
                ttl = int(item.get("ttl", 0))
                if ttl < current_time:
                    continue
                if vocab_type:
                    item_vocab_key = item.get("vocab_key", "")
                    if not item_vocab_key.startswith(f"{vocab_type}#"):
                        continue
                valid_items.append(item)

            if not valid_items:
                return None

            # Return the item with highest relevance score
            best_item = max(valid_items, key=lambda x: float(x.get("relevance_score", 0)))

            # Parse vocab_key to extract vocab_type and object_name
            vocab_key = best_item.get("vocab_key", "")
            parts = vocab_key.split("#", 1)
            result_vocab_type = parts[0] if len(parts) > 0 else ""
            result_object_name = parts[1] if len(parts) > 1 else ""

            elapsed_ms = (time.time() - start_time) * 1000
            LOGGER.debug(f"lookup({term}): found in {result_object_name} ({elapsed_ms:.1f}ms)")

            return {
                "term": best_item.get("term"),
                "canonical_value": best_item.get("canonical_value"),
                "object_name": result_object_name,
                "field_name": best_item.get("field_name"),
                "source": best_item.get("source", "describe"),
                "relevance_score": float(best_item.get("relevance_score", 0.4)),
                "vocab_type": result_vocab_type,
            }

        except ClientError as e:
            LOGGER.error(f"DynamoDB error in lookup: {e.response['Error']['Message']}")
            return None
        except Exception as e:
            LOGGER.error(f"Error in lookup: {str(e)}")
            return None

    def delete_terms(self, vocab_type: str, object_name: str) -> bool:
        """
        Delete all terms for a vocab type and object.

        Args:
            vocab_type: Type of vocabulary
            object_name: Salesforce object API name

        Returns:
            True if successful, False otherwise
        """
        vocab_key = self._make_vocab_key(vocab_type, object_name)

        try:
            # First, query all items with this vocab_key
            response = self.table.query(
                KeyConditionExpression="vocab_key = :vk",
                ExpressionAttributeValues={":vk": vocab_key},
                ProjectionExpression="vocab_key, term",
            )

            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.table.query(
                    KeyConditionExpression="vocab_key = :vk",
                    ExpressionAttributeValues={":vk": vocab_key},
                    ProjectionExpression="vocab_key, term",
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            if not items:
                return True

            # Delete all items
            with self.table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={"vocab_key": item["vocab_key"], "term": item["term"]})

            LOGGER.info(f"Deleted {len(items)} terms for {vocab_type}#{object_name}")
            return True

        except ClientError as e:
            LOGGER.error(f"DynamoDB error in delete_terms: {e.response['Error']['Message']}")
            return False
        except Exception as e:
            LOGGER.error(f"Error in delete_terms: {str(e)}")
            return False

    # =========================================================================
    # Vocabulary Builder
    # =========================================================================

    def build_vocabulary(
        self,
        schema: Dict[str, Any],
        object_name: str,
        ttl_hours: Optional[int] = None,
    ) -> int:
        """
        Build vocabulary from Salesforce schema metadata.

        **Requirements: 2.1, 2.4**

        Extracts terms from:
        - Describe API labels (field labels, object label)
        - Picklist values
        - RecordType names
        - Page layout field labels (if available)

        Args:
            schema: Schema dictionary with fields, recordtypes, layouts
            object_name: Salesforce object API name
            ttl_hours: TTL in hours

        Returns:
            Number of terms stored
        """
        all_terms: List[VocabTerm] = []

        # Extract object label
        object_label = schema.get("label", object_name)
        if object_label:
            all_terms.append(
                VocabTerm(
                    term=object_label.lower(),
                    canonical_value=object_label,
                    object_name=object_name,
                    source="describe",
                    relevance_score=RELEVANCE_SCORES["describe"],
                    vocab_type="object",
                )
            )

        # Extract field labels from Describe API
        describe_terms = self._extract_describe_labels(schema, object_name)
        all_terms.extend(describe_terms)

        # Extract picklist values
        picklist_terms = self._extract_picklist_values(schema, object_name)
        all_terms.extend(picklist_terms)

        # Extract RecordType names
        recordtype_terms = self._extract_recordtype_names(schema, object_name)
        all_terms.extend(recordtype_terms)

        # Extract page layout field labels (if available)
        layout_terms = self._extract_layout_labels(schema, object_name)
        all_terms.extend(layout_terms)

        # Store all terms by vocab_type
        terms_by_type: Dict[str, List[VocabTerm]] = {}
        for term in all_terms:
            if term.vocab_type not in terms_by_type:
                terms_by_type[term.vocab_type] = []
            terms_by_type[term.vocab_type].append(term)

        total_stored = 0
        for vocab_type, terms in terms_by_type.items():
            if self.put_terms(vocab_type, object_name, terms, ttl_hours):
                total_stored += len(terms)

        LOGGER.info(f"Built vocabulary for {object_name}: {total_stored} terms")
        return total_stored

    def _extract_describe_labels(self, schema: Dict[str, Any], object_name: str) -> List[VocabTerm]:
        """
        Extract field labels from Describe API response.

        **Requirements: 2.1**

        Args:
            schema: Schema dictionary with 'fields' list
            object_name: Salesforce object API name

        Returns:
            List of VocabTerm objects for field labels
        """
        terms: List[VocabTerm] = []
        fields = schema.get("fields", [])

        for field_def in fields:
            label = field_def.get("label", "")
            name = field_def.get("name", "")

            if label and name:
                terms.append(
                    VocabTerm(
                        term=label.lower(),
                        canonical_value=label,
                        object_name=object_name,
                        field_name=name,
                        source="describe",
                        relevance_score=RELEVANCE_SCORES["describe"],
                        vocab_type="label",
                    )
                )

                # Also add the API name as a term (for technical users)
                if name.lower() != label.lower():
                    terms.append(
                        VocabTerm(
                            term=name.lower(),
                            canonical_value=name,
                            object_name=object_name,
                            field_name=name,
                            source="describe",
                            relevance_score=RELEVANCE_SCORES["describe"] * 0.8,  # Slightly lower
                            vocab_type="label",
                        )
                    )

        return terms

    def _extract_picklist_values(self, schema: Dict[str, Any], object_name: str) -> List[VocabTerm]:
        """
        Extract picklist values from schema.

        **Requirements: 2.1**

        Args:
            schema: Schema dictionary with 'fields' list
            object_name: Salesforce object API name

        Returns:
            List of VocabTerm objects for picklist values
        """
        terms: List[VocabTerm] = []
        fields = schema.get("fields", [])

        for field_def in fields:
            field_type = field_def.get("type", "").lower()
            field_name = field_def.get("name", "")

            if field_type in ("picklist", "multipicklist"):
                picklist_values = field_def.get("picklistValues", [])

                for pv in picklist_values:
                    # Only include active values
                    if not pv.get("active", True):
                        continue

                    value = pv.get("value", "")
                    label = pv.get("label", value)

                    if value:
                        terms.append(
                            VocabTerm(
                                term=value.lower(),
                                canonical_value=value,
                                object_name=object_name,
                                field_name=field_name,
                                source="picklist",
                                relevance_score=RELEVANCE_SCORES["picklist"],
                                vocab_type="picklist",
                            )
                        )

                        # Also add label if different from value
                        if label and label.lower() != value.lower():
                            terms.append(
                                VocabTerm(
                                    term=label.lower(),
                                    canonical_value=value,  # Map to canonical value
                                    object_name=object_name,
                                    field_name=field_name,
                                    source="picklist",
                                    relevance_score=RELEVANCE_SCORES["picklist"],
                                    vocab_type="picklist",
                                )
                            )

        return terms

    def _extract_recordtype_names(self, schema: Dict[str, Any], object_name: str) -> List[VocabTerm]:
        """
        Extract RecordType names from schema.

        **Requirements: 2.1**

        Args:
            schema: Schema dictionary with 'recordTypeInfos' list
            object_name: Salesforce object API name

        Returns:
            List of VocabTerm objects for RecordType names
        """
        terms: List[VocabTerm] = []
        record_types = schema.get("recordTypeInfos", [])

        for rt in record_types:
            # Skip Master record type
            if rt.get("master", False):
                continue

            name = rt.get("name", "")
            developer_name = rt.get("developerName", "")

            if name:
                terms.append(
                    VocabTerm(
                        term=name.lower(),
                        canonical_value=name,
                        object_name=object_name,
                        field_name="RecordTypeId",
                        source="recordtype",
                        relevance_score=RELEVANCE_SCORES["recordtype"],
                        vocab_type="recordtype",
                    )
                )

                # Also add developer name if different
                if developer_name and developer_name.lower() != name.lower():
                    terms.append(
                        VocabTerm(
                            term=developer_name.lower(),
                            canonical_value=name,  # Map to display name
                            object_name=object_name,
                            field_name="RecordTypeId",
                            source="recordtype",
                            relevance_score=RELEVANCE_SCORES["recordtype"] * 0.9,
                            vocab_type="recordtype",
                        )
                    )

        return terms

    def _extract_layout_labels(self, schema: Dict[str, Any], object_name: str) -> List[VocabTerm]:
        """
        Extract field labels from page layouts.

        **Requirements: 2.1, 2.4**

        Page layout fields have highest relevance as they represent
        fields that users actually see and interact with.

        Args:
            schema: Schema dictionary with 'layouts' list
            object_name: Salesforce object API name

        Returns:
            List of VocabTerm objects for layout field labels
        """
        terms: List[VocabTerm] = []
        layouts = schema.get("layouts", [])

        # Track seen field names to avoid duplicates
        seen_fields: set = set()

        for layout in layouts:
            sections = layout.get("sections", [])

            for section in sections:
                rows = section.get("rows", [])

                for row in rows:
                    items = row.get("layoutItems", [])

                    for item in items:
                        field_name = item.get("field", "")
                        label = item.get("label", "")

                        if field_name and label and field_name not in seen_fields:
                            seen_fields.add(field_name)
                            terms.append(
                                VocabTerm(
                                    term=label.lower(),
                                    canonical_value=label,
                                    object_name=object_name,
                                    field_name=field_name,
                                    source="layout",
                                    relevance_score=RELEVANCE_SCORES["layout"],
                                    vocab_type="label",
                                )
                            )

        return terms

    # =========================================================================
    # Relevance Scoring
    # =========================================================================

    def get_relevance_score(self, source: str) -> float:
        """
        Get relevance score for a term source.

        **Requirements: 2.3, 13.3**

        Scoring hierarchy:
        - layout: 1.0 (highest - fields users see)
        - recordtype: 0.8 (high - important categorization)
        - picklist: 0.6 (medium - valid values)
        - describe: 0.4 (baseline - all fields)

        Args:
            source: Source of the term

        Returns:
            Relevance score (0.0-1.0)
        """
        return RELEVANCE_SCORES.get(source.lower(), 0.4)

    def get_top_terms(
        self,
        object_name: str,
        limit: int = 10,
        vocab_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get top terms by relevance score for an object.

        **Requirements: 2.3, 13.3**

        Args:
            object_name: Salesforce object API name
            limit: Maximum number of terms to return
            vocab_types: Optional list of vocab types to include

        Returns:
            List of term dicts sorted by relevance score (descending)
        """
        all_terms: List[Dict[str, Any]] = []

        # Default vocab types if not specified
        if vocab_types is None:
            vocab_types = ["label", "picklist", "recordtype", "object"]

        for vocab_type in vocab_types:
            terms = self.get_terms(vocab_type, object_name)
            all_terms.extend(terms)

        # Sort by relevance score (descending)
        all_terms.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

        return all_terms[:limit]

    def lookup_with_score(self, term: str, min_score: float = 0.0) -> List[Dict[str, Any]]:
        """
        Look up a term and return all matches above minimum score.

        **Requirements: 2.2, 2.3**

        Args:
            term: The term to look up
            min_score: Minimum relevance score threshold

        Returns:
            List of matching terms sorted by relevance score (descending)
        """
        term_lower = term.lower()

        try:
            # Query the GSI by term
            response = self.table.query(
                IndexName="term-lookup-index",
                KeyConditionExpression="term = :t",
                ExpressionAttributeValues={":t": term_lower},
            )

            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.table.query(
                    IndexName="term-lookup-index",
                    KeyConditionExpression="term = :t",
                    ExpressionAttributeValues={":t": term_lower},
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            # Filter expired and below threshold
            current_time = int(datetime.now(timezone.utc).timestamp())
            valid_items = []

            for item in items:
                ttl = int(item.get("ttl", 0))
                if ttl < current_time:
                    continue

                score = float(item.get("relevance_score", 0))
                if score < min_score:
                    continue

                # Parse vocab_key
                vocab_key = item.get("vocab_key", "")
                parts = vocab_key.split("#", 1)
                vocab_type = parts[0] if len(parts) > 0 else ""
                obj_name = parts[1] if len(parts) > 1 else ""

                valid_items.append(
                    {
                        "term": item.get("term"),
                        "canonical_value": item.get("canonical_value"),
                        "object_name": obj_name,
                        "field_name": item.get("field_name"),
                        "source": item.get("source", "describe"),
                        "relevance_score": score,
                        "vocab_type": vocab_type,
                    }
                )

            # Sort by relevance score (descending)
            valid_items.sort(key=lambda x: x["relevance_score"], reverse=True)

            return valid_items

        except ClientError as e:
            LOGGER.error(f"DynamoDB error in lookup_with_score: {e.response['Error']['Message']}")
            return []
        except Exception as e:
            LOGGER.error(f"Error in lookup_with_score: {str(e)}")
            return []

    # =========================================================================
    # Entity Name Seeding (Task 43.2)
    # =========================================================================

    def seed_entity_names(
        self,
        entities: List[Dict[str, Any]],
        ttl_hours: Optional[int] = None,
    ) -> int:
        """
        Seed vocabulary cache with entity names from graph nodes.

        **Requirements: Task 43.2 - Vocab Cache Auto-Seeding**

        Extracts displayName from graph nodes and stores as entity_name vocab
        type, enabling EntityLinker to resolve entity mentions like
        "123 Main Street" to the correct object type.

        Args:
            entities: List of entity dicts with keys:
                - nodeId: Salesforce record ID
                - displayName: Display name of the entity
                - type: Salesforce object API name (e.g., ascendix__Property__c)
            ttl_hours: TTL in hours (defaults to default_ttl_hours)

        Returns:
            Number of entity name terms stored
        """
        if not entities:
            return 0

        # Group entities by object type
        entities_by_type: Dict[str, List[VocabTerm]] = {}

        for entity in entities:
            display_name = entity.get("displayName") or entity.get("Name") or ""
            object_type = entity.get("type") or entity.get("sobject") or ""
            record_id = entity.get("nodeId") or entity.get("recordId") or ""

            if not display_name or not object_type:
                continue

            # Skip if object type not in our list
            if object_type not in ENTITY_TYPES_FOR_VOCAB:
                continue

            # Create vocab term for the entity name
            term = VocabTerm(
                term=display_name.lower(),
                canonical_value=display_name,
                object_name=object_type,
                field_name=record_id,  # Store record ID in field_name for resolution
                source="graph_node",
                relevance_score=RELEVANCE_SCORES["entity_name"],
                vocab_type="entity_name",
            )

            if object_type not in entities_by_type:
                entities_by_type[object_type] = []
            entities_by_type[object_type].append(term)

        # Store terms grouped by object type
        total_stored = 0
        for object_type, terms in entities_by_type.items():
            if self.put_terms("entity_name", object_type, terms, ttl_hours):
                total_stored += len(terms)

        LOGGER.info(f"Seeded {total_stored} entity names from {len(entities)} graph nodes")
        return total_stored

    def seed_from_graph_nodes_table(
        self,
        object_types: Optional[List[str]] = None,
        ttl_hours: Optional[int] = None,
        max_entities: int = 10000,
    ) -> int:
        """
        Scan graph_nodes DynamoDB table and seed entity names.

        **Requirements: Task 43.2**

        Scans the graph_nodes table for Property, Account, Contact entities
        and seeds their displayName values into the vocab cache.

        Args:
            object_types: List of object types to seed (defaults to ENTITY_TYPES_FOR_VOCAB)
            ttl_hours: TTL in hours
            max_entities: Maximum entities to process (default 10000)

        Returns:
            Number of entity names seeded
        """
        target_types = set(object_types or ENTITY_TYPES_FOR_VOCAB)

        try:
            # Get graph nodes table
            graph_nodes_table = self.dynamodb.Table(GRAPH_NODES_TABLE)

            entities: List[Dict[str, Any]] = []
            scan_kwargs = {
                "ProjectionExpression": "nodeId, displayName, #t",
                "ExpressionAttributeNames": {"#t": "type"},
                "Limit": 1000,  # Batch size
            }

            # Scan table
            while len(entities) < max_entities:
                response = graph_nodes_table.scan(**scan_kwargs)
                items = response.get("Items", [])

                # Filter by object type
                for item in items:
                    if item.get("type") in target_types:
                        entities.append(item)

                    if len(entities) >= max_entities:
                        break

                # Check for more pages
                if "LastEvaluatedKey" not in response:
                    break
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

            # Seed the vocab cache
            return self.seed_entity_names(entities, ttl_hours)

        except ClientError as e:
            LOGGER.error(f"DynamoDB error scanning graph_nodes: {e.response['Error']['Message']}")
            return 0
        except Exception as e:
            LOGGER.error(f"Error seeding from graph_nodes: {str(e)}")
            return 0


# =============================================================================
# Convenience Functions
# =============================================================================


def build_vocabulary_from_schema(
    schema: Dict[str, Any],
    object_name: str,
    vocab_cache: Optional[VocabCache] = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> int:
    """
    Convenience function to build vocabulary from schema.

    **Requirements: 2.1, 2.4**

    Args:
        schema: Schema dictionary
        object_name: Salesforce object API name
        vocab_cache: Optional VocabCache instance
        ttl_hours: TTL in hours

    Returns:
        Number of terms stored
    """
    cache = vocab_cache or VocabCache()
    return cache.build_vocabulary(schema, object_name, ttl_hours)


def lookup_term(
    term: str,
    vocab_type: Optional[str] = None,
    vocab_cache: Optional[VocabCache] = None,
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to look up a term.

    **Requirements: 2.1, 2.2**

    Args:
        term: The term to look up
        vocab_type: Optional vocab type filter
        vocab_cache: Optional VocabCache instance

    Returns:
        Best matching term dict or None
    """
    cache = vocab_cache or VocabCache()
    return cache.lookup(term, vocab_type)


def seed_entity_names_from_graph(
    vocab_cache: Optional[VocabCache] = None,
    object_types: Optional[List[str]] = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    max_entities: int = 10000,
) -> int:
    """
    Convenience function to seed entity names from graph_nodes table.

    **Requirements: Task 43.2 - Vocab Cache Auto-Seeding**

    Scans the graph_nodes DynamoDB table and seeds displayName values
    into the vocab cache for entity resolution.

    Args:
        vocab_cache: Optional VocabCache instance
        object_types: List of object types to seed (defaults to all entity types)
        ttl_hours: TTL in hours
        max_entities: Maximum entities to process

    Returns:
        Number of entity names seeded
    """
    cache = vocab_cache or VocabCache()
    return cache.seed_from_graph_nodes_table(object_types, ttl_hours, max_entities)
