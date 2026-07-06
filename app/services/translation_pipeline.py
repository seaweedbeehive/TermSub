"""Multi-Agent Translation Pipeline - Director/Glossary/Translator Architecture.

This module implements a multi-agent translation system with three specialized agents:
1. Director Agent: Analyzes content and generates style guide (tone, formality, style)
2. Glossary Agent: Extracts key terms (names, places, technical terms) before translation
3. Translator Agent: Performs actual translation using sliding windows with glossary constraints

Supports WebSocket progress updates for real-time client notifications.

Usage:
    pipeline = TranslationPipeline(websocket_manager, video_id)

    # Step 1: Analyze context (Director Agent)
    style_guide = await pipeline.analyze_context(video_id)

    # Step 2: Extract glossary (Glossary Agent)
    terms = await pipeline.extract_glossary(video_id, style_guide)
    # ... user reviews and edits terms ...

    # Step 3: Translate with glossary (Translator Agent)
    video = await pipeline.translate_with_glossary(video_id, glossary)
"""  # noqa: E501

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agents.translator import (
    DEFAULT_OVERLAP,
    DEFAULT_WINDOW_SIZE,
    get_async_openai_client,
)
from app.db.session import SessionLocal
from app.models.video import Segment, Term, TermSource, Video, VideoStatus
from app.services.gemini_service import translate_video_sliding_window_async
from app.services.progress_service import get_progress_tracker

# ============================================================================
# Pydantic Schemas for LLM Response Validation
# ============================================================================


class StyleGuideSchema(BaseModel):
    """Pydantic schema for Director Agent style guide response."""

    tone: str = Field(default="neutral", min_length=1, max_length=100)
    formality_level: int = Field(default=3, ge=1, le=5)
    target_audience: str = Field(default="general", min_length=1)
    style_notes: list[str] = Field(default_factory=list)
    domain: str = Field(default="general", min_length=1)
    language_considerations: dict[str, str] = Field(default_factory=dict)


class ExtractedTermSchema(BaseModel):
    """Pydantic schema for a single extracted term."""

    original_term: str = Field(..., min_length=1, description="Term in source language")
    proposed_translation: str = Field(
        ..., min_length=1, description="Suggested translation"
    )
    category: str = Field(default="Concept", description="Term category")
    context: str = Field(default="", description="Usage context")


class GlossaryResponseSchema(BaseModel):
    """Pydantic schema for Glossary Agent response."""

    terms: list[ExtractedTermSchema] = Field(default_factory=list)


# ============================================================================
# Response Parser with Validation
# ============================================================================


class LLMResponseParser:
    """Parser for LLM responses with JSON extraction and validation."""

    @staticmethod
    def extract_json(text: str) -> str | None:
        """Extract JSON from markdown code blocks or plain text."""
        patterns = [
            r"```(?:json)?\s*\n?(.*?)\n?```",
            r"\{.*\}",
            r"\[.*\]",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1) if match.groups() else match.group(0)

        return None

    @staticmethod
    def parse_style_guide(text: str) -> StyleGuideSchema | None:
        """Parse and validate style guide response."""
        try:
            json_str = LLMResponseParser.extract_json(text)
            if json_str:
                data = json.loads(json_str)
                return StyleGuideSchema(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"[LLMResponseParser] Style guide validation failed: {e}")

        return None

    @staticmethod
    def parse_glossary(text: str) -> GlossaryResponseSchema | None:
        """Parse and validate glossary response."""
        try:
            json_str = LLMResponseParser.extract_json(text)
            if json_str:
                data = json.loads(json_str)
                return GlossaryResponseSchema(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"[LLMResponseParser] Glossary validation failed: {e}")

        return None


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class StyleGuide:
    """Style guide for translation (output from Director Agent)."""

    tone: str = "neutral"
    formality_level: int = 3
    target_audience: str = "general"
    style_notes: list[str] = field(default_factory=list)
    domain: str = "general"
    language_considerations: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tone": self.tone,
            "formality_level": self.formality_level,
            "target_audience": self.target_audience,
            "style_notes": self.style_notes,
            "domain": self.domain,
            "language_considerations": self.language_considerations,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StyleGuide":
        return cls(
            tone=data.get("tone", "neutral"),
            formality_level=data.get("formality_level", 3),
            target_audience=data.get("target_audience", "general"),
            style_notes=data.get("style_notes", []),
            domain=data.get("domain", "general"),
            language_considerations=data.get("language_considerations", {}),
        )

    def to_prompt_text(self) -> str:
        notes = "\n".join(f"- {note}" for note in self.style_notes)
        considerations = "\n".join(
            f"- {k}: {v}" for k, v in self.language_considerations.items()
        )

        return f"""Style Guide:
- Tone: {self.tone}
- Formality Level: {self.formality_level}/5
- Target Audience: {self.target_audience}
- Domain: {self.domain}

Style Notes:
{notes}

Language Considerations:
{considerations}"""


