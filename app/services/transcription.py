"""OpenAI cloud transcription service — segment-level timestamp pipeline.

Provides direct transcription with segment-level timestamps by calling
OpenAI's whisper-1 model. No local alignment models, no sequential mappers,
no clamping workarounds — text and timestamps are born together from the
cloud response.

Usage:
    segments = transcribe_with_openai("/path/to/audio.mp3", language="fa")
    # segments == [{"start": 0.0, "end": 3.5, "text": "Hello world"}, ...]
"""

import logging
import shutil
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.core.audio import chunk_audio_if_needed, get_chunk_offsets
from app.core.config import settings

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Raised when OpenAI transcription fails.

    This is a HARD FAILURE — the caller must NOT fall back to heuristics.
    The pipeline step should be marked as failed.
    """

    pass


def get_openai_client(api_key: str | None = None) -> OpenAI:
    """Initialize and return an OpenAI client.

    Args:
        api_key: Optional per-request API key. Falls back to
            settings.OPENAI_API_KEY.

    Raises:
        TranscriptionError: If no API key is available.
    """
    effective_key = api_key or settings.OPENAI_API_KEY
    if not effective_key:
        raise TranscriptionError(
            "OPENAI_API_KEY not configured. Please enter your API key in the UI."
        )
    return OpenAI(api_key=effective_key)


def merge_subtitle_segments(
    segments: list[dict[str, Any]],
    min_duration: float = 1.0,
    min_chars: int = 30,
    max_duration: float = 7.0,
    max_chars: int = 84,
) -> list[dict[str, Any]]:
    """Merge adjacent short segments into subtitle-appropriate lengths.

    Uses a greedy algorithm that merges segments until they reach
    professional subtitle standards (min duration or min chars) or
    hit maximum limits (max duration or max chars).
    """
    if not segments:
        return []

    # Detect whether these are audio segments (real timestamps)
    # or text segments (all 0.0)
    has_real_timestamps = any(seg["end"] > 0.0 for seg in segments)

    merged: list[dict[str, Any]] = []
    current: dict[str, Any] = {
        "start": segments[0]["start"],
        "end": segments[0]["end"],
        "text": segments[0]["text"],
    }

    for next_seg in segments[1:]:
        next_text = next_seg["text"]
        if not next_text:
            continue  # Skip empty segments

        next_start = next_seg["start"]
        next_end = next_seg["end"]

        merged_text = (current["text"] + " " + next_text).strip()
        merged_chars = len(merged_text)
        merged_end = next_end
        merged_duration = merged_end - current["start"] if has_real_timestamps else 0.0

        current_duration = (
            current["end"] - current["start"] if has_real_timestamps else 0.0
        )
        current_chars = len(current["text"])

        # "Good enough" to stand alone?
        is_good_enough = (
            has_real_timestamps and current_duration >= min_duration
        ) or current_chars >= min_chars

        # Would merging exceed hard maximums?
        would_exceed_max = False
        if has_real_timestamps and merged_duration > max_duration:
            would_exceed_max = True
        if merged_chars > max_chars:
            would_exceed_max = True

        if is_good_enough or would_exceed_max:
            merged.append(current)
            current = {"start": next_start, "end": next_end, "text": next_text}
        else:
            current["end"] = merged_end
            current["text"] = merged_text

    merged.append(current)
    return merged


def transcribe_with_openai(
    audio_path: str,
    language: str | None = None,
    api_key: str | None = None,
    time_offset: float = 0.0,
) -> list[dict[str, Any]]:
    """Transcribe audio using OpenAI whisper-1.

    Args:
        audio_path: Path to the audio file (FFmpeg-extracted 16 kHz mono
            WAV is ideal, but any format FFmpeg can produce works).
        language: Optional ISO-639-1 language code (e.g. 'en', 'fa', 'de').
            whisper-1 supports this natively.
        api_key: Optional API key override. Falls back to
            settings.OPENAI_API_KEY.
        time_offset: Seconds to add to every timestamp.  Used when transcribing
            a chunk that starts later in the original audio.

    Returns:
        List of dicts with ``start``, ``end``, and ``text`` keys.

    Raises:
        TranscriptionError: If the API key is missing or the API call fails.
    """
    client = get_openai_client(api_key)
    path = Path(audio_path)

    if not path.exists():
        raise TranscriptionError(f"Audio file not found: {audio_path}")

    logger.info(f"Sending audio to OpenAI whisper-1: {audio_path}")

    try:
        with open(audio_path, "rb") as audio_file:
            kwargs: dict[str, Any] = {
                "model": "whisper-1",
                "file": audio_file,
                "response_format": "verbose_json",
                # Request both segment and word timestamps. Word timestamps let us
                # recover the true start time of the first spoken word when Whisper
                # clamps the first segment's start to 0.0 because of leading silence.
                "timestamp_granularities": ["word", "segment"],
            }
            if language:
                kwargs["language"] = language

            response = client.audio.transcriptions.create(**kwargs)
    except Exception as exc:
        raise TranscriptionError(
            f"OpenAI transcription failed for '{audio_path}': {exc}"
        ) from exc

    # ------------------------------------------------------------------
    # Parse OpenAI verbose_json response into uniform segment dicts.
    # ------------------------------------------------------------------
    # The modern openai SDK returns a Transcription pydantic model;
    # fall back to dict-style access for maximum compatibility.
    segments_raw = getattr(response, "segments", None) or response.get("segments", [])
    words_raw = getattr(response, "words", None) or response.get("words", [])
    detected_language = getattr(response, "language", None) or response.get(
        "language", language or "en"
    )

    # Whisper sometimes reports the first segment as starting at 0.0 even when
    # the audio begins with silence. The word-level timestamp of the first spoken
    # word is authoritative, so we use it to correct the first segment's start.
    # When processing a chunk, shift the authoritative word timestamp by the
    # chunk's offset in the original audio.
    first_word_start: float | None = None
    if words_raw:
        for word in words_raw:
            w_start = getattr(word, "start", None)
            if w_start is None and isinstance(word, dict):
                w_start = word.get("start")
            if w_start is not None:
                first_word_start = float(w_start) + time_offset
                break

    if not segments_raw:
        raise TranscriptionError(
            f"OpenAI returned empty segments for '{audio_path}'. "
            f"The audio may be silent, corrupted, or in an unsupported language."
        )

    segments: list[dict[str, Any]] = []
    for idx, seg in enumerate(segments_raw):
        # Support both pydantic model items and plain dicts
        start = getattr(seg, "start", None)
        if start is None:
            start = seg.get("start", 0.0)
        end = getattr(seg, "end", None)
        if end is None:
            end = seg.get("end", 0.0)
        text = getattr(seg, "text", None)
        if text is None:
            text = seg.get("text", "")

        # Shift segment timestamps by the chunk offset before any correction.
        start = float(start) + time_offset
        end = float(end) + time_offset

        # Apply the authoritative first-word timestamp to the first segment only.
        if (
            idx == 0
            and first_word_start is not None
            and first_word_start > start
        ):
            start = first_word_start

        segments.append(
            {
                "start": start,
                "end": end,
                "text": str(text).strip(),
            }
        )

    # Merge short Whisper fragments into subtitle-appropriate lengths
    segments = merge_subtitle_segments(segments)

    logger.info(
        "OpenAI transcription successful for '%s': %d segments, lang=%s",
        audio_path,
        len(segments),
        detected_language,
    )

    return segments


def transcribe_audio_with_chunking(
    audio_path: str,
    language: str | None = None,
    api_key: str | None = None,
    progress_tracker: Any = None,
) -> list[dict[str, Any]]:
    """Transcribe audio, automatically chunking if it exceeds Whisper's size limit.

    Chunks are transcribed sequentially and their timestamps are shifted by the
    exact duration of all previous chunks, producing a single seamless segment
    list relative to the original audio.

    Args:
        audio_path: Path to the extracted audio file.
        language: Optional ISO-639-1 language code.
        api_key: Optional OpenAI API key override.
        progress_tracker: Optional progress tracker for per-chunk logging.

    Returns:
        Merged list of segment dicts with ``start``, ``end``, and ``text`` keys.

    Raises:
        TranscriptionError: If any chunk transcription fails.
        RuntimeError: If FFmpeg chunking fails.
    """
    chunks: list[str] = []
    temp_dir: str | None = None
    try:
        chunks, temp_dir = chunk_audio_if_needed(audio_path)
        offsets = get_chunk_offsets(chunks)

        if progress_tracker:
            progress_tracker.info(
                "WHISPER",
                f"Transcribing audio in {len(chunks)} chunk(s)",
                f"file={audio_path}",
            )

        all_segments: list[dict[str, Any]] = []
        for idx, (chunk_path, offset) in enumerate(
            zip(chunks, offsets, strict=True), start=1
        ):
            if progress_tracker:
                progress_tracker.info(
                    "WHISPER",
                    f"Transcribing chunk {idx}/{len(chunks)}",
                    f"offset={offset:.2f}s, file={chunk_path}",
                )

            chunk_segments = transcribe_with_openai(
                audio_path=chunk_path,
                language=language,
                api_key=api_key,
                time_offset=offset,
            )
            all_segments.extend(chunk_segments)

            if progress_tracker:
                progress_tracker.info(
                    "WHISPER",
                    f"Chunk {idx}/{len(chunks)} complete",
                    f"segments={len(chunk_segments)}, offset={offset:.2f}s",
                )

        if progress_tracker:
            progress_tracker.info(
                "WHISPER",
                "All chunks transcribed",
                f"total_segments={len(all_segments)}",
            )

        return all_segments
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
