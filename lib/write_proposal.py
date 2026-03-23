"""Writable Salesforce field metadata and proposal helpers.

This module keeps the write-back contract separate from search aliases so the
query stack can reject denormalized, read-only, and otherwise invalid fields
before a proposal reaches the UI layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class WriteProposalValidationError(ValueError):
    """A proposed write field or payload is not eligible for write-back."""


@dataclass(frozen=True)
class WritableFieldMetadata:
    """Metadata for one Salesforce field that may appear in a proposal."""

    api_name: str
    label: str
    data_type: str
    createable: bool
    updateable: bool
    required_on_create: bool = False
    lookup_target: str | None = None
    proposal_eligible: bool = True


@dataclass(frozen=True)
class WritableObjectMetadata:
    """Writable-field metadata for one Salesforce object."""

    object_type: str
    object_label: str
    fields: dict[str, WritableFieldMetadata]


WRITABLE_OBJECTS: dict[str, WritableObjectMetadata] = {
    "Account": WritableObjectMetadata(
        object_type="Account",
        object_label="Account",
        fields={
            "Name": WritableFieldMetadata(
                api_name="Name",
                label="Name",
                data_type="string",
                createable=True,
                updateable=True,
                required_on_create=True,
            ),
            "Phone": WritableFieldMetadata(
                api_name="Phone",
                label="Phone",
                data_type="phone",
                createable=True,
                updateable=True,
            ),
            "Website": WritableFieldMetadata(
                api_name="Website",
                label="Website",
                data_type="url",
                createable=True,
                updateable=True,
            ),
            "Industry": WritableFieldMetadata(
                api_name="Industry",
                label="Industry",
                data_type="picklist",
                createable=True,
                updateable=True,
            ),
            "Type": WritableFieldMetadata(
                api_name="Type",
                label="Type",
                data_type="picklist",
                createable=True,
                updateable=True,
            ),
            "BillingCity": WritableFieldMetadata(
                api_name="BillingCity",
                label="Billing City",
                data_type="string",
                createable=True,
                updateable=True,
            ),
            "BillingState": WritableFieldMetadata(
                api_name="BillingState",
                label="Billing State",
                data_type="string",
                createable=True,
                updateable=True,
            ),
            "BillingPostalCode": WritableFieldMetadata(
                api_name="BillingPostalCode",
                label="Billing Postal Code",
                data_type="string",
                createable=True,
                updateable=True,
            ),
            "AnnualRevenue": WritableFieldMetadata(
                api_name="AnnualRevenue",
                label="Annual Revenue",
                data_type="currency",
                createable=True,
                updateable=True,
            ),
            "NumberOfEmployees": WritableFieldMetadata(
                api_name="NumberOfEmployees",
                label="Number Of Employees",
                data_type="number",
                createable=True,
                updateable=True,
            ),
        },
    ),
    "Contact": WritableObjectMetadata(
        object_type="Contact",
        object_label="Contact",
        fields={
            "FirstName": WritableFieldMetadata(
                api_name="FirstName",
                label="First Name",
                data_type="string",
                createable=True,
                updateable=True,
            ),
            "LastName": WritableFieldMetadata(
                api_name="LastName",
                label="Last Name",
                data_type="string",
                createable=True,
                updateable=True,
                required_on_create=True,
            ),
            "Email": WritableFieldMetadata(
                api_name="Email",
                label="Email",
                data_type="email",
                createable=True,
                updateable=True,
            ),
            "Phone": WritableFieldMetadata(
                api_name="Phone",
                label="Phone",
                data_type="phone",
                createable=True,
                updateable=True,
            ),
            "MobilePhone": WritableFieldMetadata(
                api_name="MobilePhone",
                label="Mobile Phone",
                data_type="phone",
                createable=True,
                updateable=True,
            ),
            "Title": WritableFieldMetadata(
                api_name="Title",
                label="Title",
                data_type="string",
                createable=True,
                updateable=True,
            ),
            "Department": WritableFieldMetadata(
                api_name="Department",
                label="Department",
                data_type="string",
                createable=True,
                updateable=True,
            ),
            "AccountId": WritableFieldMetadata(
                api_name="AccountId",
                label="Account",
                data_type="reference",
                createable=True,
                updateable=True,
                lookup_target="Account",
            ),
            "MailingCity": WritableFieldMetadata(
                api_name="MailingCity",
                label="Mailing City",
                data_type="string",
                createable=True,
                updateable=True,
            ),
            "MailingState": WritableFieldMetadata(
                api_name="MailingState",
                label="Mailing State",
                data_type="string",
                createable=True,
                updateable=True,
            ),
            "MailingPostalCode": WritableFieldMetadata(
                api_name="MailingPostalCode",
                label="Mailing Postal Code",
                data_type="string",
                createable=True,
                updateable=True,
            ),
        },
    ),
    "Task": WritableObjectMetadata(
        object_type="Task",
        object_label="Task",
        fields={
            "Subject": WritableFieldMetadata(
                api_name="Subject",
                label="Subject",
                data_type="string",
                createable=True,
                updateable=True,
                required_on_create=True,
            ),
            "Status": WritableFieldMetadata(
                api_name="Status",
                label="Status",
                data_type="picklist",
                createable=True,
                updateable=True,
            ),
            "Priority": WritableFieldMetadata(
                api_name="Priority",
                label="Priority",
                data_type="picklist",
                createable=True,
                updateable=True,
            ),
            "ActivityDate": WritableFieldMetadata(
                api_name="ActivityDate",
                label="Activity Date",
                data_type="date",
                createable=True,
                updateable=True,
            ),
            "Description": WritableFieldMetadata(
                api_name="Description",
                label="Description",
                data_type="textarea",
                createable=True,
                updateable=True,
            ),
            "Type": WritableFieldMetadata(
                api_name="Type",
                label="Type",
                data_type="picklist",
                createable=True,
                updateable=True,
            ),
        },
    ),
}


def get_writable_object_types() -> list[str]:
    """Return the supported write-back object types."""
    return sorted(WRITABLE_OBJECTS.keys())


def get_writable_object_metadata(object_type: str) -> WritableObjectMetadata | None:
    """Look up writable metadata for *object_type* case-insensitively."""
    if not isinstance(object_type, str):
        return None

    lowered = object_type.lower()
    for key, metadata in WRITABLE_OBJECTS.items():
        if key.lower() == lowered:
            return metadata
    return None


def _resolve_field_metadata(
    object_metadata: WritableObjectMetadata,
    api_name: str,
) -> WritableFieldMetadata | None:
    for field_api_name, field_metadata in object_metadata.fields.items():
        if field_api_name == api_name or field_api_name.lower() == api_name.lower():
            return field_metadata
    return None


def _default_summary(
    object_type: str,
    record_name: str | None,
    field_names: list[str],
) -> str:
    subject = record_name or object_type
    if not field_names:
        return f"Edit {subject}"
    if len(field_names) == 1:
        return f"Edit {subject}: {field_names[0]}"
    preview = ", ".join(field_names[:3])
    if len(field_names) > 3:
        preview += ", ..."
    return f"Edit {subject}: {preview}"


def build_writable_field_reference() -> str:
    """Render a compact field reference for prompt guidance."""
    sections: list[str] = []
    for object_type in get_writable_object_types():
        metadata = WRITABLE_OBJECTS[object_type]
        field_labels: list[str] = []
        for field in metadata.fields.values():
            if not field.proposal_eligible:
                continue
            label = field.api_name
            if field.lookup_target:
                label += f" (lookup to {field.lookup_target})"
            if field.required_on_create:
                label += " [required on create]"
            field_labels.append(label)
        sections.append(f"  - {metadata.object_type}: {', '.join(field_labels)}")
    return "\n".join(sections)


def build_writable_proposal_tool_definition() -> dict[str, Any]:
    """Build the Bedrock Converse tool definition for ``propose_edit``."""
    object_enum = get_writable_object_types()
    field_reference = build_writable_field_reference()

    return {
        "toolSpec": {
            "name": "propose_edit",
            "description": (
                "Create a typed edit proposal for an existing Salesforce record. "
                "Use only when the target record is already identified. Keep the "
                "proposal minimal and use only writable fields from the contract.\n\n"
                f"Object types: {', '.join(object_enum)}.\n\n"
                "Writable fields:\n"
                f"{field_reference}\n\n"
                "Never propose Id, CreatedDate, formula, rollup, system, or "
                "denormalized/search-only fields."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "object_type": {
                            "type": "string",
                            "enum": object_enum,
                            "description": "The Salesforce object type to edit.",
                        },
                        "record_id": {
                            "type": "string",
                            "description": "The Salesforce record Id to update.",
                        },
                        "record_name": {
                            "type": "string",
                            "description": "Human-readable record name for context.",
                        },
                        "summary": {
                            "type": "string",
                            "description": "Short user-facing summary of the proposed edit.",
                        },
                        "fields": {
                            "type": "array",
                            "minItems": 1,
                            "description": (
                                "Proposed field changes using real Salesforce API "
                                "names. Each item needs apiName and proposedValue."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "apiName": {
                                        "type": "string",
                                        "description": "Salesforce field API name.",
                                    },
                                    "label": {
                                        "type": "string",
                                        "description": "Optional human-readable field label.",
                                    },
                                    "proposedValue": {
                                        "description": "The new value to apply to the field.",
                                    },
                                    "proposedLabel": {
                                        "type": "string",
                                        "description": (
                                            "Optional display label for lookup proposals "
                                            "when the human-readable target name is known."
                                        ),
                                    },
                                },
                                "required": ["apiName", "proposedValue"],
                            },
                        },
                    },
                    "required": ["object_type", "record_id", "fields"],
                }
            },
        }
    }


def build_writable_proposal_guidance() -> str:
    """Return concise prompt guidance for proposal generation."""
    return (
        "Use propose_edit only when the target record is already identified. "
        "Confirm the target record in the response, prefer minimal explicit "
        "field changes, and do not propose any field outside the writable "
        "contract."
    )


def normalize_propose_edit_input(params: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a ``propose_edit`` tool input."""
    if not isinstance(params, dict):
        raise WriteProposalValidationError("propose_edit parameters must be an object")

    raw_type = params.get("object_type")
    object_metadata = get_writable_object_metadata(raw_type) if isinstance(raw_type, str) else None
    if object_metadata is None:
        valid = get_writable_object_types()
        raise WriteProposalValidationError(
            f"Unknown or unsupported object_type '{raw_type}'. Valid writable types: {valid}"
        )

    record_id = params.get("record_id")
    if not isinstance(record_id, str) or not record_id.strip():
        raise WriteProposalValidationError("'record_id' is required for propose_edit")
    record_id = record_id.strip()

    record_name = params.get("record_name")
    if isinstance(record_name, str):
        record_name = record_name.strip() or None
    else:
        record_name = None

    raw_summary = params.get("summary")
    summary = raw_summary.strip() if isinstance(raw_summary, str) else ""

    raw_fields = params.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise WriteProposalValidationError("'fields' must be a non-empty list for propose_edit")

    normalized_fields: list[dict[str, Any]] = []
    field_names: list[str] = []

    for raw_field in raw_fields:
        if not isinstance(raw_field, dict):
            raise WriteProposalValidationError("Each proposed field must be an object")

        api_name = raw_field.get("apiName") or raw_field.get("fieldApiName")
        if not isinstance(api_name, str) or not api_name.strip():
            raise WriteProposalValidationError("Each proposed field must include 'apiName'")
        api_name = api_name.strip()

        field_metadata = _resolve_field_metadata(object_metadata, api_name)
        if field_metadata is None or not field_metadata.proposal_eligible:
            valid_fields = sorted(
                field.api_name
                for field in object_metadata.fields.values()
                if field.proposal_eligible
            )
            raise WriteProposalValidationError(
                f"Field '{api_name}' is not proposal-eligible for object_type "
                f"'{object_metadata.object_type}'. Valid writable fields: {valid_fields}"
            )

        has_explicit_value = "proposedValue" in raw_field or "value" in raw_field
        if not has_explicit_value:
            raise WriteProposalValidationError(
                f"Field '{api_name}' must include 'proposedValue'"
            )

        proposed_value = raw_field.get("proposedValue", raw_field.get("value"))
        normalized_field: dict[str, Any] = {
            "apiName": field_metadata.api_name,
            "label": raw_field.get("label") if isinstance(raw_field.get("label"), str) and raw_field.get("label") else field_metadata.label,
            "proposedValue": proposed_value,
        }
        proposed_label = raw_field.get("proposedLabel")
        if isinstance(proposed_label, str) and proposed_label.strip():
            normalized_field["proposedLabel"] = proposed_label.strip()
        if field_metadata.lookup_target:
            normalized_field["lookupTarget"] = field_metadata.lookup_target
        normalized_fields.append(normalized_field)
        field_names.append(field_metadata.api_name)

    if not summary:
        summary = _default_summary(object_metadata.object_type, record_name, field_names)

    proposal: dict[str, Any] = {
        "kind": "edit",
        "objectType": object_metadata.object_type,
        "recordId": record_id,
        "summary": summary,
        "fields": normalized_fields,
    }
    if record_name:
        proposal["recordName"] = record_name

    return proposal
