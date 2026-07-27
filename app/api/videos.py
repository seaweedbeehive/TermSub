import contextlib
import json
import threading
import traceback
import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, selectinload

from app.core.analytics import log_usage_event
from app.core.audio import get_audio_duration
from app.core.auth import RequestIdentity, get_current_user_or_byok
from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.quota import QuotaManager
from app.core.task_tracker import get_latest_task_id, record_task
from app.db.session import get_db
from app.db.session_utils import get_db_session
from app.models.video import ContentType, Segment, Term, Video, VideoStatus
from app.schemas.segment import SegmentUpdate
from app.schemas.video import VideoConfigUpdate, VideoOut
from app.services.gemini_service import translate_video_sliding_window
from app.services.text_parser import parse_text_file
from app.services.upload_service import generate_unique_filename, save_uploaded_file
from app.utils.timecode import parse_timestamp
from app.worker.tasks import (
    analyze_video_task,
    transcribe_video_task,
    translate_video_task,
)

# Import WebSocket manager (will be initialized in main.py)
_websocket_manager = None


def set_websocket_manager(manager: Any) -> None:
    """Set the WebSocket manager for progress updates."""
    global _websocket_manager
    _websocket_manager = manager


def _safe_unlink(path: Path | None) -> None:
    """Remove a file path if it exists, ignoring any errors."""
    if path:
        with contextlib.suppress(Exception):
            path.unlink(missing_ok=True)


def _segment_to_dict(s: Segment) -> dict[str, Any]:
    """Serialize a Segment for the segment-list endpoints (add/split/delete/restore/replace)."""
    return {
        "id": s.id,
        "sequence_number": s.sequence_number,
        "start_time": s.start_time,
        "end_time": s.end_time,
        "original_text": s.original_text,
        "translated_text": s.translated_text,
        "avg_logprob": s.avg_logprob,
        "no_speech_prob": s.no_speech_prob,
    }


async def _websocket_progress_callback(
    video_id: str, status: str, data: dict[str, Any]
) -> None:
    """Callback function to send progress updates via WebSocket."""
    if _websocket_manager:
        await _websocket_manager.broadcast_to_video(video_id, data)


router = APIRouter(prefix="/videos", tags=["videos"])


def _reject_text_record(video: Video) -> None:
    """Raise 400 if the record is a text file (text pipeline has its own API)."""
    if video.content_type == ContentType.TEXT.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /api/text endpoints for text files.",
        )

def require_video_owner(video: Video, identity: RequestIdentity) -> None:
    """Raise 403 if the current user does not own the video.

    Standard users are checked against the ``Video.user_id`` column. BYOK users
    are checked against the owner hash stored in Redis when the video was
    uploaded, so a BYOK user cannot access another user's video by UUID.
    """
    if identity.is_byok:
        owner_id, _, _ = QuotaManager().get_video_owner(video.id)
        if owner_id is not None and owner_id == identity.user_id:
            return
    elif video.user_id is not None and video.user_id == identity.user_id:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized for this video.",
    )


