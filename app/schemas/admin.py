"""Schemas for admin endpoints."""

from pydantic import BaseModel, EmailStr


class BulkDeleteRequest(BaseModel):
    """Request body for bulk-deleting users by email address."""

    emails: list[EmailStr]


class QuotaUpdateRequest(BaseModel):
    """Request body for updating a user's remaining minute quota."""

    minutes: float
