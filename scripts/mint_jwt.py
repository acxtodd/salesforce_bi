#!/usr/bin/env python3
"""Mint a short-lived JWT assertion for Salesforce JWT Bearer flow.

Prints the signed JWT to stdout for use as a CDK context parameter:

    npx cdk deploy SalesforceAISearch-Ingestion-dev \
      -c salesforceJwtToken="$(python3 scripts/mint_jwt.py)"

Prerequisites:
  - pip install PyJWT cryptography
  - Private key: ~/trackit-jwt.pem (matches cert uploaded to External Client App)
  - Consumer key in Secrets Manager: salesforce-ai-search/appflow-creds
"""
import json
import os
import subprocess
import sys
import time

import jwt


def get_consumer_key() -> str:
    """Retrieve consumer key from Secrets Manager."""
    result = subprocess.run(
        [
            "aws", "secretsmanager", "get-secret-value",
            "--secret-id", "salesforce-ai-search/appflow-creds",
            "--region", os.environ.get("CDK_DEFAULT_REGION", "us-west-2"),
            "--query", "SecretString",
            "--output", "text",
        ],
        capture_output=True, text=True, check=True,
    )
    secret = json.loads(result.stdout.strip())
    return secret["client_id"]


def main() -> None:
    key_path = os.path.expanduser("~/trackit-jwt.pem")
    if not os.path.exists(key_path):
        print(f"Error: private key not found at {key_path}", file=sys.stderr)
        sys.exit(1)

    with open(key_path) as f:
        private_key = f.read()

    consumer_key = get_consumer_key()

    # JWT Bearer audience must be https://test.salesforce.com for sandbox orgs
    # (NOT the My Domain URL — that's only for the client_credentials token
    # endpoint). Validated 2026-03-17: My Domain as aud → "invalid assertion";
    # test.salesforce.com as aud → 200 + access_token.
    # For production orgs, change to https://login.salesforce.com.
    audience = os.environ.get(
        "SALESFORCE_JWT_AUDIENCE", "https://test.salesforce.com",
    )

    payload = {
        "iss": consumer_key,
        "sub": "tterry@ascendix.com.agentforce.demo.beta",
        "aud": audience,
        "exp": int(time.time()) + 300,
    }

    token = jwt.encode(payload, private_key, algorithm="RS256")
    print(token)


if __name__ == "__main__":
    main()
