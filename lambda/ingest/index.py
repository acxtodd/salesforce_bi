"""
Ingest Lambda Function
Handles batch ingestion requests from Salesforce Apex export.
"""
import json
import boto3
import os
from typing import Dict, Any, List
from datetime import datetime

# Initialize AWS clients
sfn_client = boto3.client('stepfunctions')

def validate_request(event: Dict[str, Any]) -> tuple[bool, str]:
    """
    Validate ingest request.
    
    Returns:
        (is_valid, error_message)
    """
    required_fields = ['sobject', 'records']
    
    for field in required_fields:
        if field not in event:
            return False, f"Missing required field: {field}"
    
    if not isinstance(event['records'], list):
        return False, "Field 'records' must be an array"
    
    if len(event['records']) == 0:
        return False, "Field 'records' cannot be empty"
    
    if len(event['records']) > 1000:
        return False, "Maximum 1000 records per request"
    
    return True, ""


def lambda_handler(event, context):
    """
    Handle batch ingest request from Salesforce.
    
    Expected event format:
    {
        "sobject": "Account",
        "operation": "upsert",
        "records": [
            {
                "Id": "001xx",
                "Name": "ACME",
                ...
            }
        ],
        "source": "batch_export",
        "timestamp": "2025-11-13T14:30:00Z"
    }
    
    Returns:
    {
        "statusCode": 202,
        "body": {
            "accepted": true,
            "jobId": "execution-arn",
            "recordCount": 100
        }
    }
    """
    try:
        # Parse request body if it's a string (from API Gateway)
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event
        
        # Validate request
        is_valid, error_message = validate_request(body)
        if not is_valid:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'error': 'validation_error',
                    'message': error_message
                })
            }
        
        sobject = body['sobject']
        records = body['records']
        operation = body.get('operation', 'upsert')
        source = body.get('source', 'batch_export')
        
        print(f"Received batch ingest request: {len(records)} {sobject} records from {source}")
        
        # Transform records to ingestion pipeline format
        pipeline_records = []
        for record in records:
            pipeline_records.append({
                'sobject': sobject,
                'data': record
            })
        
        # Prepare input for Step Functions
        sfn_input = {
            'records': pipeline_records,
            'source': source,
            'operation': operation,
            'timestamp': body.get('timestamp', datetime.utcnow().isoformat() + 'Z')
        }
        
        # Start Step Functions execution
        STATE_MACHINE_ARN = os.environ.get('STATE_MACHINE_ARN')
        if not STATE_MACHINE_ARN:
            raise ValueError("STATE_MACHINE_ARN environment variable not set")
        
        response = sfn_client.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            input=json.dumps(sfn_input)
        )
        
        execution_arn = response['executionArn']
        
        print(f"Started Step Functions execution: {execution_arn}")
        
        return {
            'statusCode': 202,
            'headers': {
                'Content-Type': 'application/json'
            },
            'body': json.dumps({
                'accepted': True,
                'jobId': execution_arn,
                'recordCount': len(records),
                'sobject': sobject
            })
        }
    
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in request body: {str(e)}")
        return {
            'statusCode': 400,
            'body': json.dumps({
                'error': 'invalid_json',
                'message': 'Request body must be valid JSON'
            })
        }
    
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'internal_error',
                'message': 'An error occurred processing the request'
            })
        }
