# Phase 2: Agent Actions - Salesforce Metadata

This directory contains Salesforce metadata for Phase 2 Agent Actions functionality, which enables AI agents to create and update Salesforce records with two-step confirmation.

## Components Overview

### Custom Objects

#### AI_Action_Audit__c
Audit log for all agent-driven actions. Tracks who executed what action, when, and whether it succeeded.

**Location:** `objects/AI_Action_Audit__c.object`

**Key Features:**
- Private sharing model (admin-only access)
- Encrypted storage for sensitive inputs
- Indexed fields for efficient reporting
- Automatic audit trail via CreatedDate

**Use Cases:**
- Compliance and audit reporting
- Troubleshooting failed actions
- Usage analytics and monitoring
- Security incident investigation

### Custom Metadata Types

#### ActionEnablement__mdt
Configuration for agent actions. Controls which actions are enabled, rate limits, and execution parameters.

**Location:** `metadata/ActionEnablement__mdt.xml`

**Key Features:**
- Deployable across orgs (sandbox → production)
- Runtime configuration without code changes
- JSON schema validation for inputs/outputs
- Flexible Flow or Apex execution

**Use Cases:**
- Enable/disable actions without code deployment
- Configure rate limits per action
- Define input validation schemas
- Control confirmation requirements

### Custom Metadata Records

#### ActionEnablement.Create_Opportunity
Configuration for creating Opportunity records via agent.

**Location:** `customMetadata/ActionEnablement.Create_Opportunity.md-meta.xml`

**Configuration:**
- Action Name: `create_opportunity`
- Flow: `Create_Opportunity_Flow`
- Rate Limit: 20 per user per day
- Requires Confirmation: Yes
- Allowed Fields: Name, AccountId, Amount, CloseDate, StageName, Description, OwnerId

#### ActionEnablement.Update_Opportunity_Stage
Configuration for updating Opportunity stage via agent.

**Location:** `customMetadata/ActionEnablement.Update_Opportunity_Stage.md-meta.xml`

**Configuration:**
- Action Name: `update_opportunity_stage`
- Flow: `Update_Opportunity_Stage_Flow`
- Rate Limit: 50 per user per day
- Requires Confirmation: Yes
- Allowed Fields: StageName, Probability

### Permission Sets

#### AI_Agent_Actions_Editor
Grants permissions to create and update records via agent actions.

**Location:** `permissionsets/AI_Agent_Actions_Editor.permissionset-meta.xml`

**Permissions:**
- Opportunity: Create, Edit, Read
- Account: Read (for lookup validation)
- All standard Opportunity fields: Edit, Read

**Assignment:**
- Assign to pilot users only
- Review assignments regularly
- Remove if issues arise

## Directory Structure

```
salesforce/
├── objects/
│   ├── AI_Search_Export_Error__c.object      # Phase 1
│   └── AI_Action_Audit__c.object              # Phase 2 ✓
├── metadata/
│   ├── AI_Search_Config__mdt.xml              # Phase 1
│   └── ActionEnablement__mdt.xml              # Phase 2 ✓
├── customMetadata/
│   ├── ActionEnablement.Create_Opportunity.md-meta.xml           # Phase 2 ✓
│   └── ActionEnablement.Update_Opportunity_Stage.md-meta.xml     # Phase 2 ✓
├── permissionsets/
│   └── AI_Agent_Actions_Editor.permissionset-meta.xml            # Phase 2 ✓
├── deploy-phase2.sh                           # Deployment script
├── verify-phase2-deployment.sh                # Verification script
├── PHASE2_DEPLOYMENT.md                       # Deployment guide
└── PHASE2_README.md                           # This file
```

## Deployment

### Quick Start

```bash
# Deploy all Phase 2 components
cd salesforce
./deploy-phase2.sh <org-alias>

# Verify deployment
./verify-phase2-deployment.sh <org-alias>

# Assign permission set to pilot user
sfdx force:user:permset:assign -n AI_Agent_Actions_Editor -u pilot.user@company.com -o <org-alias>
```

### Detailed Instructions

See [PHASE2_DEPLOYMENT.md](./PHASE2_DEPLOYMENT.md) for comprehensive deployment instructions, including:
- Prerequisites
- Step-by-step deployment
- Post-deployment configuration
- Verification tests
- Rollback procedures
- Troubleshooting

## Configuration

### Enable/Disable Actions

To disable an action without code changes:

1. Navigate to Setup → Custom Metadata Types → Action Enablement → Manage Records
2. Click on the action (e.g., "Create Opportunity")
3. Click Edit
4. Uncheck "Enabled"
5. Save

The action will be immediately disabled for all users.

### Adjust Rate Limits

To change rate limits:

1. Navigate to Setup → Custom Metadata Types → Action Enablement → Manage Records
2. Click on the action
3. Click Edit
4. Update "Max Per User Per Day" field
5. Save

Changes take effect immediately.

### Add New Actions

To add a new action:

