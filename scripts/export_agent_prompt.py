#!/usr/bin/env python3
"""Export the current runtime prompt and tool definitions for stakeholder review."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from lib.system_prompt import build_system_prompt, build_tool_definitions

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "denorm_config.yaml"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "docs" / "agent_prompt_export.md"


@dataclass(frozen=True)
class ExportStats:
    """Summary metrics for an exported prompt snapshot."""

    object_types: list[str]
    tool_names: list[str]
    guideline_count: int


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Load the denormalized config used by the runtime prompt builder."""
    with config_path.open() as fh:
        return yaml.safe_load(fh)


def _extract_object_types(tool_definitions: list[dict]) -> list[str]:
    """Return the dynamic object_type enum from the search_records tool."""
    search_tool = next(
        tool for tool in tool_definitions if tool["toolSpec"]["name"] == "search_records"
    )
    return search_tool["toolSpec"]["inputSchema"]["json"]["properties"]["object_type"]["enum"]


def _count_guidelines(prompt: str) -> int:
    """Count numbered guidelines inside the tagged guidelines section."""
    match = re.search(r"<guidelines>\n(.*?)\n</guidelines>", prompt, re.DOTALL)
    if not match:
        return 0
    return len(re.findall(r"(?m)^\d+\. \*\*", match.group(1)))


def build_export_document(
    config: dict,
    *,
    exported_on: date | None = None,
) -> tuple[str, int, int, int]:
    """Render the stakeholder-facing prompt export document."""
    export_date = exported_on or date.today()
    prompt = build_system_prompt(config)
    tool_definitions = build_tool_definitions(config)
    tool_names = [tool["toolSpec"]["name"] for tool in tool_definitions]
    object_types = _extract_object_types(tool_definitions)
    guideline_count = _count_guidelines(prompt)
    stats = ExportStats(
        object_types=object_types,
        tool_names=tool_names,
        guideline_count=guideline_count,
    )

    document = f"""<!-- Auto-generated — do not edit manually. Run `python3 scripts/export_agent_prompt.py` to regenerate. -->
================================================================================
SYSTEM PROMPT
================================================================================
{prompt.rstrip()}

================================================================================
TOOL DEFINITIONS (Bedrock Converse API format)
================================================================================
{json.dumps(tool_definitions, indent=2)}

================================================================================
Exported: {export_date.isoformat()}
Tool definitions: {len(tool_names)} tools ({", ".join(tool_names)})
Object types: {object_types}
Guidelines: {guideline_count}
================================================================================
"""
    return document, len(object_types), len(tool_names), guideline_count


def generate_export_document(
    config: dict,
    *,
    exported_on: date | None = None,
) -> tuple[str, ExportStats]:
    """Render the stakeholder-facing prompt export document plus summary stats."""
    document, object_count, tool_count, guideline_count = build_export_document(
        config,
        exported_on=exported_on,
    )
    tool_definitions = build_tool_definitions(config)
    object_types = _extract_object_types(tool_definitions)
    tool_names = [tool["toolSpec"]["name"] for tool in tool_definitions]
    stats = ExportStats(
        object_types=object_types,
        tool_names=tool_names,
        guideline_count=guideline_count,
    )
    return document, stats


def write_export_document(
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
) -> ExportStats:
    """Write the prompt export to disk and return its summary stats."""
    config = load_config(config_path)
    document, stats = generate_export_document(config)
    output_path.write_text(document)
    return stats


def main() -> None:
    """CLI entry point."""
    stats = write_export_document()
    print(
        "Exported agent prompt:"
        f" objects={len(stats.object_types)}"
        f" tools={len(stats.tool_names)}"
        f" guidelines={stats.guideline_count}"
    )


if __name__ == "__main__":
    main()
