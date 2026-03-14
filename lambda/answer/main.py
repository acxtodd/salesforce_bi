from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import StreamingResponse
import uvicorn
import os
import json
import logging
import time
import boto3
from functools import lru_cache
# Import helpers from index.py (which we will use as logic library)
# We need to make sure index.py is importable.
from index import (
    _parse_request, 
    _invoke_retrieve_lambda, 
    _stream_bedrock_answer, 
    _extract_citations, 
    _validate_citations, 
    _persist_session_async, 
    _format_sse_event,
    _build_system_prompt,
    _build_context_string,
    _build_user_prompt,
    RetrievalError, 
    BedrockError, 
    ValidationError
)

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

app = FastAPI()


class ApiKeyError(Exception):
    """Raised when API key cannot be retrieved or validated."""
    pass


@lru_cache(maxsize=1)
def _get_api_key_from_secrets_manager() -> str:
    """
    Retrieve API key from Secrets Manager.

    **Feature: zero-config-production, Task 28.1**
    **Security Fix: graph-aware-zero-config-retrieval, Task 23 - QA Finding #3**

    Securely retrieve API key from Secrets Manager instead of environment variable.
    Uses LRU cache to avoid repeated API calls during Lambda warm starts.

    SECURITY: This function now fails closed - raises ApiKeyError if key cannot
    be retrieved, rather than returning empty string which bypasses auth.

    Returns:
        API key string

    Raises:
        ApiKeyError: If API key cannot be retrieved from any source
    """
    secret_arn = os.getenv("API_KEY_SECRET_ARN")

    # Fallback to direct API_KEY env var for backward compatibility during migration
    if not secret_arn:
        api_key = os.getenv("API_KEY", "")
        if not api_key:
            raise ApiKeyError("API_KEY_SECRET_ARN not configured and API_KEY env var not set")
        return api_key

    try:
        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_arn)
        secret_string = response.get("SecretString", "{}")
        secret_data = json.loads(secret_string)
        api_key = secret_data.get("apiKey", "")
        if not api_key:
            raise ApiKeyError("apiKey field missing or empty in secret")
        return api_key
    except ApiKeyError:
        raise
    except Exception as e:
        logger.error("Failed to retrieve API key from Secrets Manager: %s", e)
        raise ApiKeyError(f"Failed to retrieve API key: {e}")


