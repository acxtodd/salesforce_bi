# Natural Hyperlinks Implementation Guide
**Date**: November 26, 2025
**Feature**: Record names as clickable hyperlinks (Salesforce-native pattern)
**Effort**: 1-2 hours

---

## Overview

This implementation makes record names (like "ACME Corp" or "Enterprise Renewal Deal") automatically clickable in AI search answers, matching native Salesforce behavior. No citation markers needed - just clean, natural text with familiar blue hyperlinks.

---

## Step 1: Update the Backend System Prompt (15 minutes)

### File: `lambda/answer/index.py`

**Replace the `_build_system_prompt` function** (lines 157-199) with this version:

```python
def _build_system_prompt(policy: Dict[str, Any]) -> str:
    """Construct system prompt with grounding policy - optimized for natural hyperlinks."""

    prompt = """You are an AI assistant helping Salesforce users find information in their CRM data.

GROUNDING POLICY:
- Answer ONLY using information from the provided context chunks
- When mentioning specific records (Accounts, Opportunities, Cases, etc.), use their EXACT names as they appear in the context
- If the context does not contain enough information to answer, say "I don't have enough information to answer that question"
- Do NOT make up information or use knowledge outside the provided context
- Do NOT speculate or provide opinions

RECORD NAMING:
- Always use the precise record names from the context (e.g., "ACME Corp", "Enterprise Renewal Deal")
- When referring to people, use their full names as shown in the context
- Be consistent - if a record is called "ACME Corporation" in the context, don't shorten it to "ACME"
- This precision enables automatic hyperlinking in the interface

ANSWER STYLE:
- Be concise and direct
- Write naturally without citation markers
- Use bullet points for lists when appropriate
- Include relevant numbers and dates from the context
- Highlight key risks or blockers when present
- Focus on the most relevant information
- Mention record names naturally in your sentences
"""

    max_tokens = policy.get("max_tokens", DEFAULT_MAX_TOKENS)
    if max_tokens:
        prompt += f"- Keep your answer under {max_tokens} tokens\n"

    return prompt
```

### Deploy Backend Changes:

```bash
# Navigate to lambda directory
cd lambda/answer

# Build Docker image with updated code
docker build -t answer-lambda .

# Deploy to AWS (from project root)
cd ../..
npx cdk deploy SalesforceAISearch-Api-dev --require-approval never
```

---

## Step 2: Update the Frontend JavaScript (20 minutes)

### File: `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.js`

**Replace the `formattedAnswer` getter** with this enhanced version:

```javascript
get formattedAnswer() {
    if (!this.answer) return '';

    let formatted = this.answer;

    // Build name-to-ID map from citations
    const nameToId = {};
    const nameToSObject = {};

    if (this.citations && this.citations.length > 0) {
        // Sort by score to prioritize most relevant records for duplicate names
        const sortedCitations = [...this.citations].sort((a, b) => {
            const scoreA = parseFloat(b.score) || 0;
            const scoreB = parseFloat(a.score) || 0;
            return scoreB - scoreA;
        });

        sortedCitations.forEach(citation => {
            if (citation.title && citation.recordId) {
                // Only add if not already mapped (keeps highest score for duplicates)
                const normalizedTitle = citation.title.trim();
                if (!nameToId[normalizedTitle]) {
                    nameToId[normalizedTitle] = citation.recordId;
                    nameToSObject[normalizedTitle] = citation.sobject || 'Record';
                }
            }
        });
    }

    // Replace record names with hyperlinks
    Object.entries(nameToId).forEach(([name, recordId]) => {
        const sobject = nameToSObject[name];

        // Escape special regex characters in name
        const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

        // Create regex that matches the name as whole words
        const regex = new RegExp(`\\b(${escapedName})\\b`, 'g');

        // Replace with hyperlink, preserving the original text
        formatted = formatted.replace(regex, (match) => {
            return `<a href="#" data-recordid="${recordId}" data-sobject="${sobject}" class="slds-text-link record-link" title="View ${sobject}: ${name}">${match}</a>`;
        });
    });

    // Remove any remaining [Source: xxx] patterns (cleanup)
    formatted = formatted.replace(/\s*\[Source:\s*[^\]]+\]/g, '');

    // Convert line breaks to <br> tags
    formatted = formatted.replace(/\n/g, '<br/>');

    return formatted;
}
```

