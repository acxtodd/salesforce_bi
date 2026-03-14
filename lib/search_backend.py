"""Vendor-agnostic search backend protocol.

Defines the abstract interface that all search backend implementations must
satisfy.  Application code imports only this module — never the concrete
backend — so the system stays portable across vector-database vendors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class SearchBackend(ABC):
    """Platform-level search abstraction.

    Every method takes an explicit *namespace* string so a single backend
    instance can serve multiple tenants / object-type namespaces.
    """

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    @abstractmethod
    def search(
        self,
        namespace: str,
        *,
        vector: list[float] | None = None,
        text_query: str | None = None,
        text_field: str = "text",
        filters: dict | None = None,
        top_k: int = 10,
        include_attributes: list[str] | None = None,
    ) -> list[dict]:
        """Return up to *top_k* matching documents.

        At least one of *vector* (ANN) or *text_query* (BM25) must be
        provided.  When both are given the backend should perform hybrid
        ranking.

        *filters* is a plain dict of field-value pairs with optional
        operator suffixes:

            {"city": "Dallas", "total_sf_gte": 10000,
             "property_type_in": ["Office", "Industrial"]}

        Supported suffixes: ``_gte``, ``_lte``, ``_gt``, ``_lt``,
        ``_in``, ``_ne``.  No suffix means equality.

        Returns a list of dicts, each containing at minimum ``"id"`` and
        ``"dist"`` keys, plus any requested attribute key-value pairs.
        """
        ...

    # ------------------------------------------------------------------
    # Aggregate
    # ------------------------------------------------------------------
    @abstractmethod
    def aggregate(
        self,
        namespace: str,
        *,
        filters: dict | None = None,
        aggregate: str = "count",
        aggregate_field: str | None = None,
        group_by: str | None = None,
    ) -> dict:
        """Compute an aggregate (*count*, *sum*, or *avg*) over matching
        documents, optionally grouped by *group_by*.

        *aggregate_field* is required when *aggregate* is ``"sum"`` or
        ``"avg"``.

        Returns a dict.  Un-grouped results::

            {"count": 42}
            {"sum": 123456.78}

        Grouped results::

            {"groups": {"Dallas": {"count": 12}, "Houston": {"count": 30}}}
        """
        ...

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    @abstractmethod
    def upsert(
        self,
        namespace: str,
        *,
        documents: list[dict],
        distance_metric: str = "cosine_distance",
        schema: dict | None = None,
    ) -> None:
        """Insert or update documents.

        Each element of *documents* must contain ``"id"`` and ``"vector"``
        keys; all other keys are stored as attributes.

        *schema* is an optional dict declaring attribute types and indexing
        behaviour.  Pass ``{"text": {"type": "string", "full_text_search": True}}``
        to enable BM25 full-text search on the ``text`` field.  The schema
        only needs to be sent on the first write (the backend remembers it).
        """
        ...

    @abstractmethod
    def delete(self, namespace: str, *, ids: list[str]) -> None:
        """Delete documents by ID."""
        ...

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @abstractmethod
    def warm(self, namespace: str) -> None:
        """Warm the namespace cache (e.g. a lightweight query)."""
        ...
