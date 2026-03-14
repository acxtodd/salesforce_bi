// Check status of batch export jobs
List<AsyncApexJob> jobs = [
    SELECT Id, Status, JobType, ApexClass.Name, NumberOfErrors, JobItemsProcessed, TotalJobItems 
    FROM AsyncApexJob 
    WHERE ApexClass.Name = 'AISearchBatchExport' 
    AND CreatedDate = TODAY 
    ORDER BY CreatedDate DESC 
    LIMIT 10
];

for(AsyncApexJob j : jobs) { 
    System.debug('Job: ' + j.ApexClass.Name + ' | Status: ' + j.Status + ' | Progress: ' + j.JobItemsProcessed + '/' + j.TotalJobItems + ' | Errors: ' + j.NumberOfErrors); 
}