@router.post("/upload", response_model=VideoOut)
async def upload_video(
    file: UploadFile = File(...),
    target_language: str | None = Form(None),
    source_language: str = Form("auto"),
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Any:
    """Upload a video or text file.

    Standard users authenticate with JWT and are limited to 30 minutes of audio
    during the trial. BYOK users provide an X-API-Key header and are subject
    only to abuse limits.
    """
    user_id = identity.user_id
    is_byok = identity.is_byok

    # Server-side validation: target language is required
    if not target_language or not target_language.strip():
        raise HTTPException(
            status_code=422,
            detail="Target language is required. Please select a target language.",
        )

    quota = QuotaManager()

    try:
        # Determine file size for abuse-limit checking
        await file.seek(0, 2)
        file_size_bytes = await file.tell()
        await file.seek(0)
        file_size_mb = file_size_bytes / (1024 * 1024)
    except Exception:
        file_size_mb = 0.0

    temp_file_path: Path | None = None
    saved_file_path: Path | None = None
    estimated_minutes = 0.0
    minutes_reserved = False
    video_committed = False
    try:
        print(
            f"[API Upload] Starting: {file.filename}, "
            f"target={target_language}, source={source_language}, "
            f"user={user_id[:8]}, byok={is_byok}"
        )

        # Step 1: Save the upload to a temporary file for inspection and quota
        # estimation. The final file is only written after quota passes.
        safe_filename, content_type, temp_file_path = await save_uploaded_file(
            file, use_temp=True
        )

        # Convert "auto" to None for database (Whisper will auto-detect)
        db_source_language = None if source_language == "auto" else source_language
        # For text files, auto-detect doesn't make sense, so default to "en" if auto
        if content_type == ContentType.TEXT.value and db_source_language is None:
            db_source_language = "en"

        # Step 2: Estimate audio duration for video files (required for quota).
        duration_estimation_failed = False
        if content_type == ContentType.VIDEO.value:
            try:
                duration_seconds = get_audio_duration(str(temp_file_path))
                estimated_minutes = duration_seconds / 60.0
            except Exception as exc:
                print(f"[API Upload] Could not estimate audio duration: {exc}")
                duration_estimation_failed = True

        if content_type == ContentType.VIDEO.value and (
            duration_estimation_failed or estimated_minutes <= 0.0
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not determine audio duration. Please try a different file."
                ),
            )

        # Step 3: Build the Video row in memory. Do NOT add it to the session
        # until quota has passed.
        video = Video(
            filename=safe_filename,
            file_path=str(temp_file_path),
            content_type=content_type,
            status=VideoStatus.UPLOADED.value,
            target_language=target_language,
            source_language=db_source_language,
            user_id=None if is_byok else user_id,
        )

        # Step 4: Enforce quota. BYOK users use abuse limits; standard users use
        # an atomic minute reservation so concurrent uploads cannot exceed the
        # lifetime cap.
        if is_byok:
            quota_check = quota.check_upload_allowed(
                user_id, file_size_mb, estimated_minutes, is_byok=True
            )
            if not quota_check["allowed"]:
                raise HTTPException(
                    status_code=429,
                    detail=quota_check["reason"],
                )
        else:
            if estimated_minutes > 0:
                if not quota.reserve_minutes(user_id, estimated_minutes):
                    remaining = quota.get_quota_status(user_id)["minutes_remaining"]
                    raise HTTPException(
                        status_code=429,
                        detail=(
                            f"Upload would exceed the trial audio limit "
                            f"({quota.trial_minutes} minutes). "
                            f"Remaining: {remaining:.1f} minutes."
                        ),
                    )
                minutes_reserved = True

        # Step 5: Quota passed. Move the temp file to its final location, then
        # persist the Video row.
        upload_dir = Path(settings.UPLOAD_DIR)
        unique_filename = generate_unique_filename(safe_filename)
        saved_file_path = upload_dir / unique_filename
        temp_file_path.rename(saved_file_path)
        video.file_path = str(saved_file_path)

        db.add(video)
        db.commit()
        db.refresh(video)
        video_committed = True

        quota.set_video_owner(
            video.id, user_id, is_byok=is_byok, estimated_minutes=estimated_minutes
        )

        threading.Thread(
            target=log_usage_event,
            args=(
                None if is_byok else user_id,
                "upload",
                {
                    "video_id": video.id,
                    "filename": video.filename,
                    "file_size_mb": round(file_size_mb, 4),
                    "estimated_minutes": round(estimated_minutes, 2),
                    "target_language": target_language,
                    "source_language": source_language,
                    "byok": is_byok,
                },
            ),
            daemon=True,
        ).start()
        print(f"[API Upload] Success: video_id={video.id}")
        return video
    except HTTPException:
        if minutes_reserved:
            quota.release_minutes(user_id, estimated_minutes)
        _safe_unlink(temp_file_path)
        if saved_file_path and not video_committed:
            _safe_unlink(saved_file_path)
        raise
    except ValueError as e:
        if minutes_reserved:
            quota.release_minutes(user_id, estimated_minutes)
        _safe_unlink(temp_file_path)
        print(f"[API Upload] Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        if minutes_reserved:
            quota.release_minutes(user_id, estimated_minutes)
        _safe_unlink(temp_file_path)
        if saved_file_path and not video_committed:
            _safe_unlink(saved_file_path)
        db.rollback()
        print(f"[API Upload] Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}") from e


@router.get("/{video_id}", response_model=VideoOut)
def get_video(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Any:
    video = (
        db.query(Video)
        .options(selectinload(Video.segments))
        .filter(Video.id == video_id)
        .first()
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)
    return video


@router.patch("/{video_id}/config", response_model=VideoOut)
def update_video_config(
    video_id: str,
    body: VideoConfigUpdate,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Any:
    """Update configurable fields for a video job.

    Allows the user to change source/target language or toggle terminology
    extraction while the job is in a safe state. Changing the target language
    invalidates any existing translations so they can be re-generated.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    allowed_statuses = {
        VideoStatus.UPLOADED.value,
        VideoStatus.TRANSCRIBED.value,
        VideoStatus.TERMS_READY.value,
        VideoStatus.TRANSLATING.value,
        VideoStatus.COMPLETED.value,
        VideoStatus.ERROR.value,
    }
    if video.status not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot update config while video status is {video.status}. "
                f"Allowed statuses: {', '.join(sorted(allowed_statuses))}."
            ),
        )

    original_target_language = video.target_language

    # Source language changes are only meaningful before transcription. Once the
    # job has progressed past uploaded, changing it would be a silent no-op
    # because transcription is idempotent and won't re-run.
    if body.source_language is not None:
        if (
            video.status != VideoStatus.UPLOADED.value
            and body.source_language != video.source_language
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    'Cannot change source language after transcription has started. '
                    'Please start a new project for a different source language.'
                ),
            )
        video.source_language = body.source_language
    if body.target_language is not None:
        video.target_language = body.target_language
    if body.skip_glossary is not None:
        video.skip_glossary = body.skip_glossary

    target_language_changed = body.target_language is not None and (
        body.target_language != original_target_language
    )

    # Changing the target language or toggling glossary extraction after terms were
    # ready (or translation completed) invalidates prior results so the pipeline
    # can re-run cleanly from transcription.
    if (
        target_language_changed
        or (
            body.skip_glossary is False
            and video.status in {
                VideoStatus.TRANSCRIBED.value,
                VideoStatus.COMPLETED.value,
            }
        )
    ):
        # Changing the target language invalidates both existing translations and
        # extracted terms (terms include target-language translations). Reset the
        # job to transcribed so terminology analysis and translation re-run.
        db.query(Segment).filter(Segment.video_id == video_id).update(
            {Segment.translated_text: None},
            synchronize_session=False,
        )
        db.query(Term).filter(Term.video_id == video_id).delete(
            synchronize_session=False
        )
        video.status = VideoStatus.TRANSCRIBED.value
        # Reset stale progress metadata so the UI doesn't show a completed/errored state.
        video.progress_percent = 0
        video.processed_segments = 0
        video.current_segment_index = 0
        video.completed_at = None
        video.error_message = None
        if body.skip_glossary is not None:
            video.skip_glossary = body.skip_glossary

    if (
        body.skip_glossary is True
        and video.status == VideoStatus.TERMS_READY.value
    ):
        video.status = VideoStatus.TRANSCRIBED.value

    db.commit()
    db.refresh(video)
    return video


@router.post("/{video_id}/transcribe")
def transcribe_video_endpoint(
    video_id: str,
    method: str = Query("whisper", description="Transcription method: 'whisper' only"),
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Queue transcription job for video using OpenAI Whisper, or parse text files.

    Standard users authenticate via JWT. BYOK users may provide an X-API-Key
    header to use their own OpenAI key.
    """
    print(f"[API Transcribe] Request for video {video_id}")

    user_id = identity.user_id
    is_byok = identity.is_byok
    api_key = identity.api_key
    if not is_byok:
        api_key = settings.OPENAI_API_KEY
        if not api_key or not api_key.strip():
            raise HTTPException(
                status_code=400,
                detail="OpenAI API Key is not configured on the server.",
            )

    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            print(f"[API Transcribe] Video not found: {video_id}")
            raise HTTPException(status_code=404, detail="Video not found")
        require_video_owner(video, identity)

        print(f"[API Transcribe] Video: {video.filename}, type: {video.content_type}")

        # Idempotency: do not re-run transcription if it is already finished.
        # Text parsing sets status to "translating", so include that state to
        # keep text-file transcribe calls idempotent as well.
        completed_statuses = {
            VideoStatus.TRANSCRIBED.value,
            VideoStatus.TERMS_READY.value,
            VideoStatus.COMPLETED.value,
        }
        text_parsed_statuses = {
            VideoStatus.TRANSLATING.value,
            VideoStatus.TERMS_READY.value,
            VideoStatus.COMPLETED.value,
        }
        is_already_done = video.status in completed_statuses or (
            video.content_type == ContentType.TEXT.value
            and video.status in text_parsed_statuses
        )
        if is_already_done:
            print(
                f"[API Transcribe] Already complete: {video_id} status={video.status}"
            )
            segment_count = (
                db.query(Segment).filter(Segment.video_id == video_id).count()
            )
            return {
                "status": "already_complete",
                "video_id": video_id,
                "message": "Transcription already complete",
                "total_segments": segment_count,
            }

        # Handle text files - parse immediately
        if video.content_type == ContentType.TEXT.value:
            try:
                result = parse_text_file(video_id)
                threading.Thread(
                    target=log_usage_event,
                    args=(
                        None if is_byok else user_id,
                        "transcribe",
                        {
                            "video_id": video_id,
                            "method": method,
                            "content_type": video.content_type,
                            "source_language": video.source_language,
                            "byok": is_byok,
                        },
                    ),
                    daemon=True,
                ).start()
                return {
                    "status": "transcribed",
                    "video_id": video_id,
                    "message": "Text file parsed",
                    "total_segments": result.get("segment_count", 0),
                }
            except Exception as e:
                print(f"[API Transcribe] Text parsing error: {e}")
                traceback.print_exc()
                raise HTTPException(
                    status_code=500,
                    detail=f"Parsing failed: {str(e)}",
                ) from e

        # Queue transcription job via Celery
        try:
            result = transcribe_video_task.delay(
                video_id,
                api_key=api_key,
                user_id=user_id,
                is_byok=is_byok,
            )
            record_task(video_id, "transcribe", result.id)
            threading.Thread(
                target=log_usage_event,
                args=(
                    None if is_byok else user_id,
                    "transcribe",
                    {
                        "video_id": video_id,
                        "method": method,
                        "content_type": video.content_type,
                        "source_language": video.source_language,
                        "byok": is_byok,
                    },
                ),
                daemon=True,
            ).start()
            print(f"[API Transcribe] Celery task {result.id} queued")

            return {
                "status": "queued",
                "job_id": result.id,
                "video_id": video_id,
                "job_type": "transcribe",
                "message": "Transcription queued",
            }
        except Exception as e:
            print(f"[API Transcribe] Queue error: {e}")
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Queue failed: {str(e)}",
            ) from e

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API Transcribe] Unexpected error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}") from e


