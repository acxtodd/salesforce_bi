"""
Unit tests for AuthZ Sidecar Lambda
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
authz_dir = os.path.dirname(__file__)
sys.path.insert(0, authz_dir)


def _ensure_authz_index(force_reload=False):
    """Ensure we have the correct authz/index.py module loaded.

    Args:
        force_reload: If True, always reload the module even if it's already correct.
    """
    authz_dir = os.path.dirname(__file__)
    # Remove any existing authz_dir entries to avoid duplicates
    sys.path = [p for p in sys.path if p != authz_dir]
    sys.path.insert(0, authz_dir)

    # Check if the correct module is already loaded
    if "index" in sys.modules and not force_reload:
        current_index = sys.modules["index"]
        if hasattr(current_index, "__file__") and "authz" in current_index.__file__:
            return current_index

    # Remove any cached 'index' module to ensure we import the correct one
    if "index" in sys.modules:
        del sys.modules["index"]

    import index as idx

    return idx


# Initial import
index = _ensure_authz_index()


class TestAuthZSidecar:
    """Test suite for AuthZ Sidecar Lambda functions"""

    def test_generate_chunk_id_format(self):
        """Test sharing bucket tag format"""
        user_id = "005xx000001234567"

        # Test owner bucket
        owner_bucket = f"owner:{user_id}"
        assert owner_bucket == "owner:005xx000001234567"

        # Test role bucket
        role_id = "00Exx000000ABCD"
        role_bucket = f"role:{role_id}"
        assert role_bucket == "role:00Exx000000ABCD"

        # Test territory bucket
        territory_id = "0Mxxx000000EFGH"
        territory_bucket = f"territory:{territory_id}"
        assert territory_bucket == "territory:0Mxxx000000EFGH"

    @patch("index.query_salesforce")
    def test_get_user_info_success(self, mock_query):
        """Test successful user info retrieval"""
        mock_query.return_value = {
            "records": [
                {
                    "Id": "005xx000001234567",
                    "Name": "John Doe",
                    "UserRoleId": "00Exx000000ABCD",
                    "UserRole": {"Name": "SalesManager"},
                    "ProfileId": "00exx000000WXYZ",
                    "Profile": {"Name": "Standard User"},
                    "IsActive": True,
                    "Email": "john.doe@example.com",
                }
            ]
        }

        result = index.get_user_info("005xx000001234567", "fake_token")

        assert result is not None
        assert result["Id"] == "005xx000001234567"
        assert result["UserRoleId"] == "00Exx000000ABCD"
        assert result["IsActive"] is True

    @patch("index.query_salesforce")
    def test_get_user_info_not_found(self, mock_query):
        """Test user not found scenario"""
        mock_query.return_value = {"records": []}

        result = index.get_user_info("005xx000001234567", "fake_token")

        assert result is None

    @patch("index.query_salesforce")
    def test_get_user_territories(self, mock_query):
        """Test territory retrieval"""
        mock_query.return_value = {
            "records": [
                {"TerritoryId": "0Mxxx000000EFGH", "Territory": {"Name": "EMEA"}},
                {"TerritoryId": "0Mxxx000000IJKL", "Territory": {"Name": "APAC"}},
            ]
        }

        result = index.get_user_territories("005xx000001234567", "fake_token")

        assert len(result) == 2
        assert "0Mxxx000000EFGH" in result
        assert "0Mxxx000000IJKL" in result

    @patch("index.get_user_territories")
    @patch("index.get_user_info")
    def test_compute_sharing_buckets(self, mock_user_info, mock_territories):
        """Test sharing bucket computation"""
        mock_user_info.return_value = {
            "Id": "005xx000001234567",
            "UserRoleId": "00Exx000000ABCD",
            "UserRole": {"Name": "SalesManager"},
            "IsActive": True,
        }
        mock_territories.return_value = ["0Mxxx000000EFGH", "0Mxxx000000IJKL"]

        result = index.compute_sharing_buckets("005xx000001234567", "fake_token")

        assert "owner:005xx000001234567" in result
        assert "role:00Exx000000ABCD" in result
        assert "role_name:SalesManager" in result
        assert "territory:0Mxxx000000EFGH" in result
        assert "territory:0Mxxx000000IJKL" in result

    @patch("index.get_user_territories")
    @patch("index.get_user_info")
    def test_compute_sharing_buckets_sales_rep(self, mock_user_info, mock_territories):
        """Test sharing bucket computation for Sales Rep role"""
        mock_user_info.return_value = {
            "Id": "005xx000001111111",
            "UserRoleId": "00Exx000000REPS",
            "UserRole": {"Name": "SalesRep"},
            "IsActive": True,
        }
        mock_territories.return_value = ["0Mxxx000000WEST"]

        result = index.compute_sharing_buckets("005xx000001111111", "fake_token")

        assert "owner:005xx000001111111" in result
        assert "role:00Exx000000REPS" in result
        assert "role_name:SalesRep" in result
        assert "territory:0Mxxx000000WEST" in result
        assert len(result) == 4

    @patch("index.get_user_territories")
    @patch("index.get_user_info")
    def test_compute_sharing_buckets_admin_role(self, mock_user_info, mock_territories):
        """Test sharing bucket computation for Admin role with multiple territories"""
        mock_user_info.return_value = {
            "Id": "005xx000002222222",
            "UserRoleId": "00Exx000000ADMN",
            "UserRole": {"Name": "SystemAdministrator"},
            "IsActive": True,
        }
        mock_territories.return_value = ["0Mxxx000000EMEA", "0Mxxx000000APAC", "0Mxxx000000AMER"]

        result = index.compute_sharing_buckets("005xx000002222222", "fake_token")

        assert "owner:005xx000002222222" in result
        assert "role:00Exx000000ADMN" in result
        assert "role_name:SystemAdministrator" in result
        assert "territory:0Mxxx000000EMEA" in result
        assert "territory:0Mxxx000000APAC" in result
        assert "territory:0Mxxx000000AMER" in result
        assert len(result) == 6

    @patch("index.get_user_territories")
    @patch("index.get_user_info")
    def test_compute_sharing_buckets_no_role(self, mock_user_info, mock_territories):
        """Test sharing bucket computation for user without role"""
        mock_user_info.return_value = {"Id": "005xx000003333333", "UserRoleId": None, "IsActive": True}
        mock_territories.return_value = []

        result = index.compute_sharing_buckets("005xx000003333333", "fake_token")

        assert "owner:005xx000003333333" in result
        assert len(result) == 1
        # Should not have role or territory buckets
        assert not any("role:" in bucket for bucket in result if bucket != "owner:005xx000003333333")

    @patch("index.get_user_territories")
    @patch("index.get_user_info")
    def test_compute_sharing_buckets_no_territories(self, mock_user_info, mock_territories):
        """Test sharing bucket computation for user without territories"""
        mock_user_info.return_value = {
            "Id": "005xx000004444444",
            "UserRoleId": "00Exx000000MGRS",
            "UserRole": {"Name": "Manager"},
            "IsActive": True,
        }
        mock_territories.return_value = []

        result = index.compute_sharing_buckets("005xx000004444444", "fake_token")

        assert "owner:005xx000004444444" in result
        assert "role:00Exx000000MGRS" in result
        assert "role_name:Manager" in result
        assert len(result) == 3
        # Should not have territory buckets
        assert not any("territory:" in bucket for bucket in result)

    @patch("index.get_user_info")
    def test_compute_sharing_buckets_inactive_user(self, mock_user_info):
        """Test sharing bucket computation for inactive user"""
        mock_user_info.return_value = {"Id": "005xx000001234567", "IsActive": False}

        result = index.compute_sharing_buckets("005xx000001234567", "fake_token")

        # Should only have owner bucket for inactive user
        assert len(result) == 1
        assert "owner:005xx000001234567" in result

    def test_compute_fls_profile_tags_poc(self):
        """Test FLS computation returns empty list for POC"""
        result = index.compute_fls_profile_tags("005xx000001234567", "fake_token")

        # POC: FLS is not implemented, should return empty list
        assert result == []

    def test_compute_fls_profile_tags_standard_profile(self):
        """Test FLS computation for Standard User profile (POC returns empty)"""
        result = index.compute_fls_profile_tags("005xx000001111111", "fake_token")

        # POC: FLS is not implemented, should return empty list
        assert result == []
        assert isinstance(result, list)

    def test_compute_fls_profile_tags_admin_profile(self):
        """Test FLS computation for System Administrator profile (POC returns empty)"""
        result = index.compute_fls_profile_tags("005xx000002222222", "fake_token")

        # POC: FLS is not implemented, should return empty list
        assert result == []
        assert isinstance(result, list)

    def test_compute_fls_profile_tags_custom_profile(self):
        """Test FLS computation for custom profile (POC returns empty)"""
        result = index.compute_fls_profile_tags("005xx000003333333", "fake_token")

        # POC: FLS is not implemented, should return empty list
        # In Phase 3, this would return profile-specific FLS tags
        assert result == []
        assert isinstance(result, list)

    @patch("index.dynamodb")
    def test_get_cached_authz_context_hit(self, mock_dynamodb):
        """Test cache hit scenario"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        future_ttl = int((datetime.utcnow() + timedelta(hours=12)).timestamp())
        mock_table.get_item.return_value = {
            "Item": {
                "salesforceUserId": "005xx000001234567",
                "sharingBuckets": ["owner:005xx000001234567", "role:00Exx000000ABCD"],
                "flsProfileTags": [],
                "computedAt": "2025-11-13T10:00:00Z",
                "ttl": future_ttl,
            }
        }

        result = index.get_cached_authz_context("005xx000001234567")

        assert result is not None
        assert result["salesforceUserId"] == "005xx000001234567"
        assert len(result["sharingBuckets"]) == 2

    @patch("index.dynamodb")
    def test_get_cached_authz_context_miss(self, mock_dynamodb):
        """Test cache miss scenario"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}

        result = index.get_cached_authz_context("005xx000001234567")

        assert result is None

    @patch("index.dynamodb")
    def test_get_cached_authz_context_expired(self, mock_dynamodb):
        """Test expired cache scenario"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        past_ttl = int((datetime.utcnow() - timedelta(hours=1)).timestamp())
        mock_table.get_item.return_value = {
            "Item": {
                "salesforceUserId": "005xx000001234567",
                "sharingBuckets": ["owner:005xx000001234567"],
                "flsProfileTags": [],
                "computedAt": "2025-11-12T10:00:00Z",
                "ttl": past_ttl,
            }
        }

        result = index.get_cached_authz_context("005xx000001234567")

        assert result is None

    @patch("index.dynamodb")
    def test_get_cached_authz_context_with_complex_buckets(self, mock_dynamodb):
        """Test cache hit with complex sharing buckets"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        future_ttl = int((datetime.utcnow() + timedelta(hours=20)).timestamp())
        complex_buckets = [
            "owner:005xx000001234567",
            "role:00Exx000000ABCD",
            "role_name:SalesManager",
            "territory:0Mxxx000000EMEA",
            "territory:0Mxxx000000APAC",
        ]
        mock_table.get_item.return_value = {
            "Item": {
                "salesforceUserId": "005xx000001234567",
                "sharingBuckets": complex_buckets,
                "flsProfileTags": [],
                "computedAt": "2025-11-13T08:00:00Z",
                "ttl": future_ttl,
            }
        }

        result = index.get_cached_authz_context("005xx000001234567")

        assert result is not None
        assert len(result["sharingBuckets"]) == 5
        assert "territory:0Mxxx000000EMEA" in result["sharingBuckets"]
        assert "territory:0Mxxx000000APAC" in result["sharingBuckets"]

    @patch("index.dynamodb")
    def test_get_cached_authz_context_near_expiry(self, mock_dynamodb):
        """Test cache hit when TTL is near expiry (within 1 hour)"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        # TTL expires in 30 minutes
        near_expiry_ttl = int((datetime.utcnow() + timedelta(minutes=30)).timestamp())
        mock_table.get_item.return_value = {
            "Item": {
                "salesforceUserId": "005xx000001234567",
                "sharingBuckets": ["owner:005xx000001234567", "role:00Exx000000ABCD"],
                "flsProfileTags": [],
                "computedAt": "2025-11-12T10:30:00Z",
                "ttl": near_expiry_ttl,
            }
        }

        result = index.get_cached_authz_context("005xx000001234567")

        # Should still return cached result even if near expiry
        assert result is not None
        assert result["salesforceUserId"] == "005xx000001234567"

    @patch("index.dynamodb")
    def test_get_cached_authz_context_dynamodb_error(self, mock_dynamodb):
        """Test cache retrieval when DynamoDB throws error"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.side_effect = Exception("DynamoDB connection error")

        result = index.get_cached_authz_context("005xx000001234567")

        # Should return None on error, not raise exception
        assert result is None

    @patch("index.dynamodb")
    def test_cache_authz_context(self, mock_dynamodb):
        """Test caching authorization context"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        sharing_buckets = ["owner:005xx000001234567", "role:00Exx000000ABCD"]
        fls_tags = []

        index.cache_authz_context("005xx000001234567", sharing_buckets, fls_tags)

        # Verify put_item was called
        mock_table.put_item.assert_called_once()
        call_args = mock_table.put_item.call_args[1]
        item = call_args["Item"]

        assert item["salesforceUserId"] == "005xx000001234567"
        assert item["sharingBuckets"] == sharing_buckets
        assert item["flsProfileTags"] == fls_tags
        assert "computedAt" in item
        assert "ttl" in item

    @patch("index.dynamodb")
    def test_cache_authz_context_with_territories(self, mock_dynamodb):
        """Test caching authorization context with multiple territories"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        sharing_buckets = [
            "owner:005xx000001234567",
            "role:00Exx000000ABCD",
            "role_name:SalesManager",
            "territory:0Mxxx000000EMEA",
            "territory:0Mxxx000000APAC",
            "territory:0Mxxx000000AMER",
        ]
        fls_tags = []

        index.cache_authz_context("005xx000001234567", sharing_buckets, fls_tags)

        mock_table.put_item.assert_called_once()
        call_args = mock_table.put_item.call_args[1]
        item = call_args["Item"]

        assert len(item["sharingBuckets"]) == 6
        assert "territory:0Mxxx000000EMEA" in item["sharingBuckets"]

    @patch("index.dynamodb")
    def test_cache_authz_context_ttl_24_hours(self, mock_dynamodb):
        """Test that cached context has 24-hour TTL"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        sharing_buckets = ["owner:005xx000001234567"]
        fls_tags = []

        before_cache = datetime.utcnow()
        index.cache_authz_context("005xx000001234567", sharing_buckets, fls_tags)
        after_cache = datetime.utcnow()

        call_args = mock_table.put_item.call_args[1]
        item = call_args["Item"]

        # TTL should be approximately 24 hours from now
        expected_ttl_min = int((before_cache + timedelta(hours=24)).timestamp())
        expected_ttl_max = int((after_cache + timedelta(hours=24)).timestamp())

        assert expected_ttl_min <= item["ttl"] <= expected_ttl_max

    @patch("index.dynamodb")
    def test_cache_authz_context_error_handling(self, mock_dynamodb):
        """Test that caching errors don't raise exceptions"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.put_item.side_effect = Exception("DynamoDB write error")

        sharing_buckets = ["owner:005xx000001234567"]
        fls_tags = []

        # Should not raise exception
        try:
            index.cache_authz_context("005xx000001234567", sharing_buckets, fls_tags)
        except Exception:
            pytest.fail("cache_authz_context should not raise exceptions")

    @patch("index.dynamodb")
    def test_invalidate_cache_success(self, mock_dynamodb):
        """Test successful cache invalidation"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        result = index.invalidate_cache("005xx000001234567")

        assert result["success"] is True
        assert "invalidated" in result["message"].lower()
        mock_table.delete_item.assert_called_once_with(Key={"salesforceUserId": "005xx000001234567"})

    @patch("index.dynamodb")
    def test_invalidate_cache_error(self, mock_dynamodb):
        """Test cache invalidation error handling"""
        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.delete_item.side_effect = Exception("DynamoDB error")

        result = index.invalidate_cache("005xx000001234567")

        assert result["success"] is False
        assert "error" in result

    def test_lambda_handler_missing_user_id(self):
        """Test Lambda handler with missing user ID"""
        event = {"operation": "getAuthZContext"}

        result = index.lambda_handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "error" in body
        assert "required" in body["error"].lower()

    def test_lambda_handler_invalid_user_id(self):
        """Test Lambda handler with invalid user ID format"""
        event = {"operation": "getAuthZContext", "salesforceUserId": "invalid_id"}

        result = index.lambda_handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "error" in body
        assert "invalid" in body["error"].lower()

    @patch("index.invalidate_cache")
    def test_lambda_handler_invalidate_cache(self, mock_invalidate):
        """Test Lambda handler for cache invalidation"""
        mock_invalidate.return_value = {"success": True, "message": "Cache invalidated"}

        event = {"operation": "invalidateCache", "salesforceUserId": "005xx0000012345"}  # Valid 15-char ID

        result = index.lambda_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["success"] is True

    def test_lambda_handler_unknown_operation(self):
        """Test Lambda handler with unknown operation"""
        event = {"operation": "unknownOperation", "salesforceUserId": "005xx0000012345"}  # Valid 15-char ID

        result = index.lambda_handler(event, None)

        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "error" in body
        assert "unknown" in body["error"].lower()

    @patch("index.cache_authz_context")
    @patch("index.compute_fls_profile_tags")
    @patch("index.compute_sharing_buckets")
    @patch("index.get_salesforce_access_token")
    @patch("index.get_cached_authz_context")
    def test_get_authz_context_cache_miss_flow(
        self, mock_get_cached, mock_get_token, mock_compute_buckets, mock_compute_fls, mock_cache
    ):
        """Test full flow when cache misses - compute and cache"""
        mock_get_cached.return_value = None
        mock_get_token.return_value = "fake_access_token"
        mock_compute_buckets.return_value = [
            "owner:005xx000001234567",
            "role:00Exx000000ABCD",
            "territory:0Mxxx000000EMEA",
        ]
        mock_compute_fls.return_value = []

        result = index.get_authz_context("005xx000001234567")

        # Verify cache was checked
        mock_get_cached.assert_called_once_with("005xx000001234567")

        # Verify computation was performed
        mock_get_token.assert_called_once()
        mock_compute_buckets.assert_called_once_with("005xx000001234567", "fake_access_token")
        mock_compute_fls.assert_called_once_with("005xx000001234567", "fake_access_token")

        # Verify result was cached
        mock_cache.assert_called_once()

        # Verify result structure
        assert result["salesforceUserId"] == "005xx000001234567"
        assert len(result["sharingBuckets"]) == 3
        assert result["flsProfileTags"] == []
        assert result["cached"] is False
        assert "computedAt" in result

    @patch("index.get_cached_authz_context")
    def test_get_authz_context_cache_hit_flow(self, mock_get_cached):
        """Test full flow when cache hits - return cached data"""
        cached_data = {
            "salesforceUserId": "005xx000001234567",
            "sharingBuckets": ["owner:005xx000001234567", "role:00Exx000000ABCD"],
            "flsProfileTags": [],
            "computedAt": "2025-11-13T10:00:00Z",
            "ttl": int((datetime.utcnow() + timedelta(hours=12)).timestamp()),
        }
        mock_get_cached.return_value = cached_data

        result = index.get_authz_context("005xx000001234567")

        # Verify cache was checked
        mock_get_cached.assert_called_once_with("005xx000001234567")

        # Verify result structure
        assert result["salesforceUserId"] == "005xx000001234567"
        assert result["sharingBuckets"] == cached_data["sharingBuckets"]
        assert result["flsProfileTags"] == []
        assert result["cached"] is True
        assert result["computedAt"] == "2025-11-13T10:00:00Z"

    @patch("index.get_authz_context")
    def test_lambda_handler_get_authz_context_success(self, mock_get_authz):
        """Test Lambda handler for successful getAuthZContext operation"""
        mock_get_authz.return_value = {
            "salesforceUserId": "005xx0000012345",
            "sharingBuckets": ["owner:005xx0000012345", "role:00Exx000000ABCD"],
            "flsProfileTags": [],
            "computedAt": "2025-11-13T10:00:00Z",
            "cached": False,
        }

        event = {"operation": "getAuthZContext", "salesforceUserId": "005xx0000012345"}

        result = index.lambda_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["salesforceUserId"] == "005xx0000012345"
        assert len(body["sharingBuckets"]) == 2
        assert body["cached"] is False

    @patch("index.get_authz_context")
    def test_lambda_handler_get_authz_context_18_char_id(self, mock_get_authz):
        """Test Lambda handler with 18-character Salesforce ID"""
        mock_get_authz.return_value = {
            "salesforceUserId": "005xx000001234567A",
            "sharingBuckets": ["owner:005xx000001234567A"],
            "flsProfileTags": [],
            "computedAt": "2025-11-13T10:00:00Z",
            "cached": True,
        }

        event = {"operation": "getAuthZContext", "salesforceUserId": "005xx000001234567A"}  # 18-char ID

        result = index.lambda_handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["salesforceUserId"] == "005xx000001234567A"

    @patch("index.get_user_territories")
    @patch("index.get_user_info")
    def test_compute_sharing_buckets_user_not_found(self, mock_user_info, mock_territories):
        """Test sharing bucket computation when user is not found"""
        mock_user_info.return_value = None

        result = index.compute_sharing_buckets("005xx000009999999", "fake_token")

        # Should still return owner bucket even if user not found
        assert "owner:005xx000009999999" in result
        assert len(result) == 1

    @patch("index.get_user_territories")
    @patch("index.get_user_info")
    def test_compute_sharing_buckets_role_without_name(self, mock_user_info, mock_territories):
        """Test sharing bucket computation when role has no name"""
        mock_user_info.return_value = {
            "Id": "005xx000005555555",
            "UserRoleId": "00Exx000000NOID",
            "UserRole": {},  # No Name field
            "IsActive": True,
        }
        mock_territories.return_value = []

        result = index.compute_sharing_buckets("005xx000005555555", "fake_token")

        assert "owner:005xx000005555555" in result
        assert "role:00Exx000000NOID" in result
        # Should not have role_name bucket since name is missing
        assert not any("role_name:" in bucket for bucket in result)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# =============================================================================
