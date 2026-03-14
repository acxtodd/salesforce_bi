"""Answer Lambda handler for /answer endpoint.
Generates streaming answers with citations using Bedrock and retrieval context.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, Generator, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

lambda_client = boto3.client("lambda")
bedrock_runtime_client = boto3.client("bedrock-runtime")
dynamodb = boto3.resource("dynamodb")

DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "8"))
MAX_TOP_K = int(os.getenv("MAX_TOP_K", "20"))
DEFAULT_MAX_TOKENS = int(os.getenv("DEFAULT_MAX_TOKENS", "600"))
DEFAULT_TEMPERATURE = float(os.getenv("DEFAULT_TEMPERATURE", "0.3"))

# Debug mode: show query decomposition/intent in SSE stream
# Set to "true" to enable, or pass debug=true in request
DEBUG_SHOW_INTENT = os.getenv("DEBUG_SHOW_INTENT", "false").lower() == "true"


class ValidationError(Exception):
    """Raised when the request payload is invalid."""


class RetrievalError(Exception):
    """Raised when retrieval from Retrieve Lambda fails."""


class BedrockError(Exception):
    """Raised when Bedrock answer generation fails."""


def _decode_event_body(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract JSON body from an API Gateway event or raw dict."""
    if not isinstance(event, dict):
        raise ValidationError("Event payload must be a dictionary")

    body = event.get("body", event)
    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        if event.get("isBase64Encoded"):
            try:
                decoded = base64.b64decode(body)
                body = decoded.decode("utf-8")
            except Exception as exc:
                raise ValidationError("Unable to decode base64-encoded body") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValidationError("Request body must be valid JSON") from exc

    raise ValidationError("Request body must be a JSON object")


def _validate_salesforce_user(user_id: Any) -> str:
    """Validate Salesforce User ID format."""
    if not isinstance(user_id, str) or not user_id:
        raise ValidationError("salesforceUserId is required")

    trimmed = user_id.strip()
    if not (trimmed.startswith("005") and len(trimmed) in (15, 18)):
        raise ValidationError("salesforceUserId must be a 15 or 18 char ID starting with 005")

    return trimmed


def _parse_request(event: Dict[str, Any]) -> Dict[str, Any]:
    """Parse and validate incoming request payload."""
    payload = _decode_event_body(event)

    # Required fields
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValidationError("query is required")

    salesforce_user_id = _validate_salesforce_user(payload.get("salesforceUserId"))

    # Optional fields
    session_id = payload.get("sessionId")
    if session_id and not isinstance(session_id, str):
        raise ValidationError("sessionId must be a string")
    if not session_id:
        session_id = str(uuid.uuid4())

    top_k_raw = payload.get("topK", DEFAULT_TOP_K)
    try:
        top_k = int(top_k_raw)
    except (ValueError, TypeError) as exc:
        raise ValidationError("topK must be an integer") from exc

    if top_k <= 0:
        raise ValidationError("topK must be greater than zero")
    top_k = min(top_k, MAX_TOP_K)

    record_context = payload.get("recordContext") or {}
    if not isinstance(record_context, dict):
        raise ValidationError("recordContext must be an object if provided")

    # Policy configuration
    policy = payload.get("policy") or {}
    if not isinstance(policy, dict):
        raise ValidationError("policy must be an object if provided")

    max_tokens = policy.get("max_tokens", DEFAULT_MAX_TOKENS)
    try:
        max_tokens = int(max_tokens)
    except (ValueError, TypeError):
        max_tokens = DEFAULT_MAX_TOKENS

    temperature = policy.get("temperature", DEFAULT_TEMPERATURE)
    try:
        temperature = float(temperature)
    except (ValueError, TypeError):
        temperature = DEFAULT_TEMPERATURE

    require_citations = policy.get("require_citations", True)
    if not isinstance(require_citations, bool):
        require_citations = True

    # Debug flag - can be set via request or env var
    debug = payload.get("debug", False)
    if isinstance(debug, str):
        debug = debug.lower() == "true"
    debug = debug or DEBUG_SHOW_INTENT

    return {
        "query": query.strip(),
        "salesforceUserId": salesforce_user_id,
        "sessionId": session_id,
        "topK": top_k,
        "recordContext": record_context,
        "debug": debug,
        "policy": {
            "max_tokens": max_tokens,
            "temperature": temperature,
            "require_citations": require_citations,
        },
    }


