"""Tests for BYOK auth, minutes quota, admin endpoints, analytics, WebSocket auth."""

import uuid
from io import BytesIO
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token, hash_password
from app.core.quota import QuotaManager
from app.db.session import SessionLocal
from app.main import app
from app.models.analytics import PageView, UsageEvent
from app.models.newsletter import NewsletterSignup
from app.models.user import User

client = TestClient(app)


def _unique_email(prefix: str = "test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


def _create_user(
    wants_updates: bool = False, is_admin: bool = False
) -> tuple[str, dict[str, str]]:
    """Create a standard user and return their id + auth headers."""
    email = _unique_email()
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password("password123"),
            is_active=True,
            is_email_verified=True,
            is_admin=is_admin,
            wants_updates=wants_updates,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user.id)
        return user.id, {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


def _create_admin_user() -> tuple[str, dict[str, str]]:
    """Create an admin user and return their id + auth headers."""
    return _create_user(is_admin=True)


def test_byok_upload_and_transcribe_text_file() -> None:
    """BYOK users can upload and transcribe a text file with only an X-API-Key."""
    byok_key = f"byok-{uuid.uuid4().hex}"
    headers = {"X-API-Key": byok_key}

    text_content = "This is a sample transcript with multiple words for testing."
    response = client.post(
        "/videos/upload",
        data={"target_language": "fa", "source_language": "en"},
        files={
            "file": ("sample.txt", BytesIO(text_content.encode("utf-8")), "text/plain")
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    video_id = response.json()["id"]

    transcribe_response = client.post(
        f"/videos/{video_id}/transcribe",
        headers=headers,
    )
    assert transcribe_response.status_code == 200, transcribe_response.text
    data = transcribe_response.json()
    assert data["status"] == "transcribed"
    assert data["total_segments"] > 0


def test_standard_quota_tracks_minutes() -> None:
    """QuotaManager records and reports audio minutes for standard users."""
    user_id = f"user-{uuid.uuid4().hex}"
    quota = QuotaManager()

    status = quota.get_quota_status(user_id)
    assert status["is_unlimited"] is False
    assert status["trial_minutes"] == 30
    assert status["minutes_used"] == 0
    assert status["minutes_remaining"] == 30

    quota.record_upload(user_id, estimated_minutes=10.0, is_byok=False)
    status = quota.get_quota_status(user_id)
    assert status["minutes_used"] == 10.0
    assert status["minutes_remaining"] == 20.0

    # Simulate transcription completing with 12 actual minutes.
    quota.record_actual_minutes(user_id, estimated_minutes=10.0, actual_minutes=12.0)
    status = quota.get_quota_status(user_id)
    assert status["minutes_used"] == 12.0
    assert status["minutes_remaining"] == 18.0

    # Clean up
    quota._redis.delete(quota._minutes_key(user_id))


def test_reserve_minutes_is_atomic_and_release_reclaims() -> None:
    """reserve_minutes atomically checks the cap and increments; release reclaims."""
    user_id = f"user-{uuid.uuid4().hex}"
    quota = QuotaManager()

    # Reservation within cap succeeds.
    assert quota.reserve_minutes(user_id, 10.0) is True
    status = quota.get_quota_status(user_id)
    assert status["minutes_used"] == 10.0
    assert status["minutes_remaining"] == 20.0

    # Reservation that would exceed cap is rejected and does not increment.
    assert quota.reserve_minutes(user_id, 25.0) is False
    status = quota.get_quota_status(user_id)
    assert status["minutes_used"] == 10.0
    assert status["minutes_remaining"] == 20.0

    # Release reclaims the reserved minutes.
    quota.release_minutes(user_id, 10.0)
    status = quota.get_quota_status(user_id)
    assert status["minutes_used"] == 0.0
    assert status["minutes_remaining"] == 30.0

    # Edge case: releasing zero or negative minutes is a no-op.
    quota.release_minutes(user_id, 0.0)
    quota.release_minutes(user_id, -5.0)
    status = quota.get_quota_status(user_id)
    assert status["minutes_used"] == 0.0

    # Clean up
    quota._redis.delete(quota._minutes_key(user_id))


def test_quota_endpoint_for_standard_user() -> None:
    """The /api/quota endpoint returns the minutes-based trial status."""
    _, headers = _create_user()

    response = client.get("/api/quota", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["is_unlimited"] is False
    assert data["limit_type"] == "lifetime_minutes"
    assert data["trial_minutes"] == 30
    assert data["minutes_remaining"] == 30


def test_quota_endpoint_for_byok_user() -> None:
    """The /api/quota endpoint returns unlimited status for BYOK users."""
    response = client.get("/api/quota", headers={"X-API-Key": "byok-test-key"})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["is_unlimited"] is True
    assert data["limit_type"] == "byok"


def test_admin_newsletter_signups() -> None:
    """The admin endpoint lists subscribers from standard signups and BYOK signups."""
    standard_email = _unique_email("standard")
    byok_email = _unique_email("byok")

    db = SessionLocal()
    try:
        user = User(
            email=standard_email,
            password_hash="hashed",
            is_active=True,
            is_email_verified=True,
            wants_updates=True,
        )
        db.add(user)
        db.add(NewsletterSignup(email=byok_email, source="byok"))
        db.commit()
    finally:
        db.close()

    _, admin_headers = _create_admin_user()
    response = client.get(
        "/api/auth/newsletter-signups",
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    emails = {row["email"] for row in response.json()}
    assert standard_email in emails
    assert byok_email in emails


def test_admin_stats() -> None:
    """The admin stats endpoint reports usage for today."""
    _, headers = _create_user(wants_updates=True)
    _, admin_headers = _create_admin_user()

    # Generate a usage event by uploading a text file.
    response = client.post(
        "/videos/upload",
        data={"target_language": "fa"},
        files={"file": ("admin_test.txt", BytesIO(b"hello world"), "text/plain")},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    stats_response = client.get(
        "/api/admin/stats",
        headers=admin_headers,
    )
    assert stats_response.status_code == 200, stats_response.text
    data = stats_response.json()
    assert data["total_users"] >= 1
    assert data["uploads_today"] >= 1
    assert data["top_users_this_week"] is not None


def test_admin_users_list_and_actions() -> None:
    """The admin users endpoint lists users and supports reset-quota / toggle-mode."""
    user_id, _ = _create_user()
    _, admin_headers = _create_admin_user()

    users_response = client.get(
        "/api/admin/users",
        headers=admin_headers,
    )
    assert users_response.status_code == 200, users_response.text
    users = users_response.json()
    assert any(u["id"] == user_id for u in users)

    target_user = next(u for u in users if u["id"] == user_id)
    assert target_user["email"]
    assert "api_key_mode" in target_user
    assert "minutes_used" in target_user

    # Toggle mode
    toggle_response = client.post(
        f"/api/admin/users/{user_id}/toggle-mode",
        headers=admin_headers,
    )
    assert toggle_response.status_code == 200, toggle_response.text
    assert toggle_response.json()["api_key_mode"] == "byok"

    # Reset quota (should succeed even if no minutes reserved)
    reset_response = client.post(
        f"/api/admin/users/{user_id}/reset-quota",
        headers=admin_headers,
    )
    assert reset_response.status_code == 200, reset_response.text
    assert reset_response.json()["message"] == "Quota reset successfully"


def test_admin_users_rejects_non_admin_user() -> None:
    """Admin user endpoints reject requests from non-admin users."""
    _, user_headers = _create_user()

    response = client.get("/api/admin/users", headers=user_headers)
    assert response.status_code == 403, response.text


def test_analytics_logging() -> None:
    """A request to an authenticated endpoint creates a PageView and UsageEvent."""
    _, headers = _create_user()

    # PageView is logged asynchronously in a background thread; give it a moment.
    response = client.get("/api/quota", headers=headers)
    assert response.status_code == 200

    import time

    time.sleep(0.5)

    db = SessionLocal()
    try:
        page_views = db.query(PageView).filter(PageView.path == "/api/quota").all()
        assert len(page_views) >= 1
    finally:
        db.close()

    # Upload creates a UsageEvent.
    upload_response = client.post(
        "/videos/upload",
        data={"target_language": "fa"},
        files={"file": ("analytics_test.txt", BytesIO(b"test"), "text/plain")},
        headers=headers,
    )
    assert upload_response.status_code == 200, upload_response.text

    time.sleep(0.5)

    db = SessionLocal()
    try:
        usage_events = (
            db.query(UsageEvent)
            .filter(UsageEvent.event_type == "upload")
            .order_by(UsageEvent.created_at.desc())
            .all()
        )
        assert len(usage_events) >= 1
    finally:
        db.close()


def test_websocket_accepts_valid_subprotocol_token() -> None:
    """WebSocket connects when a short-lived WS token is supplied via subprotocol."""
    db = SessionLocal()
    try:
        user = User(
            email=_unique_email("ws"),
            password_hash=hash_password("password123"),
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user.id)
    finally:
        db.close()

    # Obtain a dedicated WS token; access tokens are not accepted here.
    headers = {"Authorization": f"Bearer {token}"}
    ws_token_response = client.post("/api/auth/ws-token", headers=headers)
    assert ws_token_response.status_code == 200, ws_token_response.text
    ws_token = ws_token_response.json()["ws_token"]
    subprotocol = ws_token_response.json()["subprotocol"]

    with client.websocket_connect(
        "/ws/videos/test-video", subprotocols=[subprotocol, ws_token]
    ) as ws:
        assert ws.accepted_subprotocol == subprotocol
        data = ws.receive_json()
        assert data["type"] == "connected"


def test_websocket_accepts_byok_subprotocol_key() -> None:
    """WebSocket connects when a BYOK API key is supplied via Sec-WebSocket-Protocol."""
    with client.websocket_connect(
        "/ws/videos/test-video", subprotocols=["termsub-byok", "sk-byok-test-key"]
    ) as ws:
        assert ws.accepted_subprotocol == "termsub-byok"
        data = ws.receive_json()
        assert data["type"] == "connected"


def test_websocket_rejects_missing_token() -> None:
    """WebSocket refuses connection when no credentials are provided."""
    with (
        pytest.raises(Exception),  # noqa: B017
        client.websocket_connect("/ws/videos/test-video") as ws,
    ):
        ws.receive_json()


def test_byok_start_skips_newsletter_when_email_belongs_to_user() -> None:
    """BYOK newsletter signup is skipped if the email is already a standard user."""
    email = _unique_email("byok_dup")

    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password("password123"),
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    with patch("app.api.auth._validate_openai_api_key", return_value=True):
        response = client.post(
            "/api/auth/byok-start",
            json={"api_key": "sk-byok-test-key", "email": email},
        )

    assert response.status_code == 200
    assert response.json()["valid"] is True

    db = SessionLocal()
    try:
        signup = (
            db.query(NewsletterSignup).filter(NewsletterSignup.email == email).first()
        )
        assert signup is None
    finally:
        db.close()
