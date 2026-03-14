/**
 * SchemaCacheClient
 *
 * Apex client for reading schema export fields from AWS Schema Cache API.
 * Used by AISearchBatchExport to dynamically get field configuration instead
 * of hardcoded IndexConfiguration__mdt.
 *
 * **Task 34.2: Schema-Driven Export Integration**
 *
 * Features:
 * - Calls AWS Schema Cache API via Named Credential
 * - Caches responses in Platform Cache (1 hour TTL)
 * - Falls back to IndexConfiguration__mdt if API unavailable
 *
 * Usage:
 *   SchemaCacheClient.ExportFields fields = SchemaCacheClient.getExportFields('ascendix__Property__c');
 *   if (fields.hasRecordTypes) {
 *       // Include RecordType.Name in SOQL
 *   }
 */
public class SchemaCacheClient {

    // Cache key prefix for Platform Cache
    private static final String CACHE_KEY_PREFIX = 'SchemaCache_';

    // Cache TTL in seconds (1 hour)
    private static final Integer CACHE_TTL_SECONDS = 3600;

    // Named Credential for AWS API Gateway
    private static final String NAMED_CREDENTIAL = 'AI_Search_API';

    /**
     * Export fields response structure
     */
    public class ExportFields {
        public Boolean success { get; set; }
        public String sobjectType { get; set; }
        public List<String> textFields { get; set; }
        public List<FilterableField> filterableFields { get; set; }
        public List<RelationshipField> relationshipFields { get; set; }
        public List<String> graphAttributes { get; set; }
        public Boolean hasRecordTypes { get; set; }
        public String discoveredAt { get; set; }
        public FieldCounts fieldCounts { get; set; }
        public String errorMessage { get; set; }

        public ExportFields() {
            this.textFields = new List<String>();
            this.filterableFields = new List<FilterableField>();
            this.relationshipFields = new List<RelationshipField>();
            this.graphAttributes = new List<String>();
            this.hasRecordTypes = false;
        }
    }

    public class FilterableField {
        public String name { get; set; }
        public String label { get; set; }
        public List<String> picklistValues { get; set; }
    }

    public class RelationshipField {
        public String name { get; set; }
        public String label { get; set; }
        public String relatedTo { get; set; }
    }

    public class FieldCounts {
        public Integer textCount { get; set; }
        public Integer filterableCount { get; set; }
        public Integer relationshipCount { get; set; }
        public Integer graphAttributeCount { get; set; }
    }

    /**
     * Get export fields for a specific Salesforce object.
     *
     * @param sobjectType The Salesforce object API name (e.g., 'ascendix__Property__c')
     * @return ExportFields containing field configuration from Schema Cache
     */
    public static ExportFields getExportFields(String sobjectType) {
        // Try Platform Cache first
        ExportFields cached = getCachedFields(sobjectType);
        if (cached != null) {
            System.debug('SchemaCacheClient: Cache hit for ' + sobjectType);
            return cached;
        }

        // Call AWS Schema Cache API
        try {
            ExportFields fields = callSchemaApi(sobjectType);
            if (fields.success) {
                // Cache successful response
                cacheFields(sobjectType, fields);
                System.debug('SchemaCacheClient: API call successful for ' + sobjectType);
            }
            return fields;
        } catch (Exception e) {
            System.debug(LoggingLevel.ERROR, 'SchemaCacheClient: API call failed for ' + sobjectType + ': ' + e.getMessage());

            // Return error response - caller should fall back to IndexConfiguration
            ExportFields errorFields = new ExportFields();
            errorFields.success = false;
            errorFields.sobjectType = sobjectType;
            errorFields.errorMessage = e.getMessage();
            return errorFields;
        }
    }

    /**
     * Call AWS Schema Cache API endpoint
     */
    private static ExportFields callSchemaApi(String sobjectType) {
        // Get API configuration
        AI_Search_Config__mdt config = [
            SELECT Ingest_Endpoint__c, API_Key__c
            FROM AI_Search_Config__mdt
            WHERE DeveloperName = 'Default'
            LIMIT 1
        ];

        // Build endpoint URL - replace /ingest with /schema/{objectApiName}
        String baseUrl = config.Ingest_Endpoint__c;
        String schemaEndpoint = baseUrl.replace('/ingest', '/schema/' + EncodingUtil.urlEncode(sobjectType, 'UTF-8'));

        HttpRequest req = new HttpRequest();
        req.setEndpoint(schemaEndpoint);
        req.setMethod('GET');
        req.setHeader('Content-Type', 'application/json');
        req.setHeader('x-api-key', config.API_Key__c);
        req.setTimeout(30000); // 30 seconds

        Http http = new Http();
        HttpResponse res = http.send(req);

        if (res.getStatusCode() == 200) {
            return parseApiResponse(res.getBody());
        } else if (res.getStatusCode() == 404) {
            // Schema not found in cache
            ExportFields notFound = new ExportFields();
            notFound.success = false;
            notFound.sobjectType = sobjectType;
            notFound.errorMessage = 'Schema not found in cache for ' + sobjectType;
            return notFound;
        } else {
            throw new CalloutException('Schema API returned status ' + res.getStatusCode() + ': ' + res.getBody());
        }
    }

