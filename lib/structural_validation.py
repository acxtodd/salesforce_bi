"""Ascendix Search structural validation harness.

Extracts validation fixtures from normalized Ascendix Search config and
asserts structural parity for object scope, field allowlists, default
columns, and relationship paths — without requiring identical ranking,
answer wording, or query-builder behavior.

This harness is for config-refresh evidence and structural validation,
not for constraining the NL search product to Ascendix Search behavior.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

LOG = logging.getLogger(__name__)


@dataclass
class StructuralFixture:
    """Validation fixture extracted from normalized Ascendix Search config."""

    object_api_names: list[str] = field(default_factory=list)
    field_allowlists: dict[str, list[str]] = field(default_factory=dict)
    default_columns: dict[str, list[str]] = field(default_factory=dict)
    relationship_paths: dict[str, list[str]] = field(default_factory=dict)
    saved_search_names: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ParityResult:
    """Result of a single parity assertion."""

    check: str
    passed: bool
    expected: Any = None
    actual: Any = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "check": self.check,
            "passed": self.passed,
        }
        if self.detail:
            d["detail"] = self.detail
        if not self.passed:
            d["expected"] = self.expected
            d["actual"] = self.actual
        return d


@dataclass
class ValidationReport:
    """Aggregate report from all structural parity checks."""

    results: list[ParityResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"{status}: {self.passed_count}/{self.total} checks passed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "summary": self.summary(),
            "total": self.total,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, **kwargs)


def extract_fixtures(normalized_source: dict[str, Any]) -> StructuralFixture:
    """Extract structural validation fixtures from normalized Ascendix config.

    Pulls object scope, field allowlists, default columns, and relationship
    paths from the normalized source produced by
    ``lib.config_refresh.normalize_ascendix_source``.
    """
    selected_objects = normalized_source.get("selected_objects", [])
    default_layouts = normalized_source.get("default_layouts", {})
    saved_searches = normalized_source.get("saved_searches", [])

    fixture = StructuralFixture()

    # Object scope — searchable objects
    fixture.object_api_names = sorted(
        obj["api_name"]
        for obj in selected_objects
        if obj.get("is_searchable") and obj.get("api_name")
    )

    # Field allowlists — only for filtered objects
    for obj in selected_objects:
        api_name = obj.get("api_name", "")
        if obj.get("is_field_filtered") and api_name:
            fixture.field_allowlists[api_name] = sorted(obj.get("field_allowlist", []))

    # Default columns from Default Layout rows
    for object_name, columns in sorted(default_layouts.items()):
        fixture.default_columns[object_name] = sorted(columns)

    # Relationship paths and saved search names from saved searches
    for search in saved_searches:
        primary = search.get("primary_object", "")
        if not primary:
            continue
        paths = search.get("relationship_paths", [])
        if paths:
            existing = set(fixture.relationship_paths.get(primary, []))
            existing.update(paths)
            fixture.relationship_paths[primary] = sorted(existing)
        name = search.get("Name", "")
        if name:
            fixture.saved_search_names.setdefault(primary, [])
            if name not in fixture.saved_search_names[primary]:
                fixture.saved_search_names[primary].append(name)
                fixture.saved_search_names[primary].sort()

    return fixture


def assert_object_scope_parity(
    fixture: StructuralFixture,
    runtime_artifact: dict[str, Any],
) -> ParityResult:
    """Check that runtime artifact covers all searchable objects from Ascendix config."""
    denorm_config = runtime_artifact.get("denorm_config", {})
    runtime_objects = set(denorm_config.keys())
    expected_objects = set(fixture.object_api_names)
    missing = sorted(expected_objects - runtime_objects)
    if missing:
        return ParityResult(
            check="object_scope_parity",
            passed=False,
            expected=sorted(expected_objects),
            actual=sorted(runtime_objects),
            detail=f"Missing objects: {missing}",
        )
    return ParityResult(
        check="object_scope_parity",
        passed=True,
        detail=f"All {len(expected_objects)} searchable objects present in runtime config",
    )


def assert_field_allowlist_parity(
    fixture: StructuralFixture,
    runtime_artifact: dict[str, Any],
) -> list[ParityResult]:
    """Check that runtime config includes all allowlisted fields for filtered objects."""
    results: list[ParityResult] = []
    denorm_config = runtime_artifact.get("denorm_config", {})

    for object_name, expected_fields in sorted(fixture.field_allowlists.items()):
        obj_config = denorm_config.get(object_name, {})
        runtime_fields = set(obj_config.get("embed_fields", []))
        runtime_fields |= set(obj_config.get("metadata_fields", []))
        # Also include parent reference field names
        for parent_ref, parent_fields in obj_config.get("parents", {}).items():
            runtime_fields.add(parent_ref)

        expected_set = set(expected_fields)
        missing = sorted(expected_set - runtime_fields)

        if missing:
            results.append(ParityResult(
                check=f"field_allowlist_parity:{object_name}",
                passed=False,
                expected=sorted(expected_set),
                actual=sorted(runtime_fields),
                detail=f"Missing fields: {missing}",
            ))
        else:
            results.append(ParityResult(
                check=f"field_allowlist_parity:{object_name}",
                passed=True,
                detail=f"All {len(expected_set)} allowlisted fields covered",
            ))

    return results


def assert_default_column_parity(
    fixture: StructuralFixture,
    runtime_artifact: dict[str, Any],
) -> list[ParityResult]:
    """Check that query_scope result_columns cover the default layout columns."""
    results: list[ParityResult] = []
    query_scope = runtime_artifact.get("query_scope", {})
    objects_scope = query_scope.get("objects", {})

    for object_name, expected_columns in sorted(fixture.default_columns.items()):
        obj_scope = objects_scope.get(object_name, {})
        runtime_columns = set(obj_scope.get("result_columns", []))
        expected_set = set(expected_columns)
        missing = sorted(expected_set - runtime_columns)

        if missing:
            results.append(ParityResult(
                check=f"default_column_parity:{object_name}",
                passed=False,
                expected=sorted(expected_set),
                actual=sorted(runtime_columns),
                detail=f"Missing columns: {missing}",
            ))
        else:
            results.append(ParityResult(
                check=f"default_column_parity:{object_name}",
                passed=True,
                detail=f"All {len(expected_set)} default columns covered",
            ))

    return results


def assert_relationship_path_parity(
    fixture: StructuralFixture,
    runtime_artifact: dict[str, Any],
) -> list[ParityResult]:
    """Check that query_scope relationship_paths cover saved search relationships."""
    results: list[ParityResult] = []
    query_scope = runtime_artifact.get("query_scope", {})
    objects_scope = query_scope.get("objects", {})

    for object_name, expected_paths in sorted(fixture.relationship_paths.items()):
        obj_scope = objects_scope.get(object_name, {})
        runtime_paths = set(obj_scope.get("relationship_paths", []))
        expected_set = set(expected_paths)
        missing = sorted(expected_set - runtime_paths)

        if missing:
            results.append(ParityResult(
                check=f"relationship_path_parity:{object_name}",
                passed=False,
                expected=sorted(expected_set),
                actual=sorted(runtime_paths),
                detail=f"Missing relationship paths: {missing}",
            ))
        else:
            results.append(ParityResult(
                check=f"relationship_path_parity:{object_name}",
                passed=True,
                detail=f"All {len(expected_set)} relationship paths covered",
            ))

    return results


def validate_structural_parity(
    normalized_source: dict[str, Any],
    runtime_artifact: dict[str, Any],
) -> ValidationReport:
    """Run the full structural validation harness.

    Extracts fixtures from normalized Ascendix config and asserts parity
    against the compiled runtime artifact for object scope, field
    allowlists, default columns, and relationship paths.
    """
    fixture = extract_fixtures(normalized_source)
    report = ValidationReport()

    report.results.append(
        assert_object_scope_parity(fixture, runtime_artifact)
    )
    report.results.extend(
        assert_field_allowlist_parity(fixture, runtime_artifact)
    )
    report.results.extend(
        assert_default_column_parity(fixture, runtime_artifact)
    )
    report.results.extend(
        assert_relationship_path_parity(fixture, runtime_artifact)
    )

    LOG.info("Structural validation: %s", report.summary())
    return report
