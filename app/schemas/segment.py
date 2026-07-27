from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SegmentBase(BaseModel):
    sequence_number: int
    start_time: float
    end_time: float
    original_text: str


class SegmentCreate(SegmentBase):
    video_id: str


class SegmentUpdate(BaseModel):
    translated_text: str | None = None
    original_text: str | None = None
    start_time: str | None = None
    end_time: str | None = None


class SegmentOut(SegmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    video_id: str
    translated_text: str | None
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    created_at: datetime
