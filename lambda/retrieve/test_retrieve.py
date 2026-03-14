"""Tests for Retrieve Lambda handler."""

import json
from types import SimpleNamespace

import pytest

from retrieve import index as retrieve


class DummyStream:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        if isinstance(self._payload, (bytes, bytearray)):
            return self._payload
        return json.dumps(self._payload).encode("utf-8")


class DummyLambdaClient:
    def __init__(self, status, body):
        self._status = status
        self._body = body
        self.invocations = []

    def invoke(self, **kwargs):  # pylint: disable=unused-argument
        self.invocations.append(kwargs)
        return {
            "Payload": DummyStream(
                {
                    "statusCode": self._status,
                    "body": json.dumps(self._body),
                }
            )
        }


def test_parse_request_normalizes_filters():
    event = {
        "body": json.dumps(
            {
                "query": "Find renewals",
                "salesforceUserId": "005ABCDEF123456",
                "filters": {
                    "sobject": ["Opportunity", "Case", "Invalid"],
                    "Region": "EMEA",
                    "BusinessUnit": "Enterprise",
                },
                "topK": 4,
                "recordContext": {"AccountId": "001xx"},
            }
        )
    }

    parsed = retrieve._parse_request(event)  # pylint: disable=protected-access

    assert parsed["query"] == "Find renewals"
    assert parsed["topK"] == 4
    assert parsed["filters"]["sobject"] == ["Opportunity", "Case"]
    assert parsed["filters"]["region"] == "EMEA"
    assert parsed["filters"]["businessUnit"] == "Enterprise"
    assert parsed["recordContext"] == {"AccountId": "001xx"}


class DummyBedrockClient:
    def __init__(self, retrieval_results=None):
        self._retrieval_results = retrieval_results or []
        self.retrieve_calls = []

    def retrieve(self, **kwargs):
        self.retrieve_calls.append(kwargs)
        return {"retrievalResults": self._retrieval_results}


def test_lambda_handler_returns_query_plan(monkeypatch):
    monkeypatch.setenv("AUTHZ_LAMBDA_FUNCTION_NAME", "salesforce-ai-search-authz")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")
    # Disable disambiguation to avoid disambiguation response when schema confidence is low
    monkeypatch.setenv("DISAMBIGUATION_ENABLED", "false")
    monkeypatch.setattr(retrieve, "DISAMBIGUATION_ENABLED", False)

    authz_payload = {
        "salesforceUserId": "005ABCDEF123456",
        "sharingBuckets": ["owner:005ABCDEF123456"],
        "flsProfileTags": [],
        "cached": True,
    }
    dummy_lambda_client = DummyLambdaClient(status=200, body=authz_payload)
    monkeypatch.setattr(retrieve, "lambda_client", dummy_lambda_client)

    # Mock Bedrock KB response
    bedrock_results = [
        {
            "content": {"text": "ACME renewal valued at $1.2M"},
            "location": {
                "s3Location": {"uri": "s3://bucket/Opportunity/006xx1/chunk-0"}
            },
            "metadata": {
                "recordId": "006xx1",
                "sobject": "Opportunity",
                "region": "EMEA",
            },
            "score": 0.85,
        }
    ]
    dummy_bedrock_client = DummyBedrockClient(retrieval_results=bedrock_results)
    monkeypatch.setattr(retrieve, "bedrock_agent_runtime_client", dummy_bedrock_client)

    event = {
        "body": json.dumps(
            {
                "query": "Show open opportunities",
                "salesforceUserId": "005ABCDEF123456",
                "filters": {"region": "EMEA"},
                "topK": 25,
            }
        )
    }

    response = retrieve.lambda_handler(event, SimpleNamespace(aws_request_id="test"))
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert len(body["matches"]) == 1
    assert body["matches"][0]["score"] == 0.85
    assert body["matches"][0]["metadata"]["sobject"] == "Opportunity"
    assert body["queryPlan"]["topK"] == retrieve.MAX_TOP_K
    assert (
        body["queryPlan"]["authzContext"]["sharingBuckets"]
        == authz_payload["sharingBuckets"]
    )
    assert body["queryPlan"]["filters"][0]["field"] == "region"
    assert "retrieveMs" in body["trace"]
    assert "authzMs" in body["trace"]


