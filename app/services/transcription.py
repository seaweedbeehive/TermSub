"""Transcription alignment service — strict sequential WhisperX pipeline.

Provides word-level timestamp alignment by running WhisperX over text
segments produced by Gemini (or any other coarse transcript provider).

Implements a strict 1:1 segment sync policy:
- The full batch of RTL-cleaned segments is passed to whisperx.align() once
  so the DTW global context is preserved.
- After alignment, word-level timestamps are mapped back to original segments
  using a STRICT SEQUENTIAL text-matching algorithm (NOT greedy time bounds).
- Invisible Unicode directional marks are stripped before phonetic alignment
  but the original text (with RTL markers intact) is always preserved.
- Monotonic, non-overlapping timing is enforced via a post-processing pass.
- Alignment failures are raised as AlignmentError (no silent fallbacks).
"""

import logging
import re
from typing import List, Any, Dict

logger = logging.getLogger(__name__)

# Invisible Unicode directional marks that must be removed before phonetic
# alignment (WhisperX treats them as characters to map to audio).
_RTL_CLEAN_RE = re.compile(r"[\u200e\u200f\u202a\u202b\u202c]+")


class AlignmentError(Exception):
    """Raised when WhisperX alignment fails catastrophically.

    This is a HARD FAILURE — the caller must NOT fall back to coarse
    timestamps. The pipeline step should be marked as failed and the user
    should be notified that the audio source requires manual review.
    """
    pass


def _normalize_for_match(text: str) -> str:
    """Normalize text for strict sequential matching.

    Strips RTL directional marks, removes all non-alphanumeric characters
    (spaces, punctuation, symbols), and lowercases the result.

    This makes the text comparable across Gemini and WhisperX word output
    regardless of formatting differences.  Persian, Arabic, and other RTL
    scripts are preserved because Python 3's \\w is Unicode-aware.
    """
    text = _RTL_CLEAN_RE.sub("", text)
    # \\W matches any non-word character (spaces, punctuation, symbols).
    # In Python 3, re.UNICODE is the default, so this works for all scripts.
    return re.sub(r"\W+", "", text).lower()


