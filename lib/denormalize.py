"""Pure denormalization functions for Salesforce CRE records.

Extracted from scripts/bulk_load.py so they can be shared between the
bulk loader and the CDC sync Lambda.  Every function here is stateless
and free of I/O — it transforms data in memory only.
"""

from __future__ import annotations

from typing import Any

# ===================================================================
# Embedding constants
# ===================================================================

EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1024

# ===================================================================
# Turbopuffer schema
# ===================================================================

FULL_TEXT_SEARCH_SCHEMA: dict[str, dict[str, Any]] = {
    "text": {"type": "string", "full_text_search": True},
    # Declare numeric fields as float to avoid int/float inference conflicts
    "totalbuildingarea": {"type": "float"},
    "floors": {"type": "float"},
    "occupancy": {"type": "float"},
    "landarea": {"type": "float"},
    "size": {"type": "float"},
    "leaserateperuom": {"type": "float"},
    "averagerent": {"type": "float"},
    "termmonths": {"type": "float"},
    "availablearea": {"type": "float"},
    "rentlow": {"type": "float"},
    "renthigh": {"type": "float"},
    "askingprice": {"type": "float"},
    "maxcontiguousarea": {"type": "float"},
    "mindivisiblearea": {"type": "float"},
    "leasetermmin": {"type": "float"},
    "leasetermmax": {"type": "float"},
    "property_totalbuildingarea": {"type": "float"},
    # Deal numeric fields
    "dealamount": {"type": "float"},
    "probability": {"type": "float"},
    "commission": {"type": "float"},
    "leaserate": {"type": "float"},
    # Sale numeric fields
    "saleprice": {"type": "float"},
    "pricepersf": {"type": "float"},
    "caprate": {"type": "float"},
    "noi": {"type": "float"},
}


# ===================================================================
# Field name utilities
# ===================================================================


def clean_label(field_name: str) -> str:
    """Strip namespace prefix and custom suffixes for human-readable labels.

    ascendix__City__c -> City, ascendix__Property__r -> Property, Name -> Name
    """
    return field_name.replace("ascendix__", "").replace("__c", "").replace("__r", "")


# ===================================================================
# Stage 1: SOQL construction
# ===================================================================


def build_soql(
    object_name: str,
    embed_fields: list[str],
    metadata_fields: list[str],
    parent_config: dict[str, list[str]],
    rel_map: dict[str, str],
) -> str:
    """Build SELECT SOQL with direct fields + parent relationship fields."""
    select_parts: list[str] = ["Id", "LastModifiedDate"]
    seen: set[str] = set(select_parts)

    # Direct fields (embed + metadata), deduped
    for f in embed_fields + metadata_fields:
        if f not in seen:
            select_parts.append(f)
            seen.add(f)

    # Parent relationship fields
    for ref_field, parent_fields in parent_config.items():
        rel_name = rel_map[ref_field]  # already validated
        # Include the FK field itself if not already present
        if ref_field not in seen:
            select_parts.append(ref_field)
            seen.add(ref_field)
        for pf in parent_fields:
            dotted = f"{rel_name}.{pf}"
            if dotted not in seen:
                select_parts.append(dotted)
                seen.add(dotted)

    return f"SELECT {', '.join(select_parts)} FROM {object_name}"


# ===================================================================
# Stage 2: Flatten
# ===================================================================


def flatten(
    record: dict,
    embed_fields: list[str],
    metadata_fields: list[str],
    parent_config: dict[str, list[str]],
    rel_map: dict[str, str],
) -> tuple[dict, dict]:
    """Extract direct_fields and parent_fields from a raw SF record.

    Returns:
        direct_fields: {raw_field_name: value} for embed + metadata + system fields
        parent_fields: {ref_field: {raw_parent_field: value}} per config
    """
    direct_fields: dict[str, Any] = {}
    for f in embed_fields + metadata_fields:
        val = record.get(f)
        if val is not None:
            direct_fields[f] = val

    # System fields always present
    direct_fields["Id"] = record["Id"]
    direct_fields["LastModifiedDate"] = record.get("LastModifiedDate")

    parent_fields: dict[str, dict] = {}
    for ref_field, pfield_names in parent_config.items():
        rel_name = rel_map[ref_field]
        parent_record = record.get(rel_name) or {}
        pvals: dict[str, Any] = {}
        for pf in pfield_names:
            val = parent_record.get(pf)
            if val is not None:
                pvals[pf] = val
        parent_fields[ref_field] = pvals

    return direct_fields, parent_fields


# ===================================================================
# Stage 3: Text generation
# ===================================================================


def build_text(
    direct_fields: dict,
    parent_fields: dict,
    embed_field_names: list[str],
    parent_config: dict,
    object_type: str,
) -> str:
    """Build embedding text from direct + parent fields.

    Lookups use raw SF names; labels are cleaned for readability.
    """
    parts: list[str] = [f"{clean_label(object_type)}:"]

    # Direct embed fields
    for field in embed_field_names:
        val = direct_fields.get(field)
        if val is not None:
            parts.append(f"{clean_label(field)}: {val}")

    # Parent denormalized fields
    for ref_field, pfield_names in parent_config.items():
        parent_vals = parent_fields.get(ref_field, {})
        for pf in pfield_names:
            val = parent_vals.get(pf)
            if val is not None:
                parts.append(f"{clean_label(pf)}: {val}")

    return " | ".join(parts)


# ===================================================================
# Stage 4: Document building
# ===================================================================


def build_document(
    direct_fields: dict,
    parent_fields: dict,
    text: str,
    vector: list[float],
    record_id: str,
    object_type: str,
    salesforce_org_id: str,
    embed_field_names: list[str],
    metadata_field_names: list[str],
    parent_config: dict,
) -> dict:
    """Build final Turbopuffer document with cleaned attribute keys."""
    doc: dict[str, Any] = {
        "id": record_id,
        "vector": vector,
        "text": text,
        "object_type": clean_label(object_type).lower(),
        "last_modified": direct_fields.get("LastModifiedDate", ""),
        "salesforce_org_id": salesforce_org_id,
    }

    # Direct fields with cleaned keys
    for f in embed_field_names + metadata_field_names:
        val = direct_fields.get(f)
        if val is not None:
            doc[clean_label(f).lower()] = val

    # Parent fields with prefixed cleaned keys
    for ref_field, pfield_names in parent_config.items():
        prefix = clean_label(ref_field).lower()
        parent_vals = parent_fields.get(ref_field, {})
        for pf in pfield_names:
            val = parent_vals.get(pf)
            if val is not None:
                doc[f"{prefix}_{clean_label(pf).lower()}"] = val

    return doc
