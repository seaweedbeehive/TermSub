#!/usr/bin/env python3
"""
Standalone migration script to add skip_glossary column to videos table.

This script can be run directly without Alembic:
    python migrations/add_skip_glossary_column.py

It uses SQLAlchemy to safely add the column if it doesn't exist.
"""

import sys
import os

# Add parent directory to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, inspect, text
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


def migrate_up(engine):
    """Apply migration: Add skip_glossary column to videos table."""
    print("Starting migration: Add skip_glossary column to videos")
    print("=" * 70)
    
    # Add skip_glossary column
    if not column_exists(engine, 'videos', 'skip_glossary'):
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE videos ADD COLUMN skip_glossary BOOLEAN DEFAULT 0"))
            conn.commit()
        print("✓ Added column: skip_glossary")
    else:
        print("✓ Column skip_glossary already exists, skipping")
    
    print("=" * 70)
    print("Migration completed successfully!")
    return True


def verify_migration(engine):
    """Verify the migration was applied correctly."""
    print("\nVerifying migration...")
    print("-" * 70)
    
    inspector = inspect(engine)
    columns = {col['name'] for col in inspector.get_columns('videos')}
    
    if 'skip_glossary' in columns:
        print("✓ Column 'skip_glossary' exists")
    else:
        print("✗ Column 'skip_glossary' is MISSING")
    
    print("-" * 70)


def main():
    """Main entry point."""
    try:
        engine = get_engine()
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
