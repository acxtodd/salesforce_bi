"""
Salesforce Schema Discoverer.

Discovers object schemas using the Salesforce Describe API and classifies
fields into filterable, numeric, date, relationship, and text categories.

**Feature: zero-config-schema-discovery**
**Requirements: 1.1, 1.2, 1.3, 1.4, 1.5**
"""
import json
import os
import urllib.request
import urllib.parse
from typing import Dict, List, Any, Optional
import boto3

from .models import (
    FieldSchema, ObjectSchema, classify_field_type,
    FIELD_TYPE_FILTERABLE, FIELD_TYPE_NUMERIC, FIELD_TYPE_DATE,
    FIELD_TYPE_RELATIONSHIP, FIELD_TYPE_TEXT
)

# Initialize AWS clients
ssm = boto3.client('ssm')

# Environment variables
SALESFORCE_API_ENDPOINT = os.environ.get('SALESFORCE_API_ENDPOINT', '')
SALESFORCE_API_VERSION = os.environ.get('SALESFORCE_API_VERSION', 'v59.0')

# CRE Objects to discover
CRE_OBJECTS = [
    "ascendix__Property__c",
    "ascendix__Deal__c",
    "ascendix__Availability__c",
    "ascendix__Listing__c",
    "ascendix__Inquiry__c",
    "ascendix__Lease__c",
    "Account",
    "Contact"
]


def get_salesforce_access_token() -> str:
    """
    Retrieve Salesforce access token from SSM Parameter Store or environment.
    
    Returns:
        Salesforce access token string
    """
    try:
        parameter_name = os.environ.get('SALESFORCE_TOKEN_PARAM', '/salesforce/access_token')
        response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
        return response['Parameter']['Value']
    except Exception as e:
        print(f"Error retrieving Salesforce token from SSM: {str(e)}")
        # Fallback to environment variable for local testing
        return os.environ.get('SALESFORCE_ACCESS_TOKEN', '')


def get_salesforce_instance_url() -> str:
    """
    Retrieve Salesforce instance URL from SSM Parameter Store or environment.
    
    **Feature: zero-config-production, Task 26.1**
    **Requirements: 1.1 - Configuration Service needs Salesforce API access**
    
    Returns:
        Salesforce instance URL string (e.g., 'https://myorg.my.salesforce.com')
    """
    # First check environment variable
    instance_url = os.environ.get('SALESFORCE_INSTANCE_URL', '') or os.environ.get('SALESFORCE_API_ENDPOINT', '')
    if instance_url:
        return instance_url
    
    # Fallback to SSM Parameter Store
    try:
        parameter_name = os.environ.get('SALESFORCE_INSTANCE_URL_PARAM', '/salesforce/instance_url')
        response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
        return response['Parameter']['Value']
    except Exception as e:
        print(f"Error retrieving Salesforce instance URL from SSM: {str(e)}")
        return ''


