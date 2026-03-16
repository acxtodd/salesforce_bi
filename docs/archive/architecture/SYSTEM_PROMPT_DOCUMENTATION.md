# System Prompt Documentation: How the Agent Formats Results

## Overview

Yes, there is a detailed system prompt in the code that instructs the AI agent on how to format and post results. The system prompt is located in the **Answer Lambda** function and controls citation formatting, answer style, and grounding policy.

## System Prompt Location

**File**: `lambda/answer/index.py`
**Function**: `_build_system_prompt()` (lines 157-199)
**Model**: Claude 3 Sonnet (anthropic.claude-3-sonnet-20240229-v1:0)

## Complete System Prompt Structure

### 1. Base Identity & Role
```python
"""You are an AI assistant helping Salesforce users find information in their CRM data."""
```

### 2. Grounding Policy (Always Applied)
```python
GROUNDING POLICY:
- Answer ONLY using information from the provided context chunks
- If the context does not contain enough information to answer, say "I don't have enough information to answer that question"
- Do NOT make up information or use knowledge outside the provided context
- Do NOT speculate or provide opinions
```

### 3. Citation Requirements (When `require_citations: true`)
```python
- Include paragraph-level citations using [Source: {recordId}] format for all factual claims
- Every factual statement must be supported by a citation

CITATION FORMAT:
- Cite the source record ID after each factual claim
- Use this format: [Source: Opportunity/006xx1]
- For multiple sources: [Source: Opportunity/006xx1, Case/500xx2]
- Always use the full record ID from the context metadata
```

### 4. Answer Style Guidelines
```python
ANSWER STYLE:
- Be concise and direct
- Use bullet points for lists when appropriate
- Include relevant numbers and dates from the context
- Highlight key risks or blockers when present
- Focus on the most relevant information
- Keep your answer under {max_tokens} tokens
```

## How Citations Work

### Citation Format in Responses

The system prompt instructs the model to include citations in a specific format:

**Example Output**:
```
ACME Corp has an open opportunity worth $2.5M [Source: Opportunity/006xx000001ABC].
The deal is expected to close in Q4 2025 [Source: Opportunity/006xx000001ABC].
Their main contact is John Smith [Source: Contact/003xx000002DEF].
```

### Citation Extraction

After the model generates the answer, the system extracts citations using regex:

```python
def _extract_citations(answer: str) -> List[str]:
    """Extract citation markers from answer text."""
    pattern = r'\[Source:\s*([^\]]+)\]'
    matches = re.findall(pattern, answer)

    # Parse each citation (can be single or comma-separated)
    citations = []
    for match in matches:
        parts = match.split(",")
        for part in parts:
            part = part.strip()
            # Handle both "RecordId" and "SObject/RecordId" formats
```

## Context Format Provided to Model

The system provides context to the model in this structured format:

```
[Context 1]
Source: Opportunity/006xx000001ABC
Content: ACME Corp renewal opportunity for Enterprise License. Value: $2.5M. Close date: Q4 2025. Stage: Negotiation.

[Context 2]
Source: Contact/003xx000002DEF
Content: John Smith, VP of IT at ACME Corp. Email: john.smith@acme.com. Phone: 555-0123.

[Context 3]
Source: Case/500xx000003GHI
Content: Open support case regarding API integration issues. Priority: High. Status: In Progress.
```

## Configuration Options

### Policy Parameters

You can control the system prompt behavior through the `policy` object in the request:

```json
{
  "policy": {
    "require_citations": true,    // Whether to require citations
    "max_tokens": 600,            // Maximum answer length
    "temperature": 0.3            // Creativity level (0.0-1.0)
  }
}
```

### Environment Variables

- **BEDROCK_MODEL_ID**: Model to use (default: Claude 3 Sonnet)
- **DEFAULT_MAX_TOKENS**: Default answer length (default: 600)
- **DEFAULT_TEMPERATURE**: Default creativity (default: 0.3)

## Customization Opportunities

### 1. Modify Citation Format

To change how citations appear, update line 181 in `_build_system_prompt()`:

```python
# Current format
- Use this format: [Source: Opportunity/006xx1]

# Alternative formats you could use:
- Use this format: [View Record: 006xx1]
- Use this format: (Source: 006xx1)
- Use this format: [^006xx1]
```

