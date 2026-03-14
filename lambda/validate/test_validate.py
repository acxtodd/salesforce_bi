import pytest
from validate.index import lambda_handler

class TestValidateLambda:
    
    def test_validate_valid_record(self):
        """Test validation of a valid record."""
        event = {
            "records": [
                {
                    "sobject": "Account",
                    "data": {
                        "Id": "001xx001",
                        "LastModifiedDate": "2023-01-01T00:00:00Z",
                        "Name": "Valid Account"
                    }
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert response["validCount"] == 1
        assert response["invalidCount"] == 0
        assert len(response["validRecords"]) == 1
        assert response["validRecords"][0]["sobject"] == "Account"

    def test_validate_missing_required_fields(self):
        """Test validation fails when required fields are missing."""
        event = {
            "records": [
                {
                    "sobject": "Account",
                    "data": {
                        "Name": "Invalid Account"
                        # Missing Id and LastModifiedDate
                    }
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert response["validCount"] == 0
        assert response["invalidCount"] == 1
        assert "Missing required field" in response["invalidRecords"][0]["error"]

    def test_validate_unsupported_object(self):
        """Test validation fails for unsupported object types."""
        event = {
            "records": [
                {
                    "sobject": "UnknownObject",
                    "data": {
                        "Id": "001xx001",
                        "LastModifiedDate": "2023-01-01T00:00:00Z"
                    }
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert response["validCount"] == 0
        assert response["invalidCount"] == 1
        assert "Unsupported object type" in response["invalidRecords"][0]["error"]

    def test_validate_malformed_input(self):
        """Test handling of malformed input records."""
        event = {
            "records": [
                {
                    # Missing sobject and data
                    "foo": "bar"
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert response["validCount"] == 0
        assert response["invalidCount"] == 1
        assert "Missing sobject or data" in response["invalidRecords"][0]["error"]

    def test_validate_mixed_batch(self):
        """Test batch with mixed valid and invalid records."""
        event = {
            "records": [
                {
                    "sobject": "Account",
                    "data": {"Id": "001xx1", "LastModifiedDate": "2023-01-01"}
                },
                {
                    "sobject": "Account",
                    "data": {"Name": "Invalid"}
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert response["validCount"] == 1
        assert response["invalidCount"] == 1