@router.post("/{video_id}/analyze")
def analyze_video_endpoint(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Queue analysis job (Director + Glossary Agents)."""
    print(f"[API Analyze] Request for video {video_id}")

    api_key = identity.api_key
    if not api_key:
        api_key = settings.OPENAI_API_KEY
    if not api_key or not api_key.strip():
        raise HTTPException(
            status_code=400,
            detail="OpenAI API Key is not configured on the server.",
        )

    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        require_video_owner(video, identity)
        _reject_text_record(video)

        result = analyze_video_task.delay(video_id, api_key=api_key)
        record_task(video_id, "analyze", result.id)
        print(f"[API Analyze] Celery task {result.id} queued")

        return {
            "status": "queued",
            "job_id": result.id,
            "video_id": video_id,
            "job_type": "analyze",
            "message": "Analysis queued",
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API Analyze] Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{video_id}/translate-direct")
def translate_direct_endpoint(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Skip terminology analysis and queue translation directly."""
    print(f"[API TranslateDirect] Request for video {video_id}")

    api_key = identity.api_key
    if not api_key:
        api_key = settings.OPENAI_API_KEY
    if not api_key or not api_key.strip():
        raise HTTPException(
            status_code=400,
            detail="OpenAI API Key is not configured on the server.",
        )

    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        require_video_owner(video, identity)
        _reject_text_record(video)

        # Set skip_glossary flag
        video.skip_glossary = True
        db.commit()

        result = translate_video_task.delay(video_id, api_key=api_key)
        record_task(video_id, "translate", result.id)
        threading.Thread(
            target=log_usage_event,
            args=(
                None if identity.is_byok else identity.user_id,
                "translate",
                {
                    "video_id": video_id,
                    "target_language": video.target_language,
                    "source_language": video.source_language,
                    "skip_glossary": True,
                },
            ),
            daemon=True,
        ).start()
        print(f"[API TranslateDirect] Celery task {result.id} queued")

        return {
            "status": "queued",
            "job_id": result.id,
            "video_id": video_id,
            "job_type": "translate",
            "message": "Translation queued (terminology skipped)",
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API TranslateDirect] Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{video_id}/translate")
def translate_video_endpoint(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Queue translation job."""
    print(f"[API Translate] Request for video {video_id}")

    api_key = identity.api_key
    if not api_key:
        api_key = settings.OPENAI_API_KEY
    if not api_key or not api_key.strip():
        raise HTTPException(
            status_code=400,
            detail="OpenAI API Key is not configured on the server.",
        )

    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        require_video_owner(video, identity)
        _reject_text_record(video)

        # Check prerequisites - be lenient
        valid_statuses = [
            VideoStatus.TERMS_READY.value,
            VideoStatus.TRANSLATING.value,
            VideoStatus.QUEUED.value,
            VideoStatus.TRANSCRIBING.value,
            VideoStatus.UPLOADED.value,
            VideoStatus.TRANSCRIBED.value,
            VideoStatus.COMPLETED.value,
        ]

        if video.status not in valid_statuses:
            print(f"[API Translate] Invalid status: {video.status}")
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Video status is {video.status}. Need terms_ready or transcribed."
                ),
            )

        # A translation is already running for this video; don't queue a second
        # concurrent task that would race the first one over the same segments.
        if video.status == VideoStatus.TRANSLATING.value:
            return {
                "video_id": video_id,
                "status": video.status,
                "message": "Translation already in progress",
            }

        # Re-translation from completed requires clearing previous results so
        # the new/edited glossary is applied and the worker recomputes every
        # segment instead of treating the job as already finished.
        #
        # Use an atomic UPDATE...WHERE instead of read-then-write so two
        # concurrent requests can't both observe status == COMPLETED and both
        # queue a task: only one UPDATE can win the row, the other sees
        # rowcount == 0 and backs off instead of double-queueing.
        if video.status == VideoStatus.COMPLETED.value:
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

        result = translate_video_task.delay(video_id, api_key=api_key)
        record_task(video_id, "translate", result.id)
        threading.Thread(
            target=log_usage_event,
            args=(
                None if identity.is_byok else identity.user_id,
                "translate",
                {
                    "video_id": video_id,
                    "target_language": video.target_language,
                    "source_language": video.source_language,
                    "skip_glossary": False,
                },
            ),
            daemon=True,
        ).start()
        print(f"[API Translate] Celery task {result.id} queued")

        return {
            "status": "queued",
            "job_id": result.id,
            "video_id": video_id,
            "job_type": "translate",
            "message": "Translation queued",
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API Translate] Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{video_id}/style-guide")
def get_style_guide_endpoint(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Get the generated style guide for a video."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    if not video.style_guide:
        raise HTTPException(
            status_code=400, detail="No style guide found. Run analyze first."
        )

    try:
        style_guide = json.loads(video.style_guide)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail="Invalid style guide format") from e

    return {"video_id": video_id, "style_guide": style_guide, "status": video.status}


@router.get("/{video_id}/job-status")
def get_video_job_status(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Get the status of the latest background job for a video.

    Reads the live task state from Celery instead of querying SQLite.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    task_id = get_latest_task_id(video_id)
    if not task_id:
        return {
            "video_id": video_id,
            "video_status": video.status,
            "task_id": None,
            "task_state": None,
            "task_info": None,
        }

    result = celery_app.AsyncResult(task_id)

    return {
        "video_id": video_id,
        "video_status": video.status,
        "task_id": task_id,
        "task_state": result.state,
        "task_info": result.info if result.info else None,
    }


@router.delete("/{video_id}")
def delete_video(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, str]:
    """Delete a video and all associated data."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    db.delete(video)
    db.commit()
    return {"message": "Video deleted"}


@router.post("/{video_id}/translate-legacy", response_model=VideoOut)
def translate_video_legacy_endpoint(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Any:
    """LEGACY: Direct translation without multi-agent pipeline."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    api_key = identity.api_key
    if not api_key:
        api_key = settings.OPENAI_API_KEY
    if not api_key or not api_key.strip():
        raise HTTPException(
            status_code=400,
            detail="OpenAI API Key is not configured on the server.",
        )

    from app.core.openai_key_context import byok_api_key

    ctx_token = byok_api_key.set(api_key)
    try:
        video = translate_video_sliding_window(video_id, db)
        return video
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        byok_api_key.reset(ctx_token)


@router.patch("/{video_id}/segments/{segment_id}")
def update_segment(
    video_id: str,
    segment_id: str,
    body: SegmentUpdate,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, str]:
    """Update translated text and/or timecodes for a single subtitle segment.

    The database session is managed by ``get_db_session`` so the update is
    committed on success and rolled back on any error, preventing connection
    and transaction leaks.
    """
    with get_db_session() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        require_video_owner(video, identity)

        segment = (
            db.query(Segment)
            .filter(Segment.id == segment_id, Segment.video_id == video_id)
            .first()
        )

        if not segment:
            raise HTTPException(status_code=404, detail="Segment not found")

        new_start: float | None = None
        new_end: float | None = None

        if body.start_time is not None:
            try:
                new_start = parse_timestamp(body.start_time)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid start_time: {exc}",
                ) from exc

        if body.end_time is not None:
            try:
                new_end = parse_timestamp(body.end_time)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid end_time: {exc}",
                ) from exc

        # Ensure chronological order when either boundary is supplied.
        effective_start = new_start if new_start is not None else segment.start_time
        effective_end = new_end if new_end is not None else segment.end_time
        if effective_start >= effective_end:
            raise HTTPException(
                status_code=422,
                detail="start_time must be strictly before end_time",
            )

        if body.translated_text is not None:
            segment.translated_text = body.translated_text
        if body.original_text is not None:
            segment.original_text = body.original_text
        if new_start is not None:
            segment.start_time = new_start
        if new_end is not None:
            segment.end_time = new_end

        # Do NOT refresh here: get_db_session commits on exit, and refresh
        # before commit would reload the old DB values and undo our edits.

    return {"status": "success"}


@router.post("/{video_id}/replace")
def batch_replace_segments(
    video_id: str,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Batch replace text across all translated segments for a video."""
    find_text = body.get("find_text", "")
    replace_text = body.get("replace_text", "")

    if not find_text or not isinstance(find_text, str):
        raise HTTPException(
            status_code=400, detail="find_text is required and must be a string"
        )

    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)
    _reject_text_record(video)

    # Execute SQLite batch REPLACE on translated_text
    result = db.execute(
        text("""
            UPDATE segments
            SET translated_text = REPLACE(translated_text, :find, :replace)
            WHERE video_id = :video_id
        """),
        {"find": find_text, "replace": replace_text or "", "video_id": video_id},
    )
    db.commit()

    rowcount = result.rowcount if isinstance(result, CursorResult) else 0
    if rowcount == 0:
        raise HTTPException(
            status_code=404, detail="No matching segments found for replacement"
        )

    # Re-query updated segments ordered by sequence_number
    updated_segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.sequence_number)
        .all()
    )

    return {
        "status": "success",
        "segments": [_segment_to_dict(s) for s in updated_segments],
    }


