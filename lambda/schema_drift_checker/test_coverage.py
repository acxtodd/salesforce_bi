"""
Unit tests for Schema Drift Coverage Calculator.

Tests coverage calculation logic, drift detection, and edge cases.

**Feature: schema-drift-monitoring**
**Task: 39**
"""
import unittest
from datetime import datetime, timezone, timedelta

from coverage import (
    CoverageCalculator,
    DriftResult,
    normalize_field_name,
    extract_field_names,
    calculate_coverage,
    calculate_cache_age_hours,
    EXCLUDED_SYSTEM_FIELDS,
)


class TestNormalizeFieldName(unittest.TestCase):
    """Tests for field name normalization."""

    def test_lowercase_conversion(self):
        """Field names should be lowercased."""
        self.assertEqual(normalize_field_name('Name'), 'name')
        self.assertEqual(normalize_field_name('ascendix__City__c'), 'ascendix__city__c')
        self.assertEqual(normalize_field_name('RecordType'), 'recordtype')

    def test_whitespace_stripping(self):
        """Leading/trailing whitespace should be stripped."""
        self.assertEqual(normalize_field_name('  Name  '), 'name')
        self.assertEqual(normalize_field_name('\tCity\n'), 'city')

    def test_empty_string(self):
        """Empty string should return empty string."""
        self.assertEqual(normalize_field_name(''), '')
        self.assertEqual(normalize_field_name(None), '')


class TestExtractFieldNames(unittest.TestCase):
    """Tests for field name extraction."""

    def test_basic_extraction(self):
        """Should extract field names from list of dicts."""
        fields = [
            {'name': 'Name', 'type': 'string'},
            {'name': 'ascendix__City__c', 'type': 'picklist'},
        ]
        result = extract_field_names(fields)
        self.assertEqual(result, {'name', 'ascendix__city__c'})

    def test_excludes_system_fields(self):
        """System fields should be excluded from extraction."""
        fields = [
            {'name': 'Id', 'type': 'id'},
            {'name': 'Name', 'type': 'string'},
            {'name': 'IsDeleted', 'type': 'boolean'},
            {'name': 'SystemModstamp', 'type': 'datetime'},
            {'name': 'ascendix__City__c', 'type': 'picklist'},
        ]
        result = extract_field_names(fields)

        # Should only contain Name and City, not system fields
        self.assertEqual(result, {'name', 'ascendix__city__c'})
        self.assertNotIn('id', result)
        self.assertNotIn('isdeleted', result)
        self.assertNotIn('systemmodstamp', result)

    def test_empty_list(self):
        """Empty list should return empty set."""
        self.assertEqual(extract_field_names([]), set())

    def test_missing_name_key(self):
        """Fields without 'name' key should be skipped."""
        fields = [
            {'name': 'Name', 'type': 'string'},
            {'type': 'string'},  # Missing name
            {'name': '', 'type': 'string'},  # Empty name
        ]
        result = extract_field_names(fields)
        self.assertEqual(result, {'name'})


class TestCalculateCoverage(unittest.TestCase):
    """Tests for coverage percentage calculation."""

    def test_full_coverage(self):
        """100% coverage when cache has all SF fields."""
        sf_fields = {'name', 'city', 'state'}
        cache_fields = {'name', 'city', 'state', 'extra'}

        coverage = calculate_coverage(sf_fields, cache_fields)
        self.assertEqual(coverage, 100.0)

    def test_partial_coverage(self):
        """Partial coverage when cache is missing fields."""
        sf_fields = {'name', 'city', 'state', 'zip'}
        cache_fields = {'name', 'city'}  # Missing state, zip

        coverage = calculate_coverage(sf_fields, cache_fields)
        self.assertEqual(coverage, 50.0)  # 2/4 = 50%

    def test_zero_coverage(self):
        """0% coverage when cache has none of SF fields."""
        sf_fields = {'name', 'city', 'state'}
        cache_fields = {'other', 'fields'}

        coverage = calculate_coverage(sf_fields, cache_fields)
        self.assertEqual(coverage, 0.0)

    def test_empty_sf_fields(self):
        """100% coverage if SF has no fields (edge case)."""
        sf_fields = set()
        cache_fields = {'name', 'city'}

        coverage = calculate_coverage(sf_fields, cache_fields)
        self.assertEqual(coverage, 100.0)

    def test_empty_cache_fields(self):
        """0% coverage if cache has no fields but SF does."""
        sf_fields = {'name', 'city'}
        cache_fields = set()

        coverage = calculate_coverage(sf_fields, cache_fields)
        self.assertEqual(coverage, 0.0)


