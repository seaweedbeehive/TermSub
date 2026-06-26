"""Pydantic schemas for authentication endpoints."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserSignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    wants_updates: bool = True


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


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
