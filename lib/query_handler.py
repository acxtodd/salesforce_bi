"""Core query handler: user question -> Claude tool-use -> synthesis (Task 1.1.2).

Orchestrates the multi-turn conversation loop between a user question and
Claude on Bedrock.  Claude decides which tools to call (search_records,
aggregate_records) via Bedrock's Converse API; those calls are dispatched
through :class:`~lib.tool_dispatch.ToolDispatcher` against the
:class:`~lib.search_backend.SearchBackend`.

No streaming -- that is Task 1.1.3.  This handler collects the complete
response before returning.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from lib.search_backend import SearchBackend
from lib.tool_dispatch import ToolDispatcher, build_field_registry

# Attempt to import the system prompt / tool definitions from the sibling
# module being built in parallel.  If it does not exist yet, fall back to
# minimal stubs so this module remains importable and testable.
try:
    from lib.system_prompt import SYSTEM_PROMPT, TOOL_DEFINITIONS
except ImportError:  # pragma: no cover
    SYSTEM_PROMPT = (
        "You are a commercial real-estate search assistant. "
        "Use the provided tools to answer questions about properties, "
        "leases, and availabilities."
    )
    TOOL_DEFINITIONS: list[dict[str, Any]] = []  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

# Safety cap on conversation turns to prevent infinite loops.
MAX_TURNS = 10


# ---------------------------------------------------------------------------
# Clarification extraction
# ---------------------------------------------------------------------------

# Pattern: [CLARIFY:label|query]
_CLARIFY_RE = re.compile(r"\[CLARIFY:([^|\]]+)\|([^\]]+)\]")


def extract_clarifications(answer: str) -> tuple[str, list[dict]]:
    """Extract ``[CLARIFY:label|query]`` markers from an answer.

    Returns ``(clean_answer, options)`` where *clean_answer* has the markers
    stripped and *options* is a list of ``{"label": ..., "query": ...}`` dicts.

    Also catches conversational follow-up offers like "Would you like me to
    search for X?" and converts them into clickable options, since the LWC
    is single-turn and users cannot reply with free text.
    """
    # First, convert conversational follow-ups into CLARIFY markers
    answer = _convert_followup_offers(answer)

    options: list[dict] = []
    for match in _CLARIFY_RE.finditer(answer):
        options.append({
            "label": match.group(1).strip(),
            "query": match.group(2).strip(),
        })
    clean = _CLARIFY_RE.sub("", answer).strip()
    return clean, options


# Patterns that match conversational follow-up offers
_FOLLOWUP_RE = re.compile(
    r"(?:Would you like me to|Shall I|Do you want me to|I can also|Want me to)"
    r"\s+(.+?\?)",
    re.IGNORECASE,
)


def _convert_followup_offers(answer: str) -> str:
    """Convert 'Would you like me to X?' sentences into [CLARIFY:] markers."""
    matches = list(_FOLLOWUP_RE.finditer(answer))
    if not matches:
        return answer

    for match in reversed(matches):  # Reverse to preserve positions
        full_sentence = match.group(0)
        offer_text = match.group(1).rstrip("?").strip()

        # Build a reasonable label and query from the offer
        # e.g., "search for deals involving AscendixRE" -> label + query
        label = offer_text[:60]  # Truncate long labels
        # Capitalize first letter for the query
        query = offer_text[0].upper() + offer_text[1:] if offer_text else offer_text

        clarify_marker = f"\n[CLARIFY:{label}|{query}]"

        # Find the full sentence boundaries (go back to start of sentence)
        start = answer.rfind("\n", 0, match.start())
        if start == -1:
            # Check for sentence start
            start = answer.rfind(". ", 0, match.start())
            if start != -1:
                start += 2
            else:
                start = match.start()
        else:
            start += 1

        end = match.end()
        # Replace the sentence with the clarify marker
        answer = answer[:start] + clarify_marker + answer[end:]

    return answer


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class QueryResult:
    """Complete result of a single user query."""

    answer: str
    """The synthesised answer text produced by Claude."""

    citations: list[dict] = field(default_factory=list)
    """Records referenced in the answer.
    Each entry is ``{"id": "a0x...", "name": "Tower One"}``.
    """

    tool_calls_made: int = 0
    """Total number of tool calls dispatched across all turns."""

    turns: int = 0
    """Number of Bedrock Converse API calls made."""

    tools_used: list[str] = field(default_factory=list)
    """Names of tools that were actually called (e.g. ["search_records"])."""

    search_result_count: int = 0
    """Total number of records returned by search_records calls."""

    write_proposal: dict | None = None
    """Structured write proposal returned by propose_edit, if any."""

    tool_call_log: list[dict] = field(default_factory=list)
    """Log of each tool call: {"name", "input", "result_count", "has_error", "error", "duration_s", "turn"}."""

    turn_durations: list[float] = field(default_factory=list)
    """Duration of each Bedrock Converse API call in seconds."""

    clarification_options: list[dict] = field(default_factory=list)
    """Clickable clarification options for ambiguous queries.
    Each entry is ``{"label": "By deal count", "query": "Show top 5 markets by deal count"}``."""


# ---------------------------------------------------------------------------
# Query handler
# ---------------------------------------------------------------------------

class QueryHandler:
    """Core query handler: user question -> Claude tool-use -> synthesis.

    Parameters
    ----------
    bedrock_client:
        A ``boto3`` ``bedrock-runtime`` client (or compatible mock).
    backend:
        A :class:`SearchBackend` implementation (e.g. ``TurbopufferBackend``).
    namespace:
        Turbopuffer namespace for the org (e.g. ``"org_00Ddl000003yx57EAA"``).
    field_registry:
        Output of :func:`build_field_registry`.
    model_id:
        Bedrock model identifier.
    system_prompt:
        Override for the system prompt text (mainly useful for testing).
    tool_definitions:
        Override for the Converse-API tool definitions list.
    """

    def __init__(
        self,
        bedrock_client: Any,
        backend: SearchBackend,
        namespace: str,
        field_registry: dict,
        model_id: str = "us.anthropic.claude-sonnet-4-20250514-v1:0",
        *,
        system_prompt: str | None = None,
        tool_definitions: list[dict] | None = None,
    ) -> None:
        self._client = bedrock_client
        self._model_id = model_id
        self._dispatcher = ToolDispatcher(backend, namespace, field_registry)
        self._system_prompt = system_prompt or SYSTEM_PROMPT
        self._tool_definitions = tool_definitions if tool_definitions is not None else TOOL_DEFINITIONS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(
        self,
        question: str,
        *,
        prior_context: dict[str, str] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> QueryResult:
        """Execute a user question through the Claude tool-use loop.

        Returns a :class:`QueryResult` with the final answer, citations,
        and execution metadata.
        """
        messages: list[dict[str, Any]] = []
        if conversation_history is not None:
            history = conversation_history
        elif prior_context:
            history = [prior_context]
        else:
            history = []

        for exchange in history:
            if not isinstance(exchange, dict):
                continue

            exchange_query = exchange.get("query")
            exchange_answer = exchange.get("answer")
            if not isinstance(exchange_query, str) or not isinstance(exchange_answer, str):
                continue

            exchange_query = exchange_query.strip()
            exchange_answer = exchange_answer.strip()
            if not exchange_query or not exchange_answer:
                continue

            messages.append({"role": "user", "content": [{"text": exchange_query}]})
            messages.append({"role": "assistant", "content": [{"text": exchange_answer}]})
        messages.append({"role": "user", "content": [{"text": question}]})

        tool_calls_made = 0
        turns = 0
        all_search_results: list[dict] = []
        tools_used: list[str] = []
        search_result_count = 0
        write_proposal: dict | None = None
        tool_call_log: list[dict] = []
        turn_durations: list[float] = []

        while turns < MAX_TURNS:
            # --- Call Bedrock Converse API ---
            converse_kwargs: dict[str, Any] = {
                "modelId": self._model_id,
                "messages": messages,
                "system": [{"text": self._system_prompt}],
            }
            if self._tool_definitions:
                converse_kwargs["toolConfig"] = {"tools": self._tool_definitions}

            turn_start = time.perf_counter()
            response = self._client.converse(**converse_kwargs)
            turn_duration = time.perf_counter() - turn_start
            turns += 1
            turn_durations.append(round(turn_duration, 3))

            stop_reason = response.get("stopReason", "end_turn")
            assistant_message = response["output"]["message"]

            # Always append Claude's response to the conversation.
            messages.append(assistant_message)

            if stop_reason == "end_turn":
                # Claude is done -- extract final text.
                raw_answer = self._extract_text(assistant_message)
                answer, clarification_options = extract_clarifications(raw_answer)
                citations = self._extract_citations(answer, all_search_results)
                return QueryResult(
                    answer=answer,
                    citations=citations,
                    tool_calls_made=tool_calls_made,
                    turns=turns,
                    tools_used=tools_used,
                    search_result_count=search_result_count,
                    write_proposal=write_proposal,
                    tool_call_log=tool_call_log,
                    turn_durations=turn_durations,
                    clarification_options=clarification_options,
                )

            if stop_reason == "tool_use":
                # Process every tool_use block in the response (may be
                # parallel -- Claude can emit multiple tool calls at once).
                tool_use_blocks = [
                    block for block in assistant_message["content"]
                    if "toolUse" in block
                ]

                tool_result_contents: list[dict[str, Any]] = []

                for block in tool_use_blocks:
                    tool_use = block["toolUse"]
                    tool_use_id = tool_use["toolUseId"]
                    tool_name = tool_use["name"]
                    tool_input = tool_use.get("input", {})

                    logger.debug(
                        "Dispatching tool %s (id=%s) with input %s",
                        tool_name, tool_use_id, tool_input,
                    )

                    dispatch_start = time.perf_counter()
                    dispatch_result = self._dispatcher.dispatch(
                        {"name": tool_name, "parameters": tool_input}
                    )
                    dispatch_duration = time.perf_counter() - dispatch_start

                    tool_calls_made += 1
                    tools_used.append(tool_name)

                    result_count = len(dispatch_result.get("results", []))
                    if "write_proposal" in dispatch_result:
                        proposal_fields = dispatch_result["write_proposal"].get("fields", [])
                        result_count = len(proposal_fields)
                        if write_proposal is None:
                            write_proposal = dispatch_result["write_proposal"]

                    tool_call_log.append({
                        "name": tool_name,
                        "input": tool_input,
                        "result_count": result_count,
                        "has_error": "error" in dispatch_result,
                        "error": dispatch_result.get("error", ""),
                        "duration_s": round(dispatch_duration, 3),
                        "turn": turns,
                    })

                    # Collect search results for citation extraction.
                    if tool_name == "search_records" and "results" in dispatch_result:
                        all_search_results.extend(dispatch_result["results"])
                        search_result_count += len(dispatch_result["results"])
                    # Collect record IDs from aggregate results for citation linking.
                    if tool_name == "aggregate_records":
                        agg_result = dispatch_result.get("result", {})
                        if "_records" in agg_result:
                            all_search_results.extend(agg_result["_records"])

                    tool_result_contents.append({
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"json": dispatch_result}],
                        }
                    })

                # Append tool results as a user message.
                messages.append({
                    "role": "user",
                    "content": tool_result_contents,
                })
            else:
                # Unexpected stop reason -- treat as end.
                logger.warning("Unexpected stopReason: %s", stop_reason)
                answer = self._extract_text(assistant_message)
                return QueryResult(
                    answer=answer,
                    citations=[],
                    tool_calls_made=tool_calls_made,
                    turns=turns,
                    tools_used=tools_used,
                    search_result_count=search_result_count,
                    write_proposal=write_proposal,
                    tool_call_log=tool_call_log,
                    turn_durations=turn_durations,
                )

        # Exhausted MAX_TURNS -- return whatever we have.
        logger.warning("Hit MAX_TURNS (%d) safety limit", MAX_TURNS)
        answer = self._extract_text(messages[-1]) if messages else ""
        citations = self._extract_citations(answer, all_search_results)
        return QueryResult(
            answer=answer,
            citations=citations,
            tool_calls_made=tool_calls_made,
            turns=turns,
            tools_used=tools_used,
            search_result_count=search_result_count,
            write_proposal=write_proposal,
            tool_call_log=tool_call_log,
            turn_durations=turn_durations,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(message: dict) -> str:
        """Pull concatenated text from a Converse API message."""
        parts: list[str] = []
        for block in message.get("content", []):
            if "text" in block:
                parts.append(block["text"])
        return "\n".join(parts)

    @staticmethod
    def _extract_citations(
        answer: str,
        search_results: list[dict],
    ) -> list[dict]:
        """Build citation list from search results referenced in the answer.

        All search results are included as citations so the LWC can build
        a complete hyperlink map.  The LWC linkification regex handles
        which names actually get linked in the rendered answer.
        Duplicates (by id) are removed.
        """
        if not search_results:
            return []

        seen_ids: set[str] = set()
        citations: list[dict] = []

        for record in search_results:
            record_id = record.get("id", "")
            # Some objects (e.g. Task) use "subject" instead of "name"
            record_name = record.get("name", "") or record.get("subject", "")

            if not record_id or record_id in seen_ids:
                continue

            citations.append({"id": record_id, "name": record_name})
            seen_ids.add(record_id)

        return citations
