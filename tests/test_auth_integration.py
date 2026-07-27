"""Integration tests for the authenticated upload/transcribe flow."""

import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.auth import hash_token
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User

client = TestClient(app)


def _unique_email() -> str:
    return f"e2e_{uuid.uuid4().hex[:8]}@example.com"


def _set_known_verification_token(email: str, raw_token: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        user.email_verification_token = hash_token(raw_token)
        user.email_verification_token_expires_at = datetime.utcnow() + timedelta(
            hours=24
        )
        db.commit()
    finally:
        db.close()


def test_signup_and_login_return_valid_token() -> None:
    """A user can sign up, verify their email, and then use the auth cookie."""
    email = _unique_email()
    password = "secure-pass-123"

    signup_response = client.post(
        "/api/auth/signup",
        json={"email": email, "password": password, "wants_updates": True},
    )
    assert signup_response.status_code == 201
    # The JWT is returned as an HttpOnly cookie, not in the response body.
    assert "access_token" not in signup_response.json()
    assert client.cookies.get("access_token")

    # Unverified users are blocked from authenticated endpoints.
    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 403

    _set_known_verification_token(email, "verify-me")

    verify_response = client.get("/api/auth/verify?token=verify-me")
    assert verify_response.status_code == 200

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == email


def test_email_is_normalized_during_signup_and_login() -> None:
    """Emails are lowercased and stripped so differently-cased inputs match."""
    base_email = _unique_email()
    upper_email = f"  {base_email.upper()}  "
    password = "secure-pass-123"

    signup_response = client.post(
        "/api/auth/signup",
        json={"email": upper_email, "password": password, "wants_updates": False},
    )
    assert signup_response.status_code == 201
    assert client.cookies.get("access_token")

    # Verify the stored email is normalized.
    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 403  # unverified

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == base_email.lower()).first()
        assert user is not None
        assert user.email == base_email.lower()
    finally:
        db.close()

    # Login with a different case should succeed and set a fresh cookie.
    login_response = client.post(
        "/api/auth/login",
        json={"email": base_email.upper(), "password": password},
    )
    assert login_response.status_code == 200
    assert client.cookies.get("access_token")


def test_expired_verification_token_is_rejected() -> None:
    """A token older than 24 hours is rejected with a clear expiry message."""
    email = _unique_email()
    password = "secure-pass-123"

    signup_response = client.post(
        "/api/auth/signup",
        json={"email": email, "password": password, "wants_updates": False},
    )
    assert signup_response.status_code == 201

    expired_token = f"expired-token-{uuid.uuid4().hex[:8]}"

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        user.email_verification_token = hash_token(expired_token)
        user.email_verification_token_expires_at = datetime.utcnow() - timedelta(
            seconds=1
        )
        db.commit()

        verify_response = client.get(f"/api/auth/verify?token={expired_token}")
        assert verify_response.status_code == 400
        assert verify_response.json()["detail"] == "Verification link expired"

        # The user remains unverified and can request a fresh token.
        assert user.is_email_verified is False
    finally:
        db.close()


def test_resend_verification_issues_new_token() -> None:
    """Resending verification creates a new token with a fresh 24-hour expiry."""
    email = _unique_email()
    password = "secure-pass-123"

    signup_response = client.post(
        "/api/auth/signup",
        json={"email": email, "password": password, "wants_updates": False},
    )
    assert signup_response.status_code == 201

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        old_token = user.email_verification_token
        old_expiry = user.email_verification_token_expires_at

        # Expire the old token.
        user.email_verification_token_expires_at = datetime.utcnow() - timedelta(
            hours=25
        )
        db.commit()

        resend_response = client.post(
            "/api/auth/resend-verification",
            json={"email": email},
        )
        assert resend_response.status_code == 200

        db.refresh(user)
        assert user.email_verification_token != old_token
        assert user.email_verification_token_expires_at > old_expiry
        assert user.email_verification_token_expires_at > datetime.utcnow()
    finally:
        db.close()


def test_upload_text_file_requires_authentication(tmp_path: Path) -> None:
    """Anonymous users receive 401/403 when trying to upload."""
    file_path = tmp_path / "test.txt"
    file_path.write_text("Hello world\nHow are you?", encoding="utf-8")

    with open(file_path, "rb") as f:
        response = client.post(
            "/videos/upload",
            data={"target_language": "fa", "source_language": "auto"},
            files={"file": ("test.txt", f, "text/plain")},
        )

    assert response.status_code in (401, 403)


def test_authenticated_text_upload_and_transcribe(
    auth_headers: dict[str, str], tmp_path: Path
) -> None:
    """A logged-in user can upload a text file and parse it without an API key."""
    file_path = tmp_path / "transcript.txt"
    file_path.write_text(
        "1\n00:00:01,000 --> 00:00:04,000\nHello world\n\n"
        "2\n00:00:05,000 --> 00:00:07,000\nHow are you?\n",
        encoding="utf-8",
    )

    with open(file_path, "rb") as f:
        upload_response = client.post(
            "/videos/upload",
            data={"target_language": "fa", "source_language": "auto"},
            files={"file": ("transcript.txt", f, "text/plain")},
            headers=auth_headers,
        )

    assert upload_response.status_code == 200
    video = upload_response.json()
    assert video["id"]
    assert video["target_language"] == "fa"

    transcribe_response = client.post(
        f"/videos/{video['id']}/transcribe",
        headers=auth_headers,
    )
    assert transcribe_response.status_code == 200
    data = transcribe_response.json()
    assert data["status"] == "transcribed"
    assert data["total_segments"] >= 1
