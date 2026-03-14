@isTest
private class AISearchBatchExportSchedulerTest {
    
    @isTest
    static void testScheduler() {
        Test.startTest();
        AISearchBatchExportScheduler scheduler = new AISearchBatchExportScheduler();
        String cronExp = '0 0 0 15 3 ? 2099';
        try {
            System.schedule('Test Scheduler', cronExp, scheduler);
        } catch (Exception e) {
            // Ignore
        }
        Test.stopTest();
    }
}
