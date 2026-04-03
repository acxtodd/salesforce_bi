"""Tests for poll sync Lambda (Task 4.8.1).

All tests use mocks — no network or API keys required.
"""

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import yaml

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
import poll_sync.index as _poll_sync_mod  # noqa: E402


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
    """Create a mock Bedrock client returning deterministic Cohere embeddings."""
    mock = MagicMock()

    def invoke_model(**kwargs):
        body = json.loads(kwargs["body"])
        text = body["texts"][0]
        # Use hash of text for deterministic but unique embeddings
        seed = hash(text) % 1000
        int8_embedding = [int((seed + i) % 256 - 128) for i in range(dimension)]
        response_body = json.dumps({"embeddings": {"int8": [int8_embedding]}})
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


# ===================================================================
# Runtime config loading tests (Task 4.9.6)
# ===================================================================


class TestRuntimeConfigLoading:
    """Verify poll_sync uses RuntimeConfigLoader with safe fallback."""

    def _reset_module_state(self):
        """Reset module-level caches between tests."""
        _poll_sync_mod._denorm_config = None
        _poll_sync_mod._denorm_config_raw_yaml = ""
        _poll_sync_mod._denorm_config_version = ""
        _poll_sync_mod._runtime_config_loader = None

    def test_poll_sync_loads_config_from_runtime_loader(self, monkeypatch):
        """When RuntimeConfigLoader succeeds, poll_sync uses its denorm_config."""
        self._reset_module_state()

        class FakeLoader:
            def __init__(self):
                self.called_org_ids = []

            def load(self, org_id):
                self.called_org_ids.append(org_id)
                return {
                    "version_id": "runtime-v1",
                    "denorm_config": {
                        "ascendix__Deal__c": {
                            "embed_fields": ["Name", "ascendix__NewField__c"],
                            "metadata_fields": [],
                            "parents": {},
                        }
                    },
                }

        fake_loader = FakeLoader()
        monkeypatch.setattr(_poll_sync_mod, "_runtime_config_loader", fake_loader)

        config, raw_yaml = _poll_sync_mod._load_denorm_config("00DTEST")

        assert fake_loader.called_org_ids == ["00DTEST"]
        assert "ascendix__Deal__c" in config
        assert "ascendix__NewField__c" in config["ascendix__Deal__c"]["embed_fields"]
        assert _poll_sync_mod._denorm_config_version == "runtime-v1"

        # Clean up
        self._reset_module_state()

    def test_poll_sync_falls_back_to_static_yaml_on_loader_error(self, monkeypatch, tmp_path):
        """When RuntimeConfigLoader raises, poll_sync falls back to static YAML."""
        self._reset_module_state()

        class FailingLoader:
            def load(self, org_id):
                raise RuntimeError("S3 unavailable")

        monkeypatch.setattr(_poll_sync_mod, "_runtime_config_loader", FailingLoader())

        fallback_config = {
            "ascendix__Property__c": {
                "embed_fields": ["Name"],
                "metadata_fields": [],
                "parents": {},
            }
        }
        config_path = tmp_path / "denorm_config.yaml"
        config_path.write_text(yaml.safe_dump(fallback_config))
        monkeypatch.setenv("DENORM_CONFIG_PATH", str(config_path))

        config, raw_yaml = _poll_sync_mod._load_denorm_config("00DTEST")

        assert "ascendix__Property__c" in config
        assert _poll_sync_mod._denorm_config_version == "bundled-fallback"

        # Clean up
        self._reset_module_state()

    def test_poll_sync_caches_config_after_first_load(self, monkeypatch):
        """Config is cached at module level; second call does not re-invoke loader."""
        self._reset_module_state()

        call_count = 0

        class CountingLoader:
            def load(self, org_id):
                nonlocal call_count
                call_count += 1
                return {
                    "version_id": "cached-v1",
                    "denorm_config": {"ascendix__Deal__c": {"embed_fields": ["Name"], "metadata_fields": [], "parents": {}}},
                }

        monkeypatch.setattr(_poll_sync_mod, "_runtime_config_loader", CountingLoader())

        _poll_sync_mod._load_denorm_config("00DTEST")
        _poll_sync_mod._load_denorm_config("00DTEST")

        assert call_count == 1

        # Clean up
        self._reset_module_state()

    def test_runtime_config_honors_new_objects_without_yaml_edit(self, monkeypatch):
        """A new object added via runtime config is honored by _sync_object."""
        self._reset_module_state()

        runtime_config = {
            "ascendix__Deal__c": {
                "embed_fields": ["Name", "ascendix__Description__c"],
                "metadata_fields": ["ascendix__Stage__c"],
                "parents": {},
            },
            "ascendix__NewObject__c": {
                "embed_fields": ["Name"],
                "metadata_fields": [],
                "parents": {},
            },
        }

        # _sync_object accepts denorm_config directly — verify new object is recognized
        result_known = _sync_object(
            "ascendix__NewObject__c",
            denorm_config=runtime_config,
            sf_client=_make_sf_client_mock([]),
            bedrock_client=_make_bedrock_mock(),
            backend=_make_backend_mock(),
            cloudwatch_client=_make_cloudwatch_mock(),
            ssm_client=_make_ssm_mock(watermark=None),
            namespace="org_test",
            salesforce_org_id="00Dtest",
            page_size=200,
        )
        assert "error" not in result_known

        # Unknown object still skipped
        result_unknown = _sync_object(
            "ascendix__Unknown__c",
            denorm_config=runtime_config,
            sf_client=_make_sf_client_mock([]),
            bedrock_client=_make_bedrock_mock(),
            backend=_make_backend_mock(),
            cloudwatch_client=_make_cloudwatch_mock(),
            ssm_client=_make_ssm_mock(watermark=None),
            namespace="org_test",
            salesforce_org_id="00Dtest",
            page_size=200,
        )
        assert result_unknown["error"] == "no config"

        self._reset_module_state()
