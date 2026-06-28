"""Pydantic schemas for authentication endpoints."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator


class UserSignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    wants_updates: bool = True


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info: ValidationInfo) -> str:
        if v != info.data.get("new_password"):
            raise ValueError("Passwords do not match")
        return v


class BYOKStartRequest(BaseModel):
    api_key: str = Field(..., min_length=10)
    email: EmailStr | None = None


class BYOKStartResponse(BaseModel):
    valid: bool
    message: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    is_email_verified: bool
    wants_updates: bool
    is_active: bool
    is_admin: bool
    api_key_mode: str

    class Config:
        from_attributes = True


class NewsletterSubscriberOut(BaseModel):
    email: str
    source: str
    created_at: datetime
