/**
 * AISearchBatchExport
 *
 * Batch Apex class to export modified Salesforce records to AWS ingestion endpoint.
 * This serves as a fallback mechanism when CDC/AppFlow is unavailable.
 *
 * **Task 34.3: Schema-Driven Export Integration**
 *
 * Field Configuration Priority:
 * 1. Schema Cache API (via SchemaCacheClient) - dynamically discovered from SF Describe API
 * 2. IndexConfiguration__mdt - fallback when Schema Cache unavailable
 *
 * This prevents schema drift by reading field configuration from the same source
 * (Schema Discovery) that powers query decomposition.
 *
 * Schedule: Run daily during off-peak hours (e.g., 2 AM)
 * Batch Size: 200 records per batch
 *
 * Usage:
 *   AISearchBatchExport batch = new AISearchBatchExport('Account', 24);
 *   Database.executeBatch(batch, 200);
 *
 * Or to export all configured objects:
 *   AISearchBatchExport.exportAllConfiguredObjects(24);
 */
public class AISearchBatchExport implements Database.Batchable<SObject>, Database.AllowsCallouts {
    
    private String sobjectType;
    private Integer hoursBack;
    private String ingestEndpoint;
    private String apiKey;
    private IndexConfiguration__mdt objectConfig;
    
    /**
     * Constructor
     * 
     * @param sobjectType The Salesforce object type to export (e.g., 'Account')
     * @param hoursBack Number of hours to look back for modified records (default: 24)
     */
    public AISearchBatchExport(String sobjectType, Integer hoursBack) {
        this.sobjectType = sobjectType;
        this.hoursBack = hoursBack != null ? hoursBack : 24;
        
        // Get configuration from IndexConfiguration__mdt
        this.objectConfig = getObjectConfiguration(sobjectType);
        
        if (this.objectConfig == null) {
            System.debug(LoggingLevel.WARN, 'AISearchBatchExport: No IndexConfiguration__mdt found for ' + sobjectType + '. Skipping.');
            throw new IllegalArgumentException('No IndexConfiguration__mdt record found for object: ' + sobjectType);
        }
        
        if (!this.objectConfig.Enabled__c) {
            System.debug(LoggingLevel.WARN, 'AISearchBatchExport: Object ' + sobjectType + ' is disabled in IndexConfiguration__mdt. Skipping.');
            throw new IllegalArgumentException('Object is disabled in IndexConfiguration__mdt: ' + sobjectType);
        }
        
        // Get endpoint and API key from Custom Metadata
        AI_Search_Config__mdt config = [
            SELECT Ingest_Endpoint__c, API_Key__c 
            FROM AI_Search_Config__mdt 
            WHERE DeveloperName = 'Default' 
            LIMIT 1
        ];
        
        // Use the configured ingest endpoint (API Gateway)
        this.ingestEndpoint = config.Ingest_Endpoint__c;
        this.apiKey = config.API_Key__c;
        
        if (String.isBlank(this.apiKey)) {
            throw new IllegalArgumentException('API Key not configured in AI_Search_Config__mdt');
        }
    }
    
    /**
     * Get IndexConfiguration__mdt for a specific object
     * 
     * @param sobjectType The Salesforce object API name
     * @return IndexConfiguration__mdt record or null if not found
     */
    @TestVisible
    private static IndexConfiguration__mdt getObjectConfiguration(String sobjectType) {
        List<IndexConfiguration__mdt> configs = [
            SELECT
                Object_API_Name__c,
                Enabled__c,
                Text_Fields__c,
                Long_Text_Fields__c,
                Relationship_Fields__c,
                Display_Name_Field__c,
                Graph_Enabled__c,
                Graph_Node_Attributes__c,
                Override_Schema_Cache__c,
                Additional_Fields__c
            FROM IndexConfiguration__mdt
            WHERE Object_API_Name__c = :sobjectType
            LIMIT 1
        ];

        return configs.isEmpty() ? null : configs[0];
    }
    