def test_lambda_handler_returns_502_when_authz_fails(monkeypatch):
    monkeypatch.setenv("AUTHZ_LAMBDA_FUNCTION_NAME", "salesforce-ai-search-authz")
    dummy_client = DummyLambdaClient(status=500, body={"error": "boom"})
    monkeypatch.setattr(retrieve, "lambda_client", dummy_client)

    event = {
        "body": json.dumps(
            {
                "query": "Hi",
                "salesforceUserId": "005ABCDEF123456",
            }
        )
    }

    response = retrieve.lambda_handler(event, None)
    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert body["error"].startswith("AuthZ Sidecar error")


def test_invoke_authz_sidecar_requires_env(monkeypatch):
    monkeypatch.delenv("AUTHZ_LAMBDA_FUNCTION_NAME", raising=False)
    with pytest.raises(retrieve.AuthZServiceError):
        retrieve._invoke_authz_sidecar(
            "005ABCDEF123456"
        )  # pylint: disable=protected-access


def test_parse_request_rejects_invalid_user():
    event = {
        "body": json.dumps(
            {
                "query": "Test",
                "salesforceUserId": "123",
            }
        )
    }

    with pytest.raises(retrieve.ValidationError):
        retrieve._parse_request(event)  # pylint: disable=protected-access


def test_post_filter_removes_unauthorized_matches():
    matches = [
        {
            "id": "Opportunity/006xx1/chunk-0",
            "score": 0.85,
            "text": "Public opportunity",
            "metadata": {
                "sharingBuckets": ["territory:EMEA", "role:SalesManager"],
                "flsProfileTags": [],
            },
        },
        {
            "id": "Opportunity/006xx2/chunk-0",
            "score": 0.75,
            "text": "Private opportunity",
            "metadata": {
                "sharingBuckets": ["owner:005OTHER"],
                "flsProfileTags": [],
            },
        },
        {
            "id": "Opportunity/006xx3/chunk-0",
            "score": 0.65,
            "text": "No sharing buckets",
            "metadata": {
                "sharingBuckets": [],
                "flsProfileTags": [],
            },
        },
    ]

    authz_context = {
        "sharingBuckets": ["territory:EMEA"],
        "flsProfileTags": [],
    }

    filtered = retrieve._post_filter_matches(
        matches, authz_context
    )  # pylint: disable=protected-access

    # Should keep first match (has territory:EMEA) and third match (no buckets = public)
    # Should remove second match (owner:005OTHER not in user's buckets)
    assert len(filtered) == 2
    assert filtered[0]["id"] == "Opportunity/006xx1/chunk-0"
    assert filtered[1]["id"] == "Opportunity/006xx3/chunk-0"


def test_post_filter_applies_redaction():
    matches = [
        {
            "id": "Case/500xx1/chunk-0",
            "score": 0.85,
            "text": "Sensitive case with PII: SSN 123-45-6789",
            "metadata": {
                "sharingBuckets": ["owner:005ABCDEF123456"],
                "flsProfileTags": ["profile:Admin"],
                "hasPII": True,
                "redactedText": "Sensitive case with PII: [REDACTED]",
            },
        }
    ]

    # User without Admin profile should get redacted text
    authz_context = {
        "sharingBuckets": ["owner:005ABCDEF123456"],
        "flsProfileTags": ["profile:Standard"],
    }

    filtered = retrieve._post_filter_matches(
        matches, authz_context
    )  # pylint: disable=protected-access

    assert len(filtered) == 1
    assert filtered[0]["text"] == "Sensitive case with PII: [REDACTED]"
    assert filtered[0].get("redacted") is True


