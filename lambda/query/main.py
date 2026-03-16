"""FastAPI wrapper for the /query Lambda (Task 2.5.1).

Mirrors the answer Lambda's Docker + LWA pattern to enable SSE streaming
via Lambda Function URL with RESPONSE_STREAM invoke mode.
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from index import _parse_body, handler

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI()


@app.post("/query")
@app.post("/")
async def query(request: Request):
    body = await request.json()
    # Build a Lambda-like event dict
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
