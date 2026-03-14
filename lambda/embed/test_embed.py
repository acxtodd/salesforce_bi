"""
Unit tests for embedding Lambda function.
Tests embedding generation and error handling.
"""
import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from embed.index import (
    generate_embeddings_batch,
    embed_chunks,
    lambda_handler,
    BATCH_SIZE,
    EMBEDDING_MODEL_ID
)


class TestEmbeddingGeneration:
    """Test embedding generation with Bedrock."""
    
    @patch('embed.index.bedrock_runtime')
    def test_generate_embeddings_single_text(self, mock_bedrock):
        """Test generating embedding for single text."""
        # Mock Bedrock response
        mock_response = {
            'body': MagicMock()
        }
        mock_response['body'].read.return_value = json.dumps({
            'embedding': [0.1, 0.2, 0.3, 0.4]
        }).encode('utf-8')
        mock_bedrock.invoke_model.return_value = mock_response
        
        texts = ["Test text for embedding"]
        embeddings = generate_embeddings_batch(texts)
        
        assert len(embeddings) == 1
        assert len(embeddings[0]) == 4
        assert embeddings[0] == [0.1, 0.2, 0.3, 0.4]
        
        # Verify Bedrock was called with correct parameters
        mock_bedrock.invoke_model.assert_called_once()
        call_args = mock_bedrock.invoke_model.call_args
        assert call_args[1]['modelId'] == EMBEDDING_MODEL_ID
        
        body = json.loads(call_args[1]['body'])
        assert body['inputText'] == "Test text for embedding"
        assert body['dimensions'] == 1024
        assert body['normalize'] is True
    
    @patch('embed.index.bedrock_runtime')
    def test_generate_embeddings_batch(self, mock_bedrock):
        """Test generating embeddings for multiple texts."""
        # Mock Bedrock response for batch (one call per text)
        def mock_invoke_model(**kwargs):
            body = json.loads(kwargs['body'])
            text = body['inputText']
            # Generate deterministic embedding based on text
            val = 0.1
            if "Text 2" in text: val = 0.4
            if "Text 3" in text: val = 0.7
            
            mock_response = {'body': MagicMock()}
            mock_response['body'].read.return_value = json.dumps({
                'embedding': [val, val + 0.1, val + 0.2]
            }).encode('utf-8')
            return mock_response

        mock_bedrock.invoke_model.side_effect = mock_invoke_model
        
        texts = ["Text 1", "Text 2", "Text 3"]
        embeddings = generate_embeddings_batch(texts)
        
        assert len(embeddings) == 3
        assert embeddings[0] == pytest.approx([0.1, 0.2, 0.3])
        assert embeddings[1] == pytest.approx([0.4, 0.5, 0.6])
        assert embeddings[2] == pytest.approx([0.7, 0.8, 0.9])
        
        # Verify calls
        assert mock_bedrock.invoke_model.call_count == 3
    

    
    @patch('embed.index.bedrock_runtime')
    def test_generate_embeddings_bedrock_error(self, mock_bedrock):
        """Test handling of Bedrock API errors."""
        # Mock Bedrock error
        mock_bedrock.invoke_model.side_effect = Exception("Bedrock API error")
        
        texts = ["Test text"]
        
        with pytest.raises(Exception, match="Bedrock API error"):
            generate_embeddings_batch(texts)


