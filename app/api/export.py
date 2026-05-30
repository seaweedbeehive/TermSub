from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
import json

from app.db.session import get_db
from app.models.video import Video, VideoStatus, Segment

router = APIRouter(prefix="/export", tags=["export"])


def format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT time format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_vtt_time(seconds: float) -> str:
    """Convert seconds to WebVTT time format: HH:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def sanitize_filename(filename: str) -> str:
    """Remove or replace characters that could cause issues in filenames."""
    # Remove file extension
    name = filename.rsplit('.', 1)[0] if '.' in filename else filename
    # Replace problematic characters
    sanitized = name.replace('"', '').replace("'", "").replace(':', '-').replace('/', '-').replace('\\', '-')
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
        
        start_time = format_srt_time(segment.start_time)
        end_time = format_srt_time(segment.end_time)
        
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
        
        start_time = format_vtt_time(segment.start_time)
        end_time = format_vtt_time(segment.end_time)
        
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


def generate_json(video: Video, segments: list[Segment]) -> dict:
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
        ]
    }


def get_segments_or_404(
    video_id: str,
    db: Session,
    language_code: Optional[str] = None
) -> tuple[Video, list[Segment]]:
    """Get video and segments for a specific language track, raising 404/400 if invalid."""
    # Check if video exists in database
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Check if translation is complete
    if video.status != VideoStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail="Translation is still in progress"
        )
    
    # Resolve language code: explicit param > video.target_language
    effective_lang = language_code or video.target_language or "original"
    
    segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id, Segment.language_code == effective_lang)
        .order_by(Segment.sequence_number)
        .all()
    )
    
    if not segments:
        raise HTTPException(status_code=400, detail=f"No segments found for language '{effective_lang}'. Processing may not be complete.")
    
    # Check if any segments have translated text
    has_translations = any(seg.translated_text for seg in segments)
    if not has_translations:
        raise HTTPException(
            status_code=400,
            detail=f"No translated segments found for language '{effective_lang}'. Translation step may not be complete."
        )
    
    return video, segments


@router.get("/{video_id}/srt")
def export_srt(
    video_id: str,
    lang: Optional[str] = Query(None, description="Language code for the subtitle track (e.g., 'de', 'fa')"),
    db: Session = Depends(get_db)
):
    """Export the final SRT file with consistent terminology."""
    video, segments = get_segments_or_404(video_id, db, language_code=lang)
    
    # Generate SRT content
    srt_content = generate_srt(segments)
    
    # Return with appropriate headers for download
    # Use ASCII-only filename for Content-Disposition to avoid encoding issues
    headers = {
        "Content-Disposition": 'attachment; filename="subtitles.srt"',
        "Content-Type": "text/plain; charset=utf-8"
    }
    
    return Response(
        content=srt_content.encode('utf-8'),
        headers=headers
    )


@router.get("/{video_id}/vtt")
def export_vtt(
    video_id: str,
    lang: Optional[str] = Query(None, description="Language code for the subtitle track (e.g., 'de', 'fa')"),
    db: Session = Depends(get_db)
):
    """Export the final WebVTT file."""
    video, segments = get_segments_or_404(video_id, db, language_code=lang)
    
    # Generate VTT content
    vtt_content = generate_vtt(segments)
    
    # Return with appropriate headers for download
    headers = {
        "Content-Disposition": 'attachment; filename="subtitles.vtt"',
        "Content-Type": "text/vtt; charset=utf-8"
    }
    
    return Response(
        content=vtt_content.encode('utf-8'),
        headers=headers
    )


@router.get("/{video_id}/txt")
def export_txt(
    video_id: str,
    lang: Optional[str] = Query(None, description="Language code for the text track (e.g., 'de', 'fa')"),
    db: Session = Depends(get_db)
):
    """Export plain translated text only."""
    video, segments = get_segments_or_404(video_id, db, language_code=lang)
    
    # Generate TXT content
    txt_content = generate_txt(segments)
    
    # Return with appropriate headers for download
    headers = {
        "Content-Disposition": 'attachment; filename="translation.txt"',
        "Content-Type": "text/plain; charset=utf-8"
    }
    
    return Response(
        content=txt_content.encode('utf-8'),
        headers=headers
    )


@router.get("/{video_id}/json")
def export_json(
    video_id: str,
    lang: Optional[str] = Query(None, description="Language code for the JSON track (e.g., 'de', 'fa')"),
    db: Session = Depends(get_db)
):
    """Export full JSON with metadata and all segments."""
    video, segments = get_segments_or_404(video_id, db, language_code=lang)
    
    # Generate JSON content
    json_data = generate_json(video, segments)
    
    # Return as downloadable JSON file
    headers = {
        "Content-Disposition": 'attachment; filename="translation.json"',
        "Content-Type": "application/json; charset=utf-8"
    }
    
    return Response(
        content=json.dumps(json_data, indent=2, ensure_ascii=False).encode('utf-8'),
        headers=headers
    )


def generate_original_srt(segments: list[Segment]) -> str:
    """Generate SRT file content from ORIGINAL text (not translated)."""
    srt_lines = []
    for i, segment in enumerate(segments, 1):
        # Use ORIGINAL text only (not translated)
        text = segment.original_text
        
        start_time = format_srt_time(segment.start_time)
        end_time = format_srt_time(segment.end_time)
        
        srt_lines.append(str(i))
        srt_lines.append(f"{start_time} --> {end_time}")
        srt_lines.append(text)
        srt_lines.append("")  # Empty line between entries
    
    return "\n".join(srt_lines)


@router.get("/{video_id}/transcription")
def export_original_transcription(video_id: str, db: Session = Depends(get_db)):
    """Export the ORIGINAL transcription (before translation) as SRT."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Get source-language segments for this video
    source_language = video.source_language or "original"
    segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id, Segment.language_code == source_language)
        .order_by(Segment.sequence_number)
        .all()
    )
    
    if not segments:
        raise HTTPException(status_code=400, detail="No segments found. Transcription may not be complete.")
    
    # Generate SRT from original text
    srt_content = generate_original_srt(segments)
    
    # Return with appropriate headers for download
    headers = {
        "Content-Disposition": 'attachment; filename="transcription.srt"',
        "Content-Type": "text/plain; charset=utf-8"
    }
    
    return Response(
        content=srt_content.encode('utf-8'),
        headers=headers
    )
