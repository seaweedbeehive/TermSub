"""add enum constraints and unique segment index

Revision ID: 8a95a76043aa
Revises: 79b85294de0a
Create Date: 2026-07-04 11:13:40.712401

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8a95a76043aa'
down_revision: Union[str, None] = '79b85294de0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make the per-video segment sequence unique. Drop any existing
    # non-unique version first so this migration works against fresh
    # databases and pre-existing databases alike.
    op.execute(
        "DROP INDEX IF EXISTS idx_segments_video_seq"
    )
    op.create_index(
        'idx_segments_video_seq',
        'segments',
        ['video_id', 'sequence_number'],
        unique=True,
    )

    # Enum-like check constraints. PostgreSQL does not support
    # `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS`, so use a PL/pgSQL
    # block that checks pg_constraint first. This lets the same migration
    # run against fresh databases and baselined/existing databases.
    _ensure_check_constraint(
        'job_queue', 'ck_job_queue_job_type',
        "job_type IN ('transcribe', 'analyze', 'translate')"
    )
    _ensure_check_constraint(
        'job_queue', 'ck_job_queue_status',
        "status IN ('pending', 'running', 'complete', 'error')"
    )
    _ensure_check_constraint(
        'videos', 'ck_videos_content_type',
        "content_type IN ('video', 'text')"
    )
    _ensure_check_constraint(
        'videos', 'ck_videos_status',
        "status IN ('uploaded', 'queued', 'extracting_audio', "
        "'transcribing', 'transcribed', 'analyzing', 'context_ready', "
        "'glossary_extracting', 'terms_ready', 'translating', 'completed', 'error')"
    )
    _ensure_check_constraint(
        'videos', 'ck_videos_domain',
        "domain IN ('general', 'politics', 'medicine', 'psychology', 'sociology')"
    )
    _ensure_check_constraint(
        'terms', 'ck_terms_source',
        "source IN ('auto', 'manual')"
    )
    _ensure_check_constraint(
        'users', 'ck_users_api_key_mode',
        "api_key_mode IN ('standard', 'byok')"
    )


def _ensure_check_constraint(table: str, name: str, check: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{name}' AND conrelid = '{table}'::regclass
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check});
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.drop_constraint('ck_users_api_key_mode', 'users', type_='check')
    op.drop_constraint('ck_terms_source', 'terms', type_='check')
    op.drop_constraint('ck_videos_domain', 'videos', type_='check')
    op.drop_constraint('ck_videos_status', 'videos', type_='check')
    op.drop_constraint('ck_videos_content_type', 'videos', type_='check')
    op.drop_constraint('ck_job_queue_status', 'job_queue', type_='check')
    op.drop_constraint('ck_job_queue_job_type', 'job_queue', type_='check')

    op.drop_index('idx_segments_video_seq', table_name='segments')
    op.create_index(
        'idx_segments_video_seq',
        'segments',
        ['video_id', 'sequence_number'],
        unique=False,
    )
