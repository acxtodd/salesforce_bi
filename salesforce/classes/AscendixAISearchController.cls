public with sharing class AscendixAISearchController {
    
    private static final String NAMED_CREDENTIAL = 'callout:Ascendix_RAG_API';
    private static final String QUERY_CREDENTIAL = 'callout:Ascendix_RAG_Query_API';
    private static final Integer TIMEOUT_MS = 120000; // 120 seconds
    
    /**
     * Call the /answer endpoint with streaming support
     */
    @AuraEnabled
    public static Map<String, Object> callAnswerEndpoint(String requestBodyJson) {
        try {
            Map<String, Object> requestBody = (Map<String, Object>) JSON.deserializeUntyped(requestBodyJson);

            // Build payload for /query endpoint: question, org_id, session_id, record_id
            Map<String, Object> newPayload = new Map<String, Object>();
            newPayload.put('question', (String) requestBody.get('query'));
            newPayload.put('org_id', UserInfo.getOrganizationId());
            newPayload.put('session_id', (String) requestBody.get('sessionId'));
            if (requestBody.containsKey('recordId') && requestBody.get('recordId') != null) {
                String recId = (String) requestBody.get('recordId');
                newPayload.put('record_id', recId);
                // Resolve record name and object type so the LLM has context
                try {
                    Id sfId = Id.valueOf(recId);
                    String objType = sfId.getSObjectType().getDescribe().getName();
                    newPayload.put('record_type', objType);
                    // Query the Name field (most standard/custom objects have it)
                    String nameField = (objType == 'Task') ? 'Subject' : 'Name';
                    String soql = 'SELECT ' + nameField + ' FROM ' + objType + ' WHERE Id = :recId LIMIT 1';
                    List<SObject> records = Database.query(soql);
                    if (!records.isEmpty()) {
                        newPayload.put('record_name', (String) records[0].get(nameField));
                    }
                } catch (Exception e) {
                    System.debug('Could not resolve record context: ' + e.getMessage());
                }
            }
            if (requestBody.containsKey('modelId') && requestBody.get('modelId') != null) {
                newPayload.put('model_id', (String) requestBody.get('modelId'));
            }
            if (requestBody.containsKey('conversationHistory') && requestBody.get('conversationHistory') != null) {
                newPayload.put('conversation_history', requestBody.get('conversationHistory'));
            } else if (requestBody.containsKey('priorContext') && requestBody.get('priorContext') != null) {
                newPayload.put('prior_context', requestBody.get('priorContext'));
            }

            HttpRequest req = new HttpRequest();
            req.setEndpoint(QUERY_CREDENTIAL + '/query');
            req.setMethod('POST');
            req.setHeader('Content-Type', 'application/json');
            req.setHeader('x-api-key', '{!$Credential.Ascendix_RAG_Query_API.ApiKey}');
            req.setTimeout(TIMEOUT_MS);
            req.setBody(JSON.serialize(newPayload));
            
            Http http = new Http();
            HttpResponse res = http.send(req);
            
            if (res.getStatusCode() == 200) {
                // Handle Server-Sent Events (SSE) response
                String contentType = res.getHeader('Content-Type');
                // Check for SSE signature in body or header
                if (res.getBody().contains('event:') || (contentType != null && contentType.contains('text/event-stream'))) {
                    return parseSSEResponse(res.getBody());
                } else {
                    // Fallback to standard JSON if not SSE
                    Map<String, Object> responseData = (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
                    return responseData;
                }
            } else {
                handleErrorResponse(res);
                return null;
            }
            
        } catch (Exception e) {
            System.debug('Error in callAnswerEndpoint: ' + e.getMessage());
            if (e instanceof AuraHandledException) {
                throw e;
            }
            AuraHandledException ahe = new AuraHandledException(e.getMessage());
            ahe.setMessage(e.getMessage());
            throw ahe;
        }
    }
    
    /**
     * Helper to parse SSE response from AWS Lambda (Line-by-line approach)
     */
    private static Map<String, Object> parseSSEResponse(String responseBody) {
        Map<String, Object> result = new Map<String, Object>();
        StringBuilder answerBuilder = new StringBuilder();
        
        // Normalize line endings and split
        List<String> lines = responseBody.replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n');
        
        String currentEvent = null;
        
        for (String line : lines) {
            line = line.trim();
            if (String.isBlank(line)) continue;
            
            if (line.startsWith('event:')) {
                currentEvent = line.substring(6).trim();
            } else if (line.startsWith('data:')) {
                String dataJson = line.substring(5).trim();
                try {
                    // Handle "data: [DONE]" case if present in standard SSE
                    if (dataJson == '[DONE]') continue;

                    Map<String, Object> data = (Map<String, Object>) JSON.deserializeUntyped(dataJson);
                    
                    if (currentEvent == 'token') {
                        if (data.containsKey('text')) {
                            answerBuilder.append((String)data.get('text'));
                        }
                    } else if (currentEvent == 'citations') {
                        if (data.containsKey('citations')) {
                            List<Object> rawCitations = (List<Object>) data.get('citations');
                            if (!result.containsKey('citations')) {
                                result.put('citations', new List<Object>());
                            }
                            List<Object> citationsList = (List<Object>) result.get('citations');
                            for (Object rawCitation : rawCitations) {
                                Map<String, Object> citationMap = (Map<String, Object>) rawCitation;
                                Map<String, Object> transformed = new Map<String, Object>();
                                transformed.put('recordId', citationMap.get('id'));
                                transformed.put('title', citationMap.get('name'));
                                transformed.put('id', citationMap.get('id'));
                                citationsList.add(transformed);
                            }
                        }
                    } else if (currentEvent == 'clarification') {
                        if (data.containsKey('options')) {
                            result.put('clarificationOptions', data.get('options'));
                        }
                    } else if (currentEvent == 'done') {
                        // Merge any final metadata
                        if (data.containsKey('reason')) {
                            result.put('reason', data.get('reason'));
                        }
                        if (data.containsKey('trace')) {
                            result.put('trace', data.get('trace'));
                        }
                         // If citations came in the done block
                        if (data.containsKey('citations')) {
                             result.put('citations', data.get('citations'));
                        }
                        if (data.containsKey('model_id')) {
                            result.put('modelId', data.get('model_id'));
                        }
                        if (data.containsKey('write_proposal')) {
                            result.put('writeProposal', data.get('write_proposal'));
                        } else if (data.containsKey('writeProposal')) {
                            result.put('writeProposal', data.get('writeProposal'));
                        }
                    }
                } catch (Exception e) {
                    System.debug('Error parsing SSE data line: ' + dataJson + ' Error: ' + e.getMessage());
                }
            }
        }
        
        result.put('answer', answerBuilder.toString());
        return result;
    }

    // StringBuilder helper since Apex doesn't have one built-in exactly like Java
    private class StringBuilder {
        private String buffer = '';
        public void append(String s) {
            if (s != null) buffer += s;
        }
        public override String toString() {
            return buffer;
        }
    }
    
    /**
     * Call the /retrieve endpoint for search results
     */
    @AuraEnabled
    public static Map<String, Object> callRetrieveEndpoint(String requestBodyJson) {
        try {
            Map<String, Object> requestBody = (Map<String, Object>) JSON.deserializeUntyped(requestBodyJson);
            
            if (!requestBody.containsKey('salesforceUserId') || requestBody.get('salesforceUserId') == null) {
                requestBody.put('salesforceUserId', UserInfo.getUserId());
            }
            
            HttpRequest req = new HttpRequest();
            req.setEndpoint(NAMED_CREDENTIAL + '/retrieve');
            req.setMethod('POST');
            req.setHeader('Content-Type', 'application/json');
            req.setHeader('x-api-key', '{!$Credential.Ascendix_RAG_Query_API.ApiKey}');
            req.setTimeout(TIMEOUT_MS);
            req.setBody(JSON.serialize(requestBody));

            Http http = new Http();
            HttpResponse res = http.send(req);

            if (res.getStatusCode() == 200) {
                Map<String, Object> responseData = (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
                return responseData;
            } else {
                handleErrorResponse(res);
                return null;
            }

        } catch (Exception e) {
            System.debug('Error in callRetrieveEndpoint: ' + e.getMessage());
            if (e instanceof AuraHandledException) {
                throw e;
            }
            AuraHandledException ahe = new AuraHandledException(e.getMessage());
            ahe.setMessage(e.getMessage());
            throw ahe;
        }
    }
    
    /**
     * Call the /action endpoint to execute an agent action (Phase 2)
     */
    @AuraEnabled
    public static Map<String, Object> callActionEndpoint(String requestBodyJson) {
        try {
            Map<String, Object> requestBody = (Map<String, Object>) JSON.deserializeUntyped(requestBodyJson);
            
            if (!requestBody.containsKey('salesforceUserId') || requestBody.get('salesforceUserId') == null) {
                requestBody.put('salesforceUserId', UserInfo.getUserId());
            }
            
            HttpRequest req = new HttpRequest();
            req.setEndpoint(NAMED_CREDENTIAL + '/action');
            req.setMethod('POST');
            req.setHeader('Content-Type', 'application/json');
            req.setHeader('x-api-key', '{!$Credential.Ascendix_RAG_Query_API.ApiKey}');
            req.setTimeout(TIMEOUT_MS);
            req.setBody(JSON.serialize(requestBody));

            Http http = new Http();
            HttpResponse res = http.send(req);

            if (res.getStatusCode() == 200) {
                Map<String, Object> responseData = (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
                return responseData;
            } else {
                handleErrorResponse(res);
                return null;
            }

        } catch (Exception e) {
            System.debug('Error in callActionEndpoint: ' + e.getMessage());
            if (e instanceof AuraHandledException) {
                throw e;
            }
            AuraHandledException ahe = new AuraHandledException(e.getMessage());
            ahe.setMessage(e.getMessage());
            throw ahe;
        }
    }
    
    /**
     * Get current user's Salesforce User ID
     */
    @AuraEnabled(cacheable=true)
    public static String getCurrentUserId() {
        return UserInfo.getUserId();
    }

    private static final Map<String, Set<String>> WRITE_PROPOSAL_ALLOWED_FIELDS_BY_OBJECT =
        new Map<String, Set<String>>{
            'Account' => new Set<String>{
                'Name', 'Phone', 'Website', 'Industry', 'Type',
                'BillingCity', 'BillingState', 'BillingPostalCode',
                'AnnualRevenue', 'NumberOfEmployees'
            },
            'Contact' => new Set<String>{
                'FirstName', 'LastName', 'Email', 'Phone', 'MobilePhone',
                'Title', 'Department', 'AccountId',
                'MailingCity', 'MailingState', 'MailingPostalCode'
            },
            'Task' => new Set<String>{
                'Subject', 'Status', 'Priority', 'ActivityDate',
                'Description', 'Type'
            }
        };

    @AuraEnabled
    public static Map<String, Object> previewWriteProposal(String proposalJson) {
        try {
            if (String.isBlank(proposalJson)) {
                throw new AuraHandledException('Write proposal payload was empty.');
            }

            Map<String, Object> proposal = (Map<String, Object>) JSON.deserializeUntyped(proposalJson);
            return buildWriteProposalPreview(proposal);
        } catch (Exception e) {
            if (e instanceof AuraHandledException) {
                throw e;
            }
            AuraHandledException ahe = new AuraHandledException(e.getMessage());
            ahe.setMessage(e.getMessage());
            throw ahe;
        }
    }

    private static Map<String, Object> buildWriteProposalPreview(Map<String, Object> proposal) {
        if (proposal == null || proposal.isEmpty()) {
            throw new AuraHandledException('Write proposal payload was empty.');
        }

        String kind = normalizeString(proposal.get('kind'));
        if (kind != 'edit') {
            throw new AuraHandledException('Unsupported write proposal kind: ' + kind);
        }

        String objectApiName = normalizeString(proposal.get('objectType'));
        String recordId = normalizeString(proposal.get('recordId'));
        if (String.isBlank(objectApiName)) {
            throw new AuraHandledException('Write proposal is missing objectType.');
        }
        if (String.isBlank(recordId)) {
            throw new AuraHandledException('Write proposal is missing recordId.');
        }

        Id validatedRecordId;
        try {
            validatedRecordId = Id.valueOf(recordId);
        } catch (Exception e) {
            throw new AuraHandledException('Write proposal recordId is not a valid Salesforce Id.');
        }

        String actualObjectName = validatedRecordId.getSObjectType().getDescribe().getName();
        if (actualObjectName != objectApiName) {
            throw new AuraHandledException('Write proposal objectType does not match the target record.');
        }

        Schema.SObjectType sobjectType = Schema.getGlobalDescribe().get(objectApiName);
        if (sobjectType == null) {
            throw new AuraHandledException('Unsupported objectType: ' + objectApiName);
        }

        Schema.DescribeSObjectResult objectDescribe = sobjectType.getDescribe();
        if (!objectDescribe.isUpdateable()) {
            throw new AuraHandledException('You do not have edit access to ' + objectApiName + '.');
        }

        if (!WRITE_PROPOSAL_ALLOWED_FIELDS_BY_OBJECT.containsKey(objectApiName)) {
            throw new AuraHandledException('Unsupported objectType: ' + objectApiName);
        }

        List<Object> rawFields = (List<Object>) proposal.get('fields');
        if (rawFields == null || rawFields.isEmpty()) {
            throw new AuraHandledException('Write proposal contains no fields to review.');
        }

        Map<String, Schema.SObjectField> fieldMap = objectDescribe.fields.getMap();
        List<WriteFieldPreview> fieldPreviews = new List<WriteFieldPreview>();
        List<String> selectFields = new List<String>();
        Map<String, String> referenceTargetNameFields = new Map<String, String>();
        Set<String> selectFieldSet = new Set<String>();

        String recordNameField = getNameFieldApiName(objectDescribe);
        if (!String.isBlank(recordNameField)) {
            selectFields.add(recordNameField);
            selectFieldSet.add(recordNameField);
        }
        if (fieldMap.containsKey('CurrencyIsoCode')) {
            selectFields.add('CurrencyIsoCode');
            selectFieldSet.add('CurrencyIsoCode');
        }

        for (Object rawField : rawFields) {
            Map<String, Object> fieldProposal;
            try {
                fieldProposal = (Map<String, Object>) rawField;
            } catch (Exception castException) {
                throw new AuraHandledException('Write proposal fields must be objects.');
            }
            String apiName = normalizeString(fieldProposal.get('apiName'));
            if (String.isBlank(apiName)) {
                throw new AuraHandledException('Write proposal field is missing apiName.');
            }
            if (!WRITE_PROPOSAL_ALLOWED_FIELDS_BY_OBJECT.get(objectApiName).contains(apiName)) {
                throw new AuraHandledException('Unsupported writable field: ' + apiName);
            }
            if (!fieldMap.containsKey(apiName)) {
                throw new AuraHandledException('Unsupported writable field: ' + apiName);
            }

            Schema.DescribeFieldResult fieldDescribe = fieldMap.get(apiName).getDescribe();
            validateWritableField(fieldDescribe, apiName);

            Object normalizedValue = normalizeProposedValue(fieldDescribe, fieldProposal.get('proposedValue'));

            fieldPreviews.add(new WriteFieldPreview(
                apiName,
                fieldDescribe.getLabel(),
                String.valueOf(fieldDescribe.getType()).toLowerCase(),
                normalizedValue,
                fieldProposal.get('proposedLabel')
            ));

            selectFields.add(apiName);
            selectFieldSet.add(apiName);

            if (String.valueOf(fieldDescribe.getType()).toLowerCase() == 'reference') {
                String relationshipName = fieldDescribe.getRelationshipName();
                String targetNameField = getReferenceTargetNameField(fieldDescribe);
                if (!String.isBlank(relationshipName) && !String.isBlank(targetNameField)) {
                    String displayPath = relationshipName + '.' + targetNameField;
                    referenceTargetNameFields.put(apiName, targetNameField);
                    if (!selectFieldSet.contains(displayPath)) {
                        selectFields.add(displayPath);
                        selectFieldSet.add(displayPath);
                    }
                }
            }
        }

        String soql = 'SELECT ' + String.join(selectFields, ', ') +
            ' FROM ' + objectApiName +
            ' WHERE Id = :validatedRecordId LIMIT 1';
        SObject record = Database.query(soql);
        if (record == null) {
            throw new AuraHandledException('The target record could not be found.');
        }

        String recordLabel = String.isBlank(recordNameField) ? recordId : stringValue(record.get(recordNameField));
        String currencyIsoCode = fieldMap.containsKey('CurrencyIsoCode') && record != null && record.get('CurrencyIsoCode') != null
            ? String.valueOf(record.get('CurrencyIsoCode'))
            : null;
        String summary = normalizeString(proposal.get('summary'));
        if (String.isBlank(summary)) {
            summary = 'Review the proposed edit for ' + (String.isBlank(recordLabel) ? objectDescribe.getLabel() : recordLabel);
        }

        Map<String, Object> response = new Map<String, Object>();
        response.put('kind', 'edit');
        response.put('objectApiName', objectApiName);
        response.put('objectLabel', objectDescribe.getLabel());
        response.put('recordId', recordId);
        response.put('recordLabel', recordLabel);
        response.put('summary', summary);

        List<Object> previewFields = new List<Object>();
        for (WriteFieldPreview preview : fieldPreviews) {
            Schema.DescribeFieldResult fieldDescribe = fieldMap.get(preview.apiName).getDescribe();
            Object currentRaw = record.get(preview.apiName);
            String currentDisplay = formatDisplayValue(fieldDescribe, currentRaw, record, currencyIsoCode, null, referenceTargetNameFields.get(preview.apiName));
            String proposedDisplay = formatDisplayValue(fieldDescribe, preview.proposedValue, record, currencyIsoCode, preview.proposedLabel, referenceTargetNameFields.get(preview.apiName));

            Map<String, Object> fieldPayload = new Map<String, Object>();
            fieldPayload.put('apiName', preview.apiName);
            fieldPayload.put('label', preview.label);
            fieldPayload.put('dataType', preview.dataType);
            fieldPayload.put('currentValue', currentRaw);
            fieldPayload.put('currentValueDisplay', currentDisplay);
            fieldPayload.put('proposedValue', preview.proposedValue);
            fieldPayload.put('proposedValueDisplay', proposedDisplay);
            fieldPayload.put('updateable', fieldDescribe.isUpdateable());
            fieldPayload.put('required', !fieldDescribe.isNillable() && !fieldDescribe.isDefaultedOnCreate());
            fieldPayload.put('lookupTarget', getLookupTargetName(fieldDescribe));
            previewFields.add(fieldPayload);
        }

        response.put('fields', previewFields);
        return response;
    }

    private static void validateWritableField(Schema.DescribeFieldResult fieldDescribe, String apiName) {
        String dataType = String.valueOf(fieldDescribe.getType()).toLowerCase();
        Set<String> supportedTypes = new Set<String>{
            'string', 'phone', 'email', 'url', 'textarea', 'picklist', 'multipicklist',
            'date', 'datetime', 'currency', 'double', 'int', 'integer', 'percent', 'boolean', 'reference'
        };

        if (!fieldDescribe.isAccessible() || !fieldDescribe.isUpdateable()) {
            throw new AuraHandledException('Field is not editable: ' + apiName);
        }
        if (fieldDescribe.isCalculated() || fieldDescribe.isAutoNumber()) {
            throw new AuraHandledException('Field is not editable: ' + apiName);
        }
        if (!supportedTypes.contains(dataType)) {
            throw new AuraHandledException('Unsupported field type for write proposal: ' + apiName);
        }
        if (dataType == 'reference' && fieldDescribe.getReferenceTo() != null && fieldDescribe.getReferenceTo().size() != 1) {
            throw new AuraHandledException('Unsupported lookup field for write proposal: ' + apiName);
        }
    }

    private static Object normalizeProposedValue(Schema.DescribeFieldResult fieldDescribe, Object rawValue) {
        if (rawValue == null) {
            return null;
        }

        String dataType = String.valueOf(fieldDescribe.getType()).toLowerCase();
        if (dataType == 'boolean') {
            if (rawValue instanceof Boolean) {
                return rawValue;
            }
            String normalized = normalizeString(rawValue);
            if (normalized == 'true') return true;
            if (normalized == 'false') return false;
            throw new AuraHandledException('Boolean field received an invalid value.');
        }

        if (dataType == 'picklist' || dataType == 'multipicklist') {
            return normalizePicklistValue(fieldDescribe, rawValue);
        }

        if (dataType == 'reference') {
            String referenceValue = normalizeString(rawValue);
            if (String.isBlank(referenceValue)) {
                return null;
            }
            try {
                Id.valueOf(referenceValue);
            } catch (Exception e) {
                throw new AuraHandledException('Lookup field received an invalid Salesforce Id.');
            }
            return referenceValue;
        }

        return rawValue;
    }

    private static Object normalizePicklistValue(Schema.DescribeFieldResult fieldDescribe, Object rawValue) {
        if (rawValue == null) {
            return null;
        }

        if (String.valueOf(fieldDescribe.getType()).toLowerCase() == 'multipicklist') {
            List<String> values = new List<String>();
            for (String part : normalizeString(rawValue).split(';')) {
                String normalized = part != null ? part.trim() : '';
                if (!String.isBlank(normalized)) {
                    values.add(normalizeSinglePicklistValue(fieldDescribe, normalized));
                }
            }
            return String.join(values, ';');
        }

        return normalizeSinglePicklistValue(fieldDescribe, normalizeString(rawValue));
    }

    private static String normalizeSinglePicklistValue(Schema.DescribeFieldResult fieldDescribe, String rawValue) {
        if (String.isBlank(rawValue)) {
            return null;
        }

        for (Schema.PicklistEntry entry : fieldDescribe.getPicklistValues()) {
            if (entry.getValue() == rawValue || entry.getLabel() == rawValue) {
                return entry.getValue();
            }
        }

        throw new AuraHandledException('Unsupported picklist value: ' + rawValue);
    }

    private static String getNameFieldApiName(Schema.DescribeSObjectResult objectDescribe) {
        for (Schema.SObjectField fieldRef : objectDescribe.fields.getMap().values()) {
            Schema.DescribeFieldResult fieldDescribe = fieldRef.getDescribe();
            if (fieldDescribe.isNameField()) {
                return fieldDescribe.getName();
            }
        }
        return null;
    }

    private static String getReferenceTargetNameField(Schema.DescribeFieldResult fieldDescribe) {
        List<Schema.SObjectType> targets = fieldDescribe.getReferenceTo();
        if (targets == null || targets.isEmpty()) {
            return null;
        }

        Schema.DescribeSObjectResult targetDescribe = targets[0].getDescribe();
        return getNameFieldApiName(targetDescribe);
    }

    private static String getLookupTargetName(Schema.DescribeFieldResult fieldDescribe) {
        List<Schema.SObjectType> targets = fieldDescribe.getReferenceTo();
        if (targets == null || targets.isEmpty()) {
            return null;
        }
        return targets[0].getDescribe().getName();
    }

    private static String formatDisplayValue(Schema.DescribeFieldResult fieldDescribe, Object rawValue, SObject record) {
        return formatDisplayValue(fieldDescribe, rawValue, record, null, null, null);
    }

    private static String formatDisplayValue(
        Schema.DescribeFieldResult fieldDescribe,
        Object rawValue,
        SObject record,
        String currencyIsoCode,
        Object explicitLabel,
        String referenceNameField
    ) {
        String dataType = String.valueOf(fieldDescribe.getType()).toLowerCase();
        if (rawValue == null || String.isBlank(stringValue(rawValue))) {
            return '(empty)';
        }

        if (explicitLabel != null && dataType == 'reference') {
            String labelValue = stringValue(explicitLabel);
            if (!String.isBlank(labelValue)) {
                return labelValue;
            }
        }

        if (dataType == 'reference') {
            Object currentRaw = record != null ? record.get(fieldDescribe.getName()) : null;
            if (currentRaw != null && String.valueOf(currentRaw) != String.valueOf(rawValue)) {
                return String.valueOf(rawValue);
            }

            String relationshipName = fieldDescribe.getRelationshipName();
            if (!String.isBlank(relationshipName)) {
                SObject related = record.getSObject(relationshipName);
                if (related != null && !String.isBlank(referenceNameField)) {
                    Object display = related.get(referenceNameField);
                    if (display != null) {
                        return String.valueOf(display);
                    }
                }
            }
            return String.valueOf(rawValue);
        }

        if (dataType == 'picklist') {
            String raw = String.valueOf(rawValue);
            for (Schema.PicklistEntry entry : fieldDescribe.getPicklistValues()) {
                if (entry.getValue() == raw) {
                    return entry.getLabel();
                }
            }
            return raw;
        }

        if (dataType == 'multipicklist') {
            List<String> labels = new List<String>();
            for (String valuePart : String.valueOf(rawValue).split(';')) {
                String trimmed = valuePart != null ? valuePart.trim() : '';
                if (String.isBlank(trimmed)) {
                    continue;
                }
                Boolean matched = false;
                for (Schema.PicklistEntry entry : fieldDescribe.getPicklistValues()) {
                    if (entry.getValue() == trimmed) {
                        labels.add(entry.getLabel());
                        matched = true;
                        break;
                    }
                }
                if (!matched) {
                    labels.add(trimmed);
                }
            }
            return String.join(labels, '; ');
        }

        if (dataType == 'date') {
            if (rawValue instanceof Date) {
                return ((Date) rawValue).format();
            }
            try {
                return Date.valueOf(String.valueOf(rawValue)).format();
            } catch (Exception e) {
                return String.valueOf(rawValue);
            }
        }

        if (dataType == 'datetime') {
            if (rawValue instanceof Datetime) {
                return ((Datetime) rawValue).format();
            }
            try {
                String normalized = String.valueOf(rawValue).replace('T', ' ').replace('Z', '');
                return Datetime.valueOf(normalized).format();
            } catch (Exception e) {
                return String.valueOf(rawValue);
            }
        }

        if (dataType == 'boolean') {
            return ((Boolean) rawValue) ? 'Yes' : 'No';
        }

        if (dataType == 'currency') {
            Decimal amount = Decimal.valueOf(String.valueOf(rawValue));
            String formattedAmount = amount.setScale(2).format();
            if (!String.isBlank(currencyIsoCode)) {
                return currencyIsoCode + ' ' + formattedAmount;
            }
            return '$' + formattedAmount;
        }

        if (dataType == 'double' || dataType == 'int' || dataType == 'integer' || dataType == 'percent') {
            return String.valueOf(rawValue);
        }

        if (dataType == 'phone') {
            return formatPhoneValue(String.valueOf(rawValue));
        }

        return String.valueOf(rawValue);
    }

    private static String formatPhoneValue(String rawValue) {
        if (String.isBlank(rawValue)) {
            return '(empty)';
        }

        String digits = rawValue.replaceAll('[^0-9]', '');

        if (digits.length() == 10) {
            return '(' + digits.substring(0, 3) + ') ' + digits.substring(3, 6) + '-' + digits.substring(6, 10);
        }
        return rawValue;
    }

    private static String normalizeString(Object value) {
        return value == null ? null : String.valueOf(value).trim();
    }

    private static String stringValue(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private class WriteFieldPreview {
        public String apiName;
        public String label;
        public String dataType;
        public Object proposedValue;
        public Object proposedLabel;

        public WriteFieldPreview(String apiName, String label, String dataType, Object proposedValue, Object proposedLabel) {
            this.apiName = apiName;
            this.label = label;
            this.dataType = dataType;
            this.proposedValue = proposedValue;
            this.proposedLabel = proposedLabel;
        }
    }

    private static void handleErrorResponse(HttpResponse res) {
        String errorMsg = 'Error calling AI Search API: ' + res.getStatus() + ' - ' + res.getBody();
        
        if (res.getStatusCode() == 400) {
            try {
                Map<String, Object> errorData = (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
                String apiError = (String) errorData.get('error');
                errorMsg = 'Validation error: ' + apiError;
            } catch (Exception e) {
                errorMsg = 'Validation error (400)';
            }
        } else if (res.getStatusCode() == 403) {
            errorMsg = 'Access denied: You don\'t have permission to perform this action.';
        } else if (res.getStatusCode() == 429) {
            errorMsg = 'Rate limit exceeded. Please try again later.';
        } else if (res.getStatusCode() == 503) {
            errorMsg = 'Service unavailable. Please try again later.';
        } else if (res.getStatusCode() == 504) {
            errorMsg = 'Request timeout. Please try again.';
        }
        
        AuraHandledException e = new AuraHandledException(errorMsg);
        e.setMessage(errorMsg);
        throw e;
    }
}
