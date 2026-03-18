"""
Unit tests for the Denormalization Config Generator.

Tests scoring logic, parent denormalization detection, YAML output generation,
and mock mode — all without requiring a live Salesforce connection.
"""

import os
import sys
import tempfile
import textwrap
from unittest.mock import MagicMock

import pytest

# Add scripts directory to path so we can import the generator
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
)

from generate_denorm_config import (
    THRESHOLD_EMBED,
    THRESHOLD_METADATA,
    WEIGHT_COMPACT_LAYOUT,
    WEIGHT_IS_FORMULA,
    WEIGHT_IS_NAME_FIELD,
    WEIGHT_IS_REQUIRED,
    WEIGHT_LIST_VIEW_COLUMN,
    WEIGHT_LIST_VIEW_FILTER,
    WEIGHT_SEARCH_LAYOUT,
    WEIGHT_IS_FILTERABLE,
    FieldScore,
    MockParentFetcher,
    ObjectMetadata,
    SalesforceHarvester,
    build_config_for_object,
    build_mock_metadata,
    render_yaml,
    _add_mock_field,
)


# ===================================================================
# FieldScore scoring tests
# ===================================================================


class TestFieldScore:
    """Test the per-field scoring formula."""

    def test_empty_score_is_zero(self):
        fs = FieldScore("some_field")
        assert fs.score == 0

    def test_name_field_only(self):
        fs = FieldScore("Name")
        fs.is_name_field = True
        assert fs.score == WEIGHT_IS_NAME_FIELD  # 15

    def test_required_field_only(self):
        fs = FieldScore("Status__c")
        fs.is_required = True
        assert fs.score == WEIGHT_IS_REQUIRED  # 20

    def test_compact_layout_appearance(self):
        fs = FieldScore("City__c")
        fs.compact_layout_appearances = 1
        assert fs.score == WEIGHT_COMPACT_LAYOUT  # 15

    def test_search_layout_appearance(self):
        fs = FieldScore("City__c")
        fs.search_layout_appearances = 1
        assert fs.score == WEIGHT_SEARCH_LAYOUT  # 10

    def test_list_view_column(self):
        fs = FieldScore("City__c")
        fs.list_view_column_appearances = 3
        assert fs.score == 3 * WEIGHT_LIST_VIEW_COLUMN  # 30

    def test_list_view_filter(self):
        fs = FieldScore("City__c")
        fs.list_view_filter_appearances = 2
        assert fs.score == 2 * WEIGHT_LIST_VIEW_FILTER  # 20

    def test_filterable_flag(self):
        fs = FieldScore("City__c")
        fs.is_filterable = True
        assert fs.score == WEIGHT_IS_FILTERABLE  # 2

    def test_formula_flag(self):
        fs = FieldScore("GLA__c")
        fs.is_formula = True
        assert fs.score == WEIGHT_IS_FORMULA  # 3

    def test_combined_high_score(self):
        """Simulate a highly-scored field like Name on Property."""
        fs = FieldScore("Name")
        fs.is_name_field = True
        fs.compact_layout_appearances = 1
        fs.search_layout_appearances = 1
        fs.list_view_column_appearances = 5
        fs.is_filterable = True
        expected = (
            WEIGHT_IS_NAME_FIELD
            + WEIGHT_COMPACT_LAYOUT
            + WEIGHT_SEARCH_LAYOUT
            + 5 * WEIGHT_LIST_VIEW_COLUMN
            + WEIGHT_IS_FILTERABLE
        )
        assert fs.score == expected  # 15+15+10+50+2 = 92

    def test_combined_medium_score(self):
        """A field that lands in metadata_fields (>=10, <20)."""
        fs = FieldScore("YearBuilt__c")
        fs.list_view_column_appearances = 1
        fs.is_filterable = True
        expected = WEIGHT_LIST_VIEW_COLUMN + WEIGHT_IS_FILTERABLE  # 12
        assert fs.score == expected
        assert fs.score >= THRESHOLD_METADATA
        assert fs.score < THRESHOLD_EMBED

    def test_provenance_string(self):
        fs = FieldScore("City__c")
        fs.compact_layout_appearances = 1
        fs.search_layout_appearances = 1
        fs.list_view_column_appearances = 3
        fs.list_view_filter_appearances = 2
        fs.is_filterable = True
        prov = fs.provenance_str
        assert "compact" in prov
        assert "search" in prov
        assert "list_view(3)" in prov
        assert "filter(2)" in prov
        # filterable should NOT appear when filter() is already present
        assert "filterable" not in prov

    def test_provenance_filterable_shown_when_no_filter(self):
        fs = FieldScore("SomeField")
        fs.is_filterable = True
        assert "filterable" in fs.provenance_str


