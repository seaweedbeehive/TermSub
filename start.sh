#!/bin/sh
# Start Celery worker in background
celery -A app.core.celery_app worker --loglevel=info --concurrency=2 &

# Start FastAPI web server (foreground - Render keeps container alive)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
