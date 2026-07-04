#!/bin/sh
set -e

# Wait for PostgreSQL to be ready before running migrations.
# Render provides DATABASE_URL as a full URL; Docker Compose provides
# individual DB_* variables. Parse DATABASE_URL when available, otherwise
# fall back to the individual vars.
if [ -n "$DATABASE_URL" ]; then
    eval "$(python -c "
import os, urllib.parse
url = urllib.parse.urlparse(os.environ['DATABASE_URL'])
print(f\"DB_HOST='{url.hostname or 'db'}'\")
print(f\"DB_PORT='{url.port or '5432'}'\")
")"
else
    DB_HOST="${DB_HOST:-db}"
    DB_PORT="${DB_PORT:-5432}"
fi

until pg_isready -h "$DB_HOST" -p "$DB_PORT"; do
  echo "Waiting for database at $DB_HOST:$DB_PORT..."
  sleep 1
done

alembic upgrade head

celery -A app.core.celery_app worker --loglevel=info --concurrency=2 &

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
