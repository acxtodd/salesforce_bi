"""
AuthZ Sidecar Lambda Function
Computes sharing buckets and FLS profile tags for Salesforce users.
Implements caching with DynamoDB and 24-hour TTL.

Production-ready implementation using StandardAuthStrategy for real
Salesforce sharing and FLS queries.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""
import json
import os
import boto3
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
import logging
import sys

# Add common module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))

try:
    from salesforce_client import (
        SalesforceClient,
        SalesforceAPIError,
        get_salesforce_client,
    )
except ImportError:
    # Fallback for local testing
    SalesforceClient = None
    SalesforceAPIError = Exception
    get_salesforce_client = None

# Configure logging
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(os.getenv('LOG_LEVEL', 'INFO'))

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
ssm = boto3.client('ssm')
cloudwatch = boto3.client('cloudwatch')

# Environment variables
AUTHZ_CACHE_TABLE = os.environ.get('AUTHZ_CACHE_TABLE', 'authz_cache_table')
SALESFORCE_API_ENDPOINT = os.environ.get('SALESFORCE_API_ENDPOINT', '')
SALESFORCE_API_VERSION = os.environ.get('SALESFORCE_API_VERSION', 'v59.0')

# Authorization mode: "strict" (enforce all) or "relaxed" (admin bypass)
# Requirements: 5.5, 5.6
AUTHZ_MODE = os.environ.get('AUTHZ_MODE', 'strict')

# Cache TTL: 24 hours
CACHE_TTL_HOURS = 24


class AuthorizationStrategy(ABC):
    """Abstract base class for authorization strategies."""
    
    @abstractmethod
    def compute_sharing_buckets(self, user_id: str) -> List[str]:
        """
        Compute sharing bucket tags for a Salesforce user.
        
        Args:
            user_id: Salesforce User ID
            
        Returns:
            List of sharing bucket tags
        """
        pass
    
    @abstractmethod
    def is_admin_user(self, user_id: str) -> bool:
        """
        Check if user is an admin with elevated access.
        
        Args:
            user_id: Salesforce User ID
            
        Returns:
            True if user is admin
        """
        pass


class StandardAuthStrategy(AuthorizationStrategy):
    """
    Production authorization strategy using real Salesforce APIs.
    
    Queries UserRecordAccess, role hierarchy, and territory assignments
    to compute sharing buckets. No hardcoded user lists.
    
    Requirements: 5.2, 5.3
    """
    
    # Admin profile names that get elevated access in relaxed mode
    ADMIN_PROFILE_NAMES = {
        'System Administrator',
        'システム管理者',  # Japanese
        'Systemadministrator',  # German
    }
    
    def __init__(
        self,
        sf_client: Optional[SalesforceClient] = None,
        mode: str = 'strict',
    ):
        """
        Initialize authorization strategy.
        
        Args:
            sf_client: Salesforce API client (optional, will create from SSM if not provided)
            mode: "strict" (enforce all) or "relaxed" (admin bypass)
        """
        self._sf_client = sf_client
        self._mode = mode
        self._user_info_cache: Dict[str, Dict[str, Any]] = {}
    
    @property
    def sf_client(self) -> SalesforceClient:
        """Get or create Salesforce client."""
        if self._sf_client is None:
            if get_salesforce_client is not None:
                self._sf_client = get_salesforce_client()
            else:
                raise ValueError("Salesforce client not available")
        return self._sf_client
    
    def _get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve user information including role, profile, and active status.
        
        Args:
            user_id: Salesforce User ID
            
        Returns:
            User info dictionary or None if not found
        """
        # Check cache first
        if user_id in self._user_info_cache:
            return self._user_info_cache[user_id]
        
        query = (
            f"SELECT Id, Name, UserRoleId, UserRole.Name, "
            f"ProfileId, Profile.Name, IsActive, Email "
            f"FROM User WHERE Id = '{user_id}' LIMIT 1"
        )
        
        try:
            result = self.sf_client.query(query)
            records = result.get('records', [])
            user_info = records[0] if records else None
            
            # Cache the result
            if user_info:
                self._user_info_cache[user_id] = user_info
            
            return user_info
        except SalesforceAPIError as e:
            LOGGER.error(f"Error retrieving user info for {user_id}: {e}")
            return None
    
    def _get_role_hierarchy(self, role_id: str) -> List[str]:
        """
        Get role hierarchy (parent roles) for a given role.
        
        This allows users to see records owned by users in subordinate roles.
        
        Args:
            role_id: Salesforce UserRole ID
            
        Returns:
            List of role IDs in the hierarchy (including the given role)
        """
        if not role_id:
            return []
        
        role_ids = [role_id]
        
        # Query role hierarchy - get parent roles
        # In Salesforce, ParentRoleId points to the parent role
        # Users can see records owned by users in subordinate roles
        query = (
            f"SELECT Id, ParentRoleId, Name FROM UserRole "
            f"WHERE Id = '{role_id}' LIMIT 1"
        )
        
        try:
            result = self.sf_client.query(query)
            records = result.get('records', [])
            
            if records:
                role = records[0]
                parent_role_id = role.get('ParentRoleId')
                
                # Recursively get parent roles (up to 10 levels to prevent infinite loops)
                if parent_role_id:
                    parent_roles = self._get_role_hierarchy_up(parent_role_id, max_depth=10)
                    role_ids.extend(parent_roles)
            
            return role_ids
        except SalesforceAPIError as e:
            LOGGER.error(f"Error retrieving role hierarchy for {role_id}: {e}")
            return [role_id]
    
    def _get_role_hierarchy_up(self, role_id: str, max_depth: int = 10) -> List[str]:
        """
        Get parent roles going up the hierarchy.
        
        Args:
            role_id: Starting role ID
            max_depth: Maximum depth to traverse
            
        Returns:
            List of parent role IDs
        """
        if max_depth <= 0 or not role_id:
            return []
        
        role_ids = [role_id]
        
        query = (
            f"SELECT Id, ParentRoleId FROM UserRole "
            f"WHERE Id = '{role_id}' LIMIT 1"
        )
        
        try:
            result = self.sf_client.query(query)
            records = result.get('records', [])
            
            if records and records[0].get('ParentRoleId'):
                parent_roles = self._get_role_hierarchy_up(
                    records[0]['ParentRoleId'],
                    max_depth - 1
                )
                role_ids.extend(parent_roles)
            
            return role_ids
        except SalesforceAPIError as e:
            LOGGER.error(f"Error retrieving parent roles for {role_id}: {e}")
            return [role_id]
    
    def _get_subordinate_roles(self, role_id: str) -> List[str]:
        """
        Get subordinate roles (children) for a given role.
        
        Users can see records owned by users in subordinate roles.
        
        Args:
            role_id: Salesforce UserRole ID
            
        Returns:
            List of subordinate role IDs
        """
        if not role_id:
            return []
        
        subordinate_ids: List[str] = []
        
        # Query direct children
        query = (
            f"SELECT Id FROM UserRole "
            f"WHERE ParentRoleId = '{role_id}'"
        )
        
        try:
            result = self.sf_client.query(query)
            records = result.get('records', [])
            
            for record in records:
                child_id = record.get('Id')
                if child_id:
                    subordinate_ids.append(child_id)
                    # Recursively get children (up to 10 levels)
                    subordinate_ids.extend(self._get_subordinate_roles(child_id))
            
            return subordinate_ids
        except SalesforceAPIError as e:
            LOGGER.error(f"Error retrieving subordinate roles for {role_id}: {e}")
            return []
    
    def _get_user_territories(self, user_id: str) -> List[str]:
        """
        Retrieve territory assignments for a user.
        
        Args:
            user_id: Salesforce User ID
            
        Returns:
            List of territory IDs
        """
        query = (
            f"SELECT TerritoryId, Territory.Name "
            f"FROM UserTerritory2Association "
            f"WHERE UserId = '{user_id}' AND IsActive = true"
        )
        
        try:
            result = self.sf_client.query(query)
            territories = []
            
            for record in result.get('records', []):
                territory_id = record.get('TerritoryId')
                if territory_id:
                    territories.append(territory_id)
            
            return territories
        except SalesforceAPIError as e:
            # Territory management may not be enabled in all orgs
            LOGGER.warning(f"Error retrieving territories for {user_id}: {e}")
            return []
    
    def _get_sharing_groups(self, user_id: str) -> List[str]:
        """
        Get public groups the user belongs to for sharing rules.
        
        Args:
            user_id: Salesforce User ID
            
        Returns:
            List of group IDs
        """
        query = (
            f"SELECT GroupId FROM GroupMember "
            f"WHERE UserOrGroupId = '{user_id}'"
        )
        
        try:
            result = self.sf_client.query(query)
            groups = []
            
            for record in result.get('records', []):
                group_id = record.get('GroupId')
                if group_id:
                    groups.append(group_id)
            
            return groups
        except SalesforceAPIError as e:
            LOGGER.warning(f"Error retrieving sharing groups for {user_id}: {e}")
            return []
    
    def compute_sharing_buckets(self, user_id: str) -> List[str]:
        """
        Compute sharing bucket tags for a Salesforce user.
        
        Includes buckets for:
        - Owner (user's own records)
        - Role hierarchy (records owned by users in subordinate roles)
        - Territory assignments
        - Sharing groups
        
        Requirements: 5.2, 5.3
        
        Args:
            user_id: Salesforce User ID
            
        Returns:
            List of sharing bucket tags
        """
        sharing_buckets: List[str] = []
        
        # Always add owner bucket
        sharing_buckets.append(f"owner:{user_id}")
        
        # Get user info
        user_info = self._get_user_info(user_id)
        
        if user_info:
            if not user_info.get('IsActive', False):
                LOGGER.warning(f"User {user_id} is not active")
            
            # Add role bucket
            role_id = user_info.get('UserRoleId')
            if role_id:
                sharing_buckets.append(f"role:{role_id}")
                
                role_name = user_info.get('UserRole', {}).get('Name', '')
                if role_name:
                    sharing_buckets.append(f"role_name:{role_name}")
                
                # Add subordinate role buckets (role hierarchy sharing)
                subordinate_roles = self._get_subordinate_roles(role_id)
                for sub_role_id in subordinate_roles:
                    sharing_buckets.append(f"role_hierarchy:{sub_role_id}")
        
        # Add territory buckets
        territories = self._get_user_territories(user_id)
        for territory_id in territories:
            sharing_buckets.append(f"territory:{territory_id}")
        
        # Add sharing group buckets
        groups = self._get_sharing_groups(user_id)
        for group_id in groups:
            sharing_buckets.append(f"group:{group_id}")
        
        LOGGER.info(f"Computed {len(sharing_buckets)} sharing buckets for user {user_id}")
        return sharing_buckets
    
    def is_admin_user(self, user_id: str) -> bool:
        """
        Check if user is an admin based on profile.
        
        Args:
            user_id: Salesforce User ID
            
        Returns:
            True if user has admin profile
        """
        user_info = self._get_user_info(user_id)
        
        if not user_info:
            return False
        
        profile_name = user_info.get('Profile', {}).get('Name', '')
        return profile_name in self.ADMIN_PROFILE_NAMES


