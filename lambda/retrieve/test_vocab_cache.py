"""
Tests for Vocabulary Cache.

Unit tests for VocabCache class including term storage, retrieval,
vocabulary building, and relevance scoring.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 2.1, 2.3, 2.4**
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# Add the retrieve directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vocab_cache import (
    DEFAULT_TTL_HOURS,
    RELEVANCE_SCORES,
    VocabCache,
    VocabEntry,
    VocabTerm,
    build_vocabulary_from_schema,
    lookup_term,
)


# =============================================================================
# Test Fixtures
# =============================================================================


class MockDynamoDBTable:
    """Mock DynamoDB table for testing."""

    def __init__(self):
        self.items: Dict[str, Dict[str, Any]] = {}
        self.gsi_items: Dict[str, List[Dict[str, Any]]] = {}

    def put_item(self, Item: Dict[str, Any]) -> None:
        """Store an item."""
        key = f"{Item['vocab_key']}#{Item['term']}"
        self.items[key] = Item
        # Update GSI
        term = Item["term"]
        if term not in self.gsi_items:
            self.gsi_items[term] = []
        # Remove existing entry for this key if present
        self.gsi_items[term] = [i for i in self.gsi_items[term] if i.get("vocab_key") != Item["vocab_key"] or i.get("term") != Item["term"]]
        self.gsi_items[term].append(Item)

    def query(self, **kwargs) -> Dict[str, Any]:
        """Query items."""
        if "IndexName" in kwargs and kwargs["IndexName"] == "term-lookup-index":
            # GSI query by term
            term = kwargs["ExpressionAttributeValues"][":t"]
            items = self.gsi_items.get(term, [])
            return {"Items": items}
        else:
            # Primary key query
            vocab_key = kwargs["ExpressionAttributeValues"][":vk"]
            items = [v for k, v in self.items.items() if k.startswith(f"{vocab_key}#")]
            return {"Items": items}

    def batch_writer(self):
        """Return a batch writer context manager."""
        return MockBatchWriter(self)

    def delete_item(self, Key: Dict[str, Any]) -> None:
        """Delete an item."""
        key = f"{Key['vocab_key']}#{Key['term']}"
        if key in self.items:
            item = self.items.pop(key)
            term = item["term"]
            if term in self.gsi_items:
                self.gsi_items[term] = [i for i in self.gsi_items[term] if i.get("vocab_key") != Key["vocab_key"] or i.get("term") != Key["term"]]


class MockBatchWriter:
    """Mock batch writer for DynamoDB."""

    def __init__(self, table: MockDynamoDBTable):
        self.table = table

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def put_item(self, Item: Dict[str, Any]) -> None:
        self.table.put_item(Item)

    def delete_item(self, Key: Dict[str, Any]) -> None:
        self.table.delete_item(Key)


@pytest.fixture
def mock_table():
    """Create a mock DynamoDB table."""
    return MockDynamoDBTable()


@pytest.fixture
def vocab_cache(mock_table):
    """Create a VocabCache with mock table."""
    cache = VocabCache(table_name="test-vocab-cache")
    cache._table = mock_table
    return cache


# =============================================================================
# Unit Tests for VocabTerm
# =============================================================================


class TestVocabTerm:
    """Unit tests for VocabTerm dataclass."""

    def test_vocab_term_creation(self):
        """Test basic VocabTerm creation."""
        term = VocabTerm(
            term="class a",
            canonical_value="Class A",
            object_name="Property__c",
            field_name="PropertyClass__c",
            source="picklist",
            relevance_score=0.6,
            vocab_type="picklist",
        )
        assert term.term == "class a"
        assert term.canonical_value == "Class A"
        assert term.object_name == "Property__c"
        assert term.field_name == "PropertyClass__c"
        assert term.source == "picklist"
        assert term.relevance_score == 0.6

    def test_vocab_term_to_dict(self):
        """Test VocabTerm serialization."""
        term = VocabTerm(
            term="office",
            canonical_value="Office",
            object_name="Property__c",
            source="recordtype",
            relevance_score=0.8,
            vocab_type="recordtype",
        )
        result = term.to_dict()
        assert result["term"] == "office"
        assert result["canonical_value"] == "Office"
        assert result["source"] == "recordtype"
        assert "field_name" not in result  # None values excluded

    def test_vocab_term_from_dict(self):
        """Test VocabTerm deserialization."""
        data = {
            "term": "available",
            "canonical_value": "Available",
            "object_name": "Availability__c",
            "field_name": "Status__c",
            "source": "picklist",
            "relevance_score": "0.6",
            "vocab_type": "picklist",
        }
        term = VocabTerm.from_dict(data)
        assert term.term == "available"
        assert term.canonical_value == "Available"
        assert term.relevance_score == 0.6


# =============================================================================
# Unit Tests for VocabEntry
# =============================================================================


class TestVocabEntry:
    """Unit tests for VocabEntry dataclass."""

    def test_vocab_entry_to_item(self):
        """Test VocabEntry to DynamoDB item conversion."""
        entry = VocabEntry(
            vocab_key="picklist#Property__c",
            term="class a",
            canonical_value="Class A",
            field_name="PropertyClass__c",
            source="picklist",
            relevance_score=0.6,
            ttl=1735689600,
        )
        item = entry.to_item()
        assert item["vocab_key"] == "picklist#Property__c"
        assert item["term"] == "class a"
        assert item["canonical_value"] == "Class A"
        assert item["field_name"] == "PropertyClass__c"
        assert item["ttl"] == 1735689600

    def test_vocab_entry_from_item(self):
        """Test VocabEntry from DynamoDB item."""
        item = {
            "vocab_key": "label#Account",
            "term": "account name",
            "canonical_value": "Account Name",
            "source": "describe",
            "relevance_score": "0.4",
            "ttl": 1735689600,
            "updated_at": "2025-01-01T00:00:00+00:00",
        }
        entry = VocabEntry.from_item(item)
        assert entry.vocab_key == "label#Account"
        assert entry.term == "account name"
        assert entry.relevance_score == 0.4


# =============================================================================
# Unit Tests for VocabCache Core Operations
# =============================================================================


class TestVocabCacheCore:
    """Unit tests for VocabCache core CRUD operations."""

    def test_make_vocab_key(self, vocab_cache):
        """Test vocab key generation."""
        key = vocab_cache._make_vocab_key("picklist", "Property__c")
        assert key == "picklist#Property__c"

    def test_calculate_ttl(self, vocab_cache):
        """Test TTL calculation."""
        ttl = vocab_cache._calculate_ttl(24)
        expected_min = int((datetime.now(timezone.utc) + timedelta(hours=23)).timestamp())
        expected_max = int((datetime.now(timezone.utc) + timedelta(hours=25)).timestamp())
        assert expected_min < ttl < expected_max

    def test_is_expired_false(self, vocab_cache):
        """Test TTL not expired."""
        future_ttl = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
        assert not vocab_cache._is_expired(future_ttl)

    def test_is_expired_true(self, vocab_cache):
        """Test TTL expired."""
        past_ttl = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
        assert vocab_cache._is_expired(past_ttl)

    def test_put_and_get_terms(self, vocab_cache):
        """Test storing and retrieving terms."""
        terms = [
            VocabTerm(
                term="class a",
                canonical_value="Class A",
                object_name="Property__c",
                field_name="PropertyClass__c",
                source="picklist",
                relevance_score=0.6,
                vocab_type="picklist",
            ),
            VocabTerm(
                term="class b",
                canonical_value="Class B",
                object_name="Property__c",
                field_name="PropertyClass__c",
                source="picklist",
                relevance_score=0.6,
                vocab_type="picklist",
            ),
        ]

        # Store terms
        result = vocab_cache.put_terms("picklist", "Property__c", terms)
        assert result is True

        # Retrieve terms
        retrieved = vocab_cache.get_terms("picklist", "Property__c")
        assert len(retrieved) == 2
        assert any(t["canonical_value"] == "Class A" for t in retrieved)
        assert any(t["canonical_value"] == "Class B" for t in retrieved)

    def test_get_terms_filters_expired(self, vocab_cache, mock_table):
        """Test that expired terms are filtered out."""
        # Add an expired item directly
        expired_ttl = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
        mock_table.put_item({
            "vocab_key": "picklist#Property__c",
            "term": "expired term",
            "canonical_value": "Expired",
            "source": "picklist",
            "relevance_score": "0.6",
            "ttl": expired_ttl,
        })

        # Add a valid item
        valid_ttl = int((datetime.now(timezone.utc) + timedelta(hours=24)).timestamp())
        mock_table.put_item({
            "vocab_key": "picklist#Property__c",
            "term": "valid term",
            "canonical_value": "Valid",
            "source": "picklist",
            "relevance_score": "0.6",
            "ttl": valid_ttl,
        })

        # Retrieve - should only get valid term
        retrieved = vocab_cache.get_terms("picklist", "Property__c")
        assert len(retrieved) == 1
        assert retrieved[0]["canonical_value"] == "Valid"

    def test_lookup_term(self, vocab_cache):
        """Test term lookup."""
        terms = [
            VocabTerm(
                term="office",
                canonical_value="Office",
                object_name="Property__c",
                field_name="RecordTypeId",
                source="recordtype",
                relevance_score=0.8,
                vocab_type="recordtype",
            ),
        ]
        vocab_cache.put_terms("recordtype", "Property__c", terms)

        # Lookup
        result = vocab_cache.lookup("office")
        assert result is not None
        assert result["canonical_value"] == "Office"
        assert result["object_name"] == "Property__c"
        assert result["relevance_score"] == 0.8

    def test_lookup_returns_highest_score(self, vocab_cache):
        """Test that lookup returns the term with highest relevance score."""
        # Add same term with different scores
        terms_low = [
            VocabTerm(
                term="status",
                canonical_value="Status (describe)",
                object_name="Property__c",
                field_name="Status__c",
                source="describe",
                relevance_score=0.4,
                vocab_type="label",
            ),
        ]
        terms_high = [
            VocabTerm(
                term="status",
                canonical_value="Status (layout)",
                object_name="Property__c",
                field_name="Status__c",
                source="layout",
                relevance_score=1.0,
                vocab_type="label",
            ),
        ]

        vocab_cache.put_terms("label", "Property__c", terms_low)
        vocab_cache.put_terms("label", "Property__c.layout", terms_high)

        # Lookup should return highest score
        result = vocab_cache.lookup("status")
        assert result is not None
        assert result["relevance_score"] == 1.0
        assert result["canonical_value"] == "Status (layout)"

    def test_lookup_not_found(self, vocab_cache):
        """Test lookup for non-existent term."""
        result = vocab_cache.lookup("nonexistent")
        assert result is None

    def test_delete_terms(self, vocab_cache):
        """Test deleting terms."""
        terms = [
            VocabTerm(
                term="test",
                canonical_value="Test",
                object_name="Test__c",
                source="describe",
                relevance_score=0.4,
                vocab_type="label",
            ),
        ]
        vocab_cache.put_terms("label", "Test__c", terms)

        # Verify stored
        assert len(vocab_cache.get_terms("label", "Test__c")) == 1

        # Delete
        result = vocab_cache.delete_terms("label", "Test__c")
        assert result is True

        # Verify deleted
        assert len(vocab_cache.get_terms("label", "Test__c")) == 0


# =============================================================================
# Unit Tests for Vocabulary Builder
# =============================================================================


class TestVocabularyBuilder:
    """Unit tests for vocabulary building from schema."""

    def test_extract_describe_labels(self, vocab_cache):
        """Test extracting field labels from Describe API."""
        schema = {
            "fields": [
                {"name": "Name", "label": "Property Name"},
                {"name": "Status__c", "label": "Status"},
            ]
        }

        terms = vocab_cache._extract_describe_labels(schema, "Property__c")

        # Should have 4 terms (2 labels + 2 API names)
        assert len(terms) == 4
        labels = [t.canonical_value for t in terms if t.term == t.canonical_value.lower()]
        assert "Property Name" in labels
        assert "Status" in labels

    def test_extract_picklist_values(self, vocab_cache):
        """Test extracting picklist values."""
        schema = {
            "fields": [
                {
                    "name": "PropertyClass__c",
                    "label": "Property Class",
                    "type": "picklist",
                    "picklistValues": [
                        {"value": "A", "label": "Class A", "active": True},
                        {"value": "B", "label": "Class B", "active": True},
                        {"value": "C", "label": "Class C", "active": False},  # Inactive
                    ],
                }
            ]
        }

        terms = vocab_cache._extract_picklist_values(schema, "Property__c")

        # Should have 4 terms (2 values + 2 labels for active only)
        assert len(terms) == 4
        values = [t.canonical_value for t in terms]
        assert "A" in values
        assert "B" in values
        assert "C" not in values  # Inactive excluded

    def test_extract_recordtype_names(self, vocab_cache):
        """Test extracting RecordType names."""
        schema = {
            "recordTypeInfos": [
                {"name": "Office", "developerName": "Office", "master": False},
                {"name": "Industrial", "developerName": "Industrial_RT", "master": False},
                {"name": "Master", "developerName": "Master", "master": True},  # Skip
            ]
        }

        terms = vocab_cache._extract_recordtype_names(schema, "Property__c")

        # Should have 3 terms (Office + Industrial name + Industrial dev name)
        assert len(terms) == 3
        names = [t.canonical_value for t in terms]
        assert "Office" in names
        assert "Industrial" in names
        assert "Master" not in names  # Master skipped

    def test_extract_layout_labels(self, vocab_cache):
        """Test extracting page layout field labels."""
        schema = {
            "layouts": [
                {
                    "sections": [
                        {
                            "rows": [
                                {
                                    "layoutItems": [
                                        {"field": "Name", "label": "Property Name"},
                                        {"field": "Status__c", "label": "Current Status"},
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        terms = vocab_cache._extract_layout_labels(schema, "Property__c")

        assert len(terms) == 2
        labels = [t.canonical_value for t in terms]
        assert "Property Name" in labels
        assert "Current Status" in labels

        # Layout terms should have highest relevance
        for term in terms:
            assert term.relevance_score == RELEVANCE_SCORES["layout"]

    def test_build_vocabulary_full(self, vocab_cache):
        """Test full vocabulary building from schema."""
        schema = {
            "label": "Property",
            "fields": [
                {"name": "Name", "label": "Property Name"},
                {
                    "name": "PropertyClass__c",
                    "label": "Property Class",
                    "type": "picklist",
                    "picklistValues": [
                        {"value": "A", "label": "Class A", "active": True},
                    ],
                },
            ],
            "recordTypeInfos": [
                {"name": "Office", "developerName": "Office", "master": False},
            ],
        }

        count = vocab_cache.build_vocabulary(schema, "Property__c")

        # Should have stored multiple terms
        assert count > 0

        # Verify object label stored
        result = vocab_cache.lookup("property")
        assert result is not None


# =============================================================================
# Unit Tests for Relevance Scoring
# =============================================================================


class TestRelevanceScoring:
    """Unit tests for relevance scoring."""

    def test_relevance_scores_hierarchy(self):
        """Test that relevance scores follow expected hierarchy."""
        assert RELEVANCE_SCORES["layout"] > RELEVANCE_SCORES["recordtype"]
        assert RELEVANCE_SCORES["recordtype"] > RELEVANCE_SCORES["picklist"]
        assert RELEVANCE_SCORES["picklist"] > RELEVANCE_SCORES["describe"]

    def test_get_relevance_score(self, vocab_cache):
        """Test getting relevance score by source."""
        assert vocab_cache.get_relevance_score("layout") == 1.0
        assert vocab_cache.get_relevance_score("recordtype") == 0.8
        assert vocab_cache.get_relevance_score("picklist") == 0.6
        assert vocab_cache.get_relevance_score("describe") == 0.4
        assert vocab_cache.get_relevance_score("unknown") == 0.4  # Default

    def test_get_top_terms(self, vocab_cache):
        """Test getting top terms by relevance."""
        # Add terms with different scores
        terms_describe = [
            VocabTerm(term="name", canonical_value="Name", object_name="Property__c",
                     source="describe", relevance_score=0.4, vocab_type="label"),
        ]
        terms_layout = [
            VocabTerm(term="property name", canonical_value="Property Name", object_name="Property__c",
                     source="layout", relevance_score=1.0, vocab_type="label"),
        ]
        terms_picklist = [
            VocabTerm(term="class a", canonical_value="Class A", object_name="Property__c",
                     source="picklist", relevance_score=0.6, vocab_type="picklist"),
        ]

        vocab_cache.put_terms("label", "Property__c", terms_describe)
        vocab_cache.put_terms("label", "Property__c.layout", terms_layout)
        vocab_cache.put_terms("picklist", "Property__c", terms_picklist)

        # Get top terms
        top = vocab_cache.get_top_terms("Property__c", limit=10)

        # Should be sorted by relevance (highest first)
        if len(top) >= 2:
            assert top[0]["relevance_score"] >= top[1]["relevance_score"]

    def test_lookup_with_score_threshold(self, vocab_cache):
        """Test lookup with minimum score threshold."""
        terms = [
            VocabTerm(term="status", canonical_value="Status (low)", object_name="Property__c",
                     source="describe", relevance_score=0.3, vocab_type="label"),
            VocabTerm(term="status", canonical_value="Status (high)", object_name="Property__c",
                     source="layout", relevance_score=0.9, vocab_type="label"),
        ]

        for term in terms:
            vocab_cache.put_terms(term.vocab_type, f"{term.object_name}.{term.source}", [term])

        # Lookup with high threshold
        results = vocab_cache.lookup_with_score("status", min_score=0.5)

        # Should only return high-score term
        assert len(results) == 1
        assert results[0]["relevance_score"] == 0.9


# =============================================================================
# Unit Tests for Convenience Functions
# =============================================================================


class TestConvenienceFunctions:
    """Unit tests for convenience functions."""

    def test_build_vocabulary_from_schema(self, vocab_cache):
        """Test build_vocabulary_from_schema convenience function."""
        schema = {
            "label": "Test",
            "fields": [{"name": "Name", "label": "Name"}],
        }

        with patch("vocab_cache.VocabCache") as MockCache:
            mock_instance = MagicMock()
            mock_instance.build_vocabulary.return_value = 5
            MockCache.return_value = mock_instance

            count = build_vocabulary_from_schema(schema, "Test__c")
            assert count == 5

    def test_lookup_term_function(self, vocab_cache):
        """Test lookup_term convenience function."""
        with patch("vocab_cache.VocabCache") as MockCache:
            mock_instance = MagicMock()
            mock_instance.lookup.return_value = {"term": "test", "canonical_value": "Test"}
            MockCache.return_value = mock_instance

            result = lookup_term("test")
            assert result is not None
            assert result["canonical_value"] == "Test"


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestVocabCacheIntegration:
    """Integration-style tests for vocab cache."""

    def test_full_workflow(self, vocab_cache):
        """Test complete workflow: build, lookup, delete."""
        # Build vocabulary
        schema = {
            "label": "Property",
            "fields": [
                {"name": "Name", "label": "Property Name"},
                {
                    "name": "PropertyClass__c",
                    "label": "Property Class",
                    "type": "picklist",
                    "picklistValues": [
                        {"value": "A", "label": "Class A", "active": True},
                        {"value": "B", "label": "Class B", "active": True},
                    ],
                },
            ],
            "recordTypeInfos": [
                {"name": "Office", "developerName": "Office", "master": False},
                {"name": "Industrial", "developerName": "Industrial", "master": False},
            ],
        }

        count = vocab_cache.build_vocabulary(schema, "Property__c")
        assert count > 0

        # Lookup various terms
        result = vocab_cache.lookup("property")
        assert result is not None

        result = vocab_cache.lookup("class a")
        assert result is not None
        assert result["canonical_value"] == "A"

        result = vocab_cache.lookup("office")
        assert result is not None

        # Get top terms
        top = vocab_cache.get_top_terms("Property__c", limit=5)
        assert len(top) > 0

    def test_case_insensitive_lookup(self, vocab_cache):
        """Test that lookups are case-insensitive."""
        terms = [
            VocabTerm(term="class a", canonical_value="Class A", object_name="Property__c",
                     source="picklist", relevance_score=0.6, vocab_type="picklist"),
        ]
        vocab_cache.put_terms("picklist", "Property__c", terms)

        # All these should find the term
        assert vocab_cache.lookup("class a") is not None
        assert vocab_cache.lookup("Class A") is not None
        assert vocab_cache.lookup("CLASS A") is not None
        assert vocab_cache.lookup("ClAsS a") is not None


# =============================================================================
# Unit Tests for Entity Name Seeding (Task 43.2)
# =============================================================================


class TestEntityNameSeeding:
    """Unit tests for Task 43.2 - Vocab Cache Auto-Seeding from graph nodes."""

    def test_seed_entity_names_basic(self, vocab_cache):
        """Test basic entity name seeding from graph node data."""
        entities = [
            {
                "nodeId": "a0I000000000001",
                "displayName": "123 Main Street",
                "type": "ascendix__Property__c",
            },
            {
                "nodeId": "001000000000001",
                "displayName": "Acme Corp",
                "type": "Account",
            },
            {
                "nodeId": "003000000000001",
                "displayName": "Jane Doe",
                "type": "Contact",
            },
        ]

        count = vocab_cache.seed_entity_names(entities)
        assert count == 3

        # Verify entity names can be looked up
        result = vocab_cache.lookup("123 main street")
        assert result is not None
        assert result["canonical_value"] == "123 Main Street"
        assert result["object_name"] == "ascendix__Property__c"
        assert result["source"] == "graph_node"

        result = vocab_cache.lookup("acme corp")
        assert result is not None
        assert result["object_name"] == "Account"

        result = vocab_cache.lookup("jane doe")
        assert result is not None
        assert result["object_name"] == "Contact"

    def test_seed_entity_names_stores_record_id(self, vocab_cache):
        """Test that record ID is stored in field_name for resolution."""
        entities = [
            {
                "nodeId": "a0I000000000002",
                "displayName": "456 Oak Avenue",
                "type": "ascendix__Property__c",
            },
        ]

        vocab_cache.seed_entity_names(entities)
        result = vocab_cache.lookup("456 oak avenue")

        assert result is not None
        assert result["field_name"] == "a0I000000000002"

    def test_seed_entity_names_skips_unsupported_types(self, vocab_cache):
        """Test that unsupported object types are skipped."""
        entities = [
            {
                "nodeId": "00Q000000000001",
                "displayName": "Test Lead",
                "type": "Lead",  # Not in ENTITY_TYPES_FOR_VOCAB
            },
            {
                "nodeId": "a0I000000000003",
                "displayName": "Valid Property",
                "type": "ascendix__Property__c",
            },
        ]

        count = vocab_cache.seed_entity_names(entities)
        assert count == 1  # Only the Property should be seeded

        # Lead should not be found
        result = vocab_cache.lookup("test lead")
        assert result is None

        # Property should be found
        result = vocab_cache.lookup("valid property")
        assert result is not None

    def test_seed_entity_names_handles_empty_input(self, vocab_cache):
        """Test that empty input returns 0."""
        count = vocab_cache.seed_entity_names([])
        assert count == 0

    def test_seed_entity_names_skips_missing_displayname(self, vocab_cache):
        """Test that entities without displayName are skipped."""
        entities = [
            {
                "nodeId": "a0I000000000004",
                "displayName": "",  # Empty
                "type": "ascendix__Property__c",
            },
            {
                "nodeId": "a0I000000000005",
                # Missing displayName
                "type": "ascendix__Property__c",
            },
        ]

        count = vocab_cache.seed_entity_names(entities)
        assert count == 0

    def test_seed_entity_names_high_relevance_score(self, vocab_cache):
        """Test that seeded entity names have high relevance score (0.95)."""
        entities = [
            {
                "nodeId": "a0I000000000006",
                "displayName": "High Relevance Property",
                "type": "ascendix__Property__c",
            },
        ]

        vocab_cache.seed_entity_names(entities)
        result = vocab_cache.lookup("high relevance property")

        assert result is not None
        assert float(result["relevance_score"]) == 0.95

    def test_seed_entity_names_alternative_key_names(self, vocab_cache):
        """Test that alternative key names (Name, sobject, recordId) are supported."""
        entities = [
            {
                "recordId": "001000000000002",
                "Name": "Alternative Company Name",
                "sobject": "Account",
            },
        ]

        count = vocab_cache.seed_entity_names(entities)
        assert count == 1

        result = vocab_cache.lookup("alternative company name")
        assert result is not None
        assert result["field_name"] == "001000000000002"

    def test_lookup_with_score_includes_entity_names(self, vocab_cache):
        """Test that lookup_with_score returns entity name matches."""
        entities = [
            {
                "nodeId": "a0I000000000007",
                "displayName": "Test Office Building",
                "type": "ascendix__Property__c",
            },
        ]

        vocab_cache.seed_entity_names(entities)
        results = vocab_cache.lookup_with_score("test office building", min_score=0.5)

        assert len(results) > 0
        assert results[0]["canonical_value"] == "Test Office Building"
        assert results[0]["vocab_type"] == "entity_name"
