"""
Property-based tests for AuthZ Sidecar Lambda.

Uses Hypothesis to verify correctness properties for sharing bucket computation
and authorization mode behavior.

**Feature: zero-config-production, Property 7: Sharing Bucket Computation**
**Feature: zero-config-production, Property 8: Authorization Mode Behavior**
"""
import os
import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List, Optional
import importlib

# Add parent directory to path for imports
authz_dir = os.path.dirname(__file__)
sys.path.insert(0, authz_dir)


def _ensure_authz_index(force_reload=False):
    """Ensure we have the correct authz/index.py module loaded.
    
    Args:
        force_reload: If True, always reload the module even if it's already correct.
    """
    authz_dir = os.path.dirname(__file__)
    # Remove any existing authz_dir entries to avoid duplicates
    sys.path = [p for p in sys.path if p != authz_dir]
    sys.path.insert(0, authz_dir)
    
    # Check if the correct module is already loaded
    if 'index' in sys.modules and not force_reload:
        current_index = sys.modules['index']
        if hasattr(current_index, '__file__') and 'authz' in current_index.__file__:
            return current_index
    
    # Remove any cached 'index' module to ensure we import the correct one
    if 'index' in sys.modules:
        del sys.modules['index']
    
    import index
    return index


from hypothesis import given, strategies as st, settings, assume

# Initial import
index = _ensure_authz_index()
from index import (
    StandardAuthStrategy,
    compute_sharing_buckets,
    AUTHZ_MODE,
)





# =============================================================================
# Hypothesis Strategies for Salesforce Data
# =============================================================================

# Salesforce ID strategy (15 or 18 character IDs)
def salesforce_user_id() -> st.SearchStrategy[str]:
    """Generate valid Salesforce User IDs (start with 005)."""
    return st.from_regex(r'005[a-zA-Z0-9]{12}([a-zA-Z0-9]{3})?', fullmatch=True)


def salesforce_role_id() -> st.SearchStrategy[str]:
    """Generate valid Salesforce Role IDs (start with 00E)."""
    return st.from_regex(r'00E[a-zA-Z0-9]{12}([a-zA-Z0-9]{3})?', fullmatch=True)


def salesforce_territory_id() -> st.SearchStrategy[str]:
    """Generate valid Salesforce Territory IDs (start with 0Mx)."""
    return st.from_regex(r'0Mx[a-zA-Z0-9]{12}([a-zA-Z0-9]{3})?', fullmatch=True)


def salesforce_group_id() -> st.SearchStrategy[str]:
    """Generate valid Salesforce Group IDs (start with 00G)."""
    return st.from_regex(r'00G[a-zA-Z0-9]{12}([a-zA-Z0-9]{3})?', fullmatch=True)


def role_name() -> st.SearchStrategy[str]:
    """Generate valid role names."""
    return st.text(
        alphabet=st.characters(whitelist_categories=('L', 'N', 'Zs')),
        min_size=1,
        max_size=50
    ).filter(lambda x: x.strip() != '')


def profile_name() -> st.SearchStrategy[str]:
    """Generate profile names including admin profiles."""
    admin_profiles = ['System Administrator', 'Standard User', 'Custom Profile']
    return st.sampled_from(admin_profiles)


@st.composite
def user_info_data(draw) -> Dict[str, Any]:
    """Generate user info data structure."""
    user_id = draw(salesforce_user_id())
    has_role = draw(st.booleans())
    is_active = draw(st.booleans())
    
    user_info = {
        'Id': user_id,
        'Name': draw(st.text(min_size=1, max_size=50)),
        'IsActive': is_active,
        'Email': f"{draw(st.text(min_size=1, max_size=10))}@example.com",
        'ProfileId': draw(st.from_regex(r'00e[a-zA-Z0-9]{12}', fullmatch=True)),
        'Profile': {'Name': draw(profile_name())},
    }
    
    if has_role:
        user_info['UserRoleId'] = draw(salesforce_role_id())
        user_info['UserRole'] = {'Name': draw(role_name())}
    else:
        user_info['UserRoleId'] = None
        user_info['UserRole'] = None
    
    return user_info


@st.composite
def territory_list(draw) -> List[str]:
    """Generate a list of territory IDs."""
    count = draw(st.integers(min_value=0, max_value=5))
    return [draw(salesforce_territory_id()) for _ in range(count)]