class DummyS3Client:
    def __init__(self):
        self.generate_presigned_url_calls = []

    def generate_presigned_url(self, operation, Params=None, ExpiresIn=None):
        self.generate_presigned_url_calls.append(
            {"operation": operation, "Params": Params, "ExpiresIn": ExpiresIn}
        )
        bucket = Params.get("Bucket", "")
        key = Params.get("Key", "")
        return f"https://{bucket}.s3.amazonaws.com/{key}?presigned=true"


def test_generate_presigned_urls():
    matches = [
        {
            "id": "s3://my-bucket/Opportunity/006xx1/chunk-0",
            "score": 0.85,
            "text": "Test opportunity",
            "metadata": {},
        },
        {
            "id": "Opportunity/006xx2/chunk-0",  # Not an S3 URI
            "score": 0.75,
            "text": "Another opportunity",
            "metadata": {},
        },
    ]

    dummy_s3 = DummyS3Client()
    original_s3_client = retrieve.s3_client
    retrieve.s3_client = dummy_s3

    try:
        result = retrieve._generate_presigned_urls(
            matches
        )  # pylint: disable=protected-access

        # First match should have presigned URL
        assert "previewUrl" in result[0]
        assert "presigned=true" in result[0]["previewUrl"]

        # Second match should not have presigned URL (not S3 URI)
        assert "previewUrl" not in result[1]

        # Verify S3 client was called correctly
        assert len(dummy_s3.generate_presigned_url_calls) == 1
        call = dummy_s3.generate_presigned_url_calls[0]
        assert call["operation"] == "get_object"
        assert call["Params"]["Bucket"] == "my-bucket"
        assert call["Params"]["Key"] == "Opportunity/006xx1/chunk-0"
        assert call["ExpiresIn"] == 900  # 15 minutes
    finally:
        retrieve.s3_client = original_s3_client


class DummyDynamoDBTable:
    def __init__(self):
        self.items = []

    def put_item(self, Item):
        self.items.append(Item)


class DummyDynamoDBResource:
    def __init__(self):
        self.tables = {}

    def Table(self, name):
        if name not in self.tables:
            self.tables[name] = DummyDynamoDBTable()
        return self.tables[name]


def test_telemetry_logging(monkeypatch):
    monkeypatch.setenv("AUTHZ_LAMBDA_FUNCTION_NAME", "salesforce-ai-search-authz")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")
    monkeypatch.setenv("TELEMETRY_TABLE_NAME", "test-telemetry-table")

    authz_payload = {
        "salesforceUserId": "005ABCDEF123456",
        "sharingBuckets": ["owner:005ABCDEF123456"],
        "flsProfileTags": [],
        "cached": True,
    }
    dummy_lambda_client = DummyLambdaClient(status=200, body=authz_payload)
    monkeypatch.setattr(retrieve, "lambda_client", dummy_lambda_client)

    bedrock_results = [
        {
            "content": {"text": "Test result"},
            "location": {
                "s3Location": {"uri": "s3://bucket/Opportunity/006xx1/chunk-0"}
            },
            "metadata": {"recordId": "006xx1", "sobject": "Opportunity"},
            "score": 0.85,
        }
    ]
    dummy_bedrock_client = DummyBedrockClient(retrieval_results=bedrock_results)
    monkeypatch.setattr(retrieve, "bedrock_agent_runtime_client", dummy_bedrock_client)

    dummy_dynamodb = DummyDynamoDBResource()
    monkeypatch.setattr(retrieve, "dynamodb", dummy_dynamodb)

    event = {
        "body": json.dumps(
            {
                "query": "Test query",
                "salesforceUserId": "005ABCDEF123456",
                "filters": {"region": "EMEA"},
                "topK": 10,
            }
        )
    }

    response = retrieve.lambda_handler(
        event, SimpleNamespace(aws_request_id="test-request-123")
    )
    assert response["statusCode"] == 200

    body = json.loads(response["body"])
    assert "requestId" in body
    assert body["requestId"] == "test-request-123"

    # Verify telemetry was logged
    telemetry_table = dummy_dynamodb.tables.get("test-telemetry-table")
    assert telemetry_table is not None
    assert len(telemetry_table.items) == 1

    telemetry_item = telemetry_table.items[0]
    assert telemetry_item["requestId"] == "test-request-123"
    assert telemetry_item["endpoint"] == "/retrieve"
    assert telemetry_item["salesforceUserId"] == "005ABCDEF123456"
    assert telemetry_item["query"] == "Test query"
    assert telemetry_item["matchCount"] == 1
    assert telemetry_item["authzCached"] is True
    assert "retrieveMs" in telemetry_item["trace"]
    assert "postFilterMs" in telemetry_item["trace"]


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


