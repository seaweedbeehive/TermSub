"""User profile API router."""

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import (
    RequestIdentity,
    generate_verification_token,
    get_current_user_or_byok,
    hash_password,
    verify_password,
)
from app.core.email import send_verification_email
from app.core.quota import QuotaManager
from app.core.redis_pubsub import get_sync_redis_client
from app.db.session import get_db
from app.models.analytics import PageView, UsageEvent
from app.models.job_queue import JobQueue
from app.models.user import User, UserSession
from app.models.video import Video
from app.schemas.profile import (
    DeleteAccountRequest,
    MessageResponse,
    ProfileMeResponse,
    UpdateApiKeyModeRequest,
    UpdateEmailRequest,
    UpdatePasswordRequest,
    UpdatePreferencesRequest,
    UsageHistoryItem,
    UsageHistoryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])


def _require_standard_user(identity: RequestIdentity) -> User:
    """Return the underlying User for standard JWT identities.

    Raises an HTTPException if the caller is using BYOK authentication.
    """
    if identity.is_byok or identity.user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action is only available for standard accounts.",
        )
    return identity.user


def _validate_openai_api_key(api_key: str) -> bool:
    """Make a lightweight test call to OpenAI to verify an API key."""
    try:
        response = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        return response.status_code == 200
    except Exception:
        return False


def _get_video_minutes(redis: Any, video_id: str) -> int:
    """Return the estimated/actual minutes used for a video from Redis."""
    try:
        raw = redis.get(f"quota:video_estimated_minutes:{video_id}")
        return int(round(float(raw))) if raw else 0
    except Exception:
        return 0


def _video_ids_for_byok_user(redis: Any, user_id: str) -> list[str]:
    """Return all video IDs owned by a BYOK user from Redis."""
    video_ids: list[str] = []
    try:
        for key in redis.scan_iter(match="quota:video_owner:*", count=100):
            owner = redis.get(key)
            if owner and owner.decode() == user_id:
                video_ids.append(key.decode().split(":", 2)[2])
    except Exception as exc:
        logger.warning("Failed to scan BYOK video owners: %s", exc)
    return video_ids


@router.get("/me", response_model=ProfileMeResponse)
def get_profile(
    identity: RequestIdentity = Depends(get_current_user_or_byok),
    db: Session = Depends(get_db),
) -> ProfileMeResponse | dict[str, Any]:
    """Return the current user's profile data."""
    if identity.is_byok:
        redis = get_sync_redis_client()
        video_ids = _video_ids_for_byok_user(redis, identity.user_id)
        return {
            "id": identity.user_id,
            "email": "BYOK",
            "display_name": None,
            "is_email_verified": True,
            "wants_updates": False,
            "api_key_mode": "byok",
            "total_jobs_processed": len(video_ids),
            "total_minutes_used": 0,
            "created_at": datetime.now(UTC).isoformat(),
        }

    user = identity.user
    assert user is not None

    total_jobs = db.query(Video).filter(Video.user_id == user.id).count()
    quota_status = QuotaManager().get_quota_status(user.id, is_byok=False)

    return ProfileMeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_email_verified=user.is_email_verified,
        wants_updates=user.wants_updates,
        api_key_mode=user.api_key_mode,
        total_jobs_processed=total_jobs,
        total_minutes_used=max(
            0, int(round(quota_status.get("minutes_used", 0)))
        ),
        created_at=user.created_at,
    )


@router.get("/usage", response_model=UsageHistoryResponse)
def get_usage_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
    db: Session = Depends(get_db),
) -> UsageHistoryResponse:
    """Return paginated usage history for the authenticated user."""
    redis = get_sync_redis_client()

    if identity.is_byok:
        video_ids = _video_ids_for_byok_user(redis, identity.user_id)
        query = (
            db.query(Video)
            .filter(Video.id.in_(video_ids))
            .order_by(Video.created_at.desc())
        )
    else:
        user = identity.user
        assert user is not None
        query = (
            db.query(Video)
            .filter(Video.user_id == user.id)
            .order_by(Video.created_at.desc())
        )

    total = query.count()
    videos = query.offset(skip).limit(limit).all()

    items: list[UsageHistoryItem] = []
    for video in videos:
        items.append(
            UsageHistoryItem(
                video_id=video.id,
                filename=video.filename,
                content_type=video.content_type,
                status=video.status,
                created_at=video.created_at,
                minutes_used=_get_video_minutes(redis, video.id),
            )
        )

    return UsageHistoryResponse(items=items, total=total, skip=skip, limit=limit)


