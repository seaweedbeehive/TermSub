"""Authentication helpers: password hashing, JWT tokens, and current-user dependency."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.quota import QuotaManager
from app.core.redis_pubsub import get_sync_redis_client
from app.db.session import get_db
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)

ALGORITHM = settings.JWT_ALGORITHM


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return pwd_context.hash(password)


def generate_verification_token() -> str:
    """Generate a secure random email verification token."""
    return secrets.token_urlsafe(32)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str) -> str:
    """Create a JWT access token valid for 7 days.

    Args:
        user_id: The UUID of the authenticated user.

    Returns:
        Encoded JWT token string.
    """
    expire = datetime.now(UTC) + timedelta(days=settings.JWT_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": user_id,
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def _is_token_revoked(jti: str) -> bool:
    """Return True if the token ID has been added to the Redis blocklist."""
    try:
        redis = get_sync_redis_client()
        return redis.exists(f"revoked_token:{jti}") > 0
    except Exception:
        # Redis unavailable: fail open rather than locking users out.
        return False


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token.

    Args:
        token: JWT token string.

    Returns:
        Decoded token payload.

    Raises:
        HTTPException: If the token is invalid, expired, or revoked.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    jti = payload.get("jti")
    if jti and _is_token_revoked(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency that returns the authenticated user.

    Reads the Authorization: Bearer <token> header, decodes the JWT,
    and loads the matching user from the database.

    Args:
        credentials: Bearer token credentials from the request header.
        db: Database session.

    Returns:
        Authenticated User instance.

    Raises:
        HTTPException: 401 if the token is missing, invalid, expired,
            or the user does not exist / is inactive.
    """
    token = credentials.credentials
    payload = decode_access_token(token)
    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox or request a new verification email.",
        )

    return user


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
    db: Session = Depends(get_db),
) -> User | None:
    """Return the authenticated user, or None if no/invalid token is provided.

    This dependency is useful for endpoints that support both authenticated
    users and BYOK (bring-your-own-key) traffic.
    """
    if not credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
    except HTTPException:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        return None
    return user


@dataclass
class RequestIdentity:
    """Resolved identity for a request, covering standard JWT and BYOK users."""

    user_id: str
    is_byok: bool
    api_key: str | None = None
    user: User | None = None


def get_current_user_or_byok(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    credentials: HTTPAuthorizationCredentials | None = Depends(security_optional),
    db: Session = Depends(get_db),
) -> RequestIdentity:
    """Resolve a request identity from either a JWT or a BYOK API key header.

    Standard users authenticate with Authorization: Bearer <jwt> and must have
    a verified email address. BYOK users authenticate with X-API-Key: <openai-key>.
    """
    if x_api_key and x_api_key.strip():
        api_key = x_api_key.strip()
        return RequestIdentity(
            user_id=QuotaManager.byok_user_id(api_key),
            is_byok=True,
            api_key=api_key,
        )

    if credentials:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = db.query(User).filter(User.id == user_id).first()
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email not verified. Please check your inbox or request a new verification email.",
            )

        return RequestIdentity(
            user_id=user.id,
            is_byok=False,
            user=user,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Provide a Bearer token or X-API-Key header.",
        headers={"WWW-Authenticate": "Bearer"},
    )
