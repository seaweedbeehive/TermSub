"""Celery background tasks for TermSub.

Replaces the legacy SQLite queue worker with professional Celery tasks
backed by Redis. Each task type (transcribe, analyze, translate) is a
separate Celery task with automatic retry and error handling.
"""

import logging
import os
import tempfile
import threading
import traceback
from pathlib import Path
from typing import Any

from celery.exceptions import (
    MaxRetriesExceededError,
    SoftTimeLimitExceeded,
)

from app.core.celery_app import celery_app
from app.core.openai_key_context import byok_api_key
from app.core.quota import QuotaManager
from app.core.redis_pubsub import publish_progress
from app.core.task_tracker import update_task_status
from app.db.session_utils import get_db_session
from app.models.job_queue import JobStatus
from app.models.user import User
from app.models.video import ContentType, Segment, Video, VideoStatus
from app.services.whisper_service import transcribe_video

logger = logging.getLogger(__name__)

# Maximum length for stored error messages
MAX_ERROR_LENGTH = 2000


def _truncate_error(message: str, max_length: int = MAX_ERROR_LENGTH) -> str:
    """Truncate an error message to a safe length for storage."""
    if len(message) <= max_length:
        return message
    return message[: max_length - 3] + "..."


def _cleanup_media_files(video_id: str, audio_path: str | None = None) -> None:
    """Delete uploaded video and temporary audio files after transcription."""
    try:
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video and video.file_path:
                Path(video.file_path).unlink(missing_ok=True)
                logger.info(f"[Cleanup] Deleted uploaded file for video {video_id}")
    except Exception as e:
        logger.warning(f"[Cleanup] Failed to delete uploaded file: {e}")

    temp_audio = audio_path or os.path.join(
        tempfile.gettempdir(), f"termsub_{video_id}.mp3"
    )
    try:
        if temp_audio:
            Path(temp_audio).unlink(missing_ok=True)
            logger.info(f"[Cleanup] Deleted temp audio file for video {video_id}")
    except Exception as e:
        logger.warning(f"[Cleanup] Failed to delete temp audio file: {e}")


