#!/bin/bash
# Direct Bedrock Knowledge Base Testing Script
# Tests queries directly against the knowledge base

KNOWLEDGE_BASE_ID="HOOACWECEX"
REGION="us-west-2"

echo "=== Direct Bedrock Knowledge Base Query Test ==="
echo "Knowledge Base: $KNOWLEDGE_BASE_ID"
echo "Region: $REGION"
echo ""

# Function to run a query
run_query() {
    local query="$1"
    local description="$2"

    echo "Testing: $description"
    echo "Query: $query"
    echo "---"

    result=$(aws bedrock-agent-runtime retrieve \
        --knowledge-base-id "$KNOWLEDGE_BASE_ID" \
        --retrieval-query "{\"text\": \"$query\"}" \
        --region "$REGION" \
        --no-cli-pager \
        --output json 2>/dev/null)

    if [ $? -eq 0 ]; then
        # Count results
        count=$(echo "$result" | jq '.retrievalResults | length')
        echo "✅ Results found: $count"

        # Show first result preview
        if [ "$count" -gt 0 ]; then
            echo "First result preview:"
            echo "$result" | jq -r '.retrievalResults[0] | {
                score: .score,
                sobject: .metadata.sobject,
                recordId: .metadata.recordId,
                preview: (.content.text[:100] + "...")
            }'
        fi
    else
        echo "❌ Query failed"
    fi
    echo ""
}

# Test queries
echo "=== Running Test Queries ==="
echo ""

# Single object queries
run_query "properties in Dallas" "Single Object - Properties by City"
run_query "open deals" "Single Object - Deal Status"
run_query "Class A office buildings" "Single Object - Property Class"
run_query "leases expiring" "Temporal - Lease Expiration"

# Cross-object queries
run_query "properties Dallas available space" "Cross-Object - Property + Availability"
run_query "deals properties New York" "Cross-Object - Deal + Property"

# Specific entity queries
run_query "17Seventeen McKinney" "Specific - Property Name"
run_query "StorQuest Self Storage" "Specific - Client Name"

echo "=== Test Complete ==="