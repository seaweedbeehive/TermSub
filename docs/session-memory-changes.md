# Session Memory Feature — Change Summary for Review

## Branch
`feat/session-memory` (branched from `main`, never merged back at the time of writing)

## High-level goal
Allow users to refresh the page, navigate back, or leave and return without losing their place in the subtitle/text translation pipeline. Persist enough state in `localStorage` + backend so the wizard can resume at the correct step.

---

## Backend changes

### New API endpoints (`app/api/jobs.py`)
- `GET /api/jobs` — list jobs for the authenticated user/BYOK caller.
- `GET /api/jobs/{job_id}` — detail view for a single job.

### Video API changes (`app/api/videos.py`)
- `PATCH /videos/{video_id}/config` — update `source_language`, `target_language`, and `skip_glossary`.
  - Allowed when status is `uploaded`, `transcribed`, `terms_ready`, `completed`, or `error`.
  - Changing `target_language` clears existing translations and, after a later fix, also clears extracted terms and resets status to `transcribed` so terminology is re-extracted for the new language.
- `POST /videos/{video_id}/transcribe` is idempotent: if status is already `transcribed`, `terms_ready`, or `completed`, it returns `already_complete` instead of re-running transcription.

### Schema changes (`app/schemas/video.py`)
- Added `VideoConfigUpdate` schema used by the PATCH endpoint.

---

## Frontend changes

### New module: `frontend/js/jobSession.js`
- Thin wrapper around `localStorage`.
- Key: `termsub_current_job`.
- Stores only `jobId` and `config` (`sourceLang`, `targetLang`, `mode`, `downloaded`).
- Exposes: `loadSession`, `saveSession`, `saveConfig`, `markDownloaded`, `clearSession`.

### Main UI / wizard changes (`frontend/js/main.js`, `frontend/index.html`)

#### Step model
The wizard was simplified from the previous 4-step model to 3 user-facing steps:
- `0` — config / upload (language selection + pipeline buttons).
- `2` — terminology / processing / review.
- `3` — completed / export.

There is no step 1; subtitle timeline review was removed as a standalone decision step.

#### Step-state variables
- `autoWizardStep` — the step implied by backend status.
- `userWizardStep` — set when the user presses Back; allows the displayed step to lag behind backend progress.
- `displayedWizardStep` — computed as `userWizardStep` if it is behind `autoWizardStep`, otherwise `autoWizardStep`.

#### `statusToStep(status)` mapping
| Backend status | Wizard step |
|---|---|
| `uploaded`, `error` | 0 |
| `queued`, `extracting_audio`, `transcribing`, `transcribed`, `awaiting_choice`, `analyzing`, `context_ready`, `glossary_extracting`, `terms_ready`, `translating` | 2 |
| `completed` | 3 |

`translating` intentionally maps to step 2 so export buttons are not shown before translation finishes.

#### Back / Next buttons
- New Back button returns from step 3 → step 2 (translation pipelines) or step 0 (transcribe-only pipelines).
- From step 2 → step 0.
- New Next button appears when the user has navigated back and can move forward toward `autoWizardStep`.
- Valid forward transitions are `0 → 2` and `2 → 3` (no step 1).

#### Pipeline buttons
- `translateSubtitlesBtn` — when a job exists, continues with `continueWithConfigCheck(mode)`; otherwise starts fresh upload.
- `originalSubtitlesBtn` — same for transcribe-only mode.
- Buttons are disabled while an upload / continue is in flight to prevent double-clicks.

#### `continueWithConfigCheck(mode)`
- Reads current Tom Select values.
- Compares to saved config.
- If language changed, calls `PATCH /videos/{id}/config`.
- Then calls `continuePipeline(mode)`.

#### `runPipeline(mode)`
- `transcribe`: starts transcription if not already done.
- `terminology`: waits for transcription, then runs terminology analysis. If status is already `terms_ready` / `translating` / `completed`, it does **not** auto-translate; it stays on the terms panel.
- `subtitles`: waits for transcription, then calls `skipAndTranslate()` unless already `completed` or `translating`.

#### Upload area state
- `updateUploadAreaState(step)` shows the config scene on step 0 (even with an existing job) so the user can change languages, and shows the compact upload card during processing / review / export.

#### Tom Select handling
- `restoreJobSession()` guards against calling `.setValue()` when Tom Select failed to load (e.g. CSP blocked it) and falls back to the native `<select>` element.

### CSP update (`app/main.py`)
- Added `https://cdn.jsdelivr.net` to `script-src`, `style-src`, and `connect-src` so Tom Select JS/CSS/source maps load.

### Error handling
- Added global `window.onerror` and `unhandledrejection` listeners for easier frontend debugging.
- `loadUser()` treats `401` from `/api/auth/me` as expected unauthenticated state instead of logging an error.

---

## Known limitations / areas a reviewer should check

1. **Text pipeline** was fixed on a separate branch (`feat/text-pipeline`) after session-memory work. If `feat/session-memory` is tested with `.txt` files, those fixes need to be present.
2. **Browser end-to-end tests** were not run; verification was limited to syntax checks, local Docker health checks, and `tests/test_session_memory.py`.
3. **Race condition on translation start**: a user can edit terms and click Translate; the translator loads the glossary once at task start. A later fix on `main` addresses this, but `feat/session-memory` may still need that backport.
4. **Session data is minimal**: only `jobId` + `config`. If the backend job is deleted, the session is cleared on next load. No expiration handling for very old sessions.
5. **Transcribe-only Back behavior**: Back from completed goes to step 0 for transcribe-only. This is intentional because there is no terminology review step.
6. **Celery/Redis/Render deployment**: on Render, this branch needs its own Background Worker and shared storage for `uploads/`, otherwise workers cannot find uploaded files.

---

## Tests
- `tests/test_session_memory.py` — 3 tests covering:
  - Config update
  - Translation clearing on target language change
  - Idempotent transcribe

## Validation performed
- `node --check frontend/js/main.js`
- `venv/bin/pytest tests/test_session_memory.py -q`
- Docker web service restart + `/health` check
- Manual browser interaction during development


---

## Key code snippets

### `app/api/jobs.py`

```
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
    videos = (
        query.order_by(Video.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

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

```

### `app/api/videos.py`

```
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
from sqlalchemy import text
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


async def _websocket_progress_callback(
    video_id: str, status: str, data: dict[str, Any]
) -> None:
    """Callback function to send progress updates via WebSocket."""
    if _websocket_manager:
        await _websocket_manager.broadcast_to_video(video_id, data)


router = APIRouter(prefix="/videos", tags=["videos"])


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

    if body.source_language is not None:
        video.source_language = body.source_language
    if body.target_language is not None:
        video.target_language = body.target_language
    if body.skip_glossary is not None:
        video.skip_glossary = body.skip_glossary

    target_language_changed = body.target_language is not None and (
        body.target_language != original_target_language
    )

    if target_language_changed:
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
                    "status": "completed",
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

        # Check prerequisites - be lenient
        valid_statuses = [
            VideoStatus.TERMS_READY.value,
            VideoStatus.TRANSLATING.value,
            VideoStatus.QUEUED.value,
            VideoStatus.TRANSCRIBING.value,
            VideoStatus.UPLOADED.value,
            VideoStatus.TRANSCRIBED.value,
        ]

        if video.status not in valid_statuses:
            print(f"[API Translate] Invalid status: {video.status}")
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Video status is {video.status}. Need terms_ready or transcribed."
                ),
            )

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
        "segments": [
            {
                "id": s.id,
                "sequence_number": s.sequence_number,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "original_text": s.original_text,
                "translated_text": s.translated_text,
            }
            for s in updated_segments
        ],
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
        "segments": [
            {
                "id": s.id,
                "sequence_number": s.sequence_number,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "original_text": s.original_text,
                "translated_text": s.translated_text,
            }
            for s in updated_segments
        ],
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
        "segments": [
            {
                "id": s.id,
                "sequence_number": s.sequence_number,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "original_text": s.original_text,
                "translated_text": s.translated_text,
            }
            for s in updated_segments
        ],
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
        "segments": [
            {
                "id": s.id,
                "sequence_number": s.sequence_number,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "original_text": s.original_text,
                "translated_text": s.translated_text,
            }
            for s in updated_segments
        ],
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
        "segments": [
            {
                "id": s.id,
                "sequence_number": s.sequence_number,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "original_text": s.original_text,
                "translated_text": s.translated_text,
            }
            for s in updated_segments
        ],
    }

```

### `app/schemas/video.py`

```
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sequence_number: int
    start_time: float
    end_time: float
    original_text: str
    translated_text: str | None = None


class VideoBase(BaseModel):
    filename: str
    target_language: str = Field(..., min_length=1)


class VideoCreate(VideoBase):
    file_path: str


class VideoUpdate(BaseModel):
    status: str | None = None
    source_language: str | None = None


class VideoConfigUpdate(BaseModel):
    """Editable configuration fields for an existing video job."""

    source_language: str | None = None
    target_language: str | None = None
    skip_glossary: bool | None = None


class VideoOut(VideoBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    file_path: str
    status: str
    source_language: str | None
    domain: str = "general"
    created_at: datetime
    updated_at: datetime

    # Progress tracking fields
    progress_percent: int = 0
    current_step: str | None = None
    step_detail: str | None = None
    total_segments: int = 0
    processed_segments: int = 0
    current_segment_index: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    context_analysis: str | None = None  # JSON from Pass 1
    skip_glossary: bool = False
    segments: list[SegmentOut] | None = None


class VideoProgress(BaseModel):
    """Detailed progress information for a video."""

    model_config = ConfigDict(from_attributes=True)

    video_id: str
    status: str
    progress_percent: int
    current_step: str | None
    step_detail: str | None
    total_segments: int
    processed_segments: int
    current_segment_index: int
    estimated_time_remaining: str | None
    started_at: datetime | None
    completed_at: datetime | None


class ProcessingLogEntry(BaseModel):
    """Single processing log entry."""

    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    level: str
    step: str
    message: str
    details: str | None


class VideoProgressDetail(VideoProgress):
    """Progress with detailed logs."""

    recent_logs: list[ProcessingLogEntry]

```

### `frontend/js/jobSession.js`

```
/**
 * Job session persistence layer.
 *
 * Stores only lightweight job configuration and the job id. All heavy state
 * (segments, terms, results) is fetched fresh from the backend on restore.
 */

(function () {
    const STORAGE_KEY = 'termsub_current_job';

    function now() {
        return new Date().toISOString();
    }

    function loadSession() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            return JSON.parse(raw);
        } catch (err) {
            console.error('[jobSession] Failed to load session:', err);
            return null;
        }
    }

    function saveSession(payload) {
        try {
            const session = {
                jobId: payload.jobId,
                config: payload.config || {},
                savedAt: now(),
            };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
            return session;
        } catch (err) {
            console.error('[jobSession] Failed to save session:', err);
            return null;
        }
    }

    function clearSession() {
        try {
            localStorage.removeItem(STORAGE_KEY);
        } catch (err) {
            console.error('[jobSession] Failed to clear session:', err);
        }
    }

    function saveConfig(jobId, config) {
        return saveSession({ jobId, config });
    }

    function markDownloaded() {
        clearSession();
    }

    // Expose a minimal API on window so the rest of the vanilla JS app can use
    // it without a module loader.
    window.jobSession = {
        STORAGE_KEY,
        loadSession,
        saveSession,
        saveConfig,
        markDownloaded,
        clearSession,
    };
})();

```

### `frontend/js/main.js`

