# Phase 2 Agent Actions Deployment Guide

This guide covers the deployment of Phase 2 Agent Actions metadata to Salesforce, including custom objects, metadata types, and permission sets.

## Overview

Phase 2 introduces agent-driven record creation and updates with two-step confirmation. The deployment includes:

1. **AI_Action_Audit__c** - Custom object for auditing all agent actions
2. **ActionEnablement__mdt** - Custom metadata type for action configuration
3. **AI_Agent_Actions_Editor** - Permission set for pilot users
4. **Initial Action Configurations** - Metadata records for create_opportunity and update_opportunity_stage

## Prerequisites

- SFDX CLI installed ([Installation Guide](https://developer.salesforce.com/tools/sfdxcli))
- Authenticated to target Salesforce org
- System Administrator access
- Phase 1 components already deployed

## Deployment Steps

### Option 1: Automated Deployment (Recommended)

Use the provided deployment script:

```bash
cd salesforce
./deploy-phase2.sh <org-alias>
```

Example:
```bash
./deploy-phase2.sh my-sandbox
```

### Option 2: Manual Deployment

#### Step 1: Deploy Custom Object

Deploy the AI_Action_Audit__c custom object:

```bash
sfdx force:source:deploy -u <org-alias> -p objects/AI_Action_Audit__c.object -w 10
```

**Verify:**
- Navigate to Setup → Object Manager → AI Action Audit
- Confirm all fields are present:
  - UserId__c (Lookup to User)
  - ActionName__c (Text 80, indexed)
  - InputsJson__c (Encrypted Text Long)
  - InputsHash__c (Text 64)
  - Records__c (Long Text Area)
  - Success__c (Checkbox)
  - Error__c (Long Text Area)
  - ChatSessionId__c (Text 80)
  - LatencyMs__c (Number)
- Confirm sharing model is Private

#### Step 2: Deploy Custom Metadata Type

Deploy the ActionEnablement__mdt custom metadata type:

```bash
sfdx force:source:deploy -u <org-alias> -p metadata/ActionEnablement__mdt.xml -w 10
```

**Verify:**
- Navigate to Setup → Custom Metadata Types → Action Enablement
- Confirm all fields are present:
  - ActionName__c (Text 80)
  - Enabled__c (Checkbox)
  - MaxPerUserPerDay__c (Number)
  - RequiresConfirm__c (Checkbox)
  - FlowName__c (Text 80)
  - ApexMethod__c (Text 120)
  - InputSchemaJson__c (Long Text Area)
  - OutputSchemaJson__c (Long Text Area)
  - AllowedFields__c (Long Text Area)

#### Step 3: Deploy Metadata Records

Deploy the initial action configuration records:

```bash
sfdx force:source:deploy -u <org-alias> -p customMetadata/ -w 10
```

**Verify:**
- Navigate to Setup → Custom Metadata Types → Action Enablement → Manage Records
- Confirm two records exist:
  - **Create Opportunity** (create_opportunity)
  - **Update Opportunity Stage** (update_opportunity_stage)
- Review configuration for each action

#### Step 4: Deploy Permission Set

Deploy the AI_Agent_Actions_Editor permission set:

```bash
sfdx force:source:deploy -u <org-alias> -p permissionsets/AI_Agent_Actions_Editor.permissionset-meta.xml -w 10
```

**Verify:**
- Navigate to Setup → Permission Sets → AI Agent Actions Editor
- Confirm object permissions:
  - Opportunity: Create, Edit, Read
  - Account: Read
- Confirm field permissions for Opportunity fields

#### Step 5: Assign Permission Set to Pilot Users

Assign the permission set to pilot users:

```bash
sfdx force:user:permset:assign -n AI_Agent_Actions_Editor -u <username> -o <org-alias>
```

Example:
```bash
sfdx force:user:permset:assign -n AI_Agent_Actions_Editor -u pilot.user@company.com -o my-sandbox
```

**Verify:**
- Navigate to Setup → Users → [User] → Permission Set Assignments
- Confirm AI Agent Actions Editor is assigned

## Post-Deployment Configuration

### 1. Review Action Enablement Settings

Navigate to Setup → Custom Metadata Types → Action Enablement → Manage Records

For each action, review and adjust:
- **Enabled__c**: Set to false to disable an action
- **MaxPerUserPerDay__c**: Adjust rate limits as needed
- **RequiresConfirm__c**: Keep true for safety (recommended)

### 2. Configure Additional Actions (Optional)

To add new actions:

1. Create a new ActionEnablement__mdt record
2. Define the action name, Flow/Apex method, and schemas
3. Deploy the metadata record
4. Implement the corresponding Flow or Apex method (see Task 16)

### 3. Set Up Monitoring

Create reports for AI_Action_Audit__c:

1. Navigate to Reports → New Report
2. Select "AI Action Audits" as report type
3. Create reports for:
   - Daily action counts by action name
   - Failure rates by action
   - Top users by action count
   - Recent errors

## Verification Tests

### Test 1: Custom Object Access

```bash
# Query AI_Action_Audit__c to verify object is accessible
sfdx force:data:soql:query -u <org-alias> -q "SELECT Id, Name FROM AI_Action_Audit__c LIMIT 1"
```

Expected: Query succeeds (may return 0 records if no actions executed yet)

### Test 2: Metadata Type Access

```bash
# Query ActionEnablement__mdt to verify metadata records
sfdx force:data:soql:query -u <org-alias> -q "SELECT DeveloperName, ActionName__c, Enabled__c FROM ActionEnablement__mdt"
```

Expected: Returns 2 records (Create_Opportunity, Update_Opportunity_Stage)

### Test 3: Permission Set Assignment

```bash
# Verify permission set assignment for a user
sfdx force:data:soql:query -u <org-alias> -q "SELECT AssigneeId, PermissionSet.Name FROM PermissionSetAssignment WHERE PermissionSet.Name = 'AI_Agent_Actions_Editor'"
```

Expected: Returns records for assigned users

## Rollback Procedures

### Emergency Rollback (Disable All Actions)

If issues arise, disable all actions immediately:

1. Navigate to Setup → Custom Metadata Types → Action Enablement → Manage Records
2. For each action, click Edit and set Enabled__c = false
3. Save changes

This disables action execution without affecting Phase 1 search/answer capabilities.

### Full Rollback (Remove Components)

To completely remove Phase 2 components:

```bash
# Remove permission set assignments
sfdx force:user:permset:assign -n AI_Agent_Actions_Editor -u <username> -o <org-alias> --remove

# Delete custom metadata records (via UI)
# Navigate to Setup → Custom Metadata Types → Action Enablement → Manage Records
# Delete each record

# Delete custom metadata type (via UI)
# Navigate to Setup → Custom Metadata Types → Action Enablement → Delete

# Delete permission set (via UI)
# Navigate to Setup → Permission Sets → AI Agent Actions Editor → Delete

# Delete custom object (via UI)
# Navigate to Setup → Object Manager → AI Action Audit → Delete
```

**Warning:** Deleting AI_Action_Audit__c will permanently delete all audit records.

## Troubleshooting

### Issue: Deployment fails with "Invalid field type"

**Cause:** Salesforce API version mismatch

**Solution:** Update package.xml version to match your org's API version:
```xml
<version>59.0</version>  <!-- Adjust as needed -->
```

### Issue: Permission set assignment fails

**Cause:** User doesn't have required base permissions

**Solution:** Ensure user has:
- Read access to Account object
- Create/Edit access to Opportunity object (via profile or other permission sets)

### Issue: Custom metadata records not visible

**Cause:** Metadata type not deployed before records

**Solution:** Deploy in correct order:
1. Custom metadata type definition
2. Custom metadata records

### Issue: Encrypted field not accessible

**Cause:** Platform Encryption not enabled

**Solution:** 
- Option 1: Enable Platform Encryption in your org
- Option 2: Change InputsJson__c field type from EncryptedText to LongTextArea (less secure)

## Security Considerations

### Data Protection

- **AI_Action_Audit__c** uses Private sharing model - only admins can view audit records
- **InputsJson__c** is encrypted at rest using Platform Encryption
- **InputsHash__c** stores SHA-256 hashes for PII-containing inputs

### Access Control

- **AI_Agent_Actions_Editor** permission set should only be assigned to pilot users
- Review permission set assignments regularly
- Monitor audit logs for unauthorized access attempts

### Rate Limiting

- Default rate limit: 20 actions per user per day (create_opportunity)
- Default rate limit: 50 actions per user per day (update_opportunity_stage)
- Adjust MaxPerUserPerDay__c based on usage patterns

## Next Steps

After successful deployment:

1. **Task 16**: Implement Agent Action Flows
   - Create Create_Opportunity_Flow
   - Create Update_Opportunity_Stage_Flow

2. **Task 17**: Implement Action Lambda and /action endpoint
   - Deploy Lambda function
   - Configure API Gateway endpoint

3. **Task 19**: Extend LWC for action preview and confirmation
   - Update ascendixAiSearch component
   - Add action preview modal

4. **Task 20**: Set up action monitoring and dashboards
   - Create CloudWatch dashboards
   - Configure alarms

## Support

For issues or questions:
- Review deployment logs: `sfdx force:source:deploy --help`
- Check Salesforce Setup Audit Trail for deployment history
- Consult Phase 2 design document: `.kiro/specs/salesforce-ai-search-poc/design.md`

## Appendix: Metadata Structure

### AI_Action_Audit__c Fields

| Field | Type | Purpose |
|-------|------|---------|
| UserId__c | Lookup(User) | User who executed the action |
| ActionName__c | Text(80) | Name of the action (e.g., create_opportunity) |
| InputsJson__c | EncryptedText | Full JSON of action inputs (encrypted) |
| InputsHash__c | Text(64) | SHA-256 hash of inputs (for PII cases) |
| Records__c | LongTextArea | JSON array of affected record IDs |
| Success__c | Checkbox | Whether action succeeded |
| Error__c | LongTextArea | Error message if action failed |
| ChatSessionId__c | Text(80) | Associated chat session ID |
| LatencyMs__c | Number | Action execution latency in milliseconds |

### ActionEnablement__mdt Fields

| Field | Type | Purpose |
|-------|------|---------|
| ActionName__c | Text(80) | Unique action identifier |
| Enabled__c | Checkbox | Whether action is enabled |
| MaxPerUserPerDay__c | Number | Daily rate limit per user |
| RequiresConfirm__c | Checkbox | Whether to require two-step confirmation |
| FlowName__c | Text(80) | Name of autolaunched Flow to invoke |
| ApexMethod__c | Text(120) | Apex invocable method (alternative to Flow) |
| InputSchemaJson__c | LongTextArea | JSON schema for input validation |
| OutputSchemaJson__c | LongTextArea | JSON schema for output structure |
| AllowedFields__c | LongTextArea | Comma-separated list of allowed fields |

### AI_Agent_Actions_Editor Permissions

**Object Permissions:**
- Opportunity: Create, Edit, Read
- Account: Read

**Field Permissions (Opportunity):**
- Name, AccountId, Amount, CloseDate, StageName, Probability, Description, OwnerId: Edit, Read
