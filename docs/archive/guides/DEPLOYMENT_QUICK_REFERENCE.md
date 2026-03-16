# Deployment Quick Reference Card

## Essential Commands

### AWS Deployment
```bash
# Bootstrap CDK (first time only)
cdk bootstrap aws://ACCOUNT_ID/REGION

# Install dependencies
npm install

# Synthesize templates
npm run synth

# Deploy all stacks
npm run deploy

# Get API Gateway endpoint
aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-API-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiGatewayEndpoint`].OutputValue' \
  --output text --no-cli-pager

# Get API Key
API_KEY_ID=$(aws cloudformation describe-stacks \
  --stack-name SalesforceAISearch-API-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiKeyId`].OutputValue' \
  --output text --no-cli-pager)
aws apigateway get-api-key --api-key $API_KEY_ID --include-value --no-cli-pager --query 'value' --output text
```

### Salesforce Deployment
```bash
# Authenticate
sfdx auth:web:login -a target-org

# Deploy Phase 1
sfdx force:source:deploy -x package.xml -u target-org

# Deploy Phase 2 objects
sfdx force:source:deploy -u target-org -p objects/AI_Action_Audit__c.object -w 10

# Deploy Phase 2 metadata
sfdx force:source:deploy -u target-org -p metadata/ActionEnablement__mdt.xml -w 10

# Deploy Phase 2 flows
sfdx force:source:deploy -u target-org -p flows/ -w 10

# Assign permission set
sfdx force:user:permset:assign -n AI_Agent_Actions_Editor -u user@company.com -o target-org
```

### Verification Commands
```bash
# Check VPC endpoints
aws ec2 describe-vpc-endpoints --filters "Name=vpc-id,Values=$VPC_ID" --query 'VpcEndpoints[*].[ServiceName,State]' --output table --no-cli-pager

# Check S3 buckets
aws s3 ls --no-cli-pager | grep salesforce-ai-search

# Check DynamoDB tables
aws dynamodb list-tables --no-cli-pager | grep salesforce-ai-search

# Check Lambda functions
aws lambda list-functions --query 'Functions[?contains(FunctionName, `salesforce-ai-search`)].FunctionName' --no-cli-pager

# Verify Salesforce metadata
sfdx force:data:soql:query -q "SELECT DeveloperName, Enabled__c FROM ActionEnablement__mdt" -u target-org
```

## Critical Values to Capture

| Value | Command | Save As |
|-------|---------|---------|
| API Gateway Endpoint | See AWS Deployment above | API_GATEWAY_ENDPOINT |
| API Key | See AWS Deployment above | API_KEY |
| VPC Endpoint Service Name | `aws cloudformation describe-stacks --stack-name SalesforceAISearch-API-dev --query 'Stacks[0].Outputs[?OutputKey==\`VpcEndpointServiceName\`].OutputValue' --output text --no-cli-pager` | VPC_ENDPOINT_SERVICE_NAME |

## Deployment Timeline

| Stack | Expected Time | Status |
|-------|---------------|--------|
| NetworkStack | ~7 min | ☐ |
| DataStack | ~5 min | ☐ |
| SearchStack | ~10 min | ☐ |
| APIStack | ~8 min | ☐ |
| IngestionStack | ~5 min | ☐ |
| MonitoringStack | ~3 min | ☐ |
| **Total** | **~38 min** | |

## Smoke Test Checklist

- [ ] Navigate to Account record page
- [ ] Verify AI Search component appears
- [ ] Submit query: "Show open opportunities for this account"
- [ ] Verify streaming response
- [ ] Verify citations appear
- [ ] Click citation, verify preview opens
- [ ] Submit action query: "Create opportunity for ACME worth $500K"
- [ ] Verify preview modal appears
- [ ] Click Confirm, verify success
- [ ] Check browser console (F12) - no errors

## Performance Targets

| Metric | Target | Actual |
|--------|--------|--------|
| First Token Latency (p95) | ≤800ms | _____ |
| End-to-End Latency (p95) | ≤4.0s | _____ |
| CDC Freshness Lag (P50) | ≤5min | _____ |
| Precision@5 | ≥70% | _____ |

## Emergency Contacts

| Role | Name | Contact |
|------|------|---------|
| DevOps Lead | _________ | _________ |
| Salesforce Admin | _________ | _________ |
| AWS Support | _________ | _________ |
| Salesforce Support | _________ | _________ |

## Rollback Commands

```bash
# Disable actions in Salesforce
# Setup > Custom Metadata Types > ActionEnablement
# Set Enabled__c = false for all records

# Disable Named Credential
# Setup > Named Credentials > Ascendix RAG API
# Uncheck "Enabled"

# Delete AWS stacks (if needed)
cdk destroy --all
```

## Troubleshooting Quick Fixes

**Named Credential test fails**:
- Check Private Connect status is "Active"
- Verify API key is correct
- Check VPC Endpoint Service accepts connections

**No search results**:
- Verify initial data export completed
- Check AppFlow is running
- Check Bedrock KB sync status

**Actions fail**:
- Verify Flows are active
- Check Action Lambda logs
- Verify user has permission set

## Documentation Links

- [Full Deployment Guide](./PRODUCTION_DEPLOYMENT_GUIDE.md)
- [Sandbox Installation](./SANDBOX_INSTALLATION_GUIDE.md)
- [Phase 2 Testing](./PHASE2_ACCEPTANCE_TESTING.md)
- [Readiness Checklist](./DEPLOYMENT_READINESS_CHECKLIST.md)

