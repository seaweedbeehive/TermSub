"""Database session utilities for services.

This module provides shared utilities for services to use short-lived
database sessions, preventing long-lived sessions that can cause SQLite
locking issues during long-running operations.
"""

from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional, Tuple, Any

from sqlalchemy.orm import Session

from app.db.session import SessionLocal


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions with automatic commit/rollback.
    
    Usage:
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            # Session automatically commits on successful exit
            # Session rolls back on exception
            # Session always closes in finally block
    
    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_video_with_session(video_id: str) -> Tuple[str, str, Optional[str], str]:
    """Get video primitives and immediately close session.
    
    Extracts needed fields so you can do work without holding session open.
    This is useful for long-running operations like audio extraction or
    transcription where you don't want to hold a database lock.
    
    CRITICAL: Returns primitives only, NEVER the Video object (would be detached).
    
    Args:
        video_id: ID of the video to retrieve
        
    Returns:
        Tuple of (file_path, filename, source_language, target_language)
        
    Raises:
        ValueError: If video not found
    """
    with get_db_session() as db:
        from app.models.video import Video
        
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video not found: {video_id}")
        
        # Return primitives only - Video object would be detached outside session
        return (
            video.file_path,
            video.filename,
            video.source_language,
            video.target_language
        )


def update_video_status(video_id: str, status: str, **kwargs) -> bool:
    """Update video status with short-lived session.
    
    Args:
        video_id: ID of the video to update
        status: New status value
        **kwargs: Additional fields to update (e.g., progress_percent=50)
        
    Returns:
        True if video was found and updated, False otherwise
    """
    with get_db_session() as db:
        from app.models.video import Video
        
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return False
        
        video.status = status
        video.updated_at = datetime.utcnow()
        
        for key, value in kwargs.items():
            if hasattr(video, key):
                setattr(video, key, value)
        
        return True


def get_video_segments(video_id: str, limit: Optional[int] = None) -> list:
    """Get segment texts for a video with short-lived session.
    
    Args:
        video_id: ID of the video
        limit: Optional limit on number of segments to return
        
    Returns:
        List of tuples (sequence_number, original_text, start_time, end_time)
    """
    with get_db_session() as db:
        from app.models.video import Segment
        
        query = (
            db.query(Segment)
            .filter(Segment.video_id == video_id)
            .order_by(Segment.sequence_number)
        )
        
        if limit:
            query = query.limit(limit)
        
        segments = query.all()
        
        return [
            (seg.sequence_number, seg.original_text, seg.start_time, seg.end_time)
            for seg in segments
        ]


def save_segment_translation(segment_id: str, translated_text: str) -> bool:
    """Save translation for a single segment.
    
    Args:
        segment_id: ID of the segment to update
        translated_text: Translated text to save
        
    Returns:
        True if segment was found and updated, False otherwise
    """
    with get_db_session() as db:
        from app.models.video import Segment
        
        segment = db.query(Segment).filter(Segment.id == segment_id).first()
        if not segment:
            return False
        
        segment.translated_text = translated_text
        return True


def mark_job_error(video_id: str, error_message: str, job_type: str = "") -> bool:
    """Mark a video and optional job as failed.
    
    Args:
        video_id: ID of the video
        error_message: Error message to store
        job_type: Optional job type for context
        
    Returns:
        True if video was found and updated, False otherwise
    """
    with get_db_session() as db:
        from app.models.video import Video, VideoStatus
        
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            return False
        
        video.status = VideoStatus.ERROR.value
        video.error_message = error_message
        video.updated_at = datetime.utcnow()
        
        # Also update job queue status if job_type provided
        if job_type:
            from app.models.job_queue import JobQueue, JobStatus
            
            job = (
                db.query(JobQueue)
                .filter(JobQueue.video_id == video_id)
                .filter(JobQueue.job_type == job_type)
                .filter(JobQueue.status == JobStatus.RUNNING.value)
                .first()
            )
            if job:
                job.status = JobStatus.ERROR.value
                job.error_message = error_message
                job.completed_at = datetime.utcnow()
        
        return True
