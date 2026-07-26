"""OpenAI translation service — Async Sliding Window Translation with Concurrency Control.

This module is the backward-compatible service layer that wraps the core
OpenAI translator agent (app.agents.translator) with database persistence.

All Gemini-specific logic has been replaced with OpenAI Chat Completions.
"""  # noqa: E501

import asyncio
import time
from typing import Any

from sqlalchemy.orm import Session

from app.agents.translator import (
    DEFAULT_OVERLAP,
    DEFAULT_WINDOW_SIZE,
    create_sliding_windows,
    get_async_openai_client,
    merge_translations,
    translate_batches_concurrently,
)
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.video import Segment, Video, VideoStatus
from app.services.progress_service import get_progress_tracker

# Re-export constants for backward compatibility
__all__ = [
    "DEFAULT_WINDOW_SIZE",
    "DEFAULT_OVERLAP",
    "get_gemini_client",
    "get_openai_client",
    "translate_video_sliding_window_async",
    "translate_video_sliding_window",
    "translate_video",
    "bulk_save_segments",
    "bulk_save_segments_with_short_sessions",
]


def test_openai_connection(api_key: str | None = None) -> tuple[bool, str]:
    """Test if OpenAI API is configured and working.

    Args:
        api_key: Optional API key to test. Falls back to settings.OPENAI_API_KEY.
    """
    try:
        from openai import OpenAI

        effective_key = api_key or settings.OPENAI_API_KEY
        if not effective_key:
            return (
                False,
                "OPENAI_API_KEY not configured. Please enter your API key in the UI.",
            )

        client = OpenAI(api_key=effective_key)
        response = client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {
                    "role": "user",
                    "content": "Say 'API test successful' in 5 words or less.",
                }
            ],
            max_completion_tokens=20,
        )

        if response and response.choices and response.choices[0].message.content:
            return (
                True,
                f"API working! Response: {response.choices[0].message.content[:50]}",
            )
        else:
            return False, "API returned empty response"
    except Exception as e:
        return False, f"API error: {str(e)}"


# Backward-compatible alias
test_gemini_connection = test_openai_connection


def get_openai_client(api_key: str | None = None) -> Any:
    """Initialize and return an AsyncOpenAI client.

    Args:
        api_key: Optional per-request API key.

    Raises:
        RuntimeError: If no API key is available.
    """
    return get_async_openai_client(api_key)


# Backward-compatible alias for existing imports
get_gemini_client = get_openai_client


# ============================================================================
# Database Persistence Functions
# ============================================================================


