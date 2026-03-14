"""
CDC Processor Lambda Function
Processes CDC events from S3 and prepares them for the ingestion pipeline.
"""
import json
import boto3
import os
from typing import Dict, Any, List
from datetime import datetime, timezone

# Initialize AWS clients
s3_client = boto3.client('s3')
cloudwatch_client = boto3.client('cloudwatch')

# POC object mapping
CDC_OBJECT_MAPPING = {
    'AccountChangeEvent': 'Account',
    'OpportunityChangeEvent': 'Opportunity',
    'CaseChangeEvent': 'Case',
    'NoteChangeEvent': 'Note',
    'Property__ChangeEvent': 'Property__c',
    'Lease__ChangeEvent': 'Lease__c',
    'Contract__ChangeEvent': 'Contract__c',
}


def extract_sobject_from_key(s3_key: str) -> str:
    """
    Extract sobject name from S3 key.
    
    Example: cdc/Account/2025/11/13/14/event-001.json -> Account
    """
    parts = s3_key.split('/')
    if len(parts) >= 2 and parts[0] == 'cdc':
        return parts[1]
    raise ValueError(f"Invalid S3 key format: {s3_key}")


def process_cdc_event(cdc_event: Dict[str, Any], sobject: str) -> Dict[str, Any]:
    """
    Process a single CDC event and extract record data.
    
    Args:
        cdc_event: Raw CDC event from Salesforce
        sobject: Salesforce object type (e.g., Account, Opportunity)
    
    Returns:
        Processed record in ingestion pipeline format
    """
    # Extract change event header
    header = cdc_event.get('ChangeEventHeader', {})
    change_type = header.get('changeType', 'UPDATE')
    record_ids = header.get('recordIds', [])
    commit_timestamp = header.get('commitTimestamp')
    
    # Skip DELETE events (we don't index deleted records)
    if change_type == 'DELETE':
        print(f"Skipping DELETE event for {sobject} records: {record_ids}")
        return None
    
    # Extract record data (all fields except ChangeEventHeader)
    record_data = {k: v for k, v in cdc_event.items() if k != 'ChangeEventHeader'}
    
    # Ensure required fields
    if 'Id' not in record_data:
        if record_ids:
            record_data['Id'] = record_ids[0]
        else:
            raise ValueError("CDC event missing record ID")
    
    # Add CDC metadata
    record_data['_cdc_change_type'] = change_type
    record_data['_cdc_commit_timestamp'] = commit_timestamp
    
    return {
        'sobject': sobject,
        'data': record_data
    }


def emit_freshness_metrics(sobject: str, commit_timestamp: int, event_time: str):
    """
    Emit freshness lag metrics to CloudWatch.
    
    Args:
        sobject: Salesforce object type
        commit_timestamp: CDC commit timestamp (milliseconds since epoch)
        event_time: EventBridge event time (ISO 8601 string)
    """
    try:
        # Calculate lag from Salesforce commit to S3 arrival
        commit_time = datetime.fromtimestamp(commit_timestamp / 1000.0, tz=timezone.utc)
        s3_arrival_time = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
        
        cdc_to_s3_lag_ms = int((s3_arrival_time - commit_time).total_seconds() * 1000)
        
        # Calculate lag from S3 arrival to processing start
        processing_start_time = datetime.now(timezone.utc)
        s3_to_processing_lag_ms = int((processing_start_time - s3_arrival_time).total_seconds() * 1000)
        
        # Total lag from commit to processing
        total_lag_ms = cdc_to_s3_lag_ms + s3_to_processing_lag_ms
        
        # Total lag from commit to processing
        total_lag_ms = cdc_to_s3_lag_ms + s3_to_processing_lag_ms
        

        
        # Emit metrics to CloudWatch
        cloudwatch_client.put_metric_data(
            Namespace='SalesforceAISearch/Ingestion',
            MetricData=[
                {
                    'MetricName': 'CDCToS3Lag',
                    'Value': cdc_to_s3_lag_ms,
                    'Unit': 'Milliseconds',
                    'Dimensions': [
                        {'Name': 'SObject', 'Value': sobject},
                        {'Name': 'Stage', 'Value': 'CDCToS3'}
                    ]
                },
                {
                    'MetricName': 'S3ToProcessingLag',
                    'Value': s3_to_processing_lag_ms,
                    'Unit': 'Milliseconds',
                    'Dimensions': [
                        {'Name': 'SObject', 'Value': sobject},
                        {'Name': 'Stage', 'Value': 'S3ToProcessing'}
                    ]
                },
                {
                    'MetricName': 'TotalIngestLag',
                    'Value': total_lag_ms,
                    'Unit': 'Milliseconds',
                    'Dimensions': [
                        {'Name': 'SObject', 'Value': sobject},
                        {'Name': 'Stage', 'Value': 'Total'}
                    ]
                }
            ]
        )
        
        print(f"Freshness metrics: CDC->S3={cdc_to_s3_lag_ms}ms, S3->Processing={s3_to_processing_lag_ms}ms, Total={total_lag_ms}ms")
        
    except Exception as e:
        print(f"Error emitting freshness metrics: {str(e)}")
        # Don't fail the function if metrics fail


def lambda_handler(event, context):
    """
    Process CDC event from S3 and prepare for ingestion pipeline.
    
    Expected event format (from EventBridge):
    {
        "bucket": "salesforce-ai-search-cdc-...",
        "key": "cdc/Account/2025/11/13/14/event-001.json",
        "eventTime": "2025-11-13T14:30:00Z",
        "eventSource": "cdc"
    }
    
    OR (from Ingest Lambda / Batch Export):
    {
        "records": [...],
        "source": "batch_export",
        ...
    }
    
    Returns:
    {
        "records": [
            {
                "sobject": "Account",
                "data": { ... Salesforce record fields ... }
            }
        ]
    }
    """
    try:
        # PASSTHROUGH MODE: If records are already provided (e.g. from batch export)
        if 'records' in event:
            print(f"Received direct records payload (Source: {event.get('source', 'unknown')})")
            return {
                'records': event['records'],
                'validCount': len(event['records'])
            }

        bucket = event.get('bucket')
        key = event.get('key')
        event_time = event.get('eventTime')
        
        if not bucket or not key:
            raise ValueError("Missing bucket or key in event")
        
        print(f"Processing CDC event from s3://{bucket}/{key}")
        
        # Extract sobject from S3 key
        sobject = extract_sobject_from_key(key)
        print(f"Detected sobject: {sobject}")
        
        # Download CDC event from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        cdc_event = json.loads(response['Body'].read().decode('utf-8'))
        
        # Process CDC event
        processed_record = process_cdc_event(cdc_event, sobject)
        
        if processed_record is None:
            print("No records to process (DELETE event)")
            return {
                'records': [],
                'validCount': 0
            }
        
        # Emit freshness lag metrics
        if event_time and '_cdc_commit_timestamp' in processed_record['data']:
            emit_freshness_metrics(
                sobject,
                processed_record['data']['_cdc_commit_timestamp'],
                event_time
            )
        
        print(f"Processed 1 CDC event for {sobject}")
        
        return {
            'records': [processed_record]
        }
    
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        raise
