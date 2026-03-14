# Field-Level Security (FLS) - POC Limitation

## Current Implementation (Phase 1 POC)

**Status**: FLS enforcement is **NOT IMPLEMENTED** in the POC.

### Assumptions
- All fields are readable if the user can see the record
- No field-level permission checking is performed
- No FLS profile tags are computed or stored in chunk metadata

### Rationale
1. **Simplicity**: Reduces complexity for initial POC validation
2. **Performance**: Eliminates additional Salesforce API calls for permission checks
3. **Scope**: POC focuses on proving core RAG functionality and row-level security

### Impact
- Users who can access a record can see ALL indexed fields
- No redacted chunk variants for sensitive fields
- Simplified authorization model (sharing buckets only)

## Phase 3 Enhancement Plan

### Full FLS Implementation
When FLS is implemented in Phase 3, the following will be added:

1. **FLS Profile Tag Computation**
   - Query user's profile and permission sets
   - For each field in IndexConfiguration__mdt, check read permission
   - Build FLS tags in format: `{objectApiName}.{fieldApiName}:{profileId}`
   - Use Salesforce Composite API to batch FLS checks

2. **Chunk Metadata Enhancement**
   - Store FLS tags in chunk metadata: `flsProfileTags: ["Account.Revenue__c:00e123", ...]`
   - Create redacted chunk variants for sensitive fields
   - Store both full and redacted versions in index

3. **Post-Filter Validation**
   - During retrieval, check if user's FLS tags match chunk's required tags
   - Return redacted variant if user lacks field access
   - Filter out chunks entirely if all content is restricted

4. **Caching Strategy**
   - Cache FLS tags per user with 24-hour TTL (same as sharing buckets)
   - Invalidate cache when user's profile or permission sets change
   - Cache field permission metadata per object type

### API Changes Required
```python
def compute_fls_profile_tags(user_id: str, access_token: str) -> List[str]:
    """
    Compute FLS profile tags for a user.
    
    Phase 3 implementation will:
    1. Query user's profile and permission sets
    2. Query field permissions for configured objects
    3. Build FLS tags for accessible fields
    """
    # Query user profile and permission sets
    user_info = get_user_info(user_id, access_token)
    profile_id = user_info.get('ProfileId')
    
    # Query permission set assignments
    perm_sets = get_user_permission_sets(user_id, access_token)
    
    # Query field permissions using Salesforce Metadata API
    fls_tags = []
    for obj_config in get_index_configurations():
        for field in obj_config['fields']:
            if has_field_access(profile_id, perm_sets, obj_config['object'], field):
                fls_tags.append(f"{obj_config['object']}.{field}:{profile_id}")
    
    return fls_tags
```

### Testing Requirements
- Test with users having different profiles (Standard, Sales Manager, Admin)
- Test with users having additional permission sets
- Verify redacted chunks are returned for restricted fields
- Verify no data leakage through citations or previews

### Documentation Updates
- Update API documentation to reflect FLS enforcement
- Update admin guide with FLS configuration instructions
- Document how to troubleshoot FLS-related access issues

## Current Code Location
The placeholder FLS function is in `lambda/authz/index.py`:
```python
def compute_fls_profile_tags(user_id: str, access_token: str) -> List[str]:
    """
    Compute FLS (Field-Level Security) profile tags for a user.
    
    For POC: This is a placeholder. FLS enforcement is skipped.
    Phase 3 will implement full FLS checking.
    """
    print(f"Skipping FLS computation for user {user_id} (POC limitation)")
    return []
```

## Migration Path
When implementing Phase 3:
1. Replace the placeholder `compute_fls_profile_tags()` function
2. Update chunk metadata schema to include FLS tags
3. Update chunking Lambda to create redacted variants
4. Update retrieval Lambda to filter based on FLS tags
5. Update cache schema to store FLS tags
6. Run full re-indexing of all data with FLS metadata

## References
- Requirements: 2.2, 2.3
- Design Document: Section "5. AuthZ Sidecar Lambda"
- Tasks: 4.2, 27.3 (Phase 3)
