"""Transactional email for account verification codes.

Prefers Gmail/SMTP when ASKA_SMTP_* is set (works without a custom domain and
can deliver to any recipient). Falls back to Resend HTTP API when SMTP is
unset. If neither is configured, sending is a no-op that returns False so
signup still succeeds.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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


def _verification_subject() -> str:
    # Avoid "Verify your account" phrasing — Gmail often treats that like phishing.
    return "Your ASKa-Piyu email code"


def _verification_plain(*, full_name: str, code: str) -> str:
    first_name = (full_name or "").strip().split(" ")[0] or "there"
    ttl = settings.email_verification_code_ttl_minutes
    return (
        f"Hi {first_name},\n\n"
        "Thanks for signing up for ASKa-Piyu (Laguna State Polytechnic University "
        "student support).\n\n"
        f"Your email verification code is: {code}\n\n"
        f"This code expires in {ttl} minutes.\n\n"
        "If you did not create an ASKa-Piyu account, you can ignore this message.\n"
    )


def _verification_html(*, full_name: str, code: str) -> str:
    first_name = (full_name or "").strip().split(" ")[0] or "there"
    ttl = settings.email_verification_code_ttl_minutes
    return f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 480px; margin: 0 auto; color: #222;">
      <p style="font-size: 18px; font-weight: bold; color: #7a1f2b; margin: 0 0 16px;">ASKa-Piyu</p>
      <p>Hi {first_name},</p>
      <p>Thanks for signing up for ASKa-Piyu, the campus support assistant for
         Laguna State Polytechnic University.</p>
      <p>Your email verification code:</p>
      <p style="font-size: 28px; font-weight: bold; letter-spacing: 3px; font-family: Consolas, monospace;">{code}</p>
      <p>This code expires in {ttl} minutes.</p>
      <p style="color: #666; font-size: 13px;">
        If you did not create an ASKa-Piyu account, you can ignore this message.
      </p>
    </div>
    """.strip()


def _build_verification_message(*, to_email: str, full_name: str, code: str, from_addr: str) -> MIMEMultipart:
    message = MIMEMultipart("alternative")
    message["Subject"] = _verification_subject()
    message["From"] = f"ASKa-Piyu <{from_addr}>"
    message["To"] = to_email
    message["Reply-To"] = from_addr
    message["Auto-Submitted"] = "auto-generated"
    message["X-Auto-Response-Suppress"] = "All"
    message.attach(MIMEText(_verification_plain(full_name=full_name, code=code), "plain", "utf-8"))
    message.attach(MIMEText(_verification_html(full_name=full_name, code=code), "html", "utf-8"))
    return message


def _smtp_configured() -> bool:
    host = (settings.smtp_host or "").strip()
    user = (settings.smtp_username or "").strip()
    password = (settings.smtp_password or "").strip()
    return bool(host and user and password)


def _send_via_smtp(*, to_email: str, full_name: str, code: str) -> bool:
    host = (settings.smtp_host or "").strip()
    username = (settings.smtp_username or "").strip()
    password = (settings.smtp_password or "").strip()
    from_addr = (settings.smtp_from_email or username).strip()
    port = int(settings.smtp_port or 587)
    message = _build_verification_message(
        to_email=to_email,
        full_name=full_name,
        code=code,
        from_addr=from_addr,
    )

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            if bool(settings.smtp_use_tls):
                server.starttls()
                server.ehlo()
            server.login(username, password)
            server.sendmail(from_addr, [to_email], message.as_string())
        return True
    except Exception:
        logger.exception("SMTP verification email failed for %s", to_email)
        return False


def _send_via_resend(*, to_email: str, full_name: str, code: str) -> bool:
    api_key = (settings.resend_api_key or "").strip()
    if not api_key:
        return False

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
                "subject": _verification_subject(),
                "text": _verification_plain(full_name=full_name, code=code),
                "html": _verification_html(full_name=full_name, code=code),
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


def send_verification_email(*, to_email: str, full_name: str, code: str) -> bool:
    """Best-effort send. Returns True on success, False on any failure — never raises."""
    if _smtp_configured():
        return _send_via_smtp(to_email=to_email, full_name=full_name, code=code)

    api_key = (settings.resend_api_key or "").strip()
    if api_key:
        return _send_via_resend(to_email=to_email, full_name=full_name, code=code)

    logger.warning(
        "Skipping verification email (neither ASKA_SMTP_* nor ASKA_RESEND_API_KEY set): %s",
        to_email,
    )
    return False