# ===================================================================
# ObjectMetadata tests
# ===================================================================


class TestObjectMetadata:
    """Test ObjectMetadata helper methods."""

    def test_ensure_field_score_creates_new(self):
        meta = ObjectMetadata("Test__c")
        fs = meta.ensure_field_score("Field1")
        assert isinstance(fs, FieldScore)
        assert fs.field_name == "Field1"
        assert fs.score == 0

    def test_ensure_field_score_returns_existing(self):
        meta = ObjectMetadata("Test__c")
        fs1 = meta.ensure_field_score("Field1")
        fs1.is_required = True
        fs2 = meta.ensure_field_score("Field1")
        assert fs2.is_required is True
        assert fs1 is fs2


# ===================================================================
# Config building tests
# ===================================================================


class TestBuildConfigForObject:
    """Test the config builder that classifies fields into embed/metadata."""

    def _make_simple_meta(self) -> ObjectMetadata:
        """Build a minimal ObjectMetadata for testing."""
        meta = ObjectMetadata("Test__c")
        meta.label = "Test"
        meta.name_field = "Name"

        # High-score field (embed)
        _add_mock_field(meta, "Name", name_field=True, filterable=True)
        meta.ensure_field_score("Name").compact_layout_appearances = 1
        # Name score: 15(name) + 15(compact) + 2(filterable) = 32

        # Medium-score field (metadata)
        _add_mock_field(meta, "YearBuilt__c", filterable=True, sf_type="int")
        meta.ensure_field_score("YearBuilt__c").list_view_column_appearances = 1
        # YearBuilt score: 10(lv_col) + 2(filterable) = 12

        # Low-score field (excluded)
        _add_mock_field(meta, "InternalNote__c")
        # InternalNote score: 0

        # Reference field
        _add_mock_field(meta, "Parent__c", sf_type="reference",
                        reference_to="Account")

        return meta

    def test_field_classification(self):
        meta = self._make_simple_meta()
        cfg = build_config_for_object(meta, None, set(), "")
        embed_names = [f[0] for f in cfg["embed_fields"]]
        meta_names = [f[0] for f in cfg["metadata_fields"]]

        assert "Name" in embed_names
        assert "YearBuilt__c" in meta_names
        assert "InternalNote__c" not in embed_names
        assert "InternalNote__c" not in meta_names

    def test_embed_fields_sorted_by_score_desc(self):
        meta = self._make_simple_meta()
        # Add another high-score field
        _add_mock_field(meta, "City__c", filterable=True)
        meta.ensure_field_score("City__c").compact_layout_appearances = 1
        meta.ensure_field_score("City__c").list_view_column_appearances = 3
        # City score: 15(compact) + 30(lv_col) + 2(filterable) = 47

        cfg = build_config_for_object(meta, None, set(), "")
        embed_scores = [f[1] for f in cfg["embed_fields"]]
        assert embed_scores == sorted(embed_scores, reverse=True)

    def test_parent_denormalization_with_mock_fetcher(self):
        meta = self._make_simple_meta()
        fetcher = MockParentFetcher()
        cfg = build_config_for_object(meta, fetcher, set(), "")

        assert "Parent__c" in cfg["parents"]
        parent_fields = [pf[0] for pf in cfg["parents"]["Parent__c"]]
        # MockParentFetcher returns Account compact: Name, Industry, BillingCity
        assert "Name" in parent_fields

    def test_parent_always_includes_name(self):
        """Without a fetcher, parent denorm should still include Name."""
        meta = self._make_simple_meta()
        cfg = build_config_for_object(meta, None, set(), "")
        assert "Parent__c" in cfg["parents"]
        parent_fields = [pf[0] for pf in cfg["parents"]["Parent__c"]]
        assert "Name" in parent_fields

    def test_dot_notation_denormalization(self):
        """Dot-notation columns from list views trigger additional parent denorm."""
        meta = ObjectMetadata("Child__c")
        _add_mock_field(meta, "Name", name_field=True)
        _add_mock_field(meta, "ascendix__Property__c", sf_type="reference",
                        reference_to="ascendix__Property__c")
        meta.dot_notation_columns = [
            "ascendix__Property__r.ascendix__City__c",
            "ascendix__Property__r.ascendix__State__c",
        ]

        cfg = build_config_for_object(meta, None, set(), "ascendix__")
        parent_fields = [
            pf[0] for pf in cfg["parents"]["ascendix__Property__c"]
        ]
        assert "ascendix__City__c" in parent_fields
        assert "ascendix__State__c" in parent_fields

    def test_child_in_target_set_skipped(self):
        """Child objects in the target set should be skipped."""
        meta = ObjectMetadata("ascendix__Property__c")
        meta.child_relationships = [
            {"childSObject": "ascendix__Lease__c",
             "relationshipName": "Leases__r"},
            {"childSObject": "ascendix__PropertyNote__c",
             "relationshipName": "PropertyNotes__r"},
        ]
        target_set = {"ascendix__Property__c", "ascendix__Lease__c"}
        cfg = build_config_for_object(meta, None, target_set, "ascendix__")

        assert "ascendix__Lease__c" not in cfg["children"]
        assert "ascendix__PropertyNote__c" in cfg["children"]

    def test_child_outside_namespace_skipped(self):
        """Non-namespaced children should be skipped when namespace is set."""
        meta = ObjectMetadata("ascendix__Property__c")
        meta.child_relationships = [
            {"childSObject": "CustomNonNS__c",
             "relationshipName": "CustomNonNS__r"},
            {"childSObject": "ascendix__Note__c",
             "relationshipName": "Notes__r"},
        ]
        cfg = build_config_for_object(meta, None, set(), "ascendix__")
        assert "CustomNonNS__c" not in cfg["children"]
        assert "ascendix__Note__c" in cfg["children"]

    def test_filters_out_system_and_boolean_direct_fields(self):
        meta = ObjectMetadata("ascendix__Property__c")
        _add_mock_field(meta, "Name", name_field=True, filterable=True)
        meta.ensure_field_score("Name").compact_layout_appearances = 1

        _add_mock_field(meta, "Id", filterable=True)
        meta.ensure_field_score("Id").list_view_column_appearances = 3

        _add_mock_field(meta, "CreatedDate")
        meta.ensure_field_score("CreatedDate").list_view_column_appearances = 3

        _add_mock_field(meta, "ascendix__Pool__c", sf_type="boolean", required=True)
        meta.ensure_field_score("ascendix__Pool__c").list_view_column_appearances = 1

        _add_mock_field(meta, "toLabel(RecordType.Name)")
        meta.ensure_field_score("toLabel(RecordType.Name)").search_layout_appearances = 1

        _add_mock_field(meta, "RecordType")
        meta.ensure_field_score("RecordType").list_view_column_appearances = 3

        _add_mock_field(
            meta, "ascendix__OwnerLandlord__c", sf_type="reference", reference_to="Account"
        )
        meta.ensure_field_score("ascendix__OwnerLandlord__c").compact_layout_appearances = 1

        cfg = build_config_for_object(meta, None, set(), "ascendix__")
        embed_names = [f[0] for f in cfg["embed_fields"]]
        meta_names = [f[0] for f in cfg["metadata_fields"]]
        all_names = embed_names + meta_names

        assert "Name" in embed_names
        assert "Id" not in all_names
        assert "CreatedDate" not in all_names
        assert "ascendix__Pool__c" not in all_names
        assert "toLabel(RecordType.Name)" not in all_names
        assert "RecordType" not in all_names
        assert "ascendix__OwnerLandlord__c" not in all_names

    def test_filters_parent_refs_for_current_poc_objects(self):
        meta = ObjectMetadata("ascendix__Lease__c")
        _add_mock_field(meta, "Name", name_field=True)
        _add_mock_field(
            meta,
            "ascendix__Property__c",
            sf_type="reference",
            reference_to="ascendix__Property__c",
        )
        _add_mock_field(
            meta, "ascendix__Tenant__c", sf_type="reference", reference_to="Account"
        )
        _add_mock_field(
            meta,
            "ascendix__OwnerLandlord__c",
            sf_type="reference",
            reference_to="Account",
        )
        _add_mock_field(
            meta,
            "ascendix__Floor__c",
            sf_type="reference",
            reference_to="ascendix__Floor__c",
        )
        _add_mock_field(
            meta,
            "ascendix__OriginatingDeal__c",
            sf_type="reference",
            reference_to="ascendix__Deal__c",
        )
        _add_mock_field(meta, "CreatedById", sf_type="reference", reference_to="User")
        meta.dot_notation_columns = ["ascendix__Property__r.ascendix__City__c"]

        fetcher = MockParentFetcher()
        cfg = build_config_for_object(meta, fetcher, set(), "ascendix__")

        assert set(cfg["parents"]) == {
            "ascendix__Property__c",
            "ascendix__Tenant__c",
            "ascendix__OwnerLandlord__c",
        }
        property_fields = [pf[0] for pf in cfg["parents"]["ascendix__Property__c"]]
        tenant_fields = [pf[0] for pf in cfg["parents"]["ascendix__Tenant__c"]]
        assert "Name" in property_fields
        assert "ascendix__City__c" in property_fields
        assert "Industry" not in tenant_fields

    def test_generic_parent_refs_default_to_name_only_outside_poc_allowlist(self):
        meta = self._make_simple_meta()
        cfg = build_config_for_object(meta, MockParentFetcher(), set(), "")
        assert "Parent__c" in cfg["parents"]
        assert [pf[0] for pf in cfg["parents"]["Parent__c"]] == ["Name"]