# Unit Tests for StandardAuthStrategy
# Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
# =============================================================================


class TestStandardAuthStrategy:
    """Unit tests for StandardAuthStrategy class."""

    def test_init_with_sf_client(self):
        """Test initialization with provided SF client."""
        mock_client = Mock()
        strategy = index.StandardAuthStrategy(sf_client=mock_client, mode="strict")

        assert strategy._sf_client == mock_client
        assert strategy._mode == "strict"

    def test_init_default_mode(self):
        """Test initialization with default mode."""
        mock_client = Mock()
        strategy = index.StandardAuthStrategy(sf_client=mock_client)

        assert strategy._mode == "strict"

    def test_is_admin_user_system_administrator(self):
        """Test is_admin_user returns True for System Administrator profile."""
        mock_client = Mock()
        mock_client.query.return_value = {
            "records": [
                {
                    "Id": "005xx000001234567",
                    "Profile": {"Name": "System Administrator"},
                    "IsActive": True,
                }
            ]
        }

        strategy = index.StandardAuthStrategy(sf_client=mock_client, mode="strict")
        result = strategy.is_admin_user("005xx000001234567")

        assert result is True

    def test_is_admin_user_standard_user(self):
        """Test is_admin_user returns False for Standard User profile."""
        mock_client = Mock()
        mock_client.query.return_value = {
            "records": [
                {
                    "Id": "005xx000001234567",
                    "Profile": {"Name": "Standard User"},
                    "IsActive": True,
                }
            ]
        }

        strategy = index.StandardAuthStrategy(sf_client=mock_client, mode="strict")
        result = strategy.is_admin_user("005xx000001234567")

        assert result is False

    def test_is_admin_user_not_found(self):
        """Test is_admin_user returns False when user not found."""
        mock_client = Mock()
        mock_client.query.return_value = {"records": []}

        strategy = index.StandardAuthStrategy(sf_client=mock_client, mode="strict")
        result = strategy.is_admin_user("005xx000001234567")

        assert result is False

    def test_compute_sharing_buckets_includes_owner(self):
        """Test compute_sharing_buckets always includes owner bucket."""
        mock_client = Mock()
        mock_client.query.return_value = {
            "records": [
                {
                    "Id": "005xx000001234567",
                    "UserRoleId": None,
                    "IsActive": True,
                }
            ]
        }

        strategy = index.StandardAuthStrategy(sf_client=mock_client, mode="strict")
        buckets = strategy.compute_sharing_buckets("005xx000001234567")

        assert "owner:005xx000001234567" in buckets

    def test_compute_sharing_buckets_includes_role(self):
        """Test compute_sharing_buckets includes role bucket when user has role."""
        mock_client = Mock()
        # First call for user info
        mock_client.query.side_effect = [
            {
                "records": [
                    {
                        "Id": "005xx000001234567",
                        "UserRoleId": "00Exx000000ABCD",
                        "UserRole": {"Name": "SalesManager"},
                        "IsActive": True,
                    }
                ]
            },
            # Second call for subordinate roles
            {"records": []},
            # Third call for territories
            {"records": []},
            # Fourth call for groups
            {"records": []},
        ]

        strategy = index.StandardAuthStrategy(sf_client=mock_client, mode="strict")
        buckets = strategy.compute_sharing_buckets("005xx000001234567")

        assert "owner:005xx000001234567" in buckets
        assert "role:00Exx000000ABCD" in buckets
        assert "role_name:SalesManager" in buckets

    def test_compute_sharing_buckets_includes_territories(self):
        """Test compute_sharing_buckets includes territory buckets."""
        mock_client = Mock()
        mock_client.query.side_effect = [
            # User info
            {
                "records": [
                    {
                        "Id": "005xx000001234567",
                        "UserRoleId": None,
                        "IsActive": True,
                    }
                ]
            },
            # Territories
            {
                "records": [
                    {"TerritoryId": "0Mxxx000000EMEA"},
                    {"TerritoryId": "0Mxxx000000APAC"},
                ]
            },
            # Groups
            {"records": []},
        ]

        strategy = index.StandardAuthStrategy(sf_client=mock_client, mode="strict")
        buckets = strategy.compute_sharing_buckets("005xx000001234567")

        assert "territory:0Mxxx000000EMEA" in buckets
        assert "territory:0Mxxx000000APAC" in buckets

    def test_compute_sharing_buckets_includes_groups(self):
        """Test compute_sharing_buckets includes group buckets."""
        mock_client = Mock()
        mock_client.query.side_effect = [
            # User info
            {
                "records": [
                    {
                        "Id": "005xx000001234567",
                        "UserRoleId": None,
                        "IsActive": True,
                    }
                ]
            },
            # Territories
            {"records": []},
            # Groups
            {
                "records": [
                    {"GroupId": "00Gxx000000GROUP1"},
                    {"GroupId": "00Gxx000000GROUP2"},
                ]
            },
        ]

        strategy = index.StandardAuthStrategy(sf_client=mock_client, mode="strict")
        buckets = strategy.compute_sharing_buckets("005xx000001234567")

        assert "group:00Gxx000000GROUP1" in buckets
        assert "group:00Gxx000000GROUP2" in buckets

    def test_admin_profile_names_constant(self):
        """Test ADMIN_PROFILE_NAMES contains expected profiles."""
        expected_profiles = {
            "System Administrator",
            "システム管理者",
            "Systemadministrator",
        }

        assert index.StandardAuthStrategy.ADMIN_PROFILE_NAMES == expected_profiles


