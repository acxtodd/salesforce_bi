# Salesforce Deployment Guide

This guide covers the deployment of the Ascendix AI Search POC components to Salesforce.

## ⚠️ Important: When to Use This Guide

**This guide is for LATER in the project!**

You do NOT need to follow these deployment steps yet. This guide should be used when:
1. ✅ AWS infrastructure is fully deployed (all CDK stacks)
2. ✅ API Gateway endpoint is available
3. ✅ You have access to a Salesforce sandbox or developer org
4. ✅ You're ready for integration testing (Task 10.4 or Task 14)

**Current Status**: Task 10 created all the deployment artifacts. You can continue with AWS infrastructure development without a Salesforce instance.

**See [SALESFORCE_INSTANCE_REQUIREMENTS.md](./SALESFORCE_INSTANCE_REQUIREMENTS.md) for guidance on when you need a Salesforce org.**

---

## Prerequisites

- Salesforce CLI (SFDX) installed
- Access to target Salesforce sandbox/org with System Administrator profile
- AWS Private API Gateway endpoint URL
- API Gateway API key
- Salesforce Private Connect configured (see Private Connect Setup section)

## Task 10.1: Create Named Credential for Private API Gateway

### Step 1: Get AWS API Gateway Details

Before configuring the Named Credential, obtain the following from your AWS deployment:

1. **PrivateLink Endpoint URL**: The private API Gateway endpoint URL
   - Format: `https://vpce-xxxxx-xxxxx.execute-api.{region}.vpce.amazonaws.com/{stage}`
   - This is output from the CDK deployment (APIStack)

2. **API Key**: The API Gateway API key for authentication
   - Retrieved from AWS Secrets Manager or API Gateway console
   - Format: A long alphanumeric string

### Step 2: Update Named Credential Configuration

Edit `salesforce/namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml`:

```xml
<endpoint>https://YOUR_PRIVATELINK_ENDPOINT_URL</endpoint>
<password>YOUR_API_KEY</password>
```

Replace:
- `YOUR_PRIVATELINK_ENDPOINT_URL` with the actual PrivateLink endpoint
- `YOUR_API_KEY` with the actual API Gateway key

### Step 3: Deploy Named Credential

```bash
# Navigate to salesforce directory
cd salesforce

# Authenticate to your Salesforce org
sfdx auth:web:login -a my-sandbox

# Deploy the Named Credential
sfdx force:source:deploy -m NamedCredential:Ascendix_RAG_API -u my-sandbox
```

### Step 4: Test Connectivity

After deployment, test the Named Credential:

1. Navigate to **Setup** > **Named Credentials** in Salesforce
2. Find **Ascendix RAG API**
3. Click **Edit**
4. Scroll down and click **Test Connection**
5. Verify successful connection (200 OK response)

**Troubleshooting**:
- If connection fails with timeout: Verify Private Connect is configured (see Task 10.3)
- If connection fails with 403: Verify API key is correct
- If connection fails with DNS error: Verify PrivateLink endpoint URL is correct

---

## Task 10.2: Deploy LWC to Salesforce Sandbox

### Step 1: Validate Metadata

Before deployment, validate all components:

```bash
# Validate the package
sfdx force:source:deploy -x package.xml -u my-sandbox --checkonly

# Review validation results
# Fix any errors before proceeding
```

### Step 2: Deploy All Components

Deploy the complete package to sandbox:

```bash
# Deploy all components
sfdx force:source:deploy -x package.xml -u my-sandbox

# Monitor deployment status
sfdx force:source:deploy:report -u my-sandbox
```

This deploys:
- Lightning Web Component (ascendixAiSearch)
- Apex Classes (AscendixAISearchController, AISearchBatchExport, AISearchBatchExportScheduler)
- Named Credential (Ascendix_RAG_API)
- Custom Metadata Type (AI_Search_Config__mdt)
- Custom Object (AI_Search_Export_Error__c)

### Step 3: Add LWC to Page Layouts

#### Add to Account Page Layout

1. Navigate to **Setup** > **Object Manager** > **Account**
2. Click **Lightning Record Pages**
3. Click **New** or edit existing page
4. Drag **ascendixAiSearch** component from Custom Components to the page
5. Configure component properties:
   - **Title**: "AI Search"
   - **Height**: 600px (recommended)
6. Click **Save** and **Activate**
7. Assign to appropriate profiles/apps

