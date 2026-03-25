"""End-to-end config refresh scenario validation (Task 4.9.9).

Validates the full control-plane loop against four admin config change
scenarios: field add, object add, relationship-path change, and
prompt-only change.

For each scenario, records:
  - detected diff
  - impact classification
  - applied action
  - resulting active version
  - structural parity evidence

Uses mock Salesforce metadata (mock=True) so tests run without
credentials. The structural validation harness from 4.9.10 attaches
parity evidence to each scenario.
"""

from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

import yaml

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from lib.config_refresh import (
    APPROVAL_APPLIED,
    APPROVAL_PENDING,
    ConfigArtifactStore,
    IMPACT_FIELD_SCOPE,
    IMPACT_NONE,
    IMPACT_OBJECT_SCOPE,
    IMPACT_PROMPT_ONLY,
    IMPACT_RELATIONSHIP,
    compile_config_artifact,
    execute_config_refresh,
    normalize_ascendix_source,
)
from lib.structural_validation import (
    extract_fixtures,
    validate_structural_parity,
)


# ---------------------------------------------------------------------------
# Shared test fakes
# ---------------------------------------------------------------------------


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **_: object) -> None:
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}


class _FakeSSM:
    class exceptions:
        class ParameterNotFound(Exception):
            pass

    def __init__(self) -> None:
        self.parameters: dict[str, str] = {}

    def put_parameter(self, *, Name: str, Value: str, **_: object) -> None:
        self.parameters[Name] = Value

    def get_parameter(self, *, Name: str) -> dict:
        if Name not in self.parameters:
            raise self.exceptions.ParameterNotFound(Name)
        return {"Parameter": {"Value": self.parameters[Name]}}


def _store(s3=None, ssm=None) -> ConfigArtifactStore:
    return ConfigArtifactStore(
        s3_client=s3 or _FakeS3(),
        ssm_client=ssm or _FakeSSM(),
        bucket="e2e-test-bucket",
    )


# ---------------------------------------------------------------------------
# Baseline source builder
# ---------------------------------------------------------------------------


def _baseline_source() -> dict:
    """Baseline Ascendix Search config with Property as sole searchable object."""
    selected_objects = json.dumps([
        {
            "name": "ascendix__Property__c",
            "label": "Property",
            "isSearchable": True,
            "isSearchOrResultFieldsFiltered": True,
            "fields": [
                {"name": "Name"},
                {"name": "ascendix__City__c"},
            ],
        },
    ])
    template = json.dumps({
        "sectionsList": [
            {
                "objectName": "ascendix__Property__c",
                "fieldsList": [{"logicalName": "ascendix__City__c"}],
            },
        ],
        "resultColumns": [{"logicalName": "Name"}],
    })
    return {
        "search_settings": [
            {"Name": "Selected Objects", "ascendix_search__Value__c": selected_objects},
            {
                "Name": "Default Layout Property",
                "ascendix_search__Value__c": json.dumps([
                    {"logicalName": "Name"},
                    {"logicalName": "ascendix__City__c"},
                ]),
            },
        ],
        "saved_searches": [
            {
                "Id": "ss1",
                "Name": "Property Search",
                "ascendix_search__Template__c": template,
            },
        ],
    }


def _seed_baseline(fake_s3: _FakeS3, fake_ssm: _FakeSSM) -> dict:
    """Compile and activate a baseline version. Returns compile result dict."""
    store = _store(fake_s3, fake_ssm)
    result = compile_config_artifact(
        org_id="00DTEST",
        raw_source=_baseline_source(),
        target_objects=["ascendix__Property__c"],
        mock=True,
    )
    store.write_candidate(result)
    store.set_active_version(
        "00DTEST",
        result.version_id,
        applied_by="seed",
        reason="initial_seed",
    )
    return {
        "version_id": result.version_id,
        "artifact": result.artifact,
        "normalized_source": result.normalized_source,
    }


