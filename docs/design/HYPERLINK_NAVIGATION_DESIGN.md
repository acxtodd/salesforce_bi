# Hyperlink Navigation Design for Search Results
**Date**: November 25, 2025
**Feature**: Making search results clickable with direct navigation to Salesforce records
**Status**: Design Proposal

---

## Executive Summary

This document outlines the design and implementation effort required to enhance search results with clickable hyperlinks that navigate directly to Salesforce records. The good news is that **much of the infrastructure is already in place** - we just need to extend and polish it.

**Effort Estimate**: **2-3 days** of development

---

## Current State Analysis

### ✅ What's Already Working

1. **NavigationMixin** is imported and configured
2. **Record IDs** are available in citation metadata
3. **Navigation method** (`navigateToRecord`) exists
4. **"View in Salesforce"** button works in preview modal
5. **Citation data structure** includes:
   - `recordId` (15/18 char Salesforce ID)
   - `sobject` (object type)
   - `title` (record name)
   - `snippet` (preview text)

### ⚠️ What's Missing

1. **Inline hyperlinks** in the answer text
2. **Direct citation links** in the citations drawer
3. **New tab/window** option for navigation
4. **Visual indicators** for clickable elements
5. **Accessibility** improvements for screen readers
6. **Error handling** for invalid record IDs

---

## Proposed Design

### 1. Hyperlink Locations

#### A. **In-Answer Citations** (Priority 1)
Transform `[Source: RecordId]` references into clickable links directly in the answer text.

**Current**:
```html
The top opportunity is ACME Renewal [Source: 006xx000001ABC]
```

**Proposed**:
```html
The top opportunity is ACME Renewal <a href="#" data-recordid="006xx000001ABC"
  class="citation-link" title="View Opportunity">[View Record →]</a>
```

#### B. **Citations Drawer** (Priority 2)
Make citation titles clickable to navigate directly to records.

**Current**: Citation titles open preview modal
**Proposed**: Add direct navigation option with icon

#### C. **Action Results** (Priority 3)
Already has record links, just needs enhancement for better UX.

### 2. Navigation Options

#### **Option A: Same Tab (Default)**
```javascript
this[NavigationMixin.Navigate]({
    type: 'standard__recordPage',
    attributes: {
        recordId: recordId,
        actionName: 'view'
    }
});
```

#### **Option B: New Tab/Window**
```javascript
this[NavigationMixin.GenerateUrl]({
    type: 'standard__recordPage',
    attributes: {
        recordId: recordId,
        actionName: 'view'
    }
}).then(url => {
    window.open(url, '_blank');
});
```

#### **Option C: User Preference**
Add a setting to let users choose their preferred navigation behavior.

### 3. Visual Design

#### **Link Styling**
```css
.citation-link {
    color: #0070d2; /* Salesforce blue */
    text-decoration: none;
    border-bottom: 1px dashed #0070d2;
    cursor: pointer;
    transition: all 0.2s ease;
}

.citation-link:hover {
    color: #005fb2;
    border-bottom-style: solid;
    background-color: #f3f2f2;
    padding: 2px 4px;
    border-radius: 4px;
}

.citation-link:focus {
    outline: 2px solid #1589ee;
    outline-offset: 2px;
}

/* Icon indicator */
.citation-link::after {
    content: '↗';
    margin-left: 4px;
    font-size: 0.875em;
}
```

#### **Citation Card Enhancement**
```html
<div class="citation-item">
    <div class="citation-header">
        <span class="citation-title">{citation.title}</span>
        <button class="slds-button slds-button_icon"
                title="Open in Salesforce"
                onclick={navigateToRecord}>
            <lightning-icon icon-name="utility:new_window"
                           size="x-small"></lightning-icon>
        </button>
    </div>
    <!-- Rest of citation content -->
</div>
```

---

## Implementation Plan

### Phase 1: Core Functionality (Day 1)

#### 1.1 Update Answer Formatting
**File**: `ascendixAiSearch.js`
```javascript
get formattedAnswer() {
    if (!this.answer) return '';

    // Enhanced citation replacement with proper record links
    let formatted = this.answer.replace(
        /\[Source:\s*([a-zA-Z0-9]{15,18})\]/g,
        (match, recordId) => {
            // Detect object type from ID prefix
            const objectType = this.getObjectTypeFromId(recordId);
            return `<a href="#" data-recordid="${recordId}"
                      data-objecttype="${objectType}"
                      class="citation-inline-link"
                      title="View ${objectType} Record">[View →]</a>`;
        }
    );

    formatted = formatted.replace(/\n/g, '<br/>');
    return formatted;
}

getObjectTypeFromId(recordId) {
    const prefix = recordId.substring(0, 3);
    const objectMap = {
        '001': 'Account',
        '003': 'Contact',
        '005': 'User',
        '006': 'Opportunity',
        '500': 'Case',
        '002': 'Note',
        'a0a': 'Property__c',
        'a0b': 'Lease__c',
        'a0c': 'Contract__c'
    };
    return objectMap[prefix] || 'Record';
}
```

