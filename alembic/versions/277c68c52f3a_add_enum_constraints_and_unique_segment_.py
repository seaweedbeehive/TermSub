"""add_enum_constraints_and_unique_segment_index

Revision ID: 277c68c52f3a
Revises: 48231c1eca00
Create Date: 2026-07-03 20:17:28.194749

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '277c68c52f3a'
down_revision: Union[str, None] = '48231c1eca00'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make the segment (video_id, sequence_number) index unique.
    op.drop_index("idx_segments_video_seq", table_name="segments")
    op.create_index(
        "idx_segments_video_seq",
        "segments",
        ["video_id", "sequence_number"],
        unique=True,
    )

    # Enum-like check constraints.
    op.create_check_constraint(
        "ck_videos_content_type",
        "videos",
        "content_type IN ('video', 'text')",
    )
    op.create_check_constraint(
        "ck_videos_status",
        "videos",
        "status IN ('uploaded', 'queued', 'extracting_audio', 'transcribing', "
        "'transcribed', 'analyzing', 'context_ready', 'glossary_extracting', "
        "'terms_ready', 'translating', 'completed', 'error')",
    )
    op.create_check_constraint(
        "ck_videos_domain",
        "videos",
        "domain IN ('general', 'politics', 'medicine', 'psychology', 'sociology')",
    )
    op.create_check_constraint(
        "ck_job_queue_status",
        "job_queue",
        "status IN ('pending', 'running', 'complete', 'error')",
    )
    op.create_check_constraint(
        "ck_job_queue_job_type",
        "job_queue",
        "job_type IN ('transcribe', 'analyze', 'translate')",
    )
    op.create_check_constraint(
        "ck_users_api_key_mode",
        "users",
        "api_key_mode IN ('standard', 'byok')",
    )
    op.create_check_constraint(
        "ck_terms_source",
        "terms",
        "source IN ('auto', 'manual')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_terms_source", "terms", type_="check")
    op.drop_constraint("ck_users_api_key_mode", "users", type_="check")
    op.drop_constraint("ck_job_queue_job_type", "job_queue", type_="check")
    op.drop_constraint("ck_job_queue_status", "job_queue", type_="check")
    op.drop_constraint("ck_videos_domain", "videos", type_="check")
    op.drop_constraint("ck_videos_status", "videos", type_="check")
    op.drop_constraint("ck_videos_content_type", "videos", type_="check")

    op.drop_index("idx_segments_video_seq", table_name="segments")
    op.create_index(
        "idx_segments_video_seq",
        "segments",
        ["video_id", "sequence_number"],
        unique=False,
    )