@st.composite
def group_list(draw) -> List[str]:
    """Generate a list of group IDs."""
    count = draw(st.integers(min_value=0, max_value=5))
    return [draw(salesforce_group_id()) for _ in range(count)]


# =============================================================================
# Property 7: Sharing Bucket Computation
# **Validates: Requirements 5.2, 5.3**
# =============================================================================

class TestSharingBucketComputationProperty:
    """
    Property 7: Sharing Bucket Computation
    
    *For any* Salesforce user, the AuthZ Service SHALL compute sharing buckets
    that include: owner bucket, role hierarchy buckets, territory buckets,
    and sharing rule buckets based on real Salesforce data queries.
    
    **Feature: zero-config-production, Property 7: Sharing Bucket Computation**
    **Validates: Requirements 5.2, 5.3**
    """
    
    @given(
        user_id=salesforce_user_id(),
        user_info=user_info_data(),
        territories=territory_list(),
    )
    @settings(max_examples=100, deadline=None)
    def test_owner_bucket_always_included(
        self,
        user_id: str,
        user_info: Dict[str, Any],
        territories: List[str],
    ):
        """
        Property: For any user, the owner bucket MUST always be included.
        
        **Feature: zero-config-production, Property 7: Sharing Bucket Computation**
        **Validates: Requirements 5.2, 5.3**
        """
        # Arrange: Set up mocks - ensure we patch the correct authz/index module
        user_info['Id'] = user_id  # Ensure consistency
        idx = _ensure_authz_index(force_reload=True)
        
        with patch.object(idx, 'get_user_info') as mock_user_info, \
             patch.object(idx, 'get_user_territories') as mock_territories:
            
            mock_user_info.return_value = user_info
            mock_territories.return_value = territories
            
            # Act
            buckets = idx.compute_sharing_buckets(user_id, 'fake_token')
            
            # Assert: Owner bucket must always be present
            assert f"owner:{user_id}" in buckets, \
                f"Owner bucket missing for user {user_id}"
    
    @given(
        user_id=salesforce_user_id(),
        user_info=user_info_data(),
        territories=territory_list(),
    )
    @settings(max_examples=100, deadline=None)
    def test_role_bucket_included_when_user_has_role(
        self,
        user_id: str,
        user_info: Dict[str, Any],
        territories: List[str],
    ):
        """
        Property: When user has a role, role bucket MUST be included.
        
        **Feature: zero-config-production, Property 7: Sharing Bucket Computation**
        **Validates: Requirements 5.2, 5.3**
        """
        # Only test when user has a role
        assume(user_info.get('UserRoleId') is not None)
        
        user_info['Id'] = user_id
        idx = _ensure_authz_index(force_reload=True)
        
        with patch.object(idx, 'get_user_info') as mock_user_info, \
             patch.object(idx, 'get_user_territories') as mock_territories:
            
            mock_user_info.return_value = user_info
            mock_territories.return_value = territories
            
            # Act
            buckets = idx.compute_sharing_buckets(user_id, 'fake_token')
            
            # Assert: Role bucket must be present
            role_id = user_info['UserRoleId']
            assert f"role:{role_id}" in buckets, \
                "Role bucket should be present when user has a role"
    
    @given(
        user_id=salesforce_user_id(),
        user_info=user_info_data(),
        territories=territory_list(),
    )
    @settings(max_examples=100, deadline=None)
    def test_territory_buckets_included_for_all_territories(
        self,
        user_id: str,
        user_info: Dict[str, Any],
        territories: List[str],
    ):
        """
        Property: All territory assignments MUST have corresponding buckets.
        
        **Feature: zero-config-production, Property 7: Sharing Bucket Computation**
        **Validates: Requirements 5.2, 5.3**
        """
        user_info['Id'] = user_id
        idx = _ensure_authz_index(force_reload=True)
        
        with patch.object(idx, 'get_user_info') as mock_user_info, \
             patch.object(idx, 'get_user_territories') as mock_territories:
            
            mock_user_info.return_value = user_info
            mock_territories.return_value = territories
            
            # Act
            buckets = idx.compute_sharing_buckets(user_id, 'fake_token')
            
            # Assert: All territories must have buckets
            for territory_id in territories:
                assert f"territory:{territory_id}" in buckets, \
                    "All territory buckets should be present"
    
    @given(
        user_id=salesforce_user_id(),
        user_info=user_info_data(),
        territories=territory_list(),
    )
    @settings(max_examples=100, deadline=None)
    def test_bucket_count_matches_expected(
        self,
        user_id: str,
        user_info: Dict[str, Any],
        territories: List[str],
    ):
        """
        Property: Bucket count should match expected components.
        
        **Feature: zero-config-production, Property 7: Sharing Bucket Computation**
        **Validates: Requirements 5.2, 5.3**
        """
        user_info['Id'] = user_id
        
        with patch.dict(os.environ, {'AUTHZ_MODE': 'strict'}):
            idx = _ensure_authz_index(force_reload=True)
            
            with patch.object(idx, 'get_user_info') as mock_user_info, \
                 patch.object(idx, 'get_user_territories') as mock_territories:
                
                mock_user_info.return_value = user_info
                mock_territories.return_value = territories
                
                # Act
                buckets = idx.compute_sharing_buckets(user_id, 'fake_token')
                
                # Calculate expected minimum count
                expected_min = 1  # owner bucket
                if user_info.get('UserRoleId'):
                    expected_min += 1  # role bucket
                    if user_info.get('UserRole', {}).get('Name'):
                        expected_min += 1  # role_name bucket
                expected_min += len(territories)  # territory buckets
                
                # Assert: At least expected number of buckets
                assert len(buckets) >= expected_min, \
                    "Bucket count should match expected"


