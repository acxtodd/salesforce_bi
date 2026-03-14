"""
Tests for Salesforce Client Module.

Tests the SalesforceClient class for SOQL queries, object metadata retrieval,
SSM credential loading, and retry logic with exponential backoff.

Requirements: 1.1
"""
import json
import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock, Mock
from urllib.error import HTTPError, URLError
from io import BytesIO

# Add common directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from salesforce_client import (
    SalesforceClient,
    SalesforceAPIError,
    SalesforceAuthenticationError,
    SalesforceRateLimitError,
    get_salesforce_client,
    clear_salesforce_client,
)


class TestSalesforceClientInit:
    """Tests for SalesforceClient initialization."""
    
    def test_init_with_valid_credentials(self):
        """Test client initialization with valid credentials."""
        client = SalesforceClient(
            instance_url="https://myorg.salesforce.com",
            access_token="test_token_123",
        )
        
        assert client.instance_url == "https://myorg.salesforce.com"
        assert client.access_token == "test_token_123"
        assert client.api_version == "v59.0"
    
    def test_init_normalizes_instance_url(self):
        """Test that trailing slash is removed from instance URL."""
        client = SalesforceClient(
            instance_url="https://myorg.salesforce.com/",
            access_token="test_token",
        )
        
        assert client.instance_url == "https://myorg.salesforce.com"
    
    def test_init_with_custom_api_version(self):
        """Test client initialization with custom API version."""
        client = SalesforceClient(
            instance_url="https://myorg.salesforce.com",
            access_token="test_token",
            api_version="v58.0",
        )
        
        assert client.api_version == "v58.0"
    
    def test_init_with_custom_retry_settings(self):
        """Test client initialization with custom retry settings."""
        client = SalesforceClient(
            instance_url="https://myorg.salesforce.com",
            access_token="test_token",
            max_retries=5,
            initial_backoff_seconds=2.0,
            max_backoff_seconds=60.0,
        )
        
        assert client.max_retries == 5
        assert client.initial_backoff_seconds == 2.0
        assert client.max_backoff_seconds == 60.0


class TestSalesforceClientFromSSM:
    """Tests for SalesforceClient.from_ssm() class method."""
    
    def test_from_ssm_success(self):
        """Test successful credential loading from SSM."""
        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            import importlib
            import salesforce_client
            importlib.reload(salesforce_client)
            
            mock_ssm = MagicMock()
            sys.modules["boto3"].client.return_value = mock_ssm
            
            # Mock SSM responses
            mock_ssm.get_parameter.side_effect = [
                {"Parameter": {"Value": "https://myorg.salesforce.com"}},
                {"Parameter": {"Value": "test_access_token"}},
            ]
            
            client = salesforce_client.SalesforceClient.from_ssm()
            
            assert client.instance_url == "https://myorg.salesforce.com"
            assert client.access_token == "test_access_token"
            
            # Verify SSM calls
            assert mock_ssm.get_parameter.call_count == 2
    
    def test_from_ssm_with_custom_param_names(self):
        """Test credential loading with custom parameter names."""
        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            import importlib
            import salesforce_client
            importlib.reload(salesforce_client)
            
            mock_ssm = MagicMock()
            sys.modules["boto3"].client.return_value = mock_ssm
            
            mock_ssm.get_parameter.side_effect = [
                {"Parameter": {"Value": "https://custom.salesforce.com"}},
                {"Parameter": {"Value": "custom_token"}},
            ]
            
            client = salesforce_client.SalesforceClient.from_ssm(
                instance_url_param="/custom/instance_url",
                access_token_param="/custom/token",
            )
            
            assert client.instance_url == "https://custom.salesforce.com"
            assert client.access_token == "custom_token"
    
    def test_from_ssm_parameter_not_found(self):
        """Test error handling when SSM parameter not found."""
        with patch.dict("sys.modules", {"boto3": MagicMock()}):
            import importlib
            import salesforce_client
            importlib.reload(salesforce_client)
            
            mock_ssm = MagicMock()
            sys.modules["boto3"].client.return_value = mock_ssm
            
            # Create a mock exception class
            mock_ssm.exceptions.ParameterNotFound = Exception
            mock_ssm.get_parameter.side_effect = mock_ssm.exceptions.ParameterNotFound(
                "Parameter not found"
            )
            
            with pytest.raises(salesforce_client.SalesforceAuthenticationError) as exc_info:
                salesforce_client.SalesforceClient.from_ssm()
            
            assert "Failed to load credentials from SSM" in str(exc_info.value)
    
    def test_from_ssm_uses_env_vars(self):
        """Test that environment variables are used for parameter names."""
        with patch.dict(os.environ, {
            "SALESFORCE_INSTANCE_URL_PARAM": "/env/instance_url",
            "SALESFORCE_TOKEN_PARAM": "/env/token",
        }):
            with patch.dict("sys.modules", {"boto3": MagicMock()}):
                import importlib
                import salesforce_client
                importlib.reload(salesforce_client)
                
                mock_ssm = MagicMock()
                sys.modules["boto3"].client.return_value = mock_ssm
                
                mock_ssm.get_parameter.side_effect = [
                    {"Parameter": {"Value": "https://env.salesforce.com"}},
                    {"Parameter": {"Value": "env_token"}},
                ]
                
                client = salesforce_client.SalesforceClient.from_ssm()
                
                # Verify correct parameter names were used
                calls = mock_ssm.get_parameter.call_args_list
                assert calls[0][1]["Name"] == "/env/instance_url"
                assert calls[1][1]["Name"] == "/env/token"


