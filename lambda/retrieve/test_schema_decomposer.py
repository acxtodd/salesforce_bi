"""
Tests for Schema-Aware Query Decomposer.

Includes property-based tests using Hypothesis and unit tests.

**Feature: zero-config-schema-discovery**
**Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
"""
import os
import sys
import pytest
from unittest.mock import Mock, MagicMock, patch
from hypothesis import given, strategies as st, settings, assume

# Add parent directories to path for imports
# **Feature: zero-config-production, Task 27.1**
# Updated to use schema_discovery from parent directory (Lambda Layer path)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'schema_discovery'))

from schema_decomposer import (
    SchemaAwareDecomposer,
    StructuredQuery,
    normalize_value,
    ENTITY_PATTERNS,
    DEFAULT_ENTITY,
    FUZZY_MATCH_THRESHOLD,
)
from models import ObjectSchema, FieldSchema


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def sample_property_schema():
    """Create a sample Property schema for testing."""
    return ObjectSchema(
        api_name='ascendix__Property__c',
        label='Property',
        filterable=[
            FieldSchema(
                name='ascendix__PropertyClass__c',
                label='Property Class',
                type='filterable',
                values=['A', 'B', 'C'],
            ),
            FieldSchema(
                name='ascendix__PropertySubType__c',
                label='Property Sub Type',
                type='filterable',
                values=['Office', 'Retail', 'Industrial', 'Multifamily'],
            ),
            FieldSchema(
                name='ascendix__City__c',
                label='City',
                type='filterable',
                values=['Dallas', 'Houston', 'Austin', 'San Antonio'],
            ),
            FieldSchema(
                name='ascendix__State__c',
                label='State',
                type='filterable',
                values=['TX', 'CA', 'NY', 'FL'],
            ),
        ],
        numeric=[
            FieldSchema(
                name='ascendix__TotalBuildingArea__c',
                label='Total Building Area',
                type='numeric',
            ),
            FieldSchema(
                name='ascendix__YearBuilt__c',
                label='Year Built',
                type='numeric',
            ),
        ],
        date=[
            FieldSchema(
                name='LastActivityDate',
                label='Last Activity Date',
                type='date',
            ),
        ],
        relationships=[
            FieldSchema(
                name='OwnerId',
                label='Owner',
                type='relationship',
                reference_to='User',
            ),
        ],
    )


@pytest.fixture
def sample_deal_schema():
    """Create a sample Deal schema for testing."""
    return ObjectSchema(
        api_name='ascendix__Deal__c',
        label='Deal',
        filterable=[
            FieldSchema(
                name='ascendix__Status__c',
                label='Status',
                type='filterable',
                values=['Active', 'Closed Won', 'Closed Lost', 'On Hold'],
            ),
            FieldSchema(
                name='ascendix__DealType__c',
                label='Deal Type',
                type='filterable',
                values=['Lease', 'Sale', 'Investment'],
            ),
        ],
        numeric=[
            FieldSchema(
                name='ascendix__GrossFeeAmount__c',
                label='Gross Fee Amount',
                type='numeric',
            ),
        ],
        relationships=[
            FieldSchema(
                name='ascendix__Property__c',
                label='Property',
                type='relationship',
                reference_to='ascendix__Property__c',
            ),
        ],
    )


@pytest.fixture
def mock_schema_cache(sample_property_schema, sample_deal_schema):
    """Create a mock schema cache."""
    cache = Mock()
    
    def get_schema(sobject):
        schemas = {
            'ascendix__Property__c': sample_property_schema,
            'ascendix__Deal__c': sample_deal_schema,
        }
        return schemas.get(sobject)
    
    cache.get = Mock(side_effect=get_schema)
    return cache


# =============================================================================
# Property-Based Tests
# =============================================================================

# Strategy for generating valid picklist values
# Use ASCII letters and digits only (typical Salesforce picklist values)
valid_values_strategy = st.lists(
    st.text(
        alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -_',
        min_size=1,
        max_size=20
    ).filter(lambda x: x.strip() and len(x.strip()) > 0),
    min_size=1,
    max_size=10,
    unique=True
)


