#!/bin/bash

# Verify Phase 2 Agent Actions deployment
# This script runs verification tests to ensure all components are properly deployed

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Phase 2 Deployment Verification${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if org alias is provided
if [ -z "$1" ]; then
    echo -e "${YELLOW}Usage: ./verify-phase2-deployment.sh <org-alias>${NC}"
    echo "Example: ./verify-phase2-deployment.sh my-sandbox"
    exit 1
fi

ORG_ALIAS=$1
ERRORS=0

echo -e "${YELLOW}Verifying deployment in org: ${ORG_ALIAS}${NC}"
echo ""

# Test 1: Verify AI_Action_Audit__c object exists
echo "Test 1: Verifying AI_Action_Audit__c custom object..."
if sfdx force:data:soql:query -u "$ORG_ALIAS" -q "SELECT Id, Name FROM AI_Action_Audit__c LIMIT 1" &> /dev/null; then
    echo -e "${GREEN}✓ AI_Action_Audit__c object is accessible${NC}"
else
    echo -e "${RED}✗ AI_Action_Audit__c object not found or not accessible${NC}"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Test 2: Verify ActionEnablement__mdt metadata type exists
echo "Test 2: Verifying ActionEnablement__mdt metadata type..."
METADATA_COUNT=$(sfdx force:data:soql:query -u "$ORG_ALIAS" -q "SELECT COUNT() FROM ActionEnablement__mdt" --json | grep -o '"totalSize":[0-9]*' | grep -o '[0-9]*')
if [ "$METADATA_COUNT" -ge 2 ]; then
    echo -e "${GREEN}✓ ActionEnablement__mdt has $METADATA_COUNT records (expected: 2)${NC}"
else
    echo -e "${RED}✗ ActionEnablement__mdt has $METADATA_COUNT records (expected: 2)${NC}"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Test 3: Verify create_opportunity action configuration
echo "Test 3: Verifying create_opportunity action configuration..."
CREATE_OPP=$(sfdx force:data:soql:query -u "$ORG_ALIAS" -q "SELECT ActionName__c, Enabled__c, FlowName__c FROM ActionEnablement__mdt WHERE ActionName__c = 'create_opportunity'" --json)
if echo "$CREATE_OPP" | grep -q "create_opportunity"; then
    echo -e "${GREEN}✓ create_opportunity action is configured${NC}"
    if echo "$CREATE_OPP" | grep -q '"Enabled__c":true'; then
        echo -e "${GREEN}  - Enabled: true${NC}"
    else
        echo -e "${YELLOW}  - Enabled: false (action is disabled)${NC}"
    fi
else
    echo -e "${RED}✗ create_opportunity action not found${NC}"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Test 4: Verify update_opportunity_stage action configuration
echo "Test 4: Verifying update_opportunity_stage action configuration..."
UPDATE_OPP=$(sfdx force:data:soql:query -u "$ORG_ALIAS" -q "SELECT ActionName__c, Enabled__c, FlowName__c FROM ActionEnablement__mdt WHERE ActionName__c = 'update_opportunity_stage'" --json)
if echo "$UPDATE_OPP" | grep -q "update_opportunity_stage"; then
    echo -e "${GREEN}✓ update_opportunity_stage action is configured${NC}"
    if echo "$UPDATE_OPP" | grep -q '"Enabled__c":true'; then
        echo -e "${GREEN}  - Enabled: true${NC}"
    else
        echo -e "${YELLOW}  - Enabled: false (action is disabled)${NC}"
    fi
else
    echo -e "${RED}✗ update_opportunity_stage action not found${NC}"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Test 5: Verify AI_Agent_Actions_Editor permission set exists
echo "Test 5: Verifying AI_Agent_Actions_Editor permission set..."
if sfdx force:data:soql:query -u "$ORG_ALIAS" -q "SELECT Id, Name FROM PermissionSet WHERE Name = 'AI_Agent_Actions_Editor' LIMIT 1" &> /dev/null; then
    echo -e "${GREEN}✓ AI_Agent_Actions_Editor permission set exists${NC}"
    
    # Check if any users have the permission set assigned
    ASSIGNED_USERS=$(sfdx force:data:soql:query -u "$ORG_ALIAS" -q "SELECT COUNT() FROM PermissionSetAssignment WHERE PermissionSet.Name = 'AI_Agent_Actions_Editor'" --json | grep -o '"totalSize":[0-9]*' | grep -o '[0-9]*')
    if [ "$ASSIGNED_USERS" -gt 0 ]; then
        echo -e "${GREEN}  - Assigned to $ASSIGNED_USERS user(s)${NC}"
    else
        echo -e "${YELLOW}  - Not assigned to any users yet${NC}"
    fi
else
    echo -e "${RED}✗ AI_Agent_Actions_Editor permission set not found${NC}"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Test 6: Verify AI_Action_Audit__c field structure
echo "Test 6: Verifying AI_Action_Audit__c field structure..."
FIELDS=$(sfdx force:schema:sobject:describe -u "$ORG_ALIAS" -s AI_Action_Audit__c --json | grep -o '"name":"[^"]*"' | wc -l)
if [ "$FIELDS" -ge 9 ]; then
    echo -e "${GREEN}✓ AI_Action_Audit__c has $FIELDS fields (expected: 9+)${NC}"
else
    echo -e "${RED}✗ AI_Action_Audit__c has $FIELDS fields (expected: 9+)${NC}"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Summary
echo -e "${GREEN}========================================${NC}"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}All verification tests passed!${NC}"
    echo -e "${GREEN}Phase 2 deployment is successful.${NC}"
else
    echo -e "${RED}Verification failed with $ERRORS error(s)${NC}"
    echo -e "${YELLOW}Please review the errors above and redeploy if necessary.${NC}"
fi
echo -e "${GREEN}========================================${NC}"
echo ""

exit $ERRORS
