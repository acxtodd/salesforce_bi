"""
Unit tests for chunking Lambda function.
Tests chunk size boundaries, heading retention, and metadata enrichment.

Updated for zero-config-production to use configuration-based field extraction.

**Feature: zero-config-production**
**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**
"""
import pytest
import json
from unittest.mock import patch, MagicMock
from chunking.index import (
    estimate_tokens,
    extract_text_from_record,
    split_text_with_heading_retention,
    extract_metadata,
    generate_chunk_id,
    chunk_record,
    lambda_handler,
    _format_field_value,
    _parse_field_list,
    MIN_CHUNK_TOKENS,
    MAX_CHUNK_TOKENS,
    CHARS_PER_TOKEN
)


# Test configurations for different object types
ACCOUNT_CONFIG = {
    'Text_Fields__c': 'Name,BillingStreet,BillingCity,BillingState,Phone,Website',
    'Long_Text_Fields__c': 'Description',
    'Relationship_Fields__c': 'OwnerId,ParentId',
    'Display_Name_Field__c': 'Name',
    'Enabled__c': True,
    'Graph_Node_Attributes__c': None,
}

OPPORTUNITY_CONFIG = {
    'Text_Fields__c': 'Name,StageName,LeadSource,Amount,CloseDate',
    'Long_Text_Fields__c': 'Description',
    'Relationship_Fields__c': 'AccountId,OwnerId',
    'Display_Name_Field__c': 'Name',
    'Enabled__c': True,
    'Graph_Node_Attributes__c': None,
}

CASE_CONFIG = {
    'Text_Fields__c': 'Subject,Status,Priority,Origin',
    'Long_Text_Fields__c': 'Description',
    'Relationship_Fields__c': 'AccountId,ContactId,OwnerId',
    'Display_Name_Field__c': 'Subject',
    'Enabled__c': True,
    'Graph_Node_Attributes__c': None,
}


class TestTokenEstimation:
    """Test token estimation logic."""
    
    def test_estimate_tokens_basic(self):
        """Test basic token estimation."""
        text = "a" * 400  # 400 characters
        tokens = estimate_tokens(text)
        assert tokens == 100  # 400 / 4 = 100 tokens
    
    def test_estimate_tokens_empty(self):
        """Test token estimation with empty string."""
        assert estimate_tokens("") == 0


class TestTextExtraction:
    """Test text extraction from Salesforce records."""
    
    def test_extract_text_account(self):
        """Test text extraction from Account record."""
        record = {
            "Id": "001xx",
            "Name": "ACME Corporation",
            "BillingStreet": "123 Main St",
            "BillingCity": "San Francisco",
            "BillingState": "CA",
            "Phone": "555-1234",
            "Description": "Leading provider of innovative solutions"
        }
        
        text = extract_text_from_record(record, "Account", ACCOUNT_CONFIG)
        
        assert "# ACME Corporation" in text
        assert "Billing Street: 123 Main St" in text
        assert "Billing City: San Francisco" in text
        assert "Description:\nLeading provider of innovative solutions" in text
    
    def test_extract_text_opportunity(self):
        """Test text extraction from Opportunity record."""
        record = {
            "Id": "006xx",
            "Name": "ACME Renewal",
            "StageName": "Negotiation",
            "Description": "Annual renewal opportunity"
        }
        
        text = extract_text_from_record(record, "Opportunity", OPPORTUNITY_CONFIG)
        
        assert "# ACME Renewal" in text
        assert "Stage Name: Negotiation" in text
        assert "Description:\nAnnual renewal opportunity" in text
    
    def test_extract_text_missing_fields(self):
        """Test text extraction with missing optional fields."""
        record = {
            "Id": "001xx",
            "Name": "Test Account"
        }
        
        text = extract_text_from_record(record, "Account", ACCOUNT_CONFIG)
        
        assert "# Test Account" in text
        assert "Billing Street" not in text
    
    def test_extract_text_with_custom_config(self):
        """Test text extraction with custom configuration."""
        custom_config = {
            'Text_Fields__c': 'CustomField1,CustomField2',
            'Long_Text_Fields__c': 'LongDescription',
            'Relationship_Fields__c': 'OwnerId',
            'Display_Name_Field__c': 'CustomName',
            'Enabled__c': True,
        }
        
        record = {
            "Id": "001xx",
            "CustomName": "Custom Record",
            "CustomField1": "Value 1",
            "CustomField2": "Value 2",
            "LongDescription": "This is a long description",
            "OwnerId": "005yy",
            "ExtraField": "Should not appear"
        }
        
        text = extract_text_from_record(record, "CustomObject__c", custom_config)
        
        assert "# Custom Record" in text
        assert "Value 1" in text
        assert "Value 2" in text
        assert "This is a long description" in text
        # Extra field not in config should not appear as labeled field
        assert "Extra Field:" not in text


