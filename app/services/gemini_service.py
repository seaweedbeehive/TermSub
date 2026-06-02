"""Gemini translation service - Async Sliding Window Translation with Concurrency Control.

This module implements high-performance batch translation using:
- Async/await pattern with asyncio
- Thread-safe semaphore-based concurrency limiting
- Sliding window overlap for context continuity
- Exponential backoff retry mechanism
- JSON response validation with Pydantic
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
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError
from google.genai import types
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.video import Video, VideoStatus, Segment, Term, TermOccurrence, TranslationVariant
from app.services.progress_service import get_progress_tracker


# Configuration constants
MAX_CONCURRENT_CALLS = 5
DEFAULT_WINDOW_SIZE = 20
DEFAULT_OVERLAP = 10
MAX_RETRIES = 3
BASE_RETRY_DELAY = 2  # seconds
RETRYABLE_EXCEPTIONS = (
    Exception,  # Broad catch for API errors - refine based on actual Gemini exceptions
)

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models for JSON Validation
# ============================================================================

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
    """Schema for Gemini translation response."""
    translations: List[TranslationItemSchema] = Field(
        ..., 
        min_length=1,
        description="List of translated segments"
    )


class StyleGuideSchema(BaseModel):
    """Schema for Director Agent style guide response."""
    tone: str = Field(default="neutral", min_length=1)
    formality_level: int = Field(default=3, ge=1, le=5)
    target_audience: str = Field(default="general", min_length=1)
    style_notes: List[str] = Field(default_factory=list)
    domain: str = Field(default="general", min_length=1)
    language_considerations: Dict[str, str] = Field(default_factory=dict)


class GlossaryResponseSchema(BaseModel):
    """Schema for Glossary Agent response."""
    terms: List[Dict[str, Any]] = Field(default_factory=list)


# ============================================================================
# Retry Decorator with Exponential Backoff
# ============================================================================

T = TypeVar('T')

def retry_with_backoff(
    max_retries: int = MAX_RETRIES,
    base_delay: float = BASE_RETRY_DELAY,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = RETRYABLE_EXCEPTIONS,
    on_retry: Optional[Callable[[int, Exception, float], None]] = None
) -> Callable:
    """Decorator for retrying async functions with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        backoff_factor: Multiplier for delay after each retry
        retryable_exceptions: Tuple of exceptions that should trigger retry
        on_retry: Optional callback function called on each retry (attempt, exception, delay)
        
    Returns:
        Decorated function
        
    Example:
        @retry_with_backoff(max_retries=3, base_delay=1.0)
        async def call_api():
            return await api.get_data()
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    
                    # Don't retry on last attempt
                    if attempt == max_retries - 1:
                        raise last_exception
                    
                    # Calculate delay with exponential backoff
                    delay = base_delay * (backoff_factor ** attempt)
                    
                    # Call retry callback if provided
                    if on_retry:
                        try:
                            on_retry(attempt + 1, e, delay)
                        except Exception:
                            pass  # Don't let callback errors break retry
                    
                    # Wait before retrying
                    await asyncio.sleep(delay)
            
            # Should never reach here, but just in case
            raise last_exception if last_exception else RuntimeError("Retry failed")
        
        return wrapper
    return decorator


# ============================================================================
# Thread-Safe Semaphore Management
# ============================================================================

class SemaphoreManager:
    """Thread-safe semaphore manager for API concurrency control.
    
    Creates semaphores within async contexts to ensure they work correctly
    across different threads (important for background workers).
    """
    
    def __init__(self, max_concurrent: int = MAX_CONCURRENT_CALLS):
        self.max_concurrent = max_concurrent
        self._local = threading.local()
    
    def get_semaphore(self) -> asyncio.Semaphore:
        """Get or create semaphore for current async context.
        
        Returns:
            asyncio.Semaphore instance
        """
        if not hasattr(self._local, 'semaphore'):
            self._local.semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._local.semaphore