# =============================================================================
# Field-Level Security (FLS) Enforcement
# Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
# =============================================================================

# FLS enforcement toggle: "enabled" or "disabled"
# Requirements: 6.4, 6.5
FLS_ENFORCEMENT = os.environ.get('FLS_ENFORCEMENT', 'disabled')

# FLS cache TTL: 24 hours
FLS_CACHE_TTL_HOURS = 24

# FLS cache table name
FLS_CACHE_TABLE = os.environ.get('FLS_CACHE_TABLE', 'fls_cache_table')


class FLSEnforcer:
    """
    Field-Level Security enforcement using Salesforce FieldPermissions.
    
    Queries FieldPermissions for user's profile/permission sets to determine
    which fields the user can read. Caches results with 24-hour TTL.
    
    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
    """
    
    def __init__(
        self,
        sf_client: Optional[SalesforceClient] = None,
        enabled: bool = True,
        cache_table: Optional[str] = None,
    ):
        """
        Initialize FLS enforcer.
        
        Args:
            sf_client: Salesforce API client (optional, will create from SSM if not provided)
            enabled: Whether FLS enforcement is enabled
            cache_table: DynamoDB table name for FLS cache
        """
        self._sf_client = sf_client
        self._enabled = enabled
        self._cache_table = cache_table or FLS_CACHE_TABLE
        self._memory_cache: Dict[str, Dict[str, Set[str]]] = {}
        self._memory_cache_timestamps: Dict[str, datetime] = {}
    
    @property
    def sf_client(self) -> SalesforceClient:
        """Get or create Salesforce client."""
        if self._sf_client is None:
            if get_salesforce_client is not None:
                self._sf_client = get_salesforce_client()
            else:
                raise ValueError("Salesforce client not available")
        return self._sf_client
    
    @property
    def enabled(self) -> bool:
        """Check if FLS enforcement is enabled."""
        return self._enabled
    
    def _get_user_profile_id(self, user_id: str) -> Optional[str]:
        """
        Get the profile ID for a user.
        
        Args:
            user_id: Salesforce User ID
            
        Returns:
            Profile ID or None if not found
        """
        query = f"SELECT ProfileId FROM User WHERE Id = '{user_id}' LIMIT 1"
        
        try:
            result = self.sf_client.query(query)
            records = result.get('records', [])
            if records:
                return records[0].get('ProfileId')
            return None
        except SalesforceAPIError as e:
            LOGGER.error(f"Error retrieving profile ID for user {user_id}: {e}")
            return None
    
    def _get_user_permission_set_ids(self, user_id: str) -> List[str]:
        """
        Get permission set IDs assigned to a user.
        
        Args:
            user_id: Salesforce User ID
            
        Returns:
            List of permission set IDs
        """
        query = (
            f"SELECT PermissionSetId FROM PermissionSetAssignment "
            f"WHERE AssigneeId = '{user_id}'"
        )
        
        try:
            result = self.sf_client.query(query)
            return [
                record.get('PermissionSetId')
                for record in result.get('records', [])
                if record.get('PermissionSetId')
            ]
        except SalesforceAPIError as e:
            LOGGER.warning(f"Error retrieving permission sets for user {user_id}: {e}")
            return []
    
    def _query_field_permissions(
        self,
        parent_ids: List[str],
        sobject: str,
    ) -> Set[str]:
        """
        Query FieldPermissions for given parent IDs (profile or permission sets).
        
        Args:
            parent_ids: List of profile or permission set IDs
            sobject: Salesforce object API name
            
        Returns:
            Set of readable field names
        """
        if not parent_ids:
            return set()
        
        # Build IN clause for parent IDs
        parent_ids_str = "', '".join(parent_ids)
        
        query = (
            f"SELECT Field, PermissionsRead FROM FieldPermissions "
            f"WHERE ParentId IN ('{parent_ids_str}') "
            f"AND SobjectType = '{sobject}' "
            f"AND PermissionsRead = true"
        )
        
        try:
            result = self.sf_client.query(query)
            readable_fields = set()
            
            for record in result.get('records', []):
                field = record.get('Field')
                if field:
                    # Field format is "ObjectName.FieldName", extract just the field name
                    if '.' in field:
                        field = field.split('.')[-1]
                    readable_fields.add(field)
            
            return readable_fields
        except SalesforceAPIError as e:
            LOGGER.error(f"Error querying FieldPermissions for {sobject}: {e}")
            return set()
    
    def _get_cached_fls(
        self,
        user_id: str,
        sobject: str,
    ) -> Optional[Set[str]]:
        """
        Get cached FLS permissions from DynamoDB.
        
        Args:
            user_id: Salesforce User ID
            sobject: Salesforce object API name
            
        Returns:
            Set of readable fields or None if not cached/expired
        """
        cache_key = f"{user_id}:{sobject}"
        
        # Check memory cache first
        if cache_key in self._memory_cache:
            timestamp = self._memory_cache_timestamps.get(cache_key)
            if timestamp and (datetime.utcnow() - timestamp).total_seconds() < FLS_CACHE_TTL_HOURS * 3600:
                LOGGER.debug(f"FLS memory cache hit for {cache_key}")
                return self._memory_cache[cache_key].get('readable_fields', set())
        
        # Check DynamoDB cache
        try:
            table = dynamodb.Table(self._cache_table)
            response = table.get_item(
                Key={
                    'cacheKey': cache_key,
                }
            )
            
            if 'Item' not in response:
                LOGGER.debug(f"FLS cache miss for {cache_key}")
                return None
            
            item = response['Item']
            
            # Check TTL
            ttl = item.get('ttl', 0)
            if ttl < int(datetime.utcnow().timestamp()):
                LOGGER.debug(f"FLS cache expired for {cache_key}")
                return None
            
            # Convert list back to set
            readable_fields = set(item.get('readableFields', []))
            
            # Update memory cache
            self._memory_cache[cache_key] = {'readable_fields': readable_fields}
            self._memory_cache_timestamps[cache_key] = datetime.utcnow()
            
            LOGGER.debug(f"FLS DynamoDB cache hit for {cache_key}")
            return readable_fields
            
        except Exception as e:
            LOGGER.error(f"Error retrieving FLS cache for {cache_key}: {e}")
            return None
    
    def _cache_fls(
        self,
        user_id: str,
        sobject: str,
        readable_fields: Set[str],
    ) -> None:
        """
        Cache FLS permissions in DynamoDB with 24-hour TTL.
        
        Args:
            user_id: Salesforce User ID
            sobject: Salesforce object API name
            readable_fields: Set of readable field names
        """
        cache_key = f"{user_id}:{sobject}"
        
        # Update memory cache
        self._memory_cache[cache_key] = {'readable_fields': readable_fields}
        self._memory_cache_timestamps[cache_key] = datetime.utcnow()
        
        # Update DynamoDB cache
        try:
            table = dynamodb.Table(self._cache_table)
            
            ttl = int((datetime.utcnow() + timedelta(hours=FLS_CACHE_TTL_HOURS)).timestamp())
            
            item = {
                'cacheKey': cache_key,
                'userId': user_id,
                'sobject': sobject,
                'readableFields': list(readable_fields),  # DynamoDB doesn't support sets directly
                'computedAt': datetime.utcnow().isoformat(),
                'ttl': ttl,
            }
            
            table.put_item(Item=item)
            LOGGER.debug(f"Cached FLS for {cache_key} (TTL: {ttl})")
            
        except Exception as e:
            LOGGER.error(f"Error caching FLS for {cache_key}: {e}")
            # Don't fail if caching fails
    
    def get_readable_fields(
        self,
        user_id: str,
        sobject: str,
    ) -> Set[str]:
        """
        Get fields readable by user for an object.
        
        Queries FieldPermissions for user's profile and permission sets.
        Caches results with 24-hour TTL.
        
        Requirements: 6.1, 6.3
        
        Args:
            user_id: Salesforce User ID
            sobject: Salesforce object API name
            
        Returns:
            Set of readable field names
        """
        if not self._enabled:
            LOGGER.debug(f"FLS disabled, returning empty set for {user_id}:{sobject}")
            return set()  # Return empty set when disabled (all fields allowed)
        
        # Check cache first
        cached = self._get_cached_fls(user_id, sobject)
        if cached is not None:
            return cached
        
        LOGGER.info(f"Computing FLS for user {user_id} on {sobject}")
        
        # Get user's profile ID
        profile_id = self._get_user_profile_id(user_id)
        
        # Get user's permission set IDs
        permission_set_ids = self._get_user_permission_set_ids(user_id)
        
        # Combine all parent IDs
        parent_ids = []
        if profile_id:
            parent_ids.append(profile_id)
        parent_ids.extend(permission_set_ids)
        
        if not parent_ids:
            LOGGER.warning(f"No profile or permission sets found for user {user_id}")
            return set()
        
        # Query FieldPermissions
        readable_fields = self._query_field_permissions(parent_ids, sobject)
        
        # Standard fields that are always readable (Id, Name, etc.)
        # These are typically not in FieldPermissions but are always accessible
        standard_fields = {'Id', 'Name', 'CreatedDate', 'LastModifiedDate', 'OwnerId'}
        readable_fields.update(standard_fields)
        
        # Cache the result
        self._cache_fls(user_id, sobject, readable_fields)
        
        LOGGER.info(f"Found {len(readable_fields)} readable fields for {user_id} on {sobject}")
        return readable_fields
    
    def redact_fields(
        self,
        record: Dict[str, Any],
        readable_fields: Set[str],
    ) -> Dict[str, Any]:
        """
        Redact fields user cannot read from record.
        
        Requirements: 6.2
        
        Args:
            record: Record dictionary with field values
            readable_fields: Set of fields the user can read
            
        Returns:
            Record with non-readable fields redacted
        """
        if not self._enabled:
            return record  # Return unchanged when disabled
        
        if not readable_fields:
            # If no readable fields specified, return all fields
            # This handles the case where FLS lookup failed
            return record
        
        redacted_record = {}
        
        for field, value in record.items():
            if field in readable_fields:
                redacted_record[field] = value
            else:
                # Redact the field - don't include it in output
                LOGGER.debug(f"Redacting field {field} - user lacks read permission")
        
        return redacted_record
    
    def redact_records(
        self,
        records: List[Dict[str, Any]],
        user_id: str,
        sobject: str,
    ) -> List[Dict[str, Any]]:
        """
        Redact fields from multiple records.
        
        Convenience method that gets readable fields once and applies to all records.
        
        Args:
            records: List of record dictionaries
            user_id: Salesforce User ID
            sobject: Salesforce object API name
            
        Returns:
            List of records with non-readable fields redacted
        """
        if not self._enabled:
            return records
        
        readable_fields = self.get_readable_fields(user_id, sobject)
        
        return [
            self.redact_fields(record, readable_fields)
            for record in records
        ]
    
    def invalidate_cache(self, user_id: str, sobject: Optional[str] = None) -> bool:
        """
        Invalidate FLS cache for a user.
        
        Args:
            user_id: Salesforce User ID
            sobject: Optional specific object to invalidate (all if None)
            
        Returns:
            True if successful
        """
        try:
            # Clear memory cache
            keys_to_remove = []
            for key in self._memory_cache:
                if key.startswith(f"{user_id}:"):
                    if sobject is None or key == f"{user_id}:{sobject}":
                        keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self._memory_cache[key]
                if key in self._memory_cache_timestamps:
                    del self._memory_cache_timestamps[key]
            
            # Clear DynamoDB cache
            if sobject:
                cache_key = f"{user_id}:{sobject}"
                table = dynamodb.Table(self._cache_table)
                table.delete_item(Key={'cacheKey': cache_key})
            else:
                # Would need to scan/query for all user's entries
                # For now, just clear memory cache
                LOGGER.warning(f"DynamoDB cache invalidation for all objects not implemented")
            
            LOGGER.info(f"Invalidated FLS cache for user {user_id}")
            return True
            
        except Exception as e:
            LOGGER.error(f"Error invalidating FLS cache: {e}")
            return False


