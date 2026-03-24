"""Tests for Ascendix config refresh compiler, diffing, and storage."""

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
    ConfigArtifactStore,
    IMPACT_FIELD_SCOPE,
    IMPACT_OBJECT_SCOPE,
    IMPACT_PROMPT_ONLY,
    IMPACT_RELATIONSHIP,
    UNSAFE_APPLY_BLOCK_REASON,
    compile_config_artifact,
    diff_runtime_artifacts,
    execute_config_refresh,
    normalize_ascendix_source,
)
from lib.system_prompt import build_system_prompt, build_tool_definitions


def _make_raw_source() -> dict:
    selected_objects_json = json.dumps(
        [
            {
                "name": "ascendix__Property__c",
                "label": "Property",
                "isSearchable": True,
                "isSearchOrResultFieldsFiltered": True,
                "fields": [
                    {"name": "Name"},
                    {"name": "ascendix__City__c"},
                ],
            }
        ]
    )
    template = json.dumps(
        {
            "sectionsList": [
                {
                    "objectName": "ascendix__Property__c",
                    "fieldsList": [{"logicalName": "ascendix__City__c"}],
                },
                {
                    "objectName": "ascendix__Market__c",
                    "relationship": "ascendix__Market__r",
                    "fieldsList": [{"logicalName": "Name"}],
                },
            ],
            "resultColumns": [{"logicalName": "Name"}],
        }
    )
    return {
        "search_settings": [
            {
                "Name": "Selected Objects1",
                "ascendix_search__Value__c": selected_objects_json[40:],
            },
            {
                "Name": "Selected Objects",
                "ascendix_search__Value__c": selected_objects_json[:40],
            },
            {
                "Name": "Default Layout Property",
                "ascendix_search__Value__c": json.dumps(
                    [{"logicalName": "Name"}, {"logicalName": "ascendix__City__c"}]
                ),
            },
        ],
        "saved_searches": [
            {
                "Id": "a1",
                "Name": "Dallas Property Search",
                "ascendix_search__Template__c": template,
            }
        ],
    }


def _set_selected_objects(raw_source: dict, selected_objects: list[dict]) -> None:
    selected_objects_json = json.dumps(selected_objects)
    for setting in raw_source["search_settings"]:
        if setting["Name"] == "Selected Objects":
            setting["ascendix_search__Value__c"] = selected_objects_json[:40]
        elif setting["Name"] == "Selected Objects1":
            setting["ascendix_search__Value__c"] = selected_objects_json[40:]


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


class _FakeSalesforce:
    def query(self, soql: str) -> dict:
        if "SELECT Id FROM Organization" in soql:
            return {"records": [{"Id": "00DTEST"}]}
        raise AssertionError(f"Unexpected query: {soql}")


class _FakeRefreshSalesforce:
    def query(self, soql: str) -> dict:
        return {"records": []}

    def restful(self, path: str) -> dict:
        if path == "sobjects/ascendix__Property__c/describe":
            return {
                "label": "Property",
                "keyPrefix": "a0P",
                "childRelationships": [],
                "fields": [
                    {
                        "name": "Name",
                        "type": "string",
                        "nameField": True,
                        "nillable": True,
                        "createable": True,
                        "filterable": True,
                        "groupable": True,
                        "calculated": False,
                    },
                    {
                        "name": "ascendix__City__c",
                        "type": "string",
                        "nameField": False,
                        "nillable": True,
                        "createable": True,
                        "filterable": True,
                        "groupable": True,
                        "calculated": False,
                    },
                    {
                        "name": "ascendix__State__c",
                        "type": "string",
                        "nameField": False,
                        "nillable": True,
                        "createable": True,
                        "filterable": True,
                        "groupable": True,
                        "calculated": False,
                    },
                    {
                        "name": "ascendix__Status__c",
                        "type": "string",
                        "nameField": False,
                        "nillable": False,
                        "createable": True,
                        "filterable": True,
                        "groupable": True,
                        "calculated": False,
                    },
                ],
            }
        if path == "sobjects/ascendix__Property__c/describe/compactLayouts/":
            return {"compactLayouts": []}
        if path == "search/layout/?q=ascendix__Property__c":
            return []
        if path == "sobjects/ascendix__Property__c/describe/layouts":
            return {"layouts": []}
        if path == "sobjects/ascendix__Property__c/listviews":
            return {"listviews": []}
        raise AssertionError(f"Unexpected REST path: {path}")


