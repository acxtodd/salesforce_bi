"""Retrieve Lambda handler for /retrieve endpoint.
Parses incoming requests, fetches AuthZ context, and builds hybrid query plans.

**Phase 3 Enhancement**: Integrates Query Intent Router for intelligent query classification
and routing to appropriate retrievers (vector, graph-aware, aggregation).
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import logging
import os
import random
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from collections import OrderedDict

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import BotoCoreError, ClientError

# Phase 3: Import Intent Router for query classification
try:
    from intent_router import QueryIntentRouter, QueryIntent, classify_query, route_query
    INTENT_ROUTER_AVAILABLE = True
except ImportError:
    INTENT_ROUTER_AVAILABLE = False

# Phase 3: Import Graph-Aware Retriever for relationship queries
try:
    from graph_retriever import GraphAwareRetriever
    GRAPH_RETRIEVER_AVAILABLE = True
except ImportError:
    GRAPH_RETRIEVER_AVAILABLE = False
    GraphAwareRetriever = None

# Query Decomposer for LLM-based query understanding
try:
    from query_decomposer import get_decomposer, decompose_query
    QUERY_DECOMPOSER_AVAILABLE = True
except ImportError:
    QUERY_DECOMPOSER_AVAILABLE = False
    decompose_query = None

# Schema-Aware Decomposer for zero-config schema discovery
try:
    from schema_decomposer import SchemaAwareDecomposer, StructuredQuery
    SCHEMA_DECOMPOSER_AVAILABLE = True
    print(f"[INIT] Schema decomposer loaded successfully")
except ImportError as e:
    SCHEMA_DECOMPOSER_AVAILABLE = False
    SchemaAwareDecomposer = None
    StructuredQuery = None
    print(f"[INIT] Schema decomposer import failed: {e}")

# Graph Attribute Filter for schema-driven filtering
try:
    from graph_filter import GraphAttributeFilter, apply_graph_filter
    GRAPH_FILTER_AVAILABLE = True
except ImportError:
    GRAPH_FILTER_AVAILABLE = False
    GraphAttributeFilter = None
    apply_graph_filter = None

# Cross-Object Query Handler for zero-config production
# **Requirements: 9.1, 9.2, 9.5**
try:
    from cross_object_handler import (
        CrossObjectQueryHandler,
        CrossObjectQuery,
        get_cross_object_handler,
        detect_cross_object_query,
        execute_cross_object_query,
    )
    CROSS_OBJECT_HANDLER_AVAILABLE = True
    print(f"[INIT] Cross-object handler loaded successfully")
except ImportError as e:
    CROSS_OBJECT_HANDLER_AVAILABLE = False
    CrossObjectQueryHandler = None
    CrossObjectQuery = None
    get_cross_object_handler = None
    detect_cross_object_query = None
    execute_cross_object_query = None
    print(f"[INIT] Cross-object handler import failed: {e}")

# Field-Level Security (FLS) Enforcer for result redaction
# Requirements: 6.1, 6.2
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'authz'))
try:
    from index import FLSEnforcer, get_fls_enforcer, FLS_ENFORCEMENT
    FLS_ENFORCER_AVAILABLE = True
    print(f"[INIT] FLS enforcer loaded successfully, enforcement={FLS_ENFORCEMENT}")
except ImportError as e:
    FLS_ENFORCER_AVAILABLE = False
    FLSEnforcer = None
    get_fls_enforcer = None
    FLS_ENFORCEMENT = 'disabled'

# Disambiguation Handler for ambiguous queries
# **Requirements: 11.1, 11.2, 11.3, 11.4**
try:
    from disambiguation import (
        DisambiguationHandler,
        DisambiguationRequest,
        DisambiguationOption,
        get_disambiguation_handler,
        should_disambiguate,
        build_disambiguation_request,
        CONFIDENCE_THRESHOLD,
    )
    DISAMBIGUATION_AVAILABLE = True
    print(f"[INIT] Disambiguation handler loaded successfully, threshold={CONFIDENCE_THRESHOLD}")
except ImportError as e:
    DISAMBIGUATION_AVAILABLE = False
    DisambiguationHandler = None
    DisambiguationRequest = None
    DisambiguationOption = None
    get_disambiguation_handler = None
    should_disambiguate = None
    build_disambiguation_request = None
    CONFIDENCE_THRESHOLD = 0.7
    print(f"[INIT] Disambiguation handler import failed: {e}")

# Graph-Aware Zero-Config Planner
# **Feature: graph-aware-zero-config-retrieval**
# **Requirements: 1.1, 1.2, 1.3, 1.4, 8.1**
try:
    from planner import (
        Planner,
        StructuredPlan,
        Predicate,
        DEFAULT_TIMEOUT_MS as PLANNER_DEFAULT_TIMEOUT_MS,
        DEFAULT_CONFIDENCE_THRESHOLD as PLANNER_CONFIDENCE_THRESHOLD,
    )
    PLANNER_AVAILABLE = True
    # Note: Actual timeout configured via PLANNER_TIMEOUT_MS env var (logged after env vars read)
except ImportError as e:
    PLANNER_AVAILABLE = False
    Planner = None
    StructuredPlan = None
    Predicate = None
    PLANNER_DEFAULT_TIMEOUT_MS = 500
    PLANNER_CONFIDENCE_THRESHOLD = 0.5
    print(f"[INIT] Planner import failed: {e}")

# VocabCache for entity linking in Planner
# **Feature: graph-aware-zero-config-retrieval**
# **Requirements: 2.1, 2.2, 2.3**
try:
    from vocab_cache import VocabCache
    VOCAB_CACHE_AVAILABLE = True
    # Lazy-initialized singleton for VocabCache
    _vocab_cache_instance = None
    def get_vocab_cache() -> VocabCache:
        global _vocab_cache_instance
        if _vocab_cache_instance is None:
            _vocab_cache_instance = VocabCache()
        return _vocab_cache_instance
    # VocabCache available - logged in consolidated init below
except ImportError as e:
    VOCAB_CACHE_AVAILABLE = False
    VocabCache = None
    get_vocab_cache = None
    # VocabCache import failed - logged in consolidated init below

# SchemaCache for field relevance scoring in Planner (Task 42)
# **Feature: graph-aware-zero-config-retrieval**
# **Requirements: Task 41, Task 42**
try:
    # schema_discovery is bundled in lambda/retrieve/schema_discovery/
    from schema_discovery.cache import SchemaCache
    SCHEMA_CACHE_AVAILABLE = True
    # Module-level singleton for SchemaCache (persists across warm Lambda invocations)
    # Task 29.6: Use module-level cache to avoid repeated DynamoDB calls
    _schema_cache_instance = None
    def get_schema_cache() -> SchemaCache:
        global _schema_cache_instance
        if _schema_cache_instance is None:
            _schema_cache_instance = SchemaCache()
        return _schema_cache_instance
    print(f"[INIT] SchemaCache loaded successfully (Task 42 relevance)")
except ImportError as e:
    SCHEMA_CACHE_AVAILABLE = False
    SchemaCache = None
    get_schema_cache = None
    print(f"[INIT] SchemaCache import failed: {e}")

# Query Executor for graph-aware retrieval
# **Feature: graph-aware-zero-config-retrieval**
# **Requirements: 7.1, 7.2, 5.6, 5.7, 11.4, 1.2, 8.1**
try:
    from query_executor import (
        QueryExecutor,
        ExecutionResult,
        ExecutionPath,
        AuthorizationContext,
    )
    QUERY_EXECUTOR_AVAILABLE = True
    print(f"[INIT] Query Executor loaded successfully")
except ImportError as e:
    QUERY_EXECUTOR_AVAILABLE = False
    QueryExecutor = None
    ExecutionResult = None
    ExecutionPath = None
    AuthorizationContext = None
    print(f"[INIT] Query Executor import failed: {e}")

# DerivedViewManager for aggregation query routing
# **Task: 16.5 - Aggregation Query Routing**
# **Requirements: 5.6, 5.7**
try:
    from derived_view_manager import DerivedViewManager
    DERIVED_VIEW_MANAGER_AVAILABLE = True
    print(f"[INIT] DerivedViewManager loaded successfully")
except ImportError as e:
    DERIVED_VIEW_MANAGER_AVAILABLE = False
    DerivedViewManager = None
    print(f"[INIT] DerivedViewManager import failed: {e}")

# CloudWatch metrics for Planner and Quality
# **Feature: graph-aware-zero-config-retrieval**
# **Requirements: 12.1, 12.2**
try:
    from graph_metrics import (
        get_planner_metrics,
        get_quality_metrics,
        PlannerMetrics,
        QualityMetrics,
    )
    PLANNER_METRICS_AVAILABLE = True
    print(f"[INIT] Planner metrics loaded successfully")
except ImportError as e:
    PLANNER_METRICS_AVAILABLE = False
    get_planner_metrics = None
    get_quality_metrics = None
    PlannerMetrics = None
    QualityMetrics = None
    print(f"[INIT] Planner metrics import failed: {e}")

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

lambda_client = boto3.client("lambda")
bedrock_agent_runtime_client = boto3.client("bedrock-agent-runtime")
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
cloudwatch = boto3.client("cloudwatch")

DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "8"))
MAX_TOP_K = int(os.getenv("MAX_TOP_K", "20"))
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "60"))  # Default 60 seconds
CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", "100"))  # Max 100 cached queries
MIN_RELEVANCE_SCORE = float(os.getenv("MIN_RELEVANCE_SCORE", "0.415"))  # Filter out low-relevance results

# Phase 3: Intent Router feature flags
INTENT_ROUTING_ENABLED = os.getenv("INTENT_ROUTING_ENABLED", "true").lower() == "true"
GRAPH_ROUTING_ENABLED = os.getenv("GRAPH_ROUTING_ENABLED", "true").lower() == "true"  # Enabled for Phase 3 graph enhancement
INTENT_LOGGING_ENABLED = os.getenv("INTENT_LOGGING_ENABLED", "true").lower() == "true"
# LLM Query Decomposer - set to "true" to enable
# **Performance Optimization (Task 26)**: Disabled by default
# Query Decomposer uses an LLM call which adds 200-500ms latency
# Schema Decomposer provides similar functionality without LLM overhead
QUERY_DECOMPOSER_ENABLED = os.getenv("QUERY_DECOMPOSER_ENABLED", "false").lower() == "true"
# Schema-Driven Graph Filtering - set to "true" to enable
SCHEMA_FILTER_ENABLED = os.getenv("SCHEMA_FILTER_ENABLED", "true").lower() == "true"
# Disambiguation - set to "true" to enable asking for clarification on ambiguous queries
# **Requirements: 11.1, 11.2, 11.3, 11.4**
DISAMBIGUATION_ENABLED = os.getenv("DISAMBIGUATION_ENABLED", "true").lower() == "true"
# Graph-Aware Zero-Config Planner - set to "true" to enable structured query planning
# **Feature: graph-aware-zero-config-retrieval**
# **Requirements: 1.1, 1.2, 1.3, 1.4, 8.1**
PLANNER_ENABLED = os.getenv("PLANNER_ENABLED", "true").lower() == "true"
# Planner timeout in milliseconds (default 500ms per Requirement 1.2)
PLANNER_TIMEOUT_MS = int(os.getenv("PLANNER_TIMEOUT_MS", "500"))
# Task 29.6: Cross-object query timeout in milliseconds (graph traversal can be slow)
# Timeout triggers graceful fallback to semantic search
CROSS_OBJECT_TIMEOUT_MS = int(os.getenv("CROSS_OBJECT_TIMEOUT_MS", "2000"))
# Planner confidence threshold for fallback (default 0.5 per Requirement 1.3)
PLANNER_MIN_CONFIDENCE = float(os.getenv("PLANNER_MIN_CONFIDENCE", "0.5"))
# Planner Shadow Mode - run planner and log results but don't use for retrieval
# **Task: 28.1 - Shadow Logging for Canary Deployment**
PLANNER_SHADOW_MODE = os.getenv("PLANNER_SHADOW_MODE", "false").lower() == "true"
# Planner Traffic Percentage - percentage of requests to use planner results (0-100)
# **Task: 28.2 - Phase 1 Canary Deployment**
# When > 0, this percentage of requests will use planner for actual retrieval
# Remaining requests use shadow mode (log but don't affect retrieval)
PLANNER_TRAFFIC_PERCENT = int(os.getenv("PLANNER_TRAFFIC_PERCENT", "0"))

# Aggregation Routing - route aggregation queries to DynamoDB derived views
# **Task: 16.5 - Aggregation Query Routing**
# **Requirements: 5.6, 5.7** - Route leases/vacancy/activity queries to derived views
AGGREGATION_ROUTING_ENABLED = os.getenv("AGGREGATION_ROUTING_ENABLED", "true").lower() == "true"

# Aggregation object-to-view mapping
AGGREGATION_OBJECTS = {
    "ascendix__Availability__c": "availability_view",
    "ascendix__Property__c": "vacancy_view",
    "ascendix__Lease__c": "leases_view",
    "Task": "activities_agg",
    "Event": "activities_agg",
    "ascendix__Sale__c": "sales_view",
}

# Keywords that indicate aggregation queries
AGGREGATION_KEYWORDS = {
    "vacancy", "vacant", "available", "availability",
    "expiring", "expires", "lease expiration",
    "activity", "activities", "interactions",
    "count", "total", "how many",
}

# Task 31.4: Consolidated init log - emit runtime config once
# This replaces scattered print statements with a single summary
print(f"[INIT] Retrieve Lambda config: "
      f"PLANNER_ENABLED={PLANNER_ENABLED}, "
      f"PLANNER_TIMEOUT_MS={PLANNER_TIMEOUT_MS}, "
      f"PLANNER_TRAFFIC_PERCENT={PLANNER_TRAFFIC_PERCENT}, "
      f"PLANNER_MIN_CONFIDENCE={PLANNER_MIN_CONFIDENCE}, "
      f"PLANNER_SHADOW_MODE={PLANNER_SHADOW_MODE}, "
      f"CROSS_OBJECT_TIMEOUT_MS={CROSS_OBJECT_TIMEOUT_MS}")
print(f"[INIT] Component availability: "
      f"Planner={PLANNER_AVAILABLE}, "
      f"VocabCache={VOCAB_CACHE_AVAILABLE}, "
      f"SchemaCache={SCHEMA_CACHE_AVAILABLE}")

SUPPORTED_AUTHZ_MODES = {"indexFilter", "postFilter", "both"}
FILTER_KEY_ALIASES = {
    "sobject": "sobject",
    "sobjects": "sobject",
    "Region": "region",
    "region": "region",
    "BusinessUnit": "businessUnit",
    "businessUnit": "businessUnit",
    "business_unit": "businessUnit",
    "Quarter": "quarter",
    "quarter": "quarter",
}
SUPPORTED_SOBJECTS = {
    # Standard objects
    "Account",
    "Opportunity",
    "Case",
    "Note",
    # Legacy custom objects
    "Property__c",
    "Lease__c",
    "Contract__c",
    # Ascendix CRE objects
    "ascendix__Property__c",
    "ascendix__Availability__c",
    "ascendix__Lease__c",
    "ascendix__Sale__c",
    "ascendix__Deal__c",
}


# In-memory cache for retrieval results (LRU with TTL)
class RetrievalCache:
    """Simple LRU cache with TTL for retrieval results."""
    
    def __init__(self, max_size: int = CACHE_MAX_SIZE, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
    
    def _compute_cache_key(self, query: str, filters: Dict[str, Any], top_k: int, user_id: str) -> str:
        """Compute cache key from query parameters."""
        # Create a deterministic hash of the query parameters
        cache_data = {
            "query": query.lower().strip(),
            "filters": filters,
            "topK": top_k,
            "userId": user_id,
        }
        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.sha256(cache_str.encode()).hexdigest()
    
    def get(self, query: str, filters: Dict[str, Any], top_k: int, user_id: str) -> Optional[Dict[str, Any]]:
        """Get cached result if available and not expired."""
        cache_key = self._compute_cache_key(query, filters, top_k, user_id)
        
        if cache_key not in self.cache:
            return None
        
        # Check if expired
        cached_item = self.cache[cache_key]
        cached_at = cached_item.get("cached_at", 0)
        if time.time() - cached_at > self.ttl_seconds:
            # Expired, remove from cache
            del self.cache[cache_key]
            return None
        
        # Move to end (most recently used)
        self.cache.move_to_end(cache_key)
        return cached_item.get("result")
    
    def put(self, query: str, filters: Dict[str, Any], top_k: int, user_id: str, result: Dict[str, Any]) -> None:
        """Store result in cache."""
        cache_key = self._compute_cache_key(query, filters, top_k, user_id)
        
        # Remove oldest item if cache is full
        if len(self.cache) >= self.max_size and cache_key not in self.cache:
            self.cache.popitem(last=False)
        
        # Store with timestamp
        self.cache[cache_key] = {
            "result": result,
            "cached_at": time.time(),
        }
        
        # Move to end (most recently used)
        self.cache.move_to_end(cache_key)
    
    def clear(self) -> None:
        """Clear all cached items."""
        self.cache.clear()


# Global cache instance (persists across warm Lambda invocations)
_retrieval_cache = RetrievalCache()


class ValidationError(Exception):
    """Raised when the request payload is invalid."""


class AuthZServiceError(Exception):
    """Raised when the AuthZ Sidecar invocation fails."""


class BedrockKBError(Exception):
    """Raised when Bedrock Knowledge Base query fails."""


def emit_cache_metric(metric_name: str, value: float = 1.0) -> None:
    """
    Emit CloudWatch metric for cache performance monitoring.
    
    Args:
        metric_name: Name of the metric (RetrievalCacheHit, RetrievalCacheMiss)
        value: Metric value (default: 1.0)
    """
    try:
        cloudwatch.put_metric_data(
            Namespace='SalesforceAISearch/Retrieve',
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Value': value,
                    'Unit': 'Count',
                    'Timestamp': datetime.now(timezone.utc)
                }
            ]
        )
    except Exception as e:
        # Don't fail the request if metric emission fails
        LOGGER.warning("Failed to emit CloudWatch metric %s: %s", metric_name, e)


def _decode_event_body(event: Dict[str, Any]) -> Dict[str, Any]:
    """Extract JSON body from an API Gateway event or raw dict."""
    if not isinstance(event, dict):
        raise ValidationError("Event payload must be a dictionary")

    body = event.get("body", event)
    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        if event.get("isBase64Encoded"):
            try:
                decoded = base64.b64decode(body)
                body = decoded.decode("utf-8")
            except Exception as exc:  # pragma: no cover - defensive
                raise ValidationError("Unable to decode base64-encoded body") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValidationError("Request body must be valid JSON") from exc

    raise ValidationError("Request body must be a JSON object")


def _normalize_filters(raw_filters: Any) -> Dict[str, Any]:
    """Normalize incoming filters into canonical keys."""
    if raw_filters is None:
        return {}

    if not isinstance(raw_filters, dict):
        raise ValidationError("filters must be an object")

    normalized: Dict[str, Any] = {}

    for incoming_key, raw_value in raw_filters.items():
        canonical = FILTER_KEY_ALIASES.get(incoming_key)
        if not canonical or raw_value in (None, ""):
            continue

        values: List[str]
        if isinstance(raw_value, list):
            values = [str(v).strip() for v in raw_value if v not in (None, "")]
        else:
            values = [str(raw_value).strip()]

        if not values:
            continue

        if canonical == "sobject":
            filtered = [v for v in values if v in SUPPORTED_SOBJECTS]
            if filtered:
                existing = normalized.get("sobject", [])
                for value in filtered:
                    if value not in existing:
                        existing.append(value)
                normalized["sobject"] = existing
        else:
            # Scalar filters keep the latest non-empty value
            normalized[canonical] = values[-1]

    return normalized


def _validate_salesforce_user(user_id: Any) -> str:
    if not isinstance(user_id, str) or not user_id:
        raise ValidationError("salesforceUserId is required")

    trimmed = user_id.strip()
    if not (trimmed.startswith("005") and len(trimmed) in (15, 18)):
        raise ValidationError("salesforceUserId must be a 15 or 18 char ID starting with 005")

    return trimmed


def _parse_request(event: Dict[str, Any]) -> Dict[str, Any]:
    payload = _decode_event_body(event)

    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValidationError("query is required")

    salesforce_user_id = _validate_salesforce_user(payload.get("salesforceUserId"))

    top_k_raw = payload.get("topK", DEFAULT_TOP_K)
    try:
        top_k = int(top_k_raw)
    except (ValueError, TypeError) as exc:
        raise ValidationError("topK must be an integer") from exc

    if top_k <= 0:
        raise ValidationError("topK must be greater than zero")
    top_k = min(top_k, MAX_TOP_K)

    record_context = payload.get("recordContext") or {}
    if not isinstance(record_context, dict):
        raise ValidationError("recordContext must be an object if provided")

    filters = _normalize_filters(payload.get("filters"))

    authz_mode = payload.get("authzMode", "both")
    if authz_mode not in SUPPORTED_AUTHZ_MODES:
        raise ValidationError(
            f"authzMode must be one of {sorted(SUPPORTED_AUTHZ_MODES)}"
        )

    hybrid = payload.get("hybrid", True)
    if not isinstance(hybrid, bool):
        raise ValidationError("hybrid must be a boolean")

    # Clarification for disambiguation responses
    # **Requirements: 11.3**
    clarification = payload.get("clarification")
    if clarification is not None and not isinstance(clarification, dict):
        raise ValidationError("clarification must be an object if provided")

    return {
        "query": query.strip(),
        "salesforceUserId": salesforce_user_id,
        "topK": top_k,
        "recordContext": record_context,
        "filters": filters,
        "authzMode": authz_mode,
        "hybrid": hybrid,
        "clarification": clarification,
    }


def _invoke_authz_sidecar(salesforce_user_id: str) -> Dict[str, Any]:
    function_name = os.environ.get("AUTHZ_LAMBDA_FUNCTION_NAME")
    if not function_name:
        raise AuthZServiceError("AUTHZ_LAMBDA_FUNCTION_NAME is not configured")

    request_payload = json.dumps({
        "operation": "getAuthZContext",
        "salesforceUserId": salesforce_user_id,
    })

    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=request_payload.encode("utf-8"),
        )
    except (ClientError, BotoCoreError) as exc:
        raise AuthZServiceError(f"Failed to invoke AuthZ Sidecar: {exc}") from exc

    payload_stream = response.get("Payload")
    raw_body = payload_stream.read() if payload_stream else b""
    try:
        decoded = raw_body.decode("utf-8") if isinstance(raw_body, (bytes, bytearray)) else raw_body
        data = json.loads(decoded)
    except Exception as exc:
        raise AuthZServiceError("AuthZ Sidecar returned invalid JSON") from exc

    status_code = data.get("statusCode")
    body = data.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"error": body}

    if status_code and status_code >= 400:
        message = body.get("error") if isinstance(body, dict) else "Unknown error"
        raise AuthZServiceError(f"AuthZ Sidecar error ({status_code}): {message}")

    if isinstance(body, dict):
        return body

    return data if isinstance(data, dict) else {}


def _build_metadata_filters(filters: Dict[str, Any], authz_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build Bedrock KB metadata filters from request filters and authz context.

    Note: Bedrock KB uses flat metadata keys (e.g., 'sobject'), not nested (e.g., 'metadata.sobject').
    """
    metadata_filters: List[Dict[str, Any]] = []

    sobjects = filters.get("sobject", [])
    if sobjects:
        metadata_filters.append({
            "field": "sobject",
            "operator": "IN",
            "values": sobjects,
        })

    region = filters.get("region")
    if region:
        metadata_filters.append({
            "field": "region",
            "operator": "EQ",
            "value": region,
        })

    business_unit = filters.get("businessUnit")
    if business_unit:
        metadata_filters.append({
            "field": "businessUnit",
            "operator": "EQ",
            "value": business_unit,
        })

    quarter = filters.get("quarter")
    if quarter:
        metadata_filters.append({
            "field": "quarter",
            "operator": "EQ",
            "value": quarter,
        })

    sharing_buckets = authz_context.get("sharingBuckets", [])
    # if sharing_buckets:
    #     metadata_filters.append({
    #         "field": "sharingBuckets",
    #         "operator": "CONTAINS_ANY",
    #         "values": sharing_buckets,
    #     })

    fls_profile_tags = authz_context.get("flsProfileTags", [])
    if fls_profile_tags:
        metadata_filters.append({
            "field": "flsProfileTags",
            "operator": "CONTAINS_ANY",
            "values": fls_profile_tags,
        })

    return metadata_filters


