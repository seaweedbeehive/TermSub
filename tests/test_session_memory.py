"""Tests for session-memory backend behavior.

Covers the PATCH /videos/{id}/config endpoint and idempotent transcribe.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.video import Segment, Video, VideoStatus

client = TestClient(app)


def _upload_text_file(auth_headers: dict[str, str], tmp_path: Path, text: str) -> dict:
    """Upload a text file and return the created video payload."""
    file_path = tmp_path / "transcript.txt"
    file_path.write_text(text, encoding="utf-8")

    with open(file_path, "rb") as f:
        response = client.post(
            "/videos/upload",
            data={"target_language": "fa", "source_language": "en"},
            files={"file": ("transcript.txt", f, "text/plain")},
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    return response.json()


def _add_fake_translations(video_id: str) -> list[Segment]:
    """Mark all segments for a video as translated and set status to completed."""
    db = SessionLocal()
    try:
        video = db.query(Video).filter(Video.id == video_id).first()
        assert video is not None

        segments = db.query(Segment).filter(Segment.video_id == video_id).all()
        for segment in segments:
            segment.translated_text = f"[{segment.original_text}]"

        video.status = VideoStatus.COMPLETED.value
        db.commit()
        return segments
    finally:
        db.close()


def test_patch_config_updates_target_language(
    auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """PATCH /videos/{id}/config changes the target language."""
    video = _upload_text_file(auth_headers, tmp_path, "Hello world. How are you?")

    transcribe_response = client.post(
        f"/videos/{video['id']}/transcribe",
        headers=auth_headers,
    )
    assert transcribe_response.status_code == 200

    patch_response = client.patch(
        f"/videos/{video['id']}/config",
        json={"target_language": "es"},
        headers=auth_headers,
    )
    assert patch_response.status_code == 200, patch_response.text
    data = patch_response.json()
    assert data["target_language"] == "es"
    assert data["source_language"] == "en"


def test_patch_config_clears_translations_when_target_language_changes(
    auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """Changing target language drops existing translated segments."""
    video = _upload_text_file(auth_headers, tmp_path, "Hello world. How are you?")
    video_id = video["id"]

    transcribe_response = client.post(
        f"/videos/{video_id}/transcribe",
        headers=auth_headers,
    )
    assert transcribe_response.status_code == 200

    segments = _add_fake_translations(video_id)
    assert len(segments) > 0

    patch_response = client.patch(
        f"/videos/{video_id}/config",
        json={"target_language": "es"},
        headers=auth_headers,
    )
    assert patch_response.status_code == 200, patch_response.text
    data = patch_response.json()
    assert data["target_language"] == "es"
    assert data["status"] == VideoStatus.TRANSCRIBED.value

    db = SessionLocal()
    try:
        refreshed_segments = (
            db.query(Segment).filter(Segment.video_id == video_id).all()
        )
        assert len(refreshed_segments) == len(segments)
        for segment in refreshed_segments:
            assert segment.translated_text is None
    finally:
        db.close()


def test_transcribe_is_idempotent_when_already_transcribed(
    auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """POST /videos/{id}/transcribe does not re-queue an already-transcribed job."""
    video = _upload_text_file(auth_headers, tmp_path, "Hello world. How are you?")
    video_id = video["id"]

    first_response = client.post(
        f"/videos/{video_id}/transcribe",
        headers=auth_headers,
    )
    assert first_response.status_code == 200
    first_data = first_response.json()
    assert first_data["status"] == "completed"
    assert first_data["total_segments"] >= 1

    second_response = client.post(
        f"/videos/{video_id}/transcribe",
        headers=auth_headers,
    )
    assert second_response.status_code == 200, second_response.text
    second_data = second_response.json()
    assert second_data["status"] == "already_complete"
    assert second_data["video_id"] == video_id
    assert second_data["total_segments"] == first_data["total_segments"]
