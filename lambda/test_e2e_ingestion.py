import pytest
import json
import os
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# Import all Lambda handlers
# We need to set up sys.path or use relative imports if possible, but since we are running from lambda/ root, 
# standard imports should work if __init__.py files exist (which they do).

from cdc_processor.index import lambda_handler as cdc_handler
from ingest.index import lambda_handler as ingest_handler
from validate.index import lambda_handler as validate_handler
from transform.index import lambda_handler as transform_handler
from chunking.index import lambda_handler as chunking_handler
from enrich.index import lambda_handler as enrich_handler
from embed.index import lambda_handler as embed_handler
from sync.index import lambda_handler as sync_handler

class TestE2EIngestionPipeline:
    
    @pytest.fixture
    def mock_env(self):
        """Set up environment variables for all Lambdas."""
        env_vars = {
            "DATA_BUCKET": "test-data-bucket",
            "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:test-pipeline",
            "BEDROCK_REGION": "us-west-2",
            "OPENSEARCH_ENDPOINT": "test-endpoint.us-west-2.aoss.amazonaws.com"
        }
        with patch.dict(os.environ, env_vars):
            yield

    @pytest.fixture
    def mock_aws_services(self):
        """Mock all AWS services used by the pipeline."""
        # Create mocks
        s3 = MagicMock()
        cloudwatch = MagicMock()
        stepfunctions = MagicMock()
        bedrock = MagicMock()
        
        # Patch module-level clients
        with patch("cdc_processor.index.s3_client", s3), \
             patch("cdc_processor.index.cloudwatch_client", cloudwatch), \
             patch("ingest.index.sfn_client", stepfunctions), \
             patch("embed.index.bedrock_runtime", bedrock), \
             patch("sync.index.s3_client", s3), \
             patch("sync.index.cloudwatch_client", cloudwatch):
            
            yield {
                "s3": s3,
                "cloudwatch": cloudwatch,
                "sfn": stepfunctions,
                "bedrock": bedrock
            }

    def run_pipeline_chain(self, initial_input):
        """
        Simulate the Step Functions workflow by chaining Lambda executions.
        
        Chain: Validate -> Transform -> Chunking -> Enrich -> Embed -> Sync
        """
        print("\n--- Starting Pipeline Chain ---")
        
        # 1. Validate
        print(f"1. Validate Input: {len(initial_input.get('records', []))} records")
        validate_output = validate_handler(initial_input, None)
        assert validate_output["validCount"] > 0, "Validation failed: No valid records"
        
        # 2. Transform
        # Transform expects "validRecords" which matches Validate output
        print(f"2. Transform Input: {len(validate_output['validRecords'])} valid records")
        transform_output = transform_handler(validate_output, None)
        
        # 3. Chunking
        # Chunking expects "records" which matches Transform output
        print(f"3. Chunking Input: {len(transform_output['records'])} records")
        chunking_output = chunking_handler(transform_output, None)
        
        # 4. Enrich
        # Enrich expects "chunks" which matches Chunking output
        print(f"4. Enrich Input: {len(chunking_output['chunks'])} chunks")
        enrich_output = enrich_handler(chunking_output, None)
        
        # 5. Embed
        # Embed expects "enrichedChunks" which matches Enrich output
        print(f"5. Embed Input: {len(enrich_output.get('enrichedChunks', []))} chunks")
        embed_output = embed_handler(enrich_output, None)
        
        # 6. Sync
        # Sync expects "embeddedChunks" which matches Embed output
        print(f"6. Sync Input: {len(embed_output['embeddedChunks'])} embedded chunks")
        sync_output = sync_handler(embed_output, None)
        
        return sync_output

    def test_cdc_flow_e2e(self, mock_env, mock_aws_services):
        """
        Test the full CDC flow:
        S3 Event -> CDC Processor -> [Pipeline Chain] -> Sync Success
        """
        # 1. Setup CDC Event
        cdc_event = {
            "ChangeEventHeader": {
                "entityName": "Account",
                "recordIds": ["001xx001"],
                "changeType": "UPDATE",
                "commitTimestamp": 1234567890000
            },
            "Id": "001xx001",
            "Name": "Test Account",
            "LastModifiedDate": "2023-01-01T00:00:00Z",
            "Description": "End-to-end test account"
        }
        
        # Mock S3 get_object for CDC Processor
        mock_aws_services["s3"].get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps(cdc_event).encode("utf-8"))
        }
        
        eventbridge_event = {
            "bucket": "test-bucket",
            "key": "cdc/Account/2023/01/01/12/event.json",
            "eventTime": "2023-01-01T12:00:00Z"
        }
        
        # Mock Bedrock for Embed Lambda
        mock_aws_services["bedrock"].invoke_model.return_value = {
            "body": MagicMock(read=lambda: json.dumps({"embedding": [0.1] * 1536}).encode("utf-8"))
        }
        
        # 2. Run CDC Processor
        print("\nRunning CDC Processor...")
        cdc_output = cdc_handler(eventbridge_event, None)
        
        # 3. Run Pipeline Chain
        # CDC output is {'records': [...]}, which fits Validate input
        final_result = self.run_pipeline_chain(cdc_output)
        
        # 4. Verify Success
        assert final_result["success"] is True
        assert final_result["chunkCount"] > 0
        
        # Verify S3 Sync write
        assert mock_aws_services["s3"].put_object.called
        
        # Verify CloudWatch metrics (Freshness from CDC, Lag from Sync)
        assert mock_aws_services["cloudwatch"].put_metric_data.called

    def test_batch_flow_e2e(self, mock_env, mock_aws_services):
        """
        Test the Batch Export flow:
        Batch Request -> Ingest -> [Pipeline Chain] -> Sync Success
        """
        # 1. Setup Batch Request
        batch_request = {
            "sobject": "Opportunity",
            "records": [
                {
                    "Id": "006xx001",
                    "Name": "Big Deal",
                    "StageName": "Closed Won",
                    "LastModifiedDate": "2023-01-01T00:00:00Z",
                    "Amount": 100000
                }
            ],
            "source": "batch_export"
        }
        
        # Mock Bedrock
        mock_aws_services["bedrock"].invoke_model.return_value = {
            "body": MagicMock(read=lambda: json.dumps({"embedding": [0.1] * 1536}).encode("utf-8"))
        }
        
        # Mock Step Functions for Ingest
        mock_aws_services["sfn"].start_execution.return_value = {
            "executionArn": "arn:aws:states:exec-1"
        }
        
        # 2. Run Ingest
        print("\nRunning Ingest...")
        ingest_output = ingest_handler(batch_request, None)
        assert ingest_output["statusCode"] == 202
        
        # Ingest returns 202 and triggers Step Functions.
        # In a real E2E test, we'd capture the input sent to Step Functions and use that to start the chain.
        
        # Capture SFN input
        call_args = mock_aws_services["sfn"].start_execution.call_args
        sfn_input_json = call_args[1]["input"]
        sfn_input = json.loads(sfn_input_json)
        
        # 3. Run Pipeline Chain
        # SFN input has {'records': [...]}, which fits Validate input
        final_result = self.run_pipeline_chain(sfn_input)
        
        # 4. Verify Success
        assert final_result["success"] is True
        assert final_result["chunkCount"] > 0
