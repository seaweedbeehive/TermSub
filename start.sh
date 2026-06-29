#!/bin/sh
set -e

# Recover alembic version if database has tables but no version stamp
python -c "
import os, sys
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

db_url = os.environ.get('DATABASE_URL')
if not db_url:
    print('ERROR: DATABASE_URL not set', file=sys.stderr)
    sys.exit(1)

engine = create_engine(db_url)
with engine.connect() as conn:
    try:
        result = conn.execute(text('SELECT version_num FROM alembic_version LIMIT 1')).fetchone()
        current = result[0] if result else None
    except ProgrammingError:
        current = None

    if current is None:
        try:
            conn.execute(text('SELECT 1 FROM users LIMIT 1'))
            has_users = True
        except ProgrammingError:
            has_users = False

        if has_users:
            print('DB has tables but no alembic version. Stamping to 92302a4839eb...')
            conn.execute(text(\"INSERT INTO alembic_version (version_num) VALUES ('92302a4839eb')\"))
            conn.commit()
            print('Stamped successfully.')
        else:
            print('Fresh database - migrations will create everything.')
"

# Run all pending migrations
alembic upgrade heads

# Start Celery worker in background
celery -A app.core.celery_app worker --loglevel=info --concurrency=2 &

# Start FastAPI web server (foreground)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
