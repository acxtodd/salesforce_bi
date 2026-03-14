/**
 * AISearchExportException
 *
 * Custom exception for AI Search export validation failures.
 * Thrown when required fields are missing from Salesforce schema.
 *
 * **Task 38.1: Ingest-Time Field Contract Enforcement**
 *
 * This exception ensures batch job status clearly shows the failure reason
 * when field validation fails, enabling operators to quickly identify
 * and fix schema mismatches.
 *
 * Usage:
 *   throw new AISearchExportException('Missing required fields: City__c, State__c');
 */
public class AISearchExportException extends Exception {}
