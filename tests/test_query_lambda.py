"""Tests for the query Lambda handler (Task 1.1.3).

All tests use mocked QueryHandler, SearchBackend, and Bedrock — no real
API calls.  The handler under test is ``lambda/query/index.py:handler``.

Because ``lambda`` is a Python reserved keyword, we import the module via
``importlib`` and reference it through a module-level variable ``_mod``.
"""

from __future__ import annotations

import base64
import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on the path so ``lib`` is importable.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Import the handler module despite ``lambda`` being a reserved keyword.
# We must also mock heavy dependencies that run at module import time
# (_load_config reads YAML, TurbopufferBackend needs credentials, etc.).
# ---------------------------------------------------------------------------

_SAMPLE_CONFIG = {
    "ascendix__Property__c": {
        "embed_fields": ["Name", "ascendix__City__c", "ascendix__State__c"],
        "metadata_fields": ["ascendix__TotalBuildingArea__c"],
        "parents": {},
    },
}


def _import_handler_module() -> ModuleType:
    """Import ``lambda/query/index.py`` via importlib with mocked init."""
    # Patch _load_config so it doesn't look for a YAML file on disk.
    # We'll mock at a lower level: yaml.safe_load + open.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "query_handler_lambda",
        Path(_PROJECT_ROOT) / "lambda" / "query" / "index.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules so @patch can find it.
    sys.modules["query_handler_lambda"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# Import the module.  This will succeed because denorm_config.yaml exists
# at the project root and ``lib`` is on sys.path.
_mod = _import_handler_module()

_SAMPLE_QUERY_RESULT_DICT = {
    "answer": "Tower One is a Class A office building in Dallas. It has 500,000 SF of space.",
    "citations": [{"id": "a0x001", "name": "Tower One"}],
    "tool_calls_made": 2,
    "turns": 3,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_warmed_sessions(monkeypatch):
    """Reset the module-level warm-session set between tests."""
    monkeypatch.setattr(_mod, "_warmed_sessions", set())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_query_result(**overrides):
    """Build a ``QueryResult`` with sensible defaults, applying *overrides*."""
    from lib.query_handler import QueryResult

    defaults = dict(_SAMPLE_QUERY_RESULT_DICT)
    defaults.update(overrides)
    return QueryResult(**defaults)


def _invoke(body: dict | str, is_base64: bool = False) -> dict:
    """Call the handler with a given body dict/string and return the response."""
    event: dict = {}
    if is_base64:
        raw = json.dumps(body) if isinstance(body, dict) else body
        event["body"] = base64.b64encode(raw.encode()).decode()
        event["isBase64Encoded"] = True
    else:
        event["body"] = json.dumps(body) if isinstance(body, dict) else body

    return _mod.handler(event, None)


def _parse_sse_events(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE body string into a list of ``(event_type, data_dict)``."""
    events: list[tuple[str, dict]] = []
    current_event: str | None = None
    for line in body.split("\n"):
        if line.startswith("event: "):
            current_event = line[len("event: "):]
        elif line.startswith("data: ") and current_event is not None:
            data = json.loads(line[len("data: "):])
            events.append((current_event, data))
            current_event = None
    return events


# The module was registered as ``query_handler_lambda`` in sys.modules,
# so @patch targets use that name.
_PATCH_PREFIX = "query_handler_lambda"


# ---------------------------------------------------------------------------
# 1. Valid request — 200, SSE content type, body contains token + citations + done
# ---------------------------------------------------------------------------

class TestValidRequest:
    """A well-formed request returns a 200 with all expected SSE events."""

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_returns_200_with_sse_events(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        resp = _invoke({"question": "Find offices in Dallas", "org_id": "00Ddl000003yx57EAA"})

        assert resp["statusCode"] == 200
        assert resp["headers"]["Content-Type"] == "text/event-stream"

        events = _parse_sse_events(resp["body"])
        event_types = [e[0] for e in events]

        # Must contain at least one token, one citations, and one done event.
        assert "token" in event_types
        assert "citations" in event_types
        assert "done" in event_types

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_done_event_contains_metadata(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        resp = _invoke({"question": "Find offices", "org_id": "00Ddl000003yx57EAA"})
        events = _parse_sse_events(resp["body"])
        done_events = [e for e in events if e[0] == "done"]

        assert len(done_events) == 1
        done_data = done_events[0][1]
        assert done_data["tool_calls"] == 2
        assert done_data["turns"] == 3

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_citations_event_contains_records(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        resp = _invoke({"question": "Find offices", "org_id": "00Ddl000003yx57EAA"})
        events = _parse_sse_events(resp["body"])
        citation_events = [e for e in events if e[0] == "citations"]

        assert len(citation_events) == 1
        citations = citation_events[0][1]["citations"]
        assert len(citations) == 1
        assert citations[0]["id"] == "a0x001"
        assert citations[0]["name"] == "Tower One"

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_no_citations_event_when_empty(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result(citations=[])

        resp = _invoke({"question": "Tell me about CRE", "org_id": "00Ddl000003yx57EAA"})
        events = _parse_sse_events(resp["body"])
        event_types = [e[0] for e in events]

        assert "citations" not in event_types
        assert "token" in event_types
        assert "done" in event_types


# ---------------------------------------------------------------------------
# 2. Missing question — 400 with error event
# ---------------------------------------------------------------------------

class TestMissingQuestion:

    def test_missing_question_returns_400(self):
        resp = _invoke({"org_id": "00Ddl000003yx57EAA"})

        assert resp["statusCode"] == 400
        events = _parse_sse_events(resp["body"])
        assert len(events) == 1
        assert events[0][0] == "error"
        assert "question" in events[0][1]["message"].lower()

    def test_empty_question_returns_400(self):
        resp = _invoke({"question": "   ", "org_id": "00Ddl000003yx57EAA"})

        assert resp["statusCode"] == 400
        events = _parse_sse_events(resp["body"])
        assert events[0][0] == "error"


# ---------------------------------------------------------------------------
# 3. Missing org_id — 400 with error event
# ---------------------------------------------------------------------------

class TestMissingOrgId:

    def test_missing_org_id_returns_400(self):
        resp = _invoke({"question": "Find offices"})

        assert resp["statusCode"] == 400
        events = _parse_sse_events(resp["body"])
        assert len(events) == 1
        assert events[0][0] == "error"
        assert "org_id" in events[0][1]["message"].lower()

    def test_empty_org_id_returns_400(self):
        resp = _invoke({"question": "Find offices", "org_id": ""})

        assert resp["statusCode"] == 400
        events = _parse_sse_events(resp["body"])
        assert events[0][0] == "error"


# ---------------------------------------------------------------------------
# 4. Base64-encoded body — handler decodes correctly
# ---------------------------------------------------------------------------

class TestBase64Body:

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_base64_encoded_body(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        resp = _invoke(
            {"question": "Find offices", "org_id": "00Ddl000003yx57EAA"},
            is_base64=True,
        )

        assert resp["statusCode"] == 200
        events = _parse_sse_events(resp["body"])
        event_types = [e[0] for e in events]
        assert "token" in event_types
        assert "done" in event_types


# ---------------------------------------------------------------------------
# 5. Session warm cache — second call with same session_id doesn't re-warm
# ---------------------------------------------------------------------------

class TestSessionWarmCache:

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_warm_called_on_first_request(self, MockQH, MockBackend, mock_boto3):
        mock_backend_instance = MockBackend.return_value
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        _invoke({
            "question": "Q1",
            "org_id": "00Ddl000003yx57EAA",
            "session_id": "sess-1",
        })

        mock_backend_instance.warm.assert_called_once_with("org_00Ddl000003yx57EAA")

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_warm_not_called_on_second_request_same_session(self, MockQH, MockBackend, mock_boto3):
        mock_backend_instance = MockBackend.return_value
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        _invoke({
            "question": "Q1",
            "org_id": "00Ddl000003yx57EAA",
            "session_id": "sess-2",
        })
        _invoke({
            "question": "Q2",
            "org_id": "00Ddl000003yx57EAA",
            "session_id": "sess-2",
        })

        # warm should be called once (first request) and not again (second).
        assert mock_backend_instance.warm.call_count == 1

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_warm_called_for_different_sessions(self, MockQH, MockBackend, mock_boto3):
        mock_backend_instance = MockBackend.return_value
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        _invoke({
            "question": "Q1",
            "org_id": "00Ddl000003yx57EAA",
            "session_id": "sess-a",
        })
        _invoke({
            "question": "Q2",
            "org_id": "00Ddl000003yx57EAA",
            "session_id": "sess-b",
        })

        assert mock_backend_instance.warm.call_count == 2


# ---------------------------------------------------------------------------
# 6. SSE format validation — each event has correct event: and data: lines
# ---------------------------------------------------------------------------

class TestSSEFormatValidation:

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_sse_format_structure(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        resp = _invoke({"question": "Find offices", "org_id": "00Ddl000003yx57EAA"})
        body = resp["body"]

        # Each SSE event block must have "event: <type>\n" followed by "data: <json>\n\n".
        blocks = body.strip().split("\n\n")
        for block in blocks:
            lines = block.strip().split("\n")
            assert len(lines) == 2, f"SSE block should have 2 lines, got: {lines}"
            assert lines[0].startswith("event: "), (
                f"First line must start with 'event: ', got: {lines[0]}"
            )
            assert lines[1].startswith("data: "), (
                f"Second line must start with 'data: ', got: {lines[1]}"
            )

            # data line must be valid JSON.
            data_str = lines[1][len("data: "):]
            json.loads(data_str)  # raises on invalid JSON

    def test_format_sse_helper(self):
        result = _mod.format_sse("token", {"text": "hello"})
        assert result == 'event: token\ndata: {"text": "hello"}\n\n'

    def test_format_sse_special_chars(self):
        result = _mod.format_sse("error", {"message": 'Quote "test" and newline'})
        assert result.startswith("event: error\n")
        # Must be valid JSON in data line.
        data_line = result.split("\n")[1]
        data = json.loads(data_line[len("data: "):])
        assert data["message"] == 'Quote "test" and newline'

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_answer_split_into_sentence_chunks(self, MockQH, MockBackend, mock_boto3):
        """Multi-sentence answers should produce multiple token events."""
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result(
            answer="First sentence. Second sentence. Third sentence.",
            citations=[],
        )

        resp = _invoke({"question": "Q", "org_id": "org1"})
        events = _parse_sse_events(resp["body"])
        token_events = [e for e in events if e[0] == "token"]

        assert len(token_events) >= 2, (
            "Multi-sentence answer should be split into multiple token events"
        )


# ---------------------------------------------------------------------------
# 7. Error handling — QueryHandler exception returns 500 with error event
# ---------------------------------------------------------------------------

class TestErrorHandling:

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_query_handler_exception_returns_500(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.side_effect = RuntimeError("Bedrock is down")

        resp = _invoke({"question": "Find offices", "org_id": "00Ddl000003yx57EAA"})

        assert resp["statusCode"] == 500
        events = _parse_sse_events(resp["body"])
        assert len(events) == 1
        assert events[0][0] == "error"
        assert "Bedrock is down" in events[0][1]["message"]

    def test_invalid_json_body_returns_400(self):
        resp = _mod.handler({"body": "not-valid-json{"}, None)

        assert resp["statusCode"] == 400
        events = _parse_sse_events(resp["body"])
        assert events[0][0] == "error"
        assert "json" in events[0][1]["message"].lower()

    def test_both_fields_missing_returns_400(self):
        resp = _invoke({})

        assert resp["statusCode"] == 400
        events = _parse_sse_events(resp["body"])
        assert events[0][0] == "error"
        msg = events[0][1]["message"].lower()
        assert "question" in msg
        assert "org_id" in msg


# ---------------------------------------------------------------------------
# 8. CORS headers present — Access-Control-Allow-Origin header set
# ---------------------------------------------------------------------------

class TestCORSHeaders:

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_cors_header_on_success(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        resp = _invoke({"question": "Find offices", "org_id": "00Ddl000003yx57EAA"})

        assert resp["headers"]["Access-Control-Allow-Origin"] == "*"

    def test_cors_header_on_error(self):
        resp = _invoke({"org_id": "00Ddl000003yx57EAA"})  # missing question

        assert resp["statusCode"] == 400
        assert resp["headers"]["Access-Control-Allow-Origin"] == "*"

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_cache_control_header(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        resp = _invoke({"question": "Q", "org_id": "org1"})

        assert resp["headers"]["Cache-Control"] == "no-cache"

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_content_type_header(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        resp = _invoke({"question": "Q", "org_id": "org1"})

        assert resp["headers"]["Content-Type"] == "text/event-stream"


# ---------------------------------------------------------------------------
# 9. Namespace construction
# ---------------------------------------------------------------------------

class TestNamespaceConstruction:

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_namespace_built_from_org_id(self, MockQH, MockBackend, mock_boto3):
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        _invoke({"question": "Q", "org_id": "00Ddl000003yx57EAA", "session_id": "ns-test"})

        # QueryHandler should have been constructed with the right namespace.
        call_kwargs = MockQH.call_args
        assert call_kwargs[1]["namespace"] == "org_00Ddl000003yx57EAA"


# ---------------------------------------------------------------------------
# 10. Answer chunking helper
# ---------------------------------------------------------------------------

class TestAnswerChunking:

    def test_single_sentence(self):
        chunks = _mod._split_answer_into_chunks("Just one sentence.")
        assert chunks == ["Just one sentence."]

    def test_multiple_sentences(self):
        chunks = _mod._split_answer_into_chunks("First. Second. Third.")
        assert len(chunks) == 3

    def test_paragraph_split(self):
        chunks = _mod._split_answer_into_chunks("Paragraph one.\n\nParagraph two.")
        assert len(chunks) == 2

    def test_empty_string(self):
        assert _mod._split_answer_into_chunks("") == []

    def test_no_split_points(self):
        chunks = _mod._split_answer_into_chunks("No punctuation ending here")
        assert chunks == ["No punctuation ending here"]


# ---------------------------------------------------------------------------
# 11. Prior context pass-through (Task 4.14)
# ---------------------------------------------------------------------------

class TestPriorContext:

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_prior_context_passed_to_query_handler(self, MockQH, MockBackend, mock_boto3):
        """Dict with query+answer is forwarded to qh.query()."""
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        _invoke({
            "question": "Show by deal count",
            "org_id": "00Ddl000003yx57EAA",
            "prior_context": {"query": "Top markets", "answer": "Which metric?"},
        })

        call_kwargs = mock_qh_instance.query.call_args
        assert call_kwargs[1]["prior_context"] == {"query": "Top markets", "answer": "Which metric?"}

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_no_prior_context_passes_none(self, MockQH, MockBackend, mock_boto3):
        """Absent field passes None."""
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        _invoke({"question": "Find offices", "org_id": "00Ddl000003yx57EAA"})

        call_kwargs = mock_qh_instance.query.call_args
        assert call_kwargs[1]["prior_context"] is None

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_malformed_prior_context_dropped(self, MockQH, MockBackend, mock_boto3):
        """Missing answer key -> None."""
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        _invoke({
            "question": "Q",
            "org_id": "org1",
            "prior_context": {"query": "Top markets"},
        })

        call_kwargs = mock_qh_instance.query.call_args
        assert call_kwargs[1]["prior_context"] is None

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_non_string_prior_context_fields_dropped(self, MockQH, MockBackend, mock_boto3):
        """{"query": {}, "answer": []} -> None."""
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        _invoke({
            "question": "Q",
            "org_id": "org1",
            "prior_context": {"query": {}, "answer": []},
        })

        call_kwargs = mock_qh_instance.query.call_args
        assert call_kwargs[1]["prior_context"] is None

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_non_dict_prior_context_dropped(self, MockQH, MockBackend, mock_boto3):
        """"just a string" -> None."""
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        _invoke({
            "question": "Q",
            "org_id": "org1",
            "prior_context": "just a string",
        })

        call_kwargs = mock_qh_instance.query.call_args
        assert call_kwargs[1]["prior_context"] is None

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_long_answer_truncated(self, MockQH, MockBackend, mock_boto3):
        """5000-char answer -> 2003 chars."""
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        long_answer = "x" * 5000
        _invoke({
            "question": "Q",
            "org_id": "org1",
            "prior_context": {"query": "short", "answer": long_answer},
        })

        call_kwargs = mock_qh_instance.query.call_args
        pc = call_kwargs[1]["prior_context"]
        assert pc is not None
        assert len(pc["answer"]) == 2003
        assert pc["answer"].endswith("...")

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_long_query_truncated(self, MockQH, MockBackend, mock_boto3):
        """1000-char query -> 503 chars."""
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        long_query = "q" * 1000
        _invoke({
            "question": "Q",
            "org_id": "org1",
            "prior_context": {"query": long_query, "answer": "short"},
        })

        call_kwargs = mock_qh_instance.query.call_args
        pc = call_kwargs[1]["prior_context"]
        assert pc is not None
        assert len(pc["query"]) == 503
        assert pc["query"].endswith("...")

    @patch(f"{_PATCH_PREFIX}.boto3")
    @patch(f"{_PATCH_PREFIX}.TurbopufferBackend")
    @patch(f"{_PATCH_PREFIX}.QueryHandler")
    def test_whitespace_only_fields_dropped(self, MockQH, MockBackend, mock_boto3):
        """{"query": "  ", "answer": " "} -> None."""
        mock_qh_instance = MockQH.return_value
        mock_qh_instance.query.return_value = _make_query_result()

        _invoke({
            "question": "Q",
            "org_id": "org1",
            "prior_context": {"query": "  ", "answer": " "},
        })

        call_kwargs = mock_qh_instance.query.call_args
        assert call_kwargs[1]["prior_context"] is None
