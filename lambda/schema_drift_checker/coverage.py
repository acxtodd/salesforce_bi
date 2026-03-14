"""
Schema Coverage Calculator.

Calculates coverage metrics between Salesforce Describe API output and Schema Cache.
Uses precise comparison semantics with normalized field names.

**Feature: schema-drift-monitoring**
**Task: 39.1**
"""
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional
from datetime import datetime, timezone


# System fields excluded from coverage calculations
# These are auto-managed by Salesforce and not useful for filtering
EXCLUDED_SYSTEM_FIELDS = frozenset({
    'id',
    'isdeleted',
    'systemmodstamp',
    'createdbyid',
    'lastmodifiedbyid',
    'createddate',
    'lastmodifieddate',
    'ownerid',
})


@dataclass
class DriftResult:
    """Result of drift analysis for a single object."""
    object_name: str

    # Field counts
    sf_field_count: int = 0
    cache_field_count: int = 0

    # Coverage percentages (0-100)
    filterable_coverage: float = 0.0
    relationship_coverage: float = 0.0
    numeric_coverage: float = 0.0
    date_coverage: float = 0.0

    # Drift indicators
    fields_in_cache_not_sf: List[str] = field(default_factory=list)  # CRITICAL - fake fields
    fields_in_sf_not_cache: List[str] = field(default_factory=list)  # Missing fields

    # Cache freshness
    cache_age_hours: float = 0.0
    discovered_at: Optional[str] = None

    # Overall drift flag
    has_drift: bool = False

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            'object_name': self.object_name,
            'sf_field_count': self.sf_field_count,
            'cache_field_count': self.cache_field_count,
            'filterable_coverage': round(self.filterable_coverage, 2),
            'relationship_coverage': round(self.relationship_coverage, 2),
            'numeric_coverage': round(self.numeric_coverage, 2),
            'date_coverage': round(self.date_coverage, 2),
            'fields_in_cache_not_sf': self.fields_in_cache_not_sf,
            'fields_in_sf_not_cache': self.fields_in_sf_not_cache,
            'cache_age_hours': round(self.cache_age_hours, 2),
            'discovered_at': self.discovered_at,
            'has_drift': self.has_drift,
        }


def normalize_field_name(name: str) -> str:
    """
    Normalize field name for comparison.

    Uses lowercase comparison to handle case variations between
    SF Describe API and cached schema.

    Args:
        name: Field API name

    Returns:
        Normalized (lowercase, stripped) field name
    """
    return name.lower().strip() if name else ''


def extract_field_names(fields: List[Dict], field_type: Optional[str] = None) -> Set[str]:
    """
    Extract normalized field names from a list of field definitions.

    Excludes system fields from the result.

    Args:
        fields: List of field dictionaries with 'name' key
        field_type: Optional filter by field type

    Returns:
        Set of normalized field names (excluding system fields)
    """
    names = set()
    for f in fields:
        name = f.get('name', '') if isinstance(f, dict) else getattr(f, 'name', '')
        if not name:
            continue

        normalized = normalize_field_name(name)

        # Skip system fields
        if normalized in EXCLUDED_SYSTEM_FIELDS:
            continue

        # Optionally filter by type
        if field_type:
            f_type = f.get('type', '') if isinstance(f, dict) else getattr(f, 'type', '')
            if f_type != field_type:
                continue

        names.add(normalized)

    return names


def calculate_coverage(sf_fields: Set[str], cache_fields: Set[str]) -> float:
    """
    Calculate coverage percentage of SF fields present in cache.

    Formula: |SF ∩ Cache| / |SF| * 100

    Args:
        sf_fields: Set of normalized field names from Salesforce
        cache_fields: Set of normalized field names from cache

    Returns:
        Coverage percentage (0-100), or 100.0 if SF has no fields
    """
    if not sf_fields:
        return 100.0  # If SF has no fields, cache is "fully covered"

    intersection = sf_fields & cache_fields
    return (len(intersection) / len(sf_fields)) * 100


def calculate_cache_age_hours(discovered_at: Optional[str]) -> float:
    """
    Calculate hours since schema was discovered.

    Args:
        discovered_at: ISO timestamp string of discovery time

    Returns:
        Hours since discovery, or -1 if timestamp invalid/missing
    """
    if not discovered_at:
        return -1.0

    try:
        # Parse ISO timestamp
        if discovered_at.endswith('Z'):
            discovered_at = discovered_at[:-1] + '+00:00'

        discovery_time = datetime.fromisoformat(discovered_at)

        # Ensure timezone-aware
        if discovery_time.tzinfo is None:
            discovery_time = discovery_time.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        delta = now - discovery_time

        return delta.total_seconds() / 3600  # Convert to hours
    except (ValueError, TypeError):
        return -1.0