def test_integration_query_with_multiple_filters(monkeypatch):
    """Integration test: Query with sobject, region, businessUnit, and quarter filters."""
    monkeypatch.setenv("AUTHZ_LAMBDA_FUNCTION_NAME", "salesforce-ai-search-authz")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")

    authz_payload = {
        "salesforceUserId": "005ABCDEF123456",
        "sharingBuckets": ["territory:EMEA", "role:SalesManager"],
        "flsProfileTags": ["profile:Standard"],
        "cached": False,
    }
    dummy_lambda_client = DummyLambdaClient(status=200, body=authz_payload)
    monkeypatch.setattr(retrieve, "lambda_client", dummy_lambda_client)

    bedrock_results = [
        {
            "content": {"text": "ACME opportunity in EMEA Enterprise Q1"},
            "location": {
                "s3Location": {"uri": "s3://bucket/Opportunity/006xx1/chunk-0"}
            },
            "metadata": {
                "recordId": "006xx1",
                "sobject": "Opportunity",
                "region": "EMEA",
                "businessUnit": "Enterprise",
                "quarter": "Q1",
                "sharingBuckets": ["territory:EMEA"],
            },
            "score": 0.92,
        },
        {
            "content": {"text": "ACME case in EMEA Enterprise Q1"},
            "location": {"s3Location": {"uri": "s3://bucket/Case/500xx1/chunk-0"}},
            "metadata": {
                "recordId": "500xx1",
                "sobject": "Case",
                "region": "EMEA",
                "businessUnit": "Enterprise",
                "quarter": "Q1",
                "sharingBuckets": ["territory:EMEA"],
            },
            "score": 0.88,
        },
    ]
    dummy_bedrock_client = DummyBedrockClient(retrieval_results=bedrock_results)
    monkeypatch.setattr(retrieve, "bedrock_agent_runtime_client", dummy_bedrock_client)

    event = {
        "body": json.dumps(
            {
                "query": "Show ACME data",
                "salesforceUserId": "005ABCDEF123456",
                "filters": {
                    "sobject": ["Opportunity", "Case"],
                    "region": "EMEA",
                    "businessUnit": "Enterprise",
                    "quarter": "Q1",
                },
                "topK": 10,
            }
        )
    }

    response = retrieve.lambda_handler(
        event, SimpleNamespace(aws_request_id="test-integration-1")
    )
    assert response["statusCode"] == 200

    body = json.loads(response["body"])
    assert len(body["matches"]) == 2
    assert body["matches"][0]["metadata"]["sobject"] == "Opportunity"
    assert body["matches"][1]["metadata"]["sobject"] == "Case"

    # Verify all filters were applied in query plan
    query_plan = body["queryPlan"]
    filter_fields = {f["field"] for f in query_plan["filters"]}
    assert "sobject" in filter_fields
    assert "region" in filter_fields
    assert "businessUnit" in filter_fields
    assert "quarter" in filter_fields


