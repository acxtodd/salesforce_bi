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

PINNED_TEXT_FULL_TEXT_SETTINGS: dict[str, Any] = {
    # Pin tokenizer behavior so BM25 relevance does not drift with vendor defaults.
    "tokenizer": "word_v3",
    "language": "english",
    "stemming": False,
    "remove_stopwords": False,
}

FULL_TEXT_SEARCH_SCHEMA: dict[str, dict[str, Any]] = {
    "text": {
        "type": "string",
        "full_text_search": PINNED_TEXT_FULL_TEXT_SETTINGS,
    },
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
    "salepriceperuom": {"type": "float"},
    "capratepercent": {"type": "float"},
    "netincome": {"type": "float"},
    "listingprice": {"type": "float"},
    "totalarea": {"type": "float"},
    "pricepersf": {"type": "float"},
    "caprate": {"type": "float"},
    "noi": {"type": "float"},
    # Deal numeric fields (expanded)
    "grossfeeamount": {"type": "float"},
    # Inquiry numeric fields
    "desiredsize": {"type": "float"},
    "desiredrent": {"type": "float"},
    # Listing numeric fields
    "askingrate": {"type": "float"},
    # Preference numeric fields
    "minsize": {"type": "float"},
    "maxsize": {"type": "float"},
    "minrate": {"type": "float"},
    "maxrate": {"type": "float"},
    # Geospatial component fields
    "geolocationlatitude": {"type": "float"},
    "geolocationlongitude": {"type": "float"},
}


