"""
Chunking Lambda Function
Splits Salesforce records into 300-500 token chunks with metadata enrichment.
Writes chunks to S3 to avoid Step Functions payload limits.

Phase 2.5 Updates (2025-11-25):
- Added temporal status computation for Lease and Deal objects
- Added relationship context extraction for cross-object queries

Zero-Config Production Updates (2025-12):
- Removed POC_OBJECT_FIELDS hardcoded dictionary
- Uses ConfigurationCache for dynamic field configuration
- Uses Schema Cache for type-aware field formatting

**Feature: zero-config-production**
**Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
"""

import json
import os
import re
import sys
import boto3
import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

# Initialize S3 client
s3_client = boto3.client("s3")

# Environment variables
DATA_BUCKET = os.environ.get("DATA_BUCKET")

# Token estimation: ~4 characters per token (rough approximation)
CHARS_PER_TOKEN = 4
MIN_CHUNK_TOKENS = 300
MAX_CHUNK_TOKENS = 500
MIN_CHUNK_CHARS = MIN_CHUNK_TOKENS * CHARS_PER_TOKEN
MAX_CHUNK_CHARS = MAX_CHUNK_TOKENS * CHARS_PER_TOKEN

# Temporal status configuration
TEMPORAL_STATUS_CONFIG = {
    "ascendix__Lease__c": {
        "date_field": "ascendix__TermExpirationDate__c",
        "status_label": "Lease Status",
        "compute_func": "compute_lease_status",
    },
    "ascendix__Deal__c": {"date_field": "CreatedDate", "status_label": "Deal Age", "compute_func": "compute_deal_age"},
}

# Object-specific fallback configs with proper relationship fields for CRE objects
# Used when ConfigurationCache returns default config without relationship traversal
FALLBACK_CONFIGS = {
    "ascendix__Property__c": {
        "Display_Name_Field__c": "Name",
        # Text fields include all filterable/searchable attributes from schema cache
        # NOTE: Do NOT use RecordType.Name (with dot) - OpenSearch treats it as nested field
        # Use RecordType or RecordTypeName instead (already extracted separately)
        # Updated 2025-12-10: Removed fake fields (PropertyType__c, Status__c, Submarket__c,
        # Address__c, TotalSqFt__c, AvailableSqFt__c, VacancyRate__c, AskingRent__c)
        # and replaced with verified SF fields from Schema Discovery
        "Text_Fields__c": "Name, RecordType, ascendix__PropertyClass__c, ascendix__BuildingStatus__c, ascendix__City__c, ascendix__State__c, ascendix__Street__c, ascendix__TotalAvailableArea__c, ascendix__YearBuilt__c, ascendix__AverageRent__c, ascendix__Tenancy__c",
        "Long_Text_Fields__c": "ascendix__LocationDescription__c",
        "Relationship_Fields__c": "OwnerId, ascendix__PropertyManager__c, ascendix__OwnerLandlord__c",
        "Enabled__c": True,
    },
    "ascendix__Availability__c": {
        "Display_Name_Field__c": "Name",
        # Updated 2025-12-10: Added RecordType and UseType for space type queries
        "Text_Fields__c": "Name, RecordType, ascendix__Status__c, ascendix__LeaseType__c, ascendix__UseType__c",
        "Long_Text_Fields__c": "",
        # NOTE: Do NOT use RecordType.Name (with dot) - OpenSearch treats it as nested field
        "Relationship_Fields__c": "ascendix__Property__c, ascendix__Property__r.Name, ascendix__Property__r.ascendix__City__c, ascendix__Property__r.ascendix__State__c, ascendix__Property__r.ascendix__PropertyClass__c",
        "Enabled__c": True,
    },
    "ascendix__Lease__c": {
        "Display_Name_Field__c": "Name",
        "Text_Fields__c": "Name",
        "Long_Text_Fields__c": "",
        "Relationship_Fields__c": "ascendix__Property__c, ascendix__Property__r.Name, ascendix__Property__r.ascendix__City__c, ascendix__Property__r.ascendix__State__c, ascendix__Property__r.ascendix__PropertyClass__c",
        "Enabled__c": True,
    },
    "ascendix__Deal__c": {
        "Display_Name_Field__c": "Name",
        "Text_Fields__c": "Name",
        "Long_Text_Fields__c": "",
        # Updated 2025-12-10: Added broker/party relationship fields for "deals where X is involved" queries
        "Relationship_Fields__c": ", ".join([
            # Property
            "ascendix__Property__c",
            # Broker fields (for "deals where Transwestern is involved")
            "ascendix__TenantRepBroker__c",
            "ascendix__ListingBrokerCompany__c",
            "ascendix__BuyerRep__c",
            "ascendix__LeadBrokerCompany__c",
            # Party/Client fields
            "ascendix__Client__c",
            "ascendix__Buyer__c",
            "ascendix__Seller__c",
            "ascendix__Tenant__c",
            "ascendix__OwnerLandlord__c",
            "ascendix__Lender__c",
        ]),
        "Enabled__c": True,
    },
    # Updated 2025-12-10: Added Listing with broker relationships
    "ascendix__Listing__c": {
        "Display_Name_Field__c": "Name",
        "Text_Fields__c": "Name, RecordType",
        "Long_Text_Fields__c": "",
        "Relationship_Fields__c": ", ".join([
            "ascendix__Property__c",
            "ascendix__ListingBrokerCompany__c",
            "ascendix__ListingBrokerContact__c",
            "ascendix__OwnerLandlord__c",
            "ascendix__OwnerLandlordContact__c",
        ]),
        "Enabled__c": True,
    },
    # Updated 2025-12-10: Added Inquiry with broker relationships
    "ascendix__Inquiry__c": {
        "Display_Name_Field__c": "Name",
        "Text_Fields__c": "Name, RecordType",
        "Long_Text_Fields__c": "",
        "Relationship_Fields__c": ", ".join([
            "ascendix__Property__c",
            "ascendix__Availability__c",
            "ascendix__Listing__c",
            "ascendix__BrokerCompany__c",
            "ascendix__BrokerContact__c",
        ]),
        "Enabled__c": True,
    },
}

