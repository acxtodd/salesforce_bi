#!/usr/bin/env python3
"""
Denormalization Config Generator for AscendixIQ Salesforce Connector.

Connects to a Salesforce org, harvests metadata from compact layouts,
search layouts, page layouts, list views, and field describes, scores
fields using the tiered formula from spec Section 8.5, and generates
a YAML config defining which fields to embed, which parent fields to
denormalize, and which child aggregations to compute.

Usage:
    # Live Salesforce org
    python3 scripts/generate_denorm_config.py \\
        --objects ascendix__Property__c ascendix__Lease__c \\
        --output denorm_config.yaml \\
        --namespace-prefix ascendix__

    # Mock mode (no credentials needed)
    python3 scripts/generate_denorm_config.py --mock --output denorm_config.yaml

    # With explicit credentials
    python3 scripts/generate_denorm_config.py \\
        --instance-url https://myorg.sandbox.my.salesforce.com \\
        --username user@example.com \\
        --password mypass \\
        --token mysectoken \\
        --objects ascendix__Property__c \\
        --output denorm_config.yaml

Environment variables (alternative to CLI flags):
    SALESFORCE_INSTANCE_URL, SALESFORCE_USERNAME,
    SALESFORCE_PASSWORD, SALESFORCE_SECURITY_TOKEN
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Scoring weights — spec Section 8.5
# ---------------------------------------------------------------------------
WEIGHT_COMPACT_LAYOUT = 15
WEIGHT_SEARCH_LAYOUT = 10
WEIGHT_LIST_VIEW_COLUMN = 10
WEIGHT_LIST_VIEW_FILTER = 10
WEIGHT_IS_REQUIRED = 20
WEIGHT_IS_NAME_FIELD = 15
WEIGHT_IS_FILTERABLE = 2
WEIGHT_IS_FORMULA = 3

THRESHOLD_METADATA = 10   # score >= 10 → metadata_fields
THRESHOLD_EMBED = 20      # score >= 20 → embed_fields

# Maximum list views to iterate per object (avoid API rate limits)
MAX_LISTVIEWS = 10


# ===================================================================
# Data containers
# ===================================================================

class FieldScore:
    """Accumulated score and provenance for a single field."""

    def __init__(self, field_name: str):
        self.field_name = field_name
        self.compact_layout_appearances = 0
        self.search_layout_appearances = 0
        self.list_view_column_appearances = 0
        self.list_view_filter_appearances = 0
        self.is_required = False
        self.is_name_field = False
        self.is_filterable = False
        self.is_formula = False
        self.provenance: List[str] = []

    @property
    def score(self) -> int:
        return (
            self.compact_layout_appearances * WEIGHT_COMPACT_LAYOUT
            + self.search_layout_appearances * WEIGHT_SEARCH_LAYOUT
            + self.list_view_column_appearances * WEIGHT_LIST_VIEW_COLUMN
            + self.list_view_filter_appearances * WEIGHT_LIST_VIEW_FILTER
            + int(self.is_required) * WEIGHT_IS_REQUIRED
            + int(self.is_name_field) * WEIGHT_IS_NAME_FIELD
            + int(self.is_filterable) * WEIGHT_IS_FILTERABLE
            + int(self.is_formula) * WEIGHT_IS_FORMULA
        )

    @property
    def provenance_str(self) -> str:
        parts = []
        if self.is_name_field:
            parts.append("nameField")
        if self.is_required:
            parts.append("required")
        if self.is_formula:
            parts.append("formula")
        if self.compact_layout_appearances:
            parts.append("compact")
        if self.search_layout_appearances:
            parts.append("search")
        if self.list_view_column_appearances:
            parts.append(f"list_view({self.list_view_column_appearances})")
        if self.list_view_filter_appearances:
            parts.append(f"filter({self.list_view_filter_appearances})")
        if self.is_filterable and not any(p.startswith("filter") for p in parts):
            parts.append("filterable")
        return ", ".join(parts) if parts else "intrinsic"

    def __repr__(self) -> str:
        return f"FieldScore({self.field_name}, score={self.score})"


class ObjectMetadata:
    """All harvested metadata for one Salesforce object."""

    def __init__(self, api_name: str):
        self.api_name = api_name
        self.label: str = api_name
        self.name_field: Optional[str] = None
        self.fields: Dict[str, Dict[str, Any]] = {}  # api_name → describe props
        self.field_scores: Dict[str, FieldScore] = {}
        self.reference_fields: Dict[str, str] = {}  # field_api → parent object
        self.child_relationships: List[Dict[str, Any]] = []
        # dot-notation columns from list views (e.g. "Property__r.City__c")
        self.dot_notation_columns: List[str] = []

    def ensure_field_score(self, field_name: str) -> FieldScore:
        if field_name not in self.field_scores:
            self.field_scores[field_name] = FieldScore(field_name)
        return self.field_scores[field_name]


# ===================================================================
# Salesforce metadata harvester
# ===================================================================

class SalesforceHarvester:
    """Connects to Salesforce and harvests layout/describe metadata."""

    def __init__(self, sf):
        """
        Args:
            sf: simple_salesforce.Salesforce instance
        """
        self.sf = sf

    # ----- Top-level entry point -----

    def harvest_object(self, obj_api_name: str) -> ObjectMetadata:
        """Harvest all metadata signals for one object."""
        meta = ObjectMetadata(obj_api_name)

        # T7 — Field describe (always available)
        self._harvest_describe(meta)

        # T1 — Compact layouts
        self._harvest_compact_layouts(meta)

        # T2 — Search layouts
        self._harvest_search_layouts(meta)

        # T3 — Page layouts
        self._harvest_page_layouts(meta)

        # T4 — List views (columns + filters)
        self._harvest_list_views(meta)

        return meta

    def fetch_parent_compact_fields(self, parent_obj: str) -> List[str]:
        """Return compact-layout field names for a parent object.

        Falls back to the parent's nameField if the compact layout call fails.
        """
        try:
            result = self.sf.restful(f"sobjects/{parent_obj}/describe/compactLayouts/")
            primary = result.get("defaultCompactLayoutId")
            for cl in result.get("compactLayouts", []):
                if cl.get("id") == primary:
                    return [
                        fi.get("layoutComponents", [{}])[0].get("value", "")
                        for fi in cl.get("fieldItems", [])
                        if fi.get("layoutComponents")
                    ]
            # If no primary found, try first compact layout
            if result.get("compactLayouts"):
                cl = result["compactLayouts"][0]
                return [
                    fi.get("layoutComponents", [{}])[0].get("value", "")
                    for fi in cl.get("fieldItems", [])
                    if fi.get("layoutComponents")
                ]
        except Exception as e:
            print(f"  Warning: compact layout fetch failed for {parent_obj}: {e}")

        # Fallback — get nameField from describe
        try:
            desc = self.sf.restful(f"sobjects/{parent_obj}/describe")
            for f in desc.get("fields", []):
                if f.get("nameField"):
                    return [f["name"]]
        except Exception:
            pass
        return ["Name"]

    def fetch_parent_name_field(self, parent_obj: str) -> str:
        """Return the nameField for a parent object."""
        try:
            desc = self.sf.restful(f"sobjects/{parent_obj}/describe")
            for f in desc.get("fields", []):
                if f.get("nameField"):
                    return f["name"]
        except Exception:
            pass
        return "Name"

    # ----- T7: Field Describe -----

    def _harvest_describe(self, meta: ObjectMetadata) -> None:
        try:
            desc = self.sf.restful(f"sobjects/{meta.api_name}/describe")
        except Exception as e:
            print(f"  ERROR: describe failed for {meta.api_name}: {e}")
            return

        meta.label = desc.get("label", meta.api_name)
        meta.child_relationships = desc.get("childRelationships", [])

        for f in desc.get("fields", []):
            name = f.get("name", "")
            if not name or f.get("deprecatedAndHidden"):
                continue

            meta.fields[name] = f
            fs = meta.ensure_field_score(name)

            # nameField
            if f.get("nameField"):
                fs.is_name_field = True
                meta.name_field = name

            # required = not nillable AND createable
            if not f.get("nillable", True) and f.get("createable", False):
                fs.is_required = True

            # filterable
            if f.get("filterable") and f.get("groupable"):
                fs.is_filterable = True

            # formula
            if f.get("calculated"):
                fs.is_formula = True

            # reference fields
            if f.get("type") == "reference" and f.get("referenceTo"):
                meta.reference_fields[name] = f["referenceTo"][0]

    # ----- T1: Compact Layouts -----

    def _harvest_compact_layouts(self, meta: ObjectMetadata) -> None:
        try:
            result = self.sf.restful(
                f"sobjects/{meta.api_name}/describe/compactLayouts/"
            )
        except Exception as e:
            print(f"  Warning: compact layout fetch failed for {meta.api_name}: {e}")
            return

        fields_seen: Set[str] = set()
        for cl in result.get("compactLayouts", []):
            for fi in cl.get("fieldItems", []):
                components = fi.get("layoutComponents", [])
                if components:
                    fname = components[0].get("value", "")
                    if fname and fname not in fields_seen:
                        fields_seen.add(fname)
                        fs = meta.ensure_field_score(fname)
                        fs.compact_layout_appearances += 1
                        if "compact" not in fs.provenance:
                            fs.provenance.append("compact")

    # ----- T2: Search Layouts -----

    def _harvest_search_layouts(self, meta: ObjectMetadata) -> None:
        try:
            result = self.sf.restful(f"search/layout/?q={meta.api_name}")
        except Exception as e:
            print(f"  Warning: search layout fetch failed for {meta.api_name}: {e}")
            return

        layouts = result if isinstance(result, list) else [result]
        for layout in layouts:
            for col in layout.get("searchColumns", []):
                fname = col.get("name", "")
                if fname:
                    fs = meta.ensure_field_score(fname)
                    fs.search_layout_appearances += 1
                    if "search" not in fs.provenance:
                        fs.provenance.append("search")

    # ----- T3: Page Layouts -----

    def _harvest_page_layouts(self, meta: ObjectMetadata) -> None:
        try:
            result = self.sf.restful(
                f"sobjects/{meta.api_name}/describe/layouts"
            )
        except Exception as e:
            print(f"  Warning: page layout fetch failed for {meta.api_name}: {e}")
            return

        for layout in result.get("layouts", []):
            # Walk detail layout sections
            for section in layout.get("detailLayoutSections", []):
                for row in section.get("layoutRows", []):
                    for item in row.get("layoutItems", []):
                        for comp in item.get("layoutComponents", []):
                            fname = comp.get("value", "")
                            if fname and fname in meta.fields:
                                finfo = meta.fields[fname]
                                fs = meta.ensure_field_score(fname)
                                # Required fields on page layout get the weight
                                if item.get("required"):
                                    fs.is_required = True

            # Also walk editLayoutSections as fallback
            for section in layout.get("editLayoutSections", []):
                for row in section.get("layoutRows", []):
                    for item in row.get("layoutItems", []):
                        if item.get("required"):
                            for comp in item.get("layoutComponents", []):
                                fname = comp.get("value", "")
                                if fname:
                                    fs = meta.ensure_field_score(fname)
                                    fs.is_required = True

    # ----- T4: List Views -----

    def _harvest_list_views(self, meta: ObjectMetadata) -> None:
        try:
            result = self.sf.restful(f"sobjects/{meta.api_name}/listviews")
        except Exception as e:
            print(f"  Warning: list views fetch failed for {meta.api_name}: {e}")
            return

        listviews = result.get("listviews", [])
        for lv in listviews[:MAX_LISTVIEWS]:
            lv_id = lv.get("id")
            if not lv_id:
                continue
            try:
                desc = self.sf.restful(
                    f"sobjects/{meta.api_name}/listviews/{lv_id}/describe"
                )
            except Exception as e:
                print(f"  Warning: list view describe failed ({lv_id}): {e}")
                continue

            # Columns
            for col in desc.get("columns", []):
                col_name = col.get("fieldNameOrPath", "")
                if not col_name:
                    continue

                # Dot-notation (cross-object) column
                if "." in col_name:
                    meta.dot_notation_columns.append(col_name)
                    # Also score the base reference field
                    base_field = col_name.split(".")[0]
                    # Convert relationship name to field name
                    # e.g. ascendix__Property__r → ascendix__Property__c
                    if base_field.endswith("__r"):
                        base_field = base_field[:-3] + "__c"
                    fs = meta.ensure_field_score(base_field)
                    fs.list_view_column_appearances += 1
                else:
                    fs = meta.ensure_field_score(col_name)
                    fs.list_view_column_appearances += 1

            # Filters
            where = desc.get("where")
            if where and isinstance(where, dict):
                self._extract_filter_fields(where, meta)

    def _extract_filter_fields(
        self, where_clause: Dict[str, Any], meta: ObjectMetadata
    ) -> None:
        """Recursively extract field names from list view WHERE conditions."""
        conditions = where_clause.get("conditions", [])
        for cond in conditions:
            fname = cond.get("field", "")
            if fname:
                fs = meta.ensure_field_score(fname)
                fs.list_view_filter_appearances += 1

        # Recurse into sub-clauses
        for sub in where_clause.get("subConditions", []):
            if isinstance(sub, dict):
                self._extract_filter_fields(sub, meta)


# ===================================================================
# Config generation logic (no Salesforce connection needed)
# ===================================================================

def build_config_for_object(
    meta: ObjectMetadata,
    harvester: Optional[SalesforceHarvester],
    target_set: Set[str],
    namespace_prefix: str,
) -> Dict[str, Any]:
    """Build the YAML-ready config dict for one object.

    Returns a dict like:
        {
            "embed_fields": [...],
            "metadata_fields": [...],
            "parents": {...},
            "children": {...},
        }
    where each field entry is a CommentedField (str subclass with comment).
    """
    # --- Field classification ---
    embed_fields: List[Tuple[str, int, str]] = []   # (name, score, provenance)
    metadata_fields: List[Tuple[str, int, str]] = []

    for fname, fs in sorted(
        meta.field_scores.items(), key=lambda kv: kv[1].score, reverse=True
    ):
        sc = fs.score
        if sc >= THRESHOLD_EMBED:
            embed_fields.append((fname, sc, fs.provenance_str))
        elif sc >= THRESHOLD_METADATA:
            metadata_fields.append((fname, sc, fs.provenance_str))

    # --- Parent denormalization ---
    parents: Dict[str, List[Tuple[str, str]]] = {}  # ref_field → [(field, comment)]
    for ref_field, parent_obj in meta.reference_fields.items():
        parent_fields: List[Tuple[str, str]] = []
        seen: Set[str] = set()

        if harvester is not None:
            # Fetch parent nameField
            name_field = harvester.fetch_parent_name_field(parent_obj)
            if name_field not in seen:
                parent_fields.append((name_field, "parent nameField"))
                seen.add(name_field)

            # Fetch parent compact layout fields
            compact_fields = harvester.fetch_parent_compact_fields(parent_obj)
            for cf in compact_fields:
                if cf and cf not in seen:
                    parent_fields.append((cf, "parent compact"))
                    seen.add(cf)
        else:
            # Mock / offline — always include Name
            parent_fields.append(("Name", "parent nameField"))
            seen.add("Name")

        # Check dot-notation columns from child list views
        # Convert ref field to relationship name: ascendix__Property__c → ascendix__Property__r
        rel_name = ref_field
        if rel_name.endswith("__c"):
            rel_name = rel_name[:-3] + "__r"
        elif rel_name.endswith("Id"):
            rel_name = rel_name[:-2]

        for dot_col in meta.dot_notation_columns:
            if dot_col.startswith(rel_name + "."):
                parent_field = dot_col.split(".", 1)[1]
                if parent_field not in seen:
                    parent_fields.append(
                        (parent_field, f"child list_view dot notation ({dot_col})")
                    )
                    seen.add(parent_field)

        if parent_fields:
            parents[ref_field] = parent_fields

    # --- Child aggregation ---
    children: Dict[str, Dict[str, Any]] = {}
    for cr in meta.child_relationships:
        child_obj = cr.get("childSObject", "")
        if not child_obj:
            continue
        # Skip if child is in target set
        if child_obj in target_set:
            continue
        # Skip standard system children
        if child_obj in (
            "AttachedContentDocument", "ContentDocumentLink",
            "CombinedAttachment", "ProcessInstance", "Note",
            "EntitySubscription", "FeedItem", "TopicAssignment",
        ):
            continue
        # Skip non-custom children that don't match namespace
        if namespace_prefix and not child_obj.startswith(namespace_prefix):
            continue
        rel_name = cr.get("relationshipName", "")
        if rel_name:
            children[child_obj] = {"aggregate": ["count"]}

    return {
        "embed_fields": embed_fields,
        "metadata_fields": metadata_fields,
        "parents": parents,
        "children": children,
    }


def render_yaml(
    configs: Dict[str, Dict[str, Any]], generated_at: str
) -> str:
    """Render the configs dict to human-readable YAML with inline score comments."""
    lines: List[str] = []
    lines.append("# Auto-generated from Salesforce org metadata")
    lines.append(f"# Generated: {generated_at}")
    lines.append("# Review and commit before use")
    lines.append("")

    for obj_name, cfg in configs.items():
        lines.append(f"{obj_name}:")

        # embed_fields
        if cfg["embed_fields"]:
            lines.append("  embed_fields:")
            for fname, score, prov in cfg["embed_fields"]:
                lines.append(f"    - {fname:<30s} # {prov}, score={score}")

        # metadata_fields
        if cfg["metadata_fields"]:
            lines.append("  metadata_fields:")
            for fname, score, prov in cfg["metadata_fields"]:
                lines.append(f"    - {fname:<30s} # {prov}, score={score}")

        # parents
        if cfg["parents"]:
            lines.append("  parents:")
            for ref_field, pfields in cfg["parents"].items():
                lines.append(f"    {ref_field}:")
                for pf_name, pf_comment in pfields:
                    lines.append(f"      - {pf_name:<28s} # {pf_comment}")

        # children
        if cfg["children"]:
            lines.append("  children:")
            for child_obj, child_cfg in cfg["children"].items():
                agg = child_cfg.get("aggregate", [])
                agg_str = "[" + ", ".join(agg) + "]"
                lines.append(f"    {child_obj}:")
                lines.append(f"      aggregate: {agg_str}")

        lines.append("")

    return "\n".join(lines)


# ===================================================================
# Mock metadata for --mock mode
# ===================================================================

def build_mock_metadata() -> Dict[str, ObjectMetadata]:
    """Return realistic Ascendix CRE metadata for Property, Lease, Availability.

    Exercises the full scoring pipeline without needing a live Salesforce org.
    """
    objects: Dict[str, ObjectMetadata] = {}

    # ----- Property -----
    prop = ObjectMetadata("ascendix__Property__c")
    prop.label = "Property"
    prop.name_field = "Name"

    # Simulate describe fields
    _add_mock_field(prop, "Name", name_field=True, filterable=True)
    _add_mock_field(prop, "ascendix__City__c", filterable=True)
    _add_mock_field(prop, "ascendix__State__c", filterable=True)
    _add_mock_field(prop, "ascendix__PropertyClass__c", filterable=True)
    _add_mock_field(prop, "ascendix__PropertySubType__c", filterable=True)
    _add_mock_field(prop, "ascendix__Description__c")
    _add_mock_field(prop, "ascendix__TotalSF__c", filterable=True, sf_type="double")
    _add_mock_field(prop, "ascendix__YearBuilt__c", filterable=True, sf_type="int")
    _add_mock_field(prop, "ascendix__Floors__c", sf_type="int")
    _add_mock_field(prop, "ascendix__Status__c", filterable=True, required=True)
    _add_mock_field(prop, "ascendix__ZipCode__c", filterable=True)
    _add_mock_field(prop, "ascendix__OwnerLandlord__c", sf_type="reference",
                    reference_to="Account")
    _add_mock_field(prop, "ascendix__Market__c", sf_type="reference",
                    reference_to="ascendix__Market__c")
    _add_mock_field(prop, "ascendix__SubMarket__c", sf_type="reference",
                    reference_to="ascendix__SubMarket__c")
    _add_mock_field(prop, "ascendix__GLA__c", filterable=True, sf_type="double",
                    formula=True)
    _add_mock_field(prop, "CreatedDate", sf_type="datetime")
    _add_mock_field(prop, "LastModifiedDate", sf_type="datetime")
    _add_mock_field(prop, "ascendix__Address__c")

    # Compact layout signals (T1)
    for f in ["Name", "ascendix__City__c", "ascendix__State__c",
              "ascendix__PropertyClass__c", "ascendix__PropertySubType__c",
              "ascendix__TotalSF__c"]:
        prop.ensure_field_score(f).compact_layout_appearances += 1

    # Search layout signals (T2)
    for f in ["Name", "ascendix__City__c", "ascendix__PropertyClass__c"]:
        prop.ensure_field_score(f).search_layout_appearances += 1

    # List view column signals (T4) — simulate multiple views
    lv_cols = {
        "Name": 5, "ascendix__City__c": 5, "ascendix__State__c": 4,
        "ascendix__PropertyClass__c": 4, "ascendix__TotalSF__c": 3,
        "ascendix__YearBuilt__c": 1, "ascendix__Status__c": 3,
    }
    for f, count in lv_cols.items():
        prop.ensure_field_score(f).list_view_column_appearances = count

    # List view filter signals
    lv_filters = {
        "ascendix__City__c": 3, "ascendix__State__c": 2,
        "ascendix__PropertyClass__c": 4, "ascendix__TotalSF__c": 2,
        "ascendix__Status__c": 2,
    }
    for f, count in lv_filters.items():
        prop.ensure_field_score(f).list_view_filter_appearances = count

    # Child relationships
    prop.child_relationships = [
        {"childSObject": "ascendix__Availability__c",
         "relationshipName": "Availabilities__r", "field": "ascendix__Property__c"},
        {"childSObject": "ascendix__Lease__c",
         "relationshipName": "Leases__r", "field": "ascendix__Property__c"},
        {"childSObject": "ascendix__Listing__c",
         "relationshipName": "Listings__r", "field": "ascendix__Property__c"},
        {"childSObject": "ascendix__PropertyNote__c",
         "relationshipName": "PropertyNotes__r", "field": "ascendix__Property__c"},
    ]

    # Dot-notation columns
    prop.dot_notation_columns = [
        "ascendix__Market__r.Name",
        "ascendix__SubMarket__r.Name",
    ]

    objects[prop.api_name] = prop

    # ----- Lease -----
    lease = ObjectMetadata("ascendix__Lease__c")
    lease.label = "Lease"
    lease.name_field = "Name"

    _add_mock_field(lease, "Name", name_field=True, filterable=True)
    _add_mock_field(lease, "ascendix__LeaseType__c", filterable=True, required=True)
    _add_mock_field(lease, "ascendix__Description__c")
    _add_mock_field(lease, "ascendix__LeasedSF__c", filterable=True, sf_type="double")
    _add_mock_field(lease, "ascendix__RatePSF__c", filterable=True, sf_type="currency")
    _add_mock_field(lease, "ascendix__TermCommencementDate__c", sf_type="date")
    _add_mock_field(lease, "ascendix__TermExpirationDate__c", sf_type="date")
    _add_mock_field(lease, "ascendix__Property__c", sf_type="reference",
                    reference_to="ascendix__Property__c")
    _add_mock_field(lease, "ascendix__Tenant__c", sf_type="reference",
                    reference_to="Account")
    _add_mock_field(lease, "ascendix__OwnerLandlord__c", sf_type="reference",
                    reference_to="Account")
    _add_mock_field(lease, "ascendix__Status__c", filterable=True, required=True)
    _add_mock_field(lease, "ascendix__Floor__c", filterable=True)
    _add_mock_field(lease, "ascendix__Suite__c")

    # Compact layout
    for f in ["Name", "ascendix__LeaseType__c", "ascendix__Property__c",
              "ascendix__Tenant__c", "ascendix__LeasedSF__c"]:
        lease.ensure_field_score(f).compact_layout_appearances += 1

    # Search layout
    for f in ["Name", "ascendix__LeaseType__c", "ascendix__Tenant__c"]:
        lease.ensure_field_score(f).search_layout_appearances += 1

    # List views
    lv_cols = {
        "Name": 4, "ascendix__LeaseType__c": 3, "ascendix__LeasedSF__c": 3,
        "ascendix__RatePSF__c": 2, "ascendix__Status__c": 3,
        "ascendix__TermExpirationDate__c": 2,
    }
    for f, count in lv_cols.items():
        lease.ensure_field_score(f).list_view_column_appearances = count

    lv_filters = {
        "ascendix__LeaseType__c": 2, "ascendix__Status__c": 2,
    }
    for f, count in lv_filters.items():
        lease.ensure_field_score(f).list_view_filter_appearances = count

    # Dot-notation columns from list views
    lease.dot_notation_columns = [
        "ascendix__Property__r.ascendix__City__c",
        "ascendix__Property__r.ascendix__State__c",
        "ascendix__Property__r.ascendix__PropertyClass__c",
        "ascendix__Property__r.ascendix__SubMarket__c",
    ]

    # Child relationships
    lease.child_relationships = [
        {"childSObject": "ascendix__LeasePeriod__c",
         "relationshipName": "LeasePeriods__r", "field": "ascendix__Lease__c"},
    ]

    objects[lease.api_name] = lease

    # ----- Availability -----
    avail = ObjectMetadata("ascendix__Availability__c")
    avail.label = "Availability"
    avail.name_field = "Name"

    _add_mock_field(avail, "Name", name_field=True, filterable=True)
    _add_mock_field(avail, "ascendix__AvailableDate__c", sf_type="date")
    _add_mock_field(avail, "ascendix__AvailableSF__c", filterable=True, sf_type="double")
    _add_mock_field(avail, "ascendix__AskingRatePSF__c", filterable=True, sf_type="currency")
    _add_mock_field(avail, "ascendix__SpaceType__c", filterable=True, required=True)
    _add_mock_field(avail, "ascendix__Floor__c", filterable=True)
    _add_mock_field(avail, "ascendix__Suite__c")
    _add_mock_field(avail, "ascendix__Property__c", sf_type="reference",
                    reference_to="ascendix__Property__c")
    _add_mock_field(avail, "ascendix__Status__c", filterable=True, required=True)
    _add_mock_field(avail, "ascendix__Description__c")
    _add_mock_field(avail, "ascendix__MaxContiguous__c", filterable=True, sf_type="double",
                    formula=True)
    _add_mock_field(avail, "ascendix__MinDivisible__c", filterable=True, sf_type="double")

    # Compact layout
    for f in ["Name", "ascendix__AvailableSF__c", "ascendix__SpaceType__c",
              "ascendix__Floor__c", "ascendix__Property__c"]:
        avail.ensure_field_score(f).compact_layout_appearances += 1

    # Search layout
    for f in ["Name", "ascendix__SpaceType__c"]:
        avail.ensure_field_score(f).search_layout_appearances += 1

    # List views
    lv_cols = {
        "Name": 3, "ascendix__AvailableSF__c": 3,
        "ascendix__AskingRatePSF__c": 2, "ascendix__SpaceType__c": 3,
        "ascendix__Status__c": 2,
    }
    for f, count in lv_cols.items():
        avail.ensure_field_score(f).list_view_column_appearances = count

    lv_filters = {
        "ascendix__SpaceType__c": 2, "ascendix__Status__c": 2,
    }
    for f, count in lv_filters.items():
        avail.ensure_field_score(f).list_view_filter_appearances = count

    # Dot-notation columns
    avail.dot_notation_columns = [
        "ascendix__Property__r.Name",
        "ascendix__Property__r.ascendix__City__c",
    ]

    # No children
    avail.child_relationships = []

    objects[avail.api_name] = avail

    return objects


def _add_mock_field(
    meta: ObjectMetadata,
    name: str,
    name_field: bool = False,
    required: bool = False,
    filterable: bool = False,
    formula: bool = False,
    sf_type: str = "string",
    reference_to: Optional[str] = None,
) -> None:
    """Helper to add a field to mock metadata and set intrinsic scores."""
    meta.fields[name] = {
        "name": name,
        "type": sf_type,
        "nameField": name_field,
        "nillable": not required,
        "createable": True,
        "filterable": filterable,
        "groupable": filterable,
        "calculated": formula,
        "referenceTo": [reference_to] if reference_to else [],
    }
    fs = meta.ensure_field_score(name)
    fs.is_name_field = name_field
    fs.is_required = required
    fs.is_filterable = filterable
    fs.is_formula = formula

    if sf_type == "reference" and reference_to:
        meta.reference_fields[name] = reference_to


# ===================================================================
# Mock parent fetcher (for --mock mode)
# ===================================================================

class MockParentFetcher:
    """Simulates parent compact layout / name field fetches for mock mode."""

    PARENT_COMPACT = {
        "Account": ["Name", "Industry", "BillingCity"],
        "ascendix__Property__c": [
            "Name", "ascendix__City__c", "ascendix__State__c",
            "ascendix__PropertyClass__c", "ascendix__PropertySubType__c",
            "ascendix__TotalSF__c",
        ],
        "ascendix__Market__c": ["Name"],
        "ascendix__SubMarket__c": ["Name"],
    }

    PARENT_NAME_FIELD = {
        "Account": "Name",
        "ascendix__Property__c": "Name",
        "ascendix__Market__c": "Name",
        "ascendix__SubMarket__c": "Name",
    }

    def fetch_parent_compact_fields(self, parent_obj: str) -> List[str]:
        return list(self.PARENT_COMPACT.get(parent_obj, ["Name"]))

    def fetch_parent_name_field(self, parent_obj: str) -> str:
        return self.PARENT_NAME_FIELD.get(parent_obj, "Name")


# ===================================================================
# Main entry point
# ===================================================================

def connect_salesforce(args) -> Any:
    """Create a simple_salesforce.Salesforce connection from CLI args / env vars."""
    try:
        from simple_salesforce import Salesforce
    except ImportError:
        print("ERROR: simple_salesforce is required for live mode.")
        print("Install with: pip install simple-salesforce")
        sys.exit(1)

    instance_url = args.instance_url or os.environ.get("SALESFORCE_INSTANCE_URL", "")
    username = args.username or os.environ.get("SALESFORCE_USERNAME", "")
    password = args.password or os.environ.get("SALESFORCE_PASSWORD", "")
    token = args.token or os.environ.get("SALESFORCE_SECURITY_TOKEN", "")

    if not all([instance_url, username, password]):
        print(
            "ERROR: Salesforce credentials required.\n"
            "Provide via --instance-url/--username/--password/--token flags\n"
            "or SALESFORCE_INSTANCE_URL/SALESFORCE_USERNAME/"
            "SALESFORCE_PASSWORD/SALESFORCE_SECURITY_TOKEN env vars.\n"
            "Or use --mock for testing without credentials."
        )
        sys.exit(1)

    # Parse domain from instance URL
    domain = instance_url.replace("https://", "").replace("http://", "")
    # For sandbox URLs like myorg.sandbox.my.salesforce.com
    # simple_salesforce wants the instance (domain minus .salesforce.com)
    # or we can pass instance_url directly

    sf = Salesforce(
        username=username,
        password=password,
        security_token=token,
        instance_url=instance_url,
        domain="test" if "sandbox" in instance_url.lower() else "login",
    )
    print(f"Connected to Salesforce: {sf.sf_instance}")
    return sf


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate denormalization config from Salesforce org metadata."
    )
    parser.add_argument(
        "--objects", nargs="+",
        default=[
            "ascendix__Property__c",
            "ascendix__Lease__c",
            "ascendix__Availability__c",
        ],
        help="Salesforce object API names to process.",
    )
    parser.add_argument(
        "--output", "-o", default="denorm_config.yaml",
        help="Output YAML file path (default: denorm_config.yaml).",
    )
    parser.add_argument(
        "--namespace-prefix", default="ascendix__",
        help="Namespace prefix for filtering child objects (default: ascendix__).",
    )
    parser.add_argument(
        "--mock", action="store_true",
        help="Use hardcoded mock metadata instead of live Salesforce.",
    )
    parser.add_argument("--instance-url", default="")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")

    args = parser.parse_args()

    target_set = set(args.objects)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if args.mock:
        print("Running in MOCK mode — using hardcoded Ascendix CRE metadata.")
        all_meta = build_mock_metadata()
        # Filter to requested objects
        meta_to_process = {
            k: v for k, v in all_meta.items() if k in target_set
        }
        if not meta_to_process:
            print(f"Warning: None of {args.objects} found in mock data. "
                  f"Available: {list(all_meta.keys())}")
            meta_to_process = all_meta

        fetcher = MockParentFetcher()
        configs: Dict[str, Dict[str, Any]] = {}
        for obj_name, meta in meta_to_process.items():
            print(f"\nProcessing {obj_name} ({meta.label})...")
            cfg = build_config_for_object(meta, fetcher, target_set, args.namespace_prefix)
            configs[obj_name] = cfg
            n_embed = len(cfg["embed_fields"])
            n_meta = len(cfg["metadata_fields"])
            n_parents = sum(len(v) for v in cfg["parents"].values())
            print(f"  {n_embed} embed fields, {n_meta} metadata fields, "
                  f"{n_parents} parent denorm fields, {len(cfg['children'])} child aggs")
    else:
        sf = connect_salesforce(args)
        harvester = SalesforceHarvester(sf)
        configs = {}
        for obj_name in args.objects:
            print(f"\nHarvesting metadata for {obj_name}...")
            meta = harvester.harvest_object(obj_name)
            print(f"  Scored {len(meta.field_scores)} fields")
            cfg = build_config_for_object(
                meta, harvester, target_set, args.namespace_prefix
            )
            configs[obj_name] = cfg
            n_embed = len(cfg["embed_fields"])
            n_meta = len(cfg["metadata_fields"])
            n_parents = sum(len(v) for v in cfg["parents"].values())
            print(f"  {n_embed} embed fields, {n_meta} metadata fields, "
                  f"{n_parents} parent denorm fields, {len(cfg['children'])} child aggs")

    # Render and write
    yaml_output = render_yaml(configs, generated_at)

    output_path = args.output
    with open(output_path, "w") as f:
        f.write(yaml_output)

    print(f"\nConfig written to {output_path}")
    print("Review the generated config and commit when ready.")


if __name__ == "__main__":
    main()
