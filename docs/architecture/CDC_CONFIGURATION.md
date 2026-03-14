# Salesforce CDC Configuration Guide

## Overview

This guide provides step-by-step instructions for configuring Salesforce Change Data Capture (CDC) for the AI Search POC. CDC enables near real-time data synchronization from Salesforce to AWS, supporting the 5-minute P50 freshness target.

## Prerequisites

- Salesforce org with API access
- System Administrator or equivalent permissions
- CDC feature enabled (available in Enterprise, Performance, Unlimited, and Developer editions)

## Supported Objects

The POC supports CDC for the following objects:
- **Standard Objects**: Account, Opportunity, Case, Note
- **Custom Objects**: Property__c, Lease__c, Contract__c

## Step 1: Enable Change Data Capture

### Via Setup UI

1. Navigate to **Setup** → **Integrations** → **Change Data Capture**
2. Click **Edit** to modify CDC settings
3. Select the following objects from the **Available Entities** list:
   - Account
   - Opportunity
   - Case
   - Note
   - Property__c
   - Lease__c
   - Contract__c
4. Move selected objects to **Selected Entities** using the arrow button
5. Click **Save**

### Via Metadata API (Recommended for Automation)

Create a file `package.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Package xmlns="http://soap.sforce.com/2006/04/metadata">
    <types>
        <members>AccountChangeEvent</members>
        <members>OpportunityChangeEvent</members>
        <members>CaseChangeEvent</members>
        <members>NoteChangeEvent</members>
        <members>Property__ChangeEvent</members>
        <members>Lease__ChangeEvent</members>
        <members>Contract__ChangeEvent</members>
        <name>PlatformEventChannel</name>
    </types>
    <version>59.0</version>
</Package>
```

Deploy using SFDX:
```bash
sfdx force:source:deploy -x package.xml
```

## Step 2: Configure Change Event Channels

### Create Custom Channel (Optional)

For better control and isolation, create a custom change event channel:

1. Navigate to **Setup** → **Platform Events** → **Change Event Channels**
2. Click **New Change Event Channel**
3. Configure:
   - **Label**: AI Search CDC Channel
   - **API Name**: AI_Search_CDC_Channel__chn
   - **Description**: Change events for AI Search ingestion pipeline
4. Click **Save**

### Add Objects to Custom Channel

1. Open the newly created channel
2. Click **Edit**
3. Add the following change events:
   - AccountChangeEvent
   - OpportunityChangeEvent
   - CaseChangeEvent
   - NoteChangeEvent
   - Property__ChangeEvent
   - Lease__ChangeEvent
   - Contract__ChangeEvent
4. Click **Save**

### Using Default Channel

Alternatively, use the default `/data/ChangeEvents` channel which includes all enabled CDC objects.

## Step 3: Verify CDC Configuration

### Test CDC Events

1. Navigate to **Setup** → **Integrations** → **Change Data Capture**
2. Verify all 7 objects appear in **Selected Entities**
3. Create or update a test record in one of the enabled objects
4. Use Workbench or Developer Console to subscribe to change events:

```apex
// Developer Console → Debug → Open Execute Anonymous Window
EventBus.TriggerContext ctx = EventBus.TriggerContext.currentContext();
System.debug('Trigger context: ' + ctx);
```

### Monitor Change Events

Use the Event Monitor in Setup:
1. Navigate to **Setup** → **Event Monitoring** → **Event Log File**
2. Filter by **Event Type**: ChangeDataCapture
3. Verify events are being generated for test record changes

## Step 4: Configure API Access for AppFlow

### Create Connected App

1. Navigate to **Setup** → **App Manager** → **New Connected App**
2. Configure:
   - **Connected App Name**: AI Search AppFlow Integration
   - **API Name**: AI_Search_AppFlow_Integration
   - **Contact Email**: your-email@example.com
   - **Enable OAuth Settings**: Checked
   - **Callback URL**: `https://console.aws.amazon.com/appflow/oauth`
   - **Selected OAuth Scopes**:
     - Access and manage your data (api)
     - Perform requests on your behalf at any time (refresh_token, offline_access)
     - Access your basic information (id, profile, email, address, phone)
   - **Require Secret for Web Server Flow**: Checked
3. Click **Save**
4. Click **Continue**
5. Note the **Consumer Key** and **Consumer Secret** (needed for AppFlow configuration)

### Assign Permission Set

1. Navigate to **Setup** → **Permission Sets** → **New**
2. Configure:
   - **Label**: AI Search CDC Access
   - **API Name**: AI_Search_CDC_Access
3. Click **Save**
4. Add permissions:
   - **Object Settings** → Select each object → Enable **Read** access
   - **System Permissions** → Enable:
     - API Enabled
     - View All Data (or specific object permissions)
5. Assign permission set to the integration user

## Step 5: Document Configuration

Record the following information for AppFlow setup:

- **Salesforce Instance URL**: `https://your-instance.salesforce.com`
- **Connected App Consumer Key**: `[from Step 4]`
- **Connected App Consumer Secret**: `[from Step 4]`
- **CDC Channel**: `/data/ChangeEvents` or `/data/AI_Search_CDC_Channel__chn`
- **Enabled Objects**: Account, Opportunity, Case, Note, Property__c, Lease__c, Contract__c

## Troubleshooting

### CDC Events Not Appearing

**Issue**: Change events are not being published after record updates.

**Solutions**:
1. Verify CDC is enabled for the object in Setup
2. Check that the object has been saved to **Selected Entities**
3. Ensure the user making changes has API access
4. Wait up to 1 minute for CDC events to appear (not instant)
5. Check Event Log Files for errors

### Permission Errors

**Issue**: AppFlow cannot subscribe to change events.

**Solutions**:
1. Verify Connected App has correct OAuth scopes
2. Ensure integration user has the AI Search CDC Access permission set
3. Check that API access is enabled for the user's profile
4. Verify the user has Read access to all enabled objects

### Custom Object CDC Not Working

**Issue**: Custom object change events are not being captured.

**Solutions**:
1. Verify custom object API name ends with `__c`
2. Check that CDC is supported for the custom object (must have API access enabled)
3. Ensure the custom object is deployed and active
4. Re-save the CDC configuration after deploying custom objects

## Performance Considerations

### CDC Event Volume

- Each record change generates one CDC event
- Bulk operations generate one event per record
- Monitor event volume in Event Log Files
- Consider rate limits: 10,000 events per hour per org (default)

### Event Delivery

- CDC events are delivered in near real-time (typically < 1 second)
- Events are retained for 3 days
- AppFlow polls for events every 1-5 minutes (configurable)
- Total P50 latency target: 5 minutes (includes AppFlow polling + processing)

## Next Steps

After completing CDC configuration:
1. Proceed to **Task 8.2**: Set up Amazon AppFlow for CDC streaming
2. Configure AppFlow connection using the Connected App credentials
3. Test end-to-end CDC flow from Salesforce to S3

## References

- [Salesforce CDC Developer Guide](https://developer.salesforce.com/docs/atlas.en-us.change_data_capture.meta/change_data_capture/)
- [Change Data Capture Limits](https://developer.salesforce.com/docs/atlas.en-us.change_data_capture.meta/change_data_capture/cdc_limits.htm)
- [Platform Event Channels](https://help.salesforce.com/s/articleView?id=sf.platform_event_channels.htm)
