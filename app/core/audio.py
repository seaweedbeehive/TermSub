"""Audio utility helpers for chunking and inspection.

All operations are stateless and do not touch the database.  They rely on the
same FFmpeg toolchain already used by the rest of the pipeline.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# OpenAI Whisper has a hard 25 MB upload limit.  We use 24 MB as the decision
# threshold so minor bitrate fluctuations do not push a chunk over the limit.
MAX_AUDIO_SIZE_BYTES = 24 * 1024 * 1024

# Roughly 10-minute chunks.  At the project's ~190 kbps MP3 quality this keeps
# each chunk well under the Whisper limit while minimising API round-trips.
DEFAULT_CHUNK_DURATION_SECONDS = 600.0


def get_audio_duration(audio_path: str) -> float:
    """Return the duration of an audio file in seconds using ffprobe.

    Args:
        audio_path: Path to an audio file readable by FFmpeg.

    Returns:
        Duration in seconds as a float.

    Raises:
        RuntimeError: If ffprobe is unavailable or fails to parse the file.
    """
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        audio_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"ffprobe failed for '{audio_path}': {exc.stderr}"
        ) from exc
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe not found. Is FFmpeg installed?") from exc

    raw = result.stdout.strip()
    if raw == "N/A":
        return 0.0
    return float(raw)


def split_audio_file(
    audio_path: str,
    chunk_duration: float = DEFAULT_CHUNK_DURATION_SECONDS,
    output_dir: str | None = None,
) -> list[str]:
    """Split an audio file into fixed-length chunks using FFmpeg.

    Uses stream copy (`-c copy`) so the operation is fast and does not
    re-encode the already-compressed MP3.

    Args:
        audio_path: Path to the source audio file.
        chunk_duration: Target duration per chunk in seconds.
        output_dir: Directory for chunk files.  If omitted, a temporary
            directory is created.

    Returns:
        Sorted list of chunk file paths.

    Raises:
        RuntimeError: If FFmpeg fails or is not installed.
    """
    source = Path(audio_path)
    if not source.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    out_dir = (
        Path(output_dir)
        if output_dir
        else Path(tempfile.mkdtemp(prefix="termsub_chunks_"))
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "chunk_%03d.mp3")

    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-f",
        "segment",
        "-segment_time",
        str(chunk_duration),
        "-reset_timestamps",
        "1",
        "-c",
        "copy",
        pattern,
    ]

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"FFmpeg audio splitting failed for '{audio_path}': {exc.stderr}"
        ) from exc
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg not found. Is FFmpeg installed?") from exc

    chunks = sorted(out_dir.glob("chunk_*.mp3"))
    return [str(chunk) for chunk in chunks]


def chunk_audio_if_needed(
    audio_path: str,
    max_size_bytes: int = MAX_AUDIO_SIZE_BYTES,
    chunk_duration: float = DEFAULT_CHUNK_DURATION_SECONDS,
) -> tuple[list[str], str | None]:
    """Return audio paths, splitting into chunks only when the file is too large.

    Args:
        audio_path: Path to the extracted audio file.
        max_size_bytes: Size threshold that triggers chunking.
        chunk_duration: Target chunk duration in seconds.

    Returns:
        A tuple of (chunk_paths, temp_directory).  ``temp_directory`` is
        ``None`` when no splitting occurred; otherwise it is the directory that
        holds the chunk files and can be removed by the caller once processing
        is complete.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    file_size = os.path.getsize(audio_path)
    if file_size <= max_size_bytes:
        logger.info(
            "Audio file size %.2f MB is under %.2f MB limit; no chunking needed.",
            file_size / 1024 / 1024,
            max_size_bytes / 1024 / 1024,
        )
        return [audio_path], None

    logger.info(
        "Audio file size %.2f MB exceeds %.2f MB limit; splitting into "
        "%.0fs chunks.",
        file_size / 1024 / 1024,
        max_size_bytes / 1024 / 1024,
        chunk_duration,
    )
    temp_dir = tempfile.mkdtemp(prefix="termsub_chunks_")
    chunks = split_audio_file(audio_path, chunk_duration, temp_dir)
    if not chunks:
        # Defensive: should never happen if FFmpeg succeeded, but avoid leaking
        # an empty temp directory.
        raise RuntimeError(
            f"FFmpeg produced no chunks for '{audio_path}'"
        )
    return chunks, temp_dir


def get_chunk_offsets(chunk_paths: list[str]) -> list[float]:
    """Compute the original-audio time offset for each chunk.

    The offset of chunk ``i`` is the sum of the durations of all previous
    chunks.  Using real durations keeps long files perfectly in sync even when
    FFmpeg's stream-copy splits fall slightly off the exact target duration.

    Args:
        chunk_paths: Ordered list of chunk file paths.

    Returns:
        List of offsets in seconds, one per chunk.
    """
    offsets: list[float] = [0.0]
    # We only need durations of chunks *before* the current one, so stop one
    # short and reuse the running total.
    for path in chunk_paths[:-1]:
        duration = get_audio_duration(path)
        offsets.append(offsets[-1] + duration)
    return offsets
