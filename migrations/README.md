# Database Migrations

This directory contains database migration scripts for the TermSub application.

## Migration: Add Job Queue Timeout Fields

**File**: `add_job_queue_timeout_fields.py` / `add_job_queue_timeout_fields.sql`

**Purpose**: Adds timeout detection and heartbeat tracking fields to the `job_queue` table.

### Changes

1. **New Columns**:
   - `last_heartbeat` (DateTime, nullable) - Timestamp of last heartbeat during job processing
   - `timeout_at` (DateTime, nullable) - Deadline after which job is considered timed out

2. **New Indexes**:
   - `idx_job_queue_status` - Index on `status` column for faster status queries
   - `idx_job_queue_video_status` - Composite index on `video_id` + `status` for job status lookups

### Migration Options

#### Option 1: Using the Standalone Python Script (Recommended for SQLite)

```bash
# Apply the migration
python migrations/apply_migration.py

# Verify the migration was applied
python migrations/apply_migration.py --verify
```

#### Option 2: Using Alembic

If you have Alembic configured:

```bash
# Copy the migration file to your alembic versions directory
cp migrations/add_job_queue_timeout_fields.py alembic/versions/

# Apply the migration
alembic upgrade add_job_queue_timeout_fields

# To rollback (not fully supported for SQLite DROP COLUMN)
alembic downgrade add_job_queue_timeout_fields
```

#### Option 3: Using Raw SQL

```bash
# Apply the SQL script directly
sqlite3 termsub.db < migrations/add_job_queue_timeout_fields.sql
```

Or from within the sqlite3 shell:

```sql
.read migrations/add_job_queue_timeout_fields.sql
```

### Verification

After migration, verify the changes:

```sql
-- Check columns
PRAGMA table_info(job_queue);

-- Check indexes
SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='job_queue';
```

### Notes for SQLite

SQLite has limited ALTER TABLE support:
- ✅ Adding columns is supported
- ✅ Creating indexes is supported
- ❌ Dropping columns is NOT supported (requires table recreation)

The downgrade migration is not fully automated for SQLite due to these limitations.
