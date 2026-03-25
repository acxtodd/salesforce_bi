"""Tests for Ascendix Search structural validation harness (Task 4.9.10)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from lib.structural_validation import (
    StructuralFixture,
    ValidationReport,
    extract_fixtures,
    assert_object_scope_parity,
    assert_field_allowlist_parity,
    assert_default_column_parity,
    assert_relationship_path_parity,
    validate_structural_parity,
)


def _make_normalized_source() -> dict:
    """Build a representative normalized Ascendix source for testing."""
    return {
        "selected_objects": [
            {
                "api_name": "ascendix__Property__c",
                "label": "Property",
                "is_searchable": True,
                "is_field_filtered": True,
                "field_allowlist": ["Name", "ascendix__City__c"],
                "configured_fields": ["Name", "ascendix__City__c"],
            },
            {
                "api_name": "ascendix__Lease__c",
                "label": "Lease",
                "is_searchable": True,
                "is_field_filtered": False,
                "field_allowlist": [],
                "configured_fields": [],
            },
        ],
        "default_layouts": {
            "ascendix__Property__c": ["Name", "ascendix__City__c"],
            "ascendix__Lease__c": ["Name", "ascendix__StartDate__c"],
        },
        "saved_searches": [
            {
                "Name": "Dallas Property Search",
                "primary_object": "ascendix__Property__c",
                "relationship_paths": ["ascendix__Market__r"],
                "result_columns": ["Name"],
            },
            {
                "Name": "Active Leases",
                "primary_object": "ascendix__Lease__c",
                "relationship_paths": [],
                "result_columns": ["Name"],
            },
        ],
    }


def _make_passing_artifact() -> dict:
    """Build a runtime artifact that passes all structural checks."""
    return {
        "denorm_config": {
            "ascendix__Property__c": {
                "embed_fields": ["Name", "ascendix__City__c"],
                "metadata_fields": [],
                "parents": {},
            },
            "ascendix__Lease__c": {
                "embed_fields": ["Name"],
                "metadata_fields": ["ascendix__StartDate__c"],
                "parents": {},
            },
        },
        "query_scope": {
            "objects": {
                "ascendix__Property__c": {
                    "result_columns": ["Name", "ascendix__City__c"],
                    "relationship_paths": ["ascendix__Market__r"],
                },
                "ascendix__Lease__c": {
                    "result_columns": ["Name", "ascendix__StartDate__c"],
                    "relationship_paths": [],
                },
            },
        },
    }


class TestExtractFixtures:
    def test_extracts_searchable_objects(self):
        fixture = extract_fixtures(_make_normalized_source())
        assert fixture.object_api_names == [
            "ascendix__Lease__c",
            "ascendix__Property__c",
        ]

    def test_extracts_field_allowlists_only_for_filtered(self):
        fixture = extract_fixtures(_make_normalized_source())
        assert "ascendix__Property__c" in fixture.field_allowlists
        assert "ascendix__Lease__c" not in fixture.field_allowlists
        assert fixture.field_allowlists["ascendix__Property__c"] == [
            "Name",
            "ascendix__City__c",
        ]

    def test_extracts_default_columns(self):
        fixture = extract_fixtures(_make_normalized_source())
        assert fixture.default_columns["ascendix__Property__c"] == [
            "Name",
            "ascendix__City__c",
        ]
        assert fixture.default_columns["ascendix__Lease__c"] == [
            "Name",
            "ascendix__StartDate__c",
        ]

    def test_extracts_relationship_paths(self):
        fixture = extract_fixtures(_make_normalized_source())
        assert fixture.relationship_paths["ascendix__Property__c"] == [
            "ascendix__Market__r",
        ]

    def test_extracts_saved_search_names(self):
        fixture = extract_fixtures(_make_normalized_source())
        assert fixture.saved_search_names["ascendix__Property__c"] == [
            "Dallas Property Search",
        ]
        assert fixture.saved_search_names["ascendix__Lease__c"] == ["Active Leases"]


class TestObjectScopeParity:
    def test_passes_when_all_objects_present(self):
        fixture = extract_fixtures(_make_normalized_source())
        result = assert_object_scope_parity(fixture, _make_passing_artifact())
        assert result.passed is True

    def test_fails_when_object_missing(self):
        fixture = extract_fixtures(_make_normalized_source())
        artifact = _make_passing_artifact()
        del artifact["denorm_config"]["ascendix__Lease__c"]
        result = assert_object_scope_parity(fixture, artifact)
        assert result.passed is False
        assert "ascendix__Lease__c" in result.detail


class TestFieldAllowlistParity:
    def test_passes_when_all_fields_present(self):
        fixture = extract_fixtures(_make_normalized_source())
        results = assert_field_allowlist_parity(fixture, _make_passing_artifact())
        assert all(r.passed for r in results)

    def test_fails_when_field_missing(self):
        fixture = extract_fixtures(_make_normalized_source())
        artifact = _make_passing_artifact()
        artifact["denorm_config"]["ascendix__Property__c"]["embed_fields"] = ["Name"]
        results = assert_field_allowlist_parity(fixture, artifact)
        prop_result = [r for r in results if "Property" in r.check][0]
        assert prop_result.passed is False
        assert "ascendix__City__c" in prop_result.detail


class TestDefaultColumnParity:
    def test_passes_when_columns_covered(self):
        fixture = extract_fixtures(_make_normalized_source())
        results = assert_default_column_parity(fixture, _make_passing_artifact())
        assert all(r.passed for r in results)

    def test_fails_when_column_missing(self):
        fixture = extract_fixtures(_make_normalized_source())
        artifact = _make_passing_artifact()
        artifact["query_scope"]["objects"]["ascendix__Property__c"]["result_columns"] = ["Name"]
        results = assert_default_column_parity(fixture, artifact)
        prop_result = [r for r in results if "Property" in r.check][0]
        assert prop_result.passed is False


class TestRelationshipPathParity:
    def test_passes_when_paths_covered(self):
        fixture = extract_fixtures(_make_normalized_source())
        results = assert_relationship_path_parity(fixture, _make_passing_artifact())
        assert all(r.passed for r in results)

    def test_fails_when_path_missing(self):
        fixture = extract_fixtures(_make_normalized_source())
        artifact = _make_passing_artifact()
        artifact["query_scope"]["objects"]["ascendix__Property__c"]["relationship_paths"] = []
        results = assert_relationship_path_parity(fixture, artifact)
        prop_result = [r for r in results if "Property" in r.check][0]
        assert prop_result.passed is False
        assert "ascendix__Market__r" in prop_result.detail


class TestFullValidation:
    def test_full_validation_passes(self):
        report = validate_structural_parity(
            _make_normalized_source(),
            _make_passing_artifact(),
        )
        assert report.passed is True
        assert report.failed_count == 0
        assert "PASS" in report.summary()

    def test_full_validation_reports_failures(self):
        artifact = _make_passing_artifact()
        del artifact["denorm_config"]["ascendix__Lease__c"]
        report = validate_structural_parity(
            _make_normalized_source(),
            artifact,
        )
        assert report.passed is False
        assert report.failed_count > 0
        assert "FAIL" in report.summary()

    def test_report_serializes_to_json(self):
        report = validate_structural_parity(
            _make_normalized_source(),
            _make_passing_artifact(),
        )
        report_json = report.to_json()
        parsed = json.loads(report_json)
        assert parsed["passed"] is True
        assert isinstance(parsed["results"], list)

    def test_harness_usable_by_e2e_tests(self):
        """The harness can attach structural evidence to a detected change."""
        normalized = _make_normalized_source()
        artifact = _make_passing_artifact()
        fixture = extract_fixtures(normalized)
        report = validate_structural_parity(normalized, artifact)

        evidence = {
            "scenario": "field_add",
            "fixture_object_count": len(fixture.object_api_names),
            "fixture_allowlist_count": len(fixture.field_allowlists),
            "validation_report": report.to_dict(),
        }
        assert evidence["validation_report"]["passed"] is True
        assert evidence["fixture_object_count"] == 2