def test_integration_authorization_filtering_different_users(monkeypatch):
    """Integration test: Different users with different sharing buckets see different results."""
    monkeypatch.setenv("AUTHZ_LAMBDA_FUNCTION_NAME", "salesforce-ai-search-authz")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")
    # Disable disambiguation to avoid disambiguation response when schema confidence is low
    monkeypatch.setenv("DISAMBIGUATION_ENABLED", "false")
    monkeypatch.setattr(retrieve, "DISAMBIGUATION_ENABLED", False)

    # Bedrock returns 3 opportunities with different sharing buckets
    bedrock_results = [
        {
            "content": {"text": "Public opportunity"},
            "location": {
                "s3Location": {"uri": "s3://bucket/Opportunity/006xx1/chunk-0"}
            },
            "metadata": {
                "recordId": "006xx1",
                "sobject": "Opportunity",
                "sharingBuckets": [],  # Public
            },
            "score": 0.90,
        },
        {
            "content": {"text": "EMEA territory opportunity"},
            "location": {
                "s3Location": {"uri": "s3://bucket/Opportunity/006xx2/chunk-0"}
            },
            "metadata": {
                "recordId": "006xx2",
                "sobject": "Opportunity",
                "sharingBuckets": ["territory:EMEA"],
            },
            "score": 0.85,
        },
        {
            "content": {"text": "APAC territory opportunity"},
            "location": {
                "s3Location": {"uri": "s3://bucket/Opportunity/006xx3/chunk-0"}
            },
            "metadata": {
                "recordId": "006xx3",
                "sobject": "Opportunity",
                "sharingBuckets": ["territory:APAC"],
            },
            "score": 0.80,
        },
    ]

    # Test User 1: EMEA territory
    authz_payload_user1 = {
        "salesforceUserId": "005USER1ABCDEFG",
        "sharingBuckets": ["territory:EMEA", "role:SalesRep"],
        "flsProfileTags": [],
        "cached": True,
    }
    dummy_lambda_client = DummyLambdaClient(status=200, body=authz_payload_user1)
    monkeypatch.setattr(retrieve, "lambda_client", dummy_lambda_client)

    dummy_bedrock_client = DummyBedrockClient(retrieval_results=bedrock_results)
    monkeypatch.setattr(retrieve, "bedrock_agent_runtime_client", dummy_bedrock_client)

    event_user1 = {
        "body": json.dumps(
            {
                "query": "Show opportunities",
                "salesforceUserId": "005USER1ABCDEFG",
                "topK": 10,
            }
        )
    }

    response_user1 = retrieve.lambda_handler(
        event_user1, SimpleNamespace(aws_request_id="test-user1")
    )
    assert response_user1["statusCode"] == 200

    body_user1 = json.loads(response_user1["body"])
    # User 1 should see: public (006xx1) + EMEA (006xx2) = 2 results
    assert len(body_user1["matches"]) == 2
    record_ids_user1 = {m["metadata"]["recordId"] for m in body_user1["matches"]}
    assert "006xx1" in record_ids_user1  # Public
    assert "006xx2" in record_ids_user1  # EMEA
    assert "006xx3" not in record_ids_user1  # APAC - filtered out

    # Test User 2: APAC territory
    authz_payload_user2 = {
        "salesforceUserId": "005USER2ABCDEFG",
        "sharingBuckets": ["territory:APAC", "role:SalesRep"],
        "flsProfileTags": [],
        "cached": True,
    }
    dummy_lambda_client2 = DummyLambdaClient(status=200, body=authz_payload_user2)
    monkeypatch.setattr(retrieve, "lambda_client", dummy_lambda_client2)

    event_user2 = {
        "body": json.dumps(
            {
                "query": "Show opportunities",
                "salesforceUserId": "005USER2ABCDEFG",
                "topK": 10,
            }
        )
    }

    response_user2 = retrieve.lambda_handler(
        event_user2, SimpleNamespace(aws_request_id="test-user2")
    )
    assert response_user2["statusCode"] == 200

    body_user2 = json.loads(response_user2["body"])
    # User 2 should see: public (006xx1) + APAC (006xx3) = 2 results
    assert len(body_user2["matches"]) == 2
    record_ids_user2 = {m["metadata"]["recordId"] for m in body_user2["matches"]}
    assert "006xx1" in record_ids_user2  # Public
    assert "006xx3" in record_ids_user2  # APAC
    assert "006xx2" not in record_ids_user2  # EMEA - filtered out