@router.post("/{video_id}/segments/add")
def add_segment(
    video_id: str,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Add a new segment at a specific position, shifting subsequent segments up."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    target_sequence = body.get("target_sequence")
    if target_sequence is None or not isinstance(target_sequence, int):
        raise HTTPException(
            status_code=400, detail="target_sequence is required and must be an integer"
        )

    # Shift all segments at or after target_sequence up by 1
    db.execute(
        text("""
            UPDATE segments
            SET sequence_number = sequence_number + 1
            WHERE video_id = :video_id AND sequence_number >= :target_sequence
        """),
        {"video_id": video_id, "target_sequence": target_sequence},
    )
    db.commit()

    # Insert the new segment
    new_segment = Segment(
        video_id=video_id,
        sequence_number=target_sequence,
        start_time=body.get("start_time", 0.0),
        end_time=body.get("end_time", 2.0),
        original_text=body.get("text", ""),
        translated_text=body.get("text", ""),
    )
    db.add(new_segment)
    db.commit()
    db.refresh(new_segment)

    # Return updated segment list
    updated_segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.sequence_number)
        .all()
    )

    return {
        "status": "success",
        "new_segment_id": new_segment.id,
        "segments": [_segment_to_dict(s) for s in updated_segments],
    }


@router.delete("/{video_id}/segments/{segment_id}")
def delete_segment(
    video_id: str,
    segment_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Delete a segment and shift subsequent sequence numbers down."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    segment = (
        db.query(Segment)
        .filter(Segment.id == segment_id, Segment.video_id == video_id)
        .first()
    )

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    deleted_sequence = segment.sequence_number

    # Delete the segment
    db.delete(segment)
    db.commit()

    # Shift all subsequent segments down by 1
    db.execute(
        text("""
            UPDATE segments
            SET sequence_number = sequence_number - 1
            WHERE video_id = :video_id AND sequence_number > :deleted_sequence
        """),
        {"video_id": video_id, "deleted_sequence": deleted_sequence},
    )
    db.commit()

    # Return updated segment list
    updated_segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.sequence_number)
        .all()
    )

    return {
        "status": "success",
        "segments": [_segment_to_dict(s) for s in updated_segments],
    }


