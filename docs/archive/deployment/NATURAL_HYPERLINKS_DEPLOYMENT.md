# Natural Hyperlinks Deployment Checklist

## Pre-Deployment Verification

- [ ] Backup current Lambda function version
- [ ] Backup current LWC code in Salesforce
- [ ] Notify users of upcoming change (optional)

---

## Backend Deployment (Lambda)

### Step 1: Update System Prompt
- [ ] Copy new `_build_system_prompt` function from `lambda/answer/index_updated.py`
- [ ] Replace function in `lambda/answer/index.py` (lines 157-199)
- [ ] Verify no syntax errors

### Step 2: Build Docker Image
```bash
cd lambda/answer
docker build -t answer-lambda .
```
- [ ] Build completes without errors
- [ ] Image tagged correctly

### Step 3: Deploy to AWS
```bash
cd ../..  # Return to project root
npx cdk deploy SalesforceAISearch-Api-dev --require-approval never
```
- [ ] CDK deployment successful
- [ ] Lambda function updated
- [ ] No errors in CloudWatch logs

### Step 4: Test Lambda
```bash
python3 test_automation/test_natural_hyperlinks.py
```
- [ ] Natural text (no [Source:] markers)
- [ ] Citations still returned in metadata
- [ ] Record names present in answer

---

## Frontend Deployment (Salesforce)

### Step 1: Update JavaScript
- [ ] Copy `formattedAnswer` getter from `ascendixAiSearch_updated.js`
- [ ] Copy `handleAnswerLinkClick` method
- [ ] Copy `navigateToRecord` method
- [ ] Add to `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.js`

### Step 2: Update HTML Template
- [ ] Add `onclick={handleAnswerLinkClick}` to answer-text div
- [ ] Located around line 148 in `ascendixAiSearch.html`

### Step 3: Update CSS
- [ ] Copy styles from `ascendixAiSearch_styles.css`
- [ ] Add to existing `ascendixAiSearch.css` file
- [ ] Verify no conflicting styles

### Step 4: Deploy to Sandbox
```bash
sf project deploy start \
  --source-dir salesforce/lwc/ascendixAiSearch \
  --target-org ascendix-beta-sandbox
```
- [ ] Deployment successful
- [ ] No errors or warnings

---

## Post-Deployment Testing

### In Salesforce UI:

#### Test 1: Basic Link Generation
- [ ] Run query: "What are the details for ACME Corp?"
- [ ] Record names appear as blue links
- [ ] No [Source:] text visible

#### Test 2: Click Navigation
- [ ] Click on record name → navigates to record
- [ ] Ctrl+Click → opens in new tab
- [ ] Invalid record → shows error message

#### Test 3: Multiple Records
- [ ] Query mentioning multiple records
- [ ] All record names are linkable
- [ ] Each navigates to correct record

#### Test 4: Mobile Testing
- [ ] Test in Salesforce Mobile App
- [ ] Links are tappable
- [ ] Navigation works

#### Test 5: Accessibility
- [ ] Tab key navigates to links
- [ ] Enter key activates link
- [ ] Screen reader announces links

---

## Monitoring (First 24 Hours)

### CloudWatch Metrics:
- [ ] Lambda execution errors < 1%
- [ ] Response times < 2s P95
- [ ] No memory issues

### User Feedback:
- [ ] No complaints about missing citations
- [ ] Users discovering and using links
- [ ] Positive feedback on cleaner text

---

## Production Deployment (After Successful Sandbox Testing)

### Prerequisites:
- [ ] Sandbox testing complete (minimum 2 days)
- [ ] Stakeholder approval obtained
- [ ] Deployment window scheduled

### Deploy to Production:
```bash
# Deploy Lambda (if using production environment)
npx cdk deploy SalesforceAISearch-Api-prod --require-approval never

# Deploy LWC to production
sf project deploy start \
  --source-dir salesforce/lwc/ascendixAiSearch \
  --target-org production
```

---

## Rollback Procedure (If Needed)

### Backend Rollback:
```bash
# Get previous version ARN
aws lambda list-versions-by-function \
  --function-name salesforce-ai-search-answer-docker \
  --region us-west-2

# Update alias to previous version
aws lambda update-alias \
  --function-name salesforce-ai-search-answer-docker \
  --function-version <previous-version-number> \
  --name PROD
```

### Frontend Rollback:
```bash
# Revert to previous commit
git checkout HEAD~1 -- salesforce/lwc/ascendixAiSearch/

# Deploy reverted version
sf project deploy start \
  --source-dir salesforce/lwc/ascendixAiSearch \
  --target-org ascendix-beta-sandbox
```

---

## Success Criteria

### Immediate (Day 1):
- ✅ No citation markers in text
- ✅ Record names are clickable
- ✅ Navigation works
- ✅ No JavaScript errors

### Short-term (Week 1):
- ✅ >30% click-through rate on links
- ✅ <2% error rate
- ✅ Positive user feedback
- ✅ No performance degradation

### Long-term (Month 1):
- ✅ Reduced time to information
- ✅ Increased user satisfaction
- ✅ Feature adoption >80%

---

## Communication Plan

### Before Deployment:
```
Subject: AI Search Enhancement - Clickable Record Names

Team,

We're enhancing the AI Search to make record names clickable, just like native Salesforce.

What's changing:
• Record names (like "ACME Corp") will appear as blue links
• Click to navigate directly to the record
• Ctrl+Click to open in a new tab
• Cleaner text without citation markers

When: [Date/Time]
Impact: Minimal - UI enhancement only

Questions? Reply to this email.
```

### After Deployment:
```
Subject: AI Search Update Complete - Record Names Now Clickable

The update is complete! Record names in AI Search answers are now clickable hyperlinks.

Try it out:
1. Search for any record
2. Click on blue record names to navigate
3. Use Ctrl+Click for new tab

Feedback welcome!
```

---

## Files Modified Checklist

Backend:
- [ ] `lambda/answer/index.py` - System prompt
- [ ] Tested with `test_natural_hyperlinks.py`

Frontend:
- [ ] `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.js`
- [ ] `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.html`
- [ ] `salesforce/lwc/ascendixAiSearch/ascendixAiSearch.css`

Documentation:
- [ ] Implementation guide created
- [ ] Deployment checklist created
- [ ] Test results documented

---

## Sign-off

- [ ] Development Complete - Developer: __________ Date: __________
- [ ] Testing Complete - QA: __________ Date: __________
- [ ] Deployment Approved - Manager: __________ Date: __________
- [ ] Production Deployed - DevOps: __________ Date: __________

---

**Estimated Total Time**: 1-2 hours for implementation and deployment