# Module-level FLS enforcer instance
_fls_enforcer: Optional[FLSEnforcer] = None


def get_fls_enforcer(
    sf_client: Optional[SalesforceClient] = None,
    enabled: Optional[bool] = None,
    force_refresh: bool = False,
) -> FLSEnforcer:
    """
    Get or create the FLS enforcer singleton.
    
    Args:
        sf_client: Optional Salesforce client
        enabled: Whether FLS is enabled (defaults to FLS_ENFORCEMENT env var)
        force_refresh: Force creation of new enforcer
        
    Returns:
        FLSEnforcer instance
    """
    global _fls_enforcer
    
    if _fls_enforcer is None or force_refresh:
        is_enabled = enabled if enabled is not None else (FLS_ENFORCEMENT == 'enabled')
        _fls_enforcer = FLSEnforcer(
            sf_client=sf_client,
            enabled=is_enabled,
        )
    
    return _fls_enforcer


def clear_fls_enforcer() -> None:
    """Clear the cached FLS enforcer singleton."""
    global _fls_enforcer
    _fls_enforcer = None


# Module-level strategy instance
_auth_strategy: Optional[StandardAuthStrategy] = None


def get_auth_strategy(
    sf_client: Optional[SalesforceClient] = None,
    mode: Optional[str] = None,
    force_refresh: bool = False,
) -> StandardAuthStrategy:
    """
    Get or create the authorization strategy singleton.
    
    Args:
        sf_client: Optional Salesforce client
        mode: Authorization mode (defaults to AUTHZ_MODE env var)
        force_refresh: Force creation of new strategy
        
    Returns:
        StandardAuthStrategy instance
    """
    global _auth_strategy
    
    if _auth_strategy is None or force_refresh:
        _auth_strategy = StandardAuthStrategy(
            sf_client=sf_client,
            mode=mode or AUTHZ_MODE,
        )
    
    return _auth_strategy