# =============================================================================
# Property 8: Authorization Mode Behavior
# **Validates: Requirements 5.5, 5.6**
# =============================================================================

class TestAuthorizationModeBehaviorProperty:
    """
    Property 8: Authorization Mode Behavior
    
    *For any* user request, when `AUTHZ_MODE=strict` the AuthZ Service SHALL
    enforce all sharing rules, and when `AUTHZ_MODE=relaxed` admin users
    SHALL have access to all records.
    
    **Feature: zero-config-production, Property 8: Authorization Mode Behavior**
    **Validates: Requirements 5.5, 5.6**
    """
    
    @given(
        user_id=salesforce_user_id(),
        territories=territory_list(),
    )
    @settings(max_examples=100, deadline=None)
    def test_strict_mode_no_admin_bypass(
        self,
        user_id: str,
        territories: List[str],
    ):
        """
        Property: In strict mode, admin users do NOT get special access.
        
        **Feature: zero-config-production, Property 8: Authorization Mode Behavior**
        **Validates: Requirements 5.5, 5.6**
        """
        # Create admin user info
        admin_user_info = {
            'Id': user_id,
            'Name': 'Admin User',
            'IsActive': True,
            'UserRoleId': '00Exx000000ADMIN',
            'UserRole': {'Name': 'SystemAdministrator'},
            'ProfileId': '00exx000000ADMIN',
            'Profile': {'Name': 'System Administrator'},
        }
        
        # Set env var and reload module first
        with patch.dict(os.environ, {'AUTHZ_MODE': 'strict'}):
            # Reload the module to pick up the new env var
            idx = _ensure_authz_index(force_reload=True)
            
            # Now apply mocks to the reloaded module
            with patch.object(idx, 'get_user_info') as mock_user_info, \
                 patch.object(idx, 'get_user_territories') as mock_territories:
                
                mock_user_info.return_value = admin_user_info
                mock_territories.return_value = territories
                
                # Act
                buckets = idx.compute_sharing_buckets(user_id, 'fake_token')
                
                # Assert: No admin:all_access bucket in strict mode
                assert 'admin:all_access' not in buckets, \
                    "Admin bypass should not be present in strict mode"
    
    @given(
        user_id=salesforce_user_id(),
        territories=territory_list(),
    )
    @settings(max_examples=100, deadline=None)
    def test_relaxed_mode_admin_gets_bypass(
        self,
        user_id: str,
        territories: List[str],
    ):
        """
        Property: In relaxed mode, admin users get all_access bucket.
        
        **Feature: zero-config-production, Property 8: Authorization Mode Behavior**
        **Validates: Requirements 5.5, 5.6**
        """
        # Create admin user info
        admin_user_info = {
            'Id': user_id,
            'Name': 'Admin User',
            'IsActive': True,
            'UserRoleId': '00Exx000000ADMIN',
            'UserRole': {'Name': 'SystemAdministrator'},
            'ProfileId': '00exx000000ADMIN',
            'Profile': {'Name': 'System Administrator'},
        }
        
        # Set env var and reload module first
        with patch.dict(os.environ, {'AUTHZ_MODE': 'relaxed'}):
            # Reload the module to pick up the new env var
            idx = _ensure_authz_index(force_reload=True)
            
            # Now apply mocks to the reloaded module
            with patch.object(idx, 'get_user_info') as mock_user_info, \
                 patch.object(idx, 'get_user_territories') as mock_territories:
                
                mock_user_info.return_value = admin_user_info
                mock_territories.return_value = territories
                
                # Act
                buckets = idx.compute_sharing_buckets(user_id, 'fake_token')
                
                # Assert: Admin gets all_access bucket in relaxed mode
                assert 'admin:all_access' in buckets, \
                    "Admin should have all_access bucket in relaxed mode"
    
    @given(
        user_id=salesforce_user_id(),
        territories=territory_list(),
    )
    @settings(max_examples=100, deadline=None)
    def test_relaxed_mode_non_admin_no_bypass(
        self,
        user_id: str,
        territories: List[str],
    ):
        """
        Property: In relaxed mode, non-admin users do NOT get bypass.
        
        **Feature: zero-config-production, Property 8: Authorization Mode Behavior**
        **Validates: Requirements 5.5, 5.6**
        """
        # Create non-admin user info
        standard_user_info = {
            'Id': user_id,
            'Name': 'Standard User',
            'IsActive': True,
            'UserRoleId': '00Exx000000SALES',
            'UserRole': {'Name': 'SalesRep'},
            'ProfileId': '00exx000000STAND',
            'Profile': {'Name': 'Standard User'},
        }
        
        # Set env var and reload module first
        with patch.dict(os.environ, {'AUTHZ_MODE': 'relaxed'}):
            # Reload the module to pick up the new env var
            idx = _ensure_authz_index(force_reload=True)
            
            # Now apply mocks to the reloaded module
            with patch.object(idx, 'get_user_info') as mock_user_info, \
                 patch.object(idx, 'get_user_territories') as mock_territories:
                
                mock_user_info.return_value = standard_user_info
                mock_territories.return_value = territories
                
                # Act
                buckets = idx.compute_sharing_buckets(user_id, 'fake_token')
                
                # Assert: Non-admin should NOT have all_access bucket
                assert 'admin:all_access' not in buckets, \
                    "Non-admin should not have all_access bucket even in relaxed mode"


