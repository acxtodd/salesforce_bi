"""
Salesforce Schema Discoverer.

Discovers object schemas using the Salesforce Describe API and classifies
fields into filterable, numeric, date, relationship, and text categories.

Includes Signal Harvesting integration for relevance scoring.

**Feature: zero-config-schema-discovery, graph-aware-zero-config-retrieval**
**Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 24.1-24.6**
"""
import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, List, Any, Optional
import boto3

from .models import (
    FieldSchema, ObjectSchema, classify_field_type,
    FIELD_TYPE_FILTERABLE, FIELD_TYPE_NUMERIC, FIELD_TYPE_DATE,
    FIELD_TYPE_RELATIONSHIP, FIELD_TYPE_TEXT
)
from .signal_harvester import SignalHarvester, HarvestResult, VocabSeed

# Initialize AWS clients
ssm = boto3.client('ssm')
secrets_manager = boto3.client('secretsmanager')

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


def get_salesforce_credentials() -> Dict[str, str]:
    """
    Retrieve Salesforce connected app credentials from Secrets Manager.
    
    Returns:
        Dictionary with client_id and client_secret
    """
    secret_arn = os.environ.get('SALESFORCE_CLIENT_SECRET_ARN')
    if not secret_arn:
        print("Warning: SALESFORCE_CLIENT_SECRET_ARN not set")
        return {}
        
    try:
        response = secrets_manager.get_secret_value(SecretId=secret_arn)
        if 'SecretString' in response:
            return json.loads(response['SecretString'])
        return {}
    except Exception as e:
        print(f"Error retrieving Salesforce credentials from Secrets Manager: {str(e)}")
        return {}