@router.post("/{video_id}/segments/{segment_id}/split")
def split_segment(
    video_id: str,
    segment_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Split a segment into two at the timecode midpoint and nearest text boundary."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    segment = (
        db.query(Segment)
        .filter(Segment.id == segment_id, Segment.video_id == video_id)
        .first()
    )

    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")

    def _split_at_nearest_space(text: str) -> tuple[str, str]:
        """Split text into two halves at the space nearest to the middle."""
        if not text or len(text) <= 1:
            return text or "", ""
        mid_idx = len(text) // 2
        left_space = text.rfind(" ", 0, mid_idx)
        right_space = text.find(" ", mid_idx)

        if left_space != -1 and right_space != -1:
            split_idx = (
                left_space
                if (mid_idx - left_space) <= (right_space - mid_idx)
                else right_space
            )
        elif left_space != -1:
            split_idx = left_space
        elif right_space != -1:
            split_idx = right_space
        else:
            split_idx = mid_idx

        return text[:split_idx].strip(), text[split_idx:].strip()

    mid_time = (segment.start_time + segment.end_time) / 2.0

    # Split both fields independently so translations are never overwritten
    # by source-language text.
    orig_first, orig_second = _split_at_nearest_space(segment.original_text or "")
    trans_first, trans_second = _split_at_nearest_space(segment.translated_text or "")

    # Shift subsequent segments up by 1
    db.execute(
        text("""
            UPDATE segments
            SET sequence_number = sequence_number + 1
            WHERE video_id = :video_id AND sequence_number > :current_sequence
        """),
        {"video_id": video_id, "current_sequence": segment.sequence_number},
    )
    db.commit()

    # Capture original end_time before mutating
    original_end_time = segment.end_time

    # Update original segment with first halves
    segment.original_text = orig_first
    # If a translation exists, preserve its split; otherwise copy the split
    # original so the user sees editable text instead of falling back.
    segment.translated_text = trans_first if segment.translated_text else orig_first
    segment.end_time = mid_time
    db.commit()
    db.refresh(segment)

    # Insert new segment with second halves
    new_segment = Segment(
        video_id=video_id,
        sequence_number=segment.sequence_number + 1,
        start_time=mid_time,
        end_time=original_end_time,
        original_text=orig_second,
        translated_text=trans_second if segment.translated_text else orig_second,
    )
    db.add(new_segment)
    db.commit()
    db.refresh(new_segment)

    # Return updated segment list
    updated_segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.sequence_number)
        .all()
    )

    return {
        "status": "success",
        "new_segment_id": new_segment.id,
        "segments": [_segment_to_dict(s) for s in updated_segments],
    }