def test_integration_topk_clamping(monkeypatch):
    """Integration test: Verify MAX_TOP_K=20 enforcement."""
    monkeypatch.setenv("AUTHZ_LAMBDA_FUNCTION_NAME", "salesforce-ai-search-authz")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")
    # Disable disambiguation to avoid disambiguation response when schema confidence is low
    monkeypatch.setenv("DISAMBIGUATION_ENABLED", "false")
    monkeypatch.setattr(retrieve, "DISAMBIGUATION_ENABLED", False)

    authz_payload = {
        "salesforceUserId": "005ABCDEF123456",
        "sharingBuckets": ["owner:005ABCDEF123456"],
        "flsProfileTags": [],
        "cached": True,
    }
    dummy_lambda_client = DummyLambdaClient(status=200, body=authz_payload)
    monkeypatch.setattr(retrieve, "lambda_client", dummy_lambda_client)

    # Generate 25 results
    bedrock_results = [
        {
            "content": {"text": f"Result {i}"},
            "location": {
                "s3Location": {"uri": f"s3://bucket/Opportunity/006xx{i}/chunk-0"}
            },
            "metadata": {"recordId": f"006xx{i}", "sobject": "Opportunity"},
            "score": 0.9 - (i * 0.01),
        }
        for i in range(25)
    ]
    dummy_bedrock_client = DummyBedrockClient(retrieval_results=bedrock_results)
    monkeypatch.setattr(retrieve, "bedrock_agent_runtime_client", dummy_bedrock_client)

    # Request topK=50 (should be clamped to MAX_TOP_K=20)
    event = {
        "body": json.dumps(
            {
                "query": "Show all opportunities",
                "salesforceUserId": "005ABCDEF123456",
                "topK": 50,
            }
        )
    }

    response = retrieve.lambda_handler(
        event, SimpleNamespace(aws_request_id="test-topk")
    )
    assert response["statusCode"] == 200

    body = json.loads(response["body"])
    # Verify topK was clamped to MAX_TOP_K=20
    assert body["queryPlan"]["topK"] == retrieve.MAX_TOP_K
    assert body["queryPlan"]["topK"] == 20

    # Bedrock client should have been called with clamped topK
    assert len(dummy_bedrock_client.retrieve_calls) == 1
    retrieve_call = dummy_bedrock_client.retrieve_calls[0]
    assert (
        retrieve_call["retrievalConfiguration"]["vectorSearchConfiguration"][
            "numberOfResults"
        ]
        == 20
    )


def test_integration_filter_normalization_aliases(monkeypatch):
    """Integration test: Verify filter aliases are normalized correctly."""
    monkeypatch.setenv("AUTHZ_LAMBDA_FUNCTION_NAME", "salesforce-ai-search-authz")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")

    authz_payload = {
        "salesforceUserId": "005ABCDEF123456",
        "sharingBuckets": ["owner:005ABCDEF123456"],
        "flsProfileTags": [],
        "cached": True,
    }
    dummy_lambda_client = DummyLambdaClient(status=200, body=authz_payload)
    monkeypatch.setattr(retrieve, "lambda_client", dummy_lambda_client)

    bedrock_results = [
        {
            "content": {"text": "Test result"},
            "location": {
                "s3Location": {"uri": "s3://bucket/Opportunity/006xx1/chunk-0"}
            },
            "metadata": {"recordId": "006xx1", "sobject": "Opportunity"},
            "score": 0.85,
        }
    ]
    dummy_bedrock_client = DummyBedrockClient(retrieval_results=bedrock_results)
    monkeypatch.setattr(retrieve, "bedrock_agent_runtime_client", dummy_bedrock_client)

    # Use various filter aliases
    event = {
        "body": json.dumps(
            {
                "query": "Test query",
                "salesforceUserId": "005ABCDEF123456",
                "filters": {
                    "sobjects": ["Opportunity", "Case"],  # Alias: sobjects → sobject
                    "Region": "EMEA",  # Alias: Region → region
                    "BusinessUnit": "Enterprise",  # Alias: BusinessUnit → businessUnit
                    "Quarter": "Q1",  # Alias: Quarter → quarter
                },
                "topK": 10,
            }
        )
    }

    response = retrieve.lambda_handler(
        event, SimpleNamespace(aws_request_id="test-aliases")
    )
    assert response["statusCode"] == 200

    body = json.loads(response["body"])
    query_plan = body["queryPlan"]

    # Verify filters were normalized to canonical keys
    filter_map = {f["field"]: f for f in query_plan["filters"]}

    # Check sobject filter (normalized from "sobjects")
    assert "sobject" in filter_map
    sobject_filter = filter_map["sobject"]
    assert sobject_filter["operator"] == "IN"
    assert set(sobject_filter["values"]) == {"Opportunity", "Case"}

    # Check region filter (normalized from "Region")
    assert "region" in filter_map
    region_filter = filter_map["region"]
    assert region_filter["operator"] == "EQ"
    assert region_filter["value"] == "EMEA"

    # Check businessUnit filter (normalized from "BusinessUnit")
    assert "businessUnit" in filter_map
    bu_filter = filter_map["businessUnit"]
    assert bu_filter["operator"] == "EQ"
    assert bu_filter["value"] == "Enterprise"

    # Check quarter filter (normalized from "Quarter")
    assert "quarter" in filter_map
    quarter_filter = filter_map["quarter"]
    assert quarter_filter["operator"] == "EQ"
    assert quarter_filter["value"] == "Q1"


