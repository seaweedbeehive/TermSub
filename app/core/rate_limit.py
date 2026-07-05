"""Sliding-window rate limiting using Redis.

Provides a reusable decorator for FastAPI endpoints. If Redis is unavailable,
rate limiting is skipped and a warning is logged so the endpoint remains usable.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from fastapi import HTTPException, Request, status

from app.core.redis_pool import get_redis_client as get_sync_redis_client

logger = logging.getLogger(__name__)


class RateLimiter:
    """Sliding-window rate limiter backed by Redis sorted sets."""

    def __init__(self) -> None:
        self._redis: Any | None = None
        self._redis_available: bool | None = None

    def _get_redis(self) -> Any | None:
        """Return the sync Redis client, or None if Redis is unreachable."""
        if self._redis_available is False:
            return None
        if self._redis is None:
            try:
                self._redis = get_sync_redis_client()
                self._redis_available = True
            except Exception as exc:
                self._redis_available = False
                logger.warning("Redis unavailable for rate limiting: %s", exc)
                return None
        return self._redis

    def is_allowed(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds) for the given key.

        Uses a Redis sorted set where scores are millisecond timestamps. Old
        entries outside the window are trimmed, then the remaining count is
        compared to the limit.
        """
        redis = self._get_redis()
        if redis is None:
            # Redis unavailable: fail open so auth endpoints keep working.
            return True, 0

        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - (window * 1000)

        try:
            pipe = redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start_ms)
            pipe.zcard(key)
            pipe.zadd(key, {str(now_ms): now_ms})
            pipe.pexpire(key, window * 1000)
            _, current_count, added, _ = pipe.execute()

            # ``added`` is the number of elements added (0 or 1).
            if current_count + added > limit:
                # Roll back the current attempt so the window remains accurate.
                redis.zrem(key, str(now_ms))

                # Compute time until the oldest entry in the window expires.
                oldest = redis.zrange(key, 0, 0, withscores=True)
                if oldest:
                    oldest_ts_ms = oldest[0][1]
                    retry_after = max(
                        1, int((oldest_ts_ms + window * 1000 - now_ms) / 1000)
                    )
                else:
                    retry_after = window
                return False, retry_after

            return True, 0
        except Exception as exc:
            logger.warning("Redis rate-limit check failed for %s: %s", key, exc)
            return True, 0


_limiter = RateLimiter()


def _get_client_ip(request: Request) -> str:
    """Return the client's IP address from the request."""
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _get_identifier(
    identifier: str | Callable[[Request, dict[str, Any]], str | None],
    request: Request,
    kwargs: dict[str, Any],
) -> str | None:
    """Resolve the rate-limit identifier from request/kwargs."""
    if callable(identifier):
        return identifier(request, kwargs)

    if identifier == "ip":
        return _get_client_ip(request)

    if identifier == "email":
        payload = kwargs.get("payload")
        if payload is not None and hasattr(payload, "email"):
            email = payload.email
            return email.strip().lower() if isinstance(email, str) else str(email)
        return None

    return None


def rate_limit(
    endpoint: str,
    *,
    limit: int,
    window: int,
    identifier: str | Callable[[Request, dict[str, Any]], str | None] = "ip",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that enforces a sliding-window rate limit on a FastAPI endpoint.

    Args:
        endpoint: Logical endpoint name used in the Redis key.
        limit: Maximum number of requests allowed in the window.
        window: Window size in seconds.
        identifier: ``"ip"`` (default), ``"email"``, or a callable that receives
            the FastAPI ``Request`` and endpoint keyword arguments and returns
            an identifier string (or ``None`` to skip rate limiting).

    Raises:
        HTTPException: 429 if the rate limit is exceeded.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if not isinstance(request, Request):
                logger.warning(
                    "Rate limiting skipped for %s: no Request object available",
                    endpoint,
                )
                return func(*args, **kwargs)

            ident = _get_identifier(identifier, request, kwargs)
            if not ident:
                logger.warning(
                    "Rate limiting skipped for %s: could not determine identifier",
                    endpoint,
                )
                return func(*args, **kwargs)

            key = f"rate_limit:{endpoint}:{ident}"
            allowed, retry_after = _limiter.is_allowed(key, limit, window)
            if not allowed:
                minutes = max(1, retry_after // 60)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many attempts. Please try again in {minutes} minutes.",
                )

            return func(*args, **kwargs)

        return wrapper

    return decorator
