#!/usr/bin/env python3
"""
Standalone migration script to add language_code column to segments table.

This script can be run directly without Alembic:
    python migrations/add_segment_language_code.py

It uses SQLAlchemy to safely add the column and update existing rows.
"""

import sys
import os

# Add parent directory to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, Column, String, inspect, text, Index
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
    """Apply migration: Add language_code column and update existing rows."""
    from sqlalchemy import MetaData, Table
    
    print("Starting migration: Add language_code to segments table")
    print("=" * 70)
    
    # Reflect the table
    metadata = MetaData()
    metadata.reflect(bind=engine)
    
    if 'segments' not in metadata.tables:
        print("ERROR: segments table does not exist!")
        return False
    
    segments_table = metadata.tables['segments']
    
    # Add language_code column if it doesn't exist
    if not column_exists(engine, 'segments', 'language_code'):
        print("Adding language_code column...")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE segments ADD COLUMN language_code VARCHAR(10) NOT NULL DEFAULT 'original'"))
            conn.commit()
        print("  ✓ language_code column added with default 'original'")
    else:
        print("  ⊘ language_code column already exists, skipping")
    
    # Backfill existing rows
    print("\nBackfilling language_code for existing segments...")
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        # Update all existing segments that don't have a language_code
        result = session.execute(
            text("""
                UPDATE segments
                SET language_code = 'original'
                WHERE language_code IS NULL OR language_code = ''
            """)
        )
        session.commit()
        print(f"  ✓ Updated {result.rowcount} existing segments")
    except Exception as e:
        session.rollback()
        print(f"  ✗ Error backfilling: {e}")
        return False
    finally:
        session.close()
    
    # Drop old index if it exists
    if index_exists(engine, 'segments', 'idx_segments_video_seq'):
        print("\nDropping old index idx_segments_video_seq...")
        with engine.connect() as conn:
            conn.execute(text("DROP INDEX IF EXISTS idx_segments_video_seq"))
            conn.commit()
        print("  ✓ Old index dropped")
    
    # Create new composite index
    if not index_exists(engine, 'segments', 'idx_segments_video_seq_lang'):
        print("\nCreating new composite index idx_segments_video_seq_lang...")
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE INDEX idx_segments_video_seq_lang ON segments (video_id, sequence_number, language_code)"
            ))
            conn.commit()
        print("  ✓ New index created")
    else:
        print("  ⊘ Index idx_segments_video_seq_lang already exists, skipping")
    
    print("\n" + "=" * 70)
    print("Migration complete!")
    print("The segments table now supports multi-language tracks.")
    return True


def main():
    """Run the migration."""
    engine = get_engine()
    success = migrate_up(engine)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