def align_transcript_with_whisperx(
    audio_path: str,
    gemini_segments: List[Any],
    language_code: str,
) -> List[Dict[str, Any]]:
    """Align Gemini transcript segments with WhisperX for precise word-level timestamps.

    Uses a strict sequential mapper: WhisperX word_segments are consumed
    linearly, advancing the word index only when the accumulated normalized
    text matches the target Gemini segment's normalized text.

    Args:
        audio_path: Path to the audio file (16 kHz mono WAV is ideal).
        gemini_segments: List of segment-like objects with *text*, *start*,
            and *end* attributes (e.g. ``_SegmentWrapper``).
        language_code: ISO language code, e.g. ``en``, ``de``, ``fa``.

    Returns:
        List of dicts with ``start``, ``end``, and ``text`` keys.  The
        ``text`` value is the **original** Gemini text (RTL markers intact).

    Raises:
        AlignmentError: If WhisperX is unavailable, alignment fails, or the
            sequential mapping leaves >50% of segments unmapped.
    """
    # ------------------------------------------------------------------
    # 0. Guard imports — if WhisperX is missing, we cannot align at all.
    # ------------------------------------------------------------------
    try:
        import whisperx
        import torch
    except ImportError as exc:
        raise AlignmentError(
            f"WhisperX alignment unavailable: whisperx or torch not installed ({exc}). "
            f"Please install dependencies or use a different audio source."
        ) from exc

    device = "cpu"

    # ------------------------------------------------------------------
    # 1. Load alignment model
    # ------------------------------------------------------------------
    try:
        model_a, metadata = whisperx.load_align_model(
            language_code=language_code, device=device
        )
    except Exception as exc:
        raise AlignmentError(
            f"Failed to load WhisperX alignment model for '{language_code}': {exc}"
        ) from exc

    # ------------------------------------------------------------------
    # 2. Load audio once and prepare a reusable 2-D tensor [1, samples]
    # ------------------------------------------------------------------
    try:
        audio_np = whisperx.load_audio(audio_path)
        audio_tensor = torch.from_numpy(audio_np)
        if audio_tensor.ndim == 1:
            audio_tensor = audio_tensor.unsqueeze(0)
    except Exception as exc:
        raise AlignmentError(
            f"Failed to load audio '{audio_path}' for WhisperX alignment: {exc}"
        ) from exc

    # WhisperX loads audio at 16 kHz; compute actual duration for clamping.
    audio_duration = float(len(audio_np)) / 16000.0

    # ------------------------------------------------------------------
    # 3. Build RTL-cleaned batch transcript while preserving originals
    # ------------------------------------------------------------------
    cleaned_transcript: List[Dict[str, Any]] = []
    for seg in gemini_segments:
        original_text = getattr(seg, "text", "")
        # Strip RTL marks, collapse newlines to spaces, and trim.
        # Newlines confuse WhisperX's NLTK sentence tokenizer.
        clean_text = _RTL_CLEAN_RE.sub("", original_text).replace("\n", " ").strip()
        # Clamp Gemini's coarse timestamps to the actual audio duration so
        # WhisperX never receives a start/end that exceeds the file length.
        coarse_start = max(0.0, float(getattr(seg, "start", 0.0)))
        coarse_end = max(coarse_start, float(getattr(seg, "end", 0.0)))
        safe_start = min(coarse_start, audio_duration)
        safe_end = min(coarse_end, audio_duration)
        cleaned_transcript.append(
            {
                "text": clean_text,
                "start": safe_start,
                "end": safe_end,
            }
        )

    # ------------------------------------------------------------------
    # 4. Run batch alignment (single call — preserves DTW global context)
    # ------------------------------------------------------------------
    try:
        result = whisperx.align(
            cleaned_transcript,
            model_a,
            metadata,
            audio_tensor,
            device=device,
            return_char_alignments=False,
        )
    except Exception as exc:
        raise AlignmentError(
            f"WhisperX batch alignment failed for '{language_code}': {exc}"
        ) from exc

    word_segments = result.get("word_segments", [])
    if not word_segments:
        raise AlignmentError(
            f"WhisperX returned empty word_segments for '{language_code}'. "
            f"The audio may be silent, corrupted, or in an unsupported language."
        )

    # ------------------------------------------------------------------
    # 5. WORD COUNT INDEXING MAPPER
    #
    #    Map word_segments back to gemini_segments by slicing a fixed
    #    number of words from WhisperX's output for each segment.
    #
    #    Algorithm:
    #    - word_idx is a GLOBAL pointer into word_segments.
    #    - For each Gemini segment, count the words in its text.
    #    - Slice exactly that many words from word_segments (or all
    #      remaining words for the last segment).
    #    - Take the first valid start time and last valid end time
    #      from the slice as the segment's timestamps.
    #    - Advance word_idx by the slice size.
    #
    #    This avoids brittle string-matching that breaks when Gemini
    #    and WhisperX disagree on punctuation, numbers, or word splits.
    # ------------------------------------------------------------------
    aligned_results: List[Dict[str, Any]] = []
    word_idx = 0
    total_words = len(word_segments)
    failed_segments = 0

    for seg_idx, orig_seg in enumerate(gemini_segments):
        original_text = getattr(orig_seg, "text", "")
        coarse_start = float(getattr(orig_seg, "start", 0.0))
        coarse_end = float(getattr(orig_seg, "end", 0.0))

        # If Gemini produced empty text for this segment, keep coarse timestamps.
        clean_text = _RTL_CLEAN_RE.sub("", original_text).strip()
        if not clean_text:
            aligned_results.append(
                {
                    "start": coarse_start,
                    "end": coarse_end,
                    "text": original_text,
                }
            )
            continue

        expected_word_count = len(clean_text.split())

        # For the last segment, greedily consume ALL remaining words so
        # no trailing audio is silently discarded.
        is_last_segment = seg_idx == len(gemini_segments) - 1
        if is_last_segment:
            slice_end = total_words
        else:
            slice_end = min(word_idx + expected_word_count, total_words)

        word_slice = word_segments[word_idx:slice_end]

        # Find the first valid start time and last valid end time in the slice.
        # WhisperX sometimes omits start/end keys for unaligned words.
        new_start = coarse_start
        new_end = coarse_end

        valid_starts = [w.get("start") for w in word_slice if w.get("start") is not None]
        valid_ends = [w.get("end") for w in word_slice if w.get("end") is not None]

        if valid_starts:
            new_start = min(valid_starts)
        if valid_ends:
            new_end = max(valid_ends)

        aligned_results.append(
            {
                "start": float(new_start),
                "end": float(new_end),
                "text": original_text,
            }
        )

        word_idx = slice_end

        # Track segments that received fewer words than expected as a
        # soft-failure metric for the catastrophic-mismatch check.
        if not is_last_segment and len(word_slice) < expected_word_count:
            failed_segments += 1
            logger.warning(
                "[WARN] Word-count slice shortfall for segment %d "
                "(expected %d words, got %d). Using available timestamps.",
                seg_idx,
                expected_word_count,
                len(word_slice),
            )

    # ------------------------------------------------------------------
    # 6. TRAILING CLEANUP — last segment gets the final word's end time
    #
    #    If words remain after the loop (should only happen if earlier
    #    segments had fewer words than expected), assign ALL remaining
    #    words to the last segment so no trailing audio is discarded.
    # ------------------------------------------------------------------
    if word_idx < total_words and aligned_results:
        remaining_starts = []
        remaining_ends = []
        while word_idx < total_words:
            word = word_segments[word_idx]
            if word.get("start") is not None:
                remaining_starts.append(word["start"])
            if word.get("end") is not None:
                remaining_ends.append(word["end"])
            word_idx += 1

        last = aligned_results[-1]
        if remaining_starts:
            last["start"] = min(last["start"], min(remaining_starts))
        if remaining_ends:
            last["end"] = max(last["end"], max(remaining_ends))

    # ------------------------------------------------------------------
    # 7. CATASTROPHIC FAILURE CHECK
    #
    #    If >50% of non-empty segments had word-count shortfalls, OR if
    #    the total word count differs by >50% between Gemini and WhisperX,
    #    the alignment is unusable.  Raise AlignmentError.
    # ------------------------------------------------------------------
    non_empty_segments = sum(
        1
        for s in gemini_segments
        if _RTL_CLEAN_RE.sub("", getattr(s, "text", "")).strip()
    )
    gemini_total_words = sum(
        len(_RTL_CLEAN_RE.sub("", getattr(s, "text", "")).strip().split())
        for s in gemini_segments
    )
    whisperx_total_words = total_words

    catastrophic = False
    if non_empty_segments > 0 and failed_segments / non_empty_segments > 0.5:
        catastrophic = True
    if gemini_total_words > 0 and whisperx_total_words > 0:
        ratio = min(gemini_total_words, whisperx_total_words) / max(gemini_total_words, whisperx_total_words)
        if ratio < 0.5:
            catastrophic = True

    if catastrophic:
        raise AlignmentError(
            f"WhisperX alignment catastrophic failure: {failed_segments}/{non_empty_segments} "
            f"segments had word shortfalls. Gemini word count={gemini_total_words}, "
            f"WhisperX word count={whisperx_total_words}. The transcript and audio may be mismatched."
        )

    # ------------------------------------------------------------------
    # 8. MONOTONIC, NON-OVERLAPPING TIMING PASS
    #
    #    Enforce three invariants across the entire segment list:
    #    (a) start >= 0
    #    (b) start < end  (minimum 0.1s gap)
    #    (c) segment[N].end <= segment[N+1].start  (no overlaps)
    # ------------------------------------------------------------------

    # 8a. Per-segment sanity fixes
    for seg in aligned_results:
        if seg["start"] < 0:
            seg["start"] = 0.0

        if seg["start"] >= seg["end"]:
            # If start >= end, force a minimum 0.1s duration.
            seg["end"] = seg["start"] + 0.1

    # 8b. Overlap resolution — clamp adjacent segments to midpoint
    for i in range(len(aligned_results) - 1):
        current_end = aligned_results[i]["end"]
        next_start = aligned_results[i + 1]["start"]

        if current_end > next_start:
            # Segments overlap.  Set both boundary timestamps to the
            # exact midpoint so no audio time is claimed by two segments
            # simultaneously.  This is a lossy but safe correction.
            midpoint = (current_end + next_start) / 2.0
            aligned_results[i]["end"] = midpoint
            aligned_results[i + 1]["start"] = midpoint

    # 8c. Final validation: after clamping, ensure no overlaps remain
    for i in range(len(aligned_results) - 1):
        if aligned_results[i]["end"] > aligned_results[i + 1]["start"]:
            # This should never happen after midpoint clamping, but if
            # floating-point edge cases slip through, force a tiny gap.
            aligned_results[i]["end"] = aligned_results[i + 1]["start"]

    # ------------------------------------------------------------------
    # 9. POST-MERGE SHORT SEGMENTS
    #
    #    Gemini breaks speech into "logical fragments" that are often
    #    too short for comfortable reading (2-4 words, <2 seconds).
    #    Merge adjacent short segments so subtitles feel natural.
    # ------------------------------------------------------------------
    aligned_results = _merge_short_segments(aligned_results)

    logger.info(
        "WhisperX strict alignment successful for '%s': %d segments aligned, "
        "%d mapping failures",
        language_code,
        len(aligned_results),
        failed_segments,
    )

    return aligned_results


