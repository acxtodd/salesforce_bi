"""Tests for the query handler module (Task 1.1.2).

All tests use mocked Bedrock client and SearchBackend -- no real API calls.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure project root is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.query_handler import MAX_TURNS, QueryHandler, QueryResult
from lib.search_backend import SearchBackend
from lib.tool_dispatch import ToolDispatcher, build_field_registry

# =========================================================================
# Test fixtures / helpers
# =========================================================================

SAMPLE_CONFIG = {
    "ascendix__Property__c": {
        "embed_fields": [
            "Name",
            "ascendix__City__c",
            "ascendix__State__c",
            "ascendix__PropertyClass__c",
            "ascendix__PropertySubType__c",
            "ascendix__Description__c",
        ],
        "metadata_fields": [
            "ascendix__TotalBuildingArea__c",
            "ascendix__Floors__c",
            "ascendix__YearBuilt__c",
        ],
        "parents": {
            "ascendix__OwnerLandlord__c": ["Name"],
            "ascendix__Market__c": ["Name"],
            "ascendix__SubMarket__c": ["Name"],
        },
    },
    "ascendix__Lease__c": {
        "embed_fields": [
            "Name",
            "ascendix__LeaseType__c",
        ],
        "metadata_fields": [
            "ascendix__Size__c",
            "ascendix__LeaseRatePerUOM__c",
            "ascendix__TermCommencementDate__c",
            "ascendix__TermExpirationDate__c",
        ],
        "parents": {
            "ascendix__Property__c": [
                "Name",
                "ascendix__City__c",
                "ascendix__State__c",
                "ascendix__PropertyClass__c",
            ],
            "ascendix__Tenant__c": ["Name"],
            "ascendix__OwnerLandlord__c": ["Name"],
        },
    },
}

NAMESPACE = "org_00Ddl000003yx57EAA"
MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"
SYSTEM_PROMPT = "You are a CRE search assistant."
TOOL_DEFS = [
    {
        "toolSpec": {
            "name": "search_records",
            "description": "Search AscendixIQ CRE records.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string"},
                        "filters": {"type": "object"},
                        "text_query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["object_type"],
                }
            },
        }
    },
    {
        "toolSpec": {
            "name": "aggregate_records",
            "description": "Aggregate CRE records.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "object_type": {"type": "string"},
                        "aggregate": {"type": "string"},
                        "filters": {"type": "object"},
                        "aggregate_field": {"type": "string"},
                        "group_by": {"type": "string"},
                    },
                    "required": ["object_type"],
                }
            },
        }
    },
]


def _make_backend() -> MagicMock:
    """Create a mock SearchBackend."""
    backend = MagicMock(spec=SearchBackend)
    backend.search.return_value = []
    backend.aggregate.return_value = {"count": 0}
    return backend


def _make_handler(
    bedrock_client: MagicMock,
    backend: MagicMock | None = None,
) -> QueryHandler:
    """Create a QueryHandler with mocked dependencies."""
    if backend is None:
        backend = _make_backend()
    registry = build_field_registry(SAMPLE_CONFIG)
    return QueryHandler(
        bedrock_client=bedrock_client,
        backend=backend,
        namespace=NAMESPACE,
        field_registry=registry,
        model_id=MODEL_ID,
        system_prompt=SYSTEM_PROMPT,
        tool_definitions=TOOL_DEFS,
    )


def _end_turn_response(text: str) -> dict:
    """Build a Bedrock Converse response with stopReason='end_turn'."""
    return {
        "stopReason": "end_turn",
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": text}],
            }
        },
    }


def _tool_use_response(tool_calls: list[dict]) -> dict:
    """Build a Bedrock Converse response with stopReason='tool_use'.

    Each entry in *tool_calls* is::

        {"toolUseId": "...", "name": "...", "input": {...}}
    """
    content: list[dict] = []
    for tc in tool_calls:
        content.append({
            "toolUse": {
                "toolUseId": tc["toolUseId"],
                "name": tc["name"],
                "input": tc.get("input", {}),
            }
        })
    # Claude may also emit a text block before the tool calls.
    content.insert(0, {"text": "Let me search for that."})
    return {
        "stopReason": "tool_use",
        "output": {
            "message": {
                "role": "assistant",
                "content": content,
            }
        },
    }


# =========================================================================
# 1. Simple question (no tool use)
# =========================================================================

class TestSimpleQuestion:
    """stopReason='end_turn' on first call -- no tools needed."""

    def test_returns_answer(self):
        bedrock = MagicMock()
        bedrock.converse.return_value = _end_turn_response(
            "Dallas has a thriving CRE market."
        )
        handler = _make_handler(bedrock)
        result = handler.query("Tell me about Dallas CRE")

        assert result.answer == "Dallas has a thriving CRE market."
        assert result.tool_calls_made == 0
        assert result.turns == 1
        assert result.citations == []

    def test_converse_called_with_correct_args(self):
        bedrock = MagicMock()
        bedrock.converse.return_value = _end_turn_response("Answer.")
        handler = _make_handler(bedrock)
        handler.query("Hello")

        bedrock.converse.assert_called_once()
        kwargs = bedrock.converse.call_args[1]
        assert kwargs["modelId"] == MODEL_ID
        assert kwargs["system"] == [{"text": SYSTEM_PROMPT}]
        assert kwargs["toolConfig"] == {"tools": TOOL_DEFS}
        # First message should be the user question.
        assert kwargs["messages"][0]["role"] == "user"
        assert kwargs["messages"][0]["content"][0]["text"] == "Hello"


# =========================================================================
# 2. Single tool call
# =========================================================================

class TestSingleToolCall:
    """Bedrock returns one tool_use, then end_turn."""

    def test_dispatches_tool_and_returns_synthesis(self):
        backend = _make_backend()
        backend.search.return_value = [
            {"id": "a0x001", "name": "Tower One", "city": "Dallas", "dist": 0.1},
            {"id": "a0x002", "name": "Plaza Two", "city": "Dallas", "dist": 0.2},
        ]

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([{
                "toolUseId": "call-1",
                "name": "search_records",
                "input": {"object_type": "property", "filters": {"city": "Dallas"}},
            }]),
            _end_turn_response(
                "I found Tower One and Plaza Two in Dallas."
            ),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("Find properties in Dallas")

        assert result.answer == "I found Tower One and Plaza Two in Dallas."
        assert result.tool_calls_made == 1
        assert result.turns == 2
        # Backend search should have been called.
        backend.search.assert_called_once()

    def test_tool_results_sent_back_to_claude(self):
        backend = _make_backend()
        backend.search.return_value = [
            {"id": "a0x001", "name": "Tower One", "dist": 0.1},
        ]

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([{
                "toolUseId": "call-1",
                "name": "search_records",
                "input": {"object_type": "property"},
            }]),
            _end_turn_response("Done."),
        ]

        handler = _make_handler(bedrock, backend)
        handler.query("Find properties")

        # NOTE: messages is a mutable list passed by reference. By the time
        # we inspect call_args_list it contains ALL messages (including those
        # appended after the second converse call returned).  The second call
        # was made when messages had 3 entries: [user, assistant, tool_result].
        # After the call, the end_turn assistant message is appended (index 3).
        final_messages = bedrock.converse.call_args_list[1][1]["messages"]
        # The tool result is at index 2 (user question=0, assistant=1, tool_result=2).
        tool_result_msg = final_messages[2]
        assert tool_result_msg["role"] == "user"
        assert "toolResult" in tool_result_msg["content"][0]
        assert tool_result_msg["content"][0]["toolResult"]["toolUseId"] == "call-1"


# =========================================================================
# 3. Parallel tool calls
# =========================================================================

class TestParallelToolCalls:
    """Bedrock returns 2 tool_use blocks in one response."""

    def test_both_tools_dispatched(self):
        backend = _make_backend()
        backend.search.return_value = [
            {"id": "a0x001", "name": "Tower One", "dist": 0.1},
        ]
        backend.aggregate.return_value = {"count": 42}

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([
                {
                    "toolUseId": "call-1",
                    "name": "search_records",
                    "input": {"object_type": "property", "filters": {"city": "Dallas"}},
                },
                {
                    "toolUseId": "call-2",
                    "name": "aggregate_records",
                    "input": {"object_type": "property", "aggregate": "count"},
                },
            ]),
            _end_turn_response("There are 42 properties. Tower One is notable."),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("How many properties in Dallas? Show me some.")

        assert result.tool_calls_made == 2
        assert result.turns == 2
        backend.search.assert_called_once()
        backend.aggregate.assert_called_once()

    def test_both_tool_results_in_same_message(self):
        backend = _make_backend()
        backend.search.return_value = []
        backend.aggregate.return_value = {"count": 0}

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([
                {
                    "toolUseId": "call-1",
                    "name": "search_records",
                    "input": {"object_type": "property"},
                },
                {
                    "toolUseId": "call-2",
                    "name": "aggregate_records",
                    "input": {"object_type": "property", "aggregate": "count"},
                },
            ]),
            _end_turn_response("No results found."),
        ]

        handler = _make_handler(bedrock, backend)
        handler.query("Search and count")

        # messages is mutated in place; index 2 is the tool_result message
        # (0=user, 1=assistant tool_use, 2=user tool_result, 3=assistant end_turn).
        final_messages = bedrock.converse.call_args_list[1][1]["messages"]
        tool_result_msg = final_messages[2]
        assert tool_result_msg["role"] == "user"
        # Both tool results should be in the same message.
        assert len(tool_result_msg["content"]) == 2
        tool_use_ids = {
            tr["toolResult"]["toolUseId"]
            for tr in tool_result_msg["content"]
        }
        assert tool_use_ids == {"call-1", "call-2"}


# =========================================================================
# 4. Sequential tool calls (multi-step)
# =========================================================================

class TestSequentialToolCalls:
    """Bedrock returns tool_use, then another tool_use, then end_turn."""

    def test_three_bedrock_calls(self):
        backend = _make_backend()
        backend.search.return_value = [
            {"id": "a0x001", "name": "Tower One", "dist": 0.1},
        ]
        backend.aggregate.return_value = {"count": 5}

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            # Turn 1: search for leases
            _tool_use_response([{
                "toolUseId": "call-1",
                "name": "search_records",
                "input": {"object_type": "lease", "filters": {}},
            }]),
            # Turn 2: aggregate based on results
            _tool_use_response([{
                "toolUseId": "call-2",
                "name": "aggregate_records",
                "input": {"object_type": "property", "aggregate": "count"},
            }]),
            # Turn 3: final answer
            _end_turn_response("Found 5 properties with expiring leases."),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("Which properties have expiring leases?")

        assert result.turns == 3
        assert result.tool_calls_made == 2
        assert bedrock.converse.call_count == 3


# =========================================================================
# 5. Max turns safety
# =========================================================================

class TestMaxTurnsSafety:
    """Verify handler stops after MAX_TURNS even if Claude keeps calling tools."""

    def test_stops_at_max_turns(self):
        backend = _make_backend()
        backend.search.return_value = [
            {"id": "a0x001", "name": "Tower One", "dist": 0.1},
        ]

        # Claude always wants more tool calls -- never says end_turn.
        infinite_tool = _tool_use_response([{
            "toolUseId": "call-loop",
            "name": "search_records",
            "input": {"object_type": "property"},
        }])

        bedrock = MagicMock()
        bedrock.converse.return_value = infinite_tool

        handler = _make_handler(bedrock, backend)
        result = handler.query("This will loop forever")

        assert result.turns == MAX_TURNS
        assert result.tool_calls_made == MAX_TURNS
        assert bedrock.converse.call_count == MAX_TURNS

    def test_max_turns_still_returns_result(self):
        backend = _make_backend()

        infinite_tool = _tool_use_response([{
            "toolUseId": "call-loop",
            "name": "search_records",
            "input": {"object_type": "property"},
        }])

        bedrock = MagicMock()
        bedrock.converse.return_value = infinite_tool

        handler = _make_handler(bedrock, backend)
        result = handler.query("Infinite loop")

        assert isinstance(result, QueryResult)
        # Should extract text from the last tool_use response's text block.
        assert isinstance(result.answer, str)


# =========================================================================
# 6. Tool error handling
# =========================================================================

class TestToolErrorHandling:
    """Dispatcher returns {"error": "..."} -- fed back to Claude."""

    def test_error_forwarded_as_tool_result(self):
        backend = _make_backend()
        # Dispatcher will return an error for unknown tool.
        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([{
                "toolUseId": "call-err",
                "name": "unknown_tool",
                "input": {},
            }]),
            _end_turn_response("Sorry, that tool is not available."),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("Use an unknown tool")

        assert result.turns == 2
        assert result.tool_calls_made == 1
        # Verify the error was passed back as a tool result (index 2 in
        # the mutated messages list).
        final_messages = bedrock.converse.call_args_list[1][1]["messages"]
        tool_result_msg = final_messages[2]
        tool_result_content = tool_result_msg["content"][0]["toolResult"]["content"][0]["json"]
        assert "error" in tool_result_content

    def test_field_validation_error(self):
        backend = _make_backend()
        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([{
                "toolUseId": "call-bad",
                "name": "search_records",
                "input": {
                    "object_type": "property",
                    "filters": {"nonexistent_field": "value"},
                },
            }]),
            _end_turn_response("I could not find that field. Let me try differently."),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("Search by invalid field")

        assert result.turns == 2
        # The error result should have been sent back to Claude (index 2).
        final_messages = bedrock.converse.call_args_list[1][1]["messages"]
        tool_result_msg = final_messages[2]
        error_json = tool_result_msg["content"][0]["toolResult"]["content"][0]["json"]
        assert "error" in error_json
        assert "nonexistent_field" in error_json["error"]


# =========================================================================
# 7. Citation extraction
# =========================================================================

class TestCitationExtraction:
    """Verify citations collected from search results mentioned in answer."""

    def test_citations_by_name(self):
        backend = _make_backend()
        backend.search.return_value = [
            {"id": "a0x001", "name": "Tower One", "city": "Dallas", "dist": 0.1},
            {"id": "a0x002", "name": "Plaza Two", "city": "Dallas", "dist": 0.2},
            {"id": "a0x003", "name": "Hidden Gem", "city": "Dallas", "dist": 0.3},
        ]

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([{
                "toolUseId": "call-1",
                "name": "search_records",
                "input": {"object_type": "property", "filters": {"city": "Dallas"}},
            }]),
            # Answer mentions Tower One and Plaza Two but NOT Hidden Gem.
            _end_turn_response(
                "The top properties in Dallas are Tower One (Class A) "
                "and Plaza Two (Class B)."
            ),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("Top properties in Dallas")

        # All search results are included as citations so the LWC can
        # build a complete hyperlink map for any record name in the answer.
        assert len(result.citations) == 3
        cited_names = {c["name"] for c in result.citations}
        assert cited_names == {"Tower One", "Plaza Two", "Hidden Gem"}
        cited_ids = {c["id"] for c in result.citations}
        assert cited_ids == {"a0x001", "a0x002", "a0x003"}

    def test_citations_by_id(self):
        backend = _make_backend()
        backend.search.return_value = [
            {"id": "a0x001", "name": "Tower One", "dist": 0.1},
        ]

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([{
                "toolUseId": "call-1",
                "name": "search_records",
                "input": {"object_type": "property"},
            }]),
            _end_turn_response("Record a0x001 is a notable property."),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("Find property a0x001")

        assert len(result.citations) == 1
        assert result.citations[0]["id"] == "a0x001"

    def test_no_citations_when_no_search_results(self):
        bedrock = MagicMock()
        bedrock.converse.return_value = _end_turn_response("No data found.")
        handler = _make_handler(bedrock)
        result = handler.query("Random question")

        assert result.citations == []

    def test_no_duplicate_citations(self):
        backend = _make_backend()
        # Simulate two search calls returning overlapping results.
        backend.search.side_effect = [
            [
                {"id": "a0x001", "name": "Tower One", "dist": 0.1},
            ],
            [
                {"id": "a0x001", "name": "Tower One", "dist": 0.15},
                {"id": "a0x002", "name": "Plaza Two", "dist": 0.2},
            ],
        ]

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([{
                "toolUseId": "call-1",
                "name": "search_records",
                "input": {"object_type": "property"},
            }]),
            _tool_use_response([{
                "toolUseId": "call-2",
                "name": "search_records",
                "input": {"object_type": "property", "filters": {"city": "Dallas"}},
            }]),
            _end_turn_response(
                "Tower One and Plaza Two are great properties."
            ),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("Multi-step search")

        # a0x001 should appear only once despite being in both result sets.
        ids = [c["id"] for c in result.citations]
        assert ids.count("a0x001") == 1
        assert len(result.citations) == 2

    def test_aggregate_calls_do_not_produce_citations(self):
        backend = _make_backend()
        backend.aggregate.return_value = {"count": 42}

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([{
                "toolUseId": "call-1",
                "name": "aggregate_records",
                "input": {"object_type": "property", "aggregate": "count"},
            }]),
            _end_turn_response("There are 42 properties."),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("Count properties")

        assert result.citations == []

    def test_citations_by_subject_fallback(self):
        """Task records have subject instead of name — should still produce citations.

        Uses _extract_citations directly to avoid needing Task in the field registry.
        """
        from lib.query_handler import QueryHandler

        search_results = [
            {"id": "00T001", "subject": "Follow up with tenant", "dist": 0.1},
            {"id": "00T002", "subject": "Send proposal", "dist": 0.2},
        ]
        answer = "You have a task: Follow up with tenant."

        citations = QueryHandler._extract_citations(answer, search_results)

        # All search results become citations for the LWC hyperlink map.
        assert len(citations) == 2
        assert citations[0]["id"] == "00T001"
        assert citations[0]["name"] == "Follow up with tenant"
        assert citations[1]["id"] == "00T002"
        assert citations[1]["name"] == "Send proposal"

    def test_citations_prefer_name_over_subject(self):
        """When both name and subject exist, name should be used."""
        from lib.query_handler import QueryHandler

        search_results = [
            {"id": "a0x001", "name": "Tower One", "subject": "Task subject", "dist": 0.1},
        ]
        answer = "Tower One is a great property."

        citations = QueryHandler._extract_citations(answer, search_results)

        assert len(citations) == 1
        assert citations[0]["name"] == "Tower One"


# =========================================================================
# 8. QueryResult structure
# =========================================================================

class TestQueryResultStructure:
    """Verify all fields of QueryResult are populated correctly."""

    def test_all_fields_populated(self):
        backend = _make_backend()
        backend.search.return_value = [
            {"id": "a0x001", "name": "Tower One", "dist": 0.1},
        ]

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([{
                "toolUseId": "call-1",
                "name": "search_records",
                "input": {"object_type": "property"},
            }]),
            _end_turn_response("Tower One is in Dallas."),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("Find properties")

        assert isinstance(result, QueryResult)
        assert isinstance(result.answer, str)
        assert len(result.answer) > 0
        assert isinstance(result.citations, list)
        assert isinstance(result.tool_calls_made, int)
        assert result.tool_calls_made == 1
        assert isinstance(result.turns, int)
        assert result.turns == 2

    def test_defaults(self):
        """QueryResult defaults are sensible."""
        qr = QueryResult(answer="test")
        assert qr.answer == "test"
        assert qr.citations == []
        assert qr.tool_calls_made == 0
        assert qr.turns == 0

    def test_multi_text_blocks_concatenated(self):
        """If Claude sends multiple text blocks, they're joined."""
        bedrock = MagicMock()
        bedrock.converse.return_value = {
            "stopReason": "end_turn",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "Part one."},
                        {"text": "Part two."},
                    ],
                }
            },
        }

        handler = _make_handler(bedrock)
        result = handler.query("Multi-block response")

        assert result.answer == "Part one.\nPart two."