class TestAuthorizationModes:
    """Unit tests for authorization mode behavior."""

    def test_strict_mode_no_admin_bypass(self):
        """Test strict mode does not grant admin bypass."""
        mock_user_info = MagicMock(
            return_value={
                "Id": "005xx000001234567",
                "UserRoleId": "00Exx000000ADMIN",
                "UserRole": {"Name": "SystemAdministrator"},
                "Profile": {"Name": "System Administrator"},
                "IsActive": True,
            }
        )
        mock_territories = MagicMock(return_value=[])

        with patch.dict(os.environ, {"AUTHZ_MODE": "strict"}):
            # Reload the module to pick up the new env var
            idx = _ensure_authz_index(force_reload=True)

            with patch.object(idx, "get_user_info", mock_user_info), patch.object(
                idx, "get_user_territories", mock_territories
            ):

                buckets = idx.compute_sharing_buckets("005xx000001234567", "fake_token")

                assert "admin:all_access" not in buckets

    def test_relaxed_mode_admin_gets_bypass(self):
        """Test relaxed mode grants admin bypass."""
        mock_user_info = MagicMock(
            return_value={
                "Id": "005xx000001234567",
                "UserRoleId": "00Exx000000ADMIN",
                "UserRole": {"Name": "SystemAdministrator"},
                "Profile": {"Name": "System Administrator"},
                "IsActive": True,
            }
        )
        mock_territories = MagicMock(return_value=[])

        with patch.dict(os.environ, {"AUTHZ_MODE": "relaxed"}):
            # Reload the module to pick up the new env var
            idx = _ensure_authz_index(force_reload=True)

            with patch.object(idx, "get_user_info", mock_user_info), patch.object(
                idx, "get_user_territories", mock_territories
            ):

                buckets = idx.compute_sharing_buckets("005xx000001234567", "fake_token")

                assert "admin:all_access" in buckets

    def test_relaxed_mode_non_admin_no_bypass(self):
        """Test relaxed mode does not grant bypass to non-admins."""
        mock_user_info = MagicMock(
            return_value={
                "Id": "005xx000001234567",
                "UserRoleId": "00Exx000000SALES",
                "UserRole": {"Name": "SalesRep"},
                "Profile": {"Name": "Standard User"},
                "IsActive": True,
            }
        )
        mock_territories = MagicMock(return_value=[])

        with patch.dict(os.environ, {"AUTHZ_MODE": "relaxed"}):
            # Reload the module to pick up the new env var
            idx = _ensure_authz_index(force_reload=True)

            with patch.object(idx, "get_user_info", mock_user_info), patch.object(
                idx, "get_user_territories", mock_territories
            ):

                buckets = idx.compute_sharing_buckets("005xx000001234567", "fake_token")

                assert "admin:all_access" not in buckets


