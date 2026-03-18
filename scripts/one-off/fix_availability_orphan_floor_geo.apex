List<ascendix__Availability__c> candidates = [
    SELECT
        Id,
        Name,
        ascendix__Floor__c,
        ascendix__Region__c,
        ascendix__Market__c,
        ascendix__SubMarket__c,
        ascendix__Property__r.Name,
        ascendix__Property__r.ascendix__Region__c,
        ascendix__Property__r.ascendix__Market__c,
        ascendix__Property__r.ascendix__SubMarket__c
    FROM ascendix__Availability__c
    WHERE ascendix__Property__c != null
    AND ascendix__Market__c = null
    AND ascendix__Property__r.ascendix__Market__c != null
];

Set<Id> referencedFloorIds = new Set<Id>();
for (ascendix__Availability__c availability : candidates) {
    if (availability.ascendix__Floor__c != null) {
        referencedFloorIds.add(availability.ascendix__Floor__c);
    }
}

Set<Id> validFloorIds = new Map<Id, ascendix__Floor__c>([
    SELECT Id
    FROM ascendix__Floor__c
    WHERE Id IN :referencedFloorIds
]).keySet();

List<ascendix__Availability__c> updates = new List<ascendix__Availability__c>();
for (ascendix__Availability__c availability : candidates) {
    ascendix__Availability__c updateRow = new ascendix__Availability__c(Id = availability.Id);
    Boolean needsUpdate = false;

    if (availability.ascendix__Floor__c != null && !validFloorIds.contains(availability.ascendix__Floor__c)) {
        updateRow.ascendix__Floor__c = null;
        needsUpdate = true;
    }

    if (
        availability.ascendix__Property__r.ascendix__Region__c != null &&
        availability.ascendix__Region__c != availability.ascendix__Property__r.ascendix__Region__c
    ) {
        updateRow.ascendix__Region__c = availability.ascendix__Property__r.ascendix__Region__c;
        needsUpdate = true;
    }

    if (
        availability.ascendix__Property__r.ascendix__Market__c != null &&
        availability.ascendix__Market__c != availability.ascendix__Property__r.ascendix__Market__c
    ) {
        updateRow.ascendix__Market__c = availability.ascendix__Property__r.ascendix__Market__c;
        needsUpdate = true;
    }

    if (
        availability.ascendix__Property__r.ascendix__SubMarket__c != null &&
        availability.ascendix__SubMarket__c != availability.ascendix__Property__r.ascendix__SubMarket__c
    ) {
        updateRow.ascendix__SubMarket__c = availability.ascendix__Property__r.ascendix__SubMarket__c;
        needsUpdate = true;
    }

    if (needsUpdate) {
        updates.add(updateRow);
    }
}

Database.SaveResult[] results = Database.update(updates, false);
Integer succeeded = 0;
Integer failed = 0;

for (Integer i = 0; i < results.size(); i++) {
    if (results[i].isSuccess()) {
        succeeded++;
        continue;
    }

    failed++;
    for (Database.Error err : results[i].getErrors()) {
        System.debug(
            LoggingLevel.ERROR,
            'Failed Availability ' + updates[i].Id + ': ' + err.getStatusCode() + ' ' + err.getMessage()
        );
    }
}

System.debug('Candidate Availability records: ' + candidates.size());
System.debug('Availability records queued for update: ' + updates.size());
System.debug('Availability updates succeeded: ' + succeeded);
System.debug('Availability updates failed: ' + failed);
