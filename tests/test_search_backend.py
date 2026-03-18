"""Tests for the SearchBackend protocol and TurbopufferBackend implementation.

Unit tests (filter translation, ABC enforcement) run without network.
Integration tests require a live Turbopuffer API key and are skipped
automatically when ``TURBOPUFFER_API_KEY`` is not set.
"""

from __future__ import annotations

import os
import time
import pytest

from lib.search_backend import SearchBackend
from lib.turbopuffer_backend import (
    TurbopufferBackend,
    translate_filters,
    _parse_filter_key,
)


# =========================================================================
# Unit tests — no network required
# =========================================================================


class TestSearchBackendABC:
    """The ABC must not be directly instantiable."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            SearchBackend()  # type: ignore[abstract]

    def test_subclass_missing_methods(self):
        """A subclass that omits abstract methods can't be instantiated."""

        class Incomplete(SearchBackend):
            pass

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_complete(self):
        """A subclass implementing all methods can be instantiated."""

        class Complete(SearchBackend):
            def search(self, namespace, **kw):
                return []

            def aggregate(self, namespace, **kw):
                return {}

            def upsert(self, namespace, **kw):
                return None

            def delete(self, namespace, **kw):
                return None

            def warm(self, namespace):
                return None

        obj = Complete()
        assert isinstance(obj, SearchBackend)


class TestTurbopufferBackendImplementsABC:
    """TurbopufferBackend must satisfy the SearchBackend interface."""

    def test_is_subclass(self):
        assert issubclass(TurbopufferBackend, SearchBackend)

    def test_has_all_methods(self):
        required = {"search", "aggregate", "upsert", "delete", "warm"}
        for method_name in required:
            assert hasattr(TurbopufferBackend, method_name)
            assert callable(getattr(TurbopufferBackend, method_name))


class TestParseFilterKey:
    """_parse_filter_key correctly splits suffix → (field, operator)."""

    @pytest.mark.parametrize(
        "key, expected",
        [
            ("city", ("city", "Eq")),
            ("total_sf_gte", ("total_sf", "Gte")),
            ("total_sf_lte", ("total_sf", "Lte")),
            ("price_gt", ("price", "Gt")),
            ("price_lt", ("price", "Lt")),
            ("property_type_in", ("property_type", "In")),
            ("status_ne", ("status", "NotEq")),
            # Key that looks like it has a suffix but is actually part of the name
            ("begin_date", ("begin_date", "Eq")),
        ],
    )
    def test_parse(self, key: str, expected: tuple[str, str]):
        assert _parse_filter_key(key) == expected


class TestTranslateFilters:
    """translate_filters converts dicts to Turbopuffer filter tuples."""

    def test_none(self):
        assert translate_filters(None) is None

    def test_empty_dict(self):
        assert translate_filters({}) is None

    def test_single_eq(self):
        assert translate_filters({"city": "Dallas"}) == ("city", "Eq", "Dallas")

    def test_single_gte(self):
        assert translate_filters({"total_sf_gte": 10000}) == ("total_sf", "Gte", 10000)

    def test_single_in(self):
        result = translate_filters({"property_type_in": ["Office", "Industrial"]})
        assert result == ("property_type", "In", ["Office", "Industrial"])

    def test_multiple_conditions(self):
        result = translate_filters(
            {
                "city": "Dallas",
                "total_sf_gte": 10000,
                "property_type_in": ["Office", "Industrial"],
            }
        )
        assert result is not None
        assert result[0] == "And"
        conditions = result[1]
        assert len(conditions) == 3
        assert ("city", "Eq", "Dallas") in conditions
        assert ("total_sf", "Gte", 10000) in conditions
        assert ("property_type", "In", ["Office", "Industrial"]) in conditions

    def test_ne_suffix(self):
        assert translate_filters({"status_ne": "closed"}) == ("status", "NotEq", "closed")

    def test_lt_suffix(self):
        assert translate_filters({"price_lt": 500}) == ("price", "Lt", 500)

    def test_lte_suffix(self):
        assert translate_filters({"price_lte": 500}) == ("price", "Lte", 500)

    def test_gt_suffix(self):
        assert translate_filters({"price_gt": 100}) == ("price", "Gt", 100)


