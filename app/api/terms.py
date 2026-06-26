from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.videos import require_video_owner
from app.core.auth import RequestIdentity, get_current_user_or_byok
from app.db.session import get_db
from app.models.video import Term, TermSource, Video

router = APIRouter(prefix="/terms", tags=["terms"])


class CustomTermCreate(BaseModel):
    original_term: str
    translated_term: str


class TermUpdate(BaseModel):
    standardized_term: str | None = None
    is_standardized: bool | None = None


class TranslationVariantOut(BaseModel):
    variant_translation: str
    occurrence_count: int


class TermOut(BaseModel):
    id: str
    video_id: str
    original_term: str
    translated_term: str
    is_standardized: bool
    standardized_term: str | None
    frequency: int
    category: str | None
    source: str
    created_at: datetime
    translation_variants: list[TranslationVariantOut]

    class Config:
        from_attributes = True


@router.get("/video/{video_id}")
def list_terms(
    video_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> list[dict[str, Any]]:
    """List all extracted terms for a video, including translation variants."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    terms = db.query(Term).filter(Term.video_id == video_id).all()

    # Include translation variants for each term
    result = []
    for term in terms:
        term_dict = {
            "id": term.id,
            "video_id": term.video_id,
            "original_term": term.original_term,
            "translated_term": term.translated_term,
            "is_standardized": term.is_standardized,
            "standardized_term": term.standardized_term,
            "frequency": term.frequency,
            "category": term.category,
            "source": term.source,  # Include source (auto/manual)
            "created_at": term.created_at,
            "translation_variants": [
                {
                    "variant_translation": v.variant_translation,
                    "occurrence_count": v.occurrence_count,
                }
                for v in term.translation_variants
            ],
        }
        result.append(term_dict)

    return result


@router.patch("/{term_id}", response_model=TermOut)
def update_term(
    term_id: str,
    update: TermUpdate,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Term:
    """Standardize a term (set standardized_term and is_standardized)."""
    term = db.query(Term).filter(Term.id == term_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    video = db.query(Video).filter(Video.id == term.video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    if update.standardized_term is not None:
        term.standardized_term = update.standardized_term
    if update.is_standardized is not None:
        term.is_standardized = update.is_standardized
    db.commit()
    db.refresh(term)
    return term


@router.post("/video/{video_id}/custom", response_model=TermOut)
def add_custom_term(
    video_id: str,
    term_data: CustomTermCreate,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> Term:
    """Add a custom term (manual find & replace) for a video."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    # Create manual term
    term = Term(
        video_id=video_id,
        original_term=term_data.original_term.strip(),
        translated_term=term_data.translated_term.strip(),
        category="Custom",
        source=TermSource.MANUAL,
        frequency=1,
        is_standardized=True,  # Manual terms are already standardized
        standardized_term=term_data.translated_term.strip(),
    )
    db.add(term)
    db.commit()
    db.refresh(term)

    return term


@router.delete("/video/{video_id}/custom/{term_id}")
def delete_custom_term(
    video_id: str,
    term_id: str,
    db: Session = Depends(get_db),
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, str]:
    """Delete a custom term. Only manual terms can be deleted."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    require_video_owner(video, identity)

    term = db.query(Term).filter(Term.id == term_id, Term.video_id == video_id).first()
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    # Only allow deletion of manual terms
    if term.source != TermSource.MANUAL:
        raise HTTPException(
            status_code=403, detail="Only custom (manual) terms can be deleted"
        )

    db.delete(term)
    db.commit()

    return {"message": "Custom term deleted"}
