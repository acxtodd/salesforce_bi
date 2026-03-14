# Schema Discovery Lambda - Salesforce Credentials Setup

This guide documents how to configure the Schema Discovery Lambda for automated Salesforce authentication using OAuth 2.0 Client Credentials flow.

## Overview

The Schema Discovery Lambda (`salesforce-ai-search-schema-discovery`) requires Salesforce API access to discover object schemas via the Describe API. This guide covers two authentication methods:

1. **Manual Token Refresh** (Current) - Using SF CLI to refresh access tokens
2. **Automated Client Credentials** (Recommended) - Using a Connected App for automatic token management

## Prerequisites

- AWS CLI configured with appropriate permissions
- SF CLI authenticated to the target Salesforce org
- Access to Salesforce Setup (for Connected App configuration)

## Current Configuration

### Lambda Environment Variables

| Variable | Description | Current Value |
|----------|-------------|---------------|
| `SALESFORCE_INSTANCE_URL` | Salesforce org URL | `https://ascendix-agentforce-demo--beta.sandbox.my.salesforce.com` |
| `SCHEMA_CACHE_TABLE` | DynamoDB table for schema cache | `salesforce-ai-search-schema-cache` |
| `SALESFORCE_ACCESS_TOKEN` | OAuth access token (expires ~2 hours) | Set via manual refresh |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

### Connected App in Salesforce

A Connected App named `AscendixSearchOAuth` exists in the Salesforce org:
- **App ID:** `0H4fk00000021knCAA`
- **Purpose:** OAuth authentication for AWS Lambda functions

---

## Option 1: Manual Token Refresh (Current Method)

Use this method for development or when automated refresh is not yet configured.

### Refresh Token and Update Lambda

```bash
# 1. Get fresh access token from SF CLI
ACCESS_TOKEN=$(sf org display --target-org ascendix-beta-sandbox --json | \
    python3 -c "import json,sys; print(json.load(sys.stdin)['result']['accessToken'])")

# 2. Update Lambda environment variables
aws lambda update-function-configuration \
    --function-name salesforce-ai-search-schema-discovery \
    --environment "Variables={
        SALESFORCE_INSTANCE_URL=https://ascendix-agentforce-demo--beta.sandbox.my.salesforce.com,
        SCHEMA_CACHE_TABLE=salesforce-ai-search-schema-cache,
        SALESFORCE_ACCESS_TOKEN=$ACCESS_TOKEN,
        LOG_LEVEL=INFO
    }" \
    --region us-west-2 \
    --no-cli-pager

# 3. Optionally update SSM parameter for other services
aws ssm put-parameter \
    --name "/salesforce/access_token" \
    --value "$ACCESS_TOKEN" \
    --type "SecureString" \
    --overwrite \
    --region us-west-2
```

### Verify Lambda Configuration

```bash
# Test schema discovery
aws lambda invoke \
    --function-name salesforce-ai-search-schema-discovery \
    --payload '{"operation": "discover_all"}' \
    --cli-binary-format raw-in-base64-out \
    --region us-west-2 \
    /tmp/result.json && cat /tmp/result.json | python3 -m json.tool
```

**Expected Output:**
```json
{
    "statusCode": 200,
    "body": "{\"success\": true, \"discovered_count\": 8, \"total_objects\": 8, ...}"
}
```

---

## Option 2: Automated Client Credentials Flow (Recommended)

This method uses OAuth 2.0 Client Credentials flow for automatic token management without manual intervention.

### Step 1: Configure Connected App in Salesforce

1. Navigate to: **Setup** → **Apps** → **App Manager**
2. Find `AscendixSearchOAuth` and click the dropdown → **Edit**
3. Under **OAuth Settings**, ensure these are configured:
   - **Enable OAuth Settings:** ✓
   - **Enable Client Credentials Flow:** ✓
   - **Callback URL:** `https://localhost/callback` (required but not used)
   - **Selected OAuth Scopes:**
     - `Access and manage your data (api)`
     - `Perform requests on your behalf at any time (refresh_token, offline_access)`
4. Under **Client Credentials Flow**:
   - **Run As:** Select a user with appropriate permissions (e.g., integration user)
5. **Save** the Connected App

### Step 2: Get Consumer Credentials

1. Navigate to: **Setup** → **Apps** → **App Manager**
2. Find `AscendixSearchOAuth` → Click dropdown → **Manage Consumer Details**
3. Verify your identity (may require email verification)
4. Copy:
   - **Consumer Key** (client_id)
   - **Consumer Secret** (client_secret)

### Step 3: Create AWS Secret

```bash
# Create secret with Connected App credentials
aws secretsmanager create-secret \
    --name "salesforce-ai-search/connected-app-credentials" \
    --description "Salesforce AscendixSearchOAuth connected app credentials for Schema Discovery" \
    --secret-string '{
        "client_id": "YOUR_CONSUMER_KEY_HERE",
        "client_secret": "YOUR_CONSUMER_SECRET_HERE"
    }' \
    --region us-west-2

# Get the secret ARN
SECRET_ARN=$(aws secretsmanager describe-secret \
    --secret-id "salesforce-ai-search/connected-app-credentials" \
    --region us-west-2 \
    --query 'ARN' \
    --output text)

echo "Secret ARN: $SECRET_ARN"
```

### Step 4: Grant Lambda Permission to Read Secret

```bash
# Get Lambda execution role
LAMBDA_ROLE=$(aws lambda get-function-configuration \
    --function-name salesforce-ai-search-schema-discovery \
    --region us-west-2 \
    --query 'Role' \
    --output text)

ROLE_NAME=$(echo $LAMBDA_ROLE | sed 's/.*\///')

# Add inline policy to allow reading the secret
aws iam put-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-name "SecretsManagerReadSalesforceCredentials" \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue"
                ],
                "Resource": "'"$SECRET_ARN"'"
            }
        ]
    }'
```

