"""Integration tests for Action Lambda handler."""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from action import index as action


class DummyContext:
    """Dummy Lambda context for testing."""
    def __init__(self, request_id="test-request-id"):
        self.aws_request_id = request_id


@pytest.fixture
def mock_env(monkeypatch):
    """Set up environment variables for testing."""
    monkeypatch.setenv("ACTION_METADATA_TABLE_NAME", "test-action-metadata")
    monkeypatch.setenv("RATE_LIMITS_TABLE_NAME", "test-rate-limits")
    monkeypatch.setenv("SALESFORCE_API_ENDPOINT", "https://test.salesforce.com")
    monkeypatch.setenv("SALESFORCE_API_VERSION", "v59.0")
    monkeypatch.setenv("SALESFORCE_ACCESS_TOKEN", "test-token-12345")


@pytest.fixture
def mock_dynamodb():
    """Mock DynamoDB resource."""
    with patch("action.index.dynamodb") as mock_db:
        yield mock_db


@pytest.fixture
def mock_requests():
    """Mock requests library."""
    with patch("requests.post") as mock_post:
        yield mock_post


def test_parse_request_valid_payload():
    """Test parsing a valid action request."""
    event = {
        "body": json.dumps({
            "actionName": "create_opportunity",
            "inputs": {
                "Name": "Test Opportunity",
                "AccountId": "001ABCDEF123456789",
                "Amount": 100000,
                "CloseDate": "2025-12-31",
                "StageName": "Prospecting"
            },
            "salesforceUserId": "005ABCDEF123456",
            "sessionId": "session-123",
            "confirmationToken": "token-abc123"
        })
    }
    
    parsed = action._parse_request(event)
    
    assert parsed["actionName"] == "create_opportunity"
    assert parsed["inputs"]["Name"] == "Test Opportunity"
    assert parsed["salesforceUserId"] == "005ABCDEF123456"
    assert parsed["sessionId"] == "session-123"
    assert parsed["confirmationToken"] == "token-abc123"


def test_parse_request_missing_action_name():
    """Test that missing actionName raises ValidationError."""
    event = {
        "body": json.dumps({
            "inputs": {},
            "salesforceUserId": "005ABCDEF123456",
            "confirmationToken": "token-abc123"
        })
    }
    
    with pytest.raises(action.ValidationError, match="actionName is required"):
        action._parse_request(event)


def test_parse_request_missing_confirmation_token():
    """Test that missing confirmationToken raises ValidationError."""
    event = {
        "body": json.dumps({
            "actionName": "create_opportunity",
            "inputs": {},
            "salesforceUserId": "005ABCDEF123456"
        })
    }
    
    with pytest.raises(action.ValidationError, match="confirmationToken is required"):
        action._parse_request(event)


def test_parse_request_invalid_salesforce_user_id():
    """Test that invalid Salesforce User ID raises ValidationError."""
    event = {
        "body": json.dumps({
            "actionName": "create_opportunity",
            "inputs": {},
            "salesforceUserId": "invalid-id",
            "confirmationToken": "token-abc123"
        })
    }
    
    with pytest.raises(action.ValidationError, match="salesforceUserId must be"):
        action._parse_request(event)


def test_validate_action_enabled_success(mock_env, mock_dynamodb):
    """Test validating an enabled action."""
    # Mock DynamoDB response
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {
            "actionName": "create_opportunity",
            "enabled": True,
            "maxPerUserPerDay": 20,
            "requiresConfirm": True,
            "flowName": "Create_Opportunity_Flow",
            "inputSchema": {
                "type": "object",
                "required": ["Name", "AccountId"],
                "properties": {
                    "Name": {"type": "string"},
                    "AccountId": {"type": "string"}
                }
            }
        }
    }
    mock_dynamodb.Table.return_value = mock_table
    
    metadata = action._validate_action_enabled("create_opportunity")
    
    assert metadata["enabled"] is True
    assert metadata["flowName"] == "Create_Opportunity_Flow"
    assert metadata["maxPerUserPerDay"] == 20


def test_validate_action_disabled(mock_env, mock_dynamodb):
    """Test that disabled action raises ActionDisabledError."""
    # Mock DynamoDB response
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {
            "actionName": "create_opportunity",
            "enabled": False
        }
    }
    mock_dynamodb.Table.return_value = mock_table
    
    with pytest.raises(action.ActionDisabledError, match="temporarily unavailable"):
        action._validate_action_enabled("create_opportunity")


