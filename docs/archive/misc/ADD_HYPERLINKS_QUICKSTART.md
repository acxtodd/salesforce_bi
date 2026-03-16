# Quick Implementation: Adding Hyperlinks to Search Results

## Summary
**What**: Make search result citations clickable to navigate directly to Salesforce records
**Effort**: 2-3 days
**Impact**: High - Reduces clicks by 50%+ for users accessing source records

## Good News 🎉
Most of the infrastructure is **already built**:
- ✅ NavigationMixin imported
- ✅ Record IDs available
- ✅ Navigation method exists (`navigateToRecord`)
- ✅ "View in Salesforce" button works

## Implementation Steps

### Step 1: Update Answer Formatting (30 minutes)

**File**: `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.js`

Replace the `formattedAnswer` getter:

```javascript
get formattedAnswer() {
    if (!this.answer) return '';

    // Replace [Source: RecordId] with clickable links
    let formatted = this.answer.replace(
        /\[Source:\s*([a-zA-Z0-9]{15,18})\]/g,
        '<a href="#" data-recordid="$1" class="citation-inline-link" title="View Record">[View →]</a>'
    );

    formatted = formatted.replace(/\n/g, '<br/>');
    return formatted;
}
```

### Step 2: Add Click Handler (20 minutes)

Add this method to handle clicks on citation links:

```javascript
handleAnswerLinkClick(event) {
    if (event.target.classList.contains('citation-inline-link')) {
        event.preventDefault();
        const recordId = event.target.dataset.recordid;
        const openInNewTab = event.ctrlKey || event.metaKey;

        if (recordId) {
            this.navigateToRecord(recordId, openInNewTab);
        }
    }
}
```

Update the existing `navigateToRecord` method:

```javascript
navigateToRecord(recordId, newTab = false) {
    const config = {
        type: 'standard__recordPage',
        attributes: {
            recordId: recordId,
            actionName: 'view'
        }
    };

    if (newTab) {
        this[NavigationMixin.GenerateUrl](config)
            .then(url => window.open(url, '_blank'))
            .catch(error => console.error('Navigation error:', error));
    } else {
        this[NavigationMixin.Navigate](config);
    }
}
```

### Step 3: Update Template (10 minutes)

**File**: `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.html`

Update the answer display div (around line 148):

```html
<!-- Change from -->
<div class="answer-text" role="article">
    <lightning-formatted-rich-text value={formattedAnswer}></lightning-formatted-rich-text>
</div>

<!-- Change to -->
<div class="answer-text" role="article" onclick={handleAnswerLinkClick}>
    <lightning-formatted-rich-text value={formattedAnswer}></lightning-formatted-rich-text>
</div>
```

### Step 4: Add Styling (10 minutes)

**File**: `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.css`

Add these styles:

```css
.citation-inline-link {
    color: #0070d2;
    text-decoration: none;
    border-bottom: 1px dashed #0070d2;
    padding: 0 4px;
    margin: 0 4px;
    cursor: pointer;
    font-weight: 500;
}

.citation-inline-link:hover {
    background-color: #f3f2f2;
    border-radius: 4px;
    border-bottom-style: solid;
}

.citation-inline-link:focus {
    outline: 2px solid #1589ee;
    outline-offset: 1px;
}
```

### Step 5: Deploy & Test (30 minutes)

```bash
# Deploy to sandbox
sf project deploy start --source-dir salesforce/lwc/ascendixAiSearch --target-org ascendix-beta-sandbox

# Test scenarios:
# 1. Click citation link → navigates to record
# 2. Ctrl+Click → opens in new tab
# 3. Invalid record ID → graceful handling
```

## Optional Enhancements

### Enhancement 1: Direct Links in Citations Drawer

Add navigation icons to each citation in the drawer:

```html
<!-- In citations drawer template -->
<div class="citation-item">
    <div class="slds-grid">
        <div class="slds-col slds-size_11-of-12">
            <!-- Existing citation content -->
        </div>
        <div class="slds-col slds-size_1-of-12">
            <lightning-button-icon
                icon-name="utility:new_window"
                title="Open in Salesforce"
                data-recordid={citation.recordId}
                onclick={handleQuickNavigate}>
            </lightning-button-icon>
        </div>
    </div>
</div>
```

### Enhancement 2: Smart Object Detection

Detect object type from record ID prefix:

```javascript
getObjectTypeFromId(recordId) {
    const prefix = recordId.substring(0, 3);
    const objectMap = {
        '001': 'Account',
        '003': 'Contact',
        '005': 'User',
        '006': 'Opportunity',
        '500': 'Case',
        'a0a': 'Property__c',
        'a0b': 'Lease__c'
    };
    return objectMap[prefix] || 'Record';
}
```

### Enhancement 3: User Preferences

Save navigation preference (same tab vs new tab):

```javascript
connectedCallback() {
    // Load preference
    this.navPreference = localStorage.getItem('ai-search-nav-pref') || 'same-tab';
}

savePreference(preference) {
    localStorage.setItem('ai-search-nav-pref', preference);
    this.navPreference = preference;
}
```

## Testing Checklist

- [ ] Citation links appear in answer text
- [ ] Clicking link navigates to record
- [ ] Ctrl/Cmd+Click opens new tab
- [ ] Invalid IDs handled gracefully
- [ ] Works on mobile (Salesforce app)
- [ ] Screen reader compatible
- [ ] Keyboard navigation works

## Rollback Plan

If issues occur, revert by:
1. Remove `onclick` handler from template
2. Restore original `formattedAnswer` getter
3. Redeploy original version

## Success Metrics

Track these after deployment:
- Citation click rate (target: >30%)
- Navigation errors (target: <2%)
- User feedback scores
- Time to information reduction

## Common Issues & Fixes

| Issue | Solution |
|-------|----------|
| Links not clickable | Check CSS z-index, ensure onclick handler is attached |
| Navigation fails | Verify NavigationMixin import, check record permissions |
| New tab blocked | Browser popup blocker - add site to allowed list |
| Mobile not working | Test in Salesforce Mobile App, may need touch event handlers |

## Code Review Checklist

- [ ] NavigationMixin properly imported
- [ ] Error handling for invalid IDs
- [ ] Accessibility attributes (aria-label)
- [ ] CSS follows SLDS guidelines
- [ ] No console errors
- [ ] Unit tests updated

## Questions?

Contact points for help:
- Architecture questions: See `/docs/design/HYPERLINK_NAVIGATION_DESIGN.md`
- Salesforce navigation: [Lightning Navigation docs](https://developer.salesforce.com/docs/component-library/documentation/en/lwc/use_navigate)
- CSS/styling: [SLDS documentation](https://www.lightningdesignsystem.com)

---

**Total Implementation Time: ~2-3 hours for basic functionality**

The feature is low-risk since it builds on existing navigation code. Start with basic inline links, then add enhancements based on user feedback.