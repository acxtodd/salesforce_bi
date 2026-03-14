"""
Pytest configuration for test_automation directory.

Registers custom markers for integration tests.
"""

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires live infrastructure)"
    )
