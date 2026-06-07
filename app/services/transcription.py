"""OpenAI cloud transcription service — segment-level timestamp pipeline.

Provides direct transcription with segment-level timestamps by calling
OpenAI's whisper-1 model. No local alignment models, no sequential mappers,
no clamping workarounds — text and timestamps are born together from the
cloud response.

Usage:
    segments = transcribe_with_openai("/path/to/audio.wav", language="fa")
    # segments == [{"start": 0.0, "end": 3.5, "text": "Hello world"}, ...]
"""

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

from openai import OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    """Raised when OpenAI transcription fails.

    This is a HARD FAILURE — the caller must NOT fall back to heuristics.
    The pipeline step should be marked as failed.
    """
    pass


def get_openai_client(api_key: Optional[str] = None) -> OpenAI:
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


def transcribe_with_openai(
    audio_path: str,
    language: Optional[str] = None,
    api_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Transcribe audio using OpenAI whisper-1.

    Args:
        audio_path: Path to the audio file (FFmpeg-extracted 16 kHz mono
            WAV is ideal, but any format FFmpeg can produce works).
        language: Optional ISO-639-1 language code (e.g. 'en', 'fa', 'de').
            whisper-1 supports this natively.
        api_key: Optional API key override. Falls back to
            settings.OPENAI_API_KEY.

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
            kwargs: Dict[str, Any] = {
                "model": "whisper-1",
                "file": audio_file,
                "response_format": "verbose_json",
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
    detected_language = getattr(response, "language", None) or response.get("language", language or "en")

    if not segments_raw:
        raise TranscriptionError(
            f"OpenAI returned empty segments for '{audio_path}'. "
            f"The audio may be silent, corrupted, or in an unsupported language."
        )

    segments: List[Dict[str, Any]] = []
    for seg in segments_raw:
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

        segments.append({
            "start": float(start),
            "end": float(end),
            "text": str(text).strip(),
        })

    logger.info(
        "OpenAI transcription successful for '%s': %d segments, lang=%s",
        audio_path,
        len(segments),
        detected_language,
    )

    return segments