# ===================================================================
# YAML rendering tests
# ===================================================================


class TestRenderYaml:
    """Test YAML output generation."""

    def test_header_comments(self):
        configs = {"TestObj__c": {
            "embed_fields": [], "metadata_fields": [],
            "parents": {}, "children": {},
        }}
        output = render_yaml(configs, "2026-03-14T10:30:00Z")
        assert "# Auto-generated from Salesforce org metadata" in output
        assert "# Generated: 2026-03-14T10:30:00Z" in output

    def test_embed_fields_with_score_comments(self):
        configs = {"Obj__c": {
            "embed_fields": [("Name", 55, "nameField, compact, search")],
            "metadata_fields": [],
            "parents": {},
            "children": {},
        }}
        output = render_yaml(configs, "2026-03-14T10:30:00Z")
        assert "embed_fields:" in output
        assert "- Name" in output
        assert "score=55" in output
        assert "nameField, compact, search" in output

    def test_metadata_fields_section(self):
        configs = {"Obj__c": {
            "embed_fields": [],
            "metadata_fields": [("TotalSF__c", 12, "list_view(1), filterable")],
            "parents": {},
            "children": {},
        }}
        output = render_yaml(configs, "2026-03-14T10:30:00Z")
        assert "metadata_fields:" in output
        assert "TotalSF__c" in output
        assert "score=12" in output

    def test_parents_section(self):
        configs = {"Obj__c": {
            "embed_fields": [],
            "metadata_fields": [],
            "parents": {
                "Owner__c": [("Name", "parent nameField"), ("Industry", "parent compact")]
            },
            "children": {},
        }}
        output = render_yaml(configs, "2026-03-14T10:30:00Z")
        assert "parents:" in output
        assert "Owner__c:" in output
        assert "- Name" in output
        assert "parent nameField" in output
        assert "- Industry" in output

    def test_children_section(self):
        configs = {"Obj__c": {
            "embed_fields": [],
            "metadata_fields": [],
            "parents": {},
            "children": {
                "ChildObj__c": {"aggregate": ["count"]},
            },
        }}
        output = render_yaml(configs, "2026-03-14T10:30:00Z")
        assert "children:" in output
        assert "ChildObj__c:" in output
        assert "aggregate: [count]" in output

    def test_multiple_objects(self):
        configs = {
            "Obj1__c": {
                "embed_fields": [("Name", 30, "nameField")],
                "metadata_fields": [],
                "parents": {},
                "children": {},
            },
            "Obj2__c": {
                "embed_fields": [("Title", 25, "compact")],
                "metadata_fields": [],
                "parents": {},
                "children": {},
            },
        }
        output = render_yaml(configs, "2026-03-14T10:30:00Z")
        assert "Obj1__c:" in output
        assert "Obj2__c:" in output

    def test_empty_sections_omitted(self):
        """Sections with no entries should not appear in output."""
        configs = {"Obj__c": {
            "embed_fields": [("Name", 30, "nameField")],
            "metadata_fields": [],
            "parents": {},
            "children": {},
        }}
        output = render_yaml(configs, "2026-03-14T10:30:00Z")
        assert "embed_fields:" in output
        assert "metadata_fields:" not in output
        assert "parents:" not in output
        assert "children:" not in output


