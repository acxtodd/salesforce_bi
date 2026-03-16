// Check status of batch export jobs
// Run with: sf apex run --file scripts/check_batch_status.apex --target-org ascendix-beta-sandbox

System.debug('=== Batch Job Status ===');

List<AsyncApexJob> jobs = [
    SELECT Id, Status, JobType, ApexClass.Name, JobItemsProcessed, TotalJobItems, 
           NumberOfErrors, CreatedDate, CompletedDate, ExtendedStatus
    FROM AsyncApexJob
    WHERE ApexClass.Name = 'AISearchBatchExport'
    ORDER BY CreatedDate DESC
    LIMIT 10
];

for (AsyncApexJob job : jobs) {
    System.debug('Job: ' + job.Id + 
                 ' | Status: ' + job.Status + 
                 ' | Progress: ' + job.JobItemsProcessed + '/' + job.TotalJobItems +
                 ' | Errors: ' + job.NumberOfErrors +
                 ' | Created: ' + job.CreatedDate);
    if (job.ExtendedStatus != null) {
        System.debug('  Extended Status: ' + job.ExtendedStatus);
    }
}

System.debug('=== End Status ===');