# Global semaphore manager instance
_semaphore_manager = SemaphoreManager(MAX_CONCURRENT_CALLS)


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class TranslationBatch:
    """Represents a batch of segments to be translated with context.
    
    Attributes:
        batch_index: Unique index for this batch
        segments: List of segment dicts to translate (primitives only, not ORM objects)
        context_before: Translated text from previous batch (for continuity)
        context_after: Original text from next batch (for preview)
        glossary: Domain-specific glossary to enforce term consistency
        full_transcript_text: Complete original transcript of the entire video
    """
    batch_index: int
    segments: List[Dict[str, Any]]  # Dicts with id, sequence_number, original_text
    context_before: str = ""
    context_after: str = ""
    glossary: Dict[str, str] = field(default_factory=dict)
    full_transcript_text: str = ""
    
    def to_dict(self) -> dict:
        """Convert batch to dictionary for serialization."""
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
    """Result of translating a single batch.
    
    Attributes:
        batch_index: Index of the batch
        translations: List of translated segments
        extracted_terms: Terms extracted from this batch
        success: Whether the translation succeeded
        error: Error message if failed
    """
    batch_index: int
    translations: List[Dict[str, Any]] = field(default_factory=list)
    extracted_terms: List[Dict[str, Any]] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None


# ============================================================================
# Gemini API Functions
# ============================================================================

def test_gemini_connection() -> tuple[bool, str]:
    """Test if Gemini API is configured and working."""
    try:
        from google import genai
        
        if not settings.GEMINI_API_KEY:
            return False, "GEMINI_API_KEY not configured in .env file"
        
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents="Say 'API test successful' in 5 words or less."
        )
        
        if response and response.text:
            return True, f"API working! Response: {response.text[:50]}"
        else:
            return False, "API returned empty response"
            
    except Exception as e:
        return False, f"API error: {str(e)}"


def get_gemini_client() -> Any:
    """Initialize and return Gemini client."""
    try:
        from google import genai
    except ImportError:
        raise RuntimeError("google-genai not installed. Install with: pip install google-genai>=1.0.0")
    
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not configured")
    
    return genai.Client(api_key=settings.GEMINI_API_KEY)


# ============================================================================
# Sliding Window Functions
# ============================================================================

def create_sliding_windows(
    segments: List[Dict[str, Any]],
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    glossary: Optional[Dict[str, str]] = None,
    full_transcript_text: str = "",
) -> List[TranslationBatch]:
    """Create overlapping sliding window batches from segments.
    
    Each batch overlaps with the previous one to maintain context continuity.
    The overlap region helps the model maintain consistent terminology and style.
    
    Args:
        segments: List of segment dicts with id, sequence_number, original_text
        window_size: Number of segments per batch (default 20)
        overlap: Number of overlapping segments between batches (default 10)
    
    Returns:
        List of TranslationBatch objects
    
    Example:
        Batch 1: segments 0-19 (window_size=20)
        Batch 2: segments 10-29 (overlap=10)
        Batch 3: segments 20-39
        etc.
    """
    if not segments:
        return []
    
    batches = []
    step = window_size - overlap  # How many new segments per batch
    
    for i in range(0, len(segments), step):
        batch_segments = segments[i:i + window_size]
        
        if not batch_segments:
            break
        
        # Get context from previous batch (last 2 segments if available)
        context_before = ""
        if i > 0:
            prev_segments = segments[max(0, i - 2):i]
            context_before = "\n".join([
                f"[{s['sequence_number']}] {s['original_text']}"
                for s in prev_segments
            ])
        
        # Get preview of next batch (first 2 segments if available)
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
            lines.append(f"If the source text contains {term}, you MUST use the {translation} for the provided {term}. However, you are allowed to add necessary grammatical suffixes, prefixes, or particles appropriate to ensure the sentence is grammatically perfect in the target language. The core meaning of the term must not change.")
        lines.append("")
        lines.append("You must obey these rules for every translation you produce.")
    return "\n".join(lines)


