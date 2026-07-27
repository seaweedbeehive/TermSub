"""Shared Redis connection pool for the TermSub application.

Provides module-level connection pools so the web service, Celery workers,
and pub/sub listeners reuse connections instead of creating new ones for
every operation. This is essential for staying under Render's 50-connection
Redis limit when running Celery with concurrency > 1.

Connection budget math for Render (50 max):
- Celery worker: 5 processes × (3 broker + 3 backend) = ~30
- Shared sync Redis pool (web + worker publishes): 15
- Async pub/sub listener pool: 5
- Safety buffer: ~5
- Total: ~55, tuned by the environment variables below to stay under 50.
"""

import os

import redis
import redis.asyncio as aioredis

from app.core.config import settings

# Max connections for the shared synchronous pool used by web endpoints and
# Celery workers when publishing progress updates.
MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "15"))

# Dedicated async pool for the pub/sub listener. Kept separate so a single
# long-lived subscription does not starve short-lived web operations.
ASYNC_MAX_CONNECTIONS = 5

_sync_pool: redis.ConnectionPool | None = None
_async_pool: aioredis.ConnectionPool | None = None


def get_redis_pool() -> redis.ConnectionPool:
    """Return the shared synchronous Redis connection pool."""
    global _sync_pool
    if _sync_pool is None:
        _sync_pool = redis.ConnectionPool.from_url(  # type: ignore[no-untyped-call]
            settings.REDIS_URL,
            max_connections=MAX_CONNECTIONS,
            decode_responses=True,
        )
    return _sync_pool


def get_redis_client() -> redis.Redis:
    """Return a Redis client backed by the shared synchronous pool."""
    return redis.Redis(connection_pool=get_redis_pool())


def get_async_redis_pool() -> aioredis.ConnectionPool:
    """Return the shared asynchronous Redis connection pool."""
    global _async_pool
    if _async_pool is None:
        _async_pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=ASYNC_MAX_CONNECTIONS,
            decode_responses=True,
        )
    return _async_pool


def get_async_redis_client() -> aioredis.Redis:
    """Return an async Redis client backed by the shared async pool."""
    return aioredis.Redis(connection_pool=get_async_redis_pool())
