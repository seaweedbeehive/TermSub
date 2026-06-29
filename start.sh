#!/bin/sh
set -e

alembic upgrade heads

celery -A app.core.celery_app worker --loglevel=info --concurrency=2 &

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
