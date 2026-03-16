// Evaluate CRE Data in Salesforce Org - Minimal Fields
// Run with: sf apex run --file scripts/evaluate_cre_data.apex --target-org ascendix-beta-sandbox

System.debug('=== CRE Data Evaluation ===');
System.debug('Timestamp: ' + DateTime.now());

// 1. Count records for each CRE object
System.debug('\n--- Record Counts ---');

Integer propertyCount = 0;
Integer availCount = 0;
Integer leaseCount = 0;
Integer saleCount = 0;
Integer dealCount = 0;
Integer accountCount = 0;

try {
    propertyCount = [SELECT COUNT() FROM ascendix__Property__c];
    System.debug('ascendix__Property__c: ' + propertyCount + ' records');
} catch (Exception e) {
    System.debug('ascendix__Property__c: ERROR - ' + e.getMessage());
}

try {
    availCount = [SELECT COUNT() FROM ascendix__Availability__c];
    System.debug('ascendix__Availability__c: ' + availCount + ' records');
} catch (Exception e) {
    System.debug('ascendix__Availability__c: ERROR - ' + e.getMessage());
}

try {
    leaseCount = [SELECT COUNT() FROM ascendix__Lease__c];
    System.debug('ascendix__Lease__c: ' + leaseCount + ' records');
} catch (Exception e) {
    System.debug('ascendix__Lease__c: ERROR - ' + e.getMessage());
}

try {
    saleCount = [SELECT COUNT() FROM ascendix__Sale__c];
    System.debug('ascendix__Sale__c: ' + saleCount + ' records');
} catch (Exception e) {
    System.debug('ascendix__Sale__c: ERROR - ' + e.getMessage());
}

try {
    dealCount = [SELECT COUNT() FROM ascendix__Deal__c];
    System.debug('ascendix__Deal__c: ' + dealCount + ' records');
} catch (Exception e) {
    System.debug('ascendix__Deal__c: ERROR - ' + e.getMessage());
}

try {
    accountCount = [SELECT COUNT() FROM Account];
    System.debug('Account: ' + accountCount + ' records');
} catch (Exception e) {
    System.debug('Account: ERROR - ' + e.getMessage());
}

// 2. Sample Property records
System.debug('\n--- Sample Properties (Top 5) ---');
try {
    List<ascendix__Property__c> properties = [
        SELECT Id, Name, ascendix__PropertyClass__c, ascendix__City__c, ascendix__State__c, LastModifiedDate
        FROM ascendix__Property__c
        ORDER BY LastModifiedDate DESC
        LIMIT 5
    ];
    for (ascendix__Property__c p : properties) {
        System.debug('Property: ' + p.Name + ' | Class: ' + p.ascendix__PropertyClass__c + 
                     ' | Location: ' + p.ascendix__City__c + ', ' + p.ascendix__State__c);
    }
} catch (Exception e) {
    System.debug('Property sample ERROR: ' + e.getMessage());
}

// 3. Sample Availability records
System.debug('\n--- Sample Availabilities (Top 5) ---');
try {
    List<ascendix__Availability__c> avails = [
        SELECT Id, Name, ascendix__Property__r.Name, ascendix__Status__c, LastModifiedDate
        FROM ascendix__Availability__c
        ORDER BY LastModifiedDate DESC
        LIMIT 5
    ];
    for (ascendix__Availability__c a : avails) {
        System.debug('Availability: ' + a.Name + ' | Property: ' + a.ascendix__Property__r.Name + 
                     ' | Status: ' + a.ascendix__Status__c);
    }
} catch (Exception e) {
    System.debug('Availability sample ERROR: ' + e.getMessage());
}