# =============================================================================
# StandardAuthStrategy Property Tests
# =============================================================================

class TestStandardAuthStrategyProperties:
    """
    Property tests for StandardAuthStrategy class.
    
    **Feature: zero-config-production, Property 7: Sharing Bucket Computation**
    **Validates: Requirements 5.2, 5.3**
    """
    
    @given(user_id=salesforce_user_id())
    @settings(max_examples=100, deadline=None)
    def test_is_admin_returns_boolean(self, user_id: str):
        """
        Property: is_admin_user always returns a boolean.
        
        **Feature: zero-config-production, Property 7: Sharing Bucket Computation**
        **Validates: Requirements 5.2, 5.3**
        """
        # Create mock SF client
        mock_sf_client = Mock()
        mock_sf_client.query.return_value = {
            'records': [{
                'Id': user_id,
                'Profile': {'Name': 'Standard User'},
            }]
        }
        
        strategy = StandardAuthStrategy(sf_client=mock_sf_client, mode='strict')
        
        # Act
        result = strategy.is_admin_user(user_id)
        
        # Assert: Result is always boolean
        assert isinstance(result, bool), \
            f"is_admin_user should return bool, got {type(result)}"
    
    @given(
        user_id=salesforce_user_id(),
        profile_name=st.sampled_from([
            'System Administrator',
            'システム管理者',
            'Systemadministrator',
        ])
    )
    @settings(max_examples=100, deadline=None)
    def test_admin_profiles_recognized(self, user_id: str, profile_name: str):
        """
        Property: All admin profile names are recognized.
        
        **Feature: zero-config-production, Property 7: Sharing Bucket Computation**
        **Validates: Requirements 5.2, 5.3**
        """
        # Create mock SF client
        mock_sf_client = Mock()
        mock_sf_client.query.return_value = {
            'records': [{
                'Id': user_id,
                'Profile': {'Name': profile_name},
                'IsActive': True,
            }]
        }
        
        strategy = StandardAuthStrategy(sf_client=mock_sf_client, mode='strict')
        
        # Act
        result = strategy.is_admin_user(user_id)
        
        # Assert: Admin profiles are recognized
        assert result is True, \
            f"Profile '{profile_name}' should be recognized as admin"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])


