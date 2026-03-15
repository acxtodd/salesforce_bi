public with sharing class AscendixAISearchController {
    
    private static final String NAMED_CREDENTIAL = 'callout:Ascendix_RAG_API';
    private static final Integer TIMEOUT_MS = 120000; // 120 seconds
    private static final String API_KEY = 'M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ'; // POC Workaround
    
    /**
     * Call the /answer endpoint with streaming support
     */
    @AuraEnabled
    public static Map<String, Object> callAnswerEndpoint(String requestBodyJson) {
        try {
            Map<String, Object> requestBody = (Map<String, Object>) JSON.deserializeUntyped(requestBodyJson);

            // Build payload for /query endpoint: question, org_id, session_id
            Map<String, Object> newPayload = new Map<String, Object>();
            newPayload.put('question', (String) requestBody.get('query'));
            newPayload.put('org_id', UserInfo.getOrganizationId());
            newPayload.put('session_id', (String) requestBody.get('sessionId'));

            HttpRequest req = new HttpRequest();
            req.setEndpoint(NAMED_CREDENTIAL + '/query');
            req.setMethod('POST');
            req.setHeader('Content-Type', 'application/json');
            req.setHeader('x-api-key', API_KEY); // Manual header for POC
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
            req.setHeader('x-api-key', API_KEY); // Manual header for POC
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
            req.setHeader('x-api-key', API_KEY); // Manual header for POC
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