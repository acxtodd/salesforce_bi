"""Unit tests for scripts/validate_data.py — no live credentials needed."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root + lambda + scripts to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from validate_data import (
    CheckResult,
    DataValidator,
    _is_reference_value,
    expected_parent_keys,
    format_report,
    write_telemetry_artifact,
)


# ===================================================================
# expected_parent_keys
# ===================================================================


class TestExpectedParentKeys:
    def test_ascendix_naming(self):
        keys = expected_parent_keys(
            "ascendix__Property__c", ["Name", "ascendix__City__c"]
        )
        assert keys == ["property_name", "property_city"]

    def test_standard_fields(self):
        keys = expected_parent_keys(
            "ascendix__Tenant__c", ["Name", "Industry"]
        )
        assert keys == ["tenant_name", "tenant_industry"]

    def test_empty_parent_list(self):
        keys = expected_parent_keys("ascendix__Property__c", [])
        assert keys == []

    def test_state_field(self):
        keys = expected_parent_keys(
            "ascendix__Property__c",
            ["Name", "ascendix__City__c", "ascendix__State__c"],
        )
        assert keys == ["property_name", "property_city", "property_state"]


# ===================================================================
# _is_reference_value
# ===================================================================


class TestIsReferenceValue:
    def test_sf_15_char_id(self):
        assert _is_reference_value("a0y000000000001") is True

    def test_sf_18_char_id(self):
        assert _is_reference_value("a0y000000000001AAA") is True

    def test_short_string(self):
        assert _is_reference_value("Dallas") is False

    def test_non_string(self):
        assert _is_reference_value(12345) is False

    def test_none(self):
        assert _is_reference_value(None) is False


# ===================================================================
# CheckResult
# ===================================================================


class TestCheckResult:
    def test_pass_status(self):
        r = CheckResult(name="Test", status="PASS", message="ok")
        assert r.status == "PASS"
        assert r.duration_ms == 0.0

    def test_fail_status(self):
        r = CheckResult(name="Test", status="FAIL", message="bad")
        assert r.status == "FAIL"

    def test_skip_status(self):
        r = CheckResult(name="Test", status="SKIP", message="skipped")
        assert r.status == "SKIP"

    def test_details_default_empty(self):
        r = CheckResult(name="Test", status="PASS", message="ok")
        assert r.details == {}

    def test_details_with_data(self):
        r = CheckResult(name="Test", status="PASS", message="ok",
                        details={"count": 42})
        assert r.details["count"] == 42


# ===================================================================
# format_report
# ===================================================================


class TestFormatReport:
    def test_correct_alignment(self):
        results = [
            CheckResult("Namespace exists", "PASS", "100 docs found", duration_ms=12),
            CheckResult("BM25 search", "FAIL", "0 results", duration_ms=5),
            CheckResult("System fields", "SKIP", "No config", duration_ms=0),
        ]
        report = format_report(results, "org_test")
        assert "=== Turbopuffer Data Validation ===" in report
        assert "Namespace: org_test" in report
        assert "[PASS]" in report
        assert "[FAIL]" in report
        assert "[SKIP]" in report

    def test_pass_fail_skip_counts(self):
        results = [
            CheckResult("A", "PASS", "ok"),
            CheckResult("B", "PASS", "ok"),
            CheckResult("C", "FAIL", "bad"),
            CheckResult("D", "SKIP", "no"),
        ]
        report = format_report(results, "ns")
        assert "2 PASSED" in report
        assert "1 FAILED" in report
        assert "1 SKIPPED" in report

    def test_all_pass_summary(self):
        results = [
            CheckResult("A", "PASS", "ok"),
            CheckResult("B", "PASS", "ok"),
        ]
        report = format_report(results, "ns")
        assert "2 PASSED" in report
        assert "0 FAILED" in report

    def test_warn_in_summary(self):
        results = [
            CheckResult("A", "WARN", "slow"),
        ]
        report = format_report(results, "ns")
        assert "1 WARNED" in report


class TestTelemetryArtifact:
    def test_write_telemetry_artifact(self, tmp_path):
        path = tmp_path / "telemetry.json"
        results = [CheckResult("BM25 search", "PASS", "10 results", duration_ms=12.3)]
        events = [{"operation": "search", "billing": {"billable_logical_bytes_queried": 10}}]

        write_telemetry_artifact(
            str(path),
            namespace="org_test",
            query_text="Dallas office",
            results=results,
            telemetry_events=events,
        )

        payload = path.read_text()
        assert "org_test" in payload
        assert "Dallas office" in payload
        assert "billable_logical_bytes_queried" in payload


# ===================================================================
# Latency threshold logic
# ===================================================================


class TestLatencyThreshold:
    def _make_validator(self, threshold=50.0):
        backend = MagicMock()
        backend.search.return_value = [{"id": "doc1"}]
        return DataValidator(
            namespace="test_ns",
            backend=backend,
            latency_threshold=threshold,
        )

    def test_pass_below_threshold(self):
        validator = self._make_validator(threshold=1000.0)
        result = validator._check_warm_latency()
        assert result.status == "PASS"

    def test_fail_above_double_threshold(self):
        # Use a mock that sleeps to force high latency
        backend = MagicMock()

        def slow_search(*args, **kwargs):
            import time
            time.sleep(0.15)
            return [{"id": "doc1"}]

        backend.search.side_effect = slow_search
        validator = DataValidator(
            namespace="test_ns", backend=backend, latency_threshold=50.0,
        )
        result = validator._check_warm_latency()
        # 150ms > 2*50ms = FAIL
        assert result.status == "FAIL"


# ===================================================================
# SF count comparison
# ===================================================================


class TestObjectTypeCountsFallback:
    """Verify aggregate-cap fallback in object type counts."""

    def test_missing_object_recovered_by_per_object_aggregate(self):
        """If group-by aggregate omits an object, per-object fallback fills it."""
        backend = MagicMock()
        # Group-by aggregate only returns account (property missing)
        backend.aggregate.side_effect = [
            {"groups": {"account": {"count": 100}}},  # group-by call
            {"count": 50},  # per-object fallback for property
        ]
        backend.search.return_value = [{"id": "d1"}]

        config = {
            "ascendix__Property__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            "Account": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_object_type_counts()
        # property was recovered via fallback, so not missing
        assert "Missing" not in result.message
        assert "property: 50" in result.message

    def test_truly_empty_object_still_fails(self):
        """If per-object fallback also returns 0, object is truly missing."""
        backend = MagicMock()
        backend.aggregate.side_effect = [
            {"groups": {"account": {"count": 100}}},
            {"count": 0},  # property truly empty
        ]
        backend.search.return_value = [{"id": "d1"}]

        config = {
            "ascendix__Property__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            "Account": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_object_type_counts()
        assert result.status == "FAIL"
        assert "Missing" in result.message
        assert "property" in result.message


class TestSFCountComparison:
    def test_matching_counts_pass(self):
        backend = MagicMock()
        backend.aggregate.return_value = {
            "groups": {"property": {"count": 100}}
        }
        backend.search.return_value = [{"id": "doc1"}]
        sf = MagicMock()
        sf.query.return_value = {"totalSize": 100}

        config = {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": [],
                "parents": {},
            }
        }
        validator = DataValidator(
            namespace="ns", backend=backend, config=config, sf_client=sf,
        )
        result = validator._check_object_type_counts()
        assert result.status == "PASS"

    def test_mismatched_counts_fail(self):
        backend = MagicMock()
        backend.aggregate.return_value = {
            "groups": {"property": {"count": 90}}
        }
        backend.search.return_value = [{"id": "doc1"}]
        sf = MagicMock()
        sf.query.return_value = {"totalSize": 100}

        config = {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": [],
                "parents": {},
            }
        }
        validator = DataValidator(
            namespace="ns", backend=backend, config=config, sf_client=sf,
        )
        result = validator._check_object_type_counts()
        assert result.status == "FAIL"
        assert "SF count mismatch" in result.message

    def test_no_sf_client_skips_comparison(self):
        backend = MagicMock()
        backend.aggregate.return_value = {
            "groups": {"property": {"count": 100}}
        }
        backend.search.return_value = [{"id": "doc1"}]

        config = {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": [],
                "parents": {},
            }
        }
        validator = DataValidator(
            namespace="ns", backend=backend, config=config,
        )
        result = validator._check_object_type_counts()
        # No SF client, so only TP counts matter; should PASS if count > 0
        assert result.status == "PASS"


# ===================================================================
# Parent field violation detection
# ===================================================================


class TestParentFieldViolation:
    def _make_validator(self, docs, sf_client=None):
        backend = MagicMock()
        backend.search.return_value = docs
        config = {
            "ascendix__Lease__c": {
                "embed_fields": ["Name"],
                "metadata_fields": [],
                "parents": {
                    "ascendix__Property__c": ["Name", "ascendix__City__c"],
                },
            }
        }
        return DataValidator(
            namespace="ns", backend=backend, config=config,
            sf_client=sf_client,
        )

    def test_all_keys_present_pass(self):
        docs = [
            {"id": "d1", "property_name": "Plaza", "property_city": "Dallas"},
            {"id": "d2", "property_name": "Tower", "property_city": "Houston"},
        ]
        validator = self._make_validator(docs)
        result = validator._check_parent_fields()
        assert result.status == "PASS"

    def test_partial_keys_consistent_null_warns(self):
        # Same field consistently null — likely null on source parent
        docs = [
            {"id": "d1", "property_name": "Plaza", "property_city": None},
            {"id": "d2", "property_name": "Tower", "property_city": None},
        ]
        validator = self._make_validator(docs)
        result = validator._check_parent_fields()
        assert result.status == "WARN"
        assert "partial" in result.message.lower()
        assert "null source" in result.message.lower()

    def test_partial_keys_inconsistent_fails(self):
        # Different fields missing on different docs — possible defect
        docs = [
            {"id": "d1", "property_name": "Plaza", "property_city": None},
            {"id": "d2", "property_name": None, "property_city": "Dallas"},
        ]
        validator = self._make_validator(docs)
        result = validator._check_parent_fields()
        assert result.status == "FAIL"
        assert "inconsistent" in result.message.lower()

    def test_all_keys_null_orphan_no_violation(self):
        # Orphan record: all parent keys null — consistent, not a violation
        docs = [
            {"id": "d1", "property_name": None, "property_city": None},
            {"id": "d2", "property_name": "Plaza", "property_city": "Dallas"},
        ]
        validator = self._make_validator(docs)
        result = validator._check_parent_fields()
        assert result.status == "PASS"

    def test_zero_docs_with_parent_keys_warns_sparse(self):
        # All docs have null parent keys — sparse source, not denorm defect
        docs = [
            {"id": "d1", "property_name": None, "property_city": None},
            {"id": "d2", "property_name": None, "property_city": None},
        ]
        validator = self._make_validator(docs)
        result = validator._check_parent_fields()
        assert result.status == "WARN"
        assert "0/" in result.message
        assert "sparse" in result.message.lower()

    def test_no_docs_warns_not_loaded(self):
        # No docs for this object type at all
        validator = self._make_validator([])
        result = validator._check_parent_fields()
        assert result.status == "WARN"
        assert "not loaded" in result.message.lower()

    def test_sparse_with_sf_client_stale_index(self):
        # Sampled SF records have populated FKs — stale index
        sf = MagicMock()
        sf.query.side_effect = [
            {
                "records": [
                    {"Id": "d1", "ascendix__Property__c": "a0y000000000001"},
                    {"Id": "d2", "ascendix__Property__c": None},
                ]
            },
            {"totalSize": 100},  # COUNT() WHERE FK != null
            {"totalSize": 500},  # COUNT() total
        ]
        docs = [
            {"id": "d1", "property_name": None, "property_city": None},
            {"id": "d2", "property_name": None, "property_city": None},
        ]
        validator = self._make_validator(docs, sf_client=sf)
        result = validator._check_parent_fields()
        assert result.status == "WARN"
        assert "stale" in result.message.lower()
        assert "reindex" in result.message.lower()

    def test_sparse_with_sf_client_low_incidence_not_stale(self):
        # Sampled docs are null, but other org rows have FKs populated.
        sf = MagicMock()
        sf.query.side_effect = [
            {
                "records": [
                    {"Id": "d1", "ascendix__Property__c": None},
                    {"Id": "d2", "ascendix__Property__c": None},
                ]
            },
            {"totalSize": 5},  # COUNT() WHERE FK != null
            {"totalSize": 500},  # COUNT() total
        ]
        docs = [
            {"id": "d1", "property_name": None, "property_city": None},
            {"id": "d2", "property_name": None, "property_city": None},
        ]
        validator = self._make_validator(docs, sf_client=sf)
        result = validator._check_parent_fields()
        assert result.status == "WARN"
        assert "low-incidence" in result.message.lower()
        assert "stale" not in result.message.lower()

    def test_sparse_with_sf_client_truly_sparse(self):
        # SF also shows 0 FKs populated — truly sparse source
        sf = MagicMock()
        sf.query.side_effect = [
            {
                "records": [
                    {"Id": "d1", "ascendix__Property__c": None},
                ]
            },
            {"totalSize": 0},  # COUNT() WHERE FK != null
            {"totalSize": 500},  # COUNT() total
        ]
        docs = [
            {"id": "d1", "property_name": None, "property_city": None},
        ]
        validator = self._make_validator(docs, sf_client=sf)
        result = validator._check_parent_fields()
        assert result.status == "WARN"
        assert "sparse" in result.message.lower()
        assert "SF has 0/" in result.message


# ===================================================================
# Metadata filter verification
# ===================================================================


class TestMetadataFilter:
    def test_all_docs_match_pass(self):
        backend = MagicMock()
        # First call: sample doc; second call: filtered results
        backend.search.side_effect = [
            [{"id": "d1", "city": "Dallas", "status": "Active"}],
            [
                {"id": "d1", "city": "Dallas", "status": "Active"},
                {"id": "d2", "city": "Dallas", "status": "Active"},
            ],
        ]
        config = {
            "ascendix__Property__c": {
                "embed_fields": ["ascendix__City__c", "ascendix__Status__c"],
                "metadata_fields": [],
                "parents": {},
            }
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_metadata_filter()
        assert result.status == "PASS"

    def test_doc_mismatch_fail(self):
        backend = MagicMock()
        backend.search.side_effect = [
            [{"id": "d1", "city": "Dallas", "status": "Active"}],
            [
                {"id": "d1", "city": "Dallas", "status": "Active"},
                {"id": "d2", "city": "Houston", "status": "Active"},
            ],
        ]
        config = {
            "ascendix__Property__c": {
                "embed_fields": ["ascendix__City__c", "ascendix__Status__c"],
                "metadata_fields": [],
                "parents": {},
            }
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_metadata_filter()
        assert result.status == "FAIL"

    def test_fk_id_values_excluded(self):
        backend = MagicMock()
        # Sample doc: only has an FK-shaped value, not a real string
        backend.search.side_effect = [
            [{"id": "d1", "property": "a0y000000000001AAA", "name": "Plaza"}],
            [{"id": "d1", "name": "Plaza"}],
        ]
        config = {
            "ascendix__Lease__c": {
                "embed_fields": ["ascendix__Property__c", "Name"],
                "metadata_fields": [],
                "parents": {},
            }
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_metadata_filter()
        # Should use "name" (string) not "property" (FK ID)
        assert result.status == "PASS"


# ===================================================================
# Hybrid attribute matching
# ===================================================================


# ===================================================================
# Per-object search coverage
# ===================================================================


class TestPerObjectSearch:
    def test_all_objects_covered_pass(self):
        backend = MagicMock()
        backend.search.return_value = [{"id": "d1"}]
        config = {
            "ascendix__Property__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            "ascendix__Lease__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_per_object_search()
        assert result.status == "PASS"
        assert "2/2" in result.message

    def test_one_object_empty_fail(self):
        backend = MagicMock()
        backend.search.side_effect = [
            [{"id": "d1"}],  # Property has docs
            [],               # Lease has none
        ]
        config = {
            "ascendix__Property__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
            "ascendix__Lease__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_per_object_search()
        assert result.status == "FAIL"
        assert "lease" in result.message

    def test_no_config_skip(self):
        backend = MagicMock()
        validator = DataValidator(namespace="ns", backend=backend)
        result = validator._check_per_object_search()
        assert result.status == "SKIP"

    def test_search_exception_treated_as_empty(self):
        backend = MagicMock()
        backend.search.side_effect = Exception("timeout")
        config = {
            "ascendix__Property__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}},
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_per_object_search()
        assert result.status == "FAIL"
        assert "property" in result.message


# ===================================================================
# Numeric/date filter verification
# ===================================================================


class TestNumericDateFilter:
    def test_numeric_filter_pass(self):
        backend = MagicMock()
        # First call: sample docs; second call: filtered results
        backend.search.side_effect = [
            [{"id": "d1", "totalbuildingarea": 50000}],
            [
                {"id": "d1", "totalbuildingarea": 50000},
                {"id": "d2", "totalbuildingarea": 60000},
            ],
        ]
        config = {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": ["ascendix__TotalBuildingArea__c"],
                "parents": {},
            }
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_numeric_date_filter()
        assert result.status == "PASS"
        assert "numeric" in result.message
        assert "totalbuildingarea" in result.message

    def test_numeric_filter_violation_fail(self):
        backend = MagicMock()
        backend.search.side_effect = [
            [{"id": "d1", "totalbuildingarea": 50000}],
            [
                {"id": "d1", "totalbuildingarea": 50000},
                {"id": "d2", "totalbuildingarea": 10},  # below floor
            ],
        ]
        config = {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": ["ascendix__TotalBuildingArea__c"],
                "parents": {},
            }
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_numeric_date_filter()
        assert result.status == "FAIL"
        assert "violation" in result.message

    def test_date_filter_pass(self):
        backend = MagicMock()
        # First call: sample docs with date value; second call: filtered results
        backend.search.side_effect = [
            [{"id": "d1", "termexpirationdate": "2025-06-15"}],
            [
                {"id": "d1", "termexpirationdate": "2025-06-15"},
                {"id": "d2", "termexpirationdate": "2026-01-01"},
            ],
        ]
        config = {
            "ascendix__Lease__c": {
                "embed_fields": ["Name"],
                "metadata_fields": ["ascendix__TermExpirationDate__c"],
                "parents": {},
            }
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_numeric_date_filter()
        assert result.status == "PASS"
        assert "date" in result.message
        assert "termexpirationdate" in result.message

    def test_date_filter_violation_fail(self):
        backend = MagicMock()
        backend.search.side_effect = [
            [{"id": "d1", "termexpirationdate": "2025-06-15"}],
            [
                {"id": "d1", "termexpirationdate": "2025-06-15"},
                {"id": "d2", "termexpirationdate": "2020-01-01"},  # before floor
            ],
        ]
        config = {
            "ascendix__Lease__c": {
                "embed_fields": ["Name"],
                "metadata_fields": ["ascendix__TermExpirationDate__c"],
                "parents": {},
            }
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_numeric_date_filter()
        assert result.status == "FAIL"
        assert "violation" in result.message

    def test_both_numeric_and_date_pass(self):
        backend = MagicMock()
        # Numeric sample + filter, then date sample + filter
        backend.search.side_effect = [
            [{"id": "d1", "totalbuildingarea": 50000}],
            [{"id": "d1", "totalbuildingarea": 50000}],
            [{"id": "d2", "termexpirationdate": "2025-06-15"}],
            [{"id": "d2", "termexpirationdate": "2025-06-15"}],
        ]
        config = {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": ["ascendix__TotalBuildingArea__c"],
                "parents": {},
            },
            "ascendix__Lease__c": {
                "embed_fields": ["Name"],
                "metadata_fields": ["ascendix__TermExpirationDate__c"],
                "parents": {},
            },
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_numeric_date_filter()
        assert result.status == "PASS"
        assert "numeric" in result.message
        assert "date" in result.message

    def test_no_numeric_or_date_fields_warn(self):
        backend = MagicMock()
        config = {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": [],
                "parents": {},
            }
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_numeric_date_filter()
        assert result.status == "WARN"

    def test_no_config_skip(self):
        backend = MagicMock()
        validator = DataValidator(namespace="ns", backend=backend)
        result = validator._check_numeric_date_filter()
        assert result.status == "SKIP"

    def test_all_sample_values_null_skips_to_next_object(self):
        backend = MagicMock()
        backend.search.side_effect = [
            [{"id": "d1", "totalbuildingarea": None}],
        ]
        config = {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": ["ascendix__TotalBuildingArea__c"],
                "parents": {},
            }
        }
        validator = DataValidator(namespace="ns", backend=backend, config=config)
        result = validator._check_numeric_date_filter()
        assert result.status == "WARN"


class TestHybridSearch:
    def test_attr_match_pass(self):
        backend = MagicMock()
        backend.search.return_value = [
            {"id": "d1", "object_type": "lease", "property_city": "Dallas"},
        ]
        config = {
            "ascendix__Lease__c": {
                "embed_fields": ["Name"],
                "metadata_fields": [],
                "parents": {
                    "ascendix__Property__c": ["ascendix__City__c"],
                },
            }
        }
        validator = DataValidator(
            namespace="ns", backend=backend, config=config,
            query_text="office lease Dallas",
        )

        # Mock Bedrock
        import io, json
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.invoke_model.return_value = {
                "body": io.BytesIO(
                    json.dumps({"embedding": [0.1] * 1024}).encode()
                ),
            }
            result = validator._check_hybrid_search()

        assert result.status == "PASS"
        assert "Dallas" in str(result.details)

    def test_no_attr_match_fail(self):
        backend = MagicMock()
        backend.search.return_value = [
            {"id": "d1", "object_type": "lease", "property_city": "Houston"},
        ]
        config = {
            "ascendix__Lease__c": {
                "embed_fields": [],
                "metadata_fields": [],
                "parents": {
                    "ascendix__Property__c": ["ascendix__City__c"],
                },
            }
        }
        validator = DataValidator(
            namespace="ns", backend=backend, config=config,
            query_text="office in Dallas",
        )

        import io, json
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.invoke_model.return_value = {
                "body": io.BytesIO(
                    json.dumps({"embedding": [0.1] * 1024}).encode()
                ),
            }
            result = validator._check_hybrid_search()

        # "Dallas" not in "Houston", "office" matches "office" via object_type? No.
        # query_terms: ["office", "dallas"], neither in "Houston" or "lease"
        assert result.status == "FAIL"

    def test_bedrock_unavailable_skip(self):
        backend = MagicMock()
        config = {
            "ascendix__Lease__c": {
                "embed_fields": [],
                "metadata_fields": [],
                "parents": {},
            }
        }
        validator = DataValidator(
            namespace="ns", backend=backend, config=config,
        )

        with patch("boto3.client", side_effect=Exception("No AWS creds")):
            result = validator._check_hybrid_search()

        assert result.status == "SKIP"
        assert "Bedrock unavailable" in result.message
