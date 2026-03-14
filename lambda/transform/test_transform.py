import pytest
from transform.index import lambda_handler

class TestTransformLambda:
    
    def test_transform_success(self):
        """Test successful transformation of records.
        
        Note: The transform function preserves nested relationship objects
        for downstream processing by ChunkingLambda.
        """
        event = {
            "validRecords": [
                {
                    "sobject": "Opportunity",
                    "data": {
                        "Id": "006xx001",
                        "Name": "Big Deal",
                        "Amount": 100000,
                        "Account": {
                            "attributes": {"type": "Account", "url": "..."},
                            "Name": "ACME Corp",
                            "Industry": "Tech"
                        },
                        "Owner": {
                            "attributes": {"type": "User", "url": "..."},
                            "Name": "John Doe"
                        },
                        "Description": None
                    }
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert "records" in response
        assert response["recordCount"] == 1
        
        transformed_record = response["records"][0]
        assert transformed_record["sobject"] == "Opportunity"
        
        data = transformed_record["data"]
        # Direct fields
        assert data["Id"] == "006xx001"
        assert data["Name"] == "Big Deal"
        assert data["Amount"] == 100000
        
        # Nested relationship objects are preserved (not flattened)
        # ChunkingLambda expects nested objects for proper processing
        assert data["Account"]["Name"] == "ACME Corp"
        assert data["Account"]["Industry"] == "Tech"
        assert data["Owner"]["Name"] == "John Doe"
        
        # Null fields should be skipped
        assert "Description" not in data

    def test_transform_empty_payload(self):
        """Test with empty records list."""
        event = {"validRecords": []}
        response = lambda_handler(event, None)
        
        assert response["recordCount"] == 0
        assert response["records"] == []

    def test_transform_error_handling(self):
        """Test error handling with invalid input."""
        with pytest.raises(Exception):
            lambda_handler("invalid", None)
