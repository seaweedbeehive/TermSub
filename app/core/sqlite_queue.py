"""SQLite-based background job queue worker.

Handles long-running transcription, analysis, and translation tasks
asynchronously without HTTP timeouts.
"""

import logging
import os
import tempfile
import threading
import time
import traceback
import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Generator, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.job_queue import JobQueue, JobStatus, JobType
from app.models.video import Video, VideoStatus, Segment, Term
from app.services.whisper_service import transcribe_video
from app.api.progress import send_progress_update


# Configure logger
logger = logging.getLogger(__name__)


# Valid job types for validation
VALID_JOB_TYPES = {JobType.TRANSCRIBE.value, JobType.ANALYZE.value, JobType.TRANSLATE.value}

# Singleton worker instance
_worker_instance: Optional['SQLiteQueueWorker'] = None
_worker_lock = threading.Lock()

# In-memory store for per-request OpenAI API keys.
# Key: video_id, Value: API key string
# Populated by the API endpoint before enqueue, consumed by the worker.
_openai_api_keys: Dict[str, str] = {}


def set_openai_api_key(video_id: str, api_key: str) -> None:
    """Store the OpenAI API key for a video before enqueueing.
    
    Args:
        video_id: The video ID
        api_key: OpenAI API key
    """
    _openai_api_keys[video_id] = api_key


def get_openai_api_key(video_id: str) -> Optional[str]:
    """Retrieve and clear the stored OpenAI API key for a video.
    
    Args:
        video_id: The video ID
        
    Returns:
        API key if set, None otherwise
    """
    return _openai_api_keys.pop(video_id, None)


# Backward-compatible aliases
set_gemini_api_key = set_openai_api_key
get_gemini_api_key = get_openai_api_key

# Default timeout for job processing (in minutes)
DEFAULT_JOB_TIMEOUT_MINUTES = 30
# Heartbeat interval during job processing (in seconds)
HEARTBEAT_INTERVAL_SECONDS = 60
# Maximum length for error messages stored in database
MAX_ERROR_MESSAGE_LENGTH = 2000


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions with automatic commit/rollback.
    
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