class TestAuthStrategyHelpers:
    """Unit tests for auth strategy helper functions."""

    def test_get_auth_strategy_creates_singleton(self):
        """Test get_auth_strategy creates and returns singleton."""
        index.clear_auth_strategy()

        mock_client = Mock()
        strategy1 = index.get_auth_strategy(sf_client=mock_client, mode="strict")
        strategy2 = index.get_auth_strategy()

        assert strategy1 is strategy2

    def test_get_auth_strategy_force_refresh(self):
        """Test get_auth_strategy with force_refresh creates new instance."""
        index.clear_auth_strategy()

        mock_client1 = Mock()
        mock_client2 = Mock()

        strategy1 = index.get_auth_strategy(sf_client=mock_client1, mode="strict")
        strategy2 = index.get_auth_strategy(sf_client=mock_client2, mode="relaxed", force_refresh=True)

        assert strategy1 is not strategy2
        assert strategy2._mode == "relaxed"

    def test_clear_auth_strategy(self):
        """Test clear_auth_strategy clears the singleton."""
        mock_client = Mock()
        index.get_auth_strategy(sf_client=mock_client, mode="strict")

        index.clear_auth_strategy()

        # After clearing, getting strategy should create new one
        # This would fail without a client if not cleared properly
        assert index._auth_strategy is None