# =============================================================================
# Property 9: FLS Enforcement
# **Validates: Requirements 6.1, 6.2, 6.4**
# =============================================================================

class TestFLSEnforcementProperty:
    """
    Property 9: FLS Enforcement
    
    *For any* search result and user, when `FLS_ENFORCEMENT=enabled` the FLS
    Service SHALL redact field values for which the user lacks read permission
    according to FieldPermissions.
    
    **Feature: zero-config-production, Property 9: FLS Enforcement**
    **Validates: Requirements 6.1, 6.2, 6.4**
    """
    
    @given(
        user_id=salesforce_user_id(),
        sobject=st.sampled_from(['Account', 'Contact', 'Opportunity', 'Property__c']),
        readable_fields=st.sets(st.sampled_from([
            'Id', 'Name', 'OwnerId', 'CreatedDate', 'Description',
            'Phone', 'Email', 'Address', 'City', 'State', 'Country',
        ]), min_size=1, max_size=8),
        record_fields=st.sets(st.sampled_from([
            'Id', 'Name', 'OwnerId', 'CreatedDate', 'Description',
            'Phone', 'Email', 'Address', 'City', 'State', 'Country',
            'SecretField', 'ConfidentialData', 'InternalNotes',
        ]), min_size=1, max_size=10),
    )
    @settings(max_examples=100, deadline=None)
    def test_redacted_fields_not_in_output(
        self,
        user_id: str,
        sobject: str,
        readable_fields: set,
        record_fields: set,
    ):
        """
        Property: Fields not in readable_fields MUST NOT appear in output.
        
        **Feature: zero-config-production, Property 9: FLS Enforcement**
        **Validates: Requirements 6.1, 6.2, 6.4**
        """
        idx = _ensure_authz_index(force_reload=True)
        
        # Create a record with the generated fields
        record = {field: f"value_{field}" for field in record_fields}
        
        # Create FLS enforcer (enabled)
        enforcer = idx.FLSEnforcer(sf_client=None, enabled=True)
        
        # Act: Redact fields
        redacted = enforcer.redact_fields(record, readable_fields)
        
        # Assert: No field in output that isn't in readable_fields
        for field in redacted.keys():
            assert field in readable_fields, \
                f"Field '{field}' should have been redacted (not in readable_fields)"
    
    @given(
        user_id=salesforce_user_id(),
        readable_fields=st.sets(st.sampled_from([
            'Id', 'Name', 'OwnerId', 'CreatedDate', 'Description',
        ]), min_size=1, max_size=5),
        record_fields=st.sets(st.sampled_from([
            'Id', 'Name', 'OwnerId', 'CreatedDate', 'Description',
        ]), min_size=1, max_size=5),
    )
    @settings(max_examples=100, deadline=None)
    def test_readable_fields_preserved(
        self,
        user_id: str,
        readable_fields: set,
        record_fields: set,
    ):
        """
        Property: Fields in readable_fields MUST be preserved in output.
        
        **Feature: zero-config-production, Property 9: FLS Enforcement**
        **Validates: Requirements 6.1, 6.2, 6.4**
        """
        idx = _ensure_authz_index(force_reload=True)
        
        # Create a record with the generated fields
        record = {field: f"value_{field}" for field in record_fields}
        
        # Create FLS enforcer (enabled)
        enforcer = idx.FLSEnforcer(sf_client=None, enabled=True)
        
        # Act: Redact fields
        redacted = enforcer.redact_fields(record, readable_fields)
        
        # Assert: All fields that are both in record and readable_fields are preserved
        expected_fields = record_fields & readable_fields
        for field in expected_fields:
            assert field in redacted, \
                f"Field '{field}' should be preserved (in readable_fields)"
            assert redacted[field] == record[field], \
                f"Field '{field}' value should be unchanged"
    
    @given(
        record_fields=st.sets(st.sampled_from([
            'Id', 'Name', 'OwnerId', 'SecretField', 'ConfidentialData',
        ]), min_size=1, max_size=5),
    )
    @settings(max_examples=100, deadline=None)
    def test_disabled_fls_returns_all_fields(
        self,
        record_fields: set,
    ):
        """
        Property: When FLS disabled, all fields MUST be returned unchanged.
        
        **Feature: zero-config-production, Property 9: FLS Enforcement**
        **Validates: Requirements 6.4**
        """
        idx = _ensure_authz_index(force_reload=True)
        
        # Create a record with the generated fields
        record = {field: f"value_{field}" for field in record_fields}
        
        # Create FLS enforcer (disabled)
        enforcer = idx.FLSEnforcer(sf_client=None, enabled=False)
        
        # Act: Redact fields (should do nothing when disabled)
        redacted = enforcer.redact_fields(record, {'Id'})  # Even with limited readable_fields
        
        # Assert: All fields preserved when disabled
        assert redacted == record, \
            "When FLS disabled, record should be returned unchanged"
    
    @given(
        user_id=salesforce_user_id(),
        sobject=st.sampled_from(['Account', 'Contact', 'Opportunity']),
    )
    @settings(max_examples=100, deadline=None)
    def test_disabled_fls_get_readable_fields_returns_empty(
        self,
        user_id: str,
        sobject: str,
    ):
        """
        Property: When FLS disabled, get_readable_fields returns empty set.
        
        **Feature: zero-config-production, Property 9: FLS Enforcement**
        **Validates: Requirements 6.4**
        """
        idx = _ensure_authz_index(force_reload=True)
        
        # Create FLS enforcer (disabled)
        enforcer = idx.FLSEnforcer(sf_client=None, enabled=False)
        
        # Act: Get readable fields
        readable = enforcer.get_readable_fields(user_id, sobject)
        
        # Assert: Empty set when disabled (meaning all fields allowed)
        assert readable == set(), \
            "When FLS disabled, get_readable_fields should return empty set"