**Add/update the click handler**:

```javascript
handleAnswerLinkClick(event) {
    // Check if clicked element is a record link
    const recordLink = event.target.closest('.record-link');
    if (recordLink) {
        event.preventDefault();
        event.stopPropagation();

        const recordId = recordLink.dataset.recordid;
        const sobject = recordLink.dataset.sobject;
        const openInNewTab = event.ctrlKey || event.metaKey || event.shiftKey;

        if (recordId) {
            console.log(`Navigating to ${sobject} record: ${recordId}`);
            this.navigateToRecord(recordId, openInNewTab);
        }
    }
}
```

**Update the navigation method** (if not already present):

```javascript
navigateToRecord(recordId, openInNewTab = false) {
    if (!recordId) {
        console.error('No record ID provided for navigation');
        return;
    }

    // Validate Salesforce record ID format
    if (!/^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$/.test(recordId)) {
        console.error('Invalid Salesforce record ID format:', recordId);
        this.dispatchEvent(
            new ShowToastEvent({
                title: 'Navigation Error',
                message: 'Invalid record ID format',
                variant: 'error'
            })
        );
        return;
    }

    const config = {
        type: 'standard__recordPage',
        attributes: {
            recordId: recordId,
            actionName: 'view'
        }
    };

    if (openInNewTab) {
        // Generate URL and open in new tab
        this[NavigationMixin.GenerateUrl](config)
            .then(url => {
                window.open(url, '_blank');
            })
            .catch(error => {
                console.error('Navigation error:', error);
                this.dispatchEvent(
                    new ShowToastEvent({
                        title: 'Navigation Error',
                        message: 'Unable to open record in new tab',
                        variant: 'error'
                    })
                );
            });
    } else {
        // Navigate in same tab
        this[NavigationMixin.Navigate](config)
            .catch(error => {
                console.error('Navigation error:', error);
                this.dispatchEvent(
                    new ShowToastEvent({
                        title: 'Navigation Error',
                        message: 'Unable to navigate to record',
                        variant: 'error'
                    })
                );
            });
    }
}
```

---

## Step 3: Update the HTML Template (5 minutes)

### File: `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.html`

**Update the answer text section** (around line 147-150):

```html
<!-- Answer Text with clickable record names -->
<template if:false={isStreaming}>
    <div class="answer-text" role="article" aria-label="Generated answer" onclick={handleAnswerLinkClick}>
        <lightning-formatted-rich-text value={formattedAnswer}></lightning-formatted-rich-text>
    </div>
</template>
```

The key change is adding `onclick={handleAnswerLinkClick}` to the answer-text div.

---

## Step 4: Add CSS Styling (10 minutes)

### File: `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.css`

**Add these styles** to your existing CSS file:

```css
/* Record links - matching Salesforce native link style */
.record-link {
    color: #0070d2 !important;  /* Salesforce standard link blue */
    text-decoration: none !important;
    font-weight: inherit;
    cursor: pointer;
    border-bottom: 1px solid transparent;
    transition: all 0.1s ease;
    display: inline;
}

.record-link:hover {
    color: #005fb2 !important;
    text-decoration: underline !important;
}

.record-link:active {
    color: #00396b !important;
}

.record-link:focus {
    outline: 2px solid #1589ee;
    outline-offset: 1px;
    border-radius: 2px;
    text-decoration: underline !important;
}

.record-link:focus:not(:focus-visible) {
    outline: none;
}

/* Ensure links inside formatted rich text display correctly */
lightning-formatted-rich-text .record-link {
    display: inline !important;
}

/* Mobile/touch specific styles */
@media (pointer: coarse) {
    .record-link {
        padding: 2px 4px;
        margin: -2px -4px;
    }

    .record-link:active {
        background-color: rgba(0, 112, 210, 0.1);
        border-radius: 4px;
    }
}
```

---

## Step 5: Deploy to Salesforce (15 minutes)