class TestNoPOCHacks:
    """Tests to verify POC hacks have been removed."""

    def test_no_poc_admin_users_variable(self):
        """Verify POC_ADMIN_USERS is not defined in module."""
        assert not hasattr(index, "POC_ADMIN_USERS")

    def test_no_seed_data_owners_variable(self):
        """Verify SEED_DATA_OWNERS is not defined in module."""
        assert not hasattr(index, "SEED_DATA_OWNERS")

    def test_compute_sharing_buckets_no_hardcoded_users(self):
        """Verify compute_sharing_buckets doesn't use hardcoded user lists."""
        import inspect

        source = inspect.getsource(index.compute_sharing_buckets)

        # Remove docstring from source for checking (docstring may mention removed items)
        # Find the end of the docstring
        lines = source.split("\n")
        code_lines = []
        in_docstring = False
        docstring_count = 0
        for line in lines:
            if '"""' in line:
                docstring_count += line.count('"""')
                if docstring_count >= 2:
                    in_docstring = False
                    docstring_count = 0
                else:
                    in_docstring = True
                continue
            if not in_docstring:
                code_lines.append(line)

        code_only = "\n".join(code_lines)

        # These hardcoded user IDs should not appear in the function code
        assert "005dl00000Q6a3RAAR" not in code_only, "Old hardcoded admin user ID found"
        assert "005dl00000Q6a3R" not in code_only, "Old hardcoded admin user ID (15 char) found"
        assert "005fk0000006rG9AAI" not in code_only, "Old hardcoded seed data owner ID found"
        assert "005fk0000007zjVAAQ" not in code_only, "Old hardcoded CRE batch owner ID found"

        # Verify no list assignment with hardcoded users
        assert "POC_ADMIN_USERS = [" not in source
        assert "SEED_DATA_OWNERS = [" not in source


