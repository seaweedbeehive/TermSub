"""Tests for the user profile endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api import profile
from app.core.auth import create_access_token, hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.user import User
from app.models.video import ContentType, Video, VideoStatus

client = TestClient(app)


def _unique_email() -> str:
    return f"profile_{uuid.uuid4().hex[:8]}@example.com"


def _create_verified_user(password: str = "password123") -> User:
    """Create a verified test user and return the model instance."""
    db = SessionLocal()
    try:
        user = User(
            email=_unique_email(),
            password_hash=hash_password(password),
            is_active=True,
            is_email_verified=True,
            wants_updates=True,
            api_key_mode="standard",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def _headers_for(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def profile_user() -> User:
    user = _create_verified_user()
    yield user
    # Clean up the test user and any owned data.
    db = SessionLocal()
    try:
        db.query(Video).filter(Video.user_id == user.id).delete()
        db_user = db.query(User).filter(User.id == user.id).first()
        if db_user:
            db.delete(db_user)
        db.commit()
    finally:
        db.close()


class TestGetProfile:
    def test_get_profile_requires_auth(self) -> None:
        response = client.get("/api/profile/me")
        assert response.status_code == 401

    def test_get_profile_returns_user_data(self, profile_user: User) -> None:
        response = client.get("/api/profile/me", headers=_headers_for(profile_user))
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == profile_user.email
        assert data["api_key_mode"] == "standard"
        assert "total_jobs_processed" in data
        assert "total_minutes_used" in data


class TestUsageHistory:
    def test_usage_history_requires_auth(self) -> None:
        response = client.get("/api/profile/usage")
        assert response.status_code == 401

    def test_usage_history_returns_videos(self, profile_user: User) -> None:
        db = SessionLocal()
        try:
            video = Video(
                filename="test.mp4",
                file_path="/tmp/test.mp4",
                content_type=ContentType.VIDEO.value,
                status=VideoStatus.COMPLETED.value,
                user_id=profile_user.id,
            )
            db.add(video)
            db.commit()
        finally:
            db.close()

        response = client.get("/api/profile/usage", headers=_headers_for(profile_user))
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["filename"] == "test.mp4"


class TestUpdatePassword:
    def test_change_password_requires_current_password(  # noqa: E501
        self, profile_user: User
    ) -> None:
        response = client.put(
            "/api/profile/password",
            headers=_headers_for(profile_user),
            json={
                "current_password": "wrong-password",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
        )
        assert response.status_code == 401

    def test_change_password_updates_password(self, profile_user: User) -> None:
        response = client.put(
            "/api/profile/password",
            headers=_headers_for(profile_user),
            json={
                "current_password": "password123",
                "new_password": "newpass123",
                "confirm_password": "newpass123",
            },
        )
        assert response.status_code == 200


class TestUpdatePreferences:
    def test_update_preferences(self, profile_user: User) -> None:
        response = client.put(
            "/api/profile/preferences",
            headers=_headers_for(profile_user),
            json={"wants_updates": False, "display_name": "Test User"},
        )
        assert response.status_code == 200

        response = client.get("/api/profile/me", headers=_headers_for(profile_user))
        data = response.json()
        assert data["wants_updates"] is False
        assert data["display_name"] == "Test User"


class TestApiKeyMode:
    def test_switch_to_byok_requires_valid_key(  # noqa: E501
        self, profile_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(profile, "_validate_openai_api_key", lambda key: False)
        response = client.put(
            "/api/profile/api-key-mode",
            headers=_headers_for(profile_user),
            json={"mode": "byok", "api_key": "invalid-key"},
        )
        assert response.status_code == 400

    def test_switch_to_byok_with_valid_key(  # noqa: E501
        self, profile_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(profile, "_validate_openai_api_key", lambda key: True)
        response = client.put(
            "/api/profile/api-key-mode",
            headers=_headers_for(profile_user),
            json={"mode": "byok", "api_key": "sk-validopenaikey123"},
        )
        assert response.status_code == 200

        response = client.get("/api/profile/me", headers=_headers_for(profile_user))
        assert response.json()["api_key_mode"] == "byok"


class TestLogoutAllSessions:
    def test_logout_all_sessions_invalidates_old_tokens(  # noqa: E501
        self, profile_user: User
    ) -> None:
        import time

        old_token = create_access_token(profile_user.id)
        # Ensure the old token's iat is strictly before the current token's iat.
        time.sleep(1.1)

        current_token = create_access_token(profile_user.id)
        response = client.delete(
            "/api/profile/sessions",
            headers={"Authorization": f"Bearer {current_token}"},
        )
        assert response.status_code == 200

        # The current session remains active.
        response = client.get(
            "/api/profile/me",
            headers={"Authorization": f"Bearer {current_token}"},
        )
        assert response.status_code == 200

        # Tokens issued before the logout are invalidated.
        response = client.get(
            "/api/profile/me",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert response.status_code == 401


class TestDeleteAccount:
    def test_delete_account_requires_correct_password(  # noqa: E501
        self, profile_user: User
    ) -> None:
        response = client.request(
            "DELETE",
            "/api/profile/account",
            headers=_headers_for(profile_user),
            json={"password": "wrong-password", "confirmation": "DELETE"},
        )
        assert response.status_code == 401

    def test_delete_account_requires_delete_confirmation(  # noqa: E501
        self, profile_user: User
    ) -> None:
        response = client.request(
            "DELETE",
            "/api/profile/account",
            headers=_headers_for(profile_user),
            json={"password": "password123", "confirmation": "delete"},
        )
        assert response.status_code == 422

    def test_delete_account_removes_user(self, profile_user: User) -> None:
        headers = _headers_for(profile_user)
        response = client.request(
            "DELETE",
            "/api/profile/account",
            headers=headers,
            json={"password": "password123", "confirmation": "DELETE"},
        )
        assert response.status_code == 200

        response = client.get("/api/profile/me", headers=headers)
        assert response.status_code == 401
