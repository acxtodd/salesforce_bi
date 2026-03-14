"""
Integration tests for CDC ingestion pipeline.
Tests end-to-end flow from CDC event to indexed chunk and freshness lag metrics.

Requirements: 5.1, 5.2
"""
import pytest
import json
import boto3
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List
from unittest.mock import patch, MagicMock
import os

# Import Lambda handlers
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'cdc-processor'))
from cdc_processor.index import lambda_handler as cdc_processor_handler
from ingest.index import lambda_handler as ingest_handler
from sync.index import lambda_handler as sync_handler


class TestCDCPipelineEndToEnd:
    """Test end-to-end CDC pipeline flow."""
    
    @pytest.fixture
    def sample_cdc_event(self):
        """Create a sample CDC event."""
        commit_timestamp = int((datetime.utcnow() - timedelta(minutes=2)).timestamp() * 1000)
        
        return {
            "ChangeEventHeader": {
                "entityName": "Account",
                "recordIds": ["001xx000001234AAA"],
                "changeType": "UPDATE",
                "changeOrigin": "com.salesforce.api.rest",
                "transactionKey": "00000000-0000-0000-0000-000000000000",
                "sequenceNumber": 1,
                "commitTimestamp": commit_timestamp,
                "commitNumber": 123456789,
                "commitUser": "005xx000001234AAA"
            },
            "Id": "001xx000001234AAA",
            "Name": "ACME Corporation",
            "BillingStreet": "123 Main St",
            "BillingCity": "San Francisco",
            "BillingState": "CA",
            "BillingPostalCode": "94105",
            "Phone": "555-1234",
            "Description": "Leading provider of innovative solutions for enterprise customers",
            "OwnerId": "005xx000001234AAA",
            "LastModifiedDate": "2025-11-13T14:30:00.000Z"
        }
    
    @pytest.fixture
    def eventbridge_event(self):
        """Create EventBridge event that triggers CDC processor."""
        return {
            "bucket": "salesforce-ai-search-cdc-test",
            "key": "cdc/Account/2025/11/13/14/event-001.json",
            "eventTime": datetime.utcnow().isoformat() + "Z",
            "eventSource": "cdc"
        }
    
    @patch('cdc_processor.index.s3_client')
    @patch('cdc_processor.index.cloudwatch_client')
    def test_cdc_processor_handles_event(self, mock_cloudwatch, mock_s3, sample_cdc_event, eventbridge_event):
        """Test that CDC processor handles S3 event correctly."""
        # Mock S3 response
        mock_s3.get_object.return_value = {
            'Body': MagicMock(read=lambda: json.dumps(sample_cdc_event).encode('utf-8'))
        }
        
        # Invoke handler
        result = cdc_processor_handler(eventbridge_event, None)
        
        # Verify result structure
        assert 'records' in result
        assert len(result['records']) == 1
        record = result['records'][0]
        assert record['sobject'] == 'Account'
        assert record['data']['Id'] == '001xx000001234AAA'
        assert record['data']['Name'] == 'ACME Corporation'
        assert record['data']['_cdc_change_type'] == 'UPDATE'
        assert '_cdc_commit_timestamp' in record['data']
        
        # Verify S3 was called correctly
        mock_s3.get_object.assert_called_once_with(
            Bucket='salesforce-ai-search-cdc-test',
            Key='cdc/Account/2025/11/13/14/event-001.json'
        )
        
        # Verify CloudWatch metrics were emitted
        assert mock_cloudwatch.put_metric_data.called
        metric_call = mock_cloudwatch.put_metric_data.call_args
        assert metric_call[1]['Namespace'] == 'SalesforceAISearch/Ingestion'
        
        # Verify freshness metrics
        metric_data = metric_call[1]['MetricData']
        metric_names = [m['MetricName'] for m in metric_data]
        assert 'CDCToS3Lag' in metric_names
        assert 'S3ToProcessingLag' in metric_names
        assert 'TotalIngestLag' in metric_names
    
    @patch('cdc_processor.index.s3_client')
    @patch('cdc_processor.index.cloudwatch_client')
    def test_cdc_processor_skips_delete_events(self, mock_cloudwatch, mock_s3, eventbridge_event):
        """Test CDC processor skips DELETE events."""
        delete_event = {
            "ChangeEventHeader": {
                "entityName": "Account",
                "recordIds": ["001xx000001234AAA"],
                "changeType": "DELETE",
                "commitTimestamp": int(datetime.utcnow().timestamp() * 1000)
            },
            "Id": "001xx000001234AAA"
        }
        
        mock_s3.get_object.return_value = {
            'Body': MagicMock(read=lambda: json.dumps(delete_event).encode('utf-8'))
        }
        
        result = cdc_processor_handler(eventbridge_event, None)
        
        # Should return empty records list
        assert result['records'] == []
        assert result.get('validCount', 0) == 0
    
    @patch('cdc_processor.index.s3_client')
    def test_cdc_processor_handles_multiple_objects(self, mock_s3, eventbridge_event):
        """Test CDC processor handles different object types."""
        test_objects = [
            ('Account', 'cdc/Account/2025/11/13/14/event-001.json'),
            ('Opportunity', 'cdc/Opportunity/2025/11/13/14/event-002.json'),
            ('Case', 'cdc/Case/2025/11/13/14/event-003.json'),
            ('Property__c', 'cdc/Property__c/2025/11/13/14/event-004.json')
        ]
        
        for sobject, key in test_objects:
            cdc_event = {
                "ChangeEventHeader": {
                    "entityName": sobject,
                    "recordIds": ["001xx"],
                    "changeType": "UPDATE",
                    "commitTimestamp": int(datetime.utcnow().timestamp() * 1000)
                },
                "Id": "001xx",
                "Name": f"Test {sobject}"
            }
            
            mock_s3.get_object.return_value = {
                'Body': MagicMock(read=lambda e=cdc_event: json.dumps(e).encode('utf-8'))
            }
            
            event = {**eventbridge_event, 'key': key}
            result = cdc_processor_handler(event, None)
            
            assert len(result['records']) == 1
            assert result['records'][0]['sobject'] == sobject