# =============================================================================
# Unit Tests for FLSEnforcer
# Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
# =============================================================================


class TestFLSEnforcer:
    """Unit tests for FLSEnforcer class."""

    def test_init_with_defaults(self):
        """Test FLSEnforcer initialization with default values."""
        enforcer = index.FLSEnforcer()

        assert enforcer._enabled is True
        assert enforcer._sf_client is None
        assert enforcer._memory_cache == {}

    def test_init_with_custom_values(self):
        """Test FLSEnforcer initialization with custom values."""
        mock_client = Mock()
        enforcer = index.FLSEnforcer(sf_client=mock_client, enabled=False, cache_table="custom_table")

        assert enforcer._sf_client == mock_client
        assert enforcer._enabled is False
        assert enforcer._cache_table == "custom_table"

    def test_enabled_property(self):
        """Test enabled property returns correct value."""
        enforcer_enabled = index.FLSEnforcer(enabled=True)
        enforcer_disabled = index.FLSEnforcer(enabled=False)

        assert enforcer_enabled.enabled is True
        assert enforcer_disabled.enabled is False

    def test_redact_fields_removes_non_readable(self):
        """Test redact_fields removes fields not in readable_fields."""
        enforcer = index.FLSEnforcer(enabled=True)

        record = {
            "Id": "001xx000001234567",
            "Name": "Test Account",
            "SecretField": "confidential",
            "Phone": "555-1234",
        }
        readable_fields = {"Id", "Name"}

        result = enforcer.redact_fields(record, readable_fields)

        assert "Id" in result
        assert "Name" in result
        assert "SecretField" not in result
        assert "Phone" not in result

    def test_redact_fields_preserves_readable(self):
        """Test redact_fields preserves all readable fields."""
        enforcer = index.FLSEnforcer(enabled=True)

        record = {
            "Id": "001xx000001234567",
            "Name": "Test Account",
            "Phone": "555-1234",
        }
        readable_fields = {"Id", "Name", "Phone", "Email"}  # Email not in record

        result = enforcer.redact_fields(record, readable_fields)

        assert result == record  # All fields are readable

    def test_redact_fields_disabled_returns_unchanged(self):
        """Test redact_fields returns unchanged record when disabled."""
        enforcer = index.FLSEnforcer(enabled=False)

        record = {
            "Id": "001xx000001234567",
            "SecretField": "confidential",
        }
        readable_fields = {"Id"}  # SecretField not readable

        result = enforcer.redact_fields(record, readable_fields)

        assert result == record  # Unchanged when disabled

    def test_redact_fields_empty_readable_returns_all(self):
        """Test redact_fields returns all fields when readable_fields is empty."""
        enforcer = index.FLSEnforcer(enabled=True)

        record = {
            "Id": "001xx000001234567",
            "Name": "Test",
        }

        result = enforcer.redact_fields(record, set())

        assert result == record  # Empty readable_fields means allow all

    def test_get_readable_fields_disabled_returns_empty(self):
        """Test get_readable_fields returns empty set when disabled."""
        enforcer = index.FLSEnforcer(enabled=False)

        result = enforcer.get_readable_fields("005xx000001234567", "Account")

        assert result == set()

    @patch.object(index, "dynamodb")
    def test_get_cached_fls_memory_hit(self, mock_dynamodb):
        """Test _get_cached_fls returns from memory cache."""
        enforcer = index.FLSEnforcer(enabled=True)

        # Populate memory cache
        cache_key = "005xx000001234567:Account"
        enforcer._memory_cache[cache_key] = {"readable_fields": {"Id", "Name"}}
        enforcer._memory_cache_timestamps[cache_key] = datetime.utcnow()

        result = enforcer._get_cached_fls("005xx000001234567", "Account")

        assert result == {"Id", "Name"}
        # DynamoDB should not be called
        mock_dynamodb.Table.assert_not_called()

    @patch.object(index, "dynamodb")
    def test_get_cached_fls_dynamodb_hit(self, mock_dynamodb):
        """Test _get_cached_fls returns from DynamoDB cache."""
        enforcer = index.FLSEnforcer(enabled=True)

        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        future_ttl = int((datetime.utcnow() + timedelta(hours=12)).timestamp())
        mock_table.get_item.return_value = {
            "Item": {
                "cacheKey": "005xx000001234567:Account",
                "readableFields": ["Id", "Name", "Phone"],
                "ttl": future_ttl,
            }
        }

        result = enforcer._get_cached_fls("005xx000001234567", "Account")

        assert result == {"Id", "Name", "Phone"}

    @patch.object(index, "dynamodb")
    def test_get_cached_fls_expired(self, mock_dynamodb):
        """Test _get_cached_fls returns None for expired cache."""
        enforcer = index.FLSEnforcer(enabled=True)

        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        past_ttl = int((datetime.utcnow() - timedelta(hours=1)).timestamp())
        mock_table.get_item.return_value = {
            "Item": {
                "cacheKey": "005xx000001234567:Account",
                "readableFields": ["Id", "Name"],
                "ttl": past_ttl,
            }
        }

        result = enforcer._get_cached_fls("005xx000001234567", "Account")

        assert result is None

    @patch.object(index, "dynamodb")
    def test_get_cached_fls_miss(self, mock_dynamodb):
        """Test _get_cached_fls returns None for cache miss."""
        enforcer = index.FLSEnforcer(enabled=True)

        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}  # No Item

        result = enforcer._get_cached_fls("005xx000001234567", "Account")

        assert result is None

    @patch.object(index, "dynamodb")
    def test_cache_fls_stores_correctly(self, mock_dynamodb):
        """Test _cache_fls stores data correctly."""
        enforcer = index.FLSEnforcer(enabled=True)

        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        readable_fields = {"Id", "Name", "Phone"}
        enforcer._cache_fls("005xx000001234567", "Account", readable_fields)

        # Verify put_item was called
        mock_table.put_item.assert_called_once()
        call_args = mock_table.put_item.call_args[1]
        item = call_args["Item"]

        assert item["cacheKey"] == "005xx000001234567:Account"
        assert item["userId"] == "005xx000001234567"
        assert item["sobject"] == "Account"
        assert set(item["readableFields"]) == readable_fields
        assert "ttl" in item
        assert "computedAt" in item

    @patch.object(index, "dynamodb")
    def test_cache_fls_updates_memory_cache(self, mock_dynamodb):
        """Test _cache_fls updates memory cache."""
        enforcer = index.FLSEnforcer(enabled=True)

        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        readable_fields = {"Id", "Name"}
        enforcer._cache_fls("005xx000001234567", "Account", readable_fields)

        cache_key = "005xx000001234567:Account"
        assert cache_key in enforcer._memory_cache
        assert enforcer._memory_cache[cache_key]["readable_fields"] == readable_fields

    @patch.object(index, "dynamodb")
    def test_invalidate_cache_clears_memory(self, mock_dynamodb):
        """Test invalidate_cache clears memory cache."""
        enforcer = index.FLSEnforcer(enabled=True)

        mock_table = MagicMock()
        mock_dynamodb.Table.return_value = mock_table

        # Populate memory cache
        cache_key = "005xx000001234567:Account"
        enforcer._memory_cache[cache_key] = {"readable_fields": {"Id"}}
        enforcer._memory_cache_timestamps[cache_key] = datetime.utcnow()

        result = enforcer.invalidate_cache("005xx000001234567", "Account")

        assert result is True
        assert cache_key not in enforcer._memory_cache

    def test_redact_records_applies_to_all(self):
        """Test redact_records applies redaction to all records."""
        enforcer = index.FLSEnforcer(enabled=True)

        # Mock get_readable_fields
        with patch.object(enforcer, "get_readable_fields") as mock_get:
            mock_get.return_value = {"Id", "Name"}

            records = [
                {"Id": "001", "Name": "A", "Secret": "x"},
                {"Id": "002", "Name": "B", "Secret": "y"},
            ]

            result = enforcer.redact_records(records, "005xx000001234567", "Account")

            assert len(result) == 2
            assert "Secret" not in result[0]
            assert "Secret" not in result[1]
            assert result[0]["Id"] == "001"
            assert result[1]["Name"] == "B"

    def test_redact_records_disabled_returns_unchanged(self):
        """Test redact_records returns unchanged when disabled."""
        enforcer = index.FLSEnforcer(enabled=False)

        records = [
            {"Id": "001", "Secret": "x"},
            {"Id": "002", "Secret": "y"},
        ]

        result = enforcer.redact_records(records, "005xx000001234567", "Account")

        assert result == records