    /**
     * Get all enabled IndexConfiguration__mdt records
     *
     * @return List of enabled configurations
     */
    public static List<IndexConfiguration__mdt> getEnabledConfigurations() {
        return [
            SELECT
                Object_API_Name__c,
                Enabled__c,
                Text_Fields__c,
                Long_Text_Fields__c,
                Relationship_Fields__c,
                Display_Name_Field__c,
                Graph_Enabled__c,
                Graph_Node_Attributes__c,
                Override_Schema_Cache__c,
                Additional_Fields__c
            FROM IndexConfiguration__mdt
            WHERE Enabled__c = true
        ];
    }
    
    /**
     * Export all configured and enabled objects
     * 
     * @param hoursBack Number of hours to look back for modified records
     */
    public static void exportAllConfiguredObjects(Integer hoursBack) {
        List<IndexConfiguration__mdt> configs = getEnabledConfigurations();
        
        for (IndexConfiguration__mdt config : configs) {
            try {
                AISearchBatchExport batch = new AISearchBatchExport(config.Object_API_Name__c, hoursBack);
                Database.executeBatch(batch, 200);
                System.debug('AISearchBatchExport: Started batch for ' + config.Object_API_Name__c);
            } catch (Exception e) {
                System.debug(LoggingLevel.ERROR, 'AISearchBatchExport: Failed to start batch for ' + 
                             config.Object_API_Name__c + ': ' + e.getMessage());
            }
        }
    }
    
    /**
     * Start method - Build query for modified records
     *
     * **Task 38.1: Ingest-Time Field Contract Enforcement**
     * Validates all fields exist in Salesforce schema before building SOQL.
     * This fails fast at ingest time rather than letting queries fail at runtime.
     */
    public Database.QueryLocator start(Database.BatchableContext bc) {
        DateTime cutoffTime = DateTime.now().addHours(-this.hoursBack);

        // TASK 38.1: Build field set and validate before constructing SOQL
        Set<String> fieldsToQuery = buildFieldSetFromConfig(this.objectConfig);

        // Validate all fields exist in Salesforce schema (fail-fast)
        validateFieldsExist(this.sobjectType, fieldsToQuery);

        // Build dynamic query using validated field set
        String query = buildQueryWithValidatedFields(this.objectConfig, fieldsToQuery, cutoffTime);

        System.debug('AISearchBatchExport: Starting batch for ' + this.sobjectType +
                     ' with ' + fieldsToQuery.size() + ' fields');

        return Database.getQueryLocator(query);
    }

    /**
     * Build SOQL query using pre-validated field set.
     * Called after validateFieldsExist() confirms all fields are valid.
     *
     * **Task 38.1: Ingest-Time Field Contract Enforcement**
     *
     * @param config The IndexConfiguration__mdt record
     * @param fieldsToQuery Pre-validated set of field API names
     * @param cutoffTime The cutoff time for LastModifiedDate filter
     * @return SOQL query string
     */
    @TestVisible
    private static String buildQueryWithValidatedFields(IndexConfiguration__mdt config, Set<String> fieldsToQuery, DateTime cutoffTime) {
        String cutoffStr = cutoffTime.formatGMT('yyyy-MM-dd\'T\'HH:mm:ss\'Z\'');

        List<String> fieldList = new List<String>(fieldsToQuery);
        String query = 'SELECT ' + String.join(fieldList, ', ') +
                       ' FROM ' + config.Object_API_Name__c +
                       ' WHERE LastModifiedDate >= ' + cutoffStr +
                       ' ORDER BY LastModifiedDate ASC';

        return query;
    }
    
    /**
     * Execute method - Process batch of records
     */
    public void execute(Database.BatchableContext bc, List<SObject> scope) {
        try {
            // Transform records to ingestion format
            List<Map<String, Object>> records = new List<Map<String, Object>>();
            
            for (SObject record : scope) {
                records.add(transformRecord(record));
            }
            
            // Send to ingestion endpoint
            sendToIngestEndpoint(records);
            
            System.debug('AISearchBatchExport: Successfully exported ' + scope.size() + 
                         ' ' + this.sobjectType + ' records');
            
        } catch (Exception e) {
            System.debug(LoggingLevel.ERROR, 'AISearchBatchExport: Error processing batch: ' + 
                         e.getMessage() + '\n' + e.getStackTraceString());
            
            // Log error but don't fail the batch
            logError(bc.getJobId(), scope, e);
        }
    }
    