# ===================================================================
# Filter / dot-notation parsing tests
# ===================================================================


class TestDotNotationParsing:
    """Test parsing of dot-notation columns from list views."""

    def test_relationship_name_conversion(self):
        """ascendix__Property__c → ascendix__Property__r for matching."""
        meta = ObjectMetadata("ascendix__Lease__c")
        _add_mock_field(meta, "ascendix__Property__c", sf_type="reference",
                        reference_to="ascendix__Property__c")
        meta.dot_notation_columns = [
            "ascendix__Property__r.ascendix__City__c",
        ]
        cfg = build_config_for_object(meta, None, set(), "ascendix__")
        parent_fields = [
            pf[0] for pf in cfg["parents"]["ascendix__Property__c"]
        ]
        assert "ascendix__City__c" in parent_fields

    def test_standard_lookup_conversion(self):
        """Standard fields ending in Id should also be handled.

        For example, AccountId → Account.Name
        """
        meta = ObjectMetadata("Contact")
        _add_mock_field(meta, "AccountId", sf_type="reference",
                        reference_to="Account")
        meta.dot_notation_columns = [
            "Account.Industry",
        ]
        cfg = build_config_for_object(meta, None, set(), "")
        parent_fields = [pf[0] for pf in cfg["parents"]["AccountId"]]
        assert "Industry" in parent_fields

    def test_no_duplicate_parent_fields(self):
        """If dot-notation field is already in compact, don't duplicate."""
        meta = ObjectMetadata("Child__c")
        _add_mock_field(meta, "Parent__c", sf_type="reference",
                        reference_to="Account")
        meta.dot_notation_columns = [
            "Parent.Name",  # Name is already added as nameField
        ]
        fetcher = MockParentFetcher()
        cfg = build_config_for_object(meta, fetcher, set(), "")
        parent_field_names = [pf[0] for pf in cfg["parents"]["Parent__c"]]
        # Name should appear only once
        assert parent_field_names.count("Name") == 1