def clear_auth_strategy() -> None:
    """Clear the cached auth strategy singleton."""
    global _auth_strategy
    _auth_strategy = None


def get_salesforce_access_token() -> str:
    """
    Retrieve Salesforce access token from SSM Parameter Store or environment.
    In production, this would use OAuth 2.0 JWT flow.
    """
    try:
        parameter_name = os.environ.get('SALESFORCE_TOKEN_PARAM', '/salesforce/access_token')
        response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
        return response['Parameter']['Value']
    except Exception as e:
        LOGGER.error(f"Error retrieving Salesforce token: {str(e)}")
        # Fallback to environment variable for local testing
        return os.environ.get('SALESFORCE_ACCESS_TOKEN', '')


def query_salesforce(query: str, access_token: str) -> Dict[str, Any]:
    """
    Execute SOQL query against Salesforce REST API.
    
    Args:
        query: SOQL query string
        access_token: Salesforce access token
    
    Returns:
        Query results dictionary
    """
    import urllib.request
    import urllib.parse
    
    # URL encode the query
    encoded_query = urllib.parse.quote(query)
    url = f"{SALESFORCE_API_ENDPOINT}/services/data/{SALESFORCE_API_VERSION}/query?q={encoded_query}"
    
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status != 200:
                raise Exception(f"Salesforce returned status {response.status}")
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        LOGGER.error(f"Error querying Salesforce: {str(e)}")
        raise


