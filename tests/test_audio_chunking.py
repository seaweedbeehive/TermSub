"""Tests for audio chunking utilities and chunked transcription orchestration."""

import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core.audio import (
    MAX_AUDIO_SIZE_BYTES,
    chunk_audio_if_needed,
    get_audio_duration,
    get_chunk_offsets,
    split_audio_file,
)
from app.services.transcription import transcribe_audio_with_chunking


def _generate_silent_mp3(output_path: Path, duration: float = 2.0) -> None:
    """Generate a silent mono MP3 with FFmpeg for testing."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=16000:cl=mono",
        "-t",
        str(duration),
        "-acodec",
        "libmp3lame",
        "-q:a",
        "5",
        str(output_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)


def test_chunk_audio_if_needed_does_not_split_small_file(tmp_path: Path) -> None:
    """Files under the size threshold should be returned as a single chunk."""
    audio_path = tmp_path / "small.mp3"
    audio_path.write_bytes(b"tiny audio content")

    chunks, temp_dir = chunk_audio_if_needed(str(audio_path))

    assert chunks == [str(audio_path)]
    assert temp_dir is None


def test_chunk_audio_if_needed_splits_large_file(tmp_path: Path) -> None:
    """Files over the size threshold should be passed to the splitter."""
    audio_path = tmp_path / "large.mp3"
    audio_path.write_bytes(b"audio content")

    fake_chunk_1 = str(tmp_path / "chunk_001.mp3")
    fake_chunk_2 = str(tmp_path / "chunk_002.mp3")

    with patch(
        "app.core.audio.os.path.getsize",
        return_value=MAX_AUDIO_SIZE_BYTES + 1,
    ), patch(
        "app.core.audio.split_audio_file",
        return_value=[fake_chunk_1, fake_chunk_2],
    ) as mock_split:
        chunks, temp_dir = chunk_audio_if_needed(str(audio_path))

    assert chunks == [fake_chunk_1, fake_chunk_2]
    assert temp_dir is not None
    mock_split.assert_called_once_with(
        str(audio_path),
        600.0,
        temp_dir,
    )

    # Clean up the temp directory created by chunk_audio_if_needed.
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_get_chunk_offsets_accumulates_durations() -> None:
    """Offsets must be the cumulative duration of all preceding chunks."""
    chunk_paths = ["chunk_1.mp3", "chunk_2.mp3", "chunk_3.mp3", "chunk_4.mp3"]

    with patch(
        "app.core.audio.get_audio_duration",
        side_effect=[10.0, 20.5, 5.25],
    ) as mock_duration:
        offsets = get_chunk_offsets(chunk_paths)

    assert offsets == [0.0, 10.0, 30.5, 35.75]
    assert mock_duration.call_count == 3


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg/FFprobe not installed",
)
def test_split_audio_file_and_get_duration_with_ffmpeg(tmp_path: Path) -> None:
    """Integration test: FFmpeg can split an MP3 and ffprobe can read durations."""
    source = tmp_path / "source.mp3"
    _generate_silent_mp3(source, duration=2.0)

    chunks = split_audio_file(str(source), chunk_duration=1.0, output_dir=str(tmp_path))

    # FFmpeg's segment muxer may produce a tiny trailing chunk, so we only
    # assert that the file was split and that the durations add up correctly.
    assert len(chunks) >= 2
    assert all(Path(chunk).exists() for chunk in chunks)

    total_duration = sum(get_audio_duration(chunk) for chunk in chunks)
    assert total_duration == pytest.approx(2.0, abs=0.1)


def test_transcribe_audio_with_chunking_merges_offsets_and_cleans_up(
    tmp_path: Path,
) -> None:
    """Chunked transcription must concatenate results and shift timestamps."""
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_text("dummy audio")

    chunk_paths = [str(tmp_path / "chunk_001.mp3"), str(tmp_path / "chunk_002.mp3")]
    fake_temp_dir = str(tmp_path / "chunks_dir")
    Path(fake_temp_dir).mkdir(parents=True, exist_ok=True)

    def _fake_transcribe(
        audio_path: str,
        language: str | None = None,
        api_key: str | None = None,
        time_offset: float = 0.0,
    ) -> list[dict[str, Any]]:
        # Return recognisable segments so we can verify offsets and ordering.
        if audio_path == chunk_paths[0]:
            return [
                {"start": 0.0 + time_offset, "end": 2.0 + time_offset, "text": "first"}
            ]
        if audio_path == chunk_paths[1]:
            return [
                {"start": 0.0 + time_offset, "end": 3.0 + time_offset, "text": "second"}
            ]
        return []

    progress = MagicMock()

    with patch(
        "app.services.transcription.chunk_audio_if_needed",
        return_value=(chunk_paths, fake_temp_dir),
    ), patch(
        "app.services.transcription.get_chunk_offsets",
        return_value=[0.0, 600.0],
    ), patch(
        "app.services.transcription.transcribe_with_openai",
        side_effect=_fake_transcribe,
    ) as mock_transcribe:
        segments = transcribe_audio_with_chunking(
            str(audio_path),
            language="en",
            api_key="test-key",
            progress_tracker=progress,
        )

    assert len(segments) == 2
    assert segments[0]["start"] == 0.0
    assert segments[0]["end"] == 2.0
    assert segments[1]["start"] == 600.0
    assert segments[1]["end"] == 603.0

    # Verify each chunk got the right offset.
    assert mock_transcribe.call_count == 2
    calls = mock_transcribe.call_args_list
    assert calls[0].kwargs["time_offset"] == 0.0
    assert calls[1].kwargs["time_offset"] == 600.0

    # The temp directory should have been removed.
    assert not Path(fake_temp_dir).exists()

    # Progress tracker should have received chunk-level updates.
    assert progress.info.call_count >= 3
