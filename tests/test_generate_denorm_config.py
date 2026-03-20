"""Tests for the denormalization config generator (Task 4.6.5.1).

Exercises the scoring pipeline, Ascendix Search signal harvesting,
cross-object join supplementation, and object discovery — all using
mocks, no Salesforce connection required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.generate_denorm_config import (
    FieldScore,
    ObjectMetadata,
    SalesforceHarvester,
    build_config_for_object,
    build_mock_metadata,
    _is_excluded_direct_field,
    _resolve_relationship_to_ref_field,
    MockParentFetcher,
    WEIGHT_ASCENDIX_RESULT_COL,
    WEIGHT_ASCENDIX_FILTER,
    THRESHOLD_EMBED,
    THRESHOLD_METADATA,
)


# =========================================================================
# FieldScore T5 weight tests
# =========================================================================


class TestFieldScoreT5:
    """Verify Ascendix Search (T5) weight integration in FieldScore."""

    def test_ascendix_result_boosts_score(self):
        fs = FieldScore("SomeField__c")
        fs.ascendix_result_appearances = 1
        assert fs.score == WEIGHT_ASCENDIX_RESULT_COL

    def test_ascendix_filter_boosts_score(self):
        fs = FieldScore("SomeField__c")
        fs.ascendix_filter_appearances = 1
        assert fs.score == WEIGHT_ASCENDIX_FILTER

    def test_combined_t5_pushes_into_embed(self):
        """A field with both AX result + filter appearances should reach embed threshold."""
        fs = FieldScore("SomeField__c")
        fs.ascendix_result_appearances = 1  # 12
        fs.ascendix_filter_appearances = 1  # 10
        assert fs.score >= THRESHOLD_EMBED

    def test_provenance_str_includes_ax_signals(self):
        fs = FieldScore("SomeField__c")
        fs.ascendix_result_appearances = 2
        fs.ascendix_filter_appearances = 1
        prov = fs.provenance_str
        assert "ax_result(2)" in prov
        assert "ax_filter(1)" in prov


# =========================================================================
# Relationship name resolution (__r → __c)
# =========================================================================


class TestResolveRelationshipToRefField:
    """Verify that __r relationship paths and other formats resolve correctly."""

    SAMPLE_REF_FIELDS = {
        "ascendix__Property__c": "ascendix__Property__c",
        "ascendix__Client__c": "Account",
        "AccountId": "Account",
    }

    def test_direct_ref_field_match(self):
        result = _resolve_relationship_to_ref_field(
            "ascendix__Property__c", self.SAMPLE_REF_FIELDS
        )
        assert result == "ascendix__Property__c"

    def test_custom_r_suffix_resolves_to_c(self):
        """ascendix__Property__r should resolve to ascendix__Property__c."""
        result = _resolve_relationship_to_ref_field(
            "ascendix__Property__r", self.SAMPLE_REF_FIELDS
        )
        assert result == "ascendix__Property__c"

    def test_standard_relationship_resolves_to_id(self):
        """Account should resolve to AccountId."""
        result = _resolve_relationship_to_ref_field(
            "Account", self.SAMPLE_REF_FIELDS
        )
        assert result == "AccountId"

    def test_unknown_relationship_returns_none(self):
        result = _resolve_relationship_to_ref_field(
            "ascendix__Nonexistent__r", self.SAMPLE_REF_FIELDS
        )
        assert result is None

    def test_client_r_resolves(self):
        result = _resolve_relationship_to_ref_field(
            "ascendix__Client__r", self.SAMPLE_REF_FIELDS
        )
        assert result == "ascendix__Client__c"


# =========================================================================
# Cross-object join supplementation (Finding 1 fix)
# =========================================================================


class TestCrossObjectJoinSupplementation:
    """Verify that saved-search relationship signals flow into parent config."""

    def _make_meta_with_ax_refs(self) -> ObjectMetadata:
        """Build a Deal-like ObjectMetadata with ascendix_parent_refs populated."""
        meta = ObjectMetadata("ascendix__Deal__c")
        meta.label = "Deal"
        meta.name_field = "Name"
        meta.fields["Name"] = {
            "name": "Name", "type": "string", "nameField": True,
            "nillable": True, "createable": True, "filterable": True,
            "groupable": True, "calculated": False,
        }
        meta.fields["ascendix__Property__c"] = {
            "name": "ascendix__Property__c", "type": "reference",
            "nameField": False, "nillable": True, "createable": True,
            "filterable": True, "groupable": True, "calculated": False,
            "referenceTo": ["ascendix__Property__c"],
        }
        meta.reference_fields["ascendix__Property__c"] = "ascendix__Property__c"
        meta.fields["ascendix__Client__c"] = {
            "name": "ascendix__Client__c", "type": "reference",
            "nameField": False, "nillable": True, "createable": True,
            "filterable": True, "groupable": True, "calculated": False,
            "referenceTo": ["Account"],
        }
        meta.reference_fields["ascendix__Client__c"] = "Account"
        # FieldScores
        meta.ensure_field_score("Name").is_name_field = True

        # Simulate Ascendix Search cross-object signals:
        # Property ref flagged with specific parent fields from template sections
        meta.ascendix_parent_refs = {
            "ascendix__Property__c": {"ascendix__City__c", "ascendix__State__c"},
            "ascendix__Client__c": set(),  # flagged but no specific fields
        }
        return meta

    def test_cross_object_fields_appear_in_parents(self):
        meta = self._make_meta_with_ax_refs()
        fetcher = MockParentFetcher()
        target_set = {"ascendix__Deal__c"}
        cfg = build_config_for_object(meta, fetcher, target_set, "ascendix__")

        # Property parent should include the cross-object join fields
        assert "ascendix__Property__c" in cfg["parents"]
        parent_field_names = {pf for pf, _ in cfg["parents"]["ascendix__Property__c"]}
        assert "ascendix__City__c" in parent_field_names
        assert "ascendix__State__c" in parent_field_names

    def test_empty_ref_set_gets_name_field(self):
        """Ref flagged with no specific fields should still get the parent nameField."""
        meta = self._make_meta_with_ax_refs()
        fetcher = MockParentFetcher()
        target_set = {"ascendix__Deal__c"}
        cfg = build_config_for_object(meta, fetcher, target_set, "ascendix__")

        # Client ref has no specific parent fields in ax_refs but was flagged
        assert "ascendix__Client__c" in cfg["parents"]
        parent_field_names = {pf for pf, _ in cfg["parents"]["ascendix__Client__c"]}
        assert "Name" in parent_field_names

    def test_no_ax_refs_keeps_existing_behavior(self):
        """Objects without ascendix_parent_refs should behave exactly as before."""
        all_meta = build_mock_metadata()
        prop_meta = all_meta["ascendix__Property__c"]
        # No ascendix_parent_refs attribute → existing parent logic only
        assert not hasattr(prop_meta, "ascendix_parent_refs")

        fetcher = MockParentFetcher()
        target_set = set(all_meta.keys())
        cfg = build_config_for_object(prop_meta, fetcher, target_set, "ascendix__")
        # Should still have Market parent from dot-notation columns
        assert "ascendix__Market__c" in cfg["parents"]


# =========================================================================
# __r-format relationship resolution through harvester (end-to-end)
# =========================================================================


class TestHarvestResolvesRelationshipPaths:
    """Verify _harvest_ascendix_search resolves __r relationship paths from
    real-format sectionsList payloads into __c ref-field keys in
    ascendix_parent_refs."""

    def _make_template_with_r_relationship(self) -> str:
        """Build a realistic saved-search template JSON.

        Uses __r relationship names as found in real Ascendix Search exports
        (see docs/archive/analysis/AUGMENTED_SCHEMA_DISCOVERY_PRD.md).
        """
        return json.dumps({
            "sectionsList": [
                {
                    "objectName": "ascendix__Deal__c",
                    "fieldsList": [
                        {"logicalName": "ascendix__SalesStage__c"},
                    ],
                },
                {
                    # Cross-object section: Property fields via __r path
                    "objectName": "ascendix__Property__c",
                    "relationship": "ascendix__Property__r",
                    "fieldsList": [
                        {"logicalName": "ascendix__City__c"},
                        {"logicalName": "ascendix__State__c"},
                    ],
                },
            ],
            "resultColumns": [],
        })

    def test_r_relationship_resolves_to_c_ref_field(self):
        """Template with ascendix__Property__r should populate
        ascendix_parent_refs['ascendix__Property__c']."""
        sf = MagicMock()
        template_json = self._make_template_with_r_relationship()

        def mock_query(soql):
            if "ascendix_search__Search__c" in soql:
                return {"records": [{
                    "ascendix_search__Template__c": template_json,
                    "Name": "Test Search",
                    "ascendix_search__ObjectName__c": "ascendix__Deal__c",
                }]}
            if "SearchSetting__c" in soql:
                return {"records": []}
            return {"records": []}

        sf.query.side_effect = mock_query
        sf.restful.side_effect = lambda path: (
            {"keyPrefix": "a0P", "fields": []}
            if "describe" in path else {}
        )

        harvester = SalesforceHarvester(sf, ascendix_search=True)
        meta = ObjectMetadata("ascendix__Deal__c")
        meta.fields["Name"] = {
            "name": "Name", "type": "string", "nameField": True,
            "nillable": True, "createable": True, "filterable": True,
            "groupable": True, "calculated": False,
        }
        meta.fields["ascendix__Property__c"] = {
            "name": "ascendix__Property__c", "type": "reference",
            "referenceTo": ["ascendix__Property__c"],
            "nillable": True, "createable": True, "filterable": True,
            "groupable": True, "calculated": False,
        }
        meta.reference_fields["ascendix__Property__c"] = "ascendix__Property__c"

        harvester._harvest_ascendix_search(meta)

        # The __r path should have been resolved to the __c ref field
        assert "ascendix__Property__c" in meta.ascendix_parent_refs
        # And the cross-object section fields should be recorded
        assert "ascendix__City__c" in meta.ascendix_parent_refs["ascendix__Property__c"]
        assert "ascendix__State__c" in meta.ascendix_parent_refs["ascendix__Property__c"]

    def test_unresolvable_relationship_is_skipped(self):
        """Template with a relationship that doesn't match any ref field is ignored."""
        sf = MagicMock()
        template_json = json.dumps({
            "sectionsList": [
                {"objectName": "ascendix__Deal__c", "fieldsList": []},
                {
                    "objectName": "ascendix__Nonexistent__c",
                    "relationship": "ascendix__Nonexistent__r",
                    "fieldsList": [{"logicalName": "SomeField__c"}],
                },
            ],
            "resultColumns": [],
        })

        sf.query.side_effect = lambda soql: (
            {"records": [{
                "ascendix_search__Template__c": template_json,
                "Name": "Test",
                "ascendix_search__ObjectName__c": "ascendix__Deal__c",
            }]}
            if "Search__c" in soql
            else {"records": []}
        )
        sf.restful.side_effect = lambda path: {"keyPrefix": "a0P", "fields": []}

        harvester = SalesforceHarvester(sf, ascendix_search=True)
        meta = ObjectMetadata("ascendix__Deal__c")
        meta.fields["Name"] = {"name": "Name", "type": "string"}

        harvester._harvest_ascendix_search(meta)

        # No parent refs should have been recorded
        assert not meta.ascendix_parent_refs


