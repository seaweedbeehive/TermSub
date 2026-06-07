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

import json
import re
import time
import asyncio
import functools
import threading
import logging
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional, Any, Callable, TypeVar
from collections import defaultdict

from pydantic import BaseModel, Field, ValidationError
from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_CONCURRENT_CALLS = 5
DEFAULT_WINDOW_SIZE = 20
DEFAULT_OVERLAP = 10
MAX_RETRIES = 3
BASE_RETRY_DELAY = 2  # seconds
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
    extracted_terms: List[ExtractedTermSchema] = Field(default_factory=list)


class TranslationResponseSchema(BaseModel):
    """Schema for translation response."""
    translations: List[TranslationItemSchema] = Field(
        ...,
        min_length=1,
        description="List of translated segments"
    )


# ---------------------------------------------------------------------------
# Retry Decorator with Exponential Backoff
# ---------------------------------------------------------------------------

T = TypeVar('T')


def retry_with_backoff(
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_RETRY_DELAY,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = RETRYABLE_EXCEPTIONS,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None
) -> Callable:
    """Decorator for retrying async functions with exponential backoff."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt == max_retries - 1:
                        raise last_exception
                    delay = base_delay * (backoff_factor ** attempt)
                    if on_retry:
                        try:
                            on_retry(attempt + 1, e, delay)
                        except Exception:
                            pass
                    await asyncio.sleep(delay)
            raise last_exception if last_exception else RuntimeError("Retry failed")
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Thread-Safe Semaphore Management
# ---------------------------------------------------------------------------

class SemaphoreManager:
    """Thread-safe semaphore manager for API concurrency control."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_CALLS):
        self.max_concurrent = max_concurrent
        self._local = threading.local()

    def get_semaphore(self) -> asyncio.Semaphore:
        if not hasattr(self._local, 'semaphore'):
            self._local.semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._local.semaphore


