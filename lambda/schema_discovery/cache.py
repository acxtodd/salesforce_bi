"""
DynamoDB Schema Cache.

Caches discovered Salesforce schemas in DynamoDB with configurable TTL.

**Feature: zero-config-schema-discovery**
**Requirements: 1.6, 1.7**
"""
import json
import os
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import boto3
from botocore.exceptions import ClientError

from models import ObjectSchema

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')

# Environment variables
SCHEMA_CACHE_TABLE = os.environ.get('SCHEMA_CACHE_TABLE', 'salesforce-ai-search-schema-cache')

# Default TTL: 24 hours
DEFAULT_TTL_HOURS = 24


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
        default_ttl_hours: int = DEFAULT_TTL_HOURS
    ):
        """
        Initialize SchemaCache.
        
        Args:
            table_name: DynamoDB table name (defaults to SCHEMA_CACHE_TABLE env var)
            default_ttl_hours: Default TTL in hours (default: 24)
        """
        self.table_name = table_name or SCHEMA_CACHE_TABLE
        self.default_ttl_hours = default_ttl_hours
        self._table = None
    
    @property
    def table(self):
        """Lazy-load DynamoDB table resource."""
        if self._table is None:
            self._table = dynamodb.Table(self.table_name)
        return self._table
    
    def get(self, sobject: str) -> Optional[ObjectSchema]:
        """
        Get cached schema for an object.
        
        **Requirements: 1.6, 1.7**
        
        Returns None if:
        - Schema not found in cache
        - Schema has expired (TTL passed)
        
        Args:
            sobject: Object API name (e.g., 'ascendix__Property__c')
            
        Returns:
            ObjectSchema if found and valid, None otherwise
        """
        start_time = time.time()
        
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
            
            print(f"Cache hit for {sobject} ({elapsed_ms:.1f}ms)")
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
        
        Args:
            sobject: Object API name
            schema: ObjectSchema to cache
            ttl_hours: TTL in hours (defaults to default_ttl_hours)
            
        Returns:
            True if successful, False otherwise
        """
        ttl_hours = ttl_hours if ttl_hours is not None else self.default_ttl_hours
        
        try:
            # Calculate TTL timestamp
            ttl_timestamp = int(
                (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).timestamp()
            )
            
            # Serialize schema (use Decimal for DynamoDB compatibility)
            schema_data = schema.to_dict(for_dynamodb=True)
            
            item = {
                'objectApiName': sobject,
                'schema': schema_data,
                'discoveredAt': schema.discovered_at,
                'ttl': ttl_timestamp
            }
            
            self.table.put_item(Item=item)
            
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
        
        Args:
            sobject: Object API name to invalidate, or None for all
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if sobject:
                # Delete specific object
                self.table.delete_item(Key={'objectApiName': sobject})
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
        
        Returns:
            Dictionary mapping object API name to ObjectSchema
        """
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
                    schemas[sobject] = ObjectSchema.from_dict(schema_data)
            
            print(f"Retrieved {len(schemas)} cached schemas")
            return schemas
            
        except Exception as e:
            print(f"Error getting all cached schemas: {str(e)}")
            return {}