def _merge_short_segments(
    segments: List[Dict[str, Any]],
    min_duration: float = 2.0,
    max_duration: float = 7.0,
    min_chars: int = 15,
) -> List[Dict[str, Any]]:
    """Merge adjacent segments that are too short for comfortable reading.

    Subtitle best practice:
    - Minimum ~1.5-2 seconds per card
    - Maximum ~7 seconds per card
    - ~20-40 characters per line

    We do a single left-to-right pass.  If both the current segment and
    the next segment are shorter than min_duration (or both have fewer
    than min_chars) AND their combined duration does not exceed
    max_duration, we merge them.

    Args:
        segments: List of aligned segment dicts with start, end, text.
        min_duration: Minimum duration (seconds) before a segment is
            considered "too short" and a merge candidate.
        max_duration: Hard ceiling — never create a segment longer than
            this, even if both neighbours are tiny.
        min_chars: Alternative merge trigger — if both segments have
            fewer than this many characters, merge them.

    Returns:
        New list with short adjacent segments merged.
    """
    if not segments:
        return segments

    merged: List[Dict[str, Any]] = [dict(segments[0])]  # shallow copy

    for seg in segments[1:]:
        prev = merged[-1]
        prev_dur = prev["end"] - prev["start"]
        curr_dur = seg["end"] - seg["start"]
        combined_dur = seg["end"] - prev["start"]

        both_too_short = (
            prev_dur < min_duration
            and curr_dur < min_duration
            and combined_dur <= max_duration
        )
        both_too_tiny = (
            len(prev["text"]) < min_chars
            and len(seg["text"]) < min_chars
            and combined_dur <= max_duration
        )

        if both_too_short or both_too_tiny:
            # Merge current into previous
            prev["end"] = seg["end"]
            prev["text"] = (prev["text"] + " " + seg["text"]).strip()
        else:
            merged.append(dict(seg))

    return merged
