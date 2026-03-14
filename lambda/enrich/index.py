"""
Enrich Lambda Function
Enriches chunks with authorization and business metadata.
Reads chunks from S3 and writes enriched chunks back to S3.
"""
import json
import os
import boto3
import uuid
from typing import Dict, Any, List

# Initialize S3 client
s3_client = boto3.client('s3')

# Environment variables
DATA_BUCKET = os.environ.get('DATA_BUCKET')


def enrich_chunk_metadata(chunk: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich chunk metadata with authorization tags and business context.
    """
    metadata = chunk.get("metadata", {})
    
    sharing_buckets = []
    
    if "ownerId" in metadata and metadata["ownerId"]:
        sharing_buckets.append(f"owner:{metadata['ownerId']}")
    
    if "territory" in metadata and metadata["territory"]:
        sharing_buckets.append(f"territory:{metadata['territory']}")
    
    if "businessUnit" in metadata and metadata["businessUnit"]:
        sharing_buckets.append(f"bu:{metadata['businessUnit']}")
    
    if "region" in metadata and metadata["region"]:
        sharing_buckets.append(f"region:{metadata['region']}")
    
    metadata["sharingBuckets"] = sharing_buckets
    metadata["flsProfileTags"] = ["profile:Standard"]
    metadata["hasPII"] = False
    
    if "lastModified" in metadata:
        metadata["effectiveDate"] = metadata["lastModified"]
    
    chunk["metadata"] = metadata
    return chunk


def read_chunks_from_s3(bucket: str, key: str) -> List[Dict[str, Any]]:
    """Read chunks from S3."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response['Body'].read().decode('utf-8')
    return json.loads(content)


def write_chunks_to_s3(chunks: List[Dict[str, Any]], bucket: str, batch_id: str) -> str:
    """Write enriched chunks to S3."""
    s3_key = f"staging/enriched/{batch_id}.json"
    
    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=json.dumps(chunks).encode('utf-8'),
        ContentType='application/json'
    )
    
    print(f"Wrote {len(chunks)} enriched chunks to s3://{bucket}/{s3_key}")
    return s3_key


def lambda_handler(event, context):
    """
    Enrich chunks with metadata.
    Reads from S3 and writes back to S3 to avoid payload limits.
    """
    try:
        # Check if chunks are in S3
        if "chunksS3Bucket" in event and "chunksS3Key" in event:
            bucket = event["chunksS3Bucket"]
            key = event["chunksS3Key"]
            print(f"Reading chunks from s3://{bucket}/{key}")
            chunks = read_chunks_from_s3(bucket, key)
        else:
            chunks = event.get("chunks", [])
        
        if not chunks:
            print("No chunks to enrich")
            return {
                "enrichedChunksS3Bucket": DATA_BUCKET,
                "enrichedChunksS3Key": "",
                "chunkCount": 0
            }
        
        enriched_chunks = []
        for chunk in chunks:
            enriched_chunk = enrich_chunk_metadata(chunk)
            enriched_chunks.append(enriched_chunk)
        
        print(f"Enriched {len(chunks)} chunks with metadata")
        
        # Write to S3 to avoid payload limits
        if DATA_BUCKET:
            batch_id = str(uuid.uuid4())
            s3_key = write_chunks_to_s3(enriched_chunks, DATA_BUCKET, batch_id)
            
            return {
                "enrichedChunksS3Bucket": DATA_BUCKET,
                "enrichedChunksS3Key": s3_key,
                "chunkCount": len(enriched_chunks)
            }
        else:
            # Fallback (may fail for large batches)
            return {
                "enrichedChunks": enriched_chunks,
                "chunkCount": len(enriched_chunks)
            }
    
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        raise