    /**
     * Finish method - Log completion
     */
    public void finish(Database.BatchableContext bc) {
        AsyncApexJob job = [
            SELECT Id, Status, NumberOfErrors, JobItemsProcessed, TotalJobItems,
                   CreatedDate, CompletedDate
            FROM AsyncApexJob
            WHERE Id = :bc.getJobId()
        ];
        
        System.debug('AISearchBatchExport: Batch completed for ' + this.sobjectType + 
                     '. Status: ' + job.Status + 
                     ', Processed: ' + job.JobItemsProcessed + '/' + job.TotalJobItems +
                     ', Errors: ' + job.NumberOfErrors);
        
        // Send completion notification (optional)
        if (job.NumberOfErrors > 0) {
            sendErrorNotification(job);
        }
    }
    
    /**
     * Build dynamic SOQL query using Schema Cache or IndexConfiguration__mdt fallback.
     *
     * **Task 34.3: Schema-Driven Export Integration**
     *
     * Priority:
     * 1. Try Schema Cache API (via SchemaCacheClient)
     * 2. Fall back to IndexConfiguration__mdt if Schema Cache unavailable
     *
     * Note: This method is kept for backward compatibility with existing tests.
     * New code should use buildFieldSetFromConfig() + buildQueryWithValidatedFields()
     * to enable field validation.
     *
     * @param config The IndexConfiguration__mdt record
     * @param cutoffTime The cutoff time for LastModifiedDate filter
     * @return SOQL query string
     */
    @TestVisible
    private static String buildQueryFromConfig(IndexConfiguration__mdt config, DateTime cutoffTime) {
        // Delegate to buildFieldSetFromConfig for field collection (DRY principle)
        Set<String> fieldsToQuery = buildFieldSetFromConfig(config);

        // Log field source for debugging
        if (config.Override_Schema_Cache__c) {
            System.debug('AISearchBatchExport: Override enabled for ' + config.Object_API_Name__c +
                         ', using IndexConfiguration fields');
        } else {
            Set<String> schemaCacheFields = getFieldsFromSchemaCache(config.Object_API_Name__c, config.Graph_Enabled__c);
            if (!schemaCacheFields.isEmpty()) {
                System.debug('AISearchBatchExport: Using Schema Cache for ' + config.Object_API_Name__c +
                             ' (' + schemaCacheFields.size() + ' fields)');
            } else {
                System.debug(LoggingLevel.WARN, 'AISearchBatchExport: Schema Cache unavailable for ' +
                             config.Object_API_Name__c + ', using IndexConfiguration fallback');
            }
        }

        // Build query using the collected fields
        return buildQueryWithValidatedFields(config, fieldsToQuery, cutoffTime);
    }

    /**
     * Get fields from Schema Cache API.
     *
     * **Task 34.3: Schema-Driven Export Integration**
     *
     * @param sobjectType The Salesforce object API name
     * @param graphEnabled Whether graph attributes should be included
     * @return Set of field API names, or empty set if unavailable
     */
    @TestVisible
    private static Set<String> getFieldsFromSchemaCache(String sobjectType, Boolean graphEnabled) {
        Set<String> fields = new Set<String>();

        try {
            SchemaCacheClient.ExportFields exportFields = SchemaCacheClient.getExportFields(sobjectType);

            if (!exportFields.success) {
                System.debug(LoggingLevel.WARN, 'SchemaCacheClient failed for ' + sobjectType +
                             ': ' + exportFields.errorMessage);
                return fields; // Return empty set to trigger fallback
            }

            // Add text fields
            fields.addAll(exportFields.textFields);

            // Add relationship fields
            for (SchemaCacheClient.RelationshipField rf : exportFields.relationshipFields) {
                fields.add(rf.name);
            }

            // Auto-include RecordType.Name if object has RecordTypes
            if (exportFields.hasRecordTypes) {
                fields.add('RecordType.Name');
            }

            // Add graph attributes if graph is enabled
            if (graphEnabled) {
                fields.addAll(exportFields.graphAttributes);
            }

            return fields;

        } catch (Exception e) {
            System.debug(LoggingLevel.ERROR, 'Error getting fields from Schema Cache for ' +
                         sobjectType + ': ' + e.getMessage());
            return fields; // Return empty set to trigger fallback
        }
    }

