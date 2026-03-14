"""
Validate Lambda Function
Validates Salesforce records before processing.
"""
import json
from typing import Dict, Any, List

REQUIRED_FIELDS = ["Id", "LastModifiedDate"]

POC_OBJECTS = [
    # Standard objects
    "Account", "Opportunity", "Case", "Note",
    # Legacy custom objects
    "Property__c", "Lease__c", "Contract__c",
    # Ascendix CRE objects
    "ascendix__Property__c", "ascendix__Availability__c",
    "ascendix__Lease__c", "ascendix__Sale__c", "ascendix__Deal__c"
]


def validate_record(record: Dict[str, Any], sobject: str) -> tuple[bool, str]:
    """
    Validate a single record.
    
    Returns:
        (is_valid, error_message)
    """
    # Check sobject is supported
    if sobject not in POC_OBJECTS:
        return False, f"Unsupported object type: {sobject}"
    
    # Check required fields
    for field in REQUIRED_FIELDS:
        if field not in record or not record[field]:
            return False, f"Missing required field: {field}"
    
    return True, ""


def lambda_handler(event, context):
    """
    Validate records from CDC or batch export.
    
    Expected event format:
    {
        "records": [
            {
                "sobject": "Account",
                "data": { ... Salesforce record fields ... }
            }
        ]
    }
    
    Returns:
    {
        "validRecords": [...],
        "invalidRecords": [...],
        "validCount": int,
        "invalidCount": int
    }
    """
    try:
        records = event.get("records", [])
        
        valid_records = []
        invalid_records = []
        
        for record_wrapper in records:
            sobject = record_wrapper.get("sobject")
            record_data = record_wrapper.get("data")
            
            if not sobject or not record_data:
                invalid_records.append({
                    "record": record_wrapper,
                    "error": "Missing sobject or data"
                })
                continue
            
            is_valid, error = validate_record(record_data, sobject)
            
            if is_valid:
                valid_records.append(record_wrapper)
            else:
                invalid_records.append({
                    "record": record_wrapper,
                    "error": error
                })
        
        print(f"Validated {len(records)} records: {len(valid_records)} valid, {len(invalid_records)} invalid")
        
        return {
            "validRecords": valid_records,
            "invalidRecords": invalid_records,
            "validCount": len(valid_records),
            "invalidCount": len(invalid_records)
        }
    
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        raise
