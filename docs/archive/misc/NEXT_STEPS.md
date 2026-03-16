# Next Steps - Salesforce AI Search POC Deployment

**Date**: November 20, 2025  
**Status**: Ready for Deployment (Blocked on API Key)

## Current Situation

✅ **What's Complete**:
- All AWS infrastructure deployed (6 stacks)
- All Lambda functions implemented and deployed
- All Salesforce code implemented and validated
- Salesforce org authenticated (ascendix-beta-sandbox)

❌ **What's Missing**:
- **0 of 25 Salesforce components deployed to org**
- API key not retrieved from AWS
- Named Credential not configured with AWS endpoint

## Critical Blocker

### 🔴 Task 24.2.4: Retrieve API Key from AWS

The API Gateway API key is needed to configure the Salesforce Named Credential before deployment.

**Options to retrieve API key**:

1. **From AWS Console**:
   ```
   Navigate to: API Gateway → API Keys → [Your API Key]
   Copy the API key value
   ```

2. **From AWS CLI**:
   ```bash
   # List API keys
   aws apigateway get-api-keys --region us-west-2 --include-values
   
   # Or if you know the key ID
   aws apigateway get-api-key --api-key <key-id> --include-value --region us-west-2
   ```

3. **From CDK Outputs**:
   ```bash
   # Check stack outputs
   aws cloudformation describe-stacks --stack-name ApiStack --region us-west-2 \
     --query 'Stacks[0].Outputs[?OutputKey==`ApiKeyValue`].OutputValue' --output text
   ```

4. **From Secrets Manager** (if stored there):
   ```bash
   aws secretsmanager get-secret-value --secret-id salesforce-ai-search-api-key \
     --region us-west-2 --query SecretString --output text
   ```

## Deployment Steps (Once API Key Retrieved)

### Step 1: Update Named Credential (Task 24.3.2)

Edit `salesforce/namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml`:

```xml
<endpoint>https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/</endpoint>
<password>[INSERT API KEY HERE]</password>
```

### Step 2: Deploy Custom Objects (Task 24.3.3)

```bash
cd salesforce
sf project deploy start --source-dir objects --target-org ascendix-beta-sandbox
```

**Expected**: 5 custom objects deployed

### Step 3: Deploy Phase 1 Components (Task 24.3.4)

```bash
sf project deploy start --source-dir classes,lwc,namedCredentials --target-org ascendix-beta-sandbox
```

**Expected**: 8 Apex classes, 1 LWC, 2 Named Credentials deployed

### Step 4: Deploy Phase 2 Components (Task 24.3.5)

```bash
sf project deploy start --source-dir flows,permissionsets,customMetadata --target-org ascendix-beta-sandbox
```

**Expected**: 3 Flows, 1 Permission Set, metadata records deployed

### Step 5: Verify Deployment (Task 24.3.6)

```bash
./audit-salesforce-deployment.sh
```

**Expected Output**:
```
✅ DEPLOYMENT COMPLETE: All 25 components found
```

## After Deployment

Once all components are deployed:

1. **Configure Private Connect** (Task 24.4)
   - Set up Salesforce Private Connect to AWS PrivateLink
   - Accept connection request in AWS
   - Test Named Credential connectivity

2. **Configure Page Layouts** (Task 24.5)
   - Add LWC to Account and Home pages
   - Assign permission sets to pilot users

3. **Configure CDC and AppFlow** (Task 24.6)
   - Enable CDC for target objects
   - Configure AppFlow flows
   - Run initial data export

4. **Run Smoke Tests** (Task 24.7)
   - Test search functionality
   - Test agent actions
   - Test with different user roles

## Quick Reference

**Org Details**:
- Alias: `ascendix-beta-sandbox`
- Username: `tterry@ascendix.com.agentforce.demo.beta`
- Org ID: `00Ddl000003yx57EAA`

**AWS Details**:
- Region: `us-west-2`
- API Gateway: `https://kuspjg7e7e.execute-api.us-west-2.amazonaws.com/prod/`
- VPC Endpoint: `vpce-09153968dd9f31fa2`

**Useful Commands**:
```bash
# Check org connection
sf org display --target-org ascendix-beta-sandbox

# Run deployment audit
./audit-salesforce-deployment.sh

# Check deployment status
sf project deploy report --use-most-recent --target-org ascendix-beta-sandbox

# List recent deployments
sf project deploy report --target-org ascendix-beta-sandbox
```

## Timeline Estimate

Assuming API key is available:

- **Step 1** (Update Named Credential): 5 minutes
- **Step 2** (Deploy Custom Objects): 5-10 minutes
- **Step 3** (Deploy Phase 1): 10-15 minutes
- **Step 4** (Deploy Phase 2): 10-15 minutes
- **Step 5** (Verify): 2 minutes

**Total**: ~30-45 minutes for complete Salesforce deployment

---

**Last Updated**: November 20, 2025  
**Next Action**: Retrieve API key from AWS (Task 24.2.4)