class TestFLSEnforcerToggle:
    """Tests for FLS_ENFORCEMENT toggle behavior."""

    def test_fls_enforcement_env_var_default(self):
        """Test FLS_ENFORCEMENT defaults to 'disabled'."""
        # The default is set in the module
        assert index.FLS_ENFORCEMENT == "disabled" or index.FLS_ENFORCEMENT == os.environ.get(
            "FLS_ENFORCEMENT", "disabled"
        )

    def test_get_fls_enforcer_respects_env_var(self):
        """Test get_fls_enforcer respects FLS_ENFORCEMENT env var."""
        # Clear singleton
        index.clear_fls_enforcer()

        with patch.dict(os.environ, {"FLS_ENFORCEMENT": "enabled"}):
            # Reload the module to pick up the new env var
            idx = _ensure_authz_index(force_reload=True)
            # Clear singleton again after reload to ensure fresh state
            idx.clear_fls_enforcer()

            enforcer = idx.get_fls_enforcer()
            assert enforcer.enabled is True

        # Reset
        index.clear_fls_enforcer()

    def test_get_fls_enforcer_singleton(self):
        """Test get_fls_enforcer returns singleton."""
        index.clear_fls_enforcer()

        enforcer1 = index.get_fls_enforcer(enabled=True)
        enforcer2 = index.get_fls_enforcer()

        assert enforcer1 is enforcer2

        index.clear_fls_enforcer()

    def test_get_fls_enforcer_force_refresh(self):
        """Test get_fls_enforcer with force_refresh creates new instance."""
        index.clear_fls_enforcer()

        enforcer1 = index.get_fls_enforcer(enabled=True)
        enforcer2 = index.get_fls_enforcer(enabled=False, force_refresh=True)

        assert enforcer1 is not enforcer2
        assert enforcer2.enabled is False

        index.clear_fls_enforcer()

    def test_clear_fls_enforcer(self):
        """Test clear_fls_enforcer clears singleton."""
        index.get_fls_enforcer(enabled=True)
        assert index._fls_enforcer is not None

        index.clear_fls_enforcer()
        assert index._fls_enforcer is None


