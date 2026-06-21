"""Tests for the OpenAI cloud transcription service."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from app.services.transcription import transcribe_with_openai


class _FakeWord:
    """Minimal fake word object returned by the OpenAI SDK."""

    def __init__(self, start: float, word: str):
        self.start = start
        self.word = word


class _FakeSegment:
    """Minimal fake segment object returned by the OpenAI SDK."""

    def __init__(self, start: float, end: float, text: str):
        self.start = start
        self.end = end
        self.text = text


class _FakeTranscription:
    """Minimal fake transcription response returned by the OpenAI SDK.

    Mirrors both attribute and dict-style access used by the parser.
    """

    def __init__(
        self,
        segments: list[_FakeSegment],
        words: list[_FakeWord] | None = None,
        language: str = "en",
    ):
        self.segments = segments
        self.words = words
        self.language = language

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style accessor for compatibility with the parser."""
        return getattr(self, key, default)


def _make_fake_client(transcription_response: _FakeTranscription) -> MagicMock:
    """Build a fake OpenAI client that returns the given transcription."""
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = transcription_response
    return fake_client


def test_first_segment_start_corrected_from_word_timestamp(tmp_path: Path) -> None:
    """Leading silence should be respected using the first word's timestamp."""
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_text("dummy audio")

    response = _FakeTranscription(
        segments=[
            _FakeSegment(start=0.0, end=5.0, text="Hello world"),
            _FakeSegment(start=5.0, end=8.0, text="How are you"),
        ],
        words=[
            _FakeWord(start=2.5, word="Hello"),
            _FakeWord(start=3.0, word="world"),
        ],
    )

    with patch(
        "app.services.transcription.get_openai_client",
        return_value=_make_fake_client(response),
    ):
        segments = transcribe_with_openai(str(audio_path))

    assert segments[0]["start"] == 2.5
    assert segments[0]["end"] == 5.0
    assert segments[0]["text"] == "Hello world"
    assert segments[1]["start"] == 5.0


def test_no_correction_when_first_word_starts_at_zero(tmp_path: Path) -> None:
    """If the audio really starts at 0.0, do not invent a delay."""
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_text("dummy audio")

    response = _FakeTranscription(
        segments=[
            _FakeSegment(start=0.0, end=3.0, text="Hello world"),
        ],
        words=[
            _FakeWord(start=0.0, word="Hello"),
        ],
    )

    with patch(
        "app.services.transcription.get_openai_client",
        return_value=_make_fake_client(response),
    ):
        segments = transcribe_with_openai(str(audio_path))

    assert segments[0]["start"] == 0.0


def test_fallback_when_no_word_timestamps(tmp_path: Path) -> None:
    """Segment timestamps are used unchanged when word timestamps are absent."""
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_text("dummy audio")

    response = _FakeTranscription(
        segments=[
            _FakeSegment(start=0.0, end=3.0, text="Hello world"),
        ],
        words=None,
    )

    with patch(
        "app.services.transcription.get_openai_client",
        return_value=_make_fake_client(response),
    ):
        segments = transcribe_with_openai(str(audio_path))

    assert segments[0]["start"] == 0.0
    assert segments[0]["end"] == 3.0



def test_time_offset_applied_to_segments_and_word_correction(tmp_path: Path) -> None:
    """Chunk timestamps must be shifted by the original-audio offset."""
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_text("dummy audio")

    response = _FakeTranscription(
        segments=[
            _FakeSegment(start=0.0, end=5.0, text="Hello world"),
            _FakeSegment(start=5.0, end=8.0, text="How are you"),
        ],
        words=[
            _FakeWord(start=1.5, word="Hello"),
        ],
    )

    with patch(
        "app.services.transcription.get_openai_client",
        return_value=_make_fake_client(response),
    ):
        segments = transcribe_with_openai(str(audio_path), time_offset=600.0)

    # Word correction is applied after the offset, so start becomes 601.5.
    assert segments[0]["start"] == 601.5
    assert segments[0]["end"] == 605.0
    assert segments[1]["start"] == 605.0
    assert segments[1]["end"] == 608.0


def test_offset_only_when_word_at_chunk_start(
    tmp_path: Path,
) -> None:
    """If the first word of a chunk starts at 0, the offset alone is used."""
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_text("dummy audio")

    response = _FakeTranscription(
        segments=[
            _FakeSegment(start=0.0, end=3.0, text="Hello"),
        ],
        words=[
            _FakeWord(start=0.0, word="Hello"),
        ],
    )

    with patch(
        "app.services.transcription.get_openai_client",
        return_value=_make_fake_client(response),
    ):
        segments = transcribe_with_openai(str(audio_path), time_offset=300.0)

    assert segments[0]["start"] == 300.0
    assert segments[0]["end"] == 303.0
