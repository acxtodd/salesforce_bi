# Salesforce Instance Requirements

## Overview

This document clarifies when you need an actual Salesforce sandbox/dev org versus when you can work with just the code artifacts.

## What's Been Created (No SF Instance Required)

Task 10 created all the **configuration and deployment artifacts** needed for Salesforce integration:

### ✅ Completed Without Salesforce Instance
- **Named Credential metadata template** (`namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml`)
- **SFDX project configuration** (`sfdx-project.json`)
- **Package manifest** (`package.xml`)
- **Deployment automation script** (`deploy.sh`)
- **Comprehensive documentation** (`DEPLOYMENT_GUIDE.md`, `README.md`)
- **Configuration tracking template** (`deployment-config.template.json`)

### ✅ Previously Created (No SF Instance Required)
- **Lightning Web Component code** (`lwc/ascendixAiSearch/`)
- **Apex controller classes** (`apex/AscendixAISearchController.cls`, etc.)
- **Custom objects and metadata** (`objects/`, `metadata/`)
- **Unit tests** (`lwc/__tests__/`)

## When You NEED a Salesforce Instance

### Phase 1: Development (Current Phase)
**Status**: ❌ Not required yet

You can continue development without a Salesforce instance:
- Build AWS infrastructure (CDK stacks)
- Develop Lambda functions
- Configure OpenSearch and Bedrock
- Test backend APIs independently

### Phase 2: Integration Testing
**Status**: ⚠️ Required for these tasks

You'll need a Salesforce **sandbox or developer org** for:

#### Task 10.4 (Optional Test Task)
- Deploy Named Credential to Salesforce
- Test connectivity to AWS API Gateway
- Verify Private Connect configuration

#### Task 14: Acceptance Testing
- Deploy LWC to Salesforce
- Test end-to-end flow from UI to AWS and back
- Test with real Salesforce user permissions
- Measure actual latency and performance
- Verify authorization rules work correctly

#### Task 24: Production Deployment
- Deploy to production Salesforce org
- Configure production Private Connect
- Production smoke tests

### Phase 3: Custom Object Support (Future)
**Status**: ⚠️ Required

- Configure IndexConfiguration custom metadata
- Test with custom objects
- Verify dynamic authorization

## Types of Salesforce Orgs

### Developer Org (Free)
**Best for**: Initial development and testing
- **Cost**: Free
- **How to get**: https://developer.salesforce.com/signup
- **Limitations**: 
  - Limited storage
  - No Private Connect support
  - Cannot test PrivateLink integration
- **Good for**:
  - LWC development and testing
  - Apex class testing
  - Basic functionality verification

### Sandbox Org (Requires Production License)
**Best for**: Full integration testing with Private Connect
- **Cost**: Included with Salesforce licenses
- **Types**:
  - Developer Sandbox (small, fast refresh)
  - Developer Pro Sandbox (more storage)
  - Partial Copy Sandbox (includes sample data)
  - Full Sandbox (complete production copy)
- **Capabilities**:
  - Private Connect support ✅
  - PrivateLink integration ✅
  - Production-like environment ✅
- **Good for**:
  - Full end-to-end testing
  - Private Connect configuration
  - Security testing
  - Performance testing

### Production Org
**Best for**: Final deployment
- **Cost**: Salesforce license costs
- **When**: After successful sandbox testing
- **Requirements**:
  - Change management approval
  - Backup and rollback plan
  - User training completed

## Recommended Timeline

### Now (No SF Instance Needed)
1. ✅ Complete AWS infrastructure deployment
2. ✅ Deploy all CDK stacks
3. ✅ Test backend APIs independently
4. ✅ Verify data ingestion pipeline
5. ✅ Test OpenSearch and Bedrock integration

### When AWS Infrastructure is Ready
1. ⚠️ Obtain Salesforce sandbox or developer org
2. ⚠️ Deploy Salesforce components using `deploy.sh`
3. ⚠️ Configure Named Credential with API Gateway endpoint
4. ⚠️ Test end-to-end integration

### Before Production
1. ⚠️ Obtain production Salesforce org access
2. ⚠️ Configure production Private Connect
3. ⚠️ Complete acceptance testing in sandbox
4. ⚠️ Deploy to production

## How to Get a Salesforce Instance

### Option 1: Developer Org (Free, Immediate)
```bash
# Visit Salesforce Developer signup
open https://developer.salesforce.com/signup

# Fill out the form
# Receive credentials via email (usually within minutes)
# Login and start testing
```

**Pros**:
- Free
- Immediate access
- Good for basic testing

**Cons**:
- No Private Connect support
- Cannot test PrivateLink integration
- Limited to public API Gateway testing

### Option 2: Sandbox Org (Requires License)
```bash
# Contact your Salesforce administrator
# Request a Developer or Developer Pro sandbox
# Wait for sandbox creation (can take hours to days)
# Receive credentials
```

**Pros**:
- Private Connect support ✅
- Production-like environment
- Full feature set

**Cons**:
- Requires Salesforce licenses
- Requires admin approval
- Takes time to provision