class TestSalesforceClientQuery:
    """Tests for SalesforceClient.query() method."""
    
    def setup_method(self):
        """Set up test client."""
        # Re-import to ensure we have the correct module after SSM tests may have reloaded it
        import importlib
        import salesforce_client
        importlib.reload(salesforce_client)
        
        from salesforce_client import SalesforceClient as SC
        self.client = SC(
            instance_url="https://test.salesforce.com",
            access_token="test_token",
            max_retries=0,  # Disable retries for most tests
        )
        # Store exception classes for assertions
        self.SalesforceAuthenticationError = salesforce_client.SalesforceAuthenticationError
        self.SalesforceAPIError = salesforce_client.SalesforceAPIError
    
    @patch("urllib.request.urlopen")
    def test_query_success(self, mock_urlopen):
        """Test successful SOQL query execution."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "totalSize": 2,
            "done": True,
            "records": [
                {"Id": "001xx1", "Name": "Account 1"},
                {"Id": "001xx2", "Name": "Account 2"},
            ]
        }).encode("utf-8")
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        result = self.client.query("SELECT Id, Name FROM Account LIMIT 2")
        
        assert result["totalSize"] == 2
        assert len(result["records"]) == 2
        assert result["records"][0]["Name"] == "Account 1"
    
    @patch("urllib.request.urlopen")
    def test_query_url_encoding(self, mock_urlopen):
        """Test that SOQL query is properly URL encoded."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "totalSize": 0,
            "done": True,
            "records": []
        }).encode("utf-8")
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        self.client.query("SELECT Id FROM Account WHERE Name = 'Test & Co'")
        
        # Verify URL was called with encoded query
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        assert "Test%20%26%20Co" in request.full_url or "Test+%26+Co" in request.full_url
    
    @patch("urllib.request.urlopen")
    def test_query_authentication_error(self, mock_urlopen):
        """Test handling of authentication errors."""
        # Create HTTPError with readable fp
        http_error = HTTPError(
            url="https://test.salesforce.com",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=BytesIO(b'[{"errorCode": "INVALID_SESSION_ID", "message": "Session expired"}]'),
        )
        mock_urlopen.side_effect = http_error
        
        with pytest.raises(self.SalesforceAuthenticationError) as exc_info:
            self.client.query("SELECT Id FROM Account")
        
        assert exc_info.value.status_code == 401
    
    @patch("urllib.request.urlopen")
    def test_query_api_error(self, mock_urlopen):
        """Test handling of API errors."""
        http_error = HTTPError(
            url="https://test.salesforce.com",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(b'[{"errorCode": "MALFORMED_QUERY", "message": "Invalid SOQL"}]'),
        )
        mock_urlopen.side_effect = http_error
        
        with pytest.raises(self.SalesforceAPIError) as exc_info:
            self.client.query("INVALID SOQL")
        
        assert exc_info.value.status_code == 400


