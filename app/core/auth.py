"""Authentication helpers: password hashing, JWT tokens, and current-user dependency."""

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.quota import QuotaManager
from app.core.redis_pool import get_redis_client as get_sync_redis_client
from app.db.session import get_db
from app.models.user import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS_TOKEN_COOKIE = "access_token"

# Subprotocol used to pass a short-lived WebSocket auth token from the client.
WS_TOKEN_SUBPROTOCOL = "termsub-ws-token"

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


def hash_token(token: str) -> str:
    """Hash a single-use email verification or password-reset token.

    SHA-256 is sufficient here because the tokens are already high-entropy
    random strings and the hash is only used for storage-time comparison.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_token(
    user_id: str,
    ttl: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT with the given lifetime and optional claims."""
    now = datetime.now(UTC)
    expire = now + ttl
    payload: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(
    token: str,
    *,
    required_scope: str | None = None,
) -> dict[str, Any] | None:
    """Decode a JWT, optionally requiring a specific scope claim.

    Returns None instead of raising on any validation error so callers can
    treat invalid/missing tokens uniformly.
    """
    try:
        # PyJWT types decode()'s return as Any since the payload shape isn't
        # fixed; cast to the shape every caller in this module actually relies on.
        payload = cast(
            "dict[str, Any]",
            jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM]),
        )
    except jwt.InvalidTokenError:
        return None

    if required_scope is not None and payload.get("scope") != required_scope:
        return None

    jti = payload.get("jti")
    if jti and _is_token_revoked(jti):
        return None

    return payload


def create_access_token(user_id: str) -> str:
    """Create a JWT access token valid for 7 days.

    Args:
        user_id: The UUID of the authenticated user.

    Returns:
        Encoded JWT token string.
    """
    return _create_token(user_id, timedelta(days=settings.JWT_EXPIRE_DAYS))


def create_ws_token(user_id: str) -> str:
    """Create a short-lived token used only for WebSocket authentication.

    The token is valid for 60 seconds and includes a scope claim so it cannot
    be used as a general access token.
    """
    return _create_token(user_id, timedelta(seconds=60), extra_claims={"scope": "ws"})


def decode_ws_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a WebSocket authentication token.

    Returns the token payload if valid, otherwise None.
    """
    return _decode_token(token, required_scope="ws")


def _get_access_token_from_request(request: Request) -> str | None:
    """Read the JWT from the Authorization header, falling back to the cookie.

    Programmatic clients and tests explicitly send an Authorization header,
    so it takes precedence over the HttpOnly cookie. Browser clients that rely
    on the cookie still work when no header is present.
    """
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(ACCESS_TOKEN_COOKIE)


def _is_token_revoked(jti: str) -> bool:
    """Return True if the token ID has been added to the Redis blocklist."""
    try:
        redis = get_sync_redis_client()
        # redis-py's stubs type .exists() as Awaitable[int] | int since the
        # method is shared with the async client via a common mixin; this
        # client is the synchronous one (get_sync_redis_client), so it always
        # returns a plain int here.
        return cast("int", redis.exists(f"revoked_token:{jti}")) > 0
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
        payload = cast(
            "dict[str, Any]",
            jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM]),
        )
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
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency that returns the authenticated user.

    Reads the JWT from the HttpOnly cookie first, then the Authorization
    header, decodes it, and loads the matching user from the database.

    Args:
        request: FastAPI request object.
        db: Database session.

    Returns:
        Authenticated User instance.

    Raises:
        HTTPException: 401 if the token is missing, invalid, expired,
            or the user does not exist / is inactive.
    """
    token = _get_access_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
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

    if (
        user.sessions_invalidated_at is not None
        and payload.get("iat") is not None
        and datetime.fromtimestamp(payload["iat"], tz=UTC).replace(tzinfo=None)
        < user.sessions_invalidated_at
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been invalidated. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Email not verified. Please check your inbox or request a new "
                "verification email."
            ),
        )

    return user


def get_optional_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Return the authenticated user, or None if no/invalid token is provided.

    This dependency is useful for endpoints that support both authenticated
    users and BYOK (bring-your-own-key) traffic.
    """
    token = _get_access_token_from_request(request)
    if not token:
        return None
    try:
        payload = decode_access_token(token)
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
    token_issued_at: datetime | None = None


def get_current_user_or_byok(
    request: Request,
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> RequestIdentity:
    """Resolve a request identity from either a JWT cookie or a BYOK API key header.

    Standard users authenticate with the HttpOnly `access_token` cookie (or a
    Bearer token for programmatic use) and must have a verified email address.
    BYOK users authenticate with X-API-Key: <openai-key>.
    """
    if x_api_key and x_api_key.strip():
        api_key = x_api_key.strip()
        return RequestIdentity(
            user_id=QuotaManager.byok_user_id(api_key),
            is_byok=True,
            api_key=api_key,
        )

    token = _get_access_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Authentication required. Provide a Bearer token or X-API-Key header."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

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

    if (
        user.sessions_invalidated_at is not None
        and payload.get("iat") is not None
        and datetime.fromtimestamp(payload["iat"], tz=UTC).replace(tzinfo=None)
        < user.sessions_invalidated_at
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has been invalidated. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Email not verified. Please check your inbox or request a new "
                "verification email."
            ),
        )

    token_issued_at = None
    if payload.get("iat") is not None:
        token_issued_at = datetime.fromtimestamp(payload["iat"], tz=UTC).replace(
            tzinfo=None
        )

    return RequestIdentity(
        user_id=user.id,
        is_byok=False,
        user=user,
        token_issued_at=token_issued_at,
    )