# ============================================================================
# Translation Pipeline
# ============================================================================


class TranslationPipeline:
    """Multi-agent translation pipeline with Director, Glossary, and Translator agents.

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

    async def analyze_context(self, video_id: str) -> StyleGuide:
        """Director Agent: Analyze content and generate style guide.

        Uses short-lived database sessions to avoid holding locks during LLM calls.

        Args:
            video_id: ID of the video to analyze

        Returns:
            StyleGuide object with analysis results

        Raises:
            ValueError: If video not found or no segments
        """
        with SessionLocal() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise ValueError(f"Video not found: {video_id}")

            if video.status == VideoStatus.ERROR.value:
                raise RuntimeError(
                    f"Video {video_id} is in ERROR status, aborting analysis"
                )

            target_language = video.target_language
            if not target_language:
                raise ValueError("Target language is not set for this video.")
            segments = (
                db.query(Segment)
                .filter(Segment.video_id == video_id)
                .order_by(Segment.sequence_number)
                .all()
            )

            if not segments:
                raise ValueError("No segments to analyze")

            sample_segments = segments[: min(100, len(segments))]
            transcript = "\n".join(
                [
                    f"[{seg.sequence_number}] {seg.original_text}"
                    for seg in sample_segments
                ]
            )

            video.status = VideoStatus.ANALYZING.value
            db.commit()

        progress_tracker = get_progress_tracker(video_id, None)

        await self._send_progress(
            "analyzing",
            message="Director Agent analyzing content style and context",
            total_segments=len(segments),
        )

        progress_tracker.start_step(
            "ANALYZING",
            f"Director Agent: Analyzing content style and context "
            f"({len(segments)} segments)",
        )

        try:
            print(
                f"\n[DirectorAgent] Analyzing full transcript "
                f"for video {video_id[:8]}..."
            )
            print(f"[DirectorAgent] Total segments: {len(segments)}")

            from app.core.languages import LANGUAGE_NAMES

            target_lang_name = LANGUAGE_NAMES.get(target_language, target_language)

            prompt = f"""You are a Director Agent analyzing video content for translation.

Analyze this transcript and create a style guide for translating to {target_lang_name}.

TRANSCRIPT SAMPLE:
{transcript}

Provide a JSON style guide with this exact structure:
{{
    "tone": "<e.g., formal, casual, professional, conversational>",
    "formality_level": <1-5, where 1 is very casual, 5 is very formal>,
    "target_audience": "<description of intended audience>",
    "style_notes": [
        "<specific style instruction 1>",
        "<specific style instruction 2>"
    ],
    "domain": "<e.g., technical, medical, educational, entertainment, general>",
    "language_considerations": {{
        "<key point>": "<explanation>"
    }}
}}

