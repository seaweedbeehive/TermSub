"""OpenAI Translator Agent — sliding-window batch translation.

Replaces Gemini with OpenAI Chat Completions while preserving the exact
sliding-window batching, prompt context injection, and strict glossary
tracking architecture.

Key design choices:
- Uses AsyncOpenAI for all LLM calls (the pipeline is async throughout).
- gpt-5.4-mini is the default model; gpt-5.4 can be passed via model_name.
- JSON output is requested via system prompt instructions (OpenAI does not
  support forced JSON schema on chat completions the same way Gemini does,
  so we use strict prompt instructions + Pydantic validation).
"""

import asyncio
import contextlib
import functools
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from openai import AsyncOpenAI, RateLimitError
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_CONCURRENT_CALLS = 2
DEFAULT_WINDOW_SIZE = 20
DEFAULT_OVERLAP = 10
MAX_RETRIES = 5
BASE_RETRY_DELAY = 2  # seconds
RATE_LIMIT_DELAY = 10  # seconds
RETRYABLE_EXCEPTIONS = (Exception,)
DEFAULT_TRANSLATION_MODEL = "gpt-5.4-mini"


# ---------------------------------------------------------------------------
# Pydantic Models for JSON Validation
# ---------------------------------------------------------------------------


class ExtractedTermSchema(BaseModel):
    """Schema for extracted terms from translation."""

    term: str = Field(..., min_length=1, description="Original term")
    translation: str = Field(..., min_length=1, description="Translated term")


class TranslationItemSchema(BaseModel):
    """Schema for a single translated segment."""

    sequence_number: int = Field(..., ge=1, description="Segment sequence number")
    translated_text: str = Field(..., min_length=0, description="Translated text")
    extracted_terms: list[ExtractedTermSchema] = Field(default_factory=list)


class TranslationResponseSchema(BaseModel):
    """Schema for translation response."""

    translations: list[TranslationItemSchema] = Field(
        ..., min_length=1, description="List of translated segments"
    )


# ---------------------------------------------------------------------------
# Retry Decorator with Exponential Backoff
# ---------------------------------------------------------------------------

T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_RETRY_DELAY,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple[type[Exception], ...] = RETRYABLE_EXCEPTIONS,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator for retrying async functions with exponential backoff."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt == max_retries - 1:
                        raise last_exception from e
                    delay = base_delay * (backoff_factor**attempt)
                    if on_retry:
                        with contextlib.suppress(Exception):
                            on_retry(attempt + 1, e, delay)
                    await asyncio.sleep(delay)
            raise last_exception if last_exception else RuntimeError("Retry failed")

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class TranslationBatch:
    """Represents a batch of segments to be translated with context."""

    batch_index: int
    segments: list[dict[str, Any]]
    context_before: str = ""
    context_after: str = ""
    glossary: dict[str, str] = field(default_factory=dict)
    full_transcript_text: str = ""
    style_guide: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_index": self.batch_index,
            "segments": [
                {
                    "id": s["id"],
                    "sequence_number": s["sequence_number"],
                    "text": s["original_text"],
                }
                for s in self.segments
            ],
            "context_before": self.context_before,
            "context_after": self.context_after,
            "glossary": self.glossary,
        }


@dataclass
class BatchResult:
    """Result of translating a single batch."""

    batch_index: int
    translations: list[dict[str, Any]] = field(default_factory=list)
    extracted_terms: list[dict[str, Any]] = field(default_factory=list)
    success: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# OpenAI Client
# ---------------------------------------------------------------------------


def get_async_openai_client(api_key: str | None = None) -> AsyncOpenAI:
    """Initialize and return an AsyncOpenAI client.

    Args:
        api_key: Optional per-request API key. Falls back to the active BYOK
            context, then to settings.OPENAI_API_KEY.

    Raises:
        RuntimeError: If no API key is available.
    """
    from app.core.openai_key_context import get_effective_openai_key

    effective_key = get_effective_openai_key(api_key)
    if not effective_key:
        raise RuntimeError(
            "OPENAI_API_KEY not configured. Please enter your API key in the UI "
            "before proceeding."
        )
    return AsyncOpenAI(api_key=effective_key)


# ---------------------------------------------------------------------------
# Sliding Window Functions
# ---------------------------------------------------------------------------


