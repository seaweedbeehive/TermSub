"""Celery application configuration.

Configures Celery to use Redis as both broker and result backend.
The broker URL and backend URL default to the Docker Compose service name.

Connection budget math for Render's 50-connection Redis plan:
- Celery worker: 5 processes × (3 broker + 3 backend) = ~30
- Shared web/worker Redis pool: 15
- Async pub/sub listener pool: 5
- Safety buffer: ~5
- Total: ~55, tuned below to stay safely under 50.

Tune with environment variables:
  CELERY_WORKER_CONCURRENCY
  CELERY_BROKER_POOL_LIMIT
  CELERY_REDIS_MAX_CONNECTIONS
  CELERY_RESULT_BACKEND_MAX_CONNECTIONS
  REDIS_MAX_CONNECTIONS
"""

import os

from celery import Celery

from app.core.config import settings

# Redis URL from settings so it can be overridden via env var for local dev
celery_app = Celery(
    "termsub",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.worker.tasks", "app.worker.text_tasks"],
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
    # Worker concurrency and Redis connection limits.
    # These keep total Redis connections under Render's 50-connection cap.
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", "5")),
    broker_pool_limit=int(os.getenv("CELERY_BROKER_POOL_LIMIT", "3")),
    redis_max_connections=int(os.getenv("CELERY_REDIS_MAX_CONNECTIONS", "3")),
    result_backend_max_connections=int(
        os.getenv("CELERY_RESULT_BACKEND_MAX_CONNECTIONS", "3")
    ),
)
