#!/bin/bash
# Salesforce AI Search POC - Deployment Audit Script
# This script audits what components are deployed to the Salesforce org

ORG_ALIAS="ascendix-beta-sandbox"

echo "========================================="
echo "Salesforce AI Search POC - Deployment Audit"
echo "========================================="
echo ""
echo "Target Org: $ORG_ALIAS"
echo "Date: $(date)"
echo ""

# Check org connection
echo "1. Checking org connection..."
sf org display --target-org $ORG_ALIAS --json > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✅ Connected to org"
else
    echo "❌ Not connected to org"
    exit 1
fi
echo ""

# Check Apex Classes
echo "2. Checking Apex Classes..."
echo "   Looking for AI Search related classes..."
APEX_CLASSES=$(sf data query --query "SELECT Id, Name, Status FROM ApexClass WHERE Name IN ('AISearchBatchExport', 'AISearchBatchExportScheduler', 'AISearchBatchExportTest', 'AISearchBatchExportSchedulerTest', 'ActionEnablementController', 'ActionEnablementControllerTest', 'ActionPermissionSetRemoval', 'ActionPermissionSetRemovalTest', 'Action_GraphQLProxy', 'Action_GraphQLProxyTest', 'AscendixAISearchController', 'AscendixAISearchControllerTest') ORDER BY Name" --target-org $ORG_ALIAS --json 2>/dev/null)

APEX_COUNT=$(echo "$APEX_CLASSES" | jq -r '.result.totalSize // 0')
echo "   Found $APEX_COUNT Apex classes"

if [ "$APEX_COUNT" -gt 0 ]; then
    echo "$APEX_CLASSES" | jq -r '.result.records[] | "   ✅ \(.Name) - \(.Status)"'
else
    echo "   ❌ No AI Search Apex classes found"
fi
echo ""

# Check LWC Components
echo "3. Checking Lightning Web Components..."
LWC_QUERY=$(sf data query --use-tooling-api --query "SELECT Id, DeveloperName, MasterLabel FROM LightningComponentBundle WHERE DeveloperName IN ('ascendixAiSearch', 'actionEnablementAdmin') ORDER BY DeveloperName" --target-org $ORG_ALIAS --json 2>/dev/null)

LWC_COUNT=$(echo "$LWC_QUERY" | jq -r '.result.totalSize // 0')
echo "   Found $LWC_COUNT LWC components"

if [ "$LWC_COUNT" -gt 0 ]; then
    echo "$LWC_QUERY" | jq -r '.result.records[] | "   ✅ \(.DeveloperName) - \(.MasterLabel)"'
else
    echo "   ❌ No AI Search LWC components found"
fi
echo ""

# Check Custom Objects
echo "4. Checking Custom Objects..."
CUSTOM_OBJECTS=$(sf data query --query "SELECT Id, QualifiedApiName, Label FROM EntityDefinition WHERE QualifiedApiName IN ('AI_Action_Audit__c', 'AI_Search_Export_Error__c', 'ActionEnablementSetting__c', 'ActionEnablement__mdt', 'AI_Search_Config__mdt') ORDER BY QualifiedApiName" --target-org $ORG_ALIAS --json 2>/dev/null)

OBJECT_COUNT=$(echo "$CUSTOM_OBJECTS" | jq -r '.result.totalSize // 0')
echo "   Found $OBJECT_COUNT custom objects"

if [ "$OBJECT_COUNT" -gt 0 ]; then
    echo "$CUSTOM_OBJECTS" | jq -r '.result.records[] | "   ✅ \(.QualifiedApiName) - \(.Label)"'
else
    echo "   ❌ No AI Search custom objects found"
fi
echo ""

# Check Flows
echo "5. Checking Flows..."
FLOWS=$(sf data query --use-tooling-api --query "SELECT Id, DeveloperName, MasterLabel FROM FlowDefinition WHERE DeveloperName IN ('Create_Opportunity_Flow', 'Update_Opportunity_Stage_Flow', 'Remove_AI_Agent_Actions_Permission_Set') ORDER BY DeveloperName" --target-org $ORG_ALIAS --json 2>/dev/null)

FLOW_COUNT=$(echo "$FLOWS" | jq -r '.result.totalSize // 0')
echo "   Found $FLOW_COUNT flows"

if [ "$FLOW_COUNT" -gt 0 ]; then
    echo "$FLOWS" | jq -r '.result.records[] | "   ✅ \(.DeveloperName)"'
else
    echo "   ❌ No AI Search flows found"
fi
echo ""

# Check Named Credentials
echo "6. Checking Named Credentials..."
NAMED_CREDS=$(sf data query --query "SELECT Id, DeveloperName, MasterLabel FROM NamedCredential WHERE DeveloperName IN ('Ascendix_RAG_API', 'Salesforce_GraphQL') ORDER BY DeveloperName" --target-org $ORG_ALIAS --json 2>/dev/null)

NC_COUNT=$(echo "$NAMED_CREDS" | jq -r '.result.totalSize // 0')
echo "   Found $NC_COUNT named credentials"

if [ "$NC_COUNT" -gt 0 ]; then
    echo "$NAMED_CREDS" | jq -r '.result.records[] | "   ✅ \(.DeveloperName)"'
else
    echo "   ❌ No AI Search named credentials found"
fi
echo ""

# Check Permission Sets
echo "7. Checking Permission Sets..."
PERM_SETS=$(sf data query --query "SELECT Id, Name, Label FROM PermissionSet WHERE Name IN ('AI_Agent_Actions_Editor') ORDER BY Name" --target-org $ORG_ALIAS --json 2>/dev/null)

PS_COUNT=$(echo "$PERM_SETS" | jq -r '.result.totalSize // 0')
echo "   Found $PS_COUNT permission sets"

if [ "$PS_COUNT" -gt 0 ]; then
    echo "$PERM_SETS" | jq -r '.result.records[] | "   ✅ \(.Name) - \(.Label)"'
else
    echo "   ❌ No AI Search permission sets found"
fi
echo ""

# Summary
echo "========================================="
echo "DEPLOYMENT AUDIT SUMMARY"
echo "========================================="
echo "Apex Classes:          $APEX_COUNT / 12 expected"
echo "LWC Components:        $LWC_COUNT / 2 expected"
echo "Custom Objects:        $OBJECT_COUNT / 5 expected"
echo "Flows:                 $FLOW_COUNT / 3 expected"
echo "Named Credentials:     $NC_COUNT / 2 expected"
echo "Permission Sets:       $PS_COUNT / 1 expected"
echo ""

TOTAL_FOUND=$((APEX_COUNT + LWC_COUNT + OBJECT_COUNT + FLOW_COUNT + NC_COUNT + PS_COUNT))
TOTAL_EXPECTED=25

if [ "$TOTAL_FOUND" -eq "$TOTAL_EXPECTED" ]; then
    echo "✅ DEPLOYMENT COMPLETE: All $TOTAL_EXPECTED components found"
elif [ "$TOTAL_FOUND" -eq 0 ]; then
    echo "❌ DEPLOYMENT NOT STARTED: No components found"
else
    echo "⚠️  PARTIAL DEPLOYMENT: $TOTAL_FOUND / $TOTAL_EXPECTED components found"
fi
echo ""