Consider:
- Is this educational, entertainment, technical, or promotional content?
- What tone would resonate with {target_lang_name} speakers?
- Are there cultural considerations for the translation?
"""  # noqa: E501

            progress_tracker.info(
                "ANALYZING", "Sending to Director Agent for analysis..."
            )

            response = await self.client.chat.completions.create(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_completion_tokens=4096,
            )

            response_text = response.choices[0].message.content or ""

            validated = LLMResponseParser.parse_style_guide(response_text)

            if validated:
                style_guide = StyleGuide(
                    tone=validated.tone,
                    formality_level=validated.formality_level,
                    target_audience=validated.target_audience,
                    style_notes=validated.style_notes,
                    domain=validated.domain,
                    language_considerations=validated.language_considerations,
                )
            else:
                print("[DirectorAgent] Warning: Using fallback style guide parsing")
                json_str = LLMResponseParser.extract_json(response_text)
                if json_str:
                    data = json.loads(json_str)
                    style_guide = StyleGuide.from_dict(data)
                else:
                    style_guide = StyleGuide(
                        tone="neutral",
                        formality_level=3,
                        target_audience="general",
                        style_notes=["Use clear and natural language"],
                        domain="general",
                        language_considerations={},
                    )

            print(
                f"[DirectorAgent] Analysis complete: {style_guide.tone} tone, "
                f"formality {style_guide.formality_level}/5"
            )
            print(f"[DirectorAgent] Domain: {style_guide.domain}")

            with SessionLocal() as db:
                video = db.query(Video).filter(Video.id == video_id).first()
                if video:
                    video.style_guide = json.dumps(style_guide.to_dict())
                    video.status = VideoStatus.CONTEXT_READY.value
                    db.commit()

            await self._send_progress(
                "context_ready",
                message=f"Director Agent complete: {style_guide.tone} tone",
                tone=style_guide.tone,
                formality_level=style_guide.formality_level,
                domain=style_guide.domain,
            )

            progress_tracker.end_step(
                f"Director Agent complete: {style_guide.tone} tone, "
                f"formality {style_guide.formality_level}/5"
            )

            return style_guide

        except Exception as e:
            with SessionLocal() as db:
                video_record = db.query(Video).filter(Video.id == video_id).first()
                if video_record:
                    video_record.status = VideoStatus.ERROR.value
                    video_record.error_message = str(e)
                    db.commit()

            await self._send_progress(
                "error", message=f"Director Agent failed: {str(e)}", error=str(e)
            )

            progress_tracker.error("ANALYZING", "Director Agent failed", str(e))
            raise RuntimeError(f"Context analysis failed: {e}") from e

    async def extract_glossary(
        self, video_id: str, style_guide: StyleGuide | None = None
    ) -> list[Term]:
        """Glossary Agent: Extract key terms before translation.

        Uses short-lived database sessions to avoid holding locks during LLM calls.

        Args:
            video_id: ID of the video
            style_guide: Optional style guide from Director Agent

        Returns:
            List of Term objects created (saved to database)

        Raises:
            ValueError: If video not found or no segments
        """
        with SessionLocal() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if not video:
                raise ValueError(f"Video not found: {video_id}")

            if video.status == VideoStatus.ERROR.value:
                raise RuntimeError(
                    f"Video {video_id} is in ERROR status, aborting glossary extraction"
                )

            segments = (
                db.query(Segment)
                .filter(Segment.video_id == video_id)
                .order_by(Segment.sequence_number)
                .all()
            )

            if not segments:
                raise ValueError("No segments to process")

            transcript = "\n".join(
                [f"[{seg.sequence_number}] {seg.original_text}" for seg in segments]
            )

            raw_source_language = video.source_language or "en"
            # "auto" is meaningless to the LLM; default to English or try to infer
            source_language = (
                raw_source_language if raw_source_language != "auto" else "en"
            )
            target_language = video.target_language
            if not target_language:
                raise ValueError("Target language is not set for this video.")

            style_text = ""
            if style_guide is None and video.style_guide:
                sg = StyleGuide.from_dict(json.loads(video.style_guide))
                style_text = f"\nContent Domain: {sg.domain}\nStyle: {sg.tone}"

        progress_tracker = get_progress_tracker(video_id, None)

        await self._send_progress(
            "glossary_extracting",
            message="Glossary Agent extracting key terms",
            total_segments=len(segments),
        )

        progress_tracker.start_step(
            "GLOSSARY",
            f"Glossary Agent: Extracting key terms ({len(segments)} segments)",
        )

        try:
            print("\n[GlossaryAgent] Extracting glossary terms...")
            print(f"[GlossaryAgent] Analyzing {len(segments)} segments")

            from app.core.languages import LANGUAGE_NAMES

            target_lang_name = LANGUAGE_NAMES.get(target_language, target_language)
            source_lang_name = LANGUAGE_NAMES.get(source_language, source_language)

            prompt = f"""You are a Glossary Agent extracting key terms for translation.

Extract ALL proper nouns, technical terms, names, places, and key concepts from this transcript that need consistent translation.

SOURCE LANGUAGE: {source_lang_name}
TARGET LANGUAGE: {target_lang_name}{style_text}

TRANSCRIPT:
{transcript[:5000]}

Return JSON with this structure:
{{
    "terms": [
        {{
            "original_term": "<term in {source_lang_name} — DO NOT translate this field>",
            "proposed_translation": "<suggested translation in {target_lang_name}>",
            "category": "<Name|Place|Technical|Concept|Organization>",
            "context": "<brief context or usage example>"
        }}
    ]
}}

CRITICAL: The original_term MUST be preserved exactly as it appears in the transcript's source language ({source_lang_name}). Do NOT translate the source terms.

EXAMPLE — CORRECT (English source, Farsi target):
  {{"original_term": "machine learning", "proposed_translation": "یادگیری ماشین", "category": "Technical"}}