def test_validate_action_not_found(mock_env, mock_dynamodb):
    """Test that non-existent action raises ActionDisabledError."""
    # Mock DynamoDB response
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}
    mock_dynamodb.Table.return_value = mock_table
    
    with pytest.raises(action.ActionDisabledError, match="not registered"):
        action._validate_action_enabled("unknown_action")


def test_validate_inputs_against_schema_success():
    """Test successful input validation."""
    inputs = {
        "Name": "Test Opportunity",
        "AccountId": "001ABCDEF123456789",
        "Amount": 100000
    }
    
    schema = {
        "type": "object",
        "required": ["Name", "AccountId"],
        "properties": {
            "Name": {"type": "string", "maxLength": 120},
            "AccountId": {"type": "string", "pattern": "^001[a-zA-Z0-9]{15}$"},
            "Amount": {"type": "number", "minimum": 0}
        }
    }
    
    # Should not raise
    action._validate_inputs_against_schema(inputs, schema)


def test_validate_inputs_missing_required_field():
    """Test validation fails for missing required field."""
    inputs = {
        "Name": "Test Opportunity"
    }
    
    schema = {
        "type": "object",
        "required": ["Name", "AccountId"],
        "properties": {
            "Name": {"type": "string"},
            "AccountId": {"type": "string"}
        }
    }
    
    with pytest.raises(action.ValidationError, match="Required field 'AccountId' is missing"):
        action._validate_inputs_against_schema(inputs, schema)


def test_validate_inputs_wrong_type():
    """Test validation fails for wrong field type."""
    inputs = {
        "Name": "Test Opportunity",
        "Amount": "not-a-number"
    }
    
    schema = {
        "type": "object",
        "properties": {
            "Name": {"type": "string"},
            "Amount": {"type": "number"}
        }
    }
    
    with pytest.raises(action.ValidationError, match="must be a number"):
        action._validate_inputs_against_schema(inputs, schema)


def test_validate_inputs_exceeds_max_length():
    """Test validation fails for string exceeding maxLength."""
    inputs = {
        "Name": "A" * 150
    }
    
    schema = {
        "type": "object",
        "properties": {
            "Name": {"type": "string", "maxLength": 120}
        }
    }
    
    with pytest.raises(action.ValidationError, match="exceeds maximum length"):
        action._validate_inputs_against_schema(inputs, schema)


def test_validate_inputs_invalid_enum():
    """Test validation fails for invalid enum value."""
    inputs = {
        "StageName": "InvalidStage"
    }
    
    schema = {
        "type": "object",
        "properties": {
            "StageName": {
                "type": "string",
                "enum": ["Prospecting", "Qualification", "Proposal"]
            }
        }
    }
    
    with pytest.raises(action.ValidationError, match="must be one of"):
        action._validate_inputs_against_schema(inputs, schema)


def test_check_rate_limit_within_limit(mock_env, mock_dynamodb):
    """Test rate limit check when user is within limit."""
    # Mock DynamoDB response
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {
            "userId_actionName_date": "005ABCDEF123456_create_opportunity_2025-11-13",
            "count": 5
        }
    }
    mock_dynamodb.Table.return_value = mock_table
    
    count = action._check_rate_limit("005ABCDEF123456", "create_opportunity", 20)
    
    assert count == 5


def test_check_rate_limit_exceeded(mock_env, mock_dynamodb):
    """Test rate limit check when user exceeds limit."""
    # Mock DynamoDB response
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {
            "userId_actionName_date": "005ABCDEF123456_create_opportunity_2025-11-13",
            "count": 20
        }
    }
    mock_dynamodb.Table.return_value = mock_table
    
    with pytest.raises(action.RateLimitExceededError, match="daily limit"):
        action._check_rate_limit("005ABCDEF123456", "create_opportunity", 20)


def test_check_rate_limit_first_request(mock_env, mock_dynamodb):
    """Test rate limit check for first request of the day."""
    # Mock DynamoDB response - no existing record
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}
    mock_dynamodb.Table.return_value = mock_table
    
    count = action._check_rate_limit("005ABCDEF123456", "create_opportunity", 20)
    
    assert count == 0


def test_increment_rate_limit(mock_env, mock_dynamodb):
    """Test incrementing rate limit counter."""
    mock_table = MagicMock()
    mock_dynamodb.Table.return_value = mock_table
    
    action._increment_rate_limit("005ABCDEF123456", "create_opportunity")
    
    # Verify update_item was called
    mock_table.update_item.assert_called_once()
    call_args = mock_table.update_item.call_args
    assert "userId_actionName_date" in call_args[1]["Key"]