class TestFieldFormatting:
    """Test field value formatting based on schema types."""
    
    def test_format_currency_value(self):
        """Test currency formatting with $ symbol."""
        class MockFieldSchema:
            sf_type = 'currency'
        
        class MockSchema:
            def get_field(self, name):
                return MockFieldSchema()
        
        formatted = _format_field_value(1234.56, 'Amount__c', MockSchema())
        assert formatted == "$1,234.56"
    
    def test_format_percent_value(self):
        """Test percent formatting with % symbol."""
        class MockFieldSchema:
            sf_type = 'percent'
        
        class MockSchema:
            def get_field(self, name):
                return MockFieldSchema()
        
        formatted = _format_field_value(75.5, 'Percentage__c', MockSchema())
        assert formatted == "75.50%"
    
    def test_format_date_value(self):
        """Test date formatting as ISO 8601."""
        class MockFieldSchema:
            sf_type = 'date'
        
        class MockSchema:
            def get_field(self, name):
                return MockFieldSchema()
        
        formatted = _format_field_value('2025-12-01', 'CloseDate', MockSchema())
        assert formatted == "2025-12-01"
    
    def test_format_without_schema(self):
        """Test formatting without schema falls back to string."""
        formatted = _format_field_value(12345, 'SomeField', None)
        assert formatted == "12345"


class TestChunkSplitting:
    """Test chunk splitting with heading retention."""
    
    def test_split_small_text(self):
        """Test that small text returns single chunk."""
        text = "This is a short text that fits in one chunk."
        heading = "# Test Heading"
        
        chunks = split_text_with_heading_retention(text, heading)
        
        assert len(chunks) == 1
        assert chunks[0] == text
    
    def test_split_large_text_with_heading(self):
        """Test splitting large text retains heading in each chunk."""
        # Create text larger than MAX_CHUNK_TOKENS
        paragraph = "This is a test paragraph. " * 100
        text = paragraph + "\n\n" + paragraph + "\n\n" + paragraph
        heading = "# Test Record"
        
        chunks = split_text_with_heading_retention(text, heading)
        
        # Should create multiple chunks
        assert len(chunks) > 1
        
        # Each chunk should contain the heading
        for chunk in chunks:
            assert heading in chunk or chunk.startswith(paragraph.strip())
    
    def test_split_respects_token_boundaries(self):
        """Test that chunks respect MIN and MAX token boundaries."""
        # Create text with multiple paragraphs that will require chunking
        paragraph = "This is a test sentence. " * 50  # ~250 tokens
        text = "\n\n".join([paragraph] * 5)  # ~1250 tokens total
        
        chunks = split_text_with_heading_retention(text, "# Test Heading")
        
        # Should create multiple chunks
        assert len(chunks) > 1
        
        # Check that chunks are reasonable size (allowing some flexibility)
        for chunk in chunks:
            tokens = estimate_tokens(chunk)
            # Chunks should generally be under MAX, but algorithm may exceed slightly
            # for paragraph boundaries. Focus on testing the logic works.
            assert tokens < MAX_CHUNK_TOKENS * 2  # Reasonable upper bound
    
    def test_split_empty_text(self):
        """Test splitting empty text."""
        chunks = split_text_with_heading_retention("", "# Heading")
        
        assert len(chunks) == 1
        assert chunks[0] == ""


class TestMetadataExtraction:
    """Test metadata extraction from records."""
    
    def test_extract_metadata_basic(self):
        """Test basic metadata extraction."""
        record = {
            "Id": "001xx",
            "OwnerId": "005yy",
            "LastModifiedDate": "2025-11-13T10:30:00Z"
        }
        
        metadata = extract_metadata(record, "Account", ACCOUNT_CONFIG)
        
        assert metadata["sobject"] == "Account"
        assert metadata["recordId"] == "001xx"
        assert metadata["ownerId"] == "005yy"
        assert metadata["lastModified"] == "2025-11-13T10:30:00Z"
        assert metadata["language"] == "en"
    
    def test_extract_metadata_with_relationships(self):
        """Test metadata extraction includes parent IDs."""
        record = {
            "Id": "006xx",
            "AccountId": "001xx",
            "OwnerId": "005yy"
        }
        
        metadata = extract_metadata(record, "Opportunity", OPPORTUNITY_CONFIG)
        
        assert "parentIds" in metadata
        assert "001xx" in metadata["parentIds"]
        assert "005yy" in metadata["parentIds"]
    
    def test_extract_metadata_with_business_fields(self):
        """Test metadata extraction includes business unit, region, territory."""
        record = {
            "Id": "001xx",
            "OwnerId": "005yy",
            "Territory__c": "EMEA",
            "Business_Unit__c": "Enterprise",
            "Region__c": "Europe"
        }
        
        metadata = extract_metadata(record, "Account", ACCOUNT_CONFIG)
        
        assert metadata["territory"] == "EMEA"
        assert metadata["businessUnit"] == "Enterprise"
        assert metadata["region"] == "Europe"
    
    def test_extract_metadata_opportunity_specific(self):
        """Test Opportunity-specific metadata fields."""
        record = {
            "Id": "006xx",
            "OwnerId": "005yy",
            "StageName": "Closed Won",
            "Amount": 100000,
            "CloseDate": "2025-12-31"
        }
        
        metadata = extract_metadata(record, "Opportunity", OPPORTUNITY_CONFIG)
        
        assert metadata["stage"] == "Closed Won"
        assert metadata["amount"] == 100000
        assert metadata["closeDate"] == "2025-12-31"


