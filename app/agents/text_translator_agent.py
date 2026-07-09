"""Text Translator Agent — plain-text translation with glossary enforcement.

Translates written-text segments using OpenAI Chat Completions.  This agent is
completely separate from the subtitle translator so video formatting constraints
never leak into text translations.
"""

import asyncio
import json
import re
from typing import Any

from openai import AsyncOpenAI, RateLimitError
from pydantic import BaseModel, Field, ValidationError

from app.agents.translator import DEFAULT_TRANSLATION_MODEL, get_async_openai_client
from app.core.languages import LANGUAGE_NAMES
from app.db.session import SessionLocal
from app.models.video import Segment, Term, TermSource, Video, VideoStatus
from app.services.progress_service import get_progress_tracker


class TextTranslationItem(BaseModel):
    sequence_number: int
    translated_text: str


class TextTranslationResponse(BaseModel):
    translations: list[TextTranslationItem] = Field(..., min_length=1)


MAX_RETRIES = 5
BASE_RETRY_DELAY = 2
RATE_LIMIT_DELAY = 10
MAX_CONCURRENT_CALLS = 5


def _build_text_glossary(terms: list[Term]) -> dict[str, str]:
    """Build a simple glossary dict from Term rows."""
    glossary: dict[str, str] = {}
    for term in terms:
        source = term.original_term
        target = term.standardized_term or term.translated_term
        if not source or not target:
            continue
        # Strip category prefix if present (e.g. "[Technical] foo")
        target = re.sub(r"^\s*\[.*?\]\s*", "", target).strip()
        glossary[source.lower()] = target
    return glossary


def _build_system_instruction(glossary: dict[str, str], target_language: str) -> str:
    target_lang_name = LANGUAGE_NAMES.get(target_language, target_language)
    lines = [
        "You are a professional text translator.",
        f"CRITICAL TARGET LANGUAGE RULE: Your output must be 100% in "
        f"{target_lang_name}. Do not output any words, phrases, numbers, or "
        f"punctuation in the source language or English. The entire response "
        f"must be strictly and exclusively {target_lang_name}.",
    ]
    if glossary:
        lines.append(
            "You are bound by the following MANDATORY glossary rules. "
            "These terms are NON-NEGOTIABLE:"
        )
        lines.append("")
        for term, translation in glossary.items():
            lines.append(f"{term} == {translation}")
            lines.append(
                f"If the source text contains {term}, you MUST use "
                f"{translation}. You may add grammatical suffixes/prefixes as "
                f"needed, but the core meaning must not change."
            )
        lines.append("")
        lines.append("Obey these rules for every translation.")
    return "\n".join(lines)


def _build_batch_prompt(
    batch: list[Segment],
    target_language: str,
    source_language: str | None,
    full_text: str,
) -> str:
    target_lang_name = LANGUAGE_NAMES.get(target_language, target_language)
    source_clause = (
        f"from {source_language} "
        if source_language and source_language != "auto"
        else ""
    )
    segments_text = "\n".join(
        f"[{seg.sequence_number}] {seg.original_text}" for seg in batch
    )

    return f"""You are executing a professional translation pass {source_clause}to {target_lang_name}.

FULL DOCUMENT CONTEXT (read this first for narrative continuity):
{full_text}

TRANSLATE THESE SEGMENTS:
{segments_text}

CRITICAL INSTRUCTIONS:
1. Use the full document context to maintain consistent terminology and tone.
2. You MUST translate ALL content into {target_lang_name} only.
3. Return a translation for EVERY sequence number in the batch.
4. Do not merge or drop segments.
5. Preserve paragraph breaks and sentence boundaries naturally.

Return STRICTLY as JSON with this exact format:
{{
  "translations": [
    {{
      "sequence_number": <int>,
      "translated_text": "<translated text>"
    }}
  ]
}}
"""


