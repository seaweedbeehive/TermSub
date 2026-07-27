"""Translation Pipeline — Translator Agent orchestration.

Context analysis, terminology extraction, and style-guide generation now
happen in a single unified call (app.services.context_analysis_service) —
see that module's docstring. This module previously also hosted a "Director
Agent" and "Glossary Agent" that duplicated that work in a disconnected,
never-called code path; they've been removed rather than fixed, since the
unified call replaces what they were trying to do. What remains here is the
live Translator Agent: it reads the approved glossary and style guide from
the database and runs the actual sliding-window translation.

Usage:
    pipeline = TranslationPipeline()
    result = await pipeline.translate_with_glossary(video_id)
"""

import asyncio
import json
import re
from typing import Any

from app.agents.translator import (
    DEFAULT_OVERLAP,
    DEFAULT_WINDOW_SIZE,
    get_async_openai_client,
)
from app.db.session import SessionLocal
from app.models.video import ContentType, Segment, Term, TermSource, Video, VideoStatus
from app.services.gemini_service import translate_video_sliding_window_async
from app.services.progress_service import get_progress_tracker


def _format_style_guide_text(style_guide: dict[str, Any]) -> str:
    """Render a style-guide dict (from the unified extraction call) into
    compact text for the translation prompt's STYLE GUIDE section."""
    if not style_guide:
        return ""

    tone = style_guide.get("tone", "")
    formality_level = style_guide.get("formality_level")
    target_audience = style_guide.get("target_audience", "")
    style_notes = style_guide.get("style_notes") or []
    language_considerations = style_guide.get("language_considerations") or {}

    lines = []
    if tone:
        lines.append(f"- Tone: {tone}")
    if formality_level:
        lines.append(f"- Formality Level: {formality_level}/5")
    if target_audience:
        lines.append(f"- Target Audience: {target_audience}")
    if style_notes:
        lines.append("Style Notes:")
        lines.extend(f"- {note}" for note in style_notes)
    if language_considerations:
        lines.append("Language Considerations:")
        lines.extend(f"- {k}: {v}" for k, v in language_considerations.items())

    return "\n".join(lines)


# ============================================================================
# Translation Pipeline
# ============================================================================


