public with sharing class ActionEnablementController {
    
    /**
     * Retrieves all ActionEnablement__mdt records with runtime overrides from Custom Settings
     * @return List of action configurations with merged settings
     */
    @AuraEnabled(cacheable=true)
    public static List<Map<String, Object>> getActionEnablements() {
        try {
            // Query base configuration from Custom Metadata
            List<ActionEnablement__mdt> metadataRecords = [
                SELECT 
                    DeveloperName,
                    MasterLabel,
                    ActionName__c,
                    Enabled__c,
                    MaxPerUserPerDay__c,
                    RequiresConfirm__c,
                    FlowName__c,
                    ApexMethod__c,
                    InputSchemaJson__c,
                    OutputSchemaJson__c,
                    AllowedFields__c
                FROM ActionEnablement__mdt
                ORDER BY ActionName__c
            ];
            
            // Query runtime overrides from Custom Settings
            Map<String, ActionEnablementSetting__c> settingsMap = ActionEnablementSetting__c.getAll();
            
            // Merge metadata with runtime settings
            List<Map<String, Object>> results = new List<Map<String, Object>>();
            
            for (ActionEnablement__mdt metadata : metadataRecords) {
                Map<String, Object> record = new Map<String, Object>();
                
                // Copy all metadata fields
                record.put('DeveloperName', metadata.DeveloperName);
                record.put('MasterLabel', metadata.MasterLabel);
                record.put('ActionName__c', metadata.ActionName__c);
                record.put('RequiresConfirm__c', metadata.RequiresConfirm__c);
                record.put('FlowName__c', metadata.FlowName__c);
                record.put('ApexMethod__c', metadata.ApexMethod__c);
                record.put('InputSchemaJson__c', metadata.InputSchemaJson__c);
                record.put('OutputSchemaJson__c', metadata.OutputSchemaJson__c);
                record.put('AllowedFields__c', metadata.AllowedFields__c);
                
                // Check for runtime override
                ActionEnablementSetting__c setting = settingsMap.get(metadata.ActionName__c);
                
                if (setting != null) {
                    // Use runtime override values
                    record.put('Enabled__c', setting.Enabled__c);
                    record.put('MaxPerUserPerDay__c', setting.MaxPerUserPerDay__c);
                    record.put('HasOverride', true);
                    record.put('LastModifiedByAdmin__c', setting.LastModifiedByAdmin__c);
                } else {
                    // Use metadata defaults
                    record.put('Enabled__c', metadata.Enabled__c);
                    record.put('MaxPerUserPerDay__c', metadata.MaxPerUserPerDay__c);
                    record.put('HasOverride', false);
                }
                
                results.add(record);
            }
            
            return results;
            
        } catch (Exception e) {
            throw new AuraHandledException('Error retrieving action enablements: ' + e.getMessage());
        }
    }
    
    /**
     * Updates action enablement settings via Custom Setting (immediate effect)
     * @param actionData Map containing ActionName and fields to update
     * @return Success message
     */
    @AuraEnabled
    public static Map<String, Object> updateActionEnablement(Map<String, Object> actionData) {
        Map<String, Object> response = new Map<String, Object>();
        
        try {
            String actionName = (String) actionData.get('ActionName__c');
            
            if (String.isBlank(actionName)) {
                throw new AuraHandledException('ActionName is required');
            }
            
            // Verify the action exists in metadata
            List<ActionEnablement__mdt> existing = [
                SELECT ActionName__c, Enabled__c, MaxPerUserPerDay__c
                FROM ActionEnablement__mdt
                WHERE ActionName__c = :actionName
                LIMIT 1
            ];
            
            if (existing.isEmpty()) {
                throw new AuraHandledException('Action not found: ' + actionName);
            }
            
            // Get or create Custom Setting override
            ActionEnablementSetting__c setting = ActionEnablementSetting__c.getInstance(actionName);
            
            if (setting == null) {
                setting = new ActionEnablementSetting__c(
                    Name = actionName,
                    ActionName__c = actionName
                );
            }
            
            // Update only the fields that were provided
            Boolean hasChanges = false;
            
            if (actionData.containsKey('Enabled__c')) {
                Boolean newValue = (Boolean) actionData.get('Enabled__c');
                if (setting.Enabled__c != newValue) {
                    setting.Enabled__c = newValue;
                    hasChanges = true;
                }
            }
            
            if (actionData.containsKey('MaxPerUserPerDay__c')) {
                Decimal newValue = (Decimal) actionData.get('MaxPerUserPerDay__c');
                if (setting.MaxPerUserPerDay__c != newValue) {
                    setting.MaxPerUserPerDay__c = newValue;
                    hasChanges = true;
                }
            }
            
            if (!hasChanges) {
                response.put('success', true);
                response.put('message', 'No changes detected');
                return response;
            }
            
            // Update last modified info
            setting.LastModifiedByAdmin__c = UserInfo.getName();
            
            // Upsert the setting (immediate effect)
            upsert setting Name;
            
            response.put('success', true);
            response.put('message', 'Action enablement updated successfully. Changes take effect immediately.');
            
            return response;
            
        } catch (Exception e) {
            throw new AuraHandledException('Error updating action enablement: ' + e.getMessage());
        }
    }
    
    /**
     * Removes runtime override, reverting to metadata defaults
     * @param actionName The action name to reset
     * @return Success message
     */
    @AuraEnabled
    public static Map<String, Object> removeOverride(String actionName) {
        Map<String, Object> response = new Map<String, Object>();
        
        try {
            ActionEnablementSetting__c setting = ActionEnablementSetting__c.getInstance(actionName);
            
            if (setting != null && setting.Id != null) {
                delete setting;
                response.put('success', true);
                response.put('message', 'Override removed. Action reverted to metadata defaults.');
            } else {
                response.put('success', true);
                response.put('message', 'No override found for this action.');
            }
            
            return response;
            
        } catch (Exception e) {
            throw new AuraHandledException('Error removing override: ' + e.getMessage());
        }
    }
    
    /**
     * Gets the effective configuration for an action (used by Lambda)
     * Merges metadata with runtime overrides
     * @param actionName The action name
     * @return Effective configuration
     */
    @AuraEnabled(cacheable=false)
    public static Map<String, Object> getEffectiveConfiguration(String actionName) {
        try {
            // Query metadata
            List<ActionEnablement__mdt> metadataList = [
                SELECT 
                    ActionName__c,
                    Enabled__c,
                    MaxPerUserPerDay__c,
                    RequiresConfirm__c,
                    FlowName__c,
                    ApexMethod__c,
                    InputSchemaJson__c,
                    AllowedFields__c
                FROM ActionEnablement__mdt
                WHERE ActionName__c = :actionName
                LIMIT 1
            ];
            
            if (metadataList.isEmpty()) {
                return null;
            }
            
            ActionEnablement__mdt metadata = metadataList[0];
            Map<String, Object> config = new Map<String, Object>();
            
            // Start with metadata values
            config.put('actionName', metadata.ActionName__c);
            config.put('enabled', metadata.Enabled__c);
            config.put('maxPerUserPerDay', metadata.MaxPerUserPerDay__c);
            config.put('requiresConfirm', metadata.RequiresConfirm__c);
            config.put('flowName', metadata.FlowName__c);
            config.put('apexMethod', metadata.ApexMethod__c);
            config.put('inputSchema', metadata.InputSchemaJson__c);
            config.put('allowedFields', metadata.AllowedFields__c);
            
            // Check for runtime override
            ActionEnablementSetting__c setting = ActionEnablementSetting__c.getInstance(actionName);
            
            if (setting != null) {
                // Override with runtime values
                config.put('enabled', setting.Enabled__c);
                config.put('maxPerUserPerDay', setting.MaxPerUserPerDay__c);
                config.put('hasOverride', true);
            } else {
                config.put('hasOverride', false);
            }
            
            return config;
            
        } catch (Exception e) {
            throw new AuraHandledException('Error getting effective configuration: ' + e.getMessage());
        }
    }
    
    /**
     * Tests an action configuration by validating its setup
     * @param actionName The name of the action to test
     * @return Test result with success flag and message
     */
    @AuraEnabled
    public static Map<String, Object> testAction(String actionName) {
        Map<String, Object> result = new Map<String, Object>();
        
        try {
            Map<String, Object> config = getEffectiveConfiguration(actionName);
            
            if (config == null) {
                result.put('success', false);
                result.put('message', 'Action not found: ' + actionName);
                return result;
            }
            
            List<String> validationMessages = new List<String>();
            
            // Check if enabled
            Boolean enabled = (Boolean) config.get('enabled');
            Boolean hasOverride = (Boolean) config.get('hasOverride');
            
            if (!enabled) {
                if (hasOverride) {
                    validationMessages.add('⚠️ Action is currently disabled (runtime override)');
                } else {
                    validationMessages.add('⚠️ Action is currently disabled (metadata default)');
                }
            } else {
                if (hasOverride) {
                    validationMessages.add('✓ Action is enabled (runtime override)');
                } else {
                    validationMessages.add('✓ Action is enabled (metadata default)');
                }
            }
            
            // Check rate limit
            Decimal maxPerUserPerDay = (Decimal) config.get('maxPerUserPerDay');
            if (maxPerUserPerDay != null && maxPerUserPerDay > 0) {
                validationMessages.add('✓ Rate limit: ' + maxPerUserPerDay.intValue() + ' per user per day');
            } else {
                validationMessages.add('⚠️ No rate limit configured');
            }
            
            // Check Flow or Apex configuration
            String flowName = (String) config.get('flowName');
            String apexMethod = (String) config.get('apexMethod');
            
            if (String.isNotBlank(flowName)) {
                // Verify Flow exists
                List<FlowDefinitionView> flows = [
                    SELECT ApiName, ActiveVersionId
                    FROM FlowDefinitionView
                    WHERE ApiName = :flowName
                    LIMIT 1
                ];
                
                if (!flows.isEmpty() && flows[0].ActiveVersionId != null) {
                    validationMessages.add('✓ Flow found and active: ' + flowName);
                } else {
                    validationMessages.add('❌ Flow not found or inactive: ' + flowName);
                    result.put('success', false);
                }
            } else if (String.isNotBlank(apexMethod)) {
                validationMessages.add('✓ Apex method configured: ' + apexMethod);
            } else {
                validationMessages.add('❌ No Flow or Apex method configured');
                result.put('success', false);
            }
            
            // Check input schema
            String inputSchema = (String) config.get('inputSchema');
            if (String.isNotBlank(inputSchema)) {
                try {
                    JSON.deserializeUntyped(inputSchema);
                    validationMessages.add('✓ Input schema is valid JSON');
                } catch (Exception e) {
                    validationMessages.add('❌ Input schema is invalid JSON: ' + e.getMessage());
                    result.put('success', false);
                }
            } else {
                validationMessages.add('⚠️ No input schema defined');
            }
            
            // Set success if not already set to false
            if (!result.containsKey('success')) {
                result.put('success', true);
            }
            
            result.put('message', String.join(validationMessages, '\n'));
            
        } catch (Exception e) {
            result.put('success', false);
            result.put('message', 'Error testing action: ' + e.getMessage());
        }
        
        return result;
    }
}