class TestCalculateCacheAgeHours(unittest.TestCase):
    """Tests for cache age calculation."""

    def test_recent_cache(self):
        """Cache from 1 hour ago should return ~1."""
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        age = calculate_cache_age_hours(one_hour_ago)
        self.assertAlmostEqual(age, 1.0, delta=0.1)

    def test_old_cache(self):
        """Cache from 24 hours ago should return ~24."""
        one_day_ago = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        age = calculate_cache_age_hours(one_day_ago)
        self.assertAlmostEqual(age, 24.0, delta=0.1)

    def test_missing_timestamp(self):
        """Missing timestamp should return -1."""
        self.assertEqual(calculate_cache_age_hours(None), -1.0)
        self.assertEqual(calculate_cache_age_hours(''), -1.0)

    def test_invalid_timestamp(self):
        """Invalid timestamp should return -1."""
        self.assertEqual(calculate_cache_age_hours('not-a-date'), -1.0)

    def test_z_suffix_timestamp(self):
        """Timestamps with Z suffix should be handled."""
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1))
        timestamp = one_hour_ago.strftime('%Y-%m-%dT%H:%M:%SZ')
        age = calculate_cache_age_hours(timestamp)
        self.assertAlmostEqual(age, 1.0, delta=0.1)


class TestCoverageCalculator(unittest.TestCase):
    """Tests for CoverageCalculator class."""

    def setUp(self):
        """Set up calculator for tests."""
        self.calculator = CoverageCalculator()

    def test_calculate_drift_no_drift(self):
        """No drift when schemas match."""
        sf_schema = {
            'filterable': [{'name': 'Name'}, {'name': 'ascendix__City__c'}],
            'numeric': [{'name': 'ascendix__Size__c'}],
            'date': [{'name': 'CreatedDate'}],  # System field, excluded
            'relationships': [{'name': 'OwnerId'}],  # System field, excluded
            'text': [],
        }
        cache_schema = {
            'filterable': [{'name': 'Name'}, {'name': 'ascendix__City__c'}],
            'numeric': [{'name': 'ascendix__Size__c'}],
            'date': [],
            'relationships': [],
            'text': [],
            'discovered_at': datetime.now(timezone.utc).isoformat(),
        }

        result = self.calculator.calculate_drift(sf_schema, cache_schema, 'TestObject')

        self.assertFalse(result.has_drift)
        self.assertEqual(result.fields_in_cache_not_sf, [])
        self.assertEqual(result.filterable_coverage, 100.0)

    def test_calculate_drift_fake_fields(self):
        """Drift detected when cache has fields not in SF."""
        sf_schema = {
            'filterable': [{'name': 'Name'}],
            'numeric': [],
            'date': [],
            'relationships': [],
            'text': [],
        }
        cache_schema = {
            'filterable': [{'name': 'Name'}, {'name': 'FakeField__c'}],
            'numeric': [],
            'date': [],
            'relationships': [],
            'text': [],
            'discovered_at': datetime.now(timezone.utc).isoformat(),
        }

        result = self.calculator.calculate_drift(sf_schema, cache_schema, 'TestObject')

        self.assertTrue(result.has_drift)
        self.assertIn('fakefield__c', result.fields_in_cache_not_sf)

    def test_calculate_drift_missing_fields(self):
        """Missing fields detected when SF has fields not in cache."""
        sf_schema = {
            'filterable': [{'name': 'Name'}, {'name': 'NewField__c'}],
            'numeric': [],
            'date': [],
            'relationships': [],
            'text': [],
        }
        cache_schema = {
            'filterable': [{'name': 'Name'}],
            'numeric': [],
            'date': [],
            'relationships': [],
            'text': [],
            'discovered_at': datetime.now(timezone.utc).isoformat(),
        }

        result = self.calculator.calculate_drift(sf_schema, cache_schema, 'TestObject')

        # Missing fields don't trigger has_drift (only fake fields do)
        self.assertFalse(result.has_drift)
        self.assertIn('newfield__c', result.fields_in_sf_not_cache)
        self.assertEqual(result.filterable_coverage, 50.0)

    def test_calculate_drift_system_fields_excluded(self):
        """System fields should not affect coverage calculations."""
        sf_schema = {
            'filterable': [
                {'name': 'Id'},  # System field
                {'name': 'Name'},
                {'name': 'IsDeleted'},  # System field
                {'name': 'ascendix__City__c'},
            ],
            'numeric': [],
            'date': [],
            'relationships': [],
            'text': [],
        }
        cache_schema = {
            'filterable': [{'name': 'Name'}, {'name': 'ascendix__City__c'}],
            'numeric': [],
            'date': [],
            'relationships': [],
            'text': [],
            'discovered_at': datetime.now(timezone.utc).isoformat(),
        }

        result = self.calculator.calculate_drift(sf_schema, cache_schema, 'TestObject')

        # Should be 100% coverage (2/2 non-system fields match)
        # NOT 50% (2/4 total fields)
        self.assertEqual(result.filterable_coverage, 100.0)
        self.assertFalse(result.has_drift)

    def test_summarize(self):
        """Summary should aggregate metrics correctly."""
        results = {
            'Object1': DriftResult(
                object_name='Object1',
                filterable_coverage=100.0,
                relationship_coverage=100.0,
                has_drift=False,
                fields_in_cache_not_sf=[],
                fields_in_sf_not_cache=[],
            ),
            'Object2': DriftResult(
                object_name='Object2',
                filterable_coverage=50.0,
                relationship_coverage=75.0,
                has_drift=True,
                fields_in_cache_not_sf=['fake1', 'fake2'],
                fields_in_sf_not_cache=['missing1'],
            ),
        }

        summary = self.calculator.summarize(results)

        self.assertEqual(summary['total_objects'], 2)
        self.assertEqual(summary['objects_with_drift'], 1)
        self.assertEqual(summary['total_fake_fields'], 2)
        self.assertEqual(summary['total_missing_fields'], 1)
        self.assertAlmostEqual(summary['avg_filterable_coverage'], 75.0)
        self.assertAlmostEqual(summary['avg_relationship_coverage'], 87.5)