def create_sliding_windows(
    segments: list[dict[str, Any]],
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    glossary: dict[str, str] | None = None,
    full_transcript_text: str = "",
    style_guide: str = "",
) -> list[TranslationBatch]:
    """Create overlapping sliding window batches from segments."""
    if not segments:
        return []

    batches: list[TranslationBatch] = []
    step = window_size - overlap

    for i in range(0, len(segments), step):
        batch_segments = segments[i : i + window_size]
        if not batch_segments:
            break

        context_before = ""
        if i > 0:
            prev_segments = segments[max(0, i - 2) : i]
            context_before = "\n".join(
                [
                    f"[{s['sequence_number']}] {s['original_text']}"
                    for s in prev_segments
                ]
            )

        context_after = ""
        next_start = i + window_size
        if next_start < len(segments):
            next_segments = segments[next_start : min(len(segments), next_start + 2)]
            context_after = "\n".join(
                [
                    f"[{s['sequence_number']}] {s['original_text']}"
                    for s in next_segments
                ]
            )

        batch = TranslationBatch(
            batch_index=len(batches),
            segments=batch_segments,
            context_before=context_before,
            context_after=context_after,
            glossary=glossary or {},
            full_transcript_text=full_transcript_text,
            style_guide=style_guide,
        )
        batches.append(batch)

    return batches


# ---------------------------------------------------------------------------
# Prompt Builders
# ---------------------------------------------------------------------------


def build_system_instruction(batch: TranslationBatch, target_language: str = "") -> str:
    """Build the system instruction containing mandatory glossary rules."""
    from app.core.languages import LANGUAGE_NAMES

    target_lang_name = LANGUAGE_NAMES.get(target_language, target_language)

    lines = [
        "You are a professional subtitle translator.",
        f"CRITICAL TARGET LANGUAGE RULE: Your output must be 100% in "
        f"{target_lang_name}. "
        f"Do not output any words, phrases, numbers, or punctuation in the "
        f"source language or English. "
        f"The entire response must be strictly and exclusively {target_lang_name}.",
    ]
    if batch.glossary:
        lines.append(
            "You are bound by the following MANDATORY glossary rules. "
            "These terms are NON-NEGOTIABLE:"
        )
        lines.append("")
        for term, translation in batch.glossary.items():
            lines.append(f"{term} == {translation}")
            lines.append(
                f"If the source text contains {term}, you MUST use the "
                f"{translation} for the provided {term}. "
                f"The core meaning of the term must not change, but grammatical "
                f"correctness ALWAYS takes priority over inserting the glossary "
                f"form unchanged: conjugate verbs, adjust for gender/number/case, "
                f"add or drop suffixes/prefixes/particles, and reorder words as "
                f"needed so the sentence reads naturally in the target language. "
                f"Never output a raw infinitive, dictionary form, or otherwise "
                f"ungrammatical fragment just to match the glossary text exactly."
            )
        lines.append("")
        lines.append("You must obey these rules for every translation you produce.")
    return "\n".join(lines)


def build_translation_prompt(
    batch: TranslationBatch,
    source_language: str,
    target_language: str,
    style_guide: str = "",
    plain_text: bool = False,
) -> str:
    """Build the translation prompt with context and constraints."""
    from app.core.languages import LANGUAGE_NAMES

    target_lang_name = LANGUAGE_NAMES.get(target_language, target_language)

    context_before_section = ""
    if batch.context_before:
        context_before_section = f"""
PREVIOUS CONTEXT (already translated, for reference):
{batch.context_before}
"""

    context_after_section = ""
    if batch.context_after:
        context_after_section = f"""
FUTURE PREVIEW (next segments for context):
{batch.context_after}
"""

    full_context_section = ""
    if batch.full_transcript_text:
        full_context_section = (
            "\nCRITICAL CONTEXT: Here is the complete transcript of the entire video. "
            "Read this to understand the overarching narrative, tone, and "
            "subject matter before translating the segments below:\n\n"
            f"{batch.full_transcript_text}\n"
        )

    segments_text = "\n".join(
        [f"[{s['sequence_number']}] {s['original_text']}" for s in batch.segments]
    )

    style_section = (
        f"""
STYLE GUIDE:
{style_guide}
"""
        if style_guide
        else ""
    )

    source_lang_clause = (
        f"from {source_language} "
        if source_language and source_language != "auto"
        else ""
    )
    formatting_instructions = (
        "2. STRICT BROADCAST STANDARDS: Maximum 42 characters per line. Maximum "
        "2 lines per subtitle card. If a speaker talks continuously, break their "
        "speech logically at natural breath pauses, conjunctions, or punctuation "
        "to match the rhythm of an edit. Never output a single massive block of "
        "text.\n"
        if not plain_text
        else ""
    )
    prompt = (
        f"You are executing a professional translation pass "
        f"{source_lang_clause}to {target_lang_name}.\n"
        f"\n"
        f"{style_section}"
        f"{full_context_section}"
        f"{context_before_section}\n"
        f"\n"
        f"TRANSLATE THESE SEGMENTS:\n"
        f"{segments_text}\n"
        f"\n"
        f"{context_after_section}\n"
        f"\n"
        f"CRITICAL EDITORIAL INSTRUCTIONS:\n"
        f"1. NARRATIVE CONTINUITY: Use the Full Transcript to understand the "
        f"overarching story, and rely on PREVIOUS/FUTURE context for coherent "
        f"pacing and voice.\n"
        f"{formatting_instructions}"
        f"3. MANDATORY GLOSSARY: You are strictly bound by the glossary rules "
        f"defined in your system instructions. If a term appears, the required "
        f"translation is non-negotiable.\n"
        f"4. ABSOLUTE TARGET LANGUAGE: You must translate ALL content into "
        f"{target_lang_name} only. No source language remnants, numbers, or "
        f"punctuation are allowed.\n"
        f"5. 1:1 SEGMENT MATCH: You must return a translated node for every single "
        f"sequence number provided in the batch. Do not merge or drop segments.\n"
        f"\n"
        f"Return STRICTLY as JSON with this exact format:\n"
        f"{{\n"
        f'  "translations": [\n'
        f"    {{\n"
        f'      "sequence_number": <int>,\n'
        f'      "translated_text": "<translated text>",\n'
        f'      "extracted_terms": [{{"term": "<term>", '
        f'"translation": "<translation>"}}]\n'
        f"    }}\n"
        f"  ]\n"
        f"}}\n"
    )
    return prompt