@router.post("/{video_id}/segments/restore")
def restore_segments(
    video_id: str,
    body: dict[str, Any],
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Bulk-replace all segments for a video with a restored state (undo support).

    Deletes all existing segments and re-inserts the provided list.
    Preserves IDs from the snapshot when available to avoid breaking
    frontend references.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    segments_data = body.get("segments", [])

    # Delete all existing segments for this video
    db.query(Segment).filter(Segment.video_id == video_id).delete(
        synchronize_session=False
    )
    db.commit()

    # Re-insert restored segments
    restored_ids = []
    for seg_data in segments_data:
        new_seg = Segment(
            id=seg_data.get("id") or str(uuid.uuid4()),
            video_id=video_id,
            sequence_number=int(seg_data.get("sequence_number", 0)),
            start_time=float(seg_data.get("start_time", 0.0)),
            end_time=float(seg_data.get("end_time", 0.0)),
            original_text=str(seg_data.get("original_text", "")),
            translated_text=seg_data.get("translated_text"),
        )
        db.add(new_seg)
        restored_ids.append(new_seg.id)

    db.commit()

    # Refresh and return ordered list
    updated_segments = (
        db.query(Segment)
        .filter(Segment.id.in_(restored_ids))
        .order_by(Segment.sequence_number)
        .all()
    )

    return {
        "status": "success",
        "segments": [_segment_to_dict(s) for s in updated_segments],
    }
