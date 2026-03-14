"""
Entity Resolver for Graph-Aware Zero-Config Retrieval.

Resolves entity names (Accounts, Contacts, Properties) to Salesforce record IDs
using exact and fuzzy matching against OpenSearch.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 6.1, 6.2, 6.3**
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))


# =============================================================================
# Constants
# =============================================================================

# Default fuzziness for fuzzy matching (AUTO uses Levenshtein distance based on term length)
DEFAULT_FUZZINESS = "AUTO"

# Maximum number of matches to return
DEFAULT_MAX_MATCHES = 10

# Minimum score threshold for matches
DEFAULT_MIN_SCORE = 0.5

# Supported object types for entity resolution
SUPPORTED_OBJECT_TYPES = {
    "Account",
    "Contact",
    "Property__c",
    "ascendix__Property__c",
    "ascendix__Deal__c",
    "ascendix__Lease__c",
    "ascendix__Sale__c",
    "ascendix__Availability__c",
}

# Field mappings for name lookup by object type
NAME_FIELD_MAPPINGS = {
    "Account": ["Name", "name"],
    "Contact": ["Name", "name", "FirstName", "LastName"],
    "Property__c": ["Name", "name", "Address__c", "displayName"],
    "ascendix__Property__c": ["Name", "name", "ascendix__Address__c", "displayName"],
    "ascendix__Deal__c": ["Name", "name", "displayName"],
    "ascendix__Lease__c": ["Name", "name", "displayName"],
    "ascendix__Sale__c": ["Name", "name", "displayName"],
    "ascendix__Availability__c": ["Name", "name", "displayName"],
}

# Recency boost field (for ranking by recency)
RECENCY_FIELD = "LastModifiedDate"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ResolvedEntity:
    """
    Represents a resolved entity from name lookup.

    **Requirements: 6.1, 6.2**

    Attributes:
        record_id: Salesforce record ID (15 or 18 char)
        name: Display name of the record
        object_type: Salesforce object API name
        match_type: Type of match ("exact" or "fuzzy")
        score: Match score (0.0-1.0)
        last_modified: Last modified timestamp (for recency ranking)
    """

    record_id: str
    name: str
    object_type: str
    match_type: str = "exact"
    score: float = 1.0
    last_modified: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate score is in valid range."""
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"Score must be in range [0, 1], got {self.score}")
        if self.match_type not in ("exact", "fuzzy"):
            raise ValueError(
                f"match_type must be 'exact' or 'fuzzy', got {self.match_type}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "record_id": self.record_id,
            "name": self.name,
            "object_type": self.object_type,
            "match_type": self.match_type,
            "score": self.score,
        }
        if self.last_modified:
            result["last_modified"] = self.last_modified
        return result


@dataclass
class ResolutionResult:
    """
    Result of entity resolution for a name query.

    Attributes:
        matches: List of resolved entities
        query_name: Original name query
        object_type: Object type filter used (if any)
        total_matches: Total number of matches found
        latency_ms: Resolution latency in milliseconds
    """

    matches: List[ResolvedEntity] = field(default_factory=list)
    query_name: str = ""
    object_type: Optional[str] = None
    total_matches: int = 0
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "matches": [m.to_dict() for m in self.matches],
            "query_name": self.query_name,
            "object_type": self.object_type,
            "total_matches": self.total_matches,
            "latency_ms": self.latency_ms,
        }

    @property
    def has_matches(self) -> bool:
        """Check if any matches were found."""
        return len(self.matches) > 0

    @property
    def best_match(self) -> Optional[ResolvedEntity]:
        """Get the best (highest scoring) match."""
        return self.matches[0] if self.matches else None

    @property
    def seed_ids(self) -> List[str]:
        """Get list of record IDs for use as seed filters."""
        return [m.record_id for m in self.matches]


# =============================================================================
# OpenSearch Client Protocol (for dependency injection)
# =============================================================================


