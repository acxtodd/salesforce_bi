# Deployment Documentation Index

**Current Status**: Task 24.2.3 BLOCKED - Stack in ROLLBACK_FAILED state, requires manual cleanup  
**Last Updated**: 2025-11-17 4:45 PM PST

---

## 🚀 Start Here

**New to this deployment?** Read these in order:

1. **FINAL_STATUS.md** - Current state and immediate actions (5 min read) ⭐ START HERE
2. **docs/SERVERLESS_MIGRATION_PLAN.md** - **Strategy: migrate SearchStack to OpenSearch Serverless**
3. **QUICK_START.md** - Cleanup + redeploy steps (5 min read)
4. **IAM_PERMISSIONS_BLOCKER.md** - Prior IAM issue (reference)
5. **HANDOFF_NOTES.md** - Full session context (15 min read)

---

## 🧭 Current Strategy

- Bedrock Knowledge Bases cannot use VPC-only managed OpenSearch domains; AWS requires the managed cluster to be public.
- To keep networking private, we are **switching SearchStack to OpenSearch Serverless (AOSS)**. All work should follow `docs/SERVERLESS_MIGRATION_PLAN.md` until Task 24.2.3 is complete.
- Managed-domain deployment is on hold; do not attempt to redeploy it.

---

## 📋 Document Guide

### Immediate Action Required
| Document | Purpose | Priority |
|----------|---------|----------|
| **FINAL_STATUS.md** | Current state (ROLLBACK_FAILED) and cleanup order | 🔴 CRITICAL |
| **QUICK_START.md** | 3-step resolution with correct cleanup sequence | 🔴 CRITICAL |
| **IAM_PERMISSIONS_BLOCKER.md** | IAM permissions issue and resolution | 🔴 CRITICAL |

### Context & Background
| Document | Purpose | When to Read |
|----------|---------|--------------|
| **HANDOFF_NOTES.md** | Complete session summary | Before starting work |
| **SESSION_SUMMARY.md** | High-level overview | Quick reference |
| **.kiro/specs/salesforce-ai-search-poc/tasks.md** | Task tracking | Check task status |

### Historical Reference
| Document | Purpose | When to Read |
|----------|---------|--------------|
| **DEPLOYMENT_BLOCKER.md** | Previous CloudFormation issue (resolved) | If curious about history |
| **AWS_SUPPORT_CASE.md** | Support case template (not needed) | Reference only |
| **deployment-status.md** | Deployment progress log | Troubleshooting |

### Tools & Scripts
| File | Purpose | Usage |
|------|---------|-------|
| **check-deployment.sh** | Monitor stack status | `./check-deployment.sh` |

---

## 🎯 Current Blocker

- Bedrock returns `"The OpenSearch Managed Cluster you provided is not supported because it is VPC protected"` when the domain is private-only.
- Therefore, we cannot proceed with the managed OpenSearch design; the blocker is architectural, not IAM.
- Resolution is outlined in `docs/SERVERLESS_MIGRATION_PLAN.md` (Serverless migration).

---

## 📊 Deployment Status

```
✅ NetworkStack     CREATE_COMPLETE
✅ DataStack        CREATE_COMPLETE
❌ SearchStack      BLOCKED (KnowledgeBase role IAM)
⏳ IngestionStack   WAITING
⏳ ApiStack         WAITING
⏳ MonitoringStack  WAITING
```

---

## 🔧 Quick Commands

### Check Current Status
```bash
./check-deployment.sh
```

### Clean Up Failed Resources (order matters)
```bash
# 1. Delete OpenSearch domain FIRST (releases the security group)
aws opensearch delete-domain --domain-name salesforce-ai-search
aws opensearch wait domain-not-exists --domain-name salesforce-ai-search

# 2. Delete the failed stack (now possible)
aws cloudformation delete-stack --stack-name SalesforceAISearch-Search-dev
aws cloudformation wait stack-delete-complete --stack-name SalesforceAISearch-Search-dev
```

### Deploy All Stacks
```bash
npx cdk deploy SalesforceAISearch-Search-dev \
  SalesforceAISearch-Ingestion-dev \
  SalesforceAISearch-Api-dev \
  SalesforceAISearch-Monitoring-dev \
  --require-approval never
```

---

## 📁 Code Files Modified

### CDK Infrastructure
- `lib/search-stack.ts` - SearchStack with managed OpenSearch
- `lib/monitoring-stack.ts` - Monitoring for managed OpenSearch
- `bin/app.ts` - Stack dependencies

### Configuration
- `.kiro/specs/salesforce-ai-search-poc/tasks.md` - Task 24.2.3 status

---

## 🎓 Key Learnings

1. **IAM First**: Always verify deployment user has all required permissions
2. **Resource Cleanup**: OpenSearch domains take 10-15 minutes to delete
3. **Stack Dependencies**: SearchStack must complete before others can deploy
4. **Iterative Debugging**: Each attempt revealed different issues

---

## 📞 Need Help?

1. **KnowledgeBase Role Permissions**: See IAM_PERMISSIONS_BLOCKER.md
2. **Deployment Failures**: Check HANDOFF_NOTES.md troubleshooting section
3. **Stack Status**: Run `./check-deployment.sh`
4. **Historical Context**: Read SESSION_SUMMARY.md

---

## ✅ Success Checklist

Before marking Task 24.2.3 complete:

- [ ] Failed stack cleaned up
- [ ] OpenSearch domain deleted (if exists)
- [ ] All 4 stacks deployed successfully
- [ ] All stacks show CREATE_COMPLETE status
- [ ] No errors in CloudFormation events
- [ ] Ready to proceed to Task 24.2.4

---

## 🔄 Next Steps

After Task 24.2.3 completes:

1. **Task 24.2.4**: Capture stack outputs
   - API Gateway endpoint
   - API Key
   - VPC Endpoint Service Name

2. **Task 24.2.5**: Verify AWS deployment
   - Check VPC endpoints
   - Verify S3 buckets
   - Verify DynamoDB tables
   - Verify Lambda functions

3. **Task 24.3**: Deploy Salesforce metadata

---

**Last Updated**: 2025-11-17 4:45 PM PST  
**Next Session**: Delete OpenSearch domain → delete stack → redeploy
