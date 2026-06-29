"""remove display_name from users

Revision ID: 97ee351d663f
Revises: 97403f57fa23
Create Date: 2026-06-28 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "97ee351d663f"
down_revision: str | None = "97403f57fa23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'display_name'
            ) THEN
                ALTER TABLE users DROP COLUMN display_name;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("display_name", sa.String(length=255), nullable=True),
    )