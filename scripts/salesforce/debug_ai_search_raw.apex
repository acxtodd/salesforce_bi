String NAMED_CREDENTIAL = 'callout:Ascendix_RAG_API';
String API_KEY = 'M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ';
Integer TIMEOUT_MS = 120000;

try {
    String requestBodyJson = '{"sessionId": "debug_session_raw", "query": "computer", "topK": 8, "policy": {"require_citations": true, "max_tokens": 1000}, "salesforceUserId": "' + UserInfo.getUserId() + '"}';
    Map<String, Object> requestBody = (Map<String, Object>) JSON.deserializeUntyped(requestBodyJson);

    HttpRequest req = new HttpRequest();
    req.setEndpoint(NAMED_CREDENTIAL + '/answer');
    req.setMethod('POST');
    req.setHeader('Content-Type', 'application/json');
    req.setHeader('x-api-key', API_KEY);
    req.setTimeout(TIMEOUT_MS);
    req.setBody(JSON.serialize(requestBody));

    Http http = new Http();
    HttpResponse res = http.send(req);

    System.debug('STATUS: ' + res.getStatusCode());
    System.debug('RAW_BODY_START');
    System.debug(res.getBody());
    System.debug('RAW_BODY_END');

} catch (Exception e) {
    System.debug('ERROR: ' + e.getMessage());
    System.debug('STACK: ' + e.getStackTraceString());
}