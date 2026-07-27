import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.db.base import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class VideoDomain(StrEnum):
    GENERAL = "general"
    POLITICS = "politics"
    MEDICINE = "medicine"
    PSYCHOLOGY = "psychology"
    SOCIOLOGY = "sociology"


class VideoStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"  # Waiting in background job queue
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"  # Transcription complete, ready for analysis
    ANALYZING = "analyzing"  # Multi-agent: Director analyzing context
    CONTEXT_READY = "context_ready"  # Multi-agent: Style guide generated
    GLOSSARY_EXTRACTING = (
        "glossary_extracting"  # Multi-agent: Glossary Agent extracting terms
    )
    TERMS_READY = "terms_ready"  # Multi-agent: Glossary extracted, terms for review
    TRANSLATING = "translating"  # Multi-agent: Translator running with glossary
    COMPLETED = "completed"
    ERROR = "error"


class ContentType(StrEnum):
    VIDEO = "video"
    TEXT = "text"


class Video(Base):
    __tablename__ = "videos"

    __table_args__ = (
        CheckConstraint(
            "content_type IN ('video', 'text')",
            name="ck_videos_content_type",
        ),
        CheckConstraint(
            "status IN ('uploaded', 'queued', 'extracting_audio', 'transcribing', "
            "'transcribed', 'analyzing', 'context_ready', 'glossary_extracting', "
            "'terms_ready', 'translating', 'completed', 'error')",
            name="ck_videos_status",
        ),
        CheckConstraint(
            "domain IN ('general', 'politics', 'medicine', 'psychology', 'sociology')",
            name="ck_videos_domain",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(16), default=ContentType.VIDEO.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default=VideoStatus.UPLOADED.value, nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    target_language: Mapped[str] = mapped_column(
        String(10), default="en", nullable=False
    )
    domain: Mapped[str] = mapped_column(
        String(32), default=VideoDomain.GENERAL.value, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Progress tracking fields
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_segments: Mapped[int] = mapped_column(Integer, default=0)
    processed_segments: Mapped[int] = mapped_column(Integer, default=0)
    current_segment_index: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Bulk processing tracking
    total_batches: Mapped[int] = mapped_column(Integer, default=0)
    processed_batches: Mapped[int] = mapped_column(Integer, default=0)

    # Multi-Agent Translation Pipeline
    style_guide: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON: tone, style, formality guidelines
    context_analysis: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON: topic, summary, key_terms[]
    skip_glossary: Mapped[bool] = mapped_column(Boolean, default=False)

    segments: Mapped[list["Segment"]] = relationship(
        "Segment",
        back_populates="video",
        cascade="all, delete-orphan",
        order_by="Segment.sequence_number",
    )
    terms: Mapped[list["Term"]] = relationship(
        "Term", back_populates="video", cascade="all, delete-orphan"
    )

    def update_progress(
        self, percent: int, step: str, detail: str | None = None
    ) -> None:
        """Update video processing progress.

        Args:
            percent: Progress percentage (0-100)
            step: Current processing step name
            detail: Optional detailed description of current operation
        """
        self.progress_percent = percent
        self.current_step = step
        if detail:
            self.step_detail = detail
        self.updated_at = datetime.utcnow()

    def mark_error(self, error_message: str) -> None:
        """Mark video as failed with error message.

        Args:
            error_message: Description of the error that occurred
        """
        self.status = VideoStatus.ERROR.value
        self.error_message = error_message
        self.updated_at = datetime.utcnow()

    def mark_job_complete(self, job_type: str) -> None:
        """Mark video as completed based on job type.

        Updates the video status to the appropriate state based on the
        completed job type and sets completion timestamp for translation.

        Args:
            job_type: Type of job that completed (transcribe, analyze, translate)
        """
        if job_type == "transcribe":
            self.status = VideoStatus.TRANSCRIBED.value
        elif job_type == "analyze":
            self.status = VideoStatus.TERMS_READY.value
        elif job_type == "translate":
            self.status = VideoStatus.COMPLETED.value
            self.completed_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    @property
    def is_processing(self) -> bool:
        """Check if video is currently being processed.

        Returns:
            True if video is in any processing state (queued, transcribing,
            analyzing, translating, etc.), False otherwise.
        """
        return self.status in [
            VideoStatus.QUEUED.value,
            VideoStatus.EXTRACTING_AUDIO.value,
            VideoStatus.TRANSCRIBING.value,
            VideoStatus.ANALYZING.value,
            VideoStatus.TRANSLATING.value,
        ]


class Segment(Base):
    __tablename__ = "segments"

    # Composite index for faster bulk operations by video_id + sequence_number
    __table_args__ = (Index("idx_segments_video_seq", "video_id", "sequence_number", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    avg_logprob: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_speech_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    video: Mapped["Video"] = relationship("Video", back_populates="segments")
    term_occurrences: Mapped[list["TermOccurrence"]] = relationship(
        "TermOccurrence", back_populates="segment", cascade="all, delete-orphan"
    )


class TermSource(StrEnum):
    AUTO = "auto"  # Extracted by Glossary Agent
    MANUAL = "manual"  # Added by user via Find & Replace


class Term(Base):
    __tablename__ = "terms"

    __table_args__ = (
        CheckConstraint(
            "source IN ('auto', 'manual')",
            name="ck_terms_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    original_term: Mapped[str] = mapped_column(Text, nullable=False)
    translated_term: Mapped[str] = mapped_column(Text, nullable=False)
    is_standardized: Mapped[bool] = mapped_column(Boolean, default=False)
    standardized_term: Mapped[str | None] = mapped_column(Text, nullable=True)
    frequency: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # Technical, Proper Noun, etc.
    source: Mapped[str] = mapped_column(
        String(16), default=TermSource.AUTO.value, nullable=False
    )  # auto or manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    video: Mapped["Video"] = relationship("Video", back_populates="terms")
    occurrences: Mapped[list["TermOccurrence"]] = relationship(
        "TermOccurrence", back_populates="term", cascade="all, delete-orphan"
    )
    translation_variants: Mapped[list["TranslationVariant"]] = relationship(
        "TranslationVariant", back_populates="term", cascade="all, delete-orphan"
    )


class TranslationVariant(Base):
    """Store different translations found for the same term
    (translation variance detection)."""

    __tablename__ = "translation_variants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    term_id: Mapped[str] = mapped_column(
        ForeignKey("terms.id", ondelete="CASCADE"), nullable=False
    )
    variant_translation: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    segment_ids: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON list of segment IDs
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    term: Mapped["Term"] = relationship("Term", back_populates="translation_variants")


class TermOccurrence(Base):
    """Join table linking a Term to specific Segment occurrences."""

    __tablename__ = "term_occurrences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    term_id: Mapped[str] = mapped_column(
        ForeignKey("terms.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[str] = mapped_column(
        ForeignKey("segments.id", ondelete="CASCADE"), nullable=False
    )
    context_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    term: Mapped["Term"] = relationship("Term", back_populates="occurrences")
    segment: Mapped["Segment"] = relationship(
        "Segment", back_populates="term_occurrences"
    )


class ProcessingLog(Base):
    """Log of processing steps for detailed tracking."""

    __tablename__ = "processing_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    level: Mapped[str] = mapped_column(
        String(20), default="INFO"
    )  # INFO, WARNING, ERROR
    step: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    @classmethod
    def log_step(
        cls,
        db: Session,
        video_id: str,
        step: str,
        message: str,
        level: str = "INFO",
        details: str | None = None,
    ) -> "ProcessingLog":
        """Create and add a new processing log entry.

        This is a convenience factory method for creating log entries
        without manually instantiating the class.

        Args:
            db: SQLAlchemy database session
            video_id: ID of the video being processed
            step: Name of the processing step (e.g., 'TRANSCRIBING', 'ANALYZING')
            message: Log message describing what happened
            level: Log level - 'INFO', 'WARNING', or 'ERROR' (default: 'INFO')
            details: Optional detailed information or traceback

        Returns:
            The created ProcessingLog instance (already added to session)

        Example:
            ProcessingLog.log_step(
                db=db,
                video_id=video.id,
                step="TRANSCRIBING",
                message="Starting Whisper transcription",
                level="INFO"
            )
        """
        log = cls(
            video_id=video_id, step=step, message=message, level=level, details=details
        )
        db.add(log)
        return log

    def __repr__(self) -> str:
        """Return string representation of the log entry."""
        return (
            f"<ProcessingLog(video_id={self.video_id}, "
            f"step={self.step}, level={self.level})>"
        )