### Step 5: Update Lambda Configuration

```bash
# Update Lambda with secret ARN (removes static access token)
aws lambda update-function-configuration \
    --function-name salesforce-ai-search-schema-discovery \
    --environment "Variables={
        SALESFORCE_INSTANCE_URL=https://ascendix-agentforce-demo--beta.sandbox.my.salesforce.com,
        SCHEMA_CACHE_TABLE=salesforce-ai-search-schema-cache,
        SALESFORCE_CLIENT_SECRET_ARN=$SECRET_ARN,
        LOG_LEVEL=INFO
    }" \
    --region us-west-2 \
    --no-cli-pager
```

### Step 6: Verify Automated Authentication

```bash
# Test schema discovery with client credentials
aws lambda invoke \
    --function-name salesforce-ai-search-schema-discovery \
    --payload '{"operation": "discover_all"}' \
    --cli-binary-format raw-in-base64-out \
    --region us-west-2 \
    /tmp/result.json

# Check result
python3 -c "
import json
with open('/tmp/result.json') as f:
    result = json.load(f)
body = json.loads(result.get('body', '{}'))
if body.get('success'):
    print('SUCCESS: Schema discovery working with client credentials')
    print(f'Discovered: {body.get(\"discovered_count\")}/{body.get(\"total_objects\")} objects')
else:
    print(f'ERROR: {body.get(\"error\")}')
"
```

---

## Lambda Code: Authentication Flow

The Schema Discovery Lambda (`lambda/schema_discovery/discoverer.py`) handles authentication in this order:

1. **Check for `SALESFORCE_ACCESS_TOKEN`** environment variable (manual token)
2. **If not present, check for `SALESFORCE_CLIENT_SECRET_ARN`**:
   - Retrieve client credentials from Secrets Manager
   - Perform OAuth 2.0 Client Credentials flow
   - Cache the token for subsequent calls

```python
# Authentication priority in discoverer.py
self.access_token = os.environ.get('SALESFORCE_ACCESS_TOKEN', '')
if not self.access_token:
    secret_arn = os.environ.get('SALESFORCE_CLIENT_SECRET_ARN')
    if secret_arn:
        self._login_with_client_credentials(secret_arn)
```

---

## Troubleshooting

### Token Expired Error

**Symptom:** `HTTP 401: INVALID_SESSION_ID`

**Solution (Manual):**
```bash
# Refresh token using SF CLI
ACCESS_TOKEN=$(sf org display --target-org ascendix-beta-sandbox --json | \
    python3 -c "import json,sys; print(json.load(sys.stdin)['result']['accessToken'])")
aws lambda update-function-configuration \
    --function-name salesforce-ai-search-schema-discovery \
    --environment "Variables={...SALESFORCE_ACCESS_TOKEN=$ACCESS_TOKEN...}" \
    --region us-west-2
```

**Solution (Automated):** Configure Client Credentials flow (Option 2 above)

### Client Credentials Flow Not Working

**Symptom:** `invalid_grant` or authentication error

**Check:**
1. Connected App has "Enable Client Credentials Flow" checked
2. "Run As" user is configured and active
3. Consumer Key/Secret are correct in Secrets Manager
4. Lambda has permission to read the secret

### Schema Discovery Returns 0 Objects

**Symptom:** `discovered_count: 0`

**Check:**
1. Access token is valid: Run SF CLI query to verify
2. User has access to the objects being discovered
3. Lambda logs for detailed error messages

```bash
# Check recent Lambda logs
aws logs tail /aws/lambda/salesforce-ai-search-schema-discovery \
    --since 5m \
    --region us-west-2
```

---

## Security Considerations

1. **Never commit credentials** to version control
2. **Use Secrets Manager** for storing client_id/client_secret
3. **Rotate Consumer Secret** periodically via Salesforce Setup
4. **Limit Lambda IAM permissions** to only required secrets
5. **Use a dedicated integration user** as the "Run As" user for Client Credentials flow

---

## Related Documentation

- [Salesforce OAuth 2.0 Client Credentials Flow](https://help.salesforce.com/s/articleView?id=sf.remoteaccess_oauth_client_credentials_flow.htm)
- [AWS Secrets Manager Best Practices](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html)
- [Schema Discovery Lambda Implementation](../../lambda/schema_discovery/discoverer.py)

---

## Appendix: Quick Reference Commands

### Check Current Lambda Config
```bash
aws lambda get-function-configuration \
    --function-name salesforce-ai-search-schema-discovery \
    --region us-west-2 \
    --query 'Environment.Variables'
```

### List Schema Cache Contents
```bash
aws dynamodb scan \
    --table-name salesforce-ai-search-schema-cache \
    --region us-west-2 \
    --query 'Items[].objectApiName.S'
```

### Invoke Schema Discovery
```bash
# Discover single object
aws lambda invoke \
    --function-name salesforce-ai-search-schema-discovery \
    --payload '{"operation": "discover_object", "sobject": "ascendix__Property__c"}' \
    --cli-binary-format raw-in-base64-out \
    --region us-west-2 /tmp/result.json

# Discover all objects
aws lambda invoke \
    --function-name salesforce-ai-search-schema-discovery \
    --payload '{"operation": "discover_all"}' \
    --cli-binary-format raw-in-base64-out \
    --region us-west-2 /tmp/result.json
```

---

*Last Updated: 2025-12-10*
*Task Reference: Task 37 - Schema Cache Remediation*