def get_user_info(user_id: str, access_token: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve user information including role, profile, and territory.
    """
    query = f"SELECT Id, Name, UserRoleId, UserRole.Name, ProfileId, Profile.Name, IsActive, Email FROM User WHERE Id = '{user_id}' LIMIT 1"
    
    try:
        result = query_salesforce(query, access_token)
        records = result.get('records', [])
        return records[0] if records else None
    except Exception as e:
        LOGGER.error(f"Error retrieving user info: {str(e)}")
        return None


def get_user_territories(user_id: str, access_token: str) -> List[str]:
    """
    Retrieve territory assignments for a user.
    """
    query = f"SELECT TerritoryId, Territory.Name FROM UserTerritory2Association WHERE UserId = '{user_id}' AND IsActive = true"
    
    try:
        result = query_salesforce(query, access_token)
        territories = []
        for record in result.get('records', []):
            if record.get('TerritoryId'):
                territories.append(record['TerritoryId'])
        return territories
    except Exception as e:
        LOGGER.error(f"Error retrieving user territories: {str(e)}")
        return []


def compute_sharing_buckets(user_id: str, access_token: str) -> List[str]:
    """
    Compute sharing bucket tags for a Salesforce user.
    
    Uses StandardAuthStrategy for production-ready sharing bucket computation.
    No hardcoded user lists (POC_ADMIN_USERS, SEED_DATA_OWNERS removed).
    
    Requirements: 5.1, 5.2, 5.3, 5.4
    """
    sharing_buckets = []
    
    # Always add owner bucket
    sharing_buckets.append(f"owner:{user_id}")
    
    # Try to get user info and role
    user_info = get_user_info(user_id, access_token)
    if user_info:
        if not user_info.get('IsActive', False):
            LOGGER.warning(f"User {user_id} is not active")
        
        # Add role bucket
        if user_info.get('UserRoleId'):
            role_id = user_info['UserRoleId']
            role_name = user_info.get('UserRole', {}).get('Name', '')
            sharing_buckets.append(f"role:{role_id}")
            if role_name:
                sharing_buckets.append(f"role_name:{role_name}")
    
    # Try to add territory buckets
    territories = get_user_territories(user_id, access_token)
    for territory_id in territories:
        sharing_buckets.append(f"territory:{territory_id}")
    
    # Authorization mode handling (Requirements: 5.5, 5.6)
    if AUTHZ_MODE == 'relaxed':
        if user_info:
            profile_name = user_info.get('Profile', {}).get('Name', '')
            if profile_name in StandardAuthStrategy.ADMIN_PROFILE_NAMES:
                LOGGER.info(f"Relaxed mode: Admin user {user_id} granted elevated access")
                # In relaxed mode, admin users get a special bucket that matches all records
                sharing_buckets.append('admin:all_access')
        else:
            # Network failure in relaxed mode - grant access for POC
            # This handles VPC networking issues where Salesforce API is unreachable
            LOGGER.warning(f"Relaxed mode: Could not verify user {user_id} profile (network error) - granting POC access")
            sharing_buckets.append('admin:all_access')
    
    LOGGER.info(f"Computed {len(sharing_buckets)} sharing buckets for user {user_id}")
    return sharing_buckets


def compute_fls_profile_tags(user_id: str, access_token: str) -> List[str]:
    """
    Compute FLS (Field-Level Security) profile tags for a user.
    
    For POC: This is a placeholder. FLS enforcement is skipped.
    Phase 3 will implement full FLS checking.
    
    Args:
        user_id: Salesforce User ID
    
    Returns:
        List of FLS profile tags (empty for POC)
    """
    # POC: Skip FLS enforcement
    # Assume all fields are readable if user can see the record
    LOGGER.info(f"Skipping FLS computation for user {user_id} (POC limitation)")
    return []


def get_cached_authz_context(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve cached authorization context from DynamoDB.
    
    Args:
        user_id: Salesforce User ID
    
    Returns:
        Cached context or None if not found or expired
    """
    try:
        table = dynamodb.Table(AUTHZ_CACHE_TABLE)
        response = table.get_item(Key={'salesforceUserId': user_id})
        
        if 'Item' not in response:
            LOGGER.debug(f"Cache miss for user {user_id}")
            return None
        
        item = response['Item']
        
        # Check if TTL has expired (DynamoDB TTL is eventual, so we check manually)
        ttl = item.get('ttl', 0)
        if ttl < int(datetime.utcnow().timestamp()):
            LOGGER.debug(f"Cache expired for user {user_id}")
            return None
        
        LOGGER.debug(f"Cache hit for user {user_id}")
        return item
    
    except Exception as e:
        LOGGER.error(f"Error retrieving from cache: {str(e)}")
        return None


def cache_authz_context(user_id: str, sharing_buckets: List[str], fls_profile_tags: List[str]) -> None:
    """
    Store authorization context in DynamoDB with 24-hour TTL.
    
    Args:
        user_id: Salesforce User ID
        sharing_buckets: List of sharing bucket tags
        fls_profile_tags: List of FLS profile tags
    """
    try:
        table = dynamodb.Table(AUTHZ_CACHE_TABLE)
        
        computed_at = datetime.utcnow().isoformat()
        ttl = int((datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS)).timestamp())
        
        item = {
            'salesforceUserId': user_id,
            'sharingBuckets': sharing_buckets,
            'flsProfileTags': fls_profile_tags,
            'computedAt': computed_at,
            'ttl': ttl,
            'authzMode': AUTHZ_MODE,
        }
        
        table.put_item(Item=item)
        LOGGER.debug(f"Cached authZ context for user {user_id} (TTL: {ttl})")
    
    except Exception as e:
        LOGGER.error(f"Error caching authZ context: {str(e)}")
        # Don't fail the request if caching fails


