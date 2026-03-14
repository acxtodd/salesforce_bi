import json
import os
import pytest
from unittest.mock import MagicMock, patch, ANY
from botocore.exceptions import ClientError
from answer.index import lambda_handler

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("RETRIEVE_LAMBDA_FUNCTION_NAME", "retrieve-lambda")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
    monkeypatch.setenv("SESSIONS_TABLE_NAME", "sessions-table")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

@pytest.fixture
def mock_lambda_client():
    with patch("answer.index.lambda_client") as mock:
        yield mock

@pytest.fixture
def mock_bedrock_client():
    with patch("answer.index.bedrock_runtime_client") as mock:
        yield mock

@pytest.fixture
def mock_dynamodb():
    with patch("answer.index.dynamodb") as mock:
        yield mock

@pytest.fixture
def valid_event():
    return {
        "body": json.dumps({
            "query": "What is the status of the ACME deal?",
            "salesforceUserId": "005xx0000012345",
            "sessionId": "test-session-id",
            "topK": 5
        })
    }

class TestAnswerIntegration:
    
    def test_success_path(self, mock_env, mock_lambda_client, mock_bedrock_client, mock_dynamodb, valid_event):
        # Mock Retrieve Lambda response
        retrieve_response = {
            "statusCode": 200,
            "body": {
                "matches": [
                    {
                        "text": "The ACME deal is in negotiation stage.",
                        "metadata": {"sobject": "Opportunity", "recordId": "006xx0000012345"}
                    }
                ]
            }
        }
        mock_lambda_client.invoke.return_value = {
            "Payload": MagicMock(read=lambda: json.dumps(retrieve_response).encode("utf-8"))
        }

        # Mock Bedrock streaming response
        mock_stream = MagicMock()
        mock_stream.__iter__.return_value = [
            {"chunk": {"bytes": json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "The deal"}}).encode()}},
            {"chunk": {"bytes": json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": " is in negotiation."}}).encode()}},
            {"chunk": {"bytes": json.dumps({"type": "message_stop"}).encode()}}
        ]
        mock_bedrock_client.invoke_model_with_response_stream.return_value = {"body": mock_stream}

        # Mock DynamoDB table
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        # Execute handler
        response = lambda_handler(valid_event, None)

        # Verify response
        assert response["statusCode"] == 200
        assert response["headers"]["Content-Type"] == "text/event-stream"
        
        body = response["body"]
        assert "event: token" in body
        assert "The deal" in body
        assert "is in negotiation" in body
        assert "event: done" in body

        # Verify Retrieve Lambda call
        mock_lambda_client.invoke.assert_called_once()
        call_args = mock_lambda_client.invoke.call_args
        payload = json.loads(call_args[1]["Payload"])
        assert payload["query"] == "What is the status of the ACME deal?"

        # Verify Bedrock call
        mock_bedrock_client.invoke_model_with_response_stream.assert_called_once()
        
        # Verify DynamoDB persistence
        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["sessionId"] == "test-session-id"
        assert item["query"] == "What is the status of the ACME deal?"
        assert item["answer"] == "The deal is in negotiation."

    def test_validation_error(self, mock_env):
        event = {"body": json.dumps({})}  # Missing required fields
        response = lambda_handler(event, None)
        
        assert response["statusCode"] == 400
        assert "error" in response["body"]

    def test_retrieval_error(self, mock_env, mock_lambda_client, valid_event):
        # Mock Retrieve Lambda failure
        mock_lambda_client.invoke.side_effect = ClientError(
            {"Error": {"Code": "ServiceException", "Message": "Lambda invocation failed"}},
            "Invoke"
        )
        
        response = lambda_handler(valid_event, None)
        
        assert response["statusCode"] == 502
        assert "Failed to invoke Retrieve Lambda" in response["body"]

    def test_bedrock_error(self, mock_env, mock_lambda_client, mock_bedrock_client, valid_event):
        # Mock Retrieve Lambda success
        retrieve_response = {
            "statusCode": 200,
            "body": {"matches": [{"text": "Context", "metadata": {"sobject": "Case", "recordId": "500xx"}}]}
        }
        mock_lambda_client.invoke.return_value = {
            "Payload": MagicMock(read=lambda: json.dumps(retrieve_response).encode("utf-8"))
        }

        # Mock Bedrock failure
        mock_bedrock_client.invoke_model_with_response_stream.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Bedrock overloaded"}},
            "InvokeModelWithResponseStream"
        )
        
        response = lambda_handler(valid_event, None)
        
        assert response["statusCode"] == 503
        assert "Failed to generate answer" in response["body"]

    def test_empty_context(self, mock_env, mock_lambda_client, valid_event):
        # Mock Retrieve Lambda returning no matches
        retrieve_response = {
            "statusCode": 200,
            "body": {"matches": []}
        }
        mock_lambda_client.invoke.return_value = {
            "Payload": MagicMock(read=lambda: json.dumps(retrieve_response).encode("utf-8"))
        }
        
        response = lambda_handler(valid_event, None)
        
        assert response["statusCode"] == 200
        assert "I don't have enough information" in response["body"]
        assert "reason" in response["body"]
        assert "no_accessible_results" in response["body"]
