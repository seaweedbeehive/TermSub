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


class SegmentOut(SegmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    video_id: str
    translated_text: str | None
    created_at: datetime