class OpenSearchClientProtocol(Protocol):
    """Protocol for OpenSearch client to allow dependency injection."""

    def search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a search query against OpenSearch."""
        ...


# =============================================================================
# Entity Resolver Class
# =============================================================================


class EntityResolver:
    """
    Resolves entity names to Salesforce record IDs using OpenSearch.

    **Requirements: 6.1, 6.2, 6.3**

    The Entity Resolver:
    1. Performs exact name matching against OpenSearch
    2. Falls back to fuzzy matching for approximate matches
    3. Ranks results by match score and recency
    4. Returns resolved record IDs for use as seed filters
    """

    def __init__(
        self,
        opensearch_client: Optional[OpenSearchClientProtocol] = None,
        index_name: str = "salesforce-chunks",
        fuzziness: str = DEFAULT_FUZZINESS,
        max_matches: int = DEFAULT_MAX_MATCHES,
        min_score: float = DEFAULT_MIN_SCORE,
    ):
        """
        Initialize the EntityResolver.

        Args:
            opensearch_client: OpenSearch client for queries (optional, lazy init)
            index_name: Name of the OpenSearch index to query
            fuzziness: Fuzziness setting for fuzzy matching
            max_matches: Maximum number of matches to return
            min_score: Minimum score threshold for matches
        """
        self._os_client = opensearch_client
        self.index_name = index_name
        self.fuzziness = fuzziness
        self.max_matches = max_matches
        self.min_score = min_score

    @property
    def os_client(self) -> OpenSearchClientProtocol:
        """Lazy initialization of OpenSearch client."""
        if self._os_client is None:
            self._os_client = self._create_opensearch_client()
        return self._os_client

    def _create_opensearch_client(self) -> Any:
        """Create OpenSearch client from environment configuration."""
        # Import here to avoid circular dependencies
        try:
            from opensearchpy import OpenSearch, RequestsHttpConnection
            from requests_aws4auth import AWS4Auth
            import boto3

            endpoint = os.environ.get("OPENSEARCH_ENDPOINT", "")
            region = os.environ.get("AWS_REGION", "us-west-2")

            if not endpoint:
                LOGGER.warning("OPENSEARCH_ENDPOINT not configured, using mock client")
                return MockOpenSearchClient()

            # Create AWS4Auth for AOSS
            credentials = boto3.Session().get_credentials()
            auth = AWS4Auth(
                credentials.access_key,
                credentials.secret_key,
                region,
                "aoss",
                session_token=credentials.token,
            )

            client = OpenSearch(
                hosts=[{"host": endpoint, "port": 443}],
                http_auth=auth,
                use_ssl=True,
                verify_certs=True,
                connection_class=RequestsHttpConnection,
                timeout=30,
            )
            return client

        except ImportError as e:
            LOGGER.warning(f"OpenSearch dependencies not available: {e}")
            return MockOpenSearchClient()

    def resolve(
        self,
        name: str,
        object_type: Optional[str] = None,
        max_matches: Optional[int] = None,
    ) -> ResolutionResult:
        """
        Resolve a name to record IDs using exact and fuzzy matching.

        **Requirements: 6.1, 6.2, 6.3**

        Args:
            name: Entity name to resolve (e.g., "Jane Doe", "123 Main Street")
            object_type: Optional object type filter (e.g., "Contact", "Property__c")
            max_matches: Optional override for max matches to return

        Returns:
            ResolutionResult with matched entities
        """
        start_time = time.time()
        max_matches = max_matches or self.max_matches

        if not name or not name.strip():
            return ResolutionResult(
                query_name=name,
                object_type=object_type,
                latency_ms=0.0,
            )

        name = name.strip()

        # Validate object type if provided
        if object_type and object_type not in SUPPORTED_OBJECT_TYPES:
            LOGGER.warning(f"Unsupported object type: {object_type}")

        # Try exact matching first
        exact_matches = self._exact_match(name, object_type, max_matches)

        if exact_matches:
            latency_ms = (time.time() - start_time) * 1000
            LOGGER.info(
                f"Entity resolution: exact match for '{name}' found {len(exact_matches)} results"
            )
            return ResolutionResult(
                matches=exact_matches,
                query_name=name,
                object_type=object_type,
                total_matches=len(exact_matches),
                latency_ms=latency_ms,
            )

        # Fall back to fuzzy matching
        fuzzy_matches = self._fuzzy_match(name, object_type, max_matches)

        latency_ms = (time.time() - start_time) * 1000
        LOGGER.info(
            f"Entity resolution: fuzzy match for '{name}' found {len(fuzzy_matches)} results"
        )

        return ResolutionResult(
            matches=fuzzy_matches,
            query_name=name,
            object_type=object_type,
            total_matches=len(fuzzy_matches),
            latency_ms=latency_ms,
        )

    def _exact_match(
        self,
        name: str,
        object_type: Optional[str],
        max_matches: int,
    ) -> List[ResolvedEntity]:
        """
        Perform exact name matching against OpenSearch.

        **Requirements: 6.1**

        Args:
            name: Name to match exactly
            object_type: Optional object type filter
            max_matches: Maximum matches to return

        Returns:
            List of ResolvedEntity with exact matches
        """
        # Build the query
        query = self._build_exact_query(name, object_type, max_matches)

        try:
            response = self.os_client.search(index=self.index_name, body=query)
            return self._parse_search_response(response, "exact")
        except Exception as e:
            LOGGER.error(f"Exact match query failed: {e}")
            return []

    def _fuzzy_match(
        self,
        name: str,
        object_type: Optional[str],
        max_matches: int,
    ) -> List[ResolvedEntity]:
        """
        Perform fuzzy name matching against OpenSearch.

        **Requirements: 6.1, 6.3**

        Args:
            name: Name to match approximately
            object_type: Optional object type filter
            max_matches: Maximum matches to return

        Returns:
            List of ResolvedEntity with fuzzy matches
        """
        # Build the fuzzy query
        query = self._build_fuzzy_query(name, object_type, max_matches)

        try:
            response = self.os_client.search(index=self.index_name, body=query)
            return self._parse_search_response(response, "fuzzy")
        except Exception as e:
            LOGGER.error(f"Fuzzy match query failed: {e}")
            return []

    def _build_exact_query(
        self,
        name: str,
        object_type: Optional[str],
        max_matches: int,
    ) -> Dict[str, Any]:
        """
        Build OpenSearch query for exact name matching.

        **Requirements: 6.1**

        Uses multi_match with type "phrase" for exact matching across
        multiple name fields.
        """
        # Get name fields for the object type
        name_fields = self._get_name_fields(object_type)

        # Build must clauses
        must_clauses: List[Dict[str, Any]] = [
            {
                "multi_match": {
                    "query": name,
                    "fields": name_fields,
                    "type": "phrase",
                    "boost": 2.0,
                }
            }
        ]

        # Add object type filter if specified
        filter_clauses: List[Dict[str, Any]] = []
        if object_type:
            filter_clauses.append({"term": {"sobject": object_type}})

        query: Dict[str, Any] = {
            "size": max_matches,
            "query": {
                "bool": {
                    "must": must_clauses,
                }
            },
            "_source": [
                "recordId",
                "displayName",
                "sobject",
                "LastModifiedDate",
                "name",
                "Name",
            ],
            "sort": [
                {"_score": {"order": "desc"}},
                {"LastModifiedDate": {"order": "desc", "missing": "_last"}},
            ],
        }

        if filter_clauses:
            query["query"]["bool"]["filter"] = filter_clauses

        return query

    def _build_fuzzy_query(
        self,
        name: str,
        object_type: Optional[str],
        max_matches: int,
    ) -> Dict[str, Any]:
        """
        Build OpenSearch query for fuzzy name matching.

        **Requirements: 6.1, 6.3**

        Uses multi_match with fuzziness for approximate matching.
        """
        # Get name fields for the object type
        name_fields = self._get_name_fields(object_type)

        # Build must clauses with fuzzy matching
        must_clauses: List[Dict[str, Any]] = [
            {
                "multi_match": {
                    "query": name,
                    "fields": name_fields,
                    "fuzziness": self.fuzziness,
                    "prefix_length": 1,  # Require first char to match
                    "max_expansions": 50,
                }
            }
        ]

        # Add object type filter if specified
        filter_clauses: List[Dict[str, Any]] = []
        if object_type:
            filter_clauses.append({"term": {"sobject": object_type}})

        query: Dict[str, Any] = {
            "size": max_matches,
            "min_score": self.min_score,
            "query": {
                "bool": {
                    "must": must_clauses,
                }
            },
            "_source": [
                "recordId",
                "displayName",
                "sobject",
                "LastModifiedDate",
                "name",
                "Name",
            ],
            "sort": [
                {"_score": {"order": "desc"}},
                {"LastModifiedDate": {"order": "desc", "missing": "_last"}},
            ],
        }

        if filter_clauses:
            query["query"]["bool"]["filter"] = filter_clauses

        return query

    def _get_name_fields(self, object_type: Optional[str]) -> List[str]:
        """Get name fields to search based on object type."""
        if object_type and object_type in NAME_FIELD_MAPPINGS:
            return NAME_FIELD_MAPPINGS[object_type]

        # Default: search common name fields across all types
        all_fields = set()
        for fields in NAME_FIELD_MAPPINGS.values():
            all_fields.update(fields)
        return list(all_fields)

    def _parse_search_response(
        self,
        response: Dict[str, Any],
        match_type: str,
    ) -> List[ResolvedEntity]:
        """
        Parse OpenSearch response into ResolvedEntity objects.

        **Requirements: 6.1, 6.3**

        Args:
            response: OpenSearch search response
            match_type: Type of match ("exact" or "fuzzy")

        Returns:
            List of ResolvedEntity objects
        """
        matches: List[ResolvedEntity] = []
        seen_ids: set = set()

        hits = response.get("hits", {}).get("hits", [])
        max_score = response.get("hits", {}).get("max_score", 1.0) or 1.0

        for hit in hits:
            source = hit.get("_source", {})
            record_id = source.get("recordId", "")

            # Skip duplicates
            if not record_id or record_id in seen_ids:
                continue
            seen_ids.add(record_id)

            # Get display name
            name = (
                source.get("displayName")
                or source.get("Name")
                or source.get("name")
                or ""
            )

            # Get object type
            object_type = source.get("sobject", "")

            # Normalize score to 0-1 range
            raw_score = hit.get("_score", 0.0)
            normalized_score = min(raw_score / max_score, 1.0) if max_score > 0 else 0.0

            # Get last modified date
            last_modified = source.get("LastModifiedDate")

            matches.append(
                ResolvedEntity(
                    record_id=record_id,
                    name=name,
                    object_type=object_type,
                    match_type=match_type,
                    score=normalized_score,
                    last_modified=last_modified,
                )
            )

        return matches

    def resolve_multiple(
        self,
        names: List[str],
        object_type: Optional[str] = None,
    ) -> Dict[str, ResolutionResult]:
        """
        Resolve multiple names in batch.

        Args:
            names: List of entity names to resolve
            object_type: Optional object type filter

        Returns:
            Dictionary mapping names to their resolution results
        """
        results: Dict[str, ResolutionResult] = {}

        for name in names:
            results[name] = self.resolve(name, object_type)

        return results


# =============================================================================
# Mock OpenSearch Client (for testing)
# =============================================================================


class MockOpenSearchClient:
    """Mock OpenSearch client for testing without actual OpenSearch."""

    def __init__(self, mock_data: Optional[List[Dict[str, Any]]] = None):
        """Initialize with optional mock data."""
        self.mock_data = mock_data or []

    def search(self, index: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Return mock search results."""
        # Extract query text
        query_text = ""
        query_body = body.get("query", {})
        bool_query = query_body.get("bool", {})
        must_clauses = bool_query.get("must", [])

        for clause in must_clauses:
            if "multi_match" in clause:
                query_text = clause["multi_match"].get("query", "").lower()
                break

        # Filter mock data by query text
        hits = []
        for item in self.mock_data:
            name = (
                item.get("displayName", "")
                or item.get("Name", "")
                or item.get("name", "")
            ).lower()

            if query_text in name or name in query_text:
                hits.append(
                    {
                        "_score": 1.0,
                        "_source": item,
                    }
                )

        return {
            "hits": {
                "total": {"value": len(hits)},
                "max_score": 1.0 if hits else 0.0,
                "hits": hits,
            }
        }


# =============================================================================
# Convenience Functions
# =============================================================================


def resolve_entity(
    name: str,
    object_type: Optional[str] = None,
    opensearch_client: Optional[OpenSearchClientProtocol] = None,
) -> ResolutionResult:
    """
    Convenience function to resolve an entity name.

    Args:
        name: Entity name to resolve
        object_type: Optional object type filter
        opensearch_client: Optional OpenSearch client

    Returns:
        ResolutionResult with matched entities
    """
    resolver = EntityResolver(opensearch_client=opensearch_client)
    return resolver.resolve(name, object_type)


def get_seed_ids(
    name: str,
    object_type: Optional[str] = None,
    opensearch_client: Optional[OpenSearchClientProtocol] = None,
) -> List[str]:
    """
    Convenience function to get seed IDs for a name.

    Args:
        name: Entity name to resolve
        object_type: Optional object type filter
        opensearch_client: Optional OpenSearch client

    Returns:
        List of record IDs for use as seed filters
    """
    result = resolve_entity(name, object_type, opensearch_client)
    return result.seed_ids