    /**
     * Get fields from IndexConfiguration__mdt (fallback).
     *
     * @param config The IndexConfiguration__mdt record
     * @return Set of field API names
     */
    @TestVisible
    private static Set<String> getFieldsFromIndexConfig(IndexConfiguration__mdt config) {
        Set<String> fields = new Set<String>();

        // Add Text_Fields__c
        if (String.isNotBlank(config.Text_Fields__c)) {
            fields.addAll(parseFieldList(config.Text_Fields__c));
        }

        // Add Long_Text_Fields__c
        if (String.isNotBlank(config.Long_Text_Fields__c)) {
            fields.addAll(parseFieldList(config.Long_Text_Fields__c));
        }

        // Add Relationship_Fields__c
        if (String.isNotBlank(config.Relationship_Fields__c)) {
            fields.addAll(parseFieldList(config.Relationship_Fields__c));
        }

        // Add Display_Name_Field__c if specified
        if (String.isNotBlank(config.Display_Name_Field__c)) {
            fields.add(config.Display_Name_Field__c.trim());
        }

        // Add Graph_Node_Attributes__c if graph is enabled
        if (config.Graph_Enabled__c && String.isNotBlank(config.Graph_Node_Attributes__c)) {
            fields.addAll(parseFieldList(config.Graph_Node_Attributes__c));
        }

        return fields;
    }
    
    /**
     * Parse comma-separated field list into Set of field names
     *
     * @param fieldListStr Comma-separated field names
     * @return Set of trimmed field names
     */
    @TestVisible
    private static Set<String> parseFieldList(String fieldListStr) {
        Set<String> fields = new Set<String>();

        if (String.isBlank(fieldListStr)) {
            return fields;
        }

        for (String field : fieldListStr.split(',')) {
            String trimmedField = field.trim();
            if (String.isNotBlank(trimmedField)) {
                fields.add(trimmedField);
            }
        }

        return fields;
    }

    /**
     * Build the complete field set from configuration.
     * Uses the same logic as buildQueryFromConfig() to ensure validation
     * checks the exact fields that will be queried.
     *
     * **Task 38.1: Ingest-Time Field Contract Enforcement**
     *
     * @param config The IndexConfiguration__mdt record
     * @return Set of field API names to query
     */
    @TestVisible
    private static Set<String> buildFieldSetFromConfig(IndexConfiguration__mdt config) {
        Set<String> fieldsToQuery = new Set<String>();

        // Always include Id and LastModifiedDate
        fieldsToQuery.add('Id');
        fieldsToQuery.add('LastModifiedDate');

        // Include OwnerId for authorization bucket computation (Requirement 2.5)
        if (hasOwnerIdField(config.Object_API_Name__c)) {
            fieldsToQuery.add('OwnerId');
        }

        // Check if override is enabled - use IndexConfiguration fields directly
        if (config.Override_Schema_Cache__c) {
            fieldsToQuery.addAll(getFieldsFromIndexConfig(config));
        } else {
            // Try Schema Cache first
            Set<String> schemaCacheFields = getFieldsFromSchemaCache(config.Object_API_Name__c, config.Graph_Enabled__c);

            if (!schemaCacheFields.isEmpty()) {
                // Use Schema Cache fields
                fieldsToQuery.addAll(schemaCacheFields);
            } else {
                // Fall back to IndexConfiguration__mdt
                fieldsToQuery.addAll(getFieldsFromIndexConfig(config));
            }
        }

        // Always add Additional_Fields__c regardless of source (override, cache, or fallback)
        // This ensures supplementary fields are never silently ignored
        if (String.isNotBlank(config.Additional_Fields__c)) {
            Set<String> additionalFields = parseFieldList(config.Additional_Fields__c);
            fieldsToQuery.addAll(additionalFields);
        }

        return fieldsToQuery;
    }

