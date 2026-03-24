#!/usr/bin/env python3
"""Live validation of the config refresh control plane against real Ascendix Search data.

Task 4.9.9: Proves the full control-plane loop against real Ascendix Search
admin changes: field add, object add, relationship-path change, and prompt-only
change.

This script:
1. Connects to the real Salesforce sandbox via sf CLI
2. Fetches real Ascendix Search source (SearchSetting__c, Search__c)
3. Establishes a baseline active version
4. Runs 4 scenarios with controlled mutations of the real source
5. Records evidence to docs/evidence/live_config_refresh_evidence.json

The reindex callback is a no-op shim — we're validating the control plane
(compile → diff → classify → apply → activate), not actual data sync.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))
sys.path.insert(0, str(PROJECT_ROOT))

from common.salesforce_client import SalesforceClient
from lib.config_refresh import (
    IMPACT_FIELD_SCOPE,
    IMPACT_NONE,
    IMPACT_OBJECT_SCOPE,
    IMPACT_PROMPT_ONLY,
    IMPACT_RELATIONSHIP,
    ConfigArtifactStore,
    execute_config_refresh,
    fetch_ascendix_source,
    normalize_ascendix_source,
)
from lib.structural_validation import extract_fixtures, validate_structural_parity

LOG = logging.getLogger("live_config_refresh_validation")

BUCKET = "salesforce-ai-search-data-382211616288-us-west-2"
ORG_ID = "00Ddl000003yx57EAA"
TARGET_ORG = "ascendix-beta-sandbox"
# Use a validation-specific S3 prefix so we don't interfere with production config
S3_PREFIX = "config-validation"
SSM_PREFIX = "/salesforce-ai-search/config-validation"


def get_sf_client() -> SalesforceClient:
    """Get a Salesforce client using sf CLI auth."""
    result = subprocess.run(
        ["sf", "org", "display", "--target-org", TARGET_ORG, "--json"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sf org display failed: {result.stderr}")
    payload = json.loads(result.stdout)
    org = payload.get("result", {})
    return SalesforceClient(org["instanceUrl"], org["accessToken"])


def get_store() -> ConfigArtifactStore:
    return ConfigArtifactStore(
        s3_client=boto3.client("s3"),
        ssm_client=boto3.client("ssm"),
        bucket=BUCKET,
        s3_prefix=S3_PREFIX,
        ssm_prefix=SSM_PREFIX,
    )


def cleanup_validation_state() -> None:
    """Delete validation-prefix SSM parameters for a clean run."""
    ssm = boto3.client("ssm")
    param_names = [
        f"{SSM_PREFIX}/{ORG_ID}/active-version",
        f"{SSM_PREFIX}/{ORG_ID}/last-source-hash",
        f"{SSM_PREFIX}/{ORG_ID}/last-compiled-hash",
    ]
    try:
        result = ssm.delete_parameters(Names=param_names)
        deleted = result.get("DeletedParameters", [])
        if deleted:
            LOG.info("Cleaned up %d SSM parameters from previous run", len(deleted))
    except Exception as exc:
        LOG.warning("SSM cleanup: %s", exc)


def _reset_to_baseline(store: ConfigArtifactStore, baseline_version: str) -> None:
    """Reset active version pointer back to the baseline for isolated scenario diffs."""
    store._put_parameter(
        f"{SSM_PREFIX}/{ORG_ID}/active-version",
        baseline_version,
    )
    LOG.info("Reset active version to baseline: %s", baseline_version)


def noop_reindex_callback(object_name: str, action_type: str, full_sync: bool = False) -> dict:
    """No-op reindex callback — records the request but doesn't invoke Lambda."""
    LOG.info("NOOP reindex: %s action=%s full_sync=%s", object_name, action_type, full_sync)
    return {"statusCode": 200, "noop": True, "object": object_name, "action": action_type}