# ===================================================================
# Mock mode end-to-end test
# ===================================================================


class TestMockMode:
    """Test mock mode produces valid, realistic output."""

    def test_mock_metadata_contains_expected_objects(self):
        meta = build_mock_metadata()
        assert "ascendix__Property__c" in meta
        assert "ascendix__Lease__c" in meta
        assert "ascendix__Availability__c" in meta

    def test_mock_property_has_high_score_fields(self):
        meta = build_mock_metadata()
        prop = meta["ascendix__Property__c"]

        # Name should score very high
        name_score = prop.field_scores["Name"].score
        assert name_score >= THRESHOLD_EMBED, f"Name score {name_score} < {THRESHOLD_EMBED}"

        # City should score high (compact + search + list views + filters)
        city_score = prop.field_scores["ascendix__City__c"].score
        assert city_score >= THRESHOLD_EMBED

    def test_mock_property_has_reference_fields(self):
        meta = build_mock_metadata()
        prop = meta["ascendix__Property__c"]
        assert "ascendix__OwnerLandlord__c" in prop.reference_fields
        assert prop.reference_fields["ascendix__OwnerLandlord__c"] == "Account"

    def test_mock_generates_valid_yaml(self):
        """Full pipeline: mock metadata → config → YAML string."""
        all_meta = build_mock_metadata()
        target_set = set(all_meta.keys())
        fetcher = MockParentFetcher()

        configs = {}
        for obj_name, meta in all_meta.items():
            cfg = build_config_for_object(meta, fetcher, target_set, "ascendix__")
            configs[obj_name] = cfg

        yaml_output = render_yaml(configs, "2026-03-14T10:30:00Z")

        # Basic structural checks
        assert "ascendix__Property__c:" in yaml_output
        assert "embed_fields:" in yaml_output
        assert "parents:" in yaml_output
        assert "score=" in yaml_output

    def test_mock_property_embed_includes_name_and_city(self):
        all_meta = build_mock_metadata()
        target_set = set(all_meta.keys())
        fetcher = MockParentFetcher()
        cfg = build_config_for_object(
            all_meta["ascendix__Property__c"], fetcher, target_set, "ascendix__"
        )
        embed_names = [f[0] for f in cfg["embed_fields"]]
        assert "Name" in embed_names
        assert "ascendix__City__c" in embed_names

    def test_mock_property_children_skip_target_objects(self):
        """Lease and Availability are in target set → not in children."""
        all_meta = build_mock_metadata()
        target_set = set(all_meta.keys())
        fetcher = MockParentFetcher()
        cfg = build_config_for_object(
            all_meta["ascendix__Property__c"], fetcher, target_set, "ascendix__"
        )
        assert "ascendix__Lease__c" not in cfg["children"]
        assert "ascendix__Availability__c" not in cfg["children"]

    def test_mock_lease_parent_denorm_includes_property_fields(self):
        """Lease should denormalize Property fields from compact layout + dot notation."""
        all_meta = build_mock_metadata()
        target_set = set(all_meta.keys())
        fetcher = MockParentFetcher()
        cfg = build_config_for_object(
            all_meta["ascendix__Lease__c"], fetcher, target_set, "ascendix__"
        )
        assert "ascendix__Property__c" in cfg["parents"]
        parent_fields = [pf[0] for pf in cfg["parents"]["ascendix__Property__c"]]
        # From compact layout
        assert "Name" in parent_fields
        # From dot-notation
        assert "ascendix__City__c" in parent_fields

    def test_mock_output_to_file(self, tmp_path):
        """Write output to a temp file and verify it's readable."""
        all_meta = build_mock_metadata()
        target_set = set(all_meta.keys())
        fetcher = MockParentFetcher()

        configs = {}
        for obj_name, meta in all_meta.items():
            cfg = build_config_for_object(meta, fetcher, target_set, "ascendix__")
            configs[obj_name] = cfg

        yaml_output = render_yaml(configs, "2026-03-14T10:30:00Z")

        outfile = tmp_path / "test_config.yaml"
        outfile.write_text(yaml_output)

        # Read back and verify
        content = outfile.read_text()
        assert len(content) > 100
        assert "ascendix__Property__c:" in content

    def test_mock_availability_parent_is_property(self):
        all_meta = build_mock_metadata()
        target_set = set(all_meta.keys())
        fetcher = MockParentFetcher()
        cfg = build_config_for_object(
            all_meta["ascendix__Availability__c"], fetcher, target_set, "ascendix__"
        )
        assert "ascendix__Property__c" in cfg["parents"]

    def test_mock_availability_dot_notation_fields(self):
        """Availability list views with Property__r.Name and Property__r.City__c."""
        all_meta = build_mock_metadata()
        target_set = set(all_meta.keys())
        fetcher = MockParentFetcher()
        cfg = build_config_for_object(
            all_meta["ascendix__Availability__c"], fetcher, target_set, "ascendix__"
        )
        parent_fields = [
            pf[0] for pf in cfg["parents"]["ascendix__Property__c"]
        ]
        assert "ascendix__City__c" in parent_fields


