"""
Schema Discovery Lambda for Zero-Config Schema Discovery POC.

This module automatically discovers Salesforce object schemas using the Describe API
and caches them in DynamoDB for fast query-time lookup.

**Feature: zero-config-schema-discovery**
**Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7**
"""

from .models import FieldSchema, ObjectSchema

__all__ = ['FieldSchema', 'ObjectSchema']