class CoverageCalculator:
    """
    Calculate schema coverage between Salesforce and cache.

    This class is READ-ONLY - it never modifies the schema cache.
    """

    def __init__(self):
        """Initialize calculator."""
        pass

    def calculate_drift(
        self,
        sf_schema: Dict,
        cache_schema: Dict,
        object_name: str
    ) -> DriftResult:
        """
        Calculate drift between SF schema and cached schema for one object.

        Args:
            sf_schema: Schema from Salesforce Describe API (ObjectSchema.to_dict())
            cache_schema: Schema from DynamoDB cache (ObjectSchema.to_dict())
            object_name: Object API name

        Returns:
            DriftResult with coverage metrics and drift indicators
        """
        result = DriftResult(object_name=object_name)

        # Extract fields by category from SF schema
        sf_filterable = extract_field_names(sf_schema.get('filterable', []))
        sf_numeric = extract_field_names(sf_schema.get('numeric', []))
        sf_date = extract_field_names(sf_schema.get('date', []))
        sf_relationships = extract_field_names(sf_schema.get('relationships', []))
        sf_text = extract_field_names(sf_schema.get('text', []))
        sf_all = sf_filterable | sf_numeric | sf_date | sf_relationships | sf_text

        # Extract fields by category from cache schema
        cache_filterable = extract_field_names(cache_schema.get('filterable', []))
        cache_numeric = extract_field_names(cache_schema.get('numeric', []))
        cache_date = extract_field_names(cache_schema.get('date', []))
        cache_relationships = extract_field_names(cache_schema.get('relationships', []))
        cache_text = extract_field_names(cache_schema.get('text', []))
        cache_all = cache_filterable | cache_numeric | cache_date | cache_relationships | cache_text

        # Field counts
        result.sf_field_count = len(sf_all)
        result.cache_field_count = len(cache_all)

        # Coverage percentages by category
        result.filterable_coverage = calculate_coverage(sf_filterable, cache_filterable)
        result.relationship_coverage = calculate_coverage(sf_relationships, cache_relationships)
        result.numeric_coverage = calculate_coverage(sf_numeric, cache_numeric)
        result.date_coverage = calculate_coverage(sf_date, cache_date)

        # Drift detection - CRITICAL: fields in cache but not in SF (fake fields)
        fake_fields = cache_all - sf_all
        result.fields_in_cache_not_sf = sorted(list(fake_fields))

        # Missing fields - fields in SF but not in cache
        missing_fields = sf_all - cache_all
        result.fields_in_sf_not_cache = sorted(list(missing_fields))

        # Cache freshness
        discovered_at = cache_schema.get('discovered_at')
        result.discovered_at = discovered_at
        result.cache_age_hours = calculate_cache_age_hours(discovered_at)

        # Overall drift flag
        result.has_drift = len(result.fields_in_cache_not_sf) > 0

        return result

    def calculate_all_drift(
        self,
        sf_schemas: Dict[str, Dict],
        cache_schemas: Dict[str, Dict]
    ) -> Dict[str, DriftResult]:
        """
        Calculate drift for all objects.

        Args:
            sf_schemas: Dict mapping object name to SF schema dict
            cache_schemas: Dict mapping object name to cached schema dict

        Returns:
            Dict mapping object name to DriftResult
        """
        results = {}

        # Get union of all object names
        all_objects = set(sf_schemas.keys()) | set(cache_schemas.keys())

        for obj_name in all_objects:
            sf_schema = sf_schemas.get(obj_name, {})
            cache_schema = cache_schemas.get(obj_name, {})

            results[obj_name] = self.calculate_drift(sf_schema, cache_schema, obj_name)

        return results

    def summarize(self, results: Dict[str, DriftResult]) -> Dict:
        """
        Generate summary statistics across all objects.

        Args:
            results: Dict mapping object name to DriftResult

        Returns:
            Summary dict with aggregate metrics
        """
        if not results:
            return {
                'total_objects': 0,
                'objects_with_drift': 0,
                'avg_filterable_coverage': 0.0,
                'avg_relationship_coverage': 0.0,
                'total_fake_fields': 0,
                'total_missing_fields': 0,
            }

        drift_count = sum(1 for r in results.values() if r.has_drift)

        filterable_coverages = [r.filterable_coverage for r in results.values()]
        relationship_coverages = [r.relationship_coverage for r in results.values()]

        total_fake = sum(len(r.fields_in_cache_not_sf) for r in results.values())
        total_missing = sum(len(r.fields_in_sf_not_cache) for r in results.values())

        return {
            'total_objects': len(results),
            'objects_with_drift': drift_count,
            'avg_filterable_coverage': sum(filterable_coverages) / len(filterable_coverages),
            'avg_relationship_coverage': sum(relationship_coverages) / len(relationship_coverages),
            'total_fake_fields': total_fake,
            'total_missing_fields': total_missing,
        }
