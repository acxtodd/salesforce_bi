"""
Tests for Schema Discovery Lambda.

Includes property-based tests using Hypothesis and unit tests.

**Feature: zero-config-schema-discovery**
**Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7**
"""
import sys
import os
import json
import pytest
from hypothesis import given, strategies as st, settings, assume

# Add the schema_discovery directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (
    FieldSchema, ObjectSchema, classify_field_type,
    FIELD_TYPE_FILTERABLE, FIELD_TYPE_NUMERIC, FIELD_TYPE_DATE,
    FIELD_TYPE_RELATIONSHIP, FIELD_TYPE_TEXT,
    PICKLIST_TYPES, NUMERIC_TYPES, DATE_TYPES, TEXT_TYPES
)


# =============================================================================
# Hypothesis Strategies for Salesforce Field Definitions
# =============================================================================

# Strategy for generating picklist field definitions
picklist_field_strategy = st.fixed_dictionaries({
    'name': st.text(alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_', min_size=1, max_size=40),
    'label': st.text(min_size=1, max_size=80),
    'type': st.sampled_from(list(PICKLIST_TYPES)),
    'picklistValues': st.lists(
        st.fixed_dictionaries({
            'value': st.text(min_size=1, max_size=50),
            'active': st.just(True),
            'label': st.text(min_size=1, max_size=80),
        }),
        min_size=1,
        max_size=20
    ),
})

# Strategy for generating numeric field definitions
numeric_field_strategy = st.fixed_dictionaries({
    'name': st.text(alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_', min_size=1, max_size=40),
    'label': st.text(min_size=1, max_size=80),
    'type': st.sampled_from(list(NUMERIC_TYPES)),
})

# Strategy for generating date field definitions
date_field_strategy = st.fixed_dictionaries({
    'name': st.text(alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_', min_size=1, max_size=40),
    'label': st.text(min_size=1, max_size=80),
    'type': st.sampled_from(list(DATE_TYPES)),
})

# Strategy for generating relationship field definitions
relationship_field_strategy = st.fixed_dictionaries({
    'name': st.text(alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_', min_size=1, max_size=40),
    'label': st.text(min_size=1, max_size=80),
    'type': st.just('reference'),
    'referenceTo': st.lists(
        st.text(alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_', min_size=1, max_size=40),
        min_size=1,
        max_size=3
    ),
})

# Strategy for generating text field definitions
text_field_strategy = st.fixed_dictionaries({
    'name': st.text(alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_', min_size=1, max_size=40),
    'label': st.text(min_size=1, max_size=80),
    'type': st.sampled_from(list(TEXT_TYPES)),
})


# =============================================================================
# Property Tests for Field Type Classification
# =============================================================================

class TestFieldTypeClassificationProperty:
    """
    Property-based tests for field type classification.
    
    **Property 1: Field Type Classification Correctness**
    **Validates: Requirements 1.2, 1.3, 1.4, 1.5**
    """

    @pytest.mark.property
    @given(sf_field=picklist_field_strategy)
    @settings(max_examples=100)
    def test_picklist_fields_classified_as_filterable(self, sf_field):
        """
        **Feature: zero-config-schema-discovery, Property 1: Field Type Classification Correctness**
        **Validates: Requirements 1.2**
        
        For any Salesforce field with type picklist or multipicklist,
        classify_field_type SHALL return 'filterable'.
        """
        result = classify_field_type(sf_field)
        assert result == FIELD_TYPE_FILTERABLE, \
            f"Expected 'filterable' for type '{sf_field['type']}', got '{result}'"

    @pytest.mark.property
    @given(sf_field=numeric_field_strategy)
    @settings(max_examples=100)
    def test_numeric_fields_classified_as_numeric(self, sf_field):
        """
        **Feature: zero-config-schema-discovery, Property 1: Field Type Classification Correctness**
        **Validates: Requirements 1.3**
        
        For any Salesforce field with type double, currency, int, or percent,
        classify_field_type SHALL return 'numeric'.
        """
        result = classify_field_type(sf_field)
        assert result == FIELD_TYPE_NUMERIC, \
            f"Expected 'numeric' for type '{sf_field['type']}', got '{result}'"

    @pytest.mark.property
    @given(sf_field=date_field_strategy)
    @settings(max_examples=100)
    def test_date_fields_classified_as_date(self, sf_field):
        """
        **Feature: zero-config-schema-discovery, Property 1: Field Type Classification Correctness**
        **Validates: Requirements 1.4**
        
        For any Salesforce field with type date or datetime,
        classify_field_type SHALL return 'date'.
        """
        result = classify_field_type(sf_field)
        assert result == FIELD_TYPE_DATE, \
            f"Expected 'date' for type '{sf_field['type']}', got '{result}'"

    @pytest.mark.property
    @given(sf_field=relationship_field_strategy)
    @settings(max_examples=100)
    def test_relationship_fields_classified_as_relationship(self, sf_field):
        """
        **Feature: zero-config-schema-discovery, Property 1: Field Type Classification Correctness**
        **Validates: Requirements 1.5**
        
        For any Salesforce field with type reference and non-empty referenceTo,
        classify_field_type SHALL return 'relationship'.
        """
        result = classify_field_type(sf_field)
        assert result == FIELD_TYPE_RELATIONSHIP, \
            f"Expected 'relationship' for reference field, got '{result}'"

    @pytest.mark.property
    @given(sf_field=text_field_strategy)
    @settings(max_examples=100)
    def test_text_fields_classified_as_text(self, sf_field):
        """
        **Feature: zero-config-schema-discovery, Property 1: Field Type Classification Correctness**
        **Validates: Requirements 1.2, 1.3, 1.4, 1.5**
        
        For any Salesforce field with type string, textarea, email, phone, or url,
        classify_field_type SHALL return 'text'.
        """
        result = classify_field_type(sf_field)
        assert result == FIELD_TYPE_TEXT, \
            f"Expected 'text' for type '{sf_field['type']}', got '{result}'"

    @pytest.mark.property
    @given(sf_field=st.one_of(
        picklist_field_strategy,
        numeric_field_strategy,
        date_field_strategy,
        relationship_field_strategy,
        text_field_strategy
    ))
    @settings(max_examples=100)
    def test_classification_returns_exactly_one_category(self, sf_field):
        """
        **Feature: zero-config-schema-discovery, Property 1: Field Type Classification Correctness**
        **Validates: Requirements 1.2, 1.3, 1.4, 1.5**
        
        For any Salesforce field, classify_field_type SHALL return exactly one
        of the valid classification types.
        """
        result = classify_field_type(sf_field)
        valid_types = {
            FIELD_TYPE_FILTERABLE,
            FIELD_TYPE_NUMERIC,
            FIELD_TYPE_DATE,
            FIELD_TYPE_RELATIONSHIP,
            FIELD_TYPE_TEXT
        }
        assert result in valid_types, \
            f"Classification '{result}' not in valid types: {valid_types}"


# =============================================================================
# Unit Tests for FieldSchema and ObjectSchema
# =============================================================================

class TestFieldSchema:
    """Unit tests for FieldSchema dataclass."""

    def test_field_schema_creation(self):
        """Test basic FieldSchema creation."""
        field = FieldSchema(
            name='ascendix__PropertyClass__c',
            label='Property Class',
            type='filterable',
            values=['A', 'B', 'C'],
            sf_type='picklist'
        )
        assert field.name == 'ascendix__PropertyClass__c'
        assert field.label == 'Property Class'
        assert field.type == 'filterable'
        assert field.values == ['A', 'B', 'C']

    def test_field_schema_to_dict(self):
        """Test FieldSchema serialization."""
        field = FieldSchema(
            name='Amount',
            label='Amount',
            type='numeric',
            sf_type='currency'
        )
        result = field.to_dict()
        assert result['name'] == 'Amount'
        assert result['type'] == 'numeric'
        assert 'values' not in result  # None values excluded

    def test_field_schema_from_dict(self):
        """Test FieldSchema deserialization."""
        data = {
            'name': 'Status',
            'label': 'Status',
            'type': 'filterable',
            'values': ['Open', 'Closed']
        }
        field = FieldSchema.from_dict(data)
        assert field.name == 'Status'
        assert field.values == ['Open', 'Closed']

    def test_field_schema_equality(self):
        """Test FieldSchema equality comparison."""
        field1 = FieldSchema(name='Test', label='Test', type='text')
        field2 = FieldSchema(name='Test', label='Test', type='text')
        field3 = FieldSchema(name='Other', label='Other', type='text')
        
        assert field1 == field2
        assert field1 != field3


class TestObjectSchema:
    """Unit tests for ObjectSchema dataclass."""

    def test_object_schema_creation(self):
        """Test basic ObjectSchema creation."""
        schema = ObjectSchema(
            api_name='ascendix__Property__c',
            label='Property',
            filterable=[
                FieldSchema(name='ascendix__PropertyClass__c', label='Class', type='filterable', values=['A', 'B'])
            ],
            numeric=[
                FieldSchema(name='ascendix__TotalArea__c', label='Total Area', type='numeric')
            ]
        )
        assert schema.api_name == 'ascendix__Property__c'
        assert len(schema.filterable) == 1
        assert len(schema.numeric) == 1

    def test_get_field(self):
        """Test ObjectSchema.get_field method."""
        schema = ObjectSchema(
            api_name='Test',
            label='Test',
            filterable=[FieldSchema(name='Status', label='Status', type='filterable')],
            numeric=[FieldSchema(name='Amount', label='Amount', type='numeric')]
        )
        
        status_field = schema.get_field('Status')
        assert status_field is not None
        assert status_field.name == 'Status'
        
        amount_field = schema.get_field('Amount')
        assert amount_field is not None
        assert amount_field.type == 'numeric'
        
        missing_field = schema.get_field('NonExistent')
        assert missing_field is None

    def test_get_picklist_values(self):
        """Test ObjectSchema.get_picklist_values method."""
        schema = ObjectSchema(
            api_name='Test',
            label='Test',
            filterable=[
                FieldSchema(name='Status', label='Status', type='filterable', values=['Open', 'Closed']),
                FieldSchema(name='Priority', label='Priority', type='filterable', values=['High', 'Low'])
            ]
        )
        
        status_values = schema.get_picklist_values('Status')
        assert status_values == ['Open', 'Closed']
        
        missing_values = schema.get_picklist_values('NonExistent')
        assert missing_values == []

    def test_object_schema_to_dict_and_from_dict(self):
        """Test ObjectSchema round-trip serialization."""
        original = ObjectSchema(
            api_name='ascendix__Property__c',
            label='Property',
            filterable=[
                FieldSchema(name='Class', label='Class', type='filterable', values=['A', 'B'])
            ],
            numeric=[
                FieldSchema(name='Area', label='Area', type='numeric')
            ],
            discovered_at='2025-11-29T10:00:00+00:00'
        )
        
        data = original.to_dict()
        restored = ObjectSchema.from_dict(data)
        
        assert restored.api_name == original.api_name
        assert restored.label == original.label
        assert len(restored.filterable) == len(original.filterable)
        assert restored.filterable[0].values == original.filterable[0].values

    def test_get_all_field_names(self):
        """Test ObjectSchema field name getters."""
        schema = ObjectSchema(
            api_name='Test',
            label='Test',
            filterable=[FieldSchema(name='Status', label='Status', type='filterable')],
            numeric=[FieldSchema(name='Amount', label='Amount', type='numeric')],
            date=[FieldSchema(name='CreatedDate', label='Created', type='date')],
            relationships=[FieldSchema(name='AccountId', label='Account', type='relationship', reference_to='Account')]
        )
        
        assert schema.get_all_filterable_field_names() == ['Status']
        assert schema.get_all_numeric_field_names() == ['Amount']
        assert schema.get_all_date_field_names() == ['CreatedDate']
        assert schema.get_all_relationship_field_names() == ['AccountId']


# =============================================================================
# Hypothesis Strategies for ObjectSchema Generation
# =============================================================================

# Strategy for generating FieldSchema instances
field_schema_strategy = st.builds(
    FieldSchema,
    name=st.text(alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_', min_size=1, max_size=40),
    label=st.text(min_size=1, max_size=80),
    type=st.sampled_from([FIELD_TYPE_FILTERABLE, FIELD_TYPE_NUMERIC, FIELD_TYPE_DATE, FIELD_TYPE_RELATIONSHIP, FIELD_TYPE_TEXT]),
    values=st.one_of(st.none(), st.lists(st.text(min_size=1, max_size=50), min_size=0, max_size=10)),
    reference_to=st.one_of(st.none(), st.text(alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_', min_size=1, max_size=40)),
    sf_type=st.one_of(st.none(), st.sampled_from(['picklist', 'double', 'date', 'reference', 'string']))
)

# Strategy for generating ObjectSchema instances
object_schema_strategy = st.builds(
    ObjectSchema,
    api_name=st.text(alphabet='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_', min_size=1, max_size=40),
    label=st.text(min_size=1, max_size=80),
    filterable=st.lists(field_schema_strategy, min_size=0, max_size=5),
    numeric=st.lists(field_schema_strategy, min_size=0, max_size=5),
    date=st.lists(field_schema_strategy, min_size=0, max_size=5),
    relationships=st.lists(field_schema_strategy, min_size=0, max_size=5),
    text=st.lists(field_schema_strategy, min_size=0, max_size=5),
    discovered_at=st.just('2025-11-29T10:00:00+00:00')
)


# =============================================================================
# Property Tests for Schema Cache Round-Trip
# =============================================================================

class TestSchemaCacheRoundTripProperty:
    """
    Property-based tests for schema cache round-trip.
    
    **Property 2: Schema Cache Round-Trip**
    **Validates: Requirements 1.6, 1.7**
    """

    @pytest.mark.property
    @given(schema=object_schema_strategy)
    @settings(max_examples=100)
    def test_object_schema_serialization_round_trip(self, schema):
        """
        **Feature: zero-config-schema-discovery, Property 2: Schema Cache Round-Trip**
        **Validates: Requirements 1.6, 1.7**
        
        For any ObjectSchema that is serialized to dict and deserialized back,
        the result SHALL be equivalent to the original schema.
        """
        # Serialize to dict (as would be stored in DynamoDB)
        serialized = schema.to_dict()
        
        # Deserialize back
        restored = ObjectSchema.from_dict(serialized)
        
        # Verify equivalence
        assert restored.api_name == schema.api_name, \
            f"api_name mismatch: {restored.api_name} != {schema.api_name}"
        assert restored.label == schema.label, \
            f"label mismatch: {restored.label} != {schema.label}"
        assert len(restored.filterable) == len(schema.filterable), \
            f"filterable count mismatch: {len(restored.filterable)} != {len(schema.filterable)}"
        assert len(restored.numeric) == len(schema.numeric), \
            f"numeric count mismatch: {len(restored.numeric)} != {len(schema.numeric)}"
        assert len(restored.date) == len(schema.date), \
            f"date count mismatch: {len(restored.date)} != {len(schema.date)}"
        assert len(restored.relationships) == len(schema.relationships), \
            f"relationships count mismatch: {len(restored.relationships)} != {len(schema.relationships)}"
        assert len(restored.text) == len(schema.text), \
            f"text count mismatch: {len(restored.text)} != {len(schema.text)}"

    @pytest.mark.property
    @given(field=field_schema_strategy)
    @settings(max_examples=100)
    def test_field_schema_serialization_round_trip(self, field):
        """
        **Feature: zero-config-schema-discovery, Property 2: Schema Cache Round-Trip**
        **Validates: Requirements 1.6, 1.7**
        
        For any FieldSchema that is serialized to dict and deserialized back,
        the result SHALL be equivalent to the original field.
        """
        # Serialize to dict
        serialized = field.to_dict()
        
        # Deserialize back
        restored = FieldSchema.from_dict(serialized)
        
        # Verify equivalence
        assert restored.name == field.name, \
            f"name mismatch: {restored.name} != {field.name}"
        assert restored.label == field.label, \
            f"label mismatch: {restored.label} != {field.label}"
        assert restored.type == field.type, \
            f"type mismatch: {restored.type} != {field.type}"
        assert restored.values == field.values, \
            f"values mismatch: {restored.values} != {field.values}"
        assert restored.reference_to == field.reference_to, \
            f"reference_to mismatch: {restored.reference_to} != {field.reference_to}"

    @pytest.mark.property
    @given(schema=object_schema_strategy)
    @settings(max_examples=100)
    def test_schema_double_serialization_idempotent(self, schema):
        """
        **Feature: zero-config-schema-discovery, Property 2: Schema Cache Round-Trip**
        **Validates: Requirements 1.6, 1.7**
        
        For any ObjectSchema, serializing twice SHALL produce identical results.
        """
        serialized1 = schema.to_dict()
        serialized2 = schema.to_dict()
        
        assert serialized1 == serialized2, \
            "Double serialization produced different results"


# =============================================================================
# Unit Tests for SchemaDiscoverer
# =============================================================================

class TestSchemaDiscoverer:
    """Unit tests for SchemaDiscoverer class."""

    def test_classify_and_create_field_picklist(self):
        """Test field classification for picklist fields."""
        from discoverer import SchemaDiscoverer
        
        discoverer = SchemaDiscoverer(access_token='test_token')
        
        sf_field = {
            'name': 'Status__c',
            'label': 'Status',
            'type': 'picklist',
            'picklistValues': [
                {'value': 'Open', 'active': True, 'label': 'Open'},
                {'value': 'Closed', 'active': True, 'label': 'Closed'},
                {'value': 'Inactive', 'active': False, 'label': 'Inactive'}
            ]
        }
        
        field = discoverer._classify_and_create_field(sf_field)
        
        assert field is not None
        assert field.name == 'Status__c'
        assert field.type == FIELD_TYPE_FILTERABLE
        assert field.values == ['Open', 'Closed']  # Only active values
        assert 'Inactive' not in field.values

    def test_classify_and_create_field_numeric(self):
        """Test field classification for numeric fields."""
        from discoverer import SchemaDiscoverer
        
        discoverer = SchemaDiscoverer(access_token='test_token')
        
        sf_field = {
            'name': 'Amount__c',
            'label': 'Amount',
            'type': 'currency'
        }
        
        field = discoverer._classify_and_create_field(sf_field)
        
        assert field is not None
        assert field.name == 'Amount__c'
        assert field.type == FIELD_TYPE_NUMERIC

    def test_classify_and_create_field_date(self):
        """Test field classification for date fields."""
        from discoverer import SchemaDiscoverer
        
        discoverer = SchemaDiscoverer(access_token='test_token')
        
        sf_field = {
            'name': 'CloseDate',
            'label': 'Close Date',
            'type': 'date'
        }
        
        field = discoverer._classify_and_create_field(sf_field)
        
        assert field is not None
        assert field.name == 'CloseDate'
        assert field.type == FIELD_TYPE_DATE

    def test_classify_and_create_field_relationship(self):
        """Test field classification for relationship fields."""
        from discoverer import SchemaDiscoverer
        
        discoverer = SchemaDiscoverer(access_token='test_token')
        
        sf_field = {
            'name': 'AccountId',
            'label': 'Account',
            'type': 'reference',
            'referenceTo': ['Account']
        }
        
        field = discoverer._classify_and_create_field(sf_field)
        
        assert field is not None
        assert field.name == 'AccountId'
        assert field.type == FIELD_TYPE_RELATIONSHIP
        assert field.reference_to == 'Account'

    def test_classify_and_create_field_skips_system_fields(self):
        """Test that system fields are skipped."""
        from discoverer import SchemaDiscoverer
        
        discoverer = SchemaDiscoverer(access_token='test_token')
        
        # Id field should be skipped
        sf_field = {
            'name': 'Id',
            'label': 'Record ID',
            'type': 'id'
        }
        
        field = discoverer._classify_and_create_field(sf_field)
        assert field is None

    def test_extract_picklist_values_only_active(self):
        """Test that only active picklist values are extracted."""
        from discoverer import SchemaDiscoverer
        
        discoverer = SchemaDiscoverer(access_token='test_token')
        
        sf_field = {
            'picklistValues': [
                {'value': 'A', 'active': True, 'label': 'Class A'},
                {'value': 'B', 'active': True, 'label': 'Class B'},
                {'value': 'C', 'active': False, 'label': 'Class C'},
                {'value': '', 'active': True, 'label': 'Empty'},  # Empty value
            ]
        }
        
        values = discoverer._extract_picklist_values(sf_field)
        
        assert values == ['A', 'B']
        assert 'C' not in values  # Inactive
        assert '' not in values  # Empty


# =============================================================================
# Unit Tests for Lambda Handler
# =============================================================================

class TestLambdaHandler:
    """Unit tests for Lambda handler."""

    def _get_index_module(self):
        """Load the schema_discovery index module explicitly."""
        import importlib.util
        import sys
        _current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Add the schema_discovery directory to sys.path so imports work
        if _current_dir not in sys.path:
            sys.path.insert(0, _current_dir)
        
        _spec = importlib.util.spec_from_file_location("schema_discovery_index", os.path.join(_current_dir, "index.py"))
        _idx = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_idx)
        return _idx

    def test_error_response_format(self):
        """Test error response format."""
        idx = self._get_index_module()
        
        response = idx._error_response(400, "Test error")
        
        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert body['success'] is False
        assert body['error'] == "Test error"

    def test_handler_unknown_operation(self):
        """Test handler with unknown operation."""
        idx = self._get_index_module()
        
        event = {'operation': 'unknown_operation'}
        response = idx.lambda_handler(event, None)
        
        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert 'Unknown operation' in body['error']

    def test_handler_get_schema_missing_sobject(self):
        """Test get_schema operation without sobject."""
        idx = self._get_index_module()
        
        event = {'operation': 'get_schema'}
        response = idx.lambda_handler(event, None)
        
        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert 'sobject is required' in body['error']

    def test_handler_discover_object_missing_sobject(self):
        """Test discover_object operation without sobject."""
        idx = self._get_index_module()
        
        event = {'operation': 'discover_object'}
        response = idx.lambda_handler(event, None)
        
        assert response['statusCode'] == 400
        body = json.loads(response['body'])
        assert 'sobject is required' in body['error']


# =============================================================================
# Integration-style Unit Tests (with mocking)
# =============================================================================

class TestSchemaDiscoveryIntegration:
    """Integration-style tests for schema discovery flow."""

    def test_full_schema_creation_flow(self):
        """Test creating a complete ObjectSchema from field definitions."""
        # Simulate Describe API response fields
        fields = [
            {'name': 'Name', 'label': 'Name', 'type': 'string'},
            {'name': 'Status__c', 'label': 'Status', 'type': 'picklist',
             'picklistValues': [{'value': 'Active', 'active': True, 'label': 'Active'}]},
            {'name': 'Amount__c', 'label': 'Amount', 'type': 'currency'},
            {'name': 'CloseDate__c', 'label': 'Close Date', 'type': 'date'},
            {'name': 'AccountId', 'label': 'Account', 'type': 'reference', 'referenceTo': ['Account']},
        ]
        
        from discoverer import SchemaDiscoverer
        discoverer = SchemaDiscoverer(access_token='test_token')
        
        # Classify each field
        filterable = []
        numeric = []
        date_fields = []
        relationships = []
        text = []
        
        for sf_field in fields:
            field = discoverer._classify_and_create_field(sf_field)
            if field is None:
                continue
            if field.type == FIELD_TYPE_FILTERABLE:
                filterable.append(field)
            elif field.type == FIELD_TYPE_NUMERIC:
                numeric.append(field)
            elif field.type == FIELD_TYPE_DATE:
                date_fields.append(field)
            elif field.type == FIELD_TYPE_RELATIONSHIP:
                relationships.append(field)
            elif field.type == FIELD_TYPE_TEXT:
                text.append(field)
        
        # Create schema
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test',
            filterable=filterable,
            numeric=numeric,
            date=date_fields,
            relationships=relationships,
            text=text
        )
        
        # Verify
        assert len(schema.filterable) == 1
        assert schema.filterable[0].name == 'Status__c'
        assert schema.filterable[0].values == ['Active']
        
        assert len(schema.numeric) == 1
        assert schema.numeric[0].name == 'Amount__c'
        
        assert len(schema.date) == 1
        assert schema.date[0].name == 'CloseDate__c'
        
        assert len(schema.relationships) == 1
        assert schema.relationships[0].name == 'AccountId'
        assert schema.relationships[0].reference_to == 'Account'
        
        assert len(schema.text) == 1
        assert schema.text[0].name == 'Name'

    def test_schema_cache_operations_with_mock_table(self):
        """Test cache operations work correctly with schema data."""
        # Create a schema
        schema = ObjectSchema(
            api_name='Test__c',
            label='Test Object',
            filterable=[
                FieldSchema(name='Status', label='Status', type='filterable', values=['A', 'B'])
            ],
            numeric=[
                FieldSchema(name='Amount', label='Amount', type='numeric')
            ]
        )
        
        # Test serialization (what would be stored in DynamoDB)
        serialized = schema.to_dict()
        
        # Verify structure
        assert serialized['api_name'] == 'Test__c'
        assert len(serialized['filterable']) == 1
        assert serialized['filterable'][0]['values'] == ['A', 'B']
        
        # Test deserialization (what would be retrieved from DynamoDB)
        restored = ObjectSchema.from_dict(serialized)
        
        assert restored.api_name == schema.api_name
        assert restored.get_picklist_values('Status') == ['A', 'B']
