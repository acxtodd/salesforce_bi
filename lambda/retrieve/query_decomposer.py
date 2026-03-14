"""
Query Decomposer Module

Loads prompt configuration from YAML and decomposes natural language queries
into structured query plans using an LLM.

Configuration is loaded from:
1. Local file: prompts/query_decomposition.yaml (for development)
2. S3: s3://{DATA_BUCKET}/config/query_decomposition.yaml (for production hot-reload)

Usage:
    from query_decomposer import decompose_query, get_decomposer

    # Simple usage
    result = decompose_query("deals for properties in Dallas")

    # With custom config
    decomposer = get_decomposer(config_path="path/to/config.yaml")
    result = decomposer.decompose("deals in Dallas")
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import boto3
import yaml

LOGGER = logging.getLogger()
LOGGER.setLevel(os.getenv("LOG_LEVEL", "INFO"))

# Cache for config and decomposer instance
_config_cache: Optional[Dict[str, Any]] = None
_config_cache_time: float = 0
_decomposer_instance: Optional["QueryDecomposer"] = None

# Config cache TTL (5 minutes)
CONFIG_CACHE_TTL = int(os.getenv("DECOMPOSER_CONFIG_CACHE_TTL", "300"))


class QueryDecomposer:
    """Decomposes natural language queries into structured query plans."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize decomposer with configuration.

        Args:
            config: Configuration dict loaded from YAML
        """
        self.config = config
        self.enabled = config.get("enabled", True)
        self.model_config = config.get("model", {})
        self.system_prompt = config.get("system_prompt", "")
        self.examples = config.get("examples", [])

        # Initialize Bedrock client
        self._bedrock_client = None

    @property
    def bedrock_client(self):
        """Lazy initialization of Bedrock client."""
        if self._bedrock_client is None:
            self._bedrock_client = boto3.client(
                'bedrock-runtime',
                region_name=os.getenv('AWS_REGION', 'us-west-2')
            )
        return self._bedrock_client

    def decompose(self, query: str) -> Dict[str, Any]:
        """
        Decompose a natural language query into a structured query plan.

        Args:
            query: Natural language query (e.g., "deals for properties in Dallas")

        Returns:
            Dict with:
                - target_entity: The entity to find (Deal, Property, etc.)
                - target_filters: Filters on the target entity
                - related_filters: Filters on related entities
                - needs_traversal: Whether graph traversal is needed
                - latency_ms: Processing time
                - error: Error message if failed
        """
        if not self.enabled:
            return {"enabled": False, "error": "Decomposition disabled"}

        if not self.system_prompt:
            return {"error": "No system prompt configured"}

        start_time = time.time()

        try:
            model_id = self.model_config.get("id", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
            max_tokens = self.model_config.get("max_tokens", 512)
            temperature = self.model_config.get("temperature", 0)

            response = self.bedrock_client.invoke_model(
                modelId=model_id,
                contentType='application/json',
                accept='application/json',
                body=json.dumps({
                    'anthropic_version': 'bedrock-2023-05-31',
                    'max_tokens': max_tokens,
                    'temperature': temperature,
                    'system': self.system_prompt,
                    'messages': [
                        {'role': 'user', 'content': query}
                    ]
                })
            )

            elapsed_ms = (time.time() - start_time) * 1000

            # Parse response
            response_body = json.loads(response['body'].read())
            content = response_body['content'][0]['text']

            # Strip markdown code blocks if present
            json_content = content.strip()
            if json_content.startswith('```'):
                first_newline = json_content.find('\n')
                if first_newline > 0:
                    json_content = json_content[first_newline + 1:]
                if json_content.endswith('```'):
                    json_content = json_content[:-3].strip()

            result = json.loads(json_content)
            result['latency_ms'] = round(elapsed_ms)
            result['model'] = model_id

            LOGGER.info(f"Query decomposition: query='{query[:50]}...', "
                       f"target={result.get('target_entity')}, "
                       f"traversal={result.get('needs_traversal')}, "
                       f"latency={elapsed_ms:.0f}ms")

            return result

        except json.JSONDecodeError as e:
            LOGGER.warning(f"Failed to parse decomposition response: {e}")
            return {
                "error": f"JSON parse error: {e}",
                "latency_ms": round((time.time() - start_time) * 1000)
            }
        except Exception as e:
            LOGGER.error(f"Decomposition failed: {e}")
            return {
                "error": str(e),
                "latency_ms": round((time.time() - start_time) * 1000)
            }

    def get_related_entity_filters(self, decomposition: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Extract filters for related entities from decomposition result.

        Returns:
            Dict mapping entity name to filters, e.g.:
            {"Property": {"City": "Dallas", "PropertySubType": "Office"}}
        """
        related = decomposition.get("related_filters", {})
        if not related:
            return {}

        # Handle both flat and nested structures
        if isinstance(related, dict):
            # Check if it's already entity-keyed
            first_key = next(iter(related.keys()), "")
            if first_key in ["Property", "Deal", "Availability", "Lease", "Account"]:
                return related
            else:
                # Flat structure - assume Property
                return {"Property": related}

        return {}

    def get_target_filters(self, decomposition: Dict[str, Any]) -> Dict[str, Any]:
        """Extract filters for the target entity."""
        return decomposition.get("target_filters", {})

    def needs_graph_traversal(self, decomposition: Dict[str, Any]) -> bool:
        """Check if query requires graph traversal."""
        return decomposition.get("needs_traversal", False)