def test_normalize_ascendix_source_reconstructs_actual_payload_shape():
    normalized = normalize_ascendix_source(_make_raw_source())

    assert normalized["selected_objects"][0]["api_name"] == "ascendix__Property__c"
    assert normalized["selected_objects"][0]["field_allowlist"] == ["Name", "ascendix__City__c"]
    assert normalized["default_layouts"]["ascendix__Property__c"] == ["Name", "ascendix__City__c"]
    assert normalized["saved_searches"][0]["primary_object"] == "ascendix__Property__c"
    assert normalized["saved_searches"][0]["relationship_paths"] == ["ascendix__Market__r"]


def test_compile_config_artifact_applies_field_allowlist_and_builds_query_scope():
    result = compile_config_artifact(
        org_id="00DTEST",
        raw_source=_make_raw_source(),
        target_objects=["ascendix__Property__c"],
        mock=True,
    )

    property_config = result.denorm_config["ascendix__Property__c"]
    assert set(property_config["embed_fields"]) == {"Name", "ascendix__City__c"}
    assert property_config["metadata_fields"] == []
    assert result.query_scope["objects"]["ascendix__Property__c"]["result_columns"] == [
        "Name",
        "ascendix__City__c",
    ]
    assert result.impact_classification == IMPACT_OBJECT_SCOPE


def test_compile_config_artifact_live_path_honors_selected_object_field_allowlist():
    result = compile_config_artifact(
        sf=_FakeRefreshSalesforce(),
        org_id="00DTEST",
        raw_source=_make_raw_source(),
        target_objects=["ascendix__Property__c"],
    )

    property_config = result.denorm_config["ascendix__Property__c"]
    assert property_config["embed_fields"] == ["Name"]
    assert property_config["metadata_fields"] == ["ascendix__City__c"]


def test_diff_runtime_artifacts_classifies_scope_changes():
    previous = {
        "denorm_config": {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": [],
                "parents": {},
            }
        },
        "query_scope": {"objects": {"ascendix__Property__c": {"result_columns": ["Name"]}}},
    }

    prompt_only_candidate = {
        "denorm_config": previous["denorm_config"],
        "query_scope": {"objects": {"ascendix__Property__c": {"result_columns": ["Name", "City"]}}},
    }
    assert diff_runtime_artifacts(previous, prompt_only_candidate)["classification"] == IMPACT_PROMPT_ONLY

    field_candidate = {
        "denorm_config": {
            "ascendix__Property__c": {
                "embed_fields": ["Name", "ascendix__City__c"],
                "metadata_fields": [],
                "parents": {},
            }
        },
        "query_scope": previous["query_scope"],
    }
    assert diff_runtime_artifacts(previous, field_candidate)["classification"] == IMPACT_FIELD_SCOPE

    relationship_candidate = {
        "denorm_config": {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": [],
                "parents": {"ascendix__Market__c": ["Name"]},
            }
        },
        "query_scope": previous["query_scope"],
    }
    assert diff_runtime_artifacts(previous, relationship_candidate)["classification"] == IMPACT_RELATIONSHIP


def test_config_artifact_store_writes_versioned_artifacts_and_active_pointer():
    result = compile_config_artifact(
        org_id="00DTEST",
        raw_source=_make_raw_source(),
        target_objects=["ascendix__Property__c"],
        mock=True,
    )
    fake_s3 = _FakeS3()
    fake_ssm = _FakeSSM()
    store = ConfigArtifactStore(
        s3_client=fake_s3,
        ssm_client=fake_ssm,
        bucket="config-bucket",
    )

    keys = store.write_candidate(result)
    assert keys["compiled"].endswith(f"{result.version_id}.yaml")
    assert keys["source"].endswith(f"{result.version_id}.json")
    assert keys["plan"].endswith(f"{result.version_id}.json")

    compiled_payload = yaml.safe_load(fake_s3.objects[("config-bucket", keys["compiled"])])
    assert compiled_payload["version_id"] == result.version_id

    store.set_active_version(
        "00DTEST",
        result.version_id,
        applied_by="unit-test",
        reason="manual_apply",
    )
    active_artifact = store.load_active_artifact("00DTEST")
    assert active_artifact["version_id"] == result.version_id


