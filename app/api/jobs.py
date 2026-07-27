"""Job history API router."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import RequestIdentity, get_current_user_or_byok
from app.core.quota import QuotaManager
from app.db.session import get_db
from app.models.video import Video
from app.schemas.video import VideoOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobListItem(BaseModel):
    """Lightweight job summary for the job history list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    source_language: str | None
    target_language: str
    video_filename: str
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    """Paginated response for the job history endpoint."""

    items: list[JobListItem]
    total: int
    skip: int
    limit: int


@router.get("/", response_model=JobListResponse)
def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> JobListResponse:
    """Return a paginated list of jobs for the authenticated user.

    Standard users are matched by ``Video.user_id``. BYOK users are matched by
    the owner hash stored in Redis when the video was uploaded.
    """
    user_id = identity.user_id
    is_byok = identity.is_byok

    if is_byok:
        # BYOK ownership is tracked in Redis via QuotaManager. We don't have a
        # direct DB column for BYOK user_id, so we currently return an empty list.
        # TODO: store BYOK owner hash on the Video row to support history.
        return JobListResponse(items=[], total=0, skip=skip, limit=limit)

    query = db.query(Video).filter(Video.user_id == user_id)
    total = query.count()
    videos = query.order_by(Video.created_at.desc()).offset(skip).limit(limit).all()

    items = [
        JobListItem(
            id=video.id,
            status=video.status,
            source_language=video.source_language,
            target_language=video.target_language,
            video_filename=video.filename,
            created_at=video.created_at,
            updated_at=video.updated_at,
        )
        for video in videos
    ]

    return JobListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/{job_id}", response_model=VideoOut)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Video:
    """Return full job data including segments (transcription/translation results)."""
    video = db.query(Video).filter(Video.id == job_id).first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    if identity.is_byok:
        owner_id, _, _ = QuotaManager().get_video_owner(video.id)
        if owner_id is None or owner_id != identity.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized for this job.",
            )
    elif video.user_id is None or video.user_id != identity.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this job.",
        )

    return video