```
        // State
        let currentVideoId = null;
        let videoProgressPercent = 0;  // Track progress for WebSocket updates
        let currentFileType = 'video'; // 'video' or 'text' - tracks uploaded file type
        let loggedCompletions = new Set(); // Track completed jobs to prevent duplicate logs
        let currentJobId = null; // Track current job to ignore stale messages
        let isJobRunning = false; // Silver bullet: prevents stale completion logs
        let hasStartedProcessing = false; // Status Transition Guard: ignore COMPLETED until processing starts
        let isSavingSegment = false; // Prevents concurrent blur / replace-all race conditions
        let timelineHistory = [];    // Stack of segment snapshots for undo
        let currentTimelineSegments = []; // Last rendered segment state
        let targetPipelineMode = null; // 'transcribe' | 'terminology' | 'subtitles' | null
        let autoWizardStep = 0;      // step implied by backend status
        let userWizardStep = null;   // step user explicitly navigated to via Back
        let displayedWizardStep = 0; // computed: userWizardStep if behind autoWizardStep, else autoWizardStep
        let lastKnownStatus = null;  // most recent backend status received
        const MAX_TIMELINE_HISTORY = 20;

        window.onerror = function(message, source, lineno, colno, error) {
            console.error('[TERMSUB GLOBAL ERROR]', message, 'at', source, lineno + ':' + colno, error);
        };
        window.addEventListener('unhandledrejection', function(event) {
            console.error('[TERMSUB UNHANDLED REJECTION]', event.reason);
        });

        // ------------------------------------------------------------------
        // Authentication
        // ------------------------------------------------------------------
        const API_KEY_KEY = 'termsub_api_key';
        const EMAIL_KEY = 'termsub_email';
        let currentUser = null;
        let currentAuthTab = 'standard';
        let currentStandardMode = 'signup';
        let currentAuthSubview = 'form'; // 'form' | 'forgot' | 'reset'

        function getApiKey() {
            return localStorage.getItem(API_KEY_KEY) || '';
        }

        function setApiKey(apiKey) {
            localStorage.setItem(API_KEY_KEY, apiKey);
        }

        function clearApiKey() {
            localStorage.removeItem(API_KEY_KEY);
        }

        function getStoredEmail() {
            return localStorage.getItem(EMAIL_KEY) || '';
        }

        function setStoredEmail(email) {
            if (email) localStorage.setItem(EMAIL_KEY, email);
        }

        function clearStoredEmail() {
            localStorage.removeItem(EMAIL_KEY);
        }

        function maskEmail(email) {
            if (!email || !email.includes('@')) return 'your email';
            const [localPart, domain] = email.split('@');
            const maskedLocal = localPart.length > 1
                ? localPart[0] + '*'.repeat(localPart.length - 1)
                : '*';
            return `${maskedLocal}@${domain}`;
        }

        function setupPasswordToggles() {
            document.addEventListener('click', (event) => {
                const toggleBtn = event.target.closest('[data-toggle-password]');
                if (!toggleBtn) return;

                const inputId = toggleBtn.getAttribute('data-toggle-password');
                const input = document.getElementById(inputId);
                if (!input) return;

                const isHidden = input.type === 'password';
                input.type = isHidden ? 'text' : 'password';
                toggleBtn.textContent = isHidden ? 'Hide' : 'Show';
            });
        }

        function isStandardLoggedIn() {
            return currentUser !== null && !isByokMode();
        }

        function isByokMode() {
            return !!getApiKey();
        }

        function isAuthenticated() {
            return isStandardLoggedIn() || isByokMode();
        }

        // Patch global fetch to attach the BYOK API key to same-origin API calls.
        // Standard auth is handled automatically via the HttpOnly cookie.
        (function patchFetch() {
            const originalFetch = window.fetch;
            window.fetch = async function(input, init) {
                const url = typeof input === 'string' ? input : input.url || input.toString();
                const isSameOrigin = url.startsWith('/') || url.startsWith(window.location.origin);
                if (isSameOrigin) {
                    init = init || {};
                    const headers = new Headers(init.headers || {});
                    const apiKey = getApiKey();
                    if (apiKey && !headers.has('X-API-Key')) {
                        headers.set('X-API-Key', apiKey);
                    }
                    init.headers = headers;
                }
                return originalFetch(input, init);
            };
        })();

        // ------------------------------------------------------------------
        // Admin Dashboard
        // ------------------------------------------------------------------
        let adminData = { stats: null, users: [], subscribers: [] };

        function showAdminError(message) {
            const el = document.getElementById('adminError');
            if (!el) return;
            el.textContent = message;
            el.classList.remove('hidden');
        }

        function hideAdminError() {
            const el = document.getElementById('adminError');
            if (!el) return;
            el.classList.add('hidden');
        }

        function minutesProgressColor(minutes) {
            if (minutes < 20) return 'bg-emerald-500';
            if (minutes <= 27) return 'bg-amber-500';
            return 'bg-red-500';
        }

        function renderAdminStats() {
            const stats = adminData.stats || {};
            const totalUsersEl = document.getElementById('adminStatTotalUsers');
            const newUsersEl = document.getElementById('adminStatNewUsers');
            const newsletterEl = document.getElementById('adminStatNewsletter');
            const uploadsEl = document.getElementById('adminStatUploads');
            if (totalUsersEl) totalUsersEl.textContent = stats.total_users ?? '-';
            if (newUsersEl) newUsersEl.textContent = stats.new_users_today ?? '-';
            if (newsletterEl) newsletterEl.textContent = stats.newsletter_subscribers ?? '-';
            if (uploadsEl) uploadsEl.textContent = stats.uploads_today ?? '-';
        }

        function renderAdminUsers() {
            const tbody = document.getElementById('adminUsersTable');
            if (!tbody) return;
            if (!adminData.users.length) {
                tbody.innerHTML = `<tr><td colspan="6" class="px-4 py-8 text-center text-slate-400 dark:text-[#6B7280]">No users found.</td></tr>`;
                return;
            }
            tbody.innerHTML = adminData.users.map(user => {
                const minutes = user.minutes_used ?? 0;
                const pct = Math.min(100, Math.max(0, (minutes / 30) * 100));
                const barColor = minutesProgressColor(minutes);
                const joined = user.created_at
                    ? new Date(user.created_at).toLocaleDateString()
                    : '-';
                const adminBadge = user.is_admin
                    ? '<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">Admin</span>'
                    : '<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 dark:bg-[#2A2A30] text-slate-600 dark:text-[#8A8F98]">User</span>';
                const modeClass = user.api_key_mode === 'byok'
                    ? 'bg-slate-800 text-white dark:bg-[#2A2A30] dark:text-[#E2E2E8]'
                    : 'bg-blue-600 text-white dark:bg-blue-600 dark:text-white';
                return `
                    <tr class="hover:bg-slate-50 dark:hover:bg-[#121214] transition-colors">
                        <td class="px-4 py-3 text-slate-900 dark:text-[#E2E2E8] font-medium">${escapeHtml(user.email)}</td>
                        <td class="px-4 py-3 text-slate-600 dark:text-[#8A8F98]">${joined}</td>
                        <td class="px-4 py-3">
                            <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium uppercase ${modeClass}">${user.api_key_mode}</span>
                        </td>
                        <td class="px-4 py-3 w-48">
                            <div class="flex items-center gap-2">
                                <div class="flex-1 h-2 bg-slate-100 dark:bg-[#2A2A30] rounded-full overflow-hidden">
                                    <div class="h-full ${barColor} rounded-full" style="width: ${pct}%"></div>
                                </div>
                                <span class="text-xs text-slate-600 dark:text-[#8A8F98] whitespace-nowrap">${minutes.toFixed(1)}/30</span>
                            </div>
                        </td>
                        <td class="px-4 py-3">${adminBadge}</td>
                        <td class="px-4 py-3">
                            <div class="flex items-center gap-2">
                                <button data-admin-action="reset-quota" data-user-id="${user.id}" class="px-2 py-1 text-xs font-medium rounded bg-slate-100 dark:bg-[#2A2A30] hover:bg-slate-200 dark:hover:bg-[#3A3A40] text-slate-700 dark:text-[#E2E2E8] transition-colors">Reset Quota</button>
                                <button data-admin-action="toggle-mode" data-user-id="${user.id}" class="px-2 py-1 text-xs font-medium rounded bg-slate-100 dark:bg-[#2A2A30] hover:bg-slate-200 dark:hover:bg-[#3A3A40] text-slate-700 dark:text-[#E2E2E8] transition-colors">Toggle Mode</button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        function renderAdminSubscribers() {
            const container = document.getElementById('adminNewsletterList');
            if (!container) return;
            if (!adminData.subscribers.length) {
                container.innerHTML = '<span class="text-sm text-slate-400 dark:text-[#6B7280]">No subscribers found.</span>';
                return;
            }
            container.innerHTML = adminData.subscribers.map(sub => `
                <span class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-50 dark:bg-[#121214] border border-slate-200 dark:border-[#2A2A30] text-xs text-slate-700 dark:text-[#E2E2E8]">
                    ${escapeHtml(sub.email)}
                    <span class="text-[10px] uppercase tracking-wider text-slate-400 dark:text-[#6B7280]">${sub.source}</span>
                </span>
            `).join('');
        }

        async function loadAdminDashboard() {
            hideAdminError();

            try {
                const [statsRes, usersRes, subsRes] = await Promise.all([
                    fetch('/api/admin/stats'),
                    fetch('/api/admin/users'),
                    fetch('/api/auth/newsletter-signups')
                ]);

                if (statsRes.status === 401 || statsRes.status === 403 ||
                    usersRes.status === 401 || usersRes.status === 403 ||
                    subsRes.status === 401 || subsRes.status === 403) {
                    redirectToHome('Admin access denied');
                    return;
                }

                if (!statsRes.ok || !usersRes.ok || !subsRes.ok) {
                    const detail = await statsRes.text().catch(() => 'Admin request failed');
                    throw new Error(detail || 'Admin request failed');
                }

                adminData.stats = await statsRes.json();
                adminData.users = await usersRes.json();
                adminData.subscribers = await subsRes.json();

                renderAdminStats();
                renderAdminUsers();
                renderAdminSubscribers();
            } catch (err) {
                showAdminError('Failed to load admin data: ' + err.message);
            }
        }

        async function handleAdminAction(action, userId) {
            hideAdminError();
            const endpoint = action === 'reset-quota'
                ? `/api/admin/users/${userId}/reset-quota`
                : `/api/admin/users/${userId}/toggle-mode`;
            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                if (response.status === 401 || response.status === 403) {
                    redirectToHome('Admin access denied');
                    return;
                }
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Action failed');
                }
                showToast(action === 'reset-quota' ? 'Quota reset' : 'Mode toggled', 'success');
                await loadAdminDashboard();
            } catch (err) {
                showAdminError('Action failed: ' + err.message);
            }
        }

        function redirectToHome(message) {
            const adminView = document.getElementById('adminView');
            const mainApp = document.getElementById('mainApp');
            if (adminView) adminView.classList.add('hidden');
            if (mainApp) mainApp.classList.remove('hidden');
            window.history.pushState({}, '', '/');
            showToast(message, 'error');
        }

        async function showAdminView() {
            const adminView = document.getElementById('adminView');
            const mainApp = document.getElementById('mainApp');
            const authView = document.getElementById('authView');
            const verifyView = document.getElementById('verifyView');
            if (adminView) adminView.classList.remove('hidden');
            if (mainApp) mainApp.classList.add('hidden');
            if (authView) authView.classList.add('hidden');
            if (verifyView) verifyView.classList.add('hidden');

            if (!isStandardLoggedIn()) {
                redirectToHome('Please log in as an admin');
                return;
            }

            try {
                const response = await fetch('/api/auth/me');
                if (!response.ok) {
                    redirectToHome('Admin access denied');
                    return;
                }
                const user = await response.json();
                if (!user.is_admin) {
                    redirectToHome('Admin access required');
                    return;
                }
                loadAdminDashboard();
            } catch (err) {
                redirectToHome('Could not verify admin access');
            }
        }

        function hideAdminView() {
            const adminView = document.getElementById('adminView');
            const mainApp = document.getElementById('mainApp');
            if (adminView) adminView.classList.add('hidden');
            if (mainApp) mainApp.classList.remove('hidden');
        }

        // Status config with colors
        const statusConfig = {
            uploaded: { label: 'Uploaded', color: 'bg-blue-500/20 text-blue-300', dotColor: 'bg-blue-400' },
            queued: { label: 'Queued', color: 'bg-gray-100 text-gray-700', dotColor: 'bg-gray-400' },
            extracting_audio: { label: 'Extracting Audio', color: 'bg-amber-100 text-amber-800', dotColor: 'bg-amber-500' },
            transcribing: { label: 'Transcribing', color: 'bg-orange-100 text-orange-800', dotColor: 'bg-orange-500' },
            transcribed: { label: 'Transcribed', color: 'bg-blue-100 text-blue-800', dotColor: 'bg-blue-500' },
            analyzing: { label: 'Analyzing', color: 'bg-blue-500/20 text-blue-300', dotColor: 'bg-blue-400' },
            context_ready: { label: 'Context Ready', color: 'bg-blue-500/20 text-blue-300', dotColor: 'bg-blue-400' },
            glossary_extracting: { label: 'Extracting Terms', color: 'bg-yellow-100 text-yellow-800', dotColor: 'bg-yellow-500' },
            terms_ready: { label: 'Terms Ready', color: 'bg-indigo-100 text-indigo-800', dotColor: 'bg-indigo-500' },
            translating: { label: 'Translating via OpenAI', color: 'bg-purple-100 text-purple-800', dotColor: 'bg-purple-500' },
            completed: { label: 'Completed', color: 'bg-emerald-100 text-emerald-800', dotColor: 'bg-emerald-500' },
            error: { label: 'Error', color: 'bg-rose-100 text-rose-800', dotColor: 'bg-rose-500' }
        };

        // Utility functions
        function markDownloadedSession() {
            if (window.jobSession) window.jobSession.markDownloaded();
        }

        async function fetchVideoData(videoId) {
            try {
                const response = await fetch(`/videos/${videoId}`);
                if (!response.ok) return null;
                return await response.json();
            } catch (err) {
                console.error('[session] Failed to fetch video data:', err);
                return null;
            }
        }

        async function persistTranscription(videoId) {
            if (!window.jobSession || !videoId) return;
            const session = window.jobSession.loadSession() || {};
            window.jobSession.saveConfig(videoId, session.config || {});
        }

        async function persistTranslation(videoId) {
            if (!window.jobSession || !videoId) return;
            const session = window.jobSession.loadSession() || {};
            window.jobSession.saveConfig(videoId, session.config || {});
        }

        async function restoreJobSession() {
            if (!window.jobSession) return;
            const session = window.jobSession.loadSession();
            if (!session || !session.jobId) {
                if (session) window.jobSession.clearSession();
                return;
            }

            const { jobId, config } = session;

            // Fetch fresh job data from backend; clear stale session if the job is gone.
            const data = await fetchVideoData(jobId);
            if (!data) {
                console.warn('[session] Could not restore job; clearing session.');
                window.jobSession.clearSession();
                return;
            }

            // Restore basic state
            currentVideoId = jobId;
            currentFileType = data.content_type || 'video';
            targetPipelineMode = config?.mode || null;

            // Restore form values via Tom Select instances if present and functional.
            if (window.termsubSourceLanguageTom && typeof window.termsubSourceLanguageTom.setValue === 'function') {
                window.termsubSourceLanguageTom.setValue(config?.sourceLang || 'auto');
            } else {
                const sourceLangSel = document.getElementById('sourceLanguage');
                if (sourceLangSel && config?.sourceLang) sourceLangSel.value = config.sourceLang;
            }
            if (window.termsubTargetLanguageTom && typeof window.termsubTargetLanguageTom.setValue === 'function') {
                window.termsubTargetLanguageTom.setValue(config?.targetLang || '');
            } else {
                const targetLangSel = document.getElementById('targetLanguage');
                if (targetLangSel && config?.targetLang) targetLangSel.value = config.targetLang;
            }
            const terminologyCheckbox = document.getElementById('reviewTerminologyCheckbox');
            if (terminologyCheckbox && config?.terminology !== undefined) {
                terminologyCheckbox.checked = config.terminology;
            }

            // Make sure the status and action containers are visible
            const statusCardEl = document.getElementById('statusCard');
            if (statusCardEl) statusCardEl.classList.remove('hidden');
            const primaryActionEl = document.getElementById('primaryActionContainer');
            if (primaryActionEl) primaryActionEl.classList.remove('hidden');

            // Update metadata display
            const projectTitleEl = document.getElementById('projectTitle');
            if (projectTitleEl) projectTitleEl.textContent = data.filename || config?.videoName || 'Untitled Project';
            const projectIdEl = document.getElementById('projectId');
            if (projectIdEl) projectIdEl.textContent = jobId.substring(0, 8);

            const status = data.status === 'awaiting_choice' ? 'transcribed' : data.status;

            autoWizardStep = statusToStep(status);
            userWizardStep = null;
            displayedWizardStep = computeDisplayedStep();

            updateStatus({ ...data, status });
            updateContextBrief(data);
            applyWizardStep(displayedWizardStep);

            if (data.segments && (status === 'transcribed' || status === 'completed')) {
                renderSubtitleTimeline(data.segments);
            }
            if (status === 'terms_ready' || status === 'completed') {
                renderTerms();
            }

            // Reconnect WebSocket for live updates
            await connectWebSocket(jobId);

            showToast('Resumed your previous session', 'success');
        }

        function log(message, type = 'info') {
            const logEl = document.getElementById('activityLog');
            const time = new Date().toLocaleTimeString('en-US', { hour12: false });

            if (logEl.children.length === 1 && logEl.children[0].textContent.includes('Waiting')) {
                logEl.replaceChildren();
            }

            // Prevent duplicate completion messages
            const lastEntry = logEl.lastElementChild;
            if (lastEntry && lastEntry.textContent.includes(message)) {
                return; // Skip duplicate message
            }

            // Badge map
            const badgeMap = {
                info:    { label: 'INFO',    bg: 'bg-slate-700',    text: 'text-slate-200' },
                success: { label: 'SUCCESS', bg: 'bg-emerald-600',  text: 'text-white' },
                error:   { label: 'ERROR',   bg: 'bg-red-600',      text: 'text-white' },
                warning: { label: 'WARN',    bg: 'bg-amber-500',    text: 'text-white' },
                align:   { label: 'ALIGN',   bg: 'bg-cyan-600',     text: 'text-white' },
                context: { label: 'CONTEXT', bg: 'bg-indigo-600',   text: 'text-white' }
            };
            const cfg = badgeMap[type] || badgeMap.info;

            const entry = document.createElement('div');
            entry.className = 'flex items-start gap-2 text-slate-300';

            const badge = document.createElement('span');
            badge.className = `shrink-0 mt-0.5 px-1 py-0.5 rounded text-[9px] font-bold uppercase tracking-wide ${cfg.bg} ${cfg.text}`;
            badge.textContent = cfg.label;

            const text = document.createElement('span');
            text.className = 'text-[11px] leading-tight';
            text.textContent = `[${time}] ${message}`;

            entry.appendChild(badge);
            entry.appendChild(text);
            logEl.appendChild(entry);
            logEl.scrollTo({ top: logEl.scrollHeight, behavior: 'smooth' });

            // Mirror critical errors in the normal user-facing status line
            if (type === 'error') {
                updateUserFacingStatus({ status: 'error', message });
            }
        }

        function clearActivityLog() {
            const logEl = document.getElementById('activityLog');
            logEl.replaceChildren();
            loggedCompletions.clear(); // Reset completion tracking
        }

        function expandActivityLog() {
            const container = document.getElementById('activityLogContainer');
            const toggle = document.getElementById('activityLogToggle');
            if (container) container.classList.remove('activity-log-collapsed');
            if (toggle) toggle.setAttribute('aria-expanded', 'true');
        }

        function updateUserFacingStatus(data) {
            const currentStepEl = document.getElementById('currentStep');
            if (!currentStepEl) return;

            const isError = data.status === 'error' || !!data.error;
            const friendly = {
                uploaded: 'Upload complete — ready to process.',
                queued: 'Queued — waiting for an available worker...',
                extracting_audio: 'Extracting audio from the video...',
                transcribing: 'Transcribing audio with OpenAI Whisper...',
                transcribed: 'Transcription complete — review or continue.',
                analyzing: 'Analyzing content and tone...',
                context_ready: 'Context analysis complete.',
                glossary_extracting: 'Extracting key terms...',
                terms_ready: 'Terms extracted — review them before translating.',
                translating: 'Translating subtitles with OpenAI GPT-4o...',
                completed: 'Done — subtitles are ready.',
            };

            if (isError) {
                currentStepEl.replaceChildren();
                currentStepEl.appendChild(document.createTextNode('Something went wrong.'));
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.dataset.openActivityLog = '';
                btn.className = 'text-blue-400 hover:text-blue-300 underline ml-1';
                btn.textContent = 'See the description in activity log.';
                currentStepEl.appendChild(btn);
                currentStepEl.classList.remove('text-slate-300');
                currentStepEl.classList.add('text-rose-300');
            } else {
                const message = friendly[data.status] || data.current_step || data.message || 'Processing...';
                currentStepEl.textContent = message;
                currentStepEl.classList.remove('text-rose-300');
                currentStepEl.classList.add('text-slate-300');
            }
        }

        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // ------------------------------------------------------------------
        // Auth UI helpers
        // ------------------------------------------------------------------
        function showAuthView(tab = 'standard', mode = 'signup') {
            currentAuthTab = tab;
            currentStandardMode = mode;
            currentAuthSubview = 'form';
            updateAuthUI();
            setAuthSubview('form');
            const authView = document.getElementById('authView');
            if (authView) authView.classList.remove('hidden');
            const verifyView = document.getElementById('verifyView');
            if (verifyView) verifyView.classList.add('hidden');
            document.body.style.overflow = 'hidden';
        }

        function showMainApp() {
            const authView = document.getElementById('authView');
            if (authView) authView.classList.add('hidden');
            const verifyView = document.getElementById('verifyView');
            if (verifyView) verifyView.classList.add('hidden');
            const mainApp = document.getElementById('mainApp');
            if (mainApp) mainApp.classList.remove('hidden');
            document.body.style.overflow = '';
        }

        function showVerifyView() {
            const authView = document.getElementById('authView');
            if (authView) authView.classList.add('hidden');
            const verifyView = document.getElementById('verifyView');
            if (verifyView) {
                const emailDisplay = document.getElementById('verifyEmailDisplay');
                if (emailDisplay) emailDisplay.textContent = maskEmail(getStoredEmail());
                verifyView.classList.remove('hidden');
            }
            const mainApp = document.getElementById('mainApp');
            if (mainApp) mainApp.classList.add('hidden');
            document.body.style.overflow = '';
        }

        function setAuthTab(tab) {
            currentAuthTab = tab;
            updateAuthUI();
        }

        function setStandardMode(mode) {
            currentStandardMode = mode;
            updateAuthUI();
        }

        function updateAuthUI() {
            const standardTab = document.getElementById('authTabStandard');
            const byokTab = document.getElementById('authTabByok');
            const standardForm = document.getElementById('standardAuthForm');
            const byokForm = document.getElementById('byokAuthForm');
            const submitBtn = document.getElementById('authSubmitBtn');
            const toggleText = document.getElementById('authModeToggleText');
            const toggleBtn = document.getElementById('authModeToggleBtn');
            const wantsUpdatesContainer = document.getElementById('wantsUpdatesContainer');
            const standardTermsContainer = document.getElementById('standardTermsContainer');
            const standardTermsCheckbox = document.getElementById('standardTermsCheckbox');
            const passwordInput = document.getElementById('authPassword');
            const authError = document.getElementById('authError');
            const byokError = document.getElementById('byokError');

            if (authError) authError.classList.add('hidden');
            if (byokError) byokError.classList.add('hidden');

            const activeTabClass = 'bg-white dark:bg-[#1A1A1E] text-slate-900 dark:text-[#E2E2E8] shadow-sm';
            const inactiveTabClass = 'text-slate-600 dark:text-[#8A8F98] hover:text-slate-900 dark:hover:text-[#E2E2E8]';
            if (standardTab) {
                standardTab.className = `flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${currentAuthTab === 'standard' ? activeTabClass : inactiveTabClass}`;
            }
            if (byokTab) {
                byokTab.className = `flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${currentAuthTab === 'byok' ? activeTabClass : inactiveTabClass}`;
            }

            if (standardForm) standardForm.classList.toggle('hidden', currentAuthTab !== 'standard');
            if (byokForm) byokForm.classList.toggle('hidden', currentAuthTab !== 'byok');

            const isLogin = currentStandardMode === 'login';
            if (submitBtn) submitBtn.textContent = isLogin ? 'Sign In' : 'Create Free Account';
            if (wantsUpdatesContainer) wantsUpdatesContainer.classList.toggle('hidden', isLogin);
            if (standardTermsContainer) standardTermsContainer.classList.toggle('hidden', isLogin);
            if (standardTermsCheckbox) standardTermsCheckbox.required = !isLogin;
            if (passwordInput) passwordInput.setAttribute('autocomplete', isLogin ? 'current-password' : 'new-password');
            if (toggleText) toggleText.textContent = isLogin ? "Don't have an account?" : 'Already have an account?';
            if (toggleBtn) toggleBtn.textContent = isLogin ? 'Create Free Account' : 'Sign in';
        }

        function setAuthSubview(subview) {
            currentAuthSubview = subview;
            const standardForm = document.getElementById('standardAuthForm');
            const forgotForm = document.getElementById('forgotPasswordForm');
            const resetForm = document.getElementById('resetPasswordForm');
            const byokForm = document.getElementById('byokAuthForm');
            const authTabs = document.getElementById('authTabStandard')?.parentElement;

            if (standardForm) standardForm.classList.toggle('hidden', subview !== 'form' || currentAuthTab !== 'standard');
            if (forgotForm) forgotForm.classList.toggle('hidden', subview !== 'forgot');
            if (resetForm) resetForm.classList.toggle('hidden', subview !== 'reset');
            if (byokForm) byokForm.classList.toggle('hidden', subview !== 'form' || currentAuthTab !== 'byok');
            if (authTabs) authTabs.classList.toggle('hidden', subview !== 'form');

            const authError = document.getElementById('authError');
            const forgotError = document.getElementById('forgotPasswordError');
            const forgotSuccess = document.getElementById('forgotPasswordSuccess');
            const resetError = document.getElementById('resetPasswordError');
            const resetSuccess = document.getElementById('resetPasswordSuccess');
            if (authError) authError.classList.add('hidden');
            if (forgotError) forgotError.classList.add('hidden');
            if (forgotSuccess) forgotSuccess.classList.add('hidden');
            if (resetError) resetError.classList.add('hidden');
            if (resetSuccess) resetSuccess.classList.add('hidden');
        }

        function showForgotPassword() {
            setAuthSubview('forgot');
        }

        function showResetPassword(token) {
            setAuthSubview('reset');
            const authView = document.getElementById('authView');
            if (authView) authView.classList.remove('hidden');
            document.body.style.overflow = 'hidden';
            const resetForm = document.getElementById('resetPasswordForm');
            if (resetForm) resetForm.dataset.token = token || '';
        }

        function updateUserDisplay() {
            const userInfo = document.getElementById('userInfo');
            const userEmailEl = document.getElementById('userEmail');
            const loginBtn = document.getElementById('loginBtn');
            const quotaWidget = document.getElementById('quotaWidgetHeader');

            if (currentUser && userInfo && userEmailEl) {
                userEmailEl.textContent = currentUser.email;
                userInfo.classList.remove('hidden');
                if (loginBtn) loginBtn.classList.add('hidden');
            } else if (isByokMode() && userInfo && userEmailEl) {
                userEmailEl.textContent = 'Using your OpenAI key';
                userInfo.classList.remove('hidden');
                if (loginBtn) loginBtn.classList.add('hidden');
            } else {
                if (userInfo) userInfo.classList.add('hidden');
                if (loginBtn) loginBtn.classList.remove('hidden');
                if (quotaWidget) quotaWidget.classList.add('hidden');
            }
        }

        function updateQuotaDisplay(quota) {
            const widget = document.getElementById('quotaWidgetHeader');
            const minutesEl = document.getElementById('quotaMinutesHeader');
            if (!widget || !minutesEl || !quota) return;
            if (quota.is_unlimited) {
                minutesEl.textContent = 'Unlimited';
                widget.classList.remove('hidden');
                return;
            }
            minutesEl.textContent = `${quota.minutes_remaining ?? 0} min remaining`;
            widget.classList.remove('hidden');
        }

        async function loadUser() {
            try {
                const response = await fetch('/api/auth/me');
                if (response.status === 401) {
                    // Not logged in — this is expected for guests and BYOK users.
                    currentUser = null;
                    return false;
                }
                if (response.status === 403) {
                    console.warn('Email not verified');
                    currentUser = null;
                    showVerifyView();
                    return false;
                }
                if (!response.ok) throw new Error('Session expired');
                currentUser = await response.json();
                updateUserDisplay();
                await loadQuota();
                return true;
            } catch (err) {
                console.error('Failed to load user:', err);
                clearStoredEmail();
                currentUser = null;
                return false;
            }
        }

        async function loadQuota() {
            try {
                const response = await fetch('/api/quota/');
                if (!response.ok) throw new Error('Quota unavailable');
                const quota = await response.json();
                updateQuotaDisplay(quota);
                return quota;
            } catch (err) {
                console.error('Failed to load quota:', err);
                return null;
            }
        }

        async function logout() {
            try {
                await fetch('/api/auth/logout', { method: 'POST' });
            } catch (err) {
                console.error('Logout API call failed:', err);
            }
            clearApiKey();
            clearStoredEmail();
            currentUser = null;
            updateUserDisplay();
            const widget = document.getElementById('quotaWidgetHeader');
            if (widget) widget.classList.add('hidden');
            showAuthView('standard', 'signup');
            log('Logged out', 'info');
        }

        // ------------------------------------------------------------------
        // Profile / Settings
        // ------------------------------------------------------------------
        let profileUsageSkip = 0;
        const profileUsageLimit = 10;
        let profileUsageTotal = 0;

        function toggleUserMenu(show) {
            const dropdown = document.getElementById('userMenuDropdown');
            if (!dropdown) return;
            dropdown.classList.toggle('hidden', !show);
        }

        function openProfileModal() {
            const modal = document.getElementById('profileModal');
            if (!modal) return;
            modal.classList.remove('hidden');
            modal.setAttribute('aria-hidden', 'false');
            document.body.style.overflow = 'hidden';
            loadProfile();
            loadProfileQuota();
            profileUsageSkip = 0;
            loadProfileUsage();
        }

        function closeProfileModal() {
            const modal = document.getElementById('profileModal');
            if (!modal) return;
            modal.classList.add('hidden');
            modal.setAttribute('aria-hidden', 'true');
            document.body.style.overflow = '';
        }

        function openMyJobsModal() {
            const modal = document.getElementById('myJobsModal');
            if (!modal) return;
            modal.classList.remove('hidden');
            modal.setAttribute('aria-hidden', 'false');
            loadMyJobs();
        }

        function closeMyJobsModal() {
            const modal = document.getElementById('myJobsModal');
            if (!modal) return;
            modal.classList.add('hidden');
            modal.setAttribute('aria-hidden', 'true');
        }

        async function loadMyJobs() {
            const listEl = document.getElementById('myJobsList');
            if (!listEl) return;
            listEl.innerHTML = '<p class="text-sm text-slate-500 dark:text-[#8A8F98]">Loading your jobs...</p>';

            try {
                const response = await fetch('/api/jobs?limit=50');
                if (!response.ok) throw new Error('Failed to load jobs');
                const data = await response.json();
                renderMyJobs(data.items || []);
            } catch (err) {
                listEl.innerHTML = `<p class="text-sm text-red-400">${err.message || 'Could not load jobs.'}</p>`;
            }
        }

        function renderMyJobs(jobs) {
            const listEl = document.getElementById('myJobsList');
            if (!listEl) return;

            if (jobs.length === 0) {
                listEl.innerHTML = '<p class="text-sm text-slate-500 dark:text-[#8A8F98]">No jobs yet. Upload a file to get started.</p>';
                return;
            }

            listEl.innerHTML = jobs.map((job) => {
                const source = job.source_language ? job.source_language.toUpperCase() : 'Auto';
                const target = job.target_language ? job.target_language.toUpperCase() : '-';
                const date = formatDate(job.updated_at);
                return `
                    <div class="bg-slate-50 dark:bg-[#121214] rounded-lg border border-slate-200 dark:border-[#2A2A30] p-4">
                        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                            <div class="min-w-0">
                                <p class="text-sm font-medium text-slate-900 dark:text-[#E2E2E8] truncate">${escapeHtml(job.video_filename || 'Untitled')}</p>
                                <p class="text-xs text-slate-500 dark:text-[#8A8F98] mt-1">${source} → ${target} · <span class="capitalize">${job.status.replace(/_/g, ' ')}</span> · ${date}</p>
                            </div>
                            <button type="button" data-job-id="${job.id}" class="my-jobs-resume-btn px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition-colors shrink-0">
                                Resume
                            </button>
                        </div>
                    </div>
                `;
            }).join('');

            listEl.querySelectorAll('.my-jobs-resume-btn').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const jobId = btn.dataset.jobId;
                    if (jobId) resumeJob(jobId);
                });
            });
        }

        async function resumeJob(jobId) {
            try {
                const response = await fetch(`/api/jobs/${jobId}`);
                if (!response.ok) throw new Error('Failed to load job details');
                const data = await response.json();

                // Persist as current session and restore UI.
                currentVideoId = data.id;
                targetPipelineMode = data.skip_glossary ? 'subtitles' : 'terminology';
                if (data.status === 'transcribed' || data.status === 'awaiting_choice') {
                    targetPipelineMode = 'transcribe';
                }

                if (window.jobSession) {
                    window.jobSession.saveConfig(data.id, {
                        sourceLang: data.source_language || 'auto',
                        targetLang: data.target_language || '',
                        terminology: !data.skip_glossary,
                        videoName: data.filename || 'Untitled Project',
                        mode: targetPipelineMode,
                    });
                }

                closeMyJobsModal();
                await restoreJobSession();
            } catch (err) {
                showToast(err.message || 'Could not resume job.', 'error');
            }
        }

        function openDeleteAccountModal() {
            const modal = document.getElementById('deleteAccountModal');
            if (!modal) return;
            modal.classList.remove('hidden');
            modal.setAttribute('aria-hidden', 'false');
        }

        function closeDeleteAccountModal() {
            const modal = document.getElementById('deleteAccountModal');
            if (!modal) return;
            modal.classList.add('hidden');
            modal.setAttribute('aria-hidden', 'true');
            const form = document.getElementById('deleteAccountForm');
            if (form) form.reset();
        }

        function formatDate(iso) {
            if (!iso) return '-';
            const d = new Date(iso);
            return isNaN(d) ? iso : d.toLocaleString();
        }

        async function loadProfile() {
            try {
                const response = await fetch('/api/profile/me');
                if (response.status === 401 || response.status === 403) {
                    throw new Error('Session expired. Please log in again.');
                }
                if (!response.ok) throw new Error('Failed to load profile');
                const data = await response.json();

                const emailEl = document.getElementById('profileEmail');
                const createdAtEl = document.getElementById('profileCreatedAt');
                const totalJobsEl = document.getElementById('profileTotalJobs');
                const verificationEl = document.getElementById('profileVerificationStatus');
                const wantsUpdatesInput = document.getElementById('profileWantsUpdates');
                const modeStandardInput = document.getElementById('profileModeStandard');
                const modeByokInput = document.getElementById('profileModeByok');

                if (emailEl) emailEl.textContent = data.email || '-';
                if (createdAtEl) createdAtEl.textContent = formatDate(data.created_at);
                if (totalJobsEl) totalJobsEl.textContent = data.total_jobs_processed ?? 0;
                if (verificationEl) {
                    verificationEl.textContent = data.is_email_verified ? 'Verified' : 'Unverified';
                    verificationEl.className = `text-xs font-medium ${data.is_email_verified ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'}`;
                }
                if (wantsUpdatesInput) wantsUpdatesInput.checked = !!data.wants_updates;
                if (modeStandardInput) modeStandardInput.checked = data.api_key_mode === 'standard';
                if (modeByokInput) modeByokInput.checked = data.api_key_mode === 'byok';

                const isByok = data.api_key_mode === 'byok';
                const byokContainer = document.getElementById('profileByokKeyContainer');
                if (byokContainer) byokContainer.classList.toggle('hidden', !isByok);

                // BYOK users cannot use standard-only profile features.
                const standardOnlySections = [
                    'profileQuotaSection',
                    'profilePreferencesSection',
                    'profileApiKeyModeSection',
                    'profileEmailSection',
                    'profilePasswordSection',
                    'profileSessionsSection',
                    'profileDeleteSection'
                ];
                standardOnlySections.forEach(id => {
                    const el = document.getElementById(id);
                    if (el) el.classList.toggle('hidden', isByok);
                });
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function loadProfileQuota() {
            try {
                const response = await fetch('/api/quota/');
                if (!response.ok) throw new Error('Quota unavailable');
                const data = await response.json();
                const remainingEl = document.getElementById('profileQuotaRemaining');
                const detailEl = document.getElementById('profileQuotaDetail');

                if (data.is_unlimited) {
                    if (remainingEl) remainingEl.textContent = 'Unlimited';
                    if (detailEl) detailEl.textContent = 'You are using your own OpenAI API key.';
                } else {
                    if (remainingEl) remainingEl.textContent = `${data.minutes_remaining ?? 0} min`;
                    if (detailEl) detailEl.textContent = `Used ${data.minutes_used ?? 0} of ${data.trial_minutes ?? 30} trial minutes.`;
                }
            } catch (err) {
                console.error('Failed to load profile quota:', err);
            }
        }

        function renderProfileUsage(data) {
            const tbody = document.getElementById('profileUsageTable');
            const pagination = document.getElementById('profileUsagePagination');
            const prevBtn = document.getElementById('profileUsagePrev');
            const nextBtn = document.getElementById('profileUsageNext');
            const pageInfo = document.getElementById('profileUsagePageInfo');
            if (!tbody) return;

            profileUsageTotal = data.total ?? 0;

            if (!data.items || !data.items.length) {
                tbody.innerHTML = `<tr><td colspan="4" class="px-3 py-4 text-center text-slate-400 dark:text-[#6B7280]">No usage history yet.</td></tr>`;
                if (pagination) pagination.classList.add('hidden');
                return;
            }

            tbody.innerHTML = data.items.map(item => `
                <tr class="hover:bg-slate-50 dark:hover:bg-[#121214] transition-colors">
                    <td class="px-3 py-2 text-slate-700 dark:text-[#E2E2E8]">${formatDate(item.created_at)}</td>
                    <td class="px-3 py-2 text-slate-700 dark:text-[#E2E2E8] max-w-[200px] truncate" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename)}</td>
                    <td class="px-3 py-2 text-slate-700 dark:text-[#E2E2E8]">${item.minutes_used ?? 0}</td>
                    <td class="px-3 py-2">
                        <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 dark:bg-[#2A2A30] text-slate-700 dark:text-[#E2E2E8]">${escapeHtml(item.status)}</span>
                    </td>
                </tr>
            `).join('');

            if (pagination) pagination.classList.remove('hidden');
            if (pageInfo) pageInfo.textContent = `${profileUsageSkip + 1}-${Math.min(profileUsageSkip + data.items.length, profileUsageTotal)} of ${profileUsageTotal}`;
            if (prevBtn) prevBtn.disabled = profileUsageSkip === 0;
            if (nextBtn) nextBtn.disabled = profileUsageSkip + data.items.length >= profileUsageTotal;
        }

        async function loadProfileUsage() {
            try {
                const response = await fetch(`/api/profile/usage?skip=${profileUsageSkip}&limit=${profileUsageLimit}`);
                if (!response.ok) throw new Error('Failed to load usage history');
                const data = await response.json();
                renderProfileUsage(data);
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function savePreferences(event) {
            event.preventDefault();
            const wantsUpdatesInput = document.getElementById('profileWantsUpdates');
            const body = {
                wants_updates: wantsUpdatesInput ? wantsUpdatesInput.checked : null
            };

            try {
                const response = await fetch('/api/profile/preferences', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to save preferences');
                }
                showToast('Preferences saved.', 'success');
                loadProfile();
                if (currentUser) {
                    currentUser.wants_updates = body.wants_updates;
                }
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function saveApiKeyMode(event) {
            event.preventDefault();
            const standardRadio = document.getElementById('profileModeStandard');
            const byokKeyInput = document.getElementById('profileByokKeyInput');
            const mode = standardRadio && standardRadio.checked ? 'standard' : 'byok';
            const body = { mode };
            if (mode === 'byok' && byokKeyInput) {
                body.api_key = byokKeyInput.value.trim();
            }

            try {
                const response = await fetch('/api/profile/api-key-mode', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to update API key mode');
                }
                showToast('API key mode updated.', 'success');
                loadProfile();
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function updateEmail(event) {
            event.preventDefault();
            const newEmailInput = document.getElementById('profileNewEmail');
            const passwordInput = document.getElementById('profileEmailPassword');
            const body = {
                new_email: newEmailInput ? newEmailInput.value.trim() : '',
                password: passwordInput ? passwordInput.value : ''
            };

            try {
                const response = await fetch('/api/profile/email', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to update email');
                }
                showToast('Email updated. Please verify your new address.', 'success');
                document.getElementById('profileEmailForm')?.reset();
                loadProfile();
                if (currentUser && newEmailInput) currentUser.email = newEmailInput.value.trim();
                updateUserDisplay();
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function changePassword(event) {
            event.preventDefault();
            const currentInput = document.getElementById('profileCurrentPassword');
            const newInput = document.getElementById('profileNewPassword');
            const confirmInput = document.getElementById('profileConfirmPassword');

            if (newInput.value !== confirmInput.value) {
                showToast('New passwords do not match.', 'error');
                return;
            }

            const body = {
                current_password: currentInput.value,
                new_password: newInput.value,
                confirm_password: confirmInput.value
            };

            try {
                const response = await fetch('/api/profile/password', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to change password');
                }
                showToast('Password changed successfully.', 'success');
                document.getElementById('profilePasswordForm')?.reset();
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function logoutAllSessions() {
            if (!confirm('Log out all other sessions? Your current session will remain active.')) return;
            try {
                const response = await fetch('/api/profile/sessions', { method: 'DELETE' });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to log out sessions');
                }
                showToast('All other sessions have been logged out.', 'success');
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function deleteAccount(event) {
            event.preventDefault();
            const confirmInput = document.getElementById('deleteAccountConfirm');
            const passwordInput = document.getElementById('deleteAccountPassword');

            if (confirmInput.value !== 'DELETE') {
                showToast('Please type DELETE to confirm.', 'error');
                return;
            }

            const body = {
                password: passwordInput.value,
                confirmation: confirmInput.value
            };

            try {
                const response = await fetch('/api/profile/account', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to delete account');
                }
                showToast('Your account has been deleted.', 'info');
                closeDeleteAccountModal();
                closeProfileModal();
                clearApiKey();
                clearStoredEmail();
                currentUser = null;
                updateUserDisplay();
                showAuthView('standard', 'signup');
            } catch (err) {
                showToast(err.message, 'error');
            }
        }

        async function handleStandardAuthSubmit(event) {
            event.preventDefault();
            const emailInput = document.getElementById('authEmail');
            const passwordInput = document.getElementById('authPassword');
            const wantsUpdatesInput = document.getElementById('authWantsUpdates');
            const errorEl = document.getElementById('authError');
            const submitBtn = document.getElementById('authSubmitBtn');

            const email = emailInput.value.trim();
            const password = passwordInput.value;
            const wantsUpdates = currentStandardMode === 'signup' ? wantsUpdatesInput.checked : undefined;

            if (errorEl) errorEl.classList.add('hidden');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = currentStandardMode === 'login' ? 'Signing in...' : 'Creating account...';
            }

            const endpoint = currentStandardMode === 'login' ? '/api/auth/login' : '/api/auth/signup';
            const body = { email, password };
            if (currentStandardMode === 'signup') body.wants_updates = wantsUpdates;

            try {
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });

                if (!response.ok) {
                    let detail = currentStandardMode === 'login' ? 'Invalid email or password.' : 'Sign up failed.';
                    try {
                        const data = await response.json();
                        if (data.detail) detail = data.detail;
                    } catch (e) { /* ignore */ }
                    throw new Error(detail);
                }

                clearApiKey();
                setStoredEmail(email);

                if (currentStandardMode === 'signup') {
                    // New accounts start unverified; show the verification screen immediately.
                    showVerifyView();
                    log('Account created — please verify your email', 'info');
                } else {
                    const loaded = await loadUser();
                    if (!loaded) {
                        if (getStoredEmail()) {
                            showVerifyView();
                        } else {
                            throw new Error('Could not load your account.');
                        }
                    } else {
                        showMainApp();
                        log(`Logged in as ${currentUser.email}`, 'success');
                    }
                }

                emailInput.value = '';
                passwordInput.value = '';
                if (wantsUpdatesInput) wantsUpdatesInput.checked = true;
            } catch (err) {
                if (errorEl) {
                    errorEl.textContent = err.message;
                    errorEl.classList.remove('hidden');
                }
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = currentStandardMode === 'login' ? 'Sign In' : 'Create Free Account';
                }
            }
        }

        async function handleByokSubmit(event) {
            event.preventDefault();
            const apiKeyInput = document.getElementById('byokApiKey');
            const emailInput = document.getElementById('byokEmail');
            const errorEl = document.getElementById('byokError');
            const submitBtn = document.getElementById('byokSubmitBtn');

            const apiKey = apiKeyInput.value.trim();
            const email = emailInput.value.trim();

            if (errorEl) errorEl.classList.add('hidden');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Validating key...';
            }

            try {
                const response = await fetch('/api/auth/byok-start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: apiKey, email })
                });

                if (!response.ok) {
                    let detail = 'The provided API key could not be validated.';
                    try {
                        const data = await response.json();
                        if (data.detail) detail = data.detail;
                    } catch (e) { /* ignore */ }
                    throw new Error(detail);
                }

                setApiKey(apiKey);
                updateUserDisplay();
                showMainApp();
                log('Using your own OpenAI API key', 'success');
                apiKeyInput.value = '';
                emailInput.value = '';
            } catch (err) {
                if (errorEl) {
                    errorEl.textContent = err.message;
                    errorEl.classList.remove('hidden');
                }
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Start Using TermSub';
                }
            }
        }

        async function handleForgotPasswordSubmit(event) {
            event.preventDefault();
            const emailInput = document.getElementById('forgotPasswordEmail');
            const errorEl = document.getElementById('forgotPasswordError');
            const successEl = document.getElementById('forgotPasswordSuccess');
            const submitBtn = document.getElementById('forgotPasswordSubmitBtn');

            const email = emailInput.value.trim();
            if (errorEl) errorEl.classList.add('hidden');
            if (successEl) successEl.classList.add('hidden');
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Sending...';
            }

            try {
                const response = await fetch('/api/auth/forgot-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to send reset email');
                }
                if (successEl) {
                    successEl.textContent = 'Check your email for reset link';
                    successEl.classList.remove('hidden');
                }
                emailInput.value = '';
            } catch (err) {
                if (errorEl) {
                    errorEl.textContent = err.message;
                    errorEl.classList.remove('hidden');
                }
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Send reset link';
                }
            }
        }

        async function handleResetPasswordSubmit(event) {
            event.preventDefault();
            const resetForm = document.getElementById('resetPasswordForm');
            const passwordInput = document.getElementById('resetPasswordInput');
            const confirmInput = document.getElementById('resetPasswordConfirm');
            const errorEl = document.getElementById('resetPasswordError');
            const successEl = document.getElementById('resetPasswordSuccess');
            const submitBtn = document.getElementById('resetPasswordSubmitBtn');

            const token = resetForm ? resetForm.dataset.token : '';
            const newPassword = passwordInput.value;
            const confirmPassword = confirmInput.value;

            if (errorEl) errorEl.classList.add('hidden');
            if (successEl) successEl.classList.add('hidden');

            if (newPassword !== confirmPassword) {
                if (errorEl) {
                    errorEl.textContent = 'Passwords do not match.';
                    errorEl.classList.remove('hidden');
                }
                return;
            }

            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = 'Resetting...';
            }

            try {
                const response = await fetch('/api/auth/reset-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        reset_token: token,
                        new_password: newPassword,
                        confirm_password: confirmPassword
                    })
                });
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.detail || 'Failed to reset password');
                }
                if (successEl) {
                    successEl.textContent = 'Password reset successfully. You can now sign in.';
                    successEl.classList.remove('hidden');
                }
                passwordInput.value = '';
                confirmInput.value = '';
                setTimeout(() => {
                    setAuthSubview('form');
                    setStandardMode('login');
                }, 2000);
            } catch (err) {
                if (errorEl) {
                    errorEl.textContent = err.message;
                    errorEl.classList.remove('hidden');
                }
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Reset password';
                }
            }
        }

        async function resendVerificationEmail() {
            const email = getStoredEmail();
            if (!email) {
                showVerifyMessage('Please log in again to resend the verification email.', 'error');
                showAuthView('standard', 'login');
                return;
            }
            const btn = document.getElementById('resendVerifyBtn');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin mr-2"></i>Sending...';
            }
            try {
                const response = await fetch('/api/auth/resend-verification', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email })
                });
                if (!response.ok) throw new Error('Request failed');
                showVerifyMessage('Verification email sent. Please check your inbox.', 'success');
            } catch (err) {
                console.error('Failed to resend verification email:', err);
                showVerifyMessage('Could not resend email. Please try again later.', 'error');
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fa-solid fa-paper-plane mr-2"></i>Resend Email';
                }
            }
        }

        async function recheckVerification() {
            const btn = document.getElementById('recheckVerifyBtn');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin mr-2"></i>Checking...';
            }
            const loaded = await loadUser();
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-rotate-right mr-2"></i>I\'ve Verified My Email';
            }
            if (loaded) {
                showMainApp();
                log('Email verified — welcome to TermSub', 'success');
            } else {
                showVerifyMessage('Your email is not verified yet. Please click the link in the email.', 'warning');
            }
        }

        function showVerifyMessage(message, type = 'info') {
            const el = document.getElementById('verifyMessage');
            if (!el) return;
            const colors = {
                info: 'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800',
                success: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800',
                warning: 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800',
                error: 'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800'
            };
            el.className = `text-xs mb-4 p-2 rounded border ${colors[type] || colors.info}`;
            el.textContent = message;
            el.classList.remove('hidden');
        }

        function showToast(message, type = 'info') {
            console.log("🔔 [Toast Triggered]:", message, type);
            const container = document.getElementById('toastContainer');
            if (!container) return;

            const colorMap = {
                info:    { bg: 'bg-blue-600',   icon: 'text-white' },
                success: { bg: 'bg-emerald-600', icon: 'text-white' },
                error:   { bg: 'bg-red-600',     icon: 'text-white' },
                warning: { bg: 'bg-amber-500',   icon: 'text-white' }
            };
            const cfg = colorMap[type] || colorMap.info;

            const el = document.createElement('div');
            el.className = `pointer-events-auto ${cfg.bg} text-white shadow-xl px-4 py-2 rounded-lg font-sans text-sm flex items-center gap-2 transition-all duration-300 transform translate-x-full`;

            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('class', `w-4 h-4 shrink-0 ${cfg.icon}`);
            svg.setAttribute('fill', 'none');
            svg.setAttribute('stroke', 'currentColor');
            svg.setAttribute('viewBox', '0 0 24 24');
            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('stroke-linecap', 'round');
            path.setAttribute('stroke-linejoin', 'round');
            path.setAttribute('stroke-width', '2');
            path.setAttribute('d', 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z');
            svg.appendChild(path);

            const span = document.createElement('span');
            span.className = 'font-medium';
            span.textContent = message;

            el.appendChild(svg);
            el.appendChild(span);
            container.appendChild(el);

            // Slide in
            requestAnimationFrame(() => el.classList.remove('translate-x-full'));

            // Auto-dismiss after 2.5 seconds
            setTimeout(() => {
                el.classList.add('translate-x-full', 'opacity-0');
                setTimeout(() => el.remove(), 300);
            }, 2500);
        }

        function updateStatus(data) {
            const normalizedStatus = data.status === 'awaiting_choice' ? 'transcribed' : data.status;
            lastKnownStatus = normalizedStatus;
            const cfg = statusConfig[normalizedStatus] || statusConfig.uploaded;
            const isProcessing = ['transcribing', 'extracting_audio', 'analyzing', 'glossary_extracting', 'translating', 'queued'].includes(normalizedStatus);
            
            // Update Status Badge in Card
            const statusBadge = document.getElementById('statusBadge');
            statusBadge.className = `inline-flex items-center gap-1.5 px-3 py-1.5 ${cfg.color} text-xs font-semibold rounded-full transition-colors`;
            statusBadge.innerHTML = `<span id="statusDot" class="w-1.5 h-1.5 rounded-full ${cfg.dotColor} ${isProcessing ? 'pulse-indicator' : ''}"></span>${cfg.label}`;
            
            // Update user-facing status (replaces the old currentStep / stepDetail text)
            updateUserFacingStatus(data);

            // Hide the old step-detail box to avoid redundancy
            const stepDetail = document.getElementById('stepDetail');
            if (stepDetail) stepDetail.classList.add('hidden');

            // Update segment counters
            const segmentCountEl = document.getElementById('segmentCount');
            if (segmentCountEl) segmentCountEl.textContent = `${data.total_segments ?? 0} segments`;
            const processedCountEl = document.getElementById('processedCount');
            if (processedCountEl) processedCountEl.textContent = `${data.processed_segments || 0} processed`;

            // Show/hide buttons based on status
            updateButtonVisibility(data.status);
        }

        async function renderTerms() {
            if (!currentVideoId) return;

            try {
                const response = await fetch(`/terms/video/${currentVideoId}`);
                const terms = await response.json();

                const tbody = document.getElementById('termsTable');
                const countBadge = document.getElementById('termsCount');

                if (!terms || terms.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" class="px-3 py-8 text-center text-slate-400 dark:text-[#6B7280] text-sm">No terms extracted yet.</td></tr>';
                    if (countBadge) countBadge.classList.add('hidden');
                    return;
                }

                if (countBadge) {
                    countBadge.textContent = terms.length.toString();
                    countBadge.classList.remove('hidden');
                }

                tbody.innerHTML = terms.map(term => {
                    // Clean translation: remove bracketed type prefix (e.g., "[Key Concept] ")
                    const cleanTranslation = (term.translated_term || '').replace(/^\[.*?\]\s*/, '');
                    // Format category for display: "proper_noun" → "Proper Noun"
                    const displayCategory = (term.category || 'General')
                        .replace(/_/g, ' ')
                        .replace(/\b\w/g, c => c.toUpperCase());
                    return `
                    <tr class="hover:bg-slate-50 dark:hover:bg-[#1A1A1E] ${term.source === 'manual' ? 'bg-amber-50/50 dark:bg-amber-900/20' : ''}">
                        <td class="px-3 py-2">
                            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-slate-100 dark:bg-[#2A2A30] text-slate-600 dark:text-[#8A8F98]">
                                ${escapeHtml(displayCategory)}
                            </span>
                        </td>
                        <td class="px-3 py-2 font-medium text-slate-900 dark:text-[#E2E2E8]">${escapeHtml(term.original_term)}</td>
                        <td class="px-3 py-2 text-slate-600 dark:text-[#8A8F98] rtl-text">${escapeHtml(cleanTranslation)}</td>
                        <td class="px-3 py-2">
                            <div class="flex items-center gap-2">
                                <input type="text" value="${escapeHtml(term.standardized_term || '')}" 
                                    onchange="updateTerm('${term.id}', this.value)"
                                    class="flex-1 border-transparent bg-slate-50/50 dark:bg-[#2A2A30]/70 hover:bg-slate-100/70 dark:hover:bg-[#2A2A30] focus:bg-white dark:focus:bg-[#1A1A1E] focus:border-slate-300 dark:focus:border-[#3A3A42] focus:ring-1 focus:ring-slate-300 dark:focus:ring-[#3A3A42] text-slate-900 dark:text-[#E2E2E8] placeholder-slate-400 dark:placeholder-[#6B7280] transition-all rounded px-2 py-1 text-xs">
                            </div>
                        </td>
                    </tr>
                `}).join('');

                // Refresh remaining minutes after terms are shown (video processing has billed minutes).
                loadQuota();
            } catch (err) {
                console.error('Failed to load terms:', err);
            }
        }

        const TIMECODE_REGEX = /^(\d{2}):(\d{2}):(\d{2}),(\d{3})$/;

        // Supported languages for source/target dropdowns (ISO-639-1 codes).
        // Covers the OpenAI Audio API supported languages plus legacy app languages.
        // Kept in one flat list, sorted alphabetically by English name.
        const SUPPORTED_LANGUAGES = [
            { code: 'af', name: 'Afrikaans', nativeName: 'Afrikaans' },
            { code: 'ar', name: 'Arabic', nativeName: 'العربية' },
            { code: 'hy', name: 'Armenian', nativeName: 'Հայերեն' },
            { code: 'az', name: 'Azerbaijani', nativeName: 'Azərbaycan' },
            { code: 'bn', name: 'Bengali', nativeName: 'বাংলা' },
            { code: 'be', name: 'Belarusian', nativeName: 'Беларуская' },
            { code: 'bs', name: 'Bosnian', nativeName: 'Bosanski' },
            { code: 'bg', name: 'Bulgarian', nativeName: 'Български' },
            { code: 'ca', name: 'Catalan', nativeName: 'Català' },
            { code: 'zh', name: 'Chinese (Mandarin)', nativeName: '中文' },
            { code: 'hr', name: 'Croatian', nativeName: 'Hrvatski' },
            { code: 'cs', name: 'Czech', nativeName: 'Čeština' },
            { code: 'da', name: 'Danish', nativeName: 'Dansk' },
            { code: 'nl', name: 'Dutch', nativeName: 'Nederlands' },
            { code: 'en', name: 'English', nativeName: 'English' },
            { code: 'et', name: 'Estonian', nativeName: 'Eesti' },
            { code: 'fa', name: 'Persian (Farsi)', nativeName: 'فارسی' },
            { code: 'fi', name: 'Finnish', nativeName: 'Suomi' },
            { code: 'fr', name: 'French', nativeName: 'Français' },
            { code: 'gl', name: 'Galician', nativeName: 'Galego' },
            { code: 'de', name: 'German', nativeName: 'Deutsch' },
            { code: 'el', name: 'Greek', nativeName: 'Ελληνικά' },
            { code: 'he', name: 'Hebrew', nativeName: 'עברית' },
            { code: 'hi', name: 'Hindi', nativeName: 'हिन्दी' },
            { code: 'hu', name: 'Hungarian', nativeName: 'Magyar' },
            { code: 'is', name: 'Icelandic', nativeName: 'Íslenska' },
            { code: 'id', name: 'Indonesian', nativeName: 'Bahasa Indonesia' },
            { code: 'it', name: 'Italian', nativeName: 'Italiano' },
            { code: 'ja', name: 'Japanese', nativeName: '日本語' },
            { code: 'kn', name: 'Kannada', nativeName: 'ಕನ್ನಡ' },
            { code: 'kk', name: 'Kazakh', nativeName: 'Қазақ' },
            { code: 'ko', name: 'Korean', nativeName: '한국어' },
            { code: 'lv', name: 'Latvian', nativeName: 'Latviešu' },
            { code: 'lt', name: 'Lithuanian', nativeName: 'Lietuvių' },
            { code: 'mk', name: 'Macedonian', nativeName: 'Македонски' },
            { code: 'ms', name: 'Malay', nativeName: 'Bahasa Melayu' },
            { code: 'mr', name: 'Marathi', nativeName: 'मराठी' },
            { code: 'mi', name: 'Maori', nativeName: 'Māori' },
            { code: 'ne', name: 'Nepali', nativeName: 'नेपाली' },
            { code: 'no', name: 'Norwegian', nativeName: 'Norsk' },
            { code: 'pl', name: 'Polish', nativeName: 'Polski' },
            { code: 'pt', name: 'Portuguese', nativeName: 'Português' },
            { code: 'ro', name: 'Romanian', nativeName: 'Română' },
            { code: 'ru', name: 'Russian', nativeName: 'Русский' },
            { code: 'sr', name: 'Serbian', nativeName: 'Српски' },
            { code: 'sk', name: 'Slovak', nativeName: 'Slovenčina' },
            { code: 'sl', name: 'Slovenian', nativeName: 'Slovenščina' },
            { code: 'es', name: 'Spanish', nativeName: 'Español' },
            { code: 'sw', name: 'Swahili', nativeName: 'Kiswahili' },
            { code: 'sv', name: 'Swedish', nativeName: 'Svenska' },
            { code: 'tl', name: 'Tagalog (Filipino)', nativeName: 'Tagalog' },
            { code: 'ta', name: 'Tamil', nativeName: 'தமிழ்' },
            { code: 'te', name: 'Telugu', nativeName: 'తెలుగు' },
            { code: 'th', name: 'Thai', nativeName: 'ไทย' },
            { code: 'tr', name: 'Turkish', nativeName: 'Türkçe' },
            { code: 'uk', name: 'Ukrainian', nativeName: 'Українська' },
            { code: 'ur', name: 'Urdu', nativeName: 'اردو' },
            { code: 'vi', name: 'Vietnamese', nativeName: 'Tiếng Việt' },
            { code: 'cy', name: 'Welsh', nativeName: 'Cymraeg' },
        ];

        function formatTimecode(seconds) {
            const totalMillis = Math.max(0, Math.round(seconds * 1000));
            const ms = (totalMillis % 1000).toString().padStart(3, '0');
            const totalSeconds = Math.floor(totalMillis / 1000);
            const s = (totalSeconds % 60).toString().padStart(2, '0');
            const totalMinutes = Math.floor(totalSeconds / 60);
            const m = (totalMinutes % 60).toString().padStart(2, '0');
            const h = Math.floor(totalMinutes / 60).toString().padStart(2, '0');
            return `${h}:${m}:${s},${ms}`;
        }

        function isValidTimecode(value) {
            return typeof value === 'string' && TIMECODE_REGEX.test(value.trim());
        }

        function timecodeToSeconds(value) {
            const match = value.trim().match(TIMECODE_REGEX);
            if (!match) return NaN;
            const hours = parseInt(match[1], 10);
            const minutes = parseInt(match[2], 10);
            const seconds = parseInt(match[3], 10);
            const millis = parseInt(match[4], 10);
            return hours * 3600 + minutes * 60 + seconds + millis / 1000;
        }
        
        function renderSubtitleTimeline(segments) {
            const grid = document.getElementById('timelineCardGrid');
            if (!grid) return;

            // Track the latest rendered state for history snapshots
            currentTimelineSegments = JSON.parse(JSON.stringify(segments || []));
            _updateUndoButton();

            if (!segments || segments.length === 0) {
                grid.innerHTML = '<div class="text-slate-400 dark:text-[#6B7280] text-center py-8">No subtitles available yet.</div>';
                return;
            }
            
            const template = document.getElementById('segmentCardTemplate');
            if (!template) return;

            grid.innerHTML = '';
            segments.forEach((seg, idx) => {
                const clone = template.content.cloneNode(true);
                const card = clone.querySelector('.group');
                clone.querySelector('.seq-num').textContent = `#${seg.sequence_number || idx + 1}`;

                const startInput = card.querySelector('input[data-time-role="start"]');
                const endInput = card.querySelector('input[data-time-role="end"]');
                const textEl = card.querySelector('[data-time-role="text"]');
                const splitBtn = card.querySelector('[data-action="split"]');
                const addBtn = card.querySelector('[data-action="add"]');
                const removeBtn = card.querySelector('[data-action="remove"]');

                [startInput, endInput, textEl, splitBtn, addBtn, removeBtn].forEach(el => {
                    if (el) el.setAttribute('data-segment-id', seg.id || '');
                });
                if (addBtn) addBtn.setAttribute('data-add-below', seg.sequence_number || idx + 1);

                if (startInput) startInput.value = formatTimecode(seg.start_time);
                if (endInput) endInput.value = formatTimecode(seg.end_time);

                if (textEl) {
                    textEl.textContent = seg.translated_text != null
                        ? seg.translated_text
                        : seg.original_text || '(empty)';
                    if (seg.translated_text == null) {
                        textEl.classList.add('text-slate-400', 'dark:text-[#6B7280]', 'italic');
                    }
                    textEl.dataset.originalText = textEl.textContent;
                }

                grid.appendChild(clone);
            });

            // Attach auto-save blur listeners to editable fields
            grid.querySelectorAll('input.timecode-input, [contenteditable="true"]').forEach(el => {
                el.addEventListener('blur', async (e) => {
                    if (isSavingSegment) return;
                    const segmentId = e.target.getAttribute('data-segment-id');
                    if (!segmentId || !currentVideoId) return;

                    const isTimeInput = e.target.tagName === 'INPUT' && e.target.hasAttribute('data-time-role');
                    const timeRole = isTimeInput ? e.target.getAttribute('data-time-role') : null;
                    const card = e.target.closest('.group');
                    const payload = {};

                    // Validate the specific field that triggered blur before building payload.
                    if (isTimeInput) {
                        const raw = e.target.value.trim();
                        if (!isValidTimecode(raw)) {
                            log('Invalid timecode format. Use HH:MM:SS,mmm (e.g. 00:01:23,456).', 'warning');
                            const originalSeg = currentTimelineSegments.find(s => s.id === segmentId);
                            if (originalSeg) {
                                e.target.value = formatTimecode(originalSeg[timeRole === 'start' ? 'start_time' : 'end_time']);
                            }
                            return;
                        }
                    }

                    // Aggregate latest text and timecode values for the segment.
                    const startInput = card.querySelector('input[data-time-role="start"]');
                    const endInput = card.querySelector('input[data-time-role="end"]');
                    const textEl = card.querySelector('[contenteditable="true"]');

                    if (startInput && endInput) {
                        payload.start_time = startInput.value.trim();
                        payload.end_time = endInput.value.trim();

                        if (isValidTimecode(payload.start_time) && isValidTimecode(payload.end_time)) {
                            if (timecodeToSeconds(payload.start_time) >= timecodeToSeconds(payload.end_time)) {
                                log('Start time must be strictly before end time.', 'warning');
                                const originalSeg = currentTimelineSegments.find(s => s.id === segmentId);
                                if (originalSeg && timeRole) {
                                    e.target.value = formatTimecode(originalSeg[timeRole === 'start' ? 'start_time' : 'end_time']);
                                }
                                return;
                            }
                        }
                    }

                    if (textEl) {
                        const newText = textEl.innerText.trim();
                        if (newText === '') {
                            log('Segment text cannot be empty — change discarded.', 'warning');
                            textEl.textContent = textEl.dataset.originalText || '(empty)';
                            return;
                        }
                        payload.translated_text = newText;
                    }

                    // Skip network call if nothing changed compared to the last rendered state.
                    const originalSeg = currentTimelineSegments.find(s => s.id === segmentId);
                    if (originalSeg) {
                        const changed = (
                            (payload.translated_text !== undefined && payload.translated_text !== originalSeg.translated_text) ||
                            (payload.start_time !== undefined && payload.start_time !== formatTimecode(originalSeg.start_time)) ||
                            (payload.end_time !== undefined && payload.end_time !== formatTimecode(originalSeg.end_time))
                        );
                        if (!changed) return;
                    }

                    pushTimelineHistory();
                    isSavingSegment = true;
                    try {
                        const response = await fetch(`/videos/${currentVideoId}/segments/${segmentId}`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        if (!response.ok) throw new Error('Server returned ' + response.status);
                        log('Segment updated and saved.', 'info');
                        showToast('Segment saved successfully', 'success');
                    } catch (err) {
                        console.error('Auto-save failed:', err);
                        log('Auto-save failed: ' + err.message, 'error');
                    } finally {
                        isSavingSegment = false;
                    }
                });
            });

            // Attach Split Card listeners
            grid.querySelectorAll('[data-action="split"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.preventDefault();
                    const segmentId = btn.getAttribute('data-segment-id');
                    if (!segmentId || !currentVideoId) return;
                    pushTimelineHistory();

                    try {
                        const response = await fetch(`/videos/${currentVideoId}/segments/${segmentId}/split`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' }
                        });
                        if (!response.ok) throw new Error('Server returned ' + response.status);
                        const data = await response.json();
                        log('Segment split successfully.', 'success');
                        if (data.segments) renderSubtitleTimeline(data.segments);
                    } catch (err) {
                        console.error('Split failed:', err);
                        log('Split failed: ' + err.message, 'error');
                    }
                });
            });

            // Attach Add Card Below listeners
            grid.querySelectorAll('[data-action="add"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.preventDefault();
                    const targetSeq = parseInt(btn.getAttribute('data-add-below'), 10) + 1;
                    if (!currentVideoId || isNaN(targetSeq)) return;
                    pushTimelineHistory();

                    try {
                        const response = await fetch(`/videos/${currentVideoId}/segments/add`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                target_sequence: targetSeq,
                                start_time: 0.0,
                                end_time: 2.0,
                                text: ''
                            })
                        });
                        if (!response.ok) throw new Error('Server returned ' + response.status);
                        const data = await response.json();
                        log('New segment added.', 'success');
                        if (data.segments) renderSubtitleTimeline(data.segments);
                    } catch (err) {
                        console.error('Add segment failed:', err);
                        log('Add segment failed: ' + err.message, 'error');
                    }
                });
            });

            // Attach Remove Card listeners
            grid.querySelectorAll('[data-action="remove"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.preventDefault();
                    const segmentId = btn.getAttribute('data-segment-id');
                    if (!segmentId || !currentVideoId) return;
                    pushTimelineHistory();

                    try {
                        const response = await fetch(`/videos/${currentVideoId}/segments/${segmentId}`, {
                            method: 'DELETE'
                        });
                        if (!response.ok) throw new Error('Server returned ' + response.status);
                        const data = await response.json();
                        log('Segment removed.', 'success');
                        if (data.segments) renderSubtitleTimeline(data.segments);
                    } catch (err) {
                        console.error('Remove segment failed:', err);
                        log('Remove segment failed: ' + err.message, 'error');
                    }
                });
            });
        }

        // ------------------------------------------------------------------
        // Timeline Undo System
        // ------------------------------------------------------------------
        function pushTimelineHistory() {
            // Save a snapshot of the current timeline before a mutating operation.
            if (!currentTimelineSegments || currentTimelineSegments.length === 0) return;
            timelineHistory.push(JSON.parse(JSON.stringify(currentTimelineSegments)));
            if (timelineHistory.length > MAX_TIMELINE_HISTORY) {
                timelineHistory.shift();
            }
            _updateUndoButton();
        }

        function _updateUndoButton() {
            const btn = document.getElementById('undoTimelineBtn');
            if (!btn) return;
            const hasHistory = timelineHistory.length > 0;
            btn.disabled = !hasHistory;
            btn.classList.toggle('opacity-50', !hasHistory);
            btn.classList.toggle('cursor-not-allowed', !hasHistory);
            btn.classList.toggle('hover:bg-slate-300', hasHistory);
            btn.classList.toggle('dark:hover:bg-[#3A3A40]', hasHistory);
        }

        async function undoTimeline() {
            if (timelineHistory.length === 0 || !currentVideoId) return;
            const restoredSegments = timelineHistory.pop();

            try {
                const response = await fetch(`/videos/${currentVideoId}/segments/restore`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ segments: restoredSegments })
                });
                if (!response.ok) throw new Error('Server returned ' + response.status);
                const data = await response.json();
                log('Undo successful.', 'success');
                if (data.segments) renderSubtitleTimeline(data.segments);
            } catch (err) {
                console.error('Undo failed:', err);
                log('Undo failed: ' + err.message, 'error');
                // Push the snapshot back so the user can retry
                timelineHistory.push(restoredSegments);
                _updateUndoButton();
            }
        }

        async function updateTerm(termId, value) {
            try {
                await fetch(`/terms/${termId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ standardized_term: value })
                });
                log(`Updated term ${termId.substring(0, 8)}...`, 'success');
            } catch (err) {
                log('Failed to update term: ' + err.message, 'error');
            }
        }

        async function fetchVideoStatus() {
            // Fetch current video status from server
            if (!currentVideoId) return;
            
            try {
                const response = await fetch(`/videos/${currentVideoId}`);
                const data = await response.json();

                // The backend reports "awaiting_choice" after transcription; treat it as
                // "transcribed" everywhere the UI is refreshed from polling.
                if (data.status === 'awaiting_choice') {
                    data.status = 'transcribed';
                }

                // Guard: Don't update status if we have an active job and this is stale data
                if (currentJobId && data.status === 'completed' && !loggedCompletions.has(currentJobId)) {
                    // This is likely stale data - wait for WebSocket confirmation
                    console.log('[fetchVideoStatus] Ignoring stale completion status');
                    return;
                }

                updateStatus({
                    status: data.status,
                    progress_percent: data.progress_percent || 0,
                    total_segments: data.total_segments,
                    processed_segments: data.processed_segments
                });

                updateButtonVisibility(data.status);
                updateContextBrief(data);
                if ((data.status === 'transcribed' || data.status === 'completed') && data.segments) {
                    renderSubtitleTimeline(data.segments);
                }
            } catch (err) {
                console.error('Failed to fetch video status:', err);
            }
        }

        // ============================================================================
        // WebSocket Connection Management (REPLACES OLD POLLING)
        // ============================================================================
        
        let ws = null;
        let wsReconnectAttempts = 0;
        const MAX_WS_RECONNECT_ATTEMPTS = 3;
        let fallbackPollInterval = null;
        let fallbackPollCount = 0;
        let lastPolledStatus = null;
        
        async function fetchWsToken() {
            try {
                const response = await fetch('/api/auth/ws-token', { method: 'POST' });
                if (!response.ok) return null;
                return await response.json();
            } catch (err) {
                console.error('[WebSocket] Failed to fetch WS token:', err);
                return null;
            }
        }
        
        function stopPolling() {
            if (fallbackPollInterval) {
                clearInterval(fallbackPollInterval);
                fallbackPollInterval = null;
            }
            lastPolledStatus = null;
        }
        
        async function connectWebSocket(videoId) {
            // Close existing connection and stop any polling from a previous session
            disconnectWebSocket();
            stopPolling();

            const apiKey = getApiKey();
            let protocols = null;
            let authMode = 'none';

            if (apiKey) {
                protocols = ['termsub-byok', apiKey];
                authMode = 'byok';
            } else if (currentUser) {
                // Standard users obtain a short-lived token via HTTP and send it
                // through the Sec-WebSocket-Protocol header. This is more reliable
                // than relying on cookies during the WebSocket upgrade.
                const tokenData = await fetchWsToken();
                if (tokenData && tokenData.ws_token && tokenData.subprotocol) {
                    protocols = [tokenData.subprotocol, tokenData.ws_token];
                    authMode = 'standard-ws-token';
                } else {
                    log('WebSocket auth token unavailable - falling back to status polling', 'warning');
                    fallbackToPolling(videoId);
                    return;
                }
            }

            if (authMode === 'none') {
                log('WebSocket connection skipped: not authenticated', 'warning');
                fallbackToPolling(videoId);
                return;
            }

            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${wsProtocol}//${window.location.host}/ws/videos/${videoId}`;

            log('Connecting to WebSocket...');
            console.log(`[WebSocket] Connecting to ${wsUrl} (${authMode})`);

            try {
                ws = new WebSocket(wsUrl, protocols);
                
                ws.onopen = () => {
                    console.log('[WebSocket] Connected');
                    log('WebSocket connected - real-time updates enabled', 'success');
                    wsReconnectAttempts = 0;
                    
                    // Send initial ping
                    if (ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({type: 'ping'}));
                    }
                };
                
                ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        console.log('[WebSocket] Message received:', data);
                        
                        // Handle different message types
                        if (data.type === 'pong' || data.type === 'keepalive') {
                            return; // Ignore keepalive messages
                        }
                        
                        if (data.type === 'connected') {
                            log(`Connected to video stream: ${data.video_id?.substring(0, 8)}...`);
                            return;
                        }
                        
                        // Update UI based on status
                        handleWebSocketMessage(data);
                        
                    } catch (err) {
                        console.error('[WebSocket] Failed to parse message:', err);
                    }
                };
                
                ws.onerror = (err) => {
                    console.error('[WebSocket] Error:', err);
                    log('WebSocket error - falling back to status polling', 'error');
                    fallbackToPolling(videoId);
                };
                
                ws.onclose = () => {
                    console.log('[WebSocket] Connection closed');
                    ws = null;
                    
                    // Attempt to reconnect if we have a video ID and haven't exceeded attempts
                    if (currentVideoId && wsReconnectAttempts < MAX_WS_RECONNECT_ATTEMPTS) {
                        wsReconnectAttempts++;
                        log(`WebSocket disconnected. Reconnecting (${wsReconnectAttempts}/${MAX_WS_RECONNECT_ATTEMPTS})...`);
                        setTimeout(() => connectWebSocket(currentVideoId), 2000);
                    } else if (currentVideoId) {
                        log('WebSocket reconnect attempts exhausted - falling back to status polling', 'warning');
                        fallbackToPolling(currentVideoId);
                    }
                };
                
            } catch (err) {
                console.error('[WebSocket] Failed to create connection:', err);
                log('WebSocket connection failed - falling back to status polling', 'error');
                fallbackToPolling(videoId);
            }
        }
        
        function disconnectWebSocket() {
            if (ws) {
                // Prevent the close handler from trying to reconnect
                const socket = ws;
                ws = null;
                socket.onclose = null;
                socket.close();
                console.log('[WebSocket] Disconnected by client');
            }
        }
        
        function handleWebSocketMessage(data) {
            // Handle both direct status updates and job messages
            let status = data.status;

            // The backend emits "awaiting_choice" after transcription; treat it as
            // "transcribed" so the correct pipeline UI (export or auto-advance) is shown.
            if (status === 'awaiting_choice') {
                status = 'transcribed';
            }

            // Handle job_complete messages
            if (data.type === 'job_complete') {
                const jobType = data.job_type || 'task';
                const jobId = data.job_id || `${jobType}-${Date.now()}`;
                
                // Guard: Skip if we've already logged this completion
                if (loggedCompletions.has(jobId)) {
                    console.log('[WebSocket] Ignoring duplicate job_complete for:', jobId);
                    return;
                }
                
                // Guard: Skip if this is a stale message for a previous job
                if (currentJobId && data.job_id && data.job_id !== currentJobId) {
                    console.log('[WebSocket] Ignoring stale job_complete for old job:', jobId);
                    return;
                }
                
                console.log('[WebSocket] Job complete:', jobType);
                loggedCompletions.add(jobId);
                
                // Map job types to status and log appropriate completion message
                if (jobType === 'transcribe') {
                    status = 'transcribed';
                    // Safe segment count extraction with nullish coalescing
                    const segmentCount = data.result?.total_segments ?? data.total_segments ?? 0;
                    const segText = segmentCount > 0 ? `: ${segmentCount} segments` : '';
                    log(`Transcription complete${segText}`, 'success');
                    isJobRunning = false;
                    hasStartedProcessing = false;

                    // Persist transcription milestone
                    persistTranscription(currentVideoId);

                    // Auto-advance through the selected pipeline
                    if (targetPipelineMode === 'terminology') {
                        log('Auto-advancing to terminology analysis...');
                        updateButtonVisibility('transcribed');
                        setTimeout(() => analyzeVideo(), 0);
                    } else if (targetPipelineMode === 'subtitles') {
                        log('Auto-advancing to translation...');
                        updateButtonVisibility('transcribed');
                        setTimeout(() => skipAndTranslate(), 0);
                    } else {
                        // Transcribe-only (or no mode): show export buttons
                        updateButtonVisibility('transcribed');
                    }
                } else if (jobType === 'analyze') {
                    status = 'terms_ready';
                    const termCount = data.result?.terms_extracted ?? data.terms_count ?? 0;
                    const termText = termCount > 0 ? `: ${termCount} terms extracted` : '';
                    log(`Analysis complete${termText}`, 'success');
                    isJobRunning = false;
                    hasStartedProcessing = false;
                    renderTerms();
                    updateButtonVisibility('terms_ready');
                } else if (jobType === 'translate') {
                    status = 'completed';
                    const translatedCount = data.result?.translated_segments ?? data.translated_count ?? 0;
                    const totalCount = data.result?.total_segments ?? data.total_segments ?? 0;
                    const countText = (translatedCount > 0 || totalCount > 0) 
                        ? `: ${translatedCount}/${totalCount} segments` 
                        : '';
                    log(`Translation complete${countText}`, 'success');
                    isJobRunning = false;
                    hasStartedProcessing = false;
                    updateButtonVisibility('completed');
                    if (data.result?.segments) renderSubtitleTimeline(data.result.segments);

                    // Persist translation milestone
                    persistTranslation(currentVideoId);
                } else {
                    log(`${jobType} complete`, 'success');
                }
                
                // Refresh status from server (without triggering duplicate logs)
                fetchVideoStatus();
                return; // Don't process further - we handled it
            }
            
            // Handle job_error messages
            if (data.type === 'job_error') {
                const jobType = data.job_type || 'task';
                const errorMsg = data.error || 'Unknown error';
                console.log('[WebSocket] Job error:', data);
                log(`${jobType} failed: ${errorMsg}`, 'error');
                return;
            }
            
            // Handle job_started messages
            if (data.type === 'job_started') {
                const jobType = data.job_type || 'task';
                console.log('[WebSocket] Job started:', jobType);
                hasStartedProcessing = true;
                // Log appropriate started message
                if (jobType === 'transcribe') {
                    log('Transcription started...');
                } else if (jobType === 'analyze') {
                    log('Analysis started...');
                } else if (jobType === 'translate') {
                    log('Translation started...');
                } else {
                    log(`${jobType} started...`);
                }
                return;
            }
            
            // Update status display for regular status messages
            updateStatus({
                status: status,
                progress_percent: data.progress || videoProgressPercent || 0,
                total_segments: data.total_segments,
                processed_segments: data.processed_segments,
                current_step: data.message || status
            });
            
            // Log the update (only if meaningful message exists)
            const logMessage = data.message || data.step_detail;
            if (logMessage && logMessage !== status && logMessage !== 'undefined') {
                // Badge duration & completion metrics as SUCCESS
                const isMetric = /(?:duration|elapsed|complete in|segments?|total)\\s*[:\\-]?\\s*\\d/i.test(logMessage);
                log(logMessage, isMetric ? 'success' : 'info');
            }
            
            // Status Transition Guard: only mark after we see a processing state
            if (['queued', 'extracting_audio', 'transcribing', 'analyzing', 'glossary_extracting', 'translating'].includes(status)) {
                hasStartedProcessing = true;
            }
            
            // Handle specific statuses
            switch (status) {
                case 'queued':
                    log('Job queued - waiting for available worker...');
                    break;
                    
                case 'transcribing':
                    log('Transcribing audio...');
                    break;
                    
                case 'transcribed':
                    if (isJobRunning && hasStartedProcessing) {
                        log('Transcription complete!', 'success');
                        // Do NOT reset isJobRunning/hasStartedProcessing here — that is the
                        // job_complete handler's responsibility. Resetting early causes the
                        // job_complete message to be treated as stale and breaks auto-advance.
                    }
                    updateButtonVisibility('transcribed');
                    break;
                    
                case 'analyzing':
                    log('Director Agent: Analyzing content...');
                    break;
                    
                case 'context_ready':
                    log(`Director Agent complete: ${data.tone} tone`, 'context');
                    // Fetch full Pass 1 context_analysis for the narrative brief
                    fetch(`/videos/${currentVideoId}`)
                        .then(r => r.json())
                        .then(videoData => updateContextBrief(videoData));
                    break;
                    
                case 'glossary_extracting':
                    log('Glossary Agent: Extracting terms...');
                    break;
                    
                case 'terms_ready':
                    if (isJobRunning && hasStartedProcessing) {
                        log(`Glossary complete: ${data.terms_count ?? 0} terms`, 'success');
                    }
                    renderTerms();
                    updateButtonVisibility('terms_ready');
                    break;
                    
                case 'translating':
                    log('Translating via OpenAI AI...');
                    break;
                    
                case 'completed':
                    if (isJobRunning && hasStartedProcessing) {
                        log('Translation complete!', 'success');
                    }
                    renderTerms();
                    updateButtonVisibility('completed');
                    if (data.segments) renderSubtitleTimeline(data.segments);
                    break;
                    
                case 'error':
                    log(`Error: ${data.message || data.error}`, 'error');
                    break;
            }
            
            // Handle job retry messages
            if (data.type === 'job_retry') {
                log(`Retrying: ${data.job_type} (${data.retry_count}/${data.max_retries})`);
            }
        }
        
        // Wizard step helpers
        function statusToStep(status) {
            // Map backend statuses to user-facing wizard steps.
            // 3 = completed/export
            // 2 = processing / terminology review (includes translation in progress)
            // 0 = config/upload
            if (status === 'completed') return 3;
            if (
                status === 'translating' ||
                status === 'terms_ready' ||
                status === 'analyzing' ||
                status === 'context_ready' ||
                status === 'glossary_extracting' ||
                status === 'transcribed' ||
                status === 'awaiting_choice' ||
                status === 'transcribing' ||
                status === 'extracting_audio' ||
                status === 'queued'
            ) {
                return 2;
            }
            return 0;
        }

        function computeDisplayedStep() {
            // Displayed step = userWizardStep if it is behind autoWizardStep, else autoWizardStep.
            if (userWizardStep !== null && userWizardStep < autoWizardStep) {
                return userWizardStep;
            }
            return autoWizardStep;
        }

        function refreshDisplayedStep() {
            displayedWizardStep = computeDisplayedStep();
            applyWizardStep(displayedWizardStep);
        }

        function updateUploadAreaState(step) {
            // Upload-area state is computed once, based on currentVideoId and the
            // current wizard step.
            const uploadForm = document.getElementById('uploadForm');
            const configScene = document.getElementById('configScene');
            const uploadCompleteCard = document.getElementById('uploadCompleteCard');

            if (!currentVideoId) {
                // No job yet: show file drop zone + config controls.
                if (uploadForm) uploadForm.classList.remove('hidden');
                if (configScene) configScene.classList.remove('hidden');
                if (uploadCompleteCard) uploadCompleteCard.classList.add('hidden');
            } else if (step === 0) {
                // User navigated back to edit config for an existing job.
                if (uploadForm) uploadForm.classList.add('hidden');
                if (configScene) configScene.classList.remove('hidden');
                if (uploadCompleteCard) uploadCompleteCard.classList.add('hidden');
            } else {
                // Processing/review/export steps: show compact upload card only.
                if (uploadForm) uploadForm.classList.add('hidden');
                if (configScene) configScene.classList.add('hidden');
                if (uploadCompleteCard) uploadCompleteCard.classList.remove('hidden');
            }
        }

        function goBack() {
            console.log(`[wizard] goBack called from step ${displayedWizardStep}`);
            if (displayedWizardStep <= 0) return;
            // From completed/export (3) → terms review (2) for translation pipelines,
            // or config (0) for transcribe-only pipelines.
            if (displayedWizardStep === 3) {
                userWizardStep = targetPipelineMode === 'transcribe' ? 0 : 2;
            } else {
                userWizardStep = 0;
            }
            console.log(`[wizard] userWizardStep set to ${userWizardStep}`);
            refreshDisplayedStep();
        }

        function goForward() {
            console.log(`[wizard] goForward called from step ${displayedWizardStep}, auto=${autoWizardStep}`);
            if (userWizardStep === null || displayedWizardStep >= autoWizardStep) return;
            // Valid wizard steps are 0, 2, 3 (there is no step 1). Advance to the
            // next valid step, never to the non-existent step 1.
            if (displayedWizardStep === 0) {
                userWizardStep = Math.min(2, autoWizardStep);
            } else if (displayedWizardStep === 2) {
                userWizardStep = 3;
            }
            console.log(`[wizard] userWizardStep set to ${userWizardStep}`);
            refreshDisplayedStep();
        }

        function applyWizardStep(step) {
            const primaryBtn = document.getElementById('primaryActionBtn');
            const helperText = document.getElementById('primaryHelperText');
            const ghostLink = document.getElementById('primaryGhostLink');
            const exportGrid = document.getElementById('primaryExportGrid');
            const exportHeader = document.getElementById('exportHeader');
            const container = document.getElementById('primaryActionContainer');
            const termsPanel = document.getElementById('termsPanel');
            const subtitleReviewPanel = document.getElementById('subtitleReviewPanel');
            const backBtn = document.getElementById('wizardBackBtn');

            if (!container) return;

            // Reset primary action container.
            if (primaryBtn) {
                primaryBtn.classList.remove('hidden');
                primaryBtn.disabled = false;
            }
            helperText?.classList.add('hidden');
            ghostLink?.classList.add('hidden');
            exportGrid?.classList.add('hidden');
            exportHeader?.classList.add('hidden');
            container.querySelector('#postTranscribeChoices')?.remove();

            // Hide all step scenes.
            if (termsPanel) termsPanel.classList.add('hidden');
            if (subtitleReviewPanel) subtitleReviewPanel.classList.add('hidden');

            // Compute upload-area state once based on currentVideoId.
            updateUploadAreaState(step);

            // Back/Next button visibility.
            if (backBtn) backBtn.classList.toggle('hidden', step <= 0);
            const nextBtn = document.getElementById('wizardNextBtn');
            if (nextBtn) {
                const canGoForward = userWizardStep !== null && displayedWizardStep < autoWizardStep;
                nextBtn.classList.toggle('hidden', !canGoForward);
            }

            switch (step) {
                case 0:
                    // Config review: pipeline buttons live in configScene; no primary action.
                    if (primaryBtn) primaryBtn.classList.add('hidden');
                    break;

                case 2:
                    // Processing / review step. For transcribe-only pipelines we show the
                    // subtitle timeline (or a placeholder) and the download option. For
                    // translation pipelines we show the terminology panel.
                    {
                        const currentStatus = currentVideoId ? lastKnownStatus : null;
                        const isProcessing = currentStatus && ['queued', 'extracting_audio', 'transcribing', 'analyzing', 'context_ready', 'glossary_extracting', 'translating'].includes(currentStatus);

                        if (targetPipelineMode === 'transcribe') {
                            if (subtitleReviewPanel) subtitleReviewPanel.classList.remove('hidden');
                            if (isProcessing) {
                                if (primaryBtn) primaryBtn.classList.add('hidden');
                            } else {
                                primaryBtn.textContent = 'Download Subtitles';
                                primaryBtn.className = 'w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white text-sm font-normal rounded-xl transition-colors tracking-wide';
                                primaryBtn.onclick = downloadTranscription;
                                primaryBtn.disabled = false;
                                // Load timeline if available.
                                if (currentVideoId) {
                                    fetch(`/videos/${currentVideoId}`)
                                        .then(r => r.json())
                                        .then(data => {
                                            if (data.segments) renderSubtitleTimeline(data.segments);
                                        })
                                        .catch(err => console.error('Failed to load transcription:', err));
                                }
                            }
                        } else {
                            // Terminology / translation pipeline.
                            if (termsPanel) termsPanel.classList.remove('hidden');
                            // Always load/render terms when showing this panel; terms may
                            // still exist after translation completes.
                            renderTerms();

                            const isTermsReady = currentStatus === 'terms_ready';
                            const isCompleted = currentStatus === 'completed';
                            if (isTermsReady) {
                                helperText?.classList.remove('hidden');
                                primaryBtn.textContent = 'Translate Subtitles';
                                primaryBtn.className = 'w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white text-sm font-normal rounded-xl transition-colors tracking-wide';
                                primaryBtn.onclick = translateVideo;
                                primaryBtn.disabled = false;
                            } else if (isCompleted) {
                                helperText?.classList.add('hidden');
                                primaryBtn.textContent = 'Continue to Subtitles';
                                primaryBtn.className = 'w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white text-sm font-normal rounded-xl transition-colors tracking-wide';
                                primaryBtn.onclick = () => {
                                    userWizardStep = null;
                                    refreshDisplayedStep();
                                };
                                primaryBtn.disabled = false;
                            } else if (isProcessing) {
                                helperText?.classList.add('hidden');
                                if (primaryBtn) primaryBtn.classList.add('hidden');
                            } else {
                                helperText?.classList.add('hidden');
                                if (primaryBtn) primaryBtn.classList.add('hidden');
                            }
                        }
                    }
                    break;

                case 3:
                    // Completed / export.
                    if (subtitleReviewPanel) subtitleReviewPanel.classList.remove('hidden');
                    if (primaryBtn) primaryBtn.classList.add('hidden');
                    exportGrid?.classList.remove('hidden');
                    exportHeader?.classList.remove('hidden');
                    if (exportHeader) exportHeader.textContent = 'Download Subtitles & Translations';
                    break;
            }
        }

        function updateButtonVisibility(status) {
            const normalizedStatus = status === 'awaiting_choice' ? 'transcribed' : status;
            // Backend progress updates only move autoWizardStep. The displayed step
            // respects userWizardStep when the user has explicitly navigated back.
            autoWizardStep = statusToStep(normalizedStatus);
            refreshDisplayedStep();
        }
        
        function updateContextBrief(data) {
            const container = document.getElementById('contextBriefContainer');
            const textEl = document.getElementById('contextBriefText');
            if (!container || !textEl) return;
            
            let brief = '';
            
            // Prefer explicit main_topic if available
            if (data.main_topic) {
                brief = data.main_topic;
            }
            // Try parsing context_analysis JSON (from polling)
            else if (data.context_analysis) {
                try {
                    const ca = typeof data.context_analysis === 'string' ? JSON.parse(data.context_analysis) : data.context_analysis;
                    if (ca.main_topic) brief = ca.main_topic;
                    else if (ca.translation_notes) brief = ca.translation_notes;
                } catch (e) { /* ignore parse errors */ }
            }
            // Fallback to style-guide metadata from WebSocket
            else if (data.domain || data.tone) {
                const parts = [];
                if (data.domain) parts.push(data.domain);
                if (data.tone) parts.push(`${data.tone} tone`);
                if (data.formality_level) parts.push(`formality ${data.formality_level}/5`);
                brief = parts.join(' • ');
            }
            
            if (brief) {
                textEl.textContent = brief;
                container.classList.remove('hidden');
            }
        }
        
        // HTTP polling fallback — used when the WebSocket can't connect or keeps
        // dropping. It must fully substitute for the WebSocket: not just show
        // status, but also drive the pipeline forward (auto-advance) and perform
        // the post-step UI transitions that normally come from job_complete messages.
        
        function fallbackToPolling(videoId) {
            // If we already have a working WebSocket, don't poll.
            if (ws && ws.readyState === WebSocket.OPEN) {
                return;
            }

            // Don't start duplicate polling loops
            if (fallbackPollInterval) return;

            log('Falling back to HTTP polling (WebSocket unavailable)', 'warning');
            console.log('[FALLBACK] Starting HTTP polling');
            
            fallbackPollCount = 0;
            lastPolledStatus = null;

            const poll = async () => {
                if (!currentVideoId || currentVideoId !== videoId) {
                    stopPolling();
                    return;
                }
                try {
                    const response = await fetch(`/videos/${videoId}`);
                    const data = await response.json();
                    // Treat the backend's "awaiting_choice" progress message as "transcribed"
                    // so the correct pipeline UI is shown even when polling.
                    if (data.status === 'awaiting_choice') {
                        data.status = 'transcribed';
                    }

                    const previousStatus = lastPolledStatus;
                    lastPolledStatus = data.status;

                    // Only update UI when the status actually changes, so live term edits
                    // aren't clobbered every 5 seconds during quiescent states.
                    if (data.status !== previousStatus) {
                        updateStatus(data);
                        updateContextBrief(data);
                    }

                    fallbackPollCount++;
                    if (fallbackPollCount % 5 === 0) {
                        log(`Fallback poll #${fallbackPollCount}: status=${data.status}`);
                    }

                    // Drive the pipeline forward on transitions.
                    if (data.status === 'transcribed' && previousStatus !== 'transcribed') {
                        isJobRunning = false;
                        hasStartedProcessing = false;
                        persistTranscription(currentVideoId);
                        if (targetPipelineMode === 'terminology') {
                            log('Auto-advancing to terminology analysis...');
                            updateButtonVisibility('transcribed');
                            setTimeout(() => analyzeVideo(), 0);
                        } else if (targetPipelineMode === 'subtitles') {
                            log('Auto-advancing to translation...');
                            updateButtonVisibility('transcribed');
                            setTimeout(() => skipAndTranslate(), 0);
                        } else {
                            updateButtonVisibility('transcribed');
                        }
                    } else if (data.status === 'terms_ready' && previousStatus !== 'terms_ready') {
                        isJobRunning = false;
                        hasStartedProcessing = false;
                        log('Analysis complete', 'success');
                        renderTerms();
                        updateButtonVisibility('terms_ready');
                    } else if (data.status === 'completed' && previousStatus !== 'completed') {
                        isJobRunning = false;
                        hasStartedProcessing = false;
                        log('Translation complete', 'success');
                        updateButtonVisibility('completed');
                        if (data.segments) renderSubtitleTimeline(data.segments);
                        persistTranslation(currentVideoId);
                    } else if (data.status === 'error') {
                        log('Processing failed', 'error');
                    }

                    // Stop polling once we reach a terminal state.
                    const terminalStatuses = ['terms_ready', 'completed', 'error'];
                    if (targetPipelineMode === 'transcribe') {
                        terminalStatuses.push('transcribed');
                    }
                    if (terminalStatuses.includes(data.status)) {
                        stopPolling();
                    }
                } catch (err) {
                    console.error('Fallback poll error:', err);
                }
            };

            // Run immediately, then every 5 seconds.
            poll();
            fallbackPollInterval = setInterval(poll, 5000);
        }

        function resetApp() {
            if (window.jobSession) window.jobSession.clearSession();

            currentVideoId = null;
            currentFileType = 'video';
            timelineHistory = [];
            currentTimelineSegments = [];
            currentJobId = null;
            isJobRunning = false;
            hasStartedProcessing = false;
            loggedCompletions.clear();
            targetPipelineMode = null;
            autoWizardStep = 0;
            userWizardStep = null;
            displayedWizardStep = 0;
            
            // Reset upload form
            const fileInputEl = document.getElementById('fileInput');
            if (fileInputEl) fileInputEl.value = '';
            const fileLabelEl = document.getElementById('fileLabel');
            if (fileLabelEl) fileLabelEl.textContent = 'Click to select file';
            const dropZoneEl = document.getElementById('dropZone');
            if (dropZoneEl) {
                dropZoneEl.classList.remove('border-blue-400', 'bg-blue-50');
                dropZoneEl.classList.remove('hidden');
            }
            const uploadFormReset = document.getElementById('uploadForm');
            if (uploadFormReset) uploadFormReset.classList.remove('hidden');
            const configSceneReset = document.getElementById('configScene');
            if (configSceneReset) configSceneReset.classList.remove('hidden');
            const uploadCompleteCardReset = document.getElementById('uploadCompleteCard');
            if (uploadCompleteCardReset) uploadCompleteCardReset.classList.add('hidden');
            
            // Hide status and action containers
            const statusCardReset = document.getElementById('statusCard');
            if (statusCardReset) statusCardReset.classList.add('hidden');
            const primaryActionReset = document.getElementById('primaryActionContainer');
            if (primaryActionReset) primaryActionReset.classList.add('hidden');
            const termsPanelReset = document.getElementById('termsPanel');
            if (termsPanelReset) termsPanelReset.classList.add('hidden');
            const subtitleReviewReset = document.getElementById('subtitleReviewPanel');
            if (subtitleReviewReset) subtitleReviewReset.classList.add('hidden');
            const timelineGridReset = document.getElementById('timelineCardGrid');
            if (timelineGridReset) timelineGridReset.innerHTML = '<div class="text-slate-400 dark:text-[#6B7280] text-center py-8">No subtitles available yet.</div>';
            
            // Reset step & segment counters
            const segCountReset = document.getElementById('segmentCount');
            if (segCountReset) segCountReset.textContent = '0 segments';
            const procCountReset = document.getElementById('processedCount');
            if (procCountReset) procCountReset.textContent = '0 processed';
            const stepReset = document.getElementById('currentStep');
            if (stepReset) {
                stepReset.textContent = 'Ready to process';
                stepReset.classList.remove('text-rose-300');
                stepReset.classList.add('text-slate-300');
            }
            
            // Clear logs and terms
            clearActivityLog();
            const termsTableReset = document.getElementById('termsTable');
            if (termsTableReset) termsTableReset.innerHTML = `
                <tr>
                    <td colspan="3" class="px-3 py-8 text-center text-slate-400 dark:text-[#6B7280] text-sm">
                        No terms extracted yet. Upload and process a video.
                    </td>
                </tr>
            `;
            
            // Disconnect WebSocket and stop polling
            disconnectWebSocket();
            stopPolling();
            
            // Clear URL param
            window.history.replaceState({}, document.title, window.location.pathname);
            
            log('New project ready. Upload a file to begin.', 'success');
        }

        async function waitForStatus(videoId, targetStatuses, timeoutMs = 120000) {
            const start = Date.now();
            const interval = 1500;
            while (Date.now() - start < timeoutMs) {
                const data = await fetchVideoData(videoId);
                if (!data) {
                    throw new Error('Could not fetch video status while waiting.');
                }
                if (data.status === 'error') {
                    throw new Error(data.error_message || 'Video processing failed.');
                }
                if (targetStatuses.includes(data.status)) {
                    return data;
                }
                await new Promise(resolve => setTimeout(resolve, interval));
            }
            throw new Error(`Timed out waiting for status: ${targetStatuses.join(', ')}`);
        }

        async function runPipeline(mode) {
            console.log(`[pipeline] runPipeline mode=${mode}`);
            if (!currentVideoId) {
                console.log('[pipeline] runPipeline aborted: no currentVideoId');
                return;
            }

            const data = await fetchVideoData(currentVideoId);
            if (!data) {
                log('Could not fetch current job data.', 'error');
                return;
            }

            const status = data.status === 'awaiting_choice' ? 'transcribed' : data.status;
            console.log(`[pipeline] runPipeline current status=${status}`);
            const transcribeDone = ['transcribed', 'analyzing', 'context_ready', 'glossary_extracting', 'terms_ready', 'translating', 'completed'];

            if (mode === 'transcribe') {
                const doneStatuses = ['transcribed', 'terms_ready', 'completed'];
                if (doneStatuses.includes(status)) {
                    log('Transcription already complete.', 'info');
                    updateButtonVisibility(status);
                    return;
                }
                await processFile();
                return;
            }

            if (mode === 'terminology') {
                if (!transcribeDone.includes(status)) {
                    log('Waiting for transcription to complete before terminology analysis...');
                    await waitForStatus(currentVideoId, transcribeDone);
                }
                const fresh = await fetchVideoData(currentVideoId);
                const freshStatus = fresh?.status === 'awaiting_choice' ? 'transcribed' : fresh?.status;
                console.log(`[pipeline] runPipeline terminology freshStatus=${freshStatus}`);
                if (
                    freshStatus === 'terms_ready' ||
                    freshStatus === 'translating' ||
                    freshStatus === 'completed'
                ) {
                    // Terms already extracted (or translation already running/complete).
                    // Stay on the terms panel and let the user click "Translate Subtitles".
                    log('Terminology already extracted.', 'info');
                    updateButtonVisibility(freshStatus);
                    return;
                }
                console.log('[pipeline] runPipeline terminology calling analyzeVideo');
                await analyzeVideo();
                return;
            }

            if (mode === 'subtitles') {
                if (!transcribeDone.includes(status)) {
                    log('Waiting for transcription to complete before translation...');
                    await waitForStatus(currentVideoId, transcribeDone);
                }
                const fresh = await fetchVideoData(currentVideoId);
                const freshStatus = fresh?.status === 'awaiting_choice' ? 'transcribed' : fresh?.status;
                console.log(`[pipeline] runPipeline subtitles freshStatus=${freshStatus}`);
                if (freshStatus === 'completed' || freshStatus === 'translating') {
                    log(freshStatus === 'completed' ? 'Translation already complete.' : 'Translation already in progress.', 'info');
                    updateButtonVisibility(freshStatus);
                    return;
                }
                console.log('[pipeline] runPipeline subtitles calling skipAndTranslate');
                await skipAndTranslate();
                return;
            }

            log(`Unknown pipeline mode: ${mode}`, 'error');
        }

        async function continueWithConfigCheck(mode) {
            console.log(`[pipeline] continueWithConfigCheck mode=${mode} currentVideoId=${currentVideoId}`);
            const sourceLangSelect = document.getElementById('sourceLanguage');
            const targetLangSelect = document.getElementById('targetLanguage');
            const sourceLang = window.termsubSourceLanguageTom
                ? window.termsubSourceLanguageTom.getValue()
                : (sourceLangSelect ? sourceLangSelect.value : 'auto');
            const targetLang = window.termsubTargetLanguageTom
                ? window.termsubTargetLanguageTom.getValue()
                : (targetLangSelect ? targetLangSelect.value : '');

            const session = window.jobSession ? window.jobSession.loadSession() : null;
            const saved = session?.config || {};

            const sourceChanged = sourceLang && sourceLang !== (saved.sourceLang || 'auto');
            const targetChanged = targetLang && targetLang !== saved.targetLang;

            if (sourceChanged || targetChanged) {
                try {
                    const patchBody = {};
                    if (sourceChanged) patchBody.source_language = sourceLang;
                    if (targetChanged) patchBody.target_language = targetLang;

                    log('Updating video configuration...');
                    const response = await fetch(`/videos/${currentVideoId}/config`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(patchBody),
                    });
                    if (!response.ok) {
                        const err = await response.json().catch(() => ({}));
                        throw new Error(err.detail || 'Failed to update video config.');
                    }
                    const updated = await response.json();
                    log(`Updated configuration: ${updated.source_language || 'auto'} → ${updated.target_language}`, 'success');

                    if (window.jobSession) {
                        window.jobSession.saveSession({
                            jobId: currentVideoId,
                            config: {
                                ...saved,
                                sourceLang: updated.source_language || 'auto',
                                targetLang: updated.target_language,
                            },
                        });
                    }
                } catch (err) {
                    log('Config update failed: ' + err.message, 'error');
                    showToast('Could not update language settings.', 'error');
                    return;
                }
            }

            await continuePipeline(mode);
        }

        async function continuePipeline(mode) {
            const sourceLangSelect = document.getElementById('sourceLanguage');
            const targetLangSelect = document.getElementById('targetLanguage');

            // Read from Tom Select instances when available, falling back to the native selects.
            const targetLang = window.termsubTargetLanguageTom && typeof window.termsubTargetLanguageTom.getValue === 'function'
                ? window.termsubTargetLanguageTom.getValue()
                : (targetLangSelect ? targetLangSelect.value : '');

            console.log(`[pipeline] continuePipeline mode=${mode} targetLang=${targetLang}`);

            if (!isAuthenticated()) {
                showAuthView('standard', 'signup');
                log('Please log in, sign up, or provide an API key to continue.', 'warning');
                showToast('Please log in or provide an API key to continue', 'warning');
                return;
            }

            if (mode !== 'transcribe' && !targetLang) {
                const warningEl = document.getElementById('languageWarning');
                if (warningEl) warningEl.classList.remove('hidden');
                if (targetLangSelect) {
                    targetLangSelect.classList.add('border-red-500', 'focus:ring-red-500', 'focus:border-red-500');
                    targetLangSelect.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                log('Continue blocked: target language is required.', 'warning');
                showToast('Please select a target language.', 'warning');
                return;
            }

            targetPipelineMode = mode;
            userWizardStep = null; // user continued forward; release back-lock
            log(`Continuing ${mode} pipeline with uploaded file...`);
            setPipelineButtonsDisabled(true);
            try {
                await runPipeline(mode);
            } finally {
                setPipelineButtonsDisabled(false);
            }
        }

        // Pipeline entry point: validate inputs, set mode, upload, then auto-start processing.
        async function startPipeline(mode) {
            const fileInput = document.getElementById('fileInput');
            const targetLangSelect = document.getElementById('targetLanguage');

            console.log(`[pipeline] startPipeline mode=${mode} file=${fileInput?.files?.[0]?.name || 'none'}`);

            if (!isAuthenticated()) {
                showAuthView('standard', 'signup');
                log('Please log in, sign up, or provide an API key to upload a file.', 'warning');
                showToast('Please log in or provide an API key to upload', 'warning');
                return;
            }

            if (!fileInput.files || !fileInput.files[0]) {
                showToast('Please select a file first', 'warning');
                return;
            }

            // Transcribe-only does not need a target language
            if (mode !== 'transcribe' && (!targetLangSelect || !targetLangSelect.value)) {
                const warningEl = document.getElementById('languageWarning');
                if (warningEl) warningEl.classList.remove('hidden');
                if (targetLangSelect) {
                    targetLangSelect.classList.add('border-red-500', 'focus:ring-red-500', 'focus:border-red-500');
                    targetLangSelect.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                log('Upload blocked: target language is required.', 'warning');
                return;
            }

            targetPipelineMode = mode;
            autoWizardStep = 0;
            userWizardStep = null;
            displayedWizardStep = 0;
            log(`Starting ${mode} pipeline...`);
            setPipelineButtonsDisabled(true);
            try {
                await uploadFile(mode);
            } finally {
                setPipelineButtonsDisabled(false);
            }
        }

        // Upload handler
        async function uploadFile(mode) {
            if (!isAuthenticated()) {
                showAuthView('standard', 'signup');
                log('Please log in, sign up, or provide an API key to upload a file.', 'warning');
                showToast('Please log in or provide an API key to upload', 'warning');
                return;
            }

            // Ensure the requested pipeline mode is recorded
            if (mode) targetPipelineMode = mode;

            const fileInput = document.getElementById('fileInput');
            const targetLangSelect = document.getElementById('targetLanguage');
            const sourceLangSelect = document.getElementById('sourceLanguage');
            
            if (!fileInput.files || !fileInput.files[0]) {
                return;
            }
            
            // Client-side validation: target language is required for translation pipelines only
            if (targetPipelineMode !== 'transcribe' && (!targetLangSelect || !targetLangSelect.value)) {
                const warningEl = document.getElementById('languageWarning');
                if (warningEl) warningEl.classList.remove('hidden');
                if (targetLangSelect) {
                    targetLangSelect.classList.add('border-red-500', 'focus:ring-red-500', 'focus:border-red-500');
                    targetLangSelect.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
                log('Upload blocked: target language is required.', 'warning');
                return;
            }

            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            // Transcribe-only does not need a real target language, but the backend
            // requires a non-empty value. Re-use the source language as a placeholder.
            const effectiveTargetLanguage = targetPipelineMode === 'transcribe'
                ? (sourceLangSelect.value || 'auto')
                : targetLangSelect.value;
            formData.append('target_language', effectiveTargetLanguage);
            formData.append('source_language', sourceLangSelect.value);

            log('Uploading file...');
            
            try {
                const response = await fetch('/videos/upload', {
                    method: 'POST',
                    body: formData
                });
                
                if (!response.ok) {
                    // Try to get detailed error message from response
                    let errorDetail = 'Upload failed';
                    try {
                        const errorData = await response.json();
                        errorDetail = errorData.detail || `HTTP ${response.status}: ${response.statusText}`;
                    } catch (e) {
                        errorDetail = `HTTP ${response.status}: ${response.statusText}`;
                    }
                    throw new Error(errorDetail);
                }
                
                const data = await response.json();
                currentVideoId = data.id;
                currentFileType = data.content_type || 'video';
                
                // Set Project Metadata
                const projectTitleEl = document.getElementById('projectTitle');
                if (projectTitleEl) projectTitleEl.textContent = data.filename || 'Untitled Project';
                
                const projectTypeEl = document.getElementById('projectType');
                if (projectTypeEl) projectTypeEl.innerHTML = 
                    `<i class="fa-solid ${currentFileType === 'text' ? 'fa-file-lines' : 'fa-video'} mr-1"></i>${currentFileType === 'text' ? 'Text File' : 'Video'}`;
                
                const sourceLangSel = document.getElementById('sourceLanguage');
                const sourceLang = sourceLangSel && sourceLangSel.value === 'auto' ? 'Auto' : 
                    (sourceLangSel ? sourceLangSel.value.toUpperCase() : 'Auto');
                const targetLangSel = document.getElementById('targetLanguage');
                const targetLang = targetLangSel ? targetLangSel.value.toUpperCase() : '';
                const projectLangsEl = document.getElementById('projectLangs');
                if (projectLangsEl) {
                    projectLangsEl.textContent = targetPipelineMode === 'transcribe'
                        ? `${sourceLang} (transcribe only)`
                        : `${sourceLang} → ${targetLang}`;
                }
                
                const projectIdEl = document.getElementById('projectId');
                if (projectIdEl) projectIdEl.textContent = currentVideoId.substring(0, 8);
                
                const statusCardEl = document.getElementById('statusCard');
                if (statusCardEl) statusCardEl.classList.remove('hidden');
                const primaryActionEl = document.getElementById('primaryActionContainer');
                if (primaryActionEl) primaryActionEl.classList.remove('hidden');
                
                // Swap upload form for compact filename card
                const uploadFormEl = document.getElementById('uploadForm');
                if (uploadFormEl) uploadFormEl.classList.add('hidden');
                const configSceneEl = document.getElementById('configScene');
                if (configSceneEl) configSceneEl.classList.add('hidden');
                const uploadCompleteCardEl = document.getElementById('uploadCompleteCard');
                if (uploadCompleteCardEl) uploadCompleteCardEl.classList.remove('hidden');
                const uploadedFilenameEl = document.getElementById('uploadedFilename');
                if (uploadedFilenameEl) uploadedFilenameEl.textContent = data.filename || 'Untitled Project';
                
                // Persist session so a refresh resumes from this job.
                const terminologyCheckbox = document.getElementById('reviewTerminologyCheckbox');
                if (window.jobSession) {
                    window.jobSession.saveConfig(currentVideoId, {
                        sourceLang: sourceLangSel ? sourceLangSel.value : 'auto',
                        targetLang: targetLangSel ? targetLangSel.value : '',
                        terminology: terminologyCheckbox ? terminologyCheckbox.checked : true,
                        videoName: data.filename || 'Untitled Project',
                        mode: targetPipelineMode || 'translate',
                    });
                }

                log('Upload complete: ' + data.filename, 'success');

                updateStatus({ status: 'uploaded', progress_percent: 0 });

                // Auto-start transcription for every pipeline path
                processFile();

            } catch (err) {
                const errorMsg = err.message || 'Upload failed';
                log('Upload failed: ' + errorMsg, 'error');
            }
        }

        function setPipelineButtonsDisabled(disabled) {
            const translateSubtitlesBtn = document.getElementById('translateSubtitlesBtn');
            const originalSubtitlesBtn = document.getElementById('originalSubtitlesBtn');
            if (translateSubtitlesBtn) translateSubtitlesBtn.disabled = disabled;
            if (originalSubtitlesBtn) originalSubtitlesBtn.disabled = disabled;
        }

        // Process file handler (handles both video transcription and text parsing)
        async function processFile() {
            if (!currentVideoId) return;

            // Target language is only required for pipelines that translate
            if (targetPipelineMode !== 'transcribe') {
                const targetLangSelect = document.getElementById('targetLanguage');
                if (!targetLangSelect || !targetLangSelect.value) {
                    const warningEl = document.getElementById('languageWarning');
                    if (warningEl) warningEl.classList.remove('hidden');
                    if (targetLangSelect) {
                        targetLangSelect.classList.add('border-red-500', 'focus:ring-red-500', 'focus:border-red-500');
                        targetLangSelect.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                    return;
                }
            }

            // Collapse config scene once processing starts; show the compact upload card.
            updateUploadAreaState(2);

            // Reset per-job tracking state.
            currentJobId = null;
            isJobRunning = true;
            hasStartedProcessing = false;
            // Keep the wizard step state; backend updates will advance autoWizardStep.

            const isTextFile = currentFileType === 'text';

            log(isTextFile ? 'Starting text parsing...' : 'Starting OpenAI Cloud transcription...');

            try {
                const response = await fetch(`/videos/${currentVideoId}/transcribe?method=whisper&provider=openai`, {
                    method: 'POST'
                });

                if (!response.ok) {
                    let errorMessage = isTextFile ? 'Text parsing failed' : 'Transcription failed';
                    try {
                        const errorData = await response.json();
                        errorMessage = errorData.detail || errorMessage;
                    } catch (e) {
                        // response wasn't JSON — keep default
                    }
                    throw new Error(errorMessage);
                }

                const data = await response.json();
                if (data.job_id) {
                    currentJobId = data.job_id;
                }

                // Do not update the UI to "transcribed" here. The real completion
                // (and the next pipeline step) is driven by WebSocket job_complete
                // or the HTTP polling fallback.
                await connectWebSocket(currentVideoId);

            } catch (err) {
                log((isTextFile ? 'Parsing' : 'Transcription') + ' failed: ' + err.message, 'error');
            }
        }

        // Analyze handler (Multi-Agent Step 1)
        async function analyzeVideo() {
            if (!currentVideoId || isJobRunning) return;
            
            // Reset per-job tracking state.
            currentJobId = null;
            isJobRunning = true;
            hasStartedProcessing = false;
            userWizardStep = null; // releasing back-lock when starting a forward step
            
            log('Starting Multi-Agent Analysis (Director + Glossary)...');
            log('Director Agent: Analyzing context and style...');
            
            try {
                const response = await fetch(`/videos/${currentVideoId}/analyze`, {
                    method: 'POST'
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Analysis failed');
                }
                
                const data = await response.json();
                if (data.job_id) {
                    currentJobId = data.job_id;
                }

                // The real completion and next UI state are driven by WebSocket.
            } catch (err) {
                isJobRunning = false;
                log('Analysis failed: ' + err.message, 'error');
            }
        }

        // Translate handler (Multi-Agent Step 2)
        async function translateVideo() {
            if (!currentVideoId || isJobRunning) return;
            
            // Reset per-job tracking state.
            currentJobId = null;
            isJobRunning = true;
            hasStartedProcessing = false;
            userWizardStep = null; // releasing back-lock when starting a forward step
            
            log('Starting OpenAI Translator Agent...');
            log('Using sliding window translation with glossary constraints');
            
            try {
                const response = await fetch(`/videos/${currentVideoId}/translate`, {
                    method: 'POST'
                });
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Translation failed');
                }
                
                const data = await response.json();
                if (data.job_id) {
                    currentJobId = data.job_id;
                }

                // The real completion and next UI state are driven by WebSocket.
            } catch (err) {
                isJobRunning = false;
                log('Translation failed: ' + err.message, 'error');
            }
        }

        async function skipAndTranslate() {
            if (!currentVideoId || isJobRunning) return;
            
            console.log(`[pipeline] skipAndTranslate called for ${currentVideoId}`);
            
            // Reset per-job tracking state.
            currentJobId = null;
            isJobRunning = true;
            hasStartedProcessing = false;
            userWizardStep = null; // releasing back-lock when starting a forward step
            
            log('Skipping terminology review and starting translation...');
            
            try {
                const response = await fetch(`/videos/${currentVideoId}/translate-direct`, {
                    method: 'POST'
                });
                
                console.log(`[pipeline] skipAndTranslate response status=${response.status}`);
                
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Translation failed');
                }
                
                const data = await response.json();
                if (data.job_id) {
                    currentJobId = data.job_id;
                }

                // The real completion and next UI state are driven by WebSocket.
            } catch (err) {
                isJobRunning = false;
                console.error('[pipeline] skipAndTranslate error:', err);
                log('Translation failed: ' + err.message, 'error');
            }
        }

        // Helper: extract filename from Content-Disposition header
        function getFilenameFromHeader(response, fallback) {
            const header = response.headers.get('Content-Disposition');
            if (!header) return fallback;
            const match = header.match(/filename="?([^"]+)"?/);
            return match ? match[1] : fallback;
        }

        // Ensure any pending segment edit is saved before we trigger a download.
        async function flushPendingEdits() {
            const active = document.activeElement;
            if (
                active &&
                (active.classList.contains('timecode-input') ||
                    active.getAttribute('contenteditable') === 'true')
            ) {
                active.blur();
            }

            const start = Date.now();
            while (isSavingSegment && Date.now() - start < 3000) {
                await new Promise(resolve => setTimeout(resolve, 50));
            }
        }

        // Generic export handler
        async function exportFormat(format) {
            if (!currentVideoId) return;

            await flushPendingEdits();

            const formatNames = {
                'srt': 'SRT',
                'vtt': 'WebVTT',
                'txt': 'Text',
                'json': 'JSON'
            };
            
            try {
                const response = await fetch(`/export/${currentVideoId}/${format}`);
                
                if (!response.ok) throw new Error('Export failed');
                
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.style.display = 'none';
                const fallback = `translation_${currentVideoId.substring(0, 8)}.${format}`;
                a.download = getFilenameFromHeader(response, fallback);
                document.body.appendChild(a);
                a.click();

                // Give the browser a moment to start the download before
                // cleaning up the anchor and revoking the blob URL.
                setTimeout(() => {
                    a.remove();
                    window.URL.revokeObjectURL(url);
                }, 1000);

                log(`${formatNames[format]} exported`, 'success');
                markDownloadedSession();
                
            } catch (err) {
                log('Export failed: ' + err.message, 'error');
            }
        }

        // Download original transcription handler
        async function downloadTranscription() {
            if (!currentVideoId) return;

            await flushPendingEdits();

            try {
                const response = await fetch(`/export/${currentVideoId}/transcription`);
                
                if (!response.ok) throw new Error('Download failed');
                
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.style.display = 'none';
                const fallback = `transcription_${currentVideoId.substring(0, 8)}.srt`;
                a.download = getFilenameFromHeader(response, fallback);
                document.body.appendChild(a);
                a.click();

                // Delay cleanup so the browser has time to start the download.
                setTimeout(() => {
                    a.remove();
                    window.URL.revokeObjectURL(url);
                }, 1000);

                log('Transcription downloaded', 'success');
                markDownloadedSession();
                
            } catch (err) {
                log('Download failed: ' + err.message, 'error');
            }
        }

        // Event listeners
        document.addEventListener('DOMContentLoaded', () => {
            // Auth: wire up modal UI
            const standardAuthForm = document.getElementById('standardAuthForm');
            const byokAuthForm = document.getElementById('byokAuthForm');
            const standardTab = document.getElementById('authTabStandard');
            const byokTab = document.getElementById('authTabByok');
            const authCloseBtn = document.getElementById('authCloseBtn');
            const authModeToggleBtn = document.getElementById('authModeToggleBtn');
            const logoutBtn = document.getElementById('logoutBtn');

            if (standardTab) standardTab.addEventListener('click', () => setAuthTab('standard'));
            if (byokTab) byokTab.addEventListener('click', () => setAuthTab('byok'));
            if (standardAuthForm) standardAuthForm.addEventListener('submit', handleStandardAuthSubmit);
            if (byokAuthForm) byokAuthForm.addEventListener('submit', handleByokSubmit);
            if (authModeToggleBtn) authModeToggleBtn.addEventListener('click', () => {
                setStandardMode(currentStandardMode === 'login' ? 'signup' : 'login');
            });
            if (authCloseBtn) authCloseBtn.addEventListener('click', showMainApp);
            if (logoutBtn) logoutBtn.addEventListener('click', logout);

            // Forgot / reset password
            const authForgotPasswordBtn = document.getElementById('authForgotPasswordBtn');
            const forgotPasswordForm = document.getElementById('forgotPasswordForm');
            const forgotPasswordBackBtn = document.getElementById('forgotPasswordBackBtn');
            const resetPasswordForm = document.getElementById('resetPasswordForm');
            if (authForgotPasswordBtn) authForgotPasswordBtn.addEventListener('click', showForgotPassword);
            if (forgotPasswordForm) forgotPasswordForm.addEventListener('submit', handleForgotPasswordSubmit);
            if (forgotPasswordBackBtn) forgotPasswordBackBtn.addEventListener('click', () => setAuthSubview('form'));
            if (resetPasswordForm) resetPasswordForm.addEventListener('submit', handleResetPasswordSubmit);

            // Show / hide password toggles
            setupPasswordToggles();

            // User menu dropdown
            const userMenuBtn = document.getElementById('userMenuBtn');
            const userMenuDropdown = document.getElementById('userMenuDropdown');
            if (userMenuBtn && userMenuDropdown) {
                userMenuBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    userMenuDropdown.classList.toggle('hidden');
                });
                document.addEventListener('click', (e) => {
                    if (!userMenuBtn.contains(e.target) && !userMenuDropdown.contains(e.target)) {
                        userMenuDropdown.classList.add('hidden');
                    }
                });
            }

            // My Jobs modal
            const myJobsBtn = document.getElementById('myJobsBtn');
            const myJobsModal = document.getElementById('myJobsModal');
            const myJobsModalClose = document.getElementById('myJobsModalClose');
            if (myJobsBtn) myJobsBtn.addEventListener('click', openMyJobsModal);
            if (myJobsModalClose) myJobsModalClose.addEventListener('click', closeMyJobsModal);
            if (myJobsModal) {
                myJobsModal.addEventListener('click', (e) => {
                    if (e.target === myJobsModal) closeMyJobsModal();
                });
            }

            // Profile modal
            const profileBtn = document.getElementById('profileBtn');
            const profileModal = document.getElementById('profileModal');
            const profileModalClose = document.getElementById('profileModalClose');
            if (profileBtn) profileBtn.addEventListener('click', openProfileModal);
            if (profileModalClose) profileModalClose.addEventListener('click', closeProfileModal);
            if (profileModal) {
                profileModal.addEventListener('click', (e) => {
                    if (e.target === profileModal) closeProfileModal();
                });
            }

            // Profile forms
            const profilePreferencesForm = document.getElementById('profileSavePreferencesBtn');
            if (profilePreferencesForm) profilePreferencesForm.addEventListener('click', savePreferences);
            const profileSaveApiModeBtn = document.getElementById('profileSaveApiModeBtn');
            if (profileSaveApiModeBtn) profileSaveApiModeBtn.addEventListener('click', saveApiKeyMode);
            const profileEmailForm = document.getElementById('profileEmailForm');
            if (profileEmailForm) profileEmailForm.addEventListener('submit', updateEmail);
            const profilePasswordForm = document.getElementById('profilePasswordForm');
            if (profilePasswordForm) profilePasswordForm.addEventListener('submit', changePassword);
            const profileLogoutAllBtn = document.getElementById('profileLogoutAllBtn');
            if (profileLogoutAllBtn) profileLogoutAllBtn.addEventListener('click', logoutAllSessions);
            const profileDeleteAccountBtn = document.getElementById('profileDeleteAccountBtn');
            if (profileDeleteAccountBtn) profileDeleteAccountBtn.addEventListener('click', openDeleteAccountModal);

            // API mode toggle shows/hides key input
            const profileModeStandard = document.getElementById('profileModeStandard');
            const profileModeByok = document.getElementById('profileModeByok');
            const profileByokKeyContainer = document.getElementById('profileByokKeyContainer');
            function updateByokKeyVisibility() {
                if (profileByokKeyContainer) {
                    profileByokKeyContainer.classList.toggle('hidden', !(profileModeByok && profileModeByok.checked));
                }
            }
            if (profileModeStandard) profileModeStandard.addEventListener('change', updateByokKeyVisibility);
            if (profileModeByok) profileModeByok.addEventListener('change', updateByokKeyVisibility);

            // Delete account modal
            const deleteAccountModal = document.getElementById('deleteAccountModal');
            const deleteAccountCancel = document.getElementById('deleteAccountCancel');
            const deleteAccountForm = document.getElementById('deleteAccountForm');
            if (deleteAccountCancel) deleteAccountCancel.addEventListener('click', closeDeleteAccountModal);
            if (deleteAccountForm) deleteAccountForm.addEventListener('submit', deleteAccount);
            if (deleteAccountModal) {
                deleteAccountModal.addEventListener('click', (e) => {
                    if (e.target === deleteAccountModal) closeDeleteAccountModal();
                });
            }

            // Usage pagination
            const profileUsagePrev = document.getElementById('profileUsagePrev');
            const profileUsageNext = document.getElementById('profileUsageNext');
            if (profileUsagePrev) {
                profileUsagePrev.addEventListener('click', () => {
                    if (profileUsageSkip > 0) {
                        profileUsageSkip -= profileUsageLimit;
                        loadProfileUsage();
                    }
                });
            }
            if (profileUsageNext) {
                profileUsageNext.addEventListener('click', () => {
                    if (profileUsageSkip + profileUsageLimit < profileUsageTotal) {
                        profileUsageSkip += profileUsageLimit;
                        loadProfileUsage();
                    }
                });
            }

            const loginBtn = document.getElementById('loginBtn');
            if (loginBtn) loginBtn.addEventListener('click', () => {
                showAuthView('standard', 'signup');
            });

            const resendVerifyBtn = document.getElementById('resendVerifyBtn');
            const recheckVerifyBtn = document.getElementById('recheckVerifyBtn');
            if (resendVerifyBtn) resendVerifyBtn.addEventListener('click', resendVerificationEmail);
            if (recheckVerifyBtn) recheckVerifyBtn.addEventListener('click', recheckVerification);

            // Close modal when clicking the backdrop
            const authView = document.getElementById('authView');
            if (authView) {
                authView.addEventListener('click', (e) => {
                    if (e.target === authView) showMainApp();
                });
            }

            // Close modal with Escape key.
            document.addEventListener('keydown', (e) => {
                if (e.key !== 'Escape') return;
                if (deleteAccountModal && !deleteAccountModal.classList.contains('hidden')) {
                    closeDeleteAccountModal();
                    return;
                }
                if (profileModal && !profileModal.classList.contains('hidden')) {
                    closeProfileModal();
                    return;
                }
                if (authView && !authView.classList.contains('hidden')) {
                    showMainApp();
                }
            });

            // Handle email verification links clicked from the user's inbox.
            // Supports both legacy ?token= and welcome-email ?verify_token= params.
            (async () => {
                const params = new URLSearchParams(window.location.search);
                const path = window.location.pathname;

                // Password reset links use /?reset_token=...
                const resetToken = params.get('reset_token');
                if (resetToken) {
                    showResetPassword(resetToken);
                    window.history.replaceState({}, '', '/');
                    return;
                }

                const verifyToken = params.get('verify_token') || params.get('token');
                if (verifyToken) {
                    try {
                        const response = await fetch(`/api/auth/verify?token=${encodeURIComponent(verifyToken)}`);
                        if (response.ok) {
                            showToast('Email verified successfully', 'success');
                            // The backend sets the HttpOnly auth cookie; refresh the session.
                            const loaded = await loadUser();
                            if (loaded) {
                                showMainApp();
                                window.history.replaceState({}, '', '/');
                                return;
                            }
                            // Otherwise fall through to login prompt.
                            showAuthView('standard', 'login');
                        } else {
                            const data = await response.json().catch(() => ({}));
                            showToast(data.detail || 'Verification link is invalid or expired', 'error');
                            showAuthView('standard', 'login');
                        }
                    } catch (err) {
                        console.error('Verification failed:', err);
                        showToast('Verification failed. Please try logging in.', 'error');
                        showAuthView('standard', 'login');
                    }
                    // Remove token params from URL so a refresh doesn't re-verify.
                    params.delete('verify_token');
                    params.delete('token');
                    const newUrl = params.toString()
                        ? `${window.location.pathname}?${params.toString()}`
                        : window.location.pathname;
                    window.history.replaceState({}, '', newUrl);
                }
            })();

            // Determine initial view based on the HttpOnly cookie or BYOK API key.
            (async () => {
                const loaded = await loadUser();
                if (!loaded) {
                    updateUserDisplay();
                }
            })();

            // Language dropdown population with Tom Select
            const sourceLanguageSelect = document.getElementById('sourceLanguage');
            const targetLanguageSelect = document.getElementById('targetLanguage');

            function buildNativeLanguageOptions() {
                const formatOption = (lang) =>
                    `<option value="${lang.code}">${lang.name} — ${lang.nativeName}</option>`;

                return SUPPORTED_LANGUAGES.map(formatOption).join('');
            }

            function initLanguageDropdown(selectElement, firstOption, initialValue) {
                if (!selectElement) return null;

                const nativeOptions = buildNativeLanguageOptions();
                const disabledAttr = firstOption.disabled ? 'disabled' : '';
                const selectedAttr = firstOption.selected ? 'selected' : '';
                selectElement.innerHTML =
                    `<option value="${firstOption.value}" ${disabledAttr} ${selectedAttr}>${firstOption.label}</option>` +
                    nativeOptions;
                selectElement.value = initialValue;

                if (typeof TomSelect === 'undefined') {
                    // Fallback to native select if Tom Select is not loaded.
                    return selectElement;
                }

                const options = [];
                const optgroups = [];

                // First option (Auto-detect / placeholder)
                options.push({
                    code: firstOption.value,
                    display: firstOption.label,
                    name: firstOption.label,
                    nativeName: '',
                    group: 'top',
                });
                optgroups.push({ value: 'top', label: '' });

                // All languages in one alphabetical list (searchable by name or native name)
                SUPPORTED_LANGUAGES.forEach((lang) => {
                    options.push({
                        code: lang.code,
                        display: `${lang.name} — ${lang.nativeName}`,
                        name: lang.name,
                        nativeName: lang.nativeName,
                        group: 'all',
                    });
                });
                optgroups.push({ value: 'all', label: 'Languages' });

                const tom = new TomSelect(selectElement, {
                    options,
                    optgroups,
                    optgroupField: 'group',
                    valueField: 'code',
                    labelField: 'display',
                    searchField: ['name', 'nativeName'],
                    placeholder: firstOption.label,
                    allowEmptyOption: true,
                    sortField: [{ field: '$order' }],
                    render: {
                        option: (data, escape) =>
                            `<div class="py-1 px-2">${escape(data.display)}</div>`,
                        item: (data, escape) => `<div>${escape(data.display)}</div>`,
                    },
                });

                tom.setValue(initialValue);

                // Keep the underlying native select synchronized so legacy
                // code that reads selectElement.value continues to work.
                tom.on('change', (value) => {
                    selectElement.value = value || '';
                });

                return tom;
            }

            const sourceTom = initLanguageDropdown(
                sourceLanguageSelect,
                { value: 'auto', label: 'Auto-detect' },
                'auto'
            );
            const targetTom = initLanguageDropdown(
                targetLanguageSelect,
                { value: '', label: 'Select target language...', disabled: true, selected: true },
                ''
            );

            // Expose the underlying selects and Tom Select instances for code that
            // expects them (including session restore).
            window.termsubSourceLanguage = sourceLanguageSelect;
            window.termsubTargetLanguage = targetLanguageSelect;
            window.termsubSourceLanguageTom = sourceTom;
            window.termsubTargetLanguageTom = targetTom;

            // --- Help panel toggle ---
            const helpBtn = document.getElementById('helpBtn');
            const helpCloseBtn = document.getElementById('helpCloseBtn');
            const howToPanel = document.getElementById('howToPanel');

            function toggleHelpPanel(show) {
                if (!howToPanel) return;
                const willShow = show === undefined ? howToPanel.classList.contains('hidden') : show;
                howToPanel.classList.toggle('hidden', !willShow);
            }

            if (helpBtn && howToPanel) {
                helpBtn.addEventListener('click', () => toggleHelpPanel());
            }
            if (helpCloseBtn && howToPanel) {
                helpCloseBtn.addEventListener('click', () => toggleHelpPanel(false));
            }
            // Close when clicking outside the panel or the help button
            document.addEventListener('click', (e) => {
                if (!howToPanel || howToPanel.classList.contains('hidden')) return;
                if (!howToPanel.contains(e.target) && e.target !== helpBtn && !helpBtn?.contains(e.target)) {
                    toggleHelpPanel(false);
                }
            });

            // --- Activity Log Collapse ---
            const activityLogToggle = document.getElementById('activityLogToggle');
            const activityLogContainer = document.getElementById('activityLogContainer');
            if (activityLogToggle && activityLogContainer) {
                activityLogToggle.addEventListener('click', () => {
                    const collapsed = activityLogContainer.classList.toggle('activity-log-collapsed');
                    activityLogToggle.setAttribute('aria-expanded', (!collapsed).toString());
                    if (!collapsed) {
                        // Expand downward: scroll the fully-open log into view so it
                        // clearly opens below the toggle instead of appearing to push
                        // earlier content upward out of sight.
                        setTimeout(() => {
                            activityLogContainer.scrollIntoView({ behavior: 'smooth', block: 'end' });
                        }, 50);
                    }
                });
            }

            // Clicking the "Open activity log" link in the status line expands the log
            const currentStepEl = document.getElementById('currentStep');
            if (currentStepEl) {
                currentStepEl.addEventListener('click', (e) => {
                    if (e.target.matches('[data-open-activity-log]')) {
                        e.preventDefault();
                        expandActivityLog();
                    }
                });
            }

            // File input
            const fileInput = document.getElementById('fileInput');
            const fileLabel = document.getElementById('fileLabel');
            
            fileInput.addEventListener('change', () => {
                if (fileInput.files && fileInput.files[0]) {
                    const file = fileInput.files[0];
                    fileLabel.textContent = file.name;
                    document.getElementById('dropZone').classList.add('border-blue-400', 'bg-blue-50');
                    
                    // Detect file type for downstream pipeline text
                    const isTextFile = file.name.toLowerCase().endsWith('.txt');
                    currentFileType = isTextFile ? 'text' : 'video';
                }
            });
            
            // Drag & Drop handlers
            const dropZone = document.getElementById('dropZone');
            if (dropZone) {
                ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                    dropZone.addEventListener(eventName, (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                    }, false);
                });
                
                ['dragenter', 'dragover'].forEach(eventName => {
                    dropZone.addEventListener(eventName, () => {
                        dropZone.classList.add('border-blue-400', 'bg-blue-50', 'dark:bg-blue-900/20');
                    }, false);
                });
                
                ['dragleave', 'drop'].forEach(eventName => {
                    dropZone.addEventListener(eventName, () => {
                        dropZone.classList.remove('border-blue-400', 'bg-blue-50', 'dark:bg-blue-900/20');
                    }, false);
                });
                
                dropZone.addEventListener('drop', (e) => {
                    const files = e.dataTransfer.files;
                    if (files && files.length > 0) {
                        const dt = new DataTransfer();
                        dt.items.add(files[0]);
                        fileInput.files = dt.files;
                        fileInput.dispatchEvent(new Event('change'));
                    }
                }, false);
            }
            
            // Target language change: clear validation warning
            const targetLangSelect = document.getElementById('targetLanguage');
            if (targetLangSelect) {
                targetLangSelect.addEventListener('change', () => {
                    if (targetLangSelect.value) {
                        const warningEl = document.getElementById('languageWarning');
                        if (warningEl) warningEl.classList.add('hidden');
                        targetLangSelect.classList.remove('border-red-500', 'focus:ring-red-500', 'focus:border-red-500');
                    }
                });
            }

            // Pipeline buttons
            const translateSubtitlesBtn = document.getElementById('translateSubtitlesBtn');
            const originalSubtitlesBtn = document.getElementById('originalSubtitlesBtn');

            translateSubtitlesBtn.addEventListener('click', () => {
                const reviewTerms = document.getElementById('reviewTerminologyCheckbox').checked;
                const mode = reviewTerms ? 'terminology' : 'subtitles';
                console.log(`[pipeline] translateSubtitlesBtn clicked mode=${mode} currentVideoId=${currentVideoId} step=${displayedWizardStep}`);
                if (currentVideoId) {
                    continueWithConfigCheck(mode);
                } else {
                    startPipeline(mode);
                }
            });
            originalSubtitlesBtn.addEventListener('click', () => {
                console.log(`[pipeline] originalSubtitlesBtn clicked currentVideoId=${currentVideoId} step=${displayedWizardStep}`);
                if (currentVideoId) {
                    continueWithConfigCheck('transcribe');
                } else {
                    startPipeline('transcribe');
                }
            });
            document.getElementById('startNewProjectBtn').addEventListener('click', resetApp);

            // Undo button click
            const undoBtn = document.getElementById('undoTimelineBtn');
            if (undoBtn) undoBtn.addEventListener('click', undoTimeline);

            // Wizard back/next buttons
            const wizardBackBtn = document.getElementById('wizardBackBtn');
            if (wizardBackBtn) wizardBackBtn.addEventListener('click', goBack);
            const wizardNextBtn = document.getElementById('wizardNextBtn');
            if (wizardNextBtn) wizardNextBtn.addEventListener('click', goForward);

            // Keyboard shortcut: Ctrl+Z / Cmd+Z for undo
            document.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
                    e.preventDefault();
                    undoTimeline();
                }
            });
            
            // Global Find & Replace handler
            document.getElementById('replaceAllBtn').addEventListener('click', async () => {
                if (!currentVideoId || isSavingSegment) return;
                pushTimelineHistory();
                const findInput = document.getElementById('findInput');
                const replaceInput = document.getElementById('replaceInput');
                const replaceBtn = document.getElementById('replaceAllBtn');
                const findText = findInput ? findInput.value.trim() : '';
                if (!findText) return;
                
                isSavingSegment = true;
                if (replaceBtn) {
                    replaceBtn.textContent = 'Replacing...';
                    replaceBtn.classList.add('opacity-50', 'cursor-not-allowed');
                }
                
                try {
                    const response = await fetch(`/videos/${currentVideoId}/replace`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ find_text: findText, replace_text: replaceInput ? replaceInput.value : '' })
                    });
                    if (!response.ok) throw new Error('Replace failed');
                    const data = await response.json();
                    if (data.segments) renderSubtitleTimeline(data.segments);
                    if (findInput) findInput.value = '';
                    if (replaceInput) replaceInput.value = '';
                    log('Global replace applied successfully.', 'success');
                    showToast('Batch replacement complete!', 'success');
                } catch (err) {
                    log('Replace failed: ' + err.message, 'error');
                } finally {
                    isSavingSegment = false;
                    if (replaceBtn) {
                        replaceBtn.textContent = 'Replace All';
                        replaceBtn.classList.remove('opacity-50', 'cursor-not-allowed');
                    }
                }
            });
            document.getElementById('downloadRawTranscriptionLink').addEventListener('click', downloadTranscription);
            document.getElementById('exportSrtBtn').addEventListener('click', () => exportFormat('srt'));
            document.getElementById('exportVttBtn').addEventListener('click', () => exportFormat('vtt'));
            document.getElementById('exportTxtBtn').addEventListener('click', () => exportFormat('txt'));
            document.getElementById('exportJsonBtn').addEventListener('click', () => exportFormat('json'));

            // Admin dashboard handlers
            const adminRefreshBtn = document.getElementById('adminRefreshBtn');
            if (adminRefreshBtn) {
                adminRefreshBtn.addEventListener('click', loadAdminDashboard);
            }

            const adminHomeBtn = document.getElementById('adminHomeBtn');
            if (adminHomeBtn) {
                adminHomeBtn.addEventListener('click', () => {
                    hideAdminView();
                    history.pushState(null, '', '/');
                });
            }

            const adminUsersTable = document.getElementById('adminUsersTable');
            if (adminUsersTable) {
                adminUsersTable.addEventListener('click', (e) => {
                    const btn = e.target.closest('[data-admin-action]');
                    if (!btn) return;
                    const action = btn.getAttribute('data-admin-action');
                    const userId = btn.getAttribute('data-user-id');
                    if (action && userId) handleAdminAction(action, userId);
                });
            }

            // Route handling
            async function handleRoute() {
                const path = window.location.pathname;
                const params = new URLSearchParams(window.location.search);
                const videoId = params.get('video');

                if (path === '/admin') {
                    showAdminView();
                    return;
                }

                hideAdminView();
                if (videoId && !currentVideoId) {
                currentVideoId = videoId;
                const videoIdShortEl = document.getElementById('videoIdShort');
                if (videoIdShortEl) videoIdShortEl.textContent = videoId.substring(0, 8);
                const statusCardEl2 = document.getElementById('statusCard');
                if (statusCardEl2) statusCardEl2.classList.remove('hidden');
                const primaryActionEl2 = document.getElementById('primaryActionContainer');
                if (primaryActionEl2) primaryActionEl2.classList.remove('hidden');
                
                // Hide upload form, show compact card for loaded project
                const uploadFormEl2 = document.getElementById('uploadForm');
                if (uploadFormEl2) uploadFormEl2.classList.add('hidden');
                const configSceneEl2 = document.getElementById('configScene');
                if (configSceneEl2) configSceneEl2.classList.add('hidden');
                const uploadCompleteCardEl2 = document.getElementById('uploadCompleteCard');
                if (uploadCompleteCardEl2) uploadCompleteCardEl2.classList.remove('hidden');
                const uploadedFilenameEl2 = document.getElementById('uploadedFilename');
                if (uploadedFilenameEl2) uploadedFilenameEl2.textContent = 'Loaded project';
                
                // Connect WebSocket for real-time updates
                await connectWebSocket(videoId);
                
                // Fetch current status
                fetch(`/videos/${videoId}`)
                    .then(r => r.json())
                    .then(data => {
                        // Treat "awaiting_choice" as "transcribed" on direct page loads too
                        if (data.status === 'awaiting_choice') {
                            data.status = 'transcribed';
                        }
                        updateStatus(data);
                        updateButtonVisibility(data.status);
                        updateContextBrief(data);
                        if (data.total_segments) {
                            const segCountLoad = document.getElementById('segmentCount');
                            if (segCountLoad) segCountLoad.textContent = data.total_segments;
                        }
                        if ((data.status === 'transcribed' || data.status === 'completed') && data.segments) {
                            renderSubtitleTimeline(data.segments);
                        }
                    });
                }
            }

            // Try to resume a previously saved job session.
            restoreJobSession();

            window.addEventListener('popstate', handleRoute);
            handleRoute();
        });

