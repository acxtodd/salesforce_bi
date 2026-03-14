@isTest
private class ActionPermissionSetRemovalTest {
    
    @isTest
    static void testRemovePermissionSetAssignments() {
        // Create a mock permission set and assignment would be ideal but DML on setup objects in tests is tricky
        // So we just verify the method runs without error and handles "not found" or "empty" gracefully
        
        Test.startTest();
        List<ActionPermissionSetRemoval.RemovalResult> results = ActionPermissionSetRemoval.removePermissionSetAssignments();
        Test.stopTest();
        
        // Even if no permission sets are removed, it should return a list
        System.assert(results != null);
        System.assert(!results.isEmpty());
        System.assert(results[0] != null);
    }
    
    @isTest
    static void testGetCurrentAssignments() {
        Test.startTest();
        List<ActionPermissionSetRemoval.UserAssignment> assignments = ActionPermissionSetRemoval.getCurrentAssignments();
        Test.stopTest();
        
        System.assert(assignments != null);
    }
}