# ===================================================================
# Scoring threshold boundary tests
# ===================================================================


class TestScoringThresholds:
    """Test boundary conditions for metadata/embed thresholds."""

    def test_score_below_metadata_excluded(self):
        """Fields with score < 10 should not appear in either list."""
        meta = ObjectMetadata("Test__c")
        _add_mock_field(meta, "LowField", filterable=True)
        # filterable only = score 2, below threshold
        cfg = build_config_for_object(meta, None, set(), "")
        all_fields = (
            [f[0] for f in cfg["embed_fields"]]
            + [f[0] for f in cfg["metadata_fields"]]
        )
        assert "LowField" not in all_fields

    def test_score_exactly_metadata_threshold(self):
        """Fields with score == 10 should be in metadata_fields."""
        meta = ObjectMetadata("Test__c")
        _add_mock_field(meta, "ExactTen")
        meta.ensure_field_score("ExactTen").search_layout_appearances = 1
        # score = 10
        assert meta.field_scores["ExactTen"].score == 10

        cfg = build_config_for_object(meta, None, set(), "")
        meta_names = [f[0] for f in cfg["metadata_fields"]]
        assert "ExactTen" in meta_names

    def test_score_exactly_embed_threshold(self):
        """Fields with score == 20 should be in embed_fields."""
        meta = ObjectMetadata("Test__c")
        _add_mock_field(meta, "ExactTwenty", required=True)
        # required = 20
        assert meta.field_scores["ExactTwenty"].score == 20

        cfg = build_config_for_object(meta, None, set(), "")
        embed_names = [f[0] for f in cfg["embed_fields"]]
        assert "ExactTwenty" in embed_names

    def test_score_19_is_metadata_not_embed(self):
        """Score 19 → metadata only, not embed."""
        meta = ObjectMetadata("Test__c")
        _add_mock_field(meta, "AlmostEmbed", name_field=True, filterable=True)
        # nameField(15) + filterable(2) = 17
        assert meta.field_scores["AlmostEmbed"].score == 17
        assert meta.field_scores["AlmostEmbed"].score >= THRESHOLD_METADATA
        assert meta.field_scores["AlmostEmbed"].score < THRESHOLD_EMBED

        cfg = build_config_for_object(meta, None, set(), "")
        meta_names = [f[0] for f in cfg["metadata_fields"]]
        embed_names = [f[0] for f in cfg["embed_fields"]]
        assert "AlmostEmbed" in meta_names
        assert "AlmostEmbed" not in embed_names