```

### `app/main.py`

```
"""TermSub - Video Translation and Terminology Management API.

This is the main FastAPI application entry point.
"""

import asyncio
import hashlib
import json
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.api import admin, auth, export, jobs, profile, progress, quota, terms, videos
from app.core.analytics import log_page_view
from app.core.auth import (
    ACCESS_TOKEN_COOKIE,
    WS_TOKEN_SUBPROTOCOL,
    RequestIdentity,
    decode_access_token,
    decode_ws_token,
)
from app.core.config import settings
from app.core.quota import QuotaManager
from app.db.session import SessionLocal
from app.models.user import User


class ConnectionManager:
    """Manages WebSocket connections for real-time progress updates.

    Handles multiple concurrent connections per video, allowing multiple
    clients to watch the same video's progress simultaneously.

    Attributes:
        active_connections: Dict mapping video_id to list of WebSocket connections
    """

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        video_id: str,
        subprotocol: str | None = None,
    ) -> None:
        """Accept a new WebSocket connection for a video.

        Args:
            websocket: The WebSocket connection object
            video_id: The video ID this connection is watching
            subprotocol: The negotiated subprotocol to return to the client.
        """
        await websocket.accept(subprotocol=subprotocol)

        if video_id not in self.active_connections:
            self.active_connections[video_id] = []

        self.active_connections[video_id].append(websocket)
        print(
            f"[WebSocket] Client connected for video {video_id[:8]}... "
            f"(total: {len(self.active_connections[video_id])})"
        )

    def disconnect(self, websocket: WebSocket, video_id: str) -> None:
        """Remove a WebSocket connection.

        Args:
            websocket: The WebSocket connection to remove
            video_id: The video ID this connection was watching
        """
        if video_id in self.active_connections:
            if websocket in self.active_connections[video_id]:
                self.active_connections[video_id].remove(websocket)

            # Clean up empty connection lists
            if not self.active_connections[video_id]:
                del self.active_connections[video_id]

        print(f"[WebSocket] Client disconnected from video {video_id[:8]}...")

    async def broadcast_to_video(self, video_id: str, message: dict[str, Any]) -> int:
        """Broadcast a message to all connections watching a video.

        Args:
            video_id: The video ID to broadcast to
            message: Dictionary to send as JSON

        Returns:
            Number of clients the message was sent to
        """
        if video_id not in self.active_connections:
            return 0

        disconnected = []
        sent_count = 0

        for connection in self.active_connections[video_id]:
            try:
                await connection.send_text(json.dumps(message))
                sent_count += 1
            except Exception as e:
                # Client disconnected unexpectedly
                disconnected.append(connection)
                print(f"[WebSocket] Failed to send to client: {e}")

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn, video_id)

        return sent_count

    async def send_to_client(
        self, websocket: WebSocket, message: dict[str, Any]
    ) -> None:
        """Send a message to a specific client.

        Args:
            websocket: The WebSocket connection
            message: Dictionary to send as JSON
        """
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            print(f"[WebSocket] Failed to send to client: {e}")


