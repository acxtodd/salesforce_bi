/**
 * Apex class for removing AI_Agent_Actions_Editor permission set assignments
 * Used as part of the kill switch mechanism to disable agent actions
 */
public with sharing class ActionPermissionSetRemoval {
    
    private static final String PERMISSION_SET_NAME = 'AI_Agent_Actions_Editor';
    
    /**
     * Removes all assignments of the AI_Agent_Actions_Editor permission set
     * Uses Database.delete with allOrNone=false to handle partial failures
     * 
     * @return Map containing success count, failure count, and error details
     */
    @InvocableMethod(label='Remove AI Agent Actions Permission Set' 
                     description='Removes AI_Agent_Actions_Editor permission set from all users'
                     category='AI Agent Actions')
    public static List<RemovalResult> removePermissionSetAssignments() {
        RemovalResult result = new RemovalResult();
        result.errors = new List<String>();
        
        try {
            // Query the permission set
            List<PermissionSet> permSets = [
                SELECT Id, Name
                FROM PermissionSet
                WHERE Name = :PERMISSION_SET_NAME
                LIMIT 1
            ];
            
            if (permSets.isEmpty()) {
                result.success = false;
                result.message = 'Permission set not found: ' + PERMISSION_SET_NAME;
                result.errors.add(result.message);
                return new List<RemovalResult>{ result };
            }
            
            Id permissionSetId = permSets[0].Id;
            
            // Query all assignments
            List<PermissionSetAssignment> assignments = [
                SELECT Id, AssigneeId, Assignee.Name, Assignee.Username
                FROM PermissionSetAssignment
                WHERE PermissionSetId = :permissionSetId
            ];
            
            if (assignments.isEmpty()) {
                result.success = true;
                result.message = 'No permission set assignments found to remove';
                result.successCount = 0;
                result.failureCount = 0;
                return new List<RemovalResult>{ result };
            }
            
            Integer totalAssignments = assignments.size();
            
            // Delete assignments with allOrNone=false to handle partial failures
            Database.DeleteResult[] deleteResults = Database.delete(assignments, false);
            
            // Process results
            Integer successCount = 0;
            Integer failureCount = 0;
            
            for (Integer i = 0; i < deleteResults.size(); i++) {
                Database.DeleteResult dr = deleteResults[i];
                PermissionSetAssignment assignment = assignments[i];
                
                if (dr.isSuccess()) {
                    successCount++;
                } else {
                    failureCount++;
                    String errorMsg = 'Failed to remove permission set from user ' + 
                                    assignment.Assignee.Username + ' (' + assignment.AssigneeId + '): ';
                    
                    for (Database.Error err : dr.getErrors()) {
                        errorMsg += err.getMessage() + '; ';
                    }
                    
                    result.errors.add(errorMsg);
                }
            }
            
            result.successCount = successCount;
            result.failureCount = failureCount;
            result.success = (failureCount == 0);
            result.message = String.format(
                'Removed {0} of {1} permission set assignments. {2} failures.',
                new List<Object>{ successCount, totalAssignments, failureCount }
            );
            
            // Log the operation
            System.debug('Permission set removal completed: ' + result.message);
            if (!result.errors.isEmpty()) {
                System.debug('Errors: ' + String.join(result.errors, '\n'));
            }
            
        } catch (Exception e) {
            result.success = false;
            result.message = 'Error removing permission set assignments: ' + e.getMessage();
            result.errors.add(e.getStackTraceString());
        }
        
        return new List<RemovalResult>{ result };
    }
    
    /**
     * Queries current permission set assignments for reporting
     * @return List of user details with the permission set assigned
     */
    @AuraEnabled(cacheable=true)
    public static List<UserAssignment> getCurrentAssignments() {
        List<UserAssignment> userAssignments = new List<UserAssignment>();
        
        try {
            List<PermissionSet> permSets = [
                SELECT Id
                FROM PermissionSet
                WHERE Name = :PERMISSION_SET_NAME
                LIMIT 1
            ];
            
            if (permSets.isEmpty()) {
                return userAssignments;
            }
            
            List<PermissionSetAssignment> assignments = [
                SELECT 
                    Id,
                    AssigneeId,
                    Assignee.Name,
                    Assignee.Username,
                    Assignee.Email,
                    Assignee.Profile.Name,
                    Assignee.IsActive
                FROM PermissionSetAssignment
                WHERE PermissionSetId = :permSets[0].Id
                ORDER BY Assignee.Name
            ];
            
            for (PermissionSetAssignment assignment : assignments) {
                UserAssignment ua = new UserAssignment();
                ua.userId = assignment.AssigneeId;
                ua.name = assignment.Assignee.Name;
                ua.username = assignment.Assignee.Username;
                ua.email = assignment.Assignee.Email;
                ua.profileName = assignment.Assignee.Profile.Name;
                ua.isActive = assignment.Assignee.IsActive;
                userAssignments.add(ua);
            }
            
        } catch (Exception e) {
            throw new AuraHandledException('Error querying assignments: ' + e.getMessage());
        }
        
        return userAssignments;
    }
    
    /**
     * Result class for invocable method
     */
    public class RemovalResult {
        @InvocableVariable(label='Success' description='Whether the operation succeeded')
        public Boolean success;
        
        @InvocableVariable(label='Message' description='Summary message')
        public String message;
        
        @InvocableVariable(label='Success Count' description='Number of successful removals')
        public Integer successCount;
        
        @InvocableVariable(label='Failure Count' description='Number of failed removals')
        public Integer failureCount;
        
        @InvocableVariable(label='Errors' description='List of error messages')
        public List<String> errors;
    }
    
    /**
     * User assignment details for UI display
     */
    public class UserAssignment {
        @AuraEnabled public String userId;
        @AuraEnabled public String name;
        @AuraEnabled public String username;
        @AuraEnabled public String email;
        @AuraEnabled public String profileName;
        @AuraEnabled public Boolean isActive;
    }
}