@app.post("/answer")
@app.post("/")
async def answer(request: Request, x_api_key: str = Header(None, alias="x-api-key")):
    # 1. Auth Check (API Key from Secrets Manager)
    # **Feature: zero-config-production, Task 28.1**
    # **Security Fix: graph-aware-zero-config-retrieval, Task 23 - QA Finding #3**
    # SECURITY: Fail-closed authentication - reject if:
    # - x-api-key header is missing
    # - API key cannot be retrieved from secrets/env
    # - API key doesn't match

    # Check header presence first
    if not x_api_key:
        logger.warning("Missing x-api-key header")
        raise HTTPException(status_code=401, detail="Unauthorized - API key required")

    # Get expected key (raises ApiKeyError if not configured)
    try:
        expected_key = _get_api_key_from_secrets_manager()
    except ApiKeyError as e:
        logger.error("API key configuration error: %s", e)
        raise HTTPException(status_code=500, detail="Server configuration error")

    # Validate key
    if x_api_key != expected_key:
        logger.warning("Invalid API key provided")
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2. Parse Request
    try:
        body = await request.json()
        # _parse_request expects a dict that looks like an event body or the body dict itself
        # It handles both. We pass the dict directly.
        request_payload = _parse_request(body)
    except ValidationError as exc:
        logger.warning("Validation error: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as exc:
        logger.warning("Request parsing error: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid Request")

    logger.info(
        "Processing answer request: sessionId=%s, query=%s",
        request_payload["sessionId"],
        request_payload["query"][:100]
    )

    # Generator for StreamingResponse
    async def generate_stream():
        start = time.perf_counter()
        
        # 3. Retrieve Context
        retrieve_start = time.perf_counter()
        try:
            retrieval_response = _invoke_retrieve_lambda(
                query=request_payload["query"],
                salesforce_user_id=request_payload["salesforceUserId"],
                top_k=request_payload["topK"],
                record_context=request_payload["recordContext"],
            )
            matches = retrieval_response.get("matches", [])
            retrieve_ms = round((time.perf_counter() - retrieve_start) * 1000, 2)
            # Extract retrieve component metrics for detailed tracing
            retrieve_trace = retrieval_response.get("trace", {})
            logger.info("Retrieved %d context chunks in %dms", len(matches), retrieve_ms)
        except RetrievalError as exc:
            logger.error("Retrieval failed: %s", exc)
            yield _format_sse_event("error", {"error": f"Failed to retrieve context: {str(exc)}"})
            return
        except Exception as exc:
             logger.error("Unexpected retrieval error: %s", exc)
             yield _format_sse_event("error", {"error": "Internal retrieval error"})
             return

        # Check context
        if not matches:
            logger.warning("No context retrieved for query")
            yield _format_sse_event("token", {"token": "I don't have enough information to answer that question."})
            no_match_trace = {
                "retrieveMs": retrieve_ms,
                "totalMs": round((time.perf_counter() - start) * 1000, 2)
            }
            if retrieve_trace:
                no_match_trace["retrieveComponents"] = {
                    "intentMs": retrieve_trace.get("intentMs", 0),
                    "plannerMs": retrieve_trace.get("plannerMs", 0),
                    "cached": retrieve_trace.get("cached", False),
                }
            yield _format_sse_event("done", {
                "reason": "no_accessible_results",
                "trace": no_match_trace
            })
            return

        # Extract queryPlan for debug output
        query_plan = retrieval_response.get("queryPlan", {})

        # 4. Build Prompts
        prompt_start = time.perf_counter()
        system_prompt = _build_system_prompt(request_payload["policy"])
        context_string = _build_context_string(matches)
        user_prompt = _build_user_prompt(request_payload["query"], context_string)
        prompt_ms = round((time.perf_counter() - prompt_start) * 1000, 2)
        logger.info("Built prompts in %dms", prompt_ms)

        # Send debug event with query intent/decomposition if enabled
        if request_payload.get("debug") and query_plan:
            debug_info = {
                "schemaDecomposition": query_plan.get("schemaDecomposition", {}),
                "intentClassification": query_plan.get("intentClassification", {}),
                "intentDetection": query_plan.get("intentDetection", {}),
                "planner": {
                    "targetObject": query_plan.get("planner", {}).get("targetObject"),
                    "predicates": query_plan.get("planner", {}).get("predicates", []),
                    "confidence": query_plan.get("planner", {}).get("confidence"),
                },
                "aggregation": query_plan.get("aggregation", {}),
                "matchCount": len(matches),
            }
            yield _format_sse_event("debug", debug_info)
            logger.info("[DEBUG] Query intent: %s", json.dumps(debug_info, default=str)[:500])

        # 5. Generate Answer
        generate_start = time.perf_counter()
        full_answer = ""
        first_token_ms = None

        try:
            # _stream_bedrock_answer is a synchronous generator (using boto3)
            # In FastAPI async route, we should run it in threadpool or iterate it.
            # Since boto3 is blocking, this blocks the event loop. 
            # For simple lambda usage, it's acceptable, or we can use run_in_executor.
            # But here we just iterate.
            for sse_event, token_text in _stream_bedrock_answer(
                system_prompt,
                user_prompt,
                request_payload["policy"]
            ):
                if first_token_ms is None:
                    first_token_ms = round((time.perf_counter() - generate_start) * 1000, 2)
                    logger.info("First token received in %dms", first_token_ms)
                
                yield sse_event
                full_answer += token_text
            
            generate_ms = round((time.perf_counter() - generate_start) * 1000, 2)
            logger.info("Answer generation completed in %dms", generate_ms)

        except BedrockError as exc:
            logger.error("Bedrock generation failed: %s", exc)
            yield _format_sse_event("error", {"error": f"Failed to generate answer: {str(exc)}"})
            return
        except Exception as exc:
             logger.error("Unexpected bedrock error: %s", exc)
             yield _format_sse_event("error", {"error": "Internal generation error"})
             return

        # 6. Extract and Validate Citations
        citation_start = time.perf_counter()
        extracted_citations = _extract_citations(full_answer)
        valid_citations, invalid_citations = _validate_citations(extracted_citations, matches)
        citation_ms = round((time.perf_counter() - citation_start) * 1000, 2)

        logger.info(
            "Extracted %d citations (%d valid, %d invalid) in %dms",
            len(extracted_citations),
            len(valid_citations),
            len(invalid_citations),
            citation_ms
        )

        if invalid_citations:
            logger.warning("Invalid citations found: %s", invalid_citations)

        # Send citation events
        for citation in valid_citations:
            yield _format_sse_event("citation", citation)

        # 7. Trace and Persist
        total_ms = round((time.perf_counter() - start) * 1000, 2)
        trace = {
            "retrieveMs": retrieve_ms,
            "promptMs": prompt_ms,
            "firstTokenMs": first_token_ms or 0,
            "generateMs": generate_ms,
            "citationMs": citation_ms,
            "totalMs": total_ms,
            "citationCount": len(valid_citations),
            "invalidCitationCount": len(invalid_citations),
        }
        # Include retrieve component metrics for detailed performance analysis
        # These come from the retrieve Lambda's internal trace
        if retrieve_trace:
            trace["retrieveComponents"] = {
                "intentMs": retrieve_trace.get("intentMs", 0),
                "schemaDecompositionMs": retrieve_trace.get("schemaDecompositionMs", 0),
                "plannerMs": retrieve_trace.get("plannerMs", 0),
                "graphFilterMs": retrieve_trace.get("graphFilterMs", 0),
                "crossObjectMs": retrieve_trace.get("crossObjectMs", 0),
                "authzMs": retrieve_trace.get("authzMs", 0),
                "kbQueryMs": retrieve_trace.get("retrieveMs", 0),  # KB query time
                "postFilterMs": retrieve_trace.get("postFilterMs", 0),
                "cached": retrieve_trace.get("cached", False),
                "plannerUsed": retrieve_trace.get("plannerUsed", False),
                "plannerSkipped": retrieve_trace.get("plannerSkipped", False),
            }

        _persist_session_async(
            session_id=request_payload["sessionId"],
            salesforce_user_id=request_payload["salesforceUserId"],
            query=request_payload["query"],
            answer=full_answer,
            citations=valid_citations,
            record_context=request_payload["recordContext"],
            trace=trace
        )

        yield _format_sse_event("done", {
            "citations": valid_citations,
            "trace": trace
        })

    return StreamingResponse(generate_stream(), media_type="text/event-stream")


@app.post("/ingest")
async def ingest(request: Request, x_api_key: str = Header(None, alias="x-api-key")):
    """
    Ingest endpoint for Salesforce batch exports.

    Forwards records to Step Functions ingestion pipeline.

    Expected payload:
    {
        "sobject": "ascendix__Property__c",
        "operation": "upsert",
        "records": [{"Id": "...", "Name": "...", ...}],
        "source": "batch_export",
        "timestamp": "2025-12-06T..."
    }
    """
    # 1. Auth Check
    if not x_api_key:
        logger.warning("Missing x-api-key header on /ingest")
        raise HTTPException(status_code=401, detail="Unauthorized - API key required")

    try:
        expected_key = _get_api_key_from_secrets_manager()
    except ApiKeyError as e:
        logger.error("API key configuration error: %s", e)
        raise HTTPException(status_code=500, detail="Server configuration error")

    if x_api_key != expected_key:
        logger.warning("Invalid API key provided on /ingest")
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2. Parse Request
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Validate required fields
    required_fields = ['sobject', 'records']
    for field in required_fields:
        if field not in body:
            raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

    if not isinstance(body['records'], list):
        raise HTTPException(status_code=400, detail="Field 'records' must be an array")

    if len(body['records']) == 0:
        raise HTTPException(status_code=400, detail="Field 'records' cannot be empty")

    if len(body['records']) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 records per request")

    sobject = body['sobject']
    records = body['records']
    operation = body.get('operation', 'upsert')
    source = body.get('source', 'batch_export')
    timestamp = body.get('timestamp', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))

    logger.info("Ingest request: %d %s records from %s", len(records), sobject, source)

    # 3. Transform records to pipeline format
    pipeline_records = []
    for record in records:
        pipeline_records.append({
            'sobject': sobject,
            'data': record
        })

    # 4. Start Step Functions execution
    sfn_input = {
        'records': pipeline_records,
        'source': source,
        'operation': operation,
        'timestamp': timestamp
    }

    STATE_MACHINE_ARN = os.getenv('STATE_MACHINE_ARN')
    if not STATE_MACHINE_ARN:
        logger.error("STATE_MACHINE_ARN not configured")
        raise HTTPException(status_code=500, detail="Ingestion pipeline not configured")

    try:
        sfn_client = boto3.client('stepfunctions')
        response = sfn_client.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            input=json.dumps(sfn_input)
        )
        execution_arn = response['executionArn']
        logger.info("Started Step Functions execution: %s", execution_arn)

        return {
            'accepted': True,
            'jobId': execution_arn,
            'recordCount': len(records),
            'sobject': sobject
        }

    except Exception as e:
        logger.error("Failed to start Step Functions execution: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to start ingestion: {str(e)}")
