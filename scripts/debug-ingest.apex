// Debug script to test Ingest Endpoint
AI_Search_Config__mdt config = [
    SELECT Ingest_Endpoint__c, API_Key__c 
    FROM AI_Search_Config__mdt 
    WHERE DeveloperName = 'Default' 
    LIMIT 1
];

String endpoint = config.Ingest_Endpoint__c;
String apiKey = config.API_Key__c;

System.debug('Endpoint: ' + endpoint);

Map<String, Object> payload = new Map<String, Object>{
    'sobject' => 'DebugObject',
    'operation' => 'upsert',
    'records' => new List<Map<String, Object>>{
        new Map<String, Object>{'Id' => '001000000000001', 'Name' => 'Debug Record'}
    },
    'source' => 'debug_script',
    'timestamp' => DateTime.now().formatGMT('yyyy-MM-dd\'T\'HH:mm:ss\'Z\'')
};

String jsonPayload = JSON.serialize(payload);

HttpRequest req = new HttpRequest();
req.setEndpoint(endpoint);
req.setMethod('POST');
req.setHeader('Content-Type', 'application/json');
req.setHeader('x-api-key', apiKey);
req.setBody(jsonPayload);
req.setTimeout(120000);

try {
    Http http = new Http();
    HttpResponse res = http.send(req);
    
    System.debug('STATUS: ' + res.getStatusCode());
    System.debug('BODY: ' + res.getBody());
} catch (Exception e) {
    System.debug('ERROR: ' + e.getMessage());
}
