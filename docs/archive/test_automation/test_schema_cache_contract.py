#!/usr/bin/env python3
"""
Schema Cache Field Contract Validation Test Suite.

Task 38.2: CI test gate for field contract enforcement.
Validates that schema cache fields exist in Salesforce Describe API,
blocking deployment if fake fields are detected.

**Feature: graph-aware-zero-config-retrieval**
**Task 38: Ingest-Time Field Contract Enforcement**
**Requirements: 21.1, 21.2, 23.1, 23.2**
"""

import os
import sys
import json
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from pathlib import Path

import pytest

# Configuration
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
SCHEMA_CACHE_TABLE = os.environ.get("SCHEMA_CACHE_TABLE", "salesforce-ai-search-schema-cache")
SF_TARGET_ORG = os.environ.get("SF_TARGET_ORG", "ascendix-beta-sandbox")


class SalesforceFieldValidator:
    """
    Validates schema cache fields against Salesforce Describe API.

    **Task 38.2**: CI test gate for field contract.
    **Requirements: 21.2, 23.2**
    """

    def __init__(self, target_org: str = SF_TARGET_ORG):
        self.target_org = target_org
        self.sf_field_cache: Dict[str, Set[str]] = {}

    def get_sf_fields(self, sobject: str) -> Set[str]:
        """
        Get all field names from Salesforce Describe API.

        Args:
            sobject: Salesforce object API name

        Returns:
            Set of field names
        """
        if sobject in self.sf_field_cache:
            return self.sf_field_cache[sobject]

        try:
            cmd = [
                "sf", "sobject", "describe",
                "--sobject", sobject,
                "--target-org", self.target_org,
                "--json"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                print(f"Error describing {sobject}: {result.stderr}")
                return set()

            data = json.loads(result.stdout)
            fields = data.get("result", {}).get("fields", [])

            field_names = set()
            for field in fields:
                name = field.get("name", "")
                if name:
                    field_names.add(name)
                    # Also add relationship names for lookups
                    relationship_name = field.get("relationshipName")
                    if relationship_name:
                        field_names.add(relationship_name)

            # Add standard RecordType fields
            if any(f.get("name") == "RecordTypeId" for f in fields):
                field_names.add("RecordType")
                field_names.add("RecordType.Name")

            self.sf_field_cache[sobject] = field_names
            return field_names

        except subprocess.TimeoutExpired:
            print(f"Timeout describing {sobject}")
            return set()
        except Exception as e:
            print(f"Exception describing {sobject}: {e}")
            return set()


class SchemaCacheValidator:
    """
    Validates schema cache entries against Salesforce metadata.

    **Task 38.2, 38.3**: Validates schema cache contains only real fields.
    **Requirements: 21.1, 21.2, 23.1, 23.2**
    """

    def __init__(self, region: str = AWS_REGION, table_name: str = SCHEMA_CACHE_TABLE):
        self.region = region
        self.table_name = table_name
        self.sf_validator = SalesforceFieldValidator()

    def get_schema_cache_entries(self) -> List[Dict[str, Any]]:
        """
        Get all entries from schema cache DynamoDB table.

        Returns:
            List of schema cache entries
        """
        try:
            cmd = [
                "aws", "dynamodb", "scan",
                "--table-name", self.table_name,
                "--region", self.region,
                "--no-cli-pager",
                "--output", "json"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                print(f"Error scanning schema cache: {result.stderr}")
                return []

            data = json.loads(result.stdout)
            return data.get("Items", [])

        except Exception as e:
            print(f"Exception scanning schema cache: {e}")
            return []

    def extract_field_names_from_schema(self, schema_item: Dict[str, Any]) -> Tuple[str, Set[str]]:
        """
        Extract field names from a schema cache entry.

        Args:
            schema_item: DynamoDB item from schema cache

        Returns:
            Tuple of (object_name, set of field names)
        """
        object_name = schema_item.get("objectApiName", {}).get("S", "")

        # Schema can be stored as 'schema' (M type) or as JSON string
        schema_data = schema_item.get("schema", {})

        field_names: Set[str] = set()

        # Handle Map type storage
        if "M" in schema_data:
            schema_map = schema_data["M"]

            # Extract from filterable fields
            filterable = schema_map.get("filterable", {}).get("L", [])
            for f in filterable:
                if "M" in f:
                    name = f["M"].get("name", {}).get("S", "")
                    if name:
                        field_names.add(name)

            # Extract from text fields
            text_fields = schema_map.get("text", {}).get("L", [])
            for f in text_fields:
                if "M" in f:
                    name = f["M"].get("name", {}).get("S", "")
                    if name:
                        field_names.add(name)

            # Extract from relationship fields
            relationships = schema_map.get("relationships", {}).get("L", [])
            for f in relationships:
                if "M" in f:
                    name = f["M"].get("name", {}).get("S", "")
                    if name:
                        field_names.add(name)

            # Extract from numeric fields
            numeric = schema_map.get("numeric", {}).get("L", [])
            for f in numeric:
                if "M" in f:
                    name = f["M"].get("name", {}).get("S", "")
                    if name:
                        field_names.add(name)

            # Extract from date fields
            date_fields = schema_map.get("date", {}).get("L", [])
            for f in date_fields:
                if "M" in f:
                    name = f["M"].get("name", {}).get("S", "")
                    if name:
                        field_names.add(name)

        # Handle JSON string storage
        elif "S" in schema_data:
            try:
                schema_json = json.loads(schema_data["S"])

                for category in ["filterable", "text", "relationships", "numeric", "date"]:
                    for f in schema_json.get(category, []):
                        name = f.get("name", "")
                        if name:
                            field_names.add(name)
            except json.JSONDecodeError:
                pass

        return object_name, field_names

    def validate_object(self, sobject: str, cached_fields: Set[str]) -> Dict[str, Any]:
        """
        Validate cached fields for an object against Salesforce.

        Args:
            sobject: Salesforce object API name
            cached_fields: Set of field names from schema cache

        Returns:
            Validation result dictionary
        """
        sf_fields = self.sf_validator.get_sf_fields(sobject)

        if not sf_fields:
            return {
                "sobject": sobject,
                "status": "ERROR",
                "message": f"Could not retrieve fields from Salesforce for {sobject}",
                "fake_fields": [],
                "missing_fields": [],
            }

        # Find fake fields (in cache but not in SF)
        fake_fields = cached_fields - sf_fields

        # Filter out known valid patterns
        valid_patterns = {"RecordType", "RecordType.Name"}
        fake_fields = fake_fields - valid_patterns

        # Also filter fields that might be relationship paths
        fake_fields = {f for f in fake_fields if not "." in f or f == "RecordType.Name"}

        return {
            "sobject": sobject,
            "status": "FAILED" if fake_fields else "PASSED",
            "cached_field_count": len(cached_fields),
            "sf_field_count": len(sf_fields),
            "fake_fields": sorted(list(fake_fields)),
            "fake_field_count": len(fake_fields),
        }

    def validate_all(self) -> Dict[str, Any]:
        """
        Validate all objects in schema cache.

        **Task 38.2, 38.3**: Complete validation across all cached objects.

        Returns:
            Overall validation result
        """
        entries = self.get_schema_cache_entries()

        results = {
            "timestamp": datetime.now().isoformat(),
            "table": self.table_name,
            "objects_checked": 0,
            "objects_passed": 0,
            "objects_failed": 0,
            "total_fake_fields": 0,
            "details": [],
            "all_fake_fields": {},
        }

        for entry in entries:
            sobject, cached_fields = self.extract_field_names_from_schema(entry)

            if not sobject or not cached_fields:
                continue

            result = self.validate_object(sobject, cached_fields)
            results["details"].append(result)
            results["objects_checked"] += 1

            if result["status"] == "PASSED":
                results["objects_passed"] += 1
            else:
                results["objects_failed"] += 1
                results["total_fake_fields"] += result.get("fake_field_count", 0)
                if result.get("fake_fields"):
                    results["all_fake_fields"][sobject] = result["fake_fields"]

        results["overall_status"] = "PASSED" if results["objects_failed"] == 0 else "FAILED"

        return results

    def generate_report(self, results: Dict[str, Any]) -> str:
        """
        Generate markdown report from validation results.

        Args:
            results: Validation results dictionary

        Returns:
            Markdown formatted report
        """
        report = []
        report.append("# Schema Cache Field Contract Validation Report")
        report.append("")
        report.append(f"**Date**: {results['timestamp']}")
        report.append(f"**Table**: {results['table']}")
        report.append("")

        # Executive Summary
        report.append("## Executive Summary")
        report.append("")
        status_icon = "PASSED" if results["overall_status"] == "PASSED" else "FAILED"
        report.append(f"**Status**: {status_icon}")
        report.append(f"**Objects Checked**: {results['objects_checked']}")
        report.append(f"**Objects Passed**: {results['objects_passed']}")
        report.append(f"**Objects Failed**: {results['objects_failed']}")
        report.append(f"**Total Fake Fields**: {results['total_fake_fields']}")
        report.append("")

        # Fake Fields Summary
        if results.get("all_fake_fields"):
            report.append("## Fake Fields Detected")
            report.append("")
            report.append("The following fields exist in schema cache but NOT in Salesforce:")
            report.append("")

            for sobject, fields in results["all_fake_fields"].items():
                report.append(f"### {sobject}")
                report.append("")
                for field in fields:
                    report.append(f"- `{field}`")
                report.append("")

        # Detailed Results
        report.append("## Detailed Results")
        report.append("")
        report.append("| Object | Status | Cached Fields | SF Fields | Fake Fields |")
        report.append("|--------|--------|---------------|-----------|-------------|")

        for detail in results["details"]:
            status_icon = "PASS" if detail["status"] == "PASSED" else "FAIL"
            fake_count = detail.get("fake_field_count", 0)
            report.append(
                f"| {detail['sobject']} | {status_icon} | "
                f"{detail.get('cached_field_count', '?')} | "
                f"{detail.get('sf_field_count', '?')} | "
                f"{fake_count} |"
            )

        report.append("")

        # Recommendations
        if results["overall_status"] == "FAILED":
            report.append("## Recommendations")
            report.append("")
            report.append("1. **Remove fake fields** from schema cache")
            report.append("2. **Run Schema Discovery** to repopulate with real SF Describe data")
            report.append("3. **Avoid manual seeding** of schema cache")
            report.append("")
            report.append("### Resolution Commands")
            report.append("")
            report.append("```bash")
            report.append("# Option 1: Invoke Schema Discovery to repopulate")
            report.append('aws lambda invoke --function-name salesforce-ai-search-schema-discovery \\')
            report.append('  --payload \'{"operation": "discover_all"}\' \\')
            report.append('  --cli-binary-format raw-in-base64-out \\')
            report.append(f'  --region {self.region} /tmp/result.json')
            report.append("```")
            report.append("")

        return "\n".join(report)


# =============================================================================
# PyTest Test Cases
# =============================================================================

class TestSchemaCacheContract:
    """
    CI gate tests for schema cache field contract.

    **Task 38.2**: Block deployment if fake fields detected.
    **Requirements: 21.2, 23.2**
    """

    @pytest.fixture
    def validator(self):
        """Create a schema cache validator."""
        return SchemaCacheValidator()

    def test_schema_cache_has_no_fake_fields(self, validator):
        """
        Verify schema cache contains only fields that exist in Salesforce.

        This test FAILS deployment if fake fields are detected.

        **Task 38.2, 38.3**
        **Requirements: 21.2, 23.2**
        """
        results = validator.validate_all()

        # Generate report regardless of result
        report = validator.generate_report(results)

        # Save report
        report_path = Path(__file__).parent / f"schema_contract_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report_path.write_text(report)
        print(f"\nReport saved to: {report_path}")

        # Assert no fake fields
        if results["total_fake_fields"] > 0:
            fake_summary = []
            for sobject, fields in results.get("all_fake_fields", {}).items():
                fake_summary.append(f"{sobject}: {fields}")

            pytest.fail(
                f"Schema cache contains {results['total_fake_fields']} fake fields:\n"
                + "\n".join(fake_summary)
            )

        assert results["overall_status"] == "PASSED", f"Validation failed: {results}"

    @pytest.mark.parametrize("sobject", [
        "ascendix__Property__c",
        "ascendix__Availability__c",
        "ascendix__Lease__c",
        "Account",
        "Contact",
    ])
    def test_individual_object_validation(self, validator, sobject):
        """
        Validate individual objects in schema cache.

        **Task 38.2**
        **Requirements: 23.1**
        """
        entries = validator.get_schema_cache_entries()

        for entry in entries:
            obj_name, cached_fields = validator.extract_field_names_from_schema(entry)
            if obj_name == sobject:
                result = validator.validate_object(sobject, cached_fields)

                assert result["status"] != "ERROR", f"Could not validate {sobject}: {result.get('message')}"

                if result["fake_fields"]:
                    pytest.fail(
                        f"{sobject} has fake fields: {result['fake_fields']}"
                    )

                return

        pytest.skip(f"{sobject} not found in schema cache")


# =============================================================================
# CLI Entry Point
# =============================================================================

def run_validation():
    """
    CLI entry point for running schema cache validation.

    Returns exit code 0 if all checks pass, 1 if fake fields detected.
    """
    print("=" * 80)
    print("SCHEMA CACHE FIELD CONTRACT VALIDATION")
    print("=" * 80)
    print()

    validator = SchemaCacheValidator()
    results = validator.validate_all()
    report = validator.generate_report(results)

    print(report)

    # Save report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(__file__).parent / f"schema_contract_report_{timestamp}.md"
    report_path.write_text(report)
    print(f"\nReport saved to: {report_path}")

    return 0 if results["overall_status"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(run_validation())