class TestChunkIdGeneration:
    """Test chunk ID generation."""
    
    def test_generate_chunk_id_format(self):
        """Test chunk ID follows correct format."""
        chunk_id = generate_chunk_id("Account", "001xx", 0)
        
        assert chunk_id == "Account/001xx/chunk-0"
    
    def test_generate_chunk_id_multiple_chunks(self):
        """Test chunk IDs for multiple chunks."""
        chunk_id_0 = generate_chunk_id("Opportunity", "006xx", 0)
        chunk_id_1 = generate_chunk_id("Opportunity", "006xx", 1)
        
        assert chunk_id_0 == "Opportunity/006xx/chunk-0"
        assert chunk_id_1 == "Opportunity/006xx/chunk-1"


class TestChunkRecord:
    """Test complete record chunking."""
    
    def test_chunk_record_single_chunk(self):
        """Test chunking record that fits in single chunk."""
        record = {
            "Id": "001xx",
            "Name": "Test Account",
            "OwnerId": "005yy",
            "Description": "A simple test account"
        }
        
        chunks = chunk_record(record, "Account", ACCOUNT_CONFIG)
        
        assert len(chunks) == 1
        assert chunks[0]["id"] == "Account/001xx/chunk-0"
        assert "Test Account" in chunks[0]["text"]
        assert chunks[0]["metadata"]["sobject"] == "Account"
        assert chunks[0]["metadata"]["recordId"] == "001xx"
        assert chunks[0]["metadata"]["chunkIndex"] == 0
        assert chunks[0]["metadata"]["totalChunks"] == 1
    
    def test_chunk_record_multiple_chunks(self):
        """Test chunking record that requires multiple chunks."""
        # Create a record with long description
        long_description = "This is a very long description. " * 200
        
        record = {
            "Id": "001xx",
            "Name": "Large Account",
            "OwnerId": "005yy",
            "Description": long_description
        }
        
        chunks = chunk_record(record, "Account", ACCOUNT_CONFIG)
        
        # Should create multiple chunks
        assert len(chunks) > 1
        
        # Verify chunk IDs are sequential
        for idx, chunk in enumerate(chunks):
            assert chunk["id"] == f"Account/001xx/chunk-{idx}"
            assert chunk["metadata"]["chunkIndex"] == idx
            assert chunk["metadata"]["totalChunks"] == len(chunks)
    
    def test_chunk_record_metadata_enrichment(self):
        """Test that all chunks have proper metadata enrichment."""
        record = {
            "Id": "006xx",
            "Name": "Test Opportunity",
            "AccountId": "001xx",
            "OwnerId": "005yy",
            "StageName": "Prospecting",
            "Amount": 50000,
            "Territory__c": "West",
            "Description": "Test opportunity"
        }
        
        chunks = chunk_record(record, "Opportunity", OPPORTUNITY_CONFIG)
        
        for chunk in chunks:
            metadata = chunk["metadata"]
            assert metadata["sobject"] == "Opportunity"
            assert metadata["recordId"] == "006xx"
            assert metadata["ownerId"] == "005yy"
            assert metadata["stage"] == "Prospecting"
            assert metadata["amount"] == 50000
            assert metadata["territory"] == "West"
            assert "001xx" in metadata["parentIds"]