class SQLiteQueueWorker(threading.Thread):
    """Background worker thread that processes jobs from SQLite queue.
    
    This worker runs continuously in a background thread, polling for pending
    jobs and executing them. It uses application-level locking with UUID-based
    worker IDs for reliable job selection in SQLite (where with_for_update is
    unreliable). Includes timeout detection, heartbeat tracking, and automatic
    retry logic for failed jobs.
    
    Attributes:
        check_interval: Seconds between job polling cycles
        timeout_minutes: Maximum time allowed for job processing
        _running: Event flag to control worker lifecycle
        _worker_id: Unique UUID for this worker instance
        _current_job_id: ID of job currently being processed
        _current_job_start_time: When the current job started
    """
    
    def __init__(self, check_interval: float = 1.0, timeout_minutes: int = DEFAULT_JOB_TIMEOUT_MINUTES):
        """Initialize the queue worker.
        
        Args:
            check_interval: Seconds between job polling cycles (default: 1.0)
            timeout_minutes: Maximum time allowed for job processing (default: 30)
        """
        super().__init__(daemon=True)
        self.check_interval = check_interval
        self.timeout_minutes = timeout_minutes
        self._running = threading.Event()
        self._running.set()
        # Unique worker ID for application-level locking
        self._worker_id = str(uuid.uuid4())[:16]  # Short UUID for readability
        # Current job being processed (for heartbeat updates)
        self._current_job_id: Optional[int] = None
        self._current_job_start_time: Optional[datetime] = None
        logger.info(f"[QueueWorker] Initialized with worker_id: {self._worker_id}")
    
    def stop(self) -> None:
        """Signal the worker to stop gracefully."""
        self._running.clear()
    
    def run(self) -> None:
        """Main worker loop. Polls for jobs and processes them until stopped."""
        logger.info(f"[QueueWorker] Started (timeout: {self.timeout_minutes} minutes)")
        while self._running.is_set():
            try:
                self._process_loop()
            except Exception as e:
                logger.error(f"[QueueWorker] Error in process loop: {e}")
                logger.debug(traceback.format_exc())
            time.sleep(self.check_interval)
        logger.info("[QueueWorker] Stopped")
    
    def _update_heartbeat(self, job_id: int) -> None:
        """Update the heartbeat timestamp for a running job.
        
        Args:
            job_id: ID of the job to update
        """
        try:
            with get_db_session() as db:
                job = db.query(JobQueue).filter(JobQueue.id == job_id).first()
                if job and job.status == JobStatus.RUNNING.value:
                    job.last_heartbeat = datetime.utcnow()
                    # Note: commit happens automatically when context exits
        except Exception as e:
            logger.warning(f"[QueueWorker] Failed to update heartbeat for job {job_id}: {e}")
    
    def _recover_stuck_jobs(self, db: Session) -> int:
        """Check for and reset timed-out running jobs.
        
        A job is considered stuck if:
        - It has no heartbeat and started longer than timeout ago
        - Its last heartbeat is older than the timeout threshold
        
        Args:
            db: Database session
            
        Returns:
            Number of stuck jobs recovered
        """
        timeout_threshold = datetime.utcnow() - timedelta(minutes=self.timeout_minutes)
        
        # Find running jobs that have timed out (no heartbeat or old heartbeat)
        stuck_jobs = (
            db.query(JobQueue)
            .filter(JobQueue.status == JobStatus.RUNNING.value)
            .filter(
                (JobQueue.last_heartbeat == None) |  # No heartbeat ever
                (JobQueue.last_heartbeat < timeout_threshold) |  # Old heartbeat
                (
                    (JobQueue.started_at != None) & 
                    (JobQueue.started_at < timeout_threshold) &
                    (JobQueue.last_heartbeat == None)
                )  # Started long ago but no heartbeat
            )
            .all()
        )
        
        recovered_count = 0
        for job in stuck_jobs:
            # Safely get max_retries with fallback
            max_retries = getattr(job, 'max_retries', 3)
            
            if job.retry_count >= max_retries:
                # Mark as error - exceeded max retries
                job.status = JobStatus.ERROR.value
                job.error_message = f"Job timed out after {self.timeout_minutes} minutes (max retries exceeded)"
                job.completed_at = datetime.utcnow()
                job.locked_by = None  # Clear the lock
                
                # Update video status to error
                video = db.query(Video).filter(Video.id == job.video_id).first()
                if video:
                    video.status = VideoStatus.ERROR.value
                
                logger.warning(f"[QueueWorker] Recovered stuck job {job.id} as ERROR (timeout, max retries)")
                
                # Notify via WebSocket
                self._send_ws_sync(job.video_id, {
                    'type': 'job_error',
                    'job_type': job.job_type,
                    'job_id': job.id,
                    'status': JobStatus.ERROR.value,
                    'error': f"Job timed out after {self.timeout_minutes} minutes"
                })
            else:
                # Reset for retry
                job.status = JobStatus.PENDING.value
                job.started_at = None
                job.last_heartbeat = None
                job.locked_by = None  # Clear the lock
                job.retry_count += 1
                job.error_message = f"Job timed out after {self.timeout_minutes} minutes, queued for retry {job.retry_count}/{max_retries}"
                
                logger.info(f"[QueueWorker] Recovered stuck job {job.id} for retry {job.retry_count}/{max_retries}")
                
                # Notify via WebSocket
                self._send_ws_sync(job.video_id, {
                    'type': 'job_retry',
                    'job_type': job.job_type,
                    'job_id': job.id,
                    'retry_count': job.retry_count,
                    'reason': 'timeout'
                })
            
            recovered_count += 1
        
        if recovered_count > 0:
            db.commit()
            logger.info(f"[QueueWorker] Recovered {recovered_count} stuck job(s)")
        
        return recovered_count
    
    def _claim_job(self, db: Session) -> Optional[Tuple[int, str, str]]:
        """Atomically claim a pending job using application-level locking.
        
        This method implements reliable job selection for SQLite by using an
        atomic UPDATE statement. SQLite serializes UPDATE operations, ensuring
        that only one thread can successfully claim a job even if multiple
        threads query simultaneously.
        
        The process:
        1. Find the next PENDING job with retry_count < max_retries
        2. Atomically update it to RUNNING, set locked_by to our worker_id,
           and set started_at timestamp
        3. Verify we actually got the lock by checking locked_by matches
        
        Args:
            db: Database session
            
        Returns:
            Tuple of (job_id, video_id, job_type) if job claimed, None otherwise
        """
        # First, find the next pending job (ordered by creation time)
        # We do this in a subquery to avoid race conditions
        pending_job = (
            db.query(JobQueue)
            .filter(JobQueue.status == JobStatus.PENDING.value)
            .filter(JobQueue.retry_count < JobQueue.max_retries)
            .order_by(JobQueue.created_at.asc())
            .first()
        )
        
        if not pending_job:
            return None
        
        # Atomically claim this job using UPDATE
        # SQLite serializes UPDATEs, so only one thread will succeed
        now = datetime.utcnow()
        timeout_at = now + timedelta(minutes=self.timeout_minutes)
        
        result = (
            db.query(JobQueue)
            .filter(JobQueue.id == pending_job.id)
            .filter(JobQueue.status == JobStatus.PENDING.value)  # Ensure still pending
            .update({
                'status': JobStatus.RUNNING.value,
                'locked_by': self._worker_id,
                'started_at': now,
                'last_heartbeat': now,
                'timeout_at': timeout_at
            }, synchronize_session=False)
        )
        
        db.commit()
        
        if result == 0:
            # Another thread claimed the job between our SELECT and UPDATE
            logger.debug(f"[QueueWorker] Job {pending_job.id} was claimed by another worker")
            return None
        
        # Verify we actually own this job (paranoid check)
        claimed_job = (
            db.query(JobQueue)
            .filter(JobQueue.id == pending_job.id)
            .filter(JobQueue.locked_by == self._worker_id)
            .first()
        )
        
        if not claimed_job:
            logger.warning(f"[QueueWorker] Failed to verify ownership of job {pending_job.id}")
            return None
        
        logger.info(f"[QueueWorker] Claimed job {claimed_job.id} ({claimed_job.job_type}) "
                   f"for video {claimed_job.video_id[:8]}... with worker_id {self._worker_id}")
        
        return (claimed_job.id, claimed_job.video_id, claimed_job.job_type)
    
    def _verify_job_ownership(self, db: Session, job_id: int) -> bool:
        """Verify that this worker still owns the job.
        
        This should be called before processing and after long operations
        to ensure the job hasn't been reassigned due to timeout.
        
        Args:
            db: Database session
            job_id: ID of the job to verify
            
        Returns:
            True if this worker owns the job, False otherwise
        """
        job = db.query(JobQueue).filter(JobQueue.id == job_id).first()
        if not job:
            return False
        return job.locked_by == self._worker_id and job.status == JobStatus.RUNNING.value
    
    def _process_loop(self) -> None:
        """Check for and process one pending job with atomic selection.
        
        This method:
        1. Recovers any stuck jobs that have timed out
        2. Atomically claims a pending job using application-level locking
        3. Verifies ownership before processing
        4. Processes the job in a separate session
        """
        job_id: Optional[int] = None
        video_id: Optional[str] = None
        job_type: Optional[str] = None
        
        with get_db_session() as db:
            # First, recover any stuck jobs
            self._recover_stuck_jobs(db)
            
            # Atomically claim a pending job
            claimed = self._claim_job(db)
            if claimed:
                job_id, video_id, job_type = claimed
        
        # Process job with a fresh session - claiming session is already closed
        if job_id and video_id and job_type:
            # Verify ownership one more time before processing
            with get_db_session() as db:
                if not self._verify_job_ownership(db, job_id):
                    logger.warning(f"[QueueWorker] Lost ownership of job {job_id} before processing")
                    return
            
            self._current_job_id = job_id
            self._current_job_start_time = datetime.utcnow()
            job_result = None
            try:
                job_result = self._process_job(job_id, video_id, job_type)
            finally:
                audio_path = job_result.get('audio_path') if isinstance(job_result, dict) else None
                self._cleanup_files(video_id, audio_path)
                self._current_job_id = None
                self._current_job_start_time = None
    
    def _send_ws_sync(self, video_id: str, data: Dict[str, Any]) -> None:
        """Send WebSocket message from synchronous worker thread with proper cleanup.
        
        Args:
            video_id: ID of the video to send update for
            data: Dictionary containing the WebSocket message data
        """
        loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(send_progress_update(video_id, data))
            logger.debug(f"[QueueWorker] WebSocket sent: {data.get('status', data.get('type', 'unknown'))}")
        except Exception as e:
            logger.warning(f"[QueueWorker] WebSocket send failed: {e}")
        finally:
            # Proper event loop cleanup - cancel pending tasks
            if loop:
                try:
                    # Cancel all pending tasks
                    pending = asyncio.all_tasks(loop) if hasattr(asyncio, 'all_tasks') else asyncio.Task.all_tasks(loop)
                    if pending:
                        for task in pending:
                            task.cancel()
                        # Wait briefly for tasks to cancel
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    
                    # Close the loop properly
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.close()
                except Exception as cleanup_err:
                    logger.warning(f"[QueueWorker] Event loop cleanup warning: {cleanup_err}")
    
    def _truncate_error_message(self, message: str, max_length: int = MAX_ERROR_MESSAGE_LENGTH) -> str:
        """Truncate error message to maximum length.
        
        Args:
            message: The error message to truncate
            max_length: Maximum allowed length (default: MAX_ERROR_MESSAGE_LENGTH)
            
        Returns:
            Truncated message with ellipsis if needed
        """
        if len(message) <= max_length:
            return message
        return message[:max_length - 3] + "..."

    def _cleanup_files(self, video_id: str, audio_path: Optional[str] = None) -> None:
        """Permanently delete uploaded video and temporary audio files.
        
        Args:
            video_id: ID of the video whose files should be cleaned up
            audio_path: Optional path to the temporary .mp3 file
        """
        try:
            # Delete original uploaded video file
            with get_db_session() as db:
                video_record = db.query(Video).filter(Video.id == video_id).first()
                if video_record and video_record.file_path:
                    Path(video_record.file_path).unlink(missing_ok=True)
                    logger.info(f"[QueueWorker] Deleted uploaded file for video {video_id}")
        except Exception as e:
            logger.warning(f"[QueueWorker] Failed to delete uploaded file: {e}")
        
        # Delete temporary audio file (deterministic path used by whisper_service)
        temp_audio = audio_path or os.path.join(tempfile.gettempdir(), f"termsub_{video_id}.mp3")
        try:
            if temp_audio:
                Path(temp_audio).unlink(missing_ok=True)
                logger.info(f"[QueueWorker] Deleted temp audio file for video {video_id}")
        except Exception as e:
            logger.warning(f"[QueueWorker] Failed to delete temp audio file: {e}")
    
    def _process_job(self, job_id: int, video_id: str, job_type: str) -> Optional[Dict[str, Any]]:
        """Process a single job - CLEAN SLATE PATTERN.
        
        CRITICAL: This method NEVER stores Video objects long-term.
        Only video_id (str) is stored. Fresh queries are used for all updates.
        
        Args:
            job_id: ID of the job to process
            video_id: ID of the video associated with the job
            job_type: Type of job (transcribe, analyze, translate)
        """
        logger.info(f"Processing job {job_id} for video {video_id}")
        
        self._send_ws_sync(video_id, {
            'type': 'job_started',
            'job_type': job_type,
            'job_id': job_id,
            'status': JobStatus.RUNNING.value
        })
        
        # Validate job type first
        if job_type not in VALID_JOB_TYPES:
            error_msg = f"Unknown job type: {job_type}. Valid types: {VALID_JOB_TYPES}"
            logger.error(f"Job {job_id} FAILED: {error_msg}")
            
            # Use fresh session - never store video object
            with get_db_session() as db:
                job = db.query(JobQueue).filter(JobQueue.id == job_id).first()
                if job:
                    job.status = JobStatus.ERROR.value
                    job.error_message = error_msg
                    job.completed_at = datetime.utcnow()
                    job.locked_by = None  # Clear the lock
                
                # Re-fetch video by ID for update - DO NOT store video object
                video_record = db.query(Video).filter(Video.id == video_id).first()
                if video_record:
                    video_record.status = VideoStatus.ERROR.value
            
            self._send_ws_sync(video_id, {
                'type': 'job_error',
                'job_type': job_type,
                'job_id': job_id,
                'status': JobStatus.ERROR.value,
                'error': error_msg
            })
            return
        
        try:
            # Execute the job based on type
            result = None
            success_status = None
            
            if job_type == JobType.TRANSCRIBE.value:
                # TRANSCRIBE: No db session passed - whisper_service manages its own short sessions
                result = self._do_transcription(video_id)
                success_status = VideoStatus.TRANSCRIBED.value
            elif job_type == JobType.ANALYZE.value:
                # ANALYZE: Pass only video_id, method manages its own sessions
                result = self._do_analysis(video_id)
                success_status = VideoStatus.TERMS_READY.value
            elif job_type == JobType.TRANSLATE.value:
                # TRANSLATE: Pass only video_id, method manages its own sessions
                result = self._do_translation(video_id)
                success_status = VideoStatus.COMPLETED.value
            else:
                # This should never happen due to validation above
                raise ValueError(f"Unknown job type: {job_type}")
            
            # Mark job as complete with a FRESH session
            # CRITICAL: Re-query everything - don't use old objects
            with get_db_session() as db:
                job = db.query(JobQueue).filter(JobQueue.id == job_id).first()
                if job:
                    job.status = JobStatus.COMPLETE.value
                    job.completed_at = datetime.utcnow()
                    job.error_message = None
                    job.locked_by = None  # Clear the lock
                
                # Re-fetch video by ID for update - DO NOT store video object
                video_record = db.query(Video).filter(Video.id == video_id).first()
                if video_record:
                    video_record.status = success_status
                # Session commits automatically on exit
            
            logger.info(f"Job {job_id} completed successfully")
            
            # Send completion WebSocket
            self._send_ws_sync(video_id, {
                'type': 'job_complete',
                'job_type': job_type,
                'job_id': job_id,
                'status': 'completed',
                'result': result
            })
            
            return result
            
        except Exception as e:
            error_msg = str(e)
            error_trace = traceback.format_exc()
            logger.error(f"Job {job_id} FAILED: {error_msg}")
            logger.debug(error_trace)
            
            # Handle retry/error with a FRESH session
            # CRITICAL: Re-query everything - don't use old objects
            with get_db_session() as db:
                job = db.query(JobQueue).filter(JobQueue.id == job_id).first()
                if job:
                    # Safely get max_retries with fallback
                    max_retries = getattr(job, 'max_retries', 3)
                    job.retry_count += 1
                    
                    # Truncate error message to prevent database bloat
                    full_error = f"{error_msg}\n{error_trace}"
                    job.error_message = self._truncate_error_message(full_error)
                    
                    if job.retry_count >= max_retries:
                        job.status = JobStatus.ERROR.value
                        job.completed_at = datetime.utcnow()  # Mark completion time for error
                        job.locked_by = None  # Clear the lock
                        logger.error(f"Job {job_id} marked as error (max retries)")
                        
                        # Re-fetch video by ID for update - DO NOT store video object
                        video_record = db.query(Video).filter(Video.id == video_id).first()
                        if video_record:
                            video_record.status = VideoStatus.ERROR.value
                        
                        self._send_ws_sync(video_id, {
                            'type': 'job_error',
                            'job_type': job_type,
                            'job_id': job_id,
                            'status': JobStatus.ERROR.value,
                            'error': error_msg
                        })
                    else:
                        job.status = JobStatus.PENDING.value
                        job.started_at = None
                        job.last_heartbeat = None  # Clear heartbeat when resetting for retry
                        job.locked_by = None  # Clear the lock
                        logger.info(f"Job {job_id} queued for retry {job.retry_count}/{max_retries}")
                        
                        self._send_ws_sync(video_id, {
                            'type': 'job_retry',
                            'job_type': job_type,
                            'job_id': job_id,
                            'retry_count': job.retry_count
                        })
                else:
                    # Job not found - this is a serious error
                    raise RuntimeError(f"Job {job_id} not found during error handling") from e
                # Session commits automatically on exit
            
            return None
    
    def _do_transcription(self, video_id: str) -> Dict[str, Any]:
        """Execute transcription job using Gemini Cloud.
        
        This method does NOT hold a database session during the long-running
        transcription work. It passes only video_id to whisper_service which
        manages its own short-lived sessions.
        
        Args:
            video_id: ID of the video to transcribe
            
        Returns:
            Dictionary with transcription results including segment count
            
        Raises:
            ValueError: If video not found
            RuntimeError: If no segments were created
        """
        logger.info(f"Starting transcription for {video_id}")
        
        # Get source language with a short session (don't hold session during transcription)
        source_language = None
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise ValueError(f"Video not found: {video_id}")
            
            # Check if video is in ERROR status - abort early
            if video.status == VideoStatus.ERROR.value:
                raise RuntimeError(f"Video {video_id} is in ERROR status, aborting transcription")
            
            source_language = video.source_language
            logger.debug(f"Video {video_id} source_language: {source_language}")
        
        # Check for a per-request OpenAI API key override
        api_key_override = get_openai_api_key(video_id)
        if api_key_override:
            logger.info("Using per-request OpenAI API key")
        
        # Send initial progress
        self._send_ws_sync(video_id, {
            'status': 'transcribing',
            'progress': 10,
            'message': 'Starting OpenAI Cloud transcription...'
        })
        
        # Execute transcription (NO db session - whisper_service manages its own sessions)
        # The whisper service will fetch video_path and do FFmpeg/Whisper work outside any session
        transcribe_result = None
        if source_language:
            logger.debug(f"Using specified language: {source_language}")
            transcribe_result = transcribe_video(video_id, language=source_language, api_key=api_key_override)
        else:
            logger.debug("Using auto-detect")
            transcribe_result = transcribe_video(video_id, api_key=api_key_override)
        
        # Check result - transcribe_video now returns a Dict with success flag
        if transcribe_result and not transcribe_result.get("success", True):
            logger.warning(f"Transcription returned non-success: {transcribe_result}")
        
        # Update heartbeat after transcription
        if self._current_job_id:
            self._update_heartbeat(self._current_job_id)
        
        # Re-check video exists after long operation (using fresh short session)
        segment_count = 0
        video_status = 'unknown'
        with get_db_session() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise RuntimeError(f"Video {video_id} was deleted during transcription")
            
            # Check if video was marked as ERROR during processing
            if video.status == VideoStatus.ERROR.value:
                raise RuntimeError(f"Video {video_id} was marked as ERROR during transcription")
            
            video_status = video.status
            logger.debug(f"Transcription complete. Video status: {video_status}")
            
            # Verify segments
            segment_count = db.query(Segment).filter(Segment.video_id == video_id).count()
            logger.debug(f"Segments created: {segment_count}")
        
        if segment_count == 0:
            raise RuntimeError("No segments were created")
        
        # Send completion status
        self._send_ws_sync(video_id, {
            'status': 'transcribed',
            'progress': 100,
            'message': f'Transcription complete: {segment_count} segments',
            'total_segments': segment_count
        })
        
        # Prompt user to choose next step
        self._send_ws_sync(video_id, {
            'status': 'awaiting_choice',
            'message': 'Transcription complete. Choose your next step.',
            'total_segments': segment_count
        })
        
        return {
            'total_segments': segment_count,
            'video_status': video_status,
            'audio_path': transcribe_result.get('audio_path') if transcribe_result else None
        }
    
    def _do_analysis(self, video_id: str) -> Dict[str, Any]:
        """Execute analysis job using Director and Glossary agents.
        
        This performs context analysis and glossary extraction in sequence.
        Uses short-lived sessions - NEVER holds db session during long operations.
        
        Args:
            video_id: ID of the video to analyze
            
        Returns:
            Dictionary with analysis results including term count
            
        Raises:
            ValueError: If video not found
        """
        logger.info(f"Starting analysis for {video_id}")
        
        # Check video exists and is not in ERROR - short session
        skip_glossary = False
        with get_db_session() as db:
            video_record = db.query(Video).filter(Video.id == video_id).first()
            if not video_record:
                raise ValueError(f"Video not found: {video_id}")
            
            # Check if video is in ERROR status - abort early
            if video_record.status == VideoStatus.ERROR.value:
                raise RuntimeError(f"Video {video_id} is in ERROR status, aborting analysis")
            
            skip_glossary = video_record.skip_glossary
        
        # Routing: skip analysis and glossary extraction entirely if flag is set
        if skip_glossary:
            logger.info(f"Analysis for {video_id} skipped (skip_glossary=True)")
            self._send_ws_sync(video_id, {
                'status': 'terms_ready',
                'progress': 100,
                'message': 'Terminology extraction skipped — proceeding to translation',
                'terms_count': 0
            })
            return {
                'terms_extracted': 0,
                'video_status': 'terms_ready',
                'skipped': True
            }
        
        self._send_ws_sync(video_id, {
            'status': 'analyzing',
            'progress': 0,
            'message': 'Director Agent: Analyzing content...'
        })
        
        # Step 1: Analyze context (NO session held during this)
        self._send_ws_sync(video_id, {
            'status': 'analyzing',
            'progress': 20,
            'message': 'Analyzing content style...'
        })
        
        # Create pipeline with its own session management
        from app.services.context_analysis_service import analyze_video_context, extract_glossary
        style_guide = analyze_video_context(video_id)
        
        # Update heartbeat after context analysis
        if self._current_job_id:
            self._update_heartbeat(self._current_job_id)
        
        self._send_ws_sync(video_id, {
            'status': 'context_ready',
            'progress': 50,
            'message': f'Director complete: {style_guide.get("tone", "neutral")} tone',
            'tone': style_guide.get("tone", "neutral"),
            'formality_level': style_guide.get("formality_level", "medium")
        })
        
        # Step 2: Extract glossary
        self._send_ws_sync(video_id, {
            'status': 'glossary_extracting',
            'progress': 60,
            'message': 'Extracting terms...'
        })
        
        context_data = extract_glossary(video_id, style_guide)
        term_count = len(context_data.get("key_terms", []))
        
        # Update heartbeat after glossary extraction
        if self._current_job_id:
            self._update_heartbeat(self._current_job_id)
        
        # Re-check video exists after long operation - fresh session
        video_status = 'unknown'
        with get_db_session() as db:
            video_record = db.query(Video).filter(Video.id == video_id).first()
            if not video_record:
                raise RuntimeError(f"Video {video_id} was deleted during analysis")
            
            # Check if video was marked as ERROR during processing
            if video_record.status == VideoStatus.ERROR.value:
                raise RuntimeError(f"Video {video_id} was marked as ERROR during analysis")
            
            video_status = video_record.status
        
        logger.info(f"Analysis complete. Terms: {term_count}, Status: {video_status}")
        
        self._send_ws_sync(video_id, {
            'status': 'terms_ready',
            'progress': 100,
            'message': f'Analysis complete: {term_count} terms',
            'terms_count': term_count
        })
        
        return {
            'terms_extracted': term_count,
            'video_status': video_status
        }
    
    def _do_translation(self, video_id: str) -> Dict[str, Any]:
        """Execute translation job using Translator agent.
        
        Uses short-lived sessions - NEVER holds db session during long operations.
        
        Args:
            video_id: ID of the video to translate
            
        Returns:
            Dictionary with translation results including segment counts
            
        Raises:
            ValueError: If video not found
        """
        logger.info(f"Starting translation for {video_id}")
        
        # Check video exists and is not in ERROR - short session
        with get_db_session() as db:
            video_record = db.query(Video).filter(Video.id == video_id).first()
            if not video_record:
                raise ValueError(f"Video not found: {video_id}")
            
            # Check if video is in ERROR status - abort early
            if video_record.status == VideoStatus.ERROR.value:
                raise RuntimeError(f"Video {video_id} is in ERROR status, aborting translation")
        
        self._send_ws_sync(video_id, {
            'status': 'translating',
            'progress': 0,
            'message': 'Starting translation...'
        })
        
        # Perform translation via the pipeline so glossary terms are fetched and enforced
        from app.services.translation_pipeline import TranslationPipeline
        pipeline = TranslationPipeline()
        translate_result = pipeline.translate_with_glossary_sync(video_id)
        
        # Check result - translate_video_sliding_window now returns a Dict
        if translate_result and not translate_result.get("success", True):
            logger.warning(f"Translation returned non-success: {translate_result}")
        
        # Update heartbeat after translation
        if self._current_job_id:
            self._update_heartbeat(self._current_job_id)
        
        # Re-check video exists and fetch translated segments - fresh session
        video_status = 'unknown'
        total = 0
        translated = 0
        segment_rows = []
        with get_db_session() as db:
            video_record = db.query(Video).filter(Video.id == video_id).first()
            if not video_record:
                raise RuntimeError(f"Video {video_id} was deleted during translation")
            
            video_status = video_record.status
            logger.debug(f"Translation complete. Status: {video_status}")
            
            # Count translated segments
            total = db.query(func.count(Segment.id)).filter(
                Segment.video_id == video_id
            ).scalar() or 0
            
            translated = db.query(func.count(Segment.id)).filter(
                Segment.video_id == video_id,
                Segment.translated_text.isnot(None)
            ).scalar() or 0
            
            # Fetch subtitle timeline for frontend review panel
            segment_rows = [
                {
                    'id': s.id,
                    'sequence_number': s.sequence_number,
                    'start_time': s.start_time,
                    'end_time': s.end_time,
                    'original_text': s.original_text,
                    'translated_text': s.translated_text,
                }
                for s in db.query(Segment)
                    .filter(Segment.video_id == video_id)
                    .order_by(Segment.sequence_number)
                    .all()
            ]
        
        self._send_ws_sync(video_id, {
            'status': 'completed',
            'progress': 100,
            'message': f'Translation complete: {translated}/{total} segments',
            'segments': segment_rows
        })
        
        return {
            'total_segments': total,
            'translated_segments': translated,
            'video_status': video_status,
            'segments': segment_rows
        }


