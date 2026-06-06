from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query, Request
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session, selectinload
import json
import asyncio
import traceback
import uuid

from app.db.session import get_db
from app.models.video import Video, VideoStatus, Segment
from app.schemas.video import VideoOut
from app.core.config import settings
from app.core.sqlite_queue import enqueue_job, get_job_status, set_gemini_api_key
from app.services.upload_service import save_uploaded_file
from app.services.text_parser import parse_text_file
from app.services.gemini_service import translate_video_sliding_window
from app.services.translation_pipeline import TranslationPipeline
from app.models.video import ContentType

# Import WebSocket manager (will be initialized in main.py)
_websocket_manager = None


def set_websocket_manager(manager):
    """Set the WebSocket manager for progress updates."""
    global _websocket_manager
    _websocket_manager = manager


async def _websocket_progress_callback(video_id: str, status: str, data: dict):
    """Callback function to send progress updates via WebSocket."""
    if _websocket_manager:
        await _websocket_manager.broadcast_to_video(video_id, data)


router = APIRouter(prefix="/videos", tags=["videos"])


@router.post("/upload", response_model=VideoOut)
async def upload_video(
    file: UploadFile = File(...),
    target_language: Optional[str] = Form(None),
    source_language: str = Form("auto"),
    db: Session = Depends(get_db),
):
    """Upload a video or text file."""
    # Server-side validation: target language is required
    if not target_language or not target_language.strip():
        raise HTTPException(
            status_code=422,
            detail="Target language is required. Please select a target language."
        )
    
    try:
        print(f"[API Upload] Starting: {file.filename}, target={target_language}, source={source_language}")
        video = await save_uploaded_file(file, target_language, source_language, db)
        print(f"[API Upload] Success: video_id={video.id}")
        return video
    except ValueError as e:
        print(f"[API Upload] Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[API Upload] Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: str, db: Session = Depends(get_db)):
    video = db.query(Video).options(selectinload(Video.segments)).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.post("/{video_id}/transcribe")
def transcribe_video_endpoint(
    video_id: str,
    request: Request,
    method: str = Query("whisper", description="Transcription method: 'whisper' only"),
    db: Session = Depends(get_db)
):
    """Queue transcription job for video using Gemini, or parse text files."""
    print(f"[API Transcribe] Request for video {video_id}")
    
    # Extract Gemini API key manually from raw headers to bypass Pydantic annotation quirks
    gemini_api_key = request.headers.get("X-Gemini-API-Key")
    
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            print(f"[API Transcribe] Video not found: {video_id}")
            raise HTTPException(status_code=404, detail="Video not found")
        
        print(f"[API Transcribe] Video: {video.filename}, type: {video.content_type}")
        
        # Handle text files - parse immediately
        if video.content_type == ContentType.TEXT.value:
            try:
                result = parse_text_file(video_id)
                return {
                    "status": "completed",
                    "video_id": video_id,
                    "message": "Text file parsed",
                    "total_segments": result.get("segment_count", 0)
                }
            except Exception as e:
                print(f"[API Transcribe] Text parsing error: {e}")
                traceback.print_exc()
                raise HTTPException(status_code=500, detail=f"Parsing failed: {str(e)}")
        
        # Validation: Gemini API key is required
        if not gemini_api_key or not gemini_api_key.strip():
            raise HTTPException(
                status_code=400,
                detail="Gemini API Key is required for transcription."
            )
        set_gemini_api_key(video_id, gemini_api_key.strip())
        
        # Queue transcription job
        try:
            job_id = enqueue_job('transcribe', video_id)
            print(f"[API Transcribe] Job {job_id} queued")
            
            return {
                "status": "queued",
                "job_id": job_id,
                "video_id": video_id,
                "job_type": "transcribe",
                "message": "Transcription queued"
            }
        except Exception as e:
            print(f"[API Transcribe] Queue error: {e}")
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Queue failed: {str(e)}")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API Transcribe] Unexpected error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")


@router.post("/{video_id}/analyze")
def analyze_video_endpoint(
    video_id: str,
    db: Session = Depends(get_db)
):
    """Queue analysis job (Director + Glossary Agents)."""
    print(f"[API Analyze] Request for video {video_id}")
    
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        
        job_id = enqueue_job('analyze', video_id)
        print(f"[API Analyze] Job {job_id} queued")
        
        return {
            "status": "queued",
            "job_id": job_id,
            "video_id": video_id,
            "job_type": "analyze",
            "message": "Analysis queued"
        }
    except Exception as e:
        print(f"[API Analyze] Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{video_id}/translate-direct")
def translate_direct_endpoint(
    video_id: str,
    db: Session = Depends(get_db)
):
    """Skip terminology analysis and queue translation directly."""
    print(f"[API TranslateDirect] Request for video {video_id}")
    
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        
        # Set skip_glossary flag
        video.skip_glossary = True
        db.commit()
        
        job_id = enqueue_job('translate', video_id)
        print(f"[API TranslateDirect] Job {job_id} queued")
        
        return {
            "status": "queued",
            "job_id": job_id,
            "video_id": video_id,
            "job_type": "translate",
            "message": "Translation queued (terminology skipped)"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API TranslateDirect] Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{video_id}/translate")
