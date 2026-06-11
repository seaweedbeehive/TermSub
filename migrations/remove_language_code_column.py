#!/usr/bin/env python3
"""
Migration: Remove language_code column from segments table.

This migration drops the obsolete `language_code` column and recreates
the composite index without it, reflecting the permanent removal of
multi-language track support in v1.5.0-beta.

SQLite 3.35+ supports ALTER TABLE ... DROP COLUMN directly.
For older SQLite versions, this script falls back to table recreation.

Usage:
    python migrations/remove_language_code_column.py
"""

import os
import sys
import sqlite3

# Add parent directory to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings


def get_sqlite_version() -> tuple:
    """Return SQLite version as (major, minor, patch) tuple."""
    conn = sqlite3.connect(":memory:")
    version_str = conn.execute("SELECT sqlite_version()").fetchone()[0]
    conn.close()
    parts = version_str.split(".")
    return tuple(int(p) for p in parts[:3])


def column_exists(db_path: str, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    return column in columns


def index_exists(db_path: str, index_name: str) -> bool:
    """Check if an index exists."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,)
    )
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def drop_column_direct(db_path: str, table: str, column: str) -> None:
    """Drop a column using SQLite's native ALTER TABLE ... DROP COLUMN.
    
    The old index must be dropped FIRST because SQLite refuses to drop a
    column that is referenced by an existing index.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("DROP INDEX IF EXISTS idx_segments_video_seq_lang")
    conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_segments_video_seq ON segments(video_id, sequence_number)")
    conn.commit()
    conn.close()


def drop_column_via_recreate(db_path: str, table: str, column: str) -> None:
    """Drop a column by recreating the table (fallback for old SQLite)."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get current schema
    cursor.execute(f"PRAGMA table_info({table})")
    columns = cursor.fetchall()

    # Build new column list excluding the target column
    new_columns = [c for c in columns if c[1] != column]
    column_defs = ", ".join(
        f"{c[1]} {c[2]}" + (" NOT NULL" if c[3] else "") + (f" DEFAULT {c[4]}" if c[4] is not None else "")
        for c in new_columns
    )
    column_names = ", ".join(c[1] for c in new_columns)

    # Recreate table
    cursor.execute(f"CREATE TABLE {table}_new ({column_defs})")
    cursor.execute(f"INSERT INTO {table}_new ({column_names}) SELECT {column_names} FROM {table}")
    cursor.execute(f"DROP TABLE {table}")
    cursor.execute(f"ALTER TABLE {table}_new RENAME TO {table}")

    conn.commit()
    conn.close()


def migrate() -> None:
    """Run the migration."""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        print(f"[ERROR] Database not found: {db_path}")
        sys.exit(1)

    print(f"[INFO] Using database: {db_path}")

    # Check if column exists
    if not column_exists(db_path, "segments", "language_code"):
        print("[INFO] Column 'language_code' does not exist. Nothing to migrate.")
        return

    print("[INFO] Dropping column 'language_code' from 'segments'...")

    # Determine SQLite version for DROP COLUMN support
    sqlite_ver = get_sqlite_version()
    supports_drop_column = sqlite_ver >= (3, 35, 0)

    if supports_drop_column:
        print(f"[INFO] SQLite {'.'.join(map(str, sqlite_ver))} supports DROP COLUMN. Using direct drop.")
        drop_column_direct(db_path, "segments", "language_code")
    else:
        print(f"[INFO] SQLite {'.'.join(map(str, sqlite_ver))} does not support DROP COLUMN. Using table recreation.")
        drop_column_via_recreate(db_path, "segments", "language_code")

    print("[INFO] Column dropped successfully.")

    # Handle index migration (already done inside drop_column_direct for native path)
    # For the fallback recreation path, indexes are lost during table swap and
    # recreated below.
    old_index = "idx_segments_video_seq_lang"
    new_index = "idx_segments_video_seq"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    if not supports_drop_column:
        # Fallback path: table recreation lost all indexes, so recreate
        if not index_exists(db_path, new_index):
            print(f"[INFO] Creating new index '{new_index}' on (video_id, sequence_number)...")
            cursor.execute(
                f"CREATE INDEX {new_index} ON segments (video_id, sequence_number)"
            )
        # Ensure old index name is gone if it somehow survived
        if index_exists(db_path, old_index):
            cursor.execute(f"DROP INDEX {old_index}")
    else:
        # Native path: drop_column_direct already handled index swap.
        # Just clean up if the old index name somehow still exists.
        if index_exists(db_path, old_index):
            cursor.execute(f"DROP INDEX {old_index}")

    conn.commit()
    conn.close()

    # Verify
    if column_exists(db_path, "segments", "language_code"):
        print("[ERROR] Migration failed: column still exists!")
        sys.exit(1)

    print("[SUCCESS] Migration complete. Verified: language_code removed, index recreated.")


if __name__ == "__main__":
    migrate()
