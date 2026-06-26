"""Shared admin authentication dependency."""

from fastapi import Depends, HTTPException, status

from app.core.auth import get_current_user
from app.models.user import User


def require_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Require an authenticated user with admin privileges."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
