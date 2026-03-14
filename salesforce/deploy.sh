#!/bin/bash

# Salesforce AI Search POC - Deployment Script
# This script automates the deployment of Salesforce components

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if SFDX is installed
if ! command -v sfdx &> /dev/null; then
    print_error "Salesforce CLI (sfdx) is not installed. Please install it first."
    exit 1
fi

print_info "Salesforce AI Search POC - Deployment Script"
echo ""

# Get target org alias
read -p "Enter Salesforce org alias (e.g., my-sandbox): " ORG_ALIAS

if [ -z "$ORG_ALIAS" ]; then
    print_error "Org alias cannot be empty"
    exit 1
fi

# Check if org is authenticated
print_info "Checking authentication for org: $ORG_ALIAS"
if ! sfdx force:org:display -u "$ORG_ALIAS" &> /dev/null; then
    print_warning "Not authenticated to $ORG_ALIAS. Opening login page..."
    sfdx auth:web:login -a "$ORG_ALIAS"
fi

print_info "Successfully authenticated to $ORG_ALIAS"
echo ""

# Validate Named Credential configuration
print_info "Validating Named Credential configuration..."
if grep -q "REPLACE_WITH_PRIVATELINK_ENDPOINT_URL" namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml; then
    print_error "Named Credential not configured!"
    print_error "Please update namedCredentials/Ascendix_RAG_API.namedCredential-meta.xml with:"
    print_error "  1. Replace REPLACE_WITH_PRIVATELINK_ENDPOINT_URL with your API Gateway endpoint"
    print_error "  2. Replace REPLACE_WITH_API_KEY with your API key"
    exit 1
fi

print_info "Named Credential configuration looks good"
echo ""

# Ask for deployment type
echo "Select deployment type:"
echo "1) Validate only (check for errors without deploying)"
echo "2) Deploy all components"
echo "3) Deploy Named Credential only"
echo "4) Deploy LWC only"
read -p "Enter choice (1-4): " DEPLOY_TYPE

case $DEPLOY_TYPE in
    1)
        print_info "Validating deployment..."
        sfdx force:source:deploy -x package.xml -u "$ORG_ALIAS" --checkonly
        print_info "Validation complete! No errors found."
        ;;
    2)
        print_info "Deploying all components..."
        sfdx force:source:deploy -x package.xml -u "$ORG_ALIAS"
        print_info "Deployment complete!"
        echo ""
        print_info "Next steps:"
        print_info "  1. Add LWC to Account and Home page layouts"
        print_info "  2. Test Named Credential connectivity"
        print_info "  3. Assign permissions to pilot users"
        print_info "  4. Run smoke tests"
        ;;
    3)
        print_info "Deploying Named Credential..."
        sfdx force:source:deploy -m NamedCredential:Ascendix_RAG_API -u "$ORG_ALIAS"
        print_info "Named Credential deployed!"
        echo ""
        print_info "Test connectivity:"
        print_info "  1. Navigate to Setup > Named Credentials"
        print_info "  2. Open 'Ascendix RAG API'"
        print_info "  3. Click 'Test Connection'"
        ;;
    4)
        print_info "Deploying LWC..."
        sfdx force:source:deploy -m LightningComponentBundle:ascendixAiSearch -u "$ORG_ALIAS"
        print_info "LWC deployed!"
        echo ""
        print_info "Next steps:"
        print_info "  1. Add LWC to Account and Home page layouts"
        print_info "  2. Test the component on a record page"
        ;;
    *)
        print_error "Invalid choice"
        exit 1
        ;;
esac

echo ""
print_info "Deployment script completed successfully!"
print_info "See DEPLOYMENT_GUIDE.md for detailed instructions"
