"""Whisper transcription service - extracts audio and transcribes video with progress tracking.

Uses Google Gemini Flash (cloud, JSON-structured output) exclusively.
"""

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.core.config import settings
from app.models.video import Video, VideoStatus, Segment
from app.services.progress_service import get_progress_tracker
from app.services.transcription import align_transcript_with_whisperx, AlignmentError


# ---------------------------------------------------------------------------
# Shared output format — both providers return this
# ---------------------------------------------------------------------------

class _SegmentWrapper:
    """Universal segment wrapper — used by all transcription pipelines."""
    def __init__(self, start: float, end: float, text: str):
        self.start = start
        self.end = end
        self.text = text


class _InfoWrapper:
    """Universal language info wrapper."""
    def __init__(self, language: str):
        self.language = language


# ---------------------------------------------------------------------------
# Audio extraction (provider-agnostic)
# ---------------------------------------------------------------------------

def extract_audio(video_path: str, audio_path: str, progress_tracker=None, video_id: str = None) -> None:
    """
    Extract audio from video file using FFmpeg.
    
    Args:
        video_path: Path to the video file
        audio_path: Output path for the audio file
        progress_tracker: Optional progress tracker for logging
        video_id: Optional video ID for WebSocket detailed logging (unused - kept for API compatibility)
    
    Raises:
        RuntimeError: If FFmpeg extraction fails
    """
    video_size_mb = Path(video_path).stat().st_size / 1024 / 1024 if Path(video_path).exists() else 0
    
    if progress_tracker:
        progress_tracker.info("AUDIO_EXTRACTION", f"Starting FFmpeg audio extraction", 
                             f"Video: {video_path}, Output: {audio_path}")
    
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output file
        "-i", video_path,
        "-vn",  # No video
        "-acodec", "pcm_s16le",  # PCM 16-bit little-endian
        "-ar", "16000",  # 16kHz sample rate (optimal for Whisper)
        "-ac", "1",  # Mono
        audio_path,
    ]
    
    try:
        start_time = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        elapsed = time.time() - start_time
        audio_size_mb = Path(audio_path).stat().st_size / 1024 / 1024 if Path(audio_path).exists() else 0
        
        if progress_tracker:
            progress_tracker.info("AUDIO_EXTRACTION", 
                                 f"Audio extraction completed in {elapsed:.2f}s",
                                 f"Output file size: {audio_size_mb:.2f} MB")
        
    except subprocess.CalledProcessError as e:
        if progress_tracker:
            progress_tracker.error("AUDIO_EXTRACTION", "FFmpeg audio extraction failed", e.stderr)
        raise RuntimeError(f"FFmpeg audio extraction failed: {e.stderr}")
    except FileNotFoundError:
        if progress_tracker:
            progress_tracker.error("AUDIO_EXTRACTION", "FFmpeg not found")
        raise RuntimeError("FFmpeg not found. Please install FFmpeg.")


# ---------------------------------------------------------------------------
# Gemini Transcription
# ---------------------------------------------------------------------------