    /**
     * Extract the base field name for validation from a potentially dotted path.
     * Handles relationship traversals like "RecordType.Name" → "RecordTypeId".
     *
     * **Task 38.1: Ingest-Time Field Contract Enforcement**
     *
     * @param fieldPath The field path (may contain dots)
     * @return The base field name to validate
     */
    @TestVisible
    private static String extractBaseFieldForValidation(String fieldPath) {
        if (!fieldPath.contains('.')) {
            return fieldPath;
        }

        String basePart = fieldPath.substringBefore('.');

        // Standard relationship → Id field mappings
        if (basePart.equalsIgnoreCase('RecordType')) {
            return 'RecordTypeId';
        }
        if (basePart.equalsIgnoreCase('Owner')) {
            return 'OwnerId';
        }
        if (basePart.equalsIgnoreCase('CreatedBy')) {
            return 'CreatedById';
        }
        if (basePart.equalsIgnoreCase('LastModifiedBy')) {
            return 'LastModifiedById';
        }
        if (basePart.equalsIgnoreCase('Parent')) {
            return 'ParentId';
        }

        // Custom relationships: "Account__r.Name" → "Account__c"
        if (basePart.endsWith('__r')) {
            return basePart.replace('__r', '__c');
        }

        // Standard relationships: "Account.Name" → "AccountId"
        return basePart + 'Id';
    }

    /**
     * Validate all fields exist in Salesforce schema before building SOQL.
     * For dotted paths (e.g., "RecordType.Name"), validates the base relationship exists.
     *
     * **Task 38.1: Ingest-Time Field Contract Enforcement**
     *
     * This fails fast at ingest time rather than letting queries fail at runtime.
     *
     * @param sobjectType The Salesforce object API name
     * @param fieldsToQuery Set of field API names from buildFieldSetFromConfig()
     * @throws AISearchExportException if required fields are missing
     */
    @TestVisible
    private static void validateFieldsExist(String sobjectType, Set<String> fieldsToQuery) {
        Schema.SObjectType sot = Schema.getGlobalDescribe().get(sobjectType);
        if (sot == null) {
            throw new AISearchExportException('Object not found in Salesforce schema: ' + sobjectType);
        }

        Map<String, Schema.SObjectField> fieldMap = sot.getDescribe().fields.getMap();

        // Build case-insensitive lookup map (fieldMap keys are lowercase)
        Set<String> fieldNamesLower = new Set<String>();
        for (String fieldName : fieldMap.keySet()) {
            fieldNamesLower.add(fieldName.toLowerCase());
        }

        List<String> missingFields = new List<String>();
        List<String> validatedFields = new List<String>();

        for (String field : fieldsToQuery) {
            String fieldToCheck = extractBaseFieldForValidation(field);

            // Case-insensitive check
            if (!fieldNamesLower.contains(fieldToCheck.toLowerCase())) {
                if (field.contains('.')) {
                    missingFields.add(field + ' (base field: ' + fieldToCheck + ')');
                } else {
                    missingFields.add(field);
                }
            } else {
                validatedFields.add(field);
            }
        }

        if (!missingFields.isEmpty()) {
            String errorMsg = 'AI Search Export blocked for ' + sobjectType +
                '. Missing ' + missingFields.size() + ' field(s): ' + String.join(missingFields, ', ');
            System.debug(LoggingLevel.ERROR, '[FIELD_CONTRACT] ' + errorMsg);
            throw new AISearchExportException(errorMsg);
        }

        System.debug('AISearchBatchExport: [FIELD_CONTRACT] Validation passed for ' + sobjectType +
                     ' (' + validatedFields.size() + ' fields validated)');
    }

    /**
     * Check if an object has an OwnerId field
     * Detail objects in master-detail relationships don't have OwnerId
     * 
     * @param sobjectType The Salesforce object API name
     * @return true if the object has an OwnerId field
     */
    @TestVisible
    private static Boolean hasOwnerIdField(String sobjectType) {
        try {
            Schema.SObjectType sot = Schema.getGlobalDescribe().get(sobjectType);
            if (sot == null) {
                return false;
            }
            Map<String, Schema.SObjectField> fieldMap = sot.getDescribe().fields.getMap();
            return fieldMap.containsKey('OwnerId');
        } catch (Exception e) {
            // If we can't determine, assume it doesn't have OwnerId to be safe
            System.debug(LoggingLevel.WARN, 'Could not determine if ' + sobjectType + ' has OwnerId: ' + e.getMessage());
            return false;
        }
    }
    
