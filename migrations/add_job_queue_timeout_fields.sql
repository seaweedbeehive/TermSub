-- SQLite Migration Script: Add timeout and heartbeat fields to job_queue table
-- 
-- This script adds the necessary columns and indexes for job timeout detection
-- and heartbeat tracking in the SQLite database.
--
-- Run this script with:
--   sqlite3 termsub.db < add_job_queue_timeout_fields.sql
--
-- Or from within sqlite3:
--   .read add_job_queue_timeout_fields.sql

-- ============================================================================
-- MIGRATION: Add timeout and heartbeat fields
-- ============================================================================

-- Check if last_heartbeat column exists before adding
SELECT CASE 
    WHEN COUNT(*) = 0 THEN
        'Adding last_heartbeat column...'
    ELSE
        'Column last_heartbeat already exists, skipping...'
END AS status
FROM pragma_table_info('job_queue') 
WHERE name = 'last_heartbeat';

-- Add last_heartbeat column (only if it doesn't exist)
ALTER TABLE job_queue ADD COLUMN last_heartbeat DATETIME;

-- Check if timeout_at column exists before adding
SELECT CASE 
    WHEN COUNT(*) = 0 THEN
        'Adding timeout_at column...'
    ELSE
        'Column timeout_at already exists, skipping...'
END AS status
FROM pragma_table_info('job_queue') 
WHERE name = 'timeout_at';

-- Add timeout_at column (only if it doesn't exist)
ALTER TABLE job_queue ADD COLUMN timeout_at DATETIME;

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Create index on status column for faster status-based queries
-- This optimizes queries like: SELECT * FROM job_queue WHERE status = 'pending'
CREATE INDEX IF NOT EXISTS idx_job_queue_status ON job_queue (status);

-- Create composite index on video_id + status for get_job_status queries
-- This optimizes queries like: SELECT * FROM job_queue WHERE video_id = ? AND status = ?
CREATE INDEX IF NOT EXISTS idx_job_queue_video_status ON job_queue (video_id, status);

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Verify columns were added
SELECT 'Columns in job_queue table:' AS verification;
SELECT cid, name, type, "notnull", dflt_value, pk 
FROM pragma_table_info('job_queue')
WHERE name IN ('last_heartbeat', 'timeout_at', 'status', 'video_id')
ORDER BY cid;

-- Verify indexes were created
SELECT 'Indexes on job_queue table:' AS verification;
SELECT name, sql 
FROM sqlite_master 
WHERE type = 'index' 
AND tbl_name = 'job_queue'
AND name LIKE 'idx_job_queue%';

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================
SELECT 'Migration completed successfully!' AS status;
