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
    APPROVAL_APPLIED,
    APPROVAL_PENDING,
    APPROVAL_ROLLED_BACK,
    ConfigArtifactStore,
    IMPACT_FIELD_SCOPE,
    IMPACT_NONE,
    IMPACT_OBJECT_SCOPE,
    IMPACT_PROMPT_ONLY,
    IMPACT_RELATIONSHIP,
    ApplyResult,
    _build_apply_plan,
    compile_config_artifact,
    diff_runtime_artifacts,
    execute_config_refresh,
    execute_targeted_apply,
    normalize_ascendix_source,
    rollback_to_version,
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


def test_execute_config_refresh_pending_approval_for_non_safe_without_apply_flag():
    """Non-safe change without --apply writes pending approval state."""
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
        apply=False,
    )

    assert refresh["compile_result"].impact_classification == IMPACT_FIELD_SCOPE
    assert refresh["activated"] is False
    assert "requires operator approval" in refresh["activation_blocked_reason"]
    assert store.resolve_active_version("00DTEST") == base_result.version_id

    approval = store.load_approval_state("00DTEST", refresh["compile_result"].version_id)
    assert approval is not None
    assert approval["state"] == APPROVAL_PENDING


def test_execute_config_refresh_targeted_apply_with_callback():
    """Non-safe change with --apply and reindex callback activates after reindex."""
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

    reindex_calls = []

    def fake_reindex(object_name, action_type, full_sync=False):
        reindex_calls.append({"object": object_name, "action": action_type, "full_sync": full_sync})
        return {"records_synced": 10}

    refresh = execute_config_refresh(
        sf=_FakeRefreshSalesforce(),
        org_id="00DTEST",
        store=store,
        raw_source=field_change_source,
        target_objects=["ascendix__Property__c"],
        apply=True,
        reindex_callback=fake_reindex,
    )

    assert refresh["compile_result"].impact_classification == IMPACT_FIELD_SCOPE
    assert refresh["activated"] is True
    assert len(reindex_calls) > 0
    assert refresh["apply_result"] is not None
    assert refresh["apply_result"].activated is True


def test_execute_config_refresh_targeted_apply_deferred_without_callback():
    """Non-safe change with --apply but no callback defers activation."""
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
        reindex_callback=None,
    )

    assert refresh["compile_result"].impact_classification == IMPACT_FIELD_SCOPE
    assert refresh["activated"] is False
    assert "reindex deferred" in refresh["activation_blocked_reason"]


def test_build_apply_plan_object_add():
    diff = {
        "classification": IMPACT_OBJECT_SCOPE,
        "added_objects": ["ascendix__NewObj__c"],
        "removed_objects": [],
        "field_changes": {},
        "relationship_changes": {},
    }
    plan = _build_apply_plan(diff)
    assert plan["requires_reindex"] is True
    assert any(a["action"] == "seed_new_object" for a in plan["actions"])


def test_build_apply_plan_object_remove():
    diff = {
        "classification": IMPACT_OBJECT_SCOPE,
        "added_objects": [],
        "removed_objects": ["ascendix__OldObj__c"],
        "field_changes": {},
        "relationship_changes": {},
    }
    plan = _build_apply_plan(diff)
    assert any(a["action"] == "retire_object" for a in plan["actions"])
    retire_action = [a for a in plan["actions"] if a["action"] == "retire_object"][0]
    assert retire_action["requires_reindex"] is False


def test_build_apply_plan_field_scope():
    diff = {
        "classification": IMPACT_FIELD_SCOPE,
        "added_objects": [],
        "removed_objects": [],
        "field_changes": {
            "ascendix__Property__c": {
                "added_fields": ["ascendix__State__c"],
                "removed_fields": [],
            }
        },
        "relationship_changes": {},
    }
    plan = _build_apply_plan(diff)
    assert plan["requires_reindex"] is True
    assert any(a["action"] == "reindex_field_add" for a in plan["actions"])


def test_build_apply_plan_relationship():
    diff = {
        "classification": IMPACT_RELATIONSHIP,
        "added_objects": [],
        "removed_objects": [],
        "field_changes": {},
        "relationship_changes": {
            "ascendix__Property__c": {
                "previous": {},
                "candidate": {"ascendix__Market__c": ["Name"]},
            }
        },
    }
    plan = _build_apply_plan(diff)
    assert plan["requires_reindex"] is True
    assert any(a["action"] == "reindex_relationship" for a in plan["actions"])


def test_rollback_to_version():
    result_v1 = compile_config_artifact(
        sf=_FakeRefreshSalesforce(),
        org_id="00DTEST",
        raw_source=_make_raw_source(),
        target_objects=["ascendix__Property__c"],
    )
    result_v2 = compile_config_artifact(
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
    store.write_candidate(result_v1)
    store.set_active_version("00DTEST", result_v1.version_id, applied_by="seed", reason="initial")
    store.write_candidate(result_v2)
    store.set_active_version("00DTEST", result_v2.version_id, applied_by="test", reason="upgrade")

    assert store.resolve_active_version("00DTEST") == result_v2.version_id

    rollback = rollback_to_version(
        store=store,
        org_id="00DTEST",
        target_version_id=result_v1.version_id,
        rolled_back_by="operator",
        reason="test rollback",
    )

    assert rollback["rolled_back_to"] == result_v1.version_id
    assert store.resolve_active_version("00DTEST") == result_v1.version_id


def test_cli_reindex_callback_invokes_poll_sync_lambda():
    """Verify _make_reindex_callback invokes the poll_sync Lambda correctly."""
    import io
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

    from run_config_refresh import _make_reindex_callback

    invocations = []

    class FakeLambdaClient:
        def invoke(self, **kwargs):
            invocations.append(kwargs)
            return {
                "StatusCode": 200,
                "Payload": io.BytesIO(json.dumps({
                    "statusCode": 200,
                    "summary": {"ascendix__Property__c": {"records_synced": 15}},
                }).encode("utf-8")),
            }

    callback = _make_reindex_callback(
        lambda_client=FakeLambdaClient(),
        poll_sync_function_name="test-poll-sync",
    )

    result = callback(
        object_name="ascendix__Property__c",
        action_type="reindex_field_add",
        full_sync=False,
    )

    assert len(invocations) == 1
    assert invocations[0]["FunctionName"] == "test-poll-sync"
    payload = json.loads(invocations[0]["Payload"])
    assert payload["objects"] == ["ascendix__Property__c"]
    assert payload["full_sync"] is False
    assert result["statusCode"] == 200

    # seed_new_object should force full_sync=True
    result2 = callback(
        object_name="ascendix__NewObj__c",
        action_type="seed_new_object",
        full_sync=False,
    )
    payload2 = json.loads(invocations[1]["Payload"])
    assert payload2["full_sync"] is True