def test_invoke_salesforce_flow_success(mock_env, mock_requests):
    """Test successful Flow invocation."""
    # Mock successful Flow response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "isSuccess": True,
            "outputValues": {
                "id": "006NEWRECORD123456",
                "Name": "Test Opportunity"
            },
            "errors": []
        }
    ]
    mock_requests.return_value = mock_response
    
    result = action._invoke_salesforce_flow(
        "Create_Opportunity_Flow",
        {"Name": "Test Opportunity", "AccountId": "001ABCDEF123456789"},
        "005ABCDEF123456"
    )
    
    assert result["success"] is True
    assert result["outputValues"]["id"] == "006NEWRECORD123456"


def test_invoke_salesforce_flow_failure(mock_env, mock_requests):
    """Test Flow invocation failure."""
    # Mock failed Flow response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "isSuccess": False,
            "outputValues": {},
            "errors": [
                {"message": "Required field missing: AccountId"}
            ]
        }
    ]
    mock_requests.return_value = mock_response
    
    with pytest.raises(action.SalesforceAPIError, match="Required field missing"):
        action._invoke_salesforce_flow(
            "Create_Opportunity_Flow",
            {"Name": "Test Opportunity"},
            "005ABCDEF123456"
        )


def test_invoke_salesforce_flow_http_error(mock_env, mock_requests):
    """Test Flow invocation with HTTP error."""
    # Mock HTTP error response
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    mock_response.json.return_value = [
        {"message": "Invalid Flow name"}
    ]
    mock_requests.return_value = mock_response
    
    with pytest.raises(action.SalesforceAPIError, match="Invalid Flow name"):
        action._invoke_salesforce_flow(
            "Invalid_Flow",
            {},
            "005ABCDEF123456"
        )


def test_lambda_handler_success(mock_env, mock_dynamodb, mock_requests):
    """Test successful action execution end-to-end."""
    # Mock action metadata
    mock_table = MagicMock()
    mock_table.get_item.side_effect = [
        # First call: get action metadata
        {
            "Item": {
                "actionName": "create_opportunity",
                "enabled": True,
                "maxPerUserPerDay": 20,
                "flowName": "Create_Opportunity_Flow",
                "inputSchema": {
                    "type": "object",
                    "required": ["Name", "AccountId"],
                    "properties": {
                        "Name": {"type": "string"},
                        "AccountId": {"type": "string"}
                    }
                }
            }
        },
        # Second call: check rate limit
        {
            "Item": {
                "count": 5
            }
        }
    ]
    mock_dynamodb.Table.return_value = mock_table
    
    # Mock successful Flow response
    mock_flow_response = MagicMock()
    mock_flow_response.status_code = 200
    mock_flow_response.json.return_value = [
        {
            "isSuccess": True,
            "outputValues": {
                "id": "006NEWRECORD123456"
            },
            "errors": []
        }
    ]
    
    # Mock audit record creation
    mock_audit_response = MagicMock()
    mock_audit_response.status_code = 201
    mock_audit_response.json.return_value = {"id": "audit123"}
    
    mock_requests.side_effect = [mock_flow_response, mock_audit_response]
    
    event = {
        "body": json.dumps({
            "actionName": "create_opportunity",
            "inputs": {
                "Name": "Test Opportunity",
                "AccountId": "001ABCDEF123456789"
            },
            "salesforceUserId": "005ABCDEF123456",
            "sessionId": "session-123",
            "confirmationToken": "token-abc123"
        })
    }
    
    response = action.lambda_handler(event, DummyContext())
    
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["success"] is True
    assert body["recordIds"] == ["006NEWRECORD123456"]
    assert "trace" in body
    assert "executionMs" in body["trace"]


def test_lambda_handler_validation_error(mock_env):
    """Test lambda handler with validation error."""
    event = {
        "body": json.dumps({
            "actionName": "",  # Invalid: empty action name
            "inputs": {},
            "salesforceUserId": "005ABCDEF123456",
            "confirmationToken": "token-abc123"
        })
    }
    
    response = action.lambda_handler(event, DummyContext())
    
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert "error" in body