def _detect_temporal_filter(query: str) -> Optional[Dict[str, Any]]:
    """Detect temporal query patterns and return metadata filter.

    Handles queries like:
    - "active leases" / "leases not expired" → temporalStatus = ACTIVE
    - "expiring leases" / "leases expiring soon" → temporalStatus = EXPIRING_SOON
    - "expired leases" → temporalStatus = EXPIRED
    - "new deals" / "recent deals" → temporalStatus = NEW or RECENT

    Returns dict with filter configuration for Bedrock KB metadata filtering.
    """
    query_lower = query.lower()

    # Lease temporal patterns
    lease_patterns = [
        # Active/not expired leases
        (r'\b(?:active|current|valid)\s+lease', 'ACTIVE'),
        (r'\blease[s]?\s+(?:not\s+)?(?:yet\s+)?expir(?:ed|ing)', 'ACTIVE'),
        (r'\bnot\s+(?:yet\s+)?expired\s+lease', 'ACTIVE'),
        (r'\bunexpired\s+lease', 'ACTIVE'),
        # Expiring soon
        (r'\b(?:expiring|about\s+to\s+expire)\s+(?:soon\s+)?lease', 'EXPIRING_SOON'),
        (r'\blease[s]?\s+expiring\s+(?:soon|this\s+month|next\s+month)', 'EXPIRING_SOON'),
        (r'\bexpiring\s+(?:soon|this\s+month|this\s+quarter)', 'EXPIRING_SOON'),
        # Expired
        (r'\bexpired\s+lease', 'EXPIRED'),
        (r'\blease[s]?\s+(?:that\s+)?(?:have\s+)?expired', 'EXPIRED'),
    ]

    # Deal temporal patterns
    deal_patterns = [
        # New deals
        (r'\bnew\s+deal', 'NEW'),
        (r'\bdeal[s]?\s+(?:created\s+)?this\s+week', 'NEW'),
        # Recent deals
        (r'\brecent\s+deal', 'RECENT'),
        (r'\bdeal[s]?\s+(?:from\s+)?this\s+month', 'RECENT'),
        # This quarter
        (r'\bdeal[s]?\s+this\s+quarter', 'THIS_QUARTER'),
        (r'\bquarterly\s+deal', 'THIS_QUARTER'),
    ]

    # Check lease patterns first (more specific)
    for pattern, status in lease_patterns:
        if re.search(pattern, query_lower):
            LOGGER.info(f"Temporal filter detected: Lease temporalStatus={status}")
            return {
                "field": "temporalStatus",
                "operator": "EQ",
                "value": status,
                "sobject": "ascendix__Lease__c",
            }

    # Check deal patterns
    for pattern, status in deal_patterns:
        if re.search(pattern, query_lower):
            LOGGER.info(f"Temporal filter detected: Deal temporalStatus={status}")
            return {
                "field": "temporalStatus",
                "operator": "EQ",
                "value": status,
                "sobject": "ascendix__Deal__c",
            }

    return None


def _detect_ranking_query(query: str) -> Optional[Dict[str, Any]]:
    """Detect if query is a ranking query and extract ranking parameters.

    Handles queries like "top 10 deals by gross fee amount" or "largest deals by value".

    Returns dict with:
        - limit: number of results requested (default 10)
        - field: the field to rank by (e.g., "gross fee amount", "fee", "value")
        - order: "desc" for top/highest/largest, "asc" for bottom/lowest/smallest
    """
    query_lower = query.lower()

    # Patterns for ranking queries
    ranking_patterns = [
        # "top N [anything] by X"
        (r'\btop\s+(\d+)\b.+?\bby\s+([\w\s]+?)(?:\?|$|\.)', 'desc'),
        # "top [anything] by X" (no number)
        (r'\btop\b.+?\bby\s+([\w\s]+?)(?:\?|$|\.)', 'desc'),
        # "largest/highest [anything] by Y"
        (r'\b(?:largest|highest|biggest)\b.+?\bby\s+([\w\s]+?)(?:\?|$|\.)', 'desc'),
        # "smallest/lowest [anything] by Y"
        (r'\b(?:smallest|lowest)\b.+?\bby\s+([\w\s]+?)(?:\?|$|\.)', 'asc'),
    ]

    for pattern, order in ranking_patterns:
        match = re.search(pattern, query_lower)
        if match:
            groups = match.groups()
            # Extract limit if present
            limit = 10
            field = groups[-1].strip()  # Last group is always the field

            if len(groups) > 1 and groups[0] and groups[0].isdigit():
                limit = int(groups[0])

            LOGGER.info(f"Detected ranking query: field='{field}', limit={limit}, order={order}")
            return {
                "limit": limit,
                "field": field,
                "order": order,
            }

    return None


def _extract_numerical_value(text: str, field_hint: str) -> Optional[float]:
    """Extract numerical value from chunk text based on field hint.

    Args:
        text: The chunk text content
        field_hint: Hint about which field to extract (e.g., "gross fee", "fee amount")

    Returns:
        The extracted numerical value, or None if not found
    """
    # Build patterns based on field hint
    field_patterns = []

    if 'fee' in field_hint.lower():
        field_patterns.extend([
            r'(?:gross\s+)?fee\s+amount[:\s]*\$?([\d,]+(?:\.\d{2})?)',
            r'fee[:\s]*\$?([\d,]+(?:\.\d{2})?)',
        ])

    if 'amount' in field_hint.lower() or 'value' in field_hint.lower():
        field_patterns.extend([
            r'amount[:\s]*\$?([\d,]+(?:\.\d{2})?)',
            r'value[:\s]*\$?([\d,]+(?:\.\d{2})?)',
        ])

    if 'price' in field_hint.lower():
        field_patterns.append(r'price[:\s]*\$?([\d,]+(?:\.\d{2})?)')

    if 'size' in field_hint.lower() or 'sqft' in field_hint.lower() or 'square' in field_hint.lower():
        field_patterns.extend([
            r'(?:rentable|total)\s+(?:sf|sqft|square\s+feet)[:\s]*([\d,]+)',
            r'size[:\s]*([\d,]+)',
        ])

    # Default: look for any dollar amount
    if not field_patterns:
        field_patterns.append(r'\$?([\d,]+(?:\.\d{2})?)')

    for pattern in field_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value_str = match.group(1).replace(',', '')
            try:
                return float(value_str)
            except ValueError:
                continue

    return None


