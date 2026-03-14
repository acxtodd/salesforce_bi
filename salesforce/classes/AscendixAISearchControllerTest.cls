@isTest
private class AscendixAISearchControllerTest {
    
    @isTest
    static void testCallAnswerEndpoint() {
        Test.setMock(HttpCalloutMock.class, new AISearchMock(200));
        
        Test.startTest();
        Map<String, Object> result = AscendixAISearchController.callAnswerEndpoint('{"query": "test"}');
        Test.stopTest();
        
        System.assert(result != null);
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
            if (statusCode == 200) {
                res.setBody('{"result": "success"}');
            } else if (statusCode == 400) {
                res.setBody('{"error": "Validation error"}');
            } else {
                res.setBody('{"error": "Server error"}');
            }
            return res;
        }
    }
}