def bulk_save_segments(
    db: Session,
    video: Video,
    translations: list[dict[str, Any]],
    all_segments: list[Segment],
    batch_size: int = 50,
    progress_tracker: Any = None,
) -> int:
    """Bulk save segment translations to database with efficient batch commits.

    This function collects all translations in memory and performs bulk updates
    in batches of 50 segments, committing only once per batch.
    """
    from app.db.session import bulk_update_segment_translations

    if not translations:
        return 0

    start_time = time.time()

    seq_to_segment = {s.sequence_number: s for s in all_segments}

    translation_data = []
    translation_count = 0

    for translation in translations:
        seq_num = translation.get("sequence_number")
        translated_text = translation.get("translated_text", "").strip()

        if seq_num and translated_text and seq_num in seq_to_segment:
            translation_data.append(
                {
                    "sequence_number": seq_num,
                    "translated_text": translated_text,
                }
            )
            translation_count += 1

    if not translation_data:
        return 0

    total_batches = (len(translation_data) + batch_size - 1) // batch_size
    video.total_batches = total_batches
    video.processed_batches = 0
    db.commit()

    saved_count = 0

    for i in range(0, len(translation_data), batch_size):
        batch_start = time.time()
        batch = translation_data[i : i + batch_size]

        batch_saved = bulk_update_segment_translations(video.id, batch)
        saved_count += batch_saved

        video.processed_batches = (i // batch_size) + 1
        video.processed_segments = saved_count
        video.progress_percent = int((saved_count / len(translation_data)) * 100)
        db.commit()

        batch_elapsed = (time.time() - batch_start) * 1000

        if progress_tracker:
            progress_tracker.info(
                "TRANSLATING",
                f"Bulk saved {batch_saved} segments "
                f"({saved_count}/{len(translation_data)})",
                f"Batch {video.processed_batches}/{total_batches} "
                f"in {batch_elapsed:.1f}ms",
            )

        print(
            f"[TRANSLATING] Bulk saved {len(batch)} segments in {batch_elapsed:.1f}ms "
            f"(batch {video.processed_batches}/{total_batches})"
        )

    total_elapsed = (time.time() - start_time) * 1000

    if progress_tracker:
        progress_tracker.info(
            "TRANSLATING",
            f"Bulk save complete: {saved_count} segments",
            f"Total time: {total_elapsed:.1f}ms in {total_batches} batches",
        )

    print(
        f"[TRANSLATING] ✓ Bulk saved {saved_count} segments in {total_elapsed:.1f}ms "
        f"({total_batches} batches)"
    )

    return saved_count


def bulk_save_segments_with_short_sessions(
    video_id: str,
    translations: list[dict[str, Any]],
    batch_size: int = 50,
    progress_tracker: Any = None,
) -> int:
    """Bulk save segment translations using short-lived database sessions."""
    from app.db.session import bulk_update_segment_translations

    if not translations:
        return 0

    start_time = time.time()

    translation_data = []
    for translation in translations:
        seq_num = translation.get("sequence_number")
        translated_text = translation.get("translated_text", "").strip()

        if seq_num and translated_text:
            translation_data.append(
                {
                    "sequence_number": seq_num,
                    "translated_text": translated_text,
                }
            )

    if not translation_data:
        return 0

    total_batches = (len(translation_data) + batch_size - 1) // batch_size
    with SessionLocal() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.total_batches = total_batches
            video.processed_batches = 0
            db.commit()

    saved_count = 0

    for i in range(0, len(translation_data), batch_size):
        batch_start = time.time()
        batch = translation_data[i : i + batch_size]

        batch_saved = bulk_update_segment_translations(video_id, batch)
        saved_count += batch_saved

        with SessionLocal() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.processed_batches = (i // batch_size) + 1
                video.processed_segments = saved_count
                video.progress_percent = int(
                    (saved_count / len(translation_data)) * 100
                )
                db.commit()

        batch_elapsed = (time.time() - batch_start) * 1000

        if progress_tracker:
            progress_tracker.info(
                "TRANSLATING",
                f"Bulk saved {batch_saved} segments "
                f"({saved_count}/{len(translation_data)})",
                f"Batch {((i // batch_size) + 1)}/{total_batches} "
                f"in {batch_elapsed:.1f}ms",
            )

        print(
            f"[TRANSLATING] Bulk saved {len(batch)} segments in {batch_elapsed:.1f}ms "
            f"(batch {((i // batch_size) + 1)}/{total_batches})"
        )

    total_elapsed = (time.time() - start_time) * 1000

    if progress_tracker:
        progress_tracker.info(
            "TRANSLATING",
            f"Bulk save complete: {saved_count} segments",
            f"Total time: {total_elapsed:.1f}ms in {total_batches} batches",
        )

    print(
        f"[TRANSLATING] ✓ Bulk saved {saved_count} segments in {total_elapsed:.1f}ms "
        f"({total_batches} batches)"
    )

    return saved_count


# ============================================================================
# Main Translation Functions
# ============================================================================


async def translate_video_sliding_window_async(
    video_id: str,
    db: Session | None = None,
    model_name: str = "gpt-5.4-mini",
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    glossary: dict[str, str] | None = None,
    plain_text: bool = False,
    style_guide: str = "",
) -> dict[str, Any]:
    """Async sliding window translation with concurrent batch processing.

    This function uses short-lived database sessions to avoid holding locks
    during the long-running translation process.

    Args:
        video_id: ID of the video to translate
        db: Database session (kept for backward compatibility, not used)
        model_name: OpenAI model name (default: 'gpt-5.4-mini')
        window_size: Segments per batch (default: 20)
        overlap: Overlapping segments between batches (default: 10)
        glossary: Optional glossary dict for term enforcement
        style_guide: Optional compact style-guide text (tone, formality,
            audience) from the unified extraction call, injected into every
            batch's translation prompt

    Returns:
        Dict with video_id, status, translated_count, total_segments, success flag
    """
    progress_tracker = get_progress_tracker(video_id, None)

    with SessionLocal() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video not found: {video_id}")

        source_language = video.source_language or "en"
        target_language = video.target_language
        if not target_language:
            raise ValueError("Target language is not set for this video.")

        all_segments = (
            db.query(Segment)
            .filter(Segment.video_id == video_id)
            .order_by(Segment.sequence_number)
            .all()
        )

        if not all_segments:
            raise ValueError("No segments to translate")

        total_segments = len(all_segments)

        video.status = VideoStatus.TRANSLATING.value
        video.total_segments = total_segments
        video.processed_segments = 0
        db.commit()

        all_segment_dicts = [
            {
                "id": seg.id,
                "sequence_number": seg.sequence_number,
                "original_text": seg.original_text,
            }
            for seg in all_segments
        ]

    step_started_here = False
    if progress_tracker._current_step_name != "TRANSLATING":
        progress_tracker.start_step(
            "TRANSLATING",
            f"Async sliding window: {total_segments} segments, "
            f"window={window_size}, max_concurrent={5}",
        )
        step_started_here = True

    try:
        client = get_async_openai_client()

        progress_tracker.info("TRANSLATING", "Creating sliding window batches...")
        full_transcript_text = "\n".join(
            [str(seg["original_text"]) for seg in all_segment_dicts]
        )

        batches = create_sliding_windows(
            all_segment_dicts,
            window_size,
            overlap,
            glossary,
            full_transcript_text,
            style_guide,
        )

        progress_tracker.info(
            "TRANSLATING",
            f"Created {len(batches)} batches from {total_segments} segments",
            f"Window: {window_size}, Overlap: {overlap}, Step: {window_size - overlap}",
        )

        start_time = time.time()
        batch_results = await translate_batches_concurrently(
            video_id=video_id,
            batches=batches,
            client=client,
            model_name=model_name,
            source_language=source_language,
            target_language=target_language,
            progress_tracker=progress_tracker,
            plain_text=plain_text,
        )
        elapsed = time.time() - start_time

        failed_batches = [r for r in batch_results if not r.success]
        if failed_batches:
            errors = " | ".join(
                f"batch {r.batch_index + 1}: {r.error}" for r in failed_batches[:3]
            )
            progress_tracker.error(
                "TRANSLATING",
                f"{len(failed_batches)}/{len(batches)} batches failed",
                errors,
            )
            raise RuntimeError(
                f"{len(failed_batches)}/{len(batches)} translation batches failed. "
                f"First errors: {errors}"
            )

        progress_tracker.info("TRANSLATING", "Merging batch translations...")
        final_translations, extracted_terms = merge_translations(
            batch_results, all_segment_dicts, window_size, overlap
        )

        progress_tracker.info(
            "TRANSLATING",
            f"Merged into {len(final_translations)} final translations",
            f"Extracted {len(extracted_terms)} terms in {elapsed:.2f}s",
        )

        progress_tracker.info("TRANSLATING", "Saving translations to database...")

        translation_count = bulk_save_segments_with_short_sessions(
            video_id=video_id,
            translations=final_translations,
            batch_size=50,
            progress_tracker=progress_tracker,
        )

        with SessionLocal() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.COMPLETED.value
                video.progress_percent = 100
                video.processed_segments = translation_count
                video.current_step = (
                    f"Translation complete: {translation_count}/"
                    f"{total_segments} segments"
                )
                db.commit()

        if step_started_here:
            progress_tracker.end_step(
                f"Async translation complete: {translation_count} segments, "
                f"{len(batches)} batches in {elapsed:.2f}s"
            )

    except Exception as e:
        with SessionLocal() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.ERROR.value
                video.error_message = str(e)
                db.commit()

        progress_tracker.error("TRANSLATING", "Translation failed", str(e))
        raise RuntimeError(f"Translation failed: {e}") from e

    with SessionLocal() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            return {
                "video_id": video_id,
                "status": video.status,
                "translated_count": video.processed_segments,
                "total_segments": video.total_segments,
                "success": video.status == VideoStatus.COMPLETED.value,
            }
        return {"video_id": video_id, "status": "not_found", "success": False}


def translate_video_sliding_window(
    video_id: str,
    db: Session | None = None,
    model_name: str = "gpt-5.4-mini",
    glossary: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Synchronous wrapper for async sliding window translation.

    Args:
        video_id: ID of the video to translate
        db: Database session (kept for backward compatibility)
        model_name: OpenAI model name
        glossary: Optional glossary dict

    Returns:
        Dict with video_id, status, translated_count, total_segments, success flag
    """
    return asyncio.run(
        translate_video_sliding_window_async(
            video_id, db, model_name, glossary=glossary
        )
    )


# Backward compatibility aliases
translate_video = translate_video_sliding_window


def translate_video_simple(
    video_id: str,
    db: Session,
    model_name: str = "gpt-5.4-mini",
) -> dict[str, Any]:
    """DEPRECATED: Use translate_video_sliding_window() instead.

    Simple translation without context analysis.
    Kept for backward compatibility but not recommended.
    """
    import warnings

    warnings.warn(
        "translate_video_simple() is deprecated. "
        "Use translate_video_sliding_window() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return translate_video_sliding_window(video_id, model_name=model_name)
