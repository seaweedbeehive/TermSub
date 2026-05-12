"""Whisper transcription service - extracts audio and transcribes video with progress tracking.

Supports multiple transcription providers:
  - groq   : Cloud API via Groq (fast, default)
  - local  : Local faster-whisper (offline, high-accuracy mode)
  - gemini : Google Gemini 1.5 Flash (cloud, JSON-structured output)

Provider is selected via TRANSCRIPTION_PROVIDER config variable or passed
explicitly to transcribe_audio().
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


# ---------------------------------------------------------------------------
# Shared output format — both providers return this
# ---------------------------------------------------------------------------

class _SegmentWrapper:
    """Universal segment wrapper — used by both Groq and local pipelines."""
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
# Provider: Groq (cloud API)
# ---------------------------------------------------------------------------

def groq_transcribe(
    audio_path: str,
    model_size: str = None,
    language: str = None,
    progress_tracker=None,
    video_id: str = None,
) -> tuple[List[_SegmentWrapper], _InfoWrapper]:
    """Transcribe audio using the Groq Whisper API.

    Args:
        audio_path: Path to the audio file
        model_size: Groq model identifier (default: from config GROQ_WHISPER_MODEL)
        language: Optional language code (e.g., 'en', 'fa') to force detection
        progress_tracker: Optional progress tracker for logging
        video_id: Optional video ID (unused - kept for API compatibility)

    Returns:
        Tuple of (segments, info) where segments is a list of _SegmentWrapper objects
    """
    try:
        from openai import OpenAI
    except ImportError:
        if progress_tracker:
            progress_tracker.error("WHISPER", "openai not installed")
        raise RuntimeError("openai not installed. Install with: pip install openai")

    api_key = os.getenv("GROQ_API_KEY") or settings.GROQ_API_KEY
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not configured in environment")

    client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
    model = model_size or settings.GROQ_WHISPER_MODEL

    if progress_tracker:
        progress_tracker.info("WHISPER", f"Sending audio to Groq Whisper API", f"model={model}")

    transcribe_start = time.time()

    with open(audio_path, "rb") as audio_file:
        kwargs = {
            "model": model,
            "file": audio_file,
            "response_format": "verbose_json",
        }
        if language:
            kwargs["language"] = language
            if progress_tracker:
                progress_tracker.info("WHISPER", f"Using specified language: {language} (skipping auto-detection)")

        transcript = client.audio.transcriptions.create(**kwargs)

    transcribe_elapsed = time.time() - transcribe_start
    detected_language = getattr(transcript, "language", None) or language or "en"

    if progress_tracker:
        lang_info = f"Specified: {language}" if language else f"Detected: {detected_language}"
        progress_tracker.info("WHISPER",
                             f"Transcription complete in {transcribe_elapsed:.2f}s",
                             lang_info)

    segments: List[_SegmentWrapper] = []
    for seg in transcript.segments:
        segments.append(_SegmentWrapper(
            start=getattr(seg, "start", 0),
            end=getattr(seg, "end", 0),
            text=getattr(seg, "text", "").strip(),
        ))

    info = _InfoWrapper(language=detected_language)
    return segments, info


# ---------------------------------------------------------------------------
# Provider: Local (faster-whisper)
# ---------------------------------------------------------------------------

_local_model_cache: Dict[str, Any] = {}


def _get_local_model(model_size: str):
    """Lazy-load and cache a local faster-whisper model."""
    if model_size not in _local_model_cache:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError(
                "faster-whisper not installed. "
                "Install with: pip install faster-whisper"
            )
        _local_model_cache[model_size] = WhisperModel(
            model_size,
            device=settings.LOCAL_WHISPER_DEVICE,
            compute_type=settings.LOCAL_WHISPER_COMPUTE_TYPE,
        )
    return _local_model_cache[model_size]


def local_transcribe(
    audio_path: str,
    model_size: str = None,
    language: str = None,
    progress_tracker=None,
    video_id: str = None,
) -> tuple[List[_SegmentWrapper], _InfoWrapper]:
    """Transcribe audio using a local faster-whisper model.

    Args:
        audio_path: Path to the audio file
        model_size: faster-whisper model size (default: from config LOCAL_WHISPER_MODEL)
        language: Optional language code (e.g., 'en', 'fa') to force detection
        progress_tracker: Optional progress tracker for logging
        video_id: Optional video ID (unused - kept for API compatibility)

    Returns:
        Tuple of (segments, info) where segments is a list of _SegmentWrapper objects
    """
    model = _get_local_model(model_size or settings.LOCAL_WHISPER_MODEL)

    if progress_tracker:
        progress_tracker.info("WHISPER", f"Starting local transcription", f"model={model_size or settings.LOCAL_WHISPER_MODEL}")

    transcribe_start = time.time()

    segments_iter, info_obj = model.transcribe(
        audio_path,
        language=language,
        beam_size=5,
        condition_on_previous_text=True,
    )

    segments: List[_SegmentWrapper] = []
    for seg in segments_iter:
        segments.append(_SegmentWrapper(
            start=seg.start,
            end=seg.end,
            text=seg.text.strip(),
        ))

    transcribe_elapsed = time.time() - transcribe_start
    detected_language = info_obj.language or language or "en"

    if progress_tracker:
        lang_info = f"Specified: {language}" if language else f"Detected: {detected_language}"
        progress_tracker.info("WHISPER",
                             f"Local transcription complete in {transcribe_elapsed:.2f}s ({len(segments)} segments)",
                             lang_info)

    info = _InfoWrapper(language=detected_language)
    return segments, info


# ---------------------------------------------------------------------------
# Provider: Gemini (Google GenAI)
# ---------------------------------------------------------------------------

def gemini_transcribe(
    audio_path: str,
    model_size: str = None,
    language: str = None,
    progress_tracker=None,
    video_id: str = None,
) -> tuple[List[_SegmentWrapper], _InfoWrapper]:
    """Transcribe audio using Google Gemini 1.5 Flash.

    Args:
        audio_path: Path to the audio file
        model_size: Ignored (Gemini model is fixed)
        language: Optional language code (e.g., 'en', 'fa') to force detection
        progress_tracker: Optional progress tracker for logging
        video_id: Optional video ID (unused - kept for API compatibility)

    Returns:
        Tuple of (segments, info) where segments is a list of _SegmentWrapper objects
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai not installed. Install with: pip install google-genai")

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    client = genai.Client(api_key=api_key)

    if progress_tracker:
        progress_tracker.info("WHISPER", "Uploading audio to Gemini...", f"file={audio_path}")

    transcribe_start = time.time()

    # Upload audio file
    uploaded_file = client.files.upload(file=audio_path)

    # Build prompt
    lang_hint = f"The audio is in {language}. " if language else ""
    prompt = (
        f"{lang_hint}Transcribe this audio. Return the output as a JSON list of objects, "
        f"each with 'start' (float seconds), 'end' (float seconds), and 'text' (string). "
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

    if not isinstance(data, list):
        raise RuntimeError(f"Gemini returned unexpected format (expected JSON list). Raw: {raw_text[:500]}")

    segments: List[_SegmentWrapper] = []
    for item in data:
        if isinstance(item, dict):
            segments.append(_SegmentWrapper(
                start=float(item.get("start", 0)),
                end=float(item.get("end", 0)),
                text=str(item.get("text", "")).strip(),
            ))

    detected_language = language or "en"

    if progress_tracker:
        progress_tracker.info("WHISPER",
                             f"Gemini transcription complete in {transcribe_elapsed:.2f}s ({len(segments)} segments)",
                             f"lang={detected_language}")

    info = _InfoWrapper(language=detected_language)
    return segments, info


# ---------------------------------------------------------------------------
# Router — delegates to the configured provider
# ---------------------------------------------------------------------------

def transcribe_audio(
    audio_path: str,
    model_size: str = None,
    language: str = None,
    progress_tracker=None,
    video_id: str = None,
    provider: str = None,
):
    """
    Transcribe audio using the configured or explicitly specified transcription provider.

    Args:
        audio_path: Path to the audio file
        model_size: Model identifier (provider-specific; falls back to config defaults)
        language: Optional language code (e.g., 'en', 'fa') to force detection
        progress_tracker: Optional progress tracker for logging
        video_id: Optional video ID (unused - kept for API compatibility)
        provider: Optional provider override ('groq', 'local', 'gemini').
                  If None, uses TRANSCRIPTION_PROVIDER from config.

    Returns:
        Tuple of (segments, info) where segments is a list of _SegmentWrapper objects
    """
    active_provider = (provider or settings.TRANSCRIPTION_PROVIDER).lower()

    if active_provider == "groq":
        return groq_transcribe(audio_path, model_size, language, progress_tracker, video_id)
    elif active_provider == "local":
        return local_transcribe(audio_path, model_size, language, progress_tracker, video_id)
    elif active_provider == "gemini":
        return gemini_transcribe(audio_path, model_size, language, progress_tracker, video_id)
    else:
        raise RuntimeError(f"Unknown transcription provider: '{active_provider}'. "
                           f"Use 'groq', 'local', or 'gemini'.")


# ---------------------------------------------------------------------------
# High-level video transcription orchestration (provider-agnostic)
# ---------------------------------------------------------------------------

def transcribe_video(video_id: str, model_size: str = None, language: str = None, provider: str = None) -> Dict[str, Any]:
    """
    Extract audio from video and transcribe using the configured provider.
    
    This function uses short-lived database sessions to avoid holding locks
    during long-running operations (audio extraction, transcription).
    
    Args:
        video_id: ID of the video to transcribe
        model_size: Whisper model identifier (provider-specific; None = use config default)
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
        # Create temporary audio file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
            audio_path = tmp_audio.name
        
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
        progress_tracker.start_step("TRANSCRIBING", "Transcribing audio with Whisper AI")
        with SessionLocal() as session:
            video = session.query(Video).filter(Video.id == video_id).first()
            if video:
                video.status = VideoStatus.TRANSCRIBING.value
                session.commit()
        
        # Step 2: Transcribe (NO DATABASE SESSION during this long operation)
        progress_tracker.update_progress(
            status=VideoStatus.TRANSCRIBING.value,
            percent=10,
            current_step="Sending to Whisper",
            step_detail="Uploading audio to transcription service..."
        )
        
        # Use specified language from video if not provided
        if not language and source_language:
            language = source_language
        
        segments, info = transcribe_audio(audio_path, model_size, language, progress_tracker, provider=provider)
        
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
        # Clean up temporary audio file
        if audio_path and Path(audio_path).exists():
            Path(audio_path).unlink(missing_ok=True)
            progress_tracker.info("TRANSCRIBE", "Cleaned up temporary audio file")
    
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
                "success": video.status == VideoStatus.TRANSCRIBED.value
            }
        return {"video_id": video_id, "status": "not_found", "success": False}
