// Seed Data for Account and Opportunity (Last 30 days)
Database.executeBatch(new AISearchBatchExport('Account', 720), 200);
Database.executeBatch(new AISearchBatchExport('Opportunity', 720), 200);
Database.executeBatch(new AISearchBatchExport('Case', 720), 200);