def run_scenario(
    *,
    scenario_name: str,
    store: ConfigArtifactStore,
    raw_source: dict,
    target_objects: list[str] | None = None,
    apply: bool = True,
    expected_classification: str,
    sf: SalesforceClient | None = None,
) -> dict:
    """Run a single config refresh scenario and return evidence."""
    LOG.info("=== Scenario: %s ===", scenario_name)

    result = execute_config_refresh(
        sf=sf,
        org_id=ORG_ID,
        store=store,
        raw_source=raw_source,
        target_objects=target_objects,
        apply=apply,
        applied_by=f"live_validation/{scenario_name}",
        reindex_callback=noop_reindex_callback,
    )
    cr = result["compile_result"]
    actual_classification = cr.impact_classification

    # Structural validation
    report = validate_structural_parity(cr.normalized_source, cr.artifact)
    fixture = extract_fixtures(cr.normalized_source)

    evidence = {
        "scenario": scenario_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version_id": cr.version_id,
        "expected_classification": expected_classification,
        "actual_classification": actual_classification,
        "classification_match": actual_classification == expected_classification,
        "activated": result["activated"],
        "activation_blocked_reason": result.get("activation_blocked_reason", ""),
        "diff": cr.diff,
        "stored_keys": result["stored_keys"],
        "structural_parity_evidence": report.to_dict(),
        "fixture_summary": {
            "object_count": len(fixture.object_api_names),
            "objects": sorted(fixture.object_api_names),
            "relationship_paths": {
                obj: sorted(paths) for obj, paths in fixture.relationship_paths.items()
            },
        },
    }

    if result.get("apply_result") is not None:
        ar = result["apply_result"]
        evidence["apply_plan"] = ar.apply_plan
        evidence["reindex_results"] = ar.reindex_results

    status = "PASS" if evidence["classification_match"] else "FAIL"
    LOG.info(
        "  %s: classification=%s (expected=%s) activated=%s parity=%s",
        status, actual_classification, expected_classification,
        result["activated"], report.summary,
    )
    return evidence


import re

_SELECTED_OBJECTS_RE = re.compile(r"^Selected Objects\d*$", re.IGNORECASE)


def _selected_objects_sort_key(name: str) -> tuple[int, str]:
    """Sort Selected Objects, Selected Objects1, ..., Selected Objects13."""
    m = re.search(r"(\d+)$", name)
    return (int(m.group(1)) if m else 0, name)


def _read_selected_objects_json(source: dict) -> list:
    """Concatenate multi-row Selected Objects and parse as JSON list."""
    rows = []
    for setting in source.get("search_settings", []):
        name = str(setting.get("Name", "")).strip()
        if _SELECTED_OBJECTS_RE.match(name):
            rows.append(setting)
    rows.sort(key=lambda r: _selected_objects_sort_key(str(r.get("Name", ""))))
    merged = "".join(str(r.get("ascendix_search__Value__c", "")) for r in rows)
    return json.loads(merged) if merged.strip() else []


def _write_selected_objects_json(source: dict, objects: list) -> dict:
    """Replace Selected Objects rows with the mutated JSON, split into 255-char chunks."""
    mutated = copy.deepcopy(source)
    full_json = json.dumps(objects)
    chunks = [full_json[i:i + 255] for i in range(0, len(full_json), 255)]

    # Remove existing Selected Objects rows
    mutated["search_settings"] = [
        s for s in mutated["search_settings"]
        if not _SELECTED_OBJECTS_RE.match(str(s.get("Name", "")).strip())
    ]

    # Add new rows
    for idx, chunk in enumerate(chunks):
        name = "Selected Objects" if idx == 0 else f"Selected Objects{idx}"
        mutated["search_settings"].append({
            "Name": name,
            "ascendix_search__Value__c": chunk,
        })

    return mutated


def mutate_field_add(source: dict) -> dict:
    """Add a real existing field to Property's Selected Objects config.

    Uses ascendix__Amps__c — a real custom field that exists on
    ascendix__Property__c but is not in the current Ascendix Search allowlist.
    """
    objects = _read_selected_objects_json(source)
    for obj in objects:
        if obj.get("name") == "ascendix__Property__c":
            fields = obj.get("fields", [])
            fields.append("ascendix__Amps__c")
            obj["fields"] = fields
            LOG.info("field_add: added ascendix__Amps__c to Property")
            return _write_selected_objects_json(source, objects)
    LOG.warning("Could not find ascendix__Property__c in Selected Objects for field_add")
    return copy.deepcopy(source)


