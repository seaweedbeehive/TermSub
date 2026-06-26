"""Tests for the export generation engine."""

from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _mock_video(
    status: str = "completed",
    filename: str = "test_video.mp4",
    user_id: str | None = None,
) -> MagicMock:
    """Create a minimal mock Video object for export tests."""
    video = MagicMock()
    video.id = "vid-1"
    video.filename = filename
    video.content_type = "video"
    video.source_language = "en"
    video.target_language = "fa"
    video.status = status
    video.user_id = user_id
    video.created_at.isoformat.return_value = "2024-01-01T00:00:00"
    return video


def _mock_segment(
    sequence_number: int = 1,
    start_time: float = 0.0,
    end_time: float = 2.0,
    translated_text: str = "Translated",
    original_text: str = "Original",
) -> MagicMock:
    """Create a minimal mock Segment object for export tests."""
    segment = MagicMock()
    segment.sequence_number = sequence_number
    segment.start_time = start_time
    segment.end_time = end_time
    segment.translated_text = translated_text
    segment.original_text = original_text
    return segment


def _patch_export_db(
    video: MagicMock | None, segments: list[Any]
) -> tuple[MagicMock, Any]:
    """Patch ``get_db_session`` inside the export module for a controlled session."""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = video
    (
        mock_db.query.return_value.filter.return_value.order_by.return_value.all
    ).return_value = segments
    patcher = patch("app.api.export.get_db_session")
    mock_cm = patcher.start()
    mock_cm.return_value.__enter__.return_value = mock_db
    return mock_db, patcher


def test_export_srt_uses_live_db_timecodes(authenticated_user) -> None:
    """SRT output must reflect the mocked database timestamps with a comma separator."""
    video = _mock_video(user_id=authenticated_user["user_id"])
    segments = [
        _mock_segment(1, 1.5, 4.0, "Hello", "Hello"),
        _mock_segment(2, 5.25, 7.999, "World", "World"),
    ]
    mock_db, patcher = _patch_export_db(video, segments)
    headers = authenticated_user["headers"]

    try:
        response = client.get("/export/vid-1/srt", headers=headers)
    finally:
        patcher.stop()

    assert response.status_code == 200
    body = response.text
    assert "Content-Disposition" in response.headers
    assert response.headers["Content-Type"] == "text/plain; charset=utf-8"

    assert "00:00:01,500 --> 00:00:04,000" in body
    assert "00:00:05,250 --> 00:00:07,999" in body
    assert "Hello\u200f" in body
    assert "World\u200f" in body


def test_export_vtt_uses_live_db_timecodes(authenticated_user) -> None:
    """VTT output must reflect mocked DB timestamps with a period separator."""
    video = _mock_video(user_id=authenticated_user["user_id"])
    segments = [
        _mock_segment(1, 0.0, 2.5, "First cue", "First cue"),
        _mock_segment(2, 3.75, 6.0, "Second cue", "Second cue"),
    ]
    mock_db, patcher = _patch_export_db(video, segments)
    headers = authenticated_user["headers"]

    try:
        response = client.get("/export/vid-1/vtt", headers=headers)
    finally:
        patcher.stop()

    assert response.status_code == 200
    body = response.text
    assert response.headers["Content-Type"] == "text/vtt; charset=utf-8"
    assert body.startswith("WEBVTT")

    assert "00:00:00.000 --> 00:00:02.500" in body
    assert "00:00:03.750 --> 00:00:06.000" in body
    assert "First cue\u200f" in body


def test_export_srt_requires_completed_video(authenticated_user) -> None:
    """SRT export for a non-completed video returns HTTP 400."""
    video = _mock_video(status="transcribed", user_id=authenticated_user["user_id"])
    segments = [_mock_segment(1, 0.0, 1.0, "Hello", "Hello")]
    mock_db, patcher = _patch_export_db(video, segments)
    headers = authenticated_user["headers"]

    try:
        response = client.get("/export/vid-1/srt", headers=headers)
    finally:
        patcher.stop()

    assert response.status_code == 400
    assert "Translation is still in progress" in response.json()["detail"]


def test_export_srt_video_not_found(authenticated_user) -> None:
    """Export for a missing video returns HTTP 404."""
    mock_db, patcher = _patch_export_db(None, [])
    headers = authenticated_user["headers"]

    try:
        response = client.get("/export/missing/srt", headers=headers)
    finally:
        patcher.stop()

    assert response.status_code == 404
    assert response.json()["detail"] == "Video not found"


def test_export_srt_with_real_sqlalchemy_session() -> None:
    """Regression: export must not crash after the database session closes."""
    from collections.abc import Generator
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from app.api.export import export_srt
    from app.core.auth import RequestIdentity
    from app.db.base import Base
    from app.models.video import Segment, Video, VideoStatus

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    @contextmanager
    def _in_memory_session() -> Generator[Session, None, None]:
        db = session_maker()
        try:
            yield db
        finally:
            db.close()

    # Seed the in-memory database.
    with _in_memory_session() as db:
        video = Video(
            id="vid-real",
            filename="real_video.mp4",
            file_path="/tmp/real_video.mp4",
            status=VideoStatus.COMPLETED.value,
            target_language="fa",
            user_id="user-test",
        )
        segment = Segment(
            id="seg-real",
            video_id=video.id,
            sequence_number=1,
            start_time=12.345,
            end_time=15.678,
            original_text="Hello",
            translated_text="Salam",
        )
        db.add(video)
        db.add(segment)
        db.commit()

    # Patch the export route to use the in-memory session factory.
    fake_identity = RequestIdentity(user_id="user-test", is_byok=False)
    with patch("app.api.export.get_db_session", new=_in_memory_session):
        response = export_srt("vid-real", identity=fake_identity)

    assert response.status_code == 200
    body = bytes(response.body).decode("utf-8")
    assert "00:00:12,345 --> 00:00:15,678" in body
    assert "Salam\u200f" in body
    assert 'filename="real_video.srt"' in response.headers["Content-Disposition"]
