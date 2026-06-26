"""Tests for Redis-backed sliding-window rate limiting on auth endpoints."""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.auth import hash_password
from app.core.rate_limit import RateLimiter
from app.core.redis_pubsub import get_sync_redis_client
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User

client = TestClient(app)


def _unique_email() -> str:
    return f"rate_{uuid.uuid4().hex[:8]}@example.com"


def _clear_rate_limit_keys(endpoint: str, identifier: str) -> None:
    """Remove any existing rate-limit keys for an endpoint/identifier."""
    redis = RateLimiter()._get_redis()
    if redis is None:
        return
    key = f"rate_limit:{endpoint}:{identifier}"
    redis.delete(key)


def test_signup_rate_limited_by_ip() -> None:
    """After 3 signups from the same IP, further signups are blocked for 429."""
    _clear_rate_limit_keys("signup", "testclient")

    password = "secure-pass-123"
    payload = {"email": _unique_email(), "password": password, "wants_updates": False}
    for i in range(3):
        response = client.post("/api/auth/signup", json=payload)
        assert response.status_code == 201, f"Signup {i + 1} should succeed"
        payload["email"] = _unique_email()

    blocked = client.post("/api/auth/signup", json=payload)
    assert blocked.status_code == 429
    assert "Too many attempts" in blocked.json()["detail"]


def test_login_rate_limited_by_email() -> None:
    """After 5 failed logins for the same email, further logins are blocked."""
    email = _unique_email()

    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password("correct-password"),
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    _clear_rate_limit_keys("login", email)

    for i in range(5):
        response = client.post(
            "/api/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
        assert response.status_code == 401, f"Login {i + 1} should fail"

    blocked = client.post(
        "/api/auth/login",
        json={"email": email, "password": "wrong-password"},
    )
    assert blocked.status_code == 429
    assert "Too many attempts" in blocked.json()["detail"]


def test_resend_verification_rate_limited_by_email() -> None:
    """After 5 resend requests for the same email, further requests are blocked."""
    email = _unique_email()
    _clear_rate_limit_keys("resend-verification", email)

    for i in range(5):
        response = client.post(
            "/api/auth/resend-verification",
            json={"email": email},
        )
        assert response.status_code == 200, f"Resend {i + 1} should succeed"

    blocked = client.post(
        "/api/auth/resend-verification",
        json={"email": email},
    )
    assert blocked.status_code == 429
    assert "Too many attempts" in blocked.json()["detail"]


def test_byok_start_rate_limited_by_ip() -> None:
    """After 3 byok-start requests from the same IP, further requests are blocked."""
    _clear_rate_limit_keys("byok-start", "testclient")

    for i in range(3):
        response = client.post(
            "/api/auth/byok-start",
            json={"api_key": f"sk-fake-key-{i}", "email": _unique_email()},
        )
        # The OpenAI key validation fails, but the rate-limit counter still increments.
        assert response.status_code == 400, f"BYOK start {i + 1} should fail validation"

    blocked = client.post(
        "/api/auth/byok-start",
        json={"api_key": "sk-fake-key-blocked", "email": _unique_email()},
    )
    assert blocked.status_code == 429
    assert "Too many attempts" in blocked.json()["detail"]


def test_rate_limit_skipped_when_redis_unavailable() -> None:
    """Auth endpoints remain usable when Redis is unreachable."""
    email = _unique_email()
    password = "secure-pass-123"

    with patch.object(RateLimiter, "_get_redis", return_value=None):
        response = client.post(
            "/api/auth/signup",
            json={"email": email, "password": password, "wants_updates": False},
        )
    assert response.status_code == 201


def test_resend_verification_cooldown_blocks_within_60_seconds() -> None:
    """A second resend-verification request for the same email within 60s is blocked."""
    email = _unique_email()
    password = "secure-pass-123"

    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password(password),
            is_active=True,
            is_email_verified=False,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    # Ensure no stale cooldown key exists.
    redis = get_sync_redis_client()
    redis.delete(f"resend_cooldown:{email}")

    first = client.post("/api/auth/resend-verification", json={"email": email})
    assert first.status_code == 200

    second = client.post("/api/auth/resend-verification", json={"email": email})
    assert second.status_code == 429
    assert "Please wait 60 seconds" in second.json()["detail"]
