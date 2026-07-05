"""Shared test fixtures for TermSub."""

import uuid
from typing import Any

import pytest

from app.core.auth import create_access_token, hash_password
from app.core.redis_pool import get_redis_client as get_sync_redis_client
from app.db.session import SessionLocal
from app.models.user import User


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Create a test user and return Authorization headers with a valid JWT."""
    user_info = _create_test_user()
    yield user_info["headers"]


@pytest.fixture
def authenticated_user() -> dict[str, Any]:
    """Create a test user and return headers plus user_id for ownership tests."""
    yield _create_test_user()


@pytest.fixture(autouse=True)
def _clear_rate_limits_and_revocations() -> None:
    """Reset Redis rate-limit, revocation, and cooldown keys before each test."""
    try:
        redis = get_sync_redis_client()
        for key in redis.scan_iter(match="rate_limit:*", count=100):
            redis.delete(key)
        for key in redis.scan_iter(match="revoked_token:*", count=100):
            redis.delete(key)
        for key in redis.scan_iter(match="resend_cooldown:*", count=100):
            redis.delete(key)
    except Exception:
        # Redis may be unavailable; tests should still run.
        pass


def _create_test_user() -> dict[str, Any]:
    """Create a verified test user and return headers + user_id."""
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    password = "password123"
    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password(password),
            is_active=True,
            is_email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user.id)
        return {"headers": {"Authorization": f"Bearer {token}"}, "user_id": user.id}
    finally:
        db.close()