class TestSearchValidation:
    """search() must require at least one of vector or text_query."""

    def test_search_requires_vector_or_text(self):
        """Should raise ValueError when neither vector nor text_query given."""

        # We can't call search on TurbopufferBackend without a real API key,
        # so we test the validation logic by instantiating with a dummy.
        # The constructor creates a Turbopuffer client which doesn't validate
        # the key eagerly, so this is fine.
        backend = TurbopufferBackend.__new__(TurbopufferBackend)
        # Manually set the client attribute so the object is usable
        from unittest.mock import MagicMock

        backend._client = MagicMock()

        with pytest.raises(ValueError, match="At least one of"):
            backend.search("test_ns")

    def test_aggregate_requires_field_for_sum(self):
        backend = TurbopufferBackend.__new__(TurbopufferBackend)
        from unittest.mock import MagicMock

        backend._client = MagicMock()

        with pytest.raises(ValueError, match="aggregate_field is required"):
            backend.aggregate("test_ns", aggregate="sum")

    def test_aggregate_requires_field_for_avg(self):
        backend = TurbopufferBackend.__new__(TurbopufferBackend)
        from unittest.mock import MagicMock

        backend._client = MagicMock()

        with pytest.raises(ValueError, match="aggregate_field is required"):
            backend.aggregate("test_ns", aggregate="avg")

    def test_hybrid_uses_multi_query_with_rrf(self):
        """Hybrid search must use multi_query (BM25 + ANN) with RRF fusion."""
        from unittest.mock import MagicMock

        backend = TurbopufferBackend.__new__(TurbopufferBackend)
        backend._client = MagicMock()

        mock_ns = MagicMock()

        # Build mock rows with id and $dist attributes
        def _make_row(rid, dist=0.5):
            row = MagicMock()
            row.id = rid
            setattr(row, "$dist", dist)
            row.model_extra = {}
            return row

        bm25_result = MagicMock()
        bm25_result.rows = [_make_row("r1"), _make_row("r2"), _make_row("r3")]
        ann_result = MagicMock()
        ann_result.rows = [_make_row("r2"), _make_row("r3"), _make_row("r4")]

        mock_response = MagicMock()
        mock_response.results = [bm25_result, ann_result]
        mock_ns.multi_query.return_value = mock_response
        backend._client.namespace.return_value = mock_ns

        vector = [0.1] * 8
        results = backend.search("ns", vector=vector, text_query="test query")

        # multi_query must be called (not query)
        mock_ns.multi_query.assert_called_once()
        mock_ns.query.assert_not_called()

        call_kwargs = mock_ns.multi_query.call_args[1]
        queries = call_kwargs["queries"]
        assert len(queries) == 2
        assert queries[0]["rank_by"] == ("text", "BM25", "test query")
        assert queries[1]["rank_by"] == ("vector", "ANN", vector)

        # RRF fusion: r2 and r3 appear in both lists, should rank higher
        result_ids = [r["id"] for r in results]
        assert "r2" in result_ids
        assert "r3" in result_ids
        # r2 and r3 are in both lists → higher RRF score than r1 or r4
        r2_idx = result_ids.index("r2")
        r1_idx = result_ids.index("r1") if "r1" in result_ids else len(result_ids)
        assert r2_idx < r1_idx, "r2 (in both lists) should rank above r1 (BM25-only)"

    def test_bm25_only_rank_by_is_bare_tuple(self):
        """BM25-only search should produce a bare rank_by, not wrapped in Sum."""
        from unittest.mock import MagicMock

        backend = TurbopufferBackend.__new__(TurbopufferBackend)
        backend._client = MagicMock()

        mock_ns = MagicMock()
        mock_result = MagicMock()
        mock_result.rows = []
        mock_ns.query.return_value = mock_result
        backend._client.namespace.return_value = mock_ns

        backend.search("ns", text_query="hello")

        call_kwargs = mock_ns.query.call_args[1]
        assert call_kwargs["rank_by"] == ("text", "BM25", "hello")

    def test_ann_only_rank_by_is_bare_tuple(self):
        """ANN-only search should produce a bare rank_by, not wrapped in Sum."""
        from unittest.mock import MagicMock

        backend = TurbopufferBackend.__new__(TurbopufferBackend)
        backend._client = MagicMock()

        mock_ns = MagicMock()
        mock_result = MagicMock()
        mock_result.rows = []
        mock_ns.query.return_value = mock_result
        backend._client.namespace.return_value = mock_ns

        vector = [0.5] * 4
        backend.search("ns", vector=vector)

        call_kwargs = mock_ns.query.call_args[1]
        assert call_kwargs["rank_by"] == ("vector", "ANN", vector)


# =========================================================================
# No-import guard
# =========================================================================


class TestNoDirectTpufImport:
    """Verify turbopuffer is NOT imported outside of turbopuffer_backend.py."""

    def test_search_backend_module_has_no_tpuf_import(self):
        import lib.search_backend as mod
        import inspect

        source = inspect.getsource(mod)
        assert "turbopuffer" not in source
        assert "tpuf" not in source


