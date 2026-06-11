"""Lightweight task tracker using the existing JobQueue table.

Maps Celery task IDs to videos so the status endpoint can resolve
video_id -> task_id and query Celery for the live task state.
"""

from datetime import datetime

from app.db.session_utils import get_db_session
from app.models.job_queue import JobQueue, JobStatus


def record_task(video_id: str, job_type: str, celery_task_id: str) -> None:
    """Create a JobQueue record linking a video to its Celery task.

    Args:
        video_id: The video ID.
        job_type: Type of job (transcribe, analyze, translate).
        celery_task_id: The Celery AsyncResult ID.
    """
    with get_db_session() as db:
        job = JobQueue(
            job_type=job_type,
            video_id=video_id,
            status=JobStatus.PENDING.value,
            retry_count=0,
            celery_task_id=celery_task_id,
        )
        db.add(job)


def get_latest_task_id(video_id: str) -> str | None:
    """Get the most recent Celery task ID for a video.

    Args:
        video_id: The video ID.

    Returns:
        Celery task ID string, or None if no tasks found.
    """
    with get_db_session() as db:
        job = (
            db.query(JobQueue)
            .filter(JobQueue.video_id == video_id)
            .order_by(JobQueue.created_at.desc())
            .first()
        )
        return job.celery_task_id if job else None


def update_task_status(
    celery_task_id: str, status: str, error_message: str | None = None
) -> None:
    """Update the stored status for a given Celery task.

    Args:
        celery_task_id: The Celery task ID.
        status: New status value (pending, running, complete, error).
        error_message: Optional error message.
    """
    with get_db_session() as db:
        job = (
            db.query(JobQueue).filter(JobQueue.celery_task_id == celery_task_id).first()
        )
        if job:
            job.status = status
            if error_message:
                job.error_message = error_message
            if status in (JobStatus.COMPLETE.value, JobStatus.ERROR.value):
                job.completed_at = datetime.utcnow()
