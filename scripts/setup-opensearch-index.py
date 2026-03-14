#!/usr/bin/env python3
"""
Script to create OpenSearch index with authorization metadata fields.
This script should be run after the OpenSearch cluster is deployed.

Usage:
    python scripts/setup-opensearch-index.py --endpoint <opensearch-endpoint>
"""

import argparse
import json
import sys
from typing import Dict, Any
import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Index name for Salesforce chunks
INDEX_NAME = 'salesforce-chunks'

# Index mapping with authorization metadata fields
INDEX_MAPPING = {
    "settings": {
        "index": {
            "number_of_shards": 2,
            "number_of_replicas": 1,
            "refresh_interval": "5s",
            "knn": True,
            "knn.algo_param.ef_search": 512
        },
        "analysis": {
            "analyzer": {
                "default": {
                    "type": "standard"
                }
            }
        }
    },
    "mappings": {
        "properties": {
            # Core fields
            "id": {
                "type": "keyword"
            },
            "text": {
                "type": "text",
                "analyzer": "standard",
                "fields": {
                    "keyword": {
                        "type": "keyword",
                        "ignore_above": 256
                    }
                }
            },
            "embedding": {
                "type": "knn_vector",
                "dimension": 1024,  # Titan Text Embeddings v2 dimension
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "nmslib",
                    "parameters": {
                        "ef_construction": 512,
                        "m": 16
                    }
                }
            },
            
            # Metadata fields
            "metadata": {
                "type": "object",
                "properties": {
                    # Salesforce object metadata
                    "sobject": {
                        "type": "keyword"
                    },
                    "recordId": {
                        "type": "keyword"
                    },
                    "parentIds": {
                        "type": "keyword"
                    },
                    "ownerId": {
                        "type": "keyword"
                    },
                    "ownerName": {
                        "type": "text",
                        "fields": {
                            "keyword": {
                                "type": "keyword"
                            }
                        }
                    },
                    
                    # Territory and business unit
                    "territory": {
                        "type": "keyword"
                    },
                    "businessUnit": {
                        "type": "keyword"
                    },
                    "region": {
                        "type": "keyword"
                    },
                    
                    # Authorization fields
                    "sharingBuckets": {
                        "type": "keyword"
                    },
                    "flsProfileTags": {
                        "type": "keyword"
                    },
                    "hasPII": {
                        "type": "boolean"
                    },
                    
                    # Temporal fields
                    "effectiveDate": {
                        "type": "date"
                    },
                    "lastModified": {
                        "type": "date"
                    },
                    
                    # Content metadata
                    "language": {
                        "type": "keyword"
                    },
                    "chunkIndex": {
                        "type": "integer"
                    },
                    "totalChunks": {
                        "type": "integer"
                    },
                    "sourceField": {
                        "type": "keyword"
                    },
                    "recordUrl": {
                        "type": "keyword"
                    },
                    
                    # Object-specific fields (dynamic based on sobject)
                    "stage": {
                        "type": "keyword"
                    },
                    "amount": {
                        "type": "double"
                    },
                    "closeDate": {
                        "type": "date"
                    },
                    "accountName": {
                        "type": "text",
                        "fields": {
                            "keyword": {
                                "type": "keyword"
                            }
                        }
                    },
                    "status": {
                        "type": "keyword"
                    },
                    "priority": {
                        "type": "keyword"
                    }
                }
            }
        }
    }
}


def get_opensearch_client(endpoint: str, region: str) -> OpenSearch:
    """
    Create an OpenSearch client with AWS authentication.
    
    Args:
        endpoint: OpenSearch domain endpoint (without https://)
        region: AWS region
        
    Returns:
        OpenSearch client instance
    """
    # Get AWS credentials
    credentials = boto3.Session().get_credentials()
    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        'es',
        session_token=credentials.token
    )
    
    # Create OpenSearch client
    client = OpenSearch(
        hosts=[{'host': endpoint, 'port': 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30
    )
    
    return client


def create_index(client: OpenSearch, index_name: str, mapping: Dict[str, Any]) -> bool:
    """
    Create OpenSearch index with the specified mapping.
    
    Args:
        client: OpenSearch client
        index_name: Name of the index to create
        mapping: Index mapping configuration
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if index already exists
        if client.indices.exists(index=index_name):
            print(f"Index '{index_name}' already exists.")
            response = input("Do you want to delete and recreate it? (yes/no): ")
            if response.lower() == 'yes':
                print(f"Deleting existing index '{index_name}'...")
                client.indices.delete(index=index_name)
            else:
                print("Keeping existing index.")
                return True
        
        # Create index
        print(f"Creating index '{index_name}'...")
        response = client.indices.create(
            index=index_name,
            body=mapping
        )
        
        print(f"Index '{index_name}' created successfully!")
        print(f"Response: {json.dumps(response, indent=2)}")
        return True
        
    except Exception as e:
        print(f"Error creating index: {str(e)}")
        return False


def verify_index(client: OpenSearch, index_name: str) -> bool:
    """
    Verify the index was created with correct mappings.
    
    Args:
        client: OpenSearch client
        index_name: Name of the index to verify
        
    Returns:
        True if verification successful, False otherwise
    """
    try:
        # Get index mappings
        mappings = client.indices.get_mapping(index=index_name)
        print(f"\nIndex mappings for '{index_name}':")
        print(json.dumps(mappings, indent=2))
        
        # Get index settings
        settings = client.indices.get_settings(index=index_name)
        print(f"\nIndex settings for '{index_name}':")
        print(json.dumps(settings, indent=2))
        
        return True
        
    except Exception as e:
        print(f"Error verifying index: {str(e)}")
        return False


def main():
    """Main function to set up OpenSearch index."""
    parser = argparse.ArgumentParser(
        description='Set up OpenSearch index with authorization metadata fields'
    )
    parser.add_argument(
        '--endpoint',
        required=True,
        help='OpenSearch domain endpoint (without https://)'
    )
    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region (default: us-east-1)'
    )
    parser.add_argument(
        '--index-name',
        default=INDEX_NAME,
        help=f'Index name (default: {INDEX_NAME})'
    )
    
    args = parser.parse_args()
    
    print(f"Connecting to OpenSearch at {args.endpoint}...")
    
    try:
        # Create OpenSearch client
        client = get_opensearch_client(args.endpoint, args.region)
        
        # Test connection
        info = client.info()
        print(f"Connected to OpenSearch cluster:")
        print(f"  Version: {info['version']['number']}")
        print(f"  Cluster: {info['cluster_name']}")
        
        # Create index
        success = create_index(client, args.index_name, INDEX_MAPPING)
        
        if success:
            # Verify index
            verify_index(client, args.index_name)
            print("\n✓ Index setup completed successfully!")
            return 0
        else:
            print("\n✗ Index setup failed!")
            return 1
            
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
