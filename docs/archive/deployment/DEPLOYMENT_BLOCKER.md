# Deployment Blocker: CloudFormation Schema Limitation

## Status: BLOCKED
**Date**: 2025-11-17  
**Task**: 24.2.3 Deploy all AWS stacks  
**Blocker**: CloudFormation in us-west-2 does not support `OPENSEARCH` storage type for Bedrock Knowledge Bases

---

## Problem Statement

AWS CloudFormation is rejecting the deployment of `AWS::Bedrock::KnowledgeBase` resources configured with managed OpenSearch domains (`storageConfiguration.type = "OPENSEARCH"`), despite AWS documentation stating this feature is Generally Available as of March 27, 2025.

### Error Message
```
Properties validation failed for resource KnowledgeBase with message:
#/StorageConfiguration: #: only 1 subschema matches out of 2
#/StorageConfiguration/Type: #: only 1 subschema matches out of 2
#/StorageConfiguration/Type: failed validation constraint for keyword [enum]
```

### Impact
- **SearchStack deployment**: FAILED
- **Remaining stacks**: BLOCKED (IngestionStack, ApiStack, MonitoringStack depend on SearchStack)
- **Task 24.2.3**: Cannot complete
- **Downstream tasks**: 24.2.4+ blocked

---

## Root Cause Analysis

### What We Know
1. **AWS Announcement**: March 27, 2025 - "Amazon Bedrock Knowledge Bases now supports Amazon OpenSearch Service clusters as vector storage"
   - Source: https://aws.amazon.com/about-aws/whats-new/2025/03/amazon-bedrock-knowledge-bases-opensearch-cluster-vector-storage/

2. **CloudFormation Documentation**: Lists `OPENSEARCH` as valid storage type
   - Property: `AWS::Bedrock::KnowledgeBase.StorageConfiguration.Type`
   - Expected values: OPENSEARCH_SERVERLESS, OPENSEARCH, PINECONE, REDIS_ENTERPRISE_CLOUD, RDS

3. **Actual Behavior**: CloudFormation schema validator in us-west-2 rejects `OPENSEARCH` as invalid enum value

### Why This Is Happening
- **Regional Rollout**: Feature may not be enabled in us-west-2 yet
- **Account-Level Feature Flag**: Feature may require explicit enablement for account 382211616288
- **Schema Update Lag**: CloudFormation service schema may not be updated despite API support

### What We've Tried
1. ✅ Verified CDK configuration is correct (`opensearchManagedClusterConfiguration`)
2. ✅ Confirmed AWS CLI is up to date (v2.31.1)
3. ✅ Validated CloudFormation template syntax
4. ✅ Checked IAM permissions (all correct)
5. ❌ Deployment still fails at CloudFormation validation layer

---

## Resolution Paths

### Path 1: AWS Support Case (RECOMMENDED)
**Status**: Prepared, ready to submit  
**File**: AWS_SUPPORT_CASE.md  
**Expected Timeline**: 1-3 business days

**Actions**:
1. Submit support case requesting feature enablement
2. Provide stack events, template, and documentation references
3. Request account-level or regional enablement
4. Get timeline for us-west-2 rollout

**Pros**:
- Aligns with intended architecture (managed OpenSearch)
- No code changes needed once enabled
- Maintains consistency with documentation

**Cons**:
- Blocks progress until AWS responds
- Timeline uncertain

### Path 2: OpenSearch Serverless Fallback (UNBLOCK)
**Status**: Ready to implement  
**Expected Timeline**: 2-4 hours

**Actions**:
1. Revert SearchStack to OpenSearch Serverless
2. Create proper VPC endpoint (`AWS::OpenSearchServerless::VpcEndpoint`)
3. Update network policy with VPC endpoint ID
4. Fix IAM data access policy for Bedrock and Lambdas
5. Update all documentation and scripts
6. Deploy and validate

**Pros**:
- Unblocks task 24.2.3 immediately
- Known working configuration (used by existing KBs)
- Can revert to managed OpenSearch later