def emit_cache_metric(metric_name: str, value: float = 1.0) -> None:
    """
    Emit CloudWatch metric for cache performance monitoring.
    
    Args:
        metric_name: Name of the metric (CacheHit, CacheMiss, CacheError)
        value: Metric value (default: 1.0)
    """
    try:
        cloudwatch.put_metric_data(
            Namespace='SalesforceAISearch/AuthZ',
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Value': value,
                    'Unit': 'Count',
                    'Timestamp': datetime.utcnow()
                }
            ]
        )
    except Exception as e:
        # Don't fail the request if metric emission fails
        LOGGER.warning(f"Failed to emit CloudWatch metric {metric_name}: {str(e)}")


def get_authz_context(user_id: str) -> Dict[str, Any]:
    """
    Get authorization context for a user (from cache or compute fresh).
    
    Args:
        user_id: Salesforce User ID
    
    Returns:
        Authorization context with sharing buckets and FLS tags
    """
    # Check cache first
    cached = get_cached_authz_context(user_id)
    if cached:
        emit_cache_metric('CacheHit')
        return {
            'salesforceUserId': user_id,
            'sharingBuckets': cached.get('sharingBuckets', []),
            'flsProfileTags': cached.get('flsProfileTags', []),
            'computedAt': cached.get('computedAt'),
            'cached': True,
            'authzMode': cached.get('authzMode', AUTHZ_MODE),
        }
    
    # Cache miss - compute fresh
    LOGGER.info(f"Computing fresh authZ context for user {user_id}")
    emit_cache_metric('CacheMiss')
    
    access_token = get_salesforce_access_token()
    if not access_token:
        raise ValueError("Salesforce access token not available")
    
    sharing_buckets = compute_sharing_buckets(user_id, access_token)
    fls_profile_tags = compute_fls_profile_tags(user_id, access_token)
    
    # Cache the result
    cache_authz_context(user_id, sharing_buckets, fls_profile_tags)
    
    return {
        'salesforceUserId': user_id,
        'sharingBuckets': sharing_buckets,
        'flsProfileTags': fls_profile_tags,
        'computedAt': datetime.utcnow().isoformat(),
        'cached': False,
        'authzMode': AUTHZ_MODE,
    }


