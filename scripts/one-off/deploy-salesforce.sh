#!/bin/bash

# Salesforce Deployment Script for AI Search POC
# This script automates the deployment of Salesforce metadata after AWS infrastructure is ready

set -e  # Exit on error

echo "========================================="
echo "Salesforce AI Search POC - Deployment"
echo "========================================="
echo ""

# Configuration
SF_ORG_ALIAS="ascendix-beta-sandbox"
SF_USERNAME="tterry@ascendix.com.agentforce.demo.beta"

# Check if Salesforce CLI is authenticated
echo "Checking Salesforce authentication..."
if ! sfdx org display --target-org $SF_ORG_ALIAS &>/dev/null; then
    echo "❌ Not authenticated to Salesforce org: $SF_ORG_ALIAS"
    echo "Please run: sfdx org login web --alias $SF_ORG_ALIAS"
    exit 1
fi

echo "✅ Authenticated to Salesforce org: $SF_USERNAME"
echo ""

# Get AWS outputs (these should be set as environment variables or passed as arguments)
if [ -z "$API_GATEWAY_ENDPOINT" ]; then
    echo "⚠️  API_GATEWAY_ENDPOINT not set. Please provide it:"
    read -p "API Gateway Endpoint URL: " API_GATEWAY_ENDPOINT
fi

if [ -z "$API_KEY" ]; then
    echo "⚠️  API_KEY not set. Please provide it:"
    read -p "API Key: " API_KEY
fi

echo "API Gateway Endpoint: $API_GATEWAY_ENDPOINT"
echo "API Key: ${API_KEY:0:10}..."
echo ""

# Update Named Credential with AWS outputs
echo "Step 1: Updating Named Credential configuration..."
cd salesforce

# Create a temporary file with updated values
cat namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml | \
    sed "s|https://REPLACE_WITH_PRIVATELINK_ENDPOINT_URL|$API_GATEWAY_ENDPOINT|g" | \
    sed "s|REPLACE_WITH_API_KEY|$API_KEY|g" > /tmp/Ascendix_RAG_API.namedCredential-meta.xml

# Replace the original file
mv /tmp/Ascendix_RAG_API.namedCredential-meta.xml namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml

echo "✅ Named Credential updated"
echo ""

# Deploy Phase 1 and Phase 2 metadata
echo "Step 2: Deploying Salesforce metadata (Phase 1 + Phase 2)..."
echo "This may take 5-10 minutes..."
echo ""

sfdx project deploy start \
    --manifest package.xml \
    --target-org $SF_ORG_ALIAS \
    --wait 20

if [ $? -eq 0 ]; then
    echo "✅ Salesforce metadata deployed successfully"
else
    echo "❌ Salesforce metadata deployment failed"
    exit 1
fi

echo ""
echo "Step 3: Verifying deployment..."

# Verify custom objects
echo "Checking custom objects..."
sfdx data query \
    --query "SELECT Id FROM AI_Action_Audit__c LIMIT 1" \
    --target-org $SF_ORG_ALIAS &>/dev/null && echo "  ✅ AI_Action_Audit__c" || echo "  ❌ AI_Action_Audit__c"

# Verify custom metadata
echo "Checking custom metadata..."
sfdx data query \
    --query "SELECT DeveloperName, Enabled__c FROM ActionEnablement__mdt" \
    --target-org $SF_ORG_ALIAS \
    --result-format human

echo ""
echo "========================================="
echo "✅ Salesforce Deployment Complete!"
echo "========================================="
echo ""
echo "Next Steps:"
echo "1. Configure Private Connect in Salesforce Setup"
echo "2. Test Named Credential connectivity"
echo "3. Add LWC to Account and Home page layouts"
echo "4. Assign permission sets to pilot users"
echo "5. Enable CDC for target objects"
echo "6. Run smoke tests"
echo ""