    /**
     * Transform SObject record to ingestion format
     * Handles relationship fields (e.g., RecordType.Name) by flattening nested SObjects
     */
    private Map<String, Object> transformRecord(SObject record) {
        Map<String, Object> recordMap = new Map<String, Object>();

        // Get all populated fields
        Map<String, Object> fieldMap = record.getPopulatedFieldsAsMap();

        for (String fieldName : fieldMap.keySet()) {
            Object value = fieldMap.get(fieldName);

            // Handle relationship fields (nested SObjects like RecordType)
            if (value instanceof SObject) {
                SObject relatedRecord = (SObject) value;
                Map<String, Object> relatedFields = relatedRecord.getPopulatedFieldsAsMap();
                for (String relFieldName : relatedFields.keySet()) {
                    // Skip Id fields from related objects to avoid confusion
                    if (relFieldName == 'Id') continue;
                    Object relValue = relatedFields.get(relFieldName);
                    String flatFieldName = fieldName + '.' + relFieldName;
                    recordMap.put(flatFieldName, formatValue(relValue));
                }
            } else {
                recordMap.put(fieldName, formatValue(value));
            }
        }

        return recordMap;
    }

    /**
     * Format a value for JSON serialization
     */
    private Object formatValue(Object value) {
        if (value instanceof DateTime) {
            return ((DateTime)value).formatGMT('yyyy-MM-dd\'T\'HH:mm:ss\'Z\'');
        } else if (value instanceof Date) {
            return ((Date)value).format();
        }
        return value;
    }
    
    /**
     * Send records to AWS ingestion endpoint
     */
    private void sendToIngestEndpoint(List<Map<String, Object>> records) {
        // Build request payload
        Map<String, Object> payload = new Map<String, Object>{
            'sobject' => this.sobjectType,
            'operation' => 'upsert',
            'records' => records,
            'source' => 'batch_export',
            'timestamp' => DateTime.now().formatGMT('yyyy-MM-dd\'T\'HH:mm:ss\'Z\'')
        };
        
        String jsonPayload = JSON.serialize(payload);
        
        // Make HTTP callout
        HttpRequest req = new HttpRequest();
        req.setEndpoint(this.ingestEndpoint);
        req.setMethod('POST');
        req.setHeader('Content-Type', 'application/json');
        req.setHeader('x-api-key', this.apiKey);
        req.setBody(jsonPayload);
        req.setTimeout(120000); // 2 minutes
        
        Http http = new Http();
        HttpResponse res = http.send(req);
        
        if (res.getStatusCode() != 200 && res.getStatusCode() != 202) {
            throw new CalloutException('Ingestion endpoint returned status ' + 
                                       res.getStatusCode() + ': ' + res.getBody());
        }
        
        System.debug('AISearchBatchExport: Successfully sent ' + records.size() + 
                     ' records to ingestion endpoint');
    }
    
    /**
     * Log error to custom object for monitoring
     */
    private void logError(Id jobId, List<SObject> scope, Exception e) {
        try {
            AI_Search_Export_Error__c error = new AI_Search_Export_Error__c(
                Job_Id__c = String.valueOf(jobId),
                Object_Type__c = this.sobjectType,
                Error_Message__c = e.getMessage(),
                Stack_Trace__c = e.getStackTraceString(),
                Record_Count__c = scope.size(),
                Timestamp__c = DateTime.now()
            );
            insert error;
        } catch (Exception logEx) {
            System.debug(LoggingLevel.ERROR, 'Failed to log error: ' + logEx.getMessage());
        }
    }
    
    /**
     * Send error notification to administrators
     */
    private void sendErrorNotification(AsyncApexJob job) {
        // TODO: Implement email notification or platform event
        System.debug('AISearchBatchExport: Batch job ' + job.Id + ' completed with errors');
    }
}