class TestEmbedChunks:
    """Test batch processing of chunks."""
    
    @patch('embed.index.bedrock_runtime')
    def test_embed_chunks_single_batch(self, mock_bedrock):
        """Test embedding chunks that fit in single batch."""
        # Mock Bedrock response
        def mock_invoke_model(**kwargs):
            body = json.loads(kwargs['body'])
            text = body['inputText']
            val = 0.1
            if "Text 2" in text: val = 0.3
            
            mock_response = {'body': MagicMock()}
            mock_response['body'].read.return_value = json.dumps({
                'embedding': [val, val + 0.1]
            }).encode('utf-8')
            return mock_response
            
        mock_bedrock.invoke_model.side_effect = mock_invoke_model
        
        chunks = [
            {"id": "chunk-0", "text": "Text 1", "metadata": {}},
            {"id": "chunk-1", "text": "Text 2", "metadata": {}}
        ]
        
        embedded_chunks = embed_chunks(chunks)
        
        assert len(embedded_chunks) == 2
        assert embedded_chunks[0]["embedding"] == [0.1, 0.2]
        assert embedded_chunks[1]["embedding"] == [0.3, 0.4]
        assert embedded_chunks[0]["id"] == "chunk-0"
        assert embedded_chunks[1]["id"] == "chunk-1"
    
    @patch('embed.index.bedrock_runtime')
    def test_embed_chunks_multiple_batches(self, mock_bedrock):
        """Test embedding chunks requiring multiple batches."""
        # Mock Bedrock responses for multiple batches
        def mock_invoke_model(**kwargs):
            mock_response = {'body': MagicMock()}
            mock_response['body'].read.return_value = json.dumps({
                'embedding': [0.1]
            }).encode('utf-8')
            return mock_response
        
        mock_bedrock.invoke_model.side_effect = mock_invoke_model
        
        # Create more chunks than batch size
        chunks = [
            {"id": f"chunk-{i}", "text": f"Text {i}", "metadata": {}}
            for i in range(BATCH_SIZE + 5)
        ]
        
        embedded_chunks = embed_chunks(chunks)
        
        # All chunks should be embedded
        assert len(embedded_chunks) == BATCH_SIZE + 5
        
        # Verify multiple Bedrock calls were made (one per text)
        assert mock_bedrock.invoke_model.call_count == BATCH_SIZE + 5
    
    @patch('embed.index.bedrock_runtime')
    def test_embed_chunks_partial_failure(self, mock_bedrock):
        """Test that batch failure doesn't stop processing."""
        call_count = [0]
        
        def mock_invoke_model(**kwargs):
            call_count[0] += 1
            # Fail calls for the first batch (indices 1-25)
            # But wait, embed_chunks calls generate_embeddings_batch which iterates.
            # If generate_embeddings_batch fails for ONE text, it raises exception and fails the WHOLE batch.
            # So we need to simulate failure for texts in the first batch.
            
            # Let's say we have 30 chunks. Batch 1: 0-24. Batch 2: 25-29.
            # If call_count <= 25 (Batch 1), we raise exception.
            # But generate_embeddings_batch stops at first failure.
            # So if we fail at call 1, the whole batch 1 fails.
            
            if call_count[0] == 1:
                raise Exception("Bedrock error")
            else:
                mock_response = {'body': MagicMock()}
                mock_response['body'].read.return_value = json.dumps({
                    'embedding': [0.1]
                }).encode('utf-8')
                return mock_response
        
        mock_bedrock.invoke_model.side_effect = mock_invoke_model
        
        # Create chunks for two batches
        chunks = [
            {"id": f"chunk-{i}", "text": f"Text {i}", "metadata": {}}
            for i in range(BATCH_SIZE + 5)
        ]
        
        embedded_chunks = embed_chunks(chunks)
        
        # Only second batch should be embedded
        assert len(embedded_chunks) == 5
        assert all('embedding' in chunk for chunk in embedded_chunks)
    
    @patch('embed.index.bedrock_runtime')
    def test_embed_chunks_empty_list(self, mock_bedrock):
        """Test embedding empty chunk list."""
        chunks = []
        
        embedded_chunks = embed_chunks(chunks)
        
        assert len(embedded_chunks) == 0
        mock_bedrock.invoke_model.assert_not_called()