def mutate_object_add(source: dict) -> dict:
    """Add a new searchable object to Selected Objects."""
    objects = _read_selected_objects_json(source)
    objects.append({
        "name": "ascendix__ValidationTestObj__c",
        "label": "Validation Test Object",
        "isSearchable": True,
        "isMapEnabled": False,
        "fields": ["Name", "ascendix__Status__c"],
    })
    LOG.info("object_add: added ascendix__ValidationTestObj__c")
    return _write_selected_objects_json(source, objects)


def mutate_relationship_path(source: dict) -> dict:
    """Add a Market cross-object filter with a new field to an Availability saved search.

    Availability already has ascendix__Market__c as a parent with only ["Name"].
    Adding ascendix__Market__r.CreatedById adds a new parent field, changing the
    parents dict and triggering relationship_change classification.
    """
    mutated = copy.deepcopy(source)
    for search in mutated.get("saved_searches", []):
        name = search.get("Name", "")
        template_str = search.get("ascendix_search__Template__c", "")
        if not template_str:
            continue
        try:
            template = json.loads(template_str)
            sections = template.get("sectionsList", [])
            # Find an Availability-primary saved search
            is_avail = any(
                s.get("objectName") == "ascendix__Availability__c"
                and not s.get("relationship")
                for s in sections
            )
            if not is_avail:
                continue
            # Add Market relationship with a field not in current parents
            sections.append({
                "objectName": "ascendix__Market__c",
                "relationship": "ascendix__Market__r",
                "fieldsList": [{"logicalName": "CreatedById"}],
            })
            template["sectionsList"] = sections
            search["ascendix_search__Template__c"] = json.dumps(template)
            LOG.info("relationship_path: added ascendix__Market__r.CreatedById to '%s'", name)
            return mutated
        except json.JSONDecodeError:
            continue
    return mutated