#### Add to Home Page Layout

1. Navigate to **Setup** > **Lightning App Builder**
2. Click **New** > **Home Page**
3. Select template (e.g., "Header and Two Columns")
4. Drag **ascendixAiSearch** component to desired region
5. Configure component properties
6. Click **Save** and **Activate**
7. Assign to appropriate profiles/apps

### Step 4: Assign Permissions

Create and assign a permission set for pilot users:

```bash
# Create permission set (manual step in Salesforce UI)
# Or deploy via metadata
```

1. Navigate to **Setup** > **Permission Sets**
2. Click **New**
3. Name: "AI Search User"
4. Assign object permissions:
   - **AI_Search_Export_Error__c**: Read access
5. Assign Apex class access:
   - **AscendixAISearchController**: Enabled
6. Save and assign to pilot users

### Step 5: Verify Deployment

Test the LWC in Salesforce:

1. Navigate to an Account record page
2. Verify the AI Search component appears
3. Submit a test query (e.g., "Show open opportunities for this account")
4. Verify streaming response displays
5. Verify citations appear in drawer
6. Click a citation to verify preview panel opens

**Expected Behavior**:
- Query input field is visible and functional
- Streaming tokens appear as they arrive
- Citations drawer shows relevant records
- No console errors in browser developer tools

**Troubleshooting**:
- If component doesn't appear: Check page layout assignment and activation
- If query fails: Check Named Credential configuration and connectivity
- If no results: Verify data has been ingested via CDC pipeline
- If console errors: Check browser console for detailed error messages

---

## Task 10.3: Configure Salesforce Private Connect

### Overview

Salesforce Private Connect enables secure, private connectivity between Salesforce and AWS services without traversing the public internet. This is required for the Named Credential to reach the Private API Gateway.

### Prerequisites

- AWS PrivateLink endpoint created (from APIStack deployment)
- AWS PrivateLink Service Name (format: `com.amazonaws.vpce.{region}.vpce-svc-xxxxx`)
- Salesforce org with Private Connect enabled (contact Salesforce support if not available)

### Step 1: Get AWS PrivateLink Service Details

From your AWS deployment, retrieve:

1. **VPC Endpoint Service Name**:
   ```bash
   # From CDK outputs or AWS Console
   aws ec2 describe-vpc-endpoint-services --region us-east-1 --query 'ServiceNames[?contains(@, `vpce-svc`)]'
   ```

2. **Allowed Principals** (Salesforce AWS account):
   - Salesforce provides their AWS account ID for allowlisting
   - Contact Salesforce support or check documentation for your region

### Step 2: Configure AWS PrivateLink Permissions

Allow Salesforce to connect to your VPC Endpoint Service:

```bash
# Add Salesforce AWS account as allowed principal
aws ec2 modify-vpc-endpoint-service-permissions \
  --service-id vpce-svc-xxxxx \
  --add-allowed-principals arn:aws:iam::SALESFORCE_AWS_ACCOUNT:root \
  --region us-east-1
```

### Step 3: Create Private Connect Endpoint in Salesforce

1. Navigate to **Setup** > **Private Connect** in Salesforce
2. Click **New Private Connect Endpoint**
3. Enter details:
   - **Name**: Ascendix RAG API Private Connect
   - **AWS Service Name**: `com.amazonaws.vpce.{region}.vpce-svc-xxxxx`
   - **AWS Region**: Your API Gateway region (e.g., us-east-1)
4. Click **Save**
5. Wait for status to change to **Active** (may take 5-10 minutes)

### Step 4: Accept Connection Request in AWS

Salesforce will create a connection request to your VPC Endpoint Service:

```bash
# List pending connection requests
aws ec2 describe-vpc-endpoint-connections \
  --service-id vpce-svc-xxxxx \
  --region us-east-1

# Accept the connection request
aws ec2 accept-vpc-endpoint-connections \
  --service-id vpce-svc-xxxxx \
  --vpc-endpoint-ids vpce-xxxxx \
  --region us-east-1
```

### Step 5: Verify End-to-End Connectivity

Test the complete connection path:

1. In Salesforce, navigate to **Setup** > **Private Connect**
2. Verify endpoint status is **Active**
3. Navigate to **Setup** > **Named Credentials**
4. Open **Ascendix RAG API**
5. Click **Test Connection**
6. Verify successful response (200 OK)