```bash
# Deploy the updated LWC to your sandbox
sf project deploy start --source-dir salesforce/lwc/ascendixAiSearch --target-org ascendix-beta-sandbox

# Or deploy to production (when ready)
sf project deploy start --source-dir salesforce/lwc/ascendixAiSearch --target-org production
```

---

## Step 6: Testing (15 minutes)

### Test Scenarios:

1. **Basic Navigation**
   - Query: "Show me information about ACME Corp"
   - Expected: "ACME Corp" appears as blue hyperlink
   - Click → navigates to Account record

2. **Multiple Records**
   - Query: "Compare Enterprise Deal with Standard Package"
   - Expected: Both opportunity names are clickable
   - Each navigates to correct opportunity

3. **Keyboard Navigation**
   - Tab through the answer text
   - Press Enter on focused link → navigates
   - Press Ctrl+Enter → opens in new tab

4. **Mobile Testing**
   - Test on Salesforce Mobile App
   - Tap links → should navigate
   - Long press → should show context menu

5. **Edge Cases**
   - Records with special characters: "ACME (2024)"
   - Records with numbers: "Deal #12345"
   - Long record names

### Test Commands:

```bash
# Test the updated Lambda locally
curl -X POST "https://v2zweox56y5r6sdvlxnif3gzea0ffqow.lambda-url.us-west-2.on.aws/answer" \
  -H "x-api-key: M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Show me details about ACME Corp and their opportunities",
    "salesforceUserId": "005dl00000Q6a3RAAR",
    "policy": {
      "require_citations": false,
      "max_tokens": 300
    }
  }'
```

---

## Rollback Plan

If issues occur:

### Backend Rollback:
```bash
# Revert Lambda function to previous version
aws lambda update-function-code \
  --function-name salesforce-ai-search-answer-docker \
  --image-uri <previous-docker-image-uri>
```

### Frontend Rollback:
```bash
# Restore previous version from git
git checkout HEAD~1 -- salesforce/lwc/ascendixAiSearch/
sf project deploy start --source-dir salesforce/lwc/ascendixAiSearch --target-org ascendix-beta-sandbox
```

---

## Expected Results

### Before (with citations):
> The opportunity ACME Renewal [Source: 006xx1] is worth $2.5M and owned by John Smith [Source: 005xx2].

### After (natural hyperlinks):
> The opportunity <span style="color: #0070d2; text-decoration: underline;">ACME Renewal</span> is worth $2.5M and owned by <span style="color: #0070d2; text-decoration: underline;">John Smith</span>.

Where underlined text = clickable hyperlinks to respective records.

---

## Success Metrics

Track these after deployment:

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Link Generation Rate** | >90% | Records mentioned that become links |
| **Click-through Rate** | >40% | Users clicking on hyperlinks |
| **Navigation Success** | >98% | Successful navigations vs errors |
| **User Feedback** | Positive | Survey or feedback form |

---

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| **Links not appearing** | Check citations array is populated; verify record titles exist |
| **Partial name matches** | Ensure regex uses word boundaries (`\\b`) |
| **Duplicate names** | Sort by score, use highest relevance |
| **Special characters** | Escape regex characters in name |
| **Mobile not working** | Check touch event handlers, test in Salesforce app |

---

## Next Steps

After successful deployment:

1. **Monitor Usage**: Track click-through rates in CloudWatch
2. **Gather Feedback**: Survey 5-10 power users
3. **Iterate**:
   - Add hover preview cards (Phase 2)
   - Support partial name matching (Phase 3)
   - Add visual indicators for record type (icon prefix)

---

## Files Changed Summary

1. **Backend**: `lambda/answer/index.py` - System prompt update
2. **Frontend JS**: `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.js` - Name-to-ID mapping
3. **Frontend HTML**: `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.html` - Click handler
4. **Frontend CSS**: `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.css` - Link styling

Total implementation time: **1-2 hours**

---

## Questions or Issues?

- Backend issues: Check Lambda logs in CloudWatch
- Frontend issues: Use browser developer tools console
- Navigation issues: Verify record permissions in Salesforce

The implementation is straightforward and leverages existing infrastructure - the citations already provide name-to-ID mapping!