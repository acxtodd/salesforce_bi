/**
 * AISearchBatchExportScheduler
 * 
 * Schedulable class to run batch export jobs for all supported objects.
 * Runs daily during off-peak hours as a fallback to CDC/AppFlow.
 * 
 * Schedule Expression: Run daily at 2 AM
 *   0 0 2 * * ?
 * 
 * Usage (from Developer Console or Execute Anonymous):
 *   AISearchBatchExportScheduler scheduler = new AISearchBatchExportScheduler();
 *   String cronExp = '0 0 2 * * ?'; // Daily at 2 AM
 *   System.schedule('AI Search Batch Export', cronExp, scheduler);
 * 
 * Or schedule all objects:
 *   AISearchBatchExportScheduler.scheduleAll();
 */
public class AISearchBatchExportScheduler implements Schedulable {
    
    private static final Set<String> SUPPORTED_OBJECTS = new Set<String>{
        'Account', 'Opportunity', 'Case', 'Note',
        'Property__c', 'Lease__c', 'Contract__c'
    };
    
    private String sobjectType;
    private Integer hoursBack;
    
    /**
     * Default constructor - exports all objects
     */
    public AISearchBatchExportScheduler() {
        this(null, 24);
    }
    
    /**
     * Constructor for specific object
     * 
     * @param sobjectType The Salesforce object type to export (null for all)
     * @param hoursBack Number of hours to look back for modified records
     */
    public AISearchBatchExportScheduler(String sobjectType, Integer hoursBack) {
        this.sobjectType = sobjectType;
        this.hoursBack = hoursBack;
    }
    
    /**
     * Execute method - Called by Salesforce scheduler
     */
    public void execute(SchedulableContext sc) {
        if (String.isBlank(this.sobjectType)) {
            // Export all supported objects
            exportAllObjects();
        } else {
            // Export specific object
            exportObject(this.sobjectType);
        }
    }
    
    /**
     * Export all supported objects
     */
    private void exportAllObjects() {
        System.debug('AISearchBatchExportScheduler: Starting export for all objects');
        
        for (String sobj : SUPPORTED_OBJECTS) {
            exportObject(sobj);
            
            // Add small delay between batches to avoid governor limits
            // Note: In production, consider using Queueable chaining instead
        }
    }
    
    /**
     * Export specific object
     */
    private void exportObject(String sobjectType) {
        try {
            System.debug('AISearchBatchExportScheduler: Starting export for ' + sobjectType);
            
            AISearchBatchExport batch = new AISearchBatchExport(sobjectType, this.hoursBack);
            
            // Execute batch with batch size of 200
            Id batchId = Database.executeBatch(batch, 200);
            
            System.debug('AISearchBatchExportScheduler: Batch job started for ' + 
                         sobjectType + ' with ID: ' + batchId);
            
        } catch (Exception e) {
            System.debug(LoggingLevel.ERROR, 
                         'AISearchBatchExportScheduler: Error starting batch for ' + 
                         sobjectType + ': ' + e.getMessage());
        }
    }
    
    /**
     * Schedule all objects with separate jobs
     * This allows for better monitoring and control
     */
    public static void scheduleAll() {
        // Unschedule any existing jobs first
        unscheduleAll();
        
        // Schedule each object at different times to spread load
        Integer hourOffset = 2; // Start at 2 AM
        Integer minuteOffset = 0;
        
        for (String sobj : SUPPORTED_OBJECTS) {
            String jobName = 'AI Search Export - ' + sobj;
            String cronExp = '0 ' + minuteOffset + ' ' + hourOffset + ' * * ?';
            
            AISearchBatchExportScheduler scheduler = new AISearchBatchExportScheduler(sobj, 24);
            System.schedule(jobName, cronExp, scheduler);
            
            System.debug('Scheduled: ' + jobName + ' with cron: ' + cronExp);
            
            // Stagger jobs by 10 minutes
            minuteOffset += 10;
            if (minuteOffset >= 60) {
                minuteOffset = 0;
                hourOffset++;
            }
        }
    }
    
    /**
     * Unschedule all AI Search export jobs
     */
    public static void unscheduleAll() {
        List<CronTrigger> jobs = [
            SELECT Id, CronJobDetail.Name
            FROM CronTrigger
            WHERE CronJobDetail.Name LIKE 'AI Search Export%'
        ];
        
        for (CronTrigger job : jobs) {
            System.abortJob(job.Id);
            System.debug('Aborted job: ' + job.CronJobDetail.Name);
        }
    }
    
    /**
     * Get status of all scheduled jobs
     */
    public static List<Map<String, String>> getScheduledJobs() {
        List<Map<String, String>> jobStatus = new List<Map<String, String>>();
        
        List<CronTrigger> jobs = [
            SELECT Id, CronJobDetail.Name, State, NextFireTime, PreviousFireTime
            FROM CronTrigger
            WHERE CronJobDetail.Name LIKE 'AI Search Export%'
            ORDER BY CronJobDetail.Name
        ];
        
        for (CronTrigger job : jobs) {
            Map<String, String> status = new Map<String, String>{
                'Id' => job.Id,
                'Name' => job.CronJobDetail.Name,
                'State' => job.State,
                'NextFireTime' => String.valueOf(job.NextFireTime),
                'PreviousFireTime' => String.valueOf(job.PreviousFireTime)
            };
            jobStatus.add(status);
        }
        
        return jobStatus;
    }
    
    /**
     * Manually trigger export for specific object (for testing)
     */
    public static Id triggerExport(String sobjectType, Integer hoursBack) {
        AISearchBatchExport batch = new AISearchBatchExport(sobjectType, hoursBack);
        return Database.executeBatch(batch, 200);
    }
}