def translate_video_endpoint(
    video_id: str, 
    db: Session = Depends(get_db)
):
    """Queue translation job."""
    print(f"[API Translate] Request for video {video_id}")
    
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        
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
                detail=f"Video status is {video.status}. Need terms_ready or transcribed."
            )
        
        job_id = enqueue_job('translate', video_id)
        print(f"[API Translate] Job {job_id} queued")
        
        return {
            "status": "queued",
            "job_id": job_id,
            "video_id": video_id,
            "job_type": "translate",
            "message": "Translation queued"
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[API Translate] Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{video_id}/style-guide")
def get_style_guide_endpoint(
    video_id: str,
    db: Session = Depends(get_db)
):
    """Get the generated style guide for a video."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    if not video.style_guide:
        raise HTTPException(
            status_code=400, 
            detail="No style guide found. Run analyze first."
        )
    
    try:
        style_guide = json.loads(video.style_guide)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid style guide format")
    
    return {
        "video_id": video_id,
        "style_guide": style_guide,
        "status": video.status
    }


@router.get("/{video_id}/job-status")
def get_video_job_status(
    video_id: str,
    db: Session = Depends(get_db)
):
    """Get the status of the latest background job for a video."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    job_status = get_job_status(video_id)
    
    return {
        "video_id": video_id,
        "video_status": video.status,
        "job": job_status
    }


@router.delete("/{video_id}")
def delete_video(video_id: str, db: Session = Depends(get_db)):
    """Delete a video and all associated data."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    db.delete(video)
    db.commit()
    return {"message": "Video deleted"}


@router.post("/{video_id}/translate-legacy", response_model=VideoOut)
def translate_video_legacy_endpoint(
    video_id: str, 
    db: Session = Depends(get_db)
):
    """LEGACY: Direct translation without multi-agent pipeline."""
    try:
        video = translate_video_sliding_window(video_id, db)
        return video
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{video_id}/segments/{segment_id}")
def update_segment_translation(
    video_id: str,
    segment_id: str,
    body: dict,
    db: Session = Depends(get_db)
):
    """Update translated_text for a single subtitle segment."""
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.video_id == video_id
    ).first()
    
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    new_text = body.get("translated_text")
    if new_text is not None and isinstance(new_text, str):
        segment.translated_text = new_text
        db.commit()
        db.refresh(segment)
    
    return {"status": "success"}


@router.post("/{video_id}/replace")
def batch_replace_segments(
    video_id: str,
    body: dict,
    db: Session = Depends(get_db)
):
    """Batch replace text across all translated segments for a video."""
    find_text = body.get("find_text", "")
    replace_text = body.get("replace_text", "")
    
    if not find_text or not isinstance(find_text, str):
        raise HTTPException(status_code=400, detail="find_text is required and must be a string")
    
    # Execute SQLite batch REPLACE on translated_text
    result = db.execute(
        text("""
            UPDATE segments
            SET translated_text = REPLACE(translated_text, :find, :replace)
            WHERE video_id = :video_id
        """),
        {"find": find_text, "replace": replace_text or "", "video_id": video_id}
    )
    db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="No matching segments found for replacement")
    
    # Re-query updated segments ordered by sequence_number
    updated_segments = db.query(Segment).filter(
        Segment.video_id == video_id
    ).order_by(Segment.sequence_number).all()
    
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
        ]
    }


@router.post("/{video_id}/segments/add")
def add_segment(
    video_id: str,
    body: dict,
    db: Session = Depends(get_db)
):
    """Add a new segment at a specific position, shifting subsequent segments up."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    target_sequence = body.get("target_sequence")
    if target_sequence is None or not isinstance(target_sequence, int):
        raise HTTPException(status_code=400, detail="target_sequence is required and must be an integer")
    
    # Shift all segments at or after target_sequence up by 1
    db.execute(
        text("""
            UPDATE segments
            SET sequence_number = sequence_number + 1
            WHERE video_id = :video_id AND sequence_number >= :target_sequence
        """),
        {"video_id": video_id, "target_sequence": target_sequence}
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
    updated_segments = db.query(Segment).filter(
        Segment.video_id == video_id
    ).order_by(Segment.sequence_number).all()
    
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
        ]
    }


@router.delete("/{video_id}/segments/{segment_id}")
def delete_segment(
    video_id: str,
    segment_id: str,
    db: Session = Depends(get_db)
):
    """Delete a segment and shift subsequent sequence numbers down."""
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.video_id == video_id
    ).first()
    
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
        {"video_id": video_id, "deleted_sequence": deleted_sequence}
    )
    db.commit()
    
    # Return updated segment list
    updated_segments = db.query(Segment).filter(
        Segment.video_id == video_id
    ).order_by(Segment.sequence_number).all()
    
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
        ]
    }


@router.post("/{video_id}/segments/{segment_id}/split")
def split_segment(
    video_id: str,
    segment_id: str,
    db: Session = Depends(get_db)
):
    """Split a segment into two at the timecode midpoint and nearest text boundary."""
    segment = db.query(Segment).filter(
        Segment.id == segment_id,
        Segment.video_id == video_id
    ).first()
    
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
            split_idx = left_space if (mid_idx - left_space) <= (right_space - mid_idx) else right_space
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
        {"video_id": video_id, "current_sequence": segment.sequence_number}
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
    updated_segments = db.query(Segment).filter(
        Segment.video_id == video_id
    ).order_by(Segment.sequence_number).all()
    
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
        ]
    }

@router.post("/{video_id}/segments/restore")
def restore_segments(
    video_id: str,
    body: dict,
    db: Session = Depends(get_db)
):
    """Bulk-replace all segments for a video with a restored state (undo support).

    Deletes all existing segments and re-inserts the provided list.
    Preserves IDs from the snapshot when available to avoid breaking
    frontend references.
    """
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

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