def _send_progress(video_id: str, data: dict[str, Any]) -> None:
    """Send a progress update via Redis Pub/Sub to WebSocket clients."""
    publish_progress(video_id, data)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=1500,  # 25 minutes
    time_limit=1800,  # 30 minutes
)
def transcribe_video_task(
    self: Any,
    video_id: str,
    api_key: str | None = None,
    user_id: str | None = None,
    is_byok: bool = False,
) -> dict[str, Any]:
    """Celery task: transcribe a video using OpenAI Whisper.

    Args:
        video_id: The video ID to transcribe.
        api_key: Optional per-request OpenAI API key.
        user_id: Owner user id (standard) or BYOK key hash.
        is_byok: Whether the owner is a BYOK user.

    Returns:
        Dictionary with segment count and audio path.
    """
    logger.info(f"[Task] Starting transcription for {video_id}")
    update_task_status(self.request.id, JobStatus.RUNNING.value)

    quota = QuotaManager()
    heartbeat_thread = None
    stop_heartbeat = threading.Event()
    ctx_token = None

    def _heartbeat_loop() -> None:
        while not stop_heartbeat.wait(60):
            try:
                quota.refresh_byok_job(user_id, self.request.id)
            except Exception as exc:
                logger.warning(f"[Task] BYOK heartbeat failed for {video_id}: {exc}")

    if api_key:
        ctx_token = byok_api_key.set(api_key)

    if is_byok and user_id:
        quota.register_byok_job(user_id, self.request.id)
        heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
        heartbeat_thread.start()

    _send_progress(
        video_id,
        {
            "type": "job_started",
            "job_type": "transcribe",
            "job_id": self.request.id,
            "status": "running",
        },
    )

    try:
        # Fetch video metadata with a short session
        source_language = None
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise ValueError(f"Video not found: {video_id}")
            if video.status == VideoStatus.ERROR.value:
                raise RuntimeError(
                    f"Video {video_id} is in ERROR status, aborting transcription"
                )
            source_language = video.source_language

        _send_progress(
            video_id,
            {
                "status": "transcribing",
                "progress": 10,
                "message": "Starting OpenAI Cloud transcription...",
            },
        )

        # Run transcription (long-running, no DB session held)
        if source_language:
            result = transcribe_video(
                video_id, language=source_language, api_key=api_key
            )
        else:
            result = transcribe_video(video_id, api_key=api_key)

        # Verify segments were created
        segment_count = 0
        actual_minutes = 0.0
        with get_db_session() as db:
            segment_count = (
                db.query(Segment).filter(Segment.video_id == video_id).count()
            )
            if segment_count == 0:
                raise RuntimeError("No segments were created")

            max_end = (
                db.query(Segment)
                .filter(Segment.video_id == video_id)
                .with_entities(Segment.end_time)
                .order_by(Segment.end_time.desc())
                .first()
            )
            if max_end:
                actual_minutes = max_end[0] / 60.0

            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.TRANSCRIBED.value

        # Adjust the quota minutes estimate with the actual duration
        if not is_byok and user_id:
            try:
                owner, byok_flag, estimated_minutes = quota.get_video_owner(video_id)
                if owner == user_id and not byok_flag:
                    quota.record_actual_minutes(
                        user_id, estimated_minutes, actual_minutes
                    )
                    with get_db_session() as db:
                        user = db.query(User).filter(User.id == user_id).first()
                        if user:
                            quota_status = quota.get_quota_status(user_id)
                            user.total_minutes_used = max(
                                0, int(round(quota_status["minutes_used"]))
                            )
            except Exception as exc:
                logger.warning(
                    f"[Task] Failed to record actual minutes for {video_id}: {exc}"
                )

        _send_progress(
            video_id,
            {
                "status": "transcribed",
                "progress": 100,
                "message": f"Transcription complete: {segment_count} segments",
                "total_segments": segment_count,
            },
        )

        _send_progress(
            video_id,
            {
                "status": "awaiting_choice",
                "message": "Transcription complete.",
                "total_segments": segment_count,
            },
        )

        update_task_status(self.request.id, JobStatus.COMPLETE.value)
        _send_progress(
            video_id,
            {
                "type": "job_complete",
                "job_type": "transcribe",
                "job_id": self.request.id,
                "status": "completed",
                "result": {"total_segments": segment_count},
            },
        )

        return {
            "total_segments": segment_count,
            "video_status": VideoStatus.TRANSCRIBED.value,
            "audio_path": result.get("audio_path")
            if isinstance(result, dict)
            else None,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[Task] Transcription soft time limit exceeded for {video_id}")
        _mark_video_error(video_id, "Transcription timed out (soft limit)")
        update_task_status(
            self.request.id, JobStatus.ERROR.value, "Soft time limit exceeded"
        )
        raise

    except Exception as exc:
        error_msg = str(exc)
        error_trace = traceback.format_exc()
        logger.error(f"[Task] Transcription failed for {video_id}: {error_msg}")
        logger.debug(error_trace)

        _send_progress(
            video_id,
            {
                "type": "job_error",
                "job_type": "transcribe",
                "job_id": self.request.id,
                "status": "error",
                "error": error_msg,
            },
        )

        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            full_error = _truncate_error(f"{error_msg}\n{error_trace}")
            _mark_video_error(video_id, full_error)
            update_task_status(self.request.id, JobStatus.ERROR.value, full_error)
            raise

    finally:
        if is_byok and user_id:
            stop_heartbeat.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=5)
            try:
                quota.unregister_byok_job(user_id, self.request.id)
            except Exception as exc:
                logger.warning(
                    f"[Task] Failed to unregister BYOK job for {video_id}: {exc}"
                )
        if ctx_token is not None:
            try:
                byok_api_key.reset(ctx_token)
            except Exception as exc:
                logger.warning(f"[Task] Failed to reset BYOK context for {video_id}: {exc}")
        # Always clean up media files after transcription attempt
        _cleanup_media_files(video_id)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=1500,
    time_limit=1800,
)
def analyze_video_task(
    self: Any,
    video_id: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Celery task: analyze video context and extract glossary terms.

    Args:
        video_id: The video ID to analyze.
        api_key: Optional per-request OpenAI API key (BYOK).

    Returns:
        Dictionary with term count and video status.
    """
    logger.info(f"[Task] Starting analysis for {video_id}")
    update_task_status(self.request.id, JobStatus.RUNNING.value)

    ctx_token = None
    if api_key:
        ctx_token = byok_api_key.set(api_key)

    _send_progress(
        video_id,
        {
            "type": "job_started",
            "job_type": "analyze",
            "job_id": self.request.id,
            "status": "running",
        },
    )

    try:
        # Check video exists and get skip_glossary flag
        skip_glossary = False
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise ValueError(f"Video not found: {video_id}")
            if video.status == VideoStatus.ERROR.value:
                raise RuntimeError(
                    f"Video {video_id} is in ERROR status, aborting analysis"
                )
            skip_glossary = video.skip_glossary

        # Short-circuit if glossary should be skipped
        if skip_glossary:
            logger.info(f"[Task] Analysis skipped for {video_id} (skip_glossary=True)")
            _send_progress(
                video_id,
                {
                    "status": "terms_ready",
                    "progress": 100,
                    "message": (
                        "Terminology extraction skipped — proceeding to translation"
                    ),
                    "terms_count": 0,
                },
            )
            update_task_status(self.request.id, JobStatus.COMPLETE.value)
            return {
                "terms_extracted": 0,
                "video_status": "terms_ready",
                "skipped": True,
            }

        _send_progress(
            video_id,
            {
                "status": "analyzing",
                "progress": 0,
                "message": "Director Agent: Analyzing content...",
            },
        )

        from app.services.context_analysis_service import (
            analyze_video_context,
            extract_glossary,
        )

        _send_progress(
            video_id,
            {
                "status": "analyzing",
                "progress": 20,
                "message": "Analyzing content style...",
            },
        )

        style_guide = analyze_video_context(video_id)

        _send_progress(
            video_id,
            {
                "status": "context_ready",
                "progress": 50,
                "message": (
                    f"Director complete: {style_guide.get('tone', 'neutral')} tone"
                ),
                "tone": style_guide.get("tone", "neutral"),
                "formality_level": style_guide.get("formality_level", "medium"),
            },
        )

        _send_progress(
            video_id,
            {
                "status": "glossary_extracting",
                "progress": 60,
                "message": "Extracting terms...",
            },
        )

        context_data = extract_glossary(video_id, style_guide)
        term_count = len(context_data.get("key_terms", []))

        _send_progress(
            video_id,
            {
                "status": "terms_ready",
                "progress": 100,
                "message": f"Analysis complete: {term_count} terms",
                "terms_count": term_count,
            },
        )

        update_task_status(self.request.id, JobStatus.COMPLETE.value)
        _send_progress(
            video_id,
            {
                "type": "job_complete",
                "job_type": "analyze",
                "job_id": self.request.id,
                "status": "completed",
                "result": {"terms_extracted": term_count},
            },
        )

        return {
            "terms_extracted": term_count,
            "video_status": "terms_ready",
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[Task] Analysis soft time limit exceeded for {video_id}")
        _mark_video_error(video_id, "Analysis timed out (soft limit)")
        update_task_status(
            self.request.id, JobStatus.ERROR.value, "Soft time limit exceeded"
        )
        raise

    except Exception as exc:
        error_msg = str(exc)
        error_trace = traceback.format_exc()
        logger.error(f"[Task] Analysis failed for {video_id}: {error_msg}")
        logger.debug(error_trace)

        _send_progress(
            video_id,
            {
                "type": "job_error",
                "job_type": "analyze",
                "job_id": self.request.id,
                "status": "error",
                "error": error_msg,
            },
        )

        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            full_error = _truncate_error(f"{error_msg}\n{error_trace}")
            _mark_video_error(video_id, full_error)
            update_task_status(self.request.id, JobStatus.ERROR.value, full_error)
            raise

    finally:
        if ctx_token is not None:
            try:
                byok_api_key.reset(ctx_token)
            except Exception as exc:
                logger.warning(f"[Task] Failed to reset BYOK context for {video_id}: {exc}")


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=1500,
    time_limit=1800,
)
def translate_video_task(
    self: Any,
    video_id: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Celery task: translate video segments using the multi-agent pipeline.

    Args:
        video_id: The video ID to translate.
        api_key: Optional per-request OpenAI API key (BYOK).

    Returns:
        Dictionary with segment counts and video status.
    """
    logger.info(f"[Task] Starting translation for {video_id}")
    update_task_status(self.request.id, JobStatus.RUNNING.value)

    ctx_token = None
    if api_key:
        ctx_token = byok_api_key.set(api_key)

    _send_progress(
        video_id,
        {
            "type": "job_started",
            "job_type": "translate",
            "job_id": self.request.id,
            "status": "running",
        },
    )

    try:
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise ValueError(f"Video not found: {video_id}")
            if video.status == VideoStatus.ERROR.value:
                raise RuntimeError(
                    f"Video {video_id} is in ERROR status, aborting translation"
                )

        _send_progress(
            video_id,
            {
                "status": "translating",
                "progress": 0,
                "message": "Starting translation...",
            },
        )

        from sqlalchemy import func

        from app.services.translation_pipeline import TranslationPipeline

        # Enforce text-translation character quota for non-BYOK users.
        with get_db_session() as db:
            video_for_quota = db.query(Video).filter(Video.id == video_id).first()
            identity_for_quota = None
            if video_for_quota:
                from app.core.auth import RequestIdentity
                if video_for_quota.user_id:
                    identity_for_quota = RequestIdentity(
                        user_id=video_for_quota.user_id,
                        is_byok=False,
                        api_key=None,
                    )
                elif video_for_quota.byok_user_id:
                    identity_for_quota = RequestIdentity(
                        user_id=video_for_quota.byok_user_id,
                        is_byok=True,
                        api_key=None,
                    )
            if identity_for_quota and video_for_quota.content_type == ContentType.TEXT.value:
                total_chars = (
                    db.query(func.coalesce(func.sum(func.length(Segment.original_text)), 0))
                    .filter(Segment.video_id == video_id)
                    .scalar()
                    or 0
                )
                quota = QuotaManager()
                check = quota.check_text_translation_allowed(
                    identity_for_quota.user_id,
                    int(total_chars),
                    identity_for_quota.is_byok,
                )
                if not check["allowed"]:
                    raise RuntimeError(check["reason"])

        pipeline = TranslationPipeline()
        translate_result = pipeline.translate_with_glossary_sync(video_id)

        if translate_result and not translate_result.get("success", True):
            logger.warning(
                f"[Task] Translation returned non-success: {translate_result}"
            )

        # Record consumed text-translation characters after successful translation.
        if identity_for_quota and video_for_quota.content_type == ContentType.TEXT.value:
            with get_db_session() as db_quota:
                translated_chars = sum(
                    len(s.translated_text or "")
                    for s in db_quota.query(Segment)
                    .filter(Segment.video_id == video_id)
                    .all()
                )
                quota.record_text_translation(
                    identity_for_quota.user_id,
                    translated_chars,
                )

        # Fetch results with a fresh session
        total = 0
        translated = 0
        segment_rows = []
        with get_db_session() as db:
            total = (
                db.query(func.count(Segment.id))
                .filter(Segment.video_id == video_id)
                .scalar()
                or 0
            )

            translated = (
                db.query(func.count(Segment.id))
                .filter(
                    Segment.video_id == video_id,
                    Segment.translated_text.isnot(None),
                )
                .scalar()
                or 0
            )

            segment_rows = [
                {
                    "id": s.id,
                    "sequence_number": s.sequence_number,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "original_text": s.original_text,
                    "translated_text": s.translated_text,
                }
                for s in db.query(Segment)
                .filter(Segment.video_id == video_id)
                .order_by(Segment.sequence_number)
                .all()
            ]

        if translated != total:
            raise RuntimeError(
                f"Translation incomplete: {translated}/{total} segments translated. "
                "Retrying the task."
            )

        _send_progress(
            video_id,
            {
                "status": "completed",
                "progress": 100,
                "message": f"Translation complete: {translated}/{total} segments",
                "segments": segment_rows,
            },
        )

        update_task_status(self.request.id, JobStatus.COMPLETE.value)
        _send_progress(
            video_id,
            {
                "type": "job_complete",
                "job_type": "translate",
                "job_id": self.request.id,
                "status": "completed",
                "result": {
                    "total_segments": total,
                    "translated_segments": translated,
                },
            },
        )

        return {
            "total_segments": total,
            "translated_segments": translated,
            "video_status": VideoStatus.COMPLETED.value,
            "segments": segment_rows,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[Task] Translation soft time limit exceeded for {video_id}")
        _mark_video_error(video_id, "Translation timed out (soft limit)")
        update_task_status(
            self.request.id, JobStatus.ERROR.value, "Soft time limit exceeded"
        )
        raise

    except Exception as exc:
        error_msg = str(exc)
        error_trace = traceback.format_exc()
        logger.error(f"[Task] Translation failed for {video_id}: {error_msg}")
        logger.debug(error_trace)

        _send_progress(
            video_id,
            {
                "type": "job_error",
                "job_type": "translate",
                "job_id": self.request.id,
                "status": "error",
                "error": error_msg,
            },
        )

        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            full_error = _truncate_error(f"{error_msg}\n{error_trace}")
            _mark_video_error(video_id, full_error)
            update_task_status(self.request.id, JobStatus.ERROR.value, full_error)
            raise

    finally:
        if ctx_token is not None:
            try:
                byok_api_key.reset(ctx_token)
            except Exception as exc:
                logger.warning(f"[Task] Failed to reset BYOK context for {video_id}: {exc}")


def _mark_video_error(video_id: str, error_message: str) -> None:
    """Mark a video as ERROR in the database."""
    try:
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.ERROR.value
                video.error_message = _truncate_error(error_message)
    except Exception as e:
        logger.warning(f"[Task] Failed to mark video {video_id} as error: {e}")
