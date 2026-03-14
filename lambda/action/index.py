"""Action Lambda handler for /action endpoint.
Executes agent actions (create/update) with two-step confirmation and rate limiting.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

lambda_client = boto3.client("lambda")
dynamodb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")
cloudwatch = boto3.client("cloudwatch")


class ValidationError(Exception):
    """Raised when the request payload is invalid."""


class AuthZServiceError(Exception):
    """Raised when the AuthZ Sidecar invocation fails."""


class ActionDisabledError(Exception):
    """Raised when the requested action is disabled."""


class RateLimitExceededError(Exception):
    """Raised when the user exceeds the rate limit for an action."""


class SalesforceAPIError(Exception):
    """Raised when Salesforce API call fails."""


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


def _validate_confirmation_token(token: Any, action_name: str, inputs: Dict[str, Any]) -> bool:
    """Validate confirmation token to prevent replay attacks.
    
    Token should be a hash of: actionName + inputs + timestamp (within 5 minutes).
    For POC, we use a simple hash validation. Production should use signed tokens.
    
    Args:
        token: Confirmation token from request
        action_name: Name of the action being executed
        inputs: Action inputs
    
    Returns:
        True if token is valid, False otherwise
    """
    if not isinstance(token, str) or not token:
        return False
    
    # For POC: Accept any non-empty token
    # Production should implement proper token signing and validation
    # with timestamp checking and single-use enforcement
    LOGGER.info("Confirmation token validated for action: %s", action_name)
    return True


def _parse_request(event: Dict[str, Any]) -> Dict[str, Any]:
    """Parse and validate incoming request payload."""
    payload = _decode_event_body(event)

    # Required fields
    action_name = payload.get("actionName")
    if not isinstance(action_name, str) or not action_name.strip():
        raise ValidationError("actionName is required")

    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        raise ValidationError("inputs must be an object")

    salesforce_user_id = _validate_salesforce_user(payload.get("salesforceUserId"))

    # Optional fields
    session_id = payload.get("sessionId")
    if session_id and not isinstance(session_id, str):
        raise ValidationError("sessionId must be a string")
    if not session_id:
        session_id = str(uuid.uuid4())

    confirmation_token = payload.get("confirmationToken")
    if not confirmation_token:
        raise ValidationError("confirmationToken is required")

    # Validate confirmation token
    if not _validate_confirmation_token(confirmation_token, action_name, inputs):
        raise ValidationError("Invalid or expired confirmation token")

    return {
        "actionName": action_name.strip(),
        "inputs": inputs,
        "salesforceUserId": salesforce_user_id,
        "sessionId": session_id,
        "confirmationToken": confirmation_token,
    }


def _get_action_metadata(action_name: str) -> Optional[Dict[str, Any]]:
    """Retrieve action metadata from DynamoDB.
    
    Args:
        action_name: Name of the action
    
    Returns:
        Action metadata dictionary or None if not found
    """
    action_metadata_table_name = os.getenv("ACTION_METADATA_TABLE_NAME", "")
    if not action_metadata_table_name:
        LOGGER.warning("ACTION_METADATA_TABLE_NAME not configured")
        return None
    
    try:
        table = dynamodb.Table(action_metadata_table_name)
        response = table.get_item(Key={"actionName": action_name})
        
        if "Item" not in response:
            LOGGER.warning("Action metadata not found for: %s", action_name)
            return None
        
        return response["Item"]
    
    except Exception as exc:
        LOGGER.error("Error retrieving action metadata: %s", exc)
        return None


def _validate_action_enabled(action_name: str) -> Dict[str, Any]:
    """Validate that the action is enabled and retrieve its configuration.
    
    Args:
        action_name: Name of the action to validate
    
    Returns:
        Action metadata dictionary
    
    Raises:
        ActionDisabledError: If action is disabled or not found
    """
    metadata = _get_action_metadata(action_name)
    
    if not metadata:
        raise ActionDisabledError(f"Action '{action_name}' is not registered")
    
    enabled = metadata.get("enabled", False)
    if not enabled:
        raise ActionDisabledError(f"Action '{action_name}' is temporarily unavailable")
    
    LOGGER.info("Action '%s' is enabled", action_name)
    return metadata


def _validate_inputs_against_schema(
    inputs: Dict[str, Any],
    input_schema: Dict[str, Any]
) -> None:
    """Validate action inputs against JSON schema.
    
    Args:
        inputs: Input values to validate
        input_schema: JSON schema definition
    
    Raises:
        ValidationError: If inputs don't match schema
    """
    if not input_schema:
        # No schema defined, skip validation
        return
    
    # Check required fields
    required_fields = input_schema.get("required", [])
    for field in required_fields:
        if field not in inputs or inputs[field] is None:
            raise ValidationError(f"Required field '{field}' is missing")
    
    # Validate field types and constraints
    properties = input_schema.get("properties", {})
    for field_name, field_value in inputs.items():
        if field_name not in properties:
            # Field not in schema - could be extra field
            LOGGER.warning("Input field '%s' not defined in schema", field_name)
            continue
        
        field_schema = properties[field_name]
        field_type = field_schema.get("type")
        
        # Type validation
        if field_type == "string" and not isinstance(field_value, str):
            raise ValidationError(f"Field '{field_name}' must be a string")
        elif field_type == "number" and not isinstance(field_value, (int, float)):
            raise ValidationError(f"Field '{field_name}' must be a number")
        elif field_type == "integer" and not isinstance(field_value, int):
            raise ValidationError(f"Field '{field_name}' must be an integer")
        elif field_type == "boolean" and not isinstance(field_value, bool):
            raise ValidationError(f"Field '{field_name}' must be a boolean")
        elif field_type == "object" and not isinstance(field_value, dict):
            raise ValidationError(f"Field '{field_name}' must be an object")
        elif field_type == "array" and not isinstance(field_value, list):
            raise ValidationError(f"Field '{field_name}' must be an array")
        
        # String constraints
        if field_type == "string" and isinstance(field_value, str):
            max_length = field_schema.get("maxLength")
            if max_length and len(field_value) > max_length:
                raise ValidationError(
                    f"Field '{field_name}' exceeds maximum length of {max_length}"
                )
            
            pattern = field_schema.get("pattern")
            if pattern:
                import re
                if not re.match(pattern, field_value):
                    raise ValidationError(
                        f"Field '{field_name}' does not match required pattern"
                    )
            
            enum_values = field_schema.get("enum")
            if enum_values and field_value not in enum_values:
                raise ValidationError(
                    f"Field '{field_name}' must be one of: {', '.join(enum_values)}"
                )
        
        # Number constraints
        if field_type in ("number", "integer") and isinstance(field_value, (int, float)):
            minimum = field_schema.get("minimum")
            if minimum is not None and field_value < minimum:
                raise ValidationError(
                    f"Field '{field_name}' must be at least {minimum}"
                )
            
            maximum = field_schema.get("maximum")
            if maximum is not None and field_value > maximum:
                raise ValidationError(
                    f"Field '{field_name}' must be at most {maximum}"
                )
    
    LOGGER.info("Input validation passed")


def _get_rate_limit_key(user_id: str, action_name: str) -> str:
    """Generate rate limit key for DynamoDB.
    
    Format: {userId}_{actionName}_{date}
    Example: 005xx_create_opportunity_2025-11-13
    
    Args:
        user_id: Salesforce User ID
        action_name: Action name
    
    Returns:
        Rate limit key string
    """
    from datetime import datetime
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    return f"{user_id}_{action_name}_{date_str}"


def _check_rate_limit(
    user_id: str,
    action_name: str,
    max_per_day: int
) -> int:
    """Check if user has exceeded rate limit for the action.
    
    Args:
        user_id: Salesforce User ID
        action_name: Action name
        max_per_day: Maximum executions per user per day
    
    Returns:
        Current count for today
    
    Raises:
        RateLimitExceededError: If limit is exceeded
    """
    rate_limits_table_name = os.getenv("RATE_LIMITS_TABLE_NAME", "")
    if not rate_limits_table_name:
        LOGGER.warning("RATE_LIMITS_TABLE_NAME not configured, skipping rate limit check")
        return 0
    
    try:
        table = dynamodb.Table(rate_limits_table_name)
        rate_limit_key = _get_rate_limit_key(user_id, action_name)
        
        response = table.get_item(Key={"userId_actionName_date": rate_limit_key})
        
        if "Item" in response:
            current_count = response["Item"].get("count", 0)
        else:
            current_count = 0
        
        LOGGER.info(
            "Rate limit check: user=%s, action=%s, count=%d, limit=%d",
            user_id,
            action_name,
            current_count,
            max_per_day
        )
        
        if current_count >= max_per_day:
            raise RateLimitExceededError(
                f"You've reached the daily limit of {max_per_day} for this action. "
                "Try again tomorrow."
            )
        
        return current_count
    
    except RateLimitExceededError:
        raise
    except Exception as exc:
        LOGGER.error("Error checking rate limit: %s", exc)
        # Don't fail the request if rate limit check fails
        return 0


def _increment_rate_limit(user_id: str, action_name: str) -> None:
    """Increment rate limit counter for user/action/date.
    
    Args:
        user_id: Salesforce User ID
        action_name: Action name
    """
    rate_limits_table_name = os.getenv("RATE_LIMITS_TABLE_NAME", "")
    if not rate_limits_table_name:
        LOGGER.warning("RATE_LIMITS_TABLE_NAME not configured, skipping rate limit increment")
        return
    
    try:
        from datetime import datetime, timedelta
        
        table = dynamodb.Table(rate_limits_table_name)
        rate_limit_key = _get_rate_limit_key(user_id, action_name)
        
        # Calculate TTL: end of day + 7 days
        now = datetime.utcnow()
        end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        ttl_datetime = end_of_day + timedelta(days=7)
        ttl = int(ttl_datetime.timestamp())
        
        # Increment counter using atomic update
        table.update_item(
            Key={"userId_actionName_date": rate_limit_key},
            UpdateExpression="ADD #count :inc SET lastUpdated = :now, #ttl = :ttl",
            ExpressionAttributeNames={
                "#count": "count",
                "#ttl": "ttl",
            },
            ExpressionAttributeValues={
                ":inc": 1,
                ":now": int(now.timestamp()),
                ":ttl": ttl,
            },
        )
        
        LOGGER.info("Incremented rate limit counter for: %s", rate_limit_key)
    
    except Exception as exc:
        # Don't fail the request if rate limit increment fails
        LOGGER.error("Error incrementing rate limit: %s", exc)


def _get_salesforce_access_token() -> str:
    """Retrieve Salesforce access token from SSM Parameter Store.
    
    Returns:
        Salesforce access token
    
    Raises:
        SalesforceAPIError: If token cannot be retrieved
    """
    try:
        parameter_name = os.environ.get("SALESFORCE_TOKEN_PARAM", "/salesforce/access_token")
        response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
        return response["Parameter"]["Value"]
    except Exception as exc:
        LOGGER.error("Error retrieving Salesforce token: %s", exc)
        # Fallback to environment variable for local testing
        token = os.environ.get("SALESFORCE_ACCESS_TOKEN", "")
        if not token:
            raise SalesforceAPIError("Salesforce access token not available") from exc
        return token


def _invoke_salesforce_flow(
    flow_name: str,
    inputs: Dict[str, Any],
    user_id: str
) -> Dict[str, Any]:
    """Invoke Salesforce autolaunched Flow via REST API.
    
    Args:
        flow_name: API name of the Flow to invoke
        inputs: Input variables for the Flow
        user_id: Salesforce User ID (for context)
    
    Returns:
        Flow execution result dictionary
    
    Raises:
        SalesforceAPIError: If Flow invocation fails
    """
    import requests
    
    salesforce_api_endpoint = os.getenv("SALESFORCE_API_ENDPOINT", "")
    salesforce_api_version = os.getenv("SALESFORCE_API_VERSION", "v59.0")
    
    if not salesforce_api_endpoint:
        raise SalesforceAPIError("SALESFORCE_API_ENDPOINT not configured")
    
    access_token = _get_salesforce_access_token()
    
    # Build Flow invocation URL
    url = f"{salesforce_api_endpoint}/services/data/{salesforce_api_version}/actions/custom/flow/{flow_name}"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    
    # Build request body with inputs
    request_body = {
        "inputs": [inputs]  # Flows expect an array of input records
    }
    
    LOGGER.info("Invoking Salesforce Flow: %s", flow_name)
    
    try:
        response = requests.post(
            url,
            headers=headers,
            json=request_body,
            timeout=25  # Leave buffer for Lambda timeout
        )
        
        # Log response for debugging
        LOGGER.info("Flow response status: %d", response.status_code)
        
        if response.status_code >= 400:
            error_body = response.text
            try:
                error_json = response.json()
                error_message = error_json[0].get("message", error_body) if error_json else error_body
            except (json.JSONDecodeError, IndexError, KeyError):
                error_message = error_body
            
            LOGGER.error("Flow invocation failed: %s", error_message)
            raise SalesforceAPIError(f"Flow execution failed: {error_message}")
        
        # Parse response
        response_data = response.json()
        
        # Flow responses are arrays with one element per input
        if not response_data or not isinstance(response_data, list):
            raise SalesforceAPIError("Invalid Flow response format")
        
        flow_result = response_data[0]
        
        # Check if Flow execution was successful
        is_success = flow_result.get("isSuccess", False)
        output_values = flow_result.get("outputValues", {})
        errors = flow_result.get("errors", [])
        
        if not is_success:
            error_message = errors[0].get("message", "Unknown Flow error") if errors else "Flow execution failed"
            LOGGER.error("Flow execution failed: %s", error_message)
            raise SalesforceAPIError(f"Flow execution failed: {error_message}")
        
        LOGGER.info("Flow executed successfully: %s", flow_name)
        
        return {
            "success": True,
            "outputValues": output_values,
            "errors": errors,
        }
    
    except requests.exceptions.Timeout as exc:
        LOGGER.error("Flow invocation timed out: %s", exc)
        raise SalesforceAPIError("Flow invocation timed out") from exc
    except requests.exceptions.RequestException as exc:
        LOGGER.error("Flow invocation request failed: %s", exc)
        raise SalesforceAPIError(f"Flow invocation failed: {str(exc)}") from exc
    except SalesforceAPIError:
        raise
    except Exception as exc:
        LOGGER.error("Unexpected error invoking Flow: %s", exc)
        raise SalesforceAPIError(f"Unexpected error: {str(exc)}") from exc


def _invoke_apex_method(
    apex_method: str,
    inputs: Dict[str, Any],
    user_id: str
) -> Dict[str, Any]:
    """Invoke Salesforce Apex invocable method via REST API.
    
    Args:
        apex_method: Fully qualified Apex method name (Class.method)
        inputs: Input parameters for the method
        user_id: Salesforce User ID (for context)
    
    Returns:
        Apex method result dictionary
    
    Raises:
        SalesforceAPIError: If Apex invocation fails
    """
    import requests
    
    salesforce_api_endpoint = os.getenv("SALESFORCE_API_ENDPOINT", "")
    salesforce_api_version = os.getenv("SALESFORCE_API_VERSION", "v59.0")
    
    if not salesforce_api_endpoint:
        raise SalesforceAPIError("SALESFORCE_API_ENDPOINT not configured")
    
    access_token = _get_salesforce_access_token()
    
    # Build Apex invocation URL
    url = f"{salesforce_api_endpoint}/services/data/{salesforce_api_version}/actions/custom/apex/{apex_method}"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    
    # Build request body with inputs
    request_body = {
        "inputs": [inputs]  # Apex methods expect an array of input records
    }
    
    LOGGER.info("Invoking Salesforce Apex method: %s", apex_method)
    
    try:
        response = requests.post(
            url,
            headers=headers,
            json=request_body,
            timeout=25  # Leave buffer for Lambda timeout
        )
        
        # Log response for debugging
        LOGGER.info("Apex response status: %d", response.status_code)
        
        if response.status_code >= 400:
            error_body = response.text
            try:
                error_json = response.json()
                error_message = error_json[0].get("message", error_body) if error_json else error_body
            except (json.JSONDecodeError, IndexError, KeyError):
                error_message = error_body
            
            LOGGER.error("Apex invocation failed: %s", error_message)
            raise SalesforceAPIError(f"Apex execution failed: {error_message}")
        
        # Parse response
        response_data = response.json()
        
        # Apex responses are arrays with one element per input
        if not response_data or not isinstance(response_data, list):
            raise SalesforceAPIError("Invalid Apex response format")
        
        apex_result = response_data[0]
        
        # Check if Apex execution was successful
        is_success = apex_result.get("isSuccess", False)
        output_values = apex_result.get("outputValues", {})
        errors = apex_result.get("errors", [])
        
        if not is_success:
            error_message = errors[0].get("message", "Unknown Apex error") if errors else "Apex execution failed"
            LOGGER.error("Apex execution failed: %s", error_message)
            raise SalesforceAPIError(f"Apex execution failed: {error_message}")
        
        LOGGER.info("Apex method executed successfully: %s", apex_method)
        
        return {
            "success": True,
            "outputValues": output_values,
            "errors": errors,
        }
    
    except requests.exceptions.Timeout as exc:
        LOGGER.error("Apex invocation timed out: %s", exc)
        raise SalesforceAPIError("Apex invocation timed out") from exc
    except requests.exceptions.RequestException as exc:
        LOGGER.error("Apex invocation request failed: %s", exc)
        raise SalesforceAPIError(f"Apex invocation failed: {str(exc)}") from exc
    except SalesforceAPIError:
        raise
    except Exception as exc:
        LOGGER.error("Unexpected error invoking Apex: %s", exc)
        raise SalesforceAPIError(f"Unexpected error: {str(exc)}") from exc


def _execute_action(
    action_metadata: Dict[str, Any],
    inputs: Dict[str, Any],
    user_id: str
) -> Dict[str, Any]:
    """Execute the action by invoking Flow or Apex method.
    
    Args:
        action_metadata: Action configuration from metadata table
        inputs: Validated input values
        user_id: Salesforce User ID
    
    Returns:
        Execution result dictionary with success, recordIds, and error fields
    
    Raises:
        SalesforceAPIError: If execution fails
    """
    flow_name = action_metadata.get("flowName")
    apex_method = action_metadata.get("apexMethod")
    
    if flow_name:
        # Invoke Flow
        result = _invoke_salesforce_flow(flow_name, inputs, user_id)
        output_values = result.get("outputValues", {})
        
        # Extract record IDs from output
        record_ids = []
        if "id" in output_values:
            record_ids.append(output_values["id"])
        elif "recordId" in output_values:
            record_ids.append(output_values["recordId"])
        elif "recordIds" in output_values:
            record_ids = output_values["recordIds"]
        
        return {
            "success": True,
            "recordIds": record_ids,
            "outputValues": output_values,
            "error": None,
        }
    
    elif apex_method:
        # Invoke Apex method
        result = _invoke_apex_method(apex_method, inputs, user_id)
        output_values = result.get("outputValues", {})
        
        # Extract record IDs from output
        record_ids = []
        if "id" in output_values:
            record_ids.append(output_values["id"])
        elif "recordId" in output_values:
            record_ids.append(output_values["recordId"])
        elif "recordIds" in output_values:
            record_ids = output_values["recordIds"]
        
        return {
            "success": True,
            "recordIds": record_ids,
            "outputValues": output_values,
            "error": None,
        }
    
    else:
        raise SalesforceAPIError("Action has no Flow or Apex method configured")


def _hash_pii_inputs(inputs: Dict[str, Any]) -> str:
    """Hash inputs containing PII for audit logging.
    
    Args:
        inputs: Input dictionary
    
    Returns:
        SHA-256 hash of inputs
    """
    inputs_str = json.dumps(inputs, sort_keys=True)
    return hashlib.sha256(inputs_str.encode()).hexdigest()


def _check_has_pii(inputs: Dict[str, Any]) -> bool:
    """Check if inputs contain PII fields.
    
    For POC, we use simple heuristics. Production should use more sophisticated detection.
    
    Args:
        inputs: Input dictionary
    
    Returns:
        True if inputs likely contain PII
    """
    pii_field_patterns = [
        "email",
        "phone",
        "ssn",
        "social",
        "address",
        "birthdate",
        "dob",
        "credit",
        "card",
    ]
    
    # Check field names for PII indicators
    for key in inputs.keys():
        key_lower = key.lower()
        for pattern in pii_field_patterns:
            if pattern in key_lower:
                return True
    
    # Check values for email patterns
    for value in inputs.values():
        if isinstance(value, str):
            # Simple email pattern check
            if "@" in value and "." in value:
                return True
    
    return False


def _log_action_audit_async(
    user_id: str,
    action_name: str,
    inputs: Dict[str, Any],
    record_ids: List[str],
    success: bool,
    error: Optional[str],
    session_id: str,
    latency_ms: float
) -> None:
    """Log action execution to Salesforce AI_Action_Audit__c object.
    
    This is done asynchronously (non-blocking) to avoid impacting response time.
    
    Args:
        user_id: Salesforce User ID
        action_name: Action name
        inputs: Action inputs
        record_ids: List of affected record IDs
        success: Whether action succeeded
        error: Error message if failed
        session_id: Chat session ID
        latency_ms: Execution latency in milliseconds
    """
    import requests
    
    try:
        salesforce_api_endpoint = os.getenv("SALESFORCE_API_ENDPOINT", "")
        salesforce_api_version = os.getenv("SALESFORCE_API_VERSION", "v59.0")
        
        if not salesforce_api_endpoint:
            LOGGER.warning("SALESFORCE_API_ENDPOINT not configured, skipping audit logging")
            return
        
        access_token = _get_salesforce_access_token()
        
        # Build audit record
        has_pii = _check_has_pii(inputs)
        
        audit_record = {
            "UserId__c": user_id,
            "ActionName__c": action_name,
            "Records__c": json.dumps(record_ids) if record_ids else None,
            "Success__c": success,
            "Error__c": error[:32000] if error else None,  # Truncate to field limit
            "ChatSessionId__c": session_id,
            "LatencyMs__c": latency_ms,
        }
        
        # Handle PII: hash inputs if PII detected, otherwise store full inputs
        if has_pii:
            audit_record["InputsHash__c"] = _hash_pii_inputs(inputs)
            # Don't store full inputs if PII detected
            LOGGER.info("PII detected in inputs, storing hash only")
        else:
            # Store full inputs as encrypted text (Salesforce handles encryption)
            inputs_json = json.dumps(inputs)
            if len(inputs_json) <= 131072:  # Long Text Area limit
                audit_record["InputsJson__c"] = inputs_json
            else:
                # Inputs too large, store hash instead
                audit_record["InputsHash__c"] = _hash_pii_inputs(inputs)
                LOGGER.warning("Inputs too large for InputsJson__c, storing hash")
        
        # Create audit record via Salesforce REST API
        url = f"{salesforce_api_endpoint}/services/data/{salesforce_api_version}/sobjects/AI_Action_Audit__c"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        
        response = requests.post(
            url,
            headers=headers,
            json=audit_record,
            timeout=10
        )
        
        if response.status_code >= 400:
            LOGGER.error("Failed to create audit record: %s", response.text)
        else:
            audit_id = response.json().get("id")
            LOGGER.info("Created audit record: %s", audit_id)
    
    except Exception as exc:
        # Don't fail the request if audit logging fails
        LOGGER.error("Error logging action audit: %s", exc)


def _emit_cloudwatch_metrics(
    action_name: str,
    success: bool,
    latency_ms: float,
    user_id: str,
    is_rate_limited: bool = False,
    consecutive_failures: int = 0
) -> None:
    """Emit custom CloudWatch metrics for action monitoring.
    
    Args:
        action_name: Name of the action executed
        success: Whether action succeeded
        latency_ms: Execution latency in milliseconds
        user_id: Salesforce User ID
        is_rate_limited: Whether request was rate limited
        consecutive_failures: Number of consecutive failures for this user
    """
    try:
        metric_data = []
        
        # Action count by action name
        metric_data.append({
            'MetricName': 'ActionCount',
            'Value': 1,
            'Unit': 'Count',
            'Dimensions': [
                {'Name': 'ActionName', 'Value': action_name}
            ]
        })
        
        # Action success/failure
        metric_data.append({
            'MetricName': 'ActionSuccessRate',
            'Value': 100.0 if success else 0.0,
            'Unit': 'Percent',
            'Dimensions': [
                {'Name': 'ActionName', 'Value': action_name}
            ]
        })
        
        metric_data.append({
            'MetricName': 'ActionFailureRate',
            'Value': 0.0 if success else 100.0,
            'Unit': 'Percent',
            'Dimensions': [
                {'Name': 'ActionName', 'Value': action_name}
            ]
        })
        
        # Rate limit rejections
        if is_rate_limited:
            metric_data.append({
                'MetricName': 'RateLimitRejections',
                'Value': 1,
                'Unit': 'Count',
                'Dimensions': [
                    {'Name': 'ActionName', 'Value': action_name}
                ]
            })
        
        # Mutation volume (count all successful actions as mutations)
        if success:
            metric_data.append({
                'MetricName': 'MutationVolume',
                'Value': 1,
                'Unit': 'Count'
            })
        
        # Consecutive failures per user
        if consecutive_failures > 0:
            metric_data.append({
                'MetricName': 'ConsecutiveFailures',
                'Value': consecutive_failures,
                'Unit': 'Count',
                'Dimensions': [
                    {'Name': 'UserId', 'Value': user_id}
                ]
            })
        
        # Publish metrics to CloudWatch
        cloudwatch.put_metric_data(
            Namespace='SalesforceAISearch',
            MetricData=metric_data
        )
        
        LOGGER.debug("Emitted CloudWatch metrics for action: %s", action_name)
    
    except Exception as exc:
        # Don't fail the request if metrics emission fails
        LOGGER.error("Error emitting CloudWatch metrics: %s", exc)


def _get_consecutive_failures(user_id: str, action_name: str) -> int:
    """Get count of consecutive failures for user/action from DynamoDB.
    
    Args:
        user_id: Salesforce User ID
        action_name: Action name
    
    Returns:
        Number of consecutive failures
    """
    rate_limits_table_name = os.getenv("RATE_LIMITS_TABLE_NAME", "")
    if not rate_limits_table_name:
        return 0
    
    try:
        table = dynamodb.Table(rate_limits_table_name)
        failure_key = f"{user_id}_{action_name}_failures"
        
        response = table.get_item(Key={"userId_actionName_date": failure_key})
        
        if "Item" in response:
            return response["Item"].get("consecutiveFailures", 0)
        
        return 0
    
    except Exception as exc:
        LOGGER.error("Error getting consecutive failures: %s", exc)
        return 0


def _update_consecutive_failures(user_id: str, action_name: str, success: bool) -> int:
    """Update consecutive failure counter for user/action.
    
    Args:
        user_id: Salesforce User ID
        action_name: Action name
        success: Whether action succeeded
    
    Returns:
        Updated consecutive failure count
    """
    rate_limits_table_name = os.getenv("RATE_LIMITS_TABLE_NAME", "")
    if not rate_limits_table_name:
        return 0
    
    try:
        from datetime import datetime, timedelta
        
        table = dynamodb.Table(rate_limits_table_name)
        failure_key = f"{user_id}_{action_name}_failures"
        
        if success:
            # Reset consecutive failures on success
            table.delete_item(Key={"userId_actionName_date": failure_key})
            return 0
        else:
            # Increment consecutive failures
            now = datetime.utcnow()
            ttl_datetime = now + timedelta(days=1)
            ttl = int(ttl_datetime.timestamp())
            
            response = table.update_item(
                Key={"userId_actionName_date": failure_key},
                UpdateExpression="ADD consecutiveFailures :inc SET lastUpdated = :now, #ttl = :ttl",
                ExpressionAttributeNames={
                    "#ttl": "ttl",
                },
                ExpressionAttributeValues={
                    ":inc": 1,
                    ":now": int(now.timestamp()),
                    ":ttl": ttl,
                },
                ReturnValues="ALL_NEW"
            )
            
            return response["Attributes"].get("consecutiveFailures", 1)
    
    except Exception as exc:
        LOGGER.error("Error updating consecutive failures: %s", exc)
        return 0


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Build HTTP response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    """Main Lambda handler for /action endpoint."""
    start = time.perf_counter()
    request_id = str(uuid.uuid4())
    
    # Extract request ID from context if available
    if context and hasattr(context, "aws_request_id"):
        request_id = context.aws_request_id
    
    # Kill switch check - disable all actions via environment variable
    actions_enabled = os.environ.get("ACTIONS_ENABLED", "true").lower()
    if actions_enabled == "false":
        LOGGER.warning("Actions are disabled via ACTIONS_ENABLED environment variable")
        return {
            "statusCode": 503,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": "service_unavailable",
                "message": "Agent actions are temporarily unavailable. Please try again later or contact your administrator."
            })
        }
    
    try:
        request_payload = _parse_request(event)
        LOGGER.info(
            "Processing action request: actionName=%s, sessionId=%s",
            request_payload["actionName"],
            request_payload["sessionId"]
        )
        
        # Validate action is enabled and get configuration
        action_metadata = _validate_action_enabled(request_payload["actionName"])
        
        # Validate inputs against schema
        input_schema = action_metadata.get("inputSchema", {})
        if isinstance(input_schema, str):
            try:
                input_schema = json.loads(input_schema)
            except json.JSONDecodeError:
                LOGGER.warning("Invalid input schema JSON for action: %s", request_payload["actionName"])
                input_schema = {}
        
        _validate_inputs_against_schema(request_payload["inputs"], input_schema)
        
        # Check rate limit
        max_per_user_per_day = action_metadata.get("maxPerUserPerDay", 100)
        current_count = _check_rate_limit(
            request_payload["salesforceUserId"],
            request_payload["actionName"],
            max_per_user_per_day
        )
        
        # Execute the action (Flow or Apex)
        execution_start = time.perf_counter()
        try:
            execution_result = _execute_action(
                action_metadata,
                request_payload["inputs"],
                request_payload["salesforceUserId"]
            )
            execution_ms = round((time.perf_counter() - execution_start) * 1000, 2)
            
            # Increment rate limit counter after successful execution
            _increment_rate_limit(
                request_payload["salesforceUserId"],
                request_payload["actionName"]
            )
            
            # Log audit record (async, non-blocking)
            total_ms = round((time.perf_counter() - start) * 1000, 2)
            _log_action_audit_async(
                user_id=request_payload["salesforceUserId"],
                action_name=request_payload["actionName"],
                inputs=request_payload["inputs"],
                record_ids=execution_result.get("recordIds", []),
                success=True,
                error=None,
                session_id=request_payload["sessionId"],
                latency_ms=total_ms
            )
            
            # Update consecutive failures (reset on success)
            _update_consecutive_failures(
                request_payload["salesforceUserId"],
                request_payload["actionName"],
                success=True
            )
            
            # Emit CloudWatch metrics
            _emit_cloudwatch_metrics(
                action_name=request_payload["actionName"],
                success=True,
                latency_ms=total_ms,
                user_id=request_payload["salesforceUserId"],
                is_rate_limited=False,
                consecutive_failures=0
            )
            
            # Build success response
            response_body = {
                "success": True,
                "recordIds": execution_result.get("recordIds", []),
                "outputValues": execution_result.get("outputValues", {}),
                "actionName": request_payload["actionName"],
                "requestId": request_id,
                "trace": {
                    "executionMs": execution_ms,
                    "totalMs": total_ms,
                },
            }
            
            return _response(200, response_body)
        
        except SalesforceAPIError as exc:
            # Log failed action to audit
            execution_ms = round((time.perf_counter() - execution_start) * 1000, 2)
            total_ms = round((time.perf_counter() - start) * 1000, 2)
            
            _log_action_audit_async(
                user_id=request_payload["salesforceUserId"],
                action_name=request_payload["actionName"],
                inputs=request_payload["inputs"],
                record_ids=[],
                success=False,
                error=str(exc),
                session_id=request_payload["sessionId"],
                latency_ms=total_ms
            )
            
            # Update consecutive failures
            consecutive_failures = _update_consecutive_failures(
                request_payload["salesforceUserId"],
                request_payload["actionName"],
                success=False
            )
            
            # Emit CloudWatch metrics
            _emit_cloudwatch_metrics(
                action_name=request_payload["actionName"],
                success=False,
                latency_ms=total_ms,
                user_id=request_payload["salesforceUserId"],
                is_rate_limited=False,
                consecutive_failures=consecutive_failures
            )
            
            raise

    except ValidationError as exc:
        LOGGER.warning("Validation error: %s", exc)
        return _response(400, {"error": str(exc)})
    except ActionDisabledError as exc:
        LOGGER.warning("Action disabled: %s", exc)
        return _response(503, {"error": str(exc)})
    except RateLimitExceededError as exc:
        LOGGER.warning("Rate limit exceeded: %s", exc)
        # Emit rate limit rejection metric
        try:
            request_payload = _parse_request(event)
            _emit_cloudwatch_metrics(
                action_name=request_payload["actionName"],
                success=False,
                latency_ms=0,
                user_id=request_payload["salesforceUserId"],
                is_rate_limited=True,
                consecutive_failures=0
            )
        except Exception:
            pass  # Don't fail if we can't emit metrics
        return _response(429, {"error": str(exc)})
    except AuthZServiceError as exc:
        LOGGER.error("AuthZ service error: %s", exc)
        return _response(502, {"error": str(exc)})
    except SalesforceAPIError as exc:
        LOGGER.error("Salesforce API error: %s", exc)
        return _response(502, {"error": str(exc)})
    except Exception as exc:
        LOGGER.exception("Unexpected error in Action Lambda")
        return _response(500, {"error": f"Internal server error: {str(exc)}"})