def test_integration_invalid_salesforce_user_id_rejection(monkeypatch):
    """Integration test: Verify invalid Salesforce User IDs are rejected."""
    monkeypatch.setenv("AUTHZ_LAMBDA_FUNCTION_NAME", "salesforce-ai-search-authz")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")

    # Test various invalid user IDs
    invalid_user_ids = [
        "123",  # Too short
        "005",  # Too short
        "005ABCDEF",  # Too short (only 9 chars)
        "001ABCDEF123456",  # Wrong prefix (001 is Account)
        "005ABCDEF12345678901",  # Too long
        "",  # Empty
        None,  # None
        "not-a-user-id",  # Invalid format
    ]

    for invalid_id in invalid_user_ids:
        event = {
            "body": json.dumps(
                {
                    "query": "Test query",
                    "salesforceUserId": invalid_id,
                    "topK": 10,
                }
            )
        }

        response = retrieve.lambda_handler(
            event, SimpleNamespace(aws_request_id="test-invalid-id")
        )
        assert response["statusCode"] == 400

        body = json.loads(response["body"])
        assert "error" in body
        assert "salesforceUserId" in body["error"]


def test_integration_performance_latency_targets(monkeypatch):
    """Integration test: Verify performance against latency targets."""
    monkeypatch.setenv("AUTHZ_LAMBDA_FUNCTION_NAME", "salesforce-ai-search-authz")
    monkeypatch.setenv("KNOWLEDGE_BASE_ID", "test-kb-id")
    monkeypatch.setenv("TELEMETRY_TABLE_NAME", "test-telemetry-table")
    # Disable disambiguation to avoid disambiguation response when schema confidence is low
    monkeypatch.setenv("DISAMBIGUATION_ENABLED", "false")
    monkeypatch.setattr(retrieve, "DISAMBIGUATION_ENABLED", False)

    authz_payload = {
        "salesforceUserId": "005ABCDEF123456",
        "sharingBuckets": ["territory:EMEA"],
        "flsProfileTags": ["profile:Standard"],
        "cached": True,
    }
    dummy_lambda_client = DummyLambdaClient(status=200, body=authz_payload)
    monkeypatch.setattr(retrieve, "lambda_client", dummy_lambda_client)

    # Generate realistic result set
    bedrock_results = [
        {
            "content": {"text": f"Opportunity {i} with detailed description"},
            "location": {
                "s3Location": {"uri": f"s3://bucket/Opportunity/006xx{i}/chunk-0"}
            },
            "metadata": {
                "recordId": f"006xx{i}",
                "sobject": "Opportunity",
                "region": "EMEA",
                "sharingBuckets": ["territory:EMEA"],
            },
            "score": 0.9 - (i * 0.05),
        }
        for i in range(8)
    ]
    dummy_bedrock_client = DummyBedrockClient(retrieval_results=bedrock_results)
    monkeypatch.setattr(retrieve, "bedrock_agent_runtime_client", dummy_bedrock_client)

    dummy_dynamodb = DummyDynamoDBResource()
    monkeypatch.setattr(retrieve, "dynamodb", dummy_dynamodb)

    event = {
        "body": json.dumps(
            {
                "query": "Show open opportunities in EMEA",
                "salesforceUserId": "005ABCDEF123456",
                "filters": {"region": "EMEA"},
                "topK": 8,
            }
        )
    }

    response = retrieve.lambda_handler(
        event, SimpleNamespace(aws_request_id="test-perf")
    )
    assert response["statusCode"] == 200

    body = json.loads(response["body"])
    trace = body["trace"]

    # Verify timing metrics are present
    assert "authzMs" in trace
    assert "retrieveMs" in trace
    assert "postFilterMs" in trace
    assert "totalMs" in trace

    # Performance targets from requirements (Requirement 8.1):
    # p95 first token latency: ≤800ms (for /answer endpoint)
    # For /retrieve endpoint, we expect faster response
    # Target: p95 latency ≤400ms (as noted in design doc)

    # In this test with mocked services, total latency should be very fast
    # In production, we'd measure against actual targets
    # Note: Query decomposition may involve LLM calls which can be slow in test environments
    # Using a higher threshold (5000ms) to account for LLM latency in test environments
    assert (
        trace["totalMs"] < 5000
    )  # Sanity check for test environment (includes LLM latency)

    # Verify all timing components are reasonable
    assert trace["authzMs"] >= 0
    assert trace["retrieveMs"] >= 0
    assert trace["postFilterMs"] >= 0
    assert trace["presignedUrlMs"] >= 0

    # Verify pre/post filter counts
    assert trace["preFilterCount"] == 8
    assert trace["postFilterCount"] == 8  # All should pass authz

    # Verify matches were returned
    assert len(body["matches"]) == 8


