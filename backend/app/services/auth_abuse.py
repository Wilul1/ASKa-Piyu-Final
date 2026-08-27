"""Persist and evaluate auth abuse signals (signup / login velocity by IP)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.db_models import AuthEvent, User, utc_now

# Soft thresholds — flag for admin review, do not auto-ban.
SIGNUP_IP_LIMIT_24H = 5
LOGIN_FAIL_IP_LIMIT_1H = 15

EVENT_SIGNUP = "signup"
EVENT_LOGIN_OK = "login_ok"
EVENT_LOGIN_FAIL = "login_fail"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def record_auth_event(
    session: Session,
    *,
    event_type: str,
    ip_address: str,
    email: str | None = None,
    user_id: str | None = None,
    user_agent: str | None = None,
    commit: bool = True,
) -> AuthEvent:
    """Best-effort persist. Never raises to callers for commit failures after add."""
    normalized_email = (email or "").strip().lower() or None
    ua = (user_agent or "").strip()
    if len(ua) > 512:
        ua = ua[:512]
    item = AuthEvent(
        event_type=event_type,
        email=normalized_email,
        user_id=user_id,
        ip_address=(ip_address or "unknown").strip()[:80] or "unknown",
        user_agent=ua or None,
        created_at=utc_now(),
    )
    session.add(item)
    if commit:
        session.commit()
        session.refresh(item)
    return item


def list_abuse_flags(session: Session) -> list[dict[str, Any]]:
    """Compute current abuse flags from recent auth events."""
    now = utc_now()
    flags: list[dict[str, Any]] = []

    signup_since = now - timedelta(hours=24)
    signup_rows = (
        session.query(AuthEvent.ip_address, func.count(AuthEvent.id), func.max(AuthEvent.created_at))
        .filter(
            AuthEvent.event_type == EVENT_SIGNUP,
            AuthEvent.created_at >= signup_since,
        )
        .group_by(AuthEvent.ip_address)
        .having(func.count(AuthEvent.id) >= SIGNUP_IP_LIMIT_24H)
        .all()
    )
    for ip, count, latest in signup_rows:
        flags.append(
            _flag_payload(
                session,
                kind="signup_velocity",
                ip_address=str(ip),
                count=int(count),
                window_hours=24,
                reason=f"{int(count)} signups from this IP in 24 hours",
                latest_at=latest,
                event_type=EVENT_SIGNUP,
                since=signup_since,
            )
        )

    fail_since = now - timedelta(hours=1)
    fail_rows = (
        session.query(AuthEvent.ip_address, func.count(AuthEvent.id), func.max(AuthEvent.created_at))
        .filter(
            AuthEvent.event_type == EVENT_LOGIN_FAIL,
            AuthEvent.created_at >= fail_since,
        )
        .group_by(AuthEvent.ip_address)
        .having(func.count(AuthEvent.id) >= LOGIN_FAIL_IP_LIMIT_1H)
        .all()
    )
    for ip, count, latest in fail_rows:
        flags.append(
            _flag_payload(
                session,
                kind="login_fail_velocity",
                ip_address=str(ip),
                count=int(count),
                window_hours=1,
                reason=f"{int(count)} failed logins from this IP in 1 hour",
                latest_at=latest,
                event_type=EVENT_LOGIN_FAIL,
                since=fail_since,
            )
        )

    flags.sort(key=lambda item: item.get("latest_at") or "", reverse=True)
    return flags


def _flag_payload(
    session: Session,
    *,
    kind: str,
    ip_address: str,
    count: int,
    window_hours: int,
    reason: str,
    latest_at: datetime | None,
    event_type: str,
    since: datetime,
) -> dict[str, Any]:
    related = _related_users_for_ip(session, ip_address=ip_address, since=since)
    latest_iso = ""
    if latest_at is not None:
        latest_iso = _as_utc(latest_at).isoformat()
    return {
        "kind": kind,
        "ip_address": ip_address,
        "count": count,
        "window_hours": window_hours,
        "reason": reason,
        "latest_at": latest_iso,
        "related_users": related,
        "event_type": event_type,
    }


def _related_users_for_ip(
    session: Session,
    *,
    ip_address: str,
    since: datetime,
) -> list[dict[str, Any]]:
    user_ids = {
        row[0]
        for row in session.query(AuthEvent.user_id)
        .filter(
            AuthEvent.ip_address == ip_address,
            AuthEvent.created_at >= since,
            AuthEvent.user_id.isnot(None),
        )
        .distinct()
        .all()
        if row[0]
    }
    emails = {
        row[0]
        for row in session.query(AuthEvent.email)
        .filter(
            AuthEvent.ip_address == ip_address,
            AuthEvent.created_at >= since,
            AuthEvent.email.isnot(None),
        )
        .distinct()
        .all()
        if row[0]
    }
    users: list[User] = []
    if user_ids:
        users.extend(session.query(User).filter(User.id.in_(user_ids)).all())
    if emails:
        found = session.query(User).filter(User.email.in_(emails)).all()
        seen = {u.id for u in users}
        for user in found:
            if user.id not in seen:
                users.append(user)
                seen.add(user.id)
    users.sort(key=lambda u: u.created_at or utc_now(), reverse=True)
    return [
        {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "is_active": bool(getattr(user, "is_active", True)),
        }
        for user in users[:20]
    ]


def list_auth_events(
    session: Session,
    *,
    ip_address: str | None = None,
    limit: int = 50,
) -> list[AuthEvent]:
    query = session.query(AuthEvent).order_by(AuthEvent.created_at.desc())
    if ip_address:
        query = query.filter(AuthEvent.ip_address == ip_address.strip())
    return query.limit(max(1, min(limit, 200))).all()


def auth_event_to_dict(item: AuthEvent) -> dict[str, Any]:
    return {
        "id": item.id,
        "event_type": item.event_type,
        "email": item.email,
        "user_id": item.user_id,
        "ip_address": item.ip_address,
        "user_agent": item.user_agent,
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }
