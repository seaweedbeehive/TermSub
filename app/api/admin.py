"""Admin API router for operational dashboards."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_user
from app.core.quota import QuotaManager
from app.db.session import get_db
from app.models.analytics import PageView, UsageEvent
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"])


def _naive_utc_now() -> datetime:
    """Return the current UTC time as a naive datetime."""
    return datetime.utcnow()


@router.get("/stats")
def admin_stats(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> dict[str, Any]:
    """Return aggregate platform statistics for the admin dashboard."""
    now = _naive_utc_now()
    today_start = datetime.combine(now.date(), datetime.min.time())
    week_start = today_start - timedelta(days=6)  # last 7 days, inclusive

    total_users = db.query(func.count(User.id)).scalar() or 0

    new_users_today = (
        db.query(func.count(User.id))
        .filter(User.created_at >= today_start)
        .scalar()
        or 0
    )

    newsletter_subscribers = (
        db.query(func.count(User.id))
        .filter(User.wants_updates.is_(True))
        .scalar()
        or 0
    )

    page_views_today = (
        db.query(func.count(PageView.id))
        .filter(PageView.created_at >= today_start)
        .scalar()
        or 0
    )

    unique_visitors_today = (
        db.query(func.count(func.distinct(PageView.ip_hash)))
        .filter(PageView.created_at >= today_start, PageView.ip_hash.isnot(None))
        .scalar()
        or 0
    )

    uploads_today = (
        db.query(func.count(UsageEvent.id))
        .filter(
            UsageEvent.created_at >= today_start,
            UsageEvent.event_type == "upload",
        )
        .scalar()
        or 0
    )

    upload_counts = (
        db.query(UsageEvent.user_id, func.count(UsageEvent.id).label("upload_count"))
        .filter(
            UsageEvent.created_at >= week_start,
            UsageEvent.event_type == "upload",
            UsageEvent.user_id.isnot(None),
        )
        .group_by(UsageEvent.user_id)
        .subquery()
    )

    top_users = (
        db.query(User.email, upload_counts.c.upload_count)
        .join(upload_counts, User.id == upload_counts.c.user_id)
        .order_by(upload_counts.c.upload_count.desc())
        .limit(10)
        .all()
    )

    return {
        "total_users": total_users,
        "new_users_today": new_users_today,
        "newsletter_subscribers": newsletter_subscribers,
        "page_views_today": page_views_today,
        "unique_visitors_today": unique_visitors_today,
        "uploads_today": uploads_today,
        "top_users_this_week": [
            {"email": email, "upload_count": upload_count}
            for email, upload_count in top_users
        ],
    }


@router.get("/users")
def admin_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> list[dict[str, Any]]:
    """Return all users with quota usage for the admin dashboard."""
    quota = QuotaManager()
    users = db.query(User).order_by(User.created_at.desc()).all()

    result = []
    for user in users:
        quota_status = quota.get_quota_status(user.id)
        result.append(
            {
                "id": user.id,
                "email": user.email,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "api_key_mode": user.api_key_mode,
                "is_admin": user.is_admin,
                "is_email_verified": user.is_email_verified,
                "minutes_used": quota_status["minutes_used"],
                "minutes_remaining": quota_status["minutes_remaining"],
            }
        )
    return result


@router.post("/users/{user_id}/reset-quota")
def admin_reset_user_quota(
    user_id: str,
    _admin: User = Depends(require_admin_user),
) -> dict[str, str]:
    """Reset a standard user's minute quota to zero."""
    quota = QuotaManager()
    try:
        quota._redis.delete(quota._minutes_key(user_id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to reset quota",
        ) from exc
    return {"message": "Quota reset successfully"}


@router.post("/users/{user_id}/toggle-mode")
def admin_toggle_user_mode(
    user_id: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> dict[str, Any]:
    """Toggle a user's API key mode between standard and BYOK."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.api_key_mode = "byok" if user.api_key_mode == "standard" else "standard"
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "api_key_mode": user.api_key_mode,
        "message": f"User mode switched to {user.api_key_mode}",
    }