class TestDecimalEncoder:
    """Tests for DecimalEncoder JSON serialization."""

    def test_decimal_encoder_handles_decimals(self):
        """Test that Decimals are serialized to floats."""
        from decimal import Decimal

        body = {"value": Decimal("123.45")}
        result = json.dumps(body, cls=retrieve.DecimalEncoder)
        parsed = json.loads(result)
        assert parsed["value"] == 123.45

    def test_decimal_encoder_handles_dataclasses(self):
        """Test that dataclass instances are serialized to dicts.

        This test verifies the fix for the GeoExpansion serialization error
        that caused blank UI responses.
        """
        from dataclasses import dataclass
        from typing import List

        @dataclass
        class TestGeoExpansion:
            cities: List[str]
            states: List[str]
            original: str

        geo = TestGeoExpansion(
            cities=["Plano", "Dallas"],
            states=["TX"],
            original="DFW"
        )

        body = {
            "queryPlan": {
                "predicates": [{"field": "location", "value": geo}]
            }
        }

        # This should not raise TypeError
        result = json.dumps(body, cls=retrieve.DecimalEncoder)
        parsed = json.loads(result)

        assert parsed["queryPlan"]["predicates"][0]["value"]["cities"] == ["Plano", "Dallas"]
        assert parsed["queryPlan"]["predicates"][0]["value"]["states"] == ["TX"]
        assert parsed["queryPlan"]["predicates"][0]["value"]["original"] == "DFW"

    def test_decimal_encoder_handles_nested_dataclasses(self):
        """Test that nested dataclass instances are serialized correctly."""
        from dataclasses import dataclass

        @dataclass
        class Inner:
            value: str

        @dataclass
        class Outer:
            inner: Inner
            name: str

        obj = Outer(inner=Inner(value="test"), name="outer")
        body = {"data": obj}

        result = json.dumps(body, cls=retrieve.DecimalEncoder)
        parsed = json.loads(result)

        assert parsed["data"]["inner"]["value"] == "test"
        assert parsed["data"]["name"] == "outer"
