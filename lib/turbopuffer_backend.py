"""Turbopuffer implementation of the SearchBackend protocol.

This is the *only* module in the project that imports the ``turbopuffer``
SDK.  All other application code talks to ``SearchBackend`` from
``lib.search_backend``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from turbopuffer import Turbopuffer

from lib.search_backend import SearchBackend

# -- Filter-dict → Turbopuffer-tuple translation ----------------------------

# Mapping of dict-key suffixes to Turbopuffer comparison operators.
_SUFFIX_TO_OP: list[tuple[str, str]] = [
    ("_gte", "Gte"),
    ("_lte", "Lte"),
    ("_gt", "Gt"),
    ("_lt", "Lt"),
    ("_in", "In"),
    ("_ne", "NotEq"),
]


def _parse_filter_key(key: str) -> tuple[str, str]:
    """Return ``(field_name, operator)`` for a filter dict key.

    >>> _parse_filter_key("total_sf_gte")
    ('total_sf', 'Gte')
    >>> _parse_filter_key("city")
    ('city', 'Eq')
    """
    for suffix, op in _SUFFIX_TO_OP:
        if key.endswith(suffix):
            return key[: -len(suffix)], op
    return key, "Eq"


def translate_filters(filters: dict | None) -> tuple | None:
    """Convert a plain dict of filters into Turbopuffer filter tuples.

    ``None`` / empty dict → ``None`` (no filtering).

    A single-condition dict produces a bare condition tuple; multiple
    conditions are wrapped in ``('And', (...))``.
    """
    if not filters:
        return None

    conditions: list[tuple] = []
    for key, value in filters.items():
        field, op = _parse_filter_key(key)
        conditions.append((field, op, value))

    if len(conditions) == 1:
        return conditions[0]
    return ("And", tuple(conditions))


# -- Backend implementation --------------------------------------------------


class TurbopufferBackend(SearchBackend):
    """SearchBackend backed by the Turbopuffer vector database.

    The API key is read automatically by the SDK from the
    ``TURBOPUFFER_API_KEY`` environment variable.
    """

    def __init__(self, region: str = "gcp-us-central1") -> None:
        self._client = Turbopuffer(region=region)

    # -- helpers -------------------------------------------------------------

    def _ns(self, namespace: str):
        """Return a Turbopuffer namespace handle."""
        return self._client.namespace(namespace)

    # -- SearchBackend interface ---------------------------------------------

    # -- row conversion helpers ----------------------------------------------

    @staticmethod
    def _row_to_dict(
        row: Any,
        include_attributes: list[str] | bool | None,
    ) -> dict[str, Any]:
        """Convert a single SDK row to a plain dict."""
        return_all = include_attributes is True
        doc: dict[str, Any] = {"id": row.id, "dist": getattr(row, "$dist", None)}
        if return_all:
            extras = getattr(row, "model_extra", {}) or {}
            for attr_name, val in extras.items():
                if attr_name != "$dist" and val is not None:
                    doc[attr_name] = val
        elif include_attributes:
            for attr in include_attributes:
                doc[attr] = getattr(row, attr, None)
        return doc

    # -- SearchBackend interface ---------------------------------------------

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
        if vector is None and text_query is None:
            raise ValueError("At least one of 'vector' or 'text_query' must be provided")

        # Hybrid case: Turbopuffer doesn't support Sum(BM25, ANN) in a single
        # query.  Use multi_query + RRF (Reciprocal Rank Fusion) instead.
        if vector is not None and text_query is not None:
            return self._hybrid_search(
                namespace,
                vector=vector,
                text_query=text_query,
                text_field=text_field,
                filters=filters,
                top_k=top_k,
                include_attributes=include_attributes,
            )

        # Single-signal path: BM25-only or ANN-only
        if text_query is not None:
            rank_by: tuple = (text_field, "BM25", text_query)
        else:
            rank_by = ("vector", "ANN", vector)

        # Build kwargs ----------------------------------------------------
        kwargs: dict[str, Any] = {
            "rank_by": rank_by,
            "top_k": top_k,
        }

        tpuf_filters = translate_filters(filters)
        if tpuf_filters is not None:
            kwargs["filters"] = tpuf_filters

        if include_attributes is True:
            kwargs["include_attributes"] = True
        elif include_attributes is not None:
            kwargs["include_attributes"] = include_attributes

        # Execute ---------------------------------------------------------
        result = self._ns(namespace).query(**kwargs)

        return [
            self._row_to_dict(row, include_attributes) for row in result.rows
        ]

    def _hybrid_search(
        self,
        namespace: str,
        *,
        vector: list[float],
        text_query: str,
        text_field: str = "text",
        filters: dict | None = None,
        top_k: int = 10,
        include_attributes: list[str] | None = None,
    ) -> list[dict]:
        """Run BM25 + ANN via multi_query and fuse with RRF."""
        shared: dict[str, Any] = {"top_k": top_k}

        tpuf_filters = translate_filters(filters)
        if tpuf_filters is not None:
            shared["filters"] = tpuf_filters

        if include_attributes is True:
            shared["include_attributes"] = True
        elif include_attributes is not None:
            shared["include_attributes"] = include_attributes

        bm25_query = {"rank_by": (text_field, "BM25", text_query), **shared}
        ann_query = {"rank_by": ("vector", "ANN", vector), **shared}

        response = self._ns(namespace).multi_query(queries=[bm25_query, ann_query])

        bm25_rows = response.results[0].rows or []
        ann_rows = response.results[1].rows or []

        # RRF: score = sum(1 / (k + rank)) across lists, k=60 is standard
        k = 60
        scores: dict[str, float] = defaultdict(float)
        row_map: dict[str, Any] = {}

        for rank, row in enumerate(bm25_rows):
            scores[row.id] += 1.0 / (k + rank + 1)
            row_map[row.id] = row
        for rank, row in enumerate(ann_rows):
            scores[row.id] += 1.0 / (k + rank + 1)
            row_map[row.id] = row  # ANN row overwrites; attrs are the same

        ranked_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]

        return [
            {**self._row_to_dict(row_map[rid], include_attributes), "dist": scores[rid]}
            for rid in ranked_ids
        ]

    def aggregate(
        self,
        namespace: str,
        *,
        filters: dict | None = None,
        aggregate: str = "count",
        aggregate_field: str | None = None,
        group_by: str | None = None,
    ) -> dict:
        if aggregate in ("sum", "avg") and aggregate_field is None:
            raise ValueError(f"aggregate_field is required for '{aggregate}'")

        # Turbopuffer has no native server-side aggregation, so we fetch
        # matching rows and compute in Python.
        attrs_to_fetch: list[str] = []
        if aggregate_field:
            attrs_to_fetch.append(aggregate_field)
        if group_by:
            attrs_to_fetch.append(group_by)
        # Deduplicate while preserving order.
        attrs_to_fetch = list(dict.fromkeys(attrs_to_fetch))

        # Turbopuffer requires rank_by for every query.  For aggregations we
        # want to scan all matching docs regardless of text.  Strategy:
        # 1. Try BM25 on the 'text' field with common tokens.
        # 2. If that returns nothing, fall back to a zero-vector ANN scan
        #    (requires knowing dimensionality — we use 8 as a safe minimum
        #    and let Turbopuffer return what it can).
        tpuf_filters = translate_filters(filters)

        base_kwargs: dict[str, Any] = {"top_k": 10_000}
        if tpuf_filters is not None:
            base_kwargs["filters"] = tpuf_filters
        if attrs_to_fetch:
            base_kwargs["include_attributes"] = attrs_to_fetch

        # Attempt 1: BM25 broad scan
        try:
            result = self._ns(namespace).query(
                rank_by=("text", "BM25", "a the is of and to in for"),
                **base_kwargs,
            )
            if result.rows:
                pass  # success — fall through
            else:
                raise ValueError("empty BM25 result")
        except Exception:
            # Attempt 2: zero-vector ANN scan (catches all docs)
            try:
                result = self._ns(namespace).query(
                    rank_by=("vector", "ANN", [0.0] * 1024),
                    **base_kwargs,
                )
            except Exception:
                # Attempt 3: smaller vector dimension
                result = self._ns(namespace).query(
                    rank_by=("vector", "ANN", [0.0] * 8),
                    **base_kwargs,
                )

        # Compute aggregation locally ------------------------------------
        if group_by:
            groups: dict[str, dict] = defaultdict(lambda: {"_values": []})
            for row in result.rows:
                key = str(getattr(row, group_by, "__none__"))
                if aggregate_field:
                    val = getattr(row, aggregate_field, None)
                    if val is not None:
                        groups[key]["_values"].append(val)
                    else:
                        groups[key].setdefault("_values", [])
                else:
                    groups[key]["_values"].append(1)

            out_groups: dict[str, dict] = {}
            for key, info in groups.items():
                values = info["_values"]
                out_groups[key] = self._compute_agg(aggregate, values)
            return {"groups": out_groups}

        # Un-grouped
        values: list = []
        for row in result.rows:
            if aggregate_field:
                val = getattr(row, aggregate_field, None)
                if val is not None:
                    values.append(val)
            else:
                values.append(1)

        return self._compute_agg(aggregate, values)

    @staticmethod
    def _compute_agg(aggregate: str, values: list) -> dict:
        if aggregate == "count":
            return {"count": len(values)}
        elif aggregate == "sum":
            return {"sum": sum(values)}
        elif aggregate == "avg":
            return {"avg": sum(values) / len(values) if values else 0}
        else:
            raise ValueError(f"Unsupported aggregate: {aggregate}")

    def upsert(
        self,
        namespace: str,
        *,
        documents: list[dict],
        distance_metric: str = "cosine_distance",
        schema: dict | None = None,
    ) -> None:
        if not documents:
            return
        kwargs: dict[str, Any] = {
            "distance_metric": distance_metric,
            "upsert_rows": documents,
        }
        if schema:
            kwargs["schema"] = schema
        self._ns(namespace).write(**kwargs)

    def delete(self, namespace: str, *, ids: list[str]) -> None:
        if not ids:
            return
        self._ns(namespace).write(deletes=ids)

    def warm(self, namespace: str) -> None:
        """Issue a lightweight query to warm the namespace cache."""
        try:
            self._ns(namespace).query(
                rank_by=("text", "BM25", " "),
                top_k=1,
            )
        except Exception:
            # Warm is best-effort — swallow errors (e.g. empty namespace).
            pass