def get_queue_worker(timeout_minutes: int = DEFAULT_JOB_TIMEOUT_MINUTES) -> SQLiteQueueWorker:
    """Get the singleton queue worker instance with thread-safe double-checked locking.
    
    Args:
        timeout_minutes: Maximum time allowed for job processing before considered stuck
        
    Returns:
        SQLiteQueueWorker singleton instance
    """
    global _worker_instance
    
    # First check without lock for performance
    if _worker_instance is not None:
        return _worker_instance
    
    # Acquire lock and double-check
    with _worker_lock:
        if _worker_instance is None:
            _worker_instance = SQLiteQueueWorker(timeout_minutes=timeout_minutes)
    
    return _worker_instance


def enqueue_job(job_type: str, video_id: str) -> int:
    """Create and enqueue a new background job.
    
    Args:
        job_type: Type of job to create (transcribe, analyze, translate)
        video_id: ID of the video to process
        
    Returns:
        int: The job ID
    """
    with get_db_session() as db:
        job = JobQueue(
            job_type=job_type,
            video_id=video_id,
            status=JobStatus.PENDING.value,
            retry_count=0
        )
        db.add(job)
        
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.status = VideoStatus.QUEUED.value
        
        db.flush()
        job_id = job.id
        
        logger.info(f"[QueueWorker] Enqueued job {job_id}: {job_type} for video {video_id}")
        return job_id


def get_job_status(video_id: str) -> Optional[Dict[str, Any]]:
    """Get the latest job status for a video.
    
    Args:
        video_id: ID of the video to check
        
    Returns:
        Dictionary with job status information, or None if no job found
    """
    with get_db_session() as db:
        job = (
            db.query(JobQueue)
            .filter(JobQueue.video_id == video_id)
            .order_by(JobQueue.created_at.desc())
            .first()
        )
        
        if not job:
            return None
        
        return {
            'job_id': job.id,
            'job_type': job.job_type,
            'status': job.status,
            'retry_count': job.retry_count,
            'max_retries': job.max_retries,
            'error_message': job.error_message,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None
        }