### Step 6: Update Named Credential with Private Connect

If using Private Connect, update the Named Credential endpoint to use the private DNS name:

```xml
<endpoint>https://vpce-xxxxx.execute-api.{region}.vpce.amazonaws.com/prod</endpoint>
```

The endpoint should resolve through Private Connect, not public internet.

### Verification Checklist

- [ ] AWS PrivateLink Service created and configured
- [ ] Salesforce AWS account added to allowed principals
- [ ] Private Connect endpoint created in Salesforce
- [ ] Connection request accepted in AWS
- [ ] Private Connect status is Active
- [ ] Named Credential test connection succeeds
- [ ] LWC can successfully query the API
- [ ] Network traffic does not traverse public internet (verify with network monitoring)

**Troubleshooting**:
- **Connection timeout**: Verify security groups allow traffic from Salesforce CIDR ranges
- **DNS resolution fails**: Verify Private Connect endpoint is active and DNS is configured
- **403 Forbidden**: Verify API key is correct in Named Credential
- **Connection refused**: Verify API Gateway is deployed and VPC endpoint is attached

---

## Deployment Checklist

### Pre-Deployment
- [ ] AWS infrastructure deployed (all CDK stacks)
- [ ] API Gateway endpoint URL obtained
- [ ] API Gateway API key obtained
- [ ] Private Connect configured and active
- [ ] Salesforce CLI installed and authenticated

### Deployment
- [ ] Named Credential configured with correct endpoint and API key
- [ ] Named Credential deployed to Salesforce
- [ ] Named Credential connectivity tested
- [ ] All metadata components deployed via package.xml
- [ ] LWC added to Account page layout
- [ ] LWC added to Home page layout
- [ ] Permission set created and assigned to pilot users

### Post-Deployment
- [ ] LWC visible on Account pages
- [ ] Test query submitted successfully
- [ ] Streaming response displays correctly
- [ ] Citations appear and are clickable
- [ ] No console errors in browser
- [ ] End-to-end connectivity verified through Private Connect

### Smoke Tests
- [ ] Query: "Show open opportunities for this account" returns results
- [ ] Query: "Summarize recent cases" returns results with citations
- [ ] Citation click opens preview panel
- [ ] Facet filters (Region, BU, Quarter) work correctly
- [ ] Error handling displays friendly messages

---

## Rollback Procedure

If issues arise, rollback in reverse order:

### Step 1: Remove LWC from Page Layouts
1. Navigate to Lightning App Builder
2. Remove ascendixAiSearch component from all pages
3. Save and activate

### Step 2: Disable Named Credential
1. Navigate to **Setup** > **Named Credentials**
2. Edit **Ascendix RAG API**
3. Set **Callout Status** to **Disabled**
4. Save

### Step 3: Uninstall Components (Optional)
```bash
# Remove all components
sfdx force:source:delete -m LightningComponentBundle:ascendixAiSearch -u my-sandbox
sfdx force:source:delete -m NamedCredential:Ascendix_RAG_API -u my-sandbox
```

### Step 4: Disable Private Connect (Optional)
1. Navigate to **Setup** > **Private Connect**
2. Delete the Private Connect endpoint
3. This will not affect AWS infrastructure

---

## Production Deployment

After successful sandbox testing, deploy to production:

### Option 1: Change Set
1. Create outbound change set in sandbox
2. Include all components from package.xml
3. Upload to production
4. Deploy in production during maintenance window

### Option 2: SFDX Deployment
```bash
# Authenticate to production
sfdx auth:web:login -a production

# Deploy with validation
sfdx force:source:deploy -x package.xml -u production --checkonly

# Deploy to production
sfdx force:source:deploy -x package.xml -u production
```

### Production-Specific Configuration
- Update Named Credential with production API Gateway endpoint
- Update Private Connect with production VPC Endpoint Service
- Assign permission sets to production users
- Configure production page layouts
- Schedule production smoke tests

---

## Support and Troubleshooting

### Common Issues

**Issue**: Named Credential test fails with timeout
- **Cause**: Private Connect not configured or inactive
- **Solution**: Complete Task 10.3 to configure Private Connect

**Issue**: LWC shows "Access Denied" error
- **Cause**: User lacks permissions or Named Credential is disabled
- **Solution**: Assign permission set and verify Named Credential is enabled

