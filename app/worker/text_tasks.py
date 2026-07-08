"""Celery background tasks for the text-only translation pipeline.

These tasks are separate from video tasks to keep the text pipeline isolated.
"""

import logging
import threading
import traceback
from typing import Any

from celery.exceptions import MaxRetriesExceededError, SoftTimeLimitExceeded

from app.core.celery_app import celery_app
from app.core.openai_key_context import byok_api_key
from app.core.quota import QuotaManager
from app.core.redis_pubsub import publish_progress
from app.core.task_tracker import update_task_status
from app.db.session_utils import get_db_session
from app.models.job_queue import JobStatus
from app.models.video import Video, VideoStatus
from app.services.text_translation_service import (
    extract_terms_for_text,
    translate_text,
)
from app.core.auth import RequestIdentity

logger = logging.getLogger(__name__)
MAX_ERROR_LENGTH = 2000


def _truncate_error(message: str, max_length: int = MAX_ERROR_LENGTH) -> str:
    if len(message) <= max_length:
        return message
    return message[: max_length - 3] + "..."


def _send_progress(video_id: str, data: dict[str, Any]) -> None:
    """Send a progress update via Redis Pub/Sub."""
    publish_progress(video_id, data)


def _mark_text_error(video_id: str, error_message: str) -> None:
    """Mark a text record as errored."""
    try:
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.ERROR.value
                video.error_message = _truncate_error(error_message)
                db.commit()
    except Exception as exc:
        logger.warning(f"[TextTask] Failed to mark error for {video_id}: {exc}")


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=1500,
    time_limit=1800,
)
def extract_text_terms_task(
    self: Any,
    video_id: str,
    api_key: str | None = None,
    user_id: str | None = None,
    is_byok: bool = False,
) -> dict[str, Any]:
    """Celery task: extract terminology for a text document."""
    logger.info(f"[TextTask] Starting term extraction for {video_id}")
    update_task_status(self.request.id, JobStatus.RUNNING.value)

    quota = QuotaManager()
    ctx_token = None
    heartbeat_thread = None
    stop_heartbeat = threading.Event()

    def _heartbeat_loop() -> None:
        while not stop_heartbeat.wait(60):
            try:
                quota.refresh_byok_job(user_id, self.request.id)
            except Exception as exc:
                logger.warning(
                    f"[TextTask] BYOK heartbeat failed for {video_id}: {exc}"
                )

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
            "job_type": "text_analyze",
            "job_id": self.request.id,
            "status": "running",
        },
    )

    try:
        result = extract_terms_for_text(video_id)
        term_count = len(result.get("key_terms", []))

        update_task_status(self.request.id, JobStatus.COMPLETE.value)
        _send_progress(
            video_id,
            {
                "type": "job_complete",
                "job_type": "text_analyze",
                "job_id": self.request.id,
                "status": "completed",
                "result": {"terms_extracted": term_count},
            },
        )
        return {
            "terms_extracted": term_count,
            "video_status": VideoStatus.TERMS_READY.value,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[TextTask] Term extraction soft time limit exceeded for {video_id}")
        _mark_text_error(video_id, "Term extraction timed out")
        update_task_status(
            self.request.id, JobStatus.ERROR.value, "Soft time limit exceeded"
        )
        raise

    except Exception as exc:
        error_msg = str(exc)
        error_trace = traceback.format_exc()
        logger.error(f"[TextTask] Term extraction failed for {video_id}: {error_msg}")
        _send_progress(
            video_id,
            {
                "type": "job_error",
                "job_type": "text_analyze",
                "job_id": self.request.id,
                "status": "error",
                "error": error_msg,
            },
        )
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            full_error = _truncate_error(f"{error_msg}\n{error_trace}")
            _mark_text_error(video_id, full_error)
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
                    f"[TextTask] Failed to unregister BYOK job for {video_id}: {exc}"
                )
        if ctx_token is not None:
            try:
                byok_api_key.reset(ctx_token)
            except Exception as exc:
                logger.warning(
                    f"[TextTask] Failed to reset BYOK context for {video_id}: {exc}"
                )


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=1500,
    time_limit=1800,
)
def translate_text_task(
    self: Any,
    video_id: str,
    api_key: str | None = None,
    user_id: str | None = None,
    is_byok: bool = False,
) -> dict[str, Any]:
    """Celery task: translate a text document using its glossary."""
    logger.info(f"[TextTask] Starting translation for {video_id}")
    update_task_status(self.request.id, JobStatus.RUNNING.value)

    quota = QuotaManager()
    ctx_token = None
    heartbeat_thread = None
    stop_heartbeat = threading.Event()

    def _heartbeat_loop() -> None:
        while not stop_heartbeat.wait(60):
            try:
                quota.refresh_byok_job(user_id, self.request.id)
            except Exception as exc:
                logger.warning(
                    f"[TextTask] BYOK heartbeat failed for {video_id}: {exc}"
                )

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
            "job_type": "text_translate",
            "job_id": self.request.id,
            "status": "running",
        },
    )

    try:
        identity = RequestIdentity(
            user_id=user_id or "",
            is_byok=is_byok,
            api_key=api_key,
        )
        result = translate_text(video_id, identity)

        update_task_status(self.request.id, JobStatus.COMPLETE.value)
        _send_progress(
            video_id,
            {
                "type": "job_complete",
                "job_type": "text_translate",
                "job_id": self.request.id,
                "status": "completed",
                "result": {
                    "total_segments": result.get("total_segments", 0),
                    "translated_segments": result.get("translated_segments", 0),
                },
            },
        )
        return {
            "total_segments": result.get("total_segments", 0),
            "translated_segments": result.get("translated_segments", 0),
            "video_status": VideoStatus.COMPLETED.value,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[TextTask] Translation soft time limit exceeded for {video_id}")
        _mark_text_error(video_id, "Text translation timed out")
        update_task_status(
            self.request.id, JobStatus.ERROR.value, "Soft time limit exceeded"
        )
        raise

    except Exception as exc:
        error_msg = str(exc)
        error_trace = traceback.format_exc()
        logger.error(f"[TextTask] Translation failed for {video_id}: {error_msg}")
        _send_progress(
            video_id,
            {
                "type": "job_error",
                "job_type": "text_translate",
                "job_id": self.request.id,
                "status": "error",
                "error": error_msg,
            },
        )
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            full_error = _truncate_error(f"{error_msg}\n{error_trace}")
            _mark_text_error(video_id, full_error)
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
                    f"[TextTask] Failed to unregister BYOK job for {video_id}: {exc}"
                )
        if ctx_token is not None:
            try:
                byok_api_key.reset(ctx_token)
            except Exception as exc:
                logger.warning(
                    f"[TextTask] Failed to reset BYOK context for {video_id}: {exc}"
                )