### 2. Adjust Answer Style

To change the writing style, modify lines 187-192:

```python
# Add new style guidelines
prompt += """ANSWER STYLE:
- Be concise and direct
- Start with a summary sentence
- Group related information together
- Use tables for comparisons
- End with next steps or recommendations
"""
```

### 3. Add Domain-Specific Instructions

For CRE (Commercial Real Estate) context, you could add:

```python
# Add after line 192
prompt += """
CRE-SPECIFIC GUIDELINES:
- Always include property addresses when mentioned
- Highlight square footage and lease rates
- Note expiration dates prominently
- Group information by property or deal
"""
```

### 4. Control Citation Density

To reduce citation frequency, modify line 168:

```python
# Current (citation after every claim)
- Include paragraph-level citations using [Source: {recordId}] format for all factual claims

# Alternative (less frequent)
- Include one citation per paragraph using [Source: {recordId}] at the end
```

## Example: Complete System Prompt

Here's what the complete system prompt looks like when assembled:

```
You are an AI assistant helping Salesforce users find information in their CRM data.

GROUNDING POLICY:
- Answer ONLY using information from the provided context chunks
- Include paragraph-level citations using [Source: {recordId}] format for all factual claims
- Every factual statement must be supported by a citation
- If the context does not contain enough information to answer, say "I don't have enough information to answer that question"
- Do NOT make up information or use knowledge outside the provided context
- Do NOT speculate or provide opinions

CITATION FORMAT:
- Cite the source record ID after each factual claim
- Use this format: [Source: Opportunity/006xx1]
- For multiple sources: [Source: Opportunity/006xx1, Case/500xx2]
- Always use the full record ID from the context metadata

ANSWER STYLE:
- Be concise and direct
- Use bullet points for lists when appropriate
- Include relevant numbers and dates from the context
- Highlight key risks or blockers when present
- Focus on the most relevant information
- Keep your answer under 600 tokens
```

## Testing System Prompt Changes

To test changes to the system prompt:

1. **Modify the prompt** in `lambda/answer/index.py`
2. **Deploy the change**:
   ```bash
   cd lambda/answer
   docker build -t answer-lambda .
   npx cdk deploy SalesforceAISearch-Api-dev
   ```
3. **Test with curl**:
   ```bash
   curl -X POST "https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer" \
     -H "x-api-key: YOUR_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "test query",
       "salesforceUserId": "005xx000000XXXXX",
       "policy": {
         "require_citations": true,
         "max_tokens": 300
       }
     }'
   ```

## Impact on Frontend Display

The frontend (`ascendixAiSearch.js`) processes these citations:

1. **Extracts citations** from the `[Source: RecordId]` format
2. **Transforms them** into hyperlinks (as per the hyperlink design)
3. **Displays them** in the citations drawer
4. **Makes them clickable** for navigation

## Recommendations

### For Better Hyperlink Integration

Consider modifying the citation format to include more metadata:

```python
# Enhanced format with object type
- Use this format: [Source: {sobject}/{recordId}]
# Example: [Source: Opportunity/006xx1]

# Or with clickable hint
- Use this format: [View: {recordId}]
# Example: [View: 006xx1]
```

### For Cleaner Display

If citations make the text too cluttered, consider:

1. **Footnote style**: Number citations [1] and list at the end
2. **Inline minimal**: Just record ID [006xx1]
3. **Hover style**: Hide citations until hover

### For Better Accuracy

Add instructions for citation confidence:

```python
CITATION CONFIDENCE:
- Only cite when directly quoting or paraphrasing
- Don't cite for general knowledge or transitions
- Group related facts under one citation when from same source
```

## Summary

The system prompt is a powerful control mechanism that determines:
- ✅ How citations are formatted (`[Source: RecordId]`)
- ✅ When citations are required (every factual claim)
- ✅ Answer style (concise, bulleted, focused)
- ✅ Grounding policy (context-only, no speculation)

This prompt can be easily modified to:
- Change citation format for better hyperlink display
- Adjust citation frequency
- Add domain-specific guidelines
- Control answer length and style

The current format `[Source: RecordId]` works well for the hyperlink feature, as it provides clear record IDs that can be transformed into clickable links in the frontend.