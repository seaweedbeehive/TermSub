"""Per-user upload quota enforcement using Redis."""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from app.core.redis_pool import get_redis_client as get_sync_redis_client

logger = logging.getLogger(__name__)

# Standard trial users get 30 minutes of transcribed audio in total.
DEFAULT_TRIAL_MINUTES = 30

# BYOK abuse limits.
BYOK_MAX_UPLOAD_MB = 500
BYOK_MAX_CONCURRENT_JOBS = 10
BYOK_JOB_TTL_SECONDS = 120

# Long-lived TTL for quota ownership metadata. BYOK ownership is stored in
# Redis, so use a 1-year TTL to avoid locking users out of older videos.
OWNER_TTL_SECONDS = 365 * 24 * 60 * 60


class QuotaManager:
    """Enforces the trial minute allowance for standard users.

    Standard users are limited to a lifetime total of transcribed audio minutes.
    BYOK (bring-your-own-key) users bypass the minute allowance but are still
    subject to basic abuse limits and a concurrent-job ceiling.
    """

    def __init__(self, trial_minutes: float = DEFAULT_TRIAL_MINUTES) -> None:
        self.trial_minutes = trial_minutes
        self._redis = get_sync_redis_client()

    @staticmethod
    def _minutes_key(user_id: str) -> str:
        return f"quota:{user_id}:minutes"

    @staticmethod
    def _byok_job_key(user_id: str, task_id: str) -> str:
        return f"byok:job:{user_id}:{task_id}"

    @staticmethod
    def _byok_job_pattern(user_id: str) -> str:
        return f"byok:job:{user_id}:*"

    @staticmethod
    def _video_owner_key(video_id: str) -> str:
        return f"quota:video_owner:{video_id}"

    @staticmethod
    def _video_byok_key(video_id: str) -> str:
        return f"quota:video_byok:{video_id}"

    @staticmethod
    def _video_estimated_minutes_key(video_id: str) -> str:
        return f"quota:video_estimated_minutes:{video_id}"

    @staticmethod
    def byok_user_id(api_key: str) -> str:
        """Return a stable, opaque identifier for a BYOK API key."""
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]

    def _get_float(self, key: str) -> float:
        try:
            value = self._redis.get(key)
            return float(value) if value is not None else 0.0
        except Exception as exc:
            logger.error("Redis read failed for %s: %s", key, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota service unavailable",
            ) from exc

    def _count_byok_jobs(self, user_id: str) -> int:
        try:
            return sum(1 for _ in self._redis.scan_iter(
                match=self._byok_job_pattern(user_id), count=100
            ))
        except Exception as exc:
            logger.error("Redis scan failed for BYOK jobs %s: %s", user_id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota service unavailable",
            ) from exc

    def check_upload_allowed(
        self,
        user_id: str,
        file_size_mb: float,
        estimated_minutes: float,
        is_byok: bool = False,
    ) -> dict[str, Any]:
        """Check whether an upload is within the user's limits.

        Args:
            user_id: UUID for standard users or a stable BYOK key hash.
            file_size_mb: Size of the incoming file in megabytes.
            estimated_minutes: Estimated audio duration in minutes.
            is_byok: Whether the caller is a BYOK user.

        Returns:
            Dict with `allowed` (bool), `reason` (str | None), and
            `is_unlimited` (bool).
        """
        if is_byok:
            if file_size_mb > BYOK_MAX_UPLOAD_MB:
                return {
                    "allowed": False,
                    "reason": f"BYOK uploads are limited to {BYOK_MAX_UPLOAD_MB} MB per file.",
                    "is_unlimited": True,
                }

            concurrent_jobs = self._count_byok_jobs(user_id)
            if concurrent_jobs >= BYOK_MAX_CONCURRENT_JOBS:
                return {
                    "allowed": False,
                    "reason": (
                        f"BYOK users are limited to {BYOK_MAX_CONCURRENT_JOBS} "
                        "concurrent jobs. Please wait for an existing job to finish."
                    ),
                    "is_unlimited": True,
                }

            return {
                "allowed": True,
                "reason": None,
                "is_unlimited": True,
            }

        current_minutes = self._get_float(self._minutes_key(user_id))
        if current_minutes + estimated_minutes > self.trial_minutes:
            return {
                "allowed": False,
                "reason": (
                    f"Upload would exceed the trial audio limit "
                    f"({self.trial_minutes} minutes). "
                    f"Remaining: {max(0, self.trial_minutes - current_minutes):.1f} minutes. "
                    f"Write us an email if you need more quota!"
                ),
                "is_unlimited": False,
            }

        return {
            "allowed": True,
            "reason": None,
            "is_unlimited": False,
        }

    def reserve_minutes(
        self,
        user_id: str,
        estimated_minutes: float,
    ) -> bool:
        """Atomically reserve estimated minutes for a standard user.

        Uses a Lua script to check the cap and increment in a single Redis
        operation, eliminating the race condition between read and write.

        Returns:
            True if the reservation succeeded, False if it would exceed the cap.
        """
        if estimated_minutes <= 0:
            return True

        key = self._minutes_key(user_id)
        lua = """
        local current = tonumber(redis.call('get', KEYS[1]) or 0)
        local estimate = tonumber(ARGV[1])
        local cap = tonumber(ARGV[2])
        if current + estimate > cap then
            return 0
        end
        redis.call('incrbyfloat', KEYS[1], estimate)
        return 1
        """
        try:
            result = self._redis.eval(
                lua, 1, key, str(estimated_minutes), str(self.trial_minutes)
            )
            return bool(int(result))
        except Exception as exc:
            logger.error("Redis reservation failed for %s: %s", user_id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota service unavailable",
            ) from exc

    def release_minutes(
        self,
        user_id: str,
        estimated_minutes: float,
    ) -> None:
        """Release previously reserved minutes when an upload fails after reservation."""
        if estimated_minutes <= 0:
            return

        key = self._minutes_key(user_id)
        try:
            self._redis.incrbyfloat(key, -estimated_minutes)
        except Exception as exc:
            logger.error(
                "Redis release failed for %s (%.2f min): %s",
                user_id,
                estimated_minutes,
                exc,
            )
            # Do not raise here: the upload has already failed and we do not
            # want to mask the original error. The minute counter may be
            # slightly off until the worker reconciles it.

    def record_upload(
        self,
        user_id: str,
        estimated_minutes: float,
        is_byok: bool = False,
    ) -> None:
        """Reserve estimated audio minutes for a standard user's upload.

        Deprecated: prefer ``reserve_minutes`` for new call sites because it
        checks the cap atomically.
        """
        if is_byok:
            return

        try:
            self._redis.incrbyfloat(self._minutes_key(user_id), estimated_minutes)
        except Exception as exc:
            logger.error("Redis write failed while recording upload: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota service unavailable",
            ) from exc

    def record_actual_minutes(
        self,
        user_id: str,
        estimated_minutes: float,
        actual_minutes: float,
    ) -> None:
        """Adjust the minutes counter after transcription completes."""
        delta = actual_minutes - estimated_minutes
        try:
            self._redis.incrbyfloat(self._minutes_key(user_id), delta)
        except Exception as exc:
            logger.error("Redis write failed while recording minutes: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota service unavailable",
            ) from exc

    def set_video_owner(
        self,
        video_id: str,
        user_id: str,
        is_byok: bool = False,
        estimated_minutes: float = 0.0,
    ) -> None:
        """Remember which user owns a video so the worker can bill minutes."""
        try:
            pipe = self._redis.pipeline()
            pipe.setex(self._video_owner_key(video_id), OWNER_TTL_SECONDS, user_id)
            pipe.setex(
                self._video_byok_key(video_id),
                OWNER_TTL_SECONDS,
                "1" if is_byok else "0",
            )
            pipe.setex(
                self._video_estimated_minutes_key(video_id),
                OWNER_TTL_SECONDS,
                str(estimated_minutes),
            )
            pipe.execute()
        except Exception as exc:
            logger.error("Redis write failed while setting video owner: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota service unavailable",
            ) from exc

    def get_video_owner(self, video_id: str) -> tuple[str | None, bool, float]:
        """Return the owner user_id, BYOK flag, and estimated minutes for a video."""
        try:
            owner = self._redis.get(self._video_owner_key(video_id))
            byok_flag = self._redis.get(self._video_byok_key(video_id))
            estimated_raw = self._redis.get(self._video_estimated_minutes_key(video_id))
            estimated_minutes = float(estimated_raw) if estimated_raw else 0.0
            return (
                owner if owner else None,
                byok_flag == "1",
                estimated_minutes,
            )
        except Exception as exc:
            logger.error("Redis read failed for video owner %s: %s", video_id, exc)
            return None, False, 0.0

    def register_byok_job(self, user_id: str, task_id: str) -> None:
        """Register an active BYOK job with a short TTL."""
        try:
            self._redis.setex(
                self._byok_job_key(user_id, task_id),
                BYOK_JOB_TTL_SECONDS,
                "1",
            )
        except Exception as exc:
            logger.error("Redis write failed while registering BYOK job: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota service unavailable",
            ) from exc

    def refresh_byok_job(self, user_id: str, task_id: str) -> None:
        """Refresh the TTL of an active BYOK job (heartbeat)."""
        try:
            self._redis.expire(
                self._byok_job_key(user_id, task_id),
                BYOK_JOB_TTL_SECONDS,
            )
        except Exception as exc:
            logger.error("Redis write failed while refreshing BYOK job: %s", exc)

    def unregister_byok_job(self, user_id: str, task_id: str) -> None:
        """Remove an active BYOK job."""
        try:
            self._redis.delete(self._byok_job_key(user_id, task_id))
        except Exception as exc:
            logger.error("Redis write failed while unregistering BYOK job: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota service unavailable",
            ) from exc

    def set_quota(self, user_id: str, minutes: float) -> None:
        """Set the user's remaining minute quota in Redis.

        The quota model stores minutes *used* and computes remaining as
        ``trial_minutes - used``. Setting remaining to ``minutes`` means storing
        ``used = trial_minutes - minutes``. Negative used values are allowed and
        effectively grant extra quota beyond the default trial allowance.
        """
        try:
            used = self.trial_minutes - float(minutes)
            self._redis.set(self._minutes_key(user_id), str(used))
        except Exception as exc:
            logger.error("Redis set_quota failed for %s: %s", user_id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Quota service unavailable",
            ) from exc

    def get_quota_status(self, user_id: str, is_byok: bool = False) -> dict[str, Any]:
        """Return remaining quota for the UI.

        Args:
            user_id: UUID of the authenticated user or BYOK key hash.
            is_byok: Whether the caller is a BYOK user.

        Returns:
            Dict with limits, current/remaining usage, and is_unlimited.
        """
        if is_byok:
            return {
                "is_unlimited": True,
                "limit_type": "byok",
                "trial_minutes": None,
                "minutes_used": None,
                "minutes_remaining": None,
                "byok_max_upload_mb": BYOK_MAX_UPLOAD_MB,
                "byok_max_concurrent_jobs": BYOK_MAX_CONCURRENT_JOBS,
            }

        current_minutes = self._get_float(self._minutes_key(user_id))

        return {
            "is_unlimited": False,
            "limit_type": "lifetime_minutes",
            "trial_minutes": self.trial_minutes,
            "minutes_used": round(current_minutes, 2),
            "minutes_remaining": round(
                max(0.0, self.trial_minutes - current_minutes), 2
            ),
        }
