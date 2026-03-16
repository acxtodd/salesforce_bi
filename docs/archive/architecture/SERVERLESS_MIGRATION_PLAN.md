# OpenSearch Serverless Migration Plan

**Date**: 2025-11-18  
**Owners**: Task 24.2.3 (Production Deployment)

## Why We Need This

- Bedrock Knowledge Bases with `OPENSEARCH_MANAGED_CLUSTER` **require a public endpoint**. Our OpenSearch domain is VPC-isolated for security reasons, so Bedrock rejects the configuration with:  
  `"The OpenSearch Managed Cluster you provided is not supported because it is VPC protected. Your cluster must be behind a public network."`
- Keeping the domain public is not acceptable, and AWS has not yet released VPC support for managed clusters.  
- Bedrock already supports **OpenSearch Serverless (AOSS)** for private deployments via VPC endpoints. The original fallback plan in `DEPLOYMENT_BLOCKER.md` referenced this option.

## Remediation Overview

| Step | Area | Description |
|------|------|-------------|
| 1 | Cleanup | Delete the failed managed-domain stack + domain (same order as documented) so the environment is clean. |
| 2 | CDK Code | Replace the managed OpenSearch domain with a Serverless collection, security policies, and VPC endpoint configuration. Update the Bedrock KB storage block to `OPENSEARCH_SERVERLESS`. |
| 3 | Documentation | Update deployment guides and task notes to describe the Serverless architecture and commands. |
| 4 | Redeploy | `cdk deploy` Search/Ingestion/Api/Monitoring stacks. Expect ~25 minutes total. |
| 5 | Resume Tasks | Continue with Task 24.2.4 (capture outputs) and downstream Salesforce deployment steps. |

## Detailed Work Items

### 1. Cleanup (pre-work)

```bash
aws opensearch delete-domain --domain-name salesforce-ai-search || true
aws opensearch wait domain-not-exists --domain-name salesforce-ai-search || true

aws cloudformation delete-stack --stack-name SalesforceAISearch-Search-dev || true
aws cloudformation wait stack-delete-complete --stack-name SalesforceAISearch-Search-dev || true
```

### 2. CDK Updates

1. **`lib/search-stack.ts`**
   - Remove `opensearch.Domain`, security group, and managed-cluster role logic.
   - Add AOSS constructs:
     - `CfnCollection` (type `VECTORSEARCH`)
     - Security policy, access policy
     - Optional `CfnVpcEndpoint` referencing the existing VPC + subnets
   - Configure Bedrock KB to use:
     ```ts
     storageConfiguration: {
       type: "OPENSEARCH_SERVERLESS",
       opensearchServerlessConfiguration: {
         collectionArn: collection.attrArn,
         vectorIndexName: "salesforce-chunks",
         fieldMapping: { ... }
       }
     }
     ```
   - Grant the knowledge-base role `aoss:APIAccessAll` (or fine-grained `aoss:ReadDocument` / `aoss:WriteDocument` etc.) on the collection.

2. **`lib/network-stack.ts`**
   - Retain/confirm the interface endpoint for `aoss` (Serverless). Remove obsolete managed-domain references.

3. **Other stacks**
   - Monitoring stack: adjust metrics/alarms to use Serverless endpoints if referenced.

### 3. Documentation Updates

- `docs/SEARCH_STACK_DEPLOYMENT.md`: describe the serverless architecture, deployment commands, and verification steps.
- `.kiro/specs/salesforce-ai-search-poc/tasks.md`: note that Task 24.2.3 requires switching to Serverless, referencing this plan.
- `README_DEPLOYMENT.md` / `FINAL_STATUS.md`: point to this migration document for next steps.

### 4. Redeploy

```bash
rm -rf cdk.out
npm run build
npx cdk synth

npx cdk deploy SalesforceAISearch-Search-dev \
  SalesforceAISearch-Ingestion-dev \
  SalesforceAISearch-Api-dev \
  SalesforceAISearch-Monitoring-dev \
  --require-approval never
```

### 5. Resume Task 24 workflow

Once SearchStack succeeds:

1. Task 24.2.4 – capture and store stack outputs (`DEPLOYMENT_OUTPUTS.md`).
2. Task 24.2.5 – verify AWS deployment.
3. Task 24.3 – Salesforce metadata deployment, followed by Private Connect, CDC, smoke tests, etc.

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| New AOSS constructs unfamiliar | Follow AWS samples; use `CfnCollection` + AWS docs. |
| Need to reconfigure monitoring/logging | Update metrics post-migration. |
| Temporarily re-ingest data | Expect one-time re-index after switch. |

## References

- `DEPLOYMENT_BLOCKER.md` – earlier Serverless fallback notes
- AWS docs: [Bedrock Knowledge Bases storage types](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
- AWS docs: [OpenSearch Serverless](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)