EXAMPLE — WRONG (English source, Farsi target):
  {{"original_term": "یادگیری ماشین", "proposed_translation": "یادگیری ماشین", "category": "Technical"}}

Focus on:
1. People names (preserve or transliterate appropriately)
2. Place names (use established {target_lang_name} conventions)
3. Technical terms (domain-specific translations)
4. Organizations and brands
5. Key concepts that recur in the text

Only include terms that actually appear in the text.
"""  # noqa: E501

            progress_tracker.info(
                "GLOSSARY", "Sending to Glossary Agent for term extraction..."
            )

            response = await self.client.chat.completions.create(
                model="gpt-5.4-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_completion_tokens=4096,
            )

            response_text = response.choices[0].message.content or ""

            validated = LLMResponseParser.parse_glossary(response_text)

            if validated:
                term_data_list = validated.terms
            else:
                print("[GlossaryAgent] Warning: Using fallback glossary parsing")
                json_str = LLMResponseParser.extract_json(response_text)
                if json_str:
                    data = json.loads(json_str)
                    term_data_list = data.get("terms", [])
                else:
                    term_data_list = []

            with SessionLocal() as db:
                terms = []
                for term_data in term_data_list:
                    original_term = term_data.original_term
                    proposed_translation = term_data.proposed_translation
                    category = term_data.category

                    if original_term and proposed_translation:
                        from app.models.video import TermSource

                        term = Term(
                            video_id=video_id,
                            original_term=original_term,
                            translated_term=proposed_translation,
                            category=category,
                            frequency=1,
                            is_standardized=False,
                            source=TermSource.AUTO.value,
                        )
                        db.add(term)
                        terms.append(term)

                video = db.query(Video).filter(Video.id == video_id).first()
                if video:
                    video.status = VideoStatus.TERMS_READY.value
                    db.commit()

            print(f"[GlossaryAgent] Extracted {len(terms)} terms")

            await self._send_progress(
                "terms_ready",
                message=f"Found {len(terms)} terms to review",
                terms_count=len(terms),
                terms=[
                    {
                        "id": t.id,
                        "original_term": t.original_term,
                        "proposed_translation": t.translated_term,
                        "category": t.category,
                    }
                    for t in terms[:10]
                ],
            )

            progress_tracker.end_step(
                f"Glossary Agent complete: extracted {len(terms)} terms for review"
            )

            return terms

        except Exception as e:
            with SessionLocal() as db:
                video = db.query(Video).filter(Video.id == video_id).first()
                if video:
                    video.status = VideoStatus.ERROR.value
                    video.error_message = str(e)
                    db.commit()

            await self._send_progress(
                "error", message=f"Glossary Agent failed: {str(e)}", error=str(e)
            )

            progress_tracker.error("GLOSSARY", "Glossary Agent failed", str(e))
            raise RuntimeError(f"Glossary extraction failed: {e}") from e

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
                # The passed glossary comes from extract_glossary() and was built at
                # task-start time. User edits made just before clicking Translate may
                # not be reflected there. Treat database terms as the source of truth,
                # but keep any passed terms that are not yet persisted.
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

    async def run_full_pipeline(self, video_id: str) -> dict[str, Any]:
        """Run the complete multi-agent pipeline.

        Convenience method to run all three agents in sequence:
        1. Director (analyze context)
        2. Glossary (extract terms)
        3. Translator (translate with glossary)

        Args:
            video_id: ID of the video

        Returns:
            Dict with pipeline results and final status
        """
        style_guide = await self.analyze_context(video_id)
        terms = await self.extract_glossary(video_id, style_guide)
        result = await self.translate_with_glossary(video_id, terms)

        return result

    # ============================================================================
    # Synchronous versions for background worker (thread-based)
    # ============================================================================

    def analyze_context_sync(self, video_id: str) -> StyleGuide:
        """Synchronous version of analyze_context for background worker."""
        return asyncio.run(self.analyze_context(video_id))

    def extract_glossary_sync(
        self, video_id: str, style_guide: StyleGuide | None = None
    ) -> list[Term]:
        """Synchronous version of extract_glossary for background worker."""
        return asyncio.run(self.extract_glossary(video_id, style_guide))

    def translate_with_glossary_sync(
        self, video_id: str, glossary: list[Term] | None = None
    ) -> dict[str, Any]:
        """Synchronous version of translate_with_glossary for background worker."""
        return asyncio.run(self.translate_with_glossary(video_id, glossary))