async def _translate_batch(
    batch: list[Segment],
    client: AsyncOpenAI,
    model_name: str,
    system_instruction: str,
    target_language: str,
    source_language: str | None,
    full_text: str,
    progress_tracker: Any,
    semaphore: asyncio.Semaphore,
) -> dict[int, str]:
    prompt = _build_batch_prompt(batch, target_language, source_language, full_text)

    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_completion_tokens=8192,
                )
                break
            except RateLimitError as e:
                if attempt < MAX_RETRIES - 1:
                    delay = RATE_LIMIT_DELAY * (2 ** attempt)
                    progress_tracker.warning(
                        "TEXT_TRANSLATING",
                        f"Batch rate limited (attempt {attempt + 1}); retrying in {delay}s",
                        str(e),
                    )
                    await asyncio.sleep(delay)
                else:
                    raise
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_RETRY_DELAY * (2 ** attempt)
                    progress_tracker.warning(
                        "TEXT_TRANSLATING",
                        f"Batch failed (attempt {attempt + 1}); retrying in {delay}s",
                        str(e),
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

    response_text = response.choices[0].message.content or ""
    json_match = re.search(
        r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL
    )
    if json_match:
        response_text = json_match.group(1)
    response_text = response_text.strip()

    try:
        parsed = json.loads(response_text)
        validated = TextTranslationResponse(**parsed)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response: {e}") from e
    except ValidationError as e:
        raise ValueError(f"JSON validation failed: {e}") from e

    return {
        t.sequence_number: t.translated_text
        for t in validated.translations
    }


async def translate_text_document(
    video_id: str,
    model_name: str = DEFAULT_TRANSLATION_MODEL,
    batch_size: int = 30,
) -> dict[str, Any]:
    """Translate all segments of a text document.

    Loads segments and glossary terms, translates in batches, and writes
    translated_text back to the Segment table.
    """
    progress_tracker = get_progress_tracker(video_id, None)

    # Keep the session open for the whole translation so segment objects
    # remain bound while batches read original_text and write translated_text.
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Text record not found: {video_id}")
        if video.status == VideoStatus.ERROR.value:
            raise RuntimeError(f"Text record {video_id} is in ERROR status")

        source_language = video.source_language or "auto"
        target_language = video.target_language
        if not target_language:
            raise ValueError("Target language is not set")

        segments = (
            db.query(Segment)
            .filter(Segment.video_id == video_id)
            .order_by(Segment.sequence_number)
            .all()
        )
        if not segments:
            raise ValueError("No segments found for text translation")

        terms = (
            db.query(Term)
            .filter(Term.video_id == video_id)
            .all()
        )
        glossary = _build_text_glossary(terms)

        video.status = VideoStatus.TRANSLATING.value
        db.commit()

        total_segments = len(segments)
        full_text = "\n\n".join(
            f"[{seg.sequence_number}] {seg.original_text}" for seg in segments
        )
        system_instruction = _build_system_instruction(glossary, target_language)

    except Exception:
        db.close()
        raise

    progress_tracker.start_step(
        "TEXT_TRANSLATING",
        f"Translating {total_segments} text segments with {len(glossary)} glossary terms",
    )
    progress_tracker.update_progress(
        status=VideoStatus.TRANSLATING.value,
        percent=0,
        current_step="Text Translation",
        step_detail="Preparing batches...",
    )

    # Build batches
    batches: list[list[Segment]] = []
    for i in range(0, total_segments, batch_size):
        batches.append(segments[i : i + batch_size])

    client = get_async_openai_client()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)

    tasks = [
        _translate_batch(
            batch=batch,
            client=client,
            model_name=model_name,
            system_instruction=system_instruction,
            target_language=target_language,
            source_language=source_language,
            full_text=full_text,
            progress_tracker=progress_tracker,
            semaphore=semaphore,
        )
        for batch in batches
    ]

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        progress_tracker.error("TEXT_TRANSLATING", "Batch translation failed", str(e))
        raise

    translations: dict[int, str] = {}
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            progress_tracker.error(
                "TEXT_TRANSLATING",
                f"Batch {i + 1} failed",
                str(result),
            )
            raise RuntimeError(
                f"Text translation batch {i + 1} failed: {result}"
            ) from result
        translations.update(result)

    # Save translations
    saved_count = 0
    for seg in db.query(Segment).filter(Segment.video_id == video_id).all():
        translated = translations.get(seg.sequence_number)
        if translated:
            seg.translated_text = translated
            saved_count += 1

    video = db.query(Video).filter(Video.id == video_id).first()
    if video:
        video.status = VideoStatus.COMPLETED.value
        video.progress_percent = 100
        video.processed_segments = saved_count
        video.current_step = f"Translation complete: {saved_count}/{total_segments} segments"
        db.commit()

    db.close()

    progress_tracker.end_step(
        f"Text translation complete: {saved_count}/{total_segments} segments"
    )
    progress_tracker.update_progress(
        status=VideoStatus.COMPLETED.value,
        percent=100,
        current_step="Text Translation",
        step_detail=f"Saved {saved_count} translations",
        total_segments=total_segments,
        processed_segments=saved_count,
    )

    return {
        "video_id": video_id,
        "status": VideoStatus.COMPLETED.value,
        "total_segments": total_segments,
        "translated_segments": saved_count,
        "success": True,
    }
