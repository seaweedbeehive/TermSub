"""Celery application configuration.

Configures Celery to use Redis as both broker and result backend.
The broker URL and backend URL default to the Docker Compose service name.
"""

from celery import Celery

from app.core.config import settings

# Redis URL from settings so it can be overridden via env var for local dev
celery_app = Celery(
    "termsub",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=1800,  # 30 minutes hard limit
    task_soft_time_limit=1500,  # 25 minutes soft limit
    worker_prefetch_multiplier=1,
    result_expires=3600 * 24,  # Keep results for 24 hours
)