class SchemaDiscoverer:
    """
    Auto-discover Salesforce object schema using the Describe API.

    Includes Signal Harvesting for relevance scoring from Ascendix Search configs.

    **Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 24.1-24.6**
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        api_version: Optional[str] = None,
        enable_signal_harvesting: bool = True
    ):
        """
        Initialize SchemaDiscoverer.

        Args:
            access_token: Salesforce access token (fetched via OAuth if not provided)
            api_endpoint: Salesforce API endpoint URL
            api_version: Salesforce API version (e.g., 'v59.0')
            enable_signal_harvesting: Whether to harvest signals from Ascendix Search (default: True)
        """
        self.access_token = access_token
        self.api_endpoint = api_endpoint or get_salesforce_instance_url() or SALESFORCE_API_ENDPOINT
        self.api_version = api_version or SALESFORCE_API_VERSION
        self.enable_signal_harvesting = enable_signal_harvesting

        # If token is provided, assume it's valid for at least an hour
        if self.access_token:
            self.token_expiry = time.time() + 3600
        else:
            self.token_expiry = 0
        
    def login(self) -> bool:
        """
        Authenticate with Salesforce using Client Credentials flow.
        
        Returns:
            True if successful, False otherwise
        """
        if self.access_token and time.time() < self.token_expiry:
            return True
            
        credentials = get_salesforce_credentials()
        if not credentials:
            print("Cannot login: No credentials available")
            return False
            
        # Try common key names for client id/secret
        client_id = credentials.get('client_id') or credentials.get('consumer_key')
        client_secret = credentials.get('client_secret') or credentials.get('consumer_secret')
        
        if not client_id or not client_secret:
            print("Cannot login: Missing client_id or client_secret in secret")
            return False
            
        token_url = f"{self.api_endpoint}/services/oauth2/token"
        data = urllib.parse.urlencode({
            'grant_type': 'client_credentials',
            'client_id': client_id,
            'client_secret': client_secret
        }).encode('utf-8')
        
        try:
            req = urllib.request.Request(token_url, data=data, method='POST')
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                self.access_token = result['access_token']
                # Set expiry slightly before actual expiry (default 2 hours usually)
                self.token_expiry = time.time() + 3600 
                print("Successfully authenticated with Salesforce")
                return True
        except Exception as e:
            print(f"Failed to authenticate with Salesforce: {str(e)}")
            return False

    def _make_api_request(self, url: str, retry: bool = True) -> Dict[str, Any]:
        """
        Make authenticated request to Salesforce API.
        
        Args:
            url: Full URL to request
            retry: Whether to retry on 401
            
        Returns:
            JSON response as dictionary
            
        Raises:
            Exception: If request fails
        """
        # Ensure we have a token
        if not self.access_token:
            # Try to get token from env var one last time before login
            self.access_token = os.environ.get('SALESFORCE_ACCESS_TOKEN', '')
            if self.access_token:
                self.token_expiry = time.time() + 3600
            
            if not self.access_token and not self.login():
                raise Exception("Authentication failed")
        
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
            if e.code == 401 and retry:
                print("Token expired, retrying login...")
                self.access_token = None
                if self.login():
                    return self._make_api_request(url, retry=False)
            
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

        # Extract RecordType as synthetic filterable field from recordTypeInfos
        record_type_field = self._extract_record_types(describe_result)
        if record_type_field:
            filterable_fields.append(record_type_field)

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

        # Apply signal harvesting to boost field relevance (Req 24.1-24.6)
        if self.enable_signal_harvesting:
            harvest_result = self._harvest_signals(sobject)
            if harvest_result:
                # Apply relevance scores to fields
                if harvest_result.field_scores:
                    schema.apply_relevance_scores(harvest_result.field_scores)
                    print(f"Applied relevance scores to {len(harvest_result.field_scores)} fields")

                # Store primary relationships in schema (Req 24.4)
                if harvest_result.primary_relationships:
                    schema.primary_relationships = harvest_result.primary_relationships
                    print(f"Stored {len(harvest_result.primary_relationships)} primary relationships")

                # Persist vocab seeds to vocab cache (Req 24.5)
                if harvest_result.vocab_seeds:
                    self._persist_vocab_seeds(sobject, harvest_result.vocab_seeds)

        # Apply default relevance scores to fields without signal-based scores (Task 41.4)
        schema.apply_default_relevance_scores()
        print(f"Applied default relevance scores to remaining fields")

        return schema

    def _harvest_signals(self, sobject: str) -> Optional[HarvestResult]:
        """
        Harvest relevance signals from Ascendix Search configurations.

        **Requirements: 24.1-24.6**

        Args:
            sobject: Object API name

        Returns:
            HarvestResult or None if harvesting fails/not available
        """
        # Ensure we have a valid token
        if not self.access_token:
            self.access_token = os.environ.get('SALESFORCE_ACCESS_TOKEN', '')
            if not self.access_token and not self.login():
                print("Cannot harvest signals: No authentication")
                return None

        try:
            harvester = SignalHarvester(
                access_token=self.access_token,
                instance_url=self.api_endpoint,
                api_version=self.api_version
            )
            return harvester.harvest(sobject)
        except Exception as e:
            # Graceful degradation - log warning and continue without signals
            print(f"Warning: Signal harvesting failed for {sobject}: {e}")
            return None

    def _persist_vocab_seeds(self, sobject: str, vocab_seeds: List[VocabSeed]) -> None:
        """
        Persist vocabulary seeds from signal harvesting to vocab cache.

        **Requirements: 24.5**

        Seeds the vocab cache with filter values discovered from saved searches,
        enabling entity resolution (e.g., 'Plano' -> ascendix__City__c).

        Args:
            sobject: Object API name
            vocab_seeds: List of VocabSeed objects from harvesting
        """
        if not vocab_seeds:
            return

        try:
            # Import vocab cache (lazy to avoid circular imports)
            import sys
            vocab_cache_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'retrieve'
            )
            if vocab_cache_path not in sys.path:
                sys.path.insert(0, vocab_cache_path)

            from vocab_cache import VocabCache, VocabTerm

            cache = VocabCache()

            # Convert VocabSeeds to VocabTerms and group by field
            terms_by_field: Dict[str, List[VocabTerm]] = {}
            for seed in vocab_seeds:
                term = VocabTerm(
                    term=seed.term.lower(),
                    canonical_value=seed.term,
                    object_name=sobject,
                    field_name=seed.field,
                    source='saved_search',
                    relevance_score=0.9,  # High relevance - user-configured filter value
                    vocab_type='filter_value'
                )
                if seed.field not in terms_by_field:
                    terms_by_field[seed.field] = []
                terms_by_field[seed.field].append(term)

            # Store terms grouped by field
            total_stored = 0
            for field_name, terms in terms_by_field.items():
                # Use field-specific vocab type for precise lookup
                vocab_type = f"filter_value#{field_name}"
                if cache.put_terms(vocab_type, sobject, terms):
                    total_stored += len(terms)

            print(f"Persisted {total_stored} vocab seeds for {sobject}")

        except ImportError as e:
            # Vocab cache not available - skip seeding
            print(f"Warning: Could not import vocab_cache for seeding: {e}")
        except Exception as e:
            # Don't fail discovery if vocab seeding fails
            print(f"Warning: Failed to persist vocab seeds for {sobject}: {e}")

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

    def _extract_record_types(self, describe_result: Dict[str, Any]) -> Optional[FieldSchema]:
        """
        Extract RecordType as a synthetic filterable field from recordTypeInfos.

        **Requirements: 1.2 - RecordType is critical for property type queries**

        RecordType is a standard Salesforce feature but not a regular picklist field.
        It's exposed via recordTypeInfos in the Describe API response.

        Args:
            describe_result: Full Describe API response

        Returns:
            FieldSchema for RecordType or None if no record types defined
        """
        record_type_infos = describe_result.get('recordTypeInfos', [])
        if not record_type_infos:
            return None

        # Extract active record type names (excluding Master)
        values = []
        for rt in record_type_infos:
            if rt.get('active', False) and rt.get('available', True):
                name = rt.get('name', '')
                if name and name != 'Master':  # Exclude Master record type
                    values.append(name)

        if not values:
            return None

        return FieldSchema(
            name='RecordType',
            label='Record Type',
            type=FIELD_TYPE_FILTERABLE,
            values=values,
            sf_type='recordType'  # Synthetic type for traceability
        )

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
