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
        System.assert(result.containsKey('writeProposal'));
        Map<String, Object> writeProposal = (Map<String, Object>) result.get('writeProposal');
        System.assertEquals('edit', writeProposal.get('kind'));
        System.assertEquals('Contact', writeProposal.get('objectType'));
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

    @isTest
    static void testPreviewWriteProposalContactFormatsCurrentAndProposedValues() {
        Account account = new Account(Name = 'Northwind');
        insert account;

        Contact contact = new Contact(
            LastName = 'Smith',
            AccountId = account.Id,
            Phone = '2145551234',
            MailingCity = 'Dallas'
        );
        insert contact;

        Account secondAccount = new Account(Name = 'Southwind');
        insert secondAccount;

        Map<String, Object> proposal = new Map<String, Object>{
            'kind' => 'edit',
            'objectType' => 'Contact',
            'recordId' => contact.Id,
            'summary' => 'Update contact',
            'fields' => new List<Object>{
                new Map<String, Object>{
                    'apiName' => 'Phone',
                    'proposedValue' => '4695559988'
                },
                new Map<String, Object>{
                    'apiName' => 'MailingCity',
                    'proposedValue' => 'Austin'
                },
                new Map<String, Object>{
                    'apiName' => 'AccountId',
                    'proposedValue' => secondAccount.Id
                }
            }
        };

        Test.startTest();
        Map<String, Object> preview = AscendixAISearchController.previewWriteProposal(JSON.serialize(proposal));
        Test.stopTest();

        System.assertEquals('Contact', preview.get('objectApiName'));
        System.assertEquals(contact.Id, preview.get('recordId'));
        System.assertEquals('Update contact', preview.get('summary'));

        List<Object> fields = (List<Object>) preview.get('fields');
        System.assertEquals(3, fields.size());

        Map<String, Object> phoneField = (Map<String, Object>) fields[0];
        System.assertEquals('Phone', phoneField.get('apiName'));
        System.assert(((String) phoneField.get('currentValueDisplay')).contains('214') || ((String) phoneField.get('currentValueDisplay')).contains('-'));
        System.assert(((String) phoneField.get('proposedValueDisplay')).contains('469'));

        Map<String, Object> cityField = (Map<String, Object>) fields[1];
        System.assertEquals('MailingCity', cityField.get('apiName'));
        System.assertEquals('Dallas', cityField.get('currentValueDisplay'));
        System.assertEquals('Austin', cityField.get('proposedValueDisplay'));

        Map<String, Object> accountField = (Map<String, Object>) fields[2];
        System.assertEquals('AccountId', accountField.get('apiName'));
        System.assertEquals('Northwind', accountField.get('currentValueDisplay'));
        System.assertEquals(String.valueOf(secondAccount.Id), accountField.get('proposedValueDisplay'));
    }

    @isTest
    static void testPreviewWriteProposalAccountFormatsCurrencyNumberAndPicklist() {
        List<Schema.PicklistEntry> industryValues = Account.Industry.getDescribe().getPicklistValues();
        System.assert(industryValues.size() >= 2, 'Expected Account.Industry to expose at least two picklist values for the test.');
        String currentIndustry = industryValues[0].getValue();
        String proposedIndustry = industryValues[1].getValue();

        Account account = new Account(
            Name = 'Globex',
            AnnualRevenue = 1250000,
            NumberOfEmployees = 42,
            Industry = currentIndustry
        );
        insert account;

        Map<String, Object> proposal = new Map<String, Object>{
            'kind' => 'edit',
            'objectType' => 'Account',
            'recordId' => account.Id,
            'summary' => 'Update account details',
            'fields' => new List<Object>{
                new Map<String, Object>{
                    'apiName' => 'AnnualRevenue',
                    'proposedValue' => 2500000
                },
                new Map<String, Object>{
                    'apiName' => 'NumberOfEmployees',
                    'proposedValue' => 100
                },
                new Map<String, Object>{
                    'apiName' => 'Industry',
                    'proposedValue' => proposedIndustry
                }
            }
        };

        Test.startTest();
        Map<String, Object> preview = AscendixAISearchController.previewWriteProposal(JSON.serialize(proposal));
        Test.stopTest();

        List<Object> fields = (List<Object>) preview.get('fields');
        System.assertEquals(3, fields.size());

        Map<String, Object> revenueField = (Map<String, Object>) fields[0];
        System.assertEquals('AnnualRevenue', revenueField.get('apiName'));
        System.assert(((String) revenueField.get('currentValueDisplay')).contains('$'));
        System.assert(((String) revenueField.get('proposedValueDisplay')).contains('$'));

        Map<String, Object> employeeField = (Map<String, Object>) fields[1];
        System.assertEquals('NumberOfEmployees', employeeField.get('apiName'));
        System.assertEquals('42', String.valueOf(employeeField.get('currentValueDisplay')));
        System.assertEquals('100', String.valueOf(employeeField.get('proposedValueDisplay')));

        Map<String, Object> industryField = (Map<String, Object>) fields[2];
        System.assertEquals('Industry', industryField.get('apiName'));
        System.assertEquals(currentIndustry, industryField.get('currentValueDisplay'));
        System.assertEquals(proposedIndustry, industryField.get('proposedValueDisplay'));
    }

    @isTest
    static void testPreviewWriteProposalRejectsUnsupportedObject() {
        Account account = new Account(Name = 'Restricted Acme');
        insert account;

        Opportunity opportunity = new Opportunity(
            Name = 'Unsupported Proposal',
            StageName = 'Prospecting',
            CloseDate = Date.today().addDays(30),
            AccountId = account.Id
        );
        insert opportunity;

        Map<String, Object> proposal = new Map<String, Object>{
            'kind' => 'edit',
            'objectType' => 'Opportunity',
            'recordId' => opportunity.Id,
            'fields' => new List<Object>{
                new Map<String, Object>{
                    'apiName' => 'Name',
                    'proposedValue' => 'Unsupported'
                }
            }
        };

        Test.startTest();
        try {
            AscendixAISearchController.previewWriteProposal(JSON.serialize(proposal));
            System.assert(false, 'Expected unsupported object to be rejected.');
        } catch (Exception e) {
            System.assertNotEquals(null, e.getMessage());
        }
        Test.stopTest();
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
                        'event: done\ndata: {"tool_calls": 1, "turns": 1, "writeProposal": {"kind": "edit", "objectType": "Contact", "recordId": "003000000000001AAA", "fields": [{"apiName": "Phone", "proposedValue": "4695559988"}]}}\n\n'
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