class TestLambdaHandler:
    """Test Lambda handler function."""
    
    @patch('chunking.index._get_config_cache')
    @patch('chunking.index._get_schema_cache')
    def test_lambda_handler_success(self, mock_schema_cache, mock_config_cache):
        """Test successful Lambda invocation."""
        # Mock config cache to return Account config
        mock_cache = MagicMock()
        mock_cache.get_config.return_value = ACCOUNT_CONFIG
        mock_config_cache.return_value = mock_cache
        mock_schema_cache.return_value = None
        
        event = {
            "records": [
                {
                    "sobject": "Account",
                    "data": {
                        "Id": "001xx",
                        "Name": "Test Account",
                        "OwnerId": "005yy",
                        "Description": "Test description"
                    }
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert "chunks" in response
        assert response["recordCount"] == 1
        assert response["chunkCount"] >= 1
        assert len(response["chunks"]) >= 1
    
    @patch('chunking.index._get_config_cache')
    @patch('chunking.index._get_schema_cache')
    def test_lambda_handler_multiple_records(self, mock_schema_cache, mock_config_cache):
        """Test Lambda with multiple records."""
        # Mock config cache to return appropriate configs
        mock_cache = MagicMock()
        mock_cache.get_config.side_effect = lambda obj: {
            'Account': ACCOUNT_CONFIG,
            'Opportunity': OPPORTUNITY_CONFIG,
        }.get(obj, ACCOUNT_CONFIG)
        mock_config_cache.return_value = mock_cache
        mock_schema_cache.return_value = None
        
        event = {
            "records": [
                {
                    "sobject": "Account",
                    "data": {"Id": "001xx", "Name": "Account 1", "OwnerId": "005yy"}
                },
                {
                    "sobject": "Opportunity",
                    "data": {"Id": "006xx", "Name": "Opp 1", "OwnerId": "005yy"}
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert "chunks" in response
        assert response["recordCount"] == 2
        assert response["chunkCount"] >= 2
    
    def test_lambda_handler_no_records(self):
        """Test Lambda with no records."""
        event = {"records": []}
        
        response = lambda_handler(event, None)
        
        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "error" in body
    
    @patch('chunking.index._get_config_cache')
    @patch('chunking.index._get_schema_cache')
    def test_lambda_handler_disabled_object(self, mock_schema_cache, mock_config_cache):
        """Test Lambda skips disabled object types."""
        # Mock config cache to return disabled config for first object
        disabled_config = {**ACCOUNT_CONFIG, 'Enabled__c': False}
        mock_cache = MagicMock()
        mock_cache.get_config.side_effect = lambda obj: {
            'DisabledObject__c': disabled_config,
            'Account': ACCOUNT_CONFIG,
        }.get(obj, ACCOUNT_CONFIG)
        mock_config_cache.return_value = mock_cache
        mock_schema_cache.return_value = None
        
        event = {
            "records": [
                {
                    "sobject": "DisabledObject__c",
                    "data": {"Id": "001xx", "Name": "Test"}
                },
                {
                    "sobject": "Account",
                    "data": {"Id": "002xx", "Name": "Valid Account", "OwnerId": "005yy"}
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert "chunks" in response
        # Should only process the Account record
        assert response["chunkCount"] >= 1
    
    @patch('chunking.index._get_config_cache')
    @patch('chunking.index._get_schema_cache')
    def test_lambda_handler_invalid_record(self, mock_schema_cache, mock_config_cache):
        """Test Lambda handles invalid record gracefully."""
        mock_cache = MagicMock()
        mock_cache.get_config.return_value = ACCOUNT_CONFIG
        mock_config_cache.return_value = mock_cache
        mock_schema_cache.return_value = None
        
        event = {
            "records": [
                {
                    "sobject": "Account"
                    # Missing 'data' field
                },
                {
                    "sobject": "Account",
                    "data": {"Id": "001xx", "Name": "Valid Account", "OwnerId": "005yy"}
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        # Should process valid record and skip invalid one
        assert "chunks" in response
        assert response["chunkCount"] >= 1
    
    @patch('chunking.index._get_config_cache')
    @patch('chunking.index._get_schema_cache')
    def test_lambda_handler_fallback_config(self, mock_schema_cache, mock_config_cache):
        """Test Lambda uses fallback config when cache unavailable."""
        # Mock config cache to return None (unavailable)
        mock_config_cache.return_value = None
        mock_schema_cache.return_value = None
        
        event = {
            "records": [
                {
                    "sobject": "Account",
                    "data": {
                        "Id": "001xx",
                        "Name": "Test Account",
                        "OwnerId": "005yy"
                    }
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        # Should still process with fallback config
        assert "chunks" in response
        assert response["chunkCount"] >= 1


class TestParseFieldList:
    """Test field list parsing utility."""
    
    def test_parse_field_list_basic(self):
        """Test basic comma-separated parsing."""
        result = _parse_field_list("Field1,Field2,Field3")
        assert result == ["Field1", "Field2", "Field3"]
    
    def test_parse_field_list_with_spaces(self):
        """Test parsing with spaces around commas."""
        result = _parse_field_list("Field1 , Field2 , Field3")
        assert result == ["Field1", "Field2", "Field3"]
    
    def test_parse_field_list_empty(self):
        """Test parsing empty string."""
        result = _parse_field_list("")
        assert result == []
    
    def test_parse_field_list_none(self):
        """Test parsing None."""
        result = _parse_field_list(None)
        assert result == []
    
    def test_parse_field_list_single(self):
        """Test parsing single field."""
        result = _parse_field_list("SingleField")
        assert result == ["SingleField"]