def _record_evidence(
    scenario: str,
    diff: dict,
    classification: str,
    activated: bool,
    version_id: str,
    structural_report: dict,
    **extra: object,
) -> dict:
    """Build a durable evidence record for a scenario."""
    return {
        "scenario": scenario,
        "detected_diff": diff,
        "impact_classification": classification,
        "activated": activated,
        "resulting_active_version": version_id,
        "structural_parity_evidence": structural_report,
        **extra,
    }


# ---------------------------------------------------------------------------
# Scenario 1: Field Add
# ---------------------------------------------------------------------------


class TestFieldAddScenario:
    """Admin adds ascendix__State__c to Property's search fields."""

    def test_field_add_end_to_end(self):
        fake_s3 = _FakeS3()
        fake_ssm = _FakeSSM()
        baseline = _seed_baseline(fake_s3, fake_ssm)
        store = _store(fake_s3, fake_ssm)

        # Admin adds State field to Property
        field_add_source = _baseline_source()
        field_add_source["search_settings"][0]["ascendix_search__Value__c"] = json.dumps([
            {
                "name": "ascendix__Property__c",
                "label": "Property",
                "isSearchable": True,
                "isSearchOrResultFieldsFiltered": True,
                "fields": [
                    {"name": "Name"},
                    {"name": "ascendix__City__c"},
                    {"name": "ascendix__State__c"},
                ],
            },
        ])

        reindex_log = []

        def fake_reindex(object_name, action_type, full_sync=False):
            reindex_log.append({"object": object_name, "action": action_type})
            return {"records_synced": 5}

        refresh = execute_config_refresh(
            org_id="00DTEST",
            store=store,
            raw_source=field_add_source,
            target_objects=["ascendix__Property__c"],
            apply=True,
            applied_by="e2e_test",
            namespace_prefix="ascendix__",
            reindex_callback=fake_reindex,
            mock=True,
        )

        cr = refresh["compile_result"]

        # Assertions
        assert cr.impact_classification == IMPACT_FIELD_SCOPE
        assert refresh["activated"] is True
        assert len(reindex_log) > 0

        # Structural validation
        report = validate_structural_parity(cr.normalized_source, cr.artifact)
        evidence = _record_evidence(
            scenario="field_add",
            diff=cr.diff,
            classification=cr.impact_classification,
            activated=refresh["activated"],
            version_id=cr.version_id,
            structural_report=report.to_dict(),
            reindex_log=reindex_log,
        )

        assert evidence["impact_classification"] == IMPACT_FIELD_SCOPE
        assert evidence["activated"] is True
        assert evidence["structural_parity_evidence"]["passed"] is True
        assert store.resolve_active_version("00DTEST") == cr.version_id


# ---------------------------------------------------------------------------
# Scenario 2: Object Add
# ---------------------------------------------------------------------------


class TestObjectAddScenario:
    """Admin adds Lease as a new searchable object."""

    def test_object_add_end_to_end(self):
        fake_s3 = _FakeS3()
        fake_ssm = _FakeSSM()
        baseline = _seed_baseline(fake_s3, fake_ssm)
        store = _store(fake_s3, fake_ssm)

        # Admin adds Lease object
        object_add_source = _baseline_source()
        existing_objects = json.loads(
            object_add_source["search_settings"][0]["ascendix_search__Value__c"]
        )
        existing_objects.append({
            "name": "ascendix__Lease__c",
            "label": "Lease",
            "isSearchable": True,
            "isSearchOrResultFieldsFiltered": False,
            "fields": [],
        })
        object_add_source["search_settings"][0]["ascendix_search__Value__c"] = json.dumps(existing_objects)

        reindex_log = []

        def fake_reindex(object_name, action_type, full_sync=False):
            reindex_log.append({"object": object_name, "action": action_type, "full_sync": full_sync})
            return {"records_synced": 20}

        refresh = execute_config_refresh(
            org_id="00DTEST",
            store=store,
            raw_source=object_add_source,
            target_objects=["ascendix__Property__c", "ascendix__Lease__c"],
            apply=True,
            applied_by="e2e_test",
            namespace_prefix="ascendix__",
            reindex_callback=fake_reindex,
            mock=True,
        )

        cr = refresh["compile_result"]

        assert cr.impact_classification == IMPACT_OBJECT_SCOPE
        assert refresh["activated"] is True
        assert any(r["action"] == "seed_new_object" for r in reindex_log)

        # Structural validation
        report = validate_structural_parity(cr.normalized_source, cr.artifact)
        evidence = _record_evidence(
            scenario="object_add",
            diff=cr.diff,
            classification=cr.impact_classification,
            activated=refresh["activated"],
            version_id=cr.version_id,
            structural_report=report.to_dict(),
            reindex_log=reindex_log,
        )

        assert evidence["impact_classification"] == IMPACT_OBJECT_SCOPE
        assert evidence["activated"] is True
        assert "ascendix__Lease__c" in cr.diff["added_objects"]