def _apply_post_retrieval_ranking(
    matches: List[Dict[str, Any]],
    ranking_params: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Apply post-retrieval ranking to sort results by numerical field.

    Args:
        matches: List of retrieval results
        ranking_params: Dict with 'field', 'limit', 'order' from _detect_ranking_query

    Returns:
        Re-ranked list of matches
    """
    field = ranking_params.get("field", "")
    limit = ranking_params.get("limit", 10)
    order = ranking_params.get("order", "desc")

    # Map field hints to metadata keys
    field_lower = field.lower()
    metadata_key = None
    if 'fee' in field_lower or 'amount' in field_lower:
        metadata_key = "grossFeeAmount"

    # Extract numerical values for each match
    scored_matches = []
    for match in matches:
        value = None

        # First, try to get value from metadata (more reliable)
        metadata = match.get("metadata", {})
        if metadata_key and metadata_key in metadata:
            try:
                value = float(metadata[metadata_key])
            except (ValueError, TypeError):
                pass

        # Fall back to text extraction if metadata not available
        if value is None:
            text = match.get("text", "")
            value = _extract_numerical_value(text, field)

        if value is not None:
            scored_matches.append((match, value))
        else:
            # Keep matches without values at the end
            scored_matches.append((match, 0 if order == "desc" else float('inf')))

    # Sort by extracted value
    reverse = (order == "desc")
    scored_matches.sort(key=lambda x: x[1], reverse=reverse)

    # Log the ranking
    LOGGER.info(f"Post-retrieval ranking applied: {len(scored_matches)} matches sorted by '{field}' ({order})")
    if scored_matches:
        top_values = [(m[0].get("text", "")[:50], m[1]) for m in scored_matches[:3]]
        LOGGER.info(f"Top 3 values: {top_values}")

    # Return limited results
    return [m[0] for m in scored_matches[:limit]]


def _rewrite_aggregation_query(query: str) -> str:
    """Rewrite aggregation queries to include ranking keywords for better hybrid search.

    Handles queries like "top 10 deals by fee" by adding keywords that BM25 can match.
    """
    query_lower = query.lower()

    # Detect aggregation patterns
    aggregation_patterns = [
        (r'\btop\s+(\d+)\s+', 'highest largest biggest most expensive '),
        (r'\blargest\b', 'highest biggest most expensive maximum '),
        (r'\bhighest\b', 'largest biggest most expensive maximum '),
        (r'\bbiggest\b', 'largest highest most expensive maximum '),
        (r'\bsmallest\b', 'lowest minimum cheapest least '),
        (r'\blowest\b', 'smallest minimum cheapest least '),
    ]

    rewrite_needed = False
    additions = []

    for pattern, keywords in aggregation_patterns:
        if re.search(pattern, query_lower):
            rewrite_needed = True
            additions.append(keywords)

    # Detect fee/amount-related queries
    fee_patterns = [r'\bfee\b', r'\bamount\b', r'\bvalue\b', r'\bprice\b', r'\bcost\b']
    for pattern in fee_patterns:
        if re.search(pattern, query_lower):
            # Add common fee amounts to help BM25 match high-value records
            additions.append('$1,000,000 $2,000,000 $5,000,000 million ')

    if rewrite_needed and additions:
        # Append keywords to original query for hybrid search benefit
        expanded_query = query + " " + " ".join(set(" ".join(additions).split()))
        LOGGER.info(f"Query rewritten for hybrid search: '{query}' -> '{expanded_query[:200]}...'")
        return expanded_query

    return query


# Object type detection patterns for CRE domain
# Exclusions prevent false positives (e.g., "lease deal" should be Deal, not Lease)
INTENT_PATTERNS = {
    'ascendix__Property__c': {
        'keywords': [
            r'\bpropert(?:y|ies)\b',
            r'\bbuilding(?:s)?\b',
            r'\boffice(?:s)?\b',
            r'\btower(?:s)?\b',
            r'\bcomplex(?:es)?\b',
            r'\bpark(?:s)?\b',  # e.g., "business park"
            r'\breal estate\b',
            r'\bsquare\s+feet\b',
            r'\bsqft\b',
            r'\bclass\s+[abc]\b',  # "Class A building"
        ],
        'exclusions': [r'\bproperty\s+sale', r'\bsale\s+of\s+property'],  # Property sale = Sale object
        'priority': 2,
    },
    'ascendix__Deal__c': {
        'keywords': [
            r'\bdeal(?:s)?\b',
            r'\btransaction(?:s)?\b',
            r'\bopportunit(?:y|ies)\b',
            r'\bpipeline\b',
            r'\bfee(?:s)?\b',
            r'\bcommission(?:s)?\b',
            r'\bstage\b',
            r'\bwon\b',
            r'\bopen deal(?:s)?\b',
            r'\bclosed deal(?:s)?\b',
            r'\bloi\b',  # Letter of Intent
            r'\blease\s+deal(?:s)?\b',  # "lease deal" = Deal, not Lease
            r'\bsale\s+deal(?:s)?\b',  # "sale deal" = Deal
            r'\bacquisition(?:s)?\b',  # Acquisition deals are tracked as Deal objects
            r'\bstatus\s+of\b',  # "status of X" queries are typically about Deals
        ],
        'exclusions': [],
        'priority': 3,  # Increased priority - deals are explicit
    },
    'ascendix__Lease__c': {
        'keywords': [
            r'\btenant(?:s)?\b',
            r'\brental\b',
            r'\brent\b',
            r'\bterm\s+expir',
            r'\bexpiring\b',
            r'\blease\s+expir',
            r'\bnnn\b',  # Triple Net
            r'\bgross\s+lease\b',
            r'\bcurrent\s+lease(?:s)?\b',
            r'\bactive\s+lease(?:s)?\b',
        ],
        'exclusions': [r'\blease\s+deal', r'\bfor\s+lease'],  # "lease deal" = Deal, "for lease" = Availability
        'priority': 2,
        'standalone_lease': r'(?<!\w)\blease(?:s)?\b(?!\s+deal)',  # Only match standalone "lease" not followed by "deal"
    },
    'ascendix__Availability__c': {
        'keywords': [
            r'\bavailab(?:le|ility)\b',
            r'\bvacant\b',
            r'\bvacanc(?:y|ies)\b',
            r'\bsuite(?:s)?\b',
            r'\bspace(?:s)?\s+(?:for|to)\s+(?:lease|rent)\b',
            r'\bavailable\s+space(?:s)?\b',
            r'\bfor\s+lease\b',
            r'\bfor\s+rent\b',
        ],
        'exclusions': [],
        'priority': 4,  # Highest priority
    },
    'ascendix__Sale__c': {
        'keywords': [
            r'\bsale(?:s)?\b',
            r'\bsold\b',
            r'\bproperty\s+sale(?:s)?\b',
            r'\brecent\s+sale(?:s)?\b',
            r'\bacquisition(?:s)?\b',
            r'\bpurchase(?:s|d)?\b',
        ],
        'exclusions': [r'\bsale\s+deal', r'\bfor\s+sale'],  # "sale deal" = Deal
        'priority': 3,
    },
    'Account': {
        'keywords': [
            r'\baccount(?:s)?\b',
            r'\bcompan(?:y|ies)\b',
            r'\bclient(?:s)?\b',
            r'\bcustomer(?:s)?\b',
            r'\borganization(?:s)?\b',
        ],
        'exclusions': [],
        'priority': 1,  # Lower priority
    },
}


def _detect_intent(query: str) -> Optional[List[str]]:
    """Detect target object type(s) from the query using keyword patterns.

    Returns a list of sobject API names that match the query intent,
    sorted by match priority and confidence.

    Handles exclusions to prevent false positives (e.g., "lease deal" → Deal, not Lease).
    """
    query_lower = query.lower()
    matches = []

    for sobject, config in INTENT_PATTERNS.items():
        # Check exclusions first - if any exclusion matches, skip counting keywords
        exclusions = config.get('exclusions', [])
        is_excluded = False
        for excl in exclusions:
            if re.search(excl, query_lower, re.IGNORECASE):
                is_excluded = True
                LOGGER.debug(f"Intent exclusion matched for {sobject}: {excl}")
                break

        if is_excluded:
            continue

        match_count = 0
        for pattern in config['keywords']:
            if re.search(pattern, query_lower, re.IGNORECASE):
                match_count += 1

        # Special handling for standalone lease patterns
        if sobject == 'ascendix__Lease__c' and match_count == 0:
            standalone = config.get('standalone_lease')
            if standalone and re.search(standalone, query_lower, re.IGNORECASE):
                match_count = 1

        if match_count > 0:
            # Score = match_count * priority
            score = match_count * config['priority']
            matches.append((sobject, score, match_count))

    if not matches:
        return None

    # Sort by score descending
    matches.sort(key=lambda x: x[1], reverse=True)

    # Get the top match
    top_sobject, top_score, top_count = matches[0]

    # If there's a clear winner (score > 2x second place), use only that
    if len(matches) > 1:
        second_score = matches[1][1]
        if top_score >= second_score * 2:
            LOGGER.info(f"Intent detected: {top_sobject} (score={top_score}, clear winner)")
            return [top_sobject]

    # If multiple matches with similar scores, return top 2
    if len(matches) > 1 and matches[1][1] >= top_score * 0.5:
        result = [matches[0][0], matches[1][0]]
        LOGGER.info(f"Intent detected: {result} (ambiguous, top 2)")
        return result

    LOGGER.info(f"Intent detected: {top_sobject} (score={top_score})")
    return [top_sobject]


def _get_sobject_for_view(view_name: str) -> str:
    """Map derived view name back to Salesforce object type."""
    VIEW_TO_SOBJECT = {
        "leases_view": "ascendix__Lease__c",
        "vacancy_view": "ascendix__Property__c",
        "availability_view": "ascendix__Availability__c",
        "activities_agg": "Task",  # Activities are represented as Task
        "sales_view": "ascendix__Sale__c",
    }
    return VIEW_TO_SOBJECT.get(view_name, "ascendix__Property__c")


def _format_aggregation_content(record_dict: Dict[str, Any], view_name: str) -> str:
    """Format aggregation record as human-readable content for LLM context."""
    lines = []

    if view_name == "leases_view":
        name = record_dict.get("lease_name") or record_dict.get("name", "Lease")
        lines.append(f"# {name}")
        if record_dict.get("tenant_name"):
            lines.append(f"Tenant: {record_dict['tenant_name']}")
        if record_dict.get("property_name"):
            lines.append(f"Property: {record_dict['property_name']}")
        if record_dict.get("end_date"):
            lines.append(f"Lease End Date: {record_dict['end_date']}")
        if record_dict.get("rsf"):
            lines.append(f"RSF: {record_dict['rsf']:,.0f}" if isinstance(record_dict['rsf'], (int, float)) else f"RSF: {record_dict['rsf']}")
        if record_dict.get("rent"):
            lines.append(f"Rent: ${record_dict['rent']:,.2f}" if isinstance(record_dict['rent'], (int, float)) else f"Rent: {record_dict['rent']}")

    elif view_name == "vacancy_view":
        name = record_dict.get("property_name") or record_dict.get("name", "Property")
        lines.append(f"# {name}")
        if record_dict.get("city"):
            city_state = f"{record_dict['city']}, {record_dict.get('state', '')}"
            lines.append(f"Location: {city_state}")
        if record_dict.get("property_class"):
            lines.append(f"Class: {record_dict['property_class']}")
        if record_dict.get("vacancy_pct") is not None:
            lines.append(f"Vacancy Rate: {record_dict['vacancy_pct']:.1f}%")
        if record_dict.get("vacant_sqft"):
            lines.append(f"Vacant SF: {record_dict['vacant_sqft']:,.0f}")
        if record_dict.get("total_sqft"):
            lines.append(f"Total SF: {record_dict['total_sqft']:,.0f}")

    elif view_name == "activities_agg":
        name = record_dict.get("entity_name") or record_dict.get("name", "Entity")
        lines.append(f"# {name} - Activity Summary")
        if record_dict.get("entity_type"):
            lines.append(f"Type: {record_dict['entity_type']}")
        if record_dict.get("count_30d") is not None:
            lines.append(f"Activities (30 days): {record_dict['count_30d']}")
        if record_dict.get("count_90d") is not None:
            lines.append(f"Activities (90 days): {record_dict['count_90d']}")
        if record_dict.get("last_activity_date"):
            lines.append(f"Last Activity: {record_dict['last_activity_date']}")

    elif view_name == "sales_view":
        name = record_dict.get("sale_name") or record_dict.get("property_name") or record_dict.get("name", "Sale")
        lines.append(f"# {name}")
        if record_dict.get("property_name"):
            lines.append(f"Property: {record_dict['property_name']}")
        if record_dict.get("city"):
            lines.append(f"Location: {record_dict['city']}")
        if record_dict.get("sale_date"):
            lines.append(f"Sale Date: {record_dict['sale_date']}")
        if record_dict.get("sale_price"):
            lines.append(f"Sale Price: ${record_dict['sale_price']:,.0f}" if isinstance(record_dict['sale_price'], (int, float)) else f"Sale Price: {record_dict['sale_price']}")
        if record_dict.get("listing_price"):
            lines.append(f"Listing Price: ${record_dict['listing_price']:,.0f}" if isinstance(record_dict['listing_price'], (int, float)) else f"Listing Price: {record_dict['listing_price']}")
        if record_dict.get("buyer_name"):
            lines.append(f"Buyer: {record_dict['buyer_name']}")
        if record_dict.get("seller_name"):
            lines.append(f"Seller: {record_dict['seller_name']}")

    elif view_name == "availability_view":
        # Build a descriptive name from available fields
        name = record_dict.get("availability_name") or record_dict.get("property_name") or record_dict.get("name")
        if not name:
            # Build name from location and type info
            parts = []
            if record_dict.get("city"):
                parts.append(record_dict["city"])
            if record_dict.get("property_type"):
                parts.append(record_dict["property_type"])
            if record_dict.get("property_class"):
                parts.append(f"Class {record_dict['property_class']}")
            name = " ".join(parts) if parts else "Availability"
        lines.append(f"# {name} - Available Space")

        # Location info
        if record_dict.get("city") or record_dict.get("state"):
            city = record_dict.get("city", "")
            state = record_dict.get("state", "")
            location = f"{city}, {state}".strip(", ")
            lines.append(f"Location: {location}")
        if record_dict.get("submarket"):
            lines.append(f"Submarket: {record_dict['submarket']}")

        # Property classification
        if record_dict.get("property_class"):
            lines.append(f"Property Class: {record_dict['property_class']}")
        if record_dict.get("property_type"):
            lines.append(f"Property Type: {record_dict['property_type']}")

        # Space details - use 'size' field from AvailabilityRecord
        if record_dict.get("size"):
            size = record_dict['size']
            lines.append(f"Available SF: {size:,.0f}" if isinstance(size, (int, float)) else f"Available SF: {size}")
        if record_dict.get("available_sqft"):
            lines.append(f"Available SF: {record_dict['available_sqft']:,.0f}")

        # Status
        if record_dict.get("status"):
            lines.append(f"Status: {record_dict['status']}")

        # TI hints if available
        if record_dict.get("ti_hints"):
            lines.append(f"TI Notes: {record_dict['ti_hints']}")

        # Rent info if available
        if record_dict.get("asking_rent"):
            lines.append(f"Asking Rent: ${record_dict['asking_rent']:,.2f}/SF" if isinstance(record_dict['asking_rent'], (int, float)) else f"Asking Rent: {record_dict['asking_rent']}")
        if record_dict.get("available_date"):
            lines.append(f"Available Date: {record_dict['available_date']}")
    else:
        # Generic fallback
        lines.append(f"# Record from {view_name}")
        for key, value in record_dict.items():
            if value and not key.endswith("_id"):
                lines.append(f"{key.replace('_', ' ').title()}: {value}")

    return "\n".join(lines) if lines else str(record_dict)


def _query_bedrock_kb(query: str, top_k: int, metadata_filters: List[Dict[str, Any]], use_hybrid: bool = True) -> List[Dict[str, Any]]:
    """Query Bedrock Knowledge Base with hybrid search and metadata filters."""
    knowledge_base_id = os.getenv("KNOWLEDGE_BASE_ID", "")
    if not knowledge_base_id:
        raise BedrockKBError("KNOWLEDGE_BASE_ID environment variable is not configured")

    # Rewrite aggregation queries for better hybrid search results
    search_query = _rewrite_aggregation_query(query) if use_hybrid else query

    # Build the retrieval configuration with hybrid search enabled
    retrieval_config = {
        "vectorSearchConfiguration": {
            "numberOfResults": top_k,
            "overrideSearchType": "HYBRID" if use_hybrid else "SEMANTIC",
        }
    }

    # Convert metadata filters to Bedrock KB format
    if metadata_filters:
        bedrock_filters = []
        for filter_item in metadata_filters:
            field = filter_item.get("field", "")
            operator = filter_item.get("operator", "")
            
            # Build filter based on operator type
            if operator == "IN":
                values = filter_item.get("values", [])
                if values:
                    bedrock_filters.append({
                        "in": {
                            "key": field,
                            "value": values
                        }
                    })
            elif operator == "EQ":
                value = filter_item.get("value")
                if value is not None:
                    bedrock_filters.append({
                        "equals": {
                            "key": field,
                            "value": value
                        }
                    })
            elif operator == "CONTAINS_ANY":
                values = filter_item.get("values", [])
                if values:
                    # For CONTAINS_ANY, we need to check if the field contains any of the values
                    # In Bedrock KB, we can use "in" operator on array fields
                    bedrock_filters.append({
                        "in": {
                            "key": field,
                            "value": values
                        }
                    })

        if bedrock_filters:
            # Combine filters with AND logic
            if len(bedrock_filters) == 1:
                retrieval_config["vectorSearchConfiguration"]["filter"] = bedrock_filters[0]
            else:
                retrieval_config["vectorSearchConfiguration"]["filter"] = {
                    "andAll": bedrock_filters
                }

    LOGGER.info(f"Bedrock Retrieval Config: {json.dumps(retrieval_config)}")
    LOGGER.info(f"Search query (original: '{query[:100]}'): '{search_query[:200]}'")

    try:
        response = bedrock_agent_runtime_client.retrieve(
            knowledgeBaseId=knowledge_base_id,
            retrievalQuery={
                "text": search_query
            },
            retrievalConfiguration=retrieval_config
        )
    except (ClientError, BotoCoreError) as exc:
        LOGGER.error("Bedrock KB query failed: %s", exc)
        raise BedrockKBError(f"Failed to query Bedrock Knowledge Base: {exc}") from exc

    # Parse retrieval results
    matches = []
    retrieval_results = response.get("retrievalResults", [])
    
    for result in retrieval_results:
        content = result.get("content", {})
        text = content.get("text", "")
        location = result.get("location", {})
        s3_location = location.get("s3Location", {})
        uri = s3_location.get("uri", "")
        
        metadata = result.get("metadata", {})
        score = result.get("score", 0.0)
        
        # Extract record ID from URI or metadata
        record_id = metadata.get("recordId", "")
        sobject = metadata.get("sobject", "")
        
        # Build match object
        match = {
            "id": uri or f"{sobject}/{record_id}",
            "score": score,
            "text": text,
            "metadata": metadata
        }
        
        matches.append(match)
    
    return matches


def _log_telemetry_async(
    request_id: str,
    request_payload: Dict[str, Any],
    match_count: int,
    trace: Dict[str, Any],
    authz_cached: bool
) -> None:
    """Log telemetry to DynamoDB asynchronously (non-blocking)."""
    telemetry_table_name = os.getenv("TELEMETRY_TABLE_NAME", "")
    if not telemetry_table_name:
        LOGGER.warning("TELEMETRY_TABLE_NAME not configured, skipping telemetry logging")
        return
    
    try:
        table = dynamodb.Table(telemetry_table_name)
        
        # Convert floats to Decimal for DynamoDB
        from decimal import Decimal
        
        safe_trace = {}
        for k, v in trace.items():
            if isinstance(v, float):
                safe_trace[k] = Decimal(str(v))
            else:
                safe_trace[k] = v
        
        # Build telemetry item
        item = {
            "requestId": request_id,
            "timestamp": int(time.time()),
            "endpoint": "/retrieve",
            "salesforceUserId": request_payload.get("salesforceUserId", ""),
            "query": request_payload.get("query", ""),
            "filters": request_payload.get("filters", {}),
            "topK": request_payload.get("topK", 0),
            "matchCount": match_count,
            "authzCached": authz_cached,
            "trace": safe_trace,
            "success": True,
        }
        
        # Write to DynamoDB (this is synchronous but fast)
        # In production, consider using SQS for truly async logging
        table.put_item(Item=item)
        
    except Exception as exc:  # pragma: no cover - defensive
        # Don't fail the request if telemetry logging fails
        LOGGER.error("Failed to log telemetry: %s", exc)


def _generate_presigned_urls(matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate presigned S3 URLs for citation previews with 15-minute expiration."""
    expiration_seconds = 900  # 15 minutes
    
    for match in matches:
        match_id = match.get("id", "")
        
        # Try to extract S3 location from the match ID (format: s3://bucket/key)
        if match_id.startswith("s3://"):
            try:
                # Parse S3 URI
                s3_uri = match_id.replace("s3://", "")
                parts = s3_uri.split("/", 1)
                if len(parts) == 2:
                    bucket, key = parts
                    
                    # Generate presigned URL
                    presigned_url = s3_client.generate_presigned_url(
                        'get_object',
                        Params={
                            'Bucket': bucket,
                            'Key': key
                        },
                        ExpiresIn=expiration_seconds
                    )
                    match["previewUrl"] = presigned_url
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.warning("Failed to generate presigned URL for %s: %s", match_id, exc)
                # Continue without presigned URL
        
        # If no presigned URL was generated, we can still return the match
        # The client can use the record ID to fetch data via Salesforce API
    
    return matches


# =============================================================================
# Required Fields Contract - Runtime Guard (Gap 2)
# =============================================================================
# Define required fields per object type for presentation contract.
# If these are missing after enrichment, log for visibility.
# =============================================================================

REQUIRED_FIELDS_CONTRACT = {
    "ascendix__Availability__c": {
        "fields": ["propertyClass", "propertyType", "propertyCity", "propertyState", "propertyName"],
        "source": "enrichment",  # These come from Property via enrichment
    },
    "ascendix__Deal__c": {
        "fields": ["propertyClass", "propertyType", "propertyCity", "propertyState", "propertyName"],
        "source": "enrichment",  # These come from Property via enrichment
    },
    "ascendix__Lease__c": {
        "fields": ["propertyClass", "propertyType", "propertyCity", "propertyState", "propertyName"],
        "source": "enrichment",  # These come from Property via enrichment
    },
    "ascendix__Property__c": {
        "fields": ["ascendix__PropertyClass__c", "RecordType", "ascendix__City__c", "ascendix__State__c", "Name"],
        "source": "chunk",  # These should be in the chunk metadata
    },
}


def _validate_required_fields(
    matches: List[Dict[str, Any]],
    enrichment_attempted: bool = False,
) -> Dict[str, Any]:
    """
    Validate that matches have required fields per object type.

    Runtime guard that logs missing fields for visibility.
    Does NOT block results - just logs and returns validation summary.

    Args:
        matches: List of match objects with metadata
        enrichment_attempted: Whether enrichment was attempted

    Returns:
        Validation summary dict with missing field details
    """
    validation_result = {
        "totalMatches": len(matches),
        "validMatches": 0,
        "partialMatches": 0,
        "missingFieldsDetails": [],
        "enrichmentAttempted": enrichment_attempted,
    }

    for match in matches:
        metadata = match.get("metadata", {})
        sobject = metadata.get("sobject", "")
        record_id = metadata.get("recordId", "")

        contract = REQUIRED_FIELDS_CONTRACT.get(sobject)
        if not contract:
            # No contract defined for this object type - consider valid
            validation_result["validMatches"] += 1
            continue

        required_fields = contract["fields"]
        missing_fields = []

        for field in required_fields:
            # Check both metadata and text content for field presence
            has_in_metadata = field in metadata and metadata[field]
            has_in_text = False

            # Also check if field value appears in the text (enrichment adds to text)
            text = match.get("text", "")
            if contract["source"] == "enrichment":
                # For enriched fields, check common patterns in text
                field_patterns = {
                    "propertyClass": r"Property Class:\s*\w",
                    "propertyType": r"Property Type:\s*\w",
                    "propertyCity": r"(?:Location|City):\s*\w",
                    "propertyState": r"(?:Location.*,\s*[A-Z]{2}|State:\s*[A-Z]{2})",
                    "propertyName": r"Property:\s*\w",
                }
                pattern = field_patterns.get(field, "")
                if pattern and re.search(pattern, text):
                    has_in_text = True

            if not has_in_metadata and not has_in_text:
                missing_fields.append(field)

        if missing_fields:
            validation_result["partialMatches"] += 1
            validation_result["missingFieldsDetails"].append({
                "sobject": sobject,
                "recordId": record_id,
                "missingFields": missing_fields,
                "enrichmentSource": contract["source"],
            })

            # Log for visibility
            LOGGER.warning(
                f"[FIELD_CONTRACT] Missing required fields for {sobject}/{record_id}: "
                f"{missing_fields} (enrichment_attempted={enrichment_attempted})"
            )
        else:
            validation_result["validMatches"] += 1

    # Summary log
    if validation_result["partialMatches"] > 0:
        LOGGER.warning(
            f"[FIELD_CONTRACT] {validation_result['partialMatches']}/{validation_result['totalMatches']} "
            f"matches missing required fields (enrichment_attempted={enrichment_attempted})"
        )
    else:
        LOGGER.info(
            f"[FIELD_CONTRACT] All {validation_result['totalMatches']} matches have required fields"
        )

    return validation_result


def _enrich_availability_matches_with_property_data(
    matches: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Enrich Availability/Lease/Deal matches with parent Property data from graph.

    This is used when cross-object query returns child record IDs but the KB chunks
    don't contain Property-level attributes (class, type, city).

    Uses graph edges to find parent Property, then graph nodes to get attributes.

    Args:
        matches: KB matches for Availability/Lease/Deal records

    Returns:
        Enriched matches with Property context added to text
    """
    if not matches:
        return matches

    # Objects that have Property as parent and need enrichment
    PROPERTY_CHILD_OBJECTS = ('ascendix__Availability__c', 'ascendix__Lease__c', 'ascendix__Deal__c')

    # Filter to records that need enrichment
    child_record_ids = []
    for match in matches:
        metadata = match.get("metadata", {})
        sobject = metadata.get("sobject", "")
        if sobject in PROPERTY_CHILD_OBJECTS:
            record_id = metadata.get("recordId", "")
            if record_id:
                child_record_ids.append(record_id)

    if not child_record_ids:
        return matches

    LOGGER.info(f"[ENRICHMENT] Enriching {len(child_record_ids)} Availability/Lease/Deal records with Property data")

    try:
        dynamodb = boto3.resource('dynamodb')
        edges_table = dynamodb.Table(
            os.environ.get('GRAPH_EDGES_TABLE', 'salesforce-ai-search-graph-edges')
        )
        nodes_table = dynamodb.Table(
            os.environ.get('GRAPH_NODES_TABLE', 'salesforce-ai-search-graph-nodes')
        )

        # Step 1: Find parent Property IDs via edges (child -> Property relationship)
        # Edge structure: toId=child record, fromId=Property, fieldName=ascendix__Property__c
        child_to_property: Dict[str, str] = {}
        for child_id in child_record_ids:
            try:
                # Query edges where this record is the child (toId)
                response = edges_table.query(
                    IndexName='toId-index',  # GSI with toId as partition key
                    KeyConditionExpression='toId = :cid',
                    ExpressionAttributeValues={':cid': child_id},
                    Limit=10  # Usually just a few parent relationships
                )
                for edge in response.get('Items', []):
                    field_name = edge.get('fieldName', '')
                    from_id = edge.get('fromId', '')
                    # Property relationship is indicated by fieldName containing "Property"
                    if 'Property' in field_name and from_id:
                        child_to_property[child_id] = from_id
                        break
            except Exception as e:
                LOGGER.debug(f"Could not find parent Property for {child_id}: {e}")

        LOGGER.info(f"[ENRICHMENT] Found {len(child_to_property)} parent Properties")

        # Step 2: Fetch Property attributes from graph nodes
        property_ids = list(set(child_to_property.values()))
        property_data: Dict[str, Dict[str, Any]] = {}

        for prop_id in property_ids:
            try:
                # Key is 'nodeId' not 'id'
                response = nodes_table.get_item(Key={'nodeId': prop_id})
                item = response.get('Item', {})
                if item:
                    # Extract relevant Property attributes
                    # boto3 Table resource auto-converts DynamoDB format
                    attrs = item.get('attributes', {})
                    display_name = item.get('displayName', '')
                    property_data[prop_id] = {
                        'name': attrs.get('Name', '') or display_name,
                        'class': attrs.get('ascendix__PropertyClass__c', ''),
                        'type': attrs.get('RecordType.Name', '') or attrs.get('RecordType', '') or attrs.get('RecordTypeName', ''),
                        'city': attrs.get('ascendix__City__c', ''),
                        'state': attrs.get('ascendix__State__c', ''),
                        'submarket': attrs.get('ascendix__SubMarket__c', ''),
                    }
                    LOGGER.debug(f"[ENRICHMENT] Property {prop_id}: {property_data[prop_id]}")
            except Exception as e:
                LOGGER.debug(f"Could not fetch Property attributes for {prop_id}: {e}")

        LOGGER.info(f"[ENRICHMENT] Fetched data for {len(property_data)} Properties")

        # Step 3: Enrich matches with Property context
        enriched_count = 0
        for match in matches:
            metadata = match.get("metadata", {})
            record_id = metadata.get("recordId", "")
            sobject = metadata.get("sobject", "")

            if sobject not in PROPERTY_CHILD_OBJECTS:
                continue

            prop_id = child_to_property.get(record_id)
            if not prop_id:
                continue

            prop_data = property_data.get(prop_id)
            if not prop_data:
                continue

            # Build property context string
            context_parts = []
            if prop_data.get('name'):
                context_parts.append(f"Property: {prop_data['name']}")
            if prop_data.get('city'):
                location = prop_data['city']
                if prop_data.get('state'):
                    location += f", {prop_data['state']}"
                context_parts.append(f"Location: {location}")
            if prop_data.get('class'):
                context_parts.append(f"Property Class: {prop_data['class']}")
            if prop_data.get('type'):
                context_parts.append(f"Property Type: {prop_data['type']}")
            if prop_data.get('submarket'):
                context_parts.append(f"Submarket: {prop_data['submarket']}")

            if context_parts:
                property_context = "\n".join(context_parts)
                current_text = match.get("text", "")
                if property_context not in current_text:
                    match["text"] = f"{current_text}\n\n--- Property Context ---\n{property_context}"
                    # Also add to metadata for easy access
                    match["metadata"]["propertyName"] = prop_data.get('name', '')
                    match["metadata"]["propertyClass"] = prop_data.get('class', '')
                    match["metadata"]["propertyType"] = prop_data.get('type', '')
                    match["metadata"]["propertyCity"] = prop_data.get('city', '')
                    match["metadata"]["propertyState"] = prop_data.get('state', '')
                    enriched_count += 1

        LOGGER.info(f"[ENRICHMENT] Enriched {enriched_count} matches with Property context")

    except Exception as e:
        LOGGER.warning(f"[ENRICHMENT] Failed to enrich matches: {e}")

    return matches


def _merge_graph_and_vector_results(
    vector_matches: List[Dict[str, Any]],
    graph_result: Dict[str, Any],
    supplemental_property_ids: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Merge graph traversal results with vector search results.

    Graph results are used to:
    1. Boost relevance of records that are connected via relationships
    2. ADD new records discovered via graph traversal that weren't in vector results

    **Requirements: 7.3**

    Args:
        vector_matches: Results from vector search
        graph_result: Result from graph retriever with matchingNodeIds and paths

    Returns:
        Merged and re-ranked list of matches
    """
    if not graph_result:
        return vector_matches

    matching_node_ids = set(graph_result.get("matchingNodeIds", []))
    paths = graph_result.get("paths", [])

    # Build a map of node ID to SHORTEST path for quick lookup
    # This ensures directly-connected nodes get priority over multi-hop paths
    node_to_path: Dict[str, List[Dict[str, Any]]] = {}
    for path in paths:
        if path.get("nodes"):
            end_node = path["nodes"][-1] if path["nodes"] else None
            if end_node:
                # Keep the shortest path to each node
                new_path_len = len(path["nodes"])
                existing_path = node_to_path.get(end_node)
                if existing_path is None or new_path_len < len(existing_path.get("nodes", [])):
                    node_to_path[end_node] = path

    # Track which graph nodes are already in vector results
    vector_record_ids = set()
    for match in vector_matches:
        record_id = match.get("metadata", {}).get("recordId", "")
        if record_id:
            vector_record_ids.add(record_id)

    # Process vector matches and boost graph-connected results
    merged_matches = []
    graph_boost = 0.15  # Boost score for graph-connected results

    # Pre-fetch parent Property info for Availability records
    # This enriches Availability results with their parent Property's location
    graph_nodes_table = None
    parent_location_cache: Dict[str, Dict[str, str]] = {}
    try:
        graph_nodes_table = boto3.resource('dynamodb').Table(
            os.environ.get('GRAPH_NODES_TABLE', 'salesforce-ai-search-graph-nodes')
        )
    except Exception as e:
        LOGGER.debug(f"Could not initialize graph nodes table: {e}")

    for match in vector_matches:
        metadata = match.get("metadata", {})
        record_id = metadata.get("recordId", "")
        sobject = metadata.get("sobject", "")

        # Check if this record was found via graph traversal
        is_graph_match = record_id in matching_node_ids

        if is_graph_match:
            # Boost the score and add relationship path
            boosted_score = min(1.0, match.get("score", 0) + graph_boost)
            match["score"] = boosted_score
            match["graphMatch"] = True

            # Add relationship path if available
            if record_id in node_to_path:
                path_info = node_to_path[record_id]
                match["relationshipPath"] = path_info.get("nodes", [])
                match["relationshipEdges"] = path_info.get("edges", [])

        # Enrich Availability/Lease records with parent Property location
        # This helps LLM answer location-based queries about spaces/leases
        if sobject in ('ascendix__Availability__c', 'ascendix__Lease__c'):
            parent_ids = metadata.get("parentIds", [])
            # Find the Property parent (starts with 'a0a' for ascendix__Property__c)
            property_parent_id = None
            for pid in parent_ids:
                if pid.startswith('a0a'):  # Property ID prefix
                    property_parent_id = pid
                    break

            if property_parent_id and property_parent_id not in parent_location_cache:
                try:
                    # Fetch parent Property chunk from S3 to get location
                    s3_client = boto3.client('s3')
                    data_bucket = os.environ.get('DATA_BUCKET', 'salesforce-ai-search-data-382211616288-us-west-2')
                    chunk_key = f"chunks/ascendix__Property__c/{property_parent_id}/chunk-0.txt"

                    chunk_response = s3_client.get_object(Bucket=data_bucket, Key=chunk_key)
                    chunk_text = chunk_response['Body'].read().decode('utf-8')

                    # Parse City and State from chunk text
                    loc_data = {'name': '', 'city': '', 'state': ''}
                    for line in chunk_text.split('\n'):
                        if line.startswith('# '):
                            loc_data['name'] = line[2:].strip()
                        elif line.startswith('Name:'):
                            loc_data['name'] = line.split(':', 1)[1].strip()
                        elif line.startswith('City:'):
                            loc_data['city'] = line.split(':', 1)[1].strip()
                        elif line.startswith('State:'):
                            loc_data['state'] = line.split(':', 1)[1].strip()

                    parent_location_cache[property_parent_id] = loc_data
                    LOGGER.debug(f"Fetched Property location for {property_parent_id}: {loc_data}")
                except Exception as e:
                    LOGGER.debug(f"Could not fetch Property location for {property_parent_id}: {e}")
                    parent_location_cache[property_parent_id] = {}

            # Add parent Property location to the result text
            if property_parent_id and property_parent_id in parent_location_cache:
                loc = parent_location_cache[property_parent_id]
                if loc.get('name') or loc.get('city'):
                    location_parts = []
                    if loc.get('name'):
                        location_parts.append(loc['name'])
                    if loc.get('city'):
                        location_parts.append(loc['city'])
                    if loc.get('state'):
                        location_parts.append(loc['state'])
                    location_str = ", ".join(location_parts)
                    # Append location context to the match text
                    current_text = match.get("text", "")
                    if location_str and location_str not in current_text:
                        match["text"] = f"{current_text}\n\nPROPERTY LOCATION: {location_str}"
                        match["propertyLocation"] = location_str

        merged_matches.append(match)

    # ADD graph-discovered nodes that weren't in vector results
    # These are records found via relationship traversal
    graph_only_nodes = matching_node_ids - vector_record_ids
    added_from_graph = 0

    LOGGER.info(f"Graph-only nodes to add: {len(graph_only_nodes)}")

    if graph_only_nodes:
        # Fetch metadata for graph-only nodes from DynamoDB
        try:
            graph_nodes_table = boto3.resource('dynamodb').Table(
                os.environ.get('GRAPH_NODES_TABLE', 'salesforce-ai-search-graph-nodes')
            )
            s3_client = boto3.client('s3')
            data_bucket = os.environ.get('DATA_BUCKET', 'salesforce-ai-search-data-382211616288-us-west-2')

            # Build a cache of node ID to display name for path resolution
            # Include all path nodes and seed nodes for lookup
            node_name_cache: Dict[str, str] = {}
            all_path_node_ids = set()
            for path_info in node_to_path.values():
                all_path_node_ids.update(path_info.get("nodes", []))

            # Batch fetch display names for path nodes
            for path_node_id in all_path_node_ids:
                try:
                    resp = graph_nodes_table.get_item(
                        Key={'nodeId': path_node_id},
                        ProjectionExpression='nodeId, displayName, #t',
                        ExpressionAttributeNames={'#t': 'type'}
                    )
                    if 'Item' in resp:
                        item = resp['Item']
                        node_name_cache[path_node_id] = item.get('displayName', path_node_id)
                except Exception:
                    node_name_cache[path_node_id] = path_node_id

            # Find nodes directly connected to Property-type seeds
            # This is more reliable than path-based sorting when DFS visits via other routes
            edges_table = boto3.resource('dynamodb').Table(
                os.environ.get('GRAPH_EDGES_TABLE', 'salesforce-ai-search-graph-edges')
            )
            property_seed_ids = [rid for rid in vector_record_ids if rid.startswith('a0a')]  # Property prefix
            # Include supplemental properties from decomposition
            if supplemental_property_ids:
                for prop_id in supplemental_property_ids:
                    if prop_id not in property_seed_ids:
                        property_seed_ids.append(prop_id)
            directly_connected_deals = set()

            for prop_id in property_seed_ids[:10]:  # Check top 10 Property seeds (increased for supplemental)
                try:
                    edge_response = edges_table.query(
                        KeyConditionExpression=Key('fromId').eq(prop_id),
                        FilterExpression=Attr('type').eq('ascendix__Deal__c'),
                        Limit=20
                    )
                    for edge in edge_response.get('Items', []):
                        deal_id = edge.get('toId')
                        if deal_id:
                            directly_connected_deals.add(deal_id)
                except Exception as e:
                    LOGGER.debug(f"Error querying edges for {prop_id}: {e}")

            LOGGER.info(f"Found {len(directly_connected_deals)} deals directly connected to Property seeds")

            # Prioritize: 1) directly connected to Property, 2) path depth, 3) Deal type
            def node_sort_key(node_id):
                # First priority: directly connected to a Property seed
                is_direct = 0 if node_id in directly_connected_deals else 1

                # Second: path depth
                path_info = node_to_path.get(node_id, {})
                path_nodes = path_info.get("nodes", [])
                path_depth = len(path_nodes) if path_nodes else 99

                # Third: Deal types
                is_deal = 0 if node_id.startswith('a0P') else 1

                return (is_direct, path_depth, is_deal, node_id)

            sorted_nodes = sorted(list(graph_only_nodes), key=node_sort_key)
            direct_in_top5 = sum(1 for n in sorted_nodes[:5] if n in directly_connected_deals)
            LOGGER.info(f"Graph-only sorting: {len(graph_only_nodes)} nodes, {direct_in_top5}/5 top are direct")

            # Limit to top N graph-discovered nodes to avoid overwhelming results
            max_graph_additions = 15  # Increased to get more deals
            for node_id in sorted_nodes[:max_graph_additions]:
                try:
                    response = graph_nodes_table.get_item(Key={'nodeId': node_id})
                    if 'Item' in response:
                        node = response['Item']
                        node_type = node.get('type', '')
                        display_name = node.get('displayName', node_id)
                        attributes = node.get('attributes', {})

                        # Build rich text from node attributes
                        text_parts = [f"Record: {display_name}"]
                        text_parts.append(f"Type: {node_type}")

                        # Add attributes to text
                        for attr_key, attr_val in attributes.items():
                            if attr_val and attr_key != 'Name':
                                text_parts.append(f"{attr_key}: {attr_val}")

                        # Try to fetch actual chunk content from S3
                        try:
                            chunk_key = f"chunks/{node_type}/{node_id}/chunk-0.txt"
                            chunk_response = s3_client.get_object(Bucket=data_bucket, Key=chunk_key)
                            chunk_text = chunk_response['Body'].read().decode('utf-8')
                            if chunk_text:
                                text_parts = [chunk_text]  # Use actual chunk content
                                LOGGER.info(f"Fetched S3 chunk for {node_id}: {len(chunk_text)} chars")
                        except Exception as s3_err:
                            LOGGER.debug(f"S3 chunk not found for {node_id}: {s3_err}")

                        # Build relationship context with DISPLAY NAMES (not IDs)
                        if node_id in node_to_path:
                            path_info = node_to_path[node_id]
                            path_nodes = path_info.get("nodes", [])
                            if len(path_nodes) > 1:
                                # Resolve node IDs to display names
                                path_names = [node_name_cache.get(nid, nid) for nid in path_nodes[:3]]
                                text_parts.append(f"Relationship Path: {' → '.join(path_names)}")

                                # Add explicit property association for deals
                                if node_type == 'ascendix__Deal__c' and len(path_nodes) >= 1:
                                    start_node_id = path_nodes[0]
                                    start_node_name = node_name_cache.get(start_node_id, start_node_id)
                                    text_parts.append(f"ASSOCIATED WITH PROPERTY: {start_node_name}")

                        # Create a match entry for this graph-discovered node
                        graph_match = {
                            "text": "\n".join(text_parts),
                            "score": 0.75,  # Base score for graph-discovered results
                            "metadata": {
                                "recordId": node_id,
                                "sobject": node_type,
                                "name": display_name,
                                "sharingBuckets": node.get('sharingBuckets', []),
                                "graphDiscovered": True,
                            },
                            "graphMatch": True,
                            "graphDiscovered": True,
                        }

                        # Add relationship path if available
                        if node_id in node_to_path:
                            path_info = node_to_path[node_id]
                            graph_match["relationshipPath"] = path_info.get("nodes", [])
                            graph_match["relationshipEdges"] = path_info.get("edges", [])

                        merged_matches.append(graph_match)
                        added_from_graph += 1
                except Exception as e:
                    LOGGER.warning(f"Error fetching graph node {node_id}: {e}")

        except Exception as e:
            LOGGER.warning(f"Error adding graph-discovered nodes: {e}")

    # Sort by score descending (graph-boosted results will rank higher)
    merged_matches.sort(key=lambda x: x.get("score", 0), reverse=True)

    LOGGER.info(f"Graph merge: {len(matching_node_ids)} graph nodes, "
               f"{sum(1 for m in merged_matches if m.get('graphMatch'))} boosted matches, "
               f"{added_from_graph} added from graph")

    return merged_matches


def _filter_low_relevance(
    matches: List[Dict[str, Any]],
    min_score: float = MIN_RELEVANCE_SCORE,
    has_metadata_filter: bool = False
) -> List[Dict[str, Any]]:
    """Filter out results with relevance scores below the threshold.

    This helps return meaningful "no results" for queries that don't match
    any content (e.g., "properties in Antarctica" should return nothing).

    When has_metadata_filter=True, uses a lower threshold since the metadata
    filter already guarantees type relevance.
    """
    if not matches:
        return matches

    # Use lower threshold when metadata filters are applied
    # The metadata filter (e.g., sobject=Deal) already ensures type relevance
    # **Task 26**: Increased from 0.6 to 0.7 to be more conservative (QA feedback)
    effective_threshold = min_score * 0.7 if has_metadata_filter else min_score

    # Log score distribution for debugging
    scores = [m.get("score", 0) for m in matches]
    if scores:
        LOGGER.info(
            f"Relevance scores: min={min(scores):.3f}, max={max(scores):.3f}, "
            f"threshold={effective_threshold:.3f}, has_metadata_filter={has_metadata_filter}"
        )

    filtered = [m for m in matches if m.get("score", 0) >= effective_threshold]

    if len(filtered) < len(matches):
        LOGGER.info(f"Relevance filter: removed {len(matches) - len(filtered)} low-score results (threshold={effective_threshold:.3f})")

    return filtered


def _post_filter_matches(matches: List[Dict[str, Any]], authz_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Post-filter matches to validate authorization and apply FLS redaction."""
    user_sharing_buckets = set(authz_context.get("sharingBuckets", []))
    user_fls_tags = set(authz_context.get("flsProfileTags", []))
    
    filtered_matches = []
    
    for match in matches:
        metadata = match.get("metadata", {})
        
        # Check sharing bucket authorization
        chunk_sharing_buckets = metadata.get("sharingBuckets", [])
        if isinstance(chunk_sharing_buckets, str):
            chunk_sharing_buckets = [chunk_sharing_buckets]
        
        # User must have at least one matching sharing bucket
        has_sharing_access = False

        # Admin bypass: admin:all_access grants access to all records (relaxed mode)
        if 'admin:all_access' in user_sharing_buckets:
            has_sharing_access = True
        elif not chunk_sharing_buckets:
            # If no sharing buckets specified, allow access (public data)
            has_sharing_access = True
        else:
            chunk_buckets_set = set(chunk_sharing_buckets)
            has_sharing_access = bool(user_sharing_buckets & chunk_buckets_set)
        
        if not has_sharing_access:
            # User doesn't have access to this record
            LOGGER.debug(f"Access denied for record {metadata.get('recordId')} (sobject: {metadata.get('sobject')}). "
                         f"User buckets: {user_sharing_buckets}, Chunk buckets: {chunk_sharing_buckets}")
            continue
        
        # Check FLS authorization
        chunk_fls_tags = metadata.get("flsProfileTags", [])
        if isinstance(chunk_fls_tags, str):
            chunk_fls_tags = [chunk_fls_tags]
        
        # Determine if redaction is needed
        needs_redaction = False
        if chunk_fls_tags:
            chunk_fls_set = set(chunk_fls_tags)
            # If user doesn't have all required FLS tags, redaction may be needed
            if not chunk_fls_set.issubset(user_fls_tags):
                needs_redaction = True
        
        # Apply redaction if needed
        if needs_redaction:
            # Check if a redacted variant exists
            has_pii = metadata.get("hasPII", False)
            if has_pii:
                # Use redacted text if available, otherwise skip this match
                redacted_text = metadata.get("redactedText")
                if redacted_text:
                    match["text"] = redacted_text
                    match["redacted"] = True
                else:
                    # No redacted variant available, skip this match
                    continue
        
        filtered_matches.append(match)
    
    return filtered_matches


def _build_query_plan(request_payload: Dict[str, Any], metadata_filters: List[Dict[str, Any]], authz_context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "query": request_payload["query"],
        "topK": request_payload["topK"],
        "hybrid": {
            "enabled": request_payload["hybrid"],
            "weights": {
                "dense": 0.6,
                "sparse": 0.4,
            },
        },
        "authzMode": request_payload["authzMode"],
        "recordContext": request_payload["recordContext"],
        "filters": metadata_filters,
        "authzContext": {
            "salesforceUserId": authz_context.get(
                "salesforceUserId", request_payload["salesforceUserId"]
            ),
            "sharingBuckets": authz_context.get("sharingBuckets", []),
            "flsProfileTags": authz_context.get("flsProfileTags", []),
            "cached": authz_context.get("cached", False),
        },
    }


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles Decimal types from DynamoDB and dataclasses."""
    def default(self, obj):
        from decimal import Decimal
        if isinstance(obj, Decimal):
            return float(obj)
        # Handle dataclass instances (e.g., GeoExpansion, SizeRange, PercentageValue)
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        return super().default(obj)


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def lambda_handler(event, context):
    start = time.perf_counter()
    request_id = str(uuid.uuid4())
    
    # Extract request ID from context if available
    if context and hasattr(context, "aws_request_id"):
        request_id = context.aws_request_id
    
    try:
        request_payload = _parse_request(event)

        # Initialize authz context (will be populated later, possibly twice: during cross-object handling and main flow)
        authz_context = None

        # Phase 3: Query Intent Classification
        intent_classification = None
        intent_routing = None
        intent_ms = 0

        if INTENT_ROUTER_AVAILABLE and INTENT_ROUTING_ENABLED:
            intent_start = time.perf_counter()
            try:
                # Create router with feature flags
                router = QueryIntentRouter(feature_flags={
                    'graph_routing_enabled': GRAPH_ROUTING_ENABLED,
                    'intent_logging_enabled': INTENT_LOGGING_ENABLED,
                })

                # Classify the query
                intent_classification = router.classify(request_payload["query"])
                intent_routing = router.route(request_payload["query"], intent_classification)

                LOGGER.info(f"Intent Classification: intent={intent_classification.intent.value}, "
                           f"confidence={intent_classification.confidence}, "
                           f"routing={intent_routing.get('retriever')}")

                # Log classification to DynamoDB (async)
                if INTENT_LOGGING_ENABLED:
                    router.log_classification(
                        query=request_payload["query"],
                        classification=intent_classification,
                        user_id=request_payload["salesforceUserId"],
                        request_id=request_id
                    )
            except Exception as e:
                LOGGER.warning(f"Intent classification failed (continuing with vector search): {e}")

            intent_ms = round((time.perf_counter() - intent_start) * 1000, 2)

        # LLM-based Query Decomposition (experimental)
        query_decomposition = None
        decomposition_ms = 0

        if QUERY_DECOMPOSER_AVAILABLE and QUERY_DECOMPOSER_ENABLED:
            decomposition_start = time.perf_counter()
            try:
                query_decomposition = decompose_query(request_payload["query"])

                if "error" not in query_decomposition:
                    LOGGER.info(f"Query Decomposition: target={query_decomposition.get('target_entity')}, "
                               f"needs_traversal={query_decomposition.get('needs_traversal')}, "
                               f"paths={query_decomposition.get('traversal_paths')}, "
                               f"latency={query_decomposition.get('latency_ms')}ms")

                    # If decomposition says we need traversal, ensure graph routing is enabled
                    if query_decomposition.get('needs_traversal') and intent_routing:
                        intent_routing['parameters']['useGraphTraversal'] = True
                        LOGGER.info("Decomposition triggered graph traversal")
                else:
                    LOGGER.warning(f"Query decomposition error: {query_decomposition.get('error')}")

            except Exception as e:
                LOGGER.warning(f"Query decomposition failed: {e}")

            decomposition_ms = round((time.perf_counter() - decomposition_start) * 1000, 2)

        # Schema-Aware Decomposition for zero-config filtering
        # **Feature: zero-config-schema-discovery**
        # **Requirements: 3.1, 3.2, 3.3, 3.4, 3.7, 4.1, 4.4, 4.5, 9.1, 9.2, 9.5**
        schema_decomposition = None
        schema_decomposition_ms = 0
        graph_filter_result = None
        graph_filter_ms = 0
        graph_filter_candidate_ids = None
        cross_object_result = None
        cross_object_ms = 0
        cross_query = None  # Initialize cross_query to avoid UnboundLocalError

        if SCHEMA_DECOMPOSER_AVAILABLE and SCHEMA_FILTER_ENABLED:
            schema_decomp_start = time.perf_counter()
            try:
                # Task 29.6: Use module-level schema_cache singleton for caching
                schema_cache = get_schema_cache() if SCHEMA_CACHE_AVAILABLE and get_schema_cache else None
                schema_decomposer = SchemaAwareDecomposer(schema_cache=schema_cache)
                schema_decomposition = schema_decomposer.decompose(request_payload["query"])

                LOGGER.info(
                    f"Schema decomposition: entity={schema_decomposition.target_entity}, "
                    f"filters={schema_decomposition.filters}, "
                    f"numeric_filters={schema_decomposition.numeric_filters}, "
                    f"confidence={schema_decomposition.confidence}, "
                    f"needs_cross_object={schema_decomposition.needs_cross_object_traversal}"
                )

                # Cross-Object Query Handling
                # **Requirements: 9.1, 9.2, 9.5**
                cross_object_result = None
                cross_object_ms = 0

                # Get authz context early for cross-object query handling
                # (also used later in the function)
                authz_context = _invoke_authz_sidecar(request_payload["salesforceUserId"])
                LOGGER.info(f"AuthZ Context for cross-object query: {json.dumps(authz_context)}")

                if CROSS_OBJECT_HANDLER_AVAILABLE and (
                    schema_decomposition.needs_cross_object_traversal or
                    schema_decomposition.traversals
                ):
                    cross_object_start = time.perf_counter()
                    try:
                        cross_handler = get_cross_object_handler()
                        
                        # Try to detect cross-object query from filters
                        cross_query = cross_handler.detect_cross_object_query(
                            target_entity=schema_decomposition.target_entity,
                            filters=schema_decomposition.filters,
                            numeric_filters=schema_decomposition.numeric_filters,
                        )
                        
                        # If not detected from filters, check traversals from LLM
                        if not cross_query and schema_decomposition.traversals:
                            for traversal in schema_decomposition.traversals:
                                filter_entity = traversal.get("to")
                                traversal_filters = traversal.get("filters", {})
                                if filter_entity and traversal_filters:
                                    cross_query = CrossObjectQuery(
                                        target_entity=schema_decomposition.target_entity,
                                        filter_entity=filter_entity,
                                        filters=traversal_filters,
                                        traversal_path=[schema_decomposition.target_entity, filter_entity],
                                        confidence=schema_decomposition.confidence,
                                    )
                                    break
                        
                        if cross_query:
                            LOGGER.info(
                                f"Cross-object query detected: target={cross_query.target_entity}, "
                                f"filter_entity={cross_query.filter_entity}, "
                                f"filters={cross_query.filters}"
                            )

                            # Execute cross-object query with timeout (Task 29.6)
                            # Graph traversal can be slow - timeout and fallback to semantic search
                            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
                            user_sharing_buckets = set(authz_context.get('sharingBuckets', []))

                            cross_object_executor = ThreadPoolExecutor(max_workers=1)
                            try:
                                cross_future = cross_object_executor.submit(
                                    cross_handler.execute_cross_object_query,
                                    cross_query,
                                    user_sharing_buckets,
                                )
                                try:
                                    cross_object_ids = cross_future.result(
                                        timeout=CROSS_OBJECT_TIMEOUT_MS / 1000.0
                                    )

                                    if cross_object_ids:
                                        cross_object_result = {
                                            "matchingIds": cross_object_ids,
                                            "crossQuery": cross_query.to_dict(),
                                        }
                                        # Use cross-object IDs as graph filter candidates
                                        graph_filter_candidate_ids = cross_object_ids
                                        LOGGER.info(
                                            f"Cross-object query returned {len(cross_object_ids)} "
                                            f"{cross_query.target_entity} records"
                                        )
                                    else:
                                        LOGGER.info("Cross-object query returned no results")
                                except FuturesTimeoutError:
                                    elapsed_ms = (time.perf_counter() - cross_object_start) * 1000
                                    LOGGER.warning(
                                        f"[CROSS_OBJECT_TIMEOUT] Graph traversal timed out after "
                                        f"{elapsed_ms:.0f}ms (budget={CROSS_OBJECT_TIMEOUT_MS}ms), "
                                        f"continuing to disambiguation"
                                    )
                                    # Mark cross_query as None so we don't trigger fallback mode
                                    # For timeouts, we still want to try disambiguation
                                    cross_query = None
                            finally:
                                cross_object_executor.shutdown(wait=False)
                    
                    except Exception as e:
                        LOGGER.warning(f"Cross-object query handling failed: {e}")
                    
                    cross_object_ms = round((time.perf_counter() - cross_object_start) * 1000, 2)

                # Apply graph attribute filtering if we have filters
                # **Requirements: 4.1, 4.4, 4.5**
                if GRAPH_FILTER_AVAILABLE and graph_filter_candidate_ids is None and (
                    schema_decomposition.filters or schema_decomposition.numeric_filters
                ):
                    graph_filter_start = time.perf_counter()
                    try:
                        graph_filter = GraphAttributeFilter()
                        graph_filter_candidate_ids = graph_filter.query_by_attributes(
                            object_type=schema_decomposition.target_entity,
                            filters=schema_decomposition.filters,
                            numeric_filters=schema_decomposition.numeric_filters,
                        )

                        LOGGER.info(
                            f"Graph filter: {len(graph_filter_candidate_ids)} candidates "
                            f"for {schema_decomposition.target_entity}"
                        )

                        # **Requirement 4.5**: Return empty results when no graph matches
                        # BUT: Fall back to semantic search if cross-object also failed
                        # (indicates possible metadata indexing gap)
                        if not graph_filter_candidate_ids:
                            # Check if cross-object query was attempted and also returned no results
                            cross_object_also_failed = (
                                cross_query is not None and
                                cross_object_result is None
                            )

                            # Check if this is an aggregation query that should bypass short-circuit
                            query_lower = request_payload["query"].lower()
                            is_aggregation = any(kw in query_lower for kw in AGGREGATION_KEYWORDS)

                            if cross_object_also_failed:
                                # Both cross-object and graph filter failed - likely metadata issue
                                # Fall back to pure semantic search
                                LOGGER.warning(
                                    "Both cross-object and graph filter returned zero matches - "
                                    "falling back to pure semantic search (possible metadata indexing gap)"
                                )
                                graph_filter_candidate_ids = None  # Allow semantic search to proceed
                            elif is_aggregation:
                                # Aggregation queries should bypass short-circuit and use derived views
                                LOGGER.info(
                                    f"Graph filter returned zero matches, but aggregation query detected - "
                                    f"bypassing short-circuit for derived view routing"
                                )
                                graph_filter_candidate_ids = None  # Allow aggregation routing to proceed
                            else:
                                LOGGER.info(
                                    "Graph filter returned zero matches, short-circuiting to empty result"
                                )
                                # Return empty result without executing vector search
                                trace = {
                                    "intentMs": intent_ms,
                                    "decompositionMs": decomposition_ms,
                                    "schemaDecompositionMs": round(
                                        (time.perf_counter() - schema_decomp_start) * 1000, 2
                                    ),
                                    "graphFilterMs": round(
                                        (time.perf_counter() - graph_filter_start) * 1000, 2
                                    ),
                                    "graphFilterShortCircuit": True,
                                    "totalMs": round((time.perf_counter() - start) * 1000, 2),
                                    "cached": False,
                                    "preFilterCount": 0,
                                    "postFilterCount": 0,
                                }
                                response_body = {
                                    "matches": [],
                                    "queryPlan": {
                                        "query": request_payload["query"],
                                        "schemaDecomposition": schema_decomposition.to_dict(),
                                        "graphFilterShortCircuit": True,
                                    },
                                    "trace": trace,
                                    "requestId": request_id,
                                }
                                return _response(200, response_body)

                    except Exception as e:
                        LOGGER.warning(f"Graph filter failed (continuing without): {e}")
                        graph_filter_candidate_ids = None

                    graph_filter_ms = round(
                        (time.perf_counter() - graph_filter_start) * 1000, 2
                    )

            except Exception as e:
                LOGGER.warning(f"Schema decomposition failed: {e}")

            schema_decomposition_ms = round(
                (time.perf_counter() - schema_decomp_start) * 1000, 2
            )

        # =====================================================================
        # Canary Decision - Made EARLY to affect disambiguation path
        # **Task: 28.2 - Phase 1 Canary Deployment**
        # =====================================================================
        # Determine if this request should use planner results or shadow mode
        # When PLANNER_TRAFFIC_PERCENT > 0, that percentage uses planner results
        use_planner_for_request = False
        canary_roll = 0
        if PLANNER_TRAFFIC_PERCENT > 0:
            canary_roll = random.randint(1, 100)
            use_planner_for_request = canary_roll <= PLANNER_TRAFFIC_PERCENT
        # If not in shadow mode at all, always use planner
        if not PLANNER_SHADOW_MODE:
            use_planner_for_request = True

        if use_planner_for_request:
            LOGGER.info(f"Canary: enabled (roll={canary_roll}, traffic_pct={PLANNER_TRAFFIC_PERCENT})")

        # Track planner result from disambiguation path (to avoid running twice)
        early_planner_result = None
        early_planner_ran = False

        # Disambiguation Check
        # **Requirements: 11.1, 11.2, 11.3, 11.4**
        # Skip disambiguation if cross-object query was attempted but returned no results
        # (this indicates metadata indexing gap, should fall back to semantic search)
        cross_object_fallback_mode = (cross_query is not None and cross_object_result is None)
        if cross_object_fallback_mode:
            LOGGER.info("Skipping disambiguation - cross-object query returned no results, falling back to semantic search")

        # Skip disambiguation if cross-object query succeeded with results
        # The graph traversal provides high-confidence filtering, so we should proceed with results
        cross_object_success = (cross_object_result is not None and len(cross_object_result.get("matchingIds", [])) > 0)
        if cross_object_success:
            LOGGER.info(f"Skipping disambiguation - cross-object query succeeded with {len(cross_object_result.get('matchingIds', []))} results")

        disambiguation_result = None
        disambiguation_ms = 0

        # Early aggregation query detection - skip disambiguation for aggregation queries
        # This allows vacancy/lease/activity queries to route to derived views directly
        def _is_aggregation_query_early(query: str) -> bool:
            """Detect if query is an aggregation query that should skip disambiguation."""
            query_lower = query.lower()
            for keyword in AGGREGATION_KEYWORDS:
                if keyword in query_lower:
                    return True
            return False

        skip_disambiguation_for_aggregation = (
            AGGREGATION_ROUTING_ENABLED
            and DERIVED_VIEW_MANAGER_AVAILABLE
            and _is_aggregation_query_early(request_payload["query"])
        )
        if skip_disambiguation_for_aggregation:
            LOGGER.info(f"[AGGREGATION] Skipping disambiguation for aggregation query: '{request_payload['query'][:50]}'")

        if DISAMBIGUATION_AVAILABLE and DISAMBIGUATION_ENABLED and schema_decomposition and not cross_object_fallback_mode and not skip_disambiguation_for_aggregation and not cross_object_success:
            disambiguation_start = time.perf_counter()
            try:
                disambiguator = get_disambiguation_handler()
                
                # Check for clarification in request (user responding to disambiguation)
                clarification = request_payload.get("clarification")
                if clarification:
                    # User is responding to a disambiguation request
                    # **Requirements: 11.3**
                    selected_entity = clarification.get("selectedEntity")
                    if selected_entity:
                        LOGGER.info(f"Disambiguation clarification received: {selected_entity}")
                        # Override the target entity with user's selection
                        schema_decomposition.target_entity = selected_entity
                        schema_decomposition.confidence = 1.0  # User confirmed
                        disambiguation_result = {
                            "clarificationApplied": True,
                            "selectedEntity": selected_entity,
                        }
                else:
                    # Check if disambiguation is needed
                    # Detect ambiguous terms in query
                    ambiguous_terms = disambiguator.detect_ambiguous_terms(
                        request_payload["query"]
                    )
                    
                    # Get candidate entities if ambiguous
                    entity_scores = None
                    if ambiguous_terms:
                        entity_scores = disambiguator.get_candidate_entities(
                            request_payload["query"],
                            ambiguous_terms,
                        )
                    
                    # Check if we should ask for disambiguation
                    needs_disambiguation = disambiguator.should_disambiguate(
                        confidence=schema_decomposition.confidence,
                        entity_scores=entity_scores,
                        ambiguous_terms_found=ambiguous_terms,
                    )
                    
                    if needs_disambiguation:
                        # Build disambiguation request
                        # **Requirements: 11.1, 11.2**
                        candidates = entity_scores or disambiguator.get_candidate_entities(
                            request_payload["query"],
                            ambiguous_terms,
                        )
                        
                        if candidates:
                            disambiguation_request = disambiguator.build_disambiguation_request(
                                query=request_payload["query"],
                                candidates=candidates,
                                ambiguous_terms=ambiguous_terms,
                            )
                            
                            LOGGER.info(
                                f"Disambiguation needed: confidence={schema_decomposition.confidence}, "
                                f"ambiguous_terms={ambiguous_terms}, "
                                f"options={len(disambiguation_request.options)}"
                            )
                            
                            # Return disambiguation request instead of results
                            disambiguation_ms = round(
                                (time.perf_counter() - disambiguation_start) * 1000, 2
                            )
                            
                            trace = {
                                "intentMs": intent_ms,
                                "decompositionMs": decomposition_ms,
                                "schemaDecompositionMs": schema_decomposition_ms,
                                "disambiguationMs": disambiguation_ms,
                                "totalMs": round((time.perf_counter() - start) * 1000, 2),
                                "cached": False,
                            }
                            
                            # **Task: 28.1 - Shadow Logging for Canary Deployment**
                            # **Task: 28.2 - Canary Mode: Optionally bypass disambiguation when planner is confident**
                            # Run planner to determine if we should:
                            # 1. Shadow only: Log results and return disambiguation (no behavior change)
                            # 2. Canary: If planner confident, BYPASS disambiguation and use structured retrieval
                            planner_data = None
                            bypass_disambiguation = False

                            if PLANNER_AVAILABLE:
                                try:
                                    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

                                    planner_start = time.perf_counter()
                                    query_hash = hashlib.sha256(request_payload["query"].encode()).hexdigest()[:12]
                                    # Initialize vocab_cache for entity linking
                                    vocab_cache = get_vocab_cache() if VOCAB_CACHE_AVAILABLE and get_vocab_cache else None
                                    # Initialize schema_cache for field relevance scoring (Task 42)
                                    schema_cache = get_schema_cache() if SCHEMA_CACHE_AVAILABLE and get_schema_cache else None
                                    planner = Planner(vocab_cache=vocab_cache, schema_cache=schema_cache, timeout_ms=PLANNER_TIMEOUT_MS)

                                    # Task 29.6: Use explicit executor management with shutdown(wait=False)
                                    # to avoid blocking on context manager exit after timeout
                                    planner_executor = ThreadPoolExecutor(max_workers=1)
                                    try:
                                        future = planner_executor.submit(
                                            planner.plan,
                                            request_payload["query"],
                                            PLANNER_TIMEOUT_MS,
                                        )
                                        try:
                                            planner_result = future.result(timeout=PLANNER_TIMEOUT_MS / 1000.0)
                                            would_use_planner = planner_result and planner_result.confidence >= PLANNER_MIN_CONFIDENCE

                                            if planner_result:
                                                is_canary = use_planner_for_request and PLANNER_SHADOW_MODE
                                                mode_label = "[CANARY]" if is_canary else "[SHADOW]"

                                                LOGGER.info(
                                                    f"{mode_label} Planner result (disambiguation path): query_hash={query_hash}, "
                                                    f"target={planner_result.target_object}, "
                                                    f"predicates={len(planner_result.predicates)}, "
                                                    f"confidence={planner_result.confidence:.2f}, "
                                                    f"would_use={would_use_planner}, "
                                                    f"time_ms={planner_result.planning_time_ms:.1f}"
                                                )

                                                if PLANNER_METRICS_AVAILABLE:
                                                    planner_metrics = get_planner_metrics()
                                                    if use_planner_for_request and would_use_planner:
                                                        # Canary: emit production metrics
                                                        planner_metrics.emit_plan_success(
                                                            latency_ms=planner_result.planning_time_ms,
                                                            confidence=planner_result.confidence,
                                                            predicate_count=len(planner_result.predicates),
                                                            target_object=planner_result.target_object or "unknown",
                                                        )
                                                    else:
                                                        # Shadow: emit shadow metrics
                                                        planner_metrics.emit_shadow_execution(
                                                            latency_ms=planner_result.planning_time_ms,
                                                            confidence=planner_result.confidence,
                                                            predicate_count=len(planner_result.predicates),
                                                            target_object=planner_result.target_object or "unknown",
                                                            would_use=would_use_planner,
                                                            query_hash=query_hash,
                                                        )

                                                # **Task: 28.2 Canary Decision**
                                                # If canary AND planner confident: bypass disambiguation, proceed with structured retrieval
                                                if use_planner_for_request and would_use_planner:
                                                    LOGGER.info(
                                                        f"[CANARY] Bypassing disambiguation - planner confident: "
                                                        f"confidence={planner_result.confidence:.2f}, target={planner_result.target_object}"
                                                    )
                                                    bypass_disambiguation = True
                                                    early_planner_result = planner_result
                                                    early_planner_ran = True
                                                    planner_data = {
                                                        "used": True,
                                                        "canary": True,
                                                        "canaryPercent": PLANNER_TRAFFIC_PERCENT,
                                                        "bypassedDisambiguation": True,
                                                        "targetObject": planner_result.target_object,
                                                        "predicates": [p.to_dict() for p in planner_result.predicates],
                                                        "confidence": planner_result.confidence,
                                                        "queryHash": query_hash,
                                                    }
                                                else:
                                                    # Shadow mode or planner not confident enough
                                                    planner_data = {
                                                        "shadowMode": not use_planner_for_request,
                                                        "wouldUse": would_use_planner,
                                                        "confidence": planner_result.confidence if planner_result else 0.0,
                                                        "queryHash": query_hash,
                                                    }
                                            else:
                                                planner_data = {
                                                    "shadowMode": True,
                                                    "wouldUse": False,
                                                    "confidence": 0.0,
                                                    "queryHash": query_hash,
                                                }
                                        except FuturesTimeoutError:
                                            mode_label = "[CANARY]" if use_planner_for_request else "[SHADOW]"
                                            LOGGER.info(f"{mode_label} Planner timeout (disambiguation path): query_hash={query_hash}")
                                            if PLANNER_METRICS_AVAILABLE:
                                                planner_metrics = get_planner_metrics()
                                                planner_metrics.emit_shadow_fallback("timeout")
                                            planner_data = {"shadowMode": True, "timeout": True, "queryHash": query_hash}
                                    finally:
                                        # Shutdown executor without waiting for background thread
                                        planner_executor.shutdown(wait=False)
                                except Exception as e:
                                    mode_label = "[CANARY]" if use_planner_for_request else "[SHADOW]"
                                    LOGGER.warning(f"{mode_label} Planner error (disambiguation path): {e}")
                                    if PLANNER_METRICS_AVAILABLE:
                                        try:
                                            planner_metrics = get_planner_metrics()
                                            planner_metrics.emit_shadow_fallback("error")
                                        except Exception:
                                            pass
                                    planner_data = {"error": str(e), "queryHash": query_hash if 'query_hash' in dir() else "unknown"}

                            # If canary bypassed disambiguation, don't return - continue to main retrieval path
                            if not bypass_disambiguation:
                                response_body = {
                                    "disambiguation": disambiguation_request.to_dict(),
                                    "queryPlan": {
                                        "query": request_payload["query"],
                                        "schemaDecomposition": schema_decomposition.to_dict(),
                                        "disambiguationTriggered": True,
                                        "planner": planner_data,
                                    },
                                    "trace": trace,
                                    "requestId": request_id,
                                }
                                return _response(200, response_body)
                
            except Exception as e:
                LOGGER.warning(f"Disambiguation check failed (continuing without): {e}")
            
            disambiguation_ms = round(
                (time.perf_counter() - disambiguation_start) * 1000, 2
            )

        # Get authorization context (if not already retrieved during schema decomposition)
        authz_start = time.perf_counter()
        if authz_context is None:
            authz_context = _invoke_authz_sidecar(request_payload["salesforceUserId"])
            LOGGER.info(f"AuthZ Context for user {request_payload['salesforceUserId']}: {json.dumps(authz_context)}")
        authz_ms = round((time.perf_counter() - authz_start) * 1000, 2)
        
        # Build metadata filters
        metadata_filters = _build_metadata_filters(request_payload["filters"], authz_context)

        # Detect intent and add sobject filter if not already specified
        # PRIORITY: schema_decomposition target_entity > intent detection
        detected_sobjects = None
        if not request_payload["filters"].get("sobject"):
            # Check if schema decomposition identified a target entity (e.g., cross-object query)
            if schema_decomposition and schema_decomposition.target_entity:
                detected_sobjects = [schema_decomposition.target_entity]
                LOGGER.info(f"Schema decomposition sobject filter applied: {detected_sobjects}")
            else:
                detected_sobjects = _detect_intent(request_payload["query"])
                if detected_sobjects:
                    LOGGER.info(f"Intent-based sobject filter applied: {detected_sobjects}")

            if detected_sobjects:
                if len(detected_sobjects) > 1:
                    metadata_filters.append({
                        "field": "sobject",  # Bedrock KB uses flat metadata, not nested
                        "operator": "IN",
                        "values": detected_sobjects,
                    })
                else:
                    metadata_filters.append({
                        "field": "sobject",  # Bedrock KB uses flat metadata, not nested
                        "operator": "EQ",
                        "value": detected_sobjects[0],
                    })

        # Detect temporal queries and add temporalStatus filter
        temporal_filter = _detect_temporal_filter(request_payload["query"])
        if temporal_filter:
            # Add the temporalStatus filter
            metadata_filters.append({
                "field": temporal_filter["field"],
                "operator": temporal_filter["operator"],
                "value": temporal_filter["value"],
            })
            # Also ensure we filter by the correct sobject if temporal filter specifies one
            temporal_sobject = temporal_filter.get("sobject")
            if temporal_sobject and not detected_sobjects:
                metadata_filters.append({
                    "field": "sobject",
                    "operator": "EQ",
                    "value": temporal_sobject,
                })
                LOGGER.info(f"Temporal filter added sobject constraint: {temporal_sobject}")

        # Detect ranking queries (e.g., "top 10 deals by gross fee amount")
        ranking_params = _detect_ranking_query(request_payload["query"])
        retrieval_top_k = request_payload["topK"]

        if ranking_params:
            # For ranking queries, retrieve more results to ensure we get high-value items
            # then sort and trim to the requested limit
            retrieval_top_k = max(50, ranking_params["limit"] * 5)
            LOGGER.info(f"Ranking query detected: retrieving {retrieval_top_k} results for post-ranking")

        # **Performance Optimization (Task 26)**: Reduce topK for simple/filtered queries
        # For simple queries with moderate confidence, fewer results are needed since they're targeted
        # This saves 100-300ms in KB query time
        if (
            intent_classification and
            intent_classification.confidence >= 0.5 and
            intent_classification.intent.value in {"SIMPLE_LOOKUP", "FIELD_FILTER"} and
            not ranking_params  # Don't reduce for ranking queries
        ):
            # Use smaller topK for targeted simple queries
            reduced_top_k = min(retrieval_top_k, 5)
            if reduced_top_k < retrieval_top_k:
                LOGGER.info(
                    f"Reducing topK for simple query: {retrieval_top_k} -> {reduced_top_k} "
                    f"(intent={intent_classification.intent.value}, confidence={intent_classification.confidence:.2f})"
                )
                retrieval_top_k = reduced_top_k

        query_plan = _build_query_plan(request_payload, metadata_filters, authz_context)
        if detected_sobjects:
            query_plan["intentDetection"] = {
                "detected": True,
                "sobjects": detected_sobjects,
            }
        if temporal_filter:
            query_plan["temporalFilter"] = {
                "detected": True,
                "status": temporal_filter["value"],
                "sobject": temporal_filter.get("sobject"),
            }
        if ranking_params:
            query_plan["ranking"] = ranking_params

        # Phase 3: Add intent classification to query plan
        if intent_classification:
            query_plan["intentClassification"] = {
                "intent": intent_classification.intent.value,
                "confidence": intent_classification.confidence,
                "patternsMatched": intent_classification.patterns_matched,
                "extractedEntities": intent_classification.extracted_entities,
                "routingHint": intent_classification.routing_hint,
            }
        if intent_routing:
            query_plan["intentRouting"] = intent_routing

        # Add query decomposition to query plan (for debugging/visibility)
        if query_decomposition and "error" not in query_decomposition:
            query_plan["queryDecomposition"] = {
                "targetEntity": query_decomposition.get("target_entity"),
                "targetFilters": query_decomposition.get("target_filters", {}),
                "relatedFilters": query_decomposition.get("related_filters", {}),
                "traversalPaths": query_decomposition.get("traversal_paths", []),
                "needsTraversal": query_decomposition.get("needs_traversal", False),
                "latencyMs": query_decomposition.get("latency_ms", 0),
            }

        # Add schema decomposition to query plan (zero-config schema discovery)
        if schema_decomposition:
            query_plan["schemaDecomposition"] = schema_decomposition.to_dict()
            if graph_filter_candidate_ids is not None:
                query_plan["graphFilterCandidates"] = len(graph_filter_candidate_ids)
        
        # Add cross-object query result to query plan
        # **Requirements: 9.1, 9.2, 9.5**
        if 'cross_object_result' in dir() and cross_object_result:
            query_plan["crossObjectQuery"] = {
                "detected": True,
                "targetEntity": cross_object_result["crossQuery"]["target_entity"],
                "filterEntity": cross_object_result["crossQuery"]["filter_entity"],
                "filters": cross_object_result["crossQuery"]["filters"],
                "matchingCount": len(cross_object_result["matchingIds"]),
            }
        
        # Add disambiguation result to query plan
        # **Requirements: 11.1, 11.2, 11.3, 11.4**
        if 'disambiguation_result' in dir() and disambiguation_result:
            query_plan["disambiguation"] = disambiguation_result

        # Check cache first
        cache_start = time.perf_counter()
        cached_result = _retrieval_cache.get(
            request_payload["query"],
            request_payload["filters"],
            request_payload["topK"],
            request_payload["salesforceUserId"]
        )
        cache_check_ms = round((time.perf_counter() - cache_start) * 1000, 2)
        
        if cached_result is not None:
            # Cache hit - return cached results
            emit_cache_metric('RetrievalCacheHit')
            LOGGER.info("Cache hit for query: %s", request_payload["query"][:50])
            
            trace = {
                "intentMs": intent_ms,
                "decompositionMs": decomposition_ms,
                "authzMs": authz_ms,
                "cacheCheckMs": cache_check_ms,
                "totalMs": round((time.perf_counter() - start) * 1000, 2),
                "cached": True,
                "postFilterCount": len(cached_result),
            }
            
            # Log telemetry to DynamoDB (async, non-blocking)
            _log_telemetry_async(
                request_id,
                request_payload,
                len(cached_result),
                trace,
                authz_context.get("cached", False)
            )
            
            response_body = {
                "matches": cached_result,
                "queryPlan": query_plan,
                "trace": trace,
                "requestId": request_id,
            }
            return _response(200, response_body)
        
        # Cache miss - query Bedrock Knowledge Base
        emit_cache_metric('RetrievalCacheMiss')
        LOGGER.info("Cache miss for query: %s", request_payload["query"][:50])

        # =====================================================================
        # Graph-Aware Zero-Config Planner - Speculative Parallel Execution
        # **Feature: graph-aware-zero-config-retrieval**
        # **Requirements: 1.1, 1.2, 1.3, 8.1**
        # =====================================================================
        # Note: use_planner_for_request is set earlier (before disambiguation check)
        # Note: early_planner_result/early_planner_ran track if planner already ran in disambiguation path
        planner_result = early_planner_result  # May be set from disambiguation path (Task 28.2)
        planner_ms = 0
        planner_used = early_planner_ran  # If already ran and was used in disambiguation bypass
        planner_fallback = False
        planner_fallback_reason = None

        # **Performance Optimization (Task 26)**: Skip planner for simple queries
        # When intent classification shows SIMPLE_LOOKUP or FIELD_FILTER with moderate confidence,
        # the planner is unlikely to add value and just adds latency (100-500ms)
        skip_planner_for_simple = False
        if intent_classification:
            simple_intents = {"SIMPLE_LOOKUP", "FIELD_FILTER"}
            is_simple_intent = intent_classification.intent.value in simple_intents
            # Use 0.6 threshold since intent router typically returns 0.5-0.7 confidence
            high_confidence = intent_classification.confidence >= 0.6
            # Also skip if schema decomposition didn't detect cross-object needs
            no_cross_object = (
                not schema_decomposition or
                not schema_decomposition.needs_cross_object_traversal
            )
            skip_planner_for_simple = is_simple_intent and high_confidence and no_cross_object

            if skip_planner_for_simple:
                LOGGER.info(
                    f"Skipping planner for simple query: intent={intent_classification.intent.value}, "
                    f"confidence={intent_classification.confidence:.2f}"
                )
                query_plan["planner"] = {
                    "used": False,
                    "skipped": True,
                    "skipReason": "simple_query_high_confidence",
                    "intent": intent_classification.intent.value,
                    "intentConfidence": intent_classification.confidence,
                }

        # Run planner for production use OR shadow logging
        # In shadow mode, run for ALL queries (including simple ones) to collect metrics
        # **Task: 28.2**: Skip if planner already ran in disambiguation path (early_planner_ran)
        should_run_planner = PLANNER_AVAILABLE and not early_planner_ran and (
            (PLANNER_ENABLED and not skip_planner_for_simple) or PLANNER_SHADOW_MODE
        )

        if should_run_planner:
            planner_start = time.perf_counter()
            query_hash = hashlib.sha256(request_payload["query"].encode()).hexdigest()[:12]
            try:
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

                # Initialize planner with vocab_cache for entity linking
                # **Requirements: 2.1, 2.2** - Entity linking from vocabulary
                vocab_cache = get_vocab_cache() if VOCAB_CACHE_AVAILABLE and get_vocab_cache else None
                # Initialize schema_cache for field relevance scoring (Task 42)
                schema_cache = get_schema_cache() if SCHEMA_CACHE_AVAILABLE and get_schema_cache else None
                planner = Planner(vocab_cache=vocab_cache, schema_cache=schema_cache, timeout_ms=PLANNER_TIMEOUT_MS)

                # Run planner with timeout
                # **Requirements: 1.2** - 500ms timeout
                # IMPORTANT: Don't use context manager (with) - it calls shutdown(wait=True)
                # which blocks until the background thread completes, defeating the timeout.
                executor = ThreadPoolExecutor(max_workers=1)
                try:
                    future = executor.submit(
                        planner.plan,
                        request_payload["query"],
                        PLANNER_TIMEOUT_MS,
                    )
                    try:
                        planner_result = future.result(timeout=PLANNER_TIMEOUT_MS / 1000.0)

                        # Check confidence threshold
                        # **Requirements: 1.3, 8.1** - Fall back on low confidence
                        would_use_planner = planner_result and planner_result.confidence >= PLANNER_MIN_CONFIDENCE

                        # Shadow Mode: Log results without affecting retrieval
                        # **Task: 28.1 - Shadow Logging for Canary Deployment**
                        # **Task: 28.2 - Phase 1 Canary: use_planner_for_request determines if we use results
                        if PLANNER_SHADOW_MODE and not use_planner_for_request:
                            if planner_result:
                                LOGGER.info(
                                    f"[SHADOW] Planner result: query_hash={query_hash}, "
                                    f"target={planner_result.target_object}, "
                                    f"predicates={len(planner_result.predicates)}, "
                                    f"confidence={planner_result.confidence:.2f}, "
                                    f"would_use={would_use_planner}, "
                                    f"time_ms={planner_result.planning_time_ms:.1f}"
                                )
                                if PLANNER_METRICS_AVAILABLE:
                                    planner_metrics = get_planner_metrics()
                                    planner_metrics.emit_shadow_execution(
                                        latency_ms=planner_result.planning_time_ms,
                                        confidence=planner_result.confidence,
                                        predicate_count=len(planner_result.predicates),
                                        target_object=planner_result.target_object or "unknown",
                                        would_use=would_use_planner,
                                        query_hash=query_hash,
                                    )
                            query_plan["planner"] = {
                                "used": False,
                                "shadowMode": True,
                                "canaryPercent": PLANNER_TRAFFIC_PERCENT,
                                "wouldUse": would_use_planner,
                                "confidence": planner_result.confidence if planner_result else 0.0,
                                "queryHash": query_hash,
                            }
                        # Production Mode (or Canary): Use planner results
                        # **Task: 28.2** - Canary requests use planner results
                        elif would_use_planner:
                            planner_used = True
                            is_canary = PLANNER_SHADOW_MODE and use_planner_for_request
                            mode_label = "[CANARY]" if is_canary else ""
                            LOGGER.info(
                                f"{mode_label} Planner succeeded: target={planner_result.target_object}, "
                                f"predicates={len(planner_result.predicates)}, "
                                f"confidence={planner_result.confidence:.2f}, "
                                f"time_ms={planner_result.planning_time_ms:.1f}"
                            )

                            # Emit planner success metrics
                            # **Requirements: 12.1, 12.2**
                            if PLANNER_METRICS_AVAILABLE:
                                planner_metrics = get_planner_metrics()
                                planner_metrics.emit_plan_success(
                                    latency_ms=planner_result.planning_time_ms,
                                    confidence=planner_result.confidence,
                                    predicate_count=len(planner_result.predicates),
                                    target_object=planner_result.target_object or "unknown",
                                )

                            # Add planner result to query plan
                            query_plan["planner"] = {
                                "used": True,
                                "canary": is_canary,
                                "canaryPercent": PLANNER_TRAFFIC_PERCENT if is_canary else 0,
                                "targetObject": planner_result.target_object,
                                "predicates": [p.to_dict() for p in planner_result.predicates],
                                "confidence": planner_result.confidence,
                                "planningTimeMs": planner_result.planning_time_ms,
                                "seedIds": planner_result.seed_ids,
                                "hasTraversalPlan": planner_result.traversal_plan is not None,
                            }
                        else:
                            # Low confidence - fall back to vector search
                            # **Requirements: 8.1**
                            planner_fallback = True
                            planner_fallback_reason = "low_confidence"
                            confidence = planner_result.confidence if planner_result else 0.0
                            LOGGER.info(
                                f"Planner fallback (low confidence): "
                                f"confidence={confidence:.2f} < threshold={PLANNER_MIN_CONFIDENCE}"
                            )

                            # Emit fallback metric
                            # **Requirements: 12.2**
                            if PLANNER_METRICS_AVAILABLE:
                                planner_metrics = get_planner_metrics()
                                planner_metrics.emit_fallback("low_confidence")
                                planner_metrics.emit_confidence(confidence)

                            query_plan["planner"] = {
                                "used": False,
                                "fallback": True,
                                "fallbackReason": "low_confidence",
                                "confidence": confidence,
                            }

                    except FuturesTimeoutError:
                        # Planner timeout - fall back to vector search
                        # **Requirements: 1.2, 8.1**
                        # **Task: 28.2** - Canary requests also get fallback behavior
                        if PLANNER_SHADOW_MODE and not use_planner_for_request:
                            LOGGER.warning(f"[SHADOW] Planner timeout: query_hash={query_hash}")
                            if PLANNER_METRICS_AVAILABLE:
                                planner_metrics = get_planner_metrics()
                                planner_metrics.emit_shadow_fallback("timeout")
                            query_plan["planner"] = {
                                "used": False,
                                "shadowMode": True,
                                "canaryPercent": PLANNER_TRAFFIC_PERCENT,
                                "timeout": True,
                                "queryHash": query_hash,
                            }
                        else:
                            planner_fallback = True
                            planner_fallback_reason = "timeout"
                            LOGGER.warning(
                                f"Planner timeout after {PLANNER_TIMEOUT_MS}ms, "
                                f"falling back to vector search"
                            )
                            if PLANNER_METRICS_AVAILABLE:
                                planner_metrics = get_planner_metrics()
                                planner_metrics.emit_timeout(PLANNER_TIMEOUT_MS)
                                planner_metrics.emit_fallback("timeout")
                            query_plan["planner"] = {
                                "used": False,
                                "fallback": True,
                                "fallbackReason": "timeout",
                                "timeoutMs": PLANNER_TIMEOUT_MS,
                            }
                finally:
                    # Shutdown without waiting - let background thread complete asynchronously
                    # This prevents the timeout from being defeated by waiting for slow tasks
                    executor.shutdown(wait=False)

            except Exception as e:
                # Planner error - fall back to vector search
                # **Requirements: 8.2**
                # **Task: 28.2** - Canary requests also get fallback behavior
                if PLANNER_SHADOW_MODE and not use_planner_for_request:
                    LOGGER.warning(f"[SHADOW] Planner error: {e}, query_hash={query_hash}")
                    if PLANNER_METRICS_AVAILABLE:
                        planner_metrics = get_planner_metrics()
                        planner_metrics.emit_shadow_fallback("error")
                    query_plan["planner"] = {
                        "used": False,
                        "shadowMode": True,
                        "canaryPercent": PLANNER_TRAFFIC_PERCENT,
                        "error": str(e),
                        "queryHash": query_hash,
                    }
                else:
                    planner_fallback = True
                    planner_fallback_reason = "error"
                    LOGGER.warning(f"Planner error (falling back to vector search): {e}")
                    if PLANNER_METRICS_AVAILABLE:
                        planner_metrics = get_planner_metrics()
                        planner_metrics.emit_error(type(e).__name__)
                        planner_metrics.emit_fallback("error")
                    query_plan["planner"] = {
                        "used": False,
                        "fallback": True,
                        "fallbackReason": "error",
                        "error": str(e),
                    }

            planner_ms = round((time.perf_counter() - planner_start) * 1000, 2)

        # Phase 3: Check if graph retrieval should be used for relationship queries
        graph_result = None
        graph_ms = 0
        supplemental_search_ms = 0
        supplemental_property_count = 0
        supplemental_property_ids = []  # Properties found via decomposition-guided search

        # Skip graph retrieval if cross-object handler already found results
        # Cross-object handler already did graph traversal, so this would be redundant
        # **Performance Fix:** Avoids ~15s redundant traversal
        cross_object_already_traversed = (
            cross_object_result is not None
            and len(cross_object_result.get("matchingIds", [])) > 0
        )
        if cross_object_already_traversed:
            LOGGER.info(f"Skipping graph retrieval - cross-object handler already found {len(cross_object_result['matchingIds'])} results")

        use_graph_retrieval = (
            GRAPH_ROUTING_ENABLED
            and GRAPH_RETRIEVER_AVAILABLE
            and intent_routing
            and intent_routing.get("parameters", {}).get("useGraphTraversal", False)
            and not cross_object_already_traversed  # Skip if cross-object already did traversal
        )

        # =====================================================================
        # Aggregation Query Routing - Route to DynamoDB derived views
        # **Task: 16.5** - Aggregation Query Routing
        # **Requirements: 5.6, 5.7** - Leases/vacancy/activity queries to derived views
        # =====================================================================
        aggregation_results = None
        aggregation_view_used = None
        aggregation_ms = 0
        field_validation = None  # Runtime guard result (Gap 2)

        def _is_aggregation_query(query: str, target_object: str) -> bool:
            """Detect if query requires aggregation data."""
            query_lower = query.lower()
            # Check for aggregation keywords
            for keyword in AGGREGATION_KEYWORDS:
                if keyword in query_lower:
                    return True
            # Check if target object maps to an aggregation view
            if target_object and target_object in AGGREGATION_OBJECTS:
                return True
            return False

        # Aggregation routing can work with or without planner
        # PRIORITY: schema_decomposition.target_entity > planner.target_object > query keywords
        # Schema decomposition is more reliable for entity detection, especially for cross-object queries
        target_object = None
        if schema_decomposition and schema_decomposition.target_entity:
            # Prefer schema decomposition's entity (handles availability/lease queries correctly)
            target_object = schema_decomposition.target_entity
            LOGGER.info(f"[AGGREGATION] Using schema decomposition target: {target_object}")
        elif planner_used and planner_result and hasattr(planner_result, 'target_object'):
            target_object = planner_result.target_object
            LOGGER.info(f"[AGGREGATION] Using planner target: {target_object}")

        if (AGGREGATION_ROUTING_ENABLED
            and DERIVED_VIEW_MANAGER_AVAILABLE
            and _is_aggregation_query(request_payload["query"], target_object)):
                aggregation_start = time.perf_counter()
                try:
                    dvm = DerivedViewManager()
                    view_name = AGGREGATION_OBJECTS.get(target_object, "")
                    query_lower = request_payload["query"].lower()

                    LOGGER.info(f"[AGGREGATION] Attempting derived view routing: target={target_object}, view={view_name}")

                    # Route based on target object or detected query type
                    # Use larger scan limit for views that require post-filtering (e.g., date ranges)
                    scan_limit = max(retrieval_top_k * 50, 500)  # Scan more records for date filtering

                    if view_name == "leases_view" or "expir" in query_lower or "lease" in query_lower:
                        # Leases expiring queries - use dynamic date range parsing
                        from temporal_parser import get_lease_date_range
                        start_date, end_date = get_lease_date_range(
                            query=request_payload["query"],
                            default_days=180  # Preserve S4 behavior when no explicit period
                        )
                        LOGGER.info(
                            f"[AGGREGATION] Lease query date range: {start_date} to {end_date} "
                            f"(from query: '{request_payload['query'][:50]}...')"
                        )
                        aggregation_results = dvm.query_leases_view(
                            end_date_range=(start_date.isoformat(), end_date.isoformat()),
                            limit=scan_limit  # Larger limit for post-filter
                        )
                        # Trim to requested topK after filtering
                        aggregation_results = aggregation_results[:retrieval_top_k]
                        aggregation_view_used = "leases_view"
                        LOGGER.info(f"[AGGREGATION] leases_view returned {len(aggregation_results)} records")

                    elif view_name == "vacancy_view" or "vacanc" in query_lower:
                        # Vacancy queries
                        aggregation_results = dvm.query_vacancy_view(
                            min_vacancy_pct=0,  # Return all with any vacancy
                            limit=retrieval_top_k
                        )
                        aggregation_view_used = "vacancy_view"
                        LOGGER.info(f"[AGGREGATION] vacancy_view returned {len(aggregation_results)} records")

                    elif view_name == "activities_agg" or "activit" in query_lower:
                        # Activity queries
                        aggregation_results = dvm.query_activities_agg(
                            min_count_30d=1,  # At least 1 activity in 30 days
                            limit=retrieval_top_k
                        )
                        aggregation_view_used = "activities_agg"
                        LOGGER.info(f"[AGGREGATION] activities_agg returned {len(aggregation_results)} records")

                    elif view_name == "sales_view" or "sale" in query_lower:
                        # Sales queries (NOT deals - ascendix__Deal__c is different from ascendix__Sale__c)
                        aggregation_results = dvm.query_sales_view(limit=retrieval_top_k)
                        aggregation_view_used = "sales_view"
                        LOGGER.info(f"[AGGREGATION] sales_view returned {len(aggregation_results)} records")

                    elif target_object == "ascendix__Deal__c":
                        # Deal queries - no aggregation view, skip to use graph+KB
                        LOGGER.info(f"[AGGREGATION] No aggregation view for Deal, will use graph+KB")
                        aggregation_results = None

                    elif view_name == "availability_view" or "availab" in query_lower:
                        # Availability queries
                        aggregation_results = dvm.query_availability_view(limit=retrieval_top_k)
                        aggregation_view_used = "availability_view"
                        LOGGER.info(f"[AGGREGATION] availability_view returned {len(aggregation_results)} records")

                except Exception as e:
                    LOGGER.warning(f"[AGGREGATION] Derived view query failed, falling back to KB: {e}")
                    aggregation_results = None

                aggregation_ms = round((time.perf_counter() - aggregation_start) * 1000, 2)

                # Add to query plan for tracing
                query_plan["aggregation"] = {
                    "enabled": True,
                    "viewUsed": aggregation_view_used,
                    "recordCount": len(aggregation_results) if aggregation_results else 0,
                    "timeMs": aggregation_ms,
                }

        # =====================================================================
        # Vector Search - Run with optional planner seed ID filtering
        # **Requirements: 7.1** - Use planner seed IDs if available
        # =====================================================================
        retrieve_start = time.perf_counter()

        # Build metadata filters, optionally with planner's target object
        effective_metadata_filters = metadata_filters.copy()
        if planner_used and planner_result and planner_result.target_object:
            # Add target object filter from planner
            has_sobject_filter = any(
                f.get("field") == "sobject" for f in effective_metadata_filters
            )
            if not has_sobject_filter:
                effective_metadata_filters.append({
                    "field": "sobject",
                    "operator": "EQ",
                    "value": planner_result.target_object,
                })
                LOGGER.info(f"Planner added sobject filter: {planner_result.target_object}")

        # Add graph filter candidate IDs to filter KB results
        # This ensures KB only returns results from the graph-filtered set
        # **Feature: phase3-graph-enhancement** - Graph Filter ID Constraints
        if graph_filter_candidate_ids and len(graph_filter_candidate_ids) > 0:
            effective_metadata_filters.append({
                "field": "recordId",
                "operator": "IN",
                "values": list(graph_filter_candidate_ids)[:500],  # Limit to 500 IDs to avoid filter size issues
            })
            LOGGER.info(f"Graph filter added recordId constraint: {len(graph_filter_candidate_ids)} candidates")

        # If aggregation routing returned results, convert to matches format and skip KB
        # EXCEPTION: When graph filter has found specific IDs, prefer KB with recordId filter
        # because derived views may have stale/test data that doesn't match the graph results
        # This applies to ALL derived views (availability_view, vacancy_view, etc.)
        graph_filter_has_results = graph_filter_candidate_ids and len(graph_filter_candidate_ids) > 0
        skip_aggregation_for_graph_filter = (
            graph_filter_has_results and
            aggregation_view_used is not None  # Skip any derived view when graph filter has results
        )

        if skip_aggregation_for_graph_filter:
            LOGGER.info(
                f"[AGGREGATION] Skipping {aggregation_view_used} ({len(aggregation_results) if aggregation_results else 0} records) "
                f"- using KB with graph filter IDs ({len(graph_filter_candidate_ids)} candidates) for accurate results"
            )
            aggregation_results = None  # Force KB query with recordId filter

        if aggregation_results and len(aggregation_results) > 0:
            LOGGER.info(f"[AGGREGATION] Using {len(aggregation_results)} derived view results, skipping KB query")

            # Convert aggregation results to match format expected by downstream
            matches = []
            for record in aggregation_results:
                # Handle both dict and object results
                if hasattr(record, 'to_dict'):
                    record_dict = record.to_dict()
                else:
                    record_dict = record if isinstance(record, dict) else {}

                # Get the appropriate record ID based on view type
                if aggregation_view_used == "availability_view":
                    record_id = record_dict.get("availability_id") or record_dict.get("property_id", "")
                else:
                    record_id = record_dict.get("lease_id") or record_dict.get("property_id") or record_dict.get("entity_id") or record_dict.get("sale_id", "")

                # Format the content for LLM
                content = _format_aggregation_content(record_dict, aggregation_view_used)

                # Build match object with metadata for citations
                # Note: Use "text" field to match Bedrock KB format expected by Answer Lambda
                match = {
                    "score": 1.0,  # Aggregation results are exact matches
                    "text": content,
                    "metadata": {
                        "recordId": record_id,
                        "sobject": _get_sobject_for_view(aggregation_view_used),
                        "source": f"derived_view:{aggregation_view_used}",
                        **{k: v for k, v in record_dict.items() if v and k not in ["lease_id", "property_id", "entity_id", "sale_id", "availability_id"]}
                    }
                }
                matches.append(match)

            retrieve_ms = aggregation_ms
            LOGGER.info(f"[AGGREGATION] Converted {len(matches)} records to match format")
            # Log first match content for debugging
            if matches:
                LOGGER.info(f"[AGGREGATION] Sample text: {matches[0].get('text', 'EMPTY')[:300]}")
        else:
            # Standard Bedrock KB query
            matches = _query_bedrock_kb(
                request_payload["query"],
                retrieval_top_k,  # Use expanded topK for ranking queries
                effective_metadata_filters,
                use_hybrid=request_payload["hybrid"]
            )
            LOGGER.info(f"Bedrock KB returned {len(matches)} matches (pre-filter)")
            if matches:
                LOGGER.info(f"Sample match metadata: {json.dumps(matches[0].get('metadata', {}))}")

            # Enrich Availability/Lease/Deal matches with Property data when using graph filter
            # This adds property class, type, city to match text since KB chunks don't include them
            enrichment_attempted = False
            if graph_filter_has_results and matches:
                matches = _enrich_availability_matches_with_property_data(matches)
                enrichment_attempted = True

            # Runtime guard: Validate required fields are present after enrichment
            # Logs missing fields for visibility (Gap 2 - Presentation Contract)
            field_validation = _validate_required_fields(matches, enrichment_attempted)

            retrieve_ms = round((time.perf_counter() - retrieve_start) * 1000, 2)

        # Phase 3: Graph retrieval using vector results as seeds
        if use_graph_retrieval:
            graph_start = time.perf_counter()
            try:
                graph_retriever = GraphAwareRetriever(feature_flags={
                    'cache_enabled': True,
                    'strict_auth': True,
                    'metrics_enabled': True,
                    'circuit_breaker_enabled': True,
                    'graceful_degradation_enabled': True,
                })

                # Build user context for graph traversal
                user_context = {
                    'salesforceUserId': request_payload["salesforceUserId"],
                    'sharingBuckets': authz_context.get('sharingBuckets', []),
                    'requestId': request_id,
                }

                # Get max depth from intent routing
                max_depth = intent_routing.get("parameters", {}).get("maxDepth", 2)

                # Extract record IDs from vector search results to seed graph traversal
                seed_record_ids = []
                for match in matches[:15]:  # Use top 15 vector results as seeds
                    record_id = match.get("metadata", {}).get("recordId")
                    if record_id:
                        seed_record_ids.append(record_id)

                LOGGER.info(f"Using {len(seed_record_ids)} seed records for graph traversal")

                # Decomposition-guided supplemental search for related entities
                # If decomposition identified Property filters, do a targeted Property search
                supplemental_property_ids = []
                supplemental_start = time.perf_counter()
                if query_decomposition and query_decomposition.get("needs_traversal"):
                    related_filters = query_decomposition.get("related_filters", {})
                    property_filters = related_filters.get("Property", {})

                    if property_filters:
                        # Build a search query from Property filters
                        # e.g., {"City": "Plano", "PropertyClass": "Class A", "PropertySubType": "Office"}
                        # becomes: "Class A Office property in Plano"
                        filter_terms = []
                        if property_filters.get("PropertyClass"):
                            filter_terms.append(property_filters["PropertyClass"])
                        if property_filters.get("PropertySubType"):
                            filter_terms.append(property_filters["PropertySubType"])
                        filter_terms.append("property")
                        if property_filters.get("City"):
                            filter_terms.append(f"in {property_filters['City']}")
                        if property_filters.get("Name") or property_filters.get("Address"):
                            name_val = property_filters.get("Name") or property_filters.get("Address")
                            filter_terms.append(name_val)

                        supplemental_query = " ".join(filter_terms)
                        LOGGER.info(f"Decomposition supplemental Property search: '{supplemental_query}'")

                        # Search specifically for Properties
                        property_metadata_filters = [
                            {"field": "sobject", "operator": "EQ", "value": "ascendix__Property__c"}
                        ]

                        try:
                            supplemental_matches = _query_bedrock_kb(
                                supplemental_query,
                                10,  # Get top 10 properties
                                property_metadata_filters,
                                use_hybrid=True
                            )

                            for match in supplemental_matches:
                                prop_id = match.get("metadata", {}).get("recordId")
                                if prop_id and prop_id not in seed_record_ids:
                                    supplemental_property_ids.append(prop_id)
                                    seed_record_ids.append(prop_id)

                            LOGGER.info(f"Supplemental Property search found {len(supplemental_property_ids)} additional properties: {supplemental_property_ids[:5]}")
                        except Exception as e:
                            LOGGER.warning(f"Supplemental Property search failed: {e}")

                supplemental_search_ms = round((time.perf_counter() - supplemental_start) * 1000, 2)
                supplemental_property_count = len(supplemental_property_ids)

                # Execute graph retrieval with vector search seeds
                graph_result = graph_retriever.retrieve(
                    query=request_payload["query"],
                    user_context=user_context,
                    filters=request_payload["filters"],
                    max_depth=max_depth,
                    seed_record_ids=seed_record_ids,
                )

                LOGGER.info(f"Graph retrieval: {len(graph_result.get('matchingNodeIds', []))} nodes, "
                           f"depth={graph_result.get('traversalDepth')}, "
                           f"cache_hit={graph_result.get('cacheHit')}")

            except Exception as e:
                LOGGER.warning(f"Graph retrieval failed (falling back to vector): {e}")
                graph_result = None

            graph_ms = round((time.perf_counter() - graph_start) * 1000, 2)

        # Merge graph results with vector results if available
        if graph_result and graph_result.get("matchingNodeIds"):
            matches = _merge_graph_and_vector_results(
                matches,
                graph_result,
                supplemental_property_ids=supplemental_property_ids if 'supplemental_property_ids' in dir() else None
            )
            LOGGER.info(f"After graph merge: {len(matches)} matches")

        # Filter out low-relevance results
        # Use lower threshold when strong metadata filters are applied
        has_strong_metadata_filter = bool(
            detected_sobjects or
            (schema_decomposition and schema_decomposition.target_entity) or
            graph_filter_candidate_ids
        )
        relevance_filter_start = time.perf_counter()
        matches = _filter_low_relevance(matches, has_metadata_filter=has_strong_metadata_filter)
        relevance_filter_ms = round((time.perf_counter() - relevance_filter_start) * 1000, 2)
        LOGGER.info(f"After relevance filter: {len(matches)} matches")

        # Post-filter matches for authorization
        post_filter_start = time.perf_counter()
        filtered_matches = _post_filter_matches(matches, authz_context)
        LOGGER.info(f"Post-filter returned {len(filtered_matches)} matches")
        post_filter_ms = round((time.perf_counter() - post_filter_start) * 1000, 2)

        # Generate presigned S3 URLs for citation previews
        presigned_start = time.perf_counter()
        filtered_matches = _generate_presigned_urls(filtered_matches)
        presigned_ms = round((time.perf_counter() - presigned_start) * 1000, 2)

        # Apply post-retrieval ranking for ranking queries
        ranking_ms = 0
        if ranking_params:
            ranking_start = time.perf_counter()
            filtered_matches = _apply_post_retrieval_ranking(filtered_matches, ranking_params)
            ranking_ms = round((time.perf_counter() - ranking_start) * 1000, 2)
            LOGGER.info(f"Post-retrieval ranking complete: {len(filtered_matches)} results")

        # Apply Field-Level Security (FLS) redaction
        # Requirements: 6.1, 6.2
        fls_ms = 0
        fls_fields_redacted = 0
        if FLS_ENFORCER_AVAILABLE and FLS_ENFORCEMENT == 'enabled':
            fls_start = time.perf_counter()
            try:
                fls_enforcer = get_fls_enforcer()
                user_id = request_payload["salesforceUserId"]
                
                # Group matches by sobject for efficient FLS lookup
                matches_by_sobject: Dict[str, List[Dict[str, Any]]] = {}
                for match in filtered_matches:
                    sobject = match.get("metadata", {}).get("sobject", "Unknown")
                    if sobject not in matches_by_sobject:
                        matches_by_sobject[sobject] = []
                    matches_by_sobject[sobject].append(match)
                
                # Apply FLS redaction per sobject
                fls_filtered_matches = []
                for sobject, sobject_matches in matches_by_sobject.items():
                    readable_fields = fls_enforcer.get_readable_fields(user_id, sobject)
                    
                    for match in sobject_matches:
                        # Redact metadata fields
                        original_metadata = match.get("metadata", {})
                        redacted_metadata = fls_enforcer.redact_fields(original_metadata, readable_fields)
                        
                        # Count redacted fields
                        fls_fields_redacted += len(original_metadata) - len(redacted_metadata)
                        
                        # Create new match with redacted metadata
                        redacted_match = {**match, "metadata": redacted_metadata}
                        fls_filtered_matches.append(redacted_match)
                
                filtered_matches = fls_filtered_matches
                LOGGER.info(f"FLS redaction complete: {fls_fields_redacted} fields redacted")
                
            except Exception as e:
                LOGGER.warning(f"FLS enforcement failed (continuing without): {e}")
            
            fls_ms = round((time.perf_counter() - fls_start) * 1000, 2)

        # Cache the filtered results
        _retrieval_cache.put(
            request_payload["query"],
            request_payload["filters"],
            request_payload["topK"],
            request_payload["salesforceUserId"],
            filtered_matches
        )

        trace = {
            "intentMs": intent_ms,
            "decompositionMs": decomposition_ms,
            "schemaDecompositionMs": schema_decomposition_ms,
            "crossObjectMs": cross_object_ms if 'cross_object_ms' in dir() else 0,
            "graphFilterMs": graph_filter_ms,
            "supplementalSearchMs": supplemental_search_ms,
            "supplementalPropertyCount": supplemental_property_count,
            "plannerMs": planner_ms,
            "authzMs": authz_ms,
            "cacheCheckMs": cache_check_ms,
            "graphMs": graph_ms,
            "retrieveMs": retrieve_ms,
            "relevanceFilterMs": relevance_filter_ms,
            "postFilterMs": post_filter_ms,
            "presignedUrlMs": presigned_ms,
            "rankingMs": ranking_ms,
            "flsMs": fls_ms,
            "flsFieldsRedacted": fls_fields_redacted,
            "flsEnabled": FLS_ENFORCEMENT == 'enabled',
            "totalMs": round((time.perf_counter() - start) * 1000, 2),
            "cached": False,
            "preFilterCount": len(matches),
            "postFilterCount": len(filtered_matches),
        }

        # Add planner metadata to trace
        # **Feature: graph-aware-zero-config-retrieval**
        # **Requirements: 1.4, 12.5**
        if PLANNER_AVAILABLE and PLANNER_ENABLED:
            trace["plannerEnabled"] = True
            trace["plannerUsed"] = planner_used
            trace["plannerFallback"] = planner_fallback
            if planner_fallback_reason:
                trace["plannerFallbackReason"] = planner_fallback_reason
            if planner_result:
                trace["plannerConfidence"] = planner_result.confidence
                trace["plannerPredicateCount"] = len(planner_result.predicates)
                trace["plannerTargetObject"] = planner_result.target_object

        # Add schema decomposition metadata to trace
        if schema_decomposition:
            trace["schemaDecompositionUsed"] = True
            trace["schemaFiltersCount"] = len(schema_decomposition.filters)
            trace["schemaNumericFiltersCount"] = len(schema_decomposition.numeric_filters)
            trace["needsCrossObjectTraversal"] = schema_decomposition.needs_cross_object_traversal
            if graph_filter_candidate_ids is not None:
                trace["graphFilterCandidates"] = len(graph_filter_candidate_ids)
        
        # Add cross-object query metadata to trace
        # **Requirements: 9.1, 9.2, 9.5**
        if cross_object_result:
            trace["crossObjectUsed"] = True
            trace["crossObjectMatchCount"] = len(cross_object_result.get("matchingIds", []))

        # Add field validation metadata to trace (Gap 2 - Runtime Guard)
        if 'field_validation' in dir() and field_validation:
            trace["fieldValidation"] = {
                "totalMatches": field_validation.get("totalMatches", 0),
                "validMatches": field_validation.get("validMatches", 0),
                "partialMatches": field_validation.get("partialMatches", 0),
                "enrichmentAttempted": field_validation.get("enrichmentAttempted", False),
            }
            # Include missing fields details if any (for debugging)
            if field_validation.get("missingFieldsDetails"):
                trace["fieldValidation"]["missingFieldsSample"] = field_validation["missingFieldsDetails"][:3]

        # Phase 3: Add graph metadata to trace
        if graph_result:
            trace["graphUsed"] = True
            trace["graphNodesFound"] = len(graph_result.get("matchingNodeIds", []))
            trace["graphTraversalDepth"] = graph_result.get("traversalDepth", 0)
            trace["graphCacheHit"] = graph_result.get("cacheHit", False)
        else:
            trace["graphUsed"] = use_graph_retrieval  # True if attempted but failed

        # Log telemetry to DynamoDB (async, non-blocking)
        _log_telemetry_async(
            request_id,
            request_payload,
            len(filtered_matches),
            trace,
            authz_context.get("cached", False)
        )

        # Phase 3: Build graph metadata for response
        graph_metadata = {
            "graphUsed": graph_result is not None,
            "traversalDepth": graph_result.get("traversalDepth", 0) if graph_result else 0,
            "nodesVisited": graph_result.get("nodesVisited", 0) if graph_result else 0,
            "matchingNodeCount": len(graph_result.get("matchingNodeIds", [])) if graph_result else 0,
            "cacheHit": graph_result.get("cacheHit", False) if graph_result else False,
        }

        response_body = {
            "matches": filtered_matches,
            "queryPlan": query_plan,
            "trace": trace,
            "requestId": request_id,
            "graphMetadata": graph_metadata,
        }
        return _response(200, response_body)

    except ValidationError as exc:
        LOGGER.warning("Validation error: %s", exc)
        return _response(400, {"error": str(exc)})
    except AuthZServiceError as exc:
        LOGGER.error("AuthZ service error: %s", exc)
        return _response(502, {"error": str(exc)})
    except BedrockKBError as exc:
        LOGGER.error("Bedrock KB error: %s", exc)
        return _response(503, {"error": str(exc)})
    except Exception as exc:  # pragma: no cover - safety net
        LOGGER.exception("Unexpected error in Retrieve Lambda")
        return _response(500, {"error": str(exc)})