### Option 3: Trial Org (30 Days)
```bash
# Visit Salesforce trial signup
open https://www.salesforce.com/form/trial/freetrial-sales/

# Get 30-day trial with full features
# May include Private Connect (verify with Salesforce)
```

**Pros**:
- Free for 30 days
- Full feature set
- Quick provisioning

**Cons**:
- Time-limited
- May not include Private Connect
- Cannot extend easily

## What You Can Test Without Salesforce

### Backend API Testing (No SF Instance)
```bash
# Test /retrieve endpoint directly
curl -X POST https://your-api-gateway/retrieve \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show open opportunities",
    "salesforceUserId": "005xx000001TEST",
    "topK": 8
  }'

# Test /answer endpoint
curl -X POST https://your-api-gateway/answer \
  -H "x-api-key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Summarize renewal risks",
    "sessionId": "test-session-1",
    "salesforceUserId": "005xx000001TEST"
  }'
```

### LWC Unit Tests (No SF Instance)
```bash
cd salesforce/lwc
npm install
npm test

# Run specific test
npm test -- ascendixAiSearch.test.js
```

### Apex Class Validation (No SF Instance)
```bash
# Validate syntax without deploying
sfdx force:source:deploy -x package.xml --checkonly --testlevel NoTestRun
```

## What You CANNOT Test Without Salesforce

### ❌ Cannot Test Without SF Instance
1. **Named Credential connectivity**
   - Requires actual Salesforce org to create Named Credential
   - Cannot test Private Connect without sandbox

2. **LWC in actual Salesforce UI**
   - Cannot see component on Account/Home pages
   - Cannot test with real Salesforce data
   - Cannot test user permissions

3. **Apex callouts to AWS**
   - Cannot test actual HTTP callouts from Salesforce
   - Cannot verify API key authentication works from SF

4. **Authorization with real users**
   - Cannot test sharing rules
   - Cannot test field-level security
   - Cannot test role hierarchy

5. **CDC integration**
   - Cannot test AppFlow configuration
   - Cannot test real-time data sync
   - Cannot verify EventBridge triggers

## Decision Matrix

| Task | SF Instance Required? | Type of Org | When |
|------|----------------------|-------------|------|
| Task 1-9: AWS Infrastructure | ❌ No | N/A | Now |
| Task 10.1-10.3: Create configs | ❌ No | N/A | Now (completed) |
| Task 10.4: Test integration | ✅ Yes | Sandbox preferred | After AWS deployed |
| Task 11-13: AWS monitoring | ❌ No | N/A | Now |
| Task 14: Acceptance testing | ✅ Yes | Sandbox required | Before production |
| Task 15-23: Phase 2 features | ⚠️ Optional | Developer org OK | During development |
| Task 24: Production deploy | ✅ Yes | Production required | Final step |

## Current Status Summary

### ✅ What You Have
- Complete LWC code
- Complete Apex classes
- Complete deployment configuration
- Complete documentation
- Ready-to-deploy package

### ⏳ What You Need Next
1. **Immediate**: Deploy AWS infrastructure (Tasks 1-9)
2. **Soon**: Obtain Salesforce sandbox for integration testing
3. **Later**: Production Salesforce org for final deployment

### 🎯 Recommended Next Steps

**If you have AWS infrastructure deployed:**
1. Get a Salesforce sandbox or developer org
2. Run `./deploy.sh` to deploy components
3. Configure Named Credential with API Gateway endpoint
4. Test end-to-end integration

**If AWS infrastructure is NOT deployed yet:**
1. Continue with AWS infrastructure tasks (Tasks 1-9)
2. Test backend APIs independently
3. Get Salesforce org when AWS is ready
4. Then proceed with integration testing

## FAQ

**Q: Can I use a free Developer Org for the POC?**
A: Yes, but with limitations. You can test basic LWC functionality and Apex classes, but you cannot test Private Connect/PrivateLink integration. For full testing, you need a sandbox.

**Q: How long does it take to get a sandbox?**
A: Developer sandboxes typically provision in 1-2 hours. Full sandboxes can take 24-48 hours.

**Q: Can I test without Private Connect?**
A: Yes, you can use a public API Gateway endpoint for initial testing. However, production deployment requires Private Connect for security.

**Q: Do I need a Salesforce license?**
A: Not for development. Developer orgs are free. Sandboxes require production licenses. Production deployment requires licenses for all users.

**Q: Can I develop the LWC locally without Salesforce?**
A: Yes, you can write and test LWC code locally using Jest. However, you need a Salesforce org to see it running in the actual UI.

**Q: What if I don't have access to a sandbox?**
A: Start with a free Developer Org for basic testing. Request sandbox access from your Salesforce admin when ready for full integration testing.

## Support

For questions about:
- **Getting a Salesforce org**: Contact your Salesforce administrator or sign up at developer.salesforce.com
- **Deployment issues**: See `DEPLOYMENT_GUIDE.md`
- **Technical questions**: See `README.md`

---

**Last Updated**: 2025-11-13  
**Status**: Active  
**Next Review**: When AWS infrastructure is deployed
