"""add text job types to job_queue

Revision ID: f1a3ae98e623
Revises: 8a95a76043aa
Create Date: 2026-07-08 15:34:06.109367

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a3ae98e623"
down_revision: str | None = "8a95a76043aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_job_queue_job_type", "job_queue", type_="check")
    op.create_check_constraint(
        "ck_job_queue_job_type",
        "job_queue",
        sa.text(
            "job_type IN ('transcribe', 'analyze', 'translate', "
            "'text_analyze', 'text_translate')"
        ),
    )


def downgrade() -> None:
    op.drop_constraint("ck_job_queue_job_type", "job_queue", type_="check")
    op.create_check_constraint(
        "ck_job_queue_job_type",
        "job_queue",
        sa.text("job_type IN ('transcribe', 'analyze', 'translate')"),
    )