// 4. Sample Lease records
System.debug('\n--- Sample Leases (Top 5) ---');
try {
    List<ascendix__Lease__c> leases = [
        SELECT Id, Name, ascendix__Property__r.Name, ascendix__Tenant__r.Name,
               ascendix__TermExpirationDate__c, LastModifiedDate
        FROM ascendix__Lease__c
        ORDER BY LastModifiedDate DESC
        LIMIT 5
    ];
    for (ascendix__Lease__c l : leases) {
        System.debug('Lease: ' + l.Name + ' | Property: ' + l.ascendix__Property__r.Name + 
                     ' | Tenant: ' + l.ascendix__Tenant__r.Name + 
                     ' | Expires: ' + l.ascendix__TermExpirationDate__c);
    }
} catch (Exception e) {
    System.debug('Lease sample ERROR: ' + e.getMessage());
}

// 5. Sample Sale records
System.debug('\n--- Sample Sales (Top 5) ---');
try {
    List<ascendix__Sale__c> sales = [
        SELECT Id, Name, ascendix__Property__r.Name, ascendix__SalePrice__c, 
               ascendix__SaleDate__c, LastModifiedDate
        FROM ascendix__Sale__c
        ORDER BY LastModifiedDate DESC
        LIMIT 5
    ];
    for (ascendix__Sale__c s : sales) {
        System.debug('Sale: ' + s.Name + ' | Property: ' + s.ascendix__Property__r.Name + 
                     ' | Price: $' + s.ascendix__SalePrice__c + ' | Date: ' + s.ascendix__SaleDate__c);
    }
} catch (Exception e) {
    System.debug('Sale sample ERROR: ' + e.getMessage());
}

// 6. Sample Deal records
System.debug('\n--- Sample Deals (Top 5) ---');
try {
    List<ascendix__Deal__c> deals = [
        SELECT Id, Name, ascendix__Status__c, ascendix__SalesStage__c,
               ascendix__Property__r.Name, ascendix__Client__r.Name,
               ascendix__GrossFeeAmount__c, ascendix__DealSubType__c, LastModifiedDate
        FROM ascendix__Deal__c
        ORDER BY LastModifiedDate DESC
        LIMIT 5
    ];
    for (ascendix__Deal__c d : deals) {
        System.debug('Deal: ' + d.Name + ' | Status: ' + d.ascendix__Status__c + 
                     ' | Stage: ' + d.ascendix__SalesStage__c +
                     ' | Type: ' + d.ascendix__DealSubType__c +
                     ' | Client: ' + d.ascendix__Client__r.Name +
                     ' | Fee: $' + d.ascendix__GrossFeeAmount__c);
    }
} catch (Exception e) {
    System.debug('Deal sample ERROR: ' + e.getMessage());
}

// 7. Deal status distribution
System.debug('\n--- Deal Status Distribution ---');
try {
    List<AggregateResult> dealsByStatus = [
        SELECT ascendix__Status__c status, COUNT(Id) cnt
        FROM ascendix__Deal__c
        GROUP BY ascendix__Status__c
        ORDER BY COUNT(Id) DESC
    ];
    for (AggregateResult ar : dealsByStatus) {
        System.debug('Status: ' + ar.get('status') + ' = ' + ar.get('cnt'));
    }
} catch (Exception e) {
    System.debug('Deal status ERROR: ' + e.getMessage());
}

// 8. Deal type distribution
System.debug('\n--- Deal Type Distribution ---');
try {
    List<AggregateResult> dealsByType = [
        SELECT ascendix__DealSubType__c dtype, COUNT(Id) cnt
        FROM ascendix__Deal__c
        GROUP BY ascendix__DealSubType__c
        ORDER BY COUNT(Id) DESC
    ];
    for (AggregateResult ar : dealsByType) {
        System.debug('Type: ' + ar.get('dtype') + ' = ' + ar.get('cnt'));
    }
} catch (Exception e) {
    System.debug('Deal type ERROR: ' + e.getMessage());
}

