Id usSouthId = 'a0Rdl00000EJKB4EAP';
Id dallasFortWorthId = 'a0Rdl00000EJJbaEAH';

List<ascendix__Availability__c> updates = new List<ascendix__Availability__c>{
    new ascendix__Availability__c(
        Id = 'a0Dfk000002JuDrEAK',
        ascendix__Floor__c = null,
        ascendix__Region__c = usSouthId,
        ascendix__Market__c = dallasFortWorthId
    ),
    new ascendix__Availability__c(
        Id = 'a0Dfk000002JuDfEAK',
        ascendix__Floor__c = null,
        ascendix__Region__c = usSouthId,
        ascendix__Market__c = dallasFortWorthId
    )
};

update updates;

System.debug('Updated ' + updates.size() + ' Availability records');
