"""
DynamoDB Schema Cache.

Caches discovered Salesforce schemas in DynamoDB with configurable TTL.
Includes in-memory caching layer for Lambda warm invocations (Task 29.6).

**Feature: zero-config-schema-discovery**
**Requirements: 1.6, 1.7**
"""
import json
import os
import time
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
import boto3
from botocore.exceptions import ClientError

from .models import ObjectSchema

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')

# Environment variables
SCHEMA_CACHE_TABLE = os.environ.get('SCHEMA_CACHE_TABLE', 'salesforce-ai-search-schema-cache')

# Default TTL: 24 hours
DEFAULT_TTL_HOURS = 24

# Task 29.6: In-memory cache TTL (5 minutes) - balances freshness vs performance
MEMORY_CACHE_TTL_SECONDS = int(os.environ.get('SCHEMA_MEMORY_CACHE_TTL', '300'))


class SchemaCache:
    """
    DynamoDB-backed schema cache with TTL support.
    
    **Requirements: 1.6, 1.7**
    
    Table Schema:
    - Partition Key: objectApiName (String)
    - Attributes:
      - schema (Map): Full ObjectSchema as JSON
      - discoveredAt (String): ISO timestamp
      - ttl (Number): Unix timestamp for TTL expiration
    """
    
    def __init__(
        self,
        table_name: Optional[str] = None,
        default_ttl_hours: int = DEFAULT_TTL_HOURS,
        memory_cache_ttl_seconds: int = MEMORY_CACHE_TTL_SECONDS
    ):
        """
        Initialize SchemaCache.

        Args:
            table_name: DynamoDB table name (defaults to SCHEMA_CACHE_TABLE env var)
            default_ttl_hours: Default TTL in hours (default: 24)
            memory_cache_ttl_seconds: In-memory cache TTL in seconds (default: 300)
        """
        self.table_name = table_name or SCHEMA_CACHE_TABLE
        self.default_ttl_hours = default_ttl_hours
        self._table = None

        # Task 29.6: In-memory cache to avoid repeated DynamoDB calls
        # Format: {sobject: (ObjectSchema, timestamp)}
        self._memory_cache: Dict[str, Tuple[ObjectSchema, float]] = {}
        # Format: (all_schemas_dict, timestamp) or None
        self._all_schemas_cache: Optional[Tuple[Dict[str, ObjectSchema], float]] = None
        self._memory_cache_ttl = memory_cache_ttl_seconds
    
    @property
    def table(self):
        """Lazy-load DynamoDB table resource."""
        if self._table is None:
            self._table = dynamodb.Table(self.table_name)
        return self._table
    
    def _is_memory_cache_valid(self, timestamp: float) -> bool:
        """Check if a memory cache entry is still valid."""
        return (time.time() - timestamp) < self._memory_cache_ttl

    def get(self, sobject: str) -> Optional[ObjectSchema]:
        """
        Get cached schema for an object.

        **Requirements: 1.6, 1.7**
        Task 29.6: Added in-memory caching layer

        Returns None if:
        - Schema not found in cache
        - Schema has expired (TTL passed)

        Args:
            sobject: Object API name (e.g., 'ascendix__Property__c')

        Returns:
            ObjectSchema if found and valid, None otherwise
        """
        start_time = time.time()

        # Task 29.6: Check in-memory cache first
        if sobject in self._memory_cache:
            schema, timestamp = self._memory_cache[sobject]
            if self._is_memory_cache_valid(timestamp):
                elapsed_ms = (time.time() - start_time) * 1000
                print(f"Memory cache hit for {sobject} ({elapsed_ms:.1f}ms)")
                return schema
            else:
                # Expired, remove from memory cache
                del self._memory_cache[sobject]

        try:
            response = self.table.get_item(
                Key={'objectApiName': sobject},
                ConsistentRead=False  # Eventually consistent for speed
            )

            elapsed_ms = (time.time() - start_time) * 1000

            if 'Item' not in response:
                print(f"Cache miss for {sobject} ({elapsed_ms:.1f}ms)")
                return None

            item = response['Item']

            # Check if TTL has expired (DynamoDB TTL is eventual, so we check manually)
            ttl = item.get('ttl', 0)
            current_time = int(datetime.now(timezone.utc).timestamp())

            if ttl < current_time:
                print(f"Cache expired for {sobject} ({elapsed_ms:.1f}ms)")
                return None

            # Deserialize schema
            schema_data = item.get('schema', {})
            schema = ObjectSchema.from_dict(schema_data)

            # Task 29.6: Store in memory cache
            self._memory_cache[sobject] = (schema, time.time())

            print(f"DynamoDB cache hit for {sobject} ({elapsed_ms:.1f}ms)")
            return schema

        except ClientError as e:
            print(f"DynamoDB error getting {sobject}: {e.response['Error']['Message']}")
            return None
        except Exception as e:
            print(f"Error getting cached schema for {sobject}: {str(e)}")
            return None
    
    def put(
        self,
        sobject: str,
        schema: ObjectSchema,
        ttl_hours: Optional[int] = None
    ) -> bool:
        """
        Cache schema with TTL.

        **Requirements: 1.6**
        Task 29.6: Updates memory cache on write

        Args:
            sobject: Object API name
            schema: ObjectSchema to cache
            ttl_hours: TTL in hours (defaults to default_ttl_hours)

        Returns:
            True if successful, False otherwise
        """
        ttl_hours = ttl_hours or self.default_ttl_hours

        try:
            # Calculate TTL timestamp
            ttl_timestamp = int(
                (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).timestamp()
            )

            # Serialize schema
            schema_data = schema.to_dict()

            item = {
                'objectApiName': sobject,
                'schema': schema_data,
                'discoveredAt': schema.discovered_at,
                'ttl': ttl_timestamp
            }

            self.table.put_item(Item=item)

            # Task 29.6: Update memory cache
            self._memory_cache[sobject] = (schema, time.time())
            # Invalidate all-schemas cache since it's now stale
            self._all_schemas_cache = None

            print(f"Cached schema for {sobject} (TTL: {ttl_hours}h)")
            return True

        except ClientError as e:
            print(f"DynamoDB error putting {sobject}: {e.response['Error']['Message']}")
            return False
        except Exception as e:
            print(f"Error caching schema for {sobject}: {str(e)}")
            return False
    
    def invalidate(self, sobject: Optional[str] = None) -> bool:
        """
        Invalidate cache for specific object or all objects.

        Task 29.6: Also clears memory caches

        Args:
            sobject: Object API name to invalidate, or None for all

        Returns:
            True if successful, False otherwise
        """
        try:
            if sobject:
                # Delete specific object
                self.table.delete_item(Key={'objectApiName': sobject})
                # Task 29.6: Clear from memory cache
                if sobject in self._memory_cache:
                    del self._memory_cache[sobject]
                self._all_schemas_cache = None
                print(f"Invalidated cache for {sobject}")
            else:
                # Scan and delete all items
                response = self.table.scan(ProjectionExpression='objectApiName')
                items = response.get('Items', [])

                # Handle pagination
                while 'LastEvaluatedKey' in response:
                    response = self.table.scan(
                        ProjectionExpression='objectApiName',
                        ExclusiveStartKey=response['LastEvaluatedKey']
                    )
                    items.extend(response.get('Items', []))

                # Delete all items
                with self.table.batch_writer() as batch:
                    for item in items:
                        batch.delete_item(Key={'objectApiName': item['objectApiName']})

                # Task 29.6: Clear all memory caches
                self._memory_cache.clear()
                self._all_schemas_cache = None

                print(f"Invalidated cache for {len(items)} objects")

            return True

        except ClientError as e:
            print(f"DynamoDB error invalidating cache: {e.response['Error']['Message']}")
            return False
        except Exception as e:
            print(f"Error invalidating cache: {str(e)}")
            return False
    
    def get_all(self) -> Dict[str, ObjectSchema]:
        """
        Get all cached schemas.

        Task 29.6: Added in-memory caching layer to avoid DynamoDB scan on every call.

        Returns:
            Dictionary mapping object API name to ObjectSchema
        """
        start_time = time.time()

        # Task 29.6: Check in-memory cache first
        if self._all_schemas_cache is not None:
            schemas, timestamp = self._all_schemas_cache
            if self._is_memory_cache_valid(timestamp):
                elapsed_ms = (time.time() - start_time) * 1000
                print(f"Memory cache hit for get_all: {len(schemas)} schemas ({elapsed_ms:.1f}ms)")
                return schemas
            else:
                # Expired, clear the cache
                self._all_schemas_cache = None

        schemas: Dict[str, ObjectSchema] = {}
        current_time = int(datetime.now(timezone.utc).timestamp())

        try:
            response = self.table.scan()
            items = response.get('Items', [])

            # Handle pagination
            while 'LastEvaluatedKey' in response:
                response = self.table.scan(
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                items.extend(response.get('Items', []))

            for item in items:
                # Skip expired items
                ttl = item.get('ttl', 0)
                if ttl < current_time:
                    continue

                sobject = item.get('objectApiName')
                schema_data = item.get('schema', {})

                if sobject and schema_data:
                    schema = ObjectSchema.from_dict(schema_data)
                    schemas[sobject] = schema
                    # Also populate individual cache entries
                    self._memory_cache[sobject] = (schema, time.time())

            # Task 29.6: Store in memory cache
            self._all_schemas_cache = (schemas, time.time())

            elapsed_ms = (time.time() - start_time) * 1000
            print(f"DynamoDB scan for get_all: {len(schemas)} schemas ({elapsed_ms:.1f}ms)")
            return schemas

        except Exception as e:
            print(f"Error getting all cached schemas: {str(e)}")
            return {}
