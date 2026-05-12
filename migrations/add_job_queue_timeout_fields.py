"""Alembic migration script to add timeout and heartbeat fields to job_queue table.

Revision ID: add_job_queue_timeout_fields
Revises: 
Create Date: 2026-04-05

This migration adds:
- last_heartbeat column (DateTime, nullable)
- timeout_at column (DateTime, nullable)
- Index on status column
- Composite index on video_id + status

Usage:
    alembic upgrade add_job_queue_timeout_fields
    alembic downgrade add_job_queue_timeout_fields
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'add_job_queue_timeout_fields'
down_revision = None  # Set to previous revision if available
branch_labels = None
depends_on = None


def index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index already exists on the table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column already exists on the table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    """Apply migration: Add timeout and heartbeat fields to job_queue table."""
    
    # Add last_heartbeat column if it doesn't exist
    if not column_exists('job_queue', 'last_heartbeat'):
        op.add_column(
            'job_queue',
            sa.Column('last_heartbeat', sa.DateTime(), nullable=True)
        )
        print("Added column: last_heartbeat")
    else:
        print("Column last_heartbeat already exists, skipping")
    
    # Add timeout_at column if it doesn't exist
    if not column_exists('job_queue', 'timeout_at'):
        op.add_column(
            'job_queue',
            sa.Column('timeout_at', sa.DateTime(), nullable=True)
        )
        print("Added column: timeout_at")
    else:
        print("Column timeout_at already exists, skipping")
    
    # Create index on status column if it doesn't exist
    if not index_exists('job_queue', 'idx_job_queue_status'):
        op.create_index(
            'idx_job_queue_status',
            'job_queue',
            ['status']
        )
        print("Created index: idx_job_queue_status")
    else:
        print("Index idx_job_queue_status already exists, skipping")
    
    # Create composite index on video_id + status if it doesn't exist
    if not index_exists('job_queue', 'idx_job_queue_video_status'):
        op.create_index(
            'idx_job_queue_video_status',
            'job_queue',
            ['video_id', 'status']
        )
        print("Created index: idx_job_queue_video_status")
    else:
        print("Index idx_job_queue_video_status already exists, skipping")
    
    print("Migration completed successfully!")


def downgrade():
    """Revert migration: Remove timeout and heartbeat fields from job_queue table."""
    
    # Drop composite index
    if index_exists('job_queue', 'idx_job_queue_video_status'):
        op.drop_index('idx_job_queue_video_status', table_name='job_queue')
        print("Dropped index: idx_job_queue_video_status")
    
    # Drop status index
    if index_exists('job_queue', 'idx_job_queue_status'):
        op.drop_index('idx_job_queue_status', table_name='job_queue')
        print("Dropped index: idx_job_queue_status")
    
    # Drop timeout_at column
    if column_exists('job_queue', 'timeout_at'):
        op.drop_column('job_queue', 'timeout_at')
        print("Dropped column: timeout_at")
    
    # Drop last_heartbeat column
    if column_exists('job_queue', 'last_heartbeat'):
        op.drop_column('job_queue', 'last_heartbeat')
        print("Dropped column: last_heartbeat")
    
    print("Downgrade completed successfully!")


if __name__ == "__main__":
    # Allow running as standalone script for testing
    print("This is an Alembic migration script.")
    print("Run with: alembic upgrade add_job_queue_timeout_fields")
