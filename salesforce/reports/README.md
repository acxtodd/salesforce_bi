# Salesforce Reports for AI Agent Actions

This directory contains Salesforce report metadata for monitoring and analyzing AI Agent Actions (Phase 2).

## Report Folder: AI Agent Actions Analytics

Contains three reports for monitoring agent action usage, failures, and performance.

### 1. Daily Action Counts by Action Name

**File**: `AI_Agent_Actions_Analytics/Daily_Action_Counts_by_Action_Name.report-meta.xml`

**Purpose**: Track daily and weekly action execution counts grouped by action name.

**Metrics**:
- Total Actions: Count of all action executions
- Success Rate: Percentage of successful actions
- Grouped by: Date (Day) → Action Name

**Time Frame**: Last 7 days (configurable)

**Use Cases**:
- Monitor action adoption and usage trends
- Identify most frequently used actions
- Track success rates over time
- Detect anomalies in action volume

### 2. Failure Reasons and Affected Users

**File**: `AI_Agent_Actions_Analytics/Failure_Reasons_and_Affected_Users.report-meta.xml`

**Purpose**: Troubleshoot action failures by analyzing error messages and affected users.

**Metrics**:
- Failure Count: Total number of failed actions
- Grouped by: Error Message

**Columns**:
- Created Date
- Action Name
- User ID
- Chat Session ID
- Inputs JSON (for debugging)
- Error Message

**Filter**: Only shows failed actions (Success__c = false)

**Time Frame**: Last 30 days (configurable)

**Use Cases**:
- Identify common failure patterns
- Troubleshoot user-specific issues
- Correlate failures with specific inputs
- Track error trends over time

### 3. Top Objects Modified

**File**: `AI_Agent_Actions_Analytics/Top_Objects_Modified.report-meta.xml`

**Purpose**: Analyze which objects are most frequently modified by agent actions.

**Metrics**:
- Modification Count: Total number of successful modifications
- Avg Latency (ms): Average action execution time

**Columns**:
- Created Date
- User ID
- Records (JSON array of modified record IDs)
- Success status
- Latency in milliseconds

**Chart**: Horizontal bar chart showing modification count by action name

**Filter**: Only shows successful actions (Success__c = true)

**Time Frame**: Last 30 days (configurable)

**Use Cases**:
- Understand which actions are most impactful
- Monitor performance by action type
- Identify high-latency actions
- Track data modification patterns

## Deployment

### Deploy Reports to Salesforce

```bash
# Deploy all reports
sfdx force:source:deploy -p salesforce/reports --targetusername <org-alias>

# Or include in package.xml deployment
sfdx force:source:deploy -x salesforce/package.xml --targetusername <org-alias>
```

### Update package.xml

Add the following to `salesforce/package.xml`:

```xml
<types>
    <members>AI_Agent_Actions_Analytics</members>
    <name>ReportFolder</name>
</types>
<types>
    <members>AI_Agent_Actions_Analytics/Daily_Action_Counts_by_Action_Name</members>
    <members>AI_Agent_Actions_Analytics/Failure_Reasons_and_Affected_Users</members>
    <members>AI_Agent_Actions_Analytics/Top_Objects_Modified</members>
    <name>Report</name>
</types>
```

## Accessing Reports

After deployment:

1. Navigate to **Reports** tab in Salesforce
2. Find the **AI Agent Actions Analytics** folder
3. Click on any report to view
4. Use **Edit** to customize filters, groupings, or time frames
5. Use **Subscribe** to receive scheduled email updates

## Customization

### Modify Time Frames

Edit the `<timeFrameFilter>` section in each report:

```xml
<timeFrameFilter>
    <dateColumn>CREATED_DATE</dateColumn>
    <interval>INTERVAL_LAST7</interval>  <!-- Change to INTERVAL_LAST30, INTERVAL_CUSTOM, etc. -->
</timeFrameFilter>
```

### Add Additional Columns

Add new `<columns>` elements:

