#!/usr/bin/env python3
"""
Standalone migration script to add timeout and heartbeat fields to job_queue table.

This script can be run directly without Alembic:
    python migrations/apply_migration.py

It uses SQLAlchemy to safely add columns and indexes if they don't exist.
"""

import sys
import os

# Add parent directory to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, Column, DateTime, Index, inspect, text
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


def get_engine():
    """Create database engine from settings."""
    return create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
    )


def column_exists(engine, table_name: str, column_name: str) -> bool:
    """Check if a column exists in the table."""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def index_exists(engine, table_name: str, index_name: str) -> bool:
    """Check if an index exists on the table."""
    inspector = inspect(engine)
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def migrate_up(engine):
    """Apply migration: Add columns and indexes."""
    from sqlalchemy import MetaData, Table
    
    print("Starting migration: Add timeout and heartbeat fields to job_queue")
    print("=" * 70)
    
    # Reflect the table
    metadata = MetaData()
    metadata.reflect(bind=engine)
    
    if 'job_queue' not in metadata.tables:
        print("ERROR: job_queue table does not exist!")
        return False
    
    job_queue_table = metadata.tables['job_queue']
    
    # Add last_heartbeat column
    if not column_exists(engine, 'job_queue', 'last_heartbeat'):
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE job_queue ADD COLUMN last_heartbeat DATETIME"))
            conn.commit()
        print("✓ Added column: last_heartbeat")
    else:
        print("✓ Column last_heartbeat already exists, skipping")
    
    # Add timeout_at column
    if not column_exists(engine, 'job_queue', 'timeout_at'):
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE job_queue ADD COLUMN timeout_at DATETIME"))
            conn.commit()
        print("✓ Added column: timeout_at")
    else:
        print("✓ Column timeout_at already exists, skipping")
    
    # Create index on status
    if not index_exists(engine, 'job_queue', 'idx_job_queue_status'):
        with engine.connect() as conn:
            conn.execute(text("CREATE INDEX idx_job_queue_status ON job_queue (status)"))
            conn.commit()
        print("✓ Created index: idx_job_queue_status")
    else:
        print("✓ Index idx_job_queue_status already exists, skipping")
    
    # Create composite index on video_id + status
    if not index_exists(engine, 'job_queue', 'idx_job_queue_video_status'):
        with engine.connect() as conn:
            conn.execute(text("CREATE INDEX idx_job_queue_video_status ON job_queue (video_id, status)"))
            conn.commit()
        print("✓ Created index: idx_job_queue_video_status")
    else:
        print("✓ Index idx_job_queue_video_status already exists, skipping")
    
    print("=" * 70)
    print("Migration completed successfully!")
    return True


def migrate_down(engine):
    """Revert migration: Remove columns and indexes."""
    print("Starting downgrade: Remove timeout and heartbeat fields from job_queue")
    print("=" * 70)
    print("WARNING: SQLite does not support DROP COLUMN directly.")
    print("To downgrade, you would need to:")
    print("1. Create a new table without the columns")
    print("2. Copy data from old table")
    print("3. Drop old table")
    print("4. Rename new table")
    print("=" * 70)
    print("Downgrade not implemented for safety. Manual intervention required.")
    return False


def verify_migration(engine):
    """Verify the migration was applied correctly."""
    print("\nVerifying migration...")
    print("-" * 70)
    
    inspector = inspect(engine)
    
    # Check columns
    columns = {col['name'] for col in inspector.get_columns('job_queue')}
    required_columns = {'last_heartbeat', 'timeout_at'}
    
    for col in required_columns:
        if col in columns:
            print(f"✓ Column '{col}' exists")
        else:
            print(f"✗ Column '{col}' is MISSING")
    
    # Check indexes
    indexes = {idx['name'] for idx in inspector.get_indexes('job_queue')}
    required_indexes = {'idx_job_queue_status', 'idx_job_queue_video_status'}
    
    for idx in required_indexes:
        if idx in indexes:
            print(f"✓ Index '{idx}' exists")
        else:
            print(f"✗ Index '{idx}' is MISSING")
    
    print("-" * 70)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Apply or verify job_queue migration for timeout/heartbeat fields"
    )
    parser.add_argument(
        '--downgrade', 
        action='store_true',
        help='Attempt to downgrade (not fully supported for SQLite)'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Only verify migration, do not apply'
    )
    
    args = parser.parse_args()
    
    try:
        engine = get_engine()
        
        if args.verify:
            verify_migration(engine)
        elif args.downgrade:
            migrate_down(engine)
        else:
            success = migrate_up(engine)
            if success:
                verify_migration(engine)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