# ---------------------------------------------------------------------------
# Scenario 3: Relationship-Path Change
# ---------------------------------------------------------------------------


class TestRelationshipPathChangeScenario:
    """Admin adds an OwnerLandlord cross-object filter with a new field to Property saved search.

    Uses OwnerLandlord__r.Phone — a field not in the mock baseline's
    dot_notation_columns — so the parents dict actually changes and the
    diff classifies as IMPACT_RELATIONSHIP.
    """

    def test_relationship_path_change_end_to_end(self):
        fake_s3 = _FakeS3()
        fake_ssm = _FakeSSM()
        baseline = _seed_baseline(fake_s3, fake_ssm)
        store = _store(fake_s3, fake_ssm)

        # Admin adds OwnerLandlord relationship with Phone field to saved search
        rel_change_source = _baseline_source()
        new_template = json.dumps({
            "sectionsList": [
                {
                    "objectName": "ascendix__Property__c",
                    "fieldsList": [{"logicalName": "ascendix__City__c"}],
                },
                {
                    "objectName": "Account",
                    "relationship": "ascendix__OwnerLandlord__r",
                    "fieldsList": [{"logicalName": "Phone"}],
                },
            ],
            "resultColumns": [{"logicalName": "Name"}],
        })
        rel_change_source["saved_searches"][0]["ascendix_search__Template__c"] = new_template

        reindex_log = []

        def fake_reindex(object_name, action_type, full_sync=False):
            reindex_log.append({"object": object_name, "action": action_type})
            return {"records_synced": 8}

        # Run through the full apply workflow
        refresh = execute_config_refresh(
            org_id="00DTEST",
            store=store,
            raw_source=rel_change_source,
            target_objects=["ascendix__Property__c"],
            apply=True,
            applied_by="e2e_test",
            reindex_callback=fake_reindex,
            mock=True,
        )

        cr = refresh["compile_result"]

        # Must classify as relationship_change since parents actually changed
        assert cr.impact_classification == IMPACT_RELATIONSHIP
        assert refresh["activated"] is True
        assert len(reindex_log) > 0
        assert any(r["action"] == "reindex_relationship" for r in reindex_log)

        # The new parent field should be in the denorm config
        owner_parents = cr.denorm_config["ascendix__Property__c"]["parents"].get(
            "ascendix__OwnerLandlord__c", []
        )
        assert "Phone" in owner_parents

        # query_scope should include the relationship path
        property_scope = cr.query_scope.get("objects", {}).get("ascendix__Property__c", {})
        assert "ascendix__OwnerLandlord__r" in property_scope.get("relationship_paths", [])

        # Structural validation
        report = validate_structural_parity(cr.normalized_source, cr.artifact)
        fixture = extract_fixtures(cr.normalized_source)
        assert "ascendix__OwnerLandlord__r" in fixture.relationship_paths.get("ascendix__Property__c", [])

        evidence = _record_evidence(
            scenario="relationship_path_change",
            diff=cr.diff,
            classification=cr.impact_classification,
            activated=refresh["activated"],
            version_id=cr.version_id,
            structural_report=report.to_dict(),
            reindex_log=reindex_log,
        )

        assert evidence["impact_classification"] == IMPACT_RELATIONSHIP
        assert evidence["activated"] is True
        assert evidence["structural_parity_evidence"]["passed"] is True