def gemini_transcribe(
    audio_path: str,
    language: str = None,
    progress_tracker=None,
    video_id: str = None,
    api_key: Optional[str] = None,
) -> tuple[List[_SegmentWrapper], _InfoWrapper]:
    """Transcribe audio using Google Gemini 1.5 Flash.

    Args:
        audio_path: Path to the audio file
        language: Optional language code (e.g., 'en', 'fa') to force detection
        progress_tracker: Optional progress tracker for logging
        video_id: Optional video ID (unused - kept for API compatibility)
        api_key: Optional API key override. Falls back to settings.GEMINI_API_KEY.

    Returns:
        Tuple of (segments, info) where segments is a list of _SegmentWrapper objects
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai not installed. Install with: pip install google-genai")

    effective_api_key = api_key or settings.GEMINI_API_KEY
    if not effective_api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    client = genai.Client(api_key=effective_api_key)

    if progress_tracker:
        progress_tracker.info("WHISPER", "Uploading audio to Gemini...", f"file={audio_path}")

    transcribe_start = time.time()

    # Upload audio file
    uploaded_file = client.files.upload(file=audio_path)

    # Build prompt
    lang_hint = f"The audio is in {language}. " if language else ""
    prompt = (
        f"{lang_hint}Transcribe this audio. Return the output as a JSON object with two keys: "
        f"'detected_language' (a standard ISO 2-letter code like 'en', 'de', or 'fa' based on the dominant spoken language) "
        f"and 'segments' (a list of objects, each with 'start' (float seconds), 'end' (float seconds), and 'text' (string)). "
        f"CRITICAL SUBTITLE FORMATTING RULES: You must adhere to strict broadcast standards. "
        f"1. Maximum 42 characters per line. "
        f"2. Maximum 2 lines per subtitle card (Max 84 characters total). "
        f"3. Never output a massive block of text. If a speaker talks continuously, break their speech into smaller, logical sentence fragments across multiple JSON segments. "
        f"Do not wrap the JSON in markdown code blocks."
    )

    if progress_tracker:
        progress_tracker.info("WHISPER", "Sending to Gemini 3 Flash...")

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=[uploaded_file, prompt],
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )

    transcribe_elapsed = time.time() - transcribe_start

    # Parse JSON response
    raw_text = response.text or "[]"

    # Strip markdown code block if present
    clean_json = raw_text.strip()
    if clean_json.startswith("```"):
        clean_json = clean_json.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if clean_json.startswith("json"):
        clean_json = clean_json.split("\n", 1)[-1].strip()

    try:
        data = json.loads(clean_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini returned invalid JSON: {e}\nRaw: {raw_text[:500]}")

    # Support both new object format {"detected_language": "en", "segments": [...]}
    # and legacy list format [...]
    extracted_detected_language = None
    segments_data: List[Dict[str, Any]] = []

    if isinstance(data, dict):
        extracted_detected_language = data.get("detected_language")
        segments_data = data.get("segments", [])
        if not isinstance(segments_data, list):
            raise RuntimeError(f"Gemini returned unexpected format (expected 'segments' list). Raw: {raw_text[:500]}")
    elif isinstance(data, list):
        segments_data = data
    else:
        raise RuntimeError(f"Gemini returned unexpected format (expected JSON object or list). Raw: {raw_text[:500]}")

    segments: List[_SegmentWrapper] = []
    for item in segments_data:
        if isinstance(item, dict):
            segments.append(_SegmentWrapper(
                start=float(item.get("start", 0)),
                end=float(item.get("end", 0)),
                text=str(item.get("text", "")).strip(),
            ))

    detected_language = language or extracted_detected_language or "en"

    # ------------------------------------------------------------------
    # Hybrid alignment: refine Gemini timestamps with WhisperX
    # ------------------------------------------------------------------
    try:
        aligned = align_transcript_with_whisperx(
            audio_path=audio_path,
            gemini_segments=segments,
            language_code=detected_language,
        )
        segments = [
            _SegmentWrapper(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"],
            )
            for seg in aligned
        ]
        if progress_tracker:
            progress_tracker.info(
                "WHISPER",
                "WhisperX alignment applied",
                f"{len(segments)} segments aligned",
            )
    except AlignmentError:
        # HARD FAILURE: the transcript and audio are fundamentally mismatched.
        # Re-raise so the background worker marks the job as ERROR and the
        # UI receives a clear job_error WebSocket message.
        raise
    except Exception as exc:
        # Soft failure (unexpected runtime issue): log and keep Gemini's
        # coarse timestamps so transcription is not blocked by minor issues.
        if progress_tracker:
            progress_tracker.warning(
                "WHISPER",
                "WhisperX alignment failed, using Gemini timestamps",
                str(exc),
            )

    if progress_tracker:
        progress_tracker.info("WHISPER",
                             f"Gemini transcription complete in {transcribe_elapsed:.2f}s ({len(segments)} segments)",
                             f"lang={detected_language}")

    info = _InfoWrapper(language=detected_language)
    return segments, info


# ---------------------------------------------------------------------------
# Transcription entrypoint
# ---------------------------------------------------------------------------

def transcribe_audio(
    audio_path: str,
    language: str = None,
    progress_tracker=None,
    video_id: str = None,
    api_key: Optional[str] = None,
):
    """
    Transcribe audio using Google Gemini.

    Args:
        audio_path: Path to the audio file
        language: Optional language code (e.g., 'en', 'fa') to force detection
        progress_tracker: Optional progress tracker for logging
        video_id: Optional video ID (unused - kept for API compatibility)
        api_key: Optional Gemini API key override.

    Returns:
        Tuple of (segments, info) where segments is a list of _SegmentWrapper objects
    """
    return gemini_transcribe(audio_path, language, progress_tracker, video_id, api_key=api_key)


# ---------------------------------------------------------------------------
# High-level video transcription orchestration
# ---------------------------------------------------------------------------

def transcribe_video(video_id: str, language: str = None, api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract audio from video and transcribe using Gemini.
    
    This function uses short-lived database sessions to avoid holding locks
    during long-running operations (audio extraction, transcription).
    
    Args:
        video_id: ID of the video to transcribe
        language: Optional language code (e.g., 'en', 'fa') to force detection, None for auto-detect
    
    Returns:
        Dict with video_id, status, total_segments, source_language, and success flag
    
    Raises:
        ValueError: If video not found
        RuntimeError: If transcription fails
    """
    from app.db.session import SessionLocal
    
    # Phase 1: Fetch video info with short session - extract all primitives needed
    with SessionLocal() as session:
        video = session.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise ValueError(f"Video not found: {video_id}")
        
        # Check if video is in ERROR status - abort early
        if video.status == VideoStatus.ERROR.value:
            raise RuntimeError(f"Video {video_id} is in ERROR status, aborting transcription")
        
        # Extract needed info into local variables (DETACHED SAFE)
        file_path = video.file_path
        filename = video.filename
        source_language = video.source_language
    
    # Initialize progress tracker (creates its own sessions as needed)
    progress_tracker = get_progress_tracker(video_id, None)
    progress_tracker.info("TRANSCRIBE", f"Starting transcription for video: {filename}")
    
    # Update started_at with short session
    started_at = None
    with SessionLocal() as session:
        video = session.query(Video).filter(Video.id == video_id).first()
        if video:
            video.started_at = datetime.utcnow()
            started_at = video.started_at  # Capture for later use (DETACHED SAFE)
            session.commit()
    
    # Update status to extracting audio with short session
    progress_tracker.start_step("EXTRACTING_AUDIO", "Extracting audio from video using FFmpeg")
    with SessionLocal() as session:
        video = session.query(Video).filter(Video.id == video_id).first()
        if video:
            video.status = VideoStatus.EXTRACTING_AUDIO.value
            session.commit()
    
    audio_path = None
    try:
        # Create deterministic temporary audio file path for worker cleanup
        audio_path = os.path.join(tempfile.gettempdir(), f"termsub_{video_id}.wav")
        
        # Step 1: Extract audio (NO DATABASE SESSION during this long operation)
        progress_tracker.update_progress(
            status=VideoStatus.EXTRACTING_AUDIO.value,
            percent=5,
            current_step="Extracting Audio",
            step_detail="Converting video to audio format..."
        )
        
        extract_audio(file_path, audio_path, progress_tracker, video_id)
        
        # End the audio extraction step before starting transcription
        progress_tracker.end_step("Audio extraction complete")
        
        # Update status to transcribing with short session
        progress_tracker.start_step("TRANSCRIBING", "Transcribing audio with Gemini Cloud")
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.TRANSCRIBING.value
                session.commit()
        
        # Step 2: Transcribe (NO DATABASE SESSION during this long operation)
        progress_tracker.update_progress(
            status=VideoStatus.TRANSCRIBING.value,
            percent=10,
            current_step="Sending to Gemini",
            step_detail="Uploading audio to transcription service..."
        )
        
        # Propagate explicit source language from DB when caller didn't pass one.
        # If both are None, we let Gemini auto-detect the spoken language.
        if language is None:
            language = source_language
        
        segments, info = transcribe_audio(audio_path, language, progress_tracker, video_id=video_id, api_key=api_key)
        
        # Store source language (use detected or specified)
        detected_language = info.language if info and hasattr(info, 'language') else None
        final_language = language or detected_language or "en"
        
        if final_language:
            if language:
                progress_tracker.info("TRANSCRIBE", f"Using specified source language: {language}")
            elif detected_language:
                progress_tracker.info("TRANSCRIBE", f"Detected source language: {detected_language}")
        
        # Step 3: Save segments to database with SHORT SESSIONS
        progress_tracker.update_progress(
            status=VideoStatus.TRANSCRIBING.value,
            percent=20,
            current_step="Processing Segments",
            step_detail="Converting transcription to segments..."
        )
        
        # Collect segments first to count them
        segment_list = list(segments)
        total_segments = len(segment_list)
        
        progress_tracker.info("TRANSCRIBE", f"Total segments to process: {total_segments}")
        
        # Save segments in batches using short sessions
        sequence_number = 0
        for idx, segment in enumerate(segment_list, 1):
            sequence_number += 1
            
            # Build text from words if available for better accuracy
            text = segment.text.strip()
            
            # Use short session for each segment save
            with SessionLocal() as session:
                db_segment = Segment(
                    video_id=video_id,
                    sequence_number=sequence_number,
                    start_time=segment.start,
                    end_time=segment.end,
                    original_text=text,
                )
                session.add(db_segment)
                session.commit()
            
            # Update progress every segment or every 5 segments for performance
            if idx % 5 == 0 or idx == 1 or idx == total_segments:
                percent = 20 + int((idx / total_segments) * 70)  # 20% to 90%
                progress_tracker.update_progress(
                    status=VideoStatus.TRANSCRIBING.value,
                    percent=percent,
                    current_step="Saving Segments",
                    step_detail=f"Processing segment {idx}/{total_segments}",
                    total_segments=total_segments,
                    processed_segments=idx,
                    current_segment_index=idx
                )
                
                progress_tracker.info("TRANSCRIBE", 
                                     f"Saved segment {idx}/{total_segments}: '{text[:50]}...' "
                                     f"({segment.start:.2f}s - {segment.end:.2f}s)")
        
        # Finalize with short session
        progress_tracker.update_progress(
            status=VideoStatus.TRANSCRIBING.value,
            percent=95,
            current_step="Finalizing",
            step_detail="Committing to database..."
        )
        
        # Update video status to TRANSCRIBED with short session
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.TRANSCRIBED.value
                video.progress_percent = 100
                video.total_segments = sequence_number
                video.processed_segments = sequence_number
                video.completed_at = datetime.utcnow()
                video.source_language = final_language
                session.commit()
        
        # Calculate elapsed time using the captured started_at value
        elapsed_total = (datetime.utcnow() - started_at).total_seconds() if started_at else 0
        
        progress_tracker.end_step(f"Transcription complete! Created {sequence_number} segments")
        progress_tracker.info("TRANSCRIBE", 
                             f"Transcription finished successfully",
                             f"Total segments: {sequence_number}, Duration: {elapsed_total:.2f}s")
        
    except Exception as e:
        error_msg = str(e)
        
        # Update status to error with short session
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.ERROR.value
                video.error_message = error_msg
                video.progress_percent = 0
                session.commit()
        
        progress_tracker.error("TRANSCRIBE", "Transcription failed", error_msg)
        
        # Re-raise the exception so the caller knows it failed
        raise RuntimeError(f"Transcription failed: {error_msg}") from e
        
    finally:
        # NOTE: Audio file cleanup is handled by the background worker in sqlite_queue.py
        pass
    
    # Return primitive data only - ZERO LEAK POLICY
    # Re-query in fresh session to get final status
    with SessionLocal() as session:
        video = session.query(Video).filter(Video.id == video_id).first()
        if video:
            return {
                "video_id": video_id,
                "status": video.status,
                "total_segments": video.total_segments,
                "source_language": video.source_language,
                "success": video.status == VideoStatus.TRANSCRIBED.value,
                "audio_path": audio_path
            }
        return {"video_id": video_id, "status": "not_found", "success": False, "audio_path": audio_path}
