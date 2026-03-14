# Handoff Notes - Task 24.2.3 Deployment

**Date**: 2025-11-17  
**Session End Time**: ~3:15 PM PST  
**Task**: 24.2.3 Deploy all AWS stacks  
**Status**: BLOCKED - Bedrock does not support VPC-only managed OpenSearch domains (see `docs/SERVERLESS_MIGRATION_PLAN.md`)

> **Strategy**: We are abandoning the managed-domain approach and migrating SearchStack to OpenSearch Serverless (AOSS) so Bedrock Knowledge Bases can be provisioned while keeping private networking.

---

## Current Situation

### What's Complete ✅
- NetworkStack: Deployed successfully (CREATE_COMPLETE)
- DataStack: Deployed successfully (CREATE_COMPLETE)
- CDK configuration: Correct and validated
- Code changes: All necessary updates made to lib/search-stack.ts, lib/monitoring-stack.ts, bin/app.ts

### What's Blocked ❌
- SearchStack: Fails at KnowledgeBase resource creation
- IngestionStack: Waiting for SearchStack
- ApiStack: Waiting for SearchStack
- MonitoringStack: Waiting for ApiStack

### Current Blocker
**IAM Permissions**: User `acx-todd-cli` (arn:aws:iam::382211616288:user/acx-todd-cli) lacks permission to create Bedrock Knowledge Bases.

**Error Message**:
```
Resource handler returned message: "Access denied for operation 'CreateKnowledgeBase'."
(HandlerErrorCode: AccessDenied)
```

---

## What Happened This Session

### Timeline of Events

1. **12:35 PM** - First deployment attempt
   - Failed: OpenSearch domain not deleted from previous attempt
   - Security group had dependent resources

2. **1:55 PM** - Second deployment attempt
   - Failed: CloudFormation rejected `type: "OPENSEARCH"` as invalid enum
   - Root cause: Thought it was a schema update issue

3. **2:00 PM - 2:30 PM** - Investigation and correction
   - Discovered AWS announced managed OpenSearch support in March 2025
   - Prepared AWS Support case (AWS_SUPPORT_CASE.md)
   - Documented blocker (DEPLOYMENT_BLOCKER.md)
   - User confirmed issue was "self-inflicted" and corrected

4. **2:55 PM** - Third deployment attempt
   - Configuration corrected
   - OpenSearch domain started creating successfully
   - Failed at KnowledgeBase creation: IAM permissions denied

5. **3:08 PM** - New blocker identified
   - IAM user lacks `bedrock:CreateKnowledgeBase` permission
   - Documented in IAM_PERMISSIONS_BLOCKER.md
   - Session wrapped for handoff

### Key Learnings

1. **CloudFormation Schema Issue Was Resolved**: The `type: "OPENSEARCH"` configuration is correct per AWS March 2025 update
2. **IAM Permissions Are Missing**: This is a new, separate blocker
3. **OpenSearch Domain Cleanup**: Takes 10-15 minutes and must complete before redeployment
4. **Stack Dependencies**: SearchStack must complete before other stacks can deploy

---

## Files Created/Modified This Session

### Documentation Created
- ✅ **IAM_PERMISSIONS_BLOCKER.md** - Current blocker with resolution steps (PRIMARY REFERENCE)
- ✅ **DEPLOYMENT_BLOCKER.md** - Previous CloudFormation schema issue (resolved, kept for history)
- ✅ **AWS_SUPPORT_CASE.md** - Support case template (not needed, kept for reference)
- ✅ **HANDOFF_NOTES.md** - This file
- ✅ **deployment-status.md** - Deployment progress tracking
- ✅ **check-deployment.sh** - Helper script for checking stack status

### Code Modified
- ✅ **lib/search-stack.ts** - Configured for managed OpenSearch with correct Bedrock KB settings
- ✅ **lib/monitoring-stack.ts** - Updated to use managed OpenSearch metrics
- ✅ **bin/app.ts** - Updated MonitoringStack to pass openSearchDomain
- ✅ **.kiro/specs/salesforce-ai-search-poc/tasks.md** - Updated task 24.2.3 status

### Configuration Validated
- ✅ CDK synth completes successfully
- ✅ CloudFormation templates generated correctly
- ✅ TypeScript compilation passes
- ✅ All dependencies resolved

---

## Immediate Next Steps (For Next Agent)

### Step 1: Add IAM Permissions (5 minutes)

**Option A: Use Managed Policy (Recommended)**
```bash
aws iam attach-user-policy \
  --user-name acx-todd-cli \
  --policy-arn arn:aws:iam::aws:policy/AmazonBedrockFullAccess
```

**Option B: Use Custom Policy**
See IAM_PERMISSIONS_BLOCKER.md for detailed policy JSON and creation steps.

**Verify Permissions**:
```bash
aws bedrock list-knowledge-bases --no-cli-pager
# Should return list without AccessDenied error
```

### Step 2: Clean Up Failed Resources (20 minutes)

**CRITICAL**: Stack is in ROLLBACK_FAILED state and requires manual cleanup.

```bash
# 1. Delete OpenSearch domain first (this will release the security group)
aws opensearch delete-domain --domain-name salesforce-ai-search

# 2. Wait for domain deletion (10-15 minutes)
# Check status periodically:
aws opensearch list-domain-names --query 'DomainNames[?contains(DomainName, `salesforce`)].DomainName'
# Should return empty array [] when complete

# 3. After domain is deleted, delete the failed stack
aws cloudformation delete-stack --stack-name SalesforceAISearch-Search-dev

# 4. Verify stack deletion
aws cloudformation describe-stacks --stack-name SalesforceAISearch-Search-dev 2>&1
# Should return "Stack does not exist" error when complete
```

