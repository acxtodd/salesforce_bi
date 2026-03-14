# Salesforce Components - Documentation Index

## 🎯 Start Here

**New to this project?** → Read **[QUICK_START.md](./QUICK_START.md)** first!

**Ready to deploy?** → See **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)**

**Need a Salesforce org?** → Check **[SALESFORCE_INSTANCE_REQUIREMENTS.md](./SALESFORCE_INSTANCE_REQUIREMENTS.md)**

---

## 📚 Documentation Overview

### For Developers

| Document | Purpose | When to Read |
|----------|---------|--------------|
| **[QUICK_START.md](./QUICK_START.md)** | Quick overview and next steps | **Start here** |
| **[README.md](./README.md)** | Complete component reference | When you need details |
| **[SALESFORCE_INSTANCE_REQUIREMENTS.md](./SALESFORCE_INSTANCE_REQUIREMENTS.md)** | When you need SF org | Before requesting access |

### For Deployment

| Document | Purpose | When to Read |
|----------|---------|--------------|
| **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)** | Step-by-step deployment | When AWS is ready |
| **[deployment-config.template.json](./deployment-config.template.json)** | Configuration tracking | During deployment |
| **[deploy.sh](./deploy.sh)** | Automated deployment | When deploying |

### For Project Management

| Document | Purpose | When to Read |
|----------|---------|--------------|
| **[TASK-10-SUMMARY.md](./TASK-10-SUMMARY.md)** | What was implemented | Task completion review |
| **[INDEX.md](./INDEX.md)** | This file - documentation map | Finding documentation |

---

## 🗂️ Component Files

### Metadata
- `namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml` - API Gateway connection
- `metadata/AI_Search_Config__mdt.xml` - Search configuration
- `objects/AI_Search_Export_Error__c.object` - Error logging

### Code
- `apex/AscendixAISearchController.cls` - LWC controller
- `apex/AISearchBatchExport.cls` - Batch export
- `apex/AISearchBatchExportScheduler.cls` - Scheduler
- `lwc/ascendixAiSearch/` - Lightning Web Component

### Configuration
- `sfdx-project.json` - SFDX project config
- `package.xml` - Deployment manifest

---

## 🚦 Current Status

### ✅ Completed
- Task 10.1: Named Credential configuration created
- Task 10.2: Deployment package created
- Task 10.3: Private Connect documentation created
- All deployment artifacts ready

### ⏳ Pending
- Task 10.4: End-to-end testing (requires SF org)
- Task 14: Acceptance testing (requires SF org)
- Task 24: Production deployment (requires production org)

### ❌ Not Required Yet
- Salesforce sandbox/dev org
- Actual deployment to Salesforce
- Private Connect configuration

---

## 🎬 Typical Workflow

### Phase 1: Development (Current)
1. ✅ Create deployment artifacts (Task 10) - **DONE**
2. ⏳ Deploy AWS infrastructure (Tasks 1-9)
3. ⏳ Test AWS backend independently

### Phase 2: Integration
1. ⏳ Obtain Salesforce sandbox/dev org
2. ⏳ Configure Named Credential with API Gateway endpoint
3. ⏳ Run `./deploy.sh` to deploy components
4. ⏳ Test end-to-end integration

### Phase 3: Production
1. ⏳ Complete acceptance testing in sandbox
2. ⏳ Configure production Private Connect
3. ⏳ Deploy to production org
4. ⏳ Production smoke tests

---

## 🔍 Finding What You Need

### "I need to understand what was built"
→ Read **[TASK-10-SUMMARY.md](./TASK-10-SUMMARY.md)**

### "I need to know if I need Salesforce now"
→ Read **[QUICK_START.md](./QUICK_START.md)** or **[SALESFORCE_INSTANCE_REQUIREMENTS.md](./SALESFORCE_INSTANCE_REQUIREMENTS.md)**

### "I'm ready to deploy"
→ Read **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)**

### "I need technical details about components"
→ Read **[README.md](./README.md)**

### "I need to troubleshoot deployment"
→ See troubleshooting section in **[DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)**

### "I need to understand the architecture"
→ See **[../.kiro/specs/salesforce-ai-search-poc/design.md](../.kiro/specs/salesforce-ai-search-poc/design.md)**

---

## 📞 Support

- **Deployment questions**: See DEPLOYMENT_GUIDE.md
- **Technical questions**: See README.md
- **Salesforce org questions**: See SALESFORCE_INSTANCE_REQUIREMENTS.md
- **Architecture questions**: See design.md in specs directory

---

**Last Updated**: 2025-11-13  
**Task**: 10. Configure Salesforce integration  
**Status**: ✅ Complete (artifacts created, deployment deferred)