#### 1.2 Add Click Handler
**File**: `ascendixAiSearch.js`
```javascript
handleAnswerLinkClick(event) {
    event.preventDefault();
    const recordId = event.target.dataset.recordid;
    const openInNewTab = event.ctrlKey || event.metaKey; // Ctrl/Cmd+Click

    if (recordId) {
        this.navigateToRecord(recordId, openInNewTab);
    }
}

navigateToRecord(recordId, newTab = false) {
    const config = {
        type: 'standard__recordPage',
        attributes: {
            recordId: recordId,
            actionName: 'view'
        }
    };

    if (newTab) {
        // Generate URL and open in new tab
        this[NavigationMixin.GenerateUrl](config)
            .then(url => {
                window.open(url, '_blank');
            })
            .catch(error => {
                this.showToast('Error', 'Unable to open record', 'error');
                console.error('Navigation error:', error);
            });
    } else {
        // Navigate in same tab
        this[NavigationMixin.Navigate](config);
    }
}
```

#### 1.3 Update Template
**File**: `ascendixAiSearch.html`
```html
<!-- Update answer display to handle clicks -->
<div class="answer-text" onclick={handleAnswerLinkClick}>
    <lightning-formatted-rich-text value={formattedAnswer}>
    </lightning-formatted-rich-text>
</div>
```

### Phase 2: Enhanced Citations (Day 2)

#### 2.1 Citation Drawer Updates
**File**: `ascendixAiSearch.html`
```html
<div class="citation-item slds-box slds-m-bottom_small">
    <div class="slds-grid slds-grid_vertical-align-center">
        <div class="slds-col slds-size_11-of-12">
            <div class="citation-header">
                <button class="citation-title-link"
                        data-recordid={citation.recordId}
                        onclick={handleCitationTitleClick}>
                    {citation.title}
                </button>
                <span class="slds-badge slds-m-left_x-small">
                    {citation.sobject}
                </span>
            </div>
            <div class="citation-snippet">{citation.snippet}</div>
        </div>
        <div class="slds-col slds-size_1-of-12 slds-text-align_right">
            <lightning-button-icon
                icon-name="utility:new_window"
                alternative-text="Open in Salesforce"
                title="Open in Salesforce"
                data-recordid={citation.recordId}
                onclick={handleQuickNavigate}>
            </lightning-button-icon>
        </div>
    </div>
</div>
```

#### 2.2 Add Navigation Methods
**File**: `ascendixAiSearch.js`
```javascript
handleCitationTitleClick(event) {
    event.preventDefault();
    const recordId = event.target.dataset.recordid;
    this.navigateToRecord(recordId, false);
}

handleQuickNavigate(event) {
    const recordId = event.currentTarget.dataset.recordid;
    this.navigateToRecord(recordId, true); // Always new tab for quick nav
}
```

### Phase 3: Polish & Accessibility (Day 3)

#### 3.1 Add User Preferences
**File**: `ascendixAiSearch.js`
```javascript
@api navigationPreference = 'same-tab'; // 'same-tab' or 'new-tab'

connectedCallback() {
    // Load user preference from localStorage
    const savedPref = localStorage.getItem('ai-search-nav-preference');
    if (savedPref) {
        this.navigationPreference = savedPref;
    }
}

handleNavigationPreferenceChange(event) {
    this.navigationPreference = event.detail.value;
    localStorage.setItem('ai-search-nav-preference', this.navigationPreference);
}
```

#### 3.2 Accessibility Improvements
```javascript
// Add ARIA attributes
handleAnswerLinkClick(event) {
    if (event.target.classList.contains('citation-inline-link')) {
        event.preventDefault();

        // Announce navigation to screen readers
        this.announceToScreenReader(`Navigating to ${event.target.dataset.objecttype}`);

        const recordId = event.target.dataset.recordid;
        this.navigateToRecord(recordId);
    }
}

announceToScreenReader(message) {
    const announcement = this.template.querySelector('[aria-live="polite"]');
    if (announcement) {
        announcement.textContent = message;
        setTimeout(() => {
            announcement.textContent = '';
        }, 1000);
    }
}
```

#### 3.3 Error Handling
```javascript
async navigateToRecord(recordId, newTab = false) {
    try {
        // Validate record ID format
        if (!this.isValidRecordId(recordId)) {
            throw new Error('Invalid record ID format');
        }

        // Check if user has access (optional API call)
        const hasAccess = await this.checkRecordAccess(recordId);
        if (!hasAccess) {
            this.showToast('Access Denied',
                          'You do not have permission to view this record',
                          'warning');
            return;
        }

        // Navigate as before
        const config = {
            type: 'standard__recordPage',
            attributes: {
                recordId: recordId,
                actionName: 'view'
            }
        };

        // ... rest of navigation logic
    } catch (error) {
        console.error('Navigation error:', error);
        this.showToast('Navigation Error',
                      'Unable to open record. Please try again.',
                      'error');
    }
}

isValidRecordId(recordId) {
    // Salesforce ID validation regex
    return /^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$/.test(recordId);
}
```

