#!/bin/sh
# Start script for TermSub on Render's free tier.
# Runs the Celery worker in the background and the FastAPI web server in the foreground.

# Start Celery worker in the background
celery -A app.core.celery_app worker --loglevel=info --concurrency=2 &

# Start FastAPI web server in the foreground
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