**Issue**: No search results returned
- **Cause**: Data not yet ingested via CDC pipeline
- **Solution**: Verify CDC configuration and wait for initial sync (Task 8)

**Issue**: Citations don't open preview panel
- **Cause**: Presigned S3 URLs expired or inaccessible
- **Solution**: Verify S3 bucket permissions and URL generation logic

### Logs and Monitoring

**Salesforce Debug Logs**:
```bash
# Enable debug logs for user
sfdx force:apex:log:tail -u my-sandbox
```

**AWS CloudWatch Logs**:
- Check Lambda function logs for API errors
- Check API Gateway access logs for request details

**Browser Console**:
- Open browser developer tools (F12)
- Check Console tab for JavaScript errors
- Check Network tab for API request/response details

### Contact Information

- **AWS Infrastructure**: [DevOps Team]
- **Salesforce Configuration**: [Salesforce Admin Team]
- **Application Support**: [Development Team]
- **Security/Private Connect**: [Security Team]

---

## Appendix

### A. Named Credential Configuration Reference

```xml
<?xml version="1.0" encoding="UTF-8"?>
<NamedCredential xmlns="http://soap.sforce.com/2006/04/metadata">
    <label>Ascendix RAG API</label>
    <endpoint>https://vpce-xxxxx.execute-api.us-east-1.vpce.amazonaws.com/prod</endpoint>
    <principalType>NamedUser</principalType>
    <protocol>Password</protocol>
    <username>api-user</username>
    <password>YOUR_API_KEY_HERE</password>
    <allowMergeFieldsInBody>false</allowMergeFieldsInBody>
    <allowMergeFieldsInHeader>true</allowMergeFieldsInHeader>
    <generateAuthorizationHeader>true</generateAuthorizationHeader>
    <authorizationHeaderName>x-api-key</authorizationHeaderName>
    <calloutStatus>Enabled</calloutStatus>
</NamedCredential>
```

### B. SFDX Commands Reference

```bash
# Authenticate to org
sfdx auth:web:login -a my-org

# List orgs
sfdx force:org:list

# Deploy specific metadata type
sfdx force:source:deploy -m LightningComponentBundle:ascendixAiSearch -u my-org

# Deploy using package.xml
sfdx force:source:deploy -x package.xml -u my-org

# Validate deployment (no actual deployment)
sfdx force:source:deploy -x package.xml -u my-org --checkonly

# Retrieve metadata from org
sfdx force:source:retrieve -m LightningComponentBundle:ascendixAiSearch -u my-org

# Delete metadata from org
sfdx force:source:delete -m LightningComponentBundle:ascendixAiSearch -u my-org

# View deployment status
sfdx force:source:deploy:report -u my-org

# Tail debug logs
sfdx force:apex:log:tail -u my-org
```

### C. AWS CLI Commands Reference

```bash
# List VPC Endpoint Services
aws ec2 describe-vpc-endpoint-services --region us-east-1

# Describe VPC Endpoint Service
aws ec2 describe-vpc-endpoint-service-configurations \
  --service-ids vpce-svc-xxxxx \
  --region us-east-1

# Add allowed principal
aws ec2 modify-vpc-endpoint-service-permissions \
  --service-id vpce-svc-xxxxx \
  --add-allowed-principals arn:aws:iam::ACCOUNT_ID:root \
  --region us-east-1

# List connection requests
aws ec2 describe-vpc-endpoint-connections \
  --service-id vpce-svc-xxxxx \
  --region us-east-1

# Accept connection request
aws ec2 accept-vpc-endpoint-connections \
  --service-id vpce-svc-xxxxx \
  --vpc-endpoint-ids vpce-xxxxx \
  --region us-east-1

# Get API Gateway endpoint
aws apigateway get-rest-apis --region us-east-1 --no-cli-pager

# Get API key value
aws apigateway get-api-key --api-key API_KEY_ID --include-value --region us-east-1 --no-cli-pager
```

### D. Private Connect Salesforce AWS Account IDs by Region

Consult Salesforce documentation for the correct AWS account ID for your region:
- **US**: Contact Salesforce support
- **EMEA**: Contact Salesforce support
- **APAC**: Contact Salesforce support

These account IDs are required for the `--add-allowed-principals` step.

---

## Document Version

- **Version**: 1.0
- **Last Updated**: 2025-11-13
- **Author**: Development Team
- **Status**: Active