class TestBatchExportFallback:
    """Test batch export fallback mechanism."""
    
    @pytest.fixture
    def batch_export_request(self):
        """Create a sample batch export request."""
        return {
            "sobject": "Account",
            "operation": "upsert",
            "records": [
                {
                    "Id": "001xx000001234AAA",
                    "Name": "ACME Corporation",
                    "BillingCity": "San Francisco",
                    "Description": "Test account 1"
                },
                {
                    "Id": "001xx000001234BBB",
                    "Name": "Globex Inc",
                    "BillingCity": "New York",
                    "Description": "Test account 2"
                }
            ],
            "source": "batch_export",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    
    @patch('ingest.index.sfn_client')
    def test_ingest_handler_accepts_batch(self, mock_sfn, batch_export_request):
        """Test ingest Lambda accepts batch export request."""
        # Set environment variable
        os.environ['STATE_MACHINE_ARN'] = 'arn:aws:states:us-east-1:123456789012:stateMachine:test'
        
        # Mock Step Functions start_execution
        mock_sfn.start_execution.return_value = {
            'executionArn': 'arn:aws:states:us-east-1:123456789012:execution:test:exec-123'
        }
        
        # Call ingest handler
        result = ingest_handler(batch_export_request, None)
        
        # Verify response
        assert result['statusCode'] == 202
        body = json.loads(result['body'])
        assert body['accepted'] is True
        assert body['recordCount'] == 2
        assert body['sobject'] == 'Account'
        assert 'jobId' in body
        
        # Verify Step Functions was called
        assert mock_sfn.start_execution.called
        call_args = mock_sfn.start_execution.call_args
        
        # Verify input format
        sfn_input = json.loads(call_args[1]['input'])
        assert 'records' in sfn_input
        assert len(sfn_input['records']) == 2
        assert sfn_input['source'] == 'batch_export'
        assert sfn_input['records'][0]['sobject'] == 'Account'
    
    @patch('ingest.index.sfn_client')
    def test_ingest_handler_validates_request(self, mock_sfn):
        """Test ingest Lambda validates request format."""
        invalid_requests = [
            {},  # Missing required fields
            {"sobject": "Account"},  # Missing records
            {"records": []},  # Missing sobject
            {"sobject": "Account", "records": "not-a-list"},  # Invalid records type
            {"sobject": "Account", "records": []},  # Empty records
        ]
        
        for invalid_request in invalid_requests:
            result = ingest_handler(invalid_request, None)
            assert result['statusCode'] == 400
            body = json.loads(result['body'])
            assert 'error' in body
    
    @patch('ingest.index.sfn_client')
    def test_ingest_handler_enforces_batch_size_limit(self, mock_sfn):
        """Test ingest Lambda enforces maximum batch size."""
        # Create request with too many records
        large_batch = {
            "sobject": "Account",
            "records": [{"Id": f"001{i:05d}", "Name": f"Account {i}"} for i in range(1001)]
        }
        
        result = ingest_handler(large_batch, None)
        
        assert result['statusCode'] == 400
        body = json.loads(result['body'])
        assert 'error' in body
        assert '1000' in body['message']
    
    @patch('ingest.index.sfn_client')
    def test_ingest_handler_handles_api_gateway_format(self, mock_sfn):
        """Test ingest Lambda handles API Gateway request format."""
        os.environ['STATE_MACHINE_ARN'] = 'arn:aws:states:us-east-1:123456789012:stateMachine:test'
        
        mock_sfn.start_execution.return_value = {
            'executionArn': 'arn:aws:states:us-east-1:123456789012:execution:test:exec-123'
        }
        
        # API Gateway wraps body as string
        api_gateway_event = {
            "body": json.dumps({
                "sobject": "Account",
                "records": [{"Id": "001xx", "Name": "Test"}]
            }),
            "headers": {"Content-Type": "application/json"}
        }
        
        result = ingest_handler(api_gateway_event, None)
        
        assert result['statusCode'] == 202
        body = json.loads(result['body'])
        assert body['accepted'] is True


class TestFreshnessMetrics:
    """Test freshness lag metrics and monitoring."""
    
    @patch('sync.index.cloudwatch_client')
    @patch('sync.index.s3_client')
    def test_sync_emits_end_to_end_lag_metric(self, mock_s3, mock_cloudwatch):
        """Test sync Lambda emits end-to-end lag metric."""
        os.environ['DATA_BUCKET'] = 'test-data-bucket'
        
        # Create chunks with CDC metadata
        commit_timestamp = int((datetime.utcnow() - timedelta(minutes=3)).timestamp() * 1000)
        
        event = {
            "embeddedChunks": [
                {
                    "id": "Account/001xx/chunk-0",
                    "text": "Test chunk text",
                    "embedding": [0.1] * 1536,
                    "metadata": {
                        "sobject": "Account",
                        "recordId": "001xx",
                        "_cdc_commit_timestamp": commit_timestamp
                    }
                }
            ]
        }
        
        # Call sync handler
        result = sync_handler(event, None)
        
        # Verify result
        assert result['success'] is True
        assert result['chunkCount'] == 1
        
        # Verify CloudWatch metrics were emitted
        assert mock_cloudwatch.put_metric_data.called
        
        # Find EndToEndLag metric
        metric_calls = mock_cloudwatch.put_metric_data.call_args_list
        end_to_end_metrics = []
        
        for call in metric_calls:
            metric_data = call[1]['MetricData']
            for metric in metric_data:
                if metric['MetricName'] == 'EndToEndLag':
                    end_to_end_metrics.append(metric)
        
        assert len(end_to_end_metrics) > 0
        
        # Verify lag is reasonable (should be ~3 minutes = 180,000 ms)
        lag_metric = end_to_end_metrics[0]
        lag_ms = lag_metric['Value']
        
        # Lag should be approximately 3 minutes (with some tolerance)
        assert 170000 < lag_ms < 200000  # 2.8 - 3.3 minutes
        
        # Verify dimensions
        dimensions = {d['Name']: d['Value'] for d in lag_metric['Dimensions']}
        assert dimensions['SObject'] == 'Account'
        assert dimensions['Stage'] == 'EndToEnd'
    
    @patch('sync.index.cloudwatch_client')
    @patch('sync.index.s3_client')
    def test_sync_emits_chunks_synced_metric(self, mock_s3, mock_cloudwatch):
        """Test sync Lambda emits chunks synced metric by object."""
        os.environ['DATA_BUCKET'] = 'test-data-bucket'
        
        event = {
            "embeddedChunks": [
                {
                    "id": "Account/001xx/chunk-0",
                    "text": "Account chunk",
                    "embedding": [0.1] * 1536,
                    "metadata": {"sobject": "Account", "recordId": "001xx"}
                },
                {
                    "id": "Account/002xx/chunk-0",
                    "text": "Another account chunk",
                    "embedding": [0.1] * 1536,
                    "metadata": {"sobject": "Account", "recordId": "002xx"}
                },
                {
                    "id": "Opportunity/006xx/chunk-0",
                    "text": "Opportunity chunk",
                    "embedding": [0.1] * 1536,
                    "metadata": {"sobject": "Opportunity", "recordId": "006xx"}
                }
            ]
        }
        
        result = sync_handler(event, None)
        
        assert result['success'] is True
        assert result['chunkCount'] == 3
        
        # Verify ChunksSynced metrics
        metric_calls = mock_cloudwatch.put_metric_data.call_args_list
        chunks_synced_metrics = []
        
        for call in metric_calls:
            metric_data = call[1]['MetricData']
            for metric in metric_data:
                if metric['MetricName'] == 'ChunksSynced':
                    chunks_synced_metrics.append(metric)
        
        # Should have metrics for Account and Opportunity
        assert len(chunks_synced_metrics) >= 2
        
        # Verify counts by object
        sobject_counts = {}
        for metric in chunks_synced_metrics:
            dimensions = {d['Name']: d['Value'] for d in metric['Dimensions']}
            sobject = dimensions['SObject']
            sobject_counts[sobject] = metric['Value']
        
        assert sobject_counts.get('Account') == 2
        assert sobject_counts.get('Opportunity') == 1
    
    @patch('cdc_processor.index.cloudwatch_client')
    @patch('cdc_processor.index.s3_client')
    def test_freshness_lag_meets_target(self, mock_s3, mock_cloudwatch):
        """Test that freshness lag metrics meet P50 target of 5 minutes."""
        # Simulate CDC event with commit timestamp 4 minutes ago (within target)
        commit_timestamp = int((datetime.utcnow() - timedelta(minutes=4)).timestamp() * 1000)
        
        cdc_event = {
            "ChangeEventHeader": {
                "entityName": "Account",
                "recordIds": ["001xx"],
                "changeType": "UPDATE",
                "commitTimestamp": commit_timestamp
            },
            "Id": "001xx",
            "Name": "Test Account"
        }
        
        mock_s3.get_object.return_value = {
            'Body': MagicMock(read=lambda: json.dumps(cdc_event).encode('utf-8'))
        }
        
        eventbridge_event = {
            "bucket": "test-bucket",
            "key": "cdc/Account/2025/11/13/14/event-001.json",
            "eventTime": datetime.utcnow().isoformat() + "Z",
            "eventSource": "cdc"
        }
        
        result = cdc_processor_handler(eventbridge_event, None)
        
        # Verify metrics were emitted
        assert mock_cloudwatch.put_metric_data.called
        
        # Extract lag values
        metric_call = mock_cloudwatch.put_metric_data.call_args
        metric_data = metric_call[1]['MetricData']
        
        total_lag_metric = next(m for m in metric_data if m['MetricName'] == 'TotalIngestLag')
        total_lag_ms = total_lag_metric['Value']
        
        # Total lag should be less than 5 minutes (300,000 ms)
        # This is just the CDC->S3 + S3->Processing portion
        # Full pipeline would add more time, but this validates the early stages
        assert total_lag_ms < 300000, f"Total lag {total_lag_ms}ms exceeds 5-minute target"


class TestPipelineErrorHandling:
    """Test error handling in CDC pipeline."""
    
    @patch('cdc_processor.index.s3_client')
    def test_cdc_processor_handles_missing_s3_object(self, mock_s3):
        """Test CDC processor handles S3 object not found error."""
        mock_s3.get_object.side_effect = Exception("NoSuchKey")
        
        eventbridge_event = {
            "bucket": "test-bucket",
            "key": "cdc/Account/2025/11/13/14/missing.json",
            "eventTime": datetime.utcnow().isoformat() + "Z"
        }
        
        with pytest.raises(Exception):
            cdc_processor_handler(eventbridge_event, None)
    
    @patch('cdc_processor.index.s3_client')
    def test_cdc_processor_handles_invalid_json(self, mock_s3):
        """Test CDC processor handles invalid JSON in S3 object."""
        mock_s3.get_object.return_value = {
            'Body': MagicMock(read=lambda: b'invalid json{')
        }
        
        eventbridge_event = {
            "bucket": "test-bucket",
            "key": "cdc/Account/2025/11/13/14/event-001.json",
            "eventTime": datetime.utcnow().isoformat() + "Z"
        }
        
        with pytest.raises(Exception):
            cdc_processor_handler(eventbridge_event, None)
    
    @patch('ingest.index.sfn_client')
    def test_ingest_handler_handles_step_functions_error(self, mock_sfn):
        """Test ingest Lambda handles Step Functions errors."""
        os.environ['STATE_MACHINE_ARN'] = 'arn:aws:states:us-east-1:123456789012:stateMachine:test'
        
        mock_sfn.start_execution.side_effect = Exception("ExecutionLimitExceeded")
        
        request = {
            "sobject": "Account",
            "records": [{"Id": "001xx", "Name": "Test"}]
        }
        
        result = ingest_handler(request, None)
        
        assert result['statusCode'] == 500
        body = json.loads(result['body'])
        assert 'error' in body
    
    @patch('sync.index.s3_client')
    def test_sync_handles_s3_write_error(self, mock_s3):
        """Test sync Lambda handles S3 write errors."""
        os.environ['DATA_BUCKET'] = 'test-bucket'
        
        mock_s3.put_object.side_effect = Exception("AccessDenied")
        
        event = {
            "embeddedChunks": [
                {
                    "id": "Account/001xx/chunk-0",
                    "text": "Test",
                    "embedding": [0.1] * 1536,
                    "metadata": {"sobject": "Account"}
                }
            ]
        }
        
        with pytest.raises(Exception):
            sync_handler(event, None)


class TestPipelinePerformance:
    """Test pipeline performance characteristics."""
    
    @patch('cdc_processor.index.s3_client')
    @patch('cdc_processor.index.cloudwatch_client')
    def test_cdc_processor_performance(self, mock_cloudwatch, mock_s3):
        """Test CDC processor completes within performance target."""
        cdc_event = {
            "ChangeEventHeader": {
                "entityName": "Account",
                "recordIds": ["001xx"],
                "changeType": "UPDATE",
                "commitTimestamp": int(datetime.utcnow().timestamp() * 1000)
            },
            "Id": "001xx",
            "Name": "Test Account"
        }
        
        mock_s3.get_object.return_value = {
            'Body': MagicMock(read=lambda: json.dumps(cdc_event).encode('utf-8'))
        }
        
        eventbridge_event = {
            "bucket": "test-bucket",
            "key": "cdc/Account/2025/11/13/14/event-001.json",
            "eventTime": datetime.utcnow().isoformat() + "Z"
        }
        
        start_time = time.time()
        result = cdc_processor_handler(eventbridge_event, None)
        elapsed_ms = (time.time() - start_time) * 1000
        
        # CDC processor should complete in under 5 seconds
        assert elapsed_ms < 5000, f"CDC processor took {elapsed_ms}ms, expected < 5000ms"
        assert len(result['records']) == 1
    
    @patch('sync.index.s3_client')
    @patch('sync.index.cloudwatch_client')
    def test_sync_performance_with_multiple_chunks(self, mock_cloudwatch, mock_s3):
        """Test sync Lambda performance with multiple chunks."""
        os.environ['DATA_BUCKET'] = 'test-bucket'
        
        # Create 100 chunks
        chunks = []
        for i in range(100):
            chunks.append({
                "id": f"Account/001{i:02d}/chunk-0",
                "text": f"Test chunk {i}",
                "embedding": [0.1] * 1536,
                "metadata": {"sobject": "Account", "recordId": f"001{i:02d}"}
            })
        
        event = {"embeddedChunks": chunks}
        
        start_time = time.time()
        result = sync_handler(event, None)
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Sync should complete in under 5 seconds for 100 chunks
        assert elapsed_ms < 5000, f"Sync took {elapsed_ms}ms for 100 chunks, expected < 5000ms"
        assert result['success'] is True
        assert result['chunkCount'] == 100
