#!/bin/bash
# Monitor CDK deployment progress

while true; do
    # Check if all stacks are complete
    INCOMPLETE=$(aws cloudformation list-stacks \
        --stack-status-filter CREATE_IN_PROGRESS UPDATE_IN_PROGRESS \
        --no-cli-pager \
        --query 'StackSummaries[?contains(StackName, `SalesforceAISearch`)].StackName' \
        --output text 2>/dev/null)
    
    if [ -z "$INCOMPLETE" ]; then
        echo "✅ All stacks deployment complete!"
        
        # Show final status
        aws cloudformation list-stacks \
            --stack-status-filter CREATE_COMPLETE \
            --no-cli-pager \
            --query 'StackSummaries[?contains(StackName, `SalesforceAISearch`)].{Name:StackName,Status:StackStatus}' \
            --output table
        
        exit 0
    fi
    
    # Show current status
    echo "$(date '+%H:%M:%S') - Stacks still deploying: $INCOMPLETE"
    sleep 60
done
