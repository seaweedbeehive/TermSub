"""Tests for the password reset flow."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token, hash_password, hash_token, verify_password
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User

client = TestClient(app)


def _unique_email() -> str:
    return f"reset_{uuid.uuid4().hex[:8]}@example.com"


def _create_user(password: str = "password123") -> User:
    db = SessionLocal()
    try:
        user = User(
            email=_unique_email(),
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


@pytest.fixture
def reset_user() -> User:
    user = _create_user()
    yield user
    db = SessionLocal()
    try:
        db_user = db.query(User).filter(User.id == user.id).first()
        if db_user:
            db.delete(db_user)
            db.commit()
    finally:
        db.close()


class TestForgotPassword:
    def test_forgot_password_returns_same_message_for_missing_email(self) -> None:
        response = client.post(
            "/api/auth/forgot-password",
            json={"email": _unique_email()},
        )
        assert response.status_code == 200
        assert "If an account exists" in response.json()["message"]

    def test_forgot_password_sets_reset_token(self, reset_user: User) -> None:
        response = client.post(
            "/api/auth/forgot-password",
            json={"email": reset_user.email},
        )
        assert response.status_code == 200

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == reset_user.id).first()
            assert user is not None
            assert user.password_reset_token is not None
            assert user.password_reset_token_expires_at is not None
        finally:
            db.close()


class TestResetPassword:
    def test_reset_password_with_invalid_token_fails(self) -> None:
        response = client.post(
            "/api/auth/reset-password",
            json={
                "reset_token": "invalid-token",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
        )
        assert response.status_code == 400

    def test_reset_password_with_expired_token_fails(self, reset_user: User) -> None:
        from datetime import datetime, timedelta

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == reset_user.id).first()
            assert user is not None
            user.password_reset_token = hash_token("expired-token")
            user.password_reset_token_expires_at = datetime.utcnow() - timedelta(hours=1)
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/api/auth/reset-password",
            json={
                "reset_token": "expired-token",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
        )
        assert response.status_code == 400

    def test_reset_password_updates_password(self, reset_user: User) -> None:
        from datetime import datetime, timedelta

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == reset_user.id).first()
            assert user is not None
            user.password_reset_token = hash_token("valid-token")
            user.password_reset_token_expires_at = datetime.utcnow() + timedelta(hours=24)
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/api/auth/reset-password",
            json={
                "reset_token": "valid-token",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
        )
        assert response.status_code == 200

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == reset_user.id).first()
            assert user is not None
            assert user.password_reset_token is None
            assert user.password_reset_token_expires_at is None
            assert verify_password("newpass123", user.password_hash)
        finally:
            db.close()

    def test_reset_password_requires_matching_passwords(self, reset_user: User) -> None:
        from datetime import datetime, timedelta

        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == reset_user.id).first()
            assert user is not None
            user.password_reset_token = hash_token("valid-token")
            user.password_reset_token_expires_at = datetime.utcnow() + timedelta(hours=24)
            db.commit()
        finally:
            db.close()

        response = client.post(
            "/api/auth/reset-password",
            json={
                "reset_token": "valid-token",
                "new_password": "newpass123",
                "confirm_password": "different123",
            },
        )
        assert response.status_code == 422
