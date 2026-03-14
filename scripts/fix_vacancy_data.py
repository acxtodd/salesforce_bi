#!/usr/bin/env python3
"""
Fix Vacancy Data in DynamoDB.

Backfills missing vacancy metrics (TotalSqFt, AvailableSqFt, VacancyPct)
from Salesforce into the vacancy_view DynamoDB table.

**Task:** Fix vacancy_view Data Quality
"""

import os
import sys
import time
import logging
from decimal import Decimal
from typing import List, Dict, Any

import boto3
from botocore.exceptions import ClientError

# Add lambda directory to path to import common modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'lambda'))

from common.salesforce_client import get_salesforce_client

# Configuration
REGION = "us-west-2"
VACANCY_TABLE = "salesforce-ai-search-vacancy-view"
BATCH_SIZE = 25  # DynamoDB batch write limit

# Logging setup
logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("fix_vacancy_data")

def get_property_metrics(client) -> List[Dict[str, Any]]:
    """
    Fetch property metrics from Salesforce.
    
    Returns:
        List of property records with Id, TotalSqFt, AvailableSqFt
    """
    query = """
    SELECT Id, Name, ascendix__TotalSqFt__c, ascendix__AvailableSqFt__c
    FROM ascendix__Property__c
    WHERE ascendix__TotalSqFt__c != null
    """
    
    LOGGER.info("Fetching property metrics from Salesforce...")
    try:
        # Use query_all to get all pages
        records = client.query_all(query)
        LOGGER.info(f"Fetched {len(records)} property records")
        return records
    except Exception as e:
        LOGGER.error(f"Failed to fetch properties: {e}")
        return []

def calculate_vacancy(total: float, available: float) -> float:
    """Calculate vacancy percentage."""
    if not total or total <= 0:
        return 0.0
    if not available:
        available = 0.0
        
    return (available / total) * 100.0

def update_dynamodb(records: List[Dict[str, Any]]):
    """Update DynamoDB table with calculated metrics."""
    dynamodb = boto3.resource('dynamodb', region_name=REGION)
    table = dynamodb.Table(VACANCY_TABLE)
    
    updated_count = 0
    error_count = 0
    
    LOGGER.info(f"Updating {VACANCY_TABLE}...")
    
    # Group into batches
    for i in range(0, len(records), BATCH_SIZE):
        batch_records = records[i:i+BATCH_SIZE]
        
        # We can't use batch_writer for updates (it's only for put/delete)
        # We need to use update_item for each record to preserve existing fields
        # However, since this is a "view" table where we might want to just overwrite
        # or we assume the table keys are property_id.
        
        # Let's check the table schema.
        # PK: property_id
        
        for record in batch_records:
            prop_id = record['Id']
            total_sqft = record.get('ascendix__TotalSqFt__c')
            available_sqft = record.get('ascendix__AvailableSqFt__c')
            
            # Handle None values
            if total_sqft is None: 
                total_sqft = 0
            if available_sqft is None: 
                available_sqft = 0
                
            vacancy_pct = calculate_vacancy(float(total_sqft), float(available_sqft))
            
            # Determine bucket for GSI
            # This logic should match what's in lambda/derived_views/index.py if it exists
            bucket = "0-10"
            if vacancy_pct > 50:
                bucket = ">50"
            elif vacancy_pct > 30:
                bucket = "30-50"
            elif vacancy_pct > 20:
                bucket = "20-30"
            elif vacancy_pct > 10:
                bucket = "10-20"
            
            try:
                table.update_item(
                    Key={'property_id': prop_id},
                    UpdateExpression="SET vacancy_pct = :v, total_sqft = :t, available_sqft = :a, vacancy_pct_bucket = :b",
                    ExpressionAttributeValues={
                        ':v': Decimal(str(round(vacancy_pct, 2))),
                        ':t': Decimal(str(total_sqft)),
                        ':a': Decimal(str(available_sqft)),
                        ':b': bucket
                    }
                )
                updated_count += 1
                if updated_count % 100 == 0:
                    LOGGER.info(f"Updated {updated_count} records...")
            except ClientError as e:
                LOGGER.warning(f"Failed to update {prop_id}: {e.response['Error']['Message']}")
                error_count += 1
                
    LOGGER.info(f"Complete. Updated: {updated_count}, Errors: {error_count}")

def main():
    try:
        # Initialize Salesforce client
        sf_client = get_salesforce_client()
        
        # Fetch data
        records = get_property_metrics(sf_client)
        
        if not records:
            LOGGER.warning("No records found or failed to fetch data.")
            return
            
        # Update DynamoDB
        update_dynamodb(records)
        
    except Exception as e:
        LOGGER.error(f"Script failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