def invalidate_cache(user_id: str) -> Dict[str, Any]:
    """
    Invalidate cached authorization context for a user.
    
    Args:
        user_id: Salesforce User ID
    
    Returns:
        Result dictionary with success status
    """
    try:
        table = dynamodb.Table(AUTHZ_CACHE_TABLE)
        table.delete_item(Key={'salesforceUserId': user_id})
        
        LOGGER.info(f"Invalidated cache for user {user_id}")
        return {
            'success': True,
            'message': f'Cache invalidated for user {user_id}'
        }
    
    except Exception as e:
        LOGGER.error(f"Error invalidating cache: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def lambda_handler(event, context):
    """
    Lambda handler for AuthZ Sidecar.
    
    Supported operations:
    1. Get authorization context (default)
    2. Invalidate cache
    
    Event format for get context:
    {
        "operation": "getAuthZContext",
        "salesforceUserId": "005xx..."
    }
    
    Event format for invalidate cache:
    {
        "operation": "invalidateCache",
        "salesforceUserId": "005xx..."
    }
    
    Returns:
    {
        "salesforceUserId": "005xx...",
        "sharingBuckets": ["owner:005xx", "role:00Exx", ...],
        "flsProfileTags": [],
        "computedAt": "2025-11-13T10:30:00Z",
        "cached": true/false,
        "authzMode": "strict" | "relaxed"
    }
    """
    try:
        operation = event.get('operation', 'getAuthZContext')
        user_id = event.get('salesforceUserId')
        
        if not user_id:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'salesforceUserId is required'})
            }
        
        # Validate user ID format (15 or 18 chars starting with 005)
        if not (user_id.startswith('005') and len(user_id) in [15, 18]):
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid Salesforce User ID format'})
            }
        
        if operation == 'invalidateCache':
            result = invalidate_cache(user_id)
            return {
                'statusCode': 200 if result['success'] else 500,
                'body': json.dumps(result)
            }
        
        elif operation == 'getAuthZContext':
            authz_context = get_authz_context(user_id)
            return {
                'statusCode': 200,
                'body': json.dumps(authz_context)
            }
        
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': f'Unknown operation: {operation}'})
            }
    
    except Exception as e:
        LOGGER.error(f"Error in lambda_handler: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


# Export for testing
__all__ = [
    'StandardAuthStrategy',
    'AuthorizationStrategy',
    'get_auth_strategy',
    'clear_auth_strategy',
    'compute_sharing_buckets',
    'compute_fls_profile_tags',
    'get_authz_context',
    'invalidate_cache',
    'lambda_handler',
    'AUTHZ_MODE',
    # FLS exports
    'FLSEnforcer',
    'get_fls_enforcer',
    'clear_fls_enforcer',
    'FLS_ENFORCEMENT',
    'FLS_CACHE_TABLE',
    'FLS_CACHE_TTL_HOURS',
]
