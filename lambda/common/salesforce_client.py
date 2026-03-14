"""
Salesforce REST API Client.

Provides a lightweight, reusable client for Salesforce REST API operations
with retry logic, exponential backoff, and SSM credential loading.

Requirements: 1.1, 5.2, 6.1
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Default configuration
DEFAULT_API_VERSION = "v59.0"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_BACKOFF_SECONDS = 1.0
DEFAULT_MAX_BACKOFF_SECONDS = 30.0
DEFAULT_BACKOFF_MULTIPLIER = 2.0

# Retryable HTTP status codes
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class SalesforceCredentials:
    """Salesforce API credentials."""

    instance_url: str
    access_token: str
    api_version: str = DEFAULT_API_VERSION


class SalesforceAPIError(Exception):
    """Exception raised for Salesforce API errors."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
        response_body: Optional[str] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.response_body = response_body


class SalesforceAuthenticationError(SalesforceAPIError):
    """Exception raised for authentication failures."""

    pass


class SalesforceRateLimitError(SalesforceAPIError):
    """Exception raised when rate limited by Salesforce."""

    pass


class SalesforceClient:
    """
    Lightweight Salesforce REST API client.

    Provides methods for SOQL queries and object metadata retrieval
    with retry logic and exponential backoff.

    Usage:
        # From SSM credentials
        client = SalesforceClient.from_ssm()

        # Direct initialization
        client = SalesforceClient(
            instance_url="https://myorg.salesforce.com",
            access_token="00D..."
        )

        # Execute SOQL query
        results = client.query("SELECT Id, Name FROM Account LIMIT 10")

        # Get object metadata
        metadata = client.describe("Account")
    """

    def __init__(
        self,
        instance_url: str,
        access_token: str,
        api_version: str = DEFAULT_API_VERSION,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_backoff_seconds: float = DEFAULT_INITIAL_BACKOFF_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
    ):
        """
        Initialize Salesforce client.

        Args:
            instance_url: Salesforce instance URL (e.g., https://myorg.salesforce.com)
            access_token: OAuth access token
            api_version: Salesforce API version (default: v59.0)
            timeout_seconds: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            initial_backoff_seconds: Initial backoff delay for retries
            max_backoff_seconds: Maximum backoff delay
            backoff_multiplier: Multiplier for exponential backoff
        """
        # Normalize instance URL (remove trailing slash)
        self.instance_url = instance_url.rstrip("/")
        self.access_token = access_token
        self.api_version = api_version
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.initial_backoff_seconds = initial_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.backoff_multiplier = backoff_multiplier

        # Build base URL for API calls
        self._base_url = f"{self.instance_url}/services/data/{self.api_version}"

    @classmethod
    def from_ssm(
        cls,
        instance_url_param: Optional[str] = None,
        access_token_param: Optional[str] = None,
        api_version: str = DEFAULT_API_VERSION,
        **kwargs,
    ) -> "SalesforceClient":
        """
        Create client using credentials from AWS SSM Parameter Store.

        Args:
            instance_url_param: SSM parameter name for instance URL
                (default: /salesforce/instance_url or SALESFORCE_INSTANCE_URL_PARAM env var)
            access_token_param: SSM parameter name for access token
                (default: /salesforce/access_token or SALESFORCE_TOKEN_PARAM env var)
            api_version: Salesforce API version
            **kwargs: Additional arguments passed to __init__

        Returns:
            Configured SalesforceClient instance

        Raises:
            SalesforceAuthenticationError: If credentials cannot be loaded
        """
        import boto3

        ssm = boto3.client("ssm")

        # Determine parameter names from args, env vars, or defaults
        instance_url_param = instance_url_param or os.environ.get(
            "SALESFORCE_INSTANCE_URL_PARAM", "/salesforce/instance_url"
        )
        access_token_param = access_token_param or os.environ.get(
            "SALESFORCE_TOKEN_PARAM", "/salesforce/access_token"
        )

        try:
            # Fetch instance URL
            instance_url = cls._get_ssm_parameter(ssm, instance_url_param)

            # Fetch access token (with decryption for SecureString)
            access_token = cls._get_ssm_parameter(ssm, access_token_param, decrypt=True)

            LOGGER.info(
                f"Loaded Salesforce credentials from SSM: "
                f"instance_url_param={instance_url_param}"
            )

            return cls(
                instance_url=instance_url,
                access_token=access_token,
                api_version=api_version,
                **kwargs,
            )

        except Exception as e:
            LOGGER.error(f"Failed to load Salesforce credentials from SSM: {e}")
            raise SalesforceAuthenticationError(f"Failed to load credentials from SSM: {e}") from e

    @staticmethod
    def _get_ssm_parameter(ssm_client, param_name: str, decrypt: bool = False) -> str:
        """
        Get parameter value from SSM Parameter Store.

        Args:
            ssm_client: Boto3 SSM client
            param_name: Parameter name
            decrypt: Whether to decrypt SecureString parameters

        Returns:
            Parameter value

        Raises:
            SalesforceAuthenticationError: If parameter not found
        """
        try:
            response = ssm_client.get_parameter(
                Name=param_name,
                WithDecryption=decrypt,
            )
            return response["Parameter"]["Value"]
        except ssm_client.exceptions.ParameterNotFound:
            raise SalesforceAuthenticationError(f"SSM parameter not found: {param_name}")

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers for API requests."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _make_request(
        self,
        method: str,
        url: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make HTTP request with retry logic and exponential backoff.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL for the request
            data: Optional request body data

        Returns:
            Parsed JSON response

        Raises:
            SalesforceAPIError: On API errors
            SalesforceAuthenticationError: On authentication failures
            SalesforceRateLimitError: When rate limited
        """
        headers = self._build_headers()
        body = json.dumps(data).encode("utf-8") if data else None

        last_exception: Optional[Exception] = None
        backoff = self.initial_backoff_seconds

        for attempt in range(self.max_retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers=headers,
                    method=method,
                )

                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                    response_body = response.read().decode("utf-8")

                    if response_body:
                        return json.loads(response_body)
                    return {}

            except HTTPError as e:
                status_code = e.code
                response_body = e.read().decode("utf-8") if e.fp else ""

                # Parse error details from response
                error_code = None
                try:
                    error_data = json.loads(response_body)
                    if isinstance(error_data, list) and error_data:
                        error_code = error_data[0].get("errorCode")
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

                # Handle authentication errors (no retry)
                if status_code == 401:
                    raise SalesforceAuthenticationError(
                        f"Authentication failed: {response_body}",
                        status_code=status_code,
                        error_code=error_code,
                        response_body=response_body,
                    )

                # Handle rate limiting
                if status_code == 429:
                    if attempt < self.max_retries:
                        LOGGER.warning(
                            f"Rate limited (attempt {attempt + 1}/{self.max_retries + 1}), "
                            f"backing off {backoff}s"
                        )
                        time.sleep(backoff)
                        backoff = min(backoff * self.backoff_multiplier, self.max_backoff_seconds)
                        last_exception = SalesforceRateLimitError(
                            f"Rate limited: {response_body}",
                            status_code=status_code,
                            response_body=response_body,
                        )
                        continue
                    raise SalesforceRateLimitError(
                        f"Rate limited after {self.max_retries + 1} attempts",
                        status_code=status_code,
                        response_body=response_body,
                    )

                # Handle retryable errors
                if status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    LOGGER.warning(
                        f"Retryable error {status_code} "
                        f"(attempt {attempt + 1}/{self.max_retries + 1}), "
                        f"backing off {backoff}s"
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * self.backoff_multiplier, self.max_backoff_seconds)
                    last_exception = SalesforceAPIError(
                        f"HTTP {status_code}: {response_body}",
                        status_code=status_code,
                        error_code=error_code,
                        response_body=response_body,
                    )
                    continue

                # Non-retryable error
                raise SalesforceAPIError(
                    f"HTTP {status_code}: {response_body}",
                    status_code=status_code,
                    error_code=error_code,
                    response_body=response_body,
                )

            except URLError as e:
                # Network errors are retryable
                if attempt < self.max_retries:
                    LOGGER.warning(
                        f"Network error (attempt {attempt + 1}/{self.max_retries + 1}): {e}, "
                        f"backing off {backoff}s"
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * self.backoff_multiplier, self.max_backoff_seconds)
                    last_exception = e
                    continue
                raise SalesforceAPIError(f"Network error: {e}") from e

        # Should not reach here, but handle edge case
        if last_exception:
            raise last_exception
        raise SalesforceAPIError("Request failed after all retries")

    def query(self, soql: str) -> Dict[str, Any]:
        """
        Execute SOQL query against Salesforce REST API.

        Args:
            soql: SOQL query string

        Returns:
            Query results dictionary with 'records' list and metadata

        Raises:
            SalesforceAPIError: On query errors

        Example:
            results = client.query("SELECT Id, Name FROM Account LIMIT 10")
            for record in results.get('records', []):
                print(record['Name'])
        """
        encoded_query = urllib.parse.quote(soql)
        url = f"{self._base_url}/query?q={encoded_query}"

        LOGGER.debug(f"Executing SOQL query: {soql[:100]}...")

        result = self._make_request("GET", url)

        record_count = len(result.get("records", []))
        LOGGER.debug(f"Query returned {record_count} records")

        return result

    def query_all(self, soql: str) -> List[Dict[str, Any]]:
        """
        Execute SOQL query and fetch all records (handles pagination).

        Args:
            soql: SOQL query string

        Returns:
            List of all records

        Raises:
            SalesforceAPIError: On query errors
        """
        all_records: List[Dict[str, Any]] = []

        # Initial query
        result = self.query(soql)
        all_records.extend(result.get("records", []))

        # Handle pagination
        while not result.get("done", True):
            next_url = result.get("nextRecordsUrl")
            if not next_url:
                break

            url = f"{self.instance_url}{next_url}"
            result = self._make_request("GET", url)
            all_records.extend(result.get("records", []))

        LOGGER.debug(f"Query returned {len(all_records)} total records")
        return all_records

    def describe(self, sobject: str) -> Dict[str, Any]:
        """
        Get object describe metadata from Salesforce.

        Args:
            sobject: Salesforce object API name (e.g., "Account", "Contact")

        Returns:
            Object describe metadata dictionary

        Raises:
            SalesforceAPIError: On describe errors

        Example:
            metadata = client.describe("Account")
            for field in metadata.get('fields', []):
                print(f"{field['name']}: {field['type']}")
        """
        url = f"{self._base_url}/sobjects/{sobject}/describe"

        LOGGER.debug(f"Describing object: {sobject}")

        return self._make_request("GET", url)

    def describe_global(self) -> Dict[str, Any]:
        """
        Get global describe metadata (list of all objects).

        Returns:
            Global describe metadata with 'sobjects' list

        Raises:
            SalesforceAPIError: On describe errors
        """
        url = f"{self._base_url}/sobjects"

        LOGGER.debug("Fetching global describe")

        return self._make_request("GET", url)


# Module-level singleton for reuse across Lambda invocations
_salesforce_client: Optional[SalesforceClient] = None


def get_salesforce_client(
    force_refresh: bool = False,
    **kwargs,
) -> SalesforceClient:
    """
    Get or create a Salesforce client singleton.

    Uses SSM credentials by default. Reuses client across Lambda invocations
    for connection efficiency.

    Args:
        force_refresh: Force creation of new client
        **kwargs: Arguments passed to SalesforceClient.from_ssm()

    Returns:
        SalesforceClient instance
    """
    global _salesforce_client

    if _salesforce_client is None or force_refresh:
        _salesforce_client = SalesforceClient.from_ssm(**kwargs)

    return _salesforce_client


def clear_salesforce_client() -> None:
    """Clear the cached Salesforce client singleton."""
    global _salesforce_client
    _salesforce_client = None


__all__ = [
    "SalesforceClient",
    "SalesforceCredentials",
    "SalesforceAPIError",
    "SalesforceAuthenticationError",
    "SalesforceRateLimitError",
    "get_salesforce_client",
    "clear_salesforce_client",
]
