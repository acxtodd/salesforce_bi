# Lambda Function Unit Tests

This directory contains unit tests for the Lambda functions in the Salesforce AI Search POC.

## Test Coverage

### Chunking Tests (`lambda/chunking/test_chunking.py`)
Tests for the chunking Lambda function that splits Salesforce records into 300-500 token segments:

- **Token Estimation**: Tests token counting logic
- **Text Extraction**: Tests extraction of text fields from Salesforce records
- **Chunk Splitting**: Tests splitting logic with heading retention and token boundaries
- **Metadata Extraction**: Tests metadata enrichment (sobject, recordId, parentIds, etc.)
- **Chunk ID Generation**: Tests chunk ID format (`{sobject}/{recordId}/chunk-{index}`)
- **Record Chunking**: Tests end-to-end chunking with metadata
- **Lambda Handler**: Tests Lambda invocation with various inputs

### Embedding Tests (`lambda/embed/test_embed.py`)
Tests for the embedding Lambda function that generates embeddings using Bedrock Titan:

- **Embedding Generation**: Tests single and batch embedding generation
- **Batch Processing**: Tests processing chunks in batches of up to 25
- **Error Handling**: Tests handling of Bedrock API errors and partial failures
- **Lambda Handler**: Tests Lambda invocation and metadata preservation

## Running Tests

### Setup

1. Create a virtual environment:
```bash
python3 -m venv lambda/.venv
source lambda/.venv/bin/activate
```

2. Install test dependencies:
```bash
pip install -r lambda/test-requirements.txt
```

### Run All Tests

```bash
# From the lambda directory
pytest -v

# Or from project root
pytest lambda/ -v
```

### Run Specific Test Files

```bash
# Chunking tests only
pytest lambda/chunking/test_chunking.py -v

# Embedding tests only
pytest lambda/embed/test_embed.py -v
```

### Run Specific Test Classes or Methods

```bash
# Run a specific test class
pytest lambda/chunking/test_chunking.py::TestChunkSplitting -v

# Run a specific test method
pytest lambda/chunking/test_chunking.py::TestChunkSplitting::test_split_large_text_with_heading -v
```

### Run with Coverage

```bash
pytest --cov=lambda/chunking --cov=lambda/embed --cov-report=html
```

## Test Requirements

The tests use the following dependencies:
- `pytest`: Test framework
- `pytest-cov`: Coverage reporting
- `pytest-mock`: Mocking utilities
- `boto3`: AWS SDK (for mocking Bedrock calls)
- `moto`: AWS service mocking
- `hypothesis`: Property-based testing framework (Phase 3)

## Property-Based Testing (Phase 3)

Phase 3 Graph Enhancement uses Hypothesis for property-based testing to verify correctness properties.

### Hypothesis Configuration

Hypothesis is configured via `conftest.py` with three profiles:

| Profile | Max Examples | Use Case |
|---------|-------------|----------|
| `phase3` (default) | 100 | Standard testing per design.md |
| `ci` | 200 | Thorough CI/CD testing |
| `dev` | 50 | Fast local iteration |

### Running Property Tests

```bash
# Run all property tests
pytest -m property -v

# Run with specific profile
HYPOTHESIS_PROFILE=ci pytest -m property -v

# Run Hypothesis setup verification
pytest test_hypothesis_setup.py -v
```

### Writing Property Tests

Property tests should follow this format:

```python
from hypothesis import given, strategies as st
import pytest

@pytest.mark.property
@given(depth=st.integers(min_value=1, max_value=3))
def test_traversal_depth_limit(depth):
    """
    **Feature: phase3-graph-enhancement, Property 1: Graph Traversal Depth Limit**
    **Validates: Requirements 2.4, 5.2**
    """
    # Test implementation
    assert 1 <= depth <= 3
```

### Property Test Tagging

All property tests must be tagged with:
- `@pytest.mark.property` marker
- Feature and property number in docstring
- Requirements reference in docstring

## Test Design

### Mocking Strategy
- Bedrock API calls are mocked using `unittest.mock.patch`
- No actual AWS API calls are made during tests
- Tests validate logic without external dependencies

### Test Focus
- Core functional logic (chunking, metadata extraction, embedding generation)
- Boundary conditions (empty inputs, large inputs, batch limits)
- Error handling (API failures, invalid inputs, partial failures)
- Minimal edge case testing per guidelines

## Requirements Coverage

These tests satisfy task 2.4 requirements:
- ✅ Test chunk size boundaries and heading retention
- ✅ Test metadata enrichment accuracy
- ✅ Test embedding generation and error handling
- ✅ Requirements: 9.1, 9.2, 9.3
