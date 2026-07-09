"""Text Translation Service — orchestrates the text-only pipeline.

This service is completely separate from the video translation pipeline.  It
reuses models, DB sessions, the progress tracker, and the quota manager, but
implements its own context-analysis, glossary-extraction, translation, and
export steps tailored to plain text.
"""

import asyncio
from typing import Any

from sqlalchemy import func

from app.agents.text_context_agent import (
    analyze_text_context,
    extract_text_glossary,
)
from app.agents.text_translator_agent import translate_text_document
from app.core.auth import RequestIdentity
from app.core.quota import QuotaManager
from app.db.session import SessionLocal
from app.models.video import ContentType, Segment, Video, VideoStatus


def _load_text_record(video_id: str) -> Video:
    with SessionLocal() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Text record not found: {video_id}")
        if video.content_type != ContentType.TEXT.value:
            raise ValueError(f"Not a text record: {video_id}")
        return video


def extract_terms_for_text(video_id: str) -> dict[str, Any]:
    """Run Pass 1 + Pass 2 terminology extraction for a text document."""
    video = _load_text_record(video_id)
    if video.status == VideoStatus.ERROR.value:
        raise RuntimeError(f"Text record {video_id} is in ERROR status")

    # Pass 1
    context_data = analyze_text_context(video_id)
    # Pass 2
    glossary_data = extract_text_glossary(video_id)

    return {
        "video_id": video_id,
        "status": VideoStatus.TERMS_READY.value,
        "main_topic": context_data.get("main_topic", ""),
        "sub_topics": context_data.get("sub_topics", []),
        "key_terms": glossary_data.get("key_terms", []),
        "named_entities": glossary_data.get("named_entities", []),
    }


def _count_original_characters(video_id: str) -> int:
    with SessionLocal() as db:
        total = (
            db.query(func.coalesce(func.sum(func.length(Segment.original_text)), 0))
            .filter(Segment.video_id == video_id)
            .scalar()
            or 0
        )
    return int(total)


def _count_translated_characters(video_id: str) -> int:
    with SessionLocal() as db:
        total = (
            db.query(func.coalesce(func.sum(func.length(Segment.translated_text)), 0))
            .filter(Segment.video_id == video_id)
            .scalar()
            or 0
        )
    return int(total)


def translate_text(
    video_id: str,
    identity: RequestIdentity,
) -> dict[str, Any]:
    """Translate a text document using its extracted glossary."""
    video = _load_text_record(video_id)
    if video.status == VideoStatus.ERROR.value:
        raise RuntimeError(f"Text record {video_id} is in ERROR status")

    # Quota check for non-BYOK users.
    quota = QuotaManager()
    if not identity.is_byok:
        total_chars = _count_original_characters(video_id)
        check = quota.check_text_translation_allowed(
            identity.user_id,
            total_chars,
            identity.is_byok,
        )
        if not check["allowed"]:
            raise RuntimeError(check["reason"])

    # Run translation (agent is async; run it in a dedicated event loop).
    # Celery worker threads may not have a loop, and nested loops are not
    # allowed, so always create a fresh one on this thread.
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(translate_text_document(video_id))
    finally:
        loop.close()

    # Record quota consumption for non-BYOK users.
    if not identity.is_byok:
        translated_chars = _count_translated_characters(video_id)
        quota.record_text_translation(identity.user_id, translated_chars)

    return result


def export_text_translation(video_id: str) -> str:
    """Return the translated text as a single string."""
    video = _load_text_record(video_id)
    if video.status != VideoStatus.COMPLETED.value:
        raise ValueError("Translation is not complete")

    with SessionLocal() as db:
        segments = (
            db.query(Segment)
            .filter(Segment.video_id == video_id)
            .order_by(Segment.sequence_number)
            .all()
        )
        translated_sentences = []
        for seg in segments:
            text = seg.translated_text or seg.original_text or ""
            translated_sentences.append(text.strip())

    return "\n\n".join(translated_sentences)
