"""Tests for poll sync Lambda (Task 4.8.1).

All tests use mocks — no network or API keys required.
"""

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Add project root + lambda to path.
# Lambda dir must come FIRST so `poll_sync.index` resolves to
# lambda/poll_sync/index.py, not scripts/poll_sync.py.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))
sys.path.insert(0, str(PROJECT_ROOT))

from poll_sync.index import (  # noqa: E402
    build_poll_where,
    format_watermark,
    parse_watermark,
    _sync_object,
)


# ===================================================================
# Helpers
# ===================================================================

SAMPLE_CONFIG = {
    "ascendix__Deal__c": {
        "embed_fields": ["Name", "ascendix__Description__c"],
        "metadata_fields": ["ascendix__Stage__c"],
        "parents": {},
    }
}

SAMPLE_REL_MAP: dict = {}


def _make_sf_client_mock(query_results: list[dict] | None = None) -> MagicMock:
    """Create a mock SalesforceClient."""
    mock = MagicMock()
    if query_results is None:
        mock.query.return_value = {"records": [], "done": True}
    else:
        mock.query.return_value = {"records": query_results, "done": True}
    mock.describe.return_value = {"fields": []}
    return mock


def _make_bedrock_mock(dimension: int = 1024) -> MagicMock:
    """Create a mock Bedrock client returning deterministic embeddings."""
    mock = MagicMock()

    def invoke_model(**kwargs):
        body = json.loads(kwargs["body"])
        text = body["inputText"]
        # Use hash of text for deterministic but unique embeddings
        seed = hash(text) % 1000
        embedding = [float(seed + i) / 10000.0 for i in range(dimension)]
        response_body = json.dumps({"embedding": embedding})
        return {"body": io.BytesIO(response_body.encode("utf-8"))}

    mock.invoke_model.side_effect = invoke_model
    return mock


def _make_backend_mock() -> MagicMock:
    """Create a mock TurbopufferBackend."""
    mock = MagicMock()
    return mock


def _make_ssm_mock(watermark: str | None = None) -> MagicMock:
    """Create a mock SSM client with optional stored watermark."""
    mock = MagicMock()
    if watermark is not None:
        mock.get_parameter.return_value = {
            "Parameter": {"Value": watermark}
        }
    else:
        # Simulate ParameterNotFound
        error_response = {"Error": {"Code": "ParameterNotFound"}}
        mock.exceptions = MagicMock()
        mock.exceptions.ParameterNotFound = type(
            "ParameterNotFound", (Exception,), {}
        )
        mock.get_parameter.side_effect = mock.exceptions.ParameterNotFound(
            "not found"
        )
    return mock


def _make_cloudwatch_mock() -> MagicMock:
    """Create a mock CloudWatch client."""
    return MagicMock()


def _make_records(
    count: int,
    *,
    base_timestamp: str = "2026-03-20T06:00:00.000Z",
    id_prefix: str = "a0P",
) -> list[dict]:
    """Generate mock Salesforce records for testing."""
    records = []
    for i in range(count):
        records.append({
            "Id": f"{id_prefix}{str(i + 1).zfill(15)}AAA",
            "Name": f"Deal {i + 1}",
            "ascendix__Description__c": f"Description for deal {i + 1}",
            "ascendix__Stage__c": "Open",
            "LastModifiedDate": base_timestamp,
        })
    return records


# ===================================================================
# Watermark tests
# ===================================================================


class TestParseWatermark:
    def test_parse_watermark_composite(self):
        """Composite watermark parses into (timestamp, id)."""
        ts, last_id = parse_watermark("2026-03-20T06:00:00Z|a0P123")
        assert ts == "2026-03-20T06:00:00Z"
        assert last_id == "a0P123"

    def test_parse_watermark_empty(self):
        """Empty string defaults to epoch with no ID."""
        ts, last_id = parse_watermark("")
        assert ts == "1970-01-01T00:00:00Z"
        assert last_id == ""

    def test_parse_watermark_no_pipe(self):
        """Watermark without pipe defaults to epoch."""
        ts, last_id = parse_watermark("just-a-timestamp")
        assert ts == "1970-01-01T00:00:00Z"
        assert last_id == ""


class TestFormatWatermark:
    def test_format_watermark(self):
        """format_watermark produces composite string."""
        result = format_watermark("2026-03-20T06:00:00Z", "a0P123")
        assert result == "2026-03-20T06:00:00Z|a0P123"

    def test_format_watermark_no_id(self):
        """format_watermark with empty ID."""
        result = format_watermark("2026-03-20T06:00:00Z", "")
        assert result == "2026-03-20T06:00:00Z|"