class TranslationPipeline:
    """Translator Agent: runs sliding-window translation with the approved
    glossary and style guide (both produced upstream by the unified
    extraction call in context_analysis_service.py).

    This class uses short-lived database sessions to avoid holding locks during
    long-running LLM API calls.

    Attributes:
        client: OpenAI async client instance
    """

    def __init__(self) -> None:
        """Initialize the translation pipeline.

        Uses short-lived database sessions internally.
        """
        self.client = get_async_openai_client()

    async def _send_progress(self, status: str, message: str, **kwargs: Any) -> None:
        """Send progress update via WebSocket."""
        print(f"[Pipeline] {status}: {message}")

    async def translate_with_glossary(
        self, video_id: str, glossary: list[Term] | None = None
    ) -> dict[str, Any]:
        """Translator Agent: Translate using sliding window with glossary.

        Uses short-lived database sessions to avoid holding locks during LLM calls.

        Args:
            video_id: ID of the video to translate
            glossary: Optional list of approved terms to use during translation

        Returns:
            Dict with video_id, status, total_segments, translated_segments, success

        Raises:
            ValueError: If video not found
            RuntimeError: If translation fails
        """
        with SessionLocal() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise ValueError(f"Video not found: {video_id}")

            if video.status == VideoStatus.ERROR.value:
                raise RuntimeError(
                    f"Video {video_id} is in ERROR status, aborting translation"
                )

            plain_text = video.content_type == ContentType.TEXT.value

            style_guide_text = ""
            if video.style_guide:
                style_guide_text = _format_style_guide_text(
                    json.loads(video.style_guide)
                )

            auto_terms = (
                db.query(Term)
                .filter(Term.video_id == video_id, Term.source == TermSource.AUTO.value)
                .all()
            )
            manual_terms = (
                db.query(Term)
                .filter(
                    Term.video_id == video_id, Term.source == TermSource.MANUAL.value
                )
                .all()
            )
            db_terms = auto_terms + manual_terms

            if glossary is not None:
                # The passed glossary was built at task-start time. User edits made
                # just before clicking Translate may not be reflected there. Treat
                # database terms as the source of truth, but keep any passed terms
                # that are not yet persisted.
                term_map = {t.original_term: t for t in glossary}
                for t in db_terms:
                    existing = term_map.get(t.original_term)
                    if existing is None:
                        term_map[t.original_term] = t
                    elif t.source == TermSource.MANUAL.value:
                        # Manual/custom terms always win.
                        term_map[t.original_term] = t
                    elif t.standardized_term and not existing.standardized_term:
                        # User-edited auto terms win over the stale extracted version.
                        term_map[t.original_term] = t
                    # Otherwise keep the passed term.
                glossary = list(term_map.values())
            else:
                glossary = db_terms

            glossary_dict = {}
            sorted_glossary = sorted(
                glossary, key=lambda t: 0 if t.source == TermSource.AUTO.value else 1
            )
            for term in sorted_glossary:
                if term.source == TermSource.MANUAL.value:
                    translation = term.translated_term
                else:
                    translation = term.standardized_term or term.translated_term
                if term.original_term and translation:
                    translation = re.sub(r"\s*\[.*?\]", "", translation).strip()
                    normalized_original = (
                        term.original_term.lower().replace("-", " ").strip()
                    )
                    glossary_dict[normalized_original] = translation

            total_segments = len(
                db.query(Segment).filter(Segment.video_id == video_id).all()
            )

            video.status = VideoStatus.TRANSLATING.value
            db.commit()

        progress_tracker = get_progress_tracker(video_id, None)

        await self._send_progress(
            "translating",
            message="Translator Agent starting translation with glossary",
            glossary_size=len(glossary_dict),
            progress=0,
        )

        progress_tracker.start_step(
            "TRANSLATING",
            f"Translator Agent: Translating with {len(glossary_dict)} glossary terms",
        )

        try:
            step = DEFAULT_WINDOW_SIZE - DEFAULT_OVERLAP
            num_batches = (total_segments + step - 1) // step

            print(
                f"\n[TranslatorAgent] Starting batch translation "
                f"with {num_batches} batches"
            )
            print(
                f"[TranslatorAgent] Total segments: {total_segments}, "
                f"Window: {DEFAULT_WINDOW_SIZE}, Overlap: {DEFAULT_OVERLAP}"
            )
            print(f"[TranslatorAgent] Using glossary with {len(glossary_dict)} terms")

            await translate_video_sliding_window_async(
                video_id=video_id,
                model_name="gpt-5.4-mini",
                window_size=DEFAULT_WINDOW_SIZE,
                overlap=DEFAULT_OVERLAP,
                glossary=glossary_dict,
                plain_text=plain_text,
                style_guide=style_guide_text,
            )

            video_status = "unknown"
            total_segs = 0
            processed_segs = 0
            with SessionLocal() as db:
                video = db.query(Video).filter(Video.id == video_id).first()
                if video:
                    video.status = VideoStatus.COMPLETED.value
                    video_status = video.status
                    total_segs = video.total_segments
                    processed_segs = video.processed_segments
                    db.commit()

            await self._send_progress(
                "completed",
                message="Translation finished successfully",
                total_segments=total_segs,
                processed_segments=processed_segs,
            )

            progress_tracker.end_step("Translator Agent complete: translation finished")

            return {
                "video_id": video_id,
                "status": video_status,
                "total_segments": total_segs,
                "translated_segments": processed_segs,
                "success": True,
            }

        except Exception as e:
            with SessionLocal() as db:
                video = db.query(Video).filter(Video.id == video_id).first()
                if video:
                    video.status = VideoStatus.ERROR.value
                    video.error_message = str(e)
                    db.commit()

            await self._send_progress(
                "error", message=f"Translation failed: {str(e)}", error=str(e)
            )

            progress_tracker.error("TRANSLATING", "Translator Agent failed", str(e))
            raise RuntimeError(f"Translation failed: {e}") from e

    # ============================================================================
    # Synchronous versions for background worker (thread-based)
    # ============================================================================

    def translate_with_glossary_sync(
        self, video_id: str, glossary: list[Term] | None = None
    ) -> dict[str, Any]:
        """Synchronous version of translate_with_glossary for background worker."""
        return asyncio.run(self.translate_with_glossary(video_id, glossary))