# =========================================================================
# Integration tests — require TURBOPUFFER_API_KEY
# =========================================================================

_INTEGRATION_NS = "_test_search_backend"

_skip_no_key = pytest.mark.skipif(
    not os.environ.get("TURBOPUFFER_API_KEY"),
    reason="TURBOPUFFER_API_KEY not set — skipping live integration test",
)


@_skip_no_key
class TestTurbopufferIntegration:
    """Live round-trip: upsert → search → aggregate → delete."""

    @pytest.fixture(autouse=True)
    def backend(self):
        self.be = TurbopufferBackend()
        # Clean up namespace before and after the test.
        try:
            self.be._ns(_INTEGRATION_NS).delete_all()
        except Exception:
            pass
        yield
        try:
            self.be._ns(_INTEGRATION_NS).delete_all()
        except Exception:
            pass

    def test_round_trip(self):
        docs = [
            {
                "id": "prop-001",
                "vector": [0.1] * 8,
                "text": "Downtown Dallas office tower",
                "city": "Dallas",
                "total_sf": 50000,
                "property_type": "Office",
            },
            {
                "id": "prop-002",
                "vector": [0.2] * 8,
                "text": "Houston industrial warehouse",
                "city": "Houston",
                "total_sf": 120000,
                "property_type": "Industrial",
            },
            {
                "id": "prop-003",
                "vector": [0.15] * 8,
                "text": "Dallas suburban office park",
                "city": "Dallas",
                "total_sf": 30000,
                "property_type": "Office",
            },
        ]

        # -- Upsert (with schema declaring 'text' as full-text searchable) --
        self.be.upsert(
            _INTEGRATION_NS,
            documents=docs,
            distance_metric="cosine_distance",
            schema={"text": {"type": "string", "full_text_search": True}},
        )

        # Give Turbopuffer a moment to index.
        time.sleep(2)

        # -- Warm -------------------------------------------------------------
        self.be.warm(_INTEGRATION_NS)

        # -- Vector search (ANN) ---------------------------------------------
        results = self.be.search(
            _INTEGRATION_NS,
            vector=[0.1] * 8,
            top_k=3,
            include_attributes=["city", "total_sf", "property_type"],
        )
        assert len(results) > 0
        assert all("id" in r and "dist" in r for r in results)
        # The closest vector to [0.1]*8 should be prop-001.
        assert results[0]["id"] == "prop-001"

        # -- BM25 text search ------------------------------------------------
        text_results = self.be.search(
            _INTEGRATION_NS,
            text_query="Dallas office",
            top_k=3,
            include_attributes=["city", "property_type"],
        )
        assert len(text_results) > 0
        # At least one Dallas result should appear.
        ids = [r["id"] for r in text_results]
        assert "prop-001" in ids or "prop-003" in ids

        # -- Filtered search --------------------------------------------------
        filtered = self.be.search(
            _INTEGRATION_NS,
            text_query="office",
            filters={"city": "Dallas"},
            top_k=10,
            include_attributes=["city"],
        )
        for r in filtered:
            assert r.get("city") == "Dallas"

        # -- Aggregate (count) ------------------------------------------------
        agg_count = self.be.aggregate(
            _INTEGRATION_NS,
            aggregate="count",
        )
        assert agg_count["count"] == 3

        # -- Aggregate (sum) --------------------------------------------------
        agg_sum = self.be.aggregate(
            _INTEGRATION_NS,
            aggregate="sum",
            aggregate_field="total_sf",
        )
        assert agg_sum["sum"] == 200000

        # -- Aggregate (avg) grouped ------------------------------------------
        agg_grouped = self.be.aggregate(
            _INTEGRATION_NS,
            aggregate="avg",
            aggregate_field="total_sf",
            group_by="city",
        )
        assert "groups" in agg_grouped
        assert "Dallas" in agg_grouped["groups"]
        assert "Houston" in agg_grouped["groups"]
        assert agg_grouped["groups"]["Dallas"]["avg"] == 40000
        assert agg_grouped["groups"]["Houston"]["avg"] == 120000

        # -- Delete -----------------------------------------------------------
        self.be.delete(_INTEGRATION_NS, ids=["prop-001", "prop-002", "prop-003"])

        time.sleep(2)

        # After delete, search should return nothing (or very few).
        post_delete = self.be.search(
            _INTEGRATION_NS,
            text_query="Dallas",
            top_k=10,
            include_attributes=["city"],
        )
        remaining_ids = {r["id"] for r in post_delete}
        assert "prop-001" not in remaining_ids
        assert "prop-002" not in remaining_ids
        assert "prop-003" not in remaining_ids