def build_tpuf_schema(
    documents: list[dict[str, Any]],
    *,
    base_schema: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a stable Turbopuffer schema for a batch of denormed documents.

    Turbopuffer infers attribute types from early writes. Parent compact-layout
    fields can introduce late-arriving numeric attributes or mix ints/floats
    across batches, so predeclare every numeric attribute as float.
    """
    schema = {
        key: dict(value)
        for key, value in (base_schema or FULL_TEXT_SEARCH_SCHEMA).items()
    }
    for document in documents:
        for field_name, value in document.items():
            if field_name in schema:
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                schema[field_name] = {"type": "float"}
    return schema


# ===================================================================
# Field name utilities
# ===================================================================


def clean_label(field_name: str) -> str:
    """Strip namespace prefix and custom suffixes for human-readable labels.

    ascendix__City__c -> City, ascendix__Property__r -> Property, Name -> Name
    """
    cleaned = (
        field_name.replace("ascendix__", "")
        .replace("__Latitude__s", "Latitude")
        .replace("__Longitude__s", "Longitude")
        .replace("__c", "")
        .replace("__r", "")
    )
    if cleaned.endswith("Id") and cleaned != "Id":
        cleaned = cleaned[:-2]
    return cleaned


def _normalize_parent_entry(ref_field: str, entry: Any) -> dict[str, Any]:
    """Normalize legacy/new parent config entries to one internal shape."""
    if isinstance(entry, dict):
        fields = entry.get("fields", [])
        return {
            "fields": list(fields),
            "relationship_label": entry.get("relationship_label", clean_label(ref_field)),
            "parent_object_api": entry.get("parent_object_api", ""),
            "parent_object_label": entry.get("parent_object_label", ""),
            "name_field": entry.get("name_field", "Name"),
        }
    return {
        "fields": list(entry),
        "relationship_label": clean_label(ref_field),
        "parent_object_api": "",
        "parent_object_label": "",
        "name_field": "Name",
    }


def _relationship_name(rel_entry: Any) -> str:
    """Extract the SOQL relationship name from a rel-map entry."""
    if isinstance(rel_entry, dict):
        return rel_entry["relationship_name"]
    return rel_entry


def _relationship_label(ref_field: str, rel_entry: Any) -> str:
    """Resolve a human label for the parent relationship."""
    if isinstance(rel_entry, dict):
        return rel_entry.get("relationship_label") or clean_label(ref_field)
    return clean_label(ref_field)


def _parent_object_api(rel_entry: Any) -> str:
    if isinstance(rel_entry, dict):
        return rel_entry.get("parent_object_api", "")
    return ""


def _parent_object_label(ref_field: str, rel_entry: Any) -> str:
    if isinstance(rel_entry, dict):
        return rel_entry.get("parent_object_label") or clean_label(
            rel_entry.get("parent_object_api", "")
        )
    return ""


def build_relationship_map(sf_client: Any, object_name: str) -> dict[str, dict[str, str]]:
    """Return lookup metadata keyed by reference field API name.

    Each entry contains the SOQL relationship name plus human/object labels
    so denormalized records can preserve business role context.
    """
    desc = sf_client.describe(object_name)
    parent_labels: dict[str, str] = {}
    rel_map: dict[str, dict[str, str]] = {}
    for field in desc["fields"]:
        if field["type"] != "reference" or not field.get("relationshipName"):
            continue
        parent_object_api = (field.get("referenceTo") or [""])[0]
        if parent_object_api and parent_object_api not in parent_labels:
            try:
                parent_labels[parent_object_api] = sf_client.describe(parent_object_api).get(
                    "label", clean_label(parent_object_api)
                )
            except Exception:
                parent_labels[parent_object_api] = clean_label(parent_object_api)
        rel_map[field["name"]] = {
            "relationship_name": field["relationshipName"],
            "relationship_label": field.get("label", clean_label(field["name"])),
            "parent_object_api": parent_object_api,
            "parent_object_label": parent_labels.get(
                parent_object_api, clean_label(parent_object_api)
            ),
        }
    return rel_map


# ===================================================================
# Stage 1: SOQL construction
# ===================================================================


def build_soql(
    object_name: str,
    embed_fields: list[str],
    metadata_fields: list[str],
    parent_config: dict[str, Any],
    rel_map: dict[str, Any],
    where_clause: str | None = None,
) -> str:
    """Build SELECT SOQL with direct fields + parent relationship fields.

    Parameters
    ----------
    where_clause:
        Optional WHERE/ORDER/LIMIT clause to append (e.g. for poll sync).
        Should include the ``WHERE`` keyword if filtering is needed.
    """
    select_parts: list[str] = ["Id", "LastModifiedDate"]
    seen: set[str] = set(select_parts)

    # Direct fields (embed + metadata), deduped
    for f in embed_fields + metadata_fields:
        if f not in seen:
            select_parts.append(f)
            seen.add(f)

    # Parent relationship fields
    for ref_field, entry in parent_config.items():
        rel_name = _relationship_name(rel_map[ref_field])  # already validated
        parent_fields = _normalize_parent_entry(ref_field, entry)["fields"]
        # Include the FK field itself if not already present
        if ref_field not in seen:
            select_parts.append(ref_field)
            seen.add(ref_field)
        for pf in parent_fields:
            dotted = f"{rel_name}.{pf}"
            if dotted not in seen:
                select_parts.append(dotted)
                seen.add(dotted)

    soql = f"SELECT {', '.join(select_parts)} FROM {object_name}"
    if where_clause:
        soql += f" {where_clause}"
    return soql


# ===================================================================
# Stage 2: Flatten
# ===================================================================


def flatten(
    record: dict,
    embed_fields: list[str],
    metadata_fields: list[str],
    parent_config: dict[str, Any],
    rel_map: dict[str, Any],
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
    for ref_field, entry in parent_config.items():
        rel_name = _relationship_name(rel_map[ref_field])
        pfield_names = _normalize_parent_entry(ref_field, entry)["fields"]
        direct_fields[ref_field] = record.get(ref_field)
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
    rel_map: dict[str, Any] | None = None,
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
    for ref_field, entry in parent_config.items():
        pfield_names = _normalize_parent_entry(ref_field, entry)["fields"]
        parent_vals = parent_fields.get(ref_field, {})
        rel_label = (
            _relationship_label(ref_field, rel_map.get(ref_field))
            if rel_map is not None and ref_field in rel_map
            else clean_label(ref_field)
        )
        for pf in pfield_names:
            val = parent_vals.get(pf)
            if val is not None:
                parts.append(f"{rel_label} {clean_label(pf)}: {val}")

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
    rel_map: dict[str, Any] | None = None,
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
    for ref_field, entry in parent_config.items():
        pfield_names = _normalize_parent_entry(ref_field, entry)["fields"]
        prefix = clean_label(ref_field).lower()
        parent_vals = parent_fields.get(ref_field, {})
        parent_id = direct_fields.get(ref_field)
        if parent_id is not None:
            doc[f"{prefix}_id"] = parent_id
        for pf in pfield_names:
            val = parent_vals.get(pf)
            if val is not None:
                doc[f"{prefix}_{clean_label(pf).lower()}"] = val

    return doc
