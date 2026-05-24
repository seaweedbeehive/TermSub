from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query, Request
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session, selectinload
import json
import asyncio
import traceback

from app.db.session import get_db
from app.models.video import Video, VideoStatus, Segment
from app.schemas.video import VideoOut
from app.core.config import settings
from app.core.sqlite_queue import enqueue_job, get_job_status, set_transcription_provider, set_gemini_api_key
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
    provider: str = Query(None, description="Transcription provider: 'groq', 'local', or 'gemini'"),
    db: Session = Depends(get_db)
):
    """Queue transcription job for video using Whisper, or parse text files."""
    print(f"[API Transcribe] Request for video {video_id}, provider={provider}")
    
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
        
        # Determine effective provider for validation
        effective_provider = (provider or settings.TRANSCRIPTION_PROVIDER).lower()
        
        # Validation: Cloud engine requires a Gemini API key
        if effective_provider == "gemini":
            if not gemini_api_key or not gemini_api_key.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Gemini API Key is required for Cloud Engine processing."
                )
            set_gemini_api_key(video_id, gemini_api_key.strip())
        
        # Store per-request provider override (if any) before enqueueing
        if provider:
            set_transcription_provider(video_id, provider)
        
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
            VideoStatus.UPLOADED.value
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