```xml
<columns>
    <field>AI_Action_Audit__c.YourCustomField__c</field>
</columns>
```

### Modify Groupings

Change the `<groupingsDown>` sections to group by different fields:

```xml
<groupingsDown>
    <dateGranularity>Week</dateGranularity>  <!-- Change to Day, Week, Month, etc. -->
    <field>AI_Action_Audit__c.UserId__c</field>  <!-- Group by different field -->
    <sortOrder>Desc</sortOrder>
</groupingsDown>
```

## Report Types

All reports use the custom report type:
- **Report Type**: `CustomEntity$AI_Action_Audit__c`
- **Base Object**: AI_Action_Audit__c custom object

## Permissions

Users need the following permissions to access these reports:
- Read access to AI_Action_Audit__c object
- Access to the AI Agent Actions Analytics report folder
- Standard Salesforce reporting permissions

Administrators can control access via:
- Object-level security (OWD, sharing rules)
- Field-level security
- Report folder access settings

## Monitoring Best Practices

1. **Daily Review**: Check Daily Action Counts report for usage trends
2. **Weekly Analysis**: Review Failure Reasons report to identify patterns
3. **Monthly Planning**: Use Top Objects Modified to understand impact
4. **Set Up Subscriptions**: Configure email subscriptions for key stakeholders
5. **Create Dashboards**: Add these reports to Salesforce dashboards for at-a-glance monitoring

## Integration with CloudWatch

These Salesforce reports complement the CloudWatch dashboards:
- **CloudWatch**: Real-time metrics, latency, error rates
- **Salesforce Reports**: Historical analysis, user-level details, business context

Use both together for comprehensive monitoring:
- CloudWatch for operational alerts and performance monitoring
- Salesforce Reports for business analysis and user behavior insights

## Limitations and Workarounds

### Records__c JSON Parsing

The Top Objects Modified report displays the raw Records__c JSON field, which contains an array of record IDs like `["006xx1", "006xx2"]`. Salesforce reports don't natively support JSON parsing, so the report groups by Action Name rather than object type.

**Workarounds for Object-Level Analysis**:

1. **Formula Field Approach** (Recommended):
   Create a formula field `ObjectType__c` on AI_Action_Audit__c:
   ```
   IF(LEN(Records__c) > 10, 
     LEFT(MID(Records__c, 3, 18), 3),
     ""
   )
   ```
   This extracts the first record ID's prefix (e.g., "006" for Opportunity, "001" for Account).

2. **Apex Trigger Approach**:
   Create an Apex trigger that parses Records__c JSON and populates separate fields:
   - `ObjectTypes__c` (Text): Comma-separated list of object types
   - `RecordCount__c` (Number): Count of records modified
   
3. **Custom Report Type**:
   Create a custom report type with AI_Action_Audit__c as primary object and add custom fields for object analysis.

4. **Dashboard Component**:
   Build a Lightning Web Component that queries AI_Action_Audit__c and parses Records__c client-side for rich visualizations.

## Troubleshooting

### Report Shows No Data

1. Verify AI_Action_Audit__c records exist:
   ```sql
   SELECT COUNT() FROM AI_Action_Audit__c
   ```
2. Check report filters and time frame
3. Verify user has read access to AI_Action_Audit__c

### Permission Errors

1. Grant read access to AI_Action_Audit__c object
2. Add user to report folder access list
3. Check field-level security for all fields used in report

### Performance Issues

1. Reduce time frame (e.g., last 7 days instead of last 30)
2. Limit number of columns displayed
3. Use summary format instead of detailed
4. Consider archiving old audit records

## Related Documentation

- [Phase 2 Deployment Guide](../PHASE2_DEPLOYMENT.md)
- [Action Lambda Implementation](../../lambda/action/README.md)
- [Monitoring Stack](../../lib/monitoring-stack.ts)
- [CloudWatch Dashboards](../../docs/MONITORING_IMPLEMENTATION.md)
