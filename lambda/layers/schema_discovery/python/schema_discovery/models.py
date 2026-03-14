"""
Data models for Schema Discovery.

Defines FieldSchema and ObjectSchema dataclasses for representing
Salesforce object metadata discovered via the Describe API.

**Feature: zero-config-schema-discovery**
**Requirements: 1.1, 1.2, 1.3, 1.4, 1.5**
"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone


# Field type constants for classification
FIELD_TYPE_FILTERABLE = 'filterable'
FIELD_TYPE_NUMERIC = 'numeric'
FIELD_TYPE_DATE = 'date'
FIELD_TYPE_RELATIONSHIP = 'relationship'
FIELD_TYPE_TEXT = 'text'

# Salesforce field types that map to each category
PICKLIST_TYPES = {'picklist', 'multipicklist'}
NUMERIC_TYPES = {'double', 'currency', 'int', 'percent'}
DATE_TYPES = {'date', 'datetime'}
TEXT_TYPES = {'string', 'textarea', 'email', 'phone', 'url'}


@dataclass
class FieldSchema:
    """
    Schema for a single Salesforce field.

    **Requirements: 1.2, 1.3, 1.4, 1.5, 26.1-26.5**

    Attributes:
        name: API name of the field (e.g., 'ascendix__PropertyClass__c')
        label: Human-readable label (e.g., 'Property Class')
        type: Classification type ('filterable', 'numeric', 'date', 'relationship', 'text')
        values: List of valid picklist values (for filterable fields only)
        reference_to: Target object API name (for relationship fields only)
        sf_type: Original Salesforce field type (e.g., 'picklist', 'double')
        relevance_score: Signal-based relevance score (0-10), higher = more important
        usage_context: List of usage contexts ('filter', 'result_column', 'sort', 'relationship')
        source_signals: List of signal sources (e.g., 'SavedSearch: Class A office')
    """
    name: str
    label: str
    type: str  # 'filterable', 'numeric', 'date', 'relationship', 'text'
    values: Optional[List[str]] = None  # For picklists
    reference_to: Optional[str] = None  # For relationships
    sf_type: Optional[str] = None  # Original SF type for debugging
    # Signal Harvesting fields (Req 26.1-26.5)
    relevance_score: Optional[float] = None  # 0-10, None = not scored
    usage_context: Optional[List[str]] = None  # ['filter', 'result_column', 'sort']
    source_signals: Optional[List[str]] = None  # ['SavedSearch: Class A office']
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        from decimal import Decimal
        result = {
            'name': self.name,
            'label': self.label,
            'type': self.type,
        }
        if self.values is not None:
            result['values'] = self.values
        if self.reference_to is not None:
            result['reference_to'] = self.reference_to
        if self.sf_type is not None:
            result['sf_type'] = self.sf_type
        # Signal Harvesting fields (optional, backward compatible)
        # Convert float to Decimal for DynamoDB compatibility
        if self.relevance_score is not None:
            result['relevance_score'] = Decimal(str(self.relevance_score))
        if self.usage_context is not None:
            result['usage_context'] = self.usage_context
        if self.source_signals is not None:
            result['source_signals'] = self.source_signals
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FieldSchema':
        """Create FieldSchema from dictionary."""
        # Convert Decimal back to float for relevance_score (DynamoDB returns Decimal)
        relevance_score = data.get('relevance_score')
        if relevance_score is not None:
            relevance_score = float(relevance_score)
        return cls(
            name=data['name'],
            label=data['label'],
            type=data['type'],
            values=data.get('values'),
            reference_to=data.get('reference_to'),
            sf_type=data.get('sf_type'),
            # Signal Harvesting fields (optional, backward compatible)
            relevance_score=relevance_score,
            usage_context=data.get('usage_context'),
            source_signals=data.get('source_signals'),
        )
    
    def __eq__(self, other: object) -> bool:
        """Check equality for testing."""
        if not isinstance(other, FieldSchema):
            return False
        return (
            self.name == other.name and
            self.label == other.label and
            self.type == other.type and
            self.values == other.values and
            self.reference_to == other.reference_to and
            self.relevance_score == other.relevance_score and
            self.usage_context == other.usage_context and
            self.source_signals == other.source_signals
        )


@dataclass
class ObjectSchema:
    """
    Complete schema for a Salesforce object.

    **Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 24.1-24.6**

    Attributes:
        api_name: Object API name (e.g., 'ascendix__Property__c')
        label: Human-readable label (e.g., 'Property')
        filterable: List of picklist fields with valid values
        numeric: List of numeric fields (double, currency, int, percent)
        date: List of date/datetime fields
        relationships: List of reference/lookup fields
        text: List of text fields (for vector search)
        discovered_at: ISO timestamp when schema was discovered
        primary_relationships: List of relationship fields marked as primary by signal harvesting
    """
    api_name: str
    label: str
    filterable: List[FieldSchema] = field(default_factory=list)
    numeric: List[FieldSchema] = field(default_factory=list)
    date: List[FieldSchema] = field(default_factory=list)
    relationships: List[FieldSchema] = field(default_factory=list)
    text: List[FieldSchema] = field(default_factory=list)
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Signal Harvesting: Primary relationships (Req 24.4)
    primary_relationships: Optional[List[str]] = None
    
    def get_field(self, name: str) -> Optional[FieldSchema]:
        """
        Get field schema by name.
        
        Args:
            name: Field API name
            
        Returns:
            FieldSchema if found, None otherwise
        """
        all_fields = (
            self.filterable + 
            self.numeric + 
            self.date + 
            self.relationships + 
            self.text
        )
        for f in all_fields:
            if f.name == name:
                return f
        return None
    
    def get_picklist_values(self, field_name: str) -> List[str]:
        """
        Get valid picklist values for a field.
        
        Args:
            field_name: Field API name
            
        Returns:
            List of valid values, empty list if not a picklist field
        """
        for f in self.filterable:
            if f.name == field_name and f.values:
                return f.values
        return []
    
    def get_all_filterable_field_names(self) -> List[str]:
        """Get names of all filterable fields."""
        return [f.name for f in self.filterable]
    
    def get_all_numeric_field_names(self) -> List[str]:
        """Get names of all numeric fields."""
        return [f.name for f in self.numeric]
    
    def get_all_date_field_names(self) -> List[str]:
        """Get names of all date fields."""
        return [f.name for f in self.date]
    
    def get_all_relationship_field_names(self) -> List[str]:
        """Get names of all relationship fields."""
        return [f.name for f in self.relationships]

    def apply_relevance_scores(self, field_scores: Dict[str, Any]) -> None:
        """
        Apply relevance scores from signal harvesting to fields.

        **Requirements: 26.1-26.5**

        Args:
            field_scores: Dict mapping field name to FieldRelevance-like object
                          with relevance_score, usage_context, source_signals
        """
        all_field_lists = [
            self.filterable,
            self.numeric,
            self.date,
            self.relationships,
            self.text
        ]

        for field_list in all_field_lists:
            for field in field_list:
                if field.name in field_scores:
                    relevance = field_scores[field.name]
                    # Handle both FieldRelevance objects and dicts
                    if hasattr(relevance, 'relevance_score'):
                        field.relevance_score = relevance.relevance_score
                        field.usage_context = list(relevance.usage_context) if relevance.usage_context else None
                        field.source_signals = relevance.source_signals
                    elif isinstance(relevance, dict):
                        field.relevance_score = relevance.get('relevance_score')
                        field.usage_context = relevance.get('usage_context')
                        field.source_signals = relevance.get('source_signals')

    def get_high_relevance_fields(self, min_score: float = 5.0) -> List[FieldSchema]:
        """
        Get fields with relevance score above threshold.

        **Requirements: 27.1-27.3**

        Args:
            min_score: Minimum relevance score (default: 5.0)

        Returns:
            List of FieldSchema sorted by relevance_score descending
        """
        all_fields = (
            self.filterable +
            self.numeric +
            self.date +
            self.relationships +
            self.text
        )

        high_relevance = [
            f for f in all_fields
            if f.relevance_score is not None and f.relevance_score >= min_score
        ]

        return sorted(high_relevance, key=lambda f: f.relevance_score or 0, reverse=True)

    def apply_default_relevance_scores(self) -> None:
        """
        Apply default relevance scores to fields without signal-based scores.

        **Requirements: Task 41.4**

        Default scores by field type and category:
        - System fields (Id, CreatedDate, etc.): 1.0
        - Standard metadata fields: 2.0
        - Text fields: 3.0
        - Date fields: 4.0
        - Numeric fields: 4.0
        - Filterable fields: 5.0
        - Relationship fields: 5.0
        - Name field: 6.0

        These defaults ensure all fields have a relevance score for disambiguation,
        while signal-harvested scores (7-10) take priority.
        """
        # System fields that should have low relevance
        system_fields = {
            'Id', 'IsDeleted', 'CreatedById', 'CreatedDate', 'LastModifiedById',
            'LastModifiedDate', 'SystemModstamp', 'LastActivityDate', 'LastViewedDate',
            'LastReferencedDate', 'OwnerId', 'RecordTypeId'
        }

        # Apply defaults to each field category
        all_field_lists = [
            (self.filterable, 5.0),
            (self.numeric, 4.0),
            (self.date, 4.0),
            (self.relationships, 5.0),
            (self.text, 3.0),
        ]

        for field_list, default_score in all_field_lists:
            for field in field_list:
                # Skip if already has a signal-based score
                if field.relevance_score is not None:
                    continue

                # Assign default based on field characteristics
                if field.name in system_fields:
                    field.relevance_score = 1.0
                elif field.name == 'Name':
                    field.relevance_score = 6.0
                elif field.name == 'RecordType':
                    field.relevance_score = 6.0  # RecordType is important for filtering
                else:
                    field.relevance_score = default_score

                # Mark as default score (not from signals)
                if field.source_signals is None:
                    field.source_signals = ['default']

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            'api_name': self.api_name,
            'label': self.label,
            'filterable': [f.to_dict() for f in self.filterable],
            'numeric': [f.to_dict() for f in self.numeric],
            'date': [f.to_dict() for f in self.date],
            'relationships': [f.to_dict() for f in self.relationships],
            'text': [f.to_dict() for f in self.text],
            'discovered_at': self.discovered_at,
        }
        # Signal Harvesting: Include primary relationships if set
        if self.primary_relationships is not None:
            result['primary_relationships'] = self.primary_relationships
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ObjectSchema':
        """Create ObjectSchema from dictionary."""
        return cls(
            api_name=data['api_name'],
            label=data['label'],
            filterable=[FieldSchema.from_dict(f) for f in data.get('filterable', [])],
            numeric=[FieldSchema.from_dict(f) for f in data.get('numeric', [])],
            date=[FieldSchema.from_dict(f) for f in data.get('date', [])],
            relationships=[FieldSchema.from_dict(f) for f in data.get('relationships', [])],
            text=[FieldSchema.from_dict(f) for f in data.get('text', [])],
            discovered_at=data.get('discovered_at', datetime.now(timezone.utc).isoformat()),
            # Signal Harvesting: Load primary relationships (backward compatible)
            primary_relationships=data.get('primary_relationships'),
        )
    
    def __eq__(self, other: object) -> bool:
        """Check equality for testing."""
        if not isinstance(other, ObjectSchema):
            return False
        return (
            self.api_name == other.api_name and
            self.label == other.label and
            self.filterable == other.filterable and
            self.numeric == other.numeric and
            self.date == other.date and
            self.relationships == other.relationships and
            self.text == other.text
        )


def classify_field_type(sf_field: Dict[str, Any]) -> str:
    """
    Classify a Salesforce field into one of the schema categories.
    
    **Property 1: Field Type Classification Correctness**
    **Validates: Requirements 1.2, 1.3, 1.4, 1.5**
    
    Classification rules:
    - picklist/multipicklist → 'filterable'
    - double/currency/int/percent → 'numeric'
    - date/datetime → 'date'
    - reference (with referenceTo) → 'relationship'
    - string/textarea/email/phone/url → 'text'
    
    Args:
        sf_field: Salesforce field definition from Describe API
        
    Returns:
        Classification type string
    """
    sf_type = sf_field.get('type', '').lower()
    
    # Check for picklist types first (filterable)
    if sf_type in PICKLIST_TYPES:
        return FIELD_TYPE_FILTERABLE
    
    # Check for numeric types
    if sf_type in NUMERIC_TYPES:
        return FIELD_TYPE_NUMERIC
    
    # Check for date types
    if sf_type in DATE_TYPES:
        return FIELD_TYPE_DATE
    
    # Check for relationship (reference with referenceTo)
    if sf_type == 'reference':
        reference_to = sf_field.get('referenceTo', [])
        if reference_to:
            return FIELD_TYPE_RELATIONSHIP
    
    # Default to text for string-like types
    if sf_type in TEXT_TYPES:
        return FIELD_TYPE_TEXT
    
    # Fallback to text for unknown types
    return FIELD_TYPE_TEXT