@given(
    valid_values=valid_values_strategy,
    case_variation=st.sampled_from(['lower', 'upper', 'title', 'original']),
    whitespace_prefix=st.text(alphabet=' \t', max_size=3),
    whitespace_suffix=st.text(alphabet=' \t', max_size=3),
)
@settings(max_examples=100)
def test_property_value_normalization(
    valid_values,
    case_variation,
    whitespace_prefix,
    whitespace_suffix
):
    """
    **Property 4: Value Normalization**
    **Validates: Requirements 3.5, 3.6**
    
    *For any* filter value extracted from a query that differs only in case
    or whitespace from a valid picklist value, the Schema-Aware Decomposer
    SHALL normalize it to the canonical picklist value.
    """
    # Skip if no valid values
    assume(len(valid_values) > 0)
    assume(all(v.strip() for v in valid_values))
    
    # Pick a random valid value
    canonical_value = valid_values[0]
    assume(canonical_value.strip())  # Ensure non-empty after strip
    
    # Apply case variation
    if case_variation == 'lower':
        test_value = canonical_value.lower()
    elif case_variation == 'upper':
        test_value = canonical_value.upper()
    elif case_variation == 'title':
        test_value = canonical_value.title()
    else:
        test_value = canonical_value
    
    # Add whitespace variations
    test_value = whitespace_prefix + test_value + whitespace_suffix
    
    # Normalize the value
    result = normalize_value(test_value, valid_values)
    
    # The result should be the canonical value
    assert result == canonical_value, (
        f"Expected '{canonical_value}' but got '{result}' "
        f"for input '{test_value}' with valid values {valid_values}"
    )


@given(
    valid_values=st.lists(
        st.sampled_from(['A', 'B', 'C', 'Office', 'Retail', 'Industrial']),
        min_size=1,
        max_size=6,
        unique=True
    )
)
@settings(max_examples=100)
def test_property_exact_match_preserved(valid_values):
    """
    **Property 4: Value Normalization (exact match case)**
    **Validates: Requirements 3.5, 3.6**
    
    *For any* value that exactly matches a valid picklist value,
    normalization SHALL return that exact value unchanged.
    """
    assume(len(valid_values) > 0)
    
    # Pick a valid value
    canonical_value = valid_values[0]
    
    # Exact match should return the same value
    result = normalize_value(canonical_value, valid_values)
    
    assert result == canonical_value, (
        f"Exact match should preserve value: expected '{canonical_value}' but got '{result}'"
    )


# =============================================================================
# Unit Tests
# =============================================================================

class TestStructuredQuery:
    """Tests for StructuredQuery dataclass."""
    
    def test_to_dict(self):
        """Test StructuredQuery serialization."""
        query = StructuredQuery(
            target_entity='ascendix__Property__c',
            filters={'ascendix__City__c': 'Dallas'},
            numeric_filters={'ascendix__TotalBuildingArea__c': {'$gt': 100000}},
            confidence=0.9,
            original_query='properties in Dallas over 100k sqft',
        )
        
        result = query.to_dict()
        
        assert result['target_entity'] == 'ascendix__Property__c'
        assert result['filters'] == {'ascendix__City__c': 'Dallas'}
        assert result['numeric_filters'] == {'ascendix__TotalBuildingArea__c': {'$gt': 100000}}
        assert result['confidence'] == 0.9
    
    def test_from_dict(self):
        """Test StructuredQuery deserialization."""
        data = {
            'target_entity': 'ascendix__Deal__c',
            'filters': {'ascendix__Status__c': 'Active'},
            'confidence': 0.85,
            'original_query': 'active deals',
        }
        
        query = StructuredQuery.from_dict(data)
        
        assert query.target_entity == 'ascendix__Deal__c'
        assert query.filters == {'ascendix__Status__c': 'Active'}
        assert query.confidence == 0.85