---

## Testing Requirements

### Functional Tests
1. ✅ Click citation link in answer → navigates to record
2. ✅ Ctrl+Click citation → opens in new tab
3. ✅ Click citation title → navigates to record
4. ✅ Click "new window" icon → opens in new tab
5. ✅ Invalid record ID → shows error message
6. ✅ No permission → shows access denied message

### Browser Compatibility
- ✅ Chrome (latest)
- ✅ Safari (latest)
- ✅ Firefox (latest)
- ✅ Edge (latest)
- ✅ Salesforce Mobile App

### Accessibility Tests
- ✅ Keyboard navigation (Tab, Enter)
- ✅ Screen reader announcements
- ✅ Focus indicators
- ✅ ARIA labels

---

## Rollout Strategy

### Phase 1: Beta Testing (Week 1)
- Deploy to sandbox
- Test with 5-10 power users
- Gather feedback on navigation preferences

### Phase 2: Production (Week 2)
- Deploy to production
- Monitor click-through rates
- Track navigation errors

### Phase 3: Enhancements (Week 3+)
- Add hover preview cards
- Implement batch navigation (open multiple)
- Add navigation history

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|------------|
| **Click-through Rate** | >30% | Citations clicked / Citations shown |
| **Navigation Success** | >95% | Successful navigations / Total clicks |
| **Error Rate** | <2% | Navigation errors / Total attempts |
| **User Satisfaction** | >4/5 | Post-implementation survey |

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| **Permission Errors** | Medium | Pre-check access, graceful error handling |
| **Performance Impact** | Low | Lazy load navigation module |
| **Mobile Compatibility** | Medium | Extensive mobile testing |
| **User Confusion** | Low | Clear visual indicators, tooltips |

---

## Alternative Approaches Considered

### 1. **Hover Cards** (Rejected - Too Complex)
Show record preview on hover without navigation.
- **Pros**: Rich preview without leaving page
- **Cons**: Complex implementation, performance concerns

### 2. **Inline Frames** (Rejected - Security)
Embed record details in iframes.
- **Pros**: No navigation needed
- **Cons**: Security restrictions, poor mobile experience

### 3. **Batch Actions** (Future Enhancement)
Select multiple citations to open at once.
- **Pros**: Efficiency for power users
- **Cons**: Browser popup blockers

---

## Conclusion

Adding hyperlink navigation to search results is a **high-value, low-effort enhancement** that will significantly improve user experience. With most of the infrastructure already in place, this can be implemented in **2-3 days** with minimal risk.

### Recommended Approach
1. Start with Phase 1 (inline citation links)
2. Gather user feedback
3. Iterate with Phase 2 enhancements
4. Consider advanced features based on usage data

The implementation is straightforward, builds on existing code, and provides immediate value to users by reducing the clicks needed to navigate to relevant records.

---

## Appendix: Code Examples

### Complete Navigation Handler
```javascript
/**
 * Enhanced navigation handler with all features
 */
navigateToRecord(recordId, options = {}) {
    const {
        newTab = false,
        showToast = true,
        validateAccess = false
    } = options;

    // Build navigation config
    const config = {
        type: 'standard__recordPage',
        attributes: {
            recordId: recordId,
            actionName: 'view'
        }
    };

    // Handle navigation
    if (newTab || this.navigationPreference === 'new-tab') {
        this[NavigationMixin.GenerateUrl](config)
            .then(url => {
                window.open(url, '_blank');
                if (showToast) {
                    this.showToast('Success', 'Opening record in new tab', 'success');
                }
            })
            .catch(error => {
                console.error('Navigation error:', error);
                if (showToast) {
                    this.showToast('Error', 'Unable to open record', 'error');
                }
            });
    } else {
        this[NavigationMixin.Navigate](config);
    }
}
```

### CSS Styling
```css
/* ascendixAiSearch.css */
.citation-inline-link {
    color: var(--lwc-colorTextBrand);
    text-decoration: none;
    border-bottom: 1px dashed var(--lwc-colorTextBrand);
    padding: 0 4px;
    margin: 0 4px;
    transition: all 0.2s ease;
    cursor: pointer;
    font-weight: 500;
}

.citation-inline-link:hover {
    background-color: var(--lwc-colorBackgroundHighlight);
    border-radius: 4px;
    border-bottom-style: solid;
}

.citation-inline-link:focus {
    outline: 2px solid var(--lwc-colorBorderBrandPrimary);
    outline-offset: 1px;
    border-radius: 4px;
}

.citation-title-link {
    color: var(--lwc-colorTextActionLabel);
    text-decoration: none;
    font-weight: 600;
    cursor: pointer;
    background: none;
    border: none;
    padding: 0;
    text-align: left;
}

.citation-title-link:hover {
    text-decoration: underline;
    color: var(--lwc-colorTextActionLabelActive);
}
```