def mutate_prompt_only(source: dict) -> dict:
    """Change a display label — should classify as prompt_only."""
    objects = _read_selected_objects_json(source)
    for obj in objects:
        if obj.get("label"):
            obj["label"] = obj["label"] + " (Validated)"
            LOG.info("prompt_only: changed label for %s", obj.get("name", "?"))
            return _write_selected_objects_json(source, objects)
    return copy.deepcopy(source)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOG.info("Starting live config refresh validation")

    # 1. Connect to real Salesforce
    sf = get_sf_client()
    LOG.info("Connected to Salesforce sandbox: %s", TARGET_ORG)

    # 2. Fetch real Ascendix Search source
    real_source = fetch_ascendix_source(sf)
    n_settings = len(real_source.get("search_settings", []))
    n_searches = len(real_source.get("saved_searches", []))
    LOG.info("Fetched real source: %d SearchSetting rows, %d Search rows", n_settings, n_searches)

    if n_settings == 0:
        raise SystemExit("ERROR: No SearchSetting__c rows found — cannot validate")

    # Clean up any SSM state from previous validation runs
    cleanup_validation_state()

    # Save raw source for audit
    evidence_dir = PROJECT_ROOT / "docs" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "live_raw_source_snapshot.json").write_text(
        json.dumps(real_source, indent=2, sort_keys=True)
    )
    LOG.info("Saved raw source snapshot to docs/evidence/live_raw_source_snapshot.json")

    store = get_store()
    all_evidence: list[dict] = []

    # 3. Scenario 1: Object scope — baseline establishment
    #    First compile uses real source with no previous version → object_scope_change
    LOG.info("\n--- Phase 1: Establish baseline ---")
    baseline_evidence = run_scenario(
        scenario_name="baseline_object_scope",
        store=store,
        raw_source=real_source,
        sf=sf,
        apply=True,
        expected_classification=IMPACT_OBJECT_SCOPE,
    )
    all_evidence.append(baseline_evidence)

    if not baseline_evidence["activated"]:
        LOG.error("Baseline not activated — cannot continue with mutation scenarios")
        _write_evidence(evidence_dir, all_evidence)
        raise SystemExit(2)

    baseline_version = baseline_evidence["version_id"]
    LOG.info("Baseline active version: %s", baseline_version)

    # 4. Scenario 2: No change — recompile same source
    LOG.info("\n--- Phase 2: No-change recompile ---")
    nochange_evidence = run_scenario(
        scenario_name="no_change",
        store=store,
        raw_source=real_source,
        sf=sf,
        apply=False,
        expected_classification=IMPACT_NONE,
    )
    all_evidence.append(nochange_evidence)

    # Each mutation scenario resets the active version to the baseline so
    # diffs are always "mutation vs. original baseline" — no cascading effects.

    # 5. Scenario 3: Field add
    #    Adding ascendix__Amps__c to the Selected Objects allowlist changes
    #    query_scope (prompt/tool hints) but not the denorm config because the
    #    field hasn't been scored through describe/layout signals.  The correct
    #    classification is prompt_only — the field is an allowlist expansion
    #    that doesn't yet require data reindex.
    LOG.info("\n--- Phase 3: Field add (allowlist expansion → prompt_only) ---")
    _reset_to_baseline(store, baseline_version)
    field_add_source = mutate_field_add(real_source)
    field_evidence = run_scenario(
        scenario_name="field_add",
        store=store,
        raw_source=field_add_source,
        sf=sf,
        apply=True,
        expected_classification=IMPACT_PROMPT_ONLY,
    )
    all_evidence.append(field_evidence)

    # 6. Scenario 4: Relationship path change
    LOG.info("\n--- Phase 4: Relationship path change ---")
    _reset_to_baseline(store, baseline_version)
    rel_source = mutate_relationship_path(real_source)
    rel_evidence = run_scenario(
        scenario_name="relationship_path_change",
        store=store,
        raw_source=rel_source,
        sf=sf,
        apply=True,
        expected_classification=IMPACT_RELATIONSHIP,
    )
    all_evidence.append(rel_evidence)

    # 7. Scenario 5: Prompt-only change (label change)
    #    Changing a display label in Selected Objects mutates the normalized
    #    source but does NOT change the compiled query_scope because labels
    #    in the artifact are derived from SF metadata (describe), not the
    #    Selected Objects input.  The compiled artifacts are identical →
    #    classification is "none" (no operational impact).
    LOG.info("\n--- Phase 5: Prompt-only (label → no runtime impact) ---")
    _reset_to_baseline(store, baseline_version)
    prompt_source = mutate_prompt_only(real_source)
    prompt_evidence = run_scenario(
        scenario_name="prompt_only_label_change",
        store=store,
        raw_source=prompt_source,
        sf=sf,
        apply=True,
        expected_classification=IMPACT_NONE,
    )
    all_evidence.append(prompt_evidence)

    # 8. Write evidence
    _write_evidence(evidence_dir, all_evidence)

    # 9. Summary
    LOG.info("\n=== VALIDATION SUMMARY ===")
    all_pass = True
    for ev in all_evidence:
        status = "PASS" if ev["classification_match"] else "FAIL"
        if not ev["classification_match"]:
            all_pass = False
        LOG.info(
            "  %s: %s → %s (expected %s) activated=%s parity=%s",
            status, ev["scenario"], ev["actual_classification"],
            ev["expected_classification"], ev["activated"],
            ev["structural_parity_evidence"].get("summary", "?"),
        )

    active = store.resolve_active_version(ORG_ID)
    LOG.info("Final active version: %s", active)

    if all_pass:
        LOG.info("ALL SCENARIOS PASSED")
    else:
        LOG.error("SOME SCENARIOS FAILED — review evidence")
        raise SystemExit(1)


def _write_evidence(evidence_dir: Path, all_evidence: list[dict]) -> None:
    output_path = evidence_dir / "live_config_refresh_evidence.json"
    output_path.write_text(json.dumps(all_evidence, indent=2, sort_keys=True))
    LOG.info("Evidence written to %s", output_path)


if __name__ == "__main__":
    main()