    /**
     * Parse API response JSON into ExportFields
     */
    private static ExportFields parseApiResponse(String jsonBody) {
        Map<String, Object> response = (Map<String, Object>) JSON.deserializeUntyped(jsonBody);

        ExportFields fields = new ExportFields();
        fields.success = (Boolean) response.get('success');
        fields.sobjectType = (String) response.get('sobject');
        fields.hasRecordTypes = (Boolean) response.get('has_record_types');
        fields.discoveredAt = (String) response.get('discovered_at');

        // Parse text fields
        List<Object> textList = (List<Object>) response.get('text_fields');
        if (textList != null) {
            for (Object f : textList) {
                fields.textFields.add((String) f);
            }
        }

        // Parse graph attributes
        List<Object> graphList = (List<Object>) response.get('graph_attributes');
        if (graphList != null) {
            for (Object f : graphList) {
                fields.graphAttributes.add((String) f);
            }
        }

        // Parse filterable fields
        List<Object> filterableList = (List<Object>) response.get('filterable_fields');
        if (filterableList != null) {
            for (Object f : filterableList) {
                Map<String, Object> fieldMap = (Map<String, Object>) f;
                FilterableField ff = new FilterableField();
                ff.name = (String) fieldMap.get('name');
                ff.label = (String) fieldMap.get('label');
                ff.picklistValues = new List<String>();
                List<Object> values = (List<Object>) fieldMap.get('values');
                if (values != null) {
                    for (Object v : values) {
                        ff.picklistValues.add((String) v);
                    }
                }
                fields.filterableFields.add(ff);
            }
        }

        // Parse relationship fields
        List<Object> relList = (List<Object>) response.get('relationship_fields');
        if (relList != null) {
            for (Object f : relList) {
                Map<String, Object> fieldMap = (Map<String, Object>) f;
                RelationshipField rf = new RelationshipField();
                rf.name = (String) fieldMap.get('name');
                rf.label = (String) fieldMap.get('label');
                rf.relatedTo = (String) fieldMap.get('related_to');
                fields.relationshipFields.add(rf);
            }
        }

        // Parse field counts
        Map<String, Object> counts = (Map<String, Object>) response.get('field_counts');
        if (counts != null) {
            fields.fieldCounts = new FieldCounts();
            fields.fieldCounts.textCount = (Integer) counts.get('text');
            fields.fieldCounts.filterableCount = (Integer) counts.get('filterable');
            fields.fieldCounts.relationshipCount = (Integer) counts.get('relationships');
            fields.fieldCounts.graphAttributeCount = (Integer) counts.get('graph_attributes');
        }

        return fields;
    }

    /**
     * Get cached fields from Platform Cache.
     * Returns null if cache unavailable or miss.
     */
    private static ExportFields getCachedFields(String sobjectType) {
        // Platform Cache is optional - if not configured, skip caching
        if (!isCacheAvailable()) {
            return null;
        }

        try {
            String cacheKey = CACHE_KEY_PREFIX + sobjectType.replace('__', '_');
            Cache.OrgPartition orgPart = Cache.Org.getPartition('local.SchemaCachePartition');
            return (ExportFields) orgPart.get(cacheKey);
        } catch (Exception e) {
            // Cache miss or error - return null to trigger API call
            System.debug('SchemaCacheClient: Cache miss for ' + sobjectType + ': ' + e.getMessage());
            return null;
        }
    }

    /**
     * Cache fields in Platform Cache.
     * Silently fails if cache unavailable.
     */
    private static void cacheFields(String sobjectType, ExportFields fields) {
        // Platform Cache is optional - if not configured, skip caching
        if (!isCacheAvailable()) {
            return;
        }

        try {
            String cacheKey = CACHE_KEY_PREFIX + sobjectType.replace('__', '_');
            Cache.OrgPartition orgPart = Cache.Org.getPartition('local.SchemaCachePartition');
            orgPart.put(cacheKey, fields, CACHE_TTL_SECONDS);
        } catch (Exception e) {
            // Cache write failure is not critical
            System.debug('SchemaCacheClient: Failed to cache for ' + sobjectType + ': ' + e.getMessage());
        }
    }

    /**
     * Invalidate cached fields for an object
     */
    public static void invalidateCache(String sobjectType) {
        if (!isCacheAvailable()) {
            return;
        }

        try {
            String cacheKey = CACHE_KEY_PREFIX + sobjectType.replace('__', '_');
            Cache.OrgPartition orgPart = Cache.Org.getPartition('local.SchemaCachePartition');
            orgPart.remove(cacheKey);
            System.debug('SchemaCacheClient: Cache invalidated for ' + sobjectType);
        } catch (Exception e) {
            System.debug('SchemaCacheClient: Failed to invalidate cache for ' + sobjectType + ': ' + e.getMessage());
        }
    }

    /**
     * Check if Platform Cache partition is available.
     * Returns false if partition not configured.
     */
    private static Boolean isCacheAvailable() {
        try {
            Cache.OrgPartition orgPart = Cache.Org.getPartition('local.SchemaCachePartition');
            return orgPart != null;
        } catch (Exception e) {
            // Partition doesn't exist - caching disabled
            return false;
        }
    }

    /**
     * Convert ExportFields to field lists for SOQL query building.
     * Convenience method for AISearchBatchExport.
     *
     * @param fields The ExportFields from getExportFields()
     * @return Set of field API names for SOQL SELECT
     */
    public static Set<String> getQueryFields(ExportFields fields) {
        Set<String> queryFields = new Set<String>();

        // Add text fields
        queryFields.addAll(fields.textFields);

        // Add relationship fields (as Name references)
        for (RelationshipField rf : fields.relationshipFields) {
            queryFields.add(rf.name);
        }

        // Add RecordType.Name if object has RecordTypes
        if (fields.hasRecordTypes) {
            queryFields.add('RecordType.Name');
        }

        return queryFields;
    }

    /**
     * Get graph node attributes for an object.
     * Used for building graph node attribute list.
     *
     * @param fields The ExportFields from getExportFields()
     * @return Set of field API names for graph attributes
     */
    public static Set<String> getGraphAttributes(ExportFields fields) {
        return new Set<String>(fields.graphAttributes);
    }
}