class TestFLSFieldPermissionsQuery:
    """Tests for FieldPermissions query functionality."""

    def test_get_user_profile_id(self):
        """Test _get_user_profile_id queries correctly."""
        mock_client = Mock()
        mock_client.query.return_value = {"records": [{"ProfileId": "00exx000000PROF"}]}

        enforcer = index.FLSEnforcer(sf_client=mock_client, enabled=True)
        result = enforcer._get_user_profile_id("005xx000001234567")

        assert result == "00exx000000PROF"
        mock_client.query.assert_called_once()

    def test_get_user_profile_id_not_found(self):
        """Test _get_user_profile_id returns None when user not found."""
        mock_client = Mock()
        mock_client.query.return_value = {"records": []}

        enforcer = index.FLSEnforcer(sf_client=mock_client, enabled=True)
        result = enforcer._get_user_profile_id("005xx000001234567")

        assert result is None

    def test_get_user_permission_set_ids(self):
        """Test _get_user_permission_set_ids queries correctly."""
        mock_client = Mock()
        mock_client.query.return_value = {
            "records": [
                {"PermissionSetId": "0PSxx000000001"},
                {"PermissionSetId": "0PSxx000000002"},
            ]
        }

        enforcer = index.FLSEnforcer(sf_client=mock_client, enabled=True)
        result = enforcer._get_user_permission_set_ids("005xx000001234567")

        assert len(result) == 2
        assert "0PSxx000000001" in result
        assert "0PSxx000000002" in result

    def test_query_field_permissions(self):
        """Test _query_field_permissions queries and parses correctly."""
        mock_client = Mock()
        mock_client.query.return_value = {
            "records": [
                {"Field": "Account.Name", "PermissionsRead": True},
                {"Field": "Account.Phone", "PermissionsRead": True},
            ]
        }

        enforcer = index.FLSEnforcer(sf_client=mock_client, enabled=True)
        result = enforcer._query_field_permissions(["00exx000000PROF"], "Account")

        assert "Name" in result
        assert "Phone" in result

    def test_query_field_permissions_empty_parent_ids(self):
        """Test _query_field_permissions returns empty for no parent IDs."""
        enforcer = index.FLSEnforcer(enabled=True)
        result = enforcer._query_field_permissions([], "Account")

        assert result == set()

    def test_get_readable_fields_includes_standard_fields(self):
        """Test get_readable_fields includes standard fields."""
        mock_client = Mock()
        # Mock profile query
        mock_client.query.side_effect = [
            {"records": [{"ProfileId": "00exx000000PROF"}]},  # Profile
            {"records": []},  # Permission sets
            {"records": [{"Field": "Account.CustomField__c", "PermissionsRead": True}]},  # FieldPermissions
        ]

        enforcer = index.FLSEnforcer(sf_client=mock_client, enabled=True)

        # Mock cache to return None (force fresh query)
        with patch.object(enforcer, "_get_cached_fls", return_value=None), patch.object(enforcer, "_cache_fls"):
            result = enforcer.get_readable_fields("005xx000001234567", "Account")

        # Should include standard fields
        assert "Id" in result
        assert "Name" in result
        assert "CreatedDate" in result
        assert "OwnerId" in result
        # And the custom field
        assert "CustomField__c" in result
