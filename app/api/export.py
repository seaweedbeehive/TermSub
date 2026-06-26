import json
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.videos import require_video_owner
from app.core.analytics import log_usage_event
from app.core.auth import RequestIdentity, get_current_user_or_byok
from app.db.session_utils import get_db_session
from app.models.video import Segment, Video, VideoStatus
from app.utils.timecode import format_timestamp, format_timestamp_vtt

router = APIRouter(prefix="/export", tags=["export"])


def _log_export(
    identity: RequestIdentity,
    video_id: str,
    filename: str,
    source_language: str | None,
    target_language: str,
    export_format: str,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget a usage event for an export download."""
    metadata: dict[str, Any] = {
        "video_id": video_id,
        "filename": filename,
        "format": export_format,
        "target_language": target_language,
        "source_language": source_language,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    threading.Thread(
        target=log_usage_event,
        args=(None if identity.is_byok else identity.user_id, "export", metadata),
        daemon=True,
    ).start()


def sanitize_filename(filename: str) -> str:
    """Remove or replace characters that could cause issues in filenames."""
    # Remove file extension
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    # Replace problematic characters
    sanitized = (
        name.replace('"', "")
        .replace("'", "")
        .replace(":", "-")
        .replace("/", "-")
        .replace("\\", "-")
    )
    # Limit length
    return sanitized[:50]


def generate_srt(segments: list[Segment]) -> str:
    """Generate SRT file content from segments."""
    srt_lines = []
    for i, segment in enumerate(segments, 1):
        # Use translated text if available, otherwise original
        text = segment.translated_text or segment.original_text
        # Append RLM for RTL languages to keep punctuation on the correct side
        text = f"{text}\u200f"

        start_time = format_timestamp(segment.start_time)
        end_time = format_timestamp(segment.end_time)

        srt_lines.append(str(i))
        srt_lines.append(f"{start_time} --> {end_time}")
        srt_lines.append(text)
        srt_lines.append("")  # Empty line between entries

    return "\n".join(srt_lines)


def generate_vtt(segments: list[Segment]) -> str:
    """Generate WebVTT file content from segments."""
    vtt_lines = ["WEBVTT", ""]  # Header with blank line

    for i, segment in enumerate(segments, 1):
        # Use translated text if available, otherwise original
        text = segment.translated_text or segment.original_text
        # Append RLM for RTL languages to keep punctuation on the correct side
        text = f"{text}\u200f"

        start_time = format_timestamp_vtt(segment.start_time)
        end_time = format_timestamp_vtt(segment.end_time)

        vtt_lines.append(f"{i}")  # Cue identifier
        vtt_lines.append(f"{start_time} --> {end_time}")
        vtt_lines.append(text)
        vtt_lines.append("")  # Empty line between cues

    return "\n".join(vtt_lines)


def generate_txt(segments: list[Segment]) -> str:
    """Generate plain text file content from segments (translated text only)."""
    lines = []
    for segment in segments:
        # Use translated text if available, otherwise original
        text = segment.translated_text or segment.original_text
        # Append RLM for RTL languages to keep punctuation on the correct side
        text = f"{text}\u200f"
        lines.append(text)

    return "\n\n".join(lines)


def generate_json(video: Video, segments: list[Segment]) -> dict[str, Any]:
    """Generate JSON export with full metadata."""
    return {
        "metadata": {
            "video_id": video.id,
            "filename": video.filename,
            "content_type": video.content_type,
            "source_language": video.source_language,
            "target_language": video.target_language,
            "status": video.status,
            "total_segments": len(segments),
            "created_at": video.created_at.isoformat() if video.created_at else None,
        },
        "segments": [
            {
                "sequence_number": seg.sequence_number,
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "original_text": seg.original_text,
                "translated_text": seg.translated_text,
            }
            for seg in segments
        ],
    }


def get_segments_or_404(
    video_id: str, db: Session, identity: RequestIdentity
) -> tuple[Video, list[Segment]]:
    """Get video and segments, raising 404 if not found or 400 if incomplete."""
    # Check if video exists in database
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    # Check if translation is complete
    if video.status != VideoStatus.COMPLETED.value:
        raise HTTPException(status_code=400, detail="Translation is still in progress")

    segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.sequence_number)
        .all()
    )

    if not segments:
        raise HTTPException(
            status_code=400, detail="No segments found. Processing may not be complete."
        )

    # Check if any segments have translated text
    has_translations = any(seg.translated_text for seg in segments)
    if not has_translations:
        raise HTTPException(
            status_code=400,
            detail=(
                "No translated segments found. Translation step may not be complete."
            ),
        )

    return video, segments


@router.get("/{video_id}/srt")
def export_srt(
    video_id: str,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Response:
    """Export the final SRT file with consistent terminology."""
    with get_db_session() as db:
        video, segments = get_segments_or_404(video_id, db, identity)

        # Generate SRT content while the session is still open so segment
        # attributes remain accessible.
        srt_content = generate_srt(segments)
        download_name = sanitize_filename(video.filename) + ".srt"
        _log_export(
            identity,
            video.id,
            video.filename,
            video.source_language,
            video.target_language,
            "srt",
        )

    headers = {
        "Content-Disposition": f'attachment; filename="{download_name}"',
        "Content-Type": "text/plain; charset=utf-8",
    }

    return Response(content=srt_content.encode("utf-8"), headers=headers)


@router.get("/{video_id}/vtt")
def export_vtt(
    video_id: str,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Response:
    """Export the final WebVTT file."""
    with get_db_session() as db:
        video, segments = get_segments_or_404(video_id, db, identity)

        # Generate VTT content while the session is still open.
        vtt_content = generate_vtt(segments)
        download_name = sanitize_filename(video.filename) + ".vtt"
        _log_export(
            identity,
            video.id,
            video.filename,
            video.source_language,
            video.target_language,
            "vtt",
        )

    headers = {
        "Content-Disposition": f'attachment; filename="{download_name}"',
        "Content-Type": "text/vtt; charset=utf-8",
    }

    return Response(content=vtt_content.encode("utf-8"), headers=headers)


@router.get("/{video_id}/txt")
def export_txt(
    video_id: str,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Response:
    """Export plain translated text only."""
    with get_db_session() as db:
        video, segments = get_segments_or_404(video_id, db, identity)

        # Generate TXT content while the session is still open.
        txt_content = generate_txt(segments)
        download_name = sanitize_filename(video.filename) + ".txt"
        _log_export(
            identity,
            video.id,
            video.filename,
            video.source_language,
            video.target_language,
            "txt",
        )

    headers = {
        "Content-Disposition": f'attachment; filename="{download_name}"',
        "Content-Type": "text/plain; charset=utf-8",
    }

    return Response(content=txt_content.encode("utf-8"), headers=headers)


@router.get("/{video_id}/json")
def export_json(
    video_id: str,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Response:
    """Export full JSON with metadata and all segments."""
    with get_db_session() as db:
        video, segments = get_segments_or_404(video_id, db, identity)

        # Generate JSON content while the session is still open.
        json_data = generate_json(video, segments)
        download_name = sanitize_filename(video.filename) + ".json"
        _log_export(
            identity,
            video.id,
            video.filename,
            video.source_language,
            video.target_language,
            "json",
        )

    headers = {
        "Content-Disposition": f'attachment; filename="{download_name}"',
        "Content-Type": "application/json; charset=utf-8",
    }

    return Response(
        content=json.dumps(json_data, indent=2, ensure_ascii=False).encode("utf-8"),
        headers=headers,
    )


def generate_original_srt(segments: list[Segment]) -> str:
    """Generate SRT file content from ORIGINAL text (not translated)."""
    srt_lines = []
    for i, segment in enumerate(segments, 1):
        # Use ORIGINAL text only (not translated)
        text = segment.original_text

        start_time = format_timestamp(segment.start_time)
        end_time = format_timestamp(segment.end_time)

        srt_lines.append(str(i))
        srt_lines.append(f"{start_time} --> {end_time}")
        srt_lines.append(text)
        srt_lines.append("")  # Empty line between entries

    return "\n".join(srt_lines)


@router.get("/{video_id}/transcription")
def export_original_transcription(
    video_id: str,
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Response:
    """Export the ORIGINAL transcription (before translation) as SRT."""
    with get_db_session() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        require_video_owner(video, identity)

        # Get all segments for this video
        segments = (
            db.query(Segment)
            .filter(Segment.video_id == video_id)
            .order_by(Segment.sequence_number)
            .all()
        )

        if not segments:
            raise HTTPException(
                status_code=400,
                detail="No segments found. Transcription may not be complete.",
            )

        # Generate SRT from original text while the session is still open.
        srt_content = generate_original_srt(segments)
        download_name = sanitize_filename(video.filename) + "_transcription.srt"
        _log_export(
            identity,
            video.id,
            video.filename,
            video.source_language,
            video.target_language,
            "transcription",
        )

    headers = {
        "Content-Disposition": f'attachment; filename="{download_name}"',
        "Content-Type": "text/plain; charset=utf-8",
    }

    return Response(content=srt_content.encode("utf-8"), headers=headers)
