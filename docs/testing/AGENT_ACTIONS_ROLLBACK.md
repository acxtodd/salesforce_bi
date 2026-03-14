# Agent Actions Rollback Procedures

## Overview

This document provides step-by-step procedures for disabling and rolling back AI Agent Actions in emergency situations. The rollback mechanisms are designed to quickly disable action capabilities while preserving read-only search and answer functionality.

## Table of Contents

1. [Quick Kill Switch](#quick-kill-switch)
2. [Gradual Rollback](#gradual-rollback)
3. [AWS-Side Disabling](#aws-side-disabling)
4. [Recovery Procedures](#recovery-procedures)
5. [Verification Steps](#verification-steps)
6. [Troubleshooting](#troubleshooting)

---

## Quick Kill Switch

Use this procedure for immediate emergency shutdown of all agent actions.

### Step 1: Disable Actions via Metadata (Immediate)

**Time to Effect:** < 5 minutes

**Method: Manual Update via Setup (Required)**
1. Navigate to **Setup** → **Custom Metadata Types** → **Action Enablement**
2. Click **Manage Records**
3. For each action record:
   - Click **Edit**
   - Uncheck **Enabled__c**
   - Click **Save**

**Note:** The Admin UI can show current settings and provide update instructions, but cannot directly update Custom Metadata from Lightning context due to Salesforce security restrictions. Manual update via Setup is required.

**Result:** All action requests will be rejected with "Action temporarily unavailable" message within 5 minutes (metadata cache refresh time).

### Step 2: Remove Permission Sets (Within 10 minutes)

**Time to Effect:** Immediate upon completion

**Option A: Use Flow (Recommended)**
1. Navigate to **Setup** → **Flows**
2. Find and run **Remove AI Agent Actions Permission Set**
3. Read the warning message carefully
4. Check the confirmation checkbox
5. Click **Next** to execute
6. Review the result screen showing success/failure counts

**Option B: Use Developer Console**
1. Open **Developer Console**
2. Go to **Debug** → **Open Execute Anonymous Window**
3. Paste and execute:
```apex
List<ActionPermissionSetRemoval.RemovalResult> results = 
    ActionPermissionSetRemoval.removePermissionSetAssignments();
System.debug('Result: ' + results[0].message);
System.debug('Success: ' + results[0].successCount);
System.debug('Failures: ' + results[0].failureCount);
```
4. Check the debug log for results

**Option C: Manual Removal (Fallback)**
1. Navigate to **Setup** → **Permission Sets**
2. Click **AI_Agent_Actions_Editor**
3. Click **Manage Assignments**
4. Select all users
5. Click **Remove Assignments**

**Result:** Users immediately lose ability to execute actions, even if actions are re-enabled.

### Step 3: Unregister from Agentforce (Within 30 minutes)

**Time to Effect:** Immediate

1. Navigate to **Setup** → **Einstein** → **Agent Builder**
2. Select your AI agent
3. Go to **Actions** tab
4. For each agent action:
   - Click the action menu (⋮)
   - Select **Remove Action**
   - Confirm removal
5. Click **Save** and **Activate** the agent

**Result:** Agent will no longer suggest or attempt to execute actions.

---

## Gradual Rollback

Use this procedure for controlled rollback with monitoring.

### Phase 1: Reduce Rate Limits (Day 1)

1. Open **AI Agent Actions Admin** app
2. Reduce **Max Per User Per Day** to 5 for all actions
3. Monitor usage in CloudWatch and Salesforce reports
4. If issues persist, proceed to Phase 2

### Phase 2: Disable Specific Actions (Day 2-3)

1. Identify problematic actions from monitoring dashboards
2. Disable only those actions via metadata:
   - Set **Enabled__c = false** for problematic actions
3. Monitor for 24-48 hours
4. If issues persist, proceed to Phase 3

### Phase 3: Full Rollback (Day 4+)

Follow the [Quick Kill Switch](#quick-kill-switch) procedure above.

---

## AWS-Side Disabling

Use this procedure to disable actions at the AWS Lambda level.

### Method 1: Environment Variable Kill Switch (Recommended)

**Time to Effect:** < 2 minutes

1. Open AWS Console → Lambda
2. Navigate to the **Action Lambda** function (e.g., `ActionLambda` or similar)
3. Go to **Configuration** → **Environment variables**
4. Click **Edit**
5. Add or update:
   ```
   Key: ACTIONS_ENABLED
   Value: false
   ```
6. Click **Save**

**Result:** All action requests will be immediately rejected with 503 Service Unavailable and message: "Agent actions are temporarily unavailable. Please try again later or contact your administrator."

**Verification:**
```bash
aws lambda get-function-configuration \
  --function-name ActionLambda \
  --query 'Environment.Variables.ACTIONS_ENABLED'
```
Expected output: `"false"`

### Method 2: Verify Kill Switch Implementation

**Note:** The kill switch is already implemented in the Lambda code. This method is for verification only.

The Action Lambda handler includes this check at the beginning:
```python
# Kill switch check - disable all actions via environment variable
actions_enabled = os.environ.get("ACTIONS_ENABLED", "true").lower()
if actions_enabled == "false":
    LOGGER.warning("Actions are disabled via ACTIONS_ENABLED environment variable")
    return {
        "statusCode": 503,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "error": "service_unavailable",
            "message": "Agent actions are temporarily unavailable..."
        })
    }
```

To use this kill switch, simply set the environment variable as described in Method 1.

### Method 3: API Gateway Throttling

**Time to Effect:** Immediate

1. Open AWS Console → API Gateway
2. Select your Private API
3. Go to **Stages** → **prod**
4. Click on the **/action** resource
5. Enable **Throttling**
6. Set **Rate** to 0 requests/second
7. Set **Burst** to 0
8. Click **Save Changes**

**Result:** All action requests will receive 429 Too Many Requests.

---

## Recovery Procedures

Use these procedures to re-enable agent actions after issues are resolved.

### Step 1: Re-enable Actions via Metadata

1. Navigate to **Setup** → **Custom Metadata Types** → **Action Enablement**
2. Click **Manage Records**
3. For each action to re-enable:
   - Click **Edit**
   - Check **Enabled__c**
   - Click **Save**

### Step 2: Reassign Permission Sets

**Important:** Only assign to authorized pilot users initially.

1. Navigate to **Setup** → **Permission Sets**
2. Click **AI_Agent_Actions_Editor**
3. Click **Manage Assignments**
4. Click **Add Assignments**
5. Select authorized users
6. Click **Assign**

### Step 3: Re-register in Agentforce

1. Navigate to **Setup** → **Einstein** → **Agent Builder**
2. Select your AI agent
3. Go to **Actions** tab
4. Click **New Action**
5. For each action:
   - Select **Apex** or **Flow** type
   - Choose the action (e.g., Create_Opportunity_Flow)
   - Configure inputs/outputs
   - Add examples
   - Click **Save**
6. Click **Activate** the agent

### Step 4: AWS-Side Re-enabling

**Method 1: Environment Variable**
1. Open AWS Console → Lambda → Action Lambda
2. Go to **Configuration** → **Environment variables**
3. Update `ACTIONS_ENABLED=true`
4. Click **Save**

**Method 2: API Gateway Throttling**
1. Open AWS Console → API Gateway
2. Select your Private API → Stages → prod → /action
3. Disable **Throttling** or set appropriate limits
4. Click **Save Changes**

### Step 5: Gradual Re-enablement

1. Start with 1-2 pilot users
2. Monitor for 24 hours using:
   - CloudWatch dashboards (Agent Actions)
   - Salesforce reports (AI_Action_Audit__c)
3. If stable, expand to 5-10 users
4. Monitor for another 24-48 hours
5. Gradually expand to full pilot group

---

## Verification Steps

After executing rollback or recovery, verify the changes:

### Verify Actions are Disabled

1. **Test from LWC:**
   - Log in as a test user
   - Try to execute an action
   - Expected: "Action temporarily unavailable" message

2. **Check Metadata:**
   ```sql
   SELECT ActionName__c, Enabled__c, MaxPerUserPerDay__c 
   FROM ActionEnablement__mdt
   ```
   - Expected: All `Enabled__c = false`

3. **Check Permission Sets:**
   ```sql
   SELECT COUNT() 
   FROM PermissionSetAssignment 
   WHERE PermissionSet.Name = 'AI_Agent_Actions_Editor'
   ```
   - Expected: Count = 0

4. **Check AWS Lambda:**
   - View Lambda environment variables
   - Expected: `ACTIONS_ENABLED=false`

5. **Check CloudWatch Metrics:**
   - Open Agent Actions dashboard
   - Expected: Action count drops to 0

### Verify Actions are Re-enabled

1. **Test from LWC:**
   - Log in as authorized pilot user
   - Execute a test action (e.g., create test opportunity)
   - Expected: Preview modal → Confirm → Success toast

2. **Check Audit Log:**
   ```sql
   SELECT Id, ActionName__c, Success__c, CreatedDate 
   FROM AI_Action_Audit__c 
   WHERE CreatedDate = TODAY 
   ORDER BY CreatedDate DESC
   ```
   - Expected: Recent successful action records

3. **Check CloudWatch:**
   - View Agent Actions dashboard
   - Expected: Action count > 0, success rate > 95%

---

## Troubleshooting

### Issue: Actions still executing after disabling metadata

**Cause:** Metadata cache not refreshed

**Solution:**
1. Wait 5-10 minutes for cache to expire
2. Or, restart the Action Lambda:
   ```bash
   aws lambda update-function-configuration \
     --function-name ActionLambda \
     --environment Variables={FORCE_REFRESH=true}
   ```

### Issue: Permission set removal fails for some users

**Cause:** Users have active sessions or are system administrators

**Solution:**
1. Check the error messages in the Flow result screen
2. For system administrators, manually remove via Setup
3. For active sessions, wait for session timeout (2 hours) or force logout

### Issue: Actions re-enabled but users can't execute

**Cause:** Permission set not reassigned

**Solution:**
1. Verify user has AI_Agent_Actions_Editor permission set:
   ```sql
   SELECT Assignee.Username 
   FROM PermissionSetAssignment 
   WHERE PermissionSet.Name = 'AI_Agent_Actions_Editor' 
   AND AssigneeId = '<userId>'
   ```
2. If missing, reassign via Setup → Permission Sets

### Issue: AWS Lambda still rejecting requests

**Cause:** Environment variable not updated or API Gateway throttling

**Solution:**
1. Check Lambda environment variables
2. Check API Gateway throttling settings
3. Check CloudWatch Logs for actual error messages

### Issue: Agentforce still suggesting actions

**Cause:** Agent not re-activated after removing actions

**Solution:**
1. Go to Agent Builder
2. Click **Activate** to publish changes
3. Wait 5 minutes for changes to propagate

---

## Rollback Decision Matrix

| Severity | Scope | Recommended Action | Timeline |
|----------|-------|-------------------|----------|
| **Critical** | All actions failing | Quick Kill Switch (All 3 steps) | < 15 min |
| **High** | One action causing data corruption | Disable specific action via metadata | < 5 min |
| **Medium** | High error rate (>20%) | Reduce rate limits, monitor | 1-2 hours |
| **Low** | User complaints about UX | Gradual rollback, investigate | 1-2 days |

---

## Emergency Contacts

| Role | Contact | Escalation Path |
|------|---------|-----------------|
| **Primary On-Call** | DevOps Team | Slack: #ai-search-oncall |
| **Salesforce Admin** | SF Admin Team | Email: sf-admin@company.com |
| **AWS Admin** | Cloud Ops | PagerDuty: AWS-Critical |
| **Product Owner** | Product Team | Slack: #ai-search-product |

---

## Rollback Checklist

Use this checklist during rollback execution:

### Pre-Rollback
- [ ] Identify the issue and severity
- [ ] Notify stakeholders via Slack/email
- [ ] Take screenshots of current state
- [ ] Export recent audit logs for investigation

### During Rollback
- [ ] Execute appropriate rollback procedure
- [ ] Monitor CloudWatch for confirmation
- [ ] Verify actions are disabled (test from LWC)
- [ ] Document actions taken and timestamps

### Post-Rollback
- [ ] Verify read-only search still works
- [ ] Notify users of temporary action unavailability
- [ ] Investigate root cause
- [ ] Create incident report
- [ ] Plan recovery timeline

### Recovery
- [ ] Fix root cause issue
- [ ] Test in sandbox environment
- [ ] Execute gradual re-enablement
- [ ] Monitor for 48 hours
- [ ] Document lessons learned

---

## Appendix: Useful Queries

### Check Current Action Status
```sql
SELECT ActionName__c, Enabled__c, MaxPerUserPerDay__c, FlowName__c
FROM ActionEnablement__mdt
ORDER BY ActionName__c
```

### Check Recent Action Executions
```sql
SELECT ActionName__c, Success__c, Error__c, CreatedDate, UserId__r.Username
FROM AI_Action_Audit__c
WHERE CreatedDate = LAST_N_DAYS:7
ORDER BY CreatedDate DESC
LIMIT 100
```

### Check Permission Set Assignments
```sql
SELECT Assignee.Name, Assignee.Username, Assignee.Email, Assignee.IsActive
FROM PermissionSetAssignment
WHERE PermissionSet.Name = 'AI_Agent_Actions_Editor'
ORDER BY Assignee.Name
```

### Check Action Failure Rate
```sql
SELECT ActionName__c, 
       COUNT(Id) Total,
       SUM(CASE WHEN Success__c = true THEN 1 ELSE 0 END) Successes,
       SUM(CASE WHEN Success__c = false THEN 1 ELSE 0 END) Failures
FROM AI_Action_Audit__c
WHERE CreatedDate = TODAY
GROUP BY ActionName__c
```

---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-11-14 | AI Search Team | Initial rollback procedures |

---

## Related Documentation

- [Agent Actions Implementation Summary](../salesforce/agentforce/IMPLEMENTATION-SUMMARY.md)
- [Action Enablement Admin Guide](../salesforce/lwc/README.md)
- [Monitoring Implementation](MONITORING_IMPLEMENTATION.md)
- [Security Red Team Tests](SECURITY_RED_TEAM_TESTS.md)
