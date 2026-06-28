"""Pydantic schemas for user profile endpoints."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator


class ProfileMeResponse(BaseModel):
    """Public profile information for the authenticated user."""

    id: str
    email: str
    display_name: str | None
    is_email_verified: bool
    wants_updates: bool
    api_key_mode: str
    total_jobs_processed: int
    total_minutes_used: int
    created_at: datetime

    class Config:
        from_attributes = True


class UsageHistoryItem(BaseModel):
    """Single usage history entry for a transcription job."""

    video_id: str
    filename: str
    content_type: str
    status: str
    created_at: datetime
    minutes_used: int

    class Config:
        from_attributes = True


class UsageHistoryResponse(BaseModel):
    """Paginated usage history response."""

    items: list[UsageHistoryItem]
    total: int
    skip: int
    limit: int


class UpdateEmailRequest(BaseModel):
    """Request to update the user's email address."""

    new_email: EmailStr
    password: str = Field(..., min_length=8)


class UpdatePasswordRequest(BaseModel):
    """Request to change the user's password."""

    current_password: str
    new_password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info: ValidationInfo) -> str:
        if v != info.data.get("new_password"):
            raise ValueError("Passwords do not match")
        return v


class UpdatePreferencesRequest(BaseModel):
    """Request to update user preferences."""

    wants_updates: bool | None = None
    display_name: str | None = Field(None, max_length=255)


class UpdateApiKeyModeRequest(BaseModel):
    """Request to switch between standard and BYOK API key modes."""

    mode: str = Field(..., pattern="^(standard|byok)$")
    api_key: str | None = Field(None, min_length=10)

    @field_validator("api_key")
    @classmethod
    def require_api_key_for_byok(
        cls, v: str | None, info: ValidationInfo
    ) -> str | None:
        mode = info.data.get("mode")
        if mode == "byok" and not v:
            raise ValueError("api_key is required when switching to BYOK mode")
        return v


class DeleteAccountRequest(BaseModel):
    """Request to delete the user account."""

    password: str
    confirmation: str

    @field_validator("confirmation")
    @classmethod
    def confirmation_matches(cls, v: str) -> str:
        if v != "DELETE":
            raise ValueError('Confirmation must be "DELETE"')
        return v


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str
