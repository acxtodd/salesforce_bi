# Salesforce AI Search POC - Complete Sandbox Installation Guide

This guide provides step-by-step instructions to deploy the complete Salesforce AI Search POC solution (Phase 1 + Phase 2) to your Salesforce sandbox.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [AWS Infrastructure Deployment](#aws-infrastructure-deployment)
3. [Salesforce Metadata Deployment](#salesforce-metadata-deployment)
4. [Configuration and Testing](#configuration-and-testing)
5. [Verification Checklist](#verification-checklist)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Tools

1. **AWS CLI** - Installed and configured
   ```bash
   aws --version
   # Should show version 2.x or higher
   
   aws configure
   # Enter your AWS Access Key ID, Secret Access Key, Region, and Output format
   ```

2. **Node.js** - Version 18 or higher
   ```bash
   node --version
   # Should show v18.x or higher
   ```

3. **AWS CDK** - Installed globally
   ```bash
   npm install -g aws-cdk
   cdk --version
   # Should show 2.x or higher
   ```

4. **Salesforce CLI (SFDX)** - Installed
   ```bash
   sfdx --version
   # Should show sfdx-cli version
   ```

### Required Access

- AWS account with Administrator or PowerUser permissions
- Salesforce sandbox with System Administrator profile
- Permissions to create VPC endpoints, Lambda functions, S3 buckets, etc.

### Information to Gather

Before starting, have the following ready:

- **AWS Account ID**: `____________`
- **AWS Region**: `____________` (e.g., us-east-1)
- **Salesforce Sandbox Org ID**: `____________`
- **Salesforce Sandbox URL**: `____________`

---

## AWS Infrastructure Deployment

### Step 1: Clone and Install Dependencies

```bash
# Navigate to project root
cd /path/to/salesforce-ai-search-poc

# Install Node.js dependencies
npm install
```

### Step 2: Bootstrap CDK (First Time Only)

```bash
# Bootstrap CDK in your AWS account
cdk bootstrap aws://YOUR_ACCOUNT_ID/YOUR_REGION

# Example:
# cdk bootstrap aws://123456789012/us-east-1
```

**Expected Output:**
```
✅  Environment aws://123456789012/us-east-1 bootstrapped.
```

### Step 3: Review Infrastructure

```bash
# Synthesize CloudFormation templates
npm run synth

# Review the generated templates in cdk.out/ directory
ls -la cdk.out/
```

### Step 4: Deploy All AWS Stacks

Deploy all infrastructure stacks in the correct order:

```bash
# Deploy all stacks (this will take 20-30 minutes)
npm run deploy

# Or deploy individually:
# cdk deploy SalesforceAISearch-Network-dev
# cdk deploy SalesforceAISearch-Data-dev
# cdk deploy SalesforceAISearch-Search-dev
# cdk deploy SalesforceAISearch-API-dev
# cdk deploy SalesforceAISearch-Ingestion-dev
# cdk deploy SalesforceAISearch-Monitoring-dev
```

**Expected Stacks:**
1. **NetworkStack** - VPC, subnets, VPC endpoints, KMS key (~7 min)
2. **DataStack** - S3 buckets, DynamoDB tables (~5 min)
3. **SearchStack** - Bedrock Knowledge Base, OpenSearch (~10 min)
4. **APIStack** - Lambda functions, API Gateway (~8 min)
5. **IngestionStack** - Step Functions, EventBridge, AppFlow (~5 min)
6. **MonitoringStack** - CloudWatch dashboards, alarms (~3 min)

### Step 5: Capture Stack Outputs

After deployment completes, save the important outputs:

```bash
# Get API Gateway endpoint URL
aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-API-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiGatewayEndpoint`].OutputValue' \
  --output text

# Save this value: ___________________________

# Get API Key ID
aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-API-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiKeyId`].OutputValue' \
  --output text

# Get the actual API key value
API_KEY_ID="<value from above>"
aws apigateway get-api-key --api-key $API_KEY_ID --include-value --no-cli-pager \
  --query 'value' --output text

# Save this value: ___________________________

# Get VPC Endpoint Service Name (for Private Connect)
aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-API-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`VpcEndpointServiceName`].OutputValue' \
  --output text

# Save this value: ___________________________
```

### Step 6: Verify AWS Deployment

Run verification checks:

```bash
# Check VPC endpoints are available
VPC_ID=$(aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-Network-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`VpcId`].OutputValue' \
  --output text)

aws ec2 describe-vpc-endpoints \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'VpcEndpoints[*].[ServiceName,State]' \
  --output table

# Expected: 5 endpoints in "available" state

# Check S3 buckets exist
aws s3 ls | grep salesforce-ai-search

# Expected: 3 buckets (data, embeddings, logs)

# Check DynamoDB tables exist
aws dynamodb list-tables | grep salesforce-ai-search

# Expected: 4 tables (telemetry, sessions, authz-cache, rate-limits)

# Check Lambda functions exist
aws lambda list-functions --query 'Functions[?contains(FunctionName, `salesforce-ai-search`)].FunctionName'

# Expected: 5 functions (Retrieve, Answer, AuthZ, Action, Ingest)
```

**✅ AWS Infrastructure Deployment Complete**

---

## Salesforce Metadata Deployment

### Step 1: Authenticate to Salesforce Sandbox

```bash
# Authenticate using web login
sfdx auth:web:login -a my-sandbox

# This will open a browser window
# Log in with your Salesforce sandbox credentials
# Authorize the CLI

# Verify authentication
sfdx force:org:list
```

**Expected Output:**
```
=== Orgs
     ALIAS       USERNAME                    ORG ID              CONNECTED STATUS
───  ──────────  ──────────────────────────  ──────────────────  ────────────────
(U)  my-sandbox  admin@company.com.sandbox   00Dxx000000xxxx     Connected
```

### Step 2: Update Named Credential Configuration

Edit the Named Credential with your AWS API Gateway details:

```bash
# Navigate to salesforce directory
cd salesforce

# Edit the Named Credential file
# Update with your API Gateway endpoint and API key
nano namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml
```

Update these values:
```xml
<endpoint>YOUR_API_GATEWAY_ENDPOINT_URL</endpoint>
<password>YOUR_API_KEY</password>
```

Example:
```xml
<endpoint>https://vpce-xxxxx.execute-api.us-east-1.vpce.amazonaws.com/prod</endpoint>
<password>AbCdEf123456789...</password>
```

Save the file.

### Step 3: Deploy Phase 1 Components

Deploy the core search functionality:

```bash
# Deploy all Phase 1 components
sfdx force:source:deploy -x package.xml -u my-sandbox

# Monitor deployment
sfdx force:source:deploy:report -u my-sandbox
```

**Components Deployed:**
- Lightning Web Component (ascendixAiSearch)
- Apex Classes (AscendixAISearchController, AISearchBatchExport, AISearchBatchExportScheduler)
- Named Credential (Ascendix_RAG_API)
- Custom Metadata Type (AI_Search_Config__mdt)
- Custom Object (AI_Search_Export_Error__c)

**Expected Output:**
```
=== Deployed Source
STATE    FULL NAME                          TYPE                      PROJECT PATH
───────  ─────────────────────────────────  ────────────────────────  ─────────────────
Created  ascendixAiSearch                   LightningComponentBundle  force-app/main/...
Created  AscendixAISearchController         ApexClass                 force-app/main/...
Created  Ascendix_RAG_API                   NamedCredential           force-app/main/...
...
```

### Step 4: Deploy Phase 2 Components (Agent Actions)

Deploy the agent actions functionality:

```bash
# Deploy Phase 2 custom object
sfdx force:source:deploy -u my-sandbox -p objects/AI_Action_Audit__c.object -w 10

# Deploy Phase 2 custom metadata type
sfdx force:source:deploy -u my-sandbox -p metadata/ActionEnablement__mdt.xml -w 10

# Deploy Phase 2 metadata records
sfdx force:source:deploy -u my-sandbox -p customMetadata/ -w 10

# Deploy Phase 2 permission set
sfdx force:source:deploy -u my-sandbox -p permissionsets/AI_Agent_Actions_Editor.permissionset-meta.xml -w 10

# Deploy Phase 2 Flows
sfdx force:source:deploy -u my-sandbox -p flows/ -w 10
```

**Components Deployed:**
- Custom Object (AI_Action_Audit__c)
- Custom Metadata Type (ActionEnablement__mdt)
- Metadata Records (Create_Opportunity, Update_Opportunity_Stage)
- Permission Set (AI_Agent_Actions_Editor)
- Flows (Create_Opportunity_Flow, Update_Opportunity_Stage_Flow)

### Step 5: Verify Salesforce Deployment

```bash
# Verify custom objects
sfdx force:data:soql:query -q "SELECT Id FROM AI_Action_Audit__c LIMIT 1" -u my-sandbox

# Verify metadata records
sfdx force:data:soql:query -q "SELECT DeveloperName, ActionName__c, Enabled__c FROM ActionEnablement__mdt" -u my-sandbox

# Expected: 2 records (Create_Opportunity, Update_Opportunity_Stage)
```

**✅ Salesforce Metadata Deployment Complete**

---

## Configuration and Testing

### Step 1: Configure Salesforce Private Connect

**Note:** This step requires coordination with Salesforce support if Private Connect is not already enabled in your org.

1. **Get Salesforce AWS Account ID for your region**
   - Contact Salesforce support or check documentation
   - Save this value: `____________`

2. **Allow Salesforce to connect to your VPC Endpoint Service**
   ```bash
   # Get your VPC Endpoint Service ID
   SERVICE_ID=$(aws cloudformation describe-stacks \
     --stack-name SalesforceAISearch-API-dev \
     --query 'Stacks[0].Outputs[?OutputKey==`VpcEndpointServiceId`].OutputValue' \
     --output text)
   
   # Add Salesforce AWS account as allowed principal
   aws ec2 modify-vpc-endpoint-service-permissions \
     --service-id $SERVICE_ID \
     --add-allowed-principals arn:aws:iam::SALESFORCE_AWS_ACCOUNT:root
   ```

3. **Create Private Connect Endpoint in Salesforce**
   - Navigate to **Setup** > **Private Connect**
   - Click **New Private Connect Endpoint**
   - Enter:
     - Name: Ascendix RAG API Private Connect
     - AWS Service Name: (your VPC Endpoint Service Name from Step 5 above)
     - AWS Region: (your AWS region)
   - Click **Save**
   - Wait for status to change to **Active** (5-10 minutes)

4. **Accept Connection Request in AWS**
   ```bash
   # List pending connection requests
   aws ec2 describe-vpc-endpoint-connections \
     --service-id $SERVICE_ID
   
   # Accept the connection (replace vpce-xxxxx with actual endpoint ID)
   aws ec2 accept-vpc-endpoint-connections \
     --service-id $SERVICE_ID \
     --vpc-endpoint-ids vpce-xxxxx
   ```

### Step 2: Test Named Credential Connectivity

1. Navigate to **Setup** > **Named Credentials** in Salesforce
2. Find **Ascendix RAG API**
3. Click **Edit**
4. Scroll down and click **Test Connection**
5. Verify successful connection (200 OK response)

**If test fails:**
- Verify Private Connect is Active
- Verify API key is correct
- Verify endpoint URL is correct
- Check AWS security groups allow traffic

### Step 3: Add LWC to Page Layouts

#### Add to Account Page Layout

1. Navigate to **Setup** > **Object Manager** > **Account**
2. Click **Lightning Record Pages**
3. Click **New** or edit existing "Account Record Page"
4. Drag **ascendixAiSearch** component from Custom Components to the page
5. Configure:
   - Title: "AI Search"
   - Height: 600px
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

### Step 4: Assign Permission Sets

Assign the AI_Agent_Actions_Editor permission set to pilot users:

```bash
# Assign to a specific user
sfdx force:user:permset:assign -n AI_Agent_Actions_Editor -u pilot.user@company.com.sandbox -o my-sandbox

# Verify assignment
sfdx force:data:soql:query -q "SELECT AssigneeId, Assignee.Username FROM PermissionSetAssignment WHERE PermissionSet.Name = 'AI_Agent_Actions_Editor'" -u my-sandbox
```

### Step 5: Enable CDC for Opportunity Object

1. Navigate to **Setup** > **Change Data Capture**
2. Click **Edit**
3. Move **Opportunity** from Available Entities to Selected Entities
4. Click **Save**

### Step 6: Configure AppFlow for CDC

**Note:** This requires AWS Console access.

1. Navigate to AWS Console > AppFlow
2. Create a new flow:
   - Source: Salesforce
   - Destination: S3 (your data bucket)
   - Trigger: On event (CDC)
   - Object: Opportunity
3. Configure field mappings (see `docs/APPFLOW_SETUP.md` for details)
4. Activate the flow

### Step 7: Run Initial Data Export

Trigger the initial batch export to populate the search index:

1. Navigate to **Setup** > **Developer Console** in Salesforce
2. Open **Debug** > **Open Execute Anonymous Window**
3. Execute:
   ```apex
   AISearchBatchExport batch = new AISearchBatchExport('Opportunity');
   Database.executeBatch(batch, 200);
   ```
4. Monitor batch job progress in **Setup** > **Apex Jobs**

**Expected:** Batch job completes successfully, exporting all Opportunity records to S3.

### Step 8: Verify End-to-End Functionality

1. **Navigate to an Account record page**
2. **Verify the AI Search component appears**
3. **Submit a test query**: "Show open opportunities for this account"
4. **Verify:**
   - Streaming response displays
   - Citations appear in drawer
   - Clicking citation opens preview panel
   - No console errors

**✅ Configuration and Testing Complete**

---

## Verification Checklist

Use this checklist to verify your installation:

### AWS Infrastructure

- [ ] All 6 CDK stacks deployed successfully
- [ ] VPC endpoints are in "available" state
- [ ] S3 buckets exist with encryption enabled
- [ ] DynamoDB tables exist with TTL configured
- [ ] Lambda functions exist and are connected to VPC
- [ ] API Gateway endpoint is accessible
- [ ] CloudWatch dashboards are created

### Salesforce Metadata

- [ ] Named Credential deployed and configured
- [ ] LWC component deployed
- [ ] Apex classes deployed
- [ ] Custom objects deployed (AI_Search_Export_Error__c, AI_Action_Audit__c)
- [ ] Custom metadata types deployed (AI_Search_Config__mdt, ActionEnablement__mdt)
- [ ] Permission set deployed (AI_Agent_Actions_Editor)
- [ ] Flows deployed (Create_Opportunity_Flow, Update_Opportunity_Stage_Flow)

### Configuration

- [ ] Private Connect endpoint is Active
- [ ] Named Credential test connection succeeds
- [ ] LWC added to Account page layout
- [ ] LWC added to Home page layout
- [ ] Permission set assigned to pilot users
- [ ] CDC enabled for Opportunity object
- [ ] AppFlow configured and active
- [ ] Initial data export completed

### Functionality

- [ ] Search query returns results
- [ ] Streaming response works
- [ ] Citations appear and are clickable
- [ ] Preview panel opens with record details
- [ ] Agent actions preview modal appears
- [ ] Agent actions confirmation works
- [ ] Action audit records are created
- [ ] No console errors in browser

---

## Troubleshooting

### AWS Deployment Issues

**Issue:** CDK bootstrap fails
```bash
# Solution: Verify AWS credentials
aws sts get-caller-identity

# Verify you have Administrator or PowerUser permissions
```

**Issue:** VPC Endpoint creation fails
```bash
# Solution: Verify Bedrock is available in your region
aws ec2 describe-vpc-endpoint-services | grep bedrock

# If not available, deploy to us-east-1 or us-west-2
```

**Issue:** Lambda function timeout
```bash
# Solution: Check Lambda logs
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --follow

# Verify VPC endpoints are working
# Verify security groups allow outbound traffic
```

### Salesforce Deployment Issues

**Issue:** Named Credential test fails with timeout
- **Solution:** Verify Private Connect is Active
- Check VPC Endpoint Service accepts connections
- Verify security groups allow traffic from Salesforce

**Issue:** LWC shows "Access Denied" error
- **Solution:** Verify user has permission set assigned
- Check Named Credential is enabled
- Verify API key is correct

**Issue:** No search results returned
- **Solution:** Verify initial data export completed
- Check AppFlow is running
- Verify Bedrock Knowledge Base sync completed
- Check CloudWatch logs for errors

**Issue:** Agent actions fail
- **Solution:** Verify Flows are deployed and active
- Check Action Lambda logs in CloudWatch
- Verify ActionEnablement metadata is configured
- Check user has AI_Agent_Actions_Editor permission set

### Common Errors

**Error:** "Invalid API key"
- Verify API key in Named Credential matches AWS API Gateway key
- Check API key is not expired

**Error:** "Connection timeout"
- Verify Private Connect is Active
- Check VPC Endpoint Service is accepting connections
- Verify security groups allow traffic

**Error:** "Insufficient permissions"
- Verify user has required permission sets
- Check object and field-level security
- Verify sharing rules allow access

### Getting Help

**AWS CloudWatch Logs:**
```bash
# View Lambda function logs
aws logs tail /aws/lambda/salesforce-ai-search-retrieve --follow
aws logs tail /aws/lambda/salesforce-ai-search-answer --follow
aws logs tail /aws/lambda/salesforce-ai-search-action --follow
```

**Salesforce Debug Logs:**
```bash
# Enable debug logs for user
sfdx force:apex:log:tail -u my-sandbox
```

**Browser Console:**
- Open browser developer tools (F12)
- Check Console tab for JavaScript errors
- Check Network tab for API request/response details

---

## Next Steps

After successful installation:

1. **Review the acceptance testing plan**: `docs/PHASE2_ACCEPTANCE_TESTING.md`
2. **Create test users** with different profiles and permission sets
3. **Execute acceptance tests** to verify all functionality
4. **Monitor usage** via CloudWatch dashboards
5. **Gather feedback** from pilot users
6. **Plan production deployment** after successful sandbox testing

---

## Document Information

- **Version**: 1.0
- **Last Updated**: 2025-11-16
- **Status**: Active
- **Audience**: DevOps, Salesforce Admins, Implementation Team

## Related Documentation

- [AWS Deployment Guide](../DEPLOYMENT.md)
- [Salesforce Deployment Guide](../salesforce/DEPLOYMENT_GUIDE.md)
- [Phase 2 Deployment Guide](../salesforce/PHASE2_DEPLOYMENT.md)
- [Phase 2 Acceptance Testing](./PHASE2_ACCEPTANCE_TESTING.md)
- [AppFlow Setup Guide](./APPFLOW_SETUP.md)
- [CDC Configuration Guide](./CDC_CONFIGURATION.md)
- [Monitoring Implementation](./MONITORING_IMPLEMENTATION.md)