def build_translation_prompt(
    batch: TranslationBatch,
    source_language: str,
    target_language: str,
    style_guide: str = ""
) -> str:
    """Build the translation prompt with context and constraints.
    
    Args:
        batch: The TranslationBatch to translate
        source_language: Source language code (e.g., 'en')
        target_language: Target language name (e.g., 'Persian')
        style_guide: Optional style guide instructions
    
    Returns:
        Formatted prompt string
    """
    lang_names = {
        "fa": "Persian (Farsi)", "en": "English", "de": "German", "fr": "French",
        "es": "Spanish", "it": "Italian", "ja": "Japanese", "ko": "Korean",
        "zh": "Chinese", "ar": "Arabic", "ru": "Russian", "tr": "Turkish",
    }
    target_lang_name = lang_names.get(target_language, target_language)
    
    # Build context sections
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
    
    # Build full transcript context section
    full_context_section = ""
    if batch.full_transcript_text:
        full_context_section = f"""
CRITICAL CONTEXT: Here is the complete transcript of the entire video. Read this to understand the overarching narrative, tone, and subject matter before translating the segments below:

{batch.full_transcript_text}
"""
    
    # Build segments to translate
    segments_text = "\n".join([
        f"[{s['sequence_number']}] {s['original_text']}"
        for s in batch.segments
    ])
    
    style_section = f"""
STYLE GUIDE:
{style_guide}
""" if style_guide else ""
    
    prompt = f"""Translate the following {source_language} subtitles to {target_lang_name}.
{full_context_section}{context_before_section}
TRANSLATE THESE SEGMENTS:
{segments_text}
{context_after_section}{style_section}
INSTRUCTIONS:
1. Maintain consistent terminology across all segments
2. Preserve the meaning, tone, and timing context
3. Use natural, conversational language suitable for subtitles
4. OBEY THE MANDATORY GLOSSARY IN YOUR SYSTEM INSTRUCTIONS — use the exact specified translations whenever the source terms appear
5. MANDATORY: You must use the provided glossary for translation. If a term is in the glossary, YOU MUST use that exact translation. This is a strict requirement.
6. Use previous context to maintain narrative flow and character voice
7. Return translations for ALL segments provided
8. CRITICAL SUBTITLE FORMATTING RULES: You must adhere to strict broadcast standards. Maximum 42 characters per line. Maximum 2 lines per subtitle card (Max 84 characters total). Never output a massive block of text. If a speaker talks continuously, break their speech into smaller, logical sentence fragments across multiple JSON segments.
9. ABSOLUTE TARGET LANGUAGE ENFORCEMENT: You must translate ALL content into {target_lang_name} only. Do not output any words, phrases, numbers, or punctuation in the source language or English. The entire response must be 100% {target_lang_name}. No exceptions.

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


# ============================================================================
# Translation with Retry Logic
# ============================================================================

@retry_with_backoff(
    max_retries=MAX_RETRIES,
    base_delay=BASE_RETRY_DELAY,
    backoff_factor=2.0
)
async def translate_single_batch(
    batch: TranslationBatch,
    client: Any,
    model_name: str,
    source_language: str,
    target_language: str,
    progress_tracker: Any,
    retry_attempt: int = 0,
) -> BatchResult:
    """Translate a single batch with retry logic and JSON validation.
    
    Args:
        batch: The TranslationBatch to translate
        client: Gemini API client
        model_name: Model name (e.g., 'gemini-2.5-flash')
        source_language: Source language code
        target_language: Target language code
        progress_tracker: Progress tracker for logging
        retry_attempt: Current retry attempt (for logging)
    
    Returns:
        BatchResult with translations or error
    """
    # Validate target language before any API call
    if not target_language or not str(target_language).strip():
        raise ValueError("Target language is missing or empty. Cannot translate without a target language.")
    
    prompt = build_translation_prompt(batch, source_language, target_language)
    system_instruction = build_system_instruction(batch, target_language)
    
    print(f"\n🚀 DEBUG: Final Glossary being sent to LLM: {batch.glossary}\n")
    
    # Get thread-local semaphore
    semaphore = _semaphore_manager.get_semaphore()
    
    async with semaphore:
        start_time = time.time()
        
        # Make async API call
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3,
                max_output_tokens=8192,
            )
        )
        
        elapsed = time.time() - start_time
        
        # Parse response
        response_text = response.text
        
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
        
        # Validate translations
        if not validated.translations:
            raise ValueError("Empty translations in response")
        
        # Convert back to dict format
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
    client: Any,
    model_name: str,
    source_language: str,
    target_language: str,
    progress_tracker: Any,
) -> BatchResult:
    """Translate a single batch with exponential backoff retry.
    
    This is a wrapper that handles the retry logic with progress tracking.
    
    Args:
        batch: The TranslationBatch to translate
        client: Gemini API client
        model_name: Model name (e.g., 'gemini-2.5-flash')
        source_language: Source language code
        target_language: Target language code
        progress_tracker: Progress tracker for logging
    
    Returns:
        BatchResult with translations or error
    """
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
                # Exponential backoff: 2s, 4s, 8s...
                delay = BASE_RETRY_DELAY * (2 ** attempt)
                if progress_tracker:
                    progress_tracker.warning(
                        "TRANSLATING",
                        f"Batch {batch.batch_index + 1} failed (attempt {attempt + 1}), retrying in {delay}s",
                        str(e)
                    )
                await asyncio.sleep(delay)
            else:
                # All retries exhausted
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
    
    # Should not reach here
    return BatchResult(
        batch_index=batch.batch_index,
        success=False,
        error=str(last_error) if last_error else "Unknown error"
    )


# ============================================================================
# Concurrent Translation
# ============================================================================

async def translate_batches_concurrently(
    video_id: str,
    batches: List[TranslationBatch],
    client: Any,
    model_name: str,
    source_language: str,
    target_language: str,
    progress_tracker: Any,
) -> List[BatchResult]:
    """Translate all batches concurrently with semaphore-controlled concurrency.
    
    Args:
        video_id: Video ID for logging
        batches: List of TranslationBatch objects
        client: Gemini API client
        model_name: Model name
        source_language: Source language code
        target_language: Target language code
        progress_tracker: Progress tracker
    
    Returns:
        List of BatchResult objects
    """
    if not batches:
        return []
    
    # Create tasks for all batches
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
    
    # Execute all tasks concurrently (semaphore limits actual concurrency)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Convert exceptions to failed BatchResults
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


# ============================================================================
# Merge and Save Functions
# ============================================================================

def merge_translations(
    batches_results: List[BatchResult],
    segments: List[Dict[str, Any]],
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Merge overlapping batch translations into final segment translations.
    
    For overlapping regions, we use translations from the batch where the segment
    appears in the middle (not at the edges), as this has better context.
    
    Args:
        batches_results: List of BatchResult from translation
        segments: Original list of segment dicts with id, sequence_number, original_text
        window_size: Size of each batch window
        overlap: Number of overlapping segments
    
    Returns:
        Tuple of (final_translations, extracted_terms)
    """
    step = window_size - overlap
    final_translations = []
    all_extracted_terms = []
    
    # Create a map of sequence_number -> best translation
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
            
            # Calculate position within batch (0 = start, window_size = end)
            position_in_batch = seq_num - batch_start - 1  # sequence_number is 1-based
            
            # Determine quality score based on position
            # Middle of batch = best (more context)
            # Edges of batch = lower priority
            if position_in_batch < 0 or position_in_batch >= (batch_end - batch_start):
                continue  # Outside this batch's range
            
            # Simple priority: prefer translations from batches where segment is not at edges
            # For overlap regions, later batches have the segment closer to their start
            # but with more future context
            priority = batch_index
            
            # For the overlap region, prefer the second batch (has more context)
            is_overlap = position_in_batch < overlap and batch_index > 0
            if is_overlap:
                priority = batch_index + 0.5  # Slightly higher priority
            
            # Update if this is the first translation or higher priority
            if seq_num not in translation_map or translation_map[seq_num]["priority"] < priority:
                translation_map[seq_num] = {
                    "sequence_number": seq_num,
                    "translated_text": translation.get("translated_text", ""),
                    "priority": priority,
                }
        
        # Collect extracted terms
        all_extracted_terms.extend(batch_result.extracted_terms)
    
    # Convert map to sorted list
    final_translations = [
        translation_map[seq_num]
        for seq_num in sorted(translation_map.keys())
    ]
    
    return final_translations, all_extracted_terms