def _format_sse_event(event_type: str, data: Any) -> str:
    """Format data as Server-Sent Event."""
    json_data = json.dumps(data) if not isinstance(data, str) else data
    return f"event: {event_type}\ndata: {json_data}\n\n"


def _stream_error(error_message: str) -> str:
    """Format error as SSE event."""
    return _format_sse_event("error", {"error": error_message})


def _build_system_prompt(policy: Dict[str, Any]) -> str:
    """Construct system prompt with grounding policy."""
    require_citations = policy.get("require_citations", True)
    
    prompt = """You are an AI assistant helping Salesforce users find information in their CRM data.

GROUNDING POLICY:
- Answer ONLY using information from the provided context chunks
"""
    
    if require_citations:
        prompt += """- Include paragraph-level citations using [Source: {recordId}] format for all factual claims
- Every factual statement must be supported by a citation
"""
    
    prompt += """- If the context does not contain enough information to answer, say "I don't have enough information to answer that question"
- Do NOT make up information or use knowledge outside the provided context
- Do NOT speculate or provide opinions

"""
    
    if require_citations:
        prompt += """CITATION FORMAT:
- Cite the source record ID after each factual claim
- Use this format: [Source: Opportunity/006xx1]
- For multiple sources: [Source: Opportunity/006xx1, Case/500xx2]
- Always use the full record ID from the context metadata

"""
    
    prompt += """ANSWER STYLE:
- Be concise and direct
- Use Markdown formatting for better readability:
  * Use ## for section headers
  * Use **bold** for emphasis on key terms, amounts, and important details
  * Use numbered lists (1., 2., 3.) for sequential items
  * Use bullet points (- ) for unordered lists
- Include relevant numbers and dates from the context
- Highlight key risks or blockers when present
- Focus on the most relevant information
"""
    
    max_tokens = policy.get("max_tokens", DEFAULT_MAX_TOKENS)
    if max_tokens:
        prompt += f"\n- Keep your answer under {max_tokens} tokens\n"
    
    return prompt


def _build_context_string(matches: List[Dict[str, Any]]) -> str:
    """Build context string from retrieved matches."""
    if not matches:
        return "No context available."
    
    context_parts = []
    for idx, match in enumerate(matches, 1):
        text = match.get("text", "")
        metadata = match.get("metadata", {})
        
        sobject = metadata.get("sobject", "Unknown")
        record_id = metadata.get("recordId", "Unknown")
        
        context_parts.append(f"[Context {idx}]")
        context_parts.append(f"Source: {sobject}/{record_id}")
        context_parts.append(f"Content: {text}")
        context_parts.append("")  # Empty line between contexts
    
    return "\n".join(context_parts)


def _build_user_prompt(query: str, context: str) -> str:
    """Build user prompt with query and context."""
    return f"""CONTEXT:
{context}

USER QUERY:
{query}

Please answer the user's query based on the context provided above. Remember to cite your sources."""


def _extract_citations(answer: str) -> List[str]:
    """Extract citation markers from answer text.
    
    Looks for patterns like [Source: RecordId] or [Source: Opportunity/006xx1]
    """
    # Pattern matches [Source: ...] with various formats
    pattern = r'\[Source:\s*([^\]]+)\]'
    matches = re.findall(pattern, answer)
    
    citations = []
    for match in matches:
        # Split by comma for multiple sources in one citation
        sources = [s.strip() for s in match.split(',')]
        citations.extend(sources)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_citations = []
    for citation in citations:
        if citation not in seen:
            seen.add(citation)
            unique_citations.append(citation)
    
    return unique_citations


