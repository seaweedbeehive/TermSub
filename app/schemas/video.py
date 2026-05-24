from datetime import datetime
from pydantic import BaseModel, ConfigDict


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
    target_language: str = "en"


class VideoCreate(VideoBase):
    file_path: str


class VideoUpdate(BaseModel):
    status: str | None = None
    source_language: str | None = None


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
