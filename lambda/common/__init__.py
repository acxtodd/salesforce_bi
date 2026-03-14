"""
Common utilities for Lambda functions.

This module provides shared functionality across all Lambda functions
in the Salesforce AI Search platform.
"""
from .structured_logger import StructuredLogger, create_logger
from .feature_flags import (
    FeatureFlagName,
    FeatureFlagProvider,
    get_feature_flags,
    is_feature_enabled,
    get_all_feature_flags,
    FEATURE_FLAG_CONFIGS,
)
from .salesforce_client import (
    SalesforceClient,
    SalesforceCredentials,
    SalesforceAPIError,
    SalesforceAuthenticationError,
    SalesforceRateLimitError,
    get_salesforce_client,
    clear_salesforce_client,
)

__all__ = [
    # Logging
    "StructuredLogger",
    "create_logger",
    # Feature Flags
    "FeatureFlagName",
    "FeatureFlagProvider",
    "get_feature_flags",
    "is_feature_enabled",
    "get_all_feature_flags",
    "FEATURE_FLAG_CONFIGS",
    # Salesforce Client
    "SalesforceClient",
    "SalesforceCredentials",
    "SalesforceAPIError",
    "SalesforceAuthenticationError",
    "SalesforceRateLimitError",
    "get_salesforce_client",
    "clear_salesforce_client",
]
