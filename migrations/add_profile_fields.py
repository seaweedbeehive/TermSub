#!/usr/bin/env python3
"""
Standalone migration script to add profile fields to the users table.

This script can be run directly without Alembic:
    python migrations/add_profile_fields.py

It uses SQLAlchemy to safely add columns if they don't exist.
"""

import os
import sys

# Add parent directory to path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, inspect, text

from app.core.config import settings


def get_engine():
    """Create database engine from settings."""
    return create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False}
        if "sqlite" in settings.DATABASE_URL
        else {},
    )


def column_exists(engine, table_name: str, column_name: str) -> bool:
    """Check if a column exists in the table."""
    inspector = inspect(engine)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def migrate_up(engine):
    """Apply migration: Add profile columns to users."""
    print("Starting migration: Add profile fields to users")
    print("=" * 70)

    if not column_exists(engine, "users", "display_name"):
        with engine.connect() as conn:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN display_name VARCHAR(255)")
            )
            conn.commit()
        print("✓ Added column: display_name")
    else:
        print("✓ Column display_name already exists, skipping")

    if not column_exists(engine, "users", "total_minutes_used"):
        with engine.connect() as conn:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN total_minutes_used INTEGER DEFAULT 0"
                )
            )
            conn.commit()
        print("✓ Added column: total_minutes_used")
    else:
        print("✓ Column total_minutes_used already exists, skipping")

    if not column_exists(engine, "users", "sessions_invalidated_at"):
        with engine.connect() as conn:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN sessions_invalidated_at DATETIME")
            )
            conn.commit()
        print("✓ Added column: sessions_invalidated_at")
    else:
        print("✓ Column sessions_invalidated_at already exists, skipping")

    if not column_exists(engine, "users", "password_reset_token"):
        with engine.connect() as conn:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN password_reset_token VARCHAR(255)")
            )
            conn.commit()
        print("✓ Added column: password_reset_token")
    else:
        print("✓ Column password_reset_token already exists, skipping")

    if not column_exists(engine, "users", "password_reset_token_expires_at"):
        with engine.connect() as conn:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN password_reset_token_expires_at DATETIME"
                )
            )
            conn.commit()
        print("✓ Added column: password_reset_token_expires_at")
    else:
        print("✓ Column password_reset_token_expires_at already exists, skipping")

    print("=" * 70)
    print("Migration completed successfully!")
    return True


def migrate_down(engine):
    """Revert migration: Remove profile columns from users."""
    print("Starting downgrade: Remove profile fields from users")
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

    columns = {col["name"] for col in inspect(engine).get_columns("users")}
    required_columns = {
        "display_name",
        "total_minutes_used",
        "sessions_invalidated_at",
        "password_reset_token",
        "password_reset_token_expires_at",
    }

    for col in required_columns:
        if col in columns:
            print(f"✓ Column '{col}' exists")
        else:
            print(f"✗ Column '{col}' is MISSING")

    print("-" * 70)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Apply or verify users profile fields migration"
    )
    parser.add_argument(
        "--downgrade",
        action="store_true",
        help="Attempt to downgrade (not fully supported for SQLite)",
    )
    parser.add_argument(
        "--verify", action="store_true", help="Only verify migration, do not apply"
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
