"""Email helpers powered by Resend.

All send functions are intentionally fire-and-forget from the caller's
perspective: they log errors but never raise, so a failing email cannot break
a user-facing operation.
"""

from __future__ import annotations

import logging
from typing import Any

import resend

from app.core.config import settings

logger = logging.getLogger(__name__)

# Configure the Resend SDK once at import time.
resend.api_key = settings.RESEND_API_KEY or ""


def _from_email() -> str:
    """Return the configured sender address with a display name."""
    address = settings.RESEND_FROM_EMAIL
    if "<" in address and ">" in address:
        return address
    return f"TermSub <{address}>"


def _send_email(
    to_email: str,
    subject: str,
    html_body: str,
    idempotency_key: str | None = None,
) -> dict[str, Any] | None:
    """Send a single HTML email via Resend, logging any errors.

    Kept as a private fallback for non-templated flows (password reset,
    product broadcasts). New user-facing flows should use Resend templates via
    ``send_templated_email``.
    """
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured; skipping email to %s", to_email)
        return None

    try:
        params: dict[str, Any] = {
            "from": _from_email(),
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }
        # The idempotency_key is intentionally not passed to resend.Emails.send
        # because the installed SDK version does not accept it. Keeping the
        # parameter in the signature preserves backwards compatibility for
        # callers that may supply it.
        del idempotency_key

        return resend.Emails.send(params)
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to_email, exc, exc_info=True)
        return None


def send_templated_email(
    to_email: str,
    subject: str,
    template_alias: str,
    data_dict: dict[str, Any],
) -> dict[str, Any] | None:
    """Send a single templated email via Resend, logging any errors."""
    if not settings.RESEND_API_KEY:
        logger.warning(
            "RESEND_API_KEY not configured; skipping templated email to %s", to_email
        )
        return None

    try:
        params: dict[str, Any] = {
            "from": _from_email(),
            "to": [to_email],
            "subject": subject,
            "template": template_alias,
            "data": data_dict,
        }
        return resend.Emails.send(params)
    except Exception as exc:
        logger.error(
            "Failed to send templated email to %s: %s", to_email, exc, exc_info=True
        )
        return None


def send_verification_email(to_email: str, verify_url: str) -> dict[str, Any] | None:
    """Send an email verification link with inline HTML."""
    html = f"""
    <html>
      <body style="font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1f2937; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 24px;">
        <h1 style="color: #111827; font-size: 24px; margin-bottom: 16px;">Verify your email for TermSub</h1>
        <p>Hi there,</p>
        <p>Thanks for signing up. Please click the button below to verify your email address and activate your account:</p>
        <p style="margin: 32px 0;">
          <a href="{verify_url}" style="display: inline-block; background-color: #2563eb; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 600;">Verify email</a>
        </p>
        <p style="font-size: 14px; color: #6b7280;">If the button doesn't work, paste this link into your browser:<br><a href="{verify_url}" style="color: #2563eb;">{verify_url}</a></p>
        <p style="margin-top: 32px;">If you did not create a TermSub account, you can safely ignore this email.</p>
      </body>
    </html>
    """
    return _send_email(
        to_email,
        "Verify your email for TermSub",
        html,
        idempotency_key=f"verify/{to_email}",
    )


def send_welcome_email(to_email: str, app_url: str) -> dict[str, Any] | None:
    """Send the post-verification welcome email with inline HTML."""
    html = f"""
    <html>
      <body style="font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1f2937; line-height: 1.6; max-width: 600px; margin: 0 auto; padding: 24px;">
        <h1 style="color: #111827; font-size: 24px; margin-bottom: 16px;">Welcome to TermSub beta</h1>
        <p>Hi there,</p>
        <p>Welcome to TermSub beta. You've got <strong>30 free minutes</strong> of video translation to start with.</p>
        <p><strong>What TermSub does:</strong> Upload any video, audio, or text/SRT file and let the AI* transcribe, analyze, and translate it into subtitle files — with full control over terminology, editable subtitle cards, and it's exportable in minutes** from and to 59 languages.</p>
        <p><strong>Why TermSub is different:</strong> Unlike standard translators, TermSub reads the full context of your video, not sentence by sentence, so translations stay consistent and accurate, even for specialized topics or longer videos.</p>
        <p><strong>You're a beta tester, invited to test the app. If something breaks, feels slow, or could be better — just reply to this email.</strong></p>
        <p style="margin: 32px 0;">
          <a href="{app_url}" style="display: inline-block; background-color: #2563eb; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 600;">Open TermSub</a>
        </p>
        <p style="font-size: 14px; color: #6b7280;">If the button doesn't work, paste this link into your browser:<br><a href="{app_url}" style="color: #2563eb;">{app_url}</a></p>
        <p style="font-size: 13px; color: #6b7280; margin-top: 24px;">
          *AI processing (transcription, analysis, and translation) is powered by OpenAI.<br>
          **a feature film can be subtitled (with good quality and still under your control) in less than 10 minutes.
        </p>
        <p style="margin-top: 32px;">— seaweed</p>
      </body>
    </html>
    """
    return _send_email(
        to_email,
        "Welcome to TermSub beta",
        html,
        idempotency_key=f"welcome/{to_email}",
    )


def send_password_reset_email(
    to_email: str,
    reset_token: str,
) -> dict[str, Any] | None:
    """Send a password reset link."""
    reset_url = f"{settings.FRONTEND_BASE_URL}/app?reset_token={reset_token}"
    html = f"""
    <html>
      <body>
        <h1>Reset your TermSub password</h1>
        <p>Click the link below to choose a new password. This link expires in 24 hours.</p>
        <p><a href="{reset_url}">{reset_url}</a></p>
        <p>If you did not request a password reset, you can safely ignore this email.</p>
      </body>
    </html>
    """
    return _send_email(
        to_email,
        "Reset your TermSub password",
        html,
        idempotency_key=f"password-reset/{to_email}/{reset_token[:16]}",
    )


def broadcast_product_update(
    subject: str,
    html_body: str,
    recipient_emails: list[str],
) -> list[dict[str, Any]]:
    """Send a product update to many recipients via Resend's batch API.

    Automatically chunks the list into batches of 100 (Resend's limit) and
    returns the combined results. Errors are logged and do not raise.
    """
    if not settings.RESEND_API_KEY:
        logger.warning(
            "RESEND_API_KEY not configured; skipping broadcast to %d recipients",
            len(recipient_emails),
        )
        return []

    if not recipient_emails:
        return []

    BATCH_SIZE = 100
    results: list[dict[str, Any]] = []

    for batch_index in range(0, len(recipient_emails), BATCH_SIZE):
        chunk = recipient_emails[batch_index : batch_index + BATCH_SIZE]
        emails = [
            {
                "from": _from_email(),
                "to": [email],
                "subject": subject,
                "html": html_body,
            }
            for email in chunk
        ]

        try:
            batch_result = resend.Batch.send(emails)
            if batch_result:
                results.append(batch_result)
        except Exception as exc:
            logger.error(
                "Failed to send broadcast batch %d-%d: %s",
                batch_index,
                batch_index + len(chunk),
                exc,
                exc_info=True,
            )

    return results
