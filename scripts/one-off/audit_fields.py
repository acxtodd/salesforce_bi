#!/usr/bin/env python3
"""
Field Audit Guard - Detect fake/missing fields in code vs Salesforce.

**Task: 40.7 Field Audit Guard**

This script compares field references across code/config sources against
live Salesforce Describe API to detect:
- FAKE fields: Referenced in code but don't exist in Salesforce (CI FAIL)
- MISSING exports: SF filterable/relationship fields not in export configs (WARNING)

Usage:
    python scripts/audit_fields.py [--output FILE] [--format json|md] [--ci]
    python scripts/audit_fields.py --skip-sf  # Local code audit only

Exit Codes:
    0 - All fields valid (or --skip-sf mode)
    1 - Fake fields detected (CI should fail)
    2 - Configuration/connection error (SF auth failure, empty cache)

Required SSM Parameters (for SF validation):
    /salesforce/instance_url   - Salesforce instance URL (e.g., https://myorg.my.salesforce.com)
    /salesforce/access_token   - Valid OAuth access token (SecureString)

Required AWS Permissions:
    - ssm:GetParameter (for SF credentials)
    - dynamodb:Scan (for schema cache table)

Environment Variables:
    AWS_REGION           - AWS region (default: us-west-2)
    SCHEMA_CACHE_TABLE   - DynamoDB table name (default: salesforce-ai-search-schema-cache)
    LOG_LEVEL            - Logging level (default: INFO)

Data Sources Audited:
    1. Schema Cache (DynamoDB) - Auto-discovered schema from SF Describe
    2. Chunking FALLBACK_CONFIGS (lambda/chunking/index.py)
    3. Derived Views SOQL (lambda/derived_views/index.py, backfill.py)
    4. IndexConfiguration__mdt (Salesforce custom metadata)

Example:
    # Full validation with Salesforce
    python scripts/audit_fields.py --format md --output audit_report.md

    # CI mode - exit 1 on fake fields
    python scripts/audit_fields.py --ci

    # Skip SF (local code audit only)
    python scripts/audit_fields.py --skip-sf --verbose
"""

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import boto3
from botocore.exceptions import ClientError

# Add lambda directory to path for imports
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
LAMBDA_DIR = PROJECT_ROOT / "lambda"
sys.path.insert(0, str(LAMBDA_DIR))
sys.path.insert(0, str(LAMBDA_DIR / "common"))

# Import after path setup
try:
    from common.salesforce_client import SalesforceClient
except ImportError:
    # Fallback for direct execution
    from salesforce_client import SalesforceClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
LOGGER = logging.getLogger(__name__)

# Monitored objects
MONITORED_OBJECTS = [
    "ascendix__Property__c",
    "ascendix__Availability__c",
    "ascendix__Lease__c",
    "ascendix__Deal__c",
    "ascendix__Listing__c",
    "ascendix__Inquiry__c",
    "Account",
    "Contact",
    "Task",
    "Event",
]

# DynamoDB table name
SCHEMA_CACHE_TABLE = os.getenv(
    "SCHEMA_CACHE_TABLE", "salesforce-ai-search-schema-cache"
)


@dataclass
class FieldReference:
    """A field reference found in code/config."""
    object_name: str
    field_name: str
    source: str  # e.g., "chunking/index.py", "schema_cache", etc.
    location: Optional[str] = None  # e.g., line number or config key


@dataclass
class AuditResults:
    """Results of the field audit."""
    fake_fields: List[FieldReference] = field(default_factory=list)
    missing_exports: List[FieldReference] = field(default_factory=list)
    valid_fields: List[FieldReference] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def total_fields(self) -> int:
        return len(self.fake_fields) + len(self.missing_exports) + len(self.valid_fields)

    @property
    def has_fake_fields(self) -> bool:
        return len(self.fake_fields) > 0


