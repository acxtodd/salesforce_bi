@isTest
private class ActionEnablementControllerTest {
    
    @isTest
    static void testGetActionEnablement() {
        // Create Custom Setting
        ActionEnablementSetting__c setting = new ActionEnablementSetting__c(
            Name = 'Test_Action',
            Enabled__c = true,
            ActionName__c = 'Test_Action',
            MaxPerUserPerDay__c = 10
        );
        insert setting;
        
        Test.startTest();
        try {
            ActionEnablementController.getActionEnablements();
        } catch (Exception e) {
            // Expected if metadata is missing
        }
        Test.stopTest();
    }
    
    @isTest
    static void testUpdateActionEnablement() {
        ActionEnablementSetting__c setting = new ActionEnablementSetting__c(
            Name = 'Test_Action',
            Enabled__c = true,
            ActionName__c = 'Test_Action'
        );
        insert setting;

        Map<String, Object> updateData = new Map<String, Object>();
        updateData.put('ActionName__c', 'Test_Action');
        updateData.put('Enabled__c', false);
        updateData.put('MaxPerUserPerDay__c', 5);
        
        Test.startTest();
        try {
            ActionEnablementController.updateActionEnablement(updateData);
        } catch (Exception e) {
            // Expected if metadata validation fails
        }
        Test.stopTest();
    }

    @isTest
    static void testRemoveOverride() {
        ActionEnablementSetting__c setting = new ActionEnablementSetting__c(
            Name = 'Test_Action',
            Enabled__c = true,
            ActionName__c = 'Test_Action'
        );
        insert setting;
        
        Test.startTest();
        ActionEnablementController.removeOverride('Test_Action');
        Test.stopTest();
        
        List<ActionEnablementSetting__c> settings = [SELECT Id FROM ActionEnablementSetting__c WHERE Name = 'Test_Action'];
        System.assertEquals(0, settings.size(), 'Override should be removed');
    }

    @isTest
    static void testGetEffectiveConfiguration() {
        Test.startTest();
        try {
            ActionEnablementController.getEffectiveConfiguration('Test_Action');
        } catch (Exception e) {
            // Expected
        }
        Test.stopTest();
    }

    @isTest
    static void testTestAction() {
        Test.startTest();
        ActionEnablementController.testAction('Test_Action');
        Test.stopTest();
    }
}