**Why this order matters**: The OpenSearch domain has network interfaces attached to the security group. The security group cannot be deleted until the domain (and its network interfaces) are deleted first.

### Step 3: Deploy All Stacks (30 minutes)

```bash
# Deploy all 4 remaining stacks
npx cdk deploy SalesforceAISearch-Search-dev \
  SalesforceAISearch-Ingestion-dev \
  SalesforceAISearch-Api-dev \
  SalesforceAISearch-Monitoring-dev \
  --require-approval never \
  --no-cli-pager

# Monitor progress with helper script
./check-deployment.sh
```

**Expected Timeline**:
- SearchStack: ~15 minutes (OpenSearch domain creation is slowest)
- IngestionStack: ~5 minutes
- ApiStack: ~8 minutes
- MonitoringStack: ~3 minutes
- **Total**: ~30 minutes

### Step 4: Proceed to Task 24.2.4

Once all stacks are CREATE_COMPLETE:
- Capture stack outputs (API Gateway endpoint, API key, VPC endpoint service name)
- Save to DEPLOYMENT_OUTPUTS.md
- Continue with Salesforce metadata deployment (Task 24.3)

---

## Troubleshooting Guide

### If Deployment Fails Again

1. **Check Stack Events**:
```bash
aws cloudformation describe-stack-events \
  --stack-name SalesforceAISearch-Search-dev \
  --max-items 20 \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`]' \
  --output table
```

2. **Check OpenSearch Domain Status**:
```bash
aws opensearch describe-domain \
  --domain-name salesforce-ai-search \
  --query 'DomainStatus.{Processing:Processing,Deleted:Deleted,Created:Created}'
```

3. **Verify IAM Permissions**:
```bash
aws bedrock list-knowledge-bases
aws bedrock list-foundation-models
```

4. **Check Process Output**:
```bash
# If using background process
./check-deployment.sh
```

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "AlreadyExists" error | OpenSearch domain not deleted | Wait for domain deletion, check with `aws opensearch list-domain-names` |
| "AccessDenied" error | Missing IAM permissions | Add Bedrock permissions per IAM_PERMISSIONS_BLOCKER.md |
| "ValidationError" enum | Wrong storage type | Verify `type: "OPENSEARCH"` in lib/search-stack.ts |
| Stack stuck in ROLLBACK | Previous failure | Delete stack and redeploy |

---

## Environment Details

### AWS Account
- **Account ID**: 382211616288
- **Region**: us-west-2
- **IAM User**: acx-todd-cli

### Stack Names
- NetworkStack: SalesforceAISearch-Network-dev (✅ CREATE_COMPLETE)
- DataStack: SalesforceAISearch-Data-dev (✅ CREATE_COMPLETE)
- SearchStack: SalesforceAISearch-Search-dev (❌ BLOCKED)
- IngestionStack: SalesforceAISearch-Ingestion-dev (⏳ WAITING)
- ApiStack: SalesforceAISearch-Api-dev (⏳ WAITING)
- MonitoringStack: SalesforceAISearch-Monitoring-dev (⏳ WAITING)

### Key Resources
- OpenSearch Domain: salesforce-ai-search (needs to be created)
- VPC: vpc-07c536c5f97383753
- KMS Key: efd94c01-58e0-49bb-a507-dfdcf0ba2001
- Lambda Security Group: sg-028f6f3fb67ab50c2

---

## Success Criteria

Task 24.2.3 is complete when:
- ✅ All 6 stacks show CREATE_COMPLETE status
- ✅ OpenSearch domain is active and accessible
- ✅ Bedrock Knowledge Base is created and active
- ✅ All Lambda functions are deployed
- ✅ CloudWatch dashboards are created
- ✅ No errors in CloudFormation events

---

## References

### Primary Documentation
1. **IAM_PERMISSIONS_BLOCKER.md** - Current blocker and resolution (START HERE)
2. **.kiro/specs/salesforce-ai-search-poc/tasks.md** - Task tracking (Task 24.2.3)
3. **lib/search-stack.ts** - SearchStack configuration
4. **check-deployment.sh** - Deployment monitoring script

### Historical Context
- DEPLOYMENT_BLOCKER.md - Previous CloudFormation schema issue (resolved)
- AWS_SUPPORT_CASE.md - Support case template (not needed)
- deployment-status.md - Deployment progress log

### AWS Documentation
- Bedrock Knowledge Bases: https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html
- OpenSearch Service: https://docs.aws.amazon.com/opensearch-service/
- CDK Reference: https://docs.aws.amazon.com/cdk/api/v2/

---

## Contact/Escalation

If blocked for more than 1 hour:
1. Review IAM_PERMISSIONS_BLOCKER.md thoroughly
2. Verify all permissions are correctly applied
3. Check AWS Service Health Dashboard for us-west-2
4. Consider opening AWS Support case if Bedrock service issues suspected

---

## Final Notes (Updated Nov 18)

- Managed OpenSearch architecture is **retired**; Bedrock requires public endpoints and will not accept our VPC-only domain.
- All future work must follow `docs/SERVERLESS_MIGRATION_PLAN.md` to migrate SearchStack to OpenSearch Serverless.
- Complete the cleanup (delete domain → delete stack), apply the AOSS changes, then redeploy.
- After SearchStack succeeds, resume Task 24.2.4 and downstream tasks.

**Next Agent:** start with the migration plan, then the Quick Start cleanup steps.
