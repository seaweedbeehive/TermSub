"""Transcription alignment service — hybrid Gemini + WhisperX pipeline.

Provides word-level timestamp alignment by running WhisperX over text
segments produced by Gemini (or any other coarse transcript provider).
"""

import logging
from typing import List, Any, Dict

logger = logging.getLogger(__name__)


def align_transcript_with_whisperx(
    audio_path: str,
    gemini_segments: List[Any],
    language_code: str,
) -> List[Dict[str, Any]]:
    """
    Align Gemini transcript segments with WhisperX for precise word-level timestamps.

    Loads the WhisperX alignment model for *language_code* on CPU and runs
    ``whisperx.align`` over the Gemini text segments.

    Args:
        audio_path: Path to the audio file (16 kHz mono WAV is ideal).
        gemini_segments: List of segment-like objects with *text*, *start*,
            and *end* attributes (e.g. ``_SegmentWrapper``).
        language_code: ISO language code, e.g. ``en``, ``de``, ``fa``.

    Returns:
        List of dicts with ``start``, ``end``, and ``text`` keys.  On any
        failure the original Gemini segments are returned unchanged (as dicts).
    """
    # ------------------------------------------------------------------
    # 0. Guard imports
    # ------------------------------------------------------------------
    try:
        import whisperx
        import torch
    except ImportError as exc:
        logger.error(
            "WhisperX alignment skipped: whisperx or torch not installed (%s)",
            exc,
        )
        return [
            {
                "start": getattr(s, "start", 0.0),
                "end": getattr(s, "end", 0.0),
                "text": getattr(s, "text", ""),
            }
            for s in gemini_segments
        ]

    device = "cpu"

    # ------------------------------------------------------------------
    # 1. Load alignment model (with graceful fallback)
    # ------------------------------------------------------------------
    try:
        model_a, metadata = whisperx.load_align_model(
            language_code=language_code, device=device
        )
    except Exception as exc:
        logger.error(
            "Failed to load WhisperX alignment model for '%s': %s",
            language_code,
            exc,
        )
        return [
            {
                "start": getattr(s, "start", 0.0),
                "end": getattr(s, "end", 0.0),
                "text": getattr(s, "text", ""),
            }
            for s in gemini_segments
        ]

    # ------------------------------------------------------------------
    # 2. Load audio
    # ------------------------------------------------------------------
    try:
        audio = whisperx.load_audio(audio_path)
    except Exception as exc:
        logger.error(
            "Failed to load audio '%s' for WhisperX alignment: %s",
            audio_path,
            exc,
        )
        return [
            {
                "start": getattr(s, "start", 0.0),
                "end": getattr(s, "end", 0.0),
                "text": getattr(s, "text", ""),
            }
            for s in gemini_segments
        ]

    # ------------------------------------------------------------------
    # 3. Convert segments to WhisperX format
    # ------------------------------------------------------------------
    transcript: List[Dict[str, Any]] = []
    for seg in gemini_segments:
        transcript.append(
            {
                "text": getattr(seg, "text", ""),
                "start": getattr(seg, "start", 0.0),
                "end": getattr(seg, "end", 0.0),
            }
        )

    # ------------------------------------------------------------------
    # 4. Run alignment
    # ------------------------------------------------------------------
    try:
        result = whisperx.align(
            transcript,
            model_a,
            audio,
            device,
            return_char_alignments=False,
        )
    except Exception as exc:
        logger.error("WhisperX alignment failed: %s", exc)
        return [
            {
                "start": getattr(s, "start", 0.0),
                "end": getattr(s, "end", 0.0),
                "text": getattr(s, "text", ""),
            }
            for s in gemini_segments
        ]

    # ------------------------------------------------------------------
    # 5. Map WhisperX output back to our segment format
    # ------------------------------------------------------------------
    aligned_segments: List[Dict[str, Any]] = []
    for seg in result.get("segments", []):
        aligned_segments.append(
            {
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "text": str(seg.get("text", "")).strip(),
            }
        )

    if not aligned_segments:
        logger.warning(
            "WhisperX returned empty alignment; falling back to Gemini timestamps"
        )
        return [
            {
                "start": getattr(s, "start", 0.0),
                "end": getattr(s, "end", 0.0),
                "text": getattr(s, "text", ""),
            }
            for s in gemini_segments
        ]

    logger.info(
        "WhisperX alignment successful for '%s': %d segments aligned",
        language_code,
        len(aligned_segments),
    )
    return aligned_segments