@router.put("/email", response_model=MessageResponse)
def update_email(
    payload: UpdateEmailRequest,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Update the user's email address and send a verification email."""
    user = _require_standard_user(identity)

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )

    new_email = payload.new_email.strip().lower()
    existing = db.query(User).filter(User.email == new_email).first()
    if existing and existing.id != user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user.email = new_email
    user.is_email_verified = False
    verification_token = generate_verification_token()
    user.email_verification_token = verification_token
    user.email_verification_token_expires_at = datetime.utcnow() + timedelta(hours=24)
    db.commit()

    threading.Thread(
        target=send_verification_email,
        args=(user.email, verification_token),
        daemon=True,
    ).start()

    return MessageResponse(
        message="Email updated. Please check your inbox to verify the new address."
    )


@router.put("/password", response_model=MessageResponse)
def update_password(
    payload: UpdatePasswordRequest,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Change the user's password after verifying the current password."""
    user = _require_standard_user(identity)

    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect.",
        )

    user.password_hash = hash_password(payload.new_password)
    db.commit()

    return MessageResponse(message="Password changed successfully.")


@router.put("/preferences", response_model=MessageResponse)
def update_preferences(
    payload: UpdatePreferencesRequest,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Update user preferences such as newsletter opt-in and display name."""
    user = _require_standard_user(identity)

    if payload.wants_updates is not None:
        user.wants_updates = payload.wants_updates
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip() or None
    db.commit()

    return MessageResponse(message="Preferences updated successfully.")


@router.put("/api-key-mode", response_model=MessageResponse)
def update_api_key_mode(
    payload: UpdateApiKeyModeRequest,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Switch the user's API key mode between standard and BYOK."""
    user = _require_standard_user(identity)

    if payload.mode == "byok":
        api_key = payload.api_key
        assert api_key is not None
        if not _validate_openai_api_key(api_key):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The provided OpenAI API key could not be validated.",
            )

    user.api_key_mode = payload.mode
    db.commit()

    return MessageResponse(
        message=f"API key mode updated to {payload.mode}."
    )


@router.delete("/sessions", response_model=MessageResponse)
def invalidate_all_sessions(
    identity: RequestIdentity = Depends(get_current_user_or_byok),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Invalidate all sessions except the current one."""
    user = _require_standard_user(identity)

    # Invalidate tokens issued before the current token. Using the current
    # token's ``iat`` keeps the current session active while rejecting older
    # sessions.
    user.sessions_invalidated_at = identity.token_issued_at or datetime.utcnow()
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()
    db.commit()

    return MessageResponse(message="All other sessions have been logged out.")


@router.delete("/account", response_model=MessageResponse)
def delete_account(
    payload: DeleteAccountRequest,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Delete the user account and all associated data."""
    user = _require_standard_user(identity)

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Password is incorrect.",
        )

    user_id = user.id

    # Delete analytics tied to the user.
    db.query(UsageEvent).filter(UsageEvent.user_id == user_id).delete()
    db.query(PageView).filter(PageView.user_id == user_id).delete()

    # Delete sessions.
    db.query(UserSession).filter(UserSession.user_id == user_id).delete()

    # Delete videos owned by the user and their related job queue entries.
    videos = db.query(Video).filter(Video.user_id == user_id).all()
    for video in videos:
        db.query(JobQueue).filter(JobQueue.video_id == video.id).delete()
        db.delete(video)

    db.delete(user)
    db.commit()

    # Clean up Redis ownership metadata for this user's videos.
    try:
        redis = get_sync_redis_client()
        for key in redis.scan_iter(match="quota:video_owner:*", count=100):
            owner = redis.get(key)
            if owner and owner.decode() == user_id:
                video_id = key.decode().split(":", 2)[2]
                redis.delete(f"quota:video_estimated_minutes:{video_id}")
                redis.delete(f"quota:video_byok:{video_id}")
                redis.delete(key)
        redis.delete(f"quota:{user_id}:minutes")
    except Exception as exc:
        logger.warning(
            "Failed to clean up Redis quota metadata for %s: %s", user_id, exc
        )

    return MessageResponse(
        message="Your account and all associated data have been deleted."
    )
