#!/bin/bash

# Deploy Phase 2 Agent Actions metadata to Salesforce sandbox
# This script deploys custom objects, metadata types, and permission sets for Agent Actions

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Phase 2 Agent Actions Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if SFDX is installed
if ! command -v sfdx &> /dev/null; then
    echo -e "${RED}Error: SFDX CLI is not installed${NC}"
    echo "Please install SFDX CLI: https://developer.salesforce.com/tools/sfdxcli"
    exit 1
fi

# Check if org alias is provided
if [ -z "$1" ]; then
    echo -e "${YELLOW}Usage: ./deploy-phase2.sh <org-alias>${NC}"
    echo "Example: ./deploy-phase2.sh my-sandbox"
    exit 1
fi

ORG_ALIAS=$1

echo -e "${YELLOW}Deploying to org: ${ORG_ALIAS}${NC}"
echo ""

# Validate org connection
echo "Validating org connection..."
if ! sfdx force:org:display -u "$ORG_ALIAS" &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to org '${ORG_ALIAS}'${NC}"
    echo "Please authenticate first: sfdx force:auth:web:login -a ${ORG_ALIAS}"
    exit 1
fi
echo -e "${GREEN}✓ Org connection validated${NC}"
echo ""

# Deploy custom objects
echo "Deploying custom objects..."
sfdx force:source:deploy -u "$ORG_ALIAS" -p "objects/AI_Action_Audit__c.object" -w 10
echo -e "${GREEN}✓ AI_Action_Audit__c deployed${NC}"
echo ""

# Deploy custom metadata type
echo "Deploying custom metadata type..."
sfdx force:source:deploy -u "$ORG_ALIAS" -p "metadata/ActionEnablement__mdt.xml" -w 10
echo -e "${GREEN}✓ ActionEnablement__mdt deployed${NC}"
echo ""

# Deploy custom metadata records
echo "Deploying custom metadata records..."
sfdx force:source:deploy -u "$ORG_ALIAS" -p "customMetadata/" -w 10
echo -e "${GREEN}✓ Action metadata records deployed${NC}"
echo ""

# Deploy permission set
echo "Deploying permission set..."
sfdx force:source:deploy -u "$ORG_ALIAS" -p "permissionsets/AI_Agent_Actions_Editor.permissionset-meta.xml" -w 10
echo -e "${GREEN}✓ AI_Agent_Actions_Editor permission set deployed${NC}"
echo ""

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Verify deployment in Salesforce Setup"
echo "2. Assign AI_Agent_Actions_Editor permission set to pilot users"
echo "3. Test action enablement configuration"
echo ""
echo -e "${YELLOW}To assign permission set to a user:${NC}"
echo "sfdx force:user:permset:assign -n AI_Agent_Actions_Editor -u <username> -o ${ORG_ALIAS}"
echo ""
