# Fix: Markdown Text Showing Instead of Formatted HTML

## Problem
The AI response is showing raw markdown syntax (`**text**`, `##`, etc.) instead of properly formatted HTML.

## Root Cause
The `lightning-formatted-rich-text` component expects HTML but the system is outputting markdown format.

## Quick Solution

### Step 1: Update the formattedAnswer getter

Replace the existing `formattedAnswer` getter in `ascendixAiSearch.js` with this version that includes markdown-to-HTML conversion:

```javascript
get formattedAnswer() {
    if (!this.answer) return '';

    let formatted = this.answer;

    // === MARKDOWN TO HTML CONVERSION ===

    // Convert headers
    formatted = formatted.replace(/^### (.*?)$/gm, '<h4>$1</h4>');
    formatted = formatted.replace(/^## (.*?)$/gm, '<h3>$1</h3>');
    formatted = formatted.replace(/^# (.*?)$/gm, '<h3>$1</h3>');

    // Convert bold text
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Convert italic text (single asterisk)
    formatted = formatted.replace(/(?<!\*)\*(?!\*)([^*]+)\*(?!\*)/g, '<em>$1</em>');

    // Convert numbered lists
    let listCounter = 0;
    formatted = formatted.replace(/^(\d+)\.\s+(.*)$/gm, function(match, num, text) {
        if (num === '1') {
            listCounter = 1;
            return '<ol><li>' + text + '</li>';
        } else {
            listCounter++;
            return '<li>' + text + '</li>';
        }
    });

    // Close ordered lists
    formatted = formatted.replace(/(<li>.*?<\/li>)(\n(?!\s*<li>))/g, '$1</ol>$2');

    // Convert bullet lists
    formatted = formatted.replace(/^- (.*)$/gm, '<ul><li>$1</li></ul>');

    // Merge consecutive ul tags
    formatted = formatted.replace(/<\/ul>\n<ul>/g, '\n');

    // === HYPERLINK CONVERSION (existing code) ===

    // Build name-to-ID map from citations
    const nameToId = {};
    const nameToSObject = {};

    if (this.citations && this.citations.length > 0) {
        const sortedCitations = [...this.citations].sort((a, b) => {
            const scoreA = parseFloat(b.score) || 0;
            const scoreB = parseFloat(a.score) || 0;
            return scoreB - scoreA;
        });

        sortedCitations.forEach(citation => {
            if (citation.title && citation.recordId) {
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
        const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`\\b(${escapedName})\\b`, 'g');

        formatted = formatted.replace(regex, (match) => {
            return `<a href="#" data-recordid="${recordId}" data-sobject="${sobject}" class="slds-text-link record-link" title="View ${sobject}: ${name}">${match}</a>`;
        });
    });

    // Remove any [Source: xxx] patterns
    formatted = formatted.replace(/\[Source:\s*[^\]]+\]/g, '');

    // Convert line breaks to <br>
    formatted = formatted.replace(/\n/g, '<br/>');

    // Clean up formatting
    formatted = formatted.replace(/<\/(h[1-6]|ul|ol)><br\/>/g, '</$1>');
    formatted = formatted.replace(/<br\/><(h[1-6]|ul|ol)/g, '<$1');

    return formatted;
}
```

### Step 2: Deploy the Fix

```bash
# Deploy to sandbox
sf project deploy start --source-dir salesforce/lwc/ascendixAiSearch --target-org ascendix-beta-sandbox
```

## Testing

After deployment, the output should show:

### Before (Raw Markdown):
```
## Top Office Property Deals

1. **Dallas Office Investors** - $112,500.00 gross fee
- Status: Open, Sales Stage: Underwriting
[Source: ascendix__Deal__c/a0Pfk000000CkaEEAS]
```

### After (Formatted HTML):
> ## Top Office Property Deals
>
> 1. **Dallas Office Investors** - $112,500.00 gross fee
>    - Status: Open, Sales Stage: Underwriting

With proper formatting:
- Headers displayed as headers
- Bold text properly bolded
- Lists properly formatted
- Record names as clickable links

## Alternative: Minimal Fix

If you just want to fix the most common issues quickly:

```javascript
get formattedAnswer() {
    if (!this.answer) return '';

    let formatted = this.answer;

    // Quick fixes for most common markdown
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>'); // Bold
    formatted = formatted.replace(/^## (.*?)$/gm, '<h3>$1</h3>'); // Headers
    formatted = formatted.replace(/^# (.*?)$/gm, '<h3>$1</h3>');  // Headers
    formatted = formatted.replace(/^\d+\. /gm, '• ');              // Convert numbers to bullets
    formatted = formatted.replace(/^- /gm, '• ');                  // Bullets
    formatted = formatted.replace(/\[Source:.*?\]/g, '');          // Remove sources
    formatted = formatted.replace(/\n/g, '<br/>');                 // Line breaks

    return formatted;
}
```

## Permanent Solution

Consider using a proper markdown parser library if complex markdown is expected:

1. **markdown-it** - Lightweight parser
2. **marked** - Fast and feature-rich
3. **showdown** - Bidirectional converter

For Salesforce LWC, you'd need to include as a static resource.

## Deployment Checklist

- [ ] Update `formattedAnswer` getter
- [ ] Test with various markdown formats
- [ ] Deploy to sandbox
- [ ] Verify formatting displays correctly
- [ ] Test hyperlinks still work
- [ ] Deploy to production

## Common Markdown Patterns to Handle

| Markdown | HTML | Example |
|----------|------|---------|
| `**text**` | `<strong>text</strong>` | **bold text** |
| `*text*` | `<em>text</em>` | *italic* |
| `## Header` | `<h3>Header</h3>` | Header |
| `1. Item` | `<ol><li>Item</li></ol>` | Numbered list |
| `- Item` | `<ul><li>Item</li></ul>` | Bullet list |
| `[Source: id]` | (remove) | Citation removal |

---

**Time to Fix**: 5-10 minutes