def test_execute_config_refresh_auto_applies_prompt_only_changes():
    base_result = compile_config_artifact(
        sf=_FakeRefreshSalesforce(),
        org_id="00DTEST",
        raw_source=_make_raw_source(),
        target_objects=["ascendix__Property__c"],
    )
    fake_s3 = _FakeS3()
    fake_ssm = _FakeSSM()
    store = ConfigArtifactStore(
        s3_client=fake_s3,
        ssm_client=fake_ssm,
        bucket="config-bucket",
    )
    store.write_candidate(base_result)
    store.set_active_version(
        "00DTEST",
        base_result.version_id,
        applied_by="seed",
        reason="manual_apply",
    )

    prompt_only_source = _make_raw_source()
    prompt_only_source["search_settings"][-1]["ascendix_search__Value__c"] = json.dumps(
        [{"logicalName": "Name"}]
    )
    refresh = execute_config_refresh(
        sf=_FakeRefreshSalesforce(),
        org_id="00DTEST",
        store=store,
        raw_source=prompt_only_source,
        target_objects=["ascendix__Property__c"],
    )

    compile_result = refresh["compile_result"]
    assert compile_result.impact_classification == IMPACT_PROMPT_ONLY
    assert refresh["activated"] is True


def test_prompt_only_changes_modify_prompt_and_tool_outputs():
    base_result = compile_config_artifact(
        sf=_FakeRefreshSalesforce(),
        org_id="00DTEST",
        raw_source=_make_raw_source(),
        target_objects=["ascendix__Property__c"],
    )
    prompt_only_source = _make_raw_source()
    prompt_only_source["search_settings"][-1]["ascendix_search__Value__c"] = json.dumps(
        [{"logicalName": "Name"}]
    )
    prompt_result = compile_config_artifact(
        sf=_FakeRefreshSalesforce(),
        org_id="00DTEST",
        raw_source=prompt_only_source,
        previous_artifact=base_result.artifact,
        target_objects=["ascendix__Property__c"],
    )

    assert prompt_result.impact_classification == IMPACT_PROMPT_ONLY
    assert build_system_prompt(
        base_result.denorm_config,
        query_scope=base_result.query_scope,
    ) != build_system_prompt(
        prompt_result.denorm_config,
        query_scope=prompt_result.query_scope,
    )
    assert build_tool_definitions(
        base_result.denorm_config,
        query_scope=base_result.query_scope,
    ) != build_tool_definitions(
        prompt_result.denorm_config,
        query_scope=prompt_result.query_scope,
    )


def test_execute_config_refresh_blocks_manual_activation_for_non_safe_changes():
    base_result = compile_config_artifact(
        sf=_FakeRefreshSalesforce(),
        org_id="00DTEST",
        raw_source=_make_raw_source(),
        target_objects=["ascendix__Property__c"],
    )
    fake_s3 = _FakeS3()
    fake_ssm = _FakeSSM()
    store = ConfigArtifactStore(
        s3_client=fake_s3,
        ssm_client=fake_ssm,
        bucket="config-bucket",
    )
    store.write_candidate(base_result)
    store.set_active_version(
        "00DTEST",
        base_result.version_id,
        applied_by="seed",
        reason="manual_apply",
    )

    field_change_source = _make_raw_source()
    _set_selected_objects(
        field_change_source,
        [
            {
                "name": "ascendix__Property__c",
                "label": "Property",
                "isSearchable": True,
                "isSearchOrResultFieldsFiltered": True,
                "fields": [
                    {"name": "Name"},
                    {"name": "ascendix__City__c"},
                    {"name": "ascendix__Status__c"},
                ],
            }
        ],
    )
    refresh = execute_config_refresh(
        sf=_FakeRefreshSalesforce(),
        org_id="00DTEST",
        store=store,
        raw_source=field_change_source,
        target_objects=["ascendix__Property__c"],
        apply=True,
    )

    assert refresh["compile_result"].impact_classification == IMPACT_FIELD_SCOPE
    assert refresh["activated"] is False
    assert refresh["activation_blocked_reason"] == UNSAFE_APPLY_BLOCK_REASON
    assert store.resolve_active_version("00DTEST") == base_result.version_id