class TestDriftResult(unittest.TestCase):
    """Tests for DriftResult dataclass."""

    def test_to_dict(self):
        """to_dict should serialize all fields correctly."""
        result = DriftResult(
            object_name='TestObject',
            sf_field_count=10,
            cache_field_count=8,
            filterable_coverage=80.0,
            relationship_coverage=66.666666,
            fields_in_cache_not_sf=['fake1'],
            fields_in_sf_not_cache=['missing1', 'missing2'],
            cache_age_hours=12.5,
            discovered_at='2025-12-12T10:00:00Z',
            has_drift=True,
        )

        d = result.to_dict()

        self.assertEqual(d['object_name'], 'TestObject')
        self.assertEqual(d['sf_field_count'], 10)
        self.assertEqual(d['cache_field_count'], 8)
        self.assertEqual(d['filterable_coverage'], 80.0)
        self.assertEqual(d['relationship_coverage'], 66.67)  # Rounded
        self.assertEqual(d['fields_in_cache_not_sf'], ['fake1'])
        self.assertEqual(d['fields_in_sf_not_cache'], ['missing1', 'missing2'])
        self.assertEqual(d['cache_age_hours'], 12.5)
        self.assertTrue(d['has_drift'])


class TestEmptyCacheHandling(unittest.TestCase):
    """Tests for empty cache edge case (QA gap #4)."""

    def setUp(self):
        """Set up calculator for tests."""
        self.calculator = CoverageCalculator()

    def test_empty_results_summary(self):
        """Empty results should report 0% coverage, not 100%."""
        results = {}  # Empty cache

        summary = self.calculator.summarize(results)

        # Empty cache = 0% coverage (failure state)
        self.assertEqual(summary['total_objects'], 0)
        self.assertEqual(summary['avg_filterable_coverage'], 0.0)
        self.assertEqual(summary['avg_relationship_coverage'], 0.0)
        self.assertEqual(summary['objects_with_drift'], 0)

    def test_calculate_all_drift_empty_cache(self):
        """Empty cache should produce empty results."""
        sf_schemas = {}
        cache_schemas = {}

        results = self.calculator.calculate_all_drift(sf_schemas, cache_schemas)

        self.assertEqual(len(results), 0)


if __name__ == '__main__':
    unittest.main()
