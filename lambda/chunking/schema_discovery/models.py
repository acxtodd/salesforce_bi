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
    
    **Requirements: 1.2, 1.3, 1.4, 1.5**
    
    Attributes:
        name: API name of the field (e.g., 'ascendix__PropertyClass__c')
        label: Human-readable label (e.g., 'Property Class')
        type: Classification type ('filterable', 'numeric', 'date', 'relationship', 'text')
        values: List of valid picklist values (for filterable fields only)
        reference_to: Target object API name (for relationship fields only)
        sf_type: Original Salesforce field type (e.g., 'picklist', 'double')
    """
    name: str
    label: str
    type: str  # 'filterable', 'numeric', 'date', 'relationship', 'text'
    values: Optional[List[str]] = None  # For picklists
    reference_to: Optional[str] = None  # For relationships
    sf_type: Optional[str] = None  # Original SF type for debugging
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
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
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FieldSchema':
        """Create FieldSchema from dictionary."""
        return cls(
            name=data['name'],
            label=data['label'],
            type=data['type'],
            values=data.get('values'),
            reference_to=data.get('reference_to'),
            sf_type=data.get('sf_type'),
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
            self.reference_to == other.reference_to
        )


@dataclass
class ObjectSchema:
    """
    Complete schema for a Salesforce object.
    
    **Requirements: 1.1, 1.2, 1.3, 1.4, 1.5**
    
    Attributes:
        api_name: Object API name (e.g., 'ascendix__Property__c')
        label: Human-readable label (e.g., 'Property')
        filterable: List of picklist fields with valid values
        numeric: List of numeric fields (double, currency, int, percent)
        date: List of date/datetime fields
        relationships: List of reference/lookup fields
        text: List of text fields (for vector search)
        discovered_at: ISO timestamp when schema was discovered
    """
    api_name: str
    label: str
    filterable: List[FieldSchema] = field(default_factory=list)
    numeric: List[FieldSchema] = field(default_factory=list)
    date: List[FieldSchema] = field(default_factory=list)
    relationships: List[FieldSchema] = field(default_factory=list)
    text: List[FieldSchema] = field(default_factory=list)
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'api_name': self.api_name,
            'label': self.label,
            'filterable': [f.to_dict() for f in self.filterable],
            'numeric': [f.to_dict() for f in self.numeric],
            'date': [f.to_dict() for f in self.date],
            'relationships': [f.to_dict() for f in self.relationships],
            'text': [f.to_dict() for f in self.text],
            'discovered_at': self.discovered_at,
        }
    
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
