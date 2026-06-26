"""Synchronous analytics logging helpers.

These functions run DB inserts in a blocking fashion. Callers that need
non-blocking behavior (middleware, API endpoints) should dispatch them via
a background thread or task.
"""

from typing import Any

from app.db.session import SessionLocal
from app.models.analytics import PageView, UsageEvent


def log_page_view(
    user_id: str | None,
    path: str,
    session_id: str | None,
    ip_hash: str | None,
    user_agent: str | None,
) -> None:
    """Persist a page view record.

    Args:
        user_id: Authenticated user ID, or None for anonymous traffic.
        path: Request path.
        session_id: Optional client session identifier.
        ip_hash: Optional hashed client IP.
        user_agent: Optional user-agent string.
    """
    db = SessionLocal()
    try:
        db.add(
            PageView(
                user_id=user_id,
                path=path,
                session_id=session_id,
                ip_hash=ip_hash,
                user_agent=user_agent,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def log_usage_event(
    user_id: str | None,
    event_type: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist a product usage event.

    Args:
        user_id: Authenticated user ID, or None for anonymous traffic.
        event_type: Event type identifier (e.g., "upload", "transcribe").
        metadata: Optional JSON-serializable event payload.
    """
    db = SessionLocal()
    try:
        db.add(
            UsageEvent(
                user_id=user_id,
                event_type=event_type,
                metadata_=metadata,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