# ---------------------------------------------------------------------------
# Scenario 4: Prompt-Only Change
# ---------------------------------------------------------------------------


class TestPromptOnlyChangeScenario:
    """Admin changes only the default layout columns (no field/relationship change)."""

    def test_prompt_only_change_end_to_end(self):
        fake_s3 = _FakeS3()
        fake_ssm = _FakeSSM()
        baseline = _seed_baseline(fake_s3, fake_ssm)
        store = _store(fake_s3, fake_ssm)

        # Admin changes Default Layout columns (prompt-only)
        prompt_source = _baseline_source()
        prompt_source["search_settings"][1]["ascendix_search__Value__c"] = json.dumps([
            {"logicalName": "Name"},
        ])

        refresh = execute_config_refresh(
            org_id="00DTEST",
            store=store,
            raw_source=prompt_source,
            target_objects=["ascendix__Property__c"],
            apply=False,
            applied_by="e2e_test",
            namespace_prefix="ascendix__",
            mock=True,
        )

        cr = refresh["compile_result"]

        assert cr.impact_classification == IMPACT_PROMPT_ONLY
        assert refresh["activated"] is True  # prompt_only auto-applies

        # Structural validation
        report = validate_structural_parity(cr.normalized_source, cr.artifact)
        evidence = _record_evidence(
            scenario="prompt_only_change",
            diff=cr.diff,
            classification=cr.impact_classification,
            activated=refresh["activated"],
            version_id=cr.version_id,
            structural_report=report.to_dict(),
        )

        assert evidence["impact_classification"] == IMPACT_PROMPT_ONLY
        assert evidence["activated"] is True
        assert evidence["structural_parity_evidence"]["passed"] is True
        assert store.resolve_active_version("00DTEST") == cr.version_id


# ---------------------------------------------------------------------------
# Aggregate evidence artifact
# ---------------------------------------------------------------------------


