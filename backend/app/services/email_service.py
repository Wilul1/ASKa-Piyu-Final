"""Transactional email sending (Resend) for account email verification.

Kept deliberately small: one provider (Resend), one use case (verification
codes). If ASKA_RESEND_API_KEY is unset, sending is a no-op that returns False
so callers can degrade gracefully (signup still succeeds; the user can request
a resend once a key is configured).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
_CODE_DIGITS = 6


def generate_verification_code() -> str:
    """Six-digit numeric one-time code, e.g. '042917'."""
    return f"{secrets.randbelow(10**_CODE_DIGITS):0{_CODE_DIGITS}d}"


def hash_verification_code(code: str) -> str:
    return hashlib.sha256(code.strip().encode("utf-8")).hexdigest()


def verification_expiry(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    return base + timedelta(minutes=settings.email_verification_code_ttl_minutes)


def send_verification_email(*, to_email: str, full_name: str, code: str) -> bool:
    """Best-effort send. Returns True on success, False on any failure
    (missing API key, network error, non-2xx from Resend) — never raises,
    so a flaky email provider never breaks signup/resend requests.
    """
    api_key = (settings.resend_api_key or "").strip()
    if not api_key:
        logger.warning("Skipping verification email (ASKA_RESEND_API_KEY not set): %s", to_email)
        return False

    subject = "Verify your ASKa-Piyu account"
    first_name = (full_name or "").strip().split(" ")[0] or "there"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto;">
      <h2 style="color: #7a1f2b;">ASKa-Piyu</h2>
      <p>Hi {first_name},</p>
      <p>Use this code to verify your email address:</p>
      <p style="font-size: 32px; font-weight: bold; letter-spacing: 4px; text-align: center;
                background: #f5f5f5; padding: 16px; border-radius: 8px;">{code}</p>
      <p>This code expires in {settings.email_verification_code_ttl_minutes} minutes.</p>
      <p style="color: #777; font-size: 13px;">
        If you didn't create an ASKa-Piyu account, you can safely ignore this email.
      </p>
    </div>
    """.strip()

    try:
        response = httpx.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.resend_from_email,
                "to": [to_email],
                "subject": subject,
                "html": html,
            },
            timeout=15,
        )
        if response.status_code >= 400:
            logger.warning(
                "Resend verification email failed (status=%s): %s",
                response.status_code,
                response.text[:300],
            )
            return False
        return True
    except httpx.HTTPError:
        logger.exception("Resend verification email request failed for %s", to_email)
        return False