class TestLambdaHandler:
    """Test Lambda handler function."""
    
    @patch('embed.index.bedrock_runtime')
    def test_lambda_handler_success(self, mock_bedrock):
        """Test successful Lambda invocation."""
        # Mock Bedrock response
        def mock_invoke_model(**kwargs):
            body = json.loads(kwargs['body'])
            text = body['inputText']
            val = 0.1
            if "Test text 2" in text: val = 0.4
            
            mock_response = {'body': MagicMock()}
            mock_response['body'].read.return_value = json.dumps({
                'embedding': [val, val + 0.1, val + 0.2]
            }).encode('utf-8')
            return mock_response
            
        mock_bedrock.invoke_model.side_effect = mock_invoke_model
        
        event = {
            "enrichedChunks": [
                {
                    "id": "Account/001xx/chunk-0",
                    "text": "Test text 1",
                    "metadata": {"sobject": "Account"}
                },
                {
                    "id": "Account/001xx/chunk-1",
                    "text": "Test text 2",
                    "metadata": {"sobject": "Account"}
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert response["chunkCount"] == 2
        assert response["successCount"] == 2
        assert response["failureCount"] == 0
        assert len(response["embeddedChunks"]) == 2
        assert all('embedding' in chunk for chunk in response["embeddedChunks"])
    
    @patch('embed.index.bedrock_runtime')
    def test_lambda_handler_empty_chunks(self, mock_bedrock):
        """Test Lambda with no chunks."""
        event = {"enrichedChunks": []}
        
        response = lambda_handler(event, None)
        
        assert response["chunkCount"] == 0
        assert response["successCount"] == 0
        assert response["failureCount"] == 0
        # When chunks are empty, handler returns S3 bucket/key instead of embeddedChunks
        assert response["embeddedChunksS3Key"] == ""
        mock_bedrock.invoke_model.assert_not_called()
    
    @patch('embed.index.bedrock_runtime')
    def test_lambda_handler_missing_chunks_key(self, mock_bedrock):
        """Test Lambda with missing enrichedChunks key."""
        event = {}
        
        response = lambda_handler(event, None)
        
        assert response["chunkCount"] == 0
        assert response["successCount"] == 0
        assert response["failureCount"] == 0
    
    @patch('embed.index.bedrock_runtime')
    def test_lambda_handler_partial_success(self, mock_bedrock):
        """Test Lambda with partial batch failures."""
        call_count = [0]
        
        def mock_invoke_model(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("First batch failed")
            else:
                mock_response = {'body': MagicMock()}
                mock_response['body'].read.return_value = json.dumps({
                    'embedding': [0.1]
                }).encode('utf-8')
                return mock_response
        
        mock_bedrock.invoke_model.side_effect = mock_invoke_model
        
        # Create chunks for two batches
        event = {
            "enrichedChunks": [
                {"id": f"chunk-{i}", "text": f"Text {i}", "metadata": {}}
                for i in range(BATCH_SIZE + 5)
            ]
        }
        
        response = lambda_handler(event, None)
        
        assert response["chunkCount"] == BATCH_SIZE + 5
        assert response["successCount"] == 5
        assert response["failureCount"] == BATCH_SIZE
    
    @patch('embed.index.bedrock_runtime')
    def test_lambda_handler_preserves_metadata(self, mock_bedrock):
        """Test that Lambda preserves chunk metadata."""
        # Mock Bedrock response
        def mock_invoke_model(**kwargs):
            mock_response = {'body': MagicMock()}
            mock_response['body'].read.return_value = json.dumps({
                'embedding': [0.1, 0.2, 0.3]
            }).encode('utf-8')
            return mock_response
            
        mock_bedrock.invoke_model.side_effect = mock_invoke_model
        
        event = {
            "enrichedChunks": [
                {
                    "id": "Account/001xx/chunk-0",
                    "text": "Test text",
                    "metadata": {
                        "sobject": "Account",
                        "recordId": "001xx",
                        "ownerId": "005yy",
                        "territory": "EMEA"
                    }
                }
            ]
        }
        
        response = lambda_handler(event, None)
        
        embedded_chunk = response["embeddedChunks"][0]
        assert embedded_chunk["id"] == "Account/001xx/chunk-0"
        assert embedded_chunk["text"] == "Test text"
        assert embedded_chunk["metadata"]["sobject"] == "Account"
        assert embedded_chunk["metadata"]["recordId"] == "001xx"
        assert embedded_chunk["metadata"]["ownerId"] == "005yy"
        assert embedded_chunk["metadata"]["territory"] == "EMEA"
        assert "embedding" in embedded_chunk