1. Create a new ActionEnablement__mdt record with:
   - Unique ActionName__c
   - FlowName__c or ApexMethod__c
   - InputSchemaJson__c (JSON schema)
   - OutputSchemaJson__c (JSON schema)
   - AllowedFields__c (comma-separated)
2. Deploy the metadata record
3. Implement the corresponding Flow or Apex method
4. Test with pilot users

## Monitoring

### Audit Reports

Create reports on AI_Action_Audit__c:

**Daily Action Count by Action Name:**
```
Report Type: AI Action Audits
Group By: Action Name, Created Date (Day)
Show: Count of Records
```

**Failure Rate by Action:**
```
Report Type: AI Action Audits
Group By: Action Name, Success
Show: Count of Records
Filter: Success = False
```

**Top Users by Action Count:**
```
Report Type: AI Action Audits
Group By: User, Action Name
Show: Count of Records
Sort By: Count (Descending)
```

### CloudWatch Integration

Phase 2 also includes CloudWatch dashboards for:
- Action execution latency
- Success/failure rates
- Rate limit rejections
- Top users and objects

See Task 20 for CloudWatch setup.

## Security

### Data Protection

- **Encrypted Storage:** InputsJson__c uses Platform Encryption
- **Hash Storage:** InputsHash__c stores SHA-256 hashes for PII
- **Private Sharing:** Only admins can view audit records
- **Field-Level Security:** Enforced via permission sets

### Access Control

- **Permission Set:** Required for action execution
- **Rate Limiting:** Prevents abuse (configurable per action)
- **Two-Step Confirmation:** Required for all actions (configurable)
- **Audit Trail:** All actions logged with user, timestamp, inputs

### Best Practices

1. **Assign permission set to pilot users only**
2. **Review audit logs regularly**
3. **Monitor rate limit rejections**
4. **Test actions in sandbox before production**
5. **Use kill switch (Enabled__c = false) if issues arise**

## Testing

### Unit Tests

Test action configuration:

```bash
# Query action configurations
sfdx force:data:soql:query -u <org-alias> -q "SELECT ActionName__c, Enabled__c, MaxPerUserPerDay__c FROM ActionEnablement__mdt"

# Verify permission set
sfdx force:data:soql:query -u <org-alias> -q "SELECT Id, Name FROM PermissionSet WHERE Name = 'AI_Agent_Actions_Editor'"
```

### Integration Tests

Test end-to-end action execution (requires Phase 2 Lambda and LWC):

1. Submit action request via LWC
2. Verify preview displays correctly
3. Confirm action
4. Verify record created/updated
5. Check audit log entry

See Task 23 for comprehensive acceptance testing.

## Troubleshooting

### Common Issues

**Issue:** Permission set assignment fails  
**Solution:** Ensure user has base Opportunity permissions via profile

**Issue:** Encrypted field not accessible  
**Solution:** Enable Platform Encryption or change field type to LongTextArea

**Issue:** Metadata records not visible  
**Solution:** Deploy metadata type before records

**Issue:** Action execution fails with "Action disabled"  
**Solution:** Check Enabled__c field in ActionEnablement__mdt

### Support

For issues or questions:
- Review [PHASE2_DEPLOYMENT.md](./PHASE2_DEPLOYMENT.md)
- Check Salesforce Setup Audit Trail
- Review CloudWatch logs (Lambda execution)
- Consult design document: `.kiro/specs/salesforce-ai-search-poc/design.md`

## Next Steps

After deploying Phase 2 metadata:

1. **Task 16:** Implement Agent Action Flows
   - Create Create_Opportunity_Flow
   - Create Update_Opportunity_Stage_Flow
   - Test with different user contexts

2. **Task 17:** Implement Action Lambda
   - Deploy Lambda function
   - Configure API Gateway endpoint
   - Test action execution

3. **Task 19:** Extend LWC
   - Add action preview modal
   - Implement confirmation flow
   - Test end-to-end

4. **Task 20:** Set up monitoring
   - Create CloudWatch dashboards
   - Configure alarms
   - Create Salesforce reports

## References

- **Requirements:** `.kiro/specs/salesforce-ai-search-poc/requirements.md` (Requirements 13-22)
- **Design:** `.kiro/specs/salesforce-ai-search-poc/design.md` (Phase 2 sections)
- **Tasks:** `.kiro/specs/salesforce-ai-search-poc/tasks.md` (Tasks 15-24)
- **Salesforce Metadata API:** https://developer.salesforce.com/docs/atlas.en-us.api_meta.meta/api_meta/
- **SFDX CLI:** https://developer.salesforce.com/tools/sfdxcli

## Version History

- **v1.0** (2025-11-13): Initial Phase 2 metadata creation
  - AI_Action_Audit__c custom object
  - ActionEnablement__mdt custom metadata type
  - Initial action configurations (create_opportunity, update_opportunity_stage)
  - AI_Agent_Actions_Editor permission set
