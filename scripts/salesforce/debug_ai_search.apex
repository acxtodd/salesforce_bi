try {
    String requestBodyJson = '{"sessionId": "debug_session_002", "query": "companies in dallas", "topK": 8, "policy": {"require_citations": true, "max_tokens": 1000}}';
    Map<String, Object> result = AscendixAISearchController.callAnswerEndpoint(requestBodyJson);
    System.debug('SUCCESS: ' + JSON.serializePretty(result));
} catch (Exception e) {
    System.debug('ERROR: ' + e.getMessage());
    System.debug('STACK: ' + e.getStackTraceString());
}