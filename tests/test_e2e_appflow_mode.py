"""Regression tests for --real-appflow mode in integration_test_e2e.py.

Covers:
- Flag handling (real_appflow vs synthetic mode)
- S3 CDC file poll logic (poll_for_appflow_cdc_file)
- Enriched results dict with timing fields
"""

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lambda"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestFlagHandling:
    """Verify --real-appflow flag sets mode correctly."""

    def test_real_appflow_flag_sets_mode(self):
        """When real_appflow=True, results dict mode is 'real_appflow'."""
        from scripts.integration_test_e2e import run_e2e_tests

        mock_sf = MagicMock()
        mock_backend = MagicMock()

        with patch("scripts.integration_test_e2e.create_test_property", side_effect=Exception("test abort")):
            results = run_e2e_tests(mock_sf, mock_backend, "org_test", real_appflow=True)

        assert results["mode"] == "real_appflow"

    def test_synthetic_mode_is_default(self):
        """Without real_appflow flag, results dict mode is 'synthetic'."""
        from scripts.integration_test_e2e import run_e2e_tests

        mock_sf = MagicMock()
        mock_backend = MagicMock()

        with patch("scripts.integration_test_e2e.create_test_property", side_effect=Exception("test abort")):
            results = run_e2e_tests(mock_sf, mock_backend, "org_test")

        assert results["mode"] == "synthetic"

    def test_synthetic_mode_calls_write_cdc_event(self):
        """In synthetic mode, write_cdc_event_to_s3 IS called after CREATE."""
        from scripts.integration_test_e2e import run_e2e_tests

        mock_sf = MagicMock()
        mock_backend = MagicMock()

        with (
            patch("scripts.integration_test_e2e.create_test_property", return_value="a0xTEST001"),
            patch("scripts.integration_test_e2e.write_cdc_event_to_s3") as mock_write,
            patch("scripts.integration_test_e2e.poll_for_record", return_value=None),
            patch("scripts.integration_test_e2e.delete_test_property"),
        ):
            run_e2e_tests(mock_sf, mock_backend, "org_test", real_appflow=False)

        mock_write.assert_called_once_with("a0xTEST001", "CREATE")

    def test_real_appflow_mode_skips_write_cdc_event(self):
        """In real_appflow mode, write_cdc_event_to_s3 is NOT called."""
        from scripts.integration_test_e2e import run_e2e_tests

        mock_sf = MagicMock()
        mock_backend = MagicMock()

        with (
            patch("scripts.integration_test_e2e.create_test_property", return_value="a0xTEST001"),
            patch("scripts.integration_test_e2e.write_cdc_event_to_s3") as mock_write,
            patch("scripts.integration_test_e2e.poll_for_appflow_cdc_file", return_value=None),
            patch("scripts.integration_test_e2e.delete_test_property"),
        ):
            run_e2e_tests(mock_sf, mock_backend, "org_test", real_appflow=True)

        mock_write.assert_not_called()


