import pytest
from enrich.index import lambda_handler

class TestEnrichLambda:
    
    def test_enrich_success(self):
        """Test successful enrichment of chunks with full metadata."""
        event = {
            "chunks": [
                {
                    "id": "Account/001xx/chunk-0",
                    "text": "Test text",
                    "metadata": {
                        "ownerId": "005xx001",
                        "territory": "North",
                        "businessUnit": "Sales",
                        "region": "NA",
                        "lastModified": "2023-01-01T00:00:00Z"
                    }
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert "enrichedChunks" in response
        assert response["chunkCount"] == 1
        
        enriched_chunk = response["enrichedChunks"][0]
        metadata = enriched_chunk["metadata"]
        
        # Verify sharing buckets
        assert "owner:005xx001" in metadata["sharingBuckets"]
        assert "territory:North" in metadata["sharingBuckets"]
        assert "bu:Sales" in metadata["sharingBuckets"]
        assert "region:NA" in metadata["sharingBuckets"]
        
        # Verify other fields
        assert "profile:Standard" in metadata["flsProfileTags"]
        assert metadata["hasPII"] is False
        assert metadata["effectiveDate"] == "2023-01-01T00:00:00Z"

    def test_enrich_minimal_metadata(self):
        """Test enrichment with minimal metadata."""
        event = {
            "chunks": [
                {
                    "id": "Account/001xx/chunk-0",
                    "text": "Test text",
                    "metadata": {}
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert response["chunkCount"] == 1
        metadata = response["enrichedChunks"][0]["metadata"]
        
        assert metadata["sharingBuckets"] == []
        assert "profile:Standard" in metadata["flsProfileTags"]
        assert metadata["hasPII"] is False

    def test_enrich_empty_chunks(self):
        """Test with empty chunks list."""
        event = {"chunks": []}
        response = lambda_handler(event, None)
        
        assert response["chunkCount"] == 0
        # When no chunks, returns S3 format with empty key
        assert response["enrichedChunksS3Key"] == ""

    def test_enrich_error_handling(self):
        """Test error handling with invalid input."""
        # Pass invalid input (not a dict) to trigger exception access
        with pytest.raises(Exception):
            lambda_handler("invalid", None)
