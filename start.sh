#!/bin/sh

# Run database migrations first
alembic upgrade heads

# Start Celery worker in background
celery -A app.core.celery_app worker --loglevel=info --concurrency=2 &

# Start FastAPI web server (foreground)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000