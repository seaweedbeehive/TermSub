"""Add segment confidence fields

Revision ID: 82e2a6589c16
Revises: f1a3ae98e623
Create Date: 2026-07-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82e2a6589c16'
down_revision: Union[str, None] = 'f1a3ae98e623'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('segments', sa.Column('avg_logprob', sa.Float(), nullable=True))
    op.add_column('segments', sa.Column('no_speech_prob', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('segments', 'no_speech_prob')
    op.drop_column('segments', 'avg_logprob')
