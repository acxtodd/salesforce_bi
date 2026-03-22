"""Query Lambda handler with SSE streaming (Task 1.1.3).

Lambda Function URL handler that wraps :class:`~lib.query_handler.QueryHandler`
and returns the answer as a Server-Sent Events (SSE) stream.

Request format::

    POST /query
    {
        "question": "Find Class A office buildings in Dallas",
        "org_id": "00Ddl000003yx57EAA",
        "session_id": "optional-session-id"
    }

Response: ``text/event-stream`` with event types ``token``, ``citations``,
``done``, and ``error``.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import boto3
import yaml

from lib.query_handler import QueryHandler, QueryResult
from lib.search_backend import SearchBackend
from lib.tool_dispatch import build_field_registry
from lib.turbopuffer_backend import TurbopufferBackend

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# ---------------------------------------------------------------------------
# Module-level initialisation (runs once on Lambda cold start)
# ---------------------------------------------------------------------------

# Config loading: look in standard locations, configurable via env var.
_CONFIG_SEARCH_PATHS = [
    os.getenv("DENORM_CONFIG_PATH", ""),
    "denorm_config.yaml",
    os.path.join(os.path.dirname(__file__), "denorm_config.yaml"),
    os.path.join(os.path.dirname(__file__), "..", "..", "denorm_config.yaml"),
]


def _load_config() -> dict:
    """Load denorm_config.yaml from the first path that exists."""
    for candidate in _CONFIG_SEARCH_PATHS:
        if not candidate:
            continue
        path = Path(candidate).resolve()
        if path.is_file():
            logger.info("Loading denorm config from %s", path)
            with open(path) as fh:
                return yaml.safe_load(fh)
    raise FileNotFoundError(
        "Cannot find denorm_config.yaml. Set DENORM_CONFIG_PATH or place it "
        "in the project root."
    )


_DENORM_CONFIG: dict = _load_config()
_FIELD_REGISTRY: dict = build_field_registry(_DENORM_CONFIG)

from lib.system_prompt import build_system_prompt, build_tool_definitions
_SYSTEM_PROMPT = build_system_prompt(_DENORM_CONFIG)
_TOOL_DEFINITIONS = build_tool_definitions(_DENORM_CONFIG)

# Session warm-cache: tracks session_ids that have already been warmed.
# Resets on Lambda cold start, which is acceptable for POC.
_warmed_sessions: set[str] = set()

# Bedrock model ID, configurable via env var.
_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def format_sse(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event.

    Returns a string like::

        event: token
        data: {"text": "hello"}

    (terminated by two newlines per SSE spec).
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _split_answer_into_chunks(answer: str) -> list[str]:
    """Split an answer into sentence-level chunks for progressive rendering.

    Splits on sentence-ending punctuation followed by a space, or on
    paragraph breaks.  Each chunk retains its trailing whitespace so that
    concatenating all chunks reproduces the original text exactly.
    """
    if not answer:
        return []

    # Split after sentence-ending punctuation + space, keeping the space
    # attached to the preceding chunk.  Also split on paragraph breaks,
    # preserving the newlines so round-trip concatenation is lossless.
    parts = re.split(r"(?<=[.!?] )(?=\S)|(?<=\n\n)(?=\S)", answer)
    # Remove empty strings that may result from consecutive splits.
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------

def _parse_body(event: dict) -> dict:
    """Extract and JSON-decode the request body from a Lambda Function URL event.

    Handles both plain-text and base64-encoded bodies.
    """
    body_raw = event.get("body", "")

    if event.get("isBase64Encoded") and isinstance(body_raw, str):
        body_raw = base64.b64decode(body_raw).decode("utf-8")

    if isinstance(body_raw, dict):
        return body_raw

    return json.loads(body_raw)


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def handler(event: dict, context: Any) -> dict:
    """Lambda Function URL handler for the /query endpoint.

    Parameters
    ----------
    event:
        Lambda Function URL event dict.
    context:
        Lambda context object (unused in POC).

    Returns
    -------
    dict
        Lambda Function URL response with SSE body.
    """
    cors_headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Access-Control-Allow-Origin": "*",
    }

    # --- Parse & validate ------------------------------------------------
    try:
        body = _parse_body(event)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Invalid request body: %s", exc)
        return {
            "statusCode": 400,
            "headers": cors_headers,
            "body": format_sse("error", {"message": "Invalid JSON in request body"}),
        }

    question = body.get("question")
    org_id = body.get("org_id")
    session_id = body.get("session_id", "")
    record_id = body.get("record_id", "")
    record_type = body.get("record_type", "")
    record_name = body.get("record_name", "")
    model_id_override = body.get("model_id", "")
    prior_context = body.get("prior_context")
    if prior_context is not None:
        if (
            not isinstance(prior_context, dict)
            or not isinstance(prior_context.get("query"), str)
            or not isinstance(prior_context.get("answer"), str)
            or not prior_context["query"].strip()
            or not prior_context["answer"].strip()
        ):
            prior_context = None
        else:
            pc_query = prior_context["query"].strip()
            pc_answer = prior_context["answer"].strip()
            if len(pc_query) > 500:
                pc_query = pc_query[:500] + "..."
            if len(pc_answer) > 2000:
                pc_answer = pc_answer[:2000] + "..."
            prior_context = {"query": pc_query, "answer": pc_answer}

    errors: list[str] = []
    if not question or not isinstance(question, str) or not question.strip():
        errors.append("question is required")
    if not org_id or not isinstance(org_id, str) or not org_id.strip():
        errors.append("org_id is required")

    if errors:
        return {
            "statusCode": 400,
            "headers": cors_headers,
            "body": format_sse("error", {"message": "; ".join(errors)}),
        }

    question = question.strip()
    org_id = org_id.strip()
    namespace = f"org_{org_id}"

    # --- Initialise dependencies -----------------------------------------
    try:
        backend: SearchBackend = TurbopufferBackend()
        bedrock_client = boto3.client("bedrock-runtime")
    except Exception as exc:
        logger.error("Failed to initialise backend/bedrock: %s", exc)
        return {
            "statusCode": 500,
            "headers": cors_headers,
            "body": format_sse("error", {"message": "Internal initialisation error"}),
        }

    # --- Cache warm on first request per session -------------------------
    if session_id and session_id not in _warmed_sessions:
        try:
            backend.warm(namespace)
            _warmed_sessions.add(session_id)
            logger.info("Warmed namespace %s for session %s", namespace, session_id)
        except Exception as exc:
            # warm is best-effort
            logger.warning("Warm failed for namespace %s: %s", namespace, exc)
            _warmed_sessions.add(session_id)

    # --- Execute query ---------------------------------------------------
    sse_parts: list[str] = []

    try:
        effective_model = model_id_override.strip() if model_id_override else _MODEL_ID
        qh = QueryHandler(
            bedrock_client=bedrock_client,
            backend=backend,
            namespace=namespace,
            field_registry=_FIELD_REGISTRY,
            model_id=effective_model,
            system_prompt=_SYSTEM_PROMPT,
            tool_definitions=_TOOL_DEFINITIONS,
        )
        # Prepend record context so the LLM knows which record the user is viewing.
        effective_question = question
        if record_name and record_type:
            effective_question = (
                f"[The user is currently viewing a {record_type} record named "
                f'"{record_name}". Use this as context for their question.] '
                f"{question}"
            )
        elif record_id:
            effective_question = (
                f"[The user is viewing Salesforce record {record_id}.] "
                f"{question}"
            )
        result: QueryResult = qh.query(
            effective_question,
            prior_context=prior_context,
        )
    except Exception as exc:
        logger.exception("QueryHandler failed")
        return {
            "statusCode": 500,
            "headers": cors_headers,
            "body": format_sse("error", {"message": f"Query failed: {exc}"}),
        }

    # --- Format answer as token events -----------------------------------
    chunks = _split_answer_into_chunks(result.answer)
    if not chunks and result.answer:
        # Fallback: emit the whole answer as one chunk.
        chunks = [result.answer]

    for chunk in chunks:
        sse_parts.append(format_sse("token", {"text": chunk}))

    # --- Citations event -------------------------------------------------
    if result.citations:
        sse_parts.append(format_sse("citations", {"citations": result.citations}))

    # --- Clarification event ---------------------------------------------
    if result.clarification_options:
        sse_parts.append(format_sse("clarification", {
            "options": result.clarification_options
        }))

    # --- Done event ------------------------------------------------------
    sse_parts.append(
        format_sse("done", {
            "tool_calls": result.tool_calls_made,
            "turns": result.turns,
            "model_id": effective_model,
        })
    )

    return {
        "statusCode": 200,
        "headers": cors_headers,
        "body": "".join(sse_parts),
    }