# =============================================================================
# Property 10: FLS Caching
# **Validates: Requirements 6.3**
# =============================================================================

class TestFLSCachingProperty:
    """
    Property 10: FLS Caching
    
    *For any* FLS permission lookup, the result SHALL be cached with 24-hour TTL,
    and subsequent lookups within TTL SHALL return cached results.
    
    **Feature: zero-config-production, Property 10: FLS Caching**
    **Validates: Requirements 6.3**
    """
    
    @given(
        user_id=salesforce_user_id(),
        sobject=st.sampled_from(['Account', 'Contact', 'Opportunity', 'Property__c']),
        readable_fields=st.sets(st.sampled_from([
            'Id', 'Name', 'OwnerId', 'CreatedDate', 'Description',
            'Phone', 'Email', 'Address', 'City', 'State',
        ]), min_size=1, max_size=8),
    )
    @settings(max_examples=100, deadline=None)
    def test_memory_cache_returns_same_result(
        self,
        user_id: str,
        sobject: str,
        readable_fields: set,
    ):
        """
        Property: Memory cache returns same result on subsequent calls.
        
        **Feature: zero-config-production, Property 10: FLS Caching**
        **Validates: Requirements 6.3**
        """
        from datetime import datetime
        idx = _ensure_authz_index(force_reload=True)
        
        # Create FLS enforcer (enabled)
        enforcer = idx.FLSEnforcer(sf_client=None, enabled=True)
        
        # Manually populate memory cache
        cache_key = f"{user_id}:{sobject}"
        enforcer._memory_cache[cache_key] = {'readable_fields': readable_fields}
        enforcer._memory_cache_timestamps[cache_key] = datetime.utcnow()
        
        # Act: Get cached FLS
        cached = enforcer._get_cached_fls(user_id, sobject)
        
        # Assert: Cached result matches what we stored
        assert cached == readable_fields, \
            f"Memory cache should return stored readable_fields"
    
    @given(
        user_id=salesforce_user_id(),
        sobject=st.sampled_from(['Account', 'Contact', 'Opportunity']),
        readable_fields=st.sets(st.sampled_from([
            'Id', 'Name', 'OwnerId', 'CreatedDate',
        ]), min_size=1, max_size=4),
    )
    @settings(max_examples=100, deadline=None)
    def test_expired_memory_cache_returns_none(
        self,
        user_id: str,
        sobject: str,
        readable_fields: set,
    ):
        """
        Property: Expired memory cache returns None.
        
        **Feature: zero-config-production, Property 10: FLS Caching**
        **Validates: Requirements 6.3**
        """
        from datetime import datetime, timedelta
        idx = _ensure_authz_index(force_reload=True)
        FLS_CACHE_TTL_HOURS = idx.FLS_CACHE_TTL_HOURS
        
        # Create FLS enforcer (enabled)
        enforcer = idx.FLSEnforcer(sf_client=None, enabled=True)
        
        # Manually populate memory cache with expired timestamp
        cache_key = f"{user_id}:{sobject}"
        enforcer._memory_cache[cache_key] = {'readable_fields': readable_fields}
        # Set timestamp to be older than TTL
        enforcer._memory_cache_timestamps[cache_key] = datetime.utcnow() - timedelta(hours=FLS_CACHE_TTL_HOURS + 1)
        
        # Mock DynamoDB to return nothing (so we only test memory cache expiry)
        with patch.object(idx, 'dynamodb') as mock_dynamodb:
            mock_table = MagicMock()
            mock_dynamodb.Table.return_value = mock_table
            mock_table.get_item.return_value = {}  # No DynamoDB cache
            
            # Act: Get cached FLS
            cached = enforcer._get_cached_fls(user_id, sobject)
            
            # Assert: Expired cache returns None
            assert cached is None, \
                "Expired memory cache should return None"
    
    @given(
        user_id=salesforce_user_id(),
        sobject=st.sampled_from(['Account', 'Contact', 'Opportunity']),
        readable_fields=st.sets(st.sampled_from([
            'Id', 'Name', 'OwnerId', 'CreatedDate', 'Description',
        ]), min_size=1, max_size=5),
    )
    @settings(max_examples=100, deadline=None)
    def test_cache_stores_correct_data(
        self,
        user_id: str,
        sobject: str,
        readable_fields: set,
    ):
        """
        Property: Cache stores correct user, sobject, and fields.
        
        **Feature: zero-config-production, Property 10: FLS Caching**
        **Validates: Requirements 6.3**
        """
        idx = _ensure_authz_index(force_reload=True)
        
        # Create FLS enforcer (enabled)
        enforcer = idx.FLSEnforcer(sf_client=None, enabled=True)
        
        # Mock DynamoDB
        with patch.object(idx, 'dynamodb') as mock_dynamodb:
            mock_table = MagicMock()
            mock_dynamodb.Table.return_value = mock_table
            
            # Act: Cache FLS
            enforcer._cache_fls(user_id, sobject, readable_fields)
            
            # Assert: put_item was called with correct data
            mock_table.put_item.assert_called_once()
            call_args = mock_table.put_item.call_args[1]
            item = call_args['Item']
            
            assert item['cacheKey'] == f"{user_id}:{sobject}", \
                "Cache should store correct data"
            assert item['userId'] == user_id, \
                "Cache should store correct data"
            assert item['sobject'] == sobject, \
                "Cache should store correct data"
            assert set(item['readableFields']) == readable_fields, \
                "Cache should store correct data"
            assert 'ttl' in item, \
                "Cache should store correct data"
    
    @given(
        user_id=salesforce_user_id(),
        sobject=st.sampled_from(['Account', 'Contact', 'Opportunity']),
    )
    @settings(max_examples=100, deadline=None)
    def test_cache_invalidation_clears_memory_cache(
        self,
        user_id: str,
        sobject: str,
    ):
        """
        Property: Cache invalidation clears memory cache.
        
        **Feature: zero-config-production, Property 10: FLS Caching**
        **Validates: Requirements 6.3**
        """
        from datetime import datetime
        idx = _ensure_authz_index(force_reload=True)
        
        # Create FLS enforcer (enabled)
        enforcer = idx.FLSEnforcer(sf_client=None, enabled=True)
        
        # Populate memory cache
        cache_key = f"{user_id}:{sobject}"
        enforcer._memory_cache[cache_key] = {'readable_fields': {'Id', 'Name'}}
        enforcer._memory_cache_timestamps[cache_key] = datetime.utcnow()
        
        # Mock DynamoDB
        with patch.object(idx, 'dynamodb') as mock_dynamodb:
            mock_table = MagicMock()
            mock_dynamodb.Table.return_value = mock_table
            
            # Act: Invalidate cache
            result = enforcer.invalidate_cache(user_id, sobject)
            
            # Assert: Memory cache cleared
            assert cache_key not in enforcer._memory_cache, \
                "Memory cache should be cleared after invalidation"
            assert result is True, \
                "Memory cache should be cleared after invalidation"
