"""Progress tracking API endpoints.

NOTE: These endpoints are DEPRECATED in favor of WebSocket updates.
Connect to /ws/videos/{video_id} for real-time progress updates.

These endpoints are kept for debugging purposes only.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.videos import require_video_owner
from app.core.auth import RequestIdentity, get_current_user_or_byok
from app.db.session import get_db
from app.models.video import ProcessingLog, Video
from app.schemas.video import ProcessingLogEntry, VideoProgress, VideoProgressDetail
from app.services.progress_service import get_progress_tracker

router = APIRouter(prefix="/progress", tags=["progress"])


# Global WebSocket manager reference (set from main.py)
_websocket_manager = None


def set_websocket_manager(manager: Any) -> None:
    """Set the WebSocket manager for progress updates."""
    global _websocket_manager
    _websocket_manager = manager


async def send_progress_update(video_id: str, data: dict[str, Any]) -> None:
    """Send a progress update via WebSocket.

    Args:
        video_id: The video ID to send to
        data: Dictionary of data to send
    """
    if _websocket_manager:
        await _websocket_manager.broadcast_to_video(video_id, data)


# DEPRECATED: Use WebSocket /ws/videos/{video_id} instead
@router.get("/{video_id}", response_model=VideoProgress, deprecated=True)
def get_video_progress(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> VideoProgress:
    """DEPRECATED: Get current progress for a video.

    Use WebSocket /ws/videos/{video_id} for real-time updates instead.
    This endpoint is kept for debugging only.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    # Calculate estimated time remaining
    tracker = get_progress_tracker(video_id, db)
    time_remaining = tracker.estimate_time_remaining()

    return VideoProgress(
        video_id=video.id,
        status=video.status,
        progress_percent=video.progress_percent,
        current_step=video.current_step,
        step_detail=video.step_detail,
        total_segments=video.total_segments,
        processed_segments=video.processed_segments,
        current_segment_index=video.current_segment_index,
        estimated_time_remaining=time_remaining,
        started_at=video.started_at,
        completed_at=video.completed_at,
    )


# DEPRECATED: Use WebSocket /ws/videos/{video_id} instead
@router.get("/{video_id}/detail", response_model=VideoProgressDetail, deprecated=True)
def get_video_progress_detail(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> VideoProgressDetail:
    """DEPRECATED: Get detailed progress with recent logs.

    Use WebSocket /ws/videos/{video_id} for real-time updates instead.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    # Get recent logs
    tracker = get_progress_tracker(video_id, db)
    recent_logs = tracker.get_recent_logs(limit=50)

    # Calculate estimated time remaining
    time_remaining = tracker.estimate_time_remaining()

    # Convert logs to schema
    log_entries = [
        ProcessingLogEntry(
            timestamp=log.timestamp,
            level=log.level,
            step=log.step,
            message=log.message,
            details=log.details,
        )
        for log in reversed(recent_logs)  # Most recent last
    ]

    return VideoProgressDetail(
        video_id=video.id,
        status=video.status,
        progress_percent=video.progress_percent,
        current_step=video.current_step,
        step_detail=video.step_detail,
        total_segments=video.total_segments,
        processed_segments=video.processed_segments,
        current_segment_index=video.current_segment_index,
        estimated_time_remaining=time_remaining,
        started_at=video.started_at,
        completed_at=video.completed_at,
        recent_logs=log_entries,
    )


@router.get("/{video_id}/logs")
def get_video_logs(
    video_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Get processing logs for a video."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    logs = (
        db.query(ProcessingLog)
        .filter(ProcessingLog.video_id == video_id)
        .order_by(ProcessingLog.timestamp.desc())
        .limit(limit)
        .all()
    )

    return {
        "video_id": video_id,
        "total_logs": len(logs),
        "logs": [
            {
                "timestamp": log.timestamp.isoformat(),
                "level": log.level,
                "step": log.step,
                "message": log.message,
                "details": log.details,
            }
            for log in reversed(logs)
        ],
    }
