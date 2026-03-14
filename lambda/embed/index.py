"""
Embed Lambda Function
Generates embeddings using Amazon Bedrock Titan Text Embeddings v2.
Reads from S3 and writes back to S3 to avoid payload limits.
"""
import json
import boto3
import os
import uuid
from typing import Dict, Any, List

# Initialize clients
bedrock_runtime = boto3.client('bedrock-runtime')
s3_client = boto3.client('s3')

# Environment variables
DATA_BUCKET = os.environ.get('DATA_BUCKET')

# Titan Text Embeddings v2 model ID
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
BATCH_SIZE = 25


def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for a batch of texts."""
    embeddings = []
    
    for text in texts:
        request_body = {
            "inputText": text,
            "dimensions": 1024,
            "normalize": True
        }
        
        try:
            response = bedrock_runtime.invoke_model(
                modelId=EMBEDDING_MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(request_body)
            )
            
            response_body = json.loads(response['body'].read())
            embeddings.append(response_body['embedding'])
            
        except Exception as e:
            print(f"Error generating embedding: {str(e)}")
            raise e

    return embeddings


def embed_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate embeddings for all chunks."""
    embedded_chunks = []
    
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        texts = [chunk['text'] for chunk in batch]
        
        print(f"Generating embeddings for batch {i // BATCH_SIZE + 1} ({len(texts)} chunks)")
        
        try:
            embeddings = generate_embeddings_batch(texts)
            
            for chunk, embedding in zip(batch, embeddings):
                chunk['embedding'] = embedding
                embedded_chunks.append(chunk)
        
        except Exception as e:
            print(f"Error processing batch {i // BATCH_SIZE + 1}: {str(e)}")
            continue
    
    return embedded_chunks


def read_chunks_from_s3(bucket: str, key: str) -> List[Dict[str, Any]]:
    """Read chunks from S3."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response['Body'].read().decode('utf-8')
    return json.loads(content)


def write_chunks_to_s3(chunks: List[Dict[str, Any]], bucket: str, batch_id: str) -> str:
    """Write embedded chunks to S3."""
    s3_key = f"staging/embedded/{batch_id}.json"
    
    s3_client.put_object(
        Bucket=bucket,
        Key=s3_key,
        Body=json.dumps(chunks).encode('utf-8'),
        ContentType='application/json'
    )
    
    print(f"Wrote {len(chunks)} embedded chunks to s3://{bucket}/{s3_key}")
    return s3_key


def lambda_handler(event, context):
    """
    Generate embeddings for enriched chunks.
    Reads from S3 and writes back to S3 to avoid payload limits.
    """
    try:
        # Check if chunks are in S3
        if "enrichedChunksS3Bucket" in event and "enrichedChunksS3Key" in event:
            bucket = event["enrichedChunksS3Bucket"]
            key = event["enrichedChunksS3Key"]
            print(f"Reading enriched chunks from s3://{bucket}/{key}")
            chunks = read_chunks_from_s3(bucket, key)
        else:
            chunks = event.get("enrichedChunks", [])
        
        if not chunks:
            return {
                "embeddedChunksS3Bucket": DATA_BUCKET,
                "embeddedChunksS3Key": "",
                "chunkCount": 0,
                "successCount": 0,
                "failureCount": 0
            }
        
        print(f"Embedding {len(chunks)} chunks")
        
        embedded_chunks = embed_chunks(chunks)
        
        success_count = len(embedded_chunks)
        failure_count = len(chunks) - success_count
        
        print(f"Embedded {success_count} chunks successfully, {failure_count} failed")
        
        # Write to S3 to avoid payload limits
        if DATA_BUCKET:
            batch_id = str(uuid.uuid4())
            s3_key = write_chunks_to_s3(embedded_chunks, DATA_BUCKET, batch_id)
            
            return {
                "embeddedChunksS3Bucket": DATA_BUCKET,
                "embeddedChunksS3Key": s3_key,
                "chunkCount": len(chunks),
                "successCount": success_count,
                "failureCount": failure_count
            }
        else:
            return {
                "embeddedChunks": embedded_chunks,
                "chunkCount": len(chunks),
                "successCount": success_count,
                "failureCount": failure_count
            }
    
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        raise