# ===================================================================
# MockParentFetcher tests
# ===================================================================


class TestMockParentFetcher:
    """Test the mock parent data source."""

    def test_account_compact_fields(self):
        fetcher = MockParentFetcher()
        fields = fetcher.fetch_parent_compact_fields("Account")
        assert "Name" in fields
        assert "Industry" in fields

    def test_property_compact_fields(self):
        fetcher = MockParentFetcher()
        fields = fetcher.fetch_parent_compact_fields("ascendix__Property__c")
        assert "Name" in fields
        assert "ascendix__City__c" in fields

    def test_unknown_object_returns_name(self):
        fetcher = MockParentFetcher()
        fields = fetcher.fetch_parent_compact_fields("Unknown__c")
        assert fields == ["Name"]

    def test_name_field_for_account(self):
        fetcher = MockParentFetcher()
        assert fetcher.fetch_parent_name_field("Account") == "Name"

    def test_name_field_for_unknown(self):
        fetcher = MockParentFetcher()
        assert fetcher.fetch_parent_name_field("Unknown__c") == "Name"


class TestSalesforceHarvesterNullSafety:
    def test_fetch_parent_compact_fields_handles_null_compact_layouts(self):
        sf = MagicMock()
        sf.restful.side_effect = [
            {"compactLayouts": None, "defaultCompactLayoutId": None},
            {"fields": [{"name": "Name", "nameField": True}]},
        ]
        harvester = SalesforceHarvester(sf)
        assert harvester.fetch_parent_compact_fields("Account") == ["Name"]

    def test_harvest_search_layouts_handles_none_and_null_columns(self):
        sf = MagicMock()
        sf.restful.return_value = [None, {"searchColumns": None}]
        harvester = SalesforceHarvester(sf)
        meta = ObjectMetadata("Test__c")
        harvester._harvest_search_layouts(meta)
        assert meta.field_scores == {}

    def test_harvest_page_layouts_handles_null_nested_arrays(self):
        sf = MagicMock()
        sf.restful.return_value = {
            "layouts": [
                {
                    "detailLayoutSections": None,
                    "editLayoutSections": [
                        {"layoutRows": None},
                    ],
                }
            ]
        }
        harvester = SalesforceHarvester(sf)
        meta = ObjectMetadata("Test__c")
        harvester._harvest_page_layouts(meta)
        assert meta.field_scores == {}

    def test_harvest_list_views_handles_null_views_and_columns(self):
        sf = MagicMock()
        sf.restful.side_effect = [
            {"listviews": [{"id": "lv1"}]},
            {"columns": None, "where": None},
        ]
        harvester = SalesforceHarvester(sf)
        meta = ObjectMetadata("Test__c")
        harvester._harvest_list_views(meta)
        assert meta.field_scores == {}

    def test_extract_filter_fields_handles_null_conditions(self):
        harvester = SalesforceHarvester(MagicMock())
        meta = ObjectMetadata("Test__c")
        harvester._extract_filter_fields(
            {"conditions": None, "subConditions": None}, meta
        )
        assert meta.field_scores == {}