# Global connection manager instance
manager = ConnectionManager()


class ProxySchemeMiddleware(BaseHTTPMiddleware):
    """Respect the X-Forwarded-Proto header from reverse proxies.

    Render (and similar proxies) forward HTTPS traffic to the app over HTTP.
    Without this, FastAPI redirects and URL generation use `http://`, which
    browsers block as mixed content when the page was loaded over HTTPS.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        forwarded_proto = request.headers.get("x-forwarded-proto")
        if forwarded_proto:
            request.scope["scheme"] = forwarded_proto
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every HTTP response."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Only send HSTS over HTTPS (or when the request claims HTTPS via a trusted proxy)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://www.googletagmanager.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https://img.shields.io; "
            "connect-src 'self' wss: https://www.google-analytics.com https://*.google-analytics.com https://cdn.jsdelivr.net; "
            "frame-ancestors 'none'; "
            "base-uri 'self'"
        )
        return response


class AnalyticsMiddleware(BaseHTTPMiddleware):
    """Log incoming requests to the PageView analytics table.

    Skips static assets and dispatches the DB write to a background thread
    so the response is not blocked.
    """

    SKIP_PREFIXES = ("/static", "/assets", "/favicon")

    @staticmethod
    def _extract_user_id(authorization: str | None) -> str | None:
        if not authorization or not authorization.lower().startswith("bearer "):
            return None
        token = authorization[7:].strip()
        try:
            payload = decode_access_token(token)
            return payload.get("sub")
        except Exception:
            return None

    @staticmethod
    def _hash_ip(ip: str | None) -> str | None:
        if not ip:
            return None
        return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        if path.startswith(self.SKIP_PREFIXES):
            return await call_next(request)

        authorization = request.headers.get("authorization")
        user_id = self._extract_user_id(authorization)
        ip_hash = self._hash_ip(request.client.host if request.client else None)
        user_agent = request.headers.get("user-agent")
        session_id = request.headers.get("x-session-id")

        response = await call_next(request)

        # Fire-and-forget the DB write so analytics never blocks the response.
        threading.Thread(
            target=log_page_view,
            args=(user_id, path, session_id, ip_hash, user_agent),
            daemon=True,
        ).start()

        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    # Startup
    print("=" * 60)
    print("[INIT] Starting TermSub API...")

    # Start Redis Pub/Sub listener for WebSocket broadcasts from Celery workers
    from app.core.redis_pubsub import start_redis_listener

    listener_task = asyncio.create_task(start_redis_listener(manager))
    print("[INIT] Redis Pub/Sub listener started")

    print("[INIT] API ready at http://0.0.0.0:8000")
    print("=" * 60)
    yield
    # Shutdown
    print("[INIT] Shutting down...")
    listener_task.cancel()
    with suppress(asyncio.CancelledError):
        await listener_task
    print("[INIT] Redis Pub/Sub listener stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# CORS middleware
# Restrict to the configured frontend origin and do not allow credentials.
# TermSub currently uses JWT/API-key auth in headers, not cookies, so
# allow_credentials stays False to prevent cross-origin credential attacks.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_BASE_URL],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Trust X-Forwarded-Proto from the reverse proxy so HTTPS URLs are generated
# correctly (avoids mixed-content redirects).
app.add_middleware(ProxySchemeMiddleware)

# Security headers middleware — CSP, frame-options, HSTS, etc.
app.add_middleware(SecurityHeadersMiddleware)

# Analytics middleware — logs page views in the background
app.add_middleware(AnalyticsMiddleware)

# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(quota.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(videos.router)
app.include_router(terms.router)
app.include_router(export.router)
app.include_router(progress.router)

# Set up WebSocket manager for progress updates
videos.set_websocket_manager(manager)
progress.set_websocket_manager(manager)


# Resolve absolute path to frontend directory relative to this file
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_STATIC_DIR = _FRONTEND_DIR

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
async def root() -> FileResponse:
    """Root endpoint - serve the landing page."""
    return FileResponse(str(_FRONTEND_DIR / "landing.html"))


@app.get("/app")
@app.get("/app/{path:path}")
async def app_page(path: str | None = None) -> FileResponse:
    """App frontend route - serve index.html for /app deep links."""
    return FileResponse(str(_FRONTEND_DIR / "index.html"))


@app.get("/admin")
@app.get("/admin/{path:path}")
async def admin_page(path: str | None = None) -> FileResponse:
    """Admin dashboard frontend route - serve admin.html for /admin deep links."""
    return FileResponse(str(_FRONTEND_DIR / "admin.html"))


@app.get("/contact")
async def contact_page() -> FileResponse:
    """Contact page frontend route."""
    return FileResponse(str(_FRONTEND_DIR / "contact.html"))


@app.get("/favicon.ico")
async def favicon() -> Response:
    """Return a 1x1 transparent pixel to stop 404 errors."""
    # 1x1 transparent GIF
    return Response(
        content=b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
        media_type="image/gif",
    )


@app.get("/sitemap.xml")
async def sitemap() -> Response:
    """Serve a dynamic sitemap for public pages."""
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    pages = [
        ("", "weekly", "1.0"),
        ("/app", "weekly", "0.8"),
        ("/contact", "monthly", "0.5"),
        ("/static/legal/imprint.html", "monthly", "0.3"),
        ("/static/legal/privacy.html", "monthly", "0.3"),
        ("/static/legal/beta-terms.html", "monthly", "0.3"),
        ("/static/legal/ai-disclosure.html", "monthly", "0.3"),
    ]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path, changefreq, priority in pages:
        lines.extend([
            "  <url>",
            f"    <loc>{base}{path}</loc>",
            f"    <changefreq>{changefreq}</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
        ])
    lines.append("</urlset>")

    return Response(content="\n".join(lines), media_type="application/xml")


@app.get("/robots.txt")
async def robots_txt() -> Response:
    """Serve robots.txt with a link to the sitemap."""
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return Response(content=content, media_type="text/plain")


@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/api/version")
def get_version() -> dict[str, str]:
    """Return the current application version."""
    return {"version": settings.VERSION}


def _extract_ws_identity(
    websocket: WebSocket,
) -> tuple[str | None, RequestIdentity | None]:
    """Resolve a WebSocket identity from the HttpOnly cookie or subprotocol.

    Standard browser users first obtain a short-lived WebSocket token from
    ``POST /api/auth/ws-token`` and send it via the
    ``Sec-WebSocket-Protocol: ["termsub-ws-token", <token>]`` header. This
    avoids relying on cookies during the WebSocket upgrade, which some proxies
    handle poorly, while keeping the long-lived JWT in an HttpOnly cookie.

    BYOK users send ``["termsub-byok", <openai-api-key>]`` via the
    Sec-WebSocket-Protocol header.

    The legacy cookie path is kept as a fallback for API clients/tests.

    Returns:
        Tuple of (negotiated_subprotocol, RequestIdentity | None).
    """
    # Standard users: short-lived WS token via subprotocol (preferred).
    subprotocols = websocket.scope.get("subprotocols", [])
    if len(subprotocols) >= 2 and subprotocols[0] == WS_TOKEN_SUBPROTOCOL:
        ws_token = subprotocols[1]
        payload = decode_ws_token(ws_token)
        if not payload:
            return None, None
        user_id = payload.get("sub")
        if not user_id:
            return None, None

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active or not user.is_email_verified:
                return None, None
            if (
                user.sessions_invalidated_at is not None
                and payload.get("iat") is not None
                and datetime.fromtimestamp(payload["iat"], tz=UTC).replace(tzinfo=None)
                < user.sessions_invalidated_at
            ):
                return None, None
            return WS_TOKEN_SUBPROTOCOL, RequestIdentity(
                user_id=user_id, is_byok=False, user=user
            )
        finally:
            db.close()

    # BYOK users: API key via subprotocol.
    if len(subprotocols) >= 2:
        protocol = subprotocols[0]
        credential = subprotocols[1]

        if protocol == "termsub-byok":
            api_key = credential.strip()
            if api_key:
                return protocol, RequestIdentity(
                    user_id=QuotaManager.byok_user_id(api_key),
                    is_byok=True,
                    api_key=api_key,
                )

    # Legacy fallback: HttpOnly cookie (used by tests / API clients).
    token = websocket.cookies.get(ACCESS_TOKEN_COOKIE)
    if token:
        try:
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if not user_id:
                return None, None

            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user or not user.is_active or not user.is_email_verified:
                    return None, None
                if (
                    user.sessions_invalidated_at is not None
                    and payload.get("iat") is not None
                    and datetime.fromtimestamp(payload["iat"], tz=UTC).replace(tzinfo=None)
                    < user.sessions_invalidated_at
                ):
                    return None, None
                return None, RequestIdentity(
                    user_id=user_id, is_byok=False, user=user
                )
            finally:
                db.close()
        except Exception:
            return None, None

    return None, None


@app.websocket("/ws/videos/{video_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    video_id: str,
) -> None:
    """WebSocket endpoint for real-time video progress updates.

    Standard users authenticate with a short-lived token from
    ``POST /api/auth/ws-token`` sent via the
    ``Sec-WebSocket-Protocol: ["termsub-ws-token", <token>]`` header.
    BYOK users authenticate with ``["termsub-byok", api_key]`` via the
    Sec-WebSocket-Protocol header.

    Connect to this endpoint to receive real-time updates during:
    - Transcription
    - Context analysis (Director Agent)
    - Glossary extraction (Glossary Agent)
    - Translation (Translator Agent)

    Messages sent:
    - {"status": "connected", "video_id": "..."}
    - {"status": "analyzing", "message": "Analyzing context..."}
    - {"status": "terms_ready", "terms_count": 15, "message": "Found 15 terms"}
    - {"status": "translating", "progress": 45, "current_batch": 9, "total_batches": 20}
    - {"status": "completed", "message": "Translation finished"}
    - {"status": "error", "message": "Error description"}

    Args:
        websocket: The WebSocket connection
        video_id: The video ID to watch
    """
    subprotocol, identity = _extract_ws_identity(websocket)
    if not identity:
        await websocket.close(code=1008, reason="Missing or invalid credentials")
        return

    await manager.connect(websocket, video_id, subprotocol=subprotocol)

    try:
        # Send initial connection confirmation
        await manager.send_to_client(
            websocket,
            {
                "type": "connected",
                "video_id": video_id,
                "message": "Connected to progress updates",
            },
        )

        # Keep connection alive and handle client messages
        # Use a short receive timeout so we periodically send keepalive traffic.
        # Some proxies close idle WebSocket connections after only a few seconds;
        # sending a message every ~10s prevents that.
        ws_receive_timeout = 10.0
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(), timeout=ws_receive_timeout
                )
                message = json.loads(data)

                # Handle client messages (e.g., ping)
                if message.get("type") == "ping":
                    await manager.send_to_client(websocket, {"type": "pong"})

            except TimeoutError:
                # Send keepalive ping
                try:
                    await manager.send_to_client(
                        websocket, {"type": "keepalive"}
                    )
                except Exception:
                    break
            except json.JSONDecodeError:
                # Ignore invalid JSON
                pass

    except WebSocketDisconnect:
        print(f"[WebSocket] Client disconnected from video {video_id[:8]}...")
    except Exception as e:
        print(f"[WebSocket] Error: {e}")
    finally:
        manager.disconnect(websocket, video_id)

```