# =========================================================================
# 9. Edge cases
# =========================================================================

class TestEdgeCases:
    """Additional edge cases and robustness checks."""

    def test_empty_tool_definitions(self):
        """Handler works even if no tool definitions provided."""
        bedrock = MagicMock()
        bedrock.converse.return_value = _end_turn_response("Simple answer.")
        backend = _make_backend()
        registry = build_field_registry(SAMPLE_CONFIG)

        handler = QueryHandler(
            bedrock_client=bedrock,
            backend=backend,
            namespace=NAMESPACE,
            field_registry=registry,
            system_prompt=SYSTEM_PROMPT,
            tool_definitions=[],
        )
        result = handler.query("Simple question")

        assert result.answer == "Simple answer."
        # toolConfig should not be included when tool_definitions is empty.
        call_kwargs = bedrock.converse.call_args[1]
        assert "toolConfig" not in call_kwargs

    def test_unexpected_stop_reason(self):
        """Unexpected stopReason treated as end_turn."""
        bedrock = MagicMock()
        bedrock.converse.return_value = {
            "stopReason": "max_tokens",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": "Truncated answer..."}],
                }
            },
        }

        handler = _make_handler(bedrock)
        result = handler.query("Long question")

        assert result.answer == "Truncated answer..."
        assert result.turns == 1

    def test_message_history_grows_correctly(self):
        """Verify messages accumulate correctly across turns."""
        backend = _make_backend()
        backend.search.return_value = [
            {"id": "a0x001", "name": "Test", "dist": 0.1},
        ]

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            _tool_use_response([{
                "toolUseId": "call-1",
                "name": "search_records",
                "input": {"object_type": "property"},
            }]),
            _end_turn_response("Done."),
        ]

        handler = _make_handler(bedrock, backend)
        handler.query("Test")

        # messages is a mutable list; by the time we inspect it after the
        # handler returns, it has all 4 entries:
        #   0: user question
        #   1: assistant tool_use
        #   2: user tool_result
        #   3: assistant end_turn
        # But at the time the second converse call was made, messages had
        # 3 entries (0-2).  We verify all 4 are present and correctly ordered.
        final_messages = bedrock.converse.call_args_list[1][1]["messages"]
        assert len(final_messages) == 4
        assert final_messages[0]["role"] == "user"
        assert final_messages[1]["role"] == "assistant"
        assert final_messages[2]["role"] == "user"
        assert "toolResult" in final_messages[2]["content"][0]
        assert final_messages[3]["role"] == "assistant"

    def test_tool_input_missing_defaults_to_empty_dict(self):
        """Tool call with no 'input' key should default to empty dict."""
        backend = _make_backend()

        bedrock = MagicMock()
        bedrock.converse.side_effect = [
            {
                "stopReason": "tool_use",
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"text": "Let me check."},
                            {
                                "toolUse": {
                                    "toolUseId": "call-noinput",
                                    "name": "search_records",
                                    # No 'input' key at all
                                }
                            },
                        ],
                    }
                },
            },
            _end_turn_response("Could not search without parameters."),
        ]

        handler = _make_handler(bedrock, backend)
        result = handler.query("No input test")

        # Should not crash -- the error is handled gracefully.
        assert result.turns == 2
        assert result.tool_calls_made == 1