def bulk_save_segments(
    db: Session,
    video: Video,
    translations: List[Dict[str, Any]],
    all_segments: List[Segment],
    batch_size: int = 50,
    progress_tracker: Any = None,
) -> int:
    """Bulk save segment translations to database with efficient batch commits.
    
    This function collects all translations in memory and performs bulk updates
    in batches of 50 segments, committing only once per batch. This is much
    more efficient than individual segment commits.
    
    Args:
        db: Database session
        video: Video record to update progress on
        translations: List of translation dicts with sequence_number and translated_text
        all_segments: List of all Segment objects for this video
        batch_size: Number of segments per batch commit (default 50)
        progress_tracker: Optional progress tracker for logging
    
    Returns:
        Number of segments successfully saved
    """
    import time
    from app.db.session import bulk_update_segment_translations
    
    if not translations:
        return 0
    
    start_time = time.time()
    
    # Create sequence to segment mapping
    seq_to_segment = {s.sequence_number: s for s in all_segments}
    
    # Build translation data for bulk update
    translation_data = []
    translation_count = 0
    
    for translation in translations:
        seq_num = translation.get("sequence_number")
        translated_text = translation.get("translated_text", "").strip()
        
        if seq_num and translated_text and seq_num in seq_to_segment:
            translation_data.append({
                "sequence_number": seq_num,
                "translated_text": translated_text,
            })
            translation_count += 1
    
    if not translation_data:
        return 0
    
    # Update video batch tracking
    total_batches = (len(translation_data) + batch_size - 1) // batch_size
    video.total_batches = total_batches
    video.processed_batches = 0
    db.commit()
    
    # Process in batches of batch_size
    saved_count = 0
    
    for i in range(0, len(translation_data), batch_size):
        batch_start = time.time()
        batch = translation_data[i:i + batch_size]
        
        # Use the bulk update function
        batch_saved = bulk_update_segment_translations(video.id, batch)
        saved_count += batch_saved
        
        # Update video progress
        video.processed_batches = (i // batch_size) + 1
        video.processed_segments = saved_count
        video.progress_percent = int((saved_count / len(translation_data)) * 100)
        db.commit()
        
        batch_elapsed = (time.time() - batch_start) * 1000  # ms
        
        if progress_tracker:
            progress_tracker.info(
                "TRANSLATING",
                f"Bulk saved {batch_saved} segments ({saved_count}/{len(translation_data)})",
                f"Batch {video.processed_batches}/{total_batches} in {batch_elapsed:.1f}ms"
            )
        
        print(f"[TRANSLATING] Bulk saved {len(batch)} segments in {batch_elapsed:.1f}ms "
              f"(batch {video.processed_batches}/{total_batches})")
    
    total_elapsed = (time.time() - start_time) * 1000  # ms
    
    if progress_tracker:
        progress_tracker.info(
            "TRANSLATING",
            f"Bulk save complete: {saved_count} segments",
            f"Total time: {total_elapsed:.1f}ms in {total_batches} batches"
        )
    
    print(f"[TRANSLATING] ✓ Bulk saved {saved_count} segments in {total_elapsed:.1f}ms "
          f"({total_batches} batches)")
    
    return saved_count


def bulk_save_segments_with_short_sessions(
    video_id: str,
    translations: List[Dict[str, Any]],
    batch_size: int = 50,
    progress_tracker: Any = None,
) -> int:
    """Bulk save segment translations using short-lived database sessions.
    
    This function processes all translations in memory and performs updates
    in batches using short-lived sessions to avoid holding database locks.
    
    Args:
        video_id: Video ID
        translations: List of translation dicts with sequence_number and translated_text
        batch_size: Number of segments per batch (default 50)
        progress_tracker: Optional progress tracker for logging
    
    Returns:
        Number of segments successfully saved
    """
    import time
    from app.db.session import bulk_update_segment_translations
    
    if not translations:
        return 0
    
    start_time = time.time()
    
    # Build translation data for bulk update
    translation_data = []
    for translation in translations:
        seq_num = translation.get("sequence_number")
        translated_text = translation.get("translated_text", "").strip()
        
        if seq_num and translated_text:
            translation_data.append({
                "sequence_number": seq_num,
                "translated_text": translated_text,
            })
    
    if not translation_data:
        return 0
    
    # Update video batch tracking with short session
    total_batches = (len(translation_data) + batch_size - 1) // batch_size
    with SessionLocal() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            video.total_batches = total_batches
            video.processed_batches = 0
            db.commit()
    
    # Process in batches
    saved_count = 0
    
    for i in range(0, len(translation_data), batch_size):
        batch_start = time.time()
        batch = translation_data[i:i + batch_size]
        
        # Use the bulk update function (creates its own session)
        batch_saved = bulk_update_segment_translations(video_id, batch)
        saved_count += batch_saved
        
        # Update video progress with short session
        with SessionLocal() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.processed_batches = (i // batch_size) + 1
                video.processed_segments = saved_count
                video.progress_percent = int((saved_count / len(translation_data)) * 100)
                db.commit()
        
        batch_elapsed = (time.time() - batch_start) * 1000  # ms
        
        if progress_tracker:
            progress_tracker.info(
                "TRANSLATING",
                f"Bulk saved {batch_saved} segments ({saved_count}/{len(translation_data)})",
                f"Batch {(i // batch_size) + 1}/{total_batches} in {batch_elapsed:.1f}ms"
            )
        
        print(f"[TRANSLATING] Bulk saved {len(batch)} segments in {batch_elapsed:.1f}ms "
              f"(batch {(i // batch_size) + 1}/{total_batches})")
    
    total_elapsed = (time.time() - start_time) * 1000  # ms
    
    if progress_tracker:
        progress_tracker.info(
            "TRANSLATING",
            f"Bulk save complete: {saved_count} segments",
            f"Total time: {total_elapsed:.1f}ms in {total_batches} batches"
        )
    
    print(f"[TRANSLATING] ✓ Bulk saved {saved_count} segments in {total_elapsed:.1f}ms "
          f"({total_batches} batches)")
    
    return saved_count


# ============================================================================
# Main Translation Functions
# ============================================================================

async def translate_video_sliding_window_async(
    video_id: str,
    db: Optional[Session] = None,  # Kept for backward compatibility, not used
    model_name: str = "gemini-2.5-flash",
    window_size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    glossary: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Async sliding window translation with concurrent batch processing.
    
    This function uses short-lived database sessions to avoid holding locks
    during the long-running translation process.
    
    This is the main async translation function that:
    1. Creates overlapping sliding window batches
    2. Translates batches concurrently (max 5 at a time via semaphore)
    3. Merges overlapping translations
    4. Saves results to database
    
    Args:
        video_id: ID of the video to translate
        db: Database session
        model_name: Gemini model name (default: 'gemini-2.5-flash')
        window_size: Segments per batch (default: 20)
        overlap: Overlapping segments between batches (default: 10)
    
    Returns:
        Dict with video_id, status, translated_count, total_segments, success flag
    
    Raises:
        ValueError: If video not found
        RuntimeError: If translation fails critically
    """
    # Initialize progress tracker (uses short-lived sessions internally)
    progress_tracker = get_progress_tracker(video_id, None)
    
    # Step 1: Get video and segments with short session
    with SessionLocal() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video not found: {video_id}")
        
        # Extract needed data before closing session
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
        
        # Update status
        video.status = VideoStatus.TRANSLATING.value
        video.total_segments = total_segments
        video.processed_segments = 0
        db.commit()
        
        # CRITICAL: Convert Segment objects to primitives BEFORE session closes
        # Accessing ORM attributes after session closes causes DetachedInstanceError
        all_segment_dicts = [
            {
                "id": seg.id,
                "sequence_number": seg.sequence_number,
                "original_text": seg.original_text,
            }
            for seg in all_segments
        ]
    
    # Only start the step if not already in this step
    step_started_here = False
    if progress_tracker._current_step_name != "TRANSLATING":
        progress_tracker.start_step(
            "TRANSLATING",
            f"Async sliding window: {total_segments} segments, window={window_size}, max_concurrent={MAX_CONCURRENT_CALLS}"
        )
        step_started_here = True
    
    try:
        # Initialize client
        client = get_gemini_client()
        
        # Step 2: Create sliding window batches (NO session)
        progress_tracker.info("TRANSLATING", "Creating sliding window batches...")
        # Build full transcript for context injection
        full_transcript_text = "\n".join([seg["original_text"] for seg in all_segment_dicts])
        
        batches = create_sliding_windows(all_segment_dicts, window_size, overlap, glossary, full_transcript_text)
        
        progress_tracker.info(
            "TRANSLATING",
            f"Created {len(batches)} batches from {total_segments} segments",
            f"Window: {window_size}, Overlap: {overlap}, Step: {window_size - overlap}"
        )
        
        # Step 3: Translate all batches concurrently (NO session held)
        start_time = time.time()
        batch_results = await translate_batches_concurrently(
            video_id=video_id,
            batches=batches,
            client=client,
            model_name=model_name,
            source_language=source_language,
            target_language=target_language,
            progress_tracker=progress_tracker,
        )
        elapsed = time.time() - start_time
        
        # Check for failures
        failed_batches = [r for r in batch_results if not r.success]
        if failed_batches:
            progress_tracker.warning(
                "TRANSLATING",
                f"{len(failed_batches)}/{len(batches)} batches failed",
                "Will attempt to continue with partial results"
            )
        
        # Step 4: Merge overlapping translations (NO session)
        progress_tracker.info("TRANSLATING", "Merging batch translations...")
        final_translations, extracted_terms = merge_translations(
            batch_results, all_segment_dicts, window_size, overlap
        )
        
        progress_tracker.info(
            "TRANSLATING",
            f"Merged into {len(final_translations)} final translations",
            f"Extracted {len(extracted_terms)} terms in {elapsed:.2f}s"
        )
        
        # Step 5: Apply translations using short-lived sessions
        progress_tracker.info("TRANSLATING", "Saving translations to database...")
        
        translation_count = bulk_save_segments_with_short_sessions(
            video_id=video_id,
            translations=final_translations,
            batch_size=50,
            progress_tracker=progress_tracker,
        )
        
        # Save extracted terms (simplified - just store as-is for now)
        
        # Step 6: Finalize with short session
        with SessionLocal() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.COMPLETED.value
                video.progress_percent = 100
                video.processed_segments = translation_count
                video.current_step = f"Translation complete: {translation_count}/{total_segments} segments"
                db.commit()
        
        # Only end the step if we started it
        if step_started_here:
            progress_tracker.end_step(
                f"Async translation complete: {translation_count} segments, "
                f"{len(batches)} batches in {elapsed:.2f}s"
            )
        
    except Exception as e:
        # Update error status with short session
        with SessionLocal() as db:
            video = db.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.ERROR.value
                video.error_message = str(e)
                db.commit()
        
        progress_tracker.error("TRANSLATING", "Translation failed", str(e))
        raise RuntimeError(f"Translation failed: {e}") from e
    
    # Return primitives only - ZERO LEAK POLICY
    with SessionLocal() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if video:
            return {
                "video_id": video_id,
                "status": video.status,
                "translated_count": video.processed_segments,
                "total_segments": video.total_segments,
                "success": video.status == VideoStatus.COMPLETED.value
            }
        return {"video_id": video_id, "status": "not_found", "success": False}


def translate_video_sliding_window(
    video_id: str,
    db: Optional[Session] = None,  # Kept for backward compatibility
    model_name: str = "gemini-2.5-flash",
    glossary: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Synchronous wrapper for async sliding window translation.
    
    This is the main entry point that maintains backward compatibility.
    It runs the async function using asyncio.run().
    
    Args:
        video_id: ID of the video to translate
        db: Database session
        model_name: Gemini model name
    
    Returns:
        Dict with video_id, status, translated_count, total_segments, success flag
    """
    return asyncio.run(translate_video_sliding_window_async(video_id, db, model_name, glossary=glossary))


# Backward compatibility alias
translate_video = translate_video_sliding_window


# Deprecated: Old simple translation function (kept for compatibility)
def translate_video_simple(
    video_id: str,
    db: Session,
    model_name: str = "gemini-2.5-flash",
) -> Video:
    """DEPRECATED: Use translate_video_sliding_window() instead.
    
    Simple translation without context analysis.
    Translates segments in batches with Gemini.
    
    This function is kept for backward compatibility but is not recommended
    for new code. It does not use sliding windows or concurrency.
    """
    import warnings
    warnings.warn(
        "translate_video_simple() is deprecated. Use translate_video_sliding_window() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    from google import genai
    
    progress_tracker = get_progress_tracker(video_id, db)
    
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise ValueError(f"Video not found: {video_id}")
    
    all_segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.sequence_number)
        .all()
    )
    
    if not all_segments:
        raise ValueError("No segments to translate")
    
    total_segments = len(all_segments)
    source_language = video.source_language or "en"
    target_language = video.target_language
    if not target_language:
        raise ValueError("Target language is not set for this video.")
    
    video.status = VideoStatus.TRANSLATING.value
    video.total_segments = total_segments
    video.processed_segments = 0
    db.commit()
    
    progress_tracker.start_step("TRANSLATING", f"Translating {total_segments} segments")
    
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        batch_size = 10
        translated_count = 0
        
        for i in range(0, len(all_segments), batch_size):
            batch = all_segments[i:i + batch_size]
            texts = [f"[{s.sequence_number}] {s.original_text}" for s in batch]
            
            prompt = f"""Translate these {source_language} subtitles to {target_language}.
Maintain context and consistency.

{' '.join(texts)}

Return as JSON: {{"translations": [{{"sequence_number": N, "translated_text": "..."}}]}}"""
            
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            
            # Parse response (basic)
            try:
                result = json.loads(response.text)
                for t in result.get("translations", []):
                    seq_num = t.get("sequence_number")
                    text = t.get("translated_text", "").strip()
                    if seq_num and text:
                        for seg in all_segments:
                            if seg.sequence_number == seq_num:
                                seg.translated_text = text
                                translated_count += 1
                                break
            except Exception as e:
                progress_tracker.warning("TRANSLATING", f"Failed to parse batch: {e}")
                continue
            
            # Update progress
            video.processed_segments = min(i + batch_size, total_segments)
            video.progress_percent = int((video.processed_segments / total_segments) * 100)
            db.commit()
        
        video.status = VideoStatus.COMPLETED.value
        video.progress_percent = 100
        db.commit()
        
        progress_tracker.end_step(f"Translated {translated_count} segments")
        
    except Exception as e:
        video.status = VideoStatus.ERROR.value
        video.error_message = str(e)
        db.commit()
        progress_tracker.error("TRANSLATING", "Translation failed", str(e))
        raise RuntimeError(f"Translation failed: {e}") from e
    
    # Return primitive Dict - ZERO LEAK POLICY
    return {
        "video_id": video_id,
        "status": video.status,
        "translated_count": translated_count,
        "total_segments": total_segments,
        "success": video.status == VideoStatus.COMPLETED.value
    }
