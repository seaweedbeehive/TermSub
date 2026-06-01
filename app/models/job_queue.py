"""SQLite-based background job queue model."""

from datetime import datetime, timedelta
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import Integer, String, DateTime, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobStatus(str, PyEnum):
    """Enum for job queue status values."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


class JobType(str, PyEnum):
    """Enum for supported job types."""
    TRANSCRIBE = "transcribe"
    ANALYZE = "analyze"
    TRANSLATE = "translate"


class JobQueue(Base):
    """Background job queue for long-running tasks.
    
    Handles transcription, analysis, and translation tasks asynchronously
    to prevent HTTP timeouts. Includes timeout detection and heartbeat
    tracking for stuck job recovery.
    """
    __tablename__ = "job_queue"
    
    # Table indexes for performance
    __table_args__ = (
        Index('idx_job_queue_status', 'status'),
        Index('idx_job_queue_video_status', 'video_id', 'status'),
    )
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(
        String(50), 
        nullable=False, 
        index=True,
        doc=f"Job type: {', '.join([t.value for t in JobType])}"
    )
    video_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), 
        default=JobStatus.PENDING.value,
        doc=f"Job status: {', '.join([s.value for s in JobStatus])}"
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Timeout and heartbeat tracking
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        doc="Timestamp of last heartbeat update during job processing"
    )
    timeout_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, 
        nullable=True,
        doc="Deadline after which job is considered timed out"
    )
    
    # Application-level locking for reliable job selection in SQLite
    locked_by: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        doc="Worker ID that claimed this job (UUID)"
    )
    
    @property
    def is_pending(self) -> bool:
        """Check if job is in pending status.
        
        Returns:
            True if status is PENDING, False otherwise.
        """
        return self.status == JobStatus.PENDING.value
    
    @property
    def is_running(self) -> bool:
        """Check if job is in running status.
        
        Returns:
            True if status is RUNNING, False otherwise.
        """
        return self.status == JobStatus.RUNNING.value
    
    @property
    def is_complete(self) -> bool:
        """Check if job is in complete status.
        
        Returns:
            True if status is COMPLETE, False otherwise.
        """
        return self.status == JobStatus.COMPLETE.value
    
    @property
    def is_error(self) -> bool:
        """Check if job is in error status.
        
        Returns:
            True if status is ERROR, False otherwise.
        """
        return self.status == JobStatus.ERROR.value
    
    @property
    def can_retry(self) -> bool:
        """Check if job can be retried.
        
        Returns:
            True if retry_count < max_retries, False otherwise.
        """
        return self.retry_count < self.max_retries
    
    def is_timed_out(self) -> bool:
        """Check if the job has exceeded its timeout deadline.
        
        Returns:
            True if timeout_at is set and current time exceeds it,
            False otherwise.
        """
        if self.timeout_at is None:
            return False
        return datetime.utcnow() > self.timeout_at
    
    def reset_for_retry(self) -> None:
        """Reset job state for retry attempt.
        
        Increments retry_count, resets status to PENDING, and clears
        all timing/tracking fields. Should be called when a job fails
        and is being queued for another attempt.
        """
        self.status = JobStatus.PENDING.value
        self.retry_count += 1
        self.started_at = None
        self.completed_at = None
        self.timeout_at = None
        self.last_heartbeat = None
        self.locked_by = None
    
    def start(self, worker_id: str, timeout_minutes: int = 30) -> None:
        """Mark job as started and set timeout deadline.
        
        Args:
            worker_id: Unique ID of the worker claiming this job
            timeout_minutes: Minutes until job is considered timed out
        """
        self.status = JobStatus.RUNNING.value
        self.locked_by = worker_id
        self.started_at = datetime.utcnow()
        self.last_heartbeat = datetime.utcnow()
        self.timeout_at = datetime.utcnow() + timedelta(minutes=timeout_minutes)
    
    def complete(self) -> None:
        """Mark job as successfully completed."""
        self.status = JobStatus.COMPLETE.value
        self.completed_at = datetime.utcnow()
        self.error_message = None
    
    def fail(self, error_message: str) -> None:
        """Mark job as failed with error message.
        
        Args:
            error_message: Description of the error that occurred
        """
        self.status = JobStatus.ERROR.value
        self.completed_at = datetime.utcnow()
        self.error_message = error_message
    
    def __repr__(self) -> str:
        """Return string representation of the job."""
        return (
            f"<JobQueue(id={self.id}, type='{self.job_type}', "
            f"status='{self.status}', video_id='{self.video_id[:8]}...')>"
        )
