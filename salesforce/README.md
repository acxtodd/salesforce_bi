# Salesforce AI Search POC - Salesforce Components

This directory contains all Salesforce metadata components for the AI Search POC.

## ⚠️ Important: Salesforce Instance Requirements

**You do NOT need a Salesforce instance yet!** 

This directory contains all the **configuration and deployment artifacts** you'll need when you're ready to deploy. You can continue AWS infrastructure development without a Salesforce org.

**When you WILL need a Salesforce instance:**
- ✅ **Now**: Continue AWS infrastructure development (no SF instance needed)
- ⏳ **Later**: Integration testing (Task 10.4, Task 14) - requires sandbox or developer org
- 🎯 **Production**: Final deployment (Task 24) - requires production org

See **[SALESFORCE_INSTANCE_REQUIREMENTS.md](./SALESFORCE_INSTANCE_REQUIREMENTS.md)** for detailed guidance on when and what type of Salesforce org you need.

## Directory Structure

```
salesforce/
├── apex/                           # Apex classes
│   ├── AscendixAISearchController.cls
│   ├── AISearchBatchExport.cls
│   └── AISearchBatchExportScheduler.cls
├── lwc/                            # Lightning Web Components
│   └── ascendixAiSearch/
├── namedCredentials/               # Named Credential for API Gateway
│   └── Ascendix_RAG_API.namedCredential-meta.xml
├── metadata/                       # Custom Metadata Types
│   └── AI_Search_Config__mdt.xml
├── objects/                        # Custom Objects
│   └── AI_Search_Export_Error__c.object
├── package.xml                     # Deployment package manifest
├── sfdx-project.json              # SFDX project configuration
├── deploy.sh                       # Automated deployment script
├── deployment-config.template.json # Configuration template
├── DEPLOYMENT_GUIDE.md            # Detailed deployment instructions
└── README.md                       # This file
```

## Quick Start

### 1. Prerequisites

- Salesforce CLI installed: `npm install -g @salesforce/cli`
- Access to Salesforce sandbox/org with System Administrator profile
- AWS infrastructure deployed (API Gateway endpoint and API key)
- Salesforce Private Connect configured (see DEPLOYMENT_GUIDE.md)

### 2. Configure Named Credential

Edit `namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml`:

```xml
<endpoint>https://YOUR_PRIVATELINK_ENDPOINT</endpoint>
<password>YOUR_API_KEY</password>
```

### 3. Deploy to Salesforce

#### Option A: Using the deployment script (recommended)

```bash
cd salesforce
./deploy.sh
```

Follow the prompts to:
1. Authenticate to your Salesforce org
2. Choose deployment type (validate, deploy all, or deploy specific components)
3. Verify deployment success

#### Option B: Using SFDX commands directly

```bash
# Authenticate
sfdx auth:web:login -a my-sandbox

# Validate deployment
sfdx force:source:deploy -x package.xml -u my-sandbox --checkonly

# Deploy all components
sfdx force:source:deploy -x package.xml -u my-sandbox
```

### 4. Post-Deployment Configuration

1. **Add LWC to Page Layouts**
   - Navigate to Lightning App Builder
   - Add `ascendixAiSearch` component to Account and Home pages
   - Save and activate

2. **Test Named Credential**
   - Setup > Named Credentials > Ascendix RAG API
   - Click "Test Connection"
   - Verify 200 OK response

3. **Assign Permissions**
   - Create permission set "AI Search User"
   - Grant access to AscendixAISearchController
   - Assign to pilot users

4. **Run Smoke Tests**
   - Navigate to an Account page
   - Submit test query: "Show open opportunities for this account"
   - Verify streaming response and citations

## Components Overview

### Lightning Web Component (LWC)

**ascendixAiSearch**: Main search interface component
- Features:
  - Natural language query input
  - Streaming answer display
  - Citations drawer with record links
  - Facet filters (Region, BU, Quarter)
  - Error handling and user feedback
- Location: `lwc/ascendixAiSearch/`
- Tests: `lwc/ascendixAiSearch/__tests__/`

### Apex Classes

**AscendixAISearchController**: Controller for LWC
- Handles callouts to AWS API Gateway
- Manages Named Credential authentication
- Processes streaming responses

**AISearchBatchExport**: Batch Apex for fallback data export
- Exports modified records when CDC is unavailable
- Calls AWS /ingest endpoint
- Logs errors to AI_Search_Export_Error__c

**AISearchBatchExportScheduler**: Schedulable class for batch export
- Schedules AISearchBatchExport to run off-peak
- Configurable schedule via Apex

### Named Credential

**Ascendix_RAG_API**: Secure connection to AWS API Gateway
- Authentication: API key in header (x-api-key)
- Endpoint: Private API Gateway via PrivateLink
- Protocol: HTTPS with TLS 1.2+

### Custom Objects

**AI_Search_Export_Error__c**: Error logging for batch exports
- Fields: Record_Id__c, Error_Message__c, Timestamp__c
- Used by AISearchBatchExport for troubleshooting