# =========================================================================
# SearchSetting scoping (Finding 3 fix)
# =========================================================================


class TestHarvestAscendixSearchScoping:
    """Verify SearchSetting result-column boosting is scoped by object."""

    def _make_mock_sf(self, *, describe_key_prefix: str = "a0P",
                      search_records: list | None = None,
                      setting_records: list | None = None) -> MagicMock:
        """Build a mock simple_salesforce.Salesforce with query/restful stubs."""
        sf = MagicMock()

        def mock_query(soql: str) -> dict:
            if "ascendix_search__Search__c" in soql:
                return {"records": search_records or []}
            if "ascendix_search__SearchSetting__c" in soql:
                return {"records": setting_records or []}
            if "SELECT COUNT()" in soql:
                return {"totalSize": 10}
            return {"records": []}

        sf.query.side_effect = mock_query

        def mock_restful(path: str) -> dict:
            if "describe" in path:
                return {"keyPrefix": describe_key_prefix, "fields": []}
            return {}

        sf.restful.side_effect = mock_restful
        return sf

    def test_setting_query_uses_key_prefix(self):
        """SearchSetting query should scope by ObjectKeyPrefix when available."""
        sf = self._make_mock_sf(describe_key_prefix="a0P")
        harvester = SalesforceHarvester(sf, ascendix_search=True)

        meta = ObjectMetadata("ascendix__Deal__c")
        meta.fields["Name"] = {"name": "Name", "type": "string"}
        harvester._harvest_ascendix_search(meta)

        # The query to SearchSetting should include ObjectKeyPrefix filter
        calls = sf.query.call_args_list
        setting_calls = [c for c in calls if "SearchSetting__c" in str(c)]
        assert len(setting_calls) == 1
        query_str = str(setting_calls[0])
        assert "a0P" in query_str

    def test_setting_query_fallback_without_prefix(self):
        """When describe fails or returns no prefix, query all rows (no WHERE on prefix)."""
        sf = self._make_mock_sf(describe_key_prefix="")
        # Make restful fail for describe
        sf.restful.side_effect = Exception("describe failed")
        harvester = SalesforceHarvester(sf, ascendix_search=True)

        meta = ObjectMetadata("ascendix__Deal__c")
        meta.fields["Name"] = {"name": "Name", "type": "string"}
        harvester._harvest_ascendix_search(meta)

        # Should still query settings — no WHERE clause on ObjectKeyPrefix
        calls = sf.query.call_args_list
        setting_calls = [c for c in calls if "SearchSetting__c" in str(c)]
        assert len(setting_calls) == 1
        query_str = str(setting_calls[0])
        # The WHERE clause should NOT contain a prefix filter (= '...')
        # (the SELECT may include the column for client-side filtering)
        assert "ObjectKeyPrefix__c = " not in query_str