def _persist_session_async(
    session_id: str,
    salesforce_user_id: str,
    query: str,
    answer: str,
    citations: List[Dict[str, Any]],
    record_context: Dict[str, Any],
    trace: Dict[str, Any]
) -> None:
    """Persist session data to DynamoDB with 30-day TTL."""
    sessions_table_name = os.getenv("SESSIONS_TABLE_NAME", "")
    if not sessions_table_name:
        LOGGER.warning("SESSIONS_TABLE_NAME not configured, skipping session persistence")
        return
    
    try:
        table = dynamodb.Table(sessions_table_name)
        
        # Calculate TTL (30 days from now)
        ttl = int(time.time()) + (30 * 24 * 60 * 60)
        
        # Get turn number (for multi-turn conversations)
        # For now, we'll use timestamp as turn identifier
        turn_number = int(time.time() * 1000)  # milliseconds
        
        # Convert floats to Decimal for DynamoDB
        from decimal import Decimal
        
        def to_decimal(obj):
            if isinstance(obj, float):
                return Decimal(str(obj))
            if isinstance(obj, dict):
                return {k: to_decimal(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [to_decimal(v) for v in obj]
            return obj
            
        safe_trace = to_decimal(trace)
        
        # Build session item
        item = {
            "sessionId": session_id,
            "turnNumber": turn_number,
            "salesforceUserId": salesforce_user_id,
            "query": query,
            "answer": answer,
            "citations": citations,
            "recordContext": record_context,
            "timestamp": int(time.time()),
            "trace": safe_trace,
            "ttl": ttl,
        }
        
        # Write to DynamoDB
        table.put_item(Item=item)
        LOGGER.info("Persisted session data for sessionId=%s", session_id)
        
    except Exception as exc:  # pragma: no cover - defensive
        # Don't fail the request if session persistence fails
        LOGGER.error("Failed to persist session data: %s", exc)


def _validate_citations(
    citations: List[str],
    matches: List[Dict[str, Any]]
) -> tuple[List[Dict[str, Any]], List[str]]:
    """Validate that all citations reference records from the retrieved context.
    
    Returns tuple of (valid_citations, invalid_citations).
    """
    # Build set of valid record IDs from matches
    valid_record_ids = set()
    record_data = {}

    for match in matches:
        metadata = match.get("metadata", {})
        sobject = metadata.get("sobject", "")
        record_id = metadata.get("recordId", "")

        if sobject and record_id:
            # Support both formats: "RecordId" and "Sobject/RecordId"
            full_id = f"{sobject}/{record_id}"
            valid_record_ids.add(record_id)
            valid_record_ids.add(full_id)

            # Store full match for citation enrichment (includes score)
            record_data[record_id] = match
            record_data[full_id] = match
    
    valid_citations = []
    invalid_citations = []
    
    for citation in citations:
        if citation in valid_record_ids:
            # Get match data (includes metadata and score)
            match = record_data.get(citation, {})
            metadata = match.get("metadata", {})
            chunk_text = match.get("text", "")

            # Extract title from chunk text (format: "# Title\n\nName: Title\n...")
            # Try to get from metadata first, then parse from text
            title = (
                metadata.get("Name") or
                metadata.get("name") or
                metadata.get("title") or
                metadata.get("recordName")
            )

            # If not in metadata, try to extract from chunk text
            if not title and chunk_text:
                # Try to extract from markdown header (# Title)
                import re
                header_match = re.match(r'^#\s+(.+?)$', chunk_text, re.MULTILINE)
                if header_match:
                    title = header_match.group(1).strip()
                else:
                    # Try to extract from "Name: Value" line
                    name_match = re.search(r'Name:\s+(.+?)(?:\n|$)', chunk_text)
                    if name_match:
                        title = name_match.group(1).strip()

            # Fallback to record ID if still no title
            if not title:
                title = metadata.get("recordId", "Unknown")

            # Convert score to string for DynamoDB compatibility
            score = match.get("score", 0.0)
            citation_obj = {
                "id": citation,
                "title": title,
                "sobject": metadata.get("sobject", ""),
                "recordId": metadata.get("recordId", ""),
                "text": metadata.get("snippet", chunk_text),
                "score": str(round(score, 2)) if score else "0.00",
            }
            valid_citations.append(citation_obj)
        else:
            invalid_citations.append(citation)
    
    return valid_citations, invalid_citations


def _stream_bedrock_answer(
    system_prompt: str,
    user_prompt: str,
    policy: Dict[str, Any]
) -> Generator[tuple[str, str], None, None]:
    """Stream answer generation from Bedrock with Guardrails.
    
    Yields tuples of (sse_event, token_text) for each token.
    """
    model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
    guardrail_id = os.getenv("BEDROCK_GUARDRAIL_ID", "")
    guardrail_version = os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")
    
    max_tokens = policy.get("max_tokens", DEFAULT_MAX_TOKENS)
    temperature = policy.get("temperature", DEFAULT_TEMPERATURE)
    
    invoke_params = {
        "modelId": model_id,
        "contentType": "application/json",
        "accept": "application/json",
    }
    
    if guardrail_id:
        invoke_params["guardrailIdentifier"] = guardrail_id
        invoke_params["guardrailVersion"] = guardrail_version

    # Handle different model providers
    if "anthropic" in model_id:
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        }
    elif "amazon" in model_id:
        # Amazon Titan format
        # Titan doesn't support system prompts directly in the same way, so prepend to input
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        request_body = {
            "inputText": full_prompt,
            "textGenerationConfig": {
                "maxTokenCount": max_tokens,
                "temperature": temperature,
                "topP": 0.9,
                "stopSequences": []
            }
        }
    else:
        raise BedrockError(f"Unsupported model provider: {model_id}")

    invoke_params["body"] = json.dumps(request_body)
    
    try:
        # Use invoke_model_with_response_stream for streaming
        response = bedrock_runtime_client.invoke_model_with_response_stream(**invoke_params)
        
        stream = response.get("body")
        if not stream:
            raise BedrockError("No response stream from Bedrock")
        
        for event in stream:
            chunk = event.get("chunk")
            if chunk:
                chunk_data = json.loads(chunk.get("bytes").decode())
                
                if "anthropic" in model_id:
                    # Handle Claude events
                    if chunk_data.get("type") == "content_block_delta":
                        delta = chunk_data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield (_format_sse_event("token", {"token": text}), text)
                    elif chunk_data.get("type") == "message_stop":
                        break
                    elif chunk_data.get("type") == "error":
                        error_msg = chunk_data.get("message", "Unknown Bedrock error")
                        raise BedrockError(f"Bedrock error: {error_msg}")
                
                elif "amazon" in model_id:
                    # Handle Titan events
                    # Titan response stream structure: { "outputText": "...", "index": 0, "totalOutputText": "...", "completionReason": "...", "inputTextTokenCount": 123 }
                    text = chunk_data.get("outputText", "")
                    if text:
                        yield (_format_sse_event("token", {"token": text}), text)
                    
                    if chunk_data.get("completionReason"):
                        # End of stream
                        break
        
    except (ClientError, BotoCoreError) as exc:
        LOGGER.error("Bedrock streaming failed: %s", exc)
        raise BedrockError(f"Failed to generate answer: {exc}") from exc
    except json.JSONDecodeError as exc:
        LOGGER.error("Failed to parse Bedrock response: %s", exc)
        raise BedrockError("Invalid response from Bedrock") from exc


def _invoke_retrieve_lambda(
    query: str,
    salesforce_user_id: str,
    top_k: int,
    record_context: Dict[str, Any],
    filters: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Call Retrieve Lambda internally to get relevant chunks."""
    function_name = os.environ.get("RETRIEVE_LAMBDA_FUNCTION_NAME")
    if not function_name:
        raise RetrievalError("RETRIEVE_LAMBDA_FUNCTION_NAME is not configured")

    request_payload = {
        "query": query,
        "salesforceUserId": salesforce_user_id,
        "topK": top_k,
        "recordContext": record_context,
        "hybrid": True,
        "authzMode": "both",
    }
    
    if filters:
        request_payload["filters"] = filters

    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(request_payload).encode("utf-8"),
        )
    except (ClientError, BotoCoreError) as exc:
        LOGGER.error("Failed to invoke Retrieve Lambda: %s", exc)
        raise RetrievalError(f"Failed to invoke Retrieve Lambda: {exc}") from exc

    payload_stream = response.get("Payload")
    raw_body = payload_stream.read() if payload_stream else b""
    
    try:
        decoded = raw_body.decode("utf-8") if isinstance(raw_body, (bytes, bytearray)) else raw_body
        data = json.loads(decoded)
    except Exception as exc:
        raise RetrievalError("Retrieve Lambda returned invalid JSON") from exc

    status_code = data.get("statusCode", 200)
    body = data.get("body")
    
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"error": body}

    if status_code >= 400:
        error_msg = body.get("error") if isinstance(body, dict) else "Unknown error"
        raise RetrievalError(f"Retrieve Lambda error ({status_code}): {error_msg}")

    if not isinstance(body, dict):
        raise RetrievalError("Retrieve Lambda returned unexpected response format")

    return body


def _response(status_code: int, body: Any, is_streaming: bool = False) -> Dict[str, Any]:
    """Build HTTP response."""
    if is_streaming:
        return {
            "statusCode": status_code,
            "headers": {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
            "body": body,
        }
    
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body) if isinstance(body, dict) else body,
    }


def lambda_handler(event, context, response_stream=None):
    """Main Lambda handler for /answer endpoint."""
    start = time.perf_counter()
    
    # Handle Function URL Auth (Manual API Key Check)
    if response_stream:
        headers = event.get("headers", {})
        # Case-insensitive header lookup
        api_key = next((v for k, v in headers.items() if k.lower() == "x-api-key"), None)
        expected_key = os.getenv("API_KEY")
        
        if not expected_key or api_key != expected_key:
            LOGGER.warning("Unauthorized access attempt")
            response_stream.status_code = 401
            response_stream.write(json.dumps({"error": "Unauthorized"}))
            response_stream.end()
            return

    request_id = str(uuid.uuid4())
    
    # Extract request ID from context if available
    if context and hasattr(context, "aws_request_id"):
        request_id = context.aws_request_id
    
    try:
        request_payload = _parse_request(event)
        LOGGER.info(
            "Processing answer request: sessionId=%s, query=%s",
            request_payload["sessionId"],
            request_payload["query"][:100]
        )
        
        # Retrieve relevant context chunks
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

            # Extract component-level trace from Retrieve Lambda for observability
            # **Feature: graph-aware-zero-config-retrieval, Task 26**
            retrieve_trace = retrieval_response.get("trace", {})

            # Extract queryPlan for debug output
            query_plan = retrieval_response.get("queryPlan", {})

            LOGGER.info("Retrieved %d context chunks in %dms", len(matches), retrieve_ms)
            
        except RetrievalError as exc:
            LOGGER.error("Retrieval failed: %s", exc)
            error_body = _stream_error(f"Failed to retrieve context: {str(exc)}")
            if response_stream:
                response_stream.status_code = 502
                response_stream.content_type = "text/event-stream"
                response_stream.write(error_body)
                response_stream.end()
                return
            return _response(502, error_body, is_streaming=True)

        # Check if retrieve Lambda returned a disambiguation request
        # **Feature: zero-config-schema-discovery, Task 29**
        disambiguation = retrieval_response.get("disambiguation", {})
        if disambiguation.get("needsDisambiguation"):
            LOGGER.info(
                "Disambiguation requested: %s options, terms=%s",
                len(disambiguation.get("options", [])),
                disambiguation.get("ambiguousTerms", [])
            )
            # Return disambiguation request to frontend via SSE
            stream_body = _format_sse_event("disambiguation", disambiguation)
            stream_body += _format_sse_event("done", {
                "reason": "disambiguation_needed",
                "trace": {
                    "retrieveMs": retrieve_ms,
                    "totalMs": round((time.perf_counter() - start) * 1000, 2),
                    "retrieveComponents": {
                        "intentMs": retrieve_trace.get("intentMs", 0),
                        "schemaDecompositionMs": retrieve_trace.get("schemaDecompositionMs", 0),
                        "disambiguationMs": retrieve_trace.get("disambiguationMs", 0),
                        "cached": retrieve_trace.get("cached", False),
                    },
                },
            })
            if response_stream:
                response_stream.status_code = 200
                response_stream.content_type = "text/event-stream"
                response_stream.write(stream_body)
                response_stream.end()
                return
            return _response(200, stream_body, is_streaming=True)

        # Check if we have any context
        if not matches:
            LOGGER.warning("No context retrieved for query")
            stream_body = _format_sse_event("token", {
                "token": "I don't have enough information to answer that question."
            })
            # Include component trace even for empty results for debugging
            empty_trace = {
                "retrieveMs": retrieve_ms,
                "totalMs": round((time.perf_counter() - start) * 1000, 2),
                "retrieveComponents": {
                    "intentMs": retrieve_trace.get("intentMs", 0),
                    "plannerMs": retrieve_trace.get("plannerMs", 0),
                    "authzMs": retrieve_trace.get("authzMs", 0),
                    "kbQueryMs": retrieve_trace.get("retrieveMs", 0),
                    "cached": retrieve_trace.get("cached", False),
                },
            }
            stream_body += _format_sse_event("done", {
                "reason": "no_accessible_results",
                "trace": empty_trace
            })
            if response_stream:
                response_stream.status_code = 200
                response_stream.content_type = "text/event-stream"
                response_stream.write(stream_body)
                response_stream.end()
                return
            return _response(200, stream_body, is_streaming=True)
        
        # Build prompts
        prompt_start = time.perf_counter()
        system_prompt = _build_system_prompt(request_payload["policy"])
        context_string = _build_context_string(matches)
        user_prompt = _build_user_prompt(request_payload["query"], context_string)
        prompt_ms = round((time.perf_counter() - prompt_start) * 1000, 2)
        
        LOGGER.info("Built prompts in %dms", prompt_ms)
        
        # Stream answer generation from Bedrock
        generate_start = time.perf_counter()
        
        if response_stream:
            response_stream.status_code = 200
            response_stream.content_type = "text/event-stream"

        stream_body = ""
        full_answer = ""
        first_token_ms = None

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
            debug_event = _format_sse_event("debug", debug_info)
            if response_stream:
                response_stream.write(debug_event)
            else:
                stream_body += debug_event
            LOGGER.info(f"[DEBUG] Query intent: {json.dumps(debug_info, default=str)}")

        try:
            for sse_event, token_text in _stream_bedrock_answer(
                system_prompt,
                user_prompt,
                request_payload["policy"]
            ):
                if first_token_ms is None:
                    first_token_ms = round((time.perf_counter() - generate_start) * 1000, 2)
                    LOGGER.info("First token received in %dms", first_token_ms)
                
                if response_stream:
                    response_stream.write(sse_event)
                else:
                    stream_body += sse_event
                
                full_answer += token_text
            
            generate_ms = round((time.perf_counter() - generate_start) * 1000, 2)
            LOGGER.info("Answer generation completed in %dms", generate_ms)
            
        except BedrockError as exc:
            LOGGER.error("Bedrock generation failed: %s", exc)
            error_body = _stream_error(f"Failed to generate answer: {str(exc)}")
            if response_stream:
                response_stream.write(error_body) # Might be too late to change status code
                response_stream.end()
                return
            return _response(503, error_body, is_streaming=True)
        
        # Extract and validate citations
        citation_start = time.perf_counter()
        extracted_citations = _extract_citations(full_answer)
        valid_citations, invalid_citations = _validate_citations(extracted_citations, matches)
        citation_ms = round((time.perf_counter() - citation_start) * 1000, 2)
        
        LOGGER.info(
            "Extracted %d citations (%d valid, %d invalid) in %dms",
            len(extracted_citations),
            len(valid_citations),
            len(invalid_citations),
            citation_ms
        )
        
        if invalid_citations:
            LOGGER.warning("Invalid citations found: %s", invalid_citations)
        
        # Send citation events
        for citation in valid_citations:
            citation_event = _format_sse_event("citation", citation)
            if response_stream:
                response_stream.write(citation_event)
            else:
                stream_body += citation_event
        
        # Build final trace with component-level metrics from Retrieve Lambda
        # **Feature: graph-aware-zero-config-retrieval, Task 26**
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
            # Component-level breakdown from Retrieve Lambda for performance analysis
            # **Task 26**: Complete component tracing for latency debugging
            "retrieveComponents": {
                "intentMs": retrieve_trace.get("intentMs", 0),
                "decompositionMs": retrieve_trace.get("decompositionMs", 0),
                "schemaDecompositionMs": retrieve_trace.get("schemaDecompositionMs", 0),
                "graphFilterMs": retrieve_trace.get("graphFilterMs", 0),
                "crossObjectMs": retrieve_trace.get("crossObjectMs", 0),
                "plannerMs": retrieve_trace.get("plannerMs", 0),
                "authzMs": retrieve_trace.get("authzMs", 0),
                "cacheCheckMs": retrieve_trace.get("cacheCheckMs", 0),
                "kbQueryMs": retrieve_trace.get("retrieveMs", 0),  # KB query time
                "graphMs": retrieve_trace.get("graphMs", 0),
                "supplementalSearchMs": retrieve_trace.get("supplementalSearchMs", 0),
                "relevanceFilterMs": retrieve_trace.get("relevanceFilterMs", 0),
                "postFilterMs": retrieve_trace.get("postFilterMs", 0),
                "presignedUrlMs": retrieve_trace.get("presignedUrlMs", 0),
                "rankingMs": retrieve_trace.get("rankingMs", 0),
                "flsMs": retrieve_trace.get("flsMs", 0),
                "retrieveTotalMs": retrieve_trace.get("totalMs", 0),  # Retrieve Lambda's total time
                "cached": retrieve_trace.get("cached", False),
                "plannerUsed": retrieve_trace.get("plannerUsed", False),
                "plannerSkipped": not retrieve_trace.get("plannerUsed", False) and retrieve_trace.get("plannerEnabled", False),
                "plannerConfidence": retrieve_trace.get("plannerConfidence", 0),
                "preFilterCount": retrieve_trace.get("preFilterCount", 0),
                "postFilterCount": retrieve_trace.get("postFilterCount", 0),
            },
        }
        
        # Persist session data to DynamoDB (async, non-blocking)
        _persist_session_async(
            session_id=request_payload["sessionId"],
            salesforce_user_id=request_payload["salesforceUserId"],
            query=request_payload["query"],
            answer=full_answer,
            citations=valid_citations,
            record_context=request_payload["recordContext"],
            trace=trace
        )
        
        # Add completion event with trace
        done_event = _format_sse_event("done", {
            "citations": valid_citations,
            "trace": trace
        })
        
        if response_stream:
            response_stream.write(done_event)
            response_stream.end()
            return
        else:
            stream_body += done_event
            return _response(200, stream_body, is_streaming=True)

    except ValidationError as exc:
        LOGGER.warning("Validation error: %s", exc)
        error_body = _stream_error(str(exc))
        if response_stream:
            response_stream.status_code = 400
            response_stream.content_type = "text/event-stream"
            response_stream.write(error_body)
            response_stream.end()
            return
        return _response(400, error_body, is_streaming=True)
    except RetrievalError as exc:
        LOGGER.error("Retrieval error: %s", exc)
        error_body = _stream_error(str(exc))
        if response_stream:
            response_stream.status_code = 502
            response_stream.content_type = "text/event-stream"
            response_stream.write(error_body)
            response_stream.end()
            return
        return _response(502, error_body, is_streaming=True)
    except Exception as exc:
        LOGGER.exception("Unexpected error in Answer Lambda")
        error_body = _stream_error(f"Internal server error: {str(exc)}")
        if response_stream:
            response_stream.status_code = 500
            response_stream.content_type = "text/event-stream"
            response_stream.write(error_body)
            response_stream.end()
            return
        return _response(500, error_body, is_streaming=True)