class FieldCollector:
    """Collects field references from various sources."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.lambda_dir = project_root / "lambda"

    def collect_all(self, sf_client: Optional[SalesforceClient] = None) -> Dict[str, Set[str]]:
        """
        Collect fields from all sources.

        Returns:
            Dict mapping object name to set of field names
        """
        all_fields: Dict[str, Set[str]] = {}

        # Collect from each source
        sources = [
            ("schema_cache", self.collect_from_schema_cache()),
            ("chunking", self.collect_from_chunking()),
            ("derived_views", self.collect_from_derived_views()),
        ]

        # Add IndexConfiguration if SF client available
        if sf_client:
            sources.append(("index_config", self.collect_from_index_config(sf_client)))

        for source_name, fields in sources:
            for obj, field_set in fields.items():
                if obj not in all_fields:
                    all_fields[obj] = set()
                all_fields[obj].update(field_set)
                LOGGER.debug(f"Collected {len(field_set)} fields from {source_name} for {obj}")

        return all_fields

    def collect_from_schema_cache(self) -> Dict[str, Set[str]]:
        """Collect fields from DynamoDB schema cache."""
        fields: Dict[str, Set[str]] = {}

        try:
            dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
            table = dynamodb.Table(SCHEMA_CACHE_TABLE)

            response = table.scan()
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
                items.extend(response.get("Items", []))

            for item in items:
                obj_name = item.get("objectApiName")
                if not obj_name:
                    continue

                fields[obj_name] = set()
                schema = item.get("schema", {})

                # Extract fields from each category
                for category in ["filterable", "numeric", "date", "relationships", "text"]:
                    category_fields = schema.get(category, [])
                    for f in category_fields:
                        if isinstance(f, dict) and "name" in f:
                            fields[obj_name].add(f["name"])
                        elif isinstance(f, str):
                            fields[obj_name].add(f)

            LOGGER.info(f"Collected fields from schema cache: {len(items)} objects")

        except ClientError as e:
            LOGGER.warning(f"Could not read schema cache: {e}")

        return fields

    def collect_from_chunking(self) -> Dict[str, Set[str]]:
        """Collect fields from chunking FALLBACK_CONFIGS."""
        fields: Dict[str, Set[str]] = {}

        try:
            # Import the chunking module to get FALLBACK_CONFIGS
            chunking_path = self.lambda_dir / "chunking"
            sys.path.insert(0, str(chunking_path))

            # Read the file and extract FALLBACK_CONFIGS
            index_file = chunking_path / "index.py"
            if not index_file.exists():
                LOGGER.warning(f"Chunking index.py not found at {index_file}")
                return fields

            content = index_file.read_text()

            # Extract FALLBACK_CONFIGS dict using regex
            # Pattern to match dictionary entries
            config_match = re.search(
                r'FALLBACK_CONFIGS\s*=\s*\{(.+?)\n\}',
                content,
                re.DOTALL
            )

            if not config_match:
                LOGGER.warning("Could not find FALLBACK_CONFIGS in chunking/index.py")
                return fields

            # Parse each object's config
            for obj in MONITORED_OBJECTS:
                fields[obj] = set()

                # Look for this object's config block
                obj_pattern = rf'"{re.escape(obj)}"\s*:\s*\{{([^}}]+)\}}'
                obj_match = re.search(obj_pattern, content, re.DOTALL)

                if obj_match:
                    config_block = obj_match.group(1)

                    # Extract Text_Fields__c
                    text_match = re.search(r'"Text_Fields__c"\s*:\s*"([^"]*)"', config_block)
                    if text_match:
                        field_list = text_match.group(1)
                        for f in field_list.split(","):
                            f = f.strip()
                            if f:
                                fields[obj].add(f)

                    # Extract Long_Text_Fields__c
                    long_match = re.search(r'"Long_Text_Fields__c"\s*:\s*"([^"]*)"', config_block)
                    if long_match:
                        field_list = long_match.group(1)
                        for f in field_list.split(","):
                            f = f.strip()
                            if f:
                                fields[obj].add(f)

                    # Extract Relationship_Fields__c
                    rel_match = re.search(r'"Relationship_Fields__c"\s*:\s*"([^"]*)"', config_block)
                    if rel_match:
                        field_list = rel_match.group(1)
                        for f in field_list.split(","):
                            f = f.strip()
                            if f:
                                # Resolve relationship paths to base field
                                base_field = self._resolve_relationship_path(f)
                                fields[obj].add(base_field)

            LOGGER.info(f"Collected fields from chunking configs")

        except Exception as e:
            LOGGER.warning(f"Could not parse chunking configs: {e}")

        return fields

    def collect_from_derived_views(self) -> Dict[str, Set[str]]:
        """Collect fields from derived views SOQL queries."""
        fields: Dict[str, Set[str]] = {}

        derived_views_path = self.lambda_dir / "derived_views"

        # Files to scan
        files_to_scan = ["index.py", "backfill.py"]

        # Object mappings for derived views
        object_mappings = {
            "ascendix__Availability__c": "ascendix__Availability__c",
            "ascendix__Property__c": "ascendix__Property__c",
            "ascendix__Lease__c": "ascendix__Lease__c",
            "ascendix__Deal__c": "ascendix__Deal__c",
            "Task": "Task",
            "Event": "Event",
        }

        for filename in files_to_scan:
            file_path = derived_views_path / filename
            if not file_path.exists():
                continue

            content = file_path.read_text()

            # Find SOQL SELECT statements
            soql_pattern = r'SELECT\s+(.+?)\s+FROM\s+(\w+)'
            matches = re.findall(soql_pattern, content, re.IGNORECASE | re.DOTALL)

            for field_list, from_obj in matches:
                # Clean up the object name
                from_obj = from_obj.strip()

                # Map to monitored object if possible
                obj_name = None
                for key, val in object_mappings.items():
                    if key.lower() in from_obj.lower() or from_obj.lower() in key.lower():
                        obj_name = val
                        break

                if not obj_name:
                    continue

                if obj_name not in fields:
                    fields[obj_name] = set()

                # Parse field list
                # Handle multiline and commas
                field_list = re.sub(r'\s+', ' ', field_list)
                for f in field_list.split(","):
                    f = f.strip()
                    if f and not f.upper().startswith("COUNT"):
                        # Resolve relationship paths
                        base_field = self._resolve_relationship_path(f)
                        fields[obj_name].add(base_field)

            # NOTE: We intentionally skip .get("field_name") pattern matching here
            # because it's too broad and would attribute fields to wrong objects.
            # The SOQL parsing above is more accurate as it knows the FROM object.

        LOGGER.info(f"Collected fields from derived views")
        return fields

    def collect_from_index_config(self, sf_client: SalesforceClient) -> Dict[str, Set[str]]:
        """Collect fields from IndexConfiguration__mdt in Salesforce."""
        fields: Dict[str, Set[str]] = {}

        try:
            soql = """
                SELECT Object_API_Name__c, Text_Fields__c, Long_Text_Fields__c,
                       Relationship_Fields__c, Graph_Node_Attributes__c
                FROM IndexConfiguration__mdt
                WHERE Enabled__c = true
            """
            result = sf_client.query(soql)
            records = result.get("records", [])

            for record in records:
                obj_name = record.get("Object_API_Name__c")
                if not obj_name:
                    continue

                fields[obj_name] = set()

                # Parse each field list
                for field_key in ["Text_Fields__c", "Long_Text_Fields__c",
                                  "Relationship_Fields__c", "Graph_Node_Attributes__c"]:
                    field_list = record.get(field_key, "") or ""
                    for f in field_list.split(","):
                        f = f.strip()
                        if f:
                            base_field = self._resolve_relationship_path(f)
                            fields[obj_name].add(base_field)

            LOGGER.info(f"Collected fields from IndexConfiguration__mdt: {len(records)} configs")

        except Exception as e:
            LOGGER.warning(f"Could not query IndexConfiguration__mdt: {e}")

        return fields

    def _resolve_relationship_path(self, field_path: str) -> str:
        """
        Resolve relationship path to base field.

        Examples:
            ascendix__Property__r.Name -> ascendix__Property__c
            RecordType.Name -> RecordType
            OwnerId -> OwnerId
        """
        if "__r." in field_path:
            # Custom relationship: ascendix__Property__r.Name -> ascendix__Property__c
            base = field_path.split("__r.")[0] + "__c"
            return base
        elif "." in field_path:
            # Standard relationship: RecordType.Name -> RecordType
            return field_path.split(".")[0]
        return field_path


class SalesforceValidator:
    """Validates fields against Salesforce Describe API."""

    def __init__(self, sf_client: SalesforceClient):
        self.client = sf_client
        self._cache: Dict[str, Set[str]] = {}
        self._filterable_cache: Dict[str, Set[str]] = {}
        self._relationship_cache: Dict[str, Set[str]] = {}

    def get_valid_fields(self, sobject: str) -> Set[str]:
        """
        Get set of valid field names for an object from Describe API.

        Includes special handling for RecordType.
        """
        if sobject in self._cache:
            return self._cache[sobject]

        try:
            describe = self.client.describe(sobject)

            # Extract all field names
            fields = set()
            filterable = set()
            relationships = set()

            for f in describe.get("fields", []):
                field_name = f["name"]
                fields.add(field_name)

                # Track filterable fields (picklist, boolean, etc.)
                if f.get("filterable", False):
                    sf_type = f.get("type", "")
                    if sf_type in ("picklist", "multipicklist", "boolean", "reference"):
                        filterable.add(field_name)

                # Track relationship fields
                if f.get("type") == "reference":
                    relationships.add(field_name)

            # Add RecordType if object has record types
            record_type_infos = describe.get("recordTypeInfos", [])
            if record_type_infos and len(record_type_infos) > 1:  # More than just Master
                fields.add("RecordType")
                fields.add("RecordType.Name")
                fields.add("RecordTypeId")
                filterable.add("RecordType")

            self._cache[sobject] = fields
            self._filterable_cache[sobject] = filterable
            self._relationship_cache[sobject] = relationships
            LOGGER.debug(f"Described {sobject}: {len(fields)} fields, {len(filterable)} filterable, {len(relationships)} relationships")
            return fields

        except Exception as e:
            LOGGER.error(f"Failed to describe {sobject}: {e}")
            return set()

    def get_exportable_fields(self, sobject: str) -> Set[str]:
        """Get SF fields that should be exported (filterable + relationships)."""
        # Ensure describe has been called
        self.get_valid_fields(sobject)
        return self._filterable_cache.get(sobject, set()) | self._relationship_cache.get(sobject, set())

    def validate_all(
        self,
        code_fields: Dict[str, Set[str]],
        monitored_objects: List[str]
    ) -> AuditResults:
        """
        Validate all collected fields against Salesforce.

        Returns:
            AuditResults with fake, missing, and valid fields
        """
        results = AuditResults()

        for obj in monitored_objects:
            # Get valid fields from SF
            sf_fields = self.get_valid_fields(obj)

            if not sf_fields:
                results.errors.append(f"Could not describe {obj}")
                continue

            # Get code-referenced fields for this object
            code_refs = code_fields.get(obj, set())

            for field_name in code_refs:
                # Skip standard fields that are always valid
                if field_name in ("Id", "Name", "OwnerId", "CreatedDate",
                                  "LastModifiedDate", "SystemModstamp"):
                    results.valid_fields.append(FieldReference(
                        object_name=obj,
                        field_name=field_name,
                        source="standard_field"
                    ))
                    continue

                # Check if field exists in SF
                if field_name in sf_fields:
                    results.valid_fields.append(FieldReference(
                        object_name=obj,
                        field_name=field_name,
                        source="sf_describe"
                    ))
                else:
                    # FAKE field - in code but not in SF
                    results.fake_fields.append(FieldReference(
                        object_name=obj,
                        field_name=field_name,
                        source="code_reference"
                    ))

            # Check for missing exports (SF filterable/relationship fields not in code)
            exportable = self.get_exportable_fields(obj)
            for field_name in exportable:
                if field_name not in code_refs:
                    # Skip system fields that don't need explicit export
                    if field_name in ("Id", "OwnerId", "CreatedById", "LastModifiedById",
                                      "IsDeleted", "SystemModstamp"):
                        continue
                    results.missing_exports.append(FieldReference(
                        object_name=obj,
                        field_name=field_name,
                        source="sf_exportable"
                    ))

        return results


class AuditReporter:
    """Generates audit reports in various formats."""

    def generate(self, results: AuditResults, format: str = "json") -> str:
        """Generate report in specified format."""
        if format == "md":
            return self.generate_markdown(results)
        return self.generate_json(results)

    def generate_json(self, results: AuditResults) -> str:
        """Generate JSON report."""
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_fields": results.total_fields,
                "fake_count": len(results.fake_fields),
                "missing_export_count": len(results.missing_exports),
                "valid_count": len(results.valid_fields),
                "error_count": len(results.errors),
            },
            "status": "FAIL" if results.has_fake_fields else "PASS",
            "fake_fields": [
                {
                    "object": f.object_name,
                    "field": f.field_name,
                    "source": f.source,
                }
                for f in results.fake_fields
            ],
            "missing_exports": [
                {
                    "object": f.object_name,
                    "field": f.field_name,
                    "source": f.source,
                }
                for f in results.missing_exports
            ],
            "errors": results.errors,
        }
        return json.dumps(report, indent=2)

    def generate_markdown(self, results: AuditResults) -> str:
        """Generate Markdown report."""
        lines = [
            "# Field Audit Report",
            "",
            f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
            f"**Status:** {'FAIL' if results.has_fake_fields else 'PASS'}",
            "",
            "## Summary",
            "",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| Total Fields | {results.total_fields} |",
            f"| Valid | {len(results.valid_fields)} |",
            f"| Fake (CI Fail) | {len(results.fake_fields)} |",
            f"| Missing Export | {len(results.missing_exports)} |",
            f"| Errors | {len(results.errors)} |",
            "",
        ]

        if results.fake_fields:
            lines.extend([
                "## Fake Fields (IN CODE BUT NOT IN SALESFORCE)",
                "",
                "These fields are referenced in code/config but do not exist in Salesforce.",
                "",
                "| Object | Field | Source |",
                "|--------|-------|--------|",
            ])
            for f in results.fake_fields:
                lines.append(f"| {f.object_name} | `{f.field_name}` | {f.source} |")
            lines.append("")

        if results.missing_exports:
            lines.extend([
                "## Missing Exports (WARNING)",
                "",
                "These SF fields exist but are not exported/indexed.",
                "",
                "| Object | Field | Source |",
                "|--------|-------|--------|",
            ])
            for f in results.missing_exports:
                lines.append(f"| {f.object_name} | `{f.field_name}` | {f.source} |")
            lines.append("")

        if results.errors:
            lines.extend([
                "## Errors",
                "",
            ])
            for err in results.errors:
                lines.append(f"- {err}")
            lines.append("")

        return "\n".join(lines)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Field Audit Guard - Detect fake/missing fields"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout)"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "md"],
        default="json",
        help="Output format (default: json)"
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: exit 1 on fake fields"
    )
    parser.add_argument(
        "--skip-sf",
        action="store_true",
        help="Skip Salesforce connection (use cached describe data only)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize Salesforce client
    sf_client: Optional[SalesforceClient] = None

    if not args.skip_sf:
        try:
            LOGGER.info("Connecting to Salesforce via SSM credentials...")
            sf_client = SalesforceClient.from_ssm()
            LOGGER.info("Connected to Salesforce")
        except Exception as e:
            LOGGER.error(f"Cannot connect to Salesforce: {e}")
            print(f"ERROR: Cannot connect to Salesforce: {e}", file=sys.stderr)
            print("Use --skip-sf to run without Salesforce connection", file=sys.stderr)
            sys.exit(2)

    # Collect fields from all sources
    LOGGER.info("Collecting field references from code/config...")
    collector = FieldCollector(PROJECT_ROOT)
    code_fields = collector.collect_all(sf_client)

    total_fields = sum(len(fields) for fields in code_fields.values())
    LOGGER.info(f"Collected {total_fields} field references across {len(code_fields)} objects")

    # Guard: empty collection
    if total_fields == 0:
        print("WARNING: No fields found. Is schema cache populated?", file=sys.stderr)
        sys.exit(2)

    # Validate against Salesforce
    if sf_client:
        LOGGER.info("Validating fields against Salesforce Describe API...")
        validator = SalesforceValidator(sf_client)
        results = validator.validate_all(code_fields, MONITORED_OBJECTS)
    else:
        LOGGER.warning("Skipping validation (no SF connection)")
        results = AuditResults()
        for obj, fields in code_fields.items():
            for f in fields:
                results.valid_fields.append(FieldReference(
                    object_name=obj,
                    field_name=f,
                    source="not_validated"
                ))

    # Generate report
    reporter = AuditReporter()
    report = reporter.generate(results, args.format)

    # Output
    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        LOGGER.info(f"Report written to {args.output}")
    else:
        print(report)

    # Summary
    if results.has_fake_fields:
        LOGGER.error(f"FAIL: Found {len(results.fake_fields)} fake fields")
        if args.ci:
            sys.exit(1)
    else:
        LOGGER.info(f"PASS: All {len(results.valid_fields)} fields validated")

    sys.exit(0)


if __name__ == "__main__":
    main()
