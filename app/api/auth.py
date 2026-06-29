"""Authentication API router."""

import logging
import threading
from datetime import UTC, datetime, timedelta

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import literal
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_user
from app.core.auth import (
    create_access_token,
    generate_verification_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.core.config import settings
from app.core.email import (
    send_password_reset_email,
    send_verification_email,
    send_welcome_email,
)
from app.core.rate_limit import rate_limit
from app.core.redis_pubsub import get_sync_redis_client
from app.db.session import SessionLocal, get_db
from app.models.newsletter import NewsletterSignup
from app.models.user import User

logger = logging.getLogger(__name__)
from app.schemas.auth import (
    BYOKStartRequest,
    BYOKStartResponse,
    ForgotPasswordRequest,
    NewsletterSubscriberOut,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserLoginRequest,
    UserResponse,
    UserSignupRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _record_newsletter_signup(email: str, source: str) -> None:
    """Add an email to the newsletter list, suppressing duplicate errors."""
    try:
        with SessionLocal() as db:
            existing = (
                db.query(NewsletterSignup)
                .filter(NewsletterSignup.email == email)
                .first()
            )
            if not existing:
                db.add(NewsletterSignup(email=email, source=source))
                db.commit()
    except Exception as exc:
        logger.error("Failed to record newsletter signup for %s: %s", email, exc)


def _send_signup_emails(email: str, verify_url: str, wants_updates: bool) -> None:
    """Send the verification email and opt the user into product updates.

    Runs in a background thread so signup stays fast and never fails because
    of an email/network issue. The welcome email is sent later, after the user
    verifies their email address.
    """
    send_verification_email(email, verify_url)
    if wants_updates:
        _record_newsletter_signup(email, source="signup")


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@rate_limit("signup", limit=3, window=3600, identifier="ip")
def signup(
    payload: UserSignupRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Register a new user account and return a JWT access token."""
    email = payload.email.strip().lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        wants_updates=payload.wants_updates,
        api_key_mode="standard",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    verification_token = generate_verification_token()
    user.email_verification_token = verification_token
    user.email_verification_token_expires_at = datetime.utcnow() + timedelta(hours=24)
    db.commit()

    verify_url = f"{settings.FRONTEND_BASE_URL}/?token={verification_token}"

    # Fire verification email and optional newsletter signup in the background.
    threading.Thread(
        target=_send_signup_emails,
        args=(user.email, verify_url, user.wants_updates),
        daemon=True,
    ).start()

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
@rate_limit("login", limit=5, window=900, identifier="email")
def login(
    payload: UserLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate a user and return a JWT access token."""
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)) -> dict[str, str]:
    """Verify a user's email address using the token sent by email."""
    user = db.query(User).filter(User.email_verification_token == token).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    if (
        user.email_verification_token_expires_at is None
        or user.email_verification_token_expires_at < datetime.utcnow()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification link expired",
        )

    was_already_verified = user.is_email_verified
    user.is_email_verified = True
    user.email_verification_token = None
    user.email_verification_token_expires_at = None
    db.commit()

    # Send the welcome email only the first time the user verifies.
    if not was_already_verified:
        app_url = settings.FRONTEND_BASE_URL
        threading.Thread(
            target=send_welcome_email,
            args=(user.email, app_url),
            daemon=True,
        ).start()

    return {"message": "Email verified successfully. You can now use TermSub."}


@router.post("/resend-verification")
@rate_limit("resend-verification", limit=5, window=900, identifier="email")
def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Resend the verification email for an unverified standard user."""
    email = payload.email.strip().lower()
    cooldown_key = f"resend_cooldown:{email}"

    try:
        redis = get_sync_redis_client()
        if redis.exists(cooldown_key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Please wait 60 seconds before requesting another "
                    "verification email."
                ),
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Redis cooldown check failed for %s: %s", email, exc)

    user = db.query(User).filter(User.email == email).first()
    if not user or user.is_email_verified:
        # Do not reveal whether the email exists or is already verified.
        return {"message": "If an unverified account exists, a verification email has been sent."}

    verification_token = generate_verification_token()
    user.email_verification_token = verification_token
    user.email_verification_token_expires_at = datetime.utcnow() + timedelta(hours=24)
    db.commit()

    verify_url = f"{settings.FRONTEND_BASE_URL}/?token={verification_token}"
    threading.Thread(
        target=send_verification_email,
        args=(user.email, verify_url),
        daemon=True,
    ).start()

    try:
        redis = get_sync_redis_client()
        redis.setex(cooldown_key, 60, "1")
    except Exception as exc:
        logger.warning("Failed to set resend cooldown for %s: %s", email, exc)

    return {"message": "If an unverified account exists, a verification email has been sent."}


@router.post("/forgot-password")
@rate_limit("forgot-password", limit=3, window=3600, identifier="ip")
def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Request a password reset email.

    Always returns the same message to avoid disclosing whether an email
    address is registered.
    """
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()

    if user:
        reset_token = generate_verification_token()
        user.password_reset_token = reset_token
        user.password_reset_token_expires_at = datetime.utcnow() + timedelta(hours=24)
        db.commit()

        threading.Thread(
            target=send_password_reset_email,
            args=(user.email, reset_token),
            daemon=True,
        ).start()

    return {"message": "If an account exists, a password reset email has been sent."}


@router.post("/reset-password")
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Reset the user's password using a valid reset token."""
    user = (
        db.query(User).filter(User.password_reset_token == payload.reset_token).first()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    if (
        user.password_reset_token_expires_at is None
        or user.password_reset_token_expires_at < datetime.utcnow()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link expired.",
        )

    user.password_hash = hash_password(payload.new_password)
    user.password_reset_token = None
    user.password_reset_token_expires_at = None
    db.commit()

    return {"message": "Password reset successfully. You can now log in."}


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    """Return information about the currently authenticated user."""
    return current_user


logout_security = HTTPBearer()


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(logout_security),
) -> dict[str, str]:
    """Revoke the current JWT by adding its jti to the Redis blocklist.

    The blocklist entry TTL is the token's remaining lifetime, so the token
    cannot be used until it naturally expires.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        # If the token is malformed, there is nothing to revoke.
        return {"message": "Logged out successfully."}

    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        now = datetime.now(UTC).timestamp()
        ttl = max(0, int(exp - now))
        if ttl > 0:
            try:
                redis = get_sync_redis_client()
                redis.setex(f"revoked_token:{jti}", ttl, "1")
            except Exception as exc:
                logger.warning("Failed to store revoked token in Redis: %s", exc)

    return {"message": "Logged out successfully."}


def _validate_openai_api_key(api_key: str) -> bool:
    """Make a lightweight test call to OpenAI to verify an API key."""
    try:
        response = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        return response.status_code == 200
    except Exception:
        return False


@router.post("/byok-start", response_model=BYOKStartResponse)
@rate_limit("byok-start", limit=3, window=3600, identifier="ip")
def byok_start(
    payload: BYOKStartRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> BYOKStartResponse:
    """Validate a BYOK OpenAI API key and optionally record a newsletter signup.

    This endpoint does not create a password-backed account. The caller is
    expected to store the validated API key securely (e.g. localStorage) and
    send it with subsequent requests that need OpenAI services.
    """
    if not _validate_openai_api_key(payload.api_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The provided OpenAI API key could not be validated",
        )

    if payload.email:
        existing_signup = (
            db.query(NewsletterSignup)
            .filter(NewsletterSignup.email == payload.email)
            .first()
        )
        existing_user = (
            db.query(User).filter(User.email == payload.email).first()
        )
        if not existing_signup and not existing_user:
            signup = NewsletterSignup(email=payload.email, source="byok")
            db.add(signup)
            db.commit()

    return BYOKStartResponse(valid=True, message="OpenAI API key is valid")


@router.get("/newsletter-signups", response_model=list[NewsletterSubscriberOut])
def list_newsletter_signups(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> list[NewsletterSubscriberOut]:
    """Return all newsletter subscribers from standard signups and BYOK signups."""
    standard_subscribers = (
        db.query(
            User.email.label("email"),
            literal("signup").label("source"),
            User.created_at.label("created_at"),
        )
        .filter(User.wants_updates.is_(True))
    )

    byok_subscribers = (
        db.query(
            NewsletterSignup.email.label("email"),
            NewsletterSignup.source.label("source"),
            NewsletterSignup.created_at.label("created_at"),
        )
    )

    results = (
        standard_subscribers.union(byok_subscribers)
        .order_by("created_at")
        .all()
    )

    return [
        NewsletterSubscriberOut(
            email=row.email,
            source=row.source,
            created_at=row.created_at,
        )
        for row in results
    ]
