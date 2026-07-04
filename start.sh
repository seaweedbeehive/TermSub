#!/bin/sh
set -e

# Wait for PostgreSQL to be ready before running migrations.
DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-termsub}"
DB_NAME="${DB_NAME:-termsub}"

until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME"; do
  echo "Waiting for database at $DB_HOST:$DB_PORT..."
  sleep 1
done

alembic upgrade head

celery -A app.core.celery_app worker --loglevel=info --concurrency=2 &

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