class TestEntityDetection:
    """Tests for entity detection from queries."""
    
    def test_detect_property_entity(self, mock_schema_cache):
        """Test detection of Property entity."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        queries = [
            'Class A properties in Dallas',
            'office buildings downtown',
            'show me the tower on Main Street',
        ]
        
        for query in queries:
            entity = decomposer.detect_target_entity(query)
            assert entity == 'ascendix__Property__c', f"Failed for query: {query}"
    
    def test_detect_deal_entity(self, mock_schema_cache):
        """Test detection of Deal entity."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        queries = [
            'active deals this quarter',
            'transactions in progress',
            'show me the pipeline',
        ]
        
        for query in queries:
            entity = decomposer.detect_target_entity(query)
            assert entity == 'ascendix__Deal__c', f"Failed for query: {query}"
    
    def test_detect_availability_entity(self, mock_schema_cache):
        """Test detection of Availability entity."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        queries = [
            'available space for lease',
            'vacant suites downtown',
            'space for rent',
        ]
        
        for query in queries:
            entity = decomposer.detect_target_entity(query)
            assert entity == 'ascendix__Availability__c', f"Failed for query: {query}"
    
    def test_detect_lease_entity(self, mock_schema_cache):
        """Test detection of Lease entity."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        queries = [
            'expiring leases this year',
            'tenant agreements',
            'rental contracts',
        ]
        
        for query in queries:
            entity = decomposer.detect_target_entity(query)
            assert entity == 'ascendix__Lease__c', f"Failed for query: {query}"
    
    def test_default_entity_when_none_detected(self, mock_schema_cache):
        """Test default entity when no patterns match."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        entity = decomposer.detect_target_entity('something random')
        assert entity == DEFAULT_ENTITY


class TestSchemaContextBuilder:
    """Tests for schema context building."""
    
    def test_build_schema_context_includes_filterable_fields(
        self, mock_schema_cache, sample_property_schema
    ):
        """Test that schema context includes filterable fields with values."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        context = decomposer._build_schema_context(sample_property_schema)
        
        assert 'ascendix__PropertyClass__c' in context
        assert '"A"' in context
        assert '"B"' in context
        assert '"C"' in context
    
    def test_build_schema_context_includes_numeric_fields(
        self, mock_schema_cache, sample_property_schema
    ):
        """Test that schema context includes numeric fields."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        context = decomposer._build_schema_context(sample_property_schema)
        
        assert 'ascendix__TotalBuildingArea__c' in context
        assert 'Numeric Fields' in context
    
    def test_build_schema_context_includes_relationships(
        self, mock_schema_cache, sample_property_schema
    ):
        """Test that schema context includes relationship fields."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        context = decomposer._build_schema_context(sample_property_schema)
        
        assert 'OwnerId' in context
        assert 'Relationships' in context


class TestValueValidation:
    """Tests for value validation and normalization."""
    
    def test_validate_exact_match(self, mock_schema_cache, sample_property_schema):
        """Test validation with exact match."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        decomposition = {
            'target_filters': {
                'ascendix__PropertyClass__c': 'A',
            }
        }
        
        validated, warnings = decomposer._validate_values(
            decomposition, sample_property_schema
        )
        
        assert validated['target_filters']['ascendix__PropertyClass__c'] == 'A'
        assert len(warnings) == 0
    
    def test_validate_case_normalization(self, mock_schema_cache, sample_property_schema):
        """Test validation normalizes case."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        decomposition = {
            'target_filters': {
                'ascendix__PropertyClass__c': 'a',  # lowercase
            }
        }
        
        validated, warnings = decomposer._validate_values(
            decomposition, sample_property_schema
        )
        
        assert validated['target_filters']['ascendix__PropertyClass__c'] == 'A'
        assert len(warnings) == 0
    
    def test_validate_invalid_value_warning(
        self, mock_schema_cache, sample_property_schema
    ):
        """Test validation warns on invalid values."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        decomposition = {
            'target_filters': {
                'ascendix__PropertyClass__c': 'X',  # Invalid
            }
        }
        
        validated, warnings = decomposer._validate_values(
            decomposition, sample_property_schema
        )
        
        assert len(warnings) > 0
        assert 'Invalid value' in warnings[0]


class TestFuzzyMatching:
    """Tests for fuzzy matching functionality."""
    
    def test_fuzzy_match_close_value(self, mock_schema_cache):
        """Test fuzzy matching finds close values."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        valid_values = ['Office', 'Retail', 'Industrial']
        
        # "Offic" is close to "Office"
        result = decomposer._fuzzy_match('Offic', valid_values)
        assert result == 'Office'
    
    def test_fuzzy_match_no_match(self, mock_schema_cache):
        """Test fuzzy matching returns None for distant values."""
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        valid_values = ['Office', 'Retail', 'Industrial']
        
        # "XYZ" is too different
        result = decomposer._fuzzy_match('XYZ', valid_values)
        assert result is None
    
    def test_normalize_value_function(self):
        """Test the standalone normalize_value function."""
        valid_values = ['Class A', 'Class B', 'Class C']
        
        # Case variations
        assert normalize_value('class a', valid_values) == 'Class A'
        assert normalize_value('CLASS A', valid_values) == 'Class A'
        assert normalize_value('Class A', valid_values) == 'Class A'
        
        # Whitespace variations
        assert normalize_value('  Class A  ', valid_values) == 'Class A'
        assert normalize_value('Class  A', valid_values) == 'Class A'


# =============================================================================
# Integration Tests (with mocked LLM)
# =============================================================================

