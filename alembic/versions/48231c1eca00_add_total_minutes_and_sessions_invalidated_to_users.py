"""add total_minutes_used and sessions_invalidated_at to users

Revision ID: 48231c1eca00
Revises: 97ee351d663f
Create Date: 2026-06-28 23:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "48231c1eca00"
down_revision: str | None = "97ee351d663f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add total_minutes_used with a guard so the migration is safe to re-run
    # on databases that already have the column.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name = 'total_minutes_used'
            ) THEN
                ALTER TABLE users
                ADD COLUMN total_minutes_used INTEGER NOT NULL DEFAULT 0;
            END IF;
        END
        $$;
        """
    )

    # Add sessions_invalidated_at with the same guard.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name = 'sessions_invalidated_at'
            ) THEN
                ALTER TABLE users
                ADD COLUMN sessions_invalidated_at TIMESTAMP WITHOUT TIME ZONE;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Drop columns only if they exist to keep the downgrade idempotent as well.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name = 'sessions_invalidated_at'
            ) THEN
                ALTER TABLE users DROP COLUMN sessions_invalidated_at;
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name = 'total_minutes_used'
            ) THEN
                ALTER TABLE users DROP COLUMN total_minutes_used;
            END IF;
        END
        $$;
        """
    )
