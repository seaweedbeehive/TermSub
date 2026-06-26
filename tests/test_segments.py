"""Tests for the segment update endpoint."""

from typing import Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _mock_video(user_id: str | None = None) -> MagicMock:
    """Create a mock video object for ownership checks."""
    video = MagicMock()
    video.user_id = user_id
    return video


def _mock_segment(start_time: float = 10.0, end_time: float = 20.0) -> MagicMock:
    """Create a mock segment object for PATCH endpoint tests."""
    segment = MagicMock()
    segment.start_time = start_time
    segment.end_time = end_time
    segment.translated_text = "original translation"
    return segment


def _patch_db_session(
    video: MagicMock | None, segment: MagicMock | None
) -> tuple[MagicMock, Any]:
    """Patch ``get_db_session`` in the videos router to return a controlled session.

    The first query is for the video (ownership check), the second for the segment.
    """
    mock_db = MagicMock()
    # update_segment queries Video first, then Segment. List side_effect returns
    # items sequentially and avoids MagicMock wrapping the returned objects.
    mock_db.query.return_value.filter.return_value.first.side_effect = [video, segment]
    patcher = patch("app.api.videos.get_db_session")
    mock_cm = patcher.start()
    mock_cm.return_value.__enter__.return_value = mock_db
    return mock_db, patcher


def test_update_segment_with_valid_timecodes_and_text(authenticated_user) -> None:
    """Valid payload updates text and timecodes and returns 200."""
    video = _mock_video(user_id=authenticated_user["user_id"])
    segment = _mock_segment()
    mock_db, patcher = _patch_db_session(video, segment)

    try:
        response = client.patch(
            "/videos/vid1/segments/seg1",
            headers=authenticated_user["headers"],
            json={
                "translated_text": "updated translation",
                "start_time": "00:00:15,000",
                "end_time": "00:00:25,000",
            },
        )
    finally:
        patcher.stop()

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert segment.translated_text == "updated translation"
    assert segment.start_time == 15.0
    assert segment.end_time == 25.0


def test_update_segment_invalid_timecode_format(authenticated_user) -> None:
    """Malformed timecode strings return HTTP 422."""
    video = _mock_video(user_id=authenticated_user["user_id"])
    segment = _mock_segment()
    mock_db, patcher = _patch_db_session(video, segment)

    try:
        response = client.patch(
            "/videos/vid1/segments/seg1",
            headers=authenticated_user["headers"],
            json={"start_time": "not-a-timecode"},
        )
    finally:
        patcher.stop()

    assert response.status_code == 422
    assert "Invalid start_time" in response.json()["detail"]


def test_update_segment_start_after_end(authenticated_user) -> None:
    """start_time >= end_time returns HTTP 422."""
    video = _mock_video(user_id=authenticated_user["user_id"])
    segment = _mock_segment()
    mock_db, patcher = _patch_db_session(video, segment)

    try:
        response = client.patch(
            "/videos/vid1/segments/seg1",
            headers=authenticated_user["headers"],
            json={
                "start_time": "00:00:30,000",
                "end_time": "00:00:20,000",
            },
        )
    finally:
        patcher.stop()

    assert response.status_code == 422
    assert "start_time must be strictly before end_time" in response.json()["detail"]


def test_update_segment_not_found(authenticated_user) -> None:
    """Request for a non-existent segment returns HTTP 404."""
    video = _mock_video(user_id=authenticated_user["user_id"])
    mock_db, patcher = _patch_db_session(video, None)

    try:
        response = client.patch(
            "/videos/vid1/segments/missing",
            headers=authenticated_user["headers"],
            json={"translated_text": "irrelevant"},
        )
    finally:
        patcher.stop()

    assert response.status_code == 404
    assert response.json()["detail"] == "Segment not found"


def test_update_segment_persists_to_real_database(authenticated_user) -> None:
    """Regression: PATCH must actually commit changes so exports see them."""
    import tempfile
    from collections.abc import Generator
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from app.db.base import Base
    from app.models.video import Segment, Video, VideoStatus

    db_path = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    @contextmanager
    def _in_memory_session() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    with _in_memory_session() as db:
        video = Video(
            id="vid-real",
            filename="real.mp4",
            file_path="/tmp/real.mp4",
            status=VideoStatus.COMPLETED.value,
            target_language="fa",
            user_id=authenticated_user["user_id"],
        )
        segment = Segment(
            id="seg-real",
            video_id="vid-real",
            sequence_number=1,
            start_time=1.0,
            end_time=3.0,
            original_text="Hello",
            translated_text="Salam",
        )
        db.add(video)
        db.add(segment)

    with patch("app.api.videos.get_db_session", new=_in_memory_session):
        response = client.patch(
            "/videos/vid-real/segments/seg-real",
            headers=authenticated_user["headers"],
            json={
                "translated_text": "Updated text",
                "start_time": "00:00:05,500",
                "end_time": "00:00:08,000",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "success"

    with _in_memory_session() as db:
        updated = db.query(Segment).filter(Segment.id == "seg-real").first()
        assert updated is not None
        assert updated.translated_text == "Updated text"
        assert updated.start_time == 5.5
        assert updated.end_time == 8.0