class TestSalesforceClientDescribe:
    """Tests for SalesforceClient.describe() method."""
    
    def setup_method(self):
        """Set up test client."""
        self.client = SalesforceClient(
            instance_url="https://test.salesforce.com",
            access_token="test_token",
            max_retries=0,
        )
    
    @patch("urllib.request.urlopen")
    def test_describe_success(self, mock_urlopen):
        """Test successful object describe."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "name": "Account",
            "label": "Account",
            "fields": [
                {"name": "Id", "type": "id"},
                {"name": "Name", "type": "string"},
            ]
        }).encode("utf-8")
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        result = self.client.describe("Account")
        
        assert result["name"] == "Account"
        assert len(result["fields"]) == 2
    
    @patch("urllib.request.urlopen")
    def test_describe_url_format(self, mock_urlopen):
        """Test that describe URL is correctly formatted."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"name": "Account"}'
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        self.client.describe("Account")
        
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        assert "/sobjects/Account/describe" in request.full_url


class TestSalesforceClientRetry:
    """Tests for retry logic with exponential backoff."""
    
    def setup_method(self):
        """Re-import module to ensure correct exception classes."""
        import importlib
        import salesforce_client
        importlib.reload(salesforce_client)
        self.SalesforceAPIError = salesforce_client.SalesforceAPIError
        self.SalesforceClient = salesforce_client.SalesforceClient
    
    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_retry_on_503(self, mock_urlopen, mock_sleep):
        """Test retry on 503 Service Unavailable."""
        client = self.SalesforceClient(
            instance_url="https://test.salesforce.com",
            access_token="test_token",
            max_retries=2,
            initial_backoff_seconds=1.0,
        )
        
        # First two calls fail with 503, third succeeds
        error_response = BytesIO(b"Service Unavailable")
        mock_urlopen.side_effect = [
            HTTPError("url", 503, "Service Unavailable", {}, error_response),
            HTTPError("url", 503, "Service Unavailable", {}, BytesIO(b"Service Unavailable")),
            MagicMock(
                read=Mock(return_value=b'{"records": []}'),
                __enter__=Mock(return_value=MagicMock(read=Mock(return_value=b'{"records": []}'))),
                __exit__=Mock(return_value=False),
            ),
        ]
        
        # Create proper mock for successful response
        success_response = MagicMock()
        success_response.read.return_value = b'{"records": []}'
        success_response.__enter__ = Mock(return_value=success_response)
        success_response.__exit__ = Mock(return_value=False)
        mock_urlopen.side_effect = [
            HTTPError("url", 503, "Service Unavailable", {}, BytesIO(b"err")),
            HTTPError("url", 503, "Service Unavailable", {}, BytesIO(b"err")),
            success_response,
        ]
        
        result = client.query("SELECT Id FROM Account")
        
        assert result == {"records": []}
        assert mock_urlopen.call_count == 3
        assert mock_sleep.call_count == 2
    
    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_retry_on_rate_limit(self, mock_urlopen, mock_sleep):
        """Test retry on 429 Rate Limit."""
        client = self.SalesforceClient(
            instance_url="https://test.salesforce.com",
            access_token="test_token",
            max_retries=1,
            initial_backoff_seconds=0.5,
        )
        
        success_response = MagicMock()
        success_response.read.return_value = b'{"records": []}'
        success_response.__enter__ = Mock(return_value=success_response)
        success_response.__exit__ = Mock(return_value=False)
        
        mock_urlopen.side_effect = [
            HTTPError("url", 429, "Too Many Requests", {}, BytesIO(b"Rate limited")),
            success_response,
        ]
        
        result = client.query("SELECT Id FROM Account")
        
        assert result == {"records": []}
        assert mock_urlopen.call_count == 2
    
    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_max_retries_exceeded(self, mock_urlopen, mock_sleep):
        """Test that error is raised after max retries exceeded."""
        client = self.SalesforceClient(
            instance_url="https://test.salesforce.com",
            access_token="test_token",
            max_retries=2,
        )
        
        # Create fresh HTTPError for each call
        def create_503_error():
            return HTTPError("url", 503, "Service Unavailable", {}, BytesIO(b"err"))
        
        mock_urlopen.side_effect = [create_503_error() for _ in range(3)]
        
        with pytest.raises(self.SalesforceAPIError):
            client.query("SELECT Id FROM Account")
        
        # Initial attempt + 2 retries = 3 total
        assert mock_urlopen.call_count == 3
    
    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_no_retry_on_400(self, mock_urlopen, mock_sleep):
        """Test that 400 errors are not retried."""
        client = self.SalesforceClient(
            instance_url="https://test.salesforce.com",
            access_token="test_token",
            max_retries=3,
        )
        
        http_error = HTTPError("url", 400, "Bad Request", {}, BytesIO(b"Invalid query"))
        mock_urlopen.side_effect = http_error
        
        with pytest.raises(self.SalesforceAPIError):
            client.query("INVALID")
        
        # Should not retry on 400
        assert mock_urlopen.call_count == 1
        assert mock_sleep.call_count == 0
    
    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_retry_on_network_error(self, mock_urlopen, mock_sleep):
        """Test retry on network errors."""
        client = self.SalesforceClient(
            instance_url="https://test.salesforce.com",
            access_token="test_token",
            max_retries=1,
        )
        
        success_response = MagicMock()
        success_response.read.return_value = b'{"records": []}'
        success_response.__enter__ = Mock(return_value=success_response)
        success_response.__exit__ = Mock(return_value=False)
        
        mock_urlopen.side_effect = [
            URLError("Connection refused"),
            success_response,
        ]
        
        result = client.query("SELECT Id FROM Account")
        
        assert result == {"records": []}
        assert mock_urlopen.call_count == 2


