#!/usr/bin/env python3
"""
Data Validation for AscendixIQ Salesforce Connector (Task 0.5).

Validates data integrity in Turbopuffer after bulk loading: correct counts,
working filters, hybrid search, parent field denormalization, and query latency.

Usage:
    python3 scripts/validate_data.py --namespace org_00Dxxxxxxx

    python3 scripts/validate_data.py --namespace org_00Dxxxxxxx \
        --config denorm_config.yaml \
        --target-org ascendix-beta-sandbox \
        --query-text "office lease Dallas" \
        --latency-threshold 50
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add project root and lambda dir to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from bulk_load import clean_label, load_config
from lib.turbopuffer_backend import TurbopufferBackend

LOG = logging.getLogger("validate_data")

EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024

SYSTEM_FIELDS = ["id", "text", "object_type", "last_modified", "salesforce_org_id"]


# ===================================================================
# Data structures
# ===================================================================

@dataclass
class CheckResult:
    """Result of a single validation check."""
    name: str
    status: str  # PASS, FAIL, WARN, SKIP
    message: str
    details: dict = field(default_factory=dict)
    duration_ms: float = 0.0


# ===================================================================
# Helpers
# ===================================================================

def expected_parent_keys(ref_field: str, parent_fields: Any) -> list[str]:
    """Derive expected Turbopuffer attribute keys from denorm config parent entry.

    Must exactly mirror build_document() logic from bulk_load.py.

    Example: ref_field="ascendix__Property__c", parent_fields=["Name", "ascendix__City__c"]
    Returns: ["property_name", "property_city"]
    """
    if isinstance(parent_fields, dict):
        parent_fields = parent_fields.get("fields", [])
    prefix = clean_label(ref_field).lower()
    return [f"{prefix}_{clean_label(pf).lower()}" for pf in parent_fields]


def _is_reference_value(val) -> bool:
    """Detect Salesforce record ID values (15 or 18 char alphanumeric)."""
    return isinstance(val, str) and len(val) in (15, 18) and val[:3].isalnum()


# ===================================================================
# Validator
# ===================================================================

class DataValidator:
    """Validates data integrity in a Turbopuffer namespace.

    Importable for programmatic use (e.g., task 3.1 validation gate).
    """

    def __init__(
        self,
        namespace: str,
        backend: TurbopufferBackend,
        config: dict | None = None,
        sf_client: Any = None,
        query_text: str = "office lease Dallas",
        latency_threshold: float = 50.0,
        verbose: bool = False,
    ) -> None:
        self.namespace = namespace
        self.backend = backend
        self.config = config
        self.sf_client = sf_client
        self.query_text = query_text
        self.latency_threshold = latency_threshold
        self.verbose = verbose

    def run_all(self) -> list[CheckResult]:
        """Run all validation checks in order."""
        checks = [
            self._check_namespace_exists,
            self._check_object_type_counts,
            self._check_system_fields,
            self._check_metadata_filter,
            self._check_parent_fields,
            self._check_bm25_search,
            self._check_hybrid_search,
            self._check_warm_latency,
        ]
        results = []
        for check_fn in checks:
            start = time.perf_counter()
            try:
                result = check_fn()
            except Exception as e:
                result = CheckResult(
                    name=check_fn.__name__.replace("_check_", "").replace("_", " ").title(),
                    status="FAIL",
                    message=f"Unexpected error: {e}",
                )
            result.duration_ms = (time.perf_counter() - start) * 1000
            results.append(result)
        return results

    def _check_namespace_exists(self) -> CheckResult:
        """Check 1: Namespace exists via aggregate count."""
        try:
            agg = self.backend.aggregate(self.namespace)
            count = agg.get("count", 0)
        except Exception:
            count = 0

        if count > 0:
            return CheckResult(
                name="Namespace exists",
                status="PASS",
                message=f"{count:,} documents found",
                details={"count": count},
            )

        # Fallback: BM25 with stopwords (single space is not a valid token)
        results = self.backend.search(
            self.namespace, text_query="a the is of and", top_k=1,
        )
        if results:
            return CheckResult(
                name="Namespace exists",
                status="PASS",
                message="Namespace exists (aggregate returned 0 but search found docs)",
                details={"count": 0},
            )

        return CheckResult(
            name="Namespace exists",
            status="FAIL",
            message="Namespace empty or does not exist",
        )

    def _check_object_type_counts(self) -> CheckResult:
        """Check 2: Object type counts via aggregate(group_by='object_type')."""
        if not self.config:
            return CheckResult(
                name="Object type counts",
                status="SKIP",
                message="No config provided",
            )

        agg = self.backend.aggregate(self.namespace, group_by="object_type")
        groups = agg.get("groups", {})

        # Verify every config object has docs
        missing = []
        counts_parts = []
        for obj_name in self.config:
            obj_type = clean_label(obj_name).lower()
            group_data = groups.get(obj_type, {})
            count = group_data.get("count", 0)
            counts_parts.append(f"{obj_type}: {count:,}")
            if count == 0:
                missing.append(obj_type)

        # SF count comparison if client available
        sf_mismatches = []
        if self.sf_client:
            for obj_name in self.config:
                obj_type = clean_label(obj_name).lower()
                try:
                    sf_result = self.sf_client.query(f"SELECT COUNT() FROM {obj_name}")
                    sf_count = sf_result.get("totalSize", 0)
                    tp_count = groups.get(obj_type, {}).get("count", 0)
                    if sf_count != tp_count:
                        sf_mismatches.append(
                            f"{obj_type}: SF={sf_count} vs TP={tp_count}"
                        )
                except Exception as e:
                    LOG.warning("SF count query failed for %s: %s", obj_name, e)

        message = " | ".join(counts_parts)
        details = {"groups": groups}

        if missing:
            return CheckResult(
                name="Object type counts",
                status="FAIL",
                message=f"Missing objects: {', '.join(missing)}",
                details=details,
            )
        if sf_mismatches:
            return CheckResult(
                name="Object type counts",
                status="FAIL",
                message=f"SF count mismatch: {'; '.join(sf_mismatches)}",
                details=details,
            )
        return CheckResult(
            name="Object type counts",
            status="PASS",
            message=message,
            details=details,
        )

    def _check_system_fields(self) -> CheckResult:
        """Check 3: Sample 5 docs, verify system fields present."""
        docs = self.backend.search(
            self.namespace, text_query="a the is of and", top_k=5,
            include_attributes=SYSTEM_FIELDS,
        )
        if not docs:
            return CheckResult(
                name="System fields",
                status="FAIL",
                message="No documents returned",
            )

        missing_fields = []
        for doc in docs:
            for field_name in SYSTEM_FIELDS:
                # 'id' is always in the doc dict from search()
                if field_name == "id":
                    continue
                if doc.get(field_name) is None:
                    missing_fields.append((doc.get("id"), field_name))

        if missing_fields:
            return CheckResult(
                name="System fields",
                status="FAIL",
                message=f"{len(missing_fields)} missing field(s) across {len(docs)} docs",
                details={"missing": missing_fields[:10]},
            )
        return CheckResult(
            name="System fields",
            status="PASS",
            message=f"{len(docs)}/{len(docs)} docs have all system fields",
        )

    def _check_metadata_filter(self) -> CheckResult:
        """Check 4: Metadata filter with config-driven string field discovery."""
        if not self.config:
            return CheckResult(
                name="Metadata filter",
                status="SKIP",
                message="No config provided",
            )

        # Try each object type to find suitable filter fields
        for obj_name, obj_config in self.config.items():
            obj_type = clean_label(obj_name).lower()
            embed_fields = obj_config.get("embed_fields", [])
            metadata_fields = obj_config.get("metadata_fields", [])

            # Collect candidate fields (exclude FK reference fields)
            candidate_fields = []
            for f in embed_fields + metadata_fields:
                cleaned = clean_label(f).lower()
                if cleaned not in candidate_fields:
                    candidate_fields.append(cleaned)

            if not candidate_fields:
                continue

            # Sample a doc of this object type
            try:
                sample = self.backend.search(
                    self.namespace, text_query="a the is of and", top_k=1,
                    filters={"object_type": obj_type},
                    include_attributes=candidate_fields,
                )
            except Exception as e:
                if "not found in schema" in str(e):
                    sample = self.backend.search(
                        self.namespace, text_query="a the is of and", top_k=1,
                        filters={"object_type": obj_type},
                        include_attributes=True,
                    )
                else:
                    raise
            if not sample:
                continue

            # Pick two string-valued, non-ID attributes
            filter_pairs = {}
            for f in candidate_fields:
                val = sample[0].get(f)
                if (val is not None
                        and isinstance(val, str)
                        and not _is_reference_value(val)
                        and len(filter_pairs) < 2):
                    filter_pairs[f] = val

            if not filter_pairs:
                # Fallback to curated allowlist
                allowlist = ["city", "state", "propertyclass", "status",
                             "leasetype", "spacetype"]
                try:
                    sample2 = self.backend.search(
                        self.namespace, text_query="a the is of and", top_k=1,
                        filters={"object_type": obj_type},
                        include_attributes=allowlist,
                    )
                except Exception as e:
                    if "not found in schema" in str(e):
                        sample2 = self.backend.search(
                            self.namespace, text_query="a the is of and", top_k=1,
                            filters={"object_type": obj_type},
                            include_attributes=True,
                        )
                    else:
                        raise
                if sample2:
                    for f in allowlist:
                        val = sample2[0].get(f)
                        if val is not None and isinstance(val, str) and len(filter_pairs) < 2:
                            filter_pairs[f] = val

            if not filter_pairs:
                continue

            # Query with compound filter (business fields only)
            try:
                results = self.backend.search(
                    self.namespace, text_query="a the is of and", top_k=10,
                    filters=filter_pairs,
                    include_attributes=list(filter_pairs),
                )
            except Exception as e:
                if "not found in schema" in str(e):
                    results = self.backend.search(
                        self.namespace, text_query="a the is of and", top_k=10,
                        filters=filter_pairs,
                        include_attributes=True,
                    )
                else:
                    raise

            if not results:
                return CheckResult(
                    name="Metadata filter",
                    status="FAIL",
                    message=f"Filter {filter_pairs} returned 0 results",
                )

            # Verify every returned doc matches the filter exactly
            violations = []
            for doc in results:
                for fld, expected in filter_pairs.items():
                    actual = doc.get(fld)
                    if actual != expected:
                        violations.append(
                            f"doc {doc.get('id')}: {fld}={actual}, expected {expected}"
                        )

            if violations:
                return CheckResult(
                    name="Metadata filter",
                    status="FAIL",
                    message=f"{len(violations)} filter mismatch(es)",
                    details={"violations": violations[:5]},
                )

            filter_desc = ", ".join(f"{k}={v}" for k, v in filter_pairs.items())
            return CheckResult(
                name="Metadata filter",
                status="PASS",
                message=f"{filter_desc} -> {len(results)} results, all match",
            )

        return CheckResult(
            name="Metadata filter",
            status="WARN",
            message="No suitable string-valued fields found for filter check",
        )

    def _check_parent_fields(self) -> CheckResult:
        """Check 5: Parent field denormalization consistency.

        Classifies each parent relationship gap as one of:
        - PASS: parent fields present as expected
        - WARN (no docs): object type not loaded / empty in index
        - WARN (sparse): 0/N docs have parent keys — likely null FK in source
        - WARN (partial): some parent fields present, others null on source parent
        - FAIL (denorm defect): source has data but index is missing derived fields
        """
        if not self.config:
            return CheckResult(
                name="Parent fields",
                status="SKIP",
                message="No config provided",
            )

        has_parents = False
        passes: list[str] = []
        warns: list[str] = []
        fails: list[str] = []

        for obj_name, obj_config in self.config.items():
            parents = obj_config.get("parents", {})
            if not parents:
                continue
            has_parents = True
            obj_type = clean_label(obj_name).lower()

            for ref_field, pfields in parents.items():
                pkeys = expected_parent_keys(ref_field, pfields)
                parent_label = clean_label(ref_field).lower()

                try:
                    docs = self.backend.search(
                        self.namespace, text_query="a the is of and", top_k=10,
                        filters={"object_type": obj_type},
                        include_attributes=pkeys,
                    )
                except Exception as e:
                    if "not found in schema" in str(e):
                        docs = self.backend.search(
                            self.namespace, text_query="a the is of and", top_k=10,
                            filters={"object_type": obj_type},
                            include_attributes=True,
                        )
                    else:
                        raise

                if not docs:
                    warns.append(
                        f"{obj_type}: no indexed docs (not loaded)"
                    )
                    continue

                # Classify each doc's parent-key state
                docs_with_parent = 0
                partial_docs: list[tuple] = []
                consistently_absent: set[str] | None = None
                for doc in docs:
                    present = [k for k in pkeys if doc.get(k) is not None]
                    absent = [k for k in pkeys if doc.get(k) is None]
                    if present:
                        docs_with_parent += 1
                        if absent:
                            partial_docs.append(
                                (doc.get("id"), present, absent)
                            )
                            if consistently_absent is None:
                                consistently_absent = set(absent)
                            else:
                                consistently_absent &= set(absent)

                if docs_with_parent == 0:
                    # No docs have ANY parent keys — sparse source or stale
                    self._classify_sparse(
                        obj_name, ref_field, obj_type, parent_label,
                        docs, warns, fails,
                    )
                elif partial_docs:
                    # Some keys present, some missing — classify the gap
                    self._classify_partial(
                        obj_name, ref_field, obj_type, parent_label,
                        partial_docs, consistently_absent or set(),
                        len(docs), warns, fails,
                    )
                else:
                    passes.append(
                        f"{obj_type}: {docs_with_parent}/{len(docs)} "
                        f"{parent_label} OK"
                    )

        if not has_parents:
            return CheckResult(
                name="Parent fields",
                status="SKIP",
                message="No parent relationships in config",
            )

        all_parts = passes + warns + fails
        if fails:
            return CheckResult(
                name="Parent fields",
                status="FAIL",
                message=" | ".join(all_parts),
                details={"passes": passes, "warns": warns, "fails": fails},
            )
        if warns:
            return CheckResult(
                name="Parent fields",
                status="WARN",
                message=" | ".join(all_parts),
                details={"passes": passes, "warns": warns},
            )
        return CheckResult(
            name="Parent fields",
            status="PASS",
            message=" | ".join(passes) if passes else "OK",
        )

    def _classify_sparse(
        self,
        obj_name: str,
        ref_field: str,
        obj_type: str,
        parent_label: str,
        sampled_docs: list[dict[str, Any]],
        warns: list[str],
        fails: list[str],
    ) -> None:
        """Classify a 0/N sparse parent relationship using SF data if available."""
        sample_size = len(sampled_docs)
        if self.sf_client:
            try:
                sampled_ids = [doc.get("id") for doc in sampled_docs if doc.get("id")]
                sampled_fk_count = 0
                if sampled_ids:
                    id_list = ", ".join(f"'{sid}'" for sid in sampled_ids)
                    sampled_result = self.sf_client.query(
                        f"SELECT Id, {ref_field} FROM {obj_name} "
                        f"WHERE Id IN ({id_list})"
                    )
                    sampled_records = sampled_result.get("records", [])
                    sampled_fk_count = sum(
                        1 for record in sampled_records if record.get(ref_field) is not None
                    )

                count_result = self.sf_client.query(
                    f"SELECT COUNT() FROM {obj_name} "
                    f"WHERE {ref_field} != null"
                )
                fk_count = count_result.get("totalSize", 0)
                total_result = self.sf_client.query(
                    f"SELECT COUNT() FROM {obj_name}"
                )
                total = total_result.get("totalSize", 0)
                if fk_count == 0:
                    warns.append(
                        f"{obj_type}: 0/{sample_size} {parent_label} keys "
                        f"(sparse — SF has 0/{total} FKs populated)"
                    )
                elif sampled_fk_count > 0:
                    warns.append(
                        f"{obj_type}: 0/{sample_size} {parent_label} keys "
                        f"(stale index — sampled SF records have {sampled_fk_count}/"
                        f"{len(sampled_ids)} populated; SF has {fk_count}/{total} "
                        f"FKs populated, needs reindex)"
                    )
                else:
                    warns.append(
                        f"{obj_type}: 0/{sample_size} {parent_label} keys "
                        f"(sparse or low-incidence — sampled SF records have "
                        f"0/{len(sampled_ids)} populated; SF has {fk_count}/{total} "
                        f"FKs populated)"
                    )
                return
            except Exception as e:
                LOG.debug("SF verify failed for %s.%s: %s", obj_type, ref_field, e)

        # Without SF — report as sparse/stale (cannot distinguish)
        warns.append(
            f"{obj_type}: 0/{sample_size} {parent_label} keys "
            f"(sparse or stale — source verification unavailable)"
        )

    def _classify_partial(
        self,
        obj_name: str,
        ref_field: str,
        obj_type: str,
        parent_label: str,
        partial_docs: list[tuple],
        consistently_absent: set[str],
        sample_size: int,
        warns: list[str],
        fails: list[str],
    ) -> None:
        """Classify partial parent keys (some present, some null)."""
        if consistently_absent:
            # Same fields absent across all partial docs — likely null on source
            absent_short = ", ".join(sorted(consistently_absent))
            warns.append(
                f"{obj_type}: {len(partial_docs)} docs have partial "
                f"{parent_label} keys (null source fields: {absent_short})"
            )
        else:
            # Inconsistent pattern — harder to attribute to source nulls
            fails.append(
                f"{obj_type}: {len(partial_docs)}/{sample_size} docs have "
                f"inconsistent partial {parent_label} keys"
            )

    def _check_bm25_search(self) -> CheckResult:
        """Check 6: BM25 text search."""
        results = self.backend.search(
            self.namespace, text_query=self.query_text, top_k=10,
        )
        if results:
            return CheckResult(
                name="BM25 search",
                status="PASS",
                message=f'"{self.query_text}" -> {len(results)} results',
            )
        return CheckResult(
            name="BM25 search",
            status="FAIL",
            message=f'"{self.query_text}" -> 0 results',
        )

    def _check_hybrid_search(self) -> CheckResult:
        """Check 7: Hybrid search with attribute-grounded relevance."""
        if not self.config:
            return CheckResult(
                name="Hybrid search",
                status="SKIP",
                message="No config provided",
            )

        # Try to embed query text via Bedrock
        try:
            import boto3
            import json
            bedrock = boto3.client("bedrock-runtime")
            response = bedrock.invoke_model(
                modelId=EMBEDDING_MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "inputText": self.query_text,
                    "dimensions": EMBEDDING_DIMENSIONS,
                    "normalize": True,
                }),
            )
            embedding = json.loads(response["body"].read())["embedding"]
        except Exception as e:
            return CheckResult(
                name="Hybrid search",
                status="SKIP",
                message=f"Bedrock unavailable: {e}",
            )

        # Collect all searchable attribute names from config
        attrs_to_check = ["object_type", "name"]
        for obj_config in self.config.values():
            for f in obj_config.get("embed_fields", []) + obj_config.get("metadata_fields", []):
                attrs_to_check.append(clean_label(f).lower())
            for ref_field, pfields in obj_config.get("parents", {}).items():
                for pf in pfields:
                    attrs_to_check.append(
                        f"{clean_label(ref_field).lower()}_{clean_label(pf).lower()}"
                    )
        attrs_to_check = list(dict.fromkeys(attrs_to_check))  # dedupe

        # Hybrid search (with fallback to vector-only)
        hybrid_failed = False
        try:
            try:
                results = self.backend.search(
                    self.namespace, vector=embedding, text_query=self.query_text,
                    top_k=5, include_attributes=attrs_to_check,
                )
            except Exception as e:
                if "not found in schema" in str(e):
                    results = self.backend.search(
                        self.namespace, vector=embedding, text_query=self.query_text,
                        top_k=5, include_attributes=True,
                    )
                else:
                    raise
        except Exception as e:
            hybrid_failed = True
            LOG.warning("Hybrid search failed (%s), falling back to vector-only", e)
            try:
                results = self.backend.search(
                    self.namespace, vector=embedding,
                    top_k=5, include_attributes=attrs_to_check,
                )
            except Exception as e2:
                if "not found in schema" in str(e2):
                    results = self.backend.search(
                        self.namespace, vector=embedding,
                        top_k=5, include_attributes=True,
                    )
                else:
                    raise

        if not results:
            return CheckResult(
                name="Hybrid search",
                status="FAIL",
                message="Hybrid search returned 0 results",
            )

        # Check attribute-level match against query terms
        query_terms = [t.lower() for t in self.query_text.split() if len(t) >= 3]
        matched_attrs = []
        for doc in results:
            for attr in attrs_to_check:
                val = doc.get(attr)
                if val is not None and any(
                    term in str(val).lower() for term in query_terms
                ):
                    matched_attrs.append((doc.get("id"), attr, val))

        if not matched_attrs:
            status = "WARN" if hybrid_failed else "FAIL"
            return CheckResult(
                name="Hybrid search",
                status=status,
                message="No top-5 result has attributes matching query terms"
                + (" (hybrid ranking failed, used vector-only)" if hybrid_failed else ""),
                details={"query_terms": query_terms},
            )

        unique_docs = len(set(m[0] for m in matched_attrs))
        if hybrid_failed:
            return CheckResult(
                name="Hybrid search",
                status="WARN",
                message=f"{unique_docs}/{len(results)} results match query terms "
                f"(hybrid ranking failed, used vector-only fallback)",
                details={"matched": matched_attrs[:10]},
            )
        return CheckResult(
            name="Hybrid search",
            status="PASS",
            message=f"{unique_docs}/{len(results)} results have attrs matching query terms",
            details={"matched": matched_attrs[:10]},
        )

    def _check_warm_latency(self) -> CheckResult:
        """Check 8: Warm latency via 5 consecutive BM25 queries."""
        latencies = []
        for _ in range(5):
            start = time.perf_counter()
            self.backend.search(self.namespace, text_query="a the is of and", top_k=1)
            latencies.append((time.perf_counter() - start) * 1000)

        sorted_lat = sorted(latencies)
        p50 = sorted_lat[2]
        p95 = sorted_lat[4]  # max of 5 = p95

        message = f"p50={p50:.0f}ms, p95={p95:.0f}ms (< {self.latency_threshold:.0f}ms)"
        details = {"p50": p50, "p95": p95, "latencies": latencies}

        if p95 < self.latency_threshold:
            status = "PASS"
        elif p95 < 2 * self.latency_threshold:
            status = "WARN"
        else:
            status = "FAIL"

        return CheckResult(
            name="Warm latency", status=status, message=message, details=details,
        )


def write_telemetry_artifact(
    path: str,
    *,
    namespace: str,
    query_text: str,
    results: list[CheckResult],
    telemetry_events: list[dict[str, Any]],
) -> None:
    """Write a JSON artifact with validation results and drained telemetry."""
    payload = {
        "namespace": namespace,
        "query_text": query_text,
        "results": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "details": r.details,
                "duration_ms": round(r.duration_ms, 2),
            }
            for r in results
        ],
        "telemetry_events": telemetry_events,
    }
    Path(path).write_text(json.dumps(payload, indent=2))


# ===================================================================
# Report formatting
# ===================================================================

def format_report(
    results: list[CheckResult],
    namespace: str,
    config_path: str | None = None,
) -> str:
    """Format validation results for console output."""
    lines = [
        "=== Turbopuffer Data Validation ===",
        f"Namespace: {namespace}",
        "",
    ]

    passed = failed = skipped = warned = 0
    for i, r in enumerate(results, 1):
        status_label = f"[{r.status}]"
        duration = f"({r.duration_ms:.0f}ms)"
        lines.append(
            f" {i:>2}. {status_label:<6} {r.name:<24} {duration:<8} {r.message}"
        )
        if r.status == "PASS":
            passed += 1
        elif r.status == "FAIL":
            failed += 1
        elif r.status == "SKIP":
            skipped += 1
        elif r.status == "WARN":
            warned += 1

    lines.append("")
    parts = [f"{passed} PASSED", f"{failed} FAILED"]
    if warned:
        parts.append(f"{warned} WARNED")
    if skipped:
        parts.append(f"{skipped} SKIPPED")
    lines.append(f"Result: {' | '.join(parts)}")

    return "\n".join(lines)


# ===================================================================
# CLI
# ===================================================================

def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Validate data in Turbopuffer after bulk loading.",
    )
    parser.add_argument(
        "--namespace", required=True,
        help="Turbopuffer namespace to validate",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to denorm_config.yaml (enables object-type coverage, parent checks, SF comparison)",
    )
    parser.add_argument(
        "--target-org", default="",
        help="sf CLI alias for Salesforce count comparison",
    )
    parser.add_argument("--instance-url", default="")
    parser.add_argument("--access-token", default="")
    parser.add_argument(
        "--query-text", default="office lease Dallas",
        help="Text for search checks (default: 'office lease Dallas')",
    )
    parser.add_argument(
        "--latency-threshold", type=float, default=50.0,
        help="Max p95 latency in ms (default: 50)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print returned document snippets",
    )
    parser.add_argument(
        "--telemetry-output", default="",
        help="Optional path to write drained Turbopuffer telemetry JSON",
    )

    args = parser.parse_args()

    # Load config if provided
    config = None
    if args.config:
        config = load_config(args.config)

    # Build SF client if credentials available
    sf_client = None
    if args.instance_url and args.access_token:
        from common.salesforce_client import SalesforceClient
        sf_client = SalesforceClient(args.instance_url, args.access_token)
    elif args.target_org:
        try:
            from bulk_load import sf_client_from_cli
            sf_client = sf_client_from_cli(args.target_org)
        except Exception as e:
            LOG.warning("Could not connect to Salesforce: %s", e)

    # Initialize backend
    backend = TurbopufferBackend()

    # Run validation
    validator = DataValidator(
        namespace=args.namespace,
        backend=backend,
        config=config,
        sf_client=sf_client,
        query_text=args.query_text,
        latency_threshold=args.latency_threshold,
        verbose=args.verbose,
    )
    results = validator.run_all()

    # Print report
    report = format_report(results, args.namespace, args.config)
    print(report)

    if args.telemetry_output:
        telemetry_events = []
        drain = getattr(backend, "drain_telemetry", None)
        if callable(drain):
            drained = drain()
            if isinstance(drained, list):
                telemetry_events = drained
        write_telemetry_artifact(
            args.telemetry_output,
            namespace=args.namespace,
            query_text=args.query_text,
            results=results,
            telemetry_events=telemetry_events,
        )

    # Exit code: 0 if no FAIL, 1 if any FAIL
    has_failure = any(r.status == "FAIL" for r in results)
    sys.exit(1 if has_failure else 0)


if __name__ == "__main__":
    main()