# Default config if no fallback and no cache config available
DEFAULT_CHUNKING_CONFIG = {
    "Display_Name_Field__c": "Name",
    "Text_Fields__c": "Name",
    "Long_Text_Fields__c": "",
    "Relationship_Fields__c": "OwnerId",
    "Enabled__c": True,
}


def compute_lease_status(days_until_expiration: int) -> str:
    """Compute lease temporal status based on days until expiration."""
    if days_until_expiration < 0:
        return f"EXPIRED ({abs(days_until_expiration)} days ago)"
    elif days_until_expiration <= 30:
        return f"EXPIRING_THIS_MONTH ({days_until_expiration} days)"
    elif days_until_expiration <= 90:
        return f"EXPIRING_SOON ({days_until_expiration} days)"
    else:
        return f"ACTIVE (expires in {days_until_expiration} days)"


def compute_deal_age(days_since_created: int) -> str:
    """Compute deal age status based on days since creation."""
    if days_since_created <= 7:
        return "NEW (this week)"
    elif days_since_created <= 30:
        return "RECENT (this month)"
    elif days_since_created <= 90:
        return "THIS_QUARTER (last 3 months)"
    else:
        return f"OLDER ({days_since_created} days)"


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse ISO date string to datetime object."""
    if not date_str:
        return None
    try:
        # Handle various ISO formats
        date_str = date_str.replace("Z", "+00:00")
        if "." in date_str:
            # Handle milliseconds
            date_str = re.sub(r"\.\d+", "", date_str)
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def add_temporal_context(record: Dict[str, Any], sobject: str, text_parts: List[str]) -> None:
    """Add computed temporal status to chunk text for time-based queries."""
    if sobject not in TEMPORAL_STATUS_CONFIG:
        return

    config = TEMPORAL_STATUS_CONFIG[sobject]
    date_field = config["date_field"]
    status_label = config["status_label"]

    date_value = record.get(date_field)
    if not date_value:
        return

    parsed_date = parse_date(date_value)
    if not parsed_date:
        return

    now = datetime.now(timezone.utc)
    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=timezone.utc)

    if sobject == "ascendix__Lease__c":
        days_diff = (parsed_date - now).days
        status = compute_lease_status(days_diff)
    elif sobject == "ascendix__Deal__c":
        days_diff = (now - parsed_date).days
        status = compute_deal_age(days_diff)
    else:
        return

    text_parts.append(f"{status_label}: {status}")


def add_relationship_context(
    record: Dict[str, Any], sobject: str, text_parts: List[str], config: Dict[str, Any]
) -> None:
    """
    Add related object context to chunk text for cross-object queries.
    Extracts relationship data from nested __r fields in the record.

    **Requirements: 3.6**
    Uses Relationship_Fields__c from configuration instead of hardcoded RELATIONSHIP_ENRICHMENT.
    """
    relationship_fields = _parse_field_list(config.get("Relationship_Fields__c", ""))
    if not relationship_fields:
        return

    relationship_parts = []

    for lookup_field in relationship_fields:
        # Check for nested relationship data (e.g., ascendix__Property__r)
        rel_field_name = lookup_field.replace("__c", "__r")
        related_data = record.get(rel_field_name)

        if related_data and isinstance(related_data, dict):
            # Extract label from field name
            label = _get_relationship_label(lookup_field)

            # Extract Name and key fields from related record
            name = related_data.get("Name")
            if name:
                relationship_parts.append(f"{label}: {name}")

            # Extract common location fields if present
            city = related_data.get("ascendix__City__c") or related_data.get("City__c")
            state = related_data.get("ascendix__State__c") or related_data.get("State__c")
            prop_class = related_data.get("ascendix__PropertyClass__c") or related_data.get("PropertyClass__c")

            if city:
                relationship_parts.append(f"{label} City: {city}")
            if state:
                relationship_parts.append(f"{label} State: {state}")
            if prop_class:
                relationship_parts.append(f"{label} Class: {prop_class}")

            # Extract RecordType.Name for property type (Office, Retail, Industrial, etc.)
            record_type_data = related_data.get("RecordType")
            if record_type_data and isinstance(record_type_data, dict):
                record_type_name = record_type_data.get("Name")
                if record_type_name:
                    relationship_parts.append(f"{label} Type: {record_type_name}")
        else:
            # Fallback: just add the ID reference if no nested data
            lookup_id = record.get(lookup_field)
            if lookup_id and lookup_field not in ("OwnerId", "ParentId"):
                label = _get_relationship_label(lookup_field)
                relationship_parts.append(f"{label} ID: {lookup_id}")

    if relationship_parts:
        text_parts.append("\n--- Related Context ---")
        text_parts.extend(relationship_parts)


def _get_relationship_label(field_name: str) -> str:
    """Extract a human-readable label from a relationship field name."""
    # Remove namespace prefix
    name = field_name
    if name.startswith("ascendix__"):
        name = name[10:]
    # Remove __c suffix
    if name.endswith("__c"):
        name = name[:-3]
    # Add spaces before capitals
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return name


def estimate_tokens(text: str) -> int:
    """Estimate token count for text (rough approximation)."""
    return len(text) // CHARS_PER_TOKEN


def format_field_name(field: str) -> str:
    """Convert API field name to human-readable label."""
    name = field
    if name.startswith("ascendix__"):
        name = name[10:]
    if name.endswith("__c"):
        name = name[:-3]
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return name


def _parse_field_list(field_str: Optional[str]) -> List[str]:
    """
    Parse comma-separated field list from configuration.

    Args:
        field_str: Comma-separated field names or None

    Returns:
        List of field names (empty list if None or empty)
    """
    if not field_str:
        return []
    return [f.strip() for f in field_str.split(",") if f.strip()]


def _get_schema_cache():
    """
    Get or create Schema Cache instance for type-aware formatting.

    Returns:
        SchemaCache instance or None if unavailable
    """
    # Try multiple import paths for Lambda vs local development
    import_paths = [
        # Direct import (if bundled in Lambda layer or same package)
        None,
        # Local development path
        os.path.join(os.path.dirname(__file__), "..", "schema_discovery"),
        os.path.join(os.path.dirname(__file__), "..", "retrieve", "schema_discovery"),
    ]

    for path in import_paths:
        try:
            if path and path not in sys.path:
                sys.path.insert(0, path)

            from schema_discovery.cache import SchemaCache
            print(f"[SCHEMA] Loaded SchemaCache successfully")
            return SchemaCache()
        except ImportError:
            try:
                from cache import SchemaCache
                print(f"[SCHEMA] Loaded SchemaCache from cache module")
                return SchemaCache()
            except ImportError:
                continue

    print(f"Warning: Could not load Schema Cache from any path")
    return None


def _get_field_type_from_schema(field_name: str, schema) -> Optional[str]:
    """
    Get the Salesforce field type from schema.

    Args:
        field_name: Field API name
        schema: ObjectSchema instance

    Returns:
        Salesforce field type (e.g., 'date', 'currency', 'percent') or None
    """
    if schema is None:
        return None

    field_schema = schema.get_field(field_name)
    if field_schema:
        return field_schema.sf_type
    return None


def _format_field_value(value: Any, field_name: str, schema=None) -> str:
    """
    Format field value based on schema type.

    **Requirements: 3.3, 3.4, 3.5**

    - Date/DateTime: ISO 8601 format
    - Currency: Symbol + decimal places
    - Percent: Value + % symbol
    - Other: String conversion

    Args:
        value: Field value to format
        field_name: Field API name
        schema: Optional ObjectSchema for type information

    Returns:
        Formatted string value
    """
    if value is None:
        return ""

    # Get field type from schema if available
    sf_type = _get_field_type_from_schema(field_name, schema)

    # Format based on type
    if sf_type == "date":
        # Format Date as ISO 8601 (YYYY-MM-DD)
        try:
            if isinstance(value, str):
                parsed = parse_date(value)
                if parsed:
                    return parsed.strftime("%Y-%m-%d")
            return str(value)
        except Exception:
            return str(value)

    elif sf_type == "datetime":
        # Format DateTime as ISO 8601
        try:
            if isinstance(value, str):
                parsed = parse_date(value)
                if parsed:
                    return parsed.isoformat()
            return str(value)
        except Exception:
            return str(value)

    elif sf_type == "currency":
        # Format Currency with symbol and decimals
        try:
            return f"${float(value):,.2f}"
        except (ValueError, TypeError):
            return str(value)

    elif sf_type == "percent":
        # Format Percent with % symbol
        try:
            return f"{float(value):.2f}%"
        except (ValueError, TypeError):
            return str(value)

    elif sf_type in ("double", "int"):
        # Format numeric values
        try:
            if sf_type == "int":
                return str(int(value))
            return f"{float(value):,.2f}"
        except (ValueError, TypeError):
            return str(value)

    # Default: string conversion
    return str(value)


def extract_text_from_record(record: Dict[str, Any], sobject: str, config: Dict[str, Any], schema=None) -> str:
    """
    Extract and combine text fields from a Salesforce record.

    **Feature: zero-config-production, Property 3: Dynamic Field Configuration**
    **Validates: Requirements 3.1, 3.2, 3.6**

    Uses configuration from ConfigurationCache instead of hardcoded POC_OBJECT_FIELDS.
    Phase 2.5: Also adds temporal status and relationship context for cross-object queries.

    Args:
        record: Salesforce record data
        sobject: Object API name
        config: Configuration from ConfigurationCache
        schema: Optional ObjectSchema for type-aware formatting

    Returns:
        Extracted text for embedding
    """
    text_parts = []

    # Get display name field from config (default to Name)
    display_field = config.get("Display_Name_Field__c", "Name")
    if display_field in record and record[display_field]:
        text_parts.append(f"# {record[display_field]}\n")

    # Parse field lists from configuration
    text_fields = _parse_field_list(config.get("Text_Fields__c", ""))
    long_text_fields = _parse_field_list(config.get("Long_Text_Fields__c", ""))

    # Extract text fields with type-aware formatting
    for field in text_fields:
        if field in record and record[field]:
            value = record[field]
            formatted = _format_field_value(value, field, schema)
            if formatted.strip():
                label = format_field_name(field)
                text_parts.append(f"{label}: {formatted}")

    # Extract long text fields
    for field in long_text_fields:
        if field in record and record[field]:
            value = str(record[field])
            if value.strip():
                label = format_field_name(field)
                text_parts.append(f"\n{label}:\n{value}")

    # Phase 2.5: Add temporal status for time-based queries
    add_temporal_context(record, sobject, text_parts)

    # Phase 2.5: Add relationship context for cross-object queries
    add_relationship_context(record, sobject, text_parts, config)

    return "\n".join(text_parts)


def split_text_with_heading_retention(text: str, heading: str) -> List[str]:
    """Split text into chunks of 300-500 tokens, retaining heading in each chunk."""
    chunks = []

    if estimate_tokens(text) <= MAX_CHUNK_TOKENS:
        return [text]

    paragraphs = text.split("\n\n")
    current_chunk = heading + "\n\n" if heading else ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        test_chunk = current_chunk + "\n\n" + para if current_chunk else para

        if estimate_tokens(test_chunk) <= MAX_CHUNK_TOKENS:
            current_chunk = test_chunk
        else:
            if current_chunk and estimate_tokens(current_chunk) >= MIN_CHUNK_TOKENS:
                chunks.append(current_chunk)
                current_chunk = heading + "\n\n" + para if heading else para
            else:
                if estimate_tokens(para) > MAX_CHUNK_TOKENS:
                    sentences = re.split(r"(?<=[.!?])\s+", para)
                    for sentence in sentences:
                        test_chunk = current_chunk + " " + sentence if current_chunk else sentence
                        if estimate_tokens(test_chunk) <= MAX_CHUNK_TOKENS:
                            current_chunk = test_chunk
                        else:
                            if current_chunk:
                                chunks.append(current_chunk)
                            current_chunk = heading + "\n\n" + sentence if heading else sentence
                else:
                    current_chunk = test_chunk

    if current_chunk and estimate_tokens(current_chunk) >= MIN_CHUNK_TOKENS:
        chunks.append(current_chunk)
    elif current_chunk and chunks:
        chunks[-1] = chunks[-1] + "\n\n" + current_chunk
    elif current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [text]


def extract_metadata(record: Dict[str, Any], sobject: str, config: Dict[str, Any], schema=None) -> Dict[str, Any]:
    """
    Extract metadata fields from record for enrichment.

    **Feature: zero-config-production**
    **Validates: Requirements 3.6**

    Uses configuration from ConfigurationCache instead of hardcoded POC_OBJECT_FIELDS.

    Args:
        record: Salesforce record data
        sobject: Object API name
        config: Configuration from ConfigurationCache
        schema: Optional ObjectSchema for type information

    Returns:
        Metadata dictionary
    """
    metadata = {
        "sobject": sobject,
        "recordId": record.get("Id", ""),
        "ownerId": record.get("OwnerId", ""),
        "lastModified": record.get("LastModifiedDate", datetime.utcnow().isoformat()),
        "language": "en",
    }

    # Get display name field from config
    display_field = config.get("Display_Name_Field__c", "Name")
    if display_field in record and record[display_field]:
        metadata["name"] = record[display_field]
    elif "Name" in record and record["Name"]:
        metadata["name"] = record["Name"]
    elif "Subject" in record and record["Subject"]:
        metadata["name"] = record["Subject"]
    elif "Title" in record and record["Title"]:
        metadata["name"] = record["Title"]

    # Extract relationship fields from configuration
    relationship_fields = _parse_field_list(config.get("Relationship_Fields__c", ""))
    parent_ids = []
    for field in relationship_fields:
        if field in record and record[field]:
            parent_ids.append(record[field])
    metadata["parentIds"] = parent_ids

    # Extract standard sharing fields
    if "Territory__c" in record:
        metadata["territory"] = record["Territory__c"]
    if "Business_Unit__c" in record:
        metadata["businessUnit"] = record["Business_Unit__c"]
    if "Region__c" in record:
        metadata["region"] = record["Region__c"]

    # Extract Opportunity-specific fields
    if sobject == "Opportunity":
        if "StageName" in record:
            metadata["stage"] = record["StageName"]
        if "Amount" in record:
            metadata["amount"] = record["Amount"]
        if "CloseDate" in record:
            metadata["closeDate"] = record["CloseDate"]

    # Zero-Config: Extract all text fields for graph attribute filtering
    # Core metadata fields that should never be overwritten by text field extraction
    core_metadata_fields = {"sobject", "recordId", "ownerId", "lastModified", "language", "name", "parentIds"}
    text_fields = _parse_field_list(config.get("Text_Fields__c", ""))
    for field in text_fields:
        if field in record and record[field] is not None:
            # Skip Name as it's already handled above, and skip core metadata fields
            if field != "Name" and field not in core_metadata_fields:
                metadata[field] = record[field]

    # Extract graph node attributes from configuration
    graph_attributes = _parse_field_list(config.get("Graph_Node_Attributes__c", ""))
    for field in graph_attributes:
        if field in record and record[field] is not None:
            # Get field type from schema for proper conversion
            sf_type = _get_field_type_from_schema(field, schema)
            value = record[field]

            if sf_type in ("currency", "double", "percent"):
                try:
                    metadata[field] = float(value)
                except (ValueError, TypeError):
                    pass
            elif sf_type == "int":
                try:
                    metadata[field] = int(value)
                except (ValueError, TypeError):
                    pass
            else:
                metadata[field] = value

    # Zero-Config: Extract ALL filterable fields from schema
    # This is the core of zero-config - schema discovery identifies filterable fields,
    # and we automatically include them in metadata for cross-object filtering
    if schema is not None:
        # Extract filterable fields (picklists) - these are key for cross-object queries
        for field_schema in getattr(schema, 'filterable', []):
            field_name = field_schema.name
            if field_name not in metadata and field_name in record and record[field_name] is not None:
                metadata[field_name] = str(record[field_name])

        # Extract numeric fields for range queries
        for field_schema in getattr(schema, 'numeric', []):
            field_name = field_schema.name
            if field_name not in metadata and field_name in record and record[field_name] is not None:
                value = record[field_name]
                if isinstance(value, (int, float)):
                    metadata[field_name] = value
                else:
                    try:
                        metadata[field_name] = float(value) if '.' in str(value) else int(value)
                    except (ValueError, TypeError):
                        metadata[field_name] = str(value)

        # Extract date fields for temporal queries
        for field_schema in getattr(schema, 'date', []):
            field_name = field_schema.name
            if field_name not in metadata and field_name in record and record[field_name] is not None:
                metadata[field_name] = record[field_name]

    # Extract RecordType.Name - this is a standard Salesforce relationship
    # that determines the record type (e.g., Office, Retail, Industrial for Properties)
    # Data can come in two formats:
    # 1. Nested format from SOQL queries: {"RecordType": {"Name": "Office"}}
    # 2. Flattened format from batch exports: {"RecordType.Name": "Office"}
    record_type_name = None

    # Try nested format first (from CDC/AppFlow)
    record_type_data = record.get("RecordType")
    if record_type_data and isinstance(record_type_data, dict):
        record_type_name = record_type_data.get("Name")

    # Try flattened format (from batch export)
    if not record_type_name:
        record_type_name = record.get("RecordType.Name")

    if record_type_name:
        metadata["RecordType"] = record_type_name
        # Also store with common alias for query matching
        metadata["RecordTypeName"] = record_type_name
        # NOTE: Do NOT add "RecordType.Name" here - the dot causes OpenSearch mapping conflicts
        # The schema decomposer should use RecordType or RecordTypeName instead

    # Phase 2.5: Add temporal status to metadata for filtering
    if sobject == "ascendix__Lease__c":
        exp_date = record.get("ascendix__TermExpirationDate__c")
        if exp_date:
            parsed = parse_date(exp_date)
            if parsed:
                now = datetime.now(timezone.utc)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                days_diff = (parsed - now).days
                if days_diff < 0:
                    metadata["temporalStatus"] = "EXPIRED"
                elif days_diff <= 30:
                    metadata["temporalStatus"] = "EXPIRING_THIS_MONTH"
                elif days_diff <= 90:
                    metadata["temporalStatus"] = "EXPIRING_SOON"
                else:
                    metadata["temporalStatus"] = "ACTIVE"

    elif sobject == "ascendix__Deal__c":
        created_date = record.get("CreatedDate")
        if created_date:
            parsed = parse_date(created_date)
            if parsed:
                now = datetime.now(timezone.utc)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                days_diff = (now - parsed).days
                if days_diff <= 7:
                    metadata["temporalStatus"] = "NEW"
                elif days_diff <= 30:
                    metadata["temporalStatus"] = "RECENT"
                elif days_diff <= 90:
                    metadata["temporalStatus"] = "THIS_QUARTER"
                else:
                    metadata["temporalStatus"] = "OLDER"

        # Add numeric grossFeeAmount for ranking/filtering queries
        gross_fee = record.get("ascendix__GrossFeeAmount__c")
        if gross_fee is not None:
            try:
                metadata["grossFeeAmount"] = float(gross_fee)
            except (ValueError, TypeError):
                pass

    # Phase 2.5: Add relationship context to metadata
    # This enables filtering child objects by parent attributes
    for lookup_field in relationship_fields:
        rel_field_name = lookup_field.replace("__c", "__r")
        related_data = record.get(rel_field_name)

        if related_data and isinstance(related_data, dict):
            label = _get_relationship_label(lookup_field).lower().replace(" ", "")

            # Add all fields from related record to metadata
            for field_key, field_value in related_data.items():
                if field_value is not None and field_key != "attributes":
                    if field_key == "Name":
                        metadata[f"{label}Name"] = field_value
                    else:
                        # Convert field name to camelCase prefix
                        field_suffix = field_key.replace("ascendix__", "").replace("__c", "")
                        metadata_key = f"{label}{field_suffix}"
                        metadata[metadata_key] = field_value
                        # Also store with original field name for zero-config compatibility
                        metadata[field_key] = field_value

    return metadata


def generate_chunk_id(sobject: str, record_id: str, chunk_index: int) -> str:
    """Generate chunk ID in format: {sobject}/{recordId}/chunk-{index}"""
    return f"{sobject}/{record_id}/chunk-{chunk_index}"


def _get_config_cache():
    """
    Get or create ConfigurationCache instance.

    Returns:
        ConfigurationCache instance
    """
    try:
        # Try local import first (config_cache.py in same directory)
        from config_cache import get_config_cache
        return get_config_cache()
    except ImportError:
        try:
            # Fallback: Import config cache from graph_builder
            graph_builder_path = os.path.join(os.path.dirname(__file__), "..", "graph_builder")
            if graph_builder_path not in sys.path:
                sys.path.insert(0, graph_builder_path)
            from config_cache import get_config_cache
            return get_config_cache()
        except Exception as e:
            print(f"Warning: Could not load ConfigurationCache: {e}")
            return None


def chunk_record(record: Dict[str, Any], sobject: str, config: Dict[str, Any], schema=None) -> List[Dict[str, Any]]:
    """
    Chunk a Salesforce record into 300-500 token segments with metadata.

    Args:
        record: Salesforce record data
        sobject: Object API name
        config: Configuration from ConfigurationCache
        schema: Optional ObjectSchema for type-aware formatting

    Returns:
        List of chunk dictionaries
    """
    full_text = extract_text_from_record(record, sobject, config, schema)

    display_field = config.get("Display_Name_Field__c", "Name")
    heading = f"# {record.get(display_field, '')}" if display_field in record else ""

    text_chunks = split_text_with_heading_retention(full_text, heading)
    base_metadata = extract_metadata(record, sobject, config, schema)

    chunks = []
    for idx, text in enumerate(text_chunks):
        chunk = {
            "id": generate_chunk_id(sobject, record.get("Id", ""), idx),
            "text": text,
            "metadata": {
                **base_metadata,
                "chunkIndex": idx,
                "totalChunks": len(text_chunks),
            },
        }
        chunks.append(chunk)

    return chunks


def write_chunks_to_s3(chunks: List[Dict[str, Any]], bucket: str, batch_id: str) -> str:
    """
    Write chunks to S3 as a JSON file to avoid Step Functions payload limits.
    Returns the S3 key where chunks are stored.
    """
    s3_key = f"staging/chunks/{batch_id}.json"

    s3_client.put_object(
        Bucket=bucket, Key=s3_key, Body=json.dumps(chunks).encode("utf-8"), ContentType="application/json"
    )

    print(f"Wrote {len(chunks)} chunks to s3://{bucket}/{s3_key}")
    return s3_key


def lambda_handler(event, context):
    """
    Lambda handler for chunking Salesforce records.

    **Feature: zero-config-production**
    **Validates: Requirements 3.1**

    Fetches configuration from ConfigurationCache for each record.
    Writes chunks to S3 and returns a reference to avoid payload limits.
    """
    try:
        print(f"Received event keys: {list(event.keys())}")

        records = event.get("records", [])

        if not records:
            if "transformedRecords" in event:
                records = event["transformedRecords"]
            elif "Payload" in event:
                if "records" in event["Payload"]:
                    records = event["Payload"]["records"]

        if not records:
            return {"statusCode": 400, "body": json.dumps({"error": "No records provided"})}

        # Get configuration cache and schema cache
        config_cache = _get_config_cache()
        schema_cache = _get_schema_cache()

        all_chunks = []

        for record_wrapper in records:
            sobject = record_wrapper.get("sobject")
            record_data = record_wrapper.get("data")

            if not sobject or not record_data:
                print(f"Skipping invalid record: {record_wrapper}")
                continue

            try:
                # Get configuration for this object type
                # Strategy: Try config_cache first, but check if it has meaningful relationship fields
                # If not, use object-specific FALLBACK_CONFIGS which include relationship traversal
                config = None
                config_source = "unknown"

                if config_cache:
                    try:
                        cached_config = config_cache.get_config(sobject)
                        rel_fields = cached_config.get("Relationship_Fields__c", "")

                        # Check if cached config has meaningful relationship fields
                        # (not None, not empty, and not just "OwnerId" default)
                        has_meaningful_relationships = (
                            rel_fields and
                            rel_fields.strip() and
                            rel_fields.strip() not in ("", "OwnerId", None)
                        )

                        if has_meaningful_relationships:
                            config = cached_config
                            config_source = "config_cache"
                            print(f"[CONFIG] Using cached config for {sobject} with relationships: {rel_fields[:100]}...")
                        else:
                            print(f"[CONFIG] Cached config for {sobject} has no meaningful relationships: '{rel_fields}'")
                    except Exception as e:
                        print(f"[CONFIG] Error getting cached config for {sobject}: {e}")

                # Fall back to object-specific FALLBACK_CONFIGS if no meaningful config from cache
                if config is None and sobject in FALLBACK_CONFIGS:
                    config = FALLBACK_CONFIGS[sobject]
                    config_source = "fallback"
                    print(f"[CONFIG] Using FALLBACK_CONFIGS for {sobject} with relationships: {config.get('Relationship_Fields__c', '')[:100]}...")

                # Last resort: use generic default
                if config is None:
                    config = DEFAULT_CHUNKING_CONFIG.copy()
                    config_source = "default"
                    print(f"[CONFIG] Using DEFAULT_CHUNKING_CONFIG for {sobject}")

                # Check if object is enabled
                if not config.get("Enabled__c", True):
                    print(f"Skipping disabled object type: {sobject}")
                    continue

                # Get schema for type-aware formatting
                schema = None
                if schema_cache:
                    try:
                        schema = schema_cache.get(sobject)
                    except Exception as e:
                        print(f"Warning: Could not get schema for {sobject}: {e}")

                chunks = chunk_record(record_data, sobject, config, schema)
                all_chunks.extend(chunks)
                print(f"Chunked {sobject} record {record_data.get('Id')} into {len(chunks)} chunks")
            except Exception as e:
                print(f"Error chunking record {record_data.get('Id')}: {str(e)}")
                continue

        # Write chunks to S3 to avoid Step Functions payload limits
        if DATA_BUCKET and all_chunks:
            batch_id = str(uuid.uuid4())
            s3_key = write_chunks_to_s3(all_chunks, DATA_BUCKET, batch_id)

            return {
                "chunksS3Bucket": DATA_BUCKET,
                "chunksS3Key": s3_key,
                "recordCount": len(records),
                "chunkCount": len(all_chunks),
            }
        else:
            # Fallback: return chunks directly (may fail for large batches)
            print("WARNING: DATA_BUCKET not set, returning chunks directly")
            return {"chunks": all_chunks, "recordCount": len(records), "chunkCount": len(all_chunks)}

    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        raise e
