"""Redis Pub/Sub bridge for WebSocket progress updates.

Celery workers publish progress messages to a Redis Pub/Sub channel.
The FastAPI process subscribes to this channel and broadcasts messages
via its in-memory WebSocket manager.

This decouples Celery workers (separate processes) from the WebSocket
manager (owned by the FastAPI process).
"""

import asyncio
import json
from typing import Any

import redis
import redis.asyncio as aioredis

from app.core.config import settings

# Default Redis URL — uses the Docker Compose service name
_DEFAULT_REDIS_URL = "redis://redis:6379/0"

# Shared synchronous Redis client for Celery workers
_sync_redis_client: redis.Redis | None = None


def _get_redis_url() -> str:
    """Resolve Redis URL from settings or fallback."""
    return getattr(settings, "REDIS_URL", _DEFAULT_REDIS_URL)


def get_sync_redis_client() -> redis.Redis:
    """Get or create the synchronous Redis client (for Celery workers)."""
    global _sync_redis_client
    if _sync_redis_client is None:
        _sync_redis_client = redis.Redis.from_url(
            _get_redis_url(), decode_responses=True
        )
    return _sync_redis_client


def publish_progress(video_id: str, data: dict[str, Any]) -> None:
    """Publish a progress update to Redis Pub/Sub.

    Called from Celery workers to send real-time updates to the frontend.

    Args:
        video_id: The video ID this update belongs to.
        data: Dictionary of progress data (status, progress, message, etc.).
    """
    try:
        client = get_sync_redis_client()
        message = json.dumps({"video_id": video_id, "data": data})
        client.publish("video_progress", message)
    except Exception as e:
        # Never let a WebSocket publish failure break a background task
        print(f"[RedisPubSub] Failed to publish progress: {e}")


async def start_redis_listener(websocket_manager: Any) -> None:
    """Start the async Redis Pub/Sub listener for WebSocket broadcasts.

    This coroutine should be launched as a background task from the FastAPI
    lifespan. It listens to the 'video_progress' channel and forwards
    messages to all WebSocket clients watching the given video.

    Args:
        websocket_manager: The ConnectionManager instance from main.py.
    """
    redis_url = _get_redis_url()
    client: aioredis.Redis | None = None

    try:
        client = aioredis.from_url(redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
        pubsub = client.pubsub()
        await pubsub.subscribe("video_progress")
        print("[RedisListener] Subscribed to video_progress channel")

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                payload = json.loads(message["data"])
                video_id = payload.get("video_id")
                data = payload.get("data", {})
                if video_id:
                    await websocket_manager.broadcast_to_video(video_id, data)
            except Exception as e:
                print(f"[RedisListener] Error broadcasting message: {e}")

    except asyncio.CancelledError:
        print("[RedisListener] Shutting down...")
        raise
    except Exception as e:
        print(f"[RedisListener] Fatal error: {e}")
        raise
    finally:
        if client is not None:
            await client.close()