class TestSalesforceClientQueryAll:
    """Tests for SalesforceClient.query_all() method."""
    
    def setup_method(self):
        """Set up test client."""
        self.client = SalesforceClient(
            instance_url="https://test.salesforce.com",
            access_token="test_token",
            max_retries=0,
        )
    
    @patch("urllib.request.urlopen")
    def test_query_all_single_page(self, mock_urlopen):
        """Test query_all with single page of results."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "totalSize": 2,
            "done": True,
            "records": [{"Id": "001"}, {"Id": "002"}]
        }).encode("utf-8")
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response
        
        records = self.client.query_all("SELECT Id FROM Account")
        
        assert len(records) == 2
        assert mock_urlopen.call_count == 1
    
    @patch("urllib.request.urlopen")
    def test_query_all_pagination(self, mock_urlopen):
        """Test query_all handles pagination correctly."""
        # First page
        page1_response = MagicMock()
        page1_response.read.return_value = json.dumps({
            "totalSize": 4,
            "done": False,
            "nextRecordsUrl": "/services/data/v59.0/query/01gxx-2000",
            "records": [{"Id": "001"}, {"Id": "002"}]
        }).encode("utf-8")
        page1_response.__enter__ = Mock(return_value=page1_response)
        page1_response.__exit__ = Mock(return_value=False)
        
        # Second page
        page2_response = MagicMock()
        page2_response.read.return_value = json.dumps({
            "totalSize": 4,
            "done": True,
            "records": [{"Id": "003"}, {"Id": "004"}]
        }).encode("utf-8")
        page2_response.__enter__ = Mock(return_value=page2_response)
        page2_response.__exit__ = Mock(return_value=False)
        
        mock_urlopen.side_effect = [page1_response, page2_response]
        
        records = self.client.query_all("SELECT Id FROM Account")
        
        assert len(records) == 4
        assert mock_urlopen.call_count == 2


class TestSalesforceClientSingleton:
    """Tests for module-level singleton functions."""
    
    def setup_method(self):
        """Clear singleton before each test."""
        clear_salesforce_client()
    
    def teardown_method(self):
        """Clear singleton after each test."""
        clear_salesforce_client()
    
    @patch("salesforce_client.SalesforceClient.from_ssm")
    def test_get_salesforce_client_creates_singleton(self, mock_from_ssm):
        """Test that get_salesforce_client creates a singleton."""
        mock_client = MagicMock()
        mock_from_ssm.return_value = mock_client
        
        client1 = get_salesforce_client()
        client2 = get_salesforce_client()
        
        assert client1 is client2
        assert mock_from_ssm.call_count == 1
    
    @patch("salesforce_client.SalesforceClient.from_ssm")
    def test_get_salesforce_client_force_refresh(self, mock_from_ssm):
        """Test that force_refresh creates new client."""
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        mock_from_ssm.side_effect = [mock_client1, mock_client2]
        
        client1 = get_salesforce_client()
        client2 = get_salesforce_client(force_refresh=True)
        
        assert client1 is not client2
        assert mock_from_ssm.call_count == 2
    
    @patch("salesforce_client.SalesforceClient.from_ssm")
    def test_clear_salesforce_client(self, mock_from_ssm):
        """Test that clear_salesforce_client clears the singleton."""
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        mock_from_ssm.side_effect = [mock_client1, mock_client2]
        
        client1 = get_salesforce_client()
        clear_salesforce_client()
        client2 = get_salesforce_client()
        
        assert client1 is not client2
        assert mock_from_ssm.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
