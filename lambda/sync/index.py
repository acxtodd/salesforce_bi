"""
Sync Lambda Function
Writes chunks to S3 as individual text files with metadata for Bedrock Knowledge Base ingestion.
Reads embedded chunks from S3 staging area.
"""
import json
import boto3
import os
from datetime import datetime
from typing import Dict, Any, List

# Initialize AWS clients
s3_client = boto3.client('s3')
cloudwatch_client = boto3.client('cloudwatch')
bedrock_agent_client = boto3.client('bedrock-agent')

# Environment variables
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID')
DATA_SOURCE_ID = os.environ.get('DATA_SOURCE_ID')


def trigger_ingestion_job(knowledge_base_id: str, data_source_id: str):
    """Trigger a Bedrock Knowledge Base ingestion job."""
    try:
        if not knowledge_base_id or not data_source_id:
            print("Skipping ingestion job: KNOWLEDGE_BASE_ID or DATA_SOURCE_ID not set")
            return

        response = bedrock_agent_client.start_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
            description=f"SyncLambda trigger at {datetime.utcnow().isoformat()}"
        )
        
        ingestion_job = response.get('ingestionJob', {})
        job_id = ingestion_job.get('ingestionJobId')
        status = ingestion_job.get('status')
        print(f"Started ingestion job: {job_id} (Status: {status})")
        
    except Exception as e:
        print(f"Error triggering ingestion job: {str(e)}")


def read_chunks_from_s3(bucket: str, key: str) -> List[Dict[str, Any]]:
    """Read embedded chunks from S3 staging area."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response['Body'].read().decode('utf-8')
    return json.loads(content)


def sanitize_metadata_for_bedrock(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize metadata for Bedrock KB requirements.
    Bedrock supports: strings, numbers, booleans, and string lists.
    """
    sanitized = {}
    
    for key, value in metadata.items():
        if value is None:
            continue
        elif isinstance(value, bool):
            sanitized[key] = value
        elif isinstance(value, (int, float)):
            sanitized[key] = value
        elif isinstance(value, str):
            if value:  # Skip empty strings
                sanitized[key] = value
        elif isinstance(value, list):
            # Convert list to string list, filter empty values
            str_list = [str(v) for v in value if v]
            if str_list:
                sanitized[key] = str_list
        else:
            # Convert other types to string
            sanitized[key] = str(value)
    
    return sanitized


def write_chunk_to_s3(chunk: Dict[str, Any], bucket: str) -> str:
    """Write a single chunk to S3 as .txt and .metadata.json"""
    chunk_id = chunk["id"]
    s3_base_key = f"chunks/{chunk_id}"
    s3_txt_key = f"{s3_base_key}.txt"
    s3_meta_key = f"{s3_base_key}.txt.metadata.json"
    
    # Write text content
    text_content = chunk["text"]
    s3_client.put_object(
        Bucket=bucket,
        Key=s3_txt_key,
        Body=text_content.encode('utf-8'),
        ContentType='text/plain'
    )
    
    # Write metadata - sanitize for Bedrock KB requirements
    metadata = chunk.get("metadata", {})
    sanitized_metadata = sanitize_metadata_for_bedrock(metadata)
    bedrock_metadata = {"metadataAttributes": sanitized_metadata}
    
    s3_client.put_object(
        Bucket=bucket,
        Key=s3_meta_key,
        Body=json.dumps(bedrock_metadata).encode('utf-8'),
        ContentType='application/json'
    )
    
    return s3_base_key


def emit_pipeline_metrics(chunks: List[Dict[str, Any]]):
    """Emit pipeline completion metrics to CloudWatch."""
    try:
        sobject_counts = {}
        for chunk in chunks:
            sobject = chunk.get('metadata', {}).get('sobject', 'Unknown')
            sobject_counts[sobject] = sobject_counts.get(sobject, 0) + 1
        
        for chunk in chunks:
            metadata = chunk.get('metadata', {})
            cdc_commit_timestamp = metadata.get('_cdc_commit_timestamp')
            
            if cdc_commit_timestamp:
                commit_time = datetime.fromtimestamp(cdc_commit_timestamp / 1000.0)
                sync_time = datetime.utcnow()
                end_to_end_lag_ms = int((sync_time - commit_time).total_seconds() * 1000)
                sobject = metadata.get('sobject', 'Unknown')
                
                cloudwatch_client.put_metric_data(
                    Namespace='SalesforceAISearch/Ingestion',
                    MetricData=[{
                        'MetricName': 'EndToEndLag',
                        'Value': end_to_end_lag_ms,
                        'Unit': 'Milliseconds',
                        'Dimensions': [{'Name': 'SObject', 'Value': sobject}, {'Name': 'Stage', 'Value': 'EndToEnd'}]
                    }]
                )
        
        metric_data = []
        for sobject, count in sobject_counts.items():
            metric_data.append({
                'MetricName': 'ChunksSynced',
                'Value': count,
                'Unit': 'Count',
                'Dimensions': [{'Name': 'SObject', 'Value': sobject}]
            })
        
        if metric_data:
            cloudwatch_client.put_metric_data(
                Namespace='SalesforceAISearch/Ingestion',
                MetricData=metric_data
            )
            
        print(f"Synced chunks by object: {sobject_counts}")
        
    except Exception as e:
        print(f"Error emitting pipeline metrics: {str(e)}")


def lambda_handler(event, context):
    """Write embedded chunks to S3 in Bedrock KB format."""
    try:
        DATA_BUCKET = os.environ.get('DATA_BUCKET')
        
        # Check if chunks are in S3
        if "embeddedChunksS3Bucket" in event and "embeddedChunksS3Key" in event:
            bucket = event["embeddedChunksS3Bucket"]
            key = event["embeddedChunksS3Key"]
            
            if not key:
                print("No embedded chunks to sync (empty key)")
                return {
                    "s3Bucket": DATA_BUCKET,
                    "chunkCount": 0,
                    "success": True
                }
            
            print(f"Reading embedded chunks from s3://{bucket}/{key}")
            chunks = read_chunks_from_s3(bucket, key)
        else:
            chunks = event.get("embeddedChunks", [])
        
        if not chunks:
            print("No chunks to sync")
            return {
                "s3Bucket": DATA_BUCKET,
                "chunkCount": 0,
                "success": True
            }
        
        if not DATA_BUCKET:
            raise ValueError("DATA_BUCKET environment variable not set")
        
        print(f"Syncing {len(chunks)} chunks to S3")
        
        # Write each chunk to S3
        for chunk in chunks:
            write_chunk_to_s3(chunk, DATA_BUCKET)
        
        # Emit metrics
        emit_pipeline_metrics(chunks)
        
        # Trigger Bedrock Ingestion
        trigger_ingestion_job(KNOWLEDGE_BASE_ID, DATA_SOURCE_ID)
        
        return {
            "s3Bucket": DATA_BUCKET,
            "chunkCount": len(chunks),
            "success": True
        }
    
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        raise
