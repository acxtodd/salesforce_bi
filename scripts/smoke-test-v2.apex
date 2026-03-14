HttpRequest req = new HttpRequest();
req.setEndpoint('callout:Ascendix_RAG_API/answer');
req.setMethod('POST');
req.setHeader('Content-Type', 'application/json');
req.setHeader('x-api-key', 'M3L9GKMhRs2j5e9KvD3Et6upEWtHUQHy7SgrvCSQ'); // POC Workaround
req.setTimeout(120000);
String body = '{"query": "Hello", "salesforceUserId": "' + UserInfo.getUserId() + '", "sessionId": "test-session", "topK": 1}';
req.setBody(body);

try {
    Http http = new Http();
    HttpResponse res = http.send(req);
    System.debug('STATUS_CODE: ' + res.getStatusCode());
    System.debug('RESPONSE_BODY: ' + res.getBody());
} catch (Exception e) {
    System.debug('ERROR: ' + e.getMessage());
}