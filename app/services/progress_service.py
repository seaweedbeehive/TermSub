"""Progress tracking service for detailed video processing monitoring.

This module provides progress tracking that uses short-lived database sessions
to avoid holding locks during long-running operations.
"""

import time
from datetime import datetime, timedelta
from typing import Optional, List

from app.models.video import ProcessingLog, VideoStatus
from app.db.session_utils import get_db_session


class ProgressTracker:
    """Tracks and logs progress for video processing.
    
    Uses short-lived database sessions to avoid holding locks during
    long-running operations. Each write operation opens a new session
    and closes it immediately after.
    
    Attributes:
        video_id: ID of the video being tracked
        _step_start_time: Timestamp when current step started
        _current_step_name: Name of current processing step
    """
    
    def __init__(self, video_id: str, db=None):
        """Initialize progress tracker.
        
        Args:
            video_id: ID of the video to track
            db: Deprecated parameter, kept for backwards compatibility
        """
        self.video_id = video_id
        self._step_start_time = None
        self._current_step_name = None
        
    def _log(self, level: str, step: str, message: str, details: Optional[str] = None):
        """Log a message to database and console using short-lived session.
        
        Args:
            level: Log level (INFO, WARNING, ERROR)
            step: Processing step name
            message: Log message
            details: Optional detailed information
        """
        timestamp = datetime.utcnow()
        
        # Print to console with timestamp
        time_str = timestamp.strftime("%H:%M:%S.%f")[:-3]
        print(f"[{time_str}] [{level:8}] [{step:20}] {message}")
        if details:
            print(f"                     Details: {details}")
        
        # Save to database using short-lived session
        with get_db_session() as db:
            log_entry = ProcessingLog(
                video_id=self.video_id,
                level=level,
                step=step,
                message=message,
                details=details
            )
            db.add(log_entry)
        
    def info(self, step: str, message: str, details: Optional[str] = None):
        """Log info message."""
        self._log("INFO", step, message, details)
        
    def warning(self, step: str, message: str, details: Optional[str] = None):
        """Log warning message."""
        self._log("WARNING", step, message, details)
        
    def error(self, step: str, message: str, details: Optional[str] = None):
        """Log error message."""
        self._log("ERROR", step, message, details)
        
    def _get_video_primitives(self) -> Optional[dict]:
        """Get video primitive data with short-lived session.
        
        CRITICAL: Returns primitives only, never the Video object.
        The Video object would be detached when session closes.
        
        Returns:
            Dict with video primitive data or None if not found
        """
        from app.models.video import Video
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == self.video_id).first()
            if not video:
                return None
            # Extract primitives before session closes
            return {
                'id': video.id,
                'status': video.status,
                'progress_percent': video.progress_percent,
                'started_at': video.started_at,
            }
        
    def update_progress(
        self,
        status: str,
        percent: int,
        current_step: str,
        step_detail: str = "",
        total_segments: int = 0,
        processed_segments: int = 0,
        current_segment_index: int = 0
    ):
        """Update video progress in database using short-lived session.
        
        Args:
            status: Video status
            percent: Progress percentage (0-100)
            current_step: Current processing step
            step_detail: Detailed step description
            total_segments: Total number of segments
            processed_segments: Number of processed segments
            current_segment_index: Current segment index
        """
        from app.models.video import Video
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == self.video_id).first()
            if video:
                video.status = status
                video.progress_percent = min(max(percent, 0), 100)
                video.current_step = current_step
                video.step_detail = step_detail
                video.total_segments = total_segments
                video.processed_segments = processed_segments
                video.current_segment_index = current_segment_index
                video.updated_at = datetime.utcnow()
            
    def start_step(self, step_name: str, message: str = ""):
        """Start tracking a new processing step.
        
        Args:
            step_name: Name of the step
            message: Optional message describing the step
        """
        self._step_start_time = time.time()
        self._current_step_name = step_name
        msg = message or f"Starting {step_name}"
        self.info(step_name, msg)
        
        # Get current progress percent from video
        video_data = self._get_video_primitives()
        current_percent = video_data['progress_percent'] if video_data else 0
        
        self.update_progress(
            status=step_name.lower().replace(" ", "_"),
            percent=current_percent,
            current_step=step_name,
            step_detail=message
        )
        
    def end_step(self, message: str = ""):
        """End the current processing step.
        
        Args:
            message: Optional completion message
        """
        if self._step_start_time and self._current_step_name:
            elapsed = time.time() - self._step_start_time
            msg = message or f"Completed {self._current_step_name}"
            self.info(
                self._current_step_name,
                msg,
                f"Elapsed time: {elapsed:.2f}s"
            )
            
    def update_segment_progress(
        self,
        current: int,
        total: int,
        segment_text: str = ""
    ):
        """Update progress for segment processing.
        
        Args:
            current: Current segment number
            total: Total number of segments
            segment_text: Optional segment text for display
        """
        if total > 0:
            percent = int((current / total) * 100)
            detail = f"Processing segment {current}/{total}"
            if segment_text:
                # Truncate text for display
                text_preview = segment_text[:60] + "..." if len(segment_text) > 60 else segment_text
                detail += f" | Text: '{text_preview}'"
            
            # Get current video status
            video_data = self._get_video_primitives()
            current_status = video_data['status'] if video_data else "processing"
            
            self.update_progress(
                status=current_status,
                percent=percent,
                current_step=self._current_step_name or "processing",
                step_detail=detail,
                total_segments=total,
                processed_segments=current,
                current_segment_index=current
            )
            
            # Log every 10 segments or at start/end
            if current == 1 or current == total or current % 10 == 0:
                self.info(
                    self._current_step_name or "processing",
                    f"Progress: {current}/{total} segments ({percent}%)",
                    f"Current segment text: {segment_text[:100]}..." if segment_text else None
                )
                
    def estimate_time_remaining(self) -> Optional[str]:
        """Estimate time remaining based on progress.
        
        Returns:
            Formatted time string (e.g., "5m 30s") or None if can't estimate
        """
        video_data = self._get_video_primitives()
        if not video_data or not video_data.get('started_at'):
            return None
            
        if video_data['progress_percent'] <= 0 or video_data['progress_percent'] >= 100:
            return None
            
        elapsed = (datetime.utcnow() - video_data['started_at']).total_seconds()
        if elapsed < 1:
            return None
            
        # Calculate remaining time
        total_estimated = elapsed / (video_data['progress_percent'] / 100)
        remaining = total_estimated - elapsed
        
        if remaining < 60:
            return f"{int(remaining)}s"
        elif remaining < 3600:
            return f"{int(remaining/60)}m {int(remaining%60)}s"
        else:
            return f"{int(remaining/3600)}h {int((remaining%3600)/60)}m"
            
    def get_recent_logs(self, limit: int = 50) -> List[dict]:
        """Get recent processing logs.
        
        Args:
            limit: Maximum number of logs to return
            
        Returns:
            List of log entry dicts (primitives only, not ORM objects)
        """
        with get_db_session() as db:
            logs = (
                db.query(ProcessingLog)
                .filter(ProcessingLog.video_id == self.video_id)
                .order_by(ProcessingLog.timestamp.desc())
                .limit(limit)
                .all()
            )
            # Convert to primitives before returning
            return [
                {
                    'id': log.id,
                    'video_id': log.video_id,
                    'level': log.level,
                    'step': log.step,
                    'message': log.message,
                    'details': log.details,
                    'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                }
                for log in logs
            ]


def get_progress_tracker(video_id: str, db=None) -> ProgressTracker:
    """Factory function to create a progress tracker.
    
    Args:
        video_id: ID of the video to track
        db: Deprecated parameter, kept for backwards compatibility
        
    Returns:
        ProgressTracker instance
    """
    return ProgressTracker(video_id, db)