def test_lambda_handler_action_disabled(mock_env, mock_dynamodb):
    """Test lambda handler with disabled action."""
    # Mock disabled action
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {
            "actionName": "create_opportunity",
            "enabled": False
        }
    }
    mock_dynamodb.Table.return_value = mock_table
    
    event = {
        "body": json.dumps({
            "actionName": "create_opportunity",
            "inputs": {
                "Name": "Test Opportunity",
                "AccountId": "001ABCDEF123456789"
            },
            "salesforceUserId": "005ABCDEF123456",
            "confirmationToken": "token-abc123"
        })
    }
    
    response = action.lambda_handler(event, DummyContext())
    
    assert response["statusCode"] == 503
    body = json.loads(response["body"])
    assert "temporarily unavailable" in body["error"]


def test_lambda_handler_rate_limit_exceeded(mock_env, mock_dynamodb):
    """Test lambda handler with rate limit exceeded."""
    # Mock action metadata and rate limit
    mock_table = MagicMock()
    mock_table.get_item.side_effect = [
        # First call: get action metadata
        {
            "Item": {
                "actionName": "create_opportunity",
                "enabled": True,
                "maxPerUserPerDay": 20,
                "flowName": "Create_Opportunity_Flow",
                "inputSchema": {}
            }
        },
        # Second call: check rate limit - already at limit
        {
            "Item": {
                "count": 20
            }
        }
    ]
    mock_dynamodb.Table.return_value = mock_table
    
    event = {
        "body": json.dumps({
            "actionName": "create_opportunity",
            "inputs": {
                "Name": "Test Opportunity",
                "AccountId": "001ABCDEF123456789"
            },
            "salesforceUserId": "005ABCDEF123456",
            "confirmationToken": "token-abc123"
        })
    }
    
    response = action.lambda_handler(event, DummyContext())
    
    assert response["statusCode"] == 429
    body = json.loads(response["body"])
    assert "daily limit" in body["error"]


def test_lambda_handler_salesforce_api_error(mock_env, mock_dynamodb, mock_requests):
    """Test lambda handler with Salesforce API error."""
    # Mock action metadata
    mock_table = MagicMock()
    mock_table.get_item.side_effect = [
        # First call: get action metadata
        {
            "Item": {
                "actionName": "create_opportunity",
                "enabled": True,
                "maxPerUserPerDay": 20,
                "flowName": "Create_Opportunity_Flow",
                "inputSchema": {}
            }
        },
        # Second call: check rate limit
        {"Item": {"count": 5}}
    ]
    mock_dynamodb.Table.return_value = mock_table
    
    # Mock Flow failure
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.json.side_effect = json.JSONDecodeError("", "", 0)
    mock_requests.return_value = mock_response
    
    event = {
        "body": json.dumps({
            "actionName": "create_opportunity",
            "inputs": {
                "Name": "Test Opportunity",
                "AccountId": "001ABCDEF123456789"
            },
            "salesforceUserId": "005ABCDEF123456",
            "confirmationToken": "token-abc123"
        })
    }
    
    response = action.lambda_handler(event, DummyContext())
    
    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert "error" in body


def test_hash_pii_inputs():
    """Test PII input hashing."""
    inputs = {
        "Name": "John Doe",
        "Email": "john@example.com",
        "Phone": "555-1234"
    }
    
    hash1 = action._hash_pii_inputs(inputs)
    hash2 = action._hash_pii_inputs(inputs)
    
    # Same inputs should produce same hash
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 produces 64 hex characters


def test_check_has_pii_detects_email():
    """Test PII detection for email fields."""
    inputs = {
        "Name": "John Doe",
        "Email": "john@example.com"
    }
    
    assert action._check_has_pii(inputs) is True


def test_check_has_pii_detects_phone():
    """Test PII detection for phone fields."""
    inputs = {
        "Name": "John Doe",
        "Phone": "555-1234"
    }
    
    assert action._check_has_pii(inputs) is True


def test_check_has_pii_no_pii():
    """Test PII detection returns False for non-PII data."""
    inputs = {
        "Name": "ACME Corporation",
        "Amount": 100000,
        "Stage": "Prospecting"
    }
    
    assert action._check_has_pii(inputs) is False


def test_get_rate_limit_key_format():
    """Test rate limit key format."""
    # Test the actual function - it will use current date
    # We just verify the format is correct
    key = action._get_rate_limit_key("005ABCDEF123456", "create_opportunity")
    
    # Key should be in format: userId_actionName_YYYY-MM-DD
    parts = key.split("_")
    assert len(parts) == 4  # user_id, action, name, date
    assert parts[0] == "005ABCDEF123456"
    assert parts[1] == "create"
    assert parts[2] == "opportunity"
    # Verify date format YYYY-MM-DD
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2}", parts[3])