# =========================================================================
# Object discovery merges across rows (Finding 3 fix)
# =========================================================================


class TestDiscoverObjectsMergesRows:
    """Verify discover_objects() merges SelectedObjects from all rows."""

    def test_merges_multiple_setting_rows(self):
        sf = MagicMock()
        sf.query.side_effect = lambda soql: (
            {
                "records": [
                    {"ascendix_search__SelectedObjects__c": '["Account", "Contact"]'},
                    {"ascendix_search__SelectedObjects__c": '["ascendix__Deal__c", "Account"]'},
                ],
            }
            if "SearchSetting__c" in soql
            else {"totalSize": 5}
        )

        harvester = SalesforceHarvester(sf, ascendix_search=False)
        objects = harvester.discover_objects()

        # Should have 3 unique objects, sorted
        assert "Account" in objects
        assert "Contact" in objects
        assert "ascendix__Deal__c" in objects

    def test_skips_objects_with_zero_records(self):
        def mock_query(soql):
            if "SearchSetting__c" in soql:
                return {"records": [
                    {"ascendix_search__SelectedObjects__c": '["Lead", "Account"]'},
                ]}
            if "Lead" in soql:
                return {"totalSize": 0}
            return {"totalSize": 10}

        sf = MagicMock()
        sf.query.side_effect = mock_query

        harvester = SalesforceHarvester(sf, ascendix_search=False)
        objects = harvester.discover_objects()

        assert "Account" in objects
        assert "Lead" not in objects

    def test_handles_empty_selected_objects(self):
        sf = MagicMock()
        sf.query.return_value = {
            "records": [
                {"ascendix_search__SelectedObjects__c": ""},
                {"ascendix_search__SelectedObjects__c": None},
            ]
        }

        harvester = SalesforceHarvester(sf, ascendix_search=False)
        objects = harvester.discover_objects()
        assert objects == []


# =========================================================================
# Mock mode regression
# =========================================================================


class TestMockModeRegression:
    """Ensure mock mode still works after T5 additions."""

    def test_mock_metadata_builds_configs(self):
        all_meta = build_mock_metadata()
        fetcher = MockParentFetcher()
        target_set = set(all_meta.keys())
        for obj_name, meta in all_meta.items():
            cfg = build_config_for_object(meta, fetcher, target_set, "ascendix__")
            assert len(cfg["embed_fields"]) > 0, f"{obj_name} has no embed_fields"