# ---------------------------------------------------------------------------
# Translation with Retry Logic
# ---------------------------------------------------------------------------


async def translate_single_batch(
    batch: TranslationBatch,
    client: AsyncOpenAI,
    model_name: str,
    source_language: str,
    target_language: str,
    progress_tracker: Any,
    semaphore: asyncio.Semaphore,
    retry_attempt: int = 0,
    plain_text: bool = False,
) -> BatchResult:
    """Translate a single batch with JSON validation."""
    if not target_language or not str(target_language).strip():
        raise ValueError(
            "Target language is missing or empty. Cannot translate without a "
            "target language."
        )

    prompt = build_translation_prompt(
        batch,
        source_language,
        target_language,
        style_guide=batch.style_guide,
        plain_text=plain_text,
    )
    system_instruction = build_system_instruction(batch, target_language)

    logger.debug("Final Glossary being sent to LLM: %s", batch.glossary)

    async with semaphore:
        start_time = time.time()

        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_completion_tokens=8192,
        )

        elapsed = time.time() - start_time

        response_text = response.choices[0].message.content or ""

        # Extract JSON from markdown code blocks if present
        json_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", response_text, re.DOTALL
        )
        if json_match:
            response_text = json_match.group(1)
        response_text = response_text.strip()

        # Parse and validate JSON using Pydantic
        try:
            parsed_json = json.loads(response_text)
            validated = TranslationResponseSchema(**parsed_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON response: {e}") from e
        except ValidationError as e:
            raise ValueError(f"JSON validation failed: {e}") from e

        if not validated.translations:
            raise ValueError("Empty translations in response")

        translations: list[dict[str, Any]] = []
        all_terms: list[dict[str, str]] = []

        for t in validated.translations:
            extracted_terms: list[dict[str, str]] = [
                {"term": et.term, "translation": et.translation}
                for et in t.extracted_terms
            ]
            trans_dict: dict[str, Any] = {
                "sequence_number": t.sequence_number,
                "translated_text": t.translated_text,
                "extracted_terms": extracted_terms,
            }
            translations.append(trans_dict)
            all_terms.extend(extracted_terms)

        if progress_tracker:
            attempt_str = f" (retry {retry_attempt})" if retry_attempt > 0 else ""
            progress_tracker.info(
                "TRANSLATING",
                f"Batch {batch.batch_index + 1} translated{attempt_str}",
                f"Got {len(translations)} translations in {elapsed:.2f}s",
            )

        return BatchResult(
            batch_index=batch.batch_index,
            translations=translations,
            extracted_terms=all_terms,
            success=True,
        )


async def translate_single_batch_with_retry(
    batch: TranslationBatch,
    client: AsyncOpenAI,
    model_name: str,
    source_language: str,
    target_language: str,
    progress_tracker: Any,
    semaphore: asyncio.Semaphore,
    plain_text: bool = False,
) -> BatchResult:
    """Translate a single batch with exponential backoff retry.

    Uses a longer backoff for OpenAI 429 (Too Many Requests) errors so that
    rate-limited batches wait and retry instead of being dropped.
    """
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            return await translate_single_batch(
                batch=batch,
                client=client,
                model_name=model_name,
                source_language=source_language,
                target_language=target_language,
                progress_tracker=progress_tracker,
                semaphore=semaphore,
                retry_attempt=attempt,
                plain_text=plain_text,
            )
        except RateLimitError as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RATE_LIMIT_DELAY * (2**attempt)
                if progress_tracker:
                    progress_tracker.warning(
                        "TRANSLATING",
                        f"Batch {batch.batch_index + 1} rate limited "
                        f"(attempt {attempt + 1}), retrying in {delay}s",
                        str(e),
                    )
                await asyncio.sleep(delay)
            else:
                if progress_tracker:
                    progress_tracker.error(
                        "TRANSLATING",
                        f"Batch {batch.batch_index + 1} rate limited after "
                        f"{MAX_RETRIES} attempts",
                        str(e),
                    )
                return BatchResult(
                    batch_index=batch.batch_index,
                    success=False,
                    error=str(e),
                )
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = BASE_RETRY_DELAY * (2**attempt)
                if progress_tracker:
                    progress_tracker.warning(
                        "TRANSLATING",
                        f"Batch {batch.batch_index + 1} failed "
                        f"(attempt {attempt + 1}), retrying in {delay}s",
                        str(e),
                    )
                await asyncio.sleep(delay)
            else:
                if progress_tracker:
                    progress_tracker.error(
                        "TRANSLATING",
                        f"Batch {batch.batch_index + 1} failed after "
                        f"{MAX_RETRIES} attempts",
                        str(e),
                    )
                return BatchResult(
                    batch_index=batch.batch_index,
                    success=False,
                    error=str(e),
                )

    return BatchResult(
        batch_index=batch.batch_index,
        success=False,
        error=str(last_error) if last_error else "Unknown error",
    )


# ---------------------------------------------------------------------------
# Concurrent Translation
# ---------------------------------------------------------------------------


async def translate_batches_concurrently(
    video_id: str,
    batches: list[TranslationBatch],
    client: AsyncOpenAI,
    model_name: str,
    source_language: str,
    target_language: str,
    progress_tracker: Any,
    plain_text: bool = False,
) -> list[BatchResult]:
    """Translate all batches concurrently with semaphore-controlled concurrency.

    A fresh semaphore is created for every call so it is always bound to the
    currently running event loop.  This avoids the "bound to a different event
    loop" error that can occur when Celery reuses worker threads.
    """
    if not batches:
        return []

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)

    tasks = [
        translate_single_batch_with_retry(
            batch=batch,
            client=client,
            model_name=model_name,
            source_language=source_language,
            target_language=target_language,
            progress_tracker=progress_tracker,
            semaphore=semaphore,
            plain_text=plain_text,
        )
        for batch in batches
    ]

    if progress_tracker:
        progress_tracker.info(
            "TRANSLATING",
            f"Starting concurrent translation of {len(batches)} batches",
            f"Max concurrent: {MAX_CONCURRENT_CALLS}",
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    processed_results: list[BatchResult] = []
    for i, result in enumerate(results):
        # asyncio.gather(..., return_exceptions=True) can surface BaseException
        # (e.g. asyncio.CancelledError), which is not a subclass of Exception -
        # checking only Exception would let a cancelled batch's raw exception
        # get cast() (a no-op at runtime) into BatchResult below, silently
        # masquerading as a real result until something downstream crashes on it.
        if isinstance(result, BaseException):
            processed_results.append(
                BatchResult(
                    batch_index=i,
                    success=False,
                    error=str(result),
                )
            )
        else:
            processed_results.append(result)

    return processed_results


# ---------------------------------------------------------------------------
# Merge Overlapping Batch Translations
# ---------------------------------------------------------------------------


def merge_translations(
    batches_results: list[BatchResult],
    segments: list[dict[str, Any]],
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge overlapping batch translations into final segment translations.

    For overlapping regions, prefer translations from the batch where the segment
    appears in the middle (not at the edges), as this has better context.
    """
    step = window_size - overlap
    final_translations = []
    all_extracted_terms = []

    translation_map: dict[int, dict[str, Any]] = {}

    for batch_result in batches_results:
        if not batch_result.success:
            continue

        batch_index = batch_result.batch_index
        batch_start = batch_index * step
        batch_end = min(batch_start + window_size, len(segments))

        for translation in batch_result.translations:
            seq_num = translation.get("sequence_number")
            if seq_num is None:
                continue

            position_in_batch = seq_num - batch_start - 1
            if position_in_batch < 0 or position_in_batch >= (batch_end - batch_start):
                continue

            priority: float = batch_index
            is_overlap = position_in_batch < overlap and batch_index > 0
            if is_overlap:
                priority = batch_index + 0.5

            if (
                seq_num not in translation_map
                or translation_map[seq_num]["priority"] < priority
            ):
                translation_map[seq_num] = {
                    "sequence_number": seq_num,
                    "translated_text": translation.get("translated_text", ""),
                    "priority": priority,
                }

        all_extracted_terms.extend(batch_result.extracted_terms)

    final_translations = [
        translation_map[seq_num] for seq_num in sorted(translation_map.keys())
    ]

    return final_translations, all_extracted_terms