class TestDecomposerIntegration:
    """Integration tests for the full decomposition flow."""
    
    def test_decompose_with_no_schema(self, mock_schema_cache):
        """Test decomposition when schema is not available."""
        # Make cache return None
        mock_schema_cache.get = Mock(return_value=None)
        
        decomposer = SchemaAwareDecomposer(schema_cache=mock_schema_cache)
        
        result = decomposer.decompose('properties in Dallas')
        
        assert result.target_entity == 'ascendix__Property__c'
        assert result.confidence < 1.0
        assert len(result.validation_warnings) > 0
    
    @patch('schema_decomposer.boto3.client')
    def test_decompose_with_llm_response(
        self, mock_boto_client, mock_schema_cache, sample_property_schema
    ):
        """Test decomposition with mocked LLM response."""
        # Mock LLM response
        mock_llm = MagicMock()
        mock_response = {
            'body': MagicMock()
        }
        mock_response['body'].read.return_value = b'''
        {
            "content": [
                {
                    "text": "{\\"target_entity\\": \\"ascendix__Property__c\\", \\"target_filters\\": {\\"ascendix__City__c\\": \\"dallas\\"}, \\"needs_traversal\\": false}"
                }
            ]
        }
        '''
        mock_llm.invoke_model.return_value = mock_response
        
        decomposer = SchemaAwareDecomposer(
            schema_cache=mock_schema_cache,
            llm_client=mock_llm
        )
        
        result = decomposer.decompose('properties in Dallas')
        
        assert result.target_entity == 'ascendix__Property__c'
        # Value should be normalized to canonical "Dallas"
        assert result.filters.get('ascendix__City__c') == 'Dallas'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])


# =============================================================================
# Property Test for Decomposition Structure (Property 7)
# =============================================================================

# Strategy for generating entity names
entity_strategy = st.sampled_from([
    'ascendix__Property__c',
    'ascendix__Deal__c',
    'ascendix__Availability__c',
    'ascendix__Lease__c',
    'Account',
])

# Strategy for generating filter dictionaries
filter_strategy = st.dictionaries(
    keys=st.text(
        alphabet='abcdefghijklmnopqrstuvwxyz_',
        min_size=1,
        max_size=30
    ),
    values=st.one_of(
        st.text(min_size=1, max_size=20),
        st.integers(min_value=0, max_value=1000000),
    ),
    min_size=0,
    max_size=5
)


@given(
    target_entity=entity_strategy,
    filters=filter_strategy,
    confidence=st.floats(min_value=0.0, max_value=1.0),
    original_query=st.text(min_size=1, max_size=100),
)
@settings(max_examples=100)
def test_property_decomposition_structure_completeness(
    target_entity,
    filters,
    confidence,
    original_query
):
    """
    **Property 7: Decomposition Structure Completeness**
    **Validates: Requirements 3.1, 3.4, 3.7**
    
    *For any* natural language query that mentions a target entity and filter
    criteria, the Schema-Aware Decomposer SHALL return a StructuredQuery
    containing the detected target entity and validated filters.
    
    This test verifies that StructuredQuery maintains structural integrity
    through serialization/deserialization round-trips.
    """
    # Create a StructuredQuery with the generated data
    query = StructuredQuery(
        target_entity=target_entity,
        filters=filters,
        numeric_filters={},
        date_filters={},
        traversals=[],
        confidence=confidence,
        original_query=original_query,
        validation_warnings=[],
    )
    
    # Serialize to dict
    query_dict = query.to_dict()
    
    # Verify structure completeness
    assert 'target_entity' in query_dict
    assert 'filters' in query_dict
    assert 'numeric_filters' in query_dict
    assert 'date_filters' in query_dict
    assert 'traversals' in query_dict
    assert 'confidence' in query_dict
    assert 'original_query' in query_dict
    assert 'validation_warnings' in query_dict
    
    # Deserialize back
    restored = StructuredQuery.from_dict(query_dict)
    
    # Verify round-trip preserves data
    assert restored.target_entity == target_entity
    assert restored.filters == filters
    assert restored.confidence == confidence
    assert restored.original_query == original_query


@given(
    query_text=st.text(
        alphabet='abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ',
        min_size=5,
        max_size=100
    ).filter(lambda x: x.strip())
)
@settings(max_examples=100)
def test_property_entity_detection_always_returns_valid_entity(query_text):
    """
    **Property 7: Decomposition Structure Completeness (entity detection)**
    **Validates: Requirements 3.1, 3.7**
    
    *For any* query text, entity detection SHALL always return a valid
    Salesforce object API name (never None or empty).
    """
    mock_cache = Mock()
    mock_cache.get = Mock(return_value=None)
    
    decomposer = SchemaAwareDecomposer(schema_cache=mock_cache)
    
    entity = decomposer.detect_target_entity(query_text)
    
    # Entity should never be None or empty
    assert entity is not None
    assert len(entity) > 0
    
    # Entity should be a valid Salesforce API name format
    # (either standard object or custom object ending in __c)
    assert entity in ENTITY_PATTERNS or entity == DEFAULT_ENTITY
