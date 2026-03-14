#!/bin/bash

echo "Waiting for OpenSearch domain 'salesforce-ai-search' to be deleted..."
echo "This typically takes 10-15 minutes. Checking every 30 seconds..."
echo ""

COUNTER=0
MAX_ATTEMPTS=40  # 40 attempts * 30 seconds = 20 minutes max

while [ $COUNTER -lt $MAX_ATTEMPTS ]; do
    DOMAINS=$(aws opensearch list-domain-names --query 'DomainNames[?contains(DomainName, `salesforce`)].DomainName' --output text --no-cli-pager 2>&1)
    
    if [ -z "$DOMAINS" ]; then
        echo "✅ Domain deleted successfully!"
        exit 0
    fi
    
    COUNTER=$((COUNTER + 1))
    ELAPSED=$((COUNTER * 30))
    echo "[$ELAPSED seconds] Domain still exists, waiting..."
    sleep 30
done

echo "❌ Timeout: Domain deletion took longer than expected"
echo "Current status:"
aws opensearch describe-domain --domain-name salesforce-ai-search --query 'DomainStatus.{Processing:Processing,Deleted:Deleted}' --no-cli-pager 2>&1 || echo "Domain may be deleted"
exit 1