# ===================================================================
# build_poll_where tests
# ===================================================================


class TestBuildPollWhere:
    def test_build_poll_where_with_id(self):
        """WHERE clause includes both timestamp and ID tiebreaker."""
        clause = build_poll_where("2026-03-20T06:00:00Z", "a0P123")
        assert "LastModifiedDate > 2026-03-20T06:00:00Z" in clause
        assert "LastModifiedDate = 2026-03-20T06:00:00Z AND Id > 'a0P123'" in clause
        assert "ORDER BY LastModifiedDate ASC, Id ASC" in clause

    def test_build_poll_where_without_id(self):
        """WHERE clause uses only timestamp when no ID."""
        clause = build_poll_where("2026-03-20T06:00:00Z", "")
        assert "LastModifiedDate > 2026-03-20T06:00:00Z" in clause
        assert "Id >" not in clause
        assert "ORDER BY LastModifiedDate ASC, Id ASC" in clause


# ===================================================================
# Sync pipeline tests
# ===================================================================


class TestSyncObject:
    @patch("poll_sync.index.build_relationship_spec_map", return_value={})
    def test_pagination_cursor_advances(self, mock_rel_map):
        """Mock SF query returning 3 records -> watermark advances to last record."""
        records = _make_records(3, base_timestamp="2026-03-20T06:00:00.000Z")
        sf = _make_sf_client_mock(records)
        bedrock = _make_bedrock_mock()
        backend = _make_backend_mock()
        ssm = _make_ssm_mock(watermark=None)
        cw = _make_cloudwatch_mock()

        result = _sync_object(
            "ascendix__Deal__c",
            full_sync=False,
            context=None,
            sf_client=sf,
            bedrock_client=bedrock,
            backend=backend,
            cloudwatch_client=cw,
            ssm_client=ssm,
            denorm_config=SAMPLE_CONFIG,
            namespace="org_test",
            salesforce_org_id="00Dtest",
            page_size=200,
        )

        assert result["records_synced"] == 3
        # Watermark should reference the last record
        wm_ts, wm_id = parse_watermark(result["watermark"])
        assert wm_ts == "2026-03-20T06:00:00.000Z"
        assert wm_id == records[-1]["Id"]
        # Backend should have been called with upsert
        assert backend.upsert.called

    @patch("poll_sync.index.build_relationship_spec_map", return_value={})
    def test_same_timestamp_tiebreaking(self, mock_rel_map):
        """3 records with identical LastModifiedDate -> all processed, watermark at last Id."""
        ts = "2026-03-20T06:00:00.000Z"
        records = [
            {
                "Id": "a0P000000000001AAA",
                "Name": "Deal A",
                "ascendix__Description__c": "A",
                "ascendix__Stage__c": "Open",
                "LastModifiedDate": ts,
            },
            {
                "Id": "a0P000000000002AAA",
                "Name": "Deal B",
                "ascendix__Description__c": "B",
                "ascendix__Stage__c": "Open",
                "LastModifiedDate": ts,
            },
            {
                "Id": "a0P000000000003AAA",
                "Name": "Deal C",
                "ascendix__Description__c": "C",
                "ascendix__Stage__c": "Open",
                "LastModifiedDate": ts,
            },
        ]
        sf = _make_sf_client_mock(records)
        bedrock = _make_bedrock_mock()
        backend = _make_backend_mock()
        ssm = _make_ssm_mock(watermark=None)
        cw = _make_cloudwatch_mock()

        result = _sync_object(
            "ascendix__Deal__c",
            full_sync=False,
            context=None,
            sf_client=sf,
            bedrock_client=bedrock,
            backend=backend,
            cloudwatch_client=cw,
            ssm_client=ssm,
            denorm_config=SAMPLE_CONFIG,
            namespace="org_test",
            salesforce_org_id="00Dtest",
            page_size=200,
        )

        assert result["records_synced"] == 3
        wm_ts, wm_id = parse_watermark(result["watermark"])
        assert wm_ts == ts
        assert wm_id == "a0P000000000003AAA"

    @patch("poll_sync.index.build_relationship_spec_map", return_value={})
    def test_empty_changeset(self, mock_rel_map):
        """No records modified -> watermark unchanged, 0 records synced."""
        sf = _make_sf_client_mock(query_results=[])
        bedrock = _make_bedrock_mock()
        backend = _make_backend_mock()
        ssm = _make_ssm_mock(watermark="2026-03-20T06:00:00Z|a0Pexisting")
        cw = _make_cloudwatch_mock()

        result = _sync_object(
            "ascendix__Deal__c",
            full_sync=False,
            context=None,
            sf_client=sf,
            bedrock_client=bedrock,
            backend=backend,
            cloudwatch_client=cw,
            ssm_client=ssm,
            denorm_config=SAMPLE_CONFIG,
            namespace="org_test",
            salesforce_org_id="00Dtest",
            page_size=200,
        )

        assert result["records_synced"] == 0
        # Watermark should stay at original value
        wm_ts, wm_id = parse_watermark(result["watermark"])
        assert wm_ts == "2026-03-20T06:00:00Z"
        assert wm_id == "a0Pexisting"
        # Backend should NOT have been called
        assert not backend.upsert.called

    @patch("poll_sync.index.build_relationship_spec_map", return_value={})
    def test_full_sync_resets_watermark(self, mock_rel_map):
        """full_sync=True -> watermark starts at epoch, processes all records."""
        records = _make_records(2, base_timestamp="2026-03-20T07:00:00.000Z")
        sf = _make_sf_client_mock(records)
        bedrock = _make_bedrock_mock()
        backend = _make_backend_mock()
        # Start with an existing watermark — full_sync should override it
        ssm = _make_ssm_mock(watermark="2026-03-20T06:00:00Z|a0Pold")
        cw = _make_cloudwatch_mock()

        result = _sync_object(
            "ascendix__Deal__c",
            full_sync=True,
            context=None,
            sf_client=sf,
            bedrock_client=bedrock,
            backend=backend,
            cloudwatch_client=cw,
            ssm_client=ssm,
            denorm_config=SAMPLE_CONFIG,
            namespace="org_test",
            salesforce_org_id="00Dtest",
            page_size=200,
        )

        assert result["records_synced"] == 2
        # Verify the SOQL used epoch timestamp (not the existing watermark)
        soql_arg = sf.query.call_args[0][0]
        assert "1970-01-01T00:00:00Z" in soql_arg
        # Final watermark should reflect the last record processed
        wm_ts, wm_id = parse_watermark(result["watermark"])
        assert wm_ts == "2026-03-20T07:00:00.000Z"
        assert wm_id == records[-1]["Id"]

    @patch("poll_sync.index.build_relationship_spec_map", return_value={})
    def test_timeout_safety(self, mock_rel_map):
        """Lambda context with low remaining time -> stop with continuation_needed."""
        records = _make_records(3, base_timestamp="2026-03-20T06:00:00.000Z")
        sf = _make_sf_client_mock(records)
        bedrock = _make_bedrock_mock()
        backend = _make_backend_mock()
        ssm = _make_ssm_mock(watermark=None)
        cw = _make_cloudwatch_mock()

        # Simulate Lambda context with only 30s remaining
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 30_000

        result = _sync_object(
            "ascendix__Deal__c",
            full_sync=False,
            context=context,
            sf_client=sf,
            bedrock_client=bedrock,
            backend=backend,
            cloudwatch_client=cw,
            ssm_client=ssm,
            denorm_config=SAMPLE_CONFIG,
            namespace="org_test",
            salesforce_org_id="00Dtest",
            page_size=200,
        )

        assert result["continuation_needed"] is True
        assert result["records_synced"] == 0

    @patch("poll_sync.index.build_relationship_spec_map", return_value={})
    def test_no_config_for_object(self, mock_rel_map):
        """Object not in denorm config -> skip with error."""
        sf = _make_sf_client_mock()
        bedrock = _make_bedrock_mock()
        backend = _make_backend_mock()
        ssm = _make_ssm_mock(watermark=None)
        cw = _make_cloudwatch_mock()

        result = _sync_object(
            "Nonexistent__c",
            full_sync=False,
            context=None,
            sf_client=sf,
            bedrock_client=bedrock,
            backend=backend,
            cloudwatch_client=cw,
            ssm_client=ssm,
            denorm_config=SAMPLE_CONFIG,
            namespace="org_test",
            salesforce_org_id="00Dtest",
            page_size=200,
        )

        assert result["records_synced"] == 0
        assert result["error"] == "no config"
