@isTest
private class AscendixAISearchControllerTest {
    
    @isTest
    static void testCallAnswerEndpoint() {
        Test.setMock(HttpCalloutMock.class, new AISearchMock(200));

        Test.startTest();
        Map<String, Object> result = AscendixAISearchController.callAnswerEndpoint('{"query": "test", "sessionId": "sess_123"}');
        Test.stopTest();

        System.assert(result != null);
        // Verify SSE parsing: answer assembled from token events
        System.assertEquals('Test answer', (String) result.get('answer'));
        // Verify citations transformed from {id, name} to {recordId, title, id}
        List<Object> citations = (List<Object>) result.get('citations');
        System.assert(citations != null && citations.size() == 1);
        Map<String, Object> citation = (Map<String, Object>) citations[0];
        System.assertEquals('a0x001', citation.get('recordId'));
        System.assertEquals('Test Record', citation.get('title'));
        System.assertEquals('a0x001', citation.get('id'));
    }
    
    @isTest
    static void testCallAnswerEndpointError() {
        Test.setMock(HttpCalloutMock.class, new AISearchMock(500));
        
        Test.startTest();
        try {
            AscendixAISearchController.callAnswerEndpoint('{"query": "test"}');
        } catch (Exception e) {
            System.assert(e.getMessage() != null);
        }
        Test.stopTest();
    }

    @isTest
    static void testCallRetrieveEndpoint() {
        Test.setMock(HttpCalloutMock.class, new AISearchMock(200));
        
        Test.startTest();
        Map<String, Object> result = AscendixAISearchController.callRetrieveEndpoint('{"query": "test"}');
        Test.stopTest();
        
        System.assert(result != null);
    }
    
    @isTest
    static void testCallActionEndpoint() {
        Test.setMock(HttpCalloutMock.class, new AISearchMock(200));
        
        Test.startTest();
        Map<String, Object> result = AscendixAISearchController.callActionEndpoint('{"action": "test"}');
        Test.stopTest();
        
        System.assert(result != null);
    }
    
    @isTest
    static void testCallActionEndpointValidation() {
        Test.setMock(HttpCalloutMock.class, new AISearchMock(400));
        
        Test.startTest();
        try {
            AscendixAISearchController.callActionEndpoint('{"action": "test"}');
        } catch (Exception e) {
            System.assert(e.getMessage() != null);
        }
        Test.stopTest();
    }

    @isTest
    static void testGetCurrentUserId() {
        String userId = AscendixAISearchController.getCurrentUserId();
        System.assertEquals(UserInfo.getUserId(), userId);
    }
    
    private class AISearchMock implements HttpCalloutMock {
        private Integer statusCode;

        public AISearchMock(Integer statusCode) {
            this.statusCode = statusCode;
        }

        public HttpResponse respond(HttpRequest req) {
            HttpResponse res = new HttpResponse();
            res.setStatusCode(statusCode);

            String endpoint = req.getEndpoint();
            String apiKeyHeader = req.getHeader('x-api-key');

            // Assert no hardcoded API key in any callout
            System.assertNotEquals('M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ', apiKeyHeader,
                'API key must not be hardcoded — use External Credential merge field');

            // Assert /query uses the Query Named Credential
            if (endpoint != null && endpoint.contains('/query')) {
                System.assert(endpoint.startsWith('callout:Ascendix_RAG_Query_API'),
                    'callAnswerEndpoint must use QUERY_CREDENTIAL, got: ' + endpoint);
            }
            // Assert /retrieve and /action use the original Named Credential
            if (endpoint != null && (endpoint.contains('/retrieve') || endpoint.contains('/action'))) {
                System.assert(endpoint.startsWith('callout:Ascendix_RAG_API'),
                    'retrieve/action must use NAMED_CREDENTIAL, got: ' + endpoint);
            }

            if (statusCode == 200) {
                if (endpoint != null && endpoint.contains('/query')) {
                    // Return SSE format matching new /query Lambda contract
                    res.setHeader('Content-Type', 'text/event-stream');
                    res.setBody(
                        'event: token\ndata: {"text": "Test answer"}\n\n' +
                        'event: citations\ndata: {"citations": [{"id": "a0x001", "name": "Test Record"}]}\n\n' +
                        'event: done\ndata: {"tool_calls": 1, "turns": 1}\n\n'
                    );
                } else {
                    res.setBody('{"result": "success"}');
                }
            } else if (statusCode == 400) {
                res.setBody('{"error": "Validation error"}');
            } else {
                res.setBody('{"error": "Server error"}');
            }
            return res;
        }
    }
}
