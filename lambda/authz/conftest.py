"""
Pytest configuration for authz tests.

This conftest ensures the correct authz/index.py module is loaded
before any authz tests run, avoiding conflicts with other index.py
modules (e.g., chunking/index.py).
"""
import sys
import os
import pytest


def _ensure_authz_index():
    """Ensure we have the correct authz/index.py module loaded."""
    authz_dir = os.path.dirname(__file__)
    # Remove any existing authz_dir entries to avoid duplicates
    sys.path = [p for p in sys.path if p != authz_dir]
    sys.path.insert(0, authz_dir)
    
    # Remove any cached 'index' module to ensure we import the correct one
    if 'index' in sys.modules:
        del sys.modules['index']
    
    import index
    return index


# Ensure the correct module is loaded when this conftest is first imported
_ensure_authz_index()
