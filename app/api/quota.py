"""Quota API router."""

from typing import Any

from fastapi import APIRouter, Depends

from app.core.auth import RequestIdentity, get_current_user_or_byok
from app.core.quota import QuotaManager

router = APIRouter(prefix="/quota", tags=["quota"])


@router.get("/")
def get_quota(
    identity: RequestIdentity = Depends(get_current_user_or_byok),
) -> dict[str, Any]:
    """Return the authenticated user's remaining trial quota.

    Standard users see their remaining audio-minute allowance. BYOK users see
    the unlimited status along with the configured abuse limits.
    """
    return QuotaManager().get_quota_status(identity.user_id, is_byok=identity.is_byok)