class TestPollForAppflowCdcFile:
    """Unit tests for poll_for_appflow_cdc_file with mocked S3."""

    def test_finds_matching_cdc_file(self):
        """Returns s3_key and arrival_ts when a matching file is found."""
        from scripts.integration_test_e2e import poll_for_appflow_cdc_file

        now = datetime.now(timezone.utc)
        file_time = now + timedelta(seconds=5)

        cdc_payload = {
            "ChangeEventHeader": {
                "entityName": "ascendix__Property__ChangeEvent",
                "changeType": "CREATE",
                "recordIds": ["a0xMATCH001"],
                "commitTimestamp": int(now.timestamp() * 1000),
            }
        }

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {
                        "Key": "cdc/ascendix__Property__c/2026/03/17/event-001.json",
                        "LastModified": file_time,
                    }
                ]
            }
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        body_stream = MagicMock()
        body_stream.read.return_value = json.dumps(cdc_payload).encode("utf-8")
        mock_s3.get_object.return_value = {"Body": body_stream}

        with patch("scripts.integration_test_e2e.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_s3
            result = poll_for_appflow_cdc_file(
                "a0xMATCH001", "CREATE", now.timestamp(), timeout=5,
            )

        assert result is not None
        assert result["s3_key"] == "cdc/ascendix__Property__c/2026/03/17/event-001.json"
        assert "arrival_ts" in result
        assert result["payload"] == cdc_payload

    def test_skips_file_with_wrong_record_id(self):
        """Files with non-matching recordIds are skipped; returns None on timeout."""
        from scripts.integration_test_e2e import poll_for_appflow_cdc_file

        now = datetime.now(timezone.utc)
        file_time = now + timedelta(seconds=5)

        cdc_payload = {
            "ChangeEventHeader": {
                "changeType": "CREATE",
                "recordIds": ["a0xOTHER999"],  # wrong ID
                "commitTimestamp": int(now.timestamp() * 1000),
            }
        }

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {
                        "Key": "cdc/ascendix__Property__c/2026/03/17/event-wrong.json",
                        "LastModified": file_time,
                    }
                ]
            }
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        body_stream = MagicMock()
        body_stream.read.return_value = json.dumps(cdc_payload).encode("utf-8")
        mock_s3.get_object.return_value = {"Body": body_stream}

        with patch("scripts.integration_test_e2e.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_s3
            result = poll_for_appflow_cdc_file(
                "a0xMATCH001", "CREATE", now.timestamp(), timeout=0.5,
            )

        assert result is None

    def test_skips_stale_files(self):
        """Files with LastModified before mutation time are ignored."""
        from scripts.integration_test_e2e import poll_for_appflow_cdc_file

        now = datetime.now(timezone.utc)
        stale_time = now - timedelta(minutes=10)  # before mutation

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {
                        "Key": "cdc/ascendix__Property__c/old-file.json",
                        "LastModified": stale_time,
                    }
                ]
            }
        ]
        mock_s3.get_paginator.return_value = mock_paginator

        with patch("scripts.integration_test_e2e.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_s3
            result = poll_for_appflow_cdc_file(
                "a0xMATCH001", "CREATE", now.timestamp(), timeout=0.5,
            )

        assert result is None
        # get_object should never be called since the file was filtered by timestamp
        mock_s3.get_object.assert_not_called()

    def test_returns_none_on_empty_bucket(self):
        """Returns None when no files exist under the prefix."""
        from scripts.integration_test_e2e import poll_for_appflow_cdc_file

        now = datetime.now(timezone.utc)

        mock_s3 = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{"Contents": []}]
        mock_s3.get_paginator.return_value = mock_paginator

        with patch("scripts.integration_test_e2e.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_s3
            result = poll_for_appflow_cdc_file(
                "a0xANY001", "CREATE", now.timestamp(), timeout=0.5,
            )

        assert result is None


class TestTimingCapture:
    """Verify enriched results dict includes timing fields."""

    def test_pass_result_includes_all_timing_fields(self):
        """A passing test in real_appflow mode has mutation_ts, cdc_s3_key, etc."""
        from scripts.integration_test_e2e import run_e2e_tests

        mock_sf = MagicMock()
        mock_backend = MagicMock()

        cdc_file_result = {
            "s3_key": "cdc/ascendix__Property__c/2026/03/17/event.json",
            "arrival_ts": "2026-03-17T14:30:12+00:00",
            "payload": {},
        }

        # poll_for_record returns a record whose city dynamically matches
        # whatever update_test_property was last called with
        _current_city = {"value": "TestCity"}

        def _fake_update(sf, rid, city):
            _current_city["value"] = city

        def _fake_poll(*args, **kwargs):
            return {"id": "a0xTEST001", "name": "E2E_TEST_123", "city": _current_city["value"]}

        with (
            patch("scripts.integration_test_e2e.create_test_property", return_value="a0xTEST001"),
            patch("scripts.integration_test_e2e.poll_for_appflow_cdc_file", return_value=cdc_file_result),
            patch("scripts.integration_test_e2e.poll_for_record", side_effect=_fake_poll),
            patch("scripts.integration_test_e2e.update_test_property", side_effect=_fake_update),
            patch("scripts.integration_test_e2e.delete_test_property"),
            patch("scripts.integration_test_e2e.poll_for_record_absent", return_value=True),
            patch("scripts.integration_test_e2e.POLL_TIMEOUT_SECONDS", 2),
            patch("scripts.integration_test_e2e.POLL_INTERVAL_SECONDS", 0.01),
        ):
            results = run_e2e_tests(mock_sf, mock_backend, "org_test", real_appflow=True)

        assert results["mode"] == "real_appflow"
        create_test = next(t for t in results["tests"] if t["name"] == "CREATE")
        assert create_test["status"] == "PASS"
        assert "mutation_ts" in create_test
        assert create_test["cdc_s3_key"] == "cdc/ascendix__Property__c/2026/03/17/event.json"
        assert "cdc_arrival_ts" in create_test
        assert "turbopuffer_visible_ts" in create_test
        assert "latency_seconds" in create_test
        assert isinstance(create_test["latency_seconds"], float)

    def test_synthetic_mode_still_includes_timing(self):
        """Synthetic mode also includes timing fields (mutation_ts, latency)."""
        from scripts.integration_test_e2e import run_e2e_tests

        mock_sf = MagicMock()
        mock_backend = MagicMock()

        _current_city = {"value": "TestCity"}

        def _fake_update(sf, rid, city):
            _current_city["value"] = city

        def _fake_poll(*args, **kwargs):
            return {"id": "a0xTEST001", "name": "E2E_TEST_123", "city": _current_city["value"]}

        with (
            patch("scripts.integration_test_e2e.create_test_property", return_value="a0xTEST001"),
            patch("scripts.integration_test_e2e.write_cdc_event_to_s3"),
            patch("scripts.integration_test_e2e.poll_for_record", side_effect=_fake_poll),
            patch("scripts.integration_test_e2e.update_test_property", side_effect=_fake_update),
            patch("scripts.integration_test_e2e.delete_test_property"),
            patch("scripts.integration_test_e2e.poll_for_record_absent", return_value=True),
            patch("scripts.integration_test_e2e.POLL_TIMEOUT_SECONDS", 2),
            patch("scripts.integration_test_e2e.POLL_INTERVAL_SECONDS", 0.01),
        ):
            results = run_e2e_tests(mock_sf, mock_backend, "org_test", real_appflow=False)

        assert results["mode"] == "synthetic"
        create_test = next(t for t in results["tests"] if t["name"] == "CREATE")
        assert create_test["status"] == "PASS"
        assert "mutation_ts" in create_test
        assert "latency_seconds" in create_test
        # cdc_s3_key is empty string for synthetic mode (omitted from dict)
        assert "cdc_s3_key" not in create_test

    def test_build_test_entry_omits_empty_fields(self):
        """_build_test_entry only includes fields with non-empty values."""
        from scripts.integration_test_e2e import _build_test_entry

        entry = _build_test_entry("CREATE", "PASS", mutation_ts="2026-03-17T14:30:00Z")
        assert "mutation_ts" in entry
        assert "cdc_s3_key" not in entry
        assert "reason" not in entry

    def test_build_test_entry_includes_latency(self):
        """_build_test_entry includes latency_seconds when provided."""
        from scripts.integration_test_e2e import _build_test_entry

        entry = _build_test_entry("CREATE", "PASS", latency_seconds=42.567)
        assert entry["latency_seconds"] == 42.6  # rounded to 1 decimal