class SchemaDiscoverer:
    """
    Auto-discover Salesforce object schema using the Describe API.
    
    **Requirements: 1.1, 1.2, 1.3, 1.4, 1.5**
    """
    
    def __init__(
        self,
        access_token: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        api_version: Optional[str] = None
    ):
        """
        Initialize SchemaDiscoverer.
        
        Args:
            access_token: Salesforce access token (fetched from SSM if not provided)
            api_endpoint: Salesforce API endpoint URL (fetched from SSM if not provided)
            api_version: Salesforce API version (e.g., 'v59.0')
        """
        self.access_token = access_token or get_salesforce_access_token()
        self.api_endpoint = api_endpoint or get_salesforce_instance_url() or SALESFORCE_API_ENDPOINT
        self.api_version = api_version or SALESFORCE_API_VERSION
        
    def _make_api_request(self, url: str) -> Dict[str, Any]:
        """
        Make authenticated request to Salesforce API.
        
        Args:
            url: Full URL to request
            
        Returns:
            JSON response as dictionary
            
        Raises:
            Exception: If request fails
        """
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        
        req = urllib.request.Request(url, headers=headers)
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status != 200:
                    raise Exception(f"Salesforce returned status {response.status}")
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            raise Exception(f"HTTP {e.code}: {error_body}")
        except Exception as e:
            print(f"Error making API request to {url}: {str(e)}")
            raise
    
    def discover_object(self, sobject: str) -> ObjectSchema:
        """
        Discover complete schema for a Salesforce object using Describe API.
        
        **Requirements: 1.1, 1.2, 1.3, 1.4, 1.5**
        
        Args:
            sobject: Object API name (e.g., 'ascendix__Property__c')
            
        Returns:
            ObjectSchema with classified fields
        """
        # Call Salesforce Describe API
        url = f"{self.api_endpoint}/services/data/{self.api_version}/sobjects/{sobject}/describe"
        
        print(f"Discovering schema for {sobject}...")
        describe_result = self._make_api_request(url)
        
        # Extract object metadata
        api_name = describe_result.get('name', sobject)
        label = describe_result.get('label', sobject)
        
        # Classify fields
        filterable_fields: List[FieldSchema] = []
        numeric_fields: List[FieldSchema] = []
        date_fields: List[FieldSchema] = []
        relationship_fields: List[FieldSchema] = []
        text_fields: List[FieldSchema] = []
        
        for sf_field in describe_result.get('fields', []):
            field_schema = self._classify_and_create_field(sf_field)
            if field_schema is None:
                continue
                
            # Add to appropriate category
            if field_schema.type == FIELD_TYPE_FILTERABLE:
                filterable_fields.append(field_schema)
            elif field_schema.type == FIELD_TYPE_NUMERIC:
                numeric_fields.append(field_schema)
            elif field_schema.type == FIELD_TYPE_DATE:
                date_fields.append(field_schema)
            elif field_schema.type == FIELD_TYPE_RELATIONSHIP:
                relationship_fields.append(field_schema)
            elif field_schema.type == FIELD_TYPE_TEXT:
                text_fields.append(field_schema)
        
        schema = ObjectSchema(
            api_name=api_name,
            label=label,
            filterable=filterable_fields,
            numeric=numeric_fields,
            date=date_fields,
            relationships=relationship_fields,
            text=text_fields
        )
        
        print(f"Discovered {sobject}: {len(filterable_fields)} filterable, "
              f"{len(numeric_fields)} numeric, {len(date_fields)} date, "
              f"{len(relationship_fields)} relationship, {len(text_fields)} text fields")
        
        return schema
    
    def _classify_and_create_field(self, sf_field: Dict[str, Any]) -> Optional[FieldSchema]:
        """
        Classify a Salesforce field and create FieldSchema.
        
        **Requirements: 1.2, 1.3, 1.4, 1.5**
        
        Args:
            sf_field: Salesforce field definition from Describe API
            
        Returns:
            FieldSchema or None if field should be skipped
        """
        name = sf_field.get('name', '')
        label = sf_field.get('label', name)
        sf_type = sf_field.get('type', '')
        
        # Skip system fields that aren't useful for filtering
        if name in ('Id', 'IsDeleted', 'SystemModstamp'):
            return None
        
        # Classify the field type
        field_type = classify_field_type(sf_field)
        
        # Extract additional metadata based on type
        values = None
        reference_to = None
        
        if field_type == FIELD_TYPE_FILTERABLE:
            # Extract active picklist values
            values = self._extract_picklist_values(sf_field)
            
        elif field_type == FIELD_TYPE_RELATIONSHIP:
            # Extract reference target
            reference_to_list = sf_field.get('referenceTo', [])
            if reference_to_list:
                reference_to = reference_to_list[0]  # Use first reference target
        
        return FieldSchema(
            name=name,
            label=label,
            type=field_type,
            values=values,
            reference_to=reference_to,
            sf_type=sf_type
        )
    
    def _extract_picklist_values(self, sf_field: Dict[str, Any]) -> List[str]:
        """
        Extract active picklist values from a field definition.
        
        **Requirements: 1.2**
        
        Args:
            sf_field: Salesforce field definition
            
        Returns:
            List of active picklist value strings
        """
        values = []
        picklist_values = sf_field.get('picklistValues', [])
        
        for pv in picklist_values:
            # Only include active values
            if pv.get('active', False):
                value = pv.get('value', '')
                if value:
                    values.append(value)
        
        return values
    
    def discover_all(self, objects: Optional[List[str]] = None) -> Dict[str, ObjectSchema]:
        """
        Discover and return schema for all CRE objects.
        
        **Requirements: 1.1**
        
        Args:
            objects: List of object API names to discover (defaults to CRE_OBJECTS)
            
        Returns:
            Dictionary mapping object API name to ObjectSchema
        """
        objects_to_discover = objects or CRE_OBJECTS
        schemas: Dict[str, ObjectSchema] = {}
        errors: List[str] = []
        
        for sobject in objects_to_discover:
            try:
                schema = self.discover_object(sobject)
                schemas[sobject] = schema
            except Exception as e:
                error_msg = f"Failed to discover {sobject}: {str(e)}"
                print(error_msg)
                errors.append(error_msg)
                # Continue with other objects
        
        print(f"Discovered {len(schemas)}/{len(objects_to_discover)} objects. "
              f"Errors: {len(errors)}")
        
        return schemas
