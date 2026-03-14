#!/bin/bash
# Quick deployment status checker

echo "=== CDK Deployment Status ==="
echo ""

# Check each stack
for stack in Network Data Search Ingestion Api Monitoring; do
    stack_name="SalesforceAISearch-${stack}-dev"
    status=$(aws cloudformation describe-stacks --stack-name "$stack_name" --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "NOT_FOUND")
    
    if [ "$status" = "CREATE_COMPLETE" ] || [ "$status" = "UPDATE_COMPLETE" ]; then
        echo "✅ ${stack}Stack: $status"
    elif [ "$status" = "CREATE_IN_PROGRESS" ] || [ "$status" = "UPDATE_IN_PROGRESS" ]; then
        echo "🔄 ${stack}Stack: $status"
        # Show resource progress
        complete=$(aws cloudformation describe-stack-resources --stack-name "$stack_name" --query 'StackResources[?ResourceStatus==`CREATE_COMPLETE`] | length(@)' --output text 2>/dev/null)
        total=$(aws cloudformation describe-stack-resources --stack-name "$stack_name" --query 'length(StackResources)' --output text 2>/dev/null)
        echo "   Progress: $complete/$total resources"
    elif [ "$status" = "NOT_FOUND" ]; then
        echo "⏳ ${stack}Stack: Not started"
    else
        echo "❌ ${stack}Stack: $status"
    fi
done

echo ""
echo "=== Latest Events ==="
aws cloudformation describe-stack-events --stack-name SalesforceAISearch-Search-dev --max-items 3 --query 'StackEvents[].{Time:Timestamp,Status:ResourceStatus,Type:ResourceType}' --output table --no-cli-pager 2>/dev/null || echo "No events available"