### Custom Metadata

**AI_Search_Config__mdt**: Configuration for search behavior
- Future use: Object and field configuration
- Phase 3: Dynamic object indexing

## Deployment Scenarios

### Sandbox Deployment

```bash
# Deploy to sandbox
sfdx auth:web:login -a sandbox
sfdx force:source:deploy -x package.xml -u sandbox
```

### Production Deployment

#### Via Change Set
1. Create outbound change set in sandbox
2. Include all components from package.xml
3. Upload to production
4. Deploy during maintenance window

#### Via SFDX
```bash
# Authenticate to production
sfdx auth:web:login -a production

# Validate first
sfdx force:source:deploy -x package.xml -u production --checkonly

# Deploy to production
sfdx force:source:deploy -x package.xml -u production
```

## Testing

### Unit Tests

Run LWC Jest tests:
```bash
cd lwc
npm install
npm test
```

### Integration Tests

1. **Named Credential Connectivity**
   - Setup > Named Credentials > Test Connection
   - Expected: 200 OK

2. **LWC Functionality**
   - Submit query on Account page
   - Verify streaming response
   - Verify citations display
   - Test facet filters

3. **Batch Export**
   - Execute AISearchBatchExport manually
   - Verify records exported to AWS
   - Check AI_Search_Export_Error__c for errors

### Smoke Tests

See `DEPLOYMENT_GUIDE.md` for comprehensive smoke test checklist.

## Troubleshooting

### Named Credential Test Fails

**Symptom**: Test Connection returns timeout or error

**Solutions**:
1. Verify Private Connect is configured and active
2. Check API Gateway endpoint URL is correct
3. Verify API key is valid
4. Check AWS security groups allow traffic

### LWC Not Visible

**Symptom**: Component doesn't appear on page

**Solutions**:
1. Verify component is added to page layout
2. Check page is activated and assigned to profile
3. Clear browser cache
4. Check browser console for errors

### No Search Results

**Symptom**: Queries return no results

**Solutions**:
1. Verify CDC pipeline is running (Task 8)
2. Check data has been ingested to OpenSearch
3. Verify user has access to records (sharing rules)
4. Check CloudWatch logs for errors

### Streaming Response Fails

**Symptom**: Query hangs or times out

**Solutions**:
1. Check API Gateway timeout settings (29s max)
2. Verify Lambda functions are not cold starting
3. Check Bedrock service availability
4. Review CloudWatch logs for Lambda errors

## Security Considerations

### Sensitive Data

- **Never commit** `deployment-config.json` with real values
- **Never commit** Named Credential with real API key
- Use `.gitignore` to exclude sensitive files
- Rotate API keys regularly (every 90 days)

### Access Control

- Limit Named Credential access to authorized users
- Use permission sets for granular access control
- Monitor API usage via CloudWatch
- Review audit logs regularly

### Network Security

- All traffic via Private Connect (no public internet)
- TLS 1.2+ encryption in transit
- API key authentication required
- VPC security groups restrict access

## Maintenance

### Regular Tasks

- **Weekly**: Review error logs in AI_Search_Export_Error__c
- **Monthly**: Review API usage and costs
- **Quarterly**: Rotate API keys
- **Annually**: Review and update permissions

### Monitoring

- CloudWatch dashboards for API performance
- Salesforce debug logs for Apex errors
- Browser console for LWC errors
- User feedback for quality issues

## Support

### Documentation

- **Deployment Guide**: `DEPLOYMENT_GUIDE.md` - Detailed deployment instructions
- **Design Document**: `../.kiro/specs/salesforce-ai-search-poc/design.md` - Architecture and design
- **Requirements**: `../.kiro/specs/salesforce-ai-search-poc/requirements.md` - Feature requirements
- **Tasks**: `../.kiro/specs/salesforce-ai-search-poc/tasks.md` - Implementation plan

### Getting Help

- **Salesforce Issues**: Check Setup > Debug Logs
- **AWS Issues**: Check CloudWatch Logs
- **LWC Issues**: Check browser console (F12)
- **Deployment Issues**: See DEPLOYMENT_GUIDE.md troubleshooting section

## Version History

- **v1.0** (2025-11-13): Initial POC release
  - LWC with streaming search
  - Named Credential for Private API Gateway
  - Batch export fallback
  - Basic error handling

## Future Enhancements

### Phase 2: Agent Actions
- Agent action Flows for record creation/updates
- Two-step confirmation UI
- Action audit logging
- Rate limiting

### Phase 3: Custom Object Configuration
- IndexConfiguration custom metadata
- Dynamic object and field indexing
- Admin UI for configuration
- Enhanced authorization

See `../.kiro/specs/salesforce-ai-search-poc/tasks.md` for complete roadmap.

## License

Internal use only - Ascendix Corporation

---

For detailed deployment instructions, see **DEPLOYMENT_GUIDE.md**.
