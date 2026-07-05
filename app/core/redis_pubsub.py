"""Redis Pub/Sub bridge for WebSocket progress updates.

Celery workers publish progress messages to a Redis Pub/Sub channel.
The FastAPI process subscribes to this channel and broadcasts messages
via its in-memory WebSocket manager.

This decouples Celery workers (separate processes) from the WebSocket
manager (owned by the FastAPI process).

All Redis clients come from app.core.redis_pool so connections are reused
and bounded, keeping the app under Render's 50-connection Redis limit.
"""

import asyncio
import json
from typing import Any

from app.core.redis_pool import get_async_redis_client, get_redis_client


async def start_redis_listener(websocket_manager: Any) -> None:
    """Start the async Redis Pub/Sub listener for WebSocket broadcasts.

    This coroutine should be launched as a background task from the FastAPI
    lifespan. It listens to the 'video_progress' channel and forwards
    messages to all WebSocket clients watching the given video.

    The async Redis client is taken from the shared async pool; only the
    pub/sub object is closed on shutdown so the underlying pool stays alive.

    Args:
        websocket_manager: The ConnectionManager instance from main.py.
    """
    client = get_async_redis_client()
    pubsub = client.pubsub()

    try:
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
        await pubsub.close()


def publish_progress(video_id: str, data: dict[str, Any]) -> None:
    """Publish a progress update to Redis Pub/Sub.

    Called from Celery workers to send real-time updates to the frontend.

    Args:
        video_id: The video ID this update belongs to.
        data: Dictionary of progress data (status, progress, message, etc.).
    """
    try:
        client = get_redis_client()
        message = json.dumps({"video_id": video_id, "data": data})
        client.publish("video_progress", message)
    except Exception as e:
        # Never let a WebSocket publish failure break a background task
        print(f"[RedisPubSub] Failed to publish progress: {e}")