class TestEvidenceArtifactGeneration:
    """Generate a combined evidence artifact for all four scenarios."""

    def test_generates_combined_evidence(self, tmp_path: Path):
        """Run all scenarios and write combined evidence to a JSON file."""
        all_evidence: list[dict] = []

        # --- Field add ---
        fake_s3 = _FakeS3()
        fake_ssm = _FakeSSM()
        _seed_baseline(fake_s3, fake_ssm)
        store = _store(fake_s3, fake_ssm)

        field_source = _baseline_source()
        field_source["search_settings"][0]["ascendix_search__Value__c"] = json.dumps([{
            "name": "ascendix__Property__c",
            "label": "Property",
            "isSearchable": True,
            "isSearchOrResultFieldsFiltered": True,
            "fields": [{"name": "Name"}, {"name": "ascendix__City__c"}, {"name": "ascendix__State__c"}],
        }])

        r = execute_config_refresh(
            org_id="00DTEST", store=store,
            raw_source=field_source, target_objects=["ascendix__Property__c"],
            apply=True, reindex_callback=lambda **kw: {"ok": True}, mock=True,
        )
        report = validate_structural_parity(r["compile_result"].normalized_source, r["compile_result"].artifact)
        all_evidence.append(_record_evidence(
            "field_add", r["compile_result"].diff, r["compile_result"].impact_classification,
            r["activated"], r["compile_result"].version_id, report.to_dict(),
        ))

        # --- Object add ---
        fake_s3_2 = _FakeS3()
        fake_ssm_2 = _FakeSSM()
        _seed_baseline(fake_s3_2, fake_ssm_2)
        store2 = _store(fake_s3_2, fake_ssm_2)

        obj_source = _baseline_source()
        objs = json.loads(obj_source["search_settings"][0]["ascendix_search__Value__c"])
        objs.append({"name": "ascendix__Lease__c", "label": "Lease", "isSearchable": True,
                      "isSearchOrResultFieldsFiltered": False, "fields": []})
        obj_source["search_settings"][0]["ascendix_search__Value__c"] = json.dumps(objs)

        r2 = execute_config_refresh(
            org_id="00DTEST", store=store2,
            raw_source=obj_source, target_objects=["ascendix__Property__c", "ascendix__Lease__c"],
            apply=True, reindex_callback=lambda **kw: {"ok": True}, mock=True,
        )
        report2 = validate_structural_parity(r2["compile_result"].normalized_source, r2["compile_result"].artifact)
        all_evidence.append(_record_evidence(
            "object_add", r2["compile_result"].diff, r2["compile_result"].impact_classification,
            r2["activated"], r2["compile_result"].version_id, report2.to_dict(),
        ))

        # --- Relationship path change ---
        fake_s3_3 = _FakeS3()
        fake_ssm_3 = _FakeSSM()
        _seed_baseline(fake_s3_3, fake_ssm_3)
        store3 = _store(fake_s3_3, fake_ssm_3)

        rel_source = _baseline_source()
        rel_source["saved_searches"][0]["ascendix_search__Template__c"] = json.dumps({
            "sectionsList": [
                {"objectName": "ascendix__Property__c", "fieldsList": [{"logicalName": "ascendix__City__c"}]},
                {"objectName": "Account", "relationship": "ascendix__OwnerLandlord__r",
                 "fieldsList": [{"logicalName": "Phone"}]},
            ],
            "resultColumns": [{"logicalName": "Name"}],
        })

        r3 = execute_config_refresh(
            org_id="00DTEST", store=store3,
            raw_source=rel_source, target_objects=["ascendix__Property__c"],
            apply=True, reindex_callback=lambda **kw: {"ok": True}, mock=True,
        )
        report3 = validate_structural_parity(r3["compile_result"].normalized_source, r3["compile_result"].artifact)
        all_evidence.append(_record_evidence(
            "relationship_path_change", r3["compile_result"].diff, r3["compile_result"].impact_classification,
            r3["activated"], r3["compile_result"].version_id, report3.to_dict(),
        ))

        # --- Prompt only ---
        fake_s3_4 = _FakeS3()
        fake_ssm_4 = _FakeSSM()
        _seed_baseline(fake_s3_4, fake_ssm_4)
        store4 = _store(fake_s3_4, fake_ssm_4)

        prompt_source = _baseline_source()
        prompt_source["search_settings"][1]["ascendix_search__Value__c"] = json.dumps([{"logicalName": "Name"}])

        r4 = execute_config_refresh(
            org_id="00DTEST", store=store4,
            raw_source=prompt_source, target_objects=["ascendix__Property__c"],
            mock=True,
        )
        report4 = validate_structural_parity(r4["compile_result"].normalized_source, r4["compile_result"].artifact)
        all_evidence.append(_record_evidence(
            "prompt_only_change", r4["compile_result"].diff, r4["compile_result"].impact_classification,
            r4["activated"], r4["compile_result"].version_id, report4.to_dict(),
        ))

        # Write combined evidence artifact
        evidence_path = tmp_path / "e2e_config_refresh_evidence.json"
        evidence_path.write_text(json.dumps(all_evidence, indent=2, sort_keys=True))

        # Verify all four scenarios have evidence
        assert len(all_evidence) == 4
        scenarios = {e["scenario"] for e in all_evidence}
        assert scenarios == {"field_add", "object_add", "relationship_path_change", "prompt_only_change"}

        # Verify each has required fields
        for e in all_evidence:
            assert "detected_diff" in e
            assert "impact_classification" in e
            assert "resulting_active_version" in e
            assert "structural_parity_evidence" in e
            assert e["structural_parity_evidence"]["passed"] is True