def load_config(config_path: Optional[str] = None, force_reload: bool = False) -> Dict[str, Any]:
    """
    Load configuration from YAML file.

    Checks in order:
    1. Explicit config_path if provided
    2. S3 bucket if DATA_BUCKET env var is set
    3. Local prompts/query_decomposition.yaml

    Args:
        config_path: Optional explicit path to config file
        force_reload: Force reload even if cached

    Returns:
        Configuration dict
    """
    global _config_cache, _config_cache_time

    # Check cache
    if not force_reload and _config_cache is not None:
        if time.time() - _config_cache_time < CONFIG_CACHE_TTL:
            return _config_cache

    config = None

    # Try explicit path first
    if config_path:
        config = _load_from_file(config_path)

    # Try S3 if DATA_BUCKET is set
    if config is None:
        data_bucket = os.getenv("DATA_BUCKET")
        if data_bucket:
            config = _load_from_s3(data_bucket, "config/query_decomposition.yaml")

    # Fall back to local file
    if config is None:
        local_path = Path(__file__).parent / "prompts" / "query_decomposition.yaml"
        if local_path.exists():
            config = _load_from_file(str(local_path))

    if config is None:
        LOGGER.warning("No decomposition config found, using defaults")
        config = {"enabled": False}

    # Cache the config
    _config_cache = config
    _config_cache_time = time.time()

    return config


def _load_from_file(path: str) -> Optional[Dict[str, Any]]:
    """Load config from local file."""
    try:
        with open(path, 'r') as f:
            config = yaml.safe_load(f)
            LOGGER.info(f"Loaded decomposition config from {path}")
            return config
    except Exception as e:
        LOGGER.warning(f"Failed to load config from {path}: {e}")
        return None


def _load_from_s3(bucket: str, key: str) -> Optional[Dict[str, Any]]:
    """Load config from S3."""
    try:
        s3 = boto3.client('s3')
        response = s3.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        config = yaml.safe_load(content)
        LOGGER.info(f"Loaded decomposition config from s3://{bucket}/{key}")
        return config
    except Exception as e:
        LOGGER.debug(f"Failed to load config from S3: {e}")
        return None


def get_decomposer(config_path: Optional[str] = None, force_reload: bool = False) -> QueryDecomposer:
    """
    Get or create decomposer instance.

    Args:
        config_path: Optional path to config file
        force_reload: Force reload configuration

    Returns:
        QueryDecomposer instance
    """
    global _decomposer_instance

    if force_reload or _decomposer_instance is None:
        config = load_config(config_path, force_reload)
        _decomposer_instance = QueryDecomposer(config)

    return _decomposer_instance


def decompose_query(query: str) -> Dict[str, Any]:
    """
    Convenience function to decompose a query using default config.

    Args:
        query: Natural language query

    Returns:
        Decomposition result dict
    """
    decomposer = get_decomposer()
    return decomposer.decompose(query)


# CLI for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"\nQuery: {query}\n")

        result = decompose_query(query)
        print(json.dumps(result, indent=2))
    else:
        # Run examples from config
        config = load_config()
        decomposer = QueryDecomposer(config)

        print("\n" + "="*60)
        print("Testing examples from config")
        print("="*60)

        for example in config.get("examples", []):
            query = example.get("query", "")
            expected = example.get("expected", {})

            print(f"\nQuery: {query}")
            result = decomposer.decompose(query)

            if "error" not in result:
                # Compare with expected
                match = result.get("target_entity") == expected.get("target_entity")
                status = "PASS" if match else "FAIL"
                print(f"Target: {result.get('target_entity')} ({status})")
                print(f"Latency: {result.get('latency_ms')}ms")
            else:
                print(f"Error: {result.get('error')}")