// 9. Property class distribution
System.debug('\n--- Property Class Distribution ---');
try {
    List<AggregateResult> propsByClass = [
        SELECT ascendix__PropertyClass__c pclass, COUNT(Id) cnt
        FROM ascendix__Property__c
        GROUP BY ascendix__PropertyClass__c
        ORDER BY COUNT(Id) DESC
    ];
    for (AggregateResult ar : propsByClass) {
        System.debug('Class: ' + ar.get('pclass') + ' = ' + ar.get('cnt'));
    }
} catch (Exception e) {
    System.debug('Property class ERROR: ' + e.getMessage());
}

// 10. Data freshness - records modified in last 30 days
System.debug('\n--- Data Freshness (Last 30 Days) ---');
DateTime thirtyDaysAgo = DateTime.now().addDays(-30);

try {
    Integer recentProperties = [SELECT COUNT() FROM ascendix__Property__c WHERE LastModifiedDate >= :thirtyDaysAgo];
    System.debug('Recent Properties: ' + recentProperties + ' / ' + propertyCount);
} catch (Exception e) { System.debug('Recent Properties: ERROR'); }

try {
    Integer recentAvails = [SELECT COUNT() FROM ascendix__Availability__c WHERE LastModifiedDate >= :thirtyDaysAgo];
    System.debug('Recent Availabilities: ' + recentAvails + ' / ' + availCount);
} catch (Exception e) { System.debug('Recent Availabilities: ERROR'); }

try {
    Integer recentLeases = [SELECT COUNT() FROM ascendix__Lease__c WHERE LastModifiedDate >= :thirtyDaysAgo];
    System.debug('Recent Leases: ' + recentLeases + ' / ' + leaseCount);
} catch (Exception e) { System.debug('Recent Leases: ERROR'); }

try {
    Integer recentSales = [SELECT COUNT() FROM ascendix__Sale__c WHERE LastModifiedDate >= :thirtyDaysAgo];
    System.debug('Recent Sales: ' + recentSales + ' / ' + saleCount);
} catch (Exception e) { System.debug('Recent Sales: ERROR'); }

try {
    Integer recentDeals = [SELECT COUNT() FROM ascendix__Deal__c WHERE LastModifiedDate >= :thirtyDaysAgo];
    System.debug('Recent Deals: ' + recentDeals + ' / ' + dealCount);
} catch (Exception e) { System.debug('Recent Deals: ERROR'); }

// 11. Leases expiring soon
System.debug('\n--- Leases Expiring in Next 90 Days ---');
Date ninetyDaysOut = Date.today().addDays(90);
try {
    Integer expiringCount = [
        SELECT COUNT()
        FROM ascendix__Lease__c
        WHERE ascendix__TermExpirationDate__c <= :ninetyDaysOut
          AND ascendix__TermExpirationDate__c >= TODAY
    ];
    System.debug('Leases expiring in next 90 days: ' + expiringCount);
} catch (Exception e) {
    System.debug('Expiring leases ERROR: ' + e.getMessage());
}

// 12. Active deals
System.debug('\n--- Active Deals ---');
try {
    Integer activeDeals = [SELECT COUNT() FROM ascendix__Deal__c WHERE ascendix__Status__c = 'Active'];
    System.debug('Active Deals: ' + activeDeals);
} catch (Exception e) {
    System.debug('Active deals ERROR: ' + e.getMessage());
}

// 13. Properties by city (top 10)
System.debug('\n--- Properties by City (Top 10) ---');
try {
    List<AggregateResult> propsByCity = [
        SELECT ascendix__City__c city, COUNT(Id) cnt
        FROM ascendix__Property__c
        WHERE ascendix__City__c != null
        GROUP BY ascendix__City__c
        ORDER BY COUNT(Id) DESC
        LIMIT 10
    ];
    for (AggregateResult ar : propsByCity) {
        System.debug('City: ' + ar.get('city') + ' = ' + ar.get('cnt'));
    }
} catch (Exception e) {
    System.debug('Properties by city ERROR: ' + e.getMessage());
}

System.debug('\n=== Evaluation Complete ===');