**Cons**:
- Diverges from intended architecture
- Requires documentation updates
- Different operational characteristics (OCU-based pricing)
- Additional work to revert later

### Path 3: Deploy Without Bedrock Knowledge Base (NOT RECOMMENDED)
**Status**: Not pursued  
**Reason**: Bedrock KB is core to design

---

## Decision Matrix

| Criteria | AWS Support | Serverless Fallback |
|----------|-------------|---------------------|
| Time to Unblock | 1-3 days | 2-4 hours |
| Architecture Alignment | ✅ Perfect | ⚠️ Temporary divergence |
| Code Changes | None | Moderate |
| Documentation Updates | None | Extensive |
| Risk | Low | Low |
| Reversibility | N/A | Easy (redeploy SearchStack) |

---

## Recommended Action Plan

### Immediate (Next 1 hour)
1. ✅ Document blocker (this file)
2. ✅ Prepare AWS Support case
3. ⏳ Submit AWS Support case
4. ⏳ Begin Serverless fallback implementation in parallel

### Short Term (Next 4 hours)
1. Complete Serverless implementation
2. Update documentation
3. Deploy and validate SearchStack
4. Continue with tasks 24.2.4+

### Medium Term (1-3 days)
1. Monitor AWS Support case
2. Test managed OpenSearch once enabled
3. Revert to managed OpenSearch
4. Update documentation back to managed architecture

---

## Technical Details

### Current Configuration (Managed OpenSearch - BLOCKED)
```typescript
storageConfiguration: {
  type: "OPENSEARCH",  // ❌ Rejected by CloudFormation
  opensearchManagedClusterConfiguration: {
    domainArn: this.openSearchDomain.domainArn,
    domainEndpoint: `https://${this.openSearchDomain.domainEndpoint}/`,
    vectorIndexName: "salesforce-chunks",
    fieldMapping: {
      vectorField: "embedding",
      textField: "text",
      metadataField: "metadata",
    },
  },
}
```

### Fallback Configuration (Serverless - WORKING)
```typescript
storageConfiguration: {
  type: "OPENSEARCH_SERVERLESS",  // ✅ Accepted by CloudFormation
  opensearchServerlessConfiguration: {
    collectionArn: this.openSearchCollection.attrArn,
    vectorIndexName: "salesforce-chunks",
    fieldMapping: {
      vectorField: "embedding",
      textField: "text",
      metadataField: "metadata",
    },
  },
}
```

---

## Stakeholder Communication

### Status Update Template
```
Subject: Deployment Blocker - AWS CloudFormation Limitation

Status: BLOCKED on Task 24.2.3

Issue: CloudFormation in us-west-2 does not support the newly announced 
managed OpenSearch integration for Bedrock Knowledge Bases, despite AWS 
documentation stating it's GA.

Actions Taken:
- Verified configuration is correct per AWS documentation
- Prepared AWS Support case for feature enablement
- Designed Serverless fallback to unblock progress

Next Steps:
1. Submit AWS Support case (ETA: 1-3 days for response)
2. Implement Serverless fallback (ETA: 4 hours)
3. Continue deployment with Serverless configuration
4. Revert to managed OpenSearch once AWS enables feature

Impact: 4-hour delay to implement fallback, no impact to final functionality
```

---

## Lessons Learned

1. **Feature Announcements ≠ Immediate Availability**: GA announcements may have regional rollout delays
2. **CloudFormation Lags Behind APIs**: Service APIs may support features before CloudFormation schemas update
3. **Always Have Fallback Plans**: Critical deployments should have alternative architectures ready
4. **Document Blockers Thoroughly**: Clear documentation helps with support cases and team communication

---

## References

- AWS Announcement: https://aws.amazon.com/about-aws/whats-new/2025/03/amazon-bedrock-knowledge-bases-opensearch-cluster-vector-storage/
- CloudFormation Docs: AWS::Bedrock::KnowledgeBase
- Support Case: AWS_SUPPORT_CASE.md
- Stack Events: Captured in deployment logs
- Task Tracking: .kiro/specs/salesforce-ai-search-poc/tasks.md (Task 24.2.3)
