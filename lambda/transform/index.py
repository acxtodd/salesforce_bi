"""
Transform Lambda Function
Transforms and flattens Salesforce records for chunking.
"""
import json
from typing import Dict, Any


def flatten_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process Salesforce record structure.
    Preserves nested relationship objects for downstream processing.
    """
    processed = {}
    
    for key, value in record.items():
        if value is None:
            continue
        
        # Pass through everything as-is, including nested dicts
        # The ChunkingLambda expects nested relationship objects
        processed[key] = value
    
    return processed


def lambda_handler(event, context):
    """
    Transform records for chunking.
    
    Expected event format:
    {
        "validRecords": [
            {
                "sobject": "Account",
                "data": { ... Salesforce record fields ... }
            }
        ]
    }
    
    Returns:
    {
        "transformedRecords": [...],
        "recordCount": int
    }
    """
    try:
        records = event.get("validRecords", [])
        
        transformed_records = []
        
        for record_wrapper in records:
            sobject = record_wrapper.get("sobject")
            record_data = record_wrapper.get("data")
            
            # Flatten the record
            flattened_data = flatten_record(record_data)
            
            transformed_records.append({
                "sobject": sobject,
                "data": flattened_data
            })
        
        print(f"Transformed {len(records)} records")
        
        return {
            "records": transformed_records,
            "recordCount": len(transformed_records)
        }
    
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        raise
