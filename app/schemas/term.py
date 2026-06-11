from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TermBase(BaseModel):
    original_term: str
    translated_term: str


class TermCreate(TermBase):
    video_id: str
    frequency: int = 1


class TermUpdate(BaseModel):
    is_standardized: bool | None = None
    standardized_term: str | None = None


class TranslationVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_translation: str
    occurrence_count: int


class TermOut(TermBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    video_id: str
    is_standardized: bool
    standardized_term: str | None
    frequency: int
    category: str | None
    created_at: datetime
    translation_variants: list[TranslationVariantOut] = []
