"""FastAPI wrapper for the /query Lambda (Task 2.5.1).

Mirrors the answer Lambda's Docker + LWA pattern to enable SSE streaming
via Lambda Function URL with RESPONSE_STREAM invoke mode.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

import boto3
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from index import _parse_body, handler

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI()


# ---------------------------------------------------------------------------
# API key auth — mirrors lambda/answer/main.py
# ---------------------------------------------------------------------------


class ApiKeyError(Exception):
    """Raised when API key cannot be retrieved or validated."""
    pass


@lru_cache(maxsize=1)
def _get_api_key() -> str:
    """Retrieve API key from Secrets Manager (cached after first call).

    Falls back to API_KEY env var for local dev. Fails closed if neither
    is configured.
    """
    secret_arn = os.getenv("API_KEY_SECRET_ARN")

    if not secret_arn:
        api_key = os.getenv("API_KEY", "")
        if not api_key:
            raise ApiKeyError(
                "API_KEY_SECRET_ARN not configured and API_KEY env var not set"
            )
        return api_key

    try:
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_arn)
        secret_data = json.loads(response.get("SecretString", "{}"))
        api_key = secret_data.get("apiKey", "")
        if not api_key:
            raise ApiKeyError("apiKey field missing or empty in secret")
        return api_key
    except ApiKeyError:
        raise
    except Exception as exc:
        logger.error("Failed to retrieve API key from Secrets Manager: %s", exc)
        raise ApiKeyError(f"Failed to retrieve API key: {exc}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/query")
@app.post("/")
async def query(
    request: Request,
    x_api_key: str = Header(None, alias="x-api-key"),
):
    # Auth check — fail closed
    if not x_api_key:
        logger.warning("Missing x-api-key header")
        raise HTTPException(status_code=401, detail="Unauthorized - API key required")

    try:
        expected_key = _get_api_key()
    except ApiKeyError as exc:
        logger.error("API key configuration error: %s", exc)
        raise HTTPException(status_code=500, detail="Server configuration error")

    if x_api_key != expected_key:
        logger.warning("Invalid API key provided")
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Dispatch to handler
    body = await request.json()
    event = {"body": json.dumps(body)}
    result = handler(event, None)

    async def generate():
        yield result["body"]

    return StreamingResponse(
        generate(),
        status_code=result["statusCode"],
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
        },
    )