_semaphore_manager = SemaphoreManager(MAX_CONCURRENT_CALLS)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class TranslationBatch:
    """Represents a batch of segments to be translated with context."""
    batch_index: int
    segments: List[Dict[str, Any]]
    context_before: str = ""
    context_after: str = ""
    glossary: Dict[str, str] = field(default_factory=dict)
    full_transcript_text: str = ""

    def to_dict(self) -> dict:
        return {
            "batch_index": self.batch_index,
            "segments": [
                {"id": s["id"], "sequence_number": s["sequence_number"], "text": s["original_text"]}
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
    translations: List[Dict[str, Any]] = field(default_factory=list)
    extracted_terms: List[Dict[str, Any]] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# OpenAI Client
# ---------------------------------------------------------------------------

def get_async_openai_client(api_key: str | None = None) -> AsyncOpenAI:
    """Initialize and return an AsyncOpenAI client.

    Args:
        api_key: Optional per-request API key. Falls back to settings.OPENAI_API_KEY.

    Raises:
        RuntimeError: If no API key is available.
    """
    effective_key = api_key or settings.OPENAI_API_KEY
    if not effective_key:
        raise RuntimeError(
            "OPENAI_API_KEY not configured. Please enter your API key in the UI before proceeding."
        )
    return AsyncOpenAI(api_key=effective_key)


# ---------------------------------------------------------------------------
# Sliding Window Functions
# ---------------------------------------------------------------------------

def create_sliding_windows(
    segments: List[Dict[str, Any]],
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    glossary: Optional[Dict[str, str]] = None,
    full_transcript_text: str = "",
) -> List[TranslationBatch]:
    """Create overlapping sliding window batches from segments."""
    if not segments:
        return []

    batches = []
    step = window_size - overlap

    for i in range(0, len(segments), step):
        batch_segments = segments[i:i + window_size]
        if not batch_segments:
            break

        context_before = ""
        if i > 0:
            prev_segments = segments[max(0, i - 2):i]
            context_before = "\n".join([
                f"[{s['sequence_number']}] {s['original_text']}"
                for s in prev_segments
            ])

        context_after = ""
        next_start = i + window_size
        if next_start < len(segments):
            next_segments = segments[next_start:min(len(segments), next_start + 2)]
            context_after = "\n".join([
                f"[{s['sequence_number']}] {s['original_text']}"
                for s in next_segments
            ])

        batch = TranslationBatch(
            batch_index=len(batches),
            segments=batch_segments,
            context_before=context_before,
            context_after=context_after,
            glossary=glossary or {},
            full_transcript_text=full_transcript_text,
        )
        batches.append(batch)

    return batches


# ---------------------------------------------------------------------------
# Prompt Builders
# ---------------------------------------------------------------------------

def build_system_instruction(batch: TranslationBatch, target_language: str = "") -> str:
    """Build the system instruction containing mandatory glossary rules."""
    lang_names = {
        "fa": "Persian (Farsi)", "en": "English", "de": "German", "fr": "French",
        "es": "Spanish", "it": "Italian", "ja": "Japanese", "ko": "Korean",
        "zh": "Chinese", "ar": "Arabic", "ru": "Russian", "tr": "Turkish",
    }
    target_lang_name = lang_names.get(target_language, target_language)

    lines = [
        "You are a professional subtitle translator.",
        f"CRITICAL TARGET LANGUAGE RULE: Your output must be 100% in {target_lang_name}. "
        f"Do not output any words, phrases, numbers, or punctuation in the source language or English. "
        f"The entire response must be strictly and exclusively {target_lang_name}.",
    ]
    if batch.glossary:
        lines.append("You are bound by the following MANDATORY glossary rules. These terms are NON-NEGOTIABLE:")
        lines.append("")
        for term, translation in batch.glossary.items():
            lines.append(f"{term} == {translation}")
            lines.append(
                f"If the source text contains {term}, you MUST use the {translation} for the provided {term}. "
                f"However, you are allowed to add necessary grammatical suffixes, prefixes, or particles "
                f"appropriate to ensure the sentence is grammatically perfect in the target language. "
                f"The core meaning of the term must not change."
            )
        lines.append("")
        lines.append("You must obey these rules for every translation you produce.")
    return "\n".join(lines)


def build_translation_prompt(
    batch: TranslationBatch,
    source_language: str,
    target_language: str,
    style_guide: str = ""
) -> str:
    """Build the translation prompt with context and constraints."""
    lang_names = {
        "fa": "Persian (Farsi)", "en": "English", "de": "German", "fr": "French",
        "es": "Spanish", "it": "Italian", "ja": "Japanese", "ko": "Korean",
        "zh": "Chinese", "ar": "Arabic", "ru": "Russian", "tr": "Turkish",
    }
    target_lang_name = lang_names.get(target_language, target_language)

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
        full_context_section = f"""
CRITICAL CONTEXT: Here is the complete transcript of the entire video. Read this to understand the overarching narrative, tone, and subject matter before translating the segments below:

{batch.full_transcript_text}
"""

    segments_text = "\n".join([
        f"[{s['sequence_number']}] {s['original_text']}"
        for s in batch.segments
    ])

    style_section = f"""
STYLE GUIDE:
{style_guide}
""" if style_guide else ""

    prompt = f"""You are executing a professional subtitle translation pass from {source_language} to {target_lang_name}.

{style_section}
{full_context_section}
{context_before_section}

TRANSLATE THESE SPECIFIC TIMELINE SEGMENTS:
{segments_text}

{context_after_section}

CRITICAL EDITORIAL & FORMATTING INSTRUCTIONS:
1. NARRATIVE CONTINUITY: You must use the Full Transcript to understand the overarching story, but rely on the PREVIOUS and FUTURE context to nail the immediate pacing, conversational subtext, and character voice for this specific batch.
2. STRICT BROADCAST STANDARDS: Maximum 42 characters per line. Maximum 2 lines per subtitle card. If a speaker talks continuously, break their speech logically at natural breath pauses, conjunctions, or punctuation to match the rhythm of an edit. Never output a single massive block of text.
3. MANDATORY GLOSSARY: You are strictly bound by the glossary rules defined in your system instructions. If a term appears, the required translation is non-negotiable.
4. ABSOLUTE TARGET LANGUAGE: You must translate ALL content into {target_lang_name} only. No source language remnants, numbers, or punctuation are allowed.
5. 1:1 SEGMENT MATCH: You must return a translated node for every single sequence number provided in the batch. Do not merge or drop segments.

Return STRICTLY as JSON with this exact format:
{{
  "translations": [
    {{
      "sequence_number": <int>,
      "translated_text": "<translated text>",
      "extracted_terms": [{{"term": "<term>", "translation": "<translation>"}}]
    }}
  ]
}}
"""
    return prompt


# ---------------------------------------------------------------------------
# Translation with Retry Logic
# ---------------------------------------------------------------------------

@retry_with_backoff(
    max_retries=MAX_RETRIES,
    base_delay=BASE_RETRY_DELAY,
    backoff_factor=2.0
)
async def translate_single_batch(
    batch: TranslationBatch,
    client: AsyncOpenAI,
    model_name: str,
    source_language: str,
    target_language: str,
    progress_tracker: Any,
    retry_attempt: int = 0,
) -> BatchResult:
    """Translate a single batch with retry logic and JSON validation."""
    if not target_language or not str(target_language).strip():
        raise ValueError("Target language is missing or empty. Cannot translate without a target language.")

    prompt = build_translation_prompt(batch, source_language, target_language)
    system_instruction = build_system_instruction(batch, target_language)

    logger.debug("Final Glossary being sent to LLM: %s", batch.glossary)

    semaphore = _semaphore_manager.get_semaphore()

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
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group(1)
        response_text = response_text.strip()

        # Parse and validate JSON using Pydantic
        try:
            parsed_json = json.loads(response_text)
            validated = TranslationResponseSchema(**parsed_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON response: {e}")
        except ValidationError as e:
            raise ValueError(f"JSON validation failed: {e}")

        if not validated.translations:
            raise ValueError("Empty translations in response")

        translations = []
        all_terms = []

        for t in validated.translations:
            trans_dict = {
                "sequence_number": t.sequence_number,
                "translated_text": t.translated_text,
                "extracted_terms": [
                    {"term": et.term, "translation": et.translation}
                    for et in t.extracted_terms
                ]
            }
            translations.append(trans_dict)
            all_terms.extend(trans_dict["extracted_terms"])

        if progress_tracker:
            attempt_str = f" (retry {retry_attempt})" if retry_attempt > 0 else ""
            progress_tracker.info(
                "TRANSLATING",
                f"Batch {batch.batch_index + 1} translated{attempt_str}",
                f"Got {len(translations)} translations in {elapsed:.2f}s"
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
) -> BatchResult:
    """Translate a single batch with exponential backoff retry."""
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            return await translate_single_batch(
                batch=batch,
                client=client,
                model_name=model_name,
                source_language=source_language,
                target_language=target_language,
                progress_tracker=progress_tracker,
                retry_attempt=attempt,
            )
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = BASE_RETRY_DELAY * (2 ** attempt)
                if progress_tracker:
                    progress_tracker.warning(
                        "TRANSLATING",
                        f"Batch {batch.batch_index + 1} failed (attempt {attempt + 1}), retrying in {delay}s",
                        str(e)
                    )
                await asyncio.sleep(delay)
            else:
                if progress_tracker:
                    progress_tracker.error(
                        "TRANSLATING",
                        f"Batch {batch.batch_index + 1} failed after {MAX_RETRIES} attempts",
                        str(e)
                    )
                return BatchResult(
                    batch_index=batch.batch_index,
                    success=False,
                    error=str(e),
                )

    return BatchResult(
        batch_index=batch.batch_index,
        success=False,
        error=str(last_error) if last_error else "Unknown error"
    )


# ---------------------------------------------------------------------------
# Concurrent Translation
# ---------------------------------------------------------------------------

async def translate_batches_concurrently(
    video_id: str,
    batches: List[TranslationBatch],
    client: AsyncOpenAI,
    model_name: str,
    source_language: str,
    target_language: str,
    progress_tracker: Any,
) -> List[BatchResult]:
    """Translate all batches concurrently with semaphore-controlled concurrency."""
    if not batches:
        return []

    tasks = [
        translate_single_batch_with_retry(
            batch=batch,
            client=client,
            model_name=model_name,
            source_language=source_language,
            target_language=target_language,
            progress_tracker=progress_tracker,
        )
        for batch in batches
    ]

    if progress_tracker:
        progress_tracker.info(
            "TRANSLATING",
            f"Starting concurrent translation of {len(batches)} batches",
            f"Max concurrent: {MAX_CONCURRENT_CALLS}"
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed_results.append(BatchResult(
                batch_index=i,
                success=False,
                error=str(result),
            ))
        else:
            processed_results.append(result)

    return processed_results


# ---------------------------------------------------------------------------
# Merge Overlapping Batch Translations
# ---------------------------------------------------------------------------

def merge_translations(
    batches_results: List[BatchResult],
    segments: List[Dict[str, Any]],
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Merge overlapping batch translations into final segment translations.

    For overlapping regions, prefer translations from the batch where the segment
    appears in the middle (not at the edges), as this has better context.
    """
    step = window_size - overlap
    final_translations = []
    all_extracted_terms = []

    translation_map = {}

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

            priority = batch_index
            is_overlap = position_in_batch < overlap and batch_index > 0
            if is_overlap:
                priority = batch_index + 0.5

            if seq_num not in translation_map or translation_map[seq_num]["priority"] < priority:
                translation_map[seq_num] = {
                    "sequence_number": seq_num,
                    "translated_text": translation.get("translated_text", ""),
                    "priority": priority,
                }

        all_extracted_terms.extend(batch_result.extracted_terms)

    final_translations = [
        translation_map[seq_num]
        for seq_num in sorted(translation_map.keys())
    ]

    return final_translations, all_extracted_terms
