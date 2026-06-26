"""Tests for server-side JWT revocation on logout."""

import uuid

import jwt
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.config import settings
from app.core.redis_pubsub import get_sync_redis_client
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User

client = TestClient(app)


def _unique_email() -> str:
    return f"logout_{uuid.uuid4().hex[:8]}@example.com"


def _create_verified_user(email: str, password: str = "secure-pass-123") -> User:
    from app.core.auth import hash_password

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
        return user
    finally:
        db.close()


def test_token_includes_jti_claim() -> None:
    """Newly created access tokens include a jti claim."""
    email = _unique_email()
    user = _create_verified_user(email)
    token = create_access_token(user.id)
    payload = jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    assert "jti" in payload
    assert isinstance(payload["jti"], str)


def test_logout_revokes_token() -> None:
    """After logout, the token is rejected by protected endpoints."""
    email = _unique_email()
    user = _create_verified_user(email)
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Token works before logout.
    me_before = client.get("/api/auth/me", headers=headers)
    assert me_before.status_code == 200

    logout_response = client.post("/api/auth/logout", headers=headers)
    assert logout_response.status_code == 200

    # Token is now revoked.
    me_after = client.get("/api/auth/me", headers=headers)
    assert me_after.status_code == 401
    assert "revoked" in me_after.json()["detail"].lower()


def test_logout_stores_revocation_in_redis() -> None:
    """Logout stores the token jti in Redis with a TTL."""
    email = _unique_email()
    user = _create_verified_user(email)
    token = create_access_token(user.id)
    payload = jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    jti = payload["jti"]

    response = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    redis = get_sync_redis_client()
    ttl = redis.ttl(f"revoked_token:{jti}")
    assert ttl > 0


def test_logout_with_malformed_token_returns_success() -> None:
    """Logout is best-effort and succeeds even for invalid tokens."""
    response = client.post(
        "/api/auth/logout",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert response.status_code == 200
