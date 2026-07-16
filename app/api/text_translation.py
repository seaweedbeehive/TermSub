"""Text-only translation API.

Endpoints in this module are the only endpoints that should handle
`content_type == "text"` records once the new pipeline is live.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.auth import RequestIdentity, get_current_user_or_byok
from app.core.quota import QuotaManager
from app.core.task_tracker import record_task
from app.db.session import get_db
from app.models.video import ContentType, Segment, Term, Video, VideoStatus
from app.services.text_translation_service import (
    export_text_translation,
    extract_terms_for_text,
    translate_text,
)
from app.worker.text_tasks import extract_text_terms_task, translate_text_task

router = APIRouter(prefix="/api/text", tags=["text"])


class _SegmentUpdate(BaseModel):
    translated_text: str


class _TermUpdate(BaseModel):
    standardized_term: str | None = None
    translated_term: str | None = None


def _require_text_owner(video: Video, identity: RequestIdentity) -> None:
    """Raise 403 if the user does not own the text record."""
    if identity.is_byok:
        owner_id, _, _ = QuotaManager().get_video_owner(video.id)
        if owner_id is not None and owner_id == identity.user_id:
            return
    elif video.user_id is not None and video.user_id == identity.user_id:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized for this text record.",
    )


def _load_text_record(video_id: str, db: Session) -> Video:
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Text record not found")
    if video.content_type != ContentType.TEXT.value:
        raise HTTPException(
            status_code=400,
            detail="This endpoint is for text records only.",
        )
    return video


@router.post("/{video_id}/extract-terms")
def extract_text_terms_endpoint(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Start terminology extraction for a text document."""
    video = _load_text_record(video_id, db)
    _require_text_owner(video, identity)

    allowed_statuses = {
        VideoStatus.TRANSCRIBED.value,
        VideoStatus.CONTEXT_READY.value,
        VideoStatus.TERMS_READY.value,
        VideoStatus.COMPLETED.value,
    }
    if video.status not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot extract terms from status '{video.status}'.",
        )

    # If terms are already ready, skip re-extraction unless language changed.
    if video.status == VideoStatus.TERMS_READY.value:
        return {
            "video_id": video_id,
            "status": video.status,
            "message": "Terms already extracted",
        }

    task = extract_text_terms_task.delay(
        video_id,
        api_key=identity.api_key,
        user_id=identity.user_id,
        is_byok=identity.is_byok,
    )
    record_task(video_id, "text_analyze", task.id)

    return {
        "video_id": video_id,
        "job_id": task.id,
        "status": "queued",
        "message": "Text terminology extraction started",
    }


@router.post("/{video_id}/translate")
async def translate_text_endpoint(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Start translation for a text document."""
    video = _load_text_record(video_id, db)
    _require_text_owner(video, identity)

    if video.status not in {
        VideoStatus.TERMS_READY.value,
        VideoStatus.COMPLETED.value,
    }:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot translate from status '{video.status}'. Extract terms first.",
        )

    if video.status == VideoStatus.COMPLETED.value:
        # Re-translation after term edits: clear stale results so the new
        # glossary is applied and the worker recomputes every segment.
        #
        # Use an atomic UPDATE...WHERE instead of read-then-write so two
        # concurrent requests can't both observe status == COMPLETED and both
        # queue a task: only one UPDATE can win the row, the other sees
        # rowcount == 0 and backs off instead of double-queueing.
        claim_result = db.execute(
            update(Video)
            .where(
                Video.id == video_id,
                Video.status == VideoStatus.COMPLETED.value,
            )
            .values(
                status=VideoStatus.TERMS_READY.value,
                progress_percent=0,
                processed_segments=0,
                current_segment_index=0,
                completed_at=None,
                error_message=None,
            )
        )
        db.commit()
        if claim_result.rowcount == 0:
            # Another request already claimed the re-translation.
            return {
                "video_id": video_id,
                "status": VideoStatus.TRANSLATING.value,
                "message": "Translation already in progress",
            }
        db.query(Segment).filter(Segment.video_id == video_id).update(
            {Segment.translated_text: None},
            synchronize_session=False,
        )
        db.commit()

    task = translate_text_task.delay(
        video_id,
        api_key=identity.api_key,
        user_id=identity.user_id,
        is_byok=identity.is_byok,
    )
    record_task(video_id, "text_translate", task.id)

    return {
        "video_id": video_id,
        "job_id": task.id,
        "status": "queued",
        "message": "Text translation started",
    }


@router.get("/{video_id}/segments")
def get_text_segments(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Return all text segments with original and translated text."""
    video = _load_text_record(video_id, db)
    _require_text_owner(video, identity)

    segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.sequence_number)
        .all()
    )

    return {
        "video_id": video_id,
        "status": video.status,
        "content_type": video.content_type,
        "source_language": video.source_language,
        "target_language": video.target_language,
        "segments": [
            {
                "id": seg.id,
                "sequence_number": seg.sequence_number,
                "original_text": seg.original_text,
                "translated_text": seg.translated_text,
            }
            for seg in segments
        ],
    }


@router.get("/{video_id}/terms")
def get_text_terms(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Return extracted terms for review."""
    video = _load_text_record(video_id, db)
    _require_text_owner(video, identity)

    terms = (
        db.query(Term)
        .filter(Term.video_id == video_id)
        .order_by(Term.original_term)
        .all()
    )

    return {
        "video_id": video_id,
        "terms": [
            {
                "id": term.id,
                "original_term": term.original_term,
                "translated_term": term.translated_term,
                "standardized_term": term.standardized_term,
                "category": term.category,
                "source": term.source,
            }
            for term in terms
        ],
    }


@router.patch("/{video_id}/segments/{segment_id}")
def update_text_segment(
    video_id: str,
    segment_id: str,
    body: _SegmentUpdate,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Update translated text for a single segment."""
    video = _load_text_record(video_id, db)
    _require_text_owner(video, identity)

    segment = (
        db.query(Segment)
        .filter(Segment.id == segment_id, Segment.video_id == video_id)
        .first()
    )
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    segment.translated_text = body.translated_text
    db.commit()

    return {
        "id": segment.id,
        "sequence_number": segment.sequence_number,
        "translated_text": segment.translated_text,
    }


@router.patch("/terms/{term_id}")
def update_text_term(
    term_id: str,
    body: _TermUpdate,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Update an extracted term."""
    term = db.query(Term).filter(Term.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    video = db.query(Video).filter(Video.id == term.video_id).first()
    if not video or video.content_type != ContentType.TEXT.value:
        raise HTTPException(
            status_code=400,
            detail="This endpoint is for text terms only.",
        )
    _require_text_owner(video, identity)

    if body.standardized_term is not None:
        term.standardized_term = body.standardized_term
        term.is_standardized = True
    if body.translated_term is not None:
        term.translated_term = body.translated_term

    db.commit()

    return {
        "id": term.id,
        "original_term": term.original_term,
        "standardized_term": term.standardized_term,
        "translated_term": term.translated_term,
    }


@router.post("/{video_id}/export")
def export_text_endpoint(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Any:
    """Download the translated text as a .txt file."""
    from fastapi.responses import Response

    video = _load_text_record(video_id, db)
    _require_text_owner(video, identity)

    try:
        file_content = export_text_translation(video_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    download_name = video.filename or "translation.txt"
    if not download_name.lower().endswith(".txt"):
        download_name += "_translation.txt"

    headers = {
        "Content-Disposition": f'attachment; filename="{download_name}"',
        "Content-Type": "text/plain; charset=utf-8",
    }
    return Response(content=file_content.encode("utf-8"), headers=headers)
