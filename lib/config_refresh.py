"""Ascendix Search config compiler, diffing, and artifact storage helpers.

This module turns the live Ascendix Search payload model into a reusable
control-plane flow that can be shared by CLI and Lambda entry points.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import yaml

LOG = logging.getLogger(__name__)

ARTIFACT_SCHEMA_VERSION = 1
CONFIG_S3_PREFIX = "config"
CONFIG_SSM_PREFIX = "/salesforce-ai-search/config"

IMPACT_NONE = "none"
IMPACT_PROMPT_ONLY = "prompt_only"
IMPACT_FIELD_SCOPE = "field_scope_change"
IMPACT_RELATIONSHIP = "relationship_change"
IMPACT_OBJECT_SCOPE = "object_scope_change"

AUTO_APPLY_IMPACTS = {IMPACT_NONE, IMPACT_PROMPT_ONLY}

# Approval states for the operator review flow
APPROVAL_PENDING = "pending_approval"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_APPLIED = "applied"
APPROVAL_ROLLED_BACK = "rolled_back"

_SELECTED_OBJECTS_RE = re.compile(r"^Selected Objects(?P<index>\d+)?$")
_DEFAULT_LAYOUT_RE = re.compile(r"^Default Layout(?P<suffix>.*)$")


@dataclass
class CompileResult:
    """Shared compiler output for CLI, Lambda, and tests."""

    generated_at: str
    version_id: str
    raw_source: dict[str, Any]
    normalized_source: dict[str, Any]
    annotated_configs: dict[str, dict[str, Any]]
    denorm_config: dict[str, dict[str, Any]]
    rendered_denorm_yaml: str
    query_scope: dict[str, Any]
    artifact: dict[str, Any]
    diff: dict[str, Any]

    @property
    def impact_classification(self) -> str:
        return str(self.diff["classification"])

    @property
    def auto_apply_eligible(self) -> bool:
        return bool(self.diff["auto_apply_eligible"])

    @property
    def requires_apply(self) -> bool:
        return bool(self.diff["requires_apply"])


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _clean_object_label(api_name: str) -> str:
    cleaned = api_name.replace("ascendix__", "").replace("__c", "").replace("__r", "")
    if cleaned.endswith("Id") and cleaned != "Id":
        cleaned = cleaned[:-2]
    cleaned = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", cleaned)
    return cleaned.replace("_", " ").strip() or api_name


def _normalize_field_name(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return (
            value.get("name")
            or value.get("logicalName")
            or value.get("fieldName")
            or value.get("apiName")
            or ""
        )
    return ""


def _selected_objects_sort_key(name: str) -> tuple[int, str]:
    match = _SELECTED_OBJECTS_RE.match(name.strip())
    if not match:
        return (10_000, name)
    index = match.group("index")
    return (int(index) if index is not None else 0, name)


def _build_version_id(generated_at: str, source_hash: str) -> str:
    return f"{generated_at.replace('-', '').replace(':', '')[:15]}-{source_hash[:12]}"


def compiled_artifact_key(
    org_id: str,
    version_id: str,
    *,
    prefix: str = CONFIG_S3_PREFIX,
) -> str:
    return f"{prefix}/{org_id}/compiled/{version_id}.yaml"


def source_snapshot_key(
    org_id: str,
    version_id: str,
    *,
    prefix: str = CONFIG_S3_PREFIX,
) -> str:
    return f"{prefix}/{org_id}/source/{version_id}.json"


def plan_key(
    org_id: str,
    version_id: str,
    *,
    prefix: str = CONFIG_S3_PREFIX,
) -> str:
    return f"{prefix}/{org_id}/plan/{version_id}.json"


def apply_key(
    org_id: str,
    version_id: str,
    *,
    prefix: str = CONFIG_S3_PREFIX,
) -> str:
    return f"{prefix}/{org_id}/apply/{version_id}.json"


def active_version_parameter_name(
    org_id: str,
    *,
    prefix: str = CONFIG_SSM_PREFIX,
) -> str:
    return f"{prefix}/{org_id}/active-version"


def last_source_hash_parameter_name(
    org_id: str,
    *,
    prefix: str = CONFIG_SSM_PREFIX,
) -> str:
    return f"{prefix}/{org_id}/last-source-hash"


def last_compiled_hash_parameter_name(
    org_id: str,
    *,
    prefix: str = CONFIG_SSM_PREFIX,
) -> str:
    return f"{prefix}/{org_id}/last-compiled-hash"


def fetch_ascendix_source(sf: Any) -> dict[str, Any]:
    """Fetch the raw Ascendix Search control-plane source payloads."""
    source = {"search_settings": [], "saved_searches": []}

    try:
        result = _as_dict(
            sf.query(
                "SELECT Id, Name, ascendix_search__Value__c, LastModifiedDate "
                "FROM ascendix_search__SearchSetting__c "
                "WHERE Name LIKE 'Selected Objects%' OR Name LIKE 'Default Layout%' "
                "ORDER BY Name "
                "LIMIT 500"
            )
        )
        source["search_settings"] = _as_list(result.get("records"))
    except Exception as exc:  # pragma: no cover - defensive live-path logging
        if "INVALID_TYPE" in str(exc) or "doesn't exist" in str(exc):
            LOG.warning("Ascendix Search SearchSetting__c unavailable: %s", exc)
        else:
            LOG.warning("Failed to fetch SearchSetting__c rows: %s", exc)

    try:
        result = _as_dict(
            sf.query(
                "SELECT Id, Name, ascendix_search__Template__c, LastModifiedDate "
                "FROM ascendix_search__Search__c "
                "LIMIT 500"
            )
        )
        source["saved_searches"] = _as_list(result.get("records"))
    except Exception as exc:  # pragma: no cover - defensive live-path logging
        if "INVALID_TYPE" in str(exc) or "doesn't exist" in str(exc):
            LOG.warning("Ascendix Search Search__c unavailable: %s", exc)
        else:
            LOG.warning("Failed to fetch Search__c rows: %s", exc)

    return source


def _normalize_selected_objects(search_settings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_rows = []
    for row in search_settings:
        name = str(row.get("Name", "")).strip()
        if _SELECTED_OBJECTS_RE.match(name):
            selected_rows.append(row)

    if not selected_rows:
        return []

    selected_rows.sort(key=lambda row: _selected_objects_sort_key(str(row.get("Name", ""))))
    merged_payload = "".join(str(row.get("ascendix_search__Value__c", "")) for row in selected_rows)
    if not merged_payload.strip():
        return []

    try:
        selected_objects = json.loads(merged_payload)
    except json.JSONDecodeError:
        LOG.warning("Failed to parse concatenated Selected Objects payload")
        return []

    normalized: list[dict[str, Any]] = []
    for entry in _as_list(selected_objects):
        entry = _as_dict(entry)
        api_name = str(entry.get("name") or entry.get("objectName") or "").strip()
        if not api_name:
            continue
        configured_fields = sorted(
            {
                _normalize_field_name(field)
                for field in _as_list(entry.get("fields"))
                if _normalize_field_name(field)
            }
        )
        is_filtered = bool(entry.get("isSearchOrResultFieldsFiltered"))
        normalized.append(
            {
                "api_name": api_name,
                "label": str(entry.get("label") or _clean_object_label(api_name)).strip(),
                "is_searchable": bool(entry.get("isSearchable")),
                "is_map_enabled": bool(entry.get("isMapEnabled")),
                "is_geo_enabled": bool(entry.get("isGeoEnabled")),
                "is_ad_hoc_list_enabled": bool(entry.get("isAdHocListEnabled")),
                "is_field_filtered": is_filtered,
                "configured_fields": configured_fields,
                "field_allowlist": configured_fields if is_filtered else [],
                "raw": entry,
            }
        )
    return normalized


def _build_object_aliases(
    selected_objects: list[dict[str, Any]],
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for obj in selected_objects:
        api_name = str(obj.get("api_name", ""))
        label = str(obj.get("label") or _clean_object_label(api_name)).strip()
        keys = {
            api_name.lower(),
            label.lower(),
            label.replace(" ", "").lower(),
            _clean_object_label(api_name).lower(),
            _clean_object_label(api_name).replace(" ", "").lower(),
        }
        for key in keys:
            if key:
                aliases[key] = api_name
    return aliases


def _normalize_default_layouts(
    search_settings: list[dict[str, Any]],
    selected_objects: list[dict[str, Any]],
) -> dict[str, list[str]]:
    object_aliases = _build_object_aliases(selected_objects)
    layouts: dict[str, set[str]] = {}

    for row in search_settings:
        name = str(row.get("Name", "")).strip()
        match = _DEFAULT_LAYOUT_RE.match(name)
        if not match:
            continue

        raw_suffix = match.group("suffix").strip()
        object_api_name = object_aliases.get(raw_suffix.lower())
        if object_api_name is None and raw_suffix:
            object_api_name = object_aliases.get(raw_suffix.replace(" ", "").lower())

        raw_value = str(row.get("ascendix_search__Value__c", ""))
        if not raw_value.strip():
            continue
        try:
            parsed_columns = json.loads(raw_value)
        except json.JSONDecodeError:
            LOG.warning("Failed to parse default layout row %s", name)
            continue

        object_fields = {
            _normalize_field_name(column)
            for column in _as_list(parsed_columns)
            if _normalize_field_name(column)
        }
        if not object_fields:
            continue

        if object_api_name is None:
            continue

        layouts.setdefault(object_api_name, set()).update(object_fields)

    return {
        object_name: sorted(fields)
        for object_name, fields in sorted(layouts.items())
    }


def _normalize_saved_searches(saved_search_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in saved_search_rows:
        template_json = row.get("ascendix_search__Template__c")
        if not template_json:
            continue
        try:
            template = json.loads(template_json)
        except json.JSONDecodeError:
            LOG.warning("Skipping invalid Ascendix template for %s", row.get("Name", "Unknown"))
            continue

        sections = _as_list(template.get("sectionsList"))
        primary_object = ""
        for section in sections:
            candidate_object = str(_as_dict(section).get("objectName", "")).strip()
            if candidate_object:
                primary_object = candidate_object
                break
        target_objects = sorted(
            {
                str(section.get("objectName")).strip()
                for section in sections
                if str(section.get("objectName", "")).strip()
            }
        )
        filter_fields_by_object: dict[str, list[str]] = {}
        relationship_paths: set[str] = set()
        for section in sections:
            section = _as_dict(section)
            section_object = str(section.get("objectName") or primary_object).strip()
            if not section_object:
                continue
            filter_fields = {
                _normalize_field_name(field)
                for field in _as_list(section.get("fieldsList"))
                if _normalize_field_name(field)
            }
            if filter_fields:
                filter_fields_by_object.setdefault(section_object, [])
                filter_fields_by_object[section_object] = sorted(
                    set(filter_fields_by_object[section_object]) | filter_fields
                )
            relationship = str(section.get("relationship", "")).strip()
            if relationship and primary_object:
                relationship_paths.add(relationship)

        result_columns = sorted(
            {
                _normalize_field_name(column)
                for column in _as_list(template.get("resultColumns"))
                if _normalize_field_name(column)
            }
        )

        normalized.append(
            {
                "id": row.get("Id", ""),
                "Name": row.get("Name", "Unknown"),
                "primary_object": primary_object,
                "target_objects": target_objects,
                "template_json": template_json,
                "template": template,
                "filter_fields_by_object": filter_fields_by_object,
                "relationship_paths": sorted(relationship_paths),
                "result_columns": result_columns,
                "last_modified": row.get("LastModifiedDate", ""),
            }
        )

    return normalized


def build_query_scope(
    normalized_source: dict[str, Any],
    denorm_config: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    objects: dict[str, Any] = {}
    selected_objects = {
        obj["api_name"]: obj for obj in _as_list(normalized_source.get("selected_objects"))
    }
    default_layouts = _as_dict(normalized_source.get("default_layouts"))
    search_fixtures: dict[str, dict[str, set[str]]] = {}

    for saved_search in _as_list(normalized_source.get("saved_searches")):
        primary_object = str(saved_search.get("primary_object", "")).strip()
        if primary_object:
            fixture = search_fixtures.setdefault(
                primary_object,
                {
                    "saved_search_names": set(),
                    "relationship_paths": set(),
                    "saved_search_result_columns": set(),
                },
            )
            fixture["saved_search_names"].add(str(saved_search.get("Name", "Unknown")))
            fixture["relationship_paths"].update(_as_list(saved_search.get("relationship_paths")))
            fixture["saved_search_result_columns"].update(
                _as_list(saved_search.get("result_columns"))
            )

    for object_name in sorted(denorm_config):
        selected = _as_dict(selected_objects.get(object_name))
        fixtures = search_fixtures.get(
            object_name,
            {
                "saved_search_names": set(),
                "relationship_paths": set(),
                "saved_search_result_columns": set(),
            },
        )
        objects[object_name] = {
            "label": str(selected.get("label") or _clean_object_label(object_name)),
            "field_allowlist": sorted(_as_list(selected.get("field_allowlist"))),
            "configured_fields": sorted(_as_list(selected.get("configured_fields"))),
            "result_columns": sorted(set(_as_list(default_layouts.get(object_name)))),
            "saved_search_names": sorted(fixtures["saved_search_names"]),
            "relationship_paths": sorted(fixtures["relationship_paths"]),
            "saved_search_result_columns": sorted(fixtures["saved_search_result_columns"]),
        }

    object_labels = {obj_name: cfg["label"] for obj_name, cfg in objects.items()}
    return {
        "object_api_names": sorted(objects),
        "object_labels": object_labels,
        "object_types": sorted(label.lower() for label in object_labels.values()),
        "objects": objects,
    }


def normalize_ascendix_source(raw_source: dict[str, Any]) -> dict[str, Any]:
    search_settings = _as_list(raw_source.get("search_settings"))
    selected_objects = _normalize_selected_objects(search_settings)
    default_layouts = _normalize_default_layouts(search_settings, selected_objects)
    saved_searches = _normalize_saved_searches(_as_list(raw_source.get("saved_searches")))
    return {
        "selected_objects": selected_objects,
        "default_layouts": default_layouts,
        "saved_searches": saved_searches,
        "source_counts": {
            "search_settings": len(search_settings),
            "saved_searches": len(_as_list(raw_source.get("saved_searches"))),
        },
    }


def _strip_annotations(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "embed_fields": [name for name, _, _ in _as_list(config.get("embed_fields"))],
        "metadata_fields": [name for name, _, _ in _as_list(config.get("metadata_fields"))],
        "parents": {
            ref_field: [field_name for field_name, _ in _as_list(parent_fields)]
            for ref_field, parent_fields in _as_dict(config.get("parents")).items()
        },
        "children": _as_dict(config.get("children")),
    }


def _summarize_denorm_config(config: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for object_name, object_config in sorted(_as_dict(config).items()):
        object_config = _as_dict(object_config)
        summary[object_name] = {
            "embed_fields": sorted(_as_list(object_config.get("embed_fields"))),
            "metadata_fields": sorted(_as_list(object_config.get("metadata_fields"))),
            "parents": {
                ref_field: sorted(_as_list(parent_fields))
                for ref_field, parent_fields in sorted(
                    _as_dict(object_config.get("parents")).items()
                )
            },
        }
    return summary


def diff_runtime_artifacts(
    previous_artifact: dict[str, Any] | None,
    candidate_artifact: dict[str, Any],
) -> dict[str, Any]:
    previous_denorm = _summarize_denorm_config(
        _as_dict(_as_dict(previous_artifact).get("denorm_config"))
    )
    candidate_denorm = _summarize_denorm_config(candidate_artifact.get("denorm_config"))

    previous_objects = set(previous_denorm)
    candidate_objects = set(candidate_denorm)
    added_objects = sorted(candidate_objects - previous_objects)
    removed_objects = sorted(previous_objects - candidate_objects)

    field_changes: dict[str, Any] = {}
    relationship_changes: dict[str, Any] = {}
    for object_name in sorted(previous_objects & candidate_objects):
        prev_obj = previous_denorm[object_name]
        cand_obj = candidate_denorm[object_name]
        prev_fields = set(prev_obj["embed_fields"]) | set(prev_obj["metadata_fields"])
        cand_fields = set(cand_obj["embed_fields"]) | set(cand_obj["metadata_fields"])
        if prev_fields != cand_fields:
            field_changes[object_name] = {
                "added_fields": sorted(cand_fields - prev_fields),
                "removed_fields": sorted(prev_fields - cand_fields),
            }
        if prev_obj["parents"] != cand_obj["parents"]:
            relationship_changes[object_name] = {
                "previous": prev_obj["parents"],
                "candidate": cand_obj["parents"],
            }

    previous_query_scope = _as_dict(_as_dict(previous_artifact).get("query_scope"))
    candidate_query_scope = _as_dict(candidate_artifact.get("query_scope"))
    prompt_scope_changed = previous_query_scope != candidate_query_scope

    if added_objects or removed_objects or previous_artifact is None:
        classification = IMPACT_OBJECT_SCOPE
    elif relationship_changes:
        classification = IMPACT_RELATIONSHIP
    elif field_changes:
        classification = IMPACT_FIELD_SCOPE
    elif prompt_scope_changed:
        classification = IMPACT_PROMPT_ONLY
    else:
        classification = IMPACT_NONE

    return {
        "classification": classification,
        "auto_apply_eligible": classification in AUTO_APPLY_IMPACTS,
        "requires_apply": classification not in AUTO_APPLY_IMPACTS,
        "added_objects": added_objects,
        "removed_objects": removed_objects,
        "field_changes": field_changes,
        "relationship_changes": relationship_changes,
        "prompt_scope_changed": prompt_scope_changed,
    }


def compile_config_artifact(
    *,
    sf: Any | None = None,
    org_id: str,
    raw_source: dict[str, Any] | None = None,
    previous_artifact: dict[str, Any] | None = None,
    target_objects: list[str] | None = None,
    namespace_prefix: str = "ascendix__",
    mock: bool = False,
) -> CompileResult:
    """Compile the active runtime artifact from Ascendix Search source config."""
    from scripts.generate_denorm_config import (
        MockParentFetcher,
        SalesforceHarvester,
        build_config_for_object,
        build_mock_metadata,
        render_yaml,
    )

    generated_at = _now_utc()
    raw_source = raw_source or {"search_settings": [], "saved_searches": []}
    normalized_source = normalize_ascendix_source(raw_source)

    selected_searchable_objects = [
        obj["api_name"]
        for obj in _as_list(normalized_source.get("selected_objects"))
        if obj.get("is_searchable") and obj.get("api_name")
    ]
    object_names = list(target_objects or selected_searchable_objects)

    annotated_configs: dict[str, dict[str, Any]] = {}
    if mock:
        mock_metadata = build_mock_metadata()
        fetcher = MockParentFetcher()
        if not object_names:
            object_names = sorted(mock_metadata)
        for object_name in object_names:
            meta = mock_metadata.get(object_name)
            if meta is None:
                continue
            fixture = _as_dict(
                _as_dict(build_query_scope(normalized_source, {object_name: {}}).get("objects")).get(object_name)
            )
            allowlist = set(_as_list(fixture.get("field_allowlist")))
            if allowlist:
                if meta.name_field:
                    allowlist.add(meta.name_field)
                meta.ascendix_field_allowlist = allowlist
            annotated_configs[object_name] = build_config_for_object(
                meta,
                fetcher,
                set(object_names),
                namespace_prefix,
            )
    else:
        if sf is None:
            raise ValueError("sf is required when mock=False")
        if raw_source == {"search_settings": [], "saved_searches": []}:
            raw_source = fetch_ascendix_source(sf)
            normalized_source = normalize_ascendix_source(raw_source)
            if not object_names:
                object_names = [
                    obj["api_name"]
                    for obj in _as_list(normalized_source.get("selected_objects"))
                    if obj.get("is_searchable") and obj.get("api_name")
                ]
        harvester = SalesforceHarvester(
            sf,
            ascendix_search=True,
            normalized_ascendix_source=normalized_source,
        )
        if not object_names:
            object_names = harvester.discover_objects(require_records=False)
        for object_name in object_names:
            meta = harvester.harvest_object(object_name)
            annotated_configs[object_name] = build_config_for_object(
                meta,
                harvester,
                set(object_names),
                namespace_prefix,
            )

    denorm_config = {
        object_name: _strip_annotations(config)
        for object_name, config in sorted(annotated_configs.items())
    }
    query_scope = build_query_scope(normalized_source, denorm_config)
    source_hash = _hash_payload(normalized_source)
    version_id = _build_version_id(generated_at, source_hash)
    artifact = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "version_id": version_id,
        "org_id": org_id,
        "generated_at": generated_at,
        "source_hash": source_hash,
        "normalized_source": normalized_source,
        "denorm_config": denorm_config,
        "query_scope": query_scope,
    }
    diff = diff_runtime_artifacts(previous_artifact, artifact)
    artifact["impact_classification"] = diff["classification"]
    artifact["auto_apply_eligible"] = diff["auto_apply_eligible"]
    artifact["requires_apply"] = diff["requires_apply"]
    artifact["compiled_hash"] = _hash_payload(artifact)
    rendered_denorm_yaml = render_yaml(annotated_configs, generated_at)

    return CompileResult(
        generated_at=generated_at,
        version_id=version_id,
        raw_source=raw_source,
        normalized_source=normalized_source,
        annotated_configs=annotated_configs,
        denorm_config=denorm_config,
        rendered_denorm_yaml=rendered_denorm_yaml,
        query_scope=query_scope,
        artifact=artifact,
        diff=diff,
    )


class ConfigArtifactStore:
    """Persist compiled artifacts to S3 and active pointers to SSM."""

    def __init__(
        self,
        *,
        s3_client: Any,
        ssm_client: Any,
        bucket: str,
        s3_prefix: str = CONFIG_S3_PREFIX,
        ssm_prefix: str = CONFIG_SSM_PREFIX,
    ):
        self.s3_client = s3_client
        self.ssm_client = ssm_client
        self.bucket = bucket
        self.s3_prefix = s3_prefix
        self.ssm_prefix = ssm_prefix

    def write_candidate(self, compile_result: CompileResult) -> dict[str, str]:
        org_id = compile_result.artifact["org_id"]
        version_id = compile_result.version_id

        source_key_name = source_snapshot_key(org_id, version_id, prefix=self.s3_prefix)
        compiled_key_name = compiled_artifact_key(org_id, version_id, prefix=self.s3_prefix)
        plan_key_name = plan_key(org_id, version_id, prefix=self.s3_prefix)

        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=source_key_name,
            Body=json.dumps(compile_result.raw_source, indent=2, sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=compiled_key_name,
            Body=yaml.safe_dump(
                compile_result.artifact,
                sort_keys=False,
                allow_unicode=False,
            ).encode("utf-8"),
            ContentType="application/x-yaml",
        )
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=plan_key_name,
            Body=json.dumps(
                {
                    "version_id": version_id,
                    "generated_at": compile_result.generated_at,
                    "impact": compile_result.diff,
                    "auto_apply_eligible": compile_result.auto_apply_eligible,
                    "requires_apply": compile_result.requires_apply,
                    "compiled_hash": compile_result.artifact["compiled_hash"],
                    "source_hash": compile_result.artifact["source_hash"],
                },
                indent=2,
                sort_keys=True,
            ).encode("utf-8"),
            ContentType="application/json",
        )

        self._put_parameter(
            last_source_hash_parameter_name(org_id, prefix=self.ssm_prefix),
            compile_result.artifact["source_hash"],
        )
        self._put_parameter(
            last_compiled_hash_parameter_name(org_id, prefix=self.ssm_prefix),
            compile_result.artifact["compiled_hash"],
        )

        return {
            "source": source_key_name,
            "compiled": compiled_key_name,
            "plan": plan_key_name,
        }

    def set_active_version(
        self,
        org_id: str,
        version_id: str,
        *,
        applied_by: str,
        reason: str,
    ) -> str:
        self._put_parameter(
            active_version_parameter_name(org_id, prefix=self.ssm_prefix),
            version_id,
        )
        apply_key_name = apply_key(org_id, version_id, prefix=self.s3_prefix)
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=apply_key_name,
            Body=json.dumps(
                {
                    "version_id": version_id,
                    "applied_at": _now_utc(),
                    "applied_by": applied_by,
                    "reason": reason,
                },
                indent=2,
                sort_keys=True,
            ).encode("utf-8"),
            ContentType="application/json",
        )
        return apply_key_name

    def resolve_active_version(self, org_id: str) -> str | None:
        try:
            response = self.ssm_client.get_parameter(
                Name=active_version_parameter_name(org_id, prefix=self.ssm_prefix)
            )
        except Exception:
            return None
        return str(_as_dict(response.get("Parameter")).get("Value") or "") or None

    def load_compiled_artifact(self, org_id: str, version_id: str) -> dict[str, Any]:
        response = self.s3_client.get_object(
            Bucket=self.bucket,
            Key=compiled_artifact_key(org_id, version_id, prefix=self.s3_prefix),
        )
        body = response["Body"].read()
        return _as_dict(yaml.safe_load(body))

    def load_active_artifact(self, org_id: str) -> dict[str, Any] | None:
        version_id = self.resolve_active_version(org_id)
        if not version_id:
            return None
        return self.load_compiled_artifact(org_id, version_id)

    def _put_parameter(self, name: str, value: str) -> None:
        self.ssm_client.put_parameter(
            Name=name,
            Value=value,
            Type="String",
            Overwrite=True,
        )

    def write_approval_state(
        self,
        org_id: str,
        version_id: str,
        *,
        state: str,
        operator: str,
        reason: str,
        previous_version: str = "",
    ) -> str:
        """Write or update the approval record for a candidate version."""
        approval_key = f"{self.s3_prefix}/{org_id}/approval/{version_id}.json"
        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=approval_key,
            Body=json.dumps(
                {
                    "version_id": version_id,
                    "state": state,
                    "operator": operator,
                    "reason": reason,
                    "previous_version": previous_version,
                    "updated_at": _now_utc(),
                },
                indent=2,
                sort_keys=True,
            ).encode("utf-8"),
            ContentType="application/json",
        )
        return approval_key

    def load_approval_state(self, org_id: str, version_id: str) -> dict[str, Any] | None:
        """Load approval state for a candidate version."""
        approval_key = f"{self.s3_prefix}/{org_id}/approval/{version_id}.json"
        try:
            response = self.s3_client.get_object(Bucket=self.bucket, Key=approval_key)
            return _as_dict(json.loads(response["Body"].read()))
        except Exception:
            return None


def _build_apply_plan(diff: dict[str, Any]) -> dict[str, Any]:
    """Build an apply plan describing required work before activation.

    Returns a plan dict with per-object actions keyed by impact type.
    """
    classification = diff.get("classification", IMPACT_NONE)
    actions: list[dict[str, Any]] = []

    if classification == IMPACT_OBJECT_SCOPE:
        for obj in diff.get("added_objects", []):
            actions.append({
                "object": obj,
                "action": "seed_new_object",
                "description": (
                    f"Initial data seed required for newly added object {obj}. "
                    "Run poll_sync with full_sync=true for this object, then "
                    "initialize the poll watermark."
                ),
                "requires_reindex": True,
            })
        for obj in diff.get("removed_objects", []):
            actions.append({
                "object": obj,
                "action": "retire_object",
                "description": (
                    f"Object {obj} removed from scope. It will be excluded "
                    "from query_scope immediately on activation. Index data "
                    "can be retired asynchronously."
                ),
                "requires_reindex": False,
            })

    if classification in (IMPACT_FIELD_SCOPE, IMPACT_OBJECT_SCOPE):
        for obj, changes in diff.get("field_changes", {}).items():
            if changes.get("added_fields"):
                actions.append({
                    "object": obj,
                    "action": "reindex_field_add",
                    "description": (
                        f"Fields added to {obj}: {changes['added_fields']}. "
                        "Targeted reindex required to embed/index new field data."
                    ),
                    "added_fields": changes["added_fields"],
                    "requires_reindex": True,
                })
            if changes.get("removed_fields"):
                actions.append({
                    "object": obj,
                    "action": "reindex_field_remove",
                    "description": (
                        f"Fields removed from {obj}: {changes['removed_fields']}. "
                        "Targeted reindex to remove stale field data from embeddings."
                    ),
                    "removed_fields": changes["removed_fields"],
                    "requires_reindex": True,
                })

    if classification in (IMPACT_RELATIONSHIP, IMPACT_OBJECT_SCOPE):
        for obj, changes in diff.get("relationship_changes", {}).items():
            actions.append({
                "object": obj,
                "action": "reindex_relationship",
                "description": (
                    f"Relationship config changed for {obj}. "
                    "Targeted reindex required to update parent-field embeddings."
                ),
                "previous_parents": changes.get("previous", {}),
                "candidate_parents": changes.get("candidate", {}),
                "requires_reindex": True,
            })

    requires_reindex = any(a.get("requires_reindex") for a in actions)
    return {
        "classification": classification,
        "requires_reindex": requires_reindex,
        "action_count": len(actions),
        "actions": actions,
    }


@dataclass
class ApplyResult:
    """Result of executing a targeted apply workflow."""

    version_id: str
    activated: bool
    apply_plan: dict[str, Any]
    reindex_results: list[dict[str, Any]]
    evidence: dict[str, Any]
    approval_key: str = ""
    apply_record_key: str = ""


def execute_targeted_apply(
    *,
    store: ConfigArtifactStore,
    org_id: str,
    version_id: str,
    diff: dict[str, Any],
    applied_by: str = "operator",
    reason: str = "manual_apply",
    reindex_callback: Any | None = None,
) -> ApplyResult:
    """Execute targeted seed/reindex work and promote candidate to active.

    For each action in the apply plan:
    - object add: calls reindex_callback with full_sync=True for the object
    - field/relationship change: calls reindex_callback for affected objects
    - object remove: no reindex needed, just scope removal on activation

    If no reindex_callback is provided, the apply plan is recorded but
    reindex work is marked as deferred (for operator to execute manually).
    """
    plan = _build_apply_plan(diff)
    reindex_results: list[dict[str, Any]] = []

    for action in plan["actions"]:
        if not action.get("requires_reindex"):
            reindex_results.append({
                "object": action["object"],
                "action": action["action"],
                "status": "not_required",
            })
            continue

        if reindex_callback is not None:
            try:
                callback_result = reindex_callback(
                    object_name=action["object"],
                    action_type=action["action"],
                    full_sync=action["action"] == "seed_new_object",
                )
                reindex_results.append({
                    "object": action["object"],
                    "action": action["action"],
                    "status": "completed",
                    "result": callback_result,
                })
            except Exception as exc:
                LOG.error(
                    "Reindex failed for %s (%s): %s",
                    action["object"],
                    action["action"],
                    exc,
                )
                reindex_results.append({
                    "object": action["object"],
                    "action": action["action"],
                    "status": "failed",
                    "error": str(exc),
                })
        else:
            reindex_results.append({
                "object": action["object"],
                "action": action["action"],
                "status": "deferred",
                "description": (
                    "No reindex_callback provided. Operator must run "
                    "targeted reindex manually before activation."
                ),
            })

    # Check if all required reindex work succeeded or was deferred
    all_reindex_ok = all(
        r["status"] in ("completed", "not_required")
        for r in reindex_results
    )
    any_deferred = any(r["status"] == "deferred" for r in reindex_results)

    activated = False
    apply_record_key = ""
    approval_key = ""

    if all_reindex_ok and not any_deferred:
        # All reindex work completed — safe to activate
        apply_record_key = store.set_active_version(
            org_id,
            version_id,
            applied_by=applied_by,
            reason=reason,
        )
        approval_key = store.write_approval_state(
            org_id,
            version_id,
            state=APPROVAL_APPLIED,
            operator=applied_by,
            reason=reason,
        )
        activated = True
        LOG.info("Activated version %s for %s after targeted apply", version_id, org_id)
    elif any_deferred:
        approval_key = store.write_approval_state(
            org_id,
            version_id,
            state=APPROVAL_APPROVED,
            operator=applied_by,
            reason="Approved but reindex deferred — manual reindex required before activation",
        )
        LOG.info("Version %s approved but activation deferred pending manual reindex", version_id)
    else:
        approval_key = store.write_approval_state(
            org_id,
            version_id,
            state=APPROVAL_REJECTED,
            operator=applied_by,
            reason="Reindex failed — activation blocked",
        )
        LOG.warning("Version %s apply failed — reindex errors occurred", version_id)

    evidence = {
        "version_id": version_id,
        "org_id": org_id,
        "apply_plan": plan,
        "reindex_results": reindex_results,
        "activated": activated,
        "applied_by": applied_by,
        "applied_at": _now_utc(),
    }

    return ApplyResult(
        version_id=version_id,
        activated=activated,
        apply_plan=plan,
        reindex_results=reindex_results,
        evidence=evidence,
        approval_key=approval_key,
        apply_record_key=apply_record_key,
    )


def rollback_to_version(
    *,
    store: ConfigArtifactStore,
    org_id: str,
    target_version_id: str,
    rolled_back_by: str = "operator",
    reason: str = "manual_rollback",
) -> dict[str, Any]:
    """Roll back active config to a specified previous version.

    Verifies the target version exists before activating it.
    """
    artifact = store.load_compiled_artifact(org_id, target_version_id)
    if not artifact:
        raise ValueError(f"Target rollback version {target_version_id} not found")

    current_version = store.resolve_active_version(org_id) or ""
    apply_record_key = store.set_active_version(
        org_id,
        target_version_id,
        applied_by=rolled_back_by,
        reason=reason,
    )
    approval_key = store.write_approval_state(
        org_id,
        target_version_id,
        state=APPROVAL_ROLLED_BACK,
        operator=rolled_back_by,
        reason=reason,
        previous_version=current_version,
    )
    LOG.info(
        "Rolled back %s from %s to %s",
        org_id,
        current_version,
        target_version_id,
    )
    return {
        "org_id": org_id,
        "previous_version": current_version,
        "rolled_back_to": target_version_id,
        "apply_record_key": apply_record_key,
        "approval_key": approval_key,
        "rolled_back_by": rolled_back_by,
        "rolled_back_at": _now_utc(),
    }


def execute_config_refresh(
    *,
    sf: Any,
    org_id: str,
    store: ConfigArtifactStore | None,
    apply: bool = False,
    applied_by: str = "config_refresh",
    raw_source: dict[str, Any] | None = None,
    target_objects: list[str] | None = None,
    namespace_prefix: str = "ascendix__",
    reindex_callback: Any | None = None,
) -> dict[str, Any]:
    """Run the full config refresh flow and optionally activate the result.

    For safe changes (none, prompt_only), auto-applies immediately.
    For non-safe changes with apply=True, runs the targeted apply workflow
    which performs required seed/reindex before activation.
    """
    previous_artifact = store.load_active_artifact(org_id) if store is not None else None
    source_snapshot = raw_source or fetch_ascendix_source(sf)
    compile_result = compile_config_artifact(
        sf=sf,
        org_id=org_id,
        raw_source=source_snapshot,
        previous_artifact=previous_artifact,
        target_objects=target_objects,
        namespace_prefix=namespace_prefix,
    )

    stored_keys: dict[str, str] = {}
    if store is not None:
        stored_keys = store.write_candidate(compile_result)

    activated = False
    apply_record_key = ""
    activation_blocked_reason = ""
    apply_result: ApplyResult | None = None

    if store is not None and compile_result.auto_apply_eligible:
        reason = "auto_apply"
        apply_record_key = store.set_active_version(
            org_id,
            compile_result.version_id,
            applied_by=applied_by,
            reason=reason,
        )
        activated = True
    elif apply and store is not None and compile_result.requires_apply:
        # Targeted apply workflow for non-safe changes
        apply_result = execute_targeted_apply(
            store=store,
            org_id=org_id,
            version_id=compile_result.version_id,
            diff=compile_result.diff,
            applied_by=applied_by,
            reason="targeted_apply",
            reindex_callback=reindex_callback,
        )
        activated = apply_result.activated
        apply_record_key = apply_result.apply_record_key
        if not activated:
            activation_blocked_reason = (
                "Targeted apply did not activate: "
                + ("reindex deferred" if any(
                    r["status"] == "deferred" for r in apply_result.reindex_results
                ) else "reindex failed")
            )
    elif store is not None and compile_result.requires_apply and not apply:
        # Write pending approval state
        store.write_approval_state(
            org_id,
            compile_result.version_id,
            state=APPROVAL_PENDING,
            operator=applied_by,
            reason=f"Non-safe change ({compile_result.impact_classification}) requires approval",
        )
        activation_blocked_reason = (
            f"Change classified as {compile_result.impact_classification} — "
            "requires operator approval. Run with --apply to execute targeted "
            "apply workflow, or use approve/rollback commands."
        )
        LOG.info(
            "Version %s for %s requires approval (%s)",
            compile_result.version_id,
            org_id,
            compile_result.impact_classification,
        )

    return {
        "compile_result": compile_result,
        "stored_keys": stored_keys,
        "activated": activated,
        "apply_record_key": apply_record_key,
        "activation_blocked_reason": activation_blocked_reason,
        "apply_result": apply_